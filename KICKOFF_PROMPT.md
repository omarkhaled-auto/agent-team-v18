# TEST BUILD VERIFICATION SESSION

Copy everything below this line and paste it as your first message to a new Claude Code session.

---

## Your Mission

You are running a LIVE enterprise test build of agent-team-v15 and grading it against a **133-item verification checklist**. This is the definitive test that proves whether Features #1-#5 actually work in a real build. Every checklist item must be graded PASS, FAIL, or N/A with evidence from the actual build output.

## Step 1: Clean the test output and run the build

```bash
cd C:/Projects/agent-team-v15
rm -rf test_run/output && mkdir -p test_run/output
python -m agent_team_v15 --prd test_run/test_prd.md --cwd test_run/output --depth enterprise --model sonnet --config test_run/config.yaml 2>&1 | tee test_run/BUILD_LOG_V3.txt
```

**IMPORTANT**: Pipe the output to `BUILD_LOG_V3.txt` so you can search it afterward. The build will take several minutes and cost ~$25-30. Wait for it to complete fully.

## Step 2: Collect all evidence files

After the build completes, read these files (they contain the data you'll grade against):

1. **`test_run/BUILD_LOG_V3.txt`** — The complete build log. Search for `[TRUTH]`, `[HOOK]`, `[ROUTE]`, `[SKILL]`, `[GATE]`, `[REGRESSION]` prefixes.
2. **`test_run/output/.agent-team/STATE.json`** — Final run state. Check all fields.
3. **`test_run/output/.agent-team/AUDIT_REPORT.json`** — Audit findings and scores.
4. **`test_run/output/.agent-team/GATE_AUDIT.log`** — Gate pass/fail records.
5. **`test_run/output/.agent-team/TRUTH_SCORES.json`** — Truth score dimensions.
6. **`test_run/output/.agent-team/skills/coding_dept.md`** — Coding department skills (Feature #3.5).
7. **`test_run/output/.agent-team/skills/review_dept.md`** — Review department skills (Feature #3.5).
8. **`test_run/output/.agent-team/pattern_memory.db`** — SQLite pattern database (Feature #4). Open with: `python -c "import sqlite3; conn=sqlite3.connect('test_run/output/.agent-team/pattern_memory.db'); conn.row_factory=sqlite3.Row; print([dict(r) for r in conn.execute('SELECT * FROM build_patterns').fetchall()]); print([dict(r) for r in conn.execute('SELECT * FROM finding_patterns').fetchall()])"`.
9. **`test_run/output/.agent-team/REQUIREMENTS.md`** — Convergence tracking.
10. **`test_run/output/.agent-team/MASTER_PLAN.md`** — Architecture plan.

## Step 3: Grade EVERY item in the checklist

For each item, provide:
- **PASS** with specific evidence (log line, file content, field value)
- **FAIL** with what was expected vs what actually happened
- **N/A** with reason (e.g., "regression only applies on 2nd build")

### CONFIG LOADING (9 items)
- [ ] C1: Enterprise depth detected — search log for "enterprise" depth line
- [ ] C2: enterprise_mode.enabled = true — search log for enterprise mode banner
- [ ] C3: departments.enabled = true — search log for department creation
- [ ] C4: pseudocode.enabled = true — search log for pseudocode phase
- [ ] C5: gate_enforcement.enabled = true — search log for GATE_ entries
- [ ] C6: Model set to sonnet — search log for "Model: sonnet"
- [ ] C7: Interview skipped — log should NOT show interview prompts
- [ ] C8: hooks.enabled = true — search log for "[HOOK] Self-learning hooks initialized"
- [ ] C9: routing.enabled = true — search log for "[ROUTE] Task router initialized"

### ENTERPRISE MODE (7 items)
- [ ] E1: Enterprise mode banner displayed
- [ ] E2: Domain agents deployed
- [ ] E3: Ownership validation gate triggered, state.ownership_map_validated = true
- [ ] E4: Shared files scaffolded
- [ ] E5: Department model activated
- [ ] E6: Department teams created via TeamCreate
- [ ] E7: Managers spawned, state.manager_count > 0

### FEATURE #1: PSEUDOCODE STAGE (9 items)
- [ ] P1: Pseudocode-writer agent loaded (12 agents total)
- [ ] P2: SECTION 2.5 in orchestrator prompt
- [ ] P3: GATE 6 in orchestrator prompt
- [ ] P4: Pseudocode fleet deployed BEFORE coding
- [ ] P5: .agent-team/pseudocode/ directory created
- [ ] P6: PSEUDO_*.md files generated
- [ ] P7: Pseudocode reviewed before code generation
- [ ] P8: ST point 5 triggered
- [ ] P9: state.pseudocode_validated = true

### FEATURE #2: TRUTH SCORING (9 items)
- [ ] T1: TruthScorer instantiated, [TRUTH] Score logged — search log for "[TRUTH] Score:"
- [ ] T2: All 6 dimensions computed — check the dims line: requirement_coverage, contract_compliance, error_handling, type_safety, test_presence, security_patterns
- [ ] T3: Truth score logged after audit cycle
- [ ] T4: Regression detection runs (_check_regressions) — search for "[REGRESSION]"
- [ ] T5: state.previous_passing_acs populated — check STATE.json
- [ ] T6: Rollback suggestion logged on regression (N/A on first build if no regressions)
- [ ] T7: REGRESSION_LIMIT evaluated, corrective action on low score — search for "[TRUTH] Score X.XXX below threshold"
- [ ] T8: state.truth_scores populated with real data — check STATE.json truth_scores dict
- [ ] T9: state.regression_count tracked — check STATE.json

### FEATURE #3: AUTOMATED GATES (12 items)
- [ ] G1: GateEnforcer instantiated — search log for gate-related initialization
- [ ] G2: GATE_REQUIREMENTS fires — search log AND GATE_AUDIT.log
- [ ] G3: GATE_ARCHITECTURE fires
- [ ] G4: GATE_PSEUDOCODE fires
- [ ] G5: GATE_INDEPENDENT_REVIEW fires
- [ ] G6: GATE_CONVERGENCE fires
- [ ] G7: GATE_TRUTH_SCORE fires
- [ ] G8: GATE_E2E fires
- [ ] G9: GATE_AUDIT.log has entries for all gates that fired
- [ ] G10: state.gate_results populated — check STATE.json gate_results array
- [ ] G11: state.gates_passed > 0 — check STATE.json
- [ ] G12: First-run informational mode works (warn, not block) — pseudocode gate should WARN not crash

### CONVERGENCE LOOP (9 items)
- [ ] L1: REQUIREMENTS.md created — check file exists
- [ ] L2: Planning fleet deployed — search log
- [ ] L3: Architecture section added
- [ ] L4: Coding fleet deployed
- [ ] L5: Review fleet deployed
- [ ] L6: Review cycles > 0 — check state.convergence_cycles
- [ ] L7: Convergence ratio displayed
- [ ] L8: Debug fleet deployed (if items fail)
- [ ] L9: Escalation triggered (if items fail 3+ cycles)

### STATE PERSISTENCE (10 items)
- [ ] S1: STATE.json created — file exists
- [ ] S2: Contains pseudocode_validated
- [ ] S3: Contains truth_scores
- [ ] S4: Contains gate_results
- [ ] S5: Contains regression_count
- [ ] S6: Resume works from STATE.json (N/A — would need interrupted build)
- [ ] S7: Contains patterns_captured (Feature #4) — should be > 0 if hooks enabled
- [ ] S8: Contains patterns_retrieved (Feature #4) — 0 on first build, > 0 on second
- [ ] S9: Contains routing_decisions (Feature #5) — should have entries
- [ ] S10: Contains routing_tier_counts (Feature #5) — should have tier counts

### PRD PARSING (5 items)
- [ ] D1: Entities extracted — search log for entity extraction
- [ ] D2: State machines extracted
- [ ] D3: Business rules extracted
- [ ] D4: Events extracted
- [ ] D5: Domain model injected into prompts

### QUALITY & VERIFICATION (4 items)
- [ ] Q1: Spot checks run
- [ ] Q2: Contract verification runs
- [ ] Q3: Quality score computed
- [ ] Q4: No critical anti-patterns

### FEATURE #3.5: DEPARTMENT LEADER SKILLS (17 items)
- [ ] SK1: skills.py module exists — `python -c "from agent_team_v15.skills import update_skills_from_build, load_skills_for_department; print('OK')"`
- [ ] SK2: update_skills_from_build() reads AUDIT_REPORT.json, STATE truth_scores, GATE_AUDIT.log — verify by checking skill file content matches audit data
- [ ] SK3: .agent-team/skills/coding_dept.md created — file exists with Critical + High Priority + Quality Targets sections
- [ ] SK4: .agent-team/skills/review_dept.md created — file exists with Top Failure Modes + Weak Dimensions + Gate History
- [ ] SK5: Skill content injected into department prompt — search log for "CODING DEPARTMENT SKILLS (learned from previous builds)"
- [ ] SK6: [seen: N/M] counters — verify "Builds analyzed: 1" on first build. For second build verification, run the build twice and check "Builds analyzed: 2" and "[seen: 2/"
- [ ] SK7: Token budget — count words in skill files: `wc -w test_run/output/.agent-team/skills/coding_dept.md` then divide by 0.75, should be < 550
- [ ] SK8: Findings sorted by frequency — most-seen lessons appear first in each section
- [ ] SK9: First build works — no crash, skill files created fresh
- [ ] SK10: Backward compatible — if you remove skill files and re-run, no crash
- [ ] SK11: Enterprise mode — skills injected when departments enabled (check SK5)
- [ ] SK12: Standard mode — would need a separate --depth standard run to verify (N/A for enterprise test)
- [ ] SK13: [SKILL] log prefix — search log for "[SKILL] Department skills updated from build outcomes"
- [ ] SK14: Quality targets — check coding_dept.md Quality Targets section. Dimensions below 0.75 should appear. type_safety (1.0) should NOT appear.
- [ ] SK15: Gate history — check review_dept.md Gate History section. All gates from GATE_AUDIT.log should appear.
- [ ] SK16: Coordinated builder path — N/A for standard enterprise run (only fires in --coordinated mode)
- [ ] SK17: post_build hook calls skill update — if hooks enabled (H7 passes), check if [SKILL] appears AFTER [HOOK] post_build

### FEATURE #4: SELF-LEARNING HOOKS + PATTERN MEMORY (21 items)
- [ ] H1: HookRegistry loads — search log for "[HOOK]" lines
- [ ] H2: HooksConfig parsed — hooks.enabled should be true in this config
- [ ] H3: Hook init AFTER depth gating — "[HOOK] Self-learning hooks initialized" should appear AFTER depth/enterprise detection lines
- [ ] H4: pre_build fires — search log for "[HOOK] pre_build hooks executed"
- [ ] H5: post_orchestration fires — search log for "[HOOK] post_orchestration"
- [ ] H6: post_audit fires — search log for "[HOOK] post_audit"
- [ ] H7: post_build fires — search log for "[HOOK] post_build hooks executed"
- [ ] H8: pattern_memory.db created — `ls -la test_run/output/.agent-team/pattern_memory.db`
- [ ] H9: post_build calls skill update — [SKILL] should appear in log after [HOOK] post_build
- [ ] H10: build_patterns table has data — `python -c "import sqlite3; c=sqlite3.connect('test_run/output/.agent-team/pattern_memory.db'); print(c.execute('SELECT COUNT(*) FROM build_patterns').fetchone())"`
- [ ] H11: search_similar_builds works — N/A on first build (no prior patterns). Run second build to test.
- [ ] H12: finding_patterns occurrence — N/A on first build. Run second build.
- [ ] H13: weak_dimensions populated — `python -c "import sqlite3,json; c=sqlite3.connect('test_run/output/.agent-team/pattern_memory.db'); r=c.execute('SELECT weak_dimensions FROM build_patterns').fetchone(); print(json.loads(r[0]) if r else 'EMPTY')"` — should list dimensions < 0.7
- [ ] H14: DB persists — file exists on disk (not in-memory)
- [ ] H15: state.patterns_captured > 0 — check STATE.json
- [ ] H16: state.patterns_retrieved — 0 on first build (expected), > 0 on second build
- [ ] H17: Disabled mode — N/A (hooks are enabled in this test config)
- [ ] H18: Standard mode hooks — all 4 hook events (pre_build, post_orchestration, post_audit, post_build) present in log
- [ ] H19: Coordinated builder hook_registry — N/A for standard enterprise run
- [ ] H20: Direct skill update fallback — N/A (hooks enabled, so hook path is used)
- [ ] H21: Handler exceptions isolated — if any [HOOK] warning appears, build should still complete successfully

### FEATURE #5: 3-TIER MODEL ROUTING (15 items)
- [ ] R1: TaskRouter loads — search log for "[ROUTE]"
- [ ] R2: RoutingConfig parsed — routing.enabled should be true
- [ ] R3: 6 intents exist — `python -c "from agent_team_v15.task_router import _TIER1_INTENTS; print([i.name for i in _TIER1_INTENTS])"`
- [ ] R4: Tier 1 skips LLM — `python -c "from agent_team_v15.task_router import TaskRouter; r=TaskRouter(enabled=True,tier1_confidence_threshold=0.5); d=r.route('add types to params',code_context='function foo(x,y){}'); print(d.tier, d.model, d.transform_result)"` — tier=1, model=None
- [ ] R5: Tier 2 routing — `python -c "from agent_team_v15.task_router import TaskRouter; r=TaskRouter(enabled=True); d=r.route('add simple validation'); print(d.tier, d.model)"` — tier=2
- [ ] R6: Tier 3 routing — `python -c "from agent_team_v15.task_router import TaskRouter; r=TaskRouter(enabled=True); d=r.route('architect distributed microservice system with OAuth2 authentication'); print(d.tier, d.model)"` — tier=3, model=opus
- [ ] R7: [ROUTE] logged — search log for "[ROUTE] Tier 3: orchestrator" and "[ROUTE] Task router initialized"
- [ ] R8: Orchestrator NEVER downgraded — search log: "[ROUTE] Tier 3: orchestrator". The model should be the configured one (sonnet), never haiku.
- [ ] R9: Research routed — search log for "[ROUTE] Tier" with "research" (if tech research ran)
- [ ] R10: Summary logged — search log for "[ROUTE] Summary: Tier1="
- [ ] R11: state.routing_decisions — check STATE.json, should have entries with phase/tier/model/reason
- [ ] R12: state.routing_tier_counts — check STATE.json, should have "tier3": N
- [ ] R13: Disabled mode — N/A (routing enabled)
- [ ] R14: ComplexityAnalyzer range — verified by R4/R5/R6 commands above
- [ ] R15: Transforms work — verified by R4 command above (transform_result in output)

### CONFIG + STATE NEW FIELDS (6 items)
- [ ] CS1: hooks config parsed — verify by checking H2 and H3
- [ ] CS2: routing config parsed — verify by checking R2
- [ ] CS3: STATE.json has patterns_captured, patterns_retrieved — `python -c "import json; d=json.load(open('test_run/output/.agent-team/STATE.json')); print('patterns_captured:', d.get('patterns_captured'), 'patterns_retrieved:', d.get('patterns_retrieved'))"`
- [ ] CS4: STATE.json has routing_decisions, routing_tier_counts — `python -c "import json; d=json.load(open('test_run/output/.agent-team/STATE.json')); print('routing_decisions:', len(d.get('routing_decisions',[])), 'tier_counts:', d.get('routing_tier_counts'))"`
- [ ] CS5: Old state compat — `python -c "from agent_team_v15.state import load_state; s=load_state('test_run/output/.agent-team'); print('patterns_captured:', s.patterns_captured, 'routing_decisions:', len(s.routing_decisions))"` — should work even if fields were added after state was first created
- [ ] CS6: __init__.py exports — `python -c "import agent_team_v15; print([m for m in agent_team_v15.__all__ if m in ('skills','hooks','pattern_memory','task_router','complexity_analyzer')])"` — all 5 present

## Step 4: Write the verification report

Create `test_run/VERIFICATION_RESULTS_V3.md` with:

```markdown
# Verification Results V3 — Features #1-#5
**Date**: [today]
**Build command**: python -m agent_team_v15 --prd test_run/test_prd.md --cwd test_run/output --depth enterprise --model sonnet --config test_run/config.yaml
**Build cost**: $[X.XX]
**Build duration**: [X minutes]

## Summary
- Total items: 133
- PASS: [N]
- FAIL: [N]
- N/A: [N]
- Pass rate: [N]% (excluding N/A)

## Detailed Results
[Every item with PASS/FAIL/N/A and evidence]

## Critical Failures
[List any FAIL items that indicate a feature is broken]

## Value Assessment
For each feature, answer: "Does this feature deliver its intended value based on the build evidence?"
- Feature #1 (Pseudocode): [assessment]
- Feature #2 (Truth Scoring): [assessment]
- Feature #3 (Gates): [assessment]
- Feature #3.5 (Skills): [assessment]
- Feature #4 (Hooks + Patterns): [assessment]
- Feature #5 (Routing): [assessment]
```

## Step 5: If this is a SECOND build (optional but high value)

If time/budget allows, run the build AGAIN on the same output directory WITHOUT cleaning:

```bash
python -m agent_team_v15 --prd test_run/test_prd.md --cwd test_run/output --depth enterprise --model sonnet --config test_run/config.yaml 2>&1 | tee test_run/BUILD_LOG_V3_RUN2.txt
```

This second run is critical for verifying:
- SK6: [seen: 2/2] counters increment in skill files
- H11: search_similar_builds finds the first build's pattern
- H12: finding_patterns occurrence_count > 1
- H16: state.patterns_retrieved > 0 (patterns from run 1 found in run 2)
- The self-learning loop actually improves build quality

Grade the second run's items and add them to the verification report.

## Key Things to Watch For

1. **[HOOK] lines** — These prove Feature #4 is alive. If you see ZERO [HOOK] lines, the hooks failed to initialize.
2. **[ROUTE] lines** — These prove Feature #5 is active. The orchestrator MUST say "Tier 3" and use sonnet.
3. **[SKILL] lines** — These prove Feature #3.5 is working. Skill files should appear in .agent-team/skills/.
4. **[TRUTH] lines** — These prove Feature #2 is scoring quality. All 6 dimensions should be computed.
5. **GATE_AUDIT.log** — This proves Feature #3 is enforcing gates. Multiple gate entries expected.
6. **pattern_memory.db** — This proves Feature #4's storage works. Should have data after build.
7. **STATE.json** — This is the definitive record. ALL new fields should be populated.

## Reference Files

- **Full handoff document**: `C:/Projects/agent-team-v15/HANDOFF_DOCUMENT.md` — Section 8 has the full checklist with descriptions
- **Test PRD**: `C:/Projects/agent-team-v15/test_run/test_prd.md`
- **Test config**: `C:/Projects/agent-team-v15/test_run/config.yaml` — has ALL features enabled
- **Previous V2 results**: `C:/Projects/agent-team-v15/test_run/VERIFICATION_RESULTS_V2.md` — scored 46/68 on Features #1-#3
- **Previous V2 build log**: `C:/Projects/agent-team-v15/test_run/BUILD_LOG_V2.txt`
