"""Ordering regression: scaffold verifier fires BEFORE scaffolder runs.

Pinned down by ``build-final-smoke-20260418-054004``. The wave executor
gates the scaffold verifier on ``wave_letter == "A"`` (wave_executor.py
around line 4297), but the pre-wave scaffolder is gated on the wave
returned by ``_scaffolding_start_wave(template)`` — which is ``"B"`` for
``full_stack`` and ``backend_only`` templates.

Execution order for ``full_stack`` therefore is:

  Wave A
    -> agent writes schema + architecture artefacts
    -> compile check (noop on M1, passes)
    -> scaffold verifier fires           <-- HERE, 39+ files MISSING
    -> verdict FAIL
    -> milestone aborted
  Wave B  (never reached)
    -> scaffolder would have run here and emitted the 40+ foundation files

The verifier is checking state that does not exist yet by design. Two
complementary fixes are possible:

  A. Guard Wave A verifier with ``scaffolding_completed`` — it then no-ops
     whenever the template schedules scaffolding for a later wave.
  B. Move the verifier invocation to fire immediately after the
     scaffolder completes (so it validates the scaffolder's output at
     the actual emission boundary).

The tests below pin contracts that both fixes must satisfy; the
ordering-invariant test uses grep on ``wave_executor.py`` so it fires
if a future refactor recreates the misordering.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15.wave_executor import _scaffolding_start_wave


# ---------------------------------------------------------------------------
# Template -> scaffolding-start-wave contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template,expected",
    [
        # Post-fix (phase-final-scaffold-wave-dispatch): the scaffolder
        # now fires at the dedicated ``"Scaffold"`` slot for every
        # template that has one in WAVE_SEQUENCES. Pre-fix values were
        # "B" / "D" — see the module docstring for the ordering-bug
        # chain that this change resolves.
        ("full_stack", "Scaffold"),
        ("backend_only", "Scaffold"),
        ("frontend_only", "Scaffold"),
        ("unknown", None),
    ],
)
def test_scaffolding_start_wave_contract(template: str, expected: str | None) -> None:
    """Captures the post-fix wave-to-template mapping.

    Before the smoke-#4 dispatch fix, this helper returned "B"/"B"/"D"
    — which left the explicit ``"Scaffold"`` slot in each sequence
    unhandled. The loop would reach ``"Scaffold"`` first and
    ``build_wave_prompt`` would raise ``Unsupported wave prompt
    requested: SCAFFOLD`` before the scaffolder ever ran. The fix
    points this helper at ``"Scaffold"`` so the existing scaffolder
    block fires at the right iteration; the loop then ``continue``\\ s
    past the Scaffold slot to avoid SDK dispatch."""
    assert _scaffolding_start_wave(template) == expected


# ---------------------------------------------------------------------------
# Structural invariants on wave_executor.py
# ---------------------------------------------------------------------------


_WAVE_EXECUTOR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "wave_executor.py"
)


def test_wave_a_verifier_does_not_fire_before_scaffolder() -> None:
    """The Wave A scaffold-verifier call site must either:

      * gate on ``scaffolding_completed`` (skip when scaffolder hasn't run), OR
      * not exist at all (moved to after the scaffolder).

    Failing either option is the regression we just shipped.
    """
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")

    # Find every block that conditions on `wave_letter == "A"` and also
    # calls `_maybe_run_scaffold_verifier`. If such a block exists, it
    # MUST gate on `scaffolding_completed` as well — otherwise the
    # ordering bug recurs.
    verifier_call_pattern = re.compile(
        r'_maybe_run_scaffold_verifier\s*\(',
        re.MULTILINE,
    )

    for match in verifier_call_pattern.finditer(text):
        window_start = max(0, match.start() - 1500)
        window = text[window_start : match.start()]

        if 'wave_letter == "A"' not in window:
            # This call site is not gated on Wave A — fine, assume it
            # runs at the right boundary (after scaffolding).
            continue

        # This call site IS gated on Wave A. It must also gate on
        # scaffolding_completed to avoid firing before the scaffolder.
        if "scaffolding_completed" not in window:
            pytest.fail(
                "Scaffold-verifier call at offset "
                f"{match.start()} is gated on `wave_letter == 'A'` "
                "but NOT on `scaffolding_completed`. For full_stack / "
                "backend_only templates, scaffolding runs before Wave "
                "B, so firing the verifier after Wave A compile checks "
                "state that does not exist yet — the exact regression "
                "observed in build-final-smoke-20260418-054004. "
                "Add `and scaffolding_completed` to the guard, or move "
                "the verifier to fire after the scaffolder completes."
            )


def test_at_least_one_verifier_call_site_exists() -> None:
    """Sanity: verifier must still be wired somewhere. If the fix above
    removes all call sites, the N-13 gate is gone entirely."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")
    assert "_maybe_run_scaffold_verifier(" in text, (
        "Scaffold-verifier is not called anywhere in wave_executor.py — "
        "N-13 gate has been removed inadvertently."
    )


# ---------------------------------------------------------------------------
# scaffolding_completed semantics
# ---------------------------------------------------------------------------


def test_scaffolding_completed_false_until_start_wave() -> None:
    """Trace invariant: in the main wave loop, ``scaffolding_completed``
    starts False (unless a prior SCAFFOLD artefact was loaded) and only
    flips True when we hit ``scaffolding_start_wave``.

    This is the guard fact the verifier needs to respect: at Wave A of
    a fresh M1 run under full_stack, scaffolding_completed must still
    be False when the Wave A compile/verifier block is entered.
    """
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")

    # Find the assignment and the flip, and confirm the flip is inside
    # the block that conditions on scaffolding_start_wave.
    init_pat = re.compile(
        r"scaffolding_completed\s*=\s*bool\s*\(\s*scaffold_artifact\s*\)"
    )
    flip_pat = re.compile(
        r"scaffolding_completed\s*=\s*True",
    )
    inits = list(init_pat.finditer(text))
    flips = list(flip_pat.finditer(text))

    assert inits, "scaffolding_completed initializer not found"
    assert flips, "scaffolding_completed flip-to-True not found"

    # Every flip site should appear *after* the initializer in source.
    for flip in flips:
        window_before = text[max(0, flip.start() - 2500) : flip.start()]
        assert "scaffolding_start_wave == wave_letter" in window_before, (
            "scaffolding_completed flips True at offset "
            f"{flip.start()} but is not guarded by "
            "`scaffolding_start_wave == wave_letter` — the flip must only "
            "happen when the scaffolder actually runs."
        )
