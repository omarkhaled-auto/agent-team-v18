# Failure Recovery Testing Results

**Date:** 2026-03-19
**Pipeline:** agent-team-v15
**Target:** 8/8 PASS
**Result:** 8/8 PASS

---

## Summary

All 8 failure scenarios were tested against the actual pipeline code. Every scenario
demonstrated graceful degradation with no crashes. No code fixes were required.

| # | Scenario | Expected | Actual | Status |
|---|---------|---------|--------|--------|
| 1 | Corrupted Interface Registry | Loads empty registry without crash | Returns `InterfaceRegistry()` with 0 modules for corrupt JSON, invalid JSON, missing file, and empty file | PASS |
| 2 | Missing CONTRACTS.md | Milestone prompt builder works without contracts | `contracts_md_text=""` (default) is falsy, skips injection block entirely. None also handled. | PASS |
| 3 | Corrupted STATE.json | Returns None or safe defaults | Returns `None` for invalid JSON, empty file, binary garbage, missing dir. Wrong-schema JSON returns `RunState` with safe defaults via `_expect()` type guards. | PASS |
| 4 | PRD Parser with Empty/Garbage Input | Returns empty ParsedPRD | Empty string, None, whitespace, garbage text, and 100K garbage all return `ParsedPRD()` with 0 entities. Guard: `if not prd_text or len(prd_text.strip()) < 50` | PASS |
| 5 | Business Rules with Edge Cases | Returns empty rules list | Minimal entity table returns 0 rules (no business rules extractable). No entities returns 0 rules. No crash on any input. | PASS |
| 6 | Contract Generator with Missing Data | Returns valid ContractBundle | Empty ParsedPRD, None input, entities-only, empty fields, missing name key all produce valid `ContractBundle` with appropriate defaults. Uses `getattr()` safely. | PASS |
| 7 | Quality Scans on Empty Directory | Returns 0 violations | All three scans (`run_placeholder_scan`, `run_handler_completeness_scan`, `run_business_rule_verification`) return empty lists on empty dirs, non-existent dirs, None rules, and empty rules. Phantom entity correctly produces 1 RULE-001 violation. | PASS |
| 8 | Runtime Verification Without Docker | Skips gracefully with report | `check_docker_available()` returns False when Docker unreachable; `run_runtime_verification()` returns `RuntimeReport(docker_available=False)` immediately. Missing compose file also handled (returns early with empty report). | PASS |

---

## Detailed Test Cases Per Scenario

### Scenario 1: Corrupted Interface Registry

**File:** `src/agent_team_v15/interface_registry.py` (`load_registry` at line 340)

| Sub-test | Input | Result |
|----------|-------|--------|
| Corrupt JSON | `{"corrupt": true}` | `InterfaceRegistry()` with 0 modules |
| Invalid JSON | `NOT JSON AT ALL {{{{` | `InterfaceRegistry()` with 0 modules |
| Missing file | Non-existent path | `InterfaceRegistry()` with 0 modules |
| Empty file | `""` | `InterfaceRegistry()` with 0 modules |

**Defense mechanism:** `load_registry` catches `(json.JSONDecodeError, KeyError)` and returns empty registry. Missing file check via `if not path.is_file()`.

### Scenario 2: Missing CONTRACTS.md

**File:** `src/agent_team_v15/agents.py` (`build_milestone_prompt` at line 3109)

| Sub-test | Input | Result |
|----------|-------|--------|
| Empty string (default) | `contracts_md_text=""` | Block skipped (falsy check) |
| None | `contracts_md_text=None` | Block skipped (falsy check) |
| Oversized (50K chars) | 50K character string | Truncated to 30K with truncation notice |

**Defense mechanism:** `if contracts_md_text:` guard skips entire injection block for empty/None values. Truncation at 30K chars prevents context window overflow.

### Scenario 3: Corrupted STATE.json

**File:** `src/agent_team_v15/state.py` (`load_state` at line 353)

| Sub-test | Input | Result |
|----------|-------|--------|
| Invalid JSON | `NOT VALID JSON {{{` | `None` |
| Empty file | `""` | `None` |
| Wrong schema | `{"random_key": "value"}` | `RunState` with safe defaults |
| Wrong types | `{"total_cost": "string"}` | `RunState` with `total_cost=0.0` (type guard) |
| Missing directory | Non-existent path | `None` |
| Binary garbage | `\x00\x01\x02\xff\xfe` | `None` |

**Defense mechanism:** `_expect()` helper validates types and returns defaults for mismatched types. Broad exception catch: `(json.JSONDecodeError, KeyError, TypeError, ValueError, OSError, UnicodeDecodeError)`.

### Scenario 4: PRD Parser with Empty/Garbage Input

**File:** `src/agent_team_v15/prd_parser.py` (`parse_prd` at line 108)

| Sub-test | Input | Result |
|----------|-------|--------|
| Empty string | `""` | `ParsedPRD()` with 0 entities |
| None | `None` | `ParsedPRD()` with 0 entities |
| Short garbage | `"Hello world"` | `ParsedPRD()` with 0 entities |
| 100K garbage | `"x" * 100000` | `ParsedPRD()` with 0 entities |
| Whitespace only | `"   \n\n\t\t   "` | `ParsedPRD()` with 0 entities |
| Minimal PRD | `"# Project: Test\n..."` | `ParsedPRD(project_name="Test")` |

**Defense mechanism:** Guard at line 113: `if not prd_text or len(prd_text.strip()) < 50: return ParsedPRD()`. The `not prd_text` handles both empty string and None.

### Scenario 5: Business Rules with Edge Cases

**File:** `src/agent_team_v15/prd_parser.py` (`extract_business_rules`)

| Sub-test | Input | Result |
|----------|-------|--------|
| Minimal entity table | Single entity, no rules section | 0 rules extracted |
| No entities | Description-only PRD | 0 rules extracted |
| Entity + state machine | Invoice with transitions | 0 rules (no explicit rule section) |

**Defense mechanism:** Business rule extraction is additive -- returns empty list when no patterns match.

### Scenario 6: Contract Generator with Missing Data

**File:** `src/agent_team_v15/contract_generator.py` (`generate_contracts` at line 615)

| Sub-test | Input | Result |
|----------|-------|--------|
| Empty ParsedPRD | `ParsedPRD()` | 0 services, valid contracts_md |
| None input | `None` | 0 services, valid contracts_md |
| Entities only | 1 entity, no events | 1 service, valid clients generated |
| Empty fields | Entity with `fields=[]` | Valid bundle, empty client DTOs |
| Missing name key | Entity without `"name"` key | Uses empty string, still generates |

**Defense mechanism:** Uses `getattr(parsed_prd, ...)` with defaults for all fields, and `entity.get("name", "")` for optional keys.

### Scenario 7: Quality Scans on Empty Directory

**File:** `src/agent_team_v15/quality_checks.py`

| Sub-test | Function | Input | Result |
|----------|----------|-------|--------|
| Empty dir | `run_placeholder_scan` | Empty tmpdir | 0 violations |
| Empty dir | `run_handler_completeness_scan` | Empty tmpdir | 0 violations |
| Empty dir, no rules | `run_business_rule_verification` | Empty tmpdir, `[]` | 0 violations |
| Empty dir, None rules | `run_business_rule_verification` | Empty tmpdir, `None` | 0 violations |
| Empty dir, phantom entity | `run_business_rule_verification` | Empty tmpdir, 1 rule | 1 RULE-001 violation |
| Non-existent dir | `run_placeholder_scan` | `C:\nonexistent` | 0 violations |
| Non-existent dir | `run_handler_completeness_scan` | `C:\nonexistent` | 0 violations |

**Defense mechanism:** `_iter_source_files` uses `os.walk` which returns empty iteration for non-existent/empty dirs. `run_business_rule_verification` has `if not business_rules: return []` guard.

### Scenario 8: Runtime Verification Without Docker

**File:** `src/agent_team_v15/runtime_verification.py` (`run_runtime_verification` at line 788)

| Sub-test | Input | Result |
|----------|-------|--------|
| Docker available check | `check_docker_available()` | Returns bool (True/False) |
| No compose file | Empty tmpdir | `RuntimeReport(docker_available=True, compose_file="")` |
| Docker unavailable (simulated) | Monkey-patched check | `RuntimeReport(docker_available=False)`, returns immediately |
| All steps disabled | All `*_enabled=False` | Returns empty report, no crash |

**Defense mechanism:** Three-layer guard: (1) `check_docker_available()` catches `FileNotFoundError` from missing docker binary, (2) `find_compose_file()` returns `None` when no compose file exists, (3) `run_runtime_verification()` returns early with empty report for either failure.

---

## Conclusion

The agent-team-v15 pipeline has robust failure recovery across all tested scenarios. Key patterns:

1. **Type guards** (`_expect()` in state.py) prevent wrong-type fields from corrupting runtime state
2. **Falsy checks** (`if not value`) handle both None and empty string uniformly
3. **Broad exception catches** with fallback returns (never re-raise on corrupted input)
4. **Early returns** for missing prerequisites (Docker, compose files, empty input)
5. **`getattr()` with defaults** for duck-typed inputs (contract generator)
6. **`os.walk` natural behavior** -- returns empty iteration for missing directories

No code changes were needed. All 8 scenarios demonstrate graceful degradation as designed.
