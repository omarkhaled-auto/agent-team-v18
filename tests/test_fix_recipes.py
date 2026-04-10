"""Tests for fix recipes (Feature #4.1) — capture, store, retrieve, format, inject."""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_team_v15.pattern_memory import (
    FixRecipe,
    PatternMemory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem(tmp_path: Path) -> PatternMemory:
    """Fresh PatternMemory in a temp directory."""
    return PatternMemory(db_path=tmp_path / "test.db")


@pytest.fixture
def sample_recipe() -> FixRecipe:
    return FixRecipe(
        finding_id="F001",
        finding_description="Missing null check in handler",
        file_path="src/handler.ts",
        diff_text="--- a/src/handler.ts\n+++ b/src/handler.ts\n@@ -1 +1,2 @@\n+if (!x) return;\n x.run()",
        build_id="build_001",
    )


# ---------------------------------------------------------------------------
# Core functionality
# ---------------------------------------------------------------------------

class TestCaptureFixRecipe:
    def test_capture_fix_recipe(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Capture a recipe and verify it's in the DB."""
        mem.store_fix_recipe(sample_recipe)
        results = mem.get_fix_recipes("F001")
        assert len(results) == 1
        assert results[0].finding_id == "F001"
        assert results[0].file_path == "src/handler.ts"
        assert "if (!x) return;" in results[0].diff_text

    def test_get_fix_recipes_exact_match(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Store recipe, retrieve by exact finding_id."""
        mem.store_fix_recipe(sample_recipe)
        results = mem.get_fix_recipes("F001")
        assert len(results) == 1
        assert results[0].finding_id == "F001"

    def test_get_fix_recipes_no_match(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Query with unknown finding_id returns empty list."""
        mem.store_fix_recipe(sample_recipe)
        results = mem.get_fix_recipes("UNKNOWN_ID")
        assert results == []

    def test_recipe_deduplication(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Capture same recipe twice: occurrence_count increments to 2."""
        mem.store_fix_recipe(sample_recipe)
        mem.store_fix_recipe(sample_recipe)
        results = mem.get_fix_recipes("F001")
        assert len(results) == 1
        assert results[0].occurrence_count == 2

    def test_recipe_ranking_by_occurrence(self, mem: PatternMemory):
        """Multiple recipes for same finding: most frequent first."""
        # Recipe A: store 3 times
        recipe_a = FixRecipe(
            finding_id="F002",
            finding_description="Error X",
            file_path="a.ts",
            diff_text="diff A content unique aaa",
        )
        for _ in range(3):
            mem.store_fix_recipe(recipe_a)

        # Recipe B: store 1 time (different file so different dedup key)
        recipe_b = FixRecipe(
            finding_id="F002",
            finding_description="Error X",
            file_path="b.ts",
            diff_text="diff B content unique bbb",
        )
        mem.store_fix_recipe(recipe_b)

        results = mem.get_fix_recipes("F002", limit=5)
        assert len(results) == 2
        # Ranked by success_count DESC then occurrence_count DESC
        assert results[0].occurrence_count >= results[1].occurrence_count


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_first_build_no_recipes(self, tmp_path: Path):
        """No fix_recipes table yet still returns gracefully."""
        # Create a DB with only the old tables (no fix_recipes)
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE build_patterns (build_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE finding_patterns (finding_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        # PatternMemory will run _init_db which creates fix_recipes via CREATE IF NOT EXISTS
        mem = PatternMemory(db_path=db_path)
        results = mem.get_fix_recipes("anything")
        assert results == []
        mem.close()

    def test_large_diff_truncation(self, mem: PatternMemory):
        """1000-line diff gets truncated in prompt formatting."""
        big_diff = "\n".join(f"+line {i}" for i in range(1000))
        recipe = FixRecipe(
            finding_id="F003",
            finding_description="Big fix",
            file_path="big.ts",
            diff_text=big_diff,
        )
        mem.store_fix_recipe(recipe)

        findings = [{"finding_id": "F003", "description": "Big fix"}]
        prompt = mem.format_recipes_for_prompt(findings)
        # The format method truncates diffs to 100 lines
        assert "truncated" in prompt.lower()

    def test_empty_diff(self, mem: PatternMemory):
        """Empty diff_text: recipe still stores but diff_hash is empty-string based."""
        recipe = FixRecipe(
            finding_id="F004",
            finding_description="No change",
            file_path="unchanged.ts",
            diff_text="",
        )
        mem.store_fix_recipe(recipe)
        results = mem.get_fix_recipes("F004")
        assert len(results) == 1
        assert results[0].diff_text == ""

    def test_multiple_files_same_finding(self, mem: PatternMemory):
        """One finding, multiple file fixes stored as separate recipes."""
        for fp in ["a.ts", "b.ts", "c.ts"]:
            recipe = FixRecipe(
                finding_id="F005",
                finding_description="Multi-file fix",
                file_path=fp,
                diff_text=f"diff for {fp}",
            )
            mem.store_fix_recipe(recipe)

        results = mem.get_fix_recipes("F005", limit=10)
        assert len(results) == 3
        file_paths = {r.file_path for r in results}
        assert file_paths == {"a.ts", "b.ts", "c.ts"}

    def test_db_not_exist(self, tmp_path: Path):
        """DB directory doesn't exist: PatternMemory creates it gracefully."""
        db_path = tmp_path / "deep" / "nested" / "dir" / "test.db"
        mem = PatternMemory(db_path=db_path)
        assert db_path.parent.exists()
        results = mem.get_fix_recipes("anything")
        assert results == []
        mem.close()


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_recipe_prompt_format(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Verify the injected prompt text has expected structure."""
        mem.store_fix_recipe(sample_recipe)
        findings = [{"finding_id": "F001", "description": "Missing null check in handler"}]
        prompt = mem.format_recipes_for_prompt(findings)
        assert "## Fix Recipes from Previous Builds" in prompt
        assert "### Finding:" in prompt
        assert "```diff" in prompt
        assert "if (!x) return;" in prompt

    def test_recipe_with_skills_integration(self, mem: PatternMemory, sample_recipe: FixRecipe):
        """Recipes + skills both inject without conflict (independent text blocks)."""
        mem.store_fix_recipe(sample_recipe)
        findings = [{"finding_id": "F001", "description": "Missing null check"}]
        recipe_text = mem.format_recipes_for_prompt(findings)

        # Simulate skills text
        skills_text = "## Skill Guidance\n\nUse pattern X for handler errors."

        # Both can be concatenated into a prompt
        combined = skills_text + "\n\n" + recipe_text
        assert "## Skill Guidance" in combined
        assert "## Fix Recipes from Previous Builds" in combined

    def test_hook_triggers_recipe_capture(self, tmp_path: Path):
        """Simulate post_audit hook context: recipe capture with before/after."""
        from agent_team_v15.pattern_memory import FixRecipe, PatternMemory

        db_path = tmp_path / "hook_test.db"
        mem = PatternMemory(db_path=db_path)

        # Simulate what _capture_resolved_recipes does
        recipe = FixRecipe(
            finding_id="HOOK_F001",
            finding_description="Simulated hook capture",
            file_path="src/app.ts",
            diff_text="--- a/src/app.ts\n+++ b/src/app.ts\n@@ -1 +1 @@\n-old\n+new",
            build_id="hook_build_1",
        )
        mem.store_fix_recipe(recipe)

        results = mem.get_fix_recipes("HOOK_F001")
        assert len(results) == 1
        assert results[0].build_id == "hook_build_1"
        mem.close()

    def test_state_fields_populated(self):
        """recipes_captured and recipes_applied fields exist on RunState."""
        from agent_team_v15.state import RunState

        state = RunState()
        assert hasattr(state, "recipes_captured")
        assert hasattr(state, "recipes_applied")
        assert state.recipes_captured == 0
        assert state.recipes_applied == 0

        # Increment like the hooks do
        state.recipes_captured += 1
        assert state.recipes_captured == 1


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_old_db_without_fix_recipes_table(self, tmp_path: Path):
        """Open a DB that only has build_patterns/finding_patterns — no crash."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE build_patterns (
                build_id TEXT PRIMARY KEY,
                task_summary TEXT DEFAULT '',
                depth TEXT DEFAULT 'standard',
                tech_stack TEXT DEFAULT '[]',
                total_cost REAL DEFAULT 0.0,
                convergence_ratio REAL DEFAULT 0.0,
                truth_score REAL DEFAULT 0.0,
                audit_score REAL DEFAULT 0.0,
                finding_count INTEGER DEFAULT 0,
                top_dimensions TEXT DEFAULT '[]',
                weak_dimensions TEXT DEFAULT '[]',
                timestamp TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE finding_patterns (
                finding_id TEXT PRIMARY KEY,
                category TEXT DEFAULT '',
                dimension TEXT DEFAULT '',
                severity TEXT DEFAULT '',
                description TEXT DEFAULT '',
                fix_hint TEXT DEFAULT '',
                occurrence_count INTEGER DEFAULT 1,
                last_seen TEXT DEFAULT '',
                build_ids TEXT DEFAULT '[]'
            )
        """)
        conn.commit()
        conn.close()

        # PatternMemory should upgrade gracefully (CREATE IF NOT EXISTS)
        mem = PatternMemory(db_path=db_path)
        # Old tables still work
        from agent_team_v15.pattern_memory import BuildPattern
        mem.store_build_pattern(BuildPattern(build_id="legacy_1", task_summary="old build"))
        builds = mem.search_similar_builds("old build")
        assert len(builds) >= 1

        # New fix_recipes table was created
        results = mem.get_fix_recipes("anything")
        assert results == []

        # Can store and retrieve recipes
        recipe = FixRecipe(
            finding_id="COMPAT_001",
            file_path="compat.ts",
            diff_text="some diff",
        )
        mem.store_fix_recipe(recipe)
        results = mem.get_fix_recipes("COMPAT_001")
        assert len(results) == 1
        mem.close()

    def test_disabled_config(self):
        """fix_recipes disabled in config: field is False."""
        from agent_team_v15.config import HooksConfig

        cfg = HooksConfig(fix_recipes=False)
        assert cfg.fix_recipes is False

        # Default is True
        cfg_default = HooksConfig()
        assert cfg_default.fix_recipes is True


# ---------------------------------------------------------------------------
# FixRecipe dataclass
# ---------------------------------------------------------------------------

class TestFixRecipeDataclass:
    def test_auto_hash(self):
        """diff_hash is auto-computed from diff_text."""
        r = FixRecipe(diff_text="some diff")
        assert r.diff_hash  # non-empty
        assert len(r.diff_hash) == 16  # sha256[:16]

    def test_auto_timestamps(self):
        """created_at and last_used are auto-set."""
        r = FixRecipe()
        assert r.created_at
        assert r.last_used == r.created_at

    def test_diff_size(self):
        """diff_size is auto-computed from diff_text length."""
        r = FixRecipe(diff_text="abcdef")
        assert r.diff_size == 6


# ---------------------------------------------------------------------------
# Fuzzy description match
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_fuzzy_description_match(self, mem: PatternMemory):
        """When finding_id doesn't match, fall back to description LIKE."""
        recipe = FixRecipe(
            finding_id="FUZZY_001",
            finding_description="Authentication middleware missing CORS headers",
            file_path="middleware.ts",
            diff_text="diff content",
        )
        mem.store_fix_recipe(recipe)

        # Exact ID miss, but description words match
        results = mem.get_fix_recipes(
            "DIFFERENT_ID",
            finding_description="middleware Authentication headers",
        )
        assert len(results) >= 1
        assert results[0].finding_id == "FUZZY_001"

    def test_format_empty_findings(self, mem: PatternMemory):
        """format_recipes_for_prompt with empty findings list returns empty string."""
        assert mem.format_recipes_for_prompt([]) == ""

    def test_format_no_matching_recipes(self, mem: PatternMemory):
        """format_recipes_for_prompt with no matching recipes returns empty string."""
        findings = [{"finding_id": "NONE", "description": "nothing"}]
        assert mem.format_recipes_for_prompt(findings) == ""
