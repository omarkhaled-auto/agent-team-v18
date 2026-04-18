"""Phase G Slice 1d — CLAUDE.md + AGENTS.md template constants.

Covers ``agent_team_v15.constitution_templates``:

- ``R8_INVARIANTS`` has exactly 3 canonical project-convention invariants
  (parallel main.ts, api-client edits, git commit).
- Templates render correctly; stack info flows through from the config.
- LOCKED wording (IMMUTABLE packages/api-client, WAVE_T_CORE_PRINCIPLE,
  _ANTI_BAND_AID_FIX_RULES) is NOT duplicated into the project-convention
  files (per Wave 1c §4.4).
- `.codex/config.toml` snippet sets ``project_doc_max_bytes = 65536``.
"""

from __future__ import annotations

from agent_team_v15 import constitution_templates as _ct


def test_r8_invariants_exactly_three() -> None:
    assert isinstance(_ct.R8_INVARIANTS, tuple)
    assert len(_ct.R8_INVARIANTS) == 3


def test_r8_invariants_cover_all_three_canonical_rules() -> None:
    joined = "\n".join(_ct.R8_INVARIANTS).lower()
    # Invariant 1 — no parallel main.ts/bootstrap/AppModule.
    assert "main.ts" in joined or "appmodule" in joined or "bootstrap" in joined
    # Invariant 2 — api-client directory is frozen outside Wave C.
    assert "packages/api-client" in joined
    assert "wave c" in joined
    # Invariant 3 — agents don't commit.
    assert "git commit" in joined or "create new branches" in joined


def test_claude_md_contains_r8_invariants() -> None:
    rendered = _ct.render_claude_md()
    for invariant in _ct.R8_INVARIANTS:
        assert invariant in rendered, f"Missing invariant: {invariant[:60]!r}"


def test_agents_md_contains_r8_invariants() -> None:
    rendered = _ct.render_agents_md()
    for invariant in _ct.R8_INVARIANTS:
        assert invariant in rendered, f"Missing invariant: {invariant[:60]!r}"


def test_locked_wording_not_duplicated_into_claude_md() -> None:
    """LOCKED system-prompt content must NOT leak into CLAUDE.md per §4.4."""
    rendered = _ct.render_claude_md()
    # Anti-band-aid FIX MODE banner from cli._ANTI_BAND_AID_FIX_RULES.
    assert "FIX MODE - ROOT CAUSE ONLY" not in rendered
    # WAVE_T_CORE_PRINCIPLE key phrase.
    assert "If a test fails, THE CODE IS WRONG" not in rendered
    # IMMUTABLE Wave-T rule tell-tale from agents.py.
    assert "NEVER weaken an assertion to make a test pass" not in rendered


def test_locked_wording_not_duplicated_into_agents_md() -> None:
    rendered = _ct.render_agents_md()
    assert "FIX MODE - ROOT CAUSE ONLY" not in rendered
    assert "If a test fails, THE CODE IS WRONG" not in rendered
    assert "NEVER weaken an assertion to make a test pass" not in rendered


def test_render_claude_md_uses_supplied_stack() -> None:
    rendered = _ct.render_claude_md({
        "backend": "NestJS 13 + Prisma 6",
        "frontend": "Remix",
        "tests": "Vitest",
    })
    assert "NestJS 13 + Prisma 6" in rendered
    assert "Remix" in rendered
    assert "Vitest" in rendered


def test_render_agents_md_uses_project_name() -> None:
    rendered = _ct.render_agents_md({"project_name": "acme-platform"})
    assert "acme-platform" in rendered


def test_codex_config_snippet_raises_doc_cap_to_64kib() -> None:
    toml = _ct.render_codex_config_toml()
    assert "[features]" in toml
    assert "project_doc_max_bytes = 65536" in toml
