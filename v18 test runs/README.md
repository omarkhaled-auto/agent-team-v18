# v18 Test Runs — Reference Outputs

Snapshot of the two TaskFlow-mini builds that shook out the v18.1 multi-provider
Wave D experiment. Kept here as a reference for what the builder produces and
what's worth checking in future runs.

## What's in here

| Path | Contents |
|------|----------|
| `TASKFLOW_MINI_PRD.md` | The PRD both builds consumed (identical for both). |
| `WAVE_D_EXPERIMENT_PLAN.md` | Original experiment design doc. |
| `COMPARISON_REPORT.md` | Full comparison report — the definitive writeup of what each build produced, with the final verdict (KEEP: Wave D stays on Claude). |
| `build-a-claude/` | Wave D = Claude. `provider_map_d: claude`, `provider_map_b: codex`. |
| `build-b-codex/` | Wave D = Codex (gpt-5.4, xhigh). `provider_map_d: codex`, `provider_map_b: codex`. |

## What was excluded from the copy

To keep the snapshot small (~2 MB total instead of ~1.4 GB):

- `node_modules/` (all nesting levels) — installed deps, regenerate with `npm install`
- `.next/`, `dist/`, `*.tsbuildinfo` — build artifacts
- `data/*.db`, `data/*.sqlite3` and associated `-shm`/`-wal` files — pattern memory, chroma, symbol dbs
- `package-lock.json` — auto-regenerates from `package.json`

## What was kept

- Full source tree under `apps/api/` and `apps/web/`
- Generated API client under `packages/api-client/`
- Prisma schema + migrations under `prisma/` (or `apps/api/prisma/`)
- Root `package.json`, `docker-compose.yml`, `tsconfig*.json`
- Full `.agent-team/` directory: `MASTER_PLAN.md`, `CONTRACTS.{md,json}`, per-milestone `REQUIREMENTS.md`, `TECH_RESEARCH.md`, all `artifacts/*.json` and `telemetry/*.json` files

## Quick lookup — what each build demonstrates

### `build-a-claude/` — the baseline
Complete, functional TaskFlow backend + frontend. Wave B fell back to Claude (this run predated the Codex auth fixes); Wave D ran on Claude and produced 36 frontend files that actually import and use `@project/api-client`. Compiles clean end-to-end. Duration: **28.3 min**, $5.26.

### `build-b-codex/` — the experiment build
Codex (gpt-5.4, xhigh) executed both Wave B and Wave D successfully, no fallback. Produced **more** frontend files than Build A (37 vs 26) with richer components and better RTL discipline.

**BUT** the build is functionally broken: Codex's Wave D wrote `loginWithGeneratedClient()` as a stub that throws `AuthClientUnavailableError`, and the frontend has **zero** imports from `packages/api-client`. The translation strings even explain this to the user ("Typed API client unavailable").

This happened because an earlier version of the Wave D prompt said "the api-client is IMMUTABLE; report bugs upstream" — Codex interpreted that as "don't use the client at all." The prompt has since been rewritten to separate **MUST USE** from **MUST NOT MODIFY** (see `agents.py::build_wave_d_prompt`). A re-run with the corrected prompt would be the next verification.

Duration: **39.4 min**, $5.66.

## Telemetry quick reference

Per-wave telemetry lives under each build's `.agent-team/telemetry/`:

```
milestone-1-wave-A.json   provider, cost, duration, compile result
milestone-1-wave-B.json   same
milestone-1-wave-C.json   Python contract gen (no provider)
milestone-1-wave-D.json   same — the interesting one
milestone-1-wave-E.json   verification pass
```

Each file records `provider`, `provider_model`, `fallback_used`, token counts,
files created/modified, and compile status for that wave.

## When to look at this snapshot

- Designing a new Wave D rule and wondering what output shape is correct → `build-a-claude/apps/web/`
- Wondering if the Wave B Codex path works in practice → `build-b-codex/.agent-team/telemetry/milestone-1-wave-B.json` (shows `provider: codex, fallback_used: false, compile_passed: true`)
- Wondering what "Codex followed the rule too literally" looks like → `build-b-codex/apps/web/src/lib/auth.ts` line 97 (`loginWithGeneratedClient` stub)
- Wondering how big the generated api-client is → `build-a-claude/packages/api-client/` (Claude's revised version) vs `build-b-codex/packages/api-client/` (openapi generator's output after Fix #8)
