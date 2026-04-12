# Wave D Provider Experiment — Execution Plan

## Overview

Run the TaskFlow mini PRD through the V18.1 builder TWICE:
- **Build A (Control):** Wave D = Claude (default)
- **Build B (Experiment):** Wave D = Codex (`provider_map_d: "codex"`)

Everything else is identical: same PRD, same config, same depth. Only Wave D's provider differs.

Compare the outputs on the exact metrics that matter for the Wave D decision.

**Estimated cost:** ~$10-15 per build, ~$20-30 total
**Estimated time:** ~1-2 hours per build
**Outcome:** Definitive data on whether to promote Wave D to Codex

---

## Step 1: Setup

```bash
# Create experiment directories
mkdir C:\MY_PROJECTS\wave-d-experiment
mkdir C:\MY_PROJECTS\wave-d-experiment\build-a-claude
mkdir C:\MY_PROJECTS\wave-d-experiment\build-b-codex

# Copy the PRD to both
cp TASKFLOW_MINI_PRD.md C:\MY_PROJECTS\wave-d-experiment\build-a-claude\PRD.md
cp TASKFLOW_MINI_PRD.md C:\MY_PROJECTS\wave-d-experiment\build-b-codex\PRD.md
```

---

## Step 2: Build A — Wave D on Claude (Control)

```bash
cd C:\MY_PROJECTS\wave-d-experiment\build-a-claude

# Run the builder with default provider routing (Wave D = Claude)
agent-team --prd PRD.md --depth exhaustive \
  --config-override "v18.provider_routing=true" \
  --config-override "v18.provider_map_b=codex" \
  --config-override "v18.provider_map_d=claude"
```

Record:
- Total build time
- Total cost
- Per-wave costs from telemetry
- Final test/compile status
- Any errors or fix cycles

---

## Step 3: Build B — Wave D on Codex (Experiment)

```bash
cd C:\MY_PROJECTS\wave-d-experiment\build-b-codex

# Run the builder with Wave D routed to Codex
agent-team --prd PRD.md --depth exhaustive \
  --config-override "v18.provider_routing=true" \
  --config-override "v18.provider_map_b=codex" \
  --config-override "v18.provider_map_d=codex"
```

Record the same metrics.

---

## Step 4: Automated Comparison

Run these scans on BOTH build outputs. The commands below assume the builds produced NestJS + Next.js projects in their respective directories.

### 4A: Compile Check
```bash
echo "=== BUILD A (Claude Wave D) ==="
cd C:\MY_PROJECTS\wave-d-experiment\build-a-claude
npx tsc --noEmit 2>&1 | tail -3

echo "=== BUILD B (Codex Wave D) ==="
cd C:\MY_PROJECTS\wave-d-experiment\build-b-codex
npx tsc --noEmit 2>&1 | tail -3
```

### 4B: Manual Fetch Violations
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "fetch() calls: "
  grep -rn "fetch(" apps/ src/ --include="*.ts" --include="*.tsx" \
    | grep -v node_modules | grep -v generated | grep -v ".d.ts" | wc -l
  echo -n "axios calls: "
  grep -rn "axios\." apps/ src/ --include="*.ts" --include="*.tsx" \
    | grep -v node_modules | grep -v generated | wc -l
done
```

### 4C: i18n Compliance
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "Hardcoded strings in JSX: "
  grep -rn ">[A-Z][a-z]" apps/ src/ --include="*.tsx" \
    | grep -v node_modules | grep -v generated | grep -v className \
    | grep -v import | grep -v "//" | wc -l
  echo -n "Missing t() calls: "
  grep -rn "\"[A-Z][a-z]\{3,\}\"" apps/ src/ --include="*.tsx" \
    | grep -v node_modules | grep -v import | grep -v className \
    | grep -v "type=" | grep -v "variant=" | wc -l
  echo -n "Translation key files: "
  find . -name "en.json" -o -name "ar.json" | grep -v node_modules | wc -l
done
```

### 4D: RTL Compliance
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "Directional CSS violations: "
  grep -rn "margin-left\|margin-right\|padding-left\|padding-right\|text-align: left\|text-align: right\|float: left\|float: right" \
    apps/ src/ --include="*.tsx" --include="*.css" --include="*.scss" \
    | grep -v node_modules | wc -l
  echo -n "Logical properties used: "
  grep -rn "margin-inline\|padding-inline\|text-align: start\|text-align: end\|inset-inline" \
    apps/ src/ --include="*.tsx" --include="*.css" --include="*.scss" \
    | grep -v node_modules | wc -l
done
```

### 4E: Generated Client Usage
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "Generated client imports: "
  grep -rn "from.*generated\|from.*api-client\|from.*@api" apps/ src/ \
    --include="*.ts" --include="*.tsx" | grep -v node_modules | wc -l
done
```

### 4F: Type Safety
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "'as any' casts: "
  grep -rn "as any" apps/ src/ --include="*.ts" --include="*.tsx" \
    | grep -v node_modules | grep -v generated | wc -l
  echo -n "'@ts-ignore' comments: "
  grep -rn "@ts-ignore\|@ts-expect-error" apps/ src/ --include="*.ts" --include="*.tsx" \
    | grep -v node_modules | wc -l
done
```

### 4G: Code Volume
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  echo -n "Total TypeScript LOC: "
  find apps/ src/ -name "*.ts" -o -name "*.tsx" | grep -v node_modules \
    | xargs wc -l 2>/dev/null | tail -1
  echo -n "Frontend files: "
  find apps/ src/ -name "*.tsx" | grep -v node_modules | wc -l
done
```

### 4H: Telemetry Comparison
```bash
for BUILD in build-a-claude build-b-codex; do
  echo "=== $BUILD ==="
  cd "C:\MY_PROJECTS\wave-d-experiment\$BUILD"
  python -c "
import json, glob
total_cost = 0
for f in sorted(glob.glob('.agent-team/telemetry/*.json')):
    data = json.load(open(f))
    wave = data.get('wave', '?')
    provider = data.get('provider', 'claude')
    cost = data.get('cost', data.get('sdk_cost_usd', 0))
    fallback = data.get('fallback_used', False)
    duration = data.get('duration_seconds', 0)
    total_cost += cost
    print(f'  {wave}: provider={provider:8} cost=\${cost:.3f} duration={duration:.0f}s fallback={fallback}')
print(f'  TOTAL: \${total_cost:.3f}')
" 2>/dev/null || echo "  (telemetry not available)"
done
```

---

## Step 5: Score Card

Fill in from scan results:

| Metric | Build A (Claude D) | Build B (Codex D) | Winner |
|--------|-------------------|-------------------|--------|
| **Compile** | | | |
| TypeScript errors | | | |
| **Wiring** | | | |
| Manual fetch violations | | | |
| Generated client imports | | | |
| **i18n** | | | |
| Hardcoded strings in JSX | | | |
| Translation files present | | | |
| **RTL** | | | |
| Directional CSS violations | | | |
| Logical properties used | | | |
| **Type Safety** | | | |
| `as any` casts | | | |
| `@ts-ignore` comments | | | |
| **Efficiency** | | | |
| Total build cost | | | |
| Wave D cost | | | |
| Wave D duration | | | |
| Fix cycles | | | |
| Wave D fallback triggered | | | |
| **Volume** | | | |
| Total LOC | | | |
| Frontend files | | | |

---

## Step 6: Decision

### PROMOTE Wave D to Codex default if ALL of:
- Codex compile errors ≤ Claude compile errors
- Codex manual fetch violations ≤ Claude
- Codex hardcoded strings ≤ Claude + 20%
- Codex directional CSS violations ≤ Claude + 20%
- Codex `as any` casts ≤ Claude
- Codex fallback rate = 0 (no failures)
- Codex Wave D cost < Claude Wave D cost

### KEEP Wave D on Claude if ANY of:
- Codex compile fails when Claude passes
- Codex has >20% more hardcoded strings
- Codex has >20% more RTL violations
- Codex fallback triggered (means it couldn't complete Wave D)
- Codex produces structurally worse component architecture
- Translation files missing or placeholder-only in Codex build

### RUN ONE MORE BUILD if:
- Results are very close (within 10% on all metrics)
- One build had an anomaly (timeout, retry, unusual error)
- Need to test with a different milestone mix

---

## Why This PRD Works for the Experiment

| Wave D Concern | How the PRD Tests It |
|---------------|---------------------|
| Generated client wiring | 16 endpoints across 4 resources — all must use typed client |
| i18n discipline | Mandatory `t()` for all strings, en.json + ar.json required |
| RTL compliance | Arabic support requires logical CSS properties throughout |
| Forms + validation | 4 forms (login, project, task, comment) with translated errors |
| Data tables | Projects list + task table with sort/filter/paginate |
| State machine UI | Task status buttons conditional on user role + current state |
| Component composition | Kanban, tables, modals, forms, comments — enough variety |

The app is small (~5-8K LOC, 3-4 milestones) but covers every concern raised about Wave D. If Codex handles this well, it can handle any Wave D.
