"""Phase H1b — structured emission for h1a pattern codes.

Covers the three adapters added by Wave 2B:

* ``wave_executor._scaffold_summary_to_findings`` — parses
  ``.agent-team/scaffold_verifier_report.json`` for ``SCAFFOLD-COMPOSE-001``
  (HIGH) and ``SCAFFOLD-PORT-002`` (MEDIUM).
* ``wave_executor._probe_startup_error_to_finding`` — converts a
  ``DockerContext.startup_error`` sentinel into a structured
  ``PROBE-SPEC-DRIFT-001`` WaveFinding (HIGH).
* ``cli._cli_gate_violations.append({...})`` at the runtime-verifier
  branch — structured ``RUNTIME-TAUTOLOGY-001`` (HIGH).

Per the plan, the string-emission paths (``summary.append`` / ``print_warning``)
remain — these tests verify the structured channel ADDED alongside, not
that the strings were removed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.wave_executor import (
    WaveFinding,
    _probe_startup_error_to_finding,
    _scaffold_summary_to_findings,
)


# ---------------------------------------------------------------------------
# SCAFFOLD-COMPOSE-001 + SCAFFOLD-PORT-002 adapter
# ---------------------------------------------------------------------------


def test_scaffold_summary_to_findings_emits_compose_high_severity(
    tmp_path: Path,
) -> None:
    findings = _scaffold_summary_to_findings(
        str(tmp_path),
        summary_lines=["SCAFFOLD-COMPOSE-001 topology mismatch"],
    )
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, WaveFinding)
    assert f.code == "SCAFFOLD-COMPOSE-001"
    assert f.severity == "HIGH"
    assert "topology mismatch" in f.message


def test_scaffold_summary_to_findings_emits_port_medium_severity(
    tmp_path: Path,
) -> None:
    findings = _scaffold_summary_to_findings(
        str(tmp_path),
        summary_lines=["SCAFFOLD-PORT-002 PORT_INCONSISTENCY 3080 vs 8080"],
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.code == "SCAFFOLD-PORT-002"
    assert f.severity == "MEDIUM"


def test_scaffold_summary_ignores_unrelated_lines(tmp_path: Path) -> None:
    findings = _scaffold_summary_to_findings(
        str(tmp_path),
        summary_lines=[
            "info: nothing drifted",
            "SCAFFOLD-COMPOSE-001 drift",
            "warn: minor issue",
            "SCAFFOLD-PORT-002 ports drifted",
        ],
    )
    codes = {f.code for f in findings}
    assert codes == {"SCAFFOLD-COMPOSE-001", "SCAFFOLD-PORT-002"}


def test_scaffold_summary_reads_persisted_report_when_not_passed(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / ".agent-team" / "scaffold_verifier_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"summary_lines": ["SCAFFOLD-COMPOSE-001 drifted"]}),
        encoding="utf-8",
    )
    findings = _scaffold_summary_to_findings(str(tmp_path))
    assert len(findings) == 1
    assert findings[0].code == "SCAFFOLD-COMPOSE-001"


def test_scaffold_summary_returns_empty_when_report_absent(tmp_path: Path) -> None:
    findings = _scaffold_summary_to_findings(str(tmp_path))
    assert findings == []


# ---------------------------------------------------------------------------
# PROBE-SPEC-DRIFT-001 adapter
# ---------------------------------------------------------------------------


def test_probe_startup_error_converts_probe_spec_drift() -> None:
    err = (
        "PROBE-SPEC-DRIFT-001: code-port 8080 does not match REQUIREMENTS.md "
        "at apps/api/REQUIREMENTS.md (DoD port 3080)"
    )
    finding = _probe_startup_error_to_finding(err)
    assert finding is not None
    assert finding.code == "PROBE-SPEC-DRIFT-001"
    assert finding.severity == "HIGH"
    assert "apps/api/REQUIREMENTS.md" in finding.file
    assert "PROBE-SPEC-DRIFT-001" in finding.message


def test_probe_startup_error_ignores_non_drift_messages() -> None:
    assert _probe_startup_error_to_finding("image build failed") is None
    assert _probe_startup_error_to_finding("host-port-unbound: 5432") is None
    assert _probe_startup_error_to_finding("") is None
    assert _probe_startup_error_to_finding(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RUNTIME-TAUTOLOGY-001 structured emission — source-inspection verification
# ---------------------------------------------------------------------------


def test_runtime_tautology_structured_append_is_gated_on_finding() -> None:
    """Assert the ``_cli_gate_violations.append({...})`` at cli.py ~14178
    lives inside the ``if _tautology_finding:`` branch (no spurious
    emission when the guard is silent).

    Uses AST inspection instead of exercising the full runtime path so
    the test runs in <1s without Docker.
    """
    import ast

    from agent_team_v15 import cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Look for `if _tautology_finding:` branches.
        test = node.test
        if (
            isinstance(test, ast.Name)
            and test.id == "_tautology_finding"
        ):
            # Look inside the body for the structured append call.
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Call):
                    func = stmt.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "append"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "_cli_gate_violations"
                    ):
                        # Verify the literal dict carries the expected
                        # gate/code/severity keys.
                        arg = stmt.args[0] if stmt.args else None
                        if isinstance(arg, ast.Dict):
                            keys = [
                                k.value for k in arg.keys if isinstance(k, ast.Constant)
                            ]
                            vals = [
                                v.value for v in arg.values if isinstance(v, ast.Constant)
                            ]
                            if (
                                "gate" in keys
                                and "code" in keys
                                and "severity" in keys
                                and "RUNTIME-TAUTOLOGY-001" in vals
                                and "HIGH" in vals
                                and "runtime_tautology" in vals
                            ):
                                found = True
                                break
            if found:
                break
    assert found, (
        "Could not locate a `_cli_gate_violations.append({...})` with "
        "gate=runtime_tautology, code=RUNTIME-TAUTOLOGY-001, severity=HIGH "
        "inside an `if _tautology_finding:` branch at cli.py."
    )


def test_runtime_tautology_print_warning_log_line_preserved() -> None:
    """The structured emission must NOT remove the ``print_warning``
    log path — strings remain the user-visible channel."""
    import re

    from agent_team_v15 import cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    # Grep for `print_warning(_tautology_finding)` — h1a's existing log
    # line. Structural test: this line must still exist.
    assert re.search(r"print_warning\(\s*_tautology_finding\s*\)", src), (
        "print_warning(_tautology_finding) log line removed; structured "
        "emission must add a channel, not replace the string one."
    )
