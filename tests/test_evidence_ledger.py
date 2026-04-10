from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.audit_agent import run_audit
from agent_team_v15.evidence_ledger import (
    EvidenceLedger,
    EvidenceRecord,
    map_endpoint_to_acs,
    map_integration_to_acs,
    resolve_collector_availability,
)


STATIC_PRD = """# Project: Evidence Demo

## Feature F-001: Authentication
### Acceptance Criteria
- [ ] AC-1: GIVEN a login response, WHEN auth succeeds, THEN the JWT is stored in an httpOnly cookie.
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_master_plan(root: Path, milestones: list[dict[str, object]]) -> None:
    _write(root / ".agent-team" / "MASTER_PLAN.json", json.dumps({"milestones": milestones}, indent=2))


def _write_static_project(tmp_path: Path) -> tuple[Path, Path]:
    prd_path = tmp_path / "prd.md"
    prd_path.write_text(STATIC_PRD, encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "auth.ts").write_text(
        "export const cookieOptions = { httpOnly: true, secure: true };\n",
        encoding="utf-8",
    )
    return prd_path, tmp_path


class TestEvidenceLedger:
    def test_round_trip_record_save_load(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["code_span"])
        ledger.record_evidence(
            "AC-1",
            EvidenceRecord(type="code_span", path="src/auth.ts", content="httpOnly: true", source="static_analysis"),
            verdict="PASS",
            notes="Found cookie config",
        )

        reloaded = EvidenceLedger(tmp_path / "evidence")
        reloaded.load_all()
        entry = reloaded.get_entry("AC-1")

        assert entry is not None
        assert entry.verdict == "PASS"
        assert entry.required_evidence == ["code_span"]
        assert len(entry.evidence) == 1
        assert entry.evidence[0].path == "src/auth.ts"

    def test_check_evidence_complete(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["code_span", "http_transcript"])
        ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="code"), verdict="PARTIAL")
        assert ledger.check_evidence_complete("AC-1") is False

        ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 200"), verdict="PASS")
        assert ledger.check_evidence_complete("AC-1") is True

    def test_multiple_evidence_records_accumulate(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="one"))
        ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="two"))
        entry = ledger.get_entry("AC-1")

        assert entry is not None
        assert len(entry.evidence) == 2

    def test_empty_directory_load_is_safe(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.load_all()
        assert ledger.get_entry("AC-404") is None

    def test_sanitizes_filename_but_preserves_ac_id(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.record_evidence(
            "AC:AUTH/1",
            EvidenceRecord(type="code_span", path="src/auth.ts", content="httpOnly: true"),
            verdict="PASS",
        )

        evidence_files = list((tmp_path / "evidence").glob("*.json"))
        assert len(evidence_files) == 1
        assert evidence_files[0].name == "AC_AUTH_1.json"

        data = json.loads(evidence_files[0].read_text(encoding="utf-8"))
        assert data["ac_id"] == "AC:AUTH/1"

    def test_soft_gate_missing_available_evidence_downgrades_to_partial(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["http_transcript"])
        ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="code"), verdict="PASS")

        verdict = ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="PASS",
            evidence_mode="soft_gate",
            collector_availability={"http_transcript": True, "code_span": True},
        )

        assert verdict == "PARTIAL"

    def test_soft_gate_unavailable_collector_returns_unverified(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["simulator_state"])
        ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="code"), verdict="PASS")

        verdict = ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="PASS",
            evidence_mode="soft_gate",
            collector_availability={"simulator_state": False, "code_span": True},
        )

        assert verdict == "UNVERIFIED"

    def test_hard_gate_never_upgrades_failures(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["http_transcript"])

        verdict = ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="FAIL",
            evidence_mode="hard_gate",
            collector_availability={"http_transcript": True},
        )

        assert verdict == "FAIL"

    def test_hard_gate_uses_required_collectors_not_hardcoded_runtime_set(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / "evidence")
        ledger.set_required_evidence("AC-1", ["http_transcript"])
        ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")

        assert ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="PASS",
            evidence_mode="hard_gate",
            collector_availability={"http_transcript": True},
        ) == "PASS"
        assert ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="PASS",
            evidence_mode="hard_gate",
            collector_availability={"http_transcript": False},
        ) == "UNVERIFIED"

    def test_resolve_collector_availability_from_milestone_scoped_evidence(self, tmp_path: Path) -> None:
        _write_master_plan(
            tmp_path,
            [{"id": "milestone-orders", "ac_refs": ["AC-1", "AC-2"]}],
        )
        ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
        ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")
        ledger.record_evidence("AC-1", EvidenceRecord(type="db_assertion", content="SELECT 1"), verdict="PASS")
        ledger.record_evidence("AC-1", EvidenceRecord(type="simulator_state", content='{"ok":true}'), verdict="PASS")
        ledger.record_evidence("AC-2", EvidenceRecord(type="playwright_trace", content="trace.zip"), verdict="PASS")

        config = SimpleNamespace(v18=SimpleNamespace(live_endpoint_check=True, evidence_mode="soft_gate"))
        availability = resolve_collector_availability(
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=config,
            cwd=str(tmp_path),
        )

        assert availability["http_transcript"] is True
        assert availability["db_assertion"] is True
        assert availability["simulator_state"] is True
        assert availability["playwright_trace"] is True

    def test_resolve_collector_availability_ignores_other_milestone_db_assertions(self, tmp_path: Path) -> None:
        _write_master_plan(
            tmp_path,
            [
                {"id": "milestone-orders", "ac_refs": ["AC-1"]},
                {"id": "milestone-payments", "ac_refs": ["AC-2"]},
            ],
        )
        ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
        ledger.record_evidence("AC-2", EvidenceRecord(type="db_assertion", content="SELECT 1"), verdict="PASS")

        config = SimpleNamespace(v18=SimpleNamespace(live_endpoint_check=True, evidence_mode="soft_gate"))
        availability = resolve_collector_availability(
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=config,
            cwd=str(tmp_path),
        )

        assert availability["db_assertion"] is False
        assert availability["http_transcript"] is False
        assert availability["simulator_state"] is False

    def test_resolve_collector_availability_requires_playwright_evidence_not_spec_files(self, tmp_path: Path) -> None:
        _write_master_plan(
            tmp_path,
            [{"id": "milestone-orders", "ac_refs": ["AC-1"]}],
        )
        _write(tmp_path / "e2e" / "tests" / "milestone-orders" / "orders.spec.ts", "test('orders', async () => {});\n")

        config = SimpleNamespace(v18=SimpleNamespace(live_endpoint_check=True, evidence_mode="soft_gate"))
        availability = resolve_collector_availability(
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=config,
            cwd=str(tmp_path),
        )

        assert availability["http_transcript"] is False
        assert availability["db_assertion"] is False
        assert availability["playwright_trace"] is False
        assert availability["simulator_state"] is False

    def test_resolve_collector_availability_empty_evidence_dir_returns_only_code_span(self, tmp_path: Path) -> None:
        _write_master_plan(
            tmp_path,
            [{"id": "milestone-orders", "ac_refs": ["AC-1"]}],
        )

        config = SimpleNamespace(v18=SimpleNamespace(live_endpoint_check=True, evidence_mode="soft_gate"))
        availability = resolve_collector_availability(
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=config,
            cwd=str(tmp_path),
        )

        assert availability == {
            "code_span": True,
            "http_transcript": False,
            "playwright_trace": False,
            "db_assertion": False,
            "simulator_state": False,
            "log_excerpt": False,
        }

    def test_resolve_collector_availability_without_master_plan_degrades_explicitly(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
        ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")

        config = SimpleNamespace(v18=SimpleNamespace(live_endpoint_check=True, evidence_mode="soft_gate"))
        availability = resolve_collector_availability(
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=config,
            cwd=str(tmp_path),
        )

        assert availability == {
            "code_span": True,
            "http_transcript": False,
            "playwright_trace": False,
            "db_assertion": False,
            "simulator_state": False,
            "log_excerpt": False,
        }

    def test_endpoint_and_integration_mapping_use_product_ir(self, tmp_path: Path) -> None:
        product_ir_dir = tmp_path / ".agent-team" / "product-ir"
        product_ir_dir.mkdir(parents=True, exist_ok=True)
        (product_ir_dir / "product.ir.json").write_text(
            json.dumps(
                {
                    "acceptance_criteria": [
                        {"id": "AC-1", "feature": "F-ORDERS", "text": "Show orders list"},
                        {"id": "AC-2", "feature": "F-PAYMENTS", "text": "Charge order with Stripe"},
                    ],
                    "endpoints": [
                        {"method": "GET", "path": "/orders", "owner_feature": "F-ORDERS"},
                    ],
                    "integrations": [
                        {
                            "vendor": "Stripe",
                            "type": "payment",
                            "owner_feature": "F-PAYMENTS",
                            "methods_used": ["chargeOrder"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        assert map_endpoint_to_acs("GET", "/orders", str(tmp_path)) == ["AC-1"]
        assert map_integration_to_acs("Stripe", "chargeOrder", str(tmp_path)) == ["AC-2"]


class TestEvidenceAuditIntegration:
    def test_run_audit_records_evidence_only_when_enabled(self, tmp_path: Path) -> None:
        prd_path, codebase_path = _write_static_project(tmp_path)

        disabled_report = run_audit(
            original_prd_path=prd_path,
            codebase_path=codebase_path,
            config={"deterministic_first": False, "evidence_mode": "disabled"},
        )
        evidence_path = codebase_path / ".agent-team" / "evidence" / "AC-1.json"
        assert disabled_report.total_acs == 1
        assert evidence_path.exists() is False

        enabled_report = run_audit(
            original_prd_path=prd_path,
            codebase_path=codebase_path,
            config={"deterministic_first": False, "evidence_mode": "record_only"},
        )
        assert enabled_report.total_acs == disabled_report.total_acs
        assert enabled_report.passed_acs == disabled_report.passed_acs
        assert evidence_path.is_file()

        evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert evidence_data["ac_id"] == "AC-1"
        expected_verdict = "PASS" if enabled_report.passed_acs else "FAIL"
        assert evidence_data["verdict"] == expected_verdict
        assert evidence_data["evidence"][0]["type"] == "code_span"
