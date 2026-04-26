"""A-06 — scaffold emits RTL baseline (globals.css + tailwind.config.ts) +
ESLint rule disallowing physical Tailwind spacing utilities. See
v18 test runs/session-02-validation/a06-investigation.md for the Branch A
decision context.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.scaffold_runner import run_scaffolding


def _write_ir(tmp_path: Path) -> Path:
    ir = {
        "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
        "entities": [],
        "i18n": {"locales": ["en", "ar"]},
    }
    path = tmp_path / "product.ir.json"
    path.write_text(json.dumps(ir), encoding="utf-8")
    return path


class TestA06RtlBaseline:
    def test_globals_css_scaffolded_with_rtl_selector(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        css = tmp_path / "apps" / "web" / "src" / "styles" / "globals.css"
        assert css.is_file(), "A-06: globals.css must be scaffolded"
        body = css.read_text(encoding="utf-8")
        # RTL toggle selector
        assert 'html[dir="rtl"]' in body or "html[dir='rtl']" in body
        # Logical properties baseline — at least one instance of each family
        assert "block-size" in body  # min-block-size / block-size
        assert "inline-size" in body

    def test_globals_css_no_physical_spacing(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        css = tmp_path / "apps" / "web" / "src" / "styles" / "globals.css"
        body = css.read_text(encoding="utf-8")
        # Baseline must not itself use padding-left / margin-right etc.
        for forbidden in (
            "padding-left",
            "padding-right",
            "margin-left",
            "margin-right",
        ):
            assert forbidden not in body, f"A-06: globals.css uses physical '{forbidden}'"

    def test_tailwind_config_scaffolded(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        cfg = tmp_path / "apps" / "web" / "tailwind.config.ts"
        assert cfg.is_file(), "A-06: tailwind.config.ts must be scaffolded"
        body = cfg.read_text(encoding="utf-8")
        # Tailwind 3.4 ships logical utilities via defaults — config must not
        # disable the core plugins. Preflight must stay on.
        assert "preflight: true" in body
        # Content globs point at the Next.js src tree
        assert "./src/**/*.{ts,tsx}" in body

    def test_globals_css_avoids_comment_terminators_inside_tailwind_examples(
        self, tmp_path: Path
    ) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        css = tmp_path / "apps" / "web" / "src" / "styles" / "globals.css"
        body = css.read_text(encoding="utf-8")
        assert "ps-*/pe-*/ms-*/me-*" not in body
        assert "px-*/py-*/mx-*/my-*" not in body
        assert "ps-*, pe-*, ms-*, and me-*" in body

    def test_eslint_config_blocks_physical_spacing_utilities(
        self, tmp_path: Path
    ) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        eslint = tmp_path / "apps" / "web" / "eslint.config.js"
        assert eslint.is_file(), "A-06: apps/web/eslint.config.js must be scaffolded"
        body = eslint.read_text(encoding="utf-8")
        assert "no-restricted-syntax" in body
        # The deny regex must cover every physical spacing family per plan.
        for family in ("px-", "py-", "mx-", "my-", "pl-", "pr-", "pt-", "pb-",
                       "ml-", "mr-", "mt-", "mb-"):
            assert family in body, f"A-06: ESLint rule missing '{family}' family"
