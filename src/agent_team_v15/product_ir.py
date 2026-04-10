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
    schema_version: int = 1
    project_name: str = ""
    stack_target: StackTarget = field(default_factory=StackTarget)
    entities: list[dict[str, Any]] = field(default_factory=list)
    state_machines: list[dict[str, Any]] = field(default_factory=list)
    business_rules: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    endpoints: list[EndpointSpec] = field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    integrations: list[IntegrationSpec] = field(default_factory=list)
    workflows: list[WorkflowSpec] = field(default_factory=list)
    i18n: I18nSpec = field(default_factory=I18nSpec)


_INTEGRATION_PATTERNS: dict[str, dict[str, Any]] = {
    "Stripe": {
        "type": "payment",
        "port_name": "IPaymentProvider",
        "strong_keywords": ["stripe", "payment_intent", "paymentintent", "stripe webhook"],
        "medium_pairs": [("payment", "webhook"), ("payment", "provider")],
    },
    "Twilio": {
        "type": "sms",
        "port_name": "ISmsProvider",
        "strong_keywords": ["twilio", "twilio-node", "@twilio"],
        "medium_pairs": [("sms", "provider"), ("sms", "verification")],
    },
    "AWS_S3": {
        "type": "file_storage",
        "port_name": "IFileStorageProvider",
        "strong_keywords": ["aws-sdk", "@aws-sdk/client-s3", "s3 bucket"],
        "medium_pairs": [("file upload", "storage"), ("blob", "storage")],
    },
    "Redis": {
        "type": "cache",
        "port_name": "ICacheProvider",
        "strong_keywords": ["redis", "ioredis", "bullmq"],
        "medium_pairs": [("cache", "session"), ("queue", "worker")],
    },
    "RabbitMQ": {
        "type": "message_queue",
        "port_name": "IMessageQueueProvider",
        "strong_keywords": ["rabbitmq", "amqp", "amqplib"],
        "medium_pairs": [("message queue", "consumer"), ("message broker", "publish")],
    },
    "Kafka": {
        "type": "event_stream",
        "port_name": "IEventStreamProvider",
        "strong_keywords": ["kafka", "kafkajs", "confluent"],
        "medium_pairs": [("event stream", "producer"), ("event stream", "consumer")],
    },
    "Elasticsearch": {
        "type": "search",
        "port_name": "ISearchProvider",
        "strong_keywords": ["elasticsearch", "@elastic/elasticsearch", "opensearch"],
        "medium_pairs": [("full-text search", "index"), ("search engine", "query")],
    },
    "Odoo": {
        "type": "erp",
        "port_name": "IOdooClient",
        "strong_keywords": ["odoo", "json-rpc", "xmlrpc", "search_read", "odoo api"],
        "medium_pairs": [("erp", "sync"), ("erp", "integration")],
    },
    "Firebase": {
        "type": "push_notification",
        "port_name": "IPushNotificationProvider",
        "strong_keywords": ["fcm", "firebase", "firebase-admin", "cloud messaging"],
        "medium_pairs": [("push notification", "token"), ("push notification", "device")],
    },
    "SendGrid": {
        "type": "email",
        "port_name": "IEmailProvider",
        "strong_keywords": ["sendgrid", "@sendgrid", "sgmail"],
        "medium_pairs": [("magic link", "email"), ("transactional email", "template")],
    },
}

_METHOD_HINTS: dict[str, tuple[str, ...]] = {
    "Stripe": ("createPaymentIntent", "handleWebhook", "confirmPaymentIntent", "refundPayment"),
    "Odoo": ("search_read", "execute_kw", "create", "write", "unlink"),
    "Firebase": ("send", "subscribeToTopic", "unsubscribeFromTopic", "sendMulticast"),
    "SendGrid": ("send", "sendEmail", "sendTemplatedEmail", "sendMultiple"),
}


def compile_product_ir(prd_path: Path, parsed_prd: ParsedPRD | None = None) -> ProductIR:
    """Compile a PRD file into a typed Product IR."""
    prd_text = prd_path.read_text(encoding="utf-8")
    if parsed_prd is None:
        parsed_prd = parse_prd(prd_text)

    project_name = parsed_prd.project_name or _extract_project_name(prd_text) or prd_path.stem

    return ProductIR(
        project_name=project_name,
        stack_target=_detect_stack(parsed_prd, prd_text),
        entities=_convert_business_entities(parsed_prd.entities),
        state_machines=_convert_state_machines(parsed_prd.state_machines),
        business_rules=_convert_business_rules(parsed_prd.business_rules),
        events=_convert_events(parsed_prd.events),
        endpoints=_extract_endpoints(prd_text),
        acceptance_criteria=_extract_acs_with_evidence(prd_text),
        integrations=_detect_integrations(prd_text),
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
    if ir.integrations:
        lines.append("External Integrations: " + ", ".join(sorted({i.vendor for i in ir.integrations})))
    if ir.workflows:
        workflow_names = ", ".join(w.name for w in ir.workflows[:10])
        lines.append(f"Workflows: {workflow_names}")
    if ir.i18n.locales:
        rtl = ", ".join(ir.i18n.rtl_locales) if ir.i18n.rtl_locales else "none"
        lines.append(f"Locales: {', '.join(ir.i18n.locales)} (RTL: {rtl})")
    return "\n".join(lines)


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
    text_lower = prd_text.lower()
    integrations: list[IntegrationSpec] = []
    for vendor, config in _INTEGRATION_PATTERNS.items():
        strong_matches = sum(1 for keyword in config["strong_keywords"] if keyword in text_lower)
        medium_matches = sum(
            1 for pair in config["medium_pairs"] if all(part in text_lower for part in pair)
        )
        if strong_matches >= 1 or medium_matches >= 2:
            integrations.append(
                IntegrationSpec(
                    vendor=vendor,
                    type=config["type"],
                    port_name=config["port_name"],
                    methods_used=_detect_integration_methods(vendor, text_lower),
                )
            )
    return integrations


def _detect_integration_methods(vendor: str, text_lower: str) -> list[str]:
    methods: list[str] = []
    for method in _METHOD_HINTS.get(vendor, ()):
        if method.lower() in text_lower:
            methods.append(method)
    return _dedupe_preserve_order(methods)


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
