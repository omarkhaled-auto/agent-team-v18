# Phase H3e Contract Guard Design

Date: 2026-04-20

## Code Reality

The current contract guard stack has four layers, but they do not all carry the same authority:

1. `V18Config.contract_mode` still defaults to `"markdown"` in `src/agent_team_v15/config.py:770-779`.
2. Runtime stack-contract persistence and reload already use JSON in `src/agent_team_v15/stack_contract.py:519-547`.
3. Prompt builders render a markdown block from that JSON contract in `src/agent_team_v15/agents.py:8230-8237`, `src/agent_team_v15/agents.py:8287-8291`, and `src/agent_team_v15/agents.py:8367-8375`.
4. The scaffold verifier's port guard does not depend on the stack contract at all. It derives the expected port from milestone `REQUIREMENTS.md` via `src/agent_team_v15/requirements_parser.py:77-118` and `src/agent_team_v15/scaffold_verifier.py:180-220`.

The preserved H3d smoke matters here because it shows the practical hierarchy:

- The stack-contract file exists, but it is semantically empty.
- The scaffold verifier still found the real failure because it used the DoD port in `REQUIREMENTS.md`.

For H3e, the contract guard should therefore be built around authoritative verifier inputs, not around the mere presence of `STACK_CONTRACT.json`.

## Preserved Smoke Reality

`v18 test runs/phase-h3d-validation-smoke-20260420-135742/cwd-snapshot-at-halt-20260420-151407/.agent-team/STACK_CONTRACT.json` is not zero bytes, but it is operationally empty:

- `backend_framework = ""`
- `frontend_framework = ""`
- `orm = ""`
- `database = ""`
- all required and forbidden pattern arrays are empty

That means the relevant H3e conclusion is:

- `STACK_CONTRACT.json` exists
- but the preserved smoke contract file is empty in the sense that it carries no usable stack constraints

## Recommended Guard Hierarchy

### 1. Milestone spec and DoD are authoritative for scaffold invariants

- Source: `src/agent_team_v15/requirements_parser.py:77-118`
- Consumer: `src/agent_team_v15/scaffold_verifier.py:180-220`

For scaffold-level issues like port drift, H3e should keep using the milestone DoD as the oracle.

### 2. `scaffold_verifier_report.json` is authoritative failure evidence

- Writer: `src/agent_team_v15/wave_executor.py:1100-1123`
- Reader: `src/agent_team_v15/cli.py:767-782`, `src/agent_team_v15/cli.py:953-956`

Recovery and redispatch should classify scaffold failures from this report, not from inferred audit prose.

### 3. `STACK_CONTRACT.json` is advisory unless it is substantive

- Writer: `src/agent_team_v15/stack_contract.py:519-527`
- Loader: `src/agent_team_v15/stack_contract.py:530-547`
- Validator: `src/agent_team_v15/wave_executor.py:5021-5094`

The current validator already only hard-blocks Wave A when contract confidence is `explicit` or `high`. That is consistent with the smoke run, where the contract embedded in `STATE.json` ended as low confidence and effectively empty.

### 4. Prompt markdown is presentation only

- Source JSON -> rendered text in `src/agent_team_v15/agents.py:8230-8237`

H3e should not treat prompt markdown as the stored source of truth. It is a view over the JSON contract.

## Insertion Points

### A. Detect and surface semantically empty contracts

- `src/agent_team_v15/cli.py:3900-3917`
- Recommendation: after derivation, detect the "all primary fields blank and arrays empty" case and persist a warning or `stack_contract_effective = false` marker.

This is the best place because it sees both freshly derived contracts and already-loaded contracts before downstream waves consume them.

### B. Make contract loading distinguish empty from useful

- `src/agent_team_v15/stack_contract.py:530-547`
- Recommendation: add an explicit helper for "substantive contract" so downstream code can tell the difference between:
  - no contract file
  - semantically empty contract file
  - populated contract file

### C. Avoid overstating empty contracts in prompts

- `src/agent_team_v15/agents.py:8230-8237`
- `src/agent_team_v15/agents.py:8287-8291`
- `src/agent_team_v15/agents.py:8367-8375`
- Recommendation: when the contract is semantically empty, either omit the "non-negotiable" block or annotate it as advisory/empty so Wave A is not told that a blank contract is authoritative.

### D. Keep stack validation gated by contract quality

- `src/agent_team_v15/wave_executor.py:5021-5094`
- Recommendation: preserve the current hard-block behavior for `confidence in {"explicit", "high"}`, but add explicit telemetry when validation is effectively skipped because the contract is empty or low-confidence.

### E. Keep scaffold redispatch keyed to verifier outputs, not stack-contract existence

- `src/agent_team_v15/scaffold_verifier.py:180-220`
- Recommendation: H3e redispatch policies should key off verifier codes like `SCAFFOLD-PORT-002`, because the verifier already proved it can catch real scaffold drift even when the stack contract is empty.

## H3e Takeaway

The correct H3e contract-guard design is:

- JSON-backed stack contract for advisory stack-shape constraints
- DoD/spec-backed scaffold verifier for authoritative scaffold invariants
- scaffold-verifier report for failure classification

That ordering matches the actual smoke evidence. The system should not make redispatch decisions from "contract file exists" alone, because in the preserved H3d run the contract file existed and still contained no usable contract.
