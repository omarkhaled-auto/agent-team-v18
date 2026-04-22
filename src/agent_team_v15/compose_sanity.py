"""Phase 6.0 — Compose Sanity Gate.

Validates that every `COPY`/`ADD` source in each service's Dockerfile resolves
inside its declared `build.context`. The Codex-generated compose setups tend
to place the Dockerfile at `apps/web/Dockerfile` with `build.context:
./apps/web` while the Dockerfile itself does `COPY ../packages/shared/...` —
which escapes the narrow context and kills every downstream build with a
``not found`` cache error.

The gate runs BEFORE the first `docker compose build` so we fail-fast with a
structured violation or (when ``autorepair=True``) rewrite the compose
`build.context`/`build.dockerfile` pair plus the offending ``COPY``/``ADD``
source paths to a widened context (least-common-ancestor of the current
context and every COPY source's author-intended location).

The Dockerfile tokenizer is hand-rolled so we can track heredoc delimiters
and multi-stage `FROM ... AS` aliases without introducing a new PyPI
dependency; ``dockerfile-parse`` historically had weak heredoc support and
``dockerfile-ast`` is TypeScript-only.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CopyInstruction:
    """A single ``COPY`` or ``ADD`` instruction from a Dockerfile."""

    instruction: str              # "COPY" or "ADD"
    sources: tuple[str, ...]      # source tokens exactly as written
    dest: str                     # destination token
    flags: tuple[str, ...]        # --chown=..., --chmod=..., etc. (raw)
    from_stage: bool              # True if --from=<alias-or-image> is set
    physical_start: int           # 0-indexed first physical line
    physical_end: int             # 0-indexed last physical line (inclusive)


@dataclass(frozen=True)
class Violation:
    """A compose build-context validation failure."""

    service: str
    source: str
    resolved_path: Path
    reason: str


class ComposeSanityError(RuntimeError):
    """Raised when validation fails and autorepair cannot resolve."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = list(violations)
        parts = [
            f"  - service={v.service!s} source={v.source!r} "
            f"reason={v.reason} resolved={v.resolved_path}"
            for v in violations
        ]
        super().__init__(
            "Compose build-context sanity check failed:\n" + "\n".join(parts)
        )


# ---------------------------------------------------------------------------
# Dockerfile tokenizer
# ---------------------------------------------------------------------------

# <<EOF, <<-EOF, <<"EOF", <<'EOF'. Captures dash, quote, name.
_HEREDOC_RE = re.compile(r"<<\s*(-?)\s*([\"\']?)([A-Za-z_][A-Za-z0-9_]*)\2")
# FROM [--flag=...] image[:tag] [AS alias]  (case-insensitive)
_FROM_AS_RE = re.compile(r"\bAS\b\s+([A-Za-z_][\w.-]*)", re.IGNORECASE)


def parse_dockerfile(path: Path) -> list[CopyInstruction]:
    """Tokenize a Dockerfile and return every COPY/ADD instruction.

    Handles:
        - Line continuations (``\\`` at end of physical line)
        - Heredocs (``<<EOF``, ``<<-EOF``, ``<<"EOF"``, ``<<'EOF'``) — bodies
          are skipped so a ``COPY`` literal inside a heredoc is not flagged.
        - Multi-stage ``FROM ... AS <alias>`` — ``--from=<alias>`` targets are
          marked ``from_stage=True`` so callers can skip them.
        - ``COPY --from=<image>`` (also ``from_stage=True``).
        - ``COPY [flags] src... dst`` with any number of source tokens.
        - Block comments / blank lines.

    Does NOT handle:
        - The JSON-array form ``COPY ["src", "dst"]``. Treated as a single
          source token starting with ``[`` which will fail "not found" —
          acceptable because the generator never emits JSON-array COPY.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    physical_lines = text.splitlines()
    n = len(physical_lines)

    stages: set[str] = set()
    instructions: list[CopyInstruction] = []
    heredoc_stack: list[tuple[str, bool]] = []  # (delimiter, strip_tabs)

    i = 0
    while i < n:
        # Consume heredoc body first.
        if heredoc_stack:
            delim, strip_tabs = heredoc_stack[-1]
            line = physical_lines[i]
            check = line.lstrip("\t") if strip_tabs else line
            if check.strip() == delim:
                heredoc_stack.pop()
            i += 1
            continue

        # Collect a logical line, honoring ``\`` continuations.
        logical_start = i
        joined_parts: list[str] = []
        while i < n:
            pline = physical_lines[i]
            rstripped = pline.rstrip()
            if rstripped.endswith("\\") and not rstripped.endswith("\\\\"):
                joined_parts.append(rstripped[:-1])
                i += 1
                continue
            joined_parts.append(pline)
            i += 1
            break
        logical_end = i - 1
        logical_line = " ".join(part.strip() for part in joined_parts).strip()

        if not logical_line or logical_line.startswith("#"):
            continue

        # Detect heredoc openings in this logical line (may be multiple).
        heredoc_matches = _HEREDOC_RE.findall(logical_line)
        for dash, _quote, name in heredoc_matches:
            heredoc_stack.append((name, bool(dash)))

        parts = logical_line.split(None, 1)
        if not parts:
            continue
        instr = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ""

        if instr == "FROM":
            match = _FROM_AS_RE.search(rest)
            if match:
                stages.add(match.group(1))
            continue

        if instr not in ("COPY", "ADD"):
            continue

        # Heredoc COPY/ADD (``COPY <<EOF /path``) creates a file from the
        # heredoc body — no host-side sources to validate.
        if heredoc_matches:
            continue

        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError:
            # Unclosed quote etc. — fall back to whitespace split.
            tokens = rest.split()

        flags: list[str] = []
        from_stage = False
        positional: list[str] = []
        for tok in tokens:
            if tok.startswith("--"):
                flags.append(tok)
                if tok.startswith("--from="):
                    from_stage = True
            else:
                positional.append(tok)

        if len(positional) < 2:
            # Malformed; skip without crashing.
            continue

        instructions.append(
            CopyInstruction(
                instruction=instr,
                sources=tuple(positional[:-1]),
                dest=positional[-1],
                flags=tuple(flags),
                from_stage=from_stage,
                physical_start=logical_start,
                physical_end=logical_end,
            )
        )

    return instructions


# ---------------------------------------------------------------------------
# Least-common-ancestor
# ---------------------------------------------------------------------------

def lca(paths: list[Path]) -> Path:
    """Return the longest common directory prefix of ``paths``.

    Paths are resolved to absolute before comparison. Raises ``ValueError``
    if no common ancestor exists (e.g. different Windows drives).
    """
    if not paths:
        raise ValueError("lca requires at least one path")
    abs_parts = [Path(os.path.abspath(str(p))).parts for p in paths]
    common: list[str] = []
    for group in zip(*abs_parts):
        first = group[0]
        if all(seg == first for seg in group):
            common.append(first)
        else:
            break
    if not common:
        raise ValueError(f"no common ancestor for paths: {paths}")
    result = Path(*common)
    # If every input was the same file, the LCA is that file — back off to
    # the containing directory so callers always get a directory.
    if result.exists() and result.is_file():
        return result.parent
    return result


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_GLOB_CHARS = set("*?[")


def _has_glob(src: str) -> bool:
    return any(c in src for c in _GLOB_CHARS)


def _normalize_no_glob(base: Path, src: str) -> Path:
    """Join ``base/src`` and collapse ``..``/``.`` without expanding globs.

    ``Path.resolve()`` doesn't expand glob metacharacters, but it does
    resolve symlinks we don't care about. ``os.path.normpath`` keeps the
    semantics pure-lexical which is what validation needs.
    """
    joined = os.path.join(str(base), src)
    return Path(os.path.normpath(joined))


def _path_escapes(context: Path, path: Path) -> bool:
    """True if ``path`` is NOT within ``context`` (lexical check)."""
    try:
        path.relative_to(context)
        return False
    except ValueError:
        return True


def _source_exists(abs_path: Path) -> bool:
    """Existence check that understands glob metacharacters."""
    s = str(abs_path)
    if _has_glob(s):
        parent = abs_path.parent
        pattern = abs_path.name
        try:
            return any(True for _ in parent.glob(pattern))
        except OSError:
            return False
    return abs_path.exists()


# ---------------------------------------------------------------------------
# YAML load + override merge
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ComposeSanityError([
            Violation("(compose)", str(path), path, f"read failed: {exc}")
        ]) from exc
    data = yaml.safe_load(raw)
    return data if isinstance(data, dict) else {}


def _deep_merge(base: Any, override: Any) -> Any:
    """Compose-spec merge semantics for service configs.

    Mappings merge key-wise (override wins on leaf collisions); anything
    else — scalars, lists, or type mismatches — is replaced wholesale by
    the override value (per the compose multi-file spec).
    """
    if isinstance(base, dict) and isinstance(override, dict):
        out: dict[str, Any] = dict(base)
        for k, v in override.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    return override


def _find_override(compose_file: Path) -> Path | None:
    """Locate a sibling override file per compose-spec conventions."""
    parent = compose_file.parent
    stem = compose_file.stem  # e.g. "docker-compose" or "compose"
    candidates = [
        parent / f"{stem}.override.yml",
        parent / f"{stem}.override.yaml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _normalize_build(build: Any) -> dict[str, Any] | None:
    """Canonicalize a service's ``build`` block to dict form."""
    if isinstance(build, str):
        return {"context": build, "dockerfile": "Dockerfile"}
    if isinstance(build, dict):
        out = dict(build)
        out.setdefault("context", ".")
        out.setdefault("dockerfile", "Dockerfile")
        return out
    return None


# ---------------------------------------------------------------------------
# Dockerfile rewrite
# ---------------------------------------------------------------------------

def _rebuild_instruction_line(
    ins: CopyInstruction,
    new_sources: tuple[str, ...],
) -> str:
    """Reconstruct a single-line COPY/ADD. Line continuations are collapsed."""
    parts: list[str] = [ins.instruction]
    parts.extend(ins.flags)
    parts.extend(new_sources)
    parts.append(ins.dest)
    return " ".join(parts)


def _rewrite_dockerfile(
    dockerfile_abs: Path,
    rewrites: list[tuple[CopyInstruction, tuple[str, ...]]],
) -> None:
    """Replace each rewritten instruction's physical-line range inline."""
    original = dockerfile_abs.read_text(encoding="utf-8", errors="replace")
    lines = original.splitlines()
    # Apply bottom-up so earlier line indexes remain stable.
    ordered = sorted(rewrites, key=lambda pair: pair[0].physical_start, reverse=True)
    for ins, new_sources in ordered:
        new_line = _rebuild_instruction_line(ins, new_sources)
        lines[ins.physical_start: ins.physical_end + 1] = [new_line]
    # Preserve a trailing newline if the original had one.
    suffix = "\n" if original.endswith("\n") else ""
    dockerfile_abs.write_text("\n".join(lines) + suffix, encoding="utf-8")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Per-service planning
# ---------------------------------------------------------------------------

@dataclass
class _ServicePlan:
    """Internal scratch state for a single compose service."""

    service: str
    context_abs: Path
    dockerfile_abs: Path
    instructions: list[CopyInstruction]
    violations: list[Violation] = field(default_factory=list)
    # Absolute intended-target of every COPY source (author intent).
    intended_abs: list[Path] = field(default_factory=list)
    # Map (instruction_index, source_index) -> intended absolute path.
    intended_map: dict[tuple[int, int], Path] = field(default_factory=dict)


def _resolve_source_intent(
    context_abs: Path,
    dockerfile_dir: Path,
    src: str,
    compose_dir: Path,
) -> tuple[Path, bool]:
    """Resolve a COPY source to its author-intended absolute path.

    Three-tier strategy:
        1. Docker-spec interpretation: ``src`` relative to ``build.context``.
           This is the only legal interpretation per the Docker reference,
           so if it exists we return it (and never mark it as escaping).
        2. Dockerfile-directory interpretation: catches the common
           ``COPY ../packages/...`` anti-pattern where the author thinks of
           sources as relative to the Dockerfile rather than the context.
        3. Upward search bounded by ``compose_dir``: covers the pnpm /
           monorepo anti-pattern where the Dockerfile expects sources at
           the repo root (e.g. ``COPY pnpm-workspace.yaml``) but the
           declared context is narrower. We strip leading ``../`` from
           ``src`` and walk from the Dockerfile directory up to the
           compose-file directory looking for the first hit.

    When nothing matches, the context-relative interpretation is returned
    so the caller can surface a ``not found`` / ``escapes context``
    violation without fabricating a bogus target.
    """
    context_abs = Path(context_abs)
    dockerfile_dir = Path(dockerfile_dir)
    compose_dir = Path(compose_dir).resolve()

    # 1. Docker-spec interpretation.
    context_rel = _normalize_no_glob(context_abs, src)
    context_escapes = _path_escapes(context_abs, context_rel)
    if not context_escapes and _source_exists(context_rel):
        return context_rel, False

    # 2. Dockerfile-directory interpretation.
    dockerfile_rel = _normalize_no_glob(dockerfile_dir, src)
    if dockerfile_rel != context_rel and _source_exists(dockerfile_rel):
        return dockerfile_rel, _path_escapes(context_abs, dockerfile_rel)

    # 3. Upward search from Dockerfile dir for the source's "tail".
    tail = src.replace("\\", "/").lstrip("/")
    while tail.startswith("../"):
        tail = tail[3:]
    if tail.startswith("./"):
        tail = tail[2:]
    if tail:
        current = dockerfile_dir.resolve()
        for _ in range(32):  # defensive depth cap
            candidate = _normalize_no_glob(current, tail)
            if _source_exists(candidate):
                return candidate, _path_escapes(context_abs, candidate)
            if current == compose_dir:
                break
            parent = current.parent
            if parent == current:
                break
            # Bound at compose_dir — don't escape the project tree.
            try:
                parent.relative_to(compose_dir)
            except ValueError:
                break
            current = parent

    return context_rel, context_escapes


def _plan_service(
    service: str,
    build: dict[str, Any],
    compose_dir: Path,
    project_root: Path,
) -> _ServicePlan | None:
    """Build a _ServicePlan for one compose service with a ``build:`` block."""
    context_str = str(build.get("context", "."))
    dockerfile_rel = str(build.get("dockerfile", "Dockerfile"))
    context_abs = (compose_dir / context_str).resolve()
    dockerfile_abs = (context_abs / dockerfile_rel).resolve()

    if not dockerfile_abs.is_file():
        plan = _ServicePlan(
            service=service,
            context_abs=context_abs,
            dockerfile_abs=dockerfile_abs,
            instructions=[],
        )
        plan.violations.append(
            Violation(
                service=service,
                source=dockerfile_rel,
                resolved_path=dockerfile_abs,
                reason="Dockerfile not found",
            )
        )
        return plan

    instructions = parse_dockerfile(dockerfile_abs)
    plan = _ServicePlan(
        service=service,
        context_abs=context_abs,
        dockerfile_abs=dockerfile_abs,
        instructions=instructions,
    )

    dockerfile_dir = dockerfile_abs.parent
    # Always seed LCA with current context + dockerfile path so the result
    # never widens BEYOND what's already required.
    plan.intended_abs.extend([context_abs, dockerfile_abs])

    for ins_idx, ins in enumerate(instructions):
        if ins.from_stage:
            continue
        for src_idx, src in enumerate(ins.sources):
            abs_path, escapes = _resolve_source_intent(
                context_abs, dockerfile_dir, src, project_root
            )
            plan.intended_abs.append(abs_path)
            plan.intended_map[(ins_idx, src_idx)] = abs_path

            exists = _source_exists(abs_path)
            if escapes:
                plan.violations.append(
                    Violation(
                        service=service,
                        source=src,
                        resolved_path=abs_path,
                        reason="escapes context",
                    )
                )
            elif not exists:
                plan.violations.append(
                    Violation(
                        service=service,
                        source=src,
                        resolved_path=abs_path,
                        reason="not found in context",
                    )
                )

    return plan


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_compose_build_context(
    compose_file: Path,
    *,
    autorepair: bool = True,
    project_root: Path | None = None,
) -> list[Violation]:
    """Validate every service's build context; autorepair if enabled.

    Behavior
    --------
    * Reads ``compose_file`` and (if present) a sibling
      ``docker-compose.override.yml``/``compose.override.yml``. Merges via
      compose-spec rules so validation reflects effective config.
    * For each service with a ``build:`` block:
        - Normalizes short-form (``build: ./foo``) to dict form.
        - Tokenizes the Dockerfile and validates every COPY/ADD source.
        - Flags sources that either escape the declared context or don't
          exist on disk.
    * Sources behind ``--from=<stage>`` (or ``--from=<image>``) are ignored.
    * On violations with ``autorepair=True``: compute
      ``new_context = lca(current_context, *intended_source_paths)``,
      rewrite ``build.context``/``build.dockerfile`` in the compose file,
      rewrite offending COPY/ADD source tokens in the Dockerfile so they
      resolve from the new context, then recurse once with
      ``autorepair=False``. If violations remain, raise
      ``ComposeSanityError``.
    * With ``autorepair=False``, non-empty violations raise
      ``ComposeSanityError`` directly. (The opt-out contract: "detect +
      raise without rewriting.")

    Returns
    -------
    list[Violation]
        Empty on success. Non-empty is never returned from this function;
        the only reachable non-empty-returning path would be the ``autorepair=True``
        post-repair recursion when recursion itself succeeds — which returns
        ``[]``.
    """
    compose_file = Path(compose_file).resolve()
    compose_dir = Path(project_root).resolve() if project_root else compose_file.parent

    base = _load_yaml(compose_file)
    override_path = _find_override(compose_file)
    if override_path is not None:
        override = _load_yaml(override_path)
        effective = _deep_merge(base, override)
    else:
        effective = base

    services = effective.get("services") or {}
    if not isinstance(services, dict):
        return []

    plans: list[_ServicePlan] = []
    for svc_name, svc_cfg in services.items():
        if not isinstance(svc_cfg, dict):
            continue
        if "build" not in svc_cfg:
            continue
        build = _normalize_build(svc_cfg["build"])
        if build is None:
            continue
        plan = _plan_service(svc_name, build, compose_dir, compose_dir)
        if plan is not None:
            plans.append(plan)

    failing = [p for p in plans if p.violations]
    if not failing:
        return []

    if not autorepair:
        all_violations = [v for p in failing for v in p.violations]
        raise ComposeSanityError(all_violations)

    # Autorepair path — rewrite compose + Dockerfiles and recurse once.
    _apply_autorepair(compose_file, base, failing, compose_dir)

    # Recurse with autorepair=False — if STILL failing, ComposeSanityError
    # propagates; otherwise we return [].
    return validate_compose_build_context(
        compose_file, autorepair=False, project_root=compose_dir
    )


def _apply_autorepair(
    compose_file: Path,
    base: dict[str, Any],
    failing: list[_ServicePlan],
    compose_dir: Path,
) -> None:
    """Widen each failing service's context and rewrite sources."""
    base_services = base.setdefault("services", {}) if isinstance(base, dict) else {}
    if not isinstance(base_services, dict):
        base["services"] = {}
        base_services = base["services"]

    diff_log: list[str] = []

    for plan in failing:
        if not plan.intended_abs:
            continue
        new_context_abs = lca(plan.intended_abs)
        try:
            new_dockerfile_rel = plan.dockerfile_abs.relative_to(new_context_abs)
        except ValueError:
            # Dockerfile somehow not under new context — give up on this
            # service so the post-repair recursion surfaces it cleanly.
            continue

        # Rewrite each COPY/ADD source to be relative to new_context_abs.
        rewrites: list[tuple[CopyInstruction, tuple[str, ...]]] = []
        for ins_idx, ins in enumerate(plan.instructions):
            if ins.from_stage:
                continue
            new_srcs: list[str] = []
            changed = False
            for src_idx, src in enumerate(ins.sources):
                intended = plan.intended_map.get((ins_idx, src_idx))
                if intended is None:
                    new_srcs.append(src)
                    continue
                try:
                    rel = intended.relative_to(new_context_abs)
                    rel_s = rel.as_posix()
                    new_srcs.append(rel_s)
                    if rel_s != src:
                        changed = True
                except ValueError:
                    new_srcs.append(src)
            if changed:
                rewrites.append((ins, tuple(new_srcs)))

        if rewrites:
            _rewrite_dockerfile(plan.dockerfile_abs, rewrites)

        # Update the base compose file's build block for this service.
        svc_cfg = base_services.get(plan.service)
        if not isinstance(svc_cfg, dict):
            base_services[plan.service] = {}
            svc_cfg = base_services[plan.service]

        new_context_rel = os.path.relpath(new_context_abs, compose_dir).replace("\\", "/")
        if new_context_rel == "":
            new_context_rel = "."
        new_dockerfile_rel_s = new_dockerfile_rel.as_posix()

        build = svc_cfg.get("build")
        if isinstance(build, dict):
            build["context"] = new_context_rel
            build["dockerfile"] = new_dockerfile_rel_s
        else:
            # string or missing — canonicalize to dict form.
            svc_cfg["build"] = {
                "context": new_context_rel,
                "dockerfile": new_dockerfile_rel_s,
            }

        diff_log.append(
            f"service={plan.service} context -> {new_context_rel} "
            f"dockerfile -> {new_dockerfile_rel_s} "
            f"(violations={len(plan.violations)}, "
            f"source-rewrites={len(rewrites)})"
        )

    _write_yaml(compose_file, base)
    _log_repair(compose_file, diff_log)


def _log_repair(compose_file: Path, entries: list[str]) -> None:
    """Append a repair summary to ``.agent-team/runtime_verification.log``.

    Silently best-effort — if the log dir can't be created we still want the
    repair to go through.
    """
    if not entries:
        return
    # compose_file is usually inside the project root; its parent is the root.
    project_root = compose_file.parent
    log_dir = project_root / ".agent-team"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "runtime_verification.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("[compose-sanity] autorepair applied:\n")
            for line in entries:
                fh.write(f"  {line}\n")
    except OSError:
        logger.debug("compose-sanity: could not write repair log", exc_info=True)
    # Also surface at INFO for operators watching the run.
    for line in entries:
        logger.info("compose-sanity: %s", line)


__all__ = [
    "CopyInstruction",
    "Violation",
    "ComposeSanityError",
    "parse_dockerfile",
    "lca",
    "validate_compose_build_context",
]
