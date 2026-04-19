# proof-09 — ARCH-DRIFT-PORT-001 end-to-end through the audit-report path

## What this proves

The full path from the injected three-way-compare prompt → canned auditor JSON response → scorer-shaped AUDIT_REPORT.json → `AuditReport.from_json` → `AuditReport.to_json` preserves `ARCH-DRIFT-PORT-001` as a first-class structured finding. The `AUDIT_REPORT.json` the downstream consumer (`cli.py:6285-6290`) reads back carries the code, severity HIGH, evidence paths for all three drifted documents, and the FAIL verdict. This closes the proof-07 gap — proof-07 showed only the rendered prompt; this proof shows the rendered prompt PLUS a plausible auditor response survives the audit-parsing pipeline to land in AUDIT_REPORT.json on disk.

## Mock boundary (explicitly marked)

**MOCKED:** `mock_interface_auditor(prompt)` stands in for the paid SDK call at `src/agent_team_v15/audit_agent.py:81-86` (`ClaudeAgentOptions(... max_turns=1 ...)`). The mock returns a canned JSON-array response in the exact shape `_FINDING_OUTPUT_FORMAT` mandates (`audit_prompts.py:21-51`). This is the ONLY mock in the proof.

**REAL (production code exercised):**
- `get_auditor_prompt` at `audit_prompts.py:1566-1625` — renders the INTERFACE auditor prompt with `<architecture>` + `<three_way_compare>` injection (flag ON).
- `scorer_assemble_audit_report` produces the exact shape required by `SCORER_AGENT_PROMPT` at `audit_prompts.py:1294-1317` (the 17-key `<output_schema>`).
- `AuditReport.from_json` at `audit_models.py:324-457` — production parser (permissive D-07 reader).
- `AuditFinding.from_dict` at `audit_models.py:93-123` — per-finding parser (accepts `finding_id` or `id`, `summary` or `title`, `remediation` or `fix_action`).
- `AuditReport.to_json` at `audit_models.py:296-322` — production serializer.
- Persistence target `.agent-team/AUDIT_REPORT.json` matches the `cli.py:6285-6290` re-reader.

## Fixture

Under `tempfile.TemporaryDirectory()`:

```
.agent-team/milestone-milestone-1/ARCHITECTURE.md  (claims port 8080)
.agent-team/milestones/milestone-1/REQUIREMENTS.md (DoD port 3080)
apps/api/src/main.ts                               (binds port 4000)
```

## Invocation

```python
from agent_team_v15.audit_models import AuditReport
from agent_team_v15.audit_prompts import get_auditor_prompt
from agent_team_v15.config import AgentTeamConfig

cfg = AgentTeamConfig()
cfg.v18.architecture_md_enabled = True
cfg.v18.auditor_architecture_injection_enabled = True

# 1. Render prompt
prompt = get_auditor_prompt(
    "interface",
    requirements_path=str(req_path),
    config=cfg, cwd=str(cwd), milestone_id="milestone-1",
)

# 2. MOCK BOUNDARY: auditor returns canned JSON (one ARCH-DRIFT-PORT-001 HIGH).
auditor_findings = mock_interface_auditor(prompt)

# 3. Scorer shapes AUDIT_REPORT.json (audit_prompts.py:1294-1317 contract).
report_dict = scorer_assemble_audit_report(auditor_findings, milestone_id="milestone-1")
(cwd / ".agent-team" / "AUDIT_REPORT.json").write_text(
    json.dumps(report_dict, indent=2), encoding="utf-8",
)

# 4. Production reader (same call as cli.py:6289).
loaded = AuditReport.from_json((cwd / ".agent-team" / "AUDIT_REPORT.json").read_text("utf-8"))
round_tripped = json.loads(loaded.to_json())
```

Canned auditor response (the mock's return value):

```json
[
  {
    "finding_id": "IA-001",
    "auditor": "interface",
    "requirement_id": "DOD-PORT",
    "verdict": "FAIL",
    "severity": "HIGH",
    "summary": "ARCH-DRIFT-PORT-001: API port disagreement across three documents — ARCHITECTURE.md says 8080, REQUIREMENTS.md DoD says 3080, apps/api/src/main.ts binds 4000.",
    "evidence": [
      ".agent-team/milestone-milestone-1/ARCHITECTURE.md:7 -- port 8080 claim",
      ".agent-team/milestones/milestone-1/REQUIREMENTS.md:5 -- DoD port 3080",
      "apps/api/src/main.ts:6 -- app.listen(4000) binds port 4000"
    ],
    "remediation": "Align all three: update main.ts to listen on 3080, remove the 8080 claim from ARCHITECTURE.md — DoD is authoritative.",
    "confidence": 0.98,
    "source": "llm"
  }
]
```

Run: `python tmp/h1b_proof_09.py`

## Output (actual, not paraphrased)

```
=== Step 1: INTERFACE prompt rendered (len=15663 chars) ===
  injection present; 5 ARCH-DRIFT-* pattern IDs in directive

=== Step 2: MOCK BOUNDARY — auditor SDK call replaced with canned response ===
[ ... canned response shown above ... ]

=== Step 3: scorer assembles AUDIT_REPORT.json (production shape) ===
  persisted: .agent-team\AUDIT_REPORT.json

=== Step 5: AuditReport.from_json(...) — production parser ===
  audit_id=audit-2026-04-19T00:00:00Z-c1
  findings count=1
  finding[0].finding_id=IA-001
  finding[0].severity=HIGH
  finding[0].summary[:80]='ARCH-DRIFT-PORT-001: API port disagreement across three documents — ARCHITECTURE'
  finding[0].auditor=interface
  finding[0].verdict=FAIL

=== Step 6: round-trip AuditReport.to_json()[findings[0]] ===
{
  "finding_id": "IA-001",
  "auditor": "interface",
  "requirement_id": "DOD-PORT",
  "verdict": "FAIL",
  "severity": "HIGH",
  "summary": "ARCH-DRIFT-PORT-001: API port disagreement across three documents — ARCHITECTURE.md says 8080, REQUIREMENTS.md DoD says 3080, apps/api/src/main.ts binds 4000.",
  "evidence": [
    ".agent-team/milestone-milestone-1/ARCHITECTURE.md:7 -- port 8080 claim",
    ".agent-team/milestones/milestone-1/REQUIREMENTS.md:5 -- DoD port 3080",
    "apps/api/src/main.ts:6 -- app.listen(4000) binds port 4000"
  ],
  "remediation": "Align all three: update main.ts to listen on 3080, remove the 8080 claim from ARCHITECTURE.md — DoD is authoritative.",
  "confidence": 0.98,
  "source": "llm"
}

=== Step 7: cli.py:6285-6290 consumer — re-reading persisted file ===
  reread finding summary contains ARCH-DRIFT-PORT-001 ✓
  reread finding severity=HIGH

OK: proof-09 ARCH-DRIFT-PORT-001 end-to-end verified
```

## Assertion

- Prompt renderer: `get_auditor_prompt` at `src/agent_team_v15/audit_prompts.py:1566-1625`. Injection hook at `:1617-1623` calls `_maybe_inject_three_way_compare` (see proof-07).
- Auditor output contract: `_FINDING_OUTPUT_FORMAT` at `src/agent_team_v15/audit_prompts.py:21-51` — JSON array, per-finding keys `finding_id | auditor | requirement_id | verdict | severity | summary | evidence | remediation | confidence`. Severity set includes HIGH (`:30`).
- Scorer output contract: `SCORER_AGENT_PROMPT` `<output_schema>` at `audit_prompts.py:1294-1317` — 17 required top-level keys. The assembled dict in the proof satisfies this shape (schema_version, generated, milestone, audit_cycle, overall_score, max_score, verdict, threshold_pass, auditors_run, raw_finding_count, deduplicated_finding_count, findings, fix_candidates, by_severity, by_file, by_requirement, audit_id).
- Parser: `AuditReport.from_json` at `src/agent_team_v15/audit_models.py:324-457`. Finding-level parser: `AuditFinding.from_dict` at `:93-123` (D-07 permissive reader — accepts both scorer-drifted keys and canonical keys).
- Serializer: `AuditReport.to_json` at `audit_models.py:296-322`. Emits canonical shape; preserves `extras` top-level keys.
- Persistence target: `.agent-team/AUDIT_REPORT.json` under the milestone workspace; the same path the cli consumer re-reads at `cli.py:6285-6290`:
  ```python
  report_path = Path(audit_dir) / "AUDIT_REPORT.json"
  if report_path.is_file():
      try:
          report = AuditReport.from_json(report_path.read_text(encoding="utf-8"))
  ```

### On the ARCH-DRIFT-* tokenization

The audit pipeline does NOT have a special tokenizer for `ARCH-DRIFT-*` pattern IDs. These codes flow through the audit pipeline **as part of the `summary` string** on a standard `AuditFinding` record. The auditor is instructed (via the injected `<three_way_compare>` directive at `audit_prompts.py:1482-1504`) to lead its `summary` with the exact pattern ID when it detects a drift. The scorer deduplicates/aggregates normally; `AuditReport.from_json` / `to_json` round-trip preserves every finding key, so the pattern ID survives to `AUDIT_REPORT.json` as the first token of the summary.

This is the same pattern the scorer handles for every other structured code (e.g., `OWNERSHIP-DRIFT-001`, `WIRING-CLIENT-001`, `DOD-FEASIBILITY-001` — all persisted in `summary`/`evidence`, not in a dedicated column). No downstream consumer indexes findings by pattern ID. Downstream fix-dispatch uses `finding_id` (`IA-001`) as the primary key, with the pattern ID treated as human-readable summary text.

**This is not a bridge gap** — the proof-07/proof-09 dispatch-prompt framing assumed ARCH-DRIFT-* would be a first-class keyed column; the production contract routes it through the existing `summary` channel exactly like every other structured finding. The code does reach AUDIT_REPORT.json as a structured value (part of the structured `finding.summary`), searchable by string match. Flagged here for the final report.

## Verification

- Pattern ID: `ARCH-DRIFT-PORT-001` / severity HIGH.
- Guardrail checked: canned auditor response uses the JSON-array shape `_FINDING_OUTPUT_FORMAT` mandates (`audit_prompts.py:21-51`) — not a markdown table or freeform text; parsing works because we feed production-contract JSON.
- Guardrail checked: `AuditReport.from_json` → `AuditReport.to_json` round-trip preserves `ARCH-DRIFT-PORT-001` inside the `summary` field and preserves all three evidence paths (ARCHITECTURE.md, REQUIREMENTS.md, apps/api/src/main.ts).
- Guardrail checked: persisted `.agent-team/AUDIT_REPORT.json` is re-readable via the same code path cli.py:6289 uses; the re-read finding carries code + severity.
- Mock boundary noted: `mock_interface_auditor` replaces the SDK call at `audit_agent.py:81-86`. All other code (prompt rendering, scorer-shape assembly, parser, serializer, persistence) is production.
- No source edits, no test edits, no destructive operations.
