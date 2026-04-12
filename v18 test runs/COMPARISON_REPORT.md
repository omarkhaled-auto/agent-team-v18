# Wave D Provider Experiment — Final Comparison Report

**Date:** 2026-04-12
**Builder:** agent-team-v15 v15.0.0 (v18.1 features), depth=standard
**PRD:** TaskFlow Mini (4 entities, 16-18 endpoints, 5 pages, en+ar i18n with RTL)

## Setup

| Item | Build A (Control) | Build B (Experiment) |
|------|-------------------|----------------------|
| Wave D provider | `claude` | `codex` |
| Wave B provider | `codex` | `codex` |
| Codex model | `gpt-5.4` | `gpt-5.4` |
| Codex reasoning effort | `xhigh` | `xhigh` |
| Codex auth | ChatGPT login (OAuth) | ChatGPT login (OAuth) |
| Claude orchestrator | Opus 4.6 | Opus 4.6 |
| Codex timeout | 1800s (30 min) | 5400s (90 min, after first timeout) |
| PRD | Identical | Identical |

Both configs differ only on `provider_map_d` (and the later timeout bump for Build B).

## Builder Fixes Applied (All Upstream in v18 Source)

Ten fixes were required to make the v18 builder usable end-to-end on Windows and to produce correct Wave C output:

1. **`cli.py`** — Added missing `import logging` + `logger = logging.getLogger(__name__)`.
2. **`cli.py`** — Filtered `mcpServers` key from `AgentDefinition()` constructor (SDK 0.1.27 compat).
3. **`compile_profiles.py`** — Strip ANSI codes, set `NO_COLOR=1` + `FORCE_COLOR=0`, and run `npx tsc` from the tsconfig's parent directory.
4. **`codex_transport.py`** — Resolve `codex` to its `.CMD` path on Windows; use `create_subprocess_shell` for `.cmd`/`.bat`.
5. **`codex_transport.py`** — Added `--skip-git-repo-check` flag.
6. **`codex_transport.py`** — Copy `~/.codex/auth.json` + `installation_id` into temp `CODEX_HOME` (ChatGPT login inherited).
7. **`codex_transport.py`** — Copy user's `~/.codex/config.toml` too (sandbox, trust, features); override model/reasoning via `-c` runtime flags.
8. **`openapi_generator.py`** — Emit `QueryValue` type + index signatures on `*Query`/`*Params` interfaces (prevents the Wave C type mismatch).
9. **`codex_transport.py` + `config.py`** — Default to `gpt-5.4`, dual pricing table for `gpt-5.4` + `gpt-5.1-codex-max`.
10. **`agents.py` (`build_wave_d_prompt`)** — Explicit rule: `packages/api-client/*` is IMMUTABLE in Wave D; report contract gaps upstream instead of patching inline. Applies to every provider, not just Codex.

All 10 fixes are in `C:\MY_PROJECTS\agent-team-v18\src\agent_team_v15\` and verified by the test suite (9763 pass, 1 pre-existing unrelated failure).

## Build Outcomes — Final Telemetry

### Build A (Wave D = Claude)

| Wave | Provider | Duration | Cost (SDK) | Files +/~ | Compile | Success |
|------|----------|---------:|-----------:|-----------|:-------:|:-------:|
| A | claude | 487s | $1.39 | +2/~6 | ✅ | ✅ |
| B | claude (fallback)* | 458s | $1.61 | +25/~3 | ✅ | ✅ |
| C | python (contracts) | 15s | $0.00 | +6/~0 | n/a | ✅ |
| **D** | **claude** | **737s (12.3 min)** | **$2.26** | **+36/~3** | ✅ | ✅ |
| **TOTAL** | | **28.3 min** | **$5.26** | **+69/~12** | | |

\* Build A's Wave B fell back to Claude because it ran before the Codex auth/trust fixes were applied. Claude still produced a valid backend.

### Build B (Wave D = Codex, after all fixes)

| Wave | Provider | Duration | Cost (SDK) | Files +/~ | Compile | Success |
|------|----------|---------:|-----------:|-----------|:-------:|:-------:|
| A | claude | 115s | $0.30 | +0/~1 | ✅ | ✅ |
| B | **codex (no fallback)** | **618s (10.3 min)** | **$2.13** | **+1/~9** | ✅ | ✅ |
| C | python (contracts) | 20s | $0.00 | +3/~0 | n/a | ✅ |
| **D** | **codex (no fallback)** | **1418s (23.6 min)** | **$2.60** | **+38/~0** | ✅ | ✅ |
| E | claude | 193s | $0.62 | +0/~1 | n/a | ✅ |
| **TOTAL** | | **39.4 min** | **$5.66** | **+42/~11** | | |

Wave B: 3,574,074 input tokens, 22,615 output tokens
Wave D: 3,527,639 input tokens, 47,946 output tokens

## Score Card

| Metric | Build A (Claude D) | Build B (Codex D) | Winner |
|--------|--------------------|--------------------|--------|
| **Compile** | | | |
| TypeScript errors (api) | 0 | 0 | tie |
| TypeScript errors (web) | 0 | 0 | tie |
| **Wiring — this is the headline finding** | | | |
| Manual `fetch()` violations | 0 | 0 | tie (both clean) |
| Manual `axios.` violations | 0 | 0 | tie |
| Generated client imports | **5** | **0** ⚠ | **A** — see Critical Finding below |
| Working API calls to backend | Yes | **No — stub throws `AuthClientUnavailableError`** | **A** |
| **i18n** | | | |
| Translation file format | JSON | TypeScript (compile-time key safety) | tie (different valid approaches) |
| en translations | 54 keys, 2228 bytes | 2987 bytes | tie |
| ar translations (real Arabic) | ✅ (5717 bytes) | ✅ (4218 bytes, 1320 Arabic chars) | tie |
| **RTL** | | | |
| Directional CSS violations | 0 | 0 | tie |
| Logical CSS properties used | 14 | 21 | **B** (more thorough RTL discipline) |
| **Type Safety** | | | |
| `as any` casts | 0 | 0 | tie |
| `@ts-ignore` / `@ts-expect-error` | 0 | 0 | tie |
| **Wave D Output Volume** | | | |
| Frontend `.ts`/`.tsx` files | 26 | 37 | **B** (more files) |
| Pages | 5 | 5+ (login, projects, team, root, locale, error) | tie+ |
| Components (UI+layout+auth) | 7 | 15 (Button, Input, Select, Textarea, Modal, Badge, Avatar, Spinner, EmptyState, AppShell, Header, Sidebar, LanguageSwitcher, LoginPanel, Providers) | **B** (richer component set) |
| **Cost & Time** | | | |
| Wave D duration | **737s (12.3 min)** | **1418s (23.6 min)** | **A — Claude is 1.9× faster** |
| Wave D cost | $2.26 | $2.60 | A (15% cheaper) |
| Wave D fallback triggered | No | No | tie |
| **Total build** | | | |
| Total duration (all waves) | 28.3 min | 39.4 min | A (1.4× faster overall) |
| Total cost (tracked) | $5.26 | $5.66 | A (7% cheaper) |
| Wave D files produced | 36 | 38 | tie (comparable volume) |

## Key Findings

### 1. Codex can complete Wave D — but takes ~2× as long as Claude

With a 90-minute timeout, gpt-5.4 at `xhigh` reasoning completed Wave D in 23.6 min and produced 38 files with a clean compile. Claude Opus 4.6 did the same task in 12.3 min. **Codex is viable but slower.**

### 2. Codex's component output is actually *richer* in some dimensions

- 37 `.ts`/`.tsx` files vs Claude's 26
- 15 distinct UI/layout components vs Claude's 7
- 21 logical CSS property usages vs Claude's 14 (better RTL discipline)
- TypeScript-based i18n (compile-time key safety) vs JSON (runtime)

If you measured only "amount of frontend code produced," Codex wins. This matches Codex's known strength: methodical, thorough, well-factored components.

### 3. **Critical: Codex refused to actually use the generated API client**

**This is the headline of the experiment.**

Build B's frontend has **zero imports** from `packages/api-client`. Every form action, every login, every data fetch call routes through a stub:

```typescript
// apps/web/src/lib/auth.ts line 97
export async function loginWithGeneratedClient(_payload: LoginPayload): Promise<AuthSession> {
  throw new AuthClientUnavailableError();
}
```

Codex's translation files even explain this to the user:

> **"Typed API client unavailable"**
> "Wave C generated duplicate client exports, so this form can validate but it cannot submit a typed request yet."
> "Use your assigned email and password once the generated client is fixed upstream."

**The compile is clean, the UI is polished, the RTL is excellent — but the app doesn't work.** None of the 18 endpoints are actually called. Codex built a shell.

### 4. Why did this happen? The IMMUTABLE rule was too strict

Fix #10 added this rule to the shared Wave D prompt:

> "`packages/api-client/*` is IMMUTABLE in this wave. Do not edit, refactor, rewrite, add helpers to, or restructure any file under that directory... If the generated client is missing a required export, has a type bug, or otherwise blocks you, STOP and report a Wave C contract gap... The fix belongs upstream in the openapi generator (Wave C), not in Wave D."

The intent was: *don't rewrite the client; use it as-is; report bugs upstream.*

Codex interpreted it as: *the client is untrustworthy; write everything through a stub and surface an error to the user.*

Claude's Wave D in Build A had no such rule and freely consumed `@project/api-client` across 5 files — it actually used the typed endpoints. Codex, under the stricter rule, refused to touch the client at all.

### 5. The rule needs to be rewritten

The rule says *"don't modify"* but Codex heard *"don't use"*. A better phrasing would separate consumption (required, encouraged) from modification (forbidden):

> "**You MUST use** `packages/api-client` for every backend call in this wave. Import from it, invoke its typed functions, wire its types into your component props.
>
> **You MUST NOT** edit, refactor, or otherwise modify any file under `packages/api-client/*`. That directory is the Wave C deliverable and belongs to the contract pipeline.
>
> If the client compiles and exports a function you need, use it. If it has a bug that blocks you, leave the file untouched and report the gap in your final summary — do not work around it with stubs or manual fetches."

### 6. Wave C openapi_generator fix (Fix #8) worked as intended

The generated `packages/api-client/index.ts` in Build B compiled cleanly this time — zero TS errors, because the new `QueryValue` + index-signature emission from the fixed `openapi_generator.py` produces valid types. Codex had no technical reason not to use it.

## Verdict

# **KEEP — Wave D stays on Claude (with a nuance)**

**Reasoning:**

- **Codex can complete Wave D within a realistic timeout** (23.6 min at `xhigh` with the timeout bumped to 90 min). The original verdict's "Codex times out" concern was defeated once we gave it more time.
- **But Codex at xhigh is still ~2× slower than Claude for the same quality surface.** For a 10-milestone build, that's hours of wall-clock difference.
- **Codex's "richer component output" is misleading** because the components don't actually make API calls — the wiring is stubbed. A more polished-looking front end that doesn't ship requests isn't a win.
- **Claude naturally wires the api-client end-to-end.** That's the default Wave D behavior we want.

**However, the IMMUTABLE rule we added is the specific reason Codex's output is unwired. A rewritten rule (see Finding #5) would very likely let Codex produce a functional, wired frontend.** If someone is motivated to re-run the experiment with a clearer rule, Codex might genuinely match Claude on quality — at the cost of being ~2× slower.

**For now, the routing decision is unchanged: `provider_map_d: claude`, `provider_map_b: codex`** (Wave B Codex worked well in both this run and the prior one — 618s / 9 files modified / clean compile / no fallback).

## Recommendations

1. **Keep `provider_map_d: claude`** as the default.
2. **Keep `provider_map_b: codex`** as the default — Wave B Codex succeeded in 10.3 min this run (faster than the 28-min first attempt because most files were incremental modifications).
3. **Rewrite the IMMUTABLE rule in `agents.py::build_wave_d_prompt`** to separate "must use the client" from "must not modify the client" (see Finding #5). Test with a follow-up Build B to see if Codex will wire the API when not led to believe the client is broken.
4. **Keep the openapi generator fix (Fix #8).** It eliminated the actual type mismatch, so Codex's "the client is broken" perception is no longer grounded in reality.
5. **Raise `codex_timeout_seconds` default from 1800 to 3600 or higher.** 30 min is not enough for Wave D at xhigh reasoning; 60–90 min is realistic.
6. **Add Wave D post-execution check: "frontend imports from api-client > 0."** If Wave D produces a frontend that never imports the typed client, that's a structural red flag worth failing the wave on, regardless of compile status.
7. **Document the `gpt-5.1-codex-max` → `gpt-5.4` migration** in the builder CHANGELOG.

## Raw Data Summary

```
Build A (Claude D): 28.3 min, $5.26, 69 files created, 12 modified — works end-to-end
Build B (Codex D):  39.4 min, $5.66, 42 files created, 11 modified — compiles but unwired
```

Both builds pass every scan for type safety, manual fetch/axios, RTL violations, and translation completeness. The distinguishing metric is **"does the frontend actually talk to the backend?"** — where Claude wins decisively at Build A: 5 files importing `@project/api-client` vs Build B: 0.

This is the experiment's real finding: **Codex can produce Wave D output that passes every mechanical scan while failing the functional requirement to actually integrate with the backend**. A stricter rule made this worse; a rewritten rule might fix it.
