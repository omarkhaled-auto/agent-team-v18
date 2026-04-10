"""Automated checkpoint gates for convergence enforcement.

Provides code-level gate checks that BLOCK phase progression unless
verification conditions are met. Gates replace prompt-level instructions
(agents.py Section 3) with Python-enforced constraints that cannot be
bypassed by the LLM.

Each gate produces a GateResult for audit trail purposes. When a gate
fails and enforcement is active, a GateViolationError is raised.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentTeamConfig
from .state import RunState


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GateViolationError(Exception):
    """Raised when a checkpoint gate condition is not met and enforcement is active."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Outcome of a single gate check."""

    gate_id: str          # e.g. "GATE_REQUIREMENTS"
    gate_name: str        # Human-readable name
    passed: bool
    reason: str           # Why it passed or failed
    timestamp: str = ""   # ISO 8601
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Gate mode
# ---------------------------------------------------------------------------

class GateMode:
    """Controls whether gates block or only warn."""
    ENFORCING = "enforcing"      # Raises GateViolationError on failure
    INFORMATIONAL = "informational"  # Logs warning, does not raise


# ---------------------------------------------------------------------------
# GateEnforcer
# ---------------------------------------------------------------------------

class GateEnforcer:
    """Enforces convergence gates as code-level checks.

    Instantiated once after config loading. Each enforce_* method:
    1. Checks the condition
    2. Records a GateResult in the audit trail
    3. Writes to GATE_AUDIT.log
    4. If mode is ENFORCING and condition fails: raises GateViolationError
    5. If mode is INFORMATIONAL and condition fails: logs warning, returns result

    Args:
        config: The loaded AgentTeamConfig.
        state: The current RunState.
        project_root: Path to the project directory.
        gates_enabled: Master switch. When False, all gates are INFORMATIONAL.
    """

    def __init__(
        self,
        config: AgentTeamConfig,
        state: RunState,
        project_root: Path,
        gates_enabled: bool = True,
    ) -> None:
        self._config = config
        self._state = state
        self._project_root = project_root
        self._gates_enabled = gates_enabled
        self._audit_trail: list[GateResult] = []
        self._req_dir = project_root / config.convergence.requirements_dir
        self._mode = GateMode.ENFORCING if gates_enabled else GateMode.INFORMATIONAL

    # -- Gate 1: REQUIREMENTS -------------------------------------------

    def enforce_requirements_exist(self) -> GateResult:
        """GATE_REQUIREMENTS: .agent-team/REQUIREMENTS.md exists and has >= 1 REQ item."""
        req_path = self._req_dir / self._config.convergence.requirements_file
        if not req_path.is_file():
            return self._record(
                "GATE_REQUIREMENTS",
                "Requirements Document Exists",
                False,
                f"REQUIREMENTS.md not found at {req_path}",
                {"path": str(req_path)},
            )
        content = req_path.read_text(encoding="utf-8")
        req_items = re.findall(r"^- \[[ x]\] (REQ|TECH|INT|WIRE|SVC|DESIGN)-\d+", content, re.MULTILINE)
        if len(req_items) < 1:
            return self._record(
                "GATE_REQUIREMENTS",
                "Requirements Document Exists",
                False,
                f"REQUIREMENTS.md exists but contains 0 requirement items",
                {"path": str(req_path), "item_count": 0},
            )
        return self._record(
            "GATE_REQUIREMENTS",
            "Requirements Document Exists",
            True,
            f"REQUIREMENTS.md found with {len(req_items)} requirement items",
            {"path": str(req_path), "item_count": len(req_items)},
        )

    # -- Gate 2: ARCHITECTURE -------------------------------------------

    def enforce_architecture_exists(self) -> GateResult:
        """GATE_ARCHITECTURE: Architecture section exists in REQUIREMENTS.md."""
        req_path = self._req_dir / self._config.convergence.requirements_file
        if not req_path.is_file():
            return self._record(
                "GATE_ARCHITECTURE",
                "Architecture Section Exists",
                False,
                "REQUIREMENTS.md not found — cannot check architecture section",
                {"path": str(req_path)},
            )
        content = req_path.read_text(encoding="utf-8")
        has_arch = bool(re.search(r"^##\s+Architecture\s+Decision", content, re.MULTILINE | re.IGNORECASE))
        has_roadmap = bool(re.search(r"^##\s+Integration\s+Roadmap", content, re.MULTILINE | re.IGNORECASE))
        passed = has_arch or has_roadmap
        return self._record(
            "GATE_ARCHITECTURE",
            "Architecture Section Exists",
            passed,
            "Architecture section found" if passed else "No Architecture Decision or Integration Roadmap section in REQUIREMENTS.md",
            {"has_architecture_decision": has_arch, "has_integration_roadmap": has_roadmap},
        )

    # -- Gate 3: PSEUDOCODE (integrates with Feature #1) ----------------

    def enforce_pseudocode_exists(self) -> GateResult:
        """GATE_PSEUDOCODE: Pseudocode files exist for tasks.

        Checks for .agent-team/pseudocode/ directory or PSEUDOCODE.md.
        This gate integrates with Feature #1 (Pseudocode Stage).
        When pseudocode is enabled in config, this gate enforces (blocks).
        When pseudocode is disabled, the gate is informational only.
        """
        pseudo_dir = self._req_dir / "pseudocode"
        pseudo_file = self._req_dir / "PSEUDOCODE.md"
        if pseudo_dir.is_dir() and any(pseudo_dir.iterdir()):
            count = sum(1 for f in pseudo_dir.iterdir() if f.is_file())
            # Update state to reflect validation
            if hasattr(self._state, "pseudocode_validated"):
                self._state.pseudocode_validated = True
            if hasattr(self._state, "pseudocode_artifacts"):
                for f in pseudo_dir.iterdir():
                    if f.is_file():
                        self._state.pseudocode_artifacts[f.stem] = str(f)
            return self._record(
                "GATE_PSEUDOCODE",
                "Pseudocode Exists",
                True,
                f"Found {count} pseudocode file(s) in {pseudo_dir}",
                {"directory": str(pseudo_dir), "file_count": count},
            )
        if pseudo_file.is_file():
            if hasattr(self._state, "pseudocode_validated"):
                self._state.pseudocode_validated = True
            return self._record(
                "GATE_PSEUDOCODE",
                "Pseudocode Exists",
                True,
                f"Found PSEUDOCODE.md at {pseudo_file}",
                {"file": str(pseudo_file)},
            )
        # Determine enforcement mode based on pseudocode config
        pseudocode_enabled = getattr(self._config, "pseudocode", None) and self._config.pseudocode.enabled
        return self._record(
            "GATE_PSEUDOCODE",
            "Pseudocode Exists",
            False,
            "No pseudocode directory or PSEUDOCODE.md found"
            + (" (pseudocode stage enabled — blocking)" if pseudocode_enabled else " (pseudocode disabled — informational)"),
            {"pseudocode_enabled": bool(pseudocode_enabled)},
            force_informational=not pseudocode_enabled,
        )

    # -- Gate 4: INDEPENDENT REVIEW -------------------------------------

    def enforce_review_count(self, item_id: str = "", min_reviews: int = 2) -> GateResult:
        """GATE_INDEPENDENT_REVIEW: Each [x] item has >= min_reviews review cycles.

        If item_id is provided, checks only that item. Otherwise checks all
        checked items in REQUIREMENTS.md.
        """
        from .config import parse_per_item_review_cycles

        req_path = self._req_dir / self._config.convergence.requirements_file
        if not req_path.is_file():
            return self._record(
                "GATE_INDEPENDENT_REVIEW",
                "Independent Review Count",
                False,
                "REQUIREMENTS.md not found",
                {},
            )
        content = req_path.read_text(encoding="utf-8")
        items = parse_per_item_review_cycles(content)

        # Filter to checked items only
        checked = [(iid, chk, cycles) for iid, chk, cycles in items if chk]
        if not checked:
            return self._record(
                "GATE_INDEPENDENT_REVIEW",
                "Independent Review Count",
                True,
                "No checked items to verify (0 items marked [x])",
                {"checked_count": 0},
            )

        if item_id:
            checked = [(iid, c, cy) for iid, c, cy in checked if iid == item_id]
            if not checked:
                return self._record(
                    "GATE_INDEPENDENT_REVIEW",
                    "Independent Review Count",
                    True,
                    f"Item {item_id} not found or not checked",
                    {"item_id": item_id},
                )

        under_reviewed = [(iid, cy) for iid, _, cy in checked if cy < min_reviews]
        if under_reviewed:
            return self._record(
                "GATE_INDEPENDENT_REVIEW",
                "Independent Review Count",
                False,
                f"{len(under_reviewed)} checked item(s) have < {min_reviews} review cycles",
                {
                    "min_reviews": min_reviews,
                    "under_reviewed": [{"item": iid, "cycles": cy} for iid, cy in under_reviewed],
                },
            )
        return self._record(
            "GATE_INDEPENDENT_REVIEW",
            "Independent Review Count",
            True,
            f"All {len(checked)} checked items have >= {min_reviews} review cycles",
            {"checked_count": len(checked), "min_reviews": min_reviews},
        )

    # -- Gate 5: CONVERGENCE THRESHOLD ----------------------------------

    def enforce_convergence_threshold(self) -> GateResult:
        """GATE_CONVERGENCE: >= min_convergence_ratio items marked [x].

        Uses ConvergenceConfig.min_convergence_ratio (default 0.9 = 90%).
        """
        req_path = self._req_dir / self._config.convergence.requirements_file
        if not req_path.is_file():
            return self._record(
                "GATE_CONVERGENCE",
                "Convergence Threshold",
                False,
                "REQUIREMENTS.md not found",
                {},
            )
        content = req_path.read_text(encoding="utf-8")
        total = len(re.findall(r"^- \[[ x]\] \w+-\d+", content, re.MULTILINE))
        checked = len(re.findall(r"^- \[x\] \w+-\d+", content, re.MULTILINE))
        if total == 0:
            return self._record(
                "GATE_CONVERGENCE",
                "Convergence Threshold",
                True,
                "No requirement items found (vacuously true)",
                {"total": 0, "checked": 0, "ratio": 0.0},
            )
        ratio = checked / total
        threshold = self._config.convergence.min_convergence_ratio
        passed = ratio >= threshold
        return self._record(
            "GATE_CONVERGENCE",
            "Convergence Threshold",
            passed,
            f"Convergence {ratio:.1%} >= {threshold:.1%} threshold"
            if passed else
            f"Convergence {ratio:.1%} < {threshold:.1%} threshold ({checked}/{total} checked)",
            {"total": total, "checked": checked, "ratio": ratio, "threshold": threshold},
        )

    # -- Gate 6: TRUTH SCORE (integrates with Feature #2) ---------------

    def enforce_truth_score(self, min_score: float = 0.95) -> GateResult:
        """GATE_TRUTH_SCORE: All truth scores >= min_score.

        Integrates with Feature #2 (Truth Scoring). Reads truth scores
        from .agent-team/TRUTH_SCORES.json if available.
        """
        scores_path = self._req_dir / "TRUTH_SCORES.json"
        if not scores_path.is_file():
            # Feature #2 may not be implemented yet — informational only
            return self._record(
                "GATE_TRUTH_SCORE",
                "Truth Score Threshold",
                False,
                "TRUTH_SCORES.json not found (Feature #2 integration)",
                {},
                force_informational=True,
            )
        try:
            data = json.loads(scores_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._record(
                "GATE_TRUTH_SCORE",
                "Truth Score Threshold",
                False,
                "Failed to parse TRUTH_SCORES.json",
                {},
            )
        scores = data if isinstance(data, list) else data.get("scores", [])
        if not scores:
            return self._record(
                "GATE_TRUTH_SCORE",
                "Truth Score Threshold",
                True,
                "No truth scores recorded (vacuously true)",
                {"score_count": 0},
            )
        below = [s for s in scores if (s.get("score", 0) if isinstance(s, dict) else s) < min_score]
        if below:
            return self._record(
                "GATE_TRUTH_SCORE",
                "Truth Score Threshold",
                False,
                f"{len(below)} score(s) below {min_score} threshold",
                {"min_score": min_score, "below_count": len(below), "total": len(scores)},
            )
        return self._record(
            "GATE_TRUTH_SCORE",
            "Truth Score Threshold",
            True,
            f"All {len(scores)} scores >= {min_score}",
            {"min_score": min_score, "score_count": len(scores)},
        )

    # -- Gate 7: E2E PASS -----------------------------------------------

    def enforce_e2e_pass(self) -> GateResult:
        """GATE_E2E: All E2E tests pass.

        Reads from RunState.endpoint_test_report or E2ETestReport health field.
        """
        report = self._state.endpoint_test_report
        if not report:
            return self._record(
                "GATE_E2E",
                "E2E Tests Pass",
                False,
                "No E2E test report found in run state",
                {},
            )
        health = report.get("health", "unknown")
        tested = report.get("tested_endpoints", 0)
        passed = report.get("passed_endpoints", 0)
        if health == "passed":
            return self._record(
                "GATE_E2E",
                "E2E Tests Pass",
                True,
                f"E2E tests passed ({passed}/{tested})",
                {"health": health, "tested": tested, "passed": passed},
            )
        return self._record(
            "GATE_E2E",
            "E2E Tests Pass",
            False,
            f"E2E tests not fully passing: health={health} ({passed}/{tested})",
            {"health": health, "tested": tested, "passed": passed},
        )

    # -- Audit trail ----------------------------------------------------

    def get_gate_audit_trail(self) -> list[GateResult]:
        """Return the full list of gate results recorded this session."""
        return list(self._audit_trail)

    # -- Internal helpers -----------------------------------------------

    def _record(
        self,
        gate_id: str,
        gate_name: str,
        passed: bool,
        reason: str,
        details: dict[str, Any],
        force_informational: bool = False,
    ) -> GateResult:
        """Record a gate result, write to audit log, and optionally raise."""
        result = GateResult(
            gate_id=gate_id,
            gate_name=gate_name,
            passed=passed,
            reason=reason,
            details=details,
        )
        self._audit_trail.append(result)

        # Update state counters
        if hasattr(self._state, "gate_results"):
            self._state.gate_results.append({
                "gate_id": gate_id,
                "passed": passed,
                "reason": reason,
                "timestamp": result.timestamp,
            })
        if passed:
            if hasattr(self._state, "gates_passed"):
                self._state.gates_passed += 1
        else:
            if hasattr(self._state, "gates_failed"):
                self._state.gates_failed += 1

        # Write to audit log
        self._write_audit_log(result)

        # Log to console
        status = "PASS" if passed else "FAIL"
        _log(f"[GATE] {gate_id}: {status} — {reason}")

        # Enforce or warn
        if not passed and not force_informational:
            if self._mode == GateMode.ENFORCING:
                raise GateViolationError(
                    f"{gate_id} FAILED: {reason}"
                )

        return result

    def _write_audit_log(self, result: GateResult) -> None:
        """Append gate result to GATE_AUDIT.log."""
        log_path = self._req_dir / "GATE_AUDIT.log"
        self._req_dir.mkdir(parents=True, exist_ok=True)
        status = "PASS" if result.passed else "FAIL"
        line = f"[{result.timestamp}] {result.gate_id}: {status} — {result.reason}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Module-level log helper (matches coordinated_builder.py pattern)
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    """Print a timestamped log message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
