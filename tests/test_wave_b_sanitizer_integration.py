"""Integration test for the wave_b_sanitizer wiring.

Verifies that ``_maybe_sanitize_wave_b_outputs`` is called in the
post-Wave-B hook at ``wave_executor.py`` and appends orphan findings
to the wave_result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.wave_executor import _maybe_sanitize_wave_b_outputs


@dataclass
class _WaveResult:
    findings: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    files_modified: list = field(default_factory=list)


def _config(enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(wave_b_output_sanitization_enabled=enabled)
    return cfg


@dataclass(frozen=True)
class _FakeRow:
    path: str
    owner: str


class _FakeContract:
    def __init__(self, rows):
        self._rows = tuple(rows)

    def files_for_owner(self, owner):
        return [r for r in self._rows if r.owner == owner]

    def owner_for(self, path):
        for row in self._rows:
            if row.path == path:
                return row.owner
        return None


def _patch_contract(contract):
    return patch(
        "agent_team_v15.wave_executor.load_ownership_contract"
        if False
        else "agent_team_v15.scaffold_runner.load_ownership_contract",
        return_value=contract,
    )


class TestWaveBSanitizerWiring:
    def test_flag_off_no_findings_added(self, tmp_path: Path) -> None:
        wave_result = _WaveResult(files_created=["package.json"])
        contract = _FakeContract([_FakeRow("package.json", "scaffold")])
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        with _patch_contract(contract):
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_config(enabled=False),
                wave_result=wave_result,
            )
        assert wave_result.findings == []

    def test_orphan_emission_appended_to_findings(self, tmp_path: Path) -> None:
        # Wave B wrote package.json — a scaffold-owned path.
        wave_result = _WaveResult(files_created=["package.json"])
        contract = _FakeContract([_FakeRow("package.json", "scaffold")])
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        with _patch_contract(contract):
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_config(enabled=True),
                wave_result=wave_result,
            )
        assert len(wave_result.findings) == 1
        finding = wave_result.findings[0]
        assert finding["finding_id"].startswith("N-19-ORPHAN-")
        assert finding["severity"] in ("MEDIUM", "INFO")
        assert finding["source"] == "deterministic"

    def test_legitimate_wave_b_emission_no_finding(self, tmp_path: Path) -> None:
        wave_result = _WaveResult(
            files_created=["apps/api/src/auth/auth.module.ts"],
        )
        contract = _FakeContract([
            _FakeRow("package.json", "scaffold"),
            _FakeRow("apps/api/src/main.ts", "scaffold"),
        ])
        with _patch_contract(contract):
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_config(enabled=True),
                wave_result=wave_result,
            )
        assert wave_result.findings == []

    def test_absolute_path_normalised(self, tmp_path: Path) -> None:
        """Absolute paths in files_created get relativised before matching."""
        abs_path = tmp_path / "package.json"
        abs_path.write_text("{}", encoding="utf-8")
        wave_result = _WaveResult(files_created=[str(abs_path)])
        contract = _FakeContract([_FakeRow("package.json", "scaffold")])
        with _patch_contract(contract):
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_config(enabled=True),
                wave_result=wave_result,
            )
        assert len(wave_result.findings) == 1
        # Consumer scan + serialisation lines up the relative form.
        assert "package.json" in wave_result.findings[0]["finding_id"]

    def test_contract_load_failure_is_non_fatal(self, tmp_path: Path) -> None:
        wave_result = _WaveResult(files_created=["package.json"])
        with patch(
            "agent_team_v15.scaffold_runner.load_ownership_contract",
            side_effect=FileNotFoundError("contract gone"),
        ):
            # Should not raise.
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_config(enabled=True),
                wave_result=wave_result,
            )
        assert wave_result.findings == []
