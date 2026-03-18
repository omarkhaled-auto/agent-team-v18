"""Lightweight PRD parser for v16 pipeline (Phase 2.1).

Extracts entities, state machines, and events from PRD text using
deterministic regex strategies. No LLM calls. Ported and distilled from
super-team's 2,606-line prd_parser.py into a focused ~400-line module.

The extracted domain model is used to:
- Inject entity assignments into the decomposition prompt (Phase 2.3)
- Inject entity schemas into per-milestone prompts (Phase 2.4)
- Feed the entity coverage scan for post-build verification (Phase 2.6)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedPRD:
    """Structured result from PRD parsing."""

    project_name: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    technology_hints: dict[str, str | None] = field(default_factory=dict)
    business_rules: list[BusinessRule] = field(default_factory=list)


@dataclass
class BusinessRule:
    """A domain-specific business rule extracted from the PRD."""

    id: str  # e.g., "BR-AP-001"
    service: str  # e.g., "ap"
    entity: str  # e.g., "PurchaseInvoice"
    rule_type: str  # "validation" | "computation" | "integration" | "guard"
    description: str  # Human-readable summary
    required_operations: list[str] = field(default_factory=list)  # e.g., ["multiplication", "comparison"]
    anti_patterns: list[str] = field(default_factory=list)  # e.g., ["Check only for string field existence"]
    source_line: int = 0  # PRD line number for traceability


# ---------------------------------------------------------------------------
# Stop lists (ported from super-team prd_parser.py)
# ---------------------------------------------------------------------------

_SECTION_KEYWORDS: frozenset[str] = frozenset({
    "overview", "introduction", "summary", "requirements", "description",
    "features", "architecture", "deployment", "testing", "security",
    "authentication", "authorization", "api", "endpoints", "notes",
    "glossary", "appendix", "references", "changelog", "versioning",
    "scope", "background", "goals", "constraints", "assumptions",
    "dependencies", "risks", "timeline", "milestones", "deliverables",
    "stakeholders", "user stories", "use cases", "functional requirements",
    "non-functional requirements", "acceptance criteria", "data model",
    "entities", "domain model", "entity definitions", "technology stack",
    "tech stack", "stack", "services", "bounded contexts", "context map",
    "table of contents", "revision history", "conclusion",
    "project", "prd", "relationships", "data", "configuration",
    "monitoring", "logging", "conventions", "performance",
    "data flow", "api endpoints", "service boundaries",
    "non-functional", "state machine", "state machines",
    "system overview", "project overview", "technical requirements",
    "implementation", "implementation details", "integration",
    "notifications", "error handling", "api design",
    "database design", "service architecture",
    "api contracts", "api contracts summary", "contracts summary",
    "cross-service relationships",
})

_GENERIC_SINGLE_WORDS: frozenset[str] = frozenset({
    "data", "status", "type", "state", "result", "response", "request",
    "error", "action", "config", "option", "setting",
    "value", "list", "table", "field", "key", "index", "node",
    "overview", "relationships", "requirements", "summary", "endpoints",
    "architecture", "background", "introduction", "scope", "dependencies",
    "configuration", "deployment", "testing", "security", "performance",
    "monitoring", "logging", "conventions",
    "model", "name", "description", "title", "content", "item", "items",
    "details", "info", "information", "properties", "attributes",
})

_HEADING_SUFFIXES: tuple[str, ...] = (
    "Service", "Endpoint", "Endpoints", "StateMachine", "StateMachines",
    "Overview", "Summary", "Requirements", "Architecture", "Configuration",
    "Deployment", "Integration", "API", "Database", "Schema", "Migration",
    "Router", "Controller", "Workflow", "Pipeline", "System", "Pattern",
    "Patterns", "Design", "Flow", "Diagram", "Stack", "Setup", "Management",
    "Processing", "Handling", "Operations", "Monitoring", "Logging",
)

_STATE_FIELD_NAMES: frozenset[str] = frozenset({
    "status", "state", "phase", "lifecycle", "workflow_state",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_prd(prd_text: str) -> ParsedPRD:
    """Parse a PRD and return structured entities, state machines, and events.

    Pure, deterministic function — no LLM calls. Uses regex strategies.
    """
    if not prd_text or len(prd_text.strip()) < 50:
        return ParsedPRD()

    text = prd_text.strip()
    # Ensure trailing newline for regex patterns that require \n at end of lines
    if not text.endswith("\n"):
        text += "\n"
    project_name = _extract_project_name(text)
    entities = _extract_entities(text)
    state_machines = _extract_state_machines(text, entities)
    events = _extract_events(text)
    tech_hints = _extract_technology_hints(text)
    business_rules = extract_business_rules(text, entities, state_machines)

    return ParsedPRD(
        project_name=project_name,
        entities=entities,
        state_machines=state_machines,
        events=events,
        technology_hints=tech_hints,
        business_rules=business_rules,
    )


def format_domain_model(parsed: ParsedPRD) -> str:
    """Format parsed PRD as a markdown block for prompt injection."""
    if (
        not parsed.entities
        and not parsed.state_machines
        and not parsed.events
        and not parsed.business_rules
    ):
        return ""

    lines: list[str] = ["## PRD Analysis: Extracted Domain Model\n"]

    if parsed.entities:
        lines.append(f"### Entities ({len(parsed.entities)} found)\n")
        for i, ent in enumerate(parsed.entities, 1):
            name = ent.get("name", "?")
            fields = ent.get("fields", [])
            desc = ent.get("description", "")
            field_str = ", ".join(
                f"{f['name']}({f.get('type', '?')})" for f in fields[:10]
            )
            if len(fields) > 10:
                field_str += f", ... (+{len(fields) - 10} more)"
            line = f"{i}. **{name}**"
            if field_str:
                line += f": {field_str}"
            if desc:
                line += f" — {desc[:80]}"
            lines.append(line)
        lines.append("")

    if parsed.state_machines:
        lines.append(f"### State Machines ({len(parsed.state_machines)} found)\n")
        for sm in parsed.state_machines:
            entity = sm.get("entity", "?")
            states = sm.get("states", [])
            transitions = sm.get("transitions", [])
            state_str = " → ".join(states) if states else "(no states)"
            lines.append(f"- **{entity}**: {state_str}")
            if transitions:
                for tr in transitions[:8]:
                    lines.append(
                        f"  - {tr.get('from_state', '?')} → {tr.get('to_state', '?')}"
                        f" (trigger: {tr.get('trigger', 'N/A')})"
                    )
                if len(transitions) > 8:
                    lines.append(f"  - ... (+{len(transitions) - 8} more)")
        lines.append("")

    if parsed.events:
        lines.append(f"### Events ({len(parsed.events)} found)\n")
        for ev in parsed.events:
            name = ev.get("name", "?")
            publisher = ev.get("publisher", "")
            lines.append(f"- `{name}`" + (f" (published by {publisher})" if publisher else ""))
        lines.append("")

    if parsed.business_rules:
        lines.append(f"### Business Rules ({len(parsed.business_rules)} found)\n")
        for rule in parsed.business_rules:
            types = rule.rule_type
            lines.append(
                f"- {rule.id} ({rule.entity}): {rule.description} [{types}]"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Business rule extraction
# ---------------------------------------------------------------------------

# Keywords that map to required_operations
_OPERATION_KEYWORDS: dict[str, str] = {
    "compare": "comparison",
    "comparison": "comparison",
    "versus": "comparison",
    " vs ": "comparison",
    "against": "comparison",
    "match": "comparison",
    "validate": "validation",
    "verify": "validation",
    "calculate": "computation",
    "compute": "computation",
    "multiply": "multiplication",
    "times": "multiplication",
    "×": "multiplication",
    " * ": "multiplication",
    "tolerance": "tolerance_check",
    "threshold": "tolerance_check",
    "within": "tolerance_check",
    "absolute": "absolute_value",
    "variance": "variance",
    "percentage": "percentage",
    "sum": "summation",
    "total": "summation",
}

# Default anti-patterns by rule type
_DEFAULT_ANTI_PATTERNS: dict[str, list[str]] = {
    "guard": ["Check only for field existence without comparing values"],
    "computation": ["Return hardcoded values", "Skip the calculation"],
    "integration": ["Log the event without making the service call"],
    "validation": ["Accept all input without validation"],
}


def _detect_operations(text: str) -> list[str]:
    """Detect required operations from keywords in text."""
    text_lower = text.lower()
    ops: list[str] = []
    for keyword, operation in _OPERATION_KEYWORDS.items():
        if keyword in text_lower and operation not in ops:
            ops.append(operation)
    return ops


def _normalize_service_name(raw_context: str) -> str:
    """Normalize owning_context to a bare service name.

    Strips common suffixes like ``_service``, ``_module``, ``_bounded_context``
    so that downstream lookups using bare names (``ap``, ``gl``) match.

    Examples::

        "AP Service"          -> "ap"
        "gl_service"          -> "gl"
        "General Ledger"      -> "general_ledger"
        "Accounts Payable"    -> "accounts_payable"
        "auth"                -> "auth"
    """
    name = raw_context.lower().replace(" ", "_")
    for suffix in ("_service", "_module", "_bounded_context"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name


def _build_entity_service_lookup(
    entities: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Build a lowercase entity name -> normalized service name lookup dict."""
    if not entities:
        return {}
    lookup: dict[str, str] = {}
    for ent in entities:
        name = ent.get("name", "")
        ctx = ent.get("owning_context", "")
        if name and ctx:
            lookup[name.lower()] = _normalize_service_name(ctx)
    return lookup


def _service_for_entity(
    entity_name: str,
    entities: list[dict[str, Any]] | None,
) -> str:
    """Look up the owning service/context for an entity, or return 'unknown'."""
    if not entities:
        return "unknown"
    for ent in entities:
        if ent.get("name", "").lower() == entity_name.lower():
            ctx = ent.get("owning_context", "")
            if ctx:
                return _normalize_service_name(ctx)
    return "unknown"


def _entity_names_lower(entities: list[dict[str, Any]] | None) -> dict[str, str]:
    """Return mapping of lowercase entity name to PascalCase name."""
    if not entities:
        return {}
    return {e["name"].lower(): e["name"] for e in entities if "name" in e}


def _pascal_to_spaced(name: str) -> str:
    """Convert PascalCase to space-separated lowercase: PurchaseInvoice -> purchase invoice."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).lower()


def _find_entity_in_text(
    text: str,
    entity_map: dict[str, str],
) -> str:
    """Find the first entity name mentioned in text. Return PascalCase or empty.

    Checks both the joined PascalCase form (e.g. ``purchaseinvoice``) and
    the space-separated form (e.g. ``purchase invoice``) so that natural
    prose like "AP purchase invoice 3-way matching" is matched.
    """
    text_lower = text.lower()
    # Sort by length descending so longer names match first
    for lower_name, pascal_name in sorted(
        entity_map.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        # Try exact PascalCase (joined)
        if re.search(rf"\b{re.escape(lower_name)}\b", text_lower):
            return pascal_name
        # Try space-separated form (PurchaseInvoice -> "purchase invoice")
        spaced = _pascal_to_spaced(pascal_name)
        if spaced != lower_name and re.search(rf"\b{re.escape(spaced)}\b", text_lower):
            return pascal_name
    return ""


def _build_heading_entity_ranges(
    prd_text: str,
    entity_map: dict[str, str],
) -> list[tuple[int, int, str]]:
    """Build a list of (start_line, end_line, entity_name) from section headings.

    Detects headings like "### Invoice Status State Machine" or
    "### PurchaseInvoice State Machine" and maps their line ranges to
    the entity that owns that section.  This is used by guard extraction
    to attribute guards to the correct entity based on document structure.
    """
    # Match headings that mention an entity + "State Machine" or just
    # entity names as section headings followed by transition content.
    heading_pat = re.compile(
        r"^(#{2,5})\s+(.+?)\s*$",
        re.MULTILINE,
    )
    ranges: list[tuple[int, int, str]] = []
    lines = prd_text.split("\n")
    total_lines = len(lines)

    headings: list[tuple[int, int, str]] = []  # (line_num, level, heading_text)
    for m in heading_pat.finditer(prd_text):
        level = len(m.group(1))
        heading_text = m.group(2).strip()
        # Calculate line number (1-based)
        line_num = prd_text[:m.start()].count("\n") + 1
        headings.append((line_num, level, heading_text))

    for i, (line_num, level, heading_text) in enumerate(headings):
        # Find which entity this heading is about
        # Strip "Status State Machine", "State Machine" suffixes
        cleaned = re.sub(
            r"\s+(?:Status\s+)?State\s+Machine\s*$", "", heading_text, flags=re.IGNORECASE
        ).strip()

        entity_name = ""
        # Try direct entity map lookup
        cleaned_lower = cleaned.lower()
        if cleaned_lower in entity_map:
            entity_name = entity_map[cleaned_lower]
        else:
            # Try space-separated form
            entity_name = _find_entity_in_text(cleaned, entity_map)

        if not entity_name:
            continue

        # Determine end of this section (next heading of same or higher level)
        end_line = total_lines
        for j in range(i + 1, len(headings)):
            next_line_num, next_level, _ = headings[j]
            if next_level <= level:
                end_line = next_line_num - 1
                break

        ranges.append((line_num, end_line, entity_name))

    return ranges


def _entity_from_heading_context(
    line_num: int,
    heading_ranges: list[tuple[int, int, str]],
) -> str:
    """Return the entity name from the most specific (narrowest) heading range
    that contains line_num, or empty string if none."""
    best = ""
    best_span = float("inf")
    for start, end, entity_name in heading_ranges:
        if start <= line_num <= end:
            span = end - start
            if span < best_span:
                best = entity_name
                best_span = span
    return best


def _entity_from_unique_states(
    line: str,
    state_machines: list[dict[str, Any]],
) -> str:
    """Try to identify entity from states that are UNIQUE to a single
    state machine, avoiding ambiguity from common states."""
    line_lower = line.lower()
    # Build a map of state -> list of entities that have that state
    state_owners: dict[str, list[str]] = {}
    for sm in state_machines:
        for s in sm.get("states", []):
            state_owners.setdefault(s, []).append(sm.get("entity", ""))

    # Find states mentioned in the line that are unique to one SM
    for state, owners in state_owners.items():
        if len(owners) == 1 and re.search(rf"\b{re.escape(state)}\b", line_lower):
            return owners[0]
    return ""


def extract_business_rules(
    prd_text: str,
    entities: list[dict[str, Any]] | None = None,
    state_machines: list[dict[str, Any]] | None = None,
) -> list[BusinessRule]:
    """Extract business rules from PRD text using multiple strategies.

    Strategies:
    1. Guard conditions from state machine transitions
    2. Business flow sections (Procure-to-Pay, Order-to-Cash, etc.)
    3. Acceptance criteria
    4. Explicit formulas and tolerances

    Returns a deduplicated list of BusinessRule instances.
    """
    if not prd_text or len(prd_text.strip()) < 50:
        return []

    rules: list[BusinessRule] = []
    lines = prd_text.split("\n")
    entity_map = _entity_names_lower(entities)
    counters: dict[str, int] = {}  # service -> counter for ID generation

    def _next_id(service: str) -> str:
        svc = service.upper() if service != "unknown" else "GEN"
        counters.setdefault(svc, 0)
        counters[svc] += 1
        return f"BR-{svc}-{counters[svc]:03d}"

    # ------------------------------------------------------------------
    # Strategy 1: Guard conditions from state machine transitions
    # ------------------------------------------------------------------
    # Pattern A: table rows with "guard:" in a column
    guard_table_pat = re.compile(
        r"^\s*\|[^|]*\|[^|]*\|[^|]*guard:\s*(.+?)(?:\s*\|)",
        re.IGNORECASE,
    )
    # Pattern B: "guard:" on any line (not necessarily a table)
    guard_line_pat = re.compile(
        r"guard:\s*(.+)",
        re.IGNORECASE,
    )

    # Build entity->service lookup for fast attribution
    entity_svc_lookup = _build_entity_service_lookup(entities)

    # Build a line-number to heading-entity mapping.
    # This determines which state machine section a guard line falls in,
    # so attribution is based on the state machine OWNER, not entities
    # mentioned in the guard condition text.
    heading_entity_ranges = _build_heading_entity_ranges(prd_text, entity_map)

    for line_num, line in enumerate(lines, 1):
        condition = ""
        # Check table guard pattern first
        m = guard_table_pat.search(line)
        if m:
            condition = m.group(1).strip().rstrip("|").strip()
        elif "guard:" in line.lower():
            m2 = guard_line_pat.search(line)
            if m2:
                condition = m2.group(1).strip().rstrip("|").strip()

        if not condition:
            continue

        # Determine entity from surrounding heading context first.
        # This avoids misattribution when guard text mentions entities
        # (like JournalEntry) that belong to different services.
        entity = _entity_from_heading_context(line_num, heading_entity_ranges)

        # Fallback: try state machine transition matching
        if not entity and state_machines:
            # Use only UNIQUE states that belong to a single state machine,
            # to avoid ambiguity from common states like "draft", "approved"
            entity = _entity_from_unique_states(line, state_machines)

        if not entity:
            entity = _find_entity_in_text(line, entity_map) or "Unknown"

        # Service attribution: use the state machine entity's owning
        # service, NOT entities mentioned in the guard condition text.
        service = entity_svc_lookup.get(entity.lower(), "unknown")
        if service == "unknown":
            service = _service_for_entity(entity, entities)
        ops = _detect_operations(condition)
        rules.append(BusinessRule(
            id=_next_id(service),
            service=service,
            entity=entity,
            rule_type="guard",
            description=condition,
            required_operations=ops,
            anti_patterns=list(_DEFAULT_ANTI_PATTERNS["guard"]),
            source_line=line_num,
        ))

    # ------------------------------------------------------------------
    # Strategy 2: Business flow sections
    # ------------------------------------------------------------------
    flow_heading_pat = re.compile(
        r"^#{1,5}\s+.*(?:Flow|Process|Workflow|Lifecycle)\b.*$",
        re.IGNORECASE | re.MULTILINE,
    )
    # Patterns for system action steps
    system_action_pat = re.compile(
        r"^\s*\d+[\.\)]\s+(?:System\s+)?(?:performs?|validates?|calculates?|creates?|generates?|sends?|verifies?)\s+(.+)",
        re.IGNORECASE,
    )

    for heading_match in flow_heading_pat.finditer(prd_text):
        heading_start = heading_match.end()
        # Find the end of this section (next heading of same or higher level)
        heading_level = len(re.match(r"^(#+)", heading_match.group()).group(1))
        next_heading = re.search(
            rf"^#{{1,{heading_level}}}\s+",
            prd_text[heading_start:],
            re.MULTILINE,
        )
        section_end = heading_start + next_heading.start() if next_heading else len(prd_text)
        section_text = prd_text[heading_start:section_end]

        for step_line in section_text.split("\n"):
            sm = system_action_pat.match(step_line)
            if not sm:
                continue
            action_text = sm.group(1).strip()
            # Determine rule_type from action verb
            step_lower = step_line.lower()
            if any(w in step_lower for w in ("creates", "journal", "dr", "cr", "debit", "credit")):
                rule_type = "integration"
            elif any(w in step_lower for w in ("calculates", "compute")):
                rule_type = "computation"
            elif any(w in step_lower for w in ("validates", "verifies", "matching")):
                rule_type = "validation"
            else:
                rule_type = "computation"

            entity = _find_entity_in_text(step_line, entity_map) or "Unknown"
            service = _service_for_entity(entity, entities)
            ops = _detect_operations(action_text)

            # Calculate the actual line number in the original text
            line_offset = prd_text[:heading_start].count("\n")
            step_line_num = line_offset + section_text[:section_text.index(step_line.rstrip("\n")) if step_line.rstrip("\n") in section_text else 0].count("\n") + 1

            rules.append(BusinessRule(
                id=_next_id(service),
                service=service,
                entity=entity,
                rule_type=rule_type,
                description=action_text,
                required_operations=ops,
                anti_patterns=list(_DEFAULT_ANTI_PATTERNS.get(rule_type, [])),
                source_line=step_line_num,
            ))

    # ------------------------------------------------------------------
    # Strategy 3: Acceptance criteria
    # ------------------------------------------------------------------
    ac_heading_pat = re.compile(
        r"^#{1,5}\s+(?:Acceptance\s+(?:Criteria|Tests))\b.*$",
        re.IGNORECASE | re.MULTILINE,
    )
    ac_item_pat = re.compile(
        r"^\s*(?:\d+[\.\)]|[-*]|AC-\d+:?)\s+(.+)",
        re.IGNORECASE,
    )
    ac_action_words = re.compile(
        r"\b(?:validate[sd]?|compare[sd]?|calculate[sd]?|match(?:es|ing)?|verif(?:y|ies)|check[sd]?)\b",
        re.IGNORECASE,
    )

    for heading_match in ac_heading_pat.finditer(prd_text):
        heading_start = heading_match.end()
        heading_level = len(re.match(r"^(#+)", heading_match.group()).group(1))
        next_heading = re.search(
            rf"^#{{1,{heading_level}}}\s+",
            prd_text[heading_start:],
            re.MULTILINE,
        )
        section_end = heading_start + next_heading.start() if next_heading else len(prd_text)
        section_text = prd_text[heading_start:section_end]

        for ac_line in section_text.split("\n"):
            am = ac_item_pat.match(ac_line)
            if not am:
                continue
            criterion_text = am.group(1).strip()
            # Only accept if it mentions an entity and an action verb
            entity = _find_entity_in_text(ac_line, entity_map)
            if not entity:
                # Also try matching without entity map — look for capitalized words
                continue
            if not ac_action_words.search(ac_line):
                continue

            service = _service_for_entity(entity, entities)
            ops = _detect_operations(criterion_text)

            line_offset = prd_text[:heading_start].count("\n")
            ac_line_num = line_offset + section_text[:section_text.index(ac_line.rstrip("\n")) if ac_line.rstrip("\n") in section_text else 0].count("\n") + 1

            rules.append(BusinessRule(
                id=_next_id(service),
                service=service,
                entity=entity,
                rule_type="validation",
                description=criterion_text,
                required_operations=ops,
                anti_patterns=list(_DEFAULT_ANTI_PATTERNS["validation"]),
                source_line=ac_line_num,
            ))

    # ------------------------------------------------------------------
    # Strategy 4: Explicit formulas and tolerances
    # ------------------------------------------------------------------
    tolerance_pat = re.compile(
        r"(?:configurable\s+)?(?:tolerance|threshold)\s*"
        r"(?:\(?\s*(?:default\s+)?\d+[\.\d]*\s*%?\s*\)?)?",
        re.IGNORECASE,
    )
    formula_pats = [
        # "X times Y" or "X * Y" or "X × Y"
        (re.compile(r"\b(\w+)\s+(?:times|×|\*)\s+(\w+)", re.IGNORECASE), "multiplication"),
        # "compare X against Y" or "X versus Y" or "X vs Y"
        (re.compile(r"\b(?:compare\s+.+?\s+(?:against|with|to)|(?:\w+)\s+(?:versus|vs\.?)\s+\w+)", re.IGNORECASE), "comparison"),
    ]

    for line_num, line in enumerate(lines, 1):
        line_lower = line.lower()
        # Tolerance / threshold detection
        if tolerance_pat.search(line) and ("tolerance" in line_lower or "threshold" in line_lower):
            entity = _find_entity_in_text(line, entity_map)
            if not entity:
                # Look at surrounding context (prev/next 3 lines) for entity
                for offset in range(1, 4):
                    if line_num - 1 - offset >= 0:
                        entity = _find_entity_in_text(lines[line_num - 1 - offset], entity_map)
                        if entity:
                            break
                    if line_num - 1 + offset < len(lines):
                        entity = _find_entity_in_text(lines[line_num - 1 + offset], entity_map)
                        if entity:
                            break
            if not entity:
                entity = "Unknown"
            service = _service_for_entity(entity, entities)
            ops = _detect_operations(line)
            if "comparison" not in ops:
                ops.append("comparison")
            if "tolerance_check" not in ops:
                ops.append("tolerance_check")

            # Avoid creating a rule if we already have one with the same
            # entity and very similar description from strategies 1-3
            desc = line.strip()
            if not _is_duplicate(rules, entity, desc):
                rules.append(BusinessRule(
                    id=_next_id(service),
                    service=service,
                    entity=entity,
                    rule_type="validation",
                    description=desc,
                    required_operations=ops,
                    anti_patterns=list(_DEFAULT_ANTI_PATTERNS["validation"]),
                    source_line=line_num,
                ))

        # Formula detection
        for pat, op_name in formula_pats:
            if pat.search(line):
                entity = _find_entity_in_text(line, entity_map)
                if not entity:
                    continue
                service = _service_for_entity(entity, entities)
                ops = _detect_operations(line)
                if op_name not in ops:
                    ops.append(op_name)
                desc = line.strip()
                if not _is_duplicate(rules, entity, desc):
                    rule_type = "computation" if op_name == "multiplication" else "validation"
                    rules.append(BusinessRule(
                        id=_next_id(service),
                        service=service,
                        entity=entity,
                        rule_type=rule_type,
                        description=desc,
                        required_operations=ops,
                        anti_patterns=list(_DEFAULT_ANTI_PATTERNS.get(rule_type, [])),
                        source_line=line_num,
                    ))

    # ------------------------------------------------------------------
    # Strategy 5: Accounting integration rules (subledger -> GL patterns)
    # These are implicit in accounting PRDs but rarely stated as explicit
    # rules.  We scan for GL journal creation actions near state
    # transitions and for debit/credit patterns linked to entities.
    # ------------------------------------------------------------------
    _gl_action_pat = re.compile(
        r"(?:create[sd]?\s+(?:a\s+)?(?:GL\s+)?journal\s+entr(?:y|ies)"
        r"|post(?:s|ed|ing)?\s+(?:to\s+)?(?:the\s+)?GL"
        r"|create[sd]?\s+(?:a\s+)?journal"
        r"|generate[sd]?\s+(?:a\s+)?(?:GL\s+)?journal)",
        re.IGNORECASE,
    )
    _debit_credit_pat = re.compile(
        r"\b(?:debit|credit|DR|CR)\b",
        re.IGNORECASE,
    )
    _subledger_gl_pat = re.compile(
        r"subledger.{0,30}(?:GL|general\s+ledger)"
        r"|(?:GL|general\s+ledger).{0,30}subledger",
        re.IGNORECASE,
    )

    for line_num, line in enumerate(lines, 1):
        # Check for GL journal creation actions
        gl_match = _gl_action_pat.search(line)
        if not gl_match:
            # Also check for debit/credit near entity names
            if _debit_credit_pat.search(line):
                entity = _find_entity_in_text(line, entity_map)
                if not entity:
                    # Check surrounding lines for entity context
                    for offset in range(1, 4):
                        if line_num - 1 - offset >= 0:
                            entity = _find_entity_in_text(
                                lines[line_num - 1 - offset], entity_map
                            )
                            if entity:
                                break
                        if line_num - 1 + offset < len(lines):
                            entity = _find_entity_in_text(
                                lines[line_num - 1 + offset], entity_map
                            )
                            if entity:
                                break
                if entity:
                    service = _service_for_entity(entity, entities)
                    desc = (
                        f"When {entity} state changes, create GL journal "
                        f"entry: {line.strip()}"
                    )
                    if not _is_duplicate(
                        rules, entity, desc
                    ) and not _is_duplicate(rules, entity, line.strip()):
                        rules.append(BusinessRule(
                            id=_next_id(service),
                            service=service,
                            entity=entity,
                            rule_type="integration",
                            description=desc,
                            required_operations=["http_call", "db_write"],
                            anti_patterns=list(
                                _DEFAULT_ANTI_PATTERNS["integration"]
                            ),
                            source_line=line_num,
                        ))
            # Check for subledger-GL linkage
            if _subledger_gl_pat.search(line):
                entity = _find_entity_in_text(line, entity_map)
                if entity:
                    service = _service_for_entity(entity, entities)
                    desc = f"Subledger-to-GL integration: {line.strip()}"
                    if not _is_duplicate(rules, entity, desc):
                        rules.append(BusinessRule(
                            id=_next_id(service),
                            service=service,
                            entity=entity,
                            rule_type="integration",
                            description=desc,
                            required_operations=["http_call"],
                            anti_patterns=list(
                                _DEFAULT_ANTI_PATTERNS["integration"]
                            ),
                            source_line=line_num,
                        ))
            continue

        # GL journal creation action found
        entity = _find_entity_in_text(line, entity_map)
        if not entity:
            # Check surrounding lines for entity context
            for offset in range(1, 6):
                if line_num - 1 - offset >= 0:
                    entity = _find_entity_in_text(
                        lines[line_num - 1 - offset], entity_map
                    )
                    if entity:
                        break
                if line_num - 1 + offset < len(lines):
                    entity = _find_entity_in_text(
                        lines[line_num - 1 + offset], entity_map
                    )
                    if entity:
                        break
        if not entity:
            entity = "Unknown"

        service = _service_for_entity(entity, entities)
        desc = line.strip()
        if not _is_duplicate(rules, entity, desc):
            rules.append(BusinessRule(
                id=_next_id(service),
                service=service,
                entity=entity,
                rule_type="integration",
                description=desc,
                required_operations=["http_call", "db_write"],
                anti_patterns=list(_DEFAULT_ANTI_PATTERNS["integration"]),
                source_line=line_num,
            ))

    # ------------------------------------------------------------------
    # Strategy 5b: Auto-post rule for accounting PRDs
    # If the PRD mentions "journal entry" AND any state machine has a
    # "posted" state, add a GL auto-post rule.
    # ------------------------------------------------------------------
    prd_lower = prd_text.lower()
    has_journal_entry_mention = bool(
        re.search(r"journal\s+entr(?:y|ies)", prd_lower)
    )
    has_posted_state = False
    if state_machines:
        for sm_item in state_machines:
            for st in sm_item.get("states", []):
                if st.lower().strip() == "posted":
                    has_posted_state = True
                    break
            if not has_posted_state:
                for tr in sm_item.get("transitions", []):
                    if tr.get("to_state", "").lower().strip() == "posted":
                        has_posted_state = True
                        break
            if has_posted_state:
                break

    if has_journal_entry_mention and has_posted_state:
        # Determine the gl_service name from entities
        gl_service = "unknown"
        if entities:
            for ent in entities:
                name_lower = ent.get("name", "").lower()
                if name_lower in (
                    "journalentry", "journal_entry", "glentry",
                ):
                    ctx = ent.get("owning_context", "")
                    if ctx:
                        gl_service = _normalize_service_name(ctx)
                    break
        if gl_service == "unknown" and entities:
            # Try to find a GL-related service from entity ownership
            for ent in entities:
                ctx = ent.get("owning_context", "")
                if ctx:
                    normalized = _normalize_service_name(ctx)
                    if "gl" in normalized or "general_ledger" in normalized or "ledger" in normalized:
                        gl_service = normalized
                        break

        rules.append(BusinessRule(
            id="BR-GL-AUTO",
            service=gl_service,
            entity="JournalEntry",
            rule_type="integration",
            description=(
                "System-originated journal entries (from subledger events) "
                "must be created in posted status or auto-posted after "
                "creation. Manual journals follow "
                "draft\u2192submitted\u2192approved\u2192posted flow."
            ),
            required_operations=["http_call"],
            anti_patterns=[
                "Create all journals as draft regardless of source",
            ],
            source_line=0,
        ))

    # ------------------------------------------------------------------
    # Filter garbage rules, then deduplicate
    # ------------------------------------------------------------------
    rules = _filter_garbage_rules(rules)

    # A5: Attribute remaining "unknown" service rules by keyword matching
    _SERVICE_KEYWORDS: dict[str, list[str]] = {
        "intercompany": ["intercompany", "mirror", "elimination", "subsidiary", "ic_"],
        "auth": ["approval", "segregation", "rbac", "permission", "jwt", "role"],
        "gl": ["journal", "ledger", "fiscal", "period", "posting", "debit", "credit"],
        "ar": ["invoice", "receivable", "customer", "payment_applied", "dunning"],
        "ap": ["payable", "vendor", "purchase", "3-way", "matching"],
        "banking": ["reconciliation", "bank", "cash_position"],
        "asset": ["depreciation", "fixed_asset", "disposal"],
        "tax": ["tax", "withholding", "vat"],
        "reporting": ["report", "budget", "consolidation", "dashboard"],
    }
    for rule in rules:
        if rule.service == "unknown":
            desc_lower = rule.description.lower()
            for svc, keywords in _SERVICE_KEYWORDS.items():
                if any(kw in desc_lower for kw in keywords):
                    rule.service = svc
                    break

    return _deduplicate_rules(rules)


# Regex for detecting field type annotations typical of entity definitions
_FIELD_TYPE_ANNOTATION_PAT = re.compile(
    r"\(\s*(?:UUID|str|int|bool|float|decimal|datetime|JSONB|text)\s*\)",
    re.IGNORECASE,
)


def _filter_garbage_rules(rules: list[BusinessRule]) -> list[BusinessRule]:
    """Remove rules that are not real business rules (entity defs, tables, UI specs)."""
    filtered: list[BusinessRule] = []
    for rule in rules:
        desc = rule.description
        # Too long — likely ingested table rows or page specs
        if len(desc) > 300:
            continue
        # Contains field type annotations like (UUID), (str), (int) etc.
        if _FIELD_TYPE_ANNOTATION_PAT.search(desc):
            continue
        # Contains markdown table pipe — ingested table row
        if "| " in desc:
            continue
        # Starts with state machine transition notation (e.g., "- sent → written_off:")
        # These are full transition lines swallowed by tolerance/formula patterns
        if re.match(r"^\s*-\s+\S+\s*[\u2192→\->]+\s+\S+", desc):
            continue
        filtered.append(rule)
    return filtered


def _normalize_for_dedup(text: str) -> set[str]:
    """Normalize a description to a set of words for overlap comparison."""
    # Lowercase, remove punctuation, split into words
    text_lower = re.sub(r"[^\w\s]", "", text.lower())
    return set(text_lower.split())


def _word_overlap_ratio(words_a: set[str], words_b: set[str]) -> float:
    """Return the fraction of overlapping words relative to the smaller set."""
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    # Use the smaller set as denominator so partial containment is detected
    return overlap / min(len(words_a), len(words_b))


def _is_duplicate(
    existing_rules: list[BusinessRule], entity: str, description: str
) -> bool:
    """Check if a rule with the same entity and similar description exists.

    Two rules are considered duplicates if they share the same entity AND
    their descriptions have >60% word overlap.
    """
    desc_words = _normalize_for_dedup(description)
    for rule in existing_rules:
        if rule.entity.lower() == entity.lower():
            existing_words = _normalize_for_dedup(rule.description)
            if _word_overlap_ratio(desc_words, existing_words) > 0.60:
                return True
    return False


def _deduplicate_rules(rules: list[BusinessRule]) -> list[BusinessRule]:
    """Remove duplicate rules (same entity + >60% word overlap in description).

    When deduplicating, keep the rule with the most specific
    required_operations list. If tied, keep the one with the earliest
    source_line (most authoritative position in PRD).
    """
    kept: list[BusinessRule] = []
    for rule in rules:
        desc_words = _normalize_for_dedup(rule.description)
        duplicate_idx = -1
        for i, existing in enumerate(kept):
            if existing.entity.lower() == rule.entity.lower():
                existing_words = _normalize_for_dedup(existing.description)
                if _word_overlap_ratio(desc_words, existing_words) > 0.60:
                    duplicate_idx = i
                    break
        if duplicate_idx < 0:
            kept.append(rule)
        else:
            # Decide which to keep: more required_operations wins;
            # if tied, earlier source_line wins
            existing = kept[duplicate_idx]
            rule_ops = len(rule.required_operations)
            existing_ops = len(existing.required_operations)
            if rule_ops > existing_ops or (
                rule_ops == existing_ops and rule.source_line < existing.source_line
            ):
                kept[duplicate_idx] = rule
    return kept


# ---------------------------------------------------------------------------
# Project name extraction
# ---------------------------------------------------------------------------

def _extract_project_name(text: str) -> str:
    """Extract project name from first heading or title pattern."""
    # Pattern 1: # Project: <name> or # PRD: <name>
    m = re.search(r"^#\s+(?:Project|PRD|Product):\s*(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Pattern 2: First # heading
    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Pattern 3: First non-empty line
    for line in text.split("\n"):
        line = line.strip()
        if line and not line.startswith("---"):
            return line[:100]
    return "Unknown Project"


# ---------------------------------------------------------------------------
# Entity extraction (multi-strategy)
# ---------------------------------------------------------------------------

def _is_section_heading(name: str) -> bool:
    """Return True if name looks like a section heading, not an entity."""
    norm = name.strip().lower()
    if norm in _SECTION_KEYWORDS:
        return True
    if " " not in norm and norm in _GENERIC_SINGLE_WORDS:
        return True
    stripped = re.sub(r"^\d+[\.\d]*\s*", "", name).strip()
    if stripped.lower() in _SECTION_KEYWORDS:
        return True
    pascal = _to_pascal(stripped)
    if any(pascal.endswith(sfx) for sfx in _HEADING_SUFFIXES):
        return True
    return False


def _to_pascal(name: str) -> str:
    """Convert name to PascalCase."""
    if not name:
        return ""
    name = name.strip().strip("`*_")
    if re.match(r"^[A-Z][a-zA-Z0-9]*$", name):
        return name
    words = re.split(r"[\s_\-]+", name)
    return "".join(w.capitalize() for w in words if w)


def _extract_entities(text: str) -> list[dict[str, Any]]:
    """Extract entities using multiple strategies with deduplication."""
    entities: dict[str, dict[str, Any]] = {}

    # Strategy 1: Authoritative entity table
    auth_entities = _extract_from_authoritative_table(text)
    if len(auth_entities) >= 3:
        return auth_entities

    # Strategy 2: Markdown tables with Entity column
    for ent in _extract_from_entity_tables(text):
        key = ent["name"].lower()
        entities.setdefault(key, ent)

    # Strategy 3: Heading + bullet list fields
    for ent in _extract_from_headings(text):
        key = ent["name"].lower()
        if key in entities:
            _merge_entity(entities[key], ent)
        else:
            entities[key] = ent

    # Strategy 4: Prose patterns
    for ent in _extract_from_prose(text):
        key = ent["name"].lower()
        if key in entities:
            _merge_entity(entities[key], ent)
        else:
            entities[key] = ent

    return list(entities.values())


def _merge_entity(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge incoming entity data into existing."""
    if not existing.get("description") and incoming.get("description"):
        existing["description"] = incoming["description"]
    existing_names = {f["name"] for f in existing.get("fields", [])}
    for f in incoming.get("fields", []):
        if f["name"] not in existing_names:
            existing.setdefault("fields", []).append(f)
            existing_names.add(f["name"])
    if not existing.get("owning_context") and incoming.get("owning_context"):
        existing["owning_context"] = incoming["owning_context"]


# Strategy 1: Authoritative table
def _extract_from_authoritative_table(text: str) -> list[dict[str, Any]]:
    """Extract from tables with Entity + Owning Service/Fields columns."""
    entities: list[dict[str, Any]] = []
    # Find markdown tables
    table_pat = re.compile(
        r"^\s*\|(.+)\|\s*\n\s*\|[\s\-:|]+\|\s*\n((?:\s*\|.+\|\s*\n)+)",
        re.MULTILINE,
    )
    for m in table_pat.finditer(text):
        header = [h.strip().lower() for h in m.group(1).split("|")]
        if "entity" not in header:
            continue
        has_qualifier = any(
            kw in h for h in header
            for kw in ("owning", "service", "fields", "referenced")
        )
        if not has_qualifier:
            continue

        ent_idx = header.index("entity")
        desc_idx = next((i for i, h in enumerate(header) if "desc" in h), -1)
        field_idx = next((i for i, h in enumerate(header) if "field" in h), -1)
        owner_idx = next(
            (i for i, h in enumerate(header) if "owning" in h or "service" in h), -1
        )

        for row_line in m.group(2).strip().split("\n"):
            cols = [c.strip() for c in row_line.strip("|").split("|")]
            if len(cols) <= ent_idx:
                continue
            name = cols[ent_idx].strip().strip("`*")
            if not name or _is_section_heading(name):
                continue
            ent: dict[str, Any] = {"name": _to_pascal(name), "fields": [], "description": ""}
            if desc_idx >= 0 and desc_idx < len(cols):
                ent["description"] = cols[desc_idx].strip()
            if field_idx >= 0 and field_idx < len(cols):
                ent["fields"] = _fields_from_csv(cols[field_idx])
            if owner_idx >= 0 and owner_idx < len(cols):
                ent["owning_context"] = cols[owner_idx].strip()
            entities.append(ent)

    return entities


# Strategy 2: Entity tables
def _extract_from_entity_tables(text: str) -> list[dict[str, Any]]:
    """Extract entities from Markdown tables with Entity/Description columns."""
    entities: list[dict[str, Any]] = []
    table_pat = re.compile(
        r"^\s*\|(.+)\|\s*\n\s*\|[\s\-:|]+\|\s*\n((?:\s*\|.+\|\s*\n)+)",
        re.MULTILINE,
    )
    for m in table_pat.finditer(text):
        header = [h.strip().lower() for h in m.group(1).split("|")]
        if "entity" not in header and "name" not in header:
            continue

        name_idx = header.index("entity") if "entity" in header else header.index("name")
        desc_idx = next((i for i, h in enumerate(header) if "desc" in h), -1)

        for row_line in m.group(2).strip().split("\n"):
            cols = [c.strip() for c in row_line.strip("|").split("|")]
            if len(cols) <= name_idx:
                continue
            name = cols[name_idx].strip().strip("`*")
            if not name or _is_section_heading(name):
                continue
            ent: dict[str, Any] = {"name": _to_pascal(name), "fields": [], "description": ""}
            if desc_idx >= 0 and desc_idx < len(cols):
                ent["description"] = cols[desc_idx].strip()
            entities.append(ent)

    return entities


# Strategy 3: Heading + bullet fields
_HEADING_ENTITY_PAT = re.compile(
    r"^#{2,4}\s+(.+?)\s*\n((?:\s*[-*]\s+.+\n)*)",
    re.MULTILINE,
)

_FIELD_BULLET_PAT = re.compile(
    r"^\s*[-*]\s+`?(\w+)`?\s*[:\-]\s*(.+)",
)


def _extract_from_headings(text: str) -> list[dict[str, Any]]:
    """Extract entities from headings followed by bullet-list fields."""
    entities: list[dict[str, Any]] = []
    for m in _HEADING_ENTITY_PAT.finditer(text):
        name = m.group(1).strip().strip("`*")
        # Remove leading numbers
        name = re.sub(r"^\d+[\.\d]*\s*", "", name).strip()
        if not name or _is_section_heading(name):
            continue
        # Skip if name ends with infrastructure suffix
        if any(name.endswith(f" {sfx}") or name == sfx for sfx in (
            "Service", "Endpoint", "API", "Controller", "Router",
        )):
            continue

        body = m.group(2)
        fields: list[dict[str, Any]] = []
        desc = ""
        for line in body.split("\n"):
            fm = _FIELD_BULLET_PAT.match(line)
            if fm:
                fname = fm.group(1)
                ftype = _infer_type(fm.group(2).strip())
                fields.append({"name": fname, "type": ftype, "required": True})
            elif not desc and line.strip() and not line.strip().startswith("-"):
                desc = line.strip()

        if fields:  # Only accept as entity if it has field definitions
            entities.append({
                "name": _to_pascal(name),
                "fields": fields,
                "description": desc,
            })

    return entities


# Strategy 4: Prose patterns
_PROSE_ENTITY_PAT = re.compile(
    r"(?:system|application|platform)\s+(?:manages?|tracks?|stores?|contains?)\s+"
    r"(\w+(?:\s+\w+)?)\s+(?:which|that|with)\s+(?:has|have|contains?)\s+"
    r"([\w,\s]+)",
    re.IGNORECASE,
)


def _extract_from_prose(text: str) -> list[dict[str, Any]]:
    """Extract entities from prose descriptions."""
    entities: list[dict[str, Any]] = []
    for m in _PROSE_ENTITY_PAT.finditer(text):
        name = m.group(1).strip()
        if _is_section_heading(name):
            continue
        field_names = [f.strip() for f in m.group(2).split(",") if f.strip()]
        fields = [{"name": fn, "type": "string", "required": True} for fn in field_names[:15]]
        entities.append({
            "name": _to_pascal(name),
            "fields": fields,
            "description": "",
        })
    return entities


# ---------------------------------------------------------------------------
# State machine extraction
# ---------------------------------------------------------------------------

def _extract_state_machines(
    text: str, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract state machines using multiple strategies."""
    machines: list[dict[str, Any]] = []

    # Strategy 1: Status fields with enum values nearby
    for entity in entities:
        for fld in entity.get("fields", []):
            if fld["name"] in _STATE_FIELD_NAMES:
                states = _find_enum_values(text, entity["name"])
                if len(states) >= 2:
                    transitions = _infer_linear_transitions(states)
                    machines.append({
                        "entity": entity["name"],
                        "states": states,
                        "transitions": transitions,
                    })

    # Strategy 2: Explicit transition prose
    trans_pat = re.compile(
        r"\b([A-Z][A-Za-z]+)\s+transitions?\s+from\s+[\"']?(\w+)[\"']?\s+to\s+[\"']?(\w+)[\"']?",
        re.IGNORECASE,
    )
    for m in trans_pat.finditer(text):
        entity_name = _to_pascal(m.group(1))
        from_s = m.group(2).lower()
        to_s = m.group(3).lower()
        machine = _find_or_create_machine(machines, entity_name)
        _add_state(machine, from_s)
        _add_state(machine, to_s)
        machine["transitions"].append({
            "from_state": from_s, "to_state": to_s,
            "trigger": f"{from_s}_to_{to_s}",
        })

    # Strategy 3: Arrow notation
    arrow_pat = re.compile(
        r"\b([A-Z][A-Za-z]+)\s*(?:status|state|lifecycle|workflow)\s*"
        r"[:\-]\s*([\w]+(?:\s*(?:->|-->|=>|,)\s*[\w]+)+)",
        re.IGNORECASE,
    )
    for m in arrow_pat.finditer(text):
        entity_name = _to_pascal(m.group(1))
        raw_states = re.split(r"\s*(?:->|-->|=>|,)\s*", m.group(2))
        states = [s.strip().lower() for s in raw_states if s.strip()]
        if len(states) >= 2:
            machine = _find_or_create_machine(machines, entity_name)
            for s in states:
                _add_state(machine, s)
            for i in range(len(states) - 1):
                machine["transitions"].append({
                    "from_state": states[i], "to_state": states[i + 1],
                    "trigger": f"{states[i]}_to_{states[i + 1]}",
                })

    # Strategy 4: DISABLED — replaced by Strategy 5 which parses the same
    # heading-separated sections without the catastrophic backtracking regex
    # `((?:(?!^#{1,5}\s).*\n)*)`. Strategy 5 uses separate heading + body
    # regexes that are O(n) safe. See SIM 20 P1 bug report.

    # Strategy 5: Structured transitions under **Transitions:** heading
    # Parses: "- from → to: trigger (guard: condition)"
    # This is the format used in GlobalBooks and similar PRDs.
    trans_section_pat = re.compile(
        r"\*\*Transitions:\*\*\s*\n((?:\s*-\s+.+\n)*)",
        re.MULTILINE,
    )
    # Also capture the entity from a preceding heading or **States:** line
    states_line_pat = re.compile(
        r"(?:^#{2,5}\s+(\w[\w\s]*?)(?:\s+(?:Status\s+)?State\s+Machine))"
        r"|(?:\*\*States:\*\*)",
        re.MULTILINE | re.IGNORECASE,
    )
    structured_trans_pat = re.compile(
        r"-\s+(\w+)\s*(?:\u2192|->|-->|=>)\s*(\w+)\s*:\s*(\w+)"
        r"(?:\s*\(guard:\s*(.+?)\))?"
        r"(?:\s*\((.+?)\))?",
        re.IGNORECASE,
    )

    # Find all state machine sections by heading
    sm_heading_pat = re.compile(
        r"^#{2,5}\s+([\w\s]+?)(?:\s+(?:Status\s+)?State\s+Machine)\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    for hm in sm_heading_pat.finditer(text):
        entity_name = _to_pascal(hm.group(1).strip())
        # Get section body until next heading
        section_start = hm.end()
        next_heading = re.search(r"^#{2,5}\s", text[section_start:], re.MULTILINE)
        section_end = section_start + next_heading.start() if next_heading else len(text)
        section_body = text[section_start:section_end]

        # First try chained arrows in body: "draft -> submitted -> approved"
        chain_pat = re.compile(r"([\w]+(?:\s*(?:->|-->|=>)\s*[\w]+)+)")
        for chain_match in chain_pat.finditer(section_body):
            raw_states = re.split(r"\s*(?:->|-->|=>)\s*", chain_match.group(0))
            chain_states = [s.strip().lower() for s in raw_states if s.strip()]
            if len(chain_states) >= 2:
                machine = _find_or_create_machine(machines, entity_name)
                for s in chain_states:
                    _add_state(machine, s)
                for i in range(len(chain_states) - 1):
                    machine["transitions"].append({
                        "from_state": chain_states[i],
                        "to_state": chain_states[i + 1],
                        "trigger": f"{chain_states[i]}_to_{chain_states[i + 1]}",
                    })

        # Parse **Transitions:** block within this section (overrides chain arrows)
        trans_block = trans_section_pat.search(section_body)
        if not trans_block:
            continue

        machine = _find_or_create_machine(machines, entity_name)
        for tm in structured_trans_pat.finditer(trans_block.group(1)):
            from_s = _normalize_state_name(tm.group(1))
            to_s = _normalize_state_name(tm.group(2))
            trigger = tm.group(3)
            guard = tm.group(4) or tm.group(5) or ""

            _add_state(machine, from_s)
            _add_state(machine, to_s)

            # Check for duplicate transition — update if exists (add guard/trigger)
            existing = [
                t for t in machine["transitions"]
                if _normalize_state_name(t.get("from_state", "")) == from_s
                and _normalize_state_name(t.get("to_state", "")) == to_s
            ]
            if existing:
                # Update with richer data (trigger name, guard condition)
                existing[0]["trigger"] = trigger
                if guard and guard.strip():
                    existing[0]["guard"] = guard.strip()
            else:
                machine["transitions"].append({
                    "from_state": from_s,
                    "to_state": to_s,
                    "trigger": trigger,
                    "guard": guard.strip() if guard else "",
                })

    # Deduplicate: strip "Status" suffix, keep machine with most transitions
    return _deduplicate_machines(machines)


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------

def _extract_events(text: str) -> list[dict[str, Any]]:
    """Extract events from explicit sections and prose patterns."""
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Strategy 1: Event sections (## Events, ## Domain Events, etc.)
    section_pat = re.compile(
        r"^#{1,4}\s+(?:Domain\s+)?Events?\s*(?:Architecture|Communication|Driven)?\s*\n"
        r"((?:(?!^#{1,3}\s).*\n)*)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in section_pat.finditer(text):
        body = m.group(1)
        # Look for event names in the body
        event_name_pat = re.compile(
            r"`?(\w+\.\w+\.\w+)`?",  # domain.entity.action pattern
        )
        for em in event_name_pat.finditer(body):
            name = em.group(1).lower()
            if name not in seen:
                events.append({"name": name, "publisher": "", "payload_fields": []})
                seen.add(name)

    # Strategy 2: Prose patterns
    prose_pats = [
        re.compile(r"(?:publishes?|emits?)\s+(?:an?\s+)?`?(\w+[\.\w]*)`?\s+event", re.IGNORECASE),
        re.compile(r"subscribes?\s+to\s+`?(\w+[\.\w]*)`?", re.IGNORECASE),
    ]
    for pat in prose_pats:
        for m in pat.finditer(text):
            name = _normalize_event_name(m.group(1))
            if name and name not in seen:
                events.append({"name": name, "publisher": "", "payload_fields": []})
                seen.add(name)

    return events


# ---------------------------------------------------------------------------
# Technology hints
# ---------------------------------------------------------------------------

_LANGUAGES = {
    "python": "Python", "typescript": "TypeScript", "javascript": "JavaScript",
    "go": "Go", "golang": "Go", "rust": "Rust", "java": "Java",
    "c#": "C#", "csharp": "C#", ".net": ".NET",
}
_FRAMEWORKS = {
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "express": "Express", "nestjs": "NestJS", "nest.js": "NestJS",
    "next.js": "Next.js", "nextjs": "Next.js",
    "angular": "Angular", "react": "React", "vue": "Vue",
    "spring boot": "Spring Boot", "asp.net": "ASP.NET",
}
_DATABASES = {
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "mysql": "MySQL", "mongodb": "MongoDB", "redis": "Redis",
    "sqlite": "SQLite", "supabase": "Supabase",
}


def _extract_technology_hints(text: str) -> dict[str, str | None]:
    """Detect technology mentions in the PRD."""
    text_lower = text.lower()
    hints: dict[str, str | None] = {
        "language": None, "framework": None, "database": None,
    }
    for key, label in _LANGUAGES.items():
        if key in text_lower:
            hints["language"] = label
            break
    for key, label in _FRAMEWORKS.items():
        if key in text_lower:
            hints["framework"] = label
            break
    for key, label in _DATABASES.items():
        if key in text_lower:
            hints["database"] = label
            break
    return hints


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fields_from_csv(text: str) -> list[dict[str, Any]]:
    """Parse comma-separated field list like 'id(UUID), name(str), amount(decimal)'."""
    fields: list[dict[str, Any]] = []
    for part in text.split(","):
        part = part.strip().strip("`")
        if not part:
            continue
        m = re.match(r"(\w+)\s*(?:\((\w+)\))?", part)
        if m:
            fields.append({
                "name": m.group(1),
                "type": m.group(2) or "string",
                "required": True,
            })
    return fields


def _infer_type(text: str) -> str:
    """Infer field type from description text."""
    text_lower = text.lower()
    if "uuid" in text_lower:
        return "UUID"
    if "int" in text_lower or "integer" in text_lower:
        return "int"
    if "decimal" in text_lower or "money" in text_lower or "amount" in text_lower:
        return "decimal"
    if "float" in text_lower or "number" in text_lower:
        return "float"
    if "bool" in text_lower:
        return "boolean"
    if "date" in text_lower and "time" in text_lower:
        return "datetime"
    if "date" in text_lower:
        return "date"
    if "timestamp" in text_lower:
        return "datetime"
    return "string"


def _find_enum_values(text: str, entity_name: str) -> list[str]:
    """Find enum-like status values near an entity mention."""
    # Look for patterns like: status: draft, submitted, approved, completed
    pat = re.compile(
        rf"\b{re.escape(entity_name)}\b.*?(?:status|state)\s*[:\-]\s*"
        r"([\w]+(?:\s*[,/|]\s*[\w]+)+)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(text)
    if m:
        values = re.split(r"\s*[,/|]\s*", m.group(1))
        return [v.strip().lower() for v in values if v.strip() and len(v.strip()) < 30]

    # Fallback: look for quoted enum values near entity
    pat2 = re.compile(
        rf"\b{re.escape(entity_name)}\b[^.]*?(?:status|state)[^.]*?"
        r"['\"](\w+)['\"](?:\s*,\s*['\"](\w+)['\"])+",
        re.IGNORECASE,
    )
    m2 = pat2.search(text)
    if m2:
        return [g.lower() for g in m2.groups() if g]

    return []


def _infer_linear_transitions(states: list[str]) -> list[dict[str, str]]:
    """Create sequential transitions from a list of states."""
    return [
        {"from_state": states[i], "to_state": states[i + 1],
         "trigger": f"{states[i]}_to_{states[i + 1]}"}
        for i in range(len(states) - 1)
    ]


def _find_or_create_machine(
    machines: list[dict[str, Any]], entity_name: str
) -> dict[str, Any]:
    """Find existing machine for entity or create a new one."""
    for machine in machines:
        if machine["entity"].lower() == entity_name.lower():
            return machine
    machine: dict[str, Any] = {
        "entity": entity_name, "states": [], "transitions": [],
    }
    machines.append(machine)
    return machine


def _normalize_state_name(state: str) -> str:
    """Normalize a state name to canonical form.

    Handles common parser artifacts like abbreviations (``send`` vs ``sent``,
    ``partial`` vs ``partially_paid``).  Returns lowercase underscore form.
    """
    s = state.lower().strip().replace("-", "_").replace(" ", "_")
    # Map known abbreviations to their canonical forms
    _CANONICAL: dict[str, str] = {
        "send": "sent",
        "partial": "partially_paid",
    }
    return _CANONICAL.get(s, s)


def _add_state(machine: dict[str, Any], state: str) -> None:
    """Add a state to a machine if not already present (normalized)."""
    norm = _normalize_state_name(state)
    if norm not in [_normalize_state_name(s) for s in machine["states"]]:
        machine["states"].append(norm)


def _deduplicate_machines(machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate state machines by normalized entity name and deduplicate states."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for machine in machines:
        key = machine["entity"].lower().removesuffix("status")
        grouped.setdefault(key, []).append(machine)

    result: list[dict[str, Any]] = []
    for group in grouped.values():
        # Keep the one with the most transitions
        best = max(group, key=lambda m: len(m.get("transitions", [])))
        # Deduplicate states via normalization
        seen_states: set[str] = set()
        deduped_states: list[str] = []
        for s in best.get("states", []):
            norm = _normalize_state_name(s)
            if norm not in seen_states:
                seen_states.add(norm)
                deduped_states.append(norm)
        best["states"] = deduped_states

        # Deduplicate transitions (normalize from/to, keep richest version)
        seen_trans: dict[tuple[str, str], dict] = {}
        for t in best.get("transitions", []):
            key = (_normalize_state_name(t.get("from_state", "")),
                   _normalize_state_name(t.get("to_state", "")))
            t["from_state"] = key[0]
            t["to_state"] = key[1]
            existing = seen_trans.get(key)
            if existing:
                # Keep the one with more info (guard, non-synthetic trigger)
                has_guard = bool(t.get("guard"))
                existing_guard = bool(existing.get("guard"))
                is_synthetic = "_to_" in t.get("trigger", "")
                existing_synthetic = "_to_" in existing.get("trigger", "")
                if has_guard and not existing_guard:
                    seen_trans[key] = t
                elif not is_synthetic and existing_synthetic:
                    seen_trans[key] = t
            else:
                seen_trans[key] = t
        best["transitions"] = list(seen_trans.values())
        result.append(best)
    return result


def _normalize_event_name(raw: str) -> str:
    """Normalize event name to lowercase dot notation."""
    # InvoicePosted -> invoice.posted
    # INVOICE_POSTED -> invoice.posted
    # invoice.posted -> invoice.posted (no change)
    if "." in raw:
        return raw.lower()
    # CamelCase splitting
    parts = re.sub(r"([A-Z])", r"_\1", raw).strip("_").lower().split("_")
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return ".".join(parts)
    return raw.lower()
