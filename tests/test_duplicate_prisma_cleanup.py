"""NEW-1 duplicate Prisma cleanup — tests for
``wave_executor._maybe_cleanup_duplicate_prisma``.

Covers the 4 scenarios specified in the Wave 3 team-lead brief:

1. flag-OFF skips cleanup (stale dir persists);
2. flag-ON with both dirs populated removes ``apps/api/src/prisma/``;
3. flag-ON with only ``apps/api/src/database/`` populated is a no-op;
4. flag-ON with only ``apps/api/src/prisma/`` populated is a SAFETY no-op
   (canonical missing → never remove).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.wave_executor import _maybe_cleanup_duplicate_prisma


def _config(*, enabled: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(duplicate_prisma_cleanup_enabled=enabled)
    return cfg


def _write_canonical(workspace: Path) -> None:
    database_dir = workspace / "apps" / "api" / "src" / "database"
    database_dir.mkdir(parents=True, exist_ok=True)
    (database_dir / "prisma.module.ts").write_text(
        "// canonical module stub\nexport class PrismaModule {}\n",
        encoding="utf-8",
    )
    (database_dir / "prisma.service.ts").write_text(
        "// canonical service stub\nexport class PrismaService {}\n",
        encoding="utf-8",
    )


def _write_stale(workspace: Path) -> None:
    stale_dir = workspace / "apps" / "api" / "src" / "prisma"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "prisma.module.ts").write_text(
        "// stale module\nexport class PrismaModule {}\n",
        encoding="utf-8",
    )
    (stale_dir / "prisma.service.ts").write_text(
        "// stale service\nexport class PrismaService {}\n",
        encoding="utf-8",
    )


class TestDuplicatePrismaCleanupFlagOff:
    def test_flag_off_skips_cleanup(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        _write_stale(tmp_path)
        cfg = _config(enabled=False)

        removed = _maybe_cleanup_duplicate_prisma(cwd=str(tmp_path), config=cfg)

        assert removed == []
        stale_dir = tmp_path / "apps" / "api" / "src" / "prisma"
        assert stale_dir.exists(), "stale directory must persist when flag is OFF"
        assert (stale_dir / "prisma.module.ts").is_file()


class TestDuplicatePrismaCleanupBothPopulated:
    def test_flag_on_both_populated_removes_stale(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        _write_stale(tmp_path)
        cfg = _config(enabled=True)

        removed = _maybe_cleanup_duplicate_prisma(cwd=str(tmp_path), config=cfg)

        stale_dir = tmp_path / "apps" / "api" / "src" / "prisma"
        canonical_dir = tmp_path / "apps" / "api" / "src" / "database"
        assert not stale_dir.exists(), "stale dir must be removed"
        assert canonical_dir.is_dir(), "canonical dir must be preserved"
        assert (canonical_dir / "prisma.module.ts").is_file()
        assert (canonical_dir / "prisma.service.ts").is_file()

        # Removed list enumerates the stale files (relative, POSIX).
        assert any(p.endswith("apps/api/src/prisma/prisma.module.ts") for p in removed)
        assert any(p.endswith("apps/api/src/prisma/prisma.service.ts") for p in removed)


class TestDuplicatePrismaCleanupOnlyCanonical:
    def test_flag_on_only_canonical_no_op(self, tmp_path: Path) -> None:
        _write_canonical(tmp_path)
        cfg = _config(enabled=True)

        removed = _maybe_cleanup_duplicate_prisma(cwd=str(tmp_path), config=cfg)

        assert removed == []
        canonical_dir = tmp_path / "apps" / "api" / "src" / "database"
        assert canonical_dir.is_dir(), "canonical dir must be preserved"


class TestDuplicatePrismaCleanupOnlyStale:
    def test_flag_on_only_stale_safety_no_op(self, tmp_path: Path) -> None:
        """SAFETY: canonical missing → NEVER remove the stale tree.

        If ``src/database/`` is not populated (or missing required files),
        removing ``src/prisma/`` would leave the project without any
        Prisma wiring at all. The contract: remove only when canonical
        owns the replacement.
        """
        _write_stale(tmp_path)
        cfg = _config(enabled=True)

        removed = _maybe_cleanup_duplicate_prisma(cwd=str(tmp_path), config=cfg)

        assert removed == [], "cleanup must be a no-op when canonical is absent"
        stale_dir = tmp_path / "apps" / "api" / "src" / "prisma"
        assert stale_dir.exists(), "stale dir must be preserved when canonical is absent"
        assert (stale_dir / "prisma.module.ts").is_file()
        assert (stale_dir / "prisma.service.ts").is_file()
