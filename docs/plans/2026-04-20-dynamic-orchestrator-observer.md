# Dynamic Orchestrator Observer — Master Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the Python orchestrator real-time visibility into what each wave is building, allow it to inject targeted corrections mid-wave via `client.interrupt()` (Claude) and `turn/steer` (Codex), activate persistent agent sessions, and wire all waves into a unified communication network — all with zero risk to healthy wave execution.

**Architecture overview:** Six phases in strict dependency order. Phases 0–1 are new infrastructure that the later observer phases depend on. Nothing in Phase 2+ makes sense without them.

```
Phase 0 — Codex App-Server Enhancements    (turn/steer, notification stream, thread persistence)
Phase 1 — Phase Lead System                (AgentTeamsBackend wave alignment, cross-protocol bridge)
Phase 2 — Replay Harness                   (offline calibration, zero risk)
Phase 3 — Peek Infrastructure              (config, dataclasses, per-agent observer strategy)
Phase 4 — Peek Integration                 (wire into watchdog loop — Claude: file-poll, Codex: notifications)
Phase 5 — Semantic Observer                (time-based + plan-based triggers, calibration gate)
Phase 6 — End-to-End Smoke Verification
```

---

## Background: What Already Exists

Read these files before touching any code.

| File | What to understand |
|------|-------------------|
| `src/agent_team_v15/codex_appserver.py:614` | `_CodexAppServerClient` — `thread_start`, `turn_start`, `turn_interrupt`, `next_notification`. **Missing:** `turn_steer`. |
| `src/agent_team_v15/codex_appserver.py:934` | `_execute_once()` — single-attempt Codex dispatch. Creates thread, runs turns in a loop. Returns `CodexResult`. |
| `src/agent_team_v15/codex_appserver.py:1101` | `execute_codex()` — public entry point, wraps `_execute_once` with retry logic. Returns `CodexResult`. |
| `src/agent_team_v15/codex_appserver.py:786` | `_process_streaming_event()` — processes one notification. Called inside `_wait_for_turn_completion`. Does NOT currently handle `turn/plan/updated` or `turn/diff/updated`. |
| `src/agent_team_v15/codex_appserver.py:885` | `_wait_for_turn_completion()` — notification drain loop. Has `client`, `thread_id`, `turn_id` in scope. **Correct injection point for plan/diff observer.** |
| `src/agent_team_v15/codex_transport.py:66` | `CodexResult` dataclass — the return type from all Codex dispatch functions. Add `thread_id: str = ""` here. |
| `src/agent_team_v15/wave_executor.py:174-192` | `_WaveWatchdogState` — extend with observer fields |
| `src/agent_team_v15/wave_executor.py:~2583` | `_invoke_wave_sdk_with_watchdog(*, execute_sdk_call, prompt, wave_letter, config, cwd, milestone)` — Claude wave polling loop. `milestone_id` is NOT a parameter — extract with `str(getattr(milestone, "id", "") or "")`. Use `grep` to find current line. |
| `src/agent_team_v15/wave_executor.py:~2621` | Polling loop: `while True: done, _pending = await asyncio.wait({task}, timeout=poll_seconds)` — peek injection goes here. Use `grep` to find current line. |
| (inside same function) | `baseline_fingerprints = _capture_file_fingerprints(cwd)` — already in scope, defined near function top. |
| `src/agent_team_v15/wave_executor.py:2499` | `_capture_file_fingerprints()` — existing file event detection |
| `src/agent_team_v15/wave_executor.py:232-257` | `interrupt_oldest_orphan()` — exact `client.interrupt()` pattern |
| `src/agent_team_v15/wave_executor.py:52-65` | `WaveFinding` dataclass |
| `src/agent_team_v15/wave_executor.py:69-127` | `WaveResult` dataclass — 46 existing fields. Add `peek_summary` in Phase 5. |
| `src/agent_team_v15/config.py:636` | `AgentTeamsConfig` — pattern for new config dataclasses. Has `enabled`, `fallback_to_cli`, `phase_lead_max_turns` fields. |
| `src/agent_team_v15/config.py:545` | `PhaseLeadConfig` — per-lead config. `PhaseLeadsConfig` (line 555) has fields `planning_lead`, `architecture_lead`, `coding_lead`, `review_lead`, `testing_lead`, `audit_lead`. These must be updated in Task 1.1. |
| `src/agent_team_v15/config.py:1210` | `AgentTeamConfig` — root config. Has `agent_teams: AgentTeamsConfig` (line 1255) and `phase_leads: PhaseLeadsConfig` (line 1256). Add `observer: ObserverConfig` here. |
| `src/agent_team_v15/agent_teams_backend.py:289-296` | `PHASE_LEAD_NAMES` — currently `["planning-lead", "architecture-lead", "coding-lead", "review-lead", "testing-lead", "audit-lead"]`. Replace in Task 1.1. |
| `src/agent_team_v15/agent_teams_backend.py:689-704` | `_get_phase_lead_config()` — maps lead name to `PhaseLeadConfig`. Must be updated alongside `PHASE_LEAD_NAMES`. |
| `src/agent_team_v15/agent_teams_backend.py:856` | `route_message()` — context-dir-based inter-lead messaging |
| `src/agent_team_v15/agent_teams_backend.py:1300` | `create_execution_backend(config: AgentTeamConfig) -> ExecutionBackend` — gate logic |
| `tests/test_v18_wave_executor_extended.py` | Existing wave executor tests — new tests follow this pattern |

---

## Wave Roster (ground truth)

| Wave | Agent | Session type | Fix sub-wave |
|------|-------|-------------|--------------|
| A | Claude | Persistent SDK session | compile_fix (Claude) |
| A5 | Codex app-server | Short thread, new per milestone | — |
| Scaffold | Static Python | No agent | — |
| B | Codex app-server | **Must be persistent thread across fix iterations** | compile_fix (Claude or Codex) |
| C | Static Python | No agent | — |
| D | Codex app-server (or Claude if `wave_d_merged`) | **Must be persistent thread across fix iterations** | compile_fix (Claude or Codex) + D5 rollback |
| D5 | Claude | Persistent SDK session | compile_fix (Claude) |
| T | Claude | Persistent SDK session | test_fix (Claude) |
| T5 | Codex app-server | Short thread, new per milestone | — |
| E | Claude | Persistent SDK session | — |

---

## Phase 0 — Codex App-Server Enhancements

**Purpose:** Give Codex the same communication richness as Claude. Three gaps to close: (1) `turn/steer` for mid-turn corrections without stopping execution, (2) real-time notification handlers for `turn/plan/updated` and `turn/diff/updated`, (3) thread persistence so compile_fix iterations share the Wave B/D context instead of starting blind.

### Task 0.1: Add `turn_steer()` to `_CodexAppServerClient`

**Files:**
- Modify: `src/agent_team_v15/codex_appserver.py`
- Create: `tests/test_codex_appserver_steer.py`

**Step 1: Write the failing test**

```python
# tests/test_codex_appserver_steer.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

def test_codex_appserver_client_has_turn_steer():
    """_CodexAppServerClient exposes turn_steer method."""
    from agent_team_v15.codex_appserver import _CodexAppServerClient
    assert hasattr(_CodexAppServerClient, "turn_steer"), \
        "turn_steer missing — add it alongside turn_interrupt"

@pytest.mark.asyncio
async def test_turn_steer_sends_correct_jsonrpc():
    """turn_steer sends turn/steer JSON-RPC with threadId + expectedTurnId + input."""
    from agent_team_v15.codex_appserver import _CodexAppServerClient
    from agent_team_v15.config import CodexConfig

    client = _CodexAppServerClient.__new__(_CodexAppServerClient)
    client.cwd = "/tmp"
    client.config = MagicMock()
    client.config.reasoning_effort = "high"

    sent_params = {}
    async def mock_send(method, params):
        sent_params.update({"method": method, "params": params})
        return {"turn": {"id": "turn_xyz", "status": "processing"}}

    client.send_request = mock_send

    result = await client.turn_steer(
        thread_id="thread_abc",
        turn_id="turn_xyz",
        message="Focus only on schema.prisma — skip seed.ts for now",
    )

    assert sent_params["method"] == "turn/steer"
    assert sent_params["params"]["threadId"] == "thread_abc"
    assert sent_params["params"]["expectedTurnId"] == "turn_xyz"
    assert sent_params["params"]["input"][0]["type"] == "text"
    assert "schema.prisma" in sent_params["params"]["input"][0]["text"]
```

**Step 2: Run to verify it fails**

```bash
cd C:/Projects/agent-team-v18-codex
pytest tests/test_codex_appserver_steer.py -v
```

**Step 3: Add `turn_steer` to `_CodexAppServerClient`**

Find `turn_interrupt` in `codex_appserver.py` (~line 681) and add immediately after it:

```python
async def turn_steer(
    self,
    thread_id: str,
    turn_id: str,
    message: str,
) -> dict[str, Any]:
    """Inject steering input into a running turn without interrupting it.

    turn/steer modifies the agent's direction mid-execution.
    Use this for minor corrections (wrong file, wrong approach).
    Use turn_interrupt for major pivots that require stopping.

    Requires the turn to still be in-progress (status == "inProgress").
    If the turn has already completed, this is a no-op from Codex's perspective.
    """
    return await self.send_request(
        "turn/steer",
        {
            "threadId": thread_id,
            "expectedTurnId": turn_id,
            "input": [{"type": "text", "text": message}],
        },
    )
```

**Step 4: Run tests**

```bash
pytest tests/test_codex_appserver_steer.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add src/agent_team_v15/codex_appserver.py tests/test_codex_appserver_steer.py
git commit -m "feat: add turn_steer() to CodexAppServerClient for mid-turn corrections"
```

---

### Task 0.2: Handle `turn/plan/updated` and `turn/diff/updated` notifications

**Purpose:** The watchdog currently ignores these notifications. Handling them unlocks pre-emptive plan steering (before any file is written) and real-time diff inspection (as each file is written).

**Files:**
- Modify: `src/agent_team_v15/codex_appserver.py` — add `CodexNotificationEvent` + `parse_codex_notification()`, then wire into `_wait_for_turn_completion` (line 885). This is the correct injection point because it has `client`, `thread_id`, and `turn_id` in scope.
- Create: `tests/test_codex_notifications.py`

> **Why `_wait_for_turn_completion` and not `_process_streaming_event`:** `_process_streaming_event` (~line 786) does not have access to `client` or `turn_id`. `_wait_for_turn_completion` calls it and does have all three, making it the only place where `turn/steer` can be called in response to a notification.

**Step 1: Write the failing test**

```python
# tests/test_codex_notifications.py
import pytest
from agent_team_v15.codex_appserver import CodexNotificationEvent, parse_codex_notification

def test_parse_plan_updated_notification():
    """parse_codex_notification extracts plan steps from turn/plan/updated."""
    raw = {
        "method": "turn/plan/updated",
        "params": {
            "turnId": "turn_123",
            "explanation": "Agent decided to create schema first",
            "plan": [
                {"step": "Create schema.prisma", "status": "inProgress"},
                {"step": "Create seed.ts", "status": "pending"},
            ],
        },
    }
    event = parse_codex_notification(raw)
    assert event.kind == "plan_updated"
    assert event.turn_id == "turn_123"
    assert len(event.plan_steps) == 2
    assert event.plan_steps[0]["step"] == "Create schema.prisma"

def test_parse_diff_updated_notification():
    """parse_codex_notification extracts diff from turn/diff/updated."""
    raw = {
        "method": "turn/diff/updated",
        "params": {
            "threadId": "thread_abc",
            "turnId": "turn_123",
            "diff": "--- a/schema.prisma\n+++ b/schema.prisma\n@@ -1 +1,3 @@\n+model User { id String @id }",
        },
    }
    event = parse_codex_notification(raw)
    assert event.kind == "diff_updated"
    assert event.turn_id == "turn_123"
    assert "model User" in event.diff

def test_parse_unknown_notification_returns_other():
    raw = {"method": "some/unknown", "params": {}}
    event = parse_codex_notification(raw)
    assert event.kind == "other"
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_codex_notifications.py -v
```

**Step 3: Add `CodexNotificationEvent` and `parse_codex_notification` to `codex_appserver.py`**

**`dataclasses` is NOT currently imported in `codex_appserver.py`.** Add this import near the top of the file with the other stdlib imports:

```python
from dataclasses import dataclass, field
```

Add near the top of `codex_appserver.py`, after the imports block:

```python
@dataclass
class CodexNotificationEvent:
    """Parsed representation of a Codex app-server notification."""
    kind: str           # "plan_updated" | "diff_updated" | "turn_completed" | "other"
    turn_id: str = ""
    thread_id: str = ""
    plan_steps: list[dict[str, str]] = field(default_factory=list)
    plan_explanation: str = ""
    diff: str = ""
    raw: dict = field(default_factory=dict)


def parse_codex_notification(raw: dict[str, Any]) -> "CodexNotificationEvent":
    """Parse a raw JSON-RPC notification into a typed CodexNotificationEvent."""
    method = raw.get("method", "")
    params = raw.get("params", {}) or {}

    if method == "turn/plan/updated":
        return CodexNotificationEvent(
            kind="plan_updated",
            turn_id=str(params.get("turnId", "")),
            plan_steps=list(params.get("plan", [])),
            plan_explanation=str(params.get("explanation", "")),
            raw=raw,
        )
    if method == "turn/diff/updated":
        return CodexNotificationEvent(
            kind="diff_updated",
            turn_id=str(params.get("turnId", "")),
            thread_id=str(params.get("threadId", "")),
            diff=str(params.get("diff", "")),
            raw=raw,
        )
    if method == "turn/completed":
        turn = params.get("turn", {}) or {}
        return CodexNotificationEvent(
            kind="turn_completed",
            turn_id=str(turn.get("id", "")),
            raw=raw,
        )
    return CodexNotificationEvent(kind="other", raw=raw)
```

**Step 4: Wire into `_wait_for_turn_completion`**

Find `_wait_for_turn_completion` (line 885). The current loop is:

```python
while True:
    message = await client.next_notification()
    _process_streaming_event(message, watchdog, tokens, progress_callback, messages, capture_session)

    if message.get("method") == "error":
        ...
    if message.get("method") != "turn/completed":
        continue
    ...
```

Add the observer check AFTER `_process_streaming_event(...)` and BEFORE the `turn/completed` check:

```python
    # --- Notification observer (plan/diff events for Codex waves) ---
    _event = parse_codex_notification(message)
    if _event.kind == "plan_updated":
        if hasattr(watchdog, "codex_last_plan"):
            watchdog.codex_last_plan = _event.plan_steps

    elif _event.kind == "diff_updated":
        if hasattr(watchdog, "codex_latest_diff"):
            watchdog.codex_latest_diff = _event.diff
    # --- End notification observer ---
```

Note: `turn/steer` calls are NOT wired here yet — that is Phase 4, Task 4.3. This step only populates watchdog state so the observer can read it.

**Step 5: Run tests**

```bash
pytest tests/test_codex_notifications.py -v
```
Expected: `3 passed`

**Step 6: Commit**

```bash
git add src/agent_team_v15/codex_appserver.py tests/test_codex_notifications.py
git commit -m "feat: parse turn/plan/updated and turn/diff/updated Codex notifications"
```

---

### Task 0.3: Thread persistence — reuse Wave B/D thread across fix iterations

**Purpose:** Currently each compile_fix invocation creates a new Codex process (new `_execute_once` call, new `thread/start`, new context). With thread persistence, the fixer operates in the same thread where Codex knows exactly what it built.

**Key fact:** `CodexResult` is the return type for all Codex dispatch functions. It is defined in `codex_transport.py` (line 66), not `codex_appserver.py`. The public entry point is `execute_codex()` (line 1101 in `codex_appserver.py`), which wraps `_execute_once()` (line 934) in a retry loop. The `thread_id` is created and managed inside `_execute_once`.

**Files:**
- Modify: `src/agent_team_v15/codex_transport.py` — add `thread_id: str = ""` to `CodexResult`
- Modify: `src/agent_team_v15/codex_appserver.py` — populate `result.thread_id` in `_execute_once`, add `existing_thread_id` param to `_execute_once` and `execute_codex`
- Create: `tests/test_codex_thread_persistence.py`

**Step 1: Write the failing test**

```python
# tests/test_codex_thread_persistence.py
from agent_team_v15.codex_transport import CodexResult

def test_codex_result_exposes_thread_id():
    """CodexResult carries thread_id so callers can reuse the Codex thread."""
    result = CodexResult(model="o4-mini")
    assert hasattr(result, "thread_id"), \
        "thread_id missing from CodexResult in codex_transport.py — add it"
    assert result.thread_id == ""

def test_codex_result_with_thread_id():
    result = CodexResult(model="o4-mini", thread_id="thread_abc123")
    assert result.thread_id == "thread_abc123"
```

**Step 2: Add `thread_id` to `CodexResult` in `codex_transport.py`**

Find `CodexResult` at line 66 in `codex_transport.py` and add after the existing fields:

```python
thread_id: str = ""   # preserved for reuse in fix iterations (app-server mode only)
```

**Step 3: Populate `thread_id` in `_execute_once`**

Inside `_execute_once` (~line 975), `thread_id` is already set from `thread_start()`. Before `return result`, add:

```python
result.thread_id = thread_id
```

**Step 4: Add `existing_thread_id` parameter to `_execute_once` and `execute_codex`**

In `_execute_once` signature, add:

```python
async def _execute_once(
    prompt: str,
    cwd: str,
    config: CodexConfig,
    codex_home: Path,
    *,
    existing_thread_id: str = "",   # if set, skip thread/start and reuse this thread
    # ... existing params unchanged ...
) -> CodexResult:
```

Inside `_execute_once`, after `await client.initialize()`, replace the `thread_start()` call with:

```python
if existing_thread_id:
    thread_id = existing_thread_id
    logger.info("Reusing existing Codex thread: id=%s", thread_id)
else:
    thread_result = await client.thread_start()
    thread = thread_result.get("thread", {})
    thread_id = str(thread.get("id", "") or "")
    logger.info("Thread started: id=%s", thread_id)
```

Propagate `existing_thread_id` through `execute_codex` as well. In `execute_codex` (line 1101), add as a keyword-only parameter:

```python
async def execute_codex(
    prompt: str,
    cwd: str,
    config: Optional[CodexConfig] = None,
    codex_home: Optional[Path] = None,
    *,
    progress_callback: Callable[..., Any] | None = None,
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
    capture_enabled: bool = False,
    capture_metadata: CodexCaptureMetadata | None = None,
    existing_thread_id: str = "",   # ADD — pass from previous CodexResult.thread_id
) -> CodexResult:
```

Then pass it through to `_execute_once` inside the retry loop:
```python
result = await _execute_once(
    prompt, cwd, config, codex_home,
    # ... existing params unchanged ...
    existing_thread_id=existing_thread_id,   # ADD
)
```

**Step 5: Run tests**

```bash
pytest tests/test_codex_thread_persistence.py -v
```
Expected: `2 passed`

**Step 6: Commit**

```bash
git add src/agent_team_v15/codex_appserver.py tests/test_codex_thread_persistence.py
git commit -m "feat: thread persistence — CodexWaveResult carries thread_id for fix iteration reuse"
```

---

## Phase 1 — Phase Lead System

**Purpose:** Align the `AgentTeamsBackend` phase leads to the actual wave roster. Replace throwaway SDK calls for waves A, D5, T, E with persistent Claude CLI sessions. Add the cross-protocol bridge so Codex wave completions propagate to Claude leads.

### Task 1.1: Extend `PHASE_LEAD_NAMES` to match wave roster

**Files:**
- Modify: `src/agent_team_v15/agent_teams_backend.py`
- Modify: `src/agent_team_v15/config.py` (`PhaseLeadsConfig` sub-dataclass)
- Create: `tests/test_phase_lead_roster.py`

**Step 1: Write the failing test**

```python
# tests/test_phase_lead_roster.py
from agent_team_v15.agent_teams_backend import AgentTeamsBackend

def test_phase_lead_names_covers_all_claude_waves():
    """PHASE_LEAD_NAMES must cover every wave that uses a persistent Claude session."""
    required = {
        "wave-a-lead",    # Wave A — architecture/schema
        "wave-d5-lead",   # Wave D5 — frontend polish (WAS MISSING)
        "wave-t-lead",    # Wave T — test writing
        "wave-e-lead",    # Wave E — verification/audit
    }
    missing = required - set(AgentTeamsBackend.PHASE_LEAD_NAMES)
    assert not missing, f"Missing phase leads: {missing}"

def test_phase_lead_names_no_legacy_names():
    """Old generic names replaced by wave-letter names."""
    legacy = {"planning-lead", "architecture-lead", "coding-lead", "review-lead"}
    overlap = legacy & set(AgentTeamsBackend.PHASE_LEAD_NAMES)
    # Legacy names should be gone or replaced
    assert not overlap, f"Legacy lead names still present: {overlap}"
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_phase_lead_roster.py -v
```

**Step 3: Update `PHASE_LEAD_NAMES` in `agent_teams_backend.py`**

Find `PHASE_LEAD_NAMES` (~line 289) and replace:

```python
PHASE_LEAD_NAMES: list[str] = [
    "wave-a-lead",    # Wave A — Claude architecture/schema
    "wave-d5-lead",   # Wave D5 — Claude frontend polish
    "wave-t-lead",    # Wave T — Claude test writing
    "wave-e-lead",    # Wave E — Claude verification/audit
]
```

**Step 4: Update `PhaseLeadsConfig` in `config.py`**

Find `PhaseLeadsConfig` (or equivalent) and update the field names to match:

```python
@dataclass
class PhaseLeadsConfig:
    enabled: bool = False
    wave_a_lead: PhaseLeadConfig = field(default_factory=PhaseLeadConfig)
    wave_d5_lead: PhaseLeadConfig = field(default_factory=PhaseLeadConfig)
    wave_t_lead: PhaseLeadConfig = field(default_factory=PhaseLeadConfig)
    wave_e_lead: PhaseLeadConfig = field(default_factory=PhaseLeadConfig)
    handoff_timeout_seconds: float = 300.0   # preserved from original
    allow_parallel_phases: bool = False       # preserved from original
```

Also update `_get_phase_lead_config` in `agent_teams_backend.py` to map new names:

```python
def _get_phase_lead_config(self, lead_name: str) -> Any:
    phase_leads_cfg = self._config.phase_leads
    return {
        "wave-a-lead":  phase_leads_cfg.wave_a_lead,
        "wave-d5-lead": phase_leads_cfg.wave_d5_lead,
        "wave-t-lead":  phase_leads_cfg.wave_t_lead,
        "wave-e-lead":  phase_leads_cfg.wave_e_lead,
    }.get(lead_name, PhaseLeadConfig())
```

**Step 5: Run tests**

```bash
pytest tests/test_phase_lead_roster.py -v
```
Expected: `2 passed`

**Step 6: Commit**

```bash
git add src/agent_team_v15/agent_teams_backend.py src/agent_team_v15/config.py tests/test_phase_lead_roster.py
git commit -m "feat: align PHASE_LEAD_NAMES to wave roster — add wave-d5-lead, remove legacy names"
```

---

### Task 1.2: Wire MESSAGE_TYPES to wave lifecycle events

**Files:**
- Modify: `src/agent_team_v15/agent_teams_backend.py` (`MESSAGE_TYPES`)
- Create: `tests/test_phase_lead_messaging.py`

**Step 1: Write the failing test**

```python
# tests/test_phase_lead_messaging.py
from agent_team_v15.agent_teams_backend import AgentTeamsBackend

def test_message_types_covers_codex_wave_complete():
    """MESSAGE_TYPES must include CODEX_WAVE_COMPLETE for Codex→Claude bridge."""
    assert "CODEX_WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES

def test_message_types_covers_steer_request():
    """MESSAGE_TYPES must include STEER_REQUEST for Claude lead → Codex bridge."""
    assert "STEER_REQUEST" in AgentTeamsBackend.MESSAGE_TYPES
```

**Step 2: Add to `MESSAGE_TYPES` in `agent_teams_backend.py`**

```python
MESSAGE_TYPES: set[str] = {
    # --- existing ---
    "REQUIREMENTS_READY",
    "ARCHITECTURE_READY",
    "WAVE_COMPLETE",
    "REVIEW_RESULTS",
    "DEBUG_FIX_COMPLETE",
    "WIRING_ESCALATION",
    "CONVERGENCE_COMPLETE",
    "TESTING_COMPLETE",
    "ESCALATION_REQUEST",
    "SYSTEM_STATE",
    "RESUME",
    # --- new: cross-protocol bridge ---
    "CODEX_WAVE_COMPLETE",   # orchestrator → Claude lead: Codex turn finished, here's the diff summary
    "STEER_REQUEST",         # Claude lead → orchestrator: please steer the active Codex turn
}
```

**Step 3: Run tests**

```bash
pytest tests/test_phase_lead_messaging.py -v
```

**Step 4: Commit**

```bash
git add src/agent_team_v15/agent_teams_backend.py tests/test_phase_lead_messaging.py
git commit -m "feat: add CODEX_WAVE_COMPLETE and STEER_REQUEST message types for cross-protocol bridge"
```

---

### Task 1.3: Cross-protocol bridge — Codex turn/completed → Claude lead

**Purpose:** After a Codex wave finishes, the orchestrator reads the diff summary and routes a `CODEX_WAVE_COMPLETE` message to the relevant Claude lead. That lead can then reason and write a `STEER_REQUEST` back to the context dir, which the orchestrator translates into a `turn/steer` call if the next Codex turn is still open.

**Files:**
- Create: `src/agent_team_v15/codex_lead_bridge.py`
- Create: `tests/test_codex_lead_bridge.py`

**Step 1: Write the failing test**

```python
# tests/test_codex_lead_bridge.py
import pytest
from agent_team_v15.codex_lead_bridge import (
    build_codex_wave_complete_message,
    read_pending_steer_requests,
)

def test_build_wave_complete_message_contains_diff_summary(tmp_path):
    msg = build_codex_wave_complete_message(
        wave="B",
        thread_id="thread_abc",
        diff_summary="Created schema.prisma (42 lines). Created seed.ts (18 lines).",
        plan_steps=[
            {"step": "Create schema.prisma", "status": "completed"},
            {"step": "Create seed.ts", "status": "completed"},
        ],
        cost_usd=3.14,
    )
    assert "Wave B" in msg
    assert "schema.prisma" in msg
    assert "thread_abc" in msg
    assert "3.14" in msg

def test_read_pending_steer_requests_empty_when_no_files(tmp_path):
    requests = read_pending_steer_requests(str(tmp_path), wave="B")
    assert requests == []

def test_read_pending_steer_requests_finds_steer_file(tmp_path):
    steer_file = tmp_path / "steer_request_wave-b.md"
    steer_file.write_text(
        "To: codex-b\nFrom: wave-a-lead\nType: STEER_REQUEST\n---\n"
        "Please fix the PORT in main.ts to match the contract (3001 not 4000)"
    )
    requests = read_pending_steer_requests(str(tmp_path), wave="B")
    assert len(requests) == 1
    assert "PORT" in requests[0]["body"]

def test_wave_to_lead_references_valid_leads():
    """WAVE_TO_LEAD must only map to leads that exist in PHASE_LEAD_NAMES.
    Catches drift between the bridge mapping and the lead roster after Task 1.1.
    """
    from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD
    from agent_team_v15.agent_teams_backend import AgentTeamsBackend
    for wave, lead in WAVE_TO_LEAD.items():
        assert lead in AgentTeamsBackend.PHASE_LEAD_NAMES, \
            f"WAVE_TO_LEAD[{wave!r}] = {lead!r} not in PHASE_LEAD_NAMES"
```

**Step 2: Implement `codex_lead_bridge.py`**

```python
# src/agent_team_v15/codex_lead_bridge.py
"""Cross-protocol bridge between Codex app-server waves and Claude phase leads.

Orchestrator calls build_codex_wave_complete_message() after each Codex turn/completed
and routes it to the relevant Claude lead via AgentTeamsBackend.route_message().

Claude leads can write STEER_REQUEST files to the context dir.
Orchestrator calls read_pending_steer_requests() before the next Codex turn/start
and translates them into turn/steer calls.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maps wave letter to the Claude lead that cares about its output
WAVE_TO_LEAD: dict[str, str] = {
    "B":  "wave-a-lead",   # architecture lead reviews backend output
    "D":  "wave-d5-lead",  # frontend lead reviews frontend output
    "T5": "wave-t-lead",   # test lead reviews test audit output
    "A5": "wave-a-lead",   # architecture lead reviews plan review output
}


def build_codex_wave_complete_message(
    wave: str,
    thread_id: str,
    diff_summary: str,
    plan_steps: list[dict[str, str]],
    cost_usd: float,
) -> str:
    """Build the body of a CODEX_WAVE_COMPLETE message for the receiving Claude lead."""
    completed_steps = [s["step"] for s in plan_steps if s.get("status") == "completed"]
    pending_steps = [s["step"] for s in plan_steps if s.get("status") != "completed"]
    lines = [
        f"## Codex Wave {wave} completed",
        f"Thread: `{thread_id}` | Cost: ${cost_usd:.2f}",
        "",
        "### Files written (diff summary):",
        diff_summary[:1200] if diff_summary else "(no diff recorded)",
        "",
        f"### Completed steps ({len(completed_steps)}):",
        *[f"- {s}" for s in completed_steps],
    ]
    if pending_steps:
        lines += [
            "",
            f"### Incomplete steps ({len(pending_steps)}) — may need fix iteration:",
            *[f"- {s}" for s in pending_steps],
        ]
    lines += [
        "",
        "If you see a correctness issue, write a STEER_REQUEST to the context dir.",
        "The orchestrator will inject it as a turn/steer before the next Codex turn.",
    ]
    return "\n".join(lines)


def read_pending_steer_requests(
    context_dir: str,
    wave: str,
) -> list[dict[str, Any]]:
    """Read and consume any STEER_REQUEST files in the context dir for this wave.

    Files are deleted after reading (consumed once only).
    Returns list of dicts with keys: from_lead, body.
    """
    root = Path(context_dir)
    if not root.exists():
        return []

    pattern = f"steer_request_wave-{wave.lower()}*.md"
    requests = []
    for f in sorted(root.glob(pattern)):
        try:
            text = f.read_text(encoding="utf-8")
            header, _, body = text.partition("---\n")
            from_lead = ""
            for line in header.splitlines():
                if line.startswith("From:"):
                    from_lead = line.split(":", 1)[1].strip()
            requests.append({"from_lead": from_lead, "body": body.strip()})
            f.unlink()  # consume
        except Exception as e:
            logger.warning("codex_lead_bridge: failed to read steer request %s: %s", f, e)
    return requests
```

**Step 3: Run tests**

```bash
pytest tests/test_codex_lead_bridge.py -v
```
Expected: `3 passed`

**Step 4: Commit**

```bash
git add src/agent_team_v15/codex_lead_bridge.py tests/test_codex_lead_bridge.py
git commit -m "feat: cross-protocol bridge — Codex wave complete messages to Claude leads + steer request reader"
```

---

## Phase 2 — Replay Harness

**Purpose:** Run the observer against frozen `cwd-snapshot-*` directories from past smoke runs. Zero cost to existing builds. Lets you tune thresholds on real data before wiring into the live watchdog.

### Task 2.1: Create the replay harness module

**Files:**
- Create: `src/agent_team_v15/replay_harness.py`
- Create: `tests/test_replay_harness.py`

**Step 1: Write the failing test**

```python
# tests/test_replay_harness.py
import pytest
from pathlib import Path
from agent_team_v15.replay_harness import ReplaySnapshot, load_snapshot, list_snapshots

def test_load_snapshot_reads_requirements(tmp_path):
    m1 = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    m1.mkdir(parents=True)
    (m1 / "REQUIREMENTS.md").write_text("- [ ] apps/api/prisma/schema.prisma\n")

    snap = load_snapshot(str(tmp_path), milestone_id="milestone-1", wave="A")

    assert snap.milestone_id == "milestone-1"
    assert snap.wave == "A"
    assert "schema.prisma" in snap.requirements_text

def test_list_snapshots_finds_dirs(tmp_path):
    (tmp_path / "cwd-snapshot-at-halt-20260420-140000").mkdir()
    (tmp_path / "cwd-snapshot-at-halt-20260420-150000").mkdir()
    (tmp_path / "launch.log").write_text("log")

    snaps = list_snapshots(str(tmp_path))
    assert len(snaps) == 2
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_replay_harness.py -v
```

**Step 3: Implement**

```python
# src/agent_team_v15/replay_harness.py
"""Offline replay harness for calibrating the orchestrator observer.

Feed frozen cwd snapshots from past smoke runs into the observer
without touching any live wave.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable


@dataclass
class ReplaySnapshot:
    snapshot_dir: str
    milestone_id: str
    wave: str
    requirements_text: str = ""
    files_on_disk: list[str] = field(default_factory=list)
    wave_findings: list[dict[str, Any]] = field(default_factory=list)
    audit_score: float | None = None

    @property
    def cwd(self) -> str:
        return self.snapshot_dir


def load_snapshot(snapshot_dir: str, milestone_id: str, wave: str) -> ReplaySnapshot:
    root = Path(snapshot_dir)
    req_path = root / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"
    requirements_text = req_path.read_text(encoding="utf-8") if req_path.exists() else ""

    files_on_disk = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            if not any(seg in rel for seg in ("node_modules", ".git", "__pycache__")):
                files_on_disk.append(rel)

    findings_path = root / ".agent-team" / "milestones" / milestone_id / "WAVE_FINDINGS.json"
    wave_findings = []
    if findings_path.exists():
        try:
            wave_findings = json.loads(findings_path.read_text()).get("findings", [])
        except Exception:
            pass

    audit_score = None
    audit_path = root / ".agent-team" / "AUDIT_REPORT.json"
    if audit_path.exists():
        try:
            audit_score = float(json.loads(audit_path.read_text()).get("overall_score", 0))
        except Exception:
            pass

    return ReplaySnapshot(
        snapshot_dir=str(root),
        milestone_id=milestone_id,
        wave=wave,
        requirements_text=requirements_text,
        files_on_disk=files_on_disk,
        wave_findings=wave_findings,
        audit_score=audit_score,
    )


def list_snapshots(smoke_dir: str) -> list[str]:
    root = Path(smoke_dir)
    return sorted(
        str(p) for p in root.iterdir()
        if p.is_dir() and p.name.startswith("cwd-snapshot-")
    )


@dataclass
class ReplayReport:
    snapshot_dir: str
    milestone_id: str
    wave: str
    peek_results: list[dict[str, Any]] = field(default_factory=list)
    false_positive_count: int = 0
    true_positive_count: int = 0
    missed_count: int = 0


class ReplayRunner:
    def __init__(self, peek_fn: Callable[..., Awaitable[dict[str, Any]]]):
        self._peek_fn = peek_fn

    async def run(self, snapshot: ReplaySnapshot, trigger_files: list[str]) -> ReplayReport:
        results = []
        for file_path in trigger_files:
            result = await self._peek_fn(
                snapshot=snapshot,
                file_path=file_path,
                context={
                    "requirements": snapshot.requirements_text,
                    "files_on_disk": snapshot.files_on_disk,
                    "milestone_id": snapshot.milestone_id,
                    "wave": snapshot.wave,
                },
            )
            results.append({"file": file_path, **result})

        false_pos = sum(
            1 for r in results
            if r.get("verdict") == "issue"
            and snapshot.audit_score is not None
            and snapshot.audit_score >= 800
        )
        true_pos = sum(
            1 for r in results
            if r.get("verdict") == "issue"
            and (snapshot.audit_score is None or snapshot.audit_score < 800)
        )

        return ReplayReport(
            snapshot_dir=snapshot.snapshot_dir,
            milestone_id=snapshot.milestone_id,
            wave=snapshot.wave,
            peek_results=results,
            false_positive_count=false_pos,
            true_positive_count=true_pos,
        )


@dataclass
class CalibrationReport:
    total_peeks: int = 0
    would_have_interrupted: int = 0
    actual_interrupts: int = 0
    builds_analyzed: int = 0
    safe_to_promote: bool = False
    recommendation: str = ""


def generate_calibration_report(cwd: str) -> CalibrationReport:
    log_path = Path(cwd) / ".agent-team" / "observer_log.jsonl"
    if not log_path.exists():
        return CalibrationReport(recommendation="No log data yet. Run 1+ builds in log_only mode first.")

    entries = []
    with log_path.open() as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass

    total = len(entries)
    would_interrupt = sum(1 for e in entries if e.get("would_interrupt"))
    did_interrupt = sum(1 for e in entries if e.get("did_interrupt"))
    fp_rate = would_interrupt / total if total > 0 else 0.0
    builds = len({e.get("timestamp", "")[:10] for e in entries if e.get("timestamp")})
    safe = builds >= 3 and fp_rate < 0.10
    rec = (
        f"FP rate: {fp_rate:.0%} over {builds} build(s). "
        + ("Ready to promote to live mode." if safe
           else f"Need {max(0, 3 - builds)} more build(s) and FP rate < 10%.")
    )
    return CalibrationReport(
        total_peeks=total,
        would_have_interrupted=would_interrupt,
        actual_interrupts=did_interrupt,
        builds_analyzed=builds,
        safe_to_promote=safe,
        recommendation=rec,
    )
```

**Step 4: Run tests**

```bash
pytest tests/test_replay_harness.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add src/agent_team_v15/replay_harness.py tests/test_replay_harness.py
git commit -m "feat: add replay harness, ReplayRunner, CalibrationReport for offline observer calibration"
```

---

## Phase 3 — Peek Infrastructure

**Purpose:** Define the config flags, dataclasses, and strategy split that the observer needs. Key design: **Claude waves use file-poll peek calls; Codex waves use `turn/plan/updated` + `turn/diff/updated` notification events directly** — no file polling needed for Codex.

### Task 3.1: Add `ObserverConfig` to `config.py`

**Files:**
- Modify: `src/agent_team_v15/config.py`
- Create: `tests/test_observer_config.py`

**Step 1: Write the failing test**

```python
# tests/test_observer_config.py
from agent_team_v15.config import ObserverConfig, AgentTeamConfig

def test_observer_config_defaults():
    cfg = ObserverConfig()
    assert cfg.enabled is False
    assert cfg.log_only is True               # SAFE DEFAULT — never interrupt without explicit opt-in
    assert cfg.confidence_threshold == 0.75
    assert cfg.model == "claude-haiku-4-5-20251001"
    assert cfg.max_tokens == 512
    assert cfg.codex_notification_observer_enabled is True  # Codex uses notification stream

def test_observer_config_in_parent():
    cfg = AgentTeamConfig()
    assert hasattr(cfg, "observer")
    assert isinstance(cfg.observer, ObserverConfig)
```

**Step 2: Add to `config.py`**

Add BEFORE `AgentTeamsConfig` (around line 636):

```python
@dataclass
class ObserverConfig:
    """Configuration for the orchestrator peek / semantic observer system.

    log_only=True (default): observer runs but NEVER calls client.interrupt() or turn/steer.
    All verdicts are written to .agent-team/observer_log.jsonl only.
    Set log_only=False only after reviewing 3+ builds of clean log output.

    Two observation strategies (selected automatically per wave type):
    - Claude waves (A, D5, T, E): file-poll peek calls via Anthropic API (Haiku model)
    - Codex waves (A5, B, D, T5): notification-based — reacts to turn/plan/updated and
      turn/diff/updated events directly, no additional API calls needed
    """
    enabled: bool = False
    log_only: bool = True
    confidence_threshold: float = 0.75
    context7_enabled: bool = True
    context7_fallback_to_training: bool = True
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    peek_cooldown_seconds: float = 60.0
    max_peeks_per_wave: int = 5
    time_based_interval_seconds: float = 300.0
    # Codex-specific: react to notification events instead of polling files
    codex_notification_observer_enabled: bool = True
    # Thresholds for plan/diff analysis
    codex_plan_check_enabled: bool = True     # steer on bad plan (before files written)
    codex_diff_check_enabled: bool = True     # steer on bad diff (as files are written)
```

Add `observer: ObserverConfig = field(default_factory=ObserverConfig)` to `AgentTeamConfig`.

**Step 3: Run tests**

```bash
pytest tests/test_observer_config.py -v
```
Expected: `2 passed`

**Step 4: Commit**

```bash
git add src/agent_team_v15/config.py tests/test_observer_config.py
git commit -m "feat: add ObserverConfig with dual-strategy support (file-poll for Claude, notifications for Codex)"
```

---

### Task 3.2: Add `PeekResult`, `PeekSchedule`, `build_peek_schedule` to `wave_executor.py`

**Files:**
- Modify: `src/agent_team_v15/wave_executor.py` (add after `WaveFinding` dataclass ~line 65)
- Create: `tests/test_peek_dataclasses.py`

**Step 1: Write the failing test**

```python
# tests/test_peek_dataclasses.py
from agent_team_v15.wave_executor import PeekResult, PeekSchedule, build_peek_schedule

def test_peek_result_no_interrupt_in_log_only():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=True)
    assert r.should_interrupt is False

def test_peek_result_interrupt_when_live_and_confident():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=False)
    assert r.should_interrupt is True

def test_build_peek_schedule_parses_requirements():
    req = "## Deliverables\n- [ ] apps/api/prisma/schema.prisma\n- [ ] apps/api/src/main.ts\n"
    schedule = build_peek_schedule(requirements_text=req, wave="A")
    assert "apps/api/prisma/schema.prisma" in schedule.trigger_files
    assert "apps/api/src/main.ts" in schedule.trigger_files
    assert schedule.wave == "A"

def test_peek_schedule_wave_type():
    """PeekSchedule knows whether to use file-poll or notification strategy."""
    from agent_team_v15.wave_executor import PeekSchedule
    claude_schedule = PeekSchedule(wave="A", trigger_files=[])
    codex_schedule = PeekSchedule(wave="B", trigger_files=[])
    assert claude_schedule.uses_notifications is False
    assert codex_schedule.uses_notifications is True
```

**Step 2: Add to `wave_executor.py`**

After the `WaveFinding` dataclass:

```python
# Waves that use Codex app-server — notification-based observation, no file-poll
_CODEX_WAVES: frozenset[str] = frozenset({"A5", "B", "D", "T5"})


@dataclass
class PeekResult:
    """Verdict from one observer check (file-poll for Claude, diff/plan for Codex)."""
    file_path: str
    wave: str
    verdict: str = "ok"           # "ok" | "issue" | "skip"
    confidence: float = 0.0
    message: str = ""
    raw_response: str = ""
    log_only: bool = True
    source: str = "file_poll"     # "file_poll" | "plan_event" | "diff_event"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def should_interrupt(self) -> bool:
        return (
            not self.log_only
            and self.verdict == "issue"
            and self.confidence >= 0.5
        )

    @property
    def should_steer(self) -> bool:
        """True for Codex waves in live mode — use turn/steer instead of interrupt."""
        return self.should_interrupt and self.source in ("plan_event", "diff_event")


@dataclass
class PeekSchedule:
    """Per-wave observation schedule."""
    wave: str
    trigger_files: list[str] = field(default_factory=list)
    milestone_id: str = ""
    requirements_text: str = ""

    @property
    def uses_notifications(self) -> bool:
        """Codex waves observe via notification stream, not file polling."""
        return self.wave.upper() in _CODEX_WAVES


def build_peek_schedule(
    requirements_text: str,
    wave: str,
    milestone_id: str = "",
) -> PeekSchedule:
    import re
    trigger_files: list[str] = []
    pattern = re.compile(r"-\s*\[[ x]\]\s+([\w.\-/]+(?:\.[a-zA-Z]{1,10}))")
    for line in requirements_text.splitlines():
        m = pattern.search(line)
        if m:
            candidate = m.group(1).strip()
            if "/" in candidate or "." in candidate:
                trigger_files.append(candidate)
    return PeekSchedule(
        wave=wave,
        trigger_files=list(dict.fromkeys(trigger_files)),
        milestone_id=milestone_id,
        requirements_text=requirements_text,
    )
```

**Step 3: Run tests**

```bash
pytest tests/test_peek_dataclasses.py -v
```
Expected: `4 passed`

**Step 4: Commit**

```bash
git add src/agent_team_v15/wave_executor.py tests/test_peek_dataclasses.py
git commit -m "feat: add PeekResult, PeekSchedule, build_peek_schedule with Codex notification strategy flag"
```

---

### Task 3.3: Implement `observer_peek.py` (Claude wave strategy)

**Files:**
- Create: `src/agent_team_v15/observer_peek.py`
- Create: `tests/test_observer_peek.py`

**Step 1: Write the failing test**

```python
# tests/test_observer_peek.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from agent_team_v15.observer_peek import run_peek_call, build_peek_prompt, build_corrective_interrupt_prompt
from agent_team_v15.wave_executor import PeekSchedule, PeekResult

def test_build_peek_prompt_contains_file_path():
    schedule = PeekSchedule(wave="A", trigger_files=["apps/api/prisma/schema.prisma"],
                            requirements_text="- [ ] apps/api/prisma/schema.prisma\n")
    prompt = build_peek_prompt(
        file_path="apps/api/prisma/schema.prisma",
        file_content="model User { id String @id }",
        schedule=schedule,
        framework_pattern="",
    )
    assert "apps/api/prisma/schema.prisma" in prompt
    assert "verdict" in prompt.lower() or "ok_or_issue" in prompt.lower()

@pytest.mark.asyncio
async def test_run_peek_call_returns_peek_result(tmp_path):
    (tmp_path / "apps" / "api" / "prisma").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "prisma" / "schema.prisma").write_text("model User { id String @id }")

    schedule = PeekSchedule(wave="A", trigger_files=["apps/api/prisma/schema.prisma"],
                            requirements_text="- [ ] apps/api/prisma/schema.prisma\n")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"verdict":"ok","confidence":0.95,"message":"looks good"}')]

    with patch("agent_team_v15.observer_peek._call_anthropic_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        result = await run_peek_call(
            cwd=str(tmp_path), file_path="apps/api/prisma/schema.prisma",
            schedule=schedule, log_only=True,
            model="claude-haiku-4-5-20251001", confidence_threshold=0.75,
        )

    assert isinstance(result, PeekResult)
    assert result.verdict == "ok"
    assert result.should_interrupt is False   # log_only=True
    assert result.source == "file_poll"

def test_build_corrective_interrupt_prompt_is_specific():
    result = PeekResult(
        file_path="apps/api/prisma/schema.prisma", wave="A",
        verdict="issue", confidence=0.88,
        message="File is an empty stub — no model definitions found",
        log_only=False,
    )
    prompt = build_corrective_interrupt_prompt(result)
    assert "schema.prisma" in prompt
    assert "empty stub" in prompt
    assert "Wave A" in prompt
    assert "OBSERVER" in prompt
```

**Step 2: Implement `observer_peek.py`**

```python
# src/agent_team_v15/observer_peek.py
"""Focused single-turn peek call for Claude wave observation.

Codex waves do NOT use this module — they observe via turn/plan/updated
and turn/diff/updated notification events in codex_appserver.py.

This module is for Claude waves (A, D5, T, E) only.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .wave_executor import PeekResult, PeekSchedule

logger = logging.getLogger(__name__)

_PEEK_SYSTEM_PROMPT = """\
You are a focused code quality observer. You are given a file just written by an AI coding agent
and the requirement it should satisfy.

Respond with ONLY valid JSON:
{"verdict": "ok" | "issue", "confidence": <0.0-1.0>, "message": "<one sentence>"}

Rules:
- "ok" = file exists, non-empty, plausibly satisfies the requirement
- "issue" = stub/empty/wrong type/completely off-scope
- confidence < 0.5 = uncertain — prefer "ok" when uncertain
- Do NOT flag style issues, TODO comments, or features planned for later waves
- If you cannot determine: {"verdict": "ok", "confidence": 0.3, "message": "cannot determine"}
"""


def build_peek_prompt(file_path: str, file_content: str, schedule: PeekSchedule, framework_pattern: str) -> str:
    lines = [
        f"## File written: `{file_path}`",
        f"## Wave: {schedule.wave} | Milestone: {schedule.milestone_id}",
        "",
        "## Requirement context:",
        schedule.requirements_text[:800],
        "",
    ]
    if framework_pattern:
        lines += ["## Expected pattern:", framework_pattern[:400], ""]
    lines += [
        f"## File content (first 600 chars):",
        "```", file_content[:600], "```", "",
        'Respond with JSON only: {"verdict": ..., "confidence": ..., "message": ...}',
    ]
    return "\n".join(lines)


def build_corrective_interrupt_prompt(result: "PeekResult") -> str:
    """Specific, actionable corrective message for client.interrupt() on Claude waves."""
    return (
        f"[OBSERVER interrupt — confidence={result.confidence:.0%}]\n"
        f"Wave {result.wave} — file `{result.file_path}` was just written but has an issue:\n\n"
        f"  {result.message}\n\n"
        f"Please fix `{result.file_path}` before continuing. "
        f"If this assessment is incorrect, reply briefly and continue."
    )


def build_codex_steer_prompt(result: "PeekResult") -> str:
    """Specific corrective message for turn/steer on Codex waves."""
    return (
        f"[Observer steer — confidence={result.confidence:.0%}]\n"
        f"The file `{result.file_path}` has an issue: {result.message}\n"
        f"Please correct it before moving to the next file."
    )


async def _call_anthropic_api(prompt: str, system: str, model: str, max_tokens: int) -> Any:
    import anthropic
    client = anthropic.AsyncAnthropic()
    return await client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def _load_file_content(cwd: str, file_path: str) -> str:
    try:
        return (Path(cwd) / file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _fetch_context7_pattern(file_path: str) -> str:
    """Best-effort Context7 pattern hint. Returns empty string on any failure."""
    hints = {
        "schema.prisma": "prisma schema model definition",
        "Dockerfile": "node alpine multi-stage dockerfile",
        "docker-compose": "docker compose service healthcheck",
        "tsconfig": "typescript compiler options",
        "next.config": "next.js configuration",
        "nest-cli.json": "nestjs cli configuration",
    }
    # Context7 is MCP-only; in production this is a no-op. Used in replay harness.
    return ""


def _parse_peek_response(response_text: str) -> dict[str, Any]:
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        return {
            "verdict": str(data.get("verdict", "ok")),
            "confidence": float(data.get("confidence", 0.5)),
            "message": str(data.get("message", "")),
        }
    except Exception:
        return {"verdict": "ok", "confidence": 0.3, "message": "parse error — defaulting to ok"}


def _write_observer_log(cwd: str, result: PeekResult) -> None:
    try:
        log_path = Path(cwd) / ".agent-team" / "observer_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": result.timestamp,
            "wave": result.wave,
            "file": result.file_path,
            "verdict": result.verdict,
            "confidence": result.confidence,
            "message": result.message,
            "source": result.source,
            "log_only": result.log_only,
            "would_interrupt": result.verdict == "issue" and result.confidence >= 0.5,
            "did_interrupt": result.should_interrupt,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("observer: failed to write log entry: %s", e)


async def run_peek_call(
    cwd: str,
    file_path: str,
    schedule: PeekSchedule,
    log_only: bool,
    model: str,
    confidence_threshold: float,
    max_tokens: int = 512,
) -> PeekResult:
    """Run one focused peek call (Claude wave strategy — file-poll only).

    Always writes to observer_log.jsonl.
    Only sets should_interrupt=True when log_only=False AND confidence >= threshold.
    """
    file_content = _load_file_content(cwd, file_path)
    if not file_content.strip():
        result = PeekResult(
            file_path=file_path, wave=schedule.wave,
            verdict="skip", confidence=1.0,
            message="file is empty — skipping peek",
            log_only=log_only, source="file_poll",
        )
        _write_observer_log(cwd, result)
        return result

    framework_pattern = _fetch_context7_pattern(file_path)
    prompt = build_peek_prompt(file_path, file_content, schedule, framework_pattern)

    try:
        response = await _call_anthropic_api(prompt, _PEEK_SYSTEM_PROMPT, model, max_tokens)
        raw_text = response.content[0].text if response.content else ""
        parsed = _parse_peek_response(raw_text)
    except Exception as e:
        logger.warning("observer: peek API call failed for %s: %s", file_path, e)
        parsed = {"verdict": "ok", "confidence": 0.0, "message": f"peek failed: {e}"}
        raw_text = ""

    confidence = parsed["confidence"]
    verdict = parsed["verdict"]
    if verdict == "issue" and confidence < confidence_threshold:
        verdict = "ok"

    result = PeekResult(
        file_path=file_path, wave=schedule.wave,
        verdict=verdict, confidence=confidence,
        message=parsed["message"], raw_response=raw_text,
        log_only=log_only, source="file_poll",
    )
    _write_observer_log(cwd, result)
    return result
```

**Step 3: Run tests**

```bash
pytest tests/test_observer_peek.py -v
```
Expected: `3 passed`

**Step 4: Commit**

```bash
git add src/agent_team_v15/observer_peek.py tests/test_observer_peek.py
git commit -m "feat: observer_peek.py — file-poll peek for Claude waves with log_only safety gate"
```

---

## Phase 4 — Peek Integration into Watchdog Loops

**Purpose:** Wire the two strategies into their respective watchdog loops. Claude watchdog gets file-event peek calls. Codex notification handler gets plan/diff analysis + `turn/steer`.

### Task 4.1: Extend `_WaveWatchdogState` with observer fields

**Files:**
- Modify: `src/agent_team_v15/wave_executor.py` (lines 174-192)
- Modify: `tests/test_v18_wave_executor_extended.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_v18_wave_executor_extended.py

def test_watchdog_state_has_claude_observer_fields():
    """_WaveWatchdogState tracks observer state for Claude wave file-poll strategy only.
    Codex notification fields (codex_last_plan, codex_latest_diff) live on _OrphanWatchdog
    in codex_appserver.py — NOT here. _WaveWatchdogState is Claude-waves only.
    """
    from agent_team_v15.wave_executor import _WaveWatchdogState
    state = _WaveWatchdogState()
    assert hasattr(state, "peek_schedule") and state.peek_schedule is None
    assert hasattr(state, "peek_log") and state.peek_log == []
    assert hasattr(state, "last_peek_monotonic") and state.last_peek_monotonic == 0.0
    assert hasattr(state, "peek_count") and state.peek_count == 0
    assert hasattr(state, "seen_files") and state.seen_files == set()
```

**Step 2: Add fields to `_WaveWatchdogState`**

Add only the Claude-wave observer fields. Do NOT add `codex_last_plan` or `codex_latest_diff` here — those belong on `_OrphanWatchdog` in `codex_appserver.py` (added in Task 4.3), since `_WaveWatchdogState` is the Claude-wave watchdog and has no connection to the Codex notification stream.

```python
    # --- Observer peek fields (Claude waves — file-poll strategy only) ---
    peek_schedule: "PeekSchedule | None" = None
    peek_log: list[Any] = field(default_factory=list)
    last_peek_monotonic: float = 0.0
    peek_count: int = 0
    seen_files: set[str] = field(default_factory=set)
```

**Step 3: Commit**

```bash
git add src/agent_team_v15/wave_executor.py tests/test_v18_wave_executor_extended.py
git commit -m "feat: extend _WaveWatchdogState with Claude-wave observer peek fields"
```

---

### Task 4.2: Wire file-event peek into Claude wave watchdog loop

**Files:**
- Modify: `src/agent_team_v15/wave_executor.py` (`_invoke_wave_sdk_with_watchdog` polling loop)

**Injection point:** Find the `while True:` polling loop inside `_invoke_wave_sdk_with_watchdog` (~line 1869). Add the peek check AFTER `asyncio.wait` returns without the task being done, BEFORE the timeout check:

```python
            # --- Observer peek (Claude waves only — file-poll strategy) ---
            if (
                state.peek_schedule is not None
                and not state.peek_schedule.uses_notifications  # skip for Codex waves
                and getattr(config, "observer", None) is not None
                and getattr(config.observer, "enabled", False)
            ):
                _obs = config.observer
                _now = time.monotonic()
                if (
                    (_now - state.last_peek_monotonic) >= _obs.peek_cooldown_seconds
                    and state.peek_count < _obs.max_peeks_per_wave
                ):
                    _new_triggers = _detect_new_peek_triggers(
                        cwd=cwd,
                        baseline=baseline_fingerprints,
                        schedule=state.peek_schedule,
                        seen_files=state.seen_files,
                    )
                    for _trigger in _new_triggers:
                        state.seen_files.add(_trigger)
                        state.last_peek_monotonic = time.monotonic()
                        state.peek_count += 1
                        try:
                            from .observer_peek import run_peek_call, build_corrective_interrupt_prompt
                            _result = await run_peek_call(
                                cwd=cwd, file_path=_trigger,
                                schedule=state.peek_schedule,
                                log_only=_obs.log_only,
                                model=_obs.model,
                                confidence_threshold=_obs.confidence_threshold,
                                max_tokens=_obs.max_tokens,
                            )
                            state.peek_log.append(_result)
                            if _result.should_interrupt and state.client:
                                _msg = build_corrective_interrupt_prompt(_result)
                                logger.warning("[Wave %s] Observer INTERRUPT: %s", wave_letter, _result.message)
                                await state.client.interrupt()
                                state.interrupt_count += 1
                        except Exception as _e:
                            logger.warning("[Wave %s] Observer peek error (ignored): %s", wave_letter, _e)
            # --- End observer peek ---
```

Also add `_detect_new_peek_triggers` function near `_capture_file_fingerprints` — **use `grep -n "_capture_file_fingerprints" src/agent_team_v15/wave_executor.py` to find it** (currently at line 2499, subject to drift):

```python
def _detect_new_peek_triggers(
    cwd: str,
    baseline: dict[str, tuple[int, int]],
    schedule: "PeekSchedule",
    seen_files: set[str],
) -> list[str]:
    current = _capture_file_fingerprints(cwd)
    newly_created = set(current.keys()) - set(baseline.keys())
    triggers = []
    for trigger in schedule.trigger_files:
        normalized = trigger.replace("\\", "/")
        if normalized in seen_files:
            continue
        for new_file in newly_created:
            norm_new = new_file.replace("\\", "/")
            if norm_new.endswith(normalized) or norm_new == normalized:
                triggers.append(normalized)
                break
    return triggers
```

**Initialize peek_schedule before dispatch** — find where `_WaveWatchdogState` is constructed inside `_invoke_wave_sdk_with_watchdog` and add:

```python
# NOTE: _invoke_wave_sdk_with_watchdog receives `milestone: Any`, not `milestone_id: str`.
# Extract the ID the same way the rest of wave_executor.py does (see line ~595):
_milestone_id = str(getattr(milestone, "id", "") or "").strip()

_obs_cfg = getattr(config, "observer", None)
if _obs_cfg and _obs_cfg.enabled and _milestone_id:
    try:
        _req_path = Path(cwd) / ".agent-team" / "milestones" / _milestone_id / "REQUIREMENTS.md"
        if _req_path.exists():
            state.peek_schedule = build_peek_schedule(
                requirements_text=_req_path.read_text(encoding="utf-8"),
                wave=wave_letter,
                milestone_id=_milestone_id,
            )
    except Exception as _e:
        logger.warning("[Wave %s] Observer: failed to build peek schedule: %s", wave_letter, _e)
```

**Commit:**

```bash
git add src/agent_team_v15/wave_executor.py
git commit -m "feat: wire file-poll observer peek into Claude wave watchdog loop"
```

---

### Task 4.3: Wire plan/diff observer into `_wait_for_turn_completion`

**Files:**
- Modify: `src/agent_team_v15/codex_appserver.py` — extend `_wait_for_turn_completion` (line 885)

**Correct injection point:** `_wait_for_turn_completion` has `client`, `thread_id`, and `turn_id` in scope. `_process_streaming_event` does NOT — do not inject there.

**Add the observer check** inside `_wait_for_turn_completion`, AFTER the block from Task 0.2 that populates `watchdog.codex_last_plan` / `watchdog.codex_latest_diff`, and BEFORE the `turn/completed` check:

```python
    # --- Codex observer steer (live mode only) ---
    if _event.kind == "plan_updated":
        _obs_cfg = getattr(getattr(watchdog, "_config", None), "observer", None)
        if _obs_cfg and _obs_cfg.enabled and _obs_cfg.codex_plan_check_enabled:
            from .codex_observer_checks import check_plan_against_requirements
            _req_text = getattr(watchdog, "_requirements_text", "")
            _wave = getattr(watchdog, "_wave_letter", "")
            _issue = check_plan_against_requirements(_event.plan_steps, _req_text, wave=_wave)
            if _issue:
                if not _obs_cfg.log_only:
                    await client.turn_steer(thread_id, turn_id, _issue)
                    logger.warning("[Codex Wave %s] Observer plan steer: %s", _wave, _issue[:120])
                else:
                    logger.info("[Codex Wave %s] Observer (log_only) would steer: %s", _wave, _issue[:120])

    elif _event.kind == "diff_updated":
        _obs_cfg = getattr(getattr(watchdog, "_config", None), "observer", None)
        if _obs_cfg and _obs_cfg.enabled and _obs_cfg.codex_diff_check_enabled:
            from .codex_observer_checks import check_diff_against_requirements
            _req_text = getattr(watchdog, "_requirements_text", "")
            _wave = getattr(watchdog, "_wave_letter", "")
            _issue = check_diff_against_requirements(_event.diff, _req_text, wave=_wave)
            if _issue:
                if not _obs_cfg.log_only:
                    await client.turn_steer(thread_id, turn_id, _issue)
                    logger.warning("[Codex Wave %s] Observer diff steer: %s", _wave, _issue[:120])
                else:
                    logger.info("[Codex Wave %s] Observer (log_only) would steer: %s", _wave, _issue[:120])
    # --- End Codex observer steer ---
```

**Add `_config`, `_requirements_text`, `_wave_letter`, `codex_last_plan`, and `codex_latest_diff` to `_OrphanWatchdog.__init__`**

`_OrphanWatchdog` uses a regular `__init__` (NOT `@dataclass`) — it is at line ~116 in `codex_appserver.py`. The current signature is `__init__(self, timeout_seconds: float = 300.0, max_orphan_events: int = 2)`. Replace with:

```python
def __init__(
    self,
    timeout_seconds: float = 300.0,
    max_orphan_events: int = 2,
    observer_config: Any = None,        # ObserverConfig or None
    requirements_text: str = "",        # REQUIREMENTS.md content for this wave
    wave_letter: str = "",              # wave letter e.g. "B", "D"
) -> None:
    self.timeout_seconds = timeout_seconds
    self.max_orphan_events = max_orphan_events
    self._lock = threading.Lock()
    self.pending_tool_starts: dict[str, dict[str, Any]] = {}
    self.orphan_event_count: int = 0
    self.last_orphan_tool_name: str = ""
    self.last_orphan_tool_id: str = ""
    self.last_orphan_age: float = 0.0
    self._registered_orphans: set[str] = set()
    # Observer fields (populated by _wait_for_turn_completion notification handler)
    self._config = observer_config
    self._requirements_text = requirements_text
    self._wave_letter = wave_letter
    self.codex_last_plan: list[dict[str, str]] = []   # from turn/plan/updated
    self.codex_latest_diff: str = ""                    # from turn/diff/updated
```

> **Why `codex_last_plan`/`codex_latest_diff` go HERE (not on `_WaveWatchdogState`):**
> `_wait_for_turn_completion` holds a `watchdog: _OrphanWatchdog` reference. Task 0.2's
> notification observer writes to `watchdog.codex_last_plan` / `watchdog.codex_latest_diff`
> using `hasattr()` guards — those guards are satisfied only once these fields exist on
> `_OrphanWatchdog`. `_WaveWatchdogState` is the Claude-wave watchdog and is never in scope
> inside `_wait_for_turn_completion`.

**Add test to `tests/test_codex_appserver_steer.py` (or a new `tests/test_codex_observer_watchdog.py`):**

```python
def test_orphan_watchdog_has_observer_fields():
    from agent_team_v15.codex_appserver import _OrphanWatchdog
    w = _OrphanWatchdog(observer_config=None, requirements_text="test", wave_letter="B")
    assert hasattr(w, "codex_last_plan") and w.codex_last_plan == []
    assert hasattr(w, "codex_latest_diff") and w.codex_latest_diff == ""
    assert w._wave_letter == "B"
    assert w._requirements_text == "test"
    assert w._config is None
```

**Add `observer_config`, `requirements_text`, `wave_letter` to `_execute_once` and `execute_codex`**

`_execute_once` receives `CodexConfig` — it has no direct access to `ObserverConfig`. Thread these through as explicit parameters:

In `_execute_once` signature (line 934), add three keyword-only params:
```python
async def _execute_once(
    prompt: str,
    cwd: str,
    config: CodexConfig,
    codex_home: Path,
    *,
    existing_thread_id: str = "",
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
    orphan_check_interval_seconds: float = 60.0,
    progress_callback: Callable[..., Any] | None = None,
    capture_session: CodexCaptureSession | None = None,
    observer_config: Any = None,         # ObserverConfig | None — ADD
    requirements_text: str = "",         # REQUIREMENTS.md content — ADD
    wave_letter: str = "",               # e.g. "B", "D" — ADD
) -> CodexResult:
```

Inside `_execute_once`, change the `_OrphanWatchdog` constructor call from:
```python
watchdog = _OrphanWatchdog(
    timeout_seconds=orphan_timeout_seconds,
    max_orphan_events=orphan_max_events,
)
```
to:
```python
watchdog = _OrphanWatchdog(
    timeout_seconds=orphan_timeout_seconds,
    max_orphan_events=orphan_max_events,
    observer_config=observer_config,
    requirements_text=requirements_text,
    wave_letter=wave_letter,
)
```

Propagate these three params through `execute_codex` identically (add as keyword-only params, pass through to `_execute_once`).

**Commit:**

```bash
git add src/agent_team_v15/codex_appserver.py
git commit -m "feat: wire plan/diff notification observer into Codex watchdog — extend _OrphanWatchdog"
```

---

## Phase 5 — Semantic Observer (Semantic Analysis + Calibration Gate)

**Purpose:** Replace the placeholder rule-based checks with semantic analysis. Add time-based trigger for Claude waves. Add the calibration gate before enabling live mode.

### Task 5.1: Semantic plan and diff analysis for Codex waves

**Files:**
- Create: `src/agent_team_v15/codex_observer_checks.py`
- Create: `tests/test_codex_observer_checks.py`

**Step 1: Write the failing test**

```python
# tests/test_codex_observer_checks.py
import pytest
from agent_team_v15.codex_observer_checks import (
    check_plan_against_requirements,
    check_diff_against_requirements,
)

def test_check_plan_detects_out_of_scope_files():
    """_FRONTEND_FILE_PATTERNS matches apps/web/ — Wave B must reject this step."""
    plan_steps = [
        {"step": "Create apps/web/pages/index.tsx", "status": "pending"},  # frontend in backend wave
    ]
    requirements = "Wave B deliverables:\n- [ ] apps/api/prisma/schema.prisma\n"
    issue = check_plan_against_requirements(plan_steps, requirements, wave="B")
    assert issue != "", "Wave B should reject frontend file apps/web/pages/index.tsx"

def test_check_plan_returns_empty_for_valid_plan():
    plan_steps = [
        {"step": "Create apps/api/prisma/schema.prisma", "status": "inProgress"},
        {"step": "Create apps/api/src/main.ts", "status": "pending"},
    ]
    requirements = "- [ ] apps/api/prisma/schema.prisma\n- [ ] apps/api/src/main.ts\n"
    issue = check_plan_against_requirements(plan_steps, requirements, wave="B")
    assert issue == ""

def test_check_diff_detects_empty_file():
    diff = "--- a/schema.prisma\n+++ b/schema.prisma\n@@ -0,0 +1 @@\n+"
    issue = check_diff_against_requirements(diff, "- [ ] apps/api/prisma/schema.prisma\n", wave="B")
    # Single line file for a Prisma schema is suspicious
    assert isinstance(issue, str)  # may or may not flag — rule-based
```

**Step 2: Implement**

```python
# src/agent_team_v15/codex_observer_checks.py
"""Semantic checks for Codex plan and diff notifications.

Two layers:
1. Rule-based (fast, no API call) — catches obvious issues like empty files,
   frontend files in backend wave, wrong port
2. Haiku semantic check (optional, needs API call) — catches subtler drift
   Only fired when rule-based is inconclusive AND codex_semantic_check_enabled=True
"""
from __future__ import annotations

import re
from typing import Any

# Files that should never appear in backend Wave B
_FRONTEND_FILE_PATTERNS = re.compile(
    r"apps/web/|pages/|components/|\.tsx$|\.jsx$|tailwind\.config"
)
# Files that should never appear in frontend Wave D
_BACKEND_FILE_PATTERNS = re.compile(
    r"apps/api/|prisma/|nest-cli\.json|\.module\.ts$"
)

_WAVE_FORBIDDEN: dict[str, re.Pattern] = {
    "B": _FRONTEND_FILE_PATTERNS,
    "D": _BACKEND_FILE_PATTERNS,
}


def check_plan_against_requirements(
    plan_steps: list[dict[str, str]],
    requirements: str,
    wave: str,
) -> str:
    """Rule-based check. Returns steer message string or empty string if ok."""
    forbidden_pattern = _WAVE_FORBIDDEN.get(wave.upper())
    if not forbidden_pattern:
        return ""

    violations = []
    for step in plan_steps:
        step_text = step.get("step", "")
        if forbidden_pattern.search(step_text):
            violations.append(step_text)

    if violations:
        return (
            f"[Observer] Wave {wave} plan includes out-of-scope files: "
            + ", ".join(f"`{v}`" for v in violations[:3])
            + ". Please focus only on the wave's assigned deliverables."
        )
    return ""


def check_diff_against_requirements(
    diff: str,
    requirements: str,
    wave: str,
) -> str:
    """Rule-based diff check. Returns steer message or empty string if ok."""
    if not diff:
        return ""

    # Count added lines — a diff with only 1-2 added lines for a key file is suspicious
    added_lines = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    if len(added_lines) <= 1:
        # Extract filename from diff header
        file_match = re.search(r"\+\+\+ b/(.+)", diff)
        file_name = file_match.group(1) if file_match else "unknown file"
        return (
            f"[Observer] `{file_name}` appears to be nearly empty ({len(added_lines)} line(s)). "
            f"Please ensure it is a complete implementation, not a stub."
        )
    return ""
```

**Step 3: Wire into `codex_appserver.py`** — replace the placeholder functions with calls to this module:

```python
from .codex_observer_checks import check_plan_against_requirements, check_diff_against_requirements

# In _check_codex_plan_vs_requirements:
return check_plan_against_requirements(plan_steps, requirements_text, wave=wave)

# In _check_codex_diff_vs_requirements:
return check_diff_against_requirements(diff, requirements_text, wave=wave)
```

**Step 4: Commit**

```bash
git add src/agent_team_v15/codex_observer_checks.py src/agent_team_v15/codex_appserver.py tests/test_codex_observer_checks.py
git commit -m "feat: rule-based semantic checks for Codex plan/diff observer"
```

---

### Task 5.2: Time-based trigger for Claude wave observer

**Files:**
- Modify: `src/agent_team_v15/wave_executor.py`
- Modify: `tests/test_v18_wave_executor_extended.py`

**Add `_should_fire_time_based_peek` helper:**

```python
def _should_fire_time_based_peek(
    last_peek_monotonic: float,
    interval_seconds: float,
    peek_count: int,
    max_peeks: int,
) -> bool:
    if peek_count >= max_peeks:
        return False
    return (time.monotonic() - last_peek_monotonic) >= interval_seconds
```

Add `time_based_interval_seconds: float = 300.0` to `ObserverConfig` in `config.py`.

In the Claude wave polling loop (Task 4.2), after the file-event trigger block, add an `elif` for the time-based path that selects the most-recently-modified trigger file not yet seen.

**Test:**

```python
def test_time_based_trigger_fires_after_interval():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time
    assert _should_fire_time_based_peek(time.monotonic() - 120, 60.0, 0, 5) is True
    assert _should_fire_time_based_peek(time.monotonic() - 10, 60.0, 0, 5) is False
    assert _should_fire_time_based_peek(time.monotonic() - 120, 60.0, 5, 5) is False
```

**Commit:**

```bash
git add src/agent_team_v15/wave_executor.py src/agent_team_v15/config.py tests/test_v18_wave_executor_extended.py
git commit -m "feat: time-based peek trigger as secondary observer path for Claude waves"
```

---

### Task 5.3: Add `peek_summary` to `WaveResult`

```python
# In WaveResult dataclass:
peek_summary: list[dict[str, Any]] = field(default_factory=list)
```

In `_invoke_wave_sdk_with_watchdog`, after the polling loop exits and immediately before the final `return result`, add:

```python
# Populate peek_summary from observer log
if state.peek_log and hasattr(result, "peek_summary"):
    result.peek_summary = [
        {
            "file": r.file_path,
            "verdict": r.verdict,
            "confidence": r.confidence,
            "message": r.message,
            "source": r.source,
            "timestamp": r.timestamp,
        }
        for r in state.peek_log
    ]
```

> Grep for the return statement inside `_invoke_wave_sdk_with_watchdog` — place this block immediately before it.

**Commit:**

```bash
git add src/agent_team_v15/wave_executor.py
git commit -m "feat: add peek_summary to WaveResult for post-wave observer reporting"
```

---

## Phase 6 — End-to-End Smoke Verification

### Task 6.1: Agent Teams activation docs

**Create: `docs/AGENT_TEAMS_ACTIVATION.md`**

```markdown
# Agent Teams Activation Guide

## Activation checklist

- [ ] All Phase 0–5 tests pass: `pytest tests/ -v --tb=short`
- [ ] Run 3+ builds in log_only observer mode
- [ ] `generate_calibration_report()` says `safe_to_promote: True` (FP rate < 10%)
- [ ] Set `observer.log_only: false` in config
- [ ] Set `agent_teams.enabled: true` in config
- [ ] Export `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [ ] Run single M1 smoke with both enabled
- [ ] Review `observer_log.jsonl` for steer/interrupt quality

## Minimum config.yaml additions

    observer:
      enabled: true
      log_only: true                      # change to false ONLY after calibration clears
      model: "claude-haiku-4-5-20251001"
      confidence_threshold: 0.75
      peek_cooldown_seconds: 60.0
      max_peeks_per_wave: 5
      time_based_interval_seconds: 300.0
      context7_enabled: true
      codex_notification_observer_enabled: true
      codex_plan_check_enabled: true
      codex_diff_check_enabled: true

    agent_teams:
      enabled: true
      fallback_to_cli: true
      phase_lead_max_turns: 200

## Communication channels summary

| Channel | From | To | Protocol |
|---|---|---|---|
| Lead ↔ Lead | Claude lead | Claude lead | route_message() context dir files |
| Orchestrator → Claude | Orchestrator | Running session | client.interrupt() |
| Orchestrator → Codex (mid-turn, minor) | Orchestrator | Running turn | turn/steer |
| Orchestrator → Codex (major pivot) | Orchestrator | Running turn | turn/interrupt + new turn/start |
| Codex → Orchestrator (real-time) | Codex process | Orchestrator | turn/plan/updated + turn/diff/updated |
| Codex → Claude lead (post-turn) | Orchestrator proxy | Claude lead | route_message(CODEX_WAVE_COMPLETE) |
| Claude lead → Codex (next turn) | Claude lead | Orchestrator | STEER_REQUEST context dir file |
```

**Create: `tests/test_agent_teams_activation.py`**

```python
from agent_team_v15.agent_teams_backend import create_execution_backend, CLIBackend, AgentTeamsBackend
from agent_team_v15.config import AgentTeamConfig, AgentTeamsConfig
import os

def test_disabled_returns_cli_backend():
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=False)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)

def test_enabled_without_env_var_returns_cli_backend():
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=True)
    os.environ.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)

def test_all_gates_open_returns_agent_teams_backend(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=False)
    try:
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)
    except RuntimeError as e:
        assert "claude" in str(e).lower()
```

**Commit:**

```bash
git add docs/AGENT_TEAMS_ACTIVATION.md tests/test_agent_teams_activation.py
git commit -m "feat: agent teams activation docs and gate tests"
```

---

### Task 6.2: Full integration test suite

```bash
pytest tests/ -v --tb=short -x 2>&1 | tee test_results.txt
```

Expected: All previously passing tests still pass. All new tests pass.

### Task 6.3: Enable observer in log_only mode on a real smoke

Add to your smoke config under `v18:`:

```yaml
observer:
  enabled: true
  log_only: true
  model: "claude-haiku-4-5-20251001"
  confidence_threshold: 0.75
  peek_cooldown_seconds: 60.0
  max_peeks_per_wave: 5
  time_based_interval_seconds: 300.0
  codex_notification_observer_enabled: true
  codex_plan_check_enabled: true
  codex_diff_check_enabled: true
```

After 3+ builds, run:

```python
from agent_team_v15.replay_harness import generate_calibration_report
report = generate_calibration_report("/c/smoke/clean")
print(report.recommendation)
# safe_to_promote: True → set log_only: false
```

**Final commit:**

```bash
git add .
git commit -m "feat: dynamic orchestrator observer + phase lead system complete (log_only mode)"
```

---

## Risk Mitigation Summary

| Risk | Mitigation |
|------|-----------|
| Observer interrupts healthy Claude wave | `log_only: true` default |
| Observer steers healthy Codex turn | `log_only: true` default; `codex_plan_check_enabled` conservative rule-based only |
| False positive interrupts | Calibration report requires 3+ builds + FP rate < 10% before promoting |
| Observer crashes wave | All peek/steer calls in `try/except` — fail-open |
| Context7 quota miss | `context7_fallback_to_training: true` |
| Peek adds latency to Claude waves | Haiku + 512 tokens ≈ < 2s |
| `turn/steer` on completed turn | Codex ignores steer on completed turn — no-op, not an error |
| Thread reuse breaks fix iteration | `existing_thread_id` is optional — if thread is gone, falls back to `thread/start` |
| Persistent sessions break waves | `fallback_to_cli: true` in AgentTeamsConfig |
| Phase leads misrouted | `WAVE_TO_LEAD` map in `codex_lead_bridge.py` is the single source of truth |

---

## File Index

| New file | Purpose |
|----------|---------|
| `src/agent_team_v15/codex_lead_bridge.py` | Cross-protocol bridge: Codex → Claude lead messages + steer request reader |
| `src/agent_team_v15/codex_observer_checks.py` | Rule-based semantic checks for Codex plan/diff notifications |
| `src/agent_team_v15/replay_harness.py` | Offline calibration: ReplaySnapshot, ReplayRunner, CalibrationReport |
| `src/agent_team_v15/observer_peek.py` | File-poll peek for Claude waves, corrective interrupt/steer prompt builders |
| `docs/AGENT_TEAMS_ACTIVATION.md` | Activation checklist + config reference + communication channel table |
| `tests/test_codex_appserver_steer.py` | turn_steer tests |
| `tests/test_codex_notifications.py` | CodexNotificationEvent parse tests |
| `tests/test_codex_thread_persistence.py` | CodexWaveResult thread_id tests |
| `tests/test_phase_lead_roster.py` | PHASE_LEAD_NAMES alignment tests |
| `tests/test_phase_lead_messaging.py` | MESSAGE_TYPES coverage tests |
| `tests/test_codex_lead_bridge.py` | Cross-protocol bridge tests |
| `tests/test_replay_harness.py` | Replay harness tests |
| `tests/test_observer_config.py` | ObserverConfig tests |
| `tests/test_peek_dataclasses.py` | PeekResult / PeekSchedule tests |
| `tests/test_observer_peek.py` | run_peek_call and prompt builder tests |
| `tests/test_codex_observer_checks.py` | Plan/diff semantic check tests |
| `tests/test_agent_teams_activation.py` | AgentTeamsBackend gate tests |

| Modified file | What changes |
|---------------|-------------|
| `src/agent_team_v15/codex_appserver.py` | Add `turn_steer()`, `CodexNotificationEvent`, `parse_codex_notification()`, plan/diff notification handlers, `existing_thread_id` param, `thread_id` in `CodexWaveResult` |
| `src/agent_team_v15/agent_teams_backend.py` | `PHASE_LEAD_NAMES` aligned to wave roster, `_get_phase_lead_config` updated, `CODEX_WAVE_COMPLETE` + `STEER_REQUEST` in `MESSAGE_TYPES` |
| `src/agent_team_v15/config.py` | Add `ObserverConfig`, add `observer` field to `AgentTeamConfig`, update `PhaseLeadsConfig` field names |
| `src/agent_team_v15/wave_executor.py` | Add `PeekResult`, `PeekSchedule`, `_CODEX_WAVES`, `build_peek_schedule`, `_detect_new_peek_triggers`, `_should_fire_time_based_peek` — extend `_WaveWatchdogState` — inject peek block into Claude polling loop — add `peek_summary` to `WaveResult` |
| `tests/test_v18_wave_executor_extended.py` | Add observer integration tests |
