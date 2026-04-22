"""Configuration loading and validation for Agent Team."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorConfig:
    model: str = "opus"
    max_turns: int = 1500
    permission_mode: str = "acceptEdits"
    max_budget_usd: float | None = None
    backend: str = "auto"  # "auto" | "api" | "cli"
    max_thinking_tokens: int | None = None


@dataclass
class DepthConfig:
    default: str = "standard"
    auto_detect: bool = True
    scan_scope_mode: str = "auto"  # "auto" (depth-based), "full" (always full), "changed" (always changed-only)
    keyword_map: dict[str, list[str]] = field(default_factory=lambda: {
        "quick": ["quick", "fast", "simple"],
        "thorough": [
            "thorough", "thoroughly", "careful", "carefully", "deep", "detailed",
            "refactor", "redesign", "restyle", "rearchitect", "overhaul",
            "rewrite", "restructure", "revamp", "modernize",
        ],
        "exhaustive": [
            "exhaustive", "exhaustively", "comprehensive",
            "comprehensively", "complete",
            "migrate", "migration", "replatform", "entire", "every", "whole",
        ],
    })


@dataclass
class ConvergenceConfig:
    max_cycles: int = 10
    escalation_threshold: int = 3
    max_escalation_depth: int = 2
    requirements_dir: str = ".agent-team"
    requirements_file: str = "REQUIREMENTS.md"
    master_plan_file: str = "MASTER_PLAN.md"
    min_convergence_ratio: float = 0.9
    recovery_threshold: float = 0.8
    degraded_threshold: float = 0.5


def _validate_convergence_config(cfg: ConvergenceConfig) -> None:
    """Validate ConvergenceConfig threshold values and relationships."""
    if not (0.0 <= cfg.min_convergence_ratio <= 1.0):
        raise ValueError("convergence.min_convergence_ratio must be between 0.0 and 1.0")
    if not (0.0 <= cfg.recovery_threshold <= 1.0):
        raise ValueError("convergence.recovery_threshold must be between 0.0 and 1.0")
    if not (0.0 <= cfg.degraded_threshold <= 1.0):
        raise ValueError("convergence.degraded_threshold must be between 0.0 and 1.0")
    if cfg.recovery_threshold > cfg.min_convergence_ratio:
        raise ValueError(
            "convergence.recovery_threshold must be <= min_convergence_ratio"
        )


@dataclass
class AgentConfig:
    model: str = "opus"
    enabled: bool = True


@dataclass
class MCPServerConfig:
    enabled: bool = True


@dataclass
class InterviewConfig:
    enabled: bool = True
    model: str = "opus"
    max_exchanges: int = 50
    min_exchanges: int = 3
    require_understanding_summary: bool = True
    require_codebase_exploration: bool = True
    max_thinking_tokens: int | None = None


def _validate_max_thinking_tokens(value: int | None, section: str) -> None:
    """Validate max_thinking_tokens: must be None or >= 1024 (SDK minimum)."""
    if value is not None and value < 1024:
        raise ValueError(f"{section}.max_thinking_tokens must be >= 1024 (got {value})")


def _validate_interview_config(cfg: InterviewConfig) -> None:
    if cfg.min_exchanges < 1:
        raise ValueError("min_exchanges must be >= 1")
    if cfg.min_exchanges > cfg.max_exchanges:
        raise ValueError("min_exchanges must be <= max_exchanges")
    _validate_max_thinking_tokens(cfg.max_thinking_tokens, "interview")


@dataclass
class InvestigationConfig:
    enabled: bool = False              # Explicit opt-in (requires Gemini CLI install)
    gemini_model: str = ""             # Empty = default; e.g. "gemini-2.5-pro"
    max_queries_per_agent: int = 8     # Hard ceiling — agent decides how many to use
    timeout_seconds: int = 120         # Max seconds per Gemini query
    agents: list[str] = field(default_factory=lambda: [
        "code-reviewer", "security-auditor", "debugger",
    ])
    sequential_thinking: bool = True          # Enable ST when investigation enabled
    max_thoughts_per_item: int = 15           # Thought step budget per item
    enable_hypothesis_loop: bool = True       # Require hypothesis-verification cycles


_VALID_INVESTIGATION_AGENTS = frozenset({
    "code-reviewer", "security-auditor", "debugger",
    "planner", "researcher", "architect", "task-assigner",
    "pseudocode-writer",
    "code-writer", "test-runner", "integration-agent",
    "contract-generator", "spec-validator",
})


def _validate_investigation_config(cfg: InvestigationConfig) -> None:
    if cfg.max_queries_per_agent < 1:
        raise ValueError("investigation.max_queries_per_agent must be >= 1")
    if cfg.timeout_seconds < 1:
        raise ValueError("investigation.timeout_seconds must be >= 1")
    if cfg.max_thoughts_per_item < 3:
        raise ValueError("investigation.max_thoughts_per_item must be >= 3")
    for agent in cfg.agents:
        if agent not in _VALID_INVESTIGATION_AGENTS:
            raise ValueError(
                f"investigation.agents contains invalid agent name: {agent!r}. "
                f"Valid agents: {sorted(_VALID_INVESTIGATION_AGENTS)}"
            )


@dataclass
class OrchestratorSTConfig:
    """Sequential Thinking at the orchestrator level — depth-gated decision points."""
    enabled: bool = True                    # On by default (depth-gated anyway)
    depth_gate: dict[str, list[int]] = field(default_factory=lambda: {
        "quick": [1, 2, 3, 4],             # All points — depth is scale, not reasoning
        "standard": [1, 2, 3, 4, 5],
        "thorough": [1, 2, 3, 4, 5],
        "exhaustive": [1, 2, 3, 4, 5],
        "enterprise": [1, 2, 3, 4, 5],
    })
    thought_budgets: dict[int, int] = field(default_factory=lambda: {
        1: 8,    # Pre-run strategy: max 8 thoughts
        2: 10,   # Architecture checkpoint: max 10 thoughts
        3: 12,   # Convergence reasoning: max 12 thoughts
        4: 8,    # Completion verification: max 8 thoughts
        5: 8,    # Pseudocode review: max 8 thoughts
    })


@dataclass
class DesignReferenceConfig:
    urls: list[str] = field(default_factory=list)
    depth: str = "full"  # "branding" | "screenshots" | "full"
    max_pages_per_site: int = 5
    cache_ttl_seconds: int = 7200  # 2 hours
    standards_file: str = ""  # empty = built-in; path = custom file
    require_ui_doc: bool = True          # Hard-fail when extraction fails
    ui_requirements_file: str = "UI_REQUIREMENTS.md"  # Output filename
    extraction_retries: int = 2          # retry attempts for Firecrawl extraction
    fallback_generation: bool = True     # generate heuristic UI doc when extraction fails
    content_quality_check: bool = True   # validate section CONTENT, not just headers


@dataclass
class DisplayConfig:
    show_cost: bool = True
    show_tools: bool = True
    show_fleet_composition: bool = True
    show_convergence_status: bool = True
    verbose: bool = False


@dataclass
class CodebaseMapConfig:
    enabled: bool = True
    max_files: int = 5000
    max_file_size_kb: int = 50       # Python files
    max_file_size_kb_ts: int = 100   # TS/JS files (codegen can be larger)
    timeout_seconds: int = 30
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "node_modules", ".git", "__pycache__", "dist", "build", ".next", "venv",
    ])


@dataclass
class SchedulerConfig:
    enabled: bool = True              # enabled by default
    max_parallel_tasks: int = 5
    conflict_strategy: str = "artificial-dependency"
    enable_context_scoping: bool = True
    enable_critical_path: bool = True


@dataclass
class QualityConfig:
    """Controls production-readiness and code craft quality features."""
    production_defaults: bool = True       # Inject production-readiness TECH-xxx into planner
    craft_review: bool = True              # Enable CODE CRAFT review pass in reviewers
    quality_triggers_reloop: bool = True   # Quality violations feed back into convergence


@dataclass
class VerificationConfig:
    enabled: bool = True              # enabled by default
    contract_file: str = "CONTRACTS.json"
    verification_file: str = "VERIFICATION.md"
    blocking: bool = True
    run_lint: bool = True
    run_type_check: bool = True
    run_tests: bool = True
    run_build: bool = True
    run_security: bool = True
    run_quality_checks: bool = True
    min_test_count: int = 0


@dataclass
class PseudocodeConfig:
    """Configuration for the pseudocode validation phase.

    When ``enabled`` is True, a pseudocode-writer fleet produces language-agnostic
    pseudocode for each task BEFORE code-writers begin implementation. The architect
    fleet reviews and approves pseudocode as a mandatory gate.
    """

    enabled: bool = False                    # Explicit opt-in
    require_architect_approval: bool = True   # Architect must approve before coding
    output_dir: str = "pseudocode"           # Subdirectory under .agent-team/
    complexity_analysis: bool = True          # Require Big-O analysis
    edge_case_minimum: int = 3               # Minimum edge cases per pseudocode doc


@dataclass
class ConstraintEntry:
    text: str
    category: str  # "prohibition" | "requirement" | "scope"
    source: str    # "task" | "interview"
    emphasis: int  # 1=normal, 2=caps, 3=caps+emphasis word


@dataclass
class DepthDetection:
    level: str
    source: str  # "keyword" | "scope" | "default" | "override"
    matched_keywords: list[str]
    explanation: str

    def __str__(self) -> str:
        return self.level

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.level == other
        if isinstance(other, DepthDetection):
            return self.level == other.level
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.level)

    def __getattr__(self, name: str):
        # Guard against recursion during copy/pickle/deepcopy: these
        # protocols probe for __reduce__, __getstate__, etc. before
        # __dict__ is populated, which would cause self.level to
        # re-enter __getattr__ infinitely.
        try:
            level = self.__dict__["level"]
        except KeyError:
            raise AttributeError(name) from None
        return getattr(level, name)


@dataclass
class MilestoneConfig:
    """Configuration for the per-milestone orchestration loop.

    Only affects PRD mode.  When ``enabled`` is False (the default),
    the milestone loop is completely bypassed and non-PRD mode is
    unchanged.
    """

    enabled: bool = False
    max_parallel_milestones: int = 1
    health_gate: bool = True
    wiring_check: bool = True
    resume_from_milestone: str | None = None
    wiring_fix_retries: int = 1
    max_milestones_warning: int = 30
    review_recovery_retries: int = 1  # Max review recovery attempts per milestone
    mock_data_scan: bool = True       # Scan for mock data after each milestone
    ui_compliance_scan: bool = True      # scan for UI compliance after each milestone
    milestone_timeout_seconds: int = 1800  # 30 minutes default per-milestone timeout


@dataclass
class PostOrchestrationScanConfig:
    """Configuration for post-orchestration quality scans.

    These scans run after the main orchestration loop in ALL modes.
    They were previously on MilestoneConfig but are mode-agnostic.
    """

    mock_data_scan: bool = True       # Scan for mock data in service files
    ui_compliance_scan: bool = True   # Scan for UI compliance violations
    api_contract_scan: bool = True    # Scan for API contract field mismatches
    silent_data_loss_scan: bool = True  # SDL-001 CQRS persistence check
    endpoint_xref_scan: bool = True   # XREF-001 frontend-backend endpoint cross-reference
    handler_completeness_scan: bool = True  # STUB-001 log-only event handler detection (v16)
    enum_registry_scan: bool = True        # ENUM-001/002/003 validation
    response_shape_scan: bool = True       # SHAPE-001/002/003 validation
    soft_delete_scan: bool = True          # SOFTDEL-001/002 validation
    auth_flow_scan: bool = True            # AUTH-001/002/003/004 validation
    infrastructure_scan: bool = True       # INFRA-001 through INFRA-005
    schema_validation_scan: bool = True    # SCHEMA-001 through SCHEMA-010
    cross_service_scan: bool = True        # XSVC-001/002 event pub/sub validation
    api_completeness_scan: bool = True     # API-001/002 CRUD endpoint completeness
    max_scan_fix_passes: int = 1  # Max fix iterations per scan (1=single pass, 2+=multi-pass)
    scan_exclude_dirs: list[str] = field(default_factory=list)  # Extra dirs to exclude from scans


@dataclass
class ContractScanConfig:
    """Configuration for contract compliance scans (CONTRACT-001 through CONTRACT-004).

    These scans verify implementation against service contracts using
    static analysis. Each scan can be individually enabled/disabled.
    """

    endpoint_schema_scan: bool = True     # CONTRACT-001: Response DTO field verification
    missing_endpoint_scan: bool = True    # CONTRACT-002: Route existence verification
    event_schema_scan: bool = True        # CONTRACT-003: Event payload verification
    shared_model_scan: bool = True        # CONTRACT-004: Shared model field/casing verification


@dataclass
class PRDChunkingConfig:
    """Configuration for large PRD chunking.

    When a PRD exceeds the size threshold, it is split into focused
    chunks before the PRD Analyzer Fleet is deployed. This prevents
    context overflow for very large PRDs.
    """

    enabled: bool = True
    threshold: int = 80000  # bytes - PRDs larger trigger chunking
    max_chunk_size: int = 20000  # bytes - target size per chunk


@dataclass
class E2ETestingConfig:
    """Configuration for the end-to-end testing phase.

    When ``enabled`` is True, the E2E phase runs after UI compliance scan
    to verify the built application actually works end-to-end.  Explicit
    opt-in because it is an expensive phase (sub-orchestrator sessions).
    """

    enabled: bool = False               # Explicit opt-in (expensive phase)
    backend_api_tests: bool = True      # Part 1: Backend API E2E
    frontend_playwright_tests: bool = True  # Part 2: Playwright E2E
    max_fix_retries: int = 5            # Fix-rerun cycles per part (min 1)
    test_port: int = 9876               # Non-standard port for test isolation
    skip_if_no_api: bool = True         # Auto-skip Part 1 if no API detected
    skip_if_no_frontend: bool = True    # Auto-skip Part 2 if no frontend detected


@dataclass
class BrowserTestingConfig:
    """Interactive browser testing via Playwright MCP for production readiness.

    When ``enabled`` is True, the browser testing phase runs after E2E testing
    to verify the built application works end-to-end through a real browser.
    Explicit opt-in because it is an expensive phase (sub-orchestrator sessions).
    """

    enabled: bool = False               # Opt-in (cost: $5-15 per phase)
    max_fix_retries: int = 5            # Per-workflow fix attempts (min 1)
    e2e_pass_rate_gate: float = 0.7     # Minimum E2E pass rate to proceed
    headless: bool = True               # Headless browser mode
    app_start_command: str = ""         # Override auto-detected start (empty = auto)
    app_port: int = 0                   # Override auto-detected port (0 = auto)
    regression_sweep: bool = True       # Quick regression check after fixes


@dataclass
class IntegrityScanConfig:
    """Configuration for post-build integrity scans.

    Three lightweight static analysis checks that run before the E2E phase:
    deployment config verification, PRD reconciliation, and asset integrity.
    All produce warnings (non-blocking) and default to enabled since they
    are cheap regex/filesystem scans.
    """

    deployment_scan: bool = True      # Scan docker-compose/nginx for port/env/CORS mismatches
    asset_scan: bool = True           # Scan templates for broken asset references
    prd_reconciliation: bool = True   # Verify quantitative PRD claims match code


@dataclass
class RuntimeVerificationConfig:
    """Configuration for runtime verification (v16.5).

    When enabled, the pipeline builds Docker images, starts services,
    runs migrations, and performs smoke tests against live endpoints
    AFTER code generation completes. Opt-in because it requires Docker.
    """

    enabled: bool = True               # Enabled by default — skips gracefully if Docker unavailable
    docker_build: bool = True          # Build Docker images
    docker_start: bool = True          # Start containers
    database_init: bool = True         # Run SQL migrations
    smoke_test: bool = True            # Hit health + CRUD endpoints
    cleanup_after: bool = False        # docker compose down after verification
    max_build_fix_rounds: int = 2      # DEPRECATED — use max_fix_rounds_per_service
    startup_timeout_s: int = 90        # Seconds to wait for services to be healthy
    compose_file: str = ""             # Override compose file path (empty = auto-detect)
    # v16.5 fix loop settings
    fix_loop: bool = True              # Keep fixing until all services healthy (or budget exhausted)
    max_fix_rounds_per_service: int = 3  # Give up on a service after N failures
    max_total_fix_rounds: int = 5      # Global circuit breaker across all services
    max_fix_budget_usd: float = 75.0   # Hard cap on fix cycle spending


@dataclass
class TrackingDocumentsConfig:
    """Configuration for per-phase tracking documents.

    Three documents provide structured memory across agent phases:
    - E2E Coverage Matrix maps requirements to tests for completeness
    - Fix Cycle Log tracks fix attempts to prevent repeated strategies
    - Milestone Handoff documents interfaces between milestones
    """

    e2e_coverage_matrix: bool = True       # Generate E2E_COVERAGE_MATRIX.md before E2E testing
    fix_cycle_log: bool = True             # Maintain FIX_CYCLE_LOG.md across all fix loops
    milestone_handoff: bool = True         # Generate MILESTONE_HANDOFF.md in PRD+ mode
    coverage_completeness_gate: float = 0.8   # Minimum coverage ratio to pass E2E (0.0-1.0)
    wiring_completeness_gate: float = 1.0     # Minimum wiring ratio to pass milestone (0.0-1.0)
    contract_compliance_matrix: bool = True   # Generate CONTRACT_COMPLIANCE_MATRIX.md after contract scans


@dataclass
class DatabaseScanConfig:
    """Configuration for database integrity static scans.

    Three lightweight static analysis checks that detect cross-layer type
    inconsistencies, missing defaults, and incomplete ORM relationships.
    All produce warnings (non-blocking) and default to enabled since they
    are cheap regex/filesystem scans.
    """

    dual_orm_scan: bool = True        # Detect type mismatches between ORM and raw queries
    default_value_scan: bool = True   # Detect missing defaults and unsafe nullable access
    relationship_scan: bool = True    # Detect incomplete ORM relationship configuration


@dataclass
class TechResearchConfig:
    """Configuration for the mandatory tech stack research phase (Phase 1.5).

    When ``enabled`` is True, the pipeline detects the project tech stack
    (with versions) and queries Context7 for documentation-backed best
    practices before milestone execution begins.
    """

    enabled: bool = True
    max_techs: int = 20              # Cap on technologies to research
    max_queries_per_tech: int = 4    # Context7 queries per technology
    retry_on_incomplete: bool = True  # Retry research if coverage < min
    injection_max_chars: int = 6000  # Max chars for prompt injection summary
    expanded_queries: bool = True    # Generate expanded best-practice/integration queries
    max_expanded_queries: int = 4    # Extra queries per technology beyond basic version query


@dataclass
class AuditTeamConfig:
    """Configuration for the audit-team review system.

    When ``enabled`` is True, the audit-team replaces the single code-reviewer
    with 5 parallel specialized auditors, a scorer agent, fix dispatch, and
    re-audit loop. Opt-in by default (disabled) — set ``enabled: true`` in
    config or use thorough/exhaustive depth.
    """

    enabled: bool = False
    max_parallel_auditors: int = 5
    max_reaudit_cycles: int = 3
    fix_severity_threshold: str = "MEDIUM"
    score_healthy_threshold: float = 90.0
    score_degraded_threshold: float = 70.0
    context7_prefetch: bool = True
    max_findings_per_fix_task: int = 5
    skip_overlapping_scans: bool = True


def _validate_audit_team_config(cfg: AuditTeamConfig) -> None:
    """Validate AuditTeamConfig fields."""
    valid_severities = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
    if cfg.fix_severity_threshold not in valid_severities:
        raise ValueError(
            f"audit_team.fix_severity_threshold must be one of {valid_severities}, "
            f"got {cfg.fix_severity_threshold!r}"
        )
    if cfg.max_parallel_auditors < 1 or cfg.max_parallel_auditors > 5:
        raise ValueError("audit_team.max_parallel_auditors must be 1-5")
    if cfg.max_reaudit_cycles < 0:
        raise ValueError("audit_team.max_reaudit_cycles must be >= 0")
    if not (0.0 <= cfg.score_healthy_threshold <= 100.0):
        raise ValueError("audit_team.score_healthy_threshold must be 0-100")
    if not (0.0 <= cfg.score_degraded_threshold <= 100.0):
        raise ValueError("audit_team.score_degraded_threshold must be 0-100")
    if cfg.score_degraded_threshold > cfg.score_healthy_threshold:
        raise ValueError(
            "audit_team.score_degraded_threshold must be <= score_healthy_threshold"
        )
    if cfg.max_findings_per_fix_task < 1:
        raise ValueError("audit_team.max_findings_per_fix_task must be >= 1")
    if cfg.max_findings_per_fix_task > 20:
        raise ValueError("audit_team.max_findings_per_fix_task must be <= 20")


@dataclass
class PhaseLeadConfig:
    """Configuration for a single phase lead in the team architecture."""
    enabled: bool = True
    model: str = ""                 # empty = inherit from agent_teams.phase_lead_model or orchestrator
    max_sub_agents: int = 10        # max parallel sub-agents this lead can deploy
    tools: list[str] = field(default_factory=list)
    idle_timeout: int = 600         # seconds before considered stalled


@dataclass
class PhaseLeadsConfig:
    """Configuration for the phase lead team architecture.

    When enabled, the orchestrator registers phase leads as SDK subagents
    (AgentDefinition objects) that are invoked via the Task tool. Each lead
    is aligned to a Claude persistent-session wave (A, D5, T, E).
    """
    enabled: bool = False
    wave_a_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Write", "Edit"],
    ))
    wave_d5_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    wave_t_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    ))
    wave_e_lead: PhaseLeadConfig = field(default_factory=lambda: PhaseLeadConfig(
        tools=["Read", "Grep", "Glob", "Bash"],
    ))
    handoff_timeout_seconds: int = 300
    allow_parallel_phases: bool = True


@dataclass
class EnterpriseModeConfig:
    """Configuration for enterprise-scale builds (150K+ LOC).

    When enabled, the architecture phase produces a domain OWNERSHIP_MAP.json
    that drives parallel domain-specialized coding agents and scoped review.
    Requires phase_leads.enabled = True.
    """
    enabled: bool = False
    multi_step_architecture: bool = True
    domain_agents: bool = True
    max_backend_devs: int = 3
    max_frontend_devs: int = 2
    max_infra_devs: int = 1
    parallel_review: bool = True
    wave_state_persistence: bool = True
    ownership_validation_gate: bool = True
    scaffold_shared_files: bool = True
    department_model: bool = False  # v2: replace single phase leads with departments


@dataclass
class DepartmentConfig:
    """Configuration for a single department (e.g., coding or review)."""
    enabled: bool = False
    max_managers: int = 4
    max_workers_per_manager: int = 5
    communication_timeout: int = 300   # seconds before a stuck manager is killed
    wave_timeout: int = 1800           # seconds per wave execution


@dataclass
class DepartmentsConfig:
    """Configuration for the department model (enterprise v2).

    When enabled, coding and review phases use TeamCreate departments
    instead of single phase leads. Requires enterprise_mode.enabled = True
    and agent_teams.enabled = True.
    """
    enabled: bool = False  # master switch — sub-department .enabled flags only matter when True
    coding: DepartmentConfig = field(default_factory=lambda: DepartmentConfig(
        enabled=True, max_managers=4,
    ))
    review: DepartmentConfig = field(default_factory=lambda: DepartmentConfig(
        enabled=True, max_managers=3,
    ))


@dataclass
class ObserverConfig:
    """Configuration for the orchestrator peek / semantic observer system.

    log_only=True (default): observer runs but NEVER calls client.interrupt() or turn/steer.
    All verdicts are written to .agent-team/observer_log.jsonl only.
    Set log_only=False only after reviewing 3+ builds of clean log output.

    Two observation strategies (selected automatically per wave type):
    - Claude waves (A, D5, T, E): file-poll peek calls via Anthropic API (Haiku model)
    - Codex waves (A5, B, D, T5): notification-based - reacts to turn/plan/updated and
      turn/diff/updated events directly, no additional API calls needed.
    """

    enabled: bool = False
    log_only: bool = True
    confidence_threshold: float = 0.75
    context7_enabled: bool = True
    context7_fallback_to_training: bool = True
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    peek_cooldown_seconds: float = 60.0
    peek_timeout_seconds: float = 5.0
    # Skip peek candidates whose mtime is within this many seconds — avoids mid-write race.
    peek_settle_seconds: float = 5.0
    max_peeks_per_wave: int = 5
    time_based_interval_seconds: float = 300.0
    # Codex-specific: react to notification events instead of polling files
    codex_notification_observer_enabled: bool = True
    # Thresholds for plan/diff analysis
    codex_plan_check_enabled: bool = True     # steer on bad plan (before files written)
    codex_diff_check_enabled: bool = True     # steer on bad diff (as files are written)


@dataclass
class AgentTeamsConfig:
    """Configuration for Claude Code Agent Teams integration (Build 2).

    When enabled, the pipeline uses Agent Teams for parallel task execution
    instead of subprocess-based orchestration. Requires CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1.
    """
    enabled: bool = False
    fallback_to_cli: bool = True
    delegate_mode: bool = True
    max_teammates: int = 5
    teammate_model: str = ""
    teammate_permission_mode: str = "acceptEdits"
    teammate_idle_timeout: int = 300
    task_completed_hook: bool = True
    wave_timeout_seconds: int = 3600    # 1 hour per wave
    task_timeout_seconds: int = 1800    # 30 minutes per task
    teammate_display_mode: str = "in-process"  # "in-process" | "tmux" | "split"
    contract_limit: int = 100           # max contracts in CLAUDE.md before truncation
    team_name_prefix: str = "build"     # prefix for team names (e.g. "build-milestone-1")
    phase_lead_model: str = ""          # model for phase leads, empty = inherit from orchestrator
    phase_lead_max_turns: int = 200     # max turns per phase lead agent
    auto_shutdown: bool = True          # auto-shutdown team on completion


@dataclass
class ContractEngineConfig:
    """Configuration for Contract Engine MCP integration (Build 2).

    When enabled, the pipeline uses the Contract Engine MCP server for runtime
    contract validation, test generation, and breaking change detection.
    """
    enabled: bool = False
    mcp_command: str = "python"
    mcp_args: list[str] = field(default_factory=lambda: ["-m", "src.contract_engine.mcp_server"])
    database_path: str = ""             # falls back to os.getenv('CONTRACT_ENGINE_DB', '')
    validation_on_build: bool = True
    test_generation: bool = True
    server_root: str = ""
    startup_timeout_ms: int = 30000     # 30 seconds
    tool_timeout_ms: int = 60000        # 60 seconds


@dataclass
class CodebaseIntelligenceConfig:
    """Configuration for Codebase Intelligence MCP integration (Build 2).

    When enabled, the pipeline uses the Codebase Intelligence MCP server for
    semantic search, dependency tracing, dead code detection, and incremental
    artifact registration.
    """
    enabled: bool = False
    mcp_command: str = "python"
    mcp_args: list[str] = field(default_factory=lambda: ["-m", "src.codebase_intelligence.mcp_server"])
    database_path: str = ""             # falls back to os.getenv('DATABASE_PATH', '')
    chroma_path: str = ""               # falls back to os.getenv('CHROMA_PATH', '')
    graph_path: str = ""                # falls back to os.getenv('GRAPH_PATH', '')
    replace_static_map: bool = True
    register_artifacts: bool = True
    server_root: str = ""
    startup_timeout_ms: int = 30000     # 30 seconds
    tool_timeout_ms: int = 60000        # 60 seconds


@dataclass
class SchemaValidationConfig:
    """Configuration for Prisma schema validation gate.

    When enabled, runs schema_validator.run_schema_validation() after
    Prisma schema generation in milestone execution. Critical findings
    can optionally block the milestone.
    """
    enabled: bool = True
    checks: list[str] = field(default_factory=lambda: [
        "SCHEMA-001", "SCHEMA-002", "SCHEMA-003", "SCHEMA-004",
        "SCHEMA-005", "SCHEMA-006", "SCHEMA-007", "SCHEMA-008",
    ])
    block_on_critical: bool = True  # Block milestone if critical findings


@dataclass
class QualityValidationConfig:
    """Configuration for quality validators gate.

    When enabled, runs quality_validators.run_quality_validators() after
    each milestone completion. Critical findings can optionally block
    the pipeline.
    """
    enabled: bool = True
    soft_delete_check: bool = True
    enum_registry_check: bool = True
    response_shape_check: bool = True
    auth_flow_check: bool = True
    build_health_check: bool = True
    block_on_critical: bool = True


@dataclass
class HooksConfig:
    """Configuration for self-learning hooks and pattern memory (Feature #4)."""
    enabled: bool = False  # Disabled by default; auto-enabled for enterprise/exhaustive
    pattern_memory: bool = True  # Store build patterns in SQLite
    capture_findings: bool = True  # Store audit findings for frequency analysis
    pre_build_retrieval: bool = True  # Inject past patterns into build context
    max_similar_builds: int = 3  # Max similar builds to retrieve
    max_top_findings: int = 5  # Max recurring findings to surface
    fix_recipes: bool = True  # Capture and inject fix recipes (requires hooks.enabled)


@dataclass
class GateEnforcementConfig:
    """Configuration for automated checkpoint gates (Feature #3)."""
    enabled: bool = False  # Disabled by default for backward compat; enable explicitly
    enforce_requirements: bool = True
    enforce_architecture: bool = True
    enforce_pseudocode: bool = False  # Feature #1 dependency — off until shipped
    enforce_review_count: bool = True
    enforce_convergence: bool = True
    enforce_truth_score: bool = False  # Feature #2 dependency — off until shipped
    enforce_e2e: bool = True
    min_review_cycles: int = 2
    truth_score_threshold: float = 0.95
    first_run_informational: bool = True  # Graceful degradation on first run


@dataclass
class AgentScalingConfig:
    """Controls agent deployment minimums per phase."""
    max_requirements_per_coder: int = 15
    max_requirements_per_reviewer: int = 25
    max_requirements_per_tester: int = 20
    enforce_minimum_counts: bool = True


@dataclass
class V18Config:
    """V18.1 feature flags - all default to legacy/disabled behavior."""

    # V18.1: vertical-slice is the only planner mode. Legacy retained as a
    # deprecated alias — any value other than "vertical_slice" logs a warning
    # but the vertical-slice planner is still used.
    planner_mode: str = "vertical_slice"
    execution_mode: str = "single_call"
    contract_mode: str = "markdown"
    # V18.2 decoupling: record_only by default. Evidence records accumulate
    # but do NOT affect scoring. Users can opt-in to soft_gate/hard_gate for
    # real evidence gating; "disabled" fully suppresses evidence creation.
    evidence_mode: str = "record_only"
    git_isolation: bool = False
    # V18.2 decoupling: probes are ON by default. When Docker is unavailable
    # the prober logs a warning and skips gracefully — it does NOT fail the
    # build. Set False to silence the warning on hosts without Docker.
    live_endpoint_check: bool = True
    openapi_generation: bool = False
    scaffold_enabled: bool = False
    max_parallel_milestones: int = 1
    wave_d5_enabled: bool = True
    # --- Phase G Slice 1a: setting_sources opt-in for CLAUDE.md auto-load ---
    claude_md_setting_sources_enabled: bool = False
    # --- Phase G Slice 1c: cumulative ARCHITECTURE.md writer ---
    architecture_md_enabled: bool = False
    architecture_md_max_lines: int = 500
    architecture_md_summarize_floor: int = 5
    # --- Phase H1b: auditor architecture injection + three-way compare ---
    # When True, INTERFACE and TECHNICAL auditors receive the per-milestone
    # ARCHITECTURE.md block and a three-way-compare directive that drives
    # ARCH-DRIFT-PORT/ENTITY/ENDPOINT/CREDS/DEPS findings. Default OFF keeps
    # the auditor prompts byte-identical to the pre-H1b path (the injection
    # is additionally gated on the ARCHITECTURE.md file existing on disk).
    auditor_architecture_injection_enabled: bool = False
    # --- Phase G Slice 1d: CLAUDE.md + AGENTS.md auto-generation ---
    claude_md_autogenerate: bool = False
    agents_md_autogenerate: bool = False
    agents_md_max_bytes: int = 32768
    wave_idle_timeout_seconds: int = 1800
    orphan_tool_idle_timeout_seconds: int = 600
    wave_watchdog_poll_seconds: int = 30
    wave_watchdog_max_retries: int = 1
    sub_agent_idle_timeout_seconds: int = 600
    # V18.2 Wave T (test-writing wave, inserted between D5 and E).
    # Claude-only (bypasses provider_map). Tests verify code is correct —
    # NEVER weaken tests to pass. Core principle is embedded verbatim in
    # the Wave T prompt. Max 2 fix iterations; remaining failures become
    # TEST-FAIL findings for the audit loop.
    wave_t_enabled: bool = True
    wave_t_max_fix_iterations: int = 2

    # --- Provider routing (v18.1 multi-provider wave execution) ---
    provider_routing: bool = False          # Opt-in only. NEVER auto-enabled by depth.
    codex_model: str = "gpt-5.4"            # OpenAI Codex model (migrated from gpt-5.1-codex-max)
    codex_timeout_seconds: int = 5400       # 90 min timeout per wave for heavier Wave B/D runs
    codex_max_retries: int = 1              # Retry once on failure
    codex_reasoning_effort: str = "high"    # model_reasoning_effort config key
    codex_transport_mode: str = "exec"      # "exec" (subprocess) or "app-server" (Bug #20 RPC)
    codex_orphan_tool_timeout_seconds: int = 300  # Orphan tool detection threshold (app-server)
    codex_web_search: str = "disabled"      # Web search OFF for reproducible builds
    codex_context7_enabled: bool = True     # Include Context7 MCP server
    provider_map_b: str = "codex"           # Wave B provider
    provider_map_d: str = "codex"           # Wave D provider
    # --- Phase G Slice 3c: Wave A.5 / T.5 provider fields ---
    # A.5 is Codex plan review (reasoning_effort=medium); T.5 is Codex
    # edge-case test audit (reasoning_effort=high). Slice 4 wires the
    # dispatch; these fields feed the shared WaveProviderMap at cli.py:3199.
    provider_map_a5: str = "codex"
    provider_map_t5: str = "codex"
    # --- Phase G Slice 3: merged Wave D (functional + polish in single pass) ---
    # When True, Wave D is dispatched to Claude with a combined functional +
    # polish prompt body, D5 is stripped from the sequence, and the compile-
    # fix gate uses wave_d_compile_fix_max_attempts (default 2) before the
    # D5 rollback site restores the pre-D checkpoint and flags the milestone
    # for legacy D+D5 retry. Default False keeps today's D -> D5 behavior
    # byte-identical.
    wave_d_merged_enabled: bool = False
    wave_d_compile_fix_max_attempts: int = 2

    # --- Phase G Slice 2a: audit-fix Codex routing (patch mode only per R7) ---
    # When True, the patch-mode audit-fix dispatch at cli.py:6441 consults
    # provider_router.classify_fix_provider(); backend/wiring findings route
    # to Codex, styling/UI findings stay on Claude. Flag default False keeps
    # current all-Claude behavior. Requires v18.provider_routing=True.
    codex_fix_routing_enabled: bool = False
    codex_fix_timeout_seconds: int = 900    # 15 min cap per Codex fix invocation
    codex_fix_reasoning_effort: str = "high"  # Codex reasoning effort for fix dispatches
    # --- Phase G Slice 2b: compile-fix Codex routing (R1) ---
    # When True, compile-fix invocations from _run_wave_compile and
    # _run_wave_b_dto_contract_guard route to Codex reasoning_effort=high
    # when provider_routing is active. Default False preserves Claude path.
    compile_fix_codex_enabled: bool = False

    # --- Phase G Slice 4a: Wave A.5 plan review (Codex NEW) ---
    # Catches entity/endpoint/state-machine gaps in Wave A's plan BEFORE
    # Wave B writes backend code. Flag-gated OFF by default. When ON, the
    # dispatcher runs Codex `medium` between Wave A and Wave Scaffold/B and
    # persists findings to .agent-team/milestones/{id}/WAVE_A5_REVIEW.json.
    # Skip conditions: simple milestones (see thresholds below). GATE 8
    # enforcement is opt-in separately.
    wave_a5_enabled: bool = False
    wave_a5_reasoning_effort: str = "medium"
    wave_a5_max_reruns: int = 1
    wave_a5_skip_simple_milestones: bool = True
    wave_a5_simple_entity_threshold: int = 3
    wave_a5_simple_ac_threshold: int = 5
    wave_a5_gate_enforcement: bool = False
    # --- Phase H1b: Wave A ARCHITECTURE.md schema gate ---
    # Validator reads .agent-team/milestone-{id}/ARCHITECTURE.md after
    # Wave A completes and emits findings against the allowlist / disallow-
    # list in wave_a_schema. Retry budget is SHARED with A.5 via
    # wave_a_rerun_budget (new canonical key); legacy wave_a5_max_reruns
    # stays as a deprecated alias — see cli._get_effective_wave_a_rerun_budget.
    wave_a_schema_enforcement_enabled: bool = False
    wave_a_rerun_budget: int = 2
    # --- Phase H3e local wave redispatch recovery ---
    # When True, eligible structured findings can rewind the milestone to an
    # earlier wave inside wave_executor instead of waiting for later recovery
    # paths. Default FALSE preserves byte-identical behavior. The attempt cap
    # is persisted in STATE.json via RunState.wave_redispatch_attempts.
    recovery_wave_redispatch_enabled: bool = False
    recovery_wave_redispatch_max_attempts: int = 2
    # --- Phase H3e Wave A explicit contract guidance + verifier ---
    # When True, build_wave_a_prompt injects a concrete-values block derived
    # from STACK_CONTRACT for infra literals such as ports. Default FALSE keeps
    # the pre-H3e prompt body byte-identical.
    wave_a_contract_injection_enabled: bool = False
    # When True, wave_executor runs the deterministic Wave A contract verifier
    # before scaffold and also lets scaffold bootstrap config inherit explicit
    # contract literals when spec reconciliation is otherwise off. Default
    # FALSE preserves the pre-H3e execution path.
    wave_a_contract_verifier_enabled: bool = False
    # --- Phase H3f Wave A ownership hardening ---
    # When True, Wave A ownership findings become a real pre-scaffold gate:
    # wave_executor fails Wave A on scaffold-owned writes and lets the H3e
    # redispatch planner recover back to Wave A. Default FALSE preserves the
    # pre-H3f detection-only behavior.
    wave_a_ownership_enforcement_enabled: bool = False
    # When True, build_wave_a_prompt injects a scaffold-owned path contract
    # sourced from SCAFFOLD_OWNERSHIP.md. Default FALSE preserves the pre-H3f
    # prompt body.
    wave_a_ownership_contract_injection_enabled: bool = False
    # --- Phase G Slice 4b: Wave T.5 test-gap audit (Codex NEW) ---
    # Runs between Wave T and Wave E to identify missing edge cases, weak
    # assertions, and untested business rules. T.5 does NOT write tests —
    # it emits a gap list persisted to
    # .agent-team/milestones/{id}/WAVE_T5_GAPS.json. Skipped when Wave T
    # produced no test files. GATE 9 enforcement is opt-in separately.
    wave_t5_enabled: bool = False
    wave_t5_reasoning_effort: str = "high"
    wave_t5_skip_if_no_tests: bool = True
    wave_t5_gate_enforcement: bool = False
    # --- Phase G Slice 5 (R10): prompt integration wiring ---
    # 5a: When True, build_wave_a_prompt injects pre-fetched Prisma/TypeORM
    # idioms into a `<framework_idioms>` block (cli._n17_prefetch_cache is
    # widened to A when this is on).
    # 5b: When True, build_wave_t_prompt injects pre-fetched Jest/Vitest/
    # Playwright idioms into a `<framework_idioms>` block (cache widened to T).
    # 5d: When True, build_wave_e_prompt injects the Wave T.5 gap list as a
    # `<wave_t5_gaps>` block with an R5 Playwright rule (reads
    # .agent-team/milestones/{id}/WAVE_T5_GAPS.json).
    # 5e: When True, get_scoped_auditor_prompt appends a T.5 gap-consumption
    # rule to TEST_AUDITOR_PROMPT (adversarial context for the test auditor).
    # All four flags default OFF; flag-off path is byte-identical to the
    # pre-Slice-5 prompt bodies.
    mcp_doc_context_wave_a_enabled: bool = False
    mcp_doc_context_wave_t_enabled: bool = False
    wave_t5_gap_list_inject_wave_e: bool = False
    wave_t5_gap_list_inject_test_auditor: bool = False

    # --- UI Design Token Pipeline (two-tier design guidance) ---
    ui_design_tokens_enabled: bool = True   # Generate UI_DESIGN_TOKENS.json for Wave D / D.5
    ui_reference_path: str = ""             # Path to user-provided HTML reference (Tier 1)

    # --- A-09 milestone scope enforcement (wave prompt + post-wave validator) ---
    milestone_scope_enforcement: bool = True
    # --- C-01 audit milestone scoping (audit prompt + scope_violation finding) ---
    audit_milestone_scoping: bool = True
    # --- N-02 ownership contract consumption (Phase B). When True, the wave-B
    #     and wave-D prompts inject a [FILES YOU OWN] claim list parsed from
    #     docs/SCAFFOLD_OWNERSHIP.md, the auditor prompt suppresses spurious
    #     missing-file findings for entries marked optional, and
    #     scaffold_runner.run_scaffolding validates its emitted set against
    #     the scaffold-owned rows of the contract. Default FALSE; ON opts
    #     into Phase B ownership contract enforcement.
    ownership_contract_enabled: bool = False
    # --- H2bc ownership policy fail-loud mode. When True, ownership-policy
    #     consumers raise if SCAFFOLD_OWNERSHIP.md cannot be resolved from the
    #     workspace or repo. Default FALSE preserves warn-and-skip behavior.
    ownership_policy_required: bool = False
    # --- H3a Codex dispatch observability. When True, provider-routed app-
    #     server Codex waves emit prompt/protocol/response captures under
    #     .agent-team/codex-captures/. Default FALSE preserves byte-identical
    #     dispatch behavior.
    codex_capture_enabled: bool = False
    # --- H3c Wave B prompt hardening. When True, Wave B promotes
    #     requirements-declared deliverables and adds a Codex write-contract
    #     block for infrastructure milestones. Default FALSE preserves the
    #     pre-H3c prompt body.
    codex_wave_b_prompt_hardening_enabled: bool = False
    # --- H3d Codex writable sandbox override. When True, the app-server
    #     transport sends an explicit thread/start sandbox mode instead of
    #     relying on layered config defaults. Default FALSE preserves H3c
    #     behavior.
    codex_sandbox_writable_enabled: bool = False
    codex_sandbox_mode: str = "workspace-write"
    # --- H3h Codex turn interrupt prompt refinement. When True, the
    #     corrective turn prompt names the wedged shell tool and gives a
    #     more specific alternative-action hint. Default FALSE preserves the
    #     legacy prompt text byte-for-byte.
    codex_turn_interrupt_message_refined_enabled: bool = False
    # --- H3h Codex app-server teardown. When True, the transport performs a
    #     best-effort post-close process-tree teardown after a clean shell
    #     exit so descendant codex.exe processes do not linger. Default FALSE
    #     preserves the legacy close path.
    codex_app_server_teardown_enabled: bool = False
    # --- H3h write-path finalize invariant enforcement. When True, the CLI
    #     runs RunState.finalize() before selected STATE.json writes so the
    #     summary invariant is reconciled proactively. Default FALSE keeps the
    #     legacy write ordering and fallback behavior.
    state_finalize_invariant_enforcement_enabled: bool = False
    # --- H3c Codex cwd verification. When True, the app-server transport
    #     resolves/validates cwd and warns when the server-reported cwd
    #     diverges from the orchestrator path. Default FALSE preserves legacy
    #     dispatch behavior.
    codex_cwd_propagation_check_enabled: bool = False
    # --- H3c Codex flush debounce. When True, provider_router waits a short
    #     configurable period after a successful Codex return before taking
    #     the post-dispatch checkpoint. Default FALSE preserves legacy timing.
    codex_flush_wait_enabled: bool = False
    codex_flush_wait_seconds: float = 0.5
    # --- H3c checkpoint tracker hardening. Declared so validation configs can
    #     flip it on; behavioral hardening remains a no-op unless the H3c
    #     tracker audit proves a concrete bug. Default FALSE.
    checkpoint_tracker_hardening_enabled: bool = False
    # --- H3d BLOCKED-prefix downgrade. When True, provider routing treats a
    #     final Codex message beginning with BLOCKED: as a failure even when
    #     transport metadata reports success=True. Default FALSE preserves
    #     legacy fallback timing and diagnostics.
    codex_blocked_prefix_as_failure_enabled: bool = False
    # --- H3h scaffold web Docker context fix. When True, the scaffold
    #     composer emits a repo-root build context for apps/web so the web
    #     Dockerfile can see workspace-root files. Default FALSE preserves the
    #     legacy scaffold output byte-for-byte.
    scaffold_web_dockerfile_context_fix_enabled: bool = False
    # --- N-12 SPEC reconciliation (Phase B). When True, the pipeline runs
    #     ``milestone_spec_reconciler.reconcile_milestone_spec`` just before
    #     Wave A pre-wave scaffolding: merges REQUIREMENTS.md + PRD + stack
    #     contract + ownership contract into a resolved SPEC.md /
    #     resolved_manifest.json, and threads the derived ScaffoldConfig into
    #     scaffold_runner.run_scaffolding. Default FALSE (Phase-A behavior).
    spec_reconciliation_enabled: bool = False
    # --- N-13 scaffold verifier (Phase B). When True, the wave executor runs
    #     ``scaffold_verifier.run_scaffold_verifier`` immediately after Wave A
    #     completes; verdict == "FAIL" halts the pipeline before Wave B runs.
    #     Default FALSE (Phase-A behavior).
    scaffold_verifier_enabled: bool = False
    # --- D-20 M1 startup-AC probe (runs npm install / docker compose /
    #     prisma migrate / jest / vitest for infrastructure milestones at
    #     audit time; mocked in unit tests, real at pipeline runtime).
    m1_startup_probe: bool = True
    # --- D-04 review-fleet enforcement (fail-fast invariant at end of
    #     orchestration). When True (default), the pipeline raises
    #     ReviewFleetNotDeployedError if the final convergence report still
    #     shows 0 review cycles with >0 requirements AFTER the GATE 5
    #     recovery path has had a chance to run. When False, the existing
    #     warning-only behaviour is preserved.
    review_fleet_enforcement: bool = True
    # --- Phase G Slice 1e (R2): D-05 recovery prompt isolation is now
    #     STRUCTURAL — the legacy `[SYSTEM:]` pseudo-tag shape was deleted
    #     from cli.py per user memory "Prefer structural fixes over
    #     containment". Recovery ALWAYS uses system_addendum + user body.
    #     The recovery_prompt_isolation flag is retired.
    # --- N-11 cascade suppression (Phase B). When True, the audit-report
    #     post-processor clusters findings that share a scaffold-verifier
    #     root cause (missing/malformed path) and collapses them into a
    #     single representative finding with ``cascade_count`` /
    #     ``cascaded_from`` metadata. Default FALSE preserves the legacy
    #     one-finding-per-downstream-symptom behavior. Requires the
    #     scaffold verifier to have run (``scaffold_verifier_enabled=True``)
    #     and written ``.agent-team/scaffold_verifier_report.json``.
    cascade_consolidation_enabled: bool = False
    # --- NEW-1 duplicate Prisma cleanup (Phase B). When True, a post-Wave-B
    #     hook removes stale ``apps/api/src/prisma/`` emissions when the
    #     canonical ``apps/api/src/database/`` is populated (N-04 path
    #     relocation). Safety: never removes without first confirming
    #     prisma.module.ts + prisma.service.ts exist under src/database/.
    #     Default FALSE preserves existing artifact state.
    duplicate_prisma_cleanup_enabled: bool = False
    # --- NEW-2 template version stamping (Phase B). When True, scaffold
    #     emissions receive a version header comment (``# scaffold-template-
    #     version: <SCAFFOLD_TEMPLATE_VERSION>`` or ``// ...``). Skipped
    #     for .json (strict JSON has no comments) and .md (human-readable).
    #     Default FALSE emits byte-identical output to pre-NEW-2 runs.
    template_version_stamping_enabled: bool = False
    # --- N-10 forbidden-content scanner (Phase C). When True, the audit
    #     loop runs a regex-based deterministic scanner after the LLM
    #     scorer writes AUDIT_REPORT.json and merges its findings into the
    #     report (auditor="forbidden_content", source="deterministic").
    #     Catches surface-level lexical anti-patterns the LLM auditors miss
    #     (stub throws, TODO/FIXME comments, placeholder secrets,
    #     untranslated RTL strings, empty function bodies). Default FALSE
    #     preserves byte-identical AUDIT_REPORT.json output to pre-N-10 runs.
    content_scope_scanner_enabled: bool = False
    # --- N-08 audit-fix-loop observability (Phase C). When True, the
    #     `_run_audit_loop` initializes FIX_CYCLE_LOG.md at entry and appends
    #     a fix-cycle entry after each `_run_audit_fix_unified` call so that
    #     audit-fix iterations are observable alongside recovery-path fix
    #     cycles. Gated by `tracking_documents.fix_cycle_log` — both must be
    #     True for the log to populate. Default FALSE preserves byte-identical
    #     pre-N-08 behavior (no extra file I/O in the audit loop).
    audit_fix_iteration_enabled: bool = False
    # --- N-17 MCP-informed dispatches (Phase C). When True, the orchestrator
    #     pre-fetches framework idiom docs from Context7 MCP BEFORE building
    #     Wave B/D prompts and injects them as a [CURRENT FRAMEWORK IDIOMS]
    #     section so sub-agents receive verbatim canonical patterns. Cached
    #     per-milestone at .agent-team/framework_idioms_cache.json. When
    #     False, prompts are structurally identical to pre-N-17. This is the
    #     ONLY Phase C flag that defaults ON.
    mcp_informed_dispatches_enabled: bool = True
    # --- Phase F §7.5 broader runtime infrastructure detection. When True,
    #     ``infra_detector.detect_runtime_infra`` auto-detects the NestJS
    #     API prefix (main.ts setGlobalPrefix), CORS_ORIGIN, DATABASE_URL,
    #     and JWT audience at probe-assembly time so downstream callers
    #     do not hard-code these values. Phase A's port detection in
    #     ``endpoint_prober`` stays in effect regardless. Default True —
    #     the detector is read-only (no network / process side effects)
    #     and strictly additive for callers that opt in via
    #     ``build_probe_url(...)`` / ``detect_runtime_infra(...)``.
    runtime_infra_detection_enabled: bool = True
    # --- Phase F §7.10 user-facing confidence banners. When True, the
    #     AUDIT_REPORT.json, BUILD_LOG.txt, GATE_*_REPORT.md, and
    #     *_RECOVERY_REPORT.md emissions carry an explicit
    #     ``confidence: CONFIDENT|MEDIUM|LOW`` field with reasoning.
    #     Phase C's D-14 fidelity labels on the four verification
    #     artefacts remain; this extends the concept so operators see
    #     consistent trust signals on every user-facing artefact. Default
    #     True — purely additive metadata.
    confidence_banners_enabled: bool = True
    # --- Phase F auditor scope completeness scanner. When True, the
    #     audit pipeline runs ``audit_scope_scanner`` before the LLM
    #     scorer and emits an ``AUDIT-SCOPE-GAP`` meta-finding for every
    #     Day-1 requirement that has no auditor / scanner coverage.
    #     Prevents silent passes when a requirement is out of the
    #     auditor's scope. Default True.
    audit_scope_completeness_enabled: bool = True
    # --- Phase F N-19 Wave B output sanitization. When True, a post-
    #     Wave-B hook compares emitted files against the scaffold
    #     ownership contract (N-02 ``docs/SCAFFOLD_OWNERSHIP.md``) and
    #     flags any file Wave B created in a scaffold-owned location as
    #     an orphan. A deterministic grep-based consumer check runs
    #     before any cleanup, and every action is logged. Default True.
    wave_b_output_sanitization_enabled: bool = True

    # N-13 follow-up: restrict scaffold-verifier enforcement to files
    # within the current milestone's `allowed_file_globs`. Prevents the
    # verifier from failing M1 on modules owned by later milestones
    # (e.g. M2 users, M3 projects, etc.) under vertical_slice planning.
    # Default True — the unscoped behaviour is never correct once
    # milestone_scope_enforcement is on.
    scaffold_verifier_scope_aware: bool = True

    # --- Phase H1a: probe spec-oracle guard (PROBE-SPEC-DRIFT-001) ---
    # When True, endpoint_prober._detect_app_url consults
    # REQUIREMENTS.md's DoD port and fails fast on drift vs the resolved
    # code-side port (main.ts / .env / docker-compose). Default OFF to
    # preserve legacy silent-first-source-wins behaviour.
    probe_spec_oracle_enabled: bool = False

    # --- Phase H1a: runtime-verifier tautology guard (RUNTIME-TAUTOLOGY-001) ---
    # When True, the runtime-verification summary emitter cross-checks
    # the compose graph's critical-path (api + transitive depends_on)
    # and flags any missing/unhealthy critical service instead of
    # silently reporting "0/0 healthy" as green. Default OFF preserves
    # the previous reporting layer.
    runtime_tautology_guard_enabled: bool = False
    # --- Phase H3g: bounded refresh-before-verdict for runtime verification.
    #     When True, the runtime verifier polls container health a few more
    #     times before the final verdict so the tautology guard does not read
    #     stale pre-fix state. Default OFF preserves single-read behavior.
    runtime_verifier_refresh_enabled: bool = False
    runtime_verifier_refresh_attempts: int = 5
    runtime_verifier_refresh_interval_seconds: float = 3.0
    # --- Phase H3g: when a milestone fails the health gate, optionally run the
    #     per-milestone audit-fix-reaudit loop before the failed-milestone
    #     short-circuit. Default OFF preserves the legacy skip.
    reaudit_trigger_fix_enabled: bool = False

    # --- Phase H1a Item 3: DoD feasibility verifier. When True, a
    #     wave_executor milestone-teardown hook runs
    #     ``dod_feasibility_verifier.run_dod_feasibility_check`` and emits
    #     ``DOD-FEASIBILITY-001`` HIGH findings for each ``pnpm``/``npm``/
    #     ``yarn`` script referenced in ``## Definition of Done`` that is
    #     not defined in any root/apps/api/apps/web ``package.json``. Fires
    #     on ALL milestones including ones that failed at Wave B (the hook
    #     sits between persist_wave_findings_for_audit and
    #     architecture_writer.append_milestone, both of which run
    #     post-loop). Default FALSE preserves pre-H1a behavior.
    dod_feasibility_verifier_enabled: bool = False

    # --- Phase H1a Item 4: ownership enforcement. When True, three
    #     wave_executor hooks run the checks in ``ownership_enforcer``:
    #     (A) template-content fingerprinting at scaffold completion,
    #     (C) Wave A forbidden-writes at Wave A completion,
    #     and a post-wave re-check after every non-A wave. Scope for h1a
    #     is compose + 3 .env.example files; expanding to the full 44
    #     scaffold-owned files is a config change in
    #     ``ownership_enforcer.H1A_ENFORCED_PATHS``. Default FALSE
    #     preserves pre-H1a behavior.
    ownership_enforcement_enabled: bool = False


@dataclass
class RoutingConfig:
    """Configuration for 3-Tier Model Routing (Feature #5).

    Controls task-aware routing that assigns tasks to cheaper models
    when the task complexity is low, and reserves the most capable
    model for high-complexity work.

    Tiers:
      - Tier 1: Deterministic transforms (no LLM call)
      - Tier 2: Medium complexity (haiku/sonnet)
      - Tier 3: High complexity (opus)
    """
    enabled: bool = False  # Disabled by default for backward compat; enable explicitly
    tier1_confidence_threshold: float = 0.8
    tier2_complexity_threshold: float = 0.3
    tier3_complexity_threshold: float = 0.6
    default_model: str = "sonnet"
    log_decisions: bool = True


@dataclass
class IntegrationGateConfig:
    """Configuration for the frontend-backend integration verification gate.

    Controls API contract extraction from implemented code, enriched milestone
    handoffs with endpoint data, and post-milestone integration verification.
    All features default to enabled but non-blocking (warn mode).
    """
    enabled: bool = True
    # API Contract Extraction: parse actual backend code for endpoint/field data
    contract_extraction: bool = True
    # Integration Verification: diff frontend API calls vs backend endpoints
    verification_enabled: bool = True
    # Mode: "warn" (log mismatches, continue) or "block" (fail milestone on mismatch)
    # Default changed to "block" — root cause analysis shows warn-only mode allowed
    # 18 route mismatches (29% of all bugs) to ship undetected.
    verification_mode: str = "block"
    # Enriched Handoff: include endpoint paths/fields in milestone handoff summaries
    enriched_handoff: bool = True
    # Cross-milestone source access: inject backend file paths for frontend agents to read
    cross_milestone_source_access: bool = True
    # Serialization convention mandate: add instructions about camelCase/snake_case handling
    serialization_mandate: bool = True
    # Max chars for API contract injection into prompts
    contract_injection_max_chars: int = 15000
    # Max chars for integration report injection into prompts
    report_injection_max_chars: int = 10000
    # File patterns for backend source files to expose to frontend agents
    backend_source_patterns: list[str] = field(default_factory=lambda: [
        "*.controller.ts", "*.dto.ts", "schema.prisma",
        "*.routes.ts", "*.router.ts",
    ])
    # Directories to skip when scanning
    skip_directories: list[str] = field(default_factory=lambda: [
        "node_modules", ".next", "dist", "build", "__pycache__", ".venv",
    ])
    # Blocking mode: when True, HIGH+ mismatches fail the milestone (upgraded gate)
    blocking_mode: bool = False
    # New granular checks for upgraded integration verifier
    route_structure_check: bool = True
    response_shape_check: bool = True
    auth_flow_check: bool = True
    enum_cross_check: bool = True
    route_pattern_enforcement: bool = True  # Enable nested-vs-top-level route detection


@dataclass
class AgentTeamConfig:
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    depth: DepthConfig = field(default_factory=DepthConfig)
    convergence: ConvergenceConfig = field(default_factory=ConvergenceConfig)
    interview: InterviewConfig = field(default_factory=InterviewConfig)
    design_reference: DesignReferenceConfig = field(default_factory=DesignReferenceConfig)
    codebase_map: CodebaseMapConfig = field(default_factory=CodebaseMapConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    pseudocode: PseudocodeConfig = field(default_factory=PseudocodeConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    investigation: InvestigationConfig = field(default_factory=InvestigationConfig)
    orchestrator_st: OrchestratorSTConfig = field(default_factory=OrchestratorSTConfig)
    milestone: MilestoneConfig = field(default_factory=MilestoneConfig)
    prd_chunking: PRDChunkingConfig = field(default_factory=PRDChunkingConfig)
    e2e_testing: E2ETestingConfig = field(default_factory=E2ETestingConfig)
    browser_testing: BrowserTestingConfig = field(default_factory=BrowserTestingConfig)
    integrity_scans: IntegrityScanConfig = field(default_factory=IntegrityScanConfig)
    runtime_verification: RuntimeVerificationConfig = field(default_factory=RuntimeVerificationConfig)
    tracking_documents: TrackingDocumentsConfig = field(default_factory=TrackingDocumentsConfig)
    database_scans: DatabaseScanConfig = field(default_factory=DatabaseScanConfig)
    post_orchestration_scans: PostOrchestrationScanConfig = field(default_factory=PostOrchestrationScanConfig)
    tech_research: TechResearchConfig = field(default_factory=TechResearchConfig)
    integration_gate: IntegrationGateConfig = field(default_factory=IntegrationGateConfig)
    schema_validation: SchemaValidationConfig = field(default_factory=SchemaValidationConfig)
    quality_validation: QualityValidationConfig = field(default_factory=QualityValidationConfig)
    # Agent keys use underscores (Python convention) in config files.
    # The SDK uses hyphens (e.g., "code-writer"). See agents.py for the mapping.
    agents: dict[str, AgentConfig] = field(default_factory=lambda: {
        name: AgentConfig()
        for name in (
            "planner", "researcher", "architect", "task_assigner",
            "pseudocode_writer",
            "code_writer", "code_reviewer", "test_runner",
            "security_auditor", "debugger",
            "integration_agent", "contract_generator",
        )
    })
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=lambda: {
        "firecrawl": MCPServerConfig(),
        "context7": MCPServerConfig(),
        "sequential_thinking": MCPServerConfig(),
    })
    display: DisplayConfig = field(default_factory=DisplayConfig)
    audit_team: AuditTeamConfig = field(default_factory=AuditTeamConfig)
    agent_teams: AgentTeamsConfig = field(default_factory=AgentTeamsConfig)
    phase_leads: PhaseLeadsConfig = field(default_factory=PhaseLeadsConfig)
    observer: ObserverConfig = field(default_factory=ObserverConfig)
    contract_engine: ContractEngineConfig = field(default_factory=ContractEngineConfig)
    codebase_intelligence: CodebaseIntelligenceConfig = field(default_factory=CodebaseIntelligenceConfig)
    contract_scans: ContractScanConfig = field(default_factory=ContractScanConfig)
    enterprise_mode: EnterpriseModeConfig = field(default_factory=EnterpriseModeConfig)
    departments: DepartmentsConfig = field(default_factory=DepartmentsConfig)
    gate_enforcement: GateEnforcementConfig = field(default_factory=GateEnforcementConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    agent_scaling: AgentScalingConfig = field(default_factory=AgentScalingConfig)
    v18: V18Config = field(default_factory=V18Config)


# ---------------------------------------------------------------------------
# Depth detection
# ---------------------------------------------------------------------------

DEPTH_AGENT_COUNTS: dict[str, dict[str, tuple[int, int]]] = {
    "quick": {
        "planning": (1, 2), "research": (0, 1), "architecture": (0, 1),
        "pseudocode": (0, 1),
        "coding": (1, 1), "review": (1, 2), "testing": (1, 1),
    },
    "standard": {
        "planning": (3, 5), "research": (2, 3), "architecture": (1, 2),
        "pseudocode": (1, 2),
        "coding": (2, 3), "review": (2, 3), "testing": (1, 2),
    },
    "thorough": {
        "planning": (5, 8), "research": (3, 5), "architecture": (2, 3),
        "pseudocode": (2, 3),
        "coding": (3, 6), "review": (3, 5), "testing": (2, 3),
    },
    "exhaustive": {
        "planning": (8, 10), "research": (5, 8), "architecture": (3, 4),
        "pseudocode": (3, 4),
        "coding": (5, 10), "review": (5, 8), "testing": (3, 5),
    },
    "enterprise": {
        "planning": (8, 12), "research": (5, 8), "architecture": (3, 5),
        "pseudocode": (3, 4),
        "coding": (8, 15), "review": (5, 10), "testing": (3, 5),
    },
}


def detect_depth(task: str, config: AgentTeamConfig) -> DepthDetection:
    """Detect depth level from task keywords. Returns a DepthDetection with metadata.

    Uses word-boundary matching to avoid substring false positives.
    The returned DepthDetection supports str() conversion and == comparison
    with strings for backwards compatibility.
    """
    if not config.depth.auto_detect:
        return DepthDetection(config.depth.default, "default", [], "Auto-detect disabled")
    task_lower = task.lower()
    for level in ("exhaustive", "thorough", "quick"):
        keywords = config.depth.keyword_map.get(level, [])
        matched = [kw for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", task_lower)]
        if matched:
            return DepthDetection(level, "keyword", matched, f"Matched keywords: {matched}")
    return DepthDetection(config.depth.default, "default", [], "No keyword matches")


def apply_depth_quality_gating(
    depth: str,
    config: AgentTeamConfig,
    user_overrides: set[str] | None = None,
    prd_mode: bool = False,
) -> None:
    """Apply depth-based gating to quality and scan config fields.

    The *user_overrides* set (from :func:`load_config`) lists dotted key
    paths that the user explicitly set in their config file.  When a key
    is in *user_overrides* it is **never** changed by depth gating,
    respecting the user's intentional choice.

    Depth effects:
    - **quick**: disables all scans, 0 review retries, disables quality
    - **standard**: disables PRD reconciliation, keeps scans on
    - **thorough**: auto-enables E2E testing, 2 review retries
    - **exhaustive**: auto-enables E2E testing, 3 review retries
    """
    overrides = user_overrides or set()

    def _gate(key: str, value: object, target: object, attr: str) -> None:
        """Set *target.attr* to *value* unless *key* is user-overridden."""
        if key not in overrides:
            setattr(target, attr, value)

    if depth == "quick":
        # Audit-team: disabled at quick depth
        _gate("audit_team.enabled", False, config.audit_team, "enabled")
        # Tech research
        _gate("tech_research.enabled", False, config.tech_research, "enabled")
        # Quality
        _gate("quality.production_defaults", False, config.quality, "production_defaults")
        _gate("quality.craft_review", False, config.quality, "craft_review")
        # Post-orchestration scans
        _gate("post_orchestration_scans.mock_data_scan", False, config.post_orchestration_scans, "mock_data_scan")
        _gate("post_orchestration_scans.ui_compliance_scan", False, config.post_orchestration_scans, "ui_compliance_scan")
        _gate("post_orchestration_scans.api_contract_scan", False, config.post_orchestration_scans, "api_contract_scan")
        _gate("post_orchestration_scans.silent_data_loss_scan", False, config.post_orchestration_scans, "silent_data_loss_scan")
        _gate("post_orchestration_scans.endpoint_xref_scan", False, config.post_orchestration_scans, "endpoint_xref_scan")
        _gate("post_orchestration_scans.handler_completeness_scan", False, config.post_orchestration_scans, "handler_completeness_scan")
        _gate("post_orchestration_scans.enum_registry_scan", False, config.post_orchestration_scans, "enum_registry_scan")
        _gate("post_orchestration_scans.response_shape_scan", False, config.post_orchestration_scans, "response_shape_scan")
        _gate("post_orchestration_scans.soft_delete_scan", False, config.post_orchestration_scans, "soft_delete_scan")
        _gate("post_orchestration_scans.auth_flow_scan", False, config.post_orchestration_scans, "auth_flow_scan")
        _gate("post_orchestration_scans.infrastructure_scan", False, config.post_orchestration_scans, "infrastructure_scan")
        _gate("post_orchestration_scans.schema_validation_scan", False, config.post_orchestration_scans, "schema_validation_scan")
        # Runtime verification: disabled at quick depth
        _gate("runtime_verification.enabled", False, config.runtime_verification, "enabled")
        # Contract compliance scans
        _gate("contract_scans.endpoint_schema_scan", False, config.contract_scans, "endpoint_schema_scan")
        _gate("contract_scans.missing_endpoint_scan", False, config.contract_scans, "missing_endpoint_scan")
        _gate("contract_scans.event_schema_scan", False, config.contract_scans, "event_schema_scan")
        _gate("contract_scans.shared_model_scan", False, config.contract_scans, "shared_model_scan")
        # Milestone scans (legacy fields)
        _gate("milestone.mock_data_scan", False, config.milestone, "mock_data_scan")
        _gate("milestone.ui_compliance_scan", False, config.milestone, "ui_compliance_scan")
        _gate("milestone.review_recovery_retries", 0, config.milestone, "review_recovery_retries")
        # Integrity scans
        _gate("integrity_scans.deployment_scan", False, config.integrity_scans, "deployment_scan")
        _gate("integrity_scans.asset_scan", False, config.integrity_scans, "asset_scan")
        _gate("integrity_scans.prd_reconciliation", False, config.integrity_scans, "prd_reconciliation")
        # Database scans
        _gate("database_scans.dual_orm_scan", False, config.database_scans, "dual_orm_scan")
        _gate("database_scans.default_value_scan", False, config.database_scans, "default_value_scan")
        _gate("database_scans.relationship_scan", False, config.database_scans, "relationship_scan")
        # E2E testing
        _gate("e2e_testing.enabled", False, config.e2e_testing, "enabled")
        _gate("e2e_testing.max_fix_retries", 1, config.e2e_testing, "max_fix_retries")
        # Browser testing
        _gate("browser_testing.enabled", False, config.browser_testing, "enabled")
        # Multi-pass fix cycles
        _gate("post_orchestration_scans.max_scan_fix_passes", 0, config.post_orchestration_scans, "max_scan_fix_passes")
        # Build 2: quick disables contract/codebase subsystems but keeps agent teams + phase leads
        _gate("contract_engine.enabled", False, config.contract_engine, "enabled")
        _gate("codebase_intelligence.enabled", False, config.codebase_intelligence, "enabled")
        # Agent teams + phase leads are universal — enabled at ALL depths
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        # Schema and quality validation: disabled at quick depth
        _gate("schema_validation.enabled", False, config.schema_validation, "enabled")
        _gate("quality_validation.enabled", False, config.quality_validation, "enabled")

    elif depth == "standard":
        # Standard: tech research enabled with reduced queries
        _gate("tech_research.max_queries_per_tech", 2, config.tech_research, "max_queries_per_tech")
        # Standard disables PRD reconciliation (expensive LLM call)
        _gate("integrity_scans.prd_reconciliation", False, config.integrity_scans, "prd_reconciliation")
        # Standard: only CONTRACT-001 and CONTRACT-002 enabled
        _gate("contract_scans.event_schema_scan", False, config.contract_scans, "event_schema_scan")
        _gate("contract_scans.shared_model_scan", False, config.contract_scans, "shared_model_scan")
        # Build 2: standard enables contract_engine (validation only) and codebase_intelligence (queries only)
        _gate("contract_engine.enabled", True, config.contract_engine, "enabled")
        _gate("contract_engine.validation_on_build", True, config.contract_engine, "validation_on_build")
        _gate("contract_engine.test_generation", False, config.contract_engine, "test_generation")
        _gate("codebase_intelligence.enabled", True, config.codebase_intelligence, "enabled")
        _gate("codebase_intelligence.replace_static_map", False, config.codebase_intelligence, "replace_static_map")
        _gate("codebase_intelligence.register_artifacts", False, config.codebase_intelligence, "register_artifacts")
        # Standard enables phase lead SDK subagents and Agent Teams backend
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("milestone.enabled", True, config.milestone, "enabled")

    elif depth == "thorough":
        # Audit-team: auto-enabled at thorough depth, max 2 re-audit cycles
        _gate("audit_team.enabled", True, config.audit_team, "enabled")
        _gate("audit_team.max_reaudit_cycles", 2, config.audit_team, "max_reaudit_cycles")
        # Thorough auto-enables E2E and bumps retries
        _gate("e2e_testing.enabled", True, config.e2e_testing, "enabled")
        _gate("e2e_testing.max_fix_retries", 2, config.e2e_testing, "max_fix_retries")
        _gate("milestone.review_recovery_retries", 2, config.milestone, "review_recovery_retries")
        # Browser testing — auto-enable only for PRD/PRD+ builds
        if prd_mode or config.milestone.enabled:
            _gate("browser_testing.enabled", True, config.browser_testing, "enabled")
            _gate("browser_testing.max_fix_retries", 3, config.browser_testing, "max_fix_retries")
        # Runtime verification — auto-enable for PRD builds at thorough depth
        if prd_mode or config.milestone.enabled:
            _gate("runtime_verification.enabled", True, config.runtime_verification, "enabled")
        # Build 2: thorough enables full contract_engine, codebase_intelligence, and agent_teams
        _gate("contract_engine.enabled", True, config.contract_engine, "enabled")
        _gate("contract_engine.test_generation", True, config.contract_engine, "test_generation")
        _gate("codebase_intelligence.enabled", True, config.codebase_intelligence, "enabled")
        _gate("codebase_intelligence.replace_static_map", True, config.codebase_intelligence, "replace_static_map")
        _gate("codebase_intelligence.register_artifacts", True, config.codebase_intelligence, "register_artifacts")
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        _gate("v18.planner_mode", "vertical_slice", config.v18, "planner_mode")

    elif depth == "exhaustive":
        # Audit-team: auto-enabled at exhaustive depth, max 3 re-audit cycles
        _gate("audit_team.enabled", True, config.audit_team, "enabled")
        _gate("audit_team.max_reaudit_cycles", 3, config.audit_team, "max_reaudit_cycles")
        # Exhaustive: max tech research queries
        _gate("tech_research.max_queries_per_tech", 6, config.tech_research, "max_queries_per_tech")
        # Exhaustive: full E2E + highest retries
        _gate("e2e_testing.enabled", True, config.e2e_testing, "enabled")
        _gate("e2e_testing.max_fix_retries", 3, config.e2e_testing, "max_fix_retries")
        _gate("milestone.review_recovery_retries", 3, config.milestone, "review_recovery_retries")
        # 3600s base = 5400s effective wall-clock envelope (1.5x multiplier in cli.py).
        # Exhaustive ships codex routing (Wave B+D) + codex_reasoning_effort=high by default;
        # Wave A+B+C consume ~36 min, leaving ~54 min for Wave D — fits codex-high needs.
        # See docs/plans/2026-04-15-codex-high-milestone-budget.md for the full justification
        # and the deferred Bug #18 (Wave D scope split) follow-up.
        _gate("milestone.milestone_timeout_seconds", 3600, config.milestone, "milestone_timeout_seconds")
        # Browser testing — auto-enable only for PRD/PRD+ builds
        if prd_mode or config.milestone.enabled:
            _gate("browser_testing.enabled", True, config.browser_testing, "enabled")
            _gate("browser_testing.max_fix_retries", 5, config.browser_testing, "max_fix_retries")
        # v10: Exhaustive depth defaults to 2 fix passes
        _gate("post_orchestration_scans.max_scan_fix_passes", 2, config.post_orchestration_scans, "max_scan_fix_passes")
        # Runtime verification — auto-enable for PRD builds at exhaustive depth
        if prd_mode or config.milestone.enabled:
            _gate("runtime_verification.enabled", True, config.runtime_verification, "enabled")
        # Build 2: exhaustive enables full contract_engine, codebase_intelligence, and agent_teams
        _gate("contract_engine.enabled", True, config.contract_engine, "enabled")
        _gate("contract_engine.test_generation", True, config.contract_engine, "test_generation")
        _gate("codebase_intelligence.enabled", True, config.codebase_intelligence, "enabled")
        _gate("codebase_intelligence.replace_static_map", True, config.codebase_intelligence, "replace_static_map")
        _gate("codebase_intelligence.register_artifacts", True, config.codebase_intelligence, "register_artifacts")
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        _gate("milestone.enabled", True, config.milestone, "enabled")
        # Feature #4: auto-enable hooks at exhaustive depth
        _gate("hooks.enabled", True, config.hooks, "enabled")
        # Feature #5: auto-enable routing at exhaustive depth
        _gate("routing.enabled", True, config.routing, "enabled")
        _gate("v18.planner_mode", "vertical_slice", config.v18, "planner_mode")
        _gate("v18.execution_mode", "wave", config.v18, "execution_mode")
        _gate("v18.contract_mode", "openapi", config.v18, "contract_mode")
        _gate("v18.evidence_mode", "soft_gate", config.v18, "evidence_mode")
        _gate("v18.live_endpoint_check", True, config.v18, "live_endpoint_check")
        _gate("v18.openapi_generation", True, config.v18, "openapi_generation")
        _gate("v18.scaffold_enabled", True, config.v18, "scaffold_enabled")
        # Phase 4 throughput is explicit opt-in and must not auto-activate from
        # Phase 3 depth presets.

    elif depth == "enterprise":
        # Enterprise: everything from exhaustive PLUS domain partitioning
        _gate("audit_team.enabled", True, config.audit_team, "enabled")
        _gate("audit_team.max_reaudit_cycles", 3, config.audit_team, "max_reaudit_cycles")
        _gate("tech_research.max_queries_per_tech", 6, config.tech_research, "max_queries_per_tech")
        _gate("e2e_testing.enabled", True, config.e2e_testing, "enabled")
        _gate("e2e_testing.max_fix_retries", 3, config.e2e_testing, "max_fix_retries")
        _gate("milestone.review_recovery_retries", 3, config.milestone, "review_recovery_retries")
        _gate("milestone.milestone_timeout_seconds", 3600, config.milestone, "milestone_timeout_seconds")
        # Enterprise always enables browser testing + runtime verification (no PRD gate)
        _gate("browser_testing.enabled", True, config.browser_testing, "enabled")
        _gate("browser_testing.max_fix_retries", 5, config.browser_testing, "max_fix_retries")
        _gate("runtime_verification.enabled", True, config.runtime_verification, "enabled")
        _gate("post_orchestration_scans.max_scan_fix_passes", 3, config.post_orchestration_scans, "max_scan_fix_passes")
        _gate("contract_engine.enabled", True, config.contract_engine, "enabled")
        _gate("contract_engine.test_generation", True, config.contract_engine, "test_generation")
        _gate("codebase_intelligence.enabled", True, config.codebase_intelligence, "enabled")
        _gate("codebase_intelligence.replace_static_map", True, config.codebase_intelligence, "replace_static_map")
        _gate("codebase_intelligence.register_artifacts", True, config.codebase_intelligence, "register_artifacts")
        _gate("agent_teams.enabled", True, config.agent_teams, "enabled")
        _gate("phase_leads.enabled", True, config.phase_leads, "enabled")
        _gate("milestone.enabled", True, config.milestone, "enabled")
        # Enterprise-specific gates
        _gate("enterprise_mode.enabled", True, config.enterprise_mode, "enabled")
        _gate("enterprise_mode.domain_agents", True, config.enterprise_mode, "domain_agents")
        _gate("enterprise_mode.parallel_review", True, config.enterprise_mode, "parallel_review")
        _gate("enterprise_mode.ownership_validation_gate", True, config.enterprise_mode, "ownership_validation_gate")
        _gate("enterprise_mode.scaffold_shared_files", True, config.enterprise_mode, "scaffold_shared_files")
        # Higher convergence budget for large builds
        _gate("convergence.max_cycles", 25, config.convergence, "max_cycles")
        # Enterprise v2: department model
        _gate("enterprise_mode.department_model", True, config.enterprise_mode, "department_model")
        _gate("departments.enabled", True, config.departments, "enabled")
        # Feature #4: auto-enable hooks at enterprise depth
        _gate("hooks.enabled", True, config.hooks, "enabled")
        # Feature #5: auto-enable routing at enterprise depth
        _gate("routing.enabled", True, config.routing, "enabled")
        # Phase 9.2: tighter quality thresholds for enterprise
        _gate("gate_enforcement.enabled", True, config.gate_enforcement, "enabled")
        _gate("gate_enforcement.enforce_truth_score", True, config.gate_enforcement, "enforce_truth_score")
        _gate("gate_enforcement.truth_score_threshold", 0.95, config.gate_enforcement, "truth_score_threshold")
        _gate("gate_enforcement.min_review_cycles", 3, config.gate_enforcement, "min_review_cycles")
        _gate("e2e_testing.max_fix_retries", 5, config.e2e_testing, "max_fix_retries")
        # Phase 9.2: enterprise quality overrides
        _gate("verification.min_test_count", 10, config.verification, "min_test_count")
        _gate("convergence.escalation_threshold", 6, config.convergence, "escalation_threshold")
        _gate("audit_team.score_healthy_threshold", 95.0, config.audit_team, "score_healthy_threshold")
        _gate("audit_team.score_degraded_threshold", 85.0, config.audit_team, "score_degraded_threshold")
        _gate("audit_team.fix_severity_threshold", "LOW", config.audit_team, "fix_severity_threshold")
        # Phase 9.3: explicit thought budgets for enterprise-depth reasoning
        _gate("orchestrator_st.thought_budgets", {1: 20, 2: 25, 3: 25, 4: 20, 5: 20}, config.orchestrator_st, "thought_budgets")
        # Agent scaling enforcement at enterprise depth
        _gate("agent_scaling.enforce_minimum_counts", True, config.agent_scaling, "enforce_minimum_counts")
        _gate("v18.planner_mode", "vertical_slice", config.v18, "planner_mode")
        _gate("v18.execution_mode", "wave", config.v18, "execution_mode")
        _gate("v18.contract_mode", "openapi", config.v18, "contract_mode")
        _gate("v18.evidence_mode", "soft_gate", config.v18, "evidence_mode")
        _gate("v18.live_endpoint_check", True, config.v18, "live_endpoint_check")
        _gate("v18.openapi_generation", True, config.v18, "openapi_generation")
        _gate("v18.scaffold_enabled", True, config.v18, "scaffold_enabled")
        # Phase 4 throughput is explicit opt-in and must not auto-activate from
        # Phase 3 depth presets.


def get_agent_counts(depth: str) -> dict[str, tuple[int, int]]:
    """Return (min, max) agent counts per phase for the given depth."""
    return DEPTH_AGENT_COUNTS.get(depth, DEPTH_AGENT_COUNTS["standard"])


def get_active_st_points(depth: str, config: OrchestratorSTConfig) -> list[int]:
    """Return which ST decision points are active for this depth level."""
    if not config.enabled:
        return []
    return config.depth_gate.get(depth, [])


def _validate_orchestrator_st_config(cfg: OrchestratorSTConfig) -> None:
    """Validate OrchestratorSTConfig fields."""
    valid_depths = ("quick", "standard", "thorough", "exhaustive", "enterprise")
    for depth, points in cfg.depth_gate.items():
        if depth not in valid_depths:
            raise ValueError(f"orchestrator_st.depth_gate has invalid depth: {depth}")
        for p in points:
            if p not in (1, 2, 3, 4, 5):
                raise ValueError(f"orchestrator_st.depth_gate[{depth}] has invalid point: {p}")
    valid_points = (1, 2, 3, 4, 5)
    for point, budget in cfg.thought_budgets.items():
        if point not in valid_points:
            raise ValueError(f"orchestrator_st.thought_budgets has invalid point: {point}")
        if budget < 3 or budget > 30:
            raise ValueError(f"orchestrator_st.thought_budgets[{point}] must be 3-30")


# ---------------------------------------------------------------------------
# Constraint extraction
# ---------------------------------------------------------------------------

_PROHIBITION_RE = re.compile(
    r"(?:^|[.!?;]\s*)((?:no|zero|never|don'?t|do\s+not|must\s+not|shall\s+not|cannot|can'?t)\s+.{5,200}?)(?:[.!?;]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_REQUIREMENT_RE = re.compile(
    r"(?:^|[.!?;]\s*)((?:must|always|required|shall|need\s+to|have\s+to)\s+.{5,200}?)(?:[.!?;]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_SCOPE_RE_CONSTRAINT = re.compile(
    r"(?:^|[.!?;]\s*)((?:only|limited\s+to|just\s+the|nothing\s+but|exclusively)\s+.{5,200}?)(?:[.!?;]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_EMPHASIS_WORDS = {"zero", "never", "absolutely", "strictly", "critical", "crucial", "must"}

_TECHNOLOGY_RE = re.compile(
    r'\b(Express(?:\.js)?|React(?:\.js)?|Next\.js|Vue(?:\.js)?|Angular|'
    r'Node\.js|Django|Flask|FastAPI|Spring\s*Boot|Rails|Laravel|'
    r'MongoDB|PostgreSQL|MySQL|SQLite|Redis|Supabase|Firebase|'
    r'TypeScript|GraphQL|REST\s*API|gRPC|WebSocket|'
    r'Docker|Kubernetes|AWS|GCP|Azure|Vercel|Netlify|Render|'
    r'Jest|Vitest|Pytest|Mocha|Cypress|Playwright|'
    r'Tailwind(?:\s*CSS)?|Sass|SCSS|Styled[\s-]?Components|'
    r'Zustand|Redux|MobX|Jotai|Recoil|Tanstack[\s-]?Query|'
    r'Prisma|Drizzle|Sequelize|TypeORM|Mongoose|Knex|'
    r'pnpm|bun|yarn|npm|'
    r'monorepo|microservices?|serverless|full[\s-]?stack)\b',
    re.IGNORECASE,
)

_TEST_FRAMEWORK_RE = re.compile(
    r'\b(jest|vitest|pytest|mocha|cypress|playwright|jasmine|ava|tap|uvu)\b',
    re.IGNORECASE,
)

_TEST_REQUIREMENT_RE = re.compile(
    r'(\d+)\+?\s*(?:unit\s+)?tests?',
    re.IGNORECASE,
)

_DESIGN_URL_RE = re.compile(
    r'(?:\[([^\]]*)\]\()?'   # optional markdown link text
    r'(https?://[^\s\)]+)'   # URL itself
    r'\)?',                   # optional closing paren
    re.IGNORECASE,
)

_FALSE_POSITIVE_PHRASES = frozenset({
    "cannot be overstated", "cannot thank", "cannot emphasize enough",
    "cannot stress enough", "cannot overstate", "must have seen",
    "must have been", "must be noted", "do not hesitate",
})


def _compute_emphasis(text: str, normalized: str, emphasis_words: set[str]) -> int:
    """Compute emphasis level for a constraint.

    Returns:
        1 = normal
        2 = ALL_CAPS or emphasis word present
        3 = ALL_CAPS + emphasis word
    """
    emphasis = 1
    is_all_caps = text != text.lower() and text.upper() == text
    has_emphasis_word = any(w in normalized for w in emphasis_words)

    if is_all_caps:
        emphasis = 2
    if has_emphasis_word:
        emphasis = max(emphasis, 2)
        if is_all_caps:
            emphasis = 3

    return emphasis


def extract_constraints(task: str, interview_doc: str | None = None) -> list[ConstraintEntry]:
    """Extract user constraints from task description and interview document."""
    constraints: list[ConstraintEntry] = []

    seen_texts: set[str] = set()

    def _add_constraints(text: str, source: str) -> None:
        for match in _PROHIBITION_RE.finditer(text):
            constraint_text = match.group(1).strip()
            normalized = constraint_text.lower()
            # Filter false positives
            if any(fp in normalized for fp in _FALSE_POSITIVE_PHRASES):
                continue
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                emphasis = _compute_emphasis(constraint_text, normalized, _EMPHASIS_WORDS)
                constraints.append(ConstraintEntry(constraint_text, "prohibition", source, emphasis))

        for match in _REQUIREMENT_RE.finditer(text):
            constraint_text = match.group(1).strip()
            normalized = constraint_text.lower()
            # Filter false positives
            if any(fp in normalized for fp in _FALSE_POSITIVE_PHRASES):
                continue
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                emphasis = _compute_emphasis(constraint_text, normalized, _EMPHASIS_WORDS)
                constraints.append(ConstraintEntry(constraint_text, "requirement", source, emphasis))

        for match in _SCOPE_RE_CONSTRAINT.finditer(text):
            constraint_text = match.group(1).strip()
            normalized = constraint_text.lower()
            # Filter false positives
            if any(fp in normalized for fp in _FALSE_POSITIVE_PHRASES):
                continue
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                emphasis = _compute_emphasis(constraint_text, normalized, _EMPHASIS_WORDS)
                constraints.append(ConstraintEntry(constraint_text, "scope", source, emphasis))

    _add_constraints(task, "task")
    if interview_doc:
        _add_constraints(interview_doc, "interview")

    # Extract technology stack requirements
    for source_text, source_label in [(task, "task"), (interview_doc or "", "interview")]:
        for match in _TECHNOLOGY_RE.finditer(source_text):
            tech = match.group(1).strip()
            normalized = f"must use {tech.lower()}"
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                constraints.append(ConstraintEntry(
                    f"must use {tech}", "requirement", source_label, 2
                ))

    # Extract test count requirements
    for source_text, source_label in [(task, "task"), (interview_doc or "", "interview")]:
        for match in _TEST_REQUIREMENT_RE.finditer(source_text):
            count = match.group(1)
            text = f"must have {count}+ tests"
            normalized = text.lower()
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                constraints.append(ConstraintEntry(text, "requirement", source_label, 2))

    # Extract test framework preferences (Root Cause #12)
    for source_text, source_label in [(task, "task"), (interview_doc or "", "interview")]:
        for match in _TEST_FRAMEWORK_RE.finditer(source_text):
            framework = match.group(1).strip()
            normalized = f"must use {framework.lower()} for testing"
            if normalized not in seen_texts:
                seen_texts.add(normalized)
                constraints.append(ConstraintEntry(
                    f"must use {framework} for testing", "requirement", source_label, 2
                ))

    # Extract design reference URLs (Root Cause #12)
    for source_text, source_label in [(task, "task"), (interview_doc or "", "interview")]:
        for match in _DESIGN_URL_RE.finditer(source_text):
            url = match.group(2).strip()
            # Only include design-relevant URLs (not generic docs)
            if any(kw in url.lower() for kw in ("figma", "dribbble", "behance", "design", "prototype", "sketch")):
                normalized = f"design reference: {url.lower()}"
                if normalized not in seen_texts:
                    seen_texts.add(normalized)
                    constraints.append(ConstraintEntry(
                        f"design reference: {url}", "requirement", source_label, 1
                    ))

    return constraints


def format_constraints_block(constraints: list[ConstraintEntry]) -> str:
    """Format constraints as a prompt block for injection into agent prompts."""
    if not constraints:
        return ""
    lines = ["", "============================================================",
             "USER CONSTRAINTS (MANDATORY — VIOLATING THESE IS A FAILURE)",
             "============================================================", ""]
    for c in constraints:
        prefix = {"prohibition": "PROHIBITION", "requirement": "REQUIREMENT", "scope": "SCOPE"}.get(c.category, "CONSTRAINT")
        emphasis_marker = "!!!" if c.emphasis >= 3 else "!!" if c.emphasis >= 2 else ""
        lines.append(f"  [{prefix}] {emphasis_marker}{c.text}")
    lines.append("")
    return "\n".join(lines)


def parse_max_review_cycles(requirements_content: str) -> int:
    """Parse the maximum review_cycles value from REQUIREMENTS.md content."""
    matches = re.findall(r'\(review_cycles:\s*(\d+)\)', requirements_content)
    return max((int(m) for m in matches), default=0)


def parse_per_item_review_cycles(
    requirements_content: str,
) -> list[tuple[str, bool, int]]:
    """Parse per-item review cycle data from REQUIREMENTS.md.

    Returns list of (item_id, is_checked, review_cycles) tuples.
    """
    pattern = (
        r'^\s*-\s*\[([ xX])\]\s*'
        r'((?:REQ|TECH|INT|WIRE|DESIGN|TEST)-\d+):'
        r'.*?\(review_cycles:\s*(\d+)\)'
    )
    results: list[tuple[str, bool, int]] = []
    for match in re.finditer(pattern, requirements_content, re.MULTILINE):
        is_checked = match.group(1).lower() == 'x'
        item_id = match.group(2)
        cycles = int(match.group(3))
        results.append((item_id, is_checked, cycles))
    return results


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _dict_to_config(data: dict[str, Any]) -> tuple[AgentTeamConfig, set[str]]:
    """Convert a raw dict (from YAML) into an AgentTeamConfig and user overrides.

    Returns:
        Tuple of (config, user_overrides) where user_overrides is the set of
        dotted key paths explicitly set by the user in the YAML file (e.g.
        ``"milestone.mock_data_scan"``).  This allows depth-gating to respect
        intentional user choices.
    """
    cfg = AgentTeamConfig()
    user_overrides: set[str] = set()

    if "orchestrator" in data:
        o = data["orchestrator"]
        backend = o.get("backend", cfg.orchestrator.backend)
        if backend not in ("auto", "api", "cli"):
            raise ValueError(
                f"Invalid orchestrator.backend: {backend!r}. "
                f"Must be one of: auto, api, cli"
            )
        max_thinking_tokens = o.get("max_thinking_tokens", cfg.orchestrator.max_thinking_tokens)
        _validate_max_thinking_tokens(max_thinking_tokens, "orchestrator")
        cfg.orchestrator = OrchestratorConfig(
            model=o.get("model", cfg.orchestrator.model),
            max_turns=o.get("max_turns", cfg.orchestrator.max_turns),
            permission_mode=o.get("permission_mode", cfg.orchestrator.permission_mode),
            max_budget_usd=o.get("max_budget_usd", cfg.orchestrator.max_budget_usd),
            backend=backend,
            max_thinking_tokens=max_thinking_tokens,
        )

    if "depth" in data:
        d = data["depth"]
        scan_scope_mode = d.get("scan_scope_mode", cfg.depth.scan_scope_mode)
        if scan_scope_mode not in ("auto", "full", "changed"):
            raise ValueError(
                f"Invalid depth.scan_scope_mode: {scan_scope_mode!r}. "
                f"Must be one of: auto, full, changed"
            )
        cfg.depth = DepthConfig(
            default=d.get("default", cfg.depth.default),
            auto_detect=d.get("auto_detect", cfg.depth.auto_detect),
            scan_scope_mode=scan_scope_mode,
            keyword_map=d.get("keyword_map", cfg.depth.keyword_map),
        )

    if "convergence" in data:
        c = data["convergence"]
        cfg.convergence = ConvergenceConfig(
            max_cycles=c.get("max_cycles", cfg.convergence.max_cycles),
            escalation_threshold=c.get("escalation_threshold", cfg.convergence.escalation_threshold),
            max_escalation_depth=c.get("max_escalation_depth", cfg.convergence.max_escalation_depth),
            requirements_dir=c.get("requirements_dir", cfg.convergence.requirements_dir),
            requirements_file=c.get("requirements_file", cfg.convergence.requirements_file),
            master_plan_file=c.get("master_plan_file", cfg.convergence.master_plan_file),
            min_convergence_ratio=float(c.get("min_convergence_ratio", cfg.convergence.min_convergence_ratio)),
            recovery_threshold=float(c.get("recovery_threshold", cfg.convergence.recovery_threshold)),
            degraded_threshold=float(c.get("degraded_threshold", cfg.convergence.degraded_threshold)),
        )
        _validate_convergence_config(cfg.convergence)

    if "interview" in data:
        iv = data["interview"]
        cfg.interview = InterviewConfig(
            enabled=iv.get("enabled", cfg.interview.enabled),
            model=iv.get("model", cfg.interview.model),
            max_exchanges=iv.get("max_exchanges", cfg.interview.max_exchanges),
            min_exchanges=iv.get("min_exchanges", cfg.interview.min_exchanges),
            require_understanding_summary=iv.get("require_understanding_summary", cfg.interview.require_understanding_summary),
            require_codebase_exploration=iv.get("require_codebase_exploration", cfg.interview.require_codebase_exploration),
            max_thinking_tokens=iv.get("max_thinking_tokens", cfg.interview.max_thinking_tokens),
        )
        # Validate the InterviewConfig
        _validate_interview_config(cfg.interview)

    if "design_reference" in data and isinstance(data["design_reference"], dict):
        dr = data["design_reference"]
        cfg.design_reference = DesignReferenceConfig(
            urls=dr.get("urls", cfg.design_reference.urls),
            depth=dr.get("depth", cfg.design_reference.depth),
            max_pages_per_site=dr.get("max_pages_per_site", cfg.design_reference.max_pages_per_site),
            cache_ttl_seconds=dr.get("cache_ttl_seconds", cfg.design_reference.cache_ttl_seconds),
            standards_file=dr.get("standards_file", cfg.design_reference.standards_file),
            require_ui_doc=dr.get("require_ui_doc", cfg.design_reference.require_ui_doc),
            ui_requirements_file=dr.get("ui_requirements_file", cfg.design_reference.ui_requirements_file),
            extraction_retries=dr.get("extraction_retries", cfg.design_reference.extraction_retries),
            fallback_generation=dr.get("fallback_generation", cfg.design_reference.fallback_generation),
            content_quality_check=dr.get("content_quality_check", cfg.design_reference.content_quality_check),
        )

        # Validate design_reference.depth enum value
        if cfg.design_reference.depth and cfg.design_reference.depth not in ("branding", "screenshots", "full", ""):
            raise ValueError(
                f"Invalid design_reference.depth: {cfg.design_reference.depth!r}. "
                f"Must be one of: branding, screenshots, full"
            )

        # Validate extraction_retries is non-negative
        if cfg.design_reference.extraction_retries < 0:
            raise ValueError(
                f"Invalid design_reference.extraction_retries: {cfg.design_reference.extraction_retries}. "
                f"Must be >= 0"
            )

    if "codebase_map" in data and isinstance(data["codebase_map"], dict):
        cm = data["codebase_map"]
        cfg.codebase_map = CodebaseMapConfig(
            enabled=cm.get("enabled", cfg.codebase_map.enabled),
            max_files=cm.get("max_files", cfg.codebase_map.max_files),
            max_file_size_kb=cm.get("max_file_size_kb", cfg.codebase_map.max_file_size_kb),
            max_file_size_kb_ts=cm.get("max_file_size_kb_ts", cfg.codebase_map.max_file_size_kb_ts),
            timeout_seconds=cm.get("timeout_seconds", cfg.codebase_map.timeout_seconds),
            exclude_patterns=cm.get("exclude_patterns", cfg.codebase_map.exclude_patterns),
        )

    if "scheduler" in data and isinstance(data["scheduler"], dict):
        sc = data["scheduler"]
        cfg.scheduler = SchedulerConfig(
            enabled=sc.get("enabled", cfg.scheduler.enabled),
            max_parallel_tasks=sc.get("max_parallel_tasks", cfg.scheduler.max_parallel_tasks),
            conflict_strategy=sc.get("conflict_strategy", cfg.scheduler.conflict_strategy),
            enable_context_scoping=sc.get("enable_context_scoping", cfg.scheduler.enable_context_scoping),
            enable_critical_path=sc.get("enable_critical_path", cfg.scheduler.enable_critical_path),
        )

        # Validate conflict_strategy enum value
        if cfg.scheduler.conflict_strategy not in ("artificial-dependency", "integration-agent"):
            raise ValueError(
                f"Invalid scheduler.conflict_strategy: {cfg.scheduler.conflict_strategy!r}. "
                f"Must be one of: artificial-dependency, integration-agent"
            )

    if "verification" in data and isinstance(data["verification"], dict):
        vr = data["verification"]
        cfg.verification = VerificationConfig(
            enabled=vr.get("enabled", cfg.verification.enabled),
            contract_file=vr.get("contract_file", cfg.verification.contract_file),
            verification_file=vr.get("verification_file", cfg.verification.verification_file),
            blocking=vr.get("blocking", cfg.verification.blocking),
            run_lint=vr.get("run_lint", cfg.verification.run_lint),
            run_type_check=vr.get("run_type_check", cfg.verification.run_type_check),
            run_tests=vr.get("run_tests", cfg.verification.run_tests),
            run_build=vr.get("run_build", cfg.verification.run_build),
            run_security=vr.get("run_security", cfg.verification.run_security),
            run_quality_checks=vr.get("run_quality_checks", cfg.verification.run_quality_checks),
            min_test_count=vr.get("min_test_count", cfg.verification.min_test_count),
        )

    if "pseudocode" in data and isinstance(data["pseudocode"], dict):
        pc = data["pseudocode"]
        cfg.pseudocode = PseudocodeConfig(
            enabled=pc.get("enabled", cfg.pseudocode.enabled),
            require_architect_approval=pc.get("require_architect_approval", cfg.pseudocode.require_architect_approval),
            output_dir=pc.get("output_dir", cfg.pseudocode.output_dir),
            complexity_analysis=pc.get("complexity_analysis", cfg.pseudocode.complexity_analysis),
            edge_case_minimum=pc.get("edge_case_minimum", cfg.pseudocode.edge_case_minimum),
        )

    if "quality" in data and isinstance(data["quality"], dict):
        q = data["quality"]
        for key in ("production_defaults", "craft_review", "quality_triggers_reloop"):
            if key in q:
                user_overrides.add(f"quality.{key}")
        cfg.quality = QualityConfig(
            production_defaults=q.get("production_defaults", cfg.quality.production_defaults),
            craft_review=q.get("craft_review", cfg.quality.craft_review),
            quality_triggers_reloop=q.get("quality_triggers_reloop", cfg.quality.quality_triggers_reloop),
        )

    if "investigation" in data and isinstance(data["investigation"], dict):
        inv = data["investigation"]
        cfg.investigation = InvestigationConfig(
            enabled=inv.get("enabled", cfg.investigation.enabled),
            gemini_model=inv.get("gemini_model", cfg.investigation.gemini_model),
            max_queries_per_agent=inv.get("max_queries_per_agent", cfg.investigation.max_queries_per_agent),
            timeout_seconds=inv.get("timeout_seconds", cfg.investigation.timeout_seconds),
            agents=inv.get("agents", cfg.investigation.agents),
            sequential_thinking=inv.get("sequential_thinking", cfg.investigation.sequential_thinking),
            max_thoughts_per_item=inv.get("max_thoughts_per_item", cfg.investigation.max_thoughts_per_item),
            enable_hypothesis_loop=inv.get("enable_hypothesis_loop", cfg.investigation.enable_hypothesis_loop),
        )
        _validate_investigation_config(cfg.investigation)

    if "orchestrator_st" in data and isinstance(data["orchestrator_st"], dict):
        ost = data["orchestrator_st"]
        depth_gate_raw = ost.get("depth_gate", None)
        depth_gate = cfg.orchestrator_st.depth_gate
        if depth_gate_raw and isinstance(depth_gate_raw, dict):
            depth_gate = {k: list(v) for k, v in depth_gate_raw.items()}
        thought_budgets_raw = ost.get("thought_budgets", None)
        thought_budgets = cfg.orchestrator_st.thought_budgets
        if thought_budgets_raw and isinstance(thought_budgets_raw, dict):
            thought_budgets = {int(k): int(v) for k, v in thought_budgets_raw.items()}
        cfg.orchestrator_st = OrchestratorSTConfig(
            enabled=ost.get("enabled", cfg.orchestrator_st.enabled),
            depth_gate=depth_gate,
            thought_budgets=thought_budgets,
        )
        _validate_orchestrator_st_config(cfg.orchestrator_st)

    if "milestone" in data and isinstance(data["milestone"], dict):
        ms = data["milestone"]
        for key in ("mock_data_scan", "ui_compliance_scan", "review_recovery_retries", "milestone_timeout_seconds"):
            if key in ms:
                user_overrides.add(f"milestone.{key}")
        resume_val = ms.get("resume_from_milestone", cfg.milestone.resume_from_milestone)
        cfg.milestone = MilestoneConfig(
            enabled=ms.get("enabled", cfg.milestone.enabled),
            max_parallel_milestones=ms.get(
                "max_parallel_milestones", cfg.milestone.max_parallel_milestones,
            ),
            health_gate=ms.get("health_gate", cfg.milestone.health_gate),
            wiring_check=ms.get("wiring_check", cfg.milestone.wiring_check),
            resume_from_milestone=resume_val if isinstance(resume_val, str) else None,
            wiring_fix_retries=ms.get(
                "wiring_fix_retries", cfg.milestone.wiring_fix_retries,
            ),
            max_milestones_warning=ms.get(
                "max_milestones_warning", cfg.milestone.max_milestones_warning,
            ),
            review_recovery_retries=ms.get(
                "review_recovery_retries", cfg.milestone.review_recovery_retries,
            ),
            mock_data_scan=ms.get(
                "mock_data_scan", cfg.milestone.mock_data_scan,
            ),
            ui_compliance_scan=ms.get(
                "ui_compliance_scan", cfg.milestone.ui_compliance_scan,
            ),
            milestone_timeout_seconds=ms.get(
                "milestone_timeout_seconds", cfg.milestone.milestone_timeout_seconds,
            ),
        )
        # Validate: review_recovery_retries >= 0
        if cfg.milestone.review_recovery_retries < 0:
            raise ValueError(
                f"Invalid milestone.review_recovery_retries: "
                f"{cfg.milestone.review_recovery_retries}. Must be >= 0"
            )

    if "prd_chunking" in data and isinstance(data["prd_chunking"], dict):
        pc = data["prd_chunking"]
        cfg.prd_chunking = PRDChunkingConfig(
            enabled=pc.get("enabled", cfg.prd_chunking.enabled),
            threshold=pc.get("threshold", cfg.prd_chunking.threshold),
            max_chunk_size=pc.get("max_chunk_size", cfg.prd_chunking.max_chunk_size),
        )

    if "integrity_scans" in data and isinstance(data["integrity_scans"], dict):
        isc = data["integrity_scans"]
        for key in ("deployment_scan", "asset_scan", "prd_reconciliation"):
            if key in isc:
                user_overrides.add(f"integrity_scans.{key}")
        cfg.integrity_scans = IntegrityScanConfig(
            deployment_scan=isc.get("deployment_scan", cfg.integrity_scans.deployment_scan),
            asset_scan=isc.get("asset_scan", cfg.integrity_scans.asset_scan),
            prd_reconciliation=isc.get("prd_reconciliation", cfg.integrity_scans.prd_reconciliation),
        )

    if "runtime_verification" in data and isinstance(data["runtime_verification"], dict):
        rv = data["runtime_verification"]
        for key in rv:
            user_overrides.add(f"runtime_verification.{key}")
        cfg.runtime_verification = RuntimeVerificationConfig(
            enabled=rv.get("enabled", cfg.runtime_verification.enabled),
            docker_build=rv.get("docker_build", cfg.runtime_verification.docker_build),
            docker_start=rv.get("docker_start", cfg.runtime_verification.docker_start),
            database_init=rv.get("database_init", cfg.runtime_verification.database_init),
            smoke_test=rv.get("smoke_test", cfg.runtime_verification.smoke_test),
            cleanup_after=rv.get("cleanup_after", cfg.runtime_verification.cleanup_after),
            max_build_fix_rounds=rv.get("max_build_fix_rounds", cfg.runtime_verification.max_build_fix_rounds),
            startup_timeout_s=rv.get("startup_timeout_s", cfg.runtime_verification.startup_timeout_s),
            compose_file=rv.get("compose_file", cfg.runtime_verification.compose_file),
            fix_loop=rv.get("fix_loop", cfg.runtime_verification.fix_loop),
            max_fix_rounds_per_service=rv.get("max_fix_rounds_per_service", cfg.runtime_verification.max_fix_rounds_per_service),
            max_total_fix_rounds=rv.get("max_total_fix_rounds", cfg.runtime_verification.max_total_fix_rounds),
            max_fix_budget_usd=rv.get("max_fix_budget_usd", cfg.runtime_verification.max_fix_budget_usd),
        )

    if "e2e_testing" in data and isinstance(data["e2e_testing"], dict):
        et = data["e2e_testing"]
        for key in ("enabled", "max_fix_retries"):
            if key in et:
                user_overrides.add(f"e2e_testing.{key}")
        # Silently ignore legacy budget_limit_usd key
        cfg.e2e_testing = E2ETestingConfig(
            enabled=et.get("enabled", cfg.e2e_testing.enabled),
            backend_api_tests=et.get("backend_api_tests", cfg.e2e_testing.backend_api_tests),
            frontend_playwright_tests=et.get("frontend_playwright_tests", cfg.e2e_testing.frontend_playwright_tests),
            max_fix_retries=et.get("max_fix_retries", cfg.e2e_testing.max_fix_retries),
            test_port=et.get("test_port", cfg.e2e_testing.test_port),
            skip_if_no_api=et.get("skip_if_no_api", cfg.e2e_testing.skip_if_no_api),
            skip_if_no_frontend=et.get("skip_if_no_frontend", cfg.e2e_testing.skip_if_no_frontend),
        )
        # Validate: max_fix_retries >= 1 (at least one fix attempt mandatory)
        if cfg.e2e_testing.max_fix_retries < 1:
            raise ValueError(
                f"Invalid e2e_testing.max_fix_retries: {cfg.e2e_testing.max_fix_retries}. "
                f"Must be >= 1"
            )
        # Validate: test_port in valid range
        if not (1024 <= cfg.e2e_testing.test_port <= 65535):
            raise ValueError(
                f"Invalid e2e_testing.test_port: {cfg.e2e_testing.test_port}. "
                f"Must be between 1024 and 65535"
            )

    if "browser_testing" in data and isinstance(data["browser_testing"], dict):
        bt = data["browser_testing"]
        for key in ("enabled", "max_fix_retries"):
            if key in bt:
                user_overrides.add(f"browser_testing.{key}")
        cfg.browser_testing = BrowserTestingConfig(
            enabled=bt.get("enabled", cfg.browser_testing.enabled),
            max_fix_retries=bt.get("max_fix_retries", cfg.browser_testing.max_fix_retries),
            e2e_pass_rate_gate=bt.get("e2e_pass_rate_gate", cfg.browser_testing.e2e_pass_rate_gate),
            headless=bt.get("headless", cfg.browser_testing.headless),
            app_start_command=str(bt.get("app_start_command", cfg.browser_testing.app_start_command)),
            app_port=bt.get("app_port", cfg.browser_testing.app_port),
            regression_sweep=bt.get("regression_sweep", cfg.browser_testing.regression_sweep),
        )
        # Validate: max_fix_retries >= 1
        if cfg.browser_testing.max_fix_retries < 1:
            raise ValueError(
                f"Invalid browser_testing.max_fix_retries: {cfg.browser_testing.max_fix_retries}. "
                f"Must be >= 1"
            )
        # Validate: app_port 0 (auto) or 1024-65535
        if cfg.browser_testing.app_port != 0 and not (1024 <= cfg.browser_testing.app_port <= 65535):
            raise ValueError(
                f"Invalid browser_testing.app_port: {cfg.browser_testing.app_port}. "
                f"Must be 0 (auto) or between 1024 and 65535"
            )
        # Validate: e2e_pass_rate_gate in [0.0, 1.0]
        if not (0.0 <= cfg.browser_testing.e2e_pass_rate_gate <= 1.0):
            raise ValueError(
                f"Invalid browser_testing.e2e_pass_rate_gate: {cfg.browser_testing.e2e_pass_rate_gate}. "
                f"Must be between 0.0 and 1.0"
            )

    if "tracking_documents" in data and isinstance(data["tracking_documents"], dict):
        td = data["tracking_documents"]
        cfg.tracking_documents = TrackingDocumentsConfig(
            e2e_coverage_matrix=td.get("e2e_coverage_matrix", cfg.tracking_documents.e2e_coverage_matrix),
            fix_cycle_log=td.get("fix_cycle_log", cfg.tracking_documents.fix_cycle_log),
            milestone_handoff=td.get("milestone_handoff", cfg.tracking_documents.milestone_handoff),
            coverage_completeness_gate=td.get("coverage_completeness_gate", cfg.tracking_documents.coverage_completeness_gate),
            wiring_completeness_gate=td.get("wiring_completeness_gate", cfg.tracking_documents.wiring_completeness_gate),
            contract_compliance_matrix=td.get("contract_compliance_matrix", cfg.tracking_documents.contract_compliance_matrix),
        )
        # Validate: coverage_completeness_gate in [0.0, 1.0]
        if not (0.0 <= cfg.tracking_documents.coverage_completeness_gate <= 1.0):
            raise ValueError(
                f"Invalid tracking_documents.coverage_completeness_gate: "
                f"{cfg.tracking_documents.coverage_completeness_gate}. Must be between 0.0 and 1.0"
            )
        # Validate: wiring_completeness_gate in [0.0, 1.0]
        if not (0.0 <= cfg.tracking_documents.wiring_completeness_gate <= 1.0):
            raise ValueError(
                f"Invalid tracking_documents.wiring_completeness_gate: "
                f"{cfg.tracking_documents.wiring_completeness_gate}. Must be between 0.0 and 1.0"
            )

    if "database_scans" in data and isinstance(data["database_scans"], dict):
        dsc = data["database_scans"]
        for key in ("dual_orm_scan", "default_value_scan", "relationship_scan"):
            if key in dsc:
                user_overrides.add(f"database_scans.{key}")
        cfg.database_scans = DatabaseScanConfig(
            dual_orm_scan=dsc.get("dual_orm_scan", cfg.database_scans.dual_orm_scan),
            default_value_scan=dsc.get("default_value_scan", cfg.database_scans.default_value_scan),
            relationship_scan=dsc.get("relationship_scan", cfg.database_scans.relationship_scan),
        )

    if "post_orchestration_scans" in data and isinstance(data["post_orchestration_scans"], dict):
        pos = data["post_orchestration_scans"]
        for key in ("mock_data_scan", "ui_compliance_scan", "api_contract_scan", "silent_data_loss_scan", "endpoint_xref_scan", "max_scan_fix_passes"):
            if key in pos:
                user_overrides.add(f"post_orchestration_scans.{key}")
        _msfp = pos.get("max_scan_fix_passes", 1)
        if isinstance(_msfp, int) and _msfp >= 0:
            _msfp_val = _msfp
        elif isinstance(_msfp, int):
            _msfp_val = 0
        else:
            _msfp_val = 1
        _sed = pos.get("scan_exclude_dirs", cfg.post_orchestration_scans.scan_exclude_dirs)
        if isinstance(_sed, str):
            _sed = [_sed]
        elif not isinstance(_sed, list):
            _sed = []
        cfg.post_orchestration_scans = PostOrchestrationScanConfig(
            mock_data_scan=pos.get("mock_data_scan", cfg.post_orchestration_scans.mock_data_scan),
            ui_compliance_scan=pos.get("ui_compliance_scan", cfg.post_orchestration_scans.ui_compliance_scan),
            api_contract_scan=pos.get("api_contract_scan", cfg.post_orchestration_scans.api_contract_scan),
            silent_data_loss_scan=pos.get("silent_data_loss_scan", cfg.post_orchestration_scans.silent_data_loss_scan),
            endpoint_xref_scan=pos.get("endpoint_xref_scan", cfg.post_orchestration_scans.endpoint_xref_scan),
            handler_completeness_scan=pos.get("handler_completeness_scan", cfg.post_orchestration_scans.handler_completeness_scan),
            enum_registry_scan=pos.get("enum_registry_scan", cfg.post_orchestration_scans.enum_registry_scan),
            response_shape_scan=pos.get("response_shape_scan", cfg.post_orchestration_scans.response_shape_scan),
            soft_delete_scan=pos.get("soft_delete_scan", cfg.post_orchestration_scans.soft_delete_scan),
            auth_flow_scan=pos.get("auth_flow_scan", cfg.post_orchestration_scans.auth_flow_scan),
            infrastructure_scan=pos.get("infrastructure_scan", cfg.post_orchestration_scans.infrastructure_scan),
            schema_validation_scan=pos.get("schema_validation_scan", cfg.post_orchestration_scans.schema_validation_scan),
            cross_service_scan=pos.get("cross_service_scan", cfg.post_orchestration_scans.cross_service_scan),
            api_completeness_scan=pos.get("api_completeness_scan", cfg.post_orchestration_scans.api_completeness_scan),
            max_scan_fix_passes=_msfp_val,
            scan_exclude_dirs=_sed,
        )
    elif "milestone" in data and isinstance(data["milestone"], dict):
        # Backward compat: migrate milestone.mock_data_scan / ui_compliance_scan
        ms = data["milestone"]
        if "mock_data_scan" in ms:
            cfg.post_orchestration_scans.mock_data_scan = ms["mock_data_scan"]
        if "ui_compliance_scan" in ms:
            cfg.post_orchestration_scans.ui_compliance_scan = ms["ui_compliance_scan"]

    if "tech_research" in data and isinstance(data["tech_research"], dict):
        tr = data["tech_research"]
        for key in ("enabled", "max_queries_per_tech"):
            if key in tr:
                user_overrides.add(f"tech_research.{key}")
        cfg.tech_research = TechResearchConfig(
            enabled=tr.get("enabled", cfg.tech_research.enabled),
            max_techs=tr.get("max_techs", cfg.tech_research.max_techs),
            max_queries_per_tech=tr.get("max_queries_per_tech", cfg.tech_research.max_queries_per_tech),
            retry_on_incomplete=tr.get("retry_on_incomplete", cfg.tech_research.retry_on_incomplete),
            injection_max_chars=tr.get("injection_max_chars", cfg.tech_research.injection_max_chars),
            expanded_queries=tr.get("expanded_queries", cfg.tech_research.expanded_queries),
            max_expanded_queries=tr.get("max_expanded_queries", cfg.tech_research.max_expanded_queries),
        )
        # Validate: max_techs >= 1
        if cfg.tech_research.max_techs < 1:
            raise ValueError(
                f"Invalid tech_research.max_techs: {cfg.tech_research.max_techs}. Must be >= 1"
            )
        # Validate: max_queries_per_tech >= 1
        if cfg.tech_research.max_queries_per_tech < 1:
            raise ValueError(
                f"Invalid tech_research.max_queries_per_tech: "
                f"{cfg.tech_research.max_queries_per_tech}. Must be >= 1"
            )
        # Validate: max_expanded_queries >= 0
        if cfg.tech_research.max_expanded_queries < 0:
            raise ValueError(
                f"Invalid tech_research.max_expanded_queries: "
                f"{cfg.tech_research.max_expanded_queries}. Must be >= 0"
            )

    if "integration_gate" in data and isinstance(data["integration_gate"], dict):
        ig = data["integration_gate"]
        cfg.integration_gate = IntegrationGateConfig(
            enabled=ig.get("enabled", cfg.integration_gate.enabled),
            contract_extraction=ig.get("contract_extraction", cfg.integration_gate.contract_extraction),
            verification_enabled=ig.get("verification_enabled", cfg.integration_gate.verification_enabled),
            verification_mode=ig.get("verification_mode", cfg.integration_gate.verification_mode),
            enriched_handoff=ig.get("enriched_handoff", cfg.integration_gate.enriched_handoff),
            cross_milestone_source_access=ig.get("cross_milestone_source_access", cfg.integration_gate.cross_milestone_source_access),
            serialization_mandate=ig.get("serialization_mandate", cfg.integration_gate.serialization_mandate),
            contract_injection_max_chars=ig.get("contract_injection_max_chars", cfg.integration_gate.contract_injection_max_chars),
            report_injection_max_chars=ig.get("report_injection_max_chars", cfg.integration_gate.report_injection_max_chars),
            backend_source_patterns=ig.get("backend_source_patterns", cfg.integration_gate.backend_source_patterns),
            skip_directories=ig.get("skip_directories", cfg.integration_gate.skip_directories),
            blocking_mode=ig.get("blocking_mode", cfg.integration_gate.blocking_mode),
            route_structure_check=ig.get("route_structure_check", cfg.integration_gate.route_structure_check),
            response_shape_check=ig.get("response_shape_check", cfg.integration_gate.response_shape_check),
            auth_flow_check=ig.get("auth_flow_check", cfg.integration_gate.auth_flow_check),
            enum_cross_check=ig.get("enum_cross_check", cfg.integration_gate.enum_cross_check),
            route_pattern_enforcement=ig.get("route_pattern_enforcement", cfg.integration_gate.route_pattern_enforcement),
        )
        # Validate verification_mode
        if cfg.integration_gate.verification_mode not in ("warn", "block"):
            raise ValueError(
                f"Invalid integration_gate.verification_mode: {cfg.integration_gate.verification_mode!r}. "
                f"Must be one of: warn, block"
            )

    if "schema_validation" in data and isinstance(data["schema_validation"], dict):
        sv = data["schema_validation"]
        for key in sv:
            user_overrides.add(f"schema_validation.{key}")
        cfg.schema_validation = SchemaValidationConfig(
            enabled=sv.get("enabled", cfg.schema_validation.enabled),
            checks=sv.get("checks", cfg.schema_validation.checks),
            block_on_critical=sv.get("block_on_critical", cfg.schema_validation.block_on_critical),
        )

    if "quality_validation" in data and isinstance(data["quality_validation"], dict):
        qv = data["quality_validation"]
        for key in qv:
            user_overrides.add(f"quality_validation.{key}")
        cfg.quality_validation = QualityValidationConfig(
            enabled=qv.get("enabled", cfg.quality_validation.enabled),
            soft_delete_check=qv.get("soft_delete_check", cfg.quality_validation.soft_delete_check),
            enum_registry_check=qv.get("enum_registry_check", cfg.quality_validation.enum_registry_check),
            response_shape_check=qv.get("response_shape_check", cfg.quality_validation.response_shape_check),
            auth_flow_check=qv.get("auth_flow_check", cfg.quality_validation.auth_flow_check),
            build_health_check=qv.get("build_health_check", cfg.quality_validation.build_health_check),
            block_on_critical=qv.get("block_on_critical", cfg.quality_validation.block_on_critical),
        )

    if "audit_team" in data and isinstance(data["audit_team"], dict):
        atm = data["audit_team"]
        for key in atm:
            user_overrides.add(f"audit_team.{key}")
        cfg.audit_team = AuditTeamConfig(
            enabled=atm.get("enabled", cfg.audit_team.enabled),
            max_parallel_auditors=atm.get("max_parallel_auditors", cfg.audit_team.max_parallel_auditors),
            max_reaudit_cycles=atm.get("max_reaudit_cycles", cfg.audit_team.max_reaudit_cycles),
            fix_severity_threshold=atm.get("fix_severity_threshold", cfg.audit_team.fix_severity_threshold),
            score_healthy_threshold=float(atm.get("score_healthy_threshold", cfg.audit_team.score_healthy_threshold)),
            score_degraded_threshold=float(atm.get("score_degraded_threshold", cfg.audit_team.score_degraded_threshold)),
            context7_prefetch=atm.get("context7_prefetch", cfg.audit_team.context7_prefetch),
            max_findings_per_fix_task=atm.get("max_findings_per_fix_task", cfg.audit_team.max_findings_per_fix_task),
            skip_overlapping_scans=atm.get("skip_overlapping_scans", cfg.audit_team.skip_overlapping_scans),
        )
        _validate_audit_team_config(cfg.audit_team)

    if "agent_teams" in data and isinstance(data["agent_teams"], dict):
        at = data["agent_teams"]
        for key in ("enabled",):
            if key in at:
                user_overrides.add(f"agent_teams.{key}")
        cfg.agent_teams = AgentTeamsConfig(
            enabled=at.get("enabled", cfg.agent_teams.enabled),
            fallback_to_cli=at.get("fallback_to_cli", cfg.agent_teams.fallback_to_cli),
            delegate_mode=at.get("delegate_mode", cfg.agent_teams.delegate_mode),
            max_teammates=at.get("max_teammates", cfg.agent_teams.max_teammates),
            teammate_model=str(at.get("teammate_model", cfg.agent_teams.teammate_model)),
            teammate_permission_mode=at.get("teammate_permission_mode", cfg.agent_teams.teammate_permission_mode),
            teammate_idle_timeout=at.get("teammate_idle_timeout", cfg.agent_teams.teammate_idle_timeout),
            task_completed_hook=at.get("task_completed_hook", cfg.agent_teams.task_completed_hook),
            wave_timeout_seconds=at.get("wave_timeout_seconds", cfg.agent_teams.wave_timeout_seconds),
            task_timeout_seconds=at.get("task_timeout_seconds", cfg.agent_teams.task_timeout_seconds),
            teammate_display_mode=at.get("teammate_display_mode", cfg.agent_teams.teammate_display_mode),
            contract_limit=at.get("contract_limit", cfg.agent_teams.contract_limit),
            team_name_prefix=at.get("team_name_prefix", cfg.agent_teams.team_name_prefix),
            phase_lead_model=str(at.get("phase_lead_model", cfg.agent_teams.phase_lead_model)),
            phase_lead_max_turns=at.get("phase_lead_max_turns", cfg.agent_teams.phase_lead_max_turns),
            auto_shutdown=at.get("auto_shutdown", cfg.agent_teams.auto_shutdown),
        )
        # Validate teammate_display_mode
        _valid_display_modes = ("in-process", "tmux", "split")
        if cfg.agent_teams.teammate_display_mode not in _valid_display_modes:
            raise ValueError(
                f"Invalid agent_teams.teammate_display_mode: "
                f"{cfg.agent_teams.teammate_display_mode!r}. "
                f"Must be one of: {', '.join(_valid_display_modes)}"
            )
        # Validate max_teammates >= 1
        if cfg.agent_teams.max_teammates < 1:
            raise ValueError(
                f"Invalid agent_teams.max_teammates: {cfg.agent_teams.max_teammates}. Must be >= 1"
            )
        # Validate timeouts >= 60
        if cfg.agent_teams.wave_timeout_seconds < 60:
            raise ValueError(
                f"Invalid agent_teams.wave_timeout_seconds: {cfg.agent_teams.wave_timeout_seconds}. Must be >= 60"
            )
        if cfg.agent_teams.task_timeout_seconds < 60:
            raise ValueError(
                f"Invalid agent_teams.task_timeout_seconds: {cfg.agent_teams.task_timeout_seconds}. Must be >= 60"
            )

    if "phase_leads" in data and isinstance(data["phase_leads"], dict):
        pl = data["phase_leads"]
        for key in ("enabled", "handoff_timeout_seconds", "allow_parallel_phases"):
            if key in pl:
                user_overrides.add(f"phase_leads.{key}")

        def _phase_lead_cfg(key: str, current: PhaseLeadConfig) -> PhaseLeadConfig:
            raw = pl.get(key, {})
            if not isinstance(raw, dict):
                return current
            return PhaseLeadConfig(
                enabled=raw.get("enabled", current.enabled),
                model=str(raw.get("model", current.model)),
                max_sub_agents=raw.get("max_sub_agents", current.max_sub_agents),
                tools=list(raw.get("tools", current.tools)),
                idle_timeout=raw.get("idle_timeout", current.idle_timeout),
            )

        cfg.phase_leads = PhaseLeadsConfig(
            enabled=pl.get("enabled", cfg.phase_leads.enabled),
            wave_a_lead=_phase_lead_cfg("wave_a_lead", cfg.phase_leads.wave_a_lead),
            wave_d5_lead=_phase_lead_cfg("wave_d5_lead", cfg.phase_leads.wave_d5_lead),
            wave_t_lead=_phase_lead_cfg("wave_t_lead", cfg.phase_leads.wave_t_lead),
            wave_e_lead=_phase_lead_cfg("wave_e_lead", cfg.phase_leads.wave_e_lead),
            handoff_timeout_seconds=pl.get(
                "handoff_timeout_seconds",
                cfg.phase_leads.handoff_timeout_seconds,
            ),
            allow_parallel_phases=pl.get(
                "allow_parallel_phases",
                cfg.phase_leads.allow_parallel_phases,
            ),
        )

    if "observer" in data and isinstance(data["observer"], dict):
        ob = data["observer"]
        for key in ob:
            user_overrides.add(f"observer.{key}")
        cfg.observer = ObserverConfig(
            enabled=ob.get("enabled", cfg.observer.enabled),
            log_only=ob.get("log_only", cfg.observer.log_only),
            confidence_threshold=float(ob.get(
                "confidence_threshold",
                cfg.observer.confidence_threshold,
            )),
            context7_enabled=ob.get("context7_enabled", cfg.observer.context7_enabled),
            context7_fallback_to_training=ob.get(
                "context7_fallback_to_training",
                cfg.observer.context7_fallback_to_training,
            ),
            model=str(ob.get("model", cfg.observer.model)),
            max_tokens=ob.get("max_tokens", cfg.observer.max_tokens),
            peek_cooldown_seconds=float(ob.get(
                "peek_cooldown_seconds",
                cfg.observer.peek_cooldown_seconds,
            )),
            peek_timeout_seconds=float(ob.get(
                "peek_timeout_seconds",
                cfg.observer.peek_timeout_seconds,
            )),
            peek_settle_seconds=float(ob.get(
                "peek_settle_seconds",
                cfg.observer.peek_settle_seconds,
            )),
            max_peeks_per_wave=ob.get("max_peeks_per_wave", cfg.observer.max_peeks_per_wave),
            time_based_interval_seconds=float(ob.get(
                "time_based_interval_seconds",
                cfg.observer.time_based_interval_seconds,
            )),
            codex_notification_observer_enabled=ob.get(
                "codex_notification_observer_enabled",
                cfg.observer.codex_notification_observer_enabled,
            ),
            codex_plan_check_enabled=ob.get(
                "codex_plan_check_enabled",
                cfg.observer.codex_plan_check_enabled,
            ),
            codex_diff_check_enabled=ob.get(
                "codex_diff_check_enabled",
                cfg.observer.codex_diff_check_enabled,
            ),
        )

    if "contract_engine" in data and isinstance(data["contract_engine"], dict):
        ce = data["contract_engine"]
        for key in ("enabled", "validation_on_build", "test_generation"):
            if key in ce:
                user_overrides.add(f"contract_engine.{key}")
        cfg.contract_engine = ContractEngineConfig(
            enabled=ce.get("enabled", cfg.contract_engine.enabled),
            mcp_command=ce.get("mcp_command", cfg.contract_engine.mcp_command),
            mcp_args=ce.get("mcp_args", cfg.contract_engine.mcp_args),
            database_path=str(ce.get("database_path", cfg.contract_engine.database_path)),
            validation_on_build=ce.get("validation_on_build", cfg.contract_engine.validation_on_build),
            test_generation=ce.get("test_generation", cfg.contract_engine.test_generation),
            server_root=str(ce.get("server_root", cfg.contract_engine.server_root)),
            startup_timeout_ms=ce.get("startup_timeout_ms", cfg.contract_engine.startup_timeout_ms),
            tool_timeout_ms=ce.get("tool_timeout_ms", cfg.contract_engine.tool_timeout_ms),
        )
        # Validate startup_timeout_ms >= 1000
        if cfg.contract_engine.startup_timeout_ms < 1000:
            raise ValueError(
                f"Invalid contract_engine.startup_timeout_ms: {cfg.contract_engine.startup_timeout_ms}. Must be >= 1000"
            )
        # Validate tool_timeout_ms >= 1000
        if cfg.contract_engine.tool_timeout_ms < 1000:
            raise ValueError(
                f"Invalid contract_engine.tool_timeout_ms: {cfg.contract_engine.tool_timeout_ms}. Must be >= 1000"
            )

    if "codebase_intelligence" in data and isinstance(data["codebase_intelligence"], dict):
        ci = data["codebase_intelligence"]
        for key in ("enabled", "replace_static_map", "register_artifacts"):
            if key in ci:
                user_overrides.add(f"codebase_intelligence.{key}")
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(
            enabled=ci.get("enabled", cfg.codebase_intelligence.enabled),
            mcp_command=ci.get("mcp_command", cfg.codebase_intelligence.mcp_command),
            mcp_args=ci.get("mcp_args", cfg.codebase_intelligence.mcp_args),
            database_path=str(ci.get("database_path", cfg.codebase_intelligence.database_path)),
            chroma_path=str(ci.get("chroma_path", cfg.codebase_intelligence.chroma_path)),
            graph_path=str(ci.get("graph_path", cfg.codebase_intelligence.graph_path)),
            replace_static_map=ci.get("replace_static_map", cfg.codebase_intelligence.replace_static_map),
            register_artifacts=ci.get("register_artifacts", cfg.codebase_intelligence.register_artifacts),
            server_root=str(ci.get("server_root", cfg.codebase_intelligence.server_root)),
            startup_timeout_ms=ci.get("startup_timeout_ms", cfg.codebase_intelligence.startup_timeout_ms),
            tool_timeout_ms=ci.get("tool_timeout_ms", cfg.codebase_intelligence.tool_timeout_ms),
        )
        # Validate startup_timeout_ms >= 1000
        if cfg.codebase_intelligence.startup_timeout_ms < 1000:
            raise ValueError(
                f"Invalid codebase_intelligence.startup_timeout_ms: {cfg.codebase_intelligence.startup_timeout_ms}. Must be >= 1000"
            )
        # Validate tool_timeout_ms >= 1000
        if cfg.codebase_intelligence.tool_timeout_ms < 1000:
            raise ValueError(
                f"Invalid codebase_intelligence.tool_timeout_ms: {cfg.codebase_intelligence.tool_timeout_ms}. Must be >= 1000"
            )

    if "enterprise_mode" in data and isinstance(data["enterprise_mode"], dict):
        em = data["enterprise_mode"]
        for key in ("enabled", "domain_agents", "parallel_review", "ownership_validation_gate", "scaffold_shared_files"):
            if key in em:
                user_overrides.add(f"enterprise_mode.{key}")
        cfg.enterprise_mode = EnterpriseModeConfig(
            enabled=em.get("enabled", cfg.enterprise_mode.enabled),
            multi_step_architecture=em.get("multi_step_architecture", cfg.enterprise_mode.multi_step_architecture),
            domain_agents=em.get("domain_agents", cfg.enterprise_mode.domain_agents),
            max_backend_devs=em.get("max_backend_devs", cfg.enterprise_mode.max_backend_devs),
            max_frontend_devs=em.get("max_frontend_devs", cfg.enterprise_mode.max_frontend_devs),
            max_infra_devs=em.get("max_infra_devs", cfg.enterprise_mode.max_infra_devs),
            parallel_review=em.get("parallel_review", cfg.enterprise_mode.parallel_review),
            wave_state_persistence=em.get("wave_state_persistence", cfg.enterprise_mode.wave_state_persistence),
            ownership_validation_gate=em.get("ownership_validation_gate", cfg.enterprise_mode.ownership_validation_gate),
            scaffold_shared_files=em.get("scaffold_shared_files", cfg.enterprise_mode.scaffold_shared_files),
            department_model=em.get("department_model", cfg.enterprise_mode.department_model),
        )

    # Department model YAML loading
    if "departments" in data and isinstance(data["departments"], dict):
        dept_data = data["departments"]
        for key in dept_data:
            user_overrides.add(f"departments.{key}")

        def _load_dept_cfg(d: dict, defaults: DepartmentConfig) -> DepartmentConfig:
            def _int_or(key: str, fallback: int) -> int:
                v = d.get(key, fallback)
                return int(v) if isinstance(v, (int, float)) else fallback

            return DepartmentConfig(
                enabled=bool(d.get("enabled", defaults.enabled)),
                max_managers=_int_or("max_managers", defaults.max_managers),
                max_workers_per_manager=_int_or("max_workers_per_manager", defaults.max_workers_per_manager),
                communication_timeout=_int_or("communication_timeout", defaults.communication_timeout),
                wave_timeout=_int_or("wave_timeout", defaults.wave_timeout),
            )

        coding_data = dept_data.get("coding", {})
        review_data = dept_data.get("review", {})
        cfg.departments = DepartmentsConfig(
            enabled=dept_data.get("enabled", cfg.departments.enabled),
            coding=_load_dept_cfg(coding_data, cfg.departments.coding) if isinstance(coding_data, dict) else cfg.departments.coding,
            review=_load_dept_cfg(review_data, cfg.departments.review) if isinstance(review_data, dict) else cfg.departments.review,
        )

    # Enterprise mode requires phase leads — enforce at config load time
    if cfg.enterprise_mode.enabled and not cfg.phase_leads.enabled:
        _logger.warning(
            "enterprise_mode.enabled=True requires phase_leads.enabled=True — "
            "forcing phase_leads.enabled=True"
        )
        cfg.phase_leads.enabled = True

    # Department model requires enterprise mode + agent teams
    if cfg.departments.enabled and not cfg.enterprise_mode.enabled:
        _logger.warning(
            "departments.enabled=True requires enterprise_mode.enabled=True — "
            "forcing departments.enabled=False"
        )
        cfg.departments.enabled = False
    if cfg.departments.enabled and not cfg.agent_teams.enabled:
        _logger.warning(
            "departments.enabled=True requires agent_teams.enabled=True — "
            "forcing departments.enabled=False"
        )
        cfg.departments.enabled = False

    if "contract_scans" in data and isinstance(data["contract_scans"], dict):
        cs = data["contract_scans"]
        for key in cs:
            user_overrides.add(f"contract_scans.{key}")
        cfg.contract_scans = ContractScanConfig(
            endpoint_schema_scan=cs.get("endpoint_schema_scan", cfg.contract_scans.endpoint_schema_scan),
            missing_endpoint_scan=cs.get("missing_endpoint_scan", cfg.contract_scans.missing_endpoint_scan),
            event_schema_scan=cs.get("event_schema_scan", cfg.contract_scans.event_schema_scan),
            shared_model_scan=cs.get("shared_model_scan", cfg.contract_scans.shared_model_scan),
        )

    if "agents" in data:
        for name, agent_data in data["agents"].items():
            if isinstance(agent_data, dict):
                cfg.agents[name] = AgentConfig(
                    model=agent_data.get("model", "opus"),
                    enabled=agent_data.get("enabled", True),
                )

    if "mcp_servers" in data:
        for name, server_data in data["mcp_servers"].items():
            if isinstance(server_data, dict):
                cfg.mcp_servers[name] = MCPServerConfig(
                    enabled=server_data.get("enabled", True),
                )

    if "display" in data:
        d = data["display"]
        cfg.display = DisplayConfig(
            show_cost=d.get("show_cost", cfg.display.show_cost),
            show_tools=d.get("show_tools", cfg.display.show_tools),
            show_fleet_composition=d.get("show_fleet_composition", cfg.display.show_fleet_composition),
            show_convergence_status=d.get("show_convergence_status", cfg.display.show_convergence_status),
            verbose=d.get("verbose", cfg.display.verbose),
        )

    # Gate enforcement (Feature #3)
    if "gate_enforcement" in data and isinstance(data["gate_enforcement"], dict):
        ge = data["gate_enforcement"]
        for key in ge:
            user_overrides.add(f"gate_enforcement.{key}")
        cfg.gate_enforcement = GateEnforcementConfig(
            enabled=ge.get("enabled", cfg.gate_enforcement.enabled),
            enforce_requirements=ge.get("enforce_requirements", cfg.gate_enforcement.enforce_requirements),
            enforce_architecture=ge.get("enforce_architecture", cfg.gate_enforcement.enforce_architecture),
            enforce_pseudocode=ge.get("enforce_pseudocode", cfg.gate_enforcement.enforce_pseudocode),
            enforce_review_count=ge.get("enforce_review_count", cfg.gate_enforcement.enforce_review_count),
            enforce_convergence=ge.get("enforce_convergence", cfg.gate_enforcement.enforce_convergence),
            enforce_truth_score=ge.get("enforce_truth_score", cfg.gate_enforcement.enforce_truth_score),
            enforce_e2e=ge.get("enforce_e2e", cfg.gate_enforcement.enforce_e2e),
            min_review_cycles=ge.get("min_review_cycles", cfg.gate_enforcement.min_review_cycles),
            truth_score_threshold=float(ge.get("truth_score_threshold", cfg.gate_enforcement.truth_score_threshold)),
            first_run_informational=ge.get("first_run_informational", cfg.gate_enforcement.first_run_informational),
        )

    # Auto-enable gate enforcement for pseudocode when pseudocode is enabled,
    # unless the user explicitly set enforce_pseudocode in their config.
    if cfg.pseudocode.enabled and "gate_enforcement.enforce_pseudocode" not in user_overrides:
        cfg.gate_enforcement.enforce_pseudocode = True

    # Hooks (Feature #4)
    if "hooks" in data and isinstance(data["hooks"], dict):
        hk = data["hooks"]
        for key in hk:
            user_overrides.add(f"hooks.{key}")
        cfg.hooks = HooksConfig(
            enabled=hk.get("enabled", cfg.hooks.enabled),
            pattern_memory=hk.get("pattern_memory", cfg.hooks.pattern_memory),
            capture_findings=hk.get("capture_findings", cfg.hooks.capture_findings),
            pre_build_retrieval=hk.get("pre_build_retrieval", cfg.hooks.pre_build_retrieval),
            max_similar_builds=hk.get("max_similar_builds", cfg.hooks.max_similar_builds),
            max_top_findings=hk.get("max_top_findings", cfg.hooks.max_top_findings),
            fix_recipes=hk.get("fix_recipes", cfg.hooks.fix_recipes),
        )

    # Routing (Feature #5)
    if "routing" in data and isinstance(data["routing"], dict):
        rt = data["routing"]
        for key in rt:
            user_overrides.add(f"routing.{key}")
        cfg.routing = RoutingConfig(
            enabled=rt.get("enabled", cfg.routing.enabled),
            tier1_confidence_threshold=float(rt.get("tier1_confidence_threshold", cfg.routing.tier1_confidence_threshold)),
            tier2_complexity_threshold=float(rt.get("tier2_complexity_threshold", cfg.routing.tier2_complexity_threshold)),
            tier3_complexity_threshold=float(rt.get("tier3_complexity_threshold", cfg.routing.tier3_complexity_threshold)),
            default_model=rt.get("default_model", cfg.routing.default_model),
            log_decisions=rt.get("log_decisions", cfg.routing.log_decisions),
        )

    def _coerce_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _coerce_int(value: Any, default: int) -> int:
        if isinstance(value, bool) or value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default

    def _coerce_float(value: Any, default: float) -> float:
        if isinstance(value, bool) or value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return default
        return default

    def _coerce_text(value: Any, default: str) -> str:
        if value is None:
            return default
        return str(value).strip()

    if "v18" in data and isinstance(data["v18"], dict):
        v18 = data["v18"]
        for key in v18:
            user_overrides.add(f"v18.{key}")
        cfg.v18 = V18Config(
            planner_mode=_coerce_text(v18.get("planner_mode", cfg.v18.planner_mode), cfg.v18.planner_mode),
            execution_mode=_coerce_text(v18.get("execution_mode", cfg.v18.execution_mode), cfg.v18.execution_mode),
            contract_mode=_coerce_text(v18.get("contract_mode", cfg.v18.contract_mode), cfg.v18.contract_mode),
            evidence_mode=_coerce_text(v18.get("evidence_mode", cfg.v18.evidence_mode), cfg.v18.evidence_mode),
            git_isolation=_coerce_bool(v18.get("git_isolation", cfg.v18.git_isolation), cfg.v18.git_isolation),
            live_endpoint_check=_coerce_bool(
                v18.get("live_endpoint_check", cfg.v18.live_endpoint_check),
                cfg.v18.live_endpoint_check,
            ),
            openapi_generation=_coerce_bool(
                v18.get("openapi_generation", cfg.v18.openapi_generation),
                cfg.v18.openapi_generation,
            ),
            scaffold_enabled=_coerce_bool(
                v18.get("scaffold_enabled", cfg.v18.scaffold_enabled),
                cfg.v18.scaffold_enabled,
            ),
            max_parallel_milestones=_coerce_int(
                v18.get("max_parallel_milestones", cfg.v18.max_parallel_milestones),
                cfg.v18.max_parallel_milestones,
            ),
            wave_d5_enabled=_coerce_bool(
                v18.get("wave_d5_enabled", cfg.v18.wave_d5_enabled),
                cfg.v18.wave_d5_enabled,
            ),
            wave_idle_timeout_seconds=_coerce_int(
                v18.get("wave_idle_timeout_seconds", cfg.v18.wave_idle_timeout_seconds),
                cfg.v18.wave_idle_timeout_seconds,
            ),
            orphan_tool_idle_timeout_seconds=_coerce_int(
                v18.get(
                    "orphan_tool_idle_timeout_seconds",
                    cfg.v18.orphan_tool_idle_timeout_seconds,
                ),
                cfg.v18.orphan_tool_idle_timeout_seconds,
            ),
            wave_watchdog_poll_seconds=_coerce_int(
                v18.get("wave_watchdog_poll_seconds", cfg.v18.wave_watchdog_poll_seconds),
                cfg.v18.wave_watchdog_poll_seconds,
            ),
            wave_watchdog_max_retries=_coerce_int(
                v18.get("wave_watchdog_max_retries", cfg.v18.wave_watchdog_max_retries),
                cfg.v18.wave_watchdog_max_retries,
            ),
            sub_agent_idle_timeout_seconds=_coerce_int(
                v18.get("sub_agent_idle_timeout_seconds", cfg.v18.sub_agent_idle_timeout_seconds),
                cfg.v18.sub_agent_idle_timeout_seconds,
            ),
            wave_t_enabled=_coerce_bool(
                v18.get("wave_t_enabled", cfg.v18.wave_t_enabled),
                cfg.v18.wave_t_enabled,
            ),
            wave_t_max_fix_iterations=_coerce_int(
                v18.get("wave_t_max_fix_iterations", cfg.v18.wave_t_max_fix_iterations),
                cfg.v18.wave_t_max_fix_iterations,
            ),
            # Phase G Slice 1a/1c/1d — YAML user overrides wired through.
            claude_md_setting_sources_enabled=_coerce_bool(
                v18.get(
                    "claude_md_setting_sources_enabled",
                    cfg.v18.claude_md_setting_sources_enabled,
                ),
                cfg.v18.claude_md_setting_sources_enabled,
            ),
            architecture_md_enabled=_coerce_bool(
                v18.get("architecture_md_enabled", cfg.v18.architecture_md_enabled),
                cfg.v18.architecture_md_enabled,
            ),
            architecture_md_max_lines=_coerce_int(
                v18.get(
                    "architecture_md_max_lines", cfg.v18.architecture_md_max_lines
                ),
                cfg.v18.architecture_md_max_lines,
            ),
            architecture_md_summarize_floor=_coerce_int(
                v18.get(
                    "architecture_md_summarize_floor",
                    cfg.v18.architecture_md_summarize_floor,
                ),
                cfg.v18.architecture_md_summarize_floor,
            ),
            auditor_architecture_injection_enabled=_coerce_bool(
                v18.get(
                    "auditor_architecture_injection_enabled",
                    cfg.v18.auditor_architecture_injection_enabled,
                ),
                cfg.v18.auditor_architecture_injection_enabled,
            ),
            claude_md_autogenerate=_coerce_bool(
                v18.get("claude_md_autogenerate", cfg.v18.claude_md_autogenerate),
                cfg.v18.claude_md_autogenerate,
            ),
            agents_md_autogenerate=_coerce_bool(
                v18.get("agents_md_autogenerate", cfg.v18.agents_md_autogenerate),
                cfg.v18.agents_md_autogenerate,
            ),
            agents_md_max_bytes=_coerce_int(
                v18.get("agents_md_max_bytes", cfg.v18.agents_md_max_bytes),
                cfg.v18.agents_md_max_bytes,
            ),
            # Provider routing fields
            provider_routing=_coerce_bool(
                v18.get("provider_routing", cfg.v18.provider_routing),
                cfg.v18.provider_routing,
            ),
            codex_model=_coerce_text(v18.get("codex_model", cfg.v18.codex_model), cfg.v18.codex_model),
            codex_timeout_seconds=_coerce_int(
                v18.get("codex_timeout_seconds", cfg.v18.codex_timeout_seconds),
                cfg.v18.codex_timeout_seconds,
            ),
            codex_max_retries=_coerce_int(
                v18.get("codex_max_retries", cfg.v18.codex_max_retries),
                cfg.v18.codex_max_retries,
            ),
            codex_reasoning_effort=_coerce_text(
                v18.get("codex_reasoning_effort", cfg.v18.codex_reasoning_effort),
                cfg.v18.codex_reasoning_effort,
            ).lower(),
            codex_web_search=_coerce_text(
                v18.get("codex_web_search", cfg.v18.codex_web_search),
                cfg.v18.codex_web_search,
            ).lower(),
            codex_context7_enabled=_coerce_bool(
                v18.get("codex_context7_enabled", cfg.v18.codex_context7_enabled),
                cfg.v18.codex_context7_enabled,
            ),
            provider_map_b=_coerce_text(v18.get("provider_map_b", cfg.v18.provider_map_b), cfg.v18.provider_map_b).lower(),
            provider_map_d=_coerce_text(v18.get("provider_map_d", cfg.v18.provider_map_d), cfg.v18.provider_map_d).lower(),
            provider_map_a5=_coerce_text(
                v18.get("provider_map_a5", cfg.v18.provider_map_a5),
                cfg.v18.provider_map_a5,
            ).lower(),
            provider_map_t5=_coerce_text(
                v18.get("provider_map_t5", cfg.v18.provider_map_t5),
                cfg.v18.provider_map_t5,
            ).lower(),
            wave_d_merged_enabled=_coerce_bool(
                v18.get("wave_d_merged_enabled", cfg.v18.wave_d_merged_enabled),
                cfg.v18.wave_d_merged_enabled,
            ),
            wave_d_compile_fix_max_attempts=int(
                v18.get(
                    "wave_d_compile_fix_max_attempts",
                    cfg.v18.wave_d_compile_fix_max_attempts,
                )
                or cfg.v18.wave_d_compile_fix_max_attempts
            ),
            ui_design_tokens_enabled=_coerce_bool(
                v18.get("ui_design_tokens_enabled", cfg.v18.ui_design_tokens_enabled),
                cfg.v18.ui_design_tokens_enabled,
            ),
            ui_reference_path=_coerce_text(
                v18.get("ui_reference_path", cfg.v18.ui_reference_path),
                cfg.v18.ui_reference_path,
            ),
            milestone_scope_enforcement=_coerce_bool(
                v18.get(
                    "milestone_scope_enforcement",
                    cfg.v18.milestone_scope_enforcement,
                ),
                cfg.v18.milestone_scope_enforcement,
            ),
            audit_milestone_scoping=_coerce_bool(
                v18.get("audit_milestone_scoping", cfg.v18.audit_milestone_scoping),
                cfg.v18.audit_milestone_scoping,
            ),
            ownership_contract_enabled=_coerce_bool(
                v18.get(
                    "ownership_contract_enabled",
                    cfg.v18.ownership_contract_enabled,
                ),
                cfg.v18.ownership_contract_enabled,
            ),
            ownership_policy_required=_coerce_bool(
                v18.get(
                    "ownership_policy_required",
                    cfg.v18.ownership_policy_required,
                ),
                cfg.v18.ownership_policy_required,
            ),
            codex_capture_enabled=_coerce_bool(
                v18.get(
                    "codex_capture_enabled",
                    cfg.v18.codex_capture_enabled,
                ),
                cfg.v18.codex_capture_enabled,
            ),
            codex_wave_b_prompt_hardening_enabled=_coerce_bool(
                v18.get(
                    "codex_wave_b_prompt_hardening_enabled",
                    cfg.v18.codex_wave_b_prompt_hardening_enabled,
                ),
                cfg.v18.codex_wave_b_prompt_hardening_enabled,
            ),
            codex_sandbox_writable_enabled=_coerce_bool(
                v18.get(
                    "codex_sandbox_writable_enabled",
                    cfg.v18.codex_sandbox_writable_enabled,
                ),
                cfg.v18.codex_sandbox_writable_enabled,
            ),
            codex_sandbox_mode=_coerce_text(
                v18.get("codex_sandbox_mode", cfg.v18.codex_sandbox_mode),
                cfg.v18.codex_sandbox_mode,
            ),
            codex_turn_interrupt_message_refined_enabled=_coerce_bool(
                v18.get(
                    "codex_turn_interrupt_message_refined_enabled",
                    cfg.v18.codex_turn_interrupt_message_refined_enabled,
                ),
                cfg.v18.codex_turn_interrupt_message_refined_enabled,
            ),
            codex_app_server_teardown_enabled=_coerce_bool(
                v18.get(
                    "codex_app_server_teardown_enabled",
                    cfg.v18.codex_app_server_teardown_enabled,
                ),
                cfg.v18.codex_app_server_teardown_enabled,
            ),
            state_finalize_invariant_enforcement_enabled=_coerce_bool(
                v18.get(
                    "state_finalize_invariant_enforcement_enabled",
                    cfg.v18.state_finalize_invariant_enforcement_enabled,
                ),
                cfg.v18.state_finalize_invariant_enforcement_enabled,
            ),
            codex_cwd_propagation_check_enabled=_coerce_bool(
                v18.get(
                    "codex_cwd_propagation_check_enabled",
                    cfg.v18.codex_cwd_propagation_check_enabled,
                ),
                cfg.v18.codex_cwd_propagation_check_enabled,
            ),
            codex_flush_wait_enabled=_coerce_bool(
                v18.get(
                    "codex_flush_wait_enabled",
                    cfg.v18.codex_flush_wait_enabled,
                ),
                cfg.v18.codex_flush_wait_enabled,
            ),
            codex_flush_wait_seconds=_coerce_float(
                v18.get(
                    "codex_flush_wait_seconds",
                    cfg.v18.codex_flush_wait_seconds,
                ),
                cfg.v18.codex_flush_wait_seconds,
            ),
            checkpoint_tracker_hardening_enabled=_coerce_bool(
                v18.get(
                    "checkpoint_tracker_hardening_enabled",
                    cfg.v18.checkpoint_tracker_hardening_enabled,
                ),
                cfg.v18.checkpoint_tracker_hardening_enabled,
            ),
            codex_blocked_prefix_as_failure_enabled=_coerce_bool(
                v18.get(
                    "codex_blocked_prefix_as_failure_enabled",
                    cfg.v18.codex_blocked_prefix_as_failure_enabled,
                ),
                cfg.v18.codex_blocked_prefix_as_failure_enabled,
            ),
            spec_reconciliation_enabled=_coerce_bool(
                v18.get(
                    "spec_reconciliation_enabled",
                    cfg.v18.spec_reconciliation_enabled,
                ),
                cfg.v18.spec_reconciliation_enabled,
            ),
            scaffold_verifier_enabled=_coerce_bool(
                v18.get(
                    "scaffold_verifier_enabled",
                    cfg.v18.scaffold_verifier_enabled,
                ),
                cfg.v18.scaffold_verifier_enabled,
            ),
            m1_startup_probe=_coerce_bool(
                v18.get("m1_startup_probe", cfg.v18.m1_startup_probe),
                cfg.v18.m1_startup_probe,
            ),
            review_fleet_enforcement=_coerce_bool(
                v18.get(
                    "review_fleet_enforcement",
                    cfg.v18.review_fleet_enforcement,
                ),
                cfg.v18.review_fleet_enforcement,
            ),
            codex_fix_routing_enabled=_coerce_bool(
                v18.get(
                    "codex_fix_routing_enabled",
                    cfg.v18.codex_fix_routing_enabled,
                ),
                cfg.v18.codex_fix_routing_enabled,
            ),
            codex_fix_timeout_seconds=int(
                v18.get(
                    "codex_fix_timeout_seconds",
                    cfg.v18.codex_fix_timeout_seconds,
                )
                or cfg.v18.codex_fix_timeout_seconds
            ),
            codex_fix_reasoning_effort=str(
                v18.get(
                    "codex_fix_reasoning_effort",
                    cfg.v18.codex_fix_reasoning_effort,
                )
                or cfg.v18.codex_fix_reasoning_effort
            ),
            compile_fix_codex_enabled=_coerce_bool(
                v18.get(
                    "compile_fix_codex_enabled",
                    cfg.v18.compile_fix_codex_enabled,
                ),
                cfg.v18.compile_fix_codex_enabled,
            ),
            wave_a5_enabled=_coerce_bool(
                v18.get("wave_a5_enabled", cfg.v18.wave_a5_enabled),
                cfg.v18.wave_a5_enabled,
            ),
            wave_a5_reasoning_effort=str(
                v18.get("wave_a5_reasoning_effort", cfg.v18.wave_a5_reasoning_effort)
                or cfg.v18.wave_a5_reasoning_effort
            ),
            wave_a5_max_reruns=_coerce_int(
                v18.get("wave_a5_max_reruns", cfg.v18.wave_a5_max_reruns),
                cfg.v18.wave_a5_max_reruns,
            ),
            wave_a5_skip_simple_milestones=_coerce_bool(
                v18.get(
                    "wave_a5_skip_simple_milestones",
                    cfg.v18.wave_a5_skip_simple_milestones,
                ),
                cfg.v18.wave_a5_skip_simple_milestones,
            ),
            wave_a5_simple_entity_threshold=_coerce_int(
                v18.get(
                    "wave_a5_simple_entity_threshold",
                    cfg.v18.wave_a5_simple_entity_threshold,
                ),
                cfg.v18.wave_a5_simple_entity_threshold,
            ),
            wave_a5_simple_ac_threshold=_coerce_int(
                v18.get(
                    "wave_a5_simple_ac_threshold",
                    cfg.v18.wave_a5_simple_ac_threshold,
                ),
                cfg.v18.wave_a5_simple_ac_threshold,
            ),
            wave_a5_gate_enforcement=_coerce_bool(
                v18.get(
                    "wave_a5_gate_enforcement",
                    cfg.v18.wave_a5_gate_enforcement,
                ),
                cfg.v18.wave_a5_gate_enforcement,
            ),
            wave_a_schema_enforcement_enabled=_coerce_bool(
                v18.get(
                    "wave_a_schema_enforcement_enabled",
                    cfg.v18.wave_a_schema_enforcement_enabled,
                ),
                cfg.v18.wave_a_schema_enforcement_enabled,
            ),
            wave_a_rerun_budget=_coerce_int(
                v18.get(
                    "wave_a_rerun_budget",
                    cfg.v18.wave_a_rerun_budget,
                ),
                cfg.v18.wave_a_rerun_budget,
            ),
            recovery_wave_redispatch_enabled=_coerce_bool(
                v18.get(
                    "recovery_wave_redispatch_enabled",
                    cfg.v18.recovery_wave_redispatch_enabled,
                ),
                cfg.v18.recovery_wave_redispatch_enabled,
            ),
            recovery_wave_redispatch_max_attempts=_coerce_int(
                v18.get(
                    "recovery_wave_redispatch_max_attempts",
                    cfg.v18.recovery_wave_redispatch_max_attempts,
                ),
                cfg.v18.recovery_wave_redispatch_max_attempts,
            ),
            wave_a_contract_injection_enabled=_coerce_bool(
                v18.get(
                    "wave_a_contract_injection_enabled",
                    cfg.v18.wave_a_contract_injection_enabled,
                ),
                cfg.v18.wave_a_contract_injection_enabled,
            ),
            wave_a_contract_verifier_enabled=_coerce_bool(
                v18.get(
                    "wave_a_contract_verifier_enabled",
                    cfg.v18.wave_a_contract_verifier_enabled,
                ),
                cfg.v18.wave_a_contract_verifier_enabled,
            ),
            wave_a_ownership_enforcement_enabled=_coerce_bool(
                v18.get(
                    "wave_a_ownership_enforcement_enabled",
                    cfg.v18.wave_a_ownership_enforcement_enabled,
                ),
                cfg.v18.wave_a_ownership_enforcement_enabled,
            ),
            wave_a_ownership_contract_injection_enabled=_coerce_bool(
                v18.get(
                    "wave_a_ownership_contract_injection_enabled",
                    cfg.v18.wave_a_ownership_contract_injection_enabled,
                ),
                cfg.v18.wave_a_ownership_contract_injection_enabled,
            ),
            wave_t5_enabled=_coerce_bool(
                v18.get("wave_t5_enabled", cfg.v18.wave_t5_enabled),
                cfg.v18.wave_t5_enabled,
            ),
            wave_t5_reasoning_effort=str(
                v18.get("wave_t5_reasoning_effort", cfg.v18.wave_t5_reasoning_effort)
                or cfg.v18.wave_t5_reasoning_effort
            ),
            wave_t5_skip_if_no_tests=_coerce_bool(
                v18.get(
                    "wave_t5_skip_if_no_tests",
                    cfg.v18.wave_t5_skip_if_no_tests,
                ),
                cfg.v18.wave_t5_skip_if_no_tests,
            ),
            wave_t5_gate_enforcement=_coerce_bool(
                v18.get(
                    "wave_t5_gate_enforcement",
                    cfg.v18.wave_t5_gate_enforcement,
                ),
                cfg.v18.wave_t5_gate_enforcement,
            ),
            mcp_doc_context_wave_a_enabled=_coerce_bool(
                v18.get(
                    "mcp_doc_context_wave_a_enabled",
                    cfg.v18.mcp_doc_context_wave_a_enabled,
                ),
                cfg.v18.mcp_doc_context_wave_a_enabled,
            ),
            mcp_doc_context_wave_t_enabled=_coerce_bool(
                v18.get(
                    "mcp_doc_context_wave_t_enabled",
                    cfg.v18.mcp_doc_context_wave_t_enabled,
                ),
                cfg.v18.mcp_doc_context_wave_t_enabled,
            ),
            wave_t5_gap_list_inject_wave_e=_coerce_bool(
                v18.get(
                    "wave_t5_gap_list_inject_wave_e",
                    cfg.v18.wave_t5_gap_list_inject_wave_e,
                ),
                cfg.v18.wave_t5_gap_list_inject_wave_e,
            ),
            wave_t5_gap_list_inject_test_auditor=_coerce_bool(
                v18.get(
                    "wave_t5_gap_list_inject_test_auditor",
                    cfg.v18.wave_t5_gap_list_inject_test_auditor,
                ),
                cfg.v18.wave_t5_gap_list_inject_test_auditor,
            ),
            cascade_consolidation_enabled=_coerce_bool(
                v18.get(
                    "cascade_consolidation_enabled",
                    cfg.v18.cascade_consolidation_enabled,
                ),
                cfg.v18.cascade_consolidation_enabled,
            ),
            duplicate_prisma_cleanup_enabled=_coerce_bool(
                v18.get(
                    "duplicate_prisma_cleanup_enabled",
                    cfg.v18.duplicate_prisma_cleanup_enabled,
                ),
                cfg.v18.duplicate_prisma_cleanup_enabled,
            ),
            template_version_stamping_enabled=_coerce_bool(
                v18.get(
                    "template_version_stamping_enabled",
                    cfg.v18.template_version_stamping_enabled,
                ),
                cfg.v18.template_version_stamping_enabled,
            ),
            scaffold_web_dockerfile_context_fix_enabled=_coerce_bool(
                v18.get(
                    "scaffold_web_dockerfile_context_fix_enabled",
                    cfg.v18.scaffold_web_dockerfile_context_fix_enabled,
                ),
                cfg.v18.scaffold_web_dockerfile_context_fix_enabled,
            ),
            content_scope_scanner_enabled=_coerce_bool(
                v18.get(
                    "content_scope_scanner_enabled",
                    cfg.v18.content_scope_scanner_enabled,
                ),
                cfg.v18.content_scope_scanner_enabled,
            ),
            mcp_informed_dispatches_enabled=_coerce_bool(
                v18.get(
                    "mcp_informed_dispatches_enabled",
                    cfg.v18.mcp_informed_dispatches_enabled,
                ),
                cfg.v18.mcp_informed_dispatches_enabled,
            ),
            codex_transport_mode=_coerce_text(
                v18.get(
                    "codex_transport_mode",
                    cfg.v18.codex_transport_mode,
                ),
                cfg.v18.codex_transport_mode,
            ),
            codex_orphan_tool_timeout_seconds=_coerce_int(
                v18.get(
                    "codex_orphan_tool_timeout_seconds",
                    cfg.v18.codex_orphan_tool_timeout_seconds,
                ),
                cfg.v18.codex_orphan_tool_timeout_seconds,
            ),
            audit_fix_iteration_enabled=_coerce_bool(
                v18.get(
                    "audit_fix_iteration_enabled",
                    cfg.v18.audit_fix_iteration_enabled,
                ),
                cfg.v18.audit_fix_iteration_enabled,
            ),
            audit_scope_completeness_enabled=_coerce_bool(
                v18.get(
                    "audit_scope_completeness_enabled",
                    cfg.v18.audit_scope_completeness_enabled,
                ),
                cfg.v18.audit_scope_completeness_enabled,
            ),
            confidence_banners_enabled=_coerce_bool(
                v18.get(
                    "confidence_banners_enabled",
                    cfg.v18.confidence_banners_enabled,
                ),
                cfg.v18.confidence_banners_enabled,
            ),
            runtime_infra_detection_enabled=_coerce_bool(
                v18.get(
                    "runtime_infra_detection_enabled",
                    cfg.v18.runtime_infra_detection_enabled,
                ),
                cfg.v18.runtime_infra_detection_enabled,
            ),
            wave_b_output_sanitization_enabled=_coerce_bool(
                v18.get(
                    "wave_b_output_sanitization_enabled",
                    cfg.v18.wave_b_output_sanitization_enabled,
                ),
                cfg.v18.wave_b_output_sanitization_enabled,
            ),
            scaffold_verifier_scope_aware=_coerce_bool(
                v18.get(
                    "scaffold_verifier_scope_aware",
                    cfg.v18.scaffold_verifier_scope_aware,
                ),
                cfg.v18.scaffold_verifier_scope_aware,
            ),
            probe_spec_oracle_enabled=_coerce_bool(
                v18.get(
                    "probe_spec_oracle_enabled",
                    cfg.v18.probe_spec_oracle_enabled,
                ),
                cfg.v18.probe_spec_oracle_enabled,
            ),
            runtime_tautology_guard_enabled=_coerce_bool(
                v18.get(
                    "runtime_tautology_guard_enabled",
                    cfg.v18.runtime_tautology_guard_enabled,
                ),
                cfg.v18.runtime_tautology_guard_enabled,
            ),
            runtime_verifier_refresh_enabled=_coerce_bool(
                v18.get(
                    "runtime_verifier_refresh_enabled",
                    cfg.v18.runtime_verifier_refresh_enabled,
                ),
                cfg.v18.runtime_verifier_refresh_enabled,
            ),
            runtime_verifier_refresh_attempts=_coerce_int(
                v18.get(
                    "runtime_verifier_refresh_attempts",
                    cfg.v18.runtime_verifier_refresh_attempts,
                ),
                cfg.v18.runtime_verifier_refresh_attempts,
            ),
            runtime_verifier_refresh_interval_seconds=_coerce_float(
                v18.get(
                    "runtime_verifier_refresh_interval_seconds",
                    cfg.v18.runtime_verifier_refresh_interval_seconds,
                ),
                cfg.v18.runtime_verifier_refresh_interval_seconds,
            ),
            reaudit_trigger_fix_enabled=_coerce_bool(
                v18.get(
                    "reaudit_trigger_fix_enabled",
                    cfg.v18.reaudit_trigger_fix_enabled,
                ),
                cfg.v18.reaudit_trigger_fix_enabled,
            ),
            dod_feasibility_verifier_enabled=_coerce_bool(
                v18.get(
                    "dod_feasibility_verifier_enabled",
                    cfg.v18.dod_feasibility_verifier_enabled,
                ),
                cfg.v18.dod_feasibility_verifier_enabled,
            ),
            ownership_enforcement_enabled=_coerce_bool(
                v18.get(
                    "ownership_enforcement_enabled",
                    cfg.v18.ownership_enforcement_enabled,
                ),
                cfg.v18.ownership_enforcement_enabled,
            ),
        )

    return cfg, user_overrides


def load_config(
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> tuple[AgentTeamConfig, set[str]]:
    """Load configuration from YAML files with CLI overrides.

    Search order:
    1. Explicit config_path (if provided)
    2. ./config.yaml (cwd)
    3. ~/.agent-team/config.yaml (user home fallback)
    4. Built-in defaults

    Returns:
        Tuple of (config, user_overrides) where user_overrides tracks which
        depth-gatable keys were explicitly set by the user.
    """
    raw: dict[str, Any] = {}

    search_paths: list[Path] = []
    if config_path:
        search_paths.append(Path(config_path))
    search_paths.append(Path.cwd() / "config.yaml")
    search_paths.append(Path.home() / ".agent-team" / "config.yaml")

    for path in search_paths:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                # Security: yaml.safe_load restricts deserialization to safe
                # Python types (str, int, float, bool, list, dict, None).
                # Never use yaml.load() or yaml.unsafe_load() here -- they
                # can instantiate arbitrary Python objects from YAML tags.
                loaded = yaml.safe_load(f) or {}
            raw = _deep_merge(raw, loaded)
            break  # Use first found file

    # Apply CLI overrides
    if cli_overrides:
        raw = _deep_merge(raw, cli_overrides)

    return _dict_to_config(raw)
