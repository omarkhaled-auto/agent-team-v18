"""Proof 06: RUNTIME-TAUTOLOGY-001 via the production entry point
``cli._runtime_tautology_finding``.

Fixture compose:
  services:
    api:
      depends_on: [postgres]
    postgres: ...
    postgres_test: ...   (NOT in api's depends_on closure)

Simulated runtime: only postgres is running (api missing).

Expected: the critical-path walk identifies {api, postgres}, flags
api as absent, ignores postgres_test entirely.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

THIS = Path(__file__).resolve()
FIXTURE = THIS.parent.parent / "fixtures" / "proof-06"


COMPOSE_YAML = """\
services:
  api:
    image: taskflow-api:latest
    ports:
      - "3080:3080"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PORT: "3080"
  postgres:
    image: postgres:15
    healthcheck:
      test: ["CMD", "pg_isready"]
  postgres_test:
    image: postgres:15
    healthcheck:
      test: ["CMD", "pg_isready"]
"""


def build_fixture() -> Path:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    (FIXTURE / "docker-compose.yml").write_text(COMPOSE_YAML, encoding="utf-8")
    return FIXTURE


def make_rv_report_only_postgres_running():
    """Simulate the runtime-verifier report: only postgres is up.

    api is absent from the running set (not healthy). postgres_test is
    separately healthy (informational — must NOT contribute to finding).
    """

    return SimpleNamespace(
        services_total=2,
        services_healthy=1,
        total_duration_s=3.0,
        services_status=[
            SimpleNamespace(service="postgres", healthy=True, error=""),
            SimpleNamespace(service="postgres_test", healthy=True, error=""),
            # api is absent from the running set
        ],
    )


def main() -> int:
    from agent_team_v15.cli import _runtime_tautology_finding

    root = build_fixture()
    rv_report = make_rv_report_only_postgres_running()

    cfg = SimpleNamespace(
        v18=SimpleNamespace(runtime_tautology_guard_enabled=True),
        runtime_verification=SimpleNamespace(compose_file=""),
    )

    print("Invoking cli._runtime_tautology_finding (production entry point)")
    print(f"  compose: {root/'docker-compose.yml'}")
    print(f"  critical path expected: {{api, postgres}}")
    print(f"  running services (rv_report): postgres=healthy, postgres_test=healthy, api=absent")
    print()

    finding = _runtime_tautology_finding(root, rv_report, cfg)
    print(f"finding string: {finding!r}")
    print()

    # Assertions
    fires = finding is not None and "RUNTIME-TAUTOLOGY-001" in finding
    names_api = finding is not None and "api" in finding.lower()
    ignores_postgres_test = finding is None or "postgres_test" not in finding

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  RUNTIME-TAUTOLOGY-001 emitted:                 {fires}")
    print(f"  finding names api:                             {names_api}")
    print(f"  finding does NOT mention postgres_test:        {ignores_postgres_test}")
    return 0 if (fires and names_api and ignores_postgres_test) else 2


if __name__ == "__main__":
    sys.exit(main())
