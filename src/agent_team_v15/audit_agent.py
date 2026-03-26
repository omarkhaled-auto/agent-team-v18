"""Audit Agent — Compares build output against original PRD.

Produces structured findings that drive the coordinated builder's fix loop.
Three-tier inspection: static checks (grep), Claude-assisted behavioral
checks (Sonnet), and REQUIRES_HUMAN classification for runtime/external.

Typical usage::

    from pathlib import Path
    from agent_team_v15.audit_agent import run_audit

    report = run_audit(
        original_prd_path=Path("prd.md"),
        codebase_path=Path("./output"),
    )
    print(f"Score: {report.score:.1f}%, Findings: {len(report.findings)}")
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


def _get_anthropic_client() -> Any:
    """Create an Anthropic client using ANTHROPIC_API_KEY if available."""
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic()


def _call_claude_sdk(prompt: str, model: str = "claude-opus-4-6", max_tokens: int = 3000) -> str:
    """Call Claude via the claude_agent_sdk — uses claude login auth.

    Returns the response text. Raises RuntimeError on failure.
    """
    import asyncio
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import ResultMessage, AssistantMessage

    options = ClaudeAgentOptions(
        model=model,
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    async def _run() -> str:
        result_text = ""
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                # Extract text from content blocks
                for block in getattr(msg, "content", []):
                    if hasattr(block, "text"):
                        result_text = block.text
        return result_text

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, create new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _run()).result(timeout=120)
        else:
            result = asyncio.run(_run())
    except RuntimeError:
        result = asyncio.run(_run())

    if not result:
        raise RuntimeError("Claude SDK returned empty response")
    return result.strip()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Severity(Enum):
    """Finding severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ACCEPTABLE_DEVIATION = "acceptable_deviation"
    REQUIRES_HUMAN = "requires_human"


class FindingCategory(Enum):
    """What kind of issue the finding represents."""

    CODE_FIX = "code_fix"
    MISSING_FEATURE = "missing_feature"
    SECURITY = "security"
    REGRESSION = "regression"
    TEST_GAP = "test_gap"
    PERFORMANCE = "performance"
    UX = "ux"


class CheckType(Enum):
    """How the AC can be verified."""

    STATIC = "static"
    BEHAVIORAL = "behavioral"
    RUNTIME = "runtime"
    EXTERNAL = "external"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AcceptanceCriterion:
    """A single acceptance criterion extracted from the PRD."""

    id: str  # e.g., "AC-1"
    feature: str  # e.g., "F-001" or "unknown"
    text: str  # Full AC text
    check_type: CheckType = CheckType.BEHAVIORAL
    section_context: str = ""  # Surrounding PRD section for context


@dataclass
class CheckResult:
    """Result of checking a single AC."""

    ac_id: str
    verdict: str  # "PASS", "FAIL", "PARTIAL"
    evidence: str  # Supporting evidence
    file_path: str = ""
    line_number: int = 0
    code_snippet: str = ""


@dataclass
class Finding:
    """A single audit finding."""

    id: str  # e.g., "F001-AC10" or "SEC-001" or "CROSS-001"
    feature: str  # e.g., "F-001" or "SECURITY" or "CROSS-CUTTING"
    acceptance_criterion: str  # The AC text from the PRD
    severity: Severity
    category: FindingCategory
    title: str
    description: str
    prd_reference: str  # Exact PRD section/line reference
    current_behavior: str  # What the code does now
    expected_behavior: str  # What the PRD says it should do
    file_path: str = ""
    line_number: int = 0
    code_snippet: str = ""
    fix_suggestion: str = ""
    estimated_effort: str = "small"  # "trivial" | "small" | "medium" | "large"
    test_requirement: str = ""


@dataclass
class AuditReport:
    """Complete audit report for one run."""

    run_number: int
    timestamp: str
    original_prd_path: str
    codebase_path: str
    total_acs: int
    passed_acs: int
    failed_acs: int
    partial_acs: int
    skipped_acs: int  # REQUIRES_HUMAN — excluded from score
    score: float  # 0-100 percentage
    findings: list[Finding] = field(default_factory=list)
    previously_passing: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    audit_cost: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def actionable_count(self) -> int:
        return sum(
            1
            for f in self.findings
            if f.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM)
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        data = {
            "run_number": self.run_number,
            "timestamp": self.timestamp,
            "original_prd_path": self.original_prd_path,
            "codebase_path": self.codebase_path,
            "total_acs": self.total_acs,
            "passed_acs": self.passed_acs,
            "failed_acs": self.failed_acs,
            "partial_acs": self.partial_acs,
            "skipped_acs": self.skipped_acs,
            "score": self.score,
            "audit_cost": self.audit_cost,
            "previously_passing": self.previously_passing,
            "regressions": self.regressions,
            "findings": [_finding_to_dict(f) for f in self.findings],
        }
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditReport:
        """Deserialize from dict."""
        findings = [_finding_from_dict(f) for f in data.get("findings", [])]
        return cls(
            run_number=data["run_number"],
            timestamp=data["timestamp"],
            original_prd_path=data["original_prd_path"],
            codebase_path=data["codebase_path"],
            total_acs=data["total_acs"],
            passed_acs=data["passed_acs"],
            failed_acs=data["failed_acs"],
            partial_acs=data["partial_acs"],
            skipped_acs=data.get("skipped_acs", 0),
            score=data["score"],
            findings=findings,
            previously_passing=data.get("previously_passing", []),
            regressions=data.get("regressions", []),
            audit_cost=data.get("audit_cost", 0.0),
        )


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id,
        "feature": f.feature,
        "acceptance_criterion": f.acceptance_criterion,
        "severity": f.severity.value,
        "category": f.category.value,
        "title": f.title,
        "description": f.description,
        "prd_reference": f.prd_reference,
        "current_behavior": f.current_behavior,
        "expected_behavior": f.expected_behavior,
        "file_path": f.file_path,
        "line_number": f.line_number,
        "code_snippet": f.code_snippet,
        "fix_suggestion": f.fix_suggestion,
        "estimated_effort": f.estimated_effort,
        "test_requirement": f.test_requirement,
    }


def _finding_from_dict(d: dict[str, Any]) -> Finding:
    return Finding(
        id=d["id"],
        feature=d["feature"],
        acceptance_criterion=d.get("acceptance_criterion", ""),
        severity=Severity(d["severity"]),
        category=FindingCategory(d["category"]),
        title=d["title"],
        description=d["description"],
        prd_reference=d.get("prd_reference", ""),
        current_behavior=d.get("current_behavior", ""),
        expected_behavior=d.get("expected_behavior", ""),
        file_path=d.get("file_path", ""),
        line_number=d.get("line_number", 0),
        code_snippet=d.get("code_snippet", ""),
        fix_suggestion=d.get("fix_suggestion", ""),
        estimated_effort=d.get("estimated_effort", "small"),
        test_requirement=d.get("test_requirement", ""),
    )


# ---------------------------------------------------------------------------
# AC extraction patterns
# ---------------------------------------------------------------------------

# Feature heading patterns
_FEATURE_HEADING_RE = re.compile(
    r"^#{2,4}\s+(?:Feature\s+)?(?:F[-\s]?)(\d+)", re.MULTILINE | re.IGNORECASE
)

# AC extraction patterns (tried in order, first match wins per region)
_AC_PATTERNS: list[re.Pattern[str]] = [
    # Checkbox format: - [ ] AC-1: GIVEN...
    re.compile(
        r"-\s*\[[ xX]\]\s*AC[-\s]?(\d+)\s*:\s*(.+?)(?=\n-\s*\[|\n\n|\n#{1,4}\s|\Z)",
        re.DOTALL,
    ),
    # Bold label: **AC-1:** GIVEN...
    re.compile(
        r"\*\*AC[-\s]?(\d+):\*\*\s*(.+?)(?=\n\*\*AC|\n\n|\n#{1,4}\s|\Z)",
        re.DOTALL,
    ),
    # Plain text: AC-1: GIVEN...
    re.compile(
        r"(?:^|\n)AC[-\s]?(\d+)\s*:\s*(.+?)(?=\nAC[-\s]?\d+|\n\n|\n#{1,4}\s|\Z)",
        re.DOTALL,
    ),
    # Long form: Acceptance Criterion N:
    re.compile(
        r"Acceptance\s+Criter(?:ion|ia)\s+(\d+)\s*:\s*(.+?)(?=\nAcceptance|\n\n|\n#{1,4}\s|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
]

# Section heading patterns for PRDs that use module-based sections instead of Feature N
_SECTION_HEADING_RE = re.compile(
    r"^#{2,4}\s+(.+?)$", re.MULTILINE
)

# Numbered items under Business Rules / Success Criteria sections
_NUMBERED_ITEM_RE = re.compile(
    r"(?:^|\n)(\d{1,3})\.\s+(.+?)(?=\n\d{1,3}\.\s|\n\n|\n#{1,4}\s|\Z)",
    re.DOTALL,
)

# Keywords for check type categorization
_STATIC_KEYWORDS: dict[str, str] = {
    "httponly": "cookie_security",
    "bcrypt": "password_hashing",
    "argon2": "password_hashing",
    "jwt": "auth_token",
    "https": "transport_security",
    "cors": "cors_policy",
    "rate.limit": "rate_limiting",
    "rate limit": "rate_limiting",
    "csrf": "csrf_protection",
    "helmet": "security_headers",
    "uuid": "identifier_format",
    "encryption": "data_encryption",
    "encrypted": "data_encryption",
    "hashed": "password_hashing",
    "index": "db_index",
    "foreign key": "db_relationship",
    "unique constraint": "db_constraint",
    "not null": "db_constraint",
    "dockerfile": "containerization",
    "healthcheck": "health_endpoint",
}

_RUNTIME_KEYWORDS: list[str] = [
    "seconds",
    "milliseconds",
    "loads in",
    "response time",
    "concurrent",
    "throughput",
    "latency",
    "performance",
    "page load",
    "render time",
    "ttfb",
    "fps",
    "memory usage",
]

_EXTERNAL_KEYWORDS: list[str] = [
    "odoo",
    "stripe",
    "twilio",
    "sendgrid",
    "mailgun",
    "aws",
    "azure",
    "gcp",
    "firebase",
    "supabase",
    "third.party",
    "third party",
    "external api",
    "webhook",
    "real pdf",
    "actual email",
    "sms delivery",
    "payment gateway",
]

# Directories to skip during codebase scanning
_EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git",
    "dist", "build", "vendor", ".tox", ".mypy_cache", ".pytest_cache",
    "site-packages", ".egg-info", ".next", "env", ".angular",
    "coverage", ".nuxt", ".output", ".svelte-kit", ".agent-team",
})

_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs",
    ".java", ".kt", ".rb", ".prisma", ".sql", ".graphql",
    ".vue", ".svelte", ".html", ".css", ".scss",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_acceptance_criteria(prd_text: str) -> list[AcceptanceCriterion]:
    """Extract all acceptance criteria from PRD text.

    Associates each AC with its parent feature heading.
    Supports multiple PRD formats:
    - AC-N: ... (standard)
    - Numbered items under Business Rules / Success Criteria sections
    """
    if not prd_text or len(prd_text.strip()) < 50:
        return []

    # Build a map of line_offset → feature_id from headings
    feature_map: list[tuple[int, str]] = []
    for m in _FEATURE_HEADING_RE.finditer(prd_text):
        feature_map.append((m.start(), f"F-{int(m.group(1)):03d}"))

    # Extract ACs using all patterns (deduplicate by AC number)
    seen_ac_ids: set[str] = set()
    acs: list[AcceptanceCriterion] = []

    for pattern in _AC_PATTERNS:
        for m in pattern.finditer(prd_text):
            ac_num = m.group(1)
            ac_id = f"AC-{ac_num}"
            if ac_id in seen_ac_ids:
                continue
            seen_ac_ids.add(ac_id)

            ac_text = m.group(2).strip()
            # Clean up multi-line ACs
            ac_text = re.sub(r"\s+", " ", ac_text)

            # Find parent feature
            feature = "unknown"
            ac_offset = m.start()
            for offset, fid in reversed(feature_map):
                if offset < ac_offset:
                    feature = fid
                    break

            # Extract section context (200 chars before AC for context)
            ctx_start = max(0, ac_offset - 200)
            section_context = prd_text[ctx_start:ac_offset].strip()

            # Categorize check type
            check_type = _categorize_check_type(ac_text)

            acs.append(
                AcceptanceCriterion(
                    id=ac_id,
                    feature=feature,
                    text=ac_text,
                    check_type=check_type,
                    section_context=section_context,
                )
            )

    # Fallback: If no AC-N patterns found, extract from numbered items
    # under Business Rules and Success Criteria sections
    if not acs:
        acs = _extract_numbered_criteria(prd_text)

    # Sort by AC number
    def _ac_sort_key(a: AcceptanceCriterion) -> tuple[str, int]:
        m = re.search(r"AC-(\D*)(\d+)", a.id)
        prefix = m.group(1) if m else ""
        num = int(m.group(2)) if m else 0
        return (prefix, num)
    acs.sort(key=_ac_sort_key)
    return acs


def _extract_numbered_criteria(prd_text: str) -> list[AcceptanceCriterion]:
    """Fallback extraction for PRDs that use numbered Business Rules
    and Success Criteria instead of AC-N format."""
    acs: list[AcceptanceCriterion] = []
    seen_ids: set[str] = set()

    # Build section heading map for parent feature association
    section_map: list[tuple[int, str]] = []
    for m in _SECTION_HEADING_RE.finditer(prd_text):
        heading = m.group(1).strip()
        section_map.append((m.start(), heading))

    # Find Business Rules and Success Criteria sections
    br_match = re.search(
        r"^## Business Rules\s*\n",
        prd_text, re.MULTILINE
    )
    sc_match = re.search(
        r"^## Success Criteria\s*\n",
        prd_text, re.MULTILINE
    )

    # Extract numbered items from Business Rules section
    if br_match:
        # Find end of Business Rules (next ## heading or EOF)
        br_end_match = re.search(
            r"\n## (?!.*Rules)",
            prd_text[br_match.end():]
        )
        br_end = br_match.end() + br_end_match.start() if br_end_match else len(prd_text)
        br_text = prd_text[br_match.start():br_end]
        br_offset = br_match.start()

        for m in _NUMBERED_ITEM_RE.finditer(br_text):
            num = m.group(1)
            ac_id = f"AC-BR{num}"
            if ac_id in seen_ids:
                continue
            seen_ids.add(ac_id)

            ac_text = re.sub(r"\s+", " ", m.group(2).strip())

            # Find parent section heading
            abs_offset = br_offset + m.start()
            feature = "Business Rules"
            for offset, heading in reversed(section_map):
                if offset < abs_offset:
                    feature = heading
                    break

            ctx_start = max(0, abs_offset - 200)
            section_context = prd_text[ctx_start:abs_offset].strip()

            acs.append(
                AcceptanceCriterion(
                    id=ac_id,
                    feature=feature,
                    text=ac_text,
                    check_type=_categorize_check_type(ac_text),
                    section_context=section_context,
                )
            )

    # Extract numbered items from Success Criteria section
    if sc_match:
        sc_end_match = re.search(
            r"\n## ",
            prd_text[sc_match.end():]
        )
        sc_end = sc_match.end() + sc_end_match.start() if sc_end_match else len(prd_text)
        sc_text = prd_text[sc_match.start():sc_end]
        sc_offset = sc_match.start()

        for m in _NUMBERED_ITEM_RE.finditer(sc_text):
            num = m.group(1)
            ac_id = f"AC-SC{num}"
            if ac_id in seen_ids:
                continue
            seen_ids.add(ac_id)

            ac_text = re.sub(r"\s+", " ", m.group(2).strip())

            ctx_start = max(0, sc_offset + m.start() - 200)
            section_context = prd_text[ctx_start:sc_offset + m.start()].strip()

            acs.append(
                AcceptanceCriterion(
                    id=ac_id,
                    feature="Success Criteria",
                    text=ac_text,
                    check_type=_categorize_check_type(ac_text),
                    section_context=section_context,
                )
            )

    return acs


def run_audit(
    original_prd_path: Path,
    codebase_path: Path,
    previous_report: Optional[AuditReport] = None,
    run_number: int = 1,
    config: Optional[dict[str, Any]] = None,
) -> AuditReport:
    """Main entry point: audit the codebase against the original PRD.

    If *previous_report* is provided, also checks for regressions
    (ACs that passed before but fail now).
    """
    config = config or {}
    audit_model = config.get("audit_model", "claude-opus-4-6")
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    prd_text = original_prd_path.read_text(encoding="utf-8", errors="replace")

    # Step 1: Extract all acceptance criteria
    acs = extract_acceptance_criteria(prd_text)

    # Step 2: Discover codebase structure
    source_files = _discover_source_files(codebase_path)
    codebase_summary = _build_codebase_summary(codebase_path, source_files)

    # Step 3: Run checks per tier
    results: list[CheckResult] = []
    total_cost = 0.0

    static_acs = [ac for ac in acs if ac.check_type == CheckType.STATIC]
    behavioral_acs = [ac for ac in acs if ac.check_type == CheckType.BEHAVIORAL]
    skip_acs = [
        ac
        for ac in acs
        if ac.check_type in (CheckType.RUNTIME, CheckType.EXTERNAL)
    ]

    # Tier 1: Static checks (free)
    for ac in static_acs:
        result = _run_static_check(ac, codebase_path, source_files)
        results.append(result)

    # Tier 2: Behavioral checks (Claude Sonnet)
    for ac in behavioral_acs:
        relevant_code = _find_relevant_code(ac, codebase_path, source_files)
        result, cost = _run_behavioral_check(
            ac, relevant_code, prd_text, audit_model
        )
        results.append(result)
        total_cost += cost

    # Tier 3: Skip (classify as REQUIRES_HUMAN)
    for ac in skip_acs:
        results.append(
            CheckResult(
                ac_id=ac.id,
                verdict="SKIP",
                evidence=f"Requires {ac.check_type.value} verification (human needed)",
            )
        )

    # Step 4: Cross-cutting review
    preliminary_findings = _results_to_findings(results, acs)
    cross_findings, cross_cost = _cross_cutting_review(
        preliminary_findings, prd_text, codebase_summary, codebase_path,
        source_files, audit_model
    )
    total_cost += cross_cost

    # Step 5: Combine findings
    all_findings = preliminary_findings + cross_findings

    # Step 6: Check for regressions
    previously_passing: list[str] = []
    regressions: list[str] = []
    if previous_report:
        previously_passing = [
            r.ac_id for r in results if r.ac_id in _get_passing_ids(previous_report)
        ]
        # ACs that passed before but fail/partial now
        prev_pass = _get_passing_ids(previous_report)
        for r in results:
            if r.ac_id in prev_pass and r.verdict in ("FAIL", "PARTIAL"):
                regressions.append(r.ac_id)
                # Upgrade to REGRESSION category
                for f in all_findings:
                    if f.acceptance_criterion and r.ac_id in f.id:
                        f.category = FindingCategory.REGRESSION
                        if f.severity in (Severity.MEDIUM, Severity.LOW):
                            f.severity = Severity.HIGH

    # Step 7: Calculate scores
    passed = sum(1 for r in results if r.verdict == "PASS")
    failed = sum(1 for r in results if r.verdict == "FAIL")
    partial = sum(1 for r in results if r.verdict == "PARTIAL")
    skipped = sum(1 for r in results if r.verdict == "SKIP")
    denominator = len(results) - skipped
    score = ((passed + 0.5 * partial) / denominator * 100) if denominator > 0 else 0.0

    return AuditReport(
        run_number=run_number,
        timestamp=timestamp,
        original_prd_path=str(original_prd_path),
        codebase_path=str(codebase_path),
        total_acs=len(acs),
        passed_acs=passed,
        failed_acs=failed,
        partial_acs=partial,
        skipped_acs=skipped,
        score=round(score, 1),
        findings=all_findings,
        previously_passing=[
            r.ac_id
            for r in results
            if r.verdict == "PASS"
        ],
        regressions=regressions,
        audit_cost=round(total_cost, 4),
    )


# ---------------------------------------------------------------------------
# AC categorization
# ---------------------------------------------------------------------------


def _categorize_check_type(ac_text: str) -> CheckType:
    """Determine how an AC can be verified."""
    lower = ac_text.lower()

    # External system references → EXTERNAL
    for kw in _EXTERNAL_KEYWORDS:
        if kw in lower:
            return CheckType.EXTERNAL

    # Runtime performance → RUNTIME
    for kw in _RUNTIME_KEYWORDS:
        if kw in lower:
            return CheckType.RUNTIME

    # Static keywords → STATIC (can be checked via grep)
    for kw in _STATIC_KEYWORDS:
        if kw in lower:
            return CheckType.STATIC

    # Default: BEHAVIORAL (Claude evaluates)
    return CheckType.BEHAVIORAL


# ---------------------------------------------------------------------------
# Codebase discovery
# ---------------------------------------------------------------------------


def _discover_source_files(codebase_path: Path) -> list[Path]:
    """Find all source files in the codebase, excluding known non-source dirs."""
    files: list[Path] = []
    if not codebase_path.is_dir():
        return files

    for root, dirs, filenames in os.walk(codebase_path):
        # Prune excluded directories in-place
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
        root_path = Path(root)
        for fn in filenames:
            if any(fn.endswith(ext) for ext in _SOURCE_EXTENSIONS):
                files.append(root_path / fn)

    return sorted(files)


def _build_codebase_summary(
    codebase_path: Path, source_files: list[Path]
) -> str:
    """Build a brief text summary of the codebase structure."""
    if not source_files:
        return "No source files found."

    lines = [f"Project root: {codebase_path}", f"Total source files: {len(source_files)}", ""]

    # Group by top-level directory
    by_dir: dict[str, int] = {}
    for f in source_files:
        try:
            rel = f.relative_to(codebase_path)
            top = rel.parts[0] if len(rel.parts) > 1 else "."
            by_dir[top] = by_dir.get(top, 0) + 1
        except ValueError:
            pass

    lines.append("Directory structure:")
    for d, count in sorted(by_dir.items()):
        lines.append(f"  {d}/ — {count} files")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier 1: Static checks
# ---------------------------------------------------------------------------


def _run_static_check(
    ac: AcceptanceCriterion,
    codebase_path: Path,
    source_files: list[Path],
) -> CheckResult:
    """Check an AC via grep/file-existence patterns."""
    lower = ac.text.lower()

    # Determine which static keyword matched
    matched_category = ""
    for kw, cat in _STATIC_KEYWORDS.items():
        if kw in lower:
            matched_category = cat
            break

    if not matched_category:
        # Shouldn't happen (categorized as STATIC), fallback to grep
        return _grep_check(ac, codebase_path, source_files)

    # Dispatch by category
    if matched_category in ("cookie_security", "csrf_protection", "security_headers"):
        return _grep_check(ac, codebase_path, source_files, keywords=[matched_category.replace("_", "")])

    if matched_category == "password_hashing":
        return _grep_check(ac, codebase_path, source_files, keywords=["bcrypt", "argon2", "hash"])

    if matched_category == "auth_token":
        return _grep_check(ac, codebase_path, source_files, keywords=["jwt", "jsonwebtoken", "token"])

    if matched_category == "containerization":
        dockerfile = codebase_path / "Dockerfile"
        if dockerfile.exists():
            return CheckResult(ac_id=ac.id, verdict="PASS", evidence=f"Dockerfile exists at {dockerfile}")
        return CheckResult(ac_id=ac.id, verdict="FAIL", evidence="No Dockerfile found")

    if matched_category == "health_endpoint":
        return _grep_check(ac, codebase_path, source_files, keywords=["health", "healthcheck", "/health"])

    # Default: grep for the keyword
    return _grep_check(ac, codebase_path, source_files)


def _grep_check(
    ac: AcceptanceCriterion,
    codebase_path: Path,
    source_files: list[Path],
    keywords: Optional[list[str]] = None,
) -> CheckResult:
    """Search source files for keywords derived from the AC text."""
    if keywords is None:
        # Extract searchable terms from AC
        keywords = _extract_search_terms(ac.text)

    if not keywords:
        return CheckResult(
            ac_id=ac.id,
            verdict="PARTIAL",
            evidence="Could not extract searchable keywords from AC",
        )

    found_files: list[tuple[str, int, str]] = []  # (file, line, snippet)

    for src_file in source_files:
        try:
            content = src_file.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                lower_line = line.lower()
                if any(kw.lower() in lower_line for kw in keywords):
                    rel = str(src_file.relative_to(codebase_path)).replace("\\", "/")
                    found_files.append((rel, i, line.strip()[:120]))
                    break  # One match per file is enough
        except (OSError, UnicodeDecodeError):
            continue

    if found_files:
        first = found_files[0]
        return CheckResult(
            ac_id=ac.id,
            verdict="PASS",
            evidence=f"Found in {len(found_files)} file(s). First: {first[0]}:{first[1]}",
            file_path=first[0],
            line_number=first[1],
            code_snippet=first[2],
        )

    return CheckResult(
        ac_id=ac.id,
        verdict="FAIL",
        evidence=f"Keywords {keywords} not found in any source file",
    )


def _extract_search_terms(ac_text: str) -> list[str]:
    """Extract searchable keywords from AC text."""
    terms: list[str] = []

    # Quoted strings
    for m in re.finditer(r'"([^"]+)"', ac_text):
        terms.append(m.group(1))

    # Technical terms (camelCase, snake_case, PascalCase)
    for m in re.finditer(r"\b([a-z]+(?:[A-Z][a-z]+)+)\b", ac_text):
        terms.append(m.group(1))
    for m in re.finditer(r"\b([a-z]+_[a-z_]+)\b", ac_text):
        terms.append(m.group(1))
    for m in re.finditer(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b", ac_text):
        terms.append(m.group(1))

    # Static keyword matches
    lower = ac_text.lower()
    for kw in _STATIC_KEYWORDS:
        if kw in lower:
            terms.append(kw.replace(".", ""))

    return list(set(terms))[:10]  # Deduplicate and cap


# ---------------------------------------------------------------------------
# Tier 2: Behavioral checks (Claude-assisted)
# ---------------------------------------------------------------------------


def _find_relevant_code(
    ac: AcceptanceCriterion,
    codebase_path: Path,
    source_files: list[Path],
    max_lines: int = 25000,
) -> str:
    """Find code relevant to the AC for Claude evaluation."""
    keywords = _extract_behavioral_keywords(ac)
    if not keywords:
        return ""

    relevant_sections: list[str] = []
    total_lines = 0

    # Prioritize service/controller/guard files over seed/config/spec files
    def _file_priority(p: Path) -> int:
        name = p.name.lower()
        # Deprioritize test/seed/migration first (they match many keywords)
        if ".spec." in name or ".test." in name or "__tests__" in str(p).lower():
            return 20
        if "seed" in name: return 21
        if "migration" in name: return 22
        # Then prioritize by file type
        if ".service." in name: return 0
        if ".guard." in name: return 1
        if ".controller." in name: return 2
        if ".middleware." in name: return 3
        if ".gateway." in name: return 4
        if ".processor." in name: return 5
        if ".module." in name: return 6
        if "schema.prisma" in name: return 7
        return 10

    prioritized_files = sorted(source_files, key=_file_priority)

    # Score files by keyword match count — more matches = more relevant
    file_scores: list[tuple[int, int, Path]] = []  # (-score, priority, path)
    for src_file in prioritized_files:
        try:
            content = src_file.read_text(encoding="utf-8", errors="replace")
            lower_content = content.lower()
            match_count = sum(1 for kw in keywords if kw.lower() in lower_content)
            if match_count > 0:
                file_scores.append((-match_count, _file_priority(src_file), src_file))
        except (OSError, UnicodeDecodeError):
            continue
    file_scores.sort()

    for _, _, src_file in file_scores:
        if total_lines >= max_lines:
            break
        try:
            content = src_file.read_text(encoding="utf-8", errors="replace")

            lines = content.split("\n")
            matched_ranges: list[tuple[int, int]] = []

            for i, line in enumerate(lines):
                if any(kw.lower() in line.lower() for kw in keywords):
                    # Find enclosing block (approximate)
                    start = _find_block_start(lines, i)
                    end = _find_block_end(lines, i, max_block=75)
                    matched_ranges.append((start, end))

            # Merge overlapping ranges
            merged = _merge_ranges(matched_ranges)
            rel = str(src_file.relative_to(codebase_path)).replace("\\", "/")

            for start, end in merged:
                block_lines = end - start + 1
                if total_lines + block_lines > max_lines:
                    break
                section = "\n".join(lines[start : end + 1])
                relevant_sections.append(f"// File: {rel} (lines {start+1}-{end+1})\n{section}")
                total_lines += block_lines

        except (OSError, UnicodeDecodeError):
            continue

    return "\n\n---\n\n".join(relevant_sections) if relevant_sections else ""


def _extract_behavioral_keywords(ac: AcceptanceCriterion) -> list[str]:
    """Extract keywords from AC for finding relevant code."""
    keywords: list[str] = []
    text = ac.text
    _STOP_WORDS = {"GIVEN", "WHEN", "THEN", "AND", "The", "This", "That", "From",
                   "Only", "Time", "Date", "True", "False", "Each", "Some", "When"}

    # Dotted references (Entity.field) — highest signal
    for m in re.finditer(r"\b([A-Z]\w+)\.(\w+)", text):
        entity = m.group(1)
        keywords.append(entity)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", entity).lower()
        camel = entity[0].lower() + entity[1:]
        keywords.extend([snake, camel])

    # Entity-like words — PascalCase (WorkOrder) AND acronym-prefix (SLATimer)
    for m in re.finditer(r"\b([A-Z][A-Za-z]{3,})\b", text):
        word = m.group(1)
        if word in _STOP_WORDS:
            continue
        keywords.append(word)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", word).lower()
        camel = word[0].lower() + word[1:]
        keywords.extend([snake, camel])

    # Quoted strings
    for m in re.finditer(r'"([^"]+)"', text):
        keywords.append(m.group(1))

    # Action words → function name variants
    action_map = {
        "signup": ["signup", "register", "createUser", "create_user", "signUp"],
        "login": ["login", "signin", "authenticate", "signIn", "auth"],
        "logout": ["logout", "signout", "signOut"],
        "approve": ["approve", "approval", "approveInvoice"],
        "reject": ["reject", "rejection", "deny"],
        "match": ["match", "threeWayMatch", "three_way_match", "matching"],
        "transition": ["transition", "changeState", "setState", "updateStatus"],
        "create": ["create", "add", "insert", "post"],
        "update": ["update", "edit", "modify", "patch", "put"],
        "delete": ["delete", "remove", "destroy"],
        "send": ["send", "emit", "dispatch", "notify", "publish"],
        "validate": ["validate", "verify", "check", "assert"],
        "calculate": ["calculate", "compute", "calc"],
        "search": ["search", "find", "query", "filter", "list"],
    }
    lower = text.lower()
    for action, variants in action_map.items():
        if action in lower:
            keywords.extend(variants)

    return list(set(keywords))[:15]


def _find_block_start(lines: list[str], index: int) -> int:
    """Find the start of the enclosing function/class block."""
    # Walk backwards to find function/class definition or top-level indent
    for i in range(index, max(index - 41, -1), -1):
        line = lines[i]
        stripped = line.lstrip()
        if re.match(
            r"(export\s+)?(async\s+)?(function|class|const|let|var|def|interface|type)\s",
            stripped,
        ):
            return i
        if re.match(r"(app|router|server)\.(get|post|put|patch|delete|use)\s*\(", stripped):
            return i
        if re.match(r"@(Controller|Injectable|Module|Get|Post|Put|Delete|Patch)", stripped):
            return max(0, i - 1)
    return max(0, index - 20)


def _find_block_end(lines: list[str], index: int, max_block: int = 60) -> int:
    """Find the end of the enclosing code block."""
    # Simple brace/indent tracking
    depth = 0
    started = False
    for i in range(index, min(len(lines), index + max_block)):
        line = lines[i]
        depth += line.count("{") + line.count("(")
        depth -= line.count("}") + line.count(")")
        if depth > 0:
            started = True
        if started and depth <= 0:
            return i
    return min(len(lines) - 1, index + max_block)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping (start, end) ranges."""
    if not ranges:
        return []
    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 3:  # Allow 3-line gap for merging
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _run_behavioral_check(
    ac: AcceptanceCriterion,
    relevant_code: str,
    prd_text: str,
    model: str,
) -> tuple[CheckResult, float]:
    """Use Claude Sonnet to evaluate whether code satisfies the AC.

    Returns (CheckResult, api_cost).
    """
    if not relevant_code:
        return (
            CheckResult(
                ac_id=ac.id,
                verdict="FAIL",
                evidence="No relevant code found for this acceptance criterion",
            ),
            0.0,
        )

    prompt = f"""You are auditing code against a PRD specification. Be STRICT.

ACCEPTANCE CRITERION ({ac.id}, Feature {ac.feature}):
{ac.text}

RELEVANT CODE:
```
{relevant_code[:250000]}
```

Does the code satisfy the acceptance criterion?

Respond with EXACTLY one JSON object (no markdown fences, no extra text):
{{"verdict": "PASS" or "FAIL" or "PARTIAL", "evidence": "one concise sentence explaining your judgment", "file": "most relevant file path or empty string", "line": 0}}

Rules:
- PASS: Code fully implements the criterion with correct logic
- PARTIAL: Some aspects implemented but incomplete or has issues
- FAIL: Criterion not implemented or fundamentally wrong
- Default to FAIL if unsure — false negatives are safer than false positives"""

    # Try SDK first (requires ANTHROPIC_API_KEY), fall back to CLI
    try:
        import anthropic

        client = _get_anthropic_client()
        response = client.messages.create(
            model=model,
            max_tokens=3000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # Sonnet pricing: $3/M input, $15/M output
        cost = (input_tokens * 3 + output_tokens * 15) / 1_000_000

        # Parse JSON response
        result = _parse_claude_check_response(text, ac.id)
        return (result, cost)

    except (ImportError, EnvironmentError):
        # No SDK or no API key — fall back to Claude CLI
        pass
    except Exception:
        # API error — fall back to CLI
        pass

    # Fallback: Claude CLI (uses claude login auth)
    try:
        text = _call_claude_sdk(prompt, model="claude-opus-4-6")
        result = _parse_claude_check_response(text, ac.id)
        return (result, 0.0)  # cost unknown via CLI
    except Exception as e:
        return (
            CheckResult(
                ac_id=ac.id,
                verdict="PARTIAL",
                evidence=f"Both API and CLI failed: {type(e).__name__}: {str(e)[:100]}",
            ),
            0.0,
        )


def _parse_claude_check_response(text: str, ac_id: str) -> CheckResult:
    """Parse Claude's JSON response into a CheckResult."""
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        verdict = data.get("verdict", "FAIL").upper()
        if verdict not in ("PASS", "FAIL", "PARTIAL"):
            verdict = "FAIL"
        return CheckResult(
            ac_id=ac_id,
            verdict=verdict,
            evidence=data.get("evidence", "No evidence provided"),
            file_path=data.get("file", ""),
            line_number=data.get("line", 0),
        )
    except (json.JSONDecodeError, TypeError):
        # Try to extract verdict from plain text
        upper = text.upper()
        if "PASS" in upper:
            verdict = "PASS"
        elif "PARTIAL" in upper:
            verdict = "PARTIAL"
        else:
            verdict = "FAIL"
        return CheckResult(
            ac_id=ac_id,
            verdict=verdict,
            evidence=text[:200],
        )


# ---------------------------------------------------------------------------
# Cross-cutting review
# ---------------------------------------------------------------------------


def _cross_cutting_review(
    findings_so_far: list[Finding],
    prd_text: str,
    codebase_summary: str,
    codebase_path: Path,
    source_files: list[Path],
    model: str,
) -> tuple[list[Finding], float]:
    """One Claude call to catch cross-cutting issues individual checks miss."""
    # Identify key files (entry point, routes, schema, middleware)
    key_files = _identify_key_files(codebase_path, source_files)
    key_content = _read_key_files(key_files, max_total_lines=1500)

    findings_summary = _format_findings_summary(findings_so_far)

    # Truncate PRD to first 3000 chars (summary context)
    prd_summary = prd_text[:3000]

    prompt = f"""You are performing a cross-cutting audit of a codebase against a PRD.

INDIVIDUAL CHECK RESULTS (summary):
{findings_summary}

PRD SUMMARY (first 3000 chars):
{prd_summary}

PROJECT STRUCTURE:
{codebase_summary}

KEY FILES:
{key_content}

Look for CROSS-CUTTING issues that individual AC checks might miss:
1. Auth/middleware/guards defined but not actually wired into the app?
2. Database relationships incorrect (missing foreign keys, wrong cascades)?
3. Error handling inconsistent or missing on user-facing endpoints?
4. Event flows not connected (publisher exists but no subscriber)?
5. Files that are stubs/placeholders (empty handlers, TODO-only functions)?
6. Security concerns (exposed secrets, missing CORS, no rate limiting)?
7. Missing features that no AC specifically covers but the PRD implies?

Respond with a JSON array of findings. For each issue:
{{"id": "CROSS-NNN", "severity": "critical" or "high" or "medium", "category": "code_fix" or "missing_feature" or "security", "title": "short title", "description": "detailed description", "file_path": "path or empty", "fix_suggestion": "what to change", "estimated_effort": "trivial" or "small" or "medium" or "large"}}

If no cross-cutting issues found, respond with: []
Do NOT repeat findings already captured. Only report NEW issues."""

    # Try SDK first, fall back to CLI
    try:
        import anthropic

        client = _get_anthropic_client()
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        cost = (response.usage.input_tokens * 3 + response.usage.output_tokens * 15) / 1_000_000

        findings = _parse_cross_cutting_response(text)
        return (findings, cost)

    except (ImportError, EnvironmentError):
        pass
    except Exception:
        pass

    # Fallback: Claude CLI
    try:
        text = _call_claude_sdk(prompt, model="claude-opus-4-6")
        findings = _parse_cross_cutting_response(text)
        return (findings, 0.0)
    except Exception:
        return ([], 0.0)


def _identify_key_files(
    codebase_path: Path, source_files: list[Path]
) -> list[Path]:
    """Identify key structural files (entry point, routes, schema, etc.)."""
    key_names = {
        "app.ts", "app.js", "main.ts", "main.py", "index.ts", "index.js",
        "server.ts", "server.js", "server.py",
        "routes.ts", "routes.js", "urls.py", "router.ts",
        "schema.prisma", "models.py", "schema.ts", "schema.py",
        "middleware.ts", "middleware.js", "auth.ts", "auth.js",
        "package.json", "requirements.txt", "pyproject.toml",
    }
    key_dirs = {"routes", "middleware", "auth", "models", "schemas"}

    found: list[Path] = []
    for f in source_files:
        if f.name in key_names:
            found.append(f)
        elif f.parent.name in key_dirs and f.name.startswith("index"):
            found.append(f)

    # Also check root for config files
    for name in ("package.json", "requirements.txt", "pyproject.toml", "Dockerfile"):
        p = codebase_path / name
        if p.exists():
            found.append(p)

    return sorted(set(found))[:15]  # Cap at 15 files


def _read_key_files(files: list[Path], max_total_lines: int = 1500) -> str:
    """Read key files up to a total line limit."""
    sections: list[str] = []
    total = 0
    for f in files:
        if total >= max_total_lines:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            take = min(len(lines), max_total_lines - total, 150)  # 150 lines per file max
            section = "\n".join(lines[:take])
            sections.append(f"=== {f.name} ===\n{section}")
            total += take
        except OSError:
            continue
    return "\n\n".join(sections)


def _format_findings_summary(findings: list[Finding]) -> str:
    """Format findings into a brief text summary for Claude."""
    if not findings:
        return "No findings from individual checks."

    lines = [f"Total findings: {len(findings)}"]
    by_severity: dict[str, int] = {}
    for f in findings:
        s = f.severity.value
        by_severity[s] = by_severity.get(s, 0) + 1
    for s, count in sorted(by_severity.items()):
        lines.append(f"  {s}: {count}")

    lines.append("")
    lines.append("FAIL/PARTIAL items:")
    for f in findings[:20]:  # Cap at 20 for context size
        lines.append(f"  [{f.severity.value}] {f.id}: {f.title}")

    return "\n".join(lines)


def _parse_cross_cutting_response(text: str) -> list[Finding]:
    """Parse Claude's cross-cutting review response."""
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []

        findings: list[Finding] = []
        for item in data:
            findings.append(
                Finding(
                    id=item.get("id", f"CROSS-{len(findings)+1:03d}"),
                    feature="CROSS-CUTTING",
                    acceptance_criterion="",
                    severity=Severity(item.get("severity", "medium")),
                    category=FindingCategory(item.get("category", "code_fix")),
                    title=item.get("title", "Cross-cutting issue"),
                    description=item.get("description", ""),
                    prd_reference="Cross-cutting review",
                    current_behavior="",
                    expected_behavior="",
                    file_path=item.get("file_path", ""),
                    fix_suggestion=item.get("fix_suggestion", ""),
                    estimated_effort=item.get("estimated_effort", "small"),
                )
            )
        return findings
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Finding construction from check results
# ---------------------------------------------------------------------------


def _results_to_findings(
    results: list[CheckResult], acs: list[AcceptanceCriterion]
) -> list[Finding]:
    """Convert CheckResults to Finding objects for non-PASS results."""
    ac_map = {ac.id: ac for ac in acs}
    findings: list[Finding] = []

    for r in results:
        if r.verdict == "PASS":
            continue  # Only create findings for failures

        ac = ac_map.get(r.ac_id)
        if not ac:
            continue

        # Determine severity
        if r.verdict == "SKIP":
            severity = Severity.REQUIRES_HUMAN
        elif r.verdict == "FAIL":
            # Default to HIGH for complete failures
            severity = Severity.HIGH
        else:  # PARTIAL
            severity = Severity.MEDIUM

        # Determine category
        lower_text = ac.text.lower()
        if any(kw in lower_text for kw in ("security", "auth", "encrypt", "csrf", "xss")):
            category = FindingCategory.SECURITY
        elif r.verdict == "SKIP":
            category = FindingCategory.UX  # REQUIRES_HUMAN items tend to be UX/external
        elif "no relevant code found" in r.evidence.lower():
            category = FindingCategory.MISSING_FEATURE
        else:
            category = FindingCategory.CODE_FIX

        # Estimate effort
        if category == FindingCategory.MISSING_FEATURE:
            effort = "medium"
        elif r.verdict == "PARTIAL":
            effort = "small"
        else:
            effort = "small"

        findings.append(
            Finding(
                id=f"F-{ac.id}",
                feature=ac.feature,
                acceptance_criterion=ac.text,
                severity=severity,
                category=category,
                title=f"{ac.id}: {_truncate(ac.text, 60)}",
                description=r.evidence,
                prd_reference=f"{ac.feature} → {ac.id}",
                current_behavior=r.evidence,
                expected_behavior=ac.text,
                file_path=r.file_path,
                line_number=r.line_number,
                code_snippet=r.code_snippet,
                fix_suggestion=f"Implement {ac.id} as specified in {ac.feature}",
                estimated_effort=effort,
                test_requirement=f"Test that {ac.id} passes: {_truncate(ac.text, 100)}",
            )
        )

    return findings


def _get_passing_ids(report: AuditReport) -> set[str]:
    """Get set of AC IDs that passed in a report."""
    return set(report.previously_passing)


def _truncate(text: str, length: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."
