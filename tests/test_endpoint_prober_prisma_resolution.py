from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_team_v15 import endpoint_prober


def test_prisma_command_prefers_workspace_local_cmd_on_windows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bin_dir = tmp_path / "apps" / "api" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    prisma_cmd = bin_dir / "prisma.CMD"
    prisma_cmd.write_text("@echo off\n", encoding="utf-8")
    schema = tmp_path / "prisma" / "schema.prisma"
    schema.parent.mkdir()
    schema.write_text("datasource db { provider = \"postgresql\" url = env(\"DATABASE_URL\") }\n", encoding="utf-8")

    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(endpoint_prober.os, "name", "nt")
    monkeypatch.setattr(endpoint_prober, "_run_sync", fake_run)

    result = endpoint_prober._run_prisma_command(
        tmp_path,
        ["migrate", "reset", "--force", "--skip-seed"],
        schema=schema,
    )

    assert result.returncode == 0
    assert [str(part).lower() for part in seen["cmd"]] == [
        str(prisma_cmd).lower(),
        "migrate",
        "reset",
        "--force",
        "--skip-seed",
        "--schema",
        str(schema).lower(),
    ]
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert seen["kwargs"]["timeout"] == 120


def test_prisma_command_falls_back_to_npx_when_no_local_bin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(endpoint_prober, "_run_sync", fake_run)

    endpoint_prober._run_prisma_command(tmp_path, ["db", "seed"])

    assert seen["cmd"] == ["npx", "prisma", "db", "seed"]


@pytest.mark.asyncio
async def test_reset_db_prefers_compose_reset_over_host_prisma(
    tmp_path: Path,
    monkeypatch,
) -> None:
    schema = tmp_path / "prisma" / "schema.prisma"
    schema.parent.mkdir()
    schema.write_text("datasource db { provider = \"postgresql\" url = env(\"DATABASE_URL\") }\n", encoding="utf-8")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    calls: list[str] = []

    async def fake_truncate(project_root: Path, compose_file: Path) -> bool:
        calls.append(f"truncate:{compose_file.name}")
        return True

    def fake_migrations(project_root: Path, compose_file: Path):
        calls.append(f"migrate:{compose_file.name}")
        return True, ""

    def fake_seed(project_root: Path) -> bool:
        calls.append("seed")
        return True

    def fail_host_prisma(*args, **kwargs):
        raise AssertionError("host prisma reset should not run when compose exists")

    monkeypatch.setattr(endpoint_prober, "_truncate_tables", fake_truncate)
    monkeypatch.setattr(endpoint_prober, "run_migrations", fake_migrations)
    monkeypatch.setattr(endpoint_prober, "_run_seed", fake_seed)
    monkeypatch.setattr(endpoint_prober, "_run_prisma_command", fail_host_prisma)

    assert await endpoint_prober.reset_db_and_seed(str(tmp_path)) is True
    assert calls == ["truncate:docker-compose.yml", "migrate:docker-compose.yml", "seed"]
