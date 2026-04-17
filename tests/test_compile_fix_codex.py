"""Phase G Slice 2b — Codex-native compile-fix prompt (flag-gated).

When ``v18.compile_fix_codex_enabled=True`` AND provider routing is
active, the wave executor calls ``_build_compile_fix_prompt(...,
use_codex_shell=True)`` which delegates to
``codex_fix_prompts.build_codex_compile_fix_prompt``. The LOCKED
``_ANTI_BAND_AID_FIX_RULES`` block (``cli.py``) is passed through
verbatim — the Codex builder must not paraphrase it.

Default ``use_codex_shell=False`` preserves the legacy Claude-shaped
prompt byte-for-byte.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.cli import _ANTI_BAND_AID_FIX_RULES
from agent_team_v15.codex_fix_prompts import build_codex_compile_fix_prompt
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import _build_compile_fix_prompt


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(id="M1", title="Users")


def _errors() -> list[dict]:
    return [
        {
            "file": "apps/api/src/users/users.service.ts",
            "line": 42,
            "code": "TS2322",
            "message": "Type 'string' is not assignable to type 'number'.",
        },
    ]


def test_flag_off_emits_legacy_claude_prompt_shape() -> None:
    """Default (use_codex_shell=False) keeps legacy PHASE header."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=False,
    )
    assert prompt.startswith("[PHASE: WAVE B COMPILE FIX]")
    # Legacy shell does NOT emit the Codex JSON output contract tokens.
    assert "residual_error_count" not in prompt


def test_flag_on_emits_codex_shell_prompt() -> None:
    """use_codex_shell=True → Codex shell with output schema inlined."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=True,
    )
    assert "compile-fix agent" in prompt
    assert "<context>" in prompt
    assert "<errors>" in prompt
    # Structured Codex JSON output contract.
    assert "fixed_errors" in prompt
    assert "still_failing" in prompt
    assert "residual_error_count" in prompt


def test_codex_shell_inherits_locked_anti_band_aid_verbatim() -> None:
    """The LOCKED block must appear byte-identical inside the Codex prompt."""
    prompt = _build_compile_fix_prompt(
        _errors(),
        wave_letter="B",
        milestone=_milestone(),
        use_codex_shell=True,
    )
    assert _ANTI_BAND_AID_FIX_RULES in prompt


def test_build_codex_compile_fix_prompt_direct_call_carries_locked() -> None:
    """Direct call to the prompt builder also propagates the LOCKED block."""
    prompt = build_codex_compile_fix_prompt(
        errors=_errors(),
        wave_letter="B",
        milestone_id="M1",
        milestone_title="Users",
        iteration=0,
        max_iterations=3,
        previous_error_count=None,
        current_error_count=1,
        build_command="pnpm build",
        anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
    )
    assert _ANTI_BAND_AID_FIX_RULES in prompt
    # Context placeholders rendered.
    assert "Wave: B" in prompt
    assert "Milestone: M1 — Users" in prompt
    assert "Iteration: 0/3" in prompt


def test_compile_fix_codex_enabled_flag_exists_and_defaults_off() -> None:
    """Flag must exist on the V18 config with default False (R7)."""
    cfg = AgentTeamConfig()
    assert hasattr(cfg.v18, "compile_fix_codex_enabled")
    assert cfg.v18.compile_fix_codex_enabled is False


def test_codex_prompt_handles_missing_errors_gracefully() -> None:
    """Empty error list must not crash the builder."""
    prompt = build_codex_compile_fix_prompt(
        errors=[],
        wave_letter="B",
        milestone_id="M1",
        milestone_title="Users",
        iteration=1,
        max_iterations=3,
        previous_error_count=5,
        current_error_count=0,
        build_command="",
        anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
    )
    # Builder falls back to an explanatory bullet.
    assert "Compiler failed" in prompt or "no structured errors" in prompt
