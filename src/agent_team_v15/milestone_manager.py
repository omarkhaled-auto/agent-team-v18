"""Milestone management for PRD-mode orchestration.

Provides MASTER_PLAN.md parsing, context building, rollup health
computation, and per-milestone health checking / cross-milestone wiring
analysis.

The per-milestone orchestration loop in ``cli._run_prd_milestones()``
uses these utilities to decompose PRDs into milestones and execute
each milestone in a fresh orchestrator session with scoped context.
Only activated when MASTER_PLAN.md exists **and**
``config.milestone.enabled`` is True.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .state import ConvergenceReport

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MASTER_PLAN.md dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MasterPlanMilestone:
    """A single milestone entry parsed from MASTER_PLAN.md."""

    id: str  # e.g. "milestone-1"
    title: str
    status: str = "PENDING"  # PENDING | IN_PROGRESS | COMPLETE | FAILED
    dependencies: list[str] = field(default_factory=list)
    description: str = ""
    template: str = "full_stack"
    parallel_group: str = ""
    merge_surfaces: list[str] = field(default_factory=list)
    feature_refs: list[str] = field(default_factory=list)
    ac_refs: list[str] = field(default_factory=list)
    stack_target: str = ""
    complexity_estimate: dict[str, Any] = field(default_factory=dict)


@dataclass
class MasterPlan:
    """The full milestone plan parsed from MASTER_PLAN.md."""

    title: str = ""
    generated: str = ""
    milestones: list[MasterPlanMilestone] = field(default_factory=list)

    def all_complete(self) -> bool:
        """Return True when every milestone is COMPLETE."""
        return bool(self.milestones) and all(
            m.status == "COMPLETE" for m in self.milestones
        )

    def get_ready_milestones(self) -> list[MasterPlanMilestone]:
        """Return milestones whose dependencies are all COMPLETE and that are PENDING."""
        completed_ids = {m.id for m in self.milestones if m.status == "COMPLETE"}
        return [
            m
            for m in self.milestones
            if m.status == "PENDING"
            and all(dep in completed_ids for dep in m.dependencies)
        ]

    def get_milestone(self, milestone_id: str) -> MasterPlanMilestone | None:
        """Look up a milestone by ID."""
        for m in self.milestones:
            if m.id == milestone_id:
                return m
        return None


@dataclass
class MilestoneContext:
    """Scoped context fed to the orchestrator for a single milestone."""

    milestone_id: str
    title: str
    requirements_path: str  # path to this milestone's REQUIREMENTS.md
    predecessor_summaries: list[MilestoneCompletionSummary] = field(
        default_factory=list
    )


@dataclass
class EndpointSummary:
    """Compact summary of a single API endpoint for cross-milestone handoff."""
    path: str           # e.g. "/api/v1/users"
    method: str         # e.g. "GET"
    response_fields: list[str] = field(default_factory=list)  # e.g. ["id", "email", "first_name"]
    request_fields: list[str] = field(default_factory=list)   # e.g. ["email", "password"]
    request_params: list[str] = field(default_factory=list)   # e.g. ["id"] (path/query params)
    response_type: str = ""  # e.g. "WorkOrderResponseDto"


@dataclass
class ModelSummary:
    """Compact summary of a data model (e.g. Prisma) for cross-milestone handoff."""
    name: str           # e.g. "WorkOrder"
    fields: list[dict[str, Any]] = field(default_factory=list)
    # Each field dict: {"name": str, "type": str, "nullable": bool}


@dataclass
class EnumSummary:
    """Compact summary of an enum for cross-milestone handoff."""
    name: str           # e.g. "WorkOrderStatus"
    values: list[str] = field(default_factory=list)  # e.g. ["OPEN", "ASSIGNED", "COMPLETED"]


@dataclass
class MilestoneCompletionSummary:
    """Compressed summary of a completed milestone (~100-200 tokens)."""

    milestone_id: str
    title: str
    exported_files: list[str] = field(default_factory=list)
    exported_symbols: list[str] = field(default_factory=list)
    summary_line: str = ""
    # NEW: API endpoint data for frontend milestones
    api_endpoints: list[EndpointSummary] = field(default_factory=list)
    # NEW: Detected field naming convention ("snake_case" or "camelCase" or "")
    field_naming_convention: str = ""
    # NEW: Backend source file paths that frontend milestones can read
    backend_source_files: list[str] = field(default_factory=list)
    # Data model definitions (e.g. Prisma models) for cross-milestone handoff
    models: list[ModelSummary] = field(default_factory=list)
    # Enum definitions for cross-milestone handoff
    enums: list[EnumSummary] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MASTER_PLAN.md parsing regexes
# ---------------------------------------------------------------------------

_RE_MILESTONE_HEADER = re.compile(
    r"^#{2,4}\s+(?:Milestone\s+)?(\d+)[.:]?\s*(.*)", re.MULTILINE
)
_RE_FIELD = re.compile(r"^-\s*([A-Za-z][\w\s-]*):\s*(.+)", re.MULTILINE)
_RE_PLAN_TITLE = re.compile(r"^#\s+(?:MASTER\s+PLAN:\s*)?(.+)", re.MULTILINE)
_RE_GENERATED = re.compile(r"Generated:\s*(.+)", re.IGNORECASE)


def _normalize_field_key(key: str) -> str:
    return re.sub(r"[\s\-]+", "_", key.strip().lower())


def _parse_list_field(raw: str) -> list[str]:
    if not raw:
        return []
    if raw.strip().lower() in {"none", "n/a", "-", "[]"}:
        return []
    items: list[str] = []
    for chunk in re.split(r"[,\n;|]+", raw):
        value = chunk.strip()
        if not value:
            continue
        if value.startswith("- "):
            value = value[2:].strip()
        if value:
            items.append(value)
    return items


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null", "n/a"}:
        return None
    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except ValueError:
            return raw
    if re.fullmatch(r"-?\d+\.\d+", raw):
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def _parse_complexity_estimate(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    cleaned = raw.strip()
    if cleaned.lower() in {"none", "n/a", "-", "{}"}:
        return {}
    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
    parsed: dict[str, Any] = {}
    for chunk in re.split(r"[,\n;]+", cleaned):
        item = chunk.strip()
        if not item:
            continue
        match = re.match(r"([^:=]+?)\s*[:=]\s*(.+)", item)
        if not match:
            continue
        key = match.group(1).strip()
        if not key:
            continue
        parsed[key] = _parse_scalar(match.group(2))
    return parsed


# ---------------------------------------------------------------------------
# MASTER_PLAN.md parsing
# ---------------------------------------------------------------------------


def parse_master_plan(content: str) -> MasterPlan:
    """Parse a MASTER_PLAN.md string into a :class:`MasterPlan`.

    The parser is fault-tolerant: handles ``## Milestone N:``,
    ``## N.``, status case variations, and missing fields.
    """
    plan = MasterPlan()

    title_m = _RE_PLAN_TITLE.search(content)
    if title_m:
        plan.title = title_m.group(1).strip()

    gen_m = _RE_GENERATED.search(content)
    if gen_m:
        plan.generated = gen_m.group(1).strip()

    # Split at milestone headers
    splits = list(_RE_MILESTONE_HEADER.finditer(content))
    for idx, match in enumerate(splits):
        num = match.group(1)
        title = match.group(2).strip()

        # Determine the block (text until the next milestone header)
        start = match.end()
        end = splits[idx + 1].start() if idx + 1 < len(splits) else len(content)
        block = content[start:end]

        # Extract structured fields from the block
        fields: dict[str, str] = {}
        for fm in _RE_FIELD.finditer(block):
            key = _normalize_field_key(fm.group(1))
            fields[key] = fm.group(2).strip()

        milestone_id = fields.get("id", f"milestone-{num}")
        status = fields.get("status", "PENDING").upper()
        deps_raw = fields.get("dependencies", "")
        deps = _parse_deps(deps_raw)
        description = fields.get("description", "")
        template = fields.get("template", "full_stack")
        parallel_group = fields.get("parallel_group", "")
        merge_surfaces = _parse_list_field(fields.get("merge_surfaces", ""))
        feature_refs = _parse_list_field(fields.get("feature_refs", fields.get("features", "")))
        ac_refs = _parse_list_field(fields.get("ac_refs", ""))
        stack_target = fields.get("stack_target", "")
        complexity_estimate = _parse_complexity_estimate(fields.get("complexity_estimate", ""))

        plan.milestones.append(
            MasterPlanMilestone(
                id=milestone_id,
                title=title,
                status=status,
                dependencies=deps,
                description=description,
                template=template,
                parallel_group=parallel_group,
                merge_surfaces=merge_surfaces,
                feature_refs=feature_refs,
                ac_refs=ac_refs,
                stack_target=stack_target,
                complexity_estimate=complexity_estimate,
            )
        )

    return plan


def _milestone_to_json_dict(milestone: Any) -> dict[str, Any]:
    """Serialise a milestone to a JSON-safe dict.

    Uses ``getattr`` with defaults so duck-typed or pre-V18.1 mock objects
    (e.g. ``types.SimpleNamespace`` used in tests) don't raise when V18.1
    fields are missing.
    """

    return {
        "id": getattr(milestone, "id", ""),
        "title": getattr(milestone, "title", ""),
        "status": getattr(milestone, "status", "PENDING"),
        "dependencies": list(getattr(milestone, "dependencies", []) or []),
        "description": getattr(milestone, "description", ""),
        "template": getattr(milestone, "template", "full_stack") or "full_stack",
        "parallel_group": getattr(milestone, "parallel_group", "") or "",
        "merge_surfaces": list(getattr(milestone, "merge_surfaces", []) or []),
        "feature_refs": list(getattr(milestone, "feature_refs", []) or []),
        "ac_refs": list(getattr(milestone, "ac_refs", []) or []),
        "stack_target": getattr(milestone, "stack_target", "") or "",
        "complexity_estimate": dict(getattr(milestone, "complexity_estimate", {}) or {}),
    }


def generate_master_plan_json(
    milestones: list[MasterPlanMilestone],
    output_path: Path,
) -> None:
    """Write MASTER_PLAN.json as a canonical machine-readable format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "generated": datetime.now().isoformat(),
        "milestones": [_milestone_to_json_dict(m) for m in milestones],
    }
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# V18.1: Plan validation + deterministic topological execution order
# ---------------------------------------------------------------------------


@dataclass
class PlanValidationResult:
    """Outcome of :func:`validate_plan`.

    ``errors`` are fatal (raise at the call site). ``warnings`` are advisory
    and should be logged but allow execution to proceed.
    """

    valid: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_AC_MIN_RECOMMENDED = 3
_AC_MAX_RECOMMENDED = 13
_DEP_DEPTH_MAX_RECOMMENDED = 4


def validate_plan(milestones: list[MasterPlanMilestone]) -> PlanValidationResult:
    """Validate the milestone DAG after parsing.

    Checks performed:

    1. All dependency references resolve to existing milestone IDs.
    2. No circular dependencies (cycles would deadlock DAG execution).
    3. Max dependency depth ≤ 4 (design reference Section 2.6 — advisory).
    4. AC sizing: warn when <3 (excluding 0 = foundation) or >13 ACs.
    5. At least one root milestone (no dependencies).

    Errors are fatal — the caller should raise. Warnings are advisory.
    """

    result = PlanValidationResult()
    milestone_ids = {m.id for m in milestones}
    by_id: dict[str, MasterPlanMilestone] = {m.id: m for m in milestones}

    # 1. Unresolved dependency references
    for m in milestones:
        for dep in m.dependencies:
            if dep not in milestone_ids:
                result.errors.append(
                    f"{m.id}: depends on '{dep}' which does not exist"
                )
                result.valid = False

    # 2. Circular dependency detection via DFS
    visited: set[str] = set()
    in_stack: set[str] = set()
    cycles_found: list[list[str]] = []

    def _dfs(mid: str, path: list[str]) -> None:
        if mid in in_stack:
            # Cycle closes at mid; extract the sub-path forming the cycle
            try:
                cycle_start = path.index(mid)
            except ValueError:
                cycle_start = 0
            cycles_found.append(path[cycle_start:] + [mid])
            return
        if mid in visited:
            return
        visited.add(mid)
        in_stack.add(mid)
        ms = by_id.get(mid)
        if ms is not None:
            for dep in ms.dependencies:
                if dep in milestone_ids:
                    _dfs(dep, path + [mid])
        in_stack.discard(mid)

    for m in milestones:
        if m.id not in visited:
            _dfs(m.id, [])

    # Deduplicate cycles by their canonical signature
    seen_cycles: set[tuple[str, ...]] = set()
    for cycle in cycles_found:
        if len(cycle) < 2:
            continue
        # Normalize cycle to start at its lexicographically smallest node
        min_index = cycle.index(min(cycle[:-1]))
        rotated = cycle[min_index:-1] + cycle[:min_index] + [cycle[min_index]]
        signature = tuple(rotated)
        if signature in seen_cycles:
            continue
        seen_cycles.add(signature)
        result.errors.append(
            f"Circular dependency detected: {' → '.join(rotated)}"
        )
        result.valid = False

    # 3. Max dependency depth — memoized DFS that tolerates cycles
    depth_cache: dict[str, int] = {}
    on_path: set[str] = set()

    def _depth(mid: str) -> int:
        if mid in depth_cache:
            return depth_cache[mid]
        if mid in on_path:
            # Cycle — treat as depth 0 to avoid infinite recursion
            return 0
        ms = by_id.get(mid)
        if ms is None or not ms.dependencies:
            depth_cache[mid] = 0
            return 0
        on_path.add(mid)
        max_dep = 0
        for dep in ms.dependencies:
            if dep in milestone_ids:
                max_dep = max(max_dep, _depth(dep) + 1)
        on_path.discard(mid)
        depth_cache[mid] = max_dep
        return max_dep

    # Only walk depth if no cycles; cycle presence already produced a fatal error
    if not cycles_found:
        for m in milestones:
            d = _depth(m.id)
            if d > _DEP_DEPTH_MAX_RECOMMENDED:
                result.warnings.append(
                    f"{m.id}: dependency depth {d} exceeds recommended max of "
                    f"{_DEP_DEPTH_MAX_RECOMMENDED}"
                )

    # 4. AC sizing validation (0 ACs = foundation milestone — allowed)
    for m in milestones:
        ac_count = len(m.ac_refs) if m.ac_refs else 0
        if ac_count == 0:
            continue
        if ac_count < _AC_MIN_RECOMMENDED:
            result.warnings.append(
                f"{m.id}: only {ac_count} ACs (minimum recommended: "
                f"{_AC_MIN_RECOMMENDED}). Consider combining with a related feature."
            )
        if ac_count > _AC_MAX_RECOMMENDED:
            result.warnings.append(
                f"{m.id}: {ac_count} ACs (maximum recommended: "
                f"{_AC_MAX_RECOMMENDED}). Consider splitting into sub-features."
            )

    # 5. At least one root milestone
    if milestones:
        roots = [m for m in milestones if not m.dependencies]
        if not roots:
            result.errors.append(
                "No root milestone found (all milestones have dependencies). "
                "At least one foundation milestone must have no dependencies."
            )
            result.valid = False

    return result


def compute_execution_order(milestones: list[MasterPlanMilestone]) -> list[str]:
    """Compute the deterministic topological execution order.

    Returns milestone IDs in the order they should execute. Within the same
    dependency tier, IDs are sorted lexicographically for determinism, so the
    same plan always yields the same order.

    This is the canonical execution order for sequential DAG builds. Callers
    should log the result at build start so the user knows the upcoming order.
    Unreachable milestones (e.g. part of an orphaned cycle) are appended at
    the end in ID order with an error log, so the caller never silently skips
    work — but :func:`validate_plan` should have already caught those cases.
    """

    by_id: dict[str, MasterPlanMilestone] = {m.id: m for m in milestones}
    remaining: dict[str, MasterPlanMilestone] = dict(by_id)
    completed: set[str] = set()
    order: list[str] = []
    all_ids = set(by_id.keys())

    while remaining:
        ready = [
            mid
            for mid, m in remaining.items()
            if all((d in completed) or (d not in all_ids) for d in m.dependencies)
        ]

        if not ready:
            # DAG stalled — validate_plan should have prevented this. Defensive
            # fallback so we never silently hang: log and append in ID order.
            _logger.error(
                "DAG stall in compute_execution_order: %s have unmet deps. "
                "Completed: %s. Forcing ID order.",
                sorted(remaining.keys()),
                sorted(completed),
            )
            ready = sorted(remaining.keys())

        # Sort within tier for determinism
        ready.sort()

        for mid in ready:
            order.append(mid)
            completed.add(mid)
            del remaining[mid]

    return order


# ---------------------------------------------------------------------------
# V18.1: JSON canonical format — load, status update, MD sidecar regeneration
# ---------------------------------------------------------------------------


def _plan_json_path(cwd: str | Path) -> Path:
    return Path(cwd) / ".agent-team" / "MASTER_PLAN.json"


def _plan_md_path(cwd: str | Path) -> Path:
    return Path(cwd) / ".agent-team" / "MASTER_PLAN.md"


def load_master_plan_json(cwd: str | Path) -> MasterPlan:
    """Load the milestone plan from MASTER_PLAN.json (canonical source).

    Falls back to parsing MASTER_PLAN.md if JSON does not exist (backward
    compat for pre-V18.1 builds) — and in that case eagerly writes the JSON
    sidecar so future reads use the canonical format.
    """

    json_path = _plan_json_path(cwd)
    md_path = _plan_md_path(cwd)

    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"Failed to read canonical {json_path}: {exc}"
            ) from exc

        milestones_data = data.get("milestones", []) or []
        milestones: list[MasterPlanMilestone] = []
        for entry in milestones_data:
            if not isinstance(entry, dict):
                continue
            milestones.append(
                MasterPlanMilestone(
                    id=str(entry.get("id", "")),
                    title=str(entry.get("title", "") or ""),
                    status=str(entry.get("status", "PENDING") or "PENDING").upper(),
                    dependencies=list(entry.get("dependencies", []) or []),
                    description=str(entry.get("description", "") or ""),
                    template=str(entry.get("template", "full_stack") or "full_stack"),
                    parallel_group=str(entry.get("parallel_group", "") or ""),
                    merge_surfaces=list(entry.get("merge_surfaces", []) or []),
                    feature_refs=list(entry.get("feature_refs", []) or []),
                    ac_refs=list(entry.get("ac_refs", []) or []),
                    stack_target=str(entry.get("stack_target", "") or ""),
                    complexity_estimate=dict(entry.get("complexity_estimate", {}) or {}),
                )
            )
        plan = MasterPlan(
            title=str(data.get("title", "") or ""),
            generated=str(data.get("generated", "") or ""),
            milestones=milestones,
        )
        return plan

    if md_path.is_file():
        content = md_path.read_text(encoding="utf-8")
        plan = parse_master_plan(content)
        # Eagerly persist JSON so subsequent reads use the canonical format.
        try:
            generate_master_plan_json(plan.milestones, json_path)
        except OSError as exc:
            _logger.warning("Could not write canonical MASTER_PLAN.json: %s", exc)
        return plan

    raise FileNotFoundError(
        f"No MASTER_PLAN.json or MASTER_PLAN.md found under "
        f"{Path(cwd) / '.agent-team'}"
    )


def update_milestone_status_json(
    cwd: str | Path,
    milestone_id: str,
    new_status: str,
) -> bool:
    """Update a milestone's status in the canonical MASTER_PLAN.json.

    Returns ``True`` when the JSON was updated, ``False`` when the file does
    not exist or the milestone ID was not found. Callers should also update
    the .md sidecar via :func:`update_master_plan_status` or regenerate the
    .md via :func:`generate_master_plan_md` to keep them in sync.
    """

    json_path = _plan_json_path(cwd)
    if not json_path.is_file():
        return False
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False

    milestones = data.get("milestones", []) or []
    updated = False
    for m in milestones:
        if isinstance(m, dict) and str(m.get("id", "")) == milestone_id:
            m["status"] = new_status
            updated = True
            break

    if updated:
        try:
            json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            _logger.warning("Failed to persist MASTER_PLAN.json update: %s", exc)
            return False

    return updated


def generate_master_plan_md(cwd: str | Path) -> bool:
    """Regenerate human-readable MASTER_PLAN.md from the canonical JSON.

    Returns ``True`` when the file was written. No-op when the JSON doesn't
    exist. Writes a deterministic layout so downstream diffs stay readable.
    """

    json_path = _plan_json_path(cwd)
    md_path = _plan_md_path(cwd)
    if not json_path.is_file():
        return False
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False

    title = str(data.get("title", "") or "MASTER PLAN")
    lines: list[str] = [f"# {title}", ""]
    generated = data.get("generated")
    if generated:
        lines.append(f"Generated: {generated}")
        lines.append("")

    for m in data.get("milestones", []) or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id", ""))
        heading_title = str(m.get("title", "") or "")
        # Format heading as "## Milestone N: Title" where N is the trailing digits
        match = re.search(r"(\d+)$", mid)
        heading_num = match.group(1) if match else mid
        lines.append(f"## Milestone {heading_num}: {heading_title}".rstrip())
        lines.append(f"- ID: {mid}")
        lines.append(f"- Status: {m.get('status', 'PENDING')}")
        deps = m.get("dependencies") or []
        lines.append(f"- Dependencies: {', '.join(deps) if deps else 'none'}")
        description = str(m.get("description", "") or "")
        if description:
            lines.append(f"- Description: {description}")
        template = str(m.get("template", "") or "")
        if template:
            lines.append(f"- Template: {template}")
        parallel_group = str(m.get("parallel_group", "") or "")
        if parallel_group:
            lines.append(f"- Parallel-Group: {parallel_group}")
        feature_refs = m.get("feature_refs") or []
        if feature_refs:
            lines.append(f"- Features: {', '.join(feature_refs)}")
        ac_refs = m.get("ac_refs") or []
        if ac_refs:
            lines.append(f"- AC-Refs: {', '.join(ac_refs)}")
        merge_surfaces = m.get("merge_surfaces") or []
        if merge_surfaces:
            lines.append(f"- Merge-Surfaces: {', '.join(merge_surfaces)}")
        stack_target = str(m.get("stack_target", "") or "")
        if stack_target:
            lines.append(f"- Stack-Target: {stack_target}")
        complexity = m.get("complexity_estimate") or {}
        if isinstance(complexity, dict) and complexity:
            complexity_str = ", ".join(f"{k}={v}" for k, v in complexity.items())
            lines.append(f"- Complexity-Estimate: {complexity_str}")
        lines.append("")

    try:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        _logger.warning("Failed to write MASTER_PLAN.md sidecar: %s", exc)
        return False
    return True


# ---------------------------------------------------------------------------
# V18.1: Complexity estimate derived from Product IR (not LLM)
# ---------------------------------------------------------------------------


def compute_milestone_complexity(
    milestone: MasterPlanMilestone,
    product_ir: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive a complexity estimate for *milestone* from the Product IR.

    The planner never authors this field — it's computed deterministically
    here. Factors considered:

    - entities referenced by the milestone's feature_refs or whose name
      appears in the description
    - endpoints, state machines, and business rules for those entities
    - whether the milestone template includes a frontend

    Returns a dict with ``entity_count``, ``endpoint_count``,
    ``state_machine_count``, ``business_rule_count``, ``has_frontend``, and
    an ``estimated_loc_range`` string.
    """

    if not product_ir or not isinstance(product_ir, dict):
        return {
            "entity_count": 0,
            "endpoint_count": 0,
            "state_machine_count": 0,
            "business_rule_count": 0,
            "has_frontend": milestone.template in {"full_stack", "frontend_only"},
            "estimated_loc_range": "0-0",
        }

    ir_entities = product_ir.get("entities", []) or []
    ir_endpoints = product_ir.get("endpoints", []) or []
    ir_state_machines = product_ir.get("state_machines", []) or []
    ir_rules = product_ir.get("business_rules", []) or []

    feature_refs = set(milestone.feature_refs or [])
    desc_lower = (milestone.description or "").lower()

    entity_names: set[str] = set()
    for entity in ir_entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name", "") or "")
        if not name:
            continue
        entity_feature_refs = set(entity.get("feature_refs", []) or [])
        if feature_refs and (feature_refs & entity_feature_refs):
            entity_names.add(name)
        elif name.lower() in desc_lower:
            entity_names.add(name)

    def _entity_match_list(items: list[Any], attr: str = "entity") -> int:
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = item.get(attr)
            if isinstance(raw, list):
                for candidate in raw:
                    if candidate in entity_names:
                        count += 1
                        break
            elif isinstance(raw, str) and any(e in raw for e in entity_names):
                count += 1
        return count

    entity_count = len(entity_names)
    endpoint_count = _entity_match_list(ir_endpoints, "entity")
    sm_count = _entity_match_list(ir_state_machines, "entity")
    rule_count = 0
    for rule in ir_rules:
        if not isinstance(rule, dict):
            continue
        rule_entities = rule.get("entities", []) or []
        if any(e in entity_names for e in rule_entities):
            rule_count += 1

    has_frontend = milestone.template in {"full_stack", "frontend_only"}

    base_loc = entity_count * 500 + endpoint_count * 200
    if has_frontend:
        base_loc += endpoint_count * 300
    if sm_count > 0:
        base_loc += sm_count * 400

    low = int(base_loc * 0.7)
    high = int(base_loc * 1.3)

    return {
        "entity_count": entity_count,
        "endpoint_count": endpoint_count,
        "state_machine_count": sm_count,
        "business_rule_count": rule_count,
        "has_frontend": has_frontend,
        "estimated_loc_range": f"{low}-{high}",
    }


def _parse_deps(raw: str) -> list[str]:
    """Parse a dependency string like ``milestone-1, milestone-2`` or ``none``.

    Strips parenthetical comments before splitting so that e.g.
    ``milestone-2 (server-side setup can parallel with milestone-3, milestone-4)``
    is correctly parsed as ``["milestone-2"]`` rather than choking on the commas
    inside the parentheses.

    Also normalises short-form IDs such as ``M1``, ``m2`` to the canonical
    ``milestone-1``, ``milestone-2`` format so that dependency look-ups against
    ``MasterPlanMilestone.id`` never silently fail.
    """
    if not raw or raw.strip().lower() in ("none", "n/a", "-", ""):
        return []
    # Strip parenthetical comments: "(anything)" → ""
    cleaned = re.sub(r"\([^)]*\)", "", raw)
    # Also handle "and" as a separator: "M1 and M2" → "M1, M2"
    cleaned = re.sub(r"\band\b", ",", cleaned, flags=re.IGNORECASE)
    tokens = [tok.strip() for tok in cleaned.split(",") if tok.strip()]
    # Normalise short-form IDs: "M1" / "m2" → "milestone-1" / "milestone-2"
    _short_form = re.compile(r"^[Mm](\d+)$")
    _id_form = re.compile(r"^milestone-\d+$")
    result: list[str] = []
    for tok in tokens:
        m = _short_form.match(tok)
        if m:
            result.append(f"milestone-{m.group(1)}")
        elif _id_form.match(tok):
            result.append(tok)
        else:
            # Drop prose / non-ID tokens (e.g. "- Description: Scaffold
            # monorepo"). Some decomposer outputs put free-text bullets in
            # the Dependencies field; treating those as real dep references
            # makes plan validation fail with "depends on '...' which does
            # not exist" for every bullet. An empty list (foundation
            # milestone) is the correct interpretation when no valid IDs
            # remain.
            _logger.warning(
                "Dropped non-ID dependency token from MASTER_PLAN: %r", tok
            )
    return result


# ---------------------------------------------------------------------------
# MASTER_PLAN.md status updates
# ---------------------------------------------------------------------------


def update_master_plan_status(
    content: str,
    milestone_id: str,
    new_status: str,
) -> str:
    """Update the status of *milestone_id* in the MASTER_PLAN.md content string.

    Returns the updated content.  If the milestone ID is not found the
    content is returned unchanged.
    """
    # Find "- ID: <milestone_id>" then update the nearest Status field
    id_pattern = re.compile(
        rf"-\s*ID:\s*{re.escape(milestone_id)}", re.IGNORECASE
    )
    id_match = id_pattern.search(content)
    if not id_match:
        return content

    # Search for milestone header boundaries using the milestone regex
    # (not raw "## " prefixes) to avoid non-milestone h3/h4 subsections
    _all_headers = list(_RE_MILESTONE_HEADER.finditer(content))

    block_start = 0
    block_end = len(content)
    for i, hdr_match in enumerate(_all_headers):
        if hdr_match.start() <= id_match.start():
            block_start = hdr_match.start()
        elif hdr_match.start() > id_match.start():
            block_end = hdr_match.start()
            break

    block = content[block_start:block_end]
    status_re = re.compile(r"(-\s*Status:\s*)(\w+)", re.IGNORECASE)
    new_block = status_re.sub(rf"\g<1>{new_status}", block, count=1)

    return content[:block_start] + new_block + content[block_end:]


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


def build_milestone_context(
    milestone: MasterPlanMilestone,
    milestones_dir: str | Path,
    predecessor_summaries: list[MilestoneCompletionSummary] | None = None,
) -> MilestoneContext:
    """Build scoped context for a single milestone execution."""
    mdir = Path(milestones_dir) / milestone.id
    return MilestoneContext(
        milestone_id=milestone.id,
        title=milestone.title,
        requirements_path=str(mdir / "REQUIREMENTS.md"),
        predecessor_summaries=predecessor_summaries or [],
    )


def build_completion_summary(
    milestone: MasterPlanMilestone,
    exported_files: list[str] | None = None,
    exported_symbols: list[str] | None = None,
    summary_line: str = "",
) -> MilestoneCompletionSummary:
    """Create a compressed completion summary for a finished milestone."""
    return MilestoneCompletionSummary(
        milestone_id=milestone.id,
        title=milestone.title,
        exported_files=exported_files or [],
        exported_symbols=exported_symbols or [],
        summary_line=summary_line,
    )


_CACHE_FILE = "COMPLETION_CACHE.json"


def save_completion_cache(
    milestones_dir: str,
    milestone_id: str,
    summary: MilestoneCompletionSummary,
) -> None:
    """Persist a completion summary as JSON for fast re-reads."""
    cache_path = Path(milestones_dir) / milestone_id / _CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_completion_cache(
    milestones_dir: str,
    milestone_id: str,
) -> MilestoneCompletionSummary | None:
    """Load a cached completion summary.  Returns ``None`` if not cached."""
    cache_path = Path(milestones_dir) / milestone_id / _CACHE_FILE
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        # Handle nested EndpointSummary objects
        if "api_endpoints" in data and data["api_endpoints"]:
            data["api_endpoints"] = [
                EndpointSummary(**ep) if isinstance(ep, dict) else ep
                for ep in data["api_endpoints"]
            ]
        # Handle nested ModelSummary objects
        if "models" in data and data["models"]:
            data["models"] = [
                ModelSummary(**m) if isinstance(m, dict) else m
                for m in data["models"]
            ]
        # Handle nested EnumSummary objects
        if "enums" in data and data["enums"]:
            data["enums"] = [
                EnumSummary(**e) if isinstance(e, dict) else e
                for e in data["enums"]
            ]
        return MilestoneCompletionSummary(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def render_predecessor_context(
    summaries: list[MilestoneCompletionSummary],
) -> str:
    """Render predecessor summaries into a compact context string.

    Each summary is ~100-200 tokens (more if API endpoints are included).
    Even with 20 completed milestones this adds only ~2000-4000 tokens
    to the orchestrator prompt.
    """
    if not summaries:
        return ""
    lines = ["## Completed Milestones Context\n"]
    for s in summaries:
        lines.append(f"### {s.milestone_id}: {s.title}")
        if s.summary_line:
            lines.append(f"  Summary: {s.summary_line}")
        if s.exported_files:
            lines.append(f"  Files: {', '.join(s.exported_files[:20])}")
        if s.exported_symbols:
            lines.append(f"  Exports: {', '.join(s.exported_symbols[:20])}")
        # NEW: Include field naming convention
        if s.field_naming_convention:
            lines.append(f"  Field Convention: {s.field_naming_convention}")
        # Include API endpoint summaries
        if s.api_endpoints:
            lines.append("  API Endpoints:")
            for ep in s.api_endpoints[:30]:  # Cap at 30 endpoints per milestone
                resp_str = ", ".join(ep.response_fields[:10]) if ep.response_fields else "..."
                type_tag = f" -> {ep.response_type}" if ep.response_type else ""
                params_tag = f" params:[{', '.join(ep.request_params)}]" if ep.request_params else ""
                req_str = ""
                if ep.request_fields:
                    req_str = f" body:[{', '.join(ep.request_fields[:8])}]"
                lines.append(f"    {ep.method} {ep.path}{params_tag}{type_tag} resp:[{resp_str}]{req_str}")
        # Include data models
        if s.models:
            lines.append("  Models:")
            for model in s.models[:15]:  # Cap at 15 models per milestone
                field_parts = []
                for f in model.fields[:12]:
                    nullable = "?" if f.get("nullable") else ""
                    field_parts.append(f"{f.get('name', '')}:{f.get('type', '')}{nullable}")
                lines.append(f"    {model.name}: {{{', '.join(field_parts)}}}")
        # Include enums
        if s.enums:
            lines.append("  Enums:")
            for enum in s.enums[:20]:  # Cap at 20 enums per milestone
                lines.append(f"    {enum.name}: {' | '.join(enum.values[:15])}")
        # Include backend source files for cross-milestone access
        if s.backend_source_files:
            lines.append(f"  Backend Sources (READ these for exact field names): {', '.join(s.backend_source_files[:10])}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rollup health computation
# ---------------------------------------------------------------------------


def compute_rollup_health(
    plan: MasterPlan,
) -> dict[str, Any]:
    """Compute overall health metrics for the milestone plan.

    Returns a dict with counts and a health status string:
    ``"healthy"`` -- all milestones COMPLETE or PENDING with no failures
    ``"degraded"`` -- at least one milestone FAILED but others progressing
    ``"failed"`` -- majority of milestones FAILED
    """
    total = len(plan.milestones)
    if total == 0:
        return {"total": 0, "health": "unknown"}

    counts: dict[str, int] = {
        "PENDING": 0, "IN_PROGRESS": 0, "COMPLETE": 0, "FAILED": 0,
    }
    for m in plan.milestones:
        key = m.status.upper()
        counts[key] = counts.get(key, 0) + 1

    failed = counts.get("FAILED", 0)
    if failed == 0:
        health = "healthy"
    elif failed < total / 2:
        health = "degraded"
    else:
        health = "failed"

    return {
        "total": total,
        "complete": counts.get("COMPLETE", 0),
        "in_progress": counts.get("IN_PROGRESS", 0),
        "pending": counts.get("PENDING", 0),
        "failed": failed,
        "health": health,
    }


def aggregate_milestone_convergence(
    mm: "MilestoneManager",
    min_convergence_ratio: float = 0.9,
    degraded_threshold: float = 0.5,
) -> ConvergenceReport:
    """Aggregate convergence reports from all milestones into a single report.

    Iterates all milestone directories, calls ``check_milestone_health()``
    per milestone, and combines the results into a global
    :class:`ConvergenceReport`.

    Parameters
    ----------
    mm : MilestoneManager
        Manager instance pointing at the project root.
    min_convergence_ratio : float
        Ratio at or above which health is ``"healthy"``.
    degraded_threshold : float
        Ratio at or above which health is ``"degraded"`` when the review
        fleet has been deployed.

    Returns
    -------
    ConvergenceReport
        Aggregated health report across all milestones.
    """
    milestone_ids = mm._list_milestone_ids()
    if not milestone_ids:
        return ConvergenceReport(health="unknown")

    total_checked = 0
    total_requirements = 0
    max_cycles = 0
    all_escalated: list[str] = []
    # M3: Track zero-cycle milestones (Issue #10)
    zero_cycle_milestones: list[str] = []

    for mid in milestone_ids:
        report = mm.check_milestone_health(
            mid,
            min_convergence_ratio=min_convergence_ratio,
            degraded_threshold=degraded_threshold,
        )
        total_checked += report.checked_requirements
        total_requirements += report.total_requirements
        max_cycles = max(max_cycles, report.review_cycles)
        all_escalated.extend(report.escalated_items)
        # M3: Track milestones with requirements but 0 review cycles
        if report.review_cycles == 0 and report.total_requirements > 0:
            zero_cycle_milestones.append(mid)

    ratio = total_checked / total_requirements if total_requirements > 0 else 0.0
    fleet_deployed = max_cycles > 0

    if total_requirements == 0:
        health = "unknown"
    elif ratio >= min_convergence_ratio:
        health = "healthy"
    elif fleet_deployed and ratio >= degraded_threshold:
        health = "degraded"
    else:
        health = "failed"

    return ConvergenceReport(
        total_requirements=total_requirements,
        checked_requirements=total_checked,
        review_cycles=max_cycles,
        convergence_ratio=ratio,
        review_fleet_deployed=fleet_deployed,
        health=health,
        escalated_items=all_escalated,
        zero_cycle_milestones=zero_cycle_milestones,
    )


# ---------------------------------------------------------------------------
# Regex patterns (reuse the review_cycles pattern from config.py)
# ---------------------------------------------------------------------------

_REVIEW_CYCLES_RE = re.compile(r'\(review_cycles:\s*(\d+)\)')
_CHECKED_RE = re.compile(r'^\s*-\s*\[x\]', re.MULTILINE | re.IGNORECASE)
_UNCHECKED_RE = re.compile(r'^\s*-\s*\[ \]', re.MULTILINE)

# Detect import references in REQUIREMENTS.md content.
# Matches patterns like:
#   import { Foo } from "src/services/bar"
#   from src.services.bar import Foo
#   imports Foo from src/services/bar.ts
_IMPORT_REF_RE = re.compile(
    r'(?:'
    r'import\s*\{?\s*(\w+)\s*\}?\s*from\s*["\']([^"\']+)["\']'  # TS/JS style (groups 1-2)
    r'|from\s+([\w./]+)\s+import\s+(\w+)'                        # Python style (groups 3-4)
    r'|imports?\s+(\w+)\s+from\s+([\w./]+)'                       # prose style (groups 5-6)
    r'|require\(\s*["\']'                                          # CommonJS require (groups 7-8)
      r'((?:src|lib|app|server|client|packages|modules)/[\w/.-]+)'
      r'["\']\s*\)(?:\.(\w+))?'
    r'|import\(\s*["\']'                                           # Dynamic import() (groups 9-10)
      r'((?:src|lib|app|server|client|packages|modules)/[\w/.-]+)'
      r'["\']\s*\)(?:\.then\(\s*\w+\s*=>\s*\w+\.(\w+))?'
    r')',
    re.IGNORECASE,
)

# Detect file references in REQUIREMENTS.md content.
# Matches file paths like src/foo/bar.ts, lib/utils.py, etc.
_FILE_REF_RE = re.compile(
    r'(?:^|\s|[`"\'])((?:src|lib|app|server|client|packages|modules)/[\w/.-]+\.(?:py|ts|tsx|js|jsx|go|rs))',
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MilestoneState:
    """Tracks the convergence state of a single milestone."""

    milestone_id: str
    requirements_total: int = 0
    requirements_checked: int = 0
    convergence_cycles: int = 0
    status: str = "pending"  # "pending" | "in_progress" | "converged" | "failed"


@dataclass
class WiringGap:
    """Describes a missing cross-milestone wiring connection.

    Indicates that *target_milestone* references a file or symbol that
    is expected to be produced by *source_milestone*, but the file
    either does not exist or does not export the expected symbol.
    """

    source_milestone: str
    target_milestone: str
    missing_export: str
    expected_in_file: str


def normalize_milestone_dirs(
    project_root: Path,
    requirements_dir: str = ".agent-team",
) -> int:
    """Normalize milestone directory structure.

    The orchestrator may create ``milestone-N/`` directories directly under
    the requirements directory instead of under the ``milestones/`` sub-directory.
    This function detects such "orphan" directories and copies their contents
    into the canonical ``milestones/milestone-N/`` location.

    Parameters
    ----------
    project_root:
        Root directory of the project.
    requirements_dir:
        Name of the requirements directory (default ``.agent-team``).

    Returns
    -------
    int
        Number of directories normalized (copied to canonical location).
    """
    req_dir = project_root / requirements_dir
    if not req_dir.is_dir():
        return 0

    milestones_dir = req_dir / "milestones"
    normalized = 0

    _milestone_pattern = re.compile(r"^milestone-\w+$")

    try:
        entries = list(req_dir.iterdir())
    except OSError:
        return 0

    for entry in entries:
        if not entry.is_dir():
            continue
        if not _milestone_pattern.match(entry.name):
            continue
        # Skip the "milestones" directory itself
        if entry.name == "milestones":
            continue

        target = milestones_dir / entry.name
        if not target.exists():
            milestones_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copytree(str(entry), str(target))
                normalized += 1
            except (OSError, shutil.Error):
                pass  # Best-effort copy
        else:
            # Merge: copy files that don't already exist in target
            try:
                for src_file in entry.rglob("*"):
                    if src_file.is_file():
                        rel = src_file.relative_to(entry)
                        dest_file = target / rel
                        if not dest_file.exists():
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(src_file), str(dest_file))
                            normalized += 1
            except (OSError, shutil.Error):
                pass  # Best-effort merge

    return normalized


# ---------------------------------------------------------------------------
# MilestoneManager
# ---------------------------------------------------------------------------

class MilestoneManager:
    """Monitor milestone health and detect cross-milestone wiring gaps.

    Parameters
    ----------
    project_root : Path
        Root directory of the project.  Milestone requirements are
        expected at ``{project_root}/.agent-team/milestones/{id}/REQUIREMENTS.md``.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _milestones_dir(self) -> Path:
        """Return the base directory containing all milestone sub-directories."""
        return self.project_root / ".agent-team" / "milestones"

    def _read_requirements(self, milestone_id: str) -> str | None:
        """Read the REQUIREMENTS.md for *milestone_id*.

        Returns ``None`` when the file does not exist or cannot be read.
        """
        path = self._milestones_dir / milestone_id / "REQUIREMENTS.md"
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, PermissionError):
            return None

    def _list_milestone_ids(self) -> list[str]:
        """Return sorted list of milestone directory names."""
        milestones_dir = self._milestones_dir
        if not milestones_dir.is_dir():
            return []
        return sorted(
            d.name
            for d in milestones_dir.iterdir()
            if d.is_dir() and (d / "REQUIREMENTS.md").is_file()
        )

    @staticmethod
    def _parse_requirements_counts(content: str) -> tuple[int, int]:
        """Parse checked and total requirement counts from REQUIREMENTS.md.

        Returns
        -------
        tuple[int, int]
            ``(checked, total)`` counts.
        """
        checked = len(_CHECKED_RE.findall(content))
        unchecked = len(_UNCHECKED_RE.findall(content))
        return checked, checked + unchecked

    @staticmethod
    def _parse_max_review_cycles(content: str) -> int:
        """Parse the maximum ``review_cycles`` value from content.

        Uses the same regex pattern as :func:`config.parse_max_review_cycles`.
        """
        matches = _REVIEW_CYCLES_RE.findall(content)
        return max((int(m) for m in matches), default=0)

    @staticmethod
    def _extract_import_references(content: str) -> list[tuple[str, str]]:
        """Extract ``(symbol, file_path)`` pairs from REQUIREMENTS.md content.

        Scans for import-like references in the requirements document that
        indicate cross-module dependencies.

        Returns
        -------
        list[tuple[str, str]]
            Each tuple is ``(symbol_name, file_path)``.
        """
        refs: list[tuple[str, str]] = []
        for match in _IMPORT_REF_RE.finditer(content):
            g = match.groups()
            # TS/JS style: group(1)=symbol, group(2)=path
            if g[0] and g[1]:
                refs.append((g[0], g[1]))
            # Python style: group(3)=module_path, group(4)=symbol
            elif g[2] and g[3]:
                refs.append((g[3], g[2]))
            # Prose style: group(5)=symbol, group(6)=path
            elif g[4] and g[5]:
                refs.append((g[4], g[5]))
            # CommonJS require: group(7)=path, group(8)=symbol (optional)
            elif g[6]:
                symbol = g[7] if g[7] else ""
                refs.append((symbol, g[6]))
            # Dynamic import(): group(9)=path, group(10)=symbol (optional)
            elif g[8]:
                symbol = g[9] if g[9] else ""
                refs.append((symbol, g[8]))
        return refs

    @staticmethod
    def _extract_file_references(content: str) -> list[str]:
        """Extract file path references from REQUIREMENTS.md content.

        Returns
        -------
        list[str]
            Unique file paths found in the content.
        """
        return list(dict.fromkeys(_FILE_REF_RE.findall(content)))

    def _collect_milestone_files(self, milestone_id: str) -> set[str]:
        """Collect all file paths referenced in a milestone's REQUIREMENTS.md.

        This approximates the set of files that a milestone is responsible
        for creating.
        """
        content = self._read_requirements(milestone_id)
        if not content:
            return set()
        return set(self._extract_file_references(content))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_milestone_health(
        self,
        milestone_id: str,
        min_convergence_ratio: float = 0.9,
        degraded_threshold: float = 0.5,
        contract_report: dict[str, Any] | None = None,
    ) -> ConvergenceReport:
        """Check the convergence health of a single milestone.

        Reads ``milestones/{milestone_id}/REQUIREMENTS.md``, counts
        checked vs unchecked items, and parses ``review_cycles`` markers.

        Parameters
        ----------
        milestone_id : str
            The milestone directory name (e.g. ``"milestone-1"``).
        min_convergence_ratio : float
            Ratio at or above which health is considered ``"healthy"``.
            Defaults to ``0.9`` for backward compatibility; callers with
            access to :class:`ConvergenceConfig` should pass
            ``config.convergence.min_convergence_ratio``.
        degraded_threshold : float
            Ratio at or above which health is ``"degraded"`` (vs ``"failed"``),
            when the review fleet has been deployed.  Defaults to ``0.5``.

        Returns
        -------
        ConvergenceReport
            Health report with requirements counts, review cycle count,
            convergence ratio, and overall health assessment.
        """
        content = self._read_requirements(milestone_id)

        if content is None:
            return ConvergenceReport(
                total_requirements=0,
                checked_requirements=0,
                review_cycles=0,
                convergence_ratio=0.0,
                review_fleet_deployed=False,
                health="unknown",
            )

        if not content.strip():
            return ConvergenceReport(
                total_requirements=0,
                checked_requirements=0,
                review_cycles=0,
                convergence_ratio=0.0,
                review_fleet_deployed=False,
                health="unknown",
            )

        checked, total = self._parse_requirements_counts(content)
        cycles = self._parse_max_review_cycles(content)

        # Compute convergence ratio
        ratio = checked / total if total > 0 else 0.0

        # Factor in contract compliance ratio when available (milestone-5)
        effective_ratio = ratio
        if contract_report and contract_report.get("total_contracts", 0) > 0:
            _mm_total = contract_report.get("total_contracts", 0)
            _mm_verified = contract_report.get("verified_contracts", 0)
            contract_ratio = _mm_verified / _mm_total if _mm_total > 0 else 0.0
            effective_ratio = min(ratio, contract_ratio)

        # Determine health status using configurable thresholds
        if total == 0:
            health = "unknown"
        elif effective_ratio >= min_convergence_ratio:
            health = "healthy"
        elif cycles > 0 and effective_ratio >= degraded_threshold:
            health = "degraded"
        else:
            health = "failed"

        return ConvergenceReport(
            total_requirements=total,
            checked_requirements=checked,
            review_cycles=cycles,
            convergence_ratio=effective_ratio,
            review_fleet_deployed=cycles > 0,
            health=health,
        )

    def get_cross_milestone_wiring(self) -> list[WiringGap]:
        """Scan all milestones for cross-milestone wiring gaps.

        For each milestone, examines import references in its
        ``REQUIREMENTS.md``.  If a reference points to a file that
        belongs to a different milestone, verifies that the file
        exists on disk.  Returns a :class:`WiringGap` for each
        missing connection.

        Returns
        -------
        list[WiringGap]
            Wiring gaps where a milestone references a file or symbol
            from another milestone that does not exist.
        """
        milestone_ids = self._list_milestone_ids()
        if not milestone_ids:
            return []

        # Build a mapping of file_path -> milestone_id for all milestones
        file_to_milestone: dict[str, str] = {}
        milestone_contents: dict[str, str] = {}

        for mid in milestone_ids:
            content = self._read_requirements(mid)
            if content is None:
                continue
            milestone_contents[mid] = content
            for file_path in self._extract_file_references(content):
                # First milestone to claim a file owns it
                if file_path not in file_to_milestone:
                    file_to_milestone[file_path] = mid

        gaps: list[WiringGap] = []

        for mid, content in milestone_contents.items():
            # Check import references
            for symbol, file_path in self._extract_import_references(content):
                owner = file_to_milestone.get(file_path)
                if owner is not None and owner != mid:
                    # Cross-milestone reference: verify the file exists
                    full_path = self.project_root / file_path
                    if not full_path.is_file():
                        gaps.append(WiringGap(
                            source_milestone=owner,
                            target_milestone=mid,
                            missing_export=symbol,
                            expected_in_file=file_path,
                        ))

            # Check file references that belong to other milestones
            for file_path in self._extract_file_references(content):
                owner = file_to_milestone.get(file_path)
                if owner is not None and owner != mid:
                    full_path = self.project_root / file_path
                    if not full_path.is_file():
                        # Avoid duplicate gaps (already caught via import refs)
                        already_reported = any(
                            g.expected_in_file == file_path
                            and g.target_milestone == mid
                            for g in gaps
                        )
                        if not already_reported:
                            gaps.append(WiringGap(
                                source_milestone=owner,
                                target_milestone=mid,
                                missing_export="(file)",
                                expected_in_file=file_path,
                            ))

        return gaps

    def verify_milestone_exports(self, milestone_id: str) -> list[str]:
        """Verify that files created by a milestone are available for dependents.

        After milestone N completes, scan milestone N+1 (and later
        milestones) for references to files that milestone N is
        responsible for.  Verify those files exist on disk.

        Parameters
        ----------
        milestone_id : str
            The completed milestone whose exports to verify.

        Returns
        -------
        list[str]
            Human-readable descriptions of each missing export.
        """
        milestone_ids = self._list_milestone_ids()
        if not milestone_ids or milestone_id not in milestone_ids:
            return []

        # Collect files owned by this milestone
        owned_files = self._collect_milestone_files(milestone_id)
        if not owned_files:
            return []

        issues: list[str] = []

        # Scan all other milestones for references to owned files
        for other_id in milestone_ids:
            if other_id == milestone_id:
                continue

            content = self._read_requirements(other_id)
            if content is None:
                continue

            # Check import references that point to files owned by this milestone
            for symbol, file_path in self._extract_import_references(content):
                if file_path in owned_files:
                    full_path = self.project_root / file_path
                    if not full_path.is_file():
                        issues.append(
                            f"Milestone '{other_id}' expects '{file_path}' "
                            f"(symbol '{symbol}') from milestone '{milestone_id}', "
                            f"but the file does not exist."
                        )
                    elif symbol != "(file)":
                        # File exists; do a basic symbol presence check
                        try:
                            file_content = full_path.read_text(
                                encoding="utf-8", errors="replace"
                            )
                        except OSError:
                            issues.append(
                                f"Milestone '{other_id}' expects symbol '{symbol}' "
                                f"in '{file_path}' from milestone '{milestone_id}', "
                                f"but the file could not be read."
                            )
                            continue

                        # Simple presence check: symbol name appears in file
                        if not re.search(rf'\b{re.escape(symbol)}\b', file_content):
                            issues.append(
                                f"Milestone '{other_id}' expects symbol '{symbol}' "
                                f"in '{file_path}' from milestone '{milestone_id}', "
                                f"but the symbol was not found in the file."
                            )

            # Check bare file references to owned files
            for file_path in self._extract_file_references(content):
                if file_path in owned_files:
                    full_path = self.project_root / file_path
                    if not full_path.is_file():
                        # Avoid duplicates from import references
                        desc_prefix = (
                            f"Milestone '{other_id}' references '{file_path}' "
                            f"from milestone '{milestone_id}', "
                            f"but the file does not exist."
                        )
                        if desc_prefix not in issues:
                            issues.append(desc_prefix)

        return issues
