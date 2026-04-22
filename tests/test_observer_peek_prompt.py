"""Tests for build_peek_prompt's truncation behavior.

Regression coverage for the R1B1 false positive where a 924-char
`apps/api/Dockerfile` was flagged at 0.95 confidence because
``file_content[:600]`` ended at a bare ``WORKDIR``. The fix caps the
snippet at 4000 chars, cuts on the last newline when truncation is
needed, and labels the slice so Haiku cannot infer completeness from
the snippet boundary.
"""
from __future__ import annotations

import random
import re

import pytest

from agent_team_v15.observer_peek import build_peek_prompt
from agent_team_v15.wave_executor import PeekSchedule


def _schedule() -> PeekSchedule:
    return PeekSchedule(
        wave="B",
        trigger_files=["apps/api/Dockerfile"],
        requirements_text="- [ ] apps/api/Dockerfile\n",
    )


_FENCE_RE = re.compile(r"```\n(.*)\n```", re.DOTALL)


def _fenced_snippet(prompt: str) -> str:
    """Extract the exact ``snippet`` string that ``build_peek_prompt`` placed
    between its fence markers.

    The prompt is produced by ``"\\n".join([..., "```", snippet, "```", ...])``,
    which yields the literal substring ``"```\\n" + snippet + "\\n```"``.
    A greedy regex captures that content verbatim, preserving any trailing
    newline produced by newline-boundary truncation.
    """
    match = _FENCE_RE.search(prompt)
    assert match is not None, "expected a fenced code block in prompt"
    return match.group(1)


def test_short_file_is_not_truncated() -> None:
    content = "FROM alpine\nCMD [\"echo\", \"hi\"]\n"  # ~30 chars
    prompt = build_peek_prompt(
        file_path="apps/api/Dockerfile",
        file_content=content,
        schedule=_schedule(),
        framework_pattern="",
    )
    assert "TRUNCATED" not in prompt
    assert _fenced_snippet(prompt).strip() == content.strip()


def test_long_file_is_truncated_on_newline_boundary() -> None:
    lines = [f"line_{i} some content" for i in range(1000)]  # ~20k chars
    content = "\n".join(lines) + "\n"
    prompt = build_peek_prompt(
        file_path="src/big.ts",
        file_content=content,
        schedule=_schedule(),
        framework_pattern="",
    )
    snippet = _fenced_snippet(prompt)
    # Snippet must not end mid-token: the last line of the snippet must be
    # a complete 'line_N some content' record, not a sliced fragment.
    last_line = snippet.rsplit("\n", 1)[-1]
    assert last_line.startswith("line_") and last_line.endswith("content")


def test_truncation_signal_distinguishes_boundary_from_content_quality() -> None:
    content = "x" * 5000 + "\n"
    prompt = build_peek_prompt(
        file_path="apps/huge.txt",
        file_content=content,
        schedule=_schedule(),
        framework_pattern="",
    )
    assert "TRUNCATED" in prompt
    assert "the file continues beyond" in prompt
    assert "Do not infer syntactic completeness or incompleteness" in prompt
    # Must still instruct Haiku to flag real content-quality issues.
    assert "Continue to flag" in prompt
    assert "stubs" in prompt


def test_r1b1_preserved_dockerfile_shape_no_longer_fps() -> None:
    """Regression: the exact R1B1 FP shape — 924 chars, WORKDIR at ~600."""
    content = (
        "# syntax=docker/dockerfile:1.6\n"
        "\n"
        "FROM node:20-alpine AS base\n"
        "RUN corepack enable && corepack prepare pnpm@latest --activate\n"
        "WORKDIR /app\n"
        "\n"
        "FROM base AS deps\n"
        "COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./\n"
        "COPY apps/api/package.json apps/api/\n"
        "COPY apps/web/package.json apps/web/\n"
        "COPY packages/shared/package.json packages/shared/\n"
        "RUN pnpm install --frozen-lockfile\n"
        "\n"
        "FROM base AS build\n"
        "COPY --from=deps /app/node_modules ./node_modules\n"
        "COPY . .\n"
        "WORKDIR /app/apps/api\n"
        "RUN pnpm prisma generate --schema prisma/schema.prisma\n"
        "RUN pnpm run build\n"
        "\n"
        "FROM base AS runtime\n"
        "ENV NODE_ENV=production\n"
        "WORKDIR /app/apps/api\n"
        "\n"
        "COPY --from=build /app/node_modules /app/node_modules\n"
        "COPY --from=build /app/apps/api/dist ./dist\n"
        "COPY --from=build /app/apps/api/prisma ./prisma\n"
        "COPY --from=build /app/apps/api/package.json ./package.json\n"
        "\n"
        "EXPOSE 4000\n"
        'CMD ["sh", "-c", "npx prisma migrate deploy && '
        'npx prisma db seed && node dist/main.js"]\n'
    )
    assert 900 <= len(content) <= 1000, "fixture must mirror R1B1 size band"

    prompt = build_peek_prompt(
        file_path="apps/api/Dockerfile",
        file_content=content,
        schedule=_schedule(),
        framework_pattern="",
    )

    # File is under 4000 chars -> no truncation, full content appears.
    assert "TRUNCATED" not in prompt
    snippet = _fenced_snippet(prompt)
    # Every WORKDIR directive must appear with its path argument.
    assert "WORKDIR /app\n" in snippet
    assert snippet.count("WORKDIR /app/apps/api") == 2
    # The specific FP pattern — a bare WORKDIR at the end of the
    # fenced block — must not appear.
    assert "WORKDIR\n```" not in prompt
    assert not snippet.rstrip("\n").endswith("WORKDIR")


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_fuzz_snippet_ends_cleanly(seed: int) -> None:
    rng = random.Random(seed)
    sizes = [100, 500, 900, 2000, 3999, 4000, 4001, 6000, 10000]
    size = rng.choice(sizes)
    # Build realistic line-oriented content of the target size.
    parts: list[str] = []
    while sum(len(p) for p in parts) < size:
        parts.append(f"line {len(parts)} " + "x" * rng.randint(5, 40) + "\n")
    content = "".join(parts)[:size]
    prompt = build_peek_prompt(
        file_path="sample.txt",
        file_content=content,
        schedule=_schedule(),
        framework_pattern="",
    )
    snippet = _fenced_snippet(prompt)
    if len(content) <= 4000:
        # Short file -> snippet is the whole file, byte-identical.
        assert snippet == content
    else:
        # Long file -> snippet ends at a line boundary so no partial
        # line/token leaks into the prompt. The last line of snippet
        # must match a full ``line N xxxx`` record.
        assert len(snippet) <= 4000
        assert "\n" in snippet, "expected at least one newline in truncated snippet"
        last_line = snippet.rsplit("\n", 1)[-1]
        assert re.match(r"(line \d+ x+)?$", last_line), (
            f"snippet ended mid-line: {last_line!r}"
        )
