"""V6 — scaffold dump diff (build-l vs current Phase B scaffold).

Runs the current scaffold into a tmpdir and compares the tree it produces
against build-l's preserved tree. Reports NEW emissions (paths that scaffold
now produces but build-l did not), REMOVED paths, and callouts for
src/prisma -> src/database and PORT 3001 -> 4000 shifts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.chdir(str(REPO_ROOT))

from agent_team_v15.scaffold_runner import run_scaffolding  # noqa: E402

BUILD_L_ROOT = REPO_ROOT / "v18 test runs" / "build-l-gate-a-20260416"


def _enumerate(root: Path, relative_to: Path) -> set[str]:
    paths: set[str] = set()
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            abs_p = Path(dirpath) / f
            rel = abs_p.relative_to(relative_to).as_posix()
            # Skip inevitable orchestration artefacts — we only compare project tree.
            if rel.startswith(".agent-team/"):
                continue
            if rel.startswith("telemetry/") or rel.startswith("product-ir/"):
                continue
            if rel in {"BUILD_LOG.txt", "GATE_A_FAIL_REPORT.md", "PRD.md", "config.yaml"}:
                continue
            if "attempted-d02-d03-fixes.patch" in rel:
                continue
            if rel.endswith(".tsbuildinfo"):
                continue
            paths.add(rel)
    return paths


def _run_scaffold_into(dest: Path) -> list[str]:
    ir = {
        "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
        "entities": [],
        "i18n": {"locales": ["en"]},
    }
    ir_path = dest / "product.ir.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    emitted = run_scaffolding(ir_path, dest, "milestone-1", ["F-001"])
    # Remove the IR fixture so it doesn't pollute the comparison tree.
    ir_path.unlink()
    return emitted


def main() -> None:
    out: list[str] = []
    with tempfile.TemporaryDirectory(prefix="phase-b-scaffold-") as td:
        dest = Path(td)
        emitted = _run_scaffold_into(dest)
        current_tree = _enumerate(dest, dest)
    build_l_tree = _enumerate(BUILD_L_ROOT, BUILD_L_ROOT)

    new_paths = sorted(current_tree - build_l_tree)
    removed_paths = sorted(build_l_tree - current_tree)
    common = sorted(current_tree & build_l_tree)

    out.append("=" * 70)
    out.append("V6 SCAFFOLD DUMP DIFF — Phase B vs build-l preserved tree")
    out.append("=" * 70)
    out.append("")
    out.append(f"Current scaffold emitted count: {len(emitted)}")
    out.append(f"Current scaffold tree size (files): {len(current_tree)}")
    out.append(f"Build-l tree size (files, excl .agent-team/telemetry/ir): {len(build_l_tree)}")
    out.append("")

    out.append("-- NEW emissions (Phase B scaffold produces, build-l did not) --")
    for p in new_paths:
        out.append(f"  NEW   {p}")
    out.append(f"  total NEW: {len(new_paths)}")
    out.append("")

    out.append("-- REMOVED paths (build-l had them, current scaffold does not emit them) --")
    out.append("  Note: many of these are Wave B/D outputs; scaffold alone is not expected to emit them.")
    for p in removed_paths:
        out.append(f"  REM   {p}")
    out.append(f"  total REMOVED: {len(removed_paths)}")
    out.append("")

    out.append("-- KEY Phase B path shifts --")
    # src/prisma -> src/database
    prisma_old = [p for p in build_l_tree if p.startswith("apps/api/src/prisma/")]
    prisma_new = [p for p in current_tree if p.startswith("apps/api/src/database/")]
    out.append(f"  build-l src/prisma/ entries: {len(prisma_old)}")
    for p in prisma_old:
        out.append(f"    - {p}")
    out.append(f"  Phase B src/database/ entries: {len(prisma_new)}")
    for p in prisma_new:
        out.append(f"    - {p}")

    # PORT comparison
    out.append("")
    out.append("-- PORT literal comparison --")
    for rel in [
        "apps/api/src/main.ts",
        "apps/api/src/config/env.validation.ts",
        "apps/api/.env.example",
        ".env.example",
        "docker-compose.yml",
    ]:
        # Read Phase B
        new_port = _extract_port(dest_search_path(rel), rel)
        old_port = _extract_port(BUILD_L_ROOT / rel, rel) if (BUILD_L_ROOT / rel).exists() else "<absent>"
        out.append(f"  {rel:45s}  build-l={old_port!s:10s}  phase-b={new_port!s}")

    # Report expected Wave 2 adds
    out.append("")
    out.append("-- Phase B Wave 2 expected additions (per architecture report) --")
    for expected in [
        "pnpm-workspace.yaml",
        "tsconfig.base.json",
        "apps/web/next.config.mjs",
        "apps/web/postcss.config.mjs",
        "apps/web/openapi-ts.config.ts",
        "apps/web/tsconfig.json",
        "apps/web/.env.example",
        "apps/web/src/test/setup.ts",
        "apps/api/nest-cli.json",
        "apps/api/tsconfig.build.json",
        "apps/api/src/database/prisma.module.ts",
        "apps/api/src/database/prisma.service.ts",
        "apps/api/src/modules/auth/auth.module.ts",
        "apps/api/src/modules/users/users.module.ts",
        "apps/api/src/modules/projects/projects.module.ts",
        "apps/api/src/modules/tasks/tasks.module.ts",
        "apps/api/src/modules/comments/comments.module.ts",
        "packages/shared/package.json",
        "packages/shared/tsconfig.json",
        "packages/shared/src/enums.ts",
        "packages/shared/src/error-codes.ts",
        "packages/shared/src/pagination.ts",
        "packages/shared/src/index.ts",
        "apps/api/prisma/schema.prisma",
    ]:
        present = expected in current_tree
        in_build_l = expected in build_l_tree
        out.append(
            f"  {'PRESENT' if present else 'MISSING':<8s} {'[also in build-l]' if in_build_l else '[NEW vs build-l]':<20s} {expected}"
        )

    Path(HERE.parent / "scaffold-dump-diff.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


_dest_path_holder: list[Path] = []


def dest_search_path(_rel: str) -> Path:
    # Returning a placeholder — we re-run a quick capture scan below instead.
    # Not used; left as a stub for readability.
    return Path("/dev/null")


def _extract_port(path: Path, rel: str) -> int | str:
    if not path.exists():
        return "<absent>"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"<read-fail:{exc}>"
    import re
    if rel.endswith("main.ts"):
        m = re.search(r"process\.env\.PORT\s*\?\?\s*(\d+)", text)
        return int(m.group(1)) if m else "<not-found>"
    if "env.validation" in rel:
        m = re.search(r"PORT\s*:\s*Joi\.number\(\)[^\n]*?\.default\(\s*(\d+)\s*\)", text, re.DOTALL)
        return int(m.group(1)) if m else "<not-found>"
    if rel.endswith(".env.example") or rel.endswith(".env"):
        m = re.search(r"^PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
        return int(m.group(1)) if m else "<not-found>"
    if rel.endswith("docker-compose.yml"):
        # look for 4000:4000 port mapping
        m = re.search(r"(\d+):(\d+)", text)
        return int(m.group(1)) if m else "<not-found>"
    return "<unchecked>"


if __name__ == "__main__":
    # Because we tempdir and exit the context before _extract_port calls,
    # rewrite the core flow to re-scan the tree while the tempdir is alive.
    out: list[str] = []
    with tempfile.TemporaryDirectory(prefix="phase-b-scaffold-") as td:
        dest = Path(td)
        emitted = _run_scaffold_into(dest)
        current_tree = _enumerate(dest, dest)
        build_l_tree = _enumerate(BUILD_L_ROOT, BUILD_L_ROOT)

        new_paths = sorted(current_tree - build_l_tree)
        removed_paths = sorted(build_l_tree - current_tree)

        out.append("=" * 70)
        out.append("V6 SCAFFOLD DUMP DIFF — Phase B vs build-l preserved tree")
        out.append("=" * 70)
        out.append("")
        out.append(f"Current scaffold emitted count: {len(emitted)}")
        out.append(f"Current scaffold tree size (files): {len(current_tree)}")
        out.append(f"Build-l tree size (files, excl .agent-team/telemetry/ir): {len(build_l_tree)}")
        out.append("")

        out.append("-- Current Phase B scaffold tree (full) --")
        for p in sorted(current_tree):
            out.append(f"  {p}")
        out.append("")

        out.append("-- NEW emissions (Phase B scaffold produces, build-l did not) --")
        for p in new_paths:
            out.append(f"  NEW   {p}")
        out.append(f"  total NEW: {len(new_paths)}")
        out.append("")

        out.append("-- REMOVED paths (build-l had them, current scaffold does not emit) --")
        out.append("  Note: many are Wave B/D outputs; scaffold alone is not expected to emit them.")
        for p in removed_paths:
            out.append(f"  REM   {p}")
        out.append(f"  total REMOVED: {len(removed_paths)}")
        out.append("")

        out.append("-- KEY Phase B path shifts --")
        prisma_old = sorted(p for p in build_l_tree if p.startswith("apps/api/src/prisma/"))
        prisma_new = sorted(p for p in current_tree if p.startswith("apps/api/src/database/"))
        out.append(f"  build-l src/prisma/ entries: {len(prisma_old)}")
        for p in prisma_old:
            out.append(f"    - {p}")
        out.append(f"  Phase B src/database/ entries: {len(prisma_new)}")
        for p in prisma_new:
            out.append(f"    - {p}")

        out.append("")
        out.append("-- PORT literal comparison --")
        for rel in [
            "apps/api/src/main.ts",
            "apps/api/src/config/env.validation.ts",
            "apps/api/.env.example",
            ".env.example",
            "docker-compose.yml",
        ]:
            new_p = dest / rel
            old_p = BUILD_L_ROOT / rel
            new_port = _extract_port(new_p, rel) if new_p.exists() else "<not-emitted>"
            old_port = _extract_port(old_p, rel) if old_p.exists() else "<absent>"
            out.append(f"  {rel:45s}  build-l={str(old_port):10s}  phase-b={str(new_port)}")

        out.append("")
        out.append("-- Phase B Wave 2 expected additions (per architecture report) --")
        for expected in [
            "pnpm-workspace.yaml",
            "tsconfig.base.json",
            "apps/web/next.config.mjs",
            "apps/web/postcss.config.mjs",
            "apps/web/openapi-ts.config.ts",
            "apps/web/tsconfig.json",
            "apps/web/.env.example",
            "apps/web/src/test/setup.ts",
            "apps/api/nest-cli.json",
            "apps/api/tsconfig.build.json",
            "apps/api/src/database/prisma.module.ts",
            "apps/api/src/database/prisma.service.ts",
            "apps/api/src/modules/auth/auth.module.ts",
            "apps/api/src/modules/users/users.module.ts",
            "apps/api/src/modules/projects/projects.module.ts",
            "apps/api/src/modules/tasks/tasks.module.ts",
            "apps/api/src/modules/comments/comments.module.ts",
            "packages/shared/package.json",
            "packages/shared/tsconfig.json",
            "packages/shared/src/enums.ts",
            "packages/shared/src/error-codes.ts",
            "packages/shared/src/pagination.ts",
            "packages/shared/src/index.ts",
            "apps/api/prisma/schema.prisma",
        ]:
            present = expected in current_tree
            in_build_l = expected in build_l_tree
            status = "PRESENT" if present else "MISSING"
            marker = "[also in build-l]" if in_build_l else "[NEW vs build-l]"
            out.append(f"  {status:<8s} {marker:<20s} {expected}")

    (HERE.parent / "scaffold-dump-diff.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
