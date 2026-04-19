# D-11 — `WAVE_FINDINGS.json` remained empty; Wave T outputs missing

**Tracker ID:** D-11
**Source:** B-011, F-030 ("WAVE_FINDINGS.json empty. No e2e/ directory or playwright tests. M1 Wave E artifacts missing.")
**Session:** 4
**Size:** M (~80 LOC)
**Risk:** LOW
**Status:** plan

---

## 1. Problem statement

Build-j's `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json` is literally `{"findings": []}`. Wave T (trace/E2E) was supposed to populate findings via Playwright-based E2E runs; Wave T didn't run for M1 in build-j because it's gated behind Wave D success, and Wave D failed.

This creates a downstream problem: post-orchestration gates look at `WAVE_FINDINGS.json` for deterministic evidence and find nothing, which defeats the point of the ledger.

## 2. Root cause

Two parts:
1. **Wave T gate condition:** Wave T runs only if Wave D `success=true`. This makes Wave T useless for post-failure diagnosis when Wave D fails.
2. **Missing skip marker:** Even when Wave T doesn't run, `WAVE_FINDINGS.json` is created empty rather than with a structured skip reason. Observer can't tell if Wave T ran and found nothing vs never ran at all.

## 3. Proposed fix shape

### 3a. Always write `WAVE_FINDINGS.json` with a skip marker when Wave T doesn't run

```json
{
  "milestone_id": "milestone-1",
  "generated_at": "...",
  "wave_t_status": "skipped | completed",
  "skip_reason": "Wave D failed — Wave T cannot run E2E against failing wave output",
  "findings": []
}
```

### 3b. Run Wave T at reduced scope even when Wave D failed

For infrastructure milestones (M1) where Wave T is gated on Wave D but Wave D is about the frontend: Wave T could still validate the backend (apps/api) even if the frontend failed. Add a "partial E2E" mode that tests only what's available.

Decision: start with 3a (easy, high-value for diagnosis); 3b is optional follow-up if still useful after A-09 + A-10 land.

## 4. Test plan

File: `tests/test_wave_t_gating.py`

1. **Wave D failure writes skip marker.** Mock Wave D with `success=false`; assert `WAVE_FINDINGS.json` created with `wave_t_status="skipped"` and a reason.
2. **Wave D success runs Wave T.** Mock Wave D success; assert Wave T executes and writes findings.
3. **Skip marker has valid JSON.** Parse the skip-marker file; assert it loads cleanly.

Target: 3 tests.

## 5. Rollback plan

Revert to current behavior by removing the skip-marker write; tests verify absence.

## 6. Success criteria

- Unit tests pass.
- Gate A smoke: `WAVE_FINDINGS.json` always present and structured; if Wave T skipped, the reason is legible.

## 7. Sequencing notes

- Land in Session 4 alongside D-04, D-05, D-06, D-08.
- Independent of other tracker items.
