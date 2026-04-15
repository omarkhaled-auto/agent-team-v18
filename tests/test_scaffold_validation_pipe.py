"""A-05 — scaffold emits a standard NestJS ValidationPipe with no custom key
rewriting. See v18 test runs/session-02-validation/a05-investigation.md for
the decision context.
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


class TestA05ValidationPipe:
    def test_pipe_file_scaffolded(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        pipe = tmp_path / "apps" / "api" / "src" / "common" / "pipes" / "validation.pipe.ts"
        assert pipe.is_file(), "A-05: scaffold must emit validation.pipe.ts"

    def test_pipe_has_standard_nestjs_options(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        pipe = tmp_path / "apps" / "api" / "src" / "common" / "pipes" / "validation.pipe.ts"
        body = pipe.read_text(encoding="utf-8")
        # Standard NestJS options per plan §3 A-05 branch 1
        assert "whitelist: true" in body
        assert "forbidNonWhitelisted: true" in body
        assert "transform: true" in body

    def test_pipe_has_no_custom_key_rewriting(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        pipe = tmp_path / "apps" / "api" / "src" / "common" / "pipes" / "validation.pipe.ts"
        body = pipe.read_text(encoding="utf-8")
        # Scaffold baseline must not carry the build-j normalizeInput hook
        assert "normalizeInput" not in body, (
            "A-05: scaffold must not ship the snake_case normalization shim"
        )
        assert "toSnakeCase" not in body
        # No override transform() method
        assert "override async transform" not in body
        assert "override transform" not in body

    def test_pipe_imports_only_nestjs_common(self, tmp_path: Path) -> None:
        run_scaffolding(_write_ir(tmp_path), tmp_path, "milestone-1", ["F-001"])
        pipe = tmp_path / "apps" / "api" / "src" / "common" / "pipes" / "validation.pipe.ts"
        body = pipe.read_text(encoding="utf-8")
        # No case.util.ts dependency
        assert "case.util" not in body
        assert "from '@nestjs/common'" in body
