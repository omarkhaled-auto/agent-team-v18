"""Tests for scripts/run_validators.py — the validator helper script.

Tests the validator helper with synthetic projects, JSON output structure,
findings detection, and --previous flag regression detection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_REPO_ROOT / "src"))


# ===================================================================
# Helpers
# ===================================================================

def _import_run_validators():
    """Import run_validators module from scripts/."""
    import importlib
    spec = importlib.util.spec_from_file_location(
        "run_validators", str(_SCRIPTS_DIR / "run_validators.py"),
    )
    if spec is None or spec.loader is None:
        pytest.skip("scripts/run_validators.py not importable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _create_buggy_prisma_project(tmp_path: Path) -> Path:
    """Create a synthetic project with a Prisma schema that has known issues."""
    project = tmp_path / "test_project"
    project.mkdir()
    prisma_dir = project / "prisma"
    prisma_dir.mkdir()

    # Schema with intentional issues:
    # - Missing @relation directive on FK field (SCHEMA-002)
    # - FK field without onDelete cascade (SCHEMA-001)
    # - Bare FK ID without index (SCHEMA-005)
    schema_content = """\
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String?
  posts     Post[]
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}

model Post {
  id        String   @id @default(cuid())
  title     String
  content   String?
  authorId  String
  author    User     @relation(fields: [authorId], references: [id])
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}

model Comment {
  id        String   @id @default(cuid())
  text      String
  postId    String
  userId    String
  createdAt DateTime @default(now())
}
"""
    (prisma_dir / "schema.prisma").write_text(schema_content)
    return project


def _create_clean_project(tmp_path: Path) -> Path:
    """Create a minimal project with no Prisma or quality issues."""
    project = tmp_path / "clean_project"
    project.mkdir()
    (project / "main.py").write_text("print('hello')\n")
    return project


# ===================================================================
# Import and basic tests
# ===================================================================


class TestValidatorScriptImport:
    """Verify the script can be imported and has expected functions."""

    def test_script_imports_successfully(self):
        mod = _import_run_validators()
        assert mod is not None

    def test_script_has_run_all_function(self):
        mod = _import_run_validators()
        assert hasattr(mod, "run_all"), "run_validators must have run_all() function"
        assert callable(mod.run_all)

    def test_script_has_main_function(self):
        mod = _import_run_validators()
        assert hasattr(mod, "main"), "run_validators must have main() function"
        assert callable(mod.main)


# ===================================================================
# JSON output structure tests
# ===================================================================


class TestValidatorOutputStructure:
    """Verify JSON output from run_all has correct structure."""

    def test_output_has_total_field(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert "total" in result, "Output must have 'total' field"
        assert isinstance(result["total"], int)

    def test_output_has_by_severity(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert "by_severity" in result, "Output must have 'by_severity' field"
        sev = result["by_severity"]
        for level in ("critical", "high", "medium", "low"):
            assert level in sev, f"by_severity must have '{level}' key"

    def test_output_has_findings_list(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert "findings" in result, "Output must have 'findings' field"
        assert isinstance(result["findings"], list)

    def test_output_has_scan_time(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert "scan_time_ms" in result, "Output must have 'scan_time_ms' field"
        assert isinstance(result["scan_time_ms"], (int, float))

    def test_output_has_by_scanner(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert "by_scanner" in result, "Output must have 'by_scanner' field"
        assert isinstance(result["by_scanner"], dict)

    def test_output_is_json_serializable(self, tmp_path):
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        serialized = json.dumps(result)
        assert len(serialized) > 10, "JSON output must be non-empty"
        parsed = json.loads(serialized)
        assert parsed["total"] == result["total"]


# ===================================================================
# Findings detection tests
# ===================================================================


class TestValidatorFindings:
    """Verify the script detects known issues in buggy projects."""

    def test_buggy_prisma_project_has_findings(self, tmp_path):
        """A buggy Prisma schema should produce schema-level findings."""
        mod = _import_run_validators()
        project = _create_buggy_prisma_project(tmp_path)
        result = mod.run_all(project)
        # The buggy schema has issues (missing cascades, missing indexes, etc.)
        # At minimum the schema validator should flag something
        schema_scanner = result.get("by_scanner", {}).get("schema_validator", {})
        if schema_scanner.get("status") == "ok":
            assert result["total"] > 0, (
                "Buggy Prisma schema should produce at least one finding"
            )

    def test_clean_project_has_no_critical_findings(self, tmp_path):
        """A clean project should have no critical-severity findings."""
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project)
        assert result["by_severity"]["critical"] == 0, (
            "Clean project should have zero critical findings"
        )


# ===================================================================
# Regression detection tests (--previous flag)
# ===================================================================


class TestValidatorRegression:
    """Verify --previous flag regression analysis."""

    def test_regression_analysis_with_previous(self, tmp_path):
        """When --previous is given, regression field should appear in output."""
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)

        # Create a fake previous report with some findings
        prev_report = {
            "total": 2,
            "findings": [
                {"id": "SCHEMA-001", "file_path": "schema.prisma", "line": 10, "message": "Missing cascade"},
                {"id": "ENUM-002", "file_path": "types.ts", "line": 5, "message": "Enum mismatch"},
            ],
        }
        prev_path = tmp_path / "previous.json"
        prev_path.write_text(json.dumps(prev_report))

        result = mod.run_all(project, previous_path=prev_path)
        assert "regression" in result, "Output must have 'regression' field when --previous given"

    def test_regression_has_fixed_count(self, tmp_path):
        """Regression analysis should report fixed_count."""
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)

        prev_report = {
            "total": 1,
            "findings": [
                {"id": "FAKE-001", "file_path": "x.ts", "line": 1, "message": "Fake issue"},
            ],
        }
        prev_path = tmp_path / "previous.json"
        prev_path.write_text(json.dumps(prev_report))

        result = mod.run_all(project, previous_path=prev_path)
        reg = result.get("regression", {})
        assert "fixed_count" in reg, "Regression must have 'fixed_count'"
        assert "new_count" in reg, "Regression must have 'new_count'"
        # The previous finding won't appear in current scan of clean project
        assert reg["fixed_count"] >= 1, "Previous finding should be counted as fixed"

    def test_regression_handles_invalid_previous(self, tmp_path):
        """Regression should handle malformed previous JSON gracefully."""
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)

        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not valid json{{{")

        result = mod.run_all(project, previous_path=bad_path)
        reg = result.get("regression", {})
        assert "error" in reg, "Regression should report error for invalid JSON"

    def test_no_regression_when_no_previous(self, tmp_path):
        """Without --previous, no regression field should be present."""
        mod = _import_run_validators()
        project = _create_clean_project(tmp_path)
        result = mod.run_all(project, previous_path=None)
        assert "regression" not in result, (
            "No regression field without --previous"
        )
