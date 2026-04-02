"""Simulation tests for enterprise ownership validation and wave execution."""
import json
import pytest
from agent_team_v15.ownership_validator import validate_ownership_map, OwnershipFinding


class TestOwnershipValidation:
    def _valid_map(self):
        return {
            "version": 1,
            "domains": {
                "auth-backend": {
                    "tech_stack": "nestjs", "agent_type": "backend-dev",
                    "files": ["backend/src/auth/**"],
                    "requirements": ["REQ-001", "REQ-002"],
                    "dependencies": [], "shared_reads": []
                },
                "dashboard-frontend": {
                    "tech_stack": "nextjs", "agent_type": "frontend-dev",
                    "files": ["frontend/app/dashboard/**"],
                    "requirements": ["REQ-003", "REQ-004"],
                    "dependencies": ["auth-backend"], "shared_reads": []
                },
            },
            "waves": [
                {"id": 1, "name": "backend", "domains": ["auth-backend"], "parallel": False},
                {"id": 2, "name": "frontend", "domains": ["dashboard-frontend"], "parallel": False},
            ],
            "shared_scaffolding": ["backend/prisma/schema.prisma"]
        }

    def test_valid_map_passes(self):
        findings = validate_ownership_map(
            self._valid_map(), {"REQ-001", "REQ-002", "REQ-003", "REQ-004"}
        )
        critical = [f for f in findings if f.severity == "critical"]
        assert len(critical) == 0

    def test_file_overlap_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["files"].append("frontend/app/dashboard/**")
        findings = validate_ownership_map(m)
        own001 = [f for f in findings if f.check == "OWN-001"]
        assert len(own001) > 0

    def test_unassigned_requirement_detected(self):
        findings = validate_ownership_map(
            self._valid_map(), {"REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"}
        )
        own002 = [f for f in findings if f.check == "OWN-002"]
        assert len(own002) > 0

    def test_circular_dependency_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["dependencies"] = ["dashboard-frontend"]
        m["domains"]["dashboard-frontend"]["dependencies"] = ["auth-backend"]
        findings = validate_ownership_map(m)
        own005 = [f for f in findings if f.check == "OWN-005"]
        assert len(own005) > 0

    def test_scaffolding_in_domain_detected(self):
        m = self._valid_map()
        m["domains"]["auth-backend"]["files"].append("backend/prisma/schema.prisma")
        findings = validate_ownership_map(m)
        own006 = [f for f in findings if f.check == "OWN-006"]
        assert len(own006) > 0

    def test_no_sendmessage_in_enterprise_prompts(self):
        from agent_team_v15.agents import (
            BACKEND_DEV_PROMPT, FRONTEND_DEV_PROMPT, INFRA_DEV_PROMPT,
            ENTERPRISE_ARCHITECTURE_STEPS,
        )
        for name, prompt in [
            ("backend-dev", BACKEND_DEV_PROMPT),
            ("frontend-dev", FRONTEND_DEV_PROMPT),
            ("infra-dev", INFRA_DEV_PROMPT),
            ("architecture-steps", ENTERPRISE_ARCHITECTURE_STEPS),
        ]:
            assert "SendMessage" not in prompt, f"{name} has SendMessage"
            assert "TeamCreate" not in prompt, f"{name} has TeamCreate"
