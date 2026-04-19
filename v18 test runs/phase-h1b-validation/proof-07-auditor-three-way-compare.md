# proof-07 — Auditor three-way-compare injection (INTERFACE + TECHNICAL only)

## What this proves

`get_auditor_prompt` injects the `<architecture>…</architecture>` block AND the `<three_way_compare>` directive with all five `ARCH-DRIFT-*` pattern IDs when:
1. `v18.auditor_architecture_injection_enabled=True` AND
2. `auditor_name ∈ {"interface", "technical"}` AND
3. the per-milestone ARCHITECTURE.md exists on disk.

Flag-off and non-targeted auditors (`requirements`, etc.) get the base prompt byte-identical to the pre-H1b output. This is the Wave 2B auditor-side enforcement that complements the Wave 2A schema gate.

## Fixture

`tmp_path/.agent-team/milestone-milestone-1/ARCHITECTURE.md` containing the port drift shape:

```markdown
## What Wave A produced
- apps/api binds to port 8080 in main.ts.
```

Configs:

```python
cfg_on  = AgentTeamConfig()
cfg_on.v18.architecture_md_enabled = True
cfg_on.v18.auditor_architecture_injection_enabled = True

cfg_off = AgentTeamConfig()
cfg_off.v18.architecture_md_enabled = True
cfg_off.v18.auditor_architecture_injection_enabled = False
```

## Invocation

```python
from agent_team_v15.audit_prompts import AUDIT_PROMPTS, get_auditor_prompt

# (a) interface, flag ON
prompt_on = get_auditor_prompt(
    "interface",
    requirements_path=".agent-team/milestones/milestone-1/REQUIREMENTS.md",
    config=cfg_on, cwd=str(cwd), milestone_id="milestone-1",
)

# (b) interface, flag OFF
prompt_off = get_auditor_prompt(
    "interface",
    requirements_path=".agent-team/milestones/milestone-1/REQUIREMENTS.md",
    config=cfg_off, cwd=str(cwd), milestone_id="milestone-1",
)

# (c) requirements auditor, flag ON — should NOT get injection
prompt_req = get_auditor_prompt(
    "requirements",
    requirements_path=".agent-team/milestones/milestone-1/REQUIREMENTS.md",
    config=cfg_on, cwd=str(cwd), milestone_id="milestone-1",
)

# (d) technical auditor, flag ON — also in subset
prompt_tech = get_auditor_prompt(
    "technical",
    requirements_path=".agent-team/milestones/milestone-1/REQUIREMENTS.md",
    config=cfg_on, cwd=str(cwd), milestone_id="milestone-1",
)
```

Run: `python tmp/h1b_proof_07.py`

## Output (actual, not paraphrased)

```
=== interface flag=ON — head ===
  <architecture>
  # milestone-1

  ## Scope recap
  Users MVP.

  ## What Wave A produced
  - apps/api binds to port 8080 in main.ts.

  ## Seams Wave B must populate
  - UsersService.listUsers

  ## Seams Wave D must populate
  - Users list page.

  ## Seams Wave T must populate
  - users.controller.spec.ts

  ## Seams Wave E must populate
  - e2e users smoke

  ## Open questions
  - none
  </architecture>

... (total len 15604 chars)
OK: interface flag=ON contains all 5 ARCH-DRIFT-* pattern IDs
OK: interface flag=OFF is byte-identical to base (len 13748)
OK: requirements auditor flag=ON is unchanged (targeted subset holds)
OK: technical auditor flag=ON also gets injection
```

Delta between flag-on and flag-off interface prompts: 15604 − 13748 = 1856 bytes, accounting for the `<architecture>` body plus the 5-line `<three_way_compare>` directive.

## Assertion

- Renderer: `get_auditor_prompt` at `src/agent_team_v15/audit_prompts.py:1566-1625`.
- Injection call: `audit_prompts.py:1617-1623` — `prompt = _maybe_inject_three_way_compare(prompt, auditor_name, config=config, cwd=cwd, milestone_id=milestone_id)`.
- Injection helper: `_maybe_inject_three_way_compare` at `audit_prompts.py:1535-1563`. Targeted subset gate: `if auditor_name not in _THREE_WAY_COMPARE_AUDITORS: return prompt` at `:1551`. Flag gate: `if not bool(getattr(v18, "auditor_architecture_injection_enabled", False)): return prompt` at `:1558`.
- Subset constant: `_THREE_WAY_COMPARE_AUDITORS: frozenset[str] = frozenset({"interface", "technical"})` at `audit_prompts.py:1507` (lowercase to match `AUDIT_PROMPTS` dict keys — observation 2 in wiring-verifier §4B).
- Directive string: `_THREE_WAY_COMPARE_DIRECTIVE` at `audit_prompts.py:1482-1504`, carrying all 5 pattern IDs (`ARCH-DRIFT-PORT-001`, `ARCH-DRIFT-ENTITY-001`, `ARCH-DRIFT-ENDPOINT-001`, `ARCH-DRIFT-CREDS-001`, `ARCH-DRIFT-DEPS-001`).
- Loader: `_maybe_load_architecture_handoff_block` at `audit_prompts.py:1510-1532` delegates to `agents._load_per_milestone_architecture_block` at `agents.py:8051-8083`. Returns `""` on any failure (crash-isolated — `audit_prompts.py:1520-1532`).
- Scoped wrapper: `get_scoped_auditor_prompt` at `audit_prompts.py:1662-1700+` routes the same `cwd`/`milestone_id`/`config` through `get_auditor_prompt`, so C-01 scope + three-way compare compose cleanly.
- Byte-identical flag-off path: `prompt_off == AUDIT_PROMPTS["interface"].replace("{requirements_path}", "…/REQUIREMENTS.md")` — asserted in proof.

The output proves:
1. Flag-on + targeted auditor + arch-file-present → `<architecture>` block + `<three_way_compare>` directive prepended.
2. Flag-off → byte-identical base prompt (no injection artifacts).
3. Non-targeted auditor (`requirements`) → no injection even with flag on (subset gate holds).
4. Both `interface` and `technical` receive injection (two-auditor subset honored).

## Verification

- Pattern IDs (in directive): `ARCH-DRIFT-PORT-001`, `ARCH-DRIFT-ENTITY-001`, `ARCH-DRIFT-ENDPOINT-001`, `ARCH-DRIFT-CREDS-001`, `ARCH-DRIFT-DEPS-001` — all HIGH (per directive text at `audit_prompts.py:1488`).
- Guardrail checked: `AUDIT_PROMPTS["interface"]` static constant unchanged (flag-off equality confirms; matches wiring-verifier §4I "byte-identical vs baseline" test).
- Guardrail checked: targeted subset is lowercase (matches dict keys) — would be a silent misfire if uppercase.
- Guardrail checked: `<architecture>` contains the port-8080 drift literal from the fixture, so the downstream auditor has the comparator input it needs for the three-way compare.
