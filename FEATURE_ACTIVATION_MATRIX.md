# V18.1 Feature Activation Matrix

## Scope

This report maps the current V18.1 activation model from code, not from intent.

Two important framing points:

1. V18.1 activation is not a single switch. A feature may be:
   - configured by depth in `src/agent_team_v15/config.py`
   - additionally gated by PRD mode in `src/agent_team_v15/cli.py`
   - additionally gated by the milestone loop in `src/agent_team_v15/cli.py:8951-8954`
   - additionally gated by wave execution in `src/agent_team_v15/cli.py:2762-2787` and `src/agent_team_v15/cli.py:3312-3335`
   - additionally gated by evidence mode in `src/agent_team_v15/agents.py:7168-7265` and `src/agent_team_v15/cli.py:462-469`

2. `prd` and `prd-large` are not real depth names in `config.py`.
   - Real depth names are `quick`, `standard`, `thorough`, `exhaustive`, `enterprise` in `src/agent_team_v15/config.py:914-940`, `src/agent_team_v15/config.py:961-1187`, and `src/agent_team_v15/config.py:1203-1206`.
   - `--prd` with no explicit `--depth` becomes `exhaustive` in `src/agent_team_v15/cli.py:8711-8714`.
   - `prd-large` is just `prd` plus chunking when size exceeds the threshold in `src/agent_team_v15/prd_chunking.py:49-59` and `src/agent_team_v15/cli.py:1294-1312`.

## V18.1 Fields Found In `config.py`

### Actual `V18Config` fields

Defined in `src/agent_team_v15/config.py:769-780`:

- `planner_mode`
- `execution_mode`
- `contract_mode`
- `evidence_mode`
- `git_isolation`
- `live_endpoint_check`
- `openapi_generation`
- `max_parallel_milestones`

Loaded from YAML in `src/agent_team_v15/config.py:2219-2232`.

### Non-V18 fields that still control V18.1 activation

- `milestone.enabled` in `src/agent_team_v15/config.py:296-315`
  - This is the outer gate for almost every wave-era feature.
  - Current default is `False`.
  - The milestone loop only runs when `milestone.enabled` and `(prd_mode or master_plan_exists)` in `src/agent_team_v15/cli.py:8951-8954`.
- `prd_chunking.enabled`, `prd_chunking.threshold`, `prd_chunking.max_chunk_size` in `src/agent_team_v15/config.py:357-368`
  - This is the only PRD-size aware config surface.
  - Threshold is `80000` bytes, target chunk size is `20000` bytes.

### Other V18.1-specific observations

- `contract_mode` is currently a dead flag. Search shows no non-config consumer outside `config.py`.
- `openapi_generation` is currently a dead flag. Search shows no non-config consumer outside `config.py`.
- The actual Wave C OpenAPI generation happens because `cli.py` passes `generate_openapi_contracts` into `execute_milestone_waves`, not because `v18.openapi_generation` is consulted:
  - `src/agent_team_v15/cli.py:2763-2783`
  - `src/agent_team_v15/cli.py:3313-3331`
  - `src/agent_team_v15/openapi_generator.py:54-100`
- The actual Wave D client generation happens inside `generate_openapi_contracts()`:
  - `src/agent_team_v15/openapi_generator.py:83-90`
  - `src/agent_team_v15/openapi_generator.py:282-313`
- There are two parallelism knobs, but only one is used by Phase 4:
  - `milestone.max_parallel_milestones` is loaded in `src/agent_team_v15/config.py:1652-1656`
  - Phase 4 parallel execution actually reads `v18.max_parallel_milestones` in `src/agent_team_v15/parallel_executor.py:55-76`

## Depth Levels Actually Defined

- `quick`
- `standard`
- `thorough`
- `exhaustive`
- `enterprise`

Auto-detection only emits `quick`, `thorough`, `exhaustive`, or the default `standard`; it never auto-detects `enterprise`:

- `src/agent_team_v15/config.py:31-48`
- `src/agent_team_v15/config.py:943-958`

### Current behavior of the omitted real depth: `thorough`

`thorough` is real, but it is not in the requested six-column matrix. Current `thorough` behavior:

- `planner_mode = vertical_slice`
- `execution_mode = single_call`
- `evidence_mode = disabled`
- `live_endpoint_check = False`
- `git_isolation = False`
- `max_parallel_milestones = 1`

Evidence: `src/agent_team_v15/config.py:1063-1087`.

## PRD Size Thresholds

Current large-PRD thresholds:

- `threshold = 80000` bytes in `src/agent_team_v15/config.py:366-368`
- `max_chunk_size = 20000` bytes in `src/agent_team_v15/config.py:366-368`

Where they apply:

- `src/agent_team_v15/cli.py:1294-1312`
- `src/agent_team_v15/cli.py:1444-1458`
- `src/agent_team_v15/cli.py:2135-2152`

What overrides they apply today:

- Chunking only.
- They do not change depth.
- They do not change any V18 flag.
- They do not change `git_isolation`.
- They do not change `max_parallel_milestones`.

So `prd-large` is not a separate config mode today. It is just `prd` plus chunking.

## Current Matrix

Legend:

- `On`: active in the default code path for that column.
- `Dormant`: the flag/config is on, but the default path does not reach the feature.
- `Off`: disabled in the default code path for that column.

Assumptions for the two synthetic columns:

- `prd` = default `--prd` run with no explicit `--depth`, so effective depth is `exhaustive`.
- `prd-large` = same as `prd`, plus PRD chunking when size exceeds `80000` bytes.

| V18.1 Feature | quick | standard | exhaustive | prd | prd-large | enterprise |
|---|---|---|---|---|---|---|
| wave_mode | Off | Off | On | On | On | On |
| Product IR compilation | Off | Off | Off | On | On | Off |
| Vertical-slice planner | Off | Off | On | On | On | On |
| Compile between waves | Off | Off | Dormant | Dormant | Dormant | Dormant |
| OpenAPI generation (Wave C) | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Generated client (Wave D) | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Specialist prompts (Wave E) | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Artifact store | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Scaffolding runner | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Declaration registries | Off | Off | Off | Off | Off | Dormant |
| Fix-path unification | Off | Off | On | On | On | On |
| live_endpoint_check | Off | Off | On | On | On | On |
| evidence_mode | disabled | disabled | record_only | record_only | record_only | record_only |
| Endpoint probing | Off | Off | Dormant | Dormant | Dormant | Dormant |
| Wiring scanner | Off | Off | Off | Off | Off | Off |
| i18n scanner | Off | Off | Off | Off | Off | Off |
| Playwright in Wave E | Off | Off | Off | Off | Off | Off |
| Blast-radius analysis | Off | Off | On | On | On | On |
| git_isolation | Off | Off | Off | Off | Off | On |
| max_parallel_milestones | 1 | 1 | 1 | 1 | 1 | 3 |

### Why the current matrix looks like this

The key activations are:

- Depth gating:
  - `quick`: `src/agent_team_v15/config.py:987-1043`
  - `standard`: `src/agent_team_v15/config.py:1044-1061`
  - `thorough`: `src/agent_team_v15/config.py:1063-1087`
  - `exhaustive`: `src/agent_team_v15/config.py:1088-1125`
  - `enterprise`: `src/agent_team_v15/config.py:1127-1186`
- PRD default-to-exhaustive:
  - `src/agent_team_v15/cli.py:8711-8714`
- Milestone loop hard gate:
  - `src/agent_team_v15/cli.py:8951-8954`
- Wave execution:
  - `src/agent_team_v15/cli.py:2762-2787`
  - `src/agent_team_v15/cli.py:3312-3335`
- Wave compile boundaries:
  - `src/agent_team_v15/wave_executor.py:730-747`
- Endpoint probing:
  - `src/agent_team_v15/wave_executor.py:411-483`
  - gated by `live_endpoint_check` in `src/agent_team_v15/wave_executor.py:404-408` and `src/agent_team_v15/wave_executor.py:783-799`
- Wave E scanners and Playwright injection:
  - `src/agent_team_v15/agents.py:7168-7265`
  - `src/agent_team_v15/cli.py:462-469`
- Fix-path unification and blast radius:
  - `src/agent_team_v15/cli.py:4675-4868`
  - `src/agent_team_v15/cli.py:4978-4982`
  - `src/agent_team_v15/fix_executor.py:55-88`
  - `src/agent_team_v15/fix_executor.py:293-343`

## Off/Disabled Analysis

This is the answer to "is there a good reason this is off, or was it never wired?"

### Good reasons

- `quick`: keeping `wave_mode`, `live_endpoint_check`, `evidence_mode`, `git_isolation`, endpoint probing, and Wave E scanners off is reasonable. This tier is supposed to avoid Docker, worktree overhead, and extra orchestration passes.
- `standard`: keeping `git_isolation` off is reasonable. Worktree setup and merge orchestration are probably too expensive for a medium-depth default.
- `standard`: keeping `live_endpoint_check` off is reasonable. Docker/probing is expensive and environment-sensitive.
- `hard_gate` off everywhere is reasonable today. `EvidenceLedger` explicitly softens hard-gate behavior until core collectors are operational in `src/agent_team_v15/evidence_ledger.py:163-176`.
- `enterprise` Product IR being off in the pure `enterprise` column is not a defect. Product IR is tied to `--prd`, not to depth:
  - `src/agent_team_v15/cli.py:8497-8518`
  - `src/agent_team_v15/cli.py:8551-8557`

### Missing activation or never fully wired

- `standard` has no V18 assignments at all. It never touches `planner_mode`, `execution_mode`, `contract_mode`, `evidence_mode`, `live_endpoint_check`, `openapi_generation`, `git_isolation`, or `v18.max_parallel_milestones` in `src/agent_team_v15/config.py:1044-1061`.
- `milestone.enabled` is never auto-enabled by any depth. Default remains `False` in `src/agent_team_v15/config.py:304`, so wave-only features stay dormant even when `execution_mode="wave"`.
- `exhaustive`, `prd`, and `enterprise` all stop at `record_only`:
  - `src/agent_team_v15/config.py:1123`
  - `src/agent_team_v15/config.py:1182`
  - That leaves Wave E wiring scanner, i18n scanner, and Playwright tool injection off:
    - `src/agent_team_v15/agents.py:7200-7265`
    - `src/agent_team_v15/cli.py:463-469`
    - `src/agent_team_v15/audit_agent.py:1830-1832`
- `prd` and `prd-large` do not auto-enable `git_isolation`, even though those are the builds that benefit most from merge safety and parallel milestone throughput.
- `prd-large` has no size-aware flag override at all. The only size-aware behavior is chunking:
  - `src/agent_team_v15/prd_chunking.py:49-59`
  - `src/agent_team_v15/cli.py:1297-1307`
- `contract_mode` and `openapi_generation` are defined and depth-set, but not consumed outside config loading and gating. They are currently descriptive flags, not operative gates.
- `milestone.max_parallel_milestones` exists, but Phase 4 uses `v18.max_parallel_milestones`. The old field does not drive parallel throughput.

## Recommended Matrix

This is the matrix I would target with the current architecture and with `config.py` changes only.

Legend:

- `On`: should execute in the default path for that column after config fixes.
- `Conditional`: config can enable it, but `cli.py` still requires PRD mode or an existing master plan before milestones run.
- `Off`: intentionally left off for cost or safety reasons.

| V18.1 Feature | quick | standard | exhaustive | prd | prd-large | enterprise |
|---|---|---|---|---|---|---|
| wave_mode | Off | On | On | On | On | On |
| Product IR compilation | Off | Off | Off | On | On | Off |
| Vertical-slice planner | Off | On | On | On | On | On |
| Compile between waves | Off | Conditional | Conditional | On | On | Conditional |
| OpenAPI generation (Wave C) | Off | Conditional | Conditional | On | On | Conditional |
| Generated client (Wave D) | Off | Conditional | Conditional | On | On | Conditional |
| Specialist prompts (Wave E) | Off | Conditional | Conditional | On | On | Conditional |
| Artifact store | Off | Conditional | Conditional | On | On | Conditional |
| Scaffolding runner | Off | Conditional | Conditional | On | On | Conditional |
| Declaration registries | Off | Off | Off | On | On | Conditional |
| Fix-path unification | Off | Off | On | On | On | On |
| live_endpoint_check | Off | Off | On | On | On | On |
| evidence_mode | disabled | record_only | soft_gate | soft_gate | soft_gate | soft_gate |
| Endpoint probing | Off | Off | Conditional | On | On | Conditional |
| Wiring scanner | Off | Off | Conditional | On | On | Conditional |
| i18n scanner | Off | Off | Conditional | On | On | Conditional |
| Playwright in Wave E | Off | Off | Conditional | On | On | Conditional |
| Blast-radius analysis | Off | Off | On | On | On | On |
| git_isolation | Off | Off | Off | On | On | On |
| max_parallel_milestones | 1 | 1 | 1 | 3 | 3 | 3 |

### Why I would leave some features off

- `quick`: all heavy V18 features should stay off.
- `standard`: keep `live_endpoint_check`, Wave E scanners, Playwright-in-Wave-E, and `git_isolation` off. This tier should get structural V18 benefits without Docker and worktree cost.
- `exhaustive`: keep `git_isolation` off by default for non-PRD exhaustive builds. This still gives full wave/evidence benefits without forcing worktree overhead onto every exhaustive run.
- `hard_gate`: still leave off everywhere until collector coverage is consistently trustworthy.

### Important constraint

If you insist that `prd-large` should differ from `prd`, that is not implementable in `config.py` alone today. `apply_depth_quality_gating()` only receives `prd_mode: bool`, not a large-PRD signal:

- `src/agent_team_v15/config.py:961-966`
- `src/agent_team_v15/cli.py:8918-8919`

So the best config-only recommendation is to make `prd` and `prd-large` identical, except for the chunking behavior that already exists.

## Gap List

These are the main mismatches between the current code and the recommended matrix.

1. `standard` is effectively pre-V18.1. It never opts into vertical slices, waves, or OpenAPI/client generation.
2. `milestone.enabled` remains `False` at every depth, so wave-only features are configured but dormant.
3. `exhaustive`, `prd`, and `enterprise` never move past `record_only`, so Wave E verification never upgrades into wiring/i18n/browser checks.
4. `prd` and `prd-large` do not turn on `git_isolation` or parallel milestone throughput, even though those are the highest-value modes for Phase 4.
5. `prd-large` has no size-aware config overrides at all. The 80KB threshold only affects chunking.
6. `contract_mode` and `openapi_generation` are currently dead flags; searches show no non-config consumer outside `config.py`.
7. There is a stale split between `milestone.max_parallel_milestones` and `v18.max_parallel_milestones`; only the latter matters for Phase 4.

## Exact `config.py` Changes To Implement The Recommended Matrix

These are the config-only edits I would make.

### 1. Standard depth: add the structural V18 defaults

Edit `src/agent_team_v15/config.py:1044-1061` and add:

- `_gate("milestone.enabled", True, config.milestone, "enabled")`
- `_gate("v18.planner_mode", "vertical_slice", config.v18, "planner_mode")`
- `_gate("v18.execution_mode", "wave", config.v18, "execution_mode")`
- `_gate("v18.contract_mode", "openapi", config.v18, "contract_mode")`
- `_gate("v18.evidence_mode", "record_only", config.v18, "evidence_mode")`
- `_gate("v18.openapi_generation", True, config.v18, "openapi_generation")`

Rationale: give `standard` the structural V18 pipeline without Docker probing or git-isolation overhead.

### 2. Exhaustive depth: promote evidence from `record_only` to `soft_gate`

Edit `src/agent_team_v15/config.py:1123`:

- change `_gate("v18.evidence_mode", "record_only", config.v18, "evidence_mode")`
- to `_gate("v18.evidence_mode", "soft_gate", config.v18, "evidence_mode")`

### 3. Exhaustive depth: enable milestones so PRD/existing-master-plan runs actually enter waves

Edit `src/agent_team_v15/config.py:1088-1125` and add:

- `_gate("milestone.enabled", True, config.milestone, "enabled")`

### 4. Exhaustive depth: turn on Phase 4 isolation/parallelism for PRD runs

Still inside the `exhaustive` branch in `src/agent_team_v15/config.py:1088-1125`, add:

```python
        if prd_mode:
            _gate("v18.git_isolation", True, config.v18, "git_isolation")
            _gate("v18.max_parallel_milestones", 3, config.v18, "max_parallel_milestones")
```

Rationale: this makes default `prd` and `prd-large` runs enter the Phase 4 isolation path without forcing worktrees onto every non-PRD exhaustive run.

### 5. Enterprise depth: enable milestones explicitly

Edit `src/agent_team_v15/config.py:1127-1186` and add:

- `_gate("milestone.enabled", True, config.milestone, "enabled")`

### 6. Enterprise depth: promote evidence from `record_only` to `soft_gate`

Edit `src/agent_team_v15/config.py:1182`:

- change `_gate("v18.evidence_mode", "record_only", config.v18, "evidence_mode")`
- to `_gate("v18.evidence_mode", "soft_gate", config.v18, "evidence_mode")`

## What `config.py` Alone Cannot Fix

These are outside the scope of a config-only patch:

1. `prd-large` cannot diverge from `prd` at the config layer, because size is never passed into `apply_depth_quality_gating()`.
2. Non-PRD, no-master-plan runs cannot be forced into milestone execution from `config.py` alone, because `cli.py` hard-codes:
   - `config.milestone.enabled and (_is_prd_mode or _master_plan_exists)` at `src/agent_team_v15/cli.py:8951-8954`

So if you want:

- a separate `prd-large` activation profile, or
- standard/exhaustive plain tasks to always run milestones/waves without a PRD or pre-existing master plan,

that will require a small `cli.py` change, not just `config.py`.

