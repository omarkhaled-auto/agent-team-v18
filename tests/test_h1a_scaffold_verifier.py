"""Phase H1a Item 2 — scaffold_verifier compose + DoD-port checks.

Guards two new checks plugged into run_scaffold_verifier:

* SCAFFOLD-COMPOSE-001 — docker-compose.yml must include ``services.api``.
  Before h1a the verifier silently passed when the api service was absent
  (smoke #11 class). The new ``_check_compose_topology`` closes that hole.

* SCAFFOLD-PORT-002 — when a milestone REQUIREMENTS.md carries a canonical
  DoD port (``http://localhost:<PORT>/...``), that port — not
  ``scaffold_cfg.port`` — is the source of truth for the port-consistency
  invariant. Smoke #11: DoD said 3080, scaffold bound to 4000; verifier
  should have FAILed but instead silently PASSed.

Existing _check_port_consistency behaviour is kept as a regression guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.milestone_scope import MilestoneScope
from agent_team_v15.scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    FileOwnership,
    OwnershipContract,
    ScaffoldConfig,
)
from agent_team_v15.scaffold_verifier import run_scaffold_verifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_contract() -> OwnershipContract:
    """Contract with no required scaffold rows — isolates topology/port checks."""

    return OwnershipContract(files=tuple())


def _contract_with(paths: list[tuple[str, str, bool]]) -> OwnershipContract:
    return OwnershipContract(
        files=tuple(
            FileOwnership(path=p, owner=owner, optional=optional)
            for p, owner, optional in paths
        )
    )


def _minimal_compose_with_api(workspace: Path, port: int = 4000) -> None:
    (workspace / "docker-compose.yml").write_text(
        f"""services:
  postgres:
    image: postgres:15
  api:
    build:
      context: ./apps/api
    ports:
      - "{port}:{port}"
    environment:
      PORT: "{port}"
    depends_on:
      postgres:
        condition: service_healthy
""",
        encoding="utf-8",
    )


def _compose_without_api(workspace: Path) -> None:
    (workspace / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:15\n",
        encoding="utf-8",
    )


def _write_port_files(workspace: Path, port: int) -> None:
    api_src = workspace / "apps" / "api" / "src"
    api_src.mkdir(parents=True, exist_ok=True)
    (api_src / "main.ts").write_text(
        f"async function bootstrap() {{ await app.listen(process.env.PORT ?? {port}); }}\n"
        "NestFactory.create(AppModule);\n",
        encoding="utf-8",
    )
    (api_src / "config").mkdir(parents=True, exist_ok=True)
    (api_src / "config" / "env.validation.ts").write_text(
        f"PORT: Joi.number().default({port})\n",
        encoding="utf-8",
    )
    (workspace / ".env.example").write_text(f"PORT={port}\n", encoding="utf-8")
    (workspace / "apps" / "api" / ".env.example").write_text(
        f"PORT={port}\n", encoding="utf-8"
    )


def _write_requirements(workspace: Path, milestone_id: str, body: str) -> Path:
    req_dir = workspace / ".agent-team" / "milestones" / milestone_id
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / "REQUIREMENTS.md"
    req_path.write_text(body, encoding="utf-8")
    return req_path


# ---------------------------------------------------------------------------
# SCAFFOLD-COMPOSE-001 — api-service topology
# ---------------------------------------------------------------------------


def test_compose_with_api_passes_topology(tmp_path: Path) -> None:
    _minimal_compose_with_api(tmp_path, port=4000)
    _write_port_files(tmp_path, port=4000)
    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
    )
    assert all(
        "SCAFFOLD-COMPOSE-001" not in line for line in report.summary_lines
    ), f"topology check fired incorrectly: {report.summary_lines}"


def test_compose_without_api_triggers_topology_finding(tmp_path: Path) -> None:
    _compose_without_api(tmp_path)
    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
    )
    assert report.verdict == "FAIL"
    assert any(
        "SCAFFOLD-COMPOSE-001" in line and "services.api" in line
        for line in report.summary_lines
    ), f"expected SCAFFOLD-COMPOSE-001 finding, got: {report.summary_lines}"


def test_compose_missing_entirely_skips_topology(tmp_path: Path) -> None:
    """No docker-compose.yml on disk — topology check is silent (no FAIL
    from the topology source). Upstream MISSING check would catch this if
    compose were in the ownership contract; here we prove the topology
    check itself doesn't crash or fire when the file is absent."""

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
    )
    # No ownership rows → PASS verdict (there is nothing to find missing).
    assert report.verdict == "PASS"
    assert all(
        "SCAFFOLD-COMPOSE-001" not in line for line in report.summary_lines
    )


# ---------------------------------------------------------------------------
# SCAFFOLD-PORT-002 — DoD-port oracle
# ---------------------------------------------------------------------------


def test_dod_port_overrides_scaffold_cfg_and_triggers_drift(tmp_path: Path) -> None:
    """REQUIREMENTS.md says 3080, scaffold files say 4000 — the DoD port
    wins and the port-consistency check must FAIL."""

    _write_port_files(tmp_path, port=4000)
    _minimal_compose_with_api(tmp_path, port=4000)
    _write_requirements(
        tmp_path,
        "milestone-1",
        "# M1\n\n## Definition of Done\n\n- `GET http://localhost:3080/api/health` returns ok.\n",
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=ScaffoldConfig(port=4000),
        milestone_id="milestone-1",
    )
    assert report.verdict == "FAIL"
    assert any(
        "SCAFFOLD-PORT-002" in line and "3080" in line
        for line in report.summary_lines
    ), f"expected SCAFFOLD-PORT-002 with port=3080, got: {report.summary_lines}"


def test_requirements_missing_dod_warns_and_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """REQUIREMENTS.md exists but carries no parseable DoD port — the
    verifier must log a WARN and fall back to scaffold_cfg.port."""

    _write_port_files(tmp_path, port=4000)
    _minimal_compose_with_api(tmp_path, port=4000)
    _write_requirements(
        tmp_path,
        "milestone-1",
        "# M1\n\nNo DoD block.\n",
    )

    with caplog.at_level("WARNING", logger="agent_team_v15.scaffold_verifier"):
        report = run_scaffold_verifier(
            workspace=tmp_path,
            ownership_contract=_empty_contract(),
            scaffold_cfg=ScaffoldConfig(port=4000),
            milestone_id="milestone-1",
        )
    assert report.verdict == "PASS"
    assert any(
        "no parseable DoD" in rec.getMessage() for rec in caplog.records
    ), f"expected DoD-port WARN; got: {[r.getMessage() for r in caplog.records]}"


def test_requirements_unparseable_dod_port_falls_back(tmp_path: Path) -> None:
    """DoD block exists but port anchor is malformed — fall back to
    scaffold_cfg.port and do not emit SCAFFOLD-PORT-002."""

    _write_port_files(tmp_path, port=4000)
    _minimal_compose_with_api(tmp_path, port=4000)
    _write_requirements(
        tmp_path,
        "milestone-1",
        "# M1\n\n## Definition of Done\n\n- Hits `GET http://example.test/nope` and passes.\n",
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=ScaffoldConfig(port=4000),
        milestone_id="milestone-1",
    )
    assert report.verdict == "PASS"
    assert all(
        "SCAFFOLD-PORT-002" not in line for line in report.summary_lines
    )


def test_dod_port_matching_scaffold_cfg_does_not_fire(tmp_path: Path) -> None:
    """Happy-path: DoD port matches scaffold_cfg — no PORT-002."""

    _write_port_files(tmp_path, port=4000)
    _minimal_compose_with_api(tmp_path, port=4000)
    _write_requirements(
        tmp_path,
        "milestone-1",
        "# M1\n\n## Definition of Done\n\n- `GET http://localhost:4000/api/health` ok.\n",
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=ScaffoldConfig(port=4000),
        milestone_id="milestone-1",
    )
    assert report.verdict == "PASS"


# ---------------------------------------------------------------------------
# Regression: existing _check_port_consistency still works
# ---------------------------------------------------------------------------


def test_existing_port_consistency_still_flags_mismatch(tmp_path: Path) -> None:
    """Two different PORT values in the PORT-bearing files → SCAFFOLD-PORT-002.

    This guards the regression path that was in place before h1a."""

    api_src = tmp_path / "apps" / "api" / "src"
    api_src.mkdir(parents=True, exist_ok=True)
    (api_src / "main.ts").write_text(
        "await app.listen(process.env.PORT ?? 4000);\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text("PORT=3080\n", encoding="utf-8")
    _minimal_compose_with_api(tmp_path, port=4000)
    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=_empty_contract(),
        scaffold_cfg=ScaffoldConfig(port=4000),
    )
    # The .env.example says 3080, others say 4000 — mismatch.
    assert report.verdict == "FAIL"
    assert any(
        "SCAFFOLD-PORT-002" in line for line in report.summary_lines
    )
