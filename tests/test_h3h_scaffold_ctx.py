from __future__ import annotations

import json

import yaml

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.scaffold_runner import (
    _docker_compose_template,
    _docker_compose_template_with_web_root_context,
    run_scaffolding,
)


def _write_ir(project_root, *, stack: dict[str, str] | None = None):
    ir_path = project_root / "product.ir.json"
    ir_path.write_text(
        json.dumps(
            {
                "stack_target": stack or {"backend": "NestJS", "frontend": "Next.js"},
                "entities": [],
                "i18n": {"locales": ["en"]},
            }
        ),
        encoding="utf-8",
    )
    return ir_path


def _config(enabled: bool) -> AgentTeamConfig:
    return AgentTeamConfig(
        v18=V18Config(scaffold_web_dockerfile_context_fix_enabled=enabled)
    )


def test_docker_compose_template_uses_repo_root_context_by_default() -> None:
    """Path A (Issue #14) refactor: DOCK-001 fix is now unconditional.

    Pre-Path-A, the default template shipped ``context: ./apps/web`` (bug)
    and ``_docker_compose_template_with_web_root_context`` was the
    flag-gated fix. Path A renders every compose through the curated
    template package, which honors DOCK-001 without gating, so the two
    entrypoints now produce identical (fixed) output.
    """
    text = _docker_compose_template()

    assert "context: ." in text
    assert "dockerfile: apps/web/Dockerfile" in text
    assert "dockerfile: apps/api/Dockerfile" in text
    # The legacy bug patterns must NOT appear.
    assert "context: ./apps/web" not in text
    assert "context: ./apps/api" not in text


def test_docker_compose_template_with_web_root_context_matches_default() -> None:
    """Post-Path-A: the flag-on shim is identical to the default output.

    The ``scaffold_web_dockerfile_context_fix_enabled`` flag becomes a
    no-op after Path A — kept only for backward-compat call sites.
    """
    assert _docker_compose_template_with_web_root_context() == _docker_compose_template()


def test_run_scaffolding_writes_fixed_web_build_context_and_preserves_dockerfile(
    tmp_path,
) -> None:
    on_root = tmp_path / "flag-on"
    off_root = tmp_path / "flag-off"
    on_root.mkdir()
    off_root.mkdir()

    created = run_scaffolding(
        _write_ir(on_root),
        on_root,
        "milestone-1",
        ["F-001"],
        config=_config(True),
    )
    run_scaffolding(
        _write_ir(off_root),
        off_root,
        "milestone-1",
        ["F-001"],
        config=_config(False),
    )

    assert "docker-compose.yml" in created
    compose = yaml.safe_load((on_root / "docker-compose.yml").read_text(encoding="utf-8"))
    web_build = compose["services"]["web"]["build"]
    assert web_build["context"] == "."
    assert web_build["dockerfile"] == "apps/web/Dockerfile"

    dockerfile_on = (on_root / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    dockerfile_off = (off_root / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile_on == dockerfile_off
    assert "COPY packages/shared/package.json packages/shared/" in dockerfile_on


def test_run_scaffolding_preserves_existing_docker_compose(tmp_path) -> None:
    existing = (
        "services:\n"
        "  sentinel:\n"
        "    image: busybox\n"
    )
    (tmp_path / "docker-compose.yml").write_text(existing, encoding="utf-8")

    run_scaffolding(
        _write_ir(tmp_path),
        tmp_path,
        "milestone-1",
        ["F-001"],
        config=_config(True),
    )

    assert (tmp_path / "docker-compose.yml").read_text(encoding="utf-8") == existing
