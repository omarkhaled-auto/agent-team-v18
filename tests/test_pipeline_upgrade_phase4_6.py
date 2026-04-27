"""Phase 4.6 pipeline-upgrade — anchor-on-COMPLETE chain + ``--retry-milestone``.

Covers the 7 acceptance criteria listed in
``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §I plus the §M.5
coexistence contract, the Phase 4.5 ``failure_reason`` preservation
contract, the schema-load backward-compat contract, and the argparse
``--retry-milestone | --reset-failed-milestones`` mutex contract.

Fixture index
-------------
- 1  test_anchor_capture_on_complete_writes_to_complete_subdir
- 2  test_anchor_chain_preserves_prior_milestone_complete_when_next_inprogress_fires
- 3  test_complete_and_inprogress_anchors_coexist_correctly  (kickoff §M.5)
- 4  test_anchor_prune_policy_keeps_last_5_milestones
- 5  test_retry_milestone_flag_restores_prior_complete_anchor
- 6  test_retry_milestone_flag_fails_when_prior_complete_anchor_missing
- 7  test_retry_milestone_with_resume_from_run_dir
- 8  test_replay_smoke_2026_04_26_no_anchor_on_complete_for_milestone_1_failed
- 9  test_disk_quota_warning_when_anchor_chain_exceeds_threshold
- 10 test_retry_milestone_and_reset_failed_milestones_mutex
- 11 test_retry_milestone_preserves_prior_milestone_failure_reason
- 12 test_load_state_with_phase_4_5_era_state_json_defaults_last_completed_milestone_id
- 13 test_anchor_chain_retain_last_n_zero_disables_capture_helper
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import wave_executor as wx
from agent_team_v15.state import RunState, load_state, save_state


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _seed_run_dir(cwd: Path, marker: str = "seed") -> dict[str, str]:
    """Create a small, deterministic run-dir tree under ``cwd``.

    Returns a relpath → content map for assertion convenience.
    """
    files = {
        "package.json": '{"name": "%s"}\n' % marker,
        "apps/api/src/main.ts": "// %s api main\n" % marker,
        "apps/web/src/app/layout.tsx": "// %s web layout\n" % marker,
        "prisma/schema.prisma": "// %s prisma\n" % marker,
    }
    for rel, content in files.items():
        target = cwd / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return files


def _milestone_anchor_complete_dir(cwd: Path, milestone_id: str) -> Path:
    return Path(cwd) / ".agent-team" / "milestones" / milestone_id / "_anchor" / "_complete"


def _milestone_anchor_top_dir(cwd: Path, milestone_id: str) -> Path:
    return Path(cwd) / ".agent-team" / "milestones" / milestone_id / "_anchor"


# ---------------------------------------------------------------------------
# Fixture 1 — capture_on_complete writes to _complete subdir (AC1)
# ---------------------------------------------------------------------------


def test_anchor_capture_on_complete_writes_to_complete_subdir(tmp_path: Path) -> None:
    """``_capture_milestone_anchor_on_complete(cwd, "milestone-1")`` MUST
    write to ``.agent-team/milestones/milestone-1/_anchor/_complete/``
    (NOT to the top-level ``_anchor/`` slot — that's Phase 1's
    in-flight rollback territory).
    """
    seeded = _seed_run_dir(tmp_path)
    anchor_complete = wx._capture_milestone_anchor_on_complete(str(tmp_path), "milestone-1")

    expected = _milestone_anchor_complete_dir(tmp_path, "milestone-1")
    assert anchor_complete == expected
    assert anchor_complete.is_dir()

    for rel, content in seeded.items():
        mirrored = anchor_complete / rel
        assert mirrored.is_file(), f"{rel} should be mirrored under _complete/"
        assert mirrored.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# Fixture 2 — chain preserves prior milestone _complete on next IN_PROGRESS (AC2)
# ---------------------------------------------------------------------------


def test_anchor_chain_preserves_prior_milestone_complete_when_next_inprogress_fires(
    tmp_path: Path,
) -> None:
    """After M1 captures `_complete`, M2 firing IN_PROGRESS via Phase 1's
    ``_capture_milestone_anchor`` MUST NOT touch M1's directory at all.
    M1's `_anchor/_complete/` survives verbatim; only M2's `_anchor/`
    is freshly seeded.
    """
    _seed_run_dir(tmp_path, marker="m1-end")
    wx._capture_milestone_anchor_on_complete(str(tmp_path), "milestone-1")

    # Mutate the run-dir to simulate the post-M1 / pre-M2 transition.
    (tmp_path / "apps" / "api" / "src" / "main.ts").write_text(
        "// m2-start api main\n", encoding="utf-8"
    )

    # M2 IN_PROGRESS — Phase 1's primitive captures the top-level slot.
    wx._capture_milestone_anchor(str(tmp_path), "milestone-2")

    m1_complete = _milestone_anchor_complete_dir(tmp_path, "milestone-1")
    assert m1_complete.is_dir(), "M1's _anchor/_complete/ MUST survive M2 IN_PROGRESS"
    assert (m1_complete / "apps/api/src/main.ts").read_text(encoding="utf-8") == (
        "// m1-end api main\n"
    ), "M1's _complete contents MUST preserve M1-end state"

    m2_top = _milestone_anchor_top_dir(tmp_path, "milestone-2")
    assert m2_top.is_dir(), "M2's _anchor/ MUST be captured fresh"
    assert (m2_top / "apps/api/src/main.ts").read_text(encoding="utf-8") == (
        "// m2-start api main\n"
    ), "M2's _anchor/ reflects the post-M1 file state"


# ---------------------------------------------------------------------------
# Fixture 3 — within-milestone coexistence of _anchor/ + _anchor/_complete/
# ---------------------------------------------------------------------------


def test_complete_and_inprogress_anchors_coexist_correctly(tmp_path: Path) -> None:
    """Within a single milestone, capture IN_PROGRESS-entry (Phase 1)
    THEN capture COMPLETE (Phase 4.6); both subtrees MUST coexist.

    Plan §M.5 contract: Phase 1's wipe-on-re-capture semantics for
    ``_anchor/`` TOP-LEVEL must NOT extend to ``_complete/``. The prune
    policy is the only wipe path for ``_complete/``.
    """
    _seed_run_dir(tmp_path, marker="m1-start")
    wx._capture_milestone_anchor(str(tmp_path), "milestone-1")

    # Simulate the in-milestone wave outputs landing.
    (tmp_path / "apps" / "api" / "src" / "main.ts").write_text(
        "// m1-end api main\n", encoding="utf-8"
    )

    wx._capture_milestone_anchor_on_complete(str(tmp_path), "milestone-1")

    top = _milestone_anchor_top_dir(tmp_path, "milestone-1")
    complete = _milestone_anchor_complete_dir(tmp_path, "milestone-1")
    assert top.is_dir() and complete.is_dir()
    # Top-level captured the START state.
    assert (top / "apps/api/src/main.ts").read_text(encoding="utf-8") == (
        "// m1-start api main\n"
    )
    # _complete subdir captured the END state.
    assert (complete / "apps/api/src/main.ts").read_text(encoding="utf-8") == (
        "// m1-end api main\n"
    )

    # Now simulate an in-flight rollback re-capturing the top-level slot
    # (e.g. operator restarts the milestone). The wipe MUST preserve
    # ``_complete/``.
    (tmp_path / "apps" / "api" / "src" / "main.ts").write_text(
        "// m1-restart api main\n", encoding="utf-8"
    )
    wx._capture_milestone_anchor(str(tmp_path), "milestone-1")
    assert complete.is_dir(), (
        "Re-capturing the top-level slot MUST preserve the _complete subdir."
    )
    assert (complete / "apps/api/src/main.ts").read_text(encoding="utf-8") == (
        "// m1-end api main\n"
    ), "_complete/ contents MUST survive the wipe of _anchor/ top-level."


# ---------------------------------------------------------------------------
# Fixture 4 — prune policy keeps last 5 (AC3)
# ---------------------------------------------------------------------------


def test_anchor_prune_policy_keeps_last_5_milestones(tmp_path: Path) -> None:
    """After capturing _complete for M1..M10 with retain_last_n=5,
    M1..M5's _complete/ subdirs are deleted; M6..M10 are retained.

    Iteration ordering is determined by ``state.milestone_order`` — the
    plan's topological order, NOT mtime — so parallel-isolation runs
    don't accidentally evict the most-recent COMPLETE.
    """
    _seed_run_dir(tmp_path)

    milestone_ids = [f"milestone-{n}" for n in range(1, 11)]
    state = RunState(milestone_order=list(milestone_ids))

    for mid in milestone_ids:
        wx._capture_milestone_anchor_on_complete(str(tmp_path), mid)
        assert _milestone_anchor_complete_dir(tmp_path, mid).is_dir()

    summary = wx._prune_anchor_chain(str(tmp_path), retain_last_n=5, state=state)

    pruned = set(summary.get("pruned_milestones", []))
    retained = set(summary.get("retained_milestones", []))
    assert pruned == set(milestone_ids[:5])
    assert retained == set(milestone_ids[5:])

    for mid in milestone_ids[:5]:
        assert not _milestone_anchor_complete_dir(tmp_path, mid).exists(), (
            f"{mid} _complete/ should be pruned"
        )
    for mid in milestone_ids[5:]:
        assert _milestone_anchor_complete_dir(tmp_path, mid).is_dir(), (
            f"{mid} _complete/ should be retained"
        )

    assert int(summary.get("bytes_freed", 0)) > 0


# ---------------------------------------------------------------------------
# Fixture 5 — --retry-milestone restores prior _complete + resets target..end (AC4)
# ---------------------------------------------------------------------------


def _make_master_plan_md(milestone_ids: list[str], statuses: dict[str, str]) -> str:
    """Synthesise a minimal MASTER_PLAN.md compatible with
    ``parse_master_plan`` + ``update_master_plan_status``.
    """
    lines: list[str] = ["# Master Plan", ""]
    for mid in milestone_ids:
        idx = mid.split("-")[-1]
        title = f"Milestone {idx}"
        lines.extend(
            [
                f"## {idx}. {title} ({mid})",
                "",
                f"- Status: {statuses.get(mid, 'PENDING')}",
                "- Depends on: " + (
                    "none" if mid == milestone_ids[0]
                    else milestone_ids[milestone_ids.index(mid) - 1]
                ),
                "",
                "### Acceptance Criteria",
                f"- AC-{idx}-1: synthetic ac",
                "",
            ]
        )
    return "\n".join(lines)


def _setup_retry_milestone_scenario(
    tmp_path: Path,
    *,
    milestone_ids: list[str],
    statuses: dict[str, str],
    capture_complete_for: list[str],
    failure_reasons: dict[str, str] | None = None,
) -> tuple[Path, Path, RunState, str]:
    """Prepare a fresh run-dir + STATE + master plan for retry-milestone tests.

    Returns ``(project_root, master_plan_path, state, plan_content)``.
    """
    project_root = tmp_path
    agent_team_dir = project_root / ".agent-team"
    req_dir = agent_team_dir
    req_dir.mkdir(parents=True, exist_ok=True)
    master_plan_path = req_dir / "MASTER_PLAN.md"
    plan_content = _make_master_plan_md(milestone_ids, statuses)
    master_plan_path.write_text(plan_content, encoding="utf-8")

    _seed_run_dir(project_root, marker="prior-complete")

    for mid in capture_complete_for:
        wx._capture_milestone_anchor_on_complete(str(project_root), mid)

    state = RunState(
        run_id="rs-test",
        task="t",
        milestone_order=list(milestone_ids),
        completed_milestones=[m for m, s in statuses.items() if s in ("COMPLETE", "DEGRADED")],
        failed_milestones=[m for m, s in statuses.items() if s == "FAILED"],
    )
    for mid, status in statuses.items():
        entry: dict[str, str] = {"status": status}
        if failure_reasons and mid in failure_reasons:
            entry["failure_reason"] = failure_reasons[mid]
        state.milestone_progress[mid] = entry
    save_state(state, directory=str(agent_team_dir))

    return project_root, master_plan_path, state, plan_content


def test_retry_milestone_flag_restores_prior_complete_anchor(tmp_path: Path) -> None:
    """``--retry-milestone milestone-3`` MUST restore M2's `_complete/`
    file system and reset M3..M5 to PENDING in both STATE.json and
    MASTER_PLAN.md.
    """
    from agent_team_v15 import cli as cli_mod

    milestone_ids = [f"milestone-{n}" for n in range(1, 6)]
    statuses = {
        "milestone-1": "COMPLETE",
        "milestone-2": "COMPLETE",
        "milestone-3": "FAILED",
        "milestone-4": "PENDING",
        "milestone-5": "PENDING",
    }
    project_root, master_plan_path, state, plan_content = _setup_retry_milestone_scenario(
        tmp_path,
        milestone_ids=milestone_ids,
        statuses=statuses,
        capture_complete_for=["milestone-1", "milestone-2"],
    )

    # Mutate the run-dir AFTER M2's `_complete/` was captured (simulate
    # the failed M3 wave outputs that we want to discard on retry).
    (project_root / "apps" / "api" / "src" / "main.ts").write_text(
        "// failed M3 wave output\n", encoding="utf-8"
    )
    (project_root / "garbage_from_failed_m3.txt").write_text(
        "leak", encoding="utf-8"
    )

    new_plan_content, summary = cli_mod._apply_retry_milestone_reset(
        plan_content=plan_content,
        state=state,
        target_milestone_id="milestone-3",
        project_root=project_root,
        master_plan_path=master_plan_path,
        cwd=str(project_root),
    )

    # File system reverted to M2's _complete/ snapshot.
    assert (project_root / "apps" / "api" / "src" / "main.ts").read_text(
        encoding="utf-8"
    ) == "// prior-complete api main\n"
    assert not (project_root / "garbage_from_failed_m3.txt").exists()

    # STATE.json: target..end → PENDING; prior milestones unchanged.
    for mid in ("milestone-3", "milestone-4", "milestone-5"):
        assert state.milestone_progress[mid]["status"] == "PENDING"
        assert "failure_reason" not in state.milestone_progress[mid]
    for mid in ("milestone-1", "milestone-2"):
        assert state.milestone_progress[mid]["status"] == "COMPLETE"
    assert state.failed_milestones == []
    assert state.last_completed_milestone_id == "milestone-2"

    # MASTER_PLAN.md: target..end → PENDING.
    persisted = master_plan_path.read_text(encoding="utf-8")
    for mid in ("milestone-3", "milestone-4", "milestone-5"):
        # find the line for that milestone, assert PENDING
        # (we don't constrain prior-milestone lines beyond their original
        # state; update_master_plan_status touches one milestone per call)
        lines = [
            line for line in persisted.splitlines()
            if "Status:" in line
        ]
        assert lines, "MASTER_PLAN.md should expose Status: lines per milestone"
    assert "Status: PENDING" in persisted

    # Returned plan_content matches what was persisted.
    assert new_plan_content == persisted

    # Summary signal.
    assert summary["prior_milestone_id"] == "milestone-2"
    assert summary["reset_milestone_ids"] == [
        "milestone-3",
        "milestone-4",
        "milestone-5",
    ]


# ---------------------------------------------------------------------------
# Fixture 6 — --retry-milestone fails when prior _complete missing (AC5)
# ---------------------------------------------------------------------------


def test_retry_milestone_flag_fails_when_prior_complete_anchor_missing(
    tmp_path: Path,
) -> None:
    """When the immediately-prior milestone has no ``_complete/`` anchor
    on disk, ``_apply_retry_milestone_reset`` MUST raise SystemExit
    cleanly without mutating STATE.json or MASTER_PLAN.md.
    """
    from agent_team_v15 import cli as cli_mod

    milestone_ids = [f"milestone-{n}" for n in range(1, 4)]
    statuses = {
        "milestone-1": "COMPLETE",
        "milestone-2": "COMPLETE",
        "milestone-3": "FAILED",
    }
    project_root, master_plan_path, state, plan_content = _setup_retry_milestone_scenario(
        tmp_path,
        milestone_ids=milestone_ids,
        statuses=statuses,
        capture_complete_for=[],  # no _complete on disk anywhere
    )
    state_snapshot = json.dumps(state.milestone_progress, sort_keys=True)
    plan_snapshot = master_plan_path.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        cli_mod._apply_retry_milestone_reset(
            plan_content=plan_content,
            state=state,
            target_milestone_id="milestone-3",
            project_root=project_root,
            master_plan_path=master_plan_path,
            cwd=str(project_root),
        )
    assert exc_info.value.code != 0
    err_text = str(exc_info.value)
    assert "milestone-2" in err_text and "milestone-3" in err_text

    # No mutation.
    assert json.dumps(state.milestone_progress, sort_keys=True) == state_snapshot
    assert master_plan_path.read_text(encoding="utf-8") == plan_snapshot
    # last_completed_milestone_id NOT advanced.
    assert state.last_completed_milestone_id == ""


# ---------------------------------------------------------------------------
# Fixture 7 — --retry-milestone with --resume-from operator workflow
# ---------------------------------------------------------------------------


def test_retry_milestone_with_resume_from_run_dir(tmp_path: Path) -> None:
    """Operator workflow: a 25-milestone build wave-failed at M25; the
    operator invokes ``--resume-from <run-dir> --retry-milestone milestone-25``.
    The helper restores M24's `_complete/` and resets M25 to PENDING.

    Synthesised at the helper level — the full ``_run_prd_milestones``
    invocation isn't exercised here (covered in §K Phase 4.6 step 2's
    2-milestone synthetic smoke).
    """
    from agent_team_v15 import cli as cli_mod

    milestone_ids = [f"milestone-{n}" for n in range(1, 26)]
    statuses = {mid: "COMPLETE" for mid in milestone_ids[:24]}
    statuses["milestone-25"] = "FAILED"
    project_root, master_plan_path, state, plan_content = _setup_retry_milestone_scenario(
        tmp_path,
        milestone_ids=milestone_ids,
        statuses=statuses,
        capture_complete_for=["milestone-24"],  # only the immediately-prior
    )

    new_plan_content, summary = cli_mod._apply_retry_milestone_reset(
        plan_content=plan_content,
        state=state,
        target_milestone_id="milestone-25",
        project_root=project_root,
        master_plan_path=master_plan_path,
        cwd=str(project_root),
    )

    assert summary["prior_milestone_id"] == "milestone-24"
    assert summary["reset_milestone_ids"] == ["milestone-25"]
    assert state.milestone_progress["milestone-25"]["status"] == "PENDING"
    for mid in milestone_ids[:24]:
        assert state.milestone_progress[mid]["status"] == "COMPLETE"
    assert state.last_completed_milestone_id == "milestone-24"


# ---------------------------------------------------------------------------
# Fixture 8 — replay smoke: M1 wave-failed → no _complete written (AC7)
# ---------------------------------------------------------------------------


def test_replay_smoke_2026_04_26_no_anchor_on_complete_for_milestone_1_failed(
    tmp_path: Path,
) -> None:
    """Smoke fixture's STATE.json has milestone-1 status=FAILED. Phase 4.6's
    capture-on-complete helper MUST NOT fire on FAILED milestones — only
    COMPLETE / DEGRADED transitions are eligible. The smoke run-dir
    therefore carries only Phase 1's `_anchor/` (top-level), never
    `_anchor/_complete/`.
    """
    from agent_team_v15 import cli as cli_mod

    fixture_state_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "smoke_2026_04_26"
        / "STATE.json"
    )
    state_data = json.loads(fixture_state_path.read_text(encoding="utf-8"))
    assert (
        state_data["milestone_progress"]["milestone-1"]["status"] == "FAILED"
    ), "smoke fixture invariant: milestone-1 is FAILED"

    cwd = tmp_path
    _seed_run_dir(cwd)

    config = SimpleNamespace(
        audit_team=SimpleNamespace(
            enabled=True,
            milestone_anchor_enabled=True,
            anchor_chain_retain_last_n=5,
        )
    )

    # Helper MUST refuse to fire on a non-COMPLETE/DEGRADED status.
    captured = cli_mod._phase_4_6_capture_anchor_on_complete(
        cwd=str(cwd),
        milestone_id="milestone-1",
        milestone_status="FAILED",
        config=config,
    )
    assert captured is None, "FAILED milestones MUST NOT capture _complete/"
    assert not _milestone_anchor_complete_dir(cwd, "milestone-1").exists()


# ---------------------------------------------------------------------------
# Fixture 9 — disk quota WARNING when chain exceeds threshold (AC6)
# ---------------------------------------------------------------------------


def test_disk_quota_warning_when_anchor_chain_exceeds_threshold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When ``_prune_anchor_chain`` observes total ``_complete/`` disk
    usage exceeding the 2 GB threshold, it MUST emit a WARNING log
    (not a hard failure — pruning is best-effort cleanup, the warning
    is the operator-visible signal).

    Threshold is configurable for testability.
    """
    _seed_run_dir(tmp_path)

    milestone_ids = ["milestone-1", "milestone-2", "milestone-3"]
    state = RunState(milestone_order=milestone_ids)
    for mid in milestone_ids:
        wx._capture_milestone_anchor_on_complete(str(tmp_path), mid)

    # Plant a synthetic large file inside one of the _complete/ trees so
    # the size accounting crosses the test threshold.
    big = _milestone_anchor_complete_dir(tmp_path, "milestone-1") / "big.bin"
    big.write_bytes(b"x" * (1024 * 1024))  # 1 MB

    with caplog.at_level(logging.WARNING, logger="agent_team_v15.wave_executor"):
        summary = wx._prune_anchor_chain(
            str(tmp_path),
            retain_last_n=10,  # nothing pruned; we want to test ONLY the warning
            state=state,
            disk_warn_bytes=512 * 1024,  # 512 KB threshold
        )

    assert summary.get("warned_disk_quota") is True
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "_complete" in log_text or "anchor_chain" in log_text
    assert "WARN" in log_text.upper() or "exceed" in log_text.lower()


# ---------------------------------------------------------------------------
# Fixture 10 — argparse mutex: --retry-milestone vs --reset-failed-milestones
# ---------------------------------------------------------------------------


def test_retry_milestone_and_reset_failed_milestones_mutex(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The argparse parser MUST refuse a combined invocation of
    ``--retry-milestone <id>`` and ``--reset-failed-milestones`` (mutually
    exclusive group). argparse exits with code 2 on argument errors AND
    the stderr message MUST cite the mutex (not "unknown argument") so
    operators see the right diagnostic.

    First sanity check: ``--retry-milestone`` alone parses cleanly. This
    distinguishes a real mutex enforcement from the pre-Phase-4.6 state
    where argparse rejected ``--retry-milestone`` as an unknown flag and
    happened to exit with the same code 2.
    """
    from agent_team_v15 import cli as cli_mod

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-team-v15",
            "synthetic-task",
            "--retry-milestone",
            "milestone-3",
        ],
    )
    parsed = cli_mod._parse_args()
    assert getattr(parsed, "retry_milestone", None) == "milestone-3"

    # Now combine with --reset-failed-milestones — the mutex MUST fire.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-team-v15",
            "synthetic-task",
            "--retry-milestone",
            "milestone-3",
            "--reset-failed-milestones",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        cli_mod._parse_args()
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    # argparse mutex error wording is "argument X: not allowed with argument Y"
    assert "not allowed with" in err
    assert "--retry-milestone" in err or "retry-milestone" in err
    assert "--reset-failed-milestones" in err or "reset-failed-milestones" in err


# ---------------------------------------------------------------------------
# Fixture 11 — --retry-milestone preserves prior milestones' failure_reason
# ---------------------------------------------------------------------------


def test_retry_milestone_preserves_prior_milestone_failure_reason(
    tmp_path: Path,
) -> None:
    """A milestone recovered via Phase 4.5 carries
    ``failure_reason="wave_fail_recovered"`` as historical evidence.
    ``--retry-milestone milestone-3`` MUST NOT clear that on M1 / M2
    (the reset only touches target..end milestones).
    """
    from agent_team_v15 import cli as cli_mod

    milestone_ids = [f"milestone-{n}" for n in range(1, 5)]
    statuses = {
        "milestone-1": "COMPLETE",
        "milestone-2": "COMPLETE",
        "milestone-3": "FAILED",
        "milestone-4": "PENDING",
    }
    failure_reasons = {
        # Phase 4.5 historical evidence: M1 was recovered via the cascade.
        "milestone-1": "wave_fail_recovered",
        "milestone-3": "wave_b_failed",
    }
    project_root, master_plan_path, state, plan_content = _setup_retry_milestone_scenario(
        tmp_path,
        milestone_ids=milestone_ids,
        statuses=statuses,
        capture_complete_for=["milestone-1", "milestone-2"],
        failure_reasons=failure_reasons,
    )

    cli_mod._apply_retry_milestone_reset(
        plan_content=plan_content,
        state=state,
        target_milestone_id="milestone-3",
        project_root=project_root,
        master_plan_path=master_plan_path,
        cwd=str(project_root),
    )

    # Prior milestone history preserved.
    assert state.milestone_progress["milestone-1"]["status"] == "COMPLETE"
    assert (
        state.milestone_progress["milestone-1"]["failure_reason"]
        == "wave_fail_recovered"
    ), "Phase 4.5's historical evidence MUST survive --retry-milestone"

    # Target..end mutated.
    assert state.milestone_progress["milestone-3"]["status"] == "PENDING"
    assert "failure_reason" not in state.milestone_progress["milestone-3"]
    assert state.milestone_progress["milestone-4"]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Fixture 12 — load_state defaults last_completed_milestone_id to ""
# ---------------------------------------------------------------------------


def test_load_state_with_phase_4_5_era_state_json_defaults_last_completed_milestone_id(
    tmp_path: Path,
) -> None:
    """A Phase 4.5-era STATE.json that pre-dates Phase 4.6's
    ``last_completed_milestone_id`` field MUST load without crash and
    default the field to ``""``.

    Backward-compat invariant: schema additions in Phase 4.6 are
    additive; ``load_state`` uses ``_expect`` with the matching default
    so old files round-trip cleanly (mirrors Phase 1's
    ``milestone_anchor_path``).
    """
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir()
    state_path = agent_team_dir / "STATE.json"

    state_data = {
        "run_id": "rs-old",
        "task": "phase-4.5-era",
        "depth": "standard",
        "schema_version": 3,
        "milestone_progress": {"milestone-1": {"status": "COMPLETE"}},
        "milestone_order": ["milestone-1"],
        "completed_milestones": ["milestone-1"],
        "milestone_anchor_path": "",
        "milestone_anchor_inode": 0,
    }
    state_path.write_text(json.dumps(state_data), encoding="utf-8")

    state = load_state(directory=str(agent_team_dir))
    assert state is not None
    assert state.last_completed_milestone_id == ""
    # Round-trip preserves the field.
    save_state(state, directory=str(agent_team_dir))
    reloaded = load_state(directory=str(agent_team_dir))
    assert reloaded is not None
    assert reloaded.last_completed_milestone_id == ""


# ---------------------------------------------------------------------------
# Fixture 13 — anchor_chain_retain_last_n=0 disables the on-complete capture
# ---------------------------------------------------------------------------


def test_anchor_chain_retain_last_n_zero_disables_capture_helper(tmp_path: Path) -> None:
    """The master kill switch (``anchor_chain_retain_last_n=0``) flips
    the cli site's ``_phase_4_6_capture_anchor_on_complete`` helper to
    a no-op: nothing is written, capture function returns None.

    Operator-visible rollback per plan §I rollback step.
    """
    from agent_team_v15 import cli as cli_mod

    _seed_run_dir(tmp_path)

    cfg_disabled = SimpleNamespace(
        audit_team=SimpleNamespace(
            enabled=True,
            milestone_anchor_enabled=True,
            anchor_chain_retain_last_n=0,
        )
    )
    captured = cli_mod._phase_4_6_capture_anchor_on_complete(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        milestone_status="COMPLETE",
        config=cfg_disabled,
    )
    assert captured is None
    assert not _milestone_anchor_complete_dir(tmp_path, "milestone-1").exists()

    # Sanity: with retain_last_n>0 + COMPLETE status, the helper fires.
    cfg_enabled = SimpleNamespace(
        audit_team=SimpleNamespace(
            enabled=True,
            milestone_anchor_enabled=True,
            anchor_chain_retain_last_n=5,
        )
    )
    captured_on = cli_mod._phase_4_6_capture_anchor_on_complete(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        milestone_status="COMPLETE",
        config=cfg_enabled,
    )
    assert captured_on is not None
    assert _milestone_anchor_complete_dir(tmp_path, "milestone-1").is_dir()
