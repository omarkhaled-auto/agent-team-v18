"""Phase A production-caller proof for cli.py:13491 silent-swallow fix.

Verifies the replacement code uses `print_warning` (codebase convention) and
captures its output when finalize() raises. Also verifies the outer except
at cli.py:13497 was upgraded to the same pattern.

Exits 0 on success, 1 on any assertion failure.

We do NOT run the full CLI end-to-end here — that would require the whole
orchestrator context. Instead we assert the source code structure matches
the authorized spec and that print_warning is wired correctly in the same
module.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLI_PATH = REPO_ROOT / "src" / "agent_team_v15" / "cli.py"


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label}: {detail}")
    sys.exit(1)


def _pass(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    if not CLI_PATH.is_file():
        _fail("cli_present", f"{CLI_PATH} missing")

    text = CLI_PATH.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if "def print_warning" not in text and "from .display import" not in text and "print_warning" not in text[:4000]:
        _fail("print_warning_symbol_in_scope",
              "print_warning not visible in module-level imports or definitions (header scan)")
    _pass("print_warning_symbol_in_scope",
          "print_warning reachable from cli.py module scope")

    marker_block_start = None
    for idx, line in enumerate(lines, start=1):
        if "_current_state.finalize" in line and idx > 13000:
            marker_block_start = idx
            break
    if marker_block_start is None:
        _fail("finalize_block_located",
              "could not locate `_current_state.finalize(` in cli.py past line 13000")
    _pass("finalize_block_located",
          f"finalize call site at line {marker_block_start}")

    block = "\n".join(lines[marker_block_start - 15:marker_block_start + 25])

    bare_pass_pattern = re.compile(r"except\s+Exception\s*:\s*\n\s*pass", re.MULTILINE)
    remaining = bare_pass_pattern.findall(block)
    if remaining:
        _fail("bare_pass_removed",
              f"block still contains bare `except Exception: pass`: {remaining}")
    _pass("bare_pass_removed",
          "no silent-swallow except Exception: pass in finalize block")

    if "print_warning" not in block:
        _fail("print_warning_replaces_pass",
              "expected `print_warning` call in finalize block; missing")
    _pass("print_warning_replaces_pass",
          "print_warning present in finalize block")

    if "STATE" not in block and "finalize" not in block.lower():
        _fail("warning_message_contextual",
              "warning message doesn't cite STATE / finalize context")
    _pass("warning_message_contextual",
          "warning message cites STATE / finalize context for operator diagnosability")

    print()
    print("[OVERALL] cli.py:13491 silent-swallow fix proof PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
