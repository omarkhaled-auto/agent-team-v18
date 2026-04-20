# Phase H3c Hypothesis (c) Design

## Goal

Give the filesystem a short, configurable settle window between a successful Codex return and the post-dispatch checkpoint snapshot.

## Insertion Point

The success branch is:

- [`provider_router.py:399`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:399>) `if getattr(codex_result, "success", False):`
- [`provider_router.py:400`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:400>) `post_checkpoint = checkpoint_create(...)`
- [`provider_router.py:401`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:401>) `diff = checkpoint_diff(...)`

There is currently no existing wait, flush, or debounce on that path.

## Proposed Implementation

Add two `v18` fields:

- `codex_flush_wait_enabled: bool = False`
- `codex_flush_wait_seconds: float = 0.5`

Then in the success path:

```python
if getattr(codex_result, "success", False):
    if _get_v18_value(config, "codex_flush_wait_enabled", False):
        await asyncio.sleep(max(0.0, float(_get_v18_value(config, "codex_flush_wait_seconds", 0.5))))
    post_checkpoint = checkpoint_create(...)
```

Notes:

- keep it scoped to success only
- no OS-specific fsync logic unless a simple, cross-platform primitive exists
- negative or malformed values should clamp to `0.0` after config coercion

## Tests

- flag on -> sleep is invoked with the configured value
- flag off -> sleep is not invoked
- `codex_flush_wait_seconds` round-trips from YAML as a float
- success path still reaches checkpoint diff and fallback logic unchanged

## Risk

This fix is intentionally blunt. It may prove unnecessary if the real issue is prompt behavior or cwd mismatch, which is why the flag defaults to off.
