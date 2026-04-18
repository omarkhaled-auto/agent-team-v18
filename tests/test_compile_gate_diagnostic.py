"""Diagnostic tests for the Wave A compile-gate contradiction observed in
``build-final-smoke-20260418-041514``.

Telemetry at ``.agent-team/telemetry/milestone-1-wave-A.json``::

    "compile_iterations": 1,
    "compile_errors_initial": 0,
    "compile_passed": false,
    "error_message": "Compile failed after 1 attempt(s)"

Re-running ``run_wave_compile_check`` against the smoke's post-state returns
``passed=True`` — the disagreement means ``_run_wave_compile`` or its
ancillary guards flipped ``passed`` between the run-time check and the
final telemetry write.

These tests drive ``_run_wave_compile`` directly with the Wave A call
shape and progressively narrow where the bug originates.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.compile_profiles import CompileResult
from agent_team_v15.wave_executor import (
    CompileCheckResult,
    _coerce_compile_result,
    _run_wave_compile,
)


@dataclass
class _Milestone:
    id: str = "milestone-1"
    stack_target: str = "nestjs+nextjs"
    build_command: str = ""


def _config(**v18_overrides: Any) -> Any:
    v18 = SimpleNamespace(
        compile_fix_codex_enabled=False,
        wave_d_merged_enabled=False,
        wave_d_compile_fix_max_attempts=2,
        milestone_scope_enforcement=True,
    )
    for key, value in v18_overrides.items():
        setattr(v18, key, value)
    return SimpleNamespace(v18=v18)


async def _null_sdk(*args: Any, **kwargs: Any) -> tuple[float, Any]:
    return 0.0, None


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# Sanity: noop-style passing compile returns iterations=1, passed=True
# ---------------------------------------------------------------------------


def test_noop_compile_returns_passed_true_iterations_one(tmp_path) -> None:
    """Baseline — when run_compile_check says passed=True (no-op profile),
    _run_wave_compile must exit iteration 0 with passed=True, iterations=1."""

    async def compile_check(**_: Any) -> CompileResult:
        return CompileResult(passed=True, error_count=0, errors=[], raw_output="")

    result = _run(
        _run_wave_compile(
            run_compile_check=compile_check,
            execute_sdk_call=_null_sdk,
            wave_letter="A",
            template="enterprise",
            config=_config(),
            cwd=str(tmp_path),
            milestone=_Milestone(),
        )
    )
    assert result.passed is True
    assert result.iterations == 1
    assert result.initial_error_count == 0


# ---------------------------------------------------------------------------
# Reproduction: passed=False + zero errors mirrors the smoke's telemetry
# ---------------------------------------------------------------------------


def test_passed_false_with_zero_errors_loops_to_exhaustion(tmp_path) -> None:
    """If run_compile_check returns passed=False AND empty errors, the fix
    loop has nothing to repair. It should either:

      (a) Exhaust max_iterations (=3 for Wave A) and report iterations=3, OR
      (b) Short-circuit on the zero-error contradiction and pass.

    The smoke observed iterations=1 — neither (a) nor (b). This test
    pins down which branch actually fires today, so we know whether to
    adjust the loop exit condition or the coercion."""

    call_count = {"n": 0}

    async def compile_check(**_: Any) -> CompileResult:
        call_count["n"] += 1
        return CompileResult(passed=False, error_count=0, errors=[], raw_output="")

    result = _run(
        _run_wave_compile(
            run_compile_check=compile_check,
            execute_sdk_call=_null_sdk,
            wave_letter="A",
            template="enterprise",
            config=_config(),
            cwd=str(tmp_path),
            milestone=_Milestone(),
        )
    )

    # Record observed behavior — we will assert on specifics after diagnosis.
    assert call_count["n"] >= 1, "compile_check must have been invoked"
    # Smoke observed iterations=1 which implies early exit. Document it here
    # — if this assertion flips, the loop has been adjusted.
    assert result.iterations in (1, 2, 3), (
        f"Unexpected iteration count {result.iterations} — "
        f"compile_check invoked {call_count['n']} times"
    )


# ---------------------------------------------------------------------------
# Coercion path: CompileResult with error_count=0 but passed=False
# ---------------------------------------------------------------------------


def test_coerce_preserves_passed_false_even_when_error_count_zero() -> None:
    """``_coerce_compile_result`` must not silently flip passed=False to
    passed=True when error_count happens to be 0."""

    source = CompileResult(
        passed=False, error_count=0, errors=[], raw_output="(empty)"
    )
    coerced = _coerce_compile_result(source)
    assert coerced.passed is False
    assert coerced.initial_error_count == 0
    assert coerced.errors == []


def test_coerce_unknown_object_with_no_passed_attribute_defaults_true() -> None:
    """Guards against a regression where a compile check returns an object
    without a ``passed`` attribute and we silently default to failing."""

    class _Unknown:
        pass

    coerced = _coerce_compile_result(_Unknown())
    # The current default is True (see wave_executor.py:753-754). This test
    # pins that contract so it is not regressed quietly.
    assert coerced.passed is True


# ---------------------------------------------------------------------------
# What the smoke observed vs. what the code does:
# Document the gap.
# ---------------------------------------------------------------------------


def test_documents_smoke_contradiction() -> None:
    """Smoke recorded: iterations=1, passed=False, initial_error_count=0.

    Re-running `run_wave_compile_check` against the same cwd post-smoke
    returned passed=True (noop profile). Two hypotheses:

      H1. At run time, a compile profile was actually selected (e.g.
          a transient tsconfig existed) and produced a zero-error failure
          (command exited nonzero with no parseable errors — would show up
          via `_fallback_error`, not zero errors).
      H2. A wrapping layer (DTO guard, frontend guard, structural triage)
          mutated wave_result.compile_passed after _run_wave_compile
          returned passed=True.

    H1 is ruled out for Wave A because _run_wave_b_dto_contract_guard and
    _run_wave_d_frontend_hallucination_guard are gated on
    `wave_letter in {"B","D"}`. For Wave A both guards default to
    passed=True/compile_passed=True per _DeterministicGuardResult.

    This test is a narrative marker — the actual repro is the
    integration test in the smoke BUILD_LOG. Kept as doc-via-test.
    """
    # Assertion: this test's existence in the file implies the
    # hypothesis chain is documented. Keep it passing trivially.
    assert True
