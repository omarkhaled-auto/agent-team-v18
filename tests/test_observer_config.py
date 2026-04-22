from agent_team_v15.config import AgentTeamConfig, ObserverConfig


def test_observer_config_defaults():
    cfg = ObserverConfig()
    assert cfg.enabled is False
    assert cfg.log_only is True  # SAFE DEFAULT - never interrupts without explicit opt-in
    assert cfg.confidence_threshold == 0.75
    assert cfg.model == "claude-haiku-4-5-20251001"
    assert cfg.max_tokens == 512
    assert cfg.codex_notification_observer_enabled is True


def test_observer_config_in_parent():
    cfg = AgentTeamConfig()
    assert hasattr(cfg, "observer")
    assert isinstance(cfg.observer, ObserverConfig)


def test_observer_config_context7_fallback_default():
    cfg = ObserverConfig()
    assert cfg.context7_enabled is True
    assert cfg.context7_fallback_to_training is True
    assert cfg.time_based_interval_seconds == 300.0
    assert cfg.max_peeks_per_wave == 5
    assert cfg.peek_cooldown_seconds == 60.0
    assert cfg.peek_timeout_seconds == 30.0


def test_observer_config_min_waves_covered_default():
    """Default is 2 - grounded in the 61-entry corpus across 7 preserved
    smoke runs (2026-04-21..22). Wave C is provider="python" (no peek),
    T/E audit waves write to skip-dirs with empty trigger_files, and A5/T5
    depend on optional Codex-notification flags, so the realistic observable
    surface in CLIBackend Round 1 is 2-3 waves."""
    cfg = ObserverConfig()
    assert cfg.min_waves_covered == 2


def test_observer_config_min_waves_covered_yaml_override(tmp_path):
    """YAML ``observer.min_waves_covered`` is picked up by the loader."""
    from agent_team_v15.config import load_config

    cfg_path = tmp_path / "agent-team.yaml"
    cfg_path.write_text(
        "observer:\n  min_waves_covered: 4\n",
        encoding="utf-8",
    )
    cfg, _overrides = load_config(str(cfg_path))
    assert cfg.observer.min_waves_covered == 4
