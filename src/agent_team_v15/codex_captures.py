"""Best-effort observability captures for provider-routed Codex dispatches."""

from __future__ import annotations

import json
import logging
import re
import signal
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PROTOCOL_BYTES = 10 * 1024 * 1024
_PROTOCOL_BACKUP_COUNT = 2
_MAX_TOOL_OUTPUT_CHARS = 1024
_MAX_PROTOCOL_DIAGNOSTIC_EVENTS = 30
_OVERSIZED_OUTPUT_DELTA_BYTES = 256 * 1024
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


def _returncode_signal_payload(returncode: int | None) -> dict[str, Any] | None:
    if returncode is None or returncode >= 0:
        return None
    signal_number = abs(int(returncode))
    try:
        signal_name = signal.Signals(signal_number).name
    except Exception:  # noqa: BLE001
        signal_name = f"SIG{signal_number}"
    return {
        "signal_number": signal_number,
        "signal_name": signal_name,
    }


def _orphan_monitor_payload(watchdog: Any | None) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    if watchdog is not None:
        snapshot_pending = getattr(watchdog, "snapshot_pending", None)
        if callable(snapshot_pending):
            with suppress(Exception):
                for item_id, tool_name, age_seconds in snapshot_pending():
                    pending.append(
                        {
                            "item_id": str(item_id),
                            "tool_name": str(tool_name),
                            "age_seconds": round(float(age_seconds), 3),
                        }
                    )
    return {
        "pending_orphan_call_count": len(pending),
        "pending_orphan_calls": pending[:20],
        "orphan_events": int(getattr(watchdog, "orphan_event_count", 0) or 0),
        "last_orphan_tool_name": str(getattr(watchdog, "last_orphan_tool_name", "") or ""),
        "last_orphan_tool_id": str(getattr(watchdog, "last_orphan_tool_id", "") or ""),
        "last_orphan_age_seconds": float(getattr(watchdog, "last_orphan_age", 0.0) or 0.0),
    }


def _diagnostic_classification(
    *,
    exception: BaseException | None,
    protocol: dict[str, Any],
) -> str:
    if bool(protocol.get("turn_completed_observed")):
        return "natural_turn_completed"
    reason = str(getattr(exception, "reason", "") or exception or "")
    if "thread/archive" in reason:
        return "target_thread_archive_before_turn_completed"
    if "EOF" in reason or "stdout EOF" in reason:
        return "transport_stdout_eof_before_turn_completed"
    if exception is not None:
        return "terminal_error_before_turn_completed"
    return "diagnostic_snapshot"


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
    # B3 — per-attempt forensic identity. ``attempt_id`` increments inside
    # the provider-router EOF retry loop so a second EOF doesn't clobber
    # the first attempt's protocol log / response / diagnostic on disk.
    # ``session_id`` is generated once per dispatch boundary so the
    # latest-mirror copy + capture-index can correlate per-attempt files
    # back to the same dispatch chain. Defaults preserve the legacy stem
    # for callers (and on-disk fixtures) that pre-date this extension.
    attempt_id: int = 1
    session_id: str = ""


@dataclass(frozen=True)
class CodexCapturePaths:
    prompt_path: Path
    protocol_path: Path
    response_path: Path
    diagnostic_path: Path


def _legacy_stem(metadata: CodexCaptureMetadata) -> str:
    milestone = _safe_component(metadata.milestone_id, "unknown-milestone")
    wave = _safe_component(metadata.wave_letter.upper(), "unknown-wave")
    suffix = ""
    if metadata.fix_round is not None:
        suffix = f"-fix-{int(metadata.fix_round)}"
    return f"{milestone}-wave-{wave}{suffix}"


def _capture_stem(metadata: CodexCaptureMetadata) -> str:
    base = _legacy_stem(metadata)
    # Attempt 1 retains the legacy stem so existing on-disk consumers
    # (audit, K.2 evaluator, stage_2b driver) keep matching by the canonical
    # filename. Attempts > 1 disambiguate via the per-dispatch session_id
    # so EOF retries don't clobber the first attempt's artifacts.
    attempt_id = int(getattr(metadata, "attempt_id", 1) or 1)
    if attempt_id <= 1:
        return base
    session = _safe_component(getattr(metadata, "session_id", "") or "", "session")
    return f"{base}-attempt-{attempt_id:02d}-{session}"


def build_capture_paths(cwd: str | Path, metadata: CodexCaptureMetadata) -> CodexCapturePaths:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    stem = _capture_stem(metadata)
    return CodexCapturePaths(
        prompt_path=capture_dir / f"{stem}-prompt.txt",
        protocol_path=capture_dir / f"{stem}-protocol.log",
        response_path=capture_dir / f"{stem}-response.json",
        diagnostic_path=capture_dir / f"{stem}-terminal-diagnostic.json",
    )


def build_checkpoint_diff_capture_path(
    cwd: str | Path,
    metadata: CodexCaptureMetadata,
) -> Path:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    return capture_dir / f"{_capture_stem(metadata)}-checkpoint-diff.json"


def _capture_index_path(cwd: str | Path, metadata: CodexCaptureMetadata) -> Path:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    return capture_dir / f"{_legacy_stem(metadata)}-capture-index.json"


def _latest_mirror_paths(cwd: str | Path, metadata: CodexCaptureMetadata) -> dict[str, Path]:
    capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
    base = _legacy_stem(metadata)
    return {
        "prompt": capture_dir / f"{base}-prompt.txt",
        "protocol": capture_dir / f"{base}-protocol.log",
        "response": capture_dir / f"{base}-response.json",
        "diagnostic": capture_dir / f"{base}-terminal-diagnostic.json",
    }


def update_latest_mirror_and_index(
    *,
    cwd: str | Path,
    metadata: CodexCaptureMetadata,
) -> None:
    """B3 — refresh the legacy-stem latest-mirror + append capture-index entry.

    For ``attempt_id == 1`` this is a no-op: the per-attempt files already
    use the legacy stem, so existing consumers find them directly. For
    ``attempt_id > 1`` we copy each per-attempt artifact onto the legacy
    stem (so audit / K.2 evaluator / stage_2b driver continue to find a
    canonical filename without learning about the per-attempt scheme),
    and append the per-attempt entry to the JSON index so reviewers can
    enumerate every attempt for a given (milestone, wave, fix_round).
    Best-effort — an OS error here must NEVER fail the dispatch chain.
    """
    try:
        attempt_id = int(getattr(metadata, "attempt_id", 1) or 1)
        if attempt_id <= 1:
            return
        attempt_paths = build_capture_paths(cwd, metadata)
        attempt_diff_path = build_checkpoint_diff_capture_path(cwd, metadata)
        latest = _latest_mirror_paths(cwd, metadata)
        legacy_base_metadata = CodexCaptureMetadata(
            milestone_id=metadata.milestone_id,
            wave_letter=metadata.wave_letter,
            fix_round=metadata.fix_round,
        )
        latest_diff_path = build_checkpoint_diff_capture_path(cwd, legacy_base_metadata)
        capture_dir = Path(cwd) / ".agent-team" / "codex-captures"
        capture_dir.mkdir(parents=True, exist_ok=True)

        import shutil

        for kind, dst in latest.items():
            src = getattr(attempt_paths, f"{kind}_path")
            if src.is_file():
                with suppress(Exception):
                    shutil.copyfile(str(src), str(dst))
        if attempt_diff_path.is_file():
            with suppress(Exception):
                shutil.copyfile(str(attempt_diff_path), str(latest_diff_path))

        index_path = _capture_index_path(cwd, metadata)
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
        except Exception:  # noqa: BLE001
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        attempts = existing.get("attempts")
        if not isinstance(attempts, list):
            attempts = []
        attempts.append(
            {
                "attempt_id": attempt_id,
                "session_id": str(getattr(metadata, "session_id", "") or ""),
                "stem": _capture_stem(metadata),
                "prompt_path": str(attempt_paths.prompt_path),
                "protocol_path": str(attempt_paths.protocol_path),
                "response_path": str(attempt_paths.response_path),
                "diagnostic_path": str(attempt_paths.diagnostic_path),
                "captured_utc": _utc_now(),
            }
        )
        existing.update(
            {
                "milestone_id": metadata.milestone_id,
                "wave_letter": metadata.wave_letter,
                "fix_round": metadata.fix_round,
                "legacy_stem": _legacy_stem(metadata),
                "attempts": attempts,
            }
        )
        index_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Codex latest-mirror/index refresh failed (non-fatal): %s", exc)


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
        self._method_counts: dict[str, int] = {}
        self._last_events: deque[dict[str, Any]] = deque(maxlen=_MAX_PROTOCOL_DIAGNOSTIC_EVENTS)
        self._total_protocol_bytes_written = 0
        self._protocol_bytes_by_direction: dict[str, int] = {"IN": 0, "OUT": 0}
        self._command_output_delta_bytes_by_item_id: dict[str, int] = {}
        self._largest_output_delta_item_id = ""
        self._largest_output_delta_byte_count = 0
        self._turn_completed_observed = False
        self._target_thread_archive_before_turn_completed = False
        self._last_active_item_id = ""
        self._last_active_item_type = ""
        self._last_active_item_process_id = ""

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
        except Exception:  # noqa: BLE001
            return
        with suppress(Exception):
            self._observe_protocol_event(direction, raw, text)
        try:
            self._logger.info("%s %s %d %s", _utc_now(), direction, len(raw), _mask_text(text))
        except Exception:  # noqa: BLE001
            return

    def _observe_protocol_event(self, direction: str, raw: bytes, text: str) -> None:
        direction = str(direction or "").upper()
        byte_count = len(raw)
        self._total_protocol_bytes_written += byte_count
        self._protocol_bytes_by_direction[direction] = (
            self._protocol_bytes_by_direction.get(direction, 0) + byte_count
        )

        message = json.loads(text)
        if not isinstance(message, dict):
            return
        method = str(message.get("method", "") or "")
        if not method:
            return
        self._method_counts[method] = self._method_counts.get(method, 0) + 1
        params = message.get("params", {})
        if not isinstance(params, dict):
            params = {}

        item = params.get("item", {})
        if not isinstance(item, dict):
            item = {}

        item_id = str(params.get("itemId", "") or item.get("id", "") or "")
        item_type = str(item.get("type", "") or "")
        process_id = str(
            params.get("processId", "")
            or params.get("process_id", "")
            or params.get("pid", "")
            or item.get("processId", "")
            or item.get("process_id", "")
            or item.get("pid", "")
            or ""
        )
        if method == "item/commandExecution/outputDelta":
            item_type = item_type or "commandExecution"
            delta = params.get("delta", "")
            if isinstance(delta, str):
                delta_bytes = len(delta.encode("utf-8", errors="replace"))
            else:
                delta_bytes = len(json.dumps(_sanitize_jsonish(delta), ensure_ascii=False).encode("utf-8"))
            if item_id:
                total = self._command_output_delta_bytes_by_item_id.get(item_id, 0) + delta_bytes
                self._command_output_delta_bytes_by_item_id[item_id] = total
                if total > self._largest_output_delta_byte_count:
                    self._largest_output_delta_item_id = item_id
                    self._largest_output_delta_byte_count = total
        else:
            delta_bytes = None

        if item_id:
            self._last_active_item_id = item_id
            self._last_active_item_type = item_type
            self._last_active_item_process_id = process_id

        if method == "turn/completed":
            self._turn_completed_observed = True
        if direction == "IN" and method == "thread/archive" and not self._turn_completed_observed:
            self._target_thread_archive_before_turn_completed = True

        event: dict[str, Any] = {
            "direction": direction,
            "method": method,
            "protocol_bytes": byte_count,
        }
        if "id" in message:
            event["jsonrpc_id"] = str(message.get("id"))
        thread_id = str(
            params.get("threadId", "")
            or (params.get("thread", {}) if isinstance(params.get("thread"), dict) else {}).get("id", "")
            or ""
        )
        turn = params.get("turn", {})
        if not isinstance(turn, dict):
            turn = {}
        turn_id = str(params.get("turnId", "") or turn.get("id", "") or "")
        if thread_id:
            event["thread_id"] = thread_id
        if turn_id:
            event["turn_id"] = turn_id
        if item_id:
            event["item_id"] = item_id
        if item_type:
            event["item_type"] = item_type
        if process_id:
            event["process_id"] = process_id
        if delta_bytes is not None:
            event["output_delta_bytes"] = delta_bytes
        self._last_events.append(event)

    def stats_payload(self) -> dict[str, Any]:
        return {
            "last_events": list(self._last_events),
            "method_counts": dict(sorted(self._method_counts.items())),
            "total_protocol_bytes_written": self._total_protocol_bytes_written,
            "protocol_bytes_by_direction": dict(sorted(self._protocol_bytes_by_direction.items())),
            "command_output_delta_bytes_by_item_id": dict(
                sorted(self._command_output_delta_bytes_by_item_id.items())
            ),
            "largest_output_delta_item_id": self._largest_output_delta_item_id,
            "largest_output_delta_byte_count": self._largest_output_delta_byte_count,
            "oversized_output_observed": any(
                count >= _OVERSIZED_OUTPUT_DELTA_BYTES
                for count in self._command_output_delta_bytes_by_item_id.values()
            ),
            "oversized_output_threshold_bytes": _OVERSIZED_OUTPUT_DELTA_BYTES,
            "turn_completed_observed": self._turn_completed_observed,
            "target_thread_archive_before_turn_completed": (
                self._target_thread_archive_before_turn_completed
            ),
            "last_active_item_id": self._last_active_item_id,
            "last_active_item_type": self._last_active_item_type,
            "last_active_item_process_id": self._last_active_item_process_id,
        }

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
        self._terminal_diagnostic_path = ""
        self._terminal_diagnostic_classification = ""

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

    @property
    def terminal_diagnostic_path(self) -> str:
        return self._terminal_diagnostic_path

    @property
    def terminal_diagnostic_classification(self) -> str:
        return self._terminal_diagnostic_classification

    def write_terminal_diagnostic(
        self,
        *,
        exception: BaseException | None,
        thread_id: str,
        turn_id: str,
        codex_process_pid: int | None,
        returncode: int | None,
        stderr_tail: str,
        watchdog: Any | None,
        cleanup_thread_archive_after_failure: bool,
    ) -> Path:
        protocol = (
            self.protocol_logger.stats_payload()
            if self.protocol_logger is not None
            else {
                "last_events": [],
                "method_counts": {},
                "total_protocol_bytes_written": 0,
                "protocol_bytes_by_direction": {},
                "command_output_delta_bytes_by_item_id": {},
                "largest_output_delta_item_id": "",
                "largest_output_delta_byte_count": 0,
                "oversized_output_observed": False,
                "oversized_output_threshold_bytes": _OVERSIZED_OUTPUT_DELTA_BYTES,
                "turn_completed_observed": False,
                "target_thread_archive_before_turn_completed": False,
                "last_active_item_id": "",
                "last_active_item_type": "",
                "last_active_item_process_id": "",
            }
        )
        classification = _diagnostic_classification(
            exception=exception,
            protocol=protocol,
        )
        reason = str(getattr(exception, "reason", "") or exception or "")
        turn_completed_observed = bool(protocol.get("turn_completed_observed"))
        target_archive_before_complete = bool(
            protocol.get("target_thread_archive_before_turn_completed")
            or classification == "target_thread_archive_before_turn_completed"
        )
        eof_before_complete = (
            classification == "transport_stdout_eof_before_turn_completed"
            and not turn_completed_observed
        )
        payload = {
            "schema_version": 1,
            "created_utc": _utc_now(),
            "classification": classification,
            "reason": _mask_text(reason),
            "milestone_id": self.metadata.milestone_id,
            "wave": self.metadata.wave_letter,
            "thread_id": str(thread_id or getattr(exception, "thread_id", "") or ""),
            "turn_id": str(turn_id or getattr(exception, "turn_id", "") or ""),
            "codex_process_pid": codex_process_pid,
            "returncode": returncode,
            "returncode_signal": _returncode_signal_payload(returncode),
            "turn_completed_observed": turn_completed_observed,
            "eof_before_turn_completed": eof_before_complete,
            "target_thread_archive_before_turn_completed": target_archive_before_complete,
            "cleanup_thread_archive_after_failure": bool(cleanup_thread_archive_after_failure),
            "orphan_monitor": _orphan_monitor_payload(watchdog),
            "paths": {
                "protocol_log_path": _resolve_path_text(self.paths.protocol_path),
                "response_json_path": _resolve_path_text(self.paths.response_path),
                "diagnostic_path": _resolve_path_text(self.paths.diagnostic_path),
            },
            "protocol": protocol,
            "stderr_tail": _mask_text(str(stderr_tail or ""))[-4096:],
        }
        try:
            self.paths.diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            self.paths.diagnostic_path.write_text(
                json.dumps(_sanitize_jsonish(payload), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._terminal_diagnostic_path = str(self.paths.diagnostic_path)
            self._terminal_diagnostic_classification = classification
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codex terminal diagnostic capture failed (non-fatal): %s", exc)
        return self.paths.diagnostic_path

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
                    "codex_terminal_diagnostic_path": self._terminal_diagnostic_path,
                    "codex_terminal_diagnostic_classification": (
                        self._terminal_diagnostic_classification
                    ),
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
    "update_latest_mirror_and_index",
    "write_checkpoint_diff_capture",
]
