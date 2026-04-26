# Product IR Integration Redesign Plan

> **Target repository:** `C:\Projects\agent-team-v18-codex`
>
> **Final destination in builder repo:** `docs/plans/2026-04-13-product-ir-integration-redesign-plan.md`
>
> **For the implementing session:** Execute this plan top-to-bottom. Do not redesign while implementing. Follow the file order, helper names, and acceptance checks exactly unless a failing test proves a documented assumption is wrong.

## Goal

Redesign Product IR integration extraction so the builder:
- stops inferring vendor-specific adapters from generic PRD words
- distinguishes external systems from provider services, generic capabilities, and infra dependencies
- preserves backward compatibility for existing prompt consumers
- only scaffolds real adapter instructions for explicit or high-confidence named integrations

This is a targeted architectural redesign, not a full pipeline rewrite.

## Why This Change Is Needed

The current builder collapses too many concepts into one field:

- `ProductIR.integrations` in [src/agent_team_v15/product_ir.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/product_ir.py:146)
- `IntegrationSpec` in [src/agent_team_v15/product_ir.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/product_ir.py:114)
- `_detect_integrations()` in [src/agent_team_v15/product_ir.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/product_ir.py:648)

Today the builder treats all detected integrations as if they were adapter-worthy external SDK targets. That is wrong because the current detector conflates:

1. External business systems
2. Service providers
3. Infrastructure dependencies
4. Product capabilities

The downstream effect is not cosmetic. False detections propagate into prompt scaffolding:

- `build_adapter_instructions()` in [src/agent_team_v15/agents.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:1993)
- milestone 1 adapter injection in [src/agent_team_v15/agents.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:6292)
- backend prompt adapter port injection in [src/agent_team_v15/agents.py](C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:7687)

This means low-confidence or wrong vendor guesses can pressure the builder to scaffold adapters that the PRD never asked for.

## Concrete Failure Case

The merged ArkanPM PRD (`prd.md` + `prd.builder.md`) currently causes the builder to infer:

- `Redis` — acceptable as a dependency, but not an adapter target
- `Stripe` — false positive
- `Twilio` — false positive
- `Firebase` — false positive
- `Odoo` — false positive

Those false positives come from whole-document substring and pair matching:

- `Stripe` from combinations like `payment + webhook` or `payment + provider`
- `Twilio` from combinations like `sms + provider` or `sms + verification`
- `Firebase` from combinations like `push notification + token` or `push notification + device`
- `Odoo` from `erp` being matched as a raw substring inside unrelated words such as `WorkOrderPart` or `enterprise`

The current design therefore has two independent flaws:

1. The detector is too loose
2. The IR schema is too coarse

Fixing only the regexes helps, but it does not fix the schema or the prompt-consumer assumptions.

## Scope

This plan changes:

- Product IR integration data model
- integration extraction logic
- IR serialization artifacts
- integration-related prompt helpers
- integration-related tests
- summary formatting

This plan does **not** change:

- endpoint extraction
- acceptance criteria extraction
- milestone parsing
- contract extraction
- integration verifier logic
- scheduler or wave engine behavior

## Non-Goals

1. Do not redesign the entire Product IR system.
2. Do not remove the legacy `integrations` field immediately.
3. Do not force every downstream consumer to adopt a new schema in one pass.
4. Do not add vendor-specific adapters for providers not explicitly named in the PRD.
5. Do not model every cloud product in existence. Only add what is needed to support accurate extraction and no-regression behavior.

## Current Code Map

### Core extraction and serialization

| File | Function or Structure | Current Role |
|---|---|---|
| `src/agent_team_v15/product_ir.py` | `IntegrationSpec` | Coarse integration representation |
| `src/agent_team_v15/product_ir.py` | `ProductIR.integrations` | Only integration container |
| `src/agent_team_v15/product_ir.py` | `_INTEGRATION_PATTERNS` | Vendor heuristics |
| `src/agent_team_v15/product_ir.py` | `_METHOD_HINTS` | Method hints used for vendor details |
| `src/agent_team_v15/product_ir.py` | `_detect_integrations()` | Whole-document vendor inference |
| `src/agent_team_v15/product_ir.py` | `save_product_ir()` | Writes `product.ir.json`, `IR.json`, `integrations.ir.json` |
| `src/agent_team_v15/product_ir.py` | `format_ir_summary()` | Summarizes integrations as one flat list |

### Prompt consumers

| File | Function | Current Role |
|---|---|---|
| `src/agent_team_v15/agents.py` | `build_adapter_instructions()` | Generates adapter-first scaffolding instructions |
| `src/agent_team_v15/agents.py` | `_select_ir_integrations()` | Returns all IR integrations |
| `src/agent_team_v15/agents.py` | `_format_adapter_ports()` | Formats ports for backend prompt injection |
| `src/agent_team_v15/agents.py` | milestone-1 integration injection block | Reads `integrations.ir.json` directly |

### Tests

| File | Coverage |
|---|---|
| `tests/test_product_ir.py` | current integration detection, serialization, summary |
| `tests/test_v18_stage1.py` | adapter prompt injection behavior |

## Target Design Overview

The redesign has one canonical model and one backward-compatible derived view.

### Canonical model

Add a new `integration_items` collection to `ProductIR`. This becomes the canonical integration catalog.

Each item must explicitly state what it is:

- `external_system`
- `service_provider`
- `capability`
- `infra_dependency`

Each item must also explicitly state how the builder should treat it:

- `real_sdk`
- `adapter_stub`
- `internal_module`
- `infra_only`
- `capability_only`

### Legacy compatibility view

Keep `ProductIR.integrations`, but redefine its meaning:

- it is no longer “everything integration-related”
- it becomes “adapter candidates only”
- it is derived from `integration_items`
- it stays in the old `IntegrationSpec` shape so existing prompt consumers keep working

This allows a phased migration:

- canonical richness for the new model
- old consumers continue to work
- false positives stop turning into adapters

## Exact Data Model To Implement

### 1. Keep the existing compatibility dataclass

Keep `IntegrationSpec` as-is for legacy consumers:

```python
@dataclass
class IntegrationSpec:
    vendor: str
    type: str
    port_name: str
    methods_used: list[str] = field(default_factory=list)
```

Do not remove this in this change.

### 2. Add a new evidence dataclass

Add immediately below `IntegrationSpec`:

```python
@dataclass
class IntegrationEvidence:
    source_kind: str  # explicit_table|integration_section|technology_stack|endpoint|event|heuristic
    confidence: str   # explicit|high|medium|low
    heading: str = ""
    excerpt: str = ""
    matched_terms: list[str] = field(default_factory=list)
```

### 3. Add a new canonical item dataclass

Add immediately below `IntegrationEvidence`:

```python
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
```

### 4. Update ProductIR

Change `ProductIR` in `product_ir.py`:

- bump `schema_version` from `1` to `2`
- add `integration_items: list[IntegrationItem] = field(default_factory=list)` before the legacy `integrations` field
- keep `integrations` after it as the compatibility view

Target structure:

```python
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
    integrations: list[IntegrationSpec] = field(default_factory=list)  # legacy adapter candidates only
    workflows: list[WorkflowSpec] = field(default_factory=list)
    i18n: I18nSpec = field(default_factory=I18nSpec)
```

## Canonical Semantics

### `kind`

Use these exact values:

- `external_system`
- `service_provider`
- `capability`
- `infra_dependency`

### `status`

Use these exact values:

- `required`
- `stubbed`
- `future`
- `deferred`
- `optional`

### `implementation_mode`

Use these exact values:

- `real_sdk`
- `adapter_stub`
- `internal_module`
- `infra_only`
- `capability_only`

### Rules

1. Only `external_system` and `service_provider` items may ever become legacy `IntegrationSpec` adapter candidates.
2. `capability` items must never become adapter candidates by themselves.
3. `infra_dependency` items must never become adapter candidates.
4. `future` and `deferred` items must not generate adapter scaffolding.
5. `stubbed` items may generate adapter scaffolding only when the PRD explicitly describes a bounded integration interface that exists in this phase.

## Extraction Pipeline To Implement

Replace the current one-pass `_detect_integrations(prd_text)` logic with a staged pipeline.

### New top-level flow in `compile_product_ir()`

In `compile_product_ir()`:

1. extract `integration_items = _extract_integration_items(prd_text)`
2. derive `legacy_integrations = _derive_legacy_integrations(integration_items)`
3. assign:
   - `integration_items=integration_items`
   - `integrations=legacy_integrations`

Do **not** call the old `_detect_integrations()` from `compile_product_ir()` anymore.

### New helper functions to add in `product_ir.py`

Add these exact helpers:

```python
def _extract_integration_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_explicit_integration_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_stack_integration_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_endpoint_event_integration_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_capability_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_infra_dependency_items(prd_text: str) -> list[IntegrationItem]: ...
def _extract_heuristic_vendor_items(prd_text: str) -> list[IntegrationItem]: ...
def _derive_legacy_integrations(items: list[IntegrationItem]) -> list[IntegrationSpec]: ...
def _integration_method_hints_for_item(item: IntegrationItem) -> list[str]: ...
def _merge_integration_items(items: list[IntegrationItem]) -> list[IntegrationItem]: ...
def _integration_item_key(item: IntegrationItem) -> tuple[str, str, str]: ...
```

### Detection precedence

The extraction pipeline must run in this order:

1. `explicit_table`
2. `integration_section`
3. `technology_stack`
4. `endpoint` and `event` evidence
5. `capability`
6. `infra_dependency`
7. `heuristic`

Then merge, dedupe, and derive legacy adapter candidates.

### Rule: explicit beats heuristic

If an item already exists from explicit evidence, heuristic evidence may enrich it but must not downgrade or reclassify it.

### Rule: capability words alone do not prove vendor

These generic concepts:

- `payment`
- `sms`
- `push`
- `email`
- `provider`
- `verification`
- `webhook`
- `token`
- `device`
- `erp`
- `sync`

must never create a vendor-specific item by themselves.

They may create:

- a `capability` item
- or enrich an already explicit vendor item

They may not create `Stripe`, `Twilio`, `Firebase`, or `Odoo` unless that vendor is explicitly named.

### Rule: token-aware matching only

Any keyword that is plain text or alphanumeric must use token-aware matching.

Do **not** use raw substring checks like:

```python
keyword in text_lower
```

for generic keywords such as `erp`, `sms`, `push`, `payment`, `provider`, `verification`, `create`, `write`.

Implement a helper like:

```python
def _contains_term(text_lower: str, term: str) -> bool:
    ...
```

Behavior:

- if `term` contains letters and digits only, use regex token boundaries
- if `term` contains punctuation such as `@aws-sdk/client-s3`, allow exact substring matching
- normalize whitespace for multi-word phrases before matching

This specifically prevents `erp` from matching inside `WorkOrderPart` or `enterprise`.

## Registry Changes

### Replace `_INTEGRATION_PATTERNS` with a stricter vendor registry

Replace `_INTEGRATION_PATTERNS` with a registry that requires explicit vendor evidence to emit a vendor item.

Use a structure like:

```python
_VENDOR_REGISTRY: dict[str, dict[str, Any]] = {
    "Stripe": {
        "kind": "service_provider",
        "category": "payment",
        "port_name": "IPaymentProvider",
        "explicit_terms": ["stripe", "payment_intent", "paymentintent", "stripe webhook"],
        "sdk_terms": ["stripe", "@stripe/stripe-js", "stripe-node"],
        "default_mode": "real_sdk",
    },
    ...
}
```

The important change is:

- `medium_pairs` are removed from vendor issuance
- vendor creation requires an explicit vendor term or explicit SDK term

### Add a capability registry

Add:

```python
_CAPABILITY_PATTERNS = {
    "push_notification": [...],
    "email_delivery": [...],
    "sms_delivery": [...],
    "inbound_webhook": [...],
    "outbound_webhook": [...],
    "file_storage": [...],
    "payment_processing": [...],
}
```

These create `IntegrationItem(kind="capability", implementation_mode="capability_only")`.

### Add an infra dependency registry

Add:

```python
_INFRA_PATTERNS = {
    "Redis": {...},
    "PostgreSQL": {...},
    "BullMQ": {...},
    "Kafka": {...},
    ...
}
```

These create `IntegrationItem(kind="infra_dependency", implementation_mode="infra_only")`.

### Remove dangerous method hints

The current `_METHOD_HINTS` contains generic Odoo hints:

- `create`
- `write`

These are too broad and must be removed.

Keep only high-signal method hints such as:

- `search_read`
- `execute_kw`
- `json-rpc`
- `xmlrpc`
- explicit SDK function names

Also stop scanning the entire PRD for method hints. Method hints must be derived from local evidence excerpts only.

## Detailed Extraction Behavior

### 1. `_extract_explicit_integration_items(prd_text)`

This is the highest-priority extractor.

It should inspect:

- markdown tables with headers including one or more of:
  - `integration`
  - `system`
  - `provider`
  - `vendor`
  - `capability`
  - `status`
  - `direction`
  - `auth`
  - `port`
- sections with headings containing:
  - `integrations`
  - `dependencies`
  - `external systems`
  - `providers`

For each explicit row or bullet:

- derive `kind`
- derive `status`
- derive `implementation_mode`
- derive `direction`
- capture `heading`
- capture a short `excerpt`
- attach `confidence="explicit"`

If a PRD explicitly says:

- `stubbed`
- `future`
- `deferred`
- `not implemented in this build`

that must map directly to `status`.

If a PRD explicitly says:

- `anti-corruption layer`
- `adapter`
- `webhook receiver`
- `provider`

use that to determine `implementation_mode`.

### 2. `_extract_stack_integration_items(prd_text)`

This extractor reads the technology stack table or stack section and emits only:

- `service_provider` items for named providers like `Azure Blob Storage`, `Azure Notification Hubs`, `SendGrid`
- `infra_dependency` items for named infra like `Redis`, `PostgreSQL`

It must not emit vendor items from generic stack labels alone.

Examples for ArkanPM:

- `Azure Blob Storage` -> `service_provider`, `file_storage`, `real_sdk`
- `Azure Notification Hubs` -> `service_provider`, `push_notification`, `real_sdk`
- `Redis` -> `infra_dependency`, `cache_queue`, `infra_only`

### 3. `_extract_endpoint_event_integration_items(prd_text)`

This extractor looks for strong explicit signals in:

- endpoint paths
- event names
- surrounding lines

It is the correct place to emit something like:

- `Arkan Handover` as an `external_system`

Example signals:

- `/integrations/arkan/webhook`
- `integration.arkan.handover_received`
- explicit prose naming `Arkan`

This extractor must not create vendor items from generic webhook text alone.

### 4. `_extract_capability_items(prd_text)`

This extractor captures generic capabilities intentionally, for example:

- push notifications
- email delivery
- SMS delivery
- inbound webhooks
- outbound webhooks
- file storage

These items exist so the builder still understands architecture, but they must never become adapter candidates unless a named provider also exists.

### 5. `_extract_infra_dependency_items(prd_text)`

This extractor captures infra dependencies used by the target system itself:

- Redis
- PostgreSQL
- BullMQ

These should show up in `integration_items` so the IR is complete, but they must not flow into adapter scaffolding.

### 6. `_extract_heuristic_vendor_items(prd_text)`

This is the fallback extractor and must be conservative.

Rules:

1. It may only emit vendor items when a vendor or SDK name is explicit.
2. It may not emit vendors from generic capability pair matching.
3. If only generic capability evidence exists, emit a capability item instead.
4. Heuristic-only vendor items must carry `confidence="low"` or `confidence="medium"`.
5. Heuristic-only vendor items with confidence below `high` must not become legacy adapter candidates.

This means the current tests that rely on explicit names like `Stripe webhook receives payment_intent updates` should still pass, but generic ArkanPM-style wording should stop emitting false vendors.

## Deriving Legacy Adapter Candidates

Implement `_derive_legacy_integrations(items)` with these exact rules.

An `IntegrationItem` becomes a legacy `IntegrationSpec` only if all of the following are true:

1. `kind` is `external_system` or `service_provider`
2. `implementation_mode` is `real_sdk` or `adapter_stub`
3. `status` is `required` or `stubbed`
4. evidence confidence is `explicit` or `high`
5. `vendor` or `name` is non-empty
6. there is a meaningful `port_name`

If an item does not meet all six conditions, it must not be included in the legacy `integrations` list.

### Port-name derivation rule

If no explicit port name exists:

- for `external_system`: derive a stable interface name from the item name, e.g. `IArkanClient`
- for `service_provider`: derive a stable provider port, e.g. `IFileStorageProvider`, `IPushNotificationProvider`
- for `capability` or `infra_dependency`: do not derive a port name

## Serialization Changes

### `save_product_ir()`

Keep the existing files:

- `product.ir.json`
- `IR.json`
- `acceptance-criteria.ir.json`
- `integrations.ir.json`
- `milestones.ir.json`

Add a new file:

- `integration-items.ir.json`

### Exact file meanings after the change

| File | Meaning after redesign |
|---|---|
| `product.ir.json` | canonical full IR including `integration_items` and legacy `integrations` |
| `IR.json` | compatibility alias of `product.ir.json` |
| `integration-items.ir.json` | canonical integration catalog |
| `integrations.ir.json` | **legacy adapter candidates only** |

### Exact save behavior

In `save_product_ir()`:

1. write `product.ir.json` and `IR.json` as usual
2. write `integration-items.ir.json` from `ir.integration_items`
3. write `integrations.ir.json` from `ir.integrations`
4. do not change the filename `integrations.ir.json`, only change its semantics

This preserves existing consumers that read `integrations.ir.json` directly.

## Summary Formatting Changes

Update `format_ir_summary(ir)` in `product_ir.py`.

Current behavior:

- one line: `External Integrations: ...`

Replace with grouped summary output:

- `External Systems: ...`
- `Provider Services: ...`
- `Capabilities: ...`
- `Infra Dependencies: ...`
- optionally `Adapter Candidates: ...`

If `integration_items` is empty, fall back to legacy `integrations` for backward compatibility.

## Prompt Consumer Changes

### Principle

Prompt consumers should no longer assume:

- every integration-like thing is adapter-worthy
- every named dependency is an external SDK system

### `build_adapter_instructions()` in `agents.py`

Keep the function name. Do not break current call sites.

Change the semantics:

- its input list is now adapter candidates only
- it should not attempt to filter internally
- it should remain deterministic and simple

Add a docstring note stating that callers must pass filtered adapter candidates, not the full catalog.

### `build_adapter_instructions()` acceptance behavior

If passed:

- `Arkan Handover` with `adapter_stub` -> emit scaffold instructions
- `Azure Blob Storage` with `real_sdk` -> emit scaffold instructions
- `Redis` -> should never be passed here
- `push_notification` capability -> should never be passed here

### Milestone 1 injection block

Current code in `agents.py` reads `integrations.ir.json` directly. That is acceptable to keep **only because** `integrations.ir.json` becomes adapter-candidates-only.

Do not change the path in this redesign unless tests show it is necessary.

### `_select_ir_integrations()` in `agents.py`

Keep this helper, but update its docstring or surrounding comments to clarify that it returns legacy adapter candidates, not the full integration catalog.

Add a new helper:

```python
def _select_ir_integration_items(ir: Any) -> list[dict[str, Any]]: ...
```

This should pull `integration_items` from the IR, falling back to `[]`.

### `_format_adapter_ports()` in `agents.py`

Keep this helper operating only on adapter candidates.

Add a new helper for contextual awareness:

```python
def _format_integration_context(items: list[dict[str, Any]]) -> str: ...
```

This helper should group and display:

- external systems
- provider services
- capabilities
- infra dependencies

without implying adapter scaffolding.

### Backend prompt injection

In the backend milestone prompt builder:

1. keep the `[ADAPTER PORTS - CODE AGAINST THESE INTERFACES, NOT VENDOR SDKS]` block for adapter candidates
2. add a new read-only context block before or after it:

```text
[INTEGRATION CONTEXT]
- External systems: ...
- Provider services: ...
- Capabilities: ...
- Infra dependencies: ...
```

This gives the model architectural awareness without forcing adapters for capabilities or infra.

## File-By-File Implementation Tasks

### File 1: `src/agent_team_v15/product_ir.py`

This is the primary file. Make changes in this order.

#### Step 1: Add new dataclasses

Add:

- `IntegrationEvidence`
- `IntegrationItem`

Place them immediately after `IntegrationSpec`.

#### Step 2: Update `ProductIR`

- bump `schema_version` to `2`
- add `integration_items`
- keep legacy `integrations`

#### Step 3: Replace the current integration registry

Replace `_INTEGRATION_PATTERNS` with:

- `_VENDOR_REGISTRY`
- `_CAPABILITY_PATTERNS`
- `_INFRA_PATTERNS`

Keep `_METHOD_HINTS` but prune unsafe generic entries.

#### Step 4: Add token-aware match helpers

Add helpers:

- `_contains_term()`
- `_find_matching_terms()`
- `_normalize_excerpt()`
- `_heading_for_offset()` if useful

These helpers must be reused by all new extraction stages.

#### Step 5: Implement the staged extraction helpers

Implement:

- `_extract_integration_items()`
- `_extract_explicit_integration_items()`
- `_extract_stack_integration_items()`
- `_extract_endpoint_event_integration_items()`
- `_extract_capability_items()`
- `_extract_infra_dependency_items()`
- `_extract_heuristic_vendor_items()`
- `_merge_integration_items()`
- `_integration_item_key()`
- `_integration_method_hints_for_item()`
- `_derive_legacy_integrations()`

#### Step 6: Rewire `compile_product_ir()`

Replace the old call to `_detect_integrations(prd_text)` with:

```python
integration_items = _extract_integration_items(prd_text)
legacy_integrations = _derive_legacy_integrations(integration_items)
```

Then assign both into `ProductIR(...)`.

#### Step 7: Keep `_detect_integrations()` as compatibility wrapper

Do **not** remove `_detect_integrations()` in this change.

Re-implement it as:

```python
def _detect_integrations(prd_text: str) -> list[IntegrationSpec]:
    return _derive_legacy_integrations(_extract_integration_items(prd_text))
```

This preserves tests and external imports.

#### Step 8: Update `save_product_ir()`

Write:

- `integration-items.ir.json`
- legacy filtered `integrations.ir.json`

#### Step 9: Update `format_ir_summary()`

Group integration output by kind.

### File 2: `src/agent_team_v15/agents.py`

#### Step 1: Leave `build_adapter_instructions()` mostly intact

Only adjust:

- docstring
- comments
- optional small guardrails around missing `vendor` or `port_name`

Do not overcomplicate this helper.

#### Step 2: Add `_select_ir_integration_items(ir)`

Add immediately near `_select_ir_integrations(ir)`.

Behavior:

- return `integration_items` if present
- else return `[]`

#### Step 3: Add `_format_integration_context(items)`

This should render grouped bullet lines, not scaffolding instructions.

#### Step 4: Update backend prompt builder

Where backend prompts currently use:

- `_select_ir_integrations(ir)`
- `_format_adapter_ports(integrations)`

add:

- `integration_items = _select_ir_integration_items(ir)`
- `integration_context = _format_integration_context(integration_items)`

Inject the context block even when no adapter ports exist, if the catalog has capability or infra items.

#### Step 5: Keep milestone-1 direct file load behavior

Because `integrations.ir.json` becomes filtered adapter candidates, the existing milestone-1 direct-load path can remain. Do not redesign that path in this change.

### File 3: `tests/test_product_ir.py`

This file needs the heaviest test expansion.

Modify and add tests exactly as described in the next section.

### File 4: `tests/test_v18_stage1.py`

Add tests proving:

- adapter instructions still render for real adapter candidates
- capability-only or infra-only inputs do not generate adapter scaffolding when they are not passed through the filtered legacy file
- milestone-1 injection still works with the compatibility file

### File 5: `README.md` or docs

Optional but recommended:

- add one short note in PRD-mode documentation stating that explicit integration tables or sections are preferred over generic prose for accurate adapter planning

## Exact Tests To Add or Modify

### `tests/test_product_ir.py`

#### Keep existing positive tests

Keep these tests passing:

- explicit Stripe keyword detection
- explicit Twilio keyword detection
- explicit Odoo keyword detection
- generic email not detecting SendGrid
- explicit SendGrid detecting SendGrid

#### Add new negative regression tests

Add these exact tests:

1. `test_generic_payment_webhook_does_not_detect_stripe_without_explicit_vendor`
   - input example: `"The system handles payment approval and inbound webhook retries."`
   - expected: no `Stripe` in legacy integrations

2. `test_generic_sms_verification_does_not_detect_twilio_without_explicit_vendor`
   - input example: `"SMS is used for MFA verification when required."`
   - expected: no `Twilio`

3. `test_push_token_device_does_not_detect_firebase_without_explicit_vendor`
   - input example: `"PushToken stores device metadata for push notifications."`
   - expected: no `Firebase`

4. `test_work_order_part_text_does_not_detect_odoo_from_erp_substring`
   - input example: `"WorkOrderPart is updated during inventory integration checks."`
   - expected: no `Odoo`

5. `test_generic_provider_words_create_capability_not_vendor`
   - input example: `"Notification providers may be configured later for email, SMS, and push."`
   - expected:
     - no vendor in legacy integrations
     - `integration_items` contains capability entries

#### Add explicit provider extraction tests

6. `test_stack_extracts_azure_blob_storage_as_service_provider`
7. `test_stack_extracts_azure_notification_hubs_as_service_provider`
8. `test_stack_extracts_redis_as_infra_dependency_not_adapter_candidate`

#### Add explicit Arkan system tests

9. `test_arkan_webhook_extracts_external_system_stubbed_adapter`
   - input should include:
     - `/integrations/arkan/webhook`
     - prose mentioning stubbed or future mapping
   - expected:
     - `integration_items` contains `Arkan` or `Arkan Handover`
     - `kind == external_system`
     - `status == stubbed`
     - `implementation_mode == adapter_stub`
     - legacy `integrations` includes an adapter candidate for Arkan

#### Add serialization tests

10. `test_save_product_ir_writes_integration_items_artifact`
11. `test_legacy_integrations_artifact_only_contains_adapter_candidates`

#### Add summary-format tests

12. `test_format_ir_summary_groups_integrations_by_kind`

### `tests/test_v18_stage1.py`

Add:

1. `test_build_adapter_instructions_with_provider_service_candidate`
   - example input: Azure Blob Storage provider candidate
   - expected: adapter scaffold text present

2. `test_adapter_candidate_file_semantics_are_filtered`
   - create `integrations.ir.json` with only adapter candidates
   - create `product.ir.json` with richer `integration_items`
   - expected: milestone-1 injection reads the filtered candidate file and does not scaffold capability-only entries

3. `test_backend_prompt_receives_integration_context_without_adapter_ports`
   - IR contains capability and infra items only
   - expected:
     - prompt includes `[INTEGRATION CONTEXT]`
     - prompt does not include `[ADAPTER PORTS ...]`

## ArkanPM Regression Fixture

Add a new regression fixture file under `tests/fixtures/` with a trimmed ArkanPM-style excerpt. Do not use the full 160KB PRD in unit tests.

Suggested file:

- `tests/fixtures/product_ir/arkanpm_integration_regression.md`

Contents should include:

- technology stack rows for:
  - Azure Blob Storage
  - Azure Notification Hubs
  - Redis
- explicit Arkan webhook and stubbed integration wording
- push notification, SMS, token, device, provider wording
- `WorkOrderPart` wording
- generic payment wording
- generic verification wording

Expected assertions from this fixture:

- adapter candidates include:
  - Arkan
  - Azure Blob Storage
  - Azure Notification Hubs
- adapter candidates do **not** include:
  - Stripe
  - Twilio
  - Firebase
  - Odoo
- `integration_items` include:
  - at least one `capability`
  - at least one `infra_dependency`

## Expected Before and After Behavior

### Before

For an ArkanPM-style PRD, legacy integration output can include:

- Stripe
- Twilio
- Firebase
- Odoo
- Redis

and those may leak into adapter scaffolding.

### After

For the same PRD:

#### Canonical `integration_items`

Should include something close to:

- `Arkan Handover` — `external_system`, `stubbed`, `adapter_stub`
- `Azure Blob Storage` — `service_provider`, `real_sdk`
- `Azure Notification Hubs` — `service_provider`, `real_sdk`
- `Redis` — `infra_dependency`, `infra_only`
- `inbound_webhook` — `capability`, `capability_only`
- `outbound_webhook` — `capability`, `capability_only`
- `push_notification` — `capability`, `capability_only`
- `email_delivery` — `capability`, `capability_only`
- `sms_delivery` — `capability`, `capability_only`
- `file_storage` — `capability`, `capability_only`

#### Legacy `integrations`

Should include only adapter candidates, ideally:

- Arkan
- Azure Blob Storage
- Azure Notification Hubs

and must exclude:

- Stripe
- Twilio
- Firebase
- Odoo
- Redis

## Implementation Order

Follow this exact order. Do not jump around.

### Phase 1: Product IR schema and serializer

1. Add new dataclasses
2. Update `ProductIR`
3. Update `compile_product_ir()`
4. Update `save_product_ir()`
5. Update `format_ir_summary()`

Run:

```powershell
python -m pytest tests/test_product_ir.py -q
```

Do not proceed until this passes or only expected failing tests remain from the yet-unimplemented extractor stages.

### Phase 2: Extraction helpers

1. Add token-aware term helpers
2. Add registry splits
3. Add staged extraction helpers
4. Re-implement `_detect_integrations()` as compatibility wrapper
5. Add or update regression tests

Run:

```powershell
python -m pytest tests/test_product_ir.py -q
```

### Phase 3: Prompt consumers

1. Add `_select_ir_integration_items()`
2. Add `_format_integration_context()`
3. Update backend prompt injection
4. Keep milestone-1 compatibility path intact

Run:

```powershell
python -m pytest tests/test_v18_stage1.py -q
python -m pytest tests/test_product_ir.py -q
```

### Phase 4: Broader regression sweep

Run:

```powershell
python -m pytest tests/test_product_ir.py tests/test_v18_stage1.py tests/test_agents.py -q
```

If prompt-related assertions fail in `test_agents.py`, update the plan implementation only enough to satisfy the new grouped integration context semantics.

## Backward Compatibility Rules

1. `compile_product_ir()` must still return a `ProductIR` with a usable `integrations` field.
2. Existing imports of `_detect_integrations()` must not break.
3. Existing `integrations.ir.json` readers must continue to work.
4. Existing prompt helpers that expect `vendor`, `type`, `port_name`, `methods_used` must continue to work.
5. New consumers should prefer `integration_items`.

## Do Not Make These Mistakes

1. Do not delete `IntegrationSpec`.
2. Do not rename `integrations.ir.json`.
3. Do not keep raw substring matching for generic terms.
4. Do not let capability-only items reach `build_adapter_instructions()`.
5. Do not let infra dependencies become adapter candidates.
6. Do not search the entire PRD for method hints like `create` or `write`.
7. Do not emit vendor items from `payment + webhook`, `sms + verification`, `push + token`, or `erp + integration` alone.
8. Do not require every prompt consumer to fully understand the new catalog in this first pass.

## Definition of Done

The work is done only when all of the following are true:

1. `ProductIR` schema version is `2`
2. `product.ir.json` includes `integration_items`
3. `integration-items.ir.json` is written
4. `integrations.ir.json` contains only adapter candidates
5. explicit vendor tests still pass
6. new negative false-positive tests pass
7. ArkanPM-style regression fixture passes
8. milestone-1 adapter injection still works for real candidates
9. backend prompts can show integration context without forcing adapter ports
10. `Stripe`, `Twilio`, `Firebase`, and `Odoo` are not emitted for the ArkanPM regression fixture

## Suggested Commit Boundaries

Use these commits:

1. `refactor: add canonical integration_items model to Product IR`
2. `refactor: replace flat integration heuristic with staged extraction`
3. `refactor: keep legacy integrations as filtered adapter candidates`
4. `feat: inject grouped integration context into backend prompts`
5. `test: add product-ir and adapter prompt regression coverage`

## Final Validation Command Set

Before closing the implementation session, run:

```powershell
python -m pytest tests/test_product_ir.py tests/test_v18_stage1.py -q
```

If time allows, also run:

```powershell
python -m pytest tests/test_agents.py -q
```

## Handoff Note For The Implementing Session

If you hit ambiguity, prefer these decisions:

- favor explicit PRD text over heuristics
- favor capability classification over vendor classification
- favor infra classification over provider classification when the dependency is internal runtime infrastructure
- keep compatibility files and fields stable
- reduce prompt-side behavior changes unless the new catalog requires them

That bias preserves current behavior where it is correct and narrows behavior only where it is currently wrong.
