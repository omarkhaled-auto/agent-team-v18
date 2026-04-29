# Phase 5 — `milestone_progress[].status` Enum Migration (DEGRADED)

> **Audience:** downstream operator tooling — CI/CD pipelines, dashboards,
> Slack alerts, status pages, Looker queries, anything that reads
> `STATE.json::milestone_progress[<id>].status`.

## What changed

Phase 5 introduces a **new enum value**:

| Status        | Meaning                                                         | Pre-Phase-5? |
|---------------|-----------------------------------------------------------------|--------------|
| `PENDING`     | Not started.                                                    | yes          |
| `IN_PROGRESS` | Currently executing.                                            | yes          |
| `BLOCKED`     | Dependency-blocked; not running yet.                            | yes          |
| `COMPLETE`    | Build PASSED + audit PASSED (no unresolved FAIL ≥ HIGH).        | yes          |
| **`DEGRADED`** | **NEW.** Build PASSED + carry-forward debt (≤ MEDIUM unresolved findings OR all FAIL DEFERRED). | **NO** |
| `FAILED`      | Build FAILED OR audit returned ≥ HIGH unresolved FAIL findings. | yes          |

Pre-Phase-5, milestones with build-pass-but-audit-fail were silently
marked `COMPLETE`. Phase 5 makes the gap visible: `DEGRADED` means
*"shipped with debt"* — explicitly NOT clean, but not blocking
dependents either.

## Treat `DEGRADED` as

* Not equal to `COMPLETE`.
* Not equal to `FAILED`.
* Closer to "complete-with-warnings" than to either pole.
* Eligible for the **`completed_milestones`** rollup (dependent milestones
  may proceed) — same as `COMPLETE`, NOT same as `FAILED`. This preserves
  Phase 4's planning semantics: a DEGRADED milestone unblocks downstream
  work because its build runs; the debt is tracked separately.

## JSON schema delta

`milestone_progress[<id>]` gains four operator-visible fields (Phase 5.3
data layer; Phase 5.5 wires them):

```json
{
  "status": "COMPLETE" | "DEGRADED" | "FAILED" | "IN_PROGRESS" | "BLOCKED" | "PENDING",
  "failure_reason": "string",
  "audit_status": "clean" | "degraded" | "failed" | "unknown",
  "unresolved_findings_count": int,
  "audit_debt_severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "",
  "audit_findings_path": "string (absolute path)",
  "audit_fix_rounds": int
}
```

All four new fields use **sentinel-skip**: when absent / `-1` / `""`, the
field is *not present* on disk. Backward-compat readers that don't know
about the new fields keep working byte-identically.

## Migration recipe for downstream tooling

* **Boolean rollups** of "milestone done" — change from `status == "COMPLETE"`
  to `status in ("COMPLETE", "DEGRADED")`.
* **Strict-quality rollups** of "milestone clean" — keep `status == "COMPLETE"`.
* **Failure rollups** — keep `status == "FAILED"`.
* **Debt dashboards** — read `audit_status`, `unresolved_findings_count`,
  `audit_debt_severity`, `audit_findings_path` for per-milestone debt
  detail.

## Phase 5.5 deprecation log

The first `DEGRADED` milestone per run emits a one-time loud log:

```
[QUALITY-CONTRACT] Milestone <X> marked DEGRADED — this is a NEW status
enum introduced in Phase 5. Downstream tooling reading
milestone_progress[].status should handle DEGRADED in addition to
COMPLETE/FAILED/IN_PROGRESS/PENDING. See
docs/operator/phase-5-status-enum-migration.md.
```

## `--legacy-permissive-audit` migration flag

Operators with existing builds carrying HIGH/CRITICAL audit findings can
pass `--legacy-permissive-audit` to downgrade those milestones from
`FAILED` → `DEGRADED`. Each downgrade fires a per-milestone deprecation
log. Removal of the flag is **evidence-gated**, not calendar-gated:

* ≥80% of live milestones land clean for 4 consecutive weeks (or
  approved smoke batches).
* No active CRITICAL suppression in `.agent-team/audit_suppressions.json`.
* Median confirmed-finding precision ≥70% across the most recent 3+
  smoke batches.

The flag is **deprecated from day one**. Address findings to migrate off.

## Retroactive migration of existing run-directories

`agent-team-v15 rescan-quality-debt --cwd <run-dir>` re-evaluates each
completed milestone against the Phase 5 Quality Contract and populates
the new fields. Optional `--rescan-overwrite-status` rewrites `COMPLETE`
→ `DEGRADED` retroactively (operator opt-in; breaking change to existing
STATE.json status enum). See `QUALITY_DEBT_RESCAN.md` for the rescan
report shape.

## `_anchor/_complete/_quality.json` sidecar

Per-milestone anchor captures (Phase 4.6) now include
`_anchor/_complete/_quality.json`:

```json
{
  "quality": "clean" | "degraded",
  "audit_status": "clean" | "degraded" | "failed" | "unknown",
  "unresolved_findings_count": 0,
  "audit_debt_severity": "",
  "audit_findings_path": "",
  "captured_at": "2026-04-29T00:00:00Z"
}
```

`--retry-milestone <id>` reads the sidecar to inform the operator what
quality state they are restoring from. Single anchor slot;
`_anchor/_degraded/` does NOT exist (quality is in the sidecar).

## Auditor-noise instrumentation (`confirmation_status`)

Each `AuditFinding` on disk gains a `confirmation_status` field:

```json
{
  "finding_id": "AUDIT-001",
  "verdict": "FAIL",
  "severity": "HIGH",
  "confirmation_status": "unconfirmed" | "confirmed" | "rejected",
  ...
}
```

Default is `unconfirmed` at write-time. Operator runs
`agent-team-v15 confirm-findings --cwd <run-dir>` to mark each finding
`confirmed` (true positive) or `rejected` (false positive). Rejections
write to `.agent-team/audit_suppressions.json` (the persisted
suppression registry); subsequent Quality Contract evaluations exclude
findings whose registry entry validates.

CRITICAL findings cannot be suppressed without
`--emergency-suppress-critical`; the flag writes
`emergency_critical_suppression=true` to STATE.json (auditable).

## See also

* Plan: `docs/plans/2026-04-28-phase-5-quality-milestone.md` §B (the
  Quality Contract definition), §H (Phase 5.5 brief), §M.M1 (single
  resolver), §M.M2 (state-invariant validator), §M.M8 (anchor sidecar),
  §M.M10 (rescan command), §M.M12 (this enum migration), §M.M13
  (auditor noise instrumentation), §M.M15 (`--legacy-permissive-audit`
  evidence-based sunset).
