"""Tests for D-12 telemetry — _WaveWatchdogState.record_progress tool_name retention."""
from agent_team_v15.wave_executor import _WaveWatchdogState


def test_tool_name_empty_on_init():
    state = _WaveWatchdogState()
    assert state.last_tool_name == ""


def test_tool_name_retained_after_non_tool_message():
    state = _WaveWatchdogState()
    state.record_progress(tool_name="write_file")
    assert state.last_tool_name == "write_file"
    # Subsequent call with empty tool_name should NOT clear it
    state.record_progress(tool_name="")
    assert state.last_tool_name == "write_file"


def test_tool_name_updated_on_new_tool():
    state = _WaveWatchdogState()
    state.record_progress(tool_name="write_file")
    assert state.last_tool_name == "write_file"
    state.record_progress(tool_name="read_file")
    assert state.last_tool_name == "read_file"


def test_tool_name_not_cleared_by_result_message():
    state = _WaveWatchdogState()
    state.record_progress(tool_name="write_file", message_type="tool_use")
    assert state.last_tool_name == "write_file"
    # result_message with no tool_name should not clear
    state.record_progress(message_type="result_message")
    assert state.last_tool_name == "write_file"
