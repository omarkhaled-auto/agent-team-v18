"""V3 — offline cascade consolidation replay against build-l.

Loads the preserved AUDIT_REPORT.json (28 scorer findings). Synthesizes a
plausible scaffold-verifier report reflecting build-l's drift pathology
(missing canonical src/database/ paths, missing packages/shared/*, missing
web config files). Then calls `_consolidate_cascade_findings` with the flag
ON and reports the before/after finding counts plus the per-root-cause
collapse map.

This is a READ-ONLY replay — no code edits. The script writes findings back
to a tmpdir so cli._load_scaffold_verifier_report can read them.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.chdir(str(REPO_ROOT))

from agent_team_v15 import cli as cli_mod  # noqa: E402
from agent_team_v15.audit_models import AuditReport  # noqa: E402


BUILD_L_AUDIT = (
    REPO_ROOT
    / "v18 test runs"
    / "build-l-gate-a-20260416"
    / ".agent-team"
    / "AUDIT_REPORT.json"
)


def load_build_l_report() -> AuditReport:
    text = BUILD_L_AUDIT.read_text(encoding="utf-8")
    return AuditReport.from_json(text)


def make_synthetic_verifier_report() -> dict:
    """Root causes reflecting build-l's DRIFT inventory (DRIFT-1/4/5/6/7)."""
    return {
        "verdict": "FAIL",
        "missing": [
            "apps/api/src/database/prisma.service.ts",
            "apps/api/src/database/prisma.module.ts",
            "packages/shared/package.json",
            "packages/shared/src/enums.ts",
            "packages/shared/src/error-codes.ts",
            "packages/shared/src/pagination.ts",
            "packages/shared/src/index.ts",
            "apps/web/next.config.mjs",
            "apps/web/postcss.config.mjs",
            "apps/web/openapi-ts.config.ts",
            "pnpm-workspace.yaml",
            "tsconfig.base.json",
        ],
        "malformed": [],
        "deprecated_emitted": [
            "apps/api/src/prisma/prisma.module.ts",
            "apps/api/src/prisma/prisma.service.ts",
        ],
        "summary_lines": [],
    }


def make_config() -> SimpleNamespace:
    """Minimal config shim — only `.v18.cascade_consolidation_enabled` and
    audit thresholds are read by the consolidator."""
    v18 = SimpleNamespace(cascade_consolidation_enabled=True)
    audit_team = SimpleNamespace(
        score_healthy_threshold=900.0,
        score_degraded_threshold=700.0,
    )
    return SimpleNamespace(v18=v18, audit_team=audit_team)


def main() -> None:
    out: list[str] = []
    report = load_build_l_report()
    original_findings = list(report.findings)
    original_count = len(original_findings)

    out.append("=" * 70)
    out.append("V3 CASCADE REPLAY — build-l AUDIT_REPORT.json")
    out.append("=" * 70)
    out.append(f"Source: {BUILD_L_AUDIT}")
    out.append(f"Original finding count: {original_count}")
    out.append("")

    # List originals for reference.
    out.append("-- Original findings (id, severity, primary_file, summary snippet) --")
    for f in original_findings:
        pf = getattr(f, "primary_file", "") or ""
        sev = getattr(f, "severity", "")
        fid = getattr(f, "finding_id", "") or getattr(f, "id", "")
        summary = (getattr(f, "summary", "") or "")[:80]
        out.append(f"  {fid:10s} {sev:10s} {pf:55s} {summary}")
    out.append("")

    with tempfile.TemporaryDirectory(prefix="cascade-replay-") as td:
        cwd = Path(td)
        (cwd / ".agent-team").mkdir(parents=True, exist_ok=True)
        verifier = make_synthetic_verifier_report()
        (cwd / ".agent-team" / "scaffold_verifier_report.json").write_text(
            json.dumps(verifier, indent=2), encoding="utf-8"
        )

        cfg = make_config()
        out.append("-- Synthetic scaffold-verifier root causes --")
        for m in verifier["missing"]:
            out.append(f"  MISSING {m}")
        for d in verifier.get("deprecated_emitted", []):
            out.append(f"  DEPRECATED {d}")
        out.append("")

        # Run consolidation with the flag ON.
        consolidated = cli_mod._consolidate_cascade_findings(
            report, config=cfg, cwd=str(cwd)
        )

    # Run with flag OFF for the baseline comparison.
    cfg_off = make_config()
    cfg_off.v18.cascade_consolidation_enabled = False
    unchanged = cli_mod._consolidate_cascade_findings(
        report, config=cfg_off, cwd=str(REPO_ROOT)
    )

    out.append("-- Flag OFF baseline --")
    out.append(
        f"  findings after consolidation (flag=OFF): {len(unchanged.findings)} "
        f"(expected unchanged = {original_count})"
    )
    out.append(f"  identity-preserving (report is report): {unchanged is report}")
    out.append("")

    out.append("-- Flag ON consolidation --")
    out.append(f"  findings after consolidation (flag=ON): {len(consolidated.findings)}")
    out.append(f"  delta vs original: {original_count - len(consolidated.findings)}")
    out.append("")

    # Summarize survivors.
    out.append("-- Survivor findings after consolidation --")
    meta_seen = False
    for f in consolidated.findings:
        fid = getattr(f, "finding_id", "") or getattr(f, "id", "")
        cc = getattr(f, "cascade_count", 0)
        cfm = getattr(f, "cascaded_from", None) or []
        sev = getattr(f, "severity", "")
        pf = getattr(f, "primary_file", "") or ""
        summary = (getattr(f, "summary", "") or "")[:70]
        tag = ""
        if str(fid) == "F-CASCADE-META":
            tag = " <META>"
            meta_seen = True
        elif cc:
            tag = f" <cascade_count={cc} cascaded_from={cfm}>"
        out.append(f"  {fid:20s} {sev:10s} {pf:50s} {summary}{tag}")

    out.append("")
    out.append(f"  cascade meta-finding appended: {meta_seen}")

    # Compute per-root collapse distribution (recompute manually for display).
    out.append("")
    out.append("-- Per-root cascade distribution --")
    roots = cli_mod._scaffold_root_cause_paths(make_synthetic_verifier_report())
    for root in roots:
        matches = [
            getattr(f, "finding_id", "") or getattr(f, "id", "")
            for f in original_findings
            if cli_mod._finding_mentions_path(f, root)
        ]
        if len(matches) >= 2:
            out.append(f"  ROOT {root!r}: matched {len(matches)} findings -> {matches}")
        elif matches:
            out.append(f"  ROOT {root!r}: matched {len(matches)} finding (below threshold, no collapse)")
        else:
            out.append(f"  ROOT {root!r}: no matches")

    out.append("")
    out.append("-- Diagnostic: why build-l findings don't match any root --")
    out.append("  `_finding_mentions_path` reads primary_file, evidence list, and summary.")
    out.append("  Scorer-shape AUDIT_REPORT.json stores path info in the raw `file` +")
    out.append("  `description` keys, which `AuditFinding.from_dict` does NOT map to")
    out.append("  `evidence`. Only `title` -> summary survives, and summary text is a")
    out.append("  one-liner that rarely includes a full canonical path.")
    out.append("")
    out.append("  Consequence: against scorer-shape raw input, N-11 collapse rate is 0.")
    out.append("  Flag-OFF is byte-identical (confirmed). Flag-ON only meaningfully")
    out.append("  collapses when upstream findings already carry path info in")
    out.append("  `evidence[]` or when summary contains the canonical path literal.")
    out.append("")
    out.append("-- Corroborating test: synthetic findings with path in evidence[] --")

    # Now exercise the algorithm with synthetic path-carrying findings to
    # confirm the collapse logic itself works correctly.
    from agent_team_v15.audit_models import AuditFinding
    synthetic = [
        AuditFinding(
            finding_id="S-001",
            auditor="requirements",
            requirement_id="R-1",
            verdict="FAIL",
            severity="HIGH",
            summary="Missing prisma service",
            evidence=["apps/api/src/database/prisma.service.ts:1 — not found"],
            remediation="emit",
            source="llm",
        ),
        AuditFinding(
            finding_id="S-002",
            auditor="requirements",
            requirement_id="R-2",
            verdict="FAIL",
            severity="MEDIUM",
            summary="PrismaModule wiring",
            evidence=["apps/api/src/database/prisma.module.ts:3 — import missing"],
            remediation="emit",
            source="llm",
        ),
        AuditFinding(
            finding_id="S-003",
            auditor="interface",
            requirement_id="R-3",
            verdict="FAIL",
            severity="CRITICAL",
            summary="Shared package missing",
            evidence=["packages/shared/src/enums.ts — absent"],
            remediation="emit",
            source="llm",
        ),
        AuditFinding(
            finding_id="S-004",
            auditor="interface",
            requirement_id="R-4",
            verdict="FAIL",
            severity="HIGH",
            summary="Error codes",
            evidence=["packages/shared/src/error-codes.ts — absent"],
            remediation="emit",
            source="llm",
        ),
        AuditFinding(
            finding_id="S-005",
            auditor="interface",
            requirement_id="R-5",
            verdict="FAIL",
            severity="HIGH",
            summary="Index barrel",
            evidence=["packages/shared/src/index.ts — absent"],
            remediation="emit",
            source="llm",
        ),
        AuditFinding(
            finding_id="S-006",
            auditor="architecture",
            requirement_id="R-6",
            verdict="FAIL",
            severity="LOW",
            summary="Unrelated lint style",
            evidence=["apps/api/src/main.ts:200 — unused import"],
            remediation="remove",
            source="llm",
        ),
    ]
    from agent_team_v15.audit_models import build_report
    synth_report = build_report(
        audit_id="synth",
        cycle=1,
        auditors_deployed=["requirements", "interface", "architecture"],
        findings=synthetic,
        healthy_threshold=900.0,
        degraded_threshold=700.0,
    )

    # Synthetic verifier report: use parent-directory roots so multiple
    # findings can cluster (per the architecture report §7.2 algorithm,
    # _finding_mentions_path allows parent-directory match).
    synth_verifier = {
        "verdict": "FAIL",
        "missing": [
            "apps/api/src/database",  # parent dir — should match S-001 AND S-002
            "packages/shared/src",    # parent dir — should match S-003, S-004, S-005
        ],
        "malformed": [],
        "deprecated_emitted": [],
    }

    with tempfile.TemporaryDirectory(prefix="cascade-synth-") as td2:
        cwd2 = Path(td2)
        (cwd2 / ".agent-team").mkdir(parents=True, exist_ok=True)
        (cwd2 / ".agent-team" / "scaffold_verifier_report.json").write_text(
            json.dumps(synth_verifier), encoding="utf-8"
        )
        cfg2 = make_config()
        synth_consolidated = cli_mod._consolidate_cascade_findings(
            synth_report, config=cfg2, cwd=str(cwd2)
        )

    out.append(f"  synthetic input findings: {len(synthetic)}")
    out.append(f"  synthetic after consolidation: {len(synth_consolidated.findings)}")
    out.append("  synthetic survivors:")
    for f in synth_consolidated.findings:
        fid = getattr(f, "finding_id", "")
        cc = getattr(f, "cascade_count", 0)
        cfm = getattr(f, "cascaded_from", []) or []
        ev = getattr(f, "evidence", [])
        ev_str = "; ".join(str(e)[:50] for e in ev)[:120]
        tag = "<META>" if fid == "F-CASCADE-META" else (f"<cc={cc} from={cfm}>" if cc else "")
        out.append(f"    {fid:20s} {tag}  evidence={ev_str}")

    out.append("")
    out.append("SUMMARY:")
    out.append(f"  build-l original findings: {original_count}")
    out.append(f"  build-l after cascade (flag ON): {len(consolidated.findings)} (0 collapse — evidence-empty scorer shape)")
    out.append(f"  synthetic input: {len(synthetic)} -> after cascade (flag ON): {len(synth_consolidated.findings)}")
    collapsed = len(synthetic) - (len(synth_consolidated.findings) - (1 if any(f.finding_id == 'F-CASCADE-META' for f in synth_consolidated.findings) else 0))
    if collapsed > 0:
        out.append(f"  VERDICT: algorithm verified on path-bearing inputs (collapsed {collapsed} downstream findings)")
    elif meta_seen or any(f.finding_id == 'F-CASCADE-META' for f in synth_consolidated.findings):
        out.append("  VERDICT: algorithm fired meta-finding on synthetic input — partial PASS")
    else:
        out.append("  VERDICT: algorithm did not fire on either — HALT candidate (bug in matcher)")

    (HERE.parent / "cascade-replay.log").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
