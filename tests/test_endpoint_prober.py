"""Tests for endpoint_prober PORT detection precedence (N-01)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from agent_team_v15.endpoint_prober import _detect_app_url


class _NoConfig:
    pass


def _cfg(app_port: int = 0) -> Any:
    class C:
        class browser_testing:
            pass
    C.browser_testing.app_port = app_port
    return C


def test_detect_from_config_browser_testing_app_port_still_wins(tmp_path: Path) -> None:
    # Precedence #1 preserved.
    (tmp_path / ".env").write_text("PORT=9999\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=4000)) == "http://localhost:4000"


def test_detect_from_project_root_env(tmp_path: Path) -> None:
    # Precedence #2 preserved.
    (tmp_path / ".env").write_text("PORT=8080\nOTHER=1\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:8080"


def test_detect_from_apps_api_env_example(tmp_path: Path) -> None:
    api_dir = tmp_path / "apps" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / ".env.example").write_text("DATABASE_URL=postgres://x\nPORT=4000\nCORS_ORIGIN=*\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4000"


def test_detect_from_main_ts_listen_literal(tmp_path: Path) -> None:
    main_dir = tmp_path / "apps" / "api" / "src"
    main_dir.mkdir(parents=True)
    (main_dir / "main.ts").write_text("async function bootstrap() {\n  await app.listen(4321);\n}\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4321"


def test_detect_from_main_ts_listen_process_env_default(tmp_path: Path) -> None:
    main_dir = tmp_path / "apps" / "api" / "src"
    main_dir.mkdir(parents=True)
    (main_dir / "main.ts").write_text("await app.listen(process.env.PORT ?? 4567);\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4567"


def test_detect_from_docker_compose_api_ports(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    ports:\n      - '4000:4000'\n"
    )
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4000"


def test_detect_docker_compose_long_form_published(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    ports:\n      - published: 8000\n        target: 4000\n"
    )
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:8000"


def test_precedence_env_example_beats_main_ts(tmp_path: Path) -> None:
    api_dir = tmp_path / "apps" / "api"
    (api_dir / "src").mkdir(parents=True)
    (api_dir / ".env.example").write_text("PORT=4000\n")
    (api_dir / "src" / "main.ts").write_text("await app.listen(3000);\n")
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4000"


def test_precedence_main_ts_beats_compose(tmp_path: Path) -> None:
    api_dir = tmp_path / "apps" / "api"
    (api_dir / "src").mkdir(parents=True)
    (api_dir / "src" / "main.ts").write_text("await app.listen(4321);\n")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    ports:\n      - '5555:4000'\n"
    )
    assert _detect_app_url(tmp_path, _cfg(app_port=0)) == "http://localhost:4321"


def test_fallback_warning_when_all_sources_fail(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="agent_team_v15.endpoint_prober")
    url = _detect_app_url(tmp_path, _cfg(app_port=0))
    assert url == "http://localhost:3080"
    assert any("3080" in rec.getMessage() and "fall" in rec.getMessage().lower() for rec in caplog.records), (
        f"Expected LOUD warning on :3080 fallback; got log records: {[r.getMessage() for r in caplog.records]}"
    )


def test_no_warning_when_port_detected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="agent_team_v15.endpoint_prober")
    (tmp_path / ".env").write_text("PORT=4000\n")
    _detect_app_url(tmp_path, _cfg(app_port=0))
    assert not any("3080" in rec.getMessage() for rec in caplog.records)


def test_handles_missing_config(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PORT=4000\n")
    assert _detect_app_url(tmp_path, None) == "http://localhost:4000"


def test_compose_parse_failure_falls_through(tmp_path: Path) -> None:
    # Malformed YAML should silently fall through to fallback warning, not raise.
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    ports:\n      - not-a-port-mapping\n")
    url = _detect_app_url(tmp_path, _cfg(app_port=0))
    assert url == "http://localhost:3080"
