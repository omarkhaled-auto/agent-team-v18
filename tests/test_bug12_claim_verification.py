"""Bug 12 regression coverage.

These tests guard the specific failure modes that motivated the original Bug 12
investigation. They were originally written against a pre-H3e call graph
(`_execute_single_milestone_wave`, direct `client.query` + `_process_response`
splits) which have since been refactored on master. The assertions below
exercise the equivalent master-era APIs (`execute_milestone_waves`,
`_run_sdk_session_with_watchdog`) so the regressions they cover stay locked.

Coverage:
- ``test_outer_wait_for_preempts_hung_wave`` — proves that wrapping
  ``execute_milestone_waves`` in ``asyncio.wait_for`` cancels a wave that
  internally hangs forever, even though the wave call itself has no inner
  timeout. Bug 12 class: wave executor swallowing outer cancellation.
- ``test_watchdog_does_not_fire_during_active_stream`` — proves the SDK
  session watchdog's idle timeout does NOT fire while the stream produces
  continuous activity whose total duration exceeds the idle threshold.
  Bug 12 class: watchdog confusing total-time with idle-time (the original
  1.5x timeout wrapper bug). Master's
  ``test_run_sdk_session_with_watchdog_raises_when_stream_goes_idle`` covers
  the positive case (fires on idle); this covers the negative case.

A third original claim ("warning message uses wave_execution_timeout_s")
is already covered by
``test_cli_sdk_session_watchdog.test_milestone_timeout_warning_uses_actual_wave_execution_timeout``
and is not repeated here.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_team_v15.cli as cli_module
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import (
    WaveWatchdogTimeoutError,
    execute_milestone_waves,
)


class _FakeAssistantMessage:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResultMessage:
    """Stand-in for ``claude_agent_sdk.ResultMessage``.

    ``_consume_response_stream`` checks ``isinstance(msg, ResultMessage)`` to
    settle cost accounting; giving the fake an attribute-compatible shape lets
    the normal-termination path exercise.
    """

    def __init__(self, total_cost_usd: float = 0.0) -> None:
        self.total_cost_usd = total_cost_usd
        self.usage = {}
        self.duration_ms = 0
        self.duration_api_ms = 0
        self.num_turns = 1
        self.is_error = False
        self.result = ""
        self.session_id = "fake"
        self.subtype = "success"


def _milestone(
    *,
    template: str = "full_stack",
    milestone_id: str = "milestone-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Platform Foundation",
        template=template,
        description="Verification milestone",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
        status="PENDING",
    )


@pytest.mark.asyncio
async def test_outer_wait_for_preempts_hung_wave(tmp_path: Path) -> None:
    """Outer ``asyncio.wait_for`` must cancel a wave that internally hangs.

    Regression target: Bug 12 root cause was that an outer milestone-level
    timeout wrapped around wave execution did not propagate cancellation
    down into the hung SDK call. This test makes ``execute_sdk_call`` await
    ``asyncio.Future()`` (hang forever) on wave D and asserts the outer
    ``wait_for`` fires well before any internal watchdog could mask it.
    """

    milestone = _milestone()

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(
        *, prompt: str, wave: str, role: str = "wave", **_: object
    ) -> float:
        if wave == "D":
            await asyncio.Future()
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def extract_artifacts(**kwargs: object) -> dict[str, object]:
        return {
            "wave": kwargs.get("wave"),
            "files_created": [],
            "files_modified": [],
        }

    async def generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    def run_scaffolding(**_: object) -> list[str]:
        return []

    def save_wave_state(**_: object) -> None:
        return None

    def on_wave_complete(**_: object) -> None:
        return None

    started = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            execute_milestone_waves(
                milestone=milestone,
                ir={"project_name": "Demo"},
                config=SimpleNamespace(),
                cwd=str(tmp_path),
                build_wave_prompt=build_prompt,
                execute_sdk_call=execute_sdk_call,
                run_compile_check=run_compile_check,
                extract_artifacts=extract_artifacts,
                generate_contracts=generate_contracts,
                run_scaffolding=run_scaffolding,
                save_wave_state=save_wave_state,
                on_wave_complete=on_wave_complete,
            ),
            timeout=1.0,
        )
    elapsed = time.perf_counter() - started

    # Outer wait_for must fire at ~1s; if the hung wave swallowed cancellation,
    # elapsed would be the test harness default (>>5s).
    assert elapsed < 3.0, f"outer wait_for did not preempt: elapsed={elapsed:.2f}s"


@pytest.mark.asyncio
async def test_watchdog_does_not_fire_during_active_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session watchdog must NOT fire while the stream is continuously active.

    Regression target: if ``_consume_response_stream`` ever regresses to
    compare total-elapsed against the idle threshold (the original Bug 12
    symptom — the 1.5x timeout wrapper applied wave_total_timeout to
    response processing instead of idle time), any long-running but active
    stream would get cut off mid-flight. This test produces 0.05s-spaced
    messages for ~0.5s total with a 0.2s idle threshold — strictly active,
    total duration far exceeds idle, so any incorrect comparison raises.
    """

    config = AgentTeamConfig()
    config.v18.sub_agent_idle_timeout_seconds = 0.2

    monkeypatch.setattr(cli_module, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(cli_module, "TextBlock", _FakeTextBlock)
    monkeypatch.setattr(cli_module, "ResultMessage", _FakeResultMessage)

    class ActiveClient:
        def __init__(self) -> None:
            self.disconnect_calls = 0
            self.prompts: list[str] = []

        async def query(self, prompt: str) -> None:
            self.prompts.append(prompt)

        async def disconnect(self) -> None:
            self.disconnect_calls += 1

        def receive_response(self):
            async def _iterator():
                # 10 messages at 0.05s spacing = 0.5s of continuous activity,
                # well over the 0.2s idle threshold. Every gap < threshold.
                for i in range(10):
                    await asyncio.sleep(0.05)
                    yield _FakeAssistantMessage(
                        [_FakeTextBlock(f"chunk {i}")]
                    )
                yield _FakeResultMessage(total_cost_usd=0.01)

            return _iterator()

    client = ActiveClient()
    phase_costs: dict[str, float] = {}
    started = time.perf_counter()

    # Must NOT raise — stream is active, watchdog's per-message idle check
    # should see each <0.05s gap and reset.
    await cli_module._run_sdk_session_with_watchdog(
        client,
        "prompt",
        config,
        phase_costs,
        role="research",
    )

    elapsed = time.perf_counter() - started

    # Proves we actually exceeded the idle threshold without the watchdog firing.
    assert elapsed >= 0.45, (
        f"stream completed too quickly to exercise watchdog: elapsed={elapsed:.2f}s"
    )
    # Clean termination — no disconnect from watchdog cancellation.
    assert client.disconnect_calls == 0
