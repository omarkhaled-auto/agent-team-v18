"""PRD Agent — generates parser-perfect PRDs from any input.

A structured pipeline that takes rough requirements and produces a PRD
formatted EXACTLY as the v16 parser expects. Validates against the actual
parse_prd() function — if the parser can't extract it, the PRD is wrong.

Pipeline:
  Session 1: Comprehension + gap/contradiction detection → user checkpoint
  Session 2: Full expansion (entities, SMs, events, endpoints, frontend) → assembled PRD
  Validation: parse_prd() + contract_generator → fix loop if needed

Three public functions:
  generate_prd() — full pipeline from rough input
  improve_prd() — fix/expand an existing PRD
  validate_prd() — check parser extraction and report gaps
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Result of validating a PRD against the v16 parser."""
    entities_extracted: int = 0
    entities_with_fields: int = 0
    state_machines_extracted: int = 0
    events_extracted: int = 0
    technology_detected: bool = False
    project_name: str = ""
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.entities_extracted >= 3 and len(self.issues) == 0

    @property
    def score(self) -> float:
        """Quality score 0.0-1.0."""
        if self.entities_extracted == 0:
            return 0.0
        points = 0.0
        points += min(self.entities_extracted / 10, 1.0) * 0.3  # Entities
        points += min(self.entities_with_fields / max(self.entities_extracted, 1), 1.0) * 0.2
        points += min(self.state_machines_extracted / max(self.entities_extracted * 0.3, 1), 1.0) * 0.2
        points += min(self.events_extracted / max(self.entities_extracted * 0.5, 1), 1.0) * 0.2
        points += (0.1 if self.technology_detected else 0.0)
        return round(points, 2)


@dataclass
class PrdResult:
    """Result of PRD generation or improvement."""
    prd_text: str = ""
    validation: ValidationReport = field(default_factory=ValidationReport)
    checkpoint_message: str = ""  # For user review before expansion
    cost_usd: float = 0.0
    fix_iterations: int = 0


# ---------------------------------------------------------------------------
# Format template (extracted from GlobalBooks PRD — parser-proven format)
# ---------------------------------------------------------------------------

FORMAT_TEMPLATE = '''
# {project_name}

## Product Overview

{product_overview}

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
{tech_stack_rows}

## Entities

| Entity | Owning Service | Fields | Description |
|--------|---------------|--------|-------------|
{entity_rows}

## Entity Relationships

{entity_relationships}

## Bounded Contexts

{bounded_contexts}

## State Machines

{state_machines}

## Events

| Event | Publisher | Payload | Consumers |
|-------|----------|---------|-----------|
{event_rows}

## API Endpoints

{api_endpoints}

## Frontend

{frontend_spec}

## Authentication and Authorization

{auth_section}

## Non-Functional Requirements

{nfr_section}
'''.strip()

# Proven state machine format (parser extracts this correctly)
STATE_MACHINE_TEMPLATE = '''### {entity} Status State Machine

**States:** {states}

**Transitions:**
{transitions}

Initial State: {initial_state}
'''

# Example showing EXACT format the parser needs
FORMAT_REFERENCE = r"""
[PRD FORMAT REFERENCE — Use this EXACT structure]

The v16 parser extracts entities, state machines, and events using regex.
Use these EXACT formats or extraction will fail.

ENTITY TABLE (must have "Entity" and "Owning Service" columns):
| Entity | Owning Service | Fields | Description |
|--------|---------------|--------|-------------|
| User | Auth Service | id(UUID), email(String), password_hash(String), role(String), is_active(Boolean), created_at(DateTime) | Registered platform user |
| Invoice | AR Service | id(UUID), tenant_id(UUID), invoice_number(String), customer_id(UUID), total_amount(Decimal), status(String), issue_date(Date) | Customer invoice |

STATE MACHINES (must have **States:** and **Transitions:** with arrows):
### Invoice Status State Machine
**States:** draft, sent, partially_paid, paid, void
**Transitions:**
- draft → sent: user_sends (guard: at least one line item, total > 0)
- sent → partially_paid: payment_applied (guard: amount < total)
- sent → paid: payment_applied (guard: amount == total)
- paid → void: admin_voids (creates reversing GL journal entry)
Initial State: draft

EVENTS TABLE (must have "Event", "Publisher", "Payload", "Consumers" columns):
| Event | Publisher | Payload | Consumers |
|-------|----------|---------|-----------|
| ar.invoice.created | AR Service | invoice_id(UUID), invoice_number(String), customer_id(UUID), total_amount(Decimal), tenant_id(UUID) | GL Service (create receivable journal), Reporting Service (cache invalidation) |

TECHNOLOGY STACK TABLE:
| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Auth API | Python / FastAPI | Async, strong typing |
| GL Service | Python / FastAPI | Domain complexity |
| Frontend | Angular 18 | Enterprise UI |
| Database | PostgreSQL 16 | ACID, JSONB, RLS |
| Cache | Redis 7 | Pub/sub, caching |

BOUNDED CONTEXTS (one per service):
### Auth Service
**Entities:** User, Role, Permission, RefreshToken
**Responsibilities:** User registration, authentication, JWT issuance, RBAC

FIELD TYPES (use these exact type names):
- UUID — for IDs and foreign keys
- String — for text (add length: String(3) for codes)
- Decimal — for money (always Decimal, NEVER Float)
- Integer — for counts
- Boolean — for flags
- DateTime — for timestamps
- Date — for date-only fields
- JSON/JSONB — for flexible data
"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_comprehension_prompt(input_text: str) -> str:
    """Build Phase 1-2 prompt: understand input + find gaps."""
    return (
        "[PHASE: PRD COMPREHENSION + GAP DETECTION]\n\n"
        "You are a PRD generation specialist. Analyze the following requirements "
        "and produce a structured assessment.\n\n"
        f"[USER INPUT]\n{input_text}\n\n"
        "[INSTRUCTIONS]\n"
        "1. COMPREHENSION: Extract from the input:\n"
        "   - Core domain (accounting, e-commerce, healthcare, etc.)\n"
        "   - Entities mentioned or implied (list ALL of them)\n"
        "   - Tech stack preferences (if stated)\n"
        "   - Scale indicators (entity count, user count, complexity)\n"
        "   - Constraints (must-haves, compliance, etc.)\n\n"
        "2. CONTRADICTION & GAP DETECTION:\n"
        "   - Direct contradictions in requirements\n"
        "   - Missing critical decisions (no auth strategy? no DB choice?)\n"
        "   - Scope conflicts (too many entities for 'simple MVP')\n"
        "   - Circular dependencies between features\n\n"
        "3. OUTPUT FORMAT (use EXACTLY this structure):\n"
        "```\n"
        "## Understanding\n"
        "Domain: ...\n"
        "Entities identified: ...\n"
        "Tech stack: ...\n"
        "Scale: ... (small/medium/large/enterprise)\n"
        "Constraints: ...\n\n"
        "## Contradictions (N found)\n"
        "1. ... (needs user decision)\n\n"
        "## Missing Pieces (N found)\n"
        "1. ... (needs user input)\n\n"
        "## Expansion Plan\n"
        "I will expand the following (not change your decisions):\n"
        "- ...\n"
        "```\n"
        "If there are ZERO contradictions and ZERO missing pieces, "
        "say 'Everything is clear. No user input needed.'\n"
    )


def _build_expansion_prompt(
    input_text: str,
    comprehension_output: str,
    user_decisions: str = "",
) -> str:
    """Build Phase 4-11 prompt: full PRD generation."""
    decisions_section = ""
    if user_decisions:
        decisions_section = (
            "\n[USER DECISIONS (from checkpoint)]\n"
            f"{user_decisions}\n"
        )

    return (
        "[PHASE: PRD GENERATION — Full Expansion + Assembly]\n\n"
        "Generate a COMPLETE PRD in the EXACT format specified below. "
        "The output will be parsed by an automated system — formatting matters.\n\n"
        f"[ORIGINAL USER INPUT]\n{input_text}\n\n"
        f"[COMPREHENSION ANALYSIS]\n{comprehension_output}\n"
        f"{decisions_section}\n"
        f"{FORMAT_REFERENCE}\n\n"
        "[CRITICAL RULES]\n"
        "1. Entity table MUST have columns: Entity | Owning Service | Fields | Description\n"
        "2. Fields MUST include types in parentheses: id(UUID), amount(Decimal), name(String)\n"
        "3. State machines MUST use **States:** and **Transitions:** with arrow notation (→)\n"
        "4. Events table MUST have columns: Event | Publisher | Payload | Consumers\n"
        "5. Event names MUST use dot notation: {domain}.{entity}.{action}\n"
        "6. Money fields MUST be Decimal, NEVER Float\n"
        "7. Every entity MUST have: id(UUID), tenant_id(UUID), created_at(DateTime), updated_at(DateTime)\n"
        "8. Every entity with a lifecycle MUST have a state machine\n"
        "9. Every state transition MUST have a guard condition\n"
        "10. Every cross-module interaction MUST have an event with full payload\n\n"
        "[OUTPUT]\n"
        "Generate the COMPLETE PRD as a single markdown document. "
        "Include ALL sections from the format reference. "
        "Do NOT add commentary — output ONLY the PRD content.\n"
    )


def _build_improvement_prompt(existing_prd: str, gaps: list[str]) -> str:
    """Build prompt to improve an existing PRD."""
    gaps_text = "\n".join(f"- {g}" for g in gaps)
    return (
        "[PHASE: PRD IMPROVEMENT]\n\n"
        "Improve the following PRD by fixing formatting and filling gaps.\n\n"
        f"[EXISTING PRD]\n{existing_prd[:50000]}\n\n"
        f"[GAPS DETECTED BY PARSER]\n{gaps_text}\n\n"
        f"{FORMAT_REFERENCE}\n\n"
        "[INSTRUCTIONS]\n"
        "1. Keep ALL existing content that is correctly formatted\n"
        "2. Fix formatting issues so the parser can extract entities/SMs/events\n"
        "3. Fill the gaps listed above\n"
        "4. Output the COMPLETE improved PRD\n"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_prd(prd_text: str) -> ValidationReport:
    """Validate a PRD against the actual v16 parser.

    Runs parse_prd() and checks extraction completeness.
    Returns a ValidationReport with counts and specific issues.
    """
    from .prd_parser import parse_prd

    report = ValidationReport()

    if not prd_text or len(prd_text.strip()) < 100:
        report.issues.append("PRD is too short (minimum 100 characters)")
        return report

    parsed = parse_prd(prd_text)

    report.project_name = parsed.project_name
    report.entities_extracted = len(parsed.entities)
    report.events_extracted = len(parsed.events)
    report.state_machines_extracted = len(parsed.state_machines)
    report.technology_detected = bool(
        parsed.technology_hints.get("language")
        or parsed.technology_hints.get("framework")
    )

    # Count entities with typed fields
    for ent in parsed.entities:
        if ent.get("fields") and len(ent["fields"]) >= 2:
            report.entities_with_fields += 1

    # Check for issues
    if report.entities_extracted == 0:
        report.issues.append(
            "No entities extracted. Ensure entity table has columns: "
            "Entity | Owning Service | Fields | Description"
        )
    elif report.entities_extracted < 3:
        report.issues.append(
            f"Only {report.entities_extracted} entities extracted (expected 3+). "
            "Check entity table formatting."
        )

    if report.entities_with_fields < report.entities_extracted * 0.5:
        report.suggestions.append(
            f"Only {report.entities_with_fields}/{report.entities_extracted} entities "
            "have typed fields. Add field(type) to entity table."
        )

    if report.state_machines_extracted == 0 and report.entities_extracted >= 5:
        report.suggestions.append(
            "No state machines extracted. Add ### {Entity} Status State Machine "
            "sections with **States:** and **Transitions:** bullets."
        )

    if report.events_extracted == 0 and report.entities_extracted >= 5:
        report.suggestions.append(
            "No events extracted. Add events table with columns: "
            "Event | Publisher | Payload | Consumers"
        )

    if not report.technology_detected:
        report.suggestions.append(
            "No technology stack detected. Add a Technology Stack table "
            "mentioning Python, TypeScript, Angular, React, etc."
        )

    # Check entity-to-SM ratio
    if report.entities_extracted >= 10 and report.state_machines_extracted < 3:
        report.suggestions.append(
            f"Low state machine coverage: {report.state_machines_extracted} SMs for "
            f"{report.entities_extracted} entities. Most entities with status fields "
            "need state machines."
        )

    return report


def format_validation_report(report: ValidationReport) -> str:
    """Format a validation report as markdown."""
    lines = [
        "## PRD Validation Report\n",
        f"- Project: {report.project_name}",
        f"- Entities extracted: {report.entities_extracted}",
        f"- Entities with typed fields: {report.entities_with_fields}",
        f"- State machines: {report.state_machines_extracted}",
        f"- Events: {report.events_extracted}",
        f"- Technology detected: {'Yes' if report.technology_detected else 'No'}",
        f"- Quality score: {report.score:.0%}",
        f"- Valid: {'YES' if report.is_valid else 'NO'}",
        "",
    ]
    if report.issues:
        lines.append("### Issues (must fix)")
        for issue in report.issues:
            lines.append(f"- {issue}")
        lines.append("")
    if report.suggestions:
        lines.append("### Suggestions (recommended)")
        for sug in report.suggestions:
            lines.append(f"- {sug}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_prd(
    input_text: str,
    user_decisions: str = "",
    skip_checkpoint: bool = False,
) -> PrdResult:
    """Generate a parser-perfect PRD from rough input.

    Two-session pipeline:
      Session 1: Comprehension + gap detection → checkpoint message
      Session 2: Full expansion → assembled PRD + validation

    If skip_checkpoint is True, both sessions run without pausing.
    Otherwise, returns after Session 1 with checkpoint_message set.
    Call again with user_decisions to continue.

    Parameters
    ----------
    input_text : str
        Any input: paragraph, bullet list, rough spec, existing requirements.
    user_decisions : str
        User responses to contradictions/gaps from the checkpoint.
    skip_checkpoint : bool
        If True, skip the user checkpoint and proceed directly.

    Returns
    -------
    PrdResult
        Contains prd_text (if complete), checkpoint_message (if paused),
        validation report, and cost.
    """
    result = PrdResult()

    # Phase 1-2: Comprehension + gap detection
    if not user_decisions and not skip_checkpoint:
        comprehension_prompt = _build_comprehension_prompt(input_text)
        comprehension_output = _run_claude_session(comprehension_prompt)
        result.cost_usd += _estimate_cost(comprehension_prompt, comprehension_output)

        # Check if checkpoint is needed
        if "no user input needed" in comprehension_output.lower() or \
           "everything is clear" in comprehension_output.lower():
            # No gaps — proceed directly
            user_decisions = "No additional input needed."
        else:
            result.checkpoint_message = comprehension_output
            return result  # Pause for user

    # Phase 4-11: Full expansion
    comprehension = user_decisions or "Direct expansion (no checkpoint)."
    expansion_prompt = _build_expansion_prompt(input_text, comprehension, user_decisions)
    prd_text = _run_claude_session(expansion_prompt)
    result.cost_usd += _estimate_cost(expansion_prompt, prd_text)

    # Phase 12: Validation + fix loop
    for iteration in range(3):
        validation = validate_prd(prd_text)
        result.validation = validation
        result.fix_iterations = iteration

        if validation.is_valid and not validation.suggestions:
            break  # Perfect

        if validation.is_valid and iteration >= 1:
            break  # Good enough after one fix

        # Build fix prompt from validation issues
        gaps = validation.issues + validation.suggestions
        if not gaps:
            break

        fix_prompt = _build_improvement_prompt(prd_text, gaps)
        prd_text = _run_claude_session(fix_prompt)
        result.cost_usd += _estimate_cost(fix_prompt, prd_text)

    result.prd_text = prd_text
    result.validation = validate_prd(prd_text)
    return result


def improve_prd(
    existing_prd: str,
    preserve_entities: bool = True,
    preserve_stack: bool = True,
) -> PrdResult:
    """Improve an existing PRD by fixing formatting and filling gaps.

    Runs the parser on the existing PRD, identifies gaps, and generates
    only the missing/malformatted sections.

    Parameters
    ----------
    existing_prd : str
        The existing PRD text.
    preserve_entities : bool
        If True, don't remove entities the user already defined.
    preserve_stack : bool
        If True, keep the existing technology stack.
    """
    result = PrdResult()

    # Validate current state
    current = validate_prd(existing_prd)
    gaps = current.issues + current.suggestions

    if not gaps:
        # Already perfect
        result.prd_text = existing_prd
        result.validation = current
        return result

    # Add preservation instructions
    if preserve_entities:
        gaps.append("PRESERVE all existing entity definitions — only ADD missing ones")
    if preserve_stack:
        gaps.append("PRESERVE the existing technology stack section")

    # Generate improvements
    fix_prompt = _build_improvement_prompt(existing_prd, gaps)
    improved = _run_claude_session(fix_prompt)
    result.cost_usd += _estimate_cost(fix_prompt, improved)

    # Validate improved version
    result.prd_text = improved
    result.validation = validate_prd(improved)
    return result


# ---------------------------------------------------------------------------
# Claude session runner (abstracted for testability)
# ---------------------------------------------------------------------------

def _run_claude_session(prompt: str) -> str:
    """Run a Claude session with the given prompt.

    In production, uses Claude SDK. In tests, can be mocked.
    Returns the response text.
    """
    try:
        from .cli import _build_options, _process_response, _backend
        from .config import AgentTeamConfig
        from claude_agent_sdk import ClaudeSDKClient
        import asyncio

        config = AgentTeamConfig()
        options = _build_options(config, ".", depth="standard", backend=_backend)

        async def _run() -> str:
            response_text = ""
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client:
                    if hasattr(message, "content"):
                        for block in message.content:
                            if hasattr(block, "text"):
                                response_text += block.text
            return response_text

        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("Claude session failed: %s", exc)
        return f"[Claude session unavailable: {exc}]"


def _estimate_cost(prompt: str, response: str) -> float:
    """Rough cost estimate for a Claude session."""
    input_tokens = len(prompt) // 4
    output_tokens = len(response) // 4
    # Opus pricing: ~$15/M input, ~$75/M output
    return (input_tokens * 15 + output_tokens * 75) / 1_000_000
