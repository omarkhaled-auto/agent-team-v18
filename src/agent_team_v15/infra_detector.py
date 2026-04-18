"""Phase F §7.5: broader runtime infrastructure auto-detection.

Phase A's N-01 extended ``endpoint_prober`` with PORT detection so the
runtime verification layer could reach the API without hard-coding
``localhost:3080``. Phase F widens that auto-detection to four more
infrastructure contracts that downstream probes / verification code
frequently need:

  * API prefix — the NestJS ``setGlobalPrefix(...)`` value from
    ``apps/api/src/main.ts``. Defaults to ``""`` (no prefix) when
    absent so legacy apps keep working.
  * CORS origin — ``CORS_ORIGIN`` from ``apps/api/.env.example``
    (and the top-level ``.env`` as a fallback). Defaults to ``""``.
  * DATABASE_URL — ``DATABASE_URL`` from ``apps/api/.env.example``
    and ``.env``. Used by the M1 startup probe / Prisma migrations.
  * JWT audience — any ``JwtModule.register*`` / ``JwtService``
    registration in ``apps/api/src/**/*.module.ts`` that exposes an
    ``audience`` value. Defensive for M2+ auth milestones.

The detector is intentionally read-only and file-based — it never
executes a probe itself. Output is a plain ``RuntimeInfra`` dataclass
(JSON-serialisable) callers feed into probe URL assembly, CORS header
checks, Prisma connection tests, and audience-aware JWT verification.

Flag ``v18.runtime_infra_detection_enabled`` (default True) disables
the broader detection if a user needs the legacy Phase-A behaviour.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RuntimeInfra:
    """Structured snapshot of auto-detected runtime infrastructure.

    All fields default to empty strings / empty dicts so callers can
    use ``.get`` / truthiness checks without worrying about missing
    data when a project does not define a given contract.
    """

    app_url: str = ""
    api_prefix: str = ""
    cors_origin: str = ""
    database_url: str = ""
    jwt_audience: str = ""
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _runtime_infra_enabled(config: Any) -> bool:
    v18 = getattr(config, "v18", None)
    return bool(getattr(v18, "runtime_infra_detection_enabled", True))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _api_prefix_from_main_ts(path: Path) -> tuple[str, str]:
    """Extract the ``setGlobalPrefix('x')`` argument from NestJS main.ts.

    Returns ``(prefix, source)``. ``prefix`` is stripped of leading
    slashes so callers can freely concatenate ``/<prefix>/<route>``
    without worrying about doubled slashes.
    """
    if not path.is_file():
        return "", ""
    text = _read_text(path)
    # setGlobalPrefix('api'), setGlobalPrefix("api"), setGlobalPrefix(`api`)
    match = re.search(
        r"setGlobalPrefix\s*\(\s*[\"'`]([^\"'`]+)[\"'`]",
        text,
    )
    if not match:
        return "", ""
    prefix = match.group(1).strip().strip("/")
    return prefix, str(path)


def _value_from_env_file(path: Path, var_name: str) -> tuple[str, str]:
    """Return the raw value for ``var_name`` from a KEY=VALUE .env file.

    Keeps string quoting intact (consumers such as CORS_ORIGIN may
    include commas / protocols that we should pass through verbatim).
    Returns ``("", "")`` when the file does not exist or the var is
    unset / empty.
    """
    if not path.is_file():
        return "", ""
    text = _read_text(path)
    # Accept VAR=value, VAR="value", VAR='value'.
    pattern = rf"^\s*{re.escape(var_name)}\s*=\s*(.*)\s*$"
    for line in text.splitlines():
        m = re.match(pattern, line)
        if not m:
            continue
        value = m.group(1).strip()
        if not value or value.startswith("#"):
            continue
        # Strip surrounding quotes if present.
        if (value.startswith("\"") and value.endswith("\"")) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        return value, str(path)
    return "", ""


def _first_env_value(
    project_root: Path, var_name: str, search_paths: list[Path]
) -> tuple[str, str]:
    """Return the first ``var_name`` value found across ``search_paths``."""
    for rel_path in search_paths:
        value, source = _value_from_env_file(project_root / rel_path, var_name)
        if value:
            return value, source
    return "", ""


def _jwt_audience_from_modules(project_root: Path) -> tuple[str, str]:
    """Scan NestJS modules for a JWT audience registration.

    Targets:
      * ``JwtModule.register({ audience: 'foo', ... })``
      * ``JwtModule.registerAsync({ ... useFactory: () => ({ audience: 'foo' }) })``

    Returns ``(audience, source)`` — both empty when nothing found.
    """
    api_src = project_root / "apps" / "api" / "src"
    if not api_src.is_dir():
        return "", ""

    patterns = (
        re.compile(r"audience\s*:\s*[\"'`]([^\"'`]+)[\"'`]"),
        re.compile(r"setAudience\s*\(\s*[\"'`]([^\"'`]+)[\"'`]"),
    )

    for ts_file in api_src.rglob("*.ts"):
        try:
            text = _read_text(ts_file)
        except Exception:
            continue
        if "Jwt" not in text and "jwt" not in text:
            continue
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                audience = m.group(1).strip()
                if audience:
                    return audience, str(ts_file)
    return "", ""


def detect_runtime_infra(
    project_root: Path | str,
    *,
    config: Any | None = None,
) -> RuntimeInfra:
    """Detect runtime infrastructure contracts for the project.

    Order of reads mirrors the precedence used by the build system:
    explicit ``.env`` overrides example files, which override nothing
    (main.ts is source-of-truth only for the API prefix).

    The function is flag-gated — when
    ``v18.runtime_infra_detection_enabled`` is False it returns an
    empty ``RuntimeInfra`` so callers fall back to their pre-Phase-F
    defaults.
    """
    root = Path(project_root)
    infra = RuntimeInfra()

    if config is not None and not _runtime_infra_enabled(config):
        return infra

    # API prefix: only from main.ts. Source of truth is the NestJS boot.
    main_ts = root / "apps" / "api" / "src" / "main.ts"
    prefix, prefix_source = _api_prefix_from_main_ts(main_ts)
    if prefix:
        infra.api_prefix = prefix
        infra.sources["api_prefix"] = prefix_source

    env_search = [
        Path(".env"),
        Path("apps") / "api" / ".env",
        Path("apps") / "api" / ".env.example",
    ]

    cors_origin, cors_source = _first_env_value(root, "CORS_ORIGIN", env_search)
    if cors_origin:
        infra.cors_origin = cors_origin
        infra.sources["cors_origin"] = cors_source

    database_url, database_source = _first_env_value(
        root, "DATABASE_URL", env_search,
    )
    if database_url:
        infra.database_url = database_url
        infra.sources["database_url"] = database_source

    audience, audience_source = _jwt_audience_from_modules(root)
    if audience:
        infra.jwt_audience = audience
        infra.sources["jwt_audience"] = audience_source

    if not any(
        [infra.api_prefix, infra.cors_origin, infra.database_url, infra.jwt_audience]
    ):
        logger.info(
            "infra_detector: no broader runtime contracts detected under %s "
            "(api_prefix/CORS_ORIGIN/DATABASE_URL/JWT audience all empty). "
            "Phase-A port detection in endpoint_prober remains in effect.",
            root,
        )
    else:
        logger.info(
            "infra_detector: detected contracts under %s — api_prefix=%r "
            "cors_origin=%r database_url=%s jwt_audience=%r",
            root,
            infra.api_prefix,
            infra.cors_origin,
            "<set>" if infra.database_url else "",
            infra.jwt_audience,
        )
    return infra


def build_probe_url(
    app_url: str, route: str, *, infra: RuntimeInfra | None = None
) -> str:
    """Compose a probe URL that honours a detected ``api_prefix``.

    ``route`` may begin with ``/`` or not. When ``infra.api_prefix`` is
    empty the result is ``{app_url}{route}`` (or ``{app_url}/{route}``
    with a single slash). When it is set the final URL is
    ``{app_url}/{api_prefix}/{route}`` — one slash between each segment
    regardless of how the caller formatted the inputs.
    """
    base = app_url.rstrip("/")
    clean_route = route.lstrip("/")
    if infra and infra.api_prefix:
        prefix = infra.api_prefix.strip("/")
        if prefix:
            return f"{base}/{prefix}/{clean_route}" if clean_route else f"{base}/{prefix}"
    return f"{base}/{clean_route}" if clean_route else base
