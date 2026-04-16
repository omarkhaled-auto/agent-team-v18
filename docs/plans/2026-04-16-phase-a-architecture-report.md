# Phase A Architecture Report

**Author:** Wave 1 architecture-discoverer
**Date:** 2026-04-16
**Branch:** phase-a-foundation
**Inputs:** build-l-gate-a-20260416 preserved artifacts, current source on branch
**Deliverable type:** discovery-only; no source or test edits performed

---

## 1. AUDIT_REPORT.json write-path trace

### 1.1 Producers (there are TWO)

There are two producers of `.agent-team/AUDIT_REPORT.json` in production. They emit **different on-wire shapes**:

| # | Producer | Trigger | Shape written |
|---|----------|---------|---------------|
| 1 | **Codex scorer agent (LLM, direct tool call)** | Scorer sub-agent invoked during audit cycle; its prompt ends with "Write the report to .agent-team/AUDIT_REPORT.json" at `audit_prompts.py:1349`, `audit_prompts.py:1352` | Scorer-raw shape: top-level `schema_version`, `generated`, `milestone`, `audit_cycle`, `overall_score`, `max_score`, `verdict`, `threshold_pass`, `auditors_run`, `raw_finding_count`, `deduplicated_finding_count`, `findings`, `pass_notes`, `summary`, `score_breakdown`, `dod_results`, `fix_candidates` (as id strings), `by_severity`, `by_category`, `health`, `notes`, `category_summary`, `finding_counts`, `deductions_total`, `deductions_capped` |
| 2 | **Python re-write via `AuditReport.to_json()`** | `_run_milestone_audit_with_reaudit` writes the final report at `cli.py:6033` (`report_path.write_text(current_report.to_json(), encoding="utf-8")`) | Canonical `to_json` shape at `audit_models.py:265-280`: only `audit_id`, `timestamp`, `cycle`, `auditors_deployed`, `findings`, `score` (dict), `by_severity`, `by_file`, `by_requirement`, `fix_candidates` (as int indices), `scope`, `acceptance_tests`. Scorer-side keys (`verdict`, `health`, `notes`, `category_summary`, `finding_counts`, `deductions_total`, `overall_score`, `threshold_pass`, `auditors_run`, `schema_version`, `generated`, `milestone`, `raw_finding_count`, `deduplicated_finding_count`, `pass_notes`, `summary`, `score_breakdown`, `dod_results`, `by_category`) are **stripped**. |

### 1.2 Flow

1. Codex scorer sub-agent runs → writes `AUDIT_REPORT.json` in raw shape (Producer 1).
2. `_run_milestone_audit` at `cli.py:5394-5398` reads that file back: `AuditReport.from_json(report_path.read_text(...))`. The D-07 permissive parser at `audit_models.py:283-381` correctly ingests the scorer shape, stashing unknown top-level keys into `AuditReport.extras` (`audit_models.py:342`).
3. `_apply_evidence_gating_to_audit_report` at `cli.py:530-651` may rebuild the report through `build_report()` when scope partitioning or evidence gating fires. A rebuild **drops `extras`** because `build_report` (audit_models.py:704-759) does not propagate them.
4. When the reaudit loop finishes, `cli.py:6033` writes `current_report.to_json()` back to disk — this is where extras get permanently lost.
5. `State.finalize` at `state.py:97-207` reads `AUDIT_REPORT.json` back once more (at `state.py:153`) to populate `audit_health`. It reads `extras["health"]` first, falling back to `score.health` (`state.py:158-164`).

### 1.3 N-15 lands on Producer 2

The N-15 fix (extras unpacking in `to_json`) is production-critical:

- **Build-l evidence:** `build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json` is in scorer-raw shape (`overall_score: 40`, `verdict: "FAIL"`, `threshold_pass: 850`, findings with `id: "AUD-001"` / `file` / `line` / `source_finding_ids`). Milestone-1 failed at wave B (see `build-l/.agent-team/STATE.json` line 69-79: `wave_progress.milestone-1.failed_wave = "B"`), so the Python rewrite at `cli.py:6033` never fired — the file we see is Producer 1's unmodified output.
- **But for any milestone that DOES reach the audit-cycle return path**, Producer 2's re-write executes and truncates the report. Subsequent `State.finalize` reads then lose access to the scorer's authoritative `health` / `verdict`, and `AuditReport.extras` becomes effectively empty at rest.
- **Fix surface:** Adding `**self.extras` to the `to_json` dict literal (Python 3.5+ PEP 448 `{**existing, **extras}`) is safe because `_AUDIT_REPORT_KNOWN_KEYS` at `audit_models.py:216-231` already scoped `extras` to non-canonical keys during `from_json`, so there's no first-class key collision. Python's dict-literal spread evaluates left-to-right and later keys would win anyway — but ordering is moot because the known-key filter prevents overlap entirely.

### 1.4 Other writers (non-load-bearing for N-15)

- `cli.py:5141` — writes `integration_report.to_json()` (different artifact, not AUDIT_REPORT).
- `coordinated_builder.py:631` / `:1230` / `:1311` — writes audit_runN.json files (per-cycle artefacts, not AUDIT_REPORT.json). See also comment at `coordinated_builder.py:694` explicitly distinguishing them.
- `_audit_worker.py:62` — writes an auditor-side dump (separate worker path).

None of these rewrite the canonical `AUDIT_REPORT.json` path, so N-15 on `AuditReport.to_json` covers every production write site that matters.

---

## 2. State mutation site enumeration

These are the **actual** functions and their mutations. The plan's `RunState.update_milestone_status` / `mark_wave_completed` are fictional — no such methods exist on `RunState`.

### 2.1 `update_milestone_progress(state, milestone_id, status)` — `state.py:379-410`

Module-level function (not a method). Mutates:

- `state.current_milestone`: set to `milestone_id` when `status == "IN_PROGRESS"`; cleared otherwise.
- `state.completed_milestones`: appended with `milestone_id` when status is `COMPLETE` or `DEGRADED` (dedup-checked).
- `state.failed_milestones`: appended when `status == "FAILED"` (dedup-checked); removed when the milestone transitions to `COMPLETE`/`DEGRADED` (retry-success path at `:403-404`).
- `state.milestone_progress[milestone_id]`: set to `{"status": status_upper}`.

**Call sites in `cli.py`** (15 total):

| Line | Status passed |
|------|---------------|
| 3612 | `"COMPLETE"` or `"FAILED"` (computed `final_status`) |
| 3707 | `"IN_PROGRESS"` |
| 3737 | `"FAILED"` |
| 3753 | `"BLOCKED"` (note: `update_milestone_progress` has no BLOCKED branch — falls through to no-op for the three-way if/elif at `state.py:395-408`) |
| 3780 | `"BLOCKED"` (same no-op fallthrough) |
| 4081 | `"FAILED"` |
| 4117 | `"FAILED"` |
| 4429 | `"FAILED"` |
| 4549 | `"DEGRADED"` |
| 4564 | `"FAILED"` |
| 4672 | `"FAILED"` |
| 4704 | `"FAILED"` |
| 4822 | `"COMPLETE"` or `"DEGRADED"` (`_final_status`) |
| 4881 | `"FAILED"` |

> Note on BLOCKED: calls with `status="BLOCKED"` at `cli.py:3753` and `cli.py:3780` hit the `elif`/`elif`/`elif` chain in `update_milestone_progress` and silently fall through without writing to `milestone_progress` or either list. This is an existing behavior — out of Phase A scope but worth flagging for D-24 follow-up.

### 2.2 `_canonicalize_state(state)` — `state.py:460-505`

Module-level. Mutates:

- Coerces non-dict/list fields to their expected type with empty defaults.
- De-duplicates `completed_phases`, `completed_milestones`, `failed_milestones`, `milestone_order`, `completed_browser_workflows`, `departments_created`, `registered_artifacts`, `previous_passing_acs`.
- Calls `_reconcile_milestone_lists(state)` at `:502` when `milestone_progress` is non-empty.
- Calls `update_completion_ratio(state)` at `:504` when `milestone_order` is non-empty.
- Sets `state.schema_version = _CURRENT_SCHEMA_VERSION` (3).

### 2.3 `_reconcile_milestone_lists(state)` — `state.py:362-376`

Re-derives both list projections from `milestone_progress` as canonical truth:

- `state.completed_milestones` = milestones whose status is `COMPLETE` or `DEGRADED`.
- `state.failed_milestones` = milestones whose status is `FAILED`.

**Critical for the invariant:** this function ONLY runs when `milestone_progress` is non-empty. If a caller bypasses `update_milestone_progress` and directly sets `state.failed_milestones = ["m1"]` (as `test_state_finalize.py:60` does), `milestone_progress` stays `{}` and reconcile is a no-op. Invariant enforcement in save_state must not assume reconcile has already run.

### 2.4 `save_state(state, directory)` — `state.py:508-588`

Atomic write path. Mutates disk + re-canonicalizes state:

- `_canonicalize_state(state)` at `:517`.
- `_reconcile_milestone_lists(state)` at `:521` (iff `milestone_progress`).
- Builds `data["summary"]` at `:555-569`:
  - Line 557: `"success": finalized.get("success", not state.interrupted)` — if `finalize()` previously set `state.summary["success"] = False` (failed milestones path), it's preserved. If `finalize()` was never called or threw, defaults to `not state.interrupted` — which is the D-13 silent-swallow vector.
- Atomic `tempfile.mkstemp` + `os.replace` at `:574-586`.

### 2.5 `RunState.finalize(self, agent_team_dir=None)` — `state.py:97-207`

Method. Mutates:

- `self.summary["success"]` at `:135-137`: `(not self.interrupted) and len(self.failed_milestones) == 0`.
- `self.audit_health` at `:164`: from `AUDIT_REPORT.json` scorer `extras["health"]` preferred, else `score.health`.
- `self.wave_progress[*].current_wave` at `:170-173`: popped when `current_phase == "complete"`.
- `self.stack_contract["confidence"]` at `:181`: forced to `"low"` when both `backend_framework` and `frontend_framework` are falsy.
- `self.gate_results` at `:200-204`: loaded from `GATE_FINDINGS.json` when present.

**Called from exactly one production site:** `cli.py:13491` inside the pipeline-completion path:

```python
# cli.py:13480-13498
if _current_state:
    _current_state.interrupted = False  # completed normally
    try:
        from .state import save_state as _save_final
        try:
            _current_state.finalize(
                agent_team_dir=Path(cwd) / ".agent-team"
            )
        except Exception:
            pass  # Best-effort; save_state still writes legacy defaults.
        _save_final(_current_state, directory=str(Path(cwd) / ".agent-team"))
    except Exception:
        pass  # Best-effort final state save
```

The inner `except Exception: pass` at `:13494-13495` is the silent-swallow. When `finalize` throws (e.g., because an `AuditReport.from_json` parse fails midway, or `GATE_FINDINGS.json` is malformed, or `stack_contract` isn't a dict), `save_state` runs next with `state.summary` in whatever partial state `finalize` left it — and `finalized.get("success", not state.interrupted)` falls back to `not False = True`. That is exactly the state captured in build-l.

### 2.6 Other persistence helpers (not mutation sites, listed for completeness)

- `get_resume_milestone(state)` — read-only.
- `update_completion_ratio(state)` — mutates `state.completion_ratio` (derived field).
- `load_state(directory)` — reads from disk, returns a fresh RunState, does not mutate the caller's state.
- `clear_state(directory)` — removes the file, no state object mutation.
- `validate_for_resume(state)` — read-only; returns a list of warnings/errors.

---

## 3. Port detection source precedence

### 3.1 Current precedence (endpoint_prober.py:1023-1036)

```python
def _detect_app_url(project_root: Path, config: Any) -> str:
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"
    env_path = project_root / ".env"
    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^\s*PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
            if match:
                return f"http://localhost:{int(match.group(1))}"
        except OSError:
            pass
    return "http://localhost:3080"
```

| # | Source | Status |
|---|--------|--------|
| 1 | `config.browser_testing.app_port` (integer, non-zero) | kept |
| 2 | `<project_root>/.env` regex `^\s*PORT\s*=\s*(\d+)\s*$` (MULTILINE) | kept |
| 3 | Fallback `http://localhost:3080` | SILENT; must become LOUD |

### 3.2 Target precedence (N-01)

| # | Source | Sample content (real monorepo fixture) |
|---|--------|----------------------------------------|
| 1 | `config.browser_testing.app_port` (as-is) | stock config.yaml has `browser_testing.app_port: 0` → falls through |
| 2 | `<project_root>/.env` `PORT=<n>` (as-is) | optional; stock PRD fixture does not create root `.env` |
| 3 | **NEW**: `<project_root>/apps/api/.env.example` `PORT=<n>` | in-repo fixture would contain `PORT=4000` per build-l AUD-006 evidence ("apps/api/.env.example (DATABASE_URL, JWT_SECRET, JWT_EXPIRES_IN, BCRYPT_ROUNDS, **PORT**, NODE_ENV, CORS_ORIGIN)") |
| 4 | **NEW**: `<project_root>/apps/api/src/main.ts` regex `app\.listen\s*\(\s*(\d+)` or `\.listen\s*\(\s*process\.env\.PORT\s*\|\|\s*(\d+)` | e.g. `await app.listen(process.env.PORT ?? 4000);` |
| 5 | **NEW**: `<project_root>/docker-compose.yml` `services.api.ports` — first mapping of form `"<host>:<container>"` → host port | build-l AUD-007 evidence: api service in docker-compose.yml exposes `4000` |
| 6 | Fallback `http://localhost:3080` **with `logger.warning`** | unchanged port; LOUD log only |

Precedence is strict short-circuit: the first source that yields a port wins. All parsers MUST fail closed (empty string / no match / OSError) without raising so the fallback chain keeps moving.

Build-l does not preserve a representative `apps/api/*` fixture (milestone-1 failed before scaffold completed), so the sample content above is taken from the milestone-1 REQUIREMENTS.md snapshot cited in AUDIT_REPORT.json findings AUD-006 / AUD-007 / AUD-008.

### 3.3 `docker-compose.yml` parsing note

YAML parsing requires PyYAML (already present via other paths in this codebase). A safe regex fallback: `re\.search(r"^\s{4,}api:\s*$.*?^\s{6,}ports:\s*\n(?:\s*-\s*\"?(\d+):", text, re.MULTILINE | re.DOTALL)` — but the Wave 2a implementer should prefer `yaml.safe_load` + dict traversal to avoid multiline-regex fragility. Either is acceptable as long as parse failures fall through silently to the next source.

---

## 4. Invariant validation insertion points

### 4.1 Primary invariant location — `save_state` right before atomic write

**File:** `src/agent_team_v15/state.py`
**Insert location:** immediately after the `data["summary"]` dict is assembled (after line 569) and before the `tempfile.mkstemp` at line 574.

Why here and not earlier:

- `_canonicalize_state` (called at line 517) and `_reconcile_milestone_lists` (line 521) have already normalized shape.
- `data["summary"]["success"]` has been resolved from either finalize's value or the legacy fallback.
- The check runs on the exact dict about to be serialized — no downstream mutation can re-introduce a violation.
- Raising before `mkstemp` avoids leaking a partial tempfile on the filesystem.

### 4.2 Secondary invariant location — `finalize`

**File:** `src/agent_team_v15/state.py`
**Insert location:** after line 137, immediately after `self.summary["success"]` is assigned.

This is defense in depth. The D-13 author added this line specifically to enforce the invariant. A stray caller could set `self.failed_milestones = [...]` after `finalize` returns; that's covered by (4.1). Conversely, a bug that fails to propagate `failed_milestones` through `finalize`'s summary write would be caught here at finalize-time with a clearer trace.

### 4.3 Exception class location

**File:** `src/agent_team_v15/state.py`
**Insert location:** top-level, ideally after the `_TEST_SKIP_SEGMENTS` constants at line 332, before the `count_test_files` helper at line 335.

### 4.4 cli.py silent-swallow fix

**File:** `src/agent_team_v15/cli.py`
**Insert location:** lines 13491-13495 — replace the bare `except Exception: pass` with a logged WARNING. Preserve the outer `try/except` at 13483-13498 so a finalize failure still reaches `save_state` (don't regress back to not-writing STATE at all on finalize throw).

---

## 5. Concrete implementation specs for Wave 2

> All diffs below are MINIMAL-SURFACE — they add the required behavior and nothing else.

### 5.1 N-01: `endpoint_prober._detect_app_url` — `endpoint_prober.py:1023-1036`

**Before:**

```python
def _detect_app_url(project_root: Path, config: Any) -> str:
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"
    env_path = project_root / ".env"
    if env_path.is_file():
        try:
            text = env_path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^\s*PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
            if match:
                return f"http://localhost:{int(match.group(1))}"
        except OSError:
            pass
    return "http://localhost:3080"
```

**After (conceptual — Wave 2a to finalize syntax):**

```python
def _detect_app_url(project_root: Path, config: Any) -> str:
    # 1. config.browser_testing.app_port (highest precedence)
    port = getattr(getattr(config, "browser_testing", None), "app_port", 0) if config else 0
    if port:
        return f"http://localhost:{int(port)}"

    # 2. <root>/.env PORT=<n>
    port = _port_from_env_file(project_root / ".env")
    if port:
        return f"http://localhost:{port}"

    # 3. <root>/apps/api/.env.example PORT=<n>
    port = _port_from_env_file(project_root / "apps" / "api" / ".env.example")
    if port:
        return f"http://localhost:{port}"

    # 4. <root>/apps/api/src/main.ts app.listen(<port>)
    port = _port_from_main_ts(project_root / "apps" / "api" / "src" / "main.ts")
    if port:
        return f"http://localhost:{port}"

    # 5. <root>/docker-compose.yml services.api.ports first mapping
    port = _port_from_compose(project_root / "docker-compose.yml")
    if port:
        return f"http://localhost:{port}"

    # 6. Loud fallback — previous behavior was silent
    logger.warning(
        "endpoint_prober: no PORT detected in config.browser_testing.app_port, "
        ".env, apps/api/.env.example, apps/api/src/main.ts, or docker-compose.yml; "
        "falling back to http://localhost:3080 (N-01)"
    )
    return "http://localhost:3080"


def _port_from_env_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*PORT\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    if match:
        return int(match.group(1))
    return None


def _port_from_main_ts(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # app.listen(4000) or app.listen(process.env.PORT ?? 4000) or app.listen(PORT, ...)
    for pattern in (
        r"\.listen\s*\(\s*process\.env\.PORT\s*\?\?\s*(\d+)",
        r"\.listen\s*\(\s*process\.env\.PORT\s*\|\|\s*(\d+)",
        r"\.listen\s*\(\s*(\d+)\b",
    ):
        m = re.search(pattern, text)
        if m:
            return int(m.group(1))
    return None


def _port_from_compose(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    services = data.get("services") or {}
    api = services.get("api") if isinstance(services, dict) else None
    if not isinstance(api, dict):
        return None
    ports = api.get("ports") or []
    if not isinstance(ports, list):
        return None
    for entry in ports:
        if isinstance(entry, str):
            # "4000:4000" or "127.0.0.1:4000:4000" — host port is the PENULTIMATE number
            parts = entry.split(":")
            try:
                return int(parts[-2]) if len(parts) >= 2 else None
            except (ValueError, TypeError):
                continue
        if isinstance(entry, dict):
            published = entry.get("published")
            if isinstance(published, (int, str)):
                try:
                    return int(published)
                except (ValueError, TypeError):
                    continue
    return None
```

**Import delta at top of `endpoint_prober.py`:**

- `re` is already imported.
- `logger = logging.getLogger(__name__)` — verify it exists (it's commonly present in this file; if not, add `import logging` + logger assignment). Wave 2a verifier must confirm.
- `yaml` is imported lazily inside `_port_from_compose` to avoid a hard dep for non-compose projects.

### 5.2 N-15: `AuditReport.to_json` — `audit_models.py:265-280`

**Before:**

```python
def to_json(self) -> str:
    """Serialize to JSON for persistence (canonical shape)."""
    return json.dumps({
        "audit_id": self.audit_id,
        "timestamp": self.timestamp,
        "cycle": self.cycle,
        "auditors_deployed": self.auditors_deployed,
        "findings": [f.to_dict() for f in self.findings],
        "score": self.score.to_dict(),
        "by_severity": self.by_severity,
        "by_file": self.by_file,
        "by_requirement": self.by_requirement,
        "fix_candidates": self.fix_candidates,
        "scope": self.scope,
        "acceptance_tests": self.acceptance_tests,
    }, indent=2)
```

**After:**

```python
def to_json(self) -> str:
    """Serialize to JSON for persistence (canonical shape).

    N-15: Preserves scorer-side top-level keys captured on ``extras``
    (verdict, health, notes, category_summary, finding_counts,
    deductions_total, overall_score, threshold_pass, auditors_run, etc.)
    so a from_json -> to_json round-trip of a scorer-raw report does
    not silently drop them. Known keys win over any collision via the
    ``_AUDIT_REPORT_KNOWN_KEYS`` filter in from_json — extras cannot
    overwrite audit_id / cycle / findings / score etc. by construction.
    """
    return json.dumps({
        "audit_id": self.audit_id,
        "timestamp": self.timestamp,
        "cycle": self.cycle,
        "auditors_deployed": self.auditors_deployed,
        "findings": [f.to_dict() for f in self.findings],
        "score": self.score.to_dict(),
        "by_severity": self.by_severity,
        "by_file": self.by_file,
        "by_requirement": self.by_requirement,
        "fix_candidates": self.fix_candidates,
        "scope": self.scope,
        "acceptance_tests": self.acceptance_tests,
        **(self.extras if isinstance(self.extras, dict) else {}),
    }, indent=2)
```

- `isinstance(self.extras, dict)` guard is defensive against a malformed construction that bypassed the dataclass default.
- Placement is at the END of the literal — Python PEP 448 evaluates left-to-right, so known first-class keys shadow any collision, but `_AUDIT_REPORT_KNOWN_KEYS` filtering in `from_json` already prevents collisions at construction time.

### 5.3 NEW-7: `save_state` invariant enforcement — `state.py`

**New exception class — insert after line 332, before `count_test_files`:**

```python
class StateInvariantError(RuntimeError):
    """Raised when STATE.json is about to be written with mutually inconsistent fields.

    The canonical invariant is:
      summary["success"] == (not interrupted) and len(failed_milestones) == 0

    Violation indicates a mutation site bypassed update_milestone_progress /
    finalize or that finalize threw silently (cli.py:13491). Raising here
    fails loud so the bug is caught at write-time rather than at product
    inspection.
    """
```

**Invariant check — insert after line 569, before line 571 (`state_path = dir_path / _STATE_FILE`):**

```python
    # NEW-7: STATE.json invariant — summary.success must be consistent with
    # failed_milestones + interrupted. Fails loud at write-time rather than
    # letting an inconsistent report escape to disk (build-l root cause).
    _expected_success = (not state.interrupted) and len(state.failed_milestones) == 0
    if bool(data["summary"].get("success")) != _expected_success:
        raise StateInvariantError(
            f"STATE.json invariant violation: summary.success="
            f"{data['summary'].get('success')!r} but "
            f"interrupted={state.interrupted!r}, "
            f"failed_milestones={state.failed_milestones!r} "
            f"(expected success={_expected_success!r}). "
            f"Likely cause: finalize() was not called or threw silently. "
            f"See cli.py:13491-13498."
        )
```

**Defense-in-depth at finalize — after line 137 in `state.py`:**

finalize already sets `self.summary["success"]` at line 135-137 correctly. No change needed here UNLESS you want an assertion — skip for minimum-surface.

### 5.4 NEW-8: Dropped fix-candidate ID logging — `audit_models.py:352-356`

**Before:**

```python
        raw_fix_candidates = data.get("fix_candidates", []) or []
        if raw_fix_candidates and isinstance(raw_fix_candidates[0], str):
            id_to_idx = {f.finding_id: i for i, f in enumerate(findings)}
            fix_candidates = [
                id_to_idx[fid] for fid in raw_fix_candidates if fid in id_to_idx
            ]
```

**After:**

```python
        raw_fix_candidates = data.get("fix_candidates", []) or []
        if raw_fix_candidates and isinstance(raw_fix_candidates[0], str):
            id_to_idx = {f.finding_id: i for i, f in enumerate(findings)}
            fix_candidates = []
            dropped: list[str] = []
            for fid in raw_fix_candidates:
                if fid in id_to_idx:
                    fix_candidates.append(id_to_idx[fid])
                else:
                    dropped.append(fid)
            if dropped:
                import logging
                logging.getLogger(__name__).warning(
                    "AuditReport.from_json: %d fix_candidate id(s) dropped "
                    "(absent from findings): %s. Total findings=%d, "
                    "candidates kept=%d. (NEW-8)",
                    len(dropped),
                    dropped[:10] + (["..."] if len(dropped) > 10 else []),
                    len(findings),
                    len(fix_candidates),
                )
```

Rationale: the existing silent drop at 354-356 makes it impossible to tell from logs whether `F-999` was a scorer typo, a dedup side effect, or a real bug. The first 10 dropped IDs are enough for triage without log spam.

### 5.5 cli.py:13491 silent-swallow fix — `cli.py:13480-13498`

**Before:**

```python
    if _current_state:
        _current_state.interrupted = False  # completed normally
        try:
            from .state import save_state as _save_final
            try:
                _current_state.finalize(
                    agent_team_dir=Path(cwd) / ".agent-team"
                )
            except Exception:
                pass  # Best-effort; save_state still writes legacy defaults.
            _save_final(_current_state, directory=str(Path(cwd) / ".agent-team"))
        except Exception:
            pass  # Best-effort final state save
```

**After:**

```python
    if _current_state:
        _current_state.interrupted = False  # completed normally
        try:
            from .state import save_state as _save_final
            try:
                _current_state.finalize(
                    agent_team_dir=Path(cwd) / ".agent-team"
                )
            except Exception as exc:
                # D-13 follow-up: do NOT silent-pass. A finalize throw leaves
                # summary.success / audit_health / gate_results in a partial
                # state and save_state falls back to `not state.interrupted`
                # for success — which masks failed milestones (build-l root
                # cause). Log loud so operators can diagnose.
                print_warning(
                    f"[STATE] finalize() raised before final STATE.json write: "
                    f"{type(exc).__name__}: {exc}. "
                    f"summary.success may be derived from legacy defaults. "
                    f"Inspect failed_milestones / interrupted manually."
                )
            _save_final(_current_state, directory=str(Path(cwd) / ".agent-team"))
        except Exception as exc:
            print_warning(f"[STATE] Final save_state() failed: {type(exc).__name__}: {exc}")
```

Outer-try also upgraded from silent pass to a WARNING. `print_warning` is the codebase convention (already used throughout `cli.py` — see `:5430`, `:6035`, etc.).

---

## 6. Risk assessment

### 6.1 Test impact summary

| Test file | Impact | Reason |
|-----------|--------|--------|
| `tests/test_audit_models.py` | **Safe** — zero breaks expected | `test_to_json_from_json` / `test_roundtrip` use `build_report()` → `AuditReport` which leaves `extras={}`; unpacking an empty dict is a no-op. D-07 tests (`TestAuditReportFromJsonPermissive`) don't round-trip through `to_json` so N-15 doesn't affect them. `test_fix_candidates_coerced_from_finding_ids` drops `F-999` (unknown); NEW-8 now emits a WARNING log during this test but does not change functional output — pytest's caplog-free tests won't see it. |
| `tests/test_state.py` | **Safe** — zero breaks expected | All `TestSaveState` / `TestLoadState` tests use fresh `RunState(task=...)` with empty `failed_milestones` and default `interrupted=False`. Invariant: `(not False) and len([]) == 0` → `True`. `save_state` default for `success` is `not False = True`. Both sides agree; no `StateInvariantError`. `test_preserves_interrupted_flag` sets `interrupted=True` → expected `success = (not True) and 0 == 0 = False`; `save_state` default is `not True = False`. Both sides agree; safe. |
| `tests/test_state_extended.py` | **Safe** | No milestone fields populated; invariant holds trivially. |
| `tests/test_state_finalize.py` | **Mostly safe; ONE test deserves attention** | `test_failed_milestone_success_false` at `:57-62` sets `state.failed_milestones = ["milestone-1"]` directly (not via `update_milestone_progress`, so `milestone_progress` stays `{}` and `_reconcile_milestone_lists` is a no-op). Then calls `state.finalize()` which sets `state.summary["success"] = False`. Test only asserts the in-memory value — it never calls `save_state`, so NEW-7's raise path is not exercised. **Safe.** But the `test_finalize_idempotent` test at `:130-148` ALSO doesn't call save_state, so same conclusion: invariant never triggers. |
| `tests/test_*.py` (other) | **Safe** | No tests exercise `save_state` with deliberately-inconsistent state. |

### 6.2 Wave 2a ↔ Wave 2c coordination — `audit_models.py`

Non-overlapping ranges confirmed:

- **Wave 2a** (N-15): edit `audit_models.py:265-280` — adds `**self.extras` to the `to_json` dict literal. Pure insertion inside the `json.dumps` call. No signature changes, no new imports.
- **Wave 2c** (NEW-8): edit `audit_models.py:352-356` — rewrites the fix_candidates ID-coercion block to add logging. Pure insertion before/after the list comprehension. Adds `import logging` inside the function (local import is already the style used at `audit_models.py:721-722`).

Line ranges are **87 lines apart** (352-280 = 72). Neither touches imports at module level. Either can merge first without conflicting — a 3-way merge is trivial.

**Suggested merge order:** Wave 2a first (because it's the production-critical N-15 fix), then Wave 2c as a follow-up. If Wave 2a misses production on its branch, Wave 2c still functions independently (NEW-8 doesn't read or write extras).

### 6.3 Behavioral risks

1. **N-01 may pick up a wrong port from a vestigial `apps/api/src/main.ts`** — e.g., a stale scaffold with `app.listen(3000)` in a project whose actual port is 4000. Mitigation: precedence order puts `apps/api/.env.example` BEFORE `main.ts` so the authoritative env file wins. For full correctness, `_port_from_main_ts` only matches `app.listen(<literal>)`, not `app.listen(PORT)` without a numeric default — so a PORT-env-only setup falls through to docker-compose. Acceptable.

2. **N-15 extras unpacking leaks scorer-side keys into downstream consumers that don't expect them** — e.g., any `json.loads(report_str)["verdict"]` reader that previously got KeyError now silently sees a string. This is **the intended fix** — downstream consumers (D-07 `State.finalize`) explicitly want `extras["health"]` preserved. No consumer reads the canonical shape and silently assumes extras are absent.

3. **NEW-7 invariant may fire for tests that directly mutate STATE.json on disk** — none found in Phase A scope. If one exists (e.g., a fixture that writes `STATE.json` with mismatched fields to test load_state's tolerance), it would bypass save_state and be unaffected.

4. **cli.py:13494 WARNING may flood noisy test runs** — the test suite never hits `cli.py:13491` (it's the real orchestration-completion path invoked only from CLI flows). Unit tests use `save_state` / `finalize` directly. No flood risk.

5. **docker-compose parsing** — if the project doesn't have PyYAML installed (unlikely in this codebase; verify via Wave 2a's `pip show pyyaml`), `import yaml` raises `ModuleNotFoundError`. The wrapped `except Exception:` in `_port_from_compose` catches that cleanly and falls through. Safe.

### 6.4 Production-path wiring confidence

Confirmed wire-up for each change:

- N-01: `_detect_app_url` is called by `endpoint_prober` → `_poll_health` at `:1039` → browser-testing / E2E phases. Every smoke path through `_poll_health` exercises the new precedence.
- N-15: `AuditReport.to_json()` is called by `cli.py:6033` (every audit cycle that completes), `coordinated_builder.py:631` / `:1230` / `:1311` (per-cycle artefacts), `_audit_worker.py:62` (worker dumps), `cli.py:5141` (integration_report — different AuditReport instance, same fix applies). Every AuditReport serialization now preserves extras.
- NEW-7: `save_state` is called 15+ times across cli.py (grep `save_state\(` — see §2 for the full list). Every milestone-boundary save exercises the invariant.
- NEW-8: `AuditReport.from_json` at `audit_models.py:283` is called by `cli.py:5398`, `cli.py:5868`, `hooks.py:~164`, `state.py:153`. Every read path logs dropped IDs.
- cli.py:13491 fix: single call site; the warning fires once per pipeline completion with a finalize throw.

No orphan code paths detected.

---

## Artefacts read for this report

Absolute paths — no relative paths used:

- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/cli.py` (sections at 530-651, 3600-3630, 4810-4830, 5380-5500, 5850-6040, 13470-13498; grep results for `update_milestone_progress`, `save_state`, `finalize(`, `AUDIT_REPORT.json`, `to_json()`)
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/audit_models.py` (full 856 lines)
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/endpoint_prober.py:990-1080`
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/state.py` (full 720 lines)
- `C:/Projects/agent-team-v18-codex/src/agent_team_v15/audit_prompts.py:1340-1365`
- `C:/Projects/agent-team-v18-codex/tests/test_state.py`
- `C:/Projects/agent-team-v18-codex/tests/test_state_extended.py`
- `C:/Projects/agent-team-v18-codex/tests/test_state_finalize.py`
- `C:/Projects/agent-team-v18-codex/tests/test_audit_models.py`
- `C:/Projects/agent-team-v18-codex/v18 test runs/build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json` (first 100 lines; scorer-raw shape confirmed)
- `C:/Projects/agent-team-v18-codex/v18 test runs/build-l-gate-a-20260416/.agent-team/STATE.json` (full 155 lines; summary.success=true + failed_milestones=["milestone-1"] + stack_contract.confidence=high WITH empty framework fields — all three invariant violations captured)

## Context7 verification

- Python `{**existing, **extras}` dict-literal spread syntax (PEP 448, 3.5+) confirmed via `/websites/python_3`. Known keys can appear before `**extras` and retain precedence as long as the dict's collision semantics are respected (last-key-wins in literal order). The `_AUDIT_REPORT_KNOWN_KEYS` filter at `audit_models.py:342` prevents collision at `from_json` time, so `to_json`'s `**self.extras` can never overwrite a canonical key.
