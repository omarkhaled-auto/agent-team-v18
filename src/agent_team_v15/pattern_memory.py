"""Pattern memory for self-learning hooks (Feature #4).

SQLite + FTS5 storage for build patterns and audit findings.
Enables the builder to recall similar past builds and frequent
failure modes, improving prompt injection on subsequent runs.

All operations are best-effort — failures are logged, never raised.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


@dataclass
class BuildPattern:
    """Snapshot of a completed build for pattern matching."""

    build_id: str = ""
    task_summary: str = ""
    depth: str = "standard"
    tech_stack: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    convergence_ratio: float = 0.0
    truth_score: float = 0.0
    audit_score: float = 0.0
    finding_count: int = 0
    top_dimensions: list[str] = field(default_factory=list)
    weak_dimensions: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class FindingPattern:
    """Recurring audit finding for frequency tracking."""

    finding_id: str = ""
    category: str = ""
    dimension: str = ""
    severity: str = ""
    description: str = ""
    fix_hint: str = ""
    occurrence_count: int = 1
    last_seen: str = ""
    build_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.last_seen:
            self.last_seen = datetime.now(timezone.utc).isoformat()


@dataclass
class FixRecipe:
    """A captured fix recipe: before/after diff for a resolved finding."""

    finding_id: str = ""
    finding_description: str = ""
    file_path: str = ""
    diff_text: str = ""
    diff_hash: str = ""
    build_id: str = ""
    occurrence_count: int = 1
    success_count: int = 1
    last_used: str = ""
    created_at: str = ""
    diff_size: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.last_used:
            self.last_used = self.created_at
        if not self.diff_hash and self.diff_text:
            self.diff_hash = hashlib.sha256(self.diff_text.encode()).hexdigest()[:16]
        if not self.diff_size:
            self.diff_size = len(self.diff_text)


class PatternMemory:
    """SQLite-backed pattern memory with FTS5 full-text search."""

    _SNAPSHOT_CAP = 50
    _snapshot_cap_warned: bool = False

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(".agent-team") / "pattern_memory.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Create tables and FTS5 index if they don't exist."""
        try:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                );
                INSERT OR IGNORE INTO schema_version (version) VALUES (1);

                CREATE TABLE IF NOT EXISTS build_patterns (
                    build_id TEXT PRIMARY KEY,
                    task_summary TEXT NOT NULL DEFAULT '',
                    depth TEXT NOT NULL DEFAULT 'standard',
                    tech_stack TEXT NOT NULL DEFAULT '[]',
                    total_cost REAL NOT NULL DEFAULT 0.0,
                    convergence_ratio REAL NOT NULL DEFAULT 0.0,
                    truth_score REAL NOT NULL DEFAULT 0.0,
                    audit_score REAL NOT NULL DEFAULT 0.0,
                    finding_count INTEGER NOT NULL DEFAULT 0,
                    top_dimensions TEXT NOT NULL DEFAULT '[]',
                    weak_dimensions TEXT NOT NULL DEFAULT '[]',
                    timestamp TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS finding_patterns (
                    finding_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL DEFAULT '',
                    dimension TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    fix_hint TEXT NOT NULL DEFAULT '',
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    last_seen TEXT NOT NULL DEFAULT '',
                    build_ids TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS fix_recipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    finding_id TEXT NOT NULL,
                    finding_description TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL,
                    diff_text TEXT NOT NULL,
                    diff_hash TEXT NOT NULL DEFAULT '',
                    build_id TEXT NOT NULL DEFAULT '',
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    success_count INTEGER NOT NULL DEFAULT 1,
                    last_used TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    diff_size INTEGER NOT NULL DEFAULT 0
                );
            """)
            # Indexes for fix_recipes (separate to handle IF NOT EXISTS per-statement)
            try:
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_fix_recipes_dedup
                        ON fix_recipes(finding_id, file_path, diff_hash)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_fix_recipes_finding
                        ON fix_recipes(finding_id)
                """)
            except sqlite3.OperationalError:
                pass  # indexes may already exist
            # FTS5 virtual table for full-text search over build patterns
            try:
                cur.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS build_patterns_fts
                    USING fts5(
                        build_id,
                        task_summary,
                        depth,
                        tech_stack,
                        content=build_patterns,
                        content_rowid=rowid
                    );
                """)
            except sqlite3.OperationalError:
                # FTS5 not available — degrade gracefully
                _logger.debug("FTS5 not available; full-text search disabled")
            self._conn.commit()
        except Exception as exc:
            _logger.warning("Failed to initialize pattern memory DB: %s", exc)
            self._conn = None

    def _has_fts(self) -> bool:
        """Check whether the FTS5 table exists."""
        if not self._conn:
            return False
        try:
            row = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='build_patterns_fts'"
            ).fetchone()
            return row is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store_build_pattern(self, pattern: BuildPattern) -> None:
        """Insert or replace a build pattern."""
        if not self._conn:
            return
        try:
            # Check snapshot cap
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM build_patterns"
            ).fetchone()
            if row and row["cnt"] >= self._SNAPSHOT_CAP:
                if not PatternMemory._snapshot_cap_warned:
                    _logger.warning(
                        "Snapshot cap reached (%d); oldest patterns will be evicted",
                        self._SNAPSHOT_CAP,
                    )
                    PatternMemory._snapshot_cap_warned = True
                # Evict oldest to stay within cap
                self._conn.execute(
                    "DELETE FROM build_patterns WHERE build_id IN "
                    "(SELECT build_id FROM build_patterns ORDER BY timestamp ASC LIMIT ?)",
                    (row["cnt"] - self._SNAPSHOT_CAP + 1,),
                )
            self._conn.execute(
                """INSERT OR REPLACE INTO build_patterns
                   (build_id, task_summary, depth, tech_stack, total_cost,
                    convergence_ratio, truth_score, audit_score, finding_count,
                    top_dimensions, weak_dimensions, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pattern.build_id,
                    pattern.task_summary,
                    pattern.depth,
                    json.dumps(pattern.tech_stack),
                    pattern.total_cost,
                    pattern.convergence_ratio,
                    pattern.truth_score,
                    pattern.audit_score,
                    pattern.finding_count,
                    json.dumps(pattern.top_dimensions),
                    json.dumps(pattern.weak_dimensions),
                    pattern.timestamp,
                ),
            )
            # Update FTS index
            if self._has_fts():
                self._conn.execute(
                    """INSERT OR REPLACE INTO build_patterns_fts
                       (rowid, build_id, task_summary, depth, tech_stack)
                       VALUES (
                           (SELECT rowid FROM build_patterns WHERE build_id = ?),
                           ?, ?, ?, ?
                       )""",
                    (
                        pattern.build_id,
                        pattern.build_id,
                        pattern.task_summary,
                        pattern.depth,
                        " ".join(pattern.tech_stack),
                    ),
                )
            self._conn.commit()
        except Exception as exc:
            _logger.warning("Failed to store build pattern: %s", exc)

    def store_finding_pattern(self, pattern: FindingPattern) -> None:
        """Insert or update (increment count) a finding pattern."""
        if not self._conn:
            return
        try:
            existing = self._conn.execute(
                "SELECT occurrence_count, build_ids FROM finding_patterns WHERE finding_id = ?",
                (pattern.finding_id,),
            ).fetchone()
            if existing:
                count = existing["occurrence_count"] + 1
                prev_ids = json.loads(existing["build_ids"] or "[]")
                merged = sorted(set(prev_ids + pattern.build_ids))
                self._conn.execute(
                    """UPDATE finding_patterns
                       SET occurrence_count = ?, last_seen = ?, build_ids = ?,
                           category = ?, dimension = ?, severity = ?,
                           description = ?, fix_hint = ?
                       WHERE finding_id = ?""",
                    (
                        count,
                        pattern.last_seen,
                        json.dumps(merged),
                        pattern.category,
                        pattern.dimension,
                        pattern.severity,
                        pattern.description,
                        pattern.fix_hint,
                        pattern.finding_id,
                    ),
                )
            else:
                self._conn.execute(
                    """INSERT INTO finding_patterns
                       (finding_id, category, dimension, severity, description,
                        fix_hint, occurrence_count, last_seen, build_ids)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pattern.finding_id,
                        pattern.category,
                        pattern.dimension,
                        pattern.severity,
                        pattern.description,
                        pattern.fix_hint,
                        pattern.occurrence_count,
                        pattern.last_seen,
                        json.dumps(pattern.build_ids),
                    ),
                )
            self._conn.commit()
        except Exception as exc:
            _logger.warning("Failed to store finding pattern: %s", exc)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search_similar_builds(
        self, query: str, limit: int = 5
    ) -> list[BuildPattern]:
        """FTS5 search for builds matching *query*. Falls back to LIKE."""
        if not self._conn:
            return []
        results: list[BuildPattern] = []
        try:
            if self._has_fts() and query.strip():
                # Tokenize query for better recall (OR between significant words)
                safe_q = query.replace('"', '""')
                tokens = [t for t in safe_q.split() if len(t) > 2]
                fts_query = " OR ".join(f'"{t}"' for t in tokens) if tokens else f'"{safe_q}"'
                rows = self._conn.execute(
                    """SELECT bp.* FROM build_patterns bp
                       JOIN build_patterns_fts fts ON bp.rowid = fts.rowid
                       WHERE build_patterns_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT * FROM build_patterns
                       WHERE task_summary LIKE ? OR tech_stack LIKE ?
                       ORDER BY timestamp DESC
                       LIMIT ?""",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            for row in rows:
                results.append(BuildPattern(
                    build_id=row["build_id"],
                    task_summary=row["task_summary"],
                    depth=row["depth"],
                    tech_stack=json.loads(row["tech_stack"] or "[]"),
                    total_cost=row["total_cost"],
                    convergence_ratio=row["convergence_ratio"],
                    truth_score=row["truth_score"],
                    audit_score=row["audit_score"],
                    finding_count=row["finding_count"],
                    top_dimensions=json.loads(row["top_dimensions"] or "[]"),
                    weak_dimensions=json.loads(row["weak_dimensions"] or "[]"),
                    timestamp=row["timestamp"],
                ))
        except Exception as exc:
            _logger.warning("search_similar_builds failed: %s", exc)
        return results

    def get_top_findings(self, limit: int = 10) -> list[FindingPattern]:
        """Return the most frequently recurring findings."""
        if not self._conn:
            return []
        results: list[FindingPattern] = []
        try:
            rows = self._conn.execute(
                """SELECT * FROM finding_patterns
                   ORDER BY occurrence_count DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            for row in rows:
                results.append(FindingPattern(
                    finding_id=row["finding_id"],
                    category=row["category"],
                    dimension=row["dimension"],
                    severity=row["severity"],
                    description=row["description"],
                    fix_hint=row["fix_hint"],
                    occurrence_count=row["occurrence_count"],
                    last_seen=row["last_seen"],
                    build_ids=json.loads(row["build_ids"] or "[]"),
                ))
        except Exception as exc:
            _logger.warning("get_top_findings failed: %s", exc)
        return results

    def get_weak_dimensions(self, limit: int = 5) -> list[dict[str, Any]]:
        """Aggregate weak_dimensions across builds to find recurring weaknesses."""
        if not self._conn:
            return []
        results: list[dict[str, Any]] = []
        try:
            rows = self._conn.execute(
                "SELECT weak_dimensions FROM build_patterns"
            ).fetchall()
            counts: dict[str, int] = {}
            for row in rows:
                dims = json.loads(row["weak_dimensions"] or "[]")
                for dim in dims:
                    counts[dim] = counts.get(dim, 0) + 1
            sorted_dims = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            for dim, count in sorted_dims[:limit]:
                results.append({"dimension": dim, "count": count})
        except Exception as exc:
            _logger.warning("get_weak_dimensions failed: %s", exc)
        return results

    # ------------------------------------------------------------------
    # Fix Recipes
    # ------------------------------------------------------------------

    def store_fix_recipe(self, recipe: FixRecipe) -> None:
        """Insert or update (increment counts) a fix recipe."""
        if not self._conn:
            return
        try:
            existing = self._conn.execute(
                "SELECT id, occurrence_count, success_count FROM fix_recipes "
                "WHERE finding_id = ? AND file_path = ? AND diff_hash = ?",
                (recipe.finding_id, recipe.file_path, recipe.diff_hash),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE fix_recipes SET occurrence_count = ?, success_count = ?, "
                    "last_used = ?, build_id = ? WHERE id = ?",
                    (
                        existing["occurrence_count"] + 1,
                        existing["success_count"] + 1,
                        datetime.now(timezone.utc).isoformat(),
                        recipe.build_id,
                        existing["id"],
                    ),
                )
            else:
                self._conn.execute(
                    "INSERT INTO fix_recipes "
                    "(finding_id, finding_description, file_path, diff_text, diff_hash, "
                    "build_id, occurrence_count, success_count, last_used, created_at, diff_size) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        recipe.finding_id,
                        recipe.finding_description,
                        recipe.file_path,
                        recipe.diff_text,
                        recipe.diff_hash,
                        recipe.build_id,
                        recipe.occurrence_count,
                        recipe.success_count,
                        recipe.last_used,
                        recipe.created_at,
                        recipe.diff_size,
                    ),
                )
            self._conn.commit()
        except Exception as exc:
            _logger.warning("Failed to store fix recipe: %s", exc)

    def get_fix_recipes(
        self, finding_id: str, finding_description: str = "", limit: int = 3
    ) -> list[FixRecipe]:
        """Retrieve fix recipes by exact finding_id or fuzzy description match."""
        if not self._conn:
            return []
        results: list[FixRecipe] = []
        try:
            # Primary: exact finding_id match
            rows = self._conn.execute(
                "SELECT * FROM fix_recipes WHERE finding_id = ? "
                "ORDER BY success_count DESC, occurrence_count DESC, last_used DESC "
                "LIMIT ?",
                (finding_id, limit),
            ).fetchall()

            # Secondary: fuzzy description match if no exact hits
            if not rows and finding_description:
                words = [w for w in finding_description.split() if len(w) > 3]
                if words:
                    clauses = " OR ".join(
                        "finding_description LIKE ?" for _ in words[:5]
                    )
                    params: list[Any] = [f"%{w}%" for w in words[:5]]
                    params.append(limit)
                    rows = self._conn.execute(
                        f"SELECT * FROM fix_recipes WHERE {clauses} "
                        "ORDER BY success_count DESC LIMIT ?",
                        params,
                    ).fetchall()

            for row in rows:
                results.append(FixRecipe(
                    finding_id=row["finding_id"],
                    finding_description=row["finding_description"],
                    file_path=row["file_path"],
                    diff_text=row["diff_text"],
                    diff_hash=row["diff_hash"],
                    build_id=row["build_id"],
                    occurrence_count=row["occurrence_count"],
                    success_count=row["success_count"],
                    last_used=row["last_used"],
                    created_at=row["created_at"],
                    diff_size=row["diff_size"],
                ))
        except Exception as exc:
            _logger.warning("get_fix_recipes failed: %s", exc)
        return results

    def format_recipes_for_prompt(
        self,
        findings: list[dict[str, Any]],
        max_recipes_per_finding: int = 2,
        max_total_tokens: int = 2000,
    ) -> str:
        """Render fix recipes as markdown for prompt injection.

        *findings* is a list of dicts with keys ``finding_id`` and optionally
        ``description``.  Returns empty string when no recipes match.
        """
        if not findings:
            return ""

        sections: list[str] = []
        total_words = 0
        max_words = int(max_total_tokens * 0.75)  # rough token→word estimate
        findings_with_recipes = 0

        for f in findings:
            if findings_with_recipes >= 5:
                break
            fid = f.get("finding_id", "")
            desc = f.get("description", "")
            recipes = self.get_fix_recipes(fid, desc, limit=max_recipes_per_finding)
            if not recipes:
                continue

            findings_with_recipes += 1
            for recipe in recipes:
                # Truncate large diffs to 100 lines
                diff_lines = recipe.diff_text.splitlines()
                if len(diff_lines) > 100:
                    truncated = "\n".join(diff_lines[:100])
                    truncated += f"\n... ({len(diff_lines) - 100} more lines truncated)"
                else:
                    truncated = recipe.diff_text

                section = (
                    f"### Finding: {desc or fid}\n"
                    f"**Recipe (applied {recipe.success_count}x successfully "
                    f"in {recipe.occurrence_count} build(s)):**\n"
                    f"```diff\n{truncated}\n```\n"
                )
                word_count = len(section.split())
                if total_words + word_count > max_words:
                    break
                sections.append(section)
                total_words += word_count

        if not sections:
            return ""

        header = (
            "## Fix Recipes from Previous Builds\n\n"
            "The following diffs show how similar findings were successfully "
            "fixed in past builds.\nApply these patterns where applicable.\n\n"
        )
        return header + "\n".join(sections)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self) -> None:
        self.close()


# ------------------------------------------------------------------
# Module-level convenience wrappers
# ------------------------------------------------------------------

def get_fix_recipes(
    finding_id: str,
    finding_description: str = "",
    limit: int = 3,
    db_path: str | Path | None = None,
) -> list[FixRecipe]:
    """Retrieve fix recipes (convenience wrapper around PatternMemory)."""
    mem = PatternMemory(db_path=db_path)
    try:
        return mem.get_fix_recipes(finding_id, finding_description, limit)
    finally:
        mem.close()
