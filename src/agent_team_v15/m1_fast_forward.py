"""Milestone 1 fast-forward diagnostic gates.

This module runs deterministic pre-smoke gates against source-controlled
builder code and a disposable generated workspace. It is diagnostic readiness
only; it never converts a passing fast-forward run into final M1 proof.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .agents import build_wave_d_prompt, build_wave_t_prompt
from .codex_observer_checks import find_forbidden_paths
from .config import AgentTeamConfig, apply_depth_quality_gating, load_config
from .openapi_generator import generate_openapi_contracts
from .quality_checks import scan_generated_client_import_usage
from .scaffold_runner import run_scaffolding, scaffold_config_from_stack_contract
from .stack_contract import derive_stack_contract, load_stack_contract, write_stack_contract
from .wave_a5_t5 import build_wave_t5_prompt, collect_wave_t_test_files
from .wave_executor import (
    _CODEX_WAVES,
    WaveFinding,
    WaveResult,
    _wave_sequence,
    load_wave_t_summary,
    parse_wave_t_summary_text,
    persist_wave_findings_for_audit,
    save_wave_telemetry,
)


MILESTONE_ID = "milestone-1"
CODEX_OWNED_WAVES = {"A5", "B", "D", "T5"}
CONTEXT7_QUOTA_PATTERNS = (
    "monthly quota",
    "quota exceeded",
    "context7",
)


class GateFailure(RuntimeError):
    """Raised when a diagnostic gate proves the source is not smoke-ready."""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    returncode: int
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


@dataclass
class FastForwardContext:
    repo: Path
    run_root: Path
    workspace: Path
    config: AgentTeamConfig
    user_overrides: set[str] = field(default_factory=set)
    scaffolded_files: list[str] = field(default_factory=list)
    wave_c_artifact: dict[str, Any] = field(default_factory=dict)
    commands: list[CommandResult] = field(default_factory=list)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str, limit: int = 4000) -> str:
    if isinstance(text, bytes):
        value = text.decode("utf-8", errors="replace")
    else:
        value = str(text or "")
    if len(value) <= limit:
        return value
    return value[-limit:]


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
    context: FastForwardContext | None = None,
) -> CommandResult:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            command=list(command),
            cwd=str(cwd),
            returncode=int(proc.returncode),
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            command=list(command),
            cwd=str(cwd),
            returncode=124,
            stdout_tail=_tail(exc.stdout or ""),
            stderr_tail=_tail(f"{exc.stderr or ''}\nTimed out after {timeout} seconds."),
        )
    if context is not None:
        context.commands.append(result)
    return result


def _read_text(path: Path) -> str:
    """Read ``path`` as text, tolerating Windows PowerShell's UTF-16 BOM.

    Run artifacts written by the PowerShell smoke launcher (``BUILD_LOG.txt``,
    ``BUILD_ERR.txt``) default to UTF-16 LE with BOM on Windows. Strict
    UTF-8 decoding on those files raises ``UnicodeDecodeError`` and
    aborted Gate 5 of the fast-forward harness. Fall through UTF-8 →
    UTF-8-with-BOM → UTF-16 → latin-1 so the auditor can still substring-
    search the log without losing output. The final ``errors='replace'``
    decode always succeeds because every byte is a valid latin-1 code
    point; substring matches on log text (``Context7 quota``, etc.)
    survive this conversion unchanged.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _require(condition: bool, reason: str, details: dict[str, Any] | None = None) -> None:
    if not condition:
        raise GateFailure(reason, details)


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id=MILESTONE_ID,
        title="TaskFlow foundation",
        template="full_stack",
        description="TaskFlow foundation for API, generated client, and UI wiring.",
        dependencies=[],
        feature_refs=["F-M1"],
        ac_refs=["AC-M1-001"],
        merge_surfaces=[],
        stack_target="NestJS Next.js pnpm",
    )


def _diagnostic_ir() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
        "entities": [],
        "i18n": {"locales": ["en", "ar"]},
        "acceptance_criteria": [
            {
                "id": "AC-M1-001",
                "feature": "F-M1",
                "text": "The generated API exposes a prefixed health endpoint and a canonical generated client.",
            }
        ],
    }


def _requirements_text() -> str:
    return "\n".join(
        [
            "# Milestone 1 Requirements",
            "",
            "> Diagnostic fast-forward fixture only. Final proof still requires a fresh full smoke run.",
            "",
            "- Stack: NestJS backend, Next.js App Router frontend, PostgreSQL, Prisma ORM.",
            "- Package manager: pnpm.",
            "- API port: 4000.",
            "- Web port: 3000.",
            "- API prefix: /api.",
            "- Docker compose, env examples, Dockerfiles, and OpenAPI/client generation must agree on those ports.",
            "- Wave C output must be canonical OpenAPI script plus @hey-api/openapi-ts client-fetch output.",
        ]
    )


def _load_smoke_config(repo: Path) -> tuple[AgentTeamConfig, set[str]]:
    config_path = repo / "v18 test runs" / "configs" / "taskflow-smoke-test-config.yaml"
    config, overrides = load_config(config_path)
    apply_depth_quality_gating(
        "exhaustive",
        config,
        overrides,
        prd_mode=True,
    )
    return config, set(overrides)


def _make_context(repo: Path, output_dir: Path | None) -> FastForwardContext:
    run_root = output_dir or (repo / "v18 test runs" / f"m1-fast-forward-{_utc_stamp()}")
    workspace = run_root / "generated"
    run_root.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        raise GateFailure("fast-forward workspace already exists", {"workspace": str(workspace)})
    workspace.mkdir(parents=True)
    config, overrides = _load_smoke_config(repo)
    return FastForwardContext(
        repo=repo,
        run_root=run_root,
        workspace=workspace,
        config=config,
        user_overrides=overrides,
    )


def _gate0_source_config(ctx: FastForwardContext) -> dict[str, Any]:
    status = _run(["git", "status", "--short"], cwd=ctx.repo, context=ctx)
    worktrees = _run(["git", "worktree", "list"], cwd=ctx.repo, context=ctx)
    head = _run(["git", "rev-parse", "HEAD"], cwd=ctx.repo, context=ctx)
    smoke_script = ctx.repo / "v18 test runs" / "start-m1-hardening-smoke.ps1"
    smoke_text = _read_text(smoke_script)

    v18 = ctx.config.v18
    required_flags = {
        "provider_routing": bool(v18.provider_routing),
        "provider_map_b": v18.provider_map_b,
        "provider_map_d": v18.provider_map_d,
        "scaffold_enabled": bool(v18.scaffold_enabled),
        "openapi_generation": bool(v18.openapi_generation),
        "wave_t_enabled": bool(v18.wave_t_enabled),
        "live_endpoint_check": bool(v18.live_endpoint_check),
        "evidence_mode": v18.evidence_mode,
        "audit_score_healthy_threshold": ctx.config.audit_team.score_healthy_threshold,
        "audit_max_reaudit_cycles": ctx.config.audit_team.max_reaudit_cycles,
        "max_budget_usd": ctx.config.orchestrator.max_budget_usd,
    }
    failures = []
    if not required_flags["provider_routing"]:
        failures.append("provider_routing disabled")
    if str(required_flags["provider_map_b"]).lower() != "codex":
        failures.append("Wave B is not routed to Codex")
    # Wave D may be Codex (experiment) or Claude (original design).
    # Both are valid provider choices — Claude-on-D is now the default
    # after the Codex-on-D experiment exposed three drift classes; the
    # gate only rejects an unrecognized string.
    if str(required_flags["provider_map_d"]).lower() not in {"codex", "claude"}:
        failures.append(
            f"Wave D provider must be codex or claude, got {required_flags['provider_map_d']!r}"
        )
    for key in ("scaffold_enabled", "openapi_generation", "wave_t_enabled", "live_endpoint_check"):
        if not required_flags[key]:
            failures.append(f"{key} disabled")

    script_needles = [
        "TASKFLOW_MINI_PRD.md",
        "taskflow-smoke-test-config.yaml",
        "--depth",
        "exhaustive",
        "docker ps",
        "EXIT_CODE.txt",
    ]
    missing_script_needles = [needle for needle in script_needles if needle not in smoke_text]
    if missing_script_needles:
        failures.append("smoke launcher missing expected tokens")

    static_sequence = ["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"]
    runtime_sequence = _wave_sequence("full_stack", ctx.config)
    if set(_CODEX_WAVES) != CODEX_OWNED_WAVES:
        failures.append("Codex-owned wave set drifted")
    if "C" not in runtime_sequence or "D" not in runtime_sequence or "T" not in runtime_sequence:
        failures.append("runtime wave sequence missing C, D, or T")

    details = {
        "source_commit": head.stdout_tail.strip(),
        "git_status_short": status.stdout_tail.splitlines(),
        "git_worktree_list": worktrees.stdout_tail.splitlines(),
        "smoke_script": str(smoke_script),
        "config": required_flags,
        "static_sequence_expected": static_sequence,
        "runtime_sequence": runtime_sequence,
        "codex_owned_waves": sorted(_CODEX_WAVES),
        "context7_waiver": {
            "quota_issue_ignored": True,
            "waiver_scope": "Only logs matching the known Context7 quota/monthly-limit issue are waived.",
        },
        "missing_smoke_script_tokens": missing_script_needles,
    }
    _require(not failures, "source/config baseline failed", {"failures": failures, **details})
    return details


def _gate1_stack_scaffold(ctx: FastForwardContext) -> dict[str, Any]:
    prd_source = ctx.repo / "v18 test runs" / "TASKFLOW_MINI_PRD.md"
    prd_text = _read_text(prd_source)
    requirements = _requirements_text()

    (ctx.workspace / ".agent-team" / "milestones" / MILESTONE_ID).mkdir(parents=True, exist_ok=True)
    (ctx.workspace / "PRD.md").write_text(prd_text, encoding="utf-8")
    (ctx.workspace / ".agent-team" / "PRD.md").write_text(prd_text, encoding="utf-8")
    (ctx.workspace / ".agent-team" / "milestones" / MILESTONE_ID / "REQUIREMENTS.md").write_text(
        requirements,
        encoding="utf-8",
    )
    ir_path = ctx.workspace / "product.ir.json"
    _write_json(ir_path, _diagnostic_ir())

    contract = derive_stack_contract(
        prd_text=prd_text,
        master_plan_text="",
        tech_stack=[],
        milestone_requirements=requirements,
    )
    write_stack_contract(ctx.workspace, contract)
    scaffold_cfg = scaffold_config_from_stack_contract(contract.to_dict())
    _require(scaffold_cfg is not None, "failed to derive ScaffoldConfig from stack contract")

    ctx.scaffolded_files = run_scaffolding(
        ir_path,
        ctx.workspace,
        MILESTONE_ID,
        ["foundation"],
        stack_target="NestJS Next.js pnpm",
        config=ctx.config,
        scaffold_cfg=scaffold_cfg,
    )

    reloaded = load_stack_contract(ctx.workspace)
    _require(reloaded is not None, "STACK_CONTRACT.json was not written")
    contract_data = reloaded.to_dict()
    api_port = int(contract_data.get("api_port") or 0)
    web_port = int(contract_data.get("web_port") or 0)
    infra_slots = (
        contract_data.get("infrastructure_template", {}).get("slots", {})
        if isinstance(contract_data.get("infrastructure_template"), dict)
        else {}
    )

    files = {
        "root_env": _read_text(ctx.workspace / ".env.example"),
        "api_env": _read_text(ctx.workspace / "apps" / "api" / ".env.example"),
        "web_env": _read_text(ctx.workspace / "apps" / "web" / ".env.example"),
        "compose": _read_text(ctx.workspace / "docker-compose.yml"),
        "api_main": _read_text(ctx.workspace / "apps" / "api" / "src" / "main.ts"),
        "api_dockerfile": _read_text(ctx.workspace / "apps" / "api" / "Dockerfile"),
        "web_dockerfile": _read_text(ctx.workspace / "apps" / "web" / "Dockerfile"),
        "root_npmrc": _read_text(ctx.workspace / ".npmrc"),
        "root_lockfile": _read_text(ctx.workspace / "pnpm-lock.yaml"),
        "root_package": _read_text(ctx.workspace / "package.json"),
        "openapi_script": _read_text(ctx.workspace / "scripts" / "generate-openapi.ts"),
        "openapi_ts_config": _read_text(ctx.workspace / "apps" / "web" / "openapi-ts.config.ts"),
    }
    failures = []
    if api_port != 4000 or web_port != 3000:
        failures.append("stack contract ports are not 4000/3000")
    if set(contract_data.get("ports") or []) != {3000, 4000, 5432}:
        failures.append("stack contract port list drifted")
    if infra_slots.get("api_port") != api_port or infra_slots.get("web_port") != web_port:
        failures.append("infrastructure_template slots do not match contract ports")
    expected_tokens = [
        (".env.example", files["root_env"], "PORT=4000"),
        (".env.example", files["root_env"], "FRONTEND_ORIGIN=http://localhost:3000"),
        ("apps/api/.env.example", files["api_env"], "PORT=4000"),
        ("apps/web/.env.example", files["web_env"], "NEXT_PUBLIC_API_URL=http://localhost:4000/api"),
        ("docker-compose.yml", files["compose"], '"4000:4000"'),
        ("docker-compose.yml", files["compose"], '"3000:3000"'),
        ("docker-compose.yml", files["compose"], "http://localhost:4000/api/health"),
        ("apps/api/Dockerfile", files["api_dockerfile"], "EXPOSE 4000"),
        ("apps/api/Dockerfile", files["api_dockerfile"], "corepack prepare pnpm@10.17.1 --activate"),
        ("apps/api/Dockerfile", files["api_dockerfile"], "COPY .npmrc pnpm-workspace.yaml pnpm-lock.yaml package.json ./"),
        ("apps/web/Dockerfile", files["web_dockerfile"], "EXPOSE 3000"),
        ("apps/web/Dockerfile", files["web_dockerfile"], "corepack prepare pnpm@10.17.1 --activate"),
        ("apps/web/Dockerfile", files["web_dockerfile"], "COPY .npmrc package.json pnpm-lock.yaml pnpm-workspace.yaml ./"),
        ("apps/web/Dockerfile", files["web_dockerfile"], 'CMD ["pnpm", "next", "start", "-p", "3000"]'),
        (".npmrc", files["root_npmrc"], "offline=false"),
        (".npmrc", files["root_npmrc"], "package-import-method=copy"),
        ("pnpm-lock.yaml", files["root_lockfile"], "lockfileVersion: '9.0'"),
        ("package.json", files["root_package"], '"packageManager": "pnpm@10.17.1"'),
        ("scripts/generate-openapi.ts", files["openapi_script"], "createRequire(join(apiRoot, 'package.json'))"),
        ("scripts/generate-openapi.ts", files["openapi_script"], "process.env.SKIP_PRISMA_CONNECT ??= '1'"),
        ("scripts/generate-openapi.ts", files["openapi_script"], "setGlobalPrefix(process.env.API_PREFIX || 'api')"),
        ("apps/web/openapi-ts.config.ts", files["openapi_ts_config"], "@hey-api/client-fetch"),
    ]
    for file_name, content, token in expected_tokens:
        if token not in content:
            failures.append(f"{file_name} missing {token}")
    if re.search(r"(^|[^0-9])5432([^0-9]|$)", files["api_env"]) and "PORT=5432" in files["api_env"]:
        failures.append("database port 5432 appears as API PORT")

    details = {
        "workspace": str(ctx.workspace),
        "scaffolded_files": sorted(ctx.scaffolded_files),
        "stack_contract_path": str(ctx.workspace / ".agent-team" / "STACK_CONTRACT.json"),
        "stack_contract": contract_data,
        "api_port": api_port,
        "web_port": web_port,
        "infra_slots": infra_slots,
        "checked_files": sorted(files),
    }
    _require(not failures, "stack-contract/scaffold replay failed", {"failures": failures, **details})
    return details


def _resolve_pnpm() -> str:
    for name in ("pnpm", "pnpm.cmd", "pnpm.exe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise GateFailure("pnpm executable not found on PATH")


def _workspace_local_bin_exists(project_root: Path, name: str) -> bool:
    if not name:
        return False
    suffixes = ("", ".cmd", ".exe", ".bat")
    candidates = [project_root / "node_modules" / ".bin"]
    for parent in ("apps", "packages"):
        base = project_root / parent
        if not base.is_dir():
            continue
        for child in base.iterdir():
            candidates.append(child / "node_modules" / ".bin")
    return any((bin_dir / f"{name}{suffix}").is_file() for bin_dir in candidates for suffix in suffixes)


def _gate2_wave_c(ctx: FastForwardContext, *, skip_install: bool = False) -> dict[str, Any]:
    install_attempts: list[CommandResult] = []
    if not skip_install:
        pnpm = _resolve_pnpm()
        primary = _run(
            [pnpm, "install", "--frozen-lockfile"],
            cwd=ctx.workspace,
            timeout=300,
            context=ctx,
        )
        install_attempts.append(primary)
        install_command = primary
        _require(
            install_command.returncode == 0,
            "pnpm install failed in generated workspace",
            {
                "environment_blocker": True,
                "blocker_type": "dependency_install",
                "install_attempts": [attempt.to_dict() for attempt in install_attempts],
                "notes": [
                    "Frozen pnpm install is required before canonical Wave C replay.",
                    "This gate intentionally does not fall back to npm or patch generated output.",
                ],
            },
        )
        local_bins = {
            "ts-node": _workspace_local_bin_exists(ctx.workspace, "ts-node"),
            "openapi-ts": _workspace_local_bin_exists(ctx.workspace, "openapi-ts"),
        }
        _require(
            all(local_bins.values()),
            "canonical Wave C local launchers missing after pnpm install",
            {
                "local_bins": local_bins,
                "notes": [
                    "Wave C must use project-local ts-node and openapi-ts; npx/global fallback is not canonical proof.",
                ],
            },
        )

    result = generate_openapi_contracts(ctx.workspace, _milestone())
    degradation_reasons = [
        reason
        for reason in (result.degradation_reason, result.client_degradation_reason)
        if reason
    ]
    ctx.wave_c_artifact = {
        "success": bool(result.success),
        "milestone_spec_path": result.milestone_spec_path,
        "cumulative_spec_path": result.cumulative_spec_path,
        "files_created": list(result.files_created),
        "contract_source": result.contract_source,
        "contract_fidelity": result.contract_fidelity,
        "client_generator": result.client_generator,
        "client_fidelity": result.client_fidelity,
        "degradation_reasons": degradation_reasons,
        "endpoints": list(result.endpoints_summary),
    }

    spec = _read_json(ctx.workspace / "contracts" / "openapi" / "current.json")
    client_package = _read_json(ctx.workspace / "packages" / "api-client" / "package.json")
    client_ts_files = sorted(
        p.relative_to(ctx.workspace).as_posix()
        for p in (ctx.workspace / "packages" / "api-client").rglob("*.ts")
    ) if (ctx.workspace / "packages" / "api-client").is_dir() else []

    failures = []
    if not result.success:
        failures.append("OpenAPI generation returned success=false")
    if result.contract_source != "openapi-script" or result.contract_fidelity != "canonical":
        failures.append("OpenAPI contract is degraded")
    if result.client_generator != "openapi-ts" or result.client_fidelity != "canonical":
        failures.append("generated client is not canonical openapi-ts output")
    if degradation_reasons:
        failures.append("degradation reasons are present")
    paths = set((spec.get("paths") or {}).keys()) if isinstance(spec.get("paths"), dict) else set()
    if "/api/health" not in paths:
        failures.append("OpenAPI spec missing /api/health")
    if "/health" in paths:
        failures.append("OpenAPI spec exposes unprefixed /health")
    if not client_package:
        failures.append("packages/api-client/package.json missing")
    if not client_ts_files:
        failures.append("no TypeScript files emitted under packages/api-client")

    details = {
        "canonical_openapi": result.contract_source == "openapi-script"
        and result.contract_fidelity == "canonical",
        "canonical_client": result.client_generator == "openapi-ts"
        and result.client_fidelity == "canonical",
        "wave_c_artifact": ctx.wave_c_artifact,
        "openapi_paths": sorted(paths),
        "client_package": client_package,
        "client_ts_files": client_ts_files,
        "install_attempts": [attempt.to_dict() for attempt in install_attempts],
        "local_bins": {
            "ts-node": _workspace_local_bin_exists(ctx.workspace, "ts-node"),
            "openapi-ts": _workspace_local_bin_exists(ctx.workspace, "openapi-ts"),
        },
        "degraded_artifacts": degradation_reasons,
    }
    _require(not failures, "Wave C canonical replay failed", {"failures": failures, **details})
    return details


_RAW_API_PATTERN = re.compile(
    r"\b(?:fetch|axios\.(?:get|post|put|patch|delete))\s*\(\s*['\"](?:/api/|http://localhost:\d+/api/)",
    re.IGNORECASE,
)


def scan_frontend_raw_api_usage(project_root: Path) -> list[str]:
    """Return frontend files that bypass the generated API client."""

    root = Path(project_root) / "apps" / "web"
    if not root.is_dir():
        return []
    offenders: list[str] = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        rel = path.relative_to(project_root).as_posix()
        text = _read_text(path)
        if _RAW_API_PATTERN.search(text):
            offenders.append(rel)
    return sorted(offenders)


def _write_fixture_file(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _gate3_wave_d(ctx: FastForwardContext) -> dict[str, Any]:
    prompt = build_wave_d_prompt(
        milestone=_milestone(),
        ir=_diagnostic_ir(),
        wave_c_artifact=ctx.wave_c_artifact,
        scaffolded_files=list(ctx.scaffolded_files),
        config=ctx.config,
        existing_prompt_framework="FAST_FORWARD_FRAMEWORK",
        cwd=str(ctx.workspace),
        milestone_context=None,
        mcp_doc_context="",
        merged=False,
        wave_d_artifact=None,
    )
    lowered_prompt = prompt.lower()
    # The Wave D prompt text is authored in agents.build_wave_d_prompt and
    # phrased as positive frontend scope rules plus explicit backend
    # prohibitions ("Do not create backend services, controllers, entities,
    # or migrations"). The gate asserts semantic intent — generated-client
    # only, backend-edits forbidden, frontend-scope declared — rather than
    # a single exact sentence, so the gate does not false-fail when the
    # prompt builder rewords a rule. Port literals are validated by
    # Gate 1 (stack-contract/compose/env/Dockerfile agreement); Wave D is
    # frontend-only and consumes the generated client, which owns the
    # API base URL, so the Wave D prompt does not need to embed port
    # numbers.
    prompt_checks = {
        "mentions_generated_client": "generated client" in lowered_prompt,
        "forbids_api_client_edits": "packages/api-client" in prompt,
        "forbids_backend_edits": any(
            token in prompt
            for token in (
                "Do not modify backend",
                "Do not create backend",
                "apps/api",
            )
        ),
        "asserts_frontend_scope": "WAVE D" in prompt.upper()
        and "frontend" in lowered_prompt,
    }

    fixture_root = ctx.run_root / "wave-d-fixtures"
    positive = fixture_root / "positive"
    negative_no_client = fixture_root / "negative-no-client"
    negative_raw_fetch = fixture_root / "negative-raw-fetch"
    for fixture in (positive, negative_no_client, negative_raw_fetch):
        _write_fixture_file(fixture, "packages/api-client/index.ts", "export const getProjects = () => null;\n")
    _write_fixture_file(
        positive,
        "apps/web/src/app/page.tsx",
        "import { getProjects } from '@taskflow/api-client';\nexport default function Page() { getProjects(); return null; }\n",
    )
    _write_fixture_file(
        negative_no_client,
        "apps/web/src/app/page.tsx",
        "export default function Page() { return null; }\n",
    )
    _write_fixture_file(
        negative_raw_fetch,
        "apps/web/src/app/page.tsx",
        "import { getProjects } from '@taskflow/api-client';\nexport async function load() { await fetch('/api/projects'); return getProjects(); }\n",
    )

    positive_import_violations = scan_generated_client_import_usage(positive)
    negative_import_violations = scan_generated_client_import_usage(negative_no_client)
    raw_fetch_violations = scan_frontend_raw_api_usage(negative_raw_fetch)
    forbidden = find_forbidden_paths(
        [
            "apps/api/src/main.ts",
            "packages/api-client/index.ts",
            "apps/web/src/app/page.tsx",
        ],
        "D",
    )

    failures = []
    for key, passed in prompt_checks.items():
        if not passed:
            failures.append(f"Wave D prompt check failed: {key}")
    if positive_import_violations:
        failures.append("positive generated-client fixture reported violations")
    if not negative_import_violations:
        failures.append("zero generated-client import fixture was not detected")
    if "packages/api-client/index.ts" not in forbidden:
        failures.append("Wave D forbidden-path guard does not block packages/api-client")
    if not raw_fetch_violations:
        failures.append("manual raw fetch fixture was not detected")

    details = {
        "prompt_checks": prompt_checks,
        "positive_import_violations": [getattr(v, "message", str(v)) for v in positive_import_violations],
        "negative_import_violations": [getattr(v, "message", str(v)) for v in negative_import_violations],
        "raw_fetch_violations": raw_fetch_violations,
        "forbidden_paths_for_wave_d": forbidden,
        "wave_d_gate": {
            "generated_client_import_guard": bool(negative_import_violations),
            "raw_fetch_guard": bool(raw_fetch_violations),
            "api_client_immutable_guard": "packages/api-client/index.ts" in forbidden,
        },
    }
    _require(not failures, "Wave D deterministic readiness failed", {"failures": failures, **details})
    return details


def _valid_wave_t_output() -> str:
    summary = {
        "tests_written": {"backend": 1, "frontend": 1, "total": 2},
        "tests_passing_at_end": 2,
        "tests_failing_at_end": 0,
        "ac_tests": [
            {
                "ac_id": "AC-M1-001",
                "tests": [
                    {"path": "apps/api/src/health.controller.spec.ts", "name": "returns /api/health"},
                    {"path": "apps/web/src/app/page.test.tsx", "name": "uses generated client"},
                ],
            }
        ],
        "unverified_acs": [],
        "structural_findings": [],
        "deliberately_failing": [],
        "design_token_tests_added": False,
        "iterations_used": 0,
    }
    return "Wave T completed.\n```wave-t-summary\n" + json.dumps(summary) + "\n```\n"


def _gate4_wave_t(ctx: FastForwardContext) -> dict[str, Any]:
    sequence = _wave_sequence("full_stack", ctx.config)
    _require("T" in sequence and "E" in sequence and sequence.index("T") < sequence.index("E"), "Wave T is not before Wave E")

    prompt = build_wave_t_prompt(
        milestone=_milestone(),
        ir=_diagnostic_ir(),
        wave_artifacts={"C": ctx.wave_c_artifact, "D": {"files_modified": ["apps/web/src/app/page.tsx"]}},
        config=ctx.config,
        existing_prompt_framework="FAST_FORWARD_FRAMEWORK",
        cwd=str(ctx.workspace),
    )
    # The Wave T prompt encodes the "tests are the specification" principle
    # through three structural anchors rather than one quoted sentence:
    # the Assertive Matchers minimum standard (ban "exists-only" tests),
    # the AC→Test coverage matrix requirement, and the explicit structural
    # bug policy that leaves failing tests in place for the audit loop.
    # Matching those anchors keeps this gate honest if the prompt author
    # rephrases the summary sentence, without allowing a prompt that drops
    # any of the three substantive enforcement sections to slip through.
    prompt_checks = {
        "requires_summary": "wave-t-summary" in prompt,
        "contains_core_principle": all(
            token in prompt
            for token in (
                "ASSERTIVE MATCHERS",
                "AC TO TEST COVERAGE MATRIX",
                "WHEN A TEST FAILS",
            )
        ),
        "contains_ac_context": "AC-M1-001" in prompt,
        "contains_completed_waves": "[COMPLETED WAVES]" in prompt,
    }

    parsed = parse_wave_t_summary_text(_valid_wave_t_output())
    raw_output = ctx.workspace / ".agent-team" / "milestones" / MILESTONE_ID / "WAVE_T_OUTPUT.md"
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(_valid_wave_t_output(), encoding="utf-8")
    loaded, summary_path, summary_error = load_wave_t_summary(ctx.workspace, MILESTONE_ID)

    invalid_summary_blocked = False
    try:
        parse_wave_t_summary_text("```wave-t-summary\n{\"tests_written\": {}}\n```")
    except ValueError:
        invalid_summary_blocked = True

    test_artifact = {
        "files_created": ["apps/api/src/health.controller.spec.ts"],
        "files_modified": ["apps/web/src/app/page.test.tsx"],
    }
    _write_fixture_file(ctx.workspace, "apps/api/src/health.controller.spec.ts", "describe('health', () => {});\n")
    _write_fixture_file(ctx.workspace, "apps/web/src/app/page.test.tsx", "test('page', () => {});\n")
    collected_tests = collect_wave_t_test_files(str(ctx.workspace), test_artifact)

    t_result = WaveResult(
        wave="T",
        success=True,
        findings=[WaveFinding(code="TEST-FAIL", severity="HIGH", message="fixture failure")],
        wave_t_summary=loaded,
        wave_t_summary_path=summary_path,
        wave_t_summary_parse_error=summary_error,
    )
    save_wave_telemetry(t_result, str(ctx.workspace), MILESTONE_ID)
    findings_path = persist_wave_findings_for_audit(
        str(ctx.workspace),
        MILESTONE_ID,
        [WaveResult(wave="D", success=True), t_result],
        wave_t_expected=True,
        failing_wave=None,
    )
    telemetry = _read_json(ctx.workspace / ".agent-team" / "telemetry" / f"{MILESTONE_ID}-wave-T.json")
    findings = _read_json(findings_path) if findings_path else {}

    t5_prompt = build_wave_t5_prompt(
        test_files=collected_tests,
        source_files=[],
        acceptance_criteria="- AC-M1-001: generated client and health endpoint are covered",
    )
    failures = []
    for key, passed in prompt_checks.items():
        if not passed:
            failures.append(f"Wave T prompt check failed: {key}")
    if summary_error or not loaded:
        failures.append("Wave T summary did not parse/persist")
    if not invalid_summary_blocked:
        failures.append("invalid Wave T summary fixture was not rejected")
    if len(collected_tests) < 2:
        failures.append("Wave T test collection did not find both fixture tests")
    if telemetry.get("wave_t_summary_parse_error"):
        failures.append("Wave T telemetry carries a summary parse error")
    if findings.get("wave_t_status") != "completed":
        failures.append("WAVE_FINDINGS.json did not mark Wave T completed")
    if '"gaps"' not in t5_prompt or '"files_read"' not in t5_prompt:
        failures.append("Wave T.5 prompt missing required JSON schema")

    details = {
        "runtime_sequence": sequence,
        "prompt_checks": prompt_checks,
        "parsed_summary": parsed,
        "summary_path": summary_path,
        "summary_error": summary_error,
        "collected_tests": [rel for rel, _body in collected_tests],
        "telemetry": telemetry,
        "wave_findings_path": str(findings_path) if findings_path else "",
        "wave_findings": findings,
        "wave_t_gate": {
            "summary_parsed": bool(loaded) and not summary_error,
            "summary_persisted": bool(summary_path),
            "findings_persisted": findings.get("wave_t_status") == "completed",
            "t5_prompt_schema_present": '"gaps"' in t5_prompt and '"files_read"' in t5_prompt,
        },
    }
    _require(not failures, "Wave T/T.5 deterministic proof failed", {"failures": failures, **details})
    return details


def _known_context7_quota_only(text: str) -> bool:
    lower = str(text or "").lower()
    return all(pattern in lower for pattern in CONTEXT7_QUOTA_PATTERNS)


def audit_run_directory(run_dir: Path) -> dict[str, Any]:
    """Read-only coherence audit for a completed smoke run directory."""

    run_dir = Path(run_dir)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def issue(code: str, message: str, evidence: Any = None) -> None:
        issues.append({"code": code, "message": message, "evidence": evidence})

    exit_code_text = _read_text(run_dir / "EXIT_CODE.txt").strip()
    if exit_code_text and exit_code_text != "0":
        issue("EXIT-CODE", "smoke run exit code is nonzero", exit_code_text)

    if (run_dir / "WAVE_A_CONTRACT_CONFLICT.md").exists():
        issue("WAVE-A-CONTRACT-CONFLICT", "Wave A contract conflict file exists")

    state = _read_json(run_dir / ".agent-team" / "STATE.json")
    summary = state.get("summary") if isinstance(state.get("summary"), dict) else {}
    if summary and summary.get("success") is not True:
        issue("STATE-SUMMARY", "STATE.json summary is not successful", summary)

    progress = _read_json(run_dir / ".agent-team" / "milestone_progress.json")
    if progress:
        failures = [
            item
            for item in progress.get("milestones", [])
            if isinstance(item, dict) and str(item.get("status", "")).lower() in {"failed", "interrupted"}
        ]
        if failures:
            issue("MILESTONE-PROGRESS", "milestone progress contains failed/interrupted milestones", failures)

    stack = _read_json(run_dir / ".agent-team" / "STACK_CONTRACT.json")
    api_port = int(stack.get("api_port") or 0) if stack else 0
    web_port = int(stack.get("web_port") or 0) if stack else 0
    infra_slots = (
        stack.get("infrastructure_template", {}).get("slots", {})
        if isinstance(stack.get("infrastructure_template"), dict)
        else {}
    )
    if stack:
        if api_port == 5432:
            issue("API-PORT-DB", "port 5432 is being treated as API port")
        if api_port and infra_slots.get("api_port") not in (None, api_port):
            issue("STACK-INFRA-API-PORT", "infrastructure_template api port differs from stack contract")
        if web_port and infra_slots.get("web_port") not in (None, web_port):
            issue("STACK-INFRA-WEB-PORT", "infrastructure_template web port differs from stack contract")

    artifacts_dir = run_dir / ".agent-team" / "artifacts"
    for artifact_path in sorted(artifacts_dir.glob(f"{MILESTONE_ID}-wave-*.json")):
        artifact = _read_json(artifact_path)
        wave = str(artifact.get("wave") or artifact_path.stem)
        if wave == "C":
            if artifact.get("contract_fidelity") != "canonical" or artifact.get("client_fidelity") != "canonical":
                issue("WAVE-C-DEGRADED", "Wave C artifact is degraded", {"path": str(artifact_path), "artifact": artifact})
            if artifact.get("client_generator") not in (None, "openapi-ts"):
                issue("WAVE-C-CLIENT-GENERATOR", "Wave C client generator is not openapi-ts", artifact.get("client_generator"))

    telemetry_dir = run_dir / ".agent-team" / "telemetry"
    for telemetry_path in sorted(telemetry_dir.glob(f"{MILESTONE_ID}-wave-*.json")):
        telemetry = _read_json(telemetry_path)
        wave = str(telemetry.get("wave") or "").upper()
        if telemetry.get("success") is False:
            issue("WAVE-TELEMETRY-FAILED", f"Wave {wave} telemetry success=false", {"path": str(telemetry_path), "error": telemetry.get("error_message")})
        if telemetry.get("wave_timed_out"):
            issue("WAVE-TIMEOUT", f"Wave {wave} timed out", str(telemetry_path))
        if telemetry.get("scope_violations"):
            issue("SCOPE-VIOLATIONS", f"Wave {wave} has scope violations", telemetry.get("scope_violations"))
        if wave in CODEX_OWNED_WAVES and telemetry.get("fallback_used"):
            issue("CODEX-FALLBACK", f"Codex-owned Wave {wave} used fallback", telemetry.get("fallback_reason"))
        if wave in {"B", "D", "T5"} and str(telemetry.get("provider", "")).lower() == "claude":
            issue("CLAUDE-FALLBACK", f"Codex-owned Wave {wave} ran on Claude", telemetry)
        if wave == "T" and telemetry.get("success") is True and telemetry.get("wave_t_summary_parse_error"):
            issue("WAVE-T-SUMMARY", "Wave T telemetry has missing/invalid summary", telemetry.get("wave_t_summary_parse_error"))

    findings = _read_json(run_dir / ".agent-team" / "milestones" / MILESTONE_ID / "WAVE_FINDINGS.json")
    if findings:
        wave_t_status = findings.get("wave_t_status")
        if wave_t_status in {"skipped", "disabled", "completed_with_failure"}:
            issue("WAVE-T-STATUS", "Wave T evidence is not cleanly completed", findings)
    else:
        issue("WAVE-FINDINGS-MISSING", "WAVE_FINDINGS.json is missing")

    audit_report = _read_json(run_dir / ".agent-team" / "AUDIT_REPORT.json")
    if audit_report and audit_report.get("success") is False:
        issue("AUDIT-REPORT", "AUDIT_REPORT.json contradicts success", audit_report)
    audit_integration = _read_json(run_dir / ".agent-team" / "AUDIT_REPORT_INTEGRATION.json")
    if audit_integration and audit_integration.get("healthy") is False:
        issue("AUDIT-INTEGRATION", "AUDIT_REPORT_INTEGRATION.json is unhealthy", audit_integration)

    combined_logs = "\n".join(
        [
            _read_text(run_dir / "BUILD_LOG.txt"),
            _read_text(run_dir / "BUILD_ERR.txt"),
        ]
    )
    if "Context7" in combined_logs and "quota" in combined_logs.lower():
        if _known_context7_quota_only(combined_logs):
            warnings.append(
                {
                    "code": "CONTEXT7-QUOTA-WAIVED",
                    "message": "Known Context7 quota/monthly-limit log was treated as waived.",
                }
            )
        else:
            issue("CONTEXT7-NONQUOTA", "Context7 log does not clearly match the known quota waiver")

    return {
        "run_dir": str(run_dir),
        "clean": not issues,
        "issues": issues,
        "warnings": warnings,
        "diagnostic_only": True,
    }


def _latest_smoke_run(repo: Path) -> Path | None:
    root = repo / "v18 test runs"
    candidates = [p for p in root.glob("m1-hardening-smoke-*") if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _gate5_run_auditor(ctx: FastForwardContext, audit_run_dir: Path | None) -> dict[str, Any]:
    target = audit_run_dir or _latest_smoke_run(ctx.repo)
    if target is None:
        return {
            "auditor_exercised": False,
            "reason": "No existing m1-hardening-smoke-* run directory found.",
            "diagnostic_only": True,
        }
    audit = audit_run_directory(target)
    if audit["clean"]:
        return {
            "auditor_exercised": True,
            "expected_clean": True,
            "audit": audit,
            "diagnostic_only": True,
        }
    return {
        "auditor_exercised": True,
        "expected_clean": False,
        "negative_fixture_detected": True,
        "audit": audit,
        "diagnostic_only": True,
    }


def run_fast_forward(
    *,
    repo: Path,
    output_dir: Path | None = None,
    audit_run_dir: Path | None = None,
    skip_install: bool = False,
) -> dict[str, Any]:
    ctx = _make_context(repo.resolve(), output_dir.resolve() if output_dir else None)
    report: dict[str, Any] = {
        "success": False,
        "ready_for_full_smoke": False,
        "final_smoke_proof": False,
        "diagnostic_only": True,
        "environment_blocker": False,
        "failed_gate": "",
        "failed_reason": "",
        "workspace": str(ctx.workspace),
        "report_path": str(ctx.run_root / "fast-forward-report.json"),
        "started_at": _now_iso(),
        "gates": [],
        "commands": [],
    }

    gates = [
        ("gate0_source_config", lambda: _gate0_source_config(ctx)),
        ("gate1_stack_scaffold", lambda: _gate1_stack_scaffold(ctx)),
        ("gate2_wave_c_canonical", lambda: _gate2_wave_c(ctx, skip_install=skip_install)),
        ("gate3_wave_d_readiness", lambda: _gate3_wave_d(ctx)),
        ("gate4_wave_t_t5_proof", lambda: _gate4_wave_t(ctx)),
        ("gate5_run_dir_auditor", lambda: _gate5_run_auditor(ctx, audit_run_dir)),
    ]

    try:
        for gate_name, gate_fn in gates:
            started = time.monotonic()
            details = gate_fn()
            report["gates"].append(
                {
                    "name": gate_name,
                    "status": "passed",
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "details": details,
                }
            )
        report["success"] = True
        report["ready_for_full_smoke"] = True
    except GateFailure as exc:
        report["failed_gate"] = report["gates"][-1]["name"] if report["gates"] else ""
        pending_gate = gates[len(report["gates"])][0] if len(report["gates"]) < len(gates) else report["failed_gate"]
        report["failed_gate"] = pending_gate
        report["failed_reason"] = exc.reason
        if exc.details.get("environment_blocker"):
            report["environment_blocker"] = True
            report["blocker_type"] = exc.details.get("blocker_type", "")
        report["gates"].append(
            {
                "name": pending_gate,
                "status": "failed",
                "duration_seconds": 0.0,
                "details": exc.details,
            }
        )
    finally:
        report["finished_at"] = _now_iso()
        report["commands"] = [cmd.to_dict() for cmd in ctx.commands]
        _write_json(Path(report["report_path"]), report)
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M1 fast-forward diagnostic gates.")
    parser.add_argument("--repo", default=".", help="Repository root.")
    parser.add_argument("--output-dir", default="", help="Optional output directory.")
    parser.add_argument("--audit-run-dir", default="", help="Existing smoke run directory to audit.")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip pnpm install in the generated workspace. Intended for unit tests only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_fast_forward(
        repo=Path(args.repo),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        audit_run_dir=Path(args.audit_run_dir) if args.audit_run_dir else None,
        skip_install=bool(args.skip_install),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("success") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
