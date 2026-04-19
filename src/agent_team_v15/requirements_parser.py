"""Shared REQUIREMENTS.md parsers — Phase H1a.

Extracts structured anchors from a milestone's ``REQUIREMENTS.md`` so
that multiple post-wave verifiers can agree on a single source of truth
without re-implementing the same markdown parsing.

Today this exposes :func:`parse_dod_port`. Future helpers (DoD command
extraction, API-prefix extraction, etc.) belong here too — the pattern
is pure text-in / structured-value-out, no I/O except the single
``Path.read_text`` at the public entry.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional

_logger = logging.getLogger(__name__)

# `## Definition of Done` is the canonical heading; we accept leading
# whitespace and a trailing colon-or-newline to be forgiving.
_DOD_HEADING_RE = re.compile(r"^\s*##\s+Definition\s+of\s+Done\b", re.IGNORECASE)

# A top-level heading (``# …`` or ``## …``) that is NOT the DoD heading
# ends the DoD block.
_NEXT_HEADING_RE = re.compile(r"^\s*#{1,2}\s+\S")

# Match ``http://localhost:<PORT>`` / ``https://127.0.0.1:<PORT>`` —
# only the port after a localhost-style host. Accept ``localhost``,
# ``127.0.0.1``, and ``0.0.0.0``.
_LOCALHOST_PORT_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})\b"
)


def _iter_dod_lines(text: str) -> Iterable[str]:
    """Yield each line inside the ``## Definition of Done`` section."""

    lines = text.splitlines()
    in_block = False
    for line in lines:
        if in_block:
            # Another h1/h2 heading terminates the block.
            if _NEXT_HEADING_RE.match(line) and not _DOD_HEADING_RE.match(line):
                return
            yield line
            continue
        if _DOD_HEADING_RE.match(line):
            in_block = True


def parse_dod_port(requirements_md_path: Path) -> Optional[int]:
    """Return the canonical port from a milestone REQUIREMENTS.md DoD block.

    Reads the file, locates the ``## Definition of Done`` h2 heading, and
    scans its body for a ``http(s)://localhost:<PORT>`` anchor. Returns
    the first port found (the block is small — a handful of bullets —
    and having multiple ports would itself be a drift we do not have to
    disambiguate here; callers that need to detect multi-port DoDs
    should read the source directly).

    Returns ``None`` when:
      * the file is missing or unreadable,
      * the file has no ``## Definition of Done`` heading,
      * the block has no ``http://localhost:<PORT>`` anchor,
      * the captured port is not a valid 1-65535 integer.

    All failures are silent (no log spam) except unreadable-file, which
    is a single DEBUG — callers (scaffold_verifier / endpoint_prober)
    apply their own WARN logic on ``None``.
    """

    path = Path(requirements_md_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _logger.debug("parse_dod_port: failed to read %s: %s", path, exc)
        return None

    for line in _iter_dod_lines(text):
        match = _LOCALHOST_PORT_RE.search(line)
        if match is None:
            continue
        try:
            port = int(match.group(1))
        except ValueError:
            continue
        if 1 <= port <= 65535:
            return port

    return None


__all__ = ["parse_dod_port", "_iter_dod_lines"]
