# Phase C -- Wiring Verification Report

**Date:** 2026-04-16
**Branch:** `phase-c-truthfulness-audit-loop`
**Verifier:** Wave 3 wiring-verifier
**Predecessor:** Phase C Wave 2 implementation (N-08, N-09, N-10, N-17, latent wiring, carry-forwards)

---

## Overall Verdict: PASS

All 6 verification passes completed successfully. No wiring failures detected.

---

## V1 -- Default Flags (N-17 ON, all others OFF)

**Result: PASS**

### Flag defaults verified

| Flag | Default | Source |
|---|---|---|
| `mcp_informed_dispatches_enabled` (N-17) | `True` | `config.py:908` |
| `audit_fix_iteration_enabled` (N-08) | `False` | `config.py:900` |
| `content_scope_scanner_enabled` (N-10) | `False` | `config.py:892` |

### N-17 call chain traced end-to-end

1. **Entry:** `cli.py:3753-3762` -- `_build_wave_prompt_with_idioms` closure wraps `_build_wave_prompt`.
2. **Pre-fetch:** For waves B and D, calls `_prefetch_framework_idioms(w, milestone.id, worktree_cwd, run_config)` at `cli.py:3758`.
3. **Flag gate:** `_prefetch_framework_idioms` at `cli.py:1762` checks `v18.mcp_informed_dispatches_enabled`; returns `""` if False.
4. **Cache:** Results cached to `.agent-team/framework_idioms_cache.json` at `cli.py:1771-1845`.
5. **Propagation:** `kwargs["mcp_doc_context"]` set at `cli.py:3761` -> passed through `_build_wave_prompt` at `cli.py:1887` -> `agents.build_wave_prompt` at `agents.py:9088` (Wave B) / `agents.py:9100` (Wave D).
6. **Prompt injection:** `build_wave_b_prompt` at `agents.py:7955-7962` inserts `[CURRENT FRAMEWORK IDIOMS]` section when `mcp_doc_context` is non-empty.

### Other features confirmed OFF

- N-08: gated by `config.v18.audit_fix_iteration_enabled` (default `False`) at `cli.py:6278`.
- N-10: gated by `config.v18.content_scope_scanner_enabled` (default `False`) at `cli.py:5763`.

---

## V2 -- `v18.audit_fix_iteration_enabled: True`

**Result: PASS**

### N-08 initialization traced

- `cli.py:6277-6280`: Flag check -- requires BOTH `config.v18.audit_fix_iteration_enabled` AND `config.tracking_documents.fix_cycle_log` to be True.
- `cli.py:6281-6288`: If enabled, calls `initialize_fix_cycle_log(requirements_dir)`. On exception, sets `_n08_log_enabled = False` (non-blocking).

### N-08 append traced

- `cli.py:6346-6349`: `_run_audit_fix_unified(...)` call returns `modified_files, fix_cost`.
- `cli.py:6352-6372`: Immediately AFTER the fix call, if `_n08_log_enabled`:
  - Imports `build_fix_cycle_entry`, `append_fix_cycle_entry` from `tracking_documents`.
  - Filters findings by severity threshold (`_sev_order[:_sev_cutoff + 1]`), caps at 20.
  - Builds entry with `phase="audit-fix"`, `cycle_number=cycle`, `failures=_filtered`, `previous_cycles=cycle - 1`.
  - Calls `append_fix_cycle_entry(_n08_req_dir, _entry)`.
  - Exception handler: non-blocking warning.

### Recovery paths unaffected

Existing `append_fix_cycle_entry` calls in `fix_executor.py:177` are independent of N-08 additions. The N-08 code is confined to the loop layer in `_run_audit_loop` (cli.py:6276-6372) and does NOT touch `_run_audit_fix_unified` (cli.py:5986-6047), matching the architect's "loop-layer injection" directive.

---

## V3 -- `v18.content_scope_scanner_enabled: True`

**Result: PASS**

### Scanner invocation traced

- `cli.py:5763`: Flag check `getattr(config.v18, "content_scope_scanner_enabled", False)`.
- `cli.py:5765-5768`: Imports `DEFAULT_RULES`, `merge_findings_into_report`, `scan_repository` from `forbidden_content_scanner`.
- `cli.py:5770-5771`: `scan_root = Path(audit_dir).parent`; `fc_findings = scan_repository(scan_root, DEFAULT_RULES)`.
- `cli.py:5772-5773`: If findings exist, `merge_findings_into_report(report, fc_findings)`.
- `cli.py:5778-5779`: Exception handler: non-blocking warning.

### Scanner module verified (`forbidden_content_scanner.py`)

- **6 default rules** with correct IDs and patterns:
  - FC-001-stub-throw (MAJOR): `throw\s+new\s+Error\(['"](not implemented|todo|placeholder|unimplemented)`
  - FC-002-todo-comment (MINOR): `//\s*(TODO|FIXME|XXX)\b`
  - FC-003-block-todo (MINOR): `/\*[\s\S]*?(TODO|FIXME|XXX)[\s\S]*?\*/` (multiline)
  - FC-004-placeholder-secret (MAJOR): `['"](CHANGE_ME|YOUR_API_KEY|REPLACE_ME|PLACEHOLDER)['"]`
  - FC-005-untranslated-rtl (MINOR): `[\u0600-\u06FF\u0750-\u077F]+`
  - FC-006-empty-fn (MINOR): `(async\s+)?[a-zA-Z_$][\w$]*\s*\([^)]*\)\s*\{\s*\}`
- **Severity mapping**: MAJOR -> HIGH, MINOR -> LOW (canonical AuditFinding vocabulary).
- **Findings in canonical shape**: `AuditFinding(finding_id=..., auditor="forbidden_content", ...)` at `forbidden_content_scanner.py:318-329`.
- **Performance bounds**: `_MAX_FILE_SIZE=200KB`, `_MAX_FINDINGS_PER_RULE=200`, `_MAX_FINDINGS_TOTAL=500`.
- **Excludes**: node_modules, dist, .next, build, __pycache__, *.spec.*, *.test.*, migrations, i18n.

---

## V4 -- Latent Wirings (D-02, D-09, D-14)

**Result: PASS**

### D-02: Skip-vs-block at `wave_executor.py:1841-1856`

- `wave_executor.py:1848`: `if docker_ctx.infra_missing:` -> `return True, "", []` (skip -- success NOT flipped).
- `wave_executor.py:1856`: else `return False, reason, []` (block).
- **Caller at `wave_executor.py:3161-3163`**: `if not probe_ok:` -> `wave_result.success = False` + `wave_result.error_message = probe_error`.
- **Invariant holds**: skip returns `True` which means `probe_ok = True`, so `wave_result.success` is NOT set to False. Block returns `False` which properly triggers the failure path.

### D-09: MCP pre-flight (`cli.py:10749-10758`)

- `cli.py:10751-10752`: `from .mcp_servers import run_mcp_preflight; _preflight = run_mcp_preflight(cwd, config)`.
- Fires at pipeline startup, AFTER config load, BEFORE any wave dispatch.
- Exception handler: non-blocking warning at `cli.py:10758`.

### D-09: Contract E2E fidelity header (`cli.py:12957-12967`)

- `cli.py:12961`: checks `_contract_e2e_path.is_file()`.
- `cli.py:12963-12965`: `from .mcp_servers import contract_engine_is_deployable, ensure_contract_e2e_fidelity_header`. Calls `ensure_contract_e2e_fidelity_header(_contract_e2e_path, contract_engine_available=_ce_available)`.
- Fires AFTER runtime verification.

### D-14: 4 artefact fidelity labels

| Site | File:Line | Label | Mechanism |
|---|---|---|---|
| GATE_FINDINGS.json (1st) | `cli.py:11677` | `"fidelity": "static"` | JSON schema field |
| GATE_FINDINGS.json (2nd) | `cli.py:12884` | `"fidelity": "static"` | JSON schema field |
| RUNTIME_VERIFICATION.md | `cli.py:12932-12937` | `"runtime"` | `ensure_fidelity_label_header(report_path, "runtime")` |
| VERIFICATION.md | `verification.py:1232-1242` | `"runtime"` or `"heuristic"` | `ensure_fidelity_label_header(path, _fidelity)` based on test presence |

### D-14: Idempotency of `ensure_fidelity_label_header`

- `mcp_servers.py:544-546`: Checks `anchor = "Verification fidelity:"` in first 500 chars of file. Returns `False` (no-op) if already present.
- Calling twice produces NO duplicate header.

---

## V5 -- Carry-Forward (C-CF-1, C-CF-2, C-CF-3)

**Result: PASS**

### C-CF-1: `AuditFinding.from_dict` evidence fold

- `audit_models.py:91-98`: Evidence fold logic:
  ```python
  evidence_list = data.get("evidence", [])
  if not evidence_list:
      file_hint = data.get("file")
      desc_hint = data.get("description") or ""
      if file_hint:
          evidence_list = (
              [f"{file_hint} -- {desc_hint[:80]}"] if desc_hint else [str(file_hint)]
          )
  ```
- **Build-l empirical check**: `AUDIT_REPORT.json` first finding keys: `['category', 'description', 'file', 'id', 'line', 'remediation', 'severity', 'source_finding_ids', 'title']`. No `evidence` key. All 28 findings have `file` and `description` fields, so the evidence fold will synthesize non-empty evidence for all 28.

### C-CF-2: 8 scaffold files

- `scaffold_runner.py:766-777` (`_scaffold_root_files`): Emits 6 files including `turbo.json` at line 772.
- `scaffold_runner.py:798-822` (`_scaffold_api_foundation`): Emits:
  - `nest-cli.json` (line 800)
  - `tsconfig.build.json` (line 801)
  - `main.ts`, `env.validation.ts`, `prisma.service.ts`, `prisma.module.ts`, `validation.pipe.ts` (lines 802-806)
  - 5 module stubs: auth, users, projects, tasks, comments (lines 814-820)
- Total new scaffold-owned paths: `turbo.json` + `nest-cli.json` + `tsconfig.build.json` + 5 module stubs = 8 new paths (matching spec).

### C-CF-3: `build_report(extras=...)` propagation

- `audit_models.py:758`: `extras: dict[str, Any] | None = None` parameter on `build_report`.
- `audit_models.py:807-808`: `if extras: report.extras = dict(extras)`.
- `AuditReport.extras` field: `audit_models.py:279` -- `extras: dict[str, Any] = field(default_factory=dict)`.
- **Caller at `cli.py:739-740`**: `original_extras = dict(report.extras) if report.extras else {}` captures extras before rebuild.
- **Caller at `cli.py:857`**: `extras=original_extras` passes them to `build_report` -- extras survive the evidence-gating rebuild.

---

## V6 -- N-09 Hardener Prompt Ordering

**Result: PASS**

### `build_wave_b_prompt` section order (agents.py:7941-8016)

1. **Scope preamble** (A-09): `existing_prompt_framework` at line 7942 (includes milestone-scope preamble when enabled).
2. **`[CURRENT FRAMEWORK IDIOMS]`** (N-17): lines 7955-7962, conditional on `mcp_doc_context` non-empty.
3. **`[CANONICAL NESTJS 11 / PRISMA 5 PATTERNS]`** (N-09): lines 7964-8015, always present.
4. **`[YOUR TASK]`**: line 8016.

### All 8 AUD-* pattern IDs present in `build_wave_b_prompt`

- AUD-009 (line 7968): Global exception filter / APP_FILTER
- AUD-010 (line 7974): ConfigService getOrThrow
- AUD-012 (line 7980): bcrypt native
- AUD-013 (line 7986): Joi validationSchema
- AUD-016 (line 7992): JWT strategy
- AUD-018 (line 7998): ApiProperty type
- AUD-020 (line 8004): ValidationPipe
- AUD-023 (line 8010): prisma migrate deploy

### Codex path (`CODEX_WAVE_B_PREAMBLE`)

All 8 AUD-* patterns present in `codex_prompts.py:46-157`. The Codex path wraps the `original_prompt` (which already contains the N-09/N-17 sections from `build_wave_b_prompt`) with `CODEX_WAVE_B_PREAMBLE` as a prefix. This results in the N-09 patterns appearing twice (reinforcement, not harmful).

### Wave D prompt

`build_wave_d_prompt` at `agents.py:8734-8741` also conditionally inserts `[CURRENT FRAMEWORK IDIOMS]` before `[YOUR TASK]`, following the same ordering pattern.

---

## Out-of-Scope Findings

1. **Codex path N-09 duplication (cosmetic):** The Codex wrapper `CODEX_WAVE_B_PREAMBLE` contains all 8 AUD-* patterns, and then the inner prompt from `build_wave_b_prompt` also contains them. This is harmless (reinforcement) but could be cleaned up in Phase D by making the Codex preamble omit the hardener blocks when the inner prompt already includes them.

2. **N-17 Codex path integration:** The `mcp_doc_context` is correctly propagated through `build_wave_b_prompt` -> Codex wrapper. The N-17 `[CURRENT FRAMEWORK IDIOMS]` section appears between the Codex preamble's hardener blocks and the inner prompt's hardener blocks in the Codex path. Section ordering is: Codex directives + N-09 -> original prompt (which starts with N-17 -> N-09 duplicate -> YOUR TASK). No functional issue.

---

## Final Checklist

- [x] All 6 verifications passed
- [x] Wiring verification report at `docs/plans/2026-04-16-phase-c-wiring-verification.md`
- [x] No source code modifications (read-only investigation)
- [x] Out-of-scope findings documented
