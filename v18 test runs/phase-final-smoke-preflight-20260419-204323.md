# Phase FINAL Smoke — Pre-Flight Checklist & Verification Artifact

**Captured:** 2026-04-19 20:43:23 local
**Branch under test:** `integration-2026-04-15-closeout`
**HEAD at preflight capture:** `635a2a6` (pushed to `origin/integration-2026-04-15-closeout`)
**Target smoke:** `#12` — first paid smoke after h1a + h1b structural hardening

---

## Commit chain being smoked

```
635a2a6  Post-H1b: update walker-sweep allow-list line for cli.py rglob site
8ca6aa6  Merge branch 'phase-h1b-wave-a-architecture-md-schema' into integration-2026-04-15-closeout
dd18ea2  Phase H1b: Wave A schema gate + auditor three-way compare + structured emission
d2ce167  Phase H1a: compose ownership + downstream enforcement (#42)
b77fca0  Pre-H1a hygiene: gitignore smoke scratch + add plan/config docs (#41)
```

## Pre-Smoke Structural Validation (verified NOW, at preflight-capture time)

| # | Check | Result | Evidence |
|---|---|---|---|
| 0a | Branch chain integrity | ✅ | `git log --oneline -5` shown above |
| 0b | Full pytest on integration HEAD | ✅ **11,192 passed / 35 skipped / 0 failed** | 7m46s runtime; captured at `v18 test runs/phase-h1b-validation/pytest-output-post-fix.txt` for the pre-rewrite baseline. Re-run this turn on `635a2a6` produced identical pass count. |
| 0c | Integration branch pushed to origin | ✅ `d2ce167..635a2a6` | `git push` landed cleanly; remote now at `635a2a6` |
| 0d | Plan-interpretation decisions documented | ✅ 4 decisions in `docs/plans/phase-h1b-report.md` §"Documented Plan-Interpretation Decisions" (WAVE_A_SCHEMA_REVIEW.json mirror; consumer-site structured emission; Option 2 rerun budget; function-attribute dedupe) | — |
| 0e | 9 production-caller proofs captured | ✅ | `ls v18 test runs/phase-h1b-validation/` shows proof-01 through proof-09 + 3 pytest output files |
| 0f | No uncommitted work in the smoking branch | ✅ | `git status --short` shows only unrelated `ProjectsArkanPM_Websitepublicimagesgenerated/` untracked (unrelated to h1b; documented as local noise) |

## Pre-Flight Checklist (TO VERIFY AT SMOKE INVOCATION TIME)

> These are **not** verifiable until the smoke-config YAML and target PRD are chosen. The operator runs these immediately before firing the smoke and pastes results below each item.

### 1. Smoke branch fetched at the pushed HEAD

```bash
git fetch origin && git checkout integration-2026-04-15-closeout && git rev-parse HEAD
# Expected: 635a2a65ae2fa2414de441f73ce0766662c1e5c4
```

**Result:** _[paste actual SHA here at smoke time]_

### 2. All 7 h1a + h1b flags present AND `true` in the smoke config

```bash
rg 'wave_a_schema_enforcement_enabled|auditor_architecture_injection_enabled|wave_a_rerun_budget|dod_feasibility_verifier_enabled|ownership_enforcement_enabled|probe_spec_oracle_enabled|runtime_tautology_guard_enabled' <smoke-config.yaml>
```

**Expected:** 7 matches, each with `: true` (except `wave_a_rerun_budget: 2` which is an int, not a bool).

**Result:** _[paste actual rg output at smoke time]_

### 3. `architecture_md_enabled: true` must be present

`wave_a_schema_enforcement_enabled=true` is a silent no-op unless `architecture_md_enabled=true`. Verify:

```bash
rg 'architecture_md_enabled' <smoke-config.yaml>
```

**Expected:** `architecture_md_enabled: true`

**Result:** _[paste at smoke time]_

### 4. Codex transport mode = "exec" (NOT app-server; Bug #20 deferred to H2)

```bash
rg 'codex_transport_mode' <smoke-config.yaml>
```

**Expected:** `codex_transport_mode: "exec"` (literal string, quotes optional)

**Result:** _[paste at smoke time]_

### 5. PRD has real M1 scope: ≥4 entities AND ≥6 ACs

A.5's skip condition is `entities<3 AND acs<5`; shipping with exactly `3/5` lands on the boundary and makes attribution ambiguous when something surfaces. Target ≥4 entities AND ≥6 ACs for headroom.

Inspect the chosen PRD's M1 block (usually in `docs/PRD.md` or similar; grep the first `# Milestone 1` section for `- entity:` or `- AC-` markers):

```bash
# Count entities in M1
grep -A 200 '^# Milestone 1' <PRD.md> | grep -c '^- entity:'
# Count ACs in M1
grep -A 200 '^# Milestone 1' <PRD.md> | grep -c '^- AC-'
```

(Exact grep patterns depend on your PRD format; adjust accordingly.)

**Expected:** entities ≥4; ACs ≥6.

**Result:** _[paste counts at smoke time]_

### 6. `codex` binary on PATH AND auth present

```bash
command -v codex && codex --version
```

AND one of the following auth paths:

```bash
# Either: Codex auth JSON exists and parses
test -f ~/.codex/auth.json && python -c "import json; json.load(open(f\"{__import__('os').path.expanduser('~')}/.codex/auth.json\"))" && echo OK

# Or: OPENAI_API_KEY set
echo "$OPENAI_API_KEY" | head -c 8
```

**Result:** _[paste at smoke time]_

### 7. Editable install points at the smoking worktree

```bash
pip show agent-team-v15 | grep -i location
```

**Expected:** `Location: .../agent-team-v18-codex` (not a stale install pointing at another directory)

**Result:** _[paste at smoke time]_

### 8. Host ports free AND no stale smoke containers

```bash
# Ports that the stock PRD's apps expect
ss -tln | grep -E '(:5432|:5433|:3080)\b' || echo "PORTS FREE"
# Stale containers from prior smokes
docker ps -a --format '{{.Names}}' | grep '^clean-' || echo "NO STALE"
```

**Expected:** `PORTS FREE` and `NO STALE`.

**Result:** _[paste at smoke time]_

### 9. pytest baseline on the smoking branch

```bash
pytest tests/ -q 2>&1 | tail -3
```

**Expected:** `11192 passed, 35 skipped, 0 failed`.

**Result:** _[paste at smoke time]_

### 10. Baseline artifact capture directory ready

Create the directory that will hold post-smoke artifacts for later H2 delta measurement:

```bash
mkdir -p "v18 test runs/phase-final-smoke-baseline"
# Post-smoke, this will contain:
#   AUDIT_REPORT.json                 — final audit for delta vs H2's re-smoke
#   FIX_CYCLE_LOG.md                  — fix dispatch cadence
#   pattern_histogram.json            — jq '.findings | group_by(.finding_id) | map({code: .[0].finding_id, count: length})' AUDIT_REPORT.json > pattern_histogram.json
#   smoke_summary.md                  — verdict scored against PHASE_FINAL_EXIT_CRITERIA.md tiers
#   ARCHITECTURE.md (per milestone)   — for inspecting what h1b's schema gate let through / rejected
#   WAVE_A_SCHEMA_REVIEW.json         — per milestone; shape of any rejections the gate emitted
```

**Result:** _[confirm at smoke time]_

---

## What the smoke will exercise (feature-by-feature)

| Feature | Trigger Condition | Expected Behavior | Pattern IDs It Can Emit |
|---|---|---|---|
| Wave A schema gate (h1b) | `wave_a_schema_enforcement_enabled=true` + ARCHITECTURE.md present | Allowlisted sections only; fabricated refs rejected; retry via `[PRIOR ATTEMPT REJECTED]` up to `wave_a_rerun_budget` (default 2); `GateEnforcementError(gate="A-SCHEMA")` on exhaustion | `WAVE-A-SCHEMA-REJECTION-001` (HIGH), `WAVE-A-SCHEMA-UNDECLARED-REF-001` (MEDIUM), `WAVE-A-SCHEMA-REFERENCE-001` (HIGH, derivability — smoke #11's `PORT ?? 8080` class) |
| Auditor three-way compare (h1b) | `auditor_architecture_injection_enabled=true` + auditor ∈ {interface, technical} + per-milestone ARCHITECTURE.md exists | `<architecture>` block + `<three_way_compare>` directive prepended to interface/technical auditor prompts; 2-of-3-disagree findings emitted into AUDIT_REPORT.json `findings[]` with pattern ID in `summary` | `ARCH-DRIFT-{PORT,ENTITY,ENDPOINT,CREDS,DEPS}-001` (all HIGH) |
| Structured h1a finding emission (h1b, unflagged) | Always | `SCAFFOLD-COMPOSE-001` + `SCAFFOLD-PORT-002` from `_scaffold_summary_to_findings`; `PROBE-SPEC-DRIFT-001` from `_probe_startup_error_to_finding`; `RUNTIME-TAUTOLOGY-001` from `_cli_gate_violations.append` → flow into `GATE_FINDINGS.json` / `WaveResult.findings` / audit pipeline as structured objects | (same codes; now structured, not summary-string) |
| h1a: DoD feasibility (h1a) | `dod_feasibility_verifier_enabled=true` | DoD health-URL / port consistency check | `DOD-FEASIBILITY-001` |
| h1a: Ownership enforcement (h1a) | `ownership_enforcement_enabled=true` | SCAFFOLD_OWNERSHIP.md respected; Wave B/etc can't mutate scaffold-owned files | `OWNERSHIP-DRIFT-001`, `OWNERSHIP-WAVE-A-FORBIDDEN-001` |
| h1a: Probe spec oracle (h1a) | `probe_spec_oracle_enabled=true` | Endpoint probes check spec-oracle before marking wave pass | `PROBE-SPEC-DRIFT-001` |
| h1a: Runtime tautology guard (h1a) | `runtime_tautology_guard_enabled=true` | Post-all-milestone compose+api health check | `RUNTIME-TAUTOLOGY-001` |
| Shared rerun budget (h1b) | Both gates share `wave_a_rerun_budget` counter | Schema + stack-contract + A.5 reruns all decrement same counter; `GateEnforcementError` on first exhaustion across any gate | (uses existing gate error types) |

---

## Scoring Framework (post-smoke)

Per `PHASE_FINAL_EXIT_CRITERIA.md` tiers:

- **MUST-PASS** (any ❌ = smoke fails): `#1` all M1-M6 PASS; `#12` Wave T ran ≥1; `#3` audit_health=passed per milestone
- **SHOULD-PASS** (≥80% required): `#4, #5, #6, #7, #8, #9, #10, #11`
- **MAY-PASS** (❌ acceptable with documented reason): `#13` Codex app-server (Bug #20 deferred — ❌ expected); `#14` post-Wave-E scanners; `#15` UI_DESIGN_TOKENS via D.5; `#17` orphan/wedge (zero firings OK if zero wedges)

**Pattern-ID histogram (required post-smoke):** `jq '.findings | group_by(.finding_id) | map({code: .[0].finding_id, count: length}) | sort_by(-.count)' AUDIT_REPORT.json` → save to `pattern_histogram.json` in baseline directory. Enables delta measurement against the H2 re-smoke after Bug #20 lands.

---

## Cancel Conditions (do NOT fire the smoke if ANY of these)

- pytest baseline on smoking branch is not 11,192 passed
- any of the 7 flags is absent or `false` in the smoke config
- `architecture_md_enabled` is not `true`
- PRD M1 has <3 entities OR <5 ACs (A.5 skip territory; smoke would validate nothing)
- `codex` binary missing or `auth.json` fails to parse AND `$OPENAI_API_KEY` unset
- Editable install points at a different worktree than the smoking branch
- Ports 5432/5433/3080 already bound OR stale `clean-*` containers present
- Any git dirty state that could confuse attribution post-smoke

---

## Known Honest ❌ expected in this smoke

- `#13 Codex app-server` — **expected ❌**; Bug #20 deferred to H2. The smoke must run with `codex_transport_mode: "exec"` (legacy subprocess) to avoid this. Document as honest failure with Bug #20 reference in smoke_summary.md.
- `#15 UI_DESIGN_TOKENS consumed by D.5` — ❌ acceptable IF Wave D didn't run on any milestone (depends on PRD scope).
- `#17 orphan detection / wedge recovery` — zero firings acceptable; only triggers on actual wedges.

Do NOT let "12/20 with documented reasons for the 8" become "we failed" — PHASE_FINAL_EXIT_CRITERIA.md's tiered gating exists exactly for this nuance.

---

## References

- Phase H1b final report: `docs/plans/phase-h1b-report.md`
- Phase H1b production-caller proofs (9): `v18 test runs/phase-h1b-validation/proof-01…09-*.md`
- Phase H1b wiring verification: `docs/plans/phase-h1b-wiring-verification.md`
- Phase FINAL exit criteria tiers: `PHASE_FINAL_EXIT_CRITERIA.md`
- Memory entries applying to this smoke:
  - `feedback_verify_editable_install_before_smoke.md` (pre-flight discipline)
  - `feedback_verification_before_completion.md` (unit tests don't substitute for end-to-end)
  - `feedback_inflight_fixes_need_authorization.md` (no in-flight code fixes mid-smoke)
  - `feedback_verify_proof_inventory_on_disk.md` (disk-verify artifacts after smoke too)
