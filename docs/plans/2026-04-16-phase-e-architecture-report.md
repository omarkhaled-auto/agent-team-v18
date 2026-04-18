# Phase E — Architecture Report

Produced: 2026-04-17
Author: phase-e-architecture-discoverer (Wave 1)
Ground truth: `2026-04-16-phase-e-sdk-verification.md` (9/9 queries, ALL MATCH)
Codebase state: commit `5e215a5` (Phase D: Tracker Cleanup)

---

## 1. SDK Verification Cross-Reference

Every codebase usage was compared against the Wave 0 verified SDK shapes. Results:

| Verified Shape | Codebase Usage | Compatible? | Notes |
|---|---|---|---|
| `ClaudeSDKClient(options=)` context manager | cli.py:3712, 4351, interviewer.py:682, design_reference.py:208, prd_agent.py:1033, runtime_verification.py:780 | YES | All use `async with ClaudeSDKClient(options=options) as client:` |
| `client.query(prompt)` | cli.py:3715, 4354, 1011; interviewer.py:693; design_reference.py:209; prd_agent.py:1034 | YES | Standard bidirectional pattern |
| `client.receive_response()` async iterator | design_reference.py:210; cli.py via `_process_response()` | YES | Yields AssistantMessage, ResultMessage |
| `async for msg in query(prompt=, options=)` one-shot | audit_agent.py:81, 294 | YES (but deprecated pattern) | Step 1 migration target |
| `ClaudeAgentOptions(mcp_servers=, allowed_tools=, permission_mode=)` | cli.py:449; design_reference.py:205 | YES | Matches Query 4 shape exactly |
| `AssistantMessage.content: list[TextBlock\|ToolUseBlock\|ToolResultBlock]` | cli.py import line 31-36; design_reference.py:211-214 | YES | Matches Query 5 shape |
| `client.interrupt()` | NOT USED ANYWHERE | N/A | Step 3 will add this |
| `fork_session=True` | NOT USED ANYWHERE | N/A | Step 2 may optionally use this |
| `Task("sub-agent-name", ...)` prompt instruction | agents.py:1818-1821, 1832, 1838, 1872-1875, 1882, 1889, 1895 | YES (SDK sub-agent dispatch) | Step 2 elimination target |

**Zero conflicts between verified SDK shapes and current codebase usage.** All existing ClaudeSDKClient call sites are compatible with the verified API. The two migration targets are (a) the `query()` one-shot pattern in audit_agent.py, and (b) the Task() prompt instructions in agents.py enterprise mode.

---

## 2. Per-Agent Migration Table

Updated from Appendix D section D.4 with CURRENT line numbers (post-Phase-D code).

| # | File:Line (CURRENT) | Current Pattern | Target Pattern | Phase E Step |
|---|---|---|---|---|
| 1 | `cli.py:1001-1029` (_run_sdk_session_with_watchdog) | ClaudeSDKClient bidirectional | Keep — add `client.interrupt()` in wedge path | Step 3+4 |
| 2 | `cli.py:3712` (_execute_single_wave_sdk, worktree path) | `async with ClaudeSDKClient(options=wave_options) as client:` | Keep — pass client ref to watchdog for interrupt | Step 3+4 |
| 3 | `cli.py:4351` (_execute_single_wave_sdk, mainline path) | `async with ClaudeSDKClient(options=wave_options) as client:` | Keep — pass client ref to watchdog for interrupt | Step 3+4 |
| 4 | `cli.py:338-449` (_build_options) | Builds ClaudeAgentOptions | Keep — unchanged | Already correct |
| 5 | `cli.py:452-464` (_clone_agent_options) | Shallow clone of options | Keep — unchanged | Already correct |
| 6 | `cli.py:467-488` (_prepare_wave_sdk_options) | Per-wave MCP override (Playwright for Wave E) | Keep — unchanged | Already correct |
| 7 | `interviewer.py:682` | `async with ClaudeSDKClient(options=options) as client:` | Keep — already correct bidirectional pattern | Already correct |
| 8 | `design_reference.py:208` | `async with ClaudeSDKClient(options=options) as client:` | Keep — already correct pattern | Already correct |
| 9 | `prd_agent.py:1033` | `async with ClaudeSDKClient(options=options) as client:` | Keep — verify interrupt integration | Already correct (interrupt optional) |
| 10 | `runtime_verification.py:780` | `async with ClaudeSDKClient(options=options) as client:` | Keep — verify interrupt integration | Already correct (interrupt optional) |
| 11 | **`audit_agent.py:81`** | **`async for msg in query(prompt=prompt, options=options):`** — one-shot | **`async with ClaudeSDKClient(options=options) as client: await client.query(prompt); async for msg in client.receive_response():`** + interrupt on timeout | **Step 1** |
| 12 | **`audit_agent.py:294`** | **`async for msg in query(prompt=prompt, options=options):`** — one-shot | **Same as #11** | **Step 1** |
| 13 | **`agents.py:1818-1821`** | **Prompt text: `Task("architecture-lead", "ENTERPRISE STEP N: ...")`** x4 | **Remove Task() instructions; Python-orchestrated per-role ClaudeSDKClient sessions with MCP** | **Step 2** |
| 14 | **`agents.py:1832`** | **Prompt text: `Task("coding-lead", "ENTERPRISE WAVE {N}: ...")`** | **Remove; already handled by _execute_single_wave_sdk** | **Step 2** |
| 15 | **`agents.py:1838`** | **Prompt text: `Task("review-lead", "ENTERPRISE REVIEW: ...")`** | **Python-orchestrated review-lead session with MCP** | **Step 2** |
| 16 | **`agents.py:1872-1875`** | **Prompt text: `Task("architecture-lead", ...)` x4 (department model)** | **Same as #13** | **Step 2** |
| 17 | **`agents.py:1882`** | **Prompt text: `Task("coding-dept-head", "ENTERPRISE WAVE {N}: ...")`** | **Python-orchestrated coding-dept-head session** | **Step 2** |
| 18 | **`agents.py:1889`** | **Prompt text: `Task("review-dept-head", "ENTERPRISE REVIEW: ...")`** | **Python-orchestrated review-dept-head session** | **Step 2** |
| 19 | **`agents.py:1895`** | **Prompt text: `Task("coding-dept-head", "FIX_REQUIRED. Items: ...")`** | **Python-orchestrated fix session** | **Step 2** |

### Line Number Shifts from Appendix D

| Appendix D Reference | Current Line | Shift | Cause |
|---|---|---|---|
| `cli.py:449` (_build_options return) | cli.py:449 | 0 | No change |
| `cli.py:458-460` (_clone_agent_options) | cli.py:452-464 | -6 (start), +4 (end expanded) | Phase B/C refactors |
| `cli.py:467-488` (_prepare_wave_sdk_options) | cli.py:467-488 | 0 | No change |
| `cli.py:3350-3379` (pseudocode gate area) | cli.py:3348-3370 | -2 | Phase D additions above |
| `cli.py:3359` (wave session ref in Appendix D) | cli.py:3712 | +353 | Major: Appendix D used the wrong line; actual _execute_single_wave_sdk is at 3703 (worktree) and 4340 (mainline) |
| `cli.py:3969-3986` (parallel execution area) | cli.py:3960-3990 | -9 to +4 | Phase D shuffles |
| `audit_agent.py:81` | audit_agent.py:81 | 0 | No change |
| `audit_agent.py:294` | audit_agent.py:294 | 0 | No change |
| `agents.py:1818-1821` | agents.py:1818-1821 | 0 | No change |
| `agents.py:5287-5290` (MCP comment) | agents.py:5287-5290 | 0 | No change |
| `interviewer.py:682` | interviewer.py:682 | 0 | No change |
| `design_reference.py:208` | design_reference.py:208 | 0 | No change |
| `wave_executor.py:170` (_WaveWatchdogState) | wave_executor.py:170 | 0 | No change |

**SIGNIFICANT SHIFT:** Appendix D listed `cli.py:3359, 3980` as wave session call sites. These are actually in the pseudocode-gate and parallel-execution areas respectively. The actual `_execute_single_wave_sdk` functions are defined at **cli.py:3703** (worktree path) and **cli.py:4340** (mainline path). Implementation agents must use the corrected line numbers.

---

## 3. Enterprise Mode Dispatch Analysis (Step 2 Scope)

### 3.1 Current Architecture

Enterprise mode is activated by prompt text at `agents.py:1814`: `When [ENTERPRISE MODE] is indicated in your task prompt:`. The orchestrator (Claude session) reads these instructions and issues Task() calls to invoke sub-agents. Two variants exist:

**Standard enterprise** (agents.py:1816-1858):
- 4x architecture-lead Task() calls (sequential steps 1-4)
- Per-wave coding-lead Task() calls
- 1x review-lead Task() call

**Department model** (agents.py:1864-1905):
- Same 4x architecture-lead steps
- coding-dept-head replaces coding-lead (coordinates domain managers)
- review-dept-head replaces review-lead (coordinates review managers)
- Cross-department fix flow: coding-dept-head gets FIX_REQUIRED tasks

### 3.2 Sub-Agent Enumeration

| Sub-Agent Name | Invoked At | Purpose | Current Tools | Needs MCP? |
|---|---|---|---|---|
| architecture-lead | agents.py:1818-1821, 1872-1875 | Design architecture, ownership map, contracts, scaffolding | Read, Glob, Grep, Write, Edit (from ARCHITECT_PROMPT at agents.py:5300-5305) | YES — context7 for framework architecture patterns |
| coding-lead | agents.py:1832 | Execute per-wave domain implementation | Read, Write, Edit, Bash, Glob, Grep (from code-writer tools at agents.py:5316+) | YES — context7 for current framework idioms (N-17 root cause) |
| review-lead | agents.py:1838 | Deploy parallel domain reviewers | Read, Glob, Grep, Edit (from code-reviewer tools) | YES — context7 for verification against current docs |
| coding-dept-head | agents.py:1882, 1895 | Coordinate domain managers for wave implementation | Same as coding-lead + department coordination | YES |
| review-dept-head | agents.py:1889 | Coordinate review managers across domains | Same as review-lead + department coordination | YES |

### 3.3 Replacement Design

Each Task() dispatch becomes a Python-orchestrated `ClaudeSDKClient` session:

```python
# New function in cli.py (near _execute_single_wave_sdk, around line 3700)
async def _execute_enterprise_role_session(
    role_name: str,
    prompt: str,
    base_options: ClaudeAgentOptions,
    config: AgentTeamConfig,
    phase_costs: dict[str, float],
    *,
    progress_callback: Callable[..., Any] | None = None,
) -> float:
    """Execute one enterprise-mode sub-agent role in its own SDK session with full MCP."""
    role_options = _clone_agent_options(base_options)
    # Sub-agent gets full MCP access (context7, etc.) via inherited mcp_servers
    # + its role-specific system_prompt from agent definitions
    async with ClaudeSDKClient(options=role_options) as client:
        await client.query(prompt)
        cost = await _process_response(
            client, config, phase_costs,
            progress_callback=progress_callback,
        )
    return cost
```

The orchestrator prompt text in agents.py (lines 1814-1905) gets rewritten to:
- Remove all `Task("...", "...")` instructions
- Instead, emit structured markers (e.g., `[ENTERPRISE_STEP: architecture-lead, step=1]`) that the Python orchestrator code in cli.py detects and routes to `_execute_enterprise_role_session()`
- OR: keep the enterprise-mode flow purely in Python (the orchestrator session's enterprise-mode handler in cli.py reads OWNERSHIP_MAP.json, calls architecture-lead 4x, coding-lead per-wave, review-lead once — all as separate ClaudeSDKClient sessions)

**Recommended location:** `cli.py` near the existing `_execute_single_wave_sdk` definitions. The enterprise-mode orchestration in agents.py stays as documentation of the FLOW but the actual dispatch is Python code, not prompt instructions.

---

## 4. Codex App-Server Migration Design (Bug #20)

### 4.1 Current codex_transport.py Architecture (761 LOC)

Key functions:
- `CodexConfig` (line 38-60): model, timeout, pricing table
- `CodexResult` (line 63-82): success, tokens, cost, files, error
- `is_codex_available()` (line 89-91): checks `codex` on PATH
- `create_codex_home()` (line 124-182): temp CODEX_HOME with config.toml + auth copy
- `_parse_jsonl()` (line 203-217): parse newline-delimited JSON from stdout
- `_extract_token_usage()` (line 220-229): sum tokens across JSONL events
- `_compute_cost()` (line 232-254): USD cost from tokens + pricing
- `_extract_final_message()` (line 257-287): last agent_message from events
- `_progress_from_event()` (line 335-364): extract message_type/tool_name/tool_id/event_kind
- `_drain_stream()` (line 367-402): read subprocess stdout line-by-line, forward progress
- `_communicate_with_progress()` (line 405-441): pipe prompt, stream stdout+stderr
- `_kill_process_tree_windows()` (line 444-469): taskkill /F /T for Windows
- `_terminate_subprocess()` (line 472-496): best-effort termination
- `_execute_once()` (line 549-684): single `codex exec` invocation
- `execute_codex()` (line 687-760): retry wrapper, auto CODEX_HOME lifecycle

**Core subprocess pattern:** spawns `codex exec --json --full-auto --skip-git-repo-check --cd {cwd} -m {model} -c model_reasoning_effort={effort} -` with stdin prompt, streams JSONL from stdout, parses events for token usage and completion status.

### 4.2 New codex_appserver.py Architecture

**Recommended approach:** Use `codex_app_server.AppServerClient` (low-level API) from the verified Python bindings (SDK verification Query 9). This provides:
- JSON-RPC framing and request/response correlation handled by SDK
- `initialize()`, `thread_start()`, `turn_start()`, `wait_for_turn_completed()` methods
- Streaming via `stream_text()` or event iteration
- No need to implement 300 LOC of RPC plumbing ourselves

**Rationale for Option A (SDK) over Option B (direct RPC):**
- SDK verification confirmed `codex_app_server` package EXISTS with stable API
- `AsyncCodex` class provides async integration (additive finding from verification)
- AppServerClient gives low-level control needed for orphan detection
- Saves ~150 LOC of JSON-RPC framing code
- Pin codex + SDK version together in pyproject.toml for stability

**Public API (same surface as codex_transport.py):**
- `CodexConfig` — reuse from codex_transport
- `CodexResult` — reuse from codex_transport
- `async def execute_codex(prompt, config, cwd, codex_home, *, progress_callback) -> CodexResult`
- `def is_codex_available() -> bool`

### 4.3 RPC Sequence Diagram

```
Client (codex_appserver.py)              App-Server (codex binary)
    │                                          │
    │─── initialize ──────────────────────────>│
    │<── {userAgent, codexHome, ...} ──────────│
    │                                          │
    │─── thread/start ────────────────────────>│
    │    {model, cwd, sandbox, config}         │
    │<── {thread: {id, createdAt}} ────────────│
    │                                          │
    │─── turn/start ──────────────────────────>│
    │    {threadId, input: [{type:"text",...}]} │
    │<── {turn: {id, status:"inProgress"}} ────│
    │                                          │
    │<── turn/started notification ────────────│
    │<── item/started notification (tool) ─────│  ← orphan tracker: record
    │<── item/agentMessage/delta ──────────────│  ← liveness signal
    │<── item/completed notification (tool) ───│  ← orphan tracker: pop
    │<── turn/diff/updated ────────────────────│  ← file changes
    │<── thread/tokenUsage/updated ────────────│  ← cost accounting
    │<── turn/completed {status:"completed"} ──│  ← done
    │                                          │
    │  ON ORPHAN DETECTION:                    │
    │─── turn/interrupt ──────────────────────>│
    │    {threadId, turnId}                     │
    │<── turn/completed {status:"interrupted"} │
    │                                          │
    │─── turn/start (corrective prompt) ──────>│  ← session preserved
    │    {threadId, input: [{type:"text",...}]} │
    │<── ... streaming continues ... ──────────│
```

### 4.4 Feature Flag

Add to `V18Config` in `config.py` at approximately line 808 (after `codex_reasoning_effort`):

```python
codex_transport_mode: str = "exec"  # "exec" (current) or "app-server" (Bug #20)
```

### 4.5 Transport Factory Wiring

In `cli.py` where `codex_transport_module` is resolved (currently a direct import of `codex_transport`), add:

```python
transport_mode = getattr(getattr(config, "v18", None), "codex_transport_mode", "exec")
if transport_mode == "app-server":
    from . import codex_appserver as codex_transport_module
else:
    from . import codex_transport as codex_transport_module
```

`provider_router.py` already uses `codex_transport_module` as a parameter (line 158) — no changes needed there beyond adding `CodexOrphanToolError` handling in `_execute_codex_wave()`.

### 4.6 Bug #20 Plan Reconciliation

Bug #20 plan section 3c recommended Option B (direct JSON-RPC). SDK verification found that `codex_app_server` package EXISTS with low-level `AppServerClient` that provides the exact control needed. **Revised recommendation: Option A (AppServerClient low-level API)** because:
1. Saves ~150 LOC of JSON-RPC plumbing
2. SDK handles request/response correlation and notification dispatch
3. Pin SDK version for stability (same mitigation as Option B's "stable wire protocol" argument)
4. If SDK breaks: fallback to Option B is a known escape path since wire protocol is stable

---

## 5. Wedge Recovery Flow Design (Steps 3+4)

### 5.1 Claude Path

```
Wave session (ClaudeSDKClient at cli.py:3712 or 4351)
    │
    ├── client.query(wave_prompt)
    ├── async for msg in client.receive_response():
    │       │
    │       ├── AssistantMessage with ToolUseBlock
    │       │       → record in pending_tool_starts[block.id] = {name, time}
    │       │
    │       ├── ToolResultBlock (matching tool_use_id)
    │       │       → pop from pending_tool_starts[block.tool_use_id]
    │       │
    │       └── (watchdog poll every 30s checks pending_tool_starts ages)
    │               │
    │               ├── age > orphan_tool_idle_timeout_seconds (600s)?
    │               │       → await client.interrupt()  ← session survives
    │               │       → await client.query("Tool {name} stalled. Skip and continue.")
    │               │       → resume client.receive_response()
    │               │
    │               └── second orphan in same wave?
    │                       → raise WaveWatchdogTimeoutError(timeout_kind="orphan-tool")
```

### 5.2 Codex Path

```
Turn session (codex_appserver.py)
    │
    ├── turn/start with wave prompt
    ├── stream notifications:
    │       │
    │       ├── item/started (tool)
    │       │       → record in pending_tool_starts[item.id]
    │       │
    │       ├── item/completed (tool)
    │       │       → pop from pending_tool_starts[item.id]
    │       │
    │       └── (watchdog timer checks pending ages)
    │               │
    │               ├── age > codex_orphan_tool_timeout_seconds (300s)?
    │               │       → send turn/interrupt RPC
    │               │       → wait ≤15s for turn/completed status=interrupted
    │               │       → send new turn/start with corrective prompt
    │               │
    │               └── second orphan?
    │                       → raise CodexOrphanToolError
    │                       → provider_router catches → _claude_fallback
```

### 5.3 Orphan Tool Schema

Using VERIFIED field names from SDK verification Query 5:

```python
# Claude path: ToolUseBlock.id → pending key, ToolResultBlock.tool_use_id → pop key
# Codex path: item.id → pending key (from item/started), item.id → pop key (from item/completed)

@dataclass
class OrphanToolEvent:
    tool_use_id: str      # ToolUseBlock.id (Claude) or item.id (Codex)
    tool_name: str        # ToolUseBlock.name (Claude) or item.name (Codex)
    started_at: str       # ISO timestamp
    age_seconds: float    # monotonic age at detection time
    provider: str         # "claude" | "codex"
```

### 5.4 Interrupt Hook Location

**wave_executor.py** `_WaveWatchdogState` class (line 170-221):
- Already has `pending_tool_starts: dict[str, dict[str, Any]]` (line 183)
- Already has `record_progress()` method that tracks start/complete events (lines 213-221)
- **New field:** `client: Any = None` — reference to ClaudeSDKClient for interrupt
- **New method:** `async def interrupt_oldest_orphan(self, threshold_seconds: float) -> OrphanToolEvent | None` — checks pending tools, calls `client.interrupt()` if threshold exceeded

**cli.py** `_execute_single_wave_sdk` (lines 3703-3732, 4340-4371):
- After creating `ClaudeSDKClient`, pass the client reference to the watchdog state
- The watchdog poll loop (in wave_executor.py) gains the ability to call `client.interrupt()` instead of just raising `WaveWatchdogTimeoutError`

### 5.5 orphan_detector.py in Execution Flow

New module: `src/agent_team_v15/orphan_detector.py`

```python
def detect_orphans(
    pending_starts: dict[str, dict[str, Any]],
    threshold_seconds: float,
    current_monotonic: float,
) -> list[OrphanToolEvent]:
    """Check all pending tool starts for orphans past threshold."""
    ...
```

Called by:
- **Claude path:** wave_executor.py watchdog poll → `detect_orphans()` → if any, call `client.interrupt()` + corrective query
- **Codex path:** codex_appserver.py streaming loop timer → `detect_orphans()` → if any, send `turn/interrupt` + corrective `turn/start`

---

## 6. File Edit Coordination Map

### Per-Agent File Ownership

| Implementation Agent | Files OWNED (exclusive write) | Files READ (no write) |
|---|---|---|
| **Step 1** (audit_agent.py migration) | `audit_agent.py` | SDK verification report |
| **Bug #20** (codex app-server) | NEW `codex_appserver.py`, `config.py` (add flag), `provider_router.py` (transport factory + CodexOrphanToolError handling) | `codex_transport.py` (reference, no modify) |
| **Step 2** (enterprise-mode) | `agents.py` (enterprise section lines 1814-1905 only) | `cli.py` (read existing patterns) |
| **Step 3+4** (interrupt + orphan) | `wave_executor.py` (watchdog class), NEW `orphan_detector.py`, `cli.py` (_execute_single_wave_sdk — add client ref pass-through) | SDK verification report |

### Overlap Analysis

| File | Touched By | Conflict? | Resolution |
|---|---|---|---|
| `audit_agent.py` | Step 1 only | NO | — |
| `agents.py` | Step 2 only (enterprise section) | NO | — |
| `codex_appserver.py` | Bug #20 only (new file) | NO | — |
| `orphan_detector.py` | Step 3+4 only (new file) | NO | — |
| `config.py` | Bug #20 only (add flag) | NO | — |
| `provider_router.py` | Bug #20 only | NO | — |
| `wave_executor.py` | Step 3+4 only | NO | — |
| **`cli.py`** | **Step 2 (new function) + Step 3+4 (modify _execute_single_wave_sdk)** | **MILD** | Different functions in different line ranges. Step 2 adds `_execute_enterprise_role_session()` (new function ~line 3700). Step 3+4 modifies existing `_execute_single_wave_sdk` (lines 3712, 4351). **Run Step 2 before Step 3+4; no merge conflict.** |
| `codex_transport.py` | NONE (kept as-is under feature flag) | NO | — |

**Verdict:** One mild overlap on cli.py between Step 2 and Step 3+4, resolved by sequencing (Step 2 first). All other files have exclusive ownership.

---

## 7. Risk Map

### Step 1 — audit_agent.py query() -> ClaudeSDKClient

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Audit report JSON shape changes | LOW | HIGH (breaks downstream) | Unit test: round-trip AUDIT_REPORT.json before/after |
| asyncio event loop handling (lines 89-97, 301-310) | MEDIUM | MEDIUM | The existing ThreadPoolExecutor pattern for nested event loops is tricky; ClaudeSDKClient may simplify this |
| Timeout behavior changes | LOW | MEDIUM | audit_agent.py currently has 120s/600s timeouts in pool.submit(); new client.interrupt() adds explicit control |

### Step 2 — Enterprise-mode Task() elimination

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Enterprise-mode flow regression | MEDIUM | HIGH (enterprise builds break) | Integration test: enterprise-mode M1+M2 run validates all 4 architecture steps + wave dispatch |
| Prompt text changes cause orchestrator behavior change | MEDIUM | MEDIUM | Keep enterprise-mode flow documentation in agents.py; only remove Task() instructions |
| Session cost increase (separate sessions per role vs sub-agents) | LOW | LOW | Each role was already a separate context; sub-agent sessions had similar token cost |

### Step 3+4 — client.interrupt() + orphan detection

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| interrupt() on non-streaming session | LOW | MEDIUM | SDK verification confirms interrupt is "primarily effective in streaming mode" — verify wave sessions ARE streaming (they are: client.receive_response() is async iterator) |
| Orphan detection false positive (legitimate slow tool) | MEDIUM | LOW | Threshold is 600s (10 min) for Claude, 300s for Codex — generous for any normal tool call |
| Watchdog race with response processing | MEDIUM | MEDIUM | Watchdog runs on separate poll interval; interrupt + re-query must be atomic relative to response processing |

### Bug #20 — Codex app-server migration

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| codex_app_server SDK breakage on codex version update | MEDIUM | HIGH | Pin codex + SDK version; feature flag defaults to "exec" so rollback is config-only |
| Windows subprocess handling differences | MEDIUM | MEDIUM | Existing _kill_process_tree_windows pattern carries over; AppServerClient may handle this differently |
| Corrective prompt doesn't bypass wedged tool | LOW | LOW | Second orphan triggers Claude fallback — bounded retry budget |
| AppServerConfig field mismatch with our CodexConfig | LOW | LOW | Map fields explicitly: codex_bin, config_overrides, cwd, env |

### Cross-Cutting Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| cli.py merge conflict between Step 2 and Step 3+4 | LOW | LOW | Sequence: Step 2 before Step 3+4; different functions |
| Test suite regression from import changes | LOW | MEDIUM | Run full test suite (10,419+ baseline) after each step |
| SDK version incompatibility | LOW | HIGH | SDK verification confirms ALL shapes match as of 2026-04-17 |

---

## 8. Self-Audit

Performed via sequential-thinking (5 steps). Findings:

### 8.1 File Overlap

One mild overlap identified: cli.py touched by both Step 2 (new function) and Step 3+4 (modify existing function). Different line ranges, no structural conflict. **Resolution:** sequence Step 2 before Step 3+4.

### 8.2 SDK Shape Consistency

All five implementation paths checked against verified shapes:
- Step 1: ClaudeSDKClient + query() + receive_response() — Query 1 verified YES
- Step 2: fresh ClaudeSDKClient per role with mcp_servers — Query 4 verified YES
- Step 3: client.interrupt() — Query 2 verified YES
- Step 4: ToolUseBlock.id / ToolResultBlock.tool_use_id pairing — Query 5 verified YES
- Bug #20: thread/start, turn/start, turn/interrupt, item events — Queries 7-8 verified YES

**Zero contradictions.**

### 8.3 Config Flag Placement

`codex_transport_mode` does not exist in V18Config currently (grep confirmed). Will be added at line ~808. No conflict with existing fields.

### 8.4 Provider Router Bug Confirmation

provider_router.py:316-320 catches `WaveWatchdogTimeoutError` and **re-raises** (does NOT fall back to Claude). This is the known bug documented in Bug #20 plan section 4d. Bug #20's implementation must change this to catch + `_claude_fallback`. Step 3+4 does NOT modify provider_router.py — this is exclusively Bug #20's responsibility.

### 8.5 Appendix D Line Number Corrections

Major correction: Appendix D listed `cli.py:3359, 3980` as wave session sites. These are actually the pseudocode-gate area and parallel-execution area respectively. The actual `_execute_single_wave_sdk` functions are at **cli.py:3703** (worktree) and **cli.py:4340** (mainline). All implementation agents must use corrected line numbers from this report.

---

## Summary

| Metric | Value |
|---|---|
| Files fully read | 10 (audit_agent.py, agents.py, cli.py, wave_executor.py, codex_transport.py, config.py, provider_router.py, interviewer.py, design_reference.py, prd_agent.py, runtime_verification.py) |
| SDK shape conflicts | 0 |
| Line number shifts from Appendix D | 1 major (cli.py wave session: +353 lines), 3 minor |
| Surprises | (1) cli.py:3359/3980 were wrong in Appendix D — actual sites are 3703/4340; (2) provider_router.py:316-320 re-raises WaveWatchdogTimeoutError without fallback (known Bug #20 target) |
| File overlaps | 1 mild (cli.py: Step 2 + Step 3+4, different functions, sequencing resolves) |
| Internal contradictions | 0 |
| Recommendation | **Proceed** — all verified shapes match, all file ownership is clean, sequencing resolves the one mild overlap |
