"""Tests for Feature #3.5: Department Leader Skills."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.skills import (
    Lesson,
    SkillData,
    _enforce_token_budget,
    _merge_lessons,
    _normalize_lesson_key,
    _parse_skill_file,
    _render_skill_file,
    _update_coding_skills,
    _update_review_skills,
    load_skills_for_department,
    update_skills_from_build,
)


# ---------------------------------------------------------------------------
# Sample data matching V2 test build
# ---------------------------------------------------------------------------

SAMPLE_AUDIT_REPORT = {
    "audit_meta": {"timestamp": "2026-04-03T00:00:00Z", "cycle": 1},
    "score": {
        "value": 0,
        "grade": "F",
        "deductions": [
            {"finding_id": "AUDIT-011", "severity": "critical", "points": 15, "title": "Zero tests exist"},
            {"finding_id": "AUDIT-012", "severity": "critical", "points": 15, "title": "No test framework installed"},
            {"finding_id": "AUDIT-001", "severity": "high", "points": 8, "title": "due_date not validated"},
            {"finding_id": "AUDIT-003", "severity": "medium", "points": 4, "title": "'as any' type assertions"},
        ],
    },
    "findings": [
        {"id": "AUDIT-011", "severity": "critical", "category": "testing",
         "title": "Zero tests exist", "remediation": "Install test framework in Wave 1"},
        {"id": "AUDIT-012", "severity": "critical", "category": "testing",
         "title": "No test framework installed", "remediation": "Install jest or vitest"},
        {"id": "AUDIT-001", "severity": "high", "category": "requirements",
         "title": "due_date not validated", "remediation": "Validate date fields with .refine()"},
        {"id": "AUDIT-003", "severity": "medium", "category": "technical",
         "title": "'as any' type assertions", "remediation": "Use Express.Request augmentation"},
        {"id": "AUDIT-007", "severity": "high", "category": "technical",
         "title": "require() instead of ES imports", "remediation": "Use ES import syntax"},
    ],
}

# New-format audit report (deduplicated_findings under audit_report key)
SAMPLE_AUDIT_REPORT_V2 = {
    "audit_report": {
        "cycle": 1,
        "timestamp": "2026-04-03T00:00:00Z",
        "deduplicated_findings": [
            {
                "finding_id": "F-001",
                "requirement_id": "GENERAL",
                "verdict": "FAIL",
                "severity": "CRITICAL",
                "summary": "No source code exists",
                "remediation": "Re-run the build to completion",
            },
            {
                "finding_id": "F-036",
                "requirement_id": "TEST-SUMMARY",
                "verdict": "FAIL",
                "severity": "CRITICAL",
                "summary": "0 tests exist — no test files",
                "remediation": "Add jest + ts-jest and create test files",
            },
        ],
    },
}

SAMPLE_GATE_LOG = """[2026-04-03T10:10:11.058097+00:00] GATE_PSEUDOCODE: FAIL \u2014 No pseudocode found
[2026-04-03T10:10:11.067090+00:00] GATE_CONVERGENCE: PASS \u2014 All items converged
[2026-04-03T10:10:11.067598+00:00] GATE_TRUTH_SCORE: FAIL \u2014 1 score(s) below threshold
[2026-04-03T10:22:59.824349+00:00] GATE_E2E: PASS \u2014 E2E tests passed
"""


class FakeState:
    """Minimal state-like object for testing."""

    _DEFAULT_SCORES = {
        "overall": 0.4537,
        "requirement_coverage": 0.267,
        "contract_compliance": 0.0,
        "error_handling": 0.68,
        "type_safety": 1.0,
        "test_presence": 0.4,
        "security_patterns": 0.75,
    }

    def __init__(self, truth_scores=None):
        self.truth_scores = self._DEFAULT_SCORES.copy() if truth_scores is None else truth_scores


# ---------------------------------------------------------------------------
# Test: update_skills_from_build
# ---------------------------------------------------------------------------

class TestUpdateSkillsFromBuild:
    def test_creates_skill_files_from_audit_data(self, tmp_path: Path):
        """SK1+SK2+SK3+SK4: Skill files created from AUDIT_REPORT.json and STATE data."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")

        state = FakeState()
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding_path = skills_dir / "coding_dept.md"
        review_path = skills_dir / "review_dept.md"

        assert coding_path.is_file(), "coding_dept.md not created"
        assert review_path.is_file(), "review_dept.md not created"

        coding_content = coding_path.read_text(encoding="utf-8")
        assert "Critical" in coding_content
        assert "Install test framework" in coding_content or "Install jest" in coding_content

        review_content = review_path.read_text(encoding="utf-8")
        # New format: review has rejection rules and/or checklist
        assert "Rejection Rules" in review_content or "Review Checklist" in review_content

    def test_first_build_no_existing_skills(self, tmp_path: Path):
        """SK9: First build without existing skills doesn't crash."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")

        state = FakeState()
        # Should not raise
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

    def test_no_data_skips_gracefully(self, tmp_path: Path):
        """SK10: No audit data means no skill files created."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "nonexistent.json"
        gate_path = tmp_path / "nonexistent.log"

        state = FakeState(truth_scores={})
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        # With no findings, no gate log, AND empty truth scores,
        # the early return fires — no files should be created
        assert not skills_dir.exists() or not (skills_dir / "coding_dept.md").exists()

    def test_seen_counters_increment_on_second_build(self, tmp_path: Path):
        """SK6: [seen: N/M] counters increment on second build."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        # First build
        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        # Second build (same data)
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding_content = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "Builds analyzed: 2" in coding_content
        # At least one lesson should have seen: 2
        assert "[seen: 2/" in coding_content

    def test_truth_scores_injected_as_dimensions(self, tmp_path: Path):
        """SK5: Weak truth score dimensions appear in tiered sections."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "contract_compliance" in coding
        assert "requirement_coverage" in coding
        # type_safety=1.0 should NOT appear in body sections (only in metadata)
        body = "\n".join(
            l for l in coding.split("\n") if not l.strip().startswith("<!--")
        )
        assert "type_safety" not in body

    def test_gate_results_in_review_skills(self, tmp_path: Path):
        """Gate results appear in review department gate analysis."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "GATE_PSEUDOCODE" in review
        assert "GATE_E2E" in review

    def test_new_format_audit_report(self, tmp_path: Path):
        """New audit_report format with deduplicated_findings is parsed correctly."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT_V2), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "Re-run the build" in coding or "Add jest" in coding


# ---------------------------------------------------------------------------
# Test: load_skills_for_department
# ---------------------------------------------------------------------------

class TestLoadSkillsForDepartment:
    def test_loads_existing_skill_file(self, tmp_path: Path):
        """Load returns content of existing skill file."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "coding_dept.md").write_text("# Coding Skills\nTest content", encoding="utf-8")

        result = load_skills_for_department(skills_dir, "coding")
        assert "Test content" in result

    def test_returns_empty_for_missing_file(self, tmp_path: Path):
        """SK10: Missing file returns empty string (backward compat)."""
        result = load_skills_for_department(tmp_path / "nonexistent", "coding")
        assert result == ""

    def test_enforces_token_budget(self, tmp_path: Path):
        """SK7: Token budget enforced on load."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Write a large file with proper sections so truncation can remove sections
        lines = [
            "# Skills",
            "## Critical (prevent these always)",
            "- Critical lesson one",
            "",
            "## High Priority",
        ]
        lines += [f"- High priority lesson {i} with lots of extra words for padding" for i in range(50)]
        lines += ["", "## Quality Targets"]
        lines += [f"- Quality target {i} with extra words for padding tokens" for i in range(50)]
        lines += ["", "## Gate History"]
        lines += [f"- Gate entry {i} with extra words for padding purposes" for i in range(50)]
        big_content = "\n".join(lines)
        (skills_dir / "coding_dept.md").write_text(big_content, encoding="utf-8")

        result = load_skills_for_department(skills_dir, "coding", max_tokens=50)
        # Result should be truncated (sections removed from bottom)
        assert len(result) < len(big_content)
        # Critical section should be preserved
        assert "Critical lesson" in result


# ---------------------------------------------------------------------------
# Test: Skill parsing and rendering
# ---------------------------------------------------------------------------

class TestSkillParsing:
    def test_parse_empty_file(self, tmp_path: Path):
        """Parse non-existent file returns empty SkillData."""
        data = _parse_skill_file(tmp_path / "nope.md", "coding")
        assert data.department == "coding"
        assert data.builds_analyzed == 0
        assert data.critical == []
        assert data.high == []

    def test_roundtrip_coding(self):
        """Parse -> render -> parse preserves structure."""
        data = SkillData(
            department="coding",
            builds_analyzed=3,
            dimensions={"contract_compliance": 0.00, "error_handling": 0.60},
            score_history={"contract_compliance": [0.00, 0.00, 0.00]},
            critical=[Lesson(text="Fix tests [seen: 3/3]", severity="critical", seen=3, total=3)],
        )
        rendered = _render_skill_file(data)
        assert "Builds analyzed: 3" in rendered
        assert "Fix tests" in rendered
        assert "Critical" in rendered
        assert "contract_compliance" in rendered

    def test_roundtrip_review(self):
        """Review department renders with correct sections."""
        data = SkillData(
            department="review",
            builds_analyzed=2,
            dimensions={"contract_compliance": 0.00, "test_presence": 0.20},
            score_history={
                "contract_compliance": [0.00, 0.00],
                "test_presence": [0.00, 0.20],
            },
            gate_fail_counts={"GATE_ARCHITECTURE": 2},
            gate_total_counts={"GATE_ARCHITECTURE": 2},
            gate_reasons={"GATE_ARCHITECTURE": "No arch section"},
        )
        rendered = _render_skill_file(data)
        assert "Rejection Rules" in rendered
        assert "Checklist" in rendered
        assert "Gate Analysis" in rendered

    def test_score_history_roundtrip(self, tmp_path: Path):
        """Score history survives write -> parse cycle."""
        data = SkillData(
            department="coding",
            builds_analyzed=3,
            dimensions={"test_presence": 0.30},
            score_history={"test_presence": [0.00, 0.10, 0.30]},
        )
        path = tmp_path / "coding_dept.md"
        path.write_text(_render_skill_file(data), encoding="utf-8")

        parsed = _parse_skill_file(path, "coding")
        assert parsed.builds_analyzed == 3
        assert "test_presence" in parsed.score_history
        assert len(parsed.score_history["test_presence"]) == 3
        assert parsed.score_history["test_presence"][-1] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Test: Merge and deduplication
# ---------------------------------------------------------------------------

class TestMergeLessons:
    def test_new_lessons_added(self):
        """New lessons appear in merged output."""
        existing = []
        new = [Lesson(text="Fix X [seen: 1/1]", severity="high")]
        result = _merge_lessons(existing, new, total_builds=1)
        assert len(result) == 1

    def test_duplicate_increments_counter(self):
        """Duplicate lessons have their seen count incremented."""
        existing = [Lesson(text="Fix X [seen: 1/1]", severity="high", seen=1, total=1)]
        new = [Lesson(text="Fix X [seen: 1/2]", severity="high", seen=1, total=2)]
        result = _merge_lessons(existing, new, total_builds=2)
        assert len(result) == 1
        assert result[0].seen == 2
        assert "[seen: 2/2]" in result[0].text

    def test_different_lessons_both_kept(self):
        """Non-duplicate lessons are both kept."""
        existing = [Lesson(text="Fix A [seen: 1/1]", severity="high")]
        new = [Lesson(text="Fix B [seen: 1/2]", severity="high")]
        result = _merge_lessons(existing, new, total_builds=2)
        assert len(result) == 2

    def test_sorted_by_frequency(self):
        """Most-seen lessons come first."""
        existing = [
            Lesson(text="Rare [seen: 1/5]", severity="high", seen=1, total=5),
            Lesson(text="Common [seen: 4/5]", severity="high", seen=4, total=5),
        ]
        result = _merge_lessons(existing, [], total_builds=5)
        assert "Common" in result[0].text


class TestNormalizeLessonKey:
    def test_strips_seen_counter(self):
        result = _normalize_lesson_key("Fix X [seen: 3/5]")
        assert result == "fix x", f"Got: {result!r}"

    def test_lowercases(self):
        assert _normalize_lesson_key("FIX Types") == "fix types"


# ---------------------------------------------------------------------------
# Test: Token budget enforcement
# ---------------------------------------------------------------------------

class TestTokenBudget:
    def test_small_content_unchanged(self):
        """Content within budget is returned unchanged."""
        content = "# Skills\n- One lesson"
        result = _enforce_token_budget(content, max_tokens=500)
        assert result == content

    def test_large_content_truncated(self):
        """Content exceeding budget is truncated."""
        sections = [
            "# Skills",
            "## Critical (prevent these always)",
            "- Critical lesson 1",
            "",
            "## High Priority",
            "- High lesson with many words repeated " * 10,
            "",
            "## Quality Targets",
            "- Target with many words repeated " * 10,
            "",
            "## Gate History",
            "- Gate entry with many words repeated " * 10,
        ]
        content = "\n".join(sections)
        result = _enforce_token_budget(content, max_tokens=30)
        # Critical should be preserved
        assert "Critical lesson" in result
        # Some sections should be removed
        assert len(result) < len(content)


# ---------------------------------------------------------------------------
# Test: Department prompt injection (integration)
# ---------------------------------------------------------------------------

class TestDepartmentIntegration:
    def test_skills_injected_into_department_prompt(self, tmp_path: Path):
        """SK5+SK11: Skills content appears in department prompt output."""
        from agent_team_v15.department import build_orchestrator_department_prompt

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "coding_dept.md").write_text(
            "# Coding Skills\n## Critical\n- Always install tests\n",
            encoding="utf-8",
        )
        (skills_dir / "review_dept.md").write_text(
            "# Review Skills\n## Gate Analysis\n- GATE_E2E: PASS\n",
            encoding="utf-8",
        )

        prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
            skills_dir=skills_dir,
        )

        assert "CODING DEPARTMENT SKILLS" in prompt
        assert "Always install tests" in prompt
        assert "REVIEW DEPARTMENT SKILLS" in prompt
        assert "GATE_E2E" in prompt

    def test_no_skills_dir_no_crash(self):
        """SK10: No skills_dir parameter works (backward compat)."""
        from agent_team_v15.department import build_orchestrator_department_prompt

        prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
        )
        # Should not contain skills section
        assert "DEPARTMENT SKILLS" not in prompt
        # Should still have department structure
        assert "CODING DEPARTMENT" in prompt

    def test_empty_skills_dir_no_injection(self, tmp_path: Path):
        """Empty skills dir means no injection."""
        from agent_team_v15.department import build_orchestrator_department_prompt

        skills_dir = tmp_path / "empty_skills"
        skills_dir.mkdir()

        prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
            skills_dir=skills_dir,
        )
        assert "DEPARTMENT SKILLS" not in prompt


# ---------------------------------------------------------------------------
# Test: Pipeline integration (cli.py wiring)
# ---------------------------------------------------------------------------

class TestPipelineWiring:
    def test_update_skills_callable_from_cli_context(self):
        """Verify update_skills_from_build is importable and callable."""
        from agent_team_v15.skills import update_skills_from_build
        assert callable(update_skills_from_build)

    def test_load_skills_callable_from_department(self):
        """Verify load_skills_for_department is importable."""
        from agent_team_v15.skills import load_skills_for_department
        assert callable(load_skills_for_department)

    def test_skills_module_in_init(self):
        """Verify skills is registered in __init__.py __all__."""
        import agent_team_v15
        assert "skills" in agent_team_v15.__all__

    def test_update_skills_wired_in_cli(self):
        """Verify the skill update import path exists in cli.py."""
        import importlib
        cli = importlib.import_module("agent_team_v15.cli")
        source_path = Path(cli.__file__)
        source = source_path.read_text(encoding="utf-8")
        assert "from .skills import update_skills_from_build" in source

    def test_skills_dir_passed_to_department_prompt_in_cli(self):
        """Verify cli.py passes skills_dir to build_orchestrator_department_prompt."""
        import importlib
        cli = importlib.import_module("agent_team_v15.cli")
        source_path = Path(cli.__file__)
        source = source_path.read_text(encoding="utf-8")
        assert "skills_dir=" in source

    def test_coordinated_builder_calls_update_skills(self):
        """Verify coordinated_builder.py calls update_skills_from_build."""
        import importlib
        cb = importlib.import_module("agent_team_v15.coordinated_builder")
        source_path = Path(cb.__file__)
        source = source_path.read_text(encoding="utf-8")
        assert "update_skills_from_build" in source


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_malformed_audit_json(self, tmp_path: Path):
        """Handles malformed AUDIT_REPORT.json gracefully."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text("{invalid json", encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")
        state = FakeState(truth_scores={})

        # Should not raise
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

    def test_empty_findings_list(self, tmp_path: Path):
        """Empty findings produces minimal skill files."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")
        state = FakeState()

        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        # Should still create files (truth scores provide data)
        assert (skills_dir / "coding_dept.md").is_file()

    def test_state_without_truth_scores(self, tmp_path: Path):
        """State object without truth_scores attribute is handled."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps(SAMPLE_AUDIT_REPORT), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")

        state = type("BareState", (), {})()  # No truth_scores attribute
        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        assert (skills_dir / "coding_dept.md").is_file()


# ---------------------------------------------------------------------------
# Test: Tiered output format (new)
# ---------------------------------------------------------------------------

class TestTieredOutput:
    """Verify dimensions are correctly tiered by score."""

    def test_critical_dimension_at_zero(self, tmp_path: Path):
        """Score 0.00 dimension appears in Critical section with step-by-step."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.30,
            "contract_compliance": 0.00,
            "test_presence": 0.80,
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        # contract_compliance at 0.00 → Critical section
        assert "Critical" in coding
        assert "contract_compliance" in coding
        # Should have step-by-step guidance
        assert "1." in coding
        assert "zod" in coding.lower() or "contract" in coding.lower()

    def test_high_priority_dimension(self, tmp_path: Path):
        """Score 0.25 dimension appears in High Priority section."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.50,
            "security_patterns": 0.25,
            "type_safety": 1.0,
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "High Priority" in coding
        assert "security_patterns" in coding

    def test_moderate_dimension(self, tmp_path: Path):
        """Score 0.60 dimension appears in Moderate section."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.70,
            "error_handling": 0.60,
            "type_safety": 1.0,
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "Moderate" in coding
        assert "error_handling" in coding

    def test_on_track_not_in_body(self, tmp_path: Path):
        """Score >= 0.75 dimension does NOT appear in body sections."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.90,
            "type_safety": 1.0,
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        body = "\n".join(l for l in coding.split("\n") if not l.strip().startswith("<!--"))
        assert "type_safety" not in body

    def test_all_tiers_present_with_varied_scores(self, tmp_path: Path):
        """Mixed scores produce all three action tiers."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.50,
            "contract_compliance": 0.00,  # CRITICAL
            "test_presence": 0.30,         # HIGH
            "error_handling": 0.60,        # MODERATE
            "type_safety": 1.0,            # ON TRACK (not rendered)
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "Critical" in coding
        assert "High Priority" in coding
        assert "Moderate" in coding


# ---------------------------------------------------------------------------
# Test: Review department format (new)
# ---------------------------------------------------------------------------

class TestReviewFormat:
    """Verify review department produces rejection rules, checklist, gate table."""

    def test_hard_rejection_rule_for_zero_score(self, tmp_path: Path):
        """Score 0.00 across builds generates hard rejection rule."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.30,
            "contract_compliance": 0.00,
            "test_presence": 0.80,
        })

        # Build twice to establish history
        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "Hard Rejection Rules" in review
        assert "REJECT" in review
        assert "contract" in review.lower()

    def test_priority_checklist_for_weak_dims(self, tmp_path: Path):
        """Weak dimensions appear in priority review checklist."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={
            "overall": 0.40,
            "contract_compliance": 0.00,
            "test_presence": 0.20,
            "type_safety": 1.0,
        })
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "Priority Review Checklist" in review
        assert "- [ ]" in review

    def test_gate_analysis_table(self, tmp_path: Path):
        """Gate analysis table shows pass/fail with actions."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")

        state = FakeState()
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "Gate Analysis" in review
        assert "| Gate |" in review
        assert "FAIL" in review
        assert "PASS" in review


# ---------------------------------------------------------------------------
# Test: Score history and trend detection (new)
# ---------------------------------------------------------------------------

class TestScoreHistory:
    """Verify score history tracking and trend detection."""

    def test_score_history_accumulates(self, tmp_path: Path):
        """Score history grows with each build."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        # Build 1: low score
        state = FakeState(truth_scores={"overall": 0.30, "test_presence": 0.10})
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        # Build 2: improved score
        state = FakeState(truth_scores={"overall": 0.50, "test_presence": 0.30})
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "Builds analyzed: 2" in coding
        # Score history metadata should have two entries
        assert "Scores:" in coding
        assert "0.10" in coding
        assert "0.30" in coding

    def test_trend_shown_on_second_build(self, tmp_path: Path):
        """Trend appears in review department after 2+ builds."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        # Build 1
        state = FakeState(truth_scores={"overall": 0.30, "test_presence": 0.10})
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        # Build 2 (improved)
        state = FakeState(truth_scores={"overall": 0.50, "test_presence": 0.40})
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "Trend" in review
        assert "improved" in review

    def test_never_passed_urgency(self, tmp_path: Path):
        """Dimension at 0.00 across 2 builds shows NEVER passed message."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text("", encoding="utf-8")

        state = FakeState(truth_scores={"overall": 0.30, "contract_compliance": 0.00})

        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        coding = (skills_dir / "coding_dept.md").read_text(encoding="utf-8")
        assert "NEVER passed" in coding
        assert "2 builds" in coding


# ---------------------------------------------------------------------------
# Test: Gate tracking across builds (new)
# ---------------------------------------------------------------------------

class TestGateTracking:
    """Verify gate fail counts accumulate across builds."""

    def test_gate_counts_accumulate(self, tmp_path: Path):
        """Gate fail counts increment across builds."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        # Build 1
        update_skills_from_build(skills_dir, state, audit_path, gate_path)
        # Build 2
        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        # GATE_PSEUDOCODE fails in both builds → should show FAIL (2/2)
        assert "GATE_PSEUDOCODE" in review
        # GateCounts metadata should exist
        assert "GateCounts:" in review

    def test_gate_counts_in_metadata(self, tmp_path: Path):
        """Gate counts persist in metadata comments."""
        skills_dir = tmp_path / "skills"
        audit_path = tmp_path / "AUDIT_REPORT.json"
        gate_path = tmp_path / "GATE_AUDIT.log"

        audit_path.write_text(json.dumps({"findings": [], "score": {"deductions": []}}), encoding="utf-8")
        gate_path.write_text(SAMPLE_GATE_LOG, encoding="utf-8")
        state = FakeState()

        update_skills_from_build(skills_dir, state, audit_path, gate_path)

        review = (skills_dir / "review_dept.md").read_text(encoding="utf-8")
        assert "GateCounts:" in review
        assert "GATE_PSEUDOCODE=" in review
