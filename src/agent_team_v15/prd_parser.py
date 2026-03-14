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

    return ParsedPRD(
        project_name=project_name,
        entities=entities,
        state_machines=state_machines,
        events=events,
        technology_hints=tech_hints,
    )


def format_domain_model(parsed: ParsedPRD) -> str:
    """Format parsed PRD as a markdown block for prompt injection."""
    if not parsed.entities and not parsed.state_machines and not parsed.events:
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

    return "\n".join(lines)


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

    # Strategy 4: Heading-separated state machine sections
    heading_sm_pat = re.compile(
        r"^#{2,5}\s+([A-Z][A-Za-z]+(?:\s+[A-Z]?[a-z]+)*)\s+"
        r"(?:Status\s+)?State\s+Machine\s*\n"
        r"((?:(?!^#{1,5}\s).*\n)*)",
        re.MULTILINE | re.IGNORECASE,
    )
    for m in heading_sm_pat.finditer(text):
        entity_name = _to_pascal(m.group(1).strip())
        body = m.group(2)
        # Parse chained arrows: "draft -> submitted -> approved -> paid"
        chain_pat = re.compile(r"([\w]+(?:\s*(?:->|-->|=>)\s*[\w]+)+)")
        for chain_match in chain_pat.finditer(body):
            raw_states = re.split(r"\s*(?:->|-->|=>)\s*", chain_match.group(0))
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


def _add_state(machine: dict[str, Any], state: str) -> None:
    """Add a state to a machine if not already present."""
    if state not in machine["states"]:
        machine["states"].append(state)


def _deduplicate_machines(machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate state machines by normalized entity name."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for machine in machines:
        key = machine["entity"].lower().removesuffix("status")
        grouped.setdefault(key, []).append(machine)

    result: list[dict[str, Any]] = []
    for group in grouped.values():
        # Keep the one with the most transitions
        best = max(group, key=lambda m: len(m.get("transitions", [])))
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
