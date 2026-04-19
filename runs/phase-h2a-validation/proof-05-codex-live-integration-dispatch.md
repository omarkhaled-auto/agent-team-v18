# Proof 05 - Codex Live Integration Dispatch

## Exact pytest invocation

```powershell
$env:PYTEST_ADDOPTS=''
pytest tests/ -v -m codex_live --tb=short 2>&1
```

## Full stdout/stderr

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\Omar Khaled\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: C:\Projects\agent-team-v18-codex
configfile: pyproject.toml
plugins: anyio-4.11.0, chroma-mcp-server-0.2.28, hypothesis-6.151.8, langsmith-0.4.31, asyncio-1.3.0, cov-7.0.0, schemathesis-4.10.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 11211 items / 11210 deselected / 1 skipped / 1 selected

tests/test_codex_appserver_live.py::test_app_server_thread_start_real_codex PASSED [100%]

=============== 1 passed, 1 skipped, 11210 deselected in 13.01s ===============
```

No stderr text was emitted beyond the combined capture above.

## Cost breakdown

The live pytest test asserts only the budget ceiling (`result.cost_usd < 0.05`). The matching real transport probe for the same production path and prompt (`Reply with exactly OK and nothing else.`) returned:

```json
{
  "status": "completed",
  "message": "OK",
  "input_tokens": 21557,
  "cached_input_tokens": 2432,
  "output_tokens": 5,
  "reasoning_tokens": 0,
  "cost_usd": 0.039506
}
```

Cost math:

- Uncached input: `(21557 - 2432) = 19125` tokens x `$2.00 / 1M` = `$0.038250`
- Cached input: `2432` tokens x `$0.50 / 1M` = `$0.001216`
- Output: `5` tokens x `$8.00 / 1M` = `$0.000040`
- Reasoning output: `0` tokens = `$0.000000`
- Total: `$0.039506`

## What the transport did

1. Spawned `codex app-server --listen stdio://` as a subprocess.
2. Sent `initialize` over stdio JSON-RPC.
3. Sent `thread/start`.
4. Sent `turn/start` with the minimal prompt.
5. Consumed real notifications from stdout, including `thread/started`, `turn/started`, `item/started`, `item/agentMessage/delta`, `item/completed`, `thread/tokenUsage/updated`, and `turn/completed`.
6. Verified the final assistant text was exactly `OK`.
7. Sent `thread/archive`.
8. Observed cleanup via `thread/archived` or `thread/status/changed` to `notLoaded`.
9. Closed stdin/stdout/stderr handles and cleaned up the subprocess.

## Evidence this hit real Codex

- The machine binary is real CLI, not a test double:

```text
codex --version
codex-cli 0.121.0

(Get-Command codex).Source
C:\Users\Omar Khaled\AppData\Roaming\npm\codex.ps1
```

- The live test imports production code from `agent_team_v15.codex_appserver` and instantiates `_CodexAppServerClient` directly.
- The live test uses no monkeypatching, fake SDK module, or fake subprocess.
- Real token usage and real cost were observed from the app-server notification stream.
- Real cleanup notifications were observed after `thread/archive`, which a fake unit-test transport would not prove.
