# D-09 investigation — Contract Engine `validate_endpoint` MCP tool

**Source evidence:** `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/CONTRACT_E2E_RESULTS.md` lines 3–6: "Verification method: Static analysis — `validate_endpoint` Contract Engine MCP tool was not available in the deployed toolset." `BUILD_LOG.txt` carries no explicit `MCP pre-flight` entry — the degradation to static analysis was inferred silently by the LLM sub-agent, not flagged by deterministic pipeline code.

**Code survey:**

- `src/agent_team_v15/mcp_servers.py:241-260` defines `_contract_engine_mcp_server(config)`, and `get_contract_aware_servers(config)` registers it when `config.contract_engine.enabled` is True (line 307).
- `src/agent_team_v15/config.py:660-675` sets `ContractEngineConfig.enabled: bool = False` by default, with `mcp_command="python"` and `mcp_args=["-m", "src.contract_engine.mcp_server"]`.
- `src/agent_team_v15/contract_client.py:243-279` has `ContractEngineClient.validate_endpoint(...)` — the Python-side wrapper that calls the MCP tool over a live session.
- No `src/contract_engine/` package or `src/contract_engine/mcp_server.py` module exists in this repository. `find src/` returns only `agent_team_v15/`.

**Finding:** The Contract Engine MCP **server** is configured but its implementation module `src.contract_engine.mcp_server` is NOT shipped in this repo. When `config.contract_engine.enabled=False` (the default), the pipeline never attempts to register the server at all — build-j's run followed that path. When enabled, the registration succeeds but a live invocation would fail on launch because the target Python module is missing. The Python client (`ContractEngineClient.validate_endpoint`) exists as glue but has no deployable server to talk to.

**Decision — Branch B (labeling, not registration):** The MCP tool is not deployable in this repo. Do NOT add a fake registration. Instead: add a deterministic pre-flight helper in `mcp_servers.py` (`contract_engine_is_deployable`, `run_mcp_preflight`) that writes `.agent-team/MCP_PREFLIGHT.json` with a structured per-tool status, plus `ensure_contract_e2e_fidelity_header` which idempotently prepends a clearly-labeled "Verification fidelity: STATIC ANALYSIS (not runtime)" markdown block to CONTRACT_E2E_RESULTS.md when the engine is unavailable. Helpers are exported from `mcp_servers.py` with tests covering every branch. Wiring into `cli.py` is explicitly out of scope this session (constraints §4 bans cli.py edits for PR C); the helpers are callable and will be wired during Session 6's Gate A smoke integration or a follow-up closeout pass.

**Out-of-scope confirmation:** The MCP tool does NOT need a real implementation to close D-09 — only registration (n/a here) or labeling (done here). No stop-and-report event required.

**Scope inside authorized surface:** `mcp_servers.py` + new tests + this investigation note. Approx 90 LOC added to `mcp_servers.py`. No `cli.py` edits.
