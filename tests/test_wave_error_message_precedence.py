"""Wave error-message precedence regression — ``build-final-smoke-20260418-041514``.

Before this fix, when the scaffold verifier FAILed Wave A, the wave
executor set ``wave_result.error_message`` to the specific verifier
diagnostic ("Scaffold-verifier FAIL: verdict=FAIL missing=41 …") AND
flipped ``compile_result.passed=False``. Two code paths then unconditionally
overwrote that specific message with "Compile failed after N attempt(s)",
hiding the real cause in telemetry and BUILD_LOG.

These tests guard the post-fix contract: a non-empty, non-"Compile failed
after " prefix message set upstream is preserved; only when no specific
upstream message exists does the generic compile-failed message apply.

The test uses a minimal stub of the preservation logic that mirrors the
two patch sites in ``wave_executor.py`` (verified by regex so the tests
fail if either site drifts from the contract).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Mirror of the preservation logic in wave_executor.py
# ---------------------------------------------------------------------------


@dataclass
class _WaveResult:
    success: bool = True
    error_message: str = ""


@dataclass
class _CompileResult:
    passed: bool = True
    iterations: int = 1
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Guard:
    passed: bool = True
    error_message: str = ""


def _apply_precedence(
    wave_result: _WaveResult,
    compile_result: _CompileResult,
    dto_guard: _Guard,
    frontend_guard: _Guard,
) -> None:
    """Exact replica of the preservation logic (both sites in wave_executor)."""
    wave_result.success = False
    existing_specific = (
        wave_result.error_message
        and not wave_result.error_message.startswith("Compile failed after ")
    )
    if existing_specific:
        pass
    elif not compile_result.passed:
        wave_result.error_message = _compile_failure_error_message(compile_result)
    elif not dto_guard.passed:
        wave_result.error_message = dto_guard.error_message
    else:
        wave_result.error_message = frontend_guard.error_message


def _compile_result_terminal_transport_failure_reason(
    compile_result: _CompileResult,
) -> str:
    for error in compile_result.errors or []:
        text = f"{error.get('code', '')} {error.get('message', '')}".lower()
        if "transport_stdout_eof_before_turn_completed" in text:
            return "transport_stdout_eof_before_turn_completed"
        if "transport eof" in text and "turn/completed" in text:
            return "transport_stdout_eof_before_turn_completed"
        if "stdout eof" in text and "turn/completed" in text:
            return "transport_stdout_eof_before_turn_completed"
        if "app-server stdout eof" in text:
            return "transport_stdout_eof_before_turn_completed"
    return ""


def _compile_failure_error_message(compile_result: _CompileResult) -> str:
    reason = _compile_result_terminal_transport_failure_reason(compile_result)
    if reason:
        return f"{reason}: Compile failed after {compile_result.iterations} attempt(s)"
    return f"Compile failed after {compile_result.iterations} attempt(s)"


# ---------------------------------------------------------------------------
# Semantic contract tests
# ---------------------------------------------------------------------------


def test_scaffold_verifier_message_is_preserved() -> None:
    """The smoke regression: verifier sets the specific message + flips
    compile.passed=False. The outer block must NOT clobber the message."""
    wave = _WaveResult(error_message="Scaffold-verifier FAIL: verdict=FAIL missing=41")
    compile_result = _CompileResult(passed=False, iterations=1)

    _apply_precedence(wave, compile_result, _Guard(passed=True), _Guard(passed=True))

    assert wave.success is False
    assert wave.error_message == "Scaffold-verifier FAIL: verdict=FAIL missing=41"


def test_generic_compile_failure_still_reports_attempt_count() -> None:
    """When nothing upstream set a specific message, the generic compile
    failed message with attempt count still applies — no regression for the
    pure compile-failure path."""
    wave = _WaveResult(error_message="")
    compile_result = _CompileResult(passed=False, iterations=3)

    _apply_precedence(wave, compile_result, _Guard(passed=True), _Guard(passed=True))

    assert wave.error_message == "Compile failed after 3 attempt(s)"


def test_compile_repair_transport_eof_survives_generic_compile_failure() -> None:
    """Compile-repair EOF lives in CompileResult.errors; keep it visible to Phase 4.5."""
    wave = _WaveResult(error_message="")
    compile_result = _CompileResult(
        passed=False,
        iterations=2,
        errors=[
            {
                "code": "CODEX-REPAIR-FAILED",
                "message": (
                    "Wave B compile Codex repair ended with transport EOF before "
                    "turn/completed; host compile recheck still failed"
                ),
            }
        ],
    )

    _apply_precedence(wave, compile_result, _Guard(passed=True), _Guard(passed=True))

    assert wave.error_message == (
        "transport_stdout_eof_before_turn_completed: "
        "Compile failed after 2 attempt(s)"
    )


def test_dto_guard_failure_reports_dto_message() -> None:
    wave = _WaveResult(error_message="")
    compile_result = _CompileResult(passed=True, iterations=1)

    _apply_precedence(
        wave,
        compile_result,
        _Guard(passed=False, error_message="DTO contract drift in users.dto.ts"),
        _Guard(passed=True),
    )

    assert wave.error_message == "DTO contract drift in users.dto.ts"


def test_frontend_guard_failure_reports_frontend_message() -> None:
    wave = _WaveResult(error_message="")
    compile_result = _CompileResult(passed=True, iterations=1)

    _apply_precedence(
        wave,
        compile_result,
        _Guard(passed=True),
        _Guard(passed=False, error_message="Frontend hallucination in project-list.tsx"),
    )

    assert wave.error_message == "Frontend hallucination in project-list.tsx"


# ---------------------------------------------------------------------------
# Structural check — both call sites in wave_executor.py carry the guard
# ---------------------------------------------------------------------------


def test_both_wave_executor_sites_carry_the_preservation_guard() -> None:
    """Grep guard: if a future edit removes the ``existing_specific`` check
    from either of the two call sites in wave_executor.py, the scaffold
    verifier diagnostic will again be clobbered by the generic message. Fail
    the suite before that regression reaches production."""
    src = Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "wave_executor.py"
    text = src.read_text(encoding="utf-8")
    assert text.count("existing_specific = (") >= 2
    formatter_calls = re.findall(
        r"_compile_failure_error_message\(\s*compile_result\s*\)",
        text,
    )
    assert len(formatter_calls) >= 2, (
        "Expected both compile-failure clobber-risk sites to use the "
        "EOF-aware compile failure formatter"
    )


def test_both_wave_executor_sites_preserve_compile_repair_transport_eof() -> None:
    """Both clobber-risk sites must use the EOF-aware compile failure formatter."""
    src = Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "wave_executor.py"
    text = src.read_text(encoding="utf-8")
    formatter_calls = re.findall(
        r"_compile_failure_error_message\(\s*compile_result\s*\)",
        text,
    )
    assert len(formatter_calls) >= 2
