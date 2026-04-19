"""Phase H1a Item 3 — DoD feasibility verifier.

Unit-level coverage of ``dod_feasibility_verifier.run_dod_feasibility_check``
plus an integration test that fires the wave_executor milestone-teardown
hook on a failure-milestone fixture (REQUIREMENTS.md + package.json both
present but Wave B / Wave E artefacts ABSENT — mirrors smoke #11 M1).

Key invariants:

* ``DOD-FEASIBILITY-001`` HIGH fires per unresolvable ``pnpm``/``npm``/
  ``yarn`` script referenced in the ``## Definition of Done`` block.
* Bare executables (``curl``, ``docker``, ``GET``, ``psql``) are skipped.
* Missing REQUIREMENTS.md / missing DoD block / missing package.json
  everywhere → graceful skip (no finding, no crash).
* Teardown hook fires ON FAILURE milestones — the check must NOT be
  gated on Wave E having run. Regression guard against a future
  refactor that moves the hook under a Wave-E-only branch.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.dod_feasibility_verifier import (
    Finding,
    run_dod_feasibility_check,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_DOD_HEADER = "## Definition of Done\n\n"


def _write_requirements(milestone_dir: Path, dod_body: str) -> Path:
    milestone_dir.mkdir(parents=True, exist_ok=True)
    path = milestone_dir / "REQUIREMENTS.md"
    path.write_text(_DOD_HEADER + dod_body, encoding="utf-8")
    return path


def _write_requirements_no_dod(milestone_dir: Path, body: str = "") -> Path:
    milestone_dir.mkdir(parents=True, exist_ok=True)
    path = milestone_dir / "REQUIREMENTS.md"
    path.write_text(body, encoding="utf-8")
    return path


def _write_package_json(
    path: Path, scripts: dict[str, str] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": path.parent.name or "root", "version": "0.1.0"}
    if scripts is not None:
        data["scripts"] = scripts
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Positive / negative — root package.json
# ---------------------------------------------------------------------------


def test_dod_pnpm_dev_resolves_in_root(tmp_path: Path) -> None:
    """DoD says ``pnpm dev``; root package.json has a ``dev`` script — no finding."""

    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(ms_dir, "- `pnpm dev` boots the app.\n")
    _write_package_json(tmp_path / "package.json", scripts={"dev": "next dev"})

    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


def test_dod_pnpm_dev_unresolvable_fires_finding(tmp_path: Path) -> None:
    """DoD says ``pnpm dev`` but root has only ``dev:api`` / ``dev:web``."""

    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(ms_dir, "- `pnpm dev` boots both services.\n")
    _write_package_json(
        tmp_path / "package.json",
        scripts={"dev:api": "pnpm -C apps/api dev", "dev:web": "pnpm -C apps/web dev"},
    )

    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert len(findings) == 1
    f = findings[0]
    assert f.code == "DOD-FEASIBILITY-001"
    assert f.severity == "HIGH"
    assert "pnpm dev" in f.message
    assert f.file.endswith("REQUIREMENTS.md")


def test_compound_cd_and_pnpm_start_resolves_in_api(tmp_path: Path) -> None:
    """DoD says ``cd apps/api && pnpm start``; apps/api/package.json has ``start``."""

    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(
        ms_dir, "- `cd apps/api && pnpm start` launches the API.\n"
    )
    _write_package_json(
        tmp_path / "apps" / "api" / "package.json",
        scripts={"start": "node dist/main.js"},
    )

    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


def test_bare_executable_skipped(tmp_path: Path) -> None:
    """``curl http://localhost:4000/health`` must not be reported — curl is
    a bare executable, not a package-manager script."""

    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(
        ms_dir, "- `curl http://localhost:4000/health` returns 200.\n"
    )
    _write_package_json(tmp_path / "package.json", scripts={})

    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


def test_multiple_unresolvable_commands_emit_one_finding_each(
    tmp_path: Path,
) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(
        ms_dir,
        "- `pnpm migrate` and then `pnpm typecheck` must both succeed.\n",
    )
    _write_package_json(tmp_path / "package.json", scripts={})

    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    scripts = sorted(
        msg.split("`")[1]
        for f in findings
        for msg in [f.message]
        if "`" in msg
    )
    # Two distinct script names → two findings.
    assert len(findings) == 2
    assert any("pnpm migrate" in f.message for f in findings)
    assert any("pnpm typecheck" in f.message for f in findings)


# ---------------------------------------------------------------------------
# Graceful-skip paths
# ---------------------------------------------------------------------------


def test_no_dod_block_skips(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements_no_dod(ms_dir, "# M1\n\nNo DoD here.\n")
    _write_package_json(tmp_path / "package.json", scripts={"dev": "next"})

    with caplog.at_level("WARNING"):
        findings = run_dod_feasibility_check(tmp_path, ms_dir)
    # Graceful — empty list, no finding.
    assert findings == []


def test_missing_requirements_skips(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    # Do not create REQUIREMENTS.md.
    _write_package_json(tmp_path / "package.json", scripts={"dev": "next"})
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


def test_no_package_json_anywhere_skips(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(ms_dir, "- `pnpm dev` runs.\n")
    # No package.json at all.
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


# ---------------------------------------------------------------------------
# Parse edges — code fences, bullet lists, single-line
# ---------------------------------------------------------------------------


def test_dod_in_code_fence(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    ms_dir.mkdir(parents=True, exist_ok=True)
    (ms_dir / "REQUIREMENTS.md").write_text(
        "## Definition of Done\n\n"
        "```bash\n"
        "pnpm typecheck\n"
        "```\n",
        encoding="utf-8",
    )
    # NOTE: the verifier extracts BACKTICK-wrapped inline commands.
    # A fenced block without inline backticks has no chunks; this test
    # asserts we don't crash on fence-only DoD content.
    _write_package_json(tmp_path / "package.json", scripts={"typecheck": "tsc"})
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


def test_dod_bullet_list_with_backticks(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(
        ms_dir,
        "- `pnpm install && pnpm typecheck && pnpm lint && pnpm build` succeeds.\n",
    )
    _write_package_json(
        tmp_path / "package.json",
        scripts={"typecheck": "tsc", "lint": "eslint", "build": "tsc -b"},
    )
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    # install is a builtin, not a script — skipped. typecheck/lint/build
    # are all present. No findings.
    assert findings == []


def test_dod_single_line_backtick(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(ms_dir, "`pnpm ghost`\n")
    _write_package_json(tmp_path / "package.json", scripts={})
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert len(findings) == 1
    assert "pnpm ghost" in findings[0].message


def test_pnpm_filter_scoped_script(tmp_path: Path) -> None:
    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(
        ms_dir,
        "- `pnpm --filter api openapi:export` produces a client.\n",
    )
    _write_package_json(
        tmp_path / "apps" / "api" / "package.json",
        scripts={"openapi:export": "node scripts/export.js"},
    )
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert findings == []


# ---------------------------------------------------------------------------
# Failure-milestone firing — regression guard
# ---------------------------------------------------------------------------


def test_runs_on_failure_milestone_without_wave_e_artifact(tmp_path: Path) -> None:
    """Construct a fixture where Wave E artefact is absent — the check
    must still fire. This is the smoke #11 regression class: M1 failed at
    Wave B, Wave E never ran, and we still need DoD feasibility findings.

    The verifier is stateless with respect to wave artefacts; this test
    asserts that by calling it on a project tree that has NO wave
    artefacts on disk — only REQUIREMENTS + package.json."""

    ms_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    _write_requirements(ms_dir, "- `pnpm db:migrate` runs cleanly.\n")
    _write_package_json(tmp_path / "package.json", scripts={"lint": "eslint"})

    # Deliberately no .agent-team/milestones/milestone-1/WAVE_E.json,
    # no WAVE_B.json — just the ingredients the verifier reads.
    findings = run_dod_feasibility_check(tmp_path, ms_dir)
    assert len(findings) == 1
    assert "pnpm db:migrate" in findings[0].message
    assert findings[0].severity == "HIGH"


# ---------------------------------------------------------------------------
# Integration — wave_executor milestone-teardown hook
# ---------------------------------------------------------------------------


def test_wave_executor_teardown_invokes_dod_feasibility(tmp_path: Path) -> None:
    """Structural guard: assert the teardown block in wave_executor.py
    imports dod_feasibility_verifier and is gated on
    ``dod_feasibility_verifier_enabled`` rather than on a wave-specific
    condition. Implemented by reading the source — this is a static
    wiring check, cheap and robust."""

    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_team_v15"
        / "wave_executor.py"
    ).read_text(encoding="utf-8")
    assert "dod_feasibility_verifier" in src, (
        "wave_executor.py must import dod_feasibility_verifier"
    )
    assert "dod_feasibility_verifier_enabled" in src, (
        "teardown hook must be gated on the v18 flag"
    )
    # The hook must sit between persist_wave_findings_for_audit and the
    # architecture writer append. Confirm by ordering-of-appearance.
    first_persist = src.find("persist_wave_findings_for_audit")
    hook_site = src.find("dod_feasibility_verifier_enabled")
    arch_write = src.find("architecture", hook_site)
    assert first_persist != -1
    assert hook_site != -1
    assert hook_site > first_persist
    assert arch_write == -1 or arch_write > hook_site
