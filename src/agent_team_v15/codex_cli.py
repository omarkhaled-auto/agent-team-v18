"""Shared Codex CLI helpers for versioning, binary resolution, and error tagging."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from typing import Final

PROJECT_DOC_MAX_BYTES_KEY: Final[str] = "project_doc_max_bytes"
PROJECT_DOC_MAX_BYTES_DEFAULT: Final[int] = 65536
LAST_VALIDATED_CODEX_CLI_VERSION: Final[tuple[int, int, int]] = (0, 121, 0)
LAST_VALIDATED_CODEX_CLI_VERSION_TEXT: Final[str] = "0.121.0"

CODEX_CONFIG_SCHEMA_ERROR_CODE: Final[str] = "CODEX-CONFIG-SCHEMA-001"
# Kept to match the H2a plan naming even though the transport is protocol-native.
CODEX_APP_SERVER_AUTH_ERROR_CODE: Final[str] = "CODEX-SDK-AUTH-FAILED-001"

_VERSION_RE = re.compile(r"codex-cli\s+(\d+)\.(\d+)\.(\d+)")


def render_project_codex_config_toml(max_bytes: int = PROJECT_DOC_MAX_BYTES_DEFAULT) -> str:
    """Render the canonical project-root `.codex/config.toml` snippet."""
    return (
        "# Raise AGENTS.md cap from 32 KiB default to 64 KiB (Phase G Slice 1d).\n"
        f"{PROJECT_DOC_MAX_BYTES_KEY} = {int(max_bytes)}\n"
    )


def resolve_codex_binary() -> str:
    """Resolve a subprocess-safe Codex binary path."""
    if sys.platform == "win32":
        return shutil.which("codex.cmd") or shutil.which("codex") or "codex"
    return shutil.which("codex") or "codex"


def detect_codex_cli_version(
    codex_bin: str | None = None,
    *,
    timeout_seconds: int = 10,
) -> str | None:
    """Return the installed Codex CLI version string, or `None` on failure."""
    binary = codex_bin or resolve_codex_binary()
    try:
        raw = subprocess.check_output(
            [binary, "--version"],
            text=True,
            timeout=timeout_seconds,
            stderr=subprocess.STDOUT,
        ).strip()
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    return raw or None


def parse_codex_cli_version(version_text: str | None) -> tuple[int, int, int] | None:
    """Parse `codex-cli X.Y.Z` into a comparable version tuple."""
    if not version_text:
        return None
    match = _VERSION_RE.search(version_text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def log_codex_cli_version(
    logger: logging.Logger,
    *,
    codex_bin: str | None = None,
    schema_version_text: str = LAST_VALIDATED_CODEX_CLI_VERSION_TEXT,
) -> str | None:
    """Log the detected Codex CLI version and any compatibility warning."""
    version_text = detect_codex_cli_version(codex_bin)
    if not version_text:
        logger.warning("Unable to detect Codex CLI version; continuing without schema guard.")
        return None

    logger.info(
        "Detected Codex CLI v%s; emitting config for schema v%s",
        version_text.removeprefix("codex-cli ").strip(),
        schema_version_text,
    )

    parsed = parse_codex_cli_version(version_text)
    if parsed is None:
        logger.warning(
            "Codex CLI version string was unreadable (%s); continuing without schema drift warning.",
            version_text,
        )
        return version_text

    if parsed > LAST_VALIDATED_CODEX_CLI_VERSION:
        logger.warning(
            "Codex CLI v%s may have schema changes since v%s; if config rejection errors occur, "
            "update docs/plans/phase-h2a-codex-config-schema.md.",
            version_text.removeprefix("codex-cli ").strip(),
            schema_version_text,
        )
    elif parsed < LAST_VALIDATED_CODEX_CLI_VERSION:
        logger.warning(
            "Codex CLI v%s is older than the last validated schema v%s and may reject the current config.",
            version_text.removeprefix("codex-cli ").strip(),
            schema_version_text,
        )
    return version_text


def classify_codex_error_message(message: str) -> str | None:
    """Map a raw Codex error string to a stable H2a pattern code when possible."""
    collapsed = " ".join((message or "").split())
    lowered = collapsed.lower()
    if not lowered:
        return None

    if (
        "failed to load configuration" in lowered
        or "expected a boolean" in lowered
        or ("invalid type:" in lowered and PROJECT_DOC_MAX_BYTES_KEY in lowered)
    ):
        return CODEX_CONFIG_SCHEMA_ERROR_CODE

    if (
        "unauthorized" in lowered
        or "auth" in lowered and ("expired" in lowered or "login" in lowered or "token" in lowered)
        or "api key" in lowered
        or "401" in lowered
    ):
        return CODEX_APP_SERVER_AUTH_ERROR_CODE

    return None


def prefix_codex_error_code(message: str) -> str:
    """Prefix a known Codex error code once; leave unknown messages unchanged."""
    code = classify_codex_error_message(message)
    if code is None:
        return message
    if message.startswith(f"{code}:"):
        return message
    return f"{code}: {message}"


__all__ = [
    "CODEX_APP_SERVER_AUTH_ERROR_CODE",
    "CODEX_CONFIG_SCHEMA_ERROR_CODE",
    "LAST_VALIDATED_CODEX_CLI_VERSION",
    "LAST_VALIDATED_CODEX_CLI_VERSION_TEXT",
    "PROJECT_DOC_MAX_BYTES_DEFAULT",
    "PROJECT_DOC_MAX_BYTES_KEY",
    "classify_codex_error_message",
    "detect_codex_cli_version",
    "log_codex_cli_version",
    "parse_codex_cli_version",
    "prefix_codex_error_code",
    "render_project_codex_config_toml",
    "resolve_codex_binary",
]
