"""Static scaffold verification — build an M1 scaffold tree into a temp dir
and dump a human-readable summary for reviewer eyeballing.

Usage:
    python "v18 test runs/session-02-validation/build_m1_scaffold.py" \
        > "v18 test runs/session-02-validation/phase1-scaffold-dump.txt"

Does NOT run npm / docker / nest / vitest. Pure Python, reads the scaffold
output as files on disk.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agent_team_v15.scaffold_runner import run_scaffolding  # noqa: E402


def _resolve_ir_path() -> Path:
    """Look for build-j IR in this worktree, then fall back to the main repo.

    Large run artefacts are untracked — they live only in the primary repo
    checkout. This script may run from a sibling worktree that doesn't have
    them. Resolving both keeps the dump reproducible.
    """
    candidates = [
        REPO_ROOT,
        REPO_ROOT.parent / "agent-team-v18-codex",
    ]
    for base in candidates:
        candidate = (
            base
            / "v18 test runs"
            / "build-j-closeout-sonnet-20260415"
            / ".agent-team"
            / "product-ir"
            / "product.ir.json"
        )
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "build-j IR not found in worktree or main repo "
        "(expected v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/product-ir/product.ir.json)"
    )


IR_PATH = _resolve_ir_path()

FEATURES_M1 = ["F-001"]
KEY_FILES = (
    "docker-compose.yml",
    ".gitignore",
    ".env.example",
    "package.json",
    "apps/api/package.json",
    "apps/api/src/main.ts",
    "apps/api/src/config/env.validation.ts",
    "apps/api/src/prisma/prisma.service.ts",
    "apps/api/src/prisma/prisma.module.ts",
    "apps/web/package.json",
    "apps/web/vitest.config.ts",
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="m1-scaffold-") as tmp:
        project_root = Path(tmp)
        created = run_scaffolding(IR_PATH, project_root, "milestone-1", FEATURES_M1)

        print("# Session 2 Phase 1 scaffold dump")
        print(f"# IR: {IR_PATH.name}")
        print(f"# Project root: {project_root}")
        print()
        print("## Created paths")
        for path in sorted(created):
            print(f"- {path}")
        print()

        for rel in KEY_FILES:
            path = project_root / rel
            print(f"## {rel}")
            if path.is_file():
                print("```")
                print(path.read_text(encoding="utf-8"))
                print("```")
            else:
                print("(missing — FAIL)")
            print()

        # Locale listing
        messages_dir = project_root / "apps" / "web" / "messages"
        print("## apps/web/messages (locale directories)")
        if messages_dir.is_dir():
            for loc in sorted(p.name for p in messages_dir.iterdir() if p.is_dir()):
                ns_files = sorted(
                    f.name for f in (messages_dir / loc).iterdir() if f.is_file()
                )
                print(f"- {loc}: {', '.join(ns_files) or '(empty)'}")
        print()


if __name__ == "__main__":
    main()
