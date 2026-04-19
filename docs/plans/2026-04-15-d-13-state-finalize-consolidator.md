# D-13 — STATE.json ends internally inconsistent

**Tracker ID:** D-13
**Source:** B-013 + §2 of FINAL_VALIDATION_REPORT
**Session:** 3
**Size:** M (~120 LOC)
**Risk:** LOW
**Status:** plan

---

## 1. Problem statement

Build-j's final STATE.json has multiple internal inconsistencies:

| Field | Actual value | Should be |
|---|---|---|
| `summary.success` | `true` | `false` (because `failed_milestones=["milestone-1"]`) |
| `audit_health` | `""` | `"failed"` (AUDIT_REPORT.json says `health: failed`) |
| `waves_completed` | `3` | `4` (A + B + C + D — D failed but did run) OR `3 with failed_wave=D` clearly marked |
| `wave_progress.current_wave` | `D` | empty or `null` (since `current_phase: complete`) |
| `stack_contract.confidence` | `"high"` | `"low"` (struct fields are empty) |
| `gate_results` | `[]` | populated from `GATE_FINDINGS.json` |

These are all derivable from authoritative sources, but no step deterministically consolidates them at pipeline end.

## 2. Root cause

`state.py` has many writers (`record_progress`, `record_audit`, `mark_milestone_failed`, etc.) but no `finalize()` method that reconciles aggregate fields (`summary.*`, `audit_health`, `current_wave` clear) from their authoritative sources.

## 3. Proposed fix shape

### 3a. Add `State.finalize()`

```python
def finalize(self) -> None:
    """Reconcile aggregate fields from authoritative sources. Call once at end of pipeline."""
    # summary.success: derived from failed_milestones
    self.summary["success"] = len(self.failed_milestones) == 0
    
    # audit_health: derived from AUDIT_REPORT.json if present
    audit_path = self.artifacts.get("audit_report_path")
    if audit_path and Path(audit_path).exists():
        data = json.loads(Path(audit_path).read_text())
        self.audit_health = data.get("health", "")
    
    # current_wave: clear when phase complete
    if self.current_phase == "complete":
        for m in self.wave_progress.values():
            m.pop("current_wave", None)
    
    # stack_contract.confidence: low if fields are empty
    sc = self.stack_contract
    if not sc.backend_framework and not sc.frontend_framework:
        sc.confidence = "low"
    
    # gate_results: load from GATE_FINDINGS.json if present
    gate_path = self.artifacts.get("gate_findings_path")
    if gate_path and Path(gate_path).exists():
        self.gate_results = json.loads(Path(gate_path).read_text()).get("findings", [])
```

### 3b. Call `finalize()` in `cli.py` before writing final STATE.json

Single call site. Idempotent.

## 4. Test plan

File: `tests/test_state_finalize.py`

1. **Failed milestone → success=false.** Build state with `failed_milestones=["milestone-1"]`; call finalize(); assert `summary.success == False`.
2. **Audit report present → audit_health populated.** Mock AUDIT_REPORT.json with `health: failed`; finalize; assert `audit_health == "failed"`.
3. **Phase complete clears current_wave.** finalize; assert no `current_wave` in `wave_progress`.
4. **Empty stack_contract → confidence low.** finalize on empty contract; assert `confidence == "low"`.
5. **Populated stack_contract → confidence preserved.** finalize on filled contract; assert `confidence` unchanged.
6. **Gate findings loaded.** Mock GATE_FINDINGS.json; finalize; assert `gate_results` matches file.
7. **Idempotent.** Call finalize() twice; assert identical output.

Target: 7 tests.

## 5. Rollback plan

One-line revert (remove the finalize() call in cli.py). State writers on the hot path unchanged.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: STATE.json has `summary.success` matching `failed_milestones`, `audit_health` non-empty when AUDIT_REPORT exists, `current_wave` absent after phase=complete.

## 7. Sequencing notes

- Land in Session 3 alongside D-07 (audit schema) and D-20 (startup-AC probe).
- Depends on D-07 — if audit schema is broken, `audit_health` reading logic will crash. Land D-07 first in same session.
