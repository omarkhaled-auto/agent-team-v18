"""Phase 5 rule-based Codex observer checks - unit tests."""
from __future__ import annotations

import pytest

from agent_team_v15.codex_observer_checks import (
    check_codex_diff,
    check_codex_plan,
)


def _make_diff(paths: list[str]) -> str:
    parts: list[str] = []
    for p in paths:
        parts.append(f"diff --git a/{p} b/{p}")
        parts.append(f"--- a/{p}")
        parts.append(f"+++ b/{p}")
        parts.append("@@ -0,0 +1,2 @@")
        parts.append("+placeholder line 1")
        parts.append("+placeholder line 2")
    return "\n".join(parts) + "\n"


def test_check_codex_diff_wave_b_detects_frontend():
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ])
    msg = check_codex_diff(diff, "B")
    assert msg != ""
    assert "Wave B" in msg
    assert "backend" in msg.lower()


def test_check_codex_diff_wave_b_clean():
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/src/routes/users.py",
        "apps/api/src/db/models.py",
    ])
    msg = check_codex_diff(diff, "B")
    assert msg == ""


def test_check_codex_diff_wave_d_detects_backend():
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/prisma/schema.prisma",
        "apps/api/src/routes/users.py",
    ])
    msg = check_codex_diff(diff, "D")
    assert msg != ""
    assert "Wave D" in msg
    assert "frontend" in msg.lower()


def test_check_codex_diff_empty_diff_no_steer():
    assert check_codex_diff("", "B") == ""
    assert check_codex_diff("   \n", "B") == ""


def test_check_codex_diff_small_diff_below_floor_no_steer():
    # Two offending files - below the 3-file small-diff floor, MUST NOT trigger.
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
    ])
    assert check_codex_diff(diff, "B") == ""


def test_check_codex_diff_single_incidental_touch_no_steer():
    # Three changed files total but only one is frontend - below drift threshold.
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/src/db/models.py",
        "apps/web/README.md",
    ])
    assert check_codex_diff(diff, "B") == ""


def test_check_codex_diff_non_target_wave_no_steer():
    # Wave A has no forbidden pattern map - always returns "".
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ])
    assert check_codex_diff(diff, "A") == ""


def test_check_codex_plan_wave_b_frontend_plan():
    plan = [
        "Create apps/web/pages/index.tsx",
        "Add React component in apps/web/components/Header.tsx",
        "Wire up apps/api/src/main.py",
    ]
    msg = check_codex_plan(plan, "B")
    assert msg != ""
    assert "Wave B" in msg


def test_check_codex_plan_wave_b_clean_plan():
    plan = [
        "Create apps/api/src/main.py",
        "Add apps/api/prisma/schema.prisma",
        "Write apps/api/src/routes/users.py",
    ]
    assert check_codex_plan(plan, "B") == ""


def test_check_codex_plan_single_hit_below_threshold_no_steer():
    plan = [
        "Create apps/api/src/main.py",
        "Incidentally read apps/web/README.md for reference",
    ]
    assert check_codex_plan(plan, "B") == ""


def test_check_codex_plan_empty_input_no_steer():
    assert check_codex_plan([], "B") == ""
    assert check_codex_plan(["", "   "], "B") == ""


def test_check_codex_plan_non_target_wave_no_steer():
    plan = [
        "Create apps/web/pages/index.tsx",
        "Add apps/web/components/Header.tsx",
    ]
    assert check_codex_plan(plan, "T") == ""


def test_check_codex_diff_exception_returns_empty(monkeypatch):
    # Force an exception inside the diff scanner to prove fail-open.
    import agent_team_v15.codex_observer_checks as mod

    class _Boom:
        def finditer(self, _text):
            raise RuntimeError("injected failure")

    monkeypatch.setattr(mod, "_DIFF_GIT_HEADER", _Boom())
    monkeypatch.setattr(mod, "_DIFF_PLUSPLUS_HEADER", _Boom())
    assert check_codex_diff(_make_diff(["apps/web/a.tsx", "apps/web/b.tsx", "apps/web/c.tsx"]), "B") == ""


def test_check_codex_plan_exception_returns_empty(monkeypatch):
    import agent_team_v15.codex_observer_checks as mod

    def _boom(_path: str, _patterns):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(mod, "_matches_any", _boom)
    assert check_codex_plan(["apps/web/pages/index.tsx"] * 5, "B") == ""


def test_cross_validation_plan_and_diff_agree_on_wave_b():
    # Same offending file set - plan and diff must BOTH return non-empty for Wave B.
    paths = [
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ]
    diff = _make_diff(paths)
    plan = [f"Create {p}" for p in paths]
    diff_msg = check_codex_diff(diff, "B")
    plan_msg = check_codex_plan(plan, "B")
    assert diff_msg != ""
    assert plan_msg != ""
    assert "Wave B" in diff_msg
    assert "Wave B" in plan_msg
