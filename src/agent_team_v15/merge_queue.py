"""Serialized merge queue for Phase 4 git-isolated milestone execution."""

from __future__ import annotations

import asyncio
import inspect
import logging
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .registry_compiler import COMPILED_SHARED_SURFACES
from .worktree_manager import _run_git, _safe_git_stage

logger = logging.getLogger(__name__)

_TYPEORM_MIGRATION_DIRS = (
    "src/migrations",
    "migrations",
    "src/database/migrations",
    "apps/api/src/database/migrations",
)
_PRISMA_MIGRATION_DIRS = (
    "prisma/migrations",
    "apps/api/prisma/migrations",
)
_PRISMA_PREFIX_RE = re.compile(r"^(\d{8,})([_-].+)?$")
_TYPEORM_PREFIX_RE = re.compile(r"^(\d+)-(.+)$")


class MergeOrderError(RuntimeError):
    """Raised when the merge queue cannot determine a safe ordering."""


@dataclass
class MergeResult:
    """Outcome for one merge-queue entry."""

    milestone_id: str
    success: bool = False
    status: str = "PENDING"
    conflicts: list[str] = field(default_factory=list)
    compile_passed: bool = False
    smoke_passed: bool = False
    error: str = ""
    attempt: int = 1


@dataclass
class MergeQueueEntry:
    """A completed worktree ready for serialized integration."""

    milestone_id: str
    branch_name: str
    worktree_path: str
    dependencies: list[str] = field(default_factory=list)
    merge_order: int = 0
    status: str = "PENDING"


def _is_promoted_output_path(filepath: str) -> bool:
    """Return True when *filepath* is a Phase 4 promoted `.agent-team` output."""

    normalized = filepath.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 2 or parts[0] != ".agent-team":
        return False

    section = parts[1]
    if section == "registries":
        return len(parts) >= 4 and bool(parts[2])
    if section == "artifacts":
        return len(parts) >= 3 and "-" in parts[2]
    if section == "evidence":
        return len(parts) == 3 and parts[2].endswith(".json")
    if section == "telemetry":
        return len(parts) >= 3 and "-" in parts[2]
    if section == "wave_state":
        return len(parts) >= 4 and bool(parts[2])
    return False


def build_merge_order(
    completed_worktrees: list[Any],
    main_branch: str,
    already_merged_ids: list[str] | None = None,
    milestone_deps: dict[str, list[str]] | None = None,
) -> list[MergeQueueEntry]:
    """Return queue entries in dependency-safe deterministic order."""

    del main_branch  # Reserved for future policy decisions.

    already_merged = set(already_merged_ids or [])
    dependency_map = milestone_deps or {}

    entries = [
        MergeQueueEntry(
            milestone_id=str(getattr(worktree, "milestone_id")),
            branch_name=str(getattr(worktree, "branch_name")),
            worktree_path=str(getattr(worktree, "worktree_path")),
            dependencies=list(dependency_map.get(
                str(getattr(worktree, "milestone_id")),
                list(getattr(worktree, "dependencies", []) or []),
            )),
        )
        for worktree in completed_worktrees
    ]

    ordered: list[MergeQueueEntry] = []
    remaining = list(entries)
    satisfied = set(already_merged)

    while remaining:
        ready = sorted(
            (
                entry
                for entry in remaining
                if all(dep in satisfied for dep in entry.dependencies)
            ),
            key=lambda entry: entry.milestone_id,
        )
        if not ready:
            unsatisfied = {
                entry.milestone_id: [dep for dep in entry.dependencies if dep not in satisfied]
                for entry in remaining
            }
            raise MergeOrderError(
                "Cannot determine safe merge order. "
                f"Unsatisfied dependencies: {unsatisfied}"
            )

        for entry in ready:
            entry.merge_order = len(ordered)
            ordered.append(entry)
            satisfied.add(entry.milestone_id)
            remaining.remove(entry)

    return ordered


async def execute_merge_queue(
    queue: list[MergeQueueEntry],
    cwd: str,
    main_branch: str,
    config: Any,
    run_compile_check: Callable[..., Any],
    run_smoke_test: Callable[..., Any],
    compile_registries: Callable[..., Any],
    merged_milestone_ids: list[str],
) -> list[MergeResult]:
    """Merge completed milestone branches one at a time onto mainline."""

    results: list[MergeResult] = []
    failure_counts: dict[str, int] = {}
    pending = sorted(queue, key=lambda item: (item.merge_order, item.milestone_id))

    while pending:
        current_pass = pending
        pending = []

        for entry in current_pass:
            result = MergeResult(
                milestone_id=entry.milestone_id,
                status="MERGING",
                attempt=failure_counts.get(entry.milestone_id, 0) + 1,
            )
            entry.status = "MERGING"

            try:
                merge_success = _merge_branch(cwd, entry.branch_name, main_branch)
                if not merge_success:
                    conflicts = _get_conflict_files(cwd)
                    result.conflicts = conflicts
                    declaration_conflicts = [path for path in conflicts if _is_declaration_surface(path)]
                    non_declaration_conflicts = [path for path in conflicts if not _is_declaration_surface(path)]

                    if non_declaration_conflicts:
                        _abort_merge(cwd)
                        if _record_merge_failure(
                            failure_counts,
                            entry,
                            result,
                            "Non-declaration merge conflicts rejected to fix queue: "
                            + ", ".join(sorted(non_declaration_conflicts)),
                            conflicts=conflicts,
                        ):
                            results.append(result)
                        else:
                            pending.append(entry)
                        continue

                    if not declaration_conflicts:
                        _abort_merge(cwd)
                        if _record_merge_failure(
                            failure_counts,
                            entry,
                            result,
                            "Merge failed without a resolvable declaration-surface conflict set.",
                            conflicts=conflicts,
                        ):
                            results.append(result)
                        else:
                            pending.append(entry)
                        continue

                    _resolve_declaration_conflicts(
                        cwd=cwd,
                        milestone_id=entry.milestone_id,
                        conflict_files=declaration_conflicts,
                        merged_milestone_ids=merged_milestone_ids,
                        compile_registries=compile_registries,
                    )
                    remaining_conflicts = _get_conflict_files(cwd)
                    if remaining_conflicts:
                        _abort_merge(cwd)
                        if _record_merge_failure(
                            failure_counts,
                            entry,
                            result,
                            "Deterministic declaration-surface resolution left unresolved conflicts.",
                            conflicts=remaining_conflicts,
                        ):
                            results.append(result)
                        else:
                            pending.append(entry)
                        continue

                _renumber_migrations(cwd, entry.milestone_id)

                cumulative_ids = list(dict.fromkeys([*merged_milestone_ids, entry.milestone_id]))
                compile_outcome = await _await_if_needed(compile_registries(cwd, cumulative_ids))
                if not _registry_compile_passed(compile_outcome):
                    _abort_merge(cwd)
                    if _record_merge_failure(
                        failure_counts,
                        entry,
                        result,
                        "Registry compilation failed during merge.",
                    ):
                        results.append(result)
                    else:
                        pending.append(entry)
                    continue

                if not _regenerate_lockfile(cwd):
                    _abort_merge(cwd)
                    if _record_merge_failure(
                        failure_counts,
                        entry,
                        result,
                        "Lockfile regeneration failed during merge.",
                    ):
                        results.append(result)
                    else:
                        pending.append(entry)
                    continue

                _commit_merge(cwd, entry.milestone_id)

                compile_result = await _await_if_needed(
                    _invoke_flexible_callback(
                        run_compile_check,
                        cwd=cwd,
                        wave="full",
                        template="full_stack",
                        config=config,
                    )
                )
                result.compile_passed = _compile_passed(compile_result)
                if not result.compile_passed:
                    _revert_last_merge(cwd)
                    if _record_merge_failure(
                        failure_counts,
                        entry,
                        result,
                        f"Post-merge compile check failed: {_compile_error_count(compile_result)} error(s).",
                    ):
                        results.append(result)
                    else:
                        pending.append(entry)
                    continue

                smoke_result = await _await_if_needed(
                    _invoke_flexible_callback(
                        run_smoke_test,
                        cwd=cwd,
                        config=config,
                    )
                )
                result.smoke_passed = _smoke_passed(smoke_result)
                if not result.smoke_passed:
                    _revert_last_merge(cwd)
                    if _record_merge_failure(
                        failure_counts,
                        entry,
                        result,
                        "Post-merge smoke test failed.",
                    ):
                        results.append(result)
                    else:
                        pending.append(entry)
                    continue

                merged_milestone_ids.append(entry.milestone_id)
                entry.status = "MERGED"
                result.success = True
                result.status = "MERGED"
                results.append(result)
            except Exception as exc:  # pragma: no cover - defensive guard
                _abort_merge(cwd)
                if _record_merge_failure(
                    failure_counts,
                    entry,
                    result,
                    f"Unexpected merge queue error: {exc}",
                ):
                    results.append(result)
                else:
                    pending.append(entry)

    return results


def _record_merge_failure(
    failure_counts: dict[str, int],
    entry: MergeQueueEntry,
    result: MergeResult,
    error: str,
    *,
    conflicts: list[str] | None = None,
) -> bool:
    milestone_id = entry.milestone_id
    failure_counts[milestone_id] = failure_counts.get(milestone_id, 0) + 1
    attempt = failure_counts[milestone_id]
    result.attempt = attempt
    result.error = error
    if conflicts is not None:
        result.conflicts = conflicts

    if attempt >= 2:
        entry.status = "FIX_QUEUE"
        result.status = "FIX_QUEUE"
        logger.warning("%s: permanent FIX_QUEUE after 2 failures", milestone_id)
        return True

    entry.status = "RETRY_PENDING"
    result.status = "RETRY_PENDING"
    logger.warning("%s: merge failure %s/2, will retry next queue pass: %s", milestone_id, attempt, error)
    return False


def _merge_branch(cwd: str, branch: str, target: str) -> bool:
    """Merge *branch* into *target* without auto-committing."""

    try:
        _run_git(
            cwd,
            ["checkout", target],
            timeout=30,
            operation=f"checkout {target} before merging {branch}",
        )
        status = _run_git(
            cwd,
            ["status", "--porcelain"],
            timeout=10,
            operation=f"check mainline cleanliness before merging {branch}",
            check=False,
        )
        if status.stdout.strip():
            dirty_files: list[str] = []
            for line in status.stdout.splitlines():
                if not line.strip():
                    continue
                payload = line[3:].strip().replace("\\", "/")
                if " -> " in payload:
                    payload = payload.split(" -> ", 1)[1].strip()
                if payload:
                    dirty_files.append(payload)

            promoted = [path for path in dirty_files if _is_promoted_output_path(path)]
            unrelated = [path for path in dirty_files if not _is_promoted_output_path(path)]

            if unrelated:
                logger.error(
                    "Mainline has unrelated dirty files; refusing to merge %s: %s",
                    branch,
                    unrelated[:5],
                )
                return False

            if promoted:
                for promoted_path in sorted(set(promoted)):
                    add_result = _run_git(
                        cwd,
                        ["add", "--", promoted_path],
                        timeout=30,
                        operation=f"stage promoted output {promoted_path} before merging {branch}",
                        check=False,
                    )
                    if add_result.returncode != 0:
                        logger.error(
                            "Failed to stage promoted output %s before merging %s: %s",
                            promoted_path,
                            branch,
                            (add_result.stderr or "").strip()[:300],
                        )
                        return False

                staged = _run_git(
                    cwd,
                    ["diff", "--cached", "--name-only"],
                    timeout=10,
                    operation=f"inspect staged promoted outputs before merging {branch}",
                    check=False,
                )
                if staged.stdout.strip():
                    commit_result = _run_git(
                        cwd,
                        ["commit", "-m", f"Stage promoted outputs before merging {branch}"],
                        timeout=30,
                        operation=f"commit promoted outputs before merging {branch}",
                        check=False,
                    )
                    if commit_result.returncode != 0:
                        logger.error(
                            "Failed to commit promoted outputs before merging %s: %s",
                            branch,
                            (commit_result.stderr or "").strip()[:300],
                        )
                        return False

        result = _run_git(
            cwd,
            ["merge", branch, "--no-commit", "--no-ff"],
            timeout=90,
            operation=f"merge {branch} into {target}",
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "Merge of %s into %s reported conflicts or failed: %s",
                branch,
                target,
                (result.stderr or result.stdout or "").strip()[:300],
            )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Failed to merge %s into %s: %s", branch, target, exc)
        return False


def _get_conflict_files(cwd: str) -> list[str]:
    """Return unresolved conflict paths after a failed merge."""

    try:
        result = _run_git(
            cwd,
            ["diff", "--name-only", "--diff-filter=U"],
            timeout=30,
            operation="collect merge conflict files",
        )
    except (OSError, subprocess.SubprocessError):
        return []

    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _is_declaration_surface(filepath: str) -> bool:
    """Return True when *filepath* is a generated shared declaration surface."""

    normalized = filepath.replace("\\", "/").strip().lstrip("./")
    if normalized in COMPILED_SHARED_SURFACES:
        return True
    name = Path(normalized).name
    return any(
        normalized.endswith(surface) or name == Path(surface).name
        for surface in COMPILED_SHARED_SURFACES
    )


def _resolve_declaration_conflicts(
    cwd: str,
    milestone_id: str,
    conflict_files: list[str],
    merged_milestone_ids: list[str],
    compile_registries: Callable[..., Any],
) -> None:
    """Resolve declaration-surface conflicts by regenerating shared outputs."""

    for path in conflict_files:
        ours = _run_git(
            cwd,
            ["checkout", "--ours", "--", path],
            timeout=15,
            operation=f"resolve declaration conflict with ours for {path}",
            check=False,
        )
        if ours.returncode != 0:
            logger.warning("Failed to select ours version for %s", path)
        add_result = _run_git(
            cwd,
            ["add", "--", path],
            timeout=15,
            operation=f"stage declaration conflict resolution for {path}",
            check=False,
        )
        if add_result.returncode != 0:
            logger.warning("Failed to stage declaration conflict resolution for %s", path)

    cumulative_ids = list(dict.fromkeys([*merged_milestone_ids, milestone_id]))
    compile_outcome = compile_registries(cwd, cumulative_ids)
    if inspect.isawaitable(compile_outcome):  # pragma: no cover - async callback support
        raise RuntimeError("compile_registries must be synchronous inside conflict resolution.")
    if not _registry_compile_passed(compile_outcome):
        raise RuntimeError("Registry recompilation failed while resolving declaration conflicts.")

    staged_paths = sorted(COMPILED_SHARED_SURFACES)
    for surface in staged_paths:
        surface_path = Path(cwd) / surface
        if surface_path.exists():
            add_surface = _run_git(
                cwd,
                ["add", "--", surface],
                timeout=15,
                operation=f"stage compiled declaration surface {surface}",
                check=False,
            )
            if add_surface.returncode != 0:
                logger.warning("Failed to stage compiled declaration surface %s", surface)


def _renumber_migrations(cwd: str, milestone_id: str) -> None:
    """Normalize Prisma and TypeORM migration prefixes after merge."""

    del milestone_id  # Reserved for future logging policy.
    root = Path(cwd)

    for relative_dir in _PRISMA_MIGRATION_DIRS:
        prisma_dir = root / relative_dir
        if prisma_dir.is_dir():
            _renumber_prisma_migrations(prisma_dir)

    for relative_dir in _TYPEORM_MIGRATION_DIRS:
        typeorm_dir = root / relative_dir
        if typeorm_dir.is_dir():
            _renumber_typeorm_migrations(typeorm_dir)


def _renumber_prisma_migrations(migrations_dir: Path) -> None:
    seen: set[str] = set()
    for entry in sorted(path for path in migrations_dir.iterdir() if path.is_dir()):
        match = _PRISMA_PREFIX_RE.match(entry.name)
        if not match:
            continue
        prefix = match.group(1)
        suffix = match.group(2) or ""
        if prefix not in seen:
            seen.add(prefix)
            continue

        next_prefix = prefix
        while next_prefix in seen:
            next_prefix = str(int(next_prefix) + 1).zfill(len(prefix))
        target = entry.with_name(f"{next_prefix}{suffix}")
        entry.rename(target)
        seen.add(next_prefix)
        logger.info("Renumbered Prisma migration %s -> %s", entry.name, target.name)


def _renumber_typeorm_migrations(migrations_dir: Path) -> None:
    seen: set[int] = set()
    max_prefix = 0
    files = sorted(path for path in migrations_dir.iterdir() if path.is_file())

    for file_path in files:
        match = _TYPEORM_PREFIX_RE.match(file_path.name)
        if not match:
            continue
        prefix = int(match.group(1))
        max_prefix = max(max_prefix, prefix)
        if prefix not in seen:
            seen.add(prefix)
            continue

        max_prefix += 1
        new_name = f"{max_prefix}-{match.group(2)}"
        target = file_path.with_name(new_name)
        file_path.rename(target)
        seen.add(max_prefix)
        logger.info("Renumbered TypeORM migration %s -> %s", file_path.name, target.name)


def _regenerate_lockfile(cwd: str) -> bool:
    """Regenerate the derived dependency lockfile after a merge."""

    root = Path(cwd)
    use_shell = platform.system() == "Windows"
    lockfile_required = True

    if (root / "pnpm-lock.yaml").exists():
        command = ["pnpm", "install", "--lockfile-only"]
        exe = shutil.which("pnpm")
    elif (root / "yarn.lock").exists():
        command = ["yarn", "install", "--mode", "update-lockfile"]
        exe = shutil.which("yarn")
    elif (root / "bun.lockb").exists():
        command = ["bun", "install", "--frozen-lockfile"]
        exe = shutil.which("bun")
    elif (root / "package-lock.json").exists():
        command = ["npm", "install", "--package-lock-only"]
        exe = shutil.which("npm")
    elif (root / "package.json").exists():
        command = ["npm", "install", "--package-lock-only"]
        exe = shutil.which("npm")
        lockfile_required = False
    else:
        logger.info("No package manager detected; skipping lockfile regeneration")
        return True

    if exe is None and not use_shell:
        if not lockfile_required:
            logger.warning(
                "Package manager '%s' not found in PATH; continuing because no existing lockfile is present",
                command[0],
            )
            return True
        logger.error("Package manager '%s' not found in PATH", command[0])
        return False

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            shell=use_shell,
            check=False,
        )
        if result.returncode != 0:
            if not lockfile_required:
                logger.warning(
                    "Lockfile regeneration failed (%s) without an existing lockfile; continuing: %s",
                    command[0],
                    (result.stderr or result.stdout or "").strip()[:300],
                )
                return True
            logger.warning(
                "Lockfile regeneration failed (%s): %s",
                command[0],
                (result.stderr or result.stdout or "").strip()[:300],
            )
            return False
        return True
    except FileNotFoundError:
        if not lockfile_required:
            logger.warning(
                "Package manager '%s' not found but no existing lockfile is present; continuing",
                command[0],
            )
            return True
        logger.error("Package manager '%s' not found; install it or add it to PATH", command[0])
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        if not lockfile_required:
            logger.warning(
                "Lockfile regeneration failed with %s but no existing lockfile is present; continuing: %s",
                command[0],
                exc,
            )
            return True
        logger.warning("Lockfile regeneration failed with %s: %s", command[0], exc)
        return False


def _abort_merge(cwd: str) -> None:
    """Abort an in-progress merge, if any."""

    try:
        result = _run_git(
            cwd,
            ["merge", "--abort"],
            timeout=15,
            operation="abort in-progress merge",
            check=False,
        )
        if result.returncode != 0:
            logger.info("git merge --abort did not complete cleanly in %s", cwd)
    except (OSError, subprocess.SubprocessError):
        return


def _commit_merge(cwd: str, milestone_id: str) -> None:
    """Create the merge commit after deterministic post-processing."""

    _safe_git_stage(cwd)
    _run_git(
        cwd,
        ["commit", "-m", f"Merge milestone/{milestone_id} into mainline"],
        timeout=60,
        operation=f"commit merged milestone {milestone_id}",
    )


def _revert_last_merge(cwd: str) -> None:
    """Safely undo a failed merge. Never uses git reset --hard."""

    abort_result = _run_git(
        cwd,
        ["merge", "--abort"],
        timeout=10,
        operation="abort failed merge before revert",
        check=False,
    )
    if abort_result.returncode == 0:
        logger.info("Aborted in-progress merge before revert in %s", cwd)
        return

    try:
        result = _run_git(
            cwd,
            ["cat-file", "-p", "HEAD"],
            timeout=10,
            operation="inspect HEAD before merge revert",
            check=False,
        )
        if result.returncode != 0:
            return

        if result.stdout.count("parent ") >= 2:
            revert_result = _run_git(
                cwd,
                ["revert", "-m", "1", "HEAD", "--no-edit"],
                timeout=30,
                operation="revert merge commit after failed verification",
                check=False,
            )
            if revert_result.returncode == 0:
                logger.info("Reverted merge commit via git revert")
            return

        logger.error(
            "Cannot safely revert: HEAD is not a merge commit and no merge is in progress. "
            "Manual inspection required."
        )
    except Exception as exc:
        logger.error("Revert failed: %s", exc)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _invoke_flexible_callback(callback: Callable[..., Any], **kwargs: Any) -> Any:
    signature = inspect.signature(callback)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return callback(**kwargs)
    supported = {name: value for name, value in kwargs.items() if name in signature.parameters}
    return callback(**supported)


def _registry_compile_passed(result: Any) -> bool:
    if isinstance(result, dict):
        return all(bool(value) for value in result.values()) if result else True
    return bool(result if result is not None else True)


def _compile_passed(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if "passed" in result:
            return bool(result["passed"])
        if "success" in result:
            return bool(result["success"])
    return bool(getattr(result, "passed", getattr(result, "success", False)))


def _compile_error_count(result: Any) -> int:
    if isinstance(result, dict):
        if "error_count" in result:
            return int(result.get("error_count") or 0)
        if "errors" in result and isinstance(result["errors"], list):
            return len(result["errors"])
        return 0
    if hasattr(result, "error_count"):
        return int(getattr(result, "error_count") or 0)
    errors = getattr(result, "errors", None)
    if isinstance(errors, list):
        return len(errors)
    return 0


def _smoke_passed(result: Any) -> bool:
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if "passed" in result:
            return bool(result["passed"])
        if "success" in result:
            return bool(result["success"])
        if result:
            return all(_smoke_passed(value) for value in result.values())
        return True
    return bool(getattr(result, "passed", getattr(result, "success", result)))


__all__ = [
    "MergeOrderError",
    "MergeQueueEntry",
    "MergeResult",
    "build_merge_order",
    "execute_merge_queue",
]
