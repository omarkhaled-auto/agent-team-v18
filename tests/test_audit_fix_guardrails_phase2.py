"""Phase 2 audit-fix-loop guardrail fixtures.

Goal: cross-milestone test-surface lock + per-fix subset rerun.

Covers Acceptance Criteria from
``docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md`` §E:

- AC1: At milestone COMPLETE, evidence ledger records test-surface +
  pass_rate baseline.
- AC2: Per-fix rerun invokes Playwright with positional file paths
  targeting only the AC's test surface.
- AC3: If subset rerun regresses an AC outside the current finding's
  surface, raise lock violation (do not silently consume).
- AC4: Pinned JSON snapshot tolerates Playwright reporter schema drift on
  TestStatus only.

Also lands the Risk #17 [NEW — Session 2] fix for
``_parse_playwright_failures`` reading the wrong status field.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# These imports point at the public API Phase 2 lands. If they fail at
# import time the whole file collects as ``ImportError`` — that's the
# expected initial-red state per §0.3 TDD step 1.
from agent_team_v15.audit_models import AuditFinding
from agent_team_v15.evidence_ledger import (
    ACEvidenceEntry,
    EvidenceLedger,
)
from agent_team_v15.fix_executor import (
    CrossMilestoneLockViolation,
    _parse_playwright_failures,
    run_regression_check,
)


SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "playwright_json_snapshot.json"


# ---------------------------------------------------------------------------
# Risk #17 fix — _parse_playwright_failures reads result.status, not
# test.status. The snapshot has 5 specs:
#   - login (passed)            → test.status=expected,    result.status=passed
#   - checkout (failed)         → test.status=unexpected,  result.status=failed
#   - settings (skipped)        → test.status=skipped,     result.status=skipped
#   - search (flaky-recovered)  → test.status=flaky,       last result.status=passed
#   - metrics (timedOut)        → test.status=unexpected,  result.status=timedOut
# Expected failures = checkout + metrics. The flaky-recovered spec must
# NOT be reported because its LAST attempt passed.
# ---------------------------------------------------------------------------


def test_parse_playwright_failures_reads_per_result_status() -> None:
    """Risk #17 fix: parser uses results[].status (TestStatus enum), not
    tests[].status (outcome aggregate).
    """
    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")
    failures = _parse_playwright_failures(snapshot)
    assert failures == [
        "metrics chart loads within budget",
        "user can complete checkout flow",
    ], (
        "Expected only the failed/timedOut specs. Got: "
        f"{failures!r}. If this includes 'user can search products' the "
        "parser is treating flaky-recovered as failed. If it includes "
        "'user can log in' the parser is treating outcome=expected as "
        "failed (the original Risk #17 bug)."
    )


def test_parse_playwright_failures_warns_and_returns_empty_on_invalid_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``--reporter=json`` is set but stdout is not parseable JSON,
    we must NOT regex-scrape titles (the original fallback was too
    permissive — see Issue B in Phase 2 sequential-thinking notes).
    """
    bad_output = 'Error in test runner\n{"title": "this should not be matched"}\n'
    with caplog.at_level("WARNING"):
        failures = _parse_playwright_failures(bad_output)
    assert failures == [], (
        "Parser must fail-loud on non-JSON, not regex-scrape. Got: "
        f"{failures!r}"
    )


def test_playwright_snapshot_pin_locks_status_enum() -> None:
    """AC4 — schema-drift guard. Asserts:
      * top-level keys present (config/suites/errors/stats);
      * every test.status is in the outcome enum
        {expected, unexpected, flaky, skipped};
      * every result.status is in the TestStatus enum
        {passed, failed, timedOut, skipped, interrupted}.
    If Playwright drifts EITHER enum, this test fails LOUD so the parser
    can be re-validated.
    """
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert set(payload.keys()) >= {"config", "suites", "errors", "stats"}

    OUTCOME_ENUM = {"expected", "unexpected", "flaky", "skipped"}
    RESULT_ENUM = {"passed", "failed", "timedOut", "skipped", "interrupted"}

    def walk(node: dict) -> None:
        for spec in node.get("specs", []) or []:
            for test in spec.get("tests", []) or []:
                assert test.get("status") in OUTCOME_ENUM, (
                    f"test.status={test.get('status')!r} not in {OUTCOME_ENUM}"
                )
                for result in test.get("results", []) or []:
                    assert result.get("status") in RESULT_ENUM, (
                        f"result.status={result.get('status')!r} not in {RESULT_ENUM}"
                    )
        for child in node.get("suites", []) or []:
            walk(child)

    for suite in payload["suites"]:
        walk(suite)


# ---------------------------------------------------------------------------
# AC1 — at milestone COMPLETE, evidence ledger records test-surface +
# pass_rate baseline. The lookup helper exposes locked surface to the
# regression checker.
# ---------------------------------------------------------------------------


def test_evidence_ledger_persists_test_surface_baseline(tmp_path: Path) -> None:
    """AC1 — ``record_milestone_baseline`` writes test_surface + pass_rate
    fields into ACEvidenceEntry, persistent across reload.
    """
    ledger = EvidenceLedger(tmp_path / "evidence")
    ledger.record_milestone_baseline(
        "milestone-1",
        {
            "AC-1": ["e2e/tests/login.spec.ts", "tests/test_login.py"],
            "AC-2": ["e2e/tests/checkout.spec.ts"],
        },
        pass_rate=100.0,
    )
    # Reload from disk to confirm round-trip.
    reloaded = EvidenceLedger(tmp_path / "evidence")
    reloaded.load_all()
    entry_ac1 = reloaded.get_entry("AC-1")
    entry_ac2 = reloaded.get_entry("AC-2")
    assert entry_ac1 is not None and isinstance(entry_ac1, ACEvidenceEntry)
    assert entry_ac1.test_surface == [
        "e2e/tests/login.spec.ts",
        "tests/test_login.py",
    ]
    assert entry_ac1.pass_rate == 100.0
    assert entry_ac2 is not None and entry_ac2.test_surface == [
        "e2e/tests/checkout.spec.ts"
    ]


def test_evidence_ledger_locked_test_surface_returns_only_pass_acs(
    tmp_path: Path,
) -> None:
    """AC1 — the lock surface is the union of test_surface paths from
    completed (PASS-verdict) ACs. Failed/partial ACs are not locked
    because their tests are presumed already-broken.
    """
    ledger = EvidenceLedger(tmp_path / "evidence")
    ledger.record_milestone_baseline(
        "milestone-1",
        {"AC-1": ["e2e/tests/login.spec.ts"]},
        pass_rate=100.0,
    )
    # Manually mark AC-2 as FAIL — it shouldn't appear in the lock surface.
    ledger.record_milestone_baseline(
        "milestone-1",
        {"AC-2": ["e2e/tests/checkout.spec.ts"]},
        pass_rate=50.0,
    )
    entry_ac2 = ledger.get_entry("AC-2")
    assert entry_ac2 is not None
    entry_ac2.verdict = "FAIL"
    ledger._save_entry(entry_ac2)  # noqa: SLF001 — test-internal access

    locked = ledger.get_locked_test_surface()
    assert "AC-1" in locked
    assert locked["AC-1"] == ["e2e/tests/login.spec.ts"]
    assert "AC-2" not in locked


# ---------------------------------------------------------------------------
# AC1 attribution — sibling_test_files derives test paths from
# AuditFinding.primary_file using basename + parent-dir heuristic.
# ---------------------------------------------------------------------------


def _make_finding(primary_file: str) -> AuditFinding:
    return AuditFinding(
        finding_id="F1",
        auditor="scorer",
        requirement_id="AC-1",
        verdict="FAIL",
        severity="HIGH",
        summary="x",
        evidence=[f"{primary_file}:1 -- description"],
        remediation="fix it",
    )


def test_sibling_test_files_uses_basename_for_named_files() -> None:
    finding = _make_finding("apps/web/components/login.tsx")
    siblings = finding.sibling_test_files
    assert "e2e/tests/login.spec.ts" in siblings
    assert any(s.endswith("test_login.py") for s in siblings)


def test_sibling_test_files_uses_parent_dir_for_generic_filenames() -> None:
    """Next.js convention: apps/web/login/page.tsx → use 'login' (parent
    dir name) not 'page' (basename) since 'page.tsx' is repeated across
    routes.
    """
    finding = _make_finding("apps/web/login/page.tsx")
    siblings = finding.sibling_test_files
    assert "e2e/tests/login.spec.ts" in siblings
    # The naive basename heuristic would emit page.spec.ts which is too
    # generic — must NOT appear.
    assert "e2e/tests/page.spec.ts" not in siblings


def test_sibling_test_files_returns_empty_for_blank_primary_file() -> None:
    finding = _make_finding("")
    assert finding.sibling_test_files == []


# ---------------------------------------------------------------------------
# AC2 — per-fix rerun uses positional file args, scoped to the lock subset.
# ---------------------------------------------------------------------------


def test_run_regression_check_subset_rerun_passes_positional_args(
    tmp_path: Path,
) -> None:
    """AC2 — when ``test_surface_lock`` is provided, the Playwright
    invocation includes the lock paths as positional args before
    ``--reporter=json``.
    """
    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "login.spec.ts").write_text("// stub", encoding="utf-8")

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.fix_executor.subprocess.run", side_effect=fake_run):
        run_regression_check(
            cwd=str(tmp_path),
            previously_passing_acs=["AC-1"],
            config=SimpleNamespace(),
            test_surface_lock=["e2e/tests/login.spec.ts"],
        )

    cmd = captured["cmd"]
    # Positional file path must appear before the --reporter=json flag,
    # exactly per Playwright's CLI contract.
    assert "e2e/tests/login.spec.ts" in cmd
    assert "--reporter=json" in cmd
    # Path index must be earlier than --reporter (positional then flags).
    assert cmd.index("e2e/tests/login.spec.ts") < cmd.index("--reporter=json")


# ---------------------------------------------------------------------------
# AC3 — cross-milestone lock violation: subset rerun regresses a test
# OUTSIDE the current finding's surface → raise.
# ---------------------------------------------------------------------------


def test_run_regression_check_raises_lock_violation_outside_finding_surface(
    tmp_path: Path,
) -> None:
    """AC3 — synthetic 2-milestone scenario: M1 owns login.spec.ts,
    M2's audit-fix targets checkout.spec.ts. A subset rerun shows
    login.spec.ts FAIL — that's an M(N+1) regression of M(N)'s surface,
    which is the M25-disaster scenario. Must raise loud, not silently
    consume.
    """
    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "login.spec.ts").write_text("// stub", encoding="utf-8")
    (e2e_dir / "checkout.spec.ts").write_text("// stub", encoding="utf-8")

    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout=snapshot, stderr="")

    # Map snapshot's failed-spec titles to AC IDs via product IR. The
    # parser returns "user can complete checkout flow" + "metrics chart
    # loads within budget"; we bind those to AC-CHECKOUT and AC-METRICS.
    ir_dir = tmp_path / ".agent-team" / "product-ir"
    ir_dir.mkdir(parents=True)
    (ir_dir / "product.ir.json").write_text(
        json.dumps(
            {
                "acceptance_criteria": [
                    {"id": "AC-CHECKOUT", "text": "user complete checkout"},
                    {"id": "AC-METRICS", "text": "metrics chart loads"},
                    {"id": "AC-LOGIN", "text": "user log in"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with patch("agent_team_v15.fix_executor.subprocess.run", side_effect=fake_run):
        # Finding owns AC-CHECKOUT only. A regression in AC-METRICS is
        # OUTSIDE the finding's surface → raise.
        with pytest.raises(CrossMilestoneLockViolation) as excinfo:
            run_regression_check(
                cwd=str(tmp_path),
                previously_passing_acs=["AC-CHECKOUT", "AC-METRICS"],
                config=SimpleNamespace(),
                test_surface_lock=[
                    "e2e/tests/checkout.spec.ts",
                    "e2e/tests/dashboard.spec.ts",
                ],
                finding_id="F1",
                finding_surface=["e2e/tests/checkout.spec.ts"],
            )
    msg = str(excinfo.value)
    # The violation must name BOTH the finding ID and the regressed AC
    # outside its scope so operators know what blew up.
    assert "F1" in msg
    assert "AC-METRICS" in msg


def test_run_regression_check_does_not_raise_when_regression_is_inside_finding_surface(
    tmp_path: Path,
) -> None:
    """AC3 inverse — regressions WITHIN the finding's own surface are
    expected churn (the fix-loop is iterating on its own test surface).
    They are reported via the return value, not raised.
    """
    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "checkout.spec.ts").write_text("// stub", encoding="utf-8")

    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout=snapshot, stderr="")

    ir_dir = tmp_path / ".agent-team" / "product-ir"
    ir_dir.mkdir(parents=True)
    (ir_dir / "product.ir.json").write_text(
        json.dumps(
            {
                "acceptance_criteria": [
                    {"id": "AC-CHECKOUT", "text": "user complete checkout"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with patch("agent_team_v15.fix_executor.subprocess.run", side_effect=fake_run):
        regressed = run_regression_check(
            cwd=str(tmp_path),
            previously_passing_acs=["AC-CHECKOUT"],
            config=SimpleNamespace(),
            test_surface_lock=["e2e/tests/checkout.spec.ts"],
            finding_id="F1",
            finding_surface=["e2e/tests/checkout.spec.ts"],
        )
    assert regressed == ["AC-CHECKOUT"]


def test_run_regression_check_back_compat_with_no_lock_args(tmp_path: Path) -> None:
    """Backward compatibility: existing callers in coordinated_builder.py
    (lines 1177, 1918) and fix_executor.py (lines 301, 433) pass only
    cwd/previously_passing_acs/config. The new keyword-only args must
    default sensibly so those callers don't break.
    """
    # No e2e/tests dir → returns [] without ever shelling out.
    assert (
        run_regression_check(
            cwd=str(tmp_path),
            previously_passing_acs=["AC-1"],
            config=SimpleNamespace(),
        )
        == []
    )
