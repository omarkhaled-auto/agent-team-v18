"""Regression fence for the pnpm-monorepo root ``package.json`` scaffold.

The scaffolder emits a root ``package.json`` that drives ``pnpm install``
(``_install_workspace_deps_if_needed`` in ``wave_executor.py``). Without a
root ``devDependencies.typescript`` entry, pnpm / npm workspaces will NOT
hoist ``tsc`` into root ``node_modules/.bin/`` — so ``npx tsc`` invoked
from the repo root by the compile-check harness falls through to the
Windows App Execution Alias placeholder and emits ``ENV_NOT_READY``. That
failure burned the Wave B compile-fix retry budget in R1B1
(2026-04-22): Codex diagnosed the defect and re-added the root pin
mid-flight, but the retry loop exhausted before the fix landed.

These tests fence the structural fix so the same class of failure cannot
regress silently:

1. ``test_root_package_json_declares_typescript_devdep`` — proves the pin
   is present at scaffold time.
2. ``test_root_typescript_pin_matches_api_and_web_templates`` — fences
   drift between root / api / web. If any one moves, all three must move
   together, otherwise pnpm resolution falls back to hoisting whichever
   version wins the semver race — which defeats the deterministic
   bootstrap guarantee.
"""

from __future__ import annotations

import json

from agent_team_v15.scaffold_runner import (
    _api_package_json_template,
    _root_package_json_template,
    _web_package_json_template,
)


def test_root_package_json_declares_typescript_devdep() -> None:
    raw = _root_package_json_template()
    parsed = json.loads(raw)

    assert parsed.get("packageManager") == "pnpm@10.17.1"

    dev_deps = parsed.get("devDependencies")
    assert isinstance(dev_deps, dict), (
        "root package.json must declare a devDependencies object so pnpm "
        "hoists workspace bins (notably tsc) into root node_modules/.bin/; "
        f"got {type(dev_deps).__name__}"
    )

    typescript_pin = dev_deps.get("typescript")
    assert typescript_pin, (
        "root package.json must pin ``typescript`` as a devDependency to "
        "force pnpm / npm workspaces to hoist tsc into root "
        "node_modules/.bin/ — without this, ``npx tsc`` at the repo root "
        "hits the Windows App Execution Alias placeholder and emits "
        "ENV_NOT_READY in compile_profiles.py."
    )


def test_root_typescript_pin_matches_api_and_web_templates() -> None:
    root_pin = json.loads(_root_package_json_template())["devDependencies"]["typescript"]
    api_pin = json.loads(_api_package_json_template())["devDependencies"]["typescript"]
    web_pin = json.loads(_web_package_json_template())["devDependencies"]["typescript"]

    assert root_pin == api_pin == web_pin, (
        "root / apps/api / apps/web must pin the same ``typescript`` "
        "version so pnpm's hoist is deterministic. Drift between these "
        "three would let pnpm resolve whichever version wins the semver "
        "race at install-time, breaking the scaffold-time bootstrap "
        f"guarantee. root={root_pin!r} api={api_pin!r} web={web_pin!r}"
    )


def test_api_lint_disables_incremental_cache_writes() -> None:
    scripts = json.loads(_api_package_json_template())["scripts"]
    assert scripts["lint"] == "tsc --noEmit --incremental false -p tsconfig.json"
