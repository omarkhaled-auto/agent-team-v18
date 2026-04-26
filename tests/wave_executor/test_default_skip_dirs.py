"""Regression test for _DEFAULT_SKIP_DIRS — every entry must be pruned at descent."""

from __future__ import annotations

from agent_team_v15.wave_executor import (
    _capture_file_fingerprints,
    _capture_packages_api_client_snapshot,
    _create_checkpoint,
    _diff_checkpoints,
    _purge_wave_c_owned_dirs,
    _restore_packages_api_client_snapshot,
)


def test_capture_file_fingerprints_skips_all_default_skip_dirs(tmp_path):
    skip_dirs = [
        ".git",
        ".agent-team",
        ".next",
        ".smoke-logs",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    ]

    for name in skip_dirs:
        skip_dir = tmp_path / name
        skip_dir.mkdir()
        (skip_dir / "skip.txt").write_text("should be ignored", encoding="utf-8")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "tsconfig.tsbuildinfo").write_text("cache", encoding="utf-8")

    fingerprints = _capture_file_fingerprints(str(tmp_path))

    assert list(fingerprints.keys()) == ["src/app.py"]


def test_packages_api_client_snapshot_capture_and_restore(tmp_path):
    """Wave C-owned ``packages/api-client/*`` must survive any Wave D
    inadvertent regen. Smoke
    ``v18 test runs/m1-hardening-smoke-20260425-033258`` failed Wave D
    on ``packages/api-client/sdk.gen.ts`` because Codex's build/test
    commands re-invoked openapi-ts and produced byte-different output.
    The snapshot helper captures Wave C's exact bytes; the restore
    helper reverts any post-Wave-C mutation and reports which files
    were rolled back.
    """
    pkg = tmp_path / "packages" / "api-client"
    pkg.mkdir(parents=True)
    sdk = pkg / "sdk.gen.ts"
    types = pkg / "types.gen.ts"
    nested = pkg / "nested" / "deep.ts"
    nested.parent.mkdir(parents=True)

    sdk.write_bytes(b"export const sdk = 1;\n")
    types.write_bytes(b"export type T = number;\n")
    nested.write_bytes(b"export const deep = true;\n")

    snapshot = _capture_packages_api_client_snapshot(str(tmp_path))

    assert "packages/api-client/sdk.gen.ts" in snapshot
    assert "packages/api-client/types.gen.ts" in snapshot
    assert "packages/api-client/nested/deep.ts" in snapshot
    assert snapshot["packages/api-client/sdk.gen.ts"] == b"export const sdk = 1;\n"

    # Simulate a Wave D regen: sdk.gen.ts gets a byte-different rewrite,
    # types.gen.ts is left untouched, nested/deep.ts is also touched.
    sdk.write_bytes(b"export const sdk = 1; // regen\n")
    nested.write_bytes(b"export const deep = false;\n")

    reverted = _restore_packages_api_client_snapshot(str(tmp_path), snapshot)

    assert sorted(reverted) == [
        "packages/api-client/nested/deep.ts",
        "packages/api-client/sdk.gen.ts",
    ]
    # Bytes are exactly the Wave C snapshot.
    assert sdk.read_bytes() == b"export const sdk = 1;\n"
    assert nested.read_bytes() == b"export const deep = true;\n"
    # Untouched file is not double-restored on a no-op call.
    second = _restore_packages_api_client_snapshot(str(tmp_path), snapshot)
    assert second == []


def test_purge_wave_c_owned_dirs_removes_premature_pre_c_writes(tmp_path):
    """Pre-Wave-C waves (A, A5, Scaffold, B) must not produce
    Wave-C-territory files. Codex Wave B in smoke
    ``v18 test runs/m1-hardening-smoke-20260425-064729`` ran
    ``pnpm openapi:export`` as part of self-verify and produced
    ``contracts/openapi/current.json`` plus
    ``contracts/openapi/milestone-unknown.json`` before Wave C ever ran
    (the ``milestone-unknown`` filename is the giveaway — the openapi
    script's MILESTONE_ID env defaults to ``milestone-unknown`` when
    called outside the wave-C dispatch). The purge helper deletes
    those premature shadow copies so the pre-C wave's checkpoint diff
    stays in scope; Wave C re-creates them properly on its own turn.
    """
    contracts = tmp_path / "contracts" / "openapi"
    contracts.mkdir(parents=True)
    (contracts / "current.json").write_text("{}", encoding="utf-8")
    (contracts / "milestone-unknown.json").write_text("{}", encoding="utf-8")

    api_client = tmp_path / "packages" / "api-client"
    api_client.mkdir(parents=True)
    (api_client / "index.ts").write_text("export {};\n", encoding="utf-8")
    (api_client / "sdk.gen.ts").write_text("export {};\n", encoding="utf-8")

    # Real source file outside the Wave-C-owned dirs must NOT be touched.
    apps = tmp_path / "apps" / "api" / "src"
    apps.mkdir(parents=True)
    main_ts = apps / "main.ts"
    main_ts.write_text("console.log('x');\n", encoding="utf-8")

    purged = _purge_wave_c_owned_dirs(str(tmp_path))

    purged_set = {p.replace("\\", "/") for p in purged}
    assert "contracts/openapi/current.json" in purged_set
    assert "contracts/openapi/milestone-unknown.json" in purged_set
    assert "packages/api-client/index.ts" in purged_set
    assert "packages/api-client/sdk.gen.ts" in purged_set
    # Out-of-scope Wave-C-owned files are gone.
    assert not (contracts / "current.json").exists()
    assert not (api_client / "sdk.gen.ts").exists()
    # Source file untouched.
    assert main_ts.read_text(encoding="utf-8") == "console.log('x');\n"


def test_purge_wave_c_owned_dirs_is_noop_when_dirs_absent(tmp_path):
    """No Wave-C dirs on disk → purge returns empty list, no error."""
    purged = _purge_wave_c_owned_dirs(str(tmp_path))
    assert purged == []


def test_packages_api_client_restore_no_snapshot_is_noop(tmp_path):
    """Caller may pass an empty snapshot when Wave C never ran. The
    helper must not fabricate files in that case.
    """
    pkg = tmp_path / "packages" / "api-client"
    pkg.mkdir(parents=True)
    f = pkg / "x.ts"
    f.write_bytes(b"hand-written\n")

    reverted = _restore_packages_api_client_snapshot(str(tmp_path), {})

    assert reverted == []
    assert f.read_bytes() == b"hand-written\n"


def test_checkpoint_ignores_gitkeep_marker_files(tmp_path):
    """Empty-directory markers (``.gitkeep``, ``.keep``) must never count as
    wave output. Python's text-mode ``Path.write_text("\\n", …)`` emits
    ``\\r\\n`` on Windows, while many tools (eslint --fix, prettier, git
    core.autocrlf=input) normalize the same sequence to ``\\n``. That
    one-byte delta flipped the MD5 content hash in
    ``m1-hardening-smoke-20260425-013032`` and mis-attributed the
    scaffold-owned ``apps/web/public/.gitkeep`` to Wave B as an
    out-of-scope backend-wave write. Skipping by basename at the walker
    level keeps the scope guard focused on files that carry application
    semantics.
    """
    public_dir = tmp_path / "apps" / "web" / "public"
    public_dir.mkdir(parents=True)
    gitkeep = public_dir / ".gitkeep"
    # Simulate the scaffold's CRLF text-mode write.
    gitkeep.write_bytes(b"\r\n")
    before = _create_checkpoint("before", str(tmp_path))

    # Simulate a formatter or autocrlf=input normalizing CRLF to LF.
    gitkeep.write_bytes(b"\n")
    (public_dir / ".keep").write_bytes(b"")  # sibling convention

    # Unrelated source change that MUST still be detected.
    (tmp_path / "apps" / "api").mkdir()
    (tmp_path / "apps" / "api" / "main.ts").write_text(
        "console.log('x');\n", encoding="utf-8"
    )

    after = _create_checkpoint("after", str(tmp_path))
    diff = _diff_checkpoints(before, after)

    all_changed = {*diff.created, *diff.modified, *diff.deleted}
    assert "apps/web/public/.gitkeep" not in all_changed
    assert "apps/web/public/.keep" not in all_changed
    assert "apps/api/main.ts" in diff.created
