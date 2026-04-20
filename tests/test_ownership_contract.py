"""N-02 (Phase B) tests for the ownership contract parser and consumers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_team_v15.config import V18Config, AgentTeamConfig
from agent_team_v15.scaffold_runner import (
    FileOwnership,
    OwnershipContract,
    load_ownership_contract_from_workspace,
    _maybe_validate_ownership,
    OwnershipPolicyMissingError,
    load_ownership_contract,
)


# ---------------------------------------------------------------------------
# Parser tests (primary contract — 60 rows from docs/SCAFFOLD_OWNERSHIP.md)
# ---------------------------------------------------------------------------


class TestOwnershipParser:
    def test_parser_returns_60_rows(self) -> None:
        """The canonical contract defines exactly 60 files for M1 foundation."""
        contract = load_ownership_contract()
        assert len(contract.files) == 60

    def test_files_for_owner_scaffold_returns_44(self) -> None:
        """scaffold owns 44 rows (9 root + 12 apps/api + 13 apps/web + 6 shared — see ownership totals)."""
        contract = load_ownership_contract()
        scaffold_rows = contract.files_for_owner("scaffold")
        assert len(scaffold_rows) == 44

    def test_is_optional_editorconfig_true(self) -> None:
        """The `.editorconfig` row is marked optional: true."""
        contract = load_ownership_contract()
        assert contract.is_optional(".editorconfig") is True

    def test_is_optional_unknown_path_false(self) -> None:
        """Paths not in the contract are not optional (False is the safe default)."""
        contract = load_ownership_contract()
        assert contract.is_optional("nonexistent/path.ts") is False

    def test_owner_for_known_path(self) -> None:
        """Path-to-owner lookup returns the contract-declared owner."""
        contract = load_ownership_contract()
        assert contract.owner_for("apps/api/Dockerfile") == "wave-b"
        assert contract.owner_for("package.json") == "scaffold"

    def test_owner_for_unknown_path_returns_none(self) -> None:
        contract = load_ownership_contract()
        assert contract.owner_for("nonexistent/path.ts") is None

    def test_owner_totals_match_architecture_report(self) -> None:
        contract = load_ownership_contract()
        counts = {
            "scaffold": len(contract.files_for_owner("scaffold")),
            "wave-b": len(contract.files_for_owner("wave-b")),
            "wave-d": len(contract.files_for_owner("wave-d")),
            "wave-c-generator": len(contract.files_for_owner("wave-c-generator")),
        }
        assert counts == {
            "scaffold": 44,
            "wave-b": 12,
            "wave-d": 1,
            "wave-c-generator": 3,
        }

    def test_workspace_loader_falls_back_to_repo_contract(self, tmp_path: Path) -> None:
        contract = load_ownership_contract_from_workspace(tmp_path)
        assert contract.owner_for("apps/api/Dockerfile") == "wave-b"

    def test_requirements_deliverables_filter_by_stage(self) -> None:
        contract = load_ownership_contract()
        scaffold_paths = {
            row.path for row in contract.requirements_declared_deliverables(
                required_by="scaffold"
            )
        }
        wave_b_paths = {
            row.path for row in contract.requirements_declared_deliverables(
                required_by="wave-b"
            )
        }
        assert "docker-compose.yml" in scaffold_paths
        assert ".env.example" in scaffold_paths
        assert "apps/web/Dockerfile" in scaffold_paths
        assert wave_b_paths == {"apps/api/Dockerfile"}

    def test_parser_raises_when_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_ownership_contract(tmp_path / "missing.md")

    def test_parser_raises_on_malformed_yaml(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.md"
        bad.write_text("```yaml\n- path: foo\n  # missing required fields\n```\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_ownership_contract(bad)

    def test_parser_raises_on_unknown_owner(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.md"
        bad.write_text(
            "```yaml\n"
            "- path: x.ts\n"
            "  owner: bogus-owner\n"
            "  optional: false\n"
            "```\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_ownership_contract(bad)


# ---------------------------------------------------------------------------
# Consumer 3 tests — scaffold_runner._maybe_validate_ownership soft invariant
# ---------------------------------------------------------------------------


def _make_config(flag_on: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(ownership_contract_enabled=flag_on)
    return cfg


class TestScaffoldOwnershipValidation:
    def test_no_validation_when_config_is_none(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger="agent_team_v15.scaffold_runner")
        _maybe_validate_ownership(None, [], "M1")
        assert caplog.records == []

    def test_no_validation_when_flag_off(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger="agent_team_v15.scaffold_runner")
        _maybe_validate_ownership(_make_config(False), [], "M1")
        assert caplog.records == []

    def test_warns_on_missing_scaffold_paths_when_flag_on(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="agent_team_v15.scaffold_runner")
        # Emitted ZERO files — every non-optional scaffold-owned path will be "missing"
        _maybe_validate_ownership(_make_config(True), [], "M1")
        assert any(
            "N-02 ownership drift" in rec.message and "not emitted" in rec.message
            for rec in caplog.records
        )

    def test_warns_on_unexpected_wave_owned_path_emitted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="agent_team_v15.scaffold_runner")
        # apps/api/Dockerfile is wave-b owned — scaffold should not emit it
        _maybe_validate_ownership(
            _make_config(True),
            ["apps/api/Dockerfile"],
            "M1",
        )
        assert any(
            "N-02 ownership drift" in rec.message and "apps/api/Dockerfile" in rec.message
            and "wave-b" in rec.message
            for rec in caplog.records
        )

    def test_policy_required_raises_when_contract_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config(
            ownership_contract_enabled=True,
            ownership_policy_required=True,
        )
        monkeypatch.setattr(
            "agent_team_v15.scaffold_runner.load_ownership_contract_from_workspace",
            lambda _workspace=None: (_ for _ in ()).throw(FileNotFoundError("missing")),
        )
        with pytest.raises(OwnershipPolicyMissingError):
            _maybe_validate_ownership(cfg, [], "M1", workspace=tmp_path)


# ---------------------------------------------------------------------------
# Dataclass construction sanity
# ---------------------------------------------------------------------------


class TestFileOwnershipDataclass:
    def test_file_ownership_is_hashable(self) -> None:
        row = FileOwnership(path="x", owner="scaffold", optional=False)
        assert {row} == {row}

    def test_ownership_contract_is_immutable(self) -> None:
        row = FileOwnership(path="x", owner="scaffold", optional=False)
        contract = OwnershipContract(files=(row,))
        with pytest.raises(AttributeError):
            contract.files = ()  # type: ignore[misc]
