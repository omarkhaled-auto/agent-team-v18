"""Focused single-turn peek call for Claude wave observation.

Codex waves do NOT use this module.

This module is for Claude waves (A, D5, T, E) only.

Contract:
- run_peek_call is fail-open: any exception returns a safe PeekResult(verdict="ok").
- Every call writes a JSONL entry to .agent-team/observer_log.jsonl (best-effort).
- log_only=True disables should_interrupt.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from .wave_executor import PeekResult, PeekSchedule

logger = logging.getLogger(__name__)

_OBSERVER_RUN_ID = (
    os.environ.get("AGENT_TEAM_RUN_ID")
    or os.environ.get("AGENT_TEAM_BUILD_ID")
    or f"pid-{os.getpid()}-{int(time.time())}"
)

_PEEK_SYSTEM_PROMPT = """\
You are a focused code quality observer. You are given a file just written by an AI coding agent
and the requirement it should satisfy.

Respond with ONLY valid JSON:
{"verdict": "ok" | "issue", "confidence": <0.0-1.0>, "message": "<one sentence>"}

Rules:
- "ok" = file exists, non-empty, plausibly satisfies the requirement
- "issue" = stub/empty/wrong type/completely off-scope
- confidence < 0.5 = uncertain - prefer "ok" when uncertain
- Do NOT flag style issues, TODO comments, or features planned for later waves
- If you cannot determine: {"verdict": "ok", "confidence": 0.3, "message": "cannot determine"}
"""


def build_peek_prompt(
    file_path: str,
    file_content: str,
    schedule: PeekSchedule,
    framework_pattern: str,
) -> str:
    lines = [
        f"## File written: `{file_path}`",
        f"## Wave: {schedule.wave} | Milestone: {schedule.milestone_id}",
        "",
        "## Requirement context:",
        schedule.requirements_text[:800],
        "",
    ]
    if framework_pattern:
        lines += ["## Expected pattern:", framework_pattern[:400], ""]

    # Truncation guard: a naive `file_content[:N]` can end mid-directive,
    # which leads Haiku to flag the snippet itself as syntactically invalid
    # (see R1B1: 924-char Dockerfile, s[:600] ended at a bare "WORKDIR",
    # producing a 0.95-confidence FP on an otherwise valid file). Cap high
    # enough to fit typical config/scaffold files end-to-end, cut on the
    # last newline when truncation is still needed so the snippet never
    # ends inside a directive or token, and label the slice so the model
    # does not reason about what lies beyond the boundary.
    max_snippet_chars = 4000
    snippet = file_content[:max_snippet_chars]
    truncated = len(file_content) > max_snippet_chars
    if truncated:
        last_newline = snippet.rfind("\n")
        if last_newline > 0:
            snippet = snippet[:last_newline]
    if truncated:
        content_header = (
            f"## File content ({len(file_content)} chars total, TRUNCATED — "
            "you are seeing the first portion only; the file continues beyond "
            "this snippet. Do not infer syntactic completeness or "
            "incompleteness from the snippet boundary. Continue to flag "
            "genuine stubs, empty bodies, wrong types, or off-scope content "
            "within the visible portion.):"
        )
    else:
        content_header = f"## File content ({len(file_content)} chars total):"
    lines += [
        content_header,
        "```",
        snippet,
        "```",
        "",
        'Respond with JSON only: {"verdict": ..., "confidence": ..., "message": ...}',
    ]
    return "\n".join(lines)


def build_corrective_interrupt_prompt(result: PeekResult) -> str:
    """Specific, actionable corrective message for client.interrupt() on Claude waves."""
    return (
        f"[OBSERVER interrupt - confidence={result.confidence:.0%}]\n"
        f"Wave {result.wave} - file `{result.file_path}` was just written but has an issue:\n\n"
        f"  {result.message}\n\n"
        f"Please fix `{result.file_path}` before continuing. "
        f"If this assessment is incorrect, reply briefly and continue."
    )


def build_codex_steer_prompt(result: PeekResult) -> str:
    """Specific corrective message for Codex steering."""
    return (
        f"[Observer steer - confidence={result.confidence:.0%}]\n"
        f"The file `{result.file_path}` has an issue: {result.message}\n"
        f"Please correct it before moving to the next file."
    )


class _PeekResponseShim:
    """Minimal response shape matching anthropic SDK (`.content[0].text`) so
    call sites keep working when the underlying peek call runs via
    claude_agent_sdk instead of the anthropic SDK."""

    __slots__ = ("content",)

    def __init__(self, text: str) -> None:
        self.content = [_PeekResponseShimBlock(text)]


class _PeekResponseShimBlock:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


async def _call_via_claude_agent_sdk(
    prompt: str, system: str, model: str
) -> _PeekResponseShim:
    """Run the peek through claude_agent_sdk.ClaudeSDKClient.

    Uses `claude login` subscription auth — the same mechanism the main v18
    orchestrator (cli.py) and audit scorer (audit_agent.py) already ride on.
    Spawns one Claude CLI subprocess per peek and tears it down on exit.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from claude_agent_sdk.types import AssistantMessage

    options = ClaudeAgentOptions(
        model=model,
        max_turns=1,
        permission_mode="bypassPermissions",
        system_prompt=system,
        allowed_tools=[],
    )
    result_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in getattr(msg, "content", []) or []:
                    if hasattr(block, "text") and block.text:
                        result_text += block.text
    return _PeekResponseShim(result_text)


async def _call_anthropic_api(prompt: str, system: str, model: str, max_tokens: int) -> Any:
    """Call Claude for an observer peek verdict.

    Subscription-first: try `claude_agent_sdk.ClaudeSDKClient` (uses
    `claude login` auth, zero env vars required — same auth Claude Code
    itself uses for every tool call). Fall through to `anthropic.AsyncAnthropic`
    only when the SDK path is unavailable (import error or runtime failure);
    that path requires `ANTHROPIC_API_KEY`.
    """
    try:
        return await _call_via_claude_agent_sdk(prompt, system, model)
    except Exception as sdk_exc:
        logger.debug(
            "observer: claude_agent_sdk path unavailable (%s); "
            "trying anthropic SDK (requires ANTHROPIC_API_KEY)",
            sdk_exc,
        )

    import anthropic

    client = anthropic.AsyncAnthropic()
    return await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def _load_file_content(cwd: str, file_path: str) -> str:
    try:
        return (Path(cwd) / file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _fetch_context7_pattern(file_path: str) -> str:
    """Best-effort Context7 pattern hint. Returns empty string on any failure."""
    del file_path
    return ""


def _parse_peek_response(response_text: str) -> dict[str, Any]:
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        return {
            "verdict": str(data.get("verdict", "ok")),
            "confidence": float(data.get("confidence", 0.5)),
            "message": str(data.get("message", "")),
        }
    except Exception:
        return {"verdict": "ok", "confidence": 0.3, "message": "parse error - defaulting to ok"}


def _write_observer_log(cwd: str, result: PeekResult) -> None:
    try:
        log_path = Path(cwd) / ".agent-team" / "observer_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": result.timestamp,
            "run_id": _OBSERVER_RUN_ID,
            "wave": result.wave,
            "file": result.file_path,
            "verdict": result.verdict,
            "confidence": result.confidence,
            "message": result.message,
            "source": result.source,
            "log_only": result.log_only,
            "would_interrupt": result.verdict == "issue" and result.confidence >= 0.5,
            "did_interrupt": result.should_interrupt,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("observer: failed to write log entry: %s", e)


async def run_peek_call(
    cwd: str,
    file_path: str,
    schedule: PeekSchedule,
    log_only: bool,
    model: str,
    confidence_threshold: float,
    max_tokens: int = 512,
) -> PeekResult:
    """Run one focused peek call.

    Always writes to observer_log.jsonl. Fail-open: any exception below yields
    a safe PeekResult(verdict="ok", should_interrupt=False) so the wave proceeds.
    Only sets should_interrupt=True when log_only=False and confidence >= threshold.
    """
    try:
        file_content = _load_file_content(cwd, file_path)
        if not file_content.strip():
            result = PeekResult(
                file_path=file_path,
                wave=schedule.wave,
                verdict="skip",
                confidence=1.0,
                message="file is empty - skipping peek",
                log_only=log_only,
                source="file_poll",
            )
            _write_observer_log(cwd, result)
            return result

        framework_pattern = _fetch_context7_pattern(file_path)
        prompt = build_peek_prompt(file_path, file_content, schedule, framework_pattern)

        try:
            response = await _call_anthropic_api(prompt, _PEEK_SYSTEM_PROMPT, model, max_tokens)
            raw_text = response.content[0].text if response.content else ""
            parsed = _parse_peek_response(raw_text)
        except Exception as e:
            logger.warning("observer: peek API call failed for %s: %s", file_path, e)
            parsed = {"verdict": "ok", "confidence": 0.0, "message": f"peek failed: {e}"}
            raw_text = ""

        confidence = float(parsed["confidence"])
        verdict = str(parsed["verdict"])
        if verdict == "issue" and confidence < confidence_threshold:
            verdict = "ok"

        result = PeekResult(
            file_path=file_path,
            wave=schedule.wave,
            verdict=verdict,
            confidence=confidence,
            message=str(parsed["message"]),
            raw_response=raw_text,
            log_only=log_only,
            source="file_poll",
        )
        _write_observer_log(cwd, result)
        return result
    except Exception as e:
        logger.warning("observer: run_peek_call top-level failure for %s: %s", file_path, e)
        safe_result = PeekResult(
            file_path=file_path,
            wave=schedule.wave,
            verdict="ok",
            confidence=0.0,
            message=f"peek infrastructure failure: {e}",
            log_only=log_only,
            source="file_poll",
        )
        _write_observer_log(cwd, safe_result)
        return safe_result
