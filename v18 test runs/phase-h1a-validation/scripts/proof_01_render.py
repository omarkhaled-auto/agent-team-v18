"""Proof 01: render the Wave B prompt through the production build_wave_b_prompt
entry point for the full_stack template, then wrap through wrap_prompt_for_codex.

This is the exact call chain provider_router.py uses in production.
"""

from __future__ import annotations

import re
import sys
from types import SimpleNamespace

from agent_team_v15.agents import build_wave_b_prompt
from agent_team_v15.codex_prompts import wrap_prompt_for_codex
from agent_team_v15.config import AgentTeamConfig


def _milestone():
    return SimpleNamespace(
        id="milestone-1",
        title="Foundation",
        scope=[],
        requirements=[],
        template="full_stack",
    )


def _ir():
    return SimpleNamespace(
        endpoints=[],
        business_rules=[],
        state_machines=[],
        events=[],
        integrations=[],
        integration_items=[],
        acceptance_criteria=[],
    )


def main() -> int:
    prompt = build_wave_b_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=None,
        config=AgentTeamConfig(),
        existing_prompt_framework="",
        cwd=None,
        milestone_context=None,
        mcp_doc_context="",
    )

    signature = (
        "api` service entry in `docker-compose.yml` and its "
        "`apps/api/Dockerfile` MUST both exist or neither does"
    )

    print("=" * 78)
    print("CLAUDE BODY — signature search for compose-wiring directive")
    print("=" * 78)
    print(f"signature present in body: {signature in prompt!r}")
    print(f"[INFRASTRUCTURE WIRING] header present: {'[INFRASTRUCTURE WIRING]' in prompt!r}")
    print()

    # Slice ~60 lines around the signature for visual confirmation.
    lines = prompt.splitlines()
    match_idx = next((i for i, L in enumerate(lines) if "[INFRASTRUCTURE WIRING]" in L), -1)
    if match_idx < 0:
        print("FAIL: no [INFRASTRUCTURE WIRING] header found")
        return 2
    start = max(0, match_idx - 2)
    end = min(len(lines), match_idx + 40)
    print("-" * 78)
    print(f"Claude-body slice [lines {start}..{end}] around [INFRASTRUCTURE WIRING]:")
    print("-" * 78)
    for i, line in enumerate(lines[start:end], start=start):
        print(f"{i:5d} | {line}")

    # Codex wrapper
    wrapped = wrap_prompt_for_codex("B", prompt)
    assert "## Infrastructure Wiring (Compose + env parity)" in wrapped, "Codex PREAMBLE heading missing"

    # Find PREAMBLE section + SUFFIX bullet positions.
    preamble_heading = "## Infrastructure Wiring (Compose + env parity)"
    pre_idx = wrapped.find(preamble_heading)
    assert pre_idx >= 0

    # Show PREAMBLE infrastructure block (heading → next "---" separator).
    tail = wrapped[pre_idx:]
    sep = tail.find("\n---")
    preamble_block = tail[: sep if sep >= 0 else min(1200, len(tail))]
    print()
    print("=" * 78)
    print("CODEX PREAMBLE — Infrastructure Wiring section")
    print("=" * 78)
    print(preamble_block)

    # Show SUFFIX bullet mentioning compose.
    suffix_tail = wrapped.rsplit("\n---\n", 1)[-1] if "\n---\n" in wrapped else wrapped[-2000:]
    compose_bullets = [ln for ln in suffix_tail.splitlines() if "docker-compose" in ln.lower()]
    print()
    print("=" * 78)
    print("CODEX SUFFIX — compose-mentioning verification-checklist bullets")
    print("=" * 78)
    for bullet in compose_bullets:
        print(bullet)

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  Claude body contains [INFRASTRUCTURE WIRING]: {'[INFRASTRUCTURE WIRING]' in prompt}")
    print(f"  Claude body contains signature phrase:        {signature in prompt}")
    print(f"  Codex PREAMBLE contains heading:              {preamble_heading in wrapped}")
    print(f"  Codex SUFFIX mentions docker-compose.yml:     {any('docker-compose' in b.lower() for b in compose_bullets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
