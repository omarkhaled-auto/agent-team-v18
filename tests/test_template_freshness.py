"""NEW-2 scaffold template version stamping — tests for
``scaffold_runner._stamp_version`` and the integrated ``run_scaffolding``
behavior.

Covers the 3 scenarios specified in the Wave 3 team-lead brief:

1. flag-OFF emits no stamp (emitted bytes preserved exactly);
2. flag-ON emits a ``// scaffold-template-version: ...`` stamp in .ts files;
3. flag-ON SKIPS .json files (strict JSON has no comment syntax).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.scaffold_runner import (
    SCAFFOLD_TEMPLATE_VERSION,
    _stamp_version,
    run_scaffolding,
)


def _write_ir(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "product.ir.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _full_stack_ir() -> dict:
    return {
        "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
        "entities": [],
        "i18n": {"locales": ["en"]},
    }


class TestTemplateVersionStampingFlagOff:
    def test_flag_off_emits_byte_identical_content(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config(template_version_stamping_enabled=False)

        ir_path = _write_ir(tmp_path, _full_stack_ir())
        run_scaffolding(
            ir_path, tmp_path, "milestone-1", ["F-001"], config=cfg
        )

        # A .ts file must NOT carry the stamp comment header.
        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        assert main_ts.is_file()
        content = main_ts.read_text(encoding="utf-8")
        assert "scaffold-template-version" not in content, (
            "flag-OFF must emit byte-identical (no stamp)"
        )
        # The file must start with its real content, not a comment header.
        first_line = content.splitlines()[0]
        assert not first_line.startswith("// scaffold-template-version")


class TestTemplateVersionStampingFlagOnTs:
    def test_flag_on_emits_stamp_in_ts_file(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config(template_version_stamping_enabled=True)

        ir_path = _write_ir(tmp_path, _full_stack_ir())
        run_scaffolding(
            ir_path, tmp_path, "milestone-1", ["F-001"], config=cfg
        )

        main_ts = tmp_path / "apps" / "api" / "src" / "main.ts"
        assert main_ts.is_file()
        content = main_ts.read_text(encoding="utf-8")
        expected = f"// scaffold-template-version: {SCAFFOLD_TEMPLATE_VERSION}"
        assert content.startswith(expected), (
            f"flag-ON .ts must start with the stamp header; got first line: "
            f"{content.splitlines()[0]!r}"
        )


class TestTemplateVersionStampingSkipsJson:
    def test_flag_on_json_file_has_no_stamp(self, tmp_path: Path) -> None:
        """Strict JSON does not allow comments — the stamp must be skipped
        even when the flag is ON. Parsed JSON must round-trip cleanly.
        """
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config(template_version_stamping_enabled=True)

        ir_path = _write_ir(tmp_path, _full_stack_ir())
        run_scaffolding(
            ir_path, tmp_path, "milestone-1", ["F-001"], config=cfg
        )

        # The root package.json is one of the emitted JSON artifacts.
        root_pkg = tmp_path / "package.json"
        assert root_pkg.is_file()
        content = root_pkg.read_text(encoding="utf-8")
        assert "scaffold-template-version" not in content, (
            "JSON files must NOT receive a stamp (strict JSON has no comments)"
        )
        # It must still parse as valid JSON.
        parsed = json.loads(content)
        assert isinstance(parsed, dict)


class TestStampVersionHelper:
    """Direct unit tests for the ``_stamp_version`` helper (sanity)."""

    def test_stamp_ts_prepends_slash_comment(self) -> None:
        result = _stamp_version("const x = 1;\n", ".ts")
        assert result.startswith(
            f"// scaffold-template-version: {SCAFFOLD_TEMPLATE_VERSION}\n"
        )
        assert "const x = 1;" in result

    def test_stamp_py_prepends_hash_comment(self) -> None:
        result = _stamp_version("x = 1\n", ".py")
        assert result.startswith(
            f"# scaffold-template-version: {SCAFFOLD_TEMPLATE_VERSION}\n"
        )

    def test_stamp_skips_json(self) -> None:
        original = '{"a": 1}'
        assert _stamp_version(original, ".json") == original

    def test_stamp_skips_markdown(self) -> None:
        original = "# Title\n\nbody\n"
        assert _stamp_version(original, ".md") == original

    def test_stamp_idempotent(self) -> None:
        stamped_once = _stamp_version("code;\n", ".ts")
        stamped_twice = _stamp_version(stamped_once, ".ts")
        assert stamped_once == stamped_twice, "stamp must be idempotent"
