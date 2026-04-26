"""Phase F §7.5 — runtime infrastructure detection tests.

Covers the broader auto-detection contract added in Phase F:
  * NestJS ``setGlobalPrefix`` API prefix
  * ``CORS_ORIGIN`` from .env / .env.example
  * ``DATABASE_URL`` from .env / .env.example
  * JWT ``audience`` from NestJS JwtModule registrations
  * Feature-flag gating (``v18.runtime_infra_detection_enabled``)
  * ``build_probe_url`` honours detected ``api_prefix``.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.infra_detector import (
    RuntimeInfra,
    build_probe_url,
    detect_runtime_infra,
)


def _config(*, enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(runtime_infra_detection_enabled=enabled)
    return cfg


class TestApiPrefixDetection:
    def test_detects_setglobalprefix_single_quote(self, tmp_path: Path) -> None:
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        main_ts.parent.mkdir(parents=True)
        main_ts.write_text(
            dedent(
                """
                import { NestFactory } from '@nestjs/core';
                async function bootstrap() {
                  const app = await NestFactory.create(AppModule);
                  app.setGlobalPrefix('api');
                  await app.listen(4000);
                }
                bootstrap();
                """
            ).strip(),
            encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.api_prefix == "api"
        assert "api_prefix" in infra.sources
        assert infra.sources["api_prefix"].endswith("main.ts")

    def test_detects_setglobalprefix_strips_leading_slash(
        self, tmp_path: Path
    ) -> None:
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        main_ts.parent.mkdir(parents=True)
        main_ts.write_text(
            "app.setGlobalPrefix('/v1/api');\n", encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.api_prefix == "v1/api"

    def test_no_main_ts_empty_prefix(self, tmp_path: Path) -> None:
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.api_prefix == ""


class TestCorsOriginDetection:
    def test_detects_from_api_env_example(self, tmp_path: Path) -> None:
        env = tmp_path / "apps" / "api" / ".env.example"
        env.parent.mkdir(parents=True)
        env.write_text(
            "DATABASE_URL=postgresql://localhost\n"
            "CORS_ORIGIN=http://localhost:3080\n",
            encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.cors_origin == "http://localhost:3080"
        assert infra.sources["cors_origin"].endswith(".env.example")

    def test_top_level_env_overrides_example(self, tmp_path: Path) -> None:
        """Top-level .env takes precedence over apps/api/.env.example."""
        (tmp_path / "apps" / "api").mkdir(parents=True)
        (tmp_path / "apps" / "api" / ".env.example").write_text(
            "CORS_ORIGIN=http://example-default\n", encoding="utf-8",
        )
        (tmp_path / ".env").write_text(
            "CORS_ORIGIN=http://actual-runtime\n", encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.cors_origin == "http://actual-runtime"
        assert infra.sources["cors_origin"].endswith(".env")

    def test_empty_when_unset(self, tmp_path: Path) -> None:
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.cors_origin == ""

    def test_strips_double_quotes(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text('CORS_ORIGIN="http://localhost:3080"\n', encoding="utf-8")
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.cors_origin == "http://localhost:3080"


class TestDatabaseUrlDetection:
    def test_detects_from_env_example(self, tmp_path: Path) -> None:
        env = tmp_path / "apps" / "api" / ".env.example"
        env.parent.mkdir(parents=True)
        env.write_text(
            "DATABASE_URL=postgresql://user:pass@localhost:5432/db\n",
            encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert (
            infra.database_url
            == "postgresql://user:pass@localhost:5432/db"
        )

    def test_empty_when_unset(self, tmp_path: Path) -> None:
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.database_url == ""


class TestJwtAudienceDetection:
    def test_detects_audience_in_module_register(self, tmp_path: Path) -> None:
        mod = tmp_path / "apps" / "api" / "src" / "auth" / "auth.module.ts"
        mod.parent.mkdir(parents=True)
        mod.write_text(
            dedent(
                """
                import { JwtModule } from '@nestjs/jwt';
                @Module({
                  imports: [
                    JwtModule.register({
                      secret: 'shh',
                      signOptions: { expiresIn: '1d' },
                      audience: 'arkan-api',
                    }),
                  ],
                })
                export class AuthModule {}
                """
            ).strip(),
            encoding="utf-8",
        )
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.jwt_audience == "arkan-api"

    def test_empty_when_no_jwt_module(self, tmp_path: Path) -> None:
        infra = detect_runtime_infra(tmp_path, config=_config())
        assert infra.jwt_audience == ""


class TestFeatureFlagGating:
    def test_flag_off_returns_empty_snapshot(self, tmp_path: Path) -> None:
        """Flag off → every field stays empty even when sources exist on disk."""
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        main_ts.parent.mkdir(parents=True)
        main_ts.write_text("app.setGlobalPrefix('api');\n", encoding="utf-8")
        (tmp_path / ".env").write_text(
            "CORS_ORIGIN=http://x\nDATABASE_URL=postgresql://y\n",
            encoding="utf-8",
        )
        cfg = _config(enabled=False)
        infra = detect_runtime_infra(tmp_path, config=cfg)
        assert infra.api_prefix == ""
        assert infra.cors_origin == ""
        assert infra.database_url == ""
        assert infra.jwt_audience == ""

    def test_no_config_uses_defaults(self, tmp_path: Path) -> None:
        """Calling without config reads freely — legacy callers stay working."""
        (tmp_path / ".env").write_text("CORS_ORIGIN=http://x\n", encoding="utf-8")
        infra = detect_runtime_infra(tmp_path, config=None)
        assert infra.cors_origin == "http://x"


class TestBuildProbeUrl:
    def test_no_prefix_passthrough(self) -> None:
        url = build_probe_url("http://localhost:4000", "/health")
        assert url == "http://localhost:4000/health"

    def test_no_prefix_trailing_slash_stripped(self) -> None:
        url = build_probe_url("http://localhost:4000/", "health")
        assert url == "http://localhost:4000/health"

    def test_with_prefix(self) -> None:
        infra = RuntimeInfra(api_prefix="api")
        url = build_probe_url("http://localhost:4000", "/health", infra=infra)
        assert url == "http://localhost:4000/api/health"

    def test_with_prefix_no_double_slashes(self) -> None:
        infra = RuntimeInfra(api_prefix="/api/")
        url = build_probe_url("http://localhost:4000/", "/health", infra=infra)
        assert url == "http://localhost:4000/api/health"

    def test_with_prefix_does_not_duplicate_already_prefixed_route(self) -> None:
        infra = RuntimeInfra(api_prefix="api")
        url = build_probe_url("http://localhost:4000", "/api/auth/login", infra=infra)
        assert url == "http://localhost:4000/api/auth/login"

    def test_with_empty_route(self) -> None:
        infra = RuntimeInfra(api_prefix="api")
        url = build_probe_url("http://localhost:4000", "", infra=infra)
        assert url == "http://localhost:4000/api"


class TestRuntimeInfraSerialization:
    def test_to_dict_has_all_fields(self, tmp_path: Path) -> None:
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        main_ts.parent.mkdir(parents=True)
        main_ts.write_text("app.setGlobalPrefix('api');\n", encoding="utf-8")
        infra = detect_runtime_infra(tmp_path, config=_config())
        data = infra.to_dict()
        for key in (
            "app_url",
            "api_prefix",
            "cors_origin",
            "database_url",
            "jwt_audience",
            "sources",
        ):
            assert key in data
