"""Generate AUDIT_FIX_GUIDE.md from the latest audit report."""
import json

r = json.load(open("C:/MY_PROJECTS/facilities-platform/.agent-team/audit_run11.json", encoding="utf-8"))

lines = []
lines.append("# FacilityPlatform — Audit Report & Fix Guide")
lines.append("")
lines.append(f"## Current Score: {r.get('score', 0)}%")
lines.append("")
lines.append("| Metric | Value |")
lines.append("|--------|-------|")
lines.append(f"| Passed | {r.get('passed_acs', 0)} |")
lines.append(f"| Partial | {r.get('partial_acs', 0)} |")
lines.append(f"| Failed | {r.get('failed_acs', 0)} |")
lines.append(f"| Skipped (REQUIRES_HUMAN) | {r.get('skipped_acs', 0)} |")
lines.append(f"| Total ACs | {r.get('total_acs', 0)} |")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## How to Use This Guide")
lines.append("")
lines.append("1. Open a Claude Code session in `C:\\MY_PROJECTS\\facilities-platform`")
lines.append("2. Feed this file to Claude: `@AUDIT_FIX_GUIDE.md`")
lines.append("3. Ask Claude to fix ALL findings below, working through them systematically")
lines.append("4. The PRD source of truth is: `C:\\MY_PROJECTS\\facilities-platform\\prd.md`")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Findings to Fix")
lines.append("")

findings = r.get("findings", [])

high = [f for f in findings if f.get("severity") == "high"]
medium = [f for f in findings if f.get("severity") == "medium"]
human = [f for f in findings if f.get("severity") == "requires_human"]

for sev_label, sev_findings in [("HIGH (Failed)", high), ("MEDIUM (Partial)", medium)]:
    if not sev_findings:
        continue
    lines.append(f"### {sev_label} — {len(sev_findings)} findings")
    lines.append("")

    for i, f in enumerate(sev_findings, 1):
        fid = f.get("id", "?")
        title = f.get("title", "?")
        desc = f.get("description", "No description")
        fpath = f.get("file_path", "")
        line_num = f.get("line_number", 0)
        expected = f.get("expected_behavior", "")
        fix = f.get("fix_suggestion", "")
        snippet = f.get("code_snippet", "")
        ac = f.get("acceptance_criterion", "")

        lines.append(f"#### {i}. [{fid}] {title[:100]}")
        lines.append("")
        if fpath:
            lines.append(f"**File:** `{fpath}:{line_num}`")
            lines.append("")
        if ac:
            lines.append(f"**Acceptance Criterion:** {ac}")
            lines.append("")
        lines.append(f"**Issue:** {desc}")
        lines.append("")
        if expected:
            lines.append(f"**Expected (from PRD):** {expected}")
            lines.append("")
        if fix and "Implement AC-" not in fix:
            lines.append(f"**Required Change:** {fix}")
            lines.append("")
        if snippet:
            lines.append("**Current Code:**")
            lines.append("```typescript")
            lines.append(snippet[:2000])
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

lines.append(f"### REQUIRES_HUMAN — {len(human)} findings (skip these)")
lines.append("")
for f in human:
    lines.append(f"- {f.get('id', '?')}: {f.get('title', '?')[:120]}")
lines.append("")

# Also append the audit prompt template for re-running
lines.append("---")
lines.append("")
lines.append("## Re-Running the Audit")
lines.append("")
lines.append("After fixing, run the audit from `C:\\MY_PROJECTS\\agent-team-v15`:")
lines.append("")
lines.append("```bash")
lines.append("python -m agent_team_v15 audit \\")
lines.append('    --prd "C:\\MY_PROJECTS\\facilities-platform\\prd.md" \\')
lines.append('    --cwd "C:\\MY_PROJECTS\\facilities-platform" \\')
lines.append('    --output "C:\\MY_PROJECTS\\facilities-platform\\.agent-team\\audit_manual.json"')
lines.append("```")
lines.append("")
lines.append("Or to run the full coordinated build loop:")
lines.append("")
lines.append("```bash")
lines.append("python -m agent_team_v15 coordinated-build \\")
lines.append('    --prd "C:\\MY_PROJECTS\\facilities-platform\\prd.md" \\')
lines.append('    --cwd "C:\\MY_PROJECTS\\facilities-platform" \\')
lines.append("    --max-iterations 20 --skip-initial-build \\")
lines.append("    --browser-tests --browser-port 3080")
lines.append("```")

output_path = "C:/MY_PROJECTS/facilities-platform/AUDIT_FIX_GUIDE.md"
with open(output_path, "w", encoding="utf-8") as out:
    out.write("\n".join(lines))

print(f"Written {len(lines)} lines to {output_path}")
print(f"HIGH: {len(high)}, MEDIUM: {len(medium)}, REQUIRES_HUMAN: {len(human)}")
