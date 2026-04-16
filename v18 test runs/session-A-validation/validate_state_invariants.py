"""Phase A production-caller proof for NEW-7: save_state invariant enforcement.

Reproduces build-l's root-cause state (summary.success=True + failed_milestones
populated + interrupted=False) through the real save_state entry point. Asserts:

1. Clean state (empty failed_milestones) saves with success=True.
2. State with failed_milestones populated and NO explicit summary saves with
   success=False (the fix to state.py:570 auto-computes correctly).
3. State with failed_milestones populated and an explicit LIE
   (summary={"success": True}) RAISES StateInvariantError.
4. StateInvariantError is a subclass of RuntimeError (so cli.py's outer
   `except Exception` catches it cleanly).

Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from agent_team_v15.state import (  # noqa: E402
    RunState,
    StateInvariantError,
    save_state,
)


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label}: {detail}")
    sys.exit(1)


def _pass(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    if not issubclass(StateInvariantError, RuntimeError):
        _fail("exception_class_hierarchy",
              "StateInvariantError must subclass RuntimeError (so cli outer "
              "`except Exception` catches it without bypass)")
    _pass("exception_class_hierarchy",
          "StateInvariantError <: RuntimeError <: Exception")

    with tempfile.TemporaryDirectory(prefix="new7_clean_") as tmp:
        state = RunState(task="validate-new7", interrupted=False)
        save_state(state, directory=tmp)
        data = json.loads((Path(tmp) / "STATE.json").read_text(encoding="utf-8"))
        if data["summary"]["success"] is not True:
            _fail("clean_state_saves_success_true",
                  f"expected summary.success=True, got {data['summary']}")
        _pass("clean_state_saves_success_true", "baseline happy path unaffected")

    with tempfile.TemporaryDirectory(prefix="new7_failed_clean_") as tmp:
        state = RunState(
            task="validate-new7",
            interrupted=False,
            failed_milestones=["milestone-1"],
        )
        save_state(state, directory=tmp)
        data = json.loads((Path(tmp) / "STATE.json").read_text(encoding="utf-8"))
        if data["summary"]["success"] is not False:
            _fail("failed_milestone_clean_summary_writes_success_false",
                  f"expected summary.success=False, got {data['summary']}")
        if data["failed_milestones"] != ["milestone-1"]:
            _fail("failed_milestone_clean_summary_writes_success_false",
                  f"expected failed_milestones=['milestone-1'], got {data['failed_milestones']}")
        _pass("failed_milestone_clean_summary_writes_success_false",
              "save_state auto-computes truth when summary unset (state.py:570 fix)")

    with tempfile.TemporaryDirectory(prefix="new7_poisoned_") as tmp:
        state = RunState(
            task="validate-new7",
            interrupted=False,
            failed_milestones=["milestone-1"],
            summary={"success": True},
        )
        raised = False
        try:
            save_state(state, directory=tmp)
        except StateInvariantError as exc:
            raised = True
            msg = str(exc)
            if "milestone-1" not in msg:
                _fail("poisoned_summary_raises",
                      f"exception message missing failed_milestones context: {msg!r}")
            if "summary.success" not in msg:
                _fail("poisoned_summary_raises",
                      f"exception message missing summary.success context: {msg!r}")
            if "cli.py:13491" not in msg:
                _fail("poisoned_summary_raises",
                      f"exception message missing remediation pointer: {msg!r}")
        if not raised:
            _fail("poisoned_summary_raises",
                  "expected StateInvariantError on poisoned summary; save_state returned normally")
        state_file = Path(tmp) / "STATE.json"
        if state_file.exists():
            _fail("poisoned_summary_raises",
                  "invariant raised but tempfile still wrote STATE.json — atomicity broken")
        _pass("poisoned_summary_raises",
              "invariant fires on explicit lie; no STATE.json written (build-l root cause caught)")

    with tempfile.TemporaryDirectory(prefix="new7_wrapped_") as tmp:
        state = RunState(
            task="validate-new7",
            failed_milestones=["milestone-1"],
            summary={"success": True},
        )
        caught_as_exception = False
        try:
            save_state(state, directory=tmp)
        except Exception:
            caught_as_exception = True
        if not caught_as_exception:
            _fail("cli_outer_except_wraps",
                  "generic `except Exception` should catch StateInvariantError")
        _pass("cli_outer_except_wraps",
              "StateInvariantError caught by generic Exception handler (cli.py:13497 safety net)")

    print()
    print("[OVERALL] NEW-7 invariant proof against build-l root-cause state PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
