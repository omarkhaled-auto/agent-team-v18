"""Stage 2B Phase 5.8a §K.2 sequential M1+M2 smoke-batch driver.

Closeout-smoke plan §K Stage 2B contract:

* Up to 10 sequential M1+M2 smokes against the canonical TaskFlow
  PRD (md5 ``bd18686839c513f8538b2ad5b0e92cba``).
* ``strict_mode=ON`` (production default; counts toward §K.2 decision).
* Stop-early predicate: 3 distinct DTOs sharing the SAME
  ``divergence_class`` across the batch
  (:func:`agent_team_v15.cross_package_diagnostic.k2_decision_gate_satisfied`).
  Stop and ship Phase 5.8b path → SEPARATE implementer session.
* Otherwise: continue to 10-cap → close R-#42 via Wave A spec-quality.
* Cost: $90 floor / $600 ceiling. Per-smoke cost cap default ``$20``
  (``--milestone-cost-cap-usd`` from the launcher template).

This driver:

1. Provisions a fresh run-dir per smoke (``phase-5-closeout-stage-2b-NN-<ts>``).
2. Renders watcher + launcher via ``stage_1_prep`` (Stage 1 signal-safe
   harness — same wiring as 2C / Stage 1 1A+1B).
3. Launches each smoke in sequence (NOT concurrent — watcher SIGTERMs
   after M1+M2 reach terminal; serial avoids docker-port collisions on
   5432/5433/3080/4000).
4. After each smoke closes, scans the run-dir for
   ``PHASE_5_8A_DIAGNOSTIC.json`` artifacts and feeds them to
   :func:`k2_decision_gate_satisfied`.
5. Halts the loop early when the §K.2 predicate fires; otherwise
   continues to the cap.
6. Writes a batch-records snapshot to
   ``<batch_root>/<batch_id>-BATCH_RECORDS.json`` capturing per-smoke
   metadata + the accumulated diagnostic-count rollup. The driver
   does **NOT** invoke
   :mod:`scripts.phase_5_closeout.k2_evaluator`; the §K.2 decision-gate
   evaluation is a SEPARATE operator-authorized step (Rerun 4 in the
   closeout-smoke plan). The batch-records snapshot is one of the
   inputs the operator feeds the evaluator; the evaluator itself reads
   per-milestone ``PHASE_5_8A_DIAGNOSTIC.json`` artifacts under each
   smoke's run-dir directly. Treating BATCH_RECORDS.json as the §K.2
   summary would overclaim §O.4.14 closure.

Per the closeout-smoke plan, the driver is **operator-authorized**: the
operator runs this module as a foreground subprocess (or backgrounds
it via ``nohup``) AFTER explicit per-stage spend authorization. The
driver itself spawns ``launcher.sh`` and ``watcher.sh`` per smoke
iteration via ``subprocess.Popen`` (see :func:`_run_one_smoke`); the
operator's authorization gate is at the OUTER level — invoking the
driver — not at each inner ``Popen``. Each smoke runs to its natural
terminal (M1+M2 status terminal → watcher SIGTERMs → launcher writes
``EXIT_CODE.txt``) before the next iteration starts. Serial execution
avoids docker-port collisions on 5432/5433/3080/4000.

Usage::

    source .venv/bin/activate
    python -m scripts.phase_5_closeout.sequential_batch_2b \\
        --batch-id phase-5-8a-stage-2b-2026-04-30 \\
        --batch-root "v18 test runs" \\
        --max-smokes 10 \\
        --correlated-threshold 3
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from scripts.phase_5_closeout import k2_evaluator
from scripts.phase_5_closeout.stage_1_prep import (
    render_launcher_script,
    render_watcher_script,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_ACTIVATE = REPO_ROOT / ".venv" / "bin" / "activate"
CANONICAL_PRD = REPO_ROOT / "v18 test runs" / "TASKFLOW_MINI_PRD.md"
CANONICAL_PRD_MD5 = "bd18686839c513f8538b2ad5b0e92cba"
CANONICAL_CONFIG = (
    REPO_ROOT / "v18 test runs" / "configs" / "taskflow-smoke-test-config.yaml"
)
# Stale-state filter — Stage 2B run-dirs all use this prefix in their
# basenames, and ``docker compose up`` from the run-dir labels every
# container with that basename as ``com.docker.compose.project``. Same
# string appears in the network name (``<project>_default``).
PHASE5_8A_STAGE_2B_PROJECT_PREFIX = "phase-5-8a-stage-2b-"


def _utc_now() -> str:
    return _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _list_stale_compose_projects() -> set[str]:
    """Project names labelled on any container that match the prefix."""

    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format",
             '{{.Label "com.docker.compose.project"}}'],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()
    projects: set[str] = set()
    for line in out.splitlines():
        name = line.strip()
        if name and name.startswith(PHASE5_8A_STAGE_2B_PROJECT_PREFIX):
            projects.add(name)
    return projects


def _list_stale_compose_containers() -> list[tuple[str, str, str]]:
    """``(container_id, name, project)`` triples for stale containers."""

    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format",
             '{{.ID}}\t{{.Names}}\t{{.Label "com.docker.compose.project"}}'],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    rows: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        cid, name, project = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if project.startswith(PHASE5_8A_STAGE_2B_PROJECT_PREFIX):
            rows.append((cid, name, project))
    return rows


def _list_stale_compose_networks() -> set[str]:
    """Network names whose project prefix matches a stale Stage 2B run."""

    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()
    nets: set[str] = set()
    for line in out.splitlines():
        name = line.strip()
        if name.startswith(PHASE5_8A_STAGE_2B_PROJECT_PREFIX):
            nets.add(name)
    return nets


def _clean_stale_stage_2b_state(*, log: bool = True) -> dict[str, list[str]]:
    """Best-effort cleanup of stale Stage 2B docker artifacts.

    Returns ``{action: [items_actioned]}``. Each docker call is bounded
    (compose-down 60s, rm 20s) and never raises; missing-binary /
    timeout / nonzero-rc paths just produce an empty list for that
    action. Callers can re-run hygiene afterwards to confirm.
    """

    cleaned: dict[str, list[str]] = {
        "compose_down": [],
        "container_rm": [],
        "network_rm": [],
    }

    for project in sorted(_list_stale_compose_projects()):
        try:
            res = subprocess.run(
                ["docker", "compose", "-p", project, "down",
                 "--remove-orphans", "-v"],
                check=False, capture_output=True, text=True, timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            if log:
                print(
                    f"[STAGE-2B] auto-clean: compose down -p {project} "
                    f"failed ({exc!r})",
                    file=sys.stderr,
                )
            continue
        if res.returncode == 0:
            cleaned["compose_down"].append(project)
        elif log:
            print(
                f"[STAGE-2B] auto-clean: compose down -p {project} "
                f"rc={res.returncode}: {res.stderr.strip()[:200]}",
                file=sys.stderr,
            )

    for cid, name, _project in _list_stale_compose_containers():
        try:
            res = subprocess.run(
                ["docker", "rm", "-f", cid],
                check=False, capture_output=True, text=True, timeout=20,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if res.returncode == 0:
            cleaned["container_rm"].append(f"{name} ({cid[:12]})")

    for net in sorted(_list_stale_compose_networks()):
        try:
            res = subprocess.run(
                ["docker", "network", "rm", net],
                check=False, capture_output=True, text=True, timeout=20,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if res.returncode == 0:
            cleaned["network_rm"].append(net)

    return cleaned


def _hygiene_check_blocking() -> list[str]:
    """Return a list of blockers that should halt the batch.

    Mirrors the dispatch-prompt pre-launch hygiene rules:
    * No agent-team-v15 / launcher.sh / watcher.sh orphans.
    * Ports 5432/5433/3080/4000 not LISTEN.
    * No stale Stage 2B docker containers (project label prefix
      ``phase-5-8a-stage-2b-``) AND no stale ``clean-*`` containers from
      the legacy harness.
    * No stale Stage 2B docker networks left after a SIGTERM-killed
      smoke (e.g. ``<run-dir>_default``).
    """

    blockers: list[str] = []
    try:
        ps_out = subprocess.run(
            ["ps", "-eo", "pid,cmd"],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ps_out = ""
    for line in ps_out.splitlines():
        if any(
            needle in line
            for needle in (
                "/launcher.sh",
                "/watcher.sh",
                "agent-team-v15 --prd",
                "fault_injection_wrapper --prd",
            )
        ):
            blockers.append(f"orphan process detected: {line.strip()}")

    try:
        lsof_out = subprocess.run(
            ["lsof", "-iTCP:5432,5433,3080,4000", "-sTCP:LISTEN"],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        lsof_out = ""
    for line in lsof_out.splitlines():
        if "LISTEN" in line:
            blockers.append(f"port LISTEN detected: {line.strip()}")

    try:
        docker_out = subprocess.run(
            ["docker", "ps", "--filter", "name=clean-", "--format", "{{.Names}}"],
            check=False, capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        docker_out = ""
    for line in docker_out.splitlines():
        if line.strip():
            blockers.append(f"clean-* docker container running: {line.strip()}")

    for cid, name, project in _list_stale_compose_containers():
        blockers.append(
            f"stale Stage 2B container: {name} ({cid[:12]}) project={project}"
        )

    for net in sorted(_list_stale_compose_networks()):
        blockers.append(f"stale Stage 2B network: {net}")

    return blockers


def _provision_run_dir(
    *,
    batch_id: str,
    smoke_index: int,
    batch_root: Path,
) -> Path:
    """Create the run-dir + copy canonical inputs."""

    run_id = f"{batch_id}-{smoke_index:02d}-{_utc_now()}"
    run_dir = batch_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(CANONICAL_PRD, run_dir / "PRD.md")
    shutil.copyfile(CANONICAL_CONFIG, run_dir / "config.yaml")
    (run_dir / "PRD_MD5.txt").write_text(
        f"{CANONICAL_PRD_MD5}  PRD.md\n", encoding="utf-8",
    )
    return run_dir


def _render_harness_into(run_dir: Path, *, smoke_label: str) -> None:
    (run_dir / "watcher.sh").write_text(
        render_watcher_script(run_dir=str(run_dir)), encoding="utf-8",
    )
    (run_dir / "watcher.sh").chmod(0o755)
    (run_dir / "launcher.sh").write_text(
        render_launcher_script(
            run_dir=str(run_dir),
            repo_root=str(REPO_ROOT),
            venv_activate=str(VENV_ACTIVATE),
            stage_label=smoke_label,
        ),
        encoding="utf-8",
    )
    (run_dir / "launcher.sh").chmod(0o755)


def _launch_and_wait(
    run_dir: Path,
    *,
    inflight: dict[str, subprocess.Popen | None] | None = None,
) -> int:
    """Spawn launcher.sh + watcher.sh, wait for EXIT_CODE.txt.

    Returns the EXIT_CODE.txt value (clamped to int). The wrapper signals
    via watcher → launcher → child PG, so the launcher exits when M1+M2
    reach terminal and the watcher SIGTERMs.

    If *inflight* is provided, the launcher and watcher Popen objects are
    registered in it so a SIGTERM handler in the batch driver can
    propagate the signal to the launcher's process group (which traps
    and forwards to the agent-team-v15 child + every subprocess it
    owns).
    """

    launcher = run_dir / "launcher.sh"
    watcher = run_dir / "watcher.sh"
    if not (launcher.is_file() and watcher.is_file()):
        raise RuntimeError(f"launcher/watcher missing in {run_dir}")

    launcher_log = run_dir / "launcher.out"
    launcher_err = run_dir / "launcher.err"
    watcher_log = run_dir / "watcher.out"
    watcher_err = run_dir / "watcher.err"

    launcher_proc = subprocess.Popen(
        [str(launcher)],
        cwd=str(run_dir),
        stdout=launcher_log.open("w"),
        stderr=launcher_err.open("w"),
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    (run_dir / "LAUNCHER_PID.txt").write_text(
        f"{launcher_proc.pid}\n", encoding="utf-8",
    )
    if inflight is not None:
        inflight["launcher"] = launcher_proc

    watcher_proc = subprocess.Popen(
        [str(watcher)],
        cwd=str(run_dir),
        stdout=watcher_log.open("w"),
        stderr=watcher_err.open("w"),
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    (run_dir / "WATCHER_PID.txt").write_text(
        f"{watcher_proc.pid}\n", encoding="utf-8",
    )
    if inflight is not None:
        inflight["watcher"] = watcher_proc

    try:
        rc = launcher_proc.wait()
    finally:
        # Reap the watcher if it hasn't exited on its own.
        if watcher_proc.poll() is None:
            try:
                watcher_proc.terminate()
                watcher_proc.wait(timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    watcher_proc.kill()
                except OSError:
                    pass
        if inflight is not None:
            inflight["launcher"] = None
            inflight["watcher"] = None

    exit_file = run_dir / "EXIT_CODE.txt"
    if exit_file.is_file():
        try:
            return int(exit_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return rc
    return rc


def _scan_diagnostics(run_dir: Path) -> list[dict]:
    """Read every PHASE_5_8A_DIAGNOSTIC.json under the run-dir."""

    pattern = ".agent-team/milestones/*/PHASE_5_8A_DIAGNOSTIC.json"
    out: list[dict] = []
    for path in sorted(run_dir.glob(pattern)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _strict_mode_or_warn(payload: dict) -> str | None:
    """Surface strict_mode field; warn on absence."""

    strict = k2_evaluator._extract_strict_mode(payload)
    return strict


def _aggregate_predicate(
    *,
    accumulated_diagnostics: list[dict],
    correlated_threshold: int,
) -> bool:
    """Run k2_decision_gate_satisfied across all kept diagnostics."""

    from agent_team_v15.cross_package_diagnostic import (
        k2_decision_gate_satisfied,
    )

    diag_dicts = [
        {
            "milestone_id": payload.get("milestone_id", "?"),
            "divergences": list(payload.get("divergences", []) or []),
        }
        for payload in accumulated_diagnostics
    ]
    return k2_decision_gate_satisfied(
        diag_dicts, correlated_threshold=correlated_threshold,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 2B sequential M1+M2 §K.2 smoke-batch driver.",
    )
    parser.add_argument(
        "--batch-id",
        required=True,
        help="Operator label (e.g. phase-5-8a-stage-2b-2026-04-30).",
    )
    parser.add_argument(
        "--batch-root",
        type=Path,
        default=REPO_ROOT / "v18 test runs",
        help="Parent dir under which smoke run-dirs are provisioned.",
    )
    parser.add_argument(
        "--max-smokes",
        type=int,
        default=10,
        help="Maximum number of sequential smokes (closeout-smoke plan cap).",
    )
    parser.add_argument(
        "--correlated-threshold",
        type=int,
        default=3,
        help="§K.2 stop-early predicate threshold (default 3).",
    )
    parser.add_argument(
        "--first-only",
        action="store_true",
        help="Run a single smoke (manual / debug mode); skips the batch loop.",
    )
    parser.add_argument(
        "--auto-clean",
        dest="auto_clean",
        action="store_true",
        default=True,
        help=(
            "(default) When pre-launch / inter-smoke hygiene blockers are "
            "detected, attempt to docker-compose-down stale Stage 2B "
            "projects + remove leftover containers + networks before "
            "halting. The N1 fix (post-Stage 2 BLOCKING-NOT-APPROVED) — "
            "stale state from a SIGTERM-killed prior smoke leaks ports "
            "5432/4000 and bootstraps Wave B failures."
        ),
    )
    parser.add_argument(
        "--no-auto-clean",
        dest="auto_clean",
        action="store_false",
        help="Disable auto-clean; halt on the first hygiene blocker (legacy).",
    )
    args = parser.parse_args(argv)

    if not CANONICAL_PRD.is_file():
        print(f"[STAGE-2B] canonical PRD missing: {CANONICAL_PRD}", file=sys.stderr)
        return 2
    if not CANONICAL_CONFIG.is_file():
        print(f"[STAGE-2B] canonical config missing: {CANONICAL_CONFIG}", file=sys.stderr)
        return 2

    accumulated: list[dict] = []
    smoke_records: list[dict] = []
    inflight: dict[str, subprocess.Popen | None] = {
        "launcher": None,
        "watcher": None,
    }
    shutdown = {"flag": False, "signum": 0}
    cap = 1 if args.first_only else args.max_smokes

    def _on_signal(signum: int, frame: object) -> None:  # noqa: ARG001
        if shutdown["flag"]:
            return
        shutdown["flag"] = True
        shutdown["signum"] = signum
        sig_name = (
            "SIGTERM" if signum == signal.SIGTERM
            else "SIGINT" if signum == signal.SIGINT
            else f"signal {signum}"
        )
        print(
            f"[STAGE-2B] received {sig_name}; tearing down inflight smoke …",
            flush=True,
        )
        for key in ("launcher", "watcher"):
            proc = inflight[key]
            if proc is None:
                continue
            try:
                if proc.poll() is not None:
                    continue
            except Exception:
                continue
            try:
                # Each Popen was started with ``start_new_session=True``
                # (its PID == its PGID). The launcher template's bash
                # trap on TERM forwards to its own grandchild's PG so
                # the agent-team-v15 child + every Codex / docker /
                # npm subprocess it owns receives the same signal in
                # one shot. The watcher.sh handles SIGTERM by exiting.
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    def _write_batch_records() -> Path | None:
        # Write the batch-records snapshot — captures whatever smokes
        # closed before SIGTERM hit (or before normal completion).
        # NOT the §K.2 summary; that runs via ``k2_evaluator``
        # against the per-milestone ``PHASE_5_8A_DIAGNOSTIC.json``
        # artifacts (closeout-smoke Rerun 4).
        try:
            batch_record_path = (
                args.batch_root / f"{args.batch_id}-BATCH_RECORDS.json"
            )
            batch_record_path.write_text(
                json.dumps(
                    {
                        "batch_id": args.batch_id,
                        "max_smokes": args.max_smokes,
                        "correlated_threshold": args.correlated_threshold,
                        "smokes": smoke_records,
                        "kept_diagnostic_count": sum(
                            1
                            for d in accumulated
                            if _strict_mode_or_warn(d) == "ON"
                        ),
                        "all_diagnostic_count": len(accumulated),
                        "shutdown_signum": shutdown["signum"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return batch_record_path
        except OSError as exc:
            print(
                f"[STAGE-2B] WARNING: BATCH_RECORDS.json write failed: {exc}",
                file=sys.stderr,
            )
            return None

    def _resolve_blockers_with_auto_clean(*, phase: str) -> list[str]:
        # Run hygiene; if blockers + auto-clean, attempt cleanup
        # then re-run hygiene. Returns the post-cleanup blocker list
        # (empty == clear to proceed).
        blockers = _hygiene_check_blocking()
        if not blockers:
            return []
        if not args.auto_clean:
            return blockers
        print(
            f"[STAGE-2B] {phase}: {len(blockers)} blocker(s) detected; "
            f"running auto-clean …",
            flush=True,
        )
        cleaned = _clean_stale_stage_2b_state()
        if any(cleaned.values()):
            print(
                f"[STAGE-2B] {phase}: auto-clean removed "
                f"compose_down={len(cleaned['compose_down'])} "
                f"container_rm={len(cleaned['container_rm'])} "
                f"network_rm={len(cleaned['network_rm'])}",
                flush=True,
            )
        return _hygiene_check_blocking()

    try:
        blockers = _resolve_blockers_with_auto_clean(phase="pre-batch")
        if blockers:
            print(
                "[STAGE-2B] pre-launch hygiene FAILED — refusing to start batch:\n  "
                + "\n  ".join(blockers),
                file=sys.stderr,
            )
            return 2

        for idx in range(1, cap + 1):
            if shutdown["flag"]:
                break
            run_dir = _provision_run_dir(
                batch_id=args.batch_id,
                smoke_index=idx,
                batch_root=args.batch_root,
            )
            smoke_label = f"Stage 2B sequential {idx:02d}/{cap}"
            _render_harness_into(run_dir, smoke_label=smoke_label)
            # Pin HEAD into the run-dir alongside the launcher's own
            # HEAD_SHA.txt write (defense in depth — the operator may want
            # the SHA before the launcher finishes its first git call).
            try:
                head = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(REPO_ROOT), check=True,
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                (run_dir / "HEAD_SHA_PRESET.txt").write_text(
                    f"{head}\n", encoding="utf-8",
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                pass

            print(
                f"[STAGE-2B] smoke {idx}/{cap} starting — run_dir={run_dir.name}",
                flush=True,
            )
            start_ts = time.time()
            rc = _launch_and_wait(run_dir, inflight=inflight)
            wall_seconds = time.time() - start_ts
            print(
                f"[STAGE-2B] smoke {idx}/{cap} closed — rc={rc} "
                f"wall={wall_seconds/60:.1f}min",
                flush=True,
            )

            diagnostics = _scan_diagnostics(run_dir)
            for d in diagnostics:
                d.setdefault("_source_run_dir", str(run_dir))
                accumulated.append(d)

            smoke_records.append(
                {
                    "smoke_index": idx,
                    "run_dir": str(run_dir),
                    "rc": rc,
                    "wall_seconds": wall_seconds,
                    "diagnostics_count": len(diagnostics),
                    "strict_modes": [_strict_mode_or_warn(d) for d in diagnostics],
                }
            )

            if shutdown["flag"]:
                break

            # Stop-early predicate.
            kept = [d for d in accumulated if _strict_mode_or_warn(d) == "ON"]
            if kept:
                decision = _aggregate_predicate(
                    accumulated_diagnostics=kept,
                    correlated_threshold=args.correlated_threshold,
                )
                if decision:
                    print(
                        f"[STAGE-2B] §K.2 predicate fired after smoke {idx} "
                        f"(threshold={args.correlated_threshold}); STOPPING batch.",
                        flush=True,
                    )
                    break

            # Hygiene re-check between smokes — stale state from one
            # run (especially after a SIGTERM-killed launcher whose
            # docker-compose-up half-finished) leaks ports to the next.
            post_blockers = _resolve_blockers_with_auto_clean(
                phase=f"after smoke {idx}",
            )
            if post_blockers:
                print(
                    f"[STAGE-2B] hygiene blockers DETECTED after smoke {idx}; "
                    f"halting batch:\n  " + "\n  ".join(post_blockers),
                    file=sys.stderr,
                )
                break
    finally:
        record_path = _write_batch_records()
        if shutdown["flag"]:
            # Operator killed the driver mid-batch — clean state for the
            # next operator-authorised launch so port hygiene starts clean.
            cleaned = _clean_stale_stage_2b_state(log=False)
            print(
                f"[STAGE-2B] shutdown cleanup: "
                f"compose_down={len(cleaned['compose_down'])} "
                f"container_rm={len(cleaned['container_rm'])} "
                f"network_rm={len(cleaned['network_rm'])}",
                flush=True,
            )

    if shutdown["flag"]:
        print("[STAGE-2B] shutdown complete; exiting 143", flush=True)
        return 143

    print(
        f"[STAGE-2B] batch closed — wrote batch records to "
        f"{record_path}. NOTE: this is NOT the §K.2 summary; "
        f"run scripts.phase_5_closeout.k2_evaluator separately "
        f"(closeout-smoke Rerun 4) to evaluate the §O.4.14 decision "
        f"gate against the per-milestone PHASE_5_8A_DIAGNOSTIC.json "
        f"artifacts under each smoke's run-dir.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
