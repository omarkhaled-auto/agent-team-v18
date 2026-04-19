"""Phase H1b — Wave A ARCHITECTURE.md schema validator.

Reads ``.agent-team/milestone-{milestone_id}/ARCHITECTURE.md`` and
returns a :class:`SchemaValidationResult` describing disallowed /
missing sections and undeclared injection references.

Mirrors :mod:`wave_a5_t5` in spirit: the validator does NOT re-dispatch
Wave A; it only produces findings. The gate enforcement function in
``cli.py`` decides whether to re-run Wave A or raise
``GateEnforcementError``.

No module-level mutable state (Wave 2A anti-pattern #1).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import wave_a_schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionRejection:
    """One section that the validator is rejecting."""

    heading: str
    canonical_match: str
    reason_code: str
    message: str


@dataclass(frozen=True)
class MissingRequiredSection:
    """One canonical required section that was absent from the file."""

    canonical: str
    example_heading: str


@dataclass(frozen=True)
class UndeclaredReference:
    """One ``{var}`` / ``${VAR}`` / ``<inject:...>`` token with no source."""

    token: str
    severity: str  # "MEDIUM"


@dataclass(frozen=True)
class ConcreteReferenceViolation:
    """One concrete reference (port / entity / path / AC id / milestone id)
    that Wave A cited but that is not derivable from any of the eight
    injection sources declared in :mod:`wave_a_schema.ALLOWED_REFERENCES`.

    Mapped to pattern ID ``WAVE-A-SCHEMA-REFERENCE-001`` per
    allowlist-evidence §6 Table 1–8. Severity HIGH.
    """

    token: str
    category: str  # "port" | "entity" | "file_path" | "ac_id" | "milestone_ref"
    message: str
    severity: str = "HIGH"


@dataclass
class SchemaValidationResult:
    """Outcome of validating a single ARCHITECTURE.md file."""

    milestone_id: str
    architecture_path: str
    disallowed_sections: list[SectionRejection] = field(default_factory=list)
    missing_required: list[MissingRequiredSection] = field(default_factory=list)
    undeclared_references: list[UndeclaredReference] = field(default_factory=list)
    concrete_references: list[ConcreteReferenceViolation] = field(default_factory=list)
    skipped_reason: str = ""  # non-empty when the validator short-circuited
    skipped_concrete_checks: list[str] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(
            self.disallowed_sections
            or self.missing_required
            or self.undeclared_references
            or self.concrete_references
        )

    def to_review_dict(self) -> dict[str, Any]:
        """Serialize to a reviewer-JSON-friendly shape.

        Mirrors the :class:`wave_a5_t5.PlanReviewFinding` → JSON shape so
        the downstream formatter can consume either source uniformly.
        """
        findings: list[dict[str, Any]] = []
        for rej in self.disallowed_sections:
            findings.append(
                {
                    "category": "schema_rejection",
                    "ref": rej.heading,
                    "severity": "CRITICAL",
                    "issue": rej.message,
                    "reason_code": rej.reason_code,
                    "pattern_id": wave_a_schema.PATTERN_SECTION_REJECTION,
                }
            )
        for miss in self.missing_required:
            findings.append(
                {
                    "category": "schema_missing_required",
                    "ref": miss.canonical,
                    "severity": "CRITICAL",
                    "issue": (
                        f"Required section '{miss.example_heading}' is missing "
                        "from ARCHITECTURE.md."
                    ),
                    "pattern_id": wave_a_schema.PATTERN_SECTION_REJECTION,
                }
            )
        for undecl in self.undeclared_references:
            findings.append(
                {
                    "category": "schema_undeclared_reference",
                    "ref": undecl.token,
                    "severity": undecl.severity,
                    "issue": (
                        f"Reference '{undecl.token}' is not derivable from the "
                        "Wave A injection variables "
                        f"({', '.join(wave_a_schema.ALLOWED_REFERENCES)})."
                    ),
                    "pattern_id": wave_a_schema.PATTERN_UNDECLARED_REFERENCE,
                }
            )
        for conc in self.concrete_references:
            findings.append(
                {
                    "category": f"schema_concrete_reference_{conc.category}",
                    "ref": conc.token,
                    "severity": conc.severity,
                    "issue": conc.message,
                    "pattern_id": wave_a_schema.PATTERN_CONCRETE_REFERENCE,
                }
            )
        return {
            "milestone_id": self.milestone_id,
            "architecture_path": self.architecture_path,
            "verdict": "FAIL" if self.has_findings else "PASS",
            "findings": findings,
            "skipped_reason": self.skipped_reason,
            "skipped_concrete_checks": list(self.skipped_concrete_checks),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_h2_heading_re = re.compile(r"^\s{0,3}##\s+(.+?)\s*$", re.MULTILINE)
_h3_heading_re = re.compile(r"^\s{0,3}###\s+(.+?)\s*$", re.MULTILINE)
_brace_var_re = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_dollar_var_re = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_inject_var_re = re.compile(r"<inject:([A-Za-z_][A-Za-z0-9_]*)>")


def validate_wave_a_output(
    content: str,
    milestone_id: str,
    *,
    architecture_path: str | None = None,
    require_schema_body: bool = False,
    require_seams_wave_d: bool = True,
    allowed_references_override: Iterable[str] | None = None,
    # Concrete-reference derivability inputs (allowlist-evidence §6).
    # Any of these left as None causes the corresponding check to be
    # SKIPPED (recorded in ``skipped_concrete_checks``) — never a
    # false positive.
    scaffolded_files: Iterable[str] | None = None,
    ir_entities: Iterable[str] | None = None,
    ir_acceptance_criteria: Iterable[str] | None = None,
    stack_contract: dict[str, Any] | None = None,
    backend_context: dict[str, Any] | None = None,
    cumulative_architecture: str | None = None,
    dependency_artifacts: dict[str, Any] | None = None,
    scaffold_ownership_paths: Iterable[str] | None = None,
) -> SchemaValidationResult:
    """Validate a single Wave A ARCHITECTURE.md body.

    ``content`` is the raw markdown. ``milestone_id`` is the milestone
    id (e.g. ``"milestone-1"``). ``require_schema_body`` flips the
    conditional ``schema_body`` requirement (True when the milestone's
    IR has ≥1 entity). ``require_seams_wave_d`` flips the conditional
    Wave-D seams requirement (False for ``backend_only`` templates).

    The concrete-reference kwargs (``scaffolded_files`` through
    ``scaffold_ownership_paths``) drive the derivability checks that
    map to pattern ID ``WAVE-A-SCHEMA-REFERENCE-001``. When any kwarg
    is ``None`` the corresponding check is skipped and recorded in
    ``result.skipped_concrete_checks`` — callers without full
    injection-source context never produce false positives.

    When ``content`` is empty or cannot be parsed as markdown the
    validator returns an empty result with ``skipped_reason`` set so
    the caller can decide whether to treat it as pass or fail.
    """
    result = SchemaValidationResult(
        milestone_id=milestone_id,
        architecture_path=str(architecture_path or ""),
    )

    if not content or not content.strip():
        result.skipped_reason = "ARCHITECTURE.md is empty or missing."
        return result

    try:
        headings_h2 = [m.group(1).strip() for m in _h2_heading_re.finditer(content)]
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "wave-a-schema: heading parse raised for %s: %s", milestone_id, exc
        )
        result.skipped_reason = f"heading parse failed: {exc}"
        return result

    canonical_by_alias = _build_alias_index()
    allowed_keys = set(wave_a_schema.ALLOWED_SECTIONS.keys())
    seen_canonical: set[str] = set()

    for heading in headings_h2:
        normalized = heading.strip().lower()
        disallow_hit = _match_disallowed(normalized)
        if disallow_hit is not None:
            reason_code, message = disallow_hit
            result.disallowed_sections.append(
                SectionRejection(
                    heading=heading,
                    canonical_match=normalized,
                    reason_code=reason_code,
                    message=message,
                )
            )
            continue
        canonical = _match_allowed(normalized, canonical_by_alias)
        if canonical is None:
            result.disallowed_sections.append(
                SectionRejection(
                    heading=heading,
                    canonical_match=normalized,
                    reason_code="UNKNOWN_SECTION",
                    message=(
                        f"Section '{heading}' is not in the allowed set. "
                        f"Allowed canonical sections: "
                        f"{sorted(allowed_keys)}."
                    ),
                )
            )
            continue
        seen_canonical.add(canonical)

    required = set(wave_a_schema.REQUIRED_SECTIONS)
    if require_schema_body:
        required.add("schema_body")
    if require_seams_wave_d:
        required.add("seams_wave_d")
    for canonical in sorted(required):
        if canonical in seen_canonical:
            continue
        example = _example_heading_for_canonical(canonical)
        result.missing_required.append(
            MissingRequiredSection(
                canonical=canonical,
                example_heading=example,
            )
        )

    allowed_refs = (
        set(allowed_references_override)
        if allowed_references_override is not None
        else set(wave_a_schema.ALLOWED_REFERENCES)
    )
    for match in _brace_var_re.finditer(content):
        token = match.group(1)
        if token in allowed_refs:
            continue
        result.undeclared_references.append(
            UndeclaredReference(token=f"{{{token}}}", severity="MEDIUM")
        )
    for match in _dollar_var_re.finditer(content):
        token = match.group(1)
        if token in allowed_refs:
            continue
        result.undeclared_references.append(
            UndeclaredReference(token=f"${{{token}}}", severity="MEDIUM")
        )
    for match in _inject_var_re.finditer(content):
        token = match.group(1)
        if token in allowed_refs:
            continue
        result.undeclared_references.append(
            UndeclaredReference(token=f"<inject:{token}>", severity="MEDIUM")
        )

    # Phase H1b — concrete-reference derivability (allowlist-evidence §6
    # Table 1–8). Runs alongside the placeholder scan above; covers the
    # smoke #11 failure mode (`PORT ?? 8080` in ## What Wave A produced
    # passing validation because 8080 is not a `{var}` placeholder).
    violations, skipped = _validate_concrete_references(
        content=content,
        scaffolded_files=(
            list(scaffolded_files) if scaffolded_files is not None else None
        ),
        ir_entities=(list(ir_entities) if ir_entities is not None else None),
        ir_acceptance_criteria=(
            list(ir_acceptance_criteria)
            if ir_acceptance_criteria is not None
            else None
        ),
        stack_contract=stack_contract,
        backend_context=backend_context,
        milestone_id=milestone_id,
        cumulative_architecture=cumulative_architecture,
        dependency_artifacts=dependency_artifacts,
        scaffold_ownership_paths=(
            list(scaffold_ownership_paths)
            if scaffold_ownership_paths is not None
            else None
        ),
    )
    result.concrete_references.extend(violations)
    result.skipped_concrete_checks.extend(skipped)

    return result


def format_schema_rejection_message(
    result: SchemaValidationResult,
    *,
    rerun_count: int,
    max_reruns: int,
) -> str:
    """Render the ``[SCHEMA FEEDBACK]`` sub-block for the prompt rejection channel.

    The returned string plugs into ``stack_contract_rejection_context``
    via the existing ``[PRIOR ATTEMPT REJECTED]`` channel at
    ``agents.py:8287-8292`` — do NOT introduce a second block (Wave 2A
    anti-pattern #3).
    """
    if not result.has_findings:
        return ""
    lines = ["[SCHEMA FEEDBACK]"]
    lines.append(
        "Wave A schema validator rejected the ARCHITECTURE.md you previously "
        "produced. Retry "
        f"{rerun_count + 1} of {max_reruns} available. Address EVERY item below "
        "and emit a fresh ARCHITECTURE.md — do not patch the old one."
    )
    ordinal = 1
    for rej in result.disallowed_sections:
        lines.append(f"\n{ordinal}. [section] ## {rej.heading}")
        lines.append(f"   Reason: {rej.message}")
        ordinal += 1
    for miss in result.missing_required:
        lines.append(
            f"\n{ordinal}. [missing] {miss.example_heading} (canonical: "
            f"{miss.canonical})"
        )
        lines.append(
            "   Reason: Required section is absent. Add it — see the "
            "[ARCHITECTURE.md SCHEMA] block in this prompt for the full "
            "allowlist."
        )
        ordinal += 1
    for undecl in result.undeclared_references:
        lines.append(f"\n{ordinal}. [reference] {undecl.token}")
        lines.append(
            "   Reason: Not derivable from the Wave A injection variables. "
            "Cite only values provided in this prompt; replace with a concrete "
            "path or id drawn from "
            f"{', '.join(wave_a_schema.ALLOWED_REFERENCES)}."
        )
        ordinal += 1
    for conc in result.concrete_references:
        lines.append(
            f"\n{ordinal}. [concrete/{conc.category}] {conc.token}"
        )
        lines.append(f"   Reason: {conc.message}")
        ordinal += 1
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_alias_index() -> dict[str, str]:
    """Return {normalized_alias → canonical_key} map."""
    index: dict[str, str] = {}
    for canonical, aliases in wave_a_schema.ALLOWED_SECTIONS.items():
        for alias in aliases:
            index[alias.strip().lower()] = canonical
    return index


def _match_allowed(normalized: str, alias_index: dict[str, str]) -> str | None:
    if normalized in alias_index:
        return alias_index[normalized]
    # Case-insensitive startswith fallback so e.g. "Seams Wave B must populate
    # (auth)" still resolves to seams_wave_b.
    for alias, canonical in alias_index.items():
        if normalized.startswith(alias):
            return canonical
    return None


def _match_disallowed(normalized: str) -> tuple[str, str] | None:
    for substrings, reason_code, message in wave_a_schema.DISALLOWED_SECTION_REASONS:
        for substring in substrings:
            if substring in normalized:
                return reason_code, message
    return None


def _example_heading_for_canonical(canonical: str) -> str:
    aliases = wave_a_schema.ALLOWED_SECTIONS.get(canonical, ())
    if not aliases:
        return canonical
    # Render the first alias capitalized as an H2 heading.
    sample = aliases[0]
    return "## " + sample[:1].upper() + sample[1:]


# ---------------------------------------------------------------------------
# Concrete-reference derivability (allowlist-evidence §6 Table 1–8)
# ---------------------------------------------------------------------------

_port_literal_re = re.compile(r"(?<![A-Za-z0-9_])(\d{4,5})(?![A-Za-z0-9_])")
_port_fallback_re = re.compile(
    r"PORT\s*(?:\?\?|\|\||:-|:=|\?|:)\s*(\d{2,5})", re.IGNORECASE
)
_camelcase_entity_re = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
_ac_id_re = re.compile(r"\b((?:FR|BR|NFR)-[A-Z]+-\d+)\b")
_milestone_ref_re = re.compile(r"\bM(\d+)\b")
_workspace_path_re = re.compile(
    r"(?:^|[\s`\"'(])((?:apps|packages)/[A-Za-z0-9_./-]+)"
)

_ALL_CONCRETE_CHECK_IDS: tuple[str, ...] = (
    "ports",
    "entity_names",
    "file_paths",
    "ac_ids",
    "milestone_refs",
)


def _validate_concrete_references(
    *,
    content: str,
    scaffolded_files: list[str] | None,
    ir_entities: list[str] | None,
    ir_acceptance_criteria: list[str] | None,
    stack_contract: dict[str, Any] | None,
    backend_context: dict[str, Any] | None,
    milestone_id: str,
    cumulative_architecture: str | None,
    dependency_artifacts: dict[str, Any] | None,
    scaffold_ownership_paths: list[str] | None,
) -> tuple[list[ConcreteReferenceViolation], list[str]]:
    """Enforce allowlist-evidence §6 Table 1–8.

    Returns ``(violations, skipped_checks)``. Each check category is
    SKIPPED (not failed) when its required injection source is ``None``
    — this prevents false positives when the caller could not resolve
    the full injection context. Skipped categories are returned as
    strings in ``skipped_checks`` so the gate can surface them in logs.
    """
    violations: list[ConcreteReferenceViolation] = []
    skipped: list[str] = []

    # 1. Ports — catches smoke #11 `PORT ?? 8080` when DoD requires 3080.
    if stack_contract is None:
        skipped.append("ports")
    else:
        allowed_ports = _extract_allowed_ports(stack_contract)
        # High-priority catch: `PORT ??/||/:-/:= <digits>` fallback-default
        # shape is the exact smoke #11 pattern.
        for match in _port_fallback_re.finditer(content):
            port_str = match.group(1)
            try:
                port = int(port_str)
            except ValueError:
                continue
            if port in allowed_ports:
                continue
            violations.append(
                ConcreteReferenceViolation(
                    token=port_str,
                    category="port",
                    message=(
                        f"Wave A handoff references port {port_str} via a "
                        "fallback-default expression (e.g. `PORT ?? 8080`) "
                        f"which is not in the stack contract ports "
                        f"({sorted(allowed_ports) if allowed_ports else '[]'}). "
                        "Cite only values provided to the Wave A prompt."
                    ),
                )
            )
        # Broader port-literal scan in section bodies that must not drift:
        port_section_bodies = _extract_section_bodies(
            content,
            canonical_targets=("what_wave_a_produced", "seams_wave_b"),
        )
        seen_port_tokens: set[str] = set()
        for body in port_section_bodies:
            for match in _port_literal_re.finditer(body):
                port_str = match.group(1)
                if port_str in seen_port_tokens:
                    continue
                try:
                    port = int(port_str)
                except ValueError:
                    continue
                # Only flag obvious port numbers (1024-65535 and the
                # usual 3xxx/5xxx/8xxx cluster). Skip anything that
                # appears already in the stack contract.
                if port in allowed_ports:
                    continue
                if not _looks_like_port(port):
                    continue
                seen_port_tokens.add(port_str)
                violations.append(
                    ConcreteReferenceViolation(
                        token=port_str,
                        category="port",
                        message=(
                            f"Wave A handoff references port {port_str} "
                            "which is not in the stack contract ports "
                            f"({sorted(allowed_ports) if allowed_ports else '[]'}). "
                            "Cite only values provided to the Wave A prompt."
                        ),
                    )
                )

    # 2. Entity names — hallucinated CamelCase inside schema sections.
    if ir_entities is None:
        skipped.append("entity_names")
    else:
        allowed_entities = {e for e in ir_entities if isinstance(e, str) and e}
        entity_section_bodies = _extract_section_bodies(
            content, canonical_targets=("schema_body",)
        )
        seen_entity_tokens: set[str] = set()
        for body in entity_section_bodies:
            for match in _camelcase_entity_re.finditer(body):
                token = match.group(1)
                if token in seen_entity_tokens:
                    continue
                if token in allowed_entities:
                    continue
                # Whitelist common non-entity CamelCase (framework names,
                # method idioms) that are benign in prose.
                if _is_common_camelcase_noise(token):
                    continue
                seen_entity_tokens.add(token)
                violations.append(
                    ConcreteReferenceViolation(
                        token=token,
                        category="entity",
                        message=(
                            f"Wave A handoff references entity '{token}' "
                            "which is not in the milestone IR entity scope "
                            f"({sorted(allowed_entities) if allowed_entities else '[] (empty)'}). "
                            "Cite only entities provided to the Wave A prompt; "
                            "if this is a foundation milestone, use an "
                            "explicit-zero declaration instead."
                        ),
                    )
                )

    # 3. File paths — apps/… / packages/… citations must be derivable.
    if scaffolded_files is None:
        skipped.append("file_paths")
    else:
        allowed_paths = set(scaffolded_files)
        if scaffold_ownership_paths is not None:
            allowed_paths.update(scaffold_ownership_paths)
        api_root = ""
        repo_example = ""
        entity_example = ""
        if isinstance(backend_context, dict):
            api_root = str(backend_context.get("api_root", "") or "").strip()
            repo_example = str(
                backend_context.get("repository_example_path", "") or ""
            ).strip()
            entity_example = str(
                backend_context.get("entity_example_path", "") or ""
            ).strip()
        seen_path_tokens: set[str] = set()
        for match in _workspace_path_re.finditer(content):
            path_token = match.group(1).rstrip("`\"'),.;:")
            if path_token in seen_path_tokens:
                continue
            if path_token in allowed_paths:
                continue
            if api_root and path_token.startswith(api_root.rstrip("/") + "/"):
                continue
            if repo_example and path_token == repo_example:
                continue
            if entity_example and path_token == entity_example:
                continue
            seen_path_tokens.add(path_token)
            violations.append(
                ConcreteReferenceViolation(
                    token=path_token,
                    category="file_path",
                    message=(
                        f"Wave A handoff references path '{path_token}' "
                        "which is not in the scaffolded_files list, "
                        "docs/SCAFFOLD_OWNERSHIP.md, or the backend_context "
                        "prefixes. Cite only values provided to the Wave A "
                        "prompt."
                    ),
                )
            )

    # 4. AC IDs — `FR-…`, `BR-…`, `NFR-…` must be in the selected AC list.
    if ir_acceptance_criteria is None:
        skipped.append("ac_ids")
    else:
        allowed_acs = {
            a for a in ir_acceptance_criteria if isinstance(a, str) and a
        }
        seen_ac_tokens: set[str] = set()
        for match in _ac_id_re.finditer(content):
            ac_id = match.group(1)
            if ac_id in seen_ac_tokens:
                continue
            if ac_id in allowed_acs:
                continue
            seen_ac_tokens.add(ac_id)
            violations.append(
                ConcreteReferenceViolation(
                    token=ac_id,
                    category="ac_id",
                    message=(
                        f"Wave A handoff references acceptance-criterion "
                        f"'{ac_id}' which is not in the milestone-scoped AC "
                        "list. Cite only AC ids provided to the Wave A prompt."
                    ),
                )
            )

    # 5. Predecessor-milestone refs — `M<N>` must be self or in deps.
    # Never skipped: milestone_id is always passed and dependency_artifacts
    # defaults to {} when None is supplied.
    deps = dependency_artifacts or {}
    cumulative_blob = cumulative_architecture or ""
    self_numeric = _extract_milestone_number(milestone_id)
    allowed_milestone_numbers: set[int] = set()
    if self_numeric is not None:
        allowed_milestone_numbers.add(self_numeric)
    for key in deps.keys():
        n = _extract_milestone_number(str(key))
        if n is not None:
            allowed_milestone_numbers.add(n)
    # Also allow milestone ids that appear in the cumulative block.
    for match in _milestone_ref_re.finditer(cumulative_blob):
        try:
            allowed_milestone_numbers.add(int(match.group(1)))
        except ValueError:
            continue
    seen_milestone_tokens: set[str] = set()
    for match in _milestone_ref_re.finditer(content):
        token = match.group(0)
        if token in seen_milestone_tokens:
            continue
        try:
            n = int(match.group(1))
        except ValueError:
            continue
        if n in allowed_milestone_numbers:
            continue
        seen_milestone_tokens.add(token)
        violations.append(
            ConcreteReferenceViolation(
                token=token,
                category="milestone_ref",
                message=(
                    f"Wave A handoff references milestone '{token}' which "
                    "is neither this milestone nor a predecessor in "
                    "dependency_artifacts / cumulative ARCHITECTURE.md. "
                    "Do not describe future milestones — their context is "
                    "not available to downstream waves."
                ),
            )
        )

    return violations, skipped


def _extract_allowed_ports(stack_contract: dict[str, Any]) -> set[int]:
    """Pull port integers out of a stack-contract dict.

    Tolerant of several shapes: top-level ``ports``, nested
    ``services.*.port`` maps, and ``dod.port`` — mirrors how Wave A
    reads the contract.
    """
    result: set[int] = set()

    def _coerce(value: Any) -> None:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return
        if 1 <= n <= 65535:
            result.add(n)

    ports = stack_contract.get("ports")
    if isinstance(ports, (list, tuple, set)):
        for p in ports:
            _coerce(p)
    elif isinstance(ports, dict):
        for p in ports.values():
            _coerce(p)
    services = stack_contract.get("services")
    if isinstance(services, dict):
        for svc in services.values():
            if isinstance(svc, dict):
                _coerce(svc.get("port"))
    dod = stack_contract.get("dod")
    if isinstance(dod, dict):
        _coerce(dod.get("port"))
    _coerce(stack_contract.get("port"))
    _coerce(stack_contract.get("api_port"))
    _coerce(stack_contract.get("web_port"))
    return result


def _extract_section_bodies(
    content: str, *, canonical_targets: Iterable[str]
) -> list[str]:
    """Return the body text (no heading) of sections whose canonical
    name is in *canonical_targets*.

    Used to scope the concrete-reference scan so we don't flag e.g.
    `apps/api/src/x.ts` mentioned in an `## Open questions` discussion.
    """
    targets = set(canonical_targets)
    alias_index = _build_alias_index()
    bodies: list[str] = []
    current_canonical: str | None = None
    current_lines: list[str] = []
    for line in content.splitlines():
        heading_match = _h2_heading_re.match(line)
        if heading_match:
            if current_canonical in targets and current_lines:
                bodies.append("\n".join(current_lines))
            normalized = heading_match.group(1).strip().lower()
            current_canonical = _match_allowed(normalized, alias_index)
            current_lines = []
            continue
        current_lines.append(line)
    if current_canonical in targets and current_lines:
        bodies.append("\n".join(current_lines))
    return bodies


def _looks_like_port(port: int) -> bool:
    """Rough port-literal heuristic.

    Flags common web/API ports (3xxx/4xxx/5xxx/8xxx/9xxx) and classic
    ranges that Wave A tends to drift on. Skips obvious non-ports
    (year-like 2020–2099, large non-port integers).
    """
    if port < 1024:
        return True
    if 2020 <= port <= 2099:
        return False  # year-like
    if port > 65535:
        return False
    return True


_CAMELCASE_NOISE: frozenset[str] = frozenset(
    {
        # Framework / library names commonly mentioned in prose
        "NestJS",
        "NextJS",
        "TypeScript",
        "JavaScript",
        "PostgreSQL",
        "MongoDB",
        "PrismaClient",
        "CreateDto",
        "UpdateDto",
        "ResponseDto",
        "BaseEntity",
        "SoftDelete",
        "ReactDOM",
        "DataSource",
        "NodeJS",
        "AppModule",
        "MainModule",
        "HttpException",
        "HttpStatus",
        "PlaywrightTest",
        "VitestConfig",
        "JestConfig",
        "DockerCompose",
    }
)


def _is_common_camelcase_noise(token: str) -> bool:
    if token in _CAMELCASE_NOISE:
        return True
    # Tokens that END in Dto / Module / Service / Controller / Config
    # are framework idioms, not schema entities.
    for suffix in (
        "Dto",
        "Module",
        "Service",
        "Controller",
        "Config",
        "Resolver",
        "Guard",
        "Strategy",
        "Interceptor",
        "Filter",
        "Pipe",
        "Provider",
    ):
        if token.endswith(suffix) and len(token) > len(suffix):
            return True
    return False


def _extract_milestone_number(milestone_id: str) -> int | None:
    """Pull the numeric suffix from a milestone id like 'milestone-3'."""
    if not milestone_id:
        return None
    match = re.search(r"(\d+)$", milestone_id)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def load_scaffold_ownership_paths(cwd: str | Path) -> list[str]:
    """Parse ``docs/SCAFFOLD_OWNERSHIP.md`` and return the `path:` list.

    Returns an empty list when the file is absent or unreadable. Used
    to expand the `scaffolded_files` allowlist for the derivability
    file-path check so references to Wave-B/D-owned seams that the
    scaffolder has not yet emitted still derive cleanly.
    """
    path = Path(cwd) / "docs" / "SCAFFOLD_OWNERSHIP.md"
    try:
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "wave-a-schema: unable to read %s: %s", path, exc
        )
        return []
    paths: list[str] = []
    for match in re.finditer(r"^\s*-\s*path:\s*([^\n]+)$", text, re.MULTILINE):
        candidate = match.group(1).strip().strip('"').strip("'")
        if candidate:
            paths.append(candidate)
    return paths


def load_architecture_md(cwd: str | Path, milestone_id: str) -> tuple[str, Path]:
    """Return ``(content, path)`` for the per-milestone ARCHITECTURE.md.

    Content is empty string when the file is absent or unreadable. Path
    is the canonical location regardless of existence so callers can
    emit an "expected at …" message.

    The on-disk directory is literally ``milestone-{milestone_id}`` —
    e.g. ``milestone-milestone-1`` when ``milestone_id='milestone-1'``
    (see discovery-citations §1D).
    """
    path = Path(cwd) / ".agent-team" / f"milestone-{milestone_id}" / "ARCHITECTURE.md"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8"), path
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "wave-a-schema: unable to read %s: %s", path, exc
        )
    return "", path
