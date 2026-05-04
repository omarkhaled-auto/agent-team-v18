"""Tests for D-02 — runtime verification graceful-block.

Covers ``run_runtime_verification``'s new ``health`` / ``block_reason``
/ ``details`` fields. Before D-02 the function silently returned an
empty ``RuntimeReport`` whenever Docker or the compose file was
missing, and the markdown report read "runtime verification skipped"
— indistinguishable from an intentional opt-out. With D-02 the
behaviour splits:

- ``live_endpoint_check=False`` → ``health="skipped"`` (legacy).
- ``live_endpoint_check=True`` + infra missing → ``health="blocked"``
  with a structured ``block_reason``.
- ``live_endpoint_check=True`` + live app reachable → ``health="external_app"``
  (no Docker boot needed).

All subprocess and network calls are mocked — no real Docker or HTTP
traffic.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_team_v15 import runtime_verification as rv
from agent_team_v15.runtime_verification import (
    RuntimeReport,
    run_runtime_verification,
    format_runtime_report,
    _probe_live_app,
)


# ---------------------------------------------------------------------------
# 1. Compose missing + live_endpoint_check=True → health=blocked
# ---------------------------------------------------------------------------


def test_compose_missing_live_check_opt_in_blocks(tmp_path: Path) -> None:
    """Opt-in to live endpoint verification + no compose + no live app
    → ``health="blocked"`` with ``block_reason="compose_file_missing"``.
    This is the build-j scenario: the pipeline must halt, not silently
    degrade."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )

    assert isinstance(report, RuntimeReport)
    assert report.health == "blocked"
    assert report.block_reason == "compose_file_missing"
    assert report.details["live_endpoint_check"] is True
    assert report.details["live_app_url_checked"] == "http://127.0.0.1:3001"
    assert report.details["live_app_reachable"] is False


# ---------------------------------------------------------------------------
# 2. Compose missing + live_endpoint_check=False → health=skipped
# ---------------------------------------------------------------------------


def test_compose_missing_live_check_opt_out_skips(tmp_path: Path) -> None:
    """Legacy opt-out path preserved — caller didn't request live endpoint
    verification so the lack of compose is a silent ``skipped`` (not a
    block)."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=False,
        )
    assert report.health == "skipped"
    assert report.block_reason == ""


# ---------------------------------------------------------------------------
# 3. Docker unavailable + opt-in → blocked with docker_unavailable reason
# ---------------------------------------------------------------------------


def test_docker_unavailable_opt_in_blocks_with_docker_reason(
    tmp_path: Path,
) -> None:
    with patch.object(rv, "check_docker_available", return_value=False), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )
    assert report.health == "blocked"
    assert report.block_reason == "docker_unavailable"
    assert report.details["live_app_reachable"] is False


# ---------------------------------------------------------------------------
# 4. Compose missing + live app reachable → external_app (use live app)
# ---------------------------------------------------------------------------


def test_compose_missing_live_app_reachable_uses_external_app(
    tmp_path: Path,
) -> None:
    """Opt-in + no compose + live app responds → ``health="external_app"``.
    No block, no Docker boot needed."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=True) as probe:
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )
    assert report.health == "external_app"
    assert report.block_reason == ""
    assert report.details["live_app_reachable"] is True
    probe.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Structured details payload on blocked runs
# ---------------------------------------------------------------------------


def test_blocked_report_has_structured_details(tmp_path: Path) -> None:
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:4321",
            compose_override="docker/compose.yml",
        )
    details = report.details
    assert details["compose_path_checked"] == "docker/compose.yml"
    assert details["live_app_url_checked"] == "http://127.0.0.1:4321"
    assert details["live_endpoint_check"] is True
    assert details["live_app_reachable"] is False
    assert details["project_root"] == str(tmp_path)


# ---------------------------------------------------------------------------
# 6. format_runtime_report surfaces BLOCKED distinct from SKIPPED
# ---------------------------------------------------------------------------


def test_format_report_blocked_header_names_reason() -> None:
    report = RuntimeReport()
    report.health = "blocked"
    report.block_reason = "compose_file_missing"
    report.details = {
        "compose_path_checked": "",
        "live_app_url_checked": "http://127.0.0.1:3001",
        "live_app_reachable": False,
        "live_endpoint_check": True,
    }
    md = format_runtime_report(report)
    assert "BLOCKED" in md
    assert "`compose_file_missing`" in md
    assert "http://127.0.0.1:3001" in md
    # The legacy "runtime verification skipped" wording must NOT appear —
    # blocked runs are a distinct status.
    assert "runtime verification skipped" not in md.lower()


def test_format_report_skipped_keeps_legacy_wording() -> None:
    report = RuntimeReport()
    report.health = "skipped"
    # docker_available stays False (legacy path) — skipped banner survives.
    md = format_runtime_report(report)
    assert "Docker not available" in md or "docker-compose file" in md
    assert "skipped" in md.lower()
    assert "BLOCKED" not in md


def test_format_report_external_app_header() -> None:
    report = RuntimeReport()
    report.health = "external_app"
    report.details = {"live_app_url_checked": "http://127.0.0.1:8080"}
    md = format_runtime_report(report)
    assert "External app used" in md
    assert "http://127.0.0.1:8080" in md


# ---------------------------------------------------------------------------
# 7. _probe_live_app — pure unit coverage of the new helper
# ---------------------------------------------------------------------------


def test_probe_live_app_empty_url_returns_false() -> None:
    assert _probe_live_app("") is False
    assert _probe_live_app("   ") is False


def test_probe_live_app_success_returns_true() -> None:
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert _probe_live_app("http://127.0.0.1:3001/health") is True


def test_probe_live_app_connection_error_returns_false() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", _raise):
        assert _probe_live_app("http://127.0.0.1:3001") is False


def test_probe_live_app_treats_4xx_as_listening() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3001", 404, "Not Found", {}, None
        )

    with patch("urllib.request.urlopen", _raise):
        # 404 means the server IS listening; still counts as alive.
        assert _probe_live_app("http://127.0.0.1:3001") is True


def test_probe_live_app_5xx_not_treated_as_listening() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3001", 503, "Unavailable", {}, None
        )

    with patch("urllib.request.urlopen", _raise):
        # 5xx suggests a broken server — conservative: not "reachable".
        assert _probe_live_app("http://127.0.0.1:3001") is False


# ---------------------------------------------------------------------------
# 8. D-02 v2 — host-port binding diagnostic + structural skip-vs-block flag
#
# Build-k root cause: `bayan-db` (long-running production container) owned
# host port 5432, so `docker compose up -d` for the scaffold's postgres
# silently created the container with NO host binding. The container was
# "healthy" internally (pg_isready against localhost in the container),
# but every host-side migrate/seed/test routed to bayan-db's wrong DB and
# failed. The `start_docker_for_probing` warm-restart loop interpreted
# this as "warm probe failed" → "full restart" → same conflict → eventual
# `startup_error="...never became healthy..."`. The substring "never
# became healthy" was in the wave_executor's `infra_missing_markers`, so
# the wave silently passed. We now use a structural `infra_missing` flag
# instead of substring matching, AND we surface the unbound-host-port
# condition directly with a specific diagnostic.
# ---------------------------------------------------------------------------


from agent_team_v15 import endpoint_prober
from agent_team_v15.endpoint_prober import (
    DockerContext,
    _detect_unbound_host_ports,
    _extract_host_port,
    _parse_compose_host_ports,
    _port_from_compose,
)


def test_docker_context_infra_missing_defaults_false() -> None:
    """Default DockerContext is NOT infra-missing — only set explicitly
    when the host genuinely lacks Docker / compose / external app."""
    ctx = DockerContext()
    assert ctx.infra_missing is False


def test_extract_host_port_short_form_two_part() -> None:
    assert _extract_host_port("5432:5432") == "5432"


def test_extract_host_port_short_form_with_ip() -> None:
    assert _extract_host_port("127.0.0.1:5432:5432") == "5432"


def test_extract_host_port_long_form_dict() -> None:
    assert _extract_host_port({"published": 8080, "target": 80}) == "8080"


def test_extract_host_port_compose_default_interpolation(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    assert _extract_host_port("${POSTGRES_PORT:-5432}:5432") == "5432"


def test_extract_host_port_compose_env_override(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_PORT", "55432")
    assert _extract_host_port("${POSTGRES_PORT:-5432}:5432") == "55432"


def test_extract_host_port_compose_default_with_host_ip(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    assert _extract_host_port("127.0.0.1:${POSTGRES_PORT:-5432}:5432") == "5432"


def test_extract_host_port_container_only_returns_empty() -> None:
    """Container-only binding (no host port) is not a conflict candidate."""
    assert _extract_host_port("5432") == ""


def test_extract_host_port_unknown_shape_returns_empty() -> None:
    assert _extract_host_port(None) == ""
    assert _extract_host_port(12345) == ""


def test_parse_compose_host_ports_minimal_yaml(tmp_path: Path) -> None:
    """Build-k's actual scaffold compose layout — two services, two host ports."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
  postgres-test:
    image: postgres:16-alpine
    ports:
      - "5433:5432"
""",
        encoding="utf-8",
    )

    parsed = _parse_compose_host_ports(compose)
    assert ("postgres", "5432") in parsed
    assert ("postgres-test", "5433") in parsed


def test_parse_compose_host_ports_with_env_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
""",
        encoding="utf-8",
    )

    assert _parse_compose_host_ports(compose) == [("postgres", "5432")]


def test_port_from_compose_with_env_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("API_PORT", raising=False)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  api:
    image: app
    ports:
      - "${API_PORT:-4000}:4000"
""",
        encoding="utf-8",
    )

    assert _port_from_compose(compose) == 4000


def test_detect_unbound_host_ports_flags_unbound(tmp_path: Path) -> None:
    """When `docker inspect` reports empty bindings for a declared host
    port, _detect_unbound_host_ports must include it in the result."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
""",
        encoding="utf-8",
    )

    class _Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def _fake_run(cmd, **kwargs):
        if "ps" in cmd and "--format" in cmd:
            return _Result("clean-postgres-1\n")
        if cmd[:2] == ["docker", "inspect"]:
            # Container has the port EXPOSED but no HostPort — exactly the
            # build-k pattern.
            return _Result('{"5432/tcp": null}')
        return _Result("")

    with patch.object(endpoint_prober.subprocess, "run", side_effect=_fake_run):
        unbound = _detect_unbound_host_ports(tmp_path, compose)

    assert unbound == [("postgres", "5432")]


def test_detect_unbound_host_ports_clean_when_bound(tmp_path: Path) -> None:
    """When the container reports a HostPort matching the declaration,
    nothing is flagged."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
""",
        encoding="utf-8",
    )

    class _Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def _fake_run(cmd, **kwargs):
        if "ps" in cmd and "--format" in cmd:
            return _Result("clean-postgres-1\n")
        if cmd[:2] == ["docker", "inspect"]:
            return _Result(
                '{"5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5432"}]}'
            )
        return _Result("")

    with patch.object(endpoint_prober.subprocess, "run", side_effect=_fake_run):
        unbound = _detect_unbound_host_ports(tmp_path, compose)

    assert unbound == []


def test_start_docker_for_probing_no_compose_marks_infra_missing(
    tmp_path: Path,
) -> None:
    """No compose + no external app → infra_missing=True so wave_executor
    correctly soft-skips on CI hosts without Docker."""
    import asyncio

    async def _fake_poll_health(_url: str, timeout: int = 60) -> bool:
        return False

    with patch.object(endpoint_prober, "find_compose_file", return_value=None), \
         patch.object(endpoint_prober, "_poll_health", side_effect=_fake_poll_health):
        ctx = asyncio.run(endpoint_prober.start_docker_for_probing(str(tmp_path), None))

    assert ctx.api_healthy is False
    assert ctx.infra_missing is True
    assert "no compose file" in ctx.startup_error.lower()


def test_start_docker_for_probing_no_docker_marks_infra_missing(
    tmp_path: Path,
) -> None:
    """No docker daemon + no external app → infra_missing=True."""
    import asyncio

    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    async def _fake_poll_health(_url: str, timeout: int = 60) -> bool:
        return False

    with patch.object(endpoint_prober, "find_compose_file", return_value=compose), \
         patch.object(endpoint_prober, "check_docker_available", return_value=False), \
         patch.object(endpoint_prober, "_poll_health", side_effect=_fake_poll_health):
        ctx = asyncio.run(endpoint_prober.start_docker_for_probing(str(tmp_path), None))

    assert ctx.api_healthy is False
    assert ctx.infra_missing is True
    assert "docker is unavailable" in ctx.startup_error.lower()


def test_start_docker_for_probing_port_conflict_NOT_infra_missing(
    tmp_path: Path,
) -> None:
    """Build-k regression guard: containers up, port unbound → must NOT
    set infra_missing=True. The wave_executor must BLOCK, not skip."""
    import asyncio

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
""",
        encoding="utf-8",
    )

    class _Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def _fake_run(cmd, **kwargs):
        if "ps" in cmd and "--format" in cmd:
            return _Result("clean-postgres-1\n")
        if cmd[:2] == ["docker", "inspect"]:
            return _Result('{"5432/tcp": null}')
        return _Result("")

    class _BuildResult:
        success = True

    class _ServiceStatus:
        healthy = True

    async def _fake_poll(_url: str, timeout: int = 60) -> bool:
        # Should never be called — port-conflict detection short-circuits.
        return True

    with patch.object(endpoint_prober, "find_compose_file", return_value=compose), \
         patch.object(endpoint_prober, "check_docker_available", return_value=True), \
         patch.object(endpoint_prober, "_containers_running", return_value=False), \
         patch.object(endpoint_prober, "docker_build", return_value=[_BuildResult()]), \
         patch.object(endpoint_prober, "docker_start", return_value=[_ServiceStatus()]), \
         patch.object(endpoint_prober, "_poll_health", side_effect=_fake_poll), \
         patch.object(endpoint_prober.subprocess, "run", side_effect=_fake_run):
        ctx = asyncio.run(endpoint_prober.start_docker_for_probing(str(tmp_path), None))

    assert ctx.api_healthy is False
    # The critical assertion: port conflict is NOT infra_missing.
    assert ctx.infra_missing is False
    assert "host port" in ctx.startup_error.lower()
    assert "5432" in ctx.startup_error
    assert "unbound" in ctx.startup_error.lower()


# ---------------------------------------------------------------------------
# 9. wave_executor: skip-vs-block decision now structural, not string-match
# ---------------------------------------------------------------------------


def test_wave_b_probing_skips_when_infra_missing(tmp_path: Path) -> None:
    """infra_missing=True → wave returns (True, "", []) (soft skip with
    warning) so CI hosts without Docker keep working."""
    import asyncio
    from agent_team_v15 import wave_executor

    ctx = DockerContext(
        api_healthy=False,
        infra_missing=True,
        startup_error="Docker is unavailable and no healthy external app responded",
    )

    async def _fake_start(*_args, **_kwargs):
        return ctx

    class _Milestone:
        id = "milestone-1"
        template = "backend_only"

    with patch.object(endpoint_prober, "start_docker_for_probing", side_effect=_fake_start):
        ok, reason, _findings = asyncio.run(
            wave_executor._run_wave_b_probing(
                milestone=_Milestone(),
                ir={},
                config=None,
                cwd=str(tmp_path),
                wave_artifacts={},
                execute_sdk_call=lambda *a, **k: None,
            )
        )

    assert ok is True
    assert reason == ""


def test_wave_b_probing_blocks_when_port_conflict(tmp_path: Path) -> None:
    """Build-k regression guard: infra_missing=False + api_healthy=False
    → wave BLOCKS with the diagnostic reason. NO soft skip."""
    import asyncio
    from agent_team_v15 import wave_executor

    ctx = DockerContext(
        api_healthy=False,
        infra_missing=False,
        startup_error=(
            "live_endpoint_check=True but declared host port(s) are not bound "
            "— service 'postgres' host port 5432 unbound (another process on "
            "the host likely owns 5432; run `docker ps --filter publish=5432`)"
        ),
    )

    async def _fake_start(*_args, **_kwargs):
        return ctx

    class _Milestone:
        id = "milestone-1"
        template = "backend_only"

    with patch.object(endpoint_prober, "start_docker_for_probing", side_effect=_fake_start):
        ok, reason, _findings = asyncio.run(
            wave_executor._run_wave_b_probing(
                milestone=_Milestone(),
                ir={},
                config=None,
                cwd=str(tmp_path),
                wave_artifacts={},
                execute_sdk_call=lambda *a, **k: None,
            )
        )

    # The critical assertion: this MUST NOT silently pass.
    assert ok is False
    assert "host port" in reason.lower()
    assert "5432" in reason


def test_wave_b_probing_blocks_when_app_never_healthy(tmp_path: Path) -> None:
    """Containers came up, ports bound, but app couldn't talk to its DB
    or otherwise failed health → still BLOCK. The legacy substring match
    silently passed this case via the "never became healthy" marker."""
    import asyncio
    from agent_team_v15 import wave_executor

    ctx = DockerContext(
        api_healthy=False,
        infra_missing=False,
        startup_error=(
            "live_endpoint_check=True but the application never became "
            "healthy at http://localhost:3080"
        ),
    )

    async def _fake_start(*_args, **_kwargs):
        return ctx

    class _Milestone:
        id = "milestone-1"
        template = "backend_only"

    with patch.object(endpoint_prober, "start_docker_for_probing", side_effect=_fake_start):
        ok, reason, _findings = asyncio.run(
            wave_executor._run_wave_b_probing(
                milestone=_Milestone(),
                ir={},
                config=None,
                cwd=str(tmp_path),
                wave_artifacts={},
                execute_sdk_call=lambda *a, **k: None,
            )
        )

    assert ok is False
    assert "never became healthy" in reason.lower()


def test_wave_b_probe_fix_routes_to_codex_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from agent_team_v15 import wave_executor
    from agent_team_v15.config import AgentTeamConfig

    config = AgentTeamConfig()
    config.v18.codex_fix_routing_enabled = True
    config.v18.evidence_mode = "disabled"

    initial_ctx = DockerContext(
        api_healthy=True,
        infra_missing=False,
        startup_error="",
        app_url="http://localhost:4000",
    )
    refreshed_ctx = DockerContext(
        api_healthy=True,
        infra_missing=False,
        startup_error="",
        app_url="http://localhost:4010",
    )

    class _Milestone:
        id = "milestone-1"
        template = "backend_only"

    failing_manifest = SimpleNamespace(
        failures=[
            SimpleNamespace(
                status_code=500,
                actual_status=500,
                method="GET",
                path="/health",
                expected_status=200,
                endpoint_file="apps/api/src/modules/health/health.controller.ts",
            )
        ]
    )
    healthy_manifest = SimpleNamespace(failures=[])
    execute_calls = {"count": 0}
    start_calls = {"count": 0}
    stop_calls = {"count": 0}
    probe_urls: list[str] = []
    codex_prompts: list[str] = []

    async def _fake_start(*_args, **_kwargs):
        start_calls["count"] += 1
        if start_calls["count"] == 1:
            return initial_ctx
        return refreshed_ctx

    def _fake_stop(*_args, **_kwargs):
        stop_calls["count"] += 1

    async def _fake_reset(*_args, **_kwargs):
        return True

    async def _fake_execute_probes(_manifest, docker_ctx, *_args, **_kwargs):
        execute_calls["count"] += 1
        probe_urls.append(docker_ctx.app_url)
        if execute_calls["count"] == 1:
            return failing_manifest
        return healthy_manifest

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18, milestone=None, wave_letter=None, attempt=None, **_kwargs):
        del cwd, provider_routing, v18
        codex_prompts.append(prompt)
        return True, 0.01, ""

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("probe fix should use Codex routing, not the SDK sub-agent path")

    monkeypatch.setattr(endpoint_prober, "start_docker_for_probing", _fake_start)
    monkeypatch.setattr(endpoint_prober, "stop_docker_containers", _fake_stop)
    monkeypatch.setattr(endpoint_prober, "reset_db_and_seed", _fake_reset)
    monkeypatch.setattr(endpoint_prober, "load_seed_fixtures", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(endpoint_prober, "generate_probe_manifest", lambda *_args, **_kwargs: SimpleNamespace(failures=[]))
    monkeypatch.setattr(endpoint_prober, "execute_probes", _fake_execute_probes)
    monkeypatch.setattr(endpoint_prober, "format_probe_failures_for_fix", lambda _manifest: "[PROBE FIX]")
    monkeypatch.setattr(endpoint_prober, "save_probe_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(endpoint_prober, "save_probe_telemetry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(endpoint_prober, "collect_probe_evidence", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_invoke_sdk_sub_agent_with_watchdog", _unexpected_watchdog)

    provider_routing = {
        "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
    }

    ok, reason, findings = asyncio.run(
        wave_executor._run_wave_b_probing(
            milestone=_Milestone(),
            ir={},
            config=config,
            cwd=str(tmp_path),
            wave_artifacts={},
            execute_sdk_call=lambda *a, **k: None,
            milestone_id="milestone-1",
            provider_routing=provider_routing,
        )
    )

    assert ok is True
    assert reason == ""
    assert findings == []
    assert execute_calls["count"] == 2
    assert start_calls["count"] == 2
    assert stop_calls["count"] == 1
    assert probe_urls == ["http://localhost:4000", "http://localhost:4010"]
    assert len(codex_prompts) == 1
    assert "[PROBE FIX]" in codex_prompts[0]


def test_wave_b_probe_fix_codex_failure_fails_without_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from agent_team_v15 import wave_executor
    from agent_team_v15.config import AgentTeamConfig

    config = AgentTeamConfig()
    config.v18.codex_fix_routing_enabled = True
    config.v18.evidence_mode = "disabled"

    ctx = DockerContext(
        api_healthy=True,
        infra_missing=False,
        startup_error="",
        app_url="http://localhost:4000",
    )

    class _Milestone:
        id = "milestone-1"
        template = "backend_only"

    failing_manifest = SimpleNamespace(
        failures=[
            SimpleNamespace(
                status_code=500,
                actual_status=500,
                method="GET",
                path="/health",
                expected_status=200,
                endpoint_file="apps/api/src/modules/health/health.controller.ts",
            )
        ]
    )

    async def _fake_start(*_args, **_kwargs):
        return ctx

    async def _fake_reset(*_args, **_kwargs):
        return True

    async def _fake_execute_probes(_manifest, _docker_ctx, *_args, **_kwargs):
        return failing_manifest

    async def _fake_codex_fix(prompt: str, *, cwd: str, provider_routing, v18, milestone=None, wave_letter=None, attempt=None, **_kwargs):
        del prompt, cwd, provider_routing, v18
        return False, 0.02, "app-server unavailable"

    async def _unexpected_watchdog(**_kwargs):
        raise AssertionError("probe repair must not fall back to SDK sub-agent after Codex failure")

    monkeypatch.setattr(endpoint_prober, "start_docker_for_probing", _fake_start)
    monkeypatch.setattr(endpoint_prober, "stop_docker_containers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(endpoint_prober, "reset_db_and_seed", _fake_reset)
    monkeypatch.setattr(endpoint_prober, "load_seed_fixtures", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(endpoint_prober, "generate_probe_manifest", lambda *_args, **_kwargs: SimpleNamespace(failures=[]))
    monkeypatch.setattr(endpoint_prober, "execute_probes", _fake_execute_probes)
    monkeypatch.setattr(endpoint_prober, "format_probe_failures_for_fix", lambda _manifest: "[PROBE FIX]")
    monkeypatch.setattr(endpoint_prober, "save_probe_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(endpoint_prober, "save_probe_telemetry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(endpoint_prober, "collect_probe_evidence", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(wave_executor, "_dispatch_wrapped_codex_fix", _fake_codex_fix)
    monkeypatch.setattr(wave_executor, "_invoke_sdk_sub_agent_with_watchdog", _unexpected_watchdog)

    ok, reason, findings = asyncio.run(
        wave_executor._run_wave_b_probing(
            milestone=_Milestone(),
            ir={},
            config=config,
            cwd=str(tmp_path),
            wave_artifacts={},
            execute_sdk_call=lambda *a, **k: None,
            milestone_id="milestone-1",
            provider_routing={
                "provider_map": SimpleNamespace(provider_for=lambda wave: "codex"),
            },
        )
    )

    assert ok is False
    assert findings == []
    assert "Codex repair failed" in reason
    assert "app-server unavailable" in reason
