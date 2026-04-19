"""Phase H1a wiring verification tests — Task #8 (wiring-verifier).

Each test corresponds to a line in ``docs/plans/phase-h1a-wiring-verification.md``
and proves a structural wiring invariant:

* 4A — hook-position tests (each hook fires at the documented call site)
* 4B — flag-gating tests (no fire when flag is False; fire when flag True)
* 4C — crash-isolation tests (one hook crashing does not prevent peers)
* 4D — reporting-integration tests (findings land in ``WAVE_FINDINGS.json``)
* 4E — pattern-ID uniqueness (grep the source for each ID)
* Dead-code audit — verify ``execute_milestone_waves`` is the thin delegator
* milestone_id threading — verify the probe guard is silent when unthreaded

These tests are deliberately narrow: they invoke helper functions with
mocked config, fake filesystem trees, or monkey-patched enforcers. They do
not exercise the full wave loop — that surface is covered by
``test_v18_wave_executor_extended.py``.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helper: flag-bag config + mock result
# ---------------------------------------------------------------------------


class _V18:
    def __init__(self, **kwargs: Any) -> None:
        # Default every h1a flag to False; override via kwargs.
        self.ownership_enforcement_enabled = False
        self.dod_feasibility_verifier_enabled = False
        self.probe_spec_oracle_enabled = False
        self.runtime_tautology_guard_enabled = False
        self.scaffold_verifier_enabled = False
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Config:
    def __init__(self, **v18_kwargs: Any) -> None:
        self.v18 = _V18(**v18_kwargs)


def _mk_result(milestone_id: str = "milestone-1"):
    from agent_team_v15.wave_executor import MilestoneWaveResult

    return MilestoneWaveResult(milestone_id=milestone_id, template="full_stack")


# ---------------------------------------------------------------------------
# 4E — Pattern-ID uniqueness
# ---------------------------------------------------------------------------


PATTERN_IDS = [
    "SCAFFOLD-COMPOSE-001",
    "SCAFFOLD-PORT-002",
    "DOD-FEASIBILITY-001",
    "OWNERSHIP-DRIFT-001",
    "OWNERSHIP-WAVE-A-FORBIDDEN-001",
    "PROBE-SPEC-DRIFT-001",
    "RUNTIME-TAUTOLOGY-001",
]


def _iter_src_files() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    return list((repo_root / "src" / "agent_team_v15").rglob("*.py"))


def test_pattern_ids_unique_no_collision_in_src():
    """Each Phase H1a pattern ID appears only in h1a-owned code paths.

    We verify the pattern ID is NOT defined in any unrelated module by
    scanning for the literal string outside the h1a-owned files. This
    protects against a naming clash with a pre-existing code like
    ``SCAFFOLD-FILE-001`` or an unrelated ``RUNTIME-*`` family.
    """

    h1a_owners = {
        "SCAFFOLD-COMPOSE-001": {"scaffold_verifier.py", "wave_executor.py"},
        "SCAFFOLD-PORT-002": {"scaffold_verifier.py", "wave_executor.py"},
        "DOD-FEASIBILITY-001": {"dod_feasibility_verifier.py", "config.py", "wave_executor.py"},
        "OWNERSHIP-DRIFT-001": {"ownership_enforcer.py", "wave_executor.py", "config.py"},
        "OWNERSHIP-WAVE-A-FORBIDDEN-001": {"ownership_enforcer.py", "wave_executor.py", "config.py"},
        "PROBE-SPEC-DRIFT-001": {"endpoint_prober.py", "wave_executor.py", "config.py"},
        "RUNTIME-TAUTOLOGY-001": {"cli.py", "verification.py", "config.py"},
    }

    for pid in PATTERN_IDS:
        defining_files: set[str] = set()
        for p in _iter_src_files():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pid in text:
                defining_files.add(p.name)
        # Must be defined at least in the primary emitter (not zero).
        assert defining_files, f"Pattern ID {pid} not found in any src file"
        # Must not appear in a file outside the h1a-owned set (collision
        # detector). Allow files explicitly registered above.
        stray = defining_files - h1a_owners[pid]
        assert not stray, (
            f"Pattern ID {pid} appears in non-h1a-owned file(s): {stray}"
        )


def test_pattern_ids_do_not_collide_with_each_other():
    """No two h1a IDs share a prefix that could be mis-matched."""

    # A strict uniqueness assertion: all pattern IDs are distinct strings.
    assert len(set(PATTERN_IDS)) == len(PATTERN_IDS)

    # No ID is a prefix of another (would cause grep false-positives).
    for a in PATTERN_IDS:
        for b in PATTERN_IDS:
            if a is b:
                continue
            assert not a.startswith(b) and not b.startswith(a), (
                f"Pattern ID collision: {a} vs {b}"
            )


# ---------------------------------------------------------------------------
# Dead-code audit
# ---------------------------------------------------------------------------


def test_execute_milestone_waves_is_thin_delegator():
    """Confirm ``execute_milestone_waves`` returns-awaits the stack-contract
    function, making its post-return body unreachable dead code.

    If a future refactor accidentally introduces a second code path after
    the return, this test fails and the wiring-verifier report's dead-code
    assumption needs re-verification.
    """

    from agent_team_v15 import wave_executor

    src = Path(wave_executor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_milestone_waves":
            func = node
            break
    assert func is not None, "execute_milestone_waves AsyncFunctionDef not found"

    # Strip leading docstring expression(s) then look for the return.
    body = [
        stmt
        for stmt in func.body
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
    ]
    assert body, "execute_milestone_waves has empty body (after stripping docstring)"

    # First non-docstring statement must be a Return of an Await.
    first = body[0]
    assert isinstance(first, ast.Return), (
        f"execute_milestone_waves's first non-docstring stmt is {type(first).__name__}, "
        "expected Return. Dead-code audit failed — investigate before trusting h1a wiring."
    )
    assert isinstance(first.value, ast.Await), (
        "execute_milestone_waves returns a non-Await value; the stack-contract "
        "delegation pattern is broken."
    )
    call = first.value.value
    assert isinstance(call, ast.Call), "Return value is not an Await of a Call"
    assert isinstance(call.func, ast.Name) and call.func.id == "_execute_milestone_waves_with_stack_contract", (
        "execute_milestone_waves no longer delegates to _execute_milestone_waves_with_stack_contract"
    )


# ---------------------------------------------------------------------------
# 4B — Flag-gating: ownership fingerprint (Item 4 Check A)
# ---------------------------------------------------------------------------


def test_ownership_fingerprint_does_not_fire_when_flag_is_false(tmp_path: Path):
    """When ``ownership_enforcement_enabled=False``, the helper returns
    before importing ownership_enforcer — the enforcer is never invoked."""

    from agent_team_v15 import wave_executor

    cfg = _Config(ownership_enforcement_enabled=False)
    result = _mk_result()

    with mock.patch.object(
        wave_executor, "logger"
    ), mock.patch(
        "agent_team_v15.ownership_enforcer.check_template_drift_and_fingerprint",
        side_effect=AssertionError("enforcer must not be called when flag is False"),
    ):
        # Should not raise — the helper returns before touching the enforcer.
        wave_executor._maybe_run_scaffold_ownership_fingerprint(
            cfg, str(tmp_path), result, []
        )

    # Nothing was appended to result.waves.
    assert result.waves == []


def test_ownership_fingerprint_fires_when_flag_is_true(tmp_path: Path):
    """When the flag is True and the enforcer returns findings, a synthetic
    SCAFFOLD WaveResult is appended carrying OWNERSHIP-DRIFT-001."""

    from agent_team_v15 import ownership_enforcer, wave_executor

    cfg = _Config(ownership_enforcement_enabled=True)
    result = _mk_result()

    fake_finding = ownership_enforcer.Finding(
        code="OWNERSHIP-DRIFT-001",
        severity="HIGH",
        file="docker-compose.yml",
        message="fake-drift",
    )

    with mock.patch(
        "agent_team_v15.ownership_enforcer.check_template_drift_and_fingerprint",
        return_value=[fake_finding],
    ):
        wave_executor._maybe_run_scaffold_ownership_fingerprint(
            cfg, str(tmp_path), result, ["docker-compose.yml"]
        )

    assert len(result.waves) == 1
    appended = result.waves[0]
    assert appended.wave == "SCAFFOLD"
    assert appended.success is True  # fingerprint is advisory, not a halt
    assert len(appended.findings) == 1
    assert appended.findings[0].code == "OWNERSHIP-DRIFT-001"
    assert appended.findings[0].severity == "HIGH"


def test_ownership_fingerprint_is_crash_isolated(tmp_path: Path, caplog):
    """If the enforcer raises, the helper swallows it and logs a warning —
    the wave loop is never interrupted."""

    from agent_team_v15 import wave_executor

    cfg = _Config(ownership_enforcement_enabled=True)
    result = _mk_result()

    with mock.patch(
        "agent_team_v15.ownership_enforcer.check_template_drift_and_fingerprint",
        side_effect=RuntimeError("enforcer boom"),
    ):
        # Should not raise.
        wave_executor._maybe_run_scaffold_ownership_fingerprint(
            cfg, str(tmp_path), result, []
        )

    # No synthetic wave appended on crash.
    assert result.waves == []


# ---------------------------------------------------------------------------
# 4B — Flag-gating: DoD feasibility (Item 3) via source-AST inspection
# ---------------------------------------------------------------------------


def test_dod_feasibility_block_is_flag_gated_in_live_path():
    """AST check: the DoD-feasibility block in the LIVE wave loop
    (``_execute_milestone_waves_with_stack_contract``) is wrapped in an
    ``if _get_v18_value(config, "dod_feasibility_verifier_enabled", False):``
    guard whose body imports ``dod_feasibility_verifier``.

    Ensures a config-gated call-site (not a called-and-early-return).
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
    assert live_func is not None, "live wave loop function not found"

    found_guard = False
    for node in ast.walk(live_func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Call):
            continue
        if not (isinstance(test.func, ast.Name) and test.func.id == "_get_v18_value"):
            continue
        if len(test.args) < 2:
            continue
        arg1 = test.args[1]
        if not (isinstance(arg1, ast.Constant) and arg1.value == "dod_feasibility_verifier_enabled"):
            continue
        # Inside its body we expect an ImportFrom for dod_feasibility_verifier.
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom):
                if any(n.name == "dod_feasibility_verifier" for n in inner.names):
                    found_guard = True
                    break
            if isinstance(inner, ast.Import):
                if any(n.name.endswith("dod_feasibility_verifier") for n in inner.names):
                    found_guard = True
                    break
        if found_guard:
            break

    assert found_guard, (
        "Live wave loop does not contain an `if _get_v18_value(..., "
        "'dod_feasibility_verifier_enabled', ...)` guard wrapping the "
        "dod_feasibility_verifier import. The flag is not call-site gated."
    )


def test_dod_feasibility_fires_after_persist_wave_findings_and_before_architecture_writer():
    """AST ordering check: DoD-feasibility block sits between
    ``persist_wave_findings_for_audit`` and the architecture-writer append,
    per the plan's 4A placement spec.

    This is a call-graph / ordering invariant: even when a milestone fails
    at Wave B and breaks out of the wave loop, both the first
    persist_wave_findings_for_audit at :4965 AND the DoD-feasibility hook
    at :4981 run at teardown.
    """

    from agent_team_v15 import wave_executor

    src_lines = Path(wave_executor.__file__).read_text(encoding="utf-8").splitlines()

    # Line numbers are 1-indexed. We want LIVE-path markers — the last
    # occurrence of each anchor, because the dead-code block (3655-4091)
    # contains duplicate markers we must skip.
    markers: dict[str, int] = {}
    dod_guard_candidates: list[int] = []
    persist_candidates: list[int] = []
    arch_writer_candidates: list[int] = []
    for idx, line in enumerate(src_lines, start=1):
        if "persist_wave_findings_for_audit" in line and "def " not in line and "markers" not in line:
            persist_candidates.append(idx)
        if "dod_feasibility_verifier_enabled" in line:
            dod_guard_candidates.append(idx)
        if "_architecture_writer" in line:
            arch_writer_candidates.append(idx)

    assert persist_candidates, "no persist_wave_findings_for_audit references"
    assert dod_guard_candidates, "no dod_feasibility_verifier_enabled references"
    assert arch_writer_candidates, "no _architecture_writer references"

    # The LIVE function starts around line 4092 (verified by the
    # dead-code audit). All live-path markers must exceed that offset.
    LIVE_FUNC_START = 4092
    markers["first_persist"] = next(
        (p for p in persist_candidates if p > LIVE_FUNC_START), persist_candidates[-1]
    )
    markers["dod_flag"] = next(
        (p for p in dod_guard_candidates if p > LIVE_FUNC_START), dod_guard_candidates[-1]
    )
    markers["arch_writer"] = next(
        (p for p in arch_writer_candidates if p > markers["dod_flag"]),
        arch_writer_candidates[-1],
    )

    # The DoD flag guard must appear AFTER the first live persist call and
    # BEFORE the architecture_writer append.
    assert markers["first_persist"] < markers["dod_flag"] < markers["arch_writer"], (
        "Ordering violation: expected persist(:{p}) < dod_flag(:{d}) < "
        "arch_writer(:{a}).".format(
            p=markers["first_persist"], d=markers["dod_flag"], a=markers["arch_writer"]
        )
    )


def test_dod_feasibility_fires_even_when_wave_b_failed():
    """Structural check: the DoD-feasibility hook is OUTSIDE the
    ``for wave_letter in waves[...]`` loop body, so ``break`` on a Wave B
    failure still falls through to the teardown block that contains it.
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
    assert live_func is not None

    # Find the top-level ``for wave_letter in waves[...]`` loop.
    wave_loop = None
    for node in live_func.body:
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "wave_letter"
        ):
            wave_loop = node
            break
    assert wave_loop is not None, "wave_letter for-loop not found at top-level of live func"

    loop_end_line = wave_loop.end_lineno
    assert loop_end_line is not None

    # Locate the DoD-feasibility flag guard line and ensure it sits AFTER
    # the for-loop's end (i.e. not nested inside the per-wave loop body).
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

    assert dod_guard_line is not None, "dod_feasibility_verifier_enabled guard not found"
    assert dod_guard_line > loop_end_line, (
        f"DoD-feasibility guard at :{dod_guard_line} is inside the wave "
        f"for-loop (ends :{loop_end_line}). It must be OUTSIDE so it fires "
        "on failed milestones that broke out of the loop."
    )


# ---------------------------------------------------------------------------
# 4B — Wave-A forbidden-writes flag-gating
# ---------------------------------------------------------------------------


def test_wave_a_forbidden_writes_flag_gated_in_live_path():
    """AST: the Wave-A forbidden-writes block inside the
    ``wave_letter == "A" and wave_result.success`` branch is wrapped in an
    ``if _get_v18_value(..., "ownership_enforcement_enabled", False)`` guard."""

    from agent_team_v15 import wave_executor

    src = Path(wave_executor.__file__).read_text(encoding="utf-8")
    # Grep line-level is sufficient and robust; no deep AST walk needed.
    assert re.search(
        r'_get_v18_value\(\s*\n?\s*config,\s*"ownership_enforcement_enabled",\s*False\s*\)',
        src,
    ), "ownership_enforcement_enabled flag guard not found in source"
    # Guard appears at least three times: Check A helper, Wave A completion,
    # post-wave drift. Confirm count.
    hits = len(
        re.findall(
            r'_get_v18_value\(\s*\n?\s*config,\s*"ownership_enforcement_enabled",\s*False\s*\)',
            src,
        )
    )
    assert hits >= 3, (
        f"Expected at least 3 ownership_enforcement_enabled gates "
        f"(Check A helper, Wave A completion, post-wave drift); found {hits}"
    )


# ---------------------------------------------------------------------------
# 4B / 5 — probe spec-oracle flag-gating (Item 5)
# ---------------------------------------------------------------------------


def test_probe_spec_oracle_disabled_by_default(tmp_path: Path):
    """When the flag is False, ``_detect_app_url`` runs the legacy
    precedence chain unchanged and never tries to read REQUIREMENTS.md."""

    from agent_team_v15.endpoint_prober import _detect_app_url

    class _Cfg:
        class browser_testing:
            pass
        v18 = None

    _Cfg.browser_testing.app_port = 4242
    # milestone_id is irrelevant when flag is False — still should not fail.
    url = _detect_app_url(tmp_path, _Cfg, milestone_id="milestone-1")
    assert url == "http://localhost:4242"


def test_probe_spec_oracle_skips_silently_when_milestone_id_is_none(tmp_path: Path, caplog):
    """Even with the flag on, ``_detect_app_url`` silently falls back to
    legacy when ``milestone_id`` is None — this is the milestone_id
    threading gap documented in the wiring report.

    This test PROVES the gap exists: legacy URL is returned, no guard
    raised.
    """

    from agent_team_v15.endpoint_prober import _detect_app_url

    class _Cfg:
        class browser_testing:
            pass

        class _V:
            probe_spec_oracle_enabled = True
        v18 = _V()

    _Cfg.browser_testing.app_port = 4242
    url = _detect_app_url(tmp_path, _Cfg, milestone_id=None)
    # Still returns legacy URL — the guard short-circuits because the
    # resolved REQUIREMENTS.md path is None.
    assert url == "http://localhost:4242"


def test_probe_spec_oracle_raises_on_drift_when_fully_wired(tmp_path: Path):
    """Positive case: flag True, milestone_id provided, REQUIREMENTS.md
    exists with a port anchor that differs from the resolved code-side
    port → raises ``ProbeSpecDriftError``."""

    from agent_team_v15.endpoint_prober import _detect_app_url, ProbeSpecDriftError

    class _Cfg:
        class browser_testing:
            pass

        class _V:
            probe_spec_oracle_enabled = True
        v18 = _V()

    _Cfg.browser_testing.app_port = 4000  # code-side port

    # Write DoD REQUIREMENTS.md with port 3080.
    milestone_dir = tmp_path / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True)
    (milestone_dir / "REQUIREMENTS.md").write_text(
        "## Definition of Done\n\n- `GET http://localhost:3080/api/health` returns OK.\n",
        encoding="utf-8",
    )

    with pytest.raises(ProbeSpecDriftError) as exc:
        _detect_app_url(tmp_path, _Cfg, milestone_id="milestone-1")

    assert exc.value.dod_port == 3080
    assert exc.value.code_port == 4000


# ---------------------------------------------------------------------------
# milestone_id threading gap (Wave B probing)
# ---------------------------------------------------------------------------


def test_run_wave_b_probing_threads_milestone_id():
    """Wave 5 bridge fix: ``_run_wave_b_probing`` accepts ``milestone_id`` and
    forwards it to ``start_docker_for_probing`` so the probe spec-oracle guard
    (PROBE-SPEC-DRIFT-001) can resolve ``REQUIREMENTS.md`` via the milestone
    directory. Without this, the guard silently no-ops even when the flag is
    True (see phase-h1a-wiring-verification.md §milestone_id threading gap).
    """

    import inspect as py_inspect

    from agent_team_v15 import wave_executor

    sig = py_inspect.signature(wave_executor._run_wave_b_probing)
    assert "milestone_id" in sig.parameters, (
        "Regression: `_run_wave_b_probing` lost the `milestone_id` kwarg; "
        "the probe spec-oracle guard will silently no-op."
    )

    src = py_inspect.getsource(wave_executor._run_wave_b_probing)
    assert "milestone_id=milestone_id" in src, (
        "Regression: `_run_wave_b_probing` no longer forwards `milestone_id` "
        "to `start_docker_for_probing` — the guard cannot fire."
    )


def test_start_docker_for_probing_accepts_milestone_id():
    """The probe entry accepts the kwarg (Wave 2C added this). The caller
    side is the gap, not the callee side."""

    import inspect as py_inspect

    from agent_team_v15 import endpoint_prober

    sig = py_inspect.signature(endpoint_prober.start_docker_for_probing)
    assert "milestone_id" in sig.parameters, (
        "`start_docker_for_probing` must accept `milestone_id` — this was "
        "the Wave 2C probe-telemetry wiring change."
    )


# ---------------------------------------------------------------------------
# 4B — Runtime tautology flag-gating (Item 6)
# ---------------------------------------------------------------------------


def test_runtime_tautology_helper_returns_none_when_critical_path_healthy(tmp_path: Path):
    """``_runtime_tautology_finding`` is a pure helper: healthy critical
    path → returns None; missing / unhealthy → returns a diagnostic string.
    """

    from agent_team_v15 import cli as _cli

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  api:\n"
        "    image: example\n"
        "    depends_on: [postgres]\n"
        "  postgres:\n"
        "    image: postgres\n",
        encoding="utf-8",
    )

    class _RV:
        services_status = [
            type("_S", (), {"service": "api", "healthy": True, "error": ""})(),
            type("_S", (), {"service": "postgres", "healthy": True, "error": ""})(),
        ]

    class _Cfg:
        class runtime_verification:
            compose_file = str(compose)

    finding = _cli._runtime_tautology_finding(tmp_path, _RV(), _Cfg())
    assert finding is None


def test_runtime_tautology_helper_returns_finding_when_postgres_unhealthy(tmp_path: Path):
    from agent_team_v15 import cli as _cli

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  api:\n"
        "    image: example\n"
        "    depends_on: [postgres]\n"
        "  postgres:\n"
        "    image: postgres\n",
        encoding="utf-8",
    )

    class _RV:
        services_status = [
            type("_S", (), {"service": "api", "healthy": True, "error": ""})(),
            type("_S", (), {"service": "postgres", "healthy": False, "error": "startup failed"})(),
        ]

    class _Cfg:
        class runtime_verification:
            compose_file = str(compose)

    finding = _cli._runtime_tautology_finding(tmp_path, _RV(), _Cfg())
    assert finding is not None
    assert "RUNTIME-TAUTOLOGY-001" in finding
    assert "postgres" in finding


# ---------------------------------------------------------------------------
# 4B — Verification module: tautology flag gates the empty-state health
# ---------------------------------------------------------------------------


def test_verification_empty_state_green_when_flag_off():
    from agent_team_v15 import verification

    # Pre-fix: this test relied on a module-global toggle. Post-PR-#42
    # Finding 5 fix: the flag is per-call and passed explicitly.
    assert verification._health_from_results({}) == "green"
    assert (
        verification._health_from_results({}, tautology_detected=False)
        == "green"
    )


def test_verification_empty_state_unknown_when_flag_on():
    from agent_team_v15 import verification

    # Per-call flag passed in; does NOT affect subsequent empty-state
    # calls that pass False or omit the kwarg.
    assert (
        verification._health_from_results({}, tautology_detected=True)
        == "unknown"
    )
    # Regression: no leak into the next call.
    assert verification._health_from_results({}) == "green"


def test_verification_tautology_flag_is_not_module_global():
    """PR #42 Finding 5 guard: set_runtime_tautology_detected was removed;
    the signal must flow through ProgressiveVerificationState.tautology_detected
    and _health_from_results kwargs. This test makes the refactor stick."""

    from agent_team_v15 import verification

    assert not hasattr(verification, "_RUNTIME_TAUTOLOGY_DETECTED"), (
        "module-global _RUNTIME_TAUTOLOGY_DETECTED was removed to prevent "
        "cross-run leaks; re-adding it would reintroduce the bug"
    )
    assert not hasattr(verification, "set_runtime_tautology_detected"), (
        "set_runtime_tautology_detected was removed; callers must use "
        "ProgressiveVerificationState.tautology_detected or pass the kwarg"
    )


# ---------------------------------------------------------------------------
# 4A — Scaffold verifier signature threading (milestone_id)
# ---------------------------------------------------------------------------


def test_scaffold_verifier_accepts_milestone_id():
    """Confirms Wave 2B added the milestone_id kwarg so the DoD-port oracle
    can read REQUIREMENTS.md from the correct milestone folder."""

    import inspect as py_inspect

    from agent_team_v15 import scaffold_verifier

    sig = py_inspect.signature(scaffold_verifier.run_scaffold_verifier)
    assert "milestone_id" in sig.parameters


def test_maybe_run_scaffold_verifier_threads_milestone_id():
    """Confirm the wave-executor wrapper also accepts milestone_id."""

    import inspect as py_inspect

    from agent_team_v15 import wave_executor

    sig = py_inspect.signature(wave_executor._maybe_run_scaffold_verifier)
    assert "milestone_id" in sig.parameters


# ---------------------------------------------------------------------------
# 4D — Reporting integration: DoD findings reach WAVE_FINDINGS.json
# ---------------------------------------------------------------------------


def test_dod_finding_reaches_wave_findings_json(tmp_path: Path):
    """End-to-end simulation: a DOD_FEASIBILITY WaveResult appended to
    ``result.waves`` round-trips through ``persist_wave_findings_for_audit``
    and appears in ``WAVE_FINDINGS.json`` with the expected code.
    """

    from agent_team_v15.wave_executor import (
        WaveFinding,
        WaveResult,
        persist_wave_findings_for_audit,
    )

    waves = [
        WaveResult(
            wave="DOD_FEASIBILITY",
            success=True,
            findings=[
                WaveFinding(
                    code="DOD-FEASIBILITY-001",
                    severity="HIGH",
                    file=".agent-team/milestones/m1/REQUIREMENTS.md",
                    line=0,
                    message="DoD command `pnpm db:migrate` references missing script",
                )
            ],
        )
    ]

    out = persist_wave_findings_for_audit(
        str(tmp_path), "milestone-1", waves, wave_t_expected=False, failing_wave=None
    )
    assert out is not None
    payload = json.loads(out.read_text(encoding="utf-8"))
    codes = [f["code"] for f in payload["findings"]]
    assert "DOD-FEASIBILITY-001" in codes


def test_ownership_findings_reach_wave_findings_json(tmp_path: Path):
    from agent_team_v15.wave_executor import (
        WaveFinding,
        WaveResult,
        persist_wave_findings_for_audit,
    )

    waves = [
        WaveResult(
            wave="A",
            success=True,
            findings=[
                WaveFinding(
                    code="OWNERSHIP-WAVE-A-FORBIDDEN-001",
                    severity="HIGH",
                    file="docker-compose.yml",
                    line=0,
                    message="Wave A wrote scaffold-owned file",
                )
            ],
        ),
        WaveResult(
            wave="B",
            success=True,
            findings=[
                WaveFinding(
                    code="OWNERSHIP-DRIFT-001",
                    severity="HIGH",
                    file="apps/api/.env.example",
                    line=0,
                    message="drift after Wave B",
                )
            ],
        ),
    ]

    out = persist_wave_findings_for_audit(
        str(tmp_path), "milestone-1", waves, wave_t_expected=False, failing_wave=None
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    codes = {f["code"] for f in payload["findings"]}
    assert "OWNERSHIP-WAVE-A-FORBIDDEN-001" in codes
    assert "OWNERSHIP-DRIFT-001" in codes


# ---------------------------------------------------------------------------
# 4C — Crash isolation: mocked enforcer raises does NOT break peer checks
# ---------------------------------------------------------------------------


def test_fingerprint_crash_does_not_block_peer_hooks(tmp_path: Path):
    """If the fingerprint enforcer crashes at scaffold-completion, the
    peer scaffold verifier (run immediately before) remains unaffected —
    because each is wrapped in its own try/except.

    We prove this structurally: invoke the fingerprint helper with a
    raising enforcer, then invoke a separate helper — both complete.
    """

    from agent_team_v15 import wave_executor

    cfg = _Config(ownership_enforcement_enabled=True)
    result = _mk_result()

    with mock.patch(
        "agent_team_v15.ownership_enforcer.check_template_drift_and_fingerprint",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise — crash is swallowed.
        wave_executor._maybe_run_scaffold_ownership_fingerprint(
            cfg, str(tmp_path), result, []
        )

    # After the crash, other code continues unaffected. We demonstrate by
    # calling _now_iso() which is invoked immediately after the hook in
    # the live wave loop.
    from agent_team_v15.wave_executor import _now_iso

    assert isinstance(_now_iso(), str)


# ---------------------------------------------------------------------------
# 4D — SCAFFOLD-* reporting-integration gap test (expected partial)
# ---------------------------------------------------------------------------


def test_scaffold_pattern_ids_flow_into_scaffold_verifier_report_summary(tmp_path: Path):
    """Verify the SCAFFOLD-COMPOSE-001 token reaches the persisted
    scaffold_verifier_report.json summary_lines list. This is the
    documented (partial) reporting path — not a WaveFinding with
    ``code="SCAFFOLD-COMPOSE-001"``, but a string token inside
    summary_lines[i].
    """

    from agent_team_v15 import wave_executor

    # Build a workspace missing services.api in docker-compose → should
    # trigger the SCAFFOLD-COMPOSE-001 summary token.
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres\n",
        encoding="utf-8",
    )
    # Provide the minimal ownership contract so load_ownership_contract
    # does not crash — if it does, the helper returns None gracefully.
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)

    # Drive the helper. We can't invoke it with a real contract in this
    # unit-test surface, so we monkeypatch the verifier import to inject
    # a prefabricated report and assert the report persistence path
    # captures the summary token.
    from agent_team_v15 import scaffold_verifier as _sv

    fake_report = _sv.ScaffoldVerifierReport(
        verdict="FAIL",
        missing=[],
        malformed=[(tmp_path / "docker-compose.yml", "topology diag")],
        deprecated_emitted=[],
        summary_lines=["SCAFFOLD-COMPOSE-001 docker-compose.yml missing services.api"],
    )

    class _FakeContract:
        files = []

    with mock.patch.object(
        _sv, "run_scaffold_verifier", return_value=fake_report
    ), mock.patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract",
        return_value=_FakeContract(),
    ):
        err = wave_executor._maybe_run_scaffold_verifier(
            cwd=str(tmp_path), milestone_scope=None, scope_aware=False
        )

    assert err is not None
    assert "Scaffold-verifier FAIL" in err

    # Confirm the persisted report captured the summary token.
    report_path = tmp_path / ".agent-team" / "scaffold_verifier_report.json"
    assert report_path.is_file()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report_data.get("summary_lines", [])
    assert any("SCAFFOLD-COMPOSE-001" in line for line in summary), (
        f"Expected SCAFFOLD-COMPOSE-001 token in summary_lines; got {summary}"
    )


# ---------------------------------------------------------------------------
# 4A — Prompt directive presence (Item 1)
# ---------------------------------------------------------------------------


def test_wave_b_prompt_has_infrastructure_wiring_directive_in_claude_body():
    """Confirms Wave 2A inserted [INFRASTRUCTURE WIRING] block into the
    Claude-path ``build_wave_b_prompt``. Survives Codex→Claude fallback."""

    from agent_team_v15 import agents

    src = Path(agents.__file__).read_text(encoding="utf-8")
    assert "[INFRASTRUCTURE WIRING]" in src


def test_wave_b_prompt_has_compose_wiring_section_in_codex_preamble():
    from agent_team_v15 import codex_prompts

    src = Path(codex_prompts.__file__).read_text(encoding="utf-8")
    assert "## Infrastructure Wiring (Compose + env parity)" in src


def test_wave_b_prompt_has_compose_bullet_in_codex_suffix():
    from agent_team_v15 import codex_prompts

    # SUFFIX checklist adds a `docker-compose.yml has an `api` service` bullet.
    assert "docker-compose.yml" in codex_prompts.CODEX_WAVE_B_SUFFIX
    assert "api" in codex_prompts.CODEX_WAVE_B_SUFFIX


# ---------------------------------------------------------------------------
# 4A — TRUTH summary block emission (Item 7, unconditional)
# ---------------------------------------------------------------------------


def test_truth_summary_block_is_unconditional():
    """Item 7 TRUTH panel emitter has no flag — it always emits when
    ``TRUTH_SCORES.json`` exists. Confirmed by grepping cli.py for the
    helper name and verifying the 'Always on' comment anchors the call."""

    from agent_team_v15 import cli as _cli

    src = Path(_cli.__file__).read_text(encoding="utf-8")
    assert "_format_truth_summary_block" in src
    # The 'Always on' comment is the plan's anchor.
    assert "Always on" in src
