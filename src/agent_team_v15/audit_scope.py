"""C-01: milestone-scoped audit prompts + scope_violation category.

Pairs with A-09 (wave-prompt scope). Where A-09 stops the builder from
over-producing later-milestone content, C-01 stops the auditor from
penalising the current milestone for content that shouldn't exist yet.

Public API:
    - :class:`AuditScope` — what's in-scope for the current milestone's
      audit cycle.
    - :func:`audit_scope_for_milestone` — factory from MASTER_PLAN +
      REQUIREMENTS.md.
    - :func:`build_scoped_audit_prompt` — prepends the audit prompt with
      a scope block that restricts the evaluation target.
    - :func:`partition_findings_by_scope` — splits a flat finding list
      into in-scope vs out-of-scope.
    - :func:`scope_violation_findings` — consolidates out-of-scope
      findings into one HIGH-severity ``INFO`` verdict per directory so
      they do not deduct score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .audit_models import AuditFinding, parse_evidence_entry
from .milestone_scope import (
    MilestoneScope,
    build_scope_for_milestone,
    file_matches_any_glob,
)


@dataclass
class AuditScope:
    """What the auditor is allowed to evaluate for a given milestone.

    Distinct from :class:`MilestoneScope` (which governs the *builder*
    side) because the auditor also needs a concise summary of earlier
    milestones' outputs so it knows what it may trust (e.g. M3 audit
    knows the M2 User/Auth module exists and was verified in M2's
    audit cycle).
    """

    milestone_id: str
    allowed_file_globs: list[str] = field(default_factory=list)
    allowed_feature_refs: list[str] = field(default_factory=list)
    allowed_ac_refs: list[str] = field(default_factory=list)
    description: str = ""
    parent_milestones_summary: str = ""

    @classmethod
    def from_milestone_scope(
        cls,
        milestone_scope: MilestoneScope,
        parent_milestones_summary: str = "",
    ) -> "AuditScope":
        return cls(
            milestone_id=milestone_scope.milestone_id,
            allowed_file_globs=list(milestone_scope.allowed_file_globs),
            allowed_feature_refs=list(milestone_scope.allowed_feature_refs),
            allowed_ac_refs=list(milestone_scope.allowed_ac_refs),
            description=milestone_scope.description,
            parent_milestones_summary=parent_milestones_summary,
        )


@dataclass
class ScopePartition:
    in_scope: list[AuditFinding] = field(default_factory=list)
    out_of_scope: list[AuditFinding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def audit_scope_for_milestone(
    *,
    master_plan: Any,
    milestone_id: str,
    requirements_md_path: str | Path,
    parent_milestones_summary: str = "",
) -> AuditScope:
    """Build an :class:`AuditScope` from the same sources as the builder side.

    Parent-milestones summary is an optional freeform note the caller
    can pass (e.g. "M2 delivered User + Auth modules — treat as
    verified by M2 audit; do not re-audit under M3 scope").
    """
    milestone_scope = build_scope_for_milestone(
        master_plan=master_plan,
        milestone_id=milestone_id,
        requirements_md_path=requirements_md_path,
    )
    return AuditScope.from_milestone_scope(
        milestone_scope,
        parent_milestones_summary=parent_milestones_summary,
    )


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


_AUDIT_SCOPE_PREAMBLE_TEMPLATE = """\
## Audit Scope — {milestone_id}

You are auditing milestone **{milestone_id}** ONLY. Do NOT penalise this
milestone for missing or incomplete content that belongs to later
milestones per the phased build plan.

### Milestone description
{description}

### Evaluation target — inspect ONLY files matching these patterns
{allowed_globs_block}

### Allowed feature / AC references
{allowed_refs_block}

### Parent milestones (trusted output)
{parent_summary_block}

### Scope enforcement rules
- Any audit finding whose file path is outside the evaluation target
  above is a SCOPE VIOLATION, not an in-scope FAIL. The wave pipeline's
  scope_filter is the structural fix; your job here is to NOT deduct
  score for out-of-scope files — report one consolidated
  ``scope_violation`` finding per directory with severity HIGH and
  verdict INFO.
- Features/ACs from later milestones are deferred by design. Do not
  open findings demanding them in this cycle.

---

"""


def build_scoped_audit_prompt(base_prompt: str, scope: AuditScope) -> str:
    """Prepend *base_prompt* with the milestone-scoped audit preamble."""
    if not scope or not scope.milestone_id:
        return base_prompt

    allowed_globs_block = _format_bullets(
        scope.allowed_file_globs,
        default="(no globs declared — treat the milestone as empty-scope)",
    )
    allowed_refs = list(scope.allowed_feature_refs) + list(scope.allowed_ac_refs)
    allowed_refs_block = _format_bullets(
        allowed_refs,
        default="(none — infrastructure-only milestone)",
    )
    parent_summary_block = scope.parent_milestones_summary.strip() or (
        "(no parent milestones — this is the first phase of the build)"
    )

    preamble = _AUDIT_SCOPE_PREAMBLE_TEMPLATE.format(
        milestone_id=scope.milestone_id,
        description=scope.description or "(no description provided)",
        allowed_globs_block=allowed_globs_block,
        allowed_refs_block=allowed_refs_block,
        parent_summary_block=parent_summary_block,
    )
    return preamble + base_prompt


def build_scoped_audit_prompt_if_enabled(
    base_prompt: str,
    scope: AuditScope | None,
    config: Any,
) -> str:
    """Apply scope preamble only when the v18 feature flag is on."""
    if scope is None:
        return base_prompt
    flag = True
    try:
        flag = bool(getattr(getattr(config, "v18", None), "audit_milestone_scoping", True))
    except Exception:
        flag = True
    if not flag:
        return base_prompt
    return build_scoped_audit_prompt(base_prompt, scope)


# ---------------------------------------------------------------------------
# Finding partitioning + scope_violation consolidation
# ---------------------------------------------------------------------------


def partition_findings_by_scope(
    findings: Iterable[AuditFinding],
    scope: AuditScope,
) -> ScopePartition:
    """Split *findings* into in-scope vs out-of-scope by primary file path."""
    part = ScopePartition()
    globs = scope.allowed_file_globs
    for f in findings:
        path = _primary_file(f)
        # Findings without any file path attach to the milestone (treat
        # as in-scope so general-requirements findings are not dropped).
        if not path:
            part.in_scope.append(f)
            continue
        if file_matches_any_glob(path, globs):
            part.in_scope.append(f)
        else:
            part.out_of_scope.append(f)
    return part


def scope_violation_findings(
    out_of_scope: Iterable[AuditFinding],
    scope: AuditScope,
) -> list[AuditFinding]:
    """Consolidate out-of-scope findings into one per directory.

    Output findings:
      - severity ``HIGH`` (visible to ops, but...)
      - verdict ``INFO`` (no pass/fail scoring impact — see AuditScore.compute)
      - requirement_id ``GENERAL`` so the scorer's per-requirement dedup
        does not collapse them under unrelated reqs.
    """
    groups: dict[str, list[str]] = {}
    for f in out_of_scope:
        path = _primary_file(f) or "(unknown path)"
        parent = _parent_dir(path)
        groups.setdefault(parent, []).append(path)

    consolidated: list[AuditFinding] = []
    for idx, (directory, files) in enumerate(sorted(groups.items())):
        dedup = sorted(set(files))
        sample = ", ".join(dedup[:5])
        if len(dedup) > 5:
            sample += f", ... (+{len(dedup) - 5} more)"
        consolidated.append(
            AuditFinding(
                finding_id=f"SCOPE-VIOL-{idx+1:03d}",
                auditor="scope_validator",
                requirement_id="GENERAL",
                verdict="INFO",
                severity="HIGH",
                summary=(
                    f"Files present in {directory!r} are outside milestone "
                    f"{scope.milestone_id} scope (not a score deduction — see A-09)."
                ),
                evidence=[f"{p}:0 -- out-of-scope for {scope.milestone_id}" for p in dedup],
                remediation=(
                    "These files belong to a later milestone. The wave scope "
                    "filter (A-09) prevents their generation going forward; "
                    "this finding is an INFO-only consolidation."
                ),
                confidence=1.0,
                source="deterministic",
            )
        )
    return consolidated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _primary_file(finding: AuditFinding) -> str:
    if finding.evidence:
        path, _, _ = parse_evidence_entry(finding.evidence[0])
        return path
    return ""


def _parent_dir(path: str) -> str:
    norm = path.replace("\\", "/").strip()
    if "/" not in norm:
        return "."
    return norm.rsplit("/", 1)[0]


def _format_bullets(items: Iterable[str], default: str) -> str:
    entries = [s for s in (str(i).strip() for i in items) if s]
    if not entries:
        return f"- {default}"
    return "\n".join(f"- {e}" for e in entries)


__all__ = [
    "AuditScope",
    "ScopePartition",
    "audit_scope_for_milestone",
    "build_scoped_audit_prompt",
    "build_scoped_audit_prompt_if_enabled",
    "partition_findings_by_scope",
    "scope_violation_findings",
]
