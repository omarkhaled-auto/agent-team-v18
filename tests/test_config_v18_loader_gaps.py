"""YAML round-trip coverage for V18Config fields that previously had no loader.

Regression guard for the Phase FINAL config-loader gap audit: every field
defined on ``V18Config`` must round-trip through ``_dict_to_config``. Silent
ignores defeat the entire point of the YAML config surface and have already
caused planned smoke validations to be quietly skipped.

Keys covered here (fixed in commit introducing this test):

- codex_transport_mode            (str,  default "exec")
- codex_orphan_tool_timeout_seconds (int, default 300)
- audit_fix_iteration_enabled     (bool, default False)
- audit_scope_completeness_enabled (bool, default True)
- confidence_banners_enabled      (bool, default True)
- runtime_infra_detection_enabled (bool, default True)
- wave_b_output_sanitization_enabled (bool, default True)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15.config import V18Config, _dict_to_config


# Each tuple: (yaml_key, non_default_value, attribute_name)
_ROUND_TRIP_CASES = [
    ("codex_transport_mode", "app-server", "codex_transport_mode"),
    ("codex_orphan_tool_timeout_seconds", 900, "codex_orphan_tool_timeout_seconds"),
    ("audit_fix_iteration_enabled", True, "audit_fix_iteration_enabled"),
    ("audit_scope_completeness_enabled", False, "audit_scope_completeness_enabled"),
    ("confidence_banners_enabled", False, "confidence_banners_enabled"),
    ("runtime_infra_detection_enabled", False, "runtime_infra_detection_enabled"),
    ("wave_b_output_sanitization_enabled", False, "wave_b_output_sanitization_enabled"),
    # --- Phase H1a v18 flags ---
    ("dod_feasibility_verifier_enabled", True, "dod_feasibility_verifier_enabled"),
    ("ownership_enforcement_enabled", True, "ownership_enforcement_enabled"),
    ("ownership_policy_required", True, "ownership_policy_required"),
    ("codex_capture_enabled", True, "codex_capture_enabled"),
    ("codex_wave_b_prompt_hardening_enabled", True, "codex_wave_b_prompt_hardening_enabled"),
    ("codex_sandbox_writable_enabled", True, "codex_sandbox_writable_enabled"),
    ("codex_sandbox_mode", "dangerFullAccess", "codex_sandbox_mode"),
    ("codex_cwd_propagation_check_enabled", True, "codex_cwd_propagation_check_enabled"),
    ("codex_flush_wait_enabled", True, "codex_flush_wait_enabled"),
    ("codex_flush_wait_seconds", 0.5, "codex_flush_wait_seconds"),
    ("checkpoint_tracker_hardening_enabled", True, "checkpoint_tracker_hardening_enabled"),
    ("codex_blocked_prefix_as_failure_enabled", True, "codex_blocked_prefix_as_failure_enabled"),
    ("probe_spec_oracle_enabled", True, "probe_spec_oracle_enabled"),
    ("runtime_tautology_guard_enabled", True, "runtime_tautology_guard_enabled"),
]


@pytest.mark.parametrize("yaml_key,value,attr", _ROUND_TRIP_CASES)
def test_v18_yaml_round_trip(yaml_key: str, value, attr: str) -> None:
    cfg, overrides = _dict_to_config({"v18": {yaml_key: value}})
    assert getattr(cfg.v18, attr) == value, (
        f"YAML key v18.{yaml_key}={value!r} was silently ignored "
        f"(loaded attr = {getattr(cfg.v18, attr)!r})"
    )
    assert f"v18.{yaml_key}" in overrides


def test_v18_defaults_preserved_when_key_absent() -> None:
    cfg, _ = _dict_to_config({"v18": {}})
    # Spot-check that the patched loaders still honor dataclass defaults
    assert cfg.v18.codex_transport_mode == "exec"
    assert cfg.v18.codex_orphan_tool_timeout_seconds == 300
    assert cfg.v18.audit_fix_iteration_enabled is False
    assert cfg.v18.audit_scope_completeness_enabled is True
    assert cfg.v18.confidence_banners_enabled is True
    assert cfg.v18.runtime_infra_detection_enabled is True
    assert cfg.v18.wave_b_output_sanitization_enabled is True
    # Phase H1a defaults are OFF — production config must flip them ON.
    assert cfg.v18.dod_feasibility_verifier_enabled is False
    assert cfg.v18.ownership_enforcement_enabled is False
    assert cfg.v18.ownership_policy_required is False
    assert cfg.v18.codex_capture_enabled is False
    assert cfg.v18.codex_wave_b_prompt_hardening_enabled is False
    assert cfg.v18.codex_sandbox_writable_enabled is False
    assert cfg.v18.codex_sandbox_mode == "workspace-write"
    assert cfg.v18.codex_cwd_propagation_check_enabled is False
    assert cfg.v18.codex_flush_wait_enabled is False
    assert cfg.v18.codex_flush_wait_seconds == 0.5
    assert cfg.v18.checkpoint_tracker_hardening_enabled is False
    assert cfg.v18.codex_blocked_prefix_as_failure_enabled is False
    assert cfg.v18.probe_spec_oracle_enabled is False
    assert cfg.v18.runtime_tautology_guard_enabled is False


def test_no_v18_loader_gaps_exist() -> None:
    """Structural invariant: every V18Config field has a YAML loader.

    Guards against future fields being added to the dataclass without a
    matching ``_coerce_*(v18.get("name", default), default)`` block.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "config.py"
    text = src.read_text(encoding="utf-8")

    klass_match = re.search(r"class V18Config.*?(?=\nclass |\Z)", text, re.S)
    assert klass_match, "V18Config dataclass not found in config.py"
    klass = klass_match.group(0)

    field_re = re.compile(
        r"^\s{4}([a-z_][a-z0-9_]*)\s*:\s*"
        r"(?:bool|str|int|float|Optional\[[^\]]+\]|List\[[^\]]+\])\b",
        re.M,
    )
    fields = set(field_re.findall(klass))

    loader_keys = set(re.findall(r'v18\.get\(\s*"([a-z_][a-z0-9_]*)"', text))
    loader_keys |= set(
        re.findall(r'"([a-z_][a-z0-9_]*)"\s*,\s*cfg\.v18\.\1\b', text)
    )

    gaps = sorted(fields - loader_keys)
    assert not gaps, (
        "V18Config fields without a YAML loader (silent-ignore gap): "
        + ", ".join(gaps)
    )
