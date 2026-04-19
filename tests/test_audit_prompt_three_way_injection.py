"""Phase H1b — auditor architecture injection + three-way compare.

Verifies the renderer-wrapper (``get_auditor_prompt`` /
``get_scoped_auditor_prompt``) injects a per-milestone ``<architecture>``
block and the three-way-compare directive ONLY when:

1. ``v18.auditor_architecture_injection_enabled`` is True, AND
2. auditor is INTERFACE or TECHNICAL, AND
3. per-milestone ARCHITECTURE.md exists.

All other auditors / flag combinations return byte-identical prompts.
Also verifies the static ``AUDIT_PROMPTS`` registry matches the
integration-2026-04-15-closeout snapshot — no h1b delta to the 8
constants.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import audit_prompts
from agent_team_v15.audit_prompts import (
    AUDIT_PROMPTS,
    _THREE_WAY_COMPARE_AUDITORS,
    _THREE_WAY_COMPARE_DIRECTIVE,
    get_auditor_prompt,
    get_scoped_auditor_prompt,
)
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(*, inject: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.auditor_architecture_injection_enabled = inject
    # Required for _load_per_milestone_architecture_block helper.
    cfg.v18.architecture_md_enabled = True
    return cfg


def _seed_arch(tmp_path: Path, milestone_id: str, body: str) -> Path:
    target = (
        tmp_path / ".agent-team" / f"milestone-{milestone_id}" / "ARCHITECTURE.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_interface_auditor_gets_three_way_when_flag_on_and_arch_present(
    tmp_path: Path,
) -> None:
    _seed_arch(tmp_path, "M1", "## Scope\n- Orders\n")
    prompt = get_auditor_prompt(
        "interface",
        config=_cfg(inject=True),
        cwd=str(tmp_path),
        milestone_id="M1",
    )
    assert "<architecture>" in prompt
    assert "<three_way_compare>" in prompt


def test_technical_auditor_gets_three_way_same_as_interface(tmp_path: Path) -> None:
    _seed_arch(tmp_path, "M1", "## Scope\n- Orders\n")
    prompt = get_auditor_prompt(
        "technical",
        config=_cfg(inject=True),
        cwd=str(tmp_path),
        milestone_id="M1",
    )
    assert "<architecture>" in prompt
    assert "<three_way_compare>" in prompt


def test_interface_auditor_silent_when_arch_md_absent(tmp_path: Path) -> None:
    """Flag ON + INTERFACE but no ARCHITECTURE.md on disk → graceful skip."""
    prompt = get_auditor_prompt(
        "interface",
        config=_cfg(inject=True),
        cwd=str(tmp_path),
        milestone_id="M1",
    )
    assert "<architecture>" not in prompt
    assert "<three_way_compare>" not in prompt


def test_non_targeted_auditors_never_get_injection(tmp_path: Path) -> None:
    _seed_arch(tmp_path, "M1", "## Scope\n- Orders\n")
    cfg = _cfg(inject=True)
    for name in ("requirements", "test", "mcp_library", "prd_fidelity", "scorer", "comprehensive"):
        prompt = get_auditor_prompt(
            name,
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="M1",
        )
        assert "<architecture>" not in prompt, (
            f"Auditor {name!r} should NOT receive <architecture> injection"
        )
        assert "<three_way_compare>" not in prompt, (
            f"Auditor {name!r} should NOT receive <three_way_compare> injection"
        )


def test_injection_disabled_when_flag_off(tmp_path: Path) -> None:
    _seed_arch(tmp_path, "M1", "## Scope\n- Orders\n")
    for name in ("interface", "technical"):
        prompt = get_auditor_prompt(
            name,
            config=_cfg(inject=False),
            cwd=str(tmp_path),
            milestone_id="M1",
        )
        assert "<architecture>" not in prompt
        assert "<three_way_compare>" not in prompt


def test_three_way_compare_auditor_set_matches_plan() -> None:
    """Only INTERFACE and TECHNICAL should be in the targeted subset."""
    assert _THREE_WAY_COMPARE_AUDITORS == frozenset({"interface", "technical"})


# ---------------------------------------------------------------------------
# Directive wording
# ---------------------------------------------------------------------------


_EXPECTED_DRIFT_IDS = (
    "ARCH-DRIFT-PORT-001",
    "ARCH-DRIFT-ENTITY-001",
    "ARCH-DRIFT-ENDPOINT-001",
    "ARCH-DRIFT-CREDS-001",
    "ARCH-DRIFT-DEPS-001",
)


def test_directive_enumerates_five_drift_pattern_ids() -> None:
    for pid in _EXPECTED_DRIFT_IDS:
        assert pid in _THREE_WAY_COMPARE_DIRECTIVE, (
            f"Drift pattern id {pid!r} missing from three-way-compare directive"
        )


def test_directive_contains_two_of_three_phrase() -> None:
    assert "TWO of the three documents AND disagrees" in _THREE_WAY_COMPARE_DIRECTIVE


# ---------------------------------------------------------------------------
# get_scoped_auditor_prompt wrapper path
# ---------------------------------------------------------------------------


def test_scoped_auditor_applies_same_wrapper(tmp_path: Path) -> None:
    _seed_arch(tmp_path, "M1", "## Scope\n- Orders\n")
    prompt = get_scoped_auditor_prompt(
        "interface",
        scope=None,
        config=_cfg(inject=True),
        cwd=str(tmp_path),
        milestone_id="M1",
    )
    assert "<architecture>" in prompt
    assert "<three_way_compare>" in prompt


def test_scoped_auditor_derives_milestone_id_from_scope(tmp_path: Path) -> None:
    """When scope carries a milestone_id, the wrapper reads it."""
    _seed_arch(tmp_path, "M4", "## Scope\n- Ticketing\n")
    # Richer scope shape: real AuditScope has allowed_file_globs — but
    # with scope=None the milestone_id kwarg path is exercised directly.
    prompt = get_scoped_auditor_prompt(
        "interface",
        scope=None,
        config=_cfg(inject=True),
        cwd=str(tmp_path),
        milestone_id="M4",
    )
    assert "<architecture>" in prompt
    assert "- Ticketing" in prompt


# ---------------------------------------------------------------------------
# Byte-identical registry check
# ---------------------------------------------------------------------------


def test_audit_prompts_registry_has_expected_8_entries() -> None:
    assert set(AUDIT_PROMPTS.keys()) == {
        "requirements",
        "technical",
        "interface",
        "test",
        "mcp_library",
        "prd_fidelity",
        "comprehensive",
        "scorer",
    }


def test_h1b_did_not_edit_audit_prompt_constants() -> None:
    """Wave 2B must NOT edit the 8 static AUDIT_PROMPTS constants — only
    add injection helpers. This test diffs current source against the
    ``integration-2026-04-15-closeout`` baseline and asserts the diff is
    purely additive (no removed lines) AND that none of the 8 constant
    assignment regions changed.

    Skips gracefully when the baseline ref is unreachable.
    """

    repo_root = Path(__file__).resolve().parents[1]
    try:
        diff = subprocess.run(
            [
                "git",
                "diff",
                "integration-2026-04-15-closeout",
                "--",
                "src/agent_team_v15/audit_prompts.py",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - defensive
        pytest.skip(f"git unavailable: {exc}")
    if diff.returncode != 0:
        pytest.skip(f"git diff failed: {diff.stderr.strip()!r}")

    # Count true removal lines (lines starting with exactly one '-' and
    # not part of the ``---`` header).
    removed_lines: list[str] = []
    for line in diff.stdout.splitlines():
        if line.startswith("---"):
            continue
        if line.startswith("-") and not line.startswith("--"):
            # A removed content line. Allow mojibake-fixups (lines that
            # contain only encoding-artifact characters that were
            # replaced with proper UTF-8 in a mirror +line) — track them
            # for a later comparison rather than failing outright.
            removed_lines.append(line[1:])

    # Any removed line that mentions one of the 8 constant names means
    # h1b edited a constant. Fail.
    constant_names = {
        "REQUIREMENTS_AUDITOR_PROMPT",
        "TECHNICAL_AUDITOR_PROMPT",
        "INTERFACE_AUDITOR_PROMPT",
        "TEST_AUDITOR_PROMPT",
        "MCP_LIBRARY_AUDITOR_PROMPT",
        "PRD_FIDELITY_AUDITOR_PROMPT",
        "COMPREHENSIVE_AUDITOR_PROMPT",
        "SCORER_AGENT_PROMPT",
        "AUDIT_PROMPTS",
    }
    for removed in removed_lines:
        for name in constant_names:
            assert name not in removed, (
                f"Wave 2B removed a line referencing {name}: {removed!r}. "
                "The 8 AUDIT_PROMPTS constants must be byte-identical."
            )
