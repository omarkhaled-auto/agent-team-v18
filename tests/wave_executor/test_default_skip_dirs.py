"""Regression test for _DEFAULT_SKIP_DIRS — every entry must be pruned at descent."""

from __future__ import annotations

from agent_team_v15.wave_executor import _capture_file_fingerprints


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

    fingerprints = _capture_file_fingerprints(str(tmp_path))

    assert list(fingerprints.keys()) == ["src/app.py"]
