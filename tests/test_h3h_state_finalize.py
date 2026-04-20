from __future__ import annotations

import json

import pytest

from agent_team_v15.config import V18Config
from agent_team_v15.state import RunState, StateInvariantError, save_state, update_milestone_progress


def test_save_state_reconciles_poisoned_summary_when_flag_enabled(tmp_path) -> None:
    state = RunState(
        task="demo",
        interrupted=False,
        failed_milestones=["milestone-1"],
        summary={"success": True},
        v18_config=V18Config(state_finalize_invariant_enforcement_enabled=True),
    )

    save_state(state, directory=str(tmp_path))

    data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
    assert data["failed_milestones"] == ["milestone-1"]
    assert data["summary"]["success"] is False


def test_save_state_preserves_legacy_invariant_raise_when_flag_off(tmp_path) -> None:
    state = RunState(
        task="demo",
        interrupted=False,
        failed_milestones=["milestone-1"],
        summary={"success": True},
        v18_config=V18Config(state_finalize_invariant_enforcement_enabled=False),
    )

    with pytest.raises(StateInvariantError):
        save_state(state, directory=str(tmp_path))


def test_save_wave_state_reconciles_summary_before_write(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import cli as cli_mod

    state = RunState(
        task="demo",
        failed_milestones=["milestone-1"],
        summary={"success": True},
        v18_config=V18Config(state_finalize_invariant_enforcement_enabled=True),
    )
    monkeypatch.setattr(cli_mod, "_current_state", state)

    cli_mod._save_wave_state(
        str(tmp_path),
        "milestone-1",
        "B",
        "FAILED",
        artifact_path="artifacts/milestone-1-wave-B.json",
    )

    data = json.loads((tmp_path / ".agent-team" / "STATE.json").read_text(encoding="utf-8"))
    progress = data["wave_progress"]["milestone-1"]
    assert data["summary"]["success"] is False
    assert data["failed_milestones"] == ["milestone-1"]
    assert progress["failed_wave"] == "B"
    assert progress["wave_artifacts"]["B"] == "artifacts/milestone-1-wave-B.json"


def test_save_wave_state_replays_wave_a_success_then_wave_b_failure_without_invariant(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import cli as cli_mod

    state = RunState(
        task="demo",
        summary={"success": True},
        v18_config=V18Config(state_finalize_invariant_enforcement_enabled=True),
    )
    monkeypatch.setattr(cli_mod, "_current_state", state)

    cli_mod._save_wave_state(
        str(tmp_path),
        "milestone-1",
        "A",
        "COMPLETE",
        artifact_path="artifacts/milestone-1-wave-A.json",
    )
    update_milestone_progress(state, "milestone-1", "FAILED")
    state.summary = {"success": True}
    save_state(state, directory=str(tmp_path / ".agent-team"))
    cli_mod._save_wave_state(
        str(tmp_path),
        "milestone-1",
        "B",
        "FAILED",
        artifact_path="artifacts/milestone-1-wave-B.json",
    )

    data = json.loads((tmp_path / ".agent-team" / "STATE.json").read_text(encoding="utf-8"))
    progress = data["wave_progress"]["milestone-1"]
    assert progress["completed_waves"] == ["A"]
    assert progress["failed_wave"] == "B"
    assert data["failed_milestones"] == ["milestone-1"]
    assert data["summary"]["success"] is False


def test_finalize_helper_logs_and_swallows_finalize_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import cli as cli_mod

    class _ExplodingState:
        def __init__(self) -> None:
            self.v18_config = V18Config(state_finalize_invariant_enforcement_enabled=True)

        def finalize(self, agent_team_dir=None) -> None:
            del agent_team_dir
            raise RuntimeError("boom")

    warnings: list[str] = []
    monkeypatch.setattr(cli_mod, "print_warning", warnings.append)

    cli_mod._finalize_state_before_save(
        _ExplodingState(),
        agent_team_dir=tmp_path,
        context="wave state save_state()",
    )

    assert warnings
    assert "[STATE] finalize() raised before wave state save_state()" in warnings[0]
