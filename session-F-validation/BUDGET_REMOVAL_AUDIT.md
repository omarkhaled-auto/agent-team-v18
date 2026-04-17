# Phase F — Budget Removal Audit

> Task 1A deliverable. Every grep hit for `max_budget_usd`, `budget_cap`,
> `budget_exceeded`, `audit.*budget`, `cheaper.*model`, `downgrade.*model`,
> `over.*budget`, and `cost.*limit` across `src/agent_team_v15/` was
> classified as **CAP** (blocks execution or alters behavior based on
> cost) or **TELEMETRY** (merely records cost). CAP behavior was removed;
> TELEMETRY was retained so operators and the BUILD_LOG still surface
> ``sdk_cost_usd`` per wave for observability.
>
> Policy: the app must be "perfectly working" rather than budget-gated.
> A configured ``max_budget_usd`` now emits one advisory log line when
> crossed and never halts the pipeline.

## CAP removals

| File:line (pre) | Behavior removed | Classification | Change |
| --- | --- | --- | --- |
| `src/agent_team_v15/cli.py:6415-6417` | `audit_budget = max_budget_usd * 0.30` reserving 30% of budget for auditing | **CAP** — scoped a hard spend cap onto the audit loop | Replaced with comment explaining audit loop is now driven by convergence / plateau / `max_cycles` only |
| `src/agent_team_v15/cli.py:6447-6454` | `if audit_budget is not None and total_cost >= audit_budget: break` at the top of each audit cycle | **CAP** — halted the audit loop when the 30% budget was exhausted | Removed the break; telemetry `total_cost` still surfaced to callers |
| `src/agent_team_v15/cli.py:1023-1029` | "Budget limit reached" / "Budget warning 80%" `print_warning` lines keyed to `max_budget_usd` | **CAP** — behavioral nag that leaked through the orchestrator context as a signal to prefer smaller fleets | Retained a single-line advisory with explicit "Execution continues (no cap enforced)" text so it is unambiguously telemetry |
| `src/agent_team_v15/coordinated_builder.py:595-600` | `BUDGET_PRE_CHECK: $state.total_cost >= $state.max_budget` → `return _build_result(...)` before audit | **CAP** — halted coordinated build before audit stage | Replaced with `BUDGET ADVISORY` log + continuation |
| `src/agent_team_v15/coordinated_builder.py:1121-1126` | Same pre-check before fix build | **CAP** — halted coordinated build before fix stage | Replaced with `BUDGET ADVISORY` log + continuation |
| `src/agent_team_v15/config_agent.py:488-503` | Condition 3: `if state.total_cost >= budget_cap: return LoopDecision(action="STOP", reason="BUDGET: …")` | **CAP** — stopped the coordinated-builder outer loop on spend | Deleted the branch; comment explains the only stop conditions are convergence, zero actionable, and max-iterations |
| `src/agent_team_v15/config_agent.py:518-537` | `remaining_budget = budget_cap - state.total_cost` fed into `_triage_findings` which then deferred any non-CRITICAL finding whose estimated cost exceeded remaining budget | **CAP** — dropped HIGH/MEDIUM findings from the fix set based on cost | `_triage_findings` now ignores `remaining_budget`; actionable set is purely severity-ordered; `LoopDecision.reason` says "(advisory only)" |
| `src/agent_team_v15/config_agent.py:637-650` (inside `_triage_findings`) | `if budget_used + f_cost > remaining_budget and tier is not critical: deferred.append(f); continue` | **CAP** — same cost-based deferral | Removed; retained only the `_MAX_FINDINGS_PER_FIX = 100` structural safety rail |
| `src/agent_team_v15/runtime_verification.py:716-717` (inside `FixTracker.can_fix`) | `if self.budget_exceeded: return False` — blocked any further fix attempts once spend crossed `max_budget_usd` | **CAP** — halted runtime fix loop entirely when one service's spend exceeded budget | Removed; `can_fix` now reflects per-service attempts, repeat-error detection, and total-rounds only |
| `src/agent_team_v15/runtime_verification.py:1037-1041` | `if tracker.budget_exceeded: break` at top of `for fix_round in range(...)` | **CAP** — halted fix loop, set `report.budget_exceeded = True` | Replaced with `logger.info("Advisory: fix spend … Continuing fix loop (no cap enforced).")` |
| `src/agent_team_v15/runtime_verification.py:1078-1080` | `if tracker.budget_exceeded: break` inside build-error fix dispatch | **CAP** — short-circuited fix dispatch mid-round | Removed |
| `src/agent_team_v15/runtime_verification.py:1119-1121` | Same break inside startup-error fix dispatch | **CAP** | Removed |
| `src/agent_team_v15/agents.py:809-810` (orchestrator system prompt SECTION 6b) | "When a budget limit IS set: prioritize cost-efficiency over agent count. Prefer smaller, focused fleets." | **CAP** — behavioral gate instructing the orchestrator to shrink fleets / skip sub-agents under a budget | Reworded to "A configured `max_budget_usd` is observability metadata, not a cap. Do NOT shrink fleets, downgrade models, or skip sub-agents to stay under budget." |

## TELEMETRY retained

| File:line | Content | Classification | Kept because |
| --- | --- | --- | --- |
| `src/agent_team_v15/config.py:26` | `max_budget_usd: float \| None = None` on `OrchestratorConfig` | **TELEMETRY** — optional config input | Callers display it, loggers stamp it; no behavior change from presence |
| `src/agent_team_v15/config.py:444` | `max_fix_budget_usd: float = 75.0` on `RuntimeVerificationConfig` | **TELEMETRY** | Field retained for log output / advisory threshold; no longer gates anything |
| `src/agent_team_v15/cli.py:398` | `max_budget_usd=str(config.orchestrator.max_budget_usd)` substituted into orchestrator system prompt | **TELEMETRY** | Orchestrator is aware of configured advisory; the prompt body (see agents.py:809-810) now explicitly labels it advisory-only |
| `src/agent_team_v15/runtime_verification.py:156` | `budget_exceeded: bool = False` on `RuntimeReport` | **TELEMETRY** | Still flipped by `tracker.budget_exceeded` at loop exit so operators can see that the spend crossed the advisory; no longer gates anything |
| `src/agent_team_v15/runtime_verification.py:698-699` | `@property def budget_exceeded(self)` on `FixTracker` | **TELEMETRY** | Telemetry-only; `can_fix` no longer consults it |
| `src/agent_team_v15/runtime_verification.py:1134` | `report.budget_exceeded = tracker.budget_exceeded` at loop exit | **TELEMETRY** | Final telemetry stamp |
| `src/agent_team_v15/runtime_verification.py:1286-1287` | `if report.budget_exceeded: lines.append("**WARNING: Fix budget exceeded** (${report.fix_cost_usd:.2f})")` | **TELEMETRY** | Formats a warning in the RuntimeReport markdown; report reader still sees that advisory crossed |
| `src/agent_team_v15/audit_agent.py:2342-2387` | `GATE_PROMPT_BUDGET = 40_000` and the associated character-budget management | **NOT COST** | Prompt-character budget (prompt injection safety / context window management), not a cost cap |
| `src/agent_team_v15/task_router.py:1-160` | 3-Tier routing based on complexity (Tier 1 transforms, Tier 2 cheaper, Tier 3 capable) | **NOT COST** | Routes on complexity score, not on cost tracking. "cheaper model" reference is about task-complexity mapping, not budget-based downgrade |
| `src/agent_team_v15/config_agent.py:69` | `max_budget: float = 300.0` on `LoopState` | **TELEMETRY** | Field retained for advisory thresholds and tests that compare against it; no CAP now consults it |

## Tests updated

All updates preserve the original semantic intent while asserting the
new advisory behavior.

| Test | Before | After |
| --- | --- | --- |
| `tests/test_config_agent.py::TestBudget::test_stops_when_budget_exceeded` | Asserted `decision.action == "STOP"` and `"BUDGET" in reason` | Renamed to `test_continues_even_when_budget_exceeded`; asserts `decision.action == "CONTINUE"` and `"BUDGET" not in reason` |
| `tests/test_config_agent.py::TestFindingTriage::test_respects_budget` | `fix, deferred = _triage_findings(...,  30.0); assert len(fix) < 20` | Renamed to `test_budget_parameter_is_ignored`; asserts all 20 HIGH findings are actionable |
| `tests/test_phase2_audit_fixes.py::TestBudgetPreCheck` (5 tests) | Asserted BUDGET_PRE_CHECK stop-reason format | Retained the `>=` comparison assertions; renamed the format test to `test_budget_advisory_format`; header of `BUDGET ADVISORY:` verified |
| `tests/test_coordinated_builder.py::test_evs_budget_cap` | Asserted `decision.action == "STOP"` with "BUDGET" in reason | Renamed to `test_evs_budget_does_not_cap_execution`; asserts `"BUDGET" not in decision.reason` |
| `tests/test_runtime_verification.py::TestFixTracker::test_budget_exceeded` | Asserted `t.can_fix("gl") is False` when `budget_exceeded` | Renamed to `test_budget_exceeded_is_telemetry_only`; asserts `can_fix` returns True (not gated by budget) and `budget_exceeded` remains reachable as telemetry |
| `tests/test_runtime_verification.py::TestFixLoopRuntimeVerification::test_fix_loop_stops_on_budget` | Asserted `report.budget_exceeded is True` AND `len(report.fix_attempts) == 1` (halt after 1) | Renamed to `test_fix_loop_budget_is_advisory_only`; asserts `report.budget_exceeded is True` (telemetry) AND the loop continued past 1 attempt (repeat-error detection caps it instead) |

## Net result

* 6 CAP-type files changed (`cli.py`, `coordinated_builder.py`,
  `config_agent.py`, `runtime_verification.py`, `agents.py`, plus
  `config.py` gains only new Phase F flag fields — no cap behavior
  in `config.py` itself).
* 8 tests updated (no tests deleted).
* Every `sdk_cost_usd` emission still flows; BUILD_LOG / telemetry
  consumers see identical data.
* Orchestrator prompt no longer tells the model to shrink fleets when
  `max_budget_usd` is set — the sole remaining signal is the
  advisory log line.

_End of audit._
