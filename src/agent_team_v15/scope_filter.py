"""A-09: filter an IR dict to a single milestone's scope.

Paired with :mod:`agent_team_v15.milestone_scope` — the wave pipeline
uses ``filter_ir_to_scope`` to strip entities, endpoints, and i18n
namespaces that belong to later milestones *before* the IR is ever
placed in a wave prompt. Without this, the builder saw the full PRD
spec and over-produced M2–M5 artefacts during M1 execution.

The filter is a projection, not a mutation — it returns a new
:class:`FilteredIR` and leaves the input ``ir`` dict untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .milestone_scope import MilestoneScope


@dataclass
class FilteredIR:
    """A scope-restricted view of an IR dict."""

    milestone_id: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    endpoints: list[dict[str, Any]] = field(default_factory=list)
    translations: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def filter_ir_to_scope(ir: Any, scope: MilestoneScope) -> FilteredIR:
    """Restrict the given IR to entries whose refs match *scope*."""
    ir_dict = ir if isinstance(ir, dict) else _as_dict(ir)

    allowed_entities = {e.strip() for e in scope.allowed_entities}
    allowed_feature_refs = {f.strip() for f in scope.allowed_feature_refs}
    allowed_ac_refs = {a.strip() for a in scope.allowed_ac_refs}
    allowed_translation_namespaces = _derive_translation_namespaces(scope)

    entities = _filter_entities(
        ir_dict.get("entities") or [],
        allowed_entities,
    )
    endpoints = _filter_endpoints(
        ir_dict.get("endpoints") or [],
        allowed_feature_refs,
        allowed_ac_refs,
    )
    translations = _filter_translations(
        ir_dict.get("translations") or {},
        allowed_translation_namespaces,
    )

    return FilteredIR(
        milestone_id=scope.milestone_id,
        entities=entities,
        endpoints=endpoints,
        translations=translations,
        raw=ir_dict,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    try:
        return dict(obj)
    except Exception:
        return {}


def _filter_entities(
    entities: Iterable[Any],
    allowed_entities: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entity in entities:
        entity_dict = entity if isinstance(entity, dict) else _as_dict(entity)
        name = str(entity_dict.get("name", "")).strip()
        if not name:
            continue
        if name in allowed_entities:
            out.append(entity_dict)
    return out


def _filter_endpoints(
    endpoints: Iterable[Any],
    allowed_feature_refs: set[str],
    allowed_ac_refs: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for endpoint in endpoints:
        ep_dict = endpoint if isinstance(endpoint, dict) else _as_dict(endpoint)
        feature_ref = str(ep_dict.get("feature_ref", "")).strip()
        ac_refs = ep_dict.get("ac_refs") or []
        if not isinstance(ac_refs, (list, tuple)):
            ac_refs = [ac_refs]
        ac_ref_set = {str(a).strip() for a in ac_refs if str(a).strip()}

        if feature_ref and feature_ref in allowed_feature_refs:
            out.append(ep_dict)
            continue
        if ac_ref_set & allowed_ac_refs:
            out.append(ep_dict)
    return out


def _derive_translation_namespaces(scope: MilestoneScope) -> set[str]:
    """Translate allowed feature refs to i18n namespace guesses.

    e.g. ``F-PROJ`` → ``projects``; ``F-AUTH`` → ``auth``. Unknown refs
    fall back to the lowercased feature ref stripped of the ``F-`` prefix.
    """
    mapping = {
        "F-AUTH": "auth",
        "F-PROJ": "projects",
        "F-TASK": "tasks",
        "F-COMMENT": "comments",
        "F-MEMBER": "members",
        "F-TEAM": "team",
        "F-USER": "users",
    }
    namespaces: set[str] = set()
    for ref in scope.allowed_feature_refs:
        ref_key = ref.strip()
        if ref_key in mapping:
            namespaces.add(mapping[ref_key])
        elif ref_key.startswith("F-"):
            namespaces.add(ref_key[2:].lower())
    return namespaces


def _filter_translations(
    translations: dict[str, Any],
    allowed_namespaces: set[str],
) -> dict[str, Any]:
    if not translations:
        return {}
    if not allowed_namespaces:
        return {}
    return {
        ns: payload
        for ns, payload in translations.items()
        if ns in allowed_namespaces
    }


__all__ = ["FilteredIR", "filter_ir_to_scope"]
