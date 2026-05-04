from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from agent_team_v15.agents import build_wave_b_prompt
from agent_team_v15.codex_captures import (
    CodexCaptureMetadata,
    build_checkpoint_diff_capture_path,
)
from agent_team_v15.codex_prompts import wrap_prompt_for_codex
from agent_team_v15.codex_transport import CodexConfig, CodexResult
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider
from agent_team_v15.wave_executor import _create_checkpoint, _diff_checkpoints


class _MockStdin:
    def __init__(self, owner: "_MockProcess") -> None:
        self._owner = owner
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        chunk = bytes(data)
        self.writes.append(chunk)
        self._owner.consume_stdin(chunk)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._owner.finish(0)

    async def wait_closed(self) -> None:
        return None


class _MockProcess:
    def __init__(self, on_request) -> None:
        self.on_request = on_request
        self.stdin = _MockStdin(self)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None
        self.pid = 4242
        self._stdin_buffer = bytearray()
        self._waiter = asyncio.get_running_loop().create_future()

    def consume_stdin(self, data: bytes) -> None:
        self._stdin_buffer.extend(data)
        while b"\n" in self._stdin_buffer:
            line, _, remainder = self._stdin_buffer.partition(b"\n")
            self._stdin_buffer = bytearray(remainder)
            if not line.strip():
                continue
            request = json.loads(line.decode("utf-8"))
            responses = self.on_request(request)
            if not isinstance(responses, list):
                responses = [responses]
            for response in responses:
                if isinstance(response, tuple) and response[0] == "finish":
                    self.finish(response[1])
                    continue
                self.feed_stdout(response)

    def feed_stdout(self, message: dict[str, object]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.stdout.feed_data(payload)

    def finish(self, returncode: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        if not self._waiter.done():
            self._waiter.set_result(returncode)

    async def wait(self) -> int:
        return await self._waiter

    def kill(self) -> None:
        self.finish(-9)


def _make_milestone() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="milestone-1",
        title="Platform Foundation",
        scope=[],
        requirements=[],
    )


def _make_ir() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        endpoints=[],
        business_rules=[],
        state_machines=[],
        events=[],
        integrations=[],
        integration_items=[],
        acceptance_criteria=[],
    )


def _write_wave_b_workspace(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "SCAFFOLD_OWNERSHIP.md").write_text(
        "\n".join(
            [
                "# Ownership",
                "```yaml",
                "- path: apps/api/src/main.ts",
                "  owner: scaffold",
                "  optional: false",
                "  requirements_deliverable: true",
                "  required_by: scaffold",
                "- path: apps/api/src/auth/hashing.service.ts",
                "  owner: wave-b",
                "  optional: false",
                "  requirements_deliverable: true",
                "  required_by: wave-b",
                "- path: apps/api/src/common/state-machine/state-machine.ts",
                "  owner: wave-b",
                "  optional: false",
                "  requirements_deliverable: true",
                "  required_by: wave-b",
                "```",
            ]
        ),
        encoding="utf-8",
    )

    req_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "REQUIREMENTS.md").write_text(
        "\n".join(
            [
                "# Milestone 1",
                "- Acceptance Criteria: 0 (infrastructure milestone)",
                "- apps/api/src/main.ts must exist.",
                "- apps/api/src/auth/hashing.service.ts must exist.",
                "- apps/api/src/common/state-machine/state-machine.ts must exist.",
            ]
        ),
        encoding="utf-8",
    )
    (req_dir / "TASKS.md").write_text("- [ ] finish foundation wiring\n", encoding="utf-8")


def _wave_b_prompt(tmp_path: Path, *, hardening_enabled: bool) -> str:
    _write_wave_b_workspace(tmp_path)
    cfg = AgentTeamConfig()
    cfg.v18.codex_wave_b_prompt_hardening_enabled = hardening_enabled
    return build_wave_b_prompt(
        milestone=_make_milestone(),
        ir=_make_ir(),
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=None,
        config=cfg,
        existing_prompt_framework="",
        cwd=str(tmp_path),
        milestone_context=None,
        mcp_doc_context="",
    )


def _provider_config(
    *,
    capture_enabled: bool = False,
    flush_wait_enabled: bool = False,
    flush_wait_seconds: float = 0.5,
) -> object:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            codex_capture_enabled=capture_enabled,
            codex_flush_wait_enabled=flush_wait_enabled,
            codex_flush_wait_seconds=flush_wait_seconds,
        ),
        orchestrator=types.SimpleNamespace(model="claude-sonnet-4-6"),
    )


async def _claude_callback(**_kwargs: object) -> float:
    return 0.0


class TestWaveBPromptHardening:
    def test_flag_on_promotes_deliverables_and_emits_write_contract(self, tmp_path: Path) -> None:
        prompt = _wave_b_prompt(tmp_path, hardening_enabled=True)

        assert '<codex_wave_b_write_contract files="3">' in prompt
        assert "[DELIVERABLES - 3 REQUIREMENTS-DECLARED FILES MUST EXIST AFTER THIS WAVE]" in prompt
        assert "[INFRASTRUCTURE MILESTONE CLARIFICATION]" in prompt
        assert 'Acceptance Criteria: 0", that means no user-facing acceptance criteria' in prompt

    def test_flag_on_wrap_adds_tool_persistence_and_count_verification(self, tmp_path: Path) -> None:
        prompt = _wave_b_prompt(tmp_path, hardening_enabled=True)
        wrapped = wrap_prompt_for_codex("B", prompt)

        assert "<tool_persistence>" in wrapped
        assert "the prompt body names 3 requirements-declared files" in wrapped
        assert "<count_verification>" in wrapped

    def test_flag_off_keeps_marker_and_tool_persistence_absent(self, tmp_path: Path) -> None:
        prompt = _wave_b_prompt(tmp_path, hardening_enabled=False)
        wrapped = wrap_prompt_for_codex("B", prompt)

        assert "<codex_wave_b_write_contract" not in prompt
        assert "[DELIVERABLES - 3 REQUIREMENTS-DECLARED FILES MUST EXIST AFTER THIS WAVE]" not in prompt
        assert "<tool_persistence>" not in wrapped
        assert "<count_verification>" not in wrapped


class TestWaveBRouterFixes:
    def test_checkpoint_diff_detects_create_modify_and_delete(self, tmp_path: Path) -> None:
        existing = tmp_path / "apps" / "api" / "src" / "existing.ts"
        deleted = tmp_path / "packages" / "shared" / "src" / "obsolete.ts"
        ignored = tmp_path / ".agent-team" / "ignored.txt"

        existing.parent.mkdir(parents=True, exist_ok=True)
        deleted.parent.mkdir(parents=True, exist_ok=True)
        ignored.parent.mkdir(parents=True, exist_ok=True)

        existing.write_text("export const existing = 1;\n", encoding="utf-8")
        deleted.write_text("export const obsolete = true;\n", encoding="utf-8")
        ignored.write_text("pre\n", encoding="utf-8")

        before = _create_checkpoint("before", str(tmp_path))

        existing.write_text("export const existing = 2;\n", encoding="utf-8")
        deleted.unlink()
        created = tmp_path / "packages" / "shared" / "src" / "generated.ts"
        created.write_text("export const generated = true;\n", encoding="utf-8")
        ignored.write_text("post\n", encoding="utf-8")

        diff = _diff_checkpoints(before, _create_checkpoint("after", str(tmp_path)))

        assert diff.created == ["packages/shared/src/generated.ts"]
        assert diff.modified == ["apps/api/src/existing.ts"]
        assert diff.deleted == ["packages/shared/src/obsolete.ts"]

    @pytest.mark.asyncio
    async def test_flush_wait_uses_configured_seconds(self, monkeypatch, tmp_path: Path) -> None:
        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        async def _codex_exec(
            prompt: str,
            cwd: str,
            config: CodexConfig,
            codex_home: Path | None,
            *,
            progress_callback=None,
            **kwargs,
        ) -> CodexResult:
            del prompt, config, codex_home, progress_callback, kwargs
            target = Path(cwd) / "apps" / "api" / "src" / "generated.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export const generated = true;\n", encoding="utf-8")
            return CodexResult(success=True, model="gpt-5.4")

        monkeypatch.setattr("agent_team_v15.provider_router.asyncio.sleep", _fake_sleep)

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(flush_wait_enabled=True, flush_wait_seconds=0.25),
            provider_map=WaveProviderMap(B="codex"),
            claude_callback=_claude_callback,
            claude_callback_kwargs={"milestone": _make_milestone()},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_codex_exec,
            ),
            codex_config=CodexConfig(max_retries=0),
            codex_home=None,
            checkpoint_create=lambda label, cwd: _create_checkpoint(label, cwd),
            checkpoint_diff=_diff_checkpoints,
        )

        assert result["provider"] == "codex"
        assert sleep_calls == [0.25]

    @pytest.mark.asyncio
    async def test_flush_wait_skipped_when_flag_disabled(self, monkeypatch, tmp_path: Path) -> None:
        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        async def _codex_exec(
            prompt: str,
            cwd: str,
            config: CodexConfig,
            codex_home: Path | None,
            *,
            progress_callback=None,
            **kwargs,
        ) -> CodexResult:
            del prompt, config, codex_home, progress_callback, kwargs
            target = Path(cwd) / "apps" / "api" / "src" / "generated.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export const generated = true;\n", encoding="utf-8")
            return CodexResult(success=True, model="gpt-5.4")

        monkeypatch.setattr("agent_team_v15.provider_router.asyncio.sleep", _fake_sleep)

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(flush_wait_enabled=False),
            provider_map=WaveProviderMap(B="codex"),
            claude_callback=_claude_callback,
            claude_callback_kwargs={"milestone": _make_milestone()},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_codex_exec,
            ),
            codex_config=CodexConfig(max_retries=0),
            codex_home=None,
            checkpoint_create=lambda label, cwd: _create_checkpoint(label, cwd),
            checkpoint_diff=_diff_checkpoints,
        )

        assert result["provider"] == "codex"
        assert sleep_calls == []

    @pytest.mark.asyncio
    async def test_checkpoint_diff_capture_written_when_capture_enabled(self, tmp_path: Path) -> None:
        async def _codex_exec(
            prompt: str,
            cwd: str,
            config: CodexConfig,
            codex_home: Path | None,
            *,
            progress_callback=None,
            **kwargs,
        ) -> CodexResult:
            del prompt, config, codex_home, progress_callback, kwargs
            target = Path(cwd) / "apps" / "api" / "src" / "generated.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export const generated = true;\n", encoding="utf-8")
            return CodexResult(success=True, model="gpt-5.4")

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(capture_enabled=True),
            provider_map=WaveProviderMap(B="codex"),
            claude_callback=_claude_callback,
            claude_callback_kwargs={"milestone": _make_milestone()},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_codex_exec,
            ),
            codex_config=CodexConfig(max_retries=0),
            codex_home=None,
            checkpoint_create=lambda label, cwd: _create_checkpoint(label, cwd),
            checkpoint_diff=_diff_checkpoints,
        )

        capture_path = build_checkpoint_diff_capture_path(
            tmp_path,
            CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        )

        assert result["provider"] == "codex"
        assert capture_path.is_file()

        payload = json.loads(capture_path.read_text(encoding="utf-8"))
        assert payload["diff_created"] == ["apps/api/src/generated.ts"]
        assert payload["metadata"]["pre_file_count"] == 0
        assert payload["metadata"]["post_file_count"] == 1

    @pytest.mark.asyncio
    async def test_checkpoint_diff_capture_skipped_when_capture_disabled(self, tmp_path: Path) -> None:
        async def _codex_exec(
            prompt: str,
            cwd: str,
            config: CodexConfig,
            codex_home: Path | None,
            *,
            progress_callback=None,
            **kwargs,
        ) -> CodexResult:
            del prompt, config, codex_home, progress_callback, kwargs
            target = Path(cwd) / "apps" / "api" / "src" / "generated.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export const generated = true;\n", encoding="utf-8")
            return CodexResult(success=True, model="gpt-5.4")

        await execute_wave_with_provider(
            wave_letter="B",
            prompt="wire backend",
            cwd=str(tmp_path),
            config=_provider_config(capture_enabled=False),
            provider_map=WaveProviderMap(B="codex"),
            claude_callback=_claude_callback,
            claude_callback_kwargs={"milestone": _make_milestone()},
            codex_transport_module=types.SimpleNamespace(
                is_codex_available=lambda: True,
                execute_codex=_codex_exec,
            ),
            codex_config=CodexConfig(max_retries=0),
            codex_home=None,
            checkpoint_create=lambda label, cwd: _create_checkpoint(label, cwd),
            checkpoint_diff=_diff_checkpoints,
        )

        capture_path = build_checkpoint_diff_capture_path(
            tmp_path,
            CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        )
        assert not capture_path.exists()

    @pytest.mark.asyncio
    async def test_all_four_flags_on_dispatches_cleanly(self, monkeypatch, tmp_path: Path) -> None:
        from agent_team_v15 import codex_appserver as appserver

        _write_wave_b_workspace(tmp_path)
        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        def _on_request(request: dict[str, object]) -> list[dict[str, object] | tuple[str, int]]:
            method = request["method"]
            request_id = request["id"]
            if method == "initialize":
                return [
                    {
                        "id": request_id,
                        "result": {
                            "userAgent": "probe/0.121.0",
                            "codexHome": str(tmp_path),
                            "platformFamily": "windows",
                            "platformOs": "windows",
                        },
                    }
                ]
            if method == "thread/start":
                return [
                    {
                        "id": request_id,
                        "result": {
                            "thread": {"id": "thr_1"},
                            "cwd": str(tmp_path.resolve()),
                        },
                    }
                ]
            if method == "turn/start":
                target = tmp_path / "apps" / "api" / "src" / "generated.ts"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("export const generated = true;\n", encoding="utf-8")
                return [
                    {
                        "id": request_id,
                        "result": {
                            "turn": {
                                "id": "turn_1",
                                "items": [],
                                "status": "inProgress",
                                "error": None,
                            }
                        },
                    },
                    {
                        "method": "item/started",
                        "params": {
                            "item": {
                                "type": "commandExecution",
                                "id": "cmd_1",
                                "command": "write generated.ts",
                                "status": "inProgress",
                            }
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "item": {
                                "type": "commandExecution",
                                "id": "cmd_1",
                                "command": "write generated.ts",
                                "status": "completed",
                            }
                        },
                    },
                    {
                        "method": "item/started",
                        "params": {
                            "item": {
                                "type": "agentMessage",
                                "id": "msg_1",
                                "text": "",
                                "phase": "final_answer",
                            }
                        },
                    },
                    {
                        "method": "item/agentMessage/delta",
                        "params": {
                            "threadId": "thr_1",
                            "turnId": "turn_1",
                            "itemId": "msg_1",
                            "delta": "OK",
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "item": {
                                "type": "agentMessage",
                                "id": "msg_1",
                                "text": "OK",
                                "phase": "final_answer",
                            }
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thr_1",
                            "turn": {
                                "id": "turn_1",
                                "items": [],
                                "status": "completed",
                                "error": None,
                            },
                        },
                    },
                ]
            if method == "thread/archive":
                return [{"id": request_id, "result": {}}, ("finish", 0)]
            raise AssertionError(f"Unexpected method: {method}")

        mock_proc = _MockProcess(_on_request)

        # Place codex_home OUTSIDE cwd so ripgrep-config (written into
        # codex_home by the appserver) doesn't leak into the cwd
        # checkpoint diff and inflate diff_created.
        codex_home_dir = tmp_path.parent / f"{tmp_path.name}-codex-home"
        codex_home_dir.mkdir(parents=True, exist_ok=True)

        async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
            assert cwd == str(tmp_path.resolve())
            assert env["CODEX_HOME"] == str(codex_home_dir)
            return mock_proc

        monkeypatch.setattr("agent_team_v15.provider_router.asyncio.sleep", _fake_sleep)
        monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
        monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

        cfg = AgentTeamConfig()
        cfg.v18.codex_wave_b_prompt_hardening_enabled = True
        cfg.v18.codex_capture_enabled = True
        cfg.v18.codex_flush_wait_enabled = True
        cfg.v18.codex_flush_wait_seconds = 0.1

        prompt = build_wave_b_prompt(
            milestone=_make_milestone(),
            ir=_make_ir(),
            wave_a_artifact=None,
            dependency_artifacts=None,
            scaffolded_files=None,
            config=cfg,
            existing_prompt_framework="",
            cwd=str(tmp_path),
            milestone_context=None,
            mcp_doc_context="",
        )

        codex_cfg = CodexConfig(max_retries=0, reasoning_effort="low")
        setattr(codex_cfg, "cwd_propagation_check_enabled", True)

        result = await execute_wave_with_provider(
            wave_letter="B",
            prompt=prompt,
            cwd=str(tmp_path),
            config=cfg,
            provider_map=WaveProviderMap(B="codex"),
            claude_callback=_claude_callback,
            claude_callback_kwargs={"milestone": _make_milestone()},
            codex_transport_module=appserver,
            codex_config=codex_cfg,
            codex_home=codex_home_dir,
            checkpoint_create=lambda label, cwd: _create_checkpoint(label, cwd),
            checkpoint_diff=_diff_checkpoints,
        )

        capture_dir = tmp_path / ".agent-team" / "codex-captures"
        prompt_path = capture_dir / "milestone-1-wave-B-prompt.txt"
        diff_path = build_checkpoint_diff_capture_path(
            tmp_path,
            CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        )

        assert result["provider"] == "codex"
        assert result["fallback_used"] is False
        assert sleep_calls == [0.1]
        assert prompt_path.is_file()
        assert diff_path.is_file()
        assert "<tool_persistence>" in prompt_path.read_text(encoding="utf-8")
        diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
        assert diff_payload["diff_created"] == ["apps/api/src/generated.ts"]
