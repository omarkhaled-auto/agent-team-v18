"""N-10: Forbidden-content scanner for the auditor pipeline.

Regex-based deterministic scanner that flags surface-level lexical
anti-patterns the LLM auditors miss (stub throws, TODO/FIXME comments,
placeholder secrets, untranslated RTL strings, empty function bodies).

Findings are emitted in the canonical ``AuditFinding`` shape and merged
into ``AUDIT_REPORT.json`` alongside the LLM-derived findings, so they
flow through the existing fix-dispatch path without special-casing.

Design (architect Section 5):
- Regex over AST: patterns are surface-level lexical; AST adds a TS
  parser dep + slow walk for zero semantic gain.
- Per-rule compiled regex cache for performance.
- Glob-prefiltered file walk to keep monorepo scans bounded.
- Default OFF behind ``v18.content_scope_scanner_enabled``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .audit_models import AuditFinding


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------
# Architect spec uses MAJOR/MINOR labels; the canonical AuditFinding
# severity vocabulary is CRITICAL/HIGH/MEDIUM/LOW/INFO. Map at scan time
# so downstream score/fix-dispatch logic sees the canonical values.
_SEVERITY_MAP: dict[str, str] = {
    "MAJOR": "HIGH",
    "MINOR": "LOW",
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
}


# ---------------------------------------------------------------------------
# Performance bounds
# ---------------------------------------------------------------------------
_MAX_FILE_SIZE = 200_000  # 200 KB per file — skip generated bundles
_MAX_FINDINGS_PER_RULE = 200  # cap per rule to bound memory on noisy repos
_MAX_FINDINGS_TOTAL = 500  # global cap across all rules


# ---------------------------------------------------------------------------
# Default global excludes (architect Section 5)
# ---------------------------------------------------------------------------
DEFAULT_EXCLUDES: tuple[str, ...] = (
    "node_modules/**",
    "**/node_modules/**",
    "dist/**",
    "**/dist/**",
    ".next/**",
    "**/.next/**",
    "build/**",
    "**/build/**",
    "__pycache__/**",
    "**/__pycache__/**",
    ".git/**",
    "**/*.spec.ts",
    "**/*.spec.tsx",
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.js",
    "**/*.test.js",
    "**/migrations/**",
    "**/i18n/**",
    "**/.venv/**",
    "**/venv/**",
)


# ---------------------------------------------------------------------------
# Rule dataclass
# ---------------------------------------------------------------------------

@dataclass
class ForbiddenContentRule:
    """A single forbidden-content regex rule."""

    rule_id: str
    pattern: str
    severity: str  # "MAJOR" | "MINOR" (mapped to HIGH/LOW)
    category: str  # "quality"
    glob: str  # file filter (e.g. "**/*.{ts,tsx,js,jsx}")
    message: str
    exclude_paths: list[str] = field(default_factory=list)
    multiline: bool = False  # set True for block-comment / cross-line patterns


# ---------------------------------------------------------------------------
# Default rule set (architect Section 5 — exact table)
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[ForbiddenContentRule] = [
    ForbiddenContentRule(
        rule_id="FC-001-stub-throw",
        pattern=r"""throw\s+new\s+Error\(['"](not implemented|todo|placeholder|unimplemented)""",
        severity="MAJOR",
        category="quality",
        glob="**/*.{ts,tsx,js,jsx}",
        message=(
            "Stub `throw new Error('not implemented'|'todo'|...)` — replace "
            "with real implementation per the AC."
        ),
    ),
    ForbiddenContentRule(
        rule_id="FC-002-todo-comment",
        pattern=r"//\s*(TODO|FIXME|XXX)\b",
        severity="MINOR",
        category="quality",
        glob="**/*.{ts,tsx,js,jsx}",
        message="TODO/FIXME/XXX comment — resolve before shipping.",
    ),
    ForbiddenContentRule(
        rule_id="FC-003-block-todo",
        pattern=r"/\*[\s\S]*?(TODO|FIXME|XXX)[\s\S]*?\*/",
        severity="MINOR",
        category="quality",
        glob="**/*.{ts,tsx}",
        message="Block-comment TODO/FIXME/XXX — resolve before shipping.",
        multiline=True,
    ),
    ForbiddenContentRule(
        rule_id="FC-004-placeholder-secret",
        pattern=r"""['"](CHANGE_ME|YOUR_API_KEY|REPLACE_ME|PLACEHOLDER)['"]""",
        severity="MAJOR",
        category="quality",
        glob="**/*.{ts,tsx,js,jsx,env,env.example,env.local,env.development,env.production}",
        message=(
            "Placeholder secret literal (CHANGE_ME / YOUR_API_KEY / "
            "REPLACE_ME / PLACEHOLDER) — replace with real value or env ref."
        ),
    ),
    ForbiddenContentRule(
        rule_id="FC-005-untranslated-rtl",
        pattern=r"[\u0600-\u06FF\u0750-\u077F]+",
        severity="MINOR",
        category="quality",
        glob="apps/web/**/*.{ts,tsx}",
        message=(
            "Untranslated Arabic/RTL literal in app code — move to i18n "
            "translation files."
        ),
        exclude_paths=["**/i18n/**", "**/locales/**"],
    ),
    ForbiddenContentRule(
        rule_id="FC-006-empty-fn",
        pattern=(
            r"(async\s+)?[a-zA-Z_$][\w$]*\s*\([^)]*\)\s*\{\s*\}"
        ),
        severity="MINOR",
        category="quality",
        glob="**/*.{ts,tsx}",
        message=(
            "Empty function body — likely an unimplemented stub; either "
            "implement or remove."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Glob expansion (pathlib.rglob doesn't support brace alternation natively)
# ---------------------------------------------------------------------------

_BRACE_RE = re.compile(r"\{([^{}]+)\}")


def _expand_braces(glob: str) -> list[str]:
    """Expand ``{a,b,c}`` brace alternation into separate glob patterns.

    Input ``"**/*.{ts,tsx}"`` -> ``["**/*.ts", "**/*.tsx"]``.
    Multiple brace groups expand combinatorially.
    Returns ``[glob]`` unchanged when no braces present.
    """
    match = _BRACE_RE.search(glob)
    if not match:
        return [glob]
    prefix = glob[: match.start()]
    suffix = glob[match.end():]
    alternatives = [alt.strip() for alt in match.group(1).split(",")]
    expanded: list[str] = []
    for alt in alternatives:
        expanded.extend(_expand_braces(prefix + alt + suffix))
    return expanded


def _matches_any(rel_posix: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """Return True if rel_posix matches any of the fnmatch patterns."""
    return any(fnmatch.fnmatch(rel_posix, p) for p in patterns)


# ---------------------------------------------------------------------------
# Scan core
# ---------------------------------------------------------------------------

def _gather_candidate_files(
    repo_root: Path,
    rule: ForbiddenContentRule,
    excludes: tuple[str, ...],
) -> list[Path]:
    """Walk ``repo_root`` collecting files matching ``rule.glob``.

    Applies global ``excludes`` and rule-specific ``exclude_paths`` against
    each file's path relative to ``repo_root`` (posix form).
    """
    seen: set[Path] = set()
    out: list[Path] = []
    rule_excludes = list(rule.exclude_paths)
    sub_globs = _expand_braces(rule.glob)

    # Safe walker — prunes node_modules / .pnpm / etc. at descent.
    # Previous ``repo_root.glob(sub_glob)`` descended eagerly and
    # raised WinError 3 inside pnpm's deep symlink chains (smoke #10
    # regression, N-10 forbidden_content scanner). We enumerate files
    # with skip-dir pruning and apply the original posix-relative
    # glob match against each candidate.
    from .project_walker import iter_project_files

    try:
        candidates = iter_project_files(repo_root)
    except OSError:
        return out

    for path in candidates:
        if path in seen:
            continue
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if not _matches_any(rel, sub_globs):
            continue
        if _matches_any(rel, list(excludes)):
            continue
        if rule_excludes and _matches_any(rel, rule_excludes):
            continue
        seen.add(path)
        out.append(path)

    return out


def _scan_file_with_rule(
    path: Path,
    rel_posix: str,
    rule: ForbiddenContentRule,
    compiled_re: re.Pattern[str],
) -> list[AuditFinding]:
    """Scan one file with one rule; return per-match AuditFinding list."""
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return []
    except OSError:
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return []

    findings: list[AuditFinding] = []
    file_hash = hashlib.sha1(rel_posix.encode("utf-8")).hexdigest()[:8]
    canonical_severity = _SEVERITY_MAP.get(rule.severity.upper(), "LOW")

    if rule.multiline:
        # Whole-file scan; compute line number from match.start()
        for match in compiled_re.finditer(content):
            line_number = content.count("\n", 0, match.start()) + 1
            findings.append(_build_finding(
                rule=rule,
                rel_posix=rel_posix,
                file_hash=file_hash,
                line_number=line_number,
                matched_text=match.group(0),
                canonical_severity=canonical_severity,
            ))
            if len(findings) >= _MAX_FINDINGS_PER_RULE:
                return findings
    else:
        # Per-line scan: cheaper + accurate line numbers without counting
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = compiled_re.search(line)
            if not match:
                continue
            findings.append(_build_finding(
                rule=rule,
                rel_posix=rel_posix,
                file_hash=file_hash,
                line_number=line_number,
                matched_text=line.strip(),
                canonical_severity=canonical_severity,
            ))
            if len(findings) >= _MAX_FINDINGS_PER_RULE:
                return findings

    return findings


def _build_finding(
    *,
    rule: ForbiddenContentRule,
    rel_posix: str,
    file_hash: str,
    line_number: int,
    matched_text: str,
    canonical_severity: str,
) -> AuditFinding:
    """Construct a canonical AuditFinding from one scan match."""
    snippet = (matched_text or "").strip()
    if len(snippet) > 120:
        snippet = snippet[:117] + "..."
    description = f"{rule.message} Match: {snippet}" if snippet else rule.message
    return AuditFinding(
        finding_id=f"{rule.rule_id}-{file_hash}-{line_number}",
        auditor="forbidden_content",
        requirement_id="GENERAL",
        verdict="FAIL",
        severity=canonical_severity,
        summary=rule.message,
        evidence=[f"{rel_posix}:{line_number} -- {snippet}"] if snippet else [f"{rel_posix}:{line_number}"],
        remediation=rule.message,
        confidence=1.0,
        source="deterministic",
    )


def scan_repository(
    repo_root: Path,
    rules: list[ForbiddenContentRule] | None = None,
    *,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
) -> list[AuditFinding]:
    """Scan ``repo_root`` against ``rules`` and return canonical findings.

    Parameters
    ----------
    repo_root
        Repository root to walk.
    rules
        Rule list. Defaults to :data:`DEFAULT_RULES` when ``None``.
    excludes
        Global path excludes (fnmatch patterns against repo-relative posix).

    Returns
    -------
    list[AuditFinding]
        Findings in canonical AuditFinding shape, capped at
        :data:`_MAX_FINDINGS_TOTAL`. Each finding has ``source="deterministic"``
        and ``auditor="forbidden_content"`` so downstream consumers can
        distinguish scanner findings from LLM-emitted ones.
    """
    if not repo_root.exists() or not repo_root.is_dir():
        return []

    rule_list = rules if rules is not None else DEFAULT_RULES
    if not rule_list:
        return []

    # Per-scan compiled regex cache. Patterns are reused across all files
    # for a given rule so compile once per rule.
    compiled_cache: dict[str, re.Pattern[str]] = {}

    all_findings: list[AuditFinding] = []
    for rule in rule_list:
        try:
            flags = re.MULTILINE | re.DOTALL if rule.multiline else 0
            compiled = compiled_cache.setdefault(
                rule.rule_id, re.compile(rule.pattern, flags)
            )
        except re.error:
            # A malformed user-supplied rule must not abort the whole scan.
            continue

        for path in _gather_candidate_files(repo_root, rule, excludes):
            try:
                rel_posix = path.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            file_findings = _scan_file_with_rule(path, rel_posix, rule, compiled)
            all_findings.extend(file_findings)
            if len(all_findings) >= _MAX_FINDINGS_TOTAL:
                return all_findings[:_MAX_FINDINGS_TOTAL]

    return all_findings


# ---------------------------------------------------------------------------
# Audit-report integration helper
# ---------------------------------------------------------------------------

def merge_findings_into_report(report: object, findings: list[AuditFinding]) -> None:
    """Append scanner findings to a loaded ``AuditReport`` in-place.

    Mutates ``report.findings``, recomputes ``by_severity``/``by_file``/
    ``by_requirement``/``fix_candidates`` indices, and updates
    ``auditors_deployed`` so the integrator surfaces the scanner.

    Designed to run AFTER ``AuditReport.from_json`` and BEFORE
    ``_apply_evidence_gating_to_audit_report`` so gating rebuilds (which
    may reset the indices) still see the merged findings.
    """
    if not findings:
        return

    # Defensive: preserve byte-identical behavior when the report shape
    # diverges. Only mutate when the expected attributes are present.
    if not all(hasattr(report, attr) for attr in (
        "findings", "by_severity", "by_file", "by_requirement",
        "fix_candidates", "auditors_deployed",
    )):
        return

    base_index = len(report.findings)  # type: ignore[attr-defined]
    fix_severities = {"CRITICAL", "HIGH", "MEDIUM"}

    for offset, f in enumerate(findings):
        new_idx = base_index + offset
        report.findings.append(f)  # type: ignore[attr-defined]
        report.by_severity.setdefault(f.severity, []).append(new_idx)  # type: ignore[attr-defined]
        pf = f.primary_file
        if pf:
            report.by_file.setdefault(pf, []).append(new_idx)  # type: ignore[attr-defined]
        report.by_requirement.setdefault(f.requirement_id, []).append(new_idx)  # type: ignore[attr-defined]
        if f.severity in fix_severities and f.verdict in ("FAIL", "PARTIAL"):
            report.fix_candidates.append(new_idx)  # type: ignore[attr-defined]

    deployed = list(report.auditors_deployed or [])  # type: ignore[attr-defined]
    if "forbidden_content" not in deployed:
        deployed.append("forbidden_content")
        report.auditors_deployed = deployed  # type: ignore[attr-defined]
