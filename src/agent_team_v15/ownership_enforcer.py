"""Ownership enforcement — Phase H1a Item 4.

Three structural checks that, together, close the smoke #11 failure
where Wave A wrote ``docker-compose.yml`` / ``apps/api/.env.example``
with milestone-specific values, the scaffolder silently skipped
re-writing via ``_write_if_missing`` (:740-741), and the probe then hit
a port the runtime never bound.

Check A — Template-content fingerprinting (at scaffold-completion):
    Hash the scaffolder's template output *and* the on-disk content for
    each h1a-covered file. If they differ, emit
    ``OWNERSHIP-DRIFT-001`` HIGH. Persist both hashes into
    ``.agent-team/SCAFFOLD_FINGERPRINT.json`` so post-wave re-checks can
    compare to ``template_hash`` (not ``on_disk_hash``) — otherwise Wave
    A's already-shipped drift would be baseline.

Check C — Wave A forbidden-writes (at Wave A completion):
    Cross-reference Wave A's ``files_created`` against
    ``docs/SCAFFOLD_OWNERSHIP.md`` ``owner: scaffold`` rows. Any
    intersection is a ``OWNERSHIP-WAVE-A-FORBIDDEN-001`` HIGH finding.
    Runs BEFORE scaffold, catching the failure mode at the exact moment
    it happens — not after the scaffolder silently skips.

Post-wave re-check (after each non-A wave):
    Re-hash the h1a-covered files and compare against ``template_hash``
    from the fingerprint file. Drift → ``OWNERSHIP-DRIFT-001`` HIGH
    with the wave name attached.

Scope (h1a-generic-ready):
    Today we cover compose + 3 .env.example files. The constant
    :data:`H1A_ENFORCED_PATHS` and :data:`_TEMPLATE_RESOLVERS` are the
    only surface to extend to the full 44-file scaffold-owned set later
    — expanding is a config change, not a code change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scope — the h1a-covered paths
# ---------------------------------------------------------------------------

# The four files whose template content we own end-to-end for h1a. Each
# entry is a relative path under the project root. Expanding to the full
# 44-file scaffold-owned set is a matter of growing this list and
# populating :data:`_TEMPLATE_RESOLVERS`.
H1A_ENFORCED_PATHS: tuple[str, ...] = (
    "docker-compose.yml",
    ".env.example",
    "apps/api/.env.example",
    "apps/web/.env.example",
)


def _resolve_compose_template(cfg: Any = None) -> Optional[str]:
    # compose template is not cfg-sensitive today; signature matches the
    # resolver protocol so all four resolvers are uniform.
    del cfg
    try:
        from .scaffold_runner import _docker_compose_template

        return _docker_compose_template()
    except Exception as exc:  # pragma: no cover — defensive
        _logger.warning("ownership: failed to resolve compose template: %s", exc)
        return None


def _resolve_root_env_example_template(cfg: Any = None) -> Optional[str]:
    try:
        from .scaffold_runner import _env_example_template  # type: ignore[attr-defined]

        return _env_example_template(cfg) if cfg is not None else _env_example_template()
    except Exception:
        return None


def _resolve_api_env_example_template(cfg: Any = None) -> Optional[str]:
    try:
        from .scaffold_runner import _api_env_example_template  # type: ignore[attr-defined]

        return (
            _api_env_example_template(cfg)
            if cfg is not None
            else _api_env_example_template()
        )
    except Exception:
        return None


def _resolve_web_env_example_template(cfg: Any = None) -> Optional[str]:
    # Web env template has no cfg-sensitive signature today.
    del cfg
    try:
        from .scaffold_runner import _web_env_example_template  # type: ignore[attr-defined]

        return _web_env_example_template()
    except Exception:
        return None


# Mapping from h1a-enforced path → resolver callable. Resolvers accept an
# optional ScaffoldConfig (duck-typed as ``Any`` to avoid an import cycle
# with scaffold_runner at module load). When the caller has the resolved
# cfg (wave_executor post-reconciliation), it MUST pass it through so
# cfg-sensitive templates (PORT, DB credentials) hash to the same bytes
# the scaffolder wrote on disk. Passing ``None`` / omitting uses the
# scaffolder's DEFAULT_SCAFFOLD_CONFIG — correct only when no
# reconciliation ran.
_TEMPLATE_RESOLVERS: dict[str, Callable[[Any], Optional[str]]] = {
    "docker-compose.yml": _resolve_compose_template,
    ".env.example": _resolve_root_env_example_template,
    "apps/api/.env.example": _resolve_api_env_example_template,
    "apps/web/.env.example": _resolve_web_env_example_template,
}


FINGERPRINT_PATH = Path(".agent-team") / "SCAFFOLD_FINGERPRINT.json"


# ---------------------------------------------------------------------------
# Finding shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    file: str
    message: str
    blocks_wave: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None


def _first_n_lines_diff(template: str, on_disk: str, n: int = 5) -> str:
    """Return a short ``template vs on-disk`` head-line diff for messages."""

    t_head = template.splitlines()[:n]
    d_head = on_disk.splitlines()[:n]
    parts = []
    for idx in range(max(len(t_head), len(d_head))):
        t_line = t_head[idx] if idx < len(t_head) else "<EOF>"
        d_line = d_head[idx] if idx < len(d_head) else "<EOF>"
        if t_line == d_line:
            continue
        parts.append(f"L{idx + 1}: template={t_line!r} on_disk={d_line!r}")
    return " | ".join(parts) if parts else "(heads equal — drift is past line 5)"


def _fingerprint_path(cwd: Path) -> Path:
    return cwd / FINGERPRINT_PATH


def _load_fingerprint(cwd: Path) -> dict[str, Any]:
    fp_path = _fingerprint_path(cwd)
    try:
        raw = fp_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_fingerprint(cwd: Path, data: dict[str, Any]) -> None:
    fp_path = _fingerprint_path(cwd)
    try:
        fp_path.parent.mkdir(parents=True, exist_ok=True)
        fp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        _logger.warning(
            "ownership: failed to persist %s: %s — proceeding without fingerprint",
            fp_path,
            exc,
        )


def _load_scaffold_owned_paths(
    cwd: Path,
    *,
    config: object | None = None,
) -> Optional[set[str]]:
    """Return the set of ``owner: scaffold`` paths from ownership contract.

    Returns ``None`` when the contract is missing or unparseable — the
    caller treats this as "Check C skipped, emit one WARN".
    """

    try:
        from .scaffold_runner import (
            _build_missing_ownership_policy_error,
            _ownership_policy_required,
            load_ownership_contract_from_workspace,
        )
    except Exception as exc:  # pragma: no cover — defensive
        _logger.warning("ownership: scaffold_runner import failed: %s", exc)
        return None

    try:
        contract = load_ownership_contract_from_workspace(cwd)
    except FileNotFoundError:
        if _ownership_policy_required(config):
            raise _build_missing_ownership_policy_error(cwd)
        _logger.warning(
            "ownership: SCAFFOLD_OWNERSHIP.md not found; Check C skipped",
        )
        return None
    except Exception as exc:
        _logger.warning(
            "ownership: SCAFFOLD_OWNERSHIP.md parse failed: %s; Check C skipped",
            exc,
        )
        return None

    return {row.path for row in contract.files if row.owner == "scaffold"}


def get_scaffold_owned_paths_for_wave_a_prompt(
    cwd: str | Path | None = None,
) -> list[str]:
    """Return sorted scaffold-owned paths for Wave A prompt injection.

    Prompt construction should remain best-effort: if the ownership
    contract is unavailable, omit the block instead of breaking the
    prompt builder.
    """

    owned = _load_scaffold_owned_paths(Path(cwd) if cwd is not None else Path.cwd())
    if not owned:
        return []
    return sorted(_normalize_rel(path) for path in owned)


def _normalize_rel(path: str) -> str:
    """Normalize a file path for ownership comparisons (forward slashes, no ./)."""

    p = str(path).replace("\\", "/")
    # Strip a single leading ``./`` — ``lstrip("./")`` is wrong because
    # it strips ANY combination of '.' and '/' chars, eating the leading
    # dot on ``.env.example`` (turning it into ``env.example``).
    while p.startswith("./"):
        p = p[2:]
    return p


# ---------------------------------------------------------------------------
# Check A — Template-content fingerprinting (scaffold-completion)
# ---------------------------------------------------------------------------


def check_template_drift_and_fingerprint(
    cwd: str | Path,
    scaffold_cfg: Any = None,
) -> list[Finding]:
    """Hash scaffolder templates + on-disk content; persist fingerprint.

    Emits ``OWNERSHIP-DRIFT-001`` per h1a-covered file whose on-disk
    content does NOT match the scaffolder's canonical template. Persists
    both the template hash and the on-disk hash to
    ``.agent-team/SCAFFOLD_FINGERPRINT.json`` so post-wave re-checks
    compare against the template hash baseline (the one Wave A *should*
    have written), not the on-disk hash (what Wave A actually wrote —
    which could itself be drift).

    ``scaffold_cfg`` is the :class:`ScaffoldConfig` the scaffolder
    actually used (post-N-12 reconciliation). Cfg-sensitive templates
    (``.env.example`` / ``apps/api/.env.example``, which interpolate
    ``cfg.port``) MUST be hashed with the same cfg the scaffolder wrote
    with, or Check A emits false-positive drift. ``None`` falls back to
    the scaffolder's DEFAULT_SCAFFOLD_CONFIG — correct only when no
    reconciliation ran.
    """

    root = Path(cwd)
    findings: list[Finding] = []
    data: dict[str, Any] = {}

    for rel in H1A_ENFORCED_PATHS:
        resolver = _TEMPLATE_RESOLVERS.get(rel)
        template = resolver(scaffold_cfg) if resolver is not None else None
        entry: dict[str, Any] = {
            "template_hash": None,
            "on_disk_hash": None,
        }
        if template is None:
            # No resolvable template — record empty entry and continue.
            data[rel] = entry
            continue
        entry["template_hash"] = _hash_text(template)

        abs_path = root / rel
        on_disk = _read_text_safe(abs_path)
        if on_disk is None:
            # File missing on disk — not a drift finding here (upstream
            # scaffold verifier MISSING check owns that surface).
            data[rel] = entry
            continue
        entry["on_disk_hash"] = _hash_text(on_disk)
        data[rel] = entry

        if entry["template_hash"] != entry["on_disk_hash"]:
            head_diff = _first_n_lines_diff(template, on_disk)
            findings.append(
                Finding(
                    code="OWNERSHIP-DRIFT-001",
                    severity="HIGH",
                    file=rel,
                    message=(
                        f"Scaffold-owned file drift detected at scaffold "
                        f"completion. file={rel} "
                        f"template_hash={entry['template_hash']} "
                        f"on_disk_hash={entry['on_disk_hash']} "
                        f"head_diff=[{head_diff}]"
                    ),
                )
            )

    _save_fingerprint(root, data)
    return findings


# ---------------------------------------------------------------------------
# Check C — Wave A forbidden-writes
# ---------------------------------------------------------------------------


def check_wave_a_forbidden_writes(
    cwd: str | Path,
    wave_a_files: Iterable[str],
    milestone_id: str = "",
    *,
    config: object | None = None,
) -> list[Finding]:
    """Emit a finding per Wave A write that targets a scaffold-owned path.

    ``wave_a_files`` is the union of ``files_created`` and
    ``files_modified`` from the Wave A :class:`WaveResult`. Comparing
    against ``owner: scaffold`` rows catches the exact failure mode that
    makes ``_write_if_missing`` (:740-741) silently skip the scaffolder:
    Wave A got there first.
    """

    owned = _load_scaffold_owned_paths(Path(cwd), config=config)
    if owned is None:
        return []

    v18 = getattr(config, "v18", None) if config is not None else None
    if isinstance(v18, dict):
        enforcement_on = bool(
            v18.get("wave_a_ownership_enforcement_enabled", False)
        )
    else:
        enforcement_on = bool(
            getattr(v18, "wave_a_ownership_enforcement_enabled", False)
        )
    findings: list[Finding] = []
    seen: set[str] = set()
    owned_norm = {_normalize_rel(p) for p in owned}
    for raw in wave_a_files:
        rel = _normalize_rel(raw)
        if rel in seen:
            continue
        seen.add(rel)
        if rel in owned_norm:
            findings.append(
                Finding(
                    code="OWNERSHIP-WAVE-A-FORBIDDEN-001",
                    severity="HIGH",
                    file=rel,
                    message=(
                        f"Wave A wrote scaffold-owned file {rel} "
                        f"(milestone={milestone_id or '<unknown>'}). The "
                        "scaffolder's _write_if_missing check will "
                        "silently skip this path at scaffold time."
                    ),
                    blocks_wave=enforcement_on,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Post-wave re-check
# ---------------------------------------------------------------------------


def check_post_wave_drift(
    wave_name: str,
    cwd: str | Path,
    scaffold_cfg: Any = None,
) -> list[Finding]:
    """Re-hash h1a-covered files; compare to ``template_hash`` baseline.

    Skipped silently for Wave A (Check C already covers Wave A's write
    surface; running a hash-compare here would double-count). Skipped
    when the fingerprint file is missing (no baseline to compare) or has
    no template hash entry for a given file.

    ``scaffold_cfg`` is only used to pretty-print the ``head_diff`` in
    the emitted message (so the diff lines match what the scaffolder
    actually wrote). The comparison itself uses the ``template_hash``
    persisted by Check A, which was already computed with the correct
    cfg — the baseline is stable regardless of what's passed here.
    """

    if str(wave_name).upper() == "A":
        return []

    root = Path(cwd)
    fingerprint = _load_fingerprint(root)
    if not fingerprint:
        return []

    findings: list[Finding] = []
    for rel in H1A_ENFORCED_PATHS:
        entry = fingerprint.get(rel)
        if not isinstance(entry, dict):
            continue
        template_hash = entry.get("template_hash")
        if not template_hash:
            continue  # no canonical baseline recorded
        abs_path = root / rel
        on_disk = _read_text_safe(abs_path)
        if on_disk is None:
            continue  # file absent — upstream MISSING check owns that
        current_hash = _hash_text(on_disk)
        if current_hash == template_hash:
            continue

        resolver = _TEMPLATE_RESOLVERS.get(rel)
        template = resolver(scaffold_cfg) if resolver is not None else None
        head_diff = (
            _first_n_lines_diff(template, on_disk)
            if template is not None
            else "(template not resolvable)"
        )
        findings.append(
            Finding(
                code="OWNERSHIP-DRIFT-001",
                severity="HIGH",
                file=rel,
                message=(
                    f"Scaffold-owned file drift detected after wave "
                    f"{wave_name}. file={rel} "
                    f"template_hash={template_hash} "
                    f"current_hash={current_hash} "
                    f"head_diff=[{head_diff}]"
                ),
            )
        )

    return findings


__all__ = [
    "Finding",
    "H1A_ENFORCED_PATHS",
    "FINGERPRINT_PATH",
    "check_template_drift_and_fingerprint",
    "check_wave_a_forbidden_writes",
    "check_post_wave_drift",
    "get_scaffold_owned_paths_for_wave_a_prompt",
]
