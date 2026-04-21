"""Phase 1 Task 1.3: Codex-to-Claude cross-protocol bridge."""
from __future__ import annotations

from pathlib import Path


def test_wave_to_lead_mapping_is_exact():
    """WAVE_TO_LEAD routes every Codex wave to a concrete Claude lead."""
    from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD

    assert WAVE_TO_LEAD == {
        "A5": "wave-a-lead",
        "B": "wave-a-lead",
        "D": "wave-d5-lead",
        "T5": "wave-t-lead",
    }


def test_wave_to_lead_references_valid_leads():
    """Every value in WAVE_TO_LEAD must be a member of PHASE_LEAD_NAMES."""
    from agent_team_v15.agent_teams_backend import AgentTeamsBackend
    from agent_team_v15.codex_lead_bridge import WAVE_TO_LEAD

    for wave, lead in WAVE_TO_LEAD.items():
        assert lead in AgentTeamsBackend.PHASE_LEAD_NAMES, (
            f"WAVE_TO_LEAD[{wave!r}] = {lead!r} not in PHASE_LEAD_NAMES "
            f"({AgentTeamsBackend.PHASE_LEAD_NAMES})"
        )


def test_route_codex_wave_complete_writes_file(tmp_path: Path):
    """route_codex_wave_complete writes a CODEX_WAVE_COMPLETE message file."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete

    route_codex_wave_complete(
        wave_letter="B",
        context_dir=tmp_path,
        result_summary="Created schema.prisma (42 lines). Created seed.ts (18 lines).",
    )
    written = list(tmp_path.glob("msg_*_codex-wave-b_to_wave-a-lead.md"))
    assert len(written) == 1, f"expected exactly one message file, found {written}"
    body = written[0].read_text(encoding="utf-8")
    assert "Type: CODEX_WAVE_COMPLETE" in body
    assert "To: wave-a-lead" in body
    assert "schema.prisma" in body


def test_route_codex_wave_complete_unknown_wave_is_fail_open(tmp_path: Path):
    """Unknown wave letters are logged and skipped without raising."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete

    route_codex_wave_complete(
        wave_letter="ZZ",
        context_dir=tmp_path,
        result_summary="unused",
    )
    assert list(tmp_path.iterdir()) == []


def test_route_codex_wave_complete_missing_dir_autocreates_message(tmp_path: Path):
    """Missing context_dir is created and receives the message."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete

    missing = tmp_path / "does-not-exist"
    route_codex_wave_complete(
        wave_letter="B",
        context_dir=missing,
        result_summary="unused",
    )
    written = list(missing.glob("msg_*_codex-wave-b_to_wave-a-lead.md"))
    assert len(written) == 1


def test_route_codex_wave_complete_write_error_is_fail_open(tmp_path: Path, monkeypatch):
    """Write failures are swallowed by the fail-open bridge contract."""
    from agent_team_v15.codex_lead_bridge import route_codex_wave_complete

    def raise_oserror(self: Path, *args, **kwargs) -> int:
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "write_text", raise_oserror)

    route_codex_wave_complete(
        wave_letter="B",
        context_dir=tmp_path,
        result_summary="unused",
    )


def test_read_pending_steer_requests_empty_when_no_files(tmp_path: Path):
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests

    assert read_pending_steer_requests(wave_letter="B", context_dir=tmp_path) == []


def test_read_pending_steer_requests_reads_matching_files(tmp_path: Path):
    """Reads STEER_REQUEST files addressed to the given wave."""
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests

    steer = tmp_path / "msg_1234_wave-a-lead_to_codex-wave-b.md"
    steer.write_text(
        "To: codex-wave-b\n"
        "From: wave-a-lead\n"
        "Type: STEER_REQUEST\n"
        "Timestamp: 1234\n"
        "---\n"
        "Fix PORT in main.ts to 3001",
        encoding="utf-8",
    )
    messages = read_pending_steer_requests(wave_letter="B", context_dir=tmp_path)
    assert len(messages) == 1
    assert "PORT" in messages[0]


def test_read_pending_steer_requests_unreadable_file_is_fail_open(
    tmp_path: Path,
    monkeypatch,
):
    """Unreadable matching files are skipped without raising."""
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests

    steer = tmp_path / "msg_1234_wave-a-lead_to_codex-wave-b.md"
    steer.write_text(
        "To: codex-wave-b\n"
        "From: wave-a-lead\n"
        "Type: STEER_REQUEST\n"
        "Timestamp: 1234\n"
        "---\n"
        "Fix PORT in main.ts to 3001",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def raise_for_steer(self: Path, *args, **kwargs) -> str:
        if self == steer:
            raise OSError("simulated unreadable steer file")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raise_for_steer)

    assert read_pending_steer_requests(wave_letter="B", context_dir=tmp_path) == []


def test_read_pending_steer_requests_missing_dir_is_fail_open(tmp_path: Path):
    from agent_team_v15.codex_lead_bridge import read_pending_steer_requests

    missing = tmp_path / "does-not-exist"
    assert read_pending_steer_requests(wave_letter="B", context_dir=missing) == []
