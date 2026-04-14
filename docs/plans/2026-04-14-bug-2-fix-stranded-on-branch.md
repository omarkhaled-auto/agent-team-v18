# Bug #2 Fix Stranded On Branch

**Date:** 2026-04-14
**Status:** documented and carried forward on PR #2 as a drive-by unblock
**Reference commit:** `b57cb43d5fe986580488b2a985b3811b9a299c97`
**Source branch:** `bug-9-tier-2-stack-contract-validator`
**Carry-forward branch:** `bug-12-followup-sdk-streaming-watchdog`

## Summary

Commit `b57cb43` fixed the `m-N` dependency shorthand regression in
`src/agent_team_v15/milestone_manager.py::_parse_deps`, but that commit never
landed on `master`.

The corresponding tests were already present on `master` and failed there
without the fix:

- `tests/test_milestone_manager.py::TestParseDeps::test_comma_separated_no_spaces`
- `tests/test_milestone_manager.py::TestParseDeps::test_extra_whitespace`
- `tests/test_milestone_manager.py::TestParseDeps::test_trailing_comma`
- `tests/test_milestone_manager.py::TestParseDeps::test_leading_comma`
- `tests/test_milestone_manager.py::TestParseDeps::test_empty_between_commas`

These assertions live at roughly `tests/test_milestone_manager.py:780-795`.

## What happened

1. PR #2 validation hit the full-suite requirement and failed on the five
   `TestParseDeps` cases above.
2. The same five failures were reproduced on `master`, confirming the breakage
   was inherited and not introduced by PR #2.
3. `b57cb43` was cherry-picked onto `bug-12-followup-sdk-streaming-watchdog`
   to unblock PR #2 validation.

## Action

When `bug-9-tier-2-stack-contract-validator` is next prepared for merge, the
reviewer must check whether `b57cb43` is already present on `master`. If this
carry-forward lands first, that PR should drop the duplicate fix instead of
merging it twice.
