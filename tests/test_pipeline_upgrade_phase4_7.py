"""Phase 4.7 — wave_boundary block + scaffold-stub header fixtures.

Locks the contracts described in
``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §J:

* Phase 4.7a: Wave B / Wave D prompts gain an explicit ``<wave_boundary>``
  block; ``MilestoneScope.allowed_file_globs`` narrows when rendered for
  one of the ambiguity-prone waves so that frontend chassis files are no
  longer Wave B's blanket responsibility.
* Phase 4.7b: scaffold-emitted stub files carry a machine-readable
  ``@scaffold-stub: finalized-by-wave-<X>`` header in their first 8
  lines; the audit team reads this header in
  ``AuditFinding.from_dict`` (project_root-aware) and ``wave_ownership``
  to override path-based classification.

These fixtures are written TDD-style — every assertion is expected to
fail before the Phase 4.7 implementation lands.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

SMOKE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"
SMOKE_AUDIT_REPORT = SMOKE_FIXTURE_DIR / "AUDIT_REPORT.json"


# -----------------------------------------------------------------------------
# Phase 4.7a — wave_boundary block
# -----------------------------------------------------------------------------


def test_wave_b_boundary_block_self_identifies_and_lists_wave_d_files():
    """AC1: Wave B's boundary block names Wave B's scope, names Wave D's
    domain, and explicitly calls out the F-001 file (middleware.ts)
    that the 2026-04-26 smoke audit graded as critical because the
    Wave B prompt had 0 mentions of it."""
    from agent_team_v15.wave_boundary import format_wave_boundary_block

    block = format_wave_boundary_block("B")
    assert "<wave_boundary>" in block
    assert "</wave_boundary>" in block
    assert "Wave B" in block
    assert "BACKEND" in block
    assert "Wave D" in block
    assert "FRONTEND" in block.upper()
    # Specific Wave-D files the smoke prompt was missing:
    assert "apps/web/src/middleware.ts" in block
    assert "i18n" in block.lower()
    assert "locales" in block.lower()


def test_wave_d_boundary_block_self_identifies_and_lists_wave_b_files():
    """AC1d: symmetric — Wave D's boundary block names Wave D's scope,
    names Wave B's domain, and lists backend artifacts Wave D should not
    touch."""
    from agent_team_v15.wave_boundary import format_wave_boundary_block

    block = format_wave_boundary_block("D")
    assert "<wave_boundary>" in block
    assert "</wave_boundary>" in block
    assert "Wave D" in block
    assert "FRONTEND" in block
    assert "Wave B" in block
    assert "BACKEND" in block.upper()
    assert "apps/api" in block
    assert "prisma" in block


def test_other_waves_get_no_boundary_block():
    """Wave A/C/T/E/D5 don't suffer from the same sibling-wave ambiguity
    as B↔D, so the helper returns the empty string for them and the
    prompt builders emit no extra block."""
    from agent_team_v15.wave_boundary import format_wave_boundary_block

    for wave in ("A", "A5", "C", "T", "T5", "E", "D5", "", "?"):
        assert format_wave_boundary_block(wave) == "", (
            f"Wave {wave!r} unexpectedly produced a non-empty boundary block"
        )


def test_narrow_allowed_globs_for_wave_b_drops_apps_web_blanket():
    """AC2: Wave B's allowed-globs no longer blanket-include apps/web/**,
    locales/**, or packages/api-client/** — those belong to Wave D and
    Wave C respectively."""
    from agent_team_v15.wave_boundary import narrow_allowed_globs_for_wave

    smoke_globs = [
        "apps/api/**",
        "apps/web/**",
        "packages/api-client/**",
        "prisma/**",
        "locales/**",
        "docker-compose.yml",
        ".env.example",
        "package.json",
    ]
    out = narrow_allowed_globs_for_wave(smoke_globs, "B")
    assert "apps/api/**" in out
    assert "prisma/**" in out
    assert "apps/web/**" not in out
    assert "packages/api-client/**" not in out
    assert "locales/**" not in out
    # Wave-agnostic infra survives.
    assert "docker-compose.yml" in out
    assert ".env.example" in out
    assert "package.json" in out


def test_narrow_allowed_globs_keeps_apps_web_dockerfile_exception():
    """apps/web/Dockerfile + apps/web/.env.example stay Wave-B-touchable
    even when apps/web/** is dropped — Wave B owns the image build for
    the frontend service. Per §J infra-exception list."""
    from agent_team_v15.wave_boundary import narrow_allowed_globs_for_wave

    globs = [
        "apps/web/Dockerfile",
        "apps/web/.env.example",
        "apps/web/**",
    ]
    out = narrow_allowed_globs_for_wave(globs, "B")
    assert "apps/web/Dockerfile" in out
    assert "apps/web/.env.example" in out
    assert "apps/web/**" not in out


def test_narrow_allowed_globs_for_wave_d_drops_backend_globs():
    """AC2 symmetric: Wave D drops apps/api/**, prisma/**, and
    packages/api-client/** (Wave C's frozen deliverable)."""
    from agent_team_v15.wave_boundary import narrow_allowed_globs_for_wave

    globs = [
        "apps/api/**",
        "apps/web/**",
        "prisma/**",
        "packages/api-client/**",
    ]
    out = narrow_allowed_globs_for_wave(globs, "D")
    assert "apps/api/**" not in out
    assert "prisma/**" not in out
    assert "packages/api-client/**" not in out
    assert "apps/web/**" in out


def test_narrow_allowed_globs_noop_for_unknown_wave():
    """Defensive: unknown wave letter (A/C/T/E/D5/empty) returns globs
    unchanged. Phase 4.7a only narrows for the two ambiguity-prone
    waves (B and D)."""
    from agent_team_v15.wave_boundary import narrow_allowed_globs_for_wave

    globs = ["apps/api/**", "apps/web/**", "prisma/**"]
    for wave in ("A", "A5", "C", "T", "T5", "E", "D5", ""):
        out = narrow_allowed_globs_for_wave(globs, wave)
        assert out == globs, f"Wave {wave!r} unexpectedly narrowed: {out}"


def test_apply_scope_to_prompt_narrows_globs_for_wave_b():
    """AC6: rendered scope preamble for Wave B has 0 mentions of i18n /
    locales / components in the allowed-globs section. The smoke's
    Wave B prompt listed all three; Phase 4.7a's narrowing strips
    them."""
    from agent_team_v15.milestone_scope import (
        MilestoneScope,
        apply_scope_to_prompt,
    )

    scope = MilestoneScope(
        milestone_id="milestone-1",
        description="Test milestone",
        allowed_file_globs=[
            "apps/api/**",
            "apps/web/**",
            "apps/web/src/i18n/**",
            "apps/web/src/components/**",
            "apps/web/locales/**",
            "locales/**",
            "packages/api-client/**",
            "prisma/**",
            "docker-compose.yml",
            "package.json",
        ],
    )
    rendered = apply_scope_to_prompt("BODY", scope, wave="B")
    # Carve out the rendered "Allowed file globs" block to verify what's
    # in/out of it.
    head, _, tail = rendered.partition("### Allowed file globs")
    assert tail, "scope preamble missing 'Allowed file globs' header"
    section, _, _ = tail.partition("###")
    section_lower = section.lower()
    # Wave-D-owned globs filtered:
    assert "i18n" not in section_lower
    assert "components" not in section_lower
    assert "locales" not in section_lower
    assert "apps/web/**" not in section
    # Backend globs preserved:
    assert "apps/api/**" in section
    assert "prisma/**" in section


def test_apply_scope_to_prompt_does_not_narrow_for_non_b_d_waves():
    """Backward-compat: when wave is A/C/T/E, allowed_file_globs render
    verbatim (Phase 4.7a's narrowing is scoped to B and D only)."""
    from agent_team_v15.milestone_scope import (
        MilestoneScope,
        apply_scope_to_prompt,
    )

    scope = MilestoneScope(
        milestone_id="milestone-1",
        description="Test milestone",
        allowed_file_globs=["apps/api/**", "apps/web/**", "prisma/**"],
    )
    rendered = apply_scope_to_prompt("BODY", scope, wave="A")
    assert "apps/api/**" in rendered
    assert "apps/web/**" in rendered
    assert "prisma/**" in rendered


def test_apply_scope_to_prompt_skips_narrowing_when_flag_off():
    """Rollback path: when ``wave_boundary_narrow_globs=False`` is passed
    explicitly, narrowing is dormant and Wave B/D get the legacy verbatim
    glob list. Mirrors the Phase 4.5 ``lift_risk_1_when_nets_armed``
    rollback pattern."""
    from agent_team_v15.milestone_scope import (
        MilestoneScope,
        apply_scope_to_prompt,
    )

    scope = MilestoneScope(
        milestone_id="milestone-1",
        description="Test milestone",
        allowed_file_globs=["apps/api/**", "apps/web/**", "prisma/**"],
    )
    rendered = apply_scope_to_prompt(
        "BODY", scope, wave="B", wave_boundary_narrow_globs=False
    )
    assert "apps/api/**" in rendered
    assert "apps/web/**" in rendered  # NOT narrowed when flag off
    assert "prisma/**" in rendered


def test_wave_boundary_block_enabled_default_true():
    """Phase 4.7a master kill switch defaults True (boundary block +
    glob narrowing both active)."""
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert cfg.wave_boundary_block_enabled is True


def test_build_wave_b_prompt_includes_wave_boundary_block_when_enabled():
    """The rendered Wave B prompt body contains the
    ``<wave_boundary>`` block when the flag is on (default). Composes
    with build_wave_b_prompt's existing scaffold-deliverables / port-
    invariants / framework-instructions blocks."""
    from agent_team_v15.agents import build_wave_b_prompt
    from agent_team_v15.config import AgentTeamConfig

    config = AgentTeamConfig()
    milestone = type("M", (), {"id": "milestone-1", "title": "test", "description": "x"})()
    rendered = build_wave_b_prompt(
        milestone=milestone,
        ir=None,
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=[],
        config=config,
        existing_prompt_framework="[FRAMEWORK]",
        cwd=None,
    )
    assert "<wave_boundary>" in rendered
    assert "Wave D" in rendered
    assert "apps/web/src/middleware.ts" in rendered


def test_build_wave_b_prompt_omits_wave_boundary_block_when_flag_off():
    """When ``audit_team.wave_boundary_block_enabled = False``, the
    boundary block is omitted (rollback path; pre-Phase-4.7 behaviour)."""
    from agent_team_v15.agents import build_wave_b_prompt
    from agent_team_v15.config import AgentTeamConfig

    config = AgentTeamConfig()
    config.audit_team.wave_boundary_block_enabled = False
    milestone = type("M", (), {"id": "milestone-1", "title": "test", "description": "x"})()
    rendered = build_wave_b_prompt(
        milestone=milestone,
        ir=None,
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=[],
        config=config,
        existing_prompt_framework="[FRAMEWORK]",
        cwd=None,
    )
    assert "<wave_boundary>" not in rendered


def test_build_wave_d_prompt_includes_wave_boundary_block_when_enabled():
    """Symmetric to Wave B: build_wave_d_prompt body contains the
    boundary block listing Wave B's backend artifacts."""
    from agent_team_v15.agents import build_wave_d_prompt
    from agent_team_v15.config import AgentTeamConfig

    config = AgentTeamConfig()
    milestone = type("M", (), {"id": "milestone-1", "title": "test", "description": "x"})()
    rendered = build_wave_d_prompt(
        milestone=milestone,
        ir=None,
        wave_c_artifact=None,
        scaffolded_files=[],
        config=config,
        existing_prompt_framework="[FRAMEWORK]",
        cwd=None,
    )
    assert "<wave_boundary>" in rendered
    assert "Wave B" in rendered
    assert "apps/api" in rendered
    assert "prisma" in rendered


# -----------------------------------------------------------------------------
# Phase 4.7b — scaffold-stub headers
# -----------------------------------------------------------------------------


def test_scaffold_stub_files_carry_machine_readable_header():
    """AC3: every scaffold-emitted stub MUST carry a
    ``@scaffold-stub: finalized-by-wave-D`` header in the first 8
    lines. Walks the canonical Wave-D stub templates Phase 4.7b
    targets."""
    from agent_team_v15.scaffold_runner import (
        _web_layout_stub_template,
        _web_middleware_stub_template,
        _web_page_stub_template,
    )

    needle = "@scaffold-stub: finalized-by-wave-D"
    for name, fn in [
        ("layout", _web_layout_stub_template),
        ("page", _web_page_stub_template),
        ("middleware", _web_middleware_stub_template),
    ]:
        content = fn()
        first_8 = "\n".join(content.splitlines()[:8])
        assert needle in first_8, (
            f"{name} stub missing @scaffold-stub header in first 8 lines:\n"
            f"{first_8}"
        )


def test_scaffold_stub_header_regex_matches_all_comment_glyphs():
    """The ``_SCAFFOLD_STUB_RE`` regex defined in audit_models.py
    matches every documented comment glyph (`//`, `#`, `--`, `*`,
    `/*`, `/**`) so JS/TS, Python, YAML, SQL, Prisma, JSDoc all
    surface the marker."""
    from agent_team_v15.audit_models import _SCAFFOLD_STUB_RE

    samples = {
        "// @scaffold-stub: finalized-by-wave-D": "D",
        "  // @scaffold-stub: finalized-by-wave-D": "D",  # leading whitespace
        "# @scaffold-stub: finalized-by-wave-B": "B",  # python / yaml
        "-- @scaffold-stub: finalized-by-wave-B": "B",  # SQL / Prisma
        "* @scaffold-stub: finalized-by-wave-D": "D",  # block-comment continuation
        "/* @scaffold-stub: finalized-by-wave-D": "D",  # block open
        "/** @scaffold-stub: finalized-by-wave-D": "D",  # JSDoc
    }
    for sample, expected_wave in samples.items():
        m = _SCAFFOLD_STUB_RE.search(sample)
        assert m is not None, f"regex failed to match: {sample!r}"
        assert m.group("wave") == expected_wave


def test_read_scaffold_stub_owner_returns_none_when_marker_absent(tmp_path):
    """``_read_scaffold_stub_owner`` returns None for files without the
    header — path-based classification falls through (Phase 4.3)."""
    from agent_team_v15.audit_models import _read_scaffold_stub_owner

    (tmp_path / "no_marker.ts").write_text("export const foo = 1;\n")
    assert _read_scaffold_stub_owner("no_marker.ts", str(tmp_path)) is None


def test_read_scaffold_stub_owner_returns_wave_letter_when_marker_present(tmp_path):
    """Header found in first 8 lines → returns the wave letter."""
    from agent_team_v15.audit_models import _read_scaffold_stub_owner

    (tmp_path / "stub.ts").write_text(
        "// @scaffold-stub: finalized-by-wave-D\n"
        "// SCAFFOLD STUB — Wave D finalizes with JWT cookie forwarding.\n"
        "export function middleware() {}\n"
    )
    assert _read_scaffold_stub_owner("stub.ts", str(tmp_path)) == "D"


def test_read_scaffold_stub_owner_handles_license_header_then_marker(tmp_path):
    """Header at line 6-8 is detected even when license + spacing
    occupy the first few lines. Per §J explicit "first 8 lines"
    contract (not 5)."""
    from agent_team_v15.audit_models import _read_scaffold_stub_owner

    (tmp_path / "stub.ts").write_text(
        "/**\n"
        " * Copyright 2026.\n"
        " * SPDX-License-Identifier: MIT\n"
        " */\n"
        "\n"
        "// @scaffold-stub: finalized-by-wave-D\n"
        "export function middleware() {}\n"
    )
    assert _read_scaffold_stub_owner("stub.ts", str(tmp_path)) == "D"


def test_read_scaffold_stub_owner_ignores_marker_past_line_8(tmp_path):
    """A marker beyond line 8 is NOT honoured (avoids accidental match
    on a long file with the literal string buried deep)."""
    from agent_team_v15.audit_models import _read_scaffold_stub_owner

    body = "\n".join([f"// padding line {i}" for i in range(20)])
    (tmp_path / "stub.ts").write_text(
        body + "\n// @scaffold-stub: finalized-by-wave-D\n"
    )
    assert _read_scaffold_stub_owner("stub.ts", str(tmp_path)) is None


def test_read_scaffold_stub_owner_handles_missing_file(tmp_path):
    """Defensive: missing file returns None (no exception leaks to the
    caller — audit-time disk reads are best-effort)."""
    from agent_team_v15.audit_models import _read_scaffold_stub_owner

    assert _read_scaffold_stub_owner("never_existed.ts", str(tmp_path)) is None


def test_audit_finding_from_dict_reads_header_when_project_root_supplied(
    tmp_path,
):
    """AC4: AuditFinding.from_dict reads stub header (when project_root
    given) and overrides path-based classification."""
    from agent_team_v15.audit_models import AuditFinding

    target = tmp_path / "some" / "obscure" / "path.ts"
    target.parent.mkdir(parents=True)
    # Path "some/obscure/..." would resolve to wave-agnostic via Phase
    # 4.3's table; the header asserts D, which must win.
    target.write_text(
        "// @scaffold-stub: finalized-by-wave-D\nexport const x = 1;\n"
    )
    finding = AuditFinding.from_dict(
        {
            "id": "F-X",
            "auditor": "scorer",
            "verdict": "FAIL",
            "severity": "CRITICAL",
            "summary": "...",
            "file_path": "some/obscure/path.ts",
        },
        project_root=str(tmp_path),
    )
    assert finding.owner_wave == "D"


def test_audit_finding_from_dict_path_based_when_no_project_root():
    """Backward-compat: legacy callers (no project_root) get pure
    path-based classification (Phase 4.3 contract)."""
    from agent_team_v15.audit_models import AuditFinding

    finding = AuditFinding.from_dict(
        {
            "id": "F-X",
            "auditor": "scorer",
            "verdict": "FAIL",
            "severity": "CRITICAL",
            "summary": "...",
            "file_path": "apps/web/src/foo.ts",
        }
    )
    assert finding.owner_wave == "D"  # path-based: apps/web → D


def test_audit_finding_from_dict_explicit_owner_wave_wins(tmp_path):
    """An EXPLICIT owner_wave in the payload always wins, even when a
    project_root + on-disk header are present (auditor-tagged
    overrides — Phase 4.3 contract preserved)."""
    from agent_team_v15.audit_models import AuditFinding

    target = tmp_path / "apps" / "web" / "src" / "foo.ts"
    target.parent.mkdir(parents=True)
    target.write_text(
        "// @scaffold-stub: finalized-by-wave-D\nexport const x = 1;\n"
    )
    finding = AuditFinding.from_dict(
        {
            "id": "F-X",
            "auditor": "scorer",
            "verdict": "FAIL",
            "severity": "CRITICAL",
            "summary": "...",
            "file_path": "apps/web/src/foo.ts",
            "owner_wave": "T",  # explicit
        },
        project_root=str(tmp_path),
    )
    assert finding.owner_wave == "T"


def test_replay_smoke_2026_04_26_middleware_finding_classified_as_deferred():
    """AC5: F-001 ('apps/web/src/middleware.ts', the SCAFFOLD STUB the
    audit graded as critical) gets ``owner_wave='D'`` via Phase 4.7b's
    stub-header reading, and Phase 4.3's ``compute_finding_status``
    promotes it to DEFERRED for the smoke's wave_progress
    (Wave D never executed)."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.scaffold_runner import _web_middleware_stub_template
    from agent_team_v15.state import RunState
    from agent_team_v15.wave_ownership import compute_finding_status

    audit_data = json.loads(SMOKE_AUDIT_REPORT.read_text(encoding="utf-8"))
    f001_dict = next(d for d in audit_data["findings"] if d.get("id") == "F-001")

    # Build a synthetic project root mirroring the post-Phase-4.7b
    # middleware.ts shape (header present). The frozen
    # tests/fixtures/smoke_2026_04_26/apps/web/src/middleware.ts
    # deliberately preserves the pre-Phase-4.7b state for replay-smoke
    # comparisons; we must not mutate it.
    with tempfile.TemporaryDirectory() as project_root:
        web_src = Path(project_root) / "apps" / "web" / "src"
        web_src.mkdir(parents=True)
        (web_src / "middleware.ts").write_text(_web_middleware_stub_template())
        finding = AuditFinding.from_dict(f001_dict, project_root=project_root)

    assert finding.owner_wave == "D", (
        f"Expected owner_wave='D' from stub header; got {finding.owner_wave!r}"
    )

    # Compose with Phase 4.3 status: when Wave D didn't execute, the
    # finding is DEFERRED.
    state = RunState(
        wave_progress={
            "milestone-1": {
                "completed_waves": ["A"],
                "failed_wave": "B",
            }
        }
    )
    status = compute_finding_status(finding, state)
    assert status == "DEFERRED", (
        f"Expected DEFERRED status (Wave D never executed); got {status!r}"
    )


def test_scaffold_stub_header_enabled_default_true():
    """Phase 4.7b kill switch defaults True (header reading active)."""
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert cfg.scaffold_stub_header_enabled is True


def test_resolve_owner_wave_with_stub_header_overrides_path(tmp_path):
    """``wave_ownership.resolve_owner_wave_with_stub_header`` lets
    callers that don't go through AuditFinding.from_dict (e.g.,
    wave_failure_forensics aggregations) still benefit from header
    awareness. Header presence overrides path-based classification."""
    from agent_team_v15.wave_ownership import resolve_owner_wave_with_stub_header

    (tmp_path / "apps" / "api" / "src").mkdir(parents=True)
    # Path "apps/api/..." resolves to B; header says D → header wins.
    (tmp_path / "apps" / "api" / "src" / "stub.ts").write_text(
        "// @scaffold-stub: finalized-by-wave-D\nexport const x = 1;\n"
    )
    assert (
        resolve_owner_wave_with_stub_header(
            "apps/api/src/stub.ts", str(tmp_path)
        )
        == "D"
    )

    # No header → path-based.
    (tmp_path / "apps" / "api" / "src" / "no_header.ts").write_text(
        "export const y = 2;\n"
    )
    assert (
        resolve_owner_wave_with_stub_header(
            "apps/api/src/no_header.ts", str(tmp_path)
        )
        == "B"
    )


def test_resolve_owner_wave_with_stub_header_returns_path_owner_when_no_root():
    """When project_root is None, falls through to path-based — no
    disk reads attempted."""
    from agent_team_v15.wave_ownership import resolve_owner_wave_with_stub_header

    assert (
        resolve_owner_wave_with_stub_header("apps/web/src/foo.ts", None) == "D"
    )
    assert (
        resolve_owner_wave_with_stub_header("apps/api/src/foo.ts", None) == "B"
    )


# -----------------------------------------------------------------------------
# Risk #31 — `.codex` sentinel exception (smoke 2026-04-27 wave-fail)
# -----------------------------------------------------------------------------


def test_codex_sentinel_in_infra_exceptions_is_wave_agnostic():
    """The Codex appserver writes a 0-byte ``.codex`` sentinel at the
    run-dir root on session start. Smoke
    ``v18 test runs/m1-hardening-smoke-20260427-213258/`` HARDFAILED
    Wave B with SCOPE-VIOLATION-001 because ``.codex`` matched no
    allowed_file_globs.

    The load-bearing fix lives in
    ``milestone_scope._UNIVERSAL_SCAFFOLD_ROOT_FILES`` (covers the
    post-wave validator). Mirroring the entry in
    ``wave_boundary._INFRA_EXCEPTIONS`` keeps the prompt-narrowing
    surface (``narrow_allowed_globs_for_wave``) consistent if a future
    planner ever emits ``.codex`` as a glob in REQUIREMENTS.md.
    """
    from agent_team_v15.wave_boundary import _INFRA_EXCEPTIONS

    assert ".codex" in _INFRA_EXCEPTIONS
    assert _INFRA_EXCEPTIONS[".codex"] == "wave-agnostic"


def test_codex_sentinel_exempt_from_post_wave_scope_validator():
    """``.codex`` is exempt from ``files_outside_scope`` regardless of
    whether the milestone's declared globs cover it. Wave-agnostic
    (Codex appserver writes the sentinel whenever it runs, which today
    is Wave B but on any future wave routed to Codex would be the
    same behavior).
    """
    from agent_team_v15.milestone_scope import (
        MilestoneScope,
        files_outside_scope,
    )

    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=["apps/api/**", "prisma/**"],
    )
    assert files_outside_scope([".codex"], scope) == []
    # Out-of-scope writes that are NOT the sentinel still flag.
    assert files_outside_scope(
        [".codex", "scripts/migrate.sh"], scope
    ) == ["scripts/migrate.sh"]
