# Session 6 — Gate A smoke (M1 clearance checkpoint)

**Tracker session:** Session 6 in `docs/plans/2026-04-15-builder-reliability-tracker.md` §9.
**Category:** Smoke gate (not code-change session).
**Integration HEAD:** `8ed55a4` — Sessions 1–5 merged.
**Expected cost:** ~$8–12 USD.
**Expected duration:** 90–120 min wall clock at exhaustive depth on M1.
**Run slug:** `build-k-gate-a-20260416` (today's first attempt).

This is the first paid smoke since the closeout bundle opened on 2026-04-12. Goal is a defensible "M1 clears" signal — the baseline from which master merge becomes viable.

---

## 0. Pre-flight checklist (verify before launching)

Run each check; all must pass. Any FAIL → do NOT launch, investigate first.

### 0a. Git state
- [ ] `git -C /c/Projects/agent-team-v18-codex rev-parse HEAD` → `8ed55a4…` (or a later merge from integration; verify with `git log --oneline -1`).
- [ ] `git -C /c/Projects/agent-team-v18-codex branch --show-current` → `integration-2026-04-15-closeout`.
- [ ] `git -C /c/Projects/agent-team-v18-codex status` → clean working tree (no uncommitted changes, no untracked scaffold test-runs from prior sessions sitting in the path).

### 0b. Environment
- [ ] `C:/smoke/clean/` exists and is empty (the space-free path per Bug #5 + the reference-runs convention). If not empty: archive contents elsewhere, confirm with `ls -la` nothing remains except the incoming config/PRD.
- [ ] `docker --version` + `docker ps` run without error — daemon is up. (M1's startup-AC probe in D-20 will try `docker compose up -d postgres`; if Docker is down the probe fails.)
- [ ] `node --version` reports Node ≥ 20.
- [ ] `npm --version` reports npm ≥ 10.
- [ ] Anthropic API key present in env (`echo $ANTHROPIC_API_KEY | head -c 10` shows key prefix).
- [ ] No prior `docker compose` containers from earlier runs. If `docker ps -a` shows leftover `postgres` etc.: `docker compose down -v` from whichever dir owns them.

### 0c. Inputs in place
- [ ] Stock PRD copied: `cp "v18 test runs/TASKFLOW_MINI_PRD.md" /c/smoke/clean/PRD.md`.
- [ ] Stock config copied: `cp "v18 test runs/configs/taskflow-smoke-test-config.yaml" /c/smoke/clean/config.yaml`.
- [ ] Open `/c/smoke/clean/config.yaml` and confirm `model: claude-sonnet-4-6` (or equivalent stock Sonnet value). The Session plan specifies Sonnet; any Opus override defeats the purpose.
- [ ] Confirm feature flags in config.yaml if explicitly set:
  - `v18.milestone_scope_enforcement: true` (A-09) — default is true, leave unset OR explicit-true.
  - `v18.audit_milestone_scoping: true` (C-01) — same.
  - `v18.review_fleet_enforcement: true` (D-04) — same.
  - `v18.recovery_prompt_isolation: true` (D-05) — same.
  - `v18.m1_startup_probe: true` (D-20) — same.
  - These are the five new flags across Sessions 1/3/4. All default ON. If any was explicitly set to `false` in a prior stock config, flip to `true` or remove the override.

### 0d. Preservation target prepared
- [ ] Create `v18 test runs/build-k-gate-a-20260416/` directory. At end of run (pass OR fail), artefacts go there.

If any check fails, halt and report what failed. Do NOT launch a smoke with half-prepared environment — the $10 will be wasted.

---

## 1. Launch procedure

From `C:/smoke/clean/`:

```
cd /c/smoke/clean
python -m agent_team_v15.cli run PRD.md --config config.yaml --depth exhaustive 2>&1 | tee BUILD_LOG.txt
```

Notes on the command:
- `--depth exhaustive` — matches build-j's depth. Shallower depths skip waves that Session 6 needs to exercise.
- `tee BUILD_LOG.txt` — captures the full run to a local file that gets preserved with the artefacts.
- Do NOT pass `--coordinated` — the tracker specifically calls for a lightweight single-milestone smoke.

**Launch command exits** either on success (final phase `complete`, M1 clears) or on failure (watchdog fire, wedge, compile exhaustion, or explicit failure from a gate). Either way, process the post-run artefacts per §3 below.

---

## 2. Monitoring during the run

You do NOT need to watch live. The pipeline self-contains its telemetry. Key checkpoints to grep for in `BUILD_LOG.txt` if you want progress signals:

- **Wave A started / completed** — schema / foundation (~2–3 min, Claude).
- **Wave B started / completed** — backend (~15–35 min, codex-routed per config).
- **Wave C started / completed** — contracts (~1 min, python).
- **Wave D started / completed** — frontend (~15–30 min, codex-routed).
- **Wave T started / completed** — test / trace (Claude).
- **Wave E started / completed** — evidence / audit.
- `Audit cycle 1 for milestone-1` — audit phase starting.
- `M1 startup probe: npm install (...)` — D-20 firing.

If the process goes quiet (no new log lines) for >30 min without a watchdog message, something's wedged. The PR #11 orphan-tool watchdog should fire at 600s idle for Wave B/D. The session-level watchdog fires at 1800s. If neither fires and the process just sits there, `kill` the process — there's a new wedge class to investigate.

**Do not intervene during the run unless a watchdog should have fired and didn't.** False-positive interventions corrupt the test.

---

## 3. Post-run artefact capture

Whether pass or fail, immediately preserve:

```
mkdir -p "v18 test runs/build-k-gate-a-20260416"
cp /c/smoke/clean/BUILD_LOG.txt "v18 test runs/build-k-gate-a-20260416/"
cp /c/smoke/clean/PRD.md "v18 test runs/build-k-gate-a-20260416/"
cp /c/smoke/clean/config.yaml "v18 test runs/build-k-gate-a-20260416/"
cp -r /c/smoke/clean/.agent-team "v18 test runs/build-k-gate-a-20260416/"
# Source trees: exclude heavy derivables to keep preservation under 100MB
rsync -a --exclude node_modules --exclude .next --exclude dist \
  /c/smoke/clean/apps "v18 test runs/build-k-gate-a-20260416/" 2>/dev/null || \
  cp -r /c/smoke/clean/apps "v18 test runs/build-k-gate-a-20260416/"
# (repeat for packages/ and contracts/ if present)
```

Artefacts stay untracked per the reference-runs convention.

---

## 4. Pass criteria (M1 clears)

All of the following must be true after the run. If any one fails, the smoke did NOT clear M1.

### 4a. Run reaches `complete`
- [ ] `.agent-team/STATE.json` → `current_phase: "complete"`.
- [ ] `failed_milestones: []` (empty, not `["milestone-1"]`).
- [ ] `summary.success: true` AND consistent with `failed_milestones=[]` (D-13 State.finalize reconciliation holds).

### 4b. Audit finds ≤ 5 findings (scoped to M1)
- [ ] `.agent-team/AUDIT_REPORT.json` parses cleanly with `AuditReport.from_json` — no `audit_id` KeyError (D-07).
- [ ] `finding_counts.total ≤ 5`.
- [ ] `scope.milestone_id == "milestone-1"` (C-01 scope block populated).
- [ ] No finding on files outside `scope.allowed_file_globs` except consolidated `scope_violation` entries (which don't deduct score).

### 4c. M1 startup AC probe all-pass
- [ ] `.agent-team/AUDIT_REPORT.json.acceptance_tests.m1_startup_probe` present (D-20).
- [ ] Every sub-probe (`npm_install`, `compose_up`, `prisma_migrate`, `test_api`, `test_web`) has `status: "pass"` and `exit_code: 0`.

### 4d. Truth score healthy
- [ ] `.agent-team/STATE.json.truth_scores.requirement_coverage ≥ 0.85`.
- [ ] `truth_scores.overall ≥ 0.85` (ideally).

### 4e. Deterministic artefacts present
- [ ] `.agent-team/CONTRACTS.json` exists AND log shows `Contract generation: primary` (D-08), not `recovery-fallback`.
- [ ] `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json` exists AND is either real Wave T output OR has a structured `wave_t_status: "skipped"` with a reason (D-11).
- [ ] `.agent-team/GATE_FINDINGS.json` exists AND shows `review_cycles > 0` OR the run's gate5_enforcement / recovery handled it without the D-04 invariant firing.

### 4f. No silent degradations in the log
- [ ] Grep `BUILD_LOG.txt` for forbidden strings:
  - `Review fleet was never deployed` — MUST NOT appear (D-04).
  - `CONTRACTS.json not found after orchestration` — MUST NOT appear (D-08 primary producer ran).
  - `prompt injection attempt` — MUST NOT appear (D-05 isolation).
  - `Unknown recovery type` — MUST NOT appear (D-06 taxonomy complete).
  - `WinError 2` — MUST NOT appear (D-03 launcher resolution).
  - `runtime verification skipped` — MUST NOT appear (D-02 should `block`, not `skip`, when compose missing).

**All 4a–4f must check green. One failure ⇒ smoke did not clear M1; move to §6 fail-path.**

---

## 5. Pass-path outcome

If all criteria in §4 pass:

1. **Record the win.** Write a short report `v18 test runs/build-k-gate-a-20260416/GATE_A_REPORT.md` with the run's total cost, duration, and a quoted pass-criteria checklist with ✓ on every item.
2. **Update the tracker.** In `docs/plans/2026-04-15-builder-reliability-tracker.md` §9 Session 6, mark status `PASS`. This is the first defensible "M1 clears" signal since 2026-04-12.
3. **Decide on master merge.** Two paths per tracker:
   - **Short path:** the minimum-viable subset is done. Proceed to Session 12 (full pipeline smoke M1–M6) then Session 13 (master merge). Skip Sessions 7–11.
   - **Full path:** continue Sessions 7–11 (compile-fix investigation, telemetry hygiene, Bug #20) as quality investment before final smoke.
   - This is a user judgment call. Default to short path unless there's a specific reason to invest more.
4. **Update memory.** Append Session 6's outcome + the chosen path forward to `project_v18_hardened_builder_state.md`.

---

## 6. Fail-path outcome

If any criterion fails:

1. **Capture everything first.** The preservation in §3 should already be done. Double-check hang reports if any: `.agent-team/hang_reports/*.json`.
2. **Classify the failure** using the 4a–4f checklist — which specific criterion failed? That pinpoints the Session cluster responsible:
   - 4a fail (no `complete` or inconsistent summary) → Session 3 (D-13 finalize) or upstream wave failure (Session 7 compile-fix territory).
   - 4b fail (>5 findings or bad scope) → Session 1 (A-09 / C-01). Re-check scope filter wiring.
   - 4c fail (startup probe) → Session 3 (D-20) or Session 2 (scaffold correctness A-01/A-02/A-07). Which specific AC failed tells you which.
   - 4d fail (truth score) → Session 8 (D-17 truth calibration — deferred item; may now be in the critical path).
   - 4e fail (missing deterministic artefact) → Session 4 (D-08 / D-11).
   - 4f fail (forbidden string in log) → the mentioned session/item. Most are structural fixes; if they didn't fire, the wiring is broken.
3. **Do NOT re-run immediately.** Re-running wastes budget. Open a focused investigation session, fix the root cause, re-run only after the fix lands and is unit-tested.
4. **Write the fail report.** `v18 test runs/build-k-gate-a-20260416/GATE_A_FAIL_REPORT.md` with: which criterion failed, evidence path, which session cluster owns the regression, proposed next action. Share with the reviewer (next conversation turn) before launching any remediation session.
5. **Update the tracker** — §9 Session 6 marked `FAIL attempt 1`. If a second smoke is needed after a fix, it's `build-l-gate-a-<date>` with its own report, not a reuse of build-k.

---

## 7. Decision: run now or wait?

The go/no-go is yours. Two considerations:

**Reasons to run now:**
- All five pre-Gate-A sessions merged cleanly.
- Unit tests prove every mechanism in isolation.
- Sessions 6's Gate A is the ONLY way to prove the mechanisms work end-to-end. Nothing we can add in unit-test land improves confidence further.
- Delay costs nothing in code quality but costs time.

**Reasons to delay:**
- If there are outstanding concerns about Session 5's partial D-02/D-09 wiring that you want to close before spending $10. (I assessed those as non-blockers for Gate A; if you disagree, we wire them first.)
- If budget/time this week is tight and a Gate A fail would leave no room for a second attempt.

My recommendation: **run now.** The mechanisms are as validated as they can be without real integration signal. Gate A either confirms M1 clears (we move to master merge in 1–2 sessions) or surfaces the specific regression, which is cheaper to know now than after more layered changes.

---

## 8. Reporting back after the run

Regardless of pass/fail, reply in the conversation with:

```
## Session 6 Gate A smoke report

### Run
- Slug: build-k-gate-a-20260416
- Start: <iso>
- End: <iso>
- Duration: <min>
- Total cost: $<amount>
- Exit: success | failure
- Preserved: v18 test runs/build-k-gate-a-20260416/

### Pass criteria (§4)
- [ ] 4a Run reaches complete + state consistent
- [ ] 4b Audit ≤5 findings, scoped
- [ ] 4c M1 startup-AC probe all-pass
- [ ] 4d Truth score ≥ 0.85
- [ ] 4e Deterministic artefacts present
- [ ] 4f No silent-degradation strings in log

### Result: PASS | FAIL

### If PASS: <which forward path — short or full>
### If FAIL: <which criterion, which session owns it, proposed next action>
```

Then paste to the reviewer for the next turn — approval of the pass-path plan, or directive on the fail-path next step.
