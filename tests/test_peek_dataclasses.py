from agent_team_v15.wave_executor import (
    PeekResult,
    PeekSchedule,
    _CODEX_WAVES,
    build_peek_schedule,
)


def test_peek_result_no_interrupt_in_log_only():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=True)
    assert r.should_interrupt is False


def test_peek_result_interrupt_when_live_and_confident():
    r = PeekResult(file_path="x.ts", wave="B", verdict="issue", confidence=0.9, log_only=False)
    assert r.should_interrupt is True


def test_peek_schedule_wave_type():
    """PeekSchedule knows whether to use file-poll or notification strategy."""
    claude_schedule = PeekSchedule(wave="A", trigger_files=[])
    codex_schedule = PeekSchedule(wave="B", trigger_files=[])
    assert claude_schedule.uses_notifications is False
    assert codex_schedule.uses_notifications is True


def test_build_peek_schedule_parses_requirements():
    req = "## Deliverables\n- [ ] apps/api/prisma/schema.prisma\n- [ ] apps/api/src/main.ts\n"
    schedule = build_peek_schedule(requirements_text=req, wave="A")
    assert "apps/api/prisma/schema.prisma" in schedule.trigger_files
    assert "apps/api/src/main.ts" in schedule.trigger_files
    assert schedule.wave == "A"


def test_codex_waves_constant_includes_b_and_d():
    assert "B" in _CODEX_WAVES
    assert "D" in _CODEX_WAVES
    assert "A5" in _CODEX_WAVES
    assert "T5" in _CODEX_WAVES
    assert "A" not in _CODEX_WAVES
    assert "D5" not in _CODEX_WAVES
    assert "T" not in _CODEX_WAVES
    assert "E" not in _CODEX_WAVES


def test_peek_schedule_uses_notifications_is_case_insensitive():
    schedule = PeekSchedule(wave="b", trigger_files=[])
    assert schedule.uses_notifications is True
