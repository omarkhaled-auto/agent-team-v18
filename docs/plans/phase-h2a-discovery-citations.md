# Phase H2a Discovery Citations

## Local source citations

### Config write path
- `src/agent_team_v15/constitution_writer.py:103-107` - writes `<cwd>/.codex/config.toml`
- `src/agent_team_v15/constitution_writer.py:110-148` - gated write path through `write_all_if_enabled`
- `src/agent_team_v15/constitution_templates.py:162-172` - broken `[features]` snippet
- `src/agent_team_v15/wave_executor.py:4246-4255` - pipeline call into constitution writer
- `src/agent_team_v15/config.py:805-808` - relevant autogenerate flags

### Transport selection
- `src/agent_team_v15/cli.py:3421-3477` - provider routing assembly, temp Codex home creation, transport selection
- `src/agent_team_v15/cli.py:3457-3461` - `codex_transport_mode` branch (`app-server` vs `exec`)

### Current app-server implementation
- `src/agent_team_v15/codex_appserver.py:328-334` - load-bearing `codex_app_server` import
- `src/agent_team_v15/codex_appserver.py:346-423` - current SDK-based app-server startup and wait path
- `src/agent_team_v15/codex_appserver.py:525-595` - streaming-event processing
- `src/agent_team_v15/codex_appserver.py:634-692` - public `execute_codex(...)`

### Exec transport / temp CODEX_HOME
- `src/agent_team_v15/codex_transport.py:124-177` - `create_codex_home(...)`
- `src/agent_team_v15/codex_transport.py:549-684` - `codex exec` subprocess path
- `src/agent_team_v15/codex_transport.py:687-760` - retry wrapper

### Provider-routed Codex path and fallback
- `src/agent_team_v15/provider_router.py:244-427` - `_execute_codex_wave(...)`
- `src/agent_team_v15/provider_router.py:429-459` - `_claude_fallback(...)`

### Codex wave dispatch sites
- `src/agent_team_v15/wave_executor.py:1816-1867` - provider-routed wave execution entry
- `src/agent_team_v15/wave_executor.py:4456-4528` - Wave A.5 main + rerun entry
- `src/agent_team_v15/wave_executor.py:4531-4581` - Wave T.5 main + rerun entry
- `src/agent_team_v15/wave_executor.py:4628-4688` - provider-routed B/D + compile-fix entry points
- `src/agent_team_v15/wave_executor.py:2704-2768` - `_dispatch_codex_compile_fix(...)`
- `src/agent_team_v15/wave_executor.py:3389-3434` - Codex compile-fix branch + Claude fallback
- `src/agent_team_v15/wave_a5_t5.py:431-487` - shared A.5/T.5 Codex dispatch helper
- `src/agent_team_v15/wave_a5_t5.py:497-638` - A.5 caller
- `src/agent_team_v15/wave_a5_t5.py:691-808` - T.5 caller

### Tests to update
- `tests/test_codex_config_snippet.py`
- `tests/test_constitution_templates.py`
- `tests/test_constitution_writer.py`
- `tests/test_bug20_codex_appserver.py`
- `tests/test_transport_selector.py`
- `tests/test_provider_routing.py`
- `tests/test_phase_f_lockdown.py`

## Official citations

- Codex config reference:
  https://developers.openai.com/codex/config-reference
- Codex config docs index:
  https://github.com/openai/codex/blob/main/docs/config.md
- Codex raw config schema:
  https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/config.schema.json
- Codex app-server README:
  https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- Codex raw app-server README:
  https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server/README.md

## Local runtime citations

Verified locally on 2026-04-20:
- `codex --version` -> `codex-cli 0.121.0`
- `codex app-server --help` exposes:
  - `generate-json-schema`
  - `--listen stdio://`
  - feature enable/disable flags
- `codex app-server generate-json-schema --out <temp>` generated `v2/ThreadStartParams.json`, `v2/TurnStartParams.json`, `v2/TurnInterruptParams.json`, `v2/ThreadTokenUsageUpdatedNotification.json`, and `v2/TurnCompletedNotification.json`
- direct stdio JSON-RPC probe succeeded through `initialize`, `thread/start`, `turn/start`, and `turn/completed`
