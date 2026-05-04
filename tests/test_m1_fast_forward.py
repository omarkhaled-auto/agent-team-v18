from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_team_v15.m1_fast_forward import (
    CommandResult,
    FastForwardContext,
    GateFailure,
    _gate2_wave_c,
    audit_run_directory,
    scan_frontend_raw_api_usage,
)
from agent_team_v15.wave_executor import load_wave_t_summary, parse_wave_t_summary_text


def _wave_t_output() -> str:
    payload = {
        "tests_written": {"backend": 1, "frontend": 1, "total": 2},
        "tests_passing_at_end": 2,
        "tests_failing_at_end": 0,
        "ac_tests": [{"ac_id": "AC-1", "tests": [{"path": "x.spec.ts", "name": "works"}]}],
        "unverified_acs": [],
        "structural_findings": [],
        "deliberately_failing": [],
        "design_token_tests_added": False,
        "iterations_used": 0,
    }
    return "done\n```wave-t-summary\n" + json.dumps(payload) + "\n```\n"


def _gate2_context(tmp_path: Path) -> FastForwardContext:
    workspace = tmp_path / "generated"
    workspace.mkdir()
    bin_dir = workspace / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    for name in ("ts-node", "openapi-ts"):
        (bin_dir / name).write_text("", encoding="utf-8")
    web_bin_dir = workspace / "apps" / "web" / "node_modules" / ".bin"
    web_bin_dir.mkdir(parents=True)
    (web_bin_dir / "tsc").write_text("", encoding="utf-8")
    return FastForwardContext(
        repo=tmp_path,
        run_root=tmp_path,
        workspace=workspace,
        config=object(),  # Gate 2 does not read config.
    )


def _write_gate2_wave_c_outputs(workspace: Path) -> SimpleNamespace:
    (workspace / "contracts" / "openapi").mkdir(parents=True)
    (workspace / "contracts" / "openapi" / "current.json").write_text(
        json.dumps({"paths": {"/api/health": {"get": {}}}}),
        encoding="utf-8",
    )
    client_dir = workspace / "packages" / "api-client"
    client_dir.mkdir(parents=True)
    (client_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@taskflow/api-client",
                "dependencies": {"@hey-api/client-fetch": "^0.8.0"},
            }
        ),
        encoding="utf-8",
    )
    (client_dir / "client.gen.ts").write_text(
        "import { client } from '@hey-api/client-fetch';\nexport { client };\n",
        encoding="utf-8",
    )
    (client_dir / "sdk.gen.ts").write_text("export const ping = () => null;\n", encoding="utf-8")
    return SimpleNamespace(
        success=True,
        milestone_spec_path="contracts/openapi/milestone-1.json",
        cumulative_spec_path="contracts/openapi/current.json",
        files_created=["contracts/openapi/current.json", "packages/api-client/client.gen.ts"],
        contract_source="openapi-script",
        contract_fidelity="canonical",
        client_generator="openapi-ts",
        client_fidelity="canonical",
        degradation_reason="",
        client_degradation_reason="",
        endpoints_summary=[{"method": "GET", "path": "/api/health"}],
    )


def test_parse_wave_t_summary_requires_valid_block() -> None:
    parsed = parse_wave_t_summary_text(_wave_t_output())
    assert parsed["tests_written"]["total"] == 2
    assert parsed["unverified_acs"] == []


def test_parse_wave_t_summary_rejects_missing_keys() -> None:
    try:
        parse_wave_t_summary_text("```wave-t-summary\n{\"tests_written\": {}}\n```")
    except ValueError as exc:
        assert "missing keys" in str(exc)
    else:
        raise AssertionError("invalid Wave T summary was accepted")


def test_load_wave_t_summary_persists_json_artifact(tmp_path: Path) -> None:
    milestone_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "WAVE_T_OUTPUT.md").write_text(_wave_t_output(), encoding="utf-8")

    summary, path, error = load_wave_t_summary(tmp_path, "milestone-1")

    assert error == ""
    assert summary["tests_passing_at_end"] == 2
    assert path.endswith("WAVE_T_SUMMARY.json")
    assert (milestone_dir / "WAVE_T_SUMMARY.json").is_file()


def test_audit_run_directory_rejects_degraded_wave_c(tmp_path: Path) -> None:
    run = tmp_path
    (run / ".agent-team" / "artifacts").mkdir(parents=True)
    (run / ".agent-team" / "milestones" / "milestone-1").mkdir(parents=True)
    (run / "EXIT_CODE.txt").write_text("1", encoding="utf-8")
    (run / ".agent-team" / "artifacts" / "milestone-1-wave-C.json").write_text(
        json.dumps(
            {
                "wave": "C",
                "contract_fidelity": "degraded",
                "client_fidelity": "degraded",
                "client_generator": "minimal-ts",
            }
        ),
        encoding="utf-8",
    )
    (run / ".agent-team" / "milestones" / "milestone-1" / "WAVE_FINDINGS.json").write_text(
        json.dumps({"milestone_id": "milestone-1", "wave_t_status": "skipped"}),
        encoding="utf-8",
    )

    audit = audit_run_directory(run)

    assert audit["clean"] is False
    codes = {issue["code"] for issue in audit["issues"]}
    assert "EXIT-CODE" in codes
    assert "WAVE-C-DEGRADED" in codes
    assert "WAVE-T-STATUS" in codes


def test_audit_run_directory_rejects_codex_fallback_and_scope(tmp_path: Path) -> None:
    telemetry_dir = tmp_path / ".agent-team" / "telemetry"
    telemetry_dir.mkdir(parents=True)
    (tmp_path / ".agent-team" / "milestones" / "milestone-1").mkdir(parents=True)
    (telemetry_dir / "milestone-1-wave-D.json").write_text(
        json.dumps(
            {
                "wave": "D",
                "success": True,
                "provider": "codex",
                "fallback_used": True,
                "fallback_reason": "fixture",
                "scope_violations": ["packages/api-client/index.ts"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".agent-team" / "milestones" / "milestone-1" / "WAVE_FINDINGS.json").write_text(
        json.dumps({"milestone_id": "milestone-1", "wave_t_status": "completed"}),
        encoding="utf-8",
    )

    audit = audit_run_directory(tmp_path)

    codes = {issue["code"] for issue in audit["issues"]}
    assert "CODEX-FALLBACK" in codes
    assert "SCOPE-VIOLATIONS" in codes


def test_scan_frontend_raw_api_usage_detects_manual_fetch(tmp_path: Path) -> None:
    page = tmp_path / "apps" / "web" / "src" / "app" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text(
        "import { getProjects } from '@taskflow/api-client';\n"
        "export async function load() { return fetch('/api/projects'); }\n",
        encoding="utf-8",
    )

    assert scan_frontend_raw_api_usage(tmp_path) == ["apps/web/src/app/page.tsx"]


def test_audit_run_directory_reads_utf16_build_log(tmp_path: Path) -> None:
    """Windows PowerShell writes BUILD_LOG.txt as UTF-16 LE with BOM. The
    auditor must substring-search the log (e.g. for Context7 quota
    messages) without crashing on the BOM. Before this fix, Gate 5 of
    the fast-forward harness aborted with UnicodeDecodeError whenever
    any real Windows smoke run directory was on disk.
    """
    run = tmp_path
    (run / ".agent-team" / "milestones" / "milestone-1").mkdir(parents=True)
    (run / ".agent-team" / "milestones" / "milestone-1" / "WAVE_FINDINGS.json").write_text(
        json.dumps({"milestone_id": "milestone-1", "wave_t_status": "completed"}),
        encoding="utf-8",
    )
    # UTF-16 LE with BOM, mimicking PowerShell's default redirection.
    (run / "BUILD_LOG.txt").write_bytes(
        "Context7 monthly quota exceeded for lib=nestjs\n".encode("utf-16")
    )
    (run / "BUILD_ERR.txt").write_bytes(b"\xff\xfe")  # BOM-only empty err log

    audit = audit_run_directory(run)

    codes = {issue["code"] for issue in audit["issues"]}
    # The Context7 quota text must be visible to the auditor — the known
    # waiver should trigger a warning, not crash the harness.
    assert "CONTEXT7-NONQUOTA" not in codes
    warning_codes = {w["code"] for w in audit.get("warnings", [])}
    assert "CONTEXT7-QUOTA-WAIVED" in warning_codes


def test_gate2_fails_when_api_client_runtime_dependency_cannot_resolve(
    tmp_path: Path,
) -> None:
    ctx = _gate2_context(tmp_path)

    def fake_run(command, *, cwd, timeout=300, context=None):
        if "require.resolve('@hey-api/client-fetch/package.json')" in command:
            return CommandResult(
                command=list(command),
                cwd=str(cwd),
                returncode=1,
                stderr_tail="Cannot find module '@hey-api/client-fetch/package.json'",
            )
        return CommandResult(command=list(command), cwd=str(cwd), returncode=0)

    with patch("agent_team_v15.m1_fast_forward._resolve_pnpm", return_value="/fake/pnpm"), \
         patch("agent_team_v15.m1_fast_forward._run", side_effect=fake_run), \
         patch(
             "agent_team_v15.m1_fast_forward.generate_openapi_contracts",
             side_effect=lambda workspace, milestone: _write_gate2_wave_c_outputs(workspace),
         ):
        with pytest.raises(GateFailure, match="api-client runtime dependency resolver failed"):
            _gate2_wave_c(ctx)


def test_gate2_runs_post_wave_c_relink_resolver_and_targeted_tsc(
    tmp_path: Path,
) -> None:
    ctx = _gate2_context(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, timeout=300, context=None):
        commands.append(list(command))
        return CommandResult(command=list(command), cwd=str(cwd), returncode=0, stdout_tail="/resolved/path")

    with patch("agent_team_v15.m1_fast_forward._resolve_pnpm", return_value="/fake/pnpm"), \
         patch("agent_team_v15.m1_fast_forward._run", side_effect=fake_run), \
         patch(
             "agent_team_v15.m1_fast_forward.generate_openapi_contracts",
             side_effect=lambda workspace, milestone: _write_gate2_wave_c_outputs(workspace),
         ):
        details = _gate2_wave_c(ctx)

    assert commands.count(["/fake/pnpm", "install", "--frozen-lockfile"]) == 2
    assert [
        "/fake/pnpm",
        "--filter",
        "@taskflow/api-client",
        "exec",
        "node",
        "-p",
        "require.resolve('@hey-api/client-fetch/package.json')",
    ] in commands
    tsc_commands = [
        command for command in commands if command and command[0].endswith("/apps/web/node_modules/.bin/tsc")
    ]
    assert len(tsc_commands) == 1
    assert "packages/api-client/client.gen.ts" in tsc_commands[0]
    assert "packages/api-client/sdk.gen.ts" in tsc_commands[0]
    assert details["api_client_runtime_dependency"]["returncode"] == 0
    assert details["api_client_generated_tsc"]["returncode"] == 0
