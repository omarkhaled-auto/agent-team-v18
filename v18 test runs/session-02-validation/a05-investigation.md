# A-05 — Validation-pipe snake_case normalization investigation

**Decision:** **Remove normalization at scaffold layer.** Flag the deeper DTO/contract drift (CV-02, CV-03) for Session 3+.

## Evidence

### Build-j emission (Wave B output, not scaffold_runner)

`v18 test runs/build-j-closeout-sonnet-20260415/apps/api/src/common/pipes/validation.pipe.ts`
subclasses `ValidationPipe` and overrides `transform` to call
`normalizeInput(value)` from `src/common/utils/case.util.ts` for body / query
payloads before delegating to `super.transform`. `normalizeInput` recursively
walks any plain-object input and rewrites every key to snake_case via the
`CAMEL_SEGMENT_PATTERN` replacer.

A companion `serializeOutput` exists in the same utils file — so both request
keys and response keys are rewritten to snake_case.

### Contract alignment

`CONTRACT_E2E_RESULTS.md` records the misalignment pattern 11 times on Task
endpoints alone:

- Contract: `assigneeId` (camelCase) in request bodies and responses.
- DTOs under `apps/api/src/tasks/dto/` declare `assignee_id` (snake_case).

The pipe's `normalizeInput` is what currently lets the system receive
`assigneeId` from clients and still pass class-validator (it rewrites to the
DTO's snake_case key). Remove `normalizeInput` without also fixing the DTO
field names, and `forbidNonWhitelisted: true` starts rejecting every
contract-shaped request. That is a half-fix.

### Scaffold_runner today

`src/agent_team_v15/scaffold_runner.py` does NOT currently emit
`validation.pipe.ts`. The file comes from Wave B. PR A adds `main.ts` that
uses the built-in `ValidationPipe` directly (no subclass). PR B extends that:
scaffold now emits `apps/api/src/common/pipes/validation.pipe.ts` as a thin
barrel exporting the standard NestJS `ValidationPipe` options
(`whitelist: true, forbidNonWhitelisted: true, transform: true`) — with NO
custom key rewriting. Scaffold baseline is correct. If Wave B later regresses
the file (writes the normalizeInput version), that is a wave-layer issue.

### Why this is not a half-fix

The scope of A-05 per the tracker is "scaffold-layer correctness of the
validation pipe." The snake_case pipe does not originate in scaffold_runner,
so we're not removing a working-but-covering feature — we're establishing
the correct scaffold baseline. The *separate* DTO/contract misalignment
(CV-02 rename `assignee_id` → `assigneeId`, CV-03 missing camelCase fields,
plus removing `serializeOutput` from the response path) is a multi-file
change in Wave B's output space, explicitly out of this session's scope per
the execute brief §4 guardrails ("do not change Wave B/D prompts").

## Session 3+ follow-up (flagged, not fixed here)

1. DTO rename — every field using snake_case in `apps/api/src/*/dto/*.ts`
   renamed to camelCase to match contract.
2. Remove `serializeOutput` from the response interceptor so responses keep
   camelCase keys.
3. Delete `case.util.ts` entirely once neither pipe nor interceptor
   references it.

Reference the tracker (CV-02/CV-03 under §… of
`2026-04-15-builder-reliability-tracker.md`) when scheduling the follow-up.
