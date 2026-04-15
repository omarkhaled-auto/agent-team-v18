# D-07 — AUDIT_REPORT.json schema divergence (scorer producer vs AuditReport consumer)

Evidence file: `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/AUDIT_REPORT.json`

## Top-level fields written by the scorer (producer)

| Scorer key | Example value | AuditReport parity? |
|---|---|---|
| `audit_cycle` | `1` | **aliased** — AuditReport uses `cycle` |
| `timestamp` | `"2026-04-15T18:00:00.000Z"` | yes |
| `score` | `0` (flat number) | **shape mismatch** — AuditReport expects a nested `AuditScore` dict |
| `max_score` | `1000` | **unknown to AuditReport** (consumed via flat-score fallback) |
| `verdict` | `"FAIL"` | **not an AuditReport field** — captured as extra |
| `health` | `"failed"` | partial — sits on `AuditScore.health`, not top-level |
| `deductions_total` | `1342` | **not an AuditReport field** — extra |
| `deductions_capped` | `1000` | **not an AuditReport field** — extra |
| `finding_counts` | `{CRITICAL: 7, HIGH: 13, ...}` | **not an AuditReport field** — extra |
| `findings` | list of `{id, severity, category, title, description, location, source, fix_action}` | yes — `AuditFinding.from_dict` already handles both `id`/`finding_id` and `title`/`summary` and `fix_action`/`remediation` |
| `category_summary` | `{wiring: {...}, ...}` | **not an AuditReport field** — extra |
| `by_severity` | `{CRITICAL: ["F-001", ...]}` — values are **finding_id strings**, not indices | **shape mismatch** — AuditReport stores list[int] indices; scorer emits list[str] finding_ids. Currently preserved verbatim; lookup consumers must tolerate both shapes. Not re-keyed this session (scope guard). |
| `by_file` | `{"packages/api-client/index.ts": ["F-001", ...]}` — values are finding_id strings | **shape mismatch** — same as `by_severity` |
| `fix_candidates` | `["F-001", "F-002", ...]` — finding_id strings | **normalized in `from_json`** — coerced to `list[int]` indices into `findings`; unknown ids silently dropped. `group_findings_into_fix_tasks` is now safe on scorer-produced reports. |
| `notes` | long descriptive string | **not an AuditReport field** — extra |

## Top-level fields the legacy `to_json`/`from_json` writes but the scorer omits

- `audit_id` — missing entirely. `from_json` must synthesize from timestamp+cycle.
- `auditors_deployed` — missing. Default to `[]`.
- `by_requirement` — missing. Default to `{}`.
- `scope` — missing (C-01 addition). Default to `{}`.

## Consumer-side fix applied (D-07)

`AuditReport.from_json` is made permissive:

1. `audit_id`: use provided value if present; else synthesize as `f"audit-{timestamp}-c{cycle}"` for deterministic round-trip.
2. `cycle`: accept either `cycle` (legacy) or `audit_cycle` (scorer).
3. `auditors_deployed`: default `[]` when missing.
4. `score`: accept legacy `AuditScore` dict OR flat `{"score": N, "max_score": M}` at top level. When flat, build an `AuditScore` with populated `score`/`max_score` and zeros/derived fields elsewhere; pull `health` from top-level `health` if present, else empty.
5. `extras`: preserve every top-level key that is not a known AuditReport field so downstream consumers (e.g., `State.finalize()` reading `health`) can still access them.
6. `fix_candidates`: normalized to `list[int]` indices into `findings`. When the scorer ships finding-id strings, they are resolved via an id→index map built from the parsed `findings` list; unknown ids are dropped. This guarantees `group_findings_into_fix_tasks(report)` is safe on any report parsed by `from_json`.
7. `by_severity`/`by_file`: stored verbatim (scorer emits finding-id string values; legacy emits int indices). No production consumer uses them to index `findings`, so the shape divergence is info-only and left as-is.

`AuditReport.to_json` remains canonical — produces the legacy shape. The reader is the single tolerant point.

## Not changed this session (scope guard)

- `audit_prompts.py` (scorer prompt) — plan explicitly forbids touching.
- `build_report` / `AuditScore.compute` — unchanged, still produce legacy shape.
- `by_severity` / `by_file`: shape divergence is documented (finding-id strings vs. int indices) but left verbatim. They are info-only — no production consumer uses them to index `findings`. A follow-up would normalize them the same way `fix_candidates` is normalized, but there is no current consumer pain pulling for that work.
