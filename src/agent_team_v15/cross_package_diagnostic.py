"""Phase 5.8a §K.1 — Cross-package OpenAPI / TS-client diagnostic step.

Compares the OpenAPI 3.1 spec produced by Wave A/B's emission pipeline to
the TypeScript client emitted by openapi-ts at ``packages/api-client/``.
Reports divergences as advisory ``CONTRACT-DRIFT-DIAGNOSTIC-001`` findings
(severity ``LOW``, NEVER blocking).

Per §M.M7 diagnostic-first: this module ships with Phase 5.8a; the §K.2
decision-gate evaluator (separate operator-authorised session) reads the
per-milestone ``PHASE_5_8A_DIAGNOSTIC.json`` artifacts to decide whether
to ship Phase 5.8b's full cross-package contract OR to invest in Wave A
spec-quality.

Anti-patterns enforced (per §K.4 + scope check-in corrections):

* Severity LOW + advisory wording in the finding message + scorer-prompt
  instruction (``audit_prompts.py``) — the Quality Contract gate-3 filter
  (HIGH/CRITICAL only on ``verdict=FAIL``) does not see this finding even
  when the audit-team scorer promotes it from ``WAVE_FINDINGS.json`` into
  ``AUDIT_REPORT.json`` (the scorer is instructed to set
  ``verdict=UNVERIFIED, severity=LOW``).
* Polymorphic OpenAPI schemas (``oneOf`` / ``anyOf`` / ``allOf``) are
  SKIPPED as unsupported metadata; they do NOT inflate the divergence
  count and do NOT trigger Phase 5.8b. They surface in
  ``PHASE_5_8A_DIAGNOSTIC.json::unsupported_polymorphic_schemas`` so the
  K.2 evaluator can see what was skipped.
* Diagnostic execution is timeout-bounded (``_NODE_PARSE_TIMEOUT_SECONDS``)
  and crash-isolated: any subprocess timeout, parse error, or unexpected
  exception is captured into the artifact's ``tooling`` block; ZERO drift
  findings emit in those cases (no false positives) and Wave C continues
  unaffected.
* Per-milestone artifact path
  (``<cwd>/.agent-team/milestones/<id>/PHASE_5_8A_DIAGNOSTIC.json``) — M1
  and M2 cannot overwrite each other.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants — locked enums; consumed by the §K.2 evaluator.
# ---------------------------------------------------------------------------

CONTRACT_DRIFT_DIAGNOSTIC_CODE = "CONTRACT-DRIFT-DIAGNOSTIC-001"
DIAGNOSTIC_SEVERITY = "LOW"
DIAGNOSTIC_VERDICT_HINT = "UNVERIFIED"

DIVERGENCE_CLASS_MISSING_EXPORT = "missing-export"
DIVERGENCE_CLASS_CAMEL_VS_SNAKE = "camelCase-vs-snake_case"
DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED = "optional-vs-required"
DIVERGENCE_CLASS_TYPE_MISMATCH = "type-mismatch"

ALL_DIVERGENCE_CLASSES = (
    DIVERGENCE_CLASS_MISSING_EXPORT,
    DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
    DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
    DIVERGENCE_CLASS_TYPE_MISMATCH,
)

TOOLING_PARSER_NODE_TS_AST = "node-typescript-ast"
TOOLING_PARSER_UNAVAILABLE = "unavailable"

DIAGNOSTIC_LOG_TAG = "[CROSS-PACKAGE-DIAG]"
PHASE_5_8A_DIAGNOSTIC_FILENAME = "PHASE_5_8A_DIAGNOSTIC.json"

# Polymorphic schemas (oneOf/anyOf/allOf) are SKIPPED — recorded separately
# in the artifact's ``unsupported_polymorphic_schemas`` list. They do NOT
# inflate divergence count or trigger 5.8b (per §K.4 + scope check-in
# correction #1).
_UNSUPPORTED_POLYMORPHIC_KEYS = ("oneOf", "anyOf", "allOf")

# Tooling-unavailable visible in artifact; emit no drift findings (Q3).
_NODE_PARSE_TIMEOUT_SECONDS = 30
_NODE_BIN_CANDIDATES = ("node",)

# Embedded JS — packaged as a Python string and written to a tempfile at
# runtime. Avoids pyproject.toml package-data churn (the helper does not
# need to ship as a discrete file). Resolves ``typescript`` from the
# generated workspace via ``createRequire(<projectRoot>/package.json)`` so
# openapi-ts's pinned ``typescript`` is the one used.
_PARSE_GEN_TS_JS = r"""
'use strict';
const { createRequire } = require('node:module');
const path = require('node:path');
const fs = require('node:fs');

if (process.argv.length < 4) {
  console.error('usage: node parse_gen_ts.js <projectRoot> <targetFile>');
  process.exit(2);
}

const projectRoot = process.argv[2];
const targetFile = process.argv[3];

let ts;
try {
  // Resolve typescript from the GENERATED workspace, not from this helper's
  // location — the workspace is where openapi-ts pulled in `typescript`.
  const projectRequire = createRequire(path.join(projectRoot, 'package.json'));
  ts = projectRequire('typescript');
} catch (err) {
  console.error('typescript_unavailable: ' + (err && err.message ? err.message : 'cannot resolve typescript'));
  process.exit(3);
}

let sourceText;
try {
  sourceText = fs.readFileSync(targetFile, 'utf-8');
} catch (err) {
  console.error('read_failed: ' + (err && err.message ? err.message : 'cannot read targetFile'));
  process.exit(4);
}

const sourceFile = ts.createSourceFile('input.ts', sourceText, ts.ScriptTarget.Latest, true);

function isExported(node) {
  if (!node.modifiers) return false;
  return node.modifiers.some(function (m) { return m.kind === ts.SyntaxKind.ExportKeyword; });
}

function getLineNumber(node) {
  const lc = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return lc.line + 1;
}

function propertyName(node) {
  if (!node.name) return '';
  if (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) {
    return node.name.text;
  }
  return node.name.getText(sourceFile);
}

function typeText(typeNode) {
  if (!typeNode) return 'any';
  return typeNode.getText(sourceFile).trim();
}

function describeMembers(members) {
  const props = [];
  for (let i = 0; i < members.length; i++) {
    const member = members[i];
    if (!ts.isPropertySignature(member)) continue;
    props.push({
      name: propertyName(member),
      optional: !!member.questionToken,
      typeText: typeText(member.type),
    });
  }
  return props;
}

const out = { exports: [], parser: 'node-typescript-ast', tsVersion: ts.version };

ts.forEachChild(sourceFile, function (node) {
  if (ts.isTypeAliasDeclaration(node) && isExported(node)) {
    if (ts.isTypeLiteralNode(node.type)) {
      out.exports.push({
        name: node.name.text,
        kind: 'type-literal',
        line: getLineNumber(node),
        properties: describeMembers(node.type.members),
      });
    } else {
      out.exports.push({
        name: node.name.text,
        kind: 'type-other',
        line: getLineNumber(node),
        typeText: typeText(node.type),
      });
    }
  } else if (ts.isInterfaceDeclaration(node) && isExported(node)) {
    out.exports.push({
      name: node.name.text,
      kind: 'interface',
      line: getLineNumber(node),
      properties: describeMembers(node.members),
    });
  }
});

console.log(JSON.stringify(out));
"""


# ---------------------------------------------------------------------------
# DivergenceRecord
# ---------------------------------------------------------------------------


@dataclass
class DivergenceRecord:
    """A single ``CONTRACT-DRIFT-DIAGNOSTIC-001`` divergence."""

    divergence_class: str
    schema_name: str
    property_name: str = ""
    spec_value: str = ""
    client_value: str = ""
    client_file: str = ""
    client_line: int = 0
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Type-class normalisation helpers (per scope check-in correction #1).
# ---------------------------------------------------------------------------


def _is_polymorphic_schema(schema: dict[str, Any]) -> bool:
    return any(k in schema for k in _UNSUPPORTED_POLYMORPHIC_KEYS)


def _normalize_property_name(name: str) -> str:
    """Strip underscores + lowercase for camelCase ⟷ snake_case comparison."""

    return re.sub(r"_", "", str(name or "")).lower()


# OpenAPI primitive-to-TS-class normalisation (per @hey-api/openapi-ts
# canonical generation). The canonical generator emits TS ``number`` for
# BOTH OpenAPI ``integer`` and ``number`` schemas (refs:
# https://github.com/hey-api/openapi-ts/blob/main/docs/openapi-ts/plugins/schemas.md
# + https://github.com/hey-api/openapi-ts/blob/main/docs/openapi-ts/plugins/typescript.md).
# Without this normalisation, every ``integer`` field becomes a false-
# positive ``type-mismatch`` divergence in steady state — closed by
# scope check-in reviewer correction #2.
_OPENAPI_PRIMITIVE_TS_CLASS = {
    "integer": "number",
}


def _normalize_openapi_primitive(t: str) -> str:
    """Return the TS-equivalent class for an OpenAPI primitive type name."""

    return _OPENAPI_PRIMITIVE_TS_CLASS.get(t, t)


def _classify_openapi_type(
    schema: dict[str, Any],
    schemas: dict[str, Any],
    *,
    _depth: int = 0,
) -> str:
    """Reduce an OpenAPI property schema to a normalized type-class.

    Returns one of: ``"string"``, ``"number"``, ``"boolean"``,
    ``"array<X>"``, ``"object"``, ``"ref:<Name>"``, ``"polymorphic"``,
    ``"unknown"``.

    OpenAPI ``integer`` is normalised to ``"number"`` per canonical
    @hey-api/openapi-ts emission (both at top-level + recursively within
    arrays + within ``type: [X, "null"]`` shapes). Without this
    normalisation, every ``integer`` field would generate a false-positive
    ``type-mismatch`` against the generated TS ``number`` (reviewer
    correction #2).

    Handles modern ``type: [string, "null"]`` arrays by stripping ``"null"``
    and keeping the primary type for comparison (``nullable`` is a separate
    optional-vs-required dimension, not a type-class change).
    """

    if not isinstance(schema, dict) or _depth > 4:
        return "unknown"
    if _is_polymorphic_schema(schema):
        return "polymorphic"
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return f"ref:{ref.rsplit('/', 1)[-1]}"
    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items") or {}
        return f"array<{_classify_openapi_type(items, schemas, _depth=_depth + 1)}>"
    if isinstance(schema_type, list):
        non_null = [t for t in schema_type if t != "null"]
        if len(non_null) == 1 and isinstance(non_null[0], str):
            return _normalize_openapi_primitive(non_null[0])
        return "unknown"
    if isinstance(schema_type, str):
        return _normalize_openapi_primitive(schema_type)
    if "properties" in schema:
        return "object"
    if schema.get("enum"):
        # Enum types reduce to their underlying primitive when declared,
        # else fall through to ``unknown`` (rare on canonical openapi-ts
        # output).
        return "string"
    return "unknown"


_TS_PRIMITIVES = {"string", "number", "boolean", "bigint", "symbol", "Date"}
_TS_NEVER_LIKE = {"never", "void", "null", "undefined"}


def _classify_ts_type(ts_type: str) -> str:
    """Reduce a TS type fragment to a normalized type-class.

    Mirrors :func:`_classify_openapi_type`'s output enum so the comparison
    is symmetrical. Strips trailing ``| null`` / ``| undefined`` to match
    OpenAPI ``nullable``; recognises ``T[]`` / ``Array<T>`` array shapes
    and bare-identifier references.
    """

    if not ts_type:
        return "unknown"
    cleaned = re.sub(r"\s*\|\s*null\b", "", ts_type)
    cleaned = re.sub(r"\s*\|\s*undefined\b", "", cleaned).strip()
    cleaned = cleaned.rstrip(";").strip()

    array_brackets = re.match(r"^(.+?)\s*\[\]$", cleaned)
    if array_brackets:
        inner = _classify_ts_type(array_brackets.group(1).strip())
        return f"array<{inner}>"
    array_generic = re.match(r"^Array<(.+)>$", cleaned)
    if array_generic:
        return f"array<{_classify_ts_type(array_generic.group(1).strip())}>"

    if cleaned == "Date":
        # openapi-ts emits ``Date`` for date-time formats; OpenAPI's
        # canonical ``string`` (with format=date-time) is the comparable.
        return "string"
    if cleaned in _TS_PRIMITIVES:
        return cleaned
    if cleaned in _TS_NEVER_LIKE:
        return "unknown"
    if cleaned in ("any", "unknown"):
        return "unknown"
    if re.match(r"^['\"`].*['\"`]$", cleaned):  # literal type
        return "string"
    if re.match(r"^[+-]?[0-9]+(?:\.[0-9]+)?$", cleaned):  # numeric literal
        return "number"
    if cleaned in ("true", "false"):
        return "boolean"
    # Bare identifier referencing another exported type.
    if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", cleaned):
        return f"ref:{cleaned}"
    return "unknown"


# ---------------------------------------------------------------------------
# TS parser (Node side via TypeScript compiler API).
# ---------------------------------------------------------------------------


def _resolve_node_bin() -> str | None:
    """Return the resolved ``node`` binary path, or ``None`` if absent."""

    for candidate in _NODE_BIN_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _run_node_parser(
    file_path: Path,
    project_root: Path,
    *,
    node_bin: str | None = None,
) -> dict[str, Any]:
    """Parse *file_path* via the embedded Node TypeScript-AST helper.

    Returns the JSON parse output dict (``{exports: [...], parser: ..., tsVersion: ...}``)
    on success, or ``{"exports": [], "error": "<reason>"}`` on any failure.
    Crash-isolated — never raises to the caller.
    """

    bin_path = node_bin or _resolve_node_bin()
    if not bin_path:
        return {"exports": [], "error": "node_unavailable: node binary not on PATH"}

    tmp_script: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="-parse_gen_ts.js", delete=False, encoding="utf-8",
        ) as fh:
            fh.write(_PARSE_GEN_TS_JS)
            tmp_script = Path(fh.name)

        proc = subprocess.run(
            [bin_path, str(tmp_script), str(project_root), str(file_path)],
            capture_output=True,
            text=True,
            timeout=_NODE_PARSE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"exports": [], "error": "node_parse_timeout"}
    except (OSError, ValueError) as exc:
        return {"exports": [], "error": f"node_parse_failed: {exc}"}
    finally:
        if tmp_script is not None:
            try:
                tmp_script.unlink()
            except OSError:  # pragma: no cover - cleanup best-effort
                pass

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[:300]
        return {
            "exports": [],
            "error": f"node_parser_exit_{proc.returncode}: {stderr_tail}",
        }
    try:
        parsed = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"exports": [], "error": f"node_parser_json_decode: {exc}"}
    if not isinstance(parsed, dict):
        return {"exports": [], "error": "node_parser_unexpected_shape"}
    parsed.setdefault("exports", [])
    parsed.setdefault("parser", TOOLING_PARSER_NODE_TS_AST)
    return parsed


# ---------------------------------------------------------------------------
# Comparison core.
# ---------------------------------------------------------------------------


def _load_openapi_spec(spec_path: Path) -> dict[str, Any] | None:
    """Read + JSON-parse an OpenAPI spec file. Returns ``None`` on failure."""

    try:
        text = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _gather_client_exports(client_dir: Path) -> Path | None:
    """Return the path of ``types.gen.ts`` if present, else ``None``."""

    types_gen = client_dir / "types.gen.ts"
    if types_gen.is_file():
        return types_gen
    return None


def _index_ts_exports(ts_parse: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index TS exports by name for O(1) lookup."""

    indexed: dict[str, dict[str, Any]] = {}
    for entry in ts_parse.get("exports", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "") or "")
        if not name:
            continue
        indexed[name] = entry
    return indexed


def _compare_schema(
    schema_name: str,
    spec_schema: dict[str, Any],
    ts_export: dict[str, Any],
    schemas: dict[str, Any],
    client_file_rel: str,
) -> list[DivergenceRecord]:
    """Compare one ``components.schemas[X]`` entry to its TS export.

    Yields divergences in deterministic order: missing properties first,
    then case mismatches, optional-vs-required mismatches, then type
    mismatches. Polymorphic schemas (``oneOf`` / ``anyOf`` / ``allOf``)
    are caller-skipped and never reach this function.
    """

    out: list[DivergenceRecord] = []

    spec_props = spec_schema.get("properties") or {}
    if not isinstance(spec_props, dict):
        spec_props = {}
    spec_required = set(spec_schema.get("required") or [])
    if not isinstance(spec_required, set):
        spec_required = set()

    ts_props = ts_export.get("properties") or []
    ts_index_by_normalized = {
        _normalize_property_name(str(p.get("name", "") or "")): p
        for p in ts_props
        if isinstance(p, dict)
    }
    ts_names = {str(p.get("name", "") or "") for p in ts_props if isinstance(p, dict)}
    ts_line = int(ts_export.get("line", 0) or 0)

    for spec_prop_name, spec_prop_schema in spec_props.items():
        if not isinstance(spec_prop_name, str):
            continue
        normalized = _normalize_property_name(spec_prop_name)
        ts_prop = ts_index_by_normalized.get(normalized)

        if ts_prop is None:
            # Property-level missing-export (reviewer correction #1):
            # spec.<schema>.<prop> exists but the generated TS export
            # has no normalised match for that property. Whole-schema
            # missing is caught in the caller via the index lookup;
            # this branch covers the more common case where the export
            # is present but lost a property.
            #
            # Reuse ``DIVERGENCE_CLASS_MISSING_EXPORT`` with
            # ``property_name`` populated so the §K.2 evaluator can
            # disambiguate property-scope from schema-scope by
            # checking ``property_name != ""``. The K.2
            # distinct-``(class, schema_name)``-pair predicate is
            # preserved — N missing properties on one schema still
            # collapse to one ``(missing-export, <schema>)`` pair.
            out.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_MISSING_EXPORT,
                    schema_name=schema_name,
                    property_name=spec_prop_name,
                    spec_value=spec_prop_name,
                    client_value="",
                    client_file=client_file_rel,
                    client_line=ts_line,
                    details=(
                        f"OpenAPI components.schemas.{schema_name}."
                        f"properties.{spec_prop_name} has no matching "
                        f"property in generated client export "
                        f"'{schema_name}'"
                    ),
                )
            )
            continue

        ts_prop_name = str(ts_prop.get("name", "") or "")

        # Case-only mismatch — same normalized name, different case on disk.
        if ts_prop_name != spec_prop_name and ts_prop_name not in ts_names - {ts_prop_name}:
            out.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    schema_name=schema_name,
                    property_name=spec_prop_name,
                    spec_value=spec_prop_name,
                    client_value=ts_prop_name,
                    client_file=client_file_rel,
                    client_line=ts_line,
                    details=(
                        f"property '{spec_prop_name}' (OpenAPI) differs in case "
                        f"from '{ts_prop_name}' (generated client)"
                    ),
                )
            )

        # Optional-vs-required mismatch.
        spec_required_for_prop = spec_prop_name in spec_required
        ts_optional = bool(ts_prop.get("optional", False))
        if spec_required_for_prop and ts_optional:
            out.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
                    schema_name=schema_name,
                    property_name=spec_prop_name,
                    spec_value="required",
                    client_value="optional",
                    client_file=client_file_rel,
                    client_line=ts_line,
                    details=(
                        f"property '{spec_prop_name}' is required in OpenAPI "
                        f"but optional ('?:') in generated client"
                    ),
                )
            )
        elif (not spec_required_for_prop) and (not ts_optional):
            out.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
                    schema_name=schema_name,
                    property_name=spec_prop_name,
                    spec_value="optional",
                    client_value="required",
                    client_file=client_file_rel,
                    client_line=ts_line,
                    details=(
                        f"property '{spec_prop_name}' is optional in OpenAPI "
                        f"but required (no '?:') in generated client"
                    ),
                )
            )

        # Type-class mismatch — only after we know the property is present
        # (case mismatch is reported separately above so the operator can
        # disambiguate).
        spec_class = _classify_openapi_type(
            spec_prop_schema if isinstance(spec_prop_schema, dict) else {},
            schemas,
        )
        ts_class = _classify_ts_type(str(ts_prop.get("typeText", "") or ""))
        if spec_class == "polymorphic" or ts_class in ("unknown",):
            # Skip polymorphic / unparseable shapes — they don't inflate
            # the divergence count (correction #1).
            continue
        if spec_class == "unknown":
            continue
        if spec_class != ts_class:
            out.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_TYPE_MISMATCH,
                    schema_name=schema_name,
                    property_name=spec_prop_name,
                    spec_value=spec_class,
                    client_value=ts_class,
                    client_file=client_file_rel,
                    client_line=ts_line,
                    details=(
                        f"property '{spec_prop_name}' type-class differs: "
                        f"spec={spec_class!r} client={ts_class!r}"
                    ),
                )
            )

    return out


def _to_relative(path: Path, project_root: Path) -> str:
    """Return *path* relative to *project_root* (POSIX) or absolute as fallback."""

    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass
class DiagnosticOutcome:
    """Outcome of one Wave C diagnostic run.

    ``divergences`` is the operator-visible drift list (each becomes one
    ``WaveFinding`` advisory). ``metrics`` powers the §K.2 evaluator's
    correlated-divergence count. ``tooling`` exposes the parser used and
    any error string the Node helper surfaced — visible in
    ``PHASE_5_8A_DIAGNOSTIC.json`` (per Q3, tooling-unavailable does NOT
    emit drift findings).
    """

    divergences: list[DivergenceRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    tooling: dict[str, Any] = field(default_factory=dict)
    unsupported_polymorphic_schemas: list[str] = field(default_factory=list)


def compute_divergences(
    spec_path: str | Path,
    client_dir: str | Path,
    project_root: str | Path,
    *,
    node_bin: str | None = None,
    parser_override: Any | None = None,
) -> DiagnosticOutcome:
    """Compare the OpenAPI spec at *spec_path* to ``packages/api-client/`` types.

    Crash-isolated. ``parser_override`` is for tests — a callable
    ``(file_path, project_root) -> dict`` matching the
    :func:`_run_node_parser` return shape.

    Returns a :class:`DiagnosticOutcome` with:

    * ``divergences`` — per-divergence record list (empty on tooling failure).
    * ``metrics`` — ``schemas_in_spec``, ``exports_in_client``,
      ``divergences_detected_total``, ``unique_divergence_classes`` (sorted
      enum slice).
    * ``tooling`` — ``ts_parser`` (``"node-typescript-ast"`` or ``"unavailable"``),
      ``ts_parser_version`` (``ts.version`` from Node helper, ``""`` on failure),
      and ``error`` (failure reason, ``""`` on success).
    * ``unsupported_polymorphic_schemas`` — names of schemas skipped as
      polymorphic (``oneOf``/``anyOf``/``allOf``); these do NOT count toward
      ``divergences_detected_total``.
    """

    outcome = DiagnosticOutcome()
    spec_path = Path(spec_path)
    client_dir_path = Path(client_dir)
    project_root_path = Path(project_root)

    spec = _load_openapi_spec(spec_path)
    if spec is None:
        outcome.tooling = {
            "ts_parser": TOOLING_PARSER_UNAVAILABLE,
            "ts_parser_version": "",
            "error": f"spec_load_failed: {spec_path.as_posix()}",
        }
        outcome.metrics = {
            "schemas_in_spec": 0,
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        }
        return outcome

    schemas_raw = ((spec.get("components") or {}).get("schemas")) or {}
    schemas: dict[str, Any] = schemas_raw if isinstance(schemas_raw, dict) else {}

    types_gen_path = _gather_client_exports(client_dir_path)
    if types_gen_path is None:
        outcome.tooling = {
            "ts_parser": TOOLING_PARSER_UNAVAILABLE,
            "ts_parser_version": "",
            "error": (
                f"client_types_gen_missing: "
                f"{(client_dir_path / 'types.gen.ts').as_posix()}"
            ),
        }
        outcome.metrics = {
            "schemas_in_spec": len(schemas),
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        }
        return outcome

    if parser_override is not None:
        try:
            ts_parse = parser_override(types_gen_path, project_root_path)
        except Exception as exc:  # pragma: no cover — defensive
            ts_parse = {"exports": [], "error": f"parser_override_failed: {exc}"}
    else:
        ts_parse = _run_node_parser(
            types_gen_path,
            project_root_path,
            node_bin=node_bin,
        )

    parser_error = str(ts_parse.get("error", "") or "")
    if parser_error:
        outcome.tooling = {
            "ts_parser": TOOLING_PARSER_UNAVAILABLE,
            "ts_parser_version": "",
            "error": parser_error,
        }
        outcome.metrics = {
            "schemas_in_spec": len(schemas),
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        }
        return outcome

    ts_index = _index_ts_exports(ts_parse)
    client_file_rel = _to_relative(types_gen_path, project_root_path)

    divergences: list[DivergenceRecord] = []
    polymorphic_skips: list[str] = []

    for schema_name in sorted(schemas):
        spec_schema = schemas.get(schema_name)
        if not isinstance(spec_schema, dict):
            continue

        if _is_polymorphic_schema(spec_schema):
            polymorphic_skips.append(schema_name)
            continue

        # Only structural object schemas are compared. Top-level primitive
        # / enum aliases (e.g., ``type X = string``) are skipped to avoid
        # false-positive type-class drift on derived alias TS shapes.
        if "properties" not in spec_schema and not isinstance(
            spec_schema.get("required"), list,
        ):
            continue

        ts_export = ts_index.get(schema_name)
        if ts_export is None:
            divergences.append(
                DivergenceRecord(
                    divergence_class=DIVERGENCE_CLASS_MISSING_EXPORT,
                    schema_name=schema_name,
                    property_name="",
                    spec_value=schema_name,
                    client_value="",
                    client_file=client_file_rel,
                    client_line=0,
                    details=(
                        f"OpenAPI components.schemas.{schema_name} has no "
                        f"matching 'export type {schema_name}' in generated client"
                    ),
                )
            )
            continue

        divergences.extend(
            _compare_schema(
                schema_name,
                spec_schema,
                ts_export,
                schemas,
                client_file_rel,
            )
        )

    unique_classes = sorted({d.divergence_class for d in divergences})
    outcome.divergences = divergences
    outcome.metrics = {
        "schemas_in_spec": len(schemas),
        "exports_in_client": len(ts_index),
        "divergences_detected_total": len(divergences),
        "unique_divergence_classes": unique_classes,
    }
    outcome.tooling = {
        "ts_parser": str(ts_parse.get("parser", TOOLING_PARSER_NODE_TS_AST)),
        "ts_parser_version": str(ts_parse.get("tsVersion", "") or ""),
        "error": "",
    }
    outcome.unsupported_polymorphic_schemas = polymorphic_skips
    return outcome


# ---------------------------------------------------------------------------
# Wave finding rendering + per-milestone artifact writer.
# ---------------------------------------------------------------------------


def _build_advisory_message(record: DivergenceRecord) -> str:
    """Render the WaveFinding message with explicit advisory wording.

    Per scope check-in correction #2: when this finding enters the audit
    context (via ``persist_wave_findings_for_audit`` →
    ``cli.py:_format_wave_findings_for_audit`` → audit prompt), the scorer
    is instructed to treat ``CONTRACT-DRIFT-DIAGNOSTIC-001`` as advisory
    (verdict=UNVERIFIED, severity=LOW). The inline wording here is the
    second line of defence — even if the auditor never reads
    ``audit_prompts.py`` extension, the message itself states the
    advisory contract.
    """

    schema_part = record.schema_name or "<schema>"
    prop_part = record.property_name or ""
    suffix = ""
    if prop_part:
        suffix = f" property={prop_part}"
    return (
        f"[Phase 5.8a advisory; verdict=UNVERIFIED, severity=LOW; "
        f"does NOT block Quality Contract] "
        f"divergence={record.divergence_class} schema={schema_part}{suffix}"
        f" — spec={record.spec_value!r} client={record.client_value!r}. "
        f"{record.details}"
    )


def divergences_to_finding_dicts(
    outcome: DiagnosticOutcome,
) -> list[dict[str, Any]]:
    """Serialise divergences into the dict-shape that ``_coerce_contract_result``
    threads from :class:`ContractResult` into :func:`_execute_wave_c`.

    Each entry has the WaveFinding kwargs (``code`` / ``severity`` / ``file``
    / ``line`` / ``message``) plus the original ``divergence_class`` for the
    PHASE_5_8A_DIAGNOSTIC.json artifact.
    """

    out: list[dict[str, Any]] = []
    for rec in outcome.divergences:
        out.append(
            {
                "code": CONTRACT_DRIFT_DIAGNOSTIC_CODE,
                "severity": DIAGNOSTIC_SEVERITY,
                "file": rec.client_file,
                "line": int(rec.client_line or 0),
                "message": _build_advisory_message(rec),
                "divergence_class": rec.divergence_class,
                "schema_name": rec.schema_name,
                "property_name": rec.property_name,
                "spec_value": rec.spec_value,
                "client_value": rec.client_value,
                "details": rec.details,
            }
        )
    return out


def _milestone_diagnostic_path(cwd: str | Path, milestone_id: str) -> Path:
    """Per-milestone artifact path (correction #3 — M1+M2 cannot collide)."""

    return (
        Path(cwd)
        / ".agent-team"
        / "milestones"
        / str(milestone_id)
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )


_STRICT_MODE_TRUE_TOKENS = frozenset({"ON", "TRUE", "1", "YES"})
_STRICT_MODE_FALSE_TOKENS = frozenset({"OFF", "FALSE", "0", "NO"})


def _normalize_strict_mode(strict_mode: bool | str | None) -> str | None:
    """Normalize a strict-mode value to ``"ON"`` / ``"OFF"`` / ``None``.

    Phase 5 closeout-smoke plan approver constraint #1: every diagnostic
    artifact records strict_mode so the K.2 evaluator can default-filter
    to strict=ON. Accepts:

    * ``None`` → ``None`` (caller did not pass a value; preserve legacy
      shape — DO NOT record the field on the artifact).
    * ``True`` → ``"ON"``; ``False`` → ``"OFF"``.
    * Strings recognised under either token set are normalised
      case-insensitively. Unrecognised strings raise ``ValueError`` so
      the caller catches the typo before writing a corrupted artifact.
    """

    if strict_mode is None:
        return None
    if isinstance(strict_mode, bool):
        return "ON" if strict_mode else "OFF"
    token = str(strict_mode).strip().upper()
    if token in _STRICT_MODE_TRUE_TOKENS:
        return "ON"
    if token in _STRICT_MODE_FALSE_TOKENS:
        return "OFF"
    raise ValueError(
        f"Phase 5.8a write_phase_5_8a_diagnostic: unrecognised strict_mode "
        f"value {strict_mode!r}; expected None / bool / one of "
        f"{sorted(_STRICT_MODE_TRUE_TOKENS | _STRICT_MODE_FALSE_TOKENS)}."
    )


def write_phase_5_8a_diagnostic(
    cwd: str | Path,
    milestone_id: str,
    outcome: DiagnosticOutcome,
    *,
    smoke_id: str = "",
    correlated_compile_failures: int = 0,
    timestamp: str | None = None,
    strict_mode: bool | str | None = None,
) -> Path | None:
    """Write the per-milestone ``PHASE_5_8A_DIAGNOSTIC.json`` artifact.

    Best-effort on filesystem failure: returns ``None`` and does NOT
    raise (the diagnostic is advisory and must never break Wave C — Q2
    contract). The ONE exception is :class:`ValueError` from
    :func:`_normalize_strict_mode` when *strict_mode* is a non-None
    value the normaliser does not recognise (typo guard — surfaces
    BEFORE any artifact write so a corrupt label cannot reach disk).
    The runtime Wave C path passes ``bool``, which never trips that
    case; the production emit helper is additionally crash-isolated
    upstream.

    The K.2 evaluator reads this file (per-smoke-run, per-milestone) to
    aggregate divergence-class × distinct-DTO counts and decide whether
    to ship Phase 5.8b.

    The optional *strict_mode* kwarg records the runtime
    ``runtime_verification.tsc_strict_check_enabled`` setting so the K.2
    evaluator can apply approver-constraint #1 (count strict=ON only by
    default; strict=OFF + missing-strict-mode excluded). When
    ``strict_mode`` is ``None`` (default) the field is OMITTED from the
    artifact — legacy shape preserved byte-identical for callers that
    don't supply the value.

    Schema (locked by AC8 + Phase 5 closeout):

    .. code-block:: json

       {
         "phase": "5.8a",
         "milestone_id": "<id>",
         "smoke_id": "<run-dir-stem>",
         "generated_at": "<ISO-8601>",
         "strict_mode": "ON" | "OFF",   // optional — added when caller passes the value
         "metrics": {
           "schemas_in_spec": int,
           "exports_in_client": int,
           "divergences_detected_total": int,
           "unique_divergence_classes": ["camelCase-vs-snake_case", ...],
           "divergences_correlated_with_compile_failures": int
         },
         "divergences": [
           {
             "divergence_class": "...",
             "schema_name": "...",
             "property_name": "...",
             "spec_value": "...",
             "client_value": "...",
             "client_file": "...",
             "client_line": int,
             "details": "..."
           }
         ],
         "unsupported_polymorphic_schemas": ["..."],
         "tooling": {
           "ts_parser": "node-typescript-ast" | "unavailable",
           "ts_parser_version": "<tsc version>" | "",
           "error": "<reason>" | ""
         }
       }
    """

    if not milestone_id:
        return None

    target = _milestone_diagnostic_path(cwd, milestone_id)
    metrics = dict(outcome.metrics)
    metrics["divergences_correlated_with_compile_failures"] = int(
        correlated_compile_failures or 0,
    )

    normalized_strict = _normalize_strict_mode(strict_mode)

    payload: dict[str, Any] = {
        "phase": "5.8a",
        "milestone_id": str(milestone_id),
        "smoke_id": smoke_id or "",
        "generated_at": timestamp or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00",
        ),
        "metrics": metrics,
        "divergences": [d.to_dict() for d in outcome.divergences],
        "unsupported_polymorphic_schemas": list(
            outcome.unsupported_polymorphic_schemas,
        ),
        "tooling": dict(outcome.tooling),
    }
    # Only set strict_mode when the caller supplied a value. Legacy
    # callers (default kwarg) get byte-identical schema vs pre-Phase-5
    # closeout output.
    if normalized_strict is not None:
        payload["strict_mode"] = normalized_strict

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - best effort
        logger.warning(
            "Phase 5.8a — failed to write %s: %s",
            target.as_posix(),
            exc,
        )
        return None
    return target


# ---------------------------------------------------------------------------
# §K.2 decision-gate predicate (locked by fixture).
# ---------------------------------------------------------------------------


def k2_decision_gate_satisfied(
    per_milestone_diagnostics: list[dict[str, Any]],
    *,
    correlated_threshold: int = 3,
) -> bool:
    """Evaluate the §K.2 stop-early predicate.

    The predicate (locked here so the eventual K.2 evaluator session reads
    the same definition):

        ``correlated_threshold`` correlated divergences = at least
        ``correlated_threshold`` distinct ``(divergence_class,
        schema_name)`` pairs that share the SAME ``divergence_class``
        across the smoke batch.

    NOT 3 instances of the same ``(class, schema, property)`` triple on
    one smoke. NOT 3 properties on one DTO with the same class. The
    distinct-schema discipline is what makes correlation a real signal
    rather than a hot-spot artefact.

    ``per_milestone_diagnostics`` is the list of decoded
    ``PHASE_5_8A_DIAGNOSTIC.json`` payloads across the smoke batch (one
    per milestone × smoke run).
    """

    if not per_milestone_diagnostics:
        return False
    by_class_schemas: dict[str, set[str]] = {}
    for diag in per_milestone_diagnostics:
        if not isinstance(diag, dict):
            continue
        for record in diag.get("divergences", []) or []:
            if not isinstance(record, dict):
                continue
            cls = str(record.get("divergence_class", "") or "")
            schema = str(record.get("schema_name", "") or "")
            if not cls or not schema:
                continue
            by_class_schemas.setdefault(cls, set()).add(schema)
    return any(
        len(schemas) >= max(1, correlated_threshold)
        for schemas in by_class_schemas.values()
    )


__all__ = (
    "CONTRACT_DRIFT_DIAGNOSTIC_CODE",
    "DIAGNOSTIC_SEVERITY",
    "DIAGNOSTIC_VERDICT_HINT",
    "DIAGNOSTIC_LOG_TAG",
    "PHASE_5_8A_DIAGNOSTIC_FILENAME",
    "DIVERGENCE_CLASS_MISSING_EXPORT",
    "DIVERGENCE_CLASS_CAMEL_VS_SNAKE",
    "DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED",
    "DIVERGENCE_CLASS_TYPE_MISMATCH",
    "ALL_DIVERGENCE_CLASSES",
    "TOOLING_PARSER_NODE_TS_AST",
    "TOOLING_PARSER_UNAVAILABLE",
    "DivergenceRecord",
    "DiagnosticOutcome",
    "compute_divergences",
    "divergences_to_finding_dicts",
    "write_phase_5_8a_diagnostic",
    "k2_decision_gate_satisfied",
)
