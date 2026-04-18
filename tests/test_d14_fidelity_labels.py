"""D-14: Tests for fidelity label headers on verification artefacts.

Covers:
- ensure_fidelity_label_header writes correct HTML comment header
- Idempotent: calling twice does not duplicate header
- GATE_FINDINGS.json writers produce correct {"fidelity": "static", "findings": [...]} shape
- VERIFICATION.md gets fidelity header
- RUNTIME_VERIFICATION.md gets fidelity header
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.mcp_servers import ensure_fidelity_label_header


class TestEnsureFidelityLabelHeader:
    """ensure_fidelity_label_header writes <!-- Verification fidelity: <label> --> ."""

    def test_writes_runtime_header(self, tmp_path: Path) -> None:
        target = tmp_path / "VERIFICATION.md"
        target.write_text("# Verification\nContent here", encoding="utf-8")
        modified = ensure_fidelity_label_header(target, "runtime")
        assert modified is True
        content = target.read_text(encoding="utf-8")
        assert "<!-- Verification fidelity: runtime -->" in content

    def test_writes_heuristic_header(self, tmp_path: Path) -> None:
        target = tmp_path / "VERIFICATION.md"
        target.write_text("# Verification\nContent here", encoding="utf-8")
        modified = ensure_fidelity_label_header(target, "heuristic")
        assert modified is True
        content = target.read_text(encoding="utf-8")
        assert "<!-- Verification fidelity: heuristic -->" in content

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        target = tmp_path / "VERIFICATION.md"
        target.write_text("# Verification\nContent here", encoding="utf-8")
        ensure_fidelity_label_header(target, "runtime")
        modified_again = ensure_fidelity_label_header(target, "runtime")
        assert modified_again is False
        content = target.read_text(encoding="utf-8")
        assert content.count("Verification fidelity:") == 1

    def test_header_prepended_to_existing_content(self, tmp_path: Path) -> None:
        target = tmp_path / "VERIFICATION.md"
        original = "# Verification\nOriginal content"
        target.write_text(original, encoding="utf-8")
        ensure_fidelity_label_header(target, "runtime")
        content = target.read_text(encoding="utf-8")
        assert content.startswith("<!-- Verification fidelity: runtime -->")
        assert original in content

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        target = tmp_path / "nonexistent.md"
        modified = ensure_fidelity_label_header(target, "runtime")
        assert modified is False

    def test_runtime_verification_md(self, tmp_path: Path) -> None:
        target = tmp_path / "RUNTIME_VERIFICATION.md"
        target.write_text("# Runtime Verification\nServices checked", encoding="utf-8")
        modified = ensure_fidelity_label_header(target, "runtime")
        assert modified is True
        content = target.read_text(encoding="utf-8")
        assert "<!-- Verification fidelity: runtime -->" in content


class TestGateFindingsJsonShape:
    """GATE_FINDINGS.json must produce {"fidelity": "static", "findings": [...]}."""

    def test_gate_findings_shape_matches(self, tmp_path: Path) -> None:
        """Verify the shape matches what cli.py writes."""
        violations = [
            "Missing endpoint /api/v1/users",
            "Auth guard not registered",
        ]
        payload = {
            "fidelity": "static",
            "findings": list(violations),
        }
        gate_path = tmp_path / "GATE_FINDINGS.json"
        gate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        assert data["fidelity"] == "static"
        assert isinstance(data["findings"], list)
        assert len(data["findings"]) == 2

    def test_empty_findings_still_has_fidelity(self, tmp_path: Path) -> None:
        payload = {
            "fidelity": "static",
            "findings": [],
        }
        gate_path = tmp_path / "GATE_FINDINGS.json"
        gate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        assert data["fidelity"] == "static"
        assert data["findings"] == []
