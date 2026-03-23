"""Tests for the browser test agent — workflow extraction, result handling, reports."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.browser_test_agent import (
    BrowserTestEngine,
    BrowserTestReport,
    StepAction,
    StepResult,
    Workflow,
    WorkflowResult,
    WorkflowStep,
    WorkflowSuite,
    _extract_feature_workflows,
    _extract_journey_section,
    _extract_project_name,
    _extract_steps_heuristic,
    _file_path_to_route,
    _infer_action,
    _is_backend_step,
    _parse_json_from_response,
    _slugify,
    _step_failure_to_finding,
    generate_browser_test_report,
)
from agent_team_v15.audit_agent import FindingCategory, Severity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_PRD = """\
# EVS Customer Portal — PRD

## 8.1 User Journeys

**Journey 0: "Sign up and book my first service" (most critical for adoption)**
Visit portal → Click "Sign Up" → Enter name, email, phone → Open email → Tap magic link → Dashboard (empty state) → Tap "Book a Service" → Register vehicle → Select service type → Confirm.
Expected: Signup in under 2 minutes.

**Journey 1: "Check my car status" (most frequent)**
Open portal → Dashboard → Tap active repair → View status with progress indicator → (Optional) message advisor → Close app.
Expected: 2 taps from app open to status view.

**Journey 2: "Approve a quotation"**
Open portal → Dashboard → Tap "Action Required" badge → View quotation details → Tap "Approve" → See confirmation.
Expected: Completable within 30 seconds.

## 5.1 F-001: Authentication & Account Management

- **Workflow:**
  1. Customer opens the app and taps "Sign Up."
  2. Customer enters: full name, email address, and phone number.
  3. Backend validates email format and phone number.
  4. Backend sends a magic link email via SendGrid.
  5. Customer opens their email and taps the magic link.
  6. Portal creates a Customer record and redirects to dashboard.
  7. A welcome email is sent.

## 5.3 F-003: Quotation Approval

- **Workflow:**
  1. Customer sees "Action Required" badge on dashboard, taps to view.
  2. Quotation detail screen loads from Odoo.
  3. Screen displays vehicle name, line items, and total in AED.
  4. Customer taps "Approve" or "Decline."
  5. Backend calls Odoo action_confirm().
  6. Customer sees confirmation message.

## 5.5 F-005: Invoice Access

- **Workflow:**
  1. Customer navigates to "Invoices" from the main navigation.
  2. Invoice list loads with all invoices sorted by date.
  3. Customer taps an invoice to see details.
  4. Customer taps "Download PDF."
"""


# ---------------------------------------------------------------------------
# Journey extraction
# ---------------------------------------------------------------------------


class TestJourneyExtraction:
    def test_extracts_all_journeys(self):
        journeys = _extract_journey_section(SAMPLE_PRD)
        assert len(journeys) >= 2

    def test_journey_has_required_fields(self):
        journeys = _extract_journey_section(SAMPLE_PRD)
        j0 = journeys[0]
        assert j0["type"] == "journey"
        assert "journey-0" in j0["id"]
        assert "Sign up" in j0["name"] or "sign up" in j0["name"].lower()
        assert "→" in j0["flow_text"] or "→" in j0["flow_text"]
        assert j0["priority"] in ("critical", "high")
        assert "Journey 0" in j0["prd_reference"]

    def test_journey_priority_assignment(self):
        journeys = _extract_journey_section(SAMPLE_PRD)
        # Journey 0 and 1 should be critical (<=2)
        priorities = {j["id"].split("-")[1]: j["priority"] for j in journeys}
        assert priorities.get("0") == "critical"
        assert priorities.get("1") == "critical"


# ---------------------------------------------------------------------------
# Feature workflow extraction
# ---------------------------------------------------------------------------


class TestFeatureWorkflowExtraction:
    def test_extracts_feature_workflows(self):
        workflows = _extract_feature_workflows(SAMPLE_PRD)
        assert len(workflows) >= 3

    def test_feature_has_steps(self):
        workflows = _extract_feature_workflows(SAMPLE_PRD)
        f001 = next((w for w in workflows if "f-001" in w["id"]), None)
        assert f001 is not None
        assert len(f001["steps_raw"]) >= 5

    def test_feature_priority(self):
        workflows = _extract_feature_workflows(SAMPLE_PRD)
        for wf in workflows:
            fnum = int(wf["feature_id"].split("-")[1])
            if fnum <= 2:
                assert wf["priority"] == "critical"
            elif fnum <= 5:
                assert wf["priority"] == "high"

    def test_feature_prd_reference(self):
        workflows = _extract_feature_workflows(SAMPLE_PRD)
        f003 = next((w for w in workflows if "f-003" in w["id"]), None)
        assert f003 is not None
        assert "F-003" in f003["prd_reference"]


# ---------------------------------------------------------------------------
# Heuristic step extraction
# ---------------------------------------------------------------------------


class TestHeuristicExtraction:
    def test_journey_to_steps(self):
        raw_wf = {
            "type": "journey",
            "id": "journey-1-check-status",
            "name": "Check my car status",
            "flow_text": "Open portal → Dashboard → Tap active repair → View status",
            "expected": "",
            "priority": "critical",
            "prd_reference": "Journey 1",
        }
        steps = _extract_steps_heuristic(raw_wf)
        assert len(steps) >= 3
        assert steps[0].action in (StepAction.NAVIGATE, StepAction.CLICK)
        for step in steps:
            assert step.step_number > 0
            assert step.description

    def test_feature_to_steps_skips_backend(self):
        raw_wf = {
            "type": "feature",
            "id": "f-003-quotation",
            "name": "Quotation Approval",
            "steps_raw": [
                {"number": 1, "text": "Customer sees badge on dashboard, taps to view."},
                {"number": 2, "text": "Quotation detail loads from Odoo."},
                {"number": 3, "text": "Screen displays vehicle name and total."},
                {"number": 4, "text": 'Customer taps "Approve".'},
                {"number": 5, "text": "Backend calls Odoo action_confirm()."},
                {"number": 6, "text": "Customer sees confirmation message."},
            ],
            "priority": "critical",
            "prd_reference": "F-003",
        }
        steps = _extract_steps_heuristic(raw_wf)
        # Step 5 (backend) should be skipped
        step_descs = [s.description.lower() for s in steps]
        assert not any("backend" in d for d in step_descs)


# ---------------------------------------------------------------------------
# Action inference
# ---------------------------------------------------------------------------


class TestActionInference:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Customer navigates to Invoices", StepAction.NAVIGATE),
            ("Open the app", StepAction.NAVIGATE),
            ("Tap active repair", StepAction.CLICK),
            ('Click "Approve"', StepAction.CLICK),
            ("Enter email address", StepAction.TYPE),
            ("Customer sees confirmation", StepAction.VERIFY_TEXT),
            ("View status with progress", StepAction.VERIFY_TEXT),
            ("Dashboard loads", StepAction.WAIT),
        ],
    )
    def test_infer_action(self, text, expected):
        assert _infer_action(text) == expected


class TestBackendStepDetection:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Backend validates email format", True),
            ("Backend calls Odoo action_confirm()", True),
            ("Customer taps Approve", False),
            ("Screen displays vehicle name", False),
            ("Database updates the record", True),
            ("Webhook fires for payment", True),
        ],
    )
    def test_is_backend_step(self, text, expected):
        assert _is_backend_step(text) == expected


# ---------------------------------------------------------------------------
# Route conversion
# ---------------------------------------------------------------------------


class TestFilePathToRoute:
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("page.tsx", "/"),
            ("invoices/page.tsx", "/invoices"),
            ("invoices/[id]/page.tsx", "/invoices/:id"),
            ("(dashboard)/settings/page.tsx", "/settings"),
            ("(dashboard)/invoices/[id]/page.tsx", "/invoices/:id"),
        ],
    )
    def test_converts(self, path, expected):
        assert _file_path_to_route(path) == expected


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestJSONParsing:
    def test_direct_json(self):
        result = _parse_json_from_response('[{"step": 1}]')
        assert result == [{"step": 1}]

    def test_json_in_code_block(self):
        text = 'Some text\n```json\n[{"step": 1}]\n```\nMore text'
        result = _parse_json_from_response(text)
        assert result == [{"step": 1}]

    def test_json_object_in_text(self):
        text = 'Here are the results: {"workflow_id": "test", "steps": []} end.'
        result = _parse_json_from_response(text)
        assert result == {"workflow_id": "test", "steps": []}

    def test_json_array_in_text(self):
        text = 'Steps: [{"step": 1}] done.'
        result = _parse_json_from_response(text)
        assert result == [{"step": 1}]

    def test_invalid_json(self):
        assert _parse_json_from_response("not json at all") is None


# ---------------------------------------------------------------------------
# Failure to Finding conversion
# ---------------------------------------------------------------------------


class TestFailureToFinding:
    def test_converts_click_failure(self):
        workflow = Workflow(
            id="f003-approve",
            name="Approve Quotation",
            prd_reference="F-003, Workflow step 4",
            priority="critical",
            steps=[
                WorkflowStep(
                    step_number=1,
                    action=StepAction.NAVIGATE,
                    description="Navigate to dashboard",
                    target="/dashboard",
                ),
                WorkflowStep(
                    step_number=2,
                    action=StepAction.CLICK,
                    description="Click Approve button",
                    target="Approve",
                    expected_outcome="Confirmation message shown",
                ),
            ],
        )
        sr = StepResult(
            step=workflow.steps[1],
            status="fail",
            error_message="Element not found: Approve button",
            actual_outcome="No button with text 'Approve' found",
            console_errors=["TypeError: x is not a function"],
        )
        finding = _step_failure_to_finding(workflow, sr)

        assert finding.id == "BROWSER-f003-approve-STEP2"
        assert finding.feature == "F-003"
        assert finding.severity == Severity.HIGH
        assert finding.category == FindingCategory.CODE_FIX
        assert "Approve" in finding.title
        assert "F-003" in finding.prd_reference

    def test_converts_navigation_failure(self):
        workflow = Workflow(
            id="f005-invoices",
            name="Invoice Access",
            prd_reference="F-005",
            steps=[
                WorkflowStep(
                    step_number=1,
                    action=StepAction.NAVIGATE,
                    description="Navigate to invoices",
                    target="/invoices",
                ),
            ],
        )
        sr = StepResult(
            step=workflow.steps[0],
            status="fail",
            error_message="404 Not Found",
        )
        finding = _step_failure_to_finding(workflow, sr)
        assert finding.severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# BrowserTestReport
# ---------------------------------------------------------------------------


class TestBrowserTestReport:
    def _make_report(self, pass_steps=3, fail_steps=1) -> BrowserTestReport:
        workflow = Workflow(
            id="test-wf",
            name="Test Workflow",
            prd_reference="F-001",
            steps=[],
        )
        step_results = []
        for i in range(pass_steps):
            step_results.append(StepResult(
                step=WorkflowStep(
                    step_number=i + 1,
                    action=StepAction.CLICK,
                    description=f"Step {i + 1}",
                ),
                status="pass",
                actual_outcome="OK",
            ))
        for i in range(fail_steps):
            step_results.append(StepResult(
                step=WorkflowStep(
                    step_number=pass_steps + i + 1,
                    action=StepAction.CLICK,
                    description=f"Failed step {i + 1}",
                    expected_outcome="Should work",
                ),
                status="fail",
                error_message="Element not found",
            ))

        wr = WorkflowResult(
            workflow=workflow,
            status="fail" if fail_steps > 0 else "pass",
            step_results=step_results,
        )
        report = BrowserTestReport(
            app_url="http://localhost:3080",
            timestamp="2026-03-21 10:00:00",
            workflows_tested=1,
            workflows_passed=0 if fail_steps else 1,
            workflows_failed=1 if fail_steps else 0,
            total_steps=pass_steps + fail_steps,
            total_passed=pass_steps,
            total_failed=fail_steps,
            results=[wr],
        )
        return report

    def test_all_passed_true(self):
        report = self._make_report(pass_steps=5, fail_steps=0)
        assert report.all_passed is True

    def test_all_passed_false(self):
        report = self._make_report(pass_steps=3, fail_steps=1)
        assert report.all_passed is False

    def test_pass_rate(self):
        report = self._make_report(pass_steps=3, fail_steps=1)
        assert report.pass_rate == 75.0

    def test_to_findings(self):
        report = self._make_report(pass_steps=2, fail_steps=2)
        findings = report.to_findings()
        assert len(findings) == 2
        for f in findings:
            assert f.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM)

    def test_to_dict(self):
        report = self._make_report(pass_steps=2, fail_steps=1)
        d = report.to_dict()
        assert d["workflows_tested"] == 1
        assert d["total_steps"] == 3
        assert "results" in d


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    def test_generates_markdown(self, tmp_path):
        report = BrowserTestReport(
            app_url="http://localhost:3080",
            timestamp="2026-03-21 10:00:00",
            workflows_tested=1,
            workflows_passed=1,
            workflows_failed=0,
            total_steps=3,
            total_passed=3,
            total_failed=0,
            results=[
                WorkflowResult(
                    workflow=Workflow(
                        id="test",
                        name="Test",
                        prd_reference="F-001",
                        priority="critical",
                        steps=[],
                    ),
                    status="pass",
                    step_results=[
                        StepResult(
                            step=WorkflowStep(
                                step_number=1,
                                action=StepAction.NAVIGATE,
                                description="Go to homepage",
                            ),
                            status="pass",
                            actual_outcome="Page loaded",
                        ),
                    ],
                ),
            ],
        )

        path = generate_browser_test_report(report, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "Browser Test Report" in content
        assert "Workflows tested" in content
        assert "PASS" in content

    def test_generates_json(self, tmp_path):
        report = BrowserTestReport(
            app_url="http://localhost:3080",
            timestamp="2026-03-21",
            results=[],
        )
        generate_browser_test_report(report, tmp_path)
        json_path = tmp_path / "browser_test_results.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["app_url"] == "http://localhost:3080"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestSlugify:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Sign Up Flow", "sign-up-flow"),
            ("F-001: Authentication", "f-001-authentication"),
            ("Hello World!!!", "hello-world"),
        ],
    )
    def test_slugify(self, text, expected):
        assert _slugify(text) == expected


class TestProjectName:
    def test_extracts_name(self):
        assert _extract_project_name("# My Cool App — PRD\n\nContent") == "My Cool App"

    def test_strips_prd_suffix(self):
        assert _extract_project_name("# Product PRD\n") == "Product"

    def test_unknown_on_no_title(self):
        assert _extract_project_name("No title here") == "Unknown App"


# ---------------------------------------------------------------------------
# WorkflowStep serialization
# ---------------------------------------------------------------------------


class TestWorkflowStepSerialization:
    def test_to_dict(self):
        step = WorkflowStep(
            step_number=1,
            action=StepAction.CLICK,
            description="Click button",
            target="approve-btn",
        )
        d = step.to_dict()
        assert d["action"] == "click"
        assert d["step_number"] == 1

    def test_from_dict(self):
        d = {
            "step_number": 2,
            "action": "navigate",
            "description": "Go to page",
            "target": "/invoices",
        }
        step = WorkflowStep.from_dict(d)
        assert step.action == StepAction.NAVIGATE
        assert step.target == "/invoices"


# ---------------------------------------------------------------------------
# Operator prompt construction
# ---------------------------------------------------------------------------


class TestExecuteWorkflow:
    """Tests for workflow execution with mocked subprocess."""

    def _make_workflow(self) -> Workflow:
        return Workflow(
            id="test-wf",
            name="Test Workflow",
            prd_reference="F-001",
            priority="critical",
            steps=[
                WorkflowStep(
                    step_number=1,
                    action=StepAction.NAVIGATE,
                    description="Go to homepage",
                    target="/",
                ),
                WorkflowStep(
                    step_number=2,
                    action=StepAction.CLICK,
                    description="Click button",
                    target="Submit",
                ),
            ],
        )

    @patch("agent_team_v15.browser_test_agent.subprocess.run")
    def test_execute_workflow_success(self, mock_run, tmp_path):
        # Mock claude --version check
        version_result = MagicMock(returncode=0, stdout="claude 1.0.0\n")
        # Mock the actual execution
        execution_result = MagicMock(
            returncode=0,
            stdout='```json\n{"workflow_id": "test-wf", "steps": [{"step_number": 1, "status": "pass", "actual_outcome": "Page loaded", "error_message": "", "console_errors": [], "screenshot": "step_01.png"}, {"step_number": 2, "status": "pass", "actual_outcome": "Clicked", "error_message": "", "console_errors": [], "screenshot": "step_02.png"}]}\n```',
            stderr="",
        )
        mock_run.side_effect = [version_result, execution_result]

        engine = BrowserTestEngine(
            app_url="http://localhost:3080",
            screenshot_dir=tmp_path / "screenshots",
        )
        result = engine.execute_workflow(self._make_workflow())

        assert result.status == "pass"
        assert result.passed_steps == 2
        assert result.failed_steps == 0
        assert mock_run.call_count == 2

    @patch("agent_team_v15.browser_test_agent.subprocess.run")
    def test_execute_workflow_claude_not_found(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError("claude not found")

        engine = BrowserTestEngine(
            app_url="http://localhost:3080",
            screenshot_dir=tmp_path / "screenshots",
        )
        result = engine.execute_workflow(self._make_workflow())

        assert result.status == "fail"
        assert result.failed_steps == 2

    @patch("agent_team_v15.browser_test_agent.subprocess.run")
    def test_execute_workflow_timeout(self, mock_run, tmp_path):
        import subprocess as sp
        version_result = MagicMock(returncode=0, stdout="claude 1.0.0\n")
        mock_run.side_effect = [version_result, sp.TimeoutExpired(cmd="claude", timeout=300)]

        engine = BrowserTestEngine(
            app_url="http://localhost:3080",
            screenshot_dir=tmp_path / "screenshots",
        )
        result = engine.execute_workflow(self._make_workflow())

        assert result.status == "fail"

    @patch("agent_team_v15.browser_test_agent.subprocess.run")
    def test_execute_workflow_partial_failure(self, mock_run, tmp_path):
        version_result = MagicMock(returncode=0, stdout="claude 1.0.0\n")
        execution_result = MagicMock(
            returncode=0,
            stdout='```json\n{"workflow_id": "test-wf", "steps": [{"step_number": 1, "status": "pass", "actual_outcome": "OK", "error_message": "", "console_errors": []}, {"step_number": 2, "status": "fail", "actual_outcome": "Not found", "error_message": "Element missing", "console_errors": ["TypeError"]}]}\n```',
            stderr="",
        )
        mock_run.side_effect = [version_result, execution_result]

        engine = BrowserTestEngine(
            app_url="http://localhost:3080",
            screenshot_dir=tmp_path / "screenshots",
        )
        result = engine.execute_workflow(self._make_workflow())

        assert result.status == "partial"
        assert result.passed_steps == 1
        assert result.failed_steps == 1


class TestOperatorPrompt:
    def test_prompt_contains_workflow_info(self):
        engine = BrowserTestEngine(
            app_url="http://localhost:3080",
            auth_token="test-token-123",
        )
        workflow = Workflow(
            id="f003-approve",
            name="Approve Quotation",
            prd_reference="F-003",
            priority="critical",
            steps=[
                WorkflowStep(
                    step_number=1,
                    action=StepAction.NAVIGATE,
                    description="Navigate to dashboard",
                    target="/dashboard",
                ),
                WorkflowStep(
                    step_number=2,
                    action=StepAction.CLICK,
                    description="Click Approve button",
                    target="Approve",
                ),
            ],
        )
        prompt = engine._build_operator_prompt(workflow, Path("/tmp/screenshots"))
        assert "http://localhost:3080" in prompt
        assert "Approve Quotation" in prompt
        assert "f003-approve" in prompt
        assert "Navigate to dashboard" in prompt
        assert "Click Approve button" in prompt
        assert "test-token-123" in prompt
        assert "browser_snapshot" in prompt.lower() or "snapshot" in prompt.lower()
