"""Browser Test Agent — Extracts workflows from PRDs, executes them via Playwright MCP.

The agent works in three phases:
1. EXTRACTION: Claude reads PRD text → structured WorkflowStep objects
2. EXECUTION: Claude operator session uses Playwright MCP to walk each workflow
3. REPORTING: Collect results, screenshots, generate evidence report

The Playwright MCP is the execution mechanism — the agent constructs prompts
for a Claude session that HAS Playwright MCP tools. Claude operates the browser.

Typical usage::

    from pathlib import Path
    from agent_team_v15.browser_test_agent import (
        extract_workflows_from_prd,
        BrowserTestEngine,
        generate_browser_test_report,
    )

    workflows = extract_workflows_from_prd(Path("prd.md"))
    engine = BrowserTestEngine(app_url="http://localhost:3080")
    report = engine.run_all(workflows)
    generate_browser_test_report(report, Path(".agent-team"))
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StepAction(Enum):
    """Browser test step action types."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    WAIT = "wait"
    VERIFY_TEXT = "verify_text"
    VERIFY_ELEMENT = "verify_element"
    VERIFY_URL = "verify_url"
    SCREENSHOT = "screenshot"
    SELECT = "select"
    SCROLL = "scroll"


# ---------------------------------------------------------------------------
# Data structures — Workflow definition
# ---------------------------------------------------------------------------


@dataclass
class WorkflowStep:
    """A single step in a browser test workflow."""

    step_number: int
    action: StepAction
    description: str  # Human-readable: "Click the Approve button"
    target: str = ""  # Selector, URL, or text to type
    target_type: str = "auto"  # "testid", "text", "css", "url", "aria"
    expected_outcome: str = ""  # "Quotation status changes to Confirmed"
    wait_for: str = ""  # Element/text to wait for before proceeding
    wait_timeout_ms: int = 10000
    capture_screenshot: bool = True
    optional: bool = False  # If True, failure doesn't fail the workflow

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowStep:
        data = dict(data)
        if isinstance(data.get("action"), str):
            data["action"] = StepAction(data["action"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Workflow:
    """A complete browser test workflow extracted from the PRD."""

    id: str  # "f003-approve-quotation" or "journey-1-check-status"
    name: str  # "Approve Quotation Flow"
    prd_reference: str  # "F-003, Workflow steps 1-7"
    priority: str = "high"  # "critical", "high", "medium"
    preconditions: list[str] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    expected_duration_seconds: int = 0
    source_text: str = ""  # Original PRD text for reference

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prd_reference": self.prd_reference,
            "priority": self.priority,
            "preconditions": self.preconditions,
            "steps": [s.to_dict() for s in self.steps],
            "expected_duration_seconds": self.expected_duration_seconds,
        }


@dataclass
class WorkflowSuite:
    """Collection of all workflows extracted from a PRD."""

    app_name: str
    prd_path: str
    workflows: list[Workflow] = field(default_factory=list)

    @property
    def critical_workflows(self) -> list[Workflow]:
        return [w for w in self.workflows if w.priority == "critical"]

    @property
    def high_workflows(self) -> list[Workflow]:
        return [w for w in self.workflows if w.priority in ("critical", "high")]


# ---------------------------------------------------------------------------
# Data structures — Test results
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of executing a single workflow step."""

    step: WorkflowStep
    status: str  # "pass", "fail", "skip"
    actual_outcome: str = ""
    screenshot_path: str = ""
    error_message: str = ""
    duration_ms: int = 0
    console_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step.step_number,
            "action": self.step.action.value,
            "description": self.step.description,
            "status": self.status,
            "actual_outcome": self.actual_outcome,
            "screenshot_path": self.screenshot_path,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "console_errors": self.console_errors,
        }


@dataclass
class WorkflowResult:
    """Result of executing a complete workflow."""

    workflow: Workflow
    status: str = "pending"  # "pass", "fail", "partial", "error"
    step_results: list[StepResult] = field(default_factory=list)
    total_duration_ms: int = 0

    @property
    def passed_steps(self) -> int:
        return sum(1 for s in self.step_results if s.status == "pass")

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.step_results if s.status == "fail")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow.id,
            "workflow_name": self.workflow.name,
            "status": self.status,
            "passed_steps": self.passed_steps,
            "failed_steps": self.failed_steps,
            "total_steps": len(self.step_results),
            "step_results": [s.to_dict() for s in self.step_results],
            "total_duration_ms": self.total_duration_ms,
        }


@dataclass
class BrowserTestReport:
    """Aggregate browser test results for all workflows."""

    app_url: str
    timestamp: str
    workflows_tested: int = 0
    workflows_passed: int = 0
    workflows_failed: int = 0
    total_steps: int = 0
    total_passed: int = 0
    total_failed: int = 0
    results: list[WorkflowResult] = field(default_factory=list)
    screenshot_dir: str = ""
    extraction_cost: float = 0.0
    execution_cost: float = 0.0

    @property
    def all_passed(self) -> bool:
        return self.workflows_failed == 0 and self.workflows_tested > 0

    @property
    def pass_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.total_passed / self.total_steps) * 100

    def to_findings(self) -> list[Finding]:
        """Convert browser test failures into audit Findings for the fix loop."""
        findings = []
        for wr in self.results:
            if wr.status == "pass":
                continue
            for sr in wr.step_results:
                if sr.status == "fail":
                    finding = _step_failure_to_finding(wr.workflow, sr)
                    findings.append(finding)
        return findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_url": self.app_url,
            "timestamp": self.timestamp,
            "workflows_tested": self.workflows_tested,
            "workflows_passed": self.workflows_passed,
            "workflows_failed": self.workflows_failed,
            "total_steps": self.total_steps,
            "total_passed": self.total_passed,
            "total_failed": self.total_failed,
            "pass_rate": self.pass_rate,
            "results": [r.to_dict() for r in self.results],
            "screenshot_dir": self.screenshot_dir,
        }


# ---------------------------------------------------------------------------
# Failure → Finding conversion
# ---------------------------------------------------------------------------


_SEVERITY_MAP = {
    StepAction.NAVIGATE: Severity.CRITICAL,
    StepAction.CLICK: Severity.HIGH,
    StepAction.TYPE: Severity.HIGH,
    StepAction.VERIFY_TEXT: Severity.MEDIUM,
    StepAction.VERIFY_ELEMENT: Severity.MEDIUM,
    StepAction.VERIFY_URL: Severity.MEDIUM,
    StepAction.WAIT: Severity.HIGH,
    StepAction.SELECT: Severity.HIGH,
    StepAction.SCROLL: Severity.LOW,
    StepAction.SCREENSHOT: Severity.LOW,
}


def _step_failure_to_finding(workflow: Workflow, sr: StepResult) -> Finding:
    """Convert a failed browser step into an audit Finding."""
    severity = _SEVERITY_MAP.get(sr.step.action, Severity.MEDIUM)

    # Infer file path from route if possible
    file_path = ""
    for step in workflow.steps:
        if step.action == StepAction.NAVIGATE and step.target.startswith("/"):
            # /quotations/[id] → src/app/quotations/[id]/page.tsx
            route = step.target.rstrip("/")
            file_path = f"src/app{route}/page.tsx"
            break

    feature = ""
    ref = workflow.prd_reference
    # Extract feature ID like "F-003" from prd_reference
    m = re.search(r"F-\d{3}", ref)
    if m:
        feature = m.group()

    return Finding(
        id=f"BROWSER-{workflow.id}-STEP{sr.step.step_number}",
        feature=feature or "BROWSER",
        acceptance_criterion=f"Browser workflow '{workflow.name}' step {sr.step.step_number}: {sr.step.description}",
        severity=severity,
        category=FindingCategory.UX if sr.step.action in (StepAction.VERIFY_TEXT, StepAction.VERIFY_ELEMENT) else FindingCategory.CODE_FIX,
        title=f"{sr.step.action.value.upper()} failed: {sr.step.description[:80]}",
        description=(
            f"Browser test for {workflow.name} ({workflow.prd_reference}), "
            f"step {sr.step.step_number}: {sr.step.description}.\n"
            f"Error: {sr.error_message}\n"
            f"Console errors: {', '.join(sr.console_errors) if sr.console_errors else 'None'}"
        ),
        prd_reference=workflow.prd_reference,
        current_behavior=sr.actual_outcome or "Step failed during browser testing",
        expected_behavior=sr.step.expected_outcome or sr.step.description,
        file_path=file_path,
        fix_suggestion=_suggest_fix(sr),
        estimated_effort="small",
    )


def _suggest_fix(sr: StepResult) -> str:
    """Generate a fix suggestion based on the failure type."""
    action = sr.step.action
    if action == StepAction.NAVIGATE:
        return f"Ensure route {sr.step.target} exists and renders without errors."
    if action == StepAction.CLICK:
        return (
            f"Verify the element '{sr.step.description}' has a working onClick handler. "
            f"Check that the target element exists and is not hidden by CSS."
        )
    if action == StepAction.TYPE:
        return f"Verify the input element is visible and accepts text input."
    if action in (StepAction.VERIFY_TEXT, StepAction.VERIFY_ELEMENT):
        return (
            f"Verify the expected content '{sr.step.target}' is rendered on the page. "
            f"Check component rendering logic and data fetching."
        )
    if action == StepAction.WAIT:
        return (
            f"Element/content '{sr.step.wait_for}' did not appear within timeout. "
            f"Check loading states, API calls, and conditional rendering."
        )
    return "Review the component rendering and interaction logic."


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [browser-test] {msg}")


# ---------------------------------------------------------------------------
# PRD Workflow Extraction
# ---------------------------------------------------------------------------

# Regex patterns for parsing PRD workflow sections
_RE_JOURNEY = re.compile(
    r"\*\*Journey\s+(\d+):\s*\"([^\"]+)\"[^*]*\*\*\s*\n(.+?)(?=\n\*\*Journey|\n##|\Z)",
    re.DOTALL,
)

_RE_FEATURE_HEADER = re.compile(
    r"##\s*\d+\.\d+\s+(F-\d{3})[\s:]+(.+?)(?:\n|$)",
)

_RE_WORKFLOW_SECTION = re.compile(
    r"-\s*\*\*Workflow:?\*\*\s*\n([\s\S]+?)(?=\n-\s*\*\*(?!On |Error)|\n##|\Z)",
)

_RE_NUMBERED_STEP = re.compile(
    r"^\s*(\d+)\.\s+(.+?)$",
    re.MULTILINE,
)

_RE_ARROW_FLOW = re.compile(r"[→]")


def _extract_journey_section(prd_text: str) -> list[dict[str, Any]]:
    """Extract user journey definitions from PRD Section 8.1 or similar.

    Journeys are arrow-delimited: "Open app → Tap repair → View status"
    """
    journeys = []

    for m in _RE_JOURNEY.finditer(prd_text):
        journey_num = m.group(1)
        journey_name = m.group(2).strip()
        journey_body = m.group(3).strip()

        # Extract the arrow flow (first line that contains →)
        flow_text = ""
        expected = ""
        for line in journey_body.splitlines():
            if "→" in line or "→" in line:
                flow_text = line.strip()
            elif line.strip().lower().startswith("expected:"):
                expected = line.strip()

        if flow_text:
            journeys.append({
                "type": "journey",
                "id": f"journey-{journey_num}-{_slugify(journey_name)}",
                "name": journey_name,
                "flow_text": flow_text,
                "expected": expected,
                "priority": "critical" if int(journey_num) <= 2 else "high",
                "prd_reference": f"Section 8.1, Journey {journey_num}",
            })

    return journeys


def _extract_feature_workflows(prd_text: str) -> list[dict[str, Any]]:
    """Extract feature workflow sections (F-001 through F-XXX).

    Each feature has a "Workflow:" subsection with numbered steps.
    """
    workflows = []

    # Find all feature sections
    feature_sections = []
    for m in _RE_FEATURE_HEADER.finditer(prd_text):
        feature_sections.append({
            "feature_id": m.group(1),
            "feature_name": m.group(2).strip(),
            "start": m.start(),
        })

    for i, feat in enumerate(feature_sections):
        # Get section text (from this header to next header or end)
        start = feat["start"]
        end = feature_sections[i + 1]["start"] if i + 1 < len(feature_sections) else len(prd_text)
        section_text = prd_text[start:end]

        # Find workflow subsection
        wf_match = _RE_WORKFLOW_SECTION.search(section_text)
        if not wf_match:
            continue

        workflow_text = wf_match.group(1)

        # Extract numbered steps
        steps_raw = []
        for step_match in _RE_NUMBERED_STEP.finditer(workflow_text):
            steps_raw.append({
                "number": int(step_match.group(1)),
                "text": step_match.group(2).strip(),
            })

        if steps_raw:
            # Determine priority from feature ID
            fnum = int(feat["feature_id"].split("-")[1])
            priority = "critical" if fnum <= 2 else "high" if fnum <= 5 else "medium"

            workflows.append({
                "type": "feature",
                "id": f"{feat['feature_id'].lower()}-{_slugify(feat['feature_name'])}",
                "name": f"{feat['feature_id']}: {feat['feature_name']}",
                "feature_id": feat["feature_id"],
                "steps_raw": steps_raw,
                "workflow_text": workflow_text.strip(),
                "priority": priority,
                "prd_reference": f"{feat['feature_id']}, Workflow",
            })

    return workflows


def _slugify(text: str) -> str:
    """Convert text to a URL/filename-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")[:50]


# ---------------------------------------------------------------------------
# Claude-based workflow structuring
# ---------------------------------------------------------------------------


_WORKFLOW_EXTRACTION_PROMPT = """\
You are converting PRD workflow descriptions into structured browser test steps.

AVAILABLE ACTIONS:
- navigate: Go to a URL path (e.g., "/dashboard", "/invoices")
- click: Click a button, link, or interactive element
- type: Type text into an input field
- wait: Wait for an element or condition
- verify_text: Verify specific text content exists on the page
- verify_element: Verify a UI element exists and is visible
- verify_url: Verify the current URL matches expected
- select: Select from a dropdown
- scroll: Scroll to an element

SELECTOR PRIORITY:
1. data-testid: [data-testid="approve-quotation-detail"]
2. Button/link text: "Approve", "Submit", "Invoices"
3. Input placeholder/label: "Enter email", "Search"
4. ARIA label: "Close dialog"

RULES:
- Follow the HAPPY PATH through any branch/decision points
- Skip backend-only steps (e.g., "Backend calls Odoo", "Database updates")
- Add a verify step after every significant user action
- Add a wait step before interacting with dynamically loaded content
- Every navigation and click should have capture_screenshot: true
- Mark steps that depend on external data/services as optional: true
- Use descriptive targets that a browser operator can find visually

WORKFLOW TO CONVERT:
{workflow_text}

CONTEXT:
- App name: {app_name}
- PRD reference: {prd_reference}
- Priority: {priority}

Convert into a JSON array of step objects. Return ONLY valid JSON, no explanation:
[
  {{
    "step_number": 1,
    "action": "navigate",
    "description": "Navigate to the dashboard",
    "target": "/dashboard",
    "target_type": "url",
    "expected_outcome": "Dashboard page loads",
    "wait_for": "",
    "wait_timeout_ms": 10000,
    "capture_screenshot": true,
    "optional": false
  }}
]
"""


def extract_workflows_from_prd(
    prd_path: Path,
    codebase_path: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
) -> WorkflowSuite:
    """Extract testable workflows from a PRD file.

    Strategy:
    1. Parse PRD for user journeys (arrow-delimited flows)
    2. Parse PRD for feature workflows (numbered steps)
    3. Convert to structured WorkflowStep sequences using Claude
    4. Return WorkflowSuite

    Args:
        prd_path: Path to the PRD markdown file.
        codebase_path: Optional path to the built codebase (for route discovery).
        config: Optional config with 'extraction_model' key.

    Returns:
        WorkflowSuite with extracted workflows.
    """
    config = config or {}
    prd_text = prd_path.read_text(encoding="utf-8")

    # Extract project name
    app_name = _extract_project_name(prd_text)

    # Extract raw workflows from PRD
    journeys = _extract_journey_section(prd_text)
    features = _extract_feature_workflows(prd_text)

    _log(f"Extracted {len(journeys)} journeys + {len(features)} feature workflows from PRD")

    # Discover page routes from codebase (if available)
    routes = []
    if codebase_path:
        routes = _discover_page_routes(codebase_path)
        _log(f"Discovered {len(routes)} page routes from codebase")

    # Convert to structured workflows using Claude
    all_raw = journeys + features
    structured = []

    for raw_wf in all_raw:
        workflow = _structure_single_workflow(raw_wf, app_name, routes, config)
        if workflow and workflow.steps:
            structured.append(workflow)

    _log(f"Structured {len(structured)} workflows with {sum(len(w.steps) for w in structured)} total steps")

    return WorkflowSuite(
        app_name=app_name,
        prd_path=str(prd_path),
        workflows=structured,
    )


def _structure_single_workflow(
    raw_wf: dict[str, Any],
    app_name: str,
    routes: list[dict[str, str]],
    config: dict[str, Any],
) -> Optional[Workflow]:
    """Convert a single raw workflow dict into a structured Workflow.

    Uses Claude to interpret natural language steps into WorkflowStep objects.
    Falls back to heuristic parsing if Claude is unavailable.
    """
    # Build the text to send to Claude
    if raw_wf["type"] == "journey":
        workflow_text = f"Journey: {raw_wf['name']}\nFlow: {raw_wf['flow_text']}\n{raw_wf.get('expected', '')}"
    else:
        # Feature workflow with numbered steps
        steps_text = "\n".join(
            f"{s['number']}. {s['text']}" for s in raw_wf.get("steps_raw", [])
        )
        workflow_text = f"Feature: {raw_wf['name']}\n\nWorkflow:\n{steps_text}"

    # Try Claude extraction
    steps = _extract_steps_with_claude(
        workflow_text=workflow_text,
        app_name=app_name,
        prd_reference=raw_wf["prd_reference"],
        priority=raw_wf["priority"],
        model=config.get("extraction_model", "claude-sonnet-4-20250514"),
    )

    if not steps:
        # Fallback: heuristic extraction
        steps = _extract_steps_heuristic(raw_wf)

    return Workflow(
        id=raw_wf["id"],
        name=raw_wf["name"],
        prd_reference=raw_wf["prd_reference"],
        priority=raw_wf["priority"],
        steps=steps,
        source_text=workflow_text,
    )


def _extract_steps_with_claude(
    workflow_text: str,
    app_name: str,
    prd_reference: str,
    priority: str,
    model: str = "claude-sonnet-4-20250514",
) -> list[WorkflowStep]:
    """Use Claude to convert natural language workflow to structured steps."""
    try:
        import anthropic
    except ImportError:
        _log("anthropic SDK not available, using heuristic extraction")
        return []

    prompt = _WORKFLOW_EXTRACTION_PROMPT.format(
        workflow_text=workflow_text,
        app_name=app_name,
        prd_reference=prd_reference,
        priority=priority,
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract JSON from response
        response_text = response.content[0].text.strip()
        steps_data = _parse_json_from_response(response_text)

        if not isinstance(steps_data, list):
            _log(f"Unexpected extraction response type: {type(steps_data)}")
            return []

        steps = []
        for sd in steps_data:
            try:
                action = StepAction(sd.get("action", "wait"))
            except ValueError:
                action = StepAction.WAIT
            steps.append(WorkflowStep(
                step_number=sd.get("step_number", len(steps) + 1),
                action=action,
                description=sd.get("description", ""),
                target=sd.get("target", ""),
                target_type=sd.get("target_type", "auto"),
                expected_outcome=sd.get("expected_outcome", ""),
                wait_for=sd.get("wait_for", ""),
                wait_timeout_ms=sd.get("wait_timeout_ms", 10000),
                capture_screenshot=sd.get("capture_screenshot", True),
                optional=sd.get("optional", False),
            ))

        return steps

    except Exception as e:
        _log(f"Claude extraction failed: {e}")
        return []


def _extract_steps_heuristic(raw_wf: dict[str, Any]) -> list[WorkflowStep]:
    """Fallback: convert workflow to steps without Claude.

    Uses simple heuristics:
    - Arrow-delimited flows: each segment → navigate or click
    - Numbered steps: map keywords to actions
    """
    steps = []

    if raw_wf["type"] == "journey":
        # Split arrow flow into segments
        flow = raw_wf.get("flow_text", "")
        segments = re.split(r"\s*[→→]\s*", flow)

        for i, segment in enumerate(segments, 1):
            segment = segment.strip().rstrip(".")
            if not segment:
                continue

            action = _infer_action(segment)
            steps.append(WorkflowStep(
                step_number=i,
                action=action,
                description=segment,
                target=_infer_target(segment),
                target_type="text",
                expected_outcome=f"{segment} completes successfully",
                capture_screenshot=True,
            ))
    else:
        # Feature workflow with numbered steps
        for s in raw_wf.get("steps_raw", []):
            text = s["text"]
            # Skip backend-only steps
            if _is_backend_step(text):
                continue

            action = _infer_action(text)
            steps.append(WorkflowStep(
                step_number=s["number"],
                action=action,
                description=text[:200],
                target=_infer_target(text),
                target_type="text",
                expected_outcome="",
                capture_screenshot=True,
                optional=_is_optional_step(text),
            ))

    return steps


def _infer_action(text: str) -> StepAction:
    """Infer the step action from natural language text."""
    lower = text.lower()
    if any(kw in lower for kw in ("navigat", "open", "go to", "visit")):
        return StepAction.NAVIGATE
    if any(kw in lower for kw in ("tap", "click", "press", "select")):
        return StepAction.CLICK
    if any(kw in lower for kw in ("enter", "type", "fill", "input")):
        return StepAction.TYPE
    if any(kw in lower for kw in ("see", "view", "display", "show", "confirm")):
        return StepAction.VERIFY_TEXT
    if any(kw in lower for kw in ("wait", "load")):
        return StepAction.WAIT
    return StepAction.VERIFY_ELEMENT


def _infer_target(text: str) -> str:
    """Extract a selector target from step text."""
    # Look for quoted text
    m = re.search(r'"([^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r"'([^']+)'", text)
    if m:
        return m.group(1)
    # Look for a route path
    m = re.search(r"(/[\w/-]+)", text)
    if m:
        return m.group(1)
    return text[:100]


def _is_backend_step(text: str) -> bool:
    """Check if a step is backend-only (not browser-testable)."""
    lower = text.lower()
    return any(kw in lower for kw in (
        "backend", "server", "database", "odoo", "api call",
        "webhook", "migration", "cron", "queue", "redis",
    ))


def _is_optional_step(text: str) -> bool:
    """Check if a step should be optional."""
    lower = text.lower()
    return any(kw in lower for kw in ("optional", "if available", "may"))


def _extract_project_name(prd_text: str) -> str:
    """Extract project name from PRD title."""
    for line in prd_text.splitlines()[:10]:
        if line.startswith("# "):
            name = line.lstrip("# ").strip()
            # Remove common suffixes
            for suffix in (" — PRD", " PRD", " - PRD", " Product Requirements"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
            return name
    return "Unknown App"


def _discover_page_routes(codebase_path: Path) -> list[dict[str, str]]:
    """Discover page routes from a Next.js/React codebase."""
    # Safe walker — prunes node_modules / .pnpm at descent. Some Next.js
    # monorepos nest node_modules under app/ or src/app/ (hoisted-tools,
    # private deps), so we cannot rely on Path.rglob without post-filter
    # (project_walker.py post smoke #9/#10).
    from .project_walker import iter_project_files

    routes = []

    # Next.js app directory
    for app_dir_name in ("src/app", "app"):
        app_dir = codebase_path / app_dir_name
        if not app_dir.is_dir():
            continue

        for page_file in iter_project_files(
            app_dir, patterns=("page.tsx", "page.jsx"),
        ):
            relative = page_file.relative_to(app_dir)
            route = _file_path_to_route(str(relative))
            routes.append({"path": route, "type": "page", "file": str(page_file)})

    return routes


def _file_path_to_route(file_path: str) -> str:
    """Convert Next.js file path to route.

    Examples:
        page.tsx → /
        invoices/page.tsx → /invoices
        invoices/[id]/page.tsx → /invoices/:id
        (dashboard)/settings/page.tsx → /settings
    """
    # Normalize to forward slashes (Windows paths from pathlib use backslashes)
    file_path = file_path.replace("\\", "/")
    # Remove page.tsx or page.jsx
    route = re.sub(r"/?page\.(tsx|jsx)$", "", file_path)
    # Remove route groups (parenthesized segments)
    route = re.sub(r"\([^)]+\)/", "", route)
    route = re.sub(r"\([^)]+\)", "", route)
    # Convert [param] to :param
    route = re.sub(r"\[([^\]]+)\]", r":\1", route)
    # Normalize
    route = "/" + route.strip("/").replace("\\", "/")
    if route == "/":
        return "/"
    return route.rstrip("/")


def _parse_json_from_response(text: str) -> Any:
    """Extract JSON from Claude's response, handling markdown code blocks."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    m = re.search(r"```(?:json)?\s*\n([\s\S]+?)\n```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding a JSON object or array in the text
    for pattern in (r"(\[[\s\S]+?\])", r"(\{[\s\S]+\})"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    return None


# ---------------------------------------------------------------------------
# Browser Test Engine
# ---------------------------------------------------------------------------


class BrowserTestEngine:
    """Executes workflows using a Claude session with Playwright MCP tools.

    The engine constructs prompts for a Claude operator session that uses
    Playwright MCP tools (browser_navigate, browser_click, browser_snapshot,
    browser_take_screenshot, etc.) to walk through each workflow.
    """

    def __init__(
        self,
        app_url: str = "http://localhost:3080",
        screenshot_dir: Optional[Path] = None,
        auth_token: str = "",
        auth_cookie_name: str = "session",
        operator_model: str = "claude-sonnet-4-20250514",
        claude_cli: str = "claude",
    ):
        self.app_url = app_url.rstrip("/")
        self.screenshot_dir = screenshot_dir or Path(".agent-team/screenshots")
        self.auth_token = auth_token
        self.auth_cookie_name = auth_cookie_name
        self.operator_model = operator_model
        self.claude_cli = claude_cli
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._claude_verified = False

    def run_all(
        self,
        suite: WorkflowSuite,
        only_failed_ids: Optional[list[str]] = None,
    ) -> BrowserTestReport:
        """Execute all workflows (or only specified ones) and return report."""
        report = BrowserTestReport(
            app_url=self.app_url,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            screenshot_dir=str(self.screenshot_dir),
        )

        workflows = suite.workflows
        if only_failed_ids:
            workflows = [w for w in workflows if w.id in only_failed_ids]

        # Sort by priority: critical first, then high, then medium
        priority_order = {"critical": 0, "high": 1, "medium": 2}
        workflows.sort(key=lambda w: priority_order.get(w.priority, 3))

        for workflow in workflows:
            _log(f"Executing workflow: {workflow.name} ({workflow.id})")
            result = self.execute_workflow(workflow)

            report.results.append(result)
            report.workflows_tested += 1
            if result.status == "pass":
                report.workflows_passed += 1
            else:
                report.workflows_failed += 1
            report.total_steps += len(result.step_results)
            report.total_passed += result.passed_steps
            report.total_failed += result.failed_steps

            status_icon = "PASS" if result.status == "pass" else "FAIL"
            _log(
                f"  {status_icon}: {result.passed_steps}/{len(result.step_results)} steps passed"
            )

        return report

    def execute_workflow(self, workflow: Workflow) -> WorkflowResult:
        """Execute a single workflow via Claude + Playwright MCP."""
        result = WorkflowResult(workflow=workflow)

        # Create per-workflow screenshot directory
        wf_screenshot_dir = self.screenshot_dir / _slugify(workflow.id)
        wf_screenshot_dir.mkdir(parents=True, exist_ok=True)

        # Build the operator prompt
        prompt = self._build_operator_prompt(workflow, wf_screenshot_dir)

        # Execute via Claude session
        start_time = time.time()
        try:
            response_text = self._run_operator_session(prompt)
            step_results = self._parse_operator_results(
                response_text, workflow, wf_screenshot_dir
            )
            result.step_results = step_results
        except Exception as e:
            _log(f"  Workflow execution error: {e}")
            # Mark all steps as failed
            for step in workflow.steps:
                result.step_results.append(StepResult(
                    step=step,
                    status="fail",
                    error_message=f"Execution engine error: {e}",
                ))

        result.total_duration_ms = int((time.time() - start_time) * 1000)

        # Determine overall status
        non_optional_failures = [
            s for s in result.step_results
            if s.status == "fail" and not s.step.optional
        ]
        total = len(result.step_results) or 1
        if not non_optional_failures:
            result.status = "pass"
        elif len(non_optional_failures) <= total / 2:
            result.status = "partial"
        else:
            result.status = "fail"

        return result

    def _build_operator_prompt(
        self,
        workflow: Workflow,
        screenshot_dir: Path,
    ) -> str:
        """Build the prompt for the Claude browser operator session."""
        steps_text = ""
        for step in workflow.steps:
            steps_text += (
                f"\nStep {step.step_number}: {step.description}\n"
                f"  Action: {step.action.value}\n"
                f"  Target: {step.target or 'N/A'}\n"
                f"  Target type: {step.target_type}\n"
                f"  Expected: {step.expected_outcome or 'N/A'}\n"
                f"  Wait for: {step.wait_for or 'N/A'} (timeout: {step.wait_timeout_ms}ms)\n"
                f"  Screenshot: {step.capture_screenshot}\n"
                f"  Optional: {step.optional}\n"
            )

        auth_section = ""
        if self.auth_token:
            auth_section = (
                f"\nAUTHENTICATION:\n"
                f"Before executing any workflow steps, authenticate by doing these 3 things in order:\n"
                f"  1. browser_navigate(url: \"{self.app_url}\") — load the app domain first\n"
                f"  2. browser_evaluate(function: \"() => {{ document.cookie = "
                f"'{self.auth_cookie_name}={self.auth_token}; path=/'; }}\")\n"
                f"  3. browser_navigate(url: \"{self.app_url}\") — reload so the cookie takes effect\n"
                f"The auth cookie is now set. Proceed with the workflow steps.\n"
            )
        else:
            auth_section = "\nAUTHENTICATION: No authentication needed.\n"

        return f"""\
You are a browser test operator. Execute the following workflow step-by-step
using Playwright MCP tools. Be precise and systematic.

APPLICATION: {self.app_url}
WORKFLOW: {workflow.name} ({workflow.id})
PRIORITY: {workflow.priority}
PRD REFERENCE: {workflow.prd_reference}
{auth_section}
STEPS TO EXECUTE:
{steps_text}

EXECUTION INSTRUCTIONS:

1. For each step, follow this pattern:
   a. Call browser_snapshot() to see the current page state
   b. Find the target element in the accessibility tree or visible text
   c. Execute the action (browser_navigate, browser_click, browser_type,
      browser_hover, browser_select_option, browser_press_key, browser_wait_for, etc.)
   d. If the step has capture_screenshot=true, call browser_take_screenshot()
   e. Check browser_console_messages() for JavaScript errors

2. SELECTOR STRATEGY (try in order):
   - data-testid: Look for [data-testid="..."] in the snapshot
   - Button/link text: Click elements by their visible text
   - ARIA labels: Use [aria-label="..."] or role-based selectors
   - If the element is not found after trying all strategies, mark step as FAIL

3. ERROR HANDLING:
   - If a step fails, record the error and CONTINUE to the next step
   - Do NOT retry failed steps
   - Do NOT use browser_evaluate() to modify the page or fix issues
     (the only exception is the authentication cookie setup above)
   - Always take a screenshot on failure to capture the current state

4. After completing ALL steps, output your results as a JSON object.
   This MUST be the LAST thing you output, wrapped in ```json code block:

```json
{{
  "workflow_id": "{workflow.id}",
  "steps": [
    {{
      "step_number": 1,
      "status": "pass",
      "actual_outcome": "Description of what happened",
      "error_message": "",
      "console_errors": [],
      "screenshot": "step_01_description.png"
    }},
    {{
      "step_number": 2,
      "status": "fail",
      "actual_outcome": "Button was not found on the page",
      "error_message": "Element not found: Approve button",
      "console_errors": ["TypeError: Cannot read property 'id' of undefined"],
      "screenshot": "step_02_FAIL.png"
    }}
  ]
}}
```

Execute the workflow now. Start with step 1.
"""

    def _verify_claude_cli(self) -> bool:
        """Check that the Claude CLI is available on PATH."""
        if self._claude_verified:
            return True
        try:
            result = subprocess.run(
                [self.claude_cli, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._claude_verified = True
                return True
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return False

    def _run_operator_session(self, prompt: str) -> str:
        """Run a Claude session with Playwright MCP tools.

        Uses Claude Code CLI in print mode. The session has access to all
        Playwright MCP tools (browser_navigate, browser_click, etc.).
        """
        if not self._verify_claude_cli():
            _log(
                f"ERROR: Claude CLI '{self.claude_cli}' not found. "
                f"Install Claude Code: npm install -g @anthropic-ai/claude-code"
            )
            return ""

        cmd = [
            self.claude_cli,
            "--print",
            "--model", self.operator_model,
            "--allowedTools", "mcp__playwright__*",
            "-p", prompt,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes per workflow
                cwd=os.getcwd(),
            )

            if result.returncode != 0:
                _log(f"  Claude session failed: {result.stderr[:200]}")
                return ""

            return result.stdout

        except subprocess.TimeoutExpired:
            _log("  Claude session timed out (5 min)")
            return ""
        except FileNotFoundError:
            _log("  Claude CLI not found — install claude-code globally")
            return ""

    def _parse_operator_results(
        self,
        response_text: str,
        workflow: Workflow,
        screenshot_dir: Path,
    ) -> list[StepResult]:
        """Parse the operator's JSON results into StepResult objects."""
        if not response_text:
            # No response — all steps fail
            return [
                StepResult(
                    step=step,
                    status="fail",
                    error_message="No response from browser operator",
                )
                for step in workflow.steps
            ]

        # Extract JSON from response
        results_data = _parse_json_from_response(response_text)

        if not results_data or not isinstance(results_data, dict):
            # Try to find the JSON in the response
            return [
                StepResult(
                    step=step,
                    status="fail",
                    error_message="Could not parse operator results",
                    actual_outcome=response_text[:500],
                )
                for step in workflow.steps
            ]

        step_data_list = results_data.get("steps", [])
        step_map = {sd.get("step_number"): sd for sd in step_data_list}

        results = []
        for step in workflow.steps:
            sd = step_map.get(step.step_number, {})
            results.append(StepResult(
                step=step,
                status=sd.get("status", "skip"),
                actual_outcome=sd.get("actual_outcome", ""),
                screenshot_path=sd.get("screenshot", ""),
                error_message=sd.get("error_message", ""),
                console_errors=sd.get("console_errors", []),
            ))

        return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------


def generate_browser_test_report(
    report: BrowserTestReport,
    output_dir: Path,
) -> Path:
    """Generate a markdown browser test report with screenshot references.

    Args:
        report: The browser test report data.
        output_dir: Directory to write the report file.

    Returns:
        Path to the generated report file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Browser Test Report",
        "",
        f"**Date:** {report.timestamp}",
        f"**Application:** {report.app_url}",
        f"**Screenshots:** {report.screenshot_dir}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Workflows tested | {report.workflows_tested} |",
        f"| Workflows passed | {report.workflows_passed} |",
        f"| Workflows failed | {report.workflows_failed} |",
        f"| Total steps | {report.total_steps} |",
        f"| Steps passed | {report.total_passed} |",
        f"| Steps failed | {report.total_failed} |",
        f"| Pass rate | {report.pass_rate:.1f}% |",
        "",
        "## Workflow Results",
        "",
    ]

    for wr in report.results:
        status_icon = (
            "PASS" if wr.status == "pass"
            else "PARTIAL" if wr.status == "partial"
            else "FAIL"
        )
        lines.extend([
            f"### [{status_icon}] {wr.workflow.name} ({wr.workflow.id})",
            f"**Priority:** {wr.workflow.priority} | "
            f"**PRD:** {wr.workflow.prd_reference} | "
            f"**Result:** {wr.passed_steps}/{len(wr.step_results)} steps passed",
            "",
            "| Step | Action | Description | Status | Outcome |",
            "|------|--------|-------------|--------|---------|",
        ])

        for sr in wr.step_results:
            s_icon = (
                "PASS" if sr.status == "pass"
                else "FAIL" if sr.status == "fail"
                else "SKIP"
            )
            desc = sr.step.description[:50]
            outcome = (sr.actual_outcome or sr.error_message or "")[:80]
            screenshot = f" [{sr.screenshot_path}]" if sr.screenshot_path else ""
            lines.append(
                f"| {sr.step.step_number} | {sr.step.action.value} | "
                f"{desc} | {s_icon} | {outcome}{screenshot} |"
            )

        # Detail failures
        failures = [sr for sr in wr.step_results if sr.status == "fail"]
        if failures:
            lines.extend(["", "**Failures:**", ""])
            for sr in failures:
                lines.extend([
                    f"**Step {sr.step.step_number}: {sr.step.description}**",
                    f"- Expected: {sr.step.expected_outcome}",
                    f"- Actual: {sr.actual_outcome}",
                    f"- Error: {sr.error_message}",
                    f"- Console: {', '.join(sr.console_errors) if sr.console_errors else 'None'}",
                    f"- Screenshot: {sr.screenshot_path}",
                    "",
                ])

        lines.extend(["", "---", ""])

    # Write report
    report_path = output_dir / "BROWSER_TEST_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    # Also write JSON for programmatic access
    json_path = output_dir / "browser_test_results.json"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )

    return report_path
