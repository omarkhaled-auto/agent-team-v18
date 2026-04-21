# Phase 1 — Phase Lead System: Implementation Brief

## Phase Context

Phase 1 aligns `AgentTeamsBackend` phase leads to the actual wave roster. The current `PHASE_LEAD_NAMES` list (`planning-lead`, `architecture-lead`, `coding-lead`, `review-lead`, `testing-lead`, `audit-lead`) is a legacy generic taxonomy. It no longer matches the dispatch waves (A, A5, B, C, D, D5, T, T5, E). Phase 1 replaces the four active Claude waves' leads with wave-aligned names, adds two cross-protocol message types, and ships a new `codex_lead_bridge.py` module that lets Codex wave completions flow into Claude leads and steer requests flow back.

- **Depends on:** Phase 0 (execute_codex accepts existing_thread_id) — not directly consumed by Phase 1 code, but the sequencing guarantees Codex thread persistence exists before the bridge is integrated in Phase 4.
- **Enables:** Phase 4 — the watchdog integration layer calls `codex_lead_bridge.route_codex_wave_complete()` after each Codex turn/completed and `codex_lead_bridge.read_pending_steer_requests()` before the next turn/start.

Wave roster (only Claude persistent sessions get a phase lead):

| Wave | Agent | Lead |
|------|-------|------|
| A | Claude | wave-a-lead |
| D5 | Claude | wave-d5-lead |
| T | Claude | wave-t-lead |
| E | Claude | wave-e-lead |

Codex waves (A5, B, D, T5) do **not** get a Claude phase lead of their own; they reuse one of the four Claude leads as their reviewer via `WAVE_TO_LEAD`.

## Pre-Flight: Files to Read

Read every file below before writing any code.

| Path | Lines | Why |
|------|-------|-----|
| `src/agent_team_v15/agent_teams_backend.py` | 288–311 | Exact current `PHASE_LEAD_NAMES` and `MESSAGE_TYPES` values. |
| `src/agent_team_v15/agent_teams_backend.py` | 689–704 | Current `_get_phase_lead_config()` mapping shape. |
| `src/agent_team_v15/agent_teams_backend.py` | 856–920 | `route_message()` context-dir file-writing pattern (canonical for bridge writes). |
| `src/agent_team_v15/config.py` | 545–585 | `PhaseLeadConfig` fields and `PhaseLeadsConfig` fields. Note `handoff_timeout_seconds` (line 583) and `allow_parallel_phases` (line 584) — **preserve both (correction #8)**. |
| `src/agent_team_v15/config.py` | 1210–1267 | `AgentTeamConfig` root (line 1210 — correction #2). Confirms `phase_leads: PhaseLeadsConfig` is attached at line 1256. |
| `src/agent_team_v15/agents.py` | 5420–5435 | Existing callers that reference the old field names — must be migrated alongside the rename, or they will raise `AttributeError` at runtime. |
| `src/agent_team_v15/cli.py` | 2855–2865 | Existing `audit_lead.enabled` caller — must be migrated if `audit_lead` field is removed. |
| `tests/test_phase_lead_integration.py` | full | Existing tests that use old field names — must be migrated. |
| `tests/test_isolated_to_team_pipeline.py` | 50–120, 300–325 | Existing tests that use `audit_lead.enabled` — must be migrated. |
| `tests/test_isolated_to_team_simulation.py` | 300–310 | Existing tests that use `audit_lead.tools` — must be migrated. |
| `tests/test_agent_teams_backend.py` | 1115–1190 | Existing tests referencing `coding_lead`, `review_lead`, `testing_lead` — must be migrated. |
| `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | 459–675 | Phase 1 section. Note the plan's Task 1.3 signature differs from this artifact's spec; this artifact's spec (the team-lead brief) is authoritative. |

## Pre-Flight: Context7 Research

Run these queries with `mcp__context7__resolve-library-id` + `mcp__context7__query-docs` and note the findings inline in commit messages:

1. **Python dataclass field ordering** — verify that fields with `default_factory` can be followed by fields with plain default values (`int = 300`, `bool = True`). Finding to apply: the existing `PhaseLeadsConfig` already interleaves these, so the rewrite may keep `handoff_timeout_seconds`/`allow_parallel_phases` after the four `wave_*_lead` fields as today. No ordering change required.
2. **Python asyncio + pathlib async file writes** — verify `Path.write_text()` remains the idiomatic sync write used inside `asyncio.to_thread` for small files. If library recommends `aiofiles` for correctness: do **not** adopt — stay on `Path.write_text()` to match `route_message()` in `agent_teams_backend.py:909`.
3. **Fallback note:** if context7 yields no actionable result, use `route_message()` at `agent_teams_backend.py:856` as the canonical pattern for all context-directory writes in `codex_lead_bridge.py`.

## Pre-Flight: Sequential Thinking

Before Task 1.1, call `mcp__sequential-thinking__sequentialthinking` with the problem statement in the team-lead brief. The required conclusion — which this artifact already applies — is:

- **Clean rename, not aliases.** Aliases via `property` getters hide the breakage; an incremental shim adds permanent tech debt. Since only four callers outside the backend reference the old fields (`agents.py` line 5426-5431, `cli.py:2858`, three test files), they can all be migrated in the same commit.
- **Drop `planning_lead`, `architecture_lead`, `coding_lead`, `review_lead`, `testing_lead`, `audit_lead`** from `PhaseLeadsConfig`.
- **Add `wave_a_lead`, `wave_d5_lead`, `wave_t_lead`, `wave_e_lead`**.
- **Preserve `handoff_timeout_seconds` and `allow_parallel_phases`** as final fields (correction #8).
- **Update `agents.py:5426-5431`** to build the lead-name→(config, prompt) dict with the new names. Use `PLANNING_LEAD_PROMPT` text as the `wave-a-lead` prompt body (or rename the prompt constant; lowest-risk move is to keep the prompt constants and just reassign them). Reassignment preserves existing prompt content.
- **Remove or migrate `audit_lead`-gated code paths** in `cli.py:2858` and `test_isolated_to_team_pipeline.py`. The team-lead brief says testing-lead/audit-lead "may need to stay or be removed"; this artifact **removes** them from `PHASE_LEAD_NAMES` and `PhaseLeadsConfig` because Phase 1's roster is Claude-only waves (A, D5, T, E) and audit-lead has no wave in the new roster. If a future phase needs audit, it will be reintroduced as `wave_audit_lead` or similar.

## Corrections Applied (Phase 1)

- **Correction #2:** `AgentTeamConfig` is at `config.py:1210`, not 1193. All references in this artifact use line 1210.
- **Correction #8:** `PhaseLeadsConfig.handoff_timeout_seconds` (default `300`) and `PhaseLeadsConfig.allow_parallel_phases` (default `True`) are preserved verbatim after the rename. Both are exercised by the cross-validation test.
- **Correction #10:** `tests/test_codex_lead_bridge.py` includes `test_wave_to_lead_references_valid_leads` that asserts every value in `codex_lead_bridge.WAVE_TO_LEAD` is a member of `AgentTeamsBackend.PHASE_LEAD_NAMES`. This catches drift between the bridge mapping and the lead roster.

## Task-by-Task Implementation

### Task 1.1 — Rename PHASE_LEAD_NAMES and PhaseLeadsConfig to wave-aligned names

**Modify:** `src/agent_team_v15/agent_teams_backend.py`, `src/agent_team_v15/config.py`, `src/agent_team_v15/agents.py`, `src/agent_team_v15/cli.py`, `tests/test_phase_lead_integration.py`, `tests/test_isolated_to_team_pipeline.py`, `tests/test_isolated_to_team_simulation.py`, `tests/test_agent_teams_backend.py`.
**Create:** `tests/test_phase_lead_roster.py`.

#### Step 1 — Write the failing test

Create `tests/test_phase_lead_roster.py`:

```python
"""Phase 1 Task 1.1: PHASE_LEAD_NAMES and PhaseLeadsConfig are wave-aligned."""
from __future__ import annotations

from agent_team_v15.agent_teams_backend import AgentTeamsBackend
from agent_team_v15.config import AgentTeamConfig, PhaseLeadsConfig


def test_phase_lead_names_are_wave_aligned():
    """PHASE_LEAD_NAMES lists only wave-aligned leads."""
    expected = {"wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"}
    assert set(AgentTeamsBackend.PHASE_LEAD_NAMES) == expected


def test_phase_lead_names_no_legacy_names():
    """Legacy generic names must be absent."""
    legacy = {
        "planning-lead", "architecture-lead", "coding-lead",
        "review-lead", "testing-lead", "audit-lead",
    }
    overlap = legacy & set(AgentTeamsBackend.PHASE_LEAD_NAMES)
    assert not overlap, f"Legacy names still present: {overlap}"


def test_phase_leads_config_fields_match_roster():
    """Every name in PHASE_LEAD_NAMES maps to a PhaseLeadsConfig attribute (correction #10 cross-validation)."""
    cfg = PhaseLeadsConfig()
    backend = AgentTeamsBackend.__new__(AgentTeamsBackend)
    backend._config = AgentTeamConfig()
    for name in AgentTeamsBackend.PHASE_LEAD_NAMES:
        lead_cfg = backend._get_phase_lead_config(name)
        assert lead_cfg is not None, f"No PhaseLeadConfig mapped for {name!r}"
        assert hasattr(lead_cfg, "enabled"), (
            f"_get_phase_lead_config({name!r}) must return a PhaseLeadConfig"
        )


def test_phase_leads_config_preserves_handoff_and_parallel_fields():
    """Correction #8: handoff_timeout_seconds and allow_parallel_phases remain after rename."""
    cfg = PhaseLeadsConfig()
    assert hasattr(cfg, "handoff_timeout_seconds")
    assert hasattr(cfg, "allow_parallel_phases")
    assert isinstance(cfg.handoff_timeout_seconds, int)
    assert isinstance(cfg.allow_parallel_phases, bool)
```

Run: `python -m pytest tests/test_phase_lead_roster.py -v` — expect 4 failures (AttributeError on new fields, legacy names still present).

#### Step 2 — Implement

**File 1: `src/agent_team_v15/agent_teams_backend.py`**

Replace `PHASE_LEAD_NAMES` at lines 289–296:

```python
    PHASE_LEAD_NAMES: list[str] = [
        "wave-a-lead",    # Wave A — Claude architecture/schema
        "wave-d5-lead",   # Wave D5 — Claude frontend polish
        "wave-t-lead",    # Wave T — Claude test writing
        "wave-e-lead",    # Wave E — Claude verification/audit
    ]
```

Replace `_get_phase_lead_config` at lines 689–704:

```python
    def _get_phase_lead_config(self, lead_name: str) -> Any:
        """Return the PhaseLeadConfig for a given lead name.

        Maps wave-aligned lead names (e.g., ``"wave-a-lead"``) to the
        corresponding config attribute (e.g., ``config.phase_leads.wave_a_lead``).
        """
        phase_leads_cfg = self._config.phase_leads
        name_map = {
            "wave-a-lead":  phase_leads_cfg.wave_a_lead,
            "wave-d5-lead": phase_leads_cfg.wave_d5_lead,
            "wave-t-lead":  phase_leads_cfg.wave_t_lead,
            "wave-e-lead":  phase_leads_cfg.wave_e_lead,
        }
        return name_map.get(lead_name)
```

**File 2: `src/agent_team_v15/config.py`**

Replace `PhaseLeadsConfig` at lines 555–584:

```python
@dataclass
class PhaseLeadsConfig:
    """Configuration for the phase lead team architecture.

    When enabled, the orchestrator registers phase leads as SDK subagents
    (AgentDefinition objects) that are invoked via the Task tool. Each lead
    is aligned to a Claude persistent-session wave (A, D5, T, E).
    """
    enabled: bool = False
    wave_a_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Write", "Edit"],
    ))
    wave_d5_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    wave_t_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    wave_e_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Bash"],
    ))
    handoff_timeout_seconds: int = 300
    allow_parallel_phases: bool = True
```

**File 3: `src/agent_team_v15/agents.py`** — lines ~5421–5432

Find the `_lead_configs` dict at approximately line 5426. The live code currently reads:

```python
_arch_prompt = ARCHITECTURE_LEAD_PROMPT
if config.enterprise_mode.enabled:
    _arch_prompt += ENTERPRISE_ARCHITECTURE_STEPS

_lead_configs = {
    "planning-lead": (config.phase_leads.planning_lead, PLANNING_LEAD_PROMPT),
    "architecture-lead": (config.phase_leads.architecture_lead, _arch_prompt),
    "coding-lead": (config.phase_leads.coding_lead, CODING_LEAD_PROMPT),
    "review-lead": (config.phase_leads.review_lead, REVIEW_LEAD_PROMPT),
    "testing-lead": (config.phase_leads.testing_lead, TESTING_LEAD_PROMPT),
    "audit-lead": (config.phase_leads.audit_lead, AUDIT_LEAD_PROMPT),
}
```

Update **both** the string keys and the `config.phase_leads.*` field references to use the new wave-aligned names. The `_arch_prompt` preamble lines stay unchanged. Replace the dict body with:

```python
_lead_configs = {
    "wave-a-lead": (config.phase_leads.wave_a_lead, PLANNING_LEAD_PROMPT),
    "wave-d5-lead": (config.phase_leads.wave_d5_lead, _arch_prompt),
    "wave-t-lead": (config.phase_leads.wave_t_lead, TESTING_LEAD_PROMPT),
    "wave-e-lead": (config.phase_leads.wave_e_lead, REVIEW_LEAD_PROMPT),
}
```

Remove the `testing-lead` and `audit-lead` entries (both names are dropped from `PHASE_LEAD_NAMES`). The exact mapping must match the final `PHASE_LEAD_NAMES` list and the renamed `PhaseLeadsConfig` fields.

**File 4: `src/agent_team_v15/cli.py`** — line 2858

Replace:

```python
        if config.phase_leads.audit_lead.enabled:
```

with:

```python
        if config.phase_leads.wave_e_lead.enabled:
```

(Audit work now lives under Wave E verification.)

**File 5: `tests/test_phase_lead_integration.py`** — line 99

Replace `c.phase_leads.audit_lead.enabled = False` with `c.phase_leads.wave_e_lead.enabled = False`.

**File 6: `tests/test_isolated_to_team_pipeline.py`** — lines 54, 111, 314–321

Replace every `audit_lead` with `wave_e_lead`.

**File 7: `tests/test_isolated_to_team_simulation.py`** — lines 304–305

Replace `cfg.phase_leads.audit_lead.tools` with `cfg.phase_leads.wave_e_lead.tools`.

**File 8: `tests/test_agent_teams_backend.py`** — lines 1118, 1127, 1136, 1183

- `coding_lead` → `wave_a_lead` (coding maps to Wave A in new roster; if the test specifically tests coding-lead semantics, re-target to wave_a_lead).
- `review_lead` → `wave_e_lead`.
- `testing_lead` → `wave_t_lead`.

#### Step 3 — Quick verify

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_phase_lead_roster.py -v
python -m pytest tests/test_phase_lead_integration.py tests/test_isolated_to_team_pipeline.py tests/test_isolated_to_team_simulation.py tests/test_agent_teams_backend.py -v
python -c "from agent_team_v15.config import PhaseLeadsConfig; c = PhaseLeadsConfig(); assert hasattr(c, 'wave_a_lead'); assert hasattr(c, 'handoff_timeout_seconds'); assert hasattr(c, 'allow_parallel_phases'); assert not hasattr(c, 'planning_lead')"
grep -n "planning-lead\|architecture-lead\|coding-lead\|review-lead" src/agent_team_v15/agents.py | grep -v "^.*#\|\"\"\"" 
# Must return EMPTY (no live code references to old names)
```

All pytest invocations must pass. The `python -c` guard must exit 0. The `grep` must return empty. Commit with message: `Phase 1 Task 1.1: rename phase leads to wave-aligned names`.

---

### Task 1.2 — Add CODEX_WAVE_COMPLETE and STEER_REQUEST to MESSAGE_TYPES

**Modify:** `src/agent_team_v15/agent_teams_backend.py`.
**Create:** `tests/test_phase_lead_messaging.py`.

#### Step 1 — Write the failing test

Create `tests/test_phase_lead_messaging.py`:

```python
"""Phase 1 Task 1.2: MESSAGE_TYPES exposes cross-protocol events."""
from __future__ import annotations

from agent_team_v15.agent_teams_backend import AgentTeamsBackend


def test_message_types_contains_codex_wave_complete():
    assert "CODEX_WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES


def test_message_types_contains_steer_request():
    assert "STEER_REQUEST" in AgentTeamsBackend.MESSAGE_TYPES


def test_message_types_preserves_legacy_entries():
    """Rename must not drop existing types that other code paths rely on."""
    required_legacy = {
        "REQUIREMENTS_READY", "ARCHITECTURE_READY", "WAVE_COMPLETE",
        "REVIEW_RESULTS", "DEBUG_FIX_COMPLETE", "WIRING_ESCALATION",
        "CONVERGENCE_COMPLETE", "TESTING_COMPLETE", "ESCALATION_REQUEST",
        "SYSTEM_STATE", "RESUME",
    }
    missing = required_legacy - AgentTeamsBackend.MESSAGE_TYPES
    assert not missing, f"Legacy message types dropped: {missing}"
```

Run: `python -m pytest tests/test_phase_lead_messaging.py -v` — expect 2 failures.

#### Step 2 — Implement

Edit `src/agent_team_v15/agent_teams_backend.py` lines 299–311. Replace `MESSAGE_TYPES` with:

```python
    MESSAGE_TYPES: set[str] = {
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
        "CODEX_WAVE_COMPLETE",   # orchestrator → Claude lead: Codex turn finished with diff summary
        "STEER_REQUEST",         # Claude lead → orchestrator: please steer active Codex turn
    }
```

#### Step 3 — Quick verify

```bash
python -m pytest tests/test_phase_lead_messaging.py -v
python -c "from agent_team_v15.agent_teams_backend import AgentTeamsBackend; assert 'CODEX_WAVE_COMPLETE' in AgentTeamsBackend.MESSAGE_TYPES and 'STEER_REQUEST' in AgentTeamsBackend.MESSAGE_TYPES and 'WAVE_COMPLETE' in AgentTeamsBackend.MESSAGE_TYPES"
```

Both must succeed. Commit: `Phase 1 Task 1.2: add CODEX_WAVE_COMPLETE and STEER_REQUEST message types`.

---

### Task 1.3 — Create codex_lead_bridge.py

**Create:** `src/agent_team_v15/codex_lead_bridge.py`, `tests/test_codex_lead_bridge.py`.

#### Step 1 — Write the failing test

Create `tests/test_codex_lead_bridge.py`:

```python
"""Phase 1 Task 1.3: Codex→Claude cross-protocol bridge."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_wave_to_lead_mapping_is_exact():
    """WAVE_TO_LEAD routes every Codex wave to a concrete Claude lead."""
    from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD
    assert WAVE_TO_LEAD == {
        "A5": "wave-a-lead",
        "B":  "wave-a-lead",
        "D":  "wave-d5-lead",
        "T5": "wave-t-lead",
    }


def test_wave_to_lead_references_valid_leads():
    """Correction #10: every value in WAVE_TO_LEAD must be a member of PHASE_LEAD_NAMES.

    Catches drift between the bridge mapping and the lead roster.
    """
    from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD
    from agent_team_v15.agent_teams_backend import AgentTeamsBackend
    for wave, lead in WAVE_TO_LEAD.items():
        assert lead in AgentTeamsBackend.PHASE_LEAD_NAMES, (
            f"WAVE_TO_LEAD[{wave!r}] = {lead!r} not in PHASE_LEAD_NAMES "
            f"({AgentTeamsBackend.PHASE_LEAD_NAMES})"
        )


def test_route_codex_wave_complete_writes_file(tmp_path: Path):
    """route_codex_wave_complete writes a CODEX_WAVE_COMPLETE message file in context_dir."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete
    route_codex_wave_complete(
        wave_letter="B",
        context_dir=tmp_path,
        result_summary="Created schema.prisma (42 lines). Created seed.ts (18 lines).",
    )
    written = list(tmp_path.glob("msg_*_codex-wave-b_to_wave-a-lead.md"))
    assert len(written) == 1, f"expected exactly one message file, found {written}"
    body = written[0].read_text(encoding="utf-8")
    assert "Type: CODEX_WAVE_COMPLETE" in body
    assert "To: wave-a-lead" in body
    assert "schema.prisma" in body


def test_route_codex_wave_complete_unknown_wave_is_fail_open(tmp_path: Path):
    """Unknown wave letters are logged and skipped without raising."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete
    route_codex_wave_complete(
        wave_letter="ZZ",
        context_dir=tmp_path,
        result_summary="unused",
    )
    assert list(tmp_path.iterdir()) == []


def test_route_codex_wave_complete_missing_dir_is_fail_open(tmp_path: Path):
    """Missing context_dir does not raise — fail-open contract."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete
    missing = tmp_path / "does-not-exist"
    route_codex_wave_complete(
        wave_letter="B",
        context_dir=missing,
        result_summary="unused",
    )


def test_read_pending_steer_requests_empty_when_no_files(tmp_path: Path):
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests
    assert read_pending_steer_requests(wave_letter="B", context_dir=tmp_path) == []


def test_read_pending_steer_requests_reads_matching_files(tmp_path: Path):
    """Reads STEER_REQUEST files addressed to the given wave."""
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests
    steer = tmp_path / "msg_1234_wave-a-lead_to_codex-wave-b.md"
    steer.write_text(
        "To: codex-wave-b\n"
        "From: wave-a-lead\n"
        "Type: STEER_REQUEST\n"
        "Timestamp: 1234\n"
        "---\n"
        "Fix PORT in main.ts to 3001",
        encoding="utf-8",
    )
    messages = read_pending_steer_requests(wave_letter="B", context_dir=tmp_path)
    assert len(messages) == 1
    assert "PORT" in messages[0]


def test_read_pending_steer_requests_missing_dir_is_fail_open(tmp_path: Path):
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests
    missing = tmp_path / "does-not-exist"
    assert read_pending_steer_requests(wave_letter="B", context_dir=missing) == []
```

Run: `python -m pytest tests/test_codex_lead_bridge.py -v` — expect ImportError on the module.

#### Step 2 — Implement

Create `src/agent_team_v15/codex_lead_bridge.py`:

```python
"""Cross-protocol bridge between Codex app-server waves and Claude phase leads.

The orchestrator calls :func:`route_codex_wave_complete` after each Codex
turn/completed and routes a CODEX_WAVE_COMPLETE message to the relevant
Claude lead via the shared context directory.

Claude leads write STEER_REQUEST files into the same context directory.
The orchestrator calls :func:`read_pending_steer_requests` before the
next Codex turn/start and translates the returned bodies into turn/steer
calls against the active Codex thread.

Both entry points are fail-open: any I/O failure is logged and swallowed.
An unknown wave letter is a no-op.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps Codex wave letter to the Claude lead that owns its review.
WAVE_TO_LEAD: dict[str, str] = {
    "A5": "wave-a-lead",
    "B":  "wave-a-lead",
    "D":  "wave-d5-lead",
    "T5": "wave-t-lead",
}


def _codex_sender(wave_letter: str) -> str:
    return f"codex-wave-{wave_letter.lower()}"


def route_codex_wave_complete(
    wave_letter: str,
    context_dir: Path,
    result_summary: str,
) -> None:
    """Write a CODEX_WAVE_COMPLETE message to the context directory.

    The message follows the same framed format used by
    ``AgentTeamsBackend.route_message`` so existing parsing logic works
    unchanged. Unknown waves and any I/O failure are logged and swallowed.
    """
    try:
        lead = WAVE_TO_LEAD.get(wave_letter)
        if lead is None:
            logger.info(
                "codex_lead_bridge: no Claude lead mapped for wave %r — skipping",
                wave_letter,
            )
            return

        timestamp = int(time.time() * 1000)
        sender = _codex_sender(wave_letter)
        body = (
            f"To: {lead}\n"
            f"From: {sender}\n"
            f"Type: CODEX_WAVE_COMPLETE\n"
            f"Timestamp: {timestamp}\n"
            f"Wave: {wave_letter}\n"
            f"---\n"
            f"{result_summary}"
        )
        path = Path(context_dir) / f"msg_{timestamp}_{sender}_to_{lead}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        logger.info(
            "codex_lead_bridge: routed CODEX_WAVE_COMPLETE wave=%s → %s (%s)",
            wave_letter, lead, path.name,
        )
    except OSError as exc:
        logger.warning(
            "codex_lead_bridge.route_codex_wave_complete failed (wave=%s): %s",
            wave_letter, exc,
        )


def read_pending_steer_requests(
    wave_letter: str,
    context_dir: Path,
) -> list[str]:
    """Return STEER_REQUEST bodies addressed to the given Codex wave.

    Looks for files of the form ``msg_*_<sender>_to_codex-wave-<letter>.md``
    in *context_dir* with ``Type: STEER_REQUEST`` in the header. Returns the
    bodies (text after the ``---`` framing line) in filename order.
    Missing directory, unreadable files, and malformed headers are
    swallowed and contribute nothing to the result.
    """
    results: list[str] = []
    try:
        target = _codex_sender(wave_letter)
        base = Path(context_dir)
        if not base.exists():
            return results
        for path in sorted(base.glob(f"msg_*_to_{target}.md")):
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.debug(
                    "codex_lead_bridge: unreadable steer file %s: %s", path, exc,
                )
                continue
            header, _, body = raw.partition("\n---\n")
            if "Type: STEER_REQUEST" not in header:
                continue
            results.append(body.strip())
    except OSError as exc:
        logger.warning(
            "codex_lead_bridge.read_pending_steer_requests failed (wave=%s): %s",
            wave_letter, exc,
        )
    return results
```

#### Step 3 — Quick verify

```bash
python -m pytest tests/test_codex_lead_bridge.py -v
python -c "from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD, route_codex_wave_complete, read_pending_steer_requests; assert set(WAVE_TO_LEAD) == {'A5','B','D','T5'}"
```

All tests pass. Commit: `Phase 1 Task 1.3: add codex_lead_bridge module for Codex→Claude messaging`.

## Phase Gate: Verification Checklist

Run every command. Each must produce the exact outcome listed.

```bash
cd C:/Projects/agent-team-v18-codex

# 1. New Phase 1 tests all pass.
python -m pytest tests/test_phase_lead_roster.py tests/test_phase_lead_messaging.py tests/test_codex_lead_bridge.py -v

# 2. Legacy callers migrated — no stale test passes-by-accident and no AttributeError.
python -m pytest tests/test_phase_lead_integration.py tests/test_isolated_to_team_pipeline.py tests/test_isolated_to_team_simulation.py tests/test_agent_teams_backend.py -v

# 3. Public surface sanity check.
python -c "from agent_team_v15.agent_teams_backend import AgentTeamsBackend; assert 'wave-a-lead' in AgentTeamsBackend.PHASE_LEAD_NAMES; assert 'CODEX_WAVE_COMPLETE' in AgentTeamsBackend.MESSAGE_TYPES; assert 'STEER_REQUEST' in AgentTeamsBackend.MESSAGE_TYPES"

# 4. Preserved fields present (correction #8).
python -c "from agent_team_v15.config import PhaseLeadsConfig; c = PhaseLeadsConfig(); assert hasattr(c, 'handoff_timeout_seconds'); assert hasattr(c, 'allow_parallel_phases'); assert hasattr(c, 'wave_a_lead'); assert not hasattr(c, 'planning_lead'); assert not hasattr(c, 'audit_lead')"

# 5. No legacy lead names linger inside PHASE_LEAD_NAMES context.
python -c "
import pathlib, re
src = pathlib.Path('src/agent_team_v15/agent_teams_backend.py').read_text()
m = re.search(r'PHASE_LEAD_NAMES[^]]+\]', src, re.DOTALL)
assert m, 'PHASE_LEAD_NAMES not found'
block = m.group(0)
for stale in ('planning-lead', 'architecture-lead', 'coding-lead', 'review-lead', 'testing-lead', 'audit-lead'):
    assert stale not in block, f'Legacy name {stale!r} still in PHASE_LEAD_NAMES'
print('PHASE_LEAD_NAMES clean')
"

# 6. Bridge module import + mapping sanity.
python -c "from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD; assert WAVE_TO_LEAD['A5'] == 'wave-a-lead' and WAVE_TO_LEAD['B'] == 'wave-a-lead' and WAVE_TO_LEAD['D'] == 'wave-d5-lead' and WAVE_TO_LEAD['T5'] == 'wave-t-lead'"
```

All six commands must pass. Do **not** mark Phase 1 complete until every command returns exit code 0.

## Handoff State

After Phase 1 lands, Phase 4 can rely on the following load-bearing contracts:

- `AgentTeamsBackend.PHASE_LEAD_NAMES == ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]`.
- `AgentTeamsBackend.MESSAGE_TYPES` is a superset of `{"CODEX_WAVE_COMPLETE", "STEER_REQUEST"}` and preserves all 11 pre-existing types.
- `PhaseLeadsConfig` has fields `wave_a_lead`, `wave_d5_lead`, `wave_t_lead`, `wave_e_lead`, `handoff_timeout_seconds`, `allow_parallel_phases`.
- `agent_team_v15.codex_lead_bridge.WAVE_TO_LEAD` maps `{"A5", "B"} → "wave-a-lead"`, `"D" → "wave-d5-lead"`, `"T5" → "wave-t-lead"`.
- `route_codex_wave_complete(wave_letter, context_dir, result_summary) -> None` is fail-open (never raises).
- `read_pending_steer_requests(wave_letter, context_dir) -> list[str]` is fail-open (returns `[]` on any error).
- Callers in `agents.py` and `cli.py` reference the new field names — no `AttributeError` at runtime.
