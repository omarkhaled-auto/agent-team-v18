"""Phase 3.5 audit-fix-loop guardrail fixtures.

Goal: close the free-form-feature gap left open by Phase 3. When a
fix feature has no ``target_files`` (because every contributing
``Finding.file_path`` is empty), Phase 3's per-feature env-var
allowlist becomes a no-op — the audit-fix path-guard hook is registered
but allow-alls every write because ``AGENT_TEAM_FINDING_ID`` is unset.

Phase 3.5 closes the gap with a hybrid Path B + Path A approach:

* **Path B (root)**: fix the latent ``AuditFinding.from_dict`` bug —
  evidence synthesis reads ``file`` but every audit JSON in this
  repo's smoke history uses ``file_path``. One-line fix; recovers
  ~16 percentage points of free-form rate.
* **Path B (synthesis helper)**: add
  ``AuditFinding.synthesise_primary_file()`` /
  free-function ``synthesise_primary_file(...)`` that walks evidence +
  Finding fields for path-shaped strings, filtered against on-disk
  reality. Rejects directories and parse-garbage tokens like ``"No"``.
* **Path B (generator)**: ``_build_features_section`` falls back to
  synthesis when no finding in the feature has a direct ``file_path``,
  so every emitted feature carries a ``#### Files to Modify`` section.
* **Path B (parse backstop)**: ``_classify_fix_features`` flags
  features with empty ``files_to_modify + files_to_create`` via
  ``feature["skip_reason"] = "no_target_files"`` so downstream
  callers can honour the skip without re-running heuristics.
* **Path A (dispatch backstop)**: ``_run_patch_fixes`` skips features
  with empty ``target_files`` — defense in depth against any feature
  that slips past synthesis. Logs ``[FIX-DENYLIST] feature ... has no
  target_files; skipped per Phase 3.5``.
* **Path C (verification)**: lock the try/finally restore-prior-env
  invariant so the parent's per-feature env doesn't leak into
  ``_run_full_build``'s subprocess.

Inter-phase dependency check: imports the Phase 3.5 public API. If the
imports fail at collection time the whole file errors as
``ImportError`` — the expected initial-red state per §0.4 TDD step 1.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

# Phase 3.5 public API — these must resolve once Phase 3.5 lands.
from agent_team_v15.audit_models import (  # noqa: E402
    AuditFinding,
    synthesise_primary_file,
)
from agent_team_v15.fix_executor import _classify_fix_features  # noqa: E402
from agent_team_v15.fix_prd_agent import _build_features_section  # noqa: E402
from agent_team_v15.audit_agent import (  # noqa: E402
    Finding,
    FindingCategory,
    Severity,
)


# ---------------------------------------------------------------------------
# Path B (root): AuditFinding.from_dict synthesises evidence from file_path
# ---------------------------------------------------------------------------


def test_audit_finding_from_dict_synthesises_evidence_from_file_path() -> None:
    """The latent bug: every audit JSON in this repo's smoke history
    (build-final-smoke-2026-04-18 through m1-hardening-smoke-2026-04-25)
    uses ``file_path`` as the per-finding file key, but ``from_dict``
    reads ``file``. Evidence stayed empty, ``primary_file`` returned
    ``""``, downstream features got no ``target_files``, the audit-fix
    hook went no-op for ~25% of features. Closing this drops the free-
    form rate from 41% to ~5%.
    """
    payload = {
        "id": "FINDING-001",
        "severity": "CRITICAL",
        "title": "Layout stub",
        "description": "apps/web/src/app/layout.tsx is a 12-line stub",
        "file_path": "apps/web/src/app/layout.tsx",
        "line_number": 1,
        "fix_action": "Replace stub with locale-aware layout",
    }
    af = AuditFinding.from_dict(payload)
    assert af.evidence, (
        "Empty evidence breaks the audit-fix scope binding. "
        "from_dict must synthesise evidence from file_path when it's "
        "the only file hint available."
    )
    assert af.primary_file == "apps/web/src/app/layout.tsx", (
        f"primary_file should round-trip the file_path; got {af.primary_file!r}"
    )


def test_audit_finding_from_dict_still_reads_legacy_file_key() -> None:
    """Backward compat: the legacy ``file`` key (pre-2026 audit format
    or external integrations) must keep working. Phase 3.5 adds
    file_path as a fallback, doesn't replace file.
    """
    payload = {
        "id": "LEGACY-001",
        "severity": "HIGH",
        "summary": "legacy field name",
        "description": "uses file not file_path",
        "file": "apps/api/legacy.py",
    }
    af = AuditFinding.from_dict(payload)
    assert af.evidence, "Legacy 'file' key must still synthesise evidence"
    assert af.primary_file == "apps/api/legacy.py"


def test_audit_finding_from_dict_prefers_explicit_evidence() -> None:
    """When the auditor provides an explicit ``evidence`` array, it
    takes precedence over file_path/file synthesis (no double-emission,
    no clobber).
    """
    payload = {
        "id": "EVIDENCE-001",
        "severity": "MEDIUM",
        "summary": "explicit evidence wins",
        "evidence": ["apps/web/explicit.tsx:42 -- explicit win"],
        "file_path": "apps/api/should_not_win.py",
    }
    af = AuditFinding.from_dict(payload)
    assert af.evidence == ["apps/web/explicit.tsx:42 -- explicit win"]
    assert af.primary_file == "apps/web/explicit.tsx"


# ---------------------------------------------------------------------------
# Path B (synthesis helper): synthesise_primary_file walks Finding fields
# ---------------------------------------------------------------------------


def test_synthesise_primary_file_walks_description_for_path_shaped_strings(
    tmp_path: Path,
) -> None:
    """Free-function ``synthesise_primary_file`` extracts a path from
    a description / current_behavior / fix_suggestion field even when
    ``Finding.file_path`` is empty. The path must exist on disk to be
    accepted — otherwise downstream allowlist composition would deny
    every write for that feature.
    """
    target = tmp_path / "apps" / "web" / "login.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("// stub\n")

    finding = Finding(
        id="F-SYNTH-001",
        feature="AUDIT",
        acceptance_criterion="Login broken",
        severity=Severity.HIGH,
        category=FindingCategory.CODE_FIX,
        title="Login broken",
        description="Issue in apps/web/login.tsx is missing await on form submit",
        prd_reference="REQ-001",
        current_behavior="apps/web/login.tsx renders without await",
        expected_behavior="form submit awaits server response",
        file_path="",  # deliberately empty — synthesis must fill this gap
        line_number=0,
        code_snippet="",
        fix_suggestion="",
        estimated_effort="small",
        test_requirement="",
    )
    paths = synthesise_primary_file(finding, project_root=tmp_path)
    assert paths == ["apps/web/login.tsx"], (
        "Synthesis must extract the path-shaped token from the description "
        "and accept it (file exists on disk)."
    )


def test_synthesise_primary_file_rejects_directories(tmp_path: Path) -> None:
    """A path token like ``apps/api`` matches the regex but is a
    directory on disk — must be rejected so we don't allowlist a
    directory (which would either widen the per-feature scope to a
    Wave-D-style glob, or fail-CLOSED on every write because the
    Phase 3 hook treats entries as exact-file allowlist).
    """
    (tmp_path / "apps" / "api").mkdir(parents=True)

    finding = Finding(
        id="F-DIR-001",
        feature="AUDIT",
        acceptance_criterion="No backend",
        severity=Severity.CRITICAL,
        category=FindingCategory.CODE_FIX,
        title="No backend",
        description="No backend controllers exist under apps/api directory",
        prd_reference="REQ-002",
        current_behavior="apps/api directory contains only schema",
        expected_behavior="apps/api should contain NestJS skeleton",
        file_path="",
        line_number=0,
        code_snippet="",
        fix_suggestion="",
        estimated_effort="medium",
        test_requirement="",
    )
    paths = synthesise_primary_file(finding, project_root=tmp_path)
    assert paths == [], (
        "Directories must be filtered out — exact-file allowlist semantic "
        "means a directory entry would become an allow-zero-files entry."
    )


def test_synthesise_primary_file_rejects_nonexistent_paths(tmp_path: Path) -> None:
    """A path-shaped string for a file that doesn't exist on disk is
    most often a parse miss (description token like ``"No locales/..."``
    extracted as ``"locales/en/common.json"`` when the locales dir
    was never created). Must be rejected so the allowlist contains
    only real files.
    """
    finding = Finding(
        id="F-MISSING-001",
        feature="AUDIT",
        acceptance_criterion="Missing locales",
        severity=Severity.HIGH,
        category=FindingCategory.MISSING_FEATURE,
        title="Missing locales",
        description="No locales/en/common.json exists in the repo",
        prd_reference="REQ-003",
        current_behavior="locales/en/common.json does not exist",
        expected_behavior="locales/en/common.json with seed keys",
        file_path="",
        line_number=0,
        code_snippet="",
        fix_suggestion="Create locales/en/common.json with seed keys",
        estimated_effort="small",
        test_requirement="",
    )
    paths = synthesise_primary_file(finding, project_root=tmp_path)
    assert paths == []


def test_synthesise_primary_file_returns_empty_for_no_extractable_paths(
    tmp_path: Path,
) -> None:
    """When the finding has no path-shaped tokens at all, synthesis
    must return ``[]`` so the caller can ship-block the feature
    (Path A residual). Returning a bogus path here would violate the
    exact-file allowlist invariant and silently allow all writes.
    """
    finding = Finding(
        id="F-PROSE-001",
        feature="AUDIT",
        acceptance_criterion="Prose",
        severity=Severity.MEDIUM,
        category=FindingCategory.CODE_FIX,
        title="Prose only",
        description="The build halted with status FAILED. Convergence is zero.",
        prd_reference="REQ-004",
        current_behavior="Build halted at orchestration phase",
        expected_behavior="Build completes",
        file_path="",
        line_number=0,
        code_snippet="",
        fix_suggestion="Investigate orchestration failure",
        estimated_effort="medium",
        test_requirement="",
    )
    paths = synthesise_primary_file(finding, project_root=tmp_path)
    assert paths == []


# ---------------------------------------------------------------------------
# Path B (generator): _build_features_section synthesises when no finding
# in the feature has a direct file_path.
# ---------------------------------------------------------------------------


def test_build_features_section_synthesises_when_findings_lack_file_path(
    tmp_path: Path,
) -> None:
    """When every finding in a feature has empty ``file_path`` but the
    description contains a path-shaped token that exists on disk, the
    PRD generator must emit a ``#### Files to Modify`` section with
    that synthesised path. Without this, ``_parse_fix_features`` would
    return ``files_to_modify=[]`` and the per-feature dispatch would
    have no scope binding.
    """
    target = tmp_path / "apps" / "api" / "auth.py"
    target.parent.mkdir(parents=True)
    target.write_text("def auth(): pass\n")

    finding = Finding(
        id="F-001",
        feature="AUDIT",
        acceptance_criterion="auth broken",
        severity=Severity.HIGH,
        category=FindingCategory.CODE_FIX,
        title="auth broken",
        description="apps/api/auth.py rejects valid tokens",
        prd_reference="REQ-001",
        current_behavior="apps/api/auth.py rejects valid tokens",
        expected_behavior="apps/api/auth.py accepts valid tokens",
        file_path="",  # empty — forces synthesis path
        line_number=0,
        code_snippet="",
        fix_suggestion="",
        estimated_effort="small",
        test_requirement="",
    )
    feature = {
        "name": "auth_security",
        "findings": [finding],
        "category": FindingCategory.SECURITY,
        "severity": Severity.HIGH,
    }
    rendered = _build_features_section([feature], prd_text="", project_root=tmp_path)
    assert "#### Files to Modify" in rendered, (
        "Synthesis must emit a Files-to-Modify section even when no "
        "finding had a direct file_path."
    )
    assert "apps/api/auth.py" in rendered


def test_build_features_section_keeps_direct_file_path_when_present(
    tmp_path: Path,
) -> None:
    """Backward-compat: when a finding has a direct ``file_path``, the
    generator still emits it without invoking synthesis (no behaviour
    change for the happy path).
    """
    target = tmp_path / "apps" / "web" / "page.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("export default function() {}\n")

    finding = Finding(
        id="F-002",
        feature="AUDIT",
        acceptance_criterion="page wrong",
        severity=Severity.MEDIUM,
        category=FindingCategory.CODE_FIX,
        title="page wrong",
        description="page renders with wrong locale",
        prd_reference="REQ-002",
        current_behavior="hardcoded en",
        expected_behavior="locale-aware",
        file_path="apps/web/page.tsx",  # direct
        line_number=10,
        code_snippet="",
        fix_suggestion="",
        estimated_effort="small",
        test_requirement="",
    )
    feature = {
        "name": "page_locale",
        "findings": [finding],
        "category": FindingCategory.CODE_FIX,
        "severity": Severity.MEDIUM,
    }
    rendered = _build_features_section([feature], prd_text="", project_root=tmp_path)
    assert "apps/web/page.tsx" in rendered
    # Ensure synthesis didn't fire a SECOND Files-to-Modify entry.
    # The direct file_path goes in Files-to-Modify; existing AC formatter
    # may also reference the path in the AC text — that's pre-Phase-3.5
    # behaviour we don't disturb. What matters is that the SECTION
    # only contains one entry per file.
    files_section = rendered.split("#### Files to Modify", 1)[1].split("####", 1)[0]
    files_occurrences = files_section.count("apps/web/page.tsx")
    assert files_occurrences == 1, (
        f"Files-to-Modify section emitted apps/web/page.tsx {files_occurrences} times; "
        "expected 1 — synthesis must NOT re-add a path the direct loop already produced."
    )


# ---------------------------------------------------------------------------
# Path B (parse backstop): _classify_fix_features marks residual free-form
# features with skip_reason="no_target_files".
# ---------------------------------------------------------------------------


def test_classify_fix_features_marks_residual_freeform_for_skip(
    tmp_path: Path,
) -> None:
    """When ``_classify_fix_features`` parses a fix PRD whose feature
    has neither ``Files to Modify`` nor ``Files to Create``, the
    feature dict must carry a sentinel
    ``skip_reason == "no_target_files"`` so the dispatch loop honours
    the skip without re-running heuristics. This is the parse-time
    backstop in the Phase 3.5 hybrid: synthesis at PRD-generation
    handles the bulk; this catches anything that slipped through.
    """
    fix_prd = """# Project — Targeted Fix Run 1

## Features

### F-FIX-001: free_form_no_files
[SEVERITY: HIGH]
[EXECUTION_MODE: patch]

- prose-only finding: nothing matches a path regex

#### Acceptance Criteria
- AC-FIX-001-01: Fix the prose
"""
    features = _classify_fix_features(fix_prd, cwd=tmp_path)
    assert len(features) == 1
    feature = features[0]
    assert feature.get("skip_reason") == "no_target_files", (
        f"Feature without target files must be tagged skip_reason="
        f"'no_target_files'; got {feature.get('skip_reason')!r}"
    )


def test_classify_fix_features_does_not_mark_targeted_features(
    tmp_path: Path,
) -> None:
    """Backward-compat: features with declared targets must NOT carry
    a ``skip_reason`` — only the residual free-form ones do.
    """
    fix_prd = """# Project — Targeted Fix Run 1

## Features

### F-FIX-001: targeted_feature
[SEVERITY: HIGH]
[EXECUTION_MODE: patch]

- finding describes apps/web/login.tsx

#### Files to Modify
- `apps/web/login.tsx` (line 42)

#### Acceptance Criteria
- AC-FIX-001-01: Fix the login form
"""
    features = _classify_fix_features(fix_prd, cwd=tmp_path)
    assert len(features) == 1
    feature = features[0]
    assert "skip_reason" not in feature or not feature.get("skip_reason"), (
        f"Targeted feature must not be marked for skip; got skip_reason="
        f"{feature.get('skip_reason')!r}"
    )
    assert feature.get("files_to_modify") == ["apps/web/login.tsx"]


# ---------------------------------------------------------------------------
# Path A (dispatch backstop): _run_patch_fixes skips features with empty
# target_files. Defense-in-depth even after Path B reduces the rate.
# ---------------------------------------------------------------------------


def _build_run_patch_fixes_via_unified() -> Any:
    """Return a callable wrapping ``_run_patch_fixes`` from inside the
    closure-defined ``_run_audit_fix_unified`` so we can exercise it
    in isolation. The patch-fixes function is a closure on cli's
    ``_run_audit_fix_unified``; we rely on Phase 3.5 exposing it in a
    testable form (e.g., via a module-level ``_run_patch_fixes`` or
    via ``_run_audit_fix_unified``'s execute_unified_fix_async
    callback path that lets us observe the behaviour through a mock).
    """
    # Phase 3.5 implementation is expected to keep _run_patch_fixes a
    # closure inside _run_audit_fix_unified for context-binding
    # reasons. We exercise it indirectly via execute_unified_fix_async.
    from agent_team_v15 import cli as cli_mod

    return cli_mod


def test_run_patch_fixes_skips_freeform_feature_when_target_files_empty(
    tmp_path: Path,
) -> None:
    """The dispatch backstop: even if a feature's
    ``files_to_modify + files_to_create`` is empty (Path A residual
    case after Path B synthesis), the per-feature loop must SKIP the
    dispatch rather than proceed with no scope binding. Logs a
    ``[FIX-DENYLIST] feature ... no target_files`` warning so the
    operator sees the drop in coverage.
    """
    import asyncio

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    # Two patch features: one targeted, one free-form.
    targeted = {
        "name": "targeted_fix",
        "header": "F-FIX-001: targeted_fix",
        "block": "F-FIX-001 block",
        "files_to_modify": ["apps/web/page.tsx"],
        "files_to_create": [],
        "execution_mode": "patch",
        "mode": "patch",
    }
    freeform = {
        "name": "freeform_fix",
        "header": "F-FIX-002: freeform_fix",
        "block": "F-FIX-002 block",
        "files_to_modify": [],
        "files_to_create": [],
        "execution_mode": "patch",
        "mode": "patch",
        "skip_reason": "no_target_files",
    }

    # Track which features the dispatch path is invoked for.
    sdk_invocations: list[str] = []

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def query(self, prompt):
            sdk_invocations.append(prompt)

        async def receive_response(self):
            yield SimpleNamespace(content=[])

    # The orchestration path: _run_audit_fix_unified -> execute_unified_fix_async
    # We patch execute_unified_fix_async to simulate the path-fixes loop
    # invocation and capture which features get dispatched.
    captured_features: list[list[dict]] = []

    async def _fake_execute_unified_fix_async(
        *,
        findings,
        original_prd_path,
        cwd,
        config,
        run_number,
        run_full_build,
        run_patch_fixes,
        log,
        **_phase_4_5_kwargs: object,
    ):
        # Simulate the unified executor calling run_patch_fixes with
        # both features. The Phase 3.5 guard inside run_patch_fixes
        # must skip the freeform one.
        captured_features.append([targeted, freeform])
        return await run_patch_fixes(
            patch_features=[targeted, freeform],
            fix_prd_path=tmp_path / "fix_prd.md",
            fix_prd_text="# fix",
            cwd=tmp_path,
            config=config,
            run_number=run_number,
        )

    finding = SimpleNamespace(
        finding_id="F-SKIP-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="skip test",
        evidence=["apps/web/page.tsx:1 -- skip"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/page.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(
        audit_team=SimpleNamespace(enabled=True),
        v18=SimpleNamespace(
            codex_fix_routing_enabled=False,
        ),
    )

    with patch("agent_team_v15.cli.ClaudeSDKClient", _StubClient), \
         patch("agent_team_v15.cli._build_options", return_value=object()), \
         patch.object(
             fix_mod,
             "execute_unified_fix_async",
             side_effect=_fake_execute_unified_fix_async,
         ):
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=str(tmp_path),
                task_text="task",
                depth="standard",
            )
        )

    # The targeted feature dispatched once; the freeform feature did NOT.
    assert len(sdk_invocations) == 1, (
        f"Expected exactly one SDK dispatch (the targeted feature); got "
        f"{len(sdk_invocations)}. Phase 3.5 must skip empty-target_files "
        "features to preserve audit-fix scope binding."
    )
    assert "targeted_fix" in sdk_invocations[0]


def test_run_patch_fixes_dispatches_targeted_features(tmp_path: Path) -> None:
    """Backward-compat: when ALL features have target_files declared,
    the loop dispatches each one. No regression on the happy path.
    """
    import asyncio

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    feature_a = {
        "name": "feature_a",
        "header": "F-FIX-001: feature_a",
        "block": "block A",
        "files_to_modify": ["apps/web/a.tsx"],
        "files_to_create": [],
        "execution_mode": "patch",
        "mode": "patch",
    }
    feature_b = {
        "name": "feature_b",
        "header": "F-FIX-002: feature_b",
        "block": "block B",
        "files_to_modify": ["apps/web/b.tsx"],
        "files_to_create": [],
        "execution_mode": "patch",
        "mode": "patch",
    }

    sdk_invocations: list[str] = []

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def query(self, prompt):
            sdk_invocations.append(prompt)

        async def receive_response(self):
            yield SimpleNamespace(content=[])

    async def _fake_execute_unified_fix_async(
        *,
        findings,
        original_prd_path,
        cwd,
        config,
        run_number,
        run_full_build,
        run_patch_fixes,
        log,
        **_phase_4_5_kwargs: object,
    ):
        return await run_patch_fixes(
            patch_features=[feature_a, feature_b],
            fix_prd_path=tmp_path / "fix_prd.md",
            fix_prd_text="# fix",
            cwd=tmp_path,
            config=config,
            run_number=run_number,
        )

    finding = SimpleNamespace(
        finding_id="F-OK-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="ok",
        evidence=["apps/web/a.tsx:1 -- ok"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/a.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(
        audit_team=SimpleNamespace(enabled=True),
        v18=SimpleNamespace(codex_fix_routing_enabled=False),
    )

    with patch("agent_team_v15.cli.ClaudeSDKClient", _StubClient), \
         patch("agent_team_v15.cli._build_options", return_value=object()), \
         patch.object(
             fix_mod,
             "execute_unified_fix_async",
             side_effect=_fake_execute_unified_fix_async,
         ):
        import asyncio as _asyncio
        modified, cost = _asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=str(tmp_path),
                task_text="task",
                depth="standard",
            )
        )

    assert len(sdk_invocations) == 2, (
        f"Both targeted features must dispatch; got {len(sdk_invocations)} "
        "dispatches"
    )


# ---------------------------------------------------------------------------
# Path C (verification): the parent's per-feature env vars are restored to
# their prior values so the subprocess started by ``_run_full_build`` does
# not inherit a stale finding scope. The inner builder runs its OWN
# audit-fix scope binding inside the subprocess (Phase 3 settings.json
# writer + per-feature env vars) — this is the cleanest fix per the
# handoff §4.3 C.1.
# ---------------------------------------------------------------------------


def test_run_patch_fixes_restores_prior_env_after_dispatch(tmp_path: Path) -> None:
    """The try/finally invariant: AGENT_TEAM_FINDING_ID and
    AGENT_TEAM_ALLOWED_PATHS must be restored to their pre-iteration
    state after each per-feature dispatch. If the parent calls
    ``_run_full_build`` after ``_run_patch_fixes``, the subprocess
    inherits clean env (Path C verification).

    This is the test that fails LOUD if a future refactor strips the
    try/finally — letting per-feature scope leak into the full-build
    subprocess and silently re-scoping its inner waves.
    """
    import asyncio

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    # Parent baseline: env vars unset (the realistic state outside an
    # audit-fix per-feature loop).
    os.environ.pop("AGENT_TEAM_FINDING_ID", None)
    os.environ.pop("AGENT_TEAM_ALLOWED_PATHS", None)

    feature = {
        "name": "feature_x",
        "header": "F-FIX-001: feature_x",
        "block": "block X",
        "files_to_modify": ["apps/web/x.tsx"],
        "files_to_create": [],
        "execution_mode": "patch",
        "mode": "patch",
    }

    env_during_dispatch: dict[str, str | None] = {}

    class _CaptureClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def query(self, prompt):
            env_during_dispatch["AGENT_TEAM_FINDING_ID"] = os.environ.get(
                "AGENT_TEAM_FINDING_ID"
            )
            env_during_dispatch["AGENT_TEAM_ALLOWED_PATHS"] = os.environ.get(
                "AGENT_TEAM_ALLOWED_PATHS"
            )

        async def receive_response(self):
            yield SimpleNamespace(content=[])

    async def _fake_execute_unified_fix_async(
        *,
        findings,
        original_prd_path,
        cwd,
        config,
        run_number,
        run_full_build,
        run_patch_fixes,
        log,
        **_phase_4_5_kwargs: object,
    ):
        return await run_patch_fixes(
            patch_features=[feature],
            fix_prd_path=tmp_path / "fix_prd.md",
            fix_prd_text="# fix",
            cwd=tmp_path,
            config=config,
            run_number=run_number,
        )

    finding = SimpleNamespace(
        finding_id="F-ENV-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="env",
        evidence=["apps/web/x.tsx:1 -- env"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/x.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(
        audit_team=SimpleNamespace(enabled=True),
        v18=SimpleNamespace(codex_fix_routing_enabled=False),
    )

    with patch("agent_team_v15.cli.ClaudeSDKClient", _CaptureClient), \
         patch("agent_team_v15.cli._build_options", return_value=object()), \
         patch.object(
             fix_mod,
             "execute_unified_fix_async",
             side_effect=_fake_execute_unified_fix_async,
         ):
        asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=str(tmp_path),
                task_text="task",
                depth="standard",
            )
        )

    # During the dispatch, the env was set.
    assert env_during_dispatch["AGENT_TEAM_FINDING_ID"], (
        "Phase 3 invariant: per-feature dispatch must set "
        "AGENT_TEAM_FINDING_ID for the audit-fix path-guard hook to scope"
    )

    # AFTER _run_patch_fixes completes, env must be restored to its
    # pre-iteration state (None / unset). If this fails, Path C scope
    # leaks into _run_full_build's subprocess.
    assert os.environ.get("AGENT_TEAM_FINDING_ID") is None, (
        "Phase 3.5 / Path C: AGENT_TEAM_FINDING_ID leaked past "
        "_run_patch_fixes. The full-build subprocess would inherit the "
        "parent's last-feature scope, silently re-scoping inner waves."
    )
    assert os.environ.get("AGENT_TEAM_ALLOWED_PATHS") is None, (
        "Phase 3.5 / Path C: AGENT_TEAM_ALLOWED_PATHS leaked past "
        "_run_patch_fixes. Same risk as above."
    )
