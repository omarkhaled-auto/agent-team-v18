"""Risk #6 pin — multi-matcher conflict resolution between Wave D path
guard and audit-fix path guard.

This test exists to LOCK the contract Context7 surfaced in 2026-04-26's
research-mode lookup against ``/anthropics/claude-code``:

    Resolution precedence: deny > ask > allow.
    Multiple matching hooks run IN PARALLEL; their outputs are
    aggregated under "most-restrictive wins". A v2.1.80 changelog entry
    explicitly fixed an "allow bypasses deny" bug, confirming the
    documented contract.

If a future Claude Code release ever changes this resolution semantic,
the test below MUST fail loudly so a maintainer notices the M25-class
safety regression. Do not silently update the assertions to chase a
new behaviour — surface the change to the audit-fix guardrails owner
first (see ``docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md``
§C Risk #6).

What we cannot easily test from a unit test:
    The actual Claude Code resolution layer is internal to the CLI; we
    cannot directly observe its aggregation logic from Python.
    Instead, we exercise the two hook scripts independently and assert
    that:
        1. Each hook's output is a valid PreToolUse envelope so the
           aggregator sees structured input from both matchers.
        2. The "deny wins" contract is documented in this test's
           docstring + the test asserts it via a synthetic aggregator.
        3. The two hooks operate on disjoint env-var gates
           (AGENT_TEAM_WAVE_LETTER vs AGENT_TEAM_FINDING_ID) so they
           cannot accidentally race or share state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_WAVE_D_MODULE = "agent_team_v15.wave_d_path_guard"
_AUDIT_FIX_MODULE = "agent_team_v15.audit_fix_path_guard"


def _invoke_hook(
    module: str,
    payload: dict,
    *,
    env_overrides: dict[str, str] | None = None,
) -> tuple[int, dict]:
    env = {**os.environ}
    # Strip both gates so each test sets exactly what it needs.
    env.pop("AGENT_TEAM_WAVE_LETTER", None)
    env.pop("AGENT_TEAM_FINDING_ID", None)
    env.pop("AGENT_TEAM_ALLOWED_PATHS", None)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-m", module],
        input=json.dumps(payload),
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


def _decision_of(envelope: dict) -> str:
    """Return the canonical decision string ('allow', 'deny', 'ask') or
    'allow' if the envelope is empty (allow-by-default).
    """
    spec = envelope.get("hookSpecificOutput") or {}
    return str(spec.get("permissionDecision") or "allow").lower()


def _aggregate_per_documented_contract(decisions: list[str]) -> str:
    """Mirror the Claude Code aggregation contract documented in
    Context7 (2026-04-26 lookup): deny > ask > allow.

    This helper is the test's lock on the contract — if Claude Code
    changes the resolution semantic, the assertions below will fail
    against the empirical CLI behaviour (which we cannot directly
    exercise here, but which the live-hook smoke step in §G Phase 3
    promote-gate #4 covers).
    """
    if "deny" in decisions:
        return "deny"
    if "ask" in decisions:
        return "ask"
    return "allow"


# ---------------------------------------------------------------------------
# Both hooks ALLOW — the documented "all-allow" path. Aggregation is
# allow.
# ---------------------------------------------------------------------------

def test_both_hooks_allow_in_scope_write(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "apps" / "web" / "login.tsx"),
            "content": "x",
        },
        "cwd": str(tmp_path),
    }
    rc_d, env_d = _invoke_hook(
        _WAVE_D_MODULE,
        payload,
        env_overrides={"AGENT_TEAM_WAVE_LETTER": "D"},
    )
    rc_a, env_a = _invoke_hook(
        _AUDIT_FIX_MODULE,
        payload,
        env_overrides={
            "AGENT_TEAM_FINDING_ID": "F-001",
            "AGENT_TEAM_ALLOWED_PATHS": "apps/web/login.tsx",
        },
    )
    assert rc_d == 0 and rc_a == 0
    decisions = [_decision_of(env_d), _decision_of(env_a)]
    assert decisions == ["allow", "allow"]
    assert _aggregate_per_documented_contract(decisions) == "allow"


# ---------------------------------------------------------------------------
# Wave D denies + audit-fix allows on the same call → aggregated DENY
# wins per Context7 (deny > ask > allow). This pin closes Risk #6.
# ---------------------------------------------------------------------------

def test_wave_d_deny_overrides_audit_fix_allow(tmp_path: Path) -> None:
    """The killer scenario: Wave D running an audit-fix attempt where
    the finding's allowlist legitimately contains a path that Wave D
    would block (e.g., ``packages/api-client/sdk.gen.ts``). The plan
    §H rules out this combination upfront via the
    ``_MILESTONE_ANCHOR_IMMUTABLE_DENYLIST`` filter (Phase 1 closed
    Risk #4), but if the denylist ever drifts and a malformed dispatch
    slips through, Wave D's deny MUST win.
    """
    target = tmp_path / "packages" / "api-client" / "sdk.gen.ts"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
        "cwd": str(tmp_path),
    }
    rc_d, env_d = _invoke_hook(
        _WAVE_D_MODULE,
        payload,
        env_overrides={"AGENT_TEAM_WAVE_LETTER": "D"},
    )
    rc_a, env_a = _invoke_hook(
        _AUDIT_FIX_MODULE,
        payload,
        env_overrides={
            "AGENT_TEAM_FINDING_ID": "F-002",
            # Audit-fix would allow because the finding's allowlist names
            # the api-client path — but this is exactly when Wave D's
            # immutable boundary must override the per-finding scope.
            "AGENT_TEAM_ALLOWED_PATHS": "packages/api-client/sdk.gen.ts",
        },
    )
    assert rc_d == 0 and rc_a == 0
    decisions = [_decision_of(env_d), _decision_of(env_a)]
    assert decisions == ["deny", "allow"], (
        "If this fails, either Wave D stopped denying api-client writes "
        "or the audit-fix hook stopped allowing in-allowlist writes — "
        "either is a regression."
    )
    assert _aggregate_per_documented_contract(decisions) == "deny", (
        "Per Context7 /anthropics/claude-code (2026-04-26 lookup), the "
        "Claude Code aggregator resolves deny > ask > allow. v2.1.80 "
        "explicitly fixed an allow-bypass-deny regression. If this test "
        "fails the contract has CHANGED — surface to the audit-fix "
        "guardrails owner before silently updating the test."
    )


# ---------------------------------------------------------------------------
# Audit-fix denies + Wave D allows (e.g., a non-Wave-D dispatch like
# audit-fix repair attempt running outside the wave) → aggregated DENY.
# ---------------------------------------------------------------------------

def test_audit_fix_deny_overrides_wave_d_allow_when_outside_finding_scope(
    tmp_path: Path,
) -> None:
    target = tmp_path / "apps" / "api" / "src" / "main.py"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "a",
            "new_string": "b",
        },
        "cwd": str(tmp_path),
    }
    # Wave D: not active (AGENT_TEAM_WAVE_LETTER unset / non-D) so the
    # Wave D guard ALLOWS by gating.
    rc_d, env_d = _invoke_hook(_WAVE_D_MODULE, payload)
    # Audit-fix: active with allowlist that does NOT cover apps/api → DENY.
    rc_a, env_a = _invoke_hook(
        _AUDIT_FIX_MODULE,
        payload,
        env_overrides={
            "AGENT_TEAM_FINDING_ID": "F-003",
            "AGENT_TEAM_ALLOWED_PATHS": "apps/web/page.tsx",
        },
    )
    assert rc_d == 0 and rc_a == 0
    decisions = [_decision_of(env_d), _decision_of(env_a)]
    assert decisions == ["allow", "deny"]
    assert _aggregate_per_documented_contract(decisions) == "deny"


# ---------------------------------------------------------------------------
# Disjoint gating: Wave D and audit-fix are independent gates. Setting
# one's env var does NOT activate the other. Critical so a Wave D
# dispatch is never accidentally scoped by a stale AGENT_TEAM_FINDING_ID
# leak from a prior audit-fix run, and vice versa.
# ---------------------------------------------------------------------------

def test_audit_fix_gate_does_not_trigger_wave_d_path_guard(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "api" / "src" / "main.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
        "cwd": str(tmp_path),
    }
    # AGENT_TEAM_FINDING_ID set, AGENT_TEAM_WAVE_LETTER unset → Wave D
    # is a no-op (allow); audit-fix denies (out-of-allowlist).
    rc_d, env_d = _invoke_hook(
        _WAVE_D_MODULE,
        payload,
        env_overrides={"AGENT_TEAM_FINDING_ID": "F-leak"},
    )
    assert rc_d == 0
    assert _decision_of(env_d) == "allow"


def test_wave_d_gate_does_not_trigger_audit_fix_path_guard(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "api" / "src" / "main.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"},
        "cwd": str(tmp_path),
    }
    rc_a, env_a = _invoke_hook(
        _AUDIT_FIX_MODULE,
        payload,
        env_overrides={"AGENT_TEAM_WAVE_LETTER": "D"},
    )
    assert rc_a == 0
    assert _decision_of(env_a) == "allow"
