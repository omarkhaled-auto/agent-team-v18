"""Contract verification — check code matches CONTRACTS.md after each milestone.

After each milestone completes, compares the actual code signatures against
the contract specifications. Flags deviations so they can be either:
- Fixed (if the deviation is a bug)
- Propagated (if the deviation is an improvement — update the contract)

This prevents contract staleness: the contracts stay synchronized with
the actual implementation throughout the build.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ContractDeviation:
    """A single deviation between contract and implementation."""
    service: str
    deviation_type: str    # "missing_endpoint", "extra_endpoint", "signature_mismatch", "missing_entity"
    contract_spec: str     # What the contract says
    actual_spec: str       # What the code actually has (or "not found")
    severity: str = "warning"  # "warning" or "info"


@dataclass
class VerificationResult:
    """Result of verifying one service against its contract."""
    service: str
    deviations: list[ContractDeviation] = field(default_factory=list)
    endpoints_expected: int = 0
    endpoints_found: int = 0
    entities_expected: int = 0
    entities_found: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.deviations) == 0


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------

def verify_service_contract(
    service_name: str,
    contract_endpoints: list[dict[str, Any]],
    contract_entities: list[dict[str, Any]],
    actual_endpoints: list[dict[str, Any]],
    actual_types: list[str],
) -> VerificationResult:
    """Verify a service's implementation against its contract.

    Compares:
    - Contract endpoints vs actual route definitions
    - Contract entity names vs actual class/type definitions

    Parameters
    ----------
    service_name : str
        Service identifier.
    contract_endpoints : list
        Expected endpoints from ContractBundle.
    contract_entities : list
        Expected entities from ContractBundle.
    actual_endpoints : list
        Actual endpoints from InterfaceRegistry.
    actual_types : list
        Actual type/class names from InterfaceRegistry.
    """
    result = VerificationResult(
        service=service_name,
        endpoints_expected=len(contract_endpoints),
        entities_expected=len(contract_entities),
    )

    # Normalize actual endpoints for comparison
    actual_paths: dict[str, set[str]] = {}  # path -> set of methods
    for ep in actual_endpoints:
        path = ep.get("path", "") if isinstance(ep, dict) else getattr(ep, "path", "")
        method = ep.get("method", "") if isinstance(ep, dict) else getattr(ep, "method", "")
        actual_paths.setdefault(path.lower().strip("/"), set()).add(method.upper())

    # Check contract endpoints
    for ep in contract_endpoints:
        expected_path = ep.get("path", "").lower().strip("/")
        expected_method = ep.get("method", "").upper()

        # Normalize: remove {id} params for comparison
        normalized = re.sub(r"\{[^}]+\}", ":id", expected_path)

        found = False
        for actual_path, methods in actual_paths.items():
            actual_normalized = re.sub(r"\{[^}]+\}", ":id", actual_path)
            actual_normalized = re.sub(r":[^/]+", ":id", actual_normalized)
            if actual_normalized == normalized and expected_method in methods:
                found = True
                break
            # Fuzzy: check if the last path segment matches
            if normalized.split("/")[-1] == actual_normalized.split("/")[-1] and expected_method in methods:
                found = True
                break

        if found:
            result.endpoints_found += 1
        else:
            result.deviations.append(ContractDeviation(
                service=service_name,
                deviation_type="missing_endpoint",
                contract_spec=f"{expected_method} {ep.get('path', '')}",
                actual_spec="not found",
                severity="info",  # Missing endpoints are common during early milestones
            ))

    # Check contract entities
    actual_types_lower = {t.lower() for t in actual_types}
    for ent in contract_entities:
        ent_name = ent.get("name", "")
        if ent_name.lower() in actual_types_lower:
            result.entities_found += 1
        else:
            result.deviations.append(ContractDeviation(
                service=service_name,
                deviation_type="missing_entity",
                contract_spec=f"Entity: {ent_name}",
                actual_spec="not found in types",
                severity="info",
            ))

    # Check for extra endpoints not in contract (informational)
    # This is normal and expected — services may add health, docs, etc.

    return result


def verify_all_contracts(
    contract_services: list[Any],
    registry_modules: dict[str, Any],
) -> list[VerificationResult]:
    """Verify all services against their contracts.

    Parameters
    ----------
    contract_services : list[ServiceContract]
        From ContractBundle.services.
    registry_modules : dict[str, ModuleInterface]
        From InterfaceRegistry.modules.
    """
    results: list[VerificationResult] = []

    for svc in contract_services:
        svc_name = svc.service_name if hasattr(svc, "service_name") else svc.get("service_name", "")
        entities = svc.entities if hasattr(svc, "entities") else svc.get("entities", [])
        endpoints = svc.endpoints if hasattr(svc, "endpoints") else svc.get("endpoints", [])

        # Find matching registry module
        reg_mod = registry_modules.get(svc_name)
        if reg_mod is None:
            # Service not yet built — all endpoints/entities missing
            results.append(VerificationResult(
                service=svc_name,
                endpoints_expected=len(endpoints),
                entities_expected=len(entities),
                deviations=[ContractDeviation(
                    service=svc_name,
                    deviation_type="missing_module",
                    contract_spec=f"Service: {svc_name}",
                    actual_spec="module not found in registry",
                    severity="info",
                )],
            ))
            continue

        actual_endpoints = [
            {"path": ep.path, "method": ep.method}
            for ep in (reg_mod.endpoints if hasattr(reg_mod, "endpoints") else [])
        ]
        actual_types = reg_mod.types if hasattr(reg_mod, "types") else []

        result = verify_service_contract(
            svc_name, endpoints, entities, actual_endpoints, actual_types,
        )
        results.append(result)

    return results


def format_verification_summary(results: list[VerificationResult]) -> str:
    """Format verification results as compact markdown."""
    if not results:
        return ""

    lines = ["[CONTRACT VERIFICATION — Post-Milestone Check]\n"]

    total_expected_ep = sum(r.endpoints_expected for r in results)
    total_found_ep = sum(r.endpoints_found for r in results)
    total_expected_ent = sum(r.entities_expected for r in results)
    total_found_ent = sum(r.entities_found for r in results)

    lines.append(
        f"Endpoints: {total_found_ep}/{total_expected_ep} implemented | "
        f"Entities: {total_found_ent}/{total_expected_ent} defined\n"
    )

    for result in results:
        if result.is_clean:
            lines.append(f"- {result.service}: CLEAN ({result.endpoints_found} endpoints, {result.entities_found} entities)")
        else:
            warning_count = sum(1 for d in result.deviations if d.severity == "warning")
            info_count = sum(1 for d in result.deviations if d.severity == "info")
            lines.append(
                f"- {result.service}: {len(result.deviations)} deviations "
                f"({warning_count} warnings, {info_count} info)"
            )
            for dev in result.deviations[:5]:
                lines.append(f"    [{dev.deviation_type}] expected: {dev.contract_spec}, actual: {dev.actual_spec}")
            if len(result.deviations) > 5:
                lines.append(f"    ... +{len(result.deviations) - 5} more")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-service client import verification
# ---------------------------------------------------------------------------

_SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "build"}

# Patterns indicating a generated / structured client import
_CLIENT_IMPORT_PATTERNS = [
    re.compile(r"import\s+.*from\s+['\"].*clients/", re.IGNORECASE),
    re.compile(r"from\s+.*clients.*import", re.IGNORECASE),
    re.compile(r"from\s+.*client\s+import", re.IGNORECASE),
    re.compile(r"import\s+.*Client", re.IGNORECASE),
]


def _raw_fetch_patterns(provider: str) -> list[re.Pattern[str]]:
    """Build regex patterns that detect raw HTTP calls to *provider*."""
    p = re.escape(provider)
    p_upper = re.escape(provider.upper())
    return [
        re.compile(rf"fetch\s*\(.*{p}", re.IGNORECASE),
        re.compile(rf"axios.*{p}", re.IGNORECASE),
        re.compile(rf"httpx.*{p}", re.IGNORECASE),
        re.compile(rf"this\.{p}ServiceUrl", re.IGNORECASE),
        re.compile(rf"{p}_SERVICE_URL", re.IGNORECASE),
        re.compile(rf"{p_upper}_SERVICE_URL"),
    ]


def _iter_source_files(root: Path):
    """Yield .ts and .py files under *root*, skipping irrelevant dirs."""
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            if child.name in _SKIP_DIRS:
                continue
            yield from _iter_source_files(child)
        elif child.suffix in (".ts", ".py"):
            yield child


def verify_client_imports(
    project_root: Path,
    cross_service_deps: list[dict[str, str]] | None = None,
) -> list[ContractDeviation]:
    """Check that cross-service calls use generated contract clients.

    For each dependency in *cross_service_deps*, scans the consumer's
    source files for either:
    - A proper generated client import (good — no deviation), or
    - Raw fetch/axios/httpx calls to the provider (warning deviation), or
    - Neither (info deviation).

    Parameters
    ----------
    project_root : Path
        Root of the generated project (contains ``services/`` directory).
    cross_service_deps : list[dict] | None
        Each dict has ``"consumer"`` and ``"provider"`` keys.

    Returns
    -------
    list[ContractDeviation]
    """
    if not cross_service_deps:
        return []

    deviations: list[ContractDeviation] = []

    for dep in cross_service_deps:
        consumer = dep.get("consumer", "")
        provider = dep.get("provider", "")
        if not consumer or not provider:
            continue

        service_dir = project_root / "services" / consumer
        if not service_dir.is_dir():
            deviations.append(ContractDeviation(
                service=consumer,
                deviation_type="missing_client_import",
                contract_spec=f"{consumer} -> {provider} (generated client)",
                actual_spec="consumer service directory not found",
                severity="info",
            ))
            continue

        source_files = list(_iter_source_files(service_dir))

        has_client_import = False
        has_raw_fetch = False
        raw_fetch_pats = _raw_fetch_patterns(provider)

        for fpath in source_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pat in _CLIENT_IMPORT_PATTERNS:
                if pat.search(content):
                    has_client_import = True
                    break

            for pat in raw_fetch_pats:
                if pat.search(content):
                    has_raw_fetch = True
                    break

            # Early exit if both detected
            if has_client_import and has_raw_fetch:
                break

        if has_client_import:
            # Proper client import found — no deviation
            continue

        if has_raw_fetch:
            deviations.append(ContractDeviation(
                service=consumer,
                deviation_type="raw_fetch",
                contract_spec=f"{consumer} -> {provider} (generated client)",
                actual_spec=f"uses raw fetch instead of generated contract client",
                severity="warning",
            ))
        else:
            deviations.append(ContractDeviation(
                service=consumer,
                deviation_type="missing_client_import",
                contract_spec=f"{consumer} -> {provider} (generated client)",
                actual_spec="no cross-service call detected",
                severity="info",
            ))

    return deviations
