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
6. Aggregates by invoking the existing
   :mod:`scripts.phase_5_closeout.k2_evaluator` for the post-batch
   summary write-up.

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


def _utc_now() -> str:
    return _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _hygiene_check_blocking() -> list[str]:
    """Return a list of blockers that should halt the batch.

    Mirrors the dispatch-prompt pre-launch hygiene rules:
    * No agent-team-v15 / launcher.sh / watcher.sh orphans.
    * Ports 5432/5433/3080/4000 not LISTEN.
    * No docker `clean-*` containers.
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


def _launch_and_wait(run_dir: Path) -> int:
    """Spawn launcher.sh + watcher.sh, wait for EXIT_CODE.txt.

    Returns the EXIT_CODE.txt value (clamped to int). The wrapper signals
    via watcher → launcher → child PG, so the launcher exits when M1+M2
    reach terminal and the watcher SIGTERMs.
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
    args = parser.parse_args(argv)

    blockers = _hygiene_check_blocking()
    if blockers:
        print(
            "[STAGE-2B] pre-launch hygiene FAILED — refusing to start batch:\n  "
            + "\n  ".join(blockers),
            file=sys.stderr,
        )
        return 2

    if not CANONICAL_PRD.is_file():
        print(f"[STAGE-2B] canonical PRD missing: {CANONICAL_PRD}", file=sys.stderr)
        return 2
    if not CANONICAL_CONFIG.is_file():
        print(f"[STAGE-2B] canonical config missing: {CANONICAL_CONFIG}", file=sys.stderr)
        return 2

    accumulated: list[dict] = []
    smoke_records: list[dict] = []
    cap = 1 if args.first_only else args.max_smokes

    for idx in range(1, cap + 1):
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
        rc = _launch_and_wait(run_dir)
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

        # Hygiene re-check between smokes — orphan from one run leaks to next.
        post_blockers = _hygiene_check_blocking()
        if post_blockers:
            print(
                f"[STAGE-2B] hygiene blockers DETECTED after smoke {idx}; "
                f"halting batch:\n  " + "\n  ".join(post_blockers),
                file=sys.stderr,
            )
            break

    # Write per-batch records snapshot for the post-batch evaluator.
    batch_record_path = args.batch_root / f"{args.batch_id}-BATCH_RECORDS.json"
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[STAGE-2B] batch closed — wrote summary to {batch_record_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
