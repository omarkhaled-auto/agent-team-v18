"""Phase 3 audit-fix-loop guardrail fixtures.

Goal: per-debug-agent PreToolUse path-allowlist hook so the audit-fix
fix fleet physically cannot write outside the current finding's
declared scope (primary_file + sibling test files).

Covers Acceptance Criteria from
``docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md`` §F:

- AC1: Each debug agent runs with hook-enforced write allowlist limited
  to its finding's ``primary_file`` + sibling test files; out-of-allowlist
  Edit/Write returns canonical ``permissionDecision: deny`` envelope.
- AC2: Wave D path-guard remains intact and untouched on this Phase
  (the helper extraction must be behaviour-preserving — covered by
  ``tests/test_wave_d_path_guard.py``).
- AC3: Multi-matcher conflict test verifies Wave D + audit-fix entries
  both fire correctly (covered by
  ``tests/test_hook_multimatcher_conflict.py``).
- AC4: Env var propagation smoke runs in CI; ``AGENT_TEAM_FINDING_ID``
  and ``AGENT_TEAM_ALLOWED_PATHS`` reach the hook subprocess (Risk #7
  pin).
- AC5: Audit-fix-path-guard fails CLOSED on parse error (deny default).

Inter-phase dependency check: imports the public API Phase 3 lands. If
the imports fail at collection time the whole file errors as
``ImportError`` — the expected initial-red state per §0.4 TDD step 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Phase 3 public API (these imports must resolve once the
# implementation lands).
from agent_team_v15.wave_d_path_guard import (  # noqa: E402
    _decide_from_allowlist,
    _normalize_relative,
)
from agent_team_v15.audit_fix_path_guard import (  # noqa: E402
    main as audit_fix_main,
)
from agent_team_v15.audit_models import derive_sibling_test_files  # noqa: E402
from agent_team_v15.agent_teams_backend import AgentTeamsBackend  # noqa: E402


_HOOK_MODULE = "agent_team_v15.audit_fix_path_guard"


def _run_hook(
    payload: dict,
    *,
    finding_id: str | None = "F-001",
    allowed_paths: str | None = "apps/web/src/app/login/page.tsx",
    cwd: str | None = None,
    project_dir: str | None = None,
    raw_input: str | None = None,
) -> tuple[int, dict]:
    """Invoke the audit-fix path guard as a subprocess.

    Returns ``(returncode, parsed_envelope_or_empty_dict)``. We invoke
    the script the same way Claude Code does: a single-shot subprocess
    receiving JSON on stdin and emitting JSON on stdout.
    """
    env = {**os.environ}
    if finding_id is not None:
        env["AGENT_TEAM_FINDING_ID"] = finding_id
    else:
        env.pop("AGENT_TEAM_FINDING_ID", None)
    if allowed_paths is not None:
        env["AGENT_TEAM_ALLOWED_PATHS"] = allowed_paths
    else:
        env.pop("AGENT_TEAM_ALLOWED_PATHS", None)
    if project_dir is not None:
        env["AGENT_TEAM_PROJECT_DIR"] = project_dir
    if cwd and "cwd" not in (payload or {}):
        payload = {**(payload or {}), "cwd": cwd}
    proc = subprocess.run(
        [sys.executable, "-m", _HOOK_MODULE],
        input=raw_input if raw_input is not None else json.dumps(payload or {}),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    out = (proc.stdout or "").strip()
    parsed: dict = {}
    if out:
        parsed = json.loads(out)
    return proc.returncode, parsed


# ---------------------------------------------------------------------------
# AC1 — out-of-allowlist Edit/Write returns canonical deny envelope.
# ---------------------------------------------------------------------------

def test_audit_fix_denies_write_outside_allowlist(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "api" / "src" / "main.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x = 1"},
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-001",
        allowed_paths="apps/web/src/app/login/page.tsx:e2e/tests/login.spec.ts",
        cwd=str(tmp_path),
    )
    assert rc == 0
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("hookEventName") == "PreToolUse"
    assert deny.get("permissionDecision") == "deny"
    reason = deny.get("permissionDecisionReason") or ""
    assert "F-001" in reason, f"deny reason should mention finding id, got {reason!r}"
    assert "apps/api/src/main.py" in reason


def test_audit_fix_allows_write_inside_allowlist(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "web" / "src" / "app" / "login" / "page.tsx"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "a",
            "new_string": "b",
        },
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-001",
        allowed_paths="apps/web/src/app/login/page.tsx:e2e/tests/login.spec.ts",
        cwd=str(tmp_path),
    )
    assert rc == 0
    # Empty envelope == allow.
    assert result == {}


def test_audit_fix_allows_sibling_test_write(tmp_path: Path) -> None:
    """Sibling test files in the allowlist must be writeable so the fix
    fleet can add/update tests for the finding it's repairing.
    """
    target = tmp_path / "e2e" / "tests" / "login.spec.ts"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "test('x', () => {});"},
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-001",
        allowed_paths="apps/web/src/app/login/page.tsx:e2e/tests/login.spec.ts",
        cwd=str(tmp_path),
    )
    assert rc == 0
    assert result == {}


# ---------------------------------------------------------------------------
# AC1 / dispatch gating — when AGENT_TEAM_FINDING_ID is unset, the hook
# is a no-op (allow) so non-audit-fix dispatches (Wave A/D, repairs)
# are completely unaffected. Mirrors the wave-letter gating pattern in
# wave_d_path_guard.
# ---------------------------------------------------------------------------

def test_audit_fix_allows_when_finding_id_unset(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "anywhere.py"), "content": "x"},
    }
    rc, result = _run_hook(
        payload,
        finding_id=None,
        allowed_paths=None,
        cwd=str(tmp_path),
    )
    assert rc == 0
    assert result == {}


def test_audit_fix_allows_read_class_tools(tmp_path: Path) -> None:
    """Read tools must always pass — finding scope only applies to
    write-class operations.
    """
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "some" / "read.py")},
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-001",
        allowed_paths="apps/web/page.tsx",
        cwd=str(tmp_path),
    )
    assert rc == 0
    assert result == {}


# ---------------------------------------------------------------------------
# AC4 — env var propagation smoke. The hook must observe both env vars
# we set in the parent process; Wave D path-guard already proves the
# pattern works empirically (Risk #7 NOT FOUND in Claude Code docs).
# This test fails LOUD if a future Claude Code release stops
# propagating arbitrary parent env to hook subprocess.
# ---------------------------------------------------------------------------

def test_audit_fix_env_var_propagation_smoke(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "web" / "page.tsx"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-PROPAGATION-CHECK",
        allowed_paths="apps/web/page.tsx",
        cwd=str(tmp_path),
    )
    # The hook decided based on the env var values — proves the env
    # vars reached the subprocess. If they didn't, AGENT_TEAM_FINDING_ID
    # would be missing and the hook would treat dispatch as non-audit-fix
    # (allow), giving us false success on out-of-allowlist writes. So we
    # also verify by attempting a denied write.
    assert rc == 0
    assert result == {}

    deny_payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "apps" / "api" / "out.py"),
            "content": "x",
        },
    }
    rc2, deny_result = _run_hook(
        deny_payload,
        finding_id="F-PROPAGATION-CHECK",
        allowed_paths="apps/web/page.tsx",
        cwd=str(tmp_path),
    )
    assert rc2 == 0
    deny_envelope = deny_result.get("hookSpecificOutput") or {}
    assert deny_envelope.get("permissionDecision") == "deny"
    reason = deny_envelope.get("permissionDecisionReason") or ""
    assert "F-PROPAGATION-CHECK" in reason, (
        "AGENT_TEAM_FINDING_ID did not propagate to the hook subprocess. "
        "If this fails, Claude Code may have changed the env var "
        "contract — Risk #7 has materialised."
    )


# ---------------------------------------------------------------------------
# AC5 — audit-fix path guard fails CLOSED on parse error. Asymmetric
# vs Wave D (which fails OPEN). Audit-fix dispatch is the higher-risk
# surface (M25-disaster scenario), so a malformed payload must DENY
# rather than allow.
# ---------------------------------------------------------------------------

def test_audit_fix_fails_closed_on_invalid_json(tmp_path: Path) -> None:
    rc, result = _run_hook(
        payload={},
        finding_id="F-001",
        allowed_paths="apps/web/page.tsx",
        cwd=str(tmp_path),
        raw_input="not json at all",
    )
    assert rc == 0
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("permissionDecision") == "deny", (
        "audit_fix_path_guard must fail CLOSED on parse error per AC5 — "
        "the M25-disaster scenario is exactly when papering over a "
        "malformed dispatch lets a destructive write through."
    )
    reason = deny.get("permissionDecisionReason") or ""
    assert "audit-fix" in reason.lower() or "malformed" in reason.lower()


def test_audit_fix_fails_closed_on_empty_allowed_paths(tmp_path: Path) -> None:
    """If AGENT_TEAM_FINDING_ID is set but AGENT_TEAM_ALLOWED_PATHS is
    empty/missing, the dispatch is malformed — deny rather than allow
    the agent unbounded write access.
    """
    target = tmp_path / "anywhere" / "file.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
    }
    rc, result = _run_hook(
        payload,
        finding_id="F-001",
        allowed_paths="",
        cwd=str(tmp_path),
    )
    assert rc == 0
    deny = result.get("hookSpecificOutput") or {}
    assert deny.get("permissionDecision") == "deny"


# ---------------------------------------------------------------------------
# Helper extraction (Phase 3 §F.1) — ensure the parametric helper works
# for both Wave D and audit-fix call sites. Behaviour-preserving for
# Wave D (the existing path guard tests cover the wave-D shape).
# ---------------------------------------------------------------------------

def test_decide_from_allowlist_accepts_prefix_or_exact() -> None:
    allow_prefixes = ("apps/web/",)
    allow_files: frozenset[str] = frozenset({"package.json"})

    decide = _decide_from_allowlist
    assert decide("apps/web/x.tsx", allow_prefixes, allow_files) is True
    assert decide("package.json", allow_prefixes, allow_files) is True
    assert decide("apps/api/y.py", allow_prefixes, allow_files) is False
    assert decide("", allow_prefixes, allow_files) is False
    assert decide("apps/web/../etc/passwd", allow_prefixes, allow_files) is False


def test_decide_from_allowlist_rejects_absolute_paths() -> None:
    allow_prefixes = ("apps/web/",)
    decide = _decide_from_allowlist
    # Absolute paths that fall through normalisation must not match a
    # relative prefix; the caller should treat them as out-of-scope.
    assert decide("/etc/passwd", allow_prefixes, frozenset()) is False
    assert decide("/apps/web/x.tsx", allow_prefixes, frozenset()) is False


def test_normalize_relative_strips_cwd() -> None:
    rel = _normalize_relative("/work/run/apps/web/page.tsx", "/work/run")
    assert rel == "apps/web/page.tsx"
    rel2 = _normalize_relative("apps/web/page.tsx", "/work/run")
    assert rel2 == "apps/web/page.tsx"


# ---------------------------------------------------------------------------
# derive_sibling_test_files free function — same heuristic as
# AuditFinding.sibling_test_files (Phase 2) but callable on any path
# string. Phase 3 needs this in the dispatch pipeline where we have
# only a Feature.target_files list, not AuditFinding instances.
# ---------------------------------------------------------------------------

def test_derive_sibling_test_files_basic() -> None:
    siblings = derive_sibling_test_files("apps/web/login.tsx")
    assert "e2e/tests/login.spec.ts" in siblings
    assert "tests/test_login.py" in siblings


def test_derive_sibling_test_files_nextjs_route() -> None:
    """Next.js App Router: page.tsx in a route dir uses the route name
    (apps/web/login/page.tsx → login), not the basename "page".
    """
    siblings = derive_sibling_test_files("apps/web/login/page.tsx")
    assert any(s.endswith("login.spec.ts") for s in siblings)
    assert all("page.spec.ts" not in s for s in siblings)


def test_derive_sibling_test_files_empty_input() -> None:
    assert derive_sibling_test_files("") == []
    assert derive_sibling_test_files("   ") == []


# ---------------------------------------------------------------------------
# Settings.json writer — extends agent_teams_backend to include the
# audit-fix path-guard entry alongside Wave D's. Idempotent + preserves
# unrelated entries (matches the Wave D shape).
# ---------------------------------------------------------------------------

def test_ensure_path_guard_settings_writes_both_entries(tmp_path: Path) -> None:
    AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    pre = settings.get("PreToolUse") or []
    wave_d = [e for e in pre if isinstance(e, dict) and e.get("agent_team_v15_wave_d_path_guard")]
    audit_fix = [
        e for e in pre if isinstance(e, dict) and e.get("agent_team_v15_audit_fix_path_guard")
    ]
    assert len(wave_d) == 1, "Wave D entry must remain present"
    assert len(audit_fix) == 1, "Audit-fix entry must be added by the same writer"


def test_ensure_path_guard_settings_uses_seconds_timeout(tmp_path: Path) -> None:
    """Risk #8 + Context7 finding: timeout values are in SECONDS (default
    60s for command hooks, 30s for prompt hooks). The plan's literal
    `timeout: 5000` was a typo for `timeout: 5` (5 seconds). A 5000-second
    timeout would be ~83 minutes — useless as a circuit breaker.
    """
    AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    audit_fix = [
        e
        for e in settings["PreToolUse"]
        if isinstance(e, dict) and e.get("agent_team_v15_audit_fix_path_guard")
    ][0]
    timeout = audit_fix["hooks"][0]["timeout"]
    assert timeout == 5, (
        "audit-fix-path-guard timeout must be 5 seconds (Risk #8 + plan §F.4 "
        f"corrected from typo `timeout: 5000`), got {timeout!r}"
    )


def test_ensure_path_guard_settings_idempotent(tmp_path: Path) -> None:
    AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
    AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    audit_fix_count = sum(
        1
        for e in settings["PreToolUse"]
        if isinstance(e, dict) and e.get("agent_team_v15_audit_fix_path_guard")
    )
    assert audit_fix_count == 1


# ---------------------------------------------------------------------------
# CLI wiring — _run_audit_fix_unified writes settings.json before
# dispatch so the audit-fix path-guard hook is registered for any
# in-process SDK dispatch via _run_patch_fixes. Without this write the
# hook never fires (the SDK delegates to the Claude CLI subprocess
# which reads .claude/settings.json from cwd; if the file isn't there,
# the hook isn't registered).
# ---------------------------------------------------------------------------

def test_run_audit_fix_unified_writes_settings_for_dispatch_scope(
    tmp_path: Path,
) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch as mock_patch

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    finding = SimpleNamespace(
        finding_id="F-WIRING-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="wiring smoke",
        evidence=["apps/web/login.tsx:1 -- synthetic"],
        remediation="fix login",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/login.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(audit_team=SimpleNamespace(enabled=True))

    async def _no_op_dispatch(*args, **kwargs):
        return 0.0

    with mock_patch.object(
        fix_mod, "execute_unified_fix_async", side_effect=_no_op_dispatch
    ):
        asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=str(tmp_path),
                task_text="",
                depth="standard",
            )
        )

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.is_file(), (
        "Expected .claude/settings.json to be written at audit-fix entry "
        "so the audit-fix path-guard hook fires for ClaudeSDKClient "
        "dispatches"
    )
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    pre = settings.get("PreToolUse") or []
    audit_fix = [
        e
        for e in pre
        if isinstance(e, dict) and e.get("agent_team_v15_audit_fix_path_guard")
    ]
    assert len(audit_fix) == 1, (
        "_run_audit_fix_unified must register the audit-fix path-guard "
        "hook before dispatch (Phase 3 §F.4)"
    )


def test_run_audit_fix_unified_skips_settings_write_when_no_findings(
    tmp_path: Path,
) -> None:
    """If filter_denylisted_findings drops every finding, no settings
    write is required (no dispatch happens). Avoids leaving stale
    .claude/settings.json on the filesystem from short-circuited
    audit-fix calls.
    """
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch as mock_patch

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    finding = SimpleNamespace(
        finding_id="F-DENYLISTED",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="denylisted",
        evidence=["packages/api-client/sdk.gen.ts:1 -- synthetic"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="packages/api-client/sdk.gen.ts",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(audit_team=SimpleNamespace(enabled=True))

    async def _no_op_dispatch(*args, **kwargs):
        return 0.0

    with mock_patch.object(
        fix_mod, "execute_unified_fix_async", side_effect=_no_op_dispatch
    ):
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=str(tmp_path),
                task_text="",
                depth="standard",
            )
        )

    assert modified == [] and cost == 0.0
    # The denylisted finding triggers an early return BEFORE the
    # settings write — the .claude dir should not be touched.
    assert not (tmp_path / ".claude" / "settings.json").is_file()
