"""Deterministic template renderer for curated infrastructure templates.

Issue #14: Replace Codex-authored Dockerfiles with a curated template dropped
into the build dir before Wave B dispatches. Codex's job becomes "write app
code that fits this container layout" — not "author infra from scratch".

The renderer is intentionally minimal: ``str.replace`` for ``{{ SLOT }}``
substitution, no Jinja, no templating dependencies. Slot values carry a dry
typed contract (:class:`TemplateSlotValues`) so regressions are caught at
dataclass construction rather than deep inside a template.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, fields
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from .stack_contract import StackContract

logger = logging.getLogger(__name__)


_TEMPLATES_PACKAGE = "agent_team_v15.templates"
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Z_][A-Z0-9_]*\s*\}\}")


class TemplateNotFoundError(LookupError):
    """Raised when :func:`render_template` receives an unknown template name."""


class TemplateRenderError(ValueError):
    """Raised when slot validation or substitution fails."""


@dataclass(frozen=True)
class TemplateSlotValues:
    """Slot values substituted into a template. Defaults match scaffold_runner.

    All fields are frozen — a rendered template is a pure function of its
    slot values, so the dataclass instance is hashable + safe to share.
    """

    api_service_name: str = "api"
    web_service_name: str = "web"
    api_port: int = 4000
    web_port: int = 3000
    postgres_port: int = 5432
    postgres_version: str = "16-alpine"
    postgres_db: str = "app"
    postgres_user: str = "app"
    node_version: str = "20-alpine"
    with_redis: bool = False
    with_worker: bool = False

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        for attr in ("api_service_name", "web_service_name"):
            value = getattr(self, attr)
            if not isinstance(value, str) or not _NAME_RE.match(value):
                raise TemplateRenderError(
                    f"slot {attr!r} must match [a-z][a-z0-9-]*, got {value!r}"
                )
        for attr in ("api_port", "web_port", "postgres_port"):
            value = getattr(self, attr)
            if not isinstance(value, int) or value <= 0 or value > 65535:
                raise TemplateRenderError(
                    f"slot {attr!r} must be a port in 1..65535, got {value!r}"
                )
        for attr in ("postgres_version", "node_version", "postgres_db", "postgres_user"):
            value = getattr(self, attr)
            if not isinstance(value, str) or not value.strip():
                raise TemplateRenderError(f"slot {attr!r} must be non-empty str, got {value!r}")

    def to_mapping(self) -> dict[str, str]:
        """Return the ``{{ SLOT_NAME }}`` → string mapping used for substitution."""
        return {
            "API_SERVICE_NAME": self.api_service_name,
            "WEB_SERVICE_NAME": self.web_service_name,
            "API_PORT": str(self.api_port),
            "WEB_PORT": str(self.web_port),
            "POSTGRES_PORT": str(self.postgres_port),
            "POSTGRES_VERSION": self.postgres_version,
            "POSTGRES_DB": self.postgres_db,
            "POSTGRES_USER": self.postgres_user,
            "NODE_VERSION": self.node_version,
        }


@dataclass
class RenderedTemplate:
    """Output of :func:`render_template`.

    ``files`` keys are POSIX-style relative paths (e.g. ``apps/api/Dockerfile``);
    values are the fully-substituted UTF-8 text.
    """

    files: dict[Path, str] = field(default_factory=dict)
    template_name: str = ""
    template_version: str = ""
    slots_used: TemplateSlotValues = field(default_factory=TemplateSlotValues)


def _template_root(name: str) -> Traversable:
    try:
        root = resources.files(_TEMPLATES_PACKAGE).joinpath(name)
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        raise TemplateNotFoundError(f"template package missing: {name}") from exc
    if not root.is_dir():
        raise TemplateNotFoundError(f"no template named {name!r}")
    return root


def _load_manifest(root: Traversable) -> dict[str, Any]:
    manifest_file = root.joinpath("manifest.json")
    if not manifest_file.is_file():
        raise TemplateNotFoundError("template is missing manifest.json")
    return json.loads(manifest_file.read_text(encoding="utf-8"))


def _substitute(content: str, mapping: dict[str, str]) -> str:
    out = content
    for key, value in mapping.items():
        out = out.replace("{{ " + key + " }}", value)
    leftover = _PLACEHOLDER_RE.search(out)
    if leftover is not None:
        raise TemplateRenderError(
            f"unresolved placeholder {leftover.group(0)!r} after substitution"
        )
    return out


def _substitute_path(path: str, mapping: dict[str, str]) -> str:
    """Apply slot substitution to a path string (for {{ API_SERVICE_NAME }} in paths)."""
    return _substitute(path, mapping)


def _iter_template_files(
    root: Traversable,
    *,
    manifest: dict[str, Any],
    rel: str = "",
) -> list[tuple[str, str]]:
    """Walk ``root`` and yield ``(relative_posix_path, text_content)`` pairs.

    Skips ``manifest.json`` and Python package metadata (``__init__.py``,
    ``__pycache__``). Files listed in ``manifest['files']`` are the canonical
    contract; extra files in the tree are included but warned about to surface
    manifest drift.
    """
    declared = {p for p in manifest.get("files", [])}
    seen: list[tuple[str, str]] = []

    def walk(node: Traversable, prefix: str) -> None:
        for child in node.iterdir():
            name = child.name
            if name in {"manifest.json", "__init__.py", "__pycache__"}:
                continue
            child_rel = f"{prefix}{name}" if prefix == "" else f"{prefix}/{name}"
            if child.is_dir():
                walk(child, child_rel)
                continue
            # Dockerfile, .dockerignore, etc. — read as text.
            text = child.read_text(encoding="utf-8")
            seen.append((child_rel, text))

    walk(root, rel)

    if declared:
        found = {p for p, _ in seen}
        missing = declared - found
        if missing:
            raise TemplateRenderError(
                f"manifest declares files that are not present in the package: {sorted(missing)}"
            )
    return seen


def render_template(
    name: str,
    slots: TemplateSlotValues | None = None,
) -> RenderedTemplate:
    """Render a curated template by name.

    Parameters
    ----------
    name:
        Template directory name under ``agent_team_v15.templates`` (e.g.
        ``"pnpm_monorepo"``).
    slots:
        Optional override. ``None`` means use all defaults.

    Raises
    ------
    TemplateNotFoundError:
        The named template does not ship with the package.
    TemplateRenderError:
        Slot validation failed, or substitution left an unresolved ``{{ X }}``.
    """
    slot_values = slots if slots is not None else TemplateSlotValues()
    root = _template_root(name)
    manifest = _load_manifest(root)
    raw_files = _iter_template_files(root, manifest=manifest)
    mapping = slot_values.to_mapping()

    rendered_files: dict[Path, str] = {}
    for rel_path, content in raw_files:
        out_path = _substitute_path(rel_path, mapping)
        rendered_files[Path(out_path)] = _substitute(content, mapping)

    return RenderedTemplate(
        files=rendered_files,
        template_name=str(manifest.get("name", name)),
        template_version=str(manifest.get("version", "0.0.0")),
        slots_used=slot_values,
    )


def derive_slots_from_stack_contract(
    stack: StackContract | dict[str, Any] | None,
) -> TemplateSlotValues:
    """Pull slot values from a stack contract (dataclass or dict).

    Only the fields the contract actually carries are threaded through; any
    slot the contract doesn't influence keeps its default. ``api_port`` /
    ``web_port`` are sourced from ``stack.api_port`` / ``stack.web_port``
    when set; otherwise defaults apply.
    """
    defaults = TemplateSlotValues()
    if stack is None:
        return defaults
    if isinstance(stack, StackContract):
        data = stack.to_dict()
    elif isinstance(stack, dict):
        data = stack
    else:
        raise TemplateRenderError(
            f"stack must be StackContract|dict|None, got {type(stack).__name__}"
        )

    def _pick_port(key: str, fallback: int) -> int:
        value = data.get(key)
        if isinstance(value, int) and 0 < value <= 65535:
            return value
        return fallback

    return TemplateSlotValues(
        api_service_name=defaults.api_service_name,
        web_service_name=defaults.web_service_name,
        api_port=_pick_port("api_port", defaults.api_port),
        web_port=_pick_port("web_port", defaults.web_port),
        postgres_port=_pick_port("postgres_port", defaults.postgres_port),
        postgres_version=defaults.postgres_version,
        postgres_db=defaults.postgres_db,
        postgres_user=defaults.postgres_user,
        node_version=defaults.node_version,
        with_redis=bool(data.get("with_redis", defaults.with_redis)),
        with_worker=bool(data.get("with_worker", defaults.with_worker)),
    )


def drop_template(
    rendered: RenderedTemplate,
    target_dir: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Write rendered files into ``target_dir``.

    Returns the list of ABSOLUTE paths actually written. When ``overwrite``
    is False, existing files are skipped (and NOT returned), leaving
    scaffold-owned emissions (e.g. ``docker-compose.yml``,
    ``apps/web/Dockerfile``) untouched.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for rel_path, content in rendered.files.items():
        if rel_path.is_absolute():
            raise TemplateRenderError(
                f"rendered template files must be relative paths, got {rel_path}"
            )
        out_path = target_dir / rel_path
        if out_path.exists() and not overwrite:
            logger.debug("drop_template: skipping existing %s", out_path)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        written.append(out_path)
    return written


def stack_matches_template(
    stack: StackContract | dict[str, Any] | None,
    template_name: str,
) -> bool:
    """Return True iff the given stack is compatible with the named template.

    Compatibility is read from the template's ``manifest.json`` ->
    ``compatible_stacks``: each entry is a dict of stack_contract fields
    that must match (case-insensitive). Any entry matching means compatible.
    """
    if stack is None:
        return False
    if isinstance(stack, StackContract):
        data = stack.to_dict()
    elif isinstance(stack, dict):
        data = stack
    else:
        return False

    try:
        root = _template_root(template_name)
        manifest = _load_manifest(root)
    except TemplateNotFoundError:
        return False

    compatible = manifest.get("compatible_stacks", [])
    if not compatible:
        return False

    def _norm(value: Any) -> str:
        return str(value or "").strip().lower()

    for entry in compatible:
        if not isinstance(entry, dict):
            continue
        ok = True
        for key, expected in entry.items():
            if _norm(data.get(key)) != _norm(expected):
                ok = False
                break
        if ok:
            return True
    return False


__all__ = [
    "RenderedTemplate",
    "TemplateNotFoundError",
    "TemplateRenderError",
    "TemplateSlotValues",
    "derive_slots_from_stack_contract",
    "drop_template",
    "render_template",
    "stack_matches_template",
]
