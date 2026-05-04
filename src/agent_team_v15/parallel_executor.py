"""Parallel milestone execution for git-isolated Phase 4 throughput."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .worktree_manager import _run_git, _safe_git_stage

logger = logging.getLogger(__name__)


def _is_codex_appserver_unstable_error(exc: BaseException) -> bool:
    try:
        from .codex_appserver import (
            CodexAppserverUnstableError,
            CodexTerminalTurnError,
        )
    except ImportError:  # pragma: no cover - defensive import fallback
        return False
    return isinstance(exc, CodexAppserverUnstableError) or (
        isinstance(exc, CodexTerminalTurnError)
        and bool(getattr(exc, "repeated_eof", False))
    )


@dataclass
class ParallelGroupResult:
    """Aggregate result for one dispatched parallel group."""

    group_name: str
    milestones_dispatched: int = 0
    milestones_completed: int = 0
    milestones_failed: int = 0
    merge_results: list[Any] = field(default_factory=list)
    total_cost: float = 0.0


async def execute_parallel_group(
    milestones: list[Any],
    config: Any,
    cwd: str,
    execute_single_milestone: Callable[..., Any],
    create_worktree: Callable[..., Any],
    remove_worktree: Callable[..., Any],
    promote_worktree_outputs: Callable[..., Any],
    execute_merge_queue: Callable[..., Any],
    build_merge_order: Callable[..., Any],
    create_snapshot_commit: Callable[..., Any],
    get_main_branch: Callable[..., Any],
    merged_milestone_ids: list[str],
) -> ParallelGroupResult:
    """Execute a ready milestone group inside isolated worktrees."""

    if not milestones:
        return ParallelGroupResult(group_name="empty")

    group_name = str(getattr(milestones[0], "parallel_group", "") or f"_seq_{getattr(milestones[0], 'id', 'unknown')}")
    result = ParallelGroupResult(
        group_name=group_name,
        milestones_dispatched=len(milestones),
    )

    worktree_map: dict[str, Any] = {}
    completed_worktrees: list[Any] = []
    max_parallel = max(1, int(getattr(getattr(config, "v18", None), "max_parallel_milestones", 1) or 1))
    main_branch = str(get_main_branch(cwd))
    milestone_deps = {
        str(getattr(milestone, "id")): list(getattr(milestone, "dependencies", []) or [])
        for milestone in milestones
    }

    try:
        base_commit = create_snapshot_commit(cwd, f"Snapshot before parallel group {group_name}")

        for milestone in milestones:
            milestone_id = str(getattr(milestone, "id"))
            try:
                worktree_info = create_worktree(cwd, milestone_id, base_commit or "")
                worktree_map[milestone_id] = worktree_info
            except Exception as exc:
                result.milestones_failed += 1
                logger.error("Failed to create worktree for %s: %s", milestone_id, exc)

        # max_parallel_milestones=1 means sequential-in-worktrees, not bypass.
        # Uniform worktree usage simplifies reasoning about mainline state.
        semaphore = asyncio.Semaphore(max_parallel)

        async def _run_in_worktree(milestone: Any, worktree_info: Any) -> tuple[str, Any]:
            async with semaphore:
                milestone_id = str(getattr(milestone, "id"))
                try:
                    setattr(worktree_info, "status", "EXECUTING")
                    execution_result = await _await_if_needed(
                        _invoke_flexible_callback(
                            execute_single_milestone,
                            milestone=milestone,
                            worktree_cwd=str(getattr(worktree_info, "worktree_path")),
                            cwd=str(getattr(worktree_info, "worktree_path")),
                            config=config,
                        )
                    )
                    if _milestone_execution_succeeded(execution_result):
                        setattr(worktree_info, "status", "COMPLETE")
                    else:
                        setattr(worktree_info, "status", "FAILED")
                    return milestone_id, execution_result
                except Exception as exc:
                    if _is_codex_appserver_unstable_error(exc):
                        raise
                    setattr(worktree_info, "status", "FAILED")
                    logger.error("Parallel milestone %s failed: %s", milestone_id, exc)
                    return milestone_id, None

        execution_tasks = [
            _run_in_worktree(milestone, worktree_map[str(getattr(milestone, "id"))])
            for milestone in milestones
            if str(getattr(milestone, "id")) in worktree_map
        ]
        execution_results = await asyncio.gather(*execution_tasks, return_exceptions=True)

        for item in execution_results:
            if isinstance(item, Exception):
                if _is_codex_appserver_unstable_error(item):
                    raise item
                result.milestones_failed += 1
                continue

            milestone_id, execution_result = item
            worktree_info = worktree_map.get(milestone_id)
            if worktree_info is None:
                result.milestones_failed += 1
                continue

            if _milestone_execution_succeeded(execution_result):
                result.milestones_completed += 1
                result.total_cost += _extract_total_cost(execution_result)
                completed_worktrees.append(worktree_info)
            else:
                result.milestones_failed += 1

        for worktree_info in completed_worktrees:
            try:
                promote_worktree_outputs(
                    cwd,
                    str(getattr(worktree_info, "worktree_path")),
                    str(getattr(worktree_info, "milestone_id")),
                )
            except Exception as exc:
                setattr(worktree_info, "status", "FAILED")
                result.milestones_failed += 1
                result.milestones_completed = max(0, result.milestones_completed - 1)
                logger.warning(
                    "Failed to promote worktree outputs for %s: %s",
                    getattr(worktree_info, "milestone_id", "unknown"),
                    exc,
                )

        for worktree_info in completed_worktrees:
            try:
                _commit_worktree_branch(str(getattr(worktree_info, "worktree_path")), str(getattr(worktree_info, "milestone_id")))
            except Exception as exc:
                setattr(worktree_info, "status", "FAILED")
                result.milestones_failed += 1
                result.milestones_completed = max(0, result.milestones_completed - 1)
                logger.warning(
                    "Failed to commit worktree branch for %s: %s",
                    getattr(worktree_info, "milestone_id", "unknown"),
                    exc,
                )

        merge_candidates = [
            worktree_info
            for worktree_info in completed_worktrees
            if str(getattr(worktree_info, "status", "")).upper() == "COMPLETE"
        ]
        if merge_candidates:
            try:
                merge_order = build_merge_order(
                    merge_candidates,
                    main_branch,
                    already_merged_ids=merged_milestone_ids,
                    milestone_deps=milestone_deps,
                )
            except Exception as exc:
                from .merge_queue import MergeOrderError, MergeResult

                if not isinstance(exc, MergeOrderError):
                    raise
                logger.error("Cannot determine safe merge order for group %s: %s", group_name, exc)
                result.merge_results = []
                for worktree_info in merge_candidates:
                    setattr(worktree_info, "status", "FIX_QUEUE")
                    result.merge_results.append(
                        MergeResult(
                            milestone_id=str(getattr(worktree_info, "milestone_id")),
                            success=False,
                            status="FIX_QUEUE",
                            error=str(exc),
                        )
                    )
            else:
                result.merge_results = await _await_if_needed(
                    _invoke_flexible_callback(
                        execute_merge_queue,
                        queue=merge_order,
                        cwd=cwd,
                        main_branch=main_branch,
                        config=config,
                        merged_milestone_ids=merged_milestone_ids,
                    )
                )

        return result
    finally:
        for milestone_id in list(worktree_map):
            try:
                remove_worktree(cwd, milestone_id)
            except Exception as exc:
                logger.warning("Failed to clean up worktree for %s: %s", milestone_id, exc)


def group_milestones_by_parallel_group(ready_milestones: list[Any]) -> dict[str, list[Any]]:
    """Group ready milestones by their declared parallel group."""

    groups: dict[str, list[Any]] = {}
    for milestone in ready_milestones:
        milestone_id = str(getattr(milestone, "id", "unknown"))
        group = str(getattr(milestone, "parallel_group", "") or f"_seq_{milestone_id}")
        groups.setdefault(group, []).append(milestone)
    return groups


def _commit_worktree_branch(worktree_path: str, milestone_id: str) -> None:
    _safe_git_stage(worktree_path)
    _run_git(
        worktree_path,
        ["commit", "--allow-empty", "-m", f"Complete {milestone_id}"],
        timeout=60,
        operation=f"commit worktree branch for {milestone_id}",
    )


def _extract_total_cost(result: Any) -> float:
    if isinstance(result, (int, float)):
        return float(result)
    if isinstance(result, dict):
        return float(result.get("total_cost", result.get("cost", 0.0)) or 0.0)
    return float(getattr(result, "total_cost", getattr(result, "cost", 0.0)) or 0.0)


def _milestone_execution_succeeded(result: Any) -> bool:
    if result is None:
        return False
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if "success" in result:
            return bool(result["success"])
        if "passed" in result:
            return bool(result["passed"])
        return True
    return bool(getattr(result, "success", True))


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _invoke_flexible_callback(callback: Callable[..., Any], **kwargs: Any) -> Any:
    signature = inspect.signature(callback)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return callback(**kwargs)
    supported = {name: value for name, value in kwargs.items() if name in signature.parameters}
    if supported:
        return callback(**supported)
    return callback(*kwargs.values())


__all__ = [
    "ParallelGroupResult",
    "execute_parallel_group",
    "group_milestones_by_parallel_group",
]
