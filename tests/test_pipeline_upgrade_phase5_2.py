"""Phase 5.2 pipeline-upgrade — audit-team plumbing fix.

Closes:

* **R-#36** — audit-dispatch path drift (TWO planned sites at
  ``cli.py:5037`` + ``cli.py:5534-5535``; widened during implementation
  to cover ``cli.py:6277`` (guard) + ``cli.py:6283-6284`` (third
  dispatch site) per Option A reading of §M.M9 enumeration mandate).
* **R-#46** — audit subagent definitions are built but discarded.
  ``_build_options`` now accepts a keyword-only ``agent_defs_override``
  that merges the auditor agent map into ``ClaudeAgentOptions.agents``.
* **R-#47** — audit-* auditors lack ``Write``. Tools list extended to
  include ``Write`` for every ``audit-*`` agent that persists findings
  inline, and the new ``audit_output_path_guard`` PreToolUse hook
  bounds the scope of those writes via ``AGENT_TEAM_AUDIT_WRITER=1``
  + ``AGENT_TEAM_AUDIT_OUTPUT_ROOT`` + ``AGENT_TEAM_AUDIT_REQUIREMENTS_PATH``.

Acceptance criteria — see ``docs/plans/2026-04-28-phase-5-quality-milestone.md``
§E.5 + §E.6:

* AC1 — every per-milestone audit-dispatch construction in cli.py
  contains the ``"milestones"`` segment between ``req_dir`` and
  ``milestone.id``.
* AC2 — replay synthetic — ``Path(audit_dir) / "AUDIT_REPORT.json"``
  resolves to a canonical path that audit-team Claude can write to.
* AC3 — natural-completion path (cli.py:2280 reference site) is
  unchanged.
* AC4 — lint test (``test_audit_dispatch_path_construction.py``)
  passes at HEAD; fails on synthetic regression.
* AC5 — **DEFERRED to live M1 smoke** (gated on operator authorisation
  per §0.1.13).
* AC6 — ``_build_options(agent_defs_override=...)`` merges the
  override into ``ClaudeAgentOptions.agents`` as ``AgentDefinition``
  objects.
* AC7 — no positional-``None`` ``_build_options`` call remains inside
  ``_run_milestone_audit``.
* AC8 — integration audit (``auditors_override=["interface"]``)
  injects ``audit-interface`` into ``ClaudeAgentOptions.agents``.
* AC9 — every ``audit-*`` key returned by
  ``build_auditor_agent_definitions`` (excluding ``audit-scorer`` whose
  contract is unchanged) includes ``Write`` in its ``tools`` list.
* AC10 — ``audit_output_path_guard`` allows ``Write`` to
  ``{audit_dir}/audit-*_findings.json``, ``{audit_dir}/AUDIT_REPORT.json``,
  and ``Edit`` to ``requirements_path`` when audit env is active.
* AC11 — guard denies ``Write`` to a project source file
  (``apps/api/src/main.ts``) while audit env is active.
* AC12 — guard is a deterministic no-op outside audit env.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15.agent_teams_backend import AgentTeamsBackend
from agent_team_v15.audit_team import (
    AUDITOR_NAMES,
    build_auditor_agent_definitions,
)
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_PATH = _REPO_ROOT / "src" / "agent_team_v15" / "cli.py"
_HOOK_MODULE = "agent_team_v15.audit_output_path_guard"


def _run_audit_output_hook(
    payload: dict,
    *,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Invoke the audit-output path-guard hook as a subprocess —
    matches the runtime CLI flow.

    Returns ``(returncode, stdout, stderr)``.
    """
    base_env = {**os.environ}
    if env:
        for key, value in env.items():
            if value is None:
                base_env.pop(key, None)
            else:
                base_env[key] = value
    proc = subprocess.run(
        [sys.executable, "-m", _HOOK_MODULE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=base_env,
        timeout=15,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _hook_decision(stdout: str) -> str:
    """Parse hook stdout into a ``"allow"`` / ``"deny"`` /
    ``"unspecified"`` outcome. Empty stdout (``{}`` payload) is
    canonical allow per the wave-d / audit-fix envelope."""
    if not stdout or stdout == "{}":
        return "allow"
    payload = json.loads(stdout)
    decision = (
        payload.get("hookSpecificOutput", {}).get("permissionDecision")
        or "unspecified"
    )
    return str(decision)


# ---------------------------------------------------------------------------
# AC1 — path construction at every per-milestone audit-dispatch site
# ---------------------------------------------------------------------------


class TestAC1AuditDispatchPathConstruction:
    """Every per-milestone audit-dispatch path construction in cli.py
    must include the ``"milestones"`` segment between ``req_dir`` and
    ``milestone.id``. Locked source-shape regexes; line numbers are
    intentionally not asserted because future refactors may move the
    sites without breaking the contract."""

    def setup_method(self) -> None:
        self.cli_text = _CLI_PATH.read_text(encoding="utf-8")

    def test_canonical_direct_assignment_shape(self) -> None:
        """Catches the post-fix shape at cli.py:5037, 5534, 5535,
        6283 — direct ``X=str(req_dir / "milestones" / milestone.id / ...)``."""
        pattern = re.compile(
            r'(?:requirements_path|audit_dir|ms_audit_dir|ms_req_path)'
            r'\s*=\s*str\(\s*req_dir\s*/\s*"milestones"\s*/\s*milestone\.id\s*/',
            re.MULTILINE,
        )
        matches = pattern.findall(self.cli_text)
        assert len(matches) >= 4, (
            f"Expected at least 4 canonical direct-assignment sites "
            f"(5037, 5534, 5535, 6283); found {len(matches)}."
        )

    def test_canonical_conditional_fallback_shape(self) -> None:
        """Catches the post-fix shape at cli.py:5035 + 6284 —
        ``... else str(req_dir / "milestones" / milestone.id / ...)``."""
        pattern = re.compile(
            r'else\s+str\(\s*req_dir\s*/\s*"milestones"\s*/\s*milestone\.id\s*/',
            re.MULTILINE,
        )
        matches = pattern.findall(self.cli_text)
        assert len(matches) >= 2, (
            f"Expected at least 2 canonical conditional-fallback sites "
            f"(5035, 6284); found {len(matches)}."
        )

    def test_canonical_is_file_guard_shape(self) -> None:
        """Catches the post-fix shape at cli.py:6277 — the natural-
        completion ``_ms_audit_already_done`` guard. Coupled to the
        same canonical contract per Option A."""
        pattern = re.compile(
            r'\(\s*req_dir\s*/\s*"milestones"\s*/\s*milestone\.id\s*/'
            r'\s*"\.agent-team"\s*/\s*"AUDIT_REPORT\.json"\s*\)\s*\.is_file\(\)',
            re.MULTILINE,
        )
        matches = pattern.findall(self.cli_text)
        assert len(matches) >= 1, (
            f"Expected at least 1 canonical is_file guard site (6277); "
            f"found {len(matches)}."
        )


# ---------------------------------------------------------------------------
# AC2 — replay synthetic: AUDIT_REPORT.json at canonical path resolves
# ---------------------------------------------------------------------------


class TestAC2ReplayCanonicalAuditReportPath:
    """A synthetic run-dir with ``AUDIT_REPORT.json`` at the canonical
    Phase 5.2 path is found by ``Path(audit_dir) / "AUDIT_REPORT.json"``.

    Replay-shape: the post-fix ``audit_dir`` construction at cli.py:5535
    + 6283 produces ``<run-dir>/.agent-team/milestones/<id>/.agent-team``.
    The Phase 4 consumers at cli.py:6967 + cli.py:8374 + cli.py:8114
    look at ``Path(audit_dir) / "AUDIT_REPORT.json"`` — this resolves
    to the canonical write path that audit-team Claude now targets.
    """

    def test_replay_smoke_canonical_audit_report_path_resolves(
        self, tmp_path: Path
    ) -> None:
        req_dir = tmp_path / ".agent-team"
        milestone_id = "milestone-1"
        canonical_audit_dir = (
            req_dir / "milestones" / milestone_id / ".agent-team"
        )
        canonical_audit_dir.mkdir(parents=True)
        canonical_report = canonical_audit_dir / "AUDIT_REPORT.json"
        canonical_report.write_text(
            json.dumps(
                {
                    "score": {
                        "score": 100.0,
                        "max_score": 100,
                        "critical_count": 0,
                        "high_count": 0,
                        "medium_count": 0,
                        "low_count": 0,
                        "info_count": 0,
                        "total_items": 0,
                        "passed": 0,
                        "failed": 0,
                        "partial": 0,
                        "health": "healthy",
                    },
                    "findings": [],
                }
            ),
            encoding="utf-8",
        )

        # Mirror the post-Phase-5.2 construction (cli.py:5535 / 6283).
        audit_dir = str(req_dir / "milestones" / milestone_id / ".agent-team")
        report_path = Path(audit_dir) / "AUDIT_REPORT.json"
        assert report_path.is_file()
        assert report_path == canonical_report

        # Pre-Phase-5.2 buggy construction (the nested-path shape that
        # the smoke evidence captured) does NOT resolve to a real file.
        buggy_audit_dir = str(req_dir / milestone_id / ".agent-team")
        buggy_report_path = Path(buggy_audit_dir) / "AUDIT_REPORT.json"
        assert not buggy_report_path.is_file()


# ---------------------------------------------------------------------------
# AC3 — natural-completion cli.py:2280 reference site is unchanged
# ---------------------------------------------------------------------------


class TestAC3NaturalCompletionPathUnchanged:
    """Phase 5.2 only modifies the broken sites enumerated in §E.4 +
    Option A scope-widening. The canonical reference site at cli.py:2280
    must remain byte-identical so Phase 4 natural-completion behaviour
    is unaffected."""

    def test_cli_2280_reference_site_unchanged(self) -> None:
        cli_text = _CLI_PATH.read_text(encoding="utf-8")
        canonical_line = (
            'audit_dir = str(req_dir / "milestones" / milestone.id / '
            '".agent-team")'
        )
        assert canonical_line in cli_text, (
            "cli.py:2280 reference site (canonical natural-completion "
            "audit_dir construction) must be present after Phase 5.2."
        )


# ---------------------------------------------------------------------------
# AC4 — lint pass + synthetic-regression fail
# ---------------------------------------------------------------------------


class TestAC4LintRegressionContract:
    """The lint test passes at HEAD post-Phase-5.2 (no buggy shapes
    remain) AND fails on a synthetic source where one site is reverted
    (proves the lint actually catches the bug class)."""

    def test_lint_passes_at_head(self) -> None:
        from tests.test_audit_dispatch_path_construction import (
            test_no_audit_dispatch_site_omits_milestones_segment,
        )

        # If the production cli.py contains any buggy shapes, this
        # raises AssertionError — pytest treats raised AssertionError
        # as a test failure.
        test_no_audit_dispatch_site_omits_milestones_segment()

    def test_lint_fails_on_synthetic_regression_direct(self) -> None:
        """Synthetic buggy text (mirrors cli.py:5037 pre-fix shape).
        The lint regex MUST catch this so future regressions fail CI."""
        from tests.test_audit_dispatch_path_construction import _BAD_PATTERN

        synthetic_buggy = (
            'audit_dir=str(req_dir / milestone.id / ".agent-team"),\n'
        )
        matches = _BAD_PATTERN.findall(synthetic_buggy)
        assert len(matches) == 1, (
            "Lint must catch the direct-assignment buggy shape; "
            f"got {len(matches)} matches."
        )

    def test_lint_fails_on_synthetic_regression_conditional(self) -> None:
        """Synthetic buggy text (mirrors cli.py:5035 + 6284 fallback shape)."""
        from tests.test_audit_dispatch_path_construction import _BAD_PATTERN

        synthetic_buggy = (
            'else str(req_dir / milestone.id / "REQUIREMENTS.md")\n'
        )
        matches = _BAD_PATTERN.findall(synthetic_buggy)
        assert len(matches) == 1, (
            "Lint must catch the parenthesized-conditional buggy shape; "
            f"got {len(matches)} matches."
        )

    def test_lint_fails_on_synthetic_regression_is_file(self) -> None:
        """Synthetic buggy text (mirrors cli.py:6277 guard shape)."""
        from tests.test_audit_dispatch_path_construction import _BAD_PATTERN

        synthetic_buggy = (
            '(req_dir / milestone.id / ".agent-team" / '
            '"AUDIT_REPORT.json").is_file()\n'
        )
        matches = _BAD_PATTERN.findall(synthetic_buggy)
        assert len(matches) == 1, (
            "Lint must catch the is_file-guard buggy shape; "
            f"got {len(matches)} matches."
        )


# ---------------------------------------------------------------------------
# AC4-bis — guard fixture: post-Phase-5.2, the canonical AUDIT_REPORT.json
# guard suppresses double-dispatch in team mode.
# ---------------------------------------------------------------------------


class TestAC4BisGuardSuppressesDoubleDispatch:
    """Per the user's Option A direction: when ``_use_team_mode`` is
    true and ``AUDIT_REPORT.json`` exists at the canonical path, the
    natural-completion ``_run_audit_loop`` dispatch must NOT fire.

    Pre-Phase-5.2 the guard checked the nested non-canonical path so
    audit-lead's canonical-path write was invisible to it. Post-fix
    the guard checks the canonical path; an existing report short-
    circuits the dispatch site at cli.py:6285+. Verified by
    constructing the canonical path on disk and asserting the guard
    expression evaluates True."""

    def test_canonical_audit_report_guard_returns_true_when_present(
        self, tmp_path: Path
    ) -> None:
        # Build the canonical run-dir.
        req_dir = tmp_path / ".agent-team"
        milestone_id = "milestone-1"
        canonical_audit_dir = (
            req_dir / "milestones" / milestone_id / ".agent-team"
        )
        canonical_audit_dir.mkdir(parents=True)
        canonical_report = canonical_audit_dir / "AUDIT_REPORT.json"
        canonical_report.write_text("{}", encoding="utf-8")

        # Mirror the post-Phase-5.2 guard expression at cli.py:6275-6278:
        #   _ms_audit_already_done = (
        #       _use_team_mode
        #       and (req_dir / "milestones" / milestone.id / ".agent-team" / "AUDIT_REPORT.json").is_file()
        #   )
        guard = (
            req_dir
            / "milestones"
            / milestone_id
            / ".agent-team"
            / "AUDIT_REPORT.json"
        ).is_file()
        assert guard is True

        # The pre-Phase-5.2 nested-path shape would NOT see this file.
        buggy_guard = (
            req_dir
            / milestone_id
            / ".agent-team"
            / "AUDIT_REPORT.json"
        ).is_file()
        assert buggy_guard is False

    def test_canonical_audit_report_guard_returns_false_when_absent(
        self, tmp_path: Path
    ) -> None:
        """Without an existing AUDIT_REPORT.json, the guard returns
        False so the dispatch fires — same shape as pre-Phase-5.2 but
        now using the correct path."""
        req_dir = tmp_path / ".agent-team"
        milestone_id = "milestone-1"
        # Make the parent dirs but NOT the report file.
        canonical_audit_dir = (
            req_dir / "milestones" / milestone_id / ".agent-team"
        )
        canonical_audit_dir.mkdir(parents=True)

        guard = (
            req_dir
            / "milestones"
            / milestone_id
            / ".agent-team"
            / "AUDIT_REPORT.json"
        ).is_file()
        assert guard is False


# ---------------------------------------------------------------------------
# AC6 — _build_options merges agent_defs_override into ClaudeAgentOptions.agents
# ---------------------------------------------------------------------------


class TestAC6BuildOptionsAgentDefsOverride:
    """``_build_options(agent_defs_override=...)`` merges the override
    keys into the orchestrator agent map BEFORE the ``AgentDefinition``
    cast — the resulting ``ClaudeAgentOptions.agents`` dict contains
    both the orchestrator's base agents (project-architect, etc.) AND
    the overrides (audit-test, audit-mcp-library, etc.) as
    ``AgentDefinition`` instances."""

    def _audit_def(self, name: str, *, with_write: bool = True) -> dict[str, Any]:
        tools = ["Read", "Write", "Glob", "Grep"] if with_write else [
            "Read",
            "Glob",
            "Grep",
        ]
        return {
            "description": f"audit-team {name} auditor (Phase 5.2 fixture)",
            "prompt": f"You are the {name} auditor. Test fixture body.",
            "tools": tools,
            "model": "opus",
        }

    def test_audit_keys_injected_into_agents(self) -> None:
        from claude_agent_sdk import AgentDefinition

        cfg = AgentTeamConfig()
        override = {
            "audit-test": self._audit_def("test"),
            "audit-mcp-library": self._audit_def("mcp_library"),
            "audit-scorer": self._audit_def("scorer"),
        }

        opts = cli_module._build_options(
            cfg,
            cwd=None,
            task_text="phase 5.2 fixture",
            depth="standard",
            agent_defs_override=override,
        )

        agents = getattr(opts, "agents", None) or {}
        for key in ("audit-test", "audit-mcp-library", "audit-scorer"):
            assert key in agents, (
                f"audit-* key {key!r} missing from ClaudeAgentOptions.agents; "
                f"agent_defs_override was discarded."
            )
            assert isinstance(agents[key], AgentDefinition), (
                f"audit-* key {key!r} present but not cast to "
                f"AgentDefinition; got {type(agents[key]).__name__}."
            )

    def test_no_override_is_noop(self) -> None:
        """Outside the audit dispatch (override=None or omitted), the
        orchestrator agent map is byte-identical to the pre-Phase-5.2
        build."""
        cfg = AgentTeamConfig()
        opts_default = cli_module._build_options(
            cfg, cwd=None, task_text="phase 5.2 fixture", depth="standard"
        )
        opts_none = cli_module._build_options(
            cfg,
            cwd=None,
            task_text="phase 5.2 fixture",
            depth="standard",
            agent_defs_override=None,
        )
        assert set(opts_default.agents.keys()) == set(opts_none.agents.keys())


# ---------------------------------------------------------------------------
# AC7 — no positional-None _build_options call remains in _run_milestone_audit
# ---------------------------------------------------------------------------


class TestAC7NoPositionalNoneBuildOptionsCall:
    """The pre-Phase-5.2 audit dispatch passed ``None`` as the second
    positional arg to ``_build_options`` — that slot is ``cwd``, so
    the call worked but discarded the audit-agent definitions silently
    (R-#46 root cause). Phase 5.2 rewrites the dispatch to keyword-
    only form. This test locks the contract."""

    def test_run_milestone_audit_uses_keyword_only_cwd_and_override(
        self,
    ) -> None:
        cli_text = _CLI_PATH.read_text(encoding="utf-8")
        # Locate the _run_milestone_audit body (named function)
        # and assert the _build_options call inside it uses kwargs.
        # Find the function span heuristically.
        pattern = re.compile(
            r"async\s+def\s+_run_milestone_audit\b.*?(?=\nasync\s+def\s|\ndef\s|\Z)",
            re.DOTALL,
        )
        match = pattern.search(cli_text)
        assert match is not None, (
            "_run_milestone_audit not found in cli.py — surface drift; "
            "update the test target."
        )
        body = match.group(0)

        # No positional-None pattern after `_build_options(config,`.
        positional_none = re.compile(
            r"_build_options\(\s*config\s*,\s*None\b",
            re.MULTILINE,
        )
        assert not positional_none.search(body), (
            "_run_milestone_audit still contains the pre-Phase-5.2 "
            "positional-None _build_options call; rewrite to "
            "_build_options(config, cwd=None, ..., agent_defs_override=...)."
        )

        # Keyword form with both cwd=None and agent_defs_override=
        # must be present.
        canonical_call = re.compile(
            r"_build_options\(\s*config\s*,\s*cwd\s*=\s*None\b.*?"
            r"agent_defs_override\s*=\s*agent_defs",
            re.DOTALL,
        )
        assert canonical_call.search(body), (
            "_run_milestone_audit must call _build_options with "
            "cwd=None keyword AND agent_defs_override=agent_defs "
            "keyword (Phase 5.2 R-#46 contract)."
        )


# ---------------------------------------------------------------------------
# AC8 — integration audit injects audit-interface
# ---------------------------------------------------------------------------


class TestAC8IntegrationAuditInjectsInterface:
    """The integration audit at cli.py:6692-6702 calls
    ``_run_milestone_audit(... auditors_override=["interface"])``.
    The internal ``build_auditor_agent_definitions(["interface"], ...)``
    returns an ``audit-interface`` key (plus ``audit-comprehensive``
    and ``audit-scorer``); these are passed via ``agent_defs_override``
    and reach ``ClaudeAgentOptions.agents``."""

    def test_build_auditor_agent_definitions_interface_only_includes_audit_interface(
        self,
    ) -> None:
        agents = build_auditor_agent_definitions(["interface"])
        assert "audit-interface" in agents
        # Comprehensive auditor is always added when not in the slice.
        assert "audit-comprehensive" in agents
        # Scorer is always added.
        assert "audit-scorer" in agents

    def test_interface_only_definition_reaches_agent_options(self) -> None:
        from claude_agent_sdk import AgentDefinition

        cfg = AgentTeamConfig()
        agent_defs = build_auditor_agent_definitions(["interface"])
        opts = cli_module._build_options(
            cfg,
            cwd=None,
            task_text="integration audit",
            depth="standard",
            agent_defs_override=agent_defs,
        )
        assert "audit-interface" in opts.agents
        assert isinstance(opts.agents["audit-interface"], AgentDefinition)


# ---------------------------------------------------------------------------
# AC9 — every audit-* (excluding audit-scorer) carries Write
# ---------------------------------------------------------------------------


class TestAC9AuditAgentsCarryWrite:
    """``audit-*`` agents must be able to persist findings inline.
    Phase 5.2 adds ``Write`` to every specialized auditor and to
    ``audit-comprehensive``. ``audit-scorer`` (which already had
    ``Write`` + ``Edit``) is unchanged."""

    def test_specialized_auditors_have_write(self) -> None:
        # Use ALL specialized auditor names so the contract is exercised
        # against the full surface, not just one auditor.
        auditors = list(AUDITOR_NAMES)
        agents = build_auditor_agent_definitions(auditors)
        # Filter out the comprehensive + scorer (auto-added, separately
        # asserted below).
        for auditor_name in auditors:
            if auditor_name in {"comprehensive", "scorer"}:
                continue
            agent_key = f"audit-{auditor_name.replace('_', '-')}"
            if agent_key not in agents:
                # Some auditors may be skipped (e.g., prd_fidelity when
                # no prd_path is supplied); skip in that case.
                continue
            assert "Write" in agents[agent_key]["tools"], (
                f"{agent_key} tools list missing 'Write' (Phase 5.2 R-#47)."
            )

    def test_audit_comprehensive_has_write(self) -> None:
        agents = build_auditor_agent_definitions(["interface"])
        assert "audit-comprehensive" in agents
        assert "Write" in agents["audit-comprehensive"]["tools"]

    def test_audit_test_keeps_bash_alongside_write(self) -> None:
        """``audit-test`` is the only specialized auditor that needs
        Bash (it runs the test runner). Phase 5.2 adds Write WITHOUT
        removing Bash."""
        agents = build_auditor_agent_definitions(["test"])
        assert "audit-test" in agents
        tools = agents["audit-test"]["tools"]
        assert "Write" in tools
        assert "Bash" in tools
        assert "Read" in tools

    def test_audit_scorer_unchanged(self) -> None:
        """``audit-scorer`` already had ``Write`` + ``Edit`` (cli.py:478
        baseline). Phase 5.2 must not regress its tool list."""
        agents = build_auditor_agent_definitions(["interface"])
        scorer_tools = agents["audit-scorer"]["tools"]
        assert "Write" in scorer_tools
        assert "Edit" in scorer_tools


# ---------------------------------------------------------------------------
# AC10-AC12 — audit_output_path_guard hook semantics
# ---------------------------------------------------------------------------


class TestAC10HookAllowsAuditOutputs:
    """The hook allows ``Write`` / ``Edit`` to the audit-output
    envelope when ``AGENT_TEAM_AUDIT_WRITER=1`` is set:
    ``{audit_output_root}/audit-*_findings.json``,
    ``{audit_output_root}/AUDIT_REPORT.json``, and the exact
    ``requirements_path``."""

    def _audit_env(
        self,
        *,
        audit_output_root: Path,
        requirements_path: Path | None = None,
    ) -> dict[str, str]:
        env = {
            "AGENT_TEAM_AUDIT_WRITER": "1",
            "AGENT_TEAM_AUDIT_OUTPUT_ROOT": str(audit_output_root.resolve()),
        }
        if requirements_path is not None:
            env["AGENT_TEAM_AUDIT_REQUIREMENTS_PATH"] = str(
                requirements_path.resolve()
            )
        return env

    def test_allows_write_to_audit_findings_json(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        target = audit_dir / "audit-requirements_findings.json"
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "{}"},
            "cwd": str(tmp_path),
        }
        rc, stdout, stderr = _run_audit_output_hook(
            payload,
            env=self._audit_env(audit_output_root=audit_dir),
        )
        assert rc == 0, f"hook exited {rc}; stderr={stderr}"
        assert _hook_decision(stdout) == "allow"

    def test_allows_write_to_audit_report_json(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        target = audit_dir / "AUDIT_REPORT.json"
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "{}"},
            "cwd": str(tmp_path),
        }
        rc, stdout, stderr = _run_audit_output_hook(
            payload,
            env=self._audit_env(audit_output_root=audit_dir),
        )
        assert rc == 0
        assert _hook_decision(stdout) == "allow"

    def test_allows_edit_to_requirements_path(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        req_path = (
            tmp_path
            / ".agent-team"
            / "milestones"
            / "milestone-1"
            / "REQUIREMENTS.md"
        )
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text("baseline\n", encoding="utf-8")

        payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(req_path),
                "old_string": "baseline",
                "new_string": "verified",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, stderr = _run_audit_output_hook(
            payload,
            env=self._audit_env(
                audit_output_root=audit_dir,
                requirements_path=req_path,
            ),
        )
        assert rc == 0
        assert _hook_decision(stdout) == "allow"

    def test_allows_read_tools_unconditionally(self, tmp_path: Path) -> None:
        """Read / Glob / Grep / Bash are allowed even with audit env
        active — the path guard scope is write/edit only."""
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": str(tmp_path / "anywhere.txt")},
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env=self._audit_env(audit_output_root=audit_dir),
        )
        assert rc == 0
        assert _hook_decision(stdout) == "allow"


class TestAC11HookDeniesSourceFiles:
    """When ``AGENT_TEAM_AUDIT_WRITER=1`` is active, ``Write`` / ``Edit``
    to project source files (``apps/api/src/main.ts``, etc.) MUST be
    denied even though the audit-* agents now carry ``Write`` in their
    tools list. The path guard is the structural complement that
    bounds the scope of that ``Write``."""

    def _audit_env(self, audit_output_root: Path, requirements_path: Path) -> dict[str, str]:
        return {
            "AGENT_TEAM_AUDIT_WRITER": "1",
            "AGENT_TEAM_AUDIT_OUTPUT_ROOT": str(audit_output_root.resolve()),
            "AGENT_TEAM_AUDIT_REQUIREMENTS_PATH": str(
                requirements_path.resolve()
            ),
        }

    def test_denies_write_to_apps_api_src(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        req_path = audit_dir.parent / "REQUIREMENTS.md"
        req_path.write_text("# req", encoding="utf-8")

        source_target = tmp_path / "apps" / "api" / "src" / "main.ts"
        source_target.parent.mkdir(parents=True)
        source_target.write_text("// existing", encoding="utf-8")

        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(source_target),
                "content": "// hijacked",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, stderr = _run_audit_output_hook(
            payload,
            env=self._audit_env(
                audit_output_root=audit_dir,
                requirements_path=req_path,
            ),
        )
        assert rc == 0, f"hook exited {rc}; stderr={stderr}"
        assert _hook_decision(stdout) == "deny"

    def test_denies_write_to_sibling_prefix_path(self, tmp_path: Path) -> None:
        """Sibling-prefix shapes (``audit-team-other/``) cannot bypass
        via raw string-prefix tricks — the resolved-path containment
        check is exact-segment-aware."""
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        req_path = audit_dir.parent / "REQUIREMENTS.md"
        req_path.write_text("# req", encoding="utf-8")

        # Sibling directory whose path starts with the same string as
        # audit_dir but is a different parent.
        sibling = audit_dir.parent.parent / ".agent-team-other"
        sibling.mkdir(parents=True, exist_ok=True)
        sibling_target = sibling / "AUDIT_REPORT.json"

        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(sibling_target),
                "content": "{}",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env=self._audit_env(
                audit_output_root=audit_dir,
                requirements_path=req_path,
            ),
        )
        assert rc == 0
        assert _hook_decision(stdout) == "deny"

    def test_denies_write_when_audit_output_root_unset(
        self, tmp_path: Path
    ) -> None:
        """If ``AGENT_TEAM_AUDIT_WRITER=1`` is set but the output
        root env is missing, the dispatch is malformed — fail
        CLOSED."""
        target = tmp_path / "AUDIT_REPORT.json"
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "{}"},
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env={"AGENT_TEAM_AUDIT_WRITER": "1"},
        )
        assert rc == 0
        assert _hook_decision(stdout) == "deny"

    def test_denies_traversal_attempt(self, tmp_path: Path) -> None:
        """Path traversal via ``..`` segments cannot escape the audit
        output root — the resolve() step canonicalizes."""
        audit_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1" / ".agent-team"
        audit_dir.mkdir(parents=True)
        req_path = audit_dir.parent / "REQUIREMENTS.md"
        req_path.write_text("# req", encoding="utf-8")

        # Traversal target — climbs out of audit_dir via ``..``.
        traversal_target = audit_dir / ".." / ".." / ".." / "main.ts"

        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(traversal_target),
                "content": "// hijacked",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env=self._audit_env(
                audit_output_root=audit_dir,
                requirements_path=req_path,
            ),
        )
        assert rc == 0
        assert _hook_decision(stdout) == "deny"


class TestAC12HookNoOpOutsideAuditEnv:
    """Outside the audit dispatch (``AGENT_TEAM_AUDIT_WRITER`` unset
    or anything other than ``"1"``), the hook is a deterministic
    no-op — every tool call passes through unconditionally. This
    guarantees Wave A/B/C/D, audit-fix, and other Claude dispatches in
    the same run-dir are unaffected by the new audit-output guard."""

    def test_no_op_when_env_unset(self, tmp_path: Path) -> None:
        """No env vars set → allow every call (including writes to
        arbitrary paths)."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "apps" / "api" / "src" / "main.ts"),
                "content": "// any content",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env={
                "AGENT_TEAM_AUDIT_WRITER": None,  # type: ignore[dict-item]
                "AGENT_TEAM_AUDIT_OUTPUT_ROOT": None,  # type: ignore[dict-item]
                "AGENT_TEAM_AUDIT_REQUIREMENTS_PATH": None,  # type: ignore[dict-item]
            },
        )
        assert rc == 0
        assert _hook_decision(stdout) == "allow"

    def test_no_op_when_writer_env_is_other_value(
        self, tmp_path: Path
    ) -> None:
        """``AGENT_TEAM_AUDIT_WRITER`` set to anything other than
        ``"1"`` → still no-op. Avoids accidental activation by stray
        env values."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "apps" / "api" / "src" / "main.ts"),
                "content": "// any content",
            },
            "cwd": str(tmp_path),
        }
        rc, stdout, _ = _run_audit_output_hook(
            payload,
            env={
                "AGENT_TEAM_AUDIT_WRITER": "0",
                "AGENT_TEAM_AUDIT_OUTPUT_ROOT": str(tmp_path),
            },
        )
        assert rc == 0
        assert _hook_decision(stdout) == "allow"


# ---------------------------------------------------------------------------
# Hook registration — third managed marker added to settings.json without
# disturbing existing non-managed entries
# ---------------------------------------------------------------------------


class TestHookRegistrationPreservesNonManaged:
    """``_ensure_wave_d_path_guard_settings`` must add the third
    managed marker (``agent_team_v15_audit_output_path_guard``) and
    preserve any non-managed PreToolUse entries already in the file."""

    def test_third_marker_present_after_writer_runs(self, tmp_path: Path) -> None:
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.is_file()
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        markers = []
        for entry in settings["PreToolUse"]:
            for key in entry:
                if key.startswith("agent_team_v15_") and key.endswith("_path_guard"):
                    markers.append(key)
        assert "agent_team_v15_wave_d_path_guard" in markers
        assert "agent_team_v15_audit_fix_path_guard" in markers
        assert "agent_team_v15_audit_output_path_guard" in markers

    def test_existing_non_managed_entries_preserved(
        self, tmp_path: Path
    ) -> None:
        # Pre-populate settings.json with a non-managed PreToolUse entry.
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        settings_path = claude_dir / "settings.json"
        non_managed_entry = {
            "matcher": "Bash",
            "hooks": [
                {"type": "command", "command": "echo external", "timeout": 3}
            ],
            "external_marker": True,
        }
        settings_path.write_text(
            json.dumps({"PreToolUse": [non_managed_entry]}),
            encoding="utf-8",
        )

        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))

        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        # The non-managed entry must survive verbatim.
        non_managed_after = [
            entry
            for entry in settings["PreToolUse"]
            if entry.get("external_marker") is True
        ]
        assert len(non_managed_after) == 1
        assert non_managed_after[0] == non_managed_entry

    def test_writer_is_idempotent(self, tmp_path: Path) -> None:
        """Multiple invocations leave exactly three managed entries."""
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))

        settings = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        managed_count = 0
        for entry in settings["PreToolUse"]:
            if any(
                key.startswith("agent_team_v15_") and key.endswith("_path_guard")
                for key in entry
            ):
                managed_count += 1
        assert managed_count == 3
