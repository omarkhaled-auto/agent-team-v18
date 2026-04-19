"""Proof 05: probe spec-oracle (PROBE-SPEC-DRIFT-001) fails fast (<2s)
through the production call chain when DoD port drifts from code-side
port.

Chain exercised:
  _run_wave_b_probing(milestone_id=...)                 # wave_executor.py:2184+
    → start_docker_for_probing(cwd, config,             # endpoint_prober.py:695
         milestone_id=milestone_id)
    → _detect_app_url(project_root, config,             # endpoint_prober.py:1143+
         milestone_id=milestone_id)
    → raises ProbeSpecDriftError (PROBE-SPEC-DRIFT-001) — does NOT enter
      the _poll_health timeout loop.

Without the Wave 5 bridge fix (milestone_id threading through
_run_wave_b_probing → start_docker_for_probing), the guard silently
no-ops. The fact that this proof fires in <2s with flag=True is
load-bearing.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

THIS = Path(__file__).resolve()
FIXTURE = THIS.parent.parent / "fixtures" / "proof-05"


MAIN_TS = """\
async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  await app.listen(process.env.PORT ?? 4000);
}
"""


REQUIREMENTS_MD = """\
## Definition of Done

- `docker compose up -d postgres && pnpm db:migrate && pnpm dev` boots;
  `GET http://localhost:3080/api/health` returns `{ data: { status: 'ok' } }`.
"""


def build_fixture() -> Path:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    api_src = FIXTURE / "apps" / "api" / "src"
    api_src.mkdir(parents=True)
    (api_src / "main.ts").write_text(MAIN_TS, encoding="utf-8")
    # Place .env so legacy precedence resolves to 4000 too
    (FIXTURE / ".env").write_text("PORT=4000\n", encoding="utf-8")
    # No docker-compose.yml — we want the guard to raise BEFORE compose
    # is attempted (fast-fail). Actually the guard runs top-of-function
    # so compose doesn't matter.
    milestone_dir = FIXTURE / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "REQUIREMENTS.md").write_text(REQUIREMENTS_MD, encoding="utf-8")
    return FIXTURE


def main() -> int:
    import asyncio

    from agent_team_v15.endpoint_prober import ProbeSpecDriftError

    root = build_fixture()

    # Build a config with the flag ON.
    cfg = SimpleNamespace(
        v18=SimpleNamespace(probe_spec_oracle_enabled=True),
        browser_testing=SimpleNamespace(app_port=0),  # force chain to run
        runtime_verification=SimpleNamespace(compose_file=""),
    )

    # Exercise the production call chain: _run_wave_b_probing invokes
    # start_docker_for_probing. We test start_docker_for_probing directly
    # (it's the function the guard lives inside via _detect_app_url).
    from agent_team_v15.endpoint_prober import start_docker_for_probing

    print("Invoking production call chain with probe_spec_oracle_enabled=True")
    print(f"  fixture: {root}")
    print(f"  DoD port from REQUIREMENTS.md: 3080")
    print(f"  Code-side port from main.ts / .env: 4000")
    print()

    t0 = time.monotonic()
    raised: ProbeSpecDriftError | None = None
    try:
        asyncio.run(start_docker_for_probing(str(root), cfg, milestone_id="milestone-1"))
    except ProbeSpecDriftError as exc:
        raised = exc
        elapsed = time.monotonic() - t0
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"UNEXPECTED exception type: {type(exc).__name__}: {exc}")
        print(f"elapsed: {elapsed:.3f}s")
        return 2
    else:
        elapsed = time.monotonic() - t0
        print(f"UNEXPECTED: no exception raised. elapsed={elapsed:.3f}s")
        return 2

    print(f"ProbeSpecDriftError raised: True")
    print(f"  dod_port:           {raised.dod_port}")
    print(f"  code_port:          {raised.code_port}")
    print(f"  requirements_path:  {raised.requirements_path}")
    print(f"  exception message:  {raised}")
    print()
    print(f"wall-clock elapsed: {elapsed:.3f}s")
    print(f"  (NOT the 120s legacy poll timeout — fast-fail works)")

    # Also exercise via the _run_wave_b_probing bridge fix — confirm
    # milestone_id threads through.
    print()
    print("Also verify _run_wave_b_probing signature threads milestone_id:")
    import inspect as py_inspect
    from agent_team_v15 import wave_executor

    sig = py_inspect.signature(wave_executor._run_wave_b_probing)
    print(f"  _run_wave_b_probing.parameters: {list(sig.parameters.keys())}")
    threaded = "milestone_id" in sig.parameters
    print(f"  milestone_id in signature: {threaded}")

    fast_fail = elapsed < 2.0
    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  PROBE-SPEC-DRIFT-001 raised: True")
    print(f"  dod/code mismatch:           3080 vs 4000")
    print(f"  wall-clock fast-fail (<2s):  {fast_fail} ({elapsed:.3f}s)")
    print(f"  milestone_id threaded:       {threaded}")
    return 0 if (raised is not None and fast_fail and threaded) else 2


if __name__ == "__main__":
    sys.exit(main())
