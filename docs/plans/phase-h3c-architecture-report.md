# Phase H3c Architecture Report

Date: 2026-04-20

## Summary

H3c's four hypotheses map cleanly to the expected Wave B prompt, Codex app-server, provider router, and checkpoint surfaces, but two details in the brief do not match repo reality:

1. The checkpoint implementation is in [`src/agent_team_v15/wave_executor.py`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:358>), not a standalone `checkpoint.py`.
2. Flag-gated app-server checks cannot live in `codex_appserver.py` alone because `execute_codex()` receives a `CodexConfig`, while the new flags originate on `config.v18` and are constructed in [`src/agent_team_v15/cli.py`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/cli.py:3537>).

The preserved H2e forensics and report are in `v18 test runs/phase-h2e-validation-smoke-20260420-103635/`, not repo root.

## Insertion Map

### Hypothesis (a) prompt hardening

- Raw Wave B prompt assembly is in [`build_wave_b_prompt`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8532>).
- The existing requirements text is loaded at [`agents.py:8569`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8569>).
- The current scaffold/deliverables block is injected at [`agents.py:8688-8693`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8688>).
- The helper already capable of extracting requirements-declared file paths is [`_extract_wave_b_scaffold_deliverables`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8445>) via the ownership contract and requirements text.
- Codex-specific wrapping happens later in [`provider_router.py:301-304`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:301>) via [`wrap_prompt_for_codex`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_prompts.py:286>).

Implementation shape:

- Reuse the existing deliverables extractor as the source of truth for a real deliverables count.
- When `v18.codex_wave_b_prompt_hardening_enabled` is on, promote a count-backed deliverables block ahead of `[MILESTONE REQUIREMENTS]`.
- Because `provider_router` does not pass config into `wrap_prompt_for_codex`, the cleanest flag-preserving design is marker-based: `build_wave_b_prompt` emits a deterministic Wave B hardening marker block only when the flag is on, and `wrap_prompt_for_codex` detects that marker to add the extra `<tool_persistence>`/count-verification wrapper text.

### Hypothesis (b) cwd propagation verification

- `execute_codex()` is defined at [`codex_appserver.py:1019`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:1019>).
- The app-server subprocess is spawned through [`_spawn_appserver_process`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:284>) and already receives `cwd=` at [`codex_appserver.py:288-303`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:288>).
- JSON-RPC `thread/start` already carries `"cwd": self.cwd` at [`codex_appserver.py:588-595`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:588>).
- JSON-RPC `turn/start` also carries `"cwd": self.cwd` at [`codex_appserver.py:597-604`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:597>).
- Today there is no cwd validation or explicit cwd mismatch logging in `codex_appserver.py`.

Implementation shape:

- Extend `CodexConfig` with `cwd_propagation_check_enabled`.
- Populate it from `config.v18` where `CodexConfig` is constructed in [`cli.py:3537-3543`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/cli.py:3537>).
- In `execute_codex()`, resolve/validate cwd when the flag is on, use the resolved absolute path for spawn/capture, and compare it with the cwd echoed by the `thread/start` result. This is cheaper and more portable than probing OS process cwd on Windows.

### Hypothesis (c) flush-then-wait

- Codex success is evaluated in [`provider_router.py:398-434`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:398>).
- There is no existing wait or flush between `codex_result.success` and the post checkpoint. The code goes straight from [`provider_router.py:399`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:399>) to [`provider_router.py:400`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:400>).

Implementation shape:

- Add `v18.codex_flush_wait_enabled` and `v18.codex_flush_wait_seconds`.
- If enabled and Codex reported success, sleep for the configured duration immediately before `checkpoint_create("post-codex-wave-...")`.
- Keep this additive and scoped to the success path so failure rollback semantics stay unchanged.

### Hypothesis (d) checkpoint verification

- The real checkpoint dataclasses are [`WaveCheckpoint`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:130>) and [`CheckpointDiff`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:140>).
- File walking happens in `_checkpoint_file_iter` and `_create_checkpoint` at [`wave_executor.py:322-375`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:322>).
- Diffing is byte-hash based in [`wave_executor.py:378-391`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:378>), not mtime-based.

Implementation shape:

- Add a new checkpoint-diff capture alongside the existing H3a captures when `v18.codex_capture_enabled` is on.
- Add a synthetic create/modify/delete integration test against `_create_checkpoint`/`_diff_checkpoints`.
- Only add a tracker hardening code path if that synthetic test fails. Current repo evidence does not justify a behavior change in `_create_checkpoint` or `_diff_checkpoints`.

## Preserved H2e Inputs

- Forensics: [CODEX_WAVE_B_FALLBACK_FORENSICS.md](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/CODEX_WAVE_B_FALLBACK_FORENSICS.md:1>)
- Report: [H2E_REPORT.md](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/H2E_REPORT.md:1>)
- M1 requirements snapshot: [REQUIREMENTS.md](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/cwd-snapshot/.agent-team/milestones/milestone-1/REQUIREMENTS.md:1>)

## Risks

- The prompt hardening count must come from an existing deliverables source, not a new regex over prose-only sections.
- The cwd check needs shared plumbing through `CodexConfig`; otherwise it cannot stay flag-gated.
- The checkpoint tracker already uses content hashes, so hypothesis (d) may legitimately end up as "capture + proof only" with no behavioral delta.
