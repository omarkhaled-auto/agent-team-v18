# Proof 08 — Framework Idioms Cache Emitted

Date: 2026-04-20

## Goal

Show that `.agent-team/framework_idioms_cache.json` is written even when Context7 is unavailable and the system falls back to a note string.

## Fix

`src/agent_team_v15/cli.py`

- added `_persist_framework_idioms_cache_entry(...)`
- persists cache entries on:
  - normal document fetch
  - no Context7 servers
  - empty document text
  - exception path

## Evidence

- `tests/test_n17_mcp_prefetch.py::TestPrefetchMCPFailure::test_no_context7_persists_fallback_note`
  proves:
  - the returned value includes `Framework idiom documentation unavailable`
  - `.agent-team/framework_idioms_cache.json` exists
  - the cache entry is written under the expected milestone/wave key
- `tests/test_n17_mcp_prefetch.py::TestPrefetchFlagOff::test_flag_off_returns_empty`
  proves the cache is still absent when the feature is disabled.
- Included in the targeted regression ring:
  - `pytest tests/test_n10_content_auditor.py tests/test_prd_mode_convergence.py tests/test_config_v18_loader_gaps.py tests/test_ownership_contract.py tests/test_h1a_ownership_enforcer.py tests/test_h1a_scaffold_verifier.py tests/test_n17_mcp_prefetch.py tests/test_h2bc_regressions.py -q`
  - Result: `146 passed in 1.07s`

## Result

H2bc closes the N-17 emission gap: the cache file is now written at the expected path, including fallback-note cases that previously produced no file at all.
