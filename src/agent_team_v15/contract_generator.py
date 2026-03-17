"""Contract code generation from parsed PRD domain model.

Consumes the structured output of prd_parser.parse_prd() and generates:
1. CONTRACTS.md — Human-readable integration specification
2. Typed client code — Importable Python/TypeScript client libraries
3. Event schemas — Typed event envelope definitions

The pipeline: PRD → Parser → ParsedPRD → ContractGenerator → Code + Docs

This is a DETERMINISTIC transformation — no LLM calls. The contract code
is only as good as the parser. Fixing the parser fixes contracts for every
future build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ServiceContract:
    """Contract for a single service/module."""
    service_name: str               # e.g., "gl", "ar", "ap"
    display_name: str               # e.g., "General Ledger", "Accounts Receivable"
    entities: list[dict[str, Any]]  # Entities owned by this service
    endpoints: list[dict[str, Any]] # Generated CRUD endpoint specs
    events_published: list[dict[str, Any]]
    events_subscribed: list[dict[str, Any]]


@dataclass
class ContractBundle:
    """Complete contract bundle for a project."""
    project_name: str
    services: list[ServiceContract]
    contracts_md: str = ""          # Human-readable CONTRACTS.md
    python_clients: dict[str, str] = field(default_factory=dict)   # service -> client code
    typescript_clients: dict[str, str] = field(default_factory=dict)
    event_schemas_py: str = ""
    event_schemas_ts: str = ""


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

_PY_TYPE_MAP: dict[str, str] = {
    "uuid": "str",  # UUIDs as strings in API layer
    "UUID": "str",
    "str": "str",
    "string": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "decimal": "float",  # Decimal as float in API DTOs
    "bool": "bool",
    "boolean": "bool",
    "date": "str",       # ISO format string
    "datetime": "str",
    "json": "dict",
    "jsonb": "dict",
    "text": "str",
}

_TS_TYPE_MAP: dict[str, str] = {
    "uuid": "string",
    "UUID": "string",
    "str": "string",
    "string": "string",
    "int": "number",
    "integer": "number",
    "float": "number",
    "decimal": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "string",
    "datetime": "string",
    "json": "Record<string, any>",
    "jsonb": "Record<string, any>",
    "text": "string",
}


def _py_type(field_type: str) -> str:
    return _PY_TYPE_MAP.get(field_type, "str")


def _ts_type(field_type: str) -> str:
    return _TS_TYPE_MAP.get(field_type, "string")


def _to_snake(name: str) -> str:
    """PascalCase or camelCase to snake_case."""
    s = re.sub(r"([A-Z])", r"_\1", name).strip("_").lower()
    return re.sub(r"_+", "_", s)


def _to_kebab(name: str) -> str:
    """PascalCase to kebab-case for URL paths."""
    return _to_snake(name).replace("_", "-")


def _pluralize(name: str) -> str:
    """Simple English pluralization."""
    lower = name.lower()
    if lower.endswith("s") or lower.endswith("x") or lower.endswith("ch") or lower.endswith("sh"):
        return name + "es"
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


# ---------------------------------------------------------------------------
# Service grouping
# ---------------------------------------------------------------------------

def _group_entities_by_service(
    entities: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group entities by their owning_context (service)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for ent in entities:
        ctx = ent.get("owning_context", "").strip()
        if not ctx:
            ctx = "default"
        # Normalize: "Auth Service" -> "auth", "General Ledger" -> "gl"
        key = _normalize_service_name(ctx)
        groups.setdefault(key, []).append(ent)
    return groups


def _normalize_service_name(raw: str) -> str:
    """Normalize a service name to a short kebab identifier."""
    raw = raw.lower().strip()
    # Remove common suffixes
    for suffix in (" service", " module", " api", " system"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
    # Common abbreviations
    abbreviations = {
        "general ledger": "gl",
        "accounts receivable": "ar",
        "accounts payable": "ap",
        "fixed assets": "asset",
        "fixed asset": "asset",
        "intercompany": "ic",
        "authentication": "auth",
        "authorization": "auth",
    }
    if raw in abbreviations:
        return abbreviations[raw]
    return _to_kebab(raw).replace("-", "_")


def _group_events_by_publisher(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group events by their publisher service (inferred from event name prefix)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        name = ev.get("name", "")
        publisher = ev.get("publisher", "")
        if not publisher and "." in name:
            publisher = name.split(".")[0]
        groups.setdefault(publisher or "unknown", []).append(ev)
    return groups


# ---------------------------------------------------------------------------
# Endpoint generation
# ---------------------------------------------------------------------------

def _generate_endpoints(entity: dict[str, Any], service_name: str) -> list[dict[str, Any]]:
    """Generate CRUD endpoint specs for an entity."""
    name = entity.get("name", "")
    path_segment = _to_kebab(_pluralize(name))
    fields = entity.get("fields", [])

    # Separate ID field from data fields
    data_fields = [f for f in fields if f["name"] not in ("id", "created_at", "updated_at", "tenant_id")]

    endpoints = [
        {
            "method": "GET",
            "path": f"/{path_segment}",
            "description": f"List {_pluralize(name)} with pagination",
            "query_params": ["page", "limit", "sort_by", "order"],
            "response_type": f"list[{name}Response]",
        },
        {
            "method": "POST",
            "path": f"/{path_segment}",
            "description": f"Create a new {name}",
            "request_fields": data_fields,
            "response_type": f"{name}Response",
        },
        {
            "method": "GET",
            "path": f"/{path_segment}/{{id}}",
            "description": f"Get {name} by ID",
            "response_type": f"{name}Response",
        },
        {
            "method": "PATCH",
            "path": f"/{path_segment}/{{id}}",
            "description": f"Update {name}",
            "request_fields": data_fields,
            "response_type": f"{name}Response",
        },
    ]
    return endpoints


# ---------------------------------------------------------------------------
# CONTRACTS.md generation
# ---------------------------------------------------------------------------

def generate_contracts_md(
    project_name: str,
    services: list[ServiceContract],
) -> str:
    """Generate human-readable CONTRACTS.md."""
    lines = [
        f"# CONTRACTS.md — Cross-Module Interfaces for {project_name}\n",
        "This document specifies every cross-module API, event, and shared type.",
        "Generated from parsed PRD. Every milestone receives this document.",
        "When implementing cross-module calls, use the EXACT signatures below.\n",
        "---\n",
    ]

    # API Contracts
    lines.append("## API Contracts\n")
    for svc in services:
        if not svc.endpoints:
            continue
        lines.append(f"### {svc.display_name} ({svc.service_name})\n")
        for ep in svc.endpoints:
            lines.append(f"**{ep['method']} {ep['path']}** — {ep['description']}")
            if ep.get("request_fields"):
                field_strs = [f"{f['name']}: {f.get('type', 'string')}" for f in ep["request_fields"]]
                lines.append(f"  Request: {{{', '.join(field_strs)}}}")
            lines.append(f"  Response: {ep['response_type']}")
            lines.append("")

    # Event Contracts
    lines.append("## Event Contracts\n")
    all_events: list[dict[str, Any]] = []
    for svc in services:
        all_events.extend(svc.events_published)
    if all_events:
        for ev in all_events:
            name = ev.get("name", "?")
            publisher = ev.get("publisher", "?")
            payload = ev.get("payload_fields", [])
            lines.append(f"### Event: `{name}`")
            lines.append(f"- Publisher: {publisher}")
            if payload:
                lines.append(f"- Payload: {{{', '.join(payload)}}}")
            subscribers = ev.get("subscribers", [])
            if subscribers:
                lines.append(f"- Subscribers: {', '.join(subscribers)}")
                for sub in subscribers:
                    behavior = ev.get(f"subscriber_behavior_{sub}", "")
                    if behavior:
                        lines.append(f"  - {sub}: {behavior}")
            lines.append("")
    else:
        lines.append("No events extracted from PRD.\n")

    # A6: GL Journal Entry Account Mapping (accounting systems)
    # Check if GL service exists in the bundle
    gl_svc = next((s for s in services if s.service_name in ("gl", "general_ledger")), None)
    if gl_svc:
        lines.append("## GL Journal Entry Creation — Account Mapping\n")
        lines.append(
            "When creating GL journal entries from subledger events, use the following "
            "debit/credit account mappings. These are MANDATORY — do NOT guess account codes.\n"
        )
        lines.append("| Source Event | Debit Account | Credit Account |")
        lines.append("|-------------|--------------|----------------|")
        lines.append("| AR Invoice Sent | Accounts Receivable | Revenue |")
        lines.append("| AR Payment Applied | Cash | Accounts Receivable |")
        lines.append("| AR Credit Memo | Revenue | Accounts Receivable |")
        lines.append("| AP Invoice Approved | Expense / Asset | Accounts Payable |")
        lines.append("| AP Payment Run | Accounts Payable | Cash |")
        lines.append("| Depreciation Posted | Depreciation Expense | Accumulated Depreciation |")
        lines.append("| Asset Disposal | Cash + Accumulated Depreciation | Asset Cost (+ Gain/Loss) |")
        lines.append("| IC Transaction (originator) | IC Receivable | Revenue |")
        lines.append("| IC Transaction (counterparty) | Expense | IC Payable |")
        lines.append("| FX Revaluation Gain | Accounts Receivable/Payable | FX Gain/Loss |")
        lines.append("| FX Revaluation Loss | FX Gain/Loss | Accounts Receivable/Payable |")
        lines.append("")

        # A7: FX Gain/Loss event
        lines.append("### FX Revaluation\n")
        lines.append("**POST /gl/fx-revaluation** — Run period-end foreign exchange revaluation")
        lines.append("  Request: {period_id: UUID, target_currency: string}")
        lines.append("  Response: {revaluation_id: UUID, entries_created: int, net_gain_loss: decimal}")
        lines.append("")
        lines.append("**Event: `gl.fx.revaluation_completed`**")
        lines.append("- Publisher: gl")
        lines.append("- Payload: {revaluation_id, period_id, net_gain_loss, entries_created}")
        lines.append("- Subscribers: reporting (update trial balance), ar (adjust open invoices), ap (adjust open bills)")
        lines.append("")

    # Entity Schemas (summary)
    lines.append("## Entity Schemas\n")
    for svc in services:
        if not svc.entities:
            continue
        lines.append(f"### {svc.display_name}\n")
        for ent in svc.entities:
            name = ent.get("name", "?")
            fields = ent.get("fields", [])
            field_str = ", ".join(f"{f['name']}({f.get('type', '?')})" for f in fields[:8])
            if len(fields) > 8:
                field_str += f", ... (+{len(fields) - 8} more)"
            lines.append(f"- **{name}**: {field_str}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Python client generation
# ---------------------------------------------------------------------------

def generate_python_client(svc: ServiceContract) -> str:
    """Generate a Python HTTP client for a service's API."""
    lines = [
        f'"""Auto-generated API client for {svc.display_name} service.',
        f'',
        f'Generated from CONTRACTS.md. Do NOT edit manually.',
        f'Import this client in other services to call {svc.service_name} APIs.',
        f'"""',
        f'',
        f'from __future__ import annotations',
        f'',
        f'from dataclasses import dataclass',
        f'from typing import Any',
        f'',
        f'import httpx',
        f'',
        f'',
    ]

    # Generate response dataclasses for each entity
    for ent in svc.entities:
        name = ent.get("name", "")
        fields = ent.get("fields", [])
        lines.append(f"@dataclass")
        lines.append(f"class {name}Response:")
        lines.append(f'    """{name} API response."""')
        if fields:
            for f in fields:
                lines.append(f"    {f['name']}: {_py_type(f.get('type', 'str'))}")
        else:
            lines.append(f"    id: str")
        lines.append("")
        lines.append("")

    # Generate request dataclasses
    for ent in svc.entities:
        name = ent.get("name", "")
        data_fields = [f for f in ent.get("fields", []) if f["name"] not in ("id", "created_at", "updated_at", "tenant_id")]
        if data_fields:
            lines.append(f"@dataclass")
            lines.append(f"class Create{name}Request:")
            lines.append(f'    """{name} creation request."""')
            for f in data_fields:
                req = "" if f.get("required", True) else " = None"
                lines.append(f"    {f['name']}: {_py_type(f.get('type', 'str'))}{req}")
            lines.append("")
            lines.append("")

    # Generate client class
    svc_upper = svc.service_name.replace("_", " ").title().replace(" ", "")
    lines.append(f"class {svc_upper}Client:")
    lines.append(f'    """HTTP client for {svc.display_name} API."""')
    lines.append(f"")
    lines.append(f"    def __init__(self, base_url: str, auth_token: str = \"\") -> None:")
    lines.append(f"        self.base_url = base_url.rstrip(\"/\")")
    lines.append(f"        self.auth_token = auth_token")
    lines.append(f"")
    lines.append(f"    def _headers(self) -> dict[str, str]:")
    lines.append(f"        h: dict[str, str] = {{\"Content-Type\": \"application/json\"}}")
    lines.append(f"        if self.auth_token:")
    lines.append(f"            h[\"Authorization\"] = f\"Bearer {{self.auth_token}}\"")
    lines.append(f"        return h")
    lines.append(f"")

    # Generate methods for each entity
    for ent in svc.entities:
        name = ent.get("name", "")
        path_segment = _to_kebab(_pluralize(name))
        snake = _to_snake(name)
        data_fields = [f for f in ent.get("fields", []) if f["name"] not in ("id", "created_at", "updated_at", "tenant_id")]

        # List
        lines.append(f"    async def list_{_to_snake(_pluralize(name))}(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:")
        lines.append(f'        """List {_pluralize(name)} with pagination."""')
        lines.append(f"        async with httpx.AsyncClient() as client:")
        lines.append(f"            resp = await client.get(")
        lines.append(f"                f\"{{self.base_url}}/{path_segment}\",")
        lines.append(f"                params={{\"page\": page, \"limit\": limit}},")
        lines.append(f"                headers=self._headers(),")
        lines.append(f"            )")
        lines.append(f"            resp.raise_for_status()")
        lines.append(f"            return resp.json()")
        lines.append(f"")

        # Create
        if data_fields:
            lines.append(f"    async def create_{snake}(self, data: Create{name}Request) -> dict[str, Any]:")
            lines.append(f'        """Create a new {name}."""')
            lines.append(f"        async with httpx.AsyncClient() as client:")
            lines.append(f"            resp = await client.post(")
            lines.append(f"                f\"{{self.base_url}}/{path_segment}\",")
            lines.append(f"                json=data.__dict__,")
            lines.append(f"                headers=self._headers(),")
            lines.append(f"            )")
            lines.append(f"            resp.raise_for_status()")
            lines.append(f"            return resp.json()")
            lines.append(f"")

        # Get by ID
        lines.append(f"    async def get_{snake}(self, id: str) -> dict[str, Any]:")
        lines.append(f'        """Get {name} by ID."""')
        lines.append(f"        async with httpx.AsyncClient() as client:")
        lines.append(f"            resp = await client.get(")
        lines.append(f"                f\"{{self.base_url}}/{path_segment}/{{id}}\",")
        lines.append(f"                headers=self._headers(),")
        lines.append(f"            )")
        lines.append(f"            resp.raise_for_status()")
        lines.append(f"            return resp.json()")
        lines.append(f"")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TypeScript client generation
# ---------------------------------------------------------------------------

def generate_typescript_client(svc: ServiceContract) -> str:
    """Generate a TypeScript HTTP client for a service's API."""
    lines = [
        f"/**",
        f" * Auto-generated API client for {svc.display_name} service.",
        f" * Generated from CONTRACTS.md. Do NOT edit manually.",
        f" */",
        f"",
    ]

    # Generate interfaces for each entity
    for ent in svc.entities:
        name = ent.get("name", "")
        fields = ent.get("fields", [])
        lines.append(f"export interface {name} {{")
        for f in fields:
            optional = "" if f.get("required", True) else "?"
            lines.append(f"  {f['name']}{optional}: {_ts_type(f.get('type', 'string'))};")
        if not fields:
            lines.append(f"  id: string;")
        lines.append(f"}}")
        lines.append(f"")

        # Create request (omit id, timestamps)
        data_fields = [f for f in fields if f["name"] not in ("id", "created_at", "updated_at", "tenant_id")]
        if data_fields:
            lines.append(f"export interface Create{name}Input {{")
            for f in data_fields:
                optional = "" if f.get("required", True) else "?"
                lines.append(f"  {f['name']}{optional}: {_ts_type(f.get('type', 'string'))};")
            lines.append(f"}}")
            lines.append(f"")

    # Generate client class
    svc_pascal = svc.service_name.replace("_", " ").title().replace(" ", "")
    lines.append(f"export class {svc_pascal}Client {{")
    lines.append(f"  constructor(")
    lines.append(f"    private readonly baseUrl: string,")
    lines.append(f"    private readonly authToken: string = '',")
    lines.append(f"  ) {{}}")
    lines.append(f"")
    lines.append(f"  private headers(): Record<string, string> {{")
    lines.append(f"    const h: Record<string, string> = {{ 'Content-Type': 'application/json' }};")
    lines.append(f"    if (this.authToken) h['Authorization'] = `Bearer ${{this.authToken}}`;")
    lines.append(f"    return h;")
    lines.append(f"  }}")
    lines.append(f"")

    for ent in svc.entities:
        name = ent.get("name", "")
        path_segment = _to_kebab(_pluralize(name))
        camel = name[0].lower() + name[1:] if name else ""
        data_fields = [f for f in ent.get("fields", []) if f["name"] not in ("id", "created_at", "updated_at", "tenant_id")]

        # List
        lines.append(f"  async list{_pluralize(name)}(page = 1, limit = 20): Promise<{name}[]> {{")
        lines.append(f"    const resp = await fetch(")
        lines.append(f"      `${{this.baseUrl}}/{path_segment}?page=${{page}}&limit=${{limit}}`,")
        lines.append(f"      {{ headers: this.headers() }},")
        lines.append(f"    );")
        lines.append(f"    if (!resp.ok) throw new Error(`${{resp.status}}: ${{resp.statusText}}`);")
        lines.append(f"    return resp.json();")
        lines.append(f"  }}")
        lines.append(f"")

        # Create
        if data_fields:
            lines.append(f"  async create{name}(input: Create{name}Input): Promise<{name}> {{")
            lines.append(f"    const resp = await fetch(`${{this.baseUrl}}/{path_segment}`, {{")
            lines.append(f"      method: 'POST',")
            lines.append(f"      headers: this.headers(),")
            lines.append(f"      body: JSON.stringify(input),")
            lines.append(f"    }});")
            lines.append(f"    if (!resp.ok) throw new Error(`${{resp.status}}: ${{resp.statusText}}`);")
            lines.append(f"    return resp.json();")
            lines.append(f"  }}")
            lines.append(f"")

        # Get by ID
        lines.append(f"  async get{name}(id: string): Promise<{name}> {{")
        lines.append(f"    const resp = await fetch(")
        lines.append(f"      `${{this.baseUrl}}/{path_segment}/${{id}}`,")
        lines.append(f"      {{ headers: this.headers() }},")
        lines.append(f"    );")
        lines.append(f"    if (!resp.ok) throw new Error(`${{resp.status}}: ${{resp.statusText}}`);")
        lines.append(f"    return resp.json();")
        lines.append(f"  }}")
        lines.append(f"")

    lines.append(f"}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Event schema generation
# ---------------------------------------------------------------------------

def generate_event_schemas_py(events: list[dict[str, Any]]) -> str:
    """Generate Python event envelope dataclasses."""
    lines = [
        '"""Auto-generated event schemas from CONTRACTS.md."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, field",
        "from datetime import datetime",
        "",
        "",
        "@dataclass",
        "class EventEnvelope:",
        '    """Standard event envelope for all domain events."""',
        "    event_type: str",
        "    timestamp: str",
        "    source_service: str",
        "    tenant_id: str",
        "    payload: dict",
        "    event_id: str = \"\"",
        "    correlation_id: str = \"\"",
        "",
        "",
        "# Event type constants",
    ]
    for ev in events:
        name = ev.get("name", "")
        const_name = name.upper().replace(".", "_")
        lines.append(f'EVENT_{const_name} = "{name}"')

    lines.append("")
    return "\n".join(lines)


def generate_event_schemas_ts(events: list[dict[str, Any]]) -> str:
    """Generate TypeScript event envelope interfaces."""
    lines = [
        "/**",
        " * Auto-generated event schemas from CONTRACTS.md.",
        " */",
        "",
        "export interface EventEnvelope {",
        "  event_type: string;",
        "  timestamp: string;",
        "  source_service: string;",
        "  tenant_id: string;",
        "  payload: Record<string, any>;",
        "  event_id?: string;",
        "  correlation_id?: string;",
        "}",
        "",
        "// Event type constants",
    ]
    for ev in events:
        name = ev.get("name", "")
        const_name = name.upper().replace(".", "_")
        lines.append(f"export const EVENT_{const_name} = '{name}';")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_contracts(
    parsed_prd: Any,
) -> ContractBundle:
    """Generate a complete contract bundle from parsed PRD output.

    This is the main entry point. Takes a ParsedPRD dataclass and produces
    CONTRACTS.md + typed client code + event schemas.

    Parameters
    ----------
    parsed_prd :
        Output of ``prd_parser.parse_prd()``. Must have ``entities``,
        ``events``, ``state_machines``, ``project_name``, ``technology_hints``.

    Returns
    -------
    ContractBundle
        Complete contract bundle with markdown, Python clients, TypeScript
        clients, and event schemas.
    """
    project_name = getattr(parsed_prd, "project_name", "Project")
    entities = getattr(parsed_prd, "entities", [])
    events = getattr(parsed_prd, "events", [])
    tech_hints = getattr(parsed_prd, "technology_hints", {})

    # Group entities by service
    entity_groups = _group_entities_by_service(entities)

    # Build service contracts
    services: list[ServiceContract] = []
    event_groups = _group_events_by_publisher(events)

    for svc_name, svc_entities in sorted(entity_groups.items()):
        display_name = svc_entities[0].get("owning_context", svc_name) if svc_entities else svc_name
        endpoints: list[dict[str, Any]] = []
        for ent in svc_entities:
            endpoints.extend(_generate_endpoints(ent, svc_name))

        svc_events = event_groups.get(svc_name, [])

        services.append(ServiceContract(
            service_name=svc_name,
            display_name=display_name,
            entities=svc_entities,
            endpoints=endpoints,
            events_published=svc_events,
            events_subscribed=[],  # TODO: infer from event names
        ))

    # Generate outputs
    contracts_md = generate_contracts_md(project_name, services)

    python_clients: dict[str, str] = {}
    typescript_clients: dict[str, str] = {}
    for svc in services:
        if svc.entities:
            python_clients[svc.service_name] = generate_python_client(svc)
            typescript_clients[svc.service_name] = generate_typescript_client(svc)

    event_schemas_py = generate_event_schemas_py(events)
    event_schemas_ts = generate_event_schemas_ts(events)

    return ContractBundle(
        project_name=project_name,
        services=services,
        contracts_md=contracts_md,
        python_clients=python_clients,
        typescript_clients=typescript_clients,
        event_schemas_py=event_schemas_py,
        event_schemas_ts=event_schemas_ts,
    )


def write_contract_files(
    bundle: ContractBundle,
    output_dir: Path,
) -> list[Path]:
    """Write contract files to disk.

    Creates:
      {output_dir}/CONTRACTS.md
      {output_dir}/contracts/python/{service}_client.py
      {output_dir}/contracts/typescript/{service}-client.ts
      {output_dir}/contracts/python/event_schemas.py
      {output_dir}/contracts/typescript/event-schemas.ts

    Returns list of created file paths.
    """
    created: list[Path] = []

    # CONTRACTS.md
    contracts_path = output_dir / "CONTRACTS.md"
    contracts_path.parent.mkdir(parents=True, exist_ok=True)
    contracts_path.write_text(bundle.contracts_md, encoding="utf-8")
    created.append(contracts_path)

    # Python clients
    py_dir = output_dir / "contracts" / "python"
    py_dir.mkdir(parents=True, exist_ok=True)
    (py_dir / "__init__.py").write_text("", encoding="utf-8")
    for svc_name, code in bundle.python_clients.items():
        path = py_dir / f"{svc_name}_client.py"
        path.write_text(code, encoding="utf-8")
        created.append(path)

    # TypeScript clients
    ts_dir = output_dir / "contracts" / "typescript"
    ts_dir.mkdir(parents=True, exist_ok=True)
    for svc_name, code in bundle.typescript_clients.items():
        path = ts_dir / f"{svc_name}-client.ts"
        path.write_text(code, encoding="utf-8")
        created.append(path)

    # Event schemas
    if bundle.event_schemas_py:
        path = py_dir / "event_schemas.py"
        path.write_text(bundle.event_schemas_py, encoding="utf-8")
        created.append(path)
    if bundle.event_schemas_ts:
        path = ts_dir / "event-schemas.ts"
        path.write_text(bundle.event_schemas_ts, encoding="utf-8")
        created.append(path)

    return created
