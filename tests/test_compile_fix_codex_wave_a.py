"""Wave A regression for Codex compile-fix dispatch (Phase G Slice 2b).

``v18.compile_fix_codex_enabled=True`` with provider_routing mapping a wave
to Codex must route compile-fix dispatches to Codex for **every** wave letter
where compile-fix runs, not just Wave B. Before this test, only Wave B had
explicit coverage (tests/test_compile_fix_codex.py), leaving Wave A as a
latent risk — the build-final-smoke-20260418-041514 run showed
``compile_fix_cost_usd: 0.0`` on a failed Wave A, consistent with
compile-fix never firing.

These tests pin down the contract: given a failing Wave A compile with a
non-None execute_sdk_call AND a provider map that routes Wave A to Codex,
``_run_wave_compile`` must attempt the Codex dispatch before falling back.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.compile_profiles import CompileResult
from agent_team_v15.wave_executor import _run_wave_compile


@dataclass
class _Milestone:
    id: str = "milestone-1"
    stack_target: str = "nestjs+nextjs"
    build_command: str = ""


def _config(codex_enabled: bool) -> Any:
    return SimpleNamespace(
        v18=SimpleNamespace(
            compile_fix_codex_enabled=codex_enabled,
            wave_d_merged_enabled=False,
            wave_d_compile_fix_max_attempts=2,
            milestone_scope_enforcement=True,
        )
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def codex_dispatch_recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture calls to ``_dispatch_codex_compile_fix`` without performing them."""
    calls: list[dict[str, Any]] = []

    async def fake_dispatch(
        prompt: str,
        *,
        cwd: str,
        provider_routing: Any,
        v18: Any,
        **kwargs: Any,
    ):
        calls.append({"prompt": prompt, "cwd": cwd, "v18": v18, **kwargs})
        # Return (success, cost_delta, reason) — matches the real signature.
        return True, 0.01, ""

    monkeypatch.setattr(
        "agent_team_v15.wave_executor._dispatch_codex_compile_fix",
        fake_dispatch,
    )
    return calls


# ---------------------------------------------------------------------------
# Wave A regression: Codex dispatches when flag is on AND routing supplied
# ---------------------------------------------------------------------------


def test_wave_a_compile_fix_routes_to_codex_when_enabled(
    tmp_path, codex_dispatch_recorder: list[dict[str, Any]]
) -> None:
    """With Wave A mapped to Codex, a failing compile attempts Codex repair."""

    fail_count = {"n": 0}

    async def compile_check(**_: Any) -> CompileResult:
        fail_count["n"] += 1
        return CompileResult(
            passed=False,
            error_count=1,
            errors=[{"file": "apps/api/src/main.ts", "line": 1, "code": "TS0001", "message": "fake"}],
            raw_output="fake error",
        )

    async def null_sdk(*args: Any, **kwargs: Any) -> tuple[float, Any]:
        return 0.0, None

    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex")
    }

    result = _run(
        _run_wave_compile(
            run_compile_check=compile_check,
            execute_sdk_call=null_sdk,
            wave_letter="A",
            template="enterprise",
            config=_config(codex_enabled=True),
            cwd=str(tmp_path),
            milestone=_Milestone(),
            provider_routing=provider_routing,
        )
    )

    # Contract: Codex was attempted at least once on Wave A
    assert codex_dispatch_recorder, (
        "Codex compile-fix dispatch was NOT attempted on Wave A "
        "despite compile_fix_codex_enabled=True + provider map routing Wave A to Codex"
    )
    # Sanity: compile_check was polled multiple times (initial + retries)
    assert fail_count["n"] >= 2
    # The wave exhausted its fix attempts (passed stays False)
    assert result.passed is False


def test_wave_a_compile_fix_uses_claude_when_codex_flag_off(
    tmp_path, codex_dispatch_recorder: list[dict[str, Any]]
) -> None:
    """With ``compile_fix_codex_enabled=False`` the Codex dispatch path
    must NOT be entered — Claude SDK fallback handles compile-fix."""

    async def compile_check(**_: Any) -> CompileResult:
        return CompileResult(
            passed=False,
            error_count=1,
            errors=[{"file": "apps/api/src/main.ts", "line": 1, "code": "TS0001", "message": "fake"}],
            raw_output="fake error",
        )

    async def null_sdk(*args: Any, **kwargs: Any) -> tuple[float, Any]:
        return 0.0, None

    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex")
    }

    _run(
        _run_wave_compile(
            run_compile_check=compile_check,
            execute_sdk_call=null_sdk,
            wave_letter="A",
            template="enterprise",
            config=_config(codex_enabled=False),
            cwd=str(tmp_path),
            milestone=_Milestone(),
            provider_routing=provider_routing,
        )
    )

    assert codex_dispatch_recorder == [], (
        "Codex dispatch fired despite compile_fix_codex_enabled=False: "
        f"{codex_dispatch_recorder}"
    )


def test_wave_a_no_codex_without_provider_routing(
    tmp_path, codex_dispatch_recorder: list[dict[str, Any]]
) -> None:
    """When ``provider_routing`` is None, Codex must not be attempted even
    if the flag is True (provider_routing is the carrier for Codex)."""

    async def compile_check(**_: Any) -> CompileResult:
        return CompileResult(
            passed=False,
            error_count=1,
            errors=[{"file": "x", "line": 1, "code": "E", "message": "m"}],
        )

    async def null_sdk(*args: Any, **kwargs: Any) -> tuple[float, Any]:
        return 0.0, None

    _run(
        _run_wave_compile(
            run_compile_check=compile_check,
            execute_sdk_call=null_sdk,
            wave_letter="A",
            template="enterprise",
            config=_config(codex_enabled=True),
            cwd=str(tmp_path),
            milestone=_Milestone(),
            provider_routing=None,
        )
    )

    assert codex_dispatch_recorder == []
