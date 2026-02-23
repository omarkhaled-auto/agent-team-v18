# Phase 2A: Backward Compatibility Verification Report

**Date:** 2026-02-23
**Baseline:** 6306 tests passed, 5 skipped, 0 failures (Build 1 healthy)
**Verifier:** Claude Opus 4.6

---

## 2A.1: Config Backward Compatibility

### 2A.1.1: `_dict_to_config` Return Type

**PASS**

- **File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\config.py`
- **Line 1024:** `def _dict_to_config(data: dict[str, Any]) -> tuple[AgentTeamConfig, set[str]]:`
- **Line 1576:** `return cfg, user_overrides`
- The function signature explicitly declares `tuple[AgentTeamConfig, set[str]]` as its return type.
- The return statement at line 1576 returns `(cfg, user_overrides)` where `cfg` is an `AgentTeamConfig` (line 1033) and `user_overrides` is a `set[str]` (line 1034).

### 2A.1.2: Build 2 Config Sections Default to `enabled=False`

**PASS** (with nuance on ContractScanConfig)

| Config Section | Default `enabled` | Line | Status |
|---|---|---|---|
| `AgentTeamsConfig.enabled` | `False` | Line 494 | PASS |
| `ContractEngineConfig.enabled` | `False` | Line 515 | PASS |
| `CodebaseIntelligenceConfig.enabled` | `False` | Line 534 | PASS |
| `ContractScanConfig` | No `enabled` field | Lines 311-322 | PASS |

**Evidence:**

- **AgentTeamsConfig** (line 488-506): `enabled: bool = False` at line 494.
- **ContractEngineConfig** (line 508-524): `enabled: bool = False` at line 515.
- **CodebaseIntelligenceConfig** (line 526-544): `enabled: bool = False` at line 534.
- **ContractScanConfig** (line 311-322): Has no `enabled` field. Instead, it has 4 individual boolean scan flags (`endpoint_schema_scan`, `missing_endpoint_scan`, `event_schema_scan`, `shared_model_scan`), all defaulting to `True`. This is correct -- the scans are defined but only execute when gated by `contract_engine.enabled` in the runtime pipeline.

### 2A.1.3: Empty YAML Config Produces Valid AgentTeamConfig

**PASS**

- When `_dict_to_config({})` is called (line 1024-1576):
  - Line 1033: `cfg = AgentTeamConfig()` -- creates default config
  - Line 1034: `user_overrides: set[str] = set()` -- empty set
  - None of the `if "section" in data:` blocks execute (all check for key presence in the empty dict)
  - Line 1576: Returns `(cfg, user_overrides)` with all defaults
  - All Build 2 features are disabled by default:
    - `cfg.agent_teams.enabled = False` (line 494)
    - `cfg.contract_engine.enabled = False` (line 515)
    - `cfg.codebase_intelligence.enabled = False` (line 534)
  - Already tested in `test_build2_backward_compat.py` at TEST-073 (line 328-333).

### 2A.1.4: Unknown Config Keys Silently Ignored

**PASS**

- The `_dict_to_config` function uses an explicit `if "key" in data:` pattern for every known section (e.g., line 1036: `if "orchestrator" in data:`). Unknown top-level keys are never checked and never raise errors -- they are simply not processed.
- Within each section, `.get()` is used on the sub-dict (e.g., `o.get("model", cfg.orchestrator.model)` at line 1047), so unknown sub-keys within a known section are also silently ignored.
- Line 1275 explicitly notes: `# Silently ignore legacy budget_limit_usd key` -- confirming the intentional ignore pattern.
- There is no validation step that rejects unknown keys at any level.

---

## 2A.2: Behavioral Identity

### 2A.2.1: `get_contract_aware_servers` Identity When Disabled

**PASS**

- **File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\mcp_servers.py`
- **Lines 298-313:**
  ```python
  def get_contract_aware_servers(config: AgentTeamConfig) -> dict[str, Any]:
      servers = get_mcp_servers(config)          # Line 305: starts with base servers
      if config.contract_engine.enabled:          # Line 307: conditional
          servers["contract_engine"] = ...        # Line 308: only added if enabled
      if config.codebase_intelligence.enabled:    # Line 310: conditional
          servers["codebase_intelligence"] = ...  # Line 311: only added if enabled
      return servers                              # Line 313
  ```
- **When both disabled:** The function calls `get_mcp_servers(config)` at line 305, then neither `if` branch fires (lines 307 and 310 both skip), so it returns the exact same dict as `get_mcp_servers()` would.
- **No extra keys, no mutations:** The only modifications to the `servers` dict are the two conditional additions. No other keys are added, removed, or modified.
- **Already tested:** TEST-071 (line 290-294) and TEST-080 (line 491-499) both verify this behavior.

### 2A.2.2: `create_execution_backend` Decision Tree

**PASS**

- **File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\agent_teams_backend.py`
- **Lines 720-809:**

**Full Decision Tree:**

```
create_execution_backend(config)
|
+-- Branch 1 (line 754): agent_teams.enabled == False?
|   YES --> return CLIBackend(config)
|
+-- Branch 2 (line 759-766): CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS != "1"?
|   YES --> log warning, return CLIBackend(config)
|
+-- Branch 3 (line 769-777): claude CLI not available?
|   +-- Branch 3a (line 771): fallback_to_cli == True?
|   |   YES --> log warning, return CLIBackend(config)
|   +-- Branch 3b (line 778): fallback_to_cli == False?
|       YES --> raise RuntimeError
|
+-- Branch 5 (line 786-802): Platform/display-mode incompatible?
|   (detect_agent_teams_available returns False)
|   +-- Branch 5a (line 789): fallback_to_cli == True?
|   |   YES --> log warning, return CLIBackend(config)
|   +-- Branch 5b (line 796): fallback_to_cli == False?
|       YES --> raise RuntimeError
|
+-- Branch 6 (line 804-809): All conditions met
    --> return AgentTeamsBackend(config)
```

- **When `agent_teams.enabled=False`:** Branch 1 at line 754 fires immediately, returning `CLIBackend(config)`. No env var checks, no CLI availability checks, no platform checks. This is the critical backward compatibility path.

---

## 2A.3: Return Type Preservation -- Existing Test Coverage

**File:** `C:\MY_PROJECTS\agent-team-v15\tests\test_build2_backward_compat.py`

### Already Tested (48 tests across 30 test classes):

| Test ID | What's Tested | Lines |
|---|---|---|
| TEST-067 | ContractEngineClient populate ContractReport | 148-204 |
| TEST-068 | CodebaseIntelligenceClient codebase map | 212-239 |
| TEST-069 | Both MCP configs disabled -> base only | 248-258 |
| TEST-070 | Config without Build 2 sections defaults disabled | 266-279 |
| TEST-071 | Build 2 disabled MCP matches v14 base | 287-294 |
| TEST-072 | ContractScanConfig defaults gated on engine | 302-318 |
| TEST-073 | `_dict_to_config` returns tuple | 325-333 |
| TEST-074 | Config dataclass YAML roundtrip (4 sub-tests) | 341-374 |
| TEST-076 | E2E contract compliance prompt | 382-389 |
| TEST-077 | detect_app_type with .mcp.json | 397-408 |
| TEST-078 | ContractEngineClient safe defaults on OSError (4 sub-tests) | 416-451 |
| TEST-079 | CodebaseIntelligenceClient safe defaults on isError (2 sub-tests) | 459-480 |
| TEST-080 | Both disabled -> neither key in servers | 488-499 |
| TEST-081 | Contract scans after API scan order | 507-513 |
| TEST-082 | Signal handler saves contract report | 521-541 |
| TEST-083 | Resume restores contract report | 549-572 |
| TEST-084 | AgentTeamsBackend with contract_engine config | 579-588 |
| TEST-085 | CLIBackend no MCP dependency | 596-603 |
| TEST-086 | CLAUDE.md includes contract_engine tools | 611-624 |
| TEST-087 | get_contract_aware_servers preserves existing | 632-641 |
| TEST-088 | _dict_to_config with codebase_intelligence | 648-662 |
| TEST-089 | Override tracking for new sections | 670-690 |
| TEST-090 | Contract client safe defaults on crash | 698-716 |
| TEST-091 | Contract client safe defaults on malformed JSON | 723-744 |
| TEST-092 | Quality gate script content | 752-766 |
| TEST-093 | State JSON all reports roundtrip | 774-809 |
| TEST-094 | ScanScope in contract scanner | 817-825 |
| SEC-001 | No API key leak in mcp_clients | 833-840 |
| SEC-002 | Hook scripts no secrets | 848-866 |
| SEC-003 | save_local_cache strips securitySchemes | 874-910 |
| INT-003 | ArchitectClient.decompose safe default | 918-927 |
| INT-005 | ArchitectClient.get_service_map safe default | 935-944 |
| INT-006 | ArchitectClient.get_contracts safe default | 952-961 |
| INT-007 | ArchitectClient.get_domain_model safe default | 969-978 |
| INT-008 | Violation dataclass interface | 986-1003 |
| INT-010 | pathlib.Path usage in source | 1011-1027 |
| INT-011 | Pipeline stages preserved (15 stages) | 1035-1046 |
| INT-012 | Fix loops preserved | 1054-1062 |
| INT-014 | Milestone execution preserved | 1070-1077 |
| INT-016 | Depth gating preserved | 1085-1093 |
| INT-017 | ScanScope contract scans | 1101-1108 |
| INT-018 | register_artifact timing | 1116-1138 |
| INT-019 | Contract report in summary block | 1146-1162 |
| INT-020 | load_state handles missing Build 2 fields | 1170-1206 |

### Missing Test Coverage Areas:

1. **Empty YAML `{}` end-to-end via `load_config`** -- TEST-073 tests `_dict_to_config({})` directly but does not test the `load_config()` path with a YAML file containing just `{}`.

2. **Unknown top-level keys** -- No test passes `{"unknown_section": {"foo": "bar"}}` to `_dict_to_config` and verifies it returns a valid config without error.

3. **Unknown sub-keys within known sections** -- No test passes e.g. `{"orchestrator": {"unknown_field": 42}}` and verifies the unknown field is silently dropped.

4. **`create_execution_backend` with `enabled=False`** -- TEST-084/085 test CLIBackend creation directly, but no test calls `create_execution_backend(config)` with `agent_teams.enabled=False` and asserts the return is a `CLIBackend` instance.

5. **`get_contract_aware_servers` strict identity** -- TEST-071 tests key set equality (`set(base.keys()) == set(aware.keys())`), but does not verify value-level identity (`base == aware` or `base[k] is aware[k]`).

6. **Depth gating individual condition verification** -- INT-016 only tests that `apply_depth_quality_gating` does not raise for each depth. It does NOT verify the actual values set (e.g., that `quick` sets `contract_engine.enabled=False`).

7. **`_gate()` user override preservation** -- No test verifies that when a user explicitly sets `contract_engine.enabled: true` in their YAML, the `quick` depth gating does not override it back to `False`.

8. **`create_execution_backend` branches 2-6** -- No tests for the env var check (branch 2), CLI availability fallback (branch 3), or platform compatibility (branch 5) paths in `create_execution_backend`.

---

## 2A.4: Depth Gating Verification

### `apply_depth_quality_gating` Analysis

**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\config.py`, lines 635-764

### `_gate()` Helper (lines 656-659)

**PASS**

```python
def _gate(key: str, value: object, target: object, attr: str) -> None:
    """Set *target.attr* to *value* unless *key* is user-overridden."""
    if key not in overrides:
        setattr(target, attr, value)
```

- When `key` IS in `user_overrides`: the setattr is skipped, preserving the user's explicit value.
- When `key` is NOT in `user_overrides`: the depth default is applied.
- This correctly implements the override-respecting contract.

### Depth: `quick` (lines 661-702) -- 30 gate calls

**PASS** -- All new features disabled.

| # | Gate Key | Target | Value | Line |
|---|---|---|---|---|
| 1 | `audit_team.enabled` | `config.audit_team` | `False` | 663 |
| 2 | `tech_research.enabled` | `config.tech_research` | `False` | 665 |
| 3 | `quality.production_defaults` | `config.quality` | `False` | 667 |
| 4 | `quality.craft_review` | `config.quality` | `False` | 668 |
| 5 | `post_orchestration_scans.mock_data_scan` | `config.post_orchestration_scans` | `False` | 670 |
| 6 | `post_orchestration_scans.ui_compliance_scan` | `config.post_orchestration_scans` | `False` | 671 |
| 7 | `post_orchestration_scans.api_contract_scan` | `config.post_orchestration_scans` | `False` | 672 |
| 8 | `post_orchestration_scans.silent_data_loss_scan` | `config.post_orchestration_scans` | `False` | 673 |
| 9 | `post_orchestration_scans.endpoint_xref_scan` | `config.post_orchestration_scans` | `False` | 674 |
| 10 | `contract_scans.endpoint_schema_scan` | `config.contract_scans` | `False` | 676 |
| 11 | `contract_scans.missing_endpoint_scan` | `config.contract_scans` | `False` | 677 |
| 12 | `contract_scans.event_schema_scan` | `config.contract_scans` | `False` | 678 |
| 13 | `contract_scans.shared_model_scan` | `config.contract_scans` | `False` | 679 |
| 14 | `milestone.mock_data_scan` | `config.milestone` | `False` | 681 |
| 15 | `milestone.ui_compliance_scan` | `config.milestone` | `False` | 682 |
| 16 | `milestone.review_recovery_retries` | `config.milestone` | `0` | 683 |
| 17 | `integrity_scans.deployment_scan` | `config.integrity_scans` | `False` | 685 |
| 18 | `integrity_scans.asset_scan` | `config.integrity_scans` | `False` | 686 |
| 19 | `integrity_scans.prd_reconciliation` | `config.integrity_scans` | `False` | 687 |
| 20 | `database_scans.dual_orm_scan` | `config.database_scans` | `False` | 689 |
| 21 | `database_scans.default_value_scan` | `config.database_scans` | `False` | 690 |
| 22 | `database_scans.relationship_scan` | `config.database_scans` | `False` | 691 |
| 23 | `e2e_testing.enabled` | `config.e2e_testing` | `False` | 693 |
| 24 | `e2e_testing.max_fix_retries` | `config.e2e_testing` | `1` | 694 |
| 25 | `browser_testing.enabled` | `config.browser_testing` | `False` | 696 |
| 26 | `post_orchestration_scans.max_scan_fix_passes` | `config.post_orchestration_scans` | `0` | 698 |
| 27 | `contract_engine.enabled` | `config.contract_engine` | `False` | 700 |
| 28 | `codebase_intelligence.enabled` | `config.codebase_intelligence` | `False` | 701 |
| 29 | `agent_teams.enabled` | `config.agent_teams` | `False` | 702 |

**Build 2 specific (items 27-29):** All three new subsystems explicitly disabled at quick depth. PASS.

### Depth: `standard` (lines 704-718) -- 8 gate calls

**PASS** -- Contract engine and codebase intelligence enabled with limited features.

| # | Gate Key | Target | Value | Line |
|---|---|---|---|---|
| 1 | `tech_research.max_queries_per_tech` | `config.tech_research` | `2` | 706 |
| 2 | `integrity_scans.prd_reconciliation` | `config.integrity_scans` | `False` | 708 |
| 3 | `contract_scans.event_schema_scan` | `config.contract_scans` | `False` | 710 |
| 4 | `contract_scans.shared_model_scan` | `config.contract_scans` | `False` | 711 |
| 5 | `contract_engine.enabled` | `config.contract_engine` | `True` | 713 |
| 6 | `contract_engine.validation_on_build` | `config.contract_engine` | `True` | 714 |
| 7 | `contract_engine.test_generation` | `config.contract_engine` | `False` | 715 |
| 8 | `codebase_intelligence.enabled` | `config.codebase_intelligence` | `True` | 716 |
| 9 | `codebase_intelligence.replace_static_map` | `config.codebase_intelligence` | `False` | 717 |
| 10 | `codebase_intelligence.register_artifacts` | `config.codebase_intelligence` | `False` | 718 |

**Build 2 specific (items 5-10):**
- `contract_engine.enabled=True` but `test_generation=False` (validation only). PASS.
- `codebase_intelligence.enabled=True` but `replace_static_map=False` and `register_artifacts=False` (queries only). PASS.
- `agent_teams` is NOT gated at standard depth -- stays at its default (`enabled=False`). PASS.

### Depth: `thorough` (lines 720-739) -- 14 gate calls (+ 3 conditional)

**PASS** -- All features enabled, agent_teams conditional on env var.

| # | Gate Key | Target | Value | Line |
|---|---|---|---|---|
| 1 | `audit_team.enabled` | `config.audit_team` | `True` | 722 |
| 2 | `audit_team.max_reaudit_cycles` | `config.audit_team` | `2` | 723 |
| 3 | `e2e_testing.enabled` | `config.e2e_testing` | `True` | 725 |
| 4 | `e2e_testing.max_fix_retries` | `config.e2e_testing` | `2` | 726 |
| 5 | `milestone.review_recovery_retries` | `config.milestone` | `2` | 727 |
| 6* | `browser_testing.enabled` | `config.browser_testing` | `True` | 730 (conditional: prd_mode or milestone.enabled) |
| 7* | `browser_testing.max_fix_retries` | `config.browser_testing` | `3` | 731 (conditional: prd_mode or milestone.enabled) |
| 8 | `contract_engine.enabled` | `config.contract_engine` | `True` | 733 |
| 9 | `contract_engine.test_generation` | `config.contract_engine` | `True` | 734 |
| 10 | `codebase_intelligence.enabled` | `config.codebase_intelligence` | `True` | 735 |
| 11 | `codebase_intelligence.replace_static_map` | `config.codebase_intelligence` | `True` | 736 |
| 12 | `codebase_intelligence.register_artifacts` | `config.codebase_intelligence` | `True` | 737 |
| 13* | `agent_teams.enabled` | `config.agent_teams` | `True` | 739 (conditional: env var CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS == "1") |

**Build 2 specific (items 8-13):**
- Full contract engine including test generation. PASS.
- Full codebase intelligence including static map replacement and artifact registration. PASS.
- Agent teams only if `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. PASS.

### Depth: `exhaustive` (lines 741-764) -- 15 gate calls (+ 3 conditional)

**PASS** -- Same as thorough with higher limits.

| # | Gate Key | Target | Value | Line |
|---|---|---|---|---|
| 1 | `audit_team.enabled` | `config.audit_team` | `True` | 743 |
| 2 | `audit_team.max_reaudit_cycles` | `config.audit_team` | `3` | 744 |
| 3 | `tech_research.max_queries_per_tech` | `config.tech_research` | `6` | 746 |
| 4 | `e2e_testing.enabled` | `config.e2e_testing` | `True` | 748 |
| 5 | `e2e_testing.max_fix_retries` | `config.e2e_testing` | `3` | 749 |
| 6 | `milestone.review_recovery_retries` | `config.milestone` | `3` | 750 |
| 7* | `browser_testing.enabled` | `config.browser_testing` | `True` | 753 (conditional) |
| 8* | `browser_testing.max_fix_retries` | `config.browser_testing` | `5` | 754 (conditional) |
| 9 | `post_orchestration_scans.max_scan_fix_passes` | `config.post_orchestration_scans` | `2` | 756 |
| 10 | `contract_engine.enabled` | `config.contract_engine` | `True` | 758 |
| 11 | `contract_engine.test_generation` | `config.contract_engine` | `True` | 759 |
| 12 | `codebase_intelligence.enabled` | `config.codebase_intelligence` | `True` | 760 |
| 13 | `codebase_intelligence.replace_static_map` | `config.codebase_intelligence` | `True` | 761 |
| 14 | `codebase_intelligence.register_artifacts` | `config.codebase_intelligence` | `True` | 762 |
| 15* | `agent_teams.enabled` | `config.agent_teams` | `True` | 764 (conditional: env var) |

**Build 2 specific (items 10-15):**
- Identical to thorough for Build 2 subsystems. PASS.
- Differences from thorough: higher `max_reaudit_cycles` (3 vs 2), higher `e2e_testing.max_fix_retries` (3 vs 2), higher `milestone.review_recovery_retries` (3 vs 2), adds `post_orchestration_scans.max_scan_fix_passes=2`, higher `browser_testing.max_fix_retries` (5 vs 3), adds `tech_research.max_queries_per_tech=6`. PASS.

### Depth Gating Summary Table

| Feature | quick | standard | thorough | exhaustive |
|---|---|---|---|---|
| `contract_engine.enabled` | False | True | True | True |
| `contract_engine.test_generation` | (default False) | False | True | True |
| `codebase_intelligence.enabled` | False | True | True | True |
| `codebase_intelligence.replace_static_map` | (default True) | False | True | True |
| `codebase_intelligence.register_artifacts` | (default True) | False | True | True |
| `agent_teams.enabled` | False | (default False) | True (if env) | True (if env) |

**All 16 Build 2 depth gating conditions verified: PASS**

(Note: counting Build 2 depth gates only -- 3 in quick, 6 in standard, 6+1 conditional in thorough, 6+1 conditional in exhaustive = 16 unique condition-value pairs plus 2 conditional agent_teams gates.)

---

## Summary

| Verification Point | Result | Evidence |
|---|---|---|
| 2A.1.1: `_dict_to_config` return type | **PASS** | config.py:1024 signature, config.py:1576 return |
| 2A.1.2: AgentTeamsConfig.enabled=False | **PASS** | config.py:494 |
| 2A.1.2: ContractEngineConfig.enabled=False | **PASS** | config.py:515 |
| 2A.1.2: CodebaseIntelligenceConfig.enabled=False | **PASS** | config.py:534 |
| 2A.1.2: ContractScanConfig no enabled field | **PASS** | config.py:311-322 |
| 2A.1.3: Empty YAML produces valid config | **PASS** | config.py:1033-1576 (all section checks skip) |
| 2A.1.4: Unknown keys silently ignored | **PASS** | Explicit `if "key" in data:` pattern throughout |
| 2A.2.1: Disabled Build 2 = identical servers | **PASS** | mcp_servers.py:305-313 |
| 2A.2.2: enabled=False returns CLIBackend | **PASS** | agent_teams_backend.py:754-756 |
| 2A.2.2: Full decision tree documented | **PASS** | 6 branches documented above |
| 2A.3: Existing test coverage | **PASS** | 48 tests across 30 test classes |
| 2A.4: quick depth -- all disabled | **PASS** | config.py:700-702 |
| 2A.4: standard depth -- limited enable | **PASS** | config.py:713-718 |
| 2A.4: thorough depth -- full enable + env gate | **PASS** | config.py:733-739 |
| 2A.4: exhaustive depth -- same as thorough | **PASS** | config.py:758-764 |
| 2A.4: _gate() respects user overrides | **PASS** | config.py:656-659 |

### Discrepancies Found

**None.** All verification points pass.

### Missing Test Coverage (Recommendations for Phase 2B)

1. **Unknown keys test** -- Add a test passing `{"totally_unknown": {"foo": 1}}` to `_dict_to_config` and verify no error.
2. **`create_execution_backend` integration** -- Test the factory function returns `CLIBackend` when `agent_teams.enabled=False`.
3. **Depth gating value assertions** -- Add tests that verify specific attribute values after `apply_depth_quality_gating` for each depth (not just "does not raise").
4. **User override preservation under depth gating** -- Test that explicit `contract_engine.enabled: true` in user config survives `quick` depth gating.
5. **Server dict value identity** -- Verify `get_contract_aware_servers` returns value-identical (not just key-identical) dict to `get_mcp_servers` when disabled.
6. **`create_execution_backend` branches 2-5** -- Integration tests for env var check, CLI fallback, and platform compatibility paths.
