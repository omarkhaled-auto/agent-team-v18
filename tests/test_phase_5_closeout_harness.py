"""Tests for the Phase 5 closeout-smoke harness scripts.

Covers:

* :mod:`scripts.phase_5_closeout.k2_evaluator` — strict-mode filtering,
  diagnostic discovery, decision branches (Outcome A / Outcome B),
  summary rendering.
* :mod:`scripts.phase_5_closeout.fault_injection` — default-off
  invariant, context-manager arm/disarm, one-shot vs persistent
  semantics, concurrent-arm refusal, fixture-replay variant for O.4.6,
  post-hoc analyzer for O.4.10.

Per the Phase 5 closeout-smoke plan: harness tooling is default-off
and live-smoke-only for O.4.5-O.4.11. These tests verify the harness
itself; they do NOT replace operator-driven live smoke evidence.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
import time
from pathlib import Path

import pytest

from scripts.phase_5_closeout import fault_injection, k2_evaluator


# ---------------------------------------------------------------------------
# K.2 evaluator
# ---------------------------------------------------------------------------


def _write_diag(
    path: Path,
    *,
    milestone_id: str,
    divergences: list[dict],
    strict_mode: str | None = None,
    extra: dict | None = None,
) -> None:
    payload: dict = {
        "phase": "5.8a",
        "milestone_id": milestone_id,
        "smoke_id": path.parent.parent.parent.parent.name,
        "generated_at": "2026-04-29T00:00:00Z",
        "metrics": {
            "schemas_in_spec": len(divergences) + 1,
            "exports_in_client": len(divergences) + 1,
            "divergences_detected_total": len(divergences),
            "unique_divergence_classes": sorted(
                {d["divergence_class"] for d in divergences}
            ),
            "divergences_correlated_with_compile_failures": 0,
        },
        "divergences": divergences,
        "unsupported_polymorphic_schemas": [],
        "tooling": {
            "ts_parser": "node-typescript-ast",
            "ts_parser_version": "5.5.0",
            "error": "",
        },
    }
    if strict_mode is not None:
        payload["strict_mode"] = strict_mode
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_smoke_dir(
    batch_root: Path,
    smoke_id: str,
    *,
    milestones: list[tuple[str, list[dict]]],
    strict_mode: str | None = None,
) -> Path:
    """Create batch_root/<smoke_id>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json."""

    smoke_dir = batch_root / smoke_id
    for milestone_id, divergences in milestones:
        diag_path = (
            smoke_dir
            / ".agent-team"
            / "milestones"
            / milestone_id
            / "PHASE_5_8A_DIAGNOSTIC.json"
        )
        _write_diag(
            diag_path,
            milestone_id=milestone_id,
            divergences=divergences,
            strict_mode=strict_mode,
        )
    return smoke_dir


def test_extract_strict_mode_recognises_multiple_keys():
    """Phase 5 closeout — strict_mode field accepted at top, metrics, tooling, or via tsc alias."""

    assert k2_evaluator._extract_strict_mode({"strict_mode": "ON"}) == "ON"
    assert k2_evaluator._extract_strict_mode({"strict_mode": "off"}) == "OFF"
    assert k2_evaluator._extract_strict_mode({"strict_mode": True}) == "ON"
    assert k2_evaluator._extract_strict_mode({"strict_mode": "false"}) == "OFF"
    assert k2_evaluator._extract_strict_mode({"strict_mode": 1}) == "ON"
    assert k2_evaluator._extract_strict_mode({"strict_mode": 0}) == "OFF"
    assert k2_evaluator._extract_strict_mode(
        {"tsc_strict_check_enabled": True}
    ) == "ON"
    assert k2_evaluator._extract_strict_mode({"metrics": {"strict_mode": "ON"}}) == "ON"
    assert k2_evaluator._extract_strict_mode({"tooling": {"strict_mode": "OFF"}}) == "OFF"
    # Missing field → None.
    assert k2_evaluator._extract_strict_mode({}) is None
    assert k2_evaluator._extract_strict_mode({"phase": "5.8a"}) is None


def test_discover_diagnostics_walks_per_milestone_layout(tmp_path):
    """Phase 5 closeout — discovery walks the canonical Phase 5.8a per-milestone path."""

    _make_smoke_dir(
        tmp_path,
        "smoke-1",
        milestones=[
            ("milestone-1", [{"divergence_class": "missing-export", "schema_name": "Foo"}]),
            ("milestone-2", [{"divergence_class": "type-mismatch", "schema_name": "Bar"}]),
        ],
        strict_mode="ON",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-2",
        milestones=[
            ("milestone-1", []),
        ],
        strict_mode="OFF",
    )

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    assert len(entries) == 3
    assert {e.milestone_id for e in entries} == {"milestone-1", "milestone-2"}
    assert {e.smoke_run_dir.name for e in entries} == {"smoke-1", "smoke-2"}


def test_discover_diagnostics_skips_malformed_json(tmp_path):
    """Phase 5 closeout — malformed JSON is silently skipped (evaluator never crashes)."""

    bad = (
        tmp_path
        / "smoke-1"
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / "PHASE_5_8A_DIAGNOSTIC.json"
    )
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ malformed: json", encoding="utf-8")

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    assert entries == []


def test_filter_for_k2_strict_on_only_by_default(tmp_path):
    """Phase 5 closeout — default filter: strict=ON only; warns on OFF + missing."""

    _make_smoke_dir(
        tmp_path,
        "smoke-on",
        milestones=[("milestone-1", [{"divergence_class": "missing-export", "schema_name": "Foo"}])],
        strict_mode="ON",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-off",
        milestones=[("milestone-1", [{"divergence_class": "missing-export", "schema_name": "Bar"}])],
        strict_mode="OFF",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-missing",
        milestones=[("milestone-1", [{"divergence_class": "missing-export", "schema_name": "Baz"}])],
        strict_mode=None,
    )

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    kept, warnings = k2_evaluator._filter_for_k2(entries, include_strict_off=False)

    assert len(kept) == 1
    assert kept[0].smoke_run_dir.name == "smoke-on"
    assert any("OFF" in w for w in warnings)
    assert any("without strict_mode field" in w for w in warnings)


def test_filter_for_k2_include_strict_off_aggregates_all(tmp_path):
    """Phase 5 closeout — --include-strict-off bypasses the filter entirely."""

    _make_smoke_dir(
        tmp_path,
        "smoke-on",
        milestones=[("milestone-1", [])],
        strict_mode="ON",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-off",
        milestones=[("milestone-1", [])],
        strict_mode="OFF",
    )

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    kept, warnings = k2_evaluator._filter_for_k2(entries, include_strict_off=True)

    assert len(kept) == 2
    # Override warning surfaces in the summary.
    assert any("include-strict-off ACTIVE" in w for w in warnings)


def test_evaluate_outcome_a_when_three_distinct_dtos_share_class(tmp_path):
    """Phase 5 closeout — §K.2 predicate satisfied → Outcome A (Phase 5.8b ships)."""

    # 3 distinct DTOs sharing class "missing-export" across the batch.
    _make_smoke_dir(
        tmp_path,
        "smoke-1",
        milestones=[
            (
                "milestone-1",
                [
                    {"divergence_class": "missing-export", "schema_name": "Foo"},
                    {"divergence_class": "missing-export", "schema_name": "Bar"},
                ],
            )
        ],
        strict_mode="ON",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-2",
        milestones=[
            (
                "milestone-1",
                [{"divergence_class": "missing-export", "schema_name": "Baz"}],
            )
        ],
        strict_mode="ON",
    )

    status, summary, _kept, _all = k2_evaluator.evaluate(
        batch_root=tmp_path,
        smoke_batch_id="test-batch",
        head_sha="34bab7a",
        correlated_threshold=3,
        include_strict_off=False,
    )
    assert status == "A"
    assert "Outcome A" in summary
    assert "Phase 5.8b ships" in summary
    assert "34bab7a" in summary


def test_evaluate_outcome_b_when_predicate_not_satisfied(tmp_path):
    """Phase 5 closeout — §K.2 predicate NOT satisfied → Outcome B (Wave A spec-quality)."""

    # 2 DTOs sharing class (below threshold) + 1 different class.
    _make_smoke_dir(
        tmp_path,
        "smoke-1",
        milestones=[
            (
                "milestone-1",
                [
                    {"divergence_class": "missing-export", "schema_name": "Foo"},
                    {"divergence_class": "type-mismatch", "schema_name": "Bar"},
                ],
            )
        ],
        strict_mode="ON",
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-2",
        milestones=[
            (
                "milestone-1",
                [{"divergence_class": "missing-export", "schema_name": "Baz"}],
            )
        ],
        strict_mode="ON",
    )

    status, summary, _kept, _all = k2_evaluator.evaluate(
        batch_root=tmp_path,
        smoke_batch_id="test-batch",
        head_sha=None,
        correlated_threshold=3,
        include_strict_off=False,
    )
    assert status == "B"
    assert "Outcome B" in summary
    assert "Wave A spec-quality" in summary
    assert "unrecorded" in summary  # head_sha=None surfaces explicitly


def test_evaluate_indeterminate_when_all_strict_off_under_default_filter(tmp_path):
    """Phase 5 closeout — all-strict=OFF under default filter is INDETERMINATE, not Outcome B.

    Reviewer-correction lock: zero kept diagnostics after strict-mode
    filtering must NOT silently produce Outcome B (which would close
    R-#42 from zero countable evidence). Per approver: missing labels
    do not count toward closure.
    """

    _make_smoke_dir(
        tmp_path,
        "smoke-off",
        milestones=[
            (
                "milestone-1",
                [
                    {"divergence_class": "missing-export", "schema_name": "Foo"},
                    {"divergence_class": "missing-export", "schema_name": "Bar"},
                    {"divergence_class": "missing-export", "schema_name": "Baz"},
                ],
            )
        ],
        strict_mode="OFF",
    )

    status, summary, _kept, _all = k2_evaluator.evaluate(
        batch_root=tmp_path,
        smoke_batch_id="test-batch",
        head_sha="34bab7a",
        correlated_threshold=3,
        include_strict_off=False,
    )
    assert status == "indeterminate"
    assert "Indeterminate" in summary
    assert "no decision" in summary.lower()
    # Decision section MUST NOT carry the Outcome B finalising sentence
    # (which would close R-#42). The phrase appears only inside
    # next-steps prose ("requires an explicit Outcome A or Outcome B")
    # — that's allowed; the decision sentence itself isn't.
    assert "Phase 5.8b does NOT ship" not in summary
    assert "close R-#42 via Wave A" not in summary
    # Excluded evidence is surfaced.
    assert "strict_mode=OFF" in summary


def test_evaluate_indeterminate_when_all_diagnostics_missing_strict_mode(tmp_path):
    """Phase 5 closeout — all-missing-strict_mode is INDETERMINATE, not Outcome B.

    Reviewer-correction lock: this is the most likely failure mode at
    HEAD ``34bab7a`` since the writer doesn't yet record strict_mode.
    The evaluator must surface this loudly rather than silently
    closing R-#42 from no evidence.
    """

    # Diagnostics WITHOUT strict_mode field (today's writer's output).
    _make_smoke_dir(
        tmp_path,
        "smoke-1",
        milestones=[
            (
                "milestone-1",
                [{"divergence_class": "missing-export", "schema_name": "Foo"}],
            )
        ],
        strict_mode=None,
    )
    _make_smoke_dir(
        tmp_path,
        "smoke-2",
        milestones=[
            (
                "milestone-1",
                [{"divergence_class": "missing-export", "schema_name": "Bar"}],
            )
        ],
        strict_mode=None,
    )

    status, summary, _kept, _all = k2_evaluator.evaluate(
        batch_root=tmp_path,
        smoke_batch_id="test-batch",
        head_sha="34bab7a",
        correlated_threshold=3,
        include_strict_off=False,
    )
    assert status == "indeterminate"
    assert "Indeterminate" in summary
    # Decision section MUST NOT close R-#42; the next-steps prose may
    # still mention "Outcome A or Outcome B" descriptively.
    assert "Phase 5.8b does NOT ship" not in summary
    assert "close R-#42 via Wave A" not in summary
    assert "missing strict_mode" in summary or "without strict_mode" in summary


def test_evaluate_main_exit_2_when_all_diagnostics_excluded(tmp_path):
    """Phase 5 closeout — main exits 2 when all diagnostics excluded by filter (not 1)."""

    _make_smoke_dir(
        tmp_path,
        "smoke-1",
        milestones=[
            (
                "milestone-1",
                [{"divergence_class": "missing-export", "schema_name": "Foo"}],
            )
        ],
        strict_mode=None,  # missing → excluded by default filter
    )

    rc = k2_evaluator.main([
        "--batch-root", str(tmp_path),
        "--smoke-batch-id", "indeterminate-batch",
        "--print-only",
    ])
    # Exit 2 = indeterminate (NOT exit 1 which would be Outcome B).
    assert rc == 2


def test_evaluate_include_strict_off_promotes_indeterminate_to_decision(tmp_path):
    """Phase 5 closeout — operator override aggregates everything → A or B, not indeterminate."""

    # All-strict=OFF + override → decision drives off raw data.
    _make_smoke_dir(
        tmp_path,
        "smoke-off",
        milestones=[
            (
                "milestone-1",
                [
                    {"divergence_class": "missing-export", "schema_name": "Foo"},
                    {"divergence_class": "missing-export", "schema_name": "Bar"},
                    {"divergence_class": "missing-export", "schema_name": "Baz"},
                ],
            )
        ],
        strict_mode="OFF",
    )

    status, summary, _kept, _all = k2_evaluator.evaluate(
        batch_root=tmp_path,
        smoke_batch_id="test-batch",
        head_sha="34bab7a",
        correlated_threshold=3,
        include_strict_off=True,
    )
    # Override aggregates strict=OFF as countable; predicate satisfied.
    assert status == "A"
    assert "OPERATOR-OVERRIDE include-strict-off" in summary


def test_evaluate_main_returns_2_when_no_diagnostics_found(tmp_path):
    """Phase 5 closeout — empty batch root exits 2 (operator must investigate)."""

    rc = k2_evaluator.main([
        "--batch-root", str(tmp_path),
        "--smoke-batch-id", "empty",
        "--print-only",
    ])
    assert rc == 2


def test_evaluator_counts_writer_emitted_strict_mode_under_default_filter(tmp_path):
    """Phase 5 closeout — writer-emitted strict_mode artifact survives the default filter.

    End-to-end: write a real PHASE_5_8A_DIAGNOSTIC.json via
    ``write_phase_5_8a_diagnostic(strict_mode=True)`` and confirm the
    K.2 evaluator parses + KEEPS it under the default strict=ON filter.
    Locks the writer/evaluator handshake the closeout-smoke plan
    depends on (approver constraint #1 contract: every artifact MUST
    record strict_mode and the evaluator MUST NOT exclude
    properly-recorded ON values).
    """

    from agent_team_v15.cross_package_diagnostic import (
        DIVERGENCE_CLASS_MISSING_EXPORT,
        DiagnosticOutcome,
        DivergenceRecord,
        TOOLING_PARSER_NODE_TS_AST,
        write_phase_5_8a_diagnostic,
    )

    smoke_dir = tmp_path / "smoke-1"
    outcome = DiagnosticOutcome(
        divergences=[
            DivergenceRecord(
                divergence_class=DIVERGENCE_CLASS_MISSING_EXPORT,
                schema_name="Foo",
                property_name="",
                spec_value="schema",
                client_value="",
                client_file="",
                client_line=0,
                details="missing-export",
            )
        ],
        metrics={
            "schemas_in_spec": 1,
            "exports_in_client": 0,
            "divergences_detected_total": 1,
            "unique_divergence_classes": [DIVERGENCE_CLASS_MISSING_EXPORT],
        },
        tooling={
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        unsupported_polymorphic_schemas=[],
    )
    write_phase_5_8a_diagnostic(
        cwd=str(smoke_dir),
        milestone_id="milestone-1",
        outcome=outcome,
        smoke_id="smoke-1",
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=True,
    )

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    assert len(entries) == 1
    assert entries[0].strict_mode == "ON"

    # Default filter keeps strict=ON artifacts (no warnings about this
    # one, since it has the field and is ON).
    kept, warnings = k2_evaluator._filter_for_k2(entries, include_strict_off=False)
    assert len(kept) == 1
    assert kept[0].milestone_id == "milestone-1"
    assert all("milestone-1" not in w for w in warnings)


def test_evaluator_excludes_writer_emitted_strict_mode_off_under_default_filter(tmp_path):
    """Phase 5 closeout — writer-emitted strict=OFF artifact correctly excluded under default filter."""

    from agent_team_v15.cross_package_diagnostic import (
        DiagnosticOutcome,
        TOOLING_PARSER_NODE_TS_AST,
        write_phase_5_8a_diagnostic,
    )

    smoke_dir = tmp_path / "smoke-off"
    outcome = DiagnosticOutcome(
        divergences=[],
        metrics={
            "schemas_in_spec": 0,
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        },
        tooling={
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        unsupported_polymorphic_schemas=[],
    )
    write_phase_5_8a_diagnostic(
        cwd=str(smoke_dir),
        milestone_id="milestone-1",
        outcome=outcome,
        smoke_id="smoke-off",
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=False,
    )

    entries = k2_evaluator._discover_diagnostics(tmp_path)
    assert len(entries) == 1
    assert entries[0].strict_mode == "OFF"

    kept, warnings = k2_evaluator._filter_for_k2(entries, include_strict_off=False)
    assert kept == []
    assert any("strict_mode=OFF" in w for w in warnings)


# ---------------------------------------------------------------------------
# Fault injection — default-off invariant
# ---------------------------------------------------------------------------


def test_fault_injection_is_default_off_on_import():
    """Phase 5 closeout — importing the harness MUST NOT arm any injection."""

    assert fault_injection.is_armed() is False
    assert fault_injection.matched_count() == 0


def test_maybe_inject_delay_is_noop_when_unarmed():
    """Phase 5 closeout — maybe_inject_delay is a free pass when no injection is armed."""

    async def run() -> None:
        # Should return immediately without sleeping.
        await fault_injection.maybe_inject_delay(role="wave", wave_letter="A")

    asyncio.run(run())
    assert fault_injection.matched_count() == 0


def test_arm_first_call_delay_one_shot_then_disarms():
    """Phase 5 closeout — one-shot injection fires once then auto-disarms."""

    async def run() -> int:
        async with fault_injection.arm_first_call_delay(
            role="wave", wave_letter="A", delay_seconds=0.01,
        ):
            assert fault_injection.is_armed() is True
            # First call: matches, delays.
            await fault_injection.maybe_inject_delay(role="wave", wave_letter="A")
            # After first match, one-shot disarms automatically.
            assert fault_injection.is_armed() is False
            # Second call: no-op.
            await fault_injection.maybe_inject_delay(role="wave", wave_letter="A")
            return fault_injection.matched_count()

    matches = asyncio.run(run())
    assert matches == 1
    assert fault_injection.is_armed() is False  # context-exit also resets


def test_arm_first_call_delay_role_mismatch_does_not_fire():
    """Phase 5 closeout — role-scoped injection only matches the configured role."""

    async def run() -> int:
        async with fault_injection.arm_first_call_delay(
            role="audit_fix", wave_letter="", delay_seconds=0.01,
        ):
            await fault_injection.maybe_inject_delay(role="wave", wave_letter="A")
            await fault_injection.maybe_inject_delay(role="compile_fix", wave_letter="D")
            return fault_injection.matched_count()

    assert asyncio.run(run()) == 0


def test_arm_pipe_pause_persistent_fires_on_every_dispatch():
    """Phase 5 closeout — persistent pipe-pause matches every dispatch (drives O.4.8)."""

    async def run() -> int:
        async with fault_injection.arm_pipe_pause_on_every_dispatch(delay_seconds=0.01):
            for _ in range(5):
                await fault_injection.maybe_inject_delay(role="wave", wave_letter="A")
            return fault_injection.matched_count()

    assert asyncio.run(run()) == 5
    assert fault_injection.is_armed() is False  # disarm on context-exit


def test_concurrent_arm_raises_runtime_error():
    """Phase 5 closeout — concurrent injections refused (each closure row needs clean smoke)."""

    async def run() -> None:
        async with fault_injection.arm_first_call_delay(delay_seconds=0.01):
            with pytest.raises(RuntimeError, match="already armed"):
                async with fault_injection.arm_first_call_delay(delay_seconds=0.01):
                    pass  # pragma: no cover

    asyncio.run(run())


def test_replay_m3_fixture_returns_none_when_no_idle(tmp_path):
    """Phase 5 closeout — fixture replay returns 'none' when no productive-tool-idle."""

    fixture = tmp_path / "BUILD_LOG.txt"
    fixture.write_text(
        textwrap.dedent(
            """
            2026-04-28 09:00:00,000 INFO foo: bar
            2026-04-28 09:00:01,000 INFO foo: baz
            """
        ).strip(),
        encoding="utf-8",
    )

    outcome = fault_injection.replay_m3_productive_tool_idle_fixture(fixture)
    assert outcome.predicted_timeout_kind == "none"
    assert outcome.productive_event_count == 0


def test_replay_m3_fixture_detects_simulated_idle_at_threshold(tmp_path):
    """Phase 5 closeout — fixture replay flags a simulated >1200s gap as tool-call-idle."""

    fixture = tmp_path / "BUILD_LOG.txt"
    # One commandExecution start at t=0, then 1300s of agentMessage events.
    lines = ["2026-04-28 09:00:00,000 INFO wave_executor: item/started commandExecution"]
    for i in range(1, 1310):
        ts_minutes, ts_seconds = divmod(i, 60)
        ts_hours, ts_minutes = divmod(ts_minutes, 60)
        ts_str = f"{9 + ts_hours:02d}:{ts_minutes:02d}:{ts_seconds:02d}"
        lines.append(
            f"2026-04-28 {ts_str},000 INFO wave_executor: item/agentMessage/delta agentMessage"
        )
    fixture.write_text("\n".join(lines), encoding="utf-8")

    outcome = fault_injection.replay_m3_productive_tool_idle_fixture(
        fixture, tool_call_idle_timeout_seconds=1200,
    )
    assert outcome.predicted_timeout_kind == "tool-call-idle"
    assert outcome.productive_event_count >= 1
    # Fire time should be > 1200s (the threshold) and < 1310s (last event).
    assert 1200 <= outcome.predicted_fire_time_s < 1310


def test_replay_m3_fixture_missing_path_raises(tmp_path):
    """Phase 5 closeout — replay raises FileNotFoundError when fixture absent."""

    with pytest.raises(FileNotFoundError, match="Fixture not found"):
        fault_injection.replay_m3_productive_tool_idle_fixture(tmp_path / "nope.txt")


def test_analyze_run_dir_no_state_returns_zero_budget(tmp_path):
    """Phase 5 closeout — empty run-dir analyzes to budget=0 + no violation."""

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.cumulative_wedge_budget == 0
    assert analysis.invariant_holds is True
    assert analysis.bootstrap_hang_reports == []
    assert analysis.codex_path_hang_reports == []


def test_analyze_run_dir_o410_invariant_holds(tmp_path):
    """Phase 5 closeout — Codex hang reports present without bootstrap → invariant holds."""

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"_cumulative_wedge_budget": 0}), encoding="utf-8")
    hang = tmp_path / ".agent-team" / "hang_reports" / "wave-B-2026.json"
    hang.parent.mkdir(parents=True, exist_ok=True)
    hang.write_text(
        json.dumps(
            {
                "timeout_kind": "tool-call-idle",
                "role": "wave",
                "provider": "codex",
            }
        ),
        encoding="utf-8",
    )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is True
    assert analysis.cumulative_wedge_budget == 0
    assert hang in analysis.codex_path_hang_reports
    assert hang not in analysis.bootstrap_hang_reports


def test_analyze_run_dir_o410_invariant_violated_on_codex_bootstrap(tmp_path):
    """Phase 5 closeout — Codex provider + bootstrap timeout_kind = invariant violation (provenance)."""

    hang = tmp_path / ".agent-team" / "hang_reports" / "wave-B-2026.json"
    hang.parent.mkdir(parents=True, exist_ok=True)
    hang.write_text(
        json.dumps(
            {
                "timeout_kind": "bootstrap",
                "role": "wave",
                "provider": "codex",
            }
        ),
        encoding="utf-8",
    )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is False
    assert "O.4.10" in analysis.invariant_violation
    assert "provenance" in analysis.invariant_violation.lower()
    assert "codex" in analysis.invariant_violation.lower()


def test_analyze_run_dir_o410_invariant_violated_on_unattributable_counter(tmp_path):
    """Phase 5 closeout — non-zero counter with no Claude-SDK bootstrap reports = violation.

    Reviewer-correction lock: STATE.json _cumulative_wedge_budget=1 +
    only Codex tool-call-idle hang report MUST violate. The counter
    is non-zero but no Claude-SDK bootstrap wedge accounts for the
    increment — attribution cannot be proven, fail closed.
    """

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"_cumulative_wedge_budget": 1}), encoding="utf-8",
    )
    # Only a Codex tool-call-idle report — no bootstrap report at all.
    hang = tmp_path / ".agent-team" / "hang_reports" / "wave-B-2026.json"
    hang.parent.mkdir(parents=True, exist_ok=True)
    hang.write_text(
        json.dumps(
            {
                "timeout_kind": "tool-call-idle",
                "role": "wave",
                "provider": "codex",
            }
        ),
        encoding="utf-8",
    )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is False
    assert "attribution" in analysis.invariant_violation.lower()
    assert "1" in analysis.invariant_violation  # counter value surfaced
    assert analysis.cumulative_wedge_budget == 1


def test_analyze_run_dir_o410_invariant_holds_with_attributable_counter(tmp_path):
    """Phase 5 closeout — non-zero counter EQUAL to Claude-SDK bootstrap count = invariant holds."""

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"_cumulative_wedge_budget": 2}), encoding="utf-8",
    )
    # Two Claude-SDK bootstrap reports — counter is fully attributable.
    for i in range(2):
        hang = tmp_path / ".agent-team" / "hang_reports" / f"wave-A-{i}.json"
        hang.parent.mkdir(parents=True, exist_ok=True)
        hang.write_text(
            json.dumps(
                {
                    "timeout_kind": "bootstrap",
                    "role": "wave",
                    "provider": "claude",
                }
            ),
            encoding="utf-8",
        )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is True
    assert analysis.cumulative_wedge_budget == 2
    assert len(analysis.bootstrap_hang_reports) == 2


def test_analyze_run_dir_o410_invariant_violated_on_under_attribution(tmp_path):
    """Phase 5 closeout — counter > Claude-SDK bootstrap count = under-attribution violation.

    Reviewer-correction lock #2: the strict §O.4.10 invariant is
    ``cumulative <= len(claude_bootstrap_reports)``. Reviewer's verbatim
    repro: budget=2 with one Claude bootstrap + one Codex tool-call-idle
    must violate (the second increment has no Claude-SDK origin).
    """

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"_cumulative_wedge_budget": 2}), encoding="utf-8",
    )
    # ONE Claude-SDK bootstrap report.
    claude_hang = tmp_path / ".agent-team" / "hang_reports" / "wave-A-claude.json"
    claude_hang.parent.mkdir(parents=True, exist_ok=True)
    claude_hang.write_text(
        json.dumps(
            {
                "timeout_kind": "bootstrap",
                "role": "wave",
                "provider": "claude",
            }
        ),
        encoding="utf-8",
    )
    # PLUS a Codex tool-call-idle (NOT bootstrap; doesn't count toward
    # claude_bootstrap_reports). Counter=2 but only 1 Claude bootstrap
    # → 1 unattributed increment → violation.
    codex_hang = tmp_path / ".agent-team" / "hang_reports" / "wave-B-codex.json"
    codex_hang.write_text(
        json.dumps(
            {
                "timeout_kind": "tool-call-idle",
                "role": "wave",
                "provider": "codex",
            }
        ),
        encoding="utf-8",
    )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is False
    assert "attribution" in analysis.invariant_violation.lower()
    # Violation message must surface the counter value AND the
    # un-attributed delta so the operator can find the source.
    assert "2" in analysis.invariant_violation
    assert "1" in analysis.invariant_violation  # 1 unattributed increment


def test_analyze_run_dir_o410_invariant_zero_budget_zero_reports_holds(tmp_path):
    """Phase 5 closeout — zero counter + zero bootstrap reports = vacuously holds."""

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"_cumulative_wedge_budget": 0}), encoding="utf-8",
    )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is True
    assert analysis.cumulative_wedge_budget == 0


def test_analyze_run_dir_o410_invariant_under_increment_not_violation(tmp_path):
    """Phase 5 closeout — counter < Claude-SDK count is OUTSIDE O.4.10 (different invariant).

    O.4.10 specifically guards against Codex paths incrementing the
    counter. Counter < bootstrap-report count would suggest the
    counter under-incremented (a separate bug class), not that Codex
    snuck an increment in. Surface as informational, not a hard fail.
    """

    state = tmp_path / ".agent-team" / "STATE.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"_cumulative_wedge_budget": 1}), encoding="utf-8",
    )
    # TWO Claude-SDK bootstrap reports but counter only 1 — outside
    # O.4.10's scope (would be a separate "counter under-increments"
    # bug). Analyzer must NOT flag as O.4.10 violation.
    for i in range(2):
        hang = tmp_path / ".agent-team" / "hang_reports" / f"wave-A-{i}.json"
        hang.parent.mkdir(parents=True, exist_ok=True)
        hang.write_text(
            json.dumps(
                {
                    "timeout_kind": "bootstrap",
                    "role": "wave",
                    "provider": "claude",
                }
            ),
            encoding="utf-8",
        )

    analysis = fault_injection.analyze_run_dir_cumulative_wedge_budget(tmp_path)
    assert analysis.invariant_holds is True  # not an O.4.10 violation
    assert analysis.cumulative_wedge_budget == 1
    assert len(analysis.bootstrap_hang_reports) == 2


# ---------------------------------------------------------------------------
# Fault-injection wrapper — env-driven arming + monkey-patch wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def _disarm_fault_injection_after_test():
    """Ensure injection state is reset after every wrapper test.

    Necessary because the wrapper arms the module-level _INJECTION
    singleton; without a teardown, a flaky test could leave a fixture
    armed for subsequent tests.
    """

    yield
    fault_injection._INJECTION.armed = False
    fault_injection._INJECTION.role = ""
    fault_injection._INJECTION.wave_letter = ""
    fault_injection._INJECTION.delay_seconds = 0.0
    fault_injection._INJECTION.persistent = False
    fault_injection._INJECTION.matched_count = 0


def test_wrapper_arm_from_env_no_op_when_mode_unset(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — wrapper passes through cleanly when mode unset."""

    monkeypatch.delenv("PHASE5_INJECT_MODE", raising=False)
    from scripts.phase_5_closeout import fault_injection_wrapper

    assert fault_injection_wrapper._arm_from_env() is False
    assert fault_injection.is_armed() is False


def test_wrapper_arm_from_env_first_call_arms_one_shot(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — first-call mode arms a one-shot injection."""

    monkeypatch.setenv("PHASE5_INJECT_MODE", "first-call")
    monkeypatch.setenv("PHASE5_INJECT_ROLE", "wave")
    monkeypatch.setenv("PHASE5_INJECT_WAVE", "A")
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "0.01")
    from scripts.phase_5_closeout import fault_injection_wrapper

    assert fault_injection_wrapper._arm_from_env() is True
    assert fault_injection.is_armed() is True
    assert fault_injection._INJECTION.role == "wave"
    assert fault_injection._INJECTION.wave_letter == "A"
    assert fault_injection._INJECTION.delay_seconds == 0.01
    assert fault_injection._INJECTION.persistent is False


def test_wrapper_arm_from_env_every_arms_persistent(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — every mode arms a persistent injection."""

    monkeypatch.setenv("PHASE5_INJECT_MODE", "every")
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "0.01")
    from scripts.phase_5_closeout import fault_injection_wrapper

    assert fault_injection_wrapper._arm_from_env() is True
    assert fault_injection.is_armed() is True
    assert fault_injection._INJECTION.persistent is True


def test_wrapper_arm_from_env_rejects_invalid_mode(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — unknown mode raises SystemExit, leaves state clean."""

    monkeypatch.setenv("PHASE5_INJECT_MODE", "bogus")
    from scripts.phase_5_closeout import fault_injection_wrapper

    with pytest.raises(SystemExit):
        fault_injection_wrapper._arm_from_env()
    assert fault_injection.is_armed() is False


def test_wrapper_injected_invoke_calls_maybe_inject_delay_before_real(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — _injected_invoke fires maybe_inject_delay first."""

    from agent_team_v15 import wave_executor
    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_MODE", "first-call")
    monkeypatch.setenv("PHASE5_INJECT_ROLE", "wave")
    monkeypatch.setenv("PHASE5_INJECT_WAVE", "A")
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "0.05")
    fault_injection_wrapper._arm_from_env()

    # Monkey-patch wave_executor._invoke to the wrapper's _injected_invoke
    # for the duration of this test (auto-restored via monkeypatch).
    monkeypatch.setattr(wave_executor, "_invoke", fault_injection_wrapper._injected_invoke)

    call_order: list[str] = []

    async def fake_callee(**kwargs) -> float:
        call_order.append(f"real:role={kwargs.get('role')}/wave={kwargs.get('wave')}")
        return 0.0

    async def run() -> None:
        result = await wave_executor._invoke(fake_callee, role="wave", wave="A")
        assert result == 0.0

    asyncio.run(run())

    # maybe_inject_delay matched the (role=wave, wave=A) injection ⇒
    # matched_count incremented before fake_callee was reached, and the
    # one-shot self-disarmed.
    assert fault_injection.matched_count() == 1
    assert fault_injection.is_armed() is False
    assert call_order == ["real:role=wave/wave=A"]


def test_wrapper_injected_invoke_role_mismatch_skips_delay(
    monkeypatch, _disarm_fault_injection_after_test
):
    """Phase 5 closeout — role mismatch on the injection leaves the call clean."""

    from agent_team_v15 import wave_executor
    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_MODE", "first-call")
    monkeypatch.setenv("PHASE5_INJECT_ROLE", "audit_fix")  # only matches audit_fix
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "10.0")
    fault_injection_wrapper._arm_from_env()
    monkeypatch.setattr(wave_executor, "_invoke", fault_injection_wrapper._injected_invoke)

    async def fake_callee(**kwargs) -> float:
        return 1.5

    async def run() -> float:
        return await wave_executor._invoke(fake_callee, role="wave", wave="A")

    # Wave A → role mismatch with audit_fix injection → no delay fired,
    # call returns immediately.
    result = asyncio.run(run())
    assert result == 1.5
    assert fault_injection.matched_count() == 0
    assert fault_injection.is_armed() is True  # one-shot still armed


# ---------------------------------------------------------------------------
# A1 — Post-commandExecution stall injection (§O.4.6 closure)
# ---------------------------------------------------------------------------
#
# Drives Phase 5.7 tier-3 productive-tool-idle wedge live by sleeping AFTER
# an ``item/completed commandExecution`` event reaches the wave_executor's
# ``_WaveWatchdogState.record_progress``. Default-off; armed via
# ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY``. Hooks the codex_appserver-side
# ``_emit_progress`` so tier 3 (1200s) catches the wedge BEFORE tier 4
# (5400s) kicks in.


@pytest.fixture
def _disarm_post_cmdexec_after_test():
    """Reset the post-cmdexec injection state after every wrapper test.

    Mirrors ``_disarm_fault_injection_after_test`` for the second
    injection state machine. Required because the wrapper monkey-patches
    ``codex_appserver._emit_progress``; without a teardown a flaky test
    could leave the patch installed for subsequent tests.
    """

    yield
    fault_injection._POST_CMDEXEC_INJECTION.armed = False
    fault_injection._POST_CMDEXEC_INJECTION.delay_seconds = 0.0
    fault_injection._POST_CMDEXEC_INJECTION.persistent = False
    fault_injection._POST_CMDEXEC_INJECTION.matched_count = 0


def test_post_cmdexec_unset_env_is_pass_through(
    monkeypatch, _disarm_post_cmdexec_after_test
):
    """A1 — Wrapper passes through cleanly when
    ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` is unset.

    Locks the default-off contract: importing the wrapper + calling
    ``_arm_post_cmdexec_from_env()`` with no env var leaves the
    injection state untouched and ``codex_appserver._emit_progress``
    unpatched.
    """

    monkeypatch.delenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", raising=False)
    from scripts.phase_5_closeout import fault_injection_wrapper

    assert fault_injection_wrapper._arm_post_cmdexec_from_env() is False
    assert fault_injection.is_post_cmdexec_armed() is False
    assert fault_injection._POST_CMDEXEC_INJECTION.matched_count == 0


def test_post_cmdexec_arms_only_on_completed_commandexec(
    monkeypatch, _disarm_post_cmdexec_after_test
):
    """A1 — When armed, the hook fires the configured delay ONLY on
    ``item/completed commandExecution`` events.

    The strictest acceptance for §O.4.6: ``last_productive_tool_name=
    "commandExecution"`` requires the productive event to be a
    Codex commandExecution (not a Claude tool_use, not a Codex
    agentMessage). This test confirms the filter is exactly that.
    """

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.02")
    from scripts.phase_5_closeout import fault_injection_wrapper

    assert fault_injection_wrapper._arm_post_cmdexec_from_env() is True
    assert fault_injection.is_post_cmdexec_armed() is True
    assert fault_injection._POST_CMDEXEC_INJECTION.delay_seconds == 0.02
    assert fault_injection._POST_CMDEXEC_INJECTION.persistent is False

    # Matching event fires the delay + self-disarm (one-shot).
    async def run_match() -> None:
        await fault_injection.maybe_inject_post_cmdexec_delay(
            message_type="item/completed",
            tool_name="commandExecution",
            event_kind="complete",
        )

    t0 = time.monotonic()
    asyncio.run(run_match())
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.02, f"delay not fired; elapsed={elapsed!r}"
    assert fault_injection.post_cmdexec_matched_count() == 1
    assert fault_injection.is_post_cmdexec_armed() is False  # one-shot self-disarmed


def test_post_cmdexec_non_commandexec_events_do_not_trigger(
    monkeypatch, _disarm_post_cmdexec_after_test
):
    """A1 — Non-commandExecution events (productive Claude tools, Codex
    agentMessage / reasoning, item/started) do NOT trigger the delay.

    The acceptance for §O.4.6 specifies tier-3 fire on
    ``last_productive_tool_name="commandExecution"``. Misfiring on a
    Claude ``tool_use`` (Bash, Edit, etc.) or a Codex agentMessage would
    contaminate the closure evidence with a non-Codex baseline.
    """

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "5.0")
    from scripts.phase_5_closeout import fault_injection_wrapper

    fault_injection_wrapper._arm_post_cmdexec_from_env()
    assert fault_injection.is_post_cmdexec_armed() is True

    # Try non-matching events — none should fire the delay.
    non_matching_cases = [
        # Claude productive tool — wrong message_type.
        dict(message_type="tool_use", tool_name="Bash", event_kind="start"),
        dict(message_type="tool_result", tool_name="", event_kind="complete"),
        # Codex non-productive items.
        dict(message_type="item/started", tool_name="agentMessage", event_kind="start"),
        dict(message_type="item/completed", tool_name="reasoning", event_kind="complete"),
        dict(message_type="item/started", tool_name="commandExecution", event_kind="start"),  # start, not complete
        # Codex protocol-only.
        dict(message_type="turn/started", tool_name="", event_kind="other"),
        dict(message_type="item/agentMessage/delta", tool_name="agentMessage", event_kind="other"),
        # Wrong event_kind on commandExecution.
        dict(message_type="item/completed", tool_name="commandExecution", event_kind="other"),
    ]

    async def run_non_matches() -> None:
        for case in non_matching_cases:
            await fault_injection.maybe_inject_post_cmdexec_delay(**case)

    t0 = time.monotonic()
    asyncio.run(run_non_matches())
    elapsed = time.monotonic() - t0

    # 8 non-matching calls × no delay = should complete in well under
    # the configured 5.0s. Generous bound (1.0s) to absorb scheduling.
    assert elapsed < 1.0, f"non-matching events fired delay; elapsed={elapsed!r}"
    assert fault_injection.post_cmdexec_matched_count() == 0
    assert fault_injection.is_post_cmdexec_armed() is True  # still armed (no match)


def test_post_cmdexec_existing_bootstrap_cap_injections_still_work(
    monkeypatch, _disarm_fault_injection_after_test, _disarm_post_cmdexec_after_test
):
    """A1 — The post-cmdexec extension does NOT regress existing
    PHASE5_INJECT_MODE-driven SDK-callback injections (bootstrap respawn
    + cumulative cap).

    Locks the composition: both injections can be armed simultaneously,
    they target independent state machines (``_INJECTION`` vs
    ``_POST_CMDEXEC_INJECTION``), and the wrapper's monkey-patches
    apply to disjoint surfaces (``wave_executor._invoke`` vs
    ``codex_appserver._emit_progress``).
    """

    from agent_team_v15 import wave_executor
    from scripts.phase_5_closeout import fault_injection_wrapper

    # Arm BOTH simultaneously.
    monkeypatch.setenv("PHASE5_INJECT_MODE", "every")
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "0.01")
    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.02")

    sdk_armed = fault_injection_wrapper._arm_from_env()
    post_armed = fault_injection_wrapper._arm_post_cmdexec_from_env()
    assert sdk_armed is True
    assert post_armed is True
    assert fault_injection.is_armed() is True
    assert fault_injection.is_post_cmdexec_armed() is True
    assert fault_injection._INJECTION.persistent is True
    assert fault_injection._POST_CMDEXEC_INJECTION.persistent is False

    # Exercise the SDK-callback injection (existing path).
    monkeypatch.setattr(
        wave_executor, "_invoke", fault_injection_wrapper._injected_invoke,
    )

    async def fake_callee(**kwargs) -> float:
        return 9.99

    async def run_sdk() -> float:
        return await wave_executor._invoke(fake_callee, role="wave", wave="A")

    result = asyncio.run(run_sdk())
    assert result == 9.99
    assert fault_injection.matched_count() == 1  # SDK injection still fires
    assert fault_injection.is_armed() is True  # persistent, still armed

    # Exercise the post-cmdexec injection (new path) — independently armed.
    async def run_post() -> None:
        await fault_injection.maybe_inject_post_cmdexec_delay(
            message_type="item/completed",
            tool_name="commandExecution",
            event_kind="complete",
        )

    asyncio.run(run_post())
    assert fault_injection.post_cmdexec_matched_count() == 1
    assert fault_injection.is_post_cmdexec_armed() is False  # one-shot disarmed
    # SDK injection state untouched by post-cmdexec fire.
    assert fault_injection.matched_count() == 1
    assert fault_injection.is_armed() is True


def test_post_cmdexec_arm_from_env_rejects_non_positive(
    monkeypatch, _disarm_post_cmdexec_after_test
):
    """A1 — Negative / zero / non-numeric values are rejected with
    SystemExit; state stays clean."""

    from scripts.phase_5_closeout import fault_injection_wrapper

    for bad in ("0", "-1", "0.0", "-0.5"):
        monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", bad)
        with pytest.raises(SystemExit):
            fault_injection_wrapper._arm_post_cmdexec_from_env()
        assert fault_injection.is_post_cmdexec_armed() is False

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "not-a-number")
    with pytest.raises(SystemExit):
        fault_injection_wrapper._arm_post_cmdexec_from_env()
    assert fault_injection.is_post_cmdexec_armed() is False


def test_post_cmdexec_injected_emit_progress_calls_original_first(
    monkeypatch, _disarm_post_cmdexec_after_test
):
    """A1 — ``_injected_emit_progress`` MUST call the original
    ``codex_appserver._emit_progress`` BEFORE firing the post-cmdexec
    delay.

    Order is load-bearing: the original delivers the event to the
    wave_executor's ``_WaveWatchdogState.record_progress``, which clears
    ``pending_tool_starts`` (matching item/completed) and refreshes
    ``last_tool_call_monotonic``. The delay then stalls the
    codex_appserver event loop. If the order were reversed, tier-3's
    ``not state.pending_tool_starts`` gate would fail and tier 2
    (orphan-tool, 400s) would fire — wrong tier, wrong threshold.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.02")
    fault_injection_wrapper._arm_post_cmdexec_from_env()

    # Capture the order of operations: did the original fire BEFORE or
    # AFTER maybe_inject_post_cmdexec_delay?
    order: list[str] = []

    async def fake_progress_callback(**kwargs):
        order.append(f"original:msg={kwargs.get('message_type')}/tool={kwargs.get('tool_name')}")

    original = fault_injection_wrapper._original_emit_progress
    delay_fired = {"hit": False}
    real_inject = fault_injection.maybe_inject_post_cmdexec_delay

    async def spy_inject(**kwargs):
        order.append(f"delay:msg={kwargs.get('message_type')}/tool={kwargs.get('tool_name')}")
        delay_fired["hit"] = True
        await real_inject(**kwargs)

    monkeypatch.setattr(fault_injection, "maybe_inject_post_cmdexec_delay", spy_inject)

    async def run() -> None:
        await fault_injection_wrapper._injected_emit_progress(
            fake_progress_callback,
            message_type="item/completed",
            tool_name="commandExecution",
            tool_id="call_test_1",
            event_kind="complete",
        )

    asyncio.run(run())

    # Original must fire BEFORE the delay hook.
    assert len(order) == 2, f"unexpected order length: {order}"
    assert order[0].startswith("original:"), f"original must fire first; order={order}"
    assert order[1].startswith("delay:"), f"delay must fire second; order={order}"
    assert delay_fired["hit"] is True


# ---------------------------------------------------------------------------
# A1b — Live progress-path hooks (_process_streaming_event +
# next_notification). These exercise the actual app-server command-event
# path that delivers ``item/completed commandExecution`` notifications to
# the wave_executor, NOT the ``_emit_progress`` path the original A1
# hook targeted.
#
# The live path:
#
#   _wait_for_turn_completion (async)
#     → message = await client.next_notification()   ← A1b inject delay
#     → _process_streaming_event(message, ..., progress_callback)  ← A1b
#                                                                    set
#                                                                    flag
#       → _fire_progress_sync(progress_callback, "item/completed",
#                             "commandExecution", item_id, "complete")
#         → progress_callback(...)  (= wave_executor's record_progress)
#
# A1b sets a side-channel flag in the sync ``_process_streaming_event``
# (after the original fires the callback) and consumes it in the async
# ``next_notification`` BEFORE awaiting the next real event — stalling
# the drain loop while wave_executor's poll-task fires tier 3.


@pytest.fixture
def _disarm_post_cmdexec_live_after_test():
    """Reset the live-path side-channel flag in addition to the standard
    ``_disarm_post_cmdexec_after_test`` cleanup."""

    yield
    fault_injection._POST_CMDEXEC_INJECTION.armed = False
    fault_injection._POST_CMDEXEC_INJECTION.delay_seconds = 0.0
    fault_injection._POST_CMDEXEC_INJECTION.persistent = False
    fault_injection._POST_CMDEXEC_INJECTION.matched_count = 0
    # Clear the A1b side-channel flag too — independent of the
    # injection state machine.
    from scripts.phase_5_closeout import fault_injection_wrapper
    fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending = False


def test_post_cmdexec_live_path_flag_set_after_completed_commandexec(
    monkeypatch, _disarm_post_cmdexec_live_after_test
):
    """A1b — ``_injected_process_streaming_event`` MUST set the
    ``_PENDING_CMDEXEC_DELAY.pending`` flag after delivering an
    ``item/completed commandExecution`` event AND set it AFTER the
    original sync ``_process_streaming_event`` has run.

    Order is load-bearing: the original calls ``_fire_progress_sync``
    which dispatches to ``progress_callback`` (wave_executor's
    record_progress). That call clears ``pending_tool_starts``, refreshes
    ``last_tool_call_monotonic``, and increments ``tool_call_event_count``.
    Only AFTER that state update does the flag fire — so the next-
    notification consumer can stall the drain loop knowing tier 3's
    gate ``not state.pending_tool_starts`` is satisfied.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.05")
    fault_injection_wrapper._arm_post_cmdexec_from_env()

    delivered_events: list[dict] = []

    def fake_progress_callback(*, message_type, tool_name, tool_id, event_kind, **_):
        delivered_events.append({
            "message_type": message_type,
            "tool_name": tool_name,
            "tool_id": tool_id,
            "event_kind": event_kind,
        })

    # Stub the sync original so we can observe order without depending on
    # the real codex_appserver state machine.
    from agent_team_v15 import codex_appserver

    original_invocations: list[str] = []

    def _spy_original(event, watchdog, tokens, progress_callback,
                      messages=None, capture_session=None):
        original_invocations.append("original_called")
        # Mirror the real _process_streaming_event behaviour for
        # item/completed: dispatch to progress_callback BEFORE the flag
        # is set by the wrapper.
        method = event.get("method", "")
        if method == "item/completed":
            params = event.get("params", {})
            item = params.get("item", {})
            progress_callback(
                message_type=method,
                tool_name=item.get("name", ""),
                tool_id=item.get("id", ""),
                event_kind="complete",
            )

    monkeypatch.setattr(
        fault_injection_wrapper, "_original_process_streaming_event", _spy_original,
    )

    # Real item/completed commandExecution from a Codex app-server
    # capture.log (shape mirrored exactly).
    event = {
        "method": "item/completed",
        "params": {
            "item": {
                "id": "call_TestCmdExec_1",
                "name": "commandExecution",
                "type": "commandExecution",
            },
        },
    }

    fault_injection_wrapper._injected_process_streaming_event(
        event, watchdog=None, tokens=None,
        progress_callback=fake_progress_callback,
    )

    # Original called → callback delivered → flag THEN set.
    assert original_invocations == ["original_called"]
    assert len(delivered_events) == 1
    assert delivered_events[0]["message_type"] == "item/completed"
    assert delivered_events[0]["tool_name"] == "commandExecution"
    assert delivered_events[0]["event_kind"] == "complete"
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is True


def test_post_cmdexec_live_path_non_commandexec_does_not_set_flag(
    monkeypatch, _disarm_post_cmdexec_live_after_test
):
    """A1b — non-commandExecution events MUST NOT set the side-channel
    flag, even when the injection is armed.

    Acceptance for §O.4.6 specifies tier-3 fire on
    ``last_productive_tool_name="commandExecution"``. Misfiring on a
    Codex agentMessage / reasoning / item/agentMessage/delta or on an
    item/started commandExecution (start, not complete) would produce
    wrong-shape evidence.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper
    from agent_team_v15 import codex_appserver

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "5.0")
    fault_injection_wrapper._arm_post_cmdexec_from_env()

    # Stub the original to a no-op so we observe the flag-setting decision
    # in isolation.
    monkeypatch.setattr(
        fault_injection_wrapper,
        "_original_process_streaming_event",
        lambda *a, **k: None,
    )

    non_matching_events: list[dict] = [
        # Codex non-productive items.
        {"method": "item/started", "params": {"item": {"id": "1", "name": "agentMessage"}}},
        {"method": "item/started", "params": {"item": {"id": "2", "name": "reasoning"}}},
        # commandExecution start (not completed).
        {"method": "item/started", "params": {"item": {"id": "3", "name": "commandExecution"}}},
        # Reasoning complete (wrong tool).
        {"method": "item/completed", "params": {"item": {"id": "4", "name": "reasoning"}}},
        # AgentMessage complete (wrong tool).
        {"method": "item/completed", "params": {"item": {"id": "5", "name": "agentMessage"}}},
        # Delta event.
        {"method": "item/agentMessage/delta", "params": {"itemId": "6"}},
        # Protocol-only.
        {"method": "turn/started", "params": {}},
        # Empty method.
        {"method": "", "params": {}},
    ]

    for ev in non_matching_events:
        fault_injection_wrapper._injected_process_streaming_event(
            ev, watchdog=None, tokens=None,
            progress_callback=lambda **_: None,
        )

    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False, (
        "non-cmdexec events must NOT set the side-channel flag"
    )
    assert fault_injection.is_post_cmdexec_armed() is True, (
        "non-cmdexec events must NOT consume the one-shot arm"
    )


def test_post_cmdexec_live_path_unarmed_does_not_set_flag(
    monkeypatch, _disarm_post_cmdexec_live_after_test
):
    """A1b — when no injection is armed, the live-path wrapper is a thin
    pass-through that does NOT set the flag even on a matching event.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper
    from agent_team_v15 import codex_appserver

    monkeypatch.delenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", raising=False)
    # No arm.
    assert fault_injection.is_post_cmdexec_armed() is False

    monkeypatch.setattr(
        fault_injection_wrapper,
        "_original_process_streaming_event",
        lambda *a, **k: None,
    )

    event = {
        "method": "item/completed",
        "params": {"item": {"id": "x", "name": "commandExecution"}},
    }
    fault_injection_wrapper._injected_process_streaming_event(
        event, watchdog=None, tokens=None,
        progress_callback=lambda **_: None,
    )

    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False


def test_post_cmdexec_live_path_next_notification_stalls_then_returns(
    monkeypatch, _disarm_post_cmdexec_live_after_test
):
    """A1b — ``_injected_next_notification`` MUST sleep
    ``delay_seconds`` BEFORE awaiting the real ``next_notification`` when
    the side-channel flag is set, AND reset the flag AND self-disarm the
    one-shot injection on consume.

    Exercises the live drain-loop pause: simulate a sequence of events
    where one is ``item/completed commandExecution``; assert that on the
    NEXT ``next_notification`` call (after the flag was set by
    ``_process_streaming_event``), the wrapper sleeps the configured
    delay before returning the next real event.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.05")
    fault_injection_wrapper._arm_post_cmdexec_from_env()

    # Set the flag manually (would normally be set by
    # _injected_process_streaming_event after item/completed cmdexec).
    fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending = True

    # Fake "real" next_notification — returns a constant event so we
    # can observe the wrapper's pre-delegation sleep without depending
    # on a live transport.
    next_event = {
        "method": "item/started",
        "params": {"item": {"id": "next-after-stall", "name": "agentMessage"}},
    }

    async def fake_original(self):
        return next_event

    monkeypatch.setattr(
        fault_injection_wrapper, "_original_next_notification", fake_original,
    )

    class _StubClient:
        pass

    stub = _StubClient()

    async def run() -> dict:
        return await fault_injection_wrapper._injected_next_notification(stub)

    t0 = time.monotonic()
    result = asyncio.run(run())
    elapsed = time.monotonic() - t0

    assert result == next_event, "next event MUST be returned post-delay"
    assert elapsed >= 0.05, f"delay not awaited; elapsed={elapsed}"
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False, (
        "flag must be reset after consume"
    )
    assert fault_injection.is_post_cmdexec_armed() is False, (
        "one-shot injection must self-disarm after the live-path sleep"
    )
    assert fault_injection.post_cmdexec_matched_count() == 1


def test_post_cmdexec_live_path_next_notification_is_pass_through_when_flag_unset(
    monkeypatch, _disarm_post_cmdexec_live_after_test
):
    """A1b — when ``_PENDING_CMDEXEC_DELAY.pending`` is False, the
    wrapper MUST NOT sleep and MUST simply delegate to the original.
    """

    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "5.0")
    fault_injection_wrapper._arm_post_cmdexec_from_env()
    # Flag NOT set (no prior item/completed cmdexec yet).
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False

    next_event = {"method": "turn/started", "params": {}}

    async def fake_original(self):
        return next_event

    monkeypatch.setattr(
        fault_injection_wrapper, "_original_next_notification", fake_original,
    )

    class _StubClient:
        pass

    async def run() -> dict:
        return await fault_injection_wrapper._injected_next_notification(_StubClient())

    t0 = time.monotonic()
    result = asyncio.run(run())
    elapsed = time.monotonic() - t0

    assert result == next_event
    # No flag → no sleep → should complete fast (well under the 5s
    # configured delay).
    assert elapsed < 1.0, f"non-flagged path took too long; elapsed={elapsed}"
    assert fault_injection.is_post_cmdexec_armed() is True, (
        "one-shot stays armed when flag wasn't set"
    )


def test_post_cmdexec_live_path_end_to_end_drain_loop_stalls(
    monkeypatch, _disarm_post_cmdexec_live_after_test, _disarm_fault_injection_after_test
):
    """A1b — full live-path integration: drive a synthetic drain loop
    through ``_injected_process_streaming_event`` +
    ``_injected_next_notification``. Sequence:

    1. Pre-state: pending_tool_starts has the open commandExecution; no
       productive events on the wave_executor side yet.
    2. Drain delivers ``item/started commandExecution`` — wave_executor
       sets last_tool_call_monotonic, bootstrap_cleared, adds to
       pending_tool_starts. Flag NOT set (start, not complete).
    3. Drain delivers ``item/completed commandExecution`` — wave_executor
       removes from pending_tool_starts, refreshes last_tool_call_monotonic,
       sets last_productive_tool_name="commandExecution", increments
       tool_call_event_count. _injected_process_streaming_event THEN
       sets the side-channel flag.
    4. Drain awaits next_notification — _injected_next_notification
       sees the flag, awaits the post-cmdexec delay, resets the flag,
       and delegates to the original to fetch the next event.

    Asserts that AFTER step 4:
      - state.pending_tool_starts is empty (cleared in step 3)
      - state.last_productive_tool_name == "commandExecution"
      - state.tool_call_event_count == 2 (start + complete are both
        productive per ``_is_productive_tool_event``)
      - the delay was awaited
      - the injection self-disarmed
    """

    from agent_team_v15 import wave_executor
    from agent_team_v15.wave_executor import _WaveWatchdogState
    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.03")
    fault_injection_wrapper._arm_post_cmdexec_from_env()

    state = _WaveWatchdogState()
    progress_callback = state.record_progress

    # Minimal fake of codex_appserver._OrphanWatchdog for the real
    # _process_streaming_event's record_start / record_complete hooks.
    class _FakeOrphanWatchdog:
        def __init__(self):
            self.starts: list[tuple[str, str]] = []
            self.completes: list[str] = []

        def record_start(self, item_id, tool_name, command_summary=None):
            self.starts.append((item_id, tool_name))

        def record_complete(self, item_id):
            self.completes.append(item_id)

    fake_watchdog = _FakeOrphanWatchdog()

    started_event = {
        "method": "item/started",
        "params": {
            "item": {
                "id": "call_E2E_1",
                "name": "commandExecution",
                "type": "commandExecution",
            },
        },
    }
    completed_event = {
        "method": "item/completed",
        "params": {
            "item": {
                "id": "call_E2E_1",
                "name": "commandExecution",
                "type": "commandExecution",
            },
        },
    }

    fault_injection_wrapper._injected_process_streaming_event(
        started_event, watchdog=fake_watchdog, tokens=None,
        progress_callback=progress_callback,
    )
    # After start: bootstrap_cleared True, pending_tool_starts has entry,
    # last_tool_call_monotonic > 0, flag NOT set (start ≠ complete).
    assert state.bootstrap_cleared is True
    assert "call_E2E_1" in state.pending_tool_starts
    assert state.last_tool_call_monotonic > 0.0
    assert state.last_productive_tool_name == "commandExecution"
    assert state.tool_call_event_count == 1
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False

    fault_injection_wrapper._injected_process_streaming_event(
        completed_event, watchdog=fake_watchdog, tokens=None,
        progress_callback=progress_callback,
    )
    # After complete: pending_tool_starts cleared,
    # last_tool_call_monotonic refreshed, count incremented, flag SET.
    assert "call_E2E_1" not in state.pending_tool_starts
    assert state.tool_call_event_count == 2
    assert state.last_productive_tool_name == "commandExecution"
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is True

    # Now simulate the next drain-loop iteration's
    # ``await client.next_notification()`` call. Replace the original
    # with a fake that returns a follow-up agentMessage event.
    next_event = {
        "method": "item/started",
        "params": {"item": {"id": "after-stall", "name": "agentMessage"}},
    }

    async def fake_original(self):
        return next_event

    monkeypatch.setattr(
        fault_injection_wrapper, "_original_next_notification", fake_original,
    )

    class _StubClient:
        pass

    async def drain_next() -> dict:
        return await fault_injection_wrapper._injected_next_notification(_StubClient())

    t0 = time.monotonic()
    result = asyncio.run(drain_next())
    elapsed = time.monotonic() - t0

    assert result == next_event
    assert elapsed >= 0.03, f"delay not awaited; elapsed={elapsed}"
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is False
    assert fault_injection.is_post_cmdexec_armed() is False  # one-shot disarmed
    # Crucially: pending_tool_starts STAYS empty across the stall — the
    # tier-3 gate ``not state.pending_tool_starts`` holds throughout.
    assert "call_E2E_1" not in state.pending_tool_starts


def test_post_cmdexec_existing_bootstrap_cap_injections_still_work_with_live_path(
    monkeypatch, _disarm_fault_injection_after_test, _disarm_post_cmdexec_live_after_test
):
    """A1b — verify the live-path hooks compose with the existing
    PHASE5_INJECT_MODE-driven SDK-callback injections (bootstrap respawn
    + cumulative cap).

    Both injections target disjoint surfaces (``wave_executor._invoke``
    for SDK-callback; ``codex_appserver._process_streaming_event`` +
    ``next_notification`` for post-cmdexec). The shared
    ``_POST_CMDEXEC_INJECTION`` and ``_INJECTION`` state machines are
    independent — no shared side-channel except the
    ``_PENDING_CMDEXEC_DELAY`` flag, which the SDK-callback path doesn't
    touch.
    """

    from agent_team_v15 import wave_executor
    from scripts.phase_5_closeout import fault_injection_wrapper

    monkeypatch.setenv("PHASE5_INJECT_MODE", "every")
    monkeypatch.setenv("PHASE5_INJECT_DELAY", "0.01")
    monkeypatch.setenv("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "0.02")

    sdk = fault_injection_wrapper._arm_from_env()
    post = fault_injection_wrapper._arm_post_cmdexec_from_env()
    assert sdk is True and post is True

    # Exercise SDK-callback side.
    monkeypatch.setattr(
        wave_executor, "_invoke", fault_injection_wrapper._injected_invoke,
    )

    async def fake_callee(**_):
        return 7.7

    async def run_sdk() -> float:
        return await wave_executor._invoke(fake_callee, role="wave", wave="A")

    result = asyncio.run(run_sdk())
    assert result == 7.7
    assert fault_injection.matched_count() == 1

    # Exercise live post-cmdexec side.
    monkeypatch.setattr(
        fault_injection_wrapper,
        "_original_process_streaming_event",
        lambda *a, **k: None,
    )
    completed_event = {
        "method": "item/completed",
        "params": {"item": {"id": "cmpx", "name": "commandExecution"}},
    }
    fault_injection_wrapper._injected_process_streaming_event(
        completed_event, watchdog=None, tokens=None,
        progress_callback=lambda **_: None,
    )
    assert fault_injection_wrapper._PENDING_CMDEXEC_DELAY.pending is True

    next_event = {"method": "turn/started", "params": {}}

    async def fake_next(self):
        return next_event

    monkeypatch.setattr(
        fault_injection_wrapper, "_original_next_notification", fake_next,
    )

    class _Stub:
        pass

    async def run_live() -> dict:
        return await fault_injection_wrapper._injected_next_notification(_Stub())

    asyncio.run(run_live())
    assert fault_injection.post_cmdexec_matched_count() == 1
    assert fault_injection.is_post_cmdexec_armed() is False
    # SDK injection state untouched by live-path fire.
    assert fault_injection.matched_count() == 1
    assert fault_injection.is_armed() is True  # SDK injection persistent
