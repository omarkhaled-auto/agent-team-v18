# SDK Verification Report — Phase E

Verified: 2026-04-17
Verifier: sdk-verification-agent (Wave 0)
Method: 9 context7 queries against live upstream documentation, compared to Appendix D of `2026-04-16-deep-investigation-report.md` (lines 1438-1743).

---

## Claude Agent SDK

### Query 1: ClaudeSDKClient Bidirectional

- **Context7 source:** `/anthropics/claude-agent-sdk-python` (12 snippets, High reputation) + `/nothflare/claude-agent-sdk-docs` (821 snippets, Medium reputation)
- **Verified shape:**
  ```python
  from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock

  async with ClaudeSDKClient(options=options) as client:
      await client.query("...")
      async for msg in client.receive_response():
          if isinstance(msg, AssistantMessage):
              for block in msg.content:
                  if isinstance(block, TextBlock):
                      print(block.text)
  ```
  Types section confirms: `AssistantMessage`, `UserMessage`, `SystemMessage`, `ResultMessage` as message types. Content blocks: `TextBlock`, `ToolUseBlock`, `ToolResultBlock`.
- **Appendix D section D.1 match:** YES
- **Notes:** Context7 additionally shows `UserMessage` and `ResultMessage` types not listed in Appendix D — additive, not contradictory.

### Query 2: client.interrupt()

- **Context7 source:** `/nothflare/claude-agent-sdk-docs` (Python SDK page)
- **Verified shape:**
  ```python
  async def interrupt(self) -> None
  ```
  > "Shows how to send an interrupt signal to Claude during execution using the `interrupt` method of the `ClaudeSDKClient`. This functionality is primarily effective in streaming mode."

  Example confirms: query → sleep → interrupt → new query → receive_response (session survives, continues with new command).
- **Appendix D section D.1 match:** YES
- **Notes:** Verbatim quote and signature match. Session survival after interrupt confirmed by example.

### Query 3: Session Forking

- **Context7 source:** `/nothflare/claude-agent-sdk-docs` (sessions guide)
- **Verified shape:**
  ```python
  from claude_agent_sdk import query, ClaudeAgentOptions

  # Fork with fresh options
  async for message in query(
      prompt="...",
      options=ClaudeAgentOptions(
          resume=session_id,
          fork_session=True,
          model="claude-sonnet-4-5"
      )
  ):
      ...
  ```
  Context7 confirms:
  - `fork_session=True` generates new session ID, preserving original history
  - Original session remains unchanged and resumable with `fork_session=False`
  - Multiple parallel branches possible from single parent
  - Options are fresh at fork time (can supply different mcp_servers, allowed_tools)
- **Appendix D section D.2 match:** YES
- **Notes:** All fork semantics confirmed exactly. Python uses `fork_session` (snake_case), TypeScript uses `forkSession` (camelCase) — Appendix D correctly uses Python convention.

### Query 4: ClaudeAgentOptions Fields

- **Context7 source:** `/nothflare/claude-agent-sdk-docs` (Python SDK page, quickstart, custom-tools guide)
- **Verified shape:**
  ```python
  ClaudeAgentOptions(
      mcp_servers={"name": server},          # dict[str, McpServer]
      allowed_tools=["mcp__name__tool"],     # list[str] — exact tool names
      permission_mode="acceptEdits",         # Literal["default","acceptEdits","plan","bypassPermissions"]
      model="claude-sonnet-4-5",             # str
      # Additional: system_prompt, max_turns, hooks
  )
  ```
  `McpStdioServerConfig`: `{type?: "stdio", command: str, args?: list[str], env?: dict[str,str]}`
  `PermissionMode`: `Literal["default", "acceptEdits", "plan", "bypassPermissions"]`
- **Appendix D section D.1 match:** YES
- **Minor note:** Appendix D mentions `allowed_tools` accepts `mcp__context7__*` glob patterns. Context7 docs only show exact tool name strings (e.g., `"mcp__utils__calculate"`). Wildcard expansion is not explicitly documented — needs runtime verification. This is INFORMATIONAL, not a structural mismatch.

### Query 5: Message/Content Block Types

- **Context7 source:** `/nothflare/claude-agent-sdk-docs` (Python type definitions)
- **Verified shape:**
  ```python
  @dataclass
  class AssistantMessage:
      content: list[ContentBlock]
      model: str

  @dataclass
  class TextBlock:
      text: str

  @dataclass
  class ToolUseBlock:
      id: str
      name: str
      input: dict[str, Any]

  @dataclass
  class ToolResultBlock:
      tool_use_id: str
      content: str | list[dict[str, Any]] | None = None
      is_error: bool | None = None
  ```
  Orphan-tool detection pairing confirmed: `ToolUseBlock.id` matches `ToolResultBlock.tool_use_id`.
- **Appendix D section D.1 match:** YES
- **Notes:** All field names for orphan-tool detection confirmed exactly.

### Query 6: HookMatcher / Custom Tools (Informational)

- **Context7 source:** `/nothflare/claude-agent-sdk-docs` (hooks guide, custom-tools guide, Python SDK page)
- **Verified shape:**
  ```python
  from claude_agent_sdk import HookMatcher, tool, create_sdk_mcp_server

  # Hooks
  options = ClaudeAgentOptions(
      hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[check_fn])]}
  )

  # Custom tools
  @tool("name", "description", {"param": str})
  async def my_tool(args): ...

  server = create_sdk_mcp_server(name="...", version="...", tools=[my_tool])
  ```
  HookMatcher supports regex patterns: `'Write|Edit|Delete'`, `'^mcp__'`.
  `tool()` decorator returns `SdkMcpTool` instance.
- **Appendix D section D.1 match:** YES
- **Notes:** All APIs available. Regex matcher capability in hooks is additional useful detail.

---

## Codex App-Server

### Query 7: JSON-RPC Methods

- **Context7 source:** `/openai/codex` (870 snippets, High reputation — app-server README)
- **Verified shape:**

  **initialize** (app-server):
  ```json
  {
    "method": "initialize",
    "id": 0,
    "params": {
      "clientInfo": {
        "name": "...",    // Required
        "title": "...",   // Required
        "version": "..."  // Required
      },
      "capabilities": {
        "experimentalApi": true,                    // Optional
        "optOutNotificationMethods": ["..."]        // Optional
      }
    }
  }
  ```
  Response: `{userAgent, codexHome, platformFamily, platformOs}`

  **thread/start:**
  ```json
  {"method": "thread/start", "params": {"model": "gpt-5.4", "cwd": "...", "sandbox": "macos", "config": {"model_reasoning_effort": "high"}}}
  ```
  Response: `{result: {thread: {id, createdAt, updatedAt}}}`

  **turn/start:**
  ```json
  {"method": "turn/start", "params": {"threadId": "...", "input": [{"type": "text", "text": "..."}]}}
  ```

  **turn/interrupt:**
  ```json
  {"method": "turn/interrupt", "params": {"threadId": "...", "turnId": "..."}}
  ```
  Response includes turn with `status: "interrupted"`.

  **Bonus:** `turn/steer` method also exists (modify mid-execution) — not in Appendix D but additive.

- **Appendix D section D.3 match:** YES
- **Critical confirmation:** Method is `thread/start`, NOT `session/new`. Appendix D was correct.

### Query 8: Streaming Notifications

- **Context7 source:** `/openai/codex` (app-server README — Turn Events section)
- **Verified shape:**

  | Event | Payload | Confirmed |
  |---|---|---|
  | `turn/started` | `{turn}` with `turn.status = "inProgress"` | YES |
  | `item/started` | per-item | YES |
  | `item/completed` | per-item | YES |
  | `item/agentMessage/delta` | `{turnId, delta}` | YES |
  | `turn/diff/updated` | `{threadId, turnId, diff}` | YES |
  | `turn/plan/updated` | `{turnId, explanation?, plan}` | YES |
  | `thread/tokenUsage/updated` | per thread | YES |
  | `model/rerouted` | `{threadId, turnId, fromModel, toModel, reason}` | YES |
  | `turn/completed` | `{turn}` with status in `{completed, interrupted, failed}`, optional `turn.error` | YES |

  `turn/completed` error shape: `{message, codexErrorInfo?, additionalDetails?}`

- **Appendix D section D.3 match:** YES
- **Notes:** All 9 notification types confirmed with exact names and payload structures.

### Query 9: Python Bindings

- **Context7 source:** `/openai/codex` (Python SDK docs, API reference)
- **Verified shape:**

  **Package:** `codex_app_server` — EXISTS

  **Classes confirmed:**
  - `Codex(config: AppServerConfig | None = None)` — sync high-level client
  - `AsyncCodex(config: AppServerConfig | None = None)` — async high-level client (NOT in Appendix D, additive)
  - `AppServerClient` — low-level client
  - `AppServerConfig` — configuration

  **High-level API:**
  ```python
  from codex_app_server import Codex
  with Codex() as codex:
      thread = codex.thread_start(model="gpt-5.4", config={"model_reasoning_effort": "high"})
      result = thread.run("Say hello in one sentence.")
      print(result.final_response)
  ```

  **Low-level API:**
  ```python
  from codex_app_server import AppServerClient, AppServerConfig
  with AppServerClient(config=config) as client:
      client.start()
      init = client.initialize()
      thread = client.thread_start({"model": "gpt-5.4"})
      turn = client.turn_start(thread_id, input_items=[...])
      completed = client.wait_for_turn_completed(turn_id)
      for delta in client.stream_text(thread_id, "..."): ...
  ```

  **AppServerConfig fields:** `codex_bin`, `config_overrides` (tuple), `cwd`, `env` (dict), `client_name`, `client_title`, `client_version`, `experimental_api`

- **Appendix D section D.3 match:** YES
- **Notes:** Additional `AsyncCodex` class and `client_title`/`client_version` fields on AppServerConfig not in Appendix D — all additive.

---

## Summary Table

| API | Appendix D Shape | Live Context7 Shape | Match? | Impact if Mismatch |
|-----|-----------------|--------------------|---------|--------------------|
| ClaudeSDKClient.query() | `await client.query(prompt)` | `await client.query(prompt)` | YES | — |
| client.receive_response() | `async for msg in client.receive_response()` | `async for msg in client.receive_response()` | YES | — |
| client.interrupt() | `async def interrupt(self) -> None` | `async def interrupt(self) -> None` | YES | — |
| fork_session=True | `ClaudeAgentOptions(resume=id, fork_session=True)` | `ClaudeAgentOptions(resume=id, fork_session=True)` | YES | — |
| ClaudeAgentOptions.mcp_servers | `dict[str, McpServer]` | `dict[str, McpServer]` | YES | — |
| ClaudeAgentOptions.allowed_tools | `list[str]` | `list[str]` (exact names shown) | YES | Wildcard `*` pattern unconfirmed in docs — INFORMATIONAL |
| ClaudeAgentOptions.permission_mode | `"acceptEdits"` | `Literal["default","acceptEdits","plan","bypassPermissions"]` | YES | — |
| AssistantMessage.content | `list[ContentBlock]` | `list[ContentBlock]` | YES | — |
| TextBlock.text | `str` | `str` | YES | — |
| ToolUseBlock.id/.name/.input | `id: str, name: str, input: dict` | `id: str, name: str, input: dict[str, Any]` | YES | — |
| ToolResultBlock.tool_use_id | `str` | `str` | YES | — |
| HookMatcher | `HookMatcher(matcher=..., hooks=[...])` | `HookMatcher(matcher=..., hooks=[...])` | YES | — |
| create_sdk_mcp_server | `create_sdk_mcp_server(name, version, tools)` | `create_sdk_mcp_server(name, version, tools)` | YES | — |
| @tool decorator | `@tool(name, desc, schema)` | `@tool(name, desc, schema)` | YES | — |
| initialize (codex) | `{clientInfo: {name,title,version}, capabilities?}` | `{clientInfo: {name,title,version}, capabilities?}` | YES | — |
| thread/start (codex) | `"thread/start"` | `"thread/start"` | YES | NOT session/new |
| turn/start (codex) | `{threadId, input}` | `{threadId, input}` | YES | — |
| turn/interrupt (codex) | `{threadId, turnId}` | `{threadId, turnId}` | YES | — |
| item/started + item/completed | notification events | notification events | YES | — |
| turn/completed status | `completed \| interrupted \| failed` | `completed \| interrupted \| failed` | YES | — |
| turn/diff/updated | `{threadId, turnId, diff}` | `{threadId, turnId, diff}` | YES | — |
| thread/tokenUsage/updated | exists | exists | YES | — |
| codex_app_server package | exists: Codex, AppServerClient, AppServerConfig | exists: Codex, AsyncCodex, AppServerClient, AppServerConfig | YES | AsyncCodex is additive |

---

## Verdict

**ALL MATCH — proceed to Wave 1.**

9/9 queries returned substantive documentation from context7. Zero critical mismatches. Zero minor mismatches. All API shapes documented in Appendix D are confirmed against live upstream sources as of 2026-04-17.

### Informational Notes (non-blocking)

1. **allowed_tools wildcard patterns:** Appendix D references `mcp__context7__*` patterns in `allowed_tools`. Context7 docs only show exact tool name strings. Wildcard support should be verified at runtime during implementation but is not a structural concern.
2. **AsyncCodex:** An async counterpart to `Codex` exists in `codex_app_server` but was not documented in Appendix D. Available for use if the migration benefits from async integration.
3. **AppServerConfig extras:** `client_title` and `client_version` fields exist beyond what Appendix D listed. Additive.
4. **Additional message types:** `UserMessage` and `ResultMessage` exist beyond `AssistantMessage`/`SystemMessage`. Additive.
5. **turn/steer:** Additional Codex method `turn/steer` exists for mid-execution modification. Not in Appendix D, potentially useful.
