# D-08 investigation — CONTRACTS.json generated in recovery, not orchestration

**Source evidence:** `v18 test runs/build-j-closeout-sonnet-20260415/BUILD_LOG.txt`
lines 1425-1477 ("RECOVERY PASS : CONTRACTS.json not found after
orchestration." → "Contract health check FAILED: CONTRACTS.json not
generated." → recovery runs the `contract-generator` agent → "## CONTRACTS.json
Generated Successfully" → "Contract recovery verified").

**Function and site:** `cli.py:10316-10364` is the current "Post-orchestration
Contract health check". It only runs `_run_contract_generation` (LLM
recovery pass) when `not contract_path.is_file() and has_requirements and
generator_enabled`. There is NO primary-path invocation during orchestration
for `CONTRACTS.json` — its creation is purely whatever the LLM orchestrator
chooses to do during its turns via the `contract-generator` sub-agent.

**Why build-j failed primary:** The orchestrator in build-j didn't deploy
`contract-generator` during orchestration proper. Recovery had to. This is
not a single-flag guard condition — it's the same structural issue as D-04
(orchestrator LLM skipping a step without a deterministic producer).

**Decision:** Add a **deterministic primary producer** at end of
orchestration, *before* the existing recovery-pass block. The deterministic
path uses `api_contract_extractor.extract_api_contracts` (already used at
cli.py:1255 for per-milestone `API_CONTRACTS.json`) to produce `CONTRACTS.json`
via static source analysis. If primary succeeds → log `Contract generation:
primary`. If primary raises/empty → existing recovery pass runs as
belt-and-suspenders. Log marker `primary` vs `recovery-fallback` based on
which path produced the file. If both fail → pipeline is marked failed via a
non-silent hard-fail (set a dedicated `contract_generation_failed` flag
and let the existing gate enforcement escalate).

**Scope inside authorized surface:** `cli.py` only. No new files, no changes
outside the post-orchestration contract check block. ~60 LOC of primary-path
helper + marker logging. No new feature flag (structural, per session plan).
