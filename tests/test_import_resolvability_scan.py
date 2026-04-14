"""Tests for the import-resolvability scanner.

Covers the navigation.ts class from build-e-bug12-20260414 where Wave D wrote a
file with no exports for symbols other files imported.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.import_resolvability_scan import run_import_resolvability_scan


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_tsconfig(root: Path, base_dir: str = ".", paths_alias: str = "@/*",
                    paths_target: str = "src/*") -> None:
    _write(root / "tsconfig.json", json.dumps({
        "compilerOptions": {
            "baseUrl": base_dir,
            "paths": {paths_alias: [paths_target]},
        }
    }))


# ---------------------------------------------------------------------------
# Pass / no-finding cases
# ---------------------------------------------------------------------------

class TestNoFalsePositives:
    def test_named_import_with_matching_export(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "lib" / "math.ts", "export const add = (a:number,b:number)=>a+b;\n")
        _write(tmp_path / "src" / "app" / "page.tsx",
               "import { add } from '@/lib/math';\nconsole.log(add(1,2));\n")
        violations = run_import_resolvability_scan(tmp_path)
        assert violations == []

    def test_default_import_with_export_default(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "lib" / "default-thing.ts",
               "const Foo = () => null;\nexport default Foo;\n")
        _write(tmp_path / "src" / "app" / "page.tsx",
               "import Foo from '@/lib/default-thing';\nconsole.log(Foo);\n")
        violations = run_import_resolvability_scan(tmp_path)
        assert violations == []

    def test_type_only_import_skipped(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "lib" / "types.ts", "export type Foo = { x: number };\n")
        _write(tmp_path / "src" / "app" / "page.tsx",
               "import type { Foo } from '@/lib/types';\n")
        violations = run_import_resolvability_scan(tmp_path)
        # type imports are accepted (TS erases them); finding here is acceptable
        # but our scanner permissively doesn't emit for type-only imports
        assert violations == []

    def test_external_package_not_scanned(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "app" / "page.tsx",
               "import React from 'react';\nimport { useState } from 'react';\n")
        violations = run_import_resolvability_scan(tmp_path)
        assert violations == []

    def test_re_export_star(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "lib" / "inner.ts", "export const Bar = 1;\n")
        _write(tmp_path / "src" / "lib" / "barrel.ts", "export * from './inner';\n")
        _write(tmp_path / "src" / "app" / "page.tsx",
               "import { Bar } from '@/lib/barrel';\n")
        violations = run_import_resolvability_scan(tmp_path)
        assert violations == []

    def test_destructured_const_export_resolves(self, tmp_path: Path) -> None:
        """Catches the navigation.ts class: `export const { Link, ... } = createNavigation(routing);`"""
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "i18n" / "navigation.ts",
               "import { createNavigation } from 'next-intl/navigation';\n"
               "import { routing } from './routing';\n"
               "export const { Link, redirect, usePathname, useRouter } = createNavigation(routing);\n")
        _write(tmp_path / "src" / "i18n" / "routing.ts",
               "export const routing = { locales: ['en'] } as const;\n")
        _write(tmp_path / "src" / "components" / "auth.tsx",
               "import { useRouter } from '@/i18n/navigation';\n")
        violations = run_import_resolvability_scan(tmp_path)
        assert violations == []


# ---------------------------------------------------------------------------
# Fail / finding cases — the bug we're catching
# ---------------------------------------------------------------------------

class TestEmitsFindings:
    def test_missing_named_export_emits_001(self, tmp_path: Path) -> None:
        """Reproduction of the navigation.ts bug: no useRouter export."""
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "i18n" / "navigation.ts",
               "import { createNavigation } from 'next-intl/navigation';\n"
               "// missing destructured export — bug class\n")
        _write(tmp_path / "src" / "components" / "auth-form.tsx",
               "import { useRouter } from '@/i18n/navigation';\n")
        violations = run_import_resolvability_scan(tmp_path)
        codes = [v.check for v in violations]
        assert "IMPORT-RESOLVABLE-001" in codes
        finding = next(v for v in violations if v.check == "IMPORT-RESOLVABLE-001")
        assert "useRouter" in finding.message
        assert finding.file_path == "src/components/auth-form.tsx"
        assert finding.severity == "error"

    def test_missing_module_emits_002(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "components" / "page.tsx",
               "import { foo } from '@/does/not/exist';\n")
        violations = run_import_resolvability_scan(tmp_path)
        codes = [v.check for v in violations]
        assert "IMPORT-RESOLVABLE-002" in codes
        finding = next(v for v in violations if v.check == "IMPORT-RESOLVABLE-002")
        assert "@/does/not/exist" in finding.message

    def test_partial_destructured_export_flags_missing_only(self, tmp_path: Path) -> None:
        _make_tsconfig(tmp_path)
        _write(tmp_path / "src" / "lib" / "nav.ts",
               "export const { Link, usePathname } = ({} as any);\n")
        _write(tmp_path / "src" / "comp.tsx",
               "import { Link, useRouter } from '@/lib/nav';\n")
        violations = run_import_resolvability_scan(tmp_path)
        msgs = [v.message for v in violations]
        # `Link` must NOT trip a finding; `useRouter` must
        assert any("useRouter" in m for m in msgs)
        assert not any("`Link`" in m for m in msgs)


# ---------------------------------------------------------------------------
# Integration on preserved build-e tree (skip if not present)
# ---------------------------------------------------------------------------

PRESERVED_BUILD_E = (
    Path(__file__).parent.parent / "v18 test runs" / "build-e-bug12-20260414"
)


@pytest.mark.skipif(not PRESERVED_BUILD_E.is_dir(),
                     reason="build-e preserved tree not present in this checkout")
def test_integration_no_false_positive_on_real_navigation_ts() -> None:
    """On the preserved build-e tree (post-audit-fix state), the scanner must
    correctly resolve the real `apps/web/src/i18n/navigation.ts` destructured
    export and emit ZERO IMPORT-RESOLVABLE-001 findings naming `Link`,
    `useRouter`, `usePathname`, or `redirect` from `@/i18n/navigation`.

    Premise: the original failure-state tree was overwritten by the audit-fix
    loop. The preserved tree is the post-fix state — exporting the symbols via
    `export const { Link, ... } = createNavigation(routing);`. The scanner
    must parse that destructured export pattern without false-positiving.
    """
    web_root = PRESERVED_BUILD_E / "apps" / "web"
    if not web_root.is_dir():
        pytest.skip("preserved tree missing apps/web/")
    violations = run_import_resolvability_scan(web_root)
    nav_false_positives = [
        v for v in violations
        if v.check == "IMPORT-RESOLVABLE-001"
        and "i18n/navigation" in v.message
        and any(sym in v.message for sym in ("Link", "useRouter", "usePathname", "redirect"))
    ]
    assert nav_false_positives == [], (
        f"scanner false-positived on real navigation.ts destructured exports: "
        f"{[(v.file_path, v.message) for v in nav_false_positives[:5]]}"
    )
