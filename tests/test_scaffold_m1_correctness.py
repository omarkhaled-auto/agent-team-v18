"""M1 scaffold correctness — tracker IDs A-01, A-02, A-03, A-04, A-07, A-08, D-18.

Static file-content assertions only. No npm install / docker compose up / npx.
See docs/plans/2026-04-16-session-02-execute-scaffold-cluster.md Phase 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_team_v15.scaffold_runner import run_scaffolding


def _write_ir(tmp_path: Path, *, locales: list[str] | None = None) -> Path:
    locales_value = ["en", "ar"] if locales is None else list(locales)
    ir = {
        "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
        "entities": [],
        "i18n": {"locales": locales_value},
    }
    path = tmp_path / "product.ir.json"
    path.write_text(json.dumps(ir), encoding="utf-8")
    return path


def _scaffold_m1(tmp_path: Path, *, locales: list[str] | None = None) -> None:
    ir_path = _write_ir(tmp_path, locales=locales)
    run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"])


class TestA01DockerCompose:
    def test_docker_compose_yaml_emitted(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        dc = tmp_path / "docker-compose.yml"
        assert dc.is_file(), "A-01: docker-compose.yml must be emitted at project root"
        parsed = yaml.safe_load(dc.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)
        postgres = parsed["services"]["postgres"]
        assert str(postgres["image"]).startswith("postgres:")
        assert "5432:5432" in [str(p) for p in postgres["ports"]]
        volumes = postgres["volumes"]
        assert volumes, "A-01: postgres service must declare volumes"
        assert any("postgres_data" in str(v) for v in volumes), (
            "A-01: postgres service must reference a named volume"
        )
        assert "postgres_data" in (parsed.get("volumes") or {}), (
            "A-01: top-level named volume 'postgres_data' must be declared"
        )
        healthcheck = postgres["healthcheck"]
        assert healthcheck, "A-01: postgres service must declare healthcheck"
        test_cmd = " ".join(str(part) for part in healthcheck["test"])
        assert "pg_isready" in test_cmd


class TestN07DockerComposeFullTopology:
    """N-07 (DRIFT-5): compose emits postgres + api + web with service_healthy wiring."""

    def test_compose_has_three_services(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        parsed = yaml.safe_load((tmp_path / "docker-compose.yml").read_text(encoding="utf-8"))
        assert set(parsed["services"].keys()) == {"postgres", "api", "web"}

    def test_compose_omits_obsolete_version_key(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        parsed = yaml.safe_load((tmp_path / "docker-compose.yml").read_text(encoding="utf-8"))
        assert "version" not in parsed, (
            "N-07: compose v2+ omits the obsolete top-level `version:` key"
        )

    def test_api_service_healthcheck_and_port_4000(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        parsed = yaml.safe_load((tmp_path / "docker-compose.yml").read_text(encoding="utf-8"))
        api = parsed["services"]["api"]
        assert "4000:4000" in [str(p) for p in api["ports"]]
        assert api["environment"]["PORT"] == "4000"
        assert api["build"]["context"] == "./apps/api"
        test_cmd = " ".join(str(part) for part in api["healthcheck"]["test"])
        assert "curl -f http://localhost:4000/api/health" in test_cmd

    def test_api_depends_on_postgres_service_healthy(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        parsed = yaml.safe_load((tmp_path / "docker-compose.yml").read_text(encoding="utf-8"))
        api = parsed["services"]["api"]
        assert api["depends_on"]["postgres"]["condition"] == "service_healthy", (
            "N-07: api must gate on postgres health via long-form depends_on"
        )

    def test_web_depends_on_api_service_healthy(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        parsed = yaml.safe_load((tmp_path / "docker-compose.yml").read_text(encoding="utf-8"))
        web = parsed["services"]["web"]
        assert web["depends_on"]["api"]["condition"] == "service_healthy", (
            "N-07: web must gate on api health via long-form depends_on"
        )
        assert web["environment"]["NEXT_PUBLIC_API_URL"] == "http://localhost:4000/api"
        assert web["environment"]["INTERNAL_API_URL"] == "http://api:4000/api"


class TestA02PortDefault4000:
    """N-12/Phase-B: canonical M1 PORT is 4000 (matches DEFAULT_SCAFFOLD_CONFIG
    and docker-compose services.api). Prior revision pinned 3001."""

    def test_env_validation_defaults_port_to_4000(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        env_validation = tmp_path / "apps" / "api" / "src" / "config" / "env.validation.ts"
        assert env_validation.is_file(), "A-02: env.validation.ts must be scaffolded"
        body = env_validation.read_text(encoding="utf-8")
        assert "4000" in body
        assert "8080" not in body, "A-02: must not default PORT to 8080"

    def test_env_example_pins_port_to_4000(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        env_example = tmp_path / ".env.example"
        assert env_example.is_file(), "A-02: .env.example must be scaffolded"
        body = env_example.read_text(encoding="utf-8")
        assert "PORT=4000" in body
        assert "PORT=8080" not in body

    def test_main_ts_fallback_is_4000(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        assert main_ts.is_file(), "A-02: main.ts must be scaffolded"
        body = main_ts.read_text(encoding="utf-8")
        assert "8080" not in body, "A-02: main.ts fallback must not be 8080"
        assert "4000" in body


class TestA03PrismaShutdownHook:
    def test_prisma_service_avoids_deprecated_on_beforeexit(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        prisma_service = tmp_path / "apps" / "api" / "src" / "database" / "prisma.service.ts"
        assert prisma_service.is_file(), "A-03: prisma.service.ts must be scaffolded"
        body = prisma_service.read_text(encoding="utf-8")
        assert "$on('beforeExit'" not in body, (
            "A-03: deprecated Prisma $on('beforeExit') pattern must not appear"
        )
        assert '$on("beforeExit"' not in body
        # uses process.on('beforeExit', ...) per Prisma 5+ guidance
        assert (
            "process.on('beforeExit'" in body
            or 'process.on("beforeExit"' in body
        ), "A-03: must register shutdown hook via process.on('beforeExit', ...)"

    def test_prisma_service_implements_onmoduleinit(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        prisma_service = tmp_path / "apps" / "api" / "src" / "database" / "prisma.service.ts"
        body = prisma_service.read_text(encoding="utf-8")
        assert "OnModuleInit" in body
        assert "this.$connect()" in body


def _scaffold_m1_backend_only(tmp_path: Path) -> None:
    """NestJS-only IR for N-04/N-05 tests — scopes runs to backend emission.

    The Prisma path + migration stub changes live entirely in
    `_scaffold_api_foundation`; driving this with a backend-only IR keeps the
    tests independent of in-flight `_scaffold_web_foundation` work.
    """
    ir = {
        "stack_target": {"backend": "NestJS"},
        "entities": [],
        "i18n": {"locales": []},
    }
    ir_path = tmp_path / "product.ir.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"], stack_target="NestJS")


class TestN04N05PrismaPathAndMigrations:
    """N-04 (src/database path) + N-05 (schema.prisma + migration stub)."""

    def test_prisma_module_and_service_emitted_at_src_database(self, tmp_path: Path) -> None:
        _scaffold_m1_backend_only(tmp_path)
        db_dir = tmp_path / "apps" / "api" / "src" / "database"
        assert (db_dir / "prisma.service.ts").is_file(), (
            "N-04 / DRIFT-1: prisma.service.ts must land at src/database/"
        )
        assert (db_dir / "prisma.module.ts").is_file(), (
            "N-04 / DRIFT-1: prisma.module.ts must land at src/database/"
        )
        # Old src/prisma path must NOT be emitted by scaffold (N-04 canonical fix).
        old_path = tmp_path / "apps" / "api" / "src" / "prisma"
        assert not old_path.exists(), (
            "N-04: scaffold must not emit legacy src/prisma/ path"
        )

    def test_schema_prisma_bootstrap_emitted(self, tmp_path: Path) -> None:
        _scaffold_m1_backend_only(tmp_path)
        schema = tmp_path / "apps" / "api" / "prisma" / "schema.prisma"
        assert schema.is_file(), "N-05: schema.prisma bootstrap must be scaffolded"
        body = schema.read_text(encoding="utf-8")
        assert 'provider = "postgresql"' in body, (
            "N-05: datasource provider must be postgresql (not postgres)"
        )
        assert 'provider = "prisma-client-js"' in body, (
            "N-05: generator client provider must be prisma-client-js"
        )
        assert 'url      = env("DATABASE_URL")' in body

    def test_initial_migration_stub_emitted(self, tmp_path: Path) -> None:
        _scaffold_m1_backend_only(tmp_path)
        mig_dir = tmp_path / "apps" / "api" / "prisma" / "migrations" / "20260101000000_init"
        assert mig_dir.is_dir(), "N-05: initial migration directory must exist"
        assert (mig_dir / "migration.sql").is_file(), (
            "N-05: initial migration.sql stub must be scaffolded"
        )

    def test_migration_lock_toml_canonical_format(self, tmp_path: Path) -> None:
        _scaffold_m1_backend_only(tmp_path)
        lock = tmp_path / "apps" / "api" / "prisma" / "migrations" / "migration_lock.toml"
        assert lock.is_file(), "N-05: migration_lock.toml must be scaffolded"
        body = lock.read_text(encoding="utf-8")
        assert 'provider = "postgresql"' in body, (
            "N-05: migration_lock.toml provider must match schema.prisma datasource"
        )


class TestA04I18nLocales:
    def test_locales_filtered_to_en_and_ar_when_upstream_has_extras(
        self, tmp_path: Path
    ) -> None:
        _scaffold_m1(tmp_path, locales=["en", "ar", "id"])
        messages_dir = tmp_path / "apps" / "web" / "messages"
        assert messages_dir.is_dir()
        locale_dirs = sorted(p.name for p in messages_dir.iterdir() if p.is_dir())
        assert locale_dirs == ["ar", "en"], (
            f"A-04: upstream locales must be filtered to en+ar, got {locale_dirs}"
        )

    def test_locales_en_ar_baseline(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path, locales=["en", "ar"])
        messages_dir = tmp_path / "apps" / "web" / "messages"
        locale_dirs = sorted(p.name for p in messages_dir.iterdir() if p.is_dir())
        assert locale_dirs == ["ar", "en"]

    def test_locale_namespace_files_are_empty_json_objects(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        for locale in ("en", "ar"):
            ns = tmp_path / "apps" / "web" / "messages" / locale / "f-001.json"
            assert ns.is_file()
            assert json.loads(ns.read_text(encoding="utf-8")) == {}


class TestA07VitestScaffold:
    def test_web_package_json_has_vitest_devdeps(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        pkg = tmp_path / "apps" / "web" / "package.json"
        assert pkg.is_file(), "A-07: apps/web/package.json must be scaffolded"
        data = json.loads(pkg.read_text(encoding="utf-8"))
        dev_deps = data.get("devDependencies", {})
        for required in (
            "vitest",
            "@testing-library/react",
            "@testing-library/jest-dom",
            "jsdom",
        ):
            assert required in dev_deps, f"A-07: {required} missing from web devDependencies"

    def test_vitest_config_emitted(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        vitest_cfg = tmp_path / "apps" / "web" / "vitest.config.ts"
        assert vitest_cfg.is_file(), "A-07: vitest.config.ts must be scaffolded"
        body = vitest_cfg.read_text(encoding="utf-8")
        assert "jsdom" in body

    def test_root_package_json_has_test_web_script(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        root_pkg = tmp_path / "package.json"
        assert root_pkg.is_file(), "A-07: root package.json must be scaffolded"
        data = json.loads(root_pkg.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        assert "test:web" in scripts
        assert "vitest" in scripts["test:web"] or "test" in scripts["test:web"]


class TestA08GitignoreAndEnv:
    def test_gitignore_present_with_required_entries(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.is_file(), "A-08: .gitignore must be scaffolded at project root"
        body = gi.read_text(encoding="utf-8")
        for required in (
            "node_modules/",
            ".next/",
            "dist/",
            ".env",
            ".env.local",
            "coverage/",
            ".turbo/",
            "apps/*/node_modules/",
            "apps/*/dist/",
        ):
            assert required in body, f"A-08: .gitignore missing '{required}'"

    def test_no_env_file_committed(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        assert not (tmp_path / ".env").exists(), "A-08: must not emit .env (only .env.example)"

    def test_env_example_committed(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        assert (tmp_path / ".env.example").is_file()


class TestD18NonVulnerablePins:
    """Static pin floors — avoid known-vulnerable-range versions in scaffold templates."""

    @pytest.mark.parametrize(
        "file_rel,name,min_major_minor",
        [
            ("apps/web/package.json", "next", (15, 1)),
            ("apps/api/package.json", "@nestjs/core", (11, 0)),
            ("apps/api/package.json", "prisma", (6, 0)),
            ("apps/api/package.json", "@prisma/client", (6, 0)),
        ],
    )
    def test_pin_floor(
        self,
        tmp_path: Path,
        file_rel: str,
        name: str,
        min_major_minor: tuple[int, int],
    ) -> None:
        _scaffold_m1(tmp_path)
        pkg_path = tmp_path / file_rel
        assert pkg_path.is_file()
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        assert name in deps, f"D-18: expected {name} in {file_rel}"
        spec = deps[name].lstrip("^~>=< ")
        parts = spec.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        assert (major, minor) >= min_major_minor, (
            f"D-18: {name} pinned to {spec}; floor is {min_major_minor[0]}.{min_major_minor[1]}"
        )


class TestN06WebScaffoldCompleteness:
    """N-06 / DRIFT-6: apps/web scaffold emits the full 15-file contract.

    Verifies each of the 10 new N-06 emissions exists with the expected
    structural shape (not byte-identical). Also covers AUD-022 (vitest
    setupFiles wired) and the new hey-api package.json entries.
    """

    def test_next_config_emitted_minimal(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "next.config.mjs"
        assert path.is_file(), "N-06: apps/web/next.config.mjs must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "export default" in body
        assert "NextConfig" in body or "nextConfig" in body

    def test_web_tsconfig_extends_base(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "tsconfig.json"
        assert path.is_file(), "N-06: apps/web/tsconfig.json must be emitted"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["extends"] == "../../tsconfig.base.json"
        assert data["compilerOptions"]["jsx"] == "preserve"
        paths = data["compilerOptions"]["paths"]
        assert "@/*" in paths
        assert "@taskflow/shared" in paths

    def test_postcss_config_plugins(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "postcss.config.mjs"
        assert path.is_file(), "N-06: apps/web/postcss.config.mjs must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "tailwindcss" in body
        assert "autoprefixer" in body
        assert "export default" in body

    def test_openapi_ts_config_has_hey_api_plugins(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "openapi-ts.config.ts"
        assert path.is_file(), "N-06: apps/web/openapi-ts.config.ts must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "defineConfig" in body
        assert "'../api/openapi.json'" in body
        assert "'src/lib/api/generated'" in body
        for plugin in ("@hey-api/typescript", "@hey-api/sdk", "@hey-api/client-fetch"):
            assert f"'{plugin}'" in body, f"N-06: missing plugin {plugin}"

    def test_env_example_canonical_port_4000(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / ".env.example"
        assert path.is_file(), "N-06: apps/web/.env.example must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "NEXT_PUBLIC_API_URL=http://localhost:4000/api" in body
        assert "INTERNAL_API_URL=http://api:4000/api" in body
        assert "3001" not in body, "DRIFT-3: canonical port is 4000, not 3001"

    def test_web_dockerfile_multistage(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "Dockerfile"
        assert path.is_file(), "N-06: apps/web/Dockerfile must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "FROM node:20-alpine AS base" in body
        assert "AS deps" in body
        assert "AS build" in body
        assert "AS runner" in body
        assert "EXPOSE 3000" in body
        assert "next build" in body

    def test_layout_stub_is_valid_nextjs_root(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "src" / "app" / "layout.tsx"
        assert path.is_file(), "N-06: apps/web/src/app/layout.tsx stub must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "SCAFFOLD STUB" in body
        assert "export default function RootLayout" in body
        assert "<html" in body and "<body>" in body

    def test_page_stub_is_default_export(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "src" / "app" / "page.tsx"
        assert path.is_file(), "N-06: apps/web/src/app/page.tsx stub must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "SCAFFOLD STUB" in body
        assert "export default function" in body

    def test_middleware_stub_uses_nextrequest(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        path = tmp_path / "apps" / "web" / "src" / "middleware.ts"
        assert path.is_file(), "N-06: apps/web/src/middleware.ts stub must be emitted"
        body = path.read_text(encoding="utf-8")
        assert "SCAFFOLD STUB" in body
        assert "NextRequest" in body
        assert "NextResponse.next()" in body
        assert "export const config" in body

    def test_aud_022_vitest_setup_wired(self, tmp_path: Path) -> None:
        """AUD-022: vitest.config.ts setupFiles matches the emitted setup.ts path."""
        _scaffold_m1(tmp_path)
        setup = tmp_path / "apps" / "web" / "src" / "test" / "setup.ts"
        assert setup.is_file(), "AUD-022: src/test/setup.ts must be emitted"
        assert "@testing-library/jest-dom" in setup.read_text(encoding="utf-8")
        vitest_cfg = tmp_path / "apps" / "web" / "vitest.config.ts"
        body = vitest_cfg.read_text(encoding="utf-8")
        assert "setupFiles" in body, "AUD-022: vitest.config.ts must declare setupFiles"
        assert "'./src/test/setup.ts'" in body, (
            "AUD-022: setupFiles must reference the emitted setup.ts path"
        )

    def test_web_package_json_has_hey_api_deps(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        pkg = tmp_path / "apps" / "web" / "package.json"
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert "@hey-api/client-fetch" in data.get("dependencies", {}), (
            "N-06: @hey-api/client-fetch must be a runtime dependency"
        )
        assert "@hey-api/openapi-ts" in data.get("devDependencies", {}), (
            "N-06: @hey-api/openapi-ts must be a devDependency"
        )
