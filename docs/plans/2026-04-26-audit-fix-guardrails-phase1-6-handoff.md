# Audit-Fix-Loop Guardrails — Phase 1.6 Handoff (Quick-Wins Bundle)

**Date:** 2026-04-26
**Author:** Phase 3.5 implementer (handoff)
**Reader:** Phase 1.6 implementer (you)
**Predecessors:**
- Phase 1 (`6663cfe`) → Phase 2 (`7e5ed18`) → Phase 3 (`2b3004d`) → Phase 1.5 (`61a3630`) → Phase 3.5 (`215ccb3`)
- Plan: `docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md`
- Phase 3.5 handoff: `docs/plans/2026-04-26-audit-fix-guardrails-phase3-5-handoff.md`
- Landing memories: `phase_1_landing.md`, `phase_2_landing.md`, `phase_3_landing.md`, `phase_1_5_landing.md`, `phase_3_5_landing.md`

---

## 0 — TL;DR

Two carry-overs from Phase 1.5 and Phase 2 landing memories — both
schema-additive, low-risk, low-LoC, and bundle-able into one session:

* **#1 — Persist `failure_reason`** in `RunState.milestone_progress[id]`
  so post-hoc forensics can distinguish `regression` /
  `no_improvement` / `cross_milestone_lock_violation` /
  `no_target_files_skipped` failures. Today the helper at
  `cli.py:_handle_audit_failure_milestone_anchor` accepts `reason: str`
  but discards it.
* **#4 — Config-driven timeout** for `run_regression_check`. Today the
  300s timeout is hardcoded at `fix_executor.py:725`; a Playwright
  hang on a slow CI runner stalls the audit-fix loop with no operator
  override.

Both ship in **one commit** direct-to-master per §0.0a:
`feat(audit-fix-guardrails): Phase 1.6 — failure_reason persistence + config-driven regression timeout`

**Not in this phase**: backend-runner regression (#3) and per-finding
scope (#5) — both deferred per `phase_3_5_landing.md` §"Open
follow-ups". Both have material complexity and risk; both should be
their own plans with measurement gates, not bundled into a quick-wins
follow-up.

**Estimated effort**: 2–3 hours total. ~65 LoC source + ~150 LoC tests.

---

## 1 — Why each follow-up matters

### 1.1 #1 — failure_reason persistence

**Carry-over from `phase_1_5_landing.md` §"Plan deviations / observations":**

> The `reason` parameter on `_handle_audit_failure_milestone_anchor`
> isn't persisted anywhere. Phase 1 added it as an informational kwarg
> but the helper doesn't pass it to `update_milestone_progress` (which
> doesn't take a reason). The parameter is captured for future use —
> a Phase 1.6 candidate is to extend
> `RunState.milestone_progress[id]` with a `failure_reason` field that
> the helper writes, so post-hoc forensics can distinguish
> `regression` / `no_improvement` /
> `cross_milestone_lock_violation` failures.

Phase 3.5 added a fifth reason value (`no_target_files_skipped` is
implicit — features are skipped per Phase 3.5 §A residual without
firing the helper, but a future phase might want to count those).
Without persistence, an operator inspecting STATE.json after a halt
sees `status: "FAILED"` with no signal about *why*. Telemetry already
logs the reason at runtime; this follow-up makes it survive process
exit.

### 1.2 #4 — config-driven regression timeout

**Carry-over from `phase_2_landing.md` §"Open follow-ups (not blocking)":**

> Subprocess timeout 300s — `run_regression_check` still hard-codes
> 300s; a Playwright hang stalls the loop. Phase 1.5 should plumb a
> config-driven timeout.

The 300s value was inherited from the original Phase 2 implementation
and never made config-driven. On a slow CI runner with a large e2e
suite, 300s can be insufficient; on a local dev workflow with a single
test file, 300s is wasteful when something hangs. Operator-tunable
without a code change.

---

## 2 — Follow-up #1: persist `failure_reason`

### 2.1 Current state (citations verified against current source)

**File:** `src/agent_team_v15/state.py`

* **Line 37**: `milestone_progress: dict[str, dict] = field(default_factory=dict)`
  — schema-flexible value type; any dict shape loads.
* **Lines 402–449**: `update_milestone_progress(state, milestone_id, status)`
  is the single-resolver mutation site. Line **433**:
  `state.milestone_progress[milestone_id] = {"status": status_upper}`
  REPLACES the entire dict on every call. The comment block at lines
  435–449 documents the `summary["success"]` reconciliation invariant
  that depends on `failed_milestones`, NOT on the dict shape — so
  extending the dict with `failure_reason` does not interact with the
  summary-resolver logic.
* **Lines 684–741**: `load_state(directory: str = ".agent-team")`.
  Line **708**:
  `milestone_progress=_expect(data.get("milestone_progress", {}), dict, {})`
  — `_expect` accepts any dict shape; the Phase 1.6 schema change is
  zero-migration.

**File:** `src/agent_team_v15/cli.py`

* **Lines 7574–7613**: `_handle_audit_failure_milestone_anchor(*,
  state, milestone_id, cwd, anchor_dir, reason: str, agent_team_dir)`
  is the helper that fires Phase 1's anchor restore. It accepts
  `reason` as a keyword arg, but line **7631** invokes
  `update_milestone_progress(state, milestone_id, "FAILED")` without
  the reason. The reason is currently logged-only (and only by Phase
  1.5's invocation site at the cycle catch).
* **Lines 4006–4008**: `--reset-failed-milestones` partial-update path:
  ```python
  _mp = _current_state.milestone_progress.get(_mid)
  if isinstance(_mp, dict) and _mp.get("status") == "FAILED":
      _mp["status"] = "PENDING"
  ```
  This is a partial in-place mutation that does NOT go through
  `update_milestone_progress`. After Phase 1.6 it must also clear
  `failure_reason` to avoid stale data on reset.

**Caller audit (16 update_milestone_progress sites in cli.py):**

```
4834, 4929, 4986, 5018, 5045, 5382, 5433, 5751,
5871, 5886, 5994, 6026, 6153, 6232, 7631
```

(15 distinct in cli.py; line 7614 is a docstring reference, not a
call.) None pass a reason today; the only site that has a meaningful
reason in scope is **7631** inside the anchor helper. Phase 1.6
modifies that single call site.

### 2.2 Design decisions

**A — Storage shape**: extend the existing `milestone_progress[id]` dict
with an optional `failure_reason` key. Reason: schema-additive within
the existing `dict[str, dict]` field; load_state already accepts any
dict shape; zero migration. Rejected alternative: new top-level
`RunState.milestone_failure_reasons: dict[str, str]` field — would
introduce a new schema field requiring load/save migration.

**B — Write API**: add `failure_reason: str = ""` keyword-only argument
to `update_milestone_progress`. When provided, the new dict at line
433 includes the key:
```python
new_value: dict[str, Any] = {"status": status_upper}
if failure_reason:
    new_value["failure_reason"] = failure_reason
state.milestone_progress[milestone_id] = new_value
```
Reason: backward-compat (15 existing call sites unchanged); REPLACE
semantics auto-clear stale reasons on status transitions.

**C — Read API**: add a free function
`get_milestone_failure_reason(state: RunState, milestone_id: str) -> str`
in `state.py`. Reason: explicit accessor lets future readers (audit
dashboards, post-hoc forensics) consume the field without coupling to
the implicit dict shape.

**D — Reset cleanup**: add one line at `cli.py:4008`:
```python
_mp["status"] = "PENDING"
_mp.pop("failure_reason", None)  # Phase 1.6: clear stale audit-fix reason
```
Reason: in-place mutation must explicitly clear the new key (unlike
the REPLACE pattern in update_milestone_progress).

**E — Anchor helper wiring**: change `cli.py:7631` from
```python
update_milestone_progress(state, milestone_id, "FAILED")
```
to
```python
update_milestone_progress(state, milestone_id, "FAILED", failure_reason=reason)
```
Reason: minimal, single-site change at the only call site that has a
semantic reason in scope today.

### 2.3 Implementation sketch

```python
# state.py:402
def update_milestone_progress(
    state: RunState,
    milestone_id: str,
    status: str,
    *,
    failure_reason: str = "",
) -> None:
    """Update the milestone tracking fields on *state* in place.

    Phase 1.6 audit-fix-loop guardrail: when ``failure_reason`` is
    non-empty AND ``status`` is "FAILED", persists the reason in
    ``milestone_progress[id]["failure_reason"]`` for post-hoc
    forensics. Telemetry distinguishes reasons like ``"regression"``,
    ``"no_improvement"``, ``"cross_milestone_lock_violation"``. The
    REPLACE semantic at the dict assignment auto-clears stale reasons
    on subsequent status transitions to COMPLETE/DEGRADED/IN_PROGRESS.
    """
    status_upper = status.upper()
    if status_upper == "IN_PROGRESS":
        state.current_milestone = milestone_id
    elif status_upper in ("COMPLETE", "DEGRADED"):
        state.current_milestone = ""
        if milestone_id not in state.completed_milestones:
            state.completed_milestones.append(milestone_id)
        if milestone_id in state.failed_milestones:
            state.failed_milestones.remove(milestone_id)
    elif status_upper == "FAILED":
        state.current_milestone = ""
        if milestone_id not in state.failed_milestones:
            state.failed_milestones.append(milestone_id)

    new_value: dict[str, Any] = {"status": status_upper}
    if failure_reason:
        new_value["failure_reason"] = failure_reason
    state.milestone_progress[milestone_id] = new_value

    # ... existing summary["success"] reconciliation (unchanged) ...


def get_milestone_failure_reason(state: RunState, milestone_id: str) -> str:
    """Read the persisted failure reason for a milestone.

    Phase 1.6 audit-fix-loop guardrail: returns the empty string when
    the milestone has no failure reason persisted (e.g., never failed,
    or failed before Phase 1.6 landed, or reset via
    ``--reset-failed-milestones``).
    """
    entry = state.milestone_progress.get(milestone_id)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("failure_reason", "") or "")
```

```python
# cli.py:7631 (inside _handle_audit_failure_milestone_anchor)
update_milestone_progress(
    state, milestone_id, "FAILED", failure_reason=reason
)
```

```python
# cli.py:4006-4008 (--reset-failed-milestones path)
_mp = _current_state.milestone_progress.get(_mid)
if isinstance(_mp, dict) and _mp.get("status") == "FAILED":
    _mp["status"] = "PENDING"
    _mp.pop("failure_reason", None)  # Phase 1.6: clear stale reason on reset
```

### 2.4 Test fixtures

```python
# tests/test_audit_fix_guardrails_phase1_6.py

def test_update_milestone_progress_writes_failure_reason_when_provided():
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    assert state.milestone_progress["milestone-1"] == {
        "status": "FAILED",
        "failure_reason": "regression",
    }

def test_update_milestone_progress_omits_failure_reason_when_not_provided():
    """Backward compat: 15 existing call sites pass no reason."""
    state = RunState()
    update_milestone_progress(state, "milestone-1", "FAILED")
    assert state.milestone_progress["milestone-1"] == {"status": "FAILED"}
    assert "failure_reason" not in state.milestone_progress["milestone-1"]

def test_update_milestone_progress_replaces_stale_failure_reason_on_status_change():
    """REPLACE semantics: COMPLETE after FAILED clears the reason."""
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    update_milestone_progress(state, "milestone-1", "COMPLETE")
    assert state.milestone_progress["milestone-1"] == {"status": "COMPLETE"}
    assert "failure_reason" not in state.milestone_progress["milestone-1"]

def test_get_milestone_failure_reason_returns_empty_when_unset():
    state = RunState()
    update_milestone_progress(state, "milestone-1", "FAILED")
    assert get_milestone_failure_reason(state, "milestone-1") == ""

def test_get_milestone_failure_reason_returns_persisted_value():
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED",
        failure_reason="cross_milestone_lock_violation",
    )
    assert get_milestone_failure_reason(
        state, "milestone-1"
    ) == "cross_milestone_lock_violation"

def test_get_milestone_failure_reason_returns_empty_for_unknown_milestone():
    state = RunState()
    assert get_milestone_failure_reason(state, "milestone-99") == ""

def test_handle_audit_failure_milestone_anchor_persists_reason_to_state(tmp_path):
    """End-to-end through the Phase 1 helper: reason flows from
    _run_audit_loop catch site → helper → update_milestone_progress."""
    from agent_team_v15.cli import _handle_audit_failure_milestone_anchor
    from agent_team_v15.state import RunState, get_milestone_failure_reason
    from unittest.mock import patch

    anchor_dir = tmp_path / "_anchor"
    anchor_dir.mkdir()
    state = RunState()

    with patch("agent_team_v15.wave_executor._restore_milestone_anchor",
               return_value={"reverted": [], "deleted": [], "restored": []}), \
         patch("agent_team_v15.cli.save_state"):
        _handle_audit_failure_milestone_anchor(
            state=state,
            milestone_id="milestone-1",
            cwd=str(tmp_path),
            anchor_dir=anchor_dir,
            reason="cross_milestone_lock_violation",
            agent_team_dir=str(tmp_path),
        )

    assert get_milestone_failure_reason(
        state, "milestone-1"
    ) == "cross_milestone_lock_violation"

def test_reset_failed_milestones_clears_failure_reason():
    """The --reset-failed-milestones in-place mutation must explicitly
    clear failure_reason; without this fix, stale reasons persist after
    reset and confuse post-hoc forensics."""
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    # Simulate the cli.py:4006-4008 in-place mutation path with the
    # Phase 1.6 cleanup line.
    _mp = state.milestone_progress.get("milestone-1")
    assert isinstance(_mp, dict) and _mp.get("status") == "FAILED"
    _mp["status"] = "PENDING"
    _mp.pop("failure_reason", None)

    assert state.milestone_progress["milestone-1"] == {"status": "PENDING"}
```

### 2.5 Edge cases / risks

* **R1**: dict shape change breaks downstream readers that hard-code
  `{"status": ...}` equality. Audit: only `cli.py:4007` does
  `_mp.get("status") == "FAILED"` — that's `.get()`, schema-tolerant.
  No equality-on-whole-dict consumers found.
* **R2**: --reset-failed-milestones leaves stale failure_reason →
  fixed by 1-line addition (D above).
* **R3**: 16 update_milestone_progress call sites could surprise the
  reviewer. Audit: keyword-only kwarg with default `""` means none of
  the 15 unchanged sites need touching; only the helper at 7631
  passes the reason.
* **R4**: load_state of an old STATE.json without failure_reason →
  zero issue, `_expect(..., dict, {})` already accepts arbitrary
  dict shape, and `get_milestone_failure_reason` returns `""` for
  missing keys.

---

## 3 — Follow-up #4: config-driven regression timeout

### 3.1 Current state (citations verified against current source)

**File:** `src/agent_team_v15/fix_executor.py`

* **Lines 669–698**: `run_regression_check(cwd, previously_passing_acs,
  config, *, test_surface_lock=None, finding_id="",
  finding_surface=None) -> list[str]`. Signature already takes
  `config: Any`.
* **Lines 712–725**: `subprocess.run(cmd, cwd=str(project_root),
  capture_output=True, text=True, timeout=300)` — the hardcoded value
  is at **line 725**.
* **Line 727**: `except (OSError, subprocess.SubprocessError):` —
  catches `subprocess.TimeoutExpired` (subclass of `SubprocessError`,
  Context7-confirmed below). Existing exception path is fine; only
  the timeout value is changing.

**File:** `src/agent_team_v15/config.py`

* **Lines 514–547**: `AuditTeamConfig` dataclass. Last existing field
  is `test_surface_lock_enabled: bool = True` at **line 547**. New
  field will sit beneath it.
* **Lines 550–573**: `_validate_audit_team_config(cfg)`. Existing
  pattern: validate range, raise `ValueError` with descriptive
  message. Phase 1.6 adds one more block.

**Caller audit (5 run_regression_check sites total):**

```
src/agent_team_v15/fix_executor.py:669   (def — function definition)
src/agent_team_v15/fix_executor.py:345   (call from execute_unified_fix_async)
src/agent_team_v15/fix_executor.py:477   (call from execute_unified_fix_async)
src/agent_team_v15/coordinated_builder.py:1179  (legacy caller)
src/agent_team_v15/coordinated_builder.py:1920  (legacy caller)
```

All 4 callers already pass `config` positionally. Phase 1.6 reads
the new config field inside `run_regression_check`; **no caller
changes** required.

**Config typing reality (`fix_executor.py:1249-1250` shows the
mixed-shape pattern):**
```python
return config.get(key, default)
v18 = config.get("v18")
```
But `coordinated_builder.py:1182` passes the orchestrator's
`AgentTeamConfig` object (attribute-shaped), while
`fix_executor.py:345,477` may pass a dict. The new read site must be
defensive across both.

### 3.2 Context7-verified subprocess.run timeout contract

Per Context7 researchMode lookup of `/python/cpython/v3.11.14`
(retrieved 2026-04-26):

> **`subprocess.run(timeout=N)`** raises **`subprocess.TimeoutExpired`**
> when `N` seconds elapse before the child completes. Implementation
> (`Lib/subprocess.py`):
> 1. `process.kill()` to terminate the child
> 2. On Windows: `process.communicate()` to collect remaining output
> 3. On POSIX: `process.wait()` to reap zombie
> 4. `TimeoutExpired` is re-raised after the child has terminated
>
> **Class hierarchy** (`Lib/subprocess.py`):
> ```python
> class SubprocessError(Exception): pass
> class TimeoutExpired(SubprocessError): pass
> ```

Implications for Phase 1.6:
* The existing `except (OSError, subprocess.SubprocessError):` at
  `fix_executor.py:727` already catches TimeoutExpired correctly.
* On Windows (this repo's primary platform), the child is killed via
  `TerminateProcess` and output is collected via `communicate()`
  before re-raise. No platform-specific handling needed in our code.
* Therefore Phase 1.6 is **pure config plumbing** — no exception-
  handling changes, no platform conditionals.

### 3.3 Design decisions

**A — Field placement**: `AuditTeamConfig.regression_check_timeout: int = 300`.
Reason: lives next to existing `milestone_anchor_enabled` and
`test_surface_lock_enabled` toggles; consistent with Phase 1+2
patterns.

**B — Validation**: 1 ≤ timeout ≤ 3600. Lower bound rejects 0/negative
(would break subprocess.run); upper bound prevents pathological values
that would hide real hangs. Reason: matches existing
`_validate_audit_team_config` patterns (max_parallel_auditors 1-5,
score thresholds 0-100).

**C — Defensive read pattern**: `config: Any` means caller may pass
either an `AgentTeamConfig` object (attribute-shaped) OR a dict
(mixed code path; see fix_executor.py:1249-1250 evidence). The read
in `run_regression_check` must handle both:

```python
def _resolve_regression_check_timeout(config: Any, default: int = 300) -> int:
    """Phase 1.6: read AuditTeamConfig.regression_check_timeout from a
    dual-shape config (object OR dict). Falls back to default when the
    config is None, malformed, or pre-Phase-1.6.
    """
    audit_team = None
    if config is None:
        return default
    if hasattr(config, "audit_team"):
        audit_team = getattr(config, "audit_team", None)
    elif hasattr(config, "get"):
        audit_team = config.get("audit_team")
    if audit_team is None:
        return default
    if hasattr(audit_team, "regression_check_timeout"):
        value = getattr(audit_team, "regression_check_timeout", default)
    elif hasattr(audit_team, "get"):
        value = audit_team.get("regression_check_timeout", default)
    else:
        return default
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return default
    return timeout if 1 <= timeout <= 3600 else default
```

The defensive read sits in `fix_executor.py` near
`run_regression_check`. Reason: avoids surprising the existing
`config.get()` consumers in the file.

**D — Validation scope**: validate at config-load time (existing
`_validate_audit_team_config`). The defensive read AT CALL TIME falls
back to default on malformed values rather than raising — keeps the
audit-fix loop running even if config is corrupted. Two-layer safety.

### 3.4 Implementation sketch

```python
# config.py:547 — extend AuditTeamConfig
@dataclass
class AuditTeamConfig:
    # ... existing fields ...
    test_surface_lock_enabled: bool = True
    # Phase 1.6 audit-fix-loop guardrail. Subprocess timeout for
    # ``run_regression_check``'s Playwright invocation. Default 300s
    # preserves Phase 2 behaviour; lower for fast-feedback dev runs;
    # raise for slow CI runners. Capped at 3600s upstream by
    # ``_validate_audit_team_config`` to keep pathological values from
    # masking real hangs (the M25-disaster prevention property
    # depends on the audit-fix loop making forward progress).
    regression_check_timeout: int = 300
```

```python
# config.py:550 — extend _validate_audit_team_config
def _validate_audit_team_config(cfg: AuditTeamConfig) -> None:
    # ... existing validations ...
    if cfg.max_findings_per_fix_task > 20:
        raise ValueError("audit_team.max_findings_per_fix_task must be <= 20")
    # Phase 1.6: regression timeout sanity bounds. Negative/zero would
    # break subprocess.run; values > 1 hour are pathological and
    # likely to mask hung processes that the audit-fix loop should
    # surface, not absorb.
    if not (1 <= cfg.regression_check_timeout <= 3600):
        raise ValueError(
            "audit_team.regression_check_timeout must be 1-3600 seconds; "
            f"got {cfg.regression_check_timeout!r}"
        )
```

```python
# fix_executor.py — defensive read helper near run_regression_check
def _resolve_regression_check_timeout(config: Any, default: int = 300) -> int:
    """Phase 1.6: dual-shape config read for regression_check_timeout."""
    if config is None:
        return default
    audit_team = None
    if hasattr(config, "audit_team"):
        audit_team = getattr(config, "audit_team", None)
    elif hasattr(config, "get"):
        audit_team = config.get("audit_team")
    if audit_team is None:
        return default
    if hasattr(audit_team, "regression_check_timeout"):
        value = getattr(audit_team, "regression_check_timeout", default)
    elif hasattr(audit_team, "get"):
        value = audit_team.get("regression_check_timeout", default)
    else:
        return default
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return default
    return timeout if 1 <= timeout <= 3600 else default


def run_regression_check(...) -> list[str]:
    # ... existing setup ...
    if e2e_dir.exists():
        cmd = ["npx", "playwright", "test"]
        if locked_paths:
            cmd.extend(locked_paths)
        cmd.append("--reporter=json")
        # Phase 1.6: config-driven timeout (defaults to 300s
        # for Phase 2 behaviour preservation when config is None
        # or pre-Phase-1.6).
        regression_timeout = _resolve_regression_check_timeout(config)
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=regression_timeout,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        # ... existing handling unchanged ...
```

### 3.5 Test fixtures

```python
# tests/test_audit_fix_guardrails_phase1_6.py (continued)

def test_audit_team_config_default_regression_timeout_is_300():
    cfg = AuditTeamConfig()
    assert cfg.regression_check_timeout == 300

def test_audit_team_config_validates_regression_timeout_zero_raises():
    cfg = AuditTeamConfig(regression_check_timeout=0)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)

def test_audit_team_config_validates_regression_timeout_negative_raises():
    cfg = AuditTeamConfig(regression_check_timeout=-1)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)

def test_audit_team_config_validates_regression_timeout_above_3600_raises():
    cfg = AuditTeamConfig(regression_check_timeout=3601)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)

def test_audit_team_config_validates_regression_timeout_at_boundaries_ok():
    """Boundary values (1 and 3600) are valid."""
    cfg_low = AuditTeamConfig(regression_check_timeout=1)
    cfg_high = AuditTeamConfig(regression_check_timeout=3600)
    _validate_audit_team_config(cfg_low)  # no raise
    _validate_audit_team_config(cfg_high)  # no raise

def test_resolve_regression_check_timeout_falls_back_when_config_none():
    from agent_team_v15.fix_executor import _resolve_regression_check_timeout
    assert _resolve_regression_check_timeout(None) == 300

def test_resolve_regression_check_timeout_reads_object_shape(tmp_path):
    """coordinated_builder.py passes AgentTeamConfig (object-shaped)."""
    from types import SimpleNamespace
    from agent_team_v15.fix_executor import _resolve_regression_check_timeout
    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=120)
    )
    assert _resolve_regression_check_timeout(config) == 120

def test_resolve_regression_check_timeout_reads_dict_shape():
    """fix_executor.py call sites pass dict-shaped config in some paths."""
    from agent_team_v15.fix_executor import _resolve_regression_check_timeout
    config = {"audit_team": {"regression_check_timeout": 600}}
    assert _resolve_regression_check_timeout(config) == 600

def test_resolve_regression_check_timeout_clamps_invalid_to_default():
    from types import SimpleNamespace
    from agent_team_v15.fix_executor import _resolve_regression_check_timeout
    cfg = SimpleNamespace(audit_team=SimpleNamespace(regression_check_timeout=0))
    assert _resolve_regression_check_timeout(cfg) == 300  # falls back

def test_run_regression_check_passes_configured_timeout_to_subprocess(tmp_path):
    """Verify the subprocess.run kwargs receive the config-driven value."""
    import subprocess
    from types import SimpleNamespace
    from unittest.mock import patch, MagicMock
    from agent_team_v15.fix_executor import run_regression_check

    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "x.spec.ts").write_text("test('x', () => {})")

    captured: dict = {}

    def _fake_run(*args, **kwargs):
        captured.update(kwargs)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=42)
    )
    with patch.object(subprocess, "run", side_effect=_fake_run):
        run_regression_check(
            str(tmp_path),
            previously_passing_acs=["AC-1"],
            config=config,
        )

    assert captured.get("timeout") == 42, (
        f"Expected subprocess.run to receive timeout=42 from config; "
        f"captured kwargs were {captured!r}"
    )
```

### 3.6 Edge cases / risks

* **R5**: validation rejects 0/negative — explicit, documented.
* **R6**: very large values cap at 3600 → keeps M25 prevention
  property intact (audit-fix loop must make forward progress).
* **R7**: tests must mock `subprocess.run` and assert the exact
  timeout kwarg, otherwise a no-op default could pass for the wrong
  reason.
* **R8**: 4 existing call sites pass `config` and don't read its
  shape — the defensive helper handles both. If a future caller
  passes a non-dict / non-object (e.g., a string), the helper falls
  back to default.

---

## 4 — Pre-flight checks (mandatory before ANY code)

Same pattern as Phase 1-3 plan §0.1; tightened for Phase 1.6 scope.

1. **Re-read all five predecessor landings**: `phase_1_landing.md`,
   `phase_2_landing.md`, `phase_3_landing.md`, `phase_1_5_landing.md`,
   `phase_3_5_landing.md`. Cross-phase context informs why these
   carry-overs were deferred.

2. **Verify editable install**:
   ```
   python -c "import agent_team_v15; print(agent_team_v15.__file__)"
   ```
   Must resolve under `src/agent_team_v15/__init__.py`.

3. **Re-verify every `file:line` citation in §2 and §3 against current
   source.** This handoff was authored 2026-04-26 against
   commit `215ccb3`. Citations may drift across sessions. If ANY
   cited line moved: STOP, update the handoff with the new lines
   first, then implement. Use `grep` not line numbers when
   verifying.

4. **Run baseline test slice** — must be fully green:
   ```
   pytest tests/test_audit_fix_guardrails_phase{1,1_5,2,3,3_5}.py \
          tests/test_hook_multimatcher_conflict.py \
          tests/test_wave_d_path_guard.py \
          tests/test_agent_teams_backend.py \
          tests/test_audit_models.py \
          tests/test_audit_team.py \
          tests/test_fix_prd_agent.py
   ```
   Expected: ~225 guardrails-slice + audit-models slice green. If
   any are red BEFORE you start, STOP and surface to user.

5. **Confirm Phase 3.5 is on master**:
   ```
   git log --oneline -1
   ```
   Must show `215ccb3` (or descendants on master).

6. **Run the m1_fast_forward harness** as the baseline:
   ```
   & .\scripts\run-m1-fast-forward.ps1
   ```
   All 6 gates must pass with `ready_for_full_smoke: true` BEFORE
   you start Phase 1.6 work — ensures the pipeline is currently
   clean.

---

## 5 — TDD sequence (strict order, NON-NEGOTIABLE)

Per the original plan §0.1 #7 + `superpowers:test-driven-development`.

1. **Create `tests/test_audit_fix_guardrails_phase1_6.py`** with all
   ~14 fixtures from §2.4 + §3.5. Run pytest. Confirm fixtures fail
   with the expected `AttributeError` / `ImportError` for
   `failure_reason` kwarg, `regression_check_timeout` field,
   `_resolve_regression_check_timeout` helper. **STOP if the
   failures are wrong-shaped** (e.g., `SyntaxError`, `ModuleNotFoundError`
   for an existing module — means your test file is broken).

2. **Implement #1 in this order** (each commit-able independently if
   you're paranoid; otherwise bundle):
   1. `state.py` — extend `update_milestone_progress` with
      `failure_reason` kwarg.
   2. `state.py` — add `get_milestone_failure_reason` helper.
   3. `cli.py:7631` — wire the helper to pass `reason`.
   4. `cli.py:4008` — add `_mp.pop("failure_reason", None)` cleanup
      line.
   5. Run #1 fixtures → all green.

3. **Implement #4 in this order**:
   1. `config.py` — add `regression_check_timeout: int = 300` field.
   2. `config.py` — extend `_validate_audit_team_config`.
   3. `fix_executor.py` — add `_resolve_regression_check_timeout`
      helper.
   4. `fix_executor.py:725` — change `timeout=300` to
      `timeout=_resolve_regression_check_timeout(config)`.
   5. Run #4 fixtures → all green.

4. **Run combined test slice** (per pre-flight #4) — must be fully
   green. ~14 new fixtures + ~225 baseline. Total ~240 green.

5. **Run m1_fast_forward harness** — all 6 gates pass with
   `ready_for_full_smoke: true`. If any gate regresses on
   previously-clean state, STOP per §6.

6. **Diff review**: `git diff` — read every line one more time. Look
   for:
   - Leftover debug logs / print statements
   - Hardcoded values that should be config (irony level high, but
     check anyway)
   - Edits to files outside the four modules listed in §7

7. **Direct-to-master single commit + push** per §0.0a:
   ```
   git add src/agent_team_v15/state.py \
           src/agent_team_v15/cli.py \
           src/agent_team_v15/config.py \
           src/agent_team_v15/fix_executor.py \
           tests/test_audit_fix_guardrails_phase1_6.py
   git commit -m "feat(audit-fix-guardrails): Phase 1.6 — failure_reason persistence + config-driven regression timeout"
   git push origin master
   ```

8. **Memory write per §7.**

---

## 6 — Halting conditions

NEVER paper over a halt. STOP and surface to user if ANY of:

* A predecessor landing memory disagrees with the current source
  (citation drift). Update the handoff first.
* The `update_milestone_progress` signature has changed since
  2026-04-26 (e.g., another phase added a kwarg).
* The `run_regression_check` signature has changed since 2026-04-26.
* A test fixture passes for the WRONG reason (e.g., the mocked
  subprocess.run silently accepts any timeout value because the
  fixture forgot to assert on the kwarg).
* The m1_fast_forward harness regresses on previously-clean gates
  (Phase 1.6 is purely additive; any regression is a real bug).
* You discover that the `config: Any` reality at one of the 4
  caller sites is neither object-shaped nor dict-shaped (e.g., a
  TypedDict with constraints, or a frozen wrapper). Surface the
  shape and decide whether the defensive helper needs extension.
* You discover a NEW risk that this handoff §2.5 / §3.6 don't
  cover. Surface it explicitly with a Risk-register annotation per
  the original plan §0.1 #12.

---

## 7 — Memory write spec (after merge)

Write `phase_1_6_landing.md` to
`~/.claude/projects/C--Projects-agent-team-v18-codex/memory/`
capturing:

* Actual function signatures shipped (may differ from §2.3 / §3.4).
* List of risks closed (R1–R8 above).
* Whether the defensive helper needed extension for any unexpected
  config shape.
* Reference back to where future readers should look for failure
  reason data: `STATE.json::milestone_progress[id].failure_reason`.
* Note on values that flow into `failure_reason` — current set:
  `regression`, `no_improvement`, `cross_milestone_lock_violation`.
  If Phase 3.5's "no_target_files" ever fires the helper (today it
  doesn't — Phase 3.5 ship-blocks at dispatch without firing the
  anchor), document that as a future possibility.
* Add the index entry to `MEMORY.md`:
  ```
  - [Phase 1.6 audit-fix-loop guardrails landing](phase_1_6_landing.md) — failure_reason persistence + config-driven regression timeout shipped 2026-04-2X commit <SHA>; closes phase_1_5 + phase_2 carry-overs
  ```

---

## 8 — File index (touched by Phase 1.6)

* `src/agent_team_v15/state.py` — extend
  `update_milestone_progress` with `failure_reason` kwarg, add
  `get_milestone_failure_reason` helper.
* `src/agent_team_v15/cli.py` — wire `_handle_audit_failure_milestone_anchor`
  to pass `failure_reason=reason` (line 7631), add cleanup at
  `--reset-failed-milestones` path (line 4008).
* `src/agent_team_v15/config.py` — extend `AuditTeamConfig` with
  `regression_check_timeout: int = 300`, extend
  `_validate_audit_team_config` with the new bound check.
* `src/agent_team_v15/fix_executor.py` — add
  `_resolve_regression_check_timeout` helper, replace hardcoded
  `timeout=300` at line 725 with
  `timeout=_resolve_regression_check_timeout(config)`.
* `tests/test_audit_fix_guardrails_phase1_6.py` — new, ~14 fixtures.

**Files NOT touched**: `wave_executor.py`, `audit_models.py`,
`fix_prd_agent.py`, `audit_fix_path_guard.py`,
`wave_d_path_guard.py`, `agent_teams_backend.py`. If your diff
shows changes to any of these, you've drifted from scope.

---

## 9 — Out of scope (do NOT bundle)

Per the Phase 3.5 landing memory's deferred-with-rationale list:

* **Multi-runner regression check** (pytest/vitest/jest support in
  `run_regression_check`) — needs its own plan with measurement gate
  (observe an audit-fix run that converges green while a non-
  Playwright test silently regressed). Estimated 1–2 days.
* **Per-finding scope** (vs per-feature) — undoes the deliberate
  per-feature grouping design (`fix_prd_agent.py:373`). Needs its
  own plan with observation gate (observe a feature whose findings
  have overlapping target_files where one fix corrupts the other's
  territory). Estimated 2–5 days.
* **Wave D sandbox restriction to apps/web/** — needs precondition
  observation (current snapshot/restore proves insufficient). See
  `project_wave_d_sandbox_restriction_followup.md`.
* **3 legacy `_run_audit_loop` call sites** (`cli.py:2281`,
  `cli.py:7576`, `cli.py:13044`) — needs upstream plumbing of
  state/agent_team_dir/anchor_dir kwargs through each caller chain.
  Estimated 4–8h. Not bundled because the call-site analysis is
  Medium complexity (each chain needs its own scope verification),
  not a quick-win.
