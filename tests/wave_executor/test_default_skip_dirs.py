"""Regression test for _DEFAULT_SKIP_DIRS — every entry must be pruned at descent."""

from __future__ import annotations

from agent_team_v15.scaffold_runner import (
    _packages_api_client_index_template,
    _packages_api_client_package_json_template,
)
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

    rerun14 correction: ``packages/api-client/index.ts`` written by the
    scaffold (``_scaffold_packages_api_client``) is a Wave-C SHELL — it
    must survive the purge so the Docker ``COPY`` of the api-client
    workspace manifest can succeed in 5.6b before Wave C overwrites the
    placeholder with generated content. Truly premature pre-C writes
    (e.g. ``sdk.gen.ts`` from a build-script side effect) still get
    purged.
    """
    contracts = tmp_path / "contracts" / "openapi"
    contracts.mkdir(parents=True)
    (contracts / "current.json").write_text("{}", encoding="utf-8")
    (contracts / "milestone-unknown.json").write_text("{}", encoding="utf-8")

    api_client = tmp_path / "packages" / "api-client"
    api_client.mkdir(parents=True)
    # Scaffold-emitted shell — content matches the canonical scaffold
    # template, so it must be preserved (rerun14 fix).
    scaffold_index = _packages_api_client_index_template()
    (api_client / "index.ts").write_text(scaffold_index, encoding="utf-8")
    # Premature pre-C build-script side effect — generated, not
    # scaffold-owned — must be purged.
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
    assert "packages/api-client/sdk.gen.ts" in purged_set
    # rerun14: scaffold-shell index.ts MUST survive — Docker stages COPY
    # the api-client workspace manifest after this purge runs.
    assert "packages/api-client/index.ts" not in purged_set
    assert (api_client / "index.ts").read_text(encoding="utf-8") == scaffold_index
    # Out-of-scope Wave-C-owned files are gone.
    assert not (contracts / "current.json").exists()
    assert not (api_client / "sdk.gen.ts").exists()
    # Source file untouched.
    assert main_ts.read_text(encoding="utf-8") == "console.log('x');\n"


def test_purge_wave_c_owned_dirs_preserves_scaffold_shell_when_content_matches(tmp_path):
    """rerun14 regression — Defect B.

    Reproduces the live failure shape from
    ``v18 test runs/phase-5-8a-stage-2b-rerun14-20260504-7f59707-dirty-01-20260503-215914``:

    * Scaffold (``_scaffold_packages_api_client`` in scaffold_runner.py)
      emits ``packages/api-client/package.json`` and
      ``packages/api-client/index.ts`` BEFORE Wave B runs.
    * Wave B does NOT touch those files (confirmed via
      ``milestone-1-wave-B-checkpoint-diff.json``: both are present in
      ``pre_checkpoint_files`` AND ``post_checkpoint_files``, absent
      from ``diff_modified``).
    * ``apps/api/Dockerfile`` and ``apps/web/Dockerfile`` (regenerated
      from the patched template) ``COPY packages/api-client/package.json``
      in their deps stage.
    * Pre-fix: ``_purge_wave_c_owned_dirs`` blindly deleted EVERY file
      under ``packages/api-client/``, including the scaffold-owned
      shell. 5.6b project-scope ``docker compose build`` then failed
      with ``failed to compute cache key: failed to calculate checksum
      of ref ... packages/api-client/package.json: not found``.
    * Post-fix: scaffold-content-matching files are preserved; truly
      premature generated outputs (``sdk.gen.ts``, ``client.gen.ts``,
      ``types.gen.ts``) and ``contracts/openapi/*`` continue to be
      purged.
    """
    api_client = tmp_path / "packages" / "api-client"
    api_client.mkdir(parents=True)

    # Scaffold-owned shell: canonical content from scaffold_runner.
    scaffold_pkg = _packages_api_client_package_json_template()
    scaffold_index = _packages_api_client_index_template()
    (api_client / "package.json").write_text(scaffold_pkg, encoding="utf-8")
    (api_client / "index.ts").write_text(scaffold_index, encoding="utf-8")

    # Generated outputs that a pre-Wave-C side effect (or rogue Wave B
    # build-script) might have left behind. Wave C re-creates these
    # deterministically — purging here is correct.
    (api_client / "sdk.gen.ts").write_text(
        "// generated by openapi-ts\nexport const sdk = {};\n", encoding="utf-8"
    )
    (api_client / "client.gen.ts").write_text(
        "// generated by openapi-ts\nexport const client = {};\n",
        encoding="utf-8",
    )
    (api_client / "types.gen.ts").write_text(
        "// generated by openapi-ts\nexport type Foo = string;\n",
        encoding="utf-8",
    )

    # Premature OpenAPI exports — also Wave C territory.
    contracts = tmp_path / "contracts" / "openapi"
    contracts.mkdir(parents=True)
    (contracts / "current.json").write_text("{}", encoding="utf-8")
    (contracts / "milestone-unknown.json").write_text("{}", encoding="utf-8")

    purged = _purge_wave_c_owned_dirs(str(tmp_path))
    purged_set = {p.replace("\\", "/") for p in purged}

    # Scaffold shells survive — both files still on disk with original
    # bytes intact.
    assert (api_client / "package.json").read_text(encoding="utf-8") == scaffold_pkg
    assert (api_client / "index.ts").read_text(encoding="utf-8") == scaffold_index
    assert "packages/api-client/package.json" not in purged_set
    assert "packages/api-client/index.ts" not in purged_set

    # Generated api-client files purged.
    for rel in (
        "packages/api-client/sdk.gen.ts",
        "packages/api-client/client.gen.ts",
        "packages/api-client/types.gen.ts",
    ):
        assert rel in purged_set, rel
        assert not (tmp_path / rel).exists()

    # contracts/openapi/* still purged unchanged by this fix.
    assert "contracts/openapi/current.json" in purged_set
    assert "contracts/openapi/milestone-unknown.json" in purged_set


def test_purge_wave_c_owned_dirs_purges_non_template_api_client_files(tmp_path):
    """Negative-direction lock for the rerun14 fix: preservation is
    keyed on EXACT scaffold-template content match, not on filename.
    A ``package.json`` or ``index.ts`` whose bytes diverge from
    ``_packages_api_client_package_json_template()`` /
    ``_packages_api_client_index_template()`` is a generated/rewritten
    file (e.g., a build script, a Wave B mistake, or a Wave C output
    landing premature) and MUST still be purged. This prevents
    blanket-preservation of the whole ``packages/api-client`` directory.
    """
    api_client = tmp_path / "packages" / "api-client"
    api_client.mkdir(parents=True)

    # Same filenames as the scaffold shell, but the content is divergent
    # (different deps in package.json, generated content in index.ts).
    (api_client / "package.json").write_text(
        '{"name": "@taskflow/api-client", "dependencies": {"axios": "^1.0.0"}}\n',
        encoding="utf-8",
    )
    (api_client / "index.ts").write_text(
        "// generated by openapi-ts — NOT the scaffold placeholder\n"
        "export * from './sdk.gen';\n",
        encoding="utf-8",
    )

    purged = _purge_wave_c_owned_dirs(str(tmp_path))
    purged_set = {p.replace("\\", "/") for p in purged}

    # Both purged because content does not match the scaffold template.
    assert "packages/api-client/package.json" in purged_set
    assert "packages/api-client/index.ts" in purged_set
    assert not (api_client / "package.json").exists()
    assert not (api_client / "index.ts").exists()


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
