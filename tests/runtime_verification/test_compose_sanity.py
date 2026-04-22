"""Tests for Phase 6.0 Compose Sanity Gate.

Covers the tokenizer (``parse_dockerfile``), the public validator
(``validate_compose_build_context``), and the autorepair path. Each test
builds a self-contained fixture tree under ``tmp_path`` so there is no
coupling to the repository layout.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from agent_team_v15.compose_sanity import (
    ComposeSanityError,
    CopyInstruction,
    Violation,
    lca,
    parse_dockerfile,
    validate_compose_build_context,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def _read_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Escape + autorepair round trip
# ---------------------------------------------------------------------------

def test_detects_copy_escape_and_autorepairs(tmp_path: Path) -> None:
    """The Codex failure mode: COPY ../packages/... from a narrow context."""
    _write(tmp_path / "packages" / "shared" / "package.json", '{"name":"shared"}\n')
    _write(
        tmp_path / "apps" / "web" / "Dockerfile",
        """
        FROM node:20-alpine
        WORKDIR /app
        COPY ../packages/shared/package.json ./shared/
        COPY . .
        """,
    )
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          web:
            build:
              context: ./apps/web
              dockerfile: Dockerfile
        """,
    )

    violations = validate_compose_build_context(compose, autorepair=True)
    assert violations == []

    parsed = _read_compose(compose)
    build = parsed["services"]["web"]["build"]
    assert build["context"] == "."
    assert build["dockerfile"] == "apps/web/Dockerfile"

    # The Dockerfile COPY must now resolve from the widened context.
    dockerfile_text = (tmp_path / "apps" / "web" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "packages/shared/package.json" in dockerfile_text
    assert "../packages/shared/package.json" not in dockerfile_text


# ---------------------------------------------------------------------------
# 2. Heredoc body is not parsed as COPY
# ---------------------------------------------------------------------------

def test_heredoc_not_flagged_as_copy(tmp_path: Path) -> None:
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM alpine
        RUN cat <<EOF > /app/config
        COPY ../out-of-band/file.txt /somewhere
        some other literal text
        EOF
        """,
    )
    instructions = parse_dockerfile(dockerfile)
    # Only instruction that should show up is: none (the RUN-heredoc creates
    # a file; the COPY inside the heredoc is literal content).
    copy_add = [i for i in instructions if i.instruction in ("COPY", "ADD")]
    assert copy_add == [], (
        f"COPY inside heredoc body must NOT be flagged: {copy_add}"
    )


def test_heredoc_variants_are_recognized(tmp_path: Path) -> None:
    """<<EOF, <<-EOF, <<\"EOF\", <<'EOF' all suppress COPY detection."""
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM alpine
        RUN <<-EOF
        \tCOPY a b
        EOF
        RUN <<"DELIM"
        COPY c d
        DELIM
        RUN <<'X'
        COPY e f
        X
        COPY g h
        """,
    )
    instructions = parse_dockerfile(dockerfile)
    # Only the final ``COPY g h`` should survive.
    assert len(instructions) == 1
    assert instructions[0].sources == ("g",)
    assert instructions[0].dest == "h"


# ---------------------------------------------------------------------------
# 3. Multi-stage COPY --from=<alias> is skipped
# ---------------------------------------------------------------------------

def test_multi_stage_from_copy_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.ts", "// placeholder\n")
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM node:20 AS builder
        WORKDIR /build
        COPY src ./src
        RUN echo build

        FROM alpine
        COPY --from=builder /build/app /app
        COPY --from=somewhere-else /tmp/x /y
        """,
    )
    instructions = parse_dockerfile(dockerfile)
    stage_copies = [i for i in instructions if i.from_stage]
    host_copies = [i for i in instructions if not i.from_stage]
    assert len(stage_copies) == 2
    assert len(host_copies) == 1
    assert host_copies[0].sources == ("src",)
    # And the full validator must NOT flag the --from= sources.
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          api:
            build:
              context: .
              dockerfile: Dockerfile
        """,
    )
    assert validate_compose_build_context(compose, autorepair=False) == []


# ---------------------------------------------------------------------------
# 4. Override file is merged for effective-context
# ---------------------------------------------------------------------------

def test_override_file_merged(tmp_path: Path) -> None:
    """compose.override.yml's build.context replaces base."""
    # Base says ./apps/web (would be broken), override widens to '.'.
    _write(tmp_path / "packages" / "shared" / "package.json", "{}\n")
    _write(
        tmp_path / "apps" / "web" / "Dockerfile",
        """
        FROM node:20-alpine
        COPY packages/shared/package.json ./
        """,
    )
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          web:
            build:
              context: ./apps/web
              dockerfile: Dockerfile
        """,
    )
    _write(
        tmp_path / "docker-compose.override.yml",
        """
        services:
          web:
            build:
              context: .
              dockerfile: apps/web/Dockerfile
        """,
    )
    # With the override merged, build.context='.' and the COPY is in-bounds.
    # Autorepair=False to prove validation is a NO-OP on effective config.
    assert validate_compose_build_context(compose, autorepair=False) == []


# ---------------------------------------------------------------------------
# 5. autorepair=False raises
# ---------------------------------------------------------------------------

def test_autorepair_disabled_raises(tmp_path: Path) -> None:
    _write(tmp_path / "packages" / "shared" / "package.json", "{}\n")
    _write(
        tmp_path / "apps" / "web" / "Dockerfile",
        """
        FROM node:20-alpine
        COPY ../packages/shared/package.json ./shared/
        """,
    )
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          web:
            build:
              context: ./apps/web
              dockerfile: Dockerfile
        """,
    )
    with pytest.raises(ComposeSanityError) as excinfo:
        validate_compose_build_context(compose, autorepair=False)
    assert any(v.reason == "escapes context" for v in excinfo.value.violations)


# ---------------------------------------------------------------------------
# 6. Realistic pnpm monorepo layout
# ---------------------------------------------------------------------------

def test_pnpm_monorepo_realistic(tmp_path: Path) -> None:
    """Replicates the failing calibration: narrow context, broad COPY."""
    _write(tmp_path / "pnpm-workspace.yaml", "packages:\n  - 'packages/*'\n  - 'apps/*'\n")
    _write(tmp_path / "package.json", '{"name":"root","private":true}\n')
    _write(tmp_path / "packages" / "shared" / "package.json", '{"name":"shared"}\n')
    _write(
        tmp_path / "apps" / "web" / "Dockerfile",
        """
        FROM node:20-alpine
        WORKDIR /app
        COPY pnpm-workspace.yaml ./
        COPY package.json ./
        COPY packages/shared/package.json ./packages/shared/
        COPY . .
        """,
    )
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          web:
            build:
              context: ./apps/web
              dockerfile: Dockerfile
        """,
    )

    violations = validate_compose_build_context(compose, autorepair=True)
    assert violations == []

    parsed = _read_compose(compose)
    build = parsed["services"]["web"]["build"]
    assert build["context"] == "."
    assert build["dockerfile"] == "apps/web/Dockerfile"


# ---------------------------------------------------------------------------
# 7. Valid compose — no-op
# ---------------------------------------------------------------------------

def test_valid_compose_no_op(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name":"ok"}\n')
    _write(tmp_path / "src" / "index.ts", "export {};\n")
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM node:20
        WORKDIR /app
        COPY package.json ./
        COPY src ./src
        """,
    )
    compose_yaml = """
        services:
          api:
            build:
              context: .
              dockerfile: Dockerfile
        """
    compose = _write(tmp_path / "docker-compose.yml", compose_yaml)
    original_compose = compose.read_text(encoding="utf-8")
    original_dockerfile = dockerfile.read_text(encoding="utf-8")

    assert validate_compose_build_context(compose, autorepair=True) == []

    # Files must NOT have been rewritten.
    assert compose.read_text(encoding="utf-8") == original_compose
    assert dockerfile.read_text(encoding="utf-8") == original_dockerfile


# ---------------------------------------------------------------------------
# Extra: short-form build (``build: ./foo``) is handled
# ---------------------------------------------------------------------------

def test_short_form_build_is_normalized(tmp_path: Path) -> None:
    _write(tmp_path / "service" / "Dockerfile", "FROM alpine\nCOPY . /app\n")
    _write(tmp_path / "service" / "app.py", "print('hi')\n")
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          svc:
            build: ./service
        """,
    )
    assert validate_compose_build_context(compose, autorepair=False) == []


# ---------------------------------------------------------------------------
# Extra: line continuations inside a COPY
# ---------------------------------------------------------------------------

def test_copy_with_line_continuation(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "a\n")
    _write(tmp_path / "b.txt", "b\n")
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM alpine
        COPY a.txt \\
             b.txt \\
             /dst/
        """,
    )
    instructions = parse_dockerfile(dockerfile)
    copy_add = [i for i in instructions if i.instruction == "COPY"]
    assert len(copy_add) == 1
    assert copy_add[0].sources == ("a.txt", "b.txt")
    assert copy_add[0].dest == "/dst/"


# ---------------------------------------------------------------------------
# Extra: lca() helper edge cases
# ---------------------------------------------------------------------------

def test_lca_returns_longest_common_prefix(tmp_path: Path) -> None:
    a = tmp_path / "apps" / "web"
    b = tmp_path / "apps" / "api"
    c = tmp_path / "packages" / "shared"
    assert lca([a, b]) == tmp_path / "apps"
    assert lca([a, b, c]) == tmp_path
    assert lca([a]) == a


# ---------------------------------------------------------------------------
# Extra: missing Dockerfile surfaces as a violation (not a crash)
# ---------------------------------------------------------------------------

def test_missing_dockerfile_reported(tmp_path: Path) -> None:
    compose = _write(
        tmp_path / "docker-compose.yml",
        """
        services:
          ghost:
            build:
              context: .
              dockerfile: does-not-exist.Dockerfile
        """,
    )
    with pytest.raises(ComposeSanityError) as excinfo:
        validate_compose_build_context(compose, autorepair=False)
    reasons = [v.reason for v in excinfo.value.violations]
    assert any("Dockerfile not found" in r for r in reasons)
