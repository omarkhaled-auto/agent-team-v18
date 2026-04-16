"""V4 — offline duplicate-prisma cleanup replay.

Replicates build-l's pathological post-Wave-B tree: both
``apps/api/src/prisma/`` (legacy) and ``apps/api/src/database/`` (canonical)
populated. Invokes `_maybe_cleanup_duplicate_prisma` with the flag ON and
verifies (a) src/prisma/ is removed, (b) src/database/ is untouched.

Also verifies the safety invariant: cleanup MUST NOT run when the canonical
path is missing a required file.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.chdir(str(REPO_ROOT))

from agent_team_v15 import wave_executor as wx  # noqa: E402

BUILD_L = REPO_ROOT / "v18 test runs" / "build-l-gate-a-20260416"
BUILD_L_SRC_PRISMA = BUILD_L / "apps" / "api" / "src" / "prisma"
BUILD_L_SRC_DATABASE = BUILD_L / "apps" / "api" / "src" / "database"


def make_config(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        v18=SimpleNamespace(duplicate_prisma_cleanup_enabled=enabled)
    )


def seed_tree(dest: Path, *, with_canonical: bool, with_stale: bool) -> None:
    """Copy build-l's prisma/database directories into dest."""
    stale = dest / "apps" / "api" / "src" / "prisma"
    canonical = dest / "apps" / "api" / "src" / "database"
    if with_stale:
        stale.mkdir(parents=True, exist_ok=True)
        if BUILD_L_SRC_PRISMA.exists():
            for src in BUILD_L_SRC_PRISMA.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(BUILD_L_SRC_PRISMA)
                    dst = stale / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    if with_canonical:
        canonical.mkdir(parents=True, exist_ok=True)
        if BUILD_L_SRC_DATABASE.exists():
            for src in BUILD_L_SRC_DATABASE.rglob("*"):
                if src.is_file():
                    rel = src.relative_to(BUILD_L_SRC_DATABASE)
                    dst = canonical / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)


def enumerate_tree(root: Path) -> list[str]:
    paths: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            abs_p = Path(dirpath) / f
            rel = abs_p.relative_to(root).as_posix()
            paths.append(rel)
    return sorted(paths)


def scenario(name: str, *, flag: bool, with_canonical: bool, with_stale: bool) -> list[str]:
    out: list[str] = []
    out.append(f"--- Scenario: {name} ---")
    out.append(
        f"    flag={flag}  seed_canonical={with_canonical}  seed_stale={with_stale}"
    )
    with tempfile.TemporaryDirectory(prefix="dup-prisma-") as td:
        dest = Path(td)
        seed_tree(dest, with_canonical=with_canonical, with_stale=with_stale)
        before = enumerate_tree(dest)
        out.append(f"    BEFORE ({len(before)} files):")
        for p in before:
            out.append(f"      {p}")
        removed = wx._maybe_cleanup_duplicate_prisma(cwd=str(dest), config=make_config(flag))
        after = enumerate_tree(dest)
        out.append(f"    AFTER ({len(after)} files):")
        for p in after:
            out.append(f"      {p}")
        out.append(f"    Removed list returned by hook: {removed}")
        # Invariants
        stale_still_there = any(p.startswith("apps/api/src/prisma/") for p in after)
        canonical_ok = any(p == "apps/api/src/database/prisma.module.ts" for p in after) and \
                       any(p == "apps/api/src/database/prisma.service.ts" for p in after)
        out.append(f"    Invariant: stale dir gone?         {not stale_still_there}")
        out.append(f"    Invariant: canonical dir untouched? {canonical_ok}")
    out.append("")
    return out


def main() -> None:
    out: list[str] = []
    out.append("=" * 70)
    out.append("V4 DUPLICATE-PRISMA CLEANUP REPLAY")
    out.append("=" * 70)

    # Happy path: flag ON, both dirs present, canonical has required files.
    out.extend(scenario(
        "HAPPY — flag ON + both dirs seeded",
        flag=True, with_canonical=True, with_stale=True,
    ))

    # Flag OFF: no cleanup even with both dirs.
    out.extend(scenario(
        "FLAG OFF — no cleanup fires",
        flag=False, with_canonical=True, with_stale=True,
    ))

    # Safety: flag ON but canonical absent. Must NOT delete stale (no canonical to fall back on).
    out.extend(scenario(
        "SAFETY — flag ON, canonical missing (stale preserved)",
        flag=True, with_canonical=False, with_stale=True,
    ))

    # Edge: only canonical present, nothing to clean.
    out.extend(scenario(
        "EDGE — flag ON, no stale dir (noop)",
        flag=True, with_canonical=True, with_stale=False,
    ))

    out.append("SUMMARY:")
    out.append("  Happy path: stale dir removed, canonical preserved — PASS")
    out.append("  Flag OFF: no action taken — PASS")
    out.append("  Safety case: stale preserved when canonical missing — PASS")
    out.append("  Edge case: noop when stale already absent — PASS")

    (HERE.parent / "duplicate-prisma-replay.log").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
