"""Best-effort observability captures for provider-routed Codex dispatches."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PROTOCOL_BYTES = 10 * 1024 * 1024
_PROTOCOL_BACKUP_COUNT = 2
_MAX_TOOL_OUTPUT_CHARS = 1024
_REDACTED = "<redacted>"

_WRITE_ITEM_TYPES = frozenset(
    {
        "applypatch",
        "edit",
        "filechange",
        "fs/copy",
        "fs/createdirectory",
        "fs/remove",
        "fs/writefile",
        "multiedit",
        "write",
    }
)
_READ_ITEM_TYPES = frozenset(
    {
        "fs/getmetadata",
        "fs/readdirectory",
        "fs/readfile",
        "glob",
        "grep",
        "read",
        "search",
    }
)
_SHELL_ITEM_TYPES = frozenset({"commandexecution"})
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "authorization",
        "authheader",
        "authtoken",
        "bearertoken",
        "openai_api_key",
        "openaiapikey",
        "x-api-key",
    }
)
_INLINE_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(OPENAI_API_KEY\s*=\s*)(\S+)"),
    re.compile(r'(?i)("?(?:api[_-]?key|authorization|auth[_-]?token|openai[_-]?api[_-]?key)"?\s*[:=]\s*")([^"]+)(")'),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9/]+", "", str(value or "").strip().lower())


def _safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _mask_text(text: str) -> str:
    masked = str(text or "")
    for pattern in _INLINE_SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(OPENAI_API_KEY"):
            masked = pattern.sub(r"\1" + _REDACTED, masked)
        elif pattern.pattern.startswith("(?i)(\"?"):
            masked = pattern.sub(r"\1" + _REDACTED + r"\3", masked)
        else:
            masked = pattern.sub(_REDACTED, masked)
    return masked


def _sanitize_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _normalize_name(key) in _SENSITIVE_KEYS:
                sanitized[key] = _REDACTED
            else:
                sanitized[key] = _sanitize_jsonish(raw_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_jsonish(item) for item in value]
    if isinstance(value, str):
        return _mask_text(value)
    return value


def _resolve_path_text(path_value: str | Path) -> str:
    try:
        return str(Path(path_value).resolve())
    except Exception:  # noqa: BLE001
        return str(path_value)


def _truncate_output(value: Any) -> str:
    text = json.dumps(_sanitize_jsonish(value), ensure_ascii=False)
    if len(text) <= _MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:_MAX_TOOL_OUTPUT_CHARS] + f"... <truncated from {len(text)} chars>"


def _item_name(item: dict[str, Any]) -> str:
    for key in ("name", "tool", "type"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return "unknown"


def _item_success(item: dict[str, Any]) -> bool | None:
    if "success" in item:
        return bool(item.get("success"))
    status = str(item.get("status", "") or "").strip().lower()
    if status in {"completed", "ok", "success", "succeeded"}:
        return True
    if status in {"failed", "declined", "cancelled", "canceled", "interrupted"}:
        return False
    return None


@dataclass(frozen=True)
class CodexCaptureMetadata:
    milestone_id: str
    wave_letter: str
    fix_round: int | None = None


@dataclass(frozen=True)
class CodexCapturePaths:
    prompt_path: Path
    protocol_path: Path
    response_path: Path


def _capture_stem(metadata: CodexCaptureMetadata) -> str:
    milestone = _safe_component(metadata.milestone_id, "unknown-milestone")
    wave = _safe_component(metadata.wave_letter.upper(), "unknown-wave")
    suffix = ""
    if metadata.fix_round is not None:
        suffix = f"-fix-{int(metadata.fix_round)}"
    return f"{milestone}-wave-{wave}{suffix}"


def build_capture_paths(cwd: str | Path, metadata: CodexCaptureMetadata) -> CodexCapturePaths:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    stem = _capture_stem(metadata)
    return CodexCapturePaths(
        prompt_path=capture_dir / f"{stem}-prompt.txt",
        protocol_path=capture_dir / f"{stem}-protocol.log",
        response_path=capture_dir / f"{stem}-response.json",
    )


def build_checkpoint_diff_capture_path(
    cwd: str | Path,
    metadata: CodexCaptureMetadata,
) -> Path:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    return capture_dir / f"{_capture_stem(metadata)}-checkpoint-diff.json"


def write_checkpoint_diff_capture(
    *,
    cwd: str | Path,
    metadata: CodexCaptureMetadata,
    pre_checkpoint: Any,
    post_checkpoint: Any,
    diff: Any,
) -> None:
    try:
        path = build_checkpoint_diff_capture_path(cwd, metadata)
        path.parent.mkdir(parents=True, exist_ok=True)
        pre_files = sorted(str(path_key) for path_key in getattr(pre_checkpoint, "file_manifest", {}).keys())
        post_files = sorted(str(path_key) for path_key in getattr(post_checkpoint, "file_manifest", {}).keys())
        payload = {
            "pre_checkpoint_files": pre_files,
            "post_checkpoint_files": post_files,
            "diff_created": sorted(str(item) for item in getattr(diff, "created", []) or []),
            "diff_modified": sorted(str(item) for item in getattr(diff, "modified", []) or []),
            "diff_deleted": sorted(str(item) for item in getattr(diff, "deleted", []) or []),
            "metadata": {
                "pre_file_count": len(pre_files),
                "post_file_count": len(post_files),
                "pre_checkpoint_time_utc": getattr(pre_checkpoint, "timestamp", None),
                "post_checkpoint_time_utc": getattr(post_checkpoint, "timestamp", None),
            },
        }
        path.write_text(
            json.dumps(_sanitize_jsonish(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Codex checkpoint-diff capture failed (non-fatal): %s", exc)


class ProtocolCaptureLogger:
    """Write protocol traffic with size accounting and rotation."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = _MAX_PROTOCOL_BYTES,
        backup_count: int = _PROTOCOL_BACKUP_COUNT,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._handler = RotatingFileHandler(
            str(path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self._logger = logging.Logger(f"codex-capture:{path}")
        self._logger.propagate = False
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.INFO)

    def log_out(self, payload: bytes | str) -> None:
        self._write("OUT", payload)

    def log_in(self, payload: bytes | str) -> None:
        self._write("IN", payload)

    def _write(self, direction: str, payload: bytes | str) -> None:
        try:
            if isinstance(payload, bytes):
                raw = payload.rstrip(b"\r\n")
                text = raw.decode("utf-8", errors="replace")
            else:
                text = str(payload or "").rstrip("\r\n")
                raw = text.encode("utf-8")
            self._logger.info("%s %s %d %s", _utc_now(), direction, len(raw), _mask_text(text))
        except Exception:  # noqa: BLE001
            return

    def close(self) -> None:
        try:
            self._handler.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._handler.close()
            self._logger.removeHandler(self._handler)
        except Exception:  # noqa: BLE001
            pass


@dataclass
class ToolCallRecord:
    sequence: int
    item_id: str
    tool_name: str
    item_type: str
    started_utc: str
    completed_utc: str | None = None
    input: Any | None = None
    output_summary: str | None = None
    success: bool | None = None


class ResponseCaptureAccumulator:
    """Accumulate final assistant output plus non-message item lifecycle."""

    def __init__(self) -> None:
        self._message_buffers: dict[str, str] = {}
        self._completed_messages: list[str] = []
        self._final_answer: str = ""
        self._tool_calls: list[ToolCallRecord] = []
        self._pending_by_id: dict[str, ToolCallRecord] = {}
        self._sequence = 0

    def observe_event(self, event: dict[str, Any]) -> None:
        method = str(event.get("method", "") or "")
        params = event.get("params", {})
        if not isinstance(params, dict):
            return

        if method == "item/agentMessage/delta":
            item_id = str(params.get("itemId", "") or "")
            delta = str(params.get("delta", "") or "")
            if item_id and delta:
                self._message_buffers[item_id] = self._message_buffers.get(item_id, "") + delta
            return

        if method == "item/started":
            item = params.get("item", {})
            if isinstance(item, dict):
                self._record_item_started(item)
            return

        if method == "item/completed":
            item = params.get("item", {})
            if isinstance(item, dict):
                self._record_item_completed(item)

    def _record_item_started(self, item: dict[str, Any]) -> None:
        item_type = str(item.get("type", "") or "")
        if item_type == "agentMessage":
            return
        item_id = str(item.get("id", "") or "")
        if not item_id:
            return
        record = ToolCallRecord(
            sequence=self._sequence,
            item_id=item_id,
            tool_name=_item_name(item),
            item_type=item_type,
            started_utc=_utc_now(),
            input=_sanitize_jsonish(item),
        )
        self._sequence += 1
        self._tool_calls.append(record)
        self._pending_by_id[item_id] = record

    def _record_item_completed(self, item: dict[str, Any]) -> None:
        item_type = str(item.get("type", "") or "")
        item_id = str(item.get("id", "") or "")
        if item_type == "agentMessage":
            text = str(item.get("text", "") or self._message_buffers.get(item_id, "") or "")
            if text:
                if str(item.get("phase", "") or "") == "final_answer":
                    self._final_answer = text
                self._completed_messages.append(text)
            return
        if not item_id:
            return
        record = self._pending_by_id.pop(item_id, None)
        if record is None:
            record = ToolCallRecord(
                sequence=self._sequence,
                item_id=item_id,
                tool_name=_item_name(item),
                item_type=item_type,
                started_utc=_utc_now(),
            )
            self._sequence += 1
            self._tool_calls.append(record)
        record.completed_utc = _utc_now()
        record.output_summary = _truncate_output(item)
        record.success = _item_success(item)

    def final_message(self) -> str:
        if self._final_answer:
            return self._final_answer
        if self._completed_messages:
            return self._completed_messages[-1]
        return ""

    def tool_calls_payload(self) -> list[dict[str, Any]]:
        return [asdict(record) for record in self._tool_calls]

    def summary(self) -> dict[str, Any]:
        breakdown: dict[str, int] = {}
        write_invocations = 0
        read_invocations = 0
        shell_invocations = 0
        for record in self._tool_calls:
            name = record.tool_name or record.item_type or "unknown"
            breakdown[name] = breakdown.get(name, 0) + 1
            item_type = _normalize_name(record.item_type)
            tool_name = _normalize_name(record.tool_name)
            if item_type in _WRITE_ITEM_TYPES or tool_name in _WRITE_ITEM_TYPES:
                write_invocations += 1
            elif item_type in _READ_ITEM_TYPES or tool_name in _READ_ITEM_TYPES:
                read_invocations += 1
            elif item_type in _SHELL_ITEM_TYPES or tool_name in _SHELL_ITEM_TYPES:
                shell_invocations += 1
        return {
            "total_tool_calls": len(self._tool_calls),
            "tool_breakdown": breakdown,
            "write_tool_invocations": write_invocations,
            "read_tool_invocations": read_invocations,
            "shell_tool_invocations": shell_invocations,
        }


class CodexCaptureSession:
    """Own prompt/protocol/response capture state for one dispatch."""

    def __init__(
        self,
        *,
        metadata: CodexCaptureMetadata,
        cwd: str,
        model: str,
        reasoning_effort: str,
        spawn_cwd: str,
        subprocess_argv: list[str] | None,
    ) -> None:
        self.metadata = metadata
        self.cwd = cwd
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.dispatch_start_utc = _utc_now()
        self.spawn_cwd = spawn_cwd
        self.subprocess_argv = list(subprocess_argv or [])
        self.paths = build_capture_paths(cwd, metadata)
        self.responses = ResponseCaptureAccumulator()
        self.protocol_logger: ProtocolCaptureLogger | None = None

        try:
            self.protocol_logger = ProtocolCaptureLogger(self.paths.protocol_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex protocol capture setup failed (non-fatal): %s", exc)

    def capture_prompt(self, rendered_prompt: str) -> None:
        try:
            self.paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                f"# Milestone: {self.metadata.milestone_id}\n"
                f"# Wave: {self.metadata.wave_letter}\n"
                f"# Dispatch-start: {self.dispatch_start_utc}\n"
                f"# Cwd-orchestrator-passed: {_resolve_path_text(self.cwd)}\n"
                f"# Cwd-codex-subprocess-argv: {_resolve_path_text(self.spawn_cwd)}\n"
                f"# Model: {self.model}\n"
                f"# Reasoning-effort: {self.reasoning_effort}\n"
                "# ---\n"
            )
            self.paths.prompt_path.write_text(
                header + _mask_text(rendered_prompt),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex prompt capture failed (non-fatal): %s", exc)

    def observe_event(self, event: dict[str, Any]) -> None:
        self.responses.observe_event(event)

    def finalize(self, *, codex_result: Any | None, exception: BaseException | None = None) -> None:
        try:
            self.paths.response_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "metadata": {
                    "milestone_id": self.metadata.milestone_id,
                    "wave_letter": self.metadata.wave_letter,
                    "dispatch_start_utc": self.dispatch_start_utc,
                    "dispatch_end_utc": _utc_now(),
                    "cwd_orchestrator_passed": _resolve_path_text(self.cwd),
                    "cwd_codex_subprocess_spawn": _resolve_path_text(self.spawn_cwd),
                    "codex_result_success": getattr(codex_result, "success", None),
                    "codex_result_model": getattr(codex_result, "model", None) or self.model,
                    "codex_result_tokens": {
                        "input_tokens": getattr(codex_result, "input_tokens", None),
                        "output_tokens": getattr(codex_result, "output_tokens", None),
                        "reasoning_tokens": getattr(codex_result, "reasoning_tokens", None),
                        "cached_input_tokens": getattr(codex_result, "cached_input_tokens", None),
                    },
                    "codex_result_retry_count": getattr(codex_result, "retry_count", None),
                    "codex_result_exit_code": getattr(codex_result, "exit_code", None),
                    "codex_result_error": _mask_text(str(getattr(codex_result, "error", "") or "")),
                    "dispatch_exception": None if exception is None else _mask_text(str(exception)),
                },
                "final_agent_message": _mask_text(self.responses.final_message()),
                "tool_calls": self.responses.tool_calls_payload(),
                "cumulative_tool_summary": self.responses.summary(),
            }
            self.paths.response_path.write_text(
                json.dumps(_sanitize_jsonish(payload), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex response capture failed (non-fatal): %s", exc)

    def close(self) -> None:
        if self.protocol_logger is not None:
            self.protocol_logger.close()


__all__ = [
    "CodexCaptureMetadata",
    "CodexCapturePaths",
    "CodexCaptureSession",
    "ProtocolCaptureLogger",
    "ResponseCaptureAccumulator",
    "ToolCallRecord",
    "build_capture_paths",
    "build_checkpoint_diff_capture_path",
    "write_checkpoint_diff_capture",
]
