# Phase H2a Codex Config Schema

Branch baseline:
- Branch: `phase-h2a-codex-app-server-migration`
- Base SHA at branch cut: `b27825b05c83be8c9857265bb41d1ce03c75dcb7`

## Current v18 emission

Current writer path:
- `src/agent_team_v15/constitution_writer.py:103-107` writes `<cwd>/.codex/config.toml`
- `src/agent_team_v15/constitution_templates.py:162-172` renders the snippet
- `src/agent_team_v15/wave_executor.py:4246-4255` calls `constitution_writer.write_all_if_enabled(...)`

Current emitted TOML:

```toml
[features]
# Raise AGENTS.md cap from 32 KiB default to 64 KiB (Phase G Slice 1d).
project_doc_max_bytes = 65536
```

The current source emits exactly one non-boolean key under `[features]`: `project_doc_max_bytes`.
I found no other source-emitted non-boolean `[features]` keys in `src/`.

## Verified upstream schema

Official sources:
- OpenAI Codex config reference: https://developers.openai.com/codex/config-reference
- OpenAI Codex config schema: https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/config.schema.json
- OpenAI Codex config docs index: https://github.com/openai/codex/blob/main/docs/config.md

Verified facts:
- `project_doc_max_bytes` is a top-level integer config key in the official schema.
- `features` is a table of boolean feature toggles only; `features.<name>` is boolean.

This matches the smoke #12 failure:
- `invalid type: integer '65536', expected a boolean`

## Canonical rewrite

Rewrite the project snippet to:

```toml
project_doc_max_bytes = 65536
```

Do not emit `[features]` when no valid feature booleans are present.

## Reader impact

The repo-root `.codex/config.toml` path is write-only in this repo.
- No runtime reader of `project_doc_max_bytes` was found in `src/`.
- `src/agent_team_v15/codex_transport.py:124-177` manages temporary `CODEX_HOME/config.toml`, but that is a separate path and does not read or write `project_doc_max_bytes`.

## Validation target

Regression target for H2a:
- `codex-cli 0.121.0` accepts the rewritten config during real app-server `thread/start`
- the emitted snippet no longer places any integer/string keys under `[features]`
