"""End-to-end contract: scaffold verifier fires AT the scaffolder boundary.

Companion to ``test_scaffold_verifier_ordering.py`` (which pins the bug
via grep). These tests exercise the runtime path — when the scaffolder
runs, the verifier runs immediately after and abort-on-FAIL is wired
through ``MilestoneWaveResult.error_wave = "SCAFFOLD"``.

The tests stub ``_maybe_run_scaffold_verifier`` so behaviour is pinned
without depending on the real ownership contract or filesystem state.
"""

from __future__ import annotations

import re
from pathlib import Path


_WAVE_EXECUTOR = (
    Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "wave_executor.py"
)


def test_verifier_call_appears_after_save_wave_artifact_scaffold() -> None:
    """The new call site must appear inside the ``scaffolding_completed =
    True`` block AND after the SCAFFOLD artefact is persisted. If this
    layout ever shifts above the save, the verifier would run against a
    half-written ownership contract."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")

    # Locate the second-loop scaffolder's artefact save.
    save_calls = [
        m for m in re.finditer(
            r'_save_wave_artifact\s*\(\s*scaffold_artifact\s*,\s*cwd',
            text,
        )
    ]
    assert save_calls, (
        "Could not find _save_wave_artifact(scaffold_artifact, ...) "
        "call — wave executor restructured?"
    )

    # At least one of those save calls must be followed (within 80
    # lines) by a _maybe_run_scaffold_verifier call — that's the new
    # boundary. Checks the second loop (live code); the first loop is
    # dead (unreachable, see return-await at line ~3455).
    verifier_found_after_save = False
    for save in save_calls:
        verifier_idx = text.find("_maybe_run_scaffold_verifier(", save.end())
        fingerprint_idx = text.find(
            "_maybe_run_scaffold_ownership_fingerprint(",
            save.end(),
        )
        if verifier_idx != -1 and fingerprint_idx != -1 and verifier_idx < fingerprint_idx:
            verifier_found_after_save = True
            break

    assert verifier_found_after_save, (
        "Scaffold verifier is not called between _save_wave_artifact("
        "scaffold_artifact, ...) and ownership fingerprinting in "
        "any scaffolder block. The N-13 gate has moved again — review "
        "docstring at the call site."
    )


def test_scaffold_verifier_fail_uses_scaffold_error_wave() -> None:
    """Failure path must label ``result.error_wave = 'SCAFFOLD'`` so
    downstream telemetry attributes the failure to the scaffolder
    boundary, not to a confusing generic wave name."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")
    # Find the block that creates a WaveResult with wave="SCAFFOLD" in
    # the verifier-fail path.
    pattern = re.compile(
        r'WaveResult\s*\(\s*\n?\s*wave="SCAFFOLD"\s*,\s*\n?\s*success=False\b',
        re.DOTALL,
    )
    assert pattern.search(text), (
        "No `WaveResult(wave='SCAFFOLD', success=False, ...)` block "
        "found — the verifier-fail path must emit a SCAFFOLD wave_result."
    )

    # And error_wave must be set to "SCAFFOLD" too.
    assert re.search(
        r'result\.error_wave\s*=\s*"SCAFFOLD"',
        text,
    ), (
        "`result.error_wave = \"SCAFFOLD\"` not found — failure-attribution "
        "line missing, will confuse smoke diagnostics."
    )


def test_verifier_not_called_from_wave_a_post_compile_block() -> None:
    """The old Wave A post-compile call site must be removed. Having BOTH
    locations live doubles the cost and creates a race where the
    post-compile verifier sees the scaffolder's output mid-write (if the
    scaffolder ran earlier in the same milestone for a different wave)."""
    text = _WAVE_EXECUTOR.read_text(encoding="utf-8")

    # The signature of the old block was:
    #   if (wave_letter == "A" and compile_result.passed and
    #       _get_v18_value(config, "scaffold_verifier_enabled", False)):
    #       verifier_error = _maybe_run_scaffold_verifier(...)
    #
    # Find any `_maybe_run_scaffold_verifier` preceded within 300 chars
    # by the Wave A compile discriminator.
    for match in re.finditer(r"_maybe_run_scaffold_verifier\s*\(", text):
        window = text[max(0, match.start() - 400) : match.start()]
        if (
            'wave_letter == "A"' in window
            and "compile_result.passed" in window
        ):
            import pytest
            pytest.fail(
                "Old Wave A post-compile scaffold-verifier call site is "
                "still present at offset "
                f"{match.start()}. Remove — it runs before the scaffolder "
                "has produced anything for full_stack / backend_only "
                "templates (see build-final-smoke-20260418-054004)."
            )
