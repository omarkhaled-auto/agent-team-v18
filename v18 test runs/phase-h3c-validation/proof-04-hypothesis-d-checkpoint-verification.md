# Proof 04 - Hypothesis (d) Checkpoint Verification

## Scope

Checkpoint verification for H3c spans:

- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/codex_captures.py`
- `src/agent_team_v15/provider_router.py`

Discovery found the tracker already uses a full tree walk plus per-file content hashing, not mtime-only diffing. H3c therefore adds checkpoint-diff observability and synthetic verification rather than forcing a speculative tracker rewrite.

## Verification

Command:

```text
pytest tests/test_phase_h3c_wave_b_fixes.py -q -k "checkpoint_diff_detects_create_modify_and_delete or checkpoint_diff_capture_written_when_capture_enabled or checkpoint_diff_capture_skipped_when_capture_disabled"
```

Result:

```text
3 passed, 6 deselected in 0.28s
```

## Evidence

- `test_checkpoint_diff_detects_create_modify_and_delete`
  - snapshots a workspace with nested files
  - modifies one file, deletes one file, and creates one file
  - proves `_diff_checkpoints()` returns:
    - `created == ["packages/shared/src/generated.ts"]`
    - `modified == ["apps/api/src/existing.ts"]`
    - `deleted == ["packages/shared/src/obsolete.ts"]`
  - also proves `.agent-team` noise is excluded from the manifest
- `test_checkpoint_diff_capture_written_when_capture_enabled`
  - enables `codex_capture_enabled`
  - proves `.agent-team/codex-captures/milestone-1-wave-B-checkpoint-diff.json` is emitted
  - proves the capture records the created file and file-count delta
- `test_checkpoint_diff_capture_skipped_when_capture_disabled`
  - proves the checkpoint-diff capture is not written when captures are disabled

## Verdict

Hypothesis (d) produced a verification-and-observability outcome, not a behavioral tracker rewrite.

- The underlying tracker already passed the synthetic create/modify/delete case.
- H3c adds checkpoint-diff capture output for smoke-time forensics when `codex_capture_enabled=True`.
- `v18.checkpoint_tracker_hardening_enabled` remains reserved for a future targeted fix if a concrete tracker defect is ever reproduced.
