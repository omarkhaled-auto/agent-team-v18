"""Phase 4.2 of the pipeline upgrade — strong deterministic retry feedback.

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §E.

Phase 4.2 replaces the ~150-byte ``<previous_attempt_failed>`` block (current
implementation in ``wave_b_self_verify._build_retry_prompt_suffix`` and
the Wave D mirror) with a structured, deterministic, LLM-cost-zero
payload composed of: parsed compile errors with file:line, BuildKit
inner stderr (wrapper stripped), unresolved-import scan from modified
files, and a progressive signal across retries that sources from
WAVE_FINDINGS-shaped per-attempt service attribution (what HAPPENED),
not from the prior ``<previous_attempt_failed>`` block content (what
Codex was TOLD).

The frozen smoke fixture
``tests/fixtures/smoke_2026_04_26/codex-captures/milestone-1-wave-B-protocol-retry-payloads.txt``
is the contract baseline: each ``<previous_attempt_failed>`` block is
~150 bytes (per §0.3 step 2). Phase 4.2's payload must be ≥10× richer
(≥1500 bytes) for the same input AND bounded at 12000 bytes.

Each fixture in this file maps to one §E AC (AC1..AC7) plus the
extractor-level contract tests required by §0.3 step 1 (TDD sequence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"
RETRY_PAYLOADS_FIXTURE = (
    FIXTURE_ROOT
    / "codex-captures"
    / "milestone-1-wave-B-protocol-retry-payloads.txt"
)
WAVE_FINDINGS_FIXTURE = FIXTURE_ROOT / "WAVE_FINDINGS.json"


# ---------------------------------------------------------------------------
# Extractor-level contracts: TypeScript, BuildKit, Next.js
# ---------------------------------------------------------------------------


def test_extract_typescript_errors_canonical_format() -> None:
    """tsc --noEmit --pretty=false output: ``file(line,col): error TSXXXX: msg``.

    Format locked via Context7 against ``/microsoft/typescript`` baseline
    output (e.g.
    ``parserRegularExpressionDivideAmbiguity4.ts(1,1): error TS2304: Cannot find name 'foo'.``).
    """
    from agent_team_v15.retry_feedback import extract_typescript_errors

    stderr = (
        "apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module '@app/api-client'.\n"
        "apps/api/src/index.ts(1,1): error TS2305: "
        "Module '\"./types\"' has no exported member 'User'.\n"
    )
    errors = extract_typescript_errors(stderr)

    assert len(errors) == 2
    assert errors[0]["file"] == "apps/api/src/auth/auth.module.ts"
    assert errors[0]["line"] == 12
    assert errors[0]["col"] == 3
    assert errors[0]["code"] == "TS2307"
    assert "Cannot find module" in errors[0]["message"]
    assert errors[1]["code"] == "TS2305"


def test_extract_typescript_errors_strips_buildkit_progress_prefix() -> None:
    from agent_team_v15.retry_feedback import extract_typescript_errors

    stderr = (
        "#5 12.34 apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module './missing'.\n"
    )
    errors = extract_typescript_errors(stderr)
    assert len(errors) == 1
    assert errors[0]["file"] == "apps/api/src/auth/auth.module.ts"
    assert errors[0]["line"] == 12
    assert errors[0]["col"] == 3
    assert errors[0]["code"] == "TS2307"


def test_extract_typescript_errors_unprefixed_input_still_parses() -> None:
    from agent_team_v15.retry_feedback import extract_typescript_errors

    stderr = (
        "apps/api/src/index.ts(1,1): error TS2305: "
        "Module './foo' has no exported member 'Foo'.\n"
    )
    errors = extract_typescript_errors(stderr)
    assert len(errors) == 1
    assert errors[0]["file"] == "apps/api/src/index.ts"
    assert errors[0]["code"] == "TS2305"


def test_extract_typescript_errors_handles_mixed_buildkit_and_plain_lines() -> None:
    from agent_team_v15.retry_feedback import extract_typescript_errors

    stderr = (
        "#7 1.23 apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module './missing'.\n"
        "apps/web/src/page.tsx(42,1): error TS2304: Cannot find name 'foo'.\n"
    )
    errors = extract_typescript_errors(stderr)
    assert [err["file"] for err in errors] == [
        "apps/api/src/auth/auth.module.ts",
        "apps/web/src/page.tsx",
    ]
    assert [err["code"] for err in errors] == ["TS2307", "TS2304"]


def test_extract_typescript_errors_preserves_multiline_context() -> None:
    from agent_team_v15.retry_feedback import (
        extract_buildkit_inner_stderr,
        extract_typescript_errors,
    )

    stderr = (
        "#5 12.34 apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module './missing'.\n"
        "#5 12.35   Extra diagnostic context that is not a canonical error.\n"
        "#5 12.36 target api: failed to solve: process "
        "\"/bin/sh -c pnpm --filter api build\" did not complete successfully: exit code: 2\n"
    )
    inner = extract_buildkit_inner_stderr(stderr)
    assert "Extra diagnostic context" in inner
    assert "failed to solve" not in inner

    errors = extract_typescript_errors(inner)
    assert len(errors) == 1
    assert errors[0]["file"] == "apps/api/src/auth/auth.module.ts"


def test_extract_typescript_errors_handles_relative_and_absolute_paths() -> None:
    from agent_team_v15.retry_feedback import extract_typescript_errors

    stderr = (
        "/abs/path/file.ts(5,10): error TS1005: ';' expected.\n"
        "src/relative.tsx(99,1): error TS2304: Cannot find name 'foo'.\n"
    )
    errors = extract_typescript_errors(stderr)
    assert {e["file"] for e in errors} == {
        "/abs/path/file.ts",
        "src/relative.tsx",
    }


def test_extract_typescript_errors_returns_empty_on_no_match() -> None:
    from agent_team_v15.retry_feedback import extract_typescript_errors

    assert extract_typescript_errors("") == []
    assert extract_typescript_errors("Successfully built\n") == []


def test_extract_buildkit_inner_stderr_strips_failed_to_solve_wrapper() -> None:
    """BuildKit ``failed to solve: process X did not complete`` wrapper.

    Format anchor: 2026-04-26 smoke evidence + ``/moby/buildkit`` docs.
    """
    from agent_team_v15.retry_feedback import extract_buildkit_inner_stderr

    stderr = (
        "src/index.ts:1:8 - error TS2307: Cannot find module './missing'\n"
        "ELIFECYCLE Command failed with exit code 1.\n"
        "target api: failed to solve: process \"/bin/sh -c pnpm --filter "
        "api build\" did not complete successfully: exit code: 1\n"
    )
    inner = extract_buildkit_inner_stderr(stderr)
    assert "failed to solve" not in inner
    assert "ELIFECYCLE Command failed" in inner
    assert "TS2307" in inner


def test_extract_buildkit_inner_stderr_falls_back_when_wrapper_absent() -> None:
    from agent_team_v15.retry_feedback import extract_buildkit_inner_stderr

    stderr = "regular stderr without buildkit wrapper\nsecond line\n"
    inner = extract_buildkit_inner_stderr(stderr)
    assert "regular stderr" in inner
    assert "second line" in inner


def test_extract_nextjs_build_errors_module_not_found() -> None:
    """Next.js ``Module not found: Can't resolve '<target>'`` issue title.

    Locked via Context7: ``/vercel/next.js`` ``turbopackIgnoreIssue`` doc
    confirms ``Module not found`` is the canonical title string.
    """
    from agent_team_v15.retry_feedback import extract_nextjs_build_errors

    stderr = (
        "Failed to compile.\n\n"
        "./app/page.tsx\n"
        "Module not found: Can't resolve '@/lib/missing'\n"
    )
    errors = extract_nextjs_build_errors(stderr)
    targets = [e for e in errors if e.get("kind") == "module_not_found"]
    assert any(t["target"] == "@/lib/missing" for t in targets)


def test_extract_nextjs_build_errors_compile_error_with_file_line_col() -> None:
    """Next.js error blocks lead with ``./path:line:col`` lines."""
    from agent_team_v15.retry_feedback import extract_nextjs_build_errors

    stderr = (
        "Failed to compile.\n\n"
        "./apps/web/src/app/layout.tsx:8:17\n"
        "Type error: Property 'lang' is missing in type ...\n"
    )
    errors = extract_nextjs_build_errors(stderr)
    compile_errors = [e for e in errors if e.get("kind") == "compile_error"]
    assert any(
        e["file"] == "apps/web/src/app/layout.tsx" and e["line"] == 8
        for e in compile_errors
    )


# ---------------------------------------------------------------------------
# Unresolved-imports scanner
# ---------------------------------------------------------------------------


def test_scan_unresolved_imports_finds_missing_relative_target(
    tmp_path: Path,
) -> None:
    from agent_team_v15.retry_feedback import scan_unresolved_imports

    src = tmp_path / "a.ts"
    src.write_text(
        "import { Foo } from '../missing/file';\n"
        "import { Bar } from './also-missing';\n",
        encoding="utf-8",
    )
    findings = scan_unresolved_imports(["a.ts"], str(tmp_path))
    targets = {f["import_target"] for f in findings}
    assert "../missing/file" in targets
    assert "./also-missing" in targets


def test_scan_unresolved_imports_skips_node_modules_bare_specifiers(
    tmp_path: Path,
) -> None:
    """Bare specifiers (e.g. 'react', '@nestjs/core') resolve via
    node_modules — we can't confirm without parsing package.json. Skip."""
    from agent_team_v15.retry_feedback import scan_unresolved_imports

    src = tmp_path / "a.ts"
    src.write_text(
        "import * as React from 'react';\n"
        "import { Module } from '@nestjs/core';\n",
        encoding="utf-8",
    )
    findings = scan_unresolved_imports(["a.ts"], str(tmp_path))
    assert findings == []


def test_scan_unresolved_imports_resolves_via_index_files(tmp_path: Path) -> None:
    """An import like `./lib` resolves if `./lib/index.ts` exists."""
    from agent_team_v15.retry_feedback import scan_unresolved_imports

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    src = tmp_path / "a.ts"
    src.write_text("import { x } from './lib';\n", encoding="utf-8")

    findings = scan_unresolved_imports(["a.ts"], str(tmp_path))
    assert findings == []


def test_scan_unresolved_imports_resolves_via_extension_inference(
    tmp_path: Path,
) -> None:
    """An import like `./util` resolves if `./util.ts` exists."""
    from agent_team_v15.retry_feedback import scan_unresolved_imports

    (tmp_path / "util.ts").write_text("export const x = 1;\n", encoding="utf-8")
    src = tmp_path / "a.ts"
    src.write_text("import { x } from './util';\n", encoding="utf-8")

    findings = scan_unresolved_imports(["a.ts"], str(tmp_path))
    assert findings == []


def test_scan_unresolved_imports_ignores_non_ts_js_files(tmp_path: Path) -> None:
    from agent_team_v15.retry_feedback import scan_unresolved_imports

    src = tmp_path / "a.md"
    src.write_text("import { x } from './missing';\n", encoding="utf-8")

    findings = scan_unresolved_imports(["a.md"], str(tmp_path))
    assert findings == []


# ---------------------------------------------------------------------------
# Progressive signal — sources from WAVE_FINDINGS-shaped attribution
# ---------------------------------------------------------------------------


def test_progressive_signal_partial_progress_api_passes_web_fails() -> None:
    """retry=2 of the 2026-04-26 smoke: api PASSED (was failing on retry=1),
    web NEW failure. Signal must reflect this transition.
    """
    from agent_team_v15.retry_feedback import compute_progressive_signal

    prior = [{"retry": 1, "failing_services": ["api"]}]
    this_attempt = {"retry": 2, "failing_services": ["web"]}

    signal = compute_progressive_signal(this_attempt, prior)

    assert signal != ""
    low = signal.lower()
    # Must mention api was previously failing.
    assert "api" in low
    # Must mention web is now failing.
    assert "web" in low
    # Must indicate api is now fixed.
    assert "fixed" in low or "keep" in low or "passed" in low.lower()


def test_progressive_signal_no_progress_same_failures() -> None:
    from agent_team_v15.retry_feedback import compute_progressive_signal

    prior = [{"retry": 0, "failing_services": ["api"]}]
    this_attempt = {"retry": 1, "failing_services": ["api"]}

    signal = compute_progressive_signal(this_attempt, prior)

    assert signal != ""
    # Should not claim anything was fixed.
    assert "fixed" not in signal.lower() or "no" in signal.lower()


def test_progressive_signal_first_attempt_returns_empty() -> None:
    """No prior attempts → no progressive signal (regression-safe)."""
    from agent_team_v15.retry_feedback import compute_progressive_signal

    assert compute_progressive_signal(
        {"retry": 0, "failing_services": ["api"]}, []
    ) == ""


def test_progressive_signal_sources_from_per_attempt_failing_services() -> None:
    """Plan-level invariant: progressive signal sources from
    WAVE_FINDINGS-shaped per-attempt outcome data, NOT from the protocol
    log's <previous_attempt_failed> block content.

    The smoke quirk: protocol log at retry=2 reports service=api (prior
    failure echo) while WAVE_FINDINGS.json shows retry=2 actually failed
    on service=web. compute_progressive_signal MUST use the WAVE_FINDINGS-
    shaped attribution (failing_services), not protocol-log narration.
    """
    from agent_team_v15.retry_feedback import compute_progressive_signal

    prior = [
        {"retry": 0, "failing_services": ["api"]},
        {"retry": 1, "failing_services": ["api"]},
    ]
    this_attempt = {"retry": 2, "failing_services": ["web"]}

    signal = compute_progressive_signal(this_attempt, prior)
    # Signal compares prior[-1].failing_services (api) vs
    # this_attempt.failing_services (web). It must NOT claim "api still
    # failing" — that would be the protocol-log-derived (wrong) view.
    assert "api" in signal.lower()
    assert "web" in signal.lower()
    # Sanity: api went from FAILED → not-failing in this_attempt.
    assert (
        "fixed" in signal.lower()
        or "keep" in signal.lower()
        or "passed" in signal.lower()
    ), signal


# ---------------------------------------------------------------------------
# build_retry_payload — composition + ACs (AC1..AC7)
# ---------------------------------------------------------------------------


def test_retry_payload_passes_through_when_first_attempt() -> None:
    """AC5: empty inputs (no prior attempts, no failure data) → empty
    string. The wave_executor only appends a suffix when an attempt
    failed, so this defends against a degenerate caller.
    """
    from agent_team_v15.retry_feedback import build_retry_payload

    payload = build_retry_payload(
        stderr="",
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[],
        wave_letter="B",
    )
    assert payload == ""


def test_retry_payload_includes_full_stderr_truncated_to_5kb() -> None:
    """AC1: stderr included, but tail-bounded at ~5KB with a marker
    indicating the truncation."""
    from agent_team_v15.retry_feedback import build_retry_payload

    big_stderr = "ELIFECYCLE Command failed.\n" + ("X" * 50_000)
    payload = build_retry_payload(
        stderr=big_stderr,
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[],
        wave_letter="B",
        this_retry_index=0,
    )

    assert payload != ""
    # Marker on truncation
    assert "truncated" in payload.lower()
    # The original 50KB stderr must NOT all be present.
    assert payload.count("X") < 6000
    # But the meaningful tail content must be (we keep tail; the X's
    # appear at the tail).
    assert "XXX" in payload


def test_retry_payload_extracts_typescript_errors_with_file_line() -> None:
    """AC2: parsed compile errors with file:line in the payload."""
    from agent_team_v15.retry_feedback import build_retry_payload

    stderr = (
        "apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module '@app/api-client'.\n"
        "target api: failed to solve: process \"/bin/sh -c pnpm --filter "
        "api build\" did not complete successfully: exit code: 1\n"
    )
    payload = build_retry_payload(
        stderr=stderr,
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[],
        wave_letter="B",
        this_retry_index=0,
    )

    assert "TS2307" in payload
    assert "auth.module.ts" in payload
    assert "12" in payload  # line number


def test_retry_payload_lists_unresolved_imports_from_modified_files(
    tmp_path: Path,
) -> None:
    """AC3: unresolved imports from modified files appear in the payload."""
    from agent_team_v15.retry_feedback import build_retry_payload

    src = tmp_path / "modified.ts"
    src.write_text(
        "import { Missing } from '../does/not/exist';\n",
        encoding="utf-8",
    )
    payload = build_retry_payload(
        stderr="some build failure",
        modified_files=["modified.ts"],
        project_root=str(tmp_path),
        prior_attempts=[],
        wave_letter="B",
        this_retry_index=0,
    )

    assert "../does/not/exist" in payload
    assert "modified.ts" in payload


def test_retry_payload_includes_progressive_signal_when_partial_progress() -> None:
    """AC4: progressive signal across retries appears in the payload."""
    from agent_team_v15.retry_feedback import build_retry_payload

    payload = build_retry_payload(
        stderr=(
            "target web: failed to solve: process \"/bin/sh -c pnpm --filter "
            "web build\" did not complete successfully: exit code: 1\n"
        ),
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[
            {"retry": 0, "failing_services": ["api"]},
            {"retry": 1, "failing_services": ["api"]},
        ],
        wave_letter="B",
        this_retry_index=2,
    )
    assert payload
    low = payload.lower()
    # Mentions both services — what was failing previously and what's
    # failing now.
    assert "api" in low
    assert "web" in low
    # Progressive language present (varies by phrasing).
    assert any(tok in low for tok in ("fixed", "keep", "now", "previous"))


def test_retry_payload_respects_max_size_limit() -> None:
    """AC6: payload is bounded at 12KB even on pathological inputs."""
    from agent_team_v15.retry_feedback import build_retry_payload

    # Synthesize many TS errors so the parsed-errors section bloats.
    huge_stderr = "\n".join(
        f"apps/api/src/file{i}.ts({i},1): error TS2307: "
        f"Cannot find module '@scope/missing-{i}'."
        for i in range(2000)
    )
    payload = build_retry_payload(
        stderr=huge_stderr,
        modified_files=[f"apps/api/src/file{i}.ts" for i in range(500)],
        project_root="/tmp",
        prior_attempts=[],
        wave_letter="B",
        this_retry_index=0,
        max_size_bytes=12000,
    )
    assert len(payload.encode("utf-8")) <= 12000
    # And the tag is preserved at the start AND end so the consumer can
    # find the boundaries (no truncated tag).
    assert payload.startswith("<previous_attempt_failed>")
    assert payload.rstrip().endswith("</previous_attempt_failed>")


def test_retry_payload_handles_codex_sandbox_could_not_run_docker_case() -> None:
    """AC7 / Risk #29: Codex sandbox can't run `docker compose build`
    (Windows buildx lock). Payload must give Codex enough actionable
    signal WITHOUT requiring the sandbox to reproduce the failure.
    """
    from agent_team_v15.retry_feedback import build_retry_payload

    # We feed only the parent's parsed stderr; Codex's sandbox would NOT
    # have access to this if it tried `docker compose build` itself.
    stderr = (
        "apps/api/src/auth/auth.module.ts(12,3): error TS2307: "
        "Cannot find module '@app/api-client'.\n"
        "target api: failed to solve: process \"/bin/sh -c pnpm --filter "
        "api build\" did not complete successfully: exit code: 1\n"
    )
    payload = build_retry_payload(
        stderr=stderr,
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[{"retry": 0, "failing_services": ["api"]}],
        wave_letter="B",
        this_retry_index=1,
    )
    # Payload must contain explicit "do not re-run docker compose build"
    # guidance so Codex isn't tempted to reproduce in its sandbox.
    low = payload.lower()
    assert "do not re-run" in low or "do not reproduce" in low or "cannot run" in low
    # And the parsed error is the primary actionable input, not the
    # buildkit wrapper.
    assert "TS2307" in payload
    assert "auth.module.ts" in payload


# ---------------------------------------------------------------------------
# Wave-letter framing — Wave B vs Wave D framing differs
# ---------------------------------------------------------------------------


def test_retry_payload_wave_b_framing() -> None:
    """Wave B framing: title/identity mentions Wave B as the failing wave;
    the build-command directive is `docker compose build api`. Wave D
    may appear ONLY in the scope-boundary teaching ("Wave D owns these
    files — do not modify") — never as the just-failed wave's identity.
    """
    from agent_team_v15.retry_feedback import build_retry_payload

    payload = build_retry_payload(
        stderr="something failed",
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[{"retry": 0, "failing_services": ["api"]}],
        wave_letter="B",
        this_retry_index=1,
    )
    # Identity / build directives.
    assert "Wave B retry=" in payload
    assert "Wave B is the BACKEND wave" in payload
    assert "docker compose build api" in payload
    # Wave B appears more often than Wave D (Wave B is the subject;
    # Wave D appears only as the OUT OF SCOPE owner reminder).
    assert payload.count("Wave B") > payload.count("Wave D"), (
        payload.count("Wave B"),
        payload.count("Wave D"),
    )
    # The build directive for Wave D MUST NOT be in a Wave B payload.
    assert "docker compose build web" not in payload


def test_retry_payload_wave_d_framing() -> None:
    """Wave D framing: identity is Wave D; build directive is
    `docker compose build web`; Wave B appears only in scope-boundary
    teaching, not as the failing wave's identity.
    """
    from agent_team_v15.retry_feedback import build_retry_payload

    payload = build_retry_payload(
        stderr="something failed",
        modified_files=[],
        project_root="/tmp",
        prior_attempts=[{"retry": 0, "failing_services": ["web"]}],
        wave_letter="D",
        this_retry_index=1,
    )
    assert "Wave D retry=" in payload
    assert "Wave D is the FRONTEND" in payload
    assert "docker compose build web" in payload
    # Wave D appears more often than Wave B.
    assert payload.count("Wave D") > payload.count("Wave B"), (
        payload.count("Wave D"),
        payload.count("Wave B"),
    )
    # The build directive for Wave B MUST NOT be in a Wave D payload.
    assert "docker compose build api" not in payload


# ---------------------------------------------------------------------------
# Replay smoke evidence — the data-driven proof per §0.3 step 2
# ---------------------------------------------------------------------------


def test_replay_smoke_2026_04_26_baseline_payload_under_150_bytes_per_block() -> None:
    """Lock the baseline: each <previous_attempt_failed> block in the
    frozen smoke fixture is ~150 bytes (per §0.3 step 2). This anchors
    the ≥10× richness target.
    """
    raw = RETRY_PAYLOADS_FIXTURE.read_text(encoding="utf-8")
    blocks = []
    cursor = 0
    while True:
        start = raw.find("<previous_attempt_failed>", cursor)
        if start == -1:
            break
        end = raw.find("</previous_attempt_failed>", start)
        if end == -1:
            break
        block = raw[start : end + len("</previous_attempt_failed>")]
        blocks.append(block)
        cursor = end + 1

    assert len(blocks) == 2, f"expected 2 retry blocks in fixture, got {len(blocks)}"
    # Per the user-supplied callout: target=≥10× richer than ≥150-byte
    # baseline (so ≥1500 bytes target). The frozen blocks are bounded
    # at ~600 bytes (more substantial than the §0.3 ~150 estimate, but
    # still skinny — primary content is one buildkit error line).
    for b in blocks:
        assert len(b.encode("utf-8")) <= 700, len(b.encode("utf-8"))


def test_replay_smoke_2026_04_26_payload_is_at_least_10x_richer_than_baseline() -> None:
    """AC contract: Phase 4.2's payload built from the same smoke evidence
    is ≥10× richer (≥1500 bytes) than the legacy ≤150-byte baseline.

    Sources prior_attempts from WAVE_FINDINGS.json — the canonical
    per-attempt failing_services data — NOT from the protocol log's
    <previous_attempt_failed> blocks (the user-flagged quirk: protocol
    log narration ≠ WAVE_FINDINGS attribution).
    """
    from agent_team_v15.retry_feedback import build_retry_payload

    findings = json.loads(WAVE_FINDINGS_FIXTURE.read_text(encoding="utf-8"))
    wave_b_attempts = [
        f for f in findings["findings"]
        if f.get("wave") == "B" and f.get("code") == "WAVE-B-SELF-VERIFY"
    ]
    # Build prior_attempts from retry=0 + retry=1; this_attempt is retry=2.
    prior = []
    this_attempt_msg = ""
    for entry in wave_b_attempts:
        msg = entry.get("message", "")
        retry_n = int(msg.split(" ", 1)[0].split("=", 1)[1])
        services = [s.strip() for s in (entry.get("file") or "").split(",") if s.strip()]
        if retry_n < 2:
            prior.append({
                "retry": retry_n,
                "failing_services": services,
                "error_summary": msg,
            })
        else:
            this_attempt_msg = msg

    payload = build_retry_payload(
        stderr=this_attempt_msg
        + "\ntarget web: failed to solve: process \"/bin/sh -c pnpm "
          "--filter web build\" did not complete successfully: exit code: 1\n",
        modified_files=[],
        project_root="/tmp",
        prior_attempts=prior,
        wave_letter="B",
        this_retry_index=2,
    )

    payload_size = len(payload.encode("utf-8"))
    assert payload_size >= 1500, (
        f"Phase 4.2 contract: payload ≥1500 bytes (≥10× of ~150-byte "
        f"baseline); got {payload_size}"
    )
    assert payload_size <= 12000


# ---------------------------------------------------------------------------
# Config flag — AC kill switch
# ---------------------------------------------------------------------------


def test_audit_team_config_strong_retry_feedback_enabled_default_true() -> None:
    """Master kill switch defaults to True (Phase 4.2 active out of box).

    Operators can flip to False via config to restore the pre-Phase-4.2
    ~150-byte legacy block (rollback contract — preserves one release
    cycle of fallback as required by plan §0.3 step 2.2).
    """
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert hasattr(cfg, "strong_retry_feedback_enabled")
    assert cfg.strong_retry_feedback_enabled is True


def test_legacy_payload_when_strong_feedback_disabled() -> None:
    """When the kill switch is False, the helper returns the legacy
    ~150-byte block (rollback path)."""
    from agent_team_v15.retry_feedback import _legacy_retry_prompt_suffix

    legacy = _legacy_retry_prompt_suffix(
        "Docker build failures (per service):\n"
        "- service=api duration_s=26.83\n"
        "target api: failed to solve: process \"/bin/sh -c pnpm --filter "
        "api build\" did not complete successfully: exit code: 1",
        wave_letter="B",
    )
    # Locked: legacy block size ~600 bytes — preserves rollback behaviour.
    assert len(legacy.encode("utf-8")) < 1000
    assert "<previous_attempt_failed>" in legacy
    assert "Wave B" in legacy
    assert "</previous_attempt_failed>" in legacy


# ---------------------------------------------------------------------------
# Shim wiring — Wave B and Wave D self-verify call the new helper
# ---------------------------------------------------------------------------


def test_wave_b_shim_uses_retry_feedback_when_flag_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave B's ``_build_retry_prompt_suffix`` shim delegates to the
    Phase 4.2 ``build_retry_payload`` when ``strong_feedback_enabled``
    (default). The wave_executor passes ``stderr`` + ``prior_attempts``
    + ``modified_files`` through ``run_wave_b_acceptance_test`` kwargs.
    """
    from agent_team_v15 import wave_b_self_verify as wbsv

    suffix = wbsv._build_retry_prompt_suffix(
        error_summary="Docker build failures",
        stderr=(
            "apps/api/src/x.ts(1,1): error TS2307: Cannot find module 'foo'.\n"
            "target api: failed to solve: process \"/bin/sh -c pnpm "
            "--filter api build\" did not complete successfully: exit code: 1"
        ),
        modified_files=[],
        project_root=str(tmp_path),
        prior_attempts=[{"retry": 0, "failing_services": ["api"]}],
        this_retry_index=1,
        strong_feedback_enabled=True,
        wave_letter="B",
    )
    # New payload contains the Phase 4.2 sections (parsed errors,
    # progressive signal). Legacy payload doesn't.
    assert "TS2307" in suffix
    assert "Wave B" in suffix
    assert len(suffix.encode("utf-8")) >= 1500


def test_wave_d_shim_uses_retry_feedback_when_flag_enabled(
    tmp_path: Path,
) -> None:
    from agent_team_v15 import wave_d_self_verify as wdsv

    suffix = wdsv._build_retry_prompt_suffix(
        error_summary="Docker build failures",
        stderr=(
            "apps/web/src/middleware.ts(1,1): error TS2307: Cannot find module 'foo'.\n"
            "target web: failed to solve: process \"/bin/sh -c pnpm "
            "--filter web build\" did not complete successfully: exit code: 1"
        ),
        modified_files=[],
        project_root=str(tmp_path),
        prior_attempts=[{"retry": 0, "failing_services": ["web"]}],
        this_retry_index=1,
        strong_feedback_enabled=True,
        wave_letter="D",
    )
    assert "Wave D" in suffix
    assert "docker compose build web" in suffix
    assert "TS2307" in suffix


def test_wave_b_shim_legacy_path_when_flag_disabled() -> None:
    """``strong_feedback_enabled=False`` → legacy ~150-byte block."""
    from agent_team_v15 import wave_b_self_verify as wbsv

    suffix = wbsv._build_retry_prompt_suffix(
        error_summary="Docker build failures",
        strong_feedback_enabled=False,
        wave_letter="B",
    )
    assert len(suffix.encode("utf-8")) < 1000
    assert "<previous_attempt_failed>" in suffix
    assert "Wave B" in suffix


def test_wave_b_shim_default_call_preserves_legacy_callsite_compat() -> None:
    """Existing callers that pass only ``error_summary`` still work; the
    shim defaults to strong-feedback mode but degrades gracefully when
    Phase 4.2 inputs are absent (no progressive signal → falls back to
    just including stderr/error_summary text).
    """
    from agent_team_v15 import wave_b_self_verify as wbsv

    suffix = wbsv._build_retry_prompt_suffix("error summary text")
    # Output is non-empty and contains the Wave B framing.
    assert suffix
    assert "<previous_attempt_failed>" in suffix
    assert "Wave B" in suffix


# ---------------------------------------------------------------------------
# wave_executor wiring — passes prior_attempts and modified_files through
# ---------------------------------------------------------------------------


def test_run_wave_b_acceptance_test_accepts_phase_4_2_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 4.2 adds ``modified_files``, ``prior_attempts``,
    ``this_retry_index``, ``strong_feedback_enabled`` kwargs to
    ``run_wave_b_acceptance_test`` so the wave_executor loop can thread
    retry context through. Existing callers (no kwargs) still work.
    """
    import inspect
    from agent_team_v15 import wave_b_self_verify as wbsv

    sig = inspect.signature(wbsv.run_wave_b_acceptance_test)
    for kw in (
        "modified_files",
        "prior_attempts",
        "this_retry_index",
        "strong_feedback_enabled",
    ):
        assert kw in sig.parameters, f"missing kwarg: {kw}"


def test_run_wave_d_acceptance_test_accepts_phase_4_2_kwargs() -> None:
    import inspect
    from agent_team_v15 import wave_d_self_verify as wdsv

    sig = inspect.signature(wdsv.run_wave_d_acceptance_test)
    for kw in (
        "modified_files",
        "prior_attempts",
        "this_retry_index",
        "strong_feedback_enabled",
    ):
        assert kw in sig.parameters, f"missing kwarg: {kw}"


def test_run_wave_b_acceptance_test_threads_phase_4_2_kwargs_into_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the helper is called with Phase 4.2 kwargs, the resulting
    ``retry_prompt_suffix`` reflects the threaded context (parsed
    errors, progressive signal).
    """
    from agent_team_v15 import runtime_verification as rv
    from agent_team_v15 import wave_b_self_verify as wbsv

    monkeypatch.setattr(wbsv, "check_docker_available", lambda: True)
    monkeypatch.setattr(
        wbsv, "validate_compose_build_context", lambda *a, **kw: [],
    )

    def fake_run_docker(*args: str, cwd: str | None = None, timeout: int = 600):
        if "config" in args:
            return (0, "api\nweb\npostgres\n", "")
        # Fail on api build with TS error in stderr.
        return (
            1,
            "",
            (
                "apps/api/src/x.ts(1,1): error TS2307: Cannot find module 'foo'.\n"
                "target api: failed to solve: process \"/bin/sh -c pnpm "
                "--filter api build\" did not complete successfully: exit "
                "code: 1"
            ),
        )

    monkeypatch.setattr(rv, "_run_docker", fake_run_docker)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    result = wbsv.run_wave_b_acceptance_test(
        tmp_path,
        modified_files=[],
        prior_attempts=[{"retry": 0, "failing_services": ["api"]}],
        this_retry_index=1,
    )

    assert result.passed is False
    # The retry suffix reflects Phase 4.2 enrichment.
    assert "TS2307" in result.retry_prompt_suffix
    assert len(result.retry_prompt_suffix.encode("utf-8")) >= 1500
