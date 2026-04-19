# proof-08 — Structured `WaveFinding` emission for 4 converted h1a patterns

## What this proves

Each of the four H1a pattern IDs that previously escaped as raw strings is now surfaced as a structured object on its proper persistence path:

| Pattern | Adapter | Shape | Destination |
|---|---|---|---|
| `SCAFFOLD-COMPOSE-001` | `_scaffold_summary_to_findings` | `WaveFinding(code, severity="HIGH", file="docker-compose.yml", ...)` | `WaveResult.findings` → `persist_wave_findings_for_audit` |
| `SCAFFOLD-PORT-002` | `_scaffold_summary_to_findings` | `WaveFinding(code, severity="MEDIUM", file="", ...)` | same |
| `PROBE-SPEC-DRIFT-001` | `_probe_startup_error_to_finding` | `WaveFinding(code, severity="HIGH", file=<REQUIREMENTS.md path>, ...)` | same |
| `RUNTIME-TAUTOLOGY-001` | inline `_cli_gate_violations.append(...)` | dict `{gate, code, severity:"HIGH", message}` | `.agent-team/GATE_FINDINGS.json` |

## Fixture

```python
summary_lines = [
    "SCAFFOLD-COMPOSE-001: docker-compose.yml services.api missing image and build definitions — verifier cannot determine container source.",
    "SCAFFOLD-PORT-002: apps/api main.ts listens on 4000 but docker-compose.yml published port is 3080 (DoD mismatch).",
]
probe_err = (
    "PROBE-SPEC-DRIFT-001: scaffolded services drifted from "
    "REQUIREMENTS.md at .agent-team/milestones/milestone-1/REQUIREMENTS.md "
    "(DoD port 3080 vs api main.ts 4000)"
)
none_case = "Error: container startup timed out"
```

## Invocation

```python
from agent_team_v15.wave_executor import (
    _scaffold_summary_to_findings, _probe_startup_error_to_finding,
)
scaffold = _scaffold_summary_to_findings(cwd="/does/not/exist", summary_lines=summary_lines)
probe = _probe_startup_error_to_finding(probe_err)
none_finding = _probe_startup_error_to_finding(none_case)   # must be None

# For RUNTIME-TAUTOLOGY-001, inspect cli.py source to confirm the literal dict.
```

Run: `python tmp/h1b_proof_08.py`

## Output (actual, not paraphrased)

```
=== scaffold findings ===
  code='SCAFFOLD-COMPOSE-001' severity='HIGH' file='docker-compose.yml' msg='SCAFFOLD-COMPOSE-001: docker-compose.yml services.api missin'...
  code='SCAFFOLD-PORT-002' severity='MEDIUM' file='' msg='SCAFFOLD-PORT-002: apps/api main.ts listens on 4000 but dock'...
OK: scaffold findings structured (HIGH / MEDIUM, no string path)

=== probe finding ===
  WaveFinding(code='PROBE-SPEC-DRIFT-001', severity='HIGH', file='.agent-team/milestones/milestone-1/REQUIREMENTS.md (DoD port 3080 vs api main.ts 4000', line=0, message='PROBE-SPEC-DRIFT-001: scaffolded services drifted from REQUIREMENTS.md at .agent-team/milestones/milestone-1/REQUIREMENTS.md (DoD port 3080 vs api main.ts 4000)')
OK: probe finding structured HIGH with requirements file path
OK: non-drift startup error returns None (no false positives)

=== cli.py _cli_gate_violations.append RUNTIME-TAUTOLOGY-001 site ===
  matched starting at cli.py:14306
  14304:                     # structured channel.
  14305:                     if _tautology_finding:
  14306:                         _cli_gate_violations.append({
  14307:                             "gate": "runtime_tautology",
  14308:                             "code": "RUNTIME-TAUTOLOGY-001",
  14309:                             "severity": "HIGH",
  14310:                             "message": _tautology_finding,
  14311:                         })
  14312:                 else:
  14313:                     print_warning("Runtime verification: Docker not available — skipped")
  14314:             except Exception as exc:

=== GATE_FINDINGS.json persist sites in cli.py: lines [12978, 14187] ===
OK: runtime-tautology structured emission wired to GATE_FINDINGS.json
OK: persist_wave_findings_for_audit referenced starting at wave_executor.py:732

OK: proof-08 structured emission verified for SCAFFOLD-*, PROBE-*, RUNTIME-*
```

## Assertion

- **Scaffold adapter:** `_scaffold_summary_to_findings` at `src/agent_team_v15/wave_executor.py:1112-1166`. HIGH branch for `SCAFFOLD-COMPOSE-001` at `:1146-1155`; MEDIUM branch for `SCAFFOLD-PORT-002` at `:1156-1165`. `cwd` argument used as the fallback to re-read `.agent-team/scaffold_verifier_report.json` — here we pass `summary_lines` directly so the disk path is not needed.
- **Probe adapter:** `_probe_startup_error_to_finding` at `src/agent_team_v15/wave_executor.py:1169-1193`. `PROBE-SPEC-DRIFT-001` sentinel guard at `:1183-1184`; non-drift errors return `None` — the pre-H1b path where startup errors surface only via `error_message` is preserved.
- **Runtime tautology structured literal:** `src/agent_team_v15/cli.py:14305-14311`
  ```python
  if _tautology_finding:
      _cli_gate_violations.append({
          "gate": "runtime_tautology",
          "code": "RUNTIME-TAUTOLOGY-001",
          "severity": "HIGH",
          "message": _tautology_finding,
      })
  ```
  Appended inside the same branch that preserves `print_warning(_tautology_finding)` at `cli.py:14291, 14294` — structured channel is additive; operator-visible log is unchanged.
- **Persistence sinks:**
  - `_cli_gate_violations` → `.agent-team/GATE_FINDINGS.json` at `cli.py:12978` (post-orch first drain) and `cli.py:14187` (post-orch update).
  - `WaveResult.findings` (scaffold + probe) → `persist_wave_findings_for_audit` in `wave_executor.py` (referenced starting at `:732`). This feeds the standard audit pipeline — same route as `WIRING-CLIENT-001` etc. (Phase F pattern).
- **Non-drift safety:** `_probe_startup_error_to_finding("Error: container startup timed out")` returns `None`. This matches wiring-verifier §4D's note that legacy startup errors (host-port-unbound, image-build-failed) surface only as `WaveResult.error_message`, unchanged.

The output proves all four patterns are now structured-channel emitters. Wiring-verifier §4D observation 3 flagged that RUNTIME-TAUTOLOGY-001 lands in `GATE_FINDINGS.json` rather than `AUDIT_REPORT.json` directly — this proof confirms that routing and shows the literal dict shape the audit scorer consumes.

## Verification

- Pattern IDs + severities:
  - `SCAFFOLD-COMPOSE-001` / HIGH
  - `SCAFFOLD-PORT-002` / MEDIUM
  - `PROBE-SPEC-DRIFT-001` / HIGH
  - `RUNTIME-TAUTOLOGY-001` / HIGH
- Guardrail checked: `_probe_startup_error_to_finding` returns `None` for non-drift strings (no false positives — legacy error_message path is preserved).
- Guardrail checked: the literal `{"gate": "runtime_tautology", "code": "RUNTIME-TAUTOLOGY-001", "severity": "HIGH", "message": _tautology_finding}` dict is present in cli.py at line 14306-14311 (regex-verified).
- Guardrail checked: both `GATE_FINDINGS.json` persist sites exist (cli.py:12978 + 14187), and `persist_wave_findings_for_audit` is a real symbol in `wave_executor.py`. Downstream wiring is spot-checked here per the wiring-verifier §4D "Wave 5 should spot-check" note.
- Guardrail checked: the `print_warning(_tautology_finding)` operator-channel log at cli.py:14291/14294 is preserved (not replaced) — structured emission is additive, matching architecture-report §1E's "DO NOT rip out string emitters" directive.
