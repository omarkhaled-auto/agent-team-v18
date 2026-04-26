# Wave C OpenAPI Generation — Scaffold the Project-Level Generator Script

> **Target repository:** `C:\Projects\agent-team-v18-codex`
>
> **Final destination in builder repo:** `docs/plans/2026-04-13-wave-c-openapi-script-scaffold-plan.md`
>
> **Status:** Diagnosed, not yet fixed. Empirical evidence captured during the 2026-04-13 TaskFlow smoke-test run (`v18 test runs/build-c-hardened-clean/` and `C:/smoke/clean/`).

## ⚠️ NOTE TO THE IMPLEMENTING AGENT

**Investigate fully before implementing.** This document is a starting hypothesis backed by code reading, not a verified specification. Before writing any code:

1. **Reproduce the symptom** — run any v18 build and confirm `BUILD_LOG.txt` shows `OpenAPI script generation unavailable for milestone-X: generate-openapi script not found. Falling back to regex extraction.` Verify by checking that `<cwd>/scripts/generate-openapi.{ts,js,mjs}` does not exist after Wave B / Scaffold.
2. **Read all four files in the "Code Map" section below in full**, not just the line ranges quoted here. Confirm the function call graph matches what this plan claims.
3. **Verify the assumption that the dual-path design (script-first, regex-fallback) was intentional**, not historical drift. Search `git log -p src/agent_team_v15/openapi_generator.py` and read commit messages to confirm the original author's intent.
4. **Confirm that `regex extraction` is genuinely lower-fidelity than what `@nestjs/swagger`'s `SwaggerModule.createDocument()` would produce** for the TaskFlow PRD. Read the regex extractor's output (`contracts/openapi/milestone-1.json` from `C:/smoke/clean/`) and a hand-built equivalent from running `SwaggerModule.createDocument()` against the same backend. If the regex output is already complete enough for downstream Wave D consumption, this fix is *low priority cosmetic*, not blocking.
5. **Decide on stack scope before implementing.** This bug currently only affects NestJS backends (the only stack where the proposed `@nestjs/swagger`-based script applies). Confirm that other supported backend stacks (`scaffold_runner._scaffold_nestjs` is the only backend scaffolder I see, but verify) don't need their own equivalent.

After investigation, **implement the fix completely**: scaffold template + script + npm devDependency wiring + integration test + telemetry verification + fallback retention. Don't leave half-implementations in the tree.

If your investigation reveals this plan is wrong (e.g., the script *is* scaffolded somewhere I missed, or the regex output is actually richer than I think), update this document with your corrected findings and stop.

---

## Symptom

Every v18 build that uses the NestJS backend stack logs this warning during Wave C:

```
OpenAPI script generation unavailable for milestone-1: generate-openapi script not found. Falling back to regex extraction.
```

Wave C still completes successfully because the fallback (`_fallback_to_regex_extraction`) does work. But the design clearly intended a higher-fidelity path that nobody ever implemented.

## Empirical Evidence (from 2026-04-13 smoke test)

- Build dir: `C:/smoke/clean/` — clean NestJS+Next.js TaskFlow build, all V18 fixes (#1-#7) applied
- Wave B telemetry: `compile_passed: true`, 70 files created, codex/gpt-5.4
- Wave C telemetry: `success: true`, but ran in 7 sec via regex fallback
- Wave C artifact: produced `contracts/openapi/{current,milestone-1,previous}.json` via regex
- **`C:/smoke/clean/scripts/` directory does not exist** — scaffold never created it
- `find … -name "generate-openapi*"` returns nothing in any v18 build I've inspected

## Why This Change Is Needed

The current flow in `src/agent_team_v15/openapi_generator.py` is two-tier:

```python
# openapi_generator.py:55-71
def generate_openapi_contracts(cwd, milestone):
    spec_result = _generate_openapi_specs(...)       # tries scripts/generate-openapi.{ts,js,mjs}
    if not spec_result.get("success"):
        logger.warning("OpenAPI script generation unavailable... Falling back to regex extraction.")
        return _fallback_to_regex_extraction(...)    # parses controller decorators with regex
```

The script lookup at `openapi_generator.py:33-37`:

```python
_SCRIPT_CANDIDATES = (
    "scripts/generate-openapi.ts",
    "scripts/generate-openapi.js",
    "scripts/generate-openapi.mjs",
)
```

**No file in the codebase ever creates these scripts.** Search results:
```
grep -rn "scripts/generate-openapi" src/agent_team_v15/
→ src/agent_team_v15/openapi_generator.py: only file mentioning it
```

`src/agent_team_v15/scaffold_runner.py` (304 lines, the canonical project-template scaffolder) emits NestJS module/service/controller files + Next.js pages + i18n config. It has zero references to `generate-openapi`, `scripts/`, or `@nestjs/swagger` extraction.

So the architecture intent — *"prefer the project-level script, fall back to regex if needed"* — is technically a one-tier design today: **always falls back**.

## Quality Cost of the Status Quo

The regex extractor parses controller TypeScript files and reconstructs an OpenAPI spec from `@Controller`, `@Get`, `@Post`, `@ApiProperty`, `@IsString`, etc. decorators. It misses anything that isn't in a literal decorator argument:

- Validation rules expressed via custom pipes
- Conditional response schemas (e.g., union types resolved at runtime)
- Enum classes referenced by type annotation rather than `enum:` arg
- Inherited DTO fields (when DTOs extend a base class)
- `@ApiExtraModels` registrations
- Polymorphic responses (`@ApiResponse` with `oneOf`)
- Authorization metadata (`@ApiBearerAuth`, security scheme inheritance)

`@nestjs/swagger`'s `SwaggerModule.createDocument()` resolves all of these because it walks the actual NestJS module graph at runtime. That's why the design *had* a script tier in the first place.

In the 2026-04-13 smoke test, Wave D successfully consumed the regex-generated spec to build the frontend (`src/lib/api/client.ts`), so it's good enough today. But as the PRD complexity grows (polymorphism, custom pipes, role-based response shapes), the regex tier will start dropping fidelity that Wave D depends on, silently.

## Scope

This plan changes:

- `src/agent_team_v15/scaffold_runner.py` — extend the NestJS backend scaffolder to drop `scripts/generate-openapi.ts` + the `package.json` devDependency on `@nestjs/swagger` (already used in main app, but verify) and a script entry point
- The new template file itself
- Tests (`tests/test_scaffold_runner.py` if it exists, or new test file)
- Possibly `src/agent_team_v15/openapi_generator._generate_openapi_specs()` — confirm the env-var contract (`MILESTONE_ID`, `OUTPUT_DIR`, `MILESTONE_MODULE_FILES`) is still what we want

This plan does **not** change:

- The regex fallback (must remain — it's the safety net)
- `openapi_generator._fallback_to_regex_extraction()` behavior
- Wave C orchestration timing
- Other waves
- Stacks other than NestJS (out of scope unless investigation finds they need parallel treatment)

## Non-Goals

1. Do not remove or rewrite the regex fallback. It is the safety net for non-NestJS backends and broken NestJS setups.
2. Do not change the `ContractResult` shape or the wave_executor's contract.
3. Do not redesign the `openapi_generator` entry point. The current `generate_openapi_contracts(cwd, milestone)` API is correct; only the scaffolded artifact it expects to find is missing.
4. Do not add a runtime dependency on a global `swagger-cli` or any non-`package.json` tool. The script must be self-contained inside the generated project.
5. Do not bake assumptions about the user's specific NestJS app structure beyond what `scaffold_runner._scaffold_nestjs()` produces.

## Code Map (read these in full before implementing)

| File | Range | Role |
|---|---|---|
| `src/agent_team_v15/openapi_generator.py` | 33-37 | `_SCRIPT_CANDIDATES` — what filenames the runtime expects |
| `src/agent_team_v15/openapi_generator.py` | 55-71 | `generate_openapi_contracts()` — tier-1/tier-2 dispatch |
| `src/agent_team_v15/openapi_generator.py` | 115-160 | `_generate_openapi_specs()` — invokes the script via subprocess, with env vars `MILESTONE_ID`, `OUTPUT_DIR`, `MILESTONE_MODULE_FILES` |
| `src/agent_team_v15/openapi_generator.py` | (look up `_find_generation_script`) | filename detection |
| `src/agent_team_v15/openapi_generator.py` | (look up `_script_command`) | how the script is invoked (node? ts-node? tsx?) — **critical to match in scaffolded template** |
| `src/agent_team_v15/openapi_generator.py` | (look up `_fallback_to_regex_extraction`) | the safety net you must NOT touch |
| `src/agent_team_v15/scaffold_runner.py` | 15-56 | `run_scaffolding()` — main entry, dispatch by stack |
| `src/agent_team_v15/scaffold_runner.py` | 80-141 | `_scaffold_nestjs()` — backend scaffold; this is where the new file gets dropped |
| `src/agent_team_v15/scaffold_runner.py` | 142-170 | `_scaffold_nestjs_from_templates()` — template-rendering helper |
| `src/agent_team_v15/cli.py` | 3045, 3061, 3639, 3654 | call-sites that invoke `generate_openapi_contracts` (read for context — should not need changes) |

## Investigation Checklist (do these *before* writing code)

- [ ] Reproduce the symptom on a fresh build; confirm the warning appears
- [ ] Confirm `<cwd>/scripts/` dir does not exist after `_scaffold_nestjs` runs
- [ ] Read `_find_generation_script` to confirm it only checks `_SCRIPT_CANDIDATES` (no other paths)
- [ ] Read `_script_command(script_path)` to determine the exact invocation (node vs tsx vs ts-node) — your scaffolded template must be runnable by that command
- [ ] Inspect `_load_wave_b_module_files(project_root, milestone_id)` to understand what the script receives in `MILESTONE_MODULE_FILES` env var
- [ ] Confirm `_validate_cumulative_spec` is happy with output produced by `SwaggerModule.createDocument()` (run it manually against a minimal NestJS app and compare structure)
- [ ] Confirm that running `scripts/generate-openapi.ts` with `tsx` (or whatever `_script_command` uses) doesn't require the user to install global tools — everything must come from `package.json` devDependencies
- [ ] Look for any existing scaffolded `package.json` to confirm `@nestjs/swagger` is already a runtime dep (it should be — it's used in the controllers Codex generates)
- [ ] Decide where the script outputs. Read the env contract: `OUTPUT_DIR=<cwd>/contracts/openapi/`. Filename convention: `{MILESTONE_ID}.json` for the milestone slice, plus updating `current.json`. Verify by reading what `_generate_openapi_specs` does with `spec_result.get("milestone_spec_path")` and `cumulative_spec_path` — your script must emit files at the paths it returns

## Proposed Implementation (subject to revision after investigation)

### 1. Add a NestJS-aware OpenAPI extraction script template

Create `src/agent_team_v15/_templates/scripts/generate-openapi.ts` (new template file):

```typescript
// AUTO-GENERATED by agent-team-v15 scaffold.  Do not edit by hand.
// Invoked by the v18 wave engine during Wave C.
// Reads MILESTONE_ID, OUTPUT_DIR, MILESTONE_MODULE_FILES from env.
// Emits one milestone-local spec + updates the cumulative spec.
//
// Run with: tsx scripts/generate-openapi.ts   (or whatever _script_command picks)

import { writeFileSync, readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { NestFactory } from "@nestjs/core";
import { SwaggerModule, DocumentBuilder } from "@nestjs/swagger";
import { AppModule } from "../src/app.module";

async function main() {
  const milestoneId = process.env.MILESTONE_ID ?? "milestone-unknown";
  const outputDir = process.env.OUTPUT_DIR ?? resolve("contracts/openapi");
  // MILESTONE_MODULE_FILES is a comma-separated list — used by some scripts
  // to scope generation to just the new modules in this wave.  For a v1
  // implementation we generate the full app spec; per-milestone scoping
  // can be added later by reading this env and filtering AppModule imports.

  const app = await NestFactory.create(AppModule, { logger: false });
  await app.init();
  const config = new DocumentBuilder()
    .setTitle("Generated API")
    .setVersion("1.0.0")
    .build();
  const doc = SwaggerModule.createDocument(app, config);
  await app.close();

  const milestoneSpecPath = join(outputDir, `${milestoneId}.json`);
  const cumulativeSpecPath = join(outputDir, "current.json");
  const previousSpecPath = join(outputDir, "previous.json");

  // Rotate previous → previous.json before overwriting current.json
  if (existsSync(cumulativeSpecPath)) {
    writeFileSync(previousSpecPath, readFileSync(cumulativeSpecPath));
  }

  writeFileSync(milestoneSpecPath, JSON.stringify(doc, null, 2));
  writeFileSync(cumulativeSpecPath, JSON.stringify(doc, null, 2));

  // stdout for the wave engine to capture
  console.log(JSON.stringify({
    success: true,
    milestone_spec_path: milestoneSpecPath,
    cumulative_spec_path: cumulativeSpecPath,
    files: [milestoneSpecPath, cumulativeSpecPath, previousSpecPath],
  }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

⚠️ **Verify before committing**: the exact stdout shape `_generate_openapi_specs` parses. Read its post-`subprocess.run` block to see whether it expects JSON on stdout, a file at a known path, or both. The script above assumes stdout-JSON; revise if the runtime expects something else.

### 2. Wire it into the NestJS scaffolder

In `src/agent_team_v15/scaffold_runner.py`, extend `_scaffold_nestjs` (around line 80-141) to also write the generator script. Pseudocode:

```python
def _scaffold_nestjs(project_root: Path, entities: list[dict], ir: dict) -> list[str]:
    created: list[str] = []
    # ... existing entity-module scaffolding ...

    # NEW: drop the OpenAPI generation script
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "generate-openapi.ts"
    script_template = _read_template("scripts/generate-openapi.ts")  # use existing _templates path convention
    script_path.write_text(script_template, encoding="utf-8")
    created.append(_relpath(script_path, project_root))

    # NEW: ensure package.json includes the script + devDeps
    _ensure_package_json_openapi_script(project_root)

    return created
```

`_ensure_package_json_openapi_script(project_root)` should:
- Read `package.json` (create if missing — but in practice Codex's Wave B always emits one)
- Add `"generate-openapi": "tsx scripts/generate-openapi.ts"` to `scripts`
- Add `tsx` to `devDependencies` if missing
- Add `@nestjs/swagger` to `dependencies` if missing (likely already there)
- Pretty-print and write back

### 3. Confirm the runtime invokes the script via the matching command

Read `_script_command(script_path)` in `openapi_generator.py`. If it currently does something like:
```python
return ["npx", "tsx", str(script_path)]
```
…then the scaffolded `package.json` doesn't strictly need a `scripts.generate-openapi` entry, but adding it documents intent and lets developers run it manually (`npm run generate-openapi`).

If `_script_command` instead does `["npm", "run", "generate-openapi"]`, then the `package.json` `scripts` entry is **mandatory** — write the template accordingly.

**Do not assume — read the function and align the scaffold with what the runtime actually invokes.**

### 4. Tests

Add to `tests/test_scaffold_runner.py` (create if missing):

- `test_nestjs_scaffold_drops_generate_openapi_script`: scaffold a fake NestJS project, assert `scripts/generate-openapi.ts` exists with non-empty content
- `test_nestjs_scaffold_adds_npm_script_entry`: assert `package.json["scripts"]["generate-openapi"]` is set
- `test_nestjs_scaffold_adds_tsx_devdependency`: assert `package.json["devDependencies"]["tsx"]` is set
- `test_nestjs_scaffold_adds_swagger_dependency`: assert `package.json["dependencies"]["@nestjs/swagger"]` is set
- `test_generate_openapi_script_runnable`: integration test that actually executes the scaffolded script against a minimal NestJS app and asserts the output shape (stdout JSON + emitted files). Skip if `node`/`tsx` not available, but mark it `@pytest.mark.integration` so CI runs it.

Add to `tests/test_openapi_generator.py` if it exists:

- `test_generate_openapi_contracts_uses_script_path_when_present`: scaffold the script, run `generate_openapi_contracts`, assert `_generate_openapi_specs` succeeded (not the regex fallback path) — could verify by checking the warning was NOT logged
- `test_generate_openapi_contracts_falls_back_when_script_missing`: ensure the regex fallback still works when scripts/generate-openapi.ts is intentionally absent

### 5. Telemetry hook (optional but recommended)

In `_generate_openapi_specs`, when the script path is found AND succeeds, write a small telemetry breadcrumb so future debugging is easy. E.g., append to the `ContractResult.files_created`, log `logger.info("OpenAPI generated via project script %s", script_path)`. The user-visible signal: `BUILD_LOG.txt` should now show one of:

- `OpenAPI generated via scripts/generate-openapi.ts (NestJS Swagger module)` ← new
- `OpenAPI script generation unavailable for milestone-X: <reason>. Falling back to regex extraction.` ← existing fallback warning, preserved

## Acceptance Criteria

The fix is **complete** only when ALL of these are true:

- [ ] After running `_scaffold_nestjs` on a fresh project, `<cwd>/scripts/generate-openapi.ts` exists and is non-empty
- [ ] After running `_scaffold_nestjs`, `<cwd>/package.json` has the right `scripts` entry, `tsx` devDep, and `@nestjs/swagger` runtime dep
- [ ] Running `npx tsx scripts/generate-openapi.ts` (or equivalent) on a Codex-generated NestJS app emits valid OpenAPI 3.x JSON to `OUTPUT_DIR/<MILESTONE_ID>.json` and updates `current.json`
- [ ] In a fresh smoke-test build, `BUILD_LOG.txt` does NOT contain `OpenAPI script generation unavailable`
- [ ] The Wave C `ContractResult.success` is `true`, `milestone_spec_path` and `cumulative_spec_path` are populated, and `files_created` includes the script's outputs
- [ ] The regex fallback path is exercised by an explicit unit test (delete the script, verify fallback still works) — never delete or weaken the fallback
- [ ] All four new unit tests + the one integration test above are added and pass
- [ ] No regression in any existing test (`pytest tests/` is green)
- [ ] Manual end-to-end smoke test: re-run the TaskFlow PRD smoke test (`v18 test runs/TASKFLOW_MINI_PRD.md`) and confirm Wave C produces a richer spec than the current regex output. Concretely: the new spec should contain at minimum `components.schemas.<DtoName>` entries with `properties` matching the actual decorated DTOs, including types resolved from imports (which the regex cannot do for transitively-imported types)

## Out-of-Scope Follow-Ups (file as separate plans, do NOT bundle)

- Per-milestone scoping via `MILESTONE_MODULE_FILES` env (today the script generates the full AppModule spec; that's correct behavior for Wave C's cumulative-spec model anyway, but if scoping is desired, that's a separate plan)
- Equivalent script for non-NestJS backends (Express, Fastify, Spring, .NET, etc.) — needs separate per-stack templates and per-stack OpenAPI extractors
- Auto-generating SDK clients in additional languages (today only TypeScript clients are produced) — separate plan
- Migrating the regex extractor to AST-based parsing (TypeScript compiler API in a Python sidecar) for better tier-2 fidelity — separate plan, only worth it if tier-1 (this fix) somehow can't ship

## Risk Notes

- **Subprocess timing** — the current `_generate_openapi_specs` has a 60-second timeout. NestJS app initialization can be slow on cold-cache CI runners. If the integration test is flaky, bump the timeout in `_generate_openapi_specs` (but document why) before adding retries.
- **`@nestjs/swagger` version drift** — pin the version in the scaffolded `package.json` to whatever Codex's Wave B emits, to avoid two-version installs. Read Codex's typical output for `@nestjs/swagger` version and match it exactly.
- **`tsx` vs `ts-node`** — `tsx` is faster and friendlier; `ts-node` is the legacy default. Pick `tsx` unless `_script_command` reveals the runtime expects `ts-node`. Either way, lock the version in `package.json`.
- **Cumulative spec rotation** — the script template above rotates `current.json` → `previous.json` before overwriting. Verify the runtime's `_diff_cumulative_specs` expects this behavior (read it in `openapi_generator.py`); if the runtime does the rotation itself, remove that block from the script to avoid double-rotation.

## Done When

A fresh `python -m agent_team_v15 --prd <PRD> --cwd <clean-dir> --depth exhaustive` build of a NestJS+Next.js PRD:

1. Produces `<cwd>/scripts/generate-openapi.ts` after Scaffold
2. Wave C runs the script (no fallback warning in log)
3. Wave C's emitted `<cwd>/contracts/openapi/<milestone>.json` contains decorator-driven schemas that the regex extractor would have missed (validate by hand-comparing against a minimal example)
4. Wave D continues to consume the spec without changes
5. All tests green
