"""Post-Wave-A scaffold verifier — N-13 (Phase B).

Reads the ownership contract (``docs/SCAFFOLD_OWNERSHIP.md``) and checks that
every scaffold-owned, non-optional file exists on disk, is non-empty, and
parses structurally. Flagged off by default
(``v18.scaffold_verifier_enabled=False``); when on, ``wave_executor`` halts
the pipeline if the verifier reports ``verdict == "FAIL"``.

See ``docs/plans/2026-04-16-phase-b-architecture-report.md`` §6 for the full
design rationale.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from .milestone_scope import MilestoneScope, file_matches_any_glob
from .requirements_parser import parse_dod_port
from .scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    OwnershipContract,
    ScaffoldConfig,
)

_logger = logging.getLogger(__name__)

Verdict = Literal["PASS", "WARN", "FAIL"]


@dataclass
class ScaffoldVerifierReport:
    verdict: Verdict
    missing: list[Path] = field(default_factory=list)
    malformed: list[tuple[Path, str]] = field(default_factory=list)
    deprecated_emitted: list[Path] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        head = (
            f"verdict={self.verdict} "
            f"missing={len(self.missing)} "
            f"malformed={len(self.malformed)} "
            f"deprecated_emitted={len(self.deprecated_emitted)}"
        )
        if not self.summary_lines:
            return head
        return head + "\n" + "\n".join(self.summary_lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_scaffold_verifier(
    workspace: Path,
    ownership_contract: OwnershipContract,
    scaffold_cfg: ScaffoldConfig = DEFAULT_SCAFFOLD_CONFIG,
    *,
    deprecated_paths: Optional[list[str]] = None,
    milestone_scope: MilestoneScope | None = None,
    milestone_id: str | None = None,
) -> ScaffoldVerifierReport:
    """Verify scaffold emission against the ownership contract.

    For each ownership row with ``owner == "scaffold"`` and ``optional is
    False``:
      * Assert the file exists and is non-empty.
      * Apply a per-filetype structural parse.
      * Contribute to a cross-file port-consistency invariant.

    When *milestone_scope* is provided and carries a non-empty
    ``allowed_file_globs`` list, required rows are filtered to paths
    matching the scope — rows belonging to later milestones (e.g. M2
    ``users.module.ts`` during an M1 audit) are skipped so the verifier
    does not report them as missing. The scope filter is the structural
    complement to A-09 on the builder side: A-09 stops the builder from
    producing out-of-scope files; the scope-aware verifier stops the
    post-wave gate from demanding them.

    Returns a :class:`ScaffoldVerifierReport`. The caller (wave_executor)
    decides whether to halt: ``verdict == "FAIL"`` is the canonical halt
    signal, ``WARN`` is advisory, ``PASS`` means all checks succeeded.
    """

    missing: list[Path] = []
    malformed: list[tuple[Path, str]] = []
    deprecated_emitted: list[Path] = []
    summary: list[str] = []

    deprecated_paths = deprecated_paths or [
        "apps/api/src/prisma/prisma.service.ts",
        "apps/api/src/prisma/prisma.module.ts",
        "apps/api/src/auth/auth.module.ts",
        "apps/api/src/users/users.module.ts",
        "apps/api/src/projects/projects.module.ts",
        "apps/api/src/tasks/tasks.module.ts",
        "apps/api/src/comments/comments.module.ts",
    ]

    required_rows = [
        row
        for row in ownership_contract.files
        if row.owner == "scaffold" and not row.optional
    ]

    # Scope filter — only applied when a scope with concrete globs is
    # provided. Empty globs list means "no scope data available" (not
    # "scope forbids everything"); preserve the pre-scope behaviour in
    # that case so this path is a strict additive refinement.
    if milestone_scope is not None and milestone_scope.allowed_file_globs:
        scoped_rows = [
            row
            for row in required_rows
            if file_matches_any_glob(row.path, milestone_scope.allowed_file_globs)
        ]
        dropped = len(required_rows) - len(scoped_rows)
        if dropped:
            summary.append(
                f"SCOPE_FILTER {milestone_scope.milestone_id}: "
                f"{dropped} ownership row(s) skipped as out-of-scope"
            )
        required_rows = scoped_rows

    for row in required_rows:
        abs_path = workspace / row.path
        if not abs_path.exists():
            missing.append(abs_path)
            summary.append(f"MISSING {row.path}")
            continue
        try:
            size = abs_path.stat().st_size
        except OSError as exc:
            malformed.append((abs_path, f"stat failed: {exc}"))
            continue
        if size == 0:
            malformed.append((abs_path, "file is empty"))
            continue
        diag = _parse_file_for_type(abs_path)
        if diag is not None:
            malformed.append((abs_path, diag))
            summary.append(f"MALFORMED {row.path}: {diag}")

    # Deprecated-path check (DRIFT-1/2 style regression guard).
    for rel in deprecated_paths:
        candidate = workspace / rel
        if candidate.exists():
            deprecated_emitted.append(candidate)
            summary.append(f"DEPRECATED_EMITTED {rel}")

    # DoD-port oracle: when REQUIREMENTS.md carries a canonical port in
    # its ``## Definition of Done`` block, that port — not
    # ``scaffold_cfg.port`` — is the source of truth. This supersedes the
    # former hardcoded oracle (smoke #11: compose/env.validation bound to
    # 4000 while DoD mandated 3080).
    expected_port = scaffold_cfg.port
    if milestone_id:
        req_path = (
            workspace
            / ".agent-team"
            / "milestones"
            / milestone_id
            / "REQUIREMENTS.md"
        )
        try:
            dod_port = parse_dod_port(req_path)
        except Exception as exc:  # pragma: no cover — defensive
            _logger.warning(
                "scaffold verifier: DoD-port parse failed for %s: %s",
                req_path,
                exc,
            )
            dod_port = None
        if dod_port is not None:
            expected_port = dod_port
        elif req_path.exists():
            _logger.warning(
                "scaffold verifier: REQUIREMENTS.md %s has no parseable DoD "
                "port; falling back to scaffold_cfg.port=%d",
                req_path,
                scaffold_cfg.port,
            )

    # Port consistency invariant across the PORT-bearing files (main.ts,
    # env.validation.ts, .env.example, apps/api/.env.example, and both
    # compose sources — services.api.environment.PORT AND
    # services.api.ports[0]). Emits SCAFFOLD-PORT-002 on mismatch.
    port_diag = _check_port_consistency(workspace, expected_port)
    if port_diag is not None:
        malformed.append((workspace / ".env.example", port_diag))
        summary.append(f"SCAFFOLD-PORT-002 PORT_INCONSISTENCY {port_diag}")

    # Compose topology invariant: emit SCAFFOLD-COMPOSE-001 when
    # services.api is missing entirely. Before this check the verifier
    # silently fell through when the api service was absent from the
    # compose file (the _check_port_consistency path at :283-292 only
    # added observations when env_block was a dict). The topology check
    # is non-flag-gated: it fixes an always-on silent-pass hole.
    topology_diag = _check_compose_topology(workspace)
    if topology_diag is not None:
        malformed.append((workspace / "docker-compose.yml", topology_diag))
        summary.append(f"SCAFFOLD-COMPOSE-001 {topology_diag}")

    if missing or malformed:
        verdict: Verdict = "FAIL"
    elif deprecated_emitted:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return ScaffoldVerifierReport(
        verdict=verdict,
        missing=missing,
        malformed=malformed,
        deprecated_emitted=deprecated_emitted,
        summary_lines=summary,
    )


# ---------------------------------------------------------------------------
# Per-filetype parsers
# ---------------------------------------------------------------------------


_MAIN_TS_NEST_RE = re.compile(r"NestFactory\.create\s*\(\s*AppModule\s*\)")
_PRISMA_DATASOURCE_RE = re.compile(r"datasource\s+db\s*\{")
_PRISMA_GENERATOR_RE = re.compile(r"generator\s+client\s*\{")
_JOI_PORT_DEFAULT_RE = re.compile(
    r"PORT\s*:\s*Joi\.number\(\)[^\n]*?\.default\(\s*(\d+)\s*\)",
    re.DOTALL,
)
_MAIN_TS_PORT_RE = re.compile(r"process\.env\.PORT\s*\?\?\s*(\d+)")
_ENV_EXAMPLE_PORT_RE = re.compile(r"^PORT\s*=\s*(\d+)\s*$", re.MULTILINE)
_REQUIRED_GITIGNORE_ENTRIES = ("node_modules", "dist", ".next", ".turbo")


def _parse_file_for_type(path: Path) -> Optional[str]:
    """Return a diagnostic string when the parse fails, else None."""

    suffix = path.suffix.lower()
    name = path.name

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"read failed: {exc}"

    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return f"invalid JSON: {exc.msg} at line {exc.lineno}"
        return None

    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            return None  # yaml not available — skip structural parse
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return f"invalid YAML: {exc}"
        return None

    if suffix == ".prisma":
        missing = []
        if not _PRISMA_DATASOURCE_RE.search(text):
            missing.append("datasource db")
        if not _PRISMA_GENERATOR_RE.search(text):
            missing.append("generator client")
        if missing:
            return "prisma schema missing: " + ", ".join(missing)
        return None

    if name == "main.ts":
        if not _MAIN_TS_NEST_RE.search(text):
            return "main.ts missing NestFactory.create(AppModule) call"
        return None

    if name == ".gitignore":
        missing_entries = [
            entry for entry in _REQUIRED_GITIGNORE_ENTRIES if entry not in text
        ]
        if missing_entries:
            return ".gitignore missing: " + ", ".join(missing_entries)
        return None

    # Non-structural types fall through with no diagnostic.
    return None


def _check_port_consistency(workspace: Path, expected_port: int) -> Optional[str]:
    """Assert PORT is equal across main.ts / env.validation.ts / .env.example / docker-compose."""

    observations: list[tuple[str, int]] = []

    main_ts = workspace / "apps" / "api" / "src" / "main.ts"
    if main_ts.exists():
        match = _MAIN_TS_PORT_RE.search(main_ts.read_text(encoding="utf-8"))
        if match is not None:
            observations.append(("apps/api/src/main.ts", int(match.group(1))))

    env_val = workspace / "apps" / "api" / "src" / "config" / "env.validation.ts"
    if env_val.exists():
        match = _JOI_PORT_DEFAULT_RE.search(env_val.read_text(encoding="utf-8"))
        if match is not None:
            observations.append(("apps/api/src/config/env.validation.ts", int(match.group(1))))

    env_example = workspace / ".env.example"
    if env_example.exists():
        match = _ENV_EXAMPLE_PORT_RE.search(env_example.read_text(encoding="utf-8"))
        if match is not None:
            observations.append((".env.example", int(match.group(1))))

    api_env_example = workspace / "apps" / "api" / ".env.example"
    if api_env_example.exists():
        match = _ENV_EXAMPLE_PORT_RE.search(api_env_example.read_text(encoding="utf-8"))
        if match is not None:
            observations.append(("apps/api/.env.example", int(match.group(1))))

    compose = workspace / "docker-compose.yml"
    if compose.exists() and yaml is not None:
        try:
            compose_doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
            api_svc = (compose_doc.get("services") or {}).get("api") or {}
            env_block = api_svc.get("environment") or {}
            if isinstance(env_block, dict):
                port_val = env_block.get("PORT")
                if port_val is not None:
                    try:
                        observations.append(
                            (
                                "docker-compose.yml services.api.environment.PORT",
                                int(port_val),
                            )
                        )
                    except (TypeError, ValueError):
                        pass
            # Also inspect services.api.ports[0] — previously unread. A
            # compose file with ``PORT: "4000"`` but ``ports: ["3080:4000"]``
            # silently ships a host-port split that the probe cannot
            # survive. The host-side (left of the colon) is the value
            # external callers hit.
            ports_block = api_svc.get("ports")
            if isinstance(ports_block, list) and ports_block:
                host_port = _compose_host_port(ports_block[0])
                if host_port is not None:
                    observations.append(
                        (
                            "docker-compose.yml services.api.ports[0]",
                            host_port,
                        )
                    )
        except (yaml.YAMLError, ValueError, TypeError):
            pass

    mismatched = [(src, val) for src, val in observations if val != expected_port]
    if mismatched:
        parts = ", ".join(f"{src}={val}" for src, val in mismatched)
        return f"expected PORT={expected_port} but found {parts}"
    return None


def _compose_host_port(entry: Any) -> Optional[int]:
    """Extract host-side port from a compose ``ports:`` list entry.

    Supports the two observed shapes:
      * short form ``"4000:4000"`` / ``"3080:4000"`` / ``"4000"``
      * long form ``{"published": 4000, "target": 4000}``

    Returns ``None`` when the entry is unrecognised (we do not raise —
    malformed compose files are caught upstream by the yaml parse).
    """

    if isinstance(entry, int):
        return int(entry)
    if isinstance(entry, str):
        head = entry.split(":", 1)[0].strip()
        try:
            return int(head)
        except ValueError:
            return None
    if isinstance(entry, dict):
        published = entry.get("published")
        if isinstance(published, int):
            return int(published)
        if isinstance(published, str):
            try:
                return int(published.strip())
            except ValueError:
                return None
    return None


def _check_compose_topology(workspace: Path) -> Optional[str]:
    """Return a diagnostic when docker-compose.yml lacks ``services.api``.

    Before this check, ``_check_port_consistency`` silently skipped
    compose files whose ``services`` mapping omitted ``api`` entirely
    (the ``if isinstance(env_block, dict)`` guard only fired when ``api``
    was present AND had an ``environment`` mapping). A compose file
    missing the api service was treated as a PASS, because there were
    simply no PORT observations to mismatch against. This surface is the
    SCAFFOLD-COMPOSE-001 hole — fix, not flag-gate.
    """

    compose = workspace / "docker-compose.yml"
    if not compose.exists():
        return None  # upstream MISSING check handles absent compose
    if yaml is None:
        return None  # yaml unavailable — skip structural parse
    try:
        doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return None  # malformed yaml — malformed check handles it

    if not isinstance(doc, dict):
        return "docker-compose.yml is not a mapping"

    services = doc.get("services")
    if not isinstance(services, dict) or "api" not in services:
        return "docker-compose.yml missing services.api"

    return None
