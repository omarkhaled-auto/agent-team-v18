# D-04 investigation — Review fleet was never deployed

**Source evidence:** `v18 test runs/build-j-closeout-sonnet-20260415/BUILD_LOG.txt`
lines 1495–1500 ("ZERO-CYCLE MILESTONES: 1 milestone(s) never deployed review
fleet: milestone-6" → "GATE VIOLATION: Review fleet was never deployed
(8 requirements, 0 review cycles). GATE 5 enforcement will trigger recovery."
→ "RECOVERY PASS : 0/8 requirements checked (0 review cycles)").

**Function and site:** `src/agent_team_v15/cli.py:10459-10467` emits the GATE
VIOLATION warning; `cli.py:10543-10555` is the existing "GATE 5 ENFORCEMENT"
which sets `needs_recovery = True` when `review_cycles == 0 and
total_requirements > 0`. Recovery then runs `_run_review_only` (cli.py:8452).

**Root cause (not a single broken guard):** There is no `if ... skip` gate
incorrectly firing. The review fleet is deployed by the LLM orchestrator
choosing to invoke the `code-reviewer` sub-agent during its turns. When the
orchestrator finishes without deploying it (budget exhausted, turn ceiling,
off-task decision), `review_cycles` stays at 0. The existing code detects this
post-hoc and fires a recovery pass. In build-j the recovery pass ALSO failed
to run reviewers (D-05 prompt-injection misfire prevented it) so the pipeline
completed with 0 review cycles AND a warning AND a noop recovery — a silent
skip that didn't halt the pipeline.

**Decision:** Do NOT mutate an existing guard condition — there isn't a wrong
one. Instead, add a **post-gate, post-recovery invariant** after the existing
GATE 5 + recovery block (cli.py ~line 10621). When the *final* convergence
report still shows `review_cycles == 0 and total_requirements > 0`, and
`config.v18.review_fleet_enforcement` is True (default), raise
`ReviewFleetNotDeployedError` (halts the pipeline). When the flag is False,
log the existing warning and continue (pre-fix behaviour).

**Scope inside authorized surface:** `cli.py` + `config.py` + new test file.
No guard-condition mutation anywhere else. Approx 60 LOC in cli.py + 8 LOC in
config.py.
