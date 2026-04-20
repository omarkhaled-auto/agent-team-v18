# Proof 03 - Hypothesis (c) Flush Wait

## Scope

The post-Codex flush wait lives in:

- `src/agent_team_v15/provider_router.py`

The implementation inserts a flag-gated `asyncio.sleep()` between successful Codex completion and the post-wave checkpoint, with the wait duration loaded from `v18.codex_flush_wait_seconds`.

## Verification

Command:

```text
pytest tests/test_phase_h3c_wave_b_fixes.py -q -k "flush_wait_uses_configured_seconds or flush_wait_skipped_when_flag_disabled or all_four_flags_on_dispatches_cleanly"
```

Result:

```text
3 passed, 6 deselected in 0.26s
```

## Evidence

- `test_flush_wait_uses_configured_seconds`
  - patches `asyncio.sleep`
  - enables the flag with `codex_flush_wait_seconds=0.25`
  - proves the router sleeps for exactly `0.25`
- `test_flush_wait_skipped_when_flag_disabled`
  - patches the same sleep function
  - disables the flag
  - proves no sleep call occurs
- `test_all_four_flags_on_dispatches_cleanly`
  - enables all H3c flags
  - proves the integrated path sleeps for `0.1` before checkpointing
  - proves the wait composes correctly with prompt hardening, cwd verification, and checkpoint-diff capture

## Verdict

Hypothesis (c) is implemented and independently gated by `v18.codex_flush_wait_enabled`, with duration controlled by `v18.codex_flush_wait_seconds`.

Flag ON:

- the router performs the configured wait after Codex success

Flag OFF:

- no wait occurs
