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
