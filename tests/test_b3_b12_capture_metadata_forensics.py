"""B3 + B12 — preserve forensic metadata in hang reports + capture artifacts.

Locks in a single file:
- B3 narrow: filename ms-precision, 4 outer-write-site cumulative_wedges_so_far
  threading, CodexCaptureMetadata extension (attempt_id + session_id),
  inner+outer simultaneous-second behavioural, backward-compat consumer reads.
- B12: _dispatch_wrapped_codex_fix signature lock (milestone+wave_letter+attempt
  kwargs), behavioural milestone+wave threaded into capture stem, orphan-prefix
  on no-metadata path, static-lint zero "auto"/"unknown" literals, dataclass
  default backward-compat (frozen dataclass — mirrors a from_dict-style probe).
"""

from __future__ import annotations

import inspect
import json
import re
import types
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agent_team_v15 import wave_executor as we
from agent_team_v15.codex_captures import (
    CodexCaptureMetadata,
    _capture_stem,
    _legacy_stem,
    build_capture_paths,
    build_checkpoint_diff_capture_path,
    update_latest_mirror_and_index,
    write_checkpoint_diff_capture,
)
from agent_team_v15.wave_executor import (
    WaveWatchdogTimeoutError,
    _WaveWatchdogState,
    _write_hang_report,
)


# ---------------------------------------------------------------------------
# B3 — Test 1: filename ms precision (5x tight loop, distinct names)
# ---------------------------------------------------------------------------


def test_hang_report_filename_distinct_under_ms_resolution(tmp_path: Path) -> None:
    """Five _write_hang_report calls in a tight loop produce five distinct
    filenames thanks to ms-precision strftime. Pre-fix the second-resolution
    %Y%m%dT%H%M%SZ format silently overwrote in-second collisions, losing
    forensic evidence whenever two outer catches fired in the same UTC sec."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    err = WaveWatchdogTimeoutError(
        "B", state, 60, role="wave", timeout_kind="bootstrap"
    )
    paths: list[str] = []
    for _ in range(5):
        path = _write_hang_report(
            cwd=str(tmp_path),
            milestone_id="m1",
            wave="B",
            timeout=err,
            cumulative_wedges_so_far=0,
            bootstrap_deadline_seconds=60,
        )
        paths.append(path)
    # All distinct: ms-resolution stem + tiebreaker suffix MUST disambiguate
    # even when called within the same UTC millisecond (tight Python loop).
    assert len(set(paths)) == 5, f"Expected 5 distinct hang-report paths, got {paths}"
    # Filename pattern locks: wave-B-YYYYMMDDTHHMMSSmmmZ[-NN].json (3 ms digits
    # + optional 2-digit tiebreaker for in-millisecond collisions).
    pattern = re.compile(r"wave-B-\d{8}T\d{6}\d{3}Z(?:-\d{2})?\.json$")
    for path in paths:
        assert pattern.search(path), f"path {path} does not match ms-precision schema"


# ---------------------------------------------------------------------------
# B3 — Test 2: 4 outer sites thread cumulative_wedges_so_far
# ---------------------------------------------------------------------------


def test_outer_site_5754_probe_fix_threads_cumulative_wedges(tmp_path: Path) -> None:
    """Source-level lock for wave_executor.py:5791-area outer site
    (execute_wave_b probe-fix watchdog catch). Verifies the call site sources
    the value via _get_cumulative_wedge_count() helper."""
    src = (Path(we.__file__)).read_text(encoding="utf-8")
    # The probe-fix outer catch must include cumulative_wedges_so_far kwarg.
    probe_fix_pattern = re.compile(
        r"hang_report_path = _write_hang_report\(\s*"
        r"cwd=cwd,\s*"
        r'milestone_id=str\(getattr\(milestone, "id", ""\) or ""\),\s*'
        r'wave="B",\s*'
        r"timeout=exc,\s*"
        r"cumulative_wedges_so_far=_get_cumulative_wedge_count\(\),"
    )
    assert probe_fix_pattern.search(src), (
        "wave_executor.py probe-fix outer site (execute_wave_b) must thread "
        "cumulative_wedges_so_far=_get_cumulative_wedge_count()"
    )


def test_outer_site_wave_t_threads_cumulative_wedges() -> None:
    """Source-level lock for wave_executor.py:5940-area (Wave T initial
    SDK call timeout)."""
    src = (Path(we.__file__)).read_text(encoding="utf-8")
    pattern = re.compile(
        r"wave_result\.hang_report_path = _write_hang_report\(\s*"
        r"cwd=cwd,\s*"
        r'milestone_id=str\(getattr\(milestone, "id", ""\) or ""\),\s*'
        r'wave="T",\s*'
        r"timeout=exc,\s*"
        r"cumulative_wedges_so_far=_get_cumulative_wedge_count\(\),"
    )
    assert pattern.search(src), (
        "wave_executor.py Wave T initial-call outer site must thread "
        "cumulative_wedges_so_far"
    )


def test_outer_sites_provider_routed_and_claude_only_thread_cumulative_wedges() -> None:
    """Source-level lock for wave_executor.py:6516 + 6592 (provider-routed
    + Claude-only paths in _execute_wave_sdk). Both must include
    cumulative_wedges_so_far."""
    src = (Path(we.__file__)).read_text(encoding="utf-8")
    # Both call sites use the same shape with wave=wave_letter; count occurrences.
    pattern = re.compile(
        r"wave_result\.hang_report_path = _write_hang_report\(\s*"
        r"cwd=cwd,\s*"
        r'milestone_id=str\(getattr\(milestone, "id", ""\) or ""\),\s*'
        r"wave=wave_letter,\s*"
        r"timeout=exc,\s*"
        r"cumulative_wedges_so_far=_get_cumulative_wedge_count\(\),"
    )
    matches = pattern.findall(src)
    assert len(matches) >= 2, (
        f"Expected >=2 outer sites threading cumulative_wedges_so_far in "
        f"_execute_wave_sdk; found {len(matches)}"
    )


# ---------------------------------------------------------------------------
# B3 — Test 3: CodexCaptureMetadata extension (with + without new fields)
# ---------------------------------------------------------------------------


def test_capture_metadata_default_attempt_id_and_session_id_preserve_legacy_stem() -> None:
    """Construct without new fields → defaults attempt_id=1, session_id=""
    → stem matches the legacy format byte-for-byte."""
    metadata = CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B")
    assert metadata.attempt_id == 1
    assert metadata.session_id == ""
    # Legacy stem preserved for attempt 1.
    assert _capture_stem(metadata) == "milestone-1-wave-B"
    assert _legacy_stem(metadata) == "milestone-1-wave-B"


def test_capture_metadata_with_attempt_2_threads_session_id_into_stem() -> None:
    """attempt_id > 1 → stem disambiguates by attempt_id + session_id so
    a second EOF retry doesn't clobber the first attempt's artifacts."""
    metadata = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=2,
        session_id="abcd1234",
    )
    assert _capture_stem(metadata) == "milestone-1-wave-B-attempt-02-abcd1234"
    # Legacy stem unchanged regardless of attempt_id (latest-mirror / index
    # uses the legacy stem so existing consumers find canonical filenames).
    assert _legacy_stem(metadata) == "milestone-1-wave-B"


def test_capture_metadata_fix_round_combines_with_attempt_id() -> None:
    """fix_round + attempt_id > 1 produce a fully-qualified stem."""
    metadata = CodexCaptureMetadata(
        milestone_id="m1",
        wave_letter="D",
        fix_round=3,
        attempt_id=2,
        session_id="ffff",
    )
    assert _capture_stem(metadata) == "m1-wave-D-fix-3-attempt-02-ffff"


# ---------------------------------------------------------------------------
# B3 — Test 4: behavioural inner+outer simultaneous-second
# ---------------------------------------------------------------------------


def test_inner_and_outer_hang_reports_persist_distinct_files_in_same_second(
    tmp_path: Path,
) -> None:
    """Two hang reports produced in the same UTC second (inner watchdog +
    outer catch) must persist as TWO distinct files on disk; pre-fix the
    second-resolution timestamp would have made them collide. The inner-
    threaded cumulative_wedges_so_far value is preserved in its own file."""
    state_inner = _WaveWatchdogState()
    state_inner.record_progress(message_type="sdk_call_started", tool_name="")
    state_outer = _WaveWatchdogState()
    state_outer.record_progress(message_type="sdk_call_started", tool_name="")
    err_inner = WaveWatchdogTimeoutError(
        "B", state_inner, 60, role="wave", timeout_kind="bootstrap"
    )
    err_outer = WaveWatchdogTimeoutError(
        "B", state_outer, 1800, role="wave", timeout_kind="wave-idle"
    )
    inner_path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err_inner,
        cumulative_wedges_so_far=3,
        bootstrap_deadline_seconds=60,
    )
    outer_path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err_outer,
        cumulative_wedges_so_far=3,
    )
    assert inner_path != outer_path
    assert Path(inner_path).is_file()
    assert Path(outer_path).is_file()
    inner_payload = json.loads(Path(inner_path).read_text(encoding="utf-8"))
    outer_payload = json.loads(Path(outer_path).read_text(encoding="utf-8"))
    assert inner_payload["cumulative_wedges_so_far"] == 3
    assert outer_payload["cumulative_wedges_so_far"] == 3
    assert inner_payload["timeout_kind"] == "bootstrap"
    assert outer_payload["timeout_kind"] == "wave-idle"


# ---------------------------------------------------------------------------
# B3 — Test 5: backward-compat consumers find canonical files
# ---------------------------------------------------------------------------


def test_attempt_2_latest_mirror_refresh_preserves_legacy_filename_for_consumers(
    tmp_path: Path,
) -> None:
    """Existing capture-file consumers (audit, K.2 evaluator, stage_2b
    driver) must keep finding the canonical legacy-stem filenames after
    EOF retry. update_latest_mirror_and_index copies the per-attempt
    artifacts onto the legacy stem so consumers don't have to learn about
    the per-attempt scheme."""
    metadata_attempt_2 = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=2,
        session_id="cafecafe",
    )
    paths = build_capture_paths(tmp_path, metadata_attempt_2)
    paths.protocol_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("dispatch prompt v2", encoding="utf-8")
    paths.protocol_path.write_text("OUT initialize\n", encoding="utf-8")
    paths.response_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    paths.diagnostic_path.write_text(
        json.dumps({"classification": "transport_stdout_eof_before_turn_completed"}),
        encoding="utf-8",
    )

    update_latest_mirror_and_index(cwd=tmp_path, metadata=metadata_attempt_2)

    legacy_dir = tmp_path / ".agent-team" / "codex-captures"
    canonical_files = {
        "milestone-1-wave-B-prompt.txt",
        "milestone-1-wave-B-protocol.log",
        "milestone-1-wave-B-response.json",
        "milestone-1-wave-B-terminal-diagnostic.json",
        "milestone-1-wave-B-capture-index.json",
    }
    for name in canonical_files:
        candidate = legacy_dir / name
        assert candidate.is_file(), (
            f"backward-compat consumer would not find canonical file {name}"
        )
    assert (legacy_dir / "milestone-1-wave-B-prompt.txt").read_text(
        encoding="utf-8"
    ) == "dispatch prompt v2"
    index = json.loads(
        (legacy_dir / "milestone-1-wave-B-capture-index.json").read_text(encoding="utf-8")
    )
    assert index["legacy_stem"] == "milestone-1-wave-B"
    assert len(index["attempts"]) == 1
    assert index["attempts"][0]["attempt_id"] == 2
    assert index["attempts"][0]["session_id"] == "cafecafe"


# ---------------------------------------------------------------------------
# B12 — Test 6: signature lock (inspect.signature)
# ---------------------------------------------------------------------------


def test_dispatch_wrapped_codex_fix_signature_includes_milestone_wave_attempt() -> None:
    """B12 source-level lock: _dispatch_wrapped_codex_fix MUST accept
    milestone, wave_letter, attempt kwargs (mirrors the inner
    _dispatch_codex_compile_fix). Pre-fix the wrapper had no forensic-
    identity kwargs, so inner-dispatch capture_metadata always fell back
    to codex_appserver self-defaults (auto/unknown stem)."""
    sig = inspect.signature(we._dispatch_wrapped_codex_fix)
    assert "milestone" in sig.parameters, (
        "_dispatch_wrapped_codex_fix must accept milestone kwarg"
    )
    assert "wave_letter" in sig.parameters, (
        "_dispatch_wrapped_codex_fix must accept wave_letter kwarg"
    )
    assert "attempt" in sig.parameters, (
        "_dispatch_wrapped_codex_fix must accept attempt kwarg"
    )
    # Defaults preserve no-metadata callers (caller sites NOT in B12 scope).
    assert sig.parameters["milestone"].default is None
    assert sig.parameters["wave_letter"].default == ""
    assert sig.parameters["attempt"].default == 0


# ---------------------------------------------------------------------------
# B12 — Test 7: behavioural milestone+wave threaded into capture stem
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_wrapped_codex_fix_threads_milestone_into_inner_capture_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural lock: when callers thread milestone+wave_letter+attempt
    through _dispatch_wrapped_codex_fix, the inner _dispatch_codex_compile_fix
    sees them and the capture_metadata stem reflects the actual (milestone,
    wave, fix_round). No more 'auto-wave-UNKNOWN' filenames."""
    captured_kwargs: dict[str, Any] = {}

    async def fake_inner(prompt, *, cwd, provider_routing, v18, milestone, wave_letter, attempt):
        captured_kwargs["milestone"] = milestone
        captured_kwargs["wave_letter"] = wave_letter
        captured_kwargs["attempt"] = attempt
        return True, 0.0, ""

    monkeypatch.setattr(we, "_dispatch_codex_compile_fix", fake_inner)

    class _Milestone:
        id = "milestone-7"
        title = "Test"

    ok, _cost, _reason = await we._dispatch_wrapped_codex_fix(
        "fix prompt",
        cwd="/tmp",
        provider_routing={},
        v18=None,
        milestone=_Milestone(),
        wave_letter="B",
        attempt=2,
    )
    assert ok is True
    assert captured_kwargs["milestone"].id == "milestone-7"
    assert captured_kwargs["wave_letter"] == "B"
    assert captured_kwargs["attempt"] == 2


# ---------------------------------------------------------------------------
# B12 — Test 8: orphan-prefix on no-metadata path
# ---------------------------------------------------------------------------


def test_codex_appserver_self_default_uses_orphan_prefix_not_auto() -> None:
    """B12 source-level lock: codex_appserver.execute_codex (and the
    diagnostic-session fallback inside _execute_once) MUST replace the
    legacy literal 'auto'/'unknown' defaults with an orphan- forensic
    stem. Two concurrent orphan recoveries must produce DISTINCT stems
    (ms-precision wallclock disambiguates)."""
    from agent_team_v15 import codex_appserver as appserver

    src = (Path(appserver.__file__)).read_text(encoding="utf-8")

    # Literal "auto"/"unknown" defaults removed in non-test code (we're
    # reading the source itself; this is a real lint).
    assert 'milestone_id="auto"' not in src, (
        'codex_appserver.py must not default milestone_id="auto" '
        "(use forensic orphan-<ts> stem instead)"
    )
    assert 'wave_letter="unknown"' not in src, (
        'codex_appserver.py must not default wave_letter="unknown" '
        '(use uppercase "ORPHAN" instead)'
    )
    # Affirmative: forensic stem is used.
    assert 'milestone_id=f"orphan-{int(time.time() * 1000)}"' in src, (
        "codex_appserver.py self-defaults must use orphan-<ms> forensic stem"
    )
    assert '"ORPHAN"' in src, (
        "codex_appserver.py self-defaults must fall back to uppercase 'ORPHAN' "
        "wave letter"
    )


# ---------------------------------------------------------------------------
# B12 — Test 9: static-lint grep zero literal "auto"/"unknown" defaults
# ---------------------------------------------------------------------------


def test_static_lint_zero_literal_auto_unknown_defaults_in_non_test_src() -> None:
    """B12 hard lint: grep src/agent_team_v15/*.py (excluding tests/) for
    literal milestone_id=\"auto\" / wave_letter=\"unknown\" defaults. ZERO
    matches required; non-zero indicates a regression where the legacy
    self-default snuck back in. Tests are exempt because a backward-compat
    fixture may exercise the legacy strings."""
    src_dir = Path(we.__file__).parent
    offenders: list[str] = []
    for src_file in src_dir.glob("*.py"):
        text = src_file.read_text(encoding="utf-8")
        if 'milestone_id="auto"' in text:
            offenders.append(f'{src_file.name}: milestone_id="auto"')
        if 'wave_letter="unknown"' in text:
            offenders.append(f'{src_file.name}: wave_letter="unknown"')
    assert offenders == [], (
        f"Found {len(offenders)} non-test sources still defaulting to "
        f"the legacy auto/unknown literal: {offenders}"
    )


# ---------------------------------------------------------------------------
# B12 — Test 10: dataclass backward-compat (frozen — mirrors from_dict probe)
# ---------------------------------------------------------------------------


def test_capture_metadata_construct_with_legacy_fields_only_succeeds() -> None:
    """Backward-compat lock: legacy on-disk fixtures + tests that construct
    CodexCaptureMetadata with only milestone_id+wave_letter (no attempt_id,
    no session_id) must keep working. Defaults attempt_id=1, session_id=''
    preserve the legacy stem byte-for-byte. Frozen dataclass has no
    from_dict; this exercises the equivalent invariant via direct
    construction + dataclasses.replace."""
    legacy = CodexCaptureMetadata(milestone_id="auto", wave_letter="unknown")
    assert legacy.attempt_id == 1
    assert legacy.session_id == ""
    # legacy stem preserved (no per-attempt suffix).
    assert _capture_stem(legacy) == "auto-wave-UNKNOWN"
    # dataclasses.replace round-trip preserves the new fields too.
    bumped = _dc_replace(legacy, attempt_id=3, session_id="deadbeef")
    assert bumped.milestone_id == "auto"
    assert bumped.wave_letter == "unknown"
    assert bumped.attempt_id == 3
    assert bumped.session_id == "deadbeef"
    assert _capture_stem(bumped) == "auto-wave-UNKNOWN-attempt-03-deadbeef"


# ---------------------------------------------------------------------------
# B3 r3 sequencing — Test 11: attempt 1 with session_id gets per-attempt stem
# ---------------------------------------------------------------------------


def test_capture_stem_attempt_1_with_session_id_is_per_attempt_not_legacy() -> None:
    """B3 r3 sequencing fix: when ``session_id`` is set, EVERY attempt
    (including attempt 1) writes to a per-attempt stem. Pre-fix attempt 1
    silently shared the legacy stem with attempt 2, so an EOF→retry that
    landed inside the same dispatch chain clobbered attempt 1's artifacts
    on disk before update_latest_mirror_and_index could preserve them."""
    metadata_a1 = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=1,
        session_id="abcd1234",
    )
    # Disambiguated even at attempt 1.
    assert _capture_stem(metadata_a1) == "milestone-1-wave-B-attempt-01-abcd1234"
    # Legacy stem still computable for the mirror-target.
    assert _legacy_stem(metadata_a1) == "milestone-1-wave-B"


# ---------------------------------------------------------------------------
# B3 r3 sequencing — Test 12: update_latest_mirror_and_index runs at attempt 1
# ---------------------------------------------------------------------------


def test_update_latest_mirror_and_index_runs_at_attempt_1_no_short_circuit(
    tmp_path: Path,
) -> None:
    """B3 r3 sequencing fix: the helper must NOT short-circuit at attempt 1.
    Legacy-stem mirror must be written + index entry must be appended even
    when attempt 1 succeeds (no retry). Pre-fix the helper returned early
    when ``attempt_id <= 1``, so successful first attempts left no index
    behind and the legacy stem only existed because the per-attempt write
    happened to share that name."""
    metadata_a1 = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=1,
        session_id="abcd1234",
    )
    paths = build_capture_paths(tmp_path, metadata_a1)
    paths.protocol_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("attempt-1 prompt", encoding="utf-8")
    paths.protocol_path.write_text("OUT initialize\n", encoding="utf-8")
    paths.response_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    paths.diagnostic_path.write_text(json.dumps({"classification": "ok"}), encoding="utf-8")

    update_latest_mirror_and_index(cwd=tmp_path, metadata=metadata_a1)

    legacy_dir = tmp_path / ".agent-team" / "codex-captures"
    # Legacy stem files exist after the mirror runs.
    assert (legacy_dir / "milestone-1-wave-B-prompt.txt").is_file()
    assert (legacy_dir / "milestone-1-wave-B-protocol.log").is_file()
    assert (legacy_dir / "milestone-1-wave-B-response.json").is_file()
    assert (legacy_dir / "milestone-1-wave-B-terminal-diagnostic.json").is_file()
    # Index records the attempt-1 entry (no longer skipped).
    index_path = legacy_dir / "milestone-1-wave-B-capture-index.json"
    assert index_path.is_file(), (
        "B3 r3 fix: attempt-1 mirror call MUST append an index entry "
        "(no short-circuit). Pre-fix the helper returned early at "
        "attempt_id <= 1, leaving zero index entries."
    )
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["attempts"]) == 1
    assert index["attempts"][0]["attempt_id"] == 1
    assert index["attempts"][0]["session_id"] == "abcd1234"


# ---------------------------------------------------------------------------
# B3 r3 sequencing — Test 13: integration EOF-retry → success-after-retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eof_retry_then_success_preserves_both_attempts_in_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B3 r3 integration: drive ``execute_wave_with_provider`` through a
    fake ``execute_codex`` that raises ``CodexTerminalTurnError`` (transport
    stdout EOF before turn/completed) on attempt 1, then succeeds on
    attempt 2. Verify:
    - Both attempts produce a separate per-attempt stem on disk
      (attempt 1 NOT clobbered by attempt 2).
    - Capture-index lists BOTH attempts in chronological order.
    - Legacy stem reflects the most-recent (attempt 2) artifacts.
    """
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_appserver import CodexTerminalTurnError
    from agent_team_v15.codex_transport import CodexConfig
    from agent_team_v15.provider_router import (
        WaveProviderMap,
        execute_wave_with_provider,
    )

    attempts_seen: list[dict[str, Any]] = []

    async def _fake_execute_codex(
        prompt: str,
        cwd: str,
        config: CodexConfig,
        codex_home: Any,
        *,
        progress_callback: Any = None,
        capture_enabled: bool = False,
        capture_metadata: Any = None,
        **_kwargs: Any,
    ):
        # Each attempt simulates a CodexCaptureSession write so the
        # per-attempt stem files materialise on disk before the EOF
        # propagates. Real execute_codex does this via the capture session
        # background-writes; the test stub does it synchronously.
        from agent_team_v15.codex_captures import (
            CodexCaptureSession,
            build_capture_paths,
        )

        attempt_id = int(getattr(capture_metadata, "attempt_id", 1) or 1)
        attempts_seen.append(
            {
                "attempt_id": attempt_id,
                "session_id": getattr(capture_metadata, "session_id", ""),
            }
        )

        # Mimic the capture session's per-attempt artifact writes so
        # update_latest_mirror_and_index has files to copy.
        session = CodexCaptureSession(
            metadata=capture_metadata,
            cwd=cwd,
            model="gpt-5.4",
            reasoning_effort="low",
            spawn_cwd=cwd,
            subprocess_argv=None,
        )
        session.capture_prompt(prompt)
        paths = build_capture_paths(cwd, capture_metadata)
        paths.response_path.write_text(
            json.dumps({"attempt_id": attempt_id, "ok": attempt_id == 2}),
            encoding="utf-8",
        )
        # write_terminal_diagnostic (required for the canonical artifact
        # set) — even on the success path, a stub diagnostic is fine.
        paths.diagnostic_path.write_text(
            json.dumps({"attempt_id": attempt_id, "classification": "test_stub"}),
            encoding="utf-8",
        )
        session.close()

        if attempt_id == 1:
            raise CodexTerminalTurnError(
                "app-server stdout EOF — subprocess exited",
                thread_id=f"thread-{attempt_id}",
                turn_id=f"turn-{attempt_id}",
            )

        # Attempt 2: success.
        return types.SimpleNamespace(
            success=True,
            cost_usd=0.01,
            model="gpt-5.4",
            input_tokens=100,
            output_tokens=10,
            reasoning_tokens=0,
            cached_input_tokens=0,
            retry_count=0,
            exit_code=0,
            error="",
            final_message="OK",
            files_created=[],
            files_modified=[],
        )

    fake_appserver = types.SimpleNamespace(
        execute_codex=_fake_execute_codex,
        is_codex_available=lambda: True,
    )

    config = types.SimpleNamespace(
        v18=types.SimpleNamespace(
            codex_capture_enabled=True,
            codex_protocol_capture_enabled=True,
        ),
        orchestrator=types.SimpleNamespace(model="gpt-5.4"),
    )

    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    class _FakeCheckpoint:
        file_manifest: dict[str, str] = {}

    class _FakeDiff:
        created: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

    result = await execute_wave_with_provider(
        wave_letter="B",
        prompt="Wire the backend.",
        cwd=str(tmp_path),
        config=config,
        provider_map=WaveProviderMap(),
        claude_callback=lambda **kw: 0,
        claude_callback_kwargs={
            "milestone": types.SimpleNamespace(id="milestone-1", title="Test"),
        },
        codex_transport_module=fake_appserver,
        codex_config=CodexConfig(max_retries=1, reasoning_effort="low"),
        codex_home=tmp_path,
        checkpoint_create=lambda label, cwd: _FakeCheckpoint(),
        checkpoint_diff=lambda pre, post: _FakeDiff(),
    )

    # Two attempts ran (EOF on 1, success on 2).
    assert len(attempts_seen) == 2
    assert attempts_seen[0]["attempt_id"] == 1
    assert attempts_seen[1]["attempt_id"] == 2
    # Same session_id on both — generated once at the dispatch boundary.
    assert attempts_seen[0]["session_id"] == attempts_seen[1]["session_id"]
    assert attempts_seen[0]["session_id"] != ""

    capture_dir = tmp_path / ".agent-team" / "codex-captures"
    session_id = attempts_seen[0]["session_id"]

    # Per-attempt stems both materialised on disk — neither was clobbered.
    a1_response = capture_dir / f"milestone-1-wave-B-attempt-01-{session_id}-response.json"
    a2_response = capture_dir / f"milestone-1-wave-B-attempt-02-{session_id}-response.json"
    assert a1_response.is_file(), (
        "B3 r3: attempt-1 per-attempt response artifact must persist on disk "
        "after EOF → retry; pre-fix attempt 2 clobbered it via the shared "
        "legacy stem"
    )
    assert a2_response.is_file()
    assert json.loads(a1_response.read_text(encoding="utf-8")) == {
        "attempt_id": 1,
        "ok": False,
    }
    assert json.loads(a2_response.read_text(encoding="utf-8")) == {
        "attempt_id": 2,
        "ok": True,
    }

    # Capture-index records BOTH attempts in chronological order.
    index_path = capture_dir / "milestone-1-wave-B-capture-index.json"
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["attempts"]) == 2, (
        f"B3 r3: index must contain both attempts; got {index['attempts']}"
    )
    assert index["attempts"][0]["attempt_id"] == 1
    assert index["attempts"][1]["attempt_id"] == 2
    assert index["legacy_stem"] == "milestone-1-wave-B"

    # Legacy stem reflects attempt 2 (the most-recent successful attempt).
    legacy_response = capture_dir / "milestone-1-wave-B-response.json"
    assert legacy_response.is_file()
    assert json.loads(legacy_response.read_text(encoding="utf-8")) == {
        "attempt_id": 2,
        "ok": True,
    }
    # Provider router routed through the codex path. The B3 r3 test scope
    # ends at capture-artifact preservation; downstream codex_hard_failure
    # heuristics (no tracked file changes etc.) are out of scope here.
    assert result["provider"] == "codex"


# ---------------------------------------------------------------------------
# B3 r3 operator-spec — Test 14: mirror+index refresh after EVERY attempt
# (intermediate-state + final-state assertions per outside reviewer brief)
# ---------------------------------------------------------------------------


def test_eof_retry_then_success_refreshes_mirror_and_index_end_to_end(
    tmp_path: Path,
) -> None:
    """B3 r3 operator-spec: stronger than the integration test above —
    asserts the latest-mirror + capture-index state TWICE (after attempt 1
    fails AND after attempt 2 succeeds), proving the helper refreshes on
    EVERY call (no attempt-1 short-circuit, no skip on success path).

    Pre-fix the helper short-circuited at attempt_id == 1, so the
    intermediate-state assertions in this test would fail (no index file,
    no legacy-stem mirror). Reproduction proof in the commit body.
    """
    # Common metadata: session_id is set so per-attempt disambiguation is
    # active for ALL attempts (attempt 1 + attempt 2 both go to per-attempt
    # stems on disk; legacy stem is reproduced ONLY by the helper).
    metadata_a1 = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=1,
        session_id="abcdef01",
    )

    # --- Phase 1: attempt 1 fails (EOF) ---
    a1_paths = build_capture_paths(tmp_path, metadata_a1)
    a1_paths.protocol_path.parent.mkdir(parents=True, exist_ok=True)
    a1_paths.prompt_path.write_text("attempt-1 prompt", encoding="utf-8")
    a1_paths.protocol_path.write_text("OUT initialize\nEOF\n", encoding="utf-8")
    a1_paths.response_path.write_text(
        json.dumps({"attempt": 1, "ok": False}), encoding="utf-8"
    )
    # Attempt 1 EOFs → terminal-diagnostic written.
    a1_paths.diagnostic_path.write_text(
        json.dumps({"attempt": 1, "classification": "transport_stdout_eof_before_turn_completed"}),
        encoding="utf-8",
    )

    update_latest_mirror_and_index(cwd=tmp_path, metadata=metadata_a1)

    capture_dir = tmp_path / ".agent-team" / "codex-captures"
    legacy_diag = capture_dir / "milestone-1-wave-B-terminal-diagnostic.json"
    legacy_response = capture_dir / "milestone-1-wave-B-response.json"
    legacy_protocol = capture_dir / "milestone-1-wave-B-protocol.log"
    index_path = capture_dir / "milestone-1-wave-B-capture-index.json"

    # Assertion set 1 — after attempt 1 fails (EOF):
    # 1a. Attempt-1 terminal-diagnostic.json present at canonical (legacy) path.
    assert legacy_diag.is_file(), (
        "B3 r3 operator-spec: legacy-stem terminal-diagnostic.json must exist "
        "after attempt-1 mirror call. Pre-fix the helper short-circuited at "
        "attempt_id <= 1 and never wrote the legacy stem."
    )
    assert json.loads(legacy_diag.read_text(encoding="utf-8")) == {
        "attempt": 1,
        "classification": "transport_stdout_eof_before_turn_completed",
    }
    # 1b. Latest-mirror points to attempt-1 artifacts.
    assert json.loads(legacy_response.read_text(encoding="utf-8")) == {
        "attempt": 1,
        "ok": False,
    }
    assert legacy_protocol.read_text(encoding="utf-8") == "OUT initialize\nEOF\n"
    # 1c. Capture-index lists exactly attempt 1.
    assert index_path.is_file()
    index_after_a1 = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index_after_a1["attempts"]) == 1
    assert index_after_a1["attempts"][0]["attempt_id"] == 1
    assert index_after_a1["attempts"][0]["session_id"] == "abcdef01"
    assert index_after_a1["legacy_stem"] == "milestone-1-wave-B"

    # --- Phase 2: attempt 2 succeeds ---
    metadata_a2 = _dc_replace(metadata_a1, attempt_id=2)
    a2_paths = build_capture_paths(tmp_path, metadata_a2)
    a2_paths.prompt_path.write_text("attempt-2 prompt (retried)", encoding="utf-8")
    a2_paths.protocol_path.write_text(
        "OUT initialize\nIN turn/completed\n", encoding="utf-8"
    )
    a2_paths.response_path.write_text(
        json.dumps({"attempt": 2, "ok": True}), encoding="utf-8"
    )
    # Success path also writes a diagnostic stub (stub-classification on success).
    a2_paths.diagnostic_path.write_text(
        json.dumps({"attempt": 2, "classification": "natural_turn_completed"}),
        encoding="utf-8",
    )

    update_latest_mirror_and_index(cwd=tmp_path, metadata=metadata_a2)

    # Assertion set 2 — after attempt 2 succeeds:
    # 2a. Attempt-2 capture artifacts present at the disambiguated stem.
    assert a2_paths.prompt_path.is_file()
    assert a2_paths.protocol_path.is_file()
    assert a2_paths.response_path.is_file()
    assert a2_paths.diagnostic_path.is_file()
    # 2b. Latest-mirror NOW points to attempt-2 artifacts (refreshed).
    assert json.loads(legacy_response.read_text(encoding="utf-8")) == {
        "attempt": 2,
        "ok": True,
    }
    assert legacy_protocol.read_text(encoding="utf-8") == (
        "OUT initialize\nIN turn/completed\n"
    )
    assert json.loads(legacy_diag.read_text(encoding="utf-8")) == {
        "attempt": 2,
        "classification": "natural_turn_completed",
    }
    # 2c. Capture-index lists both attempts in chronological order.
    index_after_a2 = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index_after_a2["attempts"]) == 2, (
        "B3 r3 operator-spec: success-path mirror call must append attempt-2 "
        "to the index. Pre-fix the success path never called the helper "
        "(provider_router wrote the diagnostic + broke without refreshing "
        "the legacy mirror), so the index froze at attempt-1."
    )
    assert index_after_a2["attempts"][0]["attempt_id"] == 1
    assert index_after_a2["attempts"][1]["attempt_id"] == 2
    assert index_after_a2["attempts"][0]["session_id"] == "abcdef01"
    assert index_after_a2["attempts"][1]["session_id"] == "abcdef01"
    # 2d. attempt-1 per-attempt artifacts still preserved (NOT clobbered).
    assert a1_paths.diagnostic_path.is_file()
    assert json.loads(a1_paths.diagnostic_path.read_text(encoding="utf-8")) == {
        "attempt": 1,
        "classification": "transport_stdout_eof_before_turn_completed",
    }


# ---------------------------------------------------------------------------
# B3 r4 — Test 19: write_checkpoint_diff_capture mirrors to legacy stem
# ---------------------------------------------------------------------------


def test_write_checkpoint_diff_capture_mirrors_to_legacy_stem(tmp_path: Path) -> None:
    """B3 r4 regression: ``write_checkpoint_diff_capture`` runs on the
    success path AFTER ``update_latest_mirror_and_index`` has already
    swept the per-attempt artifacts to the legacy stem. Pre-fix the
    checkpoint-diff was written ONLY to the per-attempt stem, leaving
    consumers reading ``<base>-checkpoint-diff.json`` (legacy) with no
    file. The fix has ``write_checkpoint_diff_capture`` write to BOTH
    stems when they diverge, so the legacy filename always reflects the
    most-recent attempt's diff.
    """
    metadata_a1 = CodexCaptureMetadata(
        milestone_id="milestone-1",
        wave_letter="B",
        attempt_id=1,
        session_id="cafef00d",
    )

    class _FakeCheckpoint:
        def __init__(self, files: dict[str, str]) -> None:
            self.file_manifest = files
            self.timestamp = "2026-05-04T00:00:00Z"

    class _FakeDiff:
        def __init__(self, *, created: list[str], modified: list[str], deleted: list[str]) -> None:
            self.created = created
            self.modified = modified
            self.deleted = deleted

    pre = _FakeCheckpoint({"keep.txt": "hash1"})
    post = _FakeCheckpoint({"keep.txt": "hash1", "new.txt": "hash2"})
    diff = _FakeDiff(created=["new.txt"], modified=[], deleted=[])

    write_checkpoint_diff_capture(
        cwd=tmp_path,
        metadata=metadata_a1,
        pre_checkpoint=pre,
        post_checkpoint=post,
        diff=diff,
    )

    # Per-attempt stem written (the canonical place the helper writes to).
    per_attempt_path = build_checkpoint_diff_capture_path(tmp_path, metadata_a1)
    assert per_attempt_path.is_file()
    assert "milestone-1-wave-B-attempt-01-cafef00d" in per_attempt_path.name
    per_attempt_payload = json.loads(per_attempt_path.read_text(encoding="utf-8"))
    assert per_attempt_payload["diff_created"] == ["new.txt"]

    # Legacy stem ALSO written via the in-place mirror — consumers reading
    # ``<base>-checkpoint-diff.json`` find the file. Pre-fix this assertion
    # would fail (the legacy path didn't exist).
    legacy_metadata = CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B")
    legacy_path = build_checkpoint_diff_capture_path(tmp_path, legacy_metadata)
    assert legacy_path.is_file(), (
        "B3 r4: write_checkpoint_diff_capture must mirror to the legacy "
        "stem when per-attempt and legacy paths diverge."
    )
    legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert legacy_payload == per_attempt_payload, (
        "B3 r4: legacy-stem mirror must reflect the same payload as the "
        "per-attempt write (most-recent attempt content)."
    )

    # Bumping to attempt 2 with new diff content — legacy mirror MUST be
    # refreshed to reflect attempt-2 (not stale attempt-1).
    metadata_a2 = _dc_replace(metadata_a1, attempt_id=2)
    post2 = _FakeCheckpoint(
        {"keep.txt": "hash1", "new.txt": "hash2", "another.txt": "hash3"}
    )
    diff2 = _FakeDiff(created=["another.txt"], modified=[], deleted=[])

    write_checkpoint_diff_capture(
        cwd=tmp_path,
        metadata=metadata_a2,
        pre_checkpoint=pre,
        post_checkpoint=post2,
        diff=diff2,
    )

    # Legacy mirror updated with attempt-2 content.
    legacy_payload_after_a2 = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert legacy_payload_after_a2["diff_created"] == ["another.txt"]
    # Attempt-1 per-attempt content preserved (not clobbered).
    a1_payload = json.loads(per_attempt_path.read_text(encoding="utf-8"))
    assert a1_payload["diff_created"] == ["new.txt"]


# ---------------------------------------------------------------------------
# B3 r4 — Test 20: legacy callers (no session_id) keep byte-identical output
# ---------------------------------------------------------------------------


def test_write_checkpoint_diff_capture_no_session_id_preserves_legacy_behavior(
    tmp_path: Path,
) -> None:
    """Backward-compat lock: when ``session_id`` is empty, the per-attempt
    and legacy stems coincide. The new mirror branch must short-circuit
    (Path.resolve() src==dst guard) and NOT double-write — preserving
    byte-identical legacy behavior for callers pre-dating B3."""
    metadata = CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B")

    class _FakeCheckpoint:
        file_manifest: dict[str, str] = {}
        timestamp = None

    class _FakeDiff:
        created: list[str] = ["a.txt"]
        modified: list[str] = []
        deleted: list[str] = []

    pre = _FakeCheckpoint()
    post = _FakeCheckpoint()
    diff = _FakeDiff()

    write_checkpoint_diff_capture(
        cwd=tmp_path,
        metadata=metadata,
        pre_checkpoint=pre,
        post_checkpoint=post,
        diff=diff,
    )

    # Per-attempt and legacy stems coincide → exactly one file at the
    # legacy path with the expected content.
    legacy_path = build_checkpoint_diff_capture_path(tmp_path, metadata)
    assert legacy_path.is_file()
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert payload["diff_created"] == ["a.txt"]
    # No accidental per-attempt file was created (because the stems
    # coincide — the test verifies that the resolve()-based guard was
    # effective and we didn't end up with duplicates / mistargeted files).
    capture_dir = tmp_path / ".agent-team" / "codex-captures"
    diff_files = list(capture_dir.glob("*-checkpoint-diff.json"))
    assert len(diff_files) == 1, (
        f"B3 r4 backward-compat: expected exactly one checkpoint-diff "
        f"file when session_id is empty; got {diff_files}"
    )


# ---------------------------------------------------------------------------
# wave-1-cleanup #4 — full source-level lock for ALL 8 outer-write sites
# ---------------------------------------------------------------------------


def test_all_outer_hang_report_sites_thread_cumulative_wedges_so_far() -> None:
    """B3-broad cleanup #4 source-level lock: ALL outer-catch
    ``_write_hang_report`` call sites in ``wave_executor.py`` MUST thread
    ``cumulative_wedges_so_far=_get_cumulative_wedge_count()``. Pre-fix
    the original B3-broad round 1 covered only 4 of 8 sites; the
    remaining 4 (Wave T fix-loop catch + 3 wrapper catches around
    ``_invoke_sdk_sub_agent_with_watchdog``) silently produced hang
    reports without the cumulative-wedge counter, breaking the §M.M4
    forensic invariant on those failure paths.

    This test enumerates every outer-catch ``_write_hang_report`` call
    site in wave_executor.py and asserts each one passes the
    cumulative_wedges_so_far kwarg. Inner-watchdog sites
    (``_invoke_sdk_*_with_watchdog``) already threaded the field via
    round 1; outer-catch sites are the surface this lock covers.
    """
    src = (Path(we.__file__)).read_text(encoding="utf-8")

    # Find every `_write_hang_report(` CALL (not the def). We exclude the
    # `def _write_hang_report(` line because its parameter list is the
    # signature, not a call site. Verify the cumulative_wedges_so_far
    # kwarg appears within the call's parenthesised body. We bound the
    # body by scanning to the next closing-paren-on-its-own-line — works
    # because all real call sites in wave_executor.py use multi-line
    # kwargs formatting.
    call_re = re.compile(r"(?<!def )_write_hang_report\(\s*\n", re.MULTILINE)
    body_end_re = re.compile(r"^\s*\)", re.MULTILINE)

    call_sites: list[tuple[int, str]] = []  # (line_no, body_text)
    for match in call_re.finditer(src):
        # Find the matching close-paren on its own line after the call.
        body_start = match.end()
        body_close = body_end_re.search(src, body_start)
        if body_close is None:
            continue
        body = src[body_start:body_close.start()]
        line_no = src.count("\n", 0, match.start()) + 1
        call_sites.append((line_no, body))

    # Sanity check: we expect at least 8 outer-catch sites + several inner
    # sites. The actual count is environment-dependent, but every site
    # MUST thread the kwarg.
    assert len(call_sites) >= 8, (
        f"Expected ≥8 _write_hang_report call sites in wave_executor.py; "
        f"found {len(call_sites)}. Source may have been refactored."
    )

    missing: list[int] = []
    for line_no, body in call_sites:
        if "cumulative_wedges_so_far=_get_cumulative_wedge_count()" not in body:
            missing.append(line_no)

    assert missing == [], (
        f"B3-broad cleanup #4: {len(missing)} _write_hang_report call "
        f"site(s) at line(s) {missing} are missing "
        f"cumulative_wedges_so_far=_get_cumulative_wedge_count(). All "
        f"outer-catch + inner-watchdog sites MUST thread this kwarg "
        f"to preserve the §M.M4 forensic invariant."
    )
