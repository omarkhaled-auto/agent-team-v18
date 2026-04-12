# Codex + Claude Code Hybrid Feasibility Report

> **Date:** 2026-04-11
> **Scope:** Research only — no design or implementation
> **Verdict:** PARTIALLY FEASIBLE (via Codex CLI SDK path; Cloud path not viable)

---

## Executive Summary

Three integration paths exist for Codex:

1. **Codex CLI/SDK** — runs locally, operates on local files, supports MCP.
   Python SDK: `openai-codex-sdk` (wraps CLI binary)
2. **OpenAI Responses API** — standard `openai` Python package, no CLI
   dependency, uses `shell`/`apply_patch` tools with hosted containers.
   Application applies V4A diffs to local files
3. **Codex Cloud** — remote sandbox, async tasks, limited file access.
   NOT viable for our wave executor (no local file access)

The CLI/SDK path is the most natural fit (same filesystem model as Claude
Code, supports MCP including Context7). The Responses API is the most
production-ready alternative (no binary dependency, standard Python package).

The proposed split is architecturally feasible but introduces real complexity
in ownership boundaries, prompt engineering for two different model families,
and fix cycle routing. The biggest risk is not technical plumbing but
**model quality divergence**: Codex uses OpenAI models (GPT-5-Codex family)
whose framework knowledge, coding style, and error patterns differ from
Claude's, and maintaining consistency across both requires significant
prompt engineering and post-processing.

**Cost case is strong:** GPT-5.3-Codex ($1.75/$14.00 per 1M tokens) is
cheaper than Claude Sonnet ($3.00/$15.00) with ~4x better token efficiency,
potentially reducing backend coding costs by 30-50%.

---

## 1. Codex API for Programmatic Use

### Is there a REST API or SDK?

**Yes — five integration paths exist:**

| Path | Package / Endpoint | Language | Maturity |
|------|--------------------|----------|----------|
| **OpenAI Responses API** | `openai` Python SDK + `client.responses.create()` | Python | **Production-ready** |
| **Codex Python SDK** | `openai-codex-sdk` (PyPI, v0.1.11) | Python 3.10+ | Experimental |
| **Codex App-Server SDK** | `codex-app-server-sdk` (PyPI, v0.2.0) | Python 3.10+ | Experimental |
| **Agents SDK + MCP** | `openai-agents` + Codex as MCP server | Python | Production-ready |
| **Codex CLI TypeScript SDK** | `@openai/codex-sdk` (npm) | TypeScript | Stable |

**Two primary paths for our wave executor:**

1. **Responses API** (most production-ready, no CLI dependency): Uses the
   standard `openai` package with GPT-5-Codex models + `shell`/`apply_patch`
   tools. Application manages file I/O via V4A diff patches.

2. **Codex CLI Python SDK** (most natural fit): Wraps the Codex CLI binary,
   operates directly on local filesystem. Communicates via JSONL over
   stdin/stdout. Supports MCP servers.

### What does the request look like?

**Path A — Responses API (no CLI dependency):**
```python
from openai import OpenAI
client = OpenAI()

response = client.responses.create(
    model="gpt-5.3-codex",
    tools=[
        {"type": "shell", "environment": {"type": "container_auto"}},
        {"type": "apply_patch"},
    ],
    input="Implement the backend services for the auth module",
    background=True,  # async mode — returns ID immediately
)
```

**Path B — Codex CLI Python SDK (local filesystem):**
```python
from openai_codex_sdk import Codex

codex = Codex()
thread = codex.start_thread()
turn = await thread.run("Implement the backend services...")
print(turn.final_response)
```

**Path C — Agents SDK + MCP (multi-agent orchestration):**
```python
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async with MCPServerStdio(
    name="Codex CLI",
    params={"command": "npx", "args": ["-y", "codex", "mcp-server"]},
) as codex_mcp:
    agent = Agent(name="Developer", mcp_servers=[codex_mcp])
    result = await Runner.run(agent, "Implement backend services...")
```

Thread/request configuration supports:
- `model`: model selection (gpt-5.1-codex, gpt-5.3-codex, gpt-5.4)
- `cwd`: working directory (the project root)
- `approvalPolicy`: "never" for full-auto execution
- `sandbox`: readOnly, workspaceWrite, fullAccess (danger-full-access)
- `dynamicTools`: custom tool definitions
- `model_reasoning_effort`: low, medium, high, xhigh

### What does the response look like?

**Responses API** returns structured output items:
- `apply_patch_call` objects with `operation.type` (create_file, update_file,
  delete_file), `operation.path`, and `operation.diff` (V4A diff format)
- `shell_call` objects with command, stdout, stderr, exit_code
- Standard assistant message text

**CLI SDK** returns a turn object:
```python
result = await thread.run(prompt)
result.final_response   # text summary of what was done
result.items            # list of items (tool calls, file changes, messages)
result.usage            # token usage statistics
```

With `codex exec --json`, the CLI emits newline-delimited JSON events
including file change events with structured data. With `--output-schema`,
output conforms to a user-defined JSON schema.

### Sync vs async?

**All approaches support both:**

- **Responses API:** Synchronous by default. Set `background=True` for
  async (submit + poll). Also supports `stream=True` for SSE streaming.
  Background responses stored ~10 minutes for polling
- **CLI Python SDK:** Async-only (`run()` buffers; `run_streamed()` yields
  events)
- **CLI `codex exec`:** Synchronous (blocks until complete)
- **Codex Cloud:** Async (submit + poll via `codex cloud list`)

### Local directory or upload?

**Codex CLI operates directly on the local filesystem.** No upload needed.
The `cwd` parameter points at the project directory. Files are read and
modified in place — identical to how Claude Code SDK works.

Codex Cloud requires a GitHub-hosted repository (clones into remote sandbox).

### Can you scope read vs modify?

**Yes.** Sandbox policies control this precisely:

```json
{
  "type": "workspaceWrite",
  "writableRoots": ["/path/to/project/src"],
  "readOnlyAccess": {
    "type": "restricted",
    "readableRoots": ["/path/to/project"]
  },
  "networkAccess": false
}
```

This means we could restrict Codex to only write backend files while reading
the full project. However, this requires careful path configuration per wave.

### Max task duration and context window?

- **Context window:** 400,000 tokens (all GPT-5.x-Codex models), with
  128,000 max output tokens. GPT-5.4 has experimental 1M support (2x rate)
- **Task duration (ChatGPT plans):** Plus: 10 min, Team: 15 min, Pro: 30 min
- **Task duration (CLI):** Configurable via `agents.job_max_runtime_seconds`
  (default: 1800s / 30 min). No inherent limit for local CLI execution
- **Diff size limit:** Up to 5 MB per task
- **Our 10-20K specialist prompts:** Well within the 400K context window

### Rate limits and pricing?

**API token pricing (per 1M tokens):**

| Model | Input | Cached Input | Output |
|-------|-------|-------------|--------|
| gpt-5.1-codex-mini | $0.25 | -- | $2.00 |
| codex-mini-latest | $1.50 | $0.375 | $6.00 |
| gpt-5.2-codex | $1.25 | -- | $10.00 |
| **gpt-5.3-codex** | **$1.75** | **$0.175** | **$14.00** |
| gpt-5.4 | $62.50 | $6.25 | $375.00 |

**Claude pricing (for comparison, per 1M tokens):**

| Model | Input | Cached Input | Output |
|-------|-------|-------------|--------|
| Claude Sonnet 4.6 | $3.00 | $0.30 | $15.00 |
| Claude Opus 4.6 | $15.00 | $1.875 | $75.00 |

**Key cost finding:** GPT-5.3-Codex ($1.75/$14.00) is cheaper than Claude
Sonnet ($3.00/$15.00) on input and comparable on output. Community
benchmarks report Codex is **~4x more token-efficient** than Claude Code
(using fewer tokens for equivalent tasks), meaning effective cost savings
could be substantial.

**Estimated per-task costs (API):** Simple tasks ~$0.12, complex tasks
$0.40-$0.64, tasks with debugging $0.48-$0.72.

**API rate limits (GPT-5.3-Codex):**

| Tier | RPM | TPM |
|------|-----|-----|
| Tier 1 | 500 | 500K |
| Tier 5 | 15,000 | 40M |

**Sources:**
- https://developers.openai.com/codex/changelog (GPT-5-Codex in API)
- https://developers.openai.com/codex/pricing (credits, rate limits)
- https://developers.openai.com/codex/cli/reference (cloud exec, cloud list)
- https://github.com/openai/codex (CLI source, Python SDK)
- https://developers.openai.com/codex/app-server (JSON-RPC protocol)

---

## 2. Coding Without MCP

### Critical correction: Codex CLI DOES support MCP

From the official documentation (context7.com/openai/codex):

> "Support for MCP servers and project-specific context files helps tailor
> the AI's output to specific development environments."

The Codex CLI app-server supports MCP servers in its configuration. This
means **Context7 could be available to Codex** if using the CLI SDK path.
This significantly changes the risk calculus.

| Capability | Codex CLI (Local) | Codex Cloud |
|-----------|-------------------|-------------|
| MCP servers | **Yes** | No |
| Internet access | Configurable (`networkAccess`) | Setup phase only (configurable for agent) |
| Shell commands | **Yes** (full bash) | **Yes** (full bash) |
| npm install | **Yes** (local npm) | **Yes** (if packages cached or internet enabled) |
| Read project files | **Yes** (full filesystem) | **Yes** (cloned repo) |
| Git history | **Yes** | **Yes** |
| prisma generate, tsc | **Yes** | **Yes** (if toolchain installed) |

### Without Context7, how does Codex get accurate API docs?

If MCP is configured for the Codex CLI, Context7 works normally. If not:

| Framework | Codex Accuracy (training data only) | Risk Level |
|-----------|-------------------------------------|------------|
| React 18/19 | High | Low |
| Express.js | High | Low |
| NestJS | Medium-High (core patterns good, edge cases off) | Medium |
| Prisma | Medium-High (schema/CRUD solid, advanced queries less so) | Medium |
| TypeORM | Medium (less training data) | Medium-High |
| Next.js App Router | Medium-High (can mix Pages/App Router patterns) | Medium |
| Tailwind CSS | High | Low |
| FastAPI | High | Low |

### Risk assessment for our stacks

Our competition data showed Context7 unavailability caused incorrect API
assumptions. With Codex CLI + MCP enabled, this risk is **mitigated** — same
Context7 availability as Claude Code.

Without MCP (e.g., if MCP configuration proves difficult or unreliable for
Codex), the risk is **medium** for NestJS/Prisma stacks and **low** for
Express/React stacks. GPT-5-family models have extensive training data for
mainstream frameworks but may use deprecated patterns for rapidly evolving
APIs (e.g., Next.js App Router vs Pages Router confusion).

**Key difference from Claude:** Codex models may generate code with
different style conventions (import ordering, bracket placement, naming).
Shared linter/formatter configs (Prettier, ESLint) are essential for
consistency regardless of MCP availability.

---

## 3. The Handoff Problem

### Can Codex and Claude work on the SAME codebase in sequence?

**Yes — with the CLI SDK path, this is straightforward.**

Both Codex CLI and Claude Code SDK operate on the same local filesystem.
Files written by one are immediately available to the other. There is no
serialization, upload, or sync step needed.

| Question | Answer |
|----------|--------|
| Can Codex read files Claude wrote in Wave A? | **Yes.** Same filesystem. |
| Can Claude read files Codex wrote in Wave B? | **Yes.** Same filesystem. |
| Encoding/line-ending issues? | **Yes, on Windows.** Codex CLI has known CRLF/LF issues. Mitigated with `.gitattributes` (`* text=auto eol=lf`) and `git config core.autocrlf input`. |
| If Claude modifies a Codex-created file? | **No problems.** Regular file modification. |
| Can both see full git history? | **Yes.** Both use local git. |
| Does Codex create git commits? | **No.** CLI leaves changes unstaged. Wave executor would need to handle staging/committing between waves if desired. |

### The handoff flow for one milestone

```
1. Claude SDK (Wave A) → writes architecture report, TASKS.md
   └── Files exist on disk at cwd

2. Codex CLI SDK (Wave B.1) → reads Wave A output from disk, writes backend code
   └── Files modified in place at cwd (unstaged)

3. Claude SDK (Wave B.2) → reads Codex's code from disk, adds UI/styling
   └── Files modified in place at cwd

4. Python (Wave C) → reads backend code from disk, generates OpenAPI spec
   └── Standard file I/O

5. Codex or Claude (Wave D) → reads generated client, wires frontend
   └── Files modified in place at cwd

6. Claude SDK (Wave E) → runs Playwright via MCP, writes docs
   └── Standard Claude Code session
```

### Known issues to address

1. **CRLF/LF on Windows:** Add `.gitattributes` to generated projects
2. **No auto-commit:** Wave executor must manage git state between waves
   (currently not an issue since Claude Code also doesn't auto-commit)
3. **Style divergence:** Different models have different formatting habits.
   Run Prettier/ESLint between waves as a normalization step
4. **Context isolation:** Each agent session starts fresh. Wave artifacts
   (already used in our system) serve as the context bridge

### Community validation

Multiple community projects demonstrate this pattern working:
- **GitHub Agent HQ:** Multiple agents (Codex, Claude, Copilot) on same repo
- **agent-link-mcp:** Claude Code spawning Codex as subprocess via MCP
- **Sequential review patterns:** Claude implements, Codex reviews (or reverse)

**Sources:**
- https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/
- https://dev.to/alanwest/how-to-make-claude-codex-and-gemini-collaborate-on-your-codebase-40l2
- https://github.com/shakacode/claude-code-commands-skills-agents/blob/main/docs/claude-code-with-codex.md
- https://developers.openai.com/codex/agent-approvals-security (sandbox config)

---

## 4. Splitting Wave B into Logic and UI

### Can the wave executor make two separate calls for Wave B?

**Yes.** The current architecture already supports this cleanly.

`execute_milestone_waves()` iterates over a wave sequence list. Currently:
```python
WAVE_SEQUENCES = {
    "full_stack": ["A", "B", "C", "D", "E"],
}
```

This could become:
```python
WAVE_SEQUENCES = {
    "full_stack": ["A", "B1", "B2", "C", "D", "E"],
}
```

The `execute_sdk_call` callback is passed as a parameter — the executor
doesn't care which SDK it calls. A router function could dispatch B1 to
Codex and B2 to Claude based on the wave letter.

### How does Claude's UI wave know what Codex created?

**Two mechanisms already exist:**

1. **Filesystem:** Claude reads Codex's files directly from disk (same cwd)
2. **Wave artifacts:** The artifact store (`extract_wave_artifacts`) already
   captures what each wave produced. Wave B1's artifact would list created
   files, entities, services — and Wave B2's prompt builder would receive
   this artifact, identical to how Wave B currently receives Wave A artifacts

### Files that are both logic AND UI

This is the **hardest problem** in the proposed split. Examples:

| File Type | Logic Content | UI Content | Clean Split? |
|-----------|--------------|------------|--------------|
| Page component (e.g., `dashboard.tsx`) | Data fetching, state, handlers | Layout, styling, composition | **No** |
| Form component | Validation, submission logic | Input fields, layout, error display | **No** |
| Data table | Sorting, filtering, pagination logic | Column rendering, responsive layout | **No** |
| API client wrapper | HTTP calls, error handling | None | **Yes** (pure logic) |
| Service file | Business logic | None | **Yes** (pure logic) |
| CSS/Tailwind config | None | Pure styling | **Yes** (pure UI) |
| Layout component | Minimal logic | Structure, spacing, responsive | **Mostly UI** |

### Heuristic: Codex skeleton + Claude enhancement

**Partially realistic, with caveats.**

Codex creates the component with logic + skeleton markup:
```tsx
// Codex creates this
export function Dashboard() {
  const { data, isLoading } = useDashboardData();
  if (isLoading) return <div>Loading...</div>;
  return (
    <div>
      <h1>Dashboard</h1>
      {data.metrics.map(m => <div key={m.id}>{m.label}: {m.value}</div>)}
    </div>
  );
}
```

Claude enhances with styling and design:
```tsx
// Claude transforms to this
export function Dashboard() {
  const { data, isLoading } = useDashboardData();
  if (isLoading) return <LoadingSkeleton className="h-screen" />;
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-8">
      <h1 className="text-3xl font-bold text-slate-900 mb-8">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {data.metrics.map(m => (
          <MetricCard key={m.id} label={m.label} value={m.value} />
        ))}
      </div>
    </div>
  );
}
```

**Risks of this approach:**
- Claude may restructure component hierarchy (changing Codex's logic wiring)
- Codex's skeleton JSX may not map cleanly to Claude's design intent
- Two-pass file modification increases merge-conflict-like complexity
- If Codex's data fetching hook returns a different shape than Claude expects,
  the UI layer breaks

### Alternative: Split by directory

| Owner | Directories |
|-------|------------|
| Codex | `src/services/`, `src/controllers/`, `src/entities/`, `src/dtos/`, `src/guards/`, `src/middleware/`, `src/interceptors/`, `src/repositories/`, `src/state/`, `src/hooks/` (data-only), `src/api/`, `src/adapters/`, `src/utils/`, `src/validators/` |
| Claude | `src/components/`, `src/pages/`, `src/layouts/`, `src/styles/`, `src/design-system/` |
| **Ambiguous** | `src/pages/` with data fetching, `src/features/` (combined logic+UI) |

**The directory split is cleaner but still has the page-component problem.**
Pages in Next.js App Router are inherently mixed: they define both the data
loading (server components, `loader` functions) and the UI rendering.

### Recommendation for this question

The cleanest split is:
- **Codex writes ALL non-JSX/TSX files** (services, controllers, entities,
  state, hooks, utils, validators, API client wiring)
- **Codex writes page/component logic as exported functions/hooks** (not JSX)
- **Claude writes ALL JSX/TSX files** (components, pages, layouts) importing
  from Codex's logic exports
- **Shared contract:** An interface file or type definitions that both sides
  agree on (already exists as Wave A artifacts + IR specs)

This requires the prompt to enforce a strict separation: "export your logic
as hooks and utility functions; do not write JSX."

---

## 5. Fix Cycle Routing

### Can blast-radius analysis determine logic vs UI from file paths?

**Yes — the existing `_classify_feature_area()` and `analyze_blast_radius()`
functions already classify files by path.** Adding a logic-vs-UI dimension
is straightforward:

```python
def _classify_provider(file_path: str) -> str:
    """Determine whether a file belongs to Codex (logic) or Claude (UI)."""
    path = file_path.lower().replace("\\", "/")

    # Definite UI
    if any(seg in path for seg in ["/components/", "/pages/", "/layouts/",
                                     "/styles/", "/design-system/"]):
        return "claude"
    if path.endswith((".css", ".scss", ".module.css")):
        return "claude"

    # Definite logic
    if any(seg in path for seg in ["/controllers/", "/services/",
                                     "/entities/", "/dtos/", "/guards/",
                                     "/middleware/", "/repositories/"]):
        return "codex"
    if path.endswith((".controller.ts", ".service.ts", ".entity.ts",
                      ".dto.ts", ".guard.ts", ".module.ts")):
        return "codex"

    # Ambiguous
    if path.endswith((".tsx", ".jsx")):
        return "claude"  # default TSX/JSX to UI owner
    return "codex"  # default everything else to logic owner
```

### Heuristic reliability

| Defect Type | Routing | Confidence |
|-------------|---------|------------|
| Backend defect (broken API, wrong DTO) | Codex | **High** — file paths are unambiguous |
| Frontend logic (wrong state, bad validation) | Codex | **Medium** — state files clear, but validation may be in components |
| UI defect (wrong layout, bad styling) | Claude | **High** — TSX/CSS files are unambiguous |
| Integration defect (wrong endpoint called) | Codex | **High** — API client files are clearly logic |
| Cross-cutting (touches both logic and UI) | **Ambiguous** | **Low** — needs case-by-case routing |

### For ambiguous cases: default to Codex or Claude?

**Default to Claude.** Rationale:
- Claude already has the full project context (planning, testing, docs)
- Claude can modify both logic and UI if needed
- Codex fix cycles require spinning up a separate SDK session
- If Claude's fix touches logic that Codex "owns," there's no actual
  ownership enforcement — both write to the same filesystem

The cost of routing a logic fix to Claude is minor (Claude can write logic).
The cost of routing a UI fix to Codex is higher (Codex may lack design
context from Wave A and the frontend-design skill).

---

## 6. Practical Blockers

### Does Codex have a Python SDK?

**Yes — multiple options:**

| Package | Version | Mechanism | Install |
|---------|---------|-----------|---------|
| `openai` (standard) | Latest | Responses API (no CLI) | `pip install openai` |
| `openai-codex-sdk` | 0.1.11 | Wraps CLI binary via JSONL/stdin | `pip install openai-codex-sdk` |
| `codex-app-server-sdk` | 0.2.0 | JSON-RPC v2 with app-server | `pip install codex-app-server-sdk` |
| `openai-agents` | Latest | Codex as MCP server | `pip install openai-agents` |

**Important:** The `openai-codex-sdk` and `codex-app-server-sdk` packages
require the Codex CLI binary installed locally (`npm install -g @openai/codex`
or Rust binary). The standard `openai` package with Responses API does NOT
require the CLI — it uses hosted containers or returns patches your
application applies.

### Cost per task

**Token pricing comparison (per 1M tokens):**

| Model | Input | Output | Notes |
|-------|-------|--------|-------|
| gpt-5.3-codex | $1.75 | $14.00 | Best value Codex model |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Current wave executor default |
| Claude Opus 4.6 | $15.00 | $75.00 | Higher quality, 8.5x more expensive |
| gpt-5.4 | $62.50 | $375.00 | Frontier, very expensive |

**Effective cost advantage:** Community benchmarks show Codex is ~4x more
token-efficient than Claude Code (uses fewer tokens for equivalent tasks).
Combined with lower per-token pricing, **effective per-task cost for
GPT-5.3-Codex could be 5-7x cheaper than Claude Opus** and **2-3x cheaper
than Claude Sonnet** for backend coding tasks.

**Estimated per-task costs:** Simple fix ~$0.12, complex feature $0.40-0.64.

### Latency

- **Codex CLI (local):** No queue. Starts immediately. Latency depends on
  model inference speed (comparable to Claude Code)
- **Codex Cloud:** Tasks may queue. Reported startup latency of 30-90 seconds
  for environment provisioning
- **For our use case:** CLI path has no meaningful latency difference from
  Claude Code SDK

### Availability

- **Codex CLI:** Open source (github.com/openai/codex), runs anywhere with
  an OpenAI API key
- **API models:** GPT-5-Codex available via Responses API with standard
  API key
- **ChatGPT plans:** Plus, Pro, Team, Business, Edu, Enterprise
- **Regional restrictions:** Follows standard OpenAI API availability
  (same regions as GPT-4/GPT-5)

### Concurrent task limits

| Context | Concurrency |
|---------|-------------|
| **Codex CLI** (local) | `agents.max_threads` defaults to 6. Multiple CLI instances can run in parallel |
| **ChatGPT Plus** | 1 concurrent cloud task |
| **ChatGPT Pro** | 3 concurrent cloud tasks |
| **API (Tier 1)** | 500 RPM, 500K TPM |
| **API (Tier 5)** | 15,000 RPM, 40M TPM |

**For parallel milestones:** Each milestone could run its own Codex CLI
instance or API request. Git worktree isolation (already in Phase 4 config)
prevents filesystem conflicts. API rate limits are the practical constraint,
not a concurrency cap.

### Can Codex handle our prompt sizes?

**Yes.** Our specialist prompts are 10-20K tokens. GPT-5.x-Codex models
support 400K token context windows with 128K max output. Even with full
project context (codebase map, IR, artifacts), we stay well within limits.

---

## Key Blockers

### 1. Two-SDK dependency and operational complexity (HIGH)

Adding Codex CLI as a dependency means:
- Installing and maintaining the Codex CLI binary alongside Claude Code SDK
- Managing two API keys (ANTHROPIC_API_KEY + OPENAI_API_KEY)
- Monitoring two different rate limit buckets
- Debugging failures across two different model families
- Two different error handling patterns, response formats, telemetry schemas

### 2. Model quality divergence (HIGH)

GPT-5-Codex and Claude Opus/Sonnet have different:
- Coding styles (naming conventions, import ordering, bracket placement)
- Framework knowledge (different versions in training data)
- Instruction-following behavior (prompt engineering that works for Claude
  may not work for Codex, and vice versa)
- Error patterns (different failure modes require different fix strategies)

This means **every prompt must be tested and tuned for both models**, and
a linter/formatter normalization step is needed between waves.

### 3. The mixed-file ownership problem (MEDIUM)

Page components with both data fetching and UI rendering don't split cleanly.
Any heuristic will have edge cases. The "hooks export logic, TSX imports it"
pattern works but requires strict prompt enforcement and may produce
unnatural code architecture (premature abstraction to enable the split).

### 4. Reliability history (MEDIUM)

Codex has had significant reliability issues in its history:
- Mid-2025: tasks hanging 32-71 minutes, "Failed to sample tokens" errors
- Nov 2025: bug drained entire 5-hour quotas in 8 queries (OpenAI
  compensated with $200 credits)
- By early 2026: substantially improved, but no published SLA

For automated pipelines, reliability matters more than for interactive use.
A task failure in a multi-wave pipeline requires retry logic, fallback to
Claude, or human intervention. The wave executor needs robust error handling
for Codex-specific failure modes.

### 5. Windows CRLF/LF divergence (LOW)

Codex CLI has known line-ending issues on Windows. Mitigatable with
`.gitattributes` and git config, but adds a setup/configuration burden.

### 6. MCP configuration for Codex CLI (MEDIUM)

While Codex CLI supports MCP, the configuration mechanism differs from
Claude Code's. Context7 MCP server configuration for Codex needs to be
verified — it may require a different setup path or may not support all
MCP features Claude Code uses.

---

## Key Advantages

### From competition data (Codex won 3/3 on integration wiring)

1. **Codex excels at mechanical integration wiring** — connecting services
   to controllers, wiring DTOs, generating boilerplate. This aligns well
   with Wave B backend work
2. **Claude excels at breadth, documentation, and testing** — planning,
   verification, Playwright tests, design quality. This aligns well with
   Waves A, E, and UI work
3. **Significant cost reduction** — GPT-5.3-Codex at $1.75/$14.00 per 1M
   tokens is cheaper than Claude Sonnet ($3.00/$15.00) and dramatically
   cheaper than Claude Opus ($15.00/$75.00). Combined with ~4x token
   efficiency, routing backend coding (40-60% of total tokens) to Codex
   could reduce per-milestone costs by 30-50%

### Architectural advantages

4. **The callback pattern already exists** — `execute_milestone_waves()`
   takes `execute_sdk_call` as a parameter. Adding a second provider is
   a routing change, not an architectural rewrite
5. **Wave artifacts already bridge context** — the artifact store already
   passes structured context between waves. No new bridging mechanism needed
6. **Git worktree isolation already works** — Phase 4 parallel execution
   with git isolation is already implemented. Multiple providers per worktree
   would work the same way

### Operational advantages

7. **Redundancy** — if Claude API is down or rate-limited, Codex can handle
   coding waves (and vice versa). Provider diversity reduces single-point-
   of-failure risk
8. **Best-of-breed per task** — routing each wave to its strongest provider
   could improve overall output quality beyond what either provider achieves
   alone

---

## Wave Executor Changes (High-Level Description)

If this were to be implemented, the wave executor would need:

1. **A provider configuration** in `AgentTeamConfig.v18` — mapping wave
   letters to provider names (e.g., `{"A": "claude", "B1": "codex",
   "B2": "claude", "C": "python", "D": "codex", "E": "claude"}`)

2. **A Codex SDK client wrapper** — analogous to `ClaudeSDKClient`, wrapping
   `AsyncCodex` with the same interface: accept a prompt, return cost/result.
   Approximately 50-100 lines of Python

3. **A provider router** in `_execute_single_wave_sdk()` — check the wave
   letter against the provider map, instantiate the correct client. The
   existing callback pattern makes this a small change

4. **Wave B split into B1 + B2** — new entries in `WAVE_SEQUENCES`, new
   prompt builders (`build_wave_b1_prompt`, `build_wave_b2_prompt`), new
   artifact extraction for each sub-wave

5. **A post-wave normalization step** — run Prettier/ESLint after Codex
   waves to normalize coding style before Claude reads the output

6. **Fix cycle provider routing** — extend `_classify_fix_features()` with
   a `provider` field based on file path heuristics. Default ambiguous cases
   to Claude

7. **Dual telemetry** — extend the telemetry schema to track provider per
   wave, enabling cost comparison between Codex and Claude for equivalent
   work

---

## Recommended Next Step

**Run a controlled A/B test on a single milestone before committing to
implementation.**

### Proposed test

1. Pick one backend-heavy milestone from an existing project
2. Run it twice:
   - **Control:** Current system (Claude handles all waves)
   - **Treatment:** Codex CLI handles Wave B backend code only (manual,
     not automated — just use `codex exec` with the Wave B prompt)
3. Compare:
   - Code quality (compile errors, lint violations, test pass rate)
   - Framework accuracy (correct API usage for NestJS/Prisma/etc.)
   - Style consistency (diff formatting between Codex and Claude output)
   - Token usage and cost
   - Time to completion
4. If Codex matches or exceeds Claude on backend coding quality at lower
   cost, proceed with a minimal provider abstraction (items 1-3 above)
5. If Codex quality is significantly lower, the hybrid approach is not
   worth the complexity

### Why not jump to implementation?

The complexity of maintaining two provider SDKs, two prompt tuning paths,
two telemetry schemas, and a file-ownership routing system is only justified
if Codex demonstrably outperforms Claude on its assigned waves. Our
competition data suggests it might (3/3 on integration wiring), but that
was a different context (SWE-bench tasks, not our structured wave prompts).
One real test with our actual prompts and stacks will answer the question
definitively.

---

## Appendix: Integration Path Comparison

| Criterion | Codex CLI SDK (Local) | Codex Cloud | Codex Responses API |
|-----------|-----------------------|-------------|---------------------|
| Python SDK | `codex_app_server` (AsyncCodex) | CLI only (`codex cloud exec`) | `openai` Python package |
| Works on local files | **Yes** | No (remote sandbox) | No (returns patches) |
| MCP support | **Yes** | No | No |
| Internet access | Configurable | Setup only (configurable) | N/A |
| Auto-commits | No (unstaged changes) | Yes (creates PR) | N/A (returns diffs) |
| Multi-turn | Yes (thread resume) | No (single task) | Yes (conversation) |
| Prompt size limit | Model context window | Model context window | Model context window |
| Latency | Immediate | 30-90s setup | Immediate |
| Cost | API token-based | ChatGPT plan credits | API token-based |
| Shell commands | **Yes** (full bash) | **Yes** (full bash) | No |
| Parallel instances | **Yes** (separate processes) | Limited by plan | Limited by rate |
| Best for our use case? | **Yes** | No | Partial (no file I/O) |

## Appendix: Source Index

| Topic | Source |
|-------|--------|
| **Official Documentation** | |
| Codex Python SDK (PyPI) | https://pypi.org/project/openai-codex-sdk/ |
| Codex SDK docs | https://developers.openai.com/codex/sdk |
| Codex CLI reference | https://developers.openai.com/codex/cli/reference |
| Codex app-server protocol | https://developers.openai.com/codex/app-server |
| Codex sandbox/security | https://developers.openai.com/codex/agent-approvals-security |
| Codex sandboxing concepts | https://developers.openai.com/codex/concepts/sandboxing |
| Codex Cloud environments | https://developers.openai.com/codex/cloud/environments |
| Codex pricing | https://developers.openai.com/codex/pricing |
| Codex changelog (API) | https://developers.openai.com/codex/changelog |
| Codex subagents | https://developers.openai.com/codex/subagents |
| Codex non-interactive | https://developers.openai.com/codex/noninteractive |
| Codex GitHub Action | https://developers.openai.com/codex/github-action |
| Codex enterprise config | https://developers.openai.com/codex/enterprise/managed-configuration |
| Codex config reference | https://developers.openai.com/codex/config-reference |
| Codex auth | https://developers.openai.com/codex/auth |
| Codex Agents SDK guide | https://developers.openai.com/codex/guides/agents-sdk |
| OpenAI API pricing | https://developers.openai.com/api/docs/pricing |
| OpenAI shell tool docs | https://developers.openai.com/api/docs/guides/tools-shell |
| OpenAI apply_patch docs | https://developers.openai.com/api/docs/guides/tools-apply-patch |
| GPT-5.3-Codex model card | https://developers.openai.com/api/docs/models/gpt-5.3-codex |
| **Open Source** | |
| Codex CLI GitHub repo | https://github.com/openai/codex |
| Codex Python SDK source | https://github.com/openai/codex/tree/main/sdk/python |
| **Community / Comparisons** | |
| GitHub Agent HQ blog | https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/ |
| Multi-agent collaboration | https://dev.to/alanwest/how-to-make-claude-codex-and-gemini-collaborate-on-your-codebase-40l2 |
| Claude Code + Codex config | https://github.com/shakacode/claude-code-commands-skills-agents/blob/main/docs/claude-code-with-codex.md |
| Codex vs Claude comparison | https://www.builder.io/blog/codex-vs-claude-code |
| Codex pricing analysis | https://www.morphllm.com/codex-pricing |
| Multi-agent failure patterns | https://www.eqengineered.com/insights/multiple-coding-agents |
