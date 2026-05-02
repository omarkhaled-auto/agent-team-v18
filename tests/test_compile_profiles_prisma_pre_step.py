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
import json
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


def _write_pnpm_api_workspace(
    root: Path,
    *,
    root_schema: bool = True,
    app_schema: bool = False,
    app_prisma_config: bool = False,
) -> Path:
    """Create a pnpm monorepo fixture with an ``apps/api`` workspace."""
    (root / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "packageManager": "pnpm@9.0.0",
                "workspaces": ["apps/*"],
            }
        ),
        encoding="utf-8",
    )
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    api_dir = root / "apps" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "package.json").write_text(
        json.dumps({"name": "api", "dependencies": {"prisma": "^6.0.0"}}),
        encoding="utf-8",
    )
    prisma_bin = api_dir / "node_modules" / ".bin" / "prisma"
    prisma_bin.parent.mkdir(parents=True, exist_ok=True)
    prisma_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    if root_schema:
        _write_schema(root / "prisma" / "schema.prisma")
    if app_schema:
        _write_schema(api_dir / "prisma" / "schema.prisma")
    if app_prisma_config:
        (api_dir / "prisma.config.ts").write_text(
            "import { defineConfig } from 'prisma/config';\n"
            "export default defineConfig({ schema: 'prisma/schema.prisma' });\n",
            encoding="utf-8",
        )
    return api_dir


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
        extra_env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        record = {
            "cmd": list(cmd),
            "cwd": str(cwd),
            "timeout": timeout,
            "extra_env": dict(extra_env or {}),
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


@pytest.mark.asyncio
async def test_pnpm_workspace_config_prefers_package_schema_over_duplicate_root_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With root + package schemas, ``apps/api/prisma.config.ts`` owns generate.

    Regression: rerun8 generated with ``pnpm --filter api ... --schema
    <root>/prisma/schema.prisma`` while the package config resolved
    ``schema: 'prisma/schema.prisma'`` relative to ``apps/api``.
    """
    api_dir = _write_pnpm_api_workspace(
        tmp_path,
        root_schema=True,
        app_schema=True,
        app_prisma_config=True,
    )
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    prisma_calls = [
        c for c in recorder.calls
        if c["cmd"][:4] == ["pnpm", "--filter", "api", "exec"]
    ]
    assert len(prisma_calls) == 1
    cmd = prisma_calls[0]["cmd"]
    assert cmd == ["pnpm", "--filter", "api", "exec", "prisma", "generate"]
    assert "--schema" not in cmd
    assert Path(prisma_calls[0]["cwd"]).resolve() == tmp_path.resolve()

    invoked_paths = " ".join(" ".join(c["cmd"]) for c in recorder.calls)
    assert str((tmp_path / "prisma" / "schema.prisma").resolve()) not in invoked_paths
    assert str((api_dir / "prisma" / "schema.prisma").resolve()) not in invoked_paths


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


# ---------------------------------------------------------------------------
# (e) Builder fix #2 — package-manager-aware Prisma resolution
#
# Closes the gap surfaced by run-dir
# ``v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260502-003801-e6d3fce-01-20260502-003820/``
# (BUILD_LOG line ~631):
#
#     /prisma/schema.prisma:0 PRISMA_GENERATE_FAILED prisma generate failed
#       (exit 127) ... sh: 1: prisma: not found
#
# The pre-fix code ran ``npx prisma generate`` from the repo root. For a
# pnpm monorepo, root ``node_modules/.bin/`` does NOT carry a ``prisma``
# shim (pnpm's per-package isolation puts it under
# ``apps/api/node_modules/.bin/prisma``). ``npx`` falls through to the
# system shell which can't find ``prisma`` → exit 127.
#
# The fix detects pnpm via ``packageManager`` field or ``pnpm-lock.yaml``
# and produces a ``pnpm``-prefixed spawn (``pnpm --filter <name> exec
# prisma generate ...`` or ``pnpm exec prisma generate ...``), mirroring
# the canonical Docker pattern at
# ``templates/pnpm_monorepo/apps/api/Dockerfile:49``.
# ---------------------------------------------------------------------------


def _write_pnpm_monorepo_layout(
    tmp_path: Path,
    *,
    api_workspace_name: str = "@scaffold/api",
    include_lockfile: bool = True,
    package_manager: str | None = "pnpm@9.12.0",
    add_root_prisma_bin: bool = False,
) -> Path:
    """Build the exact failing-rerun-3 layout: pnpm monorepo with prisma at
    ``apps/api/node_modules/.bin/prisma`` but NOT at root.

    Returns the path to the root ``prisma/schema.prisma`` so callers can
    assert on it.
    """
    # Root package.json with packageManager field (canonical pnpm signal).
    root_pkg: dict[str, Any] = {"name": "scaffold-monorepo", "private": True}
    if package_manager is not None:
        root_pkg["packageManager"] = package_manager
    import json as _json
    (tmp_path / "package.json").write_text(
        _json.dumps(root_pkg), encoding="utf-8"
    )

    # Root pnpm-lock.yaml — secondary detection signal. Stub content is fine.
    if include_lockfile:
        (tmp_path / "pnpm-lock.yaml").write_text(
            "lockfileVersion: '9.0'\n", encoding="utf-8"
        )

    # Root node_modules/.bin/ — has tsc + tsserver but NOT prisma (the
    # exact "no prisma at root" condition that broke rerun3).
    root_bin = tmp_path / "node_modules" / ".bin"
    root_bin.mkdir(parents=True, exist_ok=True)
    (root_bin / "tsc").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root_bin / "tsserver").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if add_root_prisma_bin:
        (root_bin / "prisma").write_text(
            "#!/bin/sh\nexit 0\n", encoding="utf-8"
        )

    # apps/api/node_modules/.bin/prisma — the actual prisma shim location
    # under pnpm workspace isolation.
    api_dir = tmp_path / "apps" / "api"
    api_bin = api_dir / "node_modules" / ".bin"
    api_bin.mkdir(parents=True, exist_ok=True)
    (api_bin / "prisma").write_text(
        "#!/bin/sh\necho 'prisma generate stub'\nexit 0\n", encoding="utf-8"
    )
    (api_dir / "package.json").write_text(
        _json.dumps({"name": api_workspace_name, "version": "0.1.0"}),
        encoding="utf-8",
    )

    # Root-level prisma/schema.prisma (the canonical layout the failing
    # rerun3 artifact used).
    return _write_schema(tmp_path / "prisma" / "schema.prisma")


@pytest.mark.asyncio
async def test_pnpm_monorepo_uses_pnpm_filter_not_npx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator-required regression: rerun3 layout produces pnpm spawn, not npx.

    Reproduces the exact failing layout from
    ``v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260502-003801-e6d3fce-01-20260502-003820/``::

        package.json (packageManager=pnpm@…)
        pnpm-lock.yaml
        prisma/schema.prisma                          # root-level schema
        node_modules/.bin/{tsc,tsserver}              # NO prisma here
        apps/api/node_modules/.bin/prisma             # actual binary
        apps/api/package.json (name=@scaffold/api)

    Asserts the pre-step issues a ``pnpm``-prefixed command. A bare
    ``npx`` invocation here would replicate the rerun3 ``sh: 1: prisma:
    not found`` failure (exit 127) because root .bin/ has no prisma shim.
    """
    schema = _write_pnpm_monorepo_layout(tmp_path)
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True

    # First call MUST be the pnpm-prefixed prisma generate. No bare npx.
    first = recorder.calls[0]
    assert first["cmd"][0] == "pnpm", (
        f"expected pnpm-prefixed spawn, got {first['cmd']}"
    )
    assert "prisma" in first["cmd"]
    assert "generate" in first["cmd"]
    assert "--schema" in first["cmd"]
    schema_idx = first["cmd"].index("--schema")
    assert Path(first["cmd"][schema_idx + 1]).resolve() == schema.resolve()

    # When workspace name resolves, prefer `pnpm --filter <name> exec ...`
    # — the canonical Docker shape. The fallback `pnpm exec ...` (no
    # filter) is also acceptable per the dispatch prompt; assert one OR
    # the other, but NEVER bare npx.
    if "--filter" in first["cmd"]:
        filter_idx = first["cmd"].index("--filter")
        assert first["cmd"][filter_idx + 1] == "@scaffold/api"
        # `pnpm --filter` runs from monorepo root.
        assert Path(first["cwd"]).resolve() == tmp_path.resolve()
    else:
        # `pnpm exec` shape — runs from a workspace that owns prisma.
        assert first["cmd"][:2] == ["pnpm", "exec"]


@pytest.mark.asyncio
async def test_prisma_generate_disables_prisma_auto_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5.6c must verify generated deps without mutating package.json."""
    _write_pnpm_monorepo_layout(tmp_path)
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    first = recorder.calls[0]
    assert "prisma" in first["cmd"]
    assert first["extra_env"]["PRISMA_GENERATE_SKIP_AUTOINSTALL"] == "true"


@pytest.mark.asyncio
async def test_pnpm_lockfile_only_still_dispatches_pnpm_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lockfile-only detection (no packageManager field) still dispatches pnpm.

    Some in-progress scaffolds may have ``pnpm-lock.yaml`` written
    before ``packageManager`` is added to ``package.json``. The pre-step
    must still produce a pnpm-prefixed spawn (not npx) — otherwise the
    rerun3 failure would recur once Wave B writes the lockfile but
    not the manifest field.
    """
    _write_pnpm_monorepo_layout(tmp_path, package_manager=None)
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    first = recorder.calls[0]
    assert first["cmd"][0] == "pnpm", (
        f"lockfile-only pnpm detection failed; got {first['cmd']}"
    )


@pytest.mark.asyncio
async def test_yarn_lockfile_dispatches_yarn_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yarn workspaces also isolate per-package .bin; use ``yarn exec``."""
    import json as _json
    (tmp_path / "package.json").write_text(
        _json.dumps({"name": "yarn-mono", "private": True}), encoding="utf-8"
    )
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n", encoding="utf-8")
    api_bin = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    api_bin.mkdir(parents=True, exist_ok=True)
    (api_bin / "prisma").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    first = recorder.calls[0]
    assert first["cmd"][:2] == ["yarn", "exec"]
    assert "prisma" in first["cmd"]
    assert "generate" in first["cmd"]


@pytest.mark.asyncio
async def test_npm_lockfile_keeps_npx_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit npm projects (``package-lock.json``) keep the ``npx`` shape.

    Closes the "do not regress non-pnpm fixtures" anti-pattern: when
    npm is detected, the pre-step uses the historical
    ``npx prisma generate`` shape from the schema's grandparent.
    """
    import json as _json
    (tmp_path / "package.json").write_text(
        _json.dumps({"name": "npm-mono", "private": True}), encoding="utf-8"
    )
    (tmp_path / "package-lock.json").write_text(
        '{"lockfileVersion": 3}\n', encoding="utf-8"
    )
    schema = _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    first = recorder.calls[0]
    assert first["cmd"][:3] == ["npx", "prisma", "generate"]
    schema_idx = first["cmd"].index("--schema")
    assert Path(first["cmd"][schema_idx + 1]).resolve() == schema.resolve()


@pytest.mark.asyncio
async def test_no_lockfile_fallback_keeps_npx_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No package.json + no lockfile → fallback to npx (preserves test fixtures).

    This locks the contract that the existing 17-test fixture set,
    which writes neither ``packageManager`` nor a lockfile, continues
    to traverse the historical ``npx prisma generate`` path.
    """
    schema = _write_schema(tmp_path / "apps" / "api" / "prisma" / "schema.prisma")
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder()
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is True
    first = recorder.calls[0]
    assert first["cmd"][:3] == ["npx", "prisma", "generate"]
    schema_idx = first["cmd"].index("--schema")
    assert Path(first["cmd"][schema_idx + 1]).resolve() == schema.resolve()


@pytest.mark.asyncio
async def test_pnpm_missing_binary_emits_missing_command_with_pnpm_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When pnpm itself is missing, ``MISSING_COMMAND`` mentions pnpm.

    Operator-facing message clarity: the env-unavailable diagnostic
    should name the binary that was missing, not the legacy ``npx``.
    """
    _write_pnpm_monorepo_layout(tmp_path)
    profile = _make_tsconfig_only_profile(tmp_path)

    recorder = _RunRecorder(
        raise_on_match={"prisma generate": FileNotFoundError("pnpm")},
    )
    monkeypatch.setattr(compile_profiles, "_run_command", recorder)

    result = await run_wave_compile_check(
        cwd=str(tmp_path), profile=profile, project_root=tmp_path,
    )

    assert result.passed is False
    err = result.errors[0]
    assert err["code"] == "MISSING_COMMAND"
    assert "pnpm" in err["message"]
    # is_compile_env_unavailable still classifies this as env-blocked.
    assert is_compile_env_unavailable(result) is True


def test_detect_package_manager_precedence(tmp_path: Path) -> None:
    """packageManager field beats lockfile inference."""
    import json as _json
    from agent_team_v15.compile_profiles import _detect_package_manager

    # No evidence → "".
    assert _detect_package_manager(tmp_path) == ""

    # Lockfile-only.
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert _detect_package_manager(tmp_path) == "pnpm"

    # Manifest packageManager overrides any lockfile reading.
    (tmp_path / "package.json").write_text(
        _json.dumps({"packageManager": "yarn@4.0.0"}), encoding="utf-8"
    )
    assert _detect_package_manager(tmp_path) == "yarn"

    # Malformed package.json falls back to lockfile.
    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
    assert _detect_package_manager(tmp_path) == "pnpm"


def test_detect_package_manager_lockfile_priority(tmp_path: Path) -> None:
    """When packageManager absent, pnpm-lock > yarn.lock > package-lock.json."""
    from agent_team_v15.compile_profiles import _detect_package_manager

    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    assert _detect_package_manager(tmp_path) == "npm"

    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    assert _detect_package_manager(tmp_path) == "yarn"

    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert _detect_package_manager(tmp_path) == "pnpm"
