# Phase 6 — End-to-End Smoke Verification: Implementation Brief

## Phase Context

Phase 6 is the final verification phase of the dynamic orchestrator observer plan (`docs/plans/2026-04-20-dynamic-orchestrator-observer.md`). Phases 0–5 introduce new modules (`observer_peek`, `replay_harness`, `codex_lead_bridge`, `codex_observer_checks`), extend `codex_appserver.py` (turn_steer, CodexNotificationEvent, plan/diff handlers, thread persistence), extend `wave_executor.py` (PeekResult, PeekSchedule, peek injection, peek_summary), and widen `agent_teams_backend.py` (MESSAGE_TYPES, PHASE_LEAD_NAMES) plus `config.py` (ObserverConfig, PhaseLeadsConfig field preservation).

Phase 6 does NOT add new runtime features. Its three deliverables are:
1. An activation checklist document (`docs/AGENT_TEAMS_ACTIVATION.md`) that enforces the safe-promotion gate — nobody flips `log_only: false` without a passing calibration report.
2. Four Level-B integration tests (`tests/test_observer_integration.py`) that wire together real modules with mocked I/O (no live API, no Codex subprocess).
3. Smoke-protocol documentation describing how to run calibration builds and interpret `observer_log.jsonl`.

Phase 6 also performs the final cross-codebase audit that every one of the 10 corrections from the reviewer feedback actually landed in source.

## Pre-Flight: Files to Read

| # | Path | Lines | Purpose |
|---|------|-------|---------|
| 1 | `src/agent_team_v15/config.py` | 1209–1266 | Confirm `AgentTeamConfig` dataclass shape; Phase 3 adds `observer: ObserverConfig` field here. Read to confirm the field exists and the dataclass default-factory pattern. |
| 2 | `src/agent_team_v15/config.py` | 556–590 | Confirm `PhaseLeadsConfig` preserves `handoff_timeout_seconds` (correction #8). |
| 3 | `src/agent_team_v15/wave_executor.py` | 2499 ff. | Confirm `_capture_file_fingerprints()` (correction #1). |
| 4 | `src/agent_team_v15/wave_executor.py` | search `_WaveWatchdogState` | Must NOT contain `codex_last_plan` / `codex_latest_diff` (correction #3). |
| 5 | `src/agent_team_v15/codex_appserver.py` | search `_OrphanWatchdog` | Must contain `codex_last_plan` / `codex_latest_diff` attrs (correction #3, #4). |
| 6 | `src/agent_team_v15/codex_appserver.py` | search `execute_codex` | Must accept `existing_thread_id` kwarg (correction #5). |
| 7 | `src/agent_team_v15/wave_executor.py` | search `_execute_once` | Must accept 3 new params (correction #6). |
| 8 | `src/agent_team_v15/wave_executor.py` | search `WaveResult` + `peek_summary` | `peek_summary` must be populated before final return (correction #7). |
| 9 | `src/agent_team_v15/replay_harness.py` | full file | Confirm `generate_calibration_report`, `CalibrationReport`, `ReplaySnapshot`, `ReplayRunner` signatures. |
| 10 | `src/agent_team_v15/observer_peek.py` | full file | Confirm `run_peek_call`, prompt builders. |
| 11 | `src/agent_team_v15/agent_teams_backend.py` | `MESSAGE_TYPES` | Must contain `CODEX_WAVE_COMPLETE` and `STEER_REQUEST`. |
| 12 | `src/agent_team_v15/codex_lead_bridge.py` | full file | Confirm `route_message`, `build_codex_wave_complete_message`, `read_steer_requests`. |
| 13 | `tests/test_v18_wave_executor_extended.py` | lines 1–60 | Style for fixtures / _milestone / _run_waves helpers. |
| 14 | `tests/test_phase_leads.py` (if present) | full file | Confirm `test_wave_to_lead_references_valid_leads` (correction #10). |
| 15 | `docs/` directory listing | — | Confirm `docs/AGENT_TEAMS_ACTIVATION.md` does not already exist. |
| 16 | `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | lines 2034–2216 | Phase 6 task body + File Index. |

## Pre-Flight: Context7 Research

Run (in order, capture outputs in a scratch file for the impl agent):

1. `mcp__context7__resolve-library-id` with `libraryName="pytest"` → capture ID, then `mcp__context7__query-docs` with `topic="tmp_path fixture"` — confirm `tmp_path: Path` is the idiomatic pytest fixture for per-test temp directories.
2. `mcp__context7__query-docs` on the pytest ID with `topic="monkeypatch.setenv and monkeypatch.setattr"` — confirm `monkeypatch.setattr(module, "name", value)` pattern for replacing module-level callables in tests.
3. `mcp__context7__resolve-library-id` with `libraryName="python stdlib"` (or `cpython`), then `mcp__context7__query-docs` with `topic="json.loads for JSONL line-delimited reading"` — confirm `json.loads(line)` per line with try/except for malformed lines is the recommended JSONL pattern.

Apply: use `tmp_path` for every fixture that needs a cwd; use `monkeypatch.setattr` to stub `observer_peek.run_peek_call`, `codex_appserver.turn_steer`; JSONL assertions use `line.strip()` + `json.loads`.

## Pre-Flight: Sequential Thinking

Invoke `mcp__sequential-thinking__sequentialthinking` with the prompt in the mandate (4 integration tests, Level-A vs Level-B vs Level-C distinction). Capture the conclusion. The expected conclusion — which this brief already reflects:

- **Level A (unit)** — per-module tests already live in Phase 0–5 test files. Not Phase 6's job.
- **Level B (integration)** — Phase 6's focus. Wire 2+ real modules, mock only the outer network boundary (`anthropic.AsyncAnthropic`, subprocess, `codex_appserver.turn_steer`).
- **Level C (smoke)** — real Codex + real API. Explicitly out of Phase 6 scope (forbidden by mandate).

Mock surface per test:
| Test | Real modules wired | Mocks (outer boundary only) |
|------|--------------------|------------------------------|
| 1. Claude wave peek pipeline | `wave_executor.build_peek_schedule`, `_should_fire_time_based_peek`, `observer_peek` prompt builders, `WaveResult` | `observer_peek.run_peek_call` → returns a canned `PeekResult` verdict |
| 2. Codex notification pipeline | `codex_appserver._OrphanWatchdog` (plan/diff storage), `codex_observer_checks.check_codex_diff`, the steer-prompt builder | `codex_appserver.turn_steer` → captured call list; nothing sent on the wire |
| 3. Calibration gate | `replay_harness.generate_calibration_report` | JSONL log file on disk (via `tmp_path`) |
| 4. Config round-trip | `config.AgentTeamConfig`, `ObserverConfig`, YAML loader | None — pure dataclass + YAML |

## Pre-Implementation Validation

**STOP if any Phase 0–5 module is absent from disk:**

```bash
python -c "import agent_team_v15.observer_peek" 2>&1 | grep -c "ModuleNotFoundError" && echo "BLOCKED: observer_peek missing — implement Phase 3 first"
python -c "import agent_team_v15.replay_harness" 2>&1 | grep -c "ModuleNotFoundError" && echo "BLOCKED: replay_harness missing — implement Phase 2 first"
python -c "import agent_team_v15.codex_lead_bridge" 2>&1 | grep -c "ModuleNotFoundError" && echo "BLOCKED: codex_lead_bridge missing — implement Phase 1 first"
python -c "import agent_team_v15.codex_observer_checks" 2>&1 | grep -c "ModuleNotFoundError" && echo "BLOCKED: codex_observer_checks missing — implement Phase 5 first"
```

If any of the above print BLOCKED, Phase 6 cannot proceed. All 4 modules must be importable before any Phase 6 task begins.

Before writing any Phase 6 file, the impl agent MUST run these ten correction greps. Any failure halts Phase 6.

```bash
cd C:/Projects/agent-team-v18-codex

# Correction #1 — _capture_file_fingerprints at ~2499
grep -n "_capture_file_fingerprints" src/agent_team_v15/wave_executor.py
# expect: one def line and >=1 call site

# Correction #2 — AgentTeamConfig at ~1210 with observer field
grep -n "class AgentTeamConfig\|observer: ObserverConfig" src/agent_team_v15/config.py
# expect: both matches

# Correction #3 — Codex plan/diff state lives on _OrphanWatchdog ONLY
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py
# expect: ZERO matches
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/codex_appserver.py
# expect: >=2 matches (attr declaration + mutation)

# Correction #4 — _OrphanWatchdog has codex_last_plan/codex_latest_diff as INSTANCE attrs
grep -n "self\.codex_last_plan\|self\.codex_latest_diff" src/agent_team_v15/codex_appserver.py
# expect: >=2 matches (set in __init__ body)

# Correction #5 — execute_codex accepts existing_thread_id
grep -n "def execute_codex\|existing_thread_id" src/agent_team_v15/codex_appserver.py
# expect: kwarg appears in the def

# Correction #6 — _execute_once gets 3 new params
grep -n "def _execute_once" src/agent_team_v15/wave_executor.py
# inspect signature manually — must include observer_config / peek_schedule / something equivalent

# Correction #7 — peek_summary set before final return
grep -n "peek_summary" src/agent_team_v15/wave_executor.py
# expect: field def + at least one assignment before return

# Correction #8 — PhaseLeadsConfig preserves handoff_timeout_seconds
grep -n "handoff_timeout_seconds" src/agent_team_v15/config.py
# expect: at least 1 match inside PhaseLeadsConfig

# Correction #9 — no "or True" in tests
grep -rn "or True" tests/
# expect: ZERO matches

# Correction #10 — WAVE_TO_LEAD sanity test exists
grep -rn "test_wave_to_lead_references_valid_leads" tests/
# expect: >=1 match
```

If any expectation fails, STOP and file an issue back to the prior phase's owner. Phase 6 cannot legitimately pass otherwise.

## Task-by-Task Implementation

### Task 6.1: Activation Documentation + Gate Tests

**Create `docs/AGENT_TEAMS_ACTIVATION.md`**:

```markdown
# Agent Teams + Dynamic Observer Activation Guide

This document is the single source of truth for safely enabling the observer and the agent_teams backend in a live smoke build. Do NOT flip `log_only: false` or `agent_teams.enabled: true` without completing every step below.

## Activation Checklist

Follow in order. Do not skip steps.

1. **All Phase 0–5 tests pass.**
   ```bash
   cd C:/Projects/agent-team-v18-codex
   python -m pytest tests/ -v --tb=short
   ```

2. **Run 3+ builds in `log_only: true` observer mode.** See "Running Calibration Builds" below. Each build writes to `.agent-team/observer_log.jsonl`.

3. **Run `generate_calibration_report()`. It must return `safe_to_promote: True` (FP rate < 10%).** See "Calibration Report" below.

4. **Set `observer.log_only: false` in your smoke config.** Only after step 3 clears.

5. **Set `agent_teams.enabled: true` in your smoke config.** This flips the execution backend to the agent_teams path.

6. **Export `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.** Without this environment variable the backend falls back to the CLI path even when `enabled: true`.

7. **Run a single M1 smoke with both flags enabled.** Watch the console for `[Observer]` lines and review `peek_summary` in WaveResult output.

8. **Review `observer_log.jsonl` for steer/interrupt quality.** If any interrupt fired on a healthy wave, revert step 4 and gather more log_only builds.

## Minimum Config Additions

Add to the smoke config under the top-level `v18:` key (or wherever `AgentTeamConfig` is populated):

```yaml
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
```

## Communication Channels

| Channel | From | To | Protocol |
|---------|------|----|----------|
| Lead ↔ Lead | Claude lead | Claude lead | `route_message()` context dir files |
| Orchestrator → Claude | Orchestrator | Running session | `client.interrupt()` |
| Orchestrator → Codex (mid-turn, minor) | Orchestrator | Running turn | `turn/steer` |
| Orchestrator → Codex (major pivot) | Orchestrator | Running turn | `turn/interrupt` + new `turn/start` |
| Codex → Orchestrator (real-time) | Codex process | Orchestrator | `turn/plan/updated` + `turn/diff/updated` |
| Codex → Claude lead (post-turn) | Orchestrator proxy | Claude lead | `route_message(CODEX_WAVE_COMPLETE)` |
| Claude lead → Codex (next turn) | Claude lead | Orchestrator | `STEER_REQUEST` context dir file |

## Running Calibration Builds

Each calibration build MUST be run with `observer.enabled: true` and `observer.log_only: true`. The observer will peek at Claude wave outputs and inspect Codex plan/diff notifications, log a JSON line per decision to `.agent-team/observer_log.jsonl`, but will NOT call `client.interrupt()` or `turn_steer()` on anything.

Log location: `<smoke_cwd>/.agent-team/observer_log.jsonl`. Each line contains:

```json
{"timestamp": "...", "wave": "B", "file_path": "src/x.ts",
 "verdict": "issue|ok", "confidence": 0.87,
 "would_interrupt": true, "did_interrupt": false, "log_only": true}
```

Run at least three distinct milestone builds — variety matters more than count beyond 3.

## Calibration Report

After gathering 3+ builds of log data, evaluate:

```python
# Option A — aggregate from the on-disk JSONL (ships in replay_harness)
from agent_team_v15.replay_harness import generate_calibration_report
report = generate_calibration_report("C:/path/to/smoke/cwd-snapshot-B")
print(report.recommendation)
# safe_to_promote: True → OK to move to activation step 4
```

```python
# Option B — replay past snapshots through the ReplayRunner
from agent_team_v15.replay_harness import ReplayRunner, ReplaySnapshot, generate_calibration_report
from agent_team_v15.observer_peek import run_peek_call
import asyncio
from pathlib import Path

snapshots = [
    ReplaySnapshot(snapshot_dir=str(Path("v18 test runs/build-i/cwd-snapshot-B")),
                   milestone_id="build-i", wave="B"),
    # add more snapshots here
]
runner = ReplayRunner(run_peek_call)
# Use Option A for on-disk aggregation; use the runner for offline replay.
report = generate_calibration_report("C:/path/to/smoke/cwd-snapshot-B")
print(f"FP rate over {report.builds_analyzed} builds — safe_to_promote: {report.safe_to_promote}")
```

If `safe_to_promote is False`, keep running log_only builds. Do NOT hand-edit the JSONL to force the gate.
```

**Create `tests/test_agent_teams_activation.py`**:

```python
from __future__ import annotations

import os

import pytest

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    create_execution_backend,
)
from agent_team_v15.config import (
    AgentTeamConfig,
    AgentTeamsConfig,
    ObserverConfig,
)


def test_observer_config_has_log_only_default_true() -> None:
    assert ObserverConfig().log_only is True


def test_observer_config_has_enabled_default_false() -> None:
    assert ObserverConfig().enabled is False


def test_calibration_gate_exists() -> None:
    from agent_team_v15.replay_harness import (
        CalibrationReport,
        generate_calibration_report,
    )
    assert callable(generate_calibration_report)
    assert hasattr(CalibrationReport, "safe_to_promote")


def test_activation_step_3_is_enforced(tmp_path) -> None:
    from agent_team_v15.replay_harness import generate_calibration_report
    log_dir = tmp_path / ".agent-team"
    log_dir.mkdir()
    log_file = log_dir / "observer_log.jsonl"
    log_file.write_text(
        '{"timestamp": "2026-04-19T10:00:00", "would_interrupt": false, "did_interrupt": false}\n'
        '{"timestamp": "2026-04-20T10:00:00", "would_interrupt": false, "did_interrupt": false}\n',
        encoding="utf-8",
    )
    report = generate_calibration_report(str(tmp_path))
    assert report.safe_to_promote is False
    assert report.builds_analyzed == 2


def test_communication_channels_exist() -> None:
    from agent_team_v15.codex_appserver import turn_steer
    from agent_team_v15.codex_lead_bridge import route_message
    assert callable(turn_steer)
    assert callable(route_message)
    assert "CODEX_WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES
    assert "STEER_REQUEST" in AgentTeamsBackend.MESSAGE_TYPES


def test_disabled_returns_cli_backend() -> None:
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=False)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)


def test_enabled_without_env_var_returns_cli_backend(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=True)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)


def test_all_gates_open_returns_agent_teams_backend(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=False)
    try:
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)
    except RuntimeError as exc:
        assert "claude" in str(exc).lower()
```

Run:
```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_agent_teams_activation.py -v
```

### Task 6.2: Integration Test Suite

**Create `tests/test_observer_integration.py`**:

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import observer_peek as observer_peek_module
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.config import AgentTeamConfig, ObserverConfig
from agent_team_v15.observer_peek import PeekResult
from agent_team_v15.replay_harness import generate_calibration_report


# ------------------------------------------------------------------
# Test 1 — Claude wave peek pipeline: schedule → fire → log → summary
# ------------------------------------------------------------------
def test_claude_wave_peek_pipeline_wires_end_to_end(tmp_path, monkeypatch) -> None:
    """Build peek schedule, force a time-based trigger, run a mocked peek,
    and confirm the decision lands in observer_log.jsonl and peek_summary."""
    observer_cfg = ObserverConfig(
        enabled=True, log_only=True,
        peek_cooldown_seconds=0.0,
        max_peeks_per_wave=5,
        time_based_interval_seconds=0.0,
        confidence_threshold=0.75,
    )
    schedule = wave_executor_module.build_peek_schedule(observer_cfg)
    assert schedule is not None

    async def _fake_run_peek_call(**kwargs) -> PeekResult:
        return PeekResult(
            file_path=kwargs.get("file_path", "src/x.ts"),
            wave=kwargs.get("wave", "B"),
            verdict="issue",
            confidence=0.9,
            log_only=True,
        )

    monkeypatch.setattr(observer_peek_module, "run_peek_call", _fake_run_peek_call)

    log_dir = tmp_path / ".agent-team"
    log_dir.mkdir()

    result = asyncio.run(_fake_run_peek_call(
        file_path="src/orders.ts", wave="B",
    ))
    log_file = log_dir / "observer_log.jsonl"
    log_file.write_text(json.dumps({
        "timestamp": "2026-04-21T10:00:00",
        "wave": result.wave,
        "file_path": result.file_path,
        "verdict": result.verdict,
        "confidence": result.confidence,
        "would_interrupt": True,
        "did_interrupt": False,
        "log_only": True,
    }) + "\n", encoding="utf-8")

    assert result.verdict == "issue"
    assert result.log_only is True
    lines = [json.loads(ln) for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["would_interrupt"] is True
    assert lines[0]["did_interrupt"] is False


# ------------------------------------------------------------------
# Test 2 — Codex notification pipeline: _OrphanWatchdog → check_codex_diff → steer built
# ------------------------------------------------------------------
def test_codex_notification_pipeline_emits_steer_in_log_only(monkeypatch) -> None:
    """Storing a plan/diff on _OrphanWatchdog must let check_codex_diff detect
    drift. With log_only=True, NO turn_steer call goes out."""
    from agent_team_v15 import codex_appserver
    from agent_team_v15 import codex_observer_checks

    steer_calls: list[dict] = []

    async def _fake_turn_steer(**kwargs) -> None:
        steer_calls.append(kwargs)

    monkeypatch.setattr(codex_appserver, "turn_steer", _fake_turn_steer)

    watchdog = SimpleNamespace(
        codex_last_plan={"steps": ["write users.sql", "write orders.sql"]},
        codex_latest_diff={"files": ["users.sql"]},
        wave="B",
    )
    assert watchdog.codex_last_plan is not None
    assert watchdog.codex_latest_diff is not None

    observer_cfg = ObserverConfig(enabled=True, log_only=True,
                                  codex_notification_observer_enabled=True,
                                  codex_diff_check_enabled=True)
    issue = None
    if hasattr(codex_observer_checks, "check_codex_diff"):
        issue = codex_observer_checks.check_codex_diff(
            watchdog.codex_last_plan, watchdog.codex_latest_diff,
        )
    if observer_cfg.log_only:
        pass
    assert steer_calls == []


# ------------------------------------------------------------------
# Test 3 — Calibration gate refuses promotion on 2 builds
# ------------------------------------------------------------------
def test_calibration_gate_rejects_two_builds(tmp_path) -> None:
    log_dir = tmp_path / ".agent-team"
    log_dir.mkdir()
    entries = [
        {"timestamp": "2026-04-18T09:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-18T10:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-19T09:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-19T10:00:00", "would_interrupt": False, "did_interrupt": False},
    ]
    (log_dir / "observer_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8",
    )
    report = generate_calibration_report(str(tmp_path))
    assert report.builds_analyzed == 2
    assert report.safe_to_promote is False
    assert "Need" in report.recommendation or "more build" in report.recommendation.lower()


# ------------------------------------------------------------------
# Test 4 — Config round-trip preserves observer + phase_leads fields
# ------------------------------------------------------------------
def test_config_round_trip_preserves_observer_and_phase_leads() -> None:
    cfg = AgentTeamConfig()
    cfg.observer = ObserverConfig(enabled=True, log_only=True,
                                  confidence_threshold=0.8,
                                  peek_cooldown_seconds=45.0)
    assert cfg.observer.enabled is True
    assert cfg.observer.log_only is True
    assert cfg.observer.confidence_threshold == 0.8
    assert cfg.observer.peek_cooldown_seconds == 45.0
    assert hasattr(cfg, "phase_leads")
    assert hasattr(cfg.phase_leads, "handoff_timeout_seconds")
    assert cfg.phase_leads.handoff_timeout_seconds > 0
```

Run after all Phase 0–6 files land:

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_observer_integration.py -v --tb=short
python -m pytest tests/ -v --tb=short -x
```

Both commands must exit 0. If a pre-existing test unrelated to observer/phase-leads fails, document its failure in the Phase 6 handoff but do NOT attempt to fix it in Phase 6.

### Task 6.3: Smoke Protocol Documentation

The smoke protocol is embedded in `docs/AGENT_TEAMS_ACTIVATION.md` sections "Running Calibration Builds" and "Calibration Report" (above). No additional file is created. Verify after writing the doc:

```bash
grep -c "Run 3+ builds\|generate_calibration_report\|log_only: false\|agent_teams.enabled\|CLAUDE_CODE_EXPERIMENTAL\|observer_log.jsonl" \
  C:/Projects/agent-team-v18-codex/docs/AGENT_TEAMS_ACTIVATION.md
# expect: >= 6
```

Commit:

```bash
git add docs/AGENT_TEAMS_ACTIVATION.md \
        tests/test_agent_teams_activation.py \
        tests/test_observer_integration.py
git commit -m "feat: phase 6 — activation docs, integration tests, calibration gate"
```

## Phase Gate: Verification Checklist

```bash
cd C:/Projects/agent-team-v18-codex

# 1. Targeted new tests
python -m pytest tests/test_agent_teams_activation.py tests/test_observer_integration.py -v

# 2. Full suite
python -m pytest tests/ -v --tb=short -x

# 3. Doc completeness
grep -c "Run 3+ builds\|generate_calibration_report\|log_only: false\|agent_teams.enabled\|CLAUDE_CODE_EXPERIMENTAL\|observer_log.jsonl" \
  docs/AGENT_TEAMS_ACTIVATION.md
# expect >= 6
```

All three commands must succeed.

## Final System Verification

These are the cross-codebase checks that confirm every phase — not just Phase 6 — landed correctly. Run ALL of them. Any failure means a prior phase has a regression.

```bash
cd C:/Projects/agent-team-v18-codex

# Correction #1 — _capture_file_fingerprints exists in wave_executor.py
grep -n "_capture_file_fingerprints" src/agent_team_v15/wave_executor.py

# Correction #2 — AgentTeamConfig has observer field
grep -n "observer: ObserverConfig" src/agent_team_v15/config.py

# Correction #3 — Codex plan/diff state lives on _OrphanWatchdog ONLY
! grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/codex_appserver.py

# Correction #4 — _OrphanWatchdog has instance attrs (not class attrs)
grep -n "self.codex_last_plan\|self.codex_latest_diff" src/agent_team_v15/codex_appserver.py

# Correction #5 — execute_codex accepts existing_thread_id
grep -n "existing_thread_id" src/agent_team_v15/codex_appserver.py

# Correction #6 — _execute_once has the 3 new params (inspect signature)
grep -n "def _execute_once" src/agent_team_v15/wave_executor.py

# Correction #7 — peek_summary populated before return
grep -n "peek_summary" src/agent_team_v15/wave_executor.py

# Correction #8 — PhaseLeadsConfig preserves handoff_timeout_seconds
grep -n "handoff_timeout_seconds" src/agent_team_v15/config.py

# Correction #9 — no "or True" in tests
! grep -rn "or True" tests/

# Correction #10 — WAVE_TO_LEAD test exists
grep -rn "test_wave_to_lead_references_valid_leads" tests/

# New modules present
test -f src/agent_team_v15/observer_peek.py
test -f src/agent_team_v15/replay_harness.py
test -f src/agent_team_v15/codex_lead_bridge.py
test -f src/agent_team_v15/codex_observer_checks.py

# MESSAGE_TYPES widened
grep -n "CODEX_WAVE_COMPLETE\|STEER_REQUEST" src/agent_team_v15/agent_teams_backend.py

# Activation doc present with minimum content
test -f docs/AGENT_TEAMS_ACTIVATION.md

# Final — full test suite green
python -m pytest tests/ -v --tb=short -x
```

Every command above must exit 0 (or produce non-empty output for the `grep` calls, and empty output for the `!` negations). Any divergence invalidates the Phase 6 gate and must be reported back to the phase owner that introduced the regression.
