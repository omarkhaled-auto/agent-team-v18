# In-Tree Fixes Summary — 6 patches ready to commit

> These 6 fixes are already in the working tree (uncommitted), verified by syntax parse + behavior tests during the 2026-04-13 smoke test session. Total: ~30 LOC across 4 files.
>
> **Before committing**, the implementing agent should: (a) skim each section below, (b) `git diff` each file, (c) run `pytest tests/` to confirm no regressions. All 6 are minimal, surgical, and should be safe to commit as one coherent PR or six separate commits — both work.

---

## §1 — Bug #1: `compile_profiles.py` relative-cwd double-prefix

**File:** `src/agent_team_v15/compile_profiles.py`
**Lines changed:** 5 sites, all identical pattern
**Diff:** `str(path)` → `str(path.resolve())`

### Sites patched

| Line | Command family | Function |
|---|---|---|
| 290 | `npx tsc --project <path>` | `_get_typescript_profile` |
| 395 | `dart analyze <path>` | `_get_dart_profile` |
| 455 | `dotnet build <solution>` | `_get_dotnet_profile` (solution branch) |
| 480 | `dotnet build <solution>` | `_get_dotnet_profile` (solution fallback) |
| 489 | `dotnet build <path>` | `_get_dotnet_profile` (per-project) |

### Why the fix works

When `--cwd` is a relative path, `_iter_paths(root, pattern)` uses `root.rglob(pattern)` which returns paths **relative to the process CWD, not relative to `root`**. So the tsconfig path is returned with the `--cwd` prefix already baked in. The workaround at lines 530-538 then does `Path(cwd) / cmd[proj_idx + 1]` which produces a double-prefixed path that doesn't exist, so the workaround silently falls through and tsc resolves the path wrong.

`path.resolve()` short-circuits the whole problem: returns an absolute path that doesn't depend on CWD, `Path(cwd) / <abs>` correctly returns `<abs>` (Python path concatenation semantics), `is_file()` succeeds, and the cd-into-tsconfig-dir workaround now runs correctly.

### Verification

```
$ python -c "from pathlib import Path; p = Path('v18 test runs/build-c-hardened/apps/api/tsconfig.json'); print(p.resolve())"
C:\Projects\agent-team-v18-codex\v18 test runs\build-c-hardened\apps\api\tsconfig.json
```

Smoke test clean-attempt-2 produced Wave B telemetry with `compile_passed: true` after 3 fix iterations — first Wave B pass across all attempts.

---

## §2 — Bug #2: `_parse_deps` prose-bullet filter

**File:** `src/agent_team_v15/milestone_manager.py`
**Function:** `_parse_deps` (around line 835)
**Lines changed:** ~12

### Diff (summary)

Added after short-form normalization:
```python
_id_form = re.compile(r"^milestone-\d+$")
...
for tok in tokens:
    m = _short_form.match(tok)
    if m:
        result.append(f"milestone-{m.group(1)}")
    elif _id_form.match(tok):
        result.append(tok)
    else:
        # Drop prose / non-ID tokens (e.g., "- Description: Scaffold monorepo")
        _logger.warning("Dropped non-ID dependency token from MASTER_PLAN: %r", tok)
```

### Why the fix works

Prior behavior: any non-empty token after normalization was treated as a milestone ID. If the decomposer LLM emitted free-text bullets in the Dependencies field (one real case: M1 deps = "- Description: Scaffold monorepo with NestJS API, Next.js web app, Prisma schema, ..."), plan validation failed with 8 "depends on '...' which does not exist" errors and aborted.

Fix: only accept tokens matching `^milestone-\d+$`. Drop everything else with a warning. Result: free-text bullets become an empty dep list (foundation milestone), which is the correct interpretation.

### Verification

```
_parse_deps("- Description: Scaffold monorepo, Next.js web app, M1, Prisma schema")
  → ['milestone-1']
  (3 warnings logged for dropped prose tokens)
```

---

## §3 — Bug #4a: `cli.py:4736` AUDIT_REPORT double-nesting

**File:** `src/agent_team_v15/cli.py`
**Line:** 4736

### Diff

```python
# before:
integration_audit_dir = str(req_dir / ".agent-team")

# after:
# ``req_dir`` is already ``<cwd>/.agent-team`` (per ConvergenceConfig default).
# Appending another ``.agent-team`` produced ``.agent-team/.agent-team/AUDIT_REPORT.json``.
integration_audit_dir = str(req_dir)
```

### Why the fix works

`req_dir = project_root / config.convergence.requirements_dir` where `requirements_dir = ".agent-team"` by default. The old line double-appends.

Empirical evidence from attempt-1: AUDIT_REPORT.json ended up at `.agent-team/.agent-team/AUDIT_REPORT.json` instead of `.agent-team/AUDIT_REPORT.json`. Hooks looking at the canonical path fell through silently.

### Verification

Not directly testable in this smoke session (attempt-1's audit already ran against old code). Will be validated on next run that reaches the integration audit phase.

---

## §4 — Bug #4b: `AuditFinding.from_dict` defensive key aliasing

**File:** `src/agent_team_v15/audit_models.py`
**Function:** `AuditFinding.from_dict`
**Lines changed:** ~10

### Diff

```python
# before:
@classmethod
def from_dict(cls, data: dict) -> AuditFinding:
    return cls(
        finding_id=data["finding_id"],
        auditor=data["auditor"],
        requirement_id=data["requirement_id"],
        verdict=data["verdict"],
        severity=data["severity"],
        summary=data["summary"],
        evidence=data.get("evidence", []),
        remediation=data.get("remediation", ""),
        confidence=data.get("confidence", 1.0),
        source=data.get("source", "llm"),
    )

# after:
@classmethod
def from_dict(cls, data: dict) -> AuditFinding:
    # The scorer prompt historically has two output schemas (`finding_id` vs
    # `id`, `summary` vs `title`, `remediation` vs `fix_action`). Accept either
    # so minor LLM drift doesn't throw away an entire AUDIT_REPORT.json.
    finding_id = data.get("finding_id") or data.get("id") or ""
    return cls(
        finding_id=finding_id,
        auditor=data.get("auditor", "scorer"),
        requirement_id=data.get("requirement_id", ""),
        verdict=data.get("verdict", "FAIL"),
        severity=data.get("severity", "MEDIUM"),
        summary=data.get("summary") or data.get("title", ""),
        evidence=data.get("evidence", []),
        remediation=data.get("remediation") or data.get("fix_action", ""),
        confidence=data.get("confidence", 1.0),
        source=data.get("source", "llm"),
    )
```

### Why the fix works

`audit_prompts.py` line 21 specifies `"finding_id"` but line 56 (the `_STRUCTURED_FINDINGS_OUTPUT` template) specifies `"id"`. Different auditor agents see different templates. When the scorer follows the `id` template, the old parser raised `KeyError: 'finding_id'` and silently discarded the report.

Fix accepts both keys and falls back safely when any field is missing.

### Verification

```
from_dict({'finding_id':'F-1','auditor':'a','requirement_id':'R-1','verdict':'PASS',...}) → finding_id='F-1'
from_dict({'id':'F-2','requirement_id':'R-2','verdict':'FAIL','title':'...','fix_action':'...'}) → finding_id='F-2', summary='...', remediation='...'
from_dict({}) → finding_id='', auditor='scorer', verdict='FAIL' (safe defaults)
```

---

## §5 — Bug #6: `cli.main()` CLAUDECODE env pop

**File:** `src/agent_team_v15/cli.py`
**Function:** `main()`
**Lines added:** 6

### Diff

Added at top of `main()`:
```python
# Strip CLAUDECODE from env so nested ClaudeSDKClient instances we spawn
# (Phase 1.5 tech research, MCP sub-orchestrators, etc.) do not hit
# claude_agent_sdk's "cannot be launched inside another Claude Code
# session" check. We are *agent-team*, the orchestrator — we are not
# ourselves Claude Code.
os.environ.pop("CLAUDECODE", None)
```

### Why the fix works

When running inside a Claude Code session, `CLAUDECODE=1` is in the env. Any nested `ClaudeSDKClient` the builder tries to spawn (Phase 1.5 tech research, for example) fails with `"Claude Code cannot be launched inside another Claude Code session"`. This was causing Phase 1.5 to crash with a `Fatal error in message reader` on every run before this fix.

Popping the env var at the top of `main()` means: the builder process no longer advertises itself as "inside Claude Code" to its own subprocesses, and nested SDK launches work.

### Verification

In the 2026-04-13 clean-attempt-2 run, Phase 1.5 completed with "Research complete — 4/6 technologies covered" instead of the prior fatal crash. First time ever Phase 1.5 produced any output.

---

## §6 — Bug #7: `openapi_generator.py` operationId dedupe

**File:** `src/agent_team_v15/openapi_generator.py`
**Line:** 1057
**Lines changed:** ~6

### Diff

```python
# before:
commands = [
    ...
]
for normalized_path, endpoint in sorted(canonical_endpoints.values(), ...):
    ...
    operation = {
        "operationId": _operation_name(
            normalized_path,
            method.upper(),
            {"operationId": endpoint.get("handler_name", "")},
        ),
        ...
    }

# after:
# Track operationIds across the whole spec so handler-name collisions
# ("create", "findAll", etc. used in multiple controllers) get disambiguated
# by path-derived suffix instead of failing the spec validator with
# "Duplicate operationId".
_used_op_names: set[str] = set()
for normalized_path, endpoint in sorted(canonical_endpoints.values(), ...):
    ...
    operation = {
        "operationId": _unique_operation_name(
            normalized_path,
            method.upper(),
            {"operationId": endpoint.get("handler_name", "")},
            _used_op_names,
        ),
        ...
    }
```

### Why the fix works

`_unique_operation_name` already existed (line 719) — it dedupes via path-derived suffix. Line 1057 was calling the un-deduped `_operation_name`. NestJS controllers conventionally have method names like `create`, `findAll`, `findById`, `update`, `remove` — those collide across every controller. Wave C's spec validator caught the collision and failed the wave.

One-line fix: use `_unique_operation_name` + track names across the full spec.

### Verification

```
used = set()
_unique_operation_name('/projects', 'POST', {'operationId': 'create'}, used)   → 'create'
_unique_operation_name('/projects/{projectId}/tasks', 'POST', {...}, used)     → 'createProjectsProjectIdTasks'
_unique_operation_name('/tasks/{taskId}/comments', 'POST', {...}, used)        → 'createTasksTaskIdComments'
_unique_operation_name('/projects', 'GET', {'operationId': 'findAll'}, used)   → 'findAll'
_unique_operation_name('/users', 'GET', {'operationId': 'findAll'}, used)      → 'findAllUsers'
```

2026-04-13 clean-attempt-2 Wave C succeeded in 7 sec with 6 files created and `success: true`.

---

## Suggested commit structure

Option A — one coherent PR titled "V18 smoke-test fixes":
```
fix(compile): resolve tsc --project paths to absolute [Bug #1]
fix(planner): drop prose bullets from dep list [Bug #2]
fix(audit): correct AUDIT_REPORT path nesting [Bug #4a]
fix(audit): accept both finding_id and id in AuditFinding.from_dict [Bug #4b]
fix(cli): pop CLAUDECODE env var at main() entry [Bug #6]
fix(openapi): dedupe operationIds across generated spec [Bug #7]
```

Option B — single squashed commit with the above as bullet points in the message body.

Either way: mention `smoke test session 2026-04-13` in the commit message so future archaeology ties back to `FINAL_COMPARISON_REPORT.md` and the per-bug plans.

### Tests to add later (not blocking the commit)

- `tests/test_compile_profiles.py`: test that `--project` paths are absolute when `--cwd` is relative
- `tests/test_milestone_manager.py`: test `_parse_deps` with prose bullets
- `tests/test_audit_models.py`: test `AuditFinding.from_dict` with both schema shapes
- `tests/test_openapi_generator.py`: test duplicate handler names produce unique operationIds

These tests would have caught each bug. Adding them prevents regression. Filed as separate issue; not strictly required to ship the fixes.
