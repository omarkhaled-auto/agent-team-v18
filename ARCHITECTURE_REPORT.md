# V18.1 Phase 4 Architecture Report

> Scope: Phase 4 throughput implementation from `V18_PHASE4_THROUGHPUT_IMPLEMENTATION.md`
> Repo: `C:\Projects\agent-team-v18-codex`
> Source focus: `src/agent_team_v15`
> Discovery date: 2026-04-09

## Executive Summary

The current V18 codebase is still fundamentally sequential at the milestone level. `cli._run_prd_milestones()` pulls every currently-ready milestone from the master plan, but it then executes them one at a time directly in the main working tree. `wave_executor.execute_milestone_waves()` is already `cwd`-driven, so the core execution engine can run inside a git worktree without invasive changes. The main work for Phase 4 is therefore outside the wave engine itself:

1. Add isolated git worktrees and safe snapshotting.
2. Add a dependency-aware parallel dispatcher and a serialized merge queue.
3. Preserve the existing sequential path when isolation is disabled.
4. Move milestone verification to happen inside the worktree before merge.

The current registry compiler is already close to a merge-time model because it accepts an explicit `milestone_ids` list and reads declarations from `.agent-team/registries/{milestone_id}/`. It does not currently resolve version conflicts explicitly; last declaration wins because declarations are merged in list order.

State persistence is atomic but not concurrent-safe across multiple milestone executors writing the same mainline `.agent-team/STATE.json`. That confirms the Phase 4 design requirement: each worktree needs its own `.agent-team/STATE.json`, and only the serialized merge path should update mainline state.

## 1A. Git Infrastructure

### `_git_snapshot()` in `coordinated_builder.py`

File: `src/agent_team_v15/coordinated_builder.py:1481`

Current behavior:

1. Runs `git status --porcelain` in the project root.
2. If that fails, runs `git init`.
3. Runs `git add -A`.
4. Runs `git commit -m "pre-fix-run-{run_number} snapshot" --allow-empty`.

Observations:

- Git is already invoked everywhere through `subprocess.run(["git", ...])`, so adding worktree commands through the same mechanism is consistent with the codebase.
- The current snapshot helper is too broad for Phase 4 safe snapshot rules because it stages everything with `git add -A`.

### Repository git state at discovery time

Read-only checks run during discovery:

- `git --version` -> `git version 2.51.0.windows.1`
- `git branch --show-current` -> `master`
- `git worktree list` -> only the main working tree:
  - `C:/Projects/agent-team-v18-codex  452e500 [master]`

Conclusions:

- Git is available.
- Worktree support is available (`git` is well above 2.5).
- The integration branch at discovery time is `master`.
- There are no existing auxiliary worktrees.

### Current git lifecycle

- The repo is already git-initialized before Phase 4 starts.
- Existing snapshot commits are created by `coordinated_builder._git_snapshot()`.
- No current V18 milestone code creates milestone branches or worktrees.
- No current V18 milestone code merges milestone branches back into mainline.

### Windows worktree caveats

- Long nested paths can still be a problem on Windows, so `.worktrees/{milestone_id}` should stay shallow.
- Avoid relying on symlink behavior inside worktrees; Windows symlink creation often depends on developer mode or elevated privileges.
- NTFS is assumed. Worktree operations and normal file copies are fine there.
- Path normalization should use `Path` and forward-slash normalization only for git-facing file comparisons.

## 1B. Milestone Loop

### Exact loop location

File: `src/agent_team_v15/cli.py:1714`

The active loop begins later in the same function:

File: `src/agent_team_v15/cli.py:2085`

Current structure:

1. Parse/load the master plan.
2. Loop until all milestones are complete or iteration budget is exhausted.
3. Call `ready = plan.get_ready_milestones()`.
4. If no milestones are ready, stop.
5. Iterate `for milestone in ready:`.
6. Execute each ready milestone sequentially in the main `cwd`.

### `get_ready_milestones()`

File: `src/agent_team_v15/milestone_manager.py:64`

Behavior:

- Returns milestones whose `status == "PENDING"` and whose `dependencies` are all in the set of milestones whose status is `"COMPLETE"`.
- It does not schedule only one milestone. It can return multiple milestones at once.

Current consequence:

- If multiple milestones are simultaneously ready, `cli._run_prd_milestones()` still processes them serially because it just does `for milestone in ready:`.

### Where wave execution is called

File: `src/agent_team_v15/cli.py:2419`

Current call:

```python
wave_result = await asyncio.wait_for(
    execute_milestone_waves(
        milestone=milestone,
        ir=_load_product_ir(cwd),
        config=config,
        cwd=cwd,
        ...
    ),
    timeout=_ms_timeout_s * 1.5,
)
```

### Meaning of `cwd` to the wave executor

The wave executor uses `cwd` for all milestone-local file work:

- checkpoints
- `.agent-team/STATE.json`
- `.agent-team/artifacts`
- `.agent-team/telemetry`
- product file diffs
- artifact extraction persistence

This means a worktree path can be substituted directly for the current mainline `cwd`.

### Exact insertion point for the parallel conditional

The correct insertion point is inside `_run_prd_milestones()` immediately before the current sequential:

```python
ready = plan.get_ready_milestones()
...
for milestone in ready:
```

That lets the code branch cleanly into:

- legacy sequential execution when git isolation is off
- worktree-backed execution when git isolation is on

## 1C. Registry Compiler Integration

### `compile_registries()` signature and behavior

File: `src/agent_team_v15/registry_compiler.py:25`

```python
def compile_registries(cwd: str, milestone_ids: list[str]) -> dict[str, bool]:
```

Inputs:

- `cwd`: project root
- `milestone_ids`: declaration contributors to include

Outputs:

- returns a `dict[str, bool]` keyed by registry type

Registry sources:

- `.agent-team/registries/{milestone_id}/deps.registry.json`
- `.agent-team/registries/{milestone_id}/modules.registry.json`
- `.agent-team/registries/{milestone_id}/nav.registry.json`
- `.agent-team/registries/{milestone_id}/i18n.registry.json`
- `.agent-team/registries/{milestone_id}/routes.registry.json`

Compiled shared outputs:

- `package.json`
- `apps/api/src/app.module.ts`
- `apps/web/src/components/nav-registry.ts`
- `apps/web/messages/index.ts`
- `apps/api/src/routes.ts`

### Current integration mode

The compiler is already deterministic and already supports an explicit list of milestone ids, which makes merge-time compilation viable without redesigning the API.

What it does not do today:

- it is not wired into a merge queue
- it does not explicitly classify or report declaration conflicts
- it does not reject incompatible duplicate declarations

Conflict behavior today:

- dependency-like mappings are overwritten by later declarations in list order
- list-like registries are deduped by key fields

Conclusion:

- Merge-time mode is feasible now.
- Conflict semantics are implicit, not validated.

## 1D. State Management for Parallel Execution

### `wave_progress`

File: `src/agent_team_v15/state.py:39`

`RunState.wave_progress` stores per-milestone wave state, including:

- current wave
- completed wave list
- other resume metadata persisted by the wave executor and CLI

### `save_state()` / `load_state()`

Files:

- `src/agent_team_v15/state.py:318`
- `src/agent_team_v15/state.py:394`

`save_state()` behavior:

- creates the directory if needed
- writes via temp file + `os.replace()` for atomic replacement

That is good for single-writer durability, but it is not a concurrency protocol. Multiple milestone executors writing the same mainline `STATE.json` can still race and overwrite each other.

Conclusion:

- Mainline `STATE.json` is not safe for concurrent parallel milestone writes.
- Each worktree needs its own copied `.agent-team/STATE.json`.
- Mainline state updates must happen only after serialized merge completion.

## 1E. Post-Milestone Verification: Where It Runs Today

The current code does much more after wave execution than just compile/smoke.

Wave execution ends around:

- `src/agent_team_v15/cli.py:2419-2468`

After that, the same milestone continues through a long post-milestone gate chain in `cli.py`, including:

1. milestone health check via `mm.check_milestone_health(...)`
2. review-only recovery loop via `_run_review_only(...)`
3. contract extraction
4. schema validation
5. wiring completeness checks
6. mock data scan and fix loop
7. UI compliance scan and fix loop
8. wiring verification/fix loop
9. integration verification gate
10. audit loop via `_run_audit_loop(...)`
11. truth scoring
12. quality validator pass
13. completion cache and interface registry updates

This confirms the Phase 4 design requirement:

- milestone verification must happen inside the worktree before merge
- post-merge verification should be a reduced safety subset only

Can these gates run inside a worktree?

- Yes in principle, because they are overwhelmingly `cwd`/`project_root` based.
- The mainline-specific risk is state persistence. Those writes must point to the worktree-local `.agent-team/`.

## 1F. Migration System

### What exists now

Primary migration generation logic:

- `src/agent_team_v15/coordinated_builder.py:1369`

Detected systems:

- TypeORM:
  - looks for a data source file
  - runs `npx typeorm migration:generate .../AutoGenerated -d <data-source>`
- Prisma:
  - looks for `prisma/schema.prisma`
  - runs `npx prisma migrate dev --name init --create-only`

### Ordering implications

- TypeORM migrations are sequence/timestamp-prefixed filenames, typically one file per migration.
- Prisma migrations are timestamp-named directories under `prisma/migrations/`.

Parallel risk:

- Two worktrees can generate migrations with colliding prefixes or timestamps.
- Final ordering therefore has to be assigned at merge time on mainline.

Conclusion:

- Merge-time migration renumbering is required for both TypeORM-style file prefixes and Prisma-style timestamp directories.

## Implementation Guidance

### Safe decisions confirmed by the codebase

- Worktrees can be added without changing `wave_executor.execute_milestone_waves()` core mechanics.
- The registry compiler can already support merge-time cumulative compilation.
- The sequential branch can stay intact if the new worktree path is introduced as a separate conditional in `cli.py`.

### Required constraints

- Do not let parallel milestones write mainline `.agent-team/STATE.json`.
- Do not make mainline merge the first place milestone health is discovered.
- Do not treat arbitrary text conflicts as auto-resolvable.
- Do not reuse the current `_git_snapshot()` behavior for worktree snapshotting because `git add -A` is too broad.

## Discovery Outputs

### Read-only commands run

- `git --version`
- `git branch --show-current`
- `git worktree list`

### High-confidence integration points

- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/registry_compiler.py`
- `src/agent_team_v15/state.py`
- `src/agent_team_v15/coordinated_builder.py`

## Verdict

Phase 4 is implementable on the current codebase. The safest path is:

1. Add standalone worktree, merge-queue, and parallel-dispatch modules.
2. Keep the legacy sequential branch intact.
3. Add a worktree milestone wrapper that runs wave execution plus the same post-milestone verification chain before enqueue.
4. Serialize all mainline merges and mainline state updates through the merge queue.
