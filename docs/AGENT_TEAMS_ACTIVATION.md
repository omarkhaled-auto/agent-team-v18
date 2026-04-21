# Agent Teams + Dynamic Observer Activation Guide

This document is the single source of truth for safely enabling the observer
and the agent_teams backend in a live smoke build. Do NOT flip `log_only: false`
or `agent_teams.enabled: true` without completing every step below.

## Activation Checklist

Follow in order. Do not skip steps.

1. **All Phase 0-5 tests pass.**
   ```bash
   cd C:/Projects/agent-team-v18-codex
   python -m pytest tests/ -v --tb=short
   ```

2. **Run 3+ builds in `log_only: true` observer mode.** See "Running
   Calibration Builds" below. Each build writes to
   `.agent-team/observer_log.jsonl`.

3. **Run `generate_calibration_report()`. It must return
   `safe_to_promote: True` with FP rate below 10%.** See "Calibration Report"
   below.

4. **Set `observer.log_only: false` in your smoke config.** Only after step 3
   clears.

5. **Set `agent_teams.enabled: true` in your smoke config.** This flips the
   execution backend to the agent_teams path.

6. **Export `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.** Without this
   environment variable the backend falls back to the CLI path even when
   `enabled: true`.

7. **Run a single M1 smoke with both flags enabled.** Watch the console for
   `[Observer]` lines and review `peek_summary` in WaveResult output.

8. **Review `observer_log.jsonl` for steer/interrupt quality.** If any
   interrupt fired on a healthy wave, revert step 4 and gather more log_only
   builds.

## Minimum Config Additions

Add to the smoke config under the top-level config keys:

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
| Lead to lead | Claude lead | Claude lead | `AgentTeamsBackend.route_message()` context dir files |
| Orchestrator to Claude | Orchestrator | Running session | `client.interrupt()` |
| Orchestrator to Codex, minor steer | Orchestrator | Running turn | `turn/steer` |
| Orchestrator to Codex, major pivot | Orchestrator | Running turn | `turn/interrupt` plus new `turn/start` |
| Codex to orchestrator, real time | Codex process | Orchestrator | `turn/plan/updated` plus `turn/diff/updated` |
| Codex to Claude lead, post-turn | Orchestrator proxy | Claude lead | `CODEX_WAVE_COMPLETE` context message |
| Claude lead to Codex, next turn | Claude lead | Orchestrator | `STEER_REQUEST` context message |

## Running Calibration Builds

Each calibration build MUST be run with `observer.enabled: true` and
`observer.log_only: true`. The observer peeks at Claude wave outputs and
inspects Codex plan/diff notifications, logs a JSON line per decision to
`.agent-team/observer_log.jsonl`, but will NOT call `client.interrupt()` or
`turn_steer()` on anything.

Log location: `<smoke_cwd>/.agent-team/observer_log.jsonl`. Every line written
by either `observer_peek._write_observer_log` or
`codex_appserver._write_codex_observer_log` conforms to this schema.

```json
{"timestamp": "2026-04-21T10:15:30Z", "run_id": "smoke-m1-20260421",
 "wave": "B", "file": "apps/api/prisma/schema.prisma",
 "verdict": "issue", "confidence": 0.87,
 "message": "missing relation mapping for the milestone schema",
 "source": "file_poll", "log_only": true,
 "would_interrupt": true, "did_interrupt": false}
```

Run at least three distinct milestone builds. Variety matters more than count
beyond 3.

## Calibration Report

After gathering 3+ builds of log data, evaluate:

```python
from agent_team_v15.replay_harness import generate_calibration_report

report = generate_calibration_report("C:/path/to/smoke/cwd-snapshot-B")
print(report.recommendation)
# safe_to_promote: True means OK to move to activation step 4
```

For offline replay against preserved snapshots, use `ReplayRunner` with an
injected peek callable:

```python
import asyncio
from pathlib import Path

from agent_team_v15.observer_peek import run_peek_call
from agent_team_v15.replay_harness import (
    ReplayRunner,
    ReplaySnapshot,
    generate_calibration_report,
)

snapshots = [
    ReplaySnapshot(
        snapshot_dir=Path("v18 test runs/build-i/cwd-snapshot-B"),
        build_id="build-i",
        wave_letter="B",
    ),
]
runner = ReplayRunner(run_peek_call)
report = asyncio.run(generate_calibration_report(runner, snapshots))
print(
    f"FP rate over {report.builds_analyzed} builds; "
    f"safe_to_promote: {report.safe_to_promote}"
)
```

If `safe_to_promote is False`, keep running log_only builds. Do NOT hand-edit
the JSONL to force the gate.
