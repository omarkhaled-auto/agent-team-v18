# Stack Contracts

`StackContract` is the wave-pipeline guardrail for stack drift between the PRD and generated code.

## What it stores

- Backend framework
- Frontend framework
- ORM
- Database
- Monorepo layout and path prefixes
- Forbidden file, import, and decorator patterns
- Required file and import patterns
- Provenance (`derived_from`)
- Confidence (`explicit`, `high`, `medium`, `low`)

The contract is persisted to:

- `.agent-team/STACK_CONTRACT.json`
- `.agent-team/STATE.json` under `stack_contract`

## How it is used

1. Phase 1 / 1.5 derives the contract from the PRD, `MASTER_PLAN.md`, milestone requirements, and tech research.
2. Wave A receives the contract block twice in its prompt.
3. After Wave A finishes, a deterministic validator scans the actual files it wrote.
4. If an `explicit` or `high` confidence contract is violated by a CRITICAL drift signal, Wave A is rolled back and retried once with the violation list appended to the prompt.
5. The same validator runs after Wave B and Wave D in advisory mode only.

## Violation codes

- `STACK-FILE-001`: forbidden file pattern was written
- `STACK-FILE-002`: required file pattern was missing from the wave output
- `STACK-IMPORT-001`: forbidden import appeared in the wave output
- `STACK-IMPORT-002`: required import was missing from the wave output
- `STACK-DECORATOR-001`: forbidden decorator appeared in the wave output
- `STACK-PATH-001`: file was written outside the declared layout

## Confidence model

- `explicit`: framework and ORM were named directly in the PRD or plan text
- `high`: multiple stack dimensions were explicit, with the rest inferred
- `medium`: one stack dimension was explicit
- `low`: the contract was only inferred from surrounding signals such as tech research

Only `explicit` and `high` confidence contracts hard-block Wave A on CRITICAL violations. `medium` and `low` still emit findings and telemetry.

## Adding a new builtin contract

1. Add a new `(framework, orm)` entry in `src/agent_team_v15/stack_contract.py`.
2. Define narrow forbidden patterns and at least one required file/import pattern.
3. Add derivation and validation coverage in `tests/test_stack_contract.py`.
4. Add at least one wave-engine test in `tests/test_wave_executor_stack.py` if the new contract changes retry or advisory behavior.
