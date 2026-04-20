# Proof 02 - Hypothesis (b) CWD Propagation Verification

## Scope

CWD verification for Codex app-server dispatch lives in:

- `src/agent_team_v15/codex_appserver.py`
- `src/agent_team_v15/cli.py`

The implementation resolves the dispatch cwd when the flag is enabled, rejects invalid cwd inputs, and warns on a `thread/start` cwd mismatch using `CODEX-CWD-MISMATCH-001`.

## Verification

Command:

```text
pytest tests/test_bug20_codex_appserver.py -q -k "resolves_relative_cwd_when_check_enabled or raises_on_missing_cwd_when_check_enabled or raises_on_file_cwd_when_check_enabled or logs_cwd_mismatch_warning"
```

Result:

```text
4 passed, 5 deselected in 0.19s
```

## Evidence

- `test_execute_codex_resolves_relative_cwd_when_check_enabled`
  - sets `cwd_propagation_check_enabled=True`
  - invokes `execute_codex()` with a relative cwd
  - proves the subprocess spawn receives the resolved absolute path
- `test_execute_codex_raises_on_missing_cwd_when_check_enabled`
  - proves invalid missing cwd input raises `CodexDispatchError`
- `test_execute_codex_raises_on_file_cwd_when_check_enabled`
  - proves file-path input also raises `CodexDispatchError`
- `test_execute_codex_logs_cwd_mismatch_warning`
  - returns a mismatched cwd from `thread/start`
  - asserts the warning contains `CODEX-CWD-MISMATCH-001`

## Verdict

Hypothesis (b) is implemented and independently gated by `v18.codex_cwd_propagation_check_enabled`.

Flag ON:

- cwd is resolved and validated before app-server dispatch
- mismatches are surfaced explicitly instead of disappearing into transport ambiguity

Flag OFF:

- the new validation path is skipped
- existing app-server dispatch behavior remains in place
