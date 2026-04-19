"""Phase H1b — Wave 3B wiring invariants (structural tests).

These tests enforce the read-only assertions that wiring-verifier used
to certify the Wave 2A/2B deliveries. They live in the regular pytest
suite so CI catches accidental regressions to the invariants:

- 4F: no mutable module-level retry state in the new schema modules.
- 4G: ``build_wave_a_prompt`` renders no unsubstituted ``{placeholder}``
  tokens regardless of schema-enforcement flag state.
- 4H: ``_enforce_gate_wave_a_schema`` mirrors ``_enforce_gate_a5``'s
  kw-only signature + raises ``GateEnforcementError`` on exhaustion.
- 4I: the eight static auditor-prompt string constants + the
  ``AUDIT_PROMPTS`` dict literal stay byte-identical against
  ``integration-2026-04-15-closeout`` (the Wave 2B constraint).

The tests use only the stdlib + pytest + project imports — no external
dependencies. 4I's git-diff assertion falls back to a skip when the
project is not a git clone (e.g., released wheel).
"""

from __future__ import annotations

import inspect
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import wave_a_schema, wave_a_schema_validator
from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.cli import (
    GateEnforcementError,
    _enforce_gate_a5,
    _enforce_gate_wave_a_schema,
    _format_schema_rejection_feedback,
    _get_effective_wave_a_rerun_budget,
)
from agent_team_v15.config import AgentTeamConfig


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REF = "integration-2026-04-15-closeout"


# ---------------------------------------------------------------------------
# 4F — No mutable module-level state in the new schema modules
# ---------------------------------------------------------------------------


def _module_level_assignments(path: Path) -> list[tuple[int, str]]:
    """Return ``[(line_no, identifier), ...]`` for top-level ``NAME = ...``.

    Only flags assignments at column 0 whose identifier is an all-caps or
    single-leading-underscore name. Regex / tuple / frozenset values are
    still returned — the caller decides mutability.
    """
    results: list[tuple[int, str]] = []
    pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=")
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = pattern.match(line)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("__"):
            continue
        results.append((i, name))
    return results


def test_wave_a_schema_module_no_mutable_globals() -> None:
    """``wave_a_schema.py`` holds ONLY ``Final[...]`` constants."""
    path = REPO_ROOT / "src" / "agent_team_v15" / "wave_a_schema.py"
    assignments = _module_level_assignments(path)
    assert assignments, "expected module-level constants in wave_a_schema"
    body = path.read_text(encoding="utf-8")
    for line_no, name in assignments:
        line = body.splitlines()[line_no - 1]
        # Tolerate Final[...] annotations and frozenset literals; reject
        # bare list/dict/set assignments (those can mutate).
        assert (
            "Final[" in line
            or line.strip().startswith("from ")
            or line.strip().startswith("import ")
        ), (
            f"{path.name}:{line_no} — {name!r} is not Final[...]; "
            "module-level mutable state is forbidden (4F)."
        )


def test_wave_a_schema_validator_module_no_mutable_globals() -> None:
    """``wave_a_schema_validator.py`` has only regex pattern constants."""
    path = REPO_ROOT / "src" / "agent_team_v15" / "wave_a_schema_validator.py"
    body = path.read_text(encoding="utf-8")
    # Every top-level assignment should be a compiled regex (re.compile(...))
    # or an import/dataclass definition. Any bare `_FOO = []` or similar
    # rejected.
    forbidden_shapes = (
        re.compile(r"^_[A-Z_]+\s*(?::[^=]+)?=\s*(?:\[|\{[^:])", re.MULTILINE),
        re.compile(r"^_[a-z_]+\s*(?::[^=]+)?=\s*(?:\[|\{[^:])", re.MULTILINE),
    )
    for pattern in forbidden_shapes:
        hits = pattern.findall(body)
        assert not hits, (
            f"{path.name} contains mutable module-level state {hits!r}; "
            "use a local variable or a Final constant instead (4F)."
        )


# ---------------------------------------------------------------------------
# 4G — No unsubstituted placeholders in ``build_wave_a_prompt`` output
# ---------------------------------------------------------------------------


def _fixture_milestone(milestone_id: str = "milestone-1") -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Users",
        template="full_stack",
        description="wiring invariants fixture milestone",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _fixture_ir() -> dict[str, object]:
    return {
        "entities": [
            {
                "name": "User",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "email", "type": "string"},
                ],
            }
        ],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _fixture_config(
    *,
    architecture_md_enabled: bool,
    wave_a_schema_enforcement_enabled: bool,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.architecture_md_enabled = architecture_md_enabled
    cfg.v18.wave_a_schema_enforcement_enabled = wave_a_schema_enforcement_enabled
    return cfg


_UNSUB_BRACE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_UNSUB_DOLLAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_UNSUB_INJECT = re.compile(r"<inject:[A-Za-z_][A-Za-z0-9_]*>")


def _assert_no_unsubstituted(prompt: str, *, label: str) -> None:
    # Strip fenced code blocks — legitimate example placeholders live in
    # teaching snippets and must NOT be matched.
    stripped = re.sub(r"```[\s\S]*?```", "", prompt)
    # Strip single-line backtick-fenced examples similarly.
    stripped = re.sub(r"`[^`]*`", "", stripped)
    for pattern in (_UNSUB_BRACE, _UNSUB_DOLLAR, _UNSUB_INJECT):
        matches = pattern.findall(stripped)
        assert not matches, (
            f"{label}: unsubstituted placeholder(s) {matches!r} leaked into "
            "the rendered Wave A prompt (4G)."
        )


@pytest.mark.parametrize(
    "schema_flag,arch_flag",
    [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_build_wave_a_prompt_no_unsubstituted_placeholders(
    schema_flag: bool, arch_flag: bool
) -> None:
    prompt = build_wave_a_prompt(
        milestone=_fixture_milestone(),
        ir=_fixture_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_fixture_config(
            architecture_md_enabled=arch_flag,
            wave_a_schema_enforcement_enabled=schema_flag,
        ),
        existing_prompt_framework="WAVE-A FRAMEWORK TEST FIXTURE",
    )
    _assert_no_unsubstituted(
        prompt,
        label=f"schema_flag={schema_flag} arch_flag={arch_flag}",
    )


# ---------------------------------------------------------------------------
# 4H — Gate-enforcement signature mirror + GateEnforcementError on exhaustion
# ---------------------------------------------------------------------------


def test_gate_wave_a_schema_signature_mirrors_gate_a5() -> None:
    """Parameter names, kinds, and ordering must match 1:1."""
    sig_a5 = inspect.signature(_enforce_gate_a5)
    sig_schema = inspect.signature(_enforce_gate_wave_a_schema)
    assert list(sig_a5.parameters) == list(sig_schema.parameters)
    for name in sig_a5.parameters:
        a5_param = sig_a5.parameters[name]
        sch_param = sig_schema.parameters[name]
        assert a5_param.kind == sch_param.kind, (
            f"param {name!r}: a5={a5_param.kind!r} vs schema={sch_param.kind!r}"
        )


def test_gate_wave_a_schema_returns_two_tuple() -> None:
    """Both gates return a 2-tuple ``(bool, <findings>)``."""
    sig_schema = inspect.signature(_enforce_gate_wave_a_schema)
    # tuple[bool, dict[str, Any]] — second element differs from a5 by
    # intent (schema returns a review dict; a5 returns findings list).
    return_text = str(sig_schema.return_annotation)
    assert "tuple[bool" in return_text or "Tuple[bool" in return_text, (
        f"schema gate return annotation is not a 2-tuple: {return_text!r}"
    )


def test_gate_wave_a_schema_raises_gate_enforcement_error_on_exhaustion(
    tmp_path: Path,
) -> None:
    """When ``rerun_count >= budget`` AND findings exist, must raise."""
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_schema_enforcement_enabled = True
    cfg.v18.architecture_md_enabled = True
    cfg.v18.wave_a_rerun_budget = 1

    # Seed a failing ARCHITECTURE.md: out-of-scope section triggers
    # a CRITICAL schema finding.
    arch_dir = tmp_path / ".agent-team" / "milestone-milestone-1"
    arch_dir.mkdir(parents=True)
    (arch_dir / "ARCHITECTURE.md").write_text(
        "## Technology Stack\n\nStack restated here (forbidden).\n",
        encoding="utf-8",
    )

    with pytest.raises(GateEnforcementError) as exc_info:
        _enforce_gate_wave_a_schema(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=1,  # budget exhausted
        )
    assert exc_info.value.gate == "A-SCHEMA"
    assert exc_info.value.milestone_id == "milestone-1"


def test_get_effective_wave_a_rerun_budget_reads_canonical_key() -> None:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_rerun_budget = 3
    assert _get_effective_wave_a_rerun_budget(cfg) == 3


def test_format_schema_rejection_feedback_emits_block_header() -> None:
    """The feedback renderer emits ``[SCHEMA FEEDBACK]`` so the Wave A
    prompt's ``[PRIOR ATTEMPT REJECTED]`` channel carries it."""
    review = {
        "verdict": "FAIL",
        "findings": [
            {
                "category": "schema_rejection",
                "ref": "## Technology Stack",
                "severity": "CRITICAL",
                "issue": "Stack must not be redeclared.",
            }
        ],
    }
    out = _format_schema_rejection_feedback(
        review, rerun_count=0, max_reruns=2
    )
    assert out.startswith("[SCHEMA FEEDBACK]")
    assert "Retry 1 of 2" in out
    assert "## Technology Stack" in out


# ---------------------------------------------------------------------------
# 4I — Static auditor-prompt constants stay byte-identical vs baseline
# ---------------------------------------------------------------------------


AUDIT_PROMPTS_STATIC_CONSTANTS = (
    "REQUIREMENTS_AUDITOR_PROMPT",
    "TECHNICAL_AUDITOR_PROMPT",
    "INTERFACE_AUDITOR_PROMPT",
    "TEST_AUDITOR_PROMPT",
    "MCP_LIBRARY_AUDITOR_PROMPT",
    "PRD_FIDELITY_AUDITOR_PROMPT",
    "COMPREHENSIVE_AUDITOR_PROMPT",
    "SCORER_AGENT_PROMPT",
)


def _git_available() -> bool:
    return shutil.which("git") is not None and (REPO_ROOT / ".git").is_dir()


def _git_show_file(ref: str, rel_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"git show {ref}:{rel_path} failed (baseline unavailable): "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    # Decode from bytes with explicit utf-8 so Windows cp1252 does not
    # mangle unicode characters (em-dash etc.) — the baseline file is
    # utf-8 on disk and HEAD is read as utf-8, so the comparison stays
    # byte-identical.
    return result.stdout.decode("utf-8", errors="strict")


def _extract_triple_quoted_constant(body: str, name: str) -> str | None:
    """Return the exact triple-quoted body of ``name = \"\"\"...\"\"\"`` or None."""
    pattern = re.compile(
        rf'^{re.escape(name)}\s*=\s*"""(.*?)"""',
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(body)
    if match is None:
        return None
    return match.group(1)


def _extract_dict_literal(body: str, name: str) -> str | None:
    pattern = re.compile(
        rf'^{re.escape(name)}\s*=\s*\{{(.*?)\n\}}',
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(body)
    if match is None:
        return None
    return match.group(1)


@pytest.mark.parametrize("constant", AUDIT_PROMPTS_STATIC_CONSTANTS)
def test_audit_prompt_constant_byte_identical_to_baseline(constant: str) -> None:
    if not _git_available():
        pytest.skip("git not available; skipping baseline diff assertion")
    rel = "src/agent_team_v15/audit_prompts.py"
    head_body = (REPO_ROOT / rel).read_text(encoding="utf-8")
    base_body = _git_show_file(BASELINE_REF, rel)
    head_value = _extract_triple_quoted_constant(head_body, constant)
    base_value = _extract_triple_quoted_constant(base_body, constant)
    assert head_value is not None, f"{constant} not found in HEAD audit_prompts.py"
    assert base_value is not None, f"{constant} not found in baseline audit_prompts.py"
    assert head_value == base_value, (
        f"{constant} changed vs {BASELINE_REF}; static prompt strings must "
        "stay byte-identical under H1b (4I)."
    )


def test_audit_prompts_registry_byte_identical_to_baseline() -> None:
    if not _git_available():
        pytest.skip("git not available; skipping baseline diff assertion")
    rel = "src/agent_team_v15/audit_prompts.py"
    head_body = (REPO_ROOT / rel).read_text(encoding="utf-8")
    base_body = _git_show_file(BASELINE_REF, rel)
    head_dict = _extract_dict_literal(head_body, "AUDIT_PROMPTS")
    base_dict = _extract_dict_literal(base_body, "AUDIT_PROMPTS")
    assert head_dict is not None, "AUDIT_PROMPTS dict not found in HEAD"
    assert base_dict is not None, "AUDIT_PROMPTS dict not found in baseline"
    assert head_dict == base_dict, (
        "AUDIT_PROMPTS registry changed vs "
        f"{BASELINE_REF}; the dict literal must stay byte-identical (4I)."
    )


# ---------------------------------------------------------------------------
# 4E — Pattern-id uniqueness sanity (no accidental WAVE-A-SCHEMA-ESCALATION-001)
# ---------------------------------------------------------------------------


def test_no_wave_a_schema_escalation_pattern_id_in_source() -> None:
    """Plan explicitly rejects a separate escalation pattern id — exhaustion
    goes through ``GateEnforcementError``, not a WAVE-A-SCHEMA-ESCALATION-001
    finding."""
    src_root = REPO_ROOT / "src" / "agent_team_v15"
    hits: list[Path] = []
    for path in src_root.rglob("*.py"):
        if "WAVE-A-SCHEMA-ESCALATION-001" in path.read_text(encoding="utf-8"):
            hits.append(path)
    assert not hits, (
        "forbidden pattern id WAVE-A-SCHEMA-ESCALATION-001 appears in "
        f"{[str(p) for p in hits]}; use GateEnforcementError instead."
    )


def test_wave_a_schema_pattern_ids_present() -> None:
    assert wave_a_schema.PATTERN_SECTION_REJECTION == "WAVE-A-SCHEMA-REJECTION-001"
    assert (
        wave_a_schema.PATTERN_UNDECLARED_REFERENCE
        == "WAVE-A-SCHEMA-UNDECLARED-REF-001"
    )
