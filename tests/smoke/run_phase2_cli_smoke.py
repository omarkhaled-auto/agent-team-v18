from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_team_v15 import cli as cli_module
from agent_team_v15.config import load_config
from agent_team_v15.milestone_manager import MilestoneManager


FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "phase2_cli_smoke"
WORKSPACE_TEMPLATE = FIXTURE_ROOT / "workspace"
CONFIG_PATH = FIXTURE_ROOT / "config.yaml"
NPM_COMMAND = "npm.cmd" if sys.platform.startswith("win") else "npm"


class _FakeClient:
    workspace_root: Path | None = None

    def __init__(self, *, options):
        self.options = options
        self.last_prompt = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def query(self, prompt: str) -> None:
        self.last_prompt = prompt
        run_dir = self.workspace_root
        if run_dir is None:
            raise RuntimeError("Phase 2 smoke workspace root was not configured")
        if "[WAVE A" in prompt:
            target = run_dir / "src" / "bookmark.entity.ts"
            target.write_text(target.read_text(encoding="utf-8") + "\n// smoke wave A touch\n", encoding="utf-8")
        elif "[WAVE B" in prompt:
            created_module = run_dir / "src" / "wave-b-created.module.ts"
            created_module.write_text("export const waveBCreatedModule = true;\n", encoding="utf-8")
            target = run_dir / "src" / "server.ts"
            target.write_text(target.read_text(encoding="utf-8") + "\n// smoke wave B touch\n", encoding="utf-8")
        elif "[WAVE E" in prompt:
            target = run_dir / "src" / "server.ts"
            target.write_text(target.read_text(encoding="utf-8") + "\n// smoke wave E touch\n", encoding="utf-8")


async def _fake_process_response(*args, **kwargs) -> float:
    del args, kwargs
    return 0.2


async def _fake_drain_interventions(*args, **kwargs) -> float:
    del args, kwargs
    return 0.0


def _ensure_workspace_dependencies(run_dir: Path) -> None:
    typescript_bin = run_dir / "node_modules" / "typescript" / "bin" / "tsc"
    if typescript_bin.exists():
        return
    proc = subprocess.run(
        [NPM_COMMAND, "install", "--no-fund", "--no-audit"],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "npm install failed for the Phase 2 smoke fixture.\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )


async def _run_smoke(run_dir: Path) -> dict[str, object]:
    _FakeClient.workspace_root = run_dir
    cli_module.ClaudeSDKClient = _FakeClient
    cli_module._process_response = _fake_process_response
    cli_module._drain_interventions = _fake_drain_interventions

    config, _ = load_config(CONFIG_PATH)
    total_cost, convergence_report = await cli_module._run_prd_milestones(
        task="Phase 2 CLI smoke",
        config=config,
        cwd=str(run_dir),
        depth="standard",
        prd_path=None,
    )

    mm = MilestoneManager(run_dir)
    health = mm.check_milestone_health(
        "milestone-1",
        min_convergence_ratio=config.convergence.min_convergence_ratio,
    )
    requirements_path = run_dir / ".agent-team" / "milestones" / "milestone-1" / "REQUIREMENTS.md"
    tasks_path = run_dir / ".agent-team" / "milestones" / "milestone-1" / "TASKS.md"
    summary = {
        "run_dir": str(run_dir),
        "total_cost": total_cost,
        "convergence_report_health": getattr(convergence_report, "health", None),
        "milestone_health": health.health,
        "checked_requirements": health.checked_requirements,
        "total_requirements": health.total_requirements,
        "review_cycles": health.review_cycles,
        "requirements_path": str(requirements_path),
        "tasks_path": str(tasks_path),
        "current_spec_exists": (run_dir / "contracts" / "openapi" / "current.json").is_file(),
        "milestone_spec_exists": (run_dir / "contracts" / "openapi" / "milestone-1.json").is_file(),
        "evidence_dir_exists": (run_dir / ".agent-team" / "evidence").exists(),
        "wave_artifacts": sorted(
            str(path.relative_to(run_dir)).replace("\\", "/")
            for path in (run_dir / ".agent-team").rglob("milestone-1-wave-*.json")
        ),
    }

    requirements = requirements_path.read_text(encoding="utf-8")
    tasks = tasks_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if health.health != "healthy":
        errors.append(f"milestone health is {health.health!r}, expected 'healthy'")
    if "[ ]" in requirements:
        errors.append("REQUIREMENTS.md still contains unchecked items")
    if "(review_cycles:" not in requirements:
        errors.append("REQUIREMENTS.md is missing review_cycles markers")
    if "Status: DONE" in tasks or "- Status: COMPLETE" not in tasks:
        errors.append("TASKS.md was not normalized to canonical - Status: COMPLETE lines")
    if not summary["current_spec_exists"]:
        errors.append("contracts/openapi/current.json was not generated")
    if not summary["milestone_spec_exists"]:
        errors.append("contracts/openapi/milestone-1.json was not generated")
    if summary["evidence_dir_exists"]:
        errors.append("evidence artifacts were created even though Phase 2 evidence mode is disabled")
    if len(summary["wave_artifacts"]) < 4:
        errors.append("expected wave artifacts/telemetry for A, B, C, and E")
    if errors:
        summary["errors"] = errors
        raise RuntimeError(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    run_dir = Path(tempfile.mkdtemp(prefix="phase2-cli-smoke-"))
    shutil.copytree(WORKSPACE_TEMPLATE, run_dir, dirs_exist_ok=True)
    _ensure_workspace_dependencies(run_dir)
    summary = asyncio.run(_run_smoke(run_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - exercised by manual runs
        print(str(exc), file=sys.stderr)
        raise
