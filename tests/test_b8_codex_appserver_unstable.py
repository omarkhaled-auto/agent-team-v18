"""B8 - repeated Codex appserver EOF becomes a distinct environmental halt."""

from __future__ import annotations

import inspect
import re
import time
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_team_v15 import cli as cli_mod
from agent_team_v15 import codex_appserver as appserver
from agent_team_v15 import parallel_executor
from agent_team_v15 import provider_router
from agent_team_v15 import wave_executor as we_mod
from agent_team_v15.codex_transport import CodexConfig, CodexResult
from agent_team_v15.provider_router import WaveProviderMap
from agent_team_v15.state import RunState, load_state, save_state
from agent_team_v15.wave_executor import _create_checkpoint, _diff_checkpoints


def _config_with_v18_flags() -> Any:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            codex_capture_enabled=False,
            codex_protocol_capture_enabled=False,
            codex_blocked_prefix_as_failure_enabled=False,
        )
    )


def _seed_failed_state(tmp_path: Path) -> Path:
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    state = RunState()
    state.current_milestone = ""
    state.failed_milestones = ["milestone-1"]
    state.milestone_progress["milestone-1"] = {
        "status": "FAILED",
        "failure_reason": "wave_fail_recovery_attempt",
    }
    cli_mod._current_state = state
    save_state(state, directory=str(agent_team_dir))
    return agent_team_dir


def test_codex_appserver_unstable_subclasses_terminal_turn_error() -> None:
    unstable_cls = getattr(appserver, "CodexAppserverUnstableError", None)
    assert unstable_cls is not None
    assert issubclass(unstable_cls, appserver.CodexTerminalTurnError)

    plain = appserver.CodexTerminalTurnError(
        "app-server stdout EOF - subprocess exited",
        thread_id="thread-plain",
        turn_id="turn-plain",
    )
    unstable = unstable_cls(
        "app-server stdout EOF - subprocess exited",
        thread_id="thread-repeat",
        turn_id="turn-repeat",
    )

    assert getattr(plain, "repeated_eof", None) is False
    assert getattr(unstable, "repeated_eof", None) is True
    assert unstable.thread_id == "thread-repeat"
    assert unstable.turn_id == "turn-repeat"


@pytest.mark.asyncio
async def test_retry_budget_zero_transport_eof_raises_appserver_unstable_with_ids(
    tmp_path: Path,
) -> None:
    unstable_cls = getattr(appserver, "CodexAppserverUnstableError", None)
    assert unstable_cls is not None
    (tmp_path / "marker.txt").write_text("synthetic\n", encoding="utf-8")

    async def _execute_codex(*_args: Any, **_kwargs: Any) -> Any:
        raise appserver.CodexTerminalTurnError(
            "app-server stdout EOF - subprocess exited",
            thread_id="thread-original",
            turn_id="turn-original",
        )

    with pytest.raises(unstable_cls) as excinfo:
        await provider_router._execute_codex_wave(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_config_with_v18_flags(),
            claude_callback=AsyncMock(return_value=0.0),
            claude_callback_kwargs={"milestone": types.SimpleNamespace(id="milestone-1")},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_execute_codex,
            ),
            codex_config=CodexConfig(max_retries=0),
            codex_home=tmp_path / "codex-home",
            checkpoint_create=_create_checkpoint,
            checkpoint_diff=_diff_checkpoints,
        )

    assert getattr(excinfo.value, "repeated_eof", None) is True
    assert excinfo.value.reason == "app-server stdout EOF - subprocess exited"
    assert excinfo.value.thread_id == "thread-original"
    assert excinfo.value.turn_id == "turn-original"
    assert excinfo.value.milestone_id == "milestone-1"


@pytest.mark.asyncio
async def test_non_eof_terminal_turn_error_raises_original_plain_error(
    tmp_path: Path,
) -> None:
    unstable_cls = getattr(appserver, "CodexAppserverUnstableError", None)
    (tmp_path / "marker.txt").write_text("synthetic\n", encoding="utf-8")
    original = appserver.CodexTerminalTurnError(
        "thread/archive received before turn/completed",
        thread_id="thread-archive",
        turn_id="turn-archive",
    )

    async def _execute_codex(*_args: Any, **_kwargs: Any) -> Any:
        raise original

    with pytest.raises(appserver.CodexTerminalTurnError) as excinfo:
        await provider_router._execute_codex_wave(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_config_with_v18_flags(),
            claude_callback=AsyncMock(return_value=0.0),
            claude_callback_kwargs={},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_execute_codex,
            ),
            codex_config=CodexConfig(max_retries=1),
            codex_home=tmp_path / "codex-home",
            checkpoint_create=_create_checkpoint,
            checkpoint_diff=_diff_checkpoints,
        )

    assert excinfo.value is original
    if unstable_cls is not None:
        assert not isinstance(excinfo.value, unstable_cls)
    assert getattr(excinfo.value, "repeated_eof", None) is False


@pytest.mark.asyncio
async def test_single_transient_eof_retries_without_unstable_error(
    tmp_path: Path,
) -> None:
    unstable_cls = getattr(appserver, "CodexAppserverUnstableError", None)
    assert unstable_cls is not None
    (tmp_path / "marker.txt").write_text("original\n", encoding="utf-8")
    attempts: list[Path | None] = []

    async def _execute_codex(
        _prompt: str,
        cwd: str,
        _config: CodexConfig,
        codex_home: Path | None,
        **_kwargs: Any,
    ) -> CodexResult:
        attempts.append(codex_home)
        target = Path(cwd) / "marker.txt"
        if len(attempts) == 1:
            target.write_text("dirty before eof\n", encoding="utf-8")
            raise appserver.CodexTerminalTurnError(
                "app-server stdout EOF - subprocess exited",
                thread_id="thread-transient",
                turn_id="turn-transient",
            )
        assert target.read_text(encoding="utf-8") == "original\n"
        target.write_text("fixed\n", encoding="utf-8")
        return CodexResult(success=True, model="gpt-5.4", cost_usd=0.07)

    result = await provider_router._execute_codex_wave(
        wave_letter="B",
        prompt="wire backend",
        cwd=str(tmp_path),
        config=_config_with_v18_flags(),
        claude_callback=AsyncMock(return_value=0.0),
        claude_callback_kwargs={},
        codex_transport_module=types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=_execute_codex,
        ),
        codex_config=CodexConfig(max_retries=1),
        codex_home=tmp_path / "codex-home",
        checkpoint_create=_create_checkpoint,
        checkpoint_diff=_diff_checkpoints,
    )

    assert result["provider"] == "codex"
    assert result["cost"] == pytest.approx(0.07)
    assert attempts == [tmp_path / "codex-home", None]
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8") == "fixed\n"


def test_cli_appserver_unstable_helper_writes_canonical_failure_reason(
    tmp_path: Path,
) -> None:
    unstable_cls = getattr(appserver, "CodexAppserverUnstableError", None)
    assert unstable_cls is not None
    agent_team_dir = _seed_failed_state(tmp_path)

    handler = getattr(cli_mod, "_handle_codex_appserver_unstable_halt", None)
    assert handler is not None
    handler(
        caught_exc=unstable_cls(
            "app-server stdout EOF - subprocess exited",
            thread_id="thread-repeat",
            turn_id="turn-repeat",
        ),
        cwd=str(tmp_path),
        config=cli_mod.AgentTeamConfig(),
    )

    final = load_state(str(agent_team_dir))
    assert final is not None
    entry = final.milestone_progress.get("milestone-1")
    assert isinstance(entry, dict)
    assert entry.get("status") == "FAILED"
    assert entry.get("failure_reason") == "codex_appserver_unstable"


def test_cli_appserver_unstable_helper_resolves_exception_milestone_without_state_lists(
    tmp_path: Path,
) -> None:
    unstable = appserver.CodexAppserverUnstableError(
        "app-server stdout EOF - subprocess exited",
        thread_id="thread-parallel",
        turn_id="turn-parallel",
        milestone_id="milestone-1",
    )

    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    state = RunState()
    state.current_milestone = ""
    state.failed_milestones = []
    state.milestone_progress["milestone-1"] = {"status": "IN_PROGRESS"}
    cli_mod._current_state = state
    save_state(state, directory=str(agent_team_dir))

    cli_mod._handle_codex_appserver_unstable_halt(
        caught_exc=unstable,
        cwd=str(tmp_path),
        config=cli_mod.AgentTeamConfig(),
    )

    final = load_state(str(agent_team_dir))
    assert final is not None
    entry = final.milestone_progress.get("milestone-1")
    assert isinstance(entry, dict)
    assert entry.get("status") == "FAILED"
    assert entry.get("failure_reason") == "codex_appserver_unstable"
    assert entry.get("audit_status") == "unknown"


def test_provider_router_retry_exhaust_static_raise_uses_new_class() -> None:
    src = inspect.getsource(provider_router._execute_codex_wave)
    assert "CodexAppserverUnstableError" in src
    assert re.search(
        r"retry_budget\s*<=\s*0[\s\S]{0,900}?raise\s+_CodexAppserverUnstableError",
        src,
    ), "retry-exhausted transport stdout EOF must raise CodexAppserverUnstableError"


def test_cli_top_level_repeated_eof_branch_exits_2_static_lock() -> None:
    src = inspect.getsource(cli_mod)
    assert "CodexAppserverUnstableError" in src
    assert "codex_appserver_unstable" in src
    assert re.search(
        r"repeated_eof[\s\S]{0,2500}?_handle_codex_appserver_unstable_halt"
        r"[\s\S]{0,1200}?sys\.exit\(\s*2\s*\)",
        src,
    ), "top-level repeated EOF branch must finalize and sys.exit(2)"


def test_run_prd_milestones_wave_exception_rethrows_repeated_eof_static_lock() -> None:
    src = inspect.getsource(cli_mod._run_prd_milestones)
    wait_for_wave = src.index("wave_result = await asyncio.wait_for(")
    wave_call = src.index("execute_milestone_waves(", wait_for_wave)
    wave_region = src[wave_call:]
    progress_comment = wave_region.index("# Save progress for resume on unexpected errors")
    catch_marker = "except Exception as exc:"
    catch_start = wave_region.rindex(catch_marker, 0, progress_comment)
    catch_region = wave_region[catch_start:]
    before_progress_save = catch_region.split("_save_milestone_progress", 1)[0]

    assert "_is_repeated_codex_appserver_eof" in before_progress_save
    assert re.search(
        r"if\s+_is_repeated_codex_appserver_eof\(\s*exc\s*\):\s*\n\s*raise",
        before_progress_save,
    ), "milestone wave catch must re-raise repeated EOF before saving normal failure progress"


@pytest.mark.asyncio
async def test_execute_parallel_group_rethrows_codex_appserver_unstable(
    tmp_path: Path,
) -> None:
    milestone = types.SimpleNamespace(id="milestone-1", parallel_group="group-a")
    worktree_info = types.SimpleNamespace(
        milestone_id="milestone-1",
        worktree_path=tmp_path / "worktree-milestone-1",
        status="PENDING",
    )
    worktree_info.worktree_path.mkdir()

    async def _execute_single_milestone(**_kwargs: Any) -> Any:
        raise appserver.CodexAppserverUnstableError(
            "app-server stdout EOF - subprocess exited",
            thread_id="thread-parallel",
            turn_id="turn-parallel",
        )

    with pytest.raises(appserver.CodexAppserverUnstableError) as excinfo:
        await parallel_executor.execute_parallel_group(
            milestones=[milestone],
            config=types.SimpleNamespace(v18=types.SimpleNamespace(max_parallel_milestones=1)),
            cwd=str(tmp_path),
            execute_single_milestone=_execute_single_milestone,
            create_worktree=lambda *_args, **_kwargs: worktree_info,
            remove_worktree=lambda *_args, **_kwargs: None,
            promote_worktree_outputs=lambda *_args, **_kwargs: None,
            execute_merge_queue=AsyncMock(return_value=[]),
            build_merge_order=lambda *_args, **_kwargs: [],
            create_snapshot_commit=lambda *_args, **_kwargs: "base-commit",
            get_main_branch=lambda *_args, **_kwargs: "main",
            merged_milestone_ids=[],
        )

    assert excinfo.value.thread_id == "thread-parallel"
    assert excinfo.value.turn_id == "turn-parallel"
    assert excinfo.value.repeated_eof is True


def test_parallel_executor_repeated_eof_static_lock() -> None:
    src = inspect.getsource(parallel_executor.execute_parallel_group)
    assert "_is_codex_appserver_unstable_error" in src
    assert re.search(
        r"except\s+Exception\s+as\s+exc:[\s\S]{0,400}?"
        r"if\s+_is_codex_appserver_unstable_error\(\s*exc\s*\):\s*\n\s*raise",
        src,
    ), "parallel worktree catch must re-raise repeated EOF before returning a failed milestone"
    assert re.search(
        r"if\s+isinstance\(\s*item\s*,\s*Exception\s*\):[\s\S]{0,400}?"
        r"if\s+_is_codex_appserver_unstable_error\(\s*item\s*\):\s*\n\s*raise\s+item",
        src,
    ), "parallel gather result handling must re-raise repeated EOF exceptions"


def test_run_prd_milestones_parallel_group_catch_rethrows_repeated_eof_static_lock() -> None:
    src = inspect.getsource(cli_mod._run_prd_milestones)
    parallel_start = src.index("if parallel_isolation_enabled:")
    group_call = src.index("group_result = await execute_parallel_group(", parallel_start)
    group_region = src[group_call:]
    catch_marker = "except Exception as exc:"
    catch_start = group_region.index(catch_marker)
    catch_region = group_region[catch_start:]
    before_downgrade = catch_region.split("group_result = None", 1)[0]

    assert "_is_repeated_codex_appserver_eof" in before_downgrade
    assert re.search(
        r"if\s+_is_repeated_codex_appserver_eof\(\s*exc\s*\):\s*\n\s*raise",
        before_downgrade,
    ), "CLI parallel group catch must re-raise repeated EOF before parallel_milestone_merge_failed"


def test_appserver_unstable_halt_static_lock_resolves_empty_state_from_exception() -> None:
    src = inspect.getsource(cli_mod._handle_codex_appserver_unstable_halt)
    first_empty_return = src.index("if not ms_id:")
    exception_lookup = src.index('getattr(caught_exc, "milestone_id"')

    assert exception_lookup < first_empty_return
    assert "codex_appserver_unstable" in src
    assert "agent_team_dir=str(Path(cwd) / \".agent-team\")" in src


@pytest.mark.asyncio
async def test_execute_wave_sdk_provider_route_propagates_retry_exhausted_eof(
    tmp_path: Path,
) -> None:
    unstable_cls = appserver.CodexAppserverUnstableError
    (tmp_path / "marker.txt").write_text("synthetic\n", encoding="utf-8")

    async def _sdk_call(*_args: Any, **_kwargs: Any) -> float:
        return 0.0

    async def _execute_codex(*_args: Any, **_kwargs: Any) -> Any:
        raise appserver.CodexTerminalTurnError(
            "app-server stdout EOF - subprocess exited",
            thread_id="thread-sdk-route",
            turn_id="turn-sdk-route",
        )

    routing = {
        "provider_map": WaveProviderMap(B="codex"),
        "codex_transport": types.SimpleNamespace(
            is_codex_available=lambda: True,
            execute_codex=_execute_codex,
        ),
        "codex_config": CodexConfig(max_retries=0),
        "codex_home": tmp_path / "codex-home",
        "checkpoint_create": lambda label, cwd: _create_checkpoint(label, cwd),
        "checkpoint_diff": _diff_checkpoints,
    }

    with pytest.raises(unstable_cls) as excinfo:
        await we_mod._execute_wave_sdk(
            execute_sdk_call=_sdk_call,
            wave_letter="B",
            prompt="wire backend",
            config=_config_with_v18_flags(),
            cwd=str(tmp_path),
            milestone=types.SimpleNamespace(id="milestone-1", title="Test"),
            provider_routing=routing,
        )

    assert excinfo.value.thread_id == "thread-sdk-route"
    assert excinfo.value.turn_id == "turn-sdk-route"
    assert excinfo.value.repeated_eof is True


@pytest.mark.asyncio
async def test_parallel_repeated_eof_top_level_halt_writes_state_from_exception_milestone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    milestone = types.SimpleNamespace(
        id="milestone-1",
        title="Parallel target",
        status="PENDING",
        dependencies=[],
        parallel_group="alpha",
        ac_refs=[],
        template="full_stack",
    )

    class _Plan:
        milestones = [milestone]

        def all_complete(self) -> bool:
            return False

        def get_ready_milestones(self) -> list[Any]:
            return [milestone] if milestone.status == "PENDING" else []

    config = cli_mod.AgentTeamConfig()
    config.v18.git_isolation = True
    config.v18.max_parallel_milestones = 1
    config.v18.execution_mode = "phase4_parallel"
    config.runtime_verification.enabled = False
    config.schema_validation.enabled = False
    config.quality_validation.enabled = False
    config.audit_team.enabled = False

    req_dir = tmp_path / config.convergence.requirements_dir
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / config.convergence.master_plan_file).write_text("# MASTER PLAN\n", encoding="utf-8")

    state = RunState(task="demo")
    state.current_milestone = ""
    state.failed_milestones = []
    state.milestone_progress["milestone-1"] = {"status": "IN_PROGRESS"}
    cli_mod._current_state = state
    save_state(state, directory=str(tmp_path / ".agent-team"))

    import agent_team_v15.milestone_manager as mm_module
    import agent_team_v15.parallel_executor as pe_module
    import agent_team_v15.worktree_manager as wt_module

    monkeypatch.setattr(mm_module, "MilestoneManager", lambda _root: types.SimpleNamespace())
    monkeypatch.setattr(mm_module, "parse_master_plan", lambda _content: _Plan())
    monkeypatch.setattr(mm_module, "update_master_plan_status", lambda content, *_args: content)
    monkeypatch.setattr(
        mm_module,
        "compute_rollup_health",
        lambda plan: {"complete": 0, "total": len(plan.milestones), "failed": 0, "health": "healthy"},
    )
    monkeypatch.setattr(mm_module, "aggregate_milestone_convergence", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mm_module, "build_milestone_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mm_module, "render_predecessor_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mm_module, "normalize_milestone_dirs", lambda *_args, **_kwargs: 0)

    monkeypatch.setattr(wt_module, "ensure_git_initialized", lambda _cwd: True)
    monkeypatch.setattr(wt_module, "get_main_branch", lambda _cwd: "master")
    monkeypatch.setattr(wt_module, "cleanup_all_worktrees", lambda _cwd: None)
    monkeypatch.setattr(wt_module, "create_snapshot_commit", lambda *_args, **_kwargs: "abc123")
    monkeypatch.setattr(wt_module, "create_worktree", lambda *_args, **_kwargs: types.SimpleNamespace())
    monkeypatch.setattr(wt_module, "remove_worktree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(wt_module, "promote_worktree_outputs", lambda *_args, **_kwargs: None)

    async def _raise_repeated_eof(**_kwargs: Any) -> Any:
        unstable = appserver.CodexAppserverUnstableError(
            "app-server stdout EOF - subprocess exited",
            thread_id="thread-parallel",
            turn_id="turn-parallel",
            milestone_id="milestone-1",
        )
        raise unstable

    monkeypatch.setattr(pe_module, "execute_parallel_group", _raise_repeated_eof)

    async def _run_top_level_halt_branch() -> None:
        try:
            await cli_mod._run_prd_milestones(
                task="demo",
                config=config,
                cwd=str(tmp_path),
                depth="standard",
                prd_path=None,
            )
        except BaseException as caught:
            if cli_mod._is_repeated_codex_appserver_eof(caught):
                cli_mod._handle_codex_appserver_unstable_halt(
                    caught_exc=caught,
                    cwd=str(tmp_path),
                    config=config,
                )
                raise SystemExit(2) from caught
            raise

    with pytest.raises(SystemExit) as excinfo:
        await _run_top_level_halt_branch()

    assert excinfo.value.code == 2
    final = load_state(str(tmp_path / ".agent-team"))
    assert final is not None
    entry = final.milestone_progress.get("milestone-1")
    assert isinstance(entry, dict)
    assert entry.get("status") == "FAILED"
    assert entry.get("failure_reason") == "codex_appserver_unstable"
    assert entry.get("audit_status") == "unknown"


@pytest.mark.asyncio
async def test_invoke_provider_repeated_eof_bypasses_watchdog_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unstable = appserver.CodexAppserverUnstableError(
        "app-server stdout EOF - subprocess exited",
        thread_id="thread-progress",
        turn_id="turn-progress",
    )

    async def _sdk_call(*_args: Any, **_kwargs: Any) -> float:
        return 0.0

    async def _fake_execute_wave_with_provider(*, progress_callback: Any, **_kwargs: Any) -> Any:
        progress_callback(
            message_type="item/started",
            tool_name="commandExecution",
            tool_id="call-repeat-eof",
            event_kind="start",
        )
        state = progress_callback.__self__
        state.pending_tool_starts["call-repeat-eof"]["started_monotonic"] = (
            time.monotonic() - 1700
        )
        state.last_tool_call_monotonic = time.monotonic() - 1700
        raise unstable

    monkeypatch.setattr(
        provider_router,
        "execute_wave_with_provider",
        _fake_execute_wave_with_provider,
    )

    with pytest.raises(appserver.CodexAppserverUnstableError) as excinfo:
        await we_mod._invoke_provider_wave_with_watchdog(
            execute_sdk_call=_sdk_call,
            prompt="wire backend",
            wave_letter="B",
            config=_config_with_v18_flags(),
            cwd=str(tmp_path),
            milestone=types.SimpleNamespace(id="milestone-1", title="Test"),
            provider_routing={
                "provider_map": WaveProviderMap(B="codex"),
                "codex_transport": types.SimpleNamespace(),
                "codex_config": CodexConfig(max_retries=0),
                "codex_home": tmp_path / "codex-home",
            },
            bootstrap_eligible=False,
        )

    assert excinfo.value is unstable
    hang_dir = tmp_path / ".agent-team" / "hang_reports"
    assert not list(hang_dir.glob("wave-B-*.json")) if hang_dir.is_dir() else True
