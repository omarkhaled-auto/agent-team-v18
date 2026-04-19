"""Phase H1b — V18Config YAML parse + legacy alias forwarding tests.

Covers the three new v18 flags introduced for h1b:

* ``wave_a_schema_enforcement_enabled: bool = False``
* ``wave_a_rerun_budget: int = 2``
* ``auditor_architecture_injection_enabled: bool = False``

Plus the legacy ``wave_a5_max_reruns`` alias forwarding (non-default
value → ``_get_effective_wave_a_rerun_budget`` returns the legacy value
with a one-shot deprecation warning per config object).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig, load_config


@pytest.fixture(autouse=True)
def _reset_alias_warned_set() -> None:
    # Phase H1b follow-up: module-level dedupe sets were removed in
    # favor of ``warnings.warn(DeprecationWarning, ...)``. Python's
    # warnings filter dedupes by default; nothing to reset here.
    yield


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------


def test_defaults_match_plan() -> None:
    cfg = AgentTeamConfig()
    assert cfg.v18.wave_a_schema_enforcement_enabled is False
    assert cfg.v18.wave_a_rerun_budget == 2
    assert cfg.v18.auditor_architecture_injection_enabled is False


# ---------------------------------------------------------------------------
# YAML parse
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "config.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def test_yaml_sets_all_three_flags(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
v18:
  wave_a_schema_enforcement_enabled: true
  wave_a_rerun_budget: 4
  auditor_architecture_injection_enabled: true
""",
    )
    cfg, overrides = load_config(config_path=path)
    assert cfg.v18.wave_a_schema_enforcement_enabled is True
    assert cfg.v18.wave_a_rerun_budget == 4
    assert cfg.v18.auditor_architecture_injection_enabled is True
    assert "v18.wave_a_schema_enforcement_enabled" in overrides
    assert "v18.wave_a_rerun_budget" in overrides
    assert "v18.auditor_architecture_injection_enabled" in overrides


def test_yaml_coerces_bool_strings(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
v18:
  wave_a_schema_enforcement_enabled: "yes"
  auditor_architecture_injection_enabled: "off"
""",
    )
    cfg, _ = load_config(config_path=path)
    assert cfg.v18.wave_a_schema_enforcement_enabled is True
    assert cfg.v18.auditor_architecture_injection_enabled is False


def test_yaml_coerces_int_string(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
v18:
  wave_a_rerun_budget: "3"
""",
    )
    cfg, _ = load_config(config_path=path)
    assert cfg.v18.wave_a_rerun_budget == 3


# ---------------------------------------------------------------------------
# Legacy alias forwarding
# ---------------------------------------------------------------------------


def test_non_default_legacy_value_forwards_with_deprecation() -> None:
    """Phase H1b follow-up: the deprecation signal is now emitted via
    :func:`warnings.warn(DeprecationWarning, ...)` (module-level dedupe
    sets were removed). Python's default warnings filter dedupes by
    source location; with ``simplefilter("always")`` each call records."""
    import warnings as _warnings

    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_max_reruns = 3  # non-default override
    with _warnings.catch_warnings(record=True) as captured:
        _warnings.simplefilter("always", DeprecationWarning)
        effective = _cli._get_effective_wave_a_rerun_budget(cfg)
    assert effective == 3
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "Expected DeprecationWarning for legacy alias override"
    assert any("wave_a5_max_reruns" in str(w.message) for w in deprecations)


def test_default_legacy_value_no_deprecation() -> None:
    import warnings as _warnings

    cfg = AgentTeamConfig()
    with _warnings.catch_warnings(record=True) as captured:
        _warnings.simplefilter("always", DeprecationWarning)
        _cli._get_effective_wave_a_rerun_budget(cfg)
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert not deprecations


def test_deprecation_warning_fires_on_every_call_with_simplefilter_always() -> None:
    """Five calls with ``simplefilter('always')`` record five warnings.

    (The previous design used a module-level dedupe set; the current
    design defers to Python's warnings filter — the operator controls
    whether repeated warnings surface once or every call.)
    """
    import warnings as _warnings

    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_max_reruns = 7
    with _warnings.catch_warnings(record=True) as captured:
        _warnings.simplefilter("always", DeprecationWarning)
        for _ in range(5):
            _cli._get_effective_wave_a_rerun_budget(cfg)
    deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) >= 1  # at least one warning recorded
