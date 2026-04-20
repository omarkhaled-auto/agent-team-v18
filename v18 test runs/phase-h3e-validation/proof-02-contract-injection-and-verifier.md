# Proof 02 — Contract Injection And Verifier

## Harness

- Prompt entry: `agent_team_v15.agents.build_wave_a_prompt`
- Verifier entry: `agent_team_v15.wave_executor._run_wave_a_contract_verifier`
- Scaffold fallback entry: `agent_team_v15.scaffold_runner.scaffold_config_from_stack_contract`
- Contract source used by implementation: `.agent-team/STACK_CONTRACT.json`

## Observed prompt section

```text
[WAVE A EXPLICIT CONTRACT VALUES]
Use these literal values exactly when writing bootstrap, env, and compose files.
Do not invent substitute ports or swap API/Web values.
- API port: 3001
- DoD port anchor: 3001
- Allowed concrete port literals: [3001]
```

## Observed scaffold fallback materialization

```json
{
  "port": 3001,
  "api_prefix": "v1"
}
```

## Observed verifier findings

```json
[
  {
    "code": "WAVE-A-CONTRACT-DRIFT-001",
    "file": "apps/api/src/main.ts",
    "line": 1,
    "message": "apps/api/src/main.ts sets process.env.PORT fallback=4000, but the stack contract requires API port 3001."
  },
  {
    "code": "WAVE-A-CONTRACT-DRIFT-001",
    "file": "docker-compose.yml",
    "line": 0,
    "message": "docker-compose.yml sets services.api.ports[0]=4000, but the stack contract requires API port 3001."
  }
]
```

## Flag-off / match evidence

- `tests/test_h3e_contract_guard.py::test_wave_a_prompt_omits_explicit_contract_values_when_flag_disabled`
- `tests/test_h3e_contract_guard.py::test_wave_a_contract_verifier_accepts_matching_ports`

Both passed in the H3e ring, confirming:

- no explicit-values block when `wave_a_contract_injection_enabled=False`
- no verifier finding when the written literals already match the contract
