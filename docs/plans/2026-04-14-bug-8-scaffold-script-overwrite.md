# Bug #8 follow-up: scaffold_runner npm-script overwrite by Wave B

**Status:** observation (non-blocking)
**Date:** 2026-04-14
**Observed during:** build-d-rerun smoke test, Wave B complete

## Symptom

After Wave B, `/c/smoke/clean/package.json` (monorepo root) shows:

```json
"scripts": { "generate-openapi": "ts-node --project apps/api/tsconfig.json scripts/generate-openapi.ts" },
"devDependencies": { "tsx": "^4.7.0", ... },
"dependencies": { "@nestjs/swagger": "^7.0.0", ... }
```

`scaffold_runner.py` (lines 14, 84, 158-179) is designed to set the script to
`tsx scripts/generate-openapi.ts` and pin `tsx` as the runner. The `tsx` devDep
stuck, but the actual script line was rewritten to use `ts-node`, almost
certainly by the Codex agent during Wave B (ts-node was already a dep for
`prisma/seed.ts`).

## Why it is not blocking this run

- Wave C (deterministic OpenAPI generator) ran in 12s with `success: true`.
- `packages/api-client/` was generated; Wave D/T/E consume artifacts, not the script.
- `ts-node` is a functionally equivalent runner here.

## Risk

- `tsx` devDep is now dead weight (installed but unused).
- If a future flow re-invokes `npm run generate-openapi` in an environment
  that has `tsx` but lacks ts-node's tsconfig wiring, behavior diverges.
- More generally: the guarantee offered by `_ensure_package_json_openapi_script`
  only holds until the next wave that rewrites the same file.

## Proposed fix (post-run)

One of:

1. **Re-assert post-Wave-B:** call `_ensure_package_json_openapi_script`
   immediately after Wave B completes, before scanners consume the result.
2. **Make the script setting stack-contract-enforced:** add the
   `scripts.generate-openapi` line to `required_script_entries` in the
   NestJS/Prisma stack contract, so a violation is flagged when an agent
   rewrites it. Telemetry already carries `stack_contract_violations`.
3. **Document as acceptable:** accept either `tsx` or `ts-node` as the runner
   as long as the script key exists and OpenAPI generation succeeds. Lowest
   cost; matches current behavior.

Recommendation: option 2 (stack-contract enforcement) is the right long-term
fix since Tier 2 machinery is already in place; option 3 is acceptable as an
interim if nothing else breaks.

## Verification after fix

- Run a fresh smoke build to M1-Wave-C; grep the root `package.json` for
  `"generate-openapi":\s*"tsx`.
- Confirm `stack_contract_violations` flags an agent that reverts to `ts-node`.
