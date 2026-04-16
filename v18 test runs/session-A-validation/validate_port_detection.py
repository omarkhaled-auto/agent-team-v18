"""Phase A production-caller proof for N-01: endpoint_prober._detect_app_url precedence.

Exercises the 6-source precedence chain against real tmpdir fixtures and asserts
each source resolves in priority order. Also asserts the LOUD warning fires on
total fallback to :3080.

Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from agent_team_v15.endpoint_prober import _detect_app_url  # noqa: E402


def _cfg(app_port: int = 0) -> SimpleNamespace:
    return SimpleNamespace(browser_testing=SimpleNamespace(app_port=app_port))


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label}: {detail}")
    sys.exit(1)


def _pass(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def _scenario(label: str, fixture_builder, expected_url: str, expect_warning: bool) -> None:
    with tempfile.TemporaryDirectory(prefix=f"n01_{label}_") as tmp:
        project_root = Path(tmp)
        fixture_builder(project_root)

        records: list[logging.LogRecord] = []
        handler = _CapturingHandler(records)
        prober_logger = logging.getLogger("agent_team_v15.endpoint_prober")
        prev_level = prober_logger.level
        prober_logger.addHandler(handler)
        prober_logger.setLevel(logging.WARNING)
        try:
            got = _detect_app_url(project_root, _cfg(0))
        finally:
            prober_logger.removeHandler(handler)
            prober_logger.setLevel(prev_level)

        if got != expected_url:
            _fail(label, f"expected {expected_url!r}, got {got!r}")

        fallback_warn = any("3080" in rec.getMessage() and "fall" in rec.getMessage().lower()
                            for rec in records if rec.levelno >= logging.WARNING)
        if expect_warning and not fallback_warn:
            _fail(f"{label}_warning_present",
                  f"expected LOUD :3080 fallback warning; got records={[r.getMessage() for r in records]}")
        if not expect_warning and fallback_warn:
            _fail(f"{label}_warning_absent",
                  f"unexpected fallback warning: {[r.getMessage() for r in records]}")

        _pass(label, f"url={got} warnings={len(records)}")


class _CapturingHandler(logging.Handler):
    def __init__(self, sink: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record)


def main() -> int:
    _scenario("config_app_port_precedence",
              lambda r: None,
              "http://localhost:3080",
              expect_warning=True)

    def f1(r: Path) -> None:
        (r / ".env").write_text("PORT=8080\n", encoding="utf-8")
    _scenario("root_env_precedence", f1, "http://localhost:8080", expect_warning=False)

    def f2(r: Path) -> None:
        api_dir = r / "apps" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / ".env.example").write_text("DATABASE_URL=postgres://x\nPORT=4000\n", encoding="utf-8")
    _scenario("apps_api_env_example", f2, "http://localhost:4000", expect_warning=False)

    def f3(r: Path) -> None:
        src = r / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "main.ts").write_text(
            "async function bootstrap() {\n  await app.listen(4321);\n}\n",
            encoding="utf-8",
        )
    _scenario("main_ts_literal", f3, "http://localhost:4321", expect_warning=False)

    def f4(r: Path) -> None:
        src = r / "apps" / "api" / "src"
        src.mkdir(parents=True)
        (src / "main.ts").write_text("await app.listen(process.env.PORT ?? 4567);\n", encoding="utf-8")
    _scenario("main_ts_process_env_default", f4, "http://localhost:4567", expect_warning=False)

    def f5(r: Path) -> None:
        (r / "docker-compose.yml").write_text(
            "services:\n  api:\n    ports:\n      - '4000:4000'\n",
            encoding="utf-8",
        )
    _scenario("docker_compose_short", f5, "http://localhost:4000", expect_warning=False)

    def f6(r: Path) -> None:
        api_dir = r / "apps" / "api"
        src_dir = api_dir / "src"
        src_dir.mkdir(parents=True)
        (api_dir / ".env.example").write_text("PORT=4000\n", encoding="utf-8")
        (src_dir / "main.ts").write_text("await app.listen(3000);\n", encoding="utf-8")
    _scenario("precedence_env_example_beats_main_ts", f6,
              "http://localhost:4000", expect_warning=False)

    _scenario("fallback_loud_warning",
              lambda r: None,
              "http://localhost:3080",
              expect_warning=True)

    print()
    print("[OVERALL] N-01 precedence + loud-fallback proof PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
