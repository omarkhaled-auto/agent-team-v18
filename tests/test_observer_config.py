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
