"""Tests for the Wave B Docker transient-failure retry helper (PR #9).

The Wave B endpoint-probing scaffold calls `docker compose up -d` (via
`runtime_verification.docker_start`) and `docker compose exec ... TRUNCATE`
(via `endpoint_prober._truncate_tables`). Both can fail with transient
Docker daemon errors (e.g. "failed to set up container networking: driver
failed") that recover on retry. The retry helper bounds those failures
without papering over real broken-config errors.

See `docs/plans/2026-04-15-wave-b-docker-transient-retry.md`.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from agent_team_v15.runtime_verification import (
    DOCKER_RETRY_BACKOFFS_S,
    DOCKER_RETRY_MAX_ATTEMPTS,
    _retry_docker_op,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRANSIENT_ERRORS = (
    "Error response from daemon: failed to set up container networking: driver failed p",
    "driver failed programming external connectivity",
    "Error response from daemon: something went wrong",
)
NON_TRANSIENT_ERRORS = (
    "no such image: foo:latest",
    "image not found in repository",
    "invalid compose project: missing services",
    "port already allocated: 0.0.0.0:5432",
    "yaml: line 12: mapping values are not allowed here",
)


def _ok():
    return (0, "Container started\n", "")


def _fail(stderr: str):
    return (1, "", stderr)


# ---------------------------------------------------------------------------
# Test 1: transient-then-success
# ---------------------------------------------------------------------------

class TestTransientThenSuccess:
    @pytest.mark.parametrize("transient", TRANSIENT_ERRORS)
    def test_two_transient_failures_then_success(self, transient, caplog):
        """Each of the three transient substrings must be retried."""
        op = MagicMock(side_effect=[_fail(transient), _fail(transient), _ok()])
        sleep = MagicMock()

        with caplog.at_level("WARNING"):
            rc, out, err = _retry_docker_op(op, op_name="compose up", sleep=sleep)

        assert rc == 0
        assert op.call_count == 3
        # Sleeps happen between attempts: 2 sleeps for 3 attempts.
        assert sleep.call_args_list == [call(5), call(15)]
        # Retry log lines name the attempt number and op name.
        retry_lines = [r.message for r in caplog.records if "Wave B probing" in r.message]
        assert any("compose up attempt 2/3" in line for line in retry_lines)
        assert any("compose up attempt 3/3" in line for line in retry_lines)


# ---------------------------------------------------------------------------
# Test 2: persistent transient
# ---------------------------------------------------------------------------

class TestPersistentTransient:
    def test_three_transient_failures_surface_original_error(self, caplog):
        original_err = (
            "Error response from daemon: failed to set up container networking: driver failed p"
        )
        op = MagicMock(side_effect=[_fail(original_err)] * 3)
        sleep = MagicMock()

        with caplog.at_level("WARNING"):
            rc, out, err = _retry_docker_op(op, op_name="compose up", sleep=sleep)

        assert rc == 1
        assert op.call_count == DOCKER_RETRY_MAX_ATTEMPTS == 3
        # Original error preserved verbatim, not rewritten.
        assert err == original_err
        # 2 sleeps between 3 attempts.
        assert sleep.call_args_list == [call(5), call(15)]
        # All 3 attempts logged with attempt N/3 markers (attempts 2 and 3 emit retry lines).
        retry_lines = [r.message for r in caplog.records if "Wave B probing" in r.message]
        assert sum("attempt 2/3" in line for line in retry_lines) == 1
        assert sum("attempt 3/3" in line for line in retry_lines) == 1


# ---------------------------------------------------------------------------
# Test 3: non-transient error (no retry)
# ---------------------------------------------------------------------------

class TestNonTransientError:
    @pytest.mark.parametrize("permanent", NON_TRANSIENT_ERRORS)
    def test_non_transient_error_is_not_retried(self, permanent, caplog):
        op = MagicMock(side_effect=[_fail(permanent), _ok()])
        sleep = MagicMock()

        with caplog.at_level("WARNING"):
            rc, out, err = _retry_docker_op(op, op_name="compose up", sleep=sleep)

        assert rc == 1
        assert op.call_count == 1  # exactly one attempt — no retry
        assert err == permanent
        sleep.assert_not_called()
        retry_lines = [r.message for r in caplog.records if "Wave B probing" in r.message]
        assert retry_lines == []


# ---------------------------------------------------------------------------
# Test 4: mixed (transient then non-transient stops further retries)
# ---------------------------------------------------------------------------

class TestMixedErrors:
    def test_transient_then_non_transient_stops_retry(self, caplog):
        transient = "Error response from daemon: failed to set up container networking"
        permanent = "no such image: backend:latest"
        op = MagicMock(side_effect=[_fail(transient), _fail(permanent), _ok()])
        sleep = MagicMock()

        with caplog.at_level("WARNING"):
            rc, out, err = _retry_docker_op(op, op_name="compose up", sleep=sleep)

        assert rc == 1
        assert op.call_count == 2  # transient retried once → permanent → stop
        assert err == permanent  # final error is the non-transient one
        # One sleep occurred (5s) before attempt 2.
        assert sleep.call_args_list == [call(5)]


# ---------------------------------------------------------------------------
# Test 5: backoff timing
# ---------------------------------------------------------------------------

class TestBackoffTiming:
    def test_backoff_constants_are_5_15_45(self):
        """The documented policy is 5s → 15s → 45s exponential backoff."""
        assert DOCKER_RETRY_BACKOFFS_S == (5, 15, 45)
        assert DOCKER_RETRY_MAX_ATTEMPTS == 3

    def test_sleep_called_with_first_two_backoffs_in_order(self):
        """For 3 attempts (2 retries), sleep is called with backoffs[0] and backoffs[1]."""
        transient = "driver failed"
        op = MagicMock(side_effect=[_fail(transient), _fail(transient), _fail(transient)])
        sleep = MagicMock()

        _retry_docker_op(op, op_name="compose up", sleep=sleep)

        # Strictly 5 then 15 — not 0, not 45, not anything else.
        assert sleep.call_args_list == [call(5), call(15)]
        # Sleep was not called with anything else.
        for actual in sleep.call_args_list:
            assert actual.args[0] in (5, 15)
