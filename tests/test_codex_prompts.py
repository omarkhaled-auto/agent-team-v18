"""Tests for Codex native-tool directive prompt hardening.

The directive is prepended to every Codex wave prompt by ``wrap_prompt_for_codex``;
its contents govern whether Codex emits ``turn/plan/updated`` and
``turn/diff/updated`` notifications that the observer's Codex hook listens for.
"""

from __future__ import annotations

from agent_team_v15 import codex_prompts as _cp


def test_native_tool_directive_names_update_plan_and_apply_patch() -> None:
    directive = _cp.CODEX_NATIVE_TOOL_DIRECTIVE
    assert "update_plan" in directive
    assert "apply_patch" in directive


def test_native_tool_directive_marks_shell_writes_as_rejected_turn() -> None:
    directive = _cp.CODEX_NATIVE_TOOL_DIRECTIVE
    assert "REJECTED TURN" in directive


def test_native_tool_directive_enumerates_forbidden_shell_redirection_forms() -> None:
    directive = _cp.CODEX_NATIVE_TOOL_DIRECTIVE
    for fragment in ("echo", "cat <<EOF", "printf", "tee", "sed -i"):
        assert fragment in directive, f"directive must forbid {fragment!r}"


def test_native_tool_directive_is_wrapped_in_native_tools_contract() -> None:
    directive = _cp.CODEX_NATIVE_TOOL_DIRECTIVE
    assert "<native_tools_contract>" in directive
    assert "</native_tools_contract>" in directive


def test_wrap_prompt_for_codex_prepends_directive_for_non_wrapper_wave() -> None:
    wrapped = _cp.wrap_prompt_for_codex("A", "Wave A body")
    assert wrapped.startswith(_cp.CODEX_NATIVE_TOOL_DIRECTIVE)
    assert "Wave A body" in wrapped


def test_wrap_prompt_for_codex_prepends_directive_for_wrapper_wave() -> None:
    wrapped = _cp.wrap_prompt_for_codex("B", "Wave B body")
    assert _cp.CODEX_NATIVE_TOOL_DIRECTIVE in wrapped
    assert wrapped.startswith(_cp.CODEX_NATIVE_TOOL_DIRECTIVE)
    assert "Wave B body" in wrapped
