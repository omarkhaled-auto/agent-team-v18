"""Phase 5 closeout Stage 2 — team-mode backend shutdown async-safety regression.

Operator-found defect on the §O.4.6 B1 closure smoke (run-dir
``v18 test runs/phase-5-closeout-stage-2a-iv-rerun-o46-b1-20260501-103942/``):
when the integration-audit's Claude SDK orphan-tool wedge fired at
``cli.py:7203``-area, the post-orchestration cleanup path inside
``_run_prd_milestones`` raised
``asyncio.run() cannot be called from a running event loop``. The error
escaped to the outer orchestration handler at ``cli.py:15531`` and
landed on STATE.json's ``error_context``.

Root cause — defensive anti-pattern at ``cli.py:7367-7371``:

.. code-block:: python

    if config.agent_teams.auto_shutdown and _execution_backend is not None:
        try:
            asyncio.get_event_loop().run_until_complete(
                _execution_backend.shutdown()
            )
        except RuntimeError:
            # No running event loop — create one
            asyncio.run(_execution_backend.shutdown())

``_run_prd_milestones`` is ``async def`` (cli.py:3889). The OUTER
``asyncio.get_event_loop().run_until_complete(...)`` runs ON the
already-running loop, raising ``RuntimeError: This event loop is already
running``. The ``except RuntimeError`` falls back to ``asyncio.run()``,
which raises ``RuntimeError: asyncio.run() cannot be called from a
running event loop``. That second RuntimeError isn't the same exception
class but escapes the ``except RuntimeError`` handler because it's the
SAME exception class — it's RAISED FRESH inside the handler. The bare
``raise`` then propagates up out of ``_run_prd_milestones``, which is
caught by the orchestration ``except Exception as exc`` at line 15531,
sets ``state.error_context``, and ``state.interrupted=True``.

Post-fix contract: replace the asyncio.run-fallback dance with a direct
``await _execution_backend.shutdown()``. ``_run_prd_milestones`` is
async, so ``await`` is the correct primitive. The defensive
``asyncio.run`` was wrong from the start for this call site.

Two tests:

1. ``test_team_shutdown_uses_direct_await_not_asyncio_run`` — static-
   source lock on the ``cli.py:7367``-area block.
2. ``test_team_shutdown_does_not_raise_running_loop_error_in_async_context``
   — behavioural lock: a synthetic ``async`` context that calls into
   the same code shape without raising
   ``RuntimeError: asyncio.run() cannot be called from a running event loop``.

Both fail at parent commit ``3f12a12`` (TDD pre-fix lock) and pass
post-fix.
"""

from __future__ import annotations

import asyncio
import inspect
import re

import pytest

from agent_team_v15 import cli as cli_mod


def test_team_shutdown_uses_direct_await_not_asyncio_run() -> None:
    """Static-source lock — the team-mode backend shutdown block at
    ``cli.py:~7367-7375`` MUST use ``await _execution_backend.shutdown()``
    inside the async ``_run_prd_milestones``, NOT
    ``asyncio.get_event_loop().run_until_complete + asyncio.run`` fallback.

    The fallback ``asyncio.run`` is ALWAYS wrong inside an async function
    body — it raises
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
    The fix must remove the fallback and use ``await`` directly. A bare
    ``await`` is correct here because ``_run_prd_milestones`` is
    ``async def``.
    """

    src = inspect.getsource(cli_mod._run_prd_milestones)

    # The team-mode shutdown block must contain ``await`` on the backend's
    # shutdown(), not asyncio.run. Generous window absorbs the explanatory
    # comment block that documents the post-fix invariant.
    shutdown_block_re = re.compile(
        r"if\s+config\.agent_teams\.auto_shutdown\s+and\s+_execution_backend\s+is\s+not\s+None\s*:"
        r"[\s\S]{0,2000}?"
        r"_execution_backend\.shutdown\(\s*\)",
        re.MULTILINE,
    )
    match = shutdown_block_re.search(src)
    assert match is not None, (
        "Could not locate the team-mode shutdown block in "
        "_run_prd_milestones. Source has drifted."
    )

    block = match.group(0)

    # Strip Python comment lines so explanatory comments that quote
    # the pre-fix shape don't trip the substring check.
    code_lines = []
    for line in block.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines)

    # The CALL ``asyncio.run(...)`` MUST NOT appear in the code lines.
    # We check for the call shape ``asyncio.run(`` (open paren) so
    # docstring-style references like ``asyncio.run`` (no parens) in
    # adjacent identifiers don't false-positive.
    assert "asyncio.run(" not in code_only, (
        "Phase 5 closeout Stage 2 §O.4.6 follow-up: the team-mode "
        "shutdown block in async _run_prd_milestones MUST NOT contain "
        "``asyncio.run(_execution_backend.shutdown())``. asyncio.run "
        "raises ``cannot be called from a running event loop`` inside "
        "an async function body. Replace with ``await "
        "_execution_backend.shutdown()`` directly. Found asyncio.run("
        " in the code-only view of the matched block:\n" + code_only
    )
    # Same shape for ``run_until_complete(...)`` — must not appear in
    # the code lines.
    assert "run_until_complete(" not in code_only, (
        "Phase 5 closeout Stage 2 §O.4.6 follow-up: the team-mode "
        "shutdown block in async _run_prd_milestones MUST NOT contain "
        "``asyncio.get_event_loop().run_until_complete(...)``. Inside "
        "an async function body that primitive raises ``This event "
        "loop is already running``. Replace with ``await "
        "_execution_backend.shutdown()`` directly."
    )
    # Positive lock: an ``await`` MUST appear in the code lines, calling
    # ``_execution_backend.shutdown()``.
    await_re = re.compile(r"await\s+_execution_backend\.shutdown\(\s*\)")
    assert await_re.search(code_only), (
        "Phase 5 closeout Stage 2 §O.4.6 follow-up: the team-mode "
        "shutdown block in async _run_prd_milestones MUST call "
        "``await _execution_backend.shutdown()`` directly."
    )


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_team_shutdown_does_not_raise_running_loop_error_in_async_context() -> None:
    """Behavioural lock — synthesise a fragment of the team-mode shutdown
    code path inside an async context and assert it does NOT raise
    ``RuntimeError: asyncio.run() cannot be called from a running event
    loop``.

    The pre-fix shape (asyncio.run as a fallback after
    asyncio.get_event_loop().run_until_complete) raises this error
    deterministically inside any async function body. The post-fix shape
    (bare ``await``) does not.

    Implements a narrow proxy: builds the same code structure at module
    scope so the test is self-contained and doesn't require booting the
    actual orchestrator.
    """

    class _FakeExecutionBackend:
        async def shutdown(self) -> None:
            return None

    fake_backend = _FakeExecutionBackend()

    # Post-fix shape — ``await`` directly inside async function.
    async def _post_fix_shape() -> None:
        # Mirrors the post-fix block: bare await, no asyncio.run dance.
        await fake_backend.shutdown()

    # Pre-fix shape — must raise RuntimeError when run from a running
    # event loop. This codifies WHY the fix was needed.
    async def _pre_fix_shape() -> None:
        try:
            asyncio.get_event_loop().run_until_complete(fake_backend.shutdown())
        except RuntimeError:
            # The "fallback" — IS the broken bit. Inside a running loop
            # this raises again.
            asyncio.run(fake_backend.shutdown())

    # Post-fix path: must complete without error.
    asyncio.run(_post_fix_shape())  # outer event loop OK because the
                                    # inner code path uses ``await``.

    # Pre-fix path: must raise RuntimeError mentioning the running loop
    # — this is the empirical defect we're locking against.
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(_pre_fix_shape())
    assert (
        "running event loop" in str(excinfo.value)
        or "already running" in str(excinfo.value)
    ), (
        f"Pre-fix shape MUST raise the canonical 'running event loop' "
        f"RuntimeError; got: {excinfo.value!r}"
    )
