# Proof 04: SCAFFOLD-CTX-001

## Original Smoke Failure

Combined-smoke evidence:

- `launch.log:620-622`
  - Docker startup failed during post-Wave-B probing:
  - `"/packages/shared/package.json": not found`
  - `Warning: Milestone milestone-1 failed: Wave execution failed in B: Docker build failed during live endpoint probing startup`

This matches the broken template combination:

- web Dockerfile copies `packages/shared/package.json`
- scaffolded `docker-compose.yml` built `web` from `context: ./apps/web`

## Source Change

Primary source updates:

- `src/agent_team_v15/scaffold_runner.py:933-935`
  - new flag helper: `_scaffold_web_dockerfile_context_fix_enabled(...)`
- `src/agent_team_v15/scaffold_runner.py:938-959`
  - `_scaffold_docker_compose(...)` now selects fixed or legacy compose output
- `src/agent_team_v15/scaffold_runner.py:1148-1206`
  - legacy template preserved with `context: ./apps/web`
- `src/agent_team_v15/scaffold_runner.py:1209-1219`
  - fixed helper rewrites only the web build block to:
    - `context: .`
    - `dockerfile: apps/web/Dockerfile`
- `src/agent_team_v15/config.py:1011-1015, 3161-3167`
  - new flag: `scaffold_web_dockerfile_context_fix_enabled`

Diff excerpt:

```diff
+ if _scaffold_web_dockerfile_context_fix_enabled(config):
+     template = _docker_compose_template_with_web_root_context()
...
+       context: .
+       dockerfile: apps/web/Dockerfile
```

## Production-Caller Proof

Invocation:

```text
pytest tests/test_h3h_scaffold_ctx.py::test_run_scaffolding_writes_fixed_web_build_context_and_preserves_dockerfile tests/test_h3h_scaffold_ctx.py::test_docker_compose_template_is_byte_identical_when_flag_off -v --tb=short
```

Output:

```text
tests/test_h3h_scaffold_ctx.py::test_run_scaffolding_writes_fixed_web_build_context_and_preserves_dockerfile PASSED
tests/test_h3h_scaffold_ctx.py::test_docker_compose_template_is_byte_identical_when_flag_off PASSED
============================== 2 passed in 0.22s ==============================
```

What this proves:

- the real scaffolder writes the corrected web build context when the flag is on
- the web Dockerfile content is preserved unchanged
- the old broken compose template remains reachable when the flag is off

## Flag-Off Verification

`test_docker_compose_template_is_byte_identical_when_flag_off` asserts that the legacy template still contains `context: ./apps/web` and does not contain `dockerfile: apps/web/Dockerfile`.
