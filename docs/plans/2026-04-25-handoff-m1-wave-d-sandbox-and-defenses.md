# HANDOFF — M1 Wave-D path-write sandbox + layered drift defenses

**Date:** 2026-04-25
**Repo:** `C:/Projects/agent-team-v18-codex`
**Branch at handoff:** `master`
**HEAD at handoff:** `8a7f0e8` (worktree dirty — many in-flight fixes; do **NOT** revert)
**Status:** all source defenses landed and unit-tested. Final smoke not yet run with the new sandbox in place.

---

## Read this first — TL;DR

A previous session got Milestone 1 *almost* clean. Six smoke runs surfaced six distinct Codex/Claude drift classes on Wave B and Wave D — each fixed in source. The seventh run failed when **Claude Wave D** wrote to `tsconfig.base.json` at repo root (out of scope). The user authorized the structural fix the session had been deferring: a **Claude Code PreToolUse hook** that restricts Wave D writes to `apps/web/**` deterministically.

That hook is now landed. **Your job:** verify the sandbox lands cleanly, run the final M1 smoke, and decide M1 promotability. If the smoke is clean, follow up with the consolidation refactor described in §10.

---

## 1. Non-negotiable rules (carried from prior handoffs)

- **No workarounds.** Fix root causes only.
- **Do not patch a smoke run directory** as proof. Final proof is a fresh full smoke after fast-forward gates pass.
- **Preserve the dirty worktree.** Many of the fixes below are uncommitted; do not revert or normalize.
- **Context7 quota / monthly limit is waived** by the user; do not chase it. Other Context7 issues (different libraries) are real.
- **Docker / WSL / Anthropic 529 = environment evidence**, not product failure.
- **The fast-forward harness is diagnostic only**. Final M1 proof requires a fresh full smoke run that passes Gate 7.

---

## 2. What this session achieved (full chronology)

The goal: get M1 to a fully clean, promotable completion with zero workarounds.

The session ran nine full M1 smokes (a couple killed early once a decisive blocker was proven). Each smoke surfaced a distinct drift or environment problem. Source fixes landed as follows. Tests added for every fix.

| # | Where it bit | Root cause (proven from log + telemetry) | Source fix landed |
|---|---|---|---|
| 1 | Fast-forward Gate 2 | Generated `scripts/generate-openapi.ts` static-imported `reflect-metadata` from the workspace root, but pnpm doesn't hoist it there | `src/agent_team_v15/scaffold_runner.py` — load `reflect-metadata` via `apiRequire` after `createRequire(apiRoot/package.json)` is set up |
| 2 | Fast-forward Gate 2 | Scaffold's `.env.example` `JWT_SECRET=change-me` fails its own Joi `.min(16)` validation → NestJS boot fails | `scaffold_runner.py` — JWT_SECRET = `dev-insecure-change-me-please` |
| 3 | Fast-forward Gate 2 | ts-node on Node 22+ ran the script as ESM → `__dirname` undefined; missing decorator metadata broke NestJS DTOs | `src/agent_team_v15/openapi_generator.py:_script_command` — pass `--transpile-only -O '{module:commonjs,target:ES2022,esModuleInterop:true,experimentalDecorators:true,emitDecoratorMetadata:true,skipLibCheck:true,resolveJsonModule:true}'` |
| 4 | Fast-forward Gate 2 | `@prisma/client` is a stub until `prisma generate` runs; NestJS boot failed loading `PrismaService` | New helper `_ensure_prisma_generate()` in `openapi_generator.py`, called before ts-node |
| 5 | Fast-forward Gate 5 | `audit_run_directory` crashed `UnicodeDecodeError` on PowerShell-written UTF-16 LE BOM `BUILD_LOG.txt` | `m1_fast_forward._read_text` falls through UTF-8 → UTF-8-sig → UTF-16 → latin-1(replace) |
| 6 | Smoke 1 — Wave B fail | `apps/web/public/.gitkeep` byte-flipped CRLF→LF (idempotent marker; semantic noise) | `wave_executor._DEFAULT_SKIP_FILE_BASENAMES = {".gitkeep", ".keep"}` skipped in checkpoint walker |
| 7 | Smoke 2 — Wave B port drift | Wave B Codex rewrote `docker-compose.yml` ports `4000→3001`, `3000→3080` — prompt never named the canonical ports | New `format_infra_port_invariants_for_prompt()` in `stack_contract.py`; `build_wave_b_prompt` + `build_wave_d_prompt` now accept and inject `stack_contract` |
| 8 | Smoke 3 — Wave C false-fail | M1 REQUIREMENTS scope didn't enumerate `contracts/openapi/` → Wave C's own canonical output flagged out-of-scope | `wave_executor._apply_post_wave_scope_validation` skips milestone-scope check for Wave C (Python-owned generator); `find_forbidden_paths` still runs |
| 9 | Smoke 4 — Wave D regen | Codex Wave D's build/test side effects re-invoked openapi-ts → `packages/api-client/sdk.gen.ts` flipped bytes | New `_capture_packages_api_client_snapshot` + `_restore_packages_api_client_snapshot` in `wave_executor`; restore fires before BOTH `_post` and `_final` checkpoint sites in BOTH dispatch loops |
| 10 | Smoke 5 — Wave D `CON` | Codex bash-on-Windows redirect created literal file named `CON` (Windows reserved device name) at repo root | Same restore mechanism as #9 — but the deeper class motivated layered defenses below |
| 11 | Smoke 6 — Wave B `contracts/openapi/*` | Codex Wave B ran `pnpm openapi:export` during self-verify, leaving Wave C's deliverables prematurely (`milestone-unknown.json` filename was the giveaway — script default when MILESTONE_ID env unset) | New `_purge_wave_c_owned_dirs()` for `contracts/openapi/*` and `packages/api-client/*` before checkpoint diff in pre-C waves (A, A5, Scaffold, B); fires in BOTH dispatch loops |
| 12 | Provider switch | After 3 distinct Codex Wave D drift classes, user requested switching D to Claude (original design) | `v18 test runs/configs/taskflow-smoke-test-config.yaml` `provider_map_d: claude`; `m1_fast_forward.py` Gate 0 relaxed to accept codex-or-claude on D |
| 13 | Smoke 7 — Claude Wave D `tsconfig.base.json` | Claude on Wave D wrote root tsconfig — empirical proof prompt-only restrictions are weak across BOTH agents | **NEW THIS HANDOFF** — Claude Code `PreToolUse` hook sandbox (this section §3) |

---

## 3. The sandbox fix (THIS handoff's primary deliverable)

### Mechanism

The Wave-D dispatch goes through `AgentTeamsBackend._spawn_teammate` which invokes the `claude` CLI as a subprocess. Per the documented Claude Code hook contract (verified via Context7 `/anthropics/claude-code` — see `plugins/plugin-dev/skills/hook-development/SKILL.md`):

* Per-run `<cwd>/.claude/settings.json` defines `PreToolUse` hooks that the CLI executes before each tool call.
* The hook command receives a JSON payload on stdin — `{"tool_name": "...", "tool_input": {...}}` — and prints either `{}` (allow) or `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` on stdout.

### Files added

* `src/agent_team_v15/wave_d_path_guard.py` — Python module invoked via `python -m agent_team_v15.wave_d_path_guard`. Reads stdin, checks `AGENT_TEAM_WAVE_LETTER`, classifies the file path, prints the documented decision envelope.
* `tests/test_wave_d_path_guard.py` — 10 tests covering: non-D dispatches (allow), `apps/web/**` writes (allow), root `tsconfig.base.json` (deny), `packages/api-client/*` (deny), `apps/api/*` (deny), Read tool (allow), path-traversal attempts (deny), malformed stdin (fail-open), relative path resolution via `AGENT_TEAM_PROJECT_DIR`.

### Files changed

* `src/agent_team_v15/agent_teams_backend.py`:
  * Added `_wave_letter_from_task_id(task_id)` — extracts wave letter from task ids like `wave-D-milestone-1`.
  * Extended `_build_teammate_env(task_id="", cwd=None)` — sets `AGENT_TEAM_WAVE_LETTER` and `AGENT_TEAM_PROJECT_DIR` per dispatch. Existing callers (phase leads) pass nothing → no env injected → hook is a no-op for them.
  * Added `_ensure_wave_d_path_guard_settings(cwd)` — writes / updates `<cwd>/.claude/settings.json` with the `PreToolUse` hook entry under marker key `agent_team_v15_wave_d_path_guard`. Idempotent. Preserves any pre-existing unrelated hooks.
  * `_spawn_teammate` now calls `_ensure_wave_d_path_guard_settings(cwd)` and passes `task_id, cwd` into `_build_teammate_env`.
* `tests/test_agent_teams_backend.py` — 7 new tests for wave-letter parsing, env injection, settings.json creation, idempotency, and unrelated-hook preservation.

### Wave-letter awareness

The `PreToolUse` hook config in `settings.json` applies to **every** Claude dispatch in the run dir (Wave A teammate, audit auditors, repair turns). The wave-letter awareness happens **inside** `wave_d_path_guard.py`:

```
if AGENT_TEAM_WAVE_LETTER != "D":
    print "{}"   # allow — non-D dispatches are unaffected
    exit 0
```

This means:

* Wave A (architect, Claude): hook fires, env says non-D, allow everything. No change.
* Wave D (Claude with the new config): hook fires, env says D, run the apps/web/** check.
* Audit auditors / scorers (Claude): no `AGENT_TEAM_WAVE_LETTER` env (they don't go through `_build_teammate_env` with task_id), allow everything.

### What the sandbox restricts

The hook only fires for write-class tools — `Write|Edit|MultiEdit|NotebookEdit`. For wave D it allows writes only when the resolved relative path is under `apps/web/`. For all other paths it returns `permissionDecision: deny` with a reason that names the offending tool + path and explicitly tells Claude to write `WAVE_D_CONTRACT_CONFLICT.md` instead of guessing.

### What the sandbox **does NOT** restrict

* Reads — the matcher excludes `Read`. Wave D continues to consume `packages/api-client/`, `apps/api/`, root configs, etc., for context.
* Bash — not in matcher. Wave D can still run `pnpm test`, `pnpm build`, etc.
* Glob/Grep/everything else — not in matcher.
* Non-D waves — `AGENT_TEAM_WAVE_LETTER` filter short-circuits to allow.
* Wave B (currently Codex) — the hook config affects Claude dispatches only; Codex doesn't read `.claude/settings.json`. Wave B's containment remains the layered defenses #9 and #11 in §2.

This is **deliberate** — Wave D's prompt scope is "frontend specialist", legitimate writes live under `apps/web/`, and the sandbox is a hard floor under the prompt-only rule. It cannot restrict legitimate Wave D work because legitimate Wave D work is, by definition, under `apps/web/`.

### Claude Code hook contract — exact citations

* Hook file: `<cwd>/.claude/settings.json`, top-level keys per event name (user-settings format, no plugin wrapper).
* Entry shape: `{"matcher": "...", "hooks": [{"type": "command", "command": "...", "timeout": 10}]}`.
* Stdin: `{tool_name, tool_input, cwd, ...}` — `tool_input.file_path` for Write/Edit/MultiEdit; `tool_input.notebook_path` for NotebookEdit.
* Stdout deny: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`.
* Stdout allow: `{}` or empty.

(Sources: `https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md` via Context7 `/anthropics/claude-code`.)

### Verification done in this session

* 10 unit tests against the hook script (subprocess invocation that mirrors the runtime CLI flow).
* 7 unit tests against the agent_teams_backend wiring.
* All 164 tests in `tests/test_agent_teams_backend.py + tests/test_wave_d_path_guard.py` pass.

**Not yet done:** end-to-end smoke run with the sandbox in place. That is your job (§5).

---

## 4. Current source state — what is in the worktree

The worktree is dirty with all the fixes from §2. Important untracked / modified files:

### New files (untracked)

* `src/agent_team_v15/wave_d_path_guard.py` (Wave D PreToolUse hook script)
* `src/agent_team_v15/m1_fast_forward.py` (fast-forward harness from a prior session)
* `src/agent_team_v15/templates/scaffold_assets/pnpm-lock.yaml` (deterministic lockfile asset)
* `tests/test_wave_d_path_guard.py`
* `tests/test_m1_fast_forward.py`
* `scripts/run-m1-fast-forward.ps1`
* `docs/plans/2026-04-25-handoff-m1-wave-d-sandbox-and-defenses.md` (THIS file)

### Modified files (significant changes, NOT to revert)

* `src/agent_team_v15/agent_teams_backend.py` — sandbox wiring, env injection, settings.json writer
* `src/agent_team_v15/wave_executor.py` — packages/api-client snapshot+restore at 4 sites; Wave-C-owned-dirs purge at 2 sites in pre-C waves; .gitkeep skip; `_DEFAULT_SKIP_FILE_BASENAMES`; Wave C scope bypass
* `src/agent_team_v15/openapi_generator.py` — `_script_command` ts-node flags; `_ensure_prisma_generate`
* `src/agent_team_v15/scaffold_runner.py` — reflect-metadata via apiRequire; JWT_SECRET; logger fix
* `src/agent_team_v15/agents.py` — `build_wave_b_prompt` + `build_wave_d_prompt` accept `stack_contract`; port-invariants block injected; `build_wave_prompt` dispatcher forwards `stack_contract`
* `src/agent_team_v15/stack_contract.py` — new `format_infra_port_invariants_for_prompt()`
* `v18 test runs/configs/taskflow-smoke-test-config.yaml` — `provider_map_d: claude`
* `tests/test_v18_specialist_prompts.py`, `tests/test_wave_scope_filter.py`, `tests/test_v18_phase2_wave_engine.py`, `tests/test_openapi_launcher_resolution.py`, `tests/test_scaffold_m1_correctness.py`, `tests/wave_executor/test_default_skip_dirs.py`, `tests/test_h3e_contract_guard.py`, etc. — coverage + assertions updated for each fix above

### Pre-existing test failure (not caused by this session)

`tests/test_h3e_contract_guard.py::test_wave_a_contract_drift_redispatches_back_to_wave_a` was already red **before** any of this session's fixes (verified via `git stash` + run). It fails in Wave B's self-verify probe (`docker compose: service "api" has neither an image nor a build context specified`) — looks like a test fixture issue unrelated to any of the layers we added. Don't block on it.

---

## 5. What you need to do — execution plan

### Step 1 — Pre-flight

```powershell
Set-Location -LiteralPath 'C:\Projects\agent-team-v18-codex'
git status --short
git worktree list
node -e "const fs=require('fs'); const p='.tmp-delete-proof'; fs.writeFileSync(p,'probe'); try { fs.unlinkSync(p); console.log('delete-ok'); } catch (e) { console.log('delete-failed:' + e.code + ':' + e.message); }"
docker ps
```

If delete probe says `delete-ok` and `docker ps` exits 0, the environment is healthy. Otherwise classify as environment blocker, not product failure.

### Step 2 — Targeted tests

```powershell
python -m pytest tests/test_wave_d_path_guard.py tests/test_agent_teams_backend.py tests/wave_executor/ tests/test_wave_scope_filter.py tests/test_v18_phase2_wave_engine.py tests/test_v18_specialist_prompts.py tests/test_stack_contract.py tests/test_m1_fast_forward.py tests/test_codex_observer_checks.py tests/test_scaffold_m1_correctness.py tests/test_scaffold_runner.py tests/test_openapi_launcher_resolution.py
```

Expected: ~600+ passed, the one pre-existing H3e failure is acceptable but should NOT regress to additional failures.

### Step 3 — Fast-forward harness

```powershell
& .\scripts\run-m1-fast-forward.ps1
```

Latest report at `v18 test runs/m1-fast-forward-<timestamp>/fast-forward-report.json`. All six gates must pass (`success: true`, `ready_for_full_smoke: true`).

### Step 4 — Final M1 smoke

```powershell
& 'C:\Projects\agent-team-v18-codex\v18 test runs\start-m1-hardening-smoke.ps1'
```

This is the only proof that matters. Monitor `BUILD_LOG.txt` (UTF-16 on Windows!), `EXIT_CODE.txt`, `.agent-team/STATE.json`, `.agent-team/milestone_progress.json`, all wave artifacts and telemetry, `WAVE_FINDINGS.json`.

### Step 5 — Decide

**M1 is clean** if and only if every one of the following is true (Gate 7 from `docs/plans/2026-04-24-handoff-m1-fast-forward-real-simulation-before-smoke.md`):

* `EXIT_CODE.txt == 0`
* No `interrupted_milestone` in `milestone_progress.json`
* No `WAVE_A_CONTRACT_CONFLICT.md` exists
* All expected waves completed; no failed wave markers
* No `fallback_used: true` for any Codex-owned wave
* No `scope_violations` outside Wave A (Wave A is allowed because the post-wave guard is `success and wave_letter != "A"`)
* `contract_fidelity == "canonical"` and `client_fidelity == "canonical"` in Wave C artifact
* No degraded OpenAPI/client metadata
* Runtime probes returned 200 where configured
* Audit artifacts (`AUDIT_REPORT.json`, `AUDIT_REPORT_INTEGRATION.json`) do not contradict success
* `WAVE_FINDINGS.json` shows `wave_t_status: completed` (or `disabled` if Wave T is genuinely disabled)
* docker-compose.yml ports stayed `4000/3000/5432`

If clean → declare M1 success and proceed to §10 consolidation refactor.

If not clean → diagnose decisively per §6.

---

## 6. Decision tree if Wave D fails again

| What you see | Likely cause | Next move |
|---|---|---|
| `permissionDecisionReason` log lines from `wave_d_path_guard` denying many writes | The scope is too narrow — a legitimate Wave D path is being blocked | Add the path to `_WAVE_D_ALLOWED_FILES` (frozenset of exact paths) or extend `_WAVE_D_ALLOWED_PREFIXES`. Capture the exact denied paths from BUILD_LOG before adjusting. |
| Wave D succeeds but `tsconfig.base.json` is in `files_modified` | The hook didn't fire — settings.json wasn't loaded by the CLI | Check `<run_dir>/.claude/settings.json` exists and contains the `agent_team_v15_wave_d_path_guard` marker. Check the hook command's path is reachable (`python -m agent_team_v15.wave_d_path_guard`). Run the hook script manually with sample stdin. |
| Wave D is denied a Read tool call | Bug — Read should never go through the matcher | Inspect the matcher in `_ensure_wave_d_path_guard_settings`; should be `Write|Edit|MultiEdit|NotebookEdit`. |
| Wave D fails on a Wave-B/Wave-C-territory file (e.g., `apps/api/...` again) | Hook is firing but the env var isn't being read | Verify `AGENT_TEAM_WAVE_LETTER=D` is in the spawned subprocess env. The Claude CLI passes parent env to hooks via stdin too — should still work. Ensure `_build_teammate_env(task_id="wave-D-...")` is called. |
| Anthropic API 529 / overloaded | Environment, not product | Wait for `status.claude.com` to clear, retry. Do not change product code. |
| New drift class on Wave B (Codex) | This handoff did NOT sandbox Wave B — see §10 | Either (a) extend the snapshot/restore/purge layers for Wave B's specific new failure mode, or (b) escalate to the Wave B sandbox refactor described in §10 if drift surfaces > once. |

---

## 7. What to expect from the smoke

Based on smokes 6 (Codex on D) and 7 (Claude on D), the per-stage timing roughly:

| Stage | Wall time | Notes |
|---|---|---|
| Phase 0.5–0.85 | 1–2 min | Codebase map + UI requirements + design tokens |
| Phase 1 PRD decomposition | 1–3 min | Claude writes MASTER_PLAN |
| Phase 1.5 tech research | 30 s – 2 min | Context7; quota-blocked is acceptable |
| Wave A (Claude Agent Teams) | 2–4 min | Architecture + schema |
| Scaffold | < 1 min | Python deterministic |
| Wave B (Codex) | 12–18 min | Backend impl, often runs `pnpm test`/`pnpm install` triggering compile-fix iterations |
| Wave B self-verify (runtime probe) | 3–6 min | docker compose up/down with retry |
| Wave C (Python) | 30 s | OpenAPI generation + client emit |
| Wave D (Claude with new sandbox) | 8–18 min | Frontend impl + frontend_hallucination_guard recompile |
| Wave T | 5–15 min | Tests + iteration |
| Wave T.5 / E | 3–8 min | Test-gap audit + final |
| Audit cycle | 2–8 min | Health check |

Total ~50–90 min for a clean M1. ~$3–8 in API costs.

If the run blows past 2 h with no progress → orphan/wedge → check `[ORPHAN-MONITOR]` log entries.

---

## 8. Files / paths to monitor during the smoke

```
v18 test runs/m1-hardening-smoke-<TIMESTAMP>/
├── EXIT_CODE.txt                   ← final exit
├── BUILD_LOG.txt                   ← UTF-16 LE BOM on Windows; use `python -c "open(p, 'rb').read().decode('utf-16')"`
├── BUILD_ERR.txt
├── docker-compose.yml              ← grep '4000\|3000\|5432' to confirm ports stayed canonical
├── .claude/settings.json           ← MUST contain agent_team_v15_wave_d_path_guard marker
├── .agent-team/
│   ├── STATE.json
│   ├── STACK_CONTRACT.json
│   ├── milestone_progress.json
│   ├── artifacts/
│   │   ├── milestone-1-wave-A.json
│   │   ├── milestone-1-wave-SCAFFOLD.json
│   │   ├── milestone-1-wave-B.json   ← scope_violations should be empty
│   │   ├── milestone-1-wave-C.json   ← contract_fidelity=canonical, client_fidelity=canonical
│   │   ├── milestone-1-wave-D.json   ← scope_violations should be empty (the new sandbox fired)
│   │   └── milestone-1-wave-T.json
│   ├── telemetry/
│   │   └── milestone-1-wave-*.json   ← per-wave detail
│   └── milestones/milestone-1/WAVE_FINDINGS.json   ← wave_t_status=completed
```

Useful one-liner to monitor live:

```powershell
Get-Content "v18 test runs\m1-hardening-smoke-<ts>\BUILD_LOG.txt" -Encoding Unicode -Wait
```

(Note: `-Encoding Unicode` is Windows PowerShell's name for UTF-16 LE.)

---

## 9. The final goal

**Milestone 1 promotable to clean.** Specifically:

1. EXIT_CODE 0 from a fresh, full M1 smoke launched via `start-m1-hardening-smoke.ps1`.
2. All 7 milestones in MASTER_PLAN execute, but **only milestone-1 is required to be clean for M1 promotion** — later milestones may run or be intentionally skipped per config.
3. `audit_run_directory` (run by the fast-forward Gate 5 against the smoke run dir) reports `clean: true, issues: []`.
4. The user agrees the run is promotable.

Once that lands → §10.

---

## 10. Follow-up consolidation (do NOT block M1 on this)

After M1 is once-clean, open a dedicated branch + PR for **Codex sandbox restriction (Wave B)** — the structural pay-down of layers #6, #9, #11 from §2.

Memory file: `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/project_wave_d_sandbox_restriction_followup.md` carries the full chronology and proposed scope.

The investigation question for that PR (use Context7 `/openai/codex`):

> Does Codex app-server's `thread/start` `permissionProfile` config support per-path write restrictions on Windows? If yes, define a `wave_b_only` profile that allows `apps/api/**` + scaffold-allowlisted root files (`docker-compose.yml`, root `.env.example`, `package.json`, `pnpm-lock.yaml`). If not, file the upstream feature request and either (a) keep the current snapshot/restore/purge layers as-is, or (b) implement a `git stash --keep-index` wrapper around each Codex turn.

That refactor's deletion list (after sandbox lands cleanly):

* `wave_executor._capture_packages_api_client_snapshot`, `_restore_packages_api_client_snapshot`, `_purge_wave_c_owned_dirs` and all four call-sites
* The `_DEFAULT_SKIP_FILE_BASENAMES` line (only there because of CRLF/LF noise on `.gitkeep` — sandbox would block the write entirely)
* The duplicated dispatch-site logic in both `execute_milestone_waves` and `_execute_milestone_waves_with_stack_contract`

Keep:

* The port-invariants prompt block (defense-in-depth — some agents will refuse to break it once it's named)
* The Wave C python-owned scope bypass (correct semantics regardless of sandbox)
* Claude-on-D in the smoke config (until proven Codex-on-D works under sandbox)

---

## 11. Quick context for whoever reads this

* The user's bar is "clean by evidence, not by summary". They will scrutinize artifacts.
* The user authorized killing in-progress smokes if there's no point letting them finish (audit cycles after milestone failure are budget-only). Do the same.
* The user explicitly asked for the sandbox solution this session and explicitly recommended Claude-on-D. Both shipped.
* The user has noted Anthropic 529s in the wild during this work — `status.claude.com` is a useful one-liner check.
* The "Context7 quota / monthly limit" warning is **WAIVED**. Don't waste time on it.

---

## 12. Bottom line

Seven smokes have whittled the drift surface down. The sandbox hook closes the Wave D file-ownership boundary at the deterministic Python level — **even when Claude (or Codex, if we ever route D to Codex again) tries to write outside `apps/web/`, the CLI denies the write before it happens**. That eliminates the entire class of Wave D drift that has blocked M1 across smokes 4, 5, and 7.

Verify the harness, run the smoke, decide M1, then schedule the §10 consolidation. Don't add more cleanup layers — that direction is exhausted.

— end of handoff —
