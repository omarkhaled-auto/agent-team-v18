"""Proof 02: SCAFFOLD-COMPOSE-001 emitted end-to-end via
``_maybe_run_scaffold_verifier`` (the production entry point wave_executor
calls at line 4251) and persisted to ``.agent-team/scaffold_verifier_report.json``.

Fixture: postgres-only compose under fixtures/proof-02/ — no services.api.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

THIS = Path(__file__).resolve()
FIXTURE = THIS.parent.parent / "fixtures" / "proof-02"


def build_fixture() -> Path:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    # Minimal api-less compose
    (FIXTURE / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:15\n",
        encoding="utf-8",
    )
    # Stub .agent-team so the workspace looks real
    (FIXTURE / ".agent-team").mkdir()
    return FIXTURE


def run_via_production_entry() -> None:
    # Production entry point: wave_executor._maybe_run_scaffold_verifier.
    # It reads the real ownership contract, calls run_scaffold_verifier,
    # and persists the JSON report the cascade-consolidator reads.
    from agent_team_v15 import wave_executor

    class _CfgNS(SimpleNamespace):
        pass

    cfg = _CfgNS()
    cfg.v18 = SimpleNamespace(
        scaffold_verifier_enabled=True,
        scaffold_verifier_scope_aware=False,
    )

    workspace = build_fixture()
    err = wave_executor._maybe_run_scaffold_verifier(
        cwd=str(workspace),
        milestone_scope=None,
        scope_aware=False,
        milestone_id="milestone-1",
    )
    print(f"return value: {err!r}")
    report_path = workspace / ".agent-team" / "scaffold_verifier_report.json"
    print(f"report exists: {report_path.is_file()}")
    if report_path.is_file():
        data = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"verdict: {data['verdict']}")
        print("summary_lines:")
        for line in data["summary_lines"]:
            print(f"  {line}")
        compose_hits = [ln for ln in data["summary_lines"] if "SCAFFOLD-COMPOSE-001" in ln]
        print(f"SCAFFOLD-COMPOSE-001 occurrences: {len(compose_hits)}")
        print("malformed entries:")
        for pair in data["malformed"]:
            print(f"  {pair}")


if __name__ == "__main__":
    run_via_production_entry()
