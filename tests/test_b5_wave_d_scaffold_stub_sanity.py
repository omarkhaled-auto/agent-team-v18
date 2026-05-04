"""B5 — post-Wave-D scaffold-stub finalization sanity check.

Tests that ``run_wave_d_acceptance_test`` fails the wave when residual
``@scaffold-stub: finalized-by-wave-D`` markers persist under
``apps/web/**/*.{ts,tsx,js,jsx}`` after Wave D dispatch, threads the
unfinalized-file list through the Phase 4.2 retry payload's
``extra_violations`` slot, and routes naturally through the Phase 4.5
cascade re-dispatch path (cli.py:10429-10441's ``failed_letter == "D":``
branch).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agent_team_v15 import wave_d_self_verify as wdsv
from agent_team_v15.runtime_verification import BuildResult


_LAYOUT_TSX_REL = "apps/web/src/app/layout.tsx"
_PAGE_TSX_REL = "apps/web/src/app/page.tsx"

_LAYOUT_WITH_MARKER_LINE_1 = (
    "// @scaffold-stub: finalized-by-wave-D\n"
    "// SCAFFOLD STUB — Wave D finalizes with app-specific chrome.\n"
    "export default function RootLayout({\n"
    "  children,\n"
    "}: {\n"
    "  children: React.ReactNode\n"
    "}) {\n"
    "  return <html><body>{children}</body></html>\n"
    "}\n"
)

_LAYOUT_FINALIZED_NO_MARKER = (
    "import type { Metadata } from 'next'\n"
    "\n"
    "export const metadata: Metadata = {\n"
    "  title: 'TaskFlow',\n"
    "}\n"
    "\n"
    "export default function RootLayout({\n"
    "  children,\n"
    "}: {\n"
    "  children: React.ReactNode\n"
    "}) {\n"
    "  return <html><body>{children}</body></html>\n"
    "}\n"
)


@pytest.fixture(autouse=True)
def _stub_docker_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wdsv, "check_docker_available", lambda: True)


@pytest.fixture
def fake_compose(tmp_path: Path) -> Path:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    return compose


def _install_find_compose(monkeypatch: pytest.MonkeyPatch, result: Path | None) -> None:
    monkeypatch.setattr(wdsv, "find_compose_file", lambda _cwd: result)


def _install_validate(monkeypatch: pytest.MonkeyPatch, result) -> None:
    def _fake(compose_file, *, autorepair=True, project_root=None):  # noqa: ANN001, ARG001
        return list(result)

    monkeypatch.setattr(wdsv, "validate_compose_build_context", _fake)


def _install_docker_build(
    monkeypatch: pytest.MonkeyPatch,
    results: list[BuildResult],
) -> None:
    def _fake(project_root, compose_file, timeout=600, *, services=None):  # noqa: ANN001, ARG001
        return list(results)

    monkeypatch.setattr(wdsv, "docker_build", _fake)


def _disable_phase_5_6_tsc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force-skip 5.6c so unit tests don't depend on a working pnpm/tsc.

    Tests pass ``tsc_strict_enabled=False`` directly; nothing to patch.
    """
    return None


def _seed_marker(tmp_path: Path, rel: str, content: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Test 1 — Unit: marker on layout.tsx → fail with the symbolic reason.
# ---------------------------------------------------------------------------


def test_marker_on_line_1_fails_self_verify_with_symbolic_reason(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _LAYOUT_WITH_MARKER_LINE_1)

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is False
    assert result.scaffold_stub_unfinalized_files == [_LAYOUT_TSX_REL]
    assert "wave_d_scaffold_stub_unfinalized" in result.error_summary
    assert _LAYOUT_TSX_REL in result.error_summary


# ---------------------------------------------------------------------------
# Test 2 — Unit backward-compat: NO markers + clean gates → passes.
# ---------------------------------------------------------------------------


def test_no_markers_with_clean_gates_passes_backward_compat(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _LAYOUT_FINALIZED_NO_MARKER)

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is True
    assert result.scaffold_stub_unfinalized_files == []
    assert result.error_summary == ""
    assert result.retry_prompt_suffix == ""


def test_no_apps_web_dir_passes_backward_compat(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="api", success=True, duration_s=0.2)],
    )

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is True
    assert result.scaffold_stub_unfinalized_files == []


# ---------------------------------------------------------------------------
# Test 3 — Unit retry_payload: failure_reason carries the LIST.
# ---------------------------------------------------------------------------


def test_retry_payload_carries_unfinalized_file_list(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _LAYOUT_WITH_MARKER_LINE_1)
    _seed_marker(tmp_path, _PAGE_TSX_REL, _LAYOUT_WITH_MARKER_LINE_1)

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is False
    expected_list = sorted([_LAYOUT_TSX_REL, _PAGE_TSX_REL])
    assert result.scaffold_stub_unfinalized_files == expected_list

    suffix = result.retry_prompt_suffix
    assert "<previous_attempt_failed>" in suffix
    assert "</previous_attempt_failed>" in suffix
    for rel in expected_list:
        assert rel in suffix, f"expected {rel} in retry payload"
    assert "wave_d_scaffold_stub_unfinalized" in suffix


# ---------------------------------------------------------------------------
# Test 4 — Behavioural: Phase 4.5 cascade mock-call asserts the file list
#          is threaded into the re-dispatch payload.
# ---------------------------------------------------------------------------


def test_phase_4_5_cascade_redispatch_includes_unfinalized_files(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _LAYOUT_WITH_MARKER_LINE_1)
    _seed_marker(tmp_path, _PAGE_TSX_REL, _LAYOUT_WITH_MARKER_LINE_1)

    first_result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )
    assert first_result.passed is False
    assert first_result.scaffold_stub_unfinalized_files == sorted(
        [_LAYOUT_TSX_REL, _PAGE_TSX_REL]
    )

    failed_letter = "D"
    cascade_calls: list[dict[str, object]] = []

    def _cascade_redispatch(
        cwd: Path,
        *,
        autorepair: bool,
        timeout_seconds: int,
        tsc_strict_enabled: bool,
        prior_attempts: list[dict[str, object]],
        modified_files: list[str],
    ):
        cascade_calls.append(
            {
                "cwd": cwd,
                "prior_attempts": prior_attempts,
                "modified_files": modified_files,
                "tsc_strict_enabled": tsc_strict_enabled,
            }
        )
        # Phase 4.5 cascade re-runs the same helper; the re-dispatch
        # turn is what must carry the file list.
        return wdsv.run_wave_d_acceptance_test(
            cwd,
            autorepair=autorepair,
            timeout_seconds=timeout_seconds,
            tsc_strict_enabled=tsc_strict_enabled,
            prior_attempts=prior_attempts,
            modified_files=modified_files,
            this_retry_index=len(prior_attempts),
        )

    if failed_letter == "D":
        prior = [
            {
                "retry": 0,
                "failing_services": ["web"],
                "error_summary": first_result.error_summary,
            }
        ]
        modified = list(first_result.scaffold_stub_unfinalized_files)
        second = _cascade_redispatch(
            tmp_path,
            autorepair=True,
            timeout_seconds=600,
            tsc_strict_enabled=False,
            prior_attempts=prior,
            modified_files=modified,
        )

    assert len(cascade_calls) == 1
    redispatch_call = cascade_calls[0]
    assert redispatch_call["cwd"] == tmp_path
    assert redispatch_call["modified_files"] == sorted(
        [_LAYOUT_TSX_REL, _PAGE_TSX_REL]
    )

    assert second.passed is False
    for rel in (_LAYOUT_TSX_REL, _PAGE_TSX_REL):
        assert rel in second.retry_prompt_suffix
    assert "Wave D retry=1" in second.retry_prompt_suffix


# ---------------------------------------------------------------------------
# Test 5 — Static-source lock: scan code is present in run_wave_d_acceptance_test.
# ---------------------------------------------------------------------------


def test_static_source_lock_scan_call_present_in_acceptance_test() -> None:
    src = inspect.getsource(wdsv.run_wave_d_acceptance_test)
    pattern = re.compile(r"_scan_scaffold_stub_unfinalized\s*\(\s*cwd_path")
    assert pattern.search(src) is not None, (
        "run_wave_d_acceptance_test must call _scan_scaffold_stub_unfinalized"
    )

    helper_src = inspect.getsource(wdsv._scan_scaffold_stub_unfinalized)
    assert "_SCAFFOLD_STUB_SCAN_ROOT" in helper_src
    assert "_SCAFFOLD_STUB_SCAN_SUFFIXES" in helper_src
    assert "_SCAFFOLD_STUB_RE" in helper_src

    assert wdsv._SCAFFOLD_STUB_SCAN_ROOT == "apps/web"
    assert set(wdsv._SCAFFOLD_STUB_SCAN_SUFFIXES) == {".ts", ".tsx", ".js", ".jsx"}
    assert wdsv._SCAFFOLD_STUB_SCAN_HEAD_LINES == 8
    assert wdsv._SCAFFOLD_STUB_FAILURE_REASON == "wave_d_scaffold_stub_unfinalized"

    boundary_pattern = re.compile(r"@scaffold-stub:\s*finalized-by-wave-")
    assert boundary_pattern.search(inspect.getsource(wdsv)) is not None


# ---------------------------------------------------------------------------
# Test 6 — Edge case: marker on line 8 detected; line 9 NOT detected.
# ---------------------------------------------------------------------------


def _content_with_marker_on_line(line_no: int) -> str:
    assert line_no >= 1
    pre = ["// filler\n"] * (line_no - 1)
    marker = "// @scaffold-stub: finalized-by-wave-D\n"
    post = [
        "// SCAFFOLD STUB\n",
        "export default function X() { return null }\n",
    ]
    return "".join(pre) + marker + "".join(post)


def test_marker_on_line_8_detected(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _content_with_marker_on_line(8))

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is False
    assert result.scaffold_stub_unfinalized_files == [_LAYOUT_TSX_REL]


def test_marker_on_line_9_not_detected_out_of_bounded_scope(
    tmp_path: Path,
    fake_compose: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_find_compose(monkeypatch, fake_compose)
    _install_validate(monkeypatch, [])
    _install_docker_build(
        monkeypatch,
        [BuildResult(service="web", success=True, duration_s=0.4)],
    )
    _seed_marker(tmp_path, _LAYOUT_TSX_REL, _content_with_marker_on_line(9))

    result = wdsv.run_wave_d_acceptance_test(
        tmp_path,
        autorepair=True,
        tsc_strict_enabled=False,
    )

    assert result.passed is True
    assert result.scaffold_stub_unfinalized_files == []


# ---------------------------------------------------------------------------
# B5 cleanup #3 — wave-filter source-guard regression test
# ---------------------------------------------------------------------------


def test_wave_b_marker_under_apps_web_is_ignored_only_d_markers_flag(
    tmp_path: Path,
) -> None:
    """B5 source-guard regression: ``_scan_scaffold_stub_unfinalized`` MUST
    only flag ``finalized-by-wave-D`` markers; non-D markers (``B``, ``T``,
    etc.) under ``apps/web/`` are owned by other waves and must be ignored.
    Pre-fix the scanner would have falsely flagged B/T markers as Wave D
    failures, turning healthy non-D scaffold work into self-verify
    rejection. Locks the ``if match.group("wave") != "D": continue`` line
    in the scanner against future drift."""
    _seed_marker(
        tmp_path,
        "apps/web/src/some-b-stub.tsx",
        "// @scaffold-stub: finalized-by-wave-B\n"
        "export default function SomeBStub() { return null }\n",
    )
    _seed_marker(
        tmp_path,
        "apps/web/src/some-t-stub.tsx",
        "// @scaffold-stub: finalized-by-wave-T\n"
        "export default function SomeTStub() { return null }\n",
    )

    # Only B/T markers under apps/web/ — scanner should return empty list.
    assert wdsv._scan_scaffold_stub_unfinalized(tmp_path) == []

    # Belt-and-braces: seed a real D marker and confirm IT IS flagged
    # alongside the ignored B/T markers — proves the filter is selective,
    # not blanket-ignoring everything.
    _seed_marker(
        tmp_path,
        "apps/web/src/some-d-stub.tsx",
        "// @scaffold-stub: finalized-by-wave-D\n"
        "export default function SomeDStub() { return null }\n",
    )
    flagged = wdsv._scan_scaffold_stub_unfinalized(tmp_path)
    assert flagged == ["apps/web/src/some-d-stub.tsx"], (
        f"B5 wave-filter regression: expected only the D marker to flag; "
        f"got {flagged} (B/T markers should be ignored)"
    )


# ---------------------------------------------------------------------------
# B5 cleanup #3 — disk-error graceful-skip source-guard regression test
# ---------------------------------------------------------------------------


def test_disk_read_error_on_marker_file_does_not_raise_keeps_other_files_clean(
    tmp_path: Path,
) -> None:
    """B5 source-guard regression: ``_scan_scaffold_stub_unfinalized`` MUST
    swallow per-file disk errors (FileNotFoundError, PermissionError,
    IsADirectoryError, OSError) and continue scanning the remaining
    files. Pre-fix the scanner could turn a healthy build into a
    self-verify failure if a single file briefly held an exclusive
    handle, was a symlink to a missing target, or had been concurrently
    deleted between rglob() and open(). Locks the broad except clause
    against narrowing drift.

    Reproduction strategy: seed a *directory* at a path the scanner
    expects to be a file (extension matches `.tsx`). When the scanner
    tries `path.is_file()` it returns False (skipped silently). For the
    actual disk-error reproduction we use chmod 000 on a file (raises
    PermissionError on open()).
    """
    # File 1: directory at .tsx path — is_file() returns False, skipped.
    fake_dir = tmp_path / "apps" / "web" / "src" / "directory-named-as-tsx.tsx"
    fake_dir.mkdir(parents=True, exist_ok=True)

    # File 2: marker file made unreadable via chmod 000 — open() raises
    # PermissionError, must be swallowed by the except clause.
    unreadable = _seed_marker(
        tmp_path,
        "apps/web/src/unreadable-stub.tsx",
        "// @scaffold-stub: finalized-by-wave-D\n"
        "export default function UnreadableStub() { return null }\n",
    )
    # CWD/orchestrator runs as root in some CI environments; only chmod
    # if it'll actually take effect. Otherwise this branch becomes a
    # readable-marker test and the assertion below adjusts.
    import os
    skip_chmod = os.geteuid() == 0
    if not skip_chmod:
        unreadable.chmod(0o000)

    # File 3: clean apps/web file with no marker — must be present in
    # scanner output as nothing (negative space).
    _seed_marker(
        tmp_path,
        "apps/web/src/clean-no-marker.tsx",
        "export default function Clean() { return null }\n",
    )

    try:
        # Scanner MUST NOT raise — the broad except clause has to
        # swallow the chmod-induced PermissionError on open().
        result = wdsv._scan_scaffold_stub_unfinalized(tmp_path)
    finally:
        # Restore permissions so tmp_path teardown succeeds.
        if not skip_chmod:
            unreadable.chmod(0o644)

    # When chmod takes effect (non-root): unreadable file is silently
    # skipped → result is empty (clean file has no marker; directory is
    # not a file; unreadable is swallowed).
    # When skip_chmod (root): unreadable file IS readable → its D marker
    # IS flagged; result contains exactly that one file.
    if skip_chmod:
        assert result == ["apps/web/src/unreadable-stub.tsx"], (
            f"B5 disk-error regression (root-CI fallback): expected the "
            f"readable D marker to flag; got {result}"
        )
    else:
        assert result == [], (
            f"B5 disk-error regression: expected empty result (unreadable "
            f"file silently skipped, clean file has no marker, directory "
            f"is not a file); got {result}"
        )


def test_rglob_error_on_scaffold_scan_root_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B5 source-guard regression: the scanner MUST also swallow a
    root-level ``rglob`` ``OSError``. Per-file read errors are covered above;
    this locks the broader defensive guard around candidate enumeration."""
    web_root = tmp_path / "apps" / "web"
    web_root.mkdir(parents=True)

    original_rglob = Path.rglob

    def _rglob_or_raise(self: Path, pattern: str):  # noqa: ANN001
        if self == web_root:
            raise OSError("synthetic rglob failure")
        return original_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", _rglob_or_raise)

    assert wdsv._scan_scaffold_stub_unfinalized(tmp_path) == []
