# Phase H3c Discovery Citations

## Prompt / Wave B

- [`src/agent_team_v15/agents.py:8445`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8445>) defines `_extract_wave_b_scaffold_deliverables(...)`.
- [`src/agent_team_v15/agents.py:8472`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8472>) defines `_format_wave_b_scaffold_deliverables_block(...)`.
- [`src/agent_team_v15/agents.py:8569`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8569>) loads full `requirements_text`.
- [`src/agent_team_v15/agents.py:8688-8693`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8688>) injects `[MILESTONE REQUIREMENTS]` plus the current deliverables block.
- [`src/agent_team_v15/codex_prompts.py:10`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_prompts.py:10>) defines `CODEX_WAVE_B_PREAMBLE`.
- [`src/agent_team_v15/codex_prompts.py:193`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_prompts.py:193>) defines `CODEX_WAVE_B_SUFFIX`.
- [`src/agent_team_v15/codex_prompts.py:286`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_prompts.py:286>) defines `wrap_prompt_for_codex(...)`.
- [`src/agent_team_v15/provider_router.py:301-304`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:301>) applies `wrap_prompt_for_codex(...)` immediately before Codex dispatch.

## Codex cwd propagation

- [`src/agent_team_v15/codex_appserver.py:284-303`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:284>) spawns the app-server subprocess with `cwd=...`.
- [`src/agent_team_v15/codex_appserver.py:405`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:405>) starts the transport-owned subprocess.
- [`src/agent_team_v15/codex_appserver.py:588-595`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:588>) includes cwd in `thread/start`.
- [`src/agent_team_v15/codex_appserver.py:597-604`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:597>) includes cwd in `turn/start`.
- [`src/agent_team_v15/codex_appserver.py:1019-1079`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:1019>) defines `execute_codex(...)` and currently performs no cwd validation.
- [`src/agent_team_v15/cli.py:3537-3543`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/cli.py:3537>) constructs the `CodexConfig` passed into the transport.

## Codex success -> checkpoint diff

- [`src/agent_team_v15/provider_router.py:297`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:297>) creates the pre-Codex checkpoint.
- [`src/agent_team_v15/provider_router.py:342-351`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:342>) invokes `execute_codex(...)`.
- [`src/agent_team_v15/provider_router.py:399-401`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:399>) transitions directly from success to `post_checkpoint = checkpoint_create(...)` and `checkpoint_diff(...)`.
- [`src/agent_team_v15/provider_router.py:406-420`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/provider_router.py:406>) contains the zero-diff fallback warning/branch.

## Checkpoint implementation

- [`src/agent_team_v15/wave_executor.py:130-145`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:130>) defines `WaveCheckpoint` and `CheckpointDiff`.
- [`src/agent_team_v15/wave_executor.py:322-355`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:322>) walks checkpoint files via `os.walk`, pruning skip dirs.
- [`src/agent_team_v15/wave_executor.py:358-375`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:358>) hashes file bytes with `hashlib.md5(...)`.
- [`src/agent_team_v15/wave_executor.py:378-391`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:378>) computes created/modified/deleted paths by comparing hash manifests.
- [`src/agent_team_v15/wave_executor.py:1951-1955`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/wave_executor.py:1951>) injects `_create_checkpoint` / `_diff_checkpoints` into provider routing.

## Config

- [`src/agent_team_v15/config.py:823-938`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/config.py:823>) is the main `V18Config` provider-routing block, ending with `codex_capture_enabled`.
- [`src/agent_team_v15/config.py:2538-2568`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/config.py:2538>) defines `_coerce_bool`, `_coerce_int`, and `_coerce_text`.
- [`src/agent_team_v15/config.py:2575-3036`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/config.py:2575>) is the YAML loader for `v18`.
- [`tests/test_config_v18_loader_gaps.py:29-45`](</C:/Projects/agent-team-v18-codex/tests/test_config_v18_loader_gaps.py:29>) lists the current round-trip cases.

## Preserved H2e artifacts

- [`v18 test runs/phase-h2e-validation-smoke-20260420-103635/CODEX_WAVE_B_FALLBACK_FORENSICS.md:1`](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/CODEX_WAVE_B_FALLBACK_FORENSICS.md:1>) records the Wave B failure.
- [`v18 test runs/phase-h2e-validation-smoke-20260420-103635/H2E_REPORT.md:1`](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/H2E_REPORT.md:1>) is the killed-early smoke report.
- [`v18 test runs/phase-h2e-validation-smoke-20260420-103635/H2E_REPORT.md:179`](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/H2E_REPORT.md:179>) inventories the preserved artifacts.
- [`v18 test runs/phase-h2e-validation-smoke-20260420-103635/cwd-snapshot/.agent-team/milestones/milestone-1/REQUIREMENTS.md:1`](</C:/Projects/agent-team-v18-codex/v18 test runs/phase-h2e-validation-smoke-20260420-103635/cwd-snapshot/.agent-team/milestones/milestone-1/REQUIREMENTS.md:1>) is the exact M1 requirements snapshot that triggered the fallback.

## Repo-reality corrections

- `checkpoint_create` / `checkpoint_diff` are not implemented in `provider_router.py`; they live in `wave_executor.py`.
- The H2e report and forensics are not repo-root files in this checkout.
- `codex_appserver.py` already forwards cwd into subprocess spawn, `thread/start`, and `turn/start`; hypothesis (b) is therefore validation/logging oriented, not missing-parameter plumbing.
