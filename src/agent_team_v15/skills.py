"""Department leader skill management.

Reads build outcomes (audit findings, truth scores, gate results) and
maintains per-department skill files that accumulate lessons across builds.
Skills are injected into department leader prompts so leaders operate
with knowledge from previous builds.

All parsing is deterministic Python -- no LLM calls.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Token budget: approximate by word count (1 token ~ 0.75 words for English)
_DEFAULT_MAX_TOKENS = 550
_WORDS_PER_TOKEN = 0.75

# Findings not seen in this many builds get deprioritized
_STALE_THRESHOLD = 5

# Severity tier thresholds
_CRITICAL_THRESHOLD = 0.10
_HIGH_THRESHOLD = 0.50
_MODERATE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Dimension remediation knowledge base (enterprise-grade, 300K LOC targets)
# ---------------------------------------------------------------------------

_DIMENSION_GUIDANCE: dict[str, dict[str, Any]] = {
    "contract_compliance": {
        "critical": [
            "Create `src/contracts/{entity}.contract.ts` with zod schemas for EVERY entity",
            "Define typed request/response schemas BEFORE writing any route handler",
            "Export validation middleware from each contract — wire into routes BEFORE handler logic",
            "Verify every endpoint has a matching contract file before moving on",
        ],
        "high": [
            "Validate all request bodies with zod at route boundaries",
            "Define typed response objects — never return untyped data from endpoints",
        ],
        "moderate": [
            "Audit every endpoint: verify a matching contract exists",
        ],
        "instruction": "Schema first, code second. Do NOT write handlers without contracts.",
        "gate_impact": "GATE_TRUTH_SCORE WILL fail without contracts.",
        "review_rule": "No contracts \u2192 REJECT. Every route must have a zod schema contract.",
        "checklist": "Contract files exist for every entity in `src/contracts/`",
    },
    "test_presence": {
        "critical": [
            "Create `__tests__/{filename}.test.ts` for EVERY source file you write",
            "Each test file: 1 happy-path, 1 error-path, 1 edge-case test minimum",
            "Configure test runner (jest/vitest) in package.json BEFORE writing code",
            "Run `npm test` and verify pass before marking ANY file complete",
        ],
        "high": [
            "Target 80% statement coverage across all modules",
            "Add integration tests for cross-module and cross-domain interactions",
        ],
        "moderate": [
            "Check for untested error paths and boundary conditions",
        ],
        "instruction": "Do NOT defer testing to a later phase. Write tests alongside implementation.",
        "gate_impact": "GATE_TRUTH_SCORE and GATE_E2E WILL fail without tests.",
        "review_rule": "No tests \u2192 REJECT. Every source file must have a test file.",
        "checklist": "Test files exist for every source file in `__tests__/`",
    },
    "security_patterns": {
        "critical": [
            "Add auth middleware to ALL protected routes — no unguarded endpoints",
            "Validate every user input with zod at route boundaries — reject before processing",
            "Use parameterized queries for ALL DB operations — zero string concatenation",
            "Hash passwords with bcrypt (cost \u2265 10), never store plaintext",
        ],
        "high": [
            "Never expose stack traces in responses (use NODE_ENV check)",
            "Load secrets from env vars — no hardcoded JWT_SECRET or DB credentials",
            "Return 404 (not 403) for other users' resources to prevent IDOR info leak",
        ],
        "moderate": [
            "Add CORS, rate limiting, and helmet middleware to Express app",
        ],
        "review_rule": "Raw error exposure \u2192 REJECT. Errors must use `{ error, code }` format.",
        "checklist": "No hardcoded secrets — all credentials loaded from env vars",
    },
    "error_handling": {
        "critical": [
            "Create `src/middleware/errorHandler.ts` as centralized error handler",
            "Wrap EVERY async handler: `asyncHandler(async (req, res) => {...})`",
            "Return structured errors: `{ error: string, code: string }` — never raw exceptions",
            "Register error handler as the LAST middleware in the Express app",
        ],
        "high": [
            "Create typed `AppError` class with HTTP status codes and error codes",
            "Log errors server-side before sending sanitized client response",
        ],
        "moderate": [
            "Verify all try/catch blocks return proper structured error responses",
        ],
        "review_rule": "Unhandled async errors \u2192 REJECT. All async handlers must be wrapped.",
        "checklist": "All async route handlers wrapped in error-handling middleware",
    },
    "requirement_coverage": {
        "critical": [
            "After coding each module, re-read the PRD and verify every item is implemented",
            "Create checklist in REQUIREMENTS.md marking each item as implemented or not",
            "Map every SVC-xxx to a route file and verify each route file exists",
            "Map every REQ-xxx to implementation code with file:line references",
        ],
        "high": [
            "Cross-reference CONTRACTS.json endpoints against implemented routes",
            "Verify every business rule (BR-xxx) has explicit implementation AND tests",
        ],
        "moderate": [
            "Spot-check: pick 5 random requirements and trace each to code",
        ],
        "review_rule": "Unmapped requirements \u2192 REJECT. Every PRD item needs implementation.",
        "checklist": "Every PRD requirement has a corresponding implementation",
    },
    "type_safety": {
        "high": [
            "Enable TypeScript strict mode in tsconfig.json",
            "Replace `any` with proper types — use `unknown` for external data",
        ],
        "moderate": [
            "Eliminate `as any` casts — use proper type assertions or generics",
        ],
        "review_rule": "Unsafe type casts \u2192 REJECT. No `as any` in production code.",
        "checklist": "TypeScript strict mode enabled, zero `as any` casts",
    },
    "post-orchestration": {
        "critical": [
            "Verify all orchestrated outputs compile without errors — run `tsc --noEmit`",
            "Run full test suite after orchestration completes",
            "Check for orphan files — created but never imported anywhere",
        ],
        "high": [
            "Validate all cross-file imports resolve correctly",
            "Verify API endpoints match contract definitions in CONTRACTS.json",
        ],
        "moderate": [
            "Review orchestrator output for incomplete stubs or TODO placeholders",
        ],
        "review_rule": "Compilation errors \u2192 REJECT. All files must compile cleanly.",
        "checklist": "All files compile, all imports resolve, no orphan files",
    },
}


# Gate failure -> corrective action mapping
_GATE_ACTIONS: dict[str, str] = {
    "GATE_REQUIREMENTS": "Ensure REQUIREMENTS.md has all PRD items as REQ-xxx entries",
    "GATE_ARCHITECTURE": "Add Architecture Decision and Integration Roadmap sections to REQUIREMENTS.md",
    "GATE_PSEUDOCODE": "Create pseudocode files in .agent-team/pseudocode/ for every requirement",
    "GATE_CONVERGENCE": "Re-check uncovered requirements \u2014 convergence must reach 90%+",
    "GATE_TRUTH_SCORE": "Focus on weakest dimensions: {weak_dims}",
    "GATE_E2E": "Ensure E2E test suite runs and all endpoints return expected status codes",
    "GATE_INDEPENDENT_REVIEW": "Code must be reviewed by a different agent than the author",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    """A single lesson extracted from audit findings."""

    text: str
    severity: str  # "critical", "high", "medium", "low"
    seen: int = 1       # times this lesson appeared
    total: int = 1      # total builds analyzed
    category: str = ""  # e.g., "testing", "types", "security"


@dataclass
class SkillData:
    """Parsed skill file data."""

    department: str
    builds_analyzed: int = 0
    last_updated: str = ""
    # Dimension scores (current build)
    dimensions: dict[str, float] = field(default_factory=dict)
    # Score history per dimension (all builds)
    score_history: dict[str, list[float]] = field(default_factory=dict)
    # Gate tracking across builds
    gate_fail_counts: dict[str, int] = field(default_factory=dict)
    gate_total_counts: dict[str, int] = field(default_factory=dict)
    gate_reasons: dict[str, str] = field(default_factory=dict)
    # Finding-based lessons (recurring issue tracking)
    critical: list[Lesson] = field(default_factory=list)
    high: list[Lesson] = field(default_factory=list)
    medium: list[Lesson] = field(default_factory=list)
    # Legacy fields (kept for backward compat)
    quality_targets: list[str] = field(default_factory=list)
    gate_history: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_skills_from_build(
    skills_dir: Path,
    state: Any,
    audit_report_path: Path,
    gate_log_path: Path,
) -> None:
    """Update department skill files from build outcomes.

    Reads audit findings, truth scores, and gate results, then writes
    targeted lessons to coding_dept.md and review_dept.md.

    Safe to call when files don't exist yet (first build).
    """
    audit_findings = _read_audit_findings(audit_report_path)
    truth_scores = _read_truth_scores(state)
    gate_entries = _read_gate_log(gate_log_path)

    _meaningful_scores = {k: v for k, v in truth_scores.items()
                          if k != "overall" and isinstance(v, (int, float))}
    if not audit_findings and not _meaningful_scores and not gate_entries:
        _logger.info("[SKILL] No build data found \u2014 skipping skill update")
        print("[SKILL] No build data found \u2014 skipping skill update")
        return

    skills_dir.mkdir(parents=True, exist_ok=True)

    # --- Update coding department ---
    coding_path = skills_dir / "coding_dept.md"
    coding_data = _parse_skill_file(coding_path, "coding")
    coding_data = _update_coding_skills(coding_data, audit_findings, truth_scores)
    _write_skill_file(coding_path, coding_data)
    _logger.info("[SKILL] Updated %s (%d lessons)", coding_path, _count_lessons(coding_data))
    print(f"[SKILL] Updated coding_dept.md ({_count_lessons(coding_data)} lessons)")

    # --- Update review department ---
    review_path = skills_dir / "review_dept.md"
    review_data = _parse_skill_file(review_path, "review")
    review_data = _update_review_skills(review_data, audit_findings, truth_scores, gate_entries)
    _write_skill_file(review_path, review_data)
    _logger.info("[SKILL] Updated %s (%d lessons)", review_path, _count_lessons(review_data))
    print(f"[SKILL] Updated review_dept.md ({_count_lessons(review_data)} lessons)")
    print("[SKILL] Department skills updated from build outcomes")


def load_skills_for_department(
    skills_dir: Path,
    department: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> str:
    """Load and return skill content for injection into department prompt.

    Returns empty string if no skill file exists (first build, backward compat).
    """
    filename = f"{department}_dept.md"
    skill_path = skills_dir / filename
    if not skill_path.is_file():
        return ""
    try:
        content = skill_path.read_text(encoding="utf-8")
        return _enforce_token_budget(content, max_tokens)
    except (OSError, UnicodeDecodeError) as exc:
        _logger.warning("[SKILL] Failed to read %s: %s", skill_path, exc)
        return ""


# ---------------------------------------------------------------------------
# Audit data readers
# ---------------------------------------------------------------------------

def _read_audit_findings(path: Path) -> list[dict[str, Any]]:
    """Read findings from AUDIT_REPORT.json (supports both formats)."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        # New format: data.audit_report.deduplicated_findings
        if "audit_report" in data:
            findings = data["audit_report"].get("deduplicated_findings", [])
            for f in findings:
                f.setdefault("id", f.get("finding_id", ""))
                f.setdefault("title", f.get("summary", ""))
                f.setdefault("category", _infer_category(f))
                if "severity" in f:
                    f["severity"] = f["severity"].lower()
            return findings

        # Old format: data.findings with score.deductions
        findings = data.get("findings", [])
        deductions = {
            d.get("finding_id", ""): d
            for d in data.get("score", {}).get("deductions", [])
            if d.get("finding_id")
        }
        for f in findings:
            fid = f.get("id", "")
            if fid in deductions:
                f.setdefault("severity", deductions[fid].get("severity", "medium"))
                f.setdefault("points", deductions[fid].get("points", 0))
        return findings
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        _logger.warning("[SKILL] Failed to read audit report: %s", exc)
        return []


def _infer_category(finding: dict[str, Any]) -> str:
    """Infer finding category from requirement_id or content keywords."""
    req_id = finding.get("requirement_id", "")
    if req_id.startswith("TEST"):
        return "testing"
    if req_id.startswith("WIRE"):
        return "architecture"
    if req_id.startswith("SVC"):
        return "api"
    if req_id.startswith("API"):
        return "contracts"
    text = (finding.get("summary", "") + " " + finding.get("title", "")).lower()
    if "test" in text:
        return "testing"
    if any(w in text for w in ("auth", "security", "password", "jwt", "cors")):
        return "security"
    if any(w in text for w in ("contract", "schema", "validation")):
        return "contracts"
    return "general"


def _read_truth_scores(state: Any) -> dict[str, float]:
    """Extract truth scores from RunState."""
    scores = getattr(state, "truth_scores", None)
    if isinstance(scores, dict):
        return {k: float(v) for k, v in scores.items() if isinstance(v, (int, float))}
    return {}


def _read_gate_log(path: Path) -> list[dict[str, str]]:
    """Parse GATE_AUDIT.log entries."""
    if not path.is_file():
        return []
    entries: list[dict[str, str]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\[.*?\]\s+(GATE_\w+):\s+(PASS|FAIL)\s*\u2014?\s*(.*)", line)
            if m:
                entries.append({
                    "gate": m.group(1),
                    "result": m.group(2),
                    "reason": m.group(3).strip(),
                })
    except (OSError, UnicodeDecodeError):
        pass
    return entries


# ---------------------------------------------------------------------------
# Metadata parsing (score history + gate counts in HTML comments)
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(
    r"<!--\s*Last updated:\s*(.*?)\s*\|\s*Builds analyzed:\s*(\d+)\s*-->",
)
_SCORES_RE = re.compile(r"<!--\s*Scores:\s*(.*?)\s*-->")
_GATES_META_RE = re.compile(r"<!--\s*GateCounts:\s*(.*?)\s*-->")
_SEEN_RE = re.compile(r"\[seen:\s*(\d+)/(\d+)\s*\]")


def _parse_score_history(text: str) -> dict[str, list[float]]:
    """Parse score history from ``<!-- Scores: dim=s1;s2|... -->`` comment."""
    m = _SCORES_RE.search(text)
    if not m:
        return {}
    history: dict[str, list[float]] = {}
    for part in m.group(1).split("|"):
        part = part.strip()
        if "=" not in part:
            continue
        dim, scores_str = part.split("=", 1)
        try:
            history[dim.strip()] = [float(s) for s in scores_str.split(";") if s.strip()]
        except ValueError:
            continue
    return history


def _render_score_history(history: dict[str, list[float]]) -> str:
    """Render score history as compact metadata comment."""
    if not history:
        return ""
    parts = []
    for dim in sorted(history):
        scores = ";".join(f"{s:.2f}" for s in history[dim])
        parts.append(f"{dim}={scores}")
    return f"<!-- Scores: {'|'.join(parts)} -->"


def _parse_gate_counts(text: str) -> tuple[dict[str, int], dict[str, int]]:
    """Parse gate fail/total counts from ``<!-- GateCounts: GATE=fail/total|... -->``."""
    m = _GATES_META_RE.search(text)
    if not m:
        return {}, {}
    fail_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}
    for part in m.group(1).split("|"):
        part = part.strip()
        if "=" not in part:
            continue
        gate, counts_str = part.split("=", 1)
        try:
            if "/" in counts_str:
                fail_s, total_s = counts_str.split("/")
                fail_counts[gate.strip()] = int(fail_s)
                total_counts[gate.strip()] = int(total_s)
        except ValueError:
            continue
    return fail_counts, total_counts


def _render_gate_counts(fail_counts: dict[str, int], total_counts: dict[str, int]) -> str:
    """Render gate counts as compact metadata comment."""
    if not total_counts:
        return ""
    parts = []
    for gate in sorted(total_counts):
        fails = fail_counts.get(gate, 0)
        parts.append(f"{gate}={fails}/{total_counts[gate]}")
    return f"<!-- GateCounts: {'|'.join(parts)} -->"


# ---------------------------------------------------------------------------
# Skill file parsing
# ---------------------------------------------------------------------------

def _parse_skill_file(path: Path, department: str) -> SkillData:
    """Parse an existing skill file, or return empty SkillData."""
    data = SkillData(department=department)
    if not path.is_file():
        return data
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return data

    # Parse header metadata
    m = _HEADER_RE.search(text)
    if m:
        data.last_updated = m.group(1)
        data.builds_analyzed = int(m.group(2))

    # Parse score history and gate counts from metadata comments
    data.score_history = _parse_score_history(text)
    data.gate_fail_counts, data.gate_total_counts = _parse_gate_counts(text)

    # Parse lesson sections (for seen-counter tracking across builds)
    current_section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            current_section = stripped.lstrip("#").strip().lower()
            continue
        if not stripped.startswith("- "):
            continue
        lesson_text = stripped[2:].strip()
        seen_match = _SEEN_RE.search(lesson_text)
        seen = int(seen_match.group(1)) if seen_match else 1
        total = int(seen_match.group(2)) if seen_match else data.builds_analyzed or 1

        if "critical" in current_section or "audit finding" in current_section:
            data.critical.append(Lesson(text=lesson_text, severity="critical", seen=seen, total=total))
        elif "high" in current_section:
            data.high.append(Lesson(text=lesson_text, severity="high", seen=seen, total=total))
        elif "quality" in current_section or "weak" in current_section:
            data.quality_targets.append(lesson_text)
        elif "gate" in current_section:
            data.gate_history.append(lesson_text)
        elif "failure" in current_section or "top" in current_section or "rejection" in current_section:
            data.high.append(Lesson(text=lesson_text, severity="high", seen=seen, total=total))

    return data


# ---------------------------------------------------------------------------
# Tier classification and trend helpers
# ---------------------------------------------------------------------------

def _tier_for_score(score: float) -> str:
    """Classify a dimension score into a severity tier."""
    if score < _CRITICAL_THRESHOLD:
        return "critical"
    if score < _HIGH_THRESHOLD:
        return "high"
    if score < _MODERATE_THRESHOLD:
        return "moderate"
    return "on_track"


def _trend_text(dim: str, history: list[float]) -> str:
    """Generate trend description from score history."""
    if len(history) < 2:
        return ""
    prev, curr = history[-2], history[-1]
    if curr > prev + 0.05:
        return f"improved {prev:.2f} \u2192 {curr:.2f}"
    if curr < prev - 0.05:
        return f"DECLINING {prev:.2f} \u2192 {curr:.2f}"
    return f"stagnant at {curr:.2f}"


def _builds_passing(history: list[float], threshold: float = 0.50) -> str:
    """Count builds where score was at or above *threshold*."""
    if not history:
        return "0/0"
    passing = sum(1 for s in history if s >= threshold)
    return f"{passing}/{len(history)}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_skill_file(data: SkillData) -> str:
    """Render SkillData to markdown."""
    if data.department == "coding":
        return _render_coding_skills(data)
    return _render_review_skills(data)


def _render_coding_skills(data: SkillData) -> str:
    """Render coding department with tiered, actionable guidance."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        "# Coding Department Skills",
        "<!-- Auto-updated by agent-team. Do not edit manually. -->",
        f"<!-- Last updated: {now} | Builds analyzed: {data.builds_analyzed} -->",
    ]
    score_meta = _render_score_history(data.score_history)
    if score_meta:
        lines.append(score_meta)
    lines.append("")

    # Tier the dimensions
    tiers: dict[str, list[tuple[str, float]]] = {
        "critical": [], "high": [], "moderate": [], "on_track": [],
    }
    for dim, score in sorted(data.dimensions.items()):
        if dim == "overall":
            continue
        tiers[_tier_for_score(score)].append((dim, score))

    # === CRITICAL section ===
    if tiers["critical"]:
        lines.append("## Critical \u2014 Fix These First (score < 0.10)")
        lines.append("")
        for dim, score in tiers["critical"]:
            history = data.score_history.get(dim, [score])
            bp = _builds_passing(history, _CRITICAL_THRESHOLD)
            lines.append(f"### {dim} ({bp} builds passing)")
            if len(history) >= 2 and all(s < _CRITICAL_THRESHOLD for s in history):
                lines.append(
                    f"You have NEVER passed this dimension across {len(history)} builds."
                )
            elif len(history) >= 2:
                trend = _trend_text(dim, history)
                if trend:
                    lines.append(f"Trend: {trend}")
            guidance = _DIMENSION_GUIDANCE.get(dim, {})
            for i, step in enumerate(guidance.get("critical", []), 1):
                lines.append(f"{i}. {step}")
            instruction = guidance.get("instruction", "")
            if instruction:
                lines.append(instruction)
            gate_impact = guidance.get("gate_impact", "")
            if gate_impact:
                lines.append(gate_impact)
            lines.append("")

    # === HIGH PRIORITY section ===
    if tiers["high"]:
        lines.append("## High Priority \u2014 Needs Improvement (score 0.10-0.50)")
        lines.append("")
        for dim, score in tiers["high"]:
            history = data.score_history.get(dim, [score])
            trend = _trend_text(dim, history) if len(history) >= 2 else ""
            suffix = f" \u2014 {trend}" if trend else ""
            lines.append(f"### {dim} (avg {score:.2f}){suffix}")
            for step in _DIMENSION_GUIDANCE.get(dim, {}).get("high", []):
                lines.append(f"- {step}")
            lines.append("")

    # === MODERATE section ===
    if tiers["moderate"]:
        lines.append("## Moderate \u2014 Almost There (score 0.50-0.75)")
        lines.append("")
        for dim, score in tiers["moderate"]:
            lines.append(f"### {dim} (avg {score:.2f})")
            for step in _DIMENSION_GUIDANCE.get(dim, {}).get("moderate", []):
                lines.append(f"- {step}")
            lines.append("")

    # === Top Audit Findings (critical + high severity from actual audit) ===
    top_findings = data.critical[:5]
    remaining = 5 - len(top_findings)
    if remaining > 0:
        top_findings += data.high[:remaining]
    if top_findings:
        lines.append("## Top Audit Findings")
        for lesson in top_findings:
            lines.append(f"- {lesson.text}")
        lines.append("")

    return "\n".join(lines)


def _render_review_skills(data: SkillData) -> str:
    """Render review department with rejection rules, checklist, gate table."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        "# Review Department Skills",
        "<!-- Auto-updated by agent-team. Do not edit manually. -->",
        f"<!-- Last updated: {now} | Builds analyzed: {data.builds_analyzed} -->",
    ]
    score_meta = _render_score_history(data.score_history)
    if score_meta:
        lines.append(score_meta)
    gate_meta = _render_gate_counts(data.gate_fail_counts, data.gate_total_counts)
    if gate_meta:
        lines.append(gate_meta)
    lines.append("")

    # === Hard Rejection Rules ===
    reject_rules: list[str] = []
    for dim, score in sorted(data.dimensions.items()):
        if dim == "overall" or score >= _CRITICAL_THRESHOLD:
            continue
        history = data.score_history.get(dim, [score])
        guidance = _DIMENSION_GUIDANCE.get(dim, {})
        rule = guidance.get("review_rule", f"Score {score:.2f} \u2192 REJECT.")
        bp = _builds_passing(history, _CRITICAL_THRESHOLD)
        reject_rules.append(
            f"**{rule}** Score: {score:.2f} across {len(history)} builds ({bp} passing)."
        )

    # Also flag persistent HIGH-tier failures (2+ builds below HIGH threshold)
    for dim, score in sorted(data.dimensions.items()):
        if dim == "overall" or score < _CRITICAL_THRESHOLD or score >= _HIGH_THRESHOLD:
            continue
        history = data.score_history.get(dim, [score])
        if len(history) >= 2 and all(s < _HIGH_THRESHOLD for s in history):
            guidance = _DIMENSION_GUIDANCE.get(dim, {})
            rule = guidance.get("review_rule", f"Persistent failure \u2192 REJECT.")
            reject_rules.append(
                f"**{rule}** Score: {score:.2f}, failed {len(history)} consecutive builds."
            )

    if reject_rules:
        lines.append("## Hard Rejection Rules (BLOCK merge if violated)")
        for i, rule in enumerate(reject_rules, 1):
            lines.append(f"{i}. {rule}")
        lines.append("")

    # === Priority Review Checklist ===
    checklist_items: list[str] = []
    for dim, score in sorted(data.dimensions.items()):
        if dim == "overall" or score >= _MODERATE_THRESHOLD:
            continue
        guidance = _DIMENSION_GUIDANCE.get(dim, {})
        item = guidance.get("checklist", f"Verify {dim} implementation")
        checklist_items.append(f"- [ ] {item}")

    if checklist_items:
        lines.append("## Priority Review Checklist")
        lines.extend(checklist_items)
        lines.append("")

    # === Gate Analysis table (all gates, failed and passed) ===
    all_gates = sorted(set(list(data.gate_fail_counts.keys()) + list(data.gate_total_counts.keys())))
    if all_gates:
        weak_dims = [d for d, s in data.dimensions.items()
                     if d != "overall" and s < _MODERATE_THRESHOLD]

        lines.append("## Gate Analysis \u2014 Actions Required")
        lines.append("| Gate | Status | Action |")
        lines.append("|------|--------|--------|")
        for gate in all_gates:
            fails = data.gate_fail_counts.get(gate, 0)
            total = data.gate_total_counts.get(gate, 0)
            if fails > 0:
                status = f"FAIL ({fails}/{total})"
                action = _GATE_ACTIONS.get(gate, "Investigate and fix")
                if "{weak_dims}" in action:
                    action = action.replace(
                        "{weak_dims}", ", ".join(weak_dims) if weak_dims else "all dims"
                    )
            else:
                status = f"PASS ({total}/{total})"
                action = "Maintained"
            lines.append(f"| {gate} | {status} | {action} |")
        lines.append("")

    # === Trend ===
    if data.builds_analyzed >= 2 and data.score_history:
        lines.append(f"## Trend ({data.builds_analyzed} builds)")
        if "overall" in data.score_history:
            overall_hist = data.score_history["overall"]
            if len(overall_hist) >= 2:
                trend = _trend_text("overall", overall_hist)
                if trend:
                    lines.append(f"- Overall truth score: {trend}")
        for dim, score in sorted(data.dimensions.items()):
            if dim == "overall" or score >= _MODERATE_THRESHOLD:
                continue
            history = data.score_history.get(dim, [])
            if len(history) >= 2:
                trend = _trend_text(dim, history)
                if trend:
                    lines.append(f"- {dim}: {trend}")
        lines.append("")

    return "\n".join(lines)


def _write_skill_file(path: Path, data: SkillData) -> None:
    """Write skill data to file with token budget enforcement."""
    content = _render_skill_file(data)
    content = _enforce_token_budget(content, _DEFAULT_MAX_TOKENS)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Skill update logic
# ---------------------------------------------------------------------------

def _finding_to_lesson(finding: dict[str, Any], total_builds: int) -> Lesson:
    """Convert an audit finding to a Lesson."""
    title = finding.get("title", "") or finding.get("summary", "")
    remediation = finding.get("remediation", "")
    text = remediation if remediation else title
    # Truncate long remediation
    if len(text) > 120:
        text = text[:117] + "..."
    text += f" [seen: 1/{total_builds}]"
    category = finding.get("category", "")
    if not category:
        category = _infer_category(finding)
    return Lesson(
        text=text,
        severity=finding.get("severity", "medium"),
        seen=1,
        total=total_builds,
        category=category,
    )


def _update_coding_skills(
    data: SkillData,
    findings: list[dict[str, Any]],
    truth_scores: dict[str, float],
) -> SkillData:
    """Update coding department skills from build data."""
    data.builds_analyzed += 1

    # Store current dimension scores (excluding overall)
    data.dimensions = {k: v for k, v in truth_scores.items() if k != "overall"}

    # Append current scores to history
    for dim, score in truth_scores.items():
        if dim not in data.score_history:
            data.score_history[dim] = []
        data.score_history[dim].append(score)

    # Extract lessons from findings by severity (for recurring issue tracking)
    new_critical: list[Lesson] = []
    new_high: list[Lesson] = []
    for f in findings:
        sev = f.get("severity", "medium").lower()
        lesson = _finding_to_lesson(f, data.builds_analyzed)
        if sev == "critical":
            new_critical.append(lesson)
        elif sev == "high":
            new_high.append(lesson)

    data.critical = _merge_lessons(data.critical, new_critical, data.builds_analyzed)
    data.high = _merge_lessons(data.high, new_high, data.builds_analyzed)

    return data


def _update_review_skills(
    data: SkillData,
    findings: list[dict[str, Any]],
    truth_scores: dict[str, float],
    gate_entries: list[dict[str, str]],
) -> SkillData:
    """Update review department skills from build data."""
    data.builds_analyzed += 1

    # Store current dimension scores
    data.dimensions = {k: v for k, v in truth_scores.items() if k != "overall"}

    # Append current scores to history
    for dim, score in truth_scores.items():
        if dim not in data.score_history:
            data.score_history[dim] = []
        data.score_history[dim].append(score)

    # Deduplicate gate entries (keep LATEST result per gate from log)
    latest_gates: dict[str, dict[str, str]] = {}
    for entry in gate_entries:
        latest_gates[entry["gate"]] = entry

    # Update gate fail/total counts (incremental: metadata has previous builds)
    for gate, entry in latest_gates.items():
        if gate not in data.gate_total_counts:
            data.gate_total_counts[gate] = 0
            data.gate_fail_counts.setdefault(gate, 0)
        data.gate_total_counts[gate] += 1
        if entry["result"] == "FAIL":
            data.gate_fail_counts[gate] = data.gate_fail_counts.get(gate, 0) + 1
        data.gate_reasons[gate] = entry.get("reason", "")

    # Populate gate_history for backward compat
    data.gate_history = [
        f"{gate}: {entry['result']} -- {entry.get('reason', '')}"[:100]
        for gate, entry in latest_gates.items()
    ]

    # Extract lessons for recurring issue tracking
    category_counts: dict[str, int] = {}
    for f in findings:
        cat = f.get("category", "general")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total_findings = len(findings)
    new_lessons: list[Lesson] = []
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_findings * 100) if total_findings > 0 else 0
        text = (
            f"{cat}: {count} findings [{pct:.0f}%] "
            f"[seen: 1/{data.builds_analyzed}]"
        )
        new_lessons.append(Lesson(
            text=text, severity="high", seen=1,
            total=data.builds_analyzed, category=cat,
        ))

    data.high = _merge_lessons(data.high, new_lessons, data.builds_analyzed)

    return data


# ---------------------------------------------------------------------------
# Merge and deduplication
# ---------------------------------------------------------------------------

def _normalize_lesson_key(text: str) -> str:
    """Create a fuzzy key for deduplication (lowercase, strip seen counters)."""
    text = _SEEN_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text.lower())
    text = text.rstrip(".,;:")
    return text


def _merge_lessons(
    existing: list[Lesson],
    new_lessons: list[Lesson],
    total_builds: int,
) -> list[Lesson]:
    """Merge new lessons into existing, incrementing seen counters."""
    by_key: dict[str, Lesson] = {}
    for lesson in existing:
        key = _normalize_lesson_key(lesson.text)
        by_key[key] = lesson

    for new in new_lessons:
        new_key = _normalize_lesson_key(new.text)
        if new_key in by_key:
            old = by_key[new_key]
            old.seen += 1
            old.total = total_builds
            old.text = _SEEN_RE.sub("", old.text).strip()
            old.text += f" [seen: {old.seen}/{total_builds}]"
        else:
            new.total = total_builds
            by_key[new_key] = new

    # Update total for ALL lessons so staleness tracking works
    for lesson in by_key.values():
        if lesson.total < total_builds:
            lesson.total = total_builds
            lesson.text = _SEEN_RE.sub("", lesson.text).strip()
            lesson.text += f" [seen: {lesson.seen}/{total_builds}]"

    # Sort by seen count descending (most recurring first)
    result = sorted(by_key.values(), key=lambda l: l.seen, reverse=True)

    # Deprioritize stale lessons (not seen recently)
    fresh = [l for l in result if l.total - l.seen < _STALE_THRESHOLD]
    stale = [l for l in result if l.total - l.seen >= _STALE_THRESHOLD]
    return fresh + stale


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Estimate token count from text (word-based approximation)."""
    words = len(text.split())
    return int(words / _WORDS_PER_TOKEN)


def _enforce_token_budget(content: str, max_tokens: int) -> str:
    """Truncate content to fit within token budget.

    Truncation priority (removes from bottom up):
    1. Top Audit Findings / On Track (least critical)
    2. Trend (nice-to-have)
    3. Moderate / Gate Analysis (lower priority)
    4. High Priority / Priority Review Checklist
    5. Critical / Hard Rejection Rules are NEVER truncated
    """
    if _estimate_tokens(content) <= max_tokens:
        return content

    lines = content.splitlines()
    sections: list[tuple[str, int, int]] = []  # (name, start, end)
    current_section = ""
    section_start = 0

    for i, line in enumerate(lines):
        if line.strip().startswith("## "):
            if current_section:
                sections.append((current_section, section_start, i))
            current_section = line.strip()[3:].strip().lower()
            section_start = i
    if current_section:
        sections.append((current_section, section_start, len(lines)))

    # Truncation order: most expendable first
    truncation_order = [
        "top audit findings",
        "on track",
        "trend",
        "moderate",
        "gate analysis",
        "high priority",
        "priority review checklist",
        # Legacy section names
        "gate history",
        "weak quality dimensions",
        "quality targets",
        "top failure modes",
    ]

    for target in truncation_order:
        if _estimate_tokens("\n".join(lines)) <= max_tokens:
            break
        for name, start, end in sections[:]:
            if target in name:
                removed_size = end - start
                lines = lines[:start] + lines[end:]
                sections = [
                    (n, s - removed_size if s > start else s,
                     e - removed_size if e > start else e)
                    for n, s, e in sections if n != name
                ]
                break

    return "\n".join(lines)


def _count_lessons(data: SkillData) -> int:
    """Count total lessons in skill data."""
    return (
        len(data.critical) + len(data.high) + len(data.dimensions)
        + len(data.quality_targets) + len(data.gate_history)
    )
