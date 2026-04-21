"""Cross-protocol bridge between Codex app-server waves and Claude phase leads.

The orchestrator calls :func:`route_codex_wave_complete` after each Codex
turn/completed and routes a CODEX_WAVE_COMPLETE message to the relevant
Claude lead via the shared context directory.

Claude leads write STEER_REQUEST files into the same context directory.
The orchestrator calls :func:`read_pending_steer_requests` before the next
Codex turn/start and translates the returned bodies into turn/steer calls
against the active Codex thread.

Both entry points are fail-open: any I/O failure is logged and swallowed.
An unknown wave letter is a no-op.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps Codex wave letter to the Claude lead that owns its review.
WAVE_TO_LEAD: dict[str, str] = {
    "A5": "wave-a-lead",
    "B": "wave-a-lead",
    "D": "wave-d5-lead",
    "T5": "wave-t-lead",
}


def _codex_sender(wave_letter: str) -> str:
    return f"codex-wave-{wave_letter.lower()}"


def route_codex_wave_complete(
    wave_letter: str,
    context_dir: Path,
    result_summary: str,
) -> None:
    """Write a CODEX_WAVE_COMPLETE message to the context directory.

    The message follows the same framed format used by
    ``AgentTeamsBackend.route_message`` so existing parsing logic works
    unchanged. Unknown waves and any I/O failure are logged and swallowed.
    """
    try:
        lead = WAVE_TO_LEAD.get(wave_letter)
        if lead is None:
            logger.info(
                "codex_lead_bridge: no Claude lead mapped for wave %r - skipping",
                wave_letter,
            )
            return

        timestamp = int(time.time() * 1000)
        sender = _codex_sender(wave_letter)
        body = (
            f"To: {lead}\n"
            f"From: {sender}\n"
            f"Type: CODEX_WAVE_COMPLETE\n"
            f"Timestamp: {timestamp}\n"
            f"Wave: {wave_letter}\n"
            f"---\n"
            f"{result_summary}"
        )
        path = Path(context_dir) / f"msg_{timestamp}_{sender}_to_{lead}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        logger.info(
            "codex_lead_bridge: routed CODEX_WAVE_COMPLETE wave=%s -> %s (%s)",
            wave_letter,
            lead,
            path.name,
        )
    except OSError as exc:
        logger.warning(
            "codex_lead_bridge.route_codex_wave_complete failed (wave=%s): %s",
            wave_letter,
            exc,
        )


def read_pending_steer_requests(
    wave_letter: str,
    context_dir: Path,
) -> list[str]:
    """Return STEER_REQUEST bodies addressed to the given Codex wave.

    Looks for files of the form ``msg_*_<sender>_to_codex-wave-<letter>.md``
    in *context_dir* with ``Type: STEER_REQUEST`` in the header. Returns the
    bodies (text after the ``---`` framing line) in filename order.
    Missing directory, unreadable files, and malformed headers are swallowed
    and contribute nothing to the result.
    """
    results: list[str] = []
    try:
        target = _codex_sender(wave_letter)
        base = Path(context_dir)
        if not base.exists():
            return results
        for path in sorted(base.glob(f"msg_*_to_{target}.md")):
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.debug(
                    "codex_lead_bridge: unreadable steer file %s: %s",
                    path,
                    exc,
                )
                continue
            header, _, body = raw.partition("\n---\n")
            if "Type: STEER_REQUEST" not in header:
                continue
            results.append(body.strip())
    except OSError as exc:
        logger.warning(
            "codex_lead_bridge.read_pending_steer_requests failed (wave=%s): %s",
            wave_letter,
            exc,
        )
    return results
