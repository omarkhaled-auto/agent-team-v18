# Phase H3c Hypothesis (d) Design

## Goal

Verify whether the checkpoint tracker is actually missing real changes, and add direct capture evidence for future smokes.

## Repo Reality

The checkpoint tracker is already content-hash based:

- walker: [`wave_executor.py:322-355`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:322>)
- snapshot: [`wave_executor.py:358-375`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:358>)
- diff: [`wave_executor.py:378-391`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:378>)

That substantially lowers the probability of an mtime precision bug.

## Proposed Implementation

### 1. Add checkpoint-diff capture

Extend `codex_captures.py` with a helper that writes:

`<cwd>/.agent-team/codex-captures/<milestone>-wave-<wave>-checkpoint-diff.json`

Payload:

- `pre_checkpoint_files`
- `post_checkpoint_files`
- `diff_created`
- `diff_modified`
- `diff_deleted`
- `metadata.pre_file_count`
- `metadata.post_file_count`
- `metadata.pre_checkpoint_time_utc`
- `metadata.post_checkpoint_time_utc`

This capture is controlled by the existing `v18.codex_capture_enabled` flag, not by the new hardening flag.

### 2. Add a synthetic tracker proof

Add a test that:

- creates files
- modifies files
- deletes files
- snapshots before/after with `_create_checkpoint`
- asserts `_diff_checkpoints` returns the expected created/modified/deleted sets

### 3. Only harden tracker behavior if the synthetic proof fails

Current code inspection does not justify a behavior change to `_create_checkpoint` or `_diff_checkpoints`. H3c should therefore:

- declare `v18.checkpoint_tracker_hardening_enabled`
- add no behavioral hardening unless a failing synthetic test demonstrates a real bug

That keeps the implementation honest instead of inventing a speculative fix for a code path that already uses byte hashes.

## Risks

- The capture is high value even if the tracker is correct, because it tells the smoke observer whether the tree was actually unchanged or merely looked unchanged to the router.
- If a real tracker bug appears later, it will likely be an inclusion-scope problem (skipped/unreadable paths, out-of-cwd writes, symlink behavior), not hash staleness.
