# Proof 01 - Prompt Dump Capture

Date: 2026-04-20

## Goal

Show that a production-routed Wave B Codex dispatch writes the rendered wrapped prompt to `.agent-team/codex-captures/` when `v18.codex_capture_enabled` is on, and writes nothing when the flag is off.

## Production call chain

- `src/agent_team_v15/wave_executor.py:1933-1960` passes the milestone object into provider routing.
- `src/agent_team_v15/provider_router.py:320-349` reads `v18.codex_capture_enabled`, derives `CodexCaptureMetadata`, and forwards it into `execute_codex(...)`.
- `src/agent_team_v15/codex_appserver.py:1028-1062` creates `CodexCaptureSession` and writes the prompt capture before the subprocess starts.
- `src/agent_team_v15/codex_captures.py:355-397` resolves the capture paths and writes the prompt file with the metadata header.

## Evidence

- `tests/test_codex_dispatch_captures.py::test_provider_routed_codex_dispatch_writes_capture_files`
  - drives the real provider-router -> app-server call chain with a mocked Codex subprocess
  - asserts the prompt file path is:
    - `<tmp>/.agent-team/codex-captures/milestone-1-wave-B-prompt.txt`
  - asserts the header contains:
    - `# Milestone: milestone-1`
    - `# Wave: B`
    - `# Model: gpt-5.4`
    - `# Reasoning-effort: low`
  - asserts the body contains:
    - `CODEX_WAVE_B_PREAMBLE`
    - the original prompt text `Wire the backend.`
- `tests/test_codex_dispatch_captures.py::test_provider_routed_codex_dispatch_skips_capture_when_flag_off`
  - drives the same call chain with `codex_capture_enabled=False`
  - asserts `.agent-team/codex-captures/` does not exist
- `tests/test_config_v18_loader_gaps.py`
  - asserts `v18.codex_capture_enabled` round-trips from YAML
  - asserts the default when absent is `False`

## Result

Prompt dump capture is wired to the production provider-routed Codex path, includes the required header fields, captures the wrapped Wave B prompt, and remains fully inert when the flag is off.
