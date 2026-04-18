# Session Validation Template (N-14)

Use this template for every implementation session to ensure production-caller proof.

---

## Pre-flight

- [ ] Branch state confirmed (HEAD SHA, parent branch)
- [ ] `pip show agent-team-v15` — editable install at current worktree
- [ ] `pytest tests/ -v --tb=short` — capture baseline (passed/failed/skipped counts)
- [ ] Pre-existing failures captured in `session-<X>-validation/preexisting-failures.txt`
- [ ] Fresh branch created from integration HEAD

## Architecture Discovery (Wave 1)

- [ ] Architecture report produced at `docs/plans/<date>-<phase>-architecture-report.md`
- [ ] All file:line references verified by Read/Grep (not plan citations)
- [ ] Context7 queries for every framework/library idiom (verbatim quotes)
- [ ] Sequential-thinking on critical decision points
- [ ] Edit coordination map for shared files (no overlap)
- [ ] Risk map per implementation agent
- [ ] HALT findings at report TOP (if any)

## HALT Point Review

- [ ] Team-lead verifies all HALT findings against source
- [ ] Architect deviations from plan — accept/reject with justification
- [ ] Authorization memo at `session-<X>-validation/halt-point-authorization.md`

## Implementation (Wave 2)

- [ ] Each agent's file ownership matches coordination map
- [ ] New feature flags default OFF (except where plan explicitly says ON)
- [ ] Flag-OFF path is byte-identical to pre-edit behavior
- [ ] Mid-flight HALT discipline: agents halt on problems, don't fix silently
- [ ] Syntax-check all modified files: `python -c "import ast; ast.parse(...)"`

## Tests (Wave 3)

- [ ] Test files cover every implementation item
- [ ] Flag ON/OFF test cases for every feature flag
- [ ] Build-l offline replay tests where applicable
- [ ] Assertive matchers, descriptive names
- [ ] No source code modified by test agent

## Wiring Verification (Wave 3)

- [ ] End-to-end trace of every change
- [ ] Default-flag behavior verified (pipeline identical to baseline + any ON-by-default features)
- [ ] Per-flag-ON verification
- [ ] Wiring verification report at `docs/plans/<date>-<phase>-wiring-verification.md`

## Full Test Suite (Wave 4)

- [ ] `pytest tests/ -v --tb=short` — full suite
- [ ] Baseline preserved (same passed count)
- [ ] Pre-existing failures unchanged (same names, same reasons)
- [ ] New tests all passing
- [ ] ZERO regressions
- [ ] Results captured at `session-<X>-validation/wave4-full-pytest.log` + `wave4-summary.txt`

## Report + Commit (Wave 5)

- [ ] Phase report at `docs/plans/<date>-<phase>-report.md`
- [ ] session-<X>-validation/ artifacts complete
- [ ] Commit on phase branch (awaits user authorization)
- [ ] Consolidation: merge phase branch → integration; verify tests green

## Post-Session

- [ ] Out-of-scope findings filed for next phase
- [ ] Memory updated if needed
- [ ] Team cleaned up (`TeamDelete`)
