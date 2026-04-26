# Pre-Rerun Cleanup — Close Every Open Item Before the Smoke Test

> **Target session:** fresh Claude Code session. Branch: `bug-9-tier-2-stack-contract-validator` (HEAD: `cdd7b83`). Verification report at `docs/plans/2026-04-14-tier2-and-fix-verification-report.md`.
>
> **Goal:** Make `pytest tests/` fully green AND close 3 specific open items, so the smoke test re-run starts from a clean baseline.

---

## What's open (3 items + suite must be green)

1. **Bug #2 regression** — 5 failing tests in `tests/test_milestone_manager.py::TestParseDeps::*`. The defensive filter drops legacy `m-1` (hyphenated) shorthand.
2. **Bug #8 partial** — `scripts/generate-openapi.ts` is scaffolded but `package.json` is NOT updated to wire `tsx` devDep + `@nestjs/swagger` runtime dep + `scripts.generate-openapi` entry.
3. **Bug #10 deviation** — implementation works but deviates from the heartbeat-file watchdog design in the plan. Either ratify (and update the plan) or restore (and file a follow-up).

After all three are closed, `pytest tests/ -v` must report **0 failed**.

---

## Job 1 — Fix Bug #2 regression

### Cause

`_parse_deps` short-form regex is `^[Mm](\d+)$` — does not accept the hyphenated `m-1` form. Old code would keep `m-1` as-is (passed downstream). New defensive filter requires `^milestone-\d+$` after normalization, so unnormalized `m-1` gets dropped.

### Fix (1 line)

In `src/agent_team_v15/milestone_manager.py`, extend the short-form regex to accept an optional hyphen:

```python
# before
_short_form = re.compile(r"^[Mm](\d+)$")

# after
_short_form = re.compile(r"^[Mm]-?(\d+)$")
```

### Verify

```bash
pytest tests/test_milestone_manager.py::TestParseDeps -v
# Expected: all 5 previously-failing tests now pass
```

Then sanity-check the prose-bullet case still works:

```bash
python -c "
from agent_team_v15.milestone_manager import _parse_deps
print(_parse_deps('M1, m-2, milestone-3'))
# Expected: ['milestone-1', 'milestone-2', 'milestone-3']
print(_parse_deps('- Description: Scaffold, M1, Next.js web app'))
# Expected: ['milestone-1'] with 2 warnings logged
"
```

### Commit

```
fix(plan-validator): accept hyphenated m-N shorthand in _parse_deps regression
```

---

## Job 2 — Complete Bug #8

### What's missing

Per `docs/plans/2026-04-13-wave-c-openapi-script-scaffold-plan.md` §1.2 ("Wire it into the NestJS scaffolder"), the scaffolder must also ensure `package.json` has:

- `scripts.generate-openapi: "tsx scripts/generate-openapi.ts"`
- `devDependencies.tsx` (latest stable, e.g., `^4.7.0`)
- `dependencies.@nestjs/swagger` (latest compatible major, e.g., `^7.0.0` or whatever Codex's typical Wave B output uses)

### Fix (~30 LOC)

Add a helper to `src/agent_team_v15/scaffold_runner.py`:

```python
def _ensure_package_json_openapi_script(project_root: Path) -> bool:
    """
    Ensure package.json has the generate-openapi script + tsx devDep + nestjs/swagger dep.
    Idempotent — no-op if already present. Returns True if anything was modified.
    """
    pkg_path = project_root / "package.json"
    if not pkg_path.is_file():
        return False  # No package.json to update; the scaffolder will create one elsewhere

    import json
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    modified = False

    scripts = data.setdefault("scripts", {})
    if scripts.get("generate-openapi") != "tsx scripts/generate-openapi.ts":
        scripts["generate-openapi"] = "tsx scripts/generate-openapi.ts"
        modified = True

    dev_deps = data.setdefault("devDependencies", {})
    if "tsx" not in dev_deps:
        dev_deps["tsx"] = "^4.7.0"
        modified = True

    deps = data.setdefault("dependencies", {})
    if "@nestjs/swagger" not in deps:
        deps["@nestjs/swagger"] = "^7.0.0"
        modified = True

    if modified:
        pkg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return modified
```

Call it from `_scaffold_nestjs` (or wherever the OpenAPI script is currently dropped — locate the existing call-site for the Bug #8 implementation in `cdd7b83` and add this call right next to it).

### Tests

Add to `tests/test_scaffold_runner.py`:

- `test_scaffold_nestjs_adds_generate_openapi_script_entry` — verify `scripts.generate-openapi` is set after scaffold
- `test_scaffold_nestjs_adds_tsx_devdependency` — verify `devDependencies.tsx` is set
- `test_scaffold_nestjs_adds_swagger_dependency` — verify `dependencies.@nestjs/swagger` is set
- `test_scaffold_idempotent_when_entries_already_present` — set them all manually first, run scaffold, verify no duplicate writes (file content unchanged byte-for-byte)
- `test_scaffold_when_no_package_json_exists` — verify no crash, returns False, doesn't create empty file

### Verify

```bash
pytest tests/test_scaffold_runner.py -v
# Expected: all new + existing tests pass
```

### Commit

```
fix(scaffold): wire tsx devDep + @nestjs/swagger + npm script for Bug #8 completion
```

---

## Job 3 — Resolve Bug #10 deviation

### Investigate

```bash
git log --oneline 51a7409..cdd7b83 -- src/agent_team_v15/wave_executor.py
git diff 51a7409..cdd7b83 -- src/agent_team_v15/wave_executor.py
```

Read the implementation. Compare against `docs/plans/2026-04-13-wave-d5-silent-hang-plan.md` §"Proposed Implementation" (heartbeat file approach).

### Decide one of two outcomes

**Outcome A — Ratify the alternate design** (likely the right call; the heartbeat-file design was a hypothesis, the implementer probably found a cleaner internal hook)

If the implementation:
- Catches genuine hangs within a configurable timeout (default ~30 min)
- Writes a hang report when fired
- Has at least one retry on timeout
- Has tests proving it fires when it should and doesn't fire when it shouldn't

…then ratify. **Update the plan** at `docs/plans/2026-04-13-wave-d5-silent-hang-plan.md`:

- Add a new section at the top: "## Implementation Note (post-ratification)"
- Document what the implementer actually built
- Explain why it's equivalent or better than the heartbeat-file approach
- Note any tradeoffs (e.g., "no per-second progress tracking, but a wave-level timeout suffices in practice")
- Keep the original plan content below for historical context

**Outcome B — Restore the heartbeat-file design**

Only do this if the alternate approach has a concrete defect: hangs detected too slowly, no hang reports, untestable, etc. If you go this route:

- File a new plan `docs/plans/2026-04-14-wave-watchdog-restoration-plan.md` documenting the gap
- Do NOT implement the restoration in this session — that's a separate workstream; this session is just unblocking the smoke test
- Ratify the existing implementation as "good enough for the re-run" with a follow-up ticket

### Commit (whichever outcome)

```
docs(bug-10): ratify watchdog implementation; update plan with rationale
```

OR

```
docs(bug-10): file restoration plan; current implementation acceptable for re-run
```

---

## Job 4 — Verify the suite is green

```bash
# Full suite, verbose
pytest tests/ -v 2>&1 | tee /tmp/full_suite_after_cleanup.log
grep -E "passed|failed|error" /tmp/full_suite_after_cleanup.log | tail -5
```

**Expected:** 0 failed. Skips and warnings are fine. If anything else is failing that ISN'T from our 11 fixes, investigate — it may be pre-existing baseline noise. Document either way in the cleanup report.

---

## Job 5 — Update the smoke-test re-run brief

The brief at `docs/plans/2026-04-14-smoke-test-rerun-handoff.md` was written assuming Tier 2 had not yet landed and assuming all fixes were intact. Update it now to reflect:

1. Tier 2 IS in (`bug-9-tier-2-stack-contract-validator` branch, commits `64cf3f1`, `0cde844`, `76a8fa6`, `cdd7b83`)
2. The pre-flight verification grep set should be expanded with Tier 2 sentinels:
   ```bash
   grep -n "_BUILTIN_STACK_CONTRACTS\|class StackContract" src/agent_team_v15/stack_contract.py
   grep -n "stack_contract_violations" src/agent_team_v15/wave_executor.py
   grep -n "stack_contract" src/agent_team_v15/state.py
   ```
3. The fix-verification table should add a row for Tier 2 (validator output expected in per-wave telemetry, expected to be empty for healthy runs)
4. Add explicit note: "Bug #2 m-1 regression resolved in commit XXX; Bug #8 package.json wiring completed in commit YYY; Bug #10 watchdog ratified per plan."
5. Confirm the "Expected outcome" section's predictions still hold (check whether anything in `cdd7b83` changes the expected wave-by-wave timing or behavior)

### Commit

```
docs(rerun-brief): incorporate Tier 2 + cleanup commits into pre-flight checklist
```

---

## Job 6 — Produce the cleanup report

Save to `docs/plans/2026-04-14-pre-rerun-cleanup-report.md`. Include:

1. **Summary** — all 3 items closed? Suite green? Re-run brief updated?
2. **Bug #2 fix** — the 1-line regex change, before/after `_parse_deps` behavior on `m-1`
3. **Bug #8 fix** — diff of `_ensure_package_json_openapi_script` + new test names
4. **Bug #10 decision** — Ratify or Restore, with link to the updated/new plan
5. **Test suite results** — counts, with attention to any non-zero failures
6. **Re-run readiness** — is the smoke test now safe to launch? Any residual concerns?
7. **Commits in this session** — list with one-line summaries

---

## Guardrails

- **Stay on the same branch** (`bug-9-tier-2-stack-contract-validator`). All cleanup commits go on top of `cdd7b83`. Push at the end.
- **Don't refactor.** This is a closure session, not a cleanup session in the broader sense. Three specific items + green suite + brief update + report. Nothing else.
- **Don't launch the smoke test.** Separate session. Your last commit message should make clear that the re-run is unblocked but not started.
- **Don't touch the unrelated worktree changes** (`product_ir.py`, `tests/test_product_ir.py`, `tests/test_v18_stage1.py`, `docs/run-artifact*`). Leave them alone.
- **Don't skip tests to make the suite green.** If a test legitimately needs a skip, document the reason and link a plan/bug. If you can't justify the skip, don't add it.

---

## Success criteria

- [ ] `pytest tests/test_milestone_manager.py::TestParseDeps -v` reports 0 failed
- [ ] `pytest tests/test_scaffold_runner.py -v` reports 0 failed AND covers tsx + swagger + scripts entries
- [ ] Bug #10 decision documented in either the existing plan (Outcome A) or a new plan (Outcome B)
- [ ] `pytest tests/ -v` reports 0 failed for the full suite
- [ ] `docs/plans/2026-04-14-smoke-test-rerun-handoff.md` updated to reflect Tier 2 + cleanup commits
- [ ] `docs/plans/2026-04-14-pre-rerun-cleanup-report.md` produced
- [ ] All commits pushed to `bug-9-tier-2-stack-contract-validator`
- [ ] Final commit message clearly states "smoke test re-run unblocked"

---

## If stuck

1. Read the Bug #2 plan section in `docs/plans/2026-04-13-in-tree-fixes-summary.md` §2 to understand the original intent
2. Read `docs/plans/2026-04-13-wave-c-openapi-script-scaffold-plan.md` §1.2 + §2.4 for the Bug #8 plan details
3. Read `docs/plans/2026-04-13-wave-d5-silent-hang-plan.md` Proposed Implementation section for the Bug #10 design
4. Read the verification report at `docs/plans/2026-04-14-tier2-and-fix-verification-report.md` for the implementer's findings

If still stuck, surface to the user with: what you tried, what you expected, what happened, what you don't understand. Don't guess.

---

## Estimated effort

- Bug #2 fix + tests verify: **5 min**
- Bug #8 helper + 5 tests: **30 min**
- Bug #10 review + decision + plan update: **20 min**
- Full pytest run + analysis: **15 min**
- Re-run brief update: **15 min**
- Cleanup report: **15 min**

**Total: ~100 min for a focused agent.** Then the smoke test re-run is unblocked.
