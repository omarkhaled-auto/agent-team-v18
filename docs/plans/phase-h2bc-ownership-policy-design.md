# Phase H2bc Ownership Policy Design

## Decision

Keep the current ownership-policy format and update the existing file in place.

The canonical policy remains `docs/SCAFFOLD_OWNERSHIP.md`, using:

- Markdown headings and prose
- One or more fenced `yaml` blocks
- YAML list rows with required keys:
  - `path`
  - `owner`
  - `optional`
- Optional keys:
  - `emits_stub`
  - `audit_expected`
  - `notes`

This is the only format that satisfies all current consumers without adding a second parser.

## Why This Format Stays

- `load_ownership_contract()` already parses fenced YAML blocks:
  `src/agent_team_v15/scaffold_runner.py:174-229`
- `notes:` prose is already tolerated by the pre-strip step:
  `src/agent_team_v15/scaffold_runner.py:147-171`
- `wave_a_schema_validator.load_scaffold_ownership_paths()` still regex-scans raw `- path:` lines:
  `src/agent_team_v15/wave_a_schema_validator.py:860-883`

Changing to pure YAML, front matter, or a markdown table would break at least one current caller.

## Corrected H2bc Framing

At the current branch state on April 20, 2026, the policy file already exists in source control:

- `docs/SCAFFOLD_OWNERSHIP.md`
- last modified in this repo on April 16, 2026

The smoke failure came from runtime resolution against the generated worktree, not from source control lacking the file.

H2bc should therefore:

1. Update the existing policy file where needed.
2. Make runtime readers resolve it from either the worktree or the repo source.
3. Add a fail-loud flag for the contradiction case: flag enabled but policy unresolved.

## Required Runtime Resolution

Add one shared resolver in `scaffold_runner.py`:

1. Try `<workspace>/docs/SCAFFOLD_OWNERSHIP.md`
2. Fallback to repo-root `docs/SCAFFOLD_OWNERSHIP.md` resolved from module location

Do not keep ad hoc path resolution in each caller.

## Required New Flag

Add:

- `v18.ownership_policy_required: bool = False`

Behavior:

- `False`: preserve WARN-and-skip behavior
- `True`: raise `OwnershipPolicyMissingError` when the policy cannot be resolved

Consume the flag at the load boundary in:

- `ownership_enforcer._load_scaffold_owned_paths`
- `wave_executor._maybe_run_spec_reconciliation`
- `wave_executor._maybe_run_scaffold_verifier`
- `scaffold_runner._maybe_validate_ownership`
- prompt ownership-claim loading can stay fail-open unless explicitly required by call path

## Policy Content Additions Needed For H2bc

The current file is already broad enough to remain canonical, but H2bc should make it easier for runtime checks to consume deliverables deterministically.

Keep the existing per-path rows, and add:

- A short H2bc revision note at the top
- A dedicated section for required deliverables that the scaffold verifier can read from the same parsed rows, not from prose only
- Explicit coverage for:
  - `apps/api/Dockerfile`
  - `apps/web/Dockerfile`
  - `docker-compose.yml`
  - `.env.example`
  - `apps/api/.env.example`

The verifier should read this from parsed rows or a constrained extension of parsed metadata, not from free-form markdown prose.

## Ownership Claims That Matter For H2bc

The policy must continue to express:

- Scaffold-owned baseline files
- Wave-B-owned files such as `apps/api/Dockerfile`
- Wave-D-owned files
- Generator-owned files
- Optional rows
- Stub-emission rows
- Audit-expected rows

This is already supported by the current schema.

## Size / Risk

- Current file length is already in the expected range for this phase
- No format HALT is needed
- No parser-compatibility HALT is needed

The real H2bc risk is not document size; it is fail-open runtime resolution.
