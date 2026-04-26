"""Evidence Ledger - Typed evidence records for AC evaluation.

Phase 1: Record-only mode. Evidence records are created alongside evaluation
but do NOT gate PASS/FAIL decisions.

Phase 3: Evidence can become a soft gate.
Phase 3+: Evidence can become a hard gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

EVIDENCE_TYPES = {
    "code_span",
    "http_transcript",
    "playwright_trace",
    "db_assertion",
    "simulator_state",
    "log_excerpt",
}

VERDICTS = {"PASS", "PARTIAL", "FAIL", "UNVERIFIED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_evidence_type(value: str) -> str:
    value = str(value or "").strip()
    return value if value in EVIDENCE_TYPES else "code_span"


def _normalize_verdict(value: str) -> str:
    value = str(value or "").strip().upper()
    return value if value in VERDICTS else "UNVERIFIED"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _safe_filename(ac_id: str) -> str:
    """Sanitize an AC identifier for use as a filename on all platforms."""
    return re.sub(r'[<>:"/\\|?*]', "_", str(ac_id or "").strip())


@dataclass
class EvidenceRecord:
    type: str
    path: str = ""
    content: str = ""
    source: str = ""
    timestamp: str = ""


@dataclass
class ACEvidenceEntry:
    ac_id: str
    verdict: str = "UNVERIFIED"
    required_evidence: list[str] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    evaluator_notes: str = ""
    timestamp: str = ""
    # Phase 2 audit-fix-loop guardrail: test surface attached to this AC
    # at milestone COMPLETE-time. Used by run_regression_check to detect
    # cross-milestone lock violations (an M(N+1) audit-fix that breaks an
    # M(N) test).
    test_surface: list[str] = field(default_factory=list)
    # Phase 2: pass-rate captured at milestone COMPLETE; trend telemetry
    # for future M-class regression dashboards. Defaults to 100.0 because
    # a milestone reaching COMPLETE means its test surface was passing.
    pass_rate: float = 100.0


class EvidenceLedger:
    """Manages evidence records for a build."""

    def __init__(self, evidence_dir: Path):
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, ACEvidenceEntry] = {}

    def record_evidence(
        self,
        ac_id: str,
        evidence: EvidenceRecord,
        verdict: str = "UNVERIFIED",
        notes: str = "",
    ) -> None:
        """Add an evidence record for an AC."""
        ac_id = str(ac_id).strip()
        if not ac_id:
            return

        if ac_id not in self._entries:
            self._entries[ac_id] = ACEvidenceEntry(ac_id=ac_id, timestamp=_now_iso())

        entry = self._entries[ac_id]
        if not entry.timestamp:
            entry.timestamp = _now_iso()

        evidence.type = _normalize_evidence_type(evidence.type)
        if not evidence.timestamp:
            evidence.timestamp = _now_iso()
        entry.evidence.append(evidence)

        normalized_verdict = _normalize_verdict(verdict)
        if normalized_verdict != "UNVERIFIED":
            entry.verdict = normalized_verdict
        if notes:
            entry.evaluator_notes = notes

        self._save_entry(entry)

    def set_required_evidence(self, ac_id: str, required: list[str]) -> None:
        """Set required evidence types for an AC."""
        ac_id = str(ac_id).strip()
        if not ac_id:
            return

        if ac_id not in self._entries:
            self._entries[ac_id] = ACEvidenceEntry(ac_id=ac_id, timestamp=_now_iso())

        entry = self._entries[ac_id]
        entry.required_evidence = _dedupe_preserve_order([
            _normalize_evidence_type(item) for item in required
        ])
        self._save_entry(entry)

    def check_evidence_complete(self, ac_id: str) -> bool:
        """Return True when all required evidence types are present."""
        entry = self._entries.get(ac_id)
        if not entry or not entry.required_evidence:
            return False
        provided_types = {e.type for e in entry.evidence}
        return all(required in provided_types for required in entry.required_evidence)

    def get_entry(self, ac_id: str) -> Optional[ACEvidenceEntry]:
        return self._entries.get(ac_id)

    def record_milestone_baseline(
        self,
        milestone_id: str,
        ac_to_tests: dict[str, list[str]],
        pass_rate: float = 100.0,
    ) -> None:
        """Persist test_surface + pass_rate at milestone COMPLETE.

        Phase 2 audit-fix-loop guardrail. ``ac_to_tests`` maps each AC
        owned by ``milestone_id`` to its associated test files (relpaths
        from the project root). The verdict is bumped to PASS when the
        baseline is recorded — by definition, a milestone reaching
        COMPLETE means its tests are passing.
        """
        del milestone_id  # reserved for future per-milestone indexing
        for ac_id, tests in ac_to_tests.items():
            ac_id = str(ac_id).strip()
            if not ac_id:
                continue
            entry = self._entries.get(ac_id)
            if entry is None:
                entry = ACEvidenceEntry(ac_id=ac_id, timestamp=_now_iso())
                self._entries[ac_id] = entry
            normalized = [
                str(path).replace("\\", "/").strip()
                for path in (tests or [])
                if str(path).strip()
            ]
            seen: set[str] = set()
            entry.test_surface = [
                path for path in normalized
                if not (path in seen or seen.add(path))
            ]
            entry.pass_rate = float(pass_rate)
            if entry.verdict == "UNVERIFIED":
                entry.verdict = "PASS"
            self._save_entry(entry)

    def get_locked_test_surface(self) -> dict[str, list[str]]:
        """Return the cross-milestone lock surface.

        Each entry maps ``ac_id`` → list of test file paths that are
        locked against regression. Only PASS-verdict ACs contribute to
        the lock — ACs with FAIL/PARTIAL/UNVERIFIED verdict have nothing
        to protect.
        """
        return {
            ac_id: list(entry.test_surface)
            for ac_id, entry in self._entries.items()
            if entry.test_surface and entry.verdict == "PASS"
        }

    def evaluate_with_evidence_gate(
        self,
        ac_id: str,
        legacy_verdict: str,
        evidence_mode: str,
        collector_availability: dict[str, bool],
    ) -> str:
        """Apply evidence gating to a legacy AC verdict."""
        normalized_verdict = _normalize_verdict(legacy_verdict)
        if evidence_mode in ("disabled", "record_only"):
            return normalized_verdict

        entry = self.get_entry(ac_id)
        if not entry or not entry.required_evidence:
            return normalized_verdict

        if evidence_mode == "soft_gate":
            return self._apply_soft_gate(entry, normalized_verdict, collector_availability)
        if evidence_mode == "hard_gate":
            if not self._hard_gate_collectors_operational(entry, collector_availability):
                return self._apply_soft_gate(entry, normalized_verdict, collector_availability)
            return self._apply_hard_gate(entry, normalized_verdict, collector_availability)
        return normalized_verdict

    def _hard_gate_collectors_operational(
        self,
        entry: ACEvidenceEntry,
        availability: dict[str, bool],
    ) -> bool:
        """Hard gate activates only when this AC's required collectors are operational."""
        required_types = [
            required_type
            for required_type in entry.required_evidence
            if _normalize_evidence_type(required_type) != "code_span"
        ]
        if not required_types:
            return True
        return all(bool(availability.get(required_type, False)) for required_type in required_types)

    def _apply_soft_gate(
        self,
        entry: ACEvidenceEntry,
        legacy_verdict: str,
        availability: dict[str, bool],
    ) -> str:
        """Require evidence for available collectors and downgrade unavailable ones to UNVERIFIED."""
        if legacy_verdict != "PASS":
            return legacy_verdict

        provided_types = {_normalize_evidence_type(e.type) for e in entry.evidence}
        has_unavailable = False
        for required_type in entry.required_evidence:
            if availability.get(required_type, False):
                if required_type not in provided_types:
                    return "PARTIAL"
            else:
                has_unavailable = True

        if has_unavailable:
            return "UNVERIFIED"
        return legacy_verdict

    def _apply_hard_gate(
        self,
        entry: ACEvidenceEntry,
        legacy_verdict: str,
        availability: dict[str, bool],
    ) -> str:
        """Require all evidence types for PASS when hard gate is enabled."""
        del availability
        if legacy_verdict != "PASS":
            return legacy_verdict

        provided_types = {_normalize_evidence_type(e.type) for e in entry.evidence}
        for required_type in entry.required_evidence:
            if required_type not in provided_types:
                return "PARTIAL"
        return legacy_verdict

    def load_all(self) -> None:
        """Load all evidence entries from disk."""
        if not self.evidence_dir.exists():
            return

        for path in self.evidence_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue

            ac_id = str(data.get("ac_id", "")).strip()
            if not ac_id:
                continue

            entry = ACEvidenceEntry(
                ac_id=ac_id,
                verdict=_normalize_verdict(data.get("verdict", "UNVERIFIED")),
                required_evidence=_dedupe_preserve_order([
                    _normalize_evidence_type(item)
                    for item in data.get("required_evidence", [])
                    if isinstance(item, (str, int, float))
                ]),
                evidence=[
                    EvidenceRecord(
                        type=_normalize_evidence_type(e.get("type", "code_span")),
                        path=str(e.get("path", "")),
                        content=str(e.get("content", "")),
                        source=str(e.get("source", "")),
                        timestamp=str(e.get("timestamp", "")),
                    )
                    for e in data.get("evidence", [])
                    if isinstance(e, dict)
                ],
                evaluator_notes=str(data.get("evaluator_notes", "")),
                timestamp=str(data.get("timestamp", "")),
                test_surface=[
                    str(path).replace("\\", "/").strip()
                    for path in (data.get("test_surface") or [])
                    if isinstance(path, (str, int, float)) and str(path).strip()
                ],
                pass_rate=float(data.get("pass_rate", 100.0) or 100.0),
            )
            self._entries[entry.ac_id] = entry

    def _save_entry(self, entry: ACEvidenceEntry) -> None:
        path = self.evidence_dir / f"{_safe_filename(entry.ac_id)}.json"
        payload = {
            "ac_id": entry.ac_id,
            "verdict": _normalize_verdict(entry.verdict),
            "required_evidence": list(entry.required_evidence),
            "evidence": [
                {
                    "type": _normalize_evidence_type(e.type),
                    "path": e.path,
                    "content": e.content,
                    "source": e.source,
                    "timestamp": e.timestamp,
                }
                for e in entry.evidence
            ],
            "evaluator_notes": entry.evaluator_notes,
            "timestamp": entry.timestamp or _now_iso(),
            "test_surface": list(entry.test_surface),
            "pass_rate": float(entry.pass_rate),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_collector_availability(
    milestone_id: str,
    milestone_template: str,
    config: Any,
    cwd: str,
) -> dict[str, bool]:
    """Determine which evidence collectors produced output for this milestone."""
    available = {
        "code_span": True,
        "http_transcript": False,
        "playwright_trace": False,
        "db_assertion": False,
        "simulator_state": False,
        "log_excerpt": False,
    }

    live_endpoint_check = bool(_config_flag(config, "live_endpoint_check"))
    evidence_mode = str(_config_flag(config, "evidence_mode", "disabled")).strip().lower()
    evidence_dir = Path(cwd) / ".agent-team" / "evidence"
    milestone_ac_ids, scope_defined = _resolve_milestone_ac_scope(milestone_id, cwd)
    if not scope_defined:
        return available

    if live_endpoint_check and milestone_template != "frontend_only":
        if _milestone_has_evidence_of_type(evidence_dir, milestone_ac_ids, "http_transcript"):
            available["http_transcript"] = True
        if _milestone_has_evidence_of_type(evidence_dir, milestone_ac_ids, "db_assertion"):
            available["db_assertion"] = True

    if live_endpoint_check and _milestone_has_evidence_of_type(evidence_dir, milestone_ac_ids, "simulator_state"):
        available["simulator_state"] = True

    if evidence_mode in {"soft_gate", "hard_gate"} and milestone_template in {"full_stack", "frontend_only"}:
        if _milestone_has_evidence_of_type(evidence_dir, milestone_ac_ids, "playwright_trace"):
            available["playwright_trace"] = True

    return available


def _resolve_milestone_ac_scope(milestone_id: str, cwd: str) -> tuple[set[str], bool]:
    """Return milestone AC scope and whether the scope is explicitly defined."""
    normalized_id = str(milestone_id or "").strip()
    if not normalized_id:
        return set(), True

    plan_path = Path(cwd) / ".agent-team" / "MASTER_PLAN.json"
    if not plan_path.is_file():
        return set(), False

    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return set(), False

    for milestone in list(payload.get("milestones", []) or []):
        if str(milestone.get("id", "")).strip() != normalized_id:
            continue
        return (
            {
                str(ac_id).strip()
                for ac_id in list(milestone.get("ac_refs", []) or [])
                if str(ac_id).strip()
            },
            True,
        )
    return set(), False


def _milestone_has_evidence_of_type(
    evidence_dir: Path,
    milestone_ac_ids: set[str],
    evidence_type: str,
) -> bool:
    """Check whether this milestone produced evidence of the given type."""
    if not evidence_dir.exists():
        return False
    if not milestone_ac_ids:
        return False

    normalized_type = _normalize_evidence_type(evidence_type)
    for evidence_file in evidence_dir.glob("*.json"):
        try:
            payload = json.loads(evidence_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue

        ac_id = str(payload.get("ac_id", "")).strip()
        if ac_id not in milestone_ac_ids:
            continue

        evidence_list = list(payload.get("evidence", []) or [])
        if any(_normalize_evidence_type(item.get("type", "")) == normalized_type for item in evidence_list if isinstance(item, dict)):
            return True

    return False


def map_endpoint_to_acs(method: str, path: str, cwd: str) -> list[str]:
    """Map an endpoint to owning ACs using the product IR."""
    ir = _load_product_ir(cwd)
    if not ir:
        return []

    ac_ids: list[str] = []
    acceptance_criteria = list(ir.get("acceptance_criteria", []) or [])

    for ir_endpoint in list(ir.get("endpoints", []) or []):
        if str(ir_endpoint.get("method", "")).upper() != str(method).upper():
            continue
        if str(ir_endpoint.get("path", "")) != path:
            continue
        feature = str(ir_endpoint.get("owner_feature", "")).strip()
        if not feature:
            continue
        for ac in acceptance_criteria:
            if str(ac.get("feature", "")).strip() == feature:
                ac_id = str(ac.get("id", "")).strip()
                if ac_id:
                    ac_ids.append(ac_id)

    ac_ids = _dedupe_preserve_order(ac_ids)
    if ac_ids:
        return ac_ids

    path_segments = [
        segment.lower()
        for segment in str(path).split("/")
        if segment and not segment.startswith(":") and not segment.startswith("{")
    ]
    for ac in acceptance_criteria:
        ac_id = str(ac.get("id", "")).strip()
        ac_text = str(ac.get("text", "")).lower()
        if not ac_id:
            continue
        if any(segment in ac_text for segment in path_segments[-2:]):
            ac_ids.append(ac_id)

    return _dedupe_preserve_order(ac_ids)


def map_integration_to_acs(vendor: str, method_name: str, cwd: str) -> list[str]:
    """Map an integration simulator call to owning ACs using the product IR."""
    ir = _load_product_ir(cwd)
    if not ir:
        return []

    ac_ids: list[str] = []
    acceptance_criteria = list(ir.get("acceptance_criteria", []) or [])
    for integration in list(ir.get("integrations", []) or []):
        if str(integration.get("vendor", "")).lower() != str(vendor).lower():
            continue
        owner_feature = str(integration.get("owner_feature", "")).strip()
        integration_type = str(integration.get("type", "")).strip().lower()
        methods_used = {
            str(item).strip().lower()
            for item in list(integration.get("methods_used", []) or [])
        }
        for ac in acceptance_criteria:
            ac_id = str(ac.get("id", "")).strip()
            if not ac_id:
                continue
            if owner_feature and str(ac.get("feature", "")).strip() == owner_feature:
                ac_ids.append(ac_id)
                continue
            tags = [str(tag).lower() for tag in list(ac.get("tags", []) or [])]
            text = str(ac.get("text", "")).lower()
            if (
                (integration_type and integration_type in tags)
                or str(vendor).lower() in text
                or (str(method_name).lower() in methods_used and str(method_name).lower() in text)
            ):
                ac_ids.append(ac_id)
    return _dedupe_preserve_order(ac_ids)


def _load_product_ir(cwd: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    product_ir_dir = Path(cwd) / ".agent-team" / "product-ir"
    for ir_path in (product_ir_dir / "product.ir.json", product_ir_dir / "IR.json"):
        if not ir_path.is_file():
            continue
        try:
            parsed = json.loads(ir_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            data.update(parsed)
            break

    ac_path = Path(cwd) / ".agent-team" / "product-ir" / "acceptance-criteria.ir.json"
    if ac_path.is_file():
        try:
            parsed = json.loads(ac_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            data.setdefault("acceptance_criteria", parsed.get("acceptance_criteria", []))
        elif isinstance(parsed, list):
            data.setdefault("acceptance_criteria", parsed)

    return data


def _config_flag(config: Any, field_name: str, default: Any = False) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        if field_name in config:
            return config.get(field_name, default)
        v18 = config.get("v18")
        if isinstance(v18, dict):
            return v18.get(field_name, default)
        return default
    v18 = getattr(config, "v18", None)
    if v18 is not None and hasattr(v18, field_name):
        return getattr(v18, field_name)
    return getattr(config, field_name, default)


__all__ = [
    "ACEvidenceEntry",
    "EvidenceLedger",
    "EvidenceRecord",
    "map_endpoint_to_acs",
    "map_integration_to_acs",
    "resolve_collector_availability",
]
