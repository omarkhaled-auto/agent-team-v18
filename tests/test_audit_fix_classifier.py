"""Phase G Slice 2a — audit-fix classifier routes backend/wiring to Codex.

``provider_router.classify_fix_provider`` returns ``"codex"`` or
``"claude"`` based on (a) issue_type keyword match, and (b) file-path
heuristic scoring. ``cli._run_patch_fixes`` calls it only when
``v18.codex_fix_routing_enabled=True`` AND provider routing is already
configured. Full-build (subprocess) mode is unaffected per R7 qualifier.

Also asserts the Codex wrapper (``codex_fix_prompts.wrap_fix_prompt_for_codex``)
passes the Claude-shaped fix body through verbatim (LOCKED
``_ANTI_BAND_AID_FIX_RULES`` rides the wrap untouched).
"""

from __future__ import annotations

import inspect

from agent_team_v15 import cli as _cli
from agent_team_v15.codex_fix_prompts import wrap_fix_prompt_for_codex
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.provider_router import classify_fix_provider


def test_classifier_returns_codex_for_backend_issue() -> None:
    """Backend/wiring issue keywords trigger the Codex route."""
    verdict = classify_fix_provider(
        affected_files=["apps/api/src/users/users.service.ts"],
        issue_type="wiring",
    )
    assert verdict == "codex"


def test_classifier_returns_claude_for_frontend_issue() -> None:
    verdict = classify_fix_provider(
        affected_files=["apps/web/components/nav.tsx"],
        issue_type="styling",
    )
    assert verdict == "claude"


def test_classifier_uses_path_scoring_when_issue_type_ambiguous() -> None:
    """Neutral issue_type → path heuristics decide."""
    codex_files = [
        "apps/api/src/orders/orders.controller.ts",
        "apps/api/src/orders/orders.module.ts",
    ]
    claude_files = [
        "apps/web/components/order-list.tsx",
        "apps/web/styles/theme.css",
    ]
    assert classify_fix_provider(codex_files, "") == "codex"
    assert classify_fix_provider(claude_files, "") == "claude"


def test_patch_fixes_code_calls_classifier_only_when_flag_on() -> None:
    """Source inspection: ``cli._run_patch_fixes`` invokes
    ``classify_fix_provider`` inside the flag-gated branch (R7 patch-mode
    only) — the lazy ``from .provider_router import classify_fix_provider``
    sits after the ``codex_fix_routing_enabled`` check within one function.
    """
    from agent_team_v15 import cli as cli_mod

    mod_src = inspect.getsource(cli_mod)
    assert "classify_fix_provider" in mod_src
    assert "codex_fix_routing_enabled" in mod_src
    # The classifier import LINE should come after the flag LINE within the
    # patch-fix block. Search for the dispatcher-local import specifically.
    dispatcher_import = "from .provider_router import classify_fix_provider"
    assert dispatcher_import in mod_src
    import_pos = mod_src.index(dispatcher_import)
    flag_pos = mod_src.rfind("codex_fix_routing_enabled", 0, import_pos)
    assert flag_pos != -1, (
        "codex_fix_routing_enabled flag check must precede the classifier "
        "import inside the patch-fix dispatcher"
    )


def test_wrap_fix_prompt_for_codex_preserves_input_verbatim() -> None:
    """The Codex wrapper injects preamble + suffix but never modifies the
    caller-supplied body (which contains the LOCKED anti-band-aid rules)."""
    body = (
        "[FIX MODE - ROOT CAUSE ONLY]\n"
        "You are fixing real bugs. Surface patches are FORBIDDEN.\n"
        "\n[TARGET FILES]\n- apps/api/src/users/users.service.ts\n"
    )
    wrapped = wrap_fix_prompt_for_codex(body)
    # Body is contained untouched.
    assert body.strip() in wrapped
    # Codex execution shell is prepended.
    assert "autonomous fix agent" in wrapped
    # Structured-output contract is appended.
    assert "fixed_finding_ids" in wrapped
    assert "files_changed" in wrapped


def test_classifier_default_is_claude_on_empty_signals() -> None:
    verdict = classify_fix_provider(affected_files=[], issue_type="")
    assert verdict == "claude"


def test_classifier_resilient_to_windows_paths() -> None:
    """Backslash-separated paths must still match the Codex path heuristics."""
    verdict = classify_fix_provider(
        affected_files=["apps\\api\\src\\orders\\orders.service.ts"],
        issue_type="",
    )
    assert verdict == "codex"
