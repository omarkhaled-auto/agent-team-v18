# Frozen smoke artifacts — `m1-hardening-smoke-20260426-173745`

Source run-dir: `v18 test runs/m1-hardening-smoke-20260426-173745/` (HEAD `1c46445`,
Phase 1.6 baseline). These files were copied verbatim by Phase 4.1 of
`docs/plans/2026-04-26-pipeline-upgrade-phase4.md` per §0.2 step 4 and §M.8.

Plan-level invariant (§M.8): never delete the smoke run-dir without first
verifying every `test_replay_smoke_2026_04_26_*` fixture still passes against
this frozen subset. These files back the data-driven proofs that Phase 4 ships
the right behaviour against ground-truth output, not a synthesised stub.

| File | Used by phase | Purpose |
|---|---|---|
| `WAVE_FINDINGS.json` | 4.1 / 4.4 | Per-retry per-service failure attribution (the data-driven proof that retry-2 of Wave B failed only on `service=web`, which Wave B would never have owned under Phase 4.1 narrowing) |
| `STATE.json` | 4.4 | Snapshot showing `milestone_progress.milestone-1 == {"status": "FAILED"}` with no `failure_reason` (Phase 1.6 only wired audit-fail) |
| `AUDIT_REPORT.json` | 4.3 / 4.5 | 46 findings to classify by `owner_wave`; Phase 4.3's classifier asserts ≥4 critical findings get `owner_wave="D"` (Wave D never ran) |
| `STACK_CONTRACT.json` | 4.1 | Service-name resolution input (`backend_path_prefix=apps/api/` derives `api`; `frontend_path_prefix=apps/web/` derives `web`) |
| `milestone_progress.json` | 4.4 | Forensics-inconsistency reproduction (this file says interrupted_milestone="milestone-1" while STATE.json says None) |
| `telemetry/milestone-1-wave-{A,B}.json` | 4.4 | Wave success/duration telemetry feeding `WaveFailureForensics` |
| `codex-captures/milestone-1-wave-B-prompt.txt` | 4.7 | The 52KB Wave B prompt with 0 mentions of "Wave D" — the input-quality smoking gun |
| `codex-captures/milestone-1-wave-B-protocol-retry-payloads.txt` | 4.2 | Excerpt of the 4MB protocol log: only the two `<previous_attempt_failed>` blocks (retry=1, retry=2). Phase 4.2 asserts the new payload is ≥10× richer than these ~150-byte blocks |
| `apps/web/src/middleware.ts` | 4.7 | The scaffold stub literally commented `// SCAFFOLD STUB — Wave D finalizes…`; Phase 4.7b adds the machine-readable `@scaffold-stub` header here |
| `docker-compose.yml` | 4.1 | Service-name source-of-truth: confirms `api`, `web`, `postgres` are the canonical service names this smoke ran |

## Excerpts

`milestone-1-wave-B-protocol-retry-payloads.txt` is the single excerpt: the full
protocol log is 4MB and would bloat the repo. The excerpt isolates only the
`<previous_attempt_failed>` blocks via the script in
`tools/extract_smoke_retry_payloads.py` (regenerable from the source run-dir if
the smoke run-dir disappears, but the source run-dir is the canonical input).

## Regeneration

If the smoke run-dir is ever pruned and these fixtures need to be regenerated
from a successor smoke, the consuming tests will likely break (new findings
counts, different service names, different retry counts). Do NOT regenerate
casually — the captured-frozen-in-time character of these files is the test
contract. Cut a fresh `smoke_<YYYY-MM-DD>` directory for new evidence and
update fixture references explicitly.
