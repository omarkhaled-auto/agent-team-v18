"""Tests for D-10 phantom false-positive suppression.

Covers FalsePositive serialization, filter_false_positives fingerprinting,
and build_cycle_suppression_set auto-suppression.
"""
from agent_team_v15.audit_models import (
    AuditFinding,
    FalsePositive,
    filter_false_positives,
    build_cycle_suppression_set,
    _finding_line_range,
)


def _make_finding(finding_id, file_path="", line=0, end_line=0):
    """Create a minimal AuditFinding for testing."""
    f = AuditFinding(
        finding_id=finding_id,
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="warning",
        summary="test finding",
        source="deterministic",
    )
    # Set file_path and line as dynamic attributes (matching production pattern)
    f.file_path = file_path
    f.line = line
    f.end_line = end_line or line
    return f


# ---------------------------------------------------------------------------
# FalsePositive serialization
# ---------------------------------------------------------------------------

def test_false_positive_serialization_with_fingerprint():
    fp = FalsePositive(
        finding_id="DB-004",
        reason="Has database default",
        suppressed_by="auto",
        timestamp="2026-04-17T00:00:00Z",
        file_path="src/entity/user.entity.ts",
        line_range=(10, 15),
    )
    d = fp.to_dict()
    assert d["file_path"] == "src/entity/user.entity.ts"
    assert d["line_range"] == [10, 15]

    # Round-trip
    fp2 = FalsePositive.from_dict(d)
    assert fp2.finding_id == "DB-004"
    assert fp2.file_path == "src/entity/user.entity.ts"
    assert fp2.line_range == (10, 15)
    assert fp2.suppressed_by == "auto"


# ---------------------------------------------------------------------------
# filter_false_positives
# ---------------------------------------------------------------------------

def test_filter_id_only_suppresses_all_instances():
    """FalsePositive with finding_id only (no file_path) suppresses all matching findings."""
    findings = [
        _make_finding("DB-004", file_path="src/a.ts", line=10),
        _make_finding("DB-004", file_path="src/b.ts", line=20),
        _make_finding("DB-005", file_path="src/c.ts", line=30),
    ]
    suppressions = [
        FalsePositive(finding_id="DB-004", reason="Not applicable"),
    ]
    result = filter_false_positives(findings, suppressions)
    assert len(result) == 1
    assert result[0].finding_id == "DB-005"


def test_filter_fingerprint_suppresses_specific_instance():
    """FalsePositive with file_path + line_range only suppresses the matching instance."""
    findings = [
        _make_finding("DB-004", file_path="src/a.ts", line=10),
        _make_finding("DB-004", file_path="src/b.ts", line=20),
    ]
    suppressions = [
        FalsePositive(
            finding_id="DB-004",
            reason="Has DB default",
            file_path="src/a.ts",
            line_range=(10, 10),
        ),
    ]
    result = filter_false_positives(findings, suppressions)
    # Only the src/a.ts instance should be suppressed
    assert len(result) == 1
    assert result[0].file_path == "src/b.ts"


def test_suppression_fingerprint_specificity():
    """Same finding_id in a different file should NOT be suppressed by a fingerprinted entry."""
    findings = [
        _make_finding("DB-004", file_path="src/other.ts", line=99),
    ]
    suppressions = [
        FalsePositive(
            finding_id="DB-004",
            reason="Fixed",
            file_path="src/user.entity.ts",
            line_range=(10, 10),
        ),
    ]
    result = filter_false_positives(findings, suppressions)
    # Should NOT be suppressed — different file
    assert len(result) == 1
    assert result[0].finding_id == "DB-004"


# ---------------------------------------------------------------------------
# build_cycle_suppression_set
# ---------------------------------------------------------------------------

def test_build_cycle_suppression_set_creates_auto_suppressions():
    prev = [
        _make_finding("DB-004", file_path="src/user.entity.ts", line=10),
        _make_finding("DB-005", file_path="src/order.entity.ts", line=20),
    ]
    fixed_ids = ["DB-004"]
    suppressions = build_cycle_suppression_set(prev, fixed_ids)
    assert len(suppressions) == 1
    assert suppressions[0].finding_id == "DB-004"
    assert suppressions[0].suppressed_by == "auto"
    assert suppressions[0].file_path == "src/user.entity.ts"


def test_build_cycle_suppression_set_ignores_unfixed():
    prev = [
        _make_finding("DB-004", file_path="src/user.entity.ts", line=10),
        _make_finding("DB-005", file_path="src/order.entity.ts", line=20),
    ]
    fixed_ids = ["DB-004"]
    suppressions = build_cycle_suppression_set(prev, fixed_ids)
    suppressed_ids = {s.finding_id for s in suppressions}
    assert "DB-005" not in suppressed_ids
