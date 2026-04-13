"""Tests for the two-tier UI design token pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.ui_design_tokens import (
    APP_NATURE_PROFILES,
    PROFILE_KEYWORDS,
    UIDesignTokens,
    classify_app_nature,
    extract_tokens_from_html,
    format_design_tokens_block,
    infer_design_tokens,
    load_design_tokens,
    resolve_design_tokens,
)


# ---------------------------------------------------------------------------
# Tier 2 classifier
# ---------------------------------------------------------------------------


class TestClassifyAppNature:
    def test_task_management(self) -> None:
        assert (
            classify_app_nature(
                "task management with kanban board and sprints", ["Task", "Project"]
            )
            == "task_management"
        )

    def test_healthcare(self) -> None:
        assert (
            classify_app_nature(
                "patient portal with clinical appointments and prescriptions",
                ["Patient", "Doctor"],
            )
            == "healthcare"
        )

    def test_ecommerce(self) -> None:
        assert (
            classify_app_nature(
                "product catalog with shopping cart and checkout flow",
                ["Product", "Order"],
            )
            == "ecommerce"
        )

    def test_financial(self) -> None:
        assert (
            classify_app_nature(
                "banking ledger with portfolio and investment statements",
                ["Account", "Transaction"],
            )
            == "financial"
        )

    def test_dashboard(self) -> None:
        assert (
            classify_app_nature(
                "analytics dashboard with KPIs and monitoring charts",
                ["Metric"],
            )
            == "dashboard"
        )

    def test_social(self) -> None:
        assert (
            classify_app_nature(
                "social feed with posts, comments, follows and notifications",
                ["Post", "Comment"],
            )
            == "social"
        )

    def test_admin_internal(self) -> None:
        assert (
            classify_app_nature(
                "internal tool admin audit log and RBAC permissions",
                ["User", "Role"],
            )
            == "admin_internal"
        )

    def test_education(self) -> None:
        assert (
            classify_app_nature(
                "learning platform with courses, lessons, quizzes and student enrollment",
                ["Course", "Student"],
            )
            == "education"
        )

    def test_fallback_empty(self) -> None:
        assert classify_app_nature("", []) == "task_management"

    def test_fallback_no_match(self) -> None:
        assert classify_app_nature("xyz qrs", ["Foo"]) == "task_management"

    def test_all_profiles_have_keywords(self) -> None:
        """Every profile must have at least one keyword, else it is unreachable."""
        for profile in APP_NATURE_PROFILES:
            assert PROFILE_KEYWORDS.get(profile), (
                f"Profile {profile!r} has no classification keywords"
            )


# ---------------------------------------------------------------------------
# Tier 2 inference
# ---------------------------------------------------------------------------


class TestInferDesignTokens:
    def test_has_populated_fields(self) -> None:
        tokens = infer_design_tokens("task management", ["Task"])
        assert tokens.source == "inferred"
        assert tokens.industry == "task_management"
        assert tokens.personality != ""
        assert tokens.colors["primary"] != ""
        assert tokens.colors["background"] != ""
        assert tokens.typography["font_family_body"] != ""
        assert tokens.design_notes  # non-empty list

    def test_healthcare_has_clinical_personality(self) -> None:
        tokens = infer_design_tokens("patient clinical telehealth", ["Patient"])
        assert tokens.industry == "healthcare"
        assert tokens.personality == "clinical"

    def test_every_profile_round_trips_through_inference(self) -> None:
        for profile, keywords in PROFILE_KEYWORDS.items():
            text = " ".join(keywords[:3])
            tokens = infer_design_tokens(text, [])
            assert tokens.industry == profile


# ---------------------------------------------------------------------------
# Tier 1 HTML extraction
# ---------------------------------------------------------------------------


class TestExtractTokensFromHtml:
    def test_parses_css_custom_properties(self, tmp_path: Path) -> None:
        html = (
            "<html><head><style>:root { "
            "--primary-color: #ff0000; "
            "--background: #ffffff; "
            "--text-primary: #101010; "
            "font-family: 'Playfair Display', serif; "
            "border-radius: 12px; "
            "}</style></head><body class='sidebar'></body></html>"
        )
        ref = tmp_path / "ref.html"
        ref.write_text(html, encoding="utf-8")

        tokens = extract_tokens_from_html(str(ref))
        assert tokens.source == "user_reference"
        assert tokens.colors["primary"] == "#ff0000"
        assert tokens.colors["background"] == "#ffffff"
        assert tokens.colors["text_primary"] == "#101010"
        assert "Playfair Display" in tokens.typography["font_family_body"]
        assert tokens.components["border_radius"] == "lg"  # 12px → lg
        assert tokens.layout["nav_style"] == "sidebar"

    def test_missing_file_returns_empty_record(self, tmp_path: Path) -> None:
        tokens = extract_tokens_from_html(str(tmp_path / "nope.html"))
        assert tokens.source == "user_reference"
        # colors are empty strings, but the record is well-formed
        assert tokens.colors["primary"] == ""


# ---------------------------------------------------------------------------
# resolve_design_tokens priority order
# ---------------------------------------------------------------------------


class TestResolveDesignTokens:
    def test_tier_2_inference_default(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        tokens = resolve_design_tokens(
            config=cfg,
            prd_text="task management with kanban",
            entities=["Task"],
            title="Project Planner",
            cwd=str(tmp_path),
        )
        assert tokens.source == "inferred"
        assert tokens.industry == "task_management"

        out = tmp_path / ".agent-team" / "UI_DESIGN_TOKENS.json"
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["source"] == "inferred"
        assert data["industry"] == "task_management"

    def test_tier_1a_user_reference_wins(self, tmp_path: Path) -> None:
        ref = tmp_path / "reference.html"
        ref.write_text(
            ":root { --primary-color: #abcdef; }",
            encoding="utf-8",
        )
        cfg = AgentTeamConfig()
        cfg.v18.ui_reference_path = str(ref)

        tokens = resolve_design_tokens(
            config=cfg,
            prd_text="task management with kanban",
            entities=["Task"],
            cwd=str(tmp_path),
        )
        assert tokens.source == "user_reference"
        assert tokens.colors["primary"] == "#abcdef"
        # Enrichment still populates industry from PRD.
        assert tokens.industry == "task_management"

    def test_tier_1b_firecrawl_output(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        req_dir = tmp_path / cfg.convergence.requirements_dir
        req_dir.mkdir(parents=True)
        ui_file = req_dir / cfg.design_reference.ui_requirements_file
        ui_file.write_text(
            "# UI\n\nPrimary color: #123456\nfont-family: Inter, sans-serif;\n",
            encoding="utf-8",
        )

        tokens = resolve_design_tokens(
            config=cfg,
            prd_text="task management",
            entities=[],
            cwd=str(tmp_path),
        )
        assert tokens.source == "user_reference"
        assert tokens.colors["primary"] == "#123456"

    def test_disabled_reference_path_falls_back(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.ui_reference_path = str(tmp_path / "does-not-exist.html")

        tokens = resolve_design_tokens(
            config=cfg,
            prd_text="analytics dashboard with kpis",
            entities=[],
            cwd=str(tmp_path),
        )
        assert tokens.source == "inferred"
        assert tokens.industry == "dashboard"


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_round_trip(self, tmp_path: Path) -> None:
        cfg = AgentTeamConfig()
        tokens = resolve_design_tokens(
            config=cfg,
            prd_text="patient clinical appointment",
            entities=[],
            cwd=str(tmp_path),
        )
        reloaded = load_design_tokens(str(tmp_path))
        assert reloaded is not None
        assert reloaded.industry == tokens.industry
        assert reloaded.colors == tokens.colors
        assert reloaded.design_notes == tokens.design_notes

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_design_tokens(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# format_design_tokens_block
# ---------------------------------------------------------------------------


class TestFormatDesignTokensBlock:
    def test_contains_key_sections(self) -> None:
        tokens = infer_design_tokens("task kanban board", [])
        text = format_design_tokens_block(tokens)
        assert "DESIGN SYSTEM" in text
        assert "Source: inferred" in text
        assert "Industry profile: task_management" in text
        assert "Colors:" in text
        assert "Typography:" in text
        assert "Components:" in text
        assert "Layout:" in text
        assert "Design notes:" in text


# ---------------------------------------------------------------------------
# Integration into Wave D / D.5 prompts
# ---------------------------------------------------------------------------


class _FakeMilestone:
    def __init__(self) -> None:
        self.id = "M1"
        self.title = "Orders UI"
        self.acceptance_criteria = ["AC-1"]


class _FakeIR:
    def __init__(self) -> None:
        self.project_name = "Orders"
        self.entities = []
        self.acceptance_criteria = [{"id": "AC-1", "description": "See orders"}]


@pytest.fixture()
def seeded_tokens(tmp_path: Path) -> Path:
    cfg = AgentTeamConfig()
    resolve_design_tokens(
        config=cfg,
        prd_text="task management with kanban",
        entities=["Task"],
        cwd=str(tmp_path),
    )
    return tmp_path


class TestWaveDPromptIncludesDesignSystem:
    def test_d_prompt_has_design_system_when_cwd_passed(
        self, seeded_tokens: Path
    ) -> None:
        from agent_team_v15.agents import build_wave_d_prompt

        prompt = build_wave_d_prompt(
            milestone=_FakeMilestone(),
            ir=_FakeIR(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
            cwd=str(seeded_tokens),
        )
        assert "[DESIGN SYSTEM]" in prompt
        assert "task_management" in prompt

    def test_d_prompt_has_no_design_system_without_tokens_file(
        self, tmp_path: Path
    ) -> None:
        from agent_team_v15.agents import build_wave_d_prompt

        prompt = build_wave_d_prompt(
            milestone=_FakeMilestone(),
            ir=_FakeIR(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
            cwd=str(tmp_path),
        )
        assert "[DESIGN SYSTEM]" not in prompt

    def test_d_prompt_backwards_compatible_without_cwd(self) -> None:
        """Legacy callers that omit cwd still work — no tokens injected."""
        from agent_team_v15.agents import build_wave_d_prompt

        prompt = build_wave_d_prompt(
            milestone=_FakeMilestone(),
            ir=_FakeIR(),
            wave_c_artifact={"client_exports": ["listOrders"]},
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
        )
        assert "[DESIGN SYSTEM]" not in prompt
        assert "packages/api-client" in prompt  # canonical rule intact


class TestWaveD5PromptIncludesDesignContext:
    def test_d5_prompt_contains_design_system_and_personality(
        self, seeded_tokens: Path
    ) -> None:
        from agent_team_v15.agents import build_wave_d5_prompt

        prompt = build_wave_d5_prompt(
            milestone=_FakeMilestone(),
            ir=_FakeIR(),
            wave_d_artifact={"files_created": ["apps/web/src/app/orders/page.tsx"]},
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
            cwd=str(seeded_tokens),
        )
        assert "[DESIGN SYSTEM]" in prompt
        assert "[YOU CAN DO]" in prompt
        assert "[YOU MUST NOT DO]" in prompt
        assert "task_management" in prompt
        assert "Do NOT modify data fetching" in prompt

    def test_d5_prompt_without_cwd_still_functional(self) -> None:
        from agent_team_v15.agents import build_wave_d5_prompt

        prompt = build_wave_d5_prompt(
            milestone=_FakeMilestone(),
            ir=_FakeIR(),
            wave_d_artifact={"files_created": []},
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
        )
        assert "[DESIGN SYSTEM]" not in prompt
        assert "[YOU CAN DO]" in prompt  # new structure is always present
        assert "[YOU MUST NOT DO]" in prompt


# ---------------------------------------------------------------------------
# Duplicate removal check
# ---------------------------------------------------------------------------


def test_only_one_build_wave_d_prompt_definition() -> None:
    """The formerly-shadowed second definition must be gone."""
    import inspect

    import agent_team_v15.agents as agents_mod

    source = inspect.getsource(agents_mod)
    count = source.count("\ndef build_wave_d_prompt(")
    # 1 for the def itself. The first (shadowed) definition was removed.
    assert count == 1, f"Expected 1 build_wave_d_prompt definition, found {count}"


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------


def test_v18_config_has_token_fields() -> None:
    cfg = AgentTeamConfig()
    assert cfg.v18.ui_design_tokens_enabled is True
    assert cfg.v18.ui_reference_path == ""


def test_ui_standards_module_unchanged() -> None:
    """The anti-slop baseline remains a separate module, not folded in."""
    from agent_team_v15 import ui_standards

    assert hasattr(ui_standards, "UI_DESIGN_STANDARDS")
    assert "SLOP-001" in ui_standards.UI_DESIGN_STANDARDS


def test_design_reference_module_still_present() -> None:
    """Legacy Firecrawl pipeline is not deleted — it is a fallback path."""
    from agent_team_v15 import design_reference

    assert hasattr(design_reference, "generate_fallback_ui_requirements")
    assert hasattr(design_reference, "format_ui_requirements_block")
