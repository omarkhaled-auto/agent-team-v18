import ast
import hashlib
import inspect
import subprocess
from pathlib import Path

from agent_team_v15 import cli as cli_module


NEW_SCHEMA_PASS_SUMMARY = "Schema validation: PASS"
OLD_SCHEMA_CLEAN_SUMMARY = "Schema:" + " CLEAN"
CLASSIFIER_BODY_SHA256 = (
    "b8d6ffb2862a8b087cf52b2685c72f8ac9e713a71b4975a1aad386f6a1e26222"
)
ALLOWED_OLD_SCHEMA_CLEAN_PATHS = {
    Path("tests/fixtures/smoke_2026_04_26/STATE.json"),
    Path("docs/plans/phase-artifacts/2026-05-04-m1-clean-run-blockers-handoff.md"),
}


def _cli_path() -> Path:
    source_file = inspect.getsourcefile(cli_module)
    assert source_file is not None
    return Path(source_file)


def _repo_root() -> Path:
    return _cli_path().parents[2]


def _git_tracked_live_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "src", "tests", "docs"],
        cwd=_repo_root(),
        check=True,
        text=True,
        capture_output=True,
    )
    paths = []
    for line in result.stdout.splitlines():
        relative_path = Path(line)
        if relative_path in ALLOWED_OLD_SCHEMA_CLEAN_PATHS:
            continue
        paths.append(relative_path)
    return paths


def _function_body_bytes(function_name: str) -> bytes:
    source_path = _cli_path()
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            lines = source_path.read_bytes().splitlines(keepends=True)
            body_start = node.body[0].lineno
            body_end = node.end_lineno
            assert body_end is not None
            return b"".join(lines[body_start - 1 : body_end])
    raise AssertionError(f"{function_name} not found in cli.py")


def test_final_schema_validation_clean_branch_appends_pass_summary() -> None:
    source = inspect.getsource(cli_module._run_prd_milestones)

    assert f'_final_validation_summary.append("{NEW_SCHEMA_PASS_SUMMARY}")' in source
    assert OLD_SCHEMA_CLEAN_SUMMARY not in source


def test_phase_4_5_terminal_transport_failure_reason_body_is_locked() -> None:
    body = _function_body_bytes("_phase_4_5_terminal_transport_failure_reason")

    assert hashlib.sha256(body).hexdigest() == CLASSIFIER_BODY_SHA256


def test_phase_4_5_terminal_transport_failure_reason_keeps_preflight_first() -> None:
    source = inspect.getsource(
        cli_module._phase_4_5_terminal_transport_failure_reason
    )

    preflight_positions = [
        source.index("codex_appserver_preflight_failed"),
        source.index("codex appserver preflight failed"),
        source.index("codex app-server preflight failed"),
    ]
    eof_position = source.index("contains_transport_stdout_eof_classification")

    assert max(preflight_positions) < eof_position


def test_op4_committed_scope_has_new_schema_pass_label_only() -> None:
    repo_root = _repo_root()
    cli_relative_path = Path("src/agent_team_v15/cli.py")
    cli_text = (repo_root / cli_relative_path).read_text(encoding="utf-8")

    assert NEW_SCHEMA_PASS_SUMMARY in cli_text

    old_literal = OLD_SCHEMA_CLEAN_SUMMARY.encode("utf-8")
    stale_hits = []
    for relative_path in _git_tracked_live_paths():
        path = repo_root / relative_path
        if not path.is_file():
            continue
        if old_literal in path.read_bytes():
            stale_hits.append(relative_path.as_posix())

    assert stale_hits == []
