# Multi-Provider Wave Executor — Architecture Report

## Phase 1 Findings (codex-cli 0.66.0 on Windows)

### CLI Flags Validated

| Flag | Status | Notes |
|------|--------|-------|
| `codex exec --json` | WORKS | JSONL to stdout |
| `--full-auto` | WORKS | Sets `-a on-request` + `--sandbox workspace-write` |
| `-` (stdin prompt) | WORKS | "If `-` is used, instructions are read from stdin" |
| `-C, --cd <DIR>` | WORKS | Working directory override |
| `-m, --model <MODEL>` | WORKS | Model override |
| `-c key=value` | WORKS | Config override per invocation |
| `-s, --sandbox <MODE>` | WORKS | `read-only`, `workspace-write`, `danger-full-access` |
| `--search` | EXISTS | Enables web search (off by default) |
| `CODEX_QUIET_MODE=1` | WORKS | Suppresses non-JSON output |

### Flags NOT Available in `exec` Subcommand

| Assumed Flag | Reality |
|-------------|---------|
| `--ask-for-approval never` | NOT in exec. Use `--full-auto` instead. |
| `--reasoning-effort` | NOT a CLI flag. Use `-c model_reasoning_effort=value` |

### JSONL Event Structure (from real test)

```jsonl
{"type":"thread.started","thread_id":"019d7c6b-..."}
{"type":"turn.started"}
{"type":"error","message":"Reconnecting... 1/5"}
{"type":"turn.failed","error":{"message":"error message here"}}
```

On success (expected from OpenAI Responses API pattern):
```jsonl
{"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,"total_tokens":N}}
```

Exit code: Always 0. MUST check JSONL for turn.failed vs turn.completed.

### config.toml Structure (from ~/.codex/config.toml)

```toml
model = "gpt-5.1-codex-max"
model_reasoning_effort = "medium"

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
```

NOT config keys (CLI flags only): approval_policy, sandbox_mode, web_search

### CODEX_HOME

CODEX_HOME env var works. Codex reads $CODEX_HOME/config.toml.
Temp CODEX_HOME is safe — only needs config.toml.

### Transport Command Template

```bash
echo "<prompt>" | \
  CODEX_HOME="<temp_dir>" CODEX_QUIET_MODE=1 \
  codex exec --json --full-auto \
  -C <working_dir> \
  -m <model> \
  -
```
