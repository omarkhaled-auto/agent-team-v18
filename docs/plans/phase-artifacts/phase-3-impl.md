# Phase 3 — Peek Infrastructure: Implementation Brief

## Phase Context

**Phase:** 3 — Peek Infrastructure (config, dataclasses, per-agent observer strategy).
**Depends on:** Phase 0 (`CodexNotificationEvent`, `turn_steer`), Phase 1 (`PHASE_LEAD_NAMES`, `codex_lead_bridge`).
**Enables:** Phase 4 (peek integration needs `PeekSchedule`, `PeekResult`, `ObserverConfig`, `build_peek_schedule`, `run_peek_call`).

Phase 3 is a **pure structural phase** — it introduces types, one new module, and a new config field. It does not wire anything into the execution path; Phase 4 will consume these symbols. Every symbol must land with its canonical name because Phase 4's wiring imports them by name.

The core design: **Claude waves use Anthropic Haiku file-poll peeks (`observer_peek.py`); Codex waves use `turn/plan/updated` + `turn/diff/updated` notification events** (handled in `codex_appserver.py` during Phase 4). `PeekSchedule.uses_notifications` and the `_CODEX_WAVES` constant encode the strategy split.

---

## Pre-Flight: Files to Read

Read every file below BEFORE touching code. Do not skim.

| # | File / Range | Purpose |
|---|---|---|
| 1 | `src/agent_team_v15/config.py` lines 625–665 | Structural template — `AgentTeamsConfig` (line 636) is the canonical flat dataclass pattern to mirror for `ObserverConfig`. Note: all fields flat, `enabled: bool = False` first, `field(default_factory=...)` for mutable defaults. |
| 2 | `src/agent_team_v15/config.py` lines 1200–1275 | `AgentTeamConfig` at **line 1210** (Correction #2). Verify the declaration style for existing sub-configs (`agent_teams: AgentTeamsConfig = field(default_factory=AgentTeamsConfig)` at line 1255). Insert `observer: ObserverConfig = field(default_factory=ObserverConfig)` in the same block. |
| 3 | `src/agent_team_v15/wave_executor.py` lines 48–135 | `WaveFinding` (line 52), `WaveResult` (line 68). Confirms the dataclass style used in this file: `@dataclass` decorator, `field(default_factory=list)` for list defaults, type hints on every field, docstring in triple quotes. There is **no** existing `_CODEX_WAVES` constant — this phase introduces it. |
| 4 | `src/agent_team_v15/wave_executor.py` lines 165–210 | `_WaveWatchdogState` dataclass. Pattern for `field(default_factory=lambda: datetime.now(timezone.utc).isoformat())` — reuse for `PeekResult.timestamp`. |
| 5 | `src/agent_team_v15/wave_executor.py` lines 2485–2540 | `_capture_file_fingerprints()` at **line 2499** (Correction #1). Returns `dict[str, tuple[int, int]]` (rel-path → `(mtime_ns, size)`). Phase 4 will consume it; not modified in Phase 3. |
| 6 | `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` lines 1023–1510 | Phase 3 spec. Contains the exact field sets for `ObserverConfig`, `PeekResult`, `PeekSchedule`, and the full `observer_peek.py` source. **These field names are load-bearing for Phase 4 — do not rename them.** |
| 7 | `src/agent_team_v15/observer_peek.py` | Verify this file **does not exist** before Task 3.3: `ls src/agent_team_v15/observer_peek.py` must return "No such file". If it exists, stop and escalate — Phase 3 creates this file. |

---

## Pre-Flight: Context7 Research

Verification completed during artifact preparation:

1. **Anthropic SDK library id:** `/anthropics/anthropic-sdk-python` (High reputation, benchmark 78.49).
2. **`AsyncAnthropic().messages.create()` signature:** Accepts `model=`, `max_tokens=`, `system=` (top-level, NOT inside messages), and `messages=[{"role": "user", "content": "..."}]`. Auth via `ANTHROPIC_API_KEY` env var by default. Confirmed response shape: `response.content[0].text`.
3. **Model id `claude-haiku-4-5-20251001`:** Used as-is per the plan. The assistant's knowledge cutoff includes this model; do not substitute.
4. **`dataclasses.field(default_factory=list)`:** Correct Python 3.10+ usage. Already used extensively in this codebase (e.g. `wave_executor.py` line 75, 97, 169, 181). Do not use mutable literal defaults (`= []`).
5. **JSONL writing:** `with path.open("a", encoding="utf-8") as f: f.write(json.dumps(entry) + "\n")`. Used verbatim in the plan's `_write_observer_log`.

Implementing agent does not need to re-run context7 unless it hits an SDK behaviour that conflicts with this brief.

---

## Pre-Flight: Sequential Thinking

A two-thought sequential analysis was run during artifact preparation to decide between **flat** vs **nested** `ObserverConfig`. Conclusion:

**Use the plan's flat field set.** Rationale:
- `AgentTeamsConfig` (config.py line 636) is the precedent — all flat, no sub-dataclasses.
- Phase 4 will consume `observer_config.model`, `observer_config.confidence_threshold`, `observer_config.codex_notification_observer_enabled` by flat attribute access; a nested design would force a breaking rename downstream.
- The team-lead dispatch brief listed an alternate flat field set (`peek_model`, `codex_notification_enabled`, `claude_file_poll_enabled`). That naming is **superseded** by the plan's canonical names because Phase 4's wiring already references the plan names. The Rule #5 precedence (`Corrections list takes precedence`) resolves this cleanly in favor of the plan. See "Corrections Applied" below for the explicit rename map.

---

## Corrections Applied (Phase 3)

| # | Correction | Source of truth |
|---|---|---|
| **#2** | `AgentTeamConfig` is at **line 1210**, not 1193. Phase 3 adds `observer: ObserverConfig = field(default_factory=ObserverConfig)` to this class (adjacent to the `agent_teams`, `phase_leads` fields at lines 1255–1256). | `config.py:1210` confirmed by direct read. |

Non-applicable corrections for Phase 3 (documented for cross-phase consistency — **do not act on them here**):
- #1 `_capture_file_fingerprints` at line 2499 — consumed by Phase 4.
- #3/#4 Codex notification fields on `_OrphanWatchdog` — Phase 4 territory.
- #5 `execute_codex(existing_thread_id=...)` — Phase 5.
- #6 `_execute_once` new params — Phase 4.
- #7 `peek_summary` population — Phase 4.
- #8 `PhaseLeadsConfig` preservation — Phase 1/2.
- #9/#10 Test bugs — covered in Phase 5/6 test tasks.

### Naming precedence resolution (team-lead dispatch vs plan)

The dispatch brief listed minimum-field names. The plan's canonical names take precedence. Equivalence map:

| Team-lead name | Plan canonical name | Action |
|---|---|---|
| `peek_model` | `model` | Use `model`. |
| `codex_notification_enabled` | `codex_notification_observer_enabled` | Use the plan name. |
| `claude_file_poll_enabled` | *(no direct equivalent)* | **Not added.** File-poll is the implicit strategy when `PeekSchedule.uses_notifications is False`; no independent flag needed. The plan omits it. |
| `context7_fallback_to_training` | `context7_fallback_to_training` | Same name — add. |
| `time_based_interval_seconds` | `time_based_interval_seconds` (type: `float`) | Same name — add as **`float = 300.0`** (plan line 1081). |
| `max_peeks_per_wave` | `max_peeks_per_wave` | Same name — add. |
| `enabled`, `log_only` | `enabled`, `log_only` | Same names — add. |

---

## CRITICAL ANTI-PATTERN

> **`observer_peek.py` handles CLAUDE waves ONLY. DO NOT add any Codex notification polling, `turn/plan/updated`, `turn/diff/updated`, `turn_steer`, or `CodexNotificationEvent` imports to this module.** Codex notification handling lives in `codex_appserver.py` and is wired in Phase 4 on `_OrphanWatchdog` (Correction #3). Mixing the two strategies into `observer_peek.py` is an architecture violation that will break Phase 4 wiring and blur the dual-strategy boundary.
>
> Verification after Task 3.3: `grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver" src/agent_team_v15/observer_peek.py` **must return empty output.** If it returns anything, revert and redo.

Additional anti-patterns:
- Do **not** change `log_only`'s default to `False`. Safe default is `True`. The observer never interrupts accidentally.
- Do **not** raise exceptions out of `run_peek_call`. Fail-open: return a `PeekResult(verdict="ok", confidence=0.0, message="peek failed: <e>")` on any error, and keep the wave alive.
- Do **not** skip `_write_observer_log` on exceptions — wrap it in its own try/except that only logs at WARNING level.
- Do **not** add `pass`, `...`, or `# TODO` stubs. Every function has a complete implementation.

---

## Task-by-Task Implementation

### Task 3.1 — Add `ObserverConfig` to `config.py` and field to `AgentTeamConfig`

**Files:**
- Modify: `src/agent_team_v15/config.py`
- Create: `tests/test_observer_config.py`

**Step 1: Write the failing test.**

Create `tests/test_observer_config.py`:

```python
from agent_team_v15.config import ObserverConfig, AgentTeamConfig


def test_observer_config_defaults():
    cfg = ObserverConfig()
    assert cfg.enabled is False
    assert cfg.log_only is True  # SAFE DEFAULT — never interrupts without explicit opt-in
    assert cfg.confidence_threshold == 0.75
    assert cfg.model == "claude-haiku-4-5-20251001"
    assert cfg.max_tokens == 512
    assert cfg.codex_notification_observer_enabled is True


def test_observer_config_in_parent():
    cfg = AgentTeamConfig()
    assert hasattr(cfg, "observer")
    assert isinstance(cfg.observer, ObserverConfig)


def test_observer_config_context7_fallback_default():
    cfg = ObserverConfig()
    assert cfg.context7_enabled is True
    assert cfg.context7_fallback_to_training is True
    assert cfg.time_based_interval_seconds == 300.0
    assert cfg.max_peeks_per_wave == 5
    assert cfg.peek_cooldown_seconds == 60.0
```

Run it — it must fail (ObserverConfig does not exist yet):
```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_observer_config.py -v
```

**Step 2: Add `ObserverConfig` to `config.py`.**

Insert the following dataclass **immediately before** the existing `@dataclass class AgentTeamsConfig:` block (currently at line 635–636). The new block should land around line 635 pre-insert, pushing `AgentTeamsConfig` downward:

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
      turn/diff/updated events directly, no additional API calls needed.
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

**Step 3: Add the `observer` field to `AgentTeamConfig` (line 1210 block).**

Inside `class AgentTeamConfig:` (declaration at line 1210), add a new line in the same block where `agent_teams`, `phase_leads`, `contract_engine` are declared (current lines 1255–1266). Place it immediately **after** `phase_leads: PhaseLeadsConfig = field(default_factory=PhaseLeadsConfig)` (currently line 1256):

```python
    observer: ObserverConfig = field(default_factory=ObserverConfig)
```

Exact target insertion point (post-edit), shown in context:

```python
    agent_teams: AgentTeamsConfig = field(default_factory=AgentTeamsConfig)
    phase_leads: PhaseLeadsConfig = field(default_factory=PhaseLeadsConfig)
    observer: ObserverConfig = field(default_factory=ObserverConfig)  # NEW
    contract_engine: ContractEngineConfig = field(default_factory=ContractEngineConfig)
```

**Step 4: Run the tests — expect 3 passed.**

```bash
python -m pytest tests/test_observer_config.py -v
```

**Step 5: Commit.**

```bash
git add src/agent_team_v15/config.py tests/test_observer_config.py
git commit -m "feat: add ObserverConfig with dual-strategy support (file-poll for Claude, notifications for Codex)"
```

---

### Task 3.2 — Add `PeekResult`, `PeekSchedule`, `_CODEX_WAVES`, `build_peek_schedule` to `wave_executor.py`

**Files:**
- Modify: `src/agent_team_v15/wave_executor.py`
- Create: `tests/test_peek_dataclasses.py`

**Step 1: Write the failing test.**

Create `tests/test_peek_dataclasses.py`:

```python
from agent_team_v15.wave_executor import (
    PeekResult,
    PeekSchedule,
    _CODEX_WAVES,
    build_peek_schedule,
)


def test_peek_result_no_interrupt_in_log_only():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=True)
    assert r.should_interrupt is False


def test_peek_result_interrupt_when_live_and_confident():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=False)
    assert r.should_interrupt is True


def test_peek_schedule_wave_type():
    """PeekSchedule knows whether to use file-poll or notification strategy."""
    claude_schedule = PeekSchedule(wave="A", trigger_files=[])
    codex_schedule = PeekSchedule(wave="B", trigger_files=[])
    assert claude_schedule.uses_notifications is False
    assert codex_schedule.uses_notifications is True


def test_build_peek_schedule_parses_requirements():
    req = "## Deliverables\n- [ ] apps/api/prisma/schema.prisma\n- [ ] apps/api/src/main.ts\n"
    schedule = build_peek_schedule(requirements_text=req, wave="A")
    assert "apps/api/prisma/schema.prisma" in schedule.trigger_files
    assert "apps/api/src/main.ts" in schedule.trigger_files
    assert schedule.wave == "A"


def test_codex_waves_constant_includes_b_and_d():
    assert "B" in _CODEX_WAVES
    assert "D" in _CODEX_WAVES
    assert "A5" in _CODEX_WAVES
    assert "T5" in _CODEX_WAVES
    # Claude waves must NOT be in this set
    assert "A" not in _CODEX_WAVES
    assert "D5" not in _CODEX_WAVES
    assert "T" not in _CODEX_WAVES
    assert "E" not in _CODEX_WAVES


def test_peek_schedule_uses_notifications_is_case_insensitive():
    # wave letter may arrive lowercase from some callers
    schedule = PeekSchedule(wave="b", trigger_files=[])
    assert schedule.uses_notifications is True
```

Run — expect failures (symbols don't exist yet):
```bash
python -m pytest tests/test_peek_dataclasses.py -v
```

**Step 2: Insert the new dataclasses into `wave_executor.py`.**

Locate the end of the `WaveFinding` dataclass (currently lines 52–65) and the start of the `WaveResult` dataclass (line 68). Insert the following block after the last intermediate dataclass `_DeterministicGuardResult` (~line 170), immediately before `_WaveWatchdogState` (line 173). Between `WaveCheckpoint` (line ~136) and `_WaveWatchdogState` (line 173) there are three intermediate classes — `CheckpointDiff`, `CompileCheckResult`, `_DeterministicGuardResult` — insert AFTER all of them. Rationale: Phase-3 adds purely structural types that sit alongside the existing result/checkpoint dataclasses; the watchdog family follows.

Insertion block (exact):

```python
# Waves that use Codex app-server — notification-based observation, no file-poll
_CODEX_WAVES: frozenset[str] = frozenset({"A5", "B", "D", "T5"})


@dataclass
class PeekResult:
    """Verdict from one observer check (file-poll for Claude, diff/plan for Codex).

    source values:
        "file_poll"  — Claude waves, file written → observer_peek.run_peek_call
        "plan_event" — Codex waves, turn/plan/updated notification
        "diff_event" — Codex waves, turn/diff/updated notification
    """
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
    """Parse a requirements markdown block into a PeekSchedule with trigger files.

    Extracts file paths from lines like ``- [ ] apps/api/prisma/schema.prisma``.
    Duplicates are removed while preserving first-seen order.
    """
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

**Import verification:** `datetime` and `timezone` are already imported at the top of `wave_executor.py` (used by `_WaveWatchdogState` line 175). No new imports required for this block. `field` and `dataclass` are likewise already imported.

**Step 3: Run tests — expect 6 passed.**

```bash
python -m pytest tests/test_peek_dataclasses.py -v
```

**Step 4: Commit.**

```bash
git add src/agent_team_v15/wave_executor.py tests/test_peek_dataclasses.py
git commit -m "feat: add PeekResult, PeekSchedule, _CODEX_WAVES, build_peek_schedule with Codex notification strategy flag"
```

---

### Task 3.3 — Create `observer_peek.py` (Claude-wave file-poll strategy)

**Files:**
- Create: `src/agent_team_v15/observer_peek.py`
- Create: `tests/test_observer_peek.py`

**BEFORE STARTING:** confirm the file does not yet exist:
```bash
ls src/agent_team_v15/observer_peek.py
# expected: "No such file or directory"
```

**Step 1: Write the failing test.**

Create `tests/test_observer_peek.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agent_team_v15.observer_peek import (
    run_peek_call,
    build_peek_prompt,
    build_corrective_interrupt_prompt,
    build_codex_steer_prompt,
)
from agent_team_v15.wave_executor import PeekSchedule, PeekResult


def test_build_peek_prompt_contains_file_path():
    schedule = PeekSchedule(
        wave="A",
        trigger_files=["apps/api/prisma/schema.prisma"],
        requirements_text="- [ ] apps/api/prisma/schema.prisma\n",
    )
    prompt = build_peek_prompt(
        file_path="apps/api/prisma/schema.prisma",
        file_content="model User { id String @id }",
        schedule=schedule,
        framework_pattern="",
    )
    assert "apps/api/prisma/schema.prisma" in prompt
    assert "verdict" in prompt.lower()


@pytest.mark.asyncio
async def test_run_peek_call_returns_peek_result(tmp_path):
    prisma_dir = tmp_path / "apps" / "api" / "prisma"
    prisma_dir.mkdir(parents=True)
    (prisma_dir / "schema.prisma").write_text("model User { id String @id }")

    schedule = PeekSchedule(
        wave="A",
        trigger_files=["apps/api/prisma/schema.prisma"],
        requirements_text="- [ ] apps/api/prisma/schema.prisma\n",
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"verdict":"ok","confidence":0.95,"message":"looks good"}')]

    with patch("agent_team_v15.observer_peek._call_anthropic_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        result = await run_peek_call(
            cwd=str(tmp_path),
            file_path="apps/api/prisma/schema.prisma",
            schedule=schedule,
            log_only=True,
            model="claude-haiku-4-5-20251001",
            confidence_threshold=0.75,
        )

    assert isinstance(result, PeekResult)
    assert result.verdict == "ok"
    assert result.should_interrupt is False  # log_only=True
    assert result.source == "file_poll"

    log_path = tmp_path / ".agent-team" / "observer_log.jsonl"
    assert log_path.exists()


@pytest.mark.asyncio
async def test_run_peek_call_fails_open_on_api_exception(tmp_path):
    (tmp_path / "x.py").write_text("print('hi')")
    schedule = PeekSchedule(wave="A", trigger_files=["x.py"], requirements_text="- [ ] x.py\n")

    with patch("agent_team_v15.observer_peek._call_anthropic_api", new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = RuntimeError("boom")
        # Must NOT raise — fail-open contract.
        result = await run_peek_call(
            cwd=str(tmp_path),
            file_path="x.py",
            schedule=schedule,
            log_only=True,
            model="claude-haiku-4-5-20251001",
            confidence_threshold=0.75,
        )

    assert isinstance(result, PeekResult)
    assert result.verdict == "ok"
    assert result.should_interrupt is False


def test_build_corrective_interrupt_prompt_is_specific():
    result = PeekResult(
        file_path="apps/api/prisma/schema.prisma",
        wave="A",
        verdict="issue",
        confidence=0.88,
        message="File is an empty stub — no model definitions found",
        log_only=False,
    )
    prompt = build_corrective_interrupt_prompt(result)
    assert "schema.prisma" in prompt
    assert "empty stub" in prompt
    assert "Wave A" in prompt
    assert "OBSERVER" in prompt


def test_build_codex_steer_prompt_names_file_and_reason():
    result = PeekResult(
        file_path="apps/api/src/main.ts",
        wave="B",
        verdict="issue",
        confidence=0.9,
        message="missing NestJS bootstrap",
        log_only=False,
        source="diff_event",
    )
    prompt = build_codex_steer_prompt(result)
    assert "main.ts" in prompt
    assert "missing NestJS bootstrap" in prompt
    assert "Observer" in prompt or "observer" in prompt
```

**Step 2: Create `src/agent_team_v15/observer_peek.py` with the full module.**

This is the complete file — write it verbatim. **No `# TODO`, no `pass`, no `...` stubs.**

```python
"""Focused single-turn peek call for Claude wave observation.

Codex waves do NOT use this module — they observe via turn/plan/updated
and turn/diff/updated notification events in codex_appserver.py (wired in Phase 4).

This module is for Claude waves (A, D5, T, E) only.

Contract:
- run_peek_call is fail-open: any exception returns a safe PeekResult(verdict="ok").
- Every call writes a JSONL entry to .agent-team/observer_log.jsonl (best-effort).
- log_only=True (default from ObserverConfig) disables should_interrupt.
"""
from __future__ import annotations

import json
import logging
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


def build_peek_prompt(
    file_path: str,
    file_content: str,
    schedule: PeekSchedule,
    framework_pattern: str,
) -> str:
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
        "## File content (first 600 chars):",
        "```",
        file_content[:600],
        "```",
        "",
        'Respond with JSON only: {"verdict": ..., "confidence": ..., "message": ...}',
    ]
    return "\n".join(lines)


def build_corrective_interrupt_prompt(result: PeekResult) -> str:
    """Specific, actionable corrective message for client.interrupt() on Claude waves."""
    return (
        f"[OBSERVER interrupt — confidence={result.confidence:.0%}]\n"
        f"Wave {result.wave} — file `{result.file_path}` was just written but has an issue:\n\n"
        f"  {result.message}\n\n"
        f"Please fix `{result.file_path}` before continuing. "
        f"If this assessment is incorrect, reply briefly and continue."
    )


def build_codex_steer_prompt(result: PeekResult) -> str:
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
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def _load_file_content(cwd: str, file_path: str) -> str:
    try:
        return (Path(cwd) / file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _fetch_context7_pattern(file_path: str) -> str:
    """Best-effort Context7 pattern hint. Returns empty string on any failure.

    Context7 is MCP-only; in production this is a no-op. Present so that future
    replay harnesses can inject patterns without API changes.
    """
    _hints = {
        "schema.prisma": "prisma schema model definition",
        "Dockerfile": "node alpine multi-stage dockerfile",
        "docker-compose": "docker compose service healthcheck",
        "tsconfig": "typescript compiler options",
        "next.config": "next.js configuration",
        "nest-cli.json": "nestjs cli configuration",
    }
    del _hints  # reserved for future replay harness injection
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

    Always writes to observer_log.jsonl. Fail-open: any exception below yields
    a safe PeekResult(verdict="ok", should_interrupt=False) so the wave proceeds.
    Only sets should_interrupt=True when log_only=False AND confidence >= threshold.
    """
    try:
        file_content = _load_file_content(cwd, file_path)
        if not file_content.strip():
            result = PeekResult(
                file_path=file_path,
                wave=schedule.wave,
                verdict="skip",
                confidence=1.0,
                message="file is empty — skipping peek",
                log_only=log_only,
                source="file_poll",
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

        confidence = float(parsed["confidence"])
        verdict = str(parsed["verdict"])
        if verdict == "issue" and confidence < confidence_threshold:
            verdict = "ok"

        result = PeekResult(
            file_path=file_path,
            wave=schedule.wave,
            verdict=verdict,
            confidence=confidence,
            message=str(parsed["message"]),
            raw_response=raw_text,
            log_only=log_only,
            source="file_poll",
        )
        _write_observer_log(cwd, result)
        return result
    except Exception as e:
        logger.warning("observer: run_peek_call top-level failure for %s: %s", file_path, e)
        safe_result = PeekResult(
            file_path=file_path,
            wave=schedule.wave,
            verdict="ok",
            confidence=0.0,
            message=f"peek infrastructure failure: {e}",
            log_only=log_only,
            source="file_poll",
        )
        # Best-effort log write; never raises out of run_peek_call.
        _write_observer_log(cwd, safe_result)
        return safe_result
```

**Why a second outer try/except?** Phase 4 calls `run_peek_call` from the wave execution loop. Any propagated exception would break the wave. The inner try/except already covers the API call; the outer one covers the remaining surface (file read, prompt build, context7 lookup, log write, etc.) per Correction-style fail-open discipline.

**Note:** `run_peek_call` here adds an outer `try/except Exception` wrapping the entire function body. The original plan's version has only an inner try/except. The outer wrapper is intentional and correct — without it, unexpected errors in the log writer or argument preparation could surface. This artifact's spec supersedes the plan's version for this function.

**Step 3: Run tests — expect 5 passed.** (Note: plan specifies 3 baseline tests; this artifact adds 2 additional tests — `test_run_peek_call_fails_open_on_api_exception` and `test_build_codex_steer_prompt_names_file_and_reason` — for a total of 5. The expanded set is authoritative.)

```bash
python -m pytest tests/test_observer_peek.py -v
```

**Step 4: Run the anti-pattern verification.**

```bash
grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver" src/agent_team_v15/observer_peek.py
# MUST return empty (exit code 1). If any line prints, revert and redo.
```

**Step 5: Commit.**

```bash
git add src/agent_team_v15/observer_peek.py tests/test_observer_peek.py
git commit -m "feat: observer_peek.py — file-poll peek for Claude waves with log_only safety gate"
```

---

## Phase Gate: Verification Checklist

All commands below are executed from the repo root (`C:/Projects/agent-team-v18-codex`).

**1. Full Phase 3 test suite — all three test files must pass.**

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_observer_config.py tests/test_peek_dataclasses.py tests/test_observer_peek.py -v
```

**2. Defaults sanity check.**

```bash
python -c "from agent_team_v15.config import ObserverConfig; c = ObserverConfig(); assert c.log_only is True; assert c.enabled is False; assert c.model == 'claude-haiku-4-5-20251001'; print('defaults correct')"
```

**3. Strategy split sanity check.**

```bash
python -c "from agent_team_v15.wave_executor import _CODEX_WAVES, build_peek_schedule; from agent_team_v15.config import ObserverConfig; s = build_peek_schedule('', 'B'); assert s.uses_notifications is True; s2 = build_peek_schedule('', 'A'); assert s2.uses_notifications is False; assert 'B' in _CODEX_WAVES and 'A' not in _CODEX_WAVES; print('strategy split correct')"
```

**4. Anti-pattern verification — observer_peek.py has NO Codex notification code.**

```bash
grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver" src/agent_team_v15/observer_peek.py
# EXIT CODE must be 1 (no matches). If it prints lines, revert.
```

**5. AgentTeamConfig wiring.**

```bash
python -c "from agent_team_v15.config import AgentTeamConfig, ObserverConfig; c = AgentTeamConfig(); assert isinstance(c.observer, ObserverConfig); assert c.observer.log_only is True; print('observer wired into AgentTeamConfig')"
```

**6. Static import sanity — no circular imports.**

```bash
python -c "from agent_team_v15 import observer_peek, wave_executor, config; print('imports clean')"
```

All six must succeed. Only then is Phase 3 complete.

---

## Handoff State

Phase 4 can rely on the following contract:

- `agent_team_v15.config.ObserverConfig` exists as a `@dataclass` with these fields, defaults verified:
  - `enabled: bool = False`
  - `log_only: bool = True`
  - `confidence_threshold: float = 0.75`
  - `context7_enabled: bool = True`
  - `context7_fallback_to_training: bool = True`
  - `model: str = "claude-haiku-4-5-20251001"`
  - `max_tokens: int = 512`
  - `peek_cooldown_seconds: float = 60.0`
  - `max_peeks_per_wave: int = 5`
  - `time_based_interval_seconds: float = 300.0`
  - `codex_notification_observer_enabled: bool = True`
  - `codex_plan_check_enabled: bool = True`
  - `codex_diff_check_enabled: bool = True`
- `AgentTeamConfig.observer: ObserverConfig` field is present (config.py line ~1257 after insert) with factory default.
- `agent_team_v15.wave_executor._CODEX_WAVES: frozenset[str] == frozenset({"A5", "B", "D", "T5"})`.
- `agent_team_v15.wave_executor.PeekResult` dataclass exists with fields `file_path`, `wave`, `verdict`, `confidence`, `message`, `raw_response`, `log_only`, `source`, `timestamp`, and properties `should_interrupt`, `should_steer`.
- `agent_team_v15.wave_executor.PeekSchedule` dataclass exists with fields `wave`, `trigger_files`, `milestone_id`, `requirements_text`, and property `uses_notifications`.
- `agent_team_v15.wave_executor.build_peek_schedule(requirements_text, wave, milestone_id="")` returns a `PeekSchedule` with trigger files extracted from markdown checkboxes.
- `agent_team_v15.observer_peek.run_peek_call(cwd, file_path, schedule, log_only, model, confidence_threshold, max_tokens=512)` is an async fail-open function that returns a `PeekResult` and writes `.agent-team/observer_log.jsonl`.
- `agent_team_v15.observer_peek.build_peek_prompt`, `build_corrective_interrupt_prompt`, `build_codex_steer_prompt` are importable helpers.
- `src/agent_team_v15/observer_peek.py` contains **zero** Codex notification code. Grep check is part of the phase gate.

**Not yet wired (Phase 4 work):**
- `_execute_once` new params (`observer_config`, `requirements_text`, `wave_letter`).
- `_OrphanWatchdog.codex_last_plan` / `codex_latest_diff` attrs (Correction #3/#4).
- `peek_summary` on `WaveResult` (Correction #7).
- Actual invocation of `run_peek_call` from the wave polling loop.
