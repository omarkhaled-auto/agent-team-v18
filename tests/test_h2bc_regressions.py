from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_team_v15.audit_models import AuditFinding, build_report
from agent_team_v15.cli import _apply_evidence_gating_to_audit_report
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.scaffold_runner import OwnershipPolicyMissingError
from agent_team_v15.wave_executor import (
    _maybe_run_scaffold_verifier,
    _maybe_run_spec_reconciliation,
    _requirements_declared_deliverable_findings,
)


def test_wave_b_requirements_declared_deliverable_findings_use_contract(tmp_path):
    cfg = AgentTeamConfig()
    findings = _requirements_declared_deliverable_findings(
        cwd=str(tmp_path),
        config=cfg,
        required_by="wave-b",
        milestone_scope=None,
    )
    assert len(findings) == 1
    assert findings[0].code == "SCAFFOLD-REQUIREMENTS-MISSING-001"
    assert findings[0].file == "apps/api/Dockerfile"


def test_evidence_gating_persists_scope_without_verdict_downgrade(tmp_path):
    cfg = AgentTeamConfig()
    cfg.v18.evidence_mode = "soft_gate"
    report = build_report(
        audit_id="audit-h2bc-scope",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="REQ-1",
                auditor="requirements",
                requirement_id="AC-1",
                verdict="PASS",
                severity="LOW",
                summary="Implemented",
                evidence=["src/orders.ts:1"],
            )
        ],
    )
    report.acceptance_tests = {"probe": {"passed": True}}

    agent_team_dir = tmp_path / ".agent-team"
    milestones_dir = agent_team_dir / "milestones" / "milestone-orders"
    milestones_dir.mkdir(parents=True, exist_ok=True)
    (agent_team_dir / "MASTER_PLAN.json").write_text(
        json.dumps({"milestones": [{"id": "milestone-orders"}]}),
        encoding="utf-8",
    )
    (milestones_dir / "REQUIREMENTS.md").write_text("# M1\n", encoding="utf-8")

    scope = SimpleNamespace(
        milestone_id="milestone-orders",
        allowed_file_globs=["src/orders.ts"],
        allowed_feature_refs=["F-ORDERS"],
        allowed_ac_refs=["AC-1"],
    )
    partition = SimpleNamespace(in_scope=list(report.findings), out_of_scope=[])

    with patch("agent_team_v15.audit_scope.audit_scope_for_milestone", return_value=scope), patch(
        "agent_team_v15.audit_scope.partition_findings_by_scope",
        return_value=partition,
    ), patch(
        "agent_team_v15.audit_scope.scope_violation_findings",
        return_value=[],
    ):
        gated = _apply_evidence_gating_to_audit_report(
            report,
            milestone_id="milestone-orders",
            milestone_template="full_stack",
            config=cfg,
            cwd=str(tmp_path),
        )

    assert gated.scope["milestone_id"] == "milestone-orders"
    assert gated.scope["allowed_file_globs"] == ["src/orders.ts"]
    assert gated.acceptance_tests == {"probe": {"passed": True}}


def test_spec_reconciliation_raises_when_policy_required_and_contract_missing(tmp_path):
    cfg = AgentTeamConfig()
    cfg.v18.ownership_policy_required = True
    milestone_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True, exist_ok=True)
    (milestone_dir / "REQUIREMENTS.md").write_text("# M1\n", encoding="utf-8")
    with patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract_from_workspace",
        side_effect=FileNotFoundError("missing"),
    ):
        with pytest.raises(OwnershipPolicyMissingError):
            _maybe_run_spec_reconciliation(
                cwd=str(tmp_path),
                milestone_id="milestone-1",
                config=cfg,
            )


def test_spec_reconciliation_skips_when_policy_missing_and_not_required(tmp_path, caplog):
    cfg = AgentTeamConfig()
    milestone_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True, exist_ok=True)
    (milestone_dir / "REQUIREMENTS.md").write_text("# M1\n", encoding="utf-8")
    with patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract_from_workspace",
        side_effect=FileNotFoundError("missing"),
    ):
        result = _maybe_run_spec_reconciliation(
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            config=cfg,
        )
    assert result is None
    assert any(
        "spec reconciler: could not load ownership contract" in rec.message
        for rec in caplog.records
    )


def test_scaffold_verifier_raises_when_policy_required_and_contract_missing(tmp_path):
    cfg = AgentTeamConfig()
    cfg.v18.ownership_policy_required = True
    with patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract_from_workspace",
        side_effect=FileNotFoundError("missing"),
    ):
        with pytest.raises(OwnershipPolicyMissingError):
            _maybe_run_scaffold_verifier(
                cwd=str(tmp_path),
                config=cfg,
                milestone_id="milestone-1",
            )


def test_scaffold_verifier_skips_when_policy_missing_and_not_required(tmp_path, caplog):
    cfg = AgentTeamConfig()
    with patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract_from_workspace",
        side_effect=FileNotFoundError("missing"),
    ):
        result = _maybe_run_scaffold_verifier(
            cwd=str(tmp_path),
            config=cfg,
            milestone_id="milestone-1",
        )
    assert result is None
    assert any(
        "scaffold verifier: could not load ownership contract" in rec.message
        for rec in caplog.records
    )
