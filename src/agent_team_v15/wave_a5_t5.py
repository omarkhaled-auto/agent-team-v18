"""Wave A.5 (plan review) + Wave T.5 (test-gap audit) — Codex NEW waves.

Phase G Slice 4. Both waves route to Codex and are gated OFF by default
(`v18.wave_a5_enabled` / `v18.wave_t5_enabled`). The dispatcher in
``wave_executor._execute_milestone_waves_with_stack_contract`` inserts
``elif wave_letter == "A5":`` / ``"T5":`` branches that call the
``execute_wave_a5`` / ``execute_wave_t5`` helpers defined here.

Output contracts follow investigation report §4.8 / §4.9. Both helpers
persist their artifacts under
``.agent-team/milestones/{id}/WAVE_A5_REVIEW.json`` and
``.agent-team/milestones/{id}/WAVE_T5_GAPS.json`` respectively. The
orchestrator's GATE 8/9 enforcement (``cli._enforce_wave_gate`` + the
``GateEnforcementError`` in ``cli.py``) reads those artifacts to decide
whether to re-run Wave A / loop back to Wave T iteration 2.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strict JSON schemas (Codex SDK output_schema — §4.8 / §4.9).
# Embedded in the prompts so the Codex exec transport (which does not
# accept output_schema natively) still pins the response shape.
# ---------------------------------------------------------------------------

WAVE_A5_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["PASS", "FAIL", "UNCERTAIN"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "enum": [
                            "missing_endpoint",
                            "wrong_relationship",
                            "state_machine_gap",
                            "unrealistic_scope",
                            "spec_contradiction",
                            "missing_migration",
                            "uncertain",
                        ]
                    },
                    "severity": {"enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                    "ref": {"type": "string"},
                    "issue": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                },
                "required": [
                    "category",
                    "severity",
                    "ref",
                    "issue",
                    "suggested_fix",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "findings"],
    "additionalProperties": False,
}


WAVE_T5_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_file": {"type": "string"},
                    "source_symbol": {"type": "string"},
                    "ac_id": {"type": ["string", "null"]},
                    "category": {
                        "enum": [
                            "missing_edge_case",
                            "weak_assertion",
                            "untested_business_rule",
                            "uncertain",
                        ]
                    },
                    "severity": {"enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                    "missing_case": {"type": "string"},
                    "suggested_assertion": {"type": "string"},
                },
                "required": [
                    "test_file",
                    "source_symbol",
                    "ac_id",
                    "category",
                    "severity",
                    "missing_case",
                    "suggested_assertion",
                ],
                "additionalProperties": False,
            },
        },
        "files_read": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["gaps", "files_read"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Small helpers (text/file IO + heuristics)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_text_safely(path: Path, max_bytes: int = 60000) -> str:
    try:
        data = path.read_bytes()
    except (OSError, PermissionError):
        return ""
    if len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def _count_ac_bullets(requirements_text: str) -> int:
    """Rough count of AC-line bullets (skip-condition heuristic)."""
    count = 0
    for line in (requirements_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith(("- AC-", "* AC-", "AC-", "- [ ] AC-", "- [X] AC-")):
            count += 1
    return count


def _count_entity_candidates(plan_text: str) -> int:
    """Very rough entity-mention counter (skip-condition heuristic only)."""
    count = 0
    for line in (plan_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("### entity", "## entity", "- entity:", "* entity:")):
            count += 1
        elif lowered.startswith("entities:") or "@entity" in lowered:
            count += 1
    return count


def wave_a5_should_skip(
    *,
    config: Any,
    milestone: Any,
    template: str,
    plan_text: str,
    requirements_text: str,
) -> tuple[bool, str]:
    """Return (skip, reason) per investigation report §4.8 skip conditions."""
    v18 = getattr(config, "v18", None)
    if not getattr(v18, "wave_a5_enabled", False):
        return True, "wave_a5_enabled=False"
    if (template or "").strip().lower() == "frontend_only":
        return True, "template=frontend_only"
    complexity = str(getattr(milestone, "complexity", "") or "").strip().lower()
    if complexity == "simple":
        return True, "milestone.complexity=simple"
    if getattr(v18, "wave_a5_skip_simple_milestones", True):
        ent_threshold = int(getattr(v18, "wave_a5_simple_entity_threshold", 3))
        ac_threshold = int(getattr(v18, "wave_a5_simple_ac_threshold", 5))
        entity_count = _count_entity_candidates(plan_text)
        ac_count = _count_ac_bullets(requirements_text)
        if entity_count < ent_threshold and ac_count < ac_threshold:
            return True, (
                f"simple milestone: entities={entity_count} "
                f"< {ent_threshold} and acs={ac_count} < {ac_threshold}"
            )
    return False, ""


def _milestone_dir(cwd: str, milestone_id: str) -> Path:
    path = Path(cwd) / ".agent-team" / "milestones" / (milestone_id or "unknown")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_codex_json_output(raw: str) -> dict[str, Any] | None:
    """Extract the largest valid JSON object from a Codex final_message blob."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.lstrip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    last_open = text.rfind("{")
    last_close = text.rfind("}")
    if last_open == -1 or last_close == -1 or last_close < last_open:
        return None
    snippet = text[last_open : last_close + 1]
    try:
        return json.loads(snippet)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Prompt builders (verbatim text per §4.8 / §4.9 with the strict JSON Schema
# embedded inside the prompt body since the exec transport does not accept
# a separate output_schema parameter).
# ---------------------------------------------------------------------------


def build_wave_a5_prompt(
    *,
    plan_text: str,
    requirements_text: str,
    architecture_text: str,
) -> str:
    """Codex-style plan-review prompt (investigation report §4.8 / Part 5.2)."""
    arch_block = architecture_text.strip() or "(none — this is milestone M1)"
    schema_json = json.dumps(WAVE_A5_OUTPUT_SCHEMA, indent=2)
    return (
        "You are a strict plan reviewer. You flag gaps; you do not write new plans.\n"
        "\n"
        "<rules>\n"
        "- Emit findings ONLY for:\n"
        "  (a) missing endpoints implied by ACs but not in the plan,\n"
        "  (b) wrong entity relationships,\n"
        "  (c) state-machine gaps (status transitions),\n"
        "  (d) unrealistic scope for one milestone,\n"
        "  (e) PRD/requirements contradictions.\n"
        "- Every finding cites a file or plan-section reference.\n"
        "- Relative paths only.\n"
        "- Do NOT propose a new plan. Only flag gaps.\n"
        "- If the plan is consistent with the PRD, return "
        '{"verdict":"PASS","findings":[]}.\n'
        "</rules>\n"
        "\n"
        "<missing_context_gating>\n"
        "- If you would need to guess at intent, return a finding labelled UNCERTAIN\n"
        "  with the assumption you would have made.\n"
        "</missing_context_gating>\n"
        "\n"
        "<architecture>\n"
        f"{arch_block}\n"
        "</architecture>\n"
        "\n"
        "<plan>\n"
        f"{plan_text}\n"
        "</plan>\n"
        "\n"
        "<requirements>\n"
        f"{requirements_text}\n"
        "</requirements>\n"
        "\n"
        "Return JSON matching output_schema:\n"
        f"{schema_json}\n"
        "\n"
        "Final assistant message MUST be the JSON object only — no prose wrapper.\n"
    )


def build_wave_t5_prompt(
    *,
    test_files: list[tuple[str, str]],
    source_files: list[tuple[str, str]],
    acceptance_criteria: str,
) -> str:
    """Codex-style test-gap auditor prompt (investigation report §4.9 / Part 5.6)."""
    schema_json = json.dumps(WAVE_T5_OUTPUT_SCHEMA, indent=2)
    tests_block = (
        "\n".join(f"=== {rel} ===\n{body}" for rel, body in test_files)
        or "(no test files detected)"
    )
    source_block = (
        "\n".join(f"=== {rel} ===\n{body}" for rel, body in source_files)
        or "(no source files inlined — read them via the tool)"
    )
    return (
        "You are a test-gap auditor. You find missing edge cases in existing tests.\n"
        "You do NOT write new tests — you describe what is missing.\n"
        "\n"
        "<rules>\n"
        "- For each test file, identify: (a) missing edge cases, (b) weak\n"
        "  assertions, (c) untested business rules from the ACs.\n"
        "- Every gap cites {test_file, source_symbol, ac_id}.\n"
        "- Do not propose test code. Describe the assertion in prose.\n"
        "- Do NOT modify any file.\n"
        "- Relative paths only.\n"
        "</rules>\n"
        "\n"
        "<tool_persistence_rules>\n"
        "- Read the source file referenced by each test before concluding.\n"
        '- Read the ACs before flagging "missing business rule".\n'
        "- Do not stop on the first gap; scan every test.\n"
        "</tool_persistence_rules>\n"
        "\n"
        "<tests>\n"
        f"{tests_block}\n"
        "</tests>\n"
        "\n"
        "<source>\n"
        f"{source_block}\n"
        "</source>\n"
        "\n"
        "<acs>\n"
        f"{acceptance_criteria}\n"
        "</acs>\n"
        "\n"
        "Return JSON matching output_schema:\n"
        f"{schema_json}\n"
        "\n"
        "Final assistant message MUST be the JSON object only — no prose wrapper.\n"
    )


# ---------------------------------------------------------------------------
# Test + source collection (Wave T.5 helpers).
# ---------------------------------------------------------------------------


_TEST_IMPORT_RE = re.compile(r"""from\s+['\"]([^'\"]+)['\"]""")


def collect_wave_t_test_files(
    cwd: str,
    wave_t_artifact: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    """Return (rel_path, body) pairs for Wave T's test files (best-effort)."""
    wave_t_artifact = wave_t_artifact or {}
    candidates: list[str] = []
    for key in ("files_created", "files_modified", "test_files", "written_tests"):
        for rel in wave_t_artifact.get(key, []) or []:
            rel_str = str(rel or "").strip()
            if not rel_str:
                continue
            lowered = rel_str.lower()
            if (
                ".spec.ts" in lowered
                or ".test.ts" in lowered
                or ".spec.tsx" in lowered
                or ".test.tsx" in lowered
                or "/tests/" in lowered
                or "/test/" in lowered
            ):
                candidates.append(rel_str)
    seen: set[str] = set()
    files: list[tuple[str, str]] = []
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        body = _read_text_safely(Path(cwd) / rel, max_bytes=12000)
        if body:
            files.append((rel, body))
        if len(files) >= 25:
            break
    return files


def collect_source_files_from_tests(
    cwd: str,
    test_files: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Best-effort source-file extraction from relative test imports."""
    seen: set[str] = set()
    source_files: list[tuple[str, str]] = []
    for test_rel, body in test_files:
        for m in _TEST_IMPORT_RE.finditer(body or ""):
            mod = m.group(1)
            if not mod.startswith((".", "..")):
                continue
            candidate_dir = Path(cwd) / Path(test_rel).parent
            candidate = (candidate_dir / mod).with_suffix(".ts")
            alt = (candidate_dir / mod).with_suffix(".tsx")
            for probe in (candidate, alt):
                try:
                    rel_posix = (
                        probe.resolve()
                        .relative_to(Path(cwd).resolve())
                        .as_posix()
                    )
                except (ValueError, OSError):
                    continue
                if rel_posix in seen:
                    continue
                seen.add(rel_posix)
                src_body = _read_text_safely(
                    Path(cwd) / rel_posix, max_bytes=12000
                )
                if src_body:
                    source_files.append((rel_posix, src_body))
                if len(source_files) >= 25:
                    return source_files
    return source_files


# ---------------------------------------------------------------------------
# Codex dispatch helper — shared by both waves.
# ---------------------------------------------------------------------------


async def _dispatch_codex(
    *,
    prompt: str,
    cwd: str,
    config: Any,
    reasoning_effort: str,
    provider_routing: Any | None,
) -> tuple[str, Any]:
    """Invoke codex exec transport with the given prompt.

    Returns ``(final_message, codex_result_obj_or_None)``. ``codex_result_obj``
    is the ``CodexResult`` dataclass instance the transport returned (or
    ``None`` when dispatch raised). Callers that need token/cost accounting
    use ``getattr`` on the returned object.
    """
    v18 = getattr(config, "v18", None)
    codex_transport_module = None
    codex_config_obj = None
    codex_home_path = None
    if provider_routing:
        codex_transport_module = provider_routing.get("codex_transport")
        codex_config_obj = provider_routing.get("codex_config")
        codex_home_path = provider_routing.get("codex_home")

    try:
        if codex_transport_module is None:
            from . import codex_transport as _default_codex  # lazy

            codex_transport_module = _default_codex
        if codex_config_obj is None:
            from .codex_transport import CodexConfig as _CodexConfig

            codex_config_obj = _CodexConfig(
                model=str(getattr(v18, "codex_model", "gpt-5.4")),
                timeout_seconds=int(getattr(v18, "codex_timeout_seconds", 1800)),
                max_retries=int(getattr(v18, "codex_max_retries", 1)),
                reasoning_effort=reasoning_effort,
                context7_enabled=bool(getattr(v18, "codex_context7_enabled", True)),
            )
        else:
            try:
                from dataclasses import replace as _dc_replace

                codex_config_obj = _dc_replace(
                    codex_config_obj, reasoning_effort=reasoning_effort
                )
            except TypeError:
                codex_config_obj = codex_config_obj
        codex_result = await codex_transport_module.execute_codex(
            prompt=prompt,
            cwd=cwd,
            config=codex_config_obj,
            codex_home=codex_home_path,
        )
        final_message = str(getattr(codex_result, "final_message", "") or "")
        return final_message, codex_result
    except Exception as exc:  # pragma: no cover - defensive dispatch guard
        from .codex_cli import CodexCliVersionDriftError

        if isinstance(exc, CodexCliVersionDriftError):
            raise
        logger.warning("Codex dispatch failed (reasoning=%s): %s", reasoning_effort, exc)
        return "", None


# ---------------------------------------------------------------------------
# Public entrypoints used by the dispatcher.
# ---------------------------------------------------------------------------


async def execute_wave_a5(
    *,
    milestone: Any,
    config: Any,
    cwd: str,
    template: str,
    wave_artifacts: dict[str, dict[str, Any]],
    provider_routing: Any | None = None,
) -> dict[str, Any]:
    """Execute Wave A.5 — plan review (Codex, reasoning_effort=medium).

    Returns a dict with shape::

        {
            "wave": "A5",
            "success": bool,
            "skipped": bool,
            "skip_reason": str,
            "verdict": "PASS" | "FAIL" | "UNCERTAIN" | "SKIPPED",
            "findings": [...],
            "critical_count": int,
            "artifact_path": str,
            "cost": float,
            "input_tokens": int,
            "output_tokens": int,
            "reasoning_tokens": int,
            "duration_seconds": float,
            "error_message": str,
        }

    The caller (``wave_executor``) lifts these fields onto a ``WaveResult``
    and updates ``wave_artifacts["A5"]`` with the persisted artifact dict.
    """
    start = datetime.now(timezone.utc)
    milestone_id = str(getattr(milestone, "id", "") or "")
    v18 = getattr(config, "v18", None)
    milestone_dir = _milestone_dir(cwd, milestone_id)
    review_path = milestone_dir / "WAVE_A5_REVIEW.json"

    out: dict[str, Any] = {
        "wave": "A5",
        "success": True,
        "skipped": False,
        "skip_reason": "",
        "verdict": "UNCERTAIN",
        "findings": [],
        "critical_count": 0,
        "artifact_path": "",
        "cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "duration_seconds": 0.0,
        "error_message": "",
    }

    wave_a_artifact = wave_artifacts.get("A") or {}
    plan_text = (
        wave_a_artifact.get("plan_text")
        or wave_a_artifact.get("final_message")
        or wave_a_artifact.get("summary")
        or ""
    )
    if not plan_text:
        files = list(wave_a_artifact.get("files_created") or [])
        snippets: list[str] = []
        for rel in files[:20]:
            snippet = _read_text_safely(Path(cwd) / rel, max_bytes=4000)
            if snippet:
                snippets.append(f"=== {rel} ===\n{snippet}")
        plan_text = "\n\n".join(snippets) or "(no Wave A plan text on disk)"

    requirements_text = _read_text_safely(
        Path(cwd) / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"
    )
    architecture_text = _read_text_safely(Path(cwd) / "ARCHITECTURE.md")

    skip, skip_reason = wave_a5_should_skip(
        config=config,
        milestone=milestone,
        template=template,
        plan_text=plan_text,
        requirements_text=requirements_text,
    )
    if skip:
        out.update(
            {
                "skipped": True,
                "skip_reason": skip_reason,
                "verdict": "SKIPPED",
            }
        )
        skip_artifact = {
            "milestone_id": milestone_id,
            "wave": "A5",
            "skipped": True,
            "skip_reason": skip_reason,
            "verdict": "SKIPPED",
            "findings": [],
            "timestamp": _now_iso(),
        }
        try:
            review_path.write_text(
                json.dumps(skip_artifact, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            out["artifact_path"] = str(review_path)
        except OSError as exc:
            logger.warning("Wave A.5 skip-artifact write failed: %s", exc)
        wave_artifacts["A5"] = skip_artifact
        out["duration_seconds"] = (
            datetime.now(timezone.utc) - start
        ).total_seconds()
        return out

    prompt = build_wave_a5_prompt(
        plan_text=plan_text,
        requirements_text=requirements_text,
        architecture_text=architecture_text,
    )
    reasoning_effort = str(
        getattr(v18, "wave_a5_reasoning_effort", "medium") or "medium"
    )
    final_message, codex_result = await _dispatch_codex(
        prompt=prompt,
        cwd=cwd,
        config=config,
        reasoning_effort=reasoning_effort,
        provider_routing=provider_routing,
    )
    if codex_result is not None:
        out["cost"] = float(getattr(codex_result, "cost_usd", 0.0) or 0.0)
        out["input_tokens"] = int(getattr(codex_result, "input_tokens", 0) or 0)
        out["output_tokens"] = int(getattr(codex_result, "output_tokens", 0) or 0)
        out["reasoning_tokens"] = int(
            getattr(codex_result, "reasoning_tokens", 0) or 0
        )
    else:
        out["success"] = False
        out["error_message"] = "Wave A.5 Codex dispatch failed"

    parsed = _parse_codex_json_output(final_message)
    if not isinstance(parsed, dict):
        parsed = {
            "verdict": "UNCERTAIN",
            "findings": [
                {
                    "category": "uncertain",
                    "severity": "LOW",
                    "ref": "wave_a5_t5.execute_wave_a5",
                    "issue": "Codex did not return a JSON object matching output_schema",
                    "suggested_fix": "Review Wave A.5 prompt/Codex output manually",
                }
            ],
        }
        if not out["error_message"]:
            out["error_message"] = "Wave A.5 Codex output not JSON"
    verdict = str(parsed.get("verdict", "UNCERTAIN") or "UNCERTAIN").upper()
    findings_list = list(parsed.get("findings") or [])
    critical_count = sum(
        1
        for f in findings_list
        if isinstance(f, dict) and str(f.get("severity", "")).upper() == "CRITICAL"
    )

    review_artifact = {
        "milestone_id": milestone_id,
        "wave": "A5",
        "verdict": verdict,
        "findings": findings_list,
        "critical_count": critical_count,
        "reasoning_effort": reasoning_effort,
        "codex_success": bool(
            getattr(codex_result, "success", False)
        ) if codex_result else False,
        "timestamp": _now_iso(),
    }
    try:
        review_path.write_text(
            json.dumps(review_artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        out["artifact_path"] = str(review_path)
    except OSError as exc:
        logger.warning("Wave A.5 review-artifact write failed: %s", exc)

    wave_artifacts["A5"] = review_artifact
    out["verdict"] = verdict
    out["findings"] = findings_list
    out["critical_count"] = critical_count
    out["duration_seconds"] = (datetime.now(timezone.utc) - start).total_seconds()
    return out


async def execute_wave_t5(
    *,
    milestone: Any,
    config: Any,
    cwd: str,
    wave_artifacts: dict[str, dict[str, Any]],
    provider_routing: Any | None = None,
) -> dict[str, Any]:
    """Execute Wave T.5 — test-gap audit (Codex, reasoning_effort=high).

    Returns a dict with shape::

        {
            "wave": "T5",
            "success": bool,
            "skipped": bool,
            "skip_reason": str,
            "gaps": [...],
            "files_read": [...],
            "critical_count": int,
            "artifact_path": str,
            "cost": float,
            "input_tokens": int,
            "output_tokens": int,
            "reasoning_tokens": int,
            "duration_seconds": float,
            "error_message": str,
        }
    """
    start = datetime.now(timezone.utc)
    milestone_id = str(getattr(milestone, "id", "") or "")
    v18 = getattr(config, "v18", None)
    milestone_dir = _milestone_dir(cwd, milestone_id)
    gaps_path = milestone_dir / "WAVE_T5_GAPS.json"

    out: dict[str, Any] = {
        "wave": "T5",
        "success": True,
        "skipped": False,
        "skip_reason": "",
        "gaps": [],
        "files_read": [],
        "critical_count": 0,
        "artifact_path": "",
        "cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "duration_seconds": 0.0,
        "error_message": "",
    }

    wave_t_artifact = wave_artifacts.get("T") or {}
    test_files = collect_wave_t_test_files(cwd, wave_t_artifact)

    if not getattr(v18, "wave_t5_enabled", False) or (
        getattr(v18, "wave_t5_skip_if_no_tests", True) and not test_files
    ):
        skip_reason = (
            "wave_t5_enabled=False"
            if not getattr(v18, "wave_t5_enabled", False)
            else "no test files from Wave T"
        )
        out.update({"skipped": True, "skip_reason": skip_reason})
        skip_artifact = {
            "milestone_id": milestone_id,
            "wave": "T5",
            "skipped": True,
            "skip_reason": skip_reason,
            "gaps": [],
            "files_read": [],
            "timestamp": _now_iso(),
        }
        try:
            gaps_path.write_text(
                json.dumps(skip_artifact, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            out["artifact_path"] = str(gaps_path)
        except OSError as exc:
            logger.warning("Wave T.5 skip-artifact write failed: %s", exc)
        wave_artifacts["T5"] = skip_artifact
        out["duration_seconds"] = (
            datetime.now(timezone.utc) - start
        ).total_seconds()
        return out

    source_files = collect_source_files_from_tests(cwd, test_files)
    acceptance_criteria = _read_text_safely(
        Path(cwd) / ".agent-team" / "milestones" / milestone_id / "REQUIREMENTS.md"
    )
    prompt = build_wave_t5_prompt(
        test_files=test_files,
        source_files=source_files,
        acceptance_criteria=acceptance_criteria,
    )
    reasoning_effort = str(
        getattr(v18, "wave_t5_reasoning_effort", "high") or "high"
    )
    final_message, codex_result = await _dispatch_codex(
        prompt=prompt,
        cwd=cwd,
        config=config,
        reasoning_effort=reasoning_effort,
        provider_routing=provider_routing,
    )
    if codex_result is not None:
        out["cost"] = float(getattr(codex_result, "cost_usd", 0.0) or 0.0)
        out["input_tokens"] = int(getattr(codex_result, "input_tokens", 0) or 0)
        out["output_tokens"] = int(getattr(codex_result, "output_tokens", 0) or 0)
        out["reasoning_tokens"] = int(
            getattr(codex_result, "reasoning_tokens", 0) or 0
        )
    else:
        out["success"] = False
        out["error_message"] = "Wave T.5 Codex dispatch failed"

    parsed = _parse_codex_json_output(final_message)
    if not isinstance(parsed, dict):
        out["success"] = False
        parsed = {"gaps": [], "files_read": []}
        if not out["error_message"]:
            out["error_message"] = "Wave T.5 Codex output not JSON"
    gaps = list(parsed.get("gaps") or [])
    files_read = list(parsed.get("files_read") or [])
    critical_gap_count = sum(
        1
        for g in gaps
        if isinstance(g, dict) and str(g.get("severity", "")).upper() == "CRITICAL"
    )

    gaps_artifact = {
        "milestone_id": milestone_id,
        "wave": "T5",
        "gaps": gaps,
        "files_read": files_read,
        "critical_count": critical_gap_count,
        "reasoning_effort": reasoning_effort,
        "codex_success": bool(
            getattr(codex_result, "success", False)
        ) if codex_result else False,
        "timestamp": _now_iso(),
    }
    try:
        gaps_path.write_text(
            json.dumps(gaps_artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        out["artifact_path"] = str(gaps_path)
    except OSError as exc:
        logger.warning("Wave T.5 gaps-artifact write failed: %s", exc)

    wave_artifacts["T5"] = gaps_artifact
    out["gaps"] = gaps
    out["files_read"] = files_read
    out["critical_count"] = critical_gap_count
    out["duration_seconds"] = (datetime.now(timezone.utc) - start).total_seconds()
    return out


__all__ = [
    "WAVE_A5_OUTPUT_SCHEMA",
    "WAVE_T5_OUTPUT_SCHEMA",
    "build_wave_a5_prompt",
    "build_wave_t5_prompt",
    "collect_source_files_from_tests",
    "collect_wave_t_test_files",
    "execute_wave_a5",
    "execute_wave_t5",
    "wave_a5_should_skip",
]
