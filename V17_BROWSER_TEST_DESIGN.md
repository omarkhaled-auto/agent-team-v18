# V17 Browser Test Phase — Design Document

## Problem Statement

The V17 coordinated builder loop (Builder → Audit → Config → Fix PRD) converges
at ~93% quality by reading CODE. It never opens a browser. Real production issues
are invisible to static analysis:

- Pages render but buttons have non-functional onClick handlers
- Forms validate client-side but API endpoints return 500
- Navigation links point to routes that don't exist
- Modals open but can't be closed
- Loading states never resolve (API call hangs)

These bugs only surface when a real user clicks a real button in a real browser.

## Architecture

### Where It Fits

```
PRD → Builder (initial) → Audit-Fix Loop (converge ~93%) →
  ┌─────────────────────────────────────────────────────────┐
  │                  BROWSER TEST PHASE                     │
  │                                                         │
  │  1. Extract Workflows from PRD (Claude, one-time)       │
  │  2. Start Application (Docker + Dev Server)             │
  │  3. Setup Test Auth (seed credentials or DB session)    │
  │  4. Execute workflows via Claude + Playwright MCP       │
  │  5. Collect screenshots + pass/fail per step            │
  │  6. If failures: Fix PRD → Builder → Re-test (max 2x)  │
  │  7. Stop Application                                    │
  │  8. Generate evidence report                            │
  └─────────────────────────────────────────────────────────┘
  → Final Audit (if browser fixes applied) → Final Report
```

### Data Flow

```
PRD Text ──→ Workflow Extraction (Claude) ──→ WorkflowSuite
                                                  │
App Startup ──→ AppInstance(port, healthy)         │
                                                  ▼
Auth Setup ──→ test_user{token}          BrowserTestEngine
                                          │
                              ┌────────────┘
                              ▼
                    Claude Operator Session
                    (with Playwright MCP)
                              │
                    browser_navigate()
                    browser_snapshot()
                    browser_click()
                    browser_take_screenshot()
                              │
                              ▼
                    StepResult[] → WorkflowResult → BrowserTestReport
                                                          │
                                        ┌─────────────────┤
                                        ▼                 ▼
                                   to_findings()    Evidence Report
                                        │           (markdown + screenshots)
                                        ▼
                                   Fix PRD → Builder → Re-test
```

## Workflow Extraction

### Strategy: Hybrid (Extract Once, Execute Many)

Claude reads the PRD text ONCE and converts natural language workflows into
structured `WorkflowStep` objects. The extraction is ABSTRACT (what to do),
and execution is CONCRETE (how to do it on the actual page).

### PRD Workflow Formats Supported

**Format 1: User Journeys (arrow-delimited)**
```
Open app → Tap repair → View status → message advisor → Close app
```
Each arrow-segment becomes 1-3 WorkflowSteps.

**Format 2: Feature Workflows (numbered steps with branching)**
```
1. Customer sees "Action Required" badge
2. Quotation detail loads
3. Customer taps "Approve"
4. **On Approve:** Backend calls Odoo...
```
Numbered steps map directly. Branch decisions follow happy path.
Backend-only steps are marked SKIP (not browser-testable).

### Extraction Output

```json
{
  "id": "f003-approve-quotation",
  "name": "Approve Quotation",
  "priority": "critical",
  "preconditions": ["authenticated", "has_pending_quotation"],
  "steps": [
    {"step": 1, "action": "navigate", "target": "/dashboard"},
    {"step": 2, "action": "click", "description": "Tap quotation card"},
    {"step": 3, "action": "wait", "wait_for": "quotation detail loads"},
    {"step": 4, "action": "verify_text", "target": "line items, total in AED"},
    {"step": 5, "action": "click", "description": "Click Approve button"},
    {"step": 6, "action": "verify_text", "target": "Quotation approved"}
  ]
}
```

## Selector Strategy

Three-layer priority with Claude operator adapting at runtime:

| Priority | Strategy | Example | Reliability |
|----------|----------|---------|-------------|
| 1 | data-testid | `[data-testid="approve-quotation"]` | Highest |
| 2 | Role/text (via browser_snapshot) | `button:has-text("Approve")` | High |
| 3 | ARIA label | `[aria-label="Close dialog"]` | Medium |
| 4 | CSS/visual (last resort) | `.btn-primary` | Low |

The Claude operator uses `browser_snapshot()` to see the accessibility tree
and finds elements based on step descriptions. It doesn't need hardcoded selectors.

## Application Lifecycle Management

### Startup Sequence

1. **Docker check** — `docker info` (fail fast if Docker not running)
2. **Docker Compose** — `docker compose up -d postgres redis`
3. **PostgreSQL ready** — `pg_isready` (max 30s)
4. **Migrations** — `npx prisma migrate deploy` (fallback: `migrate reset --force`)
5. **Seed data** — `npx prisma db seed` (non-fatal if fails)
6. **Dev server** — `npm run dev -- -p PORT` (background process)
7. **Health check** — `GET /api/health` returns 200 (max 60s)

### Stack Detection

From `package.json`:
- Has `next` → Next.js: `npm run dev -- -p PORT`
- Has `vite` → Vite: `npm run dev -- --port PORT`
- Has `express` only → Node: `node server.js`

### Error Handling

| Failure | Response |
|---------|----------|
| Docker not running | Fail fast: "Docker Desktop must be running" |
| Port in use | Kill existing process (configurable port, default 3080) |
| Migrations fail | Try `migrate reset --force`, then fail with INFRASTRUCTURE_FAILURE |
| Dev server crash | Capture stderr, report STARTUP_FAILURE |
| Health check timeout | Check process alive, capture compilation output |

### Windows Compatibility

- Port killing: `netstat -aon | findstr :PORT` + `taskkill /F /PID`
- Process termination: `process.terminate()` (no SIGTERM on Windows)
- Paths: `pathlib.Path` consistently
- Shell: `shell=True` for npm commands on Windows

## Authentication Strategy

### Two-Tier Approach

**Tier 1 (preferred):** Login via UI using seed credentials
- `_extract_seed_credentials()` finds test email/password from seed files
- Playwright navigates to login page, fills form, submits
- Tests the actual login flow → catches auth UI bugs

**Tier 2 (fallback):** Direct DB session seeding
- For magic link/OAuth apps where UI login needs external services
- Generate a Node script using the app's own auth utilities
- Insert Customer + Session records directly in DB
- Return JWT token → set as cookie via `browser_evaluate()`

### Decision Logic

```python
if seed_credentials_found and login_page_exists:
    # Tier 1: UI login
    perform_browser_login(email, password)
elif auth_requires_external_service:
    # Tier 2: DB session
    token = create_db_session(test_user)
    set_cookie(token)
else:
    # No auth needed
    proceed_without_auth()
```

## Data Strategy

### Layered Approach

| Layer | Scope | What's Tested | Data Source |
|-------|-------|---------------|-------------|
| 1 | Portal-owned features | Auth, vehicles, appointments, NPS, dashboard | Seed data in PostgreSQL |
| 2 | External-dependent features | Navigation, empty states, error handling | No external data |
| 3 (future) | Full external integration | Invoices, repairs, quotations with data | API-level mocks (MOCK_EXTERNAL=true) |

### Odoo-Dependent Features (EVS Portal)

Without a real Odoo instance:
- **Dashboard** → Test empty state ("No active repairs", "Book a Service" CTA)
- **Invoices** → Test navigation to /invoices, verify empty state renders
- **Quotations** → Test navigation, verify empty state
- **Repair status** → Test navigation, verify empty state

Report marks these as: `PARTIAL — tested navigation and empty state only`

## Test Execution Engine

### How It Works

The engine constructs a prompt and sends it to a Claude session that has
Playwright MCP tools. The Claude session acts as the "browser operator."

```
BrowserTestEngine
  ├── construct_operator_prompt(workflow, app_url, auth_token)
  ├── invoke_claude_session(prompt)  ← Claude Code CLI --print
  ├── parse_results(response_text)   ← Extract JSON from output
  └── collect_screenshots()
```

### Execution Per Workflow

1. Navigate to starting URL
2. Set auth cookie (if needed)
3. For each step:
   a. Wait for target element (up to timeout)
   b. Execute action (click, type, verify)
   c. Take screenshot
   d. Check console for JS errors
4. Return structured JSON results

### Wait Strategy

- Element-based waits (NOT `sleep()`)
- `browser_wait_for(selector_or_text, timeout_ms)`
- Default timeout: 10 seconds per step
- Loading spinner detection: wait for spinner to disappear
- Timeout → FAIL with "Loading state never resolved"

### Error Recovery

- If step fails: screenshot current state, record error, continue
- Do NOT retry individual steps (test infrastructure handles retries)
- Do NOT modify the page (no `browser_evaluate` to fix things)

## Screenshot & Evidence System

### Capture Strategy

- **Before** first action: initial page state
- **After** each significant action: click, navigate, submit
- **On failure**: immediate capture + console errors + DOM snapshot

### Organization

```
.agent-team/screenshots/
├── iteration_1/
│   ├── f001-signup-flow/
│   │   ├── step_01_navigate_signup.png
│   │   ├── step_02_fill_form.png
│   │   └── step_03_FAIL_element_not_found.png
│   ├── f003-approve-quotation/
│   │   └── ...
│   └── BROWSER_TEST_REPORT.md
└── iteration_2/
    └── ... (only re-tested failed workflows)
```

### Naming Convention

`step_{NN}_{action}_{sanitized_target}.png`
On failure: `step_{NN}_FAIL_{reason}.png`

### Storage

- Inside `.agent-team/screenshots/` (gitignored)
- Relative paths in report markdown (portable)
- PNG format, 1280x720 viewport

## Failure Classification & Fix Loop

### Severity Taxonomy

| Severity | Examples | Category |
|----------|----------|----------|
| CRITICAL | 404/500 page, white screen, React error boundary | CODE_FIX |
| HIGH | Non-functional button, broken navigation, infinite loading | CODE_FIX |
| MEDIUM | Wrong text, missing UI element, wrong navigation target | UX |
| LOW | CSS hidden element, overlap, responsive layout broken | UX |

### Failure → Finding Conversion

Browser test failures map to the existing `Finding` dataclass:

```python
Finding(
    id="BROWSER-F003-STEP5",
    feature="F-003",
    severity=Severity.HIGH,
    category=FindingCategory.CODE_FIX,
    title="Approve button has no effect on /quotations/[id]",
    current_behavior="Button click has no visible effect",
    expected_behavior="Should call Odoo action_confirm() and show success",
    file_path="src/app/quotations/[id]/page.tsx",
    fix_suggestion="Add onClick handler calling POST /api/quotations/[id]/approve",
)
```

### Fix Loop Design

```
Browser Test → Failures Found?
  ├── No  → ALL PASS → Done
  └── Yes → Convert to Findings
            → Generate Fix PRD (UI-focused)
            → Run Builder
            → Restart App
            → Re-test ONLY failed workflows
            → Repeat (max 2 iterations)
            → Final Audit (regression check)
```

**Why max 2 iterations:** Browser issues are usually small fixes (add handler,
fix route, adjust CSS). >2 iterations means something architectural is wrong.

**Why targeted re-test:** Only re-run failed workflows, not all of them.
This saves time and cost.

## The data-testid Mandate

### Enforcement Points

1. **Cross-Service Standards** (agents.py): Build mandate
2. **Quality Scan** (quality_checks.py): Post-build verification (warning severity)

### Convention

```
data-testid="{action}-{entity}-{context}"

Actions:  navigate, submit, click, toggle, open, close, select, input, view
Entities: quotation, invoice, repair, appointment, vehicle, nps, message
Contexts: detail, list, card, modal, form, sidebar, header
```

### Quality Checks

| Check | Description | Severity |
|-------|-------------|----------|
| TEST-001 | `<button>` without data-testid | warning |
| TEST-002 | `<a>`/`<Link>` without data-testid | warning |
| TEST-003 | `<input>`/`<select>`/`<textarea>` without data-testid | warning |
| TEST-004 | Element with onClick without data-testid | warning |
| TEST-005 | data-testid doesn't follow naming convention | info |

### Progressive Enhancement

- New builds: Builder generates code WITH data-testids (from standards)
- Existing codebases: Browser tests use text/aria fallbacks, quality scan reports gaps
- Testids are IDEAL but NOT REQUIRED for browser tests to work

## Implementation Plan

### New Files

| File | Purpose | ~Lines |
|------|---------|--------|
| `browser_test_agent.py` | Workflow extraction, test engine, report generation | ~600 |
| `app_lifecycle.py` | Application startup/shutdown, auth setup | ~250 |
| `tests/test_browser_test_agent.py` | Unit tests for extraction, engine, report | ~300 |

### Modified Files

| File | Changes |
|------|---------|
| `coordinated_builder.py` | Add browser test phase after convergence, extend result |
| `agents.py` | Add data-testid mandate to cross-service standards |
| `quality_checks.py` | Add testid coverage scan (TEST-001..TEST-005) |
| `cli.py` | Add `browser-test` subcommand |

### Dependencies

- Anthropic SDK (already in project)
- Playwright MCP (user has it configured)
- No new pip dependencies

### Cost Estimation

- Workflow extraction: ~$0.50 per PRD (one-time Sonnet call)
- Browser operation: ~$0.50-1.00 per workflow (5-10 tool calls × Sonnet)
- 10 workflows: ~$5-10 per browser test iteration
- Max 2 fix iterations: ~$10-20 total browser testing cost

## Configuration

```yaml
browser_tests:
  enabled: true               # Enable/disable browser test phase
  port: 3080                  # Dev server port (avoid conflicts)
  max_iterations: 2           # Max browser-fix loops
  screenshot_dir: ".agent-team/screenshots"
  workflows: "all"            # "all" or list of workflow IDs
  auth_bypass: true           # Create test user with direct DB session
  operator_model: "claude-sonnet-4-20250514"
  step_timeout_ms: 10000      # Per-step wait timeout
  health_check_timeout: 60    # Seconds to wait for health check
```
