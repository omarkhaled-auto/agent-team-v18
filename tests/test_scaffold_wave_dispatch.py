"""``"Scaffold"`` wave-slot dispatch — regression for smoke-#4 failure.

Phase G added an explicit ``"Scaffold"`` slot to every full_stack /
backend_only wave sequence. The slot is supposed to mark "the moment
the Python scaffolder emits foundation files", but the iteration was
never special-cased:

* ``_scaffolding_start_wave`` returned ``"B"`` (pre-Phase-G), so the
  scaffolder fired at ``"B"`` — *after* ``"Scaffold"`` in the sequence.
* ``build_wave_prompt`` had no handler for ``"Scaffold"`` → it raised
  ``ValueError("Unsupported wave prompt requested: Scaffold")`` the
  moment the loop reached that iteration.

build-final-smoke-20260418-170309 hit this: Wave A + A5 completed
cleanly under the closed-class selector PRs, then the loop advanced
to ``"Scaffold"`` and crashed before the scaffolder could fire.

The fix:
1. ``_scaffolding_start_wave`` now returns ``"Scaffold"`` whenever the
   slot is in the template's sequence (``WAVE_SEQUENCES``).
2. The main wave loop advances the explicit wave index and
   ``continue``\\ s on ``wave_letter == "Scaffold"`` after the
   scaffolder block so the SDK prompt dispatch is skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15.wave_executor import (
    WAVE_SEQUENCES,
    _scaffolding_start_wave,
)


# ---------------------------------------------------------------------------
# scaffolding_start_wave now targets the explicit "Scaffold" slot
# ---------------------------------------------------------------------------


def test_full_stack_scaffolding_fires_at_scaffold_slot() -> None:
    assert "Scaffold" in WAVE_SEQUENCES["full_stack"]
    assert _scaffolding_start_wave("full_stack") == "Scaffold"


def test_backend_only_scaffolding_fires_at_scaffold_slot() -> None:
    assert "Scaffold" in WAVE_SEQUENCES["backend_only"]
    assert _scaffolding_start_wave("backend_only") == "Scaffold"


def test_frontend_only_scaffolding_fires_at_scaffold_slot() -> None:
    """frontend_only also has a ``"Scaffold"`` slot (verified in
    WAVE_SEQUENCES). The helper returns it consistently so the
    scaffolder fires before Wave D."""
    assert "Scaffold" in WAVE_SEQUENCES["frontend_only"]
    assert _scaffolding_start_wave("frontend_only") == "Scaffold"


def test_unknown_template_returns_none() -> None:
    assert _scaffolding_start_wave("some-unheard-of-template") is None


# ---------------------------------------------------------------------------
# Structural invariant: wave loop must skip prompt dispatch on "Scaffold"
# ---------------------------------------------------------------------------


_WAVE_EXECUTOR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "wave_executor.py"
)


def test_main_wave_loop_continues_past_scaffold_slot() -> None:
    """The wave loop body must ``continue`` when
    ``wave_letter == "Scaffold"``, AFTER the scaffolder block and
    BEFORE the SDK prompt dispatch. Otherwise build_wave_prompt is
    called with wave="Scaffold" and raises
    ``Unsupported wave prompt requested: Scaffold``."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")
    # Find the reachable main loop inside
    # _execute_milestone_waves_with_stack_contract.
    reachable_header = "async def _execute_milestone_waves_with_stack_contract"
    assert reachable_header in text
    fn_start = text.index(reachable_header)
    fn_end = text.find("\nasync def ", fn_start + 1)
    body = text[fn_start : fn_end if fn_end > 0 else None]

    # Must have the explicit skip-continue for the Scaffold slot.
    pattern = re.compile(
        r'if\s+wave_letter\s*==\s*"Scaffold"\s*:\s*\n'
        r'\s+wave_index\s*\+=\s*1\s*\n'
        r'\s+continue',
    )
    assert pattern.search(body), (
        "No ``if wave_letter == \"Scaffold\": continue`` found in the "
        "main wave loop of _execute_milestone_waves_with_stack_contract. "
        "Without this guard, build_wave_prompt fires for wave=\"Scaffold\" "
        "and raises ``Unsupported wave prompt requested: Scaffold`` — "
        "the exact smoke-#4 regression. Restore the guard or document "
        "why it was removed."
    )


def test_scaffold_continue_is_after_scaffolder_block() -> None:
    """The ``continue`` must appear AFTER the scaffolder block, not
    before — otherwise the scaffolder + verifier never run at the
    ``"Scaffold"`` iteration and we regress to smoke-#2/#3 behaviour."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")

    scaffolder_marker = "_save_wave_artifact(scaffold_artifact, cwd"
    continue_pattern = re.compile(
        r'if\s+wave_letter\s*==\s*"Scaffold"\s*:\s*\n'
        r'\s+wave_index\s*\+=\s*1\s*\n'
        r'\s+continue',
    )
    scaffolder_pos = text.index(scaffolder_marker)
    continue_match = continue_pattern.search(text)
    assert continue_match, "scaffold continue guard not present"
    assert continue_match.start() > scaffolder_pos, (
        "``if wave_letter == \"Scaffold\": continue`` appears BEFORE "
        "the scaffolder's ``_save_wave_artifact`` call — the scaffolder "
        "cannot have run yet. Move the continue guard after the "
        "scaffolder block."
    )


# ---------------------------------------------------------------------------
# Sanity: build_wave_prompt still lacks a "Scaffold" handler
# ---------------------------------------------------------------------------


def test_build_wave_prompt_raises_for_scaffold_letter() -> None:
    """Confirms the underlying dispatch table has no Scaffold handler
    — the fix prevents the loop from *calling* build_wave_prompt with
    that letter; it does not add a stub handler. build_wave_prompt's
    internal normaliser uppercases ``wave`` → the error mentions
    ``SCAFFOLD``."""
    from types import SimpleNamespace

    from agent_team_v15.agents import build_wave_prompt

    with pytest.raises(ValueError, match=r"Unsupported wave prompt requested: SCAFFOLD"):
        build_wave_prompt(
            wave="Scaffold",
            milestone=SimpleNamespace(id="milestone-1", feature_refs=[], ac_refs=[]),
            ir={},
            wave_artifacts={},
            dependency_artifacts=None,
            scaffolded_files=[],
            config=None,
            task="",
        )
