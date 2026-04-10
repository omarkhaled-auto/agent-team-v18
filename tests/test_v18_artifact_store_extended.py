from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.artifact_store import format_artifacts_for_prompt, load_dependency_artifacts
from agent_team_v15.wave_executor import _create_checkpoint, _diff_checkpoints


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(*, dependencies: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(id="milestone-orders", dependencies=dependencies or [])


class TestArtifactRouting:
    def test_wave_a_receives_only_dependency_entities(self) -> None:
        rendered = format_artifacts_for_prompt(
            {"A": {"entities": [{"name": "LocalOrder"}]}},
            {
                "M2-wave-A": {"entities": [{"name": "Customer", "file": "apps/api/src/customer.entity.ts"}]},
                "M2-wave-B": {"services": [{"name": "PaymentsPort", "file": "apps/api/src/payments.service.ts"}]},
            },
            "A",
        )

        assert "Customer" in rendered
        assert "PaymentsPort" not in rendered
        assert "LocalOrder" not in rendered

    def test_wave_b_receives_wave_a_entities_and_adapter_ports(self) -> None:
        rendered = format_artifacts_for_prompt(
            {"A": {"entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}]}},
            {
                "M2-wave-B": {"services": [{"name": "PaymentsPort", "file": "apps/api/src/payments.port.ts"}]},
            },
            "B",
        )

        assert "Order" in rendered
        assert "PaymentsPort" in rendered

    def test_wave_d_receives_only_wave_c_artifacts(self) -> None:
        rendered = format_artifacts_for_prompt(
            {
                "A": {"entities": [{"name": "InternalOrderEntity"}]},
                "B": {"services": [{"name": "InternalOrdersService"}]},
                "C": {"client_exports": ["listOrders"], "endpoints": [{"method": "GET", "path": "/orders"}]},
            },
            {},
            "D",
        )

        assert "listOrders" in rendered
        assert "InternalOrderEntity" not in rendered
        assert "InternalOrdersService" not in rendered

    def test_wave_d_does_not_receive_wave_a_or_b(self) -> None:
        rendered = format_artifacts_for_prompt(
            {
                "A": {"entities": [{"name": "WaveAEntity"}]},
                "B": {"services": [{"name": "WaveBService"}]},
                "C": {"client_exports": ["loadOrders"]},
            },
            {},
            "D",
        )

        assert "loadOrders" in rendered
        assert "WaveAEntity" not in rendered
        assert "WaveBService" not in rendered

    def test_wave_e_receives_all_wave_artifacts(self) -> None:
        rendered = format_artifacts_for_prompt(
            {
                "A": {"entities": [{"name": "Order"}]},
                "B": {"services": [{"name": "OrdersService"}]},
                "C": {"client_exports": ["listOrders"]},
                "D": {"pages": [{"route": "/orders"}]},
            },
            {},
            "E",
        )

        assert "## Wave A" in rendered
        assert "## Wave B" in rendered
        assert "## Wave C" in rendered
        assert "## Wave D" in rendered


class TestDependencyLoading:
    def test_loads_artifacts_from_dependency_milestones(self, tmp_path: Path) -> None:
        for wave in ("A", "B", "C"):
            _write(
                tmp_path / ".agent-team" / "artifacts" / f"M3-wave-{wave}.json",
                json.dumps({"wave": wave, "marker": f"M3-{wave}"}),
            )

        loaded = load_dependency_artifacts(_milestone(dependencies=["M3"]), str(tmp_path))

        assert set(loaded) == {"M3-wave-A", "M3-wave-B", "M3-wave-C"}

    def test_strips_fine_grained_refs_to_milestone_level(self, tmp_path: Path) -> None:
        _write(
            tmp_path / ".agent-team" / "artifacts" / "M3-wave-A.json",
            json.dumps({"wave": "A", "marker": "M3-A"}),
        )

        loaded = load_dependency_artifacts(_milestone(dependencies=["M3:SyncedSaleOrder"]), str(tmp_path))

        assert set(loaded) == {"M3-wave-A"}

    def test_missing_dependency_artifacts_returns_empty(self, tmp_path: Path) -> None:
        loaded = load_dependency_artifacts(_milestone(dependencies=["M4"]), str(tmp_path))
        assert loaded == {}


class TestCheckpointDiffing:
    def test_new_file_detected_as_created(self, tmp_path: Path) -> None:
        before = _create_checkpoint("before", str(tmp_path))
        _write(tmp_path / "src" / "new.ts", "export const created = true;\n")
        after = _create_checkpoint("after", str(tmp_path))

        diff = _diff_checkpoints(before, after)
        assert diff.created == ["src/new.ts"]

    def test_changed_checksum_detected_as_modified(self, tmp_path: Path) -> None:
        file_path = _write(tmp_path / "src" / "app.ts", "export const value = 1;\n")
        before = _create_checkpoint("before", str(tmp_path))
        file_path.write_text("export const value = 2;\n", encoding="utf-8")
        after = _create_checkpoint("after", str(tmp_path))

        diff = _diff_checkpoints(before, after)
        assert diff.modified == ["src/app.ts"]

    def test_removed_file_detected_as_deleted(self, tmp_path: Path) -> None:
        file_path = _write(tmp_path / "src" / "old.ts", "export const gone = true;\n")
        before = _create_checkpoint("before", str(tmp_path))
        file_path.unlink()
        after = _create_checkpoint("after", str(tmp_path))

        diff = _diff_checkpoints(before, after)
        assert diff.deleted == ["src/old.ts"]

    def test_unchanged_file_not_reported(self, tmp_path: Path) -> None:
        _write(tmp_path / "src" / "same.ts", "export const same = true;\n")
        before = _create_checkpoint("before", str(tmp_path))
        after = _create_checkpoint("after", str(tmp_path))

        diff = _diff_checkpoints(before, after)
        assert diff.created == []
        assert diff.modified == []
        assert diff.deleted == []

    def test_skips_git_and_node_modules(self, tmp_path: Path) -> None:
        _write(tmp_path / ".git" / "config", "ignored\n")
        _write(tmp_path / "node_modules" / "pkg" / "index.js", "ignored\n")
        _write(tmp_path / ".agent-team" / "STATE.json", "{}\n")
        _write(tmp_path / "src" / "app.ts", "export const keep = true;\n")

        checkpoint = _create_checkpoint("snapshot", str(tmp_path))

        assert "src/app.ts" in checkpoint.file_manifest
        assert ".git/config" not in checkpoint.file_manifest
        assert "node_modules/pkg/index.js" not in checkpoint.file_manifest
        assert ".agent-team/STATE.json" not in checkpoint.file_manifest
