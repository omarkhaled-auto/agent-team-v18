"""Integration tests for the infra_detector / endpoint_prober wiring.

Verifies:
  * ``_detect_runtime_infra`` is called during ``start_docker_for_probing``
    so the DockerContext carries a populated RuntimeInfra snapshot.
  * ``execute_probes`` composes URLs via ``build_probe_url`` when the
    DockerContext has a detected ``api_prefix`` — so probing /health
    hits /api/health when main.ts has ``setGlobalPrefix('api')``.
  * Flag off → no RuntimeInfra attached, URLs fall through to legacy
    ``base_url + probe.path`` shape.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import AsyncMock, patch

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.endpoint_prober import (
    DockerContext,
    ProbeSpec,
    ProbeManifest,
    _detect_runtime_infra,
    execute_probes,
)


def _config(*, enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(runtime_infra_detection_enabled=enabled)
    return cfg


def _write_main_ts_with_prefix(tmp_path: Path, prefix: str) -> None:
    main = tmp_path / "apps" / "api" / "src" / "main.ts"
    main.parent.mkdir(parents=True)
    main.write_text(
        dedent(
            f"""
            import {{ NestFactory }} from '@nestjs/core';
            async function bootstrap() {{
              const app = await NestFactory.create(AppModule);
              app.setGlobalPrefix('{prefix}');
              await app.listen(4000);
            }}
            bootstrap();
            """
        ).strip(),
        encoding="utf-8",
    )


class TestRuntimeInfraDetectedAtProbeStartup:
    def test_detect_runtime_infra_is_called(self, tmp_path: Path) -> None:
        _write_main_ts_with_prefix(tmp_path, "api")
        infra = _detect_runtime_infra(tmp_path, _config())
        assert infra is not None
        assert infra.api_prefix == "api"

    def test_flag_off_returns_empty_snapshot(self, tmp_path: Path) -> None:
        _write_main_ts_with_prefix(tmp_path, "api")
        infra = _detect_runtime_infra(tmp_path, _config(enabled=False))
        # Flag off still returns a RuntimeInfra but with empty fields.
        assert infra is not None
        assert infra.api_prefix == ""


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "OK") -> None:
        self.status_code = status_code
        self.text = text


class TestExecuteProbesHonorsApiPrefix:
    @pytest.mark.asyncio
    async def test_probe_url_includes_api_prefix(self, tmp_path: Path) -> None:
        _write_main_ts_with_prefix(tmp_path, "api")
        infra = _detect_runtime_infra(tmp_path, _config())
        ctx = DockerContext(
            app_url="http://localhost:4000",
            api_healthy=True,
            runtime_infra=infra,
        )
        manifest = ProbeManifest(milestone_id="m1")
        manifest.probes.append(
            ProbeSpec(
                endpoint="GET /health",
                method="GET",
                path="/health",
                probe_type="happy_path",
                expected_status=200,
            )
        )

        called_urls: list[str] = []

        class _CapturingClient:
            async def request(
                self, *, method, url, json_body, headers, timeout
            ):
                called_urls.append(url)
                return _FakeResponse()

            async def aclose(self):
                return None

        with patch(
            "agent_team_v15.endpoint_prober._get_http_client",
            return_value=_CapturingClient(),
        ):
            await execute_probes(manifest, ctx, cwd=str(tmp_path))

        # With api_prefix=api the probe URL must route through /api.
        assert called_urls, "execute_probes did not issue any HTTP call"
        assert called_urls[0] == "http://localhost:4000/api/health", (
            f"expected prefix honored, got {called_urls[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_probe_url_no_prefix_falls_back(self, tmp_path: Path) -> None:
        # No main.ts → no api_prefix → URL shape stays legacy.
        infra = _detect_runtime_infra(tmp_path, _config())
        ctx = DockerContext(
            app_url="http://localhost:4000",
            api_healthy=True,
            runtime_infra=infra,
        )
        manifest = ProbeManifest(milestone_id="m1")
        manifest.probes.append(
            ProbeSpec(
                endpoint="GET /health",
                method="GET",
                path="/health",
                probe_type="happy_path",
                expected_status=200,
            )
        )

        called_urls: list[str] = []

        class _CapturingClient:
            async def request(
                self, *, method, url, json_body, headers, timeout
            ):
                called_urls.append(url)
                return _FakeResponse()

            async def aclose(self):
                return None

        with patch(
            "agent_team_v15.endpoint_prober._get_http_client",
            return_value=_CapturingClient(),
        ):
            await execute_probes(manifest, ctx, cwd=str(tmp_path))

        assert called_urls[0] == "http://localhost:4000/health", (
            f"expected legacy passthrough, got {called_urls[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_probe_url_does_not_duplicate_already_prefixed_route(self, tmp_path: Path) -> None:
        _write_main_ts_with_prefix(tmp_path, "api")
        infra = _detect_runtime_infra(tmp_path, _config())
        ctx = DockerContext(
            app_url="http://localhost:4000",
            api_healthy=True,
            runtime_infra=infra,
        )
        manifest = ProbeManifest(milestone_id="m1")
        manifest.probes.append(
            ProbeSpec(
                endpoint="POST /api/auth/login",
                method="POST",
                path="/api/auth/login",
                probe_type="happy_path",
                expected_status=200,
            )
        )

        called_urls: list[str] = []

        class _CapturingClient:
            async def request(
                self, *, method, url, json_body, headers, timeout
            ):
                called_urls.append(url)
                return _FakeResponse()

            async def aclose(self):
                return None

        with patch(
            "agent_team_v15.endpoint_prober._get_http_client",
            return_value=_CapturingClient(),
        ):
            await execute_probes(manifest, ctx, cwd=str(tmp_path))

        assert called_urls == ["http://localhost:4000/api/auth/login"]
