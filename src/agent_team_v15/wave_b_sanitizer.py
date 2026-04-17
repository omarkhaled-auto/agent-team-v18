"""Phase F N-19 — Wave B output sanitization.

Phase B's NEW-1 removed stale ``apps/api/src/prisma/`` emissions that
Wave B occasionally regenerated after the canonical relocation. N-19
generalises the same idea: after Wave B writes its files, compare each
emitted path against the :class:`OwnershipContract` and flag any file
Wave B created in a location whose canonical owner is ``scaffold``
(the scaffold runner should own that slot, not Wave B).

Safety rails
============

Removal is **never** silent. For each orphan candidate:

  * Run a deterministic ripgrep-style scan over the workspace to see
    whether any other source file imports / requires / references the
    path. If a consumer is found, the file is reported but NOT
    removed.
  * The action is logged (``logger.info``) with the emitted path, the
    contract's declared owner, and whether a consumer was detected.
  * An ``OrphanReport`` is returned so callers can feed findings into
    AUDIT_REPORT / BUILD_LOG or simply log-and-move-on.

The hook is off-by-path: it only runs when
``v18.wave_b_output_sanitization_enabled`` is True (default True) and
an ownership contract is available.

NOTE: The hook's removal path is conservative. A Wave B emission that
lives in a scaffold-owned path is REPORTED (not deleted) unless
removal is explicitly opted-in via the ``remove_orphans=True`` flag.
Default is report-only so live runs do not lose work that might be
load-bearing for a fix sub-agent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class OrphanFinding:
    """One orphan candidate discovered by the sanitizer."""

    relative_path: str
    expected_owner: str  # "scaffold" / "wave-c-generator" / etc.
    wave_b_wrote: bool = True
    has_consumers: bool = False
    consumer_samples: list[str] = field(default_factory=list)
    removed: bool = False


@dataclass
class SanitizationReport:
    """Result of running the Wave B sanitizer once."""

    orphan_findings: list[OrphanFinding] = field(default_factory=list)
    scanned_files: int = 0
    skipped_reason: str = ""  # non-empty when the hook didn't run

    @property
    def orphan_count(self) -> int:
        return len(self.orphan_findings)

    @property
    def removed_count(self) -> int:
        return sum(1 for f in self.orphan_findings if f.removed)


def wave_b_output_sanitization_enabled(config: Any) -> bool:
    v18 = getattr(config, "v18", None)
    return bool(getattr(v18, "wave_b_output_sanitization_enabled", True))


# Sub-trees Wave B legitimately writes under. Anything here is allowed.
_WAVE_B_LEGITIMATE_ROOTS: tuple[str, ...] = (
    "apps/api/src/auth",
    "apps/api/src/users",
    "apps/api/src/database",
    "apps/api/src/common",
    "apps/api/src/app.module.ts",
    "apps/api/src/app.controller.ts",
    "apps/api/src/app.service.ts",
    "apps/api/test",
    "apps/api/prisma",
    "apps/api/src/dto",
    "apps/api/src/modules",
)


_CONSUMER_PATTERN = re.compile(
    r"""
    (?:
        from\s+['"](?P<import_target>[^'"]+)['"]
      | require\(\s*['"](?P<require_target>[^'"]+)['"]\s*\)
      | import\s+['"](?P<bare_target>[^'"]+)['"]
    )
    """,
    re.VERBOSE,
)


def _normalize(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def _is_legitimate_wave_b_path(relative: str) -> bool:
    """Return True when the path lives in a known Wave-B-owned subtree."""
    norm = _normalize(relative)
    return any(
        norm == root or norm.startswith(root + "/")
        for root in _WAVE_B_LEGITIMATE_ROOTS
    )


def _module_specifier_candidates(relative_path: str) -> list[str]:
    """Return strings that consumers might use to import ``relative_path``.

    We accept matches on either:
      * the full relative path (``apps/api/src/foo.ts``),
      * the path WITHOUT the leading ``apps/`` or ``packages/`` prefix,
      * the path without its extension,
      * the workspace-relative segment after ``src/`` (common TS alias).
    """
    norm = _normalize(relative_path)
    stem_candidates = {norm}
    no_ext = re.sub(r"\.[A-Za-z0-9]+$", "", norm)
    if no_ext and no_ext != norm:
        stem_candidates.add(no_ext)
    for prefix in ("apps/", "packages/"):
        if norm.startswith(prefix):
            suffix = norm[len(prefix):]
            stem_candidates.add(suffix)
            suffix_no_ext = re.sub(r"\.[A-Za-z0-9]+$", "", suffix)
            if suffix_no_ext:
                stem_candidates.add(suffix_no_ext)
    # Ditch the ``src/`` segment for path-alias-style imports.
    for cand in list(stem_candidates):
        parts = cand.split("/")
        if "src" in parts:
            idx = parts.index("src")
            tail = "/".join(parts[idx + 1:])
            if tail:
                stem_candidates.add(tail)
    return sorted(c for c in stem_candidates if c)


_CONSUMER_FILE_GLOBS: tuple[str, ...] = (
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.mjs",
    "*.cjs",
)


def _scan_for_consumers(
    workspace: Path,
    relative_path: str,
    *,
    max_samples: int = 3,
) -> list[str]:
    """Grep-like scan for imports / requires of ``relative_path``.

    Returns up to ``max_samples`` consumer paths (relative, forward
    slashed). The scan skips ``node_modules`` / ``.next`` / ``dist``
    automatically. When the file is large enough that a full scan
    would be expensive, the function still returns after finding
    ``max_samples`` matches — we only need to know whether a consumer
    exists, not count them all.
    """
    specifiers = _module_specifier_candidates(relative_path)
    if not specifiers:
        return []

    samples: list[str] = []
    skip_dirs = {"node_modules", ".next", "dist", "build", ".turbo", ".git", "__pycache__"}
    self_path = (workspace / relative_path).resolve()

    for glob_pat in _CONSUMER_FILE_GLOBS:
        if len(samples) >= max_samples:
            break
        for candidate in workspace.rglob(glob_pat):
            if len(samples) >= max_samples:
                break
            if any(part in skip_dirs for part in candidate.parts):
                continue
            try:
                if candidate.resolve() == self_path:
                    continue
            except OSError:
                pass
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hit = False
            for match in _CONSUMER_PATTERN.finditer(text):
                target = (
                    match.group("import_target")
                    or match.group("require_target")
                    or match.group("bare_target")
                    or ""
                )
                if not target:
                    continue
                if any(spec in target for spec in specifiers):
                    hit = True
                    break
            if hit:
                try:
                    rel = candidate.relative_to(workspace)
                    samples.append(_normalize(str(rel)))
                except ValueError:
                    samples.append(_normalize(str(candidate)))
    return samples


def _iter_contract_paths_owned_by(
    contract: Any,
    owner: str,
) -> Iterable[str]:
    """Yield relative paths the contract declares for ``owner``."""
    try:
        rows = contract.files_for_owner(owner)
    except AttributeError:
        return
    for row in rows:
        yield _normalize(getattr(row, "path", ""))


def sanitize_wave_b_outputs(
    *,
    cwd: str | Path,
    contract: Any,
    wave_b_files: Iterable[str],
    config: Any,
    remove_orphans: bool = False,
) -> SanitizationReport:
    """Compare Wave B emissions against the ownership contract.

    Args:
        cwd: workspace root (must exist).
        contract: an :class:`OwnershipContract` (or duck-type exposing
            ``files_for_owner(owner)``).
        wave_b_files: iterable of workspace-relative paths Wave B wrote
            during this run.
        config: active :class:`AgentTeamConfig`. Flag-gated by
            ``v18.wave_b_output_sanitization_enabled``.
        remove_orphans: when True (opt-in), orphans without detected
            consumers are deleted from disk. Default False reports but
            never removes.

    Returns:
        A :class:`SanitizationReport` with one :class:`OrphanFinding`
        per Wave B emission that lives in a scaffold-owned slot.
    """
    report = SanitizationReport()
    if not wave_b_output_sanitization_enabled(config):
        report.skipped_reason = "flag_off"
        return report
    if contract is None:
        report.skipped_reason = "no_contract"
        return report

    workspace = Path(cwd)
    # Build the "paths NOT owned by wave-b" set so we don't hit the
    # contract once per file. The sanitizer's question is: did Wave B
    # emit into a slot whose canonical owner is NOT wave-b?
    #
    # F-INT-002: extend the list to cover every valid non-wave-b
    # owner. Previously this was ``("scaffold", "wave-c-generator")``
    # which let Wave B silently overwrite wave-d-owned files with no
    # orphan finding. The scaffold ownership contract's _VALID_OWNERS
    # are {"scaffold", "wave-b", "wave-d", "wave-c-generator"}; we
    # mirror every non-wave-b entry here.
    non_wave_b_paths: set[str] = set()
    for owner in ("scaffold", "wave-c-generator", "wave-d"):
        non_wave_b_paths.update(_iter_contract_paths_owned_by(contract, owner))

    # Also treat any scaffold-owned DIRECTORY as a claim zone — if the
    # contract owns ``apps/web/next.config.mjs`` and Wave B emits a
    # file at ``apps/web/sneaky.mjs`` the directory ownership is a
    # signal, not conclusive. We only flag on an exact path collision
    # to avoid false positives.

    for emitted in wave_b_files:
        rel = _normalize(emitted)
        report.scanned_files += 1
        if not rel:
            continue
        if _is_legitimate_wave_b_path(rel):
            continue
        if rel not in non_wave_b_paths:
            continue
        # Orphan candidate — a scaffold-owned path Wave B wrote to.
        owner = "scaffold"
        try:
            declared = contract.owner_for(rel)
            if declared:
                owner = declared
        except AttributeError:
            pass
        samples = _scan_for_consumers(workspace, rel)
        finding = OrphanFinding(
            relative_path=rel,
            expected_owner=owner,
            has_consumers=bool(samples),
            consumer_samples=samples,
        )
        if remove_orphans and not samples:
            target = workspace / rel
            try:
                if target.is_file():
                    target.unlink()
                    finding.removed = True
            except OSError as exc:
                logger.warning(
                    "N-19 sanitizer: failed to remove orphan %s: %s",
                    rel,
                    exc,
                )
        logger.info(
            "N-19 sanitizer: orphan candidate %s (expected owner=%s, "
            "consumers=%s, removed=%s)",
            rel,
            owner,
            "yes" if samples else "no",
            finding.removed,
        )
        report.orphan_findings.append(finding)
    return report


def build_orphan_findings(
    report: SanitizationReport,
) -> list[dict[str, Any]]:
    """Serialise orphan candidates into audit-finding dicts.

    Each orphan becomes a MEDIUM-severity ``PARTIAL`` finding so the
    operator sees the gap without automatically failing the milestone.
    Removed orphans are downgraded to INFO because they've already
    been cleaned up.
    """
    out: list[dict[str, Any]] = []
    for finding in report.orphan_findings:
        if finding.removed:
            severity = "INFO"
            verdict = "PASS"
            summary = (
                f"N-19 removed orphan Wave-B emission at '{finding.relative_path}' "
                f"(expected owner={finding.expected_owner}, no consumers)."
            )
        else:
            severity = "INFO" if finding.has_consumers else "MEDIUM"
            verdict = "PARTIAL"
            summary = (
                f"N-19 flagged orphan Wave-B emission at '{finding.relative_path}' "
                f"(expected owner={finding.expected_owner}; "
                f"consumers={'detected' if finding.has_consumers else 'none'})."
            )
        out.append(
            {
                "finding_id": f"N-19-ORPHAN-{finding.relative_path.replace('/', '-')}",
                "auditor": "wave-b-sanitizer",
                "requirement_id": "GENERAL",
                "verdict": verdict,
                "severity": severity,
                "summary": summary,
                "evidence": [
                    f"path: {finding.relative_path}",
                    f"expected_owner: {finding.expected_owner}",
                    f"consumer_samples: {', '.join(finding.consumer_samples) or 'none'}",
                ],
                "remediation": (
                    "Move this emission back under a Wave-B-owned subtree "
                    "(apps/api/src/{auth,users,common,database,dto}) or update "
                    "SCAFFOLD_OWNERSHIP.md to reassign ownership."
                ),
                "source": "deterministic",
            }
        )
    return out
