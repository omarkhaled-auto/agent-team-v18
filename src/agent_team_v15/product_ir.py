"""Product IR compiler for PRD-mode orchestration.

This module deterministically compiles a PRD into a typed Product IR that can
be consumed by downstream stages without re-interpreting the raw PRD.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .prd_parser import BusinessRule, ParsedPRD, parse_prd


_ENDPOINT_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_FEATURE_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+)$", re.MULTILINE)
_FEATURE_ID_RE = re.compile(r"\bF[-\s]?0*(\d{1,4})\b", re.IGNORECASE)
_PROJECT_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_PROJECT_NAME_RE = re.compile(
    r"^(?:project\s+name|project)\s*:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)
_ENDPOINT_PROSE_RE = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>/[^\s`|)\],;]+)",
    re.IGNORECASE,
)
_ENDPOINT_CODEBLOCK_RE = re.compile(
    r"```[^\n]*\n[^`]*((?:GET|POST|PUT|PATCH|DELETE)\s+/\S+)[^`]*```",
    re.IGNORECASE | re.DOTALL,
)
_AC_PATTERNS = [
    re.compile(r"^[-*]\s*(AC[-_]\S+)\s*[:\-]\s*(.+)", re.MULTILINE),
    re.compile(r"^[-*]\s*\[(AC[-_]\S+)\]\s*(.+)", re.MULTILINE),
    re.compile(r"^\s*\|?\s*(AC[-_]\S+)\s*\|(.+)\|", re.MULTILINE),
    re.compile(r"^#{1,4}\s*(AC[-_]\S+)\s*[:\-]\s*(.+)", re.MULTILINE),
    re.compile(r"^[-*]\s*(?:\[[ x]\]\s*)?(AC[-_]\S+)\s*[:\-]\s*(.+)", re.MULTILINE),
    re.compile(r"^\d+\.\s*(AC[-_]\S+)\s*[:\-]\s*(.+)", re.MULTILINE),
    re.compile(r"^[-*]\s*\*\*(AC[-_]\S+)\*\*\s*[:\-]\s*(.+)", re.MULTILINE),
]
_LOCALE_PATTERNS: dict[str, list[str]] = {
    "en": [r"\ben(?:glish)?\b", r"\ben[-_](?:US|GB|AU|CA)\b"],
    "ar": [r"\bar(?:abic)?\b", r"\bar[-_](?:SA|AE|EG)\b"],
    "he": [r"\bhe(?:brew)?\b", r"\bhe[-_]IL\b"],
    "fa": [r"\bfa(?:rsi)?\b", r"\bpersian\b", r"\bfa[-_]IR\b"],
    "ur": [r"\bur(?:du)?\b", r"\bur[-_]PK\b"],
    "fr": [r"\bfr(?:ench)?\b", r"\bfr[-_](?:FR|CA|BE)\b"],
    "de": [r"\bde(?:utsch|german)?\b", r"\bde[-_](?:DE|AT|CH)\b"],
    "es": [r"\bes(?:pa[nñ]ol|spanish)?\b", r"\bes[-_](?:ES|MX|AR)\b"],
    "pt": [r"\bpt(?:portuguese)?\b", r"\bpt[-_](?:BR|PT)\b"],
    "zh": [r"\bzh(?:chinese)?\b", r"\bzh[-_](?:CN|TW|HK)\b", r"\bmandarin\b", r"\bcantonese\b"],
    "ja": [r"\bja(?:panese)?\b", r"\bja[-_]JP\b"],
    "ko": [r"\bko(?:rean)?\b", r"\bko[-_]KR\b"],
    "hi": [r"\bhi(?:ndi)?\b", r"\bhi[-_]IN\b"],
    "tr": [r"\btr(?:urkish)?\b", r"\btr[-_]TR\b"],
    "ru": [r"\bru(?:ssian)?\b", r"\bru[-_]RU\b"],
    "nl": [r"\bnl(?:dutch)?\b", r"\bne(?:derlands)?\b", r"\bnl[-_](?:NL|BE)\b"],
    "th": [r"\bth(?:ai)?\b", r"\bth[-_]TH\b"],
    "vi": [r"\bvi(?:etnamese)?\b", r"\bvi[-_]VN\b"],
    "id": [r"\bid(?:indonesian)?\b", r"\bbahasa\s+indonesia\b", r"\bid[-_]ID\b"],
    "ms": [r"\bms(?:malay)?\b", r"\bbahasa\s+melayu\b", r"\bms[-_]MY\b"],
    "sw": [r"\bsw(?:ahili)?\b", r"\bsw[-_](?:KE|TZ)\b"],
    "bn": [r"\bbn(?:bengali)?\b", r"\bbangla\b", r"\bbn[-_](?:BD|IN)\b"],
    "ta": [r"\bta(?:mil)?\b", r"\bta[-_](?:IN|LK|SG)\b"],
}
_RTL_LOCALES = {"ar", "he", "fa", "ur"}
_TRIGGER_KEYWORDS = (
    "notification",
    "email",
    "push",
    "webhook",
    "event",
    "cron",
    "timer",
    "schedule",
)
_ACTOR_KEYWORDS = (
    "customer",
    "user",
    "admin",
    "agent",
    "manager",
    "operator",
    "system",
    "vendor",
)


@dataclass
class EndpointSpec:
    method: str
    path: str
    auth: str = ""
    request_fields: list[dict[str, Any]] = field(default_factory=list)
    response_fields: list[dict[str, Any]] = field(default_factory=list)
    owner_feature: str = ""
    description: str = ""


@dataclass
class AcceptanceCriterion:
    id: str
    feature: str
    text: str
    verification_mode: str = "code_span"
    required_evidence: list[str] = field(default_factory=list)
    verifiable_statically: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class IntegrationSpec:
    vendor: str
    type: str
    port_name: str
    methods_used: list[str] = field(default_factory=list)


@dataclass
class IntegrationEvidence:
    source_kind: str  # explicit_table|integration_section|technology_stack|endpoint|event|heuristic
    confidence: str   # explicit|high|medium|low
    heading: str = ""
    excerpt: str = ""
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class IntegrationItem:
    id: str
    name: str
    kind: str  # external_system|service_provider|capability|infra_dependency
    vendor: str = ""
    category: str = ""
    status: str = "required"  # required|stubbed|future|deferred|optional
    implementation_mode: str = "internal_module"  # real_sdk|adapter_stub|internal_module|infra_only|capability_only
    direction: str = "n/a"  # inbound|outbound|bidirectional|internal|n/a
    auth_mode: str = ""
    port_name: str = ""
    methods_used: list[str] = field(default_factory=list)
    owner_features: list[str] = field(default_factory=list)
    source_evidence: list[IntegrationEvidence] = field(default_factory=list)


@dataclass
class WorkflowSpec:
    name: str
    feature: str
    actors: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)


@dataclass
class I18nSpec:
    locales: list[str] = field(default_factory=lambda: ["en"])
    rtl_locales: list[str] = field(default_factory=list)
    default_locale: str = "en"


@dataclass
class StackTarget:
    backend: str = ""
    frontend: str = ""
    db: str = ""
    mobile: Optional[str] = None


@dataclass
class ProductIR:
    schema_version: int = 2
    project_name: str = ""
    stack_target: StackTarget = field(default_factory=StackTarget)
    entities: list[dict[str, Any]] = field(default_factory=list)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    business_rules: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    endpoints: list[EndpointSpec] = field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    integration_items: list[IntegrationItem] = field(default_factory=list)
    integrations: list[IntegrationSpec] = field(default_factory=list)
    workflows: list[WorkflowSpec] = field(default_factory=list)
    i18n: I18nSpec = field(default_factory=I18nSpec)


_VENDOR_REGISTRY: dict[str, dict[str, Any]] = {
    "Stripe": {
        "kind": "service_provider",
        "category": "payment_processing",
        "port_name": "IPaymentProvider",
        "explicit_terms": ["stripe", "payment_intent", "paymentintent", "stripe webhook"],
        "sdk_terms": ["stripe", "@stripe/stripe-js", "stripe-node"],
        "default_mode": "real_sdk",
        "legacy_type": "payment",
    },
    "Twilio": {
        "kind": "service_provider",
        "category": "sms_delivery",
        "port_name": "ISmsProvider",
        "explicit_terms": ["twilio"],
        "sdk_terms": ["twilio-node", "@twilio"],
        "default_mode": "real_sdk",
        "legacy_type": "sms",
    },
    "AWS S3": {
        "kind": "service_provider",
        "category": "file_storage",
        "port_name": "IFileStorageProvider",
        "explicit_terms": ["aws s3", "s3 bucket"],
        "sdk_terms": ["aws-sdk", "@aws-sdk/client-s3"],
        "default_mode": "real_sdk",
        "legacy_type": "file_storage",
    },
    "Odoo": {
        "kind": "external_system",
        "category": "erp",
        "port_name": "IOdooClient",
        "explicit_terms": ["odoo", "odoo api"],
        "sdk_terms": ["search_read", "execute_kw", "json-rpc", "xmlrpc"],
        "default_mode": "adapter_stub",
        "legacy_type": "erp",
    },
    "Firebase": {
        "kind": "service_provider",
        "category": "push_notification",
        "port_name": "IPushNotificationProvider",
        "explicit_terms": ["firebase", "cloud messaging", "fcm"],
        "sdk_terms": ["firebase-admin"],
        "default_mode": "real_sdk",
        "legacy_type": "push_notification",
    },
    "SendGrid": {
        "kind": "service_provider",
        "category": "email_delivery",
        "port_name": "IEmailProvider",
        "explicit_terms": ["sendgrid"],
        "sdk_terms": ["@sendgrid", "sgmail"],
        "default_mode": "real_sdk",
        "legacy_type": "email",
    },
    "Azure Blob Storage": {
        "kind": "service_provider",
        "category": "file_storage",
        "port_name": "IFileStorageProvider",
        "explicit_terms": ["azure blob storage", "azure storage blob"],
        "sdk_terms": ["@azure/storage-blob", "blobserviceclient"],
        "default_mode": "real_sdk",
        "legacy_type": "file_storage",
    },
    "Azure Notification Hubs": {
        "kind": "service_provider",
        "category": "push_notification",
        "port_name": "IPushNotificationProvider",
        "explicit_terms": ["azure notification hubs"],
        "sdk_terms": ["@azure/notification-hubs", "notificationhubclient"],
        "default_mode": "real_sdk",
        "legacy_type": "push_notification",
    },
}

_CAPABILITY_PATTERNS: dict[str, dict[str, Any]] = {
    "push_notification": {
        "terms": ["push notification", "push notifications", "push delivery", "push"],
    },
    "email_delivery": {
        "terms": ["email", "emails", "transactional email", "magic link email"],
    },
    "sms_delivery": {
        "terms": ["sms", "text message", "text messages"],
    },
    "inbound_webhook": {
        "terms": ["inbound webhook", "webhook receiver", "receives webhook", "webhook retries"],
    },
    "outbound_webhook": {
        "terms": ["outbound webhook", "webhook callback", "dispatch webhook", "send webhook"],
    },
    "file_storage": {
        "terms": ["file storage", "blob storage", "object storage", "file upload storage"],
    },
    "payment_processing": {
        "terms": ["payment", "payments", "payment approval"],
    },
}

_INFRA_PATTERNS: dict[str, dict[str, Any]] = {
    "Redis": {
        "category": "cache_queue",
        "terms": ["redis", "ioredis"],
    },
    "PostgreSQL": {
        "category": "database",
        "terms": ["postgresql", "postgres"],
    },
    "BullMQ": {
        "category": "queue",
        "terms": ["bullmq"],
    },
    "Kafka": {
        "category": "event_stream",
        "terms": ["kafka", "kafkajs", "confluent"],
    },
    "RabbitMQ": {
        "category": "message_queue",
        "terms": ["rabbitmq", "amqp", "amqplib"],
    },
    "Elasticsearch": {
        "category": "search",
        "terms": ["elasticsearch", "@elastic/elasticsearch", "opensearch"],
    },
}

_METHOD_HINTS: dict[str, tuple[str, ...]] = {
    "Stripe": ("payment_intent", "createPaymentIntent", "confirmPaymentIntent", "refundPayment"),
    "Twilio": ("messages.create", "verification"),
    "Odoo": ("search_read", "execute_kw", "json-rpc", "xmlrpc"),
    "Firebase": ("sendMulticast", "subscribeToTopic", "unsubscribeFromTopic"),
    "SendGrid": ("sendTemplatedEmail", "sendMultiple"),
    "Azure Blob Storage": ("BlobServiceClient", "getContainerClient", "uploadData"),
    "Azure Notification Hubs": ("NotificationHubClient", "sendNotification"),
}

_SOURCE_KIND_ORDER = {
    "explicit_table": 7,
    "integration_section": 6,
    "technology_stack": 5,
    "endpoint": 4,
    "event": 4,
    "heuristic": 1,
}

_CONFIDENCE_ORDER = {
    "explicit": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

_SUMMARY_GROUPS = (
    ("external_system", "External Systems"),
    ("service_provider", "Provider Services"),
    ("capability", "Capabilities"),
    ("infra_dependency", "Infra Dependencies"),
)

_PORT_BY_CATEGORY = {
    "payment_processing": "IPaymentProvider",
    "sms_delivery": "ISmsProvider",
    "push_notification": "IPushNotificationProvider",
    "email_delivery": "IEmailProvider",
    "file_storage": "IFileStorageProvider",
}


def compile_product_ir(prd_path: Path, parsed_prd: ParsedPRD | None = None) -> ProductIR:
    """Compile a PRD file into a typed Product IR."""
    prd_text = prd_path.read_text(encoding="utf-8")
    if parsed_prd is None:
        parsed_prd = parse_prd(prd_text)

    project_name = parsed_prd.project_name or _extract_project_name(prd_text) or prd_path.stem
    integration_items = _extract_integration_items(prd_text)
    legacy_integrations = _derive_legacy_integrations(integration_items)

    return ProductIR(
        project_name=project_name,
        stack_target=_detect_stack(parsed_prd, prd_text),
        entities=_convert_business_entities(parsed_prd.entities),
        state_machines=_convert_state_machines(parsed_prd.state_machines),
        business_rules=_convert_business_rules(parsed_prd.business_rules),
        events=_convert_events(parsed_prd.events),
        endpoints=_extract_endpoints(prd_text),
        acceptance_criteria=_extract_acs_with_evidence(prd_text),
        integration_items=integration_items,
        integrations=legacy_integrations,
        workflows=_extract_workflows(prd_text),
        i18n=_detect_i18n(prd_text),
    )


def save_product_ir(ir: ProductIR, output_dir: Path) -> None:
    """Write the canonical IR artifacts to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    product_ir_payload = json.dumps(_ir_to_dict(ir), indent=2, ensure_ascii=False)
    (output_dir / "product.ir.json").write_text(product_ir_payload, encoding="utf-8")
    (output_dir / "IR.json").write_text(product_ir_payload, encoding="utf-8")
    (output_dir / "acceptance-criteria.ir.json").write_text(
        json.dumps([_ac_to_dict(ac) for ac in ir.acceptance_criteria], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "integrations.ir.json").write_text(
        json.dumps([_integration_to_dict(integration) for integration in ir.integrations], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "integration-items.ir.json").write_text(
        json.dumps([_integration_item_to_dict(item) for item in ir.integration_items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "milestones.ir.json").write_text(
        json.dumps(_build_milestone_hints(ir), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def format_ir_summary(ir: ProductIR) -> str:
    """Return a compact summary for prompt injection."""
    stack = _format_stack_target(ir.stack_target)
    lines = ["[PRODUCT IR SUMMARY]"]
    lines.append(f"Stack: {stack}")
    lines.append(f"Entities: {len(ir.entities)}")
    lines.append(f"Endpoints: {len(ir.endpoints)}")
    lines.append(f"Acceptance Criteria: {len(ir.acceptance_criteria)}")
    lines.append(f"Business Rules: {len(ir.business_rules)}")
    lines.append(f"State Machines: {len(ir.state_machines)}")
    if ir.integration_items:
        for kind, label in _SUMMARY_GROUPS:
            names = sorted({_integration_display_name(item) for item in ir.integration_items if item.kind == kind})
            if names:
                lines.append(f"{label}: {', '.join(names)}")
        if ir.integrations:
            lines.append("Adapter Candidates: " + ", ".join(sorted({i.vendor for i in ir.integrations if i.vendor})))
    elif ir.integrations:
        lines.append("Adapter Candidates: " + ", ".join(sorted({i.vendor for i in ir.integrations if i.vendor})))
    if ir.workflows:
        workflow_names = ", ".join(w.name for w in ir.workflows[:10])
        lines.append(f"Workflows: {workflow_names}")
    if ir.i18n.locales:
        rtl = ", ".join(ir.i18n.rtl_locales) if ir.i18n.rtl_locales else "none"
        lines.append(f"Locales: {', '.join(ir.i18n.locales)} (RTL: {rtl})")
    return "\n".join(lines)


def _extract_integration_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    items.extend(_extract_explicit_integration_items(prd_text))
    items.extend(_extract_stack_integration_items(prd_text))
    items.extend(_extract_endpoint_event_integration_items(prd_text))
    items.extend(_extract_capability_items(prd_text))
    items.extend(_extract_infra_dependency_items(prd_text))
    items.extend(_extract_heuristic_vendor_items(prd_text))
    return _merge_integration_items(items)


def _extract_explicit_integration_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)
    lines_with_offsets = _split_lines_with_offsets(prd_text)
    relevant_headers = ("integration", "system", "provider", "vendor", "capability", "status", "direction", "auth", "port")

    index = 0
    while index < len(lines_with_offsets):
        line, _offset = lines_with_offsets[index]
        if not _looks_like_table_row(line) or index + 1 >= len(lines_with_offsets):
            index += 1
            continue
        separator_line, _separator_offset = lines_with_offsets[index + 1]
        if not _looks_like_table_separator(separator_line):
            index += 1
            continue

        header_cells = [_normalize_table_header(cell) for cell in _split_table_row(line)]
        if not any(any(keyword in cell for keyword in relevant_headers) for cell in header_cells):
            index += 1
            continue

        row_index = index + 2
        while row_index < len(lines_with_offsets):
            row_line, row_offset = lines_with_offsets[row_index]
            if not _looks_like_table_row(row_line):
                break
            row_cells = _split_table_row(row_line)
            row_map = {
                header_cells[cell_index]: row_cells[cell_index].strip()
                for cell_index in range(min(len(header_cells), len(row_cells)))
                if header_cells[cell_index]
            }
            row_text = " | ".join(value for value in row_map.values() if value)
            if row_text:
                item = _explicit_item_from_text(
                    text=row_text,
                    heading=_heading_for_offset(prd_text, row_offset),
                    feature=_feature_for_offset(feature_index, row_offset),
                    source_kind="explicit_table",
                    row_map=row_map,
                )
                if item:
                    items.append(item)
            row_index += 1
        index = row_index

    for line, offset in lines_with_offsets:
        stripped = line.strip()
        if not stripped or stripped.startswith("|"):
            continue
        heading = _heading_for_offset(prd_text, offset)
        heading_lower = heading.lower()
        if not any(keyword in heading_lower for keyword in ("integrations", "dependencies", "external systems", "providers")):
            continue
        if not re.match(r"^(?:[-*]|\d+[.)])\s+", stripped):
            continue
        bullet_text = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", stripped).strip()
        if not bullet_text:
            continue
        item = _explicit_item_from_text(
            text=bullet_text,
            heading=heading,
            feature=_feature_for_offset(feature_index, offset),
            source_kind="integration_section",
        )
        if item:
            items.append(item)

    return items


def _extract_stack_integration_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)

    for heading, body, start, _end in _iter_sections(prd_text):
        heading_lower = heading.lower()
        if "stack" not in heading_lower and "technology" not in heading_lower:
            continue
        section_lower = body.lower()
        feature = _feature_for_offset(feature_index, start)

        for vendor, config in _VENDOR_REGISTRY.items():
            if config["kind"] != "service_provider":
                continue
            matched_terms = _find_matching_terms(section_lower, list(config["explicit_terms"]) + list(config["sdk_terms"]))
            if not matched_terms:
                continue
            items.append(
                _make_integration_item(
                    name=vendor,
                    kind=config["kind"],
                    vendor=vendor,
                    category=config["category"],
                    status="required",
                    implementation_mode=config["default_mode"],
                    direction="n/a",
                    auth_mode="",
                    port_name=config["port_name"],
                    feature=feature,
                    source_kind="technology_stack",
                    confidence="explicit",
                    heading=heading,
                    excerpt=_line_excerpt_containing_term(body, matched_terms[0]) or _normalize_excerpt(body),
                    matched_terms=matched_terms,
                )
            )

        for name, config in _INFRA_PATTERNS.items():
            matched_terms = _find_matching_terms(section_lower, list(config["terms"]))
            if not matched_terms:
                continue
            items.append(
                _make_integration_item(
                    name=name,
                    kind="infra_dependency",
                    vendor=name,
                    category=config["category"],
                    status="required",
                    implementation_mode="infra_only",
                    direction="internal",
                    auth_mode="",
                    port_name="",
                    feature=feature,
                    source_kind="technology_stack",
                    confidence="explicit",
                    heading=heading,
                    excerpt=_line_excerpt_containing_term(body, matched_terms[0]) or _normalize_excerpt(body),
                    matched_terms=matched_terms,
                )
            )

    return items


def _extract_endpoint_event_integration_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)
    seen: set[tuple[str, str]] = set()

    for endpoint in _extract_endpoints(prd_text):
        slug = _integration_slug_from_endpoint(endpoint.path)
        if not slug:
            continue
        key = ("endpoint", slug)
        if key in seen:
            continue
        seen.add(key)
        offset = max(prd_text.lower().find(endpoint.path.lower()), 0)
        heading = _heading_for_offset(prd_text, offset)
        feature = _feature_for_offset(feature_index, offset)
        context = _context_excerpt(prd_text, offset)
        status = _infer_status_from_text(context)
        items.append(
            _make_integration_item(
                name=_endpoint_system_name(slug, context),
                kind="external_system",
                vendor=_slug_to_title(slug),
                category="external_system",
                status=status,
                implementation_mode=_infer_mode_from_context(context, "external_system", status, "adapter_stub"),
                direction="inbound" if "webhook" in endpoint.path.lower() else _infer_direction_from_text(context),
                auth_mode=_infer_auth_from_text(context),
                port_name=_derive_port_name(_endpoint_system_name(slug, context), "external_system", "external_system"),
                feature=feature,
                source_kind="endpoint",
                confidence="high",
                heading=heading,
                excerpt=_line_excerpt_for_offset(prd_text, offset) or _normalize_excerpt(context),
                matched_terms=[endpoint.path],
            )
        )

    for match in re.finditer(r"\bintegration\.([a-z0-9_-]+)(?:[._][a-z0-9_-]+)+", prd_text.lower()):
        slug = match.group(1).strip("-_")
        if not slug:
            continue
        key = ("event", slug)
        if key in seen:
            continue
        seen.add(key)
        offset = match.start()
        heading = _heading_for_offset(prd_text, offset)
        feature = _feature_for_offset(feature_index, offset)
        context = _context_excerpt(prd_text, offset)
        status = _infer_status_from_text(context)
        items.append(
            _make_integration_item(
                name=_endpoint_system_name(slug, context),
                kind="external_system",
                vendor=_slug_to_title(slug),
                category="external_system",
                status=status,
                implementation_mode=_infer_mode_from_context(context, "external_system", status, "adapter_stub"),
                direction=_infer_direction_from_text(context),
                auth_mode=_infer_auth_from_text(context),
                port_name=_derive_port_name(_endpoint_system_name(slug, context), "external_system", "external_system"),
                feature=feature,
                source_kind="event",
                confidence="high",
                heading=heading,
                excerpt=_line_excerpt_for_offset(prd_text, offset) or _normalize_excerpt(context),
                matched_terms=[match.group(0)],
            )
        )

    return items


def _extract_capability_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)
    text_lower = prd_text.lower()

    for capability_name, config in _CAPABILITY_PATTERNS.items():
        matched_terms = _find_matching_terms(text_lower, list(config["terms"]))
        if not matched_terms:
            continue
        offset = _find_first_term_offset(prd_text, matched_terms)
        heading = _heading_for_offset(prd_text, offset) if offset >= 0 else ""
        feature = _feature_for_offset(feature_index, offset) if offset >= 0 else ""
        context = _context_excerpt(prd_text, offset) if offset >= 0 else prd_text
        status = _infer_status_from_text(context)
        items.append(
            _make_integration_item(
                name=capability_name,
                kind="capability",
                vendor="",
                category=capability_name,
                status=status,
                implementation_mode="capability_only",
                direction=_infer_direction_from_text(context),
                auth_mode="",
                port_name="",
                feature=feature,
                source_kind="heuristic",
                confidence="medium",
                heading=heading,
                excerpt=_line_excerpt_for_offset(prd_text, offset) or _normalize_excerpt(context),
                matched_terms=matched_terms,
            )
        )

    return items


def _extract_infra_dependency_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)
    text_lower = prd_text.lower()

    for infra_name, config in _INFRA_PATTERNS.items():
        matched_terms = _find_matching_terms(text_lower, list(config["terms"]))
        if not matched_terms:
            continue
        offset = _find_first_term_offset(prd_text, matched_terms)
        heading = _heading_for_offset(prd_text, offset) if offset >= 0 else ""
        feature = _feature_for_offset(feature_index, offset) if offset >= 0 else ""
        items.append(
            _make_integration_item(
                name=infra_name,
                kind="infra_dependency",
                vendor=infra_name,
                category=config["category"],
                status="required",
                implementation_mode="infra_only",
                direction="internal",
                auth_mode="",
                port_name="",
                feature=feature,
                source_kind="heuristic",
                confidence="medium",
                heading=heading,
                excerpt=_line_excerpt_for_offset(prd_text, offset) or _normalize_excerpt(prd_text),
                matched_terms=matched_terms,
            )
        )

    return items


def _extract_heuristic_vendor_items(prd_text: str) -> list[IntegrationItem]:
    items: list[IntegrationItem] = []
    feature_index = _build_feature_index(prd_text)
    text_lower = prd_text.lower()

    for vendor, config in _VENDOR_REGISTRY.items():
        matched_terms = _find_matching_terms(text_lower, list(config["explicit_terms"]) + list(config["sdk_terms"]))
        if not matched_terms:
            continue
        offset = _find_first_term_offset(prd_text, matched_terms)
        heading = _heading_for_offset(prd_text, offset) if offset >= 0 else ""
        feature = _feature_for_offset(feature_index, offset) if offset >= 0 else ""
        context = _context_excerpt(prd_text, offset) if offset >= 0 else prd_text
        status = _infer_status_from_text(context)
        confidence = _heuristic_vendor_confidence(vendor, config, context, matched_terms)
        items.append(
            _make_integration_item(
                name=vendor,
                kind=config["kind"],
                vendor=vendor,
                category=config["category"],
                status=status,
                implementation_mode=_infer_mode_from_context(context, config["kind"], status, config["default_mode"]),
                direction=_infer_direction_from_text(context),
                auth_mode=_infer_auth_from_text(context),
                port_name=config["port_name"],
                feature=feature,
                source_kind="heuristic",
                confidence=confidence,
                heading=heading,
                excerpt=_line_excerpt_for_offset(prd_text, offset) or _normalize_excerpt(context),
                matched_terms=matched_terms,
            )
        )

    return items


def _derive_legacy_integrations(items: list[IntegrationItem]) -> list[IntegrationSpec]:
    legacy_integrations: list[IntegrationSpec] = []
    for item in items:
        if item.kind not in {"external_system", "service_provider"}:
            continue
        if item.implementation_mode not in {"real_sdk", "adapter_stub"}:
            continue
        if item.status not in {"required", "stubbed"}:
            continue
        if _highest_item_confidence(item) not in {"explicit", "high"}:
            continue
        vendor = (item.vendor or item.name).strip()
        port_name = item.port_name.strip() or _derive_port_name(item.name or vendor, item.kind, item.category)
        if not vendor or not port_name:
            continue
        legacy_integrations.append(
            IntegrationSpec(
                vendor=vendor,
                type=_legacy_type_for_item(item),
                port_name=port_name,
                methods_used=_integration_method_hints_for_item(item),
            )
        )
    return legacy_integrations


def _integration_method_hints_for_item(item: IntegrationItem) -> list[str]:
    hints = list(_METHOD_HINTS.get(item.vendor or item.name, ()))
    evidence_texts = [evidence.excerpt.lower() for evidence in item.source_evidence if evidence.excerpt]
    methods: list[str] = []
    for hint in hints:
        if any(_contains_term(text, hint.lower()) for text in evidence_texts):
            methods.append(hint)
    return _dedupe_preserve_order(methods)


def _merge_integration_items(items: list[IntegrationItem]) -> list[IntegrationItem]:
    merged: dict[tuple[str, str, str], IntegrationItem] = {}

    for item in items:
        key = _integration_item_key(item)
        existing = merged.get(key)
        if existing is None:
            item.methods_used = _integration_method_hints_for_item(item)
            merged[key] = item
            continue

        existing.owner_features = _dedupe_preserve_order(existing.owner_features + item.owner_features)
        existing.source_evidence.extend(item.source_evidence)
        existing.source_evidence.sort(key=lambda evidence: (-_CONFIDENCE_ORDER.get(evidence.confidence, 0), -_SOURCE_KIND_ORDER.get(evidence.source_kind, 0)))

        if not existing.status:
            existing.status = item.status
        if existing.direction == "n/a" and item.direction != "n/a":
            existing.direction = item.direction
        if not existing.auth_mode and item.auth_mode:
            existing.auth_mode = item.auth_mode
        if not existing.port_name and item.port_name:
            existing.port_name = item.port_name
        if not existing.vendor and item.vendor:
            existing.vendor = item.vendor
        if not existing.category and item.category:
            existing.category = item.category
        if not existing.name and item.name:
            existing.name = item.name
        if existing.implementation_mode == "internal_module" and item.implementation_mode != "internal_module":
            existing.implementation_mode = item.implementation_mode
        if existing.implementation_mode == "capability_only" and item.implementation_mode in {"real_sdk", "adapter_stub"}:
            existing.implementation_mode = item.implementation_mode

        existing.methods_used = _dedupe_preserve_order(existing.methods_used + item.methods_used + _integration_method_hints_for_item(existing))

    return list(merged.values())


def _integration_item_key(item: IntegrationItem) -> tuple[str, str, str]:
    return (item.kind.strip().lower(), (item.vendor or item.name).strip().lower(), item.category.strip().lower())


def _heuristic_vendor_confidence(
    vendor: str,
    config: dict[str, Any],
    excerpt: str,
    matched_terms: list[str],
) -> str:
    excerpt_lower = excerpt.lower()
    explicit_terms = {str(term).lower() for term in config.get("explicit_terms", [])}
    sdk_terms = [str(term).lower() for term in config.get("sdk_terms", [])]
    if any(
        str(term).lower() in sdk_terms
        and (str(term).lower() not in explicit_terms or not str(term).lower().isalnum())
        for term in matched_terms
    ):
        return "high"

    method_hints = _METHOD_HINTS.get(vendor, ())
    if any(_contains_term(excerpt_lower, hint.lower()) for hint in method_hints):
        return "high"

    vendor_lower = vendor.lower()
    direct_use_patterns = (
        rf"\bvia\s+{re.escape(vendor_lower)}\b",
        rf"\bthrough\s+{re.escape(vendor_lower)}\b",
        rf"\busing\s+{re.escape(vendor_lower)}\b",
        rf"\buses?\s+{re.escape(vendor_lower)}\b",
        rf"\b{re.escape(vendor_lower)}\s+(?:webhook|handles|sends|receives|processes|syncs|verifies|delivers|authenticates)\b",
        rf"\b{re.escape(vendor_lower)}\b.*\bis used\b",
        rf"\bsent\s+(?:via|through)\s+{re.escape(vendor_lower)}\b",
    )
    if any(re.search(pattern, excerpt_lower) for pattern in direct_use_patterns):
        return "high"

    technical_terms = ("webhook", "provider", "api", "sdk", "client", "adapter", "receiver", "template", "sync", "integration")
    if _contains_term(excerpt_lower, vendor_lower) and any(_contains_term(excerpt_lower, term) for term in technical_terms):
        return "high"

    return "medium"


def _contains_term(text_lower: str, term: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", (text_lower or "").lower()).strip()
    normalized_term = re.sub(r"\s+", " ", (term or "").lower()).strip()
    if not normalized_text or not normalized_term:
        return False

    term_parts = normalized_term.split()
    if len(term_parts) > 1 and all(part.isalnum() for part in term_parts):
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in term_parts) + r"\b"
        return re.search(pattern, normalized_text) is not None
    if normalized_term.isalnum():
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_term in normalized_text


def _find_matching_terms(text_lower: str, terms: list[str]) -> list[str]:
    return _dedupe_preserve_order([term for term in terms if _contains_term(text_lower, term)])


def _normalize_excerpt(text: str, max_length: int = 180) -> str:
    excerpt = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(excerpt) <= max_length:
        return excerpt
    return excerpt[: max_length - 3].rstrip() + "..."


def _heading_for_offset(prd_text: str, offset: int) -> str:
    heading = ""
    for match in _FEATURE_HEADING_RE.finditer(prd_text):
        if match.start() > offset >= 0:
            break
        heading = match.group(2).strip()
    return heading


def _split_lines_with_offsets(prd_text: str) -> list[tuple[str, int]]:
    lines_with_offsets: list[tuple[str, int]] = []
    offset = 0
    for raw_line in prd_text.splitlines(keepends=True):
        lines_with_offsets.append((raw_line.rstrip("\r\n"), offset))
        offset += len(raw_line)
    if not lines_with_offsets and prd_text:
        lines_with_offsets.append((prd_text, 0))
    return lines_with_offsets


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _looks_like_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|").replace(" ", "")
    return bool(stripped) and all(char in "-:" for char in stripped)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_table_header(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _explicit_item_from_text(
    text: str,
    heading: str,
    feature: str,
    source_kind: str,
    row_map: dict[str, str] | None = None,
) -> IntegrationItem | None:
    row_map = row_map or {}
    combined_text = " | ".join([text] + [value for value in row_map.values() if value]).strip()
    heading_lower = heading.lower()
    status = _infer_status_from_text(combined_text)
    direction = _infer_direction_from_text(combined_text)
    auth_mode = _infer_auth_from_text(combined_text)
    port_name = _port_from_context(" ".join(value for key, value in row_map.items() if "port" in key) or combined_text)

    name_hint = ""
    for key in ("integration", "system", "provider", "vendor", "capability", "name"):
        for header, value in row_map.items():
            if key in header and value.strip():
                name_hint = value.strip()
                break
        if name_hint:
            break
    if not name_hint:
        name_hint = _extract_leading_name(text)

    vendor, matched_terms = _match_vendor_registry(f"{name_hint} {combined_text}")
    if vendor:
        config = _VENDOR_REGISTRY[vendor]
        return _make_integration_item(
            name=_normalize_named_item(name_hint or vendor),
            kind=config["kind"],
            vendor=vendor,
            category=config["category"],
            status=status,
            implementation_mode=_infer_mode_from_context(combined_text, config["kind"], status, config["default_mode"]),
            direction=direction,
            auth_mode=auth_mode,
            port_name=port_name or config["port_name"],
            feature=feature,
            source_kind=source_kind,
            confidence="explicit",
            heading=heading,
            excerpt=_normalize_excerpt(combined_text),
            matched_terms=matched_terms,
        )

    infra_name, matched_terms = _match_infra_registry(f"{name_hint} {combined_text}")
    if infra_name:
        config = _INFRA_PATTERNS[infra_name]
        return _make_integration_item(
            name=infra_name,
            kind="infra_dependency",
            vendor=infra_name,
            category=config["category"],
            status=status,
            implementation_mode="infra_only",
            direction="internal",
            auth_mode="",
            port_name="",
            feature=feature,
            source_kind=source_kind,
            confidence="explicit",
            heading=heading,
            excerpt=_normalize_excerpt(combined_text),
            matched_terms=matched_terms,
        )

    capability_matches = _capability_matches(combined_text)
    if capability_matches and (any("capability" in header for header in row_map) or "capability" in heading_lower or _is_generic_integration_name(name_hint)):
        capability_name = capability_matches[0]
        return _make_integration_item(
            name=capability_name,
            kind="capability",
            vendor="",
            category=capability_name,
            status=status,
            implementation_mode="capability_only",
            direction=direction,
            auth_mode="",
            port_name="",
            feature=feature,
            source_kind=source_kind,
            confidence="explicit",
            heading=heading,
            excerpt=_normalize_excerpt(combined_text),
            matched_terms=capability_matches,
        )

    cleaned_name = _normalize_named_item(name_hint or text)
    if not cleaned_name:
        return None
    if any(keyword in heading_lower for keyword in ("provider", "vendors")):
        kind = "service_provider"
        default_mode = "real_sdk"
    elif any(keyword in heading_lower for keyword in ("integrations", "external systems", "dependencies")):
        kind = "external_system"
        default_mode = "adapter_stub"
    else:
        return None

    category = _infer_category_from_text(combined_text, kind)
    return _make_integration_item(
        name=cleaned_name,
        kind=kind,
        vendor=_derive_vendor_name(cleaned_name) if kind in {"external_system", "service_provider"} else "",
        category=category,
        status=status,
        implementation_mode=_infer_mode_from_context(combined_text, kind, status, default_mode),
        direction=direction,
        auth_mode=auth_mode,
        port_name=port_name or _derive_port_name(cleaned_name, kind, category),
        feature=feature,
        source_kind=source_kind,
        confidence="explicit",
        heading=heading,
        excerpt=_normalize_excerpt(combined_text),
        matched_terms=[],
    )


def _match_vendor_registry(text: str) -> tuple[str, list[str]]:
    text_lower = text.lower()
    for vendor, config in _VENDOR_REGISTRY.items():
        matched_terms = _find_matching_terms(text_lower, list(config["explicit_terms"]) + list(config["sdk_terms"]))
        if matched_terms:
            return vendor, matched_terms
    return "", []


def _match_infra_registry(text: str) -> tuple[str, list[str]]:
    text_lower = text.lower()
    for infra_name, config in _INFRA_PATTERNS.items():
        matched_terms = _find_matching_terms(text_lower, list(config["terms"]))
        if matched_terms:
            return infra_name, matched_terms
    return "", []


def _capability_matches(text: str) -> list[str]:
    text_lower = text.lower()
    matched: list[str] = []
    for capability_name, config in _CAPABILITY_PATTERNS.items():
        if _find_matching_terms(text_lower, list(config["terms"])):
            matched.append(capability_name)
    return _dedupe_preserve_order(matched)


def _find_first_term_offset(prd_text: str, terms: list[str]) -> int:
    for line, offset in _split_lines_with_offsets(prd_text):
        line_lower = line.lower()
        for term in terms:
            match_start = _term_match_start(line_lower, term)
            if match_start is not None:
                return offset + match_start
    return -1


def _term_match_start(text_lower: str, term: str) -> int | None:
    normalized_text = re.sub(r"\s+", " ", (text_lower or "").lower()).strip()
    normalized_term = re.sub(r"\s+", " ", (term or "").lower()).strip()
    if not normalized_text or not normalized_term:
        return None

    term_parts = normalized_term.split()
    if len(term_parts) > 1 and all(part.isalnum() for part in term_parts):
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in term_parts) + r"\b"
        match = re.search(pattern, normalized_text)
        return match.start() if match else None
    if normalized_term.isalnum():
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
        match = re.search(pattern, normalized_text)
        return match.start() if match else None
    match_start = normalized_text.find(normalized_term)
    return match_start if match_start >= 0 else None


def _line_excerpt_for_offset(prd_text: str, offset: int) -> str:
    if offset < 0:
        return ""
    line_start = prd_text.rfind("\n", 0, offset) + 1
    line_end = prd_text.find("\n", offset)
    if line_end == -1:
        line_end = len(prd_text)
    return _normalize_excerpt(prd_text[line_start:line_end])


def _line_excerpt_containing_term(text: str, term: str) -> str:
    for line in text.splitlines():
        if _contains_term(line.lower(), term):
            return _normalize_excerpt(line)
    return ""


def _context_excerpt(prd_text: str, offset: int, radius: int = 160) -> str:
    if offset < 0:
        return _normalize_excerpt(prd_text[: radius * 2])
    start = max(0, offset - radius)
    end = min(len(prd_text), offset + radius)
    return _normalize_excerpt(prd_text[start:end])


def _extract_leading_name(text: str) -> str:
    cleaned = re.sub(r"`", "", str(text or "")).strip()
    cleaned = re.sub(r"\s+\((?:required|optional|stubbed|future|deferred)[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    leading = re.split(r"\s+-\s+|:\s+|\bvia\b|\bstatus\b|\bauth\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    return leading.strip(" -*:|")


def _normalize_named_item(name: str) -> str:
    cleaned = re.sub(r"`", "", str(name or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(webhook receiver|adapter|provider|integration)\b$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+\((?:required|optional|stubbed|future|deferred)[^)]*\)", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" -*:|")


def _is_generic_integration_name(name: str) -> bool:
    lowered = str(name or "").strip().lower()
    return lowered in {"", "integration", "integrations", "provider", "providers", "capability", "capabilities", "dependency", "dependencies"}


def _infer_status_from_text(text: str) -> str:
    text_lower = text.lower()
    if "not implemented in this build" in text_lower or "deferred" in text_lower:
        return "deferred"
    if "future" in text_lower:
        return "future"
    if "stubbed" in text_lower or "stub " in text_lower or text_lower.endswith(" stub"):
        return "stubbed"
    if "optional" in text_lower or "may be configured later" in text_lower:
        return "optional"
    return "required"


def _infer_direction_from_text(text: str) -> str:
    text_lower = f" {text.lower()} "
    inbound = any(keyword in text_lower for keyword in (" inbound ", " webhook receiver ", " receives webhook ", " receive webhook "))
    outbound = any(keyword in text_lower for keyword in (" outbound ", " send webhook ", " dispatch webhook ", " callback "))
    if inbound and outbound:
        return "bidirectional"
    if inbound:
        return "inbound"
    if outbound:
        return "outbound"
    if " internal " in text_lower:
        return "internal"
    return "n/a"


def _infer_auth_from_text(text: str) -> str:
    text_lower = text.lower()
    if "oauth" in text_lower:
        return "OAuth"
    if "api key" in text_lower or "api_key" in text_lower or "apikey" in text_lower:
        return "API_KEY"
    if "hmac" in text_lower:
        return "HMAC"
    if "basic auth" in text_lower:
        return "Basic"
    if "jwt" in text_lower or "bearer" in text_lower:
        return "JWT"
    return ""


def _infer_mode_from_context(text: str, kind: str, status: str, default_mode: str) -> str:
    if kind == "infra_dependency":
        return "infra_only"
    if kind == "capability":
        return "capability_only"

    text_lower = text.lower()
    if "anti-corruption layer" in text_lower or "adapter" in text_lower or "webhook receiver" in text_lower:
        return "adapter_stub"
    if status == "stubbed":
        return "adapter_stub"
    if kind == "external_system":
        return "adapter_stub"
    return default_mode


def _port_from_context(text: str) -> str:
    match = re.search(r"\bI[A-Z][A-Za-z0-9]+(?:Client|Provider|Port)\b", text)
    return match.group(0) if match else ""


def _infer_category_from_text(text: str, kind: str) -> str:
    if kind == "external_system":
        return "external_system"
    if kind == "service_provider":
        matches = _capability_matches(text)
        return matches[0] if matches else "provider"
    matches = _capability_matches(text)
    if matches:
        return matches[0]
    return ""


def _derive_vendor_name(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return ""
    return words[0].capitalize()


def _derive_port_name(name: str, kind: str, category: str) -> str:
    if kind == "external_system":
        base = "".join(part.capitalize() for part in re.findall(r"[A-Za-z0-9]+", name))
        return f"I{base}Client" if base else ""
    if kind == "service_provider":
        if category in _PORT_BY_CATEGORY:
            return _PORT_BY_CATEGORY[category]
        base = "".join(part.capitalize() for part in re.findall(r"[A-Za-z0-9]+", name))
        return f"I{base}Provider" if base else ""
    return ""


def _make_integration_item(
    name: str,
    kind: str,
    vendor: str,
    category: str,
    status: str,
    implementation_mode: str,
    direction: str,
    auth_mode: str,
    port_name: str,
    feature: str,
    source_kind: str,
    confidence: str,
    heading: str,
    excerpt: str,
    matched_terms: list[str],
) -> IntegrationItem:
    normalized_name = _normalize_named_item(name)
    item = IntegrationItem(
        id=_slugify(f"{kind}-{vendor or normalized_name or category}"),
        name=normalized_name,
        kind=kind,
        vendor=vendor,
        category=category,
        status=status,
        implementation_mode=implementation_mode,
        direction=direction,
        auth_mode=auth_mode,
        port_name=port_name or _derive_port_name(normalized_name or vendor, kind, category),
        methods_used=[],
        owner_features=[feature] if feature and feature != "unknown" else [],
        source_evidence=[
            IntegrationEvidence(
                source_kind=source_kind,
                confidence=confidence,
                heading=heading,
                excerpt=_normalize_excerpt(excerpt),
                matched_terms=_dedupe_preserve_order(matched_terms),
            )
        ],
    )
    item.methods_used = _integration_method_hints_for_item(item)
    return item


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "integration-item"


def _integration_slug_from_endpoint(path: str) -> str:
    path_lower = path.lower()
    for pattern in (r"/integrations/([a-z0-9_-]+)/", r"/integration/([a-z0-9_-]+)/", r"/webhooks?/([a-z0-9_-]+)/"):
        match = re.search(pattern, path_lower)
        if match:
            return match.group(1).strip("-_")
    return ""


def _endpoint_system_name(slug: str, context: str) -> str:
    system_name = _slug_to_title(slug)
    if "handover" in context.lower():
        return f"{system_name} Handover"
    return system_name


def _slug_to_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", slug) if part)


def _highest_item_confidence(item: IntegrationItem) -> str:
    if not item.source_evidence:
        return "low"
    return max(item.source_evidence, key=lambda evidence: _CONFIDENCE_ORDER.get(evidence.confidence, 0)).confidence


def _legacy_type_for_item(item: IntegrationItem) -> str:
    if item.vendor in _VENDOR_REGISTRY:
        return str(_VENDOR_REGISTRY[item.vendor].get("legacy_type") or item.category or item.kind)
    if item.kind == "external_system":
        return item.category or "external_system"
    return item.category or item.kind or "integration"


def _integration_display_name(item: IntegrationItem) -> str:
    return item.name or item.vendor or item.category or item.id


def _extract_project_name(prd_text: str) -> str:
    for pattern in (_PROJECT_TITLE_RE, _PROJECT_NAME_RE):
        match = pattern.search(prd_text)
        if match:
            return match.group(1).strip().strip("#").strip()
    return ""


def _convert_business_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(entity) for entity in entities]


def _convert_state_machines(state_machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(state_machine) for state_machine in state_machines]


def _convert_business_rules(business_rules: list[BusinessRule]) -> list[dict[str, Any]]:
    return [asdict(rule) for rule in business_rules]


def _convert_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(event) for event in events]


def _detect_stack(parsed_prd: ParsedPRD, prd_text: str) -> StackTarget:
    hints = parsed_prd.technology_hints or {}
    text_lower = prd_text.lower()

    backend = _detect_backend_stack(hints, text_lower)
    frontend = _detect_frontend_stack(hints, text_lower)
    db = _detect_database_stack(hints, text_lower)
    mobile = _detect_mobile_stack(text_lower)

    if frontend == "Flutter" and not mobile:
        mobile = "Flutter"

    return StackTarget(backend=backend, frontend=frontend, db=db, mobile=mobile)


def _detect_backend_stack(hints: dict[str, str | None], text_lower: str) -> str:
    framework = (hints.get("framework") or "").lower()
    language = (hints.get("language") or "").lower()
    if "nest" in framework or "nest" in text_lower or "nest.js" in text_lower:
        return "NestJS"
    if "fastapi" in framework or "fastapi" in text_lower:
        return "FastAPI"
    if "spring" in framework or "spring boot" in text_lower:
        return "Spring Boot"
    if "asp.net" in framework or "asp.net" in text_lower:
        return "ASP.NET"
    if "python" in language and "api" in text_lower:
        return "Python"
    return ""


def _detect_frontend_stack(hints: dict[str, str | None], text_lower: str) -> str:
    framework = (hints.get("framework") or "").lower()
    if "next.js" in framework or "nextjs" in framework or "next.js" in text_lower or "nextjs" in text_lower:
        return "Next.js"
    if "react native" in framework or "react native" in text_lower:
        return "React Native"
    if "react" in framework or "react" in text_lower:
        return "React"
    if "angular" in framework or "angular" in text_lower:
        return "Angular"
    if "flutter" in framework or "flutter" in text_lower:
        return "Flutter"
    return ""


def _detect_mobile_stack(text_lower: str) -> Optional[str]:
    if "react native" in text_lower:
        return "React Native"
    if "flutter" in text_lower:
        return "Flutter"
    return None


def _detect_database_stack(hints: dict[str, str | None], text_lower: str) -> str:
    database = (hints.get("database") or "").lower()
    if "postgres" in database or "postgres" in text_lower:
        return "PostgreSQL"
    if "mysql" in database or "mysql" in text_lower:
        return "MySQL"
    if "mongodb" in database or "mongo" in text_lower:
        return "MongoDB"
    if "sqlite" in database or "sqlite" in text_lower:
        return "SQLite"
    if "redis" in database or "redis" in text_lower:
        return "Redis"
    if "supabase" in database or "supabase" in text_lower:
        return "Supabase"
    return ""


def _build_feature_index(prd_text: str) -> list[tuple[int, str]]:
    feature_index: list[tuple[int, str]] = []
    for match in _FEATURE_HEADING_RE.finditer(prd_text):
        heading_text = match.group(2).strip()
        feature_id = _feature_id_from_heading(heading_text)
        if feature_id:
            feature_index.append((match.start(), feature_id))
    return feature_index


def _feature_id_from_heading(heading_text: str) -> str:
    match = _FEATURE_ID_RE.search(heading_text)
    if not match:
        return ""
    return f"F-{int(match.group(1)):03d}"


def _feature_for_offset(feature_index: list[tuple[int, str]], offset: int) -> str:
    feature = "unknown"
    for feature_offset, feature_id in feature_index:
        if feature_offset <= offset:
            feature = feature_id
        else:
            break
    return feature


def _extract_endpoints(prd_text: str) -> list[EndpointSpec]:
    feature_index = _build_feature_index(prd_text)
    seen: set[tuple[str, str]] = set()
    endpoints: list[EndpointSpec] = []

    for match in re.finditer(r"^\|.*\|$", prd_text, re.MULTILINE):
        line = match.group(0)
        spec = _endpoint_from_table_row(line)
        if not spec:
            continue
        spec.owner_feature = _feature_for_offset(feature_index, match.start())
        key = (spec.method, spec.path)
        if key not in seen:
            seen.add(key)
            endpoints.append(spec)

    for match in _ENDPOINT_PROSE_RE.finditer(prd_text):
        method = match.group("method").upper()
        path = _clean_endpoint_path(match.group("path"))
        if method not in _ENDPOINT_METHODS:
            continue
        spec = EndpointSpec(
            method=method,
            path=path,
            auth=_detect_endpoint_auth(prd_text, match.start(), match.end()),
            owner_feature=_feature_for_offset(feature_index, match.start()),
            description=_extract_endpoint_description(prd_text, match.start(), match.end()),
        )
        key = (spec.method, spec.path)
        if key not in seen:
            seen.add(key)
            endpoints.append(spec)

    for block_match in _ENDPOINT_CODEBLOCK_RE.finditer(prd_text):
        block_text = block_match.group(0)
        for endpoint_match in _ENDPOINT_PROSE_RE.finditer(block_text):
            method = endpoint_match.group("method").upper()
            path = _clean_endpoint_path(endpoint_match.group("path"))
            if method not in _ENDPOINT_METHODS:
                continue
            absolute_start = block_match.start() + endpoint_match.start()
            absolute_end = block_match.start() + endpoint_match.end()
            spec = EndpointSpec(
                method=method,
                path=path,
                auth=_detect_endpoint_auth(prd_text, absolute_start, absolute_end),
                owner_feature=_feature_for_offset(feature_index, block_match.start()),
                description=_extract_endpoint_description(prd_text, absolute_start, absolute_end),
            )
            key = (spec.method, spec.path)
            if key not in seen:
                seen.add(key)
                endpoints.append(spec)

    return endpoints


def _endpoint_from_table_row(line: str) -> EndpointSpec | None:
    cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
    if len(cells) < 2:
        return None

    method = cells[0].upper()
    path = _clean_endpoint_path(cells[1])
    if method not in _ENDPOINT_METHODS or not path.startswith("/"):
        return None

    auth = _normalize_text_cell(cells[2]) if len(cells) > 2 else ""
    request_cell = _normalize_text_cell(cells[3]) if len(cells) > 3 else ""
    response_cell = _normalize_text_cell(cells[4]) if len(cells) > 4 else ""

    request_fields = _field_specs_from_cell(request_cell, fallback_name="request")
    response_fields = _field_specs_from_cell(response_cell, fallback_name="response")

    return EndpointSpec(
        method=method,
        path=path,
        auth=auth,
        request_fields=request_fields,
        response_fields=response_fields,
    )


def _field_specs_from_cell(cell_text: str, fallback_name: str) -> list[dict[str, Any]]:
    if not cell_text or cell_text in {"-", "none", "n/a"}:
        return []
    field_name = fallback_name
    field_type = cell_text
    if ":" in cell_text:
        left, right = cell_text.split(":", 1)
        field_name = left.strip() or fallback_name
        field_type = right.strip() or cell_text
    return [{"name": field_name, "type": field_type, "required": True}]


def _clean_endpoint_path(path: str) -> str:
    cleaned = path.strip().strip("`").rstrip(".,;")
    return cleaned


def _normalize_text_cell(text: str) -> str:
    normalized = text.strip().strip("`")
    if normalized in {"-", "none", "n/a", ""}:
        return ""
    return normalized


def _detect_endpoint_auth(prd_text: str, start: int, end: int) -> str:
    line_start = prd_text.rfind("\n", 0, start) + 1
    line_end = prd_text.find("\n", end)
    if line_end == -1:
        line_end = len(prd_text)
    context = prd_text[line_start:line_end].lower()
    if "jwt" in context or "bearer" in context:
        return "JWT"
    if "api key" in context or "apikey" in context or "api_key" in context:
        return "API_KEY"
    if "oauth" in context:
        return "OAuth"
    if "none" in context:
        return "none"
    return ""


def _extract_endpoint_description(prd_text: str, start: int, end: int) -> str:
    line_start = prd_text.rfind("\n", 0, start) + 1
    line_end = prd_text.find("\n", end)
    if line_end == -1:
        line_end = len(prd_text)
    line = prd_text[line_start:line_end].strip()
    remainder = line[end - line_start :].strip()
    if not remainder:
        return ""
    remainder = re.sub(r"^[\s:—-]+", "", remainder)
    return remainder.strip()


def _extract_acs_with_evidence(prd_text: str) -> list[AcceptanceCriterion]:
    acs: list[AcceptanceCriterion] = []
    for ac in _extract_acceptance_criteria(prd_text):
        verification_mode = _infer_verification_mode(ac.text)
        required_evidence = _required_evidence_for_mode(verification_mode)
        acs.append(
            AcceptanceCriterion(
                id=ac.id,
                feature=_normalize_feature_ref(ac.feature),
                text=ac.text,
                verification_mode=verification_mode,
                required_evidence=required_evidence,
                verifiable_statically=verification_mode == "code_span",
            )
        )
    return acs


def _extract_acceptance_criteria(prd_text: str) -> list[AcceptanceCriterion]:
    feature_index = _build_feature_index(prd_text)
    matches: list[tuple[int, str, str]] = []

    for pattern in _AC_PATTERNS:
        for match in pattern.finditer(prd_text):
            ac_id = _normalize_ac_id(match.group(1))
            text = _clean_ac_text(match.group(2))
            if ac_id and text:
                matches.append((match.start(), ac_id, text))

    matches.sort(key=lambda item: item[0])

    seen_ids: set[str] = set()
    acceptance_criteria: list[AcceptanceCriterion] = []
    for offset, ac_id, text in matches:
        if ac_id in seen_ids:
            continue
        seen_ids.add(ac_id)
        acceptance_criteria.append(
            AcceptanceCriterion(
                id=ac_id,
                feature=_normalize_feature_ref(_feature_for_offset(feature_index, offset)),
                text=text,
            )
        )

    return acceptance_criteria


def _normalize_ac_id(ac_id: str) -> str:
    normalized = str(ac_id or "").strip().strip("[]*`|")
    return normalized.replace("_", "-").upper()


def _clean_ac_text(text: str) -> str:
    cleaned = str(text or "").strip().strip("|").strip()
    if "|" in cleaned:
        cleaned = cleaned.split("|", 1)[0].strip()
    return re.sub(r"\s+", " ", cleaned)


def _infer_verification_mode(ac_text: str) -> str:
    text_lower = ac_text.lower()
    if re.search(r"returns?\s+(?:401|403|404|500)\b", text_lower) or any(
        token in text_lower for token in ("401/403/404/500", "returns 401", "returns 403", "returns 404", "returns 500")
    ):
        return "http_transcript"
    if any(token in text_lower for token in ("displays", "shows", "renders")):
        return "playwright_trace"
    if (
        any(token in text_lower for token in ("stores", "saves", "creates"))
        and any(token in text_lower for token in ("database", "db", "persistence", "persisted"))
    ):
        return "db_assertion"
    if (
        any(token in text_lower for token in ("send", "sends", "dispatch", "emit", "publish"))
        and any(token in text_lower for token in ("notification", "email", "push"))
    ):
        return "simulator_state"
    return "code_span"


def _required_evidence_for_mode(verification_mode: str) -> list[str]:
    if verification_mode == "http_transcript":
        return ["http_transcript", "code_span"]
    if verification_mode == "playwright_trace":
        return ["playwright_trace", "code_span"]
    if verification_mode == "db_assertion":
        return ["db_assertion", "code_span"]
    if verification_mode == "simulator_state":
        return ["simulator_state", "code_span"]
    return ["code_span"]


def _detect_integrations(prd_text: str) -> list[IntegrationSpec]:
    return _derive_legacy_integrations(_extract_integration_items(prd_text))


def _extract_workflows(prd_text: str) -> list[WorkflowSpec]:
    feature_index = _build_feature_index(prd_text)
    workflows: list[WorkflowSpec] = []
    seen: set[tuple[str, str]] = set()

    for heading, body, start, _end in _iter_sections(prd_text):
        heading_lower = heading.lower()
        body_lower = body.lower()
        if not _is_workflow_section(heading_lower, body_lower):
            continue

        name = _clean_heading_name(heading)
        feature = _feature_for_offset(feature_index, start)
        steps = _extract_workflow_steps(body)
        actors = _extract_workflow_actors(body_lower)
        triggers = _extract_workflow_triggers(body_lower)

        key = (name, feature)
        if key in seen:
            continue
        seen.add(key)
        workflows.append(
            WorkflowSpec(
                name=name,
                feature=feature,
                actors=actors,
                steps=steps,
                triggers=triggers,
            )
        )

    return workflows


def _iter_sections(prd_text: str) -> list[tuple[str, str, int, int]]:
    headings = list(_FEATURE_HEADING_RE.finditer(prd_text))
    sections: list[tuple[str, str, int, int]] = []
    for index, match in enumerate(headings):
        heading = match.group(2).strip()
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(prd_text)
        sections.append((heading, prd_text[start:end], match.start(), end))
    return sections


def _is_workflow_section(heading_lower: str, body_lower: str) -> bool:
    if any(keyword in heading_lower for keyword in ("workflow", "flow", "journey", "process", "lifecycle")):
        return True
    if "workflow" in body_lower and "step" in body_lower:
        return True
    return False


def _clean_heading_name(heading: str) -> str:
    cleaned = re.sub(r"^(?:workflow|flow|process|journey)\s*[:\-]\s*", "", heading, flags=re.IGNORECASE)
    return cleaned.strip() or heading.strip()


def _extract_workflow_steps(body: str) -> list[str]:
    steps: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"(?:step\s+\d+[:.)]?|[-*]|\d+[.)])\s+(.+)$", stripped, re.IGNORECASE)
        if match:
            steps.append(match.group(1).strip())
    return _dedupe_preserve_order(steps)


def _extract_workflow_actors(body_lower: str) -> list[str]:
    actors = [actor for actor in _ACTOR_KEYWORDS if actor in body_lower]
    return _dedupe_preserve_order(actors)


def _extract_workflow_triggers(body_lower: str) -> list[str]:
    triggers = [trigger for trigger in _TRIGGER_KEYWORDS if trigger in body_lower]
    return _dedupe_preserve_order(triggers)


def _detect_i18n(prd_text: str) -> I18nSpec:
    search_text = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", " ", prd_text)
    locales = [
        locale
        for locale, patterns in _LOCALE_PATTERNS.items()
        if any(re.search(pattern, search_text, re.IGNORECASE) for pattern in patterns)
    ]
    locales = _dedupe_preserve_order(locales) or ["en"]
    rtl_locales = [locale for locale in locales if locale in _RTL_LOCALES]
    return I18nSpec(locales=locales, rtl_locales=rtl_locales, default_locale="en")


def _build_milestone_hints(ir: ProductIR) -> list[dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}

    for endpoint in ir.endpoints:
        feature = _normalize_feature_ref(endpoint.owner_feature) or "unassigned"
        entry = features.setdefault(feature, {"feature": feature, "endpoints": [], "entities": [], "acs": []})
        entry["endpoints"].append({"method": endpoint.method, "path": endpoint.path})

    for ac in ir.acceptance_criteria:
        feature = _normalize_feature_ref(ac.feature) or "unassigned"
        entry = features.setdefault(feature, {"feature": feature, "endpoints": [], "entities": [], "acs": []})
        entry["acs"].append(ac.id)

    for entity in ir.entities:
        feature = _normalize_feature_ref(
            entity.get("owner_feature") or entity.get("owner_milestone_hint") or ""
        ) or "unassigned"
        entry = features.setdefault(feature, {"feature": feature, "endpoints": [], "entities": [], "acs": []})
        entry["entities"].append(entity.get("name", ""))

    return list(features.values())


def _ir_to_dict(ir: ProductIR) -> dict[str, Any]:
    return asdict(ir)


def _ac_to_dict(ac: AcceptanceCriterion) -> dict[str, Any]:
    return asdict(ac)


def _integration_to_dict(integration: IntegrationSpec) -> dict[str, Any]:
    return asdict(integration)


def _integration_item_to_dict(item: IntegrationItem) -> dict[str, Any]:
    return asdict(item)


def _format_stack_target(stack_target: StackTarget) -> str:
    backend = stack_target.backend or "unknown"
    frontend = stack_target.frontend or "unknown"
    db = stack_target.db or "unknown"
    parts = [backend, frontend, db]
    if stack_target.mobile:
        parts.append(stack_target.mobile)
    return " + ".join(parts)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _normalize_feature_ref(feature: str) -> str:
    match = _FEATURE_ID_RE.search(feature or "")
    if not match:
        return feature
    return f"F-{int(match.group(1)):03d}"
