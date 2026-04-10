from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.artifact_store import load_dependency_artifacts
from agent_team_v15.compile_profiles import get_compile_profile
from agent_team_v15.openapi_generator import _diff_cumulative_specs


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_compile_profile_returns_noop_when_no_supported_tooling_exists(tmp_path: Path) -> None:
    profile = get_compile_profile("B", "full_stack", "Custom Stack", tmp_path)

    assert profile.name == "noop"
    assert profile.commands == []


def test_load_dependency_artifacts_ignores_non_phase2_wave_outputs(tmp_path: Path) -> None:
    milestone = SimpleNamespace(id="milestone-orders", dependencies=["M3"])
    for wave in ("A", "B", "C", "D", "E"):
        _write(
            tmp_path / ".agent-team" / "artifacts" / f"M3-wave-{wave}.json",
            json.dumps({"wave": wave, "marker": f"M3-{wave}"}),
        )

    loaded = load_dependency_artifacts(milestone, str(tmp_path))

    assert set(loaded) == {"M3-wave-A", "M3-wave-B", "M3-wave-C"}


def test_diff_cumulative_specs_reports_removed_and_changed_operations(tmp_path: Path) -> None:
    contracts_dir = tmp_path / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    previous_spec = {
        "paths": {
            "/orders": {
                "get": {"responses": {"200": {"description": "ok"}}},
                "post": {"responses": {"201": {"description": "created"}}},
            }
        }
    }
    current_spec = {
        "paths": {
            "/orders": {
                "get": {"responses": {"200": {"description": "updated"}}},
            }
        }
    }

    _write(contracts_dir / "previous.json", json.dumps(previous_spec, indent=2))
    _write(contracts_dir / "current.json", json.dumps(current_spec, indent=2))

    breaking_changes = _diff_cumulative_specs(contracts_dir)

    assert breaking_changes == ["REMOVED: POST /orders", "CHANGED: GET /orders"]
    assert json.loads((contracts_dir / "previous.json").read_text(encoding="utf-8")) == current_spec
