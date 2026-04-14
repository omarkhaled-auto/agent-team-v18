# V18 Hardened Pipeline Smoke Test - Re-Run Handoff (2026-04-14)

> For a fresh Claude Code session. Read this brief top-to-bottom before doing anything. The first smoke test ran on 2026-04-13 and is fully documented; this is the re-run with the original fixes, Tier 2 stack-contract enforcement, and pre-rerun cleanup closures in place.

---

## 1. Background - why you're doing this

Yesterday's 7-attempt smoke-test session on the V18.1 hardened builder discovered 11 bugs (10 real + 1 misdiagnosis) and verified 18 of 30 checklist items. The re-run should start from a materially cleaner baseline: the original 7 fixes are in, Bug #9 Tier 1 and Tier 2 landed on this branch, and the final pre-rerun cleanup closed the remaining Bug #2, Bug #8, and Bug #10 gaps.

### Branch state to assume

- Tier 2 stack-contract work is already on this branch via `64cf3f1`, `0cde844`, `76a8fa6`, `cdd7b83`.
- Final pre-rerun cleanup landed in:
  - `b57cb43` - Bug #2 hyphenated `m-1` regression fix
  - `266e9ab` - Bug #8 `package.json` OpenAPI wiring completion
  - `78907b8` - Bug #10 watchdog ratification note in the plan

### Full context documents (required reading, in this order)

1. `docs/plans/2026-04-13-v18-smoke-test-bugs-index.md` - master index of all 11 bugs + status
2. `docs/plans/2026-04-13-in-tree-fixes-summary.md` - the original 6 in-tree fixes (#1, #2, #4a, #4b, #6, #7) with diffs + verification notes
3. `docs/plans/2026-04-13-stack-contract-enforcement-plan.md` - Bug #9 plan; Tier 1 and Tier 2 are landed on this branch
4. `docs/plans/2026-04-13-wave-d5-silent-hang-plan.md` - Bug #10 plan; now includes a post-ratification implementation note for the landed watchdog
5. `docs/plans/2026-04-13-codex-output-hallucinations-plan.md` - Bug #11; still likely open
6. `v18 test runs/build-c-hardened-clean/FINAL_COMPARISON_REPORT.md` - yesterday's full report + 30-item checklist + comparison table

### Bugs you should EXPECT to be fixed in the code when you run

- `#1` path/cwd double-prefix in tsc compile (`compile_profiles.py`)
- `#2` plan validator accepts prose filtering and hyphenated `m-1` shorthand (`milestone_manager.py`)
- `#4a` `AUDIT_REPORT.json` double-nesting (`cli.py`)
- `#4b` `AuditFinding` accepts both schema shapes (`audit_models.py`)
- `#6` `CLAUDECODE` env pop at `cli.main()` (`cli.py`)
- `#7` operationId de-dupe across OpenAPI spec (`openapi_generator.py`)
- `#8` Nest scaffold wires `scripts.generate-openapi`, `tsx`, and `@nestjs/swagger` (`scaffold_runner.py`)
- `#9 Tier 1` parametrized stack instructions on ORM/layout (`agents.py`)
- `#9 Tier 2` stack-contract validator + telemetry plumbing (`stack_contract.py`, `wave_executor.py`, `state.py`)
- `#10` wave watchdog bounds silent hangs, writes hang evidence, and retries once (`wave_executor.py`, plan note)

### Bugs you should EXPECT to still be open

- `#5` PRD-vs-cwd location. Workaround: colocate PRD with the build dir; the clean path below already does this.
- `#11` Codex output hallucinations not caught by scanners. Do the manual Wave D review even if the run is otherwise healthy.

---

## 2. Pre-flight verification (do this before launching anything)

Run these from `C:\Projects\agent-team-v18-codex`:

```bash
# 1. Confirm venv points at this repo (not at C:\Projects\agent-team-v15)
/c/Projects/agent-team-v18-codex/.venv/Scripts/python.exe -c "import agent_team_v15; print(agent_team_v15.__file__)"
# Expected output: C:\Projects\agent-team-v18-codex\src\agent_team_v15\__init__.py
# If it shows a different path: run `pip install -e .` from this repo

# 2. Confirm the core fixes are present
grep -n "path.resolve" src/agent_team_v15/compile_profiles.py
grep -n "_id_form" src/agent_team_v15/milestone_manager.py
grep -n 'req_dir / ".agent-team"' src/agent_team_v15/cli.py
grep -n 'data.get("finding_id")' src/agent_team_v15/audit_models.py
grep -n 'pop("CLAUDECODE"' src/agent_team_v15/cli.py
grep -n "_unique_operation_name" src/agent_team_v15/openapi_generator.py
grep -n "_ensure_package_json_openapi_script\|_GENERATE_OPENAPI_SCRIPT\|@nestjs/swagger\|tsx" src/agent_team_v15/scaffold_runner.py

# 3. Confirm Bug #9 Tier 1 + Tier 2 are landed
grep -n "_typescript_nestjs_instructions\|def _typescript_nestjs" src/agent_team_v15/agents.py
grep -n "_BUILTIN_STACK_CONTRACTS\|class StackContract" src/agent_team_v15/stack_contract.py
grep -n "stack_contract_violations" src/agent_team_v15/wave_executor.py
grep -n "stack_contract" src/agent_team_v15/state.py

# 4. Confirm PRD + config exist where expected
ls -la "v18 test runs/TASKFLOW_MINI_PRD.md"
ls -la "v18 test runs/configs/taskflow-smoke-test-config.yaml"
```

Cleanup note: Bug #2 `m-1` regression resolved in `b57cb43`; Bug #8 `package.json` wiring completed in `266e9ab`; Bug #10 watchdog ratified per plan in `78907b8`.

If any of these fail, stop and report before proceeding.

---

## 3. Clean up yesterday's run

The re-run uses a clean path at `C:/smoke/clean/` to avoid the PRD-vs-cwd ambiguity (Bug #5 workaround). Clean and reset:

```bash
# Preserve yesterday's result as historical
ls "v18 test runs/build-c-hardened-clean/"

# Kill any leftover python processes from a prior run
wmic process where "name='python.exe'" get processid,commandline 2>&1 | grep -i "smoke"
# If you see any, kill them:
#   taskkill //F //PID <pid>

# Fully reset the working area
rm -rf /c/smoke
mkdir -p /c/smoke/clean

# Stage the PRD + config into the clean path
cp "v18 test runs/TASKFLOW_MINI_PRD.md" /c/smoke/clean/PRD.md
cp "v18 test runs/configs/taskflow-smoke-test-config.yaml" /c/smoke/clean/config.yaml

# Verify
ls -la /c/smoke/clean/
```

---

## 4. Launch command (exact - do not improvise)

```bash
cd /c/smoke/clean && /c/Projects/agent-team-v18-codex/.venv/Scripts/python.exe -m agent_team_v15 \
  --prd /c/smoke/clean/PRD.md \
  --config /c/smoke/clean/config.yaml \
  --cwd /c/smoke/clean \
  --depth exhaustive \
  --no-interview \
  --verbose 2>&1 | tee /c/smoke/clean/BUILD_LOG.txt
```

Notes:

- Use forward-slash paths (Git Bash on Windows).
- Launch as a background task so you can monitor while it runs.
- Expected total runtime: 2-4 hours if the pipeline fully clears.
- Budget cap: `$25` (per `config.yaml`).
- Do not kill the build unless the rules in Section 5 actually trigger.

---

## 5. Monitoring cadence

Follow this cadence:

| Elapsed | Action |
|---|---|
| ~2 min | Verify Phase 0 (codebase map, UI requirements, design tokens) completed |
| ~15 min | Verify Phase 1 PRD decomposition completed + plan validation passed |
| ~25 min | Verify Phase 1.5 tech stack research completed |
| ~30 min | Verify M1 Wave A telemetry landed with `compile_passed: true`, `provider: "claude"` |
| ~65 min | Verify M1 Wave B telemetry with `compile_passed: true`, `provider: "codex"`, `provider_model: "gpt-5.4"` |
| ~65 min | Verify M1 Wave C telemetry with `success: true`, 5-10 files |
| ~90 min | Verify M1 Wave D telemetry |
| ~105 min | Verify M1 Wave D5 telemetry or watchdog timeout/retry evidence |
| ~120 min | Verify M1 Wave T telemetry |
| ~135 min | Verify M1 Wave E telemetry |
| ~150 min | Verify M1 per-milestone audit ran + `AUDIT_REPORT.json` exists at the correct location |

### Check commands

```bash
# Quick status snapshot
date +"%H:%M:%S"
wc -l /c/smoke/clean/BUILD_LOG.txt
ls /c/smoke/clean/.agent-team/telemetry/ 2>&1
find /c/smoke/clean -type f -mmin -5 2>/dev/null | grep -v node_modules | wc -l

# Detailed wave progress
grep -nE "MILESTONE [0-9]/|compile_passed|Wave execution failed|Audit cycle|RECOVERY|Final |Wave T|Wave E|Wave D5|hang|timeout|retry" /c/smoke/clean/BUILD_LOG.txt | tail -20

# Read most recent wave telemetry
cat /c/smoke/clean/.agent-team/telemetry/milestone-1-wave-A.json
# ... repeat for B, C, D, D5, T, E as they land

# Process liveness
wmic process where "name='python.exe'" get processid,commandline 2>&1 | grep -ci "smoke"
```

### Watchdog note (Bug #10)

If 15+ minutes pass with 0 file modifications and no new log lines, treat it as suspicious, not yet automatically a confirmed regression.

```bash
find /c/smoke/clean -type f -mmin -5 2>/dev/null | grep -v node_modules | wc -l
wc -l /c/smoke/clean/BUILD_LOG.txt
```

Expected Bug #10 behavior now:

1. A genuinely stalled wave should trip the watchdog inside its configured timeout window, emit a hang report, and retry once.
2. A silent 80+ minute stall with no timeout handling is the regression case.
3. Only kill manually if the process stays silent past the watchdog window and no retry/report appears, or if both attempts wedge with no new artifacts.

### Stop-early rule

Kill the build the moment `milestone-1-wave-E.json` lands or `MILESTONE 2/5` appears in the log. M1 fully complete is sufficient data; M2-M5 are not required for this verification run.

---

## 6. Verify the fix outcomes (primary goal of this run)

As each phase or wave lands, verify the relevant fix actually worked:

| Wave completion | Fix(es) verified | What to check |
|---|---|---|
| Phase 1.5 research | `#6` CLAUDECODE pop | Log shows `Phase 1.5: Research complete - N/6 technologies covered` and no nested-Claude launch failure |
| Plan validation passes | `#2` dep-prose filter + `m-1` regression closure | `grep -E "depends on .* which does not exist" BUILD_LOG.txt` returns nothing |
| M1 Wave A completes | baseline | telemetry `success: true`, `provider: claude` |
| M1 Wave B completes | `#1` path fix | telemetry `compile_passed: true`, `provider: codex`, `provider_model: gpt-5.4`; if this fails with `TS5058`, Bug #1 regressed |
| Post-Wave-B scaffold output | `#8` OpenAPI scaffold wiring | generated `package.json` contains `scripts.generate-openapi`, `devDependencies.tsx`, and `dependencies.@nestjs/swagger` |
| Post-Wave-B DTO scan | baseline | log contains the DTO contract fix summary |
| M1 Wave C completes | `#7` operationId de-dupe | telemetry `success: true`; if this fails with duplicate operationIds, Bug #7 regressed |
| Any wave telemetry | `#9 Tier 2` stack-contract validator | `stack_contract_violations` is present in telemetry/state output and is empty for a healthy run |
| M1 Wave A, B, C artifacts | `#9 Tier 1` stack-aware generation | expect `prisma/schema.prisma`, not `*.entity.ts`; `TypeORM` references should be absent or very low |
| M1 Wave D completes | Codex quality bar | telemetry `success: true`, frontend uses `@project/api-client` |
| M1 Wave D5 completes or times out/retries | `#10` watchdog behavior | preferred outcome: `wave-D5.json` lands within 30 min; fallback acceptable outcome: watchdog emits timeout evidence and retries once; unacceptable outcome: silent 80+ min stall with no handling |
| M1 Wave T completes | new machinery | telemetry has `tests_written > 0`, `fix_iterations >= 0`, `tests_passed_final >= 0` |
| M1 Wave E completes | new machinery | telemetry shows scanner output counts; check log for wiring and contract-field scanners |
| M1 audit completes | `#4a`, `#4b` | `.agent-team/AUDIT_REPORT.json` exists at the expected location and no `finding_id` parse warning appears |

Keep a running tally: verified, regressed, or not exercised.

---

## 7. 30-item checklist

Yesterday we verified 18 of 30. The goal remains 24+ of 30. With Bug #10 now bounded by the watchdog, items 12-26 should be reachable unless a new regression appears.

Use the same checklist as yesterday:

```text
1. MASTER_PLAN.json exists and is canonical (not just .md)
2. Milestones are vertical slices (not layer-phased)
3. DAG execution order was logged at build start
4. Wave A produced a Schema Handoff block
5. Wave B compile passed
6. DTO-PROP-001 scanner ran post-Wave-B
7. DTO-CASE-001 scanner ran post-Wave-B
8. Wave C produced OpenAPI spec + structured client_manifest
9. Wave D compile passed
10. Wave D used generated client (not fetch/axios)
11. UI_DESIGN_TOKENS.json exists in .agent-team/
12. Wave D5 ran
13. Wave D5 did NOT break compilation
14. Wave T ran and wrote tests
15. Wave T core principle was in the prompt
16. Wave T fix loop ran
17. Wave T AC->test coverage matrix in handoff summary
18. Wave E ran Playwright test generation
19. Wave E wiring scanner ran (deterministic, post-LLM)
20. Wave E i18n scanner ran (deterministic, post-LLM)
21. Wave E UI compliance scanner ran (deterministic, post-LLM)
22. WIRING-CLIENT-001 check ran
23. CONTRACT-FIELD-001/002 scanner ran post-Wave-E
24. Evidence records exist at .agent-team/evidence/
25. WAVE_FINDINGS.json exists per milestone
26. Post-Wave-E npm test ran
27. Audit loop ran
28. Comprehensive auditor scored with evidence resources
29. Scorer reconciled WAVE_FINDINGS.json
30. Final score reported
30+. Total build completed without crash
```

---

## 8. Critical code-review step (after Wave D lands)

Yesterday's review of the Wave D output found 3-4 class issues that scanners did not catch. Do the same review:

```bash
# Backend + frontend should not mix in the same src/
find /c/smoke/clean/src -maxdepth 3 -name "*.module.ts" -o -name "*.controller.ts" -o -name "*.service.ts" 2>/dev/null | head -10
find /c/smoke/clean/src/app -name "page.tsx" -o -name "layout.tsx" 2>/dev/null | head -10

# Check the ORM actually used
grep -l "@Entity\|@PrimaryGeneratedColumn" /c/smoke/clean/src -r 2>/dev/null | head -3
ls /c/smoke/clean/prisma/ 2>&1

# Sample layout.tsx for Codex hallucinations
cat /c/smoke/clean/src/app/layout.tsx
```

Interpretation:

- If both Nest backend files and Next frontend files are mixed in one flat `src/`, Bug #9 did not hold.
- If `@Entity` files exist, TypeORM slipped back in.
- If `prisma/schema.prisma` exists, Tier 1 is behaving.
- Watch `layout.tsx` for bogus locales, invalid font subsets, or similar Bug #11 style hallucinations.

---

## 9. Preserve artifacts + produce the final report

When the build stops (Wave E completes, audit finishes, watchdog-handled failure, or budget cap):

```bash
DEST="v18 test runs/build-d-rerun-$(date +%Y%m%d)"
mkdir -p "$DEST"
cp -r /c/smoke/clean/.agent-team "$DEST/"
cp /c/smoke/clean/BUILD_LOG.txt "$DEST/"
cp /c/smoke/clean/PRD.md "$DEST/"
cp /c/smoke/clean/config.yaml "$DEST/"
cp /c/smoke/clean/package.json "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/src "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/contracts "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/packages "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/prisma "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/e2e "$DEST/" 2>/dev/null
cp -r /c/smoke/clean/tests "$DEST/" 2>/dev/null
```

### Required sections in the final report

1. TL;DR - did the pipeline complete M1, how many checklist items were verified, and which fixes were verified
2. Wave-by-wave results - duration, cost, provider, files, `compile_passed`, `success` per wave A through E + audit
3. Comparison table - add a new `Build D re-run` column next to Build A / Build B / Build C-original / Build C-clean
4. Fix verification matrix - one row per verified fix/closure (`#1`, `#2`, `#4a`, `#4b`, `#6`, `#7`, `#8`, `#9 Tier 1`, `#9 Tier 2`, `#10`)
5. 30-item checklist - updated
6. Any new bugs discovered - if the run surfaces a Bug #12+, file a new plan at `docs/plans/2026-04-14-<slug>.md`
7. Cumulative cost across all runs this day + lifetime
8. Recommended next steps

---

## 10. Guardrails

- Do not re-run the build if it has already completed the wave set you need. Preserve partial evidence.
- Do not edit source code during the run. Python import state and subprocess behavior can drift.
- Do not chase a new Bug #12 deeper than necessary. File a plan; do not implement it in this run.
- Budget cap is `$25` per run.
- Write the comparison report even if the run fails or the watchdog fires after retry.

---

## 11. Success criteria for this session

- [ ] Pre-flight check confirms the original fixes, cleanup closures, and Tier 2 sentinels are present
- [ ] Fresh run launched at `C:/smoke/clean/` with the exact command above
- [ ] Build monitored through completion or a watchdog-bounded failure
- [ ] Fix chain plus Tier 2 enforcement verified against actual run behavior with evidence captured
- [ ] Full artifacts preserved under `v18 test runs/build-d-rerun-<date>/`
- [ ] `FINAL_COMPARISON_REPORT.md` produced in that directory
- [ ] Updated 30-item checklist tally published
- [ ] Any new bugs filed as standalone plans if needed
- [ ] Bug #10 confirmed either fixed in practice or at least bounded by watchdog timeout/report/retry behavior

---

## 12. If you get stuck / unsure

Read these in order:

1. `docs/plans/2026-04-13-v18-smoke-test-bugs-index.md`
2. `v18 test runs/build-c-hardened-clean/FINAL_COMPARISON_REPORT.md`
3. `docs/plans/2026-04-13-in-tree-fixes-summary.md`
4. `v18 test runs/build-c-hardened-clean/BUILD_LOG.txt`

If still stuck after those four, report clearly what you tried and what is still ambiguous. Do not guess.

---

## 13. Expected outcome (prediction to falsify)

If the current branch state holds when you launch:

- Phase 0 -> Phase 1 -> Phase 1.5 complete cleanly
- M1 Waves A -> B -> C all pass
- Wave A output uses Prisma, not TypeORM, if Bug #9 Tier 1 holds
- Per-wave telemetry includes `stack_contract_violations`, and healthy waves keep it empty
- The scaffolded backend `package.json` includes the OpenAPI script wiring from Bug #8
- Wave D passes on first try
- Wave D5 either completes in 5-15 minutes or trips the watchdog inside its configured window and retries once
- If D5 completes, Wave T + Wave E + audit all run
- Final checklist tally lands around 24-28 of 30
- Total cost stays around `$15-25`

The failure mode to watch for now is narrower: if Wave D5 silently stalls for 80+ minutes with no timeout handling, Bug #10 regressed. Report what actually happened.
