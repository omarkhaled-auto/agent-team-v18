"""Git worktree helpers for isolated milestone execution."""

from __future__ import annotations

import fnmatch
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_STAGE_DIRECTORIES = (
    ".agent-team/",
    "apps/",
    "contracts/",
    "e2e/",
    "packages/",
    "prisma/",
    "src/",
)
_DISALLOWED_PATTERNS = (
    ".env",
    ".env.*",
    ".env.local",
    ".env.production",
    "*.credentials",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.pem",
    "*.secret",
    "credentials/",
    "*/credentials/*",
    "secrets/*",
    "*/secrets/*",
)


@dataclass
class WorktreeInfo:
    """Metadata for a milestone-scoped git worktree."""

    milestone_id: str
    branch_name: str
    worktree_path: str
    base_commit: str = ""
    status: str = "CREATED"
    merge_order: int = 0


def _run_git(
    cwd: str | Path,
    args: list[str],
    *,
    timeout: int = 30,
    operation: str = "",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    context = operation or str(cwd)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "git %s failed in %s: %s",
            " ".join(args),
            context,
            (exc.stderr or "").strip()[:300] or (exc.stdout or "").strip()[:300],
        )
        raise
    except subprocess.TimeoutExpired:
        logger.error("git %s timed out after %ss in %s", " ".join(args), timeout, context)
        raise
    except FileNotFoundError:
        logger.error("git not found in PATH while running %s", context)
        raise

    if result.returncode != 0:
        logger.warning(
            "git %s failed in %s: %s",
            " ".join(args),
            context,
            (result.stderr or "").strip()[:300] or (result.stdout or "").strip()[:300],
        )
    return result


def _git_output(cwd: str | Path, args: list[str], *, timeout: int = 30) -> str:
    return _run_git(cwd, args, timeout=timeout).stdout.strip()


def _path_is_disallowed(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/").strip()
    if not normalized:
        return False
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in _DISALLOWED_PATTERNS)


def _ensure_git_identity(cwd: str | Path) -> None:
    try:
        name = _git_output(cwd, ["config", "--get", "user.name"])
        email = _git_output(cwd, ["config", "--get", "user.email"])
        if name and email:
            return
    except subprocess.CalledProcessError:
        pass

    try:
        _run_git(cwd, ["config", "user.name", "agent-team"])
        _run_git(cwd, ["config", "user.email", "agent-team@example.invalid"])
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        logger.warning("Failed to configure local git identity: %s", exc.stderr.strip())


def _ensure_gitignore(project_root: Path, pattern: str) -> None:
    gitignore_path = project_root / ".gitignore"
    existing = ""
    if gitignore_path.is_file():
        try:
            existing = gitignore_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    normalized = pattern.rstrip("/") + "/"
    lines = {line.strip() for line in existing.splitlines()}
    if normalized in lines or normalized.rstrip("/") in lines:
        return

    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(f"{existing}{prefix}{normalized}\n", encoding="utf-8")


def _list_changed_paths(cwd: str | Path) -> list[str]:
    try:
        output = _git_output(cwd, ["status", "--porcelain"])
    except subprocess.CalledProcessError:
        return []

    paths: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        payload = line[3:].strip()
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1].strip()
        if payload:
            paths.append(payload)
    return paths


def _check_disallowed_files(cwd: str | Path) -> list[str]:
    return sorted({path for path in _list_changed_paths(cwd) if _path_is_disallowed(path)})


def _safe_git_stage(cwd: str | Path) -> None:
    """Stage tracked changes plus explicitly safe directories. Never use git add -A."""

    _run_git(
        cwd,
        ["add", "-u", "--", "."],
        timeout=30,
        operation="stage tracked changes safely",
        check=False,
    )
    for safe_dir in _SAFE_STAGE_DIRECTORIES:
        safe_path = Path(cwd) / safe_dir.rstrip("/")
        if not safe_path.exists():
            continue
        _run_git(
            cwd,
            ["add", safe_dir],
            timeout=30,
            operation=f"stage safe directory {safe_dir}",
            check=False,
        )


def _get_head_commit(cwd: str | Path) -> str:
    return _git_output(cwd, ["rev-parse", "HEAD"])


def _copy_agent_team_state(project_root: Path, worktree_root: Path) -> None:
    source = project_root / ".agent-team"
    destination = worktree_root / ".agent-team"
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def ensure_git_initialized(cwd: str) -> bool:
    """Ensure the project root is a git repository with at least one commit."""

    project_root = Path(cwd)
    if (project_root / ".git").exists():
        return True

    try:
        _run_git(project_root, ["init"], operation="initialize git repository")
        _ensure_git_identity(project_root)
        _safe_git_stage(project_root)
        _run_git(
            project_root,
            ["commit", "--allow-empty", "-m", "Initial commit before worktree isolation"],
            operation="create initial isolation commit",
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Git initialization failed: %s", exc)
        return False


def get_main_branch(cwd: str) -> str:
    """Return the active integration branch, falling back to common defaults."""

    try:
        current = _git_output(cwd, ["branch", "--show-current"])
        if current:
            return current
    except subprocess.CalledProcessError:
        pass

    for candidate in ("main", "master"):
        try:
            _run_git(cwd, ["rev-parse", "--verify", candidate])
            return candidate
        except subprocess.CalledProcessError:
            continue

    return "master"


def create_snapshot_commit(cwd: str, message: str) -> str:
    """Create a safe snapshot commit to serve as the worktree baseline."""

    project_root = Path(cwd)
    _ensure_git_identity(project_root)
    _ensure_gitignore(project_root, ".worktrees/")
    disallowed = _check_disallowed_files(project_root)
    if disallowed:
        raise RuntimeError(
            "Cannot create snapshot: disallowed files detected: "
            f"{disallowed}. Add them to .gitignore or remove them before enabling git isolation."
        )

    try:
        _safe_git_stage(project_root)
        _run_git(
            project_root,
            ["commit", "--allow-empty", "-m", message],
            timeout=60,
            operation="create worktree snapshot commit",
        )
        return _get_head_commit(project_root)
    except subprocess.CalledProcessError as exc:
        logger.warning("Snapshot commit failed: %s", exc.stderr.strip())
        return ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Snapshot commit failed: %s", exc)
        return ""


def create_worktree(cwd: str, milestone_id: str, base_commit: str = "") -> WorktreeInfo:
    """Create a milestone worktree under `.worktrees/<milestone_id>`."""

    project_root = Path(cwd)
    worktree_root = project_root / ".worktrees" / milestone_id
    branch_name = f"milestone/{milestone_id}"
    base_ref = base_commit or _get_head_commit(project_root)

    if worktree_root.exists():
        remove_worktree(cwd, milestone_id)

    _ensure_gitignore(project_root, ".worktrees/")

    try:
        try:
            _run_git(project_root, ["branch", "-D", branch_name], operation=f"delete stale branch {branch_name}")
        except subprocess.CalledProcessError as exc:
            logger.info("No stale branch to delete for %s: %s", branch_name, exc.stderr.strip())

        _run_git(
            project_root,
            ["worktree", "add", "-b", branch_name, str(worktree_root), base_ref],
            timeout=90,
            operation=f"create worktree for {milestone_id}",
        )
        _copy_agent_team_state(project_root, worktree_root)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Failed to create worktree for %s: %s", milestone_id, exc)
        raise

    return WorktreeInfo(
        milestone_id=milestone_id,
        branch_name=branch_name,
        worktree_path=str(worktree_root),
        base_commit=base_ref,
        status="CREATED",
    )


def remove_worktree(cwd: str, milestone_id: str) -> None:
    """Remove the milestone worktree and its branch."""

    project_root = Path(cwd)
    worktree_root = project_root / ".worktrees" / milestone_id
    branch_name = f"milestone/{milestone_id}"

    try:
        if worktree_root.exists():
            _run_git(
                project_root,
                ["worktree", "remove", "--force", str(worktree_root)],
                timeout=60,
                operation=f"remove worktree for {milestone_id}",
            )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to remove worktree for %s via git: %s", milestone_id, exc)
        shutil.rmtree(worktree_root, ignore_errors=True)

    try:
        _run_git(project_root, ["branch", "-D", branch_name], operation=f"delete branch {branch_name}")
    except subprocess.CalledProcessError as exc:
        logger.info("Failed to delete branch %s during cleanup: %s", branch_name, exc.stderr.strip())


def list_worktrees(cwd: str) -> list[dict[str, str]]:
    """Return parsed `git worktree list --porcelain` records."""

    try:
        output = _git_output(cwd, ["worktree", "list", "--porcelain"])
    except subprocess.CalledProcessError as exc:
        logger.warning("Unable to list worktrees in %s: %s", cwd, exc.stderr.strip())
        return []

    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            current["branch"] = line[7:].strip()
        elif not line.strip() and current:
            worktrees.append(current)
            current = {}
    if current:
        worktrees.append(current)
    return worktrees


def cleanup_all_worktrees(cwd: str) -> None:
    """Remove every worktree rooted under `.worktrees/`."""

    project_root = Path(cwd)
    root = project_root / ".worktrees"
    if root.exists():
        for entry in root.iterdir():
            if entry.is_dir():
                remove_worktree(cwd, entry.name)

    try:
        _run_git(project_root, ["worktree", "prune"], operation="prune worktrees")
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to prune worktrees in %s: %s", cwd, exc.stderr.strip())


def _copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    elif src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _promote_evidence_file(src: Path, dest: Path) -> None:
    if not dest.exists():
        _copy_tree(src, dest)
        return

    try:
        existing = json.loads(dest.read_text(encoding="utf-8"))
        incoming = json.loads(src.read_text(encoding="utf-8"))
        existing_ts = str(existing.get("timestamp", "") or "")
        incoming_ts = str(incoming.get("timestamp", "") or "")
        if incoming_ts > existing_ts:
            shutil.copy2(src, dest)
            logger.debug("Updated evidence %s with newer timestamp %s", dest.name, incoming_ts)
            return
        if not incoming_ts and src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
            logger.debug("Updated evidence %s using newer mtime fallback", dest.name)
    except Exception as exc:
        logger.warning("Failed to compare evidence timestamps for %s: %s", dest.name, exc)


def promote_worktree_outputs(cwd: str, worktree_path: str, milestone_id: str) -> None:
    """Promote milestone-scoped `.agent-team` outputs back to mainline."""

    main_agent = Path(cwd) / ".agent-team"
    worktree_agent = Path(worktree_path) / ".agent-team"
    if not worktree_agent.exists():
        logger.warning("No .agent-team directory found in worktree %s", worktree_path)
        return

    registries_src = worktree_agent / "registries" / milestone_id
    if registries_src.exists():
        _copy_tree(registries_src, main_agent / "registries" / milestone_id)

    artifacts_src = worktree_agent / "artifacts"
    if artifacts_src.exists():
        for candidate in artifacts_src.glob(f"{milestone_id}-*"):
            _copy_tree(candidate, main_agent / "artifacts" / candidate.name)

    evidence_src = worktree_agent / "evidence"
    if evidence_src.exists():
        for candidate in evidence_src.glob("*.json"):
            dest = main_agent / "evidence" / candidate.name
            _promote_evidence_file(candidate, dest)

    telemetry_src = worktree_agent / "telemetry"
    if telemetry_src.exists():
        for candidate in telemetry_src.glob(f"{milestone_id}-*"):
            _copy_tree(candidate, main_agent / "telemetry" / candidate.name)

    wave_state_src = worktree_agent / "wave_state" / milestone_id
    if wave_state_src.exists():
        _copy_tree(wave_state_src, main_agent / "wave_state" / milestone_id)


__all__ = [
    "WorktreeInfo",
    "cleanup_all_worktrees",
    "create_snapshot_commit",
    "create_worktree",
    "ensure_git_initialized",
    "get_main_branch",
    "list_worktrees",
    "promote_worktree_outputs",
    "remove_worktree",
]
