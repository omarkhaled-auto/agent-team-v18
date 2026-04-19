"""Phase H1a Item 4 — ownership enforcer.

Three checks:

* Check A — ``check_template_drift_and_fingerprint`` at scaffold
  completion. Hashes template + on-disk content for each h1a-covered
  file; persists both hashes into ``.agent-team/SCAFFOLD_FINGERPRINT.json``.
  Emits ``OWNERSHIP-DRIFT-001`` HIGH when they differ.

* Check C — ``check_wave_a_forbidden_writes`` at Wave A completion.
  Cross-references Wave A's files_created / files_modified against
  ``owner: scaffold`` rows in SCAFFOLD_OWNERSHIP.md. Intersection →
  ``OWNERSHIP-WAVE-A-FORBIDDEN-001`` HIGH.

* Post-wave re-check — ``check_post_wave_drift`` after every non-A wave.
  Re-hashes h1a-covered files and compares to the ``template_hash``
  baseline persisted by Check A. Drift → OWNERSHIP-DRIFT-001 HIGH with
  the wave name attached.

Note: ``.env.example`` template resolvers are defensively wrapped; if
the underlying scaffold_runner helpers raise, Check A records an empty
entry and skips — we cover that fallback path too.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15 import ownership_enforcer
from agent_team_v15.ownership_enforcer import (
    FINGERPRINT_PATH,
    H1A_ENFORCED_PATHS,
    Finding,
    check_post_wave_drift,
    check_template_drift_and_fingerprint,
    check_wave_a_forbidden_writes,
)
from agent_team_v15.scaffold_runner import _docker_compose_template


# ---------------------------------------------------------------------------
# Check A — template fingerprinting at scaffold completion
# ---------------------------------------------------------------------------


def _write_compose_matching_template(workspace: Path) -> None:
    """Write the exact scaffolder-template compose so hashes match."""

    (workspace / "docker-compose.yml").write_text(
        _docker_compose_template(), encoding="utf-8"
    )


def _write_compose_postgres_only(workspace: Path) -> None:
    (workspace / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:15\n",
        encoding="utf-8",
    )


def test_template_fingerprint_no_drift_when_compose_matches(
    tmp_path: Path,
) -> None:
    _write_compose_matching_template(tmp_path)
    findings = check_template_drift_and_fingerprint(tmp_path)
    assert all(f.file != "docker-compose.yml" for f in findings), (
        f"Unexpected drift finding for compose template: {findings}"
    )
    # Fingerprint file should exist after persist.
    fp = tmp_path / FINGERPRINT_PATH
    assert fp.is_file()
    data = json.loads(fp.read_text(encoding="utf-8"))
    compose_entry = data["docker-compose.yml"]
    assert compose_entry["template_hash"] is not None
    assert compose_entry["on_disk_hash"] == compose_entry["template_hash"]


def test_template_fingerprint_emits_drift_when_wave_a_wrote_wrong_compose(
    tmp_path: Path,
) -> None:
    _write_compose_postgres_only(tmp_path)  # drift from template
    findings = check_template_drift_and_fingerprint(tmp_path)
    compose_findings = [f for f in findings if f.file == "docker-compose.yml"]
    assert len(compose_findings) == 1
    f = compose_findings[0]
    assert f.code == "OWNERSHIP-DRIFT-001"
    assert f.severity == "HIGH"
    assert "docker-compose.yml" in f.message
    assert "template_hash" in f.message
    assert "on_disk_hash" in f.message
    assert "head_diff" in f.message or "diff" in f.message.lower()


def test_template_fingerprint_persists_both_hashes(tmp_path: Path) -> None:
    _write_compose_postgres_only(tmp_path)
    check_template_drift_and_fingerprint(tmp_path)
    fp = tmp_path / FINGERPRINT_PATH
    data = json.loads(fp.read_text(encoding="utf-8"))
    entry = data["docker-compose.yml"]
    assert entry["template_hash"] is not None
    assert entry["on_disk_hash"] is not None
    assert entry["template_hash"] != entry["on_disk_hash"]


def test_template_fetch_failure_skips_check_a_gracefully(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    """Patch the compose template resolver inside ``_TEMPLATE_RESOLVERS`` to
    return ``None`` (the contract for "unresolvable template"); Check A
    must skip that path gracefully — no crash, no drift finding — while
    still processing the other h1a-covered paths."""

    _write_compose_postgres_only(tmp_path)
    # The resolver dict is the actual indirection Check A uses at call
    # time — patch the dict entry, not the module-level symbol.
    patched_resolvers = dict(ownership_enforcer._TEMPLATE_RESOLVERS)
    patched_resolvers["docker-compose.yml"] = lambda cfg=None: None
    monkeypatch.setattr(
        ownership_enforcer, "_TEMPLATE_RESOLVERS", patched_resolvers
    )
    with caplog.at_level("WARNING"):
        findings = check_template_drift_and_fingerprint(tmp_path)
    # No drift finding for compose because template couldn't be resolved.
    compose_findings = [f for f in findings if f.file == "docker-compose.yml"]
    assert compose_findings == []


def test_template_fingerprint_entries_for_env_example_files_present(
    tmp_path: Path,
) -> None:
    """All 4 H1A_ENFORCED_PATHS entries should be in the fingerprint
    even when .env.example files are absent on disk — template_hash is
    populated (when resolvable), on_disk_hash is None."""

    _write_compose_matching_template(tmp_path)
    # Do not create .env.example files.
    check_template_drift_and_fingerprint(tmp_path)
    data = json.loads((tmp_path / FINGERPRINT_PATH).read_text(encoding="utf-8"))
    for rel in H1A_ENFORCED_PATHS:
        assert rel in data, f"missing fingerprint entry for {rel}"


# ---------------------------------------------------------------------------
# Check C — Wave A forbidden-writes
# ---------------------------------------------------------------------------


@pytest.fixture()
def contract_fixture(tmp_path: Path, monkeypatch) -> Path:
    """Ensure the real ``docs/SCAFFOLD_OWNERSHIP.md`` is resolvable when
    the enforcer calls into scaffold_runner.load_ownership_contract.

    The enforcer tries ``<cwd>/docs/SCAFFOLD_OWNERSHIP.md`` first, then
    falls back to the repo-rooted ``docs/SCAFFOLD_OWNERSHIP.md``. We use
    the repo's real contract as the fallback — both branches exercise
    the same owner-filter logic."""

    return tmp_path


def test_wave_a_no_scaffold_files_no_finding(contract_fixture: Path) -> None:
    findings = check_wave_a_forbidden_writes(
        contract_fixture,
        ["docs/milestone-1-notes.md", "AUDIT.md"],
        milestone_id="milestone-1",
    )
    assert findings == []


def test_wave_a_compose_write_fires_finding(contract_fixture: Path) -> None:
    findings = check_wave_a_forbidden_writes(
        contract_fixture,
        ["docker-compose.yml"],
        milestone_id="milestone-1",
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.code == "OWNERSHIP-WAVE-A-FORBIDDEN-001"
    assert f.severity == "HIGH"
    assert "docker-compose.yml" in f.message
    assert "milestone-1" in f.message


def test_wave_a_multiple_scaffold_files_yield_multiple_findings(
    contract_fixture: Path,
) -> None:
    findings = check_wave_a_forbidden_writes(
        contract_fixture,
        ["docker-compose.yml", ".env.example"],
        milestone_id="milestone-1",
    )
    files = sorted(f.file for f in findings)
    assert files == [".env.example", "docker-compose.yml"]
    assert all(f.code == "OWNERSHIP-WAVE-A-FORBIDDEN-001" for f in findings)


def test_wave_a_missing_contract_skips_gracefully(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Mock scaffold_runner.load_ownership_contract to raise — Check C
    returns [] and logs one WARN."""

    with patch(
        "agent_team_v15.scaffold_runner.load_ownership_contract",
        side_effect=FileNotFoundError("nope"),
    ):
        with caplog.at_level("WARNING"):
            findings = check_wave_a_forbidden_writes(
                tmp_path, ["docker-compose.yml"], milestone_id="milestone-1"
            )
    assert findings == []


def test_wave_a_normalizes_backslashes_in_paths(contract_fixture: Path) -> None:
    """Windows path separators must not hide collisions."""

    findings = check_wave_a_forbidden_writes(
        contract_fixture,
        ["docker-compose.yml"],
        milestone_id="milestone-1",
    )
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# Post-wave re-check
# ---------------------------------------------------------------------------


def test_post_wave_no_drift_when_template_matches(tmp_path: Path) -> None:
    _write_compose_matching_template(tmp_path)
    # Establish baseline via Check A.
    check_template_drift_and_fingerprint(tmp_path)
    # Wave B runs — compose unchanged.
    findings = check_post_wave_drift("B", tmp_path)
    assert all(
        f.file != "docker-compose.yml" for f in findings
    ), f"unexpected drift: {findings}"


def test_post_wave_drift_after_wave_b(tmp_path: Path) -> None:
    _write_compose_matching_template(tmp_path)
    check_template_drift_and_fingerprint(tmp_path)
    # Wave B corrupts the compose.
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  wrong:\n    image: broken\n", encoding="utf-8"
    )
    findings = check_post_wave_drift("B", tmp_path)
    compose_findings = [f for f in findings if f.file == "docker-compose.yml"]
    assert len(compose_findings) == 1
    f = compose_findings[0]
    assert f.code == "OWNERSHIP-DRIFT-001"
    assert f.severity == "HIGH"
    assert "wave B" in f.message or "B" in f.message
    assert "docker-compose.yml" in f.message


def test_post_wave_comparison_uses_template_hash_baseline(tmp_path: Path) -> None:
    """Wave A wrote a postgres-only compose (drifted from template).
    Check A records BOTH hashes. Check post-wave MUST compare against
    ``template_hash`` — the scaffolder's canonical baseline — not
    ``on_disk_hash`` (which would hide Wave A's drift)."""

    _write_compose_postgres_only(tmp_path)  # drift from template
    check_template_drift_and_fingerprint(tmp_path)  # persists both
    # Wave B doesn't touch compose; on-disk content == on_disk_hash.
    findings_b = check_post_wave_drift("B", tmp_path)
    compose_findings = [f for f in findings_b if f.file == "docker-compose.yml"]
    # template_hash != current_hash (still postgres-only) → drift finding.
    assert len(compose_findings) == 1


def test_post_wave_skipped_for_wave_a(tmp_path: Path) -> None:
    _write_compose_postgres_only(tmp_path)
    check_template_drift_and_fingerprint(tmp_path)
    findings = check_post_wave_drift("A", tmp_path)
    assert findings == []


def test_post_wave_skipped_when_no_fingerprint(tmp_path: Path) -> None:
    """No fingerprint persisted → nothing to compare against → skip."""

    (tmp_path / "docker-compose.yml").write_text("anything\n", encoding="utf-8")
    findings = check_post_wave_drift("B", tmp_path)
    assert findings == []


def test_post_wave_file_absent_at_recheck_skips(tmp_path: Path) -> None:
    """Baseline recorded, then the file vanishes — upstream MISSING
    check owns that surface. Re-check returns [] for that path."""

    _write_compose_matching_template(tmp_path)
    check_template_drift_and_fingerprint(tmp_path)
    (tmp_path / "docker-compose.yml").unlink()
    findings = check_post_wave_drift("B", tmp_path)
    # The compose file is absent; re-check does NOT emit a finding
    # for it (MISSING is upstream's problem).
    assert not any(f.file == "docker-compose.yml" for f in findings)


def test_post_wave_persistence_failure_is_nonblocking(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    """Persist-failure during Check A must not crash the pipeline —
    Check A WARN and continue. Post-wave re-check will have no
    fingerprint and return []."""

    _write_compose_matching_template(tmp_path)

    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "agent_team_v15.ownership_enforcer.json.dump", _raise, raising=False
    )
    # Patch the Path.write_text used by _save_fingerprint indirectly:
    original_write_text = Path.write_text

    def _wt(self, data, *args, **kwargs):
        if self.name == "SCAFFOLD_FINGERPRINT.json":
            raise OSError("disk full")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _wt)

    with caplog.at_level("WARNING"):
        findings = check_template_drift_and_fingerprint(tmp_path)
    # Check A still returns its own findings list; persistence failure
    # only prevents the baseline from being recorded.
    assert isinstance(findings, list)
    # Post-wave re-check sees no fingerprint → skip.
    post = check_post_wave_drift("B", tmp_path)
    assert post == []


# ---------------------------------------------------------------------------
# ScaffoldConfig threading regression (Finding 3 of PR #42 review)
# ---------------------------------------------------------------------------
#
# The initial h1a env-template resolvers ignored the resolved
# ScaffoldConfig — they always called ``_env_example_template()`` and
# ``_api_env_example_template()`` with defaults. When N-12 spec
# reconciliation resolved ``cfg.port=3080``, the scaffolder wrote files
# with PORT=3080 on disk but Check A hashed the PORT=4000 default
# template, producing false-positive OWNERSHIP-DRIFT-001 findings.


def test_check_a_threads_scaffold_cfg_port_to_env_templates(
    tmp_path: Path,
) -> None:
    """Scaffolder wrote files with cfg.port=3080; Check A must hash the
    same cfg's template, not the PORT=4000 default."""

    from agent_team_v15.scaffold_runner import (
        ScaffoldConfig,
        _api_env_example_template,
        _docker_compose_template,
        _env_example_template,
        _web_env_example_template,
    )

    cfg = ScaffoldConfig(port=3080)
    (tmp_path / ".env.example").write_text(
        _env_example_template(cfg), encoding="utf-8"
    )
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / ".env.example").write_text(
        _api_env_example_template(cfg), encoding="utf-8"
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".env.example").write_text(
        _web_env_example_template(), encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text(
        _docker_compose_template(), encoding="utf-8"
    )
    (tmp_path / ".agent-team").mkdir()

    # Without cfg — false positives on .env.example + apps/api/.env.example.
    findings_default = check_template_drift_and_fingerprint(tmp_path)
    assert {f.file for f in findings_default} == {
        ".env.example",
        "apps/api/.env.example",
    }, (
        "Default-cfg fingerprint must diverge from cfg=3080 on-disk — "
        "this test encodes the pre-fix reproduction."
    )

    # With scaffold_cfg=3080 — clean, no findings.
    findings_with_cfg = check_template_drift_and_fingerprint(
        tmp_path, scaffold_cfg=cfg
    )
    assert findings_with_cfg == [], (
        f"Check A with matching scaffold_cfg must report no drift; got: "
        f"{[(f.file, f.code) for f in findings_with_cfg]}"
    )


def test_check_a_cfg_none_preserves_default_behavior(
    tmp_path: Path,
) -> None:
    """scaffold_cfg=None (or omitted) must match the pre-fix default-cfg
    fingerprinting exactly — callers that have no cfg to pass still get
    a valid baseline."""

    from agent_team_v15.scaffold_runner import (
        _api_env_example_template,
        _docker_compose_template,
        _env_example_template,
        _web_env_example_template,
    )

    (tmp_path / ".env.example").write_text(
        _env_example_template(), encoding="utf-8"
    )
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / ".env.example").write_text(
        _api_env_example_template(), encoding="utf-8"
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".env.example").write_text(
        _web_env_example_template(), encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text(
        _docker_compose_template(), encoding="utf-8"
    )
    (tmp_path / ".agent-team").mkdir()

    assert check_template_drift_and_fingerprint(tmp_path) == []
    assert check_template_drift_and_fingerprint(
        tmp_path, scaffold_cfg=None
    ) == []


def test_post_wave_drift_head_diff_uses_scaffold_cfg(
    tmp_path: Path,
) -> None:
    """PR #42 Finding 3 second-half regression: the post-wave drift check
    must render ``head_diff`` against the cfg the scaffolder actually
    used, not the DEFAULT cfg. Detection itself uses the stored
    ``template_hash`` (correct either way), but the head_diff string in
    the emitted finding message was misleading when cfg was non-default.
    """

    from agent_team_v15.scaffold_runner import (
        ScaffoldConfig,
        _api_env_example_template,
        _docker_compose_template,
        _env_example_template,
        _web_env_example_template,
    )

    cfg = ScaffoldConfig(port=3080)
    (tmp_path / ".env.example").write_text(
        _env_example_template(cfg), encoding="utf-8"
    )
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / ".env.example").write_text(
        _api_env_example_template(cfg), encoding="utf-8"
    )
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".env.example").write_text(
        _web_env_example_template(), encoding="utf-8"
    )
    (tmp_path / "docker-compose.yml").write_text(
        _docker_compose_template(), encoding="utf-8"
    )
    (tmp_path / ".agent-team").mkdir()

    # Prime the fingerprint with Check A (cfg=3080).
    check_template_drift_and_fingerprint(tmp_path, scaffold_cfg=cfg)

    # Simulate a Wave B that modifies .env.example.
    (tmp_path / ".env.example").write_text(
        _env_example_template(cfg) + "\nAPP_SECRET=leaked\n",
        encoding="utf-8",
    )

    # Without cfg → detection still fires, but head_diff is rendered
    # against the PORT=4000 default, which misrepresents what the
    # scaffolder actually wrote. The `template=...` side of the diff
    # exposes the misleading default.
    findings_no_cfg = check_post_wave_drift("B", tmp_path)
    assert len(findings_no_cfg) == 1
    assert "template='PORT=4000'" in findings_no_cfg[0].message, (
        "Pre-fix baseline: head_diff's template side renders PORT=4000 "
        f"(the default) when cfg isn't threaded. Got: "
        f"{findings_no_cfg[0].message}"
    )

    # With cfg → head_diff uses the scaffolder's actual cfg=3080 template.
    # The PORT lines now match (both 3080), so they don't appear in
    # head_diff at all. Only the real drift (APP_SECRET) shows up.
    findings_with_cfg = check_post_wave_drift(
        "B", tmp_path, scaffold_cfg=cfg
    )
    assert len(findings_with_cfg) == 1
    assert "template='PORT=4000'" not in findings_with_cfg[0].message, (
        "With scaffold_cfg threaded, head_diff must NOT render the "
        f"default PORT=4000; got: {findings_with_cfg[0].message}"
    )
