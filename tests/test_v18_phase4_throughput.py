from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15 import merge_queue as merge_queue_module
from agent_team_v15 import parallel_executor as parallel_executor_module
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15 import worktree_manager as worktree_manager_module
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.merge_queue import (
    MergeOrderError,
    MergeQueueEntry,
    _is_declaration_surface,
    _is_promoted_output_path,
    _merge_branch,
    _regenerate_lockfile,
    _revert_last_merge,
    build_merge_order,
    execute_merge_queue,
)
from agent_team_v15.parallel_executor import execute_parallel_group, group_milestones_by_parallel_group
from agent_team_v15.state import ConvergenceReport, RunState
from agent_team_v15.worktree_manager import (
    cleanup_all_worktrees,
    create_snapshot_commit,
    create_worktree,
    ensure_git_initialized,
    list_worktrees,
    promote_worktree_outputs,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return (result.stdout or "").strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-b", "master")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    _write(root / "package.json", json.dumps({"name": "demo", "dependencies": {"react": "18.0.0"}}, indent=2) + "\n")
    _write(root / "src" / "service.ts", "export const value = 1;\n")
    _write(root / ".gitignore", ".agent-team/\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def _milestone(milestone_id: str, parallel_group: str = "", deps: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title=milestone_id.title(),
        description=f"{milestone_id} description",
        status="PENDING",
        template="full_stack",
        dependencies=list(deps or []),
        parallel_group=parallel_group,
        feature_refs=[],
        ac_refs=[],
    )


def test_ensure_git_initialized_bootstraps_new_repo(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# demo\n")

    assert ensure_git_initialized(str(tmp_path)) is True
    assert (tmp_path / ".git").exists()
    assert _git(tmp_path, "rev-parse", "--verify", "HEAD")


def test_create_worktree_copies_agent_team_and_lists_branch(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"wave_progress": {}}, indent=2))

    info = create_worktree(str(tmp_path), "milestone-1")

    assert Path(info.worktree_path).exists()
    assert info.branch_name == "milestone/milestone-1"
    assert (Path(info.worktree_path) / ".agent-team" / "STATE.json").exists()
    assert ".worktrees/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")

    worktrees = list_worktrees(str(tmp_path))
    assert any(item.get("branch", "").endswith(info.branch_name) for item in worktrees)


def test_cleanup_all_worktrees_removes_created_worktrees(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    create_worktree(str(tmp_path), "milestone-1")
    create_worktree(str(tmp_path), "milestone-2")

    cleanup_all_worktrees(str(tmp_path))

    assert not (tmp_path / ".worktrees" / "milestone-1").exists()
    assert not (tmp_path / ".worktrees" / "milestone-2").exists()


def test_promote_worktree_outputs_copies_milestone_scoped_outputs(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"wave_progress": {}}, indent=2))
    info = create_worktree(str(tmp_path), "milestone-1")
    worktree_root = Path(info.worktree_path)

    _write(
        worktree_root / ".agent-team" / "registries" / "milestone-1" / "deps.registry.json",
        json.dumps({"dependencies": {"zod": "^1.0.0"}}),
    )
    _write(worktree_root / ".agent-team" / "artifacts" / "milestone-1-wave-A.json", "{}")
    _write(worktree_root / ".agent-team" / "evidence" / "AC-1.json", "{}")
    _write(worktree_root / ".agent-team" / "telemetry" / "milestone-1-wave-A.json", "{}")
    _write(worktree_root / ".agent-team" / "wave_state" / "milestone-1" / "state.json", "{}")

    promote_worktree_outputs(str(tmp_path), str(worktree_root), "milestone-1")

    assert (tmp_path / ".agent-team" / "registries" / "milestone-1" / "deps.registry.json").exists()
    assert (tmp_path / ".agent-team" / "artifacts" / "milestone-1-wave-A.json").exists()
    assert (tmp_path / ".agent-team" / "evidence" / "AC-1.json").exists()
    assert (tmp_path / ".agent-team" / "telemetry" / "milestone-1-wave-A.json").exists()
    assert (tmp_path / ".agent-team" / "wave_state" / "milestone-1" / "state.json").exists()


def test_consumption_checklist_in_isolation_path() -> None:
    source = inspect.getsource(cli_module._run_prd_milestones)
    parallel_start = source.find("if parallel_isolation_enabled:")
    loop_start = source.find("while not plan.all_complete()")
    parallel_block = source[parallel_start:loop_start]

    checklist_pos = parallel_block.find("generate_consumption_checklist")
    prompt_pos = parallel_block.find("build_milestone_execution_prompt")
    assert checklist_pos != -1
    assert prompt_pos != -1
    assert checklist_pos < prompt_pos


def test_wave_executor_no_phase4_concepts() -> None:
    source = inspect.getsource(wave_executor_module).lower()
    assert "asyncio.gather" not in source
    assert "worktree" not in source


def test_evidence_promotion_merges_newer(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"wave_progress": {}}, indent=2))
    _write(
        tmp_path / ".agent-team" / "evidence" / "AC-1.json",
        json.dumps({"timestamp": "2026-04-08T00:00:00Z", "value": "old"}),
    )
    info = create_worktree(str(tmp_path), "milestone-1")
    worktree_root = Path(info.worktree_path)
    _write(
        worktree_root / ".agent-team" / "evidence" / "AC-1.json",
        json.dumps({"timestamp": "2026-04-09T00:00:00Z", "value": "new"}),
    )

    promote_worktree_outputs(str(tmp_path), str(worktree_root), "milestone-1")

    promoted = json.loads((tmp_path / ".agent-team" / "evidence" / "AC-1.json").read_text(encoding="utf-8"))
    assert promoted["value"] == "new"


def test_promotion_excludes_state_json(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"authoritative": "main"}, indent=2))
    info = create_worktree(str(tmp_path), "milestone-1")
    worktree_root = Path(info.worktree_path)
    _write(worktree_root / ".agent-team" / "STATE.json", json.dumps({"authoritative": "worktree"}, indent=2))
    _write(worktree_root / ".agent-team" / "artifacts" / "milestone-1-wave-A.json", "{}")

    promote_worktree_outputs(str(tmp_path), str(worktree_root), "milestone-1")

    state = json.loads((tmp_path / ".agent-team" / "STATE.json").read_text(encoding="utf-8"))
    assert state["authoritative"] == "main"
    assert (tmp_path / ".agent-team" / "artifacts" / "milestone-1-wave-A.json").exists()


def test_snapshot_fails_on_secrets(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".env.local", "TOKEN=secret\n")

    with pytest.raises(RuntimeError, match="disallowed files detected"):
        create_snapshot_commit(str(tmp_path), "Snapshot before isolation")


def test_safe_staging_no_git_add_all() -> None:
    for mod in [parallel_executor_module, merge_queue_module, worktree_manager_module]:
        source = inspect.getsource(mod)
        assert 'add", "-A"' not in source
        assert "add', '-A'" not in source
        assert 'git add .' not in source


def test_build_merge_order_uses_seeded_dependencies_and_raises_on_cycles() -> None:
    worktrees = [
        SimpleNamespace(milestone_id="m3", branch_name="milestone/m3", worktree_path="wt3"),
        SimpleNamespace(milestone_id="m4", branch_name="milestone/m4", worktree_path="wt4"),
    ]
    ordered = build_merge_order(
        worktrees,
        "master",
        already_merged_ids=["m1", "m2"],
        milestone_deps={"m3": ["m2"], "m4": ["m3"]},
    )
    assert [entry.milestone_id for entry in ordered] == ["m3", "m4"]

    with pytest.raises(MergeOrderError, match="Cannot determine safe merge order"):
        build_merge_order(
            [
                SimpleNamespace(milestone_id="m1", branch_name="milestone/m1", worktree_path="wt1"),
                SimpleNamespace(milestone_id="m2", branch_name="milestone/m2", worktree_path="wt2"),
            ],
            "master",
            milestone_deps={"m1": ["m2"], "m2": ["m1"]},
        )


@pytest.mark.asyncio
async def test_execute_merge_queue_rejects_non_declaration_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(tmp_path / "src" / "service.ts", "export const value = 2;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch change")
    _git(tmp_path, "checkout", "master")
    _write(tmp_path / "src" / "service.ts", "export const value = 3;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "mainline change")

    async def _compile(**_: object) -> dict[str, object]:
        return {"passed": True, "error_count": 0}

    async def _smoke(**_: object) -> bool:
        return True

    results = await execute_merge_queue(
        queue=[MergeQueueEntry(milestone_id="m1", branch_name="milestone/m1", worktree_path="unused")],
        cwd=str(tmp_path),
        main_branch="master",
        config=SimpleNamespace(),
        run_compile_check=_compile,
        run_smoke_test=_smoke,
        compile_registries=lambda *_: {"deps": True},
        merged_milestone_ids=[],
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].status == "FIX_QUEUE"
    assert results[0].attempt == 2
    assert "src/service.ts" in results[0].error
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_clean_state_before_merge_refuses_unrelated_dirty_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(tmp_path / "src" / "feature.ts", "export const feature = 1;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch change")
    _git(tmp_path, "checkout", "master")
    _write(tmp_path / "src" / "service.ts", "export const value = 2;\n")

    assert _merge_branch(str(tmp_path), "milestone/m1", "master") is False
    assert _git(tmp_path, "log", "-1", "--pretty=%s") == "initial"
    assert "src/service.ts" in _git(tmp_path, "status", "--porcelain")


def test_clean_state_before_merge_refuses_non_promoted_agent_team_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"authoritative": "main"}, indent=2))
    _git(tmp_path, "add", "-f", ".agent-team/STATE.json")
    _git(tmp_path, "commit", "-m", "track state")
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(tmp_path / "src" / "feature.ts", "export const feature = 1;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch change")
    _git(tmp_path, "checkout", "master")
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"authoritative": "modified"}, indent=2))

    assert _is_promoted_output_path(".agent-team/evidence/AC-1.json") is True
    assert _is_promoted_output_path(".agent-team/artifacts/m1-wave-A.json") is True
    assert _is_promoted_output_path(".agent-team/STATE.json") is False
    assert _merge_branch(str(tmp_path), "milestone/m1", "master") is False
    assert _git(tmp_path, "log", "-1", "--pretty=%s") == "track state"
    assert ".agent-team/STATE.json" in _git(tmp_path, "status", "--porcelain")


def test_safe_revert_after_failed_merge(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(tmp_path / "src" / "feature.ts", "export const feature = 1;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch change")
    _git(tmp_path, "checkout", "master")
    _git(tmp_path, "merge", "--no-ff", "milestone/m1", "-m", "Merge milestone/m1 into mainline")
    commit_count = int(_git(tmp_path, "rev-list", "--count", "HEAD"))

    _revert_last_merge(str(tmp_path))

    assert int(_git(tmp_path, "rev-list", "--count", "HEAD")) == commit_count + 1
    assert _git(tmp_path, "log", "-1", "--pretty=%s").startswith("Revert")


@pytest.mark.asyncio
async def test_execute_merge_queue_resolves_declaration_surface_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(
        tmp_path / "package.json",
        json.dumps({"name": "demo", "dependencies": {"react": "^19.0.0"}}, indent=2) + "\n",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch package change")
    _git(tmp_path, "checkout", "master")
    _write(
        tmp_path / "package.json",
        json.dumps({"name": "demo", "dependencies": {"react": "^18.2.0"}}, indent=2) + "\n",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "mainline package change")

    def _compile_registries(cwd: str, milestone_ids: list[str]) -> dict[str, bool]:
        del milestone_ids
        _write(
            Path(cwd) / "package.json",
            json.dumps({"name": "demo", "dependencies": {"react": "^20.0.0"}}, indent=2) + "\n",
        )
        return {"deps": True}

    async def _compile(**_: object) -> dict[str, object]:
        return {"passed": True, "error_count": 0}

    async def _smoke(**_: object) -> bool:
        return True

    results = await execute_merge_queue(
        queue=[MergeQueueEntry(milestone_id="m1", branch_name="milestone/m1", worktree_path="unused")],
        cwd=str(tmp_path),
        main_branch="master",
        config=SimpleNamespace(),
        run_compile_check=_compile,
        run_smoke_test=_smoke,
        compile_registries=_compile_registries,
        merged_milestone_ids=[],
    )

    package_json = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].status == "MERGED"
    assert package_json["dependencies"]["react"] == "^20.0.0"
    assert _is_declaration_surface("package.json") is True


@pytest.mark.asyncio
async def test_two_failures_permanent_fix_queue(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "milestone/m1")
    _write(tmp_path / "src" / "service.ts", "export const value = 2;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "branch change")
    _git(tmp_path, "checkout", "master")
    _write(tmp_path / "src" / "service.ts", "export const value = 3;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "mainline change")

    async def _compile(**_: object) -> dict[str, object]:
        return {"passed": True, "error_count": 0}

    async def _smoke(**_: object) -> bool:
        return True

    results = await execute_merge_queue(
        queue=[MergeQueueEntry(milestone_id="m1", branch_name="milestone/m1", worktree_path="unused")],
        cwd=str(tmp_path),
        main_branch="master",
        config=SimpleNamespace(),
        run_compile_check=_compile,
        run_smoke_test=_smoke,
        compile_registries=lambda *_: {"deps": True},
        merged_milestone_ids=[],
    )

    assert len(results) == 1
    assert results[0].status == "FIX_QUEUE"
    assert results[0].attempt == 2
    assert "src/service.ts" in results[0].error


@pytest.mark.parametrize(
    ("marker_file", "expected_exe"),
    [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
        ("package.json", "npm"),
    ],
)
def test_lockfile_regen_detects_package_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_file: str,
    expected_exe: str,
) -> None:
    commands: list[dict[str, object]] = []
    _write(tmp_path / marker_file, "{}\n")

    monkeypatch.setattr(merge_queue_module.shutil, "which", lambda exe: exe)

    def _fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append({"cmd": cmd, "shell": kwargs.get("shell", False)})
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(merge_queue_module.subprocess, "run", _fake_run)

    assert _regenerate_lockfile(str(tmp_path)) is True
    assert commands
    assert list(commands[0]["cmd"])[0] == expected_exe


def test_lockfile_regen_uses_shell_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "package-lock.json", "{}\n")
    shells: list[object] = []

    monkeypatch.setattr(merge_queue_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(merge_queue_module.shutil, "which", lambda exe: exe)

    def _fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        shells.append(kwargs.get("shell"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(merge_queue_module.subprocess, "run", _fake_run)

    assert _regenerate_lockfile(str(tmp_path)) is True
    assert shells == [True]


def test_group_milestones_by_parallel_group_groups_and_separates_singletons() -> None:
    grouped = group_milestones_by_parallel_group(
        [
            _milestone("m1", parallel_group="alpha"),
            _milestone("m2", parallel_group="alpha"),
            _milestone("m3"),
        ]
    )

    assert [item.id for item in grouped["alpha"]] == ["m1", "m2"]
    assert [item.id for item in grouped["_seq_m3"]] == ["m3"]


@pytest.mark.asyncio
async def test_execute_parallel_group_limits_concurrency_and_merges_successes() -> None:
    import agent_team_v15.parallel_executor as pe_module

    milestones = [_milestone("m1", parallel_group="alpha"), _milestone("m2", parallel_group="alpha")]
    config = SimpleNamespace(v18=SimpleNamespace(max_parallel_milestones=1))
    active = 0
    max_seen = 0
    promoted: list[str] = []
    removed: list[str] = []
    merged_queue_ids: list[str] = []

    def _create_worktree(_: str, milestone_id: str, __: str = "") -> SimpleNamespace:
        return SimpleNamespace(milestone_id=milestone_id, branch_name=f"milestone/{milestone_id}", worktree_path=f"wt/{milestone_id}", status="CREATED")

    async def _execute_single_milestone(milestone: object, worktree_cwd: str, config: object) -> SimpleNamespace:
        nonlocal active, max_seen
        del worktree_cwd, config
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return SimpleNamespace(success=True, total_cost=1.5, milestone_id=getattr(milestone, "id", ""))

    async def _execute_merge_queue(queue: list[object], **_: object) -> list[SimpleNamespace]:
        merged_queue_ids.extend(entry.milestone_id for entry in queue)
        return [SimpleNamespace(milestone_id=entry.milestone_id, success=True) for entry in queue]

    pe_module._commit_worktree_branch = lambda *_args, **_kwargs: None

    result = await execute_parallel_group(
        milestones=milestones,
        config=config,
        cwd="repo",
        execute_single_milestone=_execute_single_milestone,
        create_worktree=_create_worktree,
        remove_worktree=lambda _cwd, milestone_id: removed.append(milestone_id),
        promote_worktree_outputs=lambda _cwd, _worktree_path, milestone_id: promoted.append(milestone_id),
        execute_merge_queue=_execute_merge_queue,
        build_merge_order=build_merge_order,
        create_snapshot_commit=lambda _cwd, _message: "abc123",
        get_main_branch=lambda _cwd: "master",
        merged_milestone_ids=[],
    )

    assert result.milestones_completed == 2
    assert result.milestones_failed == 0
    assert result.total_cost == pytest.approx(3.0)
    assert max_seen == 1
    assert promoted == ["m1", "m2"]
    assert merged_queue_ids == ["m1", "m2"]
    assert removed == ["m1", "m2"]


@pytest.mark.asyncio
async def test_execute_parallel_group_merges_successful_worktrees_when_one_fails() -> None:
    import agent_team_v15.parallel_executor as pe_module

    milestones = [_milestone("m1", parallel_group="alpha"), _milestone("m2", parallel_group="alpha")]
    config = SimpleNamespace(v18=SimpleNamespace(max_parallel_milestones=2))
    merged_queue_ids: list[str] = []

    def _create_worktree(_: str, milestone_id: str, __: str = "") -> SimpleNamespace:
        return SimpleNamespace(milestone_id=milestone_id, branch_name=f"milestone/{milestone_id}", worktree_path=f"wt/{milestone_id}", status="CREATED")

    async def _execute_single_milestone(milestone: object, **_: object) -> SimpleNamespace:
        if getattr(milestone, "id") == "m2":
            raise RuntimeError("boom")
        return SimpleNamespace(success=True, total_cost=2.0)

    async def _execute_merge_queue(queue: list[object], **_: object) -> list[SimpleNamespace]:
        merged_queue_ids.extend(entry.milestone_id for entry in queue)
        return [SimpleNamespace(milestone_id=entry.milestone_id, success=True) for entry in queue]

    pe_module._commit_worktree_branch = lambda *_args, **_kwargs: None

    result = await execute_parallel_group(
        milestones=milestones,
        config=config,
        cwd="repo",
        execute_single_milestone=_execute_single_milestone,
        create_worktree=_create_worktree,
        remove_worktree=lambda *_: None,
        promote_worktree_outputs=lambda *_: None,
        execute_merge_queue=_execute_merge_queue,
        build_merge_order=build_merge_order,
        create_snapshot_commit=lambda _cwd, _message: "abc123",
        get_main_branch=lambda _cwd: "master",
        merged_milestone_ids=[],
    )

    assert result.milestones_completed == 1
    assert result.milestones_failed >= 1
    assert merged_queue_ids == ["m1"]


@pytest.mark.asyncio
async def test_execute_milestone_in_worktree_runs_post_gates_after_wave_pipeline() -> None:
    milestone = _milestone("m1")
    config = AgentTeamConfig()
    config.v18.execution_mode = "phase4_parallel"
    call_order: list[tuple[str, str]] = []

    async def _pipeline(milestone: object, worktree_cwd: str, config: object) -> SimpleNamespace:
        del milestone, config
        call_order.append(("pipeline", worktree_cwd))
        return SimpleNamespace(success=True, total_cost=2.0, waves=[])

    async def _post_gates(milestone: object, worktree_cwd: str, config: object) -> tuple[float, ConvergenceReport | None, str]:
        del milestone, config
        call_order.append(("gates", worktree_cwd))
        return 1.25, None, "COMPLETE"

    result = await cli_module._execute_milestone_in_worktree(
        milestone,
        "C:/tmp/worktree",
        config,
        execute_wave_pipeline=_pipeline,
        run_post_milestone_gates=_post_gates,
    )

    assert result.total_cost == pytest.approx(3.25)
    assert call_order == [("pipeline", "C:/tmp/worktree"), ("gates", "C:/tmp/worktree")]


@pytest.mark.asyncio
async def test_run_prd_milestones_uses_git_isolation_path_even_when_parallel_limit_is_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    milestone = _milestone("milestone-1", parallel_group="alpha")

    class _Plan:
        def __init__(self) -> None:
            self.milestones = [milestone]

        def all_complete(self) -> bool:
            return all(item.status == "COMPLETE" for item in self.milestones)

        def get_ready_milestones(self) -> list[SimpleNamespace]:
            return [item for item in self.milestones if item.status == "PENDING"]

    plan = _Plan()
    config = AgentTeamConfig()
    config.v18.git_isolation = True
    config.v18.max_parallel_milestones = 1
    config.v18.execution_mode = "phase4_parallel"
    config.runtime_verification.enabled = False
    config.schema_validation.enabled = False
    config.quality_validation.enabled = False
    config.audit_team.enabled = False

    req_dir = tmp_path / config.convergence.requirements_dir
    req_dir.mkdir(parents=True, exist_ok=True)
    _write(req_dir / config.convergence.master_plan_file, "# MASTER PLAN\n")

    monkeypatch.setattr(cli_module, "_current_state", RunState(task="demo"), raising=False)

    import agent_team_v15.milestone_manager as mm_module
    import agent_team_v15.parallel_executor as pe_module
    import agent_team_v15.worktree_manager as wt_module

    monkeypatch.setattr(mm_module, "MilestoneManager", lambda _root: SimpleNamespace())
    monkeypatch.setattr(mm_module, "parse_master_plan", lambda _content: plan)
    monkeypatch.setattr(mm_module, "update_master_plan_status", lambda content, *_args: content)
    monkeypatch.setattr(
        mm_module,
        "compute_rollup_health",
        lambda plan_obj: {
            "complete": sum(1 for item in plan_obj.milestones if item.status == "COMPLETE"),
            "total": len(plan_obj.milestones),
            "failed": sum(1 for item in plan_obj.milestones if item.status == "FAILED"),
            "health": "healthy",
        },
    )
    monkeypatch.setattr(
        mm_module,
        "aggregate_milestone_convergence",
        lambda *_args, **_kwargs: ConvergenceReport(total_requirements=0, checked_requirements=0, health="healthy"),
    )
    monkeypatch.setattr(mm_module, "build_milestone_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mm_module, "render_predecessor_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mm_module, "normalize_milestone_dirs", lambda *_args, **_kwargs: 0)

    monkeypatch.setattr(wt_module, "ensure_git_initialized", lambda _cwd: True)
    monkeypatch.setattr(wt_module, "get_main_branch", lambda _cwd: "master")
    monkeypatch.setattr(wt_module, "cleanup_all_worktrees", lambda _cwd: None)
    monkeypatch.setattr(wt_module, "create_snapshot_commit", lambda *_args, **_kwargs: "abc123")
    monkeypatch.setattr(wt_module, "create_worktree", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(wt_module, "remove_worktree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(wt_module, "promote_worktree_outputs", lambda *_args, **_kwargs: None)

    called: dict[str, object] = {}

    async def _fake_execute_parallel_group(**kwargs: object) -> SimpleNamespace:
        called["max_parallel"] = kwargs["config"].v18.max_parallel_milestones
        called["milestone_ids"] = [ms.id for ms in kwargs["milestones"]]
        return SimpleNamespace(
            total_cost=1.0,
            merge_results=[SimpleNamespace(milestone_id="milestone-1", success=True)],
        )

    monkeypatch.setattr(pe_module, "execute_parallel_group", _fake_execute_parallel_group)

    total_cost, report = await cli_module._run_prd_milestones(
        task="demo",
        config=config,
        cwd=str(tmp_path),
        depth="standard",
        prd_path=None,
    )

    assert total_cost == pytest.approx(1.0)
    assert report is not None
    assert called["max_parallel"] == 1
    assert called["milestone_ids"] == ["milestone-1"]


def test_sequential_mode_no_worktrees() -> None:
    source = inspect.getsource(cli_module._run_prd_milestones)
    sequential_start = source.find("for milestone in ready:")
    sequential_block = source[sequential_start:]

    assert "create_worktree" not in sequential_block
    assert "execute_parallel_group" not in sequential_block
    assert "build_merge_order" not in sequential_block


@pytest.mark.asyncio
async def test_phase4_end_to_end_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / ".agent-team" / "STATE.json", json.dumps({"authoritative": "main"}, indent=2))
    _write(
        tmp_path / ".agent-team" / "product_ir.json",
        json.dumps({"acceptance_criteria": [{"id": "AC-1", "text": "Ship feature"}]}, indent=2),
    )
    _write(
        tmp_path / ".agent-team" / "evidence" / "AC-1.json",
        json.dumps({"timestamp": "2026-04-08T00:00:00Z", "value": "old"}, indent=2),
    )

    milestones = [_milestone("m1", parallel_group="alpha", deps=["seeded"])]
    config = SimpleNamespace(v18=SimpleNamespace(max_parallel_milestones=1))
    lifecycle_calls: list[tuple[str, str]] = []
    compile_calls: list[tuple[str, list[str]]] = []
    compile_checks: list[str] = []
    smoke_checks: list[str] = []
    lockfile_attempts: list[dict[str, object]] = []
    original_run = merge_queue_module.subprocess.run

    def _fake_lockfile_run(cmd: object, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if isinstance(cmd, list) and cmd and cmd[0] in {"npm", "pnpm", "yarn", "bun"}:
            lockfile_attempts.append(
                {
                    "cmd": list(cmd),
                    "cwd": kwargs.get("cwd"),
                    "shell": kwargs.get("shell", False),
                }
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(merge_queue_module.subprocess, "run", _fake_lockfile_run)

    async def _pipeline(milestone: object, worktree_cwd: str, config: object) -> SimpleNamespace:
        del config
        worktree_root = Path(worktree_cwd)
        assert worktree_root.parent.name == ".worktrees"
        assert (worktree_root / ".agent-team" / "product_ir.json").exists()
        lifecycle_calls.append(("pipeline", worktree_cwd))
        _write(worktree_root / "src" / "feature.ts", "export const feature = 1;\n")
        _write(
            worktree_root / ".agent-team" / "registries" / getattr(milestone, "id") / "deps.registry.json",
            json.dumps({"dependencies": {"zod": "^1.0.0"}}, indent=2),
        )
        _write(worktree_root / ".agent-team" / "artifacts" / f"{getattr(milestone, 'id')}-wave-A.json", "{}")
        _write(
            worktree_root / ".agent-team" / "evidence" / "AC-1.json",
            json.dumps({"timestamp": "2026-04-09T00:00:00Z", "value": "new"}, indent=2),
        )
        _write(worktree_root / ".agent-team" / "telemetry" / f"{getattr(milestone, 'id')}-wave-A.json", "{}")
        _write(worktree_root / ".agent-team" / "wave_state" / getattr(milestone, "id") / "state.json", "{}")
        _write(worktree_root / ".agent-team" / "STATE.json", json.dumps({"authoritative": "worktree"}, indent=2))
        return SimpleNamespace(success=True, total_cost=1.0, waves=[], milestone_id=getattr(milestone, "id"))

    async def _post_gates(milestone: object, worktree_cwd: str, config: object) -> tuple[float, None, str]:
        del milestone, config
        lifecycle_calls.append(("gates", worktree_cwd))
        _write(
            Path(worktree_cwd) / ".agent-team" / "evidence" / "AC-1.json",
            json.dumps({"timestamp": "2026-04-09T01:00:00Z", "value": "newer"}, indent=2),
        )
        return 0.5, None, "COMPLETE"

    async def _execute_single_milestone(milestone: object, worktree_cwd: str, config: object) -> SimpleNamespace:
        return await cli_module._execute_milestone_in_worktree(
            milestone,
            worktree_cwd,
            config,
            execute_wave_pipeline=_pipeline,
            run_post_milestone_gates=_post_gates,
        )

    def _promote_outputs(cwd: str, worktree_path: str, milestone_id: str) -> None:
        promote_worktree_outputs(cwd, worktree_path, milestone_id)

    async def _run_compile_check(**kwargs: object) -> dict[str, object]:
        compile_checks.append(str(kwargs["cwd"]))
        return {"passed": True, "error_count": 0}

    async def _run_smoke_test(**kwargs: object) -> bool:
        smoke_checks.append(str(kwargs["cwd"]))
        return True

    def _compile_registries(cwd: str, milestone_ids: list[str]) -> dict[str, bool]:
        compile_calls.append((cwd, list(milestone_ids)))
        _write(Path(cwd) / "src" / "compiled.ts", f"export const merged = {json.dumps(milestone_ids)};\n")
        return {"deps": True}

    async def _execute_merge_queue(queue: list[object], **kwargs: object) -> list[object]:
        return await execute_merge_queue(
            queue=queue,
            cwd=str(kwargs["cwd"]),
            main_branch=str(kwargs["main_branch"]),
            config=kwargs["config"],
            run_compile_check=_run_compile_check,
            run_smoke_test=_run_smoke_test,
            compile_registries=_compile_registries,
            merged_milestone_ids=list(kwargs["merged_milestone_ids"]),
        )

    result = await execute_parallel_group(
        milestones=milestones,
        config=config,
        cwd=str(tmp_path),
        execute_single_milestone=_execute_single_milestone,
        create_worktree=create_worktree,
        remove_worktree=worktree_manager_module.remove_worktree,
        promote_worktree_outputs=_promote_outputs,
        execute_merge_queue=_execute_merge_queue,
        build_merge_order=build_merge_order,
        create_snapshot_commit=create_snapshot_commit,
        get_main_branch=worktree_manager_module.get_main_branch,
        merged_milestone_ids=["seeded"],
    )

    evidence = json.loads((tmp_path / ".agent-team" / "evidence" / "AC-1.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / ".agent-team" / "STATE.json").read_text(encoding="utf-8"))
    recent_messages = _git(tmp_path, "log", "--pretty=%s", "-3").splitlines()

    assert result.milestones_completed == 1
    assert result.milestones_failed == 0
    assert result.merge_results and result.merge_results[0].success is True
    assert lifecycle_calls[0][0] == "pipeline"
    assert lifecycle_calls[1][0] == "gates"
    assert lifecycle_calls[0][1].endswith("m1")
    assert lifecycle_calls[0][1] == lifecycle_calls[1][1]
    assert evidence["value"] == "newer"
    assert state["authoritative"] == "main"
    assert (tmp_path / ".agent-team" / "registries" / "m1" / "deps.registry.json").exists()
    assert (tmp_path / ".agent-team" / "artifacts" / "m1-wave-A.json").exists()
    assert (tmp_path / ".agent-team" / "telemetry" / "m1-wave-A.json").exists()
    assert (tmp_path / ".agent-team" / "wave_state" / "m1" / "state.json").exists()
    assert any(message == "Merge milestone/m1 into mainline" for message in recent_messages)
    assert compile_calls == [(str(tmp_path), ["seeded", "m1"])]
    assert compile_checks == [str(tmp_path)]
    assert smoke_checks == [str(tmp_path)]
    assert lockfile_attempts and lockfile_attempts[0]["cmd"][0] == "npm"
    assert lockfile_attempts[0]["cwd"] == str(tmp_path)
    assert lockfile_attempts[0]["shell"] is True
    assert not any((tmp_path / ".worktrees").glob("*"))
