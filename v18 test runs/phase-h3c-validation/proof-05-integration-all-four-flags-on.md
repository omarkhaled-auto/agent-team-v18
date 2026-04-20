# Proof 05 - Integration With All Four Flags On

## Scope

This proof exercises the H3c path as an integrated unit:

- prompt hardening
- cwd verification
- flush wait
- checkpoint-diff capture

## Verification

Command:

```text
pytest tests/test_phase_h3c_wave_b_fixes.py -q -k "all_four_flags_on_dispatches_cleanly"
```

Result:

```text
1 passed, 8 deselected in 0.26s
```

## Evidence

`test_all_four_flags_on_dispatches_cleanly` performs a full Wave B Codex dispatch against the real app-server transport module with a mocked JSON-RPC process.

It proves all of the following in one path:

- the app-server subprocess receives the resolved absolute cwd
- `thread/start` returns the same cwd, so the mismatch check stays quiet
- the mocked Codex turn produces a file on disk via the Codex path rather than Claude fallback
- the prompt capture is written and contains `<tool_persistence>`
- the checkpoint-diff capture is written and records `apps/api/src/generated.ts` as created
- the router sleeps for the configured `0.1` seconds before checkpointing
- the result returns `provider == "codex"` and `fallback_used is False`

## Verdict

All four H3c features compose without cascade failure when enabled together. This is the closest non-paid proof available before the separate validation smoke.
