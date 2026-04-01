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

import glob as glob_module
import json
import os
import re
import subprocess
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


def _call_claude_sdk_agentic(
    prompt: str,
    working_directory: str,
    model: str = "claude-opus-4-6",
    max_turns: int = 15,
) -> str:
    """Call Claude via claude_agent_sdk with multi-turn tool use for INVESTIGATION.

    This function is used for Phase 1 (investigation) of the two-phase audit.
    Claude uses its built-in tools (Read, Grep, Glob) to explore the codebase
    and returns investigation notes (NOT a JSON verdict).

    The cwd parameter ensures tools operate in the correct directory.

    ``max_turns`` defaults to 15 (increased from 6) to allow deeper
    investigation of complex integration and quality issues.
    """
    import asyncio
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import ResultMessage, AssistantMessage

    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        cwd=working_directory,
    )

    async def _run() -> str:
        all_text_blocks: list[str] = []
        async for msg in query(prompt=prompt, options=options):
            # Capture text from both AssistantMessage and ResultMessage
            if isinstance(msg, (AssistantMessage, ResultMessage)):
                for block in getattr(msg, "content", []):
                    if hasattr(block, "text") and block.text.strip():
                        all_text_blocks.append(block.text.strip())

        # Return ALL text blocks joined — this is investigation notes, not JSON
        return "\n\n".join(all_text_blocks) if all_text_blocks else ""

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _run()).result(timeout=600)
        else:
            result = asyncio.run(_run())
    except RuntimeError:
        result = asyncio.run(_run())

    return (result or "").strip()


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


class AuditMode(Enum):
    """The audit mode determines what the audit prioritizes.

    - PRD_COMPLIANCE: (existing) checks codebase against PRD acceptance criteria.
      Useful for initial build verification.
    - IMPLEMENTATION_QUALITY: (new) runs deterministic validators as PRIMARY,
      then uses agentic Claude only for what deterministic tools can't catch
      (business logic correctness, state machine completeness). This is the
      mode to use for fix cycles, where the real bugs are integration issues,
      schema problems, auth flow divergence, and response shape mismatches —
      none of which appear in PRD acceptance criteria.
    - FULL: runs both modes and merges findings.
    """

    PRD_COMPLIANCE = "prd_compliance"
    IMPLEMENTATION_QUALITY = "implementation_quality"
    FULL = "full"


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
    fix_suggestion: str = ""  # Specific fix needed (from Claude)


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
# Audit tools for agentic code verification
# ---------------------------------------------------------------------------

AUDIT_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a source file from the codebase. Returns contents with line numbers. Use start_line/end_line to read specific sections of large files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from codebase root, e.g. 'apps/api/src/asset/asset.service.ts'"},
                "start_line": {"type": "integer", "description": "Optional start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "Optional end line"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a regex pattern across the codebase source files. Returns matching file paths with line numbers and snippets. Use this to find where specific functions, classes, or patterns are implemented.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for, e.g. 'scoreToRating|condition_rating'"},
                "file_glob": {"type": "string", "description": "Optional file glob filter, e.g. '*.service.ts' or '*.controller.ts'"},
                "max_results": {"type": "integer", "description": "Max results to return (default 30)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern in the codebase. Use to discover project structure and find relevant files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. 'apps/api/src/**/*.service.ts' or 'apps/api/src/maintenance/**'"},
            },
            "required": ["pattern"],
        },
    },
]


# Validator tools: expose deterministic scanners as tools Claude can invoke
# during agentic investigation. These let Claude run targeted scans on
# specific subsystems rather than relying solely on grep/read.
AUDIT_VALIDATOR_TOOLS = [
    {
        "name": "run_schema_check",
        "description": "Run the Prisma schema validator on the project. Returns a list of schema issues (missing cascades, bare FK fields, type mismatches, etc.). Use this when investigating database/schema-related acceptance criteria.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_quality_check",
        "description": "Run quality validators (ENUM/AUTH/SHAPE/SOFTDEL/INFRA checks) on the project. Returns cross-layer consistency issues. Use this when investigating integration, auth flow, or response shape issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "string",
                    "description": "Optional comma-separated list of check categories to run (e.g. 'enum_registry,auth_flow,response_shape,soft_delete,infrastructure'). Omit to run all.",
                },
            },
        },
    },
    {
        "name": "run_integration_check",
        "description": "Run the frontend-backend integration verifier. Compares frontend API calls against backend route definitions and finds mismatches in endpoints, HTTP methods, field names, and parameters. Use this when investigating API contract or wiring issues.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_spot_check",
        "description": "Run anti-pattern spot checks (FRONT-xxx, BACK-xxx, SLOP-xxx patterns). Finds common code quality issues like mock data, empty handlers, silent catches, etc. Use this when investigating code quality or anti-pattern issues.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _execute_validator_tool(
    name: str,
    tool_input: dict[str, Any],
    codebase_path: Path,
) -> str:
    """Execute a validator tool call and return the result as a formatted string."""
    try:
        if name == "run_schema_check":
            from agent_team_v15.schema_validator import run_schema_validation
            findings = run_schema_validation(codebase_path)
            if not findings:
                return "Schema validation: 0 issues found."
            lines = [f"Schema validation: {len(findings)} issues found.\n"]
            for f in findings[:50]:
                lines.append(f"  [{f.check}] {f.severity}: {f.message} ({f.model}.{f.field} line {f.line})")
                if f.suggestion:
                    lines.append(f"    Fix: {f.suggestion}")
            return "\n".join(lines)

        elif name == "run_quality_check":
            from agent_team_v15.quality_validators import run_quality_validators
            checks_str = tool_input.get("checks", "")
            checks = [c.strip() for c in checks_str.split(",") if c.strip()] if checks_str else None
            violations = run_quality_validators(codebase_path, checks=checks)
            if not violations:
                return "Quality validators: 0 issues found."
            lines = [f"Quality validators: {len(violations)} issues found.\n"]
            for v in violations[:50]:
                lines.append(f"  [{v.check}] {v.severity}: {v.message} at {v.file_path}:{v.line}")
            return "\n".join(lines)

        elif name == "run_integration_check":
            from agent_team_v15.integration_verifier import verify_integration
            report = verify_integration(codebase_path, run_mode="warn")
            if not hasattr(report, "mismatches") or not report.mismatches:
                matched = getattr(report, "matched", 0)
                return f"Integration verifier: 0 mismatches ({matched} matched endpoints)."
            lines = [f"Integration verifier: {len(report.mismatches)} mismatches found.\n"]
            for mm in report.mismatches[:50]:
                desc = getattr(mm, "description", str(mm))
                lines.append(f"  - {desc}")
            if hasattr(report, "missing_endpoints") and report.missing_endpoints:
                lines.append(f"\n  Missing endpoints: {', '.join(report.missing_endpoints[:20])}")
            return "\n".join(lines)

        elif name == "run_spot_check":
            from agent_team_v15.quality_checks import run_spot_checks
            violations = run_spot_checks(codebase_path)
            if not violations:
                return "Spot checks: 0 anti-patterns found."
            lines = [f"Spot checks: {len(violations)} anti-patterns found.\n"]
            for v in violations[:50]:
                lines.append(f"  [{v.check}] {v.severity}: {v.message} at {v.file_path}:{v.line}")
            return "\n".join(lines)

        return f"Unknown validator tool: {name}"
    except ImportError as e:
        return f"Validator not available: {e}"
    except Exception as e:
        return f"Validator error: {e}"


def _execute_audit_tool(
    name: str,
    tool_input: dict[str, Any],
    codebase_path: Path,
    file_cache: dict[str, str],
) -> str:
    """Execute an audit tool call and return the result string."""
    try:
        if name == "read_file":
            full_path = codebase_path / tool_input["path"]
            if not full_path.exists():
                return f"Error: File not found: {tool_input['path']}"
            if not full_path.is_file():
                return f"Error: Not a file: {tool_input['path']}"

            cache_key = str(full_path)
            if cache_key not in file_cache:
                try:
                    file_cache[cache_key] = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    return f"Error reading file: {e}"

            content = file_cache[cache_key]
            lines = content.split("\n")
            start = max(0, (tool_input.get("start_line", 1) or 1) - 1)
            end = min(len(lines), tool_input.get("end_line") or len(lines))

            # Cap at 500 lines per read to manage context
            if end - start > 500:
                end = start + 500
                truncated = True
            else:
                truncated = False

            numbered = [f"{i + start + 1:>5}| {line}" for i, line in enumerate(lines[start:end])]
            result = "\n".join(numbered)
            if truncated:
                result += f"\n... (truncated, file has {len(lines)} total lines. Use start_line/end_line to read more.)"
            return result

        elif name == "search_code":
            pattern = tool_input["pattern"]
            max_results = tool_input.get("max_results", 30)

            # Try ripgrep first, fall back to grep
            search_path = str(codebase_path)
            for cmd_name in ["rg", "grep"]:
                try:
                    if cmd_name == "rg":
                        cmd = ["rg", "-n", "--no-heading", "--max-count=3", pattern]
                        if tool_input.get("file_glob"):
                            cmd.extend(["--glob", tool_input["file_glob"]])
                        # Exclude node_modules, dist, .git
                        cmd.extend(["--glob", "!node_modules", "--glob", "!dist", "--glob", "!.git", "--glob", "!*.spec.*"])
                        cmd.append(search_path)
                    else:
                        cmd = ["grep", "-rn"]
                        if tool_input.get("file_glob"):
                            cmd.append(f"--include={tool_input['file_glob']}")
                        else:
                            cmd.extend(["--include=*.ts", "--include=*.prisma", "--include=*.json"])
                        cmd.extend([pattern, search_path])

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=str(codebase_path))
                    output = result.stdout.strip()
                    if output:
                        out_lines = output.split("\n")[:max_results]
                        # Make paths relative
                        rel_lines = []
                        for line in out_lines:
                            line = line.replace(str(codebase_path) + "/", "").replace(str(codebase_path) + "\\", "")
                            rel_lines.append(line[:200])  # cap line length
                        return "\n".join(rel_lines)
                except FileNotFoundError:
                    continue
                except subprocess.TimeoutExpired:
                    return "Search timed out. Try a more specific pattern."

            # Python fallback if no grep/rg
            return _python_search(pattern, codebase_path, file_cache, max_results)

        elif name == "list_files":
            pattern_str = str(codebase_path / tool_input["pattern"])
            matches = glob_module.glob(pattern_str, recursive=True)
            rel = [str(Path(m).relative_to(codebase_path)).replace("\\", "/") for m in matches
                   if not any(x in m for x in ["node_modules", "dist", ".git"])]
            return "\n".join(sorted(rel)[:80]) or "No files found matching pattern"

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error: {e}"


def _python_search(pattern: str, codebase_path: Path, file_cache: dict, max_results: int) -> str:
    """Fallback search using Python re module."""
    results: list[str] = []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = re.compile(re.escape(pattern), re.IGNORECASE)

    for ext in ("*.ts", "*.prisma"):
        for fpath in codebase_path.rglob(ext):
            if any(x in str(fpath) for x in ["node_modules", "dist", ".git"]):
                continue
            cache_key = str(fpath)
            if cache_key not in file_cache:
                try:
                    file_cache[cache_key] = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
            content = file_cache[cache_key]
            for i, line in enumerate(content.split("\n"), 1):
                if compiled.search(line):
                    rel = str(fpath.relative_to(codebase_path)).replace("\\", "/")
                    results.append(f"{rel}:{i}: {line.strip()[:150]}")
                    if len(results) >= max_results:
                        return "\n".join(results)
                    break  # one match per file
    return "\n".join(results) if results else "No matches found"


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


def run_deterministic_scan(codebase_path: Path) -> list[Finding]:
    """Run all deterministic validators and return unified Finding objects.

    Calls schema_validator, quality_validators, integration_verifier, and
    quality_checks (spot checks). Each scanner is wrapped in try/except for
    graceful degradation — if a scanner is unavailable or fails, it is
    skipped silently and the others still run.

    Returns a list of Finding objects with source="deterministic" and
    confidence=1.0, ready to be merged into the audit report.
    """
    import logging

    log = logging.getLogger(__name__)
    findings: list[Finding] = []
    det_id_counter = 0

    def _next_id(prefix: str) -> str:
        nonlocal det_id_counter
        det_id_counter += 1
        return f"DET-{prefix}-{det_id_counter:03d}"

    # --- 1. Schema Validator (SCHEMA-001..008) ---
    try:
        from agent_team_v15.schema_validator import run_schema_validation

        schema_findings = run_schema_validation(codebase_path)
        for sf in schema_findings:
            findings.append(Finding(
                id=_next_id("SCH"),
                feature="SCHEMA",
                acceptance_criterion=sf.check,
                severity=_map_det_severity(sf.severity),
                category=FindingCategory.CODE_FIX,
                title=f"[{sf.check}] {sf.message[:80]}",
                description=sf.message,
                prd_reference=sf.check,
                current_behavior=f"Schema issue in {sf.model}.{sf.field} at line {sf.line}",
                expected_behavior=sf.suggestion or "Fix schema issue",
                file_path=f"schema.prisma",
                line_number=sf.line,
                fix_suggestion=sf.suggestion,
                estimated_effort="small",
                test_requirement=f"Re-run schema validator, {sf.check} should not fire",
            ))
        log.info("Schema validator: %d findings", len(schema_findings))
    except ImportError:
        log.debug("schema_validator not available, skipping")
    except Exception as e:
        log.warning("Schema validator failed: %s", e)

    # --- 2. Quality Validators (ENUM/AUTH/SHAPE/SOFTDEL/INFRA) ---
    try:
        from agent_team_v15.quality_validators import run_quality_validators

        quality_violations = run_quality_validators(codebase_path)
        for qv in quality_violations:
            findings.append(Finding(
                id=_next_id("QV"),
                feature="QUALITY",
                acceptance_criterion=qv.check,
                severity=_map_det_severity(qv.severity),
                category=FindingCategory.CODE_FIX,
                title=f"[{qv.check}] {qv.message[:80]}",
                description=qv.message,
                prd_reference=qv.check,
                current_behavior=f"Issue at {qv.file_path}:{qv.line}",
                expected_behavior="Fix quality issue",
                file_path=qv.file_path,
                line_number=qv.line,
                fix_suggestion=qv.message,
                estimated_effort="small",
                test_requirement=f"Re-run quality validators, {qv.check} should not fire",
            ))
        log.info("Quality validators: %d findings", len(quality_violations))
    except ImportError:
        log.debug("quality_validators not available, skipping")
    except Exception as e:
        log.warning("Quality validators failed: %s", e)

    # --- 3. Integration Verifier (route mismatches + blocking) ---
    try:
        from agent_team_v15.integration_verifier import verify_integration

        report = verify_integration(codebase_path, run_mode="warn")
        # verify_integration returns IntegrationReport in warn mode
        if hasattr(report, "mismatches"):
            for mm in report.mismatches:
                sev = Severity.HIGH if getattr(mm, "severity", "high") in ("critical", "high") else Severity.MEDIUM
                findings.append(Finding(
                    id=_next_id("IV"),
                    feature="INTEGRATION",
                    acceptance_criterion="API_CONTRACT",
                    severity=sev,
                    category=FindingCategory.CODE_FIX,
                    title=f"Integration mismatch: {getattr(mm, 'description', str(mm))[:80]}",
                    description=getattr(mm, "description", str(mm)),
                    prd_reference="API_CONTRACT",
                    current_behavior=getattr(mm, "frontend_value", ""),
                    expected_behavior=getattr(mm, "backend_value", ""),
                    file_path=getattr(mm, "file_path", ""),
                    line_number=getattr(mm, "line", 0),
                    fix_suggestion=getattr(mm, "suggestion", ""),
                    estimated_effort="small",
                    test_requirement="Re-run integration verifier, mismatch should be resolved",
                ))
            log.info("Integration verifier: %d mismatches", len(report.mismatches))
    except ImportError:
        log.debug("integration_verifier not available, skipping")
    except Exception as e:
        log.warning("Integration verifier failed: %s", e)

    # --- 4. Quality Checks / Spot Checks (FRONT/BACK/SLOP) ---
    try:
        from agent_team_v15.quality_checks import run_spot_checks

        spot_violations = run_spot_checks(codebase_path)
        for sv in spot_violations:
            findings.append(Finding(
                id=_next_id("SC"),
                feature="SPOT_CHECK",
                acceptance_criterion=sv.check,
                severity=_map_det_severity(sv.severity),
                category=FindingCategory.CODE_FIX,
                title=f"[{sv.check}] {sv.message[:80]}",
                description=sv.message,
                prd_reference=sv.check,
                current_behavior=f"Issue at {sv.file_path}:{sv.line}",
                expected_behavior="Fix anti-pattern",
                file_path=sv.file_path,
                line_number=sv.line,
                fix_suggestion=sv.message,
                estimated_effort="small",
                test_requirement=f"Re-run spot checks, {sv.check} should not fire",
            ))
        log.info("Spot checks: %d findings", len(spot_violations))
    except ImportError:
        log.debug("quality_checks not available, skipping")
    except Exception as e:
        log.warning("Spot checks failed: %s", e)

    log.info("Total deterministic findings: %d", len(findings))
    return findings


def _map_det_severity(severity_str: str) -> Severity:
    """Map a deterministic scanner severity string to audit Severity enum."""
    s = severity_str.lower()
    if s == "critical":
        return Severity.CRITICAL
    elif s in ("high", "error"):
        return Severity.HIGH
    elif s in ("medium", "warning"):
        return Severity.MEDIUM
    elif s in ("low", "info"):
        return Severity.LOW
    return Severity.MEDIUM


def run_implementation_quality_audit(
    codebase_path: Path,
    previous_report: Optional[AuditReport] = None,
    run_number: int = 1,
    config: Optional[dict[str, Any]] = None,
) -> AuditReport:
    """Implementation Quality audit — deterministic-primary mode.

    This mode is designed for FIX CYCLES where the real bugs are
    implementation quality issues (schema integrity, route mismatches,
    auth flow divergence, response shape inconsistency, soft-delete gaps)
    rather than PRD compliance gaps.

    The flow:
    1. Run ALL deterministic validators as the PRIMARY detection engine
    2. Summarize deterministic findings for an agentic Claude session
    3. Claude investigates ONLY what deterministic tools can't catch:
       - Business logic correctness
       - State machine completeness
       - Complex cross-module interactions
       - Behavioral issues requiring code understanding
    4. Claude has access to validator tools it can re-run during investigation

    This is the complement to ``run_audit()`` (PRD compliance mode).
    Use ``run_full_audit()`` to run both modes and merge findings.
    """
    import logging

    log = logging.getLogger(__name__)
    config = config or {}
    audit_model = config.get("audit_model", "claude-opus-4-6")
    max_agentic_turns = config.get("max_agentic_turns", 15)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Step 1: Run ALL deterministic scanners
    det_findings = run_deterministic_scan(codebase_path)
    log.info(
        "Implementation quality audit: %d deterministic findings", len(det_findings)
    )

    # Step 2: Build a summary for the agentic session
    det_summary_lines = [
        f"DETERMINISTIC SCAN RESULTS: {len(det_findings)} issues found.\n",
    ]
    by_feature: dict[str, list[Finding]] = {}
    for f in det_findings:
        by_feature.setdefault(f.feature, []).append(f)
    for feature, group in sorted(by_feature.items()):
        det_summary_lines.append(f"\n--- {feature} ({len(group)} findings) ---")
        for f in group[:15]:
            det_summary_lines.append(
                f"  [{f.severity.value.upper()}] {f.title}"
            )
            if f.file_path:
                det_summary_lines.append(f"    File: {f.file_path}:{f.line_number}")
            if f.fix_suggestion:
                det_summary_lines.append(f"    Fix: {f.fix_suggestion[:120]}")

    det_summary = "\n".join(det_summary_lines)

    # Step 3: Agentic investigation of issues deterministic tools can't catch
    agentic_findings: list[Finding] = []
    skip_agentic = config.get("skip_agentic", False)
    source_files = _discover_source_files(codebase_path)

    # Skip agentic phase if: explicitly disabled, or no source files to investigate
    if skip_agentic or not source_files:
        log.info(
            "Skipping agentic investigation (skip_agentic=%s, source_files=%d)",
            skip_agentic, len(source_files),
        )
    else:
        try:
            codebase_summary = _build_codebase_summary(codebase_path, source_files)

            investigation_prompt = (
                "You are performing an IMPLEMENTATION QUALITY audit on a codebase.\n\n"
                "The following deterministic scanners have already run and found these issues:\n"
                f"{det_summary[:12000]}\n\n"
                f"PROJECT STRUCTURE:\n{codebase_summary[:3000]}\n\n"
                "Your job is to investigate issues that deterministic scanners CANNOT catch:\n"
                "1. Business logic correctness — are handlers doing the right thing?\n"
                "2. State machine completeness — are all transitions handled?\n"
                "3. Cross-module interactions — do services call each other correctly?\n"
                "4. Error handling adequacy — do error paths provide proper feedback?\n"
                "5. Data flow integrity — does data flow correctly through the stack?\n"
                "6. Auth/guard coverage — are all sensitive routes protected?\n\n"
                "You have access to Read, Grep, Glob tools for codebase exploration.\n"
                "You can also call run_schema_check, run_quality_check, run_integration_check, "
                "and run_spot_check to re-run specific validators on the codebase.\n\n"
                "FOCUS on finding NEW issues that the deterministic results above MISSED.\n"
                "Do NOT repeat findings already listed above.\n\n"
                "When done, summarize each new issue found with:\n"
                "- Severity (critical/high/medium/low)\n"
                "- Category (code_fix/missing_feature/security/regression)\n"
                "- Title, description, file path, and fix suggestion\n"
            )

            investigation_notes = _call_claude_sdk_agentic(
                investigation_prompt,
                str(codebase_path),
                model=audit_model,
                max_turns=max_agentic_turns,
            )

            # Parse agentic findings from investigation notes
            if investigation_notes and len(investigation_notes.strip()) > 50:
                agentic_findings = _parse_agentic_quality_findings(investigation_notes)
                log.info(
                    "Agentic investigation: %d additional findings",
                    len(agentic_findings),
                )

        except Exception as e:
            log.warning("Agentic quality investigation failed: %s", e)

    # Step 4: Combine all findings
    all_findings = det_findings + agentic_findings

    # Step 5: Check for regressions
    regressions: list[str] = []
    if previous_report:
        prev_ids = {f.id for f in previous_report.findings if f.id.startswith("DET-")}
        for f in det_findings:
            if f.id in prev_ids:
                # Same deterministic finding persists — not fixed
                pass
            # New findings on previously-passing requirement areas are regressions
        prev_pass_features = set()
        for f in previous_report.findings:
            if f.severity == Severity.LOW or f.severity == Severity.ACCEPTABLE_DEVIATION:
                prev_pass_features.add(f.feature)
        for f in all_findings:
            if f.feature in prev_pass_features and f.severity in (Severity.CRITICAL, Severity.HIGH):
                regressions.append(f.id)
                f.category = FindingCategory.REGRESSION

    # Step 6: Calculate scores
    passed_count = 0  # No ACs in this mode, score is based on finding density
    total_items = max(len(all_findings), 1)
    critical = sum(1 for f in all_findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in all_findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in all_findings if f.severity == Severity.MEDIUM)

    # Score: penalize by severity — 100 minus weighted deductions
    deduction = critical * 15 + high * 5 + medium * 2
    score = max(0.0, min(100.0, 100.0 - deduction))

    return AuditReport(
        run_number=run_number,
        timestamp=timestamp,
        original_prd_path="",
        codebase_path=str(codebase_path),
        total_acs=len(all_findings),
        passed_acs=0,
        failed_acs=len(all_findings),
        partial_acs=0,
        skipped_acs=0,
        score=round(score, 1),
        findings=all_findings,
        previously_passing=[],
        regressions=regressions,
        audit_cost=0.0,
    )


def _parse_agentic_quality_findings(notes: str) -> list[Finding]:
    """Parse investigation notes from agentic quality audit into Findings.

    Attempts JSON extraction first, then falls back to structured text parsing.
    """
    findings: list[Finding] = []

    # Try JSON array extraction
    json_match = re.search(r'\[[\s\S]*\]', notes)
    if json_match:
        try:
            items = json.loads(json_match.group(0))
            if isinstance(items, list):
                for i, item in enumerate(items):
                    if isinstance(item, dict) and "title" in item:
                        sev_str = str(item.get("severity", "medium")).lower()
                        cat_str = str(item.get("category", "code_fix")).lower()
                        findings.append(Finding(
                            id=f"IQ-AGT-{i + 1:03d}",
                            feature="QUALITY_INVESTIGATION",
                            acceptance_criterion="",
                            severity=_map_det_severity(sev_str),
                            category=FindingCategory(cat_str) if cat_str in [e.value for e in FindingCategory] else FindingCategory.CODE_FIX,
                            title=item.get("title", "Agentic finding"),
                            description=item.get("description", ""),
                            prd_reference="Implementation quality audit",
                            current_behavior=item.get("current_behavior", ""),
                            expected_behavior=item.get("expected_behavior", ""),
                            file_path=item.get("file_path", ""),
                            line_number=item.get("line_number", 0),
                            fix_suggestion=item.get("fix_suggestion", item.get("fix", "")),
                            estimated_effort=item.get("estimated_effort", "small"),
                        ))
                if findings:
                    return findings
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Fallback: extract structured findings from text
    # Look for patterns like: [HIGH] Title... or **HIGH**: Title...
    finding_pattern = re.compile(
        r'(?:\[|(?:\*\*))?(CRITICAL|HIGH|MEDIUM|LOW)(?:\]|(?:\*\*)?)\s*[:\-]?\s*(.+?)(?:\n|$)',
        re.IGNORECASE,
    )
    for i, m in enumerate(finding_pattern.finditer(notes)):
        sev_str = m.group(1).lower()
        title = m.group(2).strip()[:120]
        if len(title) < 10:
            continue
        findings.append(Finding(
            id=f"IQ-AGT-{i + 1:03d}",
            feature="QUALITY_INVESTIGATION",
            acceptance_criterion="",
            severity=_map_det_severity(sev_str),
            category=FindingCategory.CODE_FIX,
            title=title,
            description=title,
            prd_reference="Implementation quality audit",
            current_behavior="",
            expected_behavior="",
            fix_suggestion="",
            estimated_effort="small",
        ))

    return findings[:30]  # Cap to avoid noise


def run_full_audit(
    original_prd_path: Path,
    codebase_path: Path,
    previous_report: Optional[AuditReport] = None,
    run_number: int = 1,
    config: Optional[dict[str, Any]] = None,
) -> AuditReport:
    """Run both PRD compliance AND implementation quality audits, merge findings.

    This is the recommended mode for comprehensive auditing. It combines:
    1. PRD Compliance (``run_audit``) — does the build satisfy the PRD?
    2. Implementation Quality (``run_implementation_quality_audit``) — does
       the build have integration bugs, schema issues, etc.?

    Findings are deduplicated by file:line, with deterministic findings
    taking priority over LLM findings for the same issue.
    """
    config = config or {}
    mode = AuditMode(config.get("audit_mode", AuditMode.FULL.value))

    if mode == AuditMode.PRD_COMPLIANCE:
        return run_audit(original_prd_path, codebase_path, previous_report, run_number, config)

    if mode == AuditMode.IMPLEMENTATION_QUALITY:
        return run_implementation_quality_audit(codebase_path, previous_report, run_number, config)

    # FULL mode: run both
    prd_report = run_audit(original_prd_path, codebase_path, previous_report, run_number, config)
    iq_report = run_implementation_quality_audit(codebase_path, previous_report, run_number, config)

    # Merge findings: deterministic first, then PRD, deduplicating by file:line
    seen_file_lines: set[tuple[str, int]] = set()
    merged_findings: list[Finding] = []

    # IQ findings first (deterministic have higher confidence)
    for f in iq_report.findings:
        key = (f.file_path, f.line_number) if f.file_path and f.line_number else (f.id, 0)
        if key not in seen_file_lines:
            seen_file_lines.add(key)
            merged_findings.append(f)

    # Then PRD findings
    for f in prd_report.findings:
        key = (f.file_path, f.line_number) if f.file_path and f.line_number else (f.id, 0)
        if key not in seen_file_lines:
            seen_file_lines.add(key)
            merged_findings.append(f)

    # Recalculate score using the merged findings
    critical = sum(1 for f in merged_findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in merged_findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in merged_findings if f.severity == Severity.MEDIUM)

    # Blend scores: weight IQ score higher for fix cycles
    iq_weight = config.get("iq_weight", 0.6)
    prd_weight = 1.0 - iq_weight
    blended_score = prd_report.score * prd_weight + iq_report.score * iq_weight

    return AuditReport(
        run_number=run_number,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        original_prd_path=str(original_prd_path),
        codebase_path=str(codebase_path),
        total_acs=prd_report.total_acs,
        passed_acs=prd_report.passed_acs,
        failed_acs=prd_report.failed_acs + len(iq_report.findings),
        partial_acs=prd_report.partial_acs,
        skipped_acs=prd_report.skipped_acs,
        score=round(blended_score, 1),
        findings=merged_findings,
        previously_passing=prd_report.previously_passing,
        regressions=list(set(prd_report.regressions + iq_report.regressions)),
        audit_cost=prd_report.audit_cost + iq_report.audit_cost,
    )


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

    When ``config.get("deterministic_first")`` is True (default), runs
    deterministic scanners before the LLM-based audit. Deterministic
    findings are merged into the final report with confidence=1.0.
    """
    config = config or {}
    audit_model = config.get("audit_model", "claude-opus-4-6")
    deterministic_first = config.get("deterministic_first", True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    prd_text = original_prd_path.read_text(encoding="utf-8", errors="replace")

    # Step 0: Deterministic scan phase (before LLM)
    deterministic_findings: list[Finding] = []
    if deterministic_first:
        deterministic_findings = run_deterministic_scan(codebase_path)

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

    # Tier 2: Behavioral checks (agentic with tool-use)
    file_cache: dict[str, str] = {}
    for ac in behavioral_acs:
        # Pre-fetch hint code (optional, gives Claude a head start)
        hint_code = _find_relevant_code(ac, codebase_path, source_files)
        result, cost = _run_agentic_check(
            ac, codebase_path, prd_text, audit_model, file_cache, hint_code
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

    # Step 5: Combine findings (deterministic first, then LLM)
    all_findings = deterministic_findings + preliminary_findings + cross_findings

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
{{"verdict": "PASS" or "FAIL" or "PARTIAL", "evidence": "specific explanation of what passes/fails and why", "file": "most relevant file path or empty string", "line": 0, "fix": "if not PASS, describe exactly what code change is needed to satisfy the criterion"}}

Rules:
- PASS: Code fully implements the criterion with correct logic
- PARTIAL: Some aspects implemented but incomplete or has issues — explain EXACTLY what is missing
- FAIL: Criterion not implemented or fundamentally wrong
- For PARTIAL/FAIL, the "fix" field must describe the specific code change needed (which function, what logic to add/change)
- Reference specific file paths and line numbers when possible"""

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


def _run_agentic_check(
    ac: AcceptanceCriterion,
    codebase_path: Path,
    prd_text: str,
    model: str,
    file_cache: dict[str, str],
    hint_code: str = "",
    max_rounds: int = 10,
) -> tuple[CheckResult, float]:
    """Two-phase agentic audit: INVESTIGATE with tools, then VERDICT without tools.

    Phase 1 (Investigation): Claude uses built-in tools (Read, Grep, Glob) to
    explore the codebase and find the relevant implementation. Returns free-form
    investigation notes — no JSON required.

    Phase 2 (Verdict): Claude receives the investigation notes and renders a
    structured JSON verdict. Single-turn, no tools, guaranteed text response.

    This separation eliminates JSON parsing failures that occur when Claude
    mixes tool-use thinking with structured output.
    """
    # --- Phase 1: INVESTIGATE with tools ---
    hint_section = ""
    if hint_code:
        hint_section = (
            f"\n\nHINT — keyword search found possibly relevant code:\n"
            f"```\n{hint_code[:8000]}\n```\n"
            f"Use your tools to verify and explore further.\n"
        )

    investigation_prompt = (
        f"You are auditing a NestJS/TypeScript codebase. Investigate this acceptance criterion:\n\n"
        f"CRITERION ({ac.id}, Feature: {ac.feature}):\n{ac.text}\n"
        f"{hint_section}\n"
        f"INSTRUCTIONS:\n"
        f"- Use Grep to search for relevant class names, method names, constants, and AC-ID comments (e.g. '{ac.id}')\n"
        f"- Use Read to examine the actual implementation code with line numbers\n"
        f"- Key source directory: apps/api/src/\n"
        f"- Service files (*.service.ts) = business logic, Controllers (*.controller.ts) = API endpoints\n"
        f"- Guards (*.guard.ts) = auth, Processors (*.processor.ts) = background jobs\n"
        f"- Schema: apps/api/prisma/schema.prisma\n"
        f"- Try multiple search strategies before concluding code doesn't exist\n\n"
        f"When done investigating, summarize your findings:\n"
        f"1. Which files contain the implementation (with line numbers)\n"
        f"2. What the code actually does\n"
        f"3. Any gaps, issues, or deviations from the criterion\n"
        f"4. Whether the criterion appears fully, partially, or not implemented"
    )

    investigation_notes = ""
    try:
        investigation_notes = _call_claude_sdk_agentic(
            investigation_prompt, str(codebase_path), model=model, max_turns=6
        )
    except Exception as e:
        investigation_notes = f"Investigation failed: {e}"

    # Use hint_code as fallback if investigation returned nothing useful
    if not investigation_notes or len(investigation_notes.strip()) < 30:
        if hint_code:
            investigation_notes = f"Investigation via tools failed. Keyword search found:\n{hint_code[:10000]}"
        else:
            investigation_notes = "No relevant code found during investigation."

    # Cap investigation notes to avoid context overflow in Phase 2
    if len(investigation_notes) > 15000:
        investigation_notes = investigation_notes[:15000] + "\n... (truncated)"

    # --- Phase 2: VERDICT without tools (guaranteed clean response) ---
    verdict_prompt = (
        f"You investigated acceptance criterion {ac.id} and found the following.\n\n"
        f"CRITERION ({ac.id}):\n{ac.text}\n\n"
        f"INVESTIGATION FINDINGS:\n{investigation_notes}\n\n"
        f"Based on these findings, render your verdict as EXACTLY one JSON object "
        f"(no markdown fences, no explanation before or after — ONLY the JSON):\n"
        f'{{"verdict": "PASS" or "FAIL" or "PARTIAL", '
        f'"evidence": "specific explanation referencing file paths and line numbers", '
        f'"file": "most relevant file path or empty string", '
        f'"line": 0, '
        f'"fix": "if not PASS, describe exactly what code change is needed"}}\n\n'
        f"Verdict rules:\n"
        f"- PASS: Code fully implements the criterion with correct logic. Minor style issues are acceptable.\n"
        f"- PARTIAL: Core functionality is implemented but has gaps — e.g. missing edge case handling, "
        f"incomplete coverage across all modules, or minor deviations from spec. Explain EXACTLY what is missing.\n"
        f"- FAIL: Criterion is not implemented at all, or the implementation is fundamentally wrong.\n"
        f"- When in doubt between PARTIAL and FAIL, prefer PARTIAL if the core logic exists."
    )

    try:
        verdict_text = _call_claude_sdk(verdict_prompt, model=model)
        result = _parse_claude_check_response(verdict_text, ac.id)

        # Enrich evidence with investigation notes if parsed evidence is sparse
        if len(result.evidence) < 80 and len(investigation_notes) > 80:
            result = CheckResult(
                ac_id=result.ac_id,
                verdict=result.verdict,
                evidence=investigation_notes[:500],
                file_path=result.file_path,
                line_number=result.line_number,
                code_snippet=result.code_snippet,
                fix_suggestion=result.fix_suggestion,
            )

        return (result, 0.0)

    except Exception as e:
        # Phase 2 failed — try to extract verdict from investigation notes
        if "pass" in investigation_notes.lower() and "fail" not in investigation_notes.lower():
            verdict = "PASS"
        elif "partial" in investigation_notes.lower():
            verdict = "PARTIAL"
        elif "not implemented" in investigation_notes.lower() or "no relevant code" in investigation_notes.lower():
            verdict = "FAIL"
        else:
            verdict = "PARTIAL"

        return (
            CheckResult(
                ac_id=ac.id,
                verdict=verdict,
                evidence=investigation_notes[:500] if investigation_notes else f"Verdict phase failed: {e}",
            ),
            0.0,
        )


def _parse_claude_check_response(text: str, ac_id: str) -> CheckResult:
    """Parse Claude's JSON response into a CheckResult."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```", "", text)

    # First try: parse the entire text as JSON
    try:
        data = json.loads(text.strip())
        return _build_check_result(data, ac_id)
    except (json.JSONDecodeError, TypeError):
        pass

    # Second try: extract JSON object containing "verdict" from within text
    # This handles cases where Claude includes thinking text before/after the JSON
    json_patterns = re.findall(r'\{[^{}]*"verdict"[^{}]*\}', text, re.DOTALL)
    for json_str in reversed(json_patterns):  # prefer last match (final verdict)
        try:
            data = json.loads(json_str)
            return _build_check_result(data, ac_id)
        except (json.JSONDecodeError, TypeError):
            continue

    # Third try: find any JSON object with nested content (for multi-line JSON)
    brace_depth = 0
    json_start = -1
    last_json = None
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                json_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and json_start >= 0:
                candidate = text[json_start:i+1]
                if '"verdict"' in candidate:
                    try:
                        data = json.loads(candidate)
                        last_json = data
                    except (json.JSONDecodeError, TypeError):
                        pass
                json_start = -1
    if last_json:
        return _build_check_result(last_json, ac_id)

    # Fallback: extract verdict from plain text
    upper = text.upper()
    if "PASS" in upper and "FAIL" not in upper:
        verdict = "PASS"
    elif "PARTIAL" in upper:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return CheckResult(
        ac_id=ac_id,
        verdict=verdict,
        evidence=text[:500],
    )


def _build_check_result(data: dict, ac_id: str) -> CheckResult:
    """Build a CheckResult from parsed JSON data."""
    verdict = str(data.get("verdict", "FAIL")).upper()
    if verdict not in ("PASS", "FAIL", "PARTIAL"):
        verdict = "FAIL"
    return CheckResult(
        ac_id=ac_id,
        verdict=verdict,
        evidence=data.get("evidence", "No evidence provided"),
        file_path=data.get("file", ""),
        line_number=data.get("line", 0),
        fix_suggestion=data.get("fix", ""),
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
                fix_suggestion=r.fix_suggestion if r.fix_suggestion else (f"Fix at {r.file_path}:{r.line_number} — {r.evidence}" if r.file_path else f"Implement {ac.id}: {_truncate(r.evidence, 200)}"),
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
