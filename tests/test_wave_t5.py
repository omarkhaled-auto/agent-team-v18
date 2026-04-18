"""Phase G Slice 4b — Wave T.5 (Codex test-gap audit).

Covers ``wave_a5_t5.build_wave_t5_prompt`` +
``WAVE_T5_OUTPUT_SCHEMA`` + the ``collect_*`` helpers that produce the
Codex input set. As with Wave A.5, we do not invoke Codex — we only test
the prompt, schema, and the collection heuristics that run offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.wave_a5_t5 import (
    WAVE_T5_OUTPUT_SCHEMA,
    build_wave_t5_prompt,
    collect_source_files_from_tests,
    collect_wave_t_test_files,
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


def test_output_schema_gap_required_fields() -> None:
    gap_item = WAVE_T5_OUTPUT_SCHEMA["properties"]["gaps"]["items"]
    assert set(gap_item["required"]) == {
        "test_file",
        "source_symbol",
        "ac_id",
        "category",
        "severity",
        "missing_case",
        "suggested_assertion",
    }
    # ac_id must accept null (gap may not map to an AC).
    assert gap_item["properties"]["ac_id"]["type"] == ["string", "null"]


def test_output_schema_category_enum() -> None:
    cat = WAVE_T5_OUTPUT_SCHEMA["properties"]["gaps"]["items"]["properties"][
        "category"
    ]["enum"]
    assert "missing_edge_case" in cat
    assert "weak_assertion" in cat


def test_output_schema_top_level_required() -> None:
    assert set(WAVE_T5_OUTPUT_SCHEMA["required"]) == {"gaps", "files_read"}


# ---------------------------------------------------------------------------
# Prompt shape
# ---------------------------------------------------------------------------


def test_prompt_includes_tests_sources_acs_and_schema() -> None:
    test_files = [("apps/api/users.service.spec.ts", "describe('users')")]
    source_files = [("apps/api/users.service.ts", "export class UsersService {}")]
    acs = "- AC-1: Users can register with valid email"

    prompt = build_wave_t5_prompt(
        test_files=test_files,
        source_files=source_files,
        acceptance_criteria=acs,
    )
    assert "<tests>" in prompt
    assert "<source>" in prompt
    assert "<acs>" in prompt
    assert "apps/api/users.service.spec.ts" in prompt
    assert "AC-1" in prompt
    assert "UsersService" in prompt
    # Schema JSON re-parseable.
    start = prompt.index('{\n  "type": "object"')
    tail = prompt.find("\n\nFinal assistant", start)
    parsed = json.loads(prompt[start:tail])
    assert parsed == WAVE_T5_OUTPUT_SCHEMA


def test_prompt_falls_back_when_no_tests_detected() -> None:
    prompt = build_wave_t5_prompt(
        test_files=[],
        source_files=[],
        acceptance_criteria="- AC-1: something",
    )
    assert "(no test files detected)" in prompt


# ---------------------------------------------------------------------------
# collect_wave_t_test_files — picks *.spec / *.test from Wave T artifact
# ---------------------------------------------------------------------------


def test_collect_wave_t_test_files_picks_spec_suffixes(tmp_path: Path) -> None:
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "users.service.spec.ts").write_text(
        "describe", encoding="utf-8"
    )
    artifact = {
        "files_created": ["apps/api/users.service.spec.ts"],
        "files_modified": ["apps/api/users.controller.ts"],
    }
    files = collect_wave_t_test_files(str(tmp_path), artifact)
    rels = {r for r, _ in files}
    assert "apps/api/users.service.spec.ts" in rels
    # Non-test files filtered out.
    assert "apps/api/users.controller.ts" not in rels


def test_collect_wave_t_test_files_returns_empty_for_none_input(tmp_path: Path) -> None:
    assert collect_wave_t_test_files(str(tmp_path), None) == []


# ---------------------------------------------------------------------------
# collect_source_files_from_tests — follows relative `from '../...'` imports
# ---------------------------------------------------------------------------


def test_collect_source_files_follows_relative_imports(tmp_path: Path) -> None:
    """Relative imports to single-segment filenames (no dotted suffix before
    ``.ts``) resolve to source files the helper actually reads back."""
    root = tmp_path / "apps" / "api" / "src" / "users"
    root.mkdir(parents=True)
    # Single-segment name so Path.with_suffix('.ts') produces the right path.
    (root / "users.ts").write_text(
        "export class UsersService {}", encoding="utf-8"
    )
    test_rel = "apps/api/src/users/users.spec.ts"
    test_body = (
        "import { UsersService } from './users';\n"
        "describe('users', () => {})"
    )
    sources = collect_source_files_from_tests(
        str(tmp_path), [(test_rel, test_body)]
    )
    rels = {r for r, _ in sources}
    assert "apps/api/src/users/users.ts" in rels


def test_collect_source_files_ignores_non_relative_imports(tmp_path: Path) -> None:
    """Non-relative imports (e.g., node_modules, aliases) must be skipped."""
    test_rel = "apps/api/src/users/x.spec.ts"
    test_body = (
        "import { Foo } from '@nestjs/common';\n"
        "import { Bar } from 'lodash';\n"
    )
    sources = collect_source_files_from_tests(
        str(tmp_path), [(test_rel, test_body)]
    )
    assert sources == []
