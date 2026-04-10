"""Tests for agent_team_v15.pattern_memory — SQLite + FTS5 pattern storage (Feature #4)."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_team_v15.pattern_memory import (
    BuildPattern,
    FindingPattern,
    PatternMemory,
)


# ---------------------------------------------------------------------------
# BuildPattern dataclass
# ---------------------------------------------------------------------------

class TestBuildPattern:
    """BuildPattern dataclass tests."""

    def test_defaults(self):
        bp = BuildPattern()
        assert bp.build_id == ""
        assert bp.depth == "standard"
        assert bp.tech_stack == []
        assert bp.total_cost == 0.0
        assert bp.timestamp  # auto-set

    def test_custom_values(self):
        bp = BuildPattern(
            build_id="abc123",
            task_summary="Build a REST API",
            depth="thorough",
            tech_stack=["fastapi", "postgres"],
            total_cost=12.5,
            truth_score=0.92,
        )
        assert bp.build_id == "abc123"
        assert bp.tech_stack == ["fastapi", "postgres"]
        assert bp.truth_score == 0.92


# ---------------------------------------------------------------------------
# FindingPattern dataclass
# ---------------------------------------------------------------------------

class TestFindingPattern:
    """FindingPattern dataclass tests."""

    def test_defaults(self):
        fp = FindingPattern()
        assert fp.finding_id == ""
        assert fp.occurrence_count == 1
        assert fp.build_ids == []
        assert fp.last_seen  # auto-set

    def test_custom_values(self):
        fp = FindingPattern(
            finding_id="AUTH-001",
            category="security",
            dimension="auth_flow",
            severity="HIGH",
            description="Missing auth check on /api/admin",
            fix_hint="Add auth middleware",
            build_ids=["build1", "build2"],
        )
        assert fp.finding_id == "AUTH-001"
        assert fp.severity == "HIGH"
        assert len(fp.build_ids) == 2


# ---------------------------------------------------------------------------
# PatternMemory — storage and retrieval
# ---------------------------------------------------------------------------

class TestPatternMemory:
    """Core PatternMemory functionality."""

    def test_init_creates_db(self, tmp_path):
        """Initializing PatternMemory creates the SQLite database file."""
        db_path = tmp_path / "test_memory.db"
        mem = PatternMemory(db_path=db_path)
        assert db_path.exists()
        mem.close()

    def test_store_and_retrieve_build_pattern(self, tmp_path):
        """Store a build pattern and retrieve it via search."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp = BuildPattern(
                build_id="test-001",
                task_summary="Build a todo app with React and Express",
                depth="thorough",
                tech_stack=["react", "express", "mongodb"],
                total_cost=5.0,
                truth_score=0.88,
            )
            mem.store_build_pattern(bp)

            # Search by task content
            results = mem.search_similar_builds("todo app", limit=5)
            assert len(results) >= 1
            assert results[0].build_id == "test-001"
            assert results[0].tech_stack == ["react", "express", "mongodb"]
        finally:
            mem.close()

    def test_store_duplicate_build_replaces(self, tmp_path):
        """Storing a build pattern with same build_id replaces it."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp1 = BuildPattern(build_id="dup", task_summary="v1", truth_score=0.5)
            bp2 = BuildPattern(build_id="dup", task_summary="v2", truth_score=0.9)
            mem.store_build_pattern(bp1)
            mem.store_build_pattern(bp2)

            results = mem.search_similar_builds("v2")
            found = [r for r in results if r.build_id == "dup"]
            assert len(found) == 1
            assert found[0].truth_score == 0.9
        finally:
            mem.close()

    def test_store_and_retrieve_finding_pattern(self, tmp_path):
        """Store finding patterns and retrieve top findings."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        try:
            fp1 = FindingPattern(
                finding_id="AUTH-001",
                category="security",
                dimension="auth",
                severity="HIGH",
                description="Missing auth middleware",
                build_ids=["b1"],
            )
            fp2 = FindingPattern(
                finding_id="ROUTE-001",
                category="integration",
                dimension="routing",
                severity="MEDIUM",
                description="Mismatched route params",
                build_ids=["b1"],
            )
            mem.store_finding_pattern(fp1)
            mem.store_finding_pattern(fp2)

            # Increment AUTH-001 (store again with new build_id)
            fp1_again = FindingPattern(
                finding_id="AUTH-001",
                category="security",
                dimension="auth",
                severity="HIGH",
                description="Missing auth middleware",
                build_ids=["b2"],
            )
            mem.store_finding_pattern(fp1_again)

            top = mem.get_top_findings(limit=10)
            assert len(top) == 2
            # AUTH-001 should be first (count=2)
            assert top[0].finding_id == "AUTH-001"
            assert top[0].occurrence_count == 2
            # build_ids should be merged
            assert "b1" in top[0].build_ids
            assert "b2" in top[0].build_ids
        finally:
            mem.close()

    def test_get_weak_dimensions(self, tmp_path):
        """get_weak_dimensions aggregates across builds."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp1 = BuildPattern(
                build_id="b1",
                weak_dimensions=["auth", "routing"],
            )
            bp2 = BuildPattern(
                build_id="b2",
                weak_dimensions=["auth", "data_model"],
            )
            bp3 = BuildPattern(
                build_id="b3",
                weak_dimensions=["auth"],
            )
            mem.store_build_pattern(bp1)
            mem.store_build_pattern(bp2)
            mem.store_build_pattern(bp3)

            weak = mem.get_weak_dimensions(limit=5)
            assert len(weak) >= 1
            # "auth" appears in all 3 builds
            auth_entry = next(w for w in weak if w["dimension"] == "auth")
            assert auth_entry["count"] == 3
        finally:
            mem.close()

    def test_search_empty_db(self, tmp_path):
        """Searching an empty database returns empty list."""
        db_path = tmp_path / "empty.db"
        mem = PatternMemory(db_path=db_path)
        try:
            results = mem.search_similar_builds("anything")
            assert results == []
        finally:
            mem.close()

    def test_close_idempotent(self, tmp_path):
        """Calling close() multiple times does not raise."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        mem.close()
        mem.close()  # Should not raise

    def test_operations_after_close_return_empty(self, tmp_path):
        """Operations after close() return empty results (not crash)."""
        db_path = tmp_path / "test.db"
        mem = PatternMemory(db_path=db_path)
        mem.close()
        assert mem.search_similar_builds("test") == []
        assert mem.get_top_findings() == []
        assert mem.get_weak_dimensions() == []


# ---------------------------------------------------------------------------
# FTS5 search
# ---------------------------------------------------------------------------

class TestFTS5Search:
    """FTS5 full-text search tests."""

    def test_fts_search_by_tech_stack(self, tmp_path):
        """FTS5 can find builds by tech stack keywords."""
        db_path = tmp_path / "fts.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp = BuildPattern(
                build_id="fts-test",
                task_summary="Build a dashboard with Next.js and PostgreSQL",
                tech_stack=["nextjs", "postgresql", "prisma"],
            )
            mem.store_build_pattern(bp)

            # Search by tech name
            results = mem.search_similar_builds("nextjs")
            assert any(r.build_id == "fts-test" for r in results)
        finally:
            mem.close()

    def test_fts_search_by_task_summary(self, tmp_path):
        """FTS5 can find builds by task description words."""
        db_path = tmp_path / "fts.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp = BuildPattern(
                build_id="fts-task",
                task_summary="E-commerce platform with payment integration",
            )
            mem.store_build_pattern(bp)

            results = mem.search_similar_builds("payment")
            assert any(r.build_id == "fts-task" for r in results)
        finally:
            mem.close()

    def test_fts_empty_query_falls_back(self, tmp_path):
        """Empty query falls back to LIKE search."""
        db_path = tmp_path / "fts.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp = BuildPattern(build_id="fb-test", task_summary="anything")
            mem.store_build_pattern(bp)
            # Empty query should not crash
            results = mem.search_similar_builds("")
            # May or may not return results, but should not raise
            assert isinstance(results, list)
        finally:
            mem.close()

    def test_fts_special_chars_in_query(self, tmp_path):
        """Special characters in search query are handled safely."""
        db_path = tmp_path / "fts.db"
        mem = PatternMemory(db_path=db_path)
        try:
            bp = BuildPattern(build_id="sc-test", task_summary="test with quotes")
            mem.store_build_pattern(bp)
            # Should not crash on special chars
            results = mem.search_similar_builds('test "with" special*')
            assert isinstance(results, list)
        finally:
            mem.close()


# ---------------------------------------------------------------------------
# Default path creation
# ---------------------------------------------------------------------------

class TestDefaultPath:
    """PatternMemory default path behavior."""

    def test_default_path_creates_directory(self, tmp_path, monkeypatch):
        """When no db_path, PatternMemory uses .agent-team/pattern_memory.db."""
        monkeypatch.chdir(tmp_path)
        mem = PatternMemory()
        expected = tmp_path / ".agent-team" / "pattern_memory.db"
        assert expected.exists()
        mem.close()
