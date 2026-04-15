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


class TestA02PortDefault3001:
    def test_env_validation_defaults_port_to_3001(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        env_validation = tmp_path / "apps" / "api" / "src" / "config" / "env.validation.ts"
        assert env_validation.is_file(), "A-02: env.validation.ts must be scaffolded"
        body = env_validation.read_text(encoding="utf-8")
        # Joi/zod schema for PORT defaults to 3001, not 8080
        assert "3001" in body
        assert "8080" not in body, "A-02: must not default PORT to 8080"

    def test_env_example_pins_port_to_3001(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        env_example = tmp_path / ".env.example"
        assert env_example.is_file(), "A-02: .env.example must be scaffolded"
        body = env_example.read_text(encoding="utf-8")
        assert "PORT=3001" in body
        assert "PORT=8080" not in body

    def test_main_ts_fallback_is_3001(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        assert main_ts.is_file(), "A-02: main.ts must be scaffolded"
        body = main_ts.read_text(encoding="utf-8")
        assert "8080" not in body, "A-02: main.ts fallback must not be 8080"
        assert "3001" in body


class TestA03PrismaShutdownHook:
    def test_prisma_service_avoids_deprecated_on_beforeexit(self, tmp_path: Path) -> None:
        _scaffold_m1(tmp_path)
        prisma_service = tmp_path / "apps" / "api" / "src" / "prisma" / "prisma.service.ts"
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
        prisma_service = tmp_path / "apps" / "api" / "src" / "prisma" / "prisma.service.ts"
        body = prisma_service.read_text(encoding="utf-8")
        assert "OnModuleInit" in body
        assert "this.$connect()" in body


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
