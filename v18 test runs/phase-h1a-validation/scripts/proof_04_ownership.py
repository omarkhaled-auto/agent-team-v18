"""Proof 04: ownership enforcement — all three production call paths.

Scenario: smoke #11 class. Wave A wrote a postgres-only docker-compose.yml
with milestone-specific values BEFORE scaffold runs. When scaffold runs,
``_write_if_missing`` silently skips because the file exists. Post-wave
drift then detects further edits.

We invoke three production entry points from ``ownership_enforcer``:

1. ``check_wave_a_forbidden_writes`` — Wave A completion hook
   (wave_executor.py:4697-4725).
2. ``check_template_drift_and_fingerprint`` — scaffold completion hook
   (wave_executor.py:4270-4273 via ``_maybe_run_scaffold_ownership_fingerprint``).
3. ``check_post_wave_drift`` — per non-A wave (wave_executor.py:4834-4858).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
FIXTURE = THIS.parent.parent / "fixtures" / "proof-04"


WAVE_A_WRITTEN_COMPOSE = """\
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: wave_a_user
      POSTGRES_PASSWORD: wave_a_pass
"""


WAVE_A_WRITTEN_ENV = """\
PORT=4000
DATABASE_URL=postgresql://wave_a_user:wave_a_pass@localhost:5432/wave_a_db
"""


def build_fixture() -> Path:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    # Simulate Wave A having written compose + .env.example before scaffold
    (FIXTURE / "docker-compose.yml").write_text(
        WAVE_A_WRITTEN_COMPOSE, encoding="utf-8"
    )
    (FIXTURE / ".env.example").write_text(WAVE_A_WRITTEN_ENV, encoding="utf-8")
    (FIXTURE / ".agent-team").mkdir()
    return FIXTURE


def check_a_fire_fingerprint(root: Path) -> list:
    from agent_team_v15 import ownership_enforcer

    findings = ownership_enforcer.check_template_drift_and_fingerprint(root)
    return findings


def check_c_wave_a_forbidden_writes(root: Path, files: list[str]) -> list:
    from agent_team_v15 import ownership_enforcer

    findings = ownership_enforcer.check_wave_a_forbidden_writes(
        root,
        files,
        milestone_id="milestone-1",
    )
    return findings


def check_post_wave_drift(root: Path, wave: str) -> list:
    from agent_team_v15 import ownership_enforcer

    findings = ownership_enforcer.check_post_wave_drift(wave, root)
    return findings


def simulate_wave_b_touches_nothing(root: Path) -> None:
    """No-op: Wave B doesn't touch h1a-enforced paths."""


def simulate_wave_d_touches_env_example(root: Path) -> None:
    (root / ".env.example").write_text(
        WAVE_A_WRITTEN_ENV + "NEW_FROM_WAVE_D=1\n", encoding="utf-8"
    )


def main() -> int:
    print("=" * 78)
    print("Check C — Wave A completion hook: OWNERSHIP-WAVE-A-FORBIDDEN-001")
    print("=" * 78)
    root = build_fixture()
    wave_a_files = ["docker-compose.yml", ".env.example"]
    check_c = check_c_wave_a_forbidden_writes(root, wave_a_files)
    print(f"findings: {len(check_c)}")
    for f in check_c:
        print(f"  {f.code} {f.severity} file={f.file}")
        print(f"    {f.message}")
    has_docker = any(f.file == "docker-compose.yml" for f in check_c)
    print(f"fires on docker-compose.yml: {has_docker}")
    print()

    print("=" * 78)
    print("Check A — scaffold-completion: OWNERSHIP-DRIFT-001 + fingerprint persisted")
    print("=" * 78)
    check_a = check_a_fire_fingerprint(root)
    print(f"findings: {len(check_a)}")
    for f in check_a:
        print(f"  {f.code} {f.severity} file={f.file}")
        # Show first 5 lines of message (diff head is bulky)
        lines = f.message.splitlines()
        for line in lines[:3]:
            print(f"    {line}")
    fp_path = root / ".agent-team" / "SCAFFOLD_FINGERPRINT.json"
    print(f"SCAFFOLD_FINGERPRINT.json exists: {fp_path.is_file()}")
    if fp_path.is_file():
        data = json.loads(fp_path.read_text(encoding="utf-8"))
        print("persisted fingerprint entries:")
        for rel, entry in data.items():
            print(f"  {rel}: template_hash={entry.get('template_hash')[:16] if entry.get('template_hash') else None}... on_disk_hash={entry.get('on_disk_hash')[:16] if entry.get('on_disk_hash') else None}...")
    print()

    print("=" * 78)
    print("Post-wave re-check after synthetic Wave B (no compose touch) — expect no findings")
    print("=" * 78)
    simulate_wave_b_touches_nothing(root)
    post_b = check_post_wave_drift(root, "B")
    print(f"findings after Wave B: {len(post_b)}")
    # Note: since Wave A's on-disk content already DIFFERS from template,
    # post-wave drift STILL fires — because the baseline is the
    # template_hash, not the on_disk_hash. This is intentional per plan.
    for f in post_b:
        print(f"  {f.code} file={f.file} wave=B")
    print()

    print("=" * 78)
    print("Post-wave re-check after synthetic Wave D (touches .env.example) — expect NEW finding")
    print("=" * 78)
    simulate_wave_d_touches_env_example(root)
    post_d = check_post_wave_drift(root, "D")
    print(f"findings after Wave D: {len(post_d)}")
    env_d = [f for f in post_d if f.file == ".env.example"]
    print(f"fires on .env.example: {bool(env_d)}")
    for f in env_d[:2]:
        print(f"  {f.code} file={f.file}")
        # truncate to first 200 chars of message
        print(f"    message (trunc): {f.message[:200]}...")
    print()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  Check C fires on docker-compose.yml at Wave A completion:   {has_docker}")
    print(f"  Check A emits OWNERSHIP-DRIFT-001 at scaffold completion:   {bool(check_a)}")
    print(f"  SCAFFOLD_FINGERPRINT.json persisted with template_hash:     {fp_path.is_file()}")
    print(f"  Post-wave drift detects Wave D's .env.example edit:         {bool(env_d)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
