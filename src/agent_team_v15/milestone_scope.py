"""A-09: milestone-scoped wave prompt enforcement.

This module is the structural complement to A-09: wave prompts built from
the full PRD/IR were causing the builder to over-produce M2–M5 features
during M1 execution (see build-j-closeout-sonnet-20260415 audit findings).
The fix moves scope enforcement into the pre-prompt layer:

1. ``build_scope_for_milestone`` derives a ``MilestoneScope`` from the
   MASTER_PLAN entry for the given milestone + the milestone's
   ``REQUIREMENTS.md`` (for the concrete "Files to Create" list).
2. ``apply_scope_to_prompt`` prefixes + suffixes any wave prompt with an
   explicit scope block: allowed file globs, forbidden content, and an
   "ONLY produce these files" directive.
3. ``files_outside_scope`` powers the post-wave validator in
   ``wave_executor`` so out-of-scope writes become
   ``WaveResult.scope_violations``.

The feature flag ``config.v18.milestone_scope_enforcement`` gates the
prompt-layer application; the post-wave validator always runs when a
scope is available, never deletes files, and lets the caller decide
whether violations should fail the wave.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MilestoneScope:
    """Scope definition for a single milestone.

    Attributes:
        milestone_id: e.g. ``milestone-1``.
        allowed_entities: domain entities this milestone may reference
            (empty for infrastructure-only milestones).
        allowed_feature_refs: feature IDs (``F-AUTH``, ``F-PROJ`` etc.).
        allowed_ac_refs: acceptance-criterion IDs.
        allowed_file_globs: glob patterns derived from the milestone's
            "Files to Create" tree. Supports ``**`` recursive and ``*``
            single-segment wildcards. Paths use forward slashes.
        description: milestone-specific description (no leakage from
            sibling milestones).
        forbidden_content: plain-English don't-generate directives
            (e.g. "No feature business logic in this milestone").
    """

    milestone_id: str
    allowed_entities: list[str] = field(default_factory=list)
    allowed_feature_refs: list[str] = field(default_factory=list)
    allowed_ac_refs: list[str] = field(default_factory=list)
    allowed_file_globs: list[str] = field(default_factory=list)
    description: str = ""
    forbidden_content: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing — REQUIREMENTS.md "Files to Create" tree -> glob list
# ---------------------------------------------------------------------------

_TREE_LINE_RE = re.compile(r"^[\s│├└─]*(?P<name>[^\s│├└─#][^\s#]*?)(?P<trail>\s*#.*)?$")

# Universal scaffold-owned root files + tooling-emitted artifacts: any wave
# may legitimately produce these as a side effect of normal work —
# ``pnpm install`` rewrites the lockfile when deps are added,
# ``.env.example`` accumulates new vars as features land, the Codex
# appserver writes a 0-byte ``.codex`` sentinel at run-dir root on
# session start, and the ``track-file-change.sh`` PostToolUse hook
# (see ``hooks_manager.generate_post_tool_use_hook``) writes
# ``.claude/hooks/file-changes.log`` on every Write/Edit. The post-wave
# ``files_outside_scope`` validator unconditionally exempts these paths
# because the planner-authored REQUIREMENTS.md does not list operational
# scaffold/tooling artifacts (smoke ``m1-hardening-smoke-20260425-171429``
# false-failed Wave B for ``.env.example`` + ``pnpm-lock.yaml``; smoke
# ``m1-hardening-smoke-20260427-213258`` HARDFAILED Wave B on the
# ``.codex`` sentinel — Risk #31).
#
# These paths are NOT added to ``MilestoneScope.allowed_file_globs`` because
# that field also drives the prompt-layer scope preamble shown to agents.
# Wave A (architect) interprets root-level paths in its scope as an
# instruction to write infra config, then writes
# ``WAVE_A_CONTRACT_CONFLICT.md`` claiming a contradiction with
# STACK-PATH-001 (smoke ``m1-hardening-smoke-20260425-174554``). Keeping
# the allowlist validator-side preserves Wave A's narrow architect scope
# while still permitting other waves' legitimate tooling-artifact writes.
_UNIVERSAL_SCAFFOLD_ROOT_FILES: frozenset[str] = frozenset({
    ".env.example",
    "docker-compose.yml",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    # Codex appserver session sentinel (0-byte file at run-dir root).
    # Risk #31 — m1-hardening-smoke-20260427-213258 wave-failed because
    # this file matched no allowed_file_globs. Wave-agnostic.
    ".codex",
    # PostToolUse hook log written by ``track-file-change.sh`` on every
    # Write/Edit (see ``hooks_manager.generate_post_tool_use_hook``).
    # Wave A produces this on its REQUIREMENTS.md / MASTER_PLAN.md
    # writes; smoke m1-hardening-smoke-20260427-213258 surfaced it as
    # NEW noise alongside the long-tolerated ``.claude/settings.json``
    # warning. Wave-agnostic by design.
    ".claude/hooks/file-changes.log",
})


def parse_files_to_create(markdown: str) -> list[str]:
    """Parse the ``## Files to Create`` tree from a REQUIREMENTS.md body.

    Returns a concise list of glob patterns. Directory nodes that contain
    2+ children collapse to ``dir/**`` so the resulting list stays small
    enough to brief an audit agent on.
    """
    block = _extract_files_to_create_block(markdown)
    if not block:
        return _derive_surface_globs_from_requirements(markdown)

    nodes = _parse_tree(block)
    return _nodes_to_globs(nodes)


def _derive_surface_globs_from_requirements(markdown: str) -> list[str]:
    """Infer broad M1-safe globs from generated surface sections.

    The generated M1 requirements used by fresh hardening runs list
    ``In-Scope Deliverables`` and ``Merge Surfaces`` instead of a literal
    ``Files to Create`` tree. For those docs, derive concrete root surfaces so
    the scope prompt remains useful and does not say nothing should be produced.
    """

    text = str(markdown or "")
    if not text.strip():
        return []
    lower = text.lower()
    globs: list[str] = []

    def _add(glob: str) -> None:
        if glob not in globs:
            globs.append(glob)

    if re.search(r"(?<![a-z0-9_-])apps/api(?:/|\b)", lower):
        _add("apps/api/**")
    if re.search(r"(?<![a-z0-9_-])apps/web(?:/|\b)", lower):
        _add("apps/web/**")
    if re.search(r"(?<![a-z0-9_-])packages/api-client(?:/|\b)", lower):
        _add("packages/api-client/**")
    if re.search(r"(?<![a-z0-9_-])prisma(?:/|\b)|prisma/schema\.prisma", lower):
        _add("prisma/**")
    if re.search(r"(?<![a-z0-9_-])locales(?:/|\b)", lower):
        _add("locales/**")

    for literal in (
        "docker-compose.yml",
        ".env.example",
        "package.json",
        "pnpm-workspace.yaml",
    ):
        if literal in lower:
            _add(literal)

    return globs


def _extract_files_to_create_block(markdown: str) -> str:
    """Return the code-fenced tree under ``## Files to Create`` or ``""``."""
    section_re = re.compile(
        r"##\s*Files\s+to\s+Create\s*\n+```[^\n]*\n(?P<body>.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    m = section_re.search(markdown)
    return m.group("body") if m else ""


@dataclass
class _TreeNode:
    name: str
    is_dir: bool = False
    children: list["_TreeNode"] = field(default_factory=list)


def _parse_tree(block: str) -> list[_TreeNode]:
    """Parse an ASCII tree (``├──`` / ``└──``) into a nested node list."""
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]

    # Each line's "depth" is the count of leading tree-structure prefixes.
    stack: list[tuple[int, _TreeNode]] = []
    roots: list[_TreeNode] = []

    for raw in lines:
        depth, name = _line_depth_and_name(raw)
        if not name:
            continue
        is_dir = name.endswith("/")
        clean = name.rstrip("/")
        # The bare root marker "/" is rendered in REQUIREMENTS.md as the
        # first tree line; skip it — its children are top-level entries.
        if clean == "" or clean == ".":
            continue
        node = _TreeNode(name=clean, is_dir=is_dir)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        if is_dir:
            stack.append((depth, node))
        else:
            # Files can still have deeper siblings in the same dir; only
            # pop when the next line's depth is shallower (handled above).
            pass

    return roots


def _line_depth_and_name(raw: str) -> tuple[int, str]:
    """Approximate tree depth from leading indent + tree characters.

    The REQUIREMENTS.md tree uses a mix of ``│``, ``├──``, ``└──``, and
    4-space indents. We normalise to a depth integer by counting
    4-character "rails" in the prefix.
    """
    # Strip a trailing inline comment before we extract the name.
    sans_comment = re.sub(r"\s+#.*$", "", raw)
    # Walk the prefix counting rails (``│   ``, ``    ``) before the node.
    prefix_match = re.match(r"^([\s│├└─]*)", sans_comment)
    prefix = prefix_match.group(1) if prefix_match else ""
    # The node name is whatever follows ``── `` or the prefix.
    remainder = sans_comment[len(prefix):].strip()
    if not remainder:
        return 0, ""
    # Count rails (each "│   " or "    " is one level of depth).
    depth = 0
    i = 0
    while i < len(prefix):
        chunk = prefix[i : i + 4]
        if chunk in ("│   ", "    ", "    "):
            depth += 1
            i += 4
            continue
        # ``├──`` / ``└──`` introduce the leaf at depth+1.
        if chunk.startswith(("├──", "└──")):
            depth += 1
            break
        # Fallback: advance a single char to avoid infinite loop on odd
        # whitespace.
        i += 1
    return depth, remainder


def _nodes_to_globs(nodes: Iterable[_TreeNode], prefix: str = "") -> list[str]:
    """Emit globs that match the tree's literal files.

    Collapse rule — only flatten *leaf directories* (directories whose
    children are all files, no nested subdirectories) when they contain
    two or more files. This keeps ``dir/**`` globs tightly scoped and
    prevents an ancestor like ``apps/**`` from swallowing later-milestone
    sub-trees (e.g. ``apps/api/src/projects/**``).
    """
    globs: list[str] = []
    for node in nodes:
        path = f"{prefix}{node.name}" if prefix else node.name
        if node.is_dir:
            has_subdir = any(child.is_dir for child in node.children)
            file_children = [c for c in node.children if not c.is_dir]
            if not has_subdir and len(file_children) >= 2:
                globs.append(f"{path}/**")
            else:
                globs.extend(_nodes_to_globs(node.children, prefix=path + "/"))
        else:
            globs.append(path)
    return globs


# ---------------------------------------------------------------------------
# MilestoneScope factory
# ---------------------------------------------------------------------------


def build_scope_for_milestone(
    *,
    master_plan: Any,
    milestone_id: str,
    requirements_md_path: str | Path,
) -> MilestoneScope:
    """Build a :class:`MilestoneScope` from the master plan + REQUIREMENTS.md.

    ``master_plan`` may be a parsed dict or an object with a ``milestones``
    attribute. Missing milestone entries fall back to empty lists — a
    safe default that does not leak cross-milestone content.
    """
    entry = _find_milestone_entry(master_plan, milestone_id)

    description = _text(entry.get("description") if isinstance(entry, dict) else "")

    allowed_entities = _string_list(
        entry.get("entities") if isinstance(entry, dict) else None
    )
    allowed_feature_refs = _string_list(
        entry.get("feature_refs") if isinstance(entry, dict) else None
    )
    allowed_ac_refs = _string_list(
        entry.get("ac_refs") if isinstance(entry, dict) else None
    )

    requirements_md_text = _read_text_safely(requirements_md_path)
    allowed_file_globs = parse_files_to_create(requirements_md_text)

    forbidden_content = _extract_forbidden_notes(requirements_md_text)

    return MilestoneScope(
        milestone_id=milestone_id,
        allowed_entities=allowed_entities,
        allowed_feature_refs=allowed_feature_refs,
        allowed_ac_refs=allowed_ac_refs,
        allowed_file_globs=allowed_file_globs,
        description=description,
        forbidden_content=forbidden_content,
    )


def _find_milestone_entry(master_plan: Any, milestone_id: str) -> dict:
    if isinstance(master_plan, dict):
        entries = master_plan.get("milestones") or []
    else:
        entries = getattr(master_plan, "milestones", []) or []
    for entry in entries:
        entry_dict = entry if isinstance(entry, dict) else _to_dict(entry)
        if str(entry_dict.get("id", "")).strip() == milestone_id:
            return entry_dict
    return {}


def _to_dict(obj: Any) -> dict:
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    try:
        return dict(obj)
    except Exception:
        return {}


def _string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value]
    return []


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_text_safely(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


_FORBIDDEN_PATTERNS = (
    re.compile(r"^\s*-\s+No\b[^\n]+", re.MULTILINE),
    re.compile(r"^\s*-\s+[^\n]+\bdeferred\b[^\n]+", re.MULTILINE | re.IGNORECASE),
    re.compile(
        r"^\s*-\s+[^\n]+\b(?:added|implemented|populated)\b[^\n]*\b(?:in|at|per)\s+M[2-9][^\n]*",
        re.MULTILINE | re.IGNORECASE,
    ),
)


def _extract_forbidden_notes(markdown: str) -> list[str]:
    """Collect plain-English don't-generate directives from the Notes section."""
    if not markdown:
        return []
    notes: list[str] = []
    notes_block_re = re.compile(r"##\s*Notes\s*\n(.+?)(?=\n##\s|\Z)", re.DOTALL)
    m = notes_block_re.search(markdown)
    body = m.group(1) if m else markdown
    seen: set[str] = set()
    for pat in _FORBIDDEN_PATTERNS:
        for hit in pat.findall(body):
            text = hit.strip().lstrip("-").strip()
            if text and text not in seen:
                notes.append(text)
                seen.add(text)
    return notes


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a simplified glob to a regex.

    Supports:
      - ``**`` — matches zero or more full path segments (including /).
      - ``*``  — matches within a single segment (no /).
      - ``?``  — matches one char (no /).

    All paths are normalised to forward slashes before matching.
    """
    i = 0
    out: list[str] = ["^"]
    while i < len(glob):
        ch = glob[i]
        if glob[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif glob[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch in r"\.+()[]{}^$|":
            out.append(re.escape(ch))
            i += 1
        else:
            out.append(ch)
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _normalize_path(path: str) -> str:
    norm = path.replace("\\", "/").strip()
    if norm.startswith("./"):
        norm = norm[2:]
    while norm.startswith("/"):
        norm = norm[1:]
    return norm


def file_matches_any_glob(path: str, globs: Iterable[str]) -> bool:
    norm = _normalize_path(path)
    for glob in globs:
        pattern = _glob_to_regex(_normalize_path(glob))
        if pattern.match(norm):
            return True
    return False


def files_outside_scope(files: Iterable[str], scope: MilestoneScope) -> list[str]:
    """Return the subset of *files* that do not match any allowed glob.

    Two validator-only exemptions are layered on top of the milestone's
    declared globs:

    * ``_UNIVERSAL_SCAFFOLD_ROOT_FILES`` — see the constant's docstring.
    * ``e2e/tests/<milestone_id>/`` — Wave E's hard-wired Playwright spec
      directory (see ``agents.build_wave_e_prompt`` and
      ``fix_executor.e2e_dir``). Smoke
      ``v18 test runs/m1-hardening-smoke-20260425-175816`` failed Wave E
      on ``e2e/tests/milestone-1/foundation.spec.ts`` because the
      planner-authored REQUIREMENTS.md only ever lists `apps/...` paths
      while Wave E is structurally required to write into the per-milestone
      e2e directory. The exemption is validator-only for the same reason
      the scaffold-files exemption is.
    """
    if not scope.allowed_file_globs:
        return []
    patterns = [_glob_to_regex(_normalize_path(g)) for g in scope.allowed_file_globs]
    e2e_prefix = (
        f"e2e/tests/{scope.milestone_id}/" if scope.milestone_id else None
    )
    out: list[str] = []
    for raw in files:
        norm = _normalize_path(raw)
        if norm in _UNIVERSAL_SCAFFOLD_ROOT_FILES:
            continue
        if e2e_prefix and norm.startswith(e2e_prefix):
            continue
        if not any(p.match(norm) for p in patterns):
            out.append(raw)
    return out


# ---------------------------------------------------------------------------
# Prompt application
# ---------------------------------------------------------------------------


_SCOPE_PREAMBLE_TEMPLATE = """\
## Milestone Scope — {milestone_id}

You are executing Wave {wave} for milestone **{milestone_id}** ONLY.
Do NOT produce files or logic that belong to other milestones. The
master plan is phased on purpose: later milestones depend on this
milestone's scaffold being minimal and correct.

### Description (milestone-scoped)
{description}

### Allowed file globs — only produce files matching these patterns
{allowed_globs_block}

### Allowed domain entities for this milestone
{allowed_entities_block}

### Allowed feature / AC references for this milestone
{allowed_feature_refs_block}

### Milestone-local directives (from REQUIREMENTS.md Notes)
{forbidden_block}

### Enforcement
- Domain entities, feature refs, or acceptance criteria NOT in the
  allowed lists above must not be referenced in code, imports,
  comments, or docstrings. Treat them as non-existent for this wave.
- A post-wave scope validator flags any file written outside the
  allowed globs as a scope_violation on WaveResult.

---

"""


_SCOPE_SUFFIX_TEMPLATE = """

---

## Scope reminder (end of prompt)
Milestone **{milestone_id}** — do not add files or symbols belonging to
later milestones. If a required import would pull in an out-of-scope
feature, stop and leave a stub that other milestones can fill in.
"""


def _format_bullet_list(items: Iterable[str], default: str) -> str:
    entries = [s for s in (str(i).strip() for i in items) if s]
    if not entries:
        return f"- {default}"
    return "\n".join(f"- {e}" for e in entries)


def apply_scope_to_prompt(
    prompt: str,
    scope: MilestoneScope,
    *,
    wave: str,
    wave_boundary_narrow_globs: bool = True,
) -> str:
    """Wrap *prompt* with the scope preamble and suffix for *wave*.

    Returns the prompt unchanged if *scope* is missing the fields that
    would make the preamble meaningful (no milestone id).

    Phase 4.7a: when *wave_boundary_narrow_globs* is True (default),
    the rendered "Allowed file globs" block drops sibling-wave globs for
    Wave B and Wave D — the two ambiguity-prone implementation waves.
    See ``wave_boundary.narrow_allowed_globs_for_wave`` for the filter
    contract. Pass ``wave_boundary_narrow_globs=False`` (or set
    ``AuditTeamConfig.wave_boundary_block_enabled = False`` and rely on
    ``apply_scope_if_enabled``'s gate) to restore pre-Phase-4.7a
    verbatim allowed-globs rendering.
    """
    if not scope or not scope.milestone_id:
        return prompt

    wave_letter = str(wave or "").upper() or "?"

    rendered_globs: list[str] = list(scope.allowed_file_globs or [])
    if wave_boundary_narrow_globs and wave_letter in {"B", "D"}:
        # Lazy import: wave_boundary depends on wave_ownership which is
        # already imported at module scope, but keeping the import
        # local makes the Phase 4.7a wiring explicit at the call site.
        from .wave_boundary import narrow_allowed_globs_for_wave
        rendered_globs = narrow_allowed_globs_for_wave(
            rendered_globs, wave_letter
        )

    preamble = _SCOPE_PREAMBLE_TEMPLATE.format(
        milestone_id=scope.milestone_id,
        wave=wave_letter,
        description=scope.description or "(no description provided)",
        allowed_globs_block=_format_bullet_list(
            rendered_globs,
            default="(no globs declared — nothing should be produced)",
        ),
        allowed_entities_block=_format_bullet_list(
            scope.allowed_entities,
            default="(none — this milestone introduces no business-logic entities)",
        ),
        allowed_feature_refs_block=_format_bullet_list(
            (scope.allowed_feature_refs or []) + (scope.allowed_ac_refs or []),
            default="(none — infrastructure-only milestone, no feature ACs)",
        ),
        forbidden_block=_format_bullet_list(
            scope.forbidden_content,
            default="(no explicit milestone-local directives beyond the globs above)",
        ),
    )
    suffix = _SCOPE_SUFFIX_TEMPLATE.format(milestone_id=scope.milestone_id)
    return preamble + prompt + suffix


def apply_scope_if_enabled(
    prompt: str,
    scope: MilestoneScope | None,
    config: Any,
    *,
    wave: str,
) -> str:
    """Apply scope only when the v18 feature flag is on and a scope exists.

    Phase 4.7a: defers narrowing of ``allowed_file_globs`` to
    ``apply_scope_to_prompt`` when ``audit_team.wave_boundary_block_enabled``
    is True (the default); flips ``wave_boundary_narrow_globs=False`` on
    the call when operators explicitly disable the feature on the config.
    """
    if scope is None:
        return prompt
    flag = True
    try:
        flag = bool(getattr(getattr(config, "v18", None), "milestone_scope_enforcement", True))
    except Exception:
        flag = True
    if not flag:
        return prompt
    narrow_globs = True
    try:
        audit_team = getattr(config, "audit_team", None)
        if audit_team is not None:
            narrow_globs = bool(
                getattr(audit_team, "wave_boundary_block_enabled", True)
            )
    except Exception:
        narrow_globs = True
    return apply_scope_to_prompt(
        prompt, scope, wave=wave, wave_boundary_narrow_globs=narrow_globs
    )


__all__ = [
    "MilestoneScope",
    "apply_scope_if_enabled",
    "apply_scope_to_prompt",
    "build_scope_for_milestone",
    "file_matches_any_glob",
    "files_outside_scope",
    "parse_files_to_create",
]
