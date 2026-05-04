"""Unit tests for agent_team_v15.template_renderer (Issue #14)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15.stack_contract import StackContract
from agent_team_v15.template_renderer import (
    RenderedTemplate,
    TemplateNotFoundError,
    TemplateRenderError,
    TemplateSlotValues,
    derive_slots_from_stack_contract,
    drop_template,
    render_template,
    stack_matches_template,
)


def _find(files: dict[Path, str], needle: str) -> tuple[Path, str]:
    for path, content in files.items():
        if needle in str(path):
            return path, content
    raise AssertionError(f"no file with {needle!r} in {sorted(str(p) for p in files)}")


class TestRenderDefaults:
    def test_renders_declared_files(self) -> None:
        rendered = render_template("pnpm_monorepo")
        paths = {str(p).replace("\\", "/") for p in rendered.files}
        assert "apps/api/Dockerfile" in paths
        assert ".dockerignore" in paths

    def test_template_metadata(self) -> None:
        rendered = render_template("pnpm_monorepo")
        assert rendered.template_name == "pnpm_monorepo"
        # v2.0.0 = Path A consolidation (web Dockerfile + compose added).
        assert rendered.template_version == "2.0.0"

    def test_all_four_files_rendered(self) -> None:
        rendered = render_template("pnpm_monorepo")
        paths = {str(p).replace("\\", "/") for p in rendered.files}
        assert paths == {
            "apps/api/Dockerfile",
            "apps/web/Dockerfile",
            "docker-compose.yml",
            ".dockerignore",
        }

    def test_no_leftover_placeholders(self) -> None:
        rendered = render_template("pnpm_monorepo")
        for path, content in rendered.files.items():
            assert "{{" not in content, f"leftover '{{{{' in {path}: {content[:120]}"
            assert "}}" not in content, f"leftover '}}}}' in {path}"

    def test_no_copy_escape(self) -> None:
        rendered = render_template("pnpm_monorepo")
        _, dockerfile = _find(rendered.files, "Dockerfile")
        for line in dockerfile.splitlines():
            if line.strip().startswith(("COPY", "ADD")):
                assert "../" not in line, f"COPY escape detected: {line!r}"

    def test_workdir_after_copy(self) -> None:
        """DOCK-006: every WORKDIR must be preceded by a COPY that populates it,
        OR land in a directory that an earlier COPY/WORKDIR already created.

        We check the specific trap: WORKDIR /app/apps/<name> must come after
        a COPY whose destination is /app/apps/<name>/ or an implicit /app
        + `COPY apps/<name>` pattern. Our template uses
        `COPY . .` then `WORKDIR /app/apps/api` so this passes.
        """
        rendered = render_template("pnpm_monorepo")
        _, dockerfile = _find(rendered.files, "Dockerfile")
        lines = dockerfile.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("WORKDIR ") and stripped != "WORKDIR /app":
                prior = "\n".join(lines[:i])
                assert "COPY" in prior, f"WORKDIR without prior COPY: {stripped}"

    def test_deps_stages_copy_api_client_manifest_before_frozen_install(self) -> None:
        rendered = render_template("pnpm_monorepo")
        for rel in ("apps/web/Dockerfile", "apps/api/Dockerfile"):
            dockerfile = rendered.files[Path(rel)]
            lines = [line.strip() for line in dockerfile.splitlines()]
            copy_line = "COPY packages/api-client/package.json packages/api-client/"
            install_line = "RUN pnpm install --frozen-lockfile"
            assert copy_line in lines, (
                f"{rel} deps stage must copy packages/api-client/package.json "
                "before frozen install"
            )
            assert lines.index(copy_line) < lines.index(install_line), (
                f"{rel} copies api-client manifest after pnpm install"
            )


class TestRenderCustomSlots:
    def test_custom_api_port(self) -> None:
        rendered = render_template(
            "pnpm_monorepo",
            TemplateSlotValues(api_port=5555),
        )
        dockerfile = rendered.files[Path("apps/api/Dockerfile")]
        assert "EXPOSE 5555" in dockerfile

    def test_custom_service_name(self) -> None:
        rendered = render_template(
            "pnpm_monorepo",
            TemplateSlotValues(api_service_name="backend"),
        )
        dockerfile = rendered.files[Path("apps/api/Dockerfile")]
        assert "/app/apps/backend" in dockerfile
        assert "/app/apps/api" not in dockerfile

    def test_custom_node_version(self) -> None:
        rendered = render_template(
            "pnpm_monorepo",
            TemplateSlotValues(node_version="22-alpine"),
        )
        _, dockerfile = _find(rendered.files, "Dockerfile")
        assert "FROM node:22-alpine" in dockerfile


class TestSlotValidation:
    @pytest.mark.parametrize("bad_port", [-1, 0, 70000])
    def test_invalid_port_rejected(self, bad_port: int) -> None:
        with pytest.raises(TemplateRenderError, match="port"):
            TemplateSlotValues(api_port=bad_port)

    @pytest.mark.parametrize("bad_name", ["", "API", "1bad", "has space"])
    def test_invalid_service_name_rejected(self, bad_name: str) -> None:
        with pytest.raises(TemplateRenderError, match="a-z"):
            TemplateSlotValues(api_service_name=bad_name)

    def test_empty_version_rejected(self) -> None:
        with pytest.raises(TemplateRenderError, match="non-empty"):
            TemplateSlotValues(node_version="")


class TestTemplateNotFound:
    def test_unknown_template_raises(self) -> None:
        with pytest.raises(TemplateNotFoundError):
            render_template("does_not_exist")


class TestDeriveSlots:
    def test_from_dict_with_ports(self) -> None:
        slots = derive_slots_from_stack_contract({
            "backend_framework": "nestjs",
            "api_port": 4001,
            "web_port": 3002,
        })
        assert slots.api_port == 4001
        assert slots.web_port == 3002

    def test_from_stackcontract_object(self) -> None:
        sc = StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            api_port=4002,
        )
        slots = derive_slots_from_stack_contract(sc)
        assert slots.api_port == 4002

    def test_none_returns_defaults(self) -> None:
        slots = derive_slots_from_stack_contract(None)
        assert slots.api_port == TemplateSlotValues().api_port

    def test_invalid_port_falls_back_to_default(self) -> None:
        slots = derive_slots_from_stack_contract({"api_port": -5})
        assert slots.api_port == TemplateSlotValues().api_port


class TestDropTemplate:
    def test_writes_expected_files(self, tmp_path: Path) -> None:
        rendered = render_template("pnpm_monorepo")
        written = drop_template(rendered, tmp_path)
        rel = {p.relative_to(tmp_path).as_posix() for p in written}
        assert "apps/api/Dockerfile" in rel
        assert ".dockerignore" in rel

    def test_overwrite_false_skips_existing(self, tmp_path: Path) -> None:
        rendered = render_template("pnpm_monorepo")
        drop_template(rendered, tmp_path)
        # Mutate one file
        target = tmp_path / "apps/api/Dockerfile"
        original = target.read_text(encoding="utf-8")
        target.write_text("# HAND-EDITED\n", encoding="utf-8")
        # Second drop with default overwrite=False must NOT clobber
        written = drop_template(rendered, tmp_path, overwrite=False)
        assert all(
            p.relative_to(tmp_path).as_posix() != "apps/api/Dockerfile"
            for p in written
        ), "apps/api/Dockerfile was clobbered with overwrite=False"
        assert target.read_text(encoding="utf-8") == "# HAND-EDITED\n"

    def test_overwrite_true_clobbers(self, tmp_path: Path) -> None:
        rendered = render_template("pnpm_monorepo")
        target = tmp_path / "apps/api/Dockerfile"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# STALE\n", encoding="utf-8")
        written = drop_template(rendered, tmp_path, overwrite=True)
        assert any(
            p.relative_to(tmp_path).as_posix() == "apps/api/Dockerfile"
            for p in written
        )
        assert "STALE" not in target.read_text(encoding="utf-8")


class TestStackMatches:
    def test_nestjs_nextjs_pnpm_matches(self) -> None:
        assert stack_matches_template(
            {
                "backend_framework": "nestjs",
                "frontend_framework": "nextjs",
                "package_manager": "pnpm",
            },
            "pnpm_monorepo",
        )

    def test_nestjs_nextjs_without_pnpm_does_not_match(self) -> None:
        # Path A gate: package_manager="pnpm" is required. Empty / other pm
        # means "unknown or different", so we must not drop a pnpm template
        # into a non-pnpm stack.
        assert not stack_matches_template(
            {"backend_framework": "nestjs", "frontend_framework": "nextjs"},
            "pnpm_monorepo",
        )
        assert not stack_matches_template(
            {
                "backend_framework": "nestjs",
                "frontend_framework": "nextjs",
                "package_manager": "npm",
            },
            "pnpm_monorepo",
        )

    def test_django_does_not_match(self) -> None:
        assert not stack_matches_template(
            {"backend_framework": "django", "frontend_framework": "react"},
            "pnpm_monorepo",
        )

    def test_none_does_not_match(self) -> None:
        assert not stack_matches_template(None, "pnpm_monorepo")

    def test_unknown_template_returns_false(self) -> None:
        assert not stack_matches_template(
            {"backend_framework": "nestjs"},
            "does_not_exist",
        )
