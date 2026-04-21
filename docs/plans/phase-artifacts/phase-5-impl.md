# Phase 5 — Semantic Observer: Implementation Brief

## Phase Context

**Phase:** 5 — Semantic Observer
**Depends on:** Phase 0 (turn_steer, notification handlers, thread persistence), Phase 3 (`ObserverConfig`, `PeekResult`, `PeekSchedule`, `build_peek_schedule`), Phase 4 (`_OrphanWatchdog` observer fields, `_WaveWatchdogState.peek_log`, `_WaveWatchdogState.last_peek_monotonic`, peek injection block in Claude polling loop, Phase 4 stub in `_wait_for_turn_completion`).
**Enables:** Phase 6 (end-to-end smoke verification — observer JSONL artifacts and `peek_summary` are the evidence surface).

**Purpose.** Replace the Phase 4 placeholder stub inside `_wait_for_turn_completion` with real rule-based plan/diff checks, wire a time-based peek trigger for Claude waves, and surface observer activity post-wave via `WaveResult.peek_summary`.

**Hard rules for this phase (non-negotiable):**
- Rule-based ONLY for Codex waves. `codex_observer_checks.py` uses pure Python regex. No Anthropic SDK import, no API calls, no `asyncio.to_thread`, no network.
- Semantic Haiku checks are an explicitly deferred future enhancement gated by `codex_semantic_check_enabled` (default False). **Do not implement Haiku in Phase 5.**
- Fail-open everywhere. Every public function returns `""` (empty string, meaning "no steer") on any internal exception.
- No test may use `assert X or True`. Every assertion must be specific and falsifiable.
- Observer imports in `codex_appserver.py` happen at the call site (inside the function body), **not** at module top. Rationale: `codex_observer_checks` is a peer module; top-level import works today but the local import pattern protects against future circular-import refactors and keeps the fail-open `except Exception:` wrapper covering the import itself.

---

## Pre-Flight: Files to Read

> **PREREQUISITE CHECK — Run before starting any task:**
> ```bash
> python -c "from agent_team_v15.codex_appserver import _OrphanWatchdog; w = _OrphanWatchdog(); assert hasattr(w, 'codex_last_plan'), 'Phase 4 not landed'"
> python -c "from agent_team_v15.wave_executor import _WaveWatchdogState; w = _WaveWatchdogState(); assert hasattr(w, 'peek_log'), 'Phase 3/4 not landed'"
> grep -c '# Phase 5 will replace this stub' src/agent_team_v15/codex_appserver.py
> ```
> If ANY of these fail: **STOP. Phase 5 cannot proceed.** Implement Phases 3 and 4 first (using `phase-3-impl.md` and `phase-4-impl.md`), then return to this artifact. The `getattr` guards in Task 5.3 are load-bearing fallbacks for when these phases are not yet applied — they are NOT a workaround for skipping Phase 3/4.

Read every entry below before writing a single character of code. The line numbers are the state at the start of Phase 5; re-grep if you suspect drift.

| # | Path | Lines | What to confirm |
|---|------|-------|-----------------|
| 1 | `src/agent_team_v15/wave_executor.py` | 62–128 | `WaveResult` dataclass. Last existing field before the closing `__post_init__`-absent boundary is `scope_violations: list[str] = field(default_factory=list)` at line 127. Append `peek_summary` immediately after it. |
| 2 | `src/agent_team_v15/wave_executor.py` | 2583–2663 | `_invoke_wave_sdk_with_watchdog(*, execute_sdk_call, prompt, wave_letter, config, cwd, milestone) -> tuple[float, _WaveWatchdogState]`. **This function returns a tuple, not a `WaveResult`.** See correction #7 below — the teammate-message wording is a plan artifact; the real population site is the caller, where `wave_result` and `watchdog_state` coexist. |
| 3 | `src/agent_team_v15/wave_executor.py` | 3853–3870 | Caller block inside `_execute_single_wave_sdk`: `cost, watchdog_state = await _invoke_wave_sdk_with_watchdog(...)`. The lines that copy `watchdog_state.last_message_type` onto `wave_result` (currently line 3863) are the correct site for `peek_summary` population. Two other sibling sites exist at ~3332 and ~3800. Update all three. |
| 4 | `src/agent_team_v15/wave_executor.py` | 2499 | `_capture_file_fingerprints()` — already in scope inside `_invoke_wave_sdk_with_watchdog`. No changes. |
| 5 | `src/agent_team_v15/codex_appserver.py` | 116–166 | `_OrphanWatchdog`. Phase 0/4 extend `__init__` with: `observer_config`, `requirements_text`, `wave_letter`, `codex_last_plan`, `codex_latest_diff`. Before writing Phase 5 code, verify with `grep -n "codex_last_plan\|codex_latest_diff\|observer_config\|wave_letter" src/agent_team_v15/codex_appserver.py`. If any are missing, STOP and raise it — Phase 4 handoff is incomplete. |
| 6 | `src/agent_team_v15/codex_appserver.py` | 885–924 | `_wait_for_turn_completion(client, *, thread_id, turn_id, watchdog, tokens, progress_callback, messages, capture_session)`. Variables `client`, `thread_id`, `turn_id`, `watchdog` are in scope. Find Phase 4 stub — grep for `# Phase 5 will replace this stub` inside this function and replace exactly that block. |
| 7 | `src/agent_team_v15/codex_observer_checks.py` | — | File must not exist yet. `ls src/agent_team_v15/codex_observer_checks.py` must return "No such file" before Task 5.1 begins. If it already exists, Phase 5 has been partially run — review and reconcile, do not overwrite blindly. |
| 8 | `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | 1809–2030 | Phase 5 section of master plan — pattern source for `_FRONTEND_FILE_PATTERNS` and `_BACKEND_FILE_PATTERNS`, and structure of `peek_summary` dict. |
| 9 | `tests/test_v18_wave_executor_extended.py` | top 50 lines | Test fixture style — imports, `pytest` idioms used elsewhere in the suite. Match it. |

**Divergence flag (corrections precedence):** The master plan (line 1886 onwards) defines signatures `check_plan_against_requirements(plan_steps, requirements, wave)` and `check_diff_against_requirements(diff, requirements, wave)`. The Phase 5 corrections supplied by the teammate lead redefine the public API to `check_codex_plan(plan_lines: list[str], wave_letter: str) -> str` and `check_codex_diff(diff_text: str, wave_letter: str) -> str`. **Use the teammate-lead signatures** — corrections list takes precedence per rule #5. Do not expose `_against_requirements` names.

---

## Pre-Flight: Context7 Research

Run these exactly. Record the result in your scratch notes before coding.

1. `mcp__context7__resolve-library-id` with `libraryName: "python"` → pick the CPython stdlib entry (usually `/python/cpython`). Confirm it resolves.
2. `mcp__context7__query-docs` against that ID with topic `"re.search vs re.match"`. Confirm: `re.search` scans the full string; `re.match` only matches at position 0. For "does this diff line contain `apps/web/`?" you want `re.search` (or `.search()` on a compiled Pattern). Use `re.search` / compiled-Pattern `.search()` everywhere in `codex_observer_checks.py`. Never use `re.match` for path detection.
3. `mcp__context7__query-docs` for `"anthropic claude-haiku-4-5-20251001"`. Confirm the model ID string is valid for the Anthropic SDK. **Only relevant as a future flag value** — do not import `anthropic` in this phase.
4. Note in your scratch: `codex_observer_checks.py` imports ONLY `re` and `logging`. No `anthropic`, no `httpx`, no `asyncio`.

---

## Pre-Flight: Sequential Thinking

Before writing Task 5.1, invoke `mcp__sequential-thinking__sequentialthinking` with the prompt defined by the teammate lead (scope-drift pattern design). The design conclusion MUST answer, at minimum:

- **Wave-to-forbidden-pattern-set map.** Wave B → `_FRONTEND_FILE_PATTERNS`. Wave D → `_BACKEND_FILE_PATTERNS`. All other waves → no rule (return `""`).
- **Threshold.** `_DRIFT_THRESHOLD = 2`. A single incidental cross-wave touch does not trigger; two or more distinct file-path hits do. Rationale: a backend wave might legitimately edit one small shared config; two+ hits indicate the agent is building the wrong layer.
- **Where to scan.** In `check_codex_diff`, scan the diff headers (`+++ b/...` and `diff --git a/... b/...`) for file paths; deduplicate by path so one file with many hunks counts once. In `check_codex_plan`, scan each plan line as raw text.
- **Steer-message shape.** One sentence stating the wave identity, one listing up to three offending paths, one directing what to focus on. Under 300 characters.
- **Small-diff floor.** `check_codex_diff` returns `""` if fewer than 3 distinct changed files appear in the diff (`diff --git` count). Rationale: early-turn diffs are noisy; we must not false-positive on the first file the agent touches.

Patterns (final — these are the values the implementation MUST use):

```python
_FRONTEND_FILE_PATTERNS = [
    re.compile(r"apps/web/"),
    re.compile(r"(^|/)pages/"),
    re.compile(r"(^|/)components/"),
    re.compile(r"\.tsx$"),
    re.compile(r"\.jsx$"),
    re.compile(r"\.css$"),
    re.compile(r"tailwind\.config"),
]

_BACKEND_FILE_PATTERNS = [
    re.compile(r"apps/api/"),
    re.compile(r"(^|/)prisma/"),
    re.compile(r"nest-cli\.json"),
    re.compile(r"\.module\.ts$"),
    re.compile(r"(^|/)Dockerfile(\.|$)"),
    re.compile(r"docker-compose(\.[^/]+)?\.ya?ml$"),
    re.compile(r"\.py$"),
]

_DRIFT_THRESHOLD = 2
_SMALL_DIFF_FLOOR = 3  # require >= 3 changed files in the diff before a steer can fire
```

---

## Corrections Applied (Phase 5)

**Correction #7 — peek_summary population site.**
The teammate brief says "just before final return in `_invoke_wave_sdk_with_watchdog`". Reading source: that function's signature is `-> tuple[float, _WaveWatchdogState]`, so there is no `WaveResult` in scope. Applying rule #5 (source wins over plan wording), the actual population site is the **caller** at `wave_executor.py:3853` (`_execute_single_wave_sdk`, the Claude wave branch), along with its two siblings (~3332 in the provider-routing path, ~3800 in the retry path). `watchdog_state` is already destructured from the tuple there and already used to populate `wave_result.last_sdk_message_type` — `peek_summary` piggy-backs on the same lines. This preserves the brief's intent ("populate from `state.peek_log` at the point the watchdog run ends") without forcing a return-signature change that Phase 5 is not scoped for.

**Correction #9 — `or True` fatal test anti-pattern.**
`assert X or True` is always True regardless of `X`. Any test written with this pattern silently passes and gives zero signal. The Phase 5 test file `tests/test_codex_observer_checks.py` MUST NOT contain the substring `or True` in any assertion. The Phase Gate includes an explicit grep guard for this.

---

## Task-by-Task Implementation

### Task 5.1 — Create `codex_observer_checks.py` and its tests

**Files to create:**
- `src/agent_team_v15/codex_observer_checks.py`
- `tests/test_codex_observer_checks.py`

**Step A — Write the implementation module.** Write exactly this content:

```python
"""Rule-based scope-drift checks for Codex plan and diff notifications.

Pure Python regex matching. NO Anthropic SDK, NO API calls, NO network.
Every public entrypoint is fail-open: any internal exception returns "".

Future extension: `codex_semantic_check_enabled` flag may add a Haiku
semantic layer. NOT implemented in Phase 5 — do not add imports for it.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_FRONTEND_FILE_PATTERNS = [
    re.compile(r"apps/web/"),
    re.compile(r"(^|/)pages/"),
    re.compile(r"(^|/)components/"),
    re.compile(r"\.tsx$"),
    re.compile(r"\.jsx$"),
    re.compile(r"\.css$"),
    re.compile(r"tailwind\.config"),
]

_BACKEND_FILE_PATTERNS = [
    re.compile(r"apps/api/"),
    re.compile(r"(^|/)prisma/"),
    re.compile(r"nest-cli\.json"),
    re.compile(r"\.module\.ts$"),
    re.compile(r"(^|/)Dockerfile(\.|$)"),
    re.compile(r"docker-compose(\.[^/]+)?\.ya?ml$"),
    re.compile(r"\.py$"),
]

_WAVE_FORBIDDEN: dict[str, list[re.Pattern[str]]] = {
    "B": _FRONTEND_FILE_PATTERNS,
    "D": _BACKEND_FILE_PATTERNS,
}

_WAVE_ROLE: dict[str, str] = {
    "B": "backend wave (Python/server-side code only)",
    "D": "frontend wave (React/TypeScript UI only)",
}

_DRIFT_THRESHOLD = 2
_SMALL_DIFF_FLOOR = 3

_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)
_DIFF_PLUSPLUS_HEADER = re.compile(r"^\+\+\+ b/(\S+)", re.MULTILINE)


def _forbidden_for(wave_letter: str) -> list[re.Pattern[str]] | None:
    if not isinstance(wave_letter, str):
        return None
    return _WAVE_FORBIDDEN.get(wave_letter.strip().upper())


def _matches_any(path: str, patterns: list[re.Pattern[str]]) -> bool:
    for pat in patterns:
        if pat.search(path):
            return True
    return False


def _steer_message(wave_letter: str, offending: list[str]) -> str:
    role = _WAVE_ROLE.get(wave_letter.upper(), f"wave {wave_letter}")
    sample = ", ".join(f"`{p}`" for p in offending[:3])
    return (
        f"[Observer] Wave {wave_letter.upper()} is the {role}. "
        f"The current step touches out-of-scope files ({sample}). "
        f"Stop editing those and focus on this wave's assigned deliverables only."
    )


def check_codex_plan(plan_lines: list[str], wave_letter: str) -> str:
    """Return a steer message if the plan drifts out of the wave's scope, else "".

    Fail-open: any internal exception returns "".
    """
    try:
        patterns = _forbidden_for(wave_letter)
        if not patterns or not plan_lines:
            return ""
        hits: list[str] = []
        for line in plan_lines:
            if not isinstance(line, str) or not line.strip():
                continue
            if _matches_any(line, patterns):
                hits.append(line.strip()[:120])
            if len(hits) >= _DRIFT_THRESHOLD:
                return _steer_message(wave_letter, hits)
        return ""
    except Exception:
        logger.warning("codex plan check failed (fail-open)", exc_info=True)
        return ""


def check_codex_diff(diff_text: str, wave_letter: str) -> str:
    """Return a steer message if the diff shows scope drift, else "".

    Fail-open: any internal exception returns "".
    """
    try:
        patterns = _forbidden_for(wave_letter)
        if not patterns or not isinstance(diff_text, str) or not diff_text:
            return ""

        changed: list[str] = []
        seen: set[str] = set()
        for match in _DIFF_GIT_HEADER.finditer(diff_text):
            path = match.group(2)
            if path and path not in seen:
                seen.add(path)
                changed.append(path)
        if not changed:
            for match in _DIFF_PLUSPLUS_HEADER.finditer(diff_text):
                path = match.group(1)
                if path and path not in seen:
                    seen.add(path)
                    changed.append(path)

        if len(changed) < _SMALL_DIFF_FLOOR:
            return ""

        offending = [p for p in changed if _matches_any(p, patterns)]
        if len(offending) >= _DRIFT_THRESHOLD:
            return _steer_message(wave_letter, offending)
        return ""
    except Exception:
        logger.warning("codex diff check failed (fail-open)", exc_info=True)
        return ""
```

**Step B — Write the test file.** Every assertion must be specific. No `or True`. No `assert isinstance(x, str)` as the sole check (too weak — you must assert emptiness or non-emptiness).

```python
"""Phase 5 rule-based Codex observer checks — unit tests."""
from __future__ import annotations

import pytest

from agent_team_v15.codex_observer_checks import (
    check_codex_diff,
    check_codex_plan,
)


def _make_diff(paths: list[str]) -> str:
    parts: list[str] = []
    for p in paths:
        parts.append(f"diff --git a/{p} b/{p}")
        parts.append(f"--- a/{p}")
        parts.append(f"+++ b/{p}")
        parts.append("@@ -0,0 +1,2 @@")
        parts.append("+placeholder line 1")
        parts.append("+placeholder line 2")
    return "\n".join(parts) + "\n"


def test_check_codex_diff_wave_b_detects_frontend():
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ])
    msg = check_codex_diff(diff, "B")
    assert msg != ""
    assert "Wave B" in msg
    assert "backend" in msg.lower()


def test_check_codex_diff_wave_b_clean():
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/src/routes/users.py",
        "apps/api/src/db/models.py",
    ])
    msg = check_codex_diff(diff, "B")
    assert msg == ""


def test_check_codex_diff_wave_d_detects_backend():
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/prisma/schema.prisma",
        "apps/api/src/routes/users.py",
    ])
    msg = check_codex_diff(diff, "D")
    assert msg != ""
    assert "Wave D" in msg
    assert "frontend" in msg.lower()


def test_check_codex_diff_empty_diff_no_steer():
    assert check_codex_diff("", "B") == ""
    assert check_codex_diff("   \n", "B") == ""


def test_check_codex_diff_small_diff_below_floor_no_steer():
    # Two offending files — below the 3-file small-diff floor, MUST NOT trigger.
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
    ])
    assert check_codex_diff(diff, "B") == ""


def test_check_codex_diff_single_incidental_touch_no_steer():
    # Three changed files total but only one is frontend — below drift threshold.
    diff = _make_diff([
        "apps/api/src/main.py",
        "apps/api/src/db/models.py",
        "apps/web/README.md",
    ])
    assert check_codex_diff(diff, "B") == ""


def test_check_codex_diff_non_target_wave_no_steer():
    # Wave A has no forbidden pattern map — always returns "".
    diff = _make_diff([
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ])
    assert check_codex_diff(diff, "A") == ""


def test_check_codex_plan_wave_b_frontend_plan():
    plan = [
        "Create apps/web/pages/index.tsx",
        "Add React component in apps/web/components/Header.tsx",
        "Wire up apps/api/src/main.py",
    ]
    msg = check_codex_plan(plan, "B")
    assert msg != ""
    assert "Wave B" in msg


def test_check_codex_plan_wave_b_clean_plan():
    plan = [
        "Create apps/api/src/main.py",
        "Add apps/api/prisma/schema.prisma",
        "Write apps/api/src/routes/users.py",
    ]
    assert check_codex_plan(plan, "B") == ""


def test_check_codex_plan_single_hit_below_threshold_no_steer():
    plan = [
        "Create apps/api/src/main.py",
        "Incidentally read apps/web/README.md for reference",
    ]
    assert check_codex_plan(plan, "B") == ""


def test_check_codex_plan_empty_input_no_steer():
    assert check_codex_plan([], "B") == ""
    assert check_codex_plan(["", "   "], "B") == ""


def test_check_codex_plan_non_target_wave_no_steer():
    plan = [
        "Create apps/web/pages/index.tsx",
        "Add apps/web/components/Header.tsx",
    ]
    assert check_codex_plan(plan, "T") == ""


def test_check_codex_diff_exception_returns_empty(monkeypatch):
    # Force an exception inside the diff scanner to prove fail-open.
    import agent_team_v15.codex_observer_checks as mod

    class _Boom:
        def finditer(self, _text):
            raise RuntimeError("injected failure")

    monkeypatch.setattr(mod, "_DIFF_GIT_HEADER", _Boom())
    monkeypatch.setattr(mod, "_DIFF_PLUSPLUS_HEADER", _Boom())
    assert check_codex_diff(_make_diff(["apps/web/a.tsx", "apps/web/b.tsx", "apps/web/c.tsx"]), "B") == ""


def test_check_codex_plan_exception_returns_empty(monkeypatch):
    import agent_team_v15.codex_observer_checks as mod

    def _boom(_path: str, _patterns):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(mod, "_matches_any", _boom)
    assert check_codex_plan(["apps/web/pages/index.tsx"] * 5, "B") == ""


def test_cross_validation_plan_and_diff_agree_on_wave_b():
    # Same offending file set — plan and diff must BOTH return non-empty for Wave B.
    paths = [
        "apps/web/pages/index.tsx",
        "apps/web/components/Header.tsx",
        "apps/web/styles/main.css",
    ]
    diff = _make_diff(paths)
    plan = [f"Create {p}" for p in paths]
    diff_msg = check_codex_diff(diff, "B")
    plan_msg = check_codex_plan(plan, "B")
    assert diff_msg != ""
    assert plan_msg != ""
    assert "Wave B" in diff_msg
    assert "Wave B" in plan_msg
```

**Step C — Run the tests.**

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_codex_observer_checks.py -v
```

All 14 tests must pass. Zero skips, zero xfails.

---

### Task 5.2 — Replace Phase 4 stub inside `_wait_for_turn_completion`

**File:** `src/agent_team_v15/codex_appserver.py`

**Step A — Locate.** Open `src/agent_team_v15/codex_appserver.py` and find the Phase 4 stub marker. Grep it first:

```bash
grep -n "Phase 5 will replace this stub" C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py
```

That grep must return exactly one line inside `_wait_for_turn_completion` (roughly lines 897–923 today after Phase 4 lands). If it returns zero hits, STOP — Phase 4 Task 4.3 has not been applied. Do NOT proceed with Task 5.2 until Phase 4 is complete. The stub marker is the insertion point — without it, there is no safe injection location. If it returns more than one hit, re-read Phase 4's Task 4.3 to understand which block to replace.

**Step B — Replace.** In `_wait_for_turn_completion`, the variables `client`, `thread_id`, `turn_id`, `watchdog` are already in scope. Import checks lazily inside the try block (see "hard rules" above — this keeps the fail-open net over the import itself). Replace the Phase 4 stub with:

```python
# Phase 5: real rule-based plan/diff observer checks for Codex waves.
# Fail-open — any exception (including ImportError) returns no steer.
try:
    from agent_team_v15.codex_observer_checks import (
        check_codex_diff,
        check_codex_plan,
    )

    steer_msg = ""
    if getattr(watchdog, "codex_latest_diff", ""):
        steer_msg = check_codex_diff(
            watchdog.codex_latest_diff,
            getattr(watchdog, "wave_letter", "") or "",
        )
    if not steer_msg and getattr(watchdog, "codex_last_plan", None):
        steer_msg = check_codex_plan(
            list(watchdog.codex_last_plan),
            getattr(watchdog, "wave_letter", "") or "",
        )

    observer_cfg = getattr(watchdog, "observer_config", None)
    if steer_msg and observer_cfg is not None and not getattr(observer_cfg, "log_only", True):
        await client.turn_steer(thread_id, turn_id, steer_msg)
        logger.info(
            "Observer steered Codex Wave %s: %s",
            getattr(watchdog, "wave_letter", "?"),
            steer_msg[:120],
        )
    elif steer_msg:
        logger.info(
            "Observer (log_only) would steer Codex Wave %s: %s",
            getattr(watchdog, "wave_letter", "?"),
            steer_msg[:120],
        )
except Exception:
    logger.warning("Codex observer check failed (fail-open)", exc_info=True)
```

Notes:
- `getattr(..., default)` guards against any stale `_OrphanWatchdog` instance that predates Phase 4 (defence in depth — Phase 4 guarantees these attrs exist, but `getattr` makes the block survive a rollback without ImportError).
- `log_only` defaults to `True` in the `elif` branch: if `observer_config` is missing we log but do not steer.
- Import is lazy inside try — if `codex_observer_checks` fails to import for any reason, the `except Exception` swallows it and the turn continues uninterrupted. This is the fail-open contract.

**Step C — `last_peek_monotonic` bookkeeping (sanity check).** Phase 4 owns the Claude-side peek loop. Re-read Phase 4's Task 4.2 and confirm `state.last_peek_monotonic = time.monotonic()` is written **every** time a peek fires (file-event path AND, once added, time-based path). If either path is missing the write, add it as part of Task 5.2 — otherwise `_should_fire_time_based_peek` will spam-fire on every poll.

**Step D — Time-based peek helper.** Add to `src/agent_team_v15/wave_executor.py` next to the other peek helpers (grep for `_detect_new_peek_triggers` to find the neighborhood):

```python
def _should_fire_time_based_peek(
    last_peek_monotonic: float,
    interval_seconds: float,
    peek_count: int,
    max_peeks: int,
) -> bool:
    """Time-based trigger gate for Claude wave observer peeks."""
    if peek_count >= max_peeks:
        return False
    if interval_seconds <= 0:
        return False
    return (time.monotonic() - last_peek_monotonic) >= interval_seconds
```

Add a test in `tests/test_v18_wave_executor_extended.py` (append; do not overwrite):

```python
def test_should_fire_time_based_peek_interval_elapsed():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 60.0, 0, 5) is True


def test_should_fire_time_based_peek_interval_not_elapsed():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 10.0, 60.0, 0, 5) is False


def test_should_fire_time_based_peek_budget_exhausted():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 60.0, 5, 5) is False


def test_should_fire_time_based_peek_zero_interval():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 0.0, 0, 5) is False
```

**Step E — Wire the time-based trigger into the Claude polling loop.** Inside `_invoke_wave_sdk_with_watchdog`'s `while True` (around line 2621), after Phase 4's file-event peek block, add an `elif` branch that fires `run_peek_call(...)` when `_should_fire_time_based_peek(state.last_peek_monotonic, observer_cfg.time_based_interval_seconds, len(state.peek_log), observer_cfg.max_peeks_per_wave)` returns True, selects the most-recently-modified file in the wave's trigger-file set that has not yet appeared in `state.peek_log`, records the result in `state.peek_log`, and sets `state.last_peek_monotonic = time.monotonic()`. Exact wording matches Phase 4's file-event branch — reuse the helper `run_peek_call` from `observer_peek.py`.

---

### Task 5.3 — Add `peek_summary` to `WaveResult` and populate it

**File:** `src/agent_team_v15/wave_executor.py`

**Step A — Add the field.** In the `WaveResult` dataclass (lines 68–127), after `scope_violations: list[str] = field(default_factory=list)` (line 127) and before the closing of the class body, insert:

```python
    # --- Phase 5 observer telemetry ---
    peek_summary: list[dict[str, Any]] = field(default_factory=list)
```

Do not remove or reorder any existing field. This is append-only.

**Step B — Populate at the caller.** Correction #7 wording says "just before final return in `_invoke_wave_sdk_with_watchdog`", but that function returns `tuple[float, _WaveWatchdogState]` — no `WaveResult` is in scope. Apply rule #5: use source truth. The correct population site is every caller that destructures `(cost, watchdog_state)` and owns a `wave_result`. Three sites exist in `wave_executor.py`:

1. Line ~3332 (`_execute_single_wave_sdk` timeout branch).
2. Line ~3800 (retry-path sibling).
3. Line ~3863 (primary Claude wave branch).

At each of these sites, immediately after the existing `wave_result.last_sdk_message_type = watchdog_state.last_message_type` assignment, add:

```python
if getattr(watchdog_state, "peek_log", None):
    wave_result.peek_summary = [
        {
            "file": getattr(r, "file_path", ""),
            "verdict": getattr(r, "verdict", ""),
            "confidence": float(getattr(r, "confidence", 0.0) or 0.0),
            "message": getattr(r, "message", ""),
            "source": getattr(r, "source", ""),
            "timestamp": getattr(r, "timestamp", ""),
        }
        for r in watchdog_state.peek_log
    ]
```

Use `getattr` defensively — `PeekResult` is the Phase 3 dataclass and the fields exist, but if an older item sneaks into `peek_log` the empty defaults keep the summary serialisable.

**Note on Phase 3/4 dependency:** If `watchdog_state.peek_log` raises `AttributeError` (because Phase 3/4 have not been applied to source), the `getattr(watchdog_state, "peek_log", None)` guard returns `None` silently and `peek_summary` will be an empty list. This guard is intentional as a runtime safety net, but it means `peek_summary` will always be empty if Phase 3/4 have not been implemented — run the prerequisite check at the top of this document before assuming empty `peek_summary` is correct behaviour.

**Step C — Verify.**

```bash
python -c "from agent_team_v15.wave_executor import WaveResult; assert 'peek_summary' in WaveResult.__dataclass_fields__; print('peek_summary field exists')"
```

Expected output: `peek_summary field exists`.

---

## Phase Gate: Verification Checklist

Run every command. Every check must pass before declaring Phase 5 done.

```bash
cd C:/Projects/agent-team-v18-codex

# 1. New tests pass.
python -m pytest tests/test_codex_observer_checks.py -v
# Expect: 14 passed, 0 failed, 0 skipped, 0 xfail.

# 2. Extended wave executor tests still pass (peek helper additions).
python -m pytest tests/test_v18_wave_executor_extended.py -v
# Expect: full suite green.

# 3. peek_summary field exists on WaveResult.
python -c "from agent_team_v15.wave_executor import WaveResult; assert 'peek_summary' in WaveResult.__dataclass_fields__; print('peek_summary OK')"

# 4. Fatal anti-pattern guard — MUST return empty.
grep -n "or True" tests/test_codex_observer_checks.py
# Expect: zero lines printed. If ANY line prints, the test file is broken. Fix and re-run.

# 5. Phase 4 stub is fully replaced — marker must be gone.
grep -n "Phase 5 will replace this stub" src/agent_team_v15/codex_appserver.py
# Expect: zero lines. A remaining hit means Task 5.2 didn't land.

# 6. Observer imports are lazy (inside the try block, not module top).
grep -n "from agent_team_v15.codex_observer_checks" src/agent_team_v15/codex_appserver.py
# Expect: the hit must sit inside _wait_for_turn_completion. If it's at the top of the file, move it inside the function.

# 7. No API imports leaked into the rule-based module.
grep -nE "(^import anthropic|from anthropic|httpx|asyncio)" src/agent_team_v15/codex_observer_checks.py
# Expect: zero lines.

# 8. Regex correctness — search not match.
grep -n "re\.match" src/agent_team_v15/codex_observer_checks.py
# Expect: zero lines.
```

If any of checks 1, 3, 4, 5, 7, 8 fails, the phase is NOT done. Checks 2 and 6 are soft (fail = fix; don't ship).

---

## Handoff State

On successful Phase 5 completion, Phase 6 may depend on:

- `src/agent_team_v15/codex_observer_checks.py` exists and exports `check_codex_plan(plan_lines, wave_letter) -> str` and `check_codex_diff(diff_text, wave_letter) -> str`. Both are fail-open (no uncaught exceptions). Both return `""` when there is no drift, a non-empty steer string when drift is detected.
- `_wait_for_turn_completion` in `codex_appserver.py` calls the real checks (not a stub) and, when `observer_config.log_only` is False, invokes `client.turn_steer(thread_id, turn_id, steer_msg)`.
- `_should_fire_time_based_peek(last_peek_monotonic, interval_seconds, peek_count, max_peeks) -> bool` is exported from `wave_executor.py`.
- The Claude polling loop fires a time-based peek when the file-event trigger has not fired within `observer_config.time_based_interval_seconds` and the per-wave peek budget is not exhausted. Every fire updates `state.last_peek_monotonic`.
- `WaveResult.peek_summary: list[dict[str, Any]]` exists, defaults to `[]`, and is populated by the callers of `_invoke_wave_sdk_with_watchdog` from `watchdog_state.peek_log`.
- No `or True` anti-patterns exist in the new test file.
- `codex_observer_checks.py` has no dependency on `anthropic`, `httpx`, or any network library.

Phase 6 will exercise these surfaces in a live smoke: expect `peek_summary` to carry at least one entry for Wave B or Wave D, and expect at least one `[Observer]` log line per observed wave.
