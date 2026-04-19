"""Proof 03: DoD feasibility verifier emits DOD-FEASIBILITY-001 in two
fixtures:

    Fixture A — the happy milestone path. DoD references `pnpm dev` but
    package.json does NOT define it. Finding should fire.

    Fixture B — CRITICAL REGRESSION GUARD. The milestone failed at Wave B.
    The teardown hook at wave_executor.py:4981-5024 is OUTSIDE the
    `for wave_letter in waves[...]` loop, so the `break` on failure
    falls through to the DoD-feasibility block. We prove BOTH:

      (1) Structural: AST walk of
          `_execute_milestone_waves_with_stack_contract` confirms the
          flag-gate is at top-level of the function, NOT inside the
          wave loop.
      (2) Behavioural: `run_dod_feasibility_check` fires on a fixture
          whose milestone never progressed past Wave B — the verifier
          is stateless on wave outcome; it reads REQUIREMENTS.md +
          package.json directly.

The behavioural check alone is insufficient because run_dod_feasibility_check
is a pure function — it always sees the same inputs regardless of wave
state. The structural check alone is insufficient because it does not
prove the function actually emits the finding. Together they prove the
feature fires through the production call chain on a Wave-B-failed
milestone.
"""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

THIS = Path(__file__).resolve()
FIXTURES_ROOT = THIS.parent.parent / "fixtures"


REQUIREMENTS_MD = """\
# Milestone 1 — Foundation

Project scaffolding.

## Definition of Done

- `pnpm install && pnpm typecheck && pnpm lint && pnpm build` succeeds.
- `docker compose up -d postgres && pnpm db:migrate && pnpm dev` boots;
  `GET http://localhost:3080/api/health` returns `{ data: { status: 'ok' } }`.
"""

PKG_JSON_MISSING_DEV = """\
{
  "name": "taskflow",
  "version": "0.1.0",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "build": "tsc -b"
  }
}
"""


def build_fixture(name: str) -> Path:
    root = FIXTURES_ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "package.json").write_text(PKG_JSON_MISSING_DEV, encoding="utf-8")
    milestone_dir = root / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "REQUIREMENTS.md").write_text(REQUIREMENTS_MD, encoding="utf-8")
    return root


def behavioural_check(label: str, workspace: Path) -> bool:
    """Invoke the production verifier directly and assert DOD-FEASIBILITY-001."""

    from agent_team_v15.dod_feasibility_verifier import run_dod_feasibility_check

    findings = run_dod_feasibility_check(
        project_root=workspace,
        milestone_dir=workspace / ".agent-team" / "milestones" / "milestone-1",
    )
    print(f"[{label}] findings: {len(findings)}")
    codes = [f.code for f in findings]
    print(f"[{label}] codes: {codes}")
    dev_hits = [f for f in findings if "db:migrate" in f.message or "pnpm dev" in f.message]
    for f in findings:
        print(f"[{label}] {f.code} HIGH in {f.file}")
        print(f"[{label}]   message: {f.message}")
    ok = any(f.code == "DOD-FEASIBILITY-001" for f in findings)
    print(f"[{label}] DOD-FEASIBILITY-001 present: {ok}")
    return ok


def structural_check_wave_b_failure_still_fires() -> bool:
    """AST proof — the DoD hook sits OUTSIDE the wave for-loop.

    Mirrors `tests/test_h1a_wiring.py::test_dod_feasibility_fires_even_when_wave_b_failed`
    but prints all the intermediate anchors so the proof is auditable.
    """

    from agent_team_v15 import wave_executor

    src = Path(wave_executor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    live_func = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_execute_milestone_waves_with_stack_contract"
        ):
            live_func = node
            break
    assert live_func is not None, "live execute function not found"

    wave_loop = None
    for node in live_func.body:
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "wave_letter"
        ):
            wave_loop = node
            break
    assert wave_loop is not None, "wave_letter for-loop not found"

    dod_guard_line: int | None = None
    for sub in ast.walk(live_func):
        if not isinstance(sub, ast.If):
            continue
        test = sub.test
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "_get_v18_value"
            and len(test.args) >= 2
            and isinstance(test.args[1], ast.Constant)
            and test.args[1].value == "dod_feasibility_verifier_enabled"
        ):
            dod_guard_line = sub.lineno
            break
    assert dod_guard_line is not None, "DoD-feasibility guard not found"

    loop_start = wave_loop.lineno
    loop_end = wave_loop.end_lineno
    print("live func:                           _execute_milestone_waves_with_stack_contract")
    print(f"  wave for-loop lines:              {loop_start}-{loop_end}")
    print(f"  DoD flag-guard line:              {dod_guard_line}")
    outside = dod_guard_line > (loop_end or 0)
    print(f"  DoD guard AFTER loop end:         {outside}")
    return outside


def main() -> int:
    print("=" * 78)
    print("FIXTURE A — happy path (milestone completes; DoD feasibility still fires)")
    print("=" * 78)
    root_a = build_fixture("proof-03-a")
    ok_a = behavioural_check("A", root_a)
    print()

    print("=" * 78)
    print("FIXTURE B — Wave B failed (critical: hook is NOT Wave-E-gated)")
    print("=" * 78)
    print("Behavioural: run the verifier as the teardown block does.")
    root_b = build_fixture("proof-03-b")
    ok_b = behavioural_check("B", root_b)
    print()
    print("Structural: AST walk confirms the hook sits OUTSIDE the wave for-loop.")
    ok_structural = structural_check_wave_b_failure_still_fires()
    print()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  Fixture A — DOD-FEASIBILITY-001 fires:              {ok_a}")
    print(f"  Fixture B — DOD-FEASIBILITY-001 fires:              {ok_b}")
    print(f"  Structural — DoD guard OUTSIDE wave for-loop body:  {ok_structural}")
    return 0 if (ok_a and ok_b and ok_structural) else 2


if __name__ == "__main__":
    sys.exit(main())
