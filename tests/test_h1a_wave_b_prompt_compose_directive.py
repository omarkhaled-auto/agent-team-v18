"""Phase H1a Item 1 — Wave B compose-wiring prompt directive tests.

Covers the new `[INFRASTRUCTURE WIRING]` block that prompt-agent added
in Wave 2A to `build_wave_b_prompt` (Claude path) and the
`## Infrastructure Wiring (Compose + env parity)` block appended to
`CODEX_WAVE_B_PREAMBLE`, plus the SUFFIX verification bullet.

The invariants guarded here:

* The directive must appear in Wave B (and only Wave B).
* The canonical depends_on / service_healthy / healthcheck terms must
  be named explicitly — oracle-by-keyword, not by a narrative.
* The directive must survive the Claude-fallback path (i.e. live in the
  body of build_wave_b_prompt, not only in the Codex wrapper).
* Rendering is idempotent (no timestamps / UUIDs in the body).
* The SUFFIX carries the one-liner reminder so Codex's final self-audit
  pass has a concrete bullet to check.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_team_v15.agents import (
    build_wave_a_prompt,
    build_wave_b_prompt,
    build_wave_d_prompt,
    build_wave_e_prompt,
    build_wave_t_prompt,
)
from agent_team_v15.codex_prompts import (
    CODEX_WAVE_B_PREAMBLE,
    CODEX_WAVE_B_SUFFIX,
)
from agent_team_v15.config import AgentTeamConfig


# Unique signature phrases from the directive — pick text that is
# specific enough to not collide with unrelated prose.
_BODY_SIGNATURE = (
    "api` service entry in `docker-compose.yml` and its "
    "`apps/api/Dockerfile` MUST both exist or neither does"
)
_CODEX_SECTION_HEADING = "## Infrastructure Wiring (Compose + env parity)"
_SUFFIX_SIGNATURE_PHRASE = "docker-compose.yml"


def _make_milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-1",
        title="Test Milestone",
        scope=[],
        requirements=[],
    )


def _make_ir() -> SimpleNamespace:
    return SimpleNamespace(
        endpoints=[],
        business_rules=[],
        state_machines=[],
        events=[],
        integrations=[],
        integration_items=[],
        acceptance_criteria=[],
    )


def _wave_b(**overrides) -> str:
    defaults = dict(
        milestone=_make_milestone(),
        ir=_make_ir(),
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
        cwd=None,
        milestone_context=None,
        mcp_doc_context="",
    )
    defaults.update(overrides)
    return build_wave_b_prompt(**defaults)


# ---------------------------------------------------------------------------
# Claude-path body tests
# ---------------------------------------------------------------------------


def test_claude_path_body_contains_directive() -> None:
    prompt = _wave_b()
    assert "[INFRASTRUCTURE WIRING]" in prompt, (
        "Expected [INFRASTRUCTURE WIRING] header in Wave B body"
    )
    assert _BODY_SIGNATURE in prompt, (
        "Expected canonical api+Dockerfile coupling rule in Wave B body"
    )


def test_claude_path_names_canonical_fields() -> None:
    prompt = _wave_b()
    # depends_on, service_healthy, healthcheck must all be mentioned.
    assert "depends_on" in prompt
    assert "service_healthy" in prompt
    assert "healthcheck" in prompt.lower()


def test_claude_path_fallback_still_carries_directive() -> None:
    """Claude-fallback path (provider_router) produces the same body —
    the directive must live in the build_wave_b_prompt body, not only
    in the Codex wrapper. This test encodes that invariant by asserting
    the directive is present in the raw return of build_wave_b_prompt
    (which is exactly what _claude_fallback forwards)."""

    prompt = _wave_b()
    assert _BODY_SIGNATURE in prompt
    # Wrapper preamble text MUST NOT be required for the directive to
    # survive — the body itself carries it.
    assert _CODEX_SECTION_HEADING not in prompt  # no wrapper in raw body


def test_claude_path_rendering_is_idempotent() -> None:
    first = _wave_b()
    second = _wave_b()
    assert first == second, (
        "Wave B prompt must render deterministically — no timestamps or UUIDs"
    )


# ---------------------------------------------------------------------------
# Codex-path tests
# ---------------------------------------------------------------------------


def test_codex_preamble_contains_compose_section() -> None:
    assert _CODEX_SECTION_HEADING in CODEX_WAVE_B_PREAMBLE
    assert (
        "depends_on: { postgres: { condition: service_healthy } }"
        in CODEX_WAVE_B_PREAMBLE
    )


def test_codex_preamble_names_healthcheck_contract() -> None:
    assert "healthcheck" in CODEX_WAVE_B_PREAMBLE.lower()
    assert "Definition of Done" in CODEX_WAVE_B_PREAMBLE


def test_codex_suffix_contains_compose_reminder() -> None:
    assert _SUFFIX_SIGNATURE_PHRASE in CODEX_WAVE_B_SUFFIX
    # The bullet must name the file+service pairing rule explicitly so
    # the Codex self-audit checks the right invariant.
    assert "api" in CODEX_WAVE_B_SUFFIX.lower()
    assert "depends_on" in CODEX_WAVE_B_SUFFIX


# ---------------------------------------------------------------------------
# Other-wave negative tests
# ---------------------------------------------------------------------------


def test_directive_not_in_wave_a_prompt() -> None:
    prompt = build_wave_a_prompt(
        milestone=_make_milestone(),
        ir=_make_ir(),
        dependency_artifacts=None,
        scaffolded_files=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
    )
    assert _BODY_SIGNATURE not in prompt, (
        "Wave A must NOT carry the Wave B compose-wiring directive"
    )


def test_directive_not_in_wave_d_prompt() -> None:
    prompt = build_wave_d_prompt(
        milestone=_make_milestone(),
        ir=_make_ir(),
        wave_c_artifact=None,
        scaffolded_files=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
    )
    assert _BODY_SIGNATURE not in prompt, (
        "Wave D must NOT carry the Wave B compose-wiring directive"
    )


def test_directive_not_in_wave_t_prompt() -> None:
    prompt = build_wave_t_prompt(
        milestone=_make_milestone(),
        ir=_make_ir(),
        wave_artifacts=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
    )
    assert _BODY_SIGNATURE not in prompt, (
        "Wave T must NOT carry the Wave B compose-wiring directive"
    )


def test_directive_not_in_wave_e_prompt() -> None:
    prompt = build_wave_e_prompt(
        milestone=_make_milestone(),
        ir=_make_ir(),
        wave_artifacts=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
    )
    assert _BODY_SIGNATURE not in prompt, (
        "Wave E must NOT carry the Wave B compose-wiring directive"
    )
