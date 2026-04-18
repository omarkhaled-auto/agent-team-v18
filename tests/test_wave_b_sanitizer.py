"""Phase F N-19 — Wave B output sanitization tests.

Covers:
  * Legitimate Wave B emissions (apps/api/src/auth, etc.) → no finding
  * Emission at a scaffold-owned path → orphan flagged
  * Orphan with a detected consumer → flagged but NOT removed, severity INFO
  * Orphan without consumers + remove_orphans=True → deleted + PASS verdict
  * Flag off short-circuits to SanitizationReport(skipped_reason="flag_off")
  * build_orphan_findings serialisation shape
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.wave_b_sanitizer import (
    OrphanFinding,
    SanitizationReport,
    build_orphan_findings,
    sanitize_wave_b_outputs,
)


@dataclass(frozen=True)
class _Row:
    path: str
    owner: str


class _FakeContract:
    """Minimal duck-type matching ``OwnershipContract.files_for_owner``."""

    def __init__(self, rows: Iterable[_Row]):
        self._rows = tuple(rows)

    def files_for_owner(self, owner: str) -> list[_Row]:
        return [r for r in self._rows if r.owner == owner]

    def owner_for(self, path: str) -> str | None:
        for row in self._rows:
            if row.path == path:
                return row.owner
        return None


def _config(enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(wave_b_output_sanitization_enabled=enabled)
    return cfg


class TestFlagGating:
    def test_flag_off_short_circuits(self, tmp_path: Path) -> None:
        contract = _FakeContract([_Row("package.json", "scaffold")])
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["package.json"],
            config=_config(enabled=False),
        )
        assert report.skipped_reason == "flag_off"
        assert report.orphan_count == 0

    def test_no_contract_short_circuits(self, tmp_path: Path) -> None:
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=None,
            wave_b_files=["package.json"],
            config=_config(),
        )
        assert report.skipped_reason == "no_contract"


class TestLegitimateWaveBPaths:
    def test_auth_module_not_flagged(self, tmp_path: Path) -> None:
        contract = _FakeContract([
            _Row("apps/api/src/main.ts", "scaffold"),
            _Row("package.json", "scaffold"),
        ])
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=[
                "apps/api/src/auth/auth.controller.ts",
                "apps/api/src/auth/auth.service.ts",
                "apps/api/src/users/users.controller.ts",
            ],
            config=_config(),
        )
        assert report.orphan_count == 0
        assert report.scanned_files == 3


class TestOrphanDetection:
    def test_emission_at_scaffold_path_is_orphan(self, tmp_path: Path) -> None:
        contract = _FakeContract([
            _Row("package.json", "scaffold"),
            _Row("apps/api/src/main.ts", "scaffold"),
        ])
        # Simulate that Wave B wrote package.json (a scaffold-owned slot).
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["package.json"],
            config=_config(),
        )
        assert report.orphan_count == 1
        orphan = report.orphan_findings[0]
        assert orphan.relative_path == "package.json"
        assert orphan.expected_owner == "scaffold"
        # No consumers wired up in tmp_path → has_consumers False.
        assert orphan.has_consumers is False
        # Report-only mode: never removed by default.
        assert orphan.removed is False
        assert (tmp_path / "package.json").is_file()

    def test_orphan_with_consumer_is_not_removed(self, tmp_path: Path) -> None:
        contract = _FakeContract([
            _Row("apps/api/src/main.ts", "scaffold"),
        ])
        # Write the orphan file and a consumer that imports it.
        main = tmp_path / "apps" / "api" / "src" / "main.ts"
        main.parent.mkdir(parents=True)
        main.write_text("// main entry\n", encoding="utf-8")
        consumer = tmp_path / "apps" / "api" / "src" / "app.module.ts"
        consumer.write_text(
            "import { bootstrap } from './main';\n", encoding="utf-8",
        )
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["apps/api/src/main.ts"],
            config=_config(),
            remove_orphans=True,
        )
        assert report.orphan_count == 1
        orphan = report.orphan_findings[0]
        assert orphan.has_consumers is True
        assert orphan.consumer_samples  # at least one sample
        # Even with remove_orphans=True, a consumer protects the file.
        assert orphan.removed is False
        assert main.is_file()

    def test_orphan_without_consumer_can_be_removed(self, tmp_path: Path) -> None:
        contract = _FakeContract([
            _Row("apps/api/stale_output.ts", "scaffold"),
        ])
        stale = tmp_path / "apps" / "api" / "stale_output.ts"
        stale.parent.mkdir(parents=True)
        stale.write_text("// stale\n", encoding="utf-8")
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["apps/api/stale_output.ts"],
            config=_config(),
            remove_orphans=True,
        )
        assert report.orphan_count == 1
        assert report.orphan_findings[0].removed is True
        assert not stale.exists()
        assert report.removed_count == 1

    def test_mixed_wave_b_output(self, tmp_path: Path) -> None:
        """Legitimate + orphan emissions in the same batch."""
        contract = _FakeContract([
            _Row("package.json", "scaffold"),
        ])
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=[
                "apps/api/src/auth/auth.module.ts",  # legitimate
                "package.json",  # orphan
            ],
            config=_config(),
        )
        assert report.orphan_count == 1
        assert report.orphan_findings[0].relative_path == "package.json"

    def test_wave_b_emission_in_wave_d_owned_path_is_orphan(
        self, tmp_path: Path
    ) -> None:
        """F-INT-002: Wave B writing a wave-d-owned path is flagged.

        The scaffold ownership contract lists four valid owners
        (``scaffold``, ``wave-b``, ``wave-d``, ``wave-c-generator``).
        The sanitizer must treat EVERY non-wave-b owner as a "not
        Wave B's slot" signal. Previously the owner list was only
        ``("scaffold", "wave-c-generator")`` so a Wave B emission in
        apps/web territory was silently accepted even though wave-d
        owned that path.
        """
        contract = _FakeContract([
            _Row("apps/web/app/page.tsx", "wave-d"),
        ])
        page = tmp_path / "apps" / "web" / "app" / "page.tsx"
        page.parent.mkdir(parents=True)
        page.write_text("// wave-d territory\n", encoding="utf-8")
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["apps/web/app/page.tsx"],
            config=_config(),
        )
        assert report.orphan_count == 1
        assert report.orphan_findings[0].expected_owner == "wave-d"


class TestBuildOrphanFindings:
    def test_removed_orphan_becomes_info_pass(self) -> None:
        report = SanitizationReport(
            orphan_findings=[
                OrphanFinding(
                    relative_path="apps/api/stale.ts",
                    expected_owner="scaffold",
                    has_consumers=False,
                    removed=True,
                )
            ],
        )
        findings = build_orphan_findings(report)
        assert len(findings) == 1
        f = findings[0]
        assert f["severity"] == "INFO"
        assert f["verdict"] == "PASS"
        assert "removed" in f["summary"].lower()

    def test_unremoved_orphan_with_consumers_is_info_partial(self) -> None:
        report = SanitizationReport(
            orphan_findings=[
                OrphanFinding(
                    relative_path="package.json",
                    expected_owner="scaffold",
                    has_consumers=True,
                    consumer_samples=["apps/api/src/main.ts"],
                )
            ],
        )
        findings = build_orphan_findings(report)
        f = findings[0]
        assert f["severity"] == "INFO"
        assert f["verdict"] == "PARTIAL"
        assert "consumers=detected" in f["summary"]

    def test_unremoved_orphan_without_consumers_is_medium(self) -> None:
        report = SanitizationReport(
            orphan_findings=[
                OrphanFinding(
                    relative_path="docker-compose.yml",
                    expected_owner="scaffold",
                    has_consumers=False,
                )
            ],
        )
        findings = build_orphan_findings(report)
        assert findings[0]["severity"] == "MEDIUM"
        assert findings[0]["verdict"] == "PARTIAL"
