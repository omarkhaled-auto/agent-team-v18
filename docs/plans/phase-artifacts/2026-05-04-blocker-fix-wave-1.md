# Wave 1 close memo - M1 clean-run blockers (corrected + cleanup)

**Date:** 2026-05-04
**Parent branch:** `phase-5-closeout-stage-1-remediation`
**Wave 1 start HEAD:** `85da3bb`
**Wave 1 final integrated HEAD:** `19f1764`
**Cleanup branch:** `wave-1-cleanup`
**Wave 1 scope:** TIER 0 + TIER 1 items B1, B2, B3-broad (B3+B12 bundle), B4, B5, B10.

---

## Outcome

Wave 1 source is merged onto the parent branch at `19f1764`. The initial "all 6 CLOSE-READY" memo was superseded by the outside-reviewer correction cycle: B1, B3-broad, and B4 each required additional corrective rounds before the integrated source approval.

The load-bearing test claim is failure-name stability against the `85da3bb` baseline: no new failure names were introduced. Exact pass/fail counts vary across local sweeps, so this memo records counts as evidence snapshots rather than as the approval gate.

---

## Corrective rounds

| Item | Initial issue found after internal PASS | Corrective result |
|---|---|---|
| **B1** | The allowlist gate read stale `self.last_tool_name` instead of the current event's `tool_name` parameter. | Fixed in B1 r4 at `1a6bcab`; regression proof reverts the source and fails, reapplies and passes. |
| **B3-broad** | Retry mirror/index sequencing missed first-attempt preservation, success-after-retry refresh, and checkpoint-diff legacy mirroring. | Fixed across B3 r3/r4, final tip `5ccb417`; regression proofs cover retry sequencing and checkpoint-diff timing. |
| **B4** | Narrative PRDs without `## Files to Create` still emitted root `prisma/**` from `milestone_scope._derive_surface_globs_from_requirements`. | Promoted from follow-up to blocker and fixed in B4 r2 at `19f1764`; narrative path now emits `apps/api/prisma/**`. |

---

## Final Wave 1 commit chain

```
19f1764 fix(scope): align narrative-PRD prisma glob to apps/api canonical (B4-r2)
419bd5b fix(scope): align wave_boundary prisma path to apps/api canonical (B4)
5ccb417 fix(codex): mirror checkpoint-diff to legacy stem alongside other captures (B3-broad round 4)
19e6615 fix(codex): add operator-spec retry mirror/index integration test (B3-broad round 3)
9bc0adc fix(codex): correct retry mirror/index sequencing - every attempt preserved (B3-r3)
acca730 fix(tests): migrate stale _fake_codex_fix signatures for B12 kwargs (B3-broad follow-up)
7245105 fix(codex): preserve forensic metadata in hang reports + capture artifacts (B3+B12)
1a6bcab fix(watchdog): gate record_progress allowlist on parameter, not cached state (B1 r4)
19f71d6 fix(tests): migrate test_phase_f_lockdown stale watchdog fixture (B1 follow-up 3)
20bfe46 fix(tests): migrate residual vacuous-pass watchdog fixtures (B1 follow-up 2)
088dc4e fix(tests): migrate stale watchdog fixture strings to commandExecution (B1 follow-up)
18581c2 fix(watchdog): allowlist commandExecution-only in pending_tool_starts (B1)
d3a7982 fix(audit-fix): route non-B/D wave failures to cascade-FAILED (B2)
2ac06ab fix(wave-d): scaffold-stub finalization sanity check (B5)
7bc5acf fix(sdk): interrupt before disconnect in _cancel_sdk_client (B10)
```

---

## Items closed

| Item | Final integrated tip | Reviewer/tester state | Test delta |
|---|---|---|---|
| **B10** | `7bc5acf` | Internal reviewer PASS, tester PASS | +4 |
| **B5** | `2ac06ab` | Internal reviewer PASS, tester PASS | +8 |
| **B2** | `d3a7982` | Internal reviewer PASS, tester PASS | +11 |
| **B1** | `1a6bcab` | Corrected after outside-reviewer flag; final PASS | +13 |
| **B3-broad (B3+B12)** | `5ccb417` | Corrected after outside-reviewer flag; final PASS | +20 |
| **B4** | `19f1764` | Corrected after outside-reviewer flag; final PASS | +7 |

Net new tests across the corrected Wave 1 source: approximately +63. Integrated sweeps can show +69 passing because B1 fixture migrations also resolved baseline fixture-rot failures.

---

## Test counts

- **Baseline snapshot** at `85da3bb`: approximately 12576 passed / 50 skipped / 40 failed / 2 errors / 12667 collected. Pre-existing baseline failures were saved at `/tmp/tester-baseline-failures-clean.txt`.
- **Corrected close report snapshot** at `19f1764`: 12645 passed / 46 skipped / 40 failed / 2 errors / 12667 collected, with zero new failure names.
- **Outside-reviewer cross-check snapshot** at `19f1764`: 12650 passed / 35 failed / 46 skipped / 2 deselected, with zero new failure names and seven disappeared baseline entries.

The approval gate is the failure-name diff, not exact count parity between runs.

---

## Wave 1 cleanup follow-ups

| Follow-up | Status on `wave-1-cleanup` |
|---|---|
| **B3-broad #1:** 4 additional `_write_hang_report` outer sites lacked `cumulative_wedges_so_far` threading. | LANDED in cleanup #4 (`f096cde`). |
| **B5 #1:** source-guard regression coverage for non-D marker filtering and disk-error graceful skip. | LANDED in cleanup #3 (`677c9a4`); cleanup #5 adds the missing `rglob`-level `OSError` guard coverage. |
| **B3-broad #2:** ripgrep-config fixture isolation in `test_all_four_flags_on_dispatches_cleanly`. | LANDED in cleanup #2 (`eb25d7c`). |
| **B4 narrative-PRD scope drift:** root `prisma/**` fallback. | MERGED as B4-r2 (`19f1764`), no longer a follow-up. |
| **B3-broad storage-cost note:** mirror/index uses copies, not symlinks. | Informational only; no code required for Wave 1 cleanup. |
| **Future hardening #6:** `_scan_scaffold_stub_unfinalized` rglob-level `OSError` guard uncovered. | Closed in cleanup #5 with focused test coverage. |
| **Future hardening #7:** `_write_hang_report` static lock only matched multiline calls. | Closed in cleanup #5 by switching the lock to AST call discovery. |

---

## Harness limitation

> `Agent`'s `isolation: "worktree"` flag does not provide per-implementer isolation in this harness version.

Wave 2/3/4 should use sequential execution or explicit manual worktrees with absolute paths.

---

## Outside-reviewer discipline

Future wave close memos must include an explicit outside-reviewer round between internal reviewer/tester PASS and operator merge approval. The required focus areas remain:

1. state-vs-parameter reads,
2. sequencing in retry/recovery flows,
3. completeness against the handoff's live path, not only canonical-input fixtures,
4. cross-branch overlap claims,
5. net-new defect classes introduced by corrective rounds.

Operator merge approval is gated on outside-reviewer NOT-FLAGGED.

---

## Updated sequence

1. Merge `wave-1-cleanup` after doc-only/internal/outside-reviewer recheck and focused tests pass.
2. Run the integrated full sweep on the parent branch after cleanup merge.
3. Stop before Wave 2 unless the operator explicitly authorizes Wave 2 start.
4. Wave 2 remains B6 with B6a (BuildKit stderr sanitizer), B6b (Dockerfile lint stage), and B6c (self-verify lint-target collapse). Docker target wording must stay precise: Compose uses service `build.target`; `docker compose build` itself does not expose a `--target` flag.
5. No paid M1/full-build smokes run inside this initiative. The Phase 5 closeout track resumes after the full initiative merge plan reaches its defined endpoint.
