# VERIFICATION CHECKLIST — Enterprise Test Run

## CONFIG LOADING
- [ ] C1: Enterprise depth detected (not auto-detected, forced via config)
- [ ] C2: enterprise_mode.enabled = true loaded
- [ ] C3: departments.enabled = true loaded
- [ ] C4: pseudocode.enabled = true loaded
- [ ] C5: gate_enforcement.enabled = true loaded
- [ ] C6: Model set to sonnet (not opus)
- [ ] C7: Interview skipped (enabled: false)

## ENTERPRISE MODE
- [ ] E1: Enterprise mode banner/message displayed
- [ ] E2: Domain agents deployed (backend, frontend, infra)
- [ ] E3: Ownership validation gate triggered
- [ ] E4: Shared files scaffolded
- [ ] E5: Department model activated (coding dept + review dept)
- [ ] E6: Department team(s) created via TeamCreate
- [ ] E7: Managers spawned within departments

## FEATURE #1: PSEUDOCODE STAGE
- [ ] P1: Pseudocode-writer agent definition loaded (12 agents total, not 11)
- [ ] P2: SECTION 2.5 (Pseudocode Validation Phase) in orchestrator prompt
- [ ] P3: GATE 6 (Pseudocode Validation) in orchestrator prompt
- [ ] P4: Pseudocode fleet deployed BEFORE coding fleet
- [ ] P5: .agent-team/pseudocode/ directory created
- [ ] P6: PSEUDO_*.md files generated for tasks
- [ ] P7: Pseudocode reviewed by architect before code generation
- [ ] P8: ST point 5 (Pseudocode Review) triggered (if depth supports it)
- [ ] P9: state.pseudocode_validated set to true after validation

## FEATURE #2: TRUTH SCORING
- [ ] T1: TruthScorer class instantiated during audit
- [ ] T2: TruthScore computed with 6 dimensions
- [ ] T3: Truth score logged after each audit cycle
- [ ] T4: Regression detection runs (_check_regressions)
- [ ] T5: Previously-passing ACs tracked in state.previous_passing_acs
- [ ] T6: Rollback suggestion logged when regression detected (if any)
- [ ] T7: REGRESSION_LIMIT stop condition evaluated
- [ ] T8: state.truth_scores populated
- [ ] T9: state.regression_count tracked

## FEATURE #3: AUTOMATED GATES
- [ ] G1: GateEnforcer instantiated in cli.py
- [ ] G2: GATE_REQUIREMENTS checked (before milestones/architecture)
- [ ] G3: GATE_ARCHITECTURE checked (before task assignment)
- [ ] G4: GATE_PSEUDOCODE checked (before coding — informational or enforcing)
- [ ] G5: GATE_INDEPENDENT_REVIEW checked (after review cycles)
- [ ] G6: GATE_CONVERGENCE checked (before E2E)
- [ ] G7: GATE_TRUTH_SCORE checked (before declaring complete)
- [ ] G8: GATE_E2E checked (before declaring complete)
- [ ] G9: .agent-team/GATE_AUDIT.log created with entries
- [ ] G10: state.gate_results populated
- [ ] G11: state.gates_passed > 0
- [ ] G12: First-run informational mode works (warn, not block on first gate)

## CONVERGENCE LOOP
- [ ] L1: REQUIREMENTS.md created in .agent-team/
- [ ] L2: Planning fleet deployed
- [ ] L3: Architecture section added to REQUIREMENTS.md
- [ ] L4: Coding fleet deployed
- [ ] L5: Review fleet deployed (adversarial)
- [ ] L6: Review cycles tracked (review_cycles > 0)
- [ ] L7: Convergence ratio computed and displayed
- [ ] L8: Debugging fleet deployed (if items fail)
- [ ] L9: Escalation triggered (if items fail 3+ cycles)

## STATE PERSISTENCE
- [ ] S1: .agent-team/STATE.json created
- [ ] S2: STATE.json contains pseudocode_validated field
- [ ] S3: STATE.json contains truth_scores field
- [ ] S4: STATE.json contains gate_results field
- [ ] S5: STATE.json contains regression_count field
- [ ] S6: Run can be resumed from STATE.json (if interrupted)

## PRD PARSING
- [ ] D1: Entities extracted (User, Task)
- [ ] D2: State machines extracted (Task: PENDING->IN_PROGRESS->DONE)
- [ ] D3: Business rules extracted (BR-001 through BR-005)
- [ ] D4: Events extracted (user.registered, task.created, task.status_changed)
- [ ] D5: Domain model injected into agent prompts

## QUALITY & VERIFICATION
- [ ] Q1: Spot checks run on generated code
- [ ] Q2: Contract verification runs
- [ ] Q3: Quality score computed
- [ ] Q4: No critical anti-patterns detected (or flagged)
