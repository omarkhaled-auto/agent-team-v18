"""Unified fix execution pipeline for coordinated and wave-aware repair runs."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from agent_team_v15.fix_prd_agent import classify_fix_feature_mode, generate_fix_prd
from agent_team_v15.tracking_documents import (
    append_fix_cycle_entry,
    build_fix_cycle_entry,
    initialize_fix_cycle_log,
    parse_fix_cycle_log,
)

_MODE_TAG_RE = re.compile(r"\[EXECUTION_MODE:\s*(full|patch)\s*\]", re.IGNORECASE)
_FEATURE_RE = re.compile(r"^###\s+([^\n]+)\n", re.MULTILINE)
_FILE_ENTRY_RE = re.compile(r"-\s+`?([^`\n]+?)`?\s*(?:\(|$)")
logger = logging.getLogger(__name__)


# Phase 2 audit-fix-loop guardrail — TestStatus enum per
# packages/playwright/types/test.d.ts (Playwright 1.x). Pinned by
# tests/fixtures/playwright_json_snapshot.json. ``passed`` and
# ``skipped`` are not failures (skipped is intentional). ``flaky`` does
# not appear here because it lives on the per-test outcome aggregate,
# not the per-attempt result.
_PLAYWRIGHT_FAILURE_RESULT_STATUSES: frozenset[str] = frozenset(
    {"failed", "timedOut", "interrupted"}
)
# Per-test outcome aggregate — used as a fallback when a test entry
# has no ``results[]``. ``unexpected`` means the test failed when it
# was expected to pass (or vice versa).
_PLAYWRIGHT_FAILURE_OUTCOME_STATUSES: frozenset[str] = frozenset({"unexpected"})


class CrossMilestoneLockViolation(Exception):
    """A subset Playwright rerun regressed a test outside the current
    finding's surface — the M(N+1)-fixes-broke-M(N)-tests scenario.

    Phase 2 audit-fix-loop guardrail. Raised by
    :func:`run_regression_check` when ``finding_surface`` is provided
    and a regressed test is NOT in that surface. The audit-fix loop
    must catch this and trigger Phase 1's milestone-anchor restore.
    """

    def __init__(
        self,
        finding_id: str,
        regressed_acs: list[str],
        regressed_tests: list[str],
        finding_surface: list[str],
    ) -> None:
        self.finding_id = finding_id
        self.regressed_acs = list(regressed_acs)
        self.regressed_tests = list(regressed_tests)
        self.finding_surface = list(finding_surface)
        super().__init__(
            f"Cross-milestone lock violation: finding {finding_id} regressed "
            f"AC(s) {sorted(self.regressed_acs)} via test(s) "
            f"{sorted(self.regressed_tests)} which are outside the finding's "
            f"surface {sorted(self.finding_surface)}"
        )


def _prepare_fix_plan(
    findings: list[Any],
    original_prd_path: Path,
    cwd: str | Path,
    config: Any,
    run_number: int,
    previously_passing_acs: list[str] | None = None,
    *,
    fix_prd_text: str | None = None,
) -> tuple[Path, str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cwd_path = Path(cwd)
    if fix_prd_text is None:
        fix_prd_text = generate_fix_prd(
            original_prd_path=original_prd_path,
            codebase_path=cwd_path,
            findings=findings,
            run_number=run_number,
            previously_passing_acs=previously_passing_acs or [],
            config=config if isinstance(config, dict) else None,
        )

    features = _classify_fix_features(fix_prd_text, cwd_path)
    patch_features = [feature for feature in features if feature["mode"] == "patch"]
    full_features = [feature for feature in features if feature["mode"] == "full"]
    return cwd_path, fix_prd_text, features, patch_features, full_features


def _classify_blast_radius(radius: int) -> str:
    if radius <= 3:
        return "patch"
    if radius <= 10:
        return "targeted"
    return "broad"


def _resolve_requirements_dir(cwd: Path, config: Any) -> Path:
    default_dir = ".agent-team"
    if isinstance(config, dict):
        convergence = config.get("convergence")
        if isinstance(convergence, dict):
            return cwd / str(convergence.get("requirements_dir", default_dir) or default_dir)
        return cwd / str(config.get("requirements_dir", default_dir) or default_dir)

    convergence = getattr(config, "convergence", None)
    if convergence is not None:
        return cwd / str(getattr(convergence, "requirements_dir", default_dir) or default_dir)
    return cwd / default_dir


def _fix_cycle_log_enabled(config: Any) -> bool:
    if isinstance(config, dict):
        tracking = config.get("tracking_documents")
        if isinstance(tracking, dict):
            return bool(tracking.get("fix_cycle_log", True))
        return True

    tracking = getattr(config, "tracking_documents", None)
    if tracking is None:
        return True
    return bool(getattr(tracking, "fix_cycle_log", True))


def _summarize_feature_scope(feature: dict[str, Any]) -> str:
    affected_files = int(feature.get("blast_radius", {}).get("radius", 0) or 0)
    parts = [
        str(feature.get("name", "Unnamed fix feature") or "Unnamed fix feature"),
        f"mode={feature.get('mode', 'patch')}",
        f"blast_radius={feature.get('blast_radius_classification', 'patch')}",
        f"affected_files={affected_files}",
    ]
    escalation_reason = str(feature.get("escalation_reason", "") or "").strip()
    if escalation_reason:
        parts.append(f"escalated_by={escalation_reason}")
    return "; ".join(parts)


def _record_unified_fix_plan(
    *,
    cwd_path: Path,
    config: Any,
    run_number: int,
    features: list[dict[str, Any]],
    patch_features: list[dict[str, Any]],
    full_features: list[dict[str, Any]],
    findings: list[Any],
    log: Callable[[str], None] | None = None,
) -> None:
    telemetry_dir = cwd_path / ".agent-team" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    unique_affected_files = {
        str(path).replace("\\", "/")
        for feature in features
        for path in list(feature.get("blast_radius", {}).get("affected_files", []) or [])
        if str(path).strip()
    }
    overall_blast_radius = _classify_blast_radius(len(unique_affected_files))
    dispatch_summary = f"{len(patch_features)} patch, {len(full_features)} full"

    telemetry_payload = {
        "pipeline": "unified",
        "run_number": run_number,
        "overall_blast_radius": overall_blast_radius,
        "dispatch_summary": dispatch_summary,
        "finding_count": len(findings),
        "features": [
            {
                "name": str(feature.get("name", "") or ""),
                "mode": str(feature.get("mode", "") or ""),
                "blast_radius": str(feature.get("blast_radius_classification", "") or ""),
                "blast_radius_detail": dict(feature.get("blast_radius", {}) or {}),
                "contract_sensitive": bool(feature.get("contract_sensitive", False)),
                "foundation_fix": bool(feature.get("foundation_fix", False)),
                "escalation_reason": str(feature.get("escalation_reason", "") or ""),
                "files_to_modify": list(feature.get("files_to_modify", []) or []),
                "files_to_create": list(feature.get("files_to_create", []) or []),
            }
            for feature in features
        ],
    }
    telemetry_path = telemetry_dir / f"fix-pipeline-run{run_number}.json"
    telemetry_path.write_text(json.dumps(telemetry_payload, indent=2, sort_keys=True), encoding="utf-8")

    if not _fix_cycle_log_enabled(config):
        return

    requirements_dir = _resolve_requirements_dir(cwd_path, config)
    log_path = initialize_fix_cycle_log(str(requirements_dir))
    try:
        previous_cycles = parse_fix_cycle_log(log_path.read_text(encoding="utf-8")).cycles_by_phase.get(
            "Unified Fix Pipeline",
            0,
        )
    except OSError:
        previous_cycles = 0

    entry = build_fix_cycle_entry(
        phase="Unified Fix Pipeline",
        cycle_number=run_number,
        failures=[
            str(getattr(finding, "title", "") or getattr(finding, "summary", "") or getattr(finding, "id", "") or "Fix finding")
            for finding in findings
        ],
        previous_cycles=previous_cycles,
        execution_pipeline="unified",
        blast_radius=overall_blast_radius,
        dispatch_summary=dispatch_summary,
        planned_scope=[_summarize_feature_scope(feature) for feature in features],
    )
    append_fix_cycle_entry(requirements_dir, entry)
    _log(log, f"Unified fix telemetry recorded at {telemetry_path}")


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def execute_unified_fix(
    findings: list[Any],
    original_prd_path: Path,
    cwd: str | Path,
    config: Any,
    run_number: int,
    previously_passing_acs: list[str] | None = None,
    *,
    fix_prd_text: str | None = None,
    fix_prd_path: Path | None = None,
    run_full_build: Callable[[Path, Path, dict[str, Any]], float] | None = None,
    run_patch_fixes: Callable[..., float] | None = None,
    log: Callable[[str], None] | None = None,
) -> float:
    """Execute a fix run through one canonical planning pipeline."""

    cwd_path, fix_prd_text, features, patch_features, full_features = _prepare_fix_plan(
        findings=findings,
        original_prd_path=original_prd_path,
        cwd=cwd,
        config=config,
        run_number=run_number,
        previously_passing_acs=previously_passing_acs,
        fix_prd_text=fix_prd_text,
    )

    _log(
        log,
        "Unified fix plan: "
        f"{len(features)} feature(s), {len(patch_features)} patch, {len(full_features)} full",
    )
    _record_unified_fix_plan(
        cwd_path=cwd_path,
        config=config,
        run_number=run_number,
        features=features,
        patch_features=patch_features,
        full_features=full_features,
        findings=findings,
        log=log,
    )

    total_cost = 0.0

    if patch_features and run_patch_fixes is not None:
        patch_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="patch",
            selected_features=patch_features,
        )
        patch_cost = float(
            run_patch_fixes(
                patch_features=patch_features,
                fix_prd_path=patch_prd_path,
                fix_prd_text=patch_prd_path.read_text(encoding="utf-8"),
                cwd=cwd_path,
                config=config,
                run_number=run_number,
            )
            or 0.0
        )
        total_cost += patch_cost

    if full_features and run_full_build is not None:
        full_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="full",
            selected_features=full_features,
        )
        total_cost += float(run_full_build(full_prd_path, cwd_path, _coerce_config_dict(config)) or 0.0)
    elif full_features and run_patch_fixes is not None:
        _log(
            log,
            "Full builder unavailable; executing remaining full-mode fix features through the inline patch executor",
        )
        full_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="full",
            selected_features=full_features,
        )
        total_cost += float(
            run_patch_fixes(
                patch_features=full_features,
                fix_prd_path=full_prd_path,
                fix_prd_text=full_prd_path.read_text(encoding="utf-8"),
                cwd=cwd_path,
                config=config,
                run_number=run_number,
            )
            or 0.0
        )
    elif patch_features and run_patch_fixes is None:
        _log(log, "Patch execution callback unavailable; falling back to the legacy full builder path")

    if not patch_features and not full_features and run_full_build is not None:
        default_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="combined",
            selected_features=features,
        )
        total_cost += float(run_full_build(default_prd_path, cwd_path, _coerce_config_dict(config)) or 0.0)

    regressions = run_regression_check(
        cwd=str(cwd_path),
        previously_passing_acs=previously_passing_acs or [],
        config=config,
    )
    if regressions:
        raise RuntimeError(f"Regression check failed for ACs: {', '.join(sorted(regressions))}")

    return total_cost


async def execute_unified_fix_async(
    findings: list[Any],
    original_prd_path: Path,
    cwd: str | Path,
    config: Any,
    run_number: int,
    previously_passing_acs: list[str] | None = None,
    *,
    fix_prd_text: str | None = None,
    fix_prd_path: Path | None = None,
    run_full_build: Callable[[Path, Path, dict[str, Any]], Any] | None = None,
    run_patch_fixes: Callable[..., Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> float:
    """Async variant for CLI audit flows that already run inside an event loop."""

    cwd_path, fix_prd_text, features, patch_features, full_features = _prepare_fix_plan(
        findings=findings,
        original_prd_path=original_prd_path,
        cwd=cwd,
        config=config,
        run_number=run_number,
        previously_passing_acs=previously_passing_acs,
        fix_prd_text=fix_prd_text,
    )

    _log(
        log,
        "Unified fix plan: "
        f"{len(features)} feature(s), {len(patch_features)} patch, {len(full_features)} full",
    )
    _record_unified_fix_plan(
        cwd_path=cwd_path,
        config=config,
        run_number=run_number,
        features=features,
        patch_features=patch_features,
        full_features=full_features,
        findings=findings,
        log=log,
    )

    total_cost = 0.0

    if patch_features and run_patch_fixes is not None:
        patch_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="patch",
            selected_features=patch_features,
        )
        patch_cost = await _await_if_needed(
            run_patch_fixes(
                patch_features=patch_features,
                fix_prd_path=patch_prd_path,
                fix_prd_text=patch_prd_path.read_text(encoding="utf-8"),
                cwd=cwd_path,
                config=config,
                run_number=run_number,
            )
        )
        total_cost += float(patch_cost or 0.0)

    if full_features and run_full_build is not None:
        full_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="full",
            selected_features=full_features,
        )
        total_cost += float(
            await _await_if_needed(run_full_build(full_prd_path, cwd_path, _coerce_config_dict(config)))
            or 0.0
        )
    elif full_features and run_patch_fixes is not None:
        _log(
            log,
            "Full builder unavailable; executing remaining full-mode fix features through the inline patch executor",
        )
        full_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="full",
            selected_features=full_features,
        )
        total_cost += float(
            await _await_if_needed(
                run_patch_fixes(
                    patch_features=full_features,
                    fix_prd_path=full_prd_path,
                    fix_prd_text=full_prd_path.read_text(encoding="utf-8"),
                    cwd=cwd_path,
                    config=config,
                    run_number=run_number,
                )
            )
            or 0.0
        )
    elif patch_features and run_patch_fixes is None:
        _log(log, "Patch execution callback unavailable; falling back to the legacy full builder path")

    if not patch_features and not full_features and run_full_build is not None:
        default_prd_path = _ensure_fix_prd_path(
            cwd_path,
            fix_prd_text,
            fix_prd_path,
            run_number,
            variant="combined",
            selected_features=features,
        )
        total_cost += float(
            await _await_if_needed(run_full_build(default_prd_path, cwd_path, _coerce_config_dict(config)))
            or 0.0
        )

    regressions = run_regression_check(
        cwd=str(cwd_path),
        previously_passing_acs=previously_passing_acs or [],
        config=config,
    )
    if regressions:
        raise RuntimeError(f"Regression check failed for ACs: {', '.join(sorted(regressions))}")

    return total_cost


def _classify_fix_features(fix_prd_text: str, cwd: str | Path | None = None) -> list[dict[str, Any]]:
    project_root = Path(cwd) if cwd is not None else Path.cwd()
    features = _parse_fix_features(fix_prd_text)
    for feature in features:
        files_to_modify = list(feature.get("files_to_modify", []))
        explicit_mode = str(feature.get("execution_mode", "") or "").lower()
        inferred_mode = classify_fix_feature_mode(feature)
        blast_radius = analyze_blast_radius(files_to_modify, project_root) if files_to_modify else {
            "radius": 0,
            "affected_files": [],
            "crosses_boundary": False,
            "feature_areas": [],
        }
        contract_sensitive = _check_contract_sensitive(files_to_modify, project_root)
        foundation_fix = is_foundation_fix([feature])

        feature["blast_radius"] = blast_radius
        feature["blast_radius_classification"] = _classify_blast_radius(int(blast_radius.get("radius", 0) or 0))
        feature["contract_sensitive"] = contract_sensitive
        feature["foundation_fix"] = foundation_fix
        feature["mode"] = "full" if explicit_mode == "full" or inferred_mode == "full" else "patch"

        if blast_radius.get("crosses_boundary"):
            feature["mode"] = "full"
            feature["escalation_reason"] = "blast_radius_crosses_boundary"
        if contract_sensitive:
            feature["mode"] = "full"
            feature["escalation_reason"] = "contract_sensitive"
        if foundation_fix:
            feature["mode"] = "full"
            feature.setdefault("escalation_reason", "foundation_fix")

    features.sort(key=lambda item: (0 if item.get("foundation_fix") else 1, item.get("name", "")))
    return features


def analyze_blast_radius(changed_files: list[str], project_root: Path) -> dict[str, Any]:
    """Analyze the blast radius of a set of changed files."""
    affected = {str(Path(path)).replace("\\", "/") for path in changed_files if str(path).strip()}
    for file_path in list(affected):
        affected.update(_find_dependents(file_path, project_root))

    feature_areas = {
        area
        for area in (_classify_feature_area(path) for path in affected)
        if area
    }
    return {
        "radius": len(affected),
        "affected_files": sorted(affected),
        "crosses_boundary": len(feature_areas) > 1,
        "feature_areas": sorted(feature_areas),
    }


def _find_dependents(file_path: str, project_root: Path) -> list[str]:
    """Find files that import the given file."""
    dependents: list[str] = []
    target_name = Path(file_path).stem
    patterns = ("*.ts", "*.tsx", "*.js", "*.jsx")
    seen: set[str] = set()

    # Safe walker — node_modules / .pnpm pruned at descent
    # (project_walker.py post smoke #9/#10).
    from .project_walker import iter_project_files
    for candidate in iter_project_files(project_root, patterns=patterns):
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(rf"from\s+['\"].*{re.escape(target_name)}['\"]", content):
            relative = str(candidate.relative_to(project_root)).replace("\\", "/")
            if relative not in seen:
                seen.add(relative)
                dependents.append(relative)
    return dependents


def _classify_feature_area(file_path: str) -> str:
    parts = [part for part in Path(file_path).parts if part not in {"src", "apps", "api", "web", "frontend", "backend"}]
    if not parts:
        return ""
    return parts[0]


def _check_contract_sensitive(files_to_modify: list[str], project_root: Path) -> bool:
    """Check whether a fix touches a contract surface."""
    for file_path in files_to_modify:
        normalized = str(file_path).replace("\\", "/")
        if normalized.endswith(".controller.ts"):
            return True
        if normalized.endswith(".dto.ts"):
            return True
        if "api-client" in normalized or "generated" in normalized:
            return True

    for file_path in files_to_modify:
        full_path = project_root / file_path
        if not full_path.exists():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(token in content for token in ("@ApiProperty", "@ApiResponse", "@UseGuards", "@Get(", "@Post(", "@Put(", "@Patch(", "@Delete(")):
            return True
    return False


def is_foundation_fix(fix_features: list[dict[str, Any]]) -> bool:
    """Determine whether a fix touches shared infrastructure."""
    foundation_patterns = (
        "app.module",
        "main.ts",
        "docker-compose",
        "prisma/schema",
        "auth/",
        "middleware/",
        "interceptor/",
        "guard/",
        "config/",
        "shared/",
        "common/",
        "packages/",
    )
    for feature in fix_features:
        for file_path in feature.get("files_to_modify", []):
            normalized = str(file_path).replace("\\", "/").lower()
            if any(pattern in normalized for pattern in foundation_patterns):
                return True
    return False


def filter_denylisted_findings(
    findings: list[Any],
    denylist: "list[str] | tuple[str, ...] | None",
) -> tuple[list[Any], list[Any]]:
    """Split findings into ``(kept, rejected)`` using the milestone-anchor denylist.

    Phase 1 audit-fix-loop guardrail: fix proposals whose ``primary_file``
    falls inside an immutable critical-path glob (``packages/api-client/**``,
    ``prisma/migrations/**``) are filtered out BEFORE dispatch. The matcher
    is :func:`agent_team_v15.wave_executor.matches_anchor_denylist` so the
    glob semantics stay consistent with the anchor primitive itself.

    A ``[FIX-DENYLIST] rejected`` warning is logged per dropped finding so
    operators can see which dispatches were blocked.
    """
    if not denylist:
        return list(findings), []

    from .wave_executor import matches_anchor_denylist

    patterns = tuple(denylist)
    kept: list[Any] = []
    rejected: list[Any] = []
    for finding in findings:
        primary_file = str(getattr(finding, "primary_file", "") or "")
        if primary_file and matches_anchor_denylist(primary_file, patterns):
            logger.warning(
                "[FIX-DENYLIST] rejected %s primary_file=%s",
                getattr(finding, "finding_id", "?"),
                primary_file,
            )
            rejected.append(finding)
        else:
            kept.append(finding)
    return kept, rejected


def run_regression_check(
    cwd: str,
    previously_passing_acs: list[str],
    config: Any,
    *,
    test_surface_lock: list[str] | tuple[str, ...] | None = None,
    finding_id: str = "",
    finding_surface: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Re-verify previously passing ACs after a fix run.

    Phase 2 audit-fix-loop guardrail.

    ``test_surface_lock`` (optional): when provided, the Playwright
    invocation is scoped to those positional file paths instead of
    running the entire ``e2e/tests`` directory. The subset rerun is
    cheaper and tighter when the caller knows which files are
    locked-against-regression.

    ``finding_id`` / ``finding_surface`` (optional): when provided, the
    function detects the M(N+1)-fixes-broke-M(N) scenario — if a
    regression hits a test OUTSIDE ``finding_surface``, raise
    :class:`CrossMilestoneLockViolation`. Regressions WITHIN the
    finding's own surface are returned via the list[str] return value
    as today (those represent expected churn within the fix's
    declared scope).

    All new arguments default such that legacy callers
    (``coordinated_builder.py:1177,1918`` and ``fix_executor.py:301,433``)
    continue to behave exactly as before.
    """
    if not previously_passing_acs:
        return []

    project_root = Path(cwd)
    regressed: set[str] = set()
    e2e_dir = project_root / "e2e" / "tests"

    locked_paths = [str(p).replace("\\", "/").strip() for p in (test_surface_lock or []) if str(p).strip()]
    finding_paths = {str(p).replace("\\", "/").strip() for p in (finding_surface or []) if str(p).strip()}
    regressed_specs: list[dict[str, str]] = []

    if e2e_dir.exists():
        cmd = ["npx", "playwright", "test"]
        # Positional file args MUST come before flags per Playwright's
        # CLI contract. When the lock is empty, fall through to the
        # legacy full-dir invocation.
        if locked_paths:
            cmd.extend(locked_paths)
        cmd.append("--reporter=json")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result and result.returncode != 0:
            regressed_specs = _parse_playwright_failures_detailed(
                result.stdout or result.stderr or ""
            )
            # Defensive: when a lock subset is configured, ignore
            # failures from files outside the subset. Playwright
            # respects positional file args but a flaky reporter or a
            # mocked subprocess in tests can return broader output;
            # filtering here keeps the contract honest.
            if locked_paths:
                lock_set = {p for p in locked_paths}
                regressed_specs = [
                    spec for spec in regressed_specs
                    if not spec["file"]
                    or any(spec["file"] == lp or spec["file"].endswith("/" + lp) or lp.endswith("/" + spec["file"]) for lp in lock_set)
                ]
            for spec in regressed_specs:
                ac_id = _map_test_to_ac(spec["title"], cwd)
                if ac_id and ac_id in previously_passing_acs:
                    regressed.add(ac_id)

    evidence_mode = str(_config_value(config, "evidence_mode", "disabled")).strip().lower()
    if evidence_mode in {"soft_gate", "hard_gate"}:
        try:
            from agent_team_v15.evidence_ledger import EvidenceLedger

            ledger = EvidenceLedger(project_root / ".agent-team" / "evidence")
            ledger.load_all()
            for ac_id in previously_passing_acs:
                if ac_id in regressed:
                    continue
                entry = ledger.get_entry(ac_id)
                if entry and entry.verdict == "PASS":
                    for evidence in entry.evidence:
                        if evidence.path and not (project_root / evidence.path).exists() and not Path(evidence.path).exists():
                            regressed.add(ac_id)
                            break
        except Exception:
            pass

    if bool(_config_value(config, "live_endpoint_check", False)):
        regressed.update(_rerun_probes_for_acs(previously_passing_acs, cwd, config))

    # Phase 2 cross-milestone lock check. Only fires when the caller
    # supplied finding_surface — legacy callers without it fall through
    # to the legacy return-list-of-AC-IDs behavior.
    if finding_surface is not None:
        regressed_outside_surface_acs: set[str] = set()
        regressed_outside_surface_tests: set[str] = set()
        for spec in regressed_specs:
            spec_file = spec["file"]
            inside = _path_matches_surface(spec_file, finding_paths)
            if inside:
                continue
            regressed_outside_surface_tests.add(spec_file or spec["title"])
            ac_id = _map_test_to_ac(spec["title"], cwd)
            if ac_id and ac_id in previously_passing_acs:
                regressed_outside_surface_acs.add(ac_id)
        if regressed_outside_surface_tests:
            raise CrossMilestoneLockViolation(
                finding_id=finding_id,
                regressed_acs=sorted(regressed_outside_surface_acs),
                regressed_tests=sorted(regressed_outside_surface_tests),
                finding_surface=sorted(finding_paths),
            )

    return sorted(regressed)


def _path_matches_surface(spec_file: str, surface: set[str]) -> bool:
    """A spec file is "inside" the finding's surface when one of the
    configured surface paths is a basename or trailing-segment match.

    Playwright's JSON reporter emits ``spec.file`` relative to the
    project's ``testDir`` (e.g., ``checkout.spec.ts``), while the
    surface paths from ``Finding.test_surface`` are relative to the
    project root (e.g., ``e2e/tests/checkout.spec.ts``). Matching the
    trailing path segment handles both shapes safely.
    """
    if not spec_file:
        return False
    spec_normalized = spec_file.replace("\\", "/").lstrip("./")
    for path in surface:
        path_norm = path.replace("\\", "/").lstrip("./")
        if not path_norm:
            continue
        if spec_normalized == path_norm:
            return True
        if path_norm.endswith("/" + spec_normalized):
            return True
        if spec_normalized.endswith("/" + path_norm):
            return True
    return False


def _parse_playwright_failures(output: str) -> list[str]:
    """Extract failed Playwright spec titles from ``--reporter=json`` stdout.

    Returns a sorted, de-duplicated list of titles. See
    :func:`_parse_playwright_failures_detailed` for the rich shape that
    also exposes file paths and statuses.

    Risk #17 (closed Session 2): the per-test ``status`` on
    ``JSONReportTest`` is the OUTCOME aggregate (``expected`` |
    ``unexpected`` | ``flaky`` | ``skipped``), NOT the per-attempt
    ``TestStatus`` enum. Per-attempt status lives on
    ``results[].status`` (``passed`` | ``failed`` | ``timedOut`` |
    ``skipped`` | ``interrupted``). The earlier implementation compared
    ``test.status`` against ``"passed"`` which is never true under the
    canonical schema, so every test in any failed run was reported as
    failed. The new logic walks ``results[]`` and looks at the LAST
    attempt — if it failed/timedOut/interrupted, the spec failed; if a
    flaky test eventually passed on retry it's not a regression.

    On JSON parse failure, returns ``[]`` and logs a WARN. The earlier
    regex-scrape fallback was over-broad (matched any ``"title"`` key in
    the output, including suite titles, project names, and attachment
    titles). Failing CLOSED here would over-rollback the fix-loop;
    failing OPEN with a warn keeps the loop moving but flags the
    silent gap to operators.
    """
    detailed = _parse_playwright_failures_detailed(output)
    return sorted({entry["title"] for entry in detailed})


def _parse_playwright_failures_detailed(
    output: str,
) -> list[dict[str, str]]:
    """Like :func:`_parse_playwright_failures` but returns
    ``[{title, file, last_status}]`` per failed spec so the caller can
    filter by file path (used by the cross-milestone lock check).
    """
    if not output.strip():
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        snippet = output.strip()[:200]
        logger.warning(
            "Playwright JSON reporter output failed to parse — "
            "regression check returning empty failure set. "
            "First 200 chars: %r",
            snippet,
        )
        return []
    failures: list[dict[str, str]] = []
    for suite in list(payload.get("suites", []) or []):
        _collect_failed_specs(suite, "", failures)
    # De-dup by (title, file) — same spec can appear under multiple
    # projects (e.g., chromium + firefox); keep one entry per pair.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for entry in failures:
        key = (entry["title"], entry["file"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _collect_failed_specs(
    node: dict[str, Any],
    inherited_file: str,
    out: list[dict[str, str]],
) -> None:
    # Suite-level ``file`` propagates to specs that don't override it.
    suite_file = str(node.get("file", "") or inherited_file).replace("\\", "/")
    for spec in list(node.get("specs", []) or []):
        spec_title = str(spec.get("title", "")).strip()
        if not spec_title:
            continue
        spec_file = str(spec.get("file", "") or suite_file).replace("\\", "/")
        for test in list(spec.get("tests", []) or []):
            results = list(test.get("results", []) or [])
            if results:
                # The last attempt is the verdict — flaky tests that
                # eventually pass are NOT regressions. Status casing is
                # canonical per Playwright's TestStatus enum
                # (``timedOut`` with a capital O); compare verbatim.
                last_status = str(results[-1].get("status", "")).strip()
                if last_status in _PLAYWRIGHT_FAILURE_RESULT_STATUSES:
                    out.append(
                        {
                            "title": spec_title,
                            "file": spec_file,
                            "last_status": last_status,
                        }
                    )
                    continue
            else:
                # No results recorded — fall back to the outcome
                # aggregate. ``unexpected`` is the only outcome here
                # that signals failure (``expected`` = pass,
                # ``skipped`` = intentional, ``flaky`` always has
                # results).
                outcome = str(test.get("status", "")).strip()
                if outcome in _PLAYWRIGHT_FAILURE_OUTCOME_STATUSES:
                    out.append(
                        {
                            "title": spec_title,
                            "file": spec_file,
                            "last_status": outcome,
                        }
                    )
    for child in list(node.get("suites", []) or []):
        _collect_failed_specs(child, suite_file, out)


def _collect_failed_titles(node: dict[str, Any]) -> list[str]:
    """Backward-compat shim retained for any external callers; prefer
    :func:`_parse_playwright_failures_detailed`.
    """
    out: list[dict[str, str]] = []
    _collect_failed_specs(node, "", out)
    return [entry["title"] for entry in out]


def _map_test_to_ac(test_name: str, cwd: str) -> str:
    """Map a failing test name to an AC ID using the product IR text."""
    product_ir_dir = Path(cwd) / ".agent-team" / "product-ir"
    ir: dict[str, Any] | None = None
    for ir_path in (product_ir_dir / "product.ir.json", product_ir_dir / "IR.json"):
        if not ir_path.is_file():
            continue
        try:
            parsed = json.loads(ir_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if isinstance(parsed, dict):
            ir = parsed
            break
    if ir is None:
        return ""

    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", test_name)
        if len(token) > 2
    }
    for ac in list(ir.get("acceptance_criteria", []) or []):
        ac_id = str(ac.get("id", "")).strip()
        ac_text = str(ac.get("text", "")).lower()
        if ac_id and any(token in ac_text for token in tokens):
            return ac_id
    return ""


def _rerun_probes_for_acs(ac_ids: list[str], cwd: str, config: Any) -> list[str]:
    """Re-execute probes associated with previously passing ACs."""
    try:
        return asyncio.run(_rerun_probes_for_acs_async(ac_ids, cwd, config))
    except RuntimeError as exc:
        logger.warning("Cannot rerun probes — %s. Regression coverage degraded.", exc)
        return []


async def _rerun_probes_for_acs_async(ac_ids: list[str], cwd: str, config: Any) -> list[str]:
    from agent_team_v15.endpoint_prober import (
        ProbeManifest,
        execute_probes,
        reset_db_and_seed,
        start_docker_for_probing,
    )
    from agent_team_v15.evidence_ledger import map_endpoint_to_acs

    telemetry_dir = Path(cwd) / ".agent-team" / "telemetry"
    if not telemetry_dir.exists():
        logger.warning("No telemetry directory — regression probe coverage degraded")
        return []

    probes_to_rerun = _load_saved_manifest_probes(telemetry_dir, ac_ids, cwd)
    if not probes_to_rerun:
        probes_to_rerun = _load_telemetry_probes(telemetry_dir, ac_ids, cwd)
    if not probes_to_rerun:
        logger.warning(
            "Cannot rerun probes — no manifest or compatible telemetry found. Regression coverage degraded."
        )
        return []

    try:
        docker_ctx = await start_docker_for_probing(cwd, config)
        if not getattr(docker_ctx, "api_healthy", False):
            logger.warning("Cannot rerun probes — Docker not healthy")
            return []

        await reset_db_and_seed(cwd)
        manifest = ProbeManifest(
            milestone_id="regression_check",
            total_probes=len(probes_to_rerun),
            probes=probes_to_rerun,
        )
        manifest = await execute_probes(manifest, docker_ctx, cwd)
    except Exception as exc:
        logger.warning("Probe re-execution failed: %s", exc)
        return []

    regressed: set[str] = set()
    for result in list(getattr(manifest, "results", []) or []):
        if result.passed:
            continue
        for ac_id in map_endpoint_to_acs(result.spec.method, result.spec.path, cwd):
            if ac_id in ac_ids:
                regressed.add(ac_id)
    return sorted(regressed)


def _load_saved_manifest_probes(telemetry_dir: Path, ac_ids: list[str], cwd: str) -> list[Any]:
    probes: list[Any] = []
    seen: set[str] = set()
    for manifest_file in sorted(telemetry_dir.glob("*-probe-manifest.json")):
        try:
            payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        for probe_payload in list(payload.get("probes", []) or []):
            mapped_ac_ids = {
                str(ac_id).strip()
                for ac_id in list(probe_payload.get("mapped_ac_ids", []) or [])
                if str(ac_id).strip()
            }
            if not mapped_ac_ids:
                mapped_ac_ids = set(_map_probe_to_acs(probe_payload, cwd))
            if not mapped_ac_ids or not mapped_ac_ids.intersection(ac_ids):
                continue
            probe_spec = _probe_spec_from_payload(probe_payload)
            if probe_spec is None:
                continue
            key = _probe_spec_key(probe_spec)
            if key in seen:
                continue
            seen.add(key)
            probes.append(probe_spec)
    return probes


def _load_telemetry_probes(telemetry_dir: Path, ac_ids: list[str], cwd: str) -> list[Any]:
    probes: list[Any] = []
    seen: set[str] = set()
    for telemetry_file in sorted(telemetry_dir.glob("*-probes.json")):
        try:
            payload = json.loads(telemetry_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        for probe_payload in list(payload.get("probes", []) or []):
            probe_spec = _probe_spec_from_payload(probe_payload)
            if probe_spec is None:
                continue
            mapped_ac_ids = set(_map_probe_to_acs(probe_payload, cwd))
            if not mapped_ac_ids or not mapped_ac_ids.intersection(ac_ids):
                continue
            key = _probe_spec_key(probe_spec)
            if key in seen:
                continue
            seen.add(key)
            probes.append(probe_spec)
    return probes


def _map_probe_to_acs(probe_payload: dict[str, Any], cwd: str) -> list[str]:
    try:
        from agent_team_v15.evidence_ledger import map_endpoint_to_acs
    except Exception:
        return []

    return map_endpoint_to_acs(
        str(probe_payload.get("method", "")),
        str(probe_payload.get("path", "")),
        cwd,
    )


def _probe_spec_from_payload(probe_payload: dict[str, Any]) -> Any | None:
    required_keys = ("method", "path", "probe_type", "expected_status", "request_body", "headers", "path_params")
    if not all(key in probe_payload for key in required_keys):
        return None
    headers = probe_payload.get("headers")
    path_params = probe_payload.get("path_params")
    request_body = probe_payload.get("request_body")
    if headers is not None and not isinstance(headers, dict):
        return None
    if path_params is not None and not isinstance(path_params, dict):
        return None
    if request_body is not None and not isinstance(request_body, dict):
        return None

    try:
        from agent_team_v15.endpoint_prober import ProbeSpec
    except Exception:
        return None

    method = str(probe_payload.get("method", "")).upper()
    path = str(probe_payload.get("path", ""))
    probe_type = str(probe_payload.get("probe_type", ""))
    if not method or not path or not probe_type:
        return None

    try:
        expected_status = int(probe_payload.get("expected_status", 0))
    except (TypeError, ValueError):
        return None

    return ProbeSpec(
        endpoint=str(probe_payload.get("endpoint", f"{method} {path}")),
        method=method,
        path=path,
        probe_type=probe_type,
        expected_status=expected_status,
        request_body=request_body,
        headers=headers or {},
        path_params=path_params or {},
        description=str(probe_payload.get("description", "")),
    )


def _probe_spec_key(probe_spec: Any) -> str:
    return json.dumps(
        {
            "method": probe_spec.method,
            "path": probe_spec.path,
            "probe_type": probe_spec.probe_type,
            "expected_status": probe_spec.expected_status,
            "request_body": probe_spec.request_body,
            "headers": probe_spec.headers,
            "path_params": probe_spec.path_params,
        },
        sort_keys=True,
    )


def _parse_fix_features(fix_prd_text: str) -> list[dict[str, Any]]:
    matches = list(_FEATURE_RE.finditer(fix_prd_text))
    if not matches:
        return []

    features: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(fix_prd_text)
        block = fix_prd_text[start:end].strip()
        header = match.group(1).strip()
        mode_match = _MODE_TAG_RE.search(block)
        features.append(
            {
                "header": header,
                "block": block,
                "name": header.split(":", 1)[1].strip() if ":" in header else header,
                "description": block,
                "execution_mode": mode_match.group(1).lower() if mode_match else "",
                "files_to_modify": _extract_file_section(block, "Files to Modify"),
                "files_to_create": _extract_file_section(block, "Files to Create"),
            }
        )
    return features


def _extract_file_section(block: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"^####\s+{re.escape(heading)}\s*\n(?P<body>(?:-.*\n)+)",
        re.MULTILINE,
    )
    match = pattern.search(block)
    if not match:
        return []

    files: list[str] = []
    for entry in match.group("body").splitlines():
        file_match = _FILE_ENTRY_RE.search(entry)
        if file_match:
            files.append(file_match.group(1).replace("\\", "/"))
    return files


def _ensure_fix_prd_path(
    cwd: Path,
    fix_prd_text: str,
    existing_path: Path | None,
    run_number: int,
    *,
    variant: str,
    selected_features: list[dict[str, Any]],
) -> Path:
    if existing_path is not None and variant == "combined":
        return existing_path

    rendered = _render_fix_prd_subset(fix_prd_text, selected_features)
    if existing_path is not None and variant == "full" and len(selected_features) == len(_parse_fix_features(fix_prd_text)):
        existing_path.write_text(rendered, encoding="utf-8")
        return existing_path

    output_dir = cwd / ".agent-team"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{variant}_fix_prd_run{run_number}.md"
    path.write_text(rendered, encoding="utf-8")
    return path


def _render_fix_prd_subset(fix_prd_text: str, selected_features: list[dict[str, Any]]) -> str:
    if not selected_features:
        return fix_prd_text

    features_start = fix_prd_text.find("## Features")
    regression_start = fix_prd_text.find("## Regression Guard")
    prefix = fix_prd_text[:features_start].rstrip() if features_start >= 0 else ""
    suffix = fix_prd_text[regression_start:].strip() if regression_start >= 0 else ""
    feature_blocks = "\n\n".join(feature["block"].strip() for feature in selected_features)

    parts = [part for part in [prefix, "## Features", feature_blocks, suffix] if part]
    return "\n\n".join(parts).strip() + "\n"


def _coerce_config_dict(config: Any) -> dict[str, Any]:
    return config if isinstance(config, dict) else {}


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        if key in config:
            return config.get(key, default)
        v18 = config.get("v18")
        if isinstance(v18, dict):
            return v18.get(key, default)
        return default
    v18 = getattr(config, "v18", None)
    if v18 is not None and hasattr(v18, key):
        return getattr(v18, key)
    return getattr(config, key, default)


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(message)


__all__ = [
    "analyze_blast_radius",
    "execute_unified_fix",
    "execute_unified_fix_async",
    "is_foundation_fix",
    "run_regression_check",
]
