"""OP1 regression coverage for strict Codex CLI version drift gating."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest


def test_codex_cli_version_drift_error_is_exported() -> None:
    from agent_team_v15 import codex_cli

    assert issubclass(codex_cli.CodexCliVersionDriftError, RuntimeError)
    assert "CodexCliVersionDriftError" in codex_cli.__all__


@pytest.mark.parametrize(
    ("version_text", "warning_fragment"),
    [
        ("codex-cli 0.124.0", "may have schema changes"),
        ("codex-cli 0.122.0", "is older than the last validated schema"),
    ],
)
def test_log_codex_cli_version_warns_without_raising_when_strict_false(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    version_text: str,
    warning_fragment: str,
) -> None:
    from agent_team_v15 import codex_cli

    monkeypatch.setattr(codex_cli, "detect_codex_cli_version", lambda _bin=None: version_text)

    with caplog.at_level("WARNING"):
        detected = codex_cli.log_codex_cli_version(
            __import__("logging").getLogger("test.codex-cli"),
            strict=False,
        )

    assert detected == version_text
    assert warning_fragment in caplog.text


def test_log_codex_cli_version_raises_typed_exception_when_strict_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import codex_cli

    monkeypatch.setattr(
        codex_cli,
        "detect_codex_cli_version",
        lambda _bin=None: "codex-cli 0.124.0",
    )

    with pytest.raises(codex_cli.CodexCliVersionDriftError) as excinfo:
        codex_cli.log_codex_cli_version(
            __import__("logging").getLogger("test.codex-cli"),
            strict=True,
        )

    assert "0.124.0" in str(excinfo.value)
    assert "0.123.0" in str(excinfo.value)


def test_log_codex_cli_version_no_drift_preserves_return_and_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from agent_team_v15 import codex_cli

    monkeypatch.setattr(
        codex_cli,
        "detect_codex_cli_version",
        lambda _bin=None: "codex-cli 0.123.0",
    )

    with caplog.at_level("WARNING"):
        detected = codex_cli.log_codex_cli_version(
            __import__("logging").getLogger("test.codex-cli"),
            strict=False,
        )

    assert detected == "codex-cli 0.123.0"
    assert caplog.text == ""


def test_codex_config_strict_cli_version_default_is_false() -> None:
    from agent_team_v15.codex_transport import CodexConfig

    assert CodexConfig().strict_codex_cli_version is False


@pytest.mark.asyncio
async def test_exec_transport_passes_strict_cli_version_flag_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_transport

    observed: dict[str, object] = {}

    class StopBeforeDispatch(RuntimeError):
        pass

    def fake_log_codex_cli_version(_logger, **kwargs):
        observed.update(kwargs)
        raise StopBeforeDispatch("stop before subprocess dispatch")

    monkeypatch.setattr(codex_transport, "log_codex_cli_version", fake_log_codex_cli_version)

    config = codex_transport.CodexConfig(
        max_retries=0,
        strict_codex_cli_version=True,
    )
    with pytest.raises(StopBeforeDispatch):
        await codex_transport.execute_codex(
            "prompt",
            str(tmp_path),
            config,
            tmp_path,
        )

    assert observed["strict"] is True


@pytest.mark.asyncio
async def test_appserver_transport_passes_strict_cli_version_flag_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver

    observed: dict[str, object] = {}

    class StopBeforeDispatch(RuntimeError):
        pass

    def fake_log_codex_cli_version(_logger, **kwargs):
        observed.update(kwargs)
        raise StopBeforeDispatch("stop before app-server dispatch")

    monkeypatch.setattr(codex_appserver, "log_codex_cli_version", fake_log_codex_cli_version)

    config = codex_appserver.CodexConfig(
        max_retries=0,
        strict_codex_cli_version=True,
    )
    with pytest.raises(StopBeforeDispatch):
        await codex_appserver.execute_codex(
            "prompt",
            str(tmp_path),
            config,
            tmp_path,
        )

    assert observed["strict"] is True


def test_run_prd_milestones_accepts_backward_compatible_strict_flag_default() -> None:
    from agent_team_v15.cli import _run_prd_milestones

    signature = inspect.signature(_run_prd_milestones)

    assert signature.parameters["strict_codex_cli_version"].default is False


def _assert_codex_drift_re_raise_near_broad_catch(
    relative_path: str,
    anchor: str,
    expected_exception_name: str = "CodexCliVersionDriftError",
    search_window: int = 1800,
) -> None:
    source = (Path(__file__).resolve().parents[1] / relative_path).read_text(
        encoding="utf-8"
    )
    anchor_index = source.index(anchor)
    window = source[anchor_index : anchor_index + search_window]

    assert "except Exception as exc" in window
    assert re.search(
        rf"if\s+isinstance\(\s*exc\s*,\s*{expected_exception_name}\s*\):\s*\n\s*raise",
        window,
    ), f"{relative_path} must re-raise {expected_exception_name} near {anchor!r}"


@pytest.mark.parametrize(
    (
        "relative_path",
        "anchor",
        "expected_exception_name",
        "search_window",
    ),
    [
        (
            "src/agent_team_v15/provider_router.py",
            "failure_reason=\"codex_appserver_preflight_failed\"",
            "_CodexCliVersionDriftError",
            1800,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "codex_result = await codex_mod.execute_codex(",
            "CodexCliVersionDriftError",
            1200,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "meta, watchdog_state = await _invoke_provider_wave_with_watchdog(",
            "CodexCliVersionDriftError",
            8000,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "structural_prompt = _build_structural_fix_prompt(",
            "CodexCliVersionDriftError",
            2600,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "codex_ok, codex_cost, reason = await _dispatch_codex_compile_fix(",
            "CodexCliVersionDriftError",
            3200,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "fix_prompt = _build_dto_contract_fix_prompt(violations, milestone)",
            "CodexCliVersionDriftError",
            3600,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "fix_prompt = _build_frontend_hallucination_fix_prompt(",
            "CodexCliVersionDriftError",
            3600,
        ),
        (
            "src/agent_team_v15/wave_executor.py",
            "codex_ok, _codex_cost, reason = await _dispatch_wrapped_codex_fix(",
            "CodexCliVersionDriftError",
            3600,
        ),
        (
            "src/agent_team_v15/wave_a5_t5.py",
            "codex_result = await codex_transport_module.execute_codex(",
            "CodexCliVersionDriftError",
            1200,
        ),
        (
            "src/agent_team_v15/cli.py",
            "codex_result = await codex_mod.execute_codex(",
            "CodexCliVersionDriftError",
            1200,
        ),
        (
            "src/agent_team_v15/cli.py",
            "success, codex_cost, reason = await _dispatch_codex_fix(",
            "CodexCliVersionDriftError",
            1400,
        ),
        (
            "src/agent_team_v15/cli.py",
            "group_result = await execute_parallel_group(",
            "CodexCliVersionDriftError",
            1700,
        ),
        (
            "src/agent_team_v15/cli.py",
            "break  # Exit milestone loop",
            "CodexCliVersionDriftError",
            1700,
        ),
        (
            "src/agent_team_v15/cli.py",
            "total_cost = await execute_unified_fix_async(",
            "CodexCliVersionDriftError",
            4200,
        ),
        (
            "src/agent_team_v15/cli.py",
            "run_cost, milestone_convergence_report = asyncio.run(_run_prd_milestones(",
            "CodexCliVersionDriftError",
            12000,
        ),
    ],
)
def test_codex_cli_version_drift_is_re_raised_by_broad_dispatch_catches(
    relative_path: str,
    anchor: str,
    expected_exception_name: str,
    search_window: int,
) -> None:
    _assert_codex_drift_re_raise_near_broad_catch(
        relative_path,
        anchor,
        expected_exception_name,
        search_window,
    )
