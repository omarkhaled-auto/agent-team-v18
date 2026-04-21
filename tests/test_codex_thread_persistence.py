"""Tests for Codex thread persistence + observer config wiring (Phase 0, Task 0.3)."""

from __future__ import annotations

import inspect

import pytest

from agent_team_v15.codex_appserver import _execute_once, execute_codex
from agent_team_v15.codex_transport import CodexResult


def test_codex_result_has_thread_id_field() -> None:
    result = CodexResult(success=True, exit_code=0, duration_seconds=0.0)
    assert hasattr(result, "thread_id")
    assert result.thread_id == ""


def test_codex_result_accepts_thread_id_kwarg() -> None:
    result = CodexResult(thread_id="thr_abc")
    assert result.thread_id == "thr_abc"


def test_execute_codex_accepts_existing_thread_id_param() -> None:
    sig = inspect.signature(execute_codex)
    assert "existing_thread_id" in sig.parameters
    param = sig.parameters["existing_thread_id"]
    assert param.default == ""
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


def test_execute_once_accepts_observer_params() -> None:
    sig = inspect.signature(_execute_once)
    for name in ("existing_thread_id", "observer_config", "requirements_text", "wave_letter"):
        assert name in sig.parameters, f"_execute_once must accept {name}"
        assert sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["existing_thread_id"].default == ""
    assert sig.parameters["observer_config"].default is None
    assert sig.parameters["requirements_text"].default == ""
    assert sig.parameters["wave_letter"].default == ""
