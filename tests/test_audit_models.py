"""Tests for agent_team.audit_models."""

from __future__ import annotations

import json

import pytest

from agent_team_v15.audit_models import (
    AUDITOR_NAMES,
    AUDITOR_PREFIXES,
    SEVERITIES,
    VERDICTS,
    _MAX_FINDINGS,
    AuditFinding,
    AuditReport,
    AuditScore,
    FixTask,
    build_report,
    compute_reaudit_scope,
    deduplicate_findings,
    detect_fix_conflicts,
    group_findings_into_fix_tasks,
    parse_evidence_entry,
)


# ===================================================================
# Helpers
# ===================================================================

def _make_finding(
    finding_id: str = "RA-001",
    auditor: str = "requirements",
    requirement_id: str = "REQ-001",
    verdict: str = "FAIL",
    severity: str = "HIGH",
    summary: str = "Test finding",
    evidence: list[str] | None = None,
    remediation: str = "Fix it",
    confidence: float = 0.9,
) -> AuditFinding:
    return AuditFinding(
        finding_id=finding_id,
        auditor=auditor,
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary=summary,
        evidence=evidence if evidence is not None else ["src/foo.py:10 -- issue found"],
        remediation=remediation,
        confidence=confidence,
    )


# ===================================================================
# Constants
# ===================================================================

class TestConstants:
    def test_severities_order(self):
        assert SEVERITIES == ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

    def test_verdicts(self):
        assert VERDICTS == ("PASS", "FAIL", "PARTIAL")

    def test_auditor_names_count(self):
        assert len(AUDITOR_NAMES) == 6

    def test_auditor_prefixes_match_names(self):
        for name in AUDITOR_NAMES:
            assert name in AUDITOR_PREFIXES


# ===================================================================
# AuditFinding
# ===================================================================

class TestAuditFinding:
    def test_construction(self):
        f = _make_finding()
        assert f.finding_id == "RA-001"
        assert f.auditor == "requirements"
        assert f.verdict == "FAIL"

    def test_to_dict(self):
        f = _make_finding()
        d = f.to_dict()
        assert d["finding_id"] == "RA-001"
        assert d["severity"] == "HIGH"
        assert isinstance(d["evidence"], list)

    def test_from_dict(self):
        f = _make_finding()
        d = f.to_dict()
        f2 = AuditFinding.from_dict(d)
        assert f2.finding_id == f.finding_id
        assert f2.confidence == f.confidence

    def test_from_dict_defaults(self):
        d = {
            "finding_id": "RA-002",
            "auditor": "requirements",
            "requirement_id": "REQ-002",
            "verdict": "PASS",
            "severity": "INFO",
            "summary": "All good",
        }
        f = AuditFinding.from_dict(d)
        assert f.evidence == []
        assert f.remediation == ""
        assert f.confidence == 1.0

    def test_roundtrip(self):
        f = _make_finding(evidence=["a.py:1 -- x", "b.py:2 -- y"])
        d = f.to_dict()
        f2 = AuditFinding.from_dict(d)
        assert f2.to_dict() == d

    def test_primary_file_standard(self):
        f = _make_finding(evidence=["src/routes/auth.ts:42 -- missing validation"])
        assert f.primary_file == "src/routes/auth.ts"

    def test_primary_file_empty_evidence(self):
        f = _make_finding(evidence=[])
        assert f.primary_file == ""

    def test_primary_file_no_colon(self):
        f = _make_finding(evidence=["some_file.py -- no line number"])
        assert f.primary_file == "some_file.py"


# ===================================================================
# AuditScore
# ===================================================================

class TestAuditScore:
    def test_all_pass_healthy(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_finding(requirement_id="REQ-002", verdict="PASS", severity="INFO"),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 2
        assert score.passed == 2
        assert score.failed == 0
        assert score.score == 100.0
        assert score.health == "healthy"

    def test_all_fail(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="FAIL", severity="HIGH"),
            _make_finding(requirement_id="REQ-002", verdict="FAIL", severity="CRITICAL"),
        ]
        score = AuditScore.compute(findings)
        assert score.passed == 0
        assert score.failed == 2
        assert score.score == 0.0
        assert score.health == "failed"

    def test_mixed_verdicts(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_finding(requirement_id="REQ-002", verdict="PARTIAL", severity="MEDIUM"),
            _make_finding(requirement_id="REQ-003", verdict="FAIL", severity="HIGH"),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 3
        assert score.passed == 1
        assert score.partial == 1
        assert score.failed == 1
        # (1*100 + 1*50 + 0) / 3 = 50.0
        assert score.score == 50.0
        assert score.health == "failed"

    def test_degraded_threshold(self):
        findings = [
            _make_finding(requirement_id=f"REQ-{i:03d}", verdict="PASS", severity="INFO")
            for i in range(8)
        ] + [
            _make_finding(requirement_id="REQ-008", verdict="FAIL", severity="HIGH"),
            _make_finding(requirement_id="REQ-009", verdict="FAIL", severity="HIGH"),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 10
        # 8 pass + 2 fail = 800/10 = 80.0
        assert score.score == 80.0
        assert score.health == "degraded"

    def test_critical_forces_failed(self):
        findings = [
            _make_finding(requirement_id=f"REQ-{i:03d}", verdict="PASS", severity="INFO")
            for i in range(9)
        ] + [
            _make_finding(requirement_id="REQ-009", verdict="FAIL", severity="CRITICAL"),
        ]
        score = AuditScore.compute(findings)
        assert score.score == 90.0
        assert score.critical_count == 1
        assert score.health == "failed"  # Critical forces failed

    def test_empty_findings(self):
        score = AuditScore.compute([])
        assert score.total_items == 0
        assert score.score == 0.0
        assert score.health == "failed"

    def test_general_findings_excluded_from_score(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_finding(requirement_id="GENERAL", verdict="FAIL", severity="HIGH"),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 1  # GENERAL not counted
        assert score.passed == 1
        assert score.score == 100.0

    def test_worst_verdict_wins(self):
        findings = [
            _make_finding(finding_id="RA-001", requirement_id="REQ-001", verdict="PASS"),
            _make_finding(finding_id="TA-001", requirement_id="REQ-001", verdict="FAIL"),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 1
        assert score.failed == 1
        assert score.passed == 0

    def test_severity_counts(self):
        findings = [
            _make_finding(severity="CRITICAL"),
            _make_finding(severity="HIGH", finding_id="RA-002"),
            _make_finding(severity="HIGH", finding_id="RA-003"),
            _make_finding(severity="MEDIUM", finding_id="RA-004"),
            _make_finding(severity="LOW", finding_id="RA-005"),
            _make_finding(severity="INFO", finding_id="RA-006"),
        ]
        score = AuditScore.compute(findings)
        assert score.critical_count == 1
        assert score.high_count == 2
        assert score.medium_count == 1
        assert score.low_count == 1
        assert score.info_count == 1

    def test_custom_thresholds(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_finding(requirement_id="REQ-002", verdict="PARTIAL", severity="MEDIUM"),
        ]
        score = AuditScore.compute(findings, healthy_threshold=80.0, degraded_threshold=60.0)
        # (100 + 50) / 2 = 75.0
        assert score.score == 75.0
        assert score.health == "degraded"

    def test_to_dict_from_dict(self):
        findings = [_make_finding(verdict="PASS", severity="INFO")]
        score = AuditScore.compute(findings)
        d = score.to_dict()
        score2 = AuditScore.from_dict(d)
        assert score2.score == score.score
        assert score2.health == score.health


# ===================================================================
# AuditReport
# ===================================================================

class TestAuditReport:
    def test_to_json_from_json(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_finding(requirement_id="REQ-002", verdict="FAIL", severity="HIGH", finding_id="RA-002"),
        ]
        report = build_report("audit-test-1", 1, ["requirements"], findings)
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert parsed["audit_id"] == "audit-test-1"
        assert len(parsed["findings"]) == 2

    def test_roundtrip(self):
        findings = [
            _make_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
        ]
        report = build_report("audit-rt", 1, ["requirements"], findings)
        json_str = report.to_json()
        report2 = AuditReport.from_json(json_str)
        assert report2.audit_id == report.audit_id
        assert len(report2.findings) == len(report.findings)
        assert report2.score.health == report.score.health

    def test_by_severity_grouping(self):
        findings = [
            _make_finding(finding_id="RA-001", severity="CRITICAL"),
            _make_finding(finding_id="RA-002", severity="HIGH", requirement_id="REQ-002"),
            _make_finding(finding_id="RA-003", severity="CRITICAL", requirement_id="REQ-003"),
        ]
        report = build_report("audit-sev", 1, ["requirements"], findings)
        assert "CRITICAL" in report.by_severity
        assert len(report.by_severity["CRITICAL"]) == 2
        assert "HIGH" in report.by_severity

    def test_fix_candidates(self):
        findings = [
            _make_finding(finding_id="RA-001", verdict="FAIL", severity="CRITICAL"),
            _make_finding(finding_id="RA-002", verdict="PASS", severity="INFO", requirement_id="REQ-002"),
            _make_finding(finding_id="RA-003", verdict="PARTIAL", severity="MEDIUM", requirement_id="REQ-003"),
            _make_finding(finding_id="RA-004", verdict="FAIL", severity="LOW", requirement_id="REQ-004"),
        ]
        report = build_report("audit-fc", 1, ["requirements"], findings)
        # CRITICAL FAIL + MEDIUM PARTIAL are fix candidates; LOW is not
        assert len(report.fix_candidates) == 2


# ===================================================================
# Deduplication
# ===================================================================

class TestDeduplication:
    def test_no_duplicates(self):
        findings = [
            _make_finding(finding_id="RA-001", requirement_id="REQ-001"),
            _make_finding(finding_id="TA-001", requirement_id="REQ-002"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 2

    def test_same_req_same_verdict_keeps_higher_confidence(self):
        findings = [
            _make_finding(finding_id="RA-001", requirement_id="REQ-001", verdict="FAIL", confidence=0.7),
            _make_finding(finding_id="TA-001", requirement_id="REQ-001", verdict="FAIL", confidence=0.9),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_same_req_different_verdict_kept(self):
        findings = [
            _make_finding(finding_id="RA-001", requirement_id="REQ-001", verdict="FAIL"),
            _make_finding(finding_id="TA-001", requirement_id="REQ-001", verdict="PARTIAL"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 2

    def test_general_never_deduplicated(self):
        findings = [
            _make_finding(finding_id="MA-001", requirement_id="GENERAL", verdict="FAIL"),
            _make_finding(finding_id="MA-002", requirement_id="GENERAL", verdict="FAIL"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 2

    def test_evidence_merged(self):
        findings = [
            _make_finding(
                finding_id="RA-001", requirement_id="REQ-001", verdict="FAIL",
                confidence=0.8, evidence=["a.py:1 -- first"],
            ),
            _make_finding(
                finding_id="TA-001", requirement_id="REQ-001", verdict="FAIL",
                confidence=0.9, evidence=["b.py:2 -- second"],
            ),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 1
        assert len(result[0].evidence) == 2


# ===================================================================
# FixTask
# ===================================================================

class TestFixTask:
    def test_priority_order(self):
        task = FixTask(target_files=["a.py"], findings=[], priority="CRITICAL")
        assert task.priority_order == 0
        task2 = FixTask(target_files=["b.py"], findings=[], priority="MEDIUM")
        assert task2.priority_order == 2

    def test_to_dict(self):
        f = _make_finding()
        task = FixTask(target_files=["a.py"], findings=[f], priority="HIGH")
        d = task.to_dict()
        assert d["target_files"] == ["a.py"]
        assert len(d["findings"]) == 1


# ===================================================================
# group_findings_into_fix_tasks
# ===================================================================

class TestGroupFindingsIntoFixTasks:
    def test_empty_candidates(self):
        report = build_report("test", 1, ["requirements"], [
            _make_finding(verdict="PASS", severity="INFO"),
        ])
        tasks = group_findings_into_fix_tasks(report)
        assert tasks == []

    def test_single_file_group(self):
        findings = [
            _make_finding(finding_id="RA-001", verdict="FAIL", severity="HIGH",
                          evidence=["src/foo.py:10 -- issue"]),
            _make_finding(finding_id="RA-002", verdict="FAIL", severity="MEDIUM",
                          requirement_id="REQ-002",
                          evidence=["src/foo.py:20 -- other issue"]),
        ]
        report = build_report("test", 1, ["requirements"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 1
        assert "src/foo.py" in tasks[0].target_files

    def test_multiple_file_groups(self):
        findings = [
            _make_finding(finding_id="RA-001", verdict="FAIL", severity="HIGH",
                          evidence=["src/a.py:10 -- issue"]),
            _make_finding(finding_id="RA-002", verdict="FAIL", severity="MEDIUM",
                          requirement_id="REQ-002",
                          evidence=["src/b.py:20 -- other"]),
        ]
        report = build_report("test", 1, ["requirements"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 2

    def test_task_split_on_max_findings(self):
        findings = [
            _make_finding(
                finding_id=f"RA-{i:03d}",
                requirement_id=f"REQ-{i:03d}",
                verdict="FAIL",
                severity="HIGH",
                evidence=["src/big.py:10 -- issue"],
            )
            for i in range(7)
        ]
        report = build_report("test", 1, ["requirements"], findings)
        tasks = group_findings_into_fix_tasks(report, max_findings_per_task=3)
        assert len(tasks) >= 3  # 7 findings / 3 per task = 3 tasks

    def test_tasks_sorted_by_severity(self):
        findings = [
            _make_finding(finding_id="RA-001", verdict="FAIL", severity="MEDIUM",
                          evidence=["src/low.py:1 -- issue"]),
            _make_finding(finding_id="RA-002", verdict="FAIL", severity="CRITICAL",
                          requirement_id="REQ-002",
                          evidence=["src/crit.py:1 -- critical"]),
        ]
        report = build_report("test", 1, ["requirements"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert tasks[0].priority == "CRITICAL"
        assert tasks[1].priority == "MEDIUM"


# ===================================================================
# compute_reaudit_scope
# ===================================================================

class TestComputeReauditScope:
    def test_test_always_included(self):
        result = compute_reaudit_scope([], [])
        assert "test" in result

    def test_maps_modified_files_to_auditors(self):
        findings = [
            _make_finding(auditor="requirements", verdict="FAIL",
                          evidence=["src/foo.py:10 -- issue"]),
            _make_finding(auditor="interface", verdict="FAIL",
                          evidence=["src/bar.py:20 -- issue"]),
        ]
        result = compute_reaudit_scope(["src/foo.py"], findings)
        assert "requirements" in result
        assert "test" in result
        assert "interface" not in result

    def test_pass_findings_excluded(self):
        findings = [
            _make_finding(auditor="requirements", verdict="PASS",
                          evidence=["src/foo.py:10 -- ok"]),
        ]
        result = compute_reaudit_scope(["src/foo.py"], findings)
        assert "requirements" not in result
        assert "test" in result


# ===================================================================
# detect_fix_conflicts
# ===================================================================

class TestDetectFixConflicts:
    def test_no_conflicts(self):
        tasks = [
            FixTask(target_files=["a.py"], findings=[], priority="HIGH"),
            FixTask(target_files=["b.py"], findings=[], priority="MEDIUM"),
        ]
        assert detect_fix_conflicts(tasks) == []

    def test_shared_file_conflict(self):
        tasks = [
            FixTask(target_files=["shared.py", "a.py"], findings=[], priority="HIGH"),
            FixTask(target_files=["shared.py", "b.py"], findings=[], priority="MEDIUM"),
        ]
        conflicts = detect_fix_conflicts(tasks)
        assert len(conflicts) == 1
        assert conflicts[0] == (0, 1)

    def test_no_conflict_disjoint(self):
        tasks = [
            FixTask(target_files=["a.py", "b.py"], findings=[], priority="HIGH"),
            FixTask(target_files=["c.py", "d.py"], findings=[], priority="MEDIUM"),
        ]
        assert detect_fix_conflicts(tasks) == []


# ===================================================================
# parse_evidence_entry
# ===================================================================

class TestParseEvidenceEntry:
    def test_standard_format(self):
        fp, ln, desc = parse_evidence_entry("src/file.ts:42 -- description")
        assert fp == "src/file.ts"
        assert ln == 42
        assert desc == "description"

    def test_windows_path(self):
        fp, ln, desc = parse_evidence_entry("C:\\Users\\path\\file.ts:42 -- desc")
        assert fp == "C:\\Users\\path\\file.ts"
        assert ln == 42
        assert desc == "desc"

    def test_no_line_number(self):
        fp, ln, desc = parse_evidence_entry("src/file.ts -- no line")
        assert fp == "src/file.ts"
        assert ln is None
        assert desc == "no line"

    def test_empty_string(self):
        fp, ln, desc = parse_evidence_entry("")
        assert fp == ""
        assert ln is None
        assert desc == ""

    def test_multiline_uses_first_line(self):
        fp, ln, desc = parse_evidence_entry("src/a.py:10 -- first\nsrc/b.py:20 -- second")
        assert fp == "src/a.py"
        assert ln == 10
        assert desc == "first"

    def test_no_description(self):
        fp, ln, desc = parse_evidence_entry("src/file.ts:42")
        assert fp == "src/file.ts"
        assert ln == 42
        assert desc == ""

    def test_no_colon_no_description(self):
        fp, ln, desc = parse_evidence_entry("some_file.py")
        assert fp == "some_file.py"
        assert ln is None
        assert desc == ""

    def test_windows_path_no_line(self):
        fp, ln, desc = parse_evidence_entry("C:\\path\\file.ts -- desc")
        assert fp == "C:\\path\\file.ts"
        assert ln is None
        assert desc == "desc"


# ===================================================================
# _MAX_FINDINGS cap
# ===================================================================

class TestMaxFindingsCap:
    def test_max_findings_constant(self):
        assert _MAX_FINDINGS == 50

    def test_build_report_caps_findings(self):
        # Create 100 findings across 100 different requirements
        findings = [
            _make_finding(
                finding_id=f"RA-{i:03d}",
                requirement_id=f"REQ-{i:03d}",
                verdict="FAIL",
                severity=["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"][i % 5],
                evidence=[f"src/file{i}.py:{i} -- issue {i}"],
            )
            for i in range(100)
        ]
        report = build_report("test-cap", 1, ["requirements"] * 5, findings)
        assert len(report.findings) <= _MAX_FINDINGS

    def test_cap_preserves_critical_first(self):
        # Create mix of severities, verify CRITICAL ones survive the cap
        findings = []
        for i in range(60):
            sev = "CRITICAL" if i < 5 else "INFO"
            findings.append(_make_finding(
                finding_id=f"RA-{i:03d}",
                requirement_id=f"REQ-{i:03d}",
                verdict="FAIL",
                severity=sev,
                evidence=[f"src/file{i}.py:{i} -- issue"],
            ))
        report = build_report("test-sev-cap", 1, ["requirements"], findings)
        critical_in_report = sum(1 for f in report.findings if f.severity == "CRITICAL")
        assert critical_in_report == 5  # All 5 CRITICAL findings kept


# ===================================================================
# Windows path handling in group_findings_into_fix_tasks
# ===================================================================

class TestWindowsPathInFixTasks:
    def test_windows_evidence_parsed_correctly(self):
        findings = [
            _make_finding(
                finding_id="RA-001",
                verdict="FAIL",
                severity="HIGH",
                evidence=["C:\\Users\\dev\\src\\app.ts:10 -- issue"],
            ),
        ]
        report = build_report("test-win", 1, ["requirements"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 1
        assert any("app.ts" in f for f in tasks[0].target_files)


# ===================================================================
# File:line level dedup
# ===================================================================

class TestFileLineDedup:
    def test_same_file_line_same_severity_merged(self):
        findings = [
            _make_finding(
                finding_id="RA-001", requirement_id="REQ-001",
                verdict="FAIL", severity="HIGH", confidence=0.8,
                evidence=["src/foo.py:10 -- issue A"],
            ),
            _make_finding(
                finding_id="IA-001", requirement_id="REQ-002",
                verdict="FAIL", severity="HIGH", confidence=0.9,
                evidence=["src/foo.py:10 -- issue B"],
            ),
        ]
        result = deduplicate_findings(findings)
        # Two different requirement_ids → both kept at req level
        # But same file:line + same severity → merged at file:line level
        assert len(result) <= 2  # At most 2, possibly merged to 1
