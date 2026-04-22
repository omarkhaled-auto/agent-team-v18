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


def test_wave_b_preamble_contains_dockerfile_contract() -> None:
    """DOCK-001..DOCK-006 bars must all appear in the Wave B preamble."""
    preamble = _cp.CODEX_WAVE_B_PREAMBLE
    for label in ("DOCK-001", "DOCK-002", "DOCK-003", "DOCK-004", "DOCK-005", "DOCK-006"):
        assert label in preamble, f"Wave B preamble missing {label}"


def test_wave_b_preamble_mentions_pnpm_workspace_context() -> None:
    """The DOCK-* block must tie build.context selection to pnpm-workspace.yaml."""
    preamble = _cp.CODEX_WAVE_B_PREAMBLE
    assert "pnpm-workspace.yaml" in preamble
    assert "build.context" in preamble


def test_wave_b_preamble_rejects_copy_escape() -> None:
    """DOCK-005 must flag `..`-escaping COPY sources as an anti-pattern."""
    preamble = _cp.CODEX_WAVE_B_PREAMBLE
    dock_005_idx = preamble.index("DOCK-005")
    # Find the first "Anti-pattern:" fragment that belongs to the DOCK-005 block.
    anti_idx = preamble.index("Anti-pattern:", dock_005_idx)
    # The next DOCK-* label bounds the block; the anti-pattern line must
    # come before that boundary.
    next_dock_idx = preamble.index("DOCK-006", dock_005_idx)
    assert anti_idx < next_dock_idx, "DOCK-005 block missing its Anti-pattern line"
    anti_fragment = preamble[anti_idx:next_dock_idx]
    assert "../packages/shared" in anti_fragment or "`..`" in anti_fragment, (
        "DOCK-005 Anti-pattern must call out `..`-escaping COPY sources"
    )
