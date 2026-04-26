# Bug #5 — PRD-vs-CWD Location Ambiguity

> **Status:** Workaround in use (colocate PRD with `--cwd`). Root cause not fixed.
>
> **Discovered:** 2026-04-13 smoke test, attempt 6 (first clean-path attempt at `C:/smoke/taskflow/output/`)
>
> **Severity:** HIGH — causes "silent successful" builds that generate zero code while exiting with code 0 and spending $10+ on recovery passes

## ⚠️ NOTE TO THE IMPLEMENTING AGENT

**Investigate before changing anything.** This document is the empirical symptom + working hypothesis. Verify both before writing code:

1. **Reproduce the symptom.** Put the PRD at `/some/path/PRD.md`, run with `--cwd /different/path/output/`, observe where `MASTER_PLAN.md` actually gets written.
2. **Inspect the Wave A / planner prompt** to confirm whether it injects the PRD path (which the LLM then treats as "the project root") vs the `--cwd` path (the actual build dir). If the prompt says both, check which one the LLM prefers in its Bash calls.
3. **Read `agents.py` decomposer / planner prompt construction** end-to-end. Look for path handling that might use `Path(prd_path).parent` as the working dir.

This plan proposes one cure; there are two plausible alternative cures. Pick the one that the investigation reveals is actually necessary.

---

## Symptom

When `--cwd` (build directory) is different from the PRD's directory, the decomposer agent writes planning artifacts (`MASTER_PLAN.md`, `milestones/milestone-N/REQUIREMENTS.md`, `MASTER_PLAN.json`) to the **PRD's directory**, not to the build's `.agent-team/`. The runtime then looks for `MASTER_PLAN.md` at `<cwd>/.agent-team/MASTER_PLAN.md`, doesn't find it, logs `"Decomposition did not create MASTER_PLAN.md. Aborting milestone loop."`, and continues to recovery passes on an empty project. Build "completes" with exit code 0 having written no code.

## Empirical Evidence (from 2026-04-13 attempt 6)

- Launch: `cd /c/smoke/taskflow && python -m agent_team_v15 --prd /c/smoke/taskflow/PRD.md --config /c/smoke/taskflow/config.yaml --cwd /c/smoke/taskflow/output --depth exhaustive`
- Process CWD: `/c/smoke/taskflow`
- Build CWD flag: `/c/smoke/taskflow/output`
- PRD at: `/c/smoke/taskflow/PRD.md`

### Where the planner actually wrote

```
WRONG (PRD's dir):
  /c/smoke/taskflow/.agent-team/MASTER_PLAN.md        ✓ file exists
  /c/smoke/taskflow/.agent-team/milestones/m1..m7/    ✓ dirs exist

MISSING (build's cwd):
  /c/smoke/taskflow/output/.agent-team/MASTER_PLAN.md ✗ not there

  But other files DID correctly land in output/.agent-team/:
    /c/smoke/taskflow/output/.agent-team/REQUIREMENTS.md           ✓ correct
    /c/smoke/taskflow/output/.agent-team/UI_DESIGN_TOKENS.json     ✓ correct
    /c/smoke/taskflow/output/.agent-team/UI_REQUIREMENTS.md        ✓ correct
    /c/smoke/taskflow/output/.agent-team/CONTRACTS.json            ✓ correct (recovery pass)
```

So: **some** artifacts land in the right place. The decomposer specifically doesn't. That narrows the root cause to how the decomposer prompt / agent is configured, not to a global CWD misunderstanding.

### The `--cwd` value reached the codebase-map phase correctly

BUILD_LOG from attempt 6:
```
Phase 0.5: Codebase Map
│ Directory: C:/smoke/taskflow/output   ← correct
```

So `--cwd` propagates correctly through Phase 0. The drift happens somewhere in Phase 1's decomposer-agent dispatch.

### Why colocating PRD + CWD avoids the bug

Subsequent attempts (7 = clean-attempt-1, 8 = clean-attempt-2) put PRD at `/c/smoke/clean/PRD.md` and `--cwd /c/smoke/clean/`. The decomposer writes planning artifacts to `/c/smoke/clean/.agent-team/MASTER_PLAN.md` — correct because PRD's dir IS the build dir.

## Working Hypothesis

The decomposer agent prompt tells the LLM "read the PRD at `<prd_path>`" and then the LLM uses `Path(prd_path).parent` as its inferred working directory for file writes — mirroring what a human would do. The prompt probably doesn't explicitly say "write all artifacts to `<cwd>/.agent-team/`, regardless of where the PRD lives". So the LLM improvises.

Alternative hypothesis 1: the ClaudeAgentOptions for the decomposer are constructed without `cwd=`, so the SDK spawns the subprocess with Python's process CWD (where `python -m agent_team_v15` was started — in attempt 6, that was `/c/smoke/taskflow`).

Alternative hypothesis 2: the decomposer's file-writing tool is restricted to the `--cwd` dir, but the prompt builder passes `Path(prd_path).parent` as the anchor when constructing relative file paths in the prompt.

Any of these would explain the symptom. Investigation step 3 of the note above will reveal which.

## Scope

Changes:
- Whatever file in `src/agent_team_v15/agents.py` constructs the Wave 1 decomposer prompt — ensure it passes the build `--cwd`, not the PRD's parent, as the anchor for artifact paths
- Whatever file constructs the ClaudeAgentOptions for the decomposer subprocess — ensure `options.cwd = build_cwd`
- Prompt text — add an unambiguous "Write all artifacts to `{cwd}/.agent-team/` — even though the PRD is at `{prd_path}`, all output files go under `{cwd}/.agent-team/`" instruction

Not in scope:
- Changing the CLI's `--prd` or `--cwd` argument handling
- Changing where OTHER artifacts land (they're already correct)
- Refactoring the decomposer into a subprocess worker (overkill for this issue)

## Proposed Cures (pick one after investigation)

### Cure A — fix the prompt (most likely correct)

In the decomposer prompt template, locate the block that tells the LLM where to write files. Currently likely something like "Create `.agent-team/MASTER_PLAN.md`" (relative). Change to absolute:

```
You MUST write all artifacts under the build directory:
  - {cwd_absolute}/.agent-team/MASTER_PLAN.md
  - {cwd_absolute}/.agent-team/MASTER_PLAN.json
  - {cwd_absolute}/.agent-team/milestones/milestone-N/REQUIREMENTS.md

Do NOT use the PRD's directory ({prd_path.parent}) as the anchor. The PRD
is input only; all OUTPUT goes under {cwd_absolute}/.
```

Where `cwd_absolute` is `Path(cwd).resolve()` computed at prompt-build time.

### Cure B — fix the SDK options (if Cure A insufficient)

Ensure `ClaudeAgentOptions.cwd` is set to the build `--cwd` for the decomposer subprocess. Find where the decomposer options are constructed (likely `_build_options` in cli.py or similar) and verify `options.cwd = str(Path(cwd).resolve())`.

### Cure C — normalize before Wave B starts (workaround that graduates to fix)

After the decomposer completes, before Phase 1.5 starts, check both `<cwd>/.agent-team/MASTER_PLAN.md` AND `<prd_path.parent>/.agent-team/MASTER_PLAN.md`. If only the second exists, `mv` everything under `<prd_path.parent>/.agent-team/` into `<cwd>/.agent-team/` with a warning. This is band-aid but prevents the silent-failure mode if Cure A/B don't hold.

Strongly recommend doing Cure A + Cure C (belt-and-suspenders).

## Investigation Checklist

- [ ] Locate the decomposer prompt template and confirm it mentions file paths relatively or absolutely
- [ ] Trace `ClaudeAgentOptions` construction for the decomposer — verify `cwd` param
- [ ] Confirm that OTHER artifacts (REQUIREMENTS.md, UI_DESIGN_TOKENS.json) use a DIFFERENT file-writing path that doesn't have this bug — and understand WHY they don't drift (this reveals the exact difference between the working and broken paths)
- [ ] Confirm the decomposer writes via the LLM's Bash/Write tools (subject to this bug) vs via Python deterministic file writes (which wouldn't drift)

## Acceptance Criteria

The fix is complete when:

- [ ] `python -m agent_team_v15 --prd /path/A/PRD.md --cwd /path/B/ --depth exhaustive` produces `MASTER_PLAN.md` and `milestones/*/REQUIREMENTS.md` under `/path/B/.agent-team/`, not `/path/A/.agent-team/`
- [ ] Re-running the 2026-04-13 smoke test with `--prd /c/smoke/taskflow/PRD.md --cwd /c/smoke/taskflow/output/` (split layout) produces planning artifacts in `/c/smoke/taskflow/output/.agent-team/`
- [ ] Build does not abort with "Decomposition did not create MASTER_PLAN.md" in any layout
- [ ] Test coverage: a new test spawns the decomposer with PRD and CWD in different directories and asserts MASTER_PLAN.md lands at `<cwd>/.agent-team/MASTER_PLAN.md`
- [ ] No regression when PRD and CWD are the same directory (the "convenient" layout)

## Risk Notes

- **Don't break the convenient layout.** Build A and Build B used the "PRD inside build dir" layout, and the current workaround uses that layout. The fix must not break it.
- **Other artifacts might have the same latent bug.** REQUIREMENTS.md lands correctly today — but that might be coincidence (the agent that writes it happens to use the right path resolution). If the fix changes decomposer behavior, verify other artifacts still land correctly.
- **Prompt changes can regress LLM output shape.** If you modify the decomposer prompt, re-verify that MASTER_PLAN.md still parses cleanly (the existing parser is regex-based and picky about section headers).

## Done When

- Split-layout builds (PRD at `/A/`, cwd at `/B/`) produce planning artifacts in `/B/.agent-team/`
- Colocated-layout builds (PRD at `/A/PRD.md`, cwd at `/A/`) continue to work
- Tests pass
- 2026-04-13 smoke test re-run with split layout succeeds past Phase 1
