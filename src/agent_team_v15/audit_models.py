"""Data models for the audit-team review system.

Provides structured finding, scoring, and reporting data classes used
by the 6 specialized auditors, the scorer agent, and the fix dispatch
algorithm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Phase 4.7b — scaffold-stub header marker. The regex is comment-glyph
# AGNOSTIC: a leading run of whitespace followed by any of `//`, `#`,
# `--`, `*`, `/*`, `/**` (with optional space) is accepted. Matches the
# canonical TS/JS comment, Python/YAML hash, SQL/Prisma double-dash,
# and JSDoc/Doxygen-style continuation glyphs. Per §J the audit reads
# the FIRST 8 LINES of the file (license headers + spacing can push the
# marker to line 6-8); ``_read_scaffold_stub_owner`` truncates the disk
# read to 8 lines before applying this regex.
#
# JSON files cannot embed comments — those scaffold stubs are NOT
# auto-tagged via this regex; the convention for JSON stubs is a
# sibling ``<filename>.scaffold-stub.txt`` marker file, which a future
# helper may surface. Phase 4.7b's audit reader does NOT attempt to
# detect headers on JSON files (the in-band marker has no comment
# syntax to attach to).
_SCAFFOLD_STUB_RE = re.compile(
    r"^\s*(?://|#|--|/\*\*?|\*)\s*@scaffold-stub:\s*finalized-by-wave-"
    r"(?P<wave>[A-Z][0-9A-Z]?)",
    re.MULTILINE,
)


def _read_scaffold_stub_owner(
    file_path: str,
    project_root: str,
) -> str | None:
    """Read first 8 lines of *file_path* (resolved against *project_root*)
    and return the wave letter named in a ``@scaffold-stub: finalized-by-wave-<X>``
    header, or ``None`` when no header is found.

    Defensive on every disk error (FileNotFoundError, PermissionError,
    UnicodeDecodeError, OSError) → returns None so audit-time disk reads
    cannot raise into the caller. The audit-classifier path falls back
    to Phase 4.3's ``wave_ownership.resolve_owner_wave`` when this
    helper returns None.

    Phase 4.7b: header overrides path-based classification when both
    apply (e.g., a stub physically located under ``apps/api/`` whose
    header names Wave D — the path table would say "B" but the header's
    explicit declaration wins).
    """
    if not file_path or not project_root:
        return None
    try:
        full_path = Path(project_root) / file_path
        # Read up to ~16 KB worth of leading content to bound disk
        # cost on pathological inputs while still capturing the first 8
        # lines of any reasonable source file. The slice to 8 lines
        # below is the load-bearing trim; this byte cap is just a
        # guardrail against a file with no newlines in 100MB.
        with full_path.open("r", encoding="utf-8", errors="replace") as fh:
            head_lines: list[str] = []
            for idx, line in enumerate(fh):
                if idx >= 8:
                    break
                head_lines.append(line)
        head = "".join(head_lines)
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
        return None
    if not head:
        return None
    m = _SCAFFOLD_STUB_RE.search(head)
    if m is None:
        return None
    return m.group("wave")


# ---------------------------------------------------------------------------
# Severity and verdict constants
# ---------------------------------------------------------------------------

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
VERDICTS = ("PASS", "FAIL", "PARTIAL", "UNVERIFIED")
AUDITOR_NAMES = ("requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity")
AUDITOR_PREFIXES = {
    "requirements": "RA",
    "technical": "TA",
    "interface": "IA",
    "test": "XA",
    "mcp_library": "MA",
    "prd_fidelity": "PA",
}

# Severity weights for fix dispatch priority ordering
_SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

# Maximum findings to keep after dedup — prevents overwhelming the fix dispatcher
_MAX_FINDINGS = 50


class AuditReportSchemaError(ValueError):
    """Raised by ``AuditReport.from_json`` on structurally invalid payloads.

    F-EDGE-003: callers previously caught a bare ``AttributeError`` from
    scorer drift (``findings`` emitted as a dict or string instead of a
    list) and silently restarted from cycle 1. That masked real schema
    regressions. This typed exception lets callers log the drift
    loudly and decide whether to resume or fail-fast.
    """


# ---------------------------------------------------------------------------
# AuditFinding
# ---------------------------------------------------------------------------

@dataclass
class AuditFinding:
    """A single audit finding from any auditor."""

    finding_id: str
    auditor: str
    requirement_id: str
    verdict: str
    severity: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    remediation: str = ""
    confidence: float = 1.0
    source: str = "llm"  # "deterministic" | "llm" | "manual"
    # N-11 cascade suppression: populated only when the consolidator
    # collapses ≥2 downstream findings that share a scaffold-verifier
    # root cause. Defaults preserve byte-identical to_dict output for
    # non-consolidated findings (cascade_count omitted when 0).
    cascade_count: int = 0
    cascaded_from: list[str] = field(default_factory=list)
    # Phase 4.3 audit-wave-awareness: each finding gains an owner_wave
    # tag derived from its primary file path (B/C/D/T/...). When the
    # owner wave never executed for a milestone, the audit team treats
    # the finding as DEFERRED rather than FAIL — convergence ratios
    # and audit-fix dispatch both filter on this. Default
    # ``wave-agnostic`` preserves byte-identical behaviour for legacy
    # consumers; ``from_dict`` auto-populates from path-shaped data
    # already in the canonical schema.
    owner_wave: str = "wave-agnostic"

    def to_dict(self, *, run_state: Any = None) -> dict:
        """Serialize this finding for AUDIT_REPORT.json.

        Phase 4.3 (2026-04-27) added ``owner_wave`` to the in-memory
        shape and gated emission to non-default values for
        byte-identical round-trip with pre-Phase-4.3 fixtures.

        Risk-#32 follow-up (2026-04-28, smoke
        m1-hardening-smoke-20260427-213258): flips that gate to ALWAYS
        emit ``owner_wave`` so consumers reading AUDIT_REPORT.json
        directly (without going through ``from_dict``) see the
        wave-attribution every time. ``"wave-agnostic"`` is now
        explicit on disk rather than implicit.

        New optional ``run_state`` kwarg threads the milestone's
        wave-progress into ``compute_finding_status`` so the disk
        shape carries a ``status`` field too: ``"DEFERRED"`` when the
        finding's owner_wave never executed, otherwise the verdict.
        Writers that have a run_state in scope (the audit-loop call
        sites in cli.py) pass it; callers without (legacy direct-
        construction sites, e.g., AuditFinding test fixtures) get the
        pre-Phase-4 shape (no ``status`` key, but explicit
        ``owner_wave``).
        """
        out: dict[str, Any] = {
            "finding_id": self.finding_id,
            "auditor": self.auditor,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "confidence": self.confidence,
            "source": self.source,
        }
        if self.cascade_count:
            out["cascade_count"] = self.cascade_count
            out["cascaded_from"] = list(self.cascaded_from)
        # Risk #32: always emit owner_wave so disk-shape mirrors
        # in-memory shape. Default ``"wave-agnostic"`` is now explicit
        # rather than implicit.
        out["owner_wave"] = self.owner_wave or "wave-agnostic"
        # Phase 4.3 status: DEFERRED when the owner wave never executed;
        # otherwise the verdict. Only computed when run_state is supplied
        # (writers that have it in scope).
        if run_state is not None:
            from .wave_ownership import compute_finding_status
            out["status"] = compute_finding_status(self, run_state)
        return out

    @classmethod
    def from_dict(
        cls,
        data: dict,
        *,
        project_root: str | None = None,
    ) -> AuditFinding:
        # The scorer prompt has historically included two output schemas
        # (``finding_id`` vs ``id``, ``summary`` vs ``title``,
        # ``remediation`` vs ``fix_action``).  Accept either shape so a
        # minor LLM drift in the scorer's JSON does not turn into
        # ``KeyError: 'finding_id'`` at parse time and silently throw away
        # an entire AUDIT_REPORT.json.
        #
        # Phase 4.7b adds the optional ``project_root`` kwarg: when
        # supplied, ``_read_scaffold_stub_owner`` consults the file's
        # first 8 lines for a ``@scaffold-stub: finalized-by-wave-<X>``
        # header and uses the named wave as ``owner_wave`` (overriding
        # path-based classification). Legacy callers that pass no
        # ``project_root`` get the pre-Phase-4.7b path-only path; no
        # disk reads happen in that mode.
        finding_id = data.get("finding_id") or data.get("id") or ""
        evidence_list = data.get("evidence", [])
        if not evidence_list:
            # Phase 3.5 audit-fix-loop guardrail (latent-bug fix): every
            # audit JSON in this repo's smoke history (build-final-smoke-
            # 2026-04-18 → m1-hardening-smoke-2026-04-25) emits the
            # per-finding file as ``file_path``, but the legacy fallback
            # only checked ``file``. The miss leaked ~16 percentage
            # points of "free-form features" (no primary_file → no
            # target_files → audit-fix hook becomes no-op for that
            # dispatch). Read both keys so the audit-fix scope binding
            # holds for the canonical schema and the legacy one.
            file_hint = data.get("file_path") or data.get("file")
            desc_hint = data.get("description") or data.get("summary") or ""
            if file_hint:
                line_hint = data.get("line_number")
                if isinstance(line_hint, int) and line_hint > 0:
                    evidence_head = f"{file_hint}:{line_hint}"
                else:
                    evidence_head = str(file_hint)
                evidence_list = (
                    [f"{evidence_head} -- {desc_hint[:80]}"] if desc_hint else [evidence_head]
                )
        # Phase 4.3 audit-wave-awareness: derive owner_wave. Explicit
        # ``owner_wave`` in the payload always wins (e.g. an auditor
        # tags a Wave-T regression on a Wave-B-owned file). Otherwise
        # resolve from the same file_hint computed above for evidence
        # synthesis — both keys (file_path / file) round-trip through
        # the wave_ownership table. ``wave-agnostic`` is the safe
        # default when no path information is present.
        owner_wave_raw = data.get("owner_wave")
        if owner_wave_raw:
            owner_wave = str(owner_wave_raw).strip() or "wave-agnostic"
        else:
            from .wave_ownership import resolve_owner_wave
            file_hint_for_wave = data.get("file_path") or data.get("file") or ""
            file_hint_str = (
                str(file_hint_for_wave) if file_hint_for_wave else ""
            )
            # Phase 4.7b: prefer the on-disk @scaffold-stub header when
            # we have a project_root to resolve the file against.
            # Header-named wave wins over path-based ownership (the
            # header is the canonical declaration for scaffold stubs;
            # see Phase 4.7b spec in docs/plans/2026-04-26-pipeline-upgrade-phase4.md §J).
            header_wave: str | None = None
            if project_root and file_hint_str:
                header_wave = _read_scaffold_stub_owner(
                    file_hint_str, project_root
                )
            if header_wave:
                owner_wave = header_wave
            else:
                owner_wave = resolve_owner_wave(file_hint_str)
        return cls(
            finding_id=finding_id,
            auditor=data.get("auditor", "scorer"),
            requirement_id=data.get("requirement_id", ""),
            verdict=data.get("verdict", "FAIL"),
            severity=data.get("severity", "MEDIUM"),
            summary=data.get("summary") or data.get("title", ""),
            evidence=evidence_list,
            remediation=data.get("remediation") or data.get("fix_action", ""),
            confidence=data.get("confidence", 1.0),
            source=data.get("source", "llm"),
            cascade_count=int(data.get("cascade_count", 0) or 0),
            cascaded_from=list(data.get("cascaded_from", []) or []),
            owner_wave=owner_wave,
        )

    @property
    def primary_file(self) -> str:
        """Extract the primary file path from the first evidence entry."""
        if not self.evidence:
            return ""
        filepath, _, _ = parse_evidence_entry(self.evidence[0])
        return filepath

    @property
    def sibling_test_files(self) -> list[str]:
        """Heuristic: derive the test files associated with this finding.

        Phase 2 audit-fix-loop guardrail. Bridges an ``AuditFinding`` to
        the test surface that protects it. Used by ``_convert_findings``
        to populate ``Finding.test_surface`` and by Phase 3's per-fix
        path-allowlist hook.

        Delegates to the free-function :func:`derive_sibling_test_files`
        so Phase 3's audit-fix dispatch pipeline (which works with raw
        path strings, not :class:`AuditFinding` instances) can apply
        the same heuristic without constructing a synthetic finding.
        """
        return derive_sibling_test_files(self.primary_file)


# Internal heuristic constants shared between the AuditFinding property
# and the free-function form. Kept module-private so future tweaks
# stay localised.
_NEXTJS_GENERIC: frozenset[str] = frozenset(
    {
        "page",
        "layout",
        "route",
        "loading",
        "error",
        "index",
        "default",
        "not-found",
        "template",
    }
)
# Don't fall back to top-level packaging dirs as the test name —
# ``apps/web/page.tsx`` shouldn't become ``e2e/tests/web.spec.ts``.
_PARENT_REJECT: frozenset[str] = frozenset(
    {"web", "api", "app", "src", "components", "pages", "tests"}
)


def derive_sibling_test_files(primary_file: str) -> list[str]:
    """Free-function form of :meth:`AuditFinding.sibling_test_files`.

    Phase 3 audit-fix-loop guardrail: callable on any path string so
    the per-feature dispatch pipeline (which has only feature
    target-files, not :class:`AuditFinding` instances) can compute the
    same per-finding test surface used by the path-allowlist hook.

    Heuristic:

    * Empty/whitespace input → ``[]``.
    * Next.js / App Router basename convention (``page``/``layout``/
      ``route``/``loading``/``error``/``index``/``default``/
      ``not-found``/``template``) where the parent dir is route-shaped
      (i.e. NOT a top-level packaging dir like ``web``/``api``/
      ``app``/``src``/etc.) uses the parent dir as the stem
      (``apps/web/login/page.tsx`` → ``login``).
    * Otherwise the basename stem (``apps/web/login.tsx`` →
      ``login``).

    Returns deterministic, ordered candidate paths covering the
    Playwright spec convention plus the pytest conventions. Callers
    filter to existing files; missing siblings are normal — not every
    code change has a sibling test.
    """
    if not primary_file or not primary_file.strip():
        return []
    normalized = primary_file.replace("\\", "/").strip()
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return []
    path_obj = Path(parts[-1])
    base = path_obj.stem
    parent = parts[-2] if len(parts) >= 2 else ""
    if base in _NEXTJS_GENERIC and parent and parent not in _PARENT_REJECT:
        stem = parent
    else:
        stem = base
    if not stem:
        return []
    return [
        f"e2e/tests/{stem}.spec.ts",
        f"tests/test_{stem}.py",
        f"apps/api/test/test_{stem}.py",
    ]


# ---------------------------------------------------------------------------
# Phase 3.5 — primary_file synthesis
# ---------------------------------------------------------------------------

# Path-shaped string regex: at least one ``/`` separator + a file extension.
# Rejects bare basenames (``STATE.json``), version-shaped tokens
# (``0.0``, ``9.9``), and prose tokens. Keeps multi-segment paths whose
# tail looks like a real file (``apps/web/login.tsx``).
_PATH_SHAPED_RE = re.compile(
    r"(?<![\w/.-])(?:[\w-]+/)+[\w.-]+\.[A-Za-z][\w]{0,5}(?![\w/])"
)


def synthesise_primary_file(
    finding: Any,
    *,
    project_root: "Path | str | None" = None,
) -> list[str]:
    """Walk a :class:`Finding` (or AuditFinding) for path-shaped tokens
    and return those that exist on disk under ``project_root``.

    Phase 3.5 audit-fix-loop guardrail: when a finding has no direct
    ``file_path`` (~25% of audit findings on this repo, even after the
    Phase 3.5 ``from_dict`` fix), walk the description / current_behavior
    / expected_behavior / fix_suggestion text for path-shaped tokens.
    Filter to:

    * Tokens whose extracted path EXISTS under ``project_root``.
    * Tokens that resolve to FILES (not directories) — Phase 3's
      audit-fix path guard treats allowlist entries as exact-file
      permissions; a directory entry would either widen scope to a
      Wave-D-style glob (anti-pattern, see handoff §8) or fail-CLOSED
      on every write.

    Returns deduplicated POSIX paths relative to ``project_root``,
    deterministic order (first-extracted wins). Empty list when no
    extractable path passes the filter — caller MUST treat empty as
    "ship-block this feature" (Path A residual semantics).

    Per-handoff anti-pattern §8: never returns a wildcard or directory
    glob; the exact-file allowlist semantic is load-bearing.
    """
    if finding is None:
        return []
    root = Path(project_root) if project_root is not None else Path.cwd()

    # Source fields ranked by reliability (file_path first if present so
    # we round-trip a known-good path; then description; then behaviours).
    sources: list[str] = []
    direct = str(getattr(finding, "file_path", "") or "").strip()
    if direct:
        sources.append(direct)
    for attr in ("description", "current_behavior", "expected_behavior", "fix_suggestion", "title"):
        value = str(getattr(finding, attr, "") or "")
        if value:
            sources.append(value)
    # AuditFinding evidence is a list, not a string; flatten it in.
    for entry in getattr(finding, "evidence", []) or []:
        sources.append(str(entry))

    seen: set[str] = set()
    matches: list[str] = []
    for source in sources:
        # The direct file_path field doesn't always carry a slash (e.g.,
        # the auditor sometimes emits a bare ``STATE.json``). Try the
        # source as a literal path first, then regex-extract.
        candidates: list[str] = []
        literal = source.strip().replace("\\", "/").lstrip("/")
        if literal and "/" in literal and "\n" not in literal and " " not in literal.split(":", 1)[0]:
            candidates.append(literal.split(":", 1)[0])
        for raw in _PATH_SHAPED_RE.findall(source):
            candidates.append(raw.replace("\\", "/"))
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            absolute = (root / candidate).resolve()
            try:
                # Reject anything outside project_root — defense against
                # an absolute path or ``..`` traversal landing in the
                # parent's filesystem.
                absolute.relative_to(root.resolve())
            except (ValueError, OSError):
                continue
            if not absolute.is_file():
                continue
            seen.add(candidate)
            matches.append(candidate)
    return matches


# ---------------------------------------------------------------------------
# AuditScore
# ---------------------------------------------------------------------------

@dataclass
class AuditScore:
    """Computed score for an audit run."""

    total_items: int
    passed: int
    failed: int
    partial: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    score: float
    health: str
    # D-07: scorer-produced reports include a top-level ``max_score``
    # (e.g. 1000) as the denominator against which ``score`` is judged.
    # Legacy ``compute`` uses a percentage scale so max_score=100 there;
    # preserved on ``AuditScore`` so downstream telemetry can display the
    # raw-scale score without re-reading AUDIT_REPORT.json.
    max_score: int = 100

    @staticmethod
    def compute(
        findings: list[AuditFinding],
        healthy_threshold: float = 90.0,
        degraded_threshold: float = 70.0,
    ) -> AuditScore:
        """Compute score from a list of findings."""
        req_verdicts: dict[str, str] = {}
        severity_counts = {s: 0 for s in SEVERITIES}
        verdict_rank = {"PASS": 0, "PARTIAL": 1, "UNVERIFIED": 2, "FAIL": 3}

        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            if f.requirement_id == "GENERAL":
                continue
            current = req_verdicts.get(f.requirement_id)
            if current is None or verdict_rank.get(f.verdict, 3) > verdict_rank.get(current, 3):
                req_verdicts[f.requirement_id] = f.verdict

        total = len(req_verdicts)
        passed = sum(1 for v in req_verdicts.values() if v == "PASS")
        failed = sum(1 for v in req_verdicts.values() if v == "FAIL")
        partial = sum(1 for v in req_verdicts.values() if v in {"PARTIAL", "UNVERIFIED"})

        score = (passed * 100 + partial * 50) / max(total, 1)

        critical = severity_counts.get("CRITICAL", 0)
        if score >= healthy_threshold and critical == 0:
            health = "healthy"
        elif score >= degraded_threshold and critical == 0:
            health = "degraded"
        else:
            health = "failed"

        return AuditScore(
            total_items=total,
            passed=passed,
            failed=failed,
            partial=partial,
            critical_count=critical,
            high_count=severity_counts.get("HIGH", 0),
            medium_count=severity_counts.get("MEDIUM", 0),
            low_count=severity_counts.get("LOW", 0),
            info_count=severity_counts.get("INFO", 0),
            score=round(score, 1),
            health=health,
            max_score=100,
        )

    def to_dict(self) -> dict:
        return {
            "total_items": self.total_items,
            "passed": self.passed,
            "failed": self.failed,
            "partial": self.partial,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "info_count": self.info_count,
            "score": self.score,
            "health": self.health,
            "max_score": self.max_score,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditScore:
        return cls(
            total_items=data["total_items"],
            passed=data["passed"],
            failed=data["failed"],
            partial=data["partial"],
            critical_count=data["critical_count"],
            high_count=data["high_count"],
            medium_count=data["medium_count"],
            low_count=data["low_count"],
            info_count=data["info_count"],
            score=data["score"],
            health=data["health"],
            max_score=data.get("max_score", 100),
        )


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------

_AUDIT_REPORT_KNOWN_KEYS = frozenset({
    "audit_id",
    "timestamp",
    "cycle",
    "audit_cycle",  # scorer-side alias consumed into `cycle`
    "auditors_deployed",
    "findings",
    "score",
    "max_score",  # scorer-side flat-score companion
    "by_severity",
    "by_file",
    "by_requirement",
    "fix_candidates",
    "scope",
    "acceptance_tests",  # D-20 startup-AC probe results (infra milestones)
})


@dataclass
class AuditReport:
    """Complete audit report produced by the scorer agent."""

    audit_id: str
    timestamp: str
    cycle: int
    auditors_deployed: list[str]
    findings: list[AuditFinding]
    score: AuditScore
    by_severity: dict[str, list[int]] = field(default_factory=dict)
    by_file: dict[str, list[int]] = field(default_factory=dict)
    by_requirement: dict[str, list[int]] = field(default_factory=dict)
    fix_candidates: list[int] = field(default_factory=list)
    # C-01: a compact snapshot of what was audited — milestone_id +
    # the allowed_file_globs the auditor was restricted to. Consumers
    # can tell at a glance whether a report was produced under
    # milestone-scoped audit or under legacy full-PRD audit.
    scope: dict[str, Any] = field(default_factory=dict)
    # D-07: preserve scorer-produced top-level fields that are not first-class
    # on AuditReport (e.g., ``verdict``, ``health``, ``notes``,
    # ``finding_counts``, ``category_summary``, ``deductions_total``,
    # ``deductions_capped``). Informational only — consumers that need them
    # (e.g., ``State.finalize`` reading the scorer's ``health``) read from
    # here rather than round-tripping through to_json.
    extras: dict[str, Any] = field(default_factory=dict)
    # D-20: structured results of audit-phase startup-AC probes (e.g.,
    # ``{"m1_startup_probe": {"npm_install": {...}, "compose_up": {...}}}``).
    # Populated only for infrastructure milestones; empty otherwise.
    acceptance_tests: dict[str, Any] = field(default_factory=dict)

    def to_json(self, *, run_state: Any = None) -> str:
        """Serialize to JSON for persistence (canonical shape).

        N-15: Preserves scorer-side top-level keys captured on ``extras``
        (verdict, health, notes, category_summary, finding_counts,
        deductions_total, overall_score, threshold_pass, auditors_run, etc.)
        so a from_json -> to_json round-trip of a scorer-raw report does
        not silently drop them. Extras are spread FIRST so canonical
        fields always win on collision (defense-in-depth; the
        ``_AUDIT_REPORT_KNOWN_KEYS`` filter at from_json:342 prevents
        collision from legitimate paths).

        Risk-#32 follow-up (2026-04-28): optional ``run_state`` kwarg
        threads the milestone's wave-progress into each finding's
        ``to_dict`` so the disk shape carries Phase 4.3 ``status``
        (DEFERRED when owner_wave never executed) and explicit
        ``owner_wave`` even for ``"wave-agnostic"``. Writers that
        have a run_state pass it; legacy callers preserve byte-shape
        modulo the always-emit ``owner_wave`` change.
        """
        return json.dumps({
            **(self.extras if isinstance(self.extras, dict) else {}),
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "cycle": self.cycle,
            "auditors_deployed": self.auditors_deployed,
            "findings": [f.to_dict(run_state=run_state) for f in self.findings],
            "score": self.score.to_dict(),
            "by_severity": self.by_severity,
            "by_file": self.by_file,
            "by_requirement": self.by_requirement,
            "fix_candidates": self.fix_candidates,
            "scope": self.scope,
            "acceptance_tests": self.acceptance_tests,
        }, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> AuditReport:
        """Deserialize from JSON.

        Permissive reader (D-07): accepts BOTH the canonical ``to_json``
        shape AND the scorer-produced shape that appears in real
        ``AUDIT_REPORT.json`` files (``audit_cycle`` alias, flat ``score``
        + ``max_score`` pair, missing ``audit_id`` / ``auditors_deployed``,
        top-level ``verdict``/``health``/``notes``/...). Unknown
        top-level keys are preserved on ``extras`` so downstream
        consumers can still access them.
        """
        data = json.loads(json_str)

        # F-EDGE-003: validate findings shape BEFORE iterating so scorer
        # drift (dict / string / other non-list) surfaces as a typed
        # ``AuditReportSchemaError`` instead of a bare ``AttributeError``
        # swallowed by callers. ``None`` and the empty-list sentinel are
        # the two valid "no findings" shapes and fall through.
        raw_findings = data.get("findings")
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            raise AuditReportSchemaError(
                f"AUDIT_REPORT findings must be a list; got "
                f"{type(raw_findings).__name__}"
            )
        try:
            findings = [AuditFinding.from_dict(f) for f in raw_findings]
        except (AttributeError, TypeError, KeyError) as exc:
            raise AuditReportSchemaError(
                f"AUDIT_REPORT findings contain malformed entries: {exc}"
            ) from exc

        # cycle: alias ``audit_cycle`` -> ``cycle``. ``cycle`` wins if both set.
        cycle_value = data.get("cycle")
        if cycle_value is None:
            cycle_value = data.get("audit_cycle", 1)
        try:
            cycle = int(cycle_value)
        except (TypeError, ValueError):
            cycle = 1

        timestamp = data.get("timestamp", "")

        # audit_id: synthesize when missing for deterministic round-trip.
        audit_id = data.get("audit_id") or f"audit-{timestamp}-c{cycle}"

        auditors_deployed = data.get("auditors_deployed") or []

        # score: accept AuditScore-shaped dict OR flat top-level number.
        raw_score = data.get("score")
        if isinstance(raw_score, dict):
            score = AuditScore.from_dict(raw_score)
        else:
            # Flat scorer shape: top-level ``score`` (number) + ``max_score``.
            try:
                flat_score = float(raw_score) if raw_score is not None else 0.0
            except (TypeError, ValueError):
                flat_score = 0.0
            try:
                max_score = int(data.get("max_score", 0))
            except (TypeError, ValueError):
                max_score = 0
            score = AuditScore(
                total_items=0,
                passed=0,
                failed=0,
                partial=0,
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                info_count=0,
                score=flat_score,
                health=str(data.get("health", "")),
                max_score=max_score,
            )

        extras = {k: v for k, v in data.items() if k not in _AUDIT_REPORT_KNOWN_KEYS}

        # D-07 completion: scorer-produced reports ship ``fix_candidates``
        # as a list of finding-id strings (["F-001", "F-002", ...]); the
        # canonical ``to_json`` shape ships integer indices into
        # ``findings``. Downstream consumers (``group_findings_into_fix_tasks``)
        # index ``findings[i]`` and would raise on strings, so normalize
        # to ``list[int]`` here. Unknown ids (absent from ``findings``)
        # are silently dropped — they're unusable to the dispatcher.
        raw_fix_candidates = data.get("fix_candidates", []) or []
        if raw_fix_candidates and isinstance(raw_fix_candidates[0], str):
            id_to_idx = {f.finding_id: i for i, f in enumerate(findings)}
            fix_candidates = []
            dropped: list[str] = []
            for fid in raw_fix_candidates:
                if fid in id_to_idx:
                    fix_candidates.append(id_to_idx[fid])
                else:
                    dropped.append(fid)
            if dropped:
                import logging
                logging.getLogger(__name__).warning(
                    "AuditReport.from_json: %d fix_candidate id(s) dropped "
                    "(absent from findings): %s. Total findings=%d, "
                    "candidates kept=%d. (NEW-8)",
                    len(dropped),
                    dropped[:10] + (["..."] if len(dropped) > 10 else []),
                    len(findings),
                    len(fix_candidates),
                )
        else:
            try:
                fix_candidates = [int(x) for x in raw_fix_candidates]
            except (TypeError, ValueError):
                fix_candidates = []

        # by_severity / by_file left verbatim — info-only in the scorer
        # shape (values are finding-id strings, not indices). No production
        # consumer indexes ``findings`` through these maps, so the shape
        # divergence is benign.
        return cls(
            audit_id=audit_id,
            timestamp=timestamp,
            cycle=cycle,
            auditors_deployed=auditors_deployed,
            findings=findings,
            score=score,
            by_severity=data.get("by_severity", {}),
            by_file=data.get("by_file", {}),
            by_requirement=data.get("by_requirement", {}),
            fix_candidates=fix_candidates,
            scope=data.get("scope", {}),
            extras=extras,
            acceptance_tests=data.get("acceptance_tests", {}),
        )


# ---------------------------------------------------------------------------
# FalsePositive — suppression tracking
# ---------------------------------------------------------------------------

@dataclass
class FalsePositive:
    """A suppressed finding marked as false positive.

    Used to prevent the same deterministic finding from re-appearing
    in subsequent audit cycles after manual review.
    """

    finding_id: str
    reason: str
    suppressed_by: str = "manual"  # "manual" | "auto"
    timestamp: str = ""
    file_path: str = ""
    line_range: tuple[int, int] = (0, 0)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "reason": self.reason,
            "suppressed_by": self.suppressed_by,
            "timestamp": self.timestamp,
            "file_path": self.file_path,
            "line_range": list(self.line_range),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FalsePositive:
        return cls(
            finding_id=data["finding_id"],
            reason=data.get("reason", ""),
            suppressed_by=data.get("suppressed_by", "manual"),
            timestamp=data.get("timestamp", ""),
            file_path=data.get("file_path", ""),
            line_range=tuple(data.get("line_range", (0, 0))),
        )


# ---------------------------------------------------------------------------
# AuditCycleMetrics — convergence tracking
# ---------------------------------------------------------------------------

@dataclass
class AuditCycleMetrics:
    """Metrics for a single audit cycle, used for convergence detection.

    Tracks finding counts, score progression, and new/fixed/regressed
    findings relative to the previous cycle.
    """

    cycle: int
    total_findings: int
    deterministic_findings: int
    llm_findings: int
    score: float
    health: str
    new_finding_ids: list[str] = field(default_factory=list)
    fixed_finding_ids: list[str] = field(default_factory=list)
    regressed_finding_ids: list[str] = field(default_factory=list)

    @property
    def net_change(self) -> int:
        """Net change in findings: positive = more bugs found, negative = bugs fixed."""
        return len(self.new_finding_ids) - len(self.fixed_finding_ids)

    @property
    def is_plateau(self) -> bool:
        """True if no findings were fixed and no new findings appeared."""
        return len(self.fixed_finding_ids) == 0 and len(self.new_finding_ids) == 0

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "total_findings": self.total_findings,
            "deterministic_findings": self.deterministic_findings,
            "llm_findings": self.llm_findings,
            "score": self.score,
            "health": self.health,
            "new_finding_ids": self.new_finding_ids,
            "fixed_finding_ids": self.fixed_finding_ids,
            "regressed_finding_ids": self.regressed_finding_ids,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditCycleMetrics:
        return cls(
            cycle=data["cycle"],
            total_findings=data["total_findings"],
            deterministic_findings=data.get("deterministic_findings", 0),
            llm_findings=data.get("llm_findings", 0),
            score=data["score"],
            health=data["health"],
            new_finding_ids=data.get("new_finding_ids", []),
            fixed_finding_ids=data.get("fixed_finding_ids", []),
            regressed_finding_ids=data.get("regressed_finding_ids", []),
        )


def compute_cycle_metrics(
    cycle: int,
    current_report: AuditReport,
    previous_report: AuditReport | None = None,
) -> AuditCycleMetrics:
    """Compute convergence metrics by comparing current and previous audit reports."""
    current_ids = {f.finding_id for f in current_report.findings}
    prev_ids = {f.finding_id for f in previous_report.findings} if previous_report else set()

    new_ids = sorted(current_ids - prev_ids)
    fixed_ids = sorted(prev_ids - current_ids)

    # Regressed = findings that were fixed in a prior cycle but reappeared
    regressed_ids: list[str] = []
    if previous_report:
        # A finding is regressed if it exists now but not in the previous report,
        # AND it had appeared in any earlier cycle (approximated by checking
        # if any current finding has a matching requirement_id that was PASS before)
        prev_pass_reqs = {
            f.requirement_id for f in previous_report.findings if f.verdict == "PASS"
        }
        for f in current_report.findings:
            if f.finding_id in new_ids and f.requirement_id in prev_pass_reqs:
                regressed_ids.append(f.finding_id)

    det_count = sum(1 for f in current_report.findings if f.source == "deterministic")
    llm_count = sum(1 for f in current_report.findings if f.source == "llm")

    return AuditCycleMetrics(
        cycle=cycle,
        total_findings=len(current_report.findings),
        deterministic_findings=det_count,
        llm_findings=llm_count,
        score=current_report.score.score,
        health=current_report.score.health,
        new_finding_ids=new_ids,
        fixed_finding_ids=fixed_ids,
        regressed_finding_ids=regressed_ids,
    )


def _finding_line_range(finding: AuditFinding) -> tuple[int, int]:
    """Extract a (start_line, end_line) range from a finding for fingerprinting."""
    line = getattr(finding, "line", 0) or 0
    end_line = getattr(finding, "end_line", 0) or line
    return (line, end_line)


def filter_false_positives(
    findings: list[AuditFinding],
    suppressions: list[FalsePositive],
) -> list[AuditFinding]:
    """Remove findings whose IDs or fingerprints appear in the suppression list.

    ID-only suppressions (manual) suppress ALL instances of that finding_id.
    Fingerprinted suppressions (auto, with file_path) only suppress the
    specific instance matching (finding_id, file_path, line_range).
    """
    # ID-only suppressions (no file_path = suppress all instances)
    suppressed_ids = {fp.finding_id for fp in suppressions if not fp.file_path}

    # Fingerprinted suppressions (file_path present = suppress specific instance)
    suppressed_fingerprints: set[tuple[str, str, tuple[int, int]]] = set()
    for fp in suppressions:
        if fp.file_path:
            suppressed_fingerprints.add((fp.finding_id, fp.file_path, fp.line_range))

    result: list[AuditFinding] = []
    for f in findings:
        if f.finding_id in suppressed_ids:
            continue
        if suppressed_fingerprints:
            fp_key = (
                f.finding_id,
                getattr(f, "file_path", "") or "",
                _finding_line_range(f),
            )
            if fp_key in suppressed_fingerprints:
                continue
        result.append(f)
    return result


def build_cycle_suppression_set(
    previous_findings: list[AuditFinding],
    fixed_finding_ids: list[str],
) -> list[FalsePositive]:
    """D-10: Build a per-cycle suppression set from previously-fixed findings.

    When a finding was present in the previous cycle and its ID appears in
    ``fixed_finding_ids`` (marked as fix-attempted), suppress it in the
    current cycle to prevent phantom re-raises.

    Suppression is fingerprinted by (finding_id, file_path, line_range)
    to avoid suppressing genuinely new instances of the same check class
    in different files.

    Safety: this set is per-run only. Fresh run = fresh suppression set.
    """
    suppressions: list[FalsePositive] = []
    fixed_set = set(fixed_finding_ids)
    for finding in previous_findings:
        if finding.finding_id in fixed_set:
            suppressions.append(FalsePositive(
                finding_id=finding.finding_id,
                reason=f"Auto-suppressed: fix applied in previous cycle",
                suppressed_by="auto",
                timestamp=finding.timestamp if hasattr(finding, "timestamp") else "",
                file_path=getattr(finding, "file_path", "") or "",
                line_range=_finding_line_range(finding),
            ))
    return suppressions


# ---------------------------------------------------------------------------
# FixTask
# ---------------------------------------------------------------------------

@dataclass
class FixTask:
    """A grouped fix task for debugger dispatch."""

    target_files: list[str]
    findings: list[AuditFinding]
    priority: str  # highest severity among findings

    @property
    def priority_order(self) -> int:
        """Numeric priority for sorting (lower = higher priority)."""
        return _SEVERITY_ORDER.get(self.priority, 99)

    def to_dict(self) -> dict:
        return {
            "target_files": self.target_files,
            "findings": [f.to_dict() for f in self.findings],
            "priority": self.priority,
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def parse_evidence_entry(entry: str) -> tuple[str, int | None, str]:
    """Parse a single evidence string into (file_path, line_number, description).

    Handles formats:
      - "src/file.ts:42 -- description"          (standard)
      - "C:\\Users\\path\\file.ts:42 -- desc"     (Windows absolute)
      - "src/file.ts -- no line number"           (missing line)
      - multiline entries (uses first line only)
    """
    # Use first line only for multiline evidence
    line = entry.split("\n")[0].strip()
    if not line:
        return ("", None, "")

    # Split on " -- " to separate file:line from description
    desc = ""
    if " -- " in line:
        file_part, desc = line.split(" -- ", 1)
    else:
        file_part = line

    file_part = file_part.strip()

    # Detect Windows absolute path (e.g., C:\Users\...) — drive letter at position 0-1
    colon_idx = file_part.find(":")
    if colon_idx == 1 and len(file_part) > 2 and file_part[2] in ("/", "\\"):
        # Windows path — look for next colon (line number separator)
        next_colon = file_part.find(":", 2)
        if next_colon != -1:
            filepath = file_part[:next_colon]
            line_str = file_part[next_colon + 1:].strip()
            try:
                return (filepath, int(line_str), desc)
            except ValueError:
                return (filepath, None, desc)
        return (file_part, None, desc)

    # Standard path — first colon is the line number separator
    if colon_idx != -1:
        filepath = file_part[:colon_idx]
        line_str = file_part[colon_idx + 1:].strip()
        try:
            return (filepath, int(line_str), desc)
        except ValueError:
            return (filepath, None, desc)

    # No colon at all — just a filepath (or partial)
    return (file_part.split(" ")[0], None, desc)


def deduplicate_findings(findings: list[AuditFinding]) -> list[AuditFinding]:
    """Deduplicate findings per the scorer rules.

    1. Same requirement_id + same verdict: keep higher confidence
    2. Same file:line across auditors: merge evidence
    3. Never deduplicate across different requirement_ids
    """
    # Group by requirement_id
    by_req: dict[str, list[AuditFinding]] = {}
    for f in findings:
        by_req.setdefault(f.requirement_id, []).append(f)

    result: list[AuditFinding] = []
    for req_id, group in by_req.items():
        if req_id == "GENERAL":
            # Keep all GENERAL findings (they may be from different auditors about different things)
            result.extend(group)
            continue

        # Within each requirement, deduplicate by verdict
        by_verdict: dict[str, list[AuditFinding]] = {}
        for f in group:
            by_verdict.setdefault(f.verdict, []).append(f)

        for verdict, vgroup in by_verdict.items():
            if len(vgroup) == 1:
                result.append(vgroup[0])
            else:
                # Keep the one with highest confidence, merge evidence
                best = max(vgroup, key=lambda x: x.confidence)
                merged_evidence = list(best.evidence)
                for other in vgroup:
                    if other is not best:
                        for ev in other.evidence:
                            if ev not in merged_evidence:
                                merged_evidence.append(ev)
                best_copy = AuditFinding(
                    finding_id=best.finding_id,
                    auditor=best.auditor,
                    requirement_id=best.requirement_id,
                    verdict=best.verdict,
                    severity=best.severity,
                    summary=best.summary,
                    evidence=merged_evidence,
                    remediation=best.remediation,
                    confidence=best.confidence,
                    source=best.source,
                )
                result.append(best_copy)

    # --- Second pass: file:line-level dedup across auditors ---
    # If multiple findings reference the same file:line with the same severity,
    # same verdict, AND the same requirement_id, merge them.
    # Never merge across requirement_ids or different verdicts.
    file_line_groups: dict[tuple[str, int | None, str, str, str], list[int]] = {}
    for idx, f in enumerate(result):
        # GENERAL findings are never deduplicated (may be from different auditors about different things)
        if f.requirement_id == "GENERAL":
            continue
        filepath, line_no, _ = parse_evidence_entry(f.evidence[0]) if f.evidence else ("", None, "")
        if filepath and line_no is not None:
            key = (filepath, line_no, f.severity, f.requirement_id, f.verdict)
            file_line_groups.setdefault(key, []).append(idx)

    indices_to_remove: set[int] = set()
    for key, indices in file_line_groups.items():
        if len(indices) < 2:
            continue
        # Keep the one with highest confidence, merge evidence
        best_idx = max(indices, key=lambda i: result[i].confidence)
        merged_evidence = list(result[best_idx].evidence)
        for other_idx in indices:
            if other_idx != best_idx:
                indices_to_remove.add(other_idx)
                for ev in result[other_idx].evidence:
                    if ev not in merged_evidence:
                        merged_evidence.append(ev)
        result[best_idx] = AuditFinding(
            finding_id=result[best_idx].finding_id,
            auditor=result[best_idx].auditor,
            requirement_id=result[best_idx].requirement_id,
            verdict=result[best_idx].verdict,
            severity=result[best_idx].severity,
            summary=result[best_idx].summary,
            evidence=merged_evidence,
            remediation=result[best_idx].remediation,
            confidence=result[best_idx].confidence,
            source=result[best_idx].source,
        )

    if indices_to_remove:
        result = [f for i, f in enumerate(result) if i not in indices_to_remove]

    return result


def build_report(
    audit_id: str,
    cycle: int,
    auditors_deployed: list[str],
    findings: list[AuditFinding],
    healthy_threshold: float = 90.0,
    degraded_threshold: float = 70.0,
    scope: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> AuditReport:
    """Build a complete AuditReport from findings.

    Deduplicates findings, computes score, and builds grouped indices.
    ``scope`` records the milestone-scoping context the audit ran under
    (C-01 milestone audit scoping) — passthrough to ``AuditReport.scope``.
    """
    deduped = deduplicate_findings(findings)
    # Cap findings to prevent overwhelming fix dispatch
    if len(deduped) > _MAX_FINDINGS:
        import logging
        logging.getLogger(__name__).warning(
            "Findings capped: %d -> %d (sorted by severity)",
            len(deduped), _MAX_FINDINGS,
        )
        deduped.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))
        deduped = deduped[:_MAX_FINDINGS]
    score = AuditScore.compute(deduped, healthy_threshold, degraded_threshold)

    by_severity: dict[str, list[int]] = {}
    by_file: dict[str, list[int]] = {}
    by_requirement: dict[str, list[int]] = {}
    fix_candidates: list[int] = []

    fix_severities = {"CRITICAL", "HIGH", "MEDIUM"}

    for i, f in enumerate(deduped):
        by_severity.setdefault(f.severity, []).append(i)
        pf = f.primary_file
        if pf:
            by_file.setdefault(pf, []).append(i)
        by_requirement.setdefault(f.requirement_id, []).append(i)
        if f.severity in fix_severities and f.verdict in ("FAIL", "PARTIAL"):
            fix_candidates.append(i)

    report = AuditReport(
        audit_id=audit_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        cycle=cycle,
        auditors_deployed=auditors_deployed,
        findings=deduped,
        score=score,
        by_severity=by_severity,
        by_file=by_file,
        by_requirement=by_requirement,
        fix_candidates=fix_candidates,
        scope=dict(scope) if scope else {},
    )
    if extras:
        report.extras = dict(extras)
    return report


def group_findings_into_fix_tasks(
    report: AuditReport,
    max_findings_per_task: int = 5,
) -> list[FixTask]:
    """Group fix candidates into FixTasks by primary file.

    Each FixTask targets a single file group. If a file has more than
    *max_findings_per_task* findings, it is split into multiple tasks
    ordered by severity.
    """
    if not report.fix_candidates:
        return []

    # Group candidate findings by primary file
    file_groups: dict[str, list[AuditFinding]] = {}
    for idx in report.fix_candidates:
        f = report.findings[idx]
        pf = f.primary_file or "__unknown__"
        file_groups.setdefault(pf, []).append(f)

    tasks: list[FixTask] = []
    for filepath, group in file_groups.items():
        # Sort by severity (CRITICAL first)
        group.sort(key=lambda x: _SEVERITY_ORDER.get(x.severity, 99))

        # Split into chunks of max_findings_per_task
        for chunk_start in range(0, len(group), max_findings_per_task):
            chunk = group[chunk_start:chunk_start + max_findings_per_task]
            target_files = [filepath]
            # Add related files from evidence
            for f in chunk:
                for ev in f.evidence:
                    ev_file, _, _ = parse_evidence_entry(ev)
                    if ev_file and ev_file not in target_files:
                        target_files.append(ev_file)
            priority = chunk[0].severity  # highest severity in chunk
            tasks.append(FixTask(
                target_files=target_files,
                findings=chunk,
                priority=priority,
            ))

    # Sort tasks by priority
    tasks.sort(key=lambda t: t.priority_order)
    return tasks


def compute_reaudit_scope(
    modified_files: list[str],
    original_findings: list[AuditFinding],
) -> list[str]:
    """Determine which auditors need to re-run based on modified files.

    Maps modified files back to the original findings that targeted them,
    then returns the set of auditor names that need to re-run.
    The test auditor always re-runs.
    """
    affected_auditors: set[str] = set()

    for f in original_findings:
        if f.verdict == "PASS":
            continue
        pf = f.primary_file
        if pf and pf in modified_files:
            affected_auditors.add(f.auditor)

    # Test auditor always re-runs after fixes
    affected_auditors.add("test")

    return sorted(affected_auditors)


def detect_fix_conflicts(tasks: list[FixTask]) -> list[tuple[int, int]]:
    """Detect conflicting fix tasks that share target files.

    Returns pairs of task indices that must be serialized (not run in parallel).
    Uses a reverse index for O(n*m) performance instead of O(n^2).
    """
    # Build reverse index: file -> set of task indices
    file_to_tasks: dict[str, list[int]] = {}
    for i, task in enumerate(tasks):
        for f in task.target_files:
            file_to_tasks.setdefault(f, []).append(i)

    # Conflicts = any file shared by 2+ tasks
    conflict_set: set[tuple[int, int]] = set()
    for indices in file_to_tasks.values():
        if len(indices) < 2:
            continue
        for a_idx in range(len(indices)):
            for b_idx in range(a_idx + 1, len(indices)):
                pair = (indices[a_idx], indices[b_idx])
                conflict_set.add(pair)

    return sorted(conflict_set)
