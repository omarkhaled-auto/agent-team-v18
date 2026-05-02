"""Phase 5 closeout — 5.6c Prisma generate pre-step parity gap.

Closes the asymmetry between the 5.6b Docker compose path (which runs
``prisma generate`` inside ``apps/api/Dockerfile`` before ``tsc``) and
the 5.6c host strict-compile profile (which historically ran
``npx tsc --noEmit --project ...`` with no Prisma pre-step).

Canonical evidence: ``v18 test runs/phase-5-8a-stage-2b-rerun3-clean-
20260501-231647-daa0e90-01-20260501-231704/.agent-team/milestones/
milestone-1/wave_B_self_verify_error.txt`` carries ::

    src/database/prisma.service.ts:2 TS2305 Module '"@prisma/client"' has no
        exported member 'PrismaClient'.
    src/database/prisma.service.ts:10 TS2339 Property '$connect' does not
        exist on type 'PrismaService'.

while the same artifact's ``BUILD_LOG.txt`` (line ~512) shows 5.6b
project-scope Docker build PASSED on the same generated source. The
asymmetry is the signal: ``apps/api/Dockerfile`` runs ``prisma
generate`` so ``node_modules/.prisma/client/default.d.ts`` is
materialised before ``tsc`` parses ``import { PrismaClient } from
'@prisma/client'``; the host 5.6c path lacked that pre-step, so the
re-export stub at ``node_modules/@prisma/client/index.d.ts``
(``export * from '.prisma/client/default'``) had no target.

These tests verify:

* **No-op contract** — when no ``schema.prisma`` is present anywhere
  under the project root, the pre-step does NOT invoke ``npx`` and
  does NOT contaminate the result. ``CompileResult`` is byte-identical
  to pre-fix behaviour.
* **Order contract** — when a schema IS present, ``prisma generate``
  runs BEFORE every ``tsc`` command in the profile.
* **Layout coverage** — both root-level (``prisma/schema.prisma``)
  and monorepo (``apps/api/prisma/schema.prisma``) layouts are
  detected; multiple schemas each get their own generate.
* **Failure surface** — a non-zero ``prisma generate`` exit results
  in a 5.6c stage failure with code ``PRISMA_GENERATE_FAILED`` and a
  readable error message that includes the schema path and stderr
  excerpt. NOT silently swallowed; tsc commands are SKIPPED so the
  cascade of derivative TS2305 errors does not drown the real
  diagnostic.
* **Env-unavailability propagation** — when ``npx`` is missing
  (``FileNotFoundError``), the pre-step emits ``MISSING_COMMAND``
  which is in the env-unavailability set used by
  :func:`agent_team_v15.unified_build_gate.is_compile_env_unavailable`,
  preserving the existing ``tsc_env_unavailable`` semantics.
* **Timeout surface** — a hung ``prisma generate`` produces a bounded
  ``TIMEOUT`` error rather than blocking the gate forever.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_team_v15 import compile_profiles
from agent_team_v15.compile_profiles import (
    CompileProfile,
    CompileResult,
    _PRISMA_GENERATE_TIMEOUT_S,
    _discover_prisma_schemas,
    _run_prisma_generate_if_needed,
    run_wave_compile_check,
)
from agent_team_v15.unified_build_gate import (
    is_compile_env_unavailable,
    run_compile_profile_sync,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_schema(path: Path, *, with_models: bool = True) -> Path:
    """Write a minimal ``schema.prisma`` so detection finds the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "generator client {\n"
        '  provider = "prisma-client-js"\n'
        "}\n\n"
        'datasource db {\n'
        '  provider = "postgresql"\n'
        '  url      = env("DATABASE_URL")\n'
        "}\n"
    )
    if with_models:
        body += (
            "\nmodel User {\n"
            "  id Int @id @default(autoincrement())\n"
            "  email String @unique\n"
            "}\n"
        )
    path.write_text(body, encoding="utf-8")
    return path


def _make_tsconfig_only_profile(tmp_path: Path) -> CompileProfile:
    """Build a profile with two tsc invocations (mirrors monorepo wiring)."""
    api_ts = tmp_path / "apps" / "api" / "tsconfig.json"
    web_ts = tmp_path / "apps" / "web" / "tsconfig.json"
    for ts in (api_ts, web_ts):
        ts.parent.mkdir(parents=True, exist_ok=True)
        ts.write_text("{}\n", encoding="utf-8")
    return CompileProfile(
        name="test_profile",
        commands=[
            ["npx", "tsc", "--noEmit", "--pretty", "false", "--project", str(api_ts)],
            ["npx", "tsc", "--noEmit", "--pretty", "false", "--project", str(web_ts)],
        ],
        description="test profile (api + web)",
    )


class _RunRecorder:
    """Substitute for :func:`compile_profiles._run_command`.

    Records each ``(cmd, cwd, timeout)`` invocation for ordering and
    cwd assertions. Each entry's response can be customised via
    ``responses`` (list of ``(returncode, output)`` tuples). When the
    list is exhausted, returns ``(0, "")``.
    """

    def __init__(
        self,
        responses: list[tuple[int, str]] | None = None,
        *,
        raise_on_match: dict[str, BaseException] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])
        self._raise_on_match = raise_on_match or {}

    async def __call__(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int = 120,
    ) -> tuple[int, str]:
        record = {
            "cmd": list(cmd),
            "cwd": str(cwd),
            "timeout": timeout,
        }
        self.calls.append(record)
        joined = " ".join(cmd)
        for needle, exc in self._raise_on_match.items():
            if needle in joined:
                raise exc
        if self._responses:
            return self._responses.pop(0)
        return (0, "")


# ---------------------------------------------------------------------------
# (a) Schema discovery + (b) no-op when no schema
# ---------------------------------------------------------------------------


def test_discover_prisma_schemas_returns_empty_when_no_schema(
    tmp_path: Path,
) -> None:
    """``_discover_prisma_schemas`` returns ``[]`` for a tree without
    ``schema.prisma``."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("export const x = 1;\n", encoding="utf-8")
    assert _discover_prisma_schemas(tmp_path) == []


def test_discover_prisma_schemas_finds_root_layout(tmp_path: Path) -> None:
    """Root-level ``prisma/schema.prisma`` is discovered."""
    schema = _write_schema(tmp_path / "prisma" / "schema.prisma")
    found = _discover_prisma_schemas(tmp_path)
    assert len(found) == 1
    assert found[0].resolve() == schema.resolve()


def test_discover_prisma_schemas_finds_monorepo_layout(tmp_path: Path) -> None:
    """``apps/api/prisma/schema.prisma`` (monorepo layout) is discovered."""
    schema = _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    found = _discover_prisma_schemas(tmp_path)
    assert len(found) == 1
    assert found[0].resolve() == schema.resolve()


def test_discover_prisma_schemas_skips_node_modules(tmp_path: Path) -> None:
    """Schemas inside ``node_modules/`` are pruned (Prisma ships fixtures).

    This is critical: the ``@prisma/engines-tests`` package ships its
    own example schemas; if we generated against them we would
    explode the per-wave time budget and risk false-positive failures.
    """
    _write_schema(
        tmp_path / "node_modules" / "@prisma" / "engines-tests" / "schema.prisma"
    )
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    found = _discover_prisma_schemas(tmp_path)
    assert len(found) == 1
    assert "node_modules" not in str(found[0])


def test_discover_prisma_schemas_finds_multiple(tmp_path: Path) -> None:
    """Multiple schemas (root + per-package) are all discovered."""
    _write_schema(tmp_path / "prisma" / "schema.prisma")
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    _write_schema(tmp_path / "packages" / "db" / "prisma" / "schema.prisma")
    found = _discover_prisma_schemas(tmp_path)
    assert len(found) == 3


@pytest.mark.asyncio
async def test_run_prisma_generate_if_needed_no_op_no_schema(
    tmp_path: Path,
) -> None:
    """No schema → no command issued, returns ``([], [])``."""
    errors, outputs = await _run_prisma_generate_if_needed(tmp_path)
    assert errors == []
    assert outputs == []


# ---------------------------------------------------------------------------
# (c) Pre-step ordering vs tsc + cwd resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_step_runs_before_tsc_when_schema_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prisma generate executes BEFORE every tsc command in the profile."""
    schema = _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    # Result clean when prisma + every tsc returns 0.
    assert result.passed is True
    assert result.errors == []

    # Three calls total: 1 prisma generate + 2 tsc invocations.
    assert len(recorder.calls) == 3

    # First call MUST be prisma generate.
    first = recorder.calls[0]
    assert first["cmd"][:3] == ["npx", "prisma", "generate"]
    assert "--schema" in first["cmd"]
    schema_idx = first["cmd"].index("--schema")
    assert Path(first["cmd"][schema_idx + 1]).resolve() == schema.resolve()
    # Generate timeout matches the dedicated 120s budget.
    assert first["timeout"] == _PRISMA_GENERATE_TIMEOUT_S
    # cwd is the package root that owns ``node_modules/`` (schema's
    # grandparent), so npx resolves the local prisma binary.
    assert (
        Path(first["cwd"]).resolve()
        == (tmp_path / "apps" / "api").resolve()
    )

    # Subsequent calls are tsc.
    for call in recorder.calls[1:]:
        assert call["cmd"][:2] == ["npx", "tsc"]


@pytest.mark.asyncio
async def test_pre_step_no_op_means_no_npx_call_when_schema_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no schema is present, the pre-step does NOT add ``npx prisma`` calls.

    Closes the operator's "be a no-op when no schema is present"
    requirement — tsc commands run unmodified.
    """
    profile = _make_tsconfig_only_profile(tmp_path)  # no schema written

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    # Exactly the two tsc commands. No prisma call.
    assert len(recorder.calls) == 2
    for call in recorder.calls:
        assert call["cmd"][:2] == ["npx", "tsc"]
        assert "prisma" not in " ".join(call["cmd"])


@pytest.mark.asyncio
async def test_multiple_schemas_each_get_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every discovered schema gets its own ``prisma generate`` call.

    Mirrors a workspace with both a root-level ``prisma/`` (e.g. shared
    types) and a per-package ``apps/api/prisma/``.
    """
    _write_schema(tmp_path / "prisma" / "schema.prisma")
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    # Two prisma + two tsc commands.
    prisma_calls = [c for c in recorder.calls if c["cmd"][:3] == ["npx", "prisma", "generate"]]
    tsc_calls = [c for c in recorder.calls if c["cmd"][:2] == ["npx", "tsc"]]
    assert len(prisma_calls) == 2
    assert len(tsc_calls) == 2

    # Both generate calls precede every tsc call (ordering invariant).
    last_prisma_index = max(
        i for i, c in enumerate(recorder.calls)
        if c["cmd"][:3] == ["npx", "prisma", "generate"]
    )
    first_tsc_index = min(
        i for i, c in enumerate(recorder.calls)
        if c["cmd"][:2] == ["npx", "tsc"]
    )
    assert last_prisma_index < first_tsc_index


# ---------------------------------------------------------------------------
# (d) Failure surface — not silently swallowed; tsc skipped to avoid noise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prisma_failure_surfaces_as_compile_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero ``prisma generate`` exit → CompileResult.passed=False, error
    code ``PRISMA_GENERATE_FAILED``, stderr in the message."""
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        responses=[
            (
                1,
                "Error: Prisma schema validation failed:\n"
                "  --> apps/api/prisma/schema.prisma\n"
                "Error code P1012: missing model attribute @id",
            ),
        ],
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err["code"] == "PRISMA_GENERATE_FAILED"
    # Schema path landed in the error; the stderr excerpt is preserved.
    assert "schema.prisma" in err["file"]
    assert "P1012" in err["message"]
    # tsc commands MUST be skipped when prisma generate fails — running
    # tsc without the generated client would only cascade derivative
    # TS2305 noise that drowns the real diagnostic.
    tsc_calls = [c for c in recorder.calls if c["cmd"][:2] == ["npx", "tsc"]]
    assert tsc_calls == []


@pytest.mark.asyncio
async def test_prisma_failure_truncates_long_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Long stderr is truncated so the retry payload stays bounded."""
    _write_schema(tmp_path / "prisma" / "schema.prisma")
    profile = CompileProfile(name="noop", commands=[["echo"]])

    huge_stderr = "Error: " + ("X" * 5000)
    recorder = _RunRecorder(responses=[(2, huge_stderr)])
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    err = result.errors[0]
    assert err["code"] == "PRISMA_GENERATE_FAILED"
    # Truncation marker present; message length bounded well under the
    # 12 KB retry-payload ceiling.
    assert "(truncated)" in err["message"]
    assert len(err["message"]) < 2000


# ---------------------------------------------------------------------------
# (d2) Env-unavailability propagation — preserves tsc_env_unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prisma_missing_npx_emits_missing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``npx`` is not installed, the pre-step emits ``MISSING_COMMAND``."""
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        raise_on_match={"prisma generate": FileNotFoundError("npx")},
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    assert result.errors[0]["code"] == "MISSING_COMMAND"


@pytest.mark.asyncio
async def test_prisma_missing_npx_classified_env_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MISSING_COMMAND`` from the prisma pre-step is classified as
    env-unavailable by :func:`unified_build_gate.is_compile_env_unavailable`,
    preserving the existing ``tsc_env_unavailable`` semantics."""
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        raise_on_match={"prisma generate": FileNotFoundError("npx")},
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    # Caller-side classification — same primitive Wave B/D self-verify use.
    assert is_compile_env_unavailable(result) is True


@pytest.mark.asyncio
async def test_prisma_real_failure_NOT_classified_env_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real ``prisma generate`` failure (P1012 schema error) is NOT
    treated as env-unavailable — operators see a wave failure, not a skip.

    Closes the "NOT silently swallowed" contract: real Codex authoring
    bugs (mis-typed schema field, missing model) MUST fail the wave so
    the retry loop / Quality Contract / cascade gate respond, not be
    suppressed via the env-unavailability escape hatch.
    """
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        responses=[(1, "Error: P1012 schema invalid")],
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    assert is_compile_env_unavailable(result) is False


# ---------------------------------------------------------------------------
# (d3) Timeout surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prisma_timeout_surfaces_as_compile_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung ``prisma generate`` produces a bounded ``TIMEOUT`` error."""
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        raise_on_match={"prisma generate": asyncio.TimeoutError()},
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    err = result.errors[0]
    assert err["code"] == "TIMEOUT"
    assert str(_PRISMA_GENERATE_TIMEOUT_S) in err["message"]
    # tsc skipped — same rationale as the PRISMA_GENERATE_FAILED path.
    tsc_calls = [c for c in recorder.calls if c["cmd"][:2] == ["npx", "tsc"]]
    assert tsc_calls == []


# ---------------------------------------------------------------------------
# (d4) End-to-end through the unified_build_gate sync bridge
# ---------------------------------------------------------------------------


def test_sync_bridge_propagates_prisma_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 5.6c sync bridge surfaces the prisma failure unchanged.

    Closes the end-to-end contract for the Wave B/D self-verify path:
    the structured error makes it through ``run_compile_profile_sync``
    so ``WaveBVerifyResult.tsc_failures`` populates and the retry
    payload sees the canonical schema diagnostic.
    """
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)
    monkeypatch.setattr(
        compile_profiles, "get_compile_profile",
        lambda *a, **kw: profile,
    )

    recorder = _RunRecorder(
        responses=[(1, "Error: Prisma schema validation failed: P1012")],
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = run_compile_profile_sync(
        cwd=str(tmp_path),
        wave_letter="B",
        project_root=tmp_path,
    )

    assert isinstance(result, CompileResult)
    assert result.passed is False
    assert any(e["code"] == "PRISMA_GENERATE_FAILED" for e in result.errors)


def test_sync_bridge_no_op_when_no_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 5.6c sync bridge stays clean when no schema is present.

    Pre-step is a no-op; tsc commands run normally; result.passed=True.
    """
    profile = _make_tsconfig_only_profile(tmp_path)
    monkeypatch.setattr(
        compile_profiles, "get_compile_profile",
        lambda *a, **kw: profile,
    )

    recorder = _RunRecorder()  # all clean returns
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = run_compile_profile_sync(
        cwd=str(tmp_path),
        wave_letter="B",
        project_root=tmp_path,
    )

    assert result.passed is True
    # No prisma call appeared.
    prisma_calls = [
        c for c in recorder.calls if c["cmd"][:3] == ["npx", "prisma", "generate"]
    ]
    assert prisma_calls == []
