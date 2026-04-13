"""UI Design Token Pipeline — two-tier design guidance for Wave D and D.5.

Tier 1  Extract structured design tokens from a user-provided HTML
        reference (``ui_reference_path``) OR from the scraped output of
        the Firecrawl-based ``design_reference`` pipeline.

Tier 2  Infer app-nature design personality from PRD keywords when no
        reference is available.  Deterministic keyword scoring — no LLM
        call, no network, no non-determinism.

Both tiers produce a ``UIDesignTokens`` record.  ``resolve_design_tokens``
is the single public entry point: it picks the best available source,
fills an ``UIDesignTokens`` instance, and writes
``.agent-team/UI_DESIGN_TOKENS.json`` for downstream Wave D / Wave D.5
prompts to consume.

The tokens are GUIDANCE, not hard requirements.  Wave D / D.5 prompts
should frame them as "use these as your design system", not "you must
use exactly these hex codes".
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class UIDesignTokens:
    """Structured design tokens — machine-readable, not prose."""

    source: str = "inferred"  # "user_reference" | "inferred"

    colors: dict = field(default_factory=lambda: {
        "primary": "",
        "secondary": "",
        "accent": "",
        "background": "",
        "surface": "",
        "text_primary": "",
        "text_secondary": "",
        "error": "",
        "warning": "",
        "success": "",
        "info": "",
    })

    typography: dict = field(default_factory=lambda: {
        "font_family_heading": "",
        "font_family_body": "",
        "font_family_mono": "",
        "scale": "default",  # "compact" | "default" | "spacious"
    })

    spacing: dict = field(default_factory=lambda: {
        "base_unit": "4px",
        "density": "default",  # "compact" | "default" | "comfortable"
    })

    components: dict = field(default_factory=lambda: {
        "border_radius": "md",     # "none" | "sm" | "md" | "lg" | "full"
        "shadow_depth": "sm",      # "none" | "sm" | "md" | "lg"
        "button_style": "filled",  # "filled" | "outlined" | "ghost"
    })

    layout: dict = field(default_factory=lambda: {
        "nav_style": "sidebar",   # "sidebar" | "topbar" | "minimal"
        "content_max_width": "1280px",
        "responsive_breakpoints": "standard",
        "density": "default",
    })

    personality: str = ""
    industry: str = ""
    design_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tier 2: App-nature profiles + classifier
# ---------------------------------------------------------------------------


APP_NATURE_PROFILES: dict[str, dict[str, Any]] = {
    "task_management": {
        "personality": "professional",
        "colors": {
            "primary": "#2563eb",
            "secondary": "#475569",
            "accent": "#f59e0b",
            "background": "#f8fafc",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_secondary": "#64748b",
            "error": "#dc2626",
            "warning": "#f59e0b",
            "success": "#16a34a",
            "info": "#0ea5e9",
        },
        "typography": {
            "font_family_heading": "Inter, system-ui, sans-serif",
            "font_family_body": "Inter, system-ui, sans-serif",
            "font_family_mono": "JetBrains Mono, monospace",
            "scale": "default",
        },
        "components": {"border_radius": "md", "shadow_depth": "sm", "button_style": "filled"},
        "layout": {"nav_style": "sidebar", "content_max_width": "1280px", "density": "default"},
        "design_notes": [
            "Prioritize scannability — users process many items quickly",
            "Status indicators must be color-coded AND icon-coded (accessibility)",
            "Tables should be compact with row hover states",
            "Kanban columns should have clear visual separation",
            "Use priority badges with distinct colors (low=gray, medium=blue, high=orange, urgent=red)",
        ],
    },
    "healthcare": {
        "personality": "clinical",
        "colors": {
            "primary": "#0891b2",
            "secondary": "#475569",
            "accent": "#059669",
            "background": "#f0fdfa",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_secondary": "#64748b",
            "error": "#b91c1c",
            "warning": "#d97706",
            "success": "#059669",
            "info": "#0284c7",
        },
        "typography": {
            "font_family_heading": "system-ui, -apple-system, sans-serif",
            "font_family_body": "system-ui, -apple-system, sans-serif",
            "font_family_mono": "ui-monospace, monospace",
            "scale": "spacious",
        },
        "components": {"border_radius": "lg", "shadow_depth": "sm", "button_style": "filled"},
        "layout": {"nav_style": "topbar", "content_max_width": "1280px", "density": "comfortable"},
        "design_notes": [
            "WCAG AAA compliance required — minimum 7:1 contrast ratio",
            "Large touch targets (min 44x44px) for clinical environments",
            "Clear visual hierarchy for critical information",
            "Calming color palette — avoid aggressive reds except for true emergencies",
            "Patient data blocks must be clearly separated from navigation chrome",
        ],
    },
    "ecommerce": {
        "personality": "conversion-focused",
        "colors": {
            "primary": "#7c3aed",
            "secondary": "#1e293b",
            "accent": "#f43f5e",
            "background": "#ffffff",
            "surface": "#f8fafc",
            "text_primary": "#0f172a",
            "text_secondary": "#64748b",
            "error": "#dc2626",
            "warning": "#f59e0b",
            "success": "#16a34a",
            "info": "#0ea5e9",
        },
        "typography": {
            "font_family_heading": "system-ui, sans-serif",
            "font_family_body": "system-ui, sans-serif",
            "font_family_mono": "ui-monospace, monospace",
            "scale": "default",
        },
        "components": {"border_radius": "lg", "shadow_depth": "md", "button_style": "filled"},
        "layout": {"nav_style": "topbar", "content_max_width": "1440px", "density": "comfortable"},
        "design_notes": [
            "CTAs must be visually dominant — large, high-contrast, action-oriented",
            "Product images are primary content — generous card space",
            "Price and availability must be immediately visible",
            "Cart/checkout flow must feel secure and simple",
            "Use badges for discounts, 'new', 'low-stock' signals",
        ],
    },
    "financial": {
        "personality": "conservative",
        "colors": {
            "primary": "#1e40af",
            "secondary": "#334155",
            "accent": "#0d9488",
            "background": "#f1f5f9",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_secondary": "#475569",
            "error": "#b91c1c",
            "warning": "#b45309",
            "success": "#15803d",
            "info": "#1d4ed8",
        },
        "typography": {
            "font_family_heading": "Inter, system-ui, sans-serif",
            "font_family_body": "Inter, system-ui, sans-serif",
            "font_family_mono": "JetBrains Mono, ui-monospace, monospace",
            "scale": "compact",
        },
        "components": {"border_radius": "sm", "shadow_depth": "none", "button_style": "outlined"},
        "layout": {"nav_style": "sidebar", "content_max_width": "1440px", "density": "compact"},
        "design_notes": [
            "Data density is high — use compact tables and tight spacing",
            "Numbers must be monospaced and right-aligned",
            "Green/red for gains/losses — never ambiguous",
            "Minimal decoration — trust comes from clarity, not prettiness",
            "Always show as-of timestamps near any monetary value",
        ],
    },
    "dashboard": {
        "personality": "analytical",
        "colors": {
            "primary": "#3b82f6",
            "secondary": "#475569",
            "accent": "#8b5cf6",
            "background": "#0f172a",
            "surface": "#1e293b",
            "text_primary": "#f1f5f9",
            "text_secondary": "#94a3b8",
            "error": "#f87171",
            "warning": "#fbbf24",
            "success": "#34d399",
            "info": "#60a5fa",
        },
        "typography": {
            "font_family_heading": "Inter, system-ui, sans-serif",
            "font_family_body": "Inter, system-ui, sans-serif",
            "font_family_mono": "JetBrains Mono, monospace",
            "scale": "compact",
        },
        "components": {"border_radius": "md", "shadow_depth": "none", "button_style": "ghost"},
        "layout": {"nav_style": "sidebar", "content_max_width": "1440px", "density": "compact"},
        "design_notes": [
            "Dark mode default — reduces eye strain for prolonged data monitoring",
            "Charts should use a consistent color palette across the app",
            "KPI cards at the top with trend indicators",
            "Tables should support column resizing and row pinning",
            "Reserve accent color for the single most important insight per view",
        ],
    },
    "social": {
        "personality": "engaging",
        "colors": {
            "primary": "#6366f1",
            "secondary": "#ec4899",
            "accent": "#f59e0b",
            "background": "#fafafa",
            "surface": "#ffffff",
            "text_primary": "#1a1a1a",
            "text_secondary": "#737373",
            "error": "#ef4444",
            "warning": "#f59e0b",
            "success": "#22c55e",
            "info": "#3b82f6",
        },
        "typography": {
            "font_family_heading": "system-ui, sans-serif",
            "font_family_body": "system-ui, sans-serif",
            "font_family_mono": "ui-monospace, monospace",
            "scale": "default",
        },
        "components": {"border_radius": "full", "shadow_depth": "md", "button_style": "filled"},
        "layout": {"nav_style": "topbar", "content_max_width": "1200px", "density": "comfortable"},
        "design_notes": [
            "Avatars are prominent — round, with online indicators",
            "Real-time feel — subtle animations for new content",
            "Feed-style layout with infinite scroll",
            "Reactions/likes need immediate visual feedback",
            "Notification badges must be visible but not overwhelming",
        ],
    },
    "admin_internal": {
        "personality": "functional",
        "colors": {
            "primary": "#4f46e5",
            "secondary": "#475569",
            "accent": "#06b6d4",
            "background": "#f8fafc",
            "surface": "#ffffff",
            "text_primary": "#0f172a",
            "text_secondary": "#64748b",
            "error": "#dc2626",
            "warning": "#d97706",
            "success": "#16a34a",
            "info": "#0284c7",
        },
        "typography": {
            "font_family_heading": "system-ui, sans-serif",
            "font_family_body": "system-ui, sans-serif",
            "font_family_mono": "ui-monospace, SFMono-Regular, monospace",
            "scale": "compact",
        },
        "components": {"border_radius": "sm", "shadow_depth": "sm", "button_style": "outlined"},
        "layout": {"nav_style": "sidebar", "content_max_width": "1600px", "density": "compact"},
        "design_notes": [
            "Function over form — every pixel should serve a purpose",
            "Dense layouts acceptable — users are trained power users",
            "Bulk actions (multi-select, batch operations) must be prominent",
            "Minimal branding — neutral palette, no decorative elements",
            "Keyboard shortcuts should be visible and documented in UI",
        ],
    },
    "education": {
        "personality": "approachable",
        "colors": {
            "primary": "#2563eb",
            "secondary": "#7c3aed",
            "accent": "#f59e0b",
            "background": "#fffbeb",
            "surface": "#ffffff",
            "text_primary": "#1e293b",
            "text_secondary": "#64748b",
            "error": "#dc2626",
            "warning": "#d97706",
            "success": "#16a34a",
            "info": "#0284c7",
        },
        "typography": {
            "font_family_heading": "system-ui, sans-serif",
            "font_family_body": "system-ui, sans-serif",
            "font_family_mono": "ui-monospace, monospace",
            "scale": "spacious",
        },
        "components": {"border_radius": "lg", "shadow_depth": "md", "button_style": "filled"},
        "layout": {"nav_style": "topbar", "content_max_width": "1200px", "density": "comfortable"},
        "design_notes": [
            "Progress indicators everywhere — completion bars, streak counters",
            "Encouraging micro-copy — 'Great job!', 'Keep going!'",
            "Clear visual hierarchy for lesson content vs navigation",
            "Large, tappable buttons for accessibility across age groups",
            "Celebrate milestones with micro-interactions (confetti, check animations)",
        ],
    },
}

DEFAULT_PROFILE_KEY = "task_management"


PROFILE_KEYWORDS: dict[str, list[str]] = {
    "task_management": [
        "task", "project", "kanban", "board", "sprint", "backlog",
        "assign", "deadline", "milestone", "todo", "ticket", "issue tracker",
    ],
    "healthcare": [
        "patient", "medical", "clinical", "health", "diagnosis", "appointment",
        "prescription", "doctor", "nurse", "ehr", "emr", "clinician", "telehealth",
    ],
    "ecommerce": [
        "product", "cart", "checkout", "price", "catalog", "order",
        "payment", "shipping", "inventory", "shop", "storefront", "sku",
    ],
    "financial": [
        "account", "transaction", "balance", "portfolio", "investment",
        "banking", "ledger", "statement", "fund", "asset", "liability",
        "accounting", "invoice", "trading",
    ],
    "dashboard": [
        "dashboard", "analytics", "metrics", "kpi", "chart",
        "monitoring", "report", "visualization", "telemetry", "observability",
    ],
    "social": [
        "post", "feed", "comment", "like", "follow", "profile",
        "message", "notification", "share", "friend", "chat", "dm", "timeline",
    ],
    "admin_internal": [
        "admin", "management console", "configuration", "settings panel",
        "users management", "permissions", "roles", "audit log", "rbac",
        "internal tool", "back office",
    ],
    "education": [
        "course", "lesson", "quiz", "student", "enrollment", "progress",
        "grade", "learning", "curriculum", "tutor", "assignment", "lecture",
    ],
}


def classify_app_nature(
    prd_text: str,
    entities: list[str] | None = None,
    title: str = "",
) -> str:
    """Classify the app's design personality from PRD content.

    Deterministic keyword scoring — no LLM call.  The profile whose
    keywords appear most often in the combined text wins.  Falls back
    to ``task_management`` when nothing matches.
    """
    parts: list[str] = []
    if prd_text:
        parts.append(prd_text)
    if title:
        parts.append(title)
    if entities:
        parts.extend(str(e) for e in entities)
    text = " ".join(parts).lower()

    if not text.strip():
        return DEFAULT_PROFILE_KEY

    scores: dict[str, int] = {}
    for profile, keywords in PROFILE_KEYWORDS.items():
        scores[profile] = sum(1 for kw in keywords if kw in text)

    if not scores or max(scores.values()) == 0:
        return DEFAULT_PROFILE_KEY

    # Deterministic tie-break: first profile in PROFILE_KEYWORDS insertion order.
    best_score = max(scores.values())
    for profile in PROFILE_KEYWORDS:
        if scores[profile] == best_score:
            return profile
    return DEFAULT_PROFILE_KEY  # unreachable


def infer_design_tokens(
    prd_text: str,
    entities: list[str] | None = None,
    title: str = "",
) -> UIDesignTokens:
    """Infer design tokens from PRD content (Tier 2)."""
    nature = classify_app_nature(prd_text, entities or [], title)
    profile = APP_NATURE_PROFILES.get(nature, APP_NATURE_PROFILES[DEFAULT_PROFILE_KEY])

    tokens = UIDesignTokens(
        source="inferred",
        colors=dict(profile.get("colors", {})),
        typography=dict(profile.get("typography", {})),
        spacing={
            "base_unit": "4px",
            "density": profile.get("layout", {}).get("density", "default"),
        },
        components=dict(profile.get("components", {})),
        layout=dict(profile.get("layout", {})),
        personality=profile.get("personality", ""),
        industry=nature,
        design_notes=list(profile.get("design_notes", [])),
    )
    return tokens


# ---------------------------------------------------------------------------
# Tier 1: Extract tokens from a user-provided reference
# ---------------------------------------------------------------------------


_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_CSS_VAR_RE = re.compile(
    r"--([a-z0-9-]+)\s*:\s*([^;}\n]+?)(?:;|})",
    re.IGNORECASE,
)
_FONT_FAMILY_RE = re.compile(
    r"font-family\s*:\s*([^;}\n]+?)(?:;|})",
    re.IGNORECASE,
)
_RADIUS_RE = re.compile(
    r"border-radius\s*:\s*([^;}\n]+?)(?:;|})",
    re.IGNORECASE,
)

_CSS_VAR_NAME_TO_TOKEN = {
    "primary": "primary",
    "primary-color": "primary",
    "color-primary": "primary",
    "brand": "primary",
    "brand-color": "primary",
    "secondary": "secondary",
    "secondary-color": "secondary",
    "accent": "accent",
    "accent-color": "accent",
    "background": "background",
    "background-color": "background",
    "bg": "background",
    "bg-color": "background",
    "surface": "surface",
    "surface-color": "surface",
    "card": "surface",
    "text": "text_primary",
    "text-color": "text_primary",
    "foreground": "text_primary",
    "color-text": "text_primary",
    "text-primary": "text_primary",
    "text-secondary": "text_secondary",
    "muted": "text_secondary",
    "error": "error",
    "danger": "error",
    "warning": "warning",
    "success": "success",
    "info": "info",
}


def _classify_radius(value: str) -> str:
    v = value.strip().lower()
    if v in ("0", "0px", "none"):
        return "none"
    if "9999" in v or "full" in v or "50%" in v:
        return "full"
    # Heuristic: map explicit pixel values.
    m = re.match(r"(\d+(?:\.\d+)?)\s*(px|rem)", v)
    if m:
        num = float(m.group(1))
        unit = m.group(2)
        px = num * 16 if unit == "rem" else num
        if px <= 4:
            return "sm"
        if px <= 10:
            return "md"
        return "lg"
    return "md"


def extract_tokens_from_html(html_path: str) -> UIDesignTokens:
    """Extract design tokens from a user-provided HTML/CSS reference file.

    Parses CSS custom properties (``--primary-color: #...``) and common
    inline style fragments.  Deterministic regex extraction — no LLM
    call.  Also accepts plain text or Markdown (reads raw content and
    scans for hex codes and ``font-family:`` declarations), so the
    Firecrawl-produced ``UI_REQUIREMENTS.md`` can be fed in too.
    """
    tokens = UIDesignTokens(source="user_reference")

    try:
        content = Path(html_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read reference file %s: %s", html_path, exc)
        return tokens

    colors = dict(tokens.colors)
    # 1) CSS custom properties mapped to semantic token slots.
    for match in _CSS_VAR_RE.finditer(content):
        var_name = match.group(1).strip().lower()
        raw_value = match.group(2).strip().strip(';').strip()
        slot = _CSS_VAR_NAME_TO_TOKEN.get(var_name)
        if slot is None:
            continue
        hex_match = _HEX_RE.search(raw_value)
        if hex_match:
            colors[slot] = hex_match.group(0)
        elif raw_value and not colors.get(slot):
            colors[slot] = raw_value

    # 2) Fallback: fill empty primary/background from first/last seen hex values.
    all_hex = _HEX_RE.findall(content)
    if all_hex:
        if not colors.get("primary"):
            colors["primary"] = all_hex[0]
        if not colors.get("background") and len(all_hex) > 1:
            colors["background"] = all_hex[-1]
    tokens.colors = colors

    # 3) Typography — font-family declarations and named :root vars.
    typography = dict(tokens.typography)
    font_families = _FONT_FAMILY_RE.findall(content)
    if font_families:
        body_font = font_families[0].strip().strip('"').strip("'")
        typography["font_family_body"] = body_font
        typography["font_family_heading"] = body_font
        if len(font_families) > 1:
            typography["font_family_heading"] = font_families[1].strip().strip('"').strip("'")
    tokens.typography = typography

    # 4) Component hints — border-radius.
    components = dict(tokens.components)
    radii = _RADIUS_RE.findall(content)
    if radii:
        components["border_radius"] = _classify_radius(radii[0])
    tokens.components = components

    # 5) Layout: detect sidebar vs topbar heuristically.
    layout = dict(tokens.layout)
    if re.search(r"\b(sidebar|side-nav|side_nav|aside)\b", content, re.IGNORECASE):
        layout["nav_style"] = "sidebar"
    elif re.search(r"\b(topbar|top-nav|header-nav|navbar)\b", content, re.IGNORECASE):
        layout["nav_style"] = "topbar"
    tokens.layout = layout

    return tokens


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _existing_ui_requirements_path(config: Any, cwd: str) -> Path | None:
    """Return the Firecrawl-produced UI_REQUIREMENTS.md path if present."""
    try:
        req_dir = config.convergence.requirements_dir
        ui_file = config.design_reference.ui_requirements_file
    except AttributeError:
        return None
    candidate = Path(cwd) / req_dir / ui_file
    if candidate.is_file() and candidate.stat().st_size > 0:
        return candidate
    return None


def resolve_design_tokens(
    config: Any,
    prd_text: str,
    entities: list[str] | None = None,
    title: str = "",
    cwd: str = "",
) -> UIDesignTokens:
    """Resolve design tokens from the best available source.

    Priority order:

    1. ``V18Config.ui_reference_path`` — user-provided HTML reference.
    2. Firecrawl-produced ``UI_REQUIREMENTS.md`` — existing design
       extraction output, treated as a reference to parse.
    3. Tier 2 inference from PRD text + entities + title.

    Writes ``.agent-team/UI_DESIGN_TOKENS.json`` to ``cwd`` when
    supplied, so Wave D and D.5 prompts can load it later.
    """
    tokens: UIDesignTokens | None = None

    # Tier 1a: explicit user-provided HTML reference.
    v18 = getattr(config, "v18", None) if config is not None else None
    ui_ref_path = str(getattr(v18, "ui_reference_path", "") or "").strip() if v18 else ""
    if ui_ref_path:
        candidate = Path(ui_ref_path)
        if candidate.is_file():
            try:
                tokens = extract_tokens_from_html(str(candidate))
                logger.info("Extracted design tokens from user reference: %s", candidate)
            except Exception as exc:  # defensive — regex extractor is tolerant
                logger.warning("Failed to extract tokens from %s: %s", candidate, exc)
                tokens = None
        else:
            logger.warning("ui_reference_path does not exist: %s", candidate)

    # Tier 1b: Firecrawl output as automated reference.
    if tokens is None and cwd and config is not None:
        firecrawl_out = _existing_ui_requirements_path(config, cwd)
        if firecrawl_out is not None:
            try:
                tokens = extract_tokens_from_html(str(firecrawl_out))
                logger.info(
                    "Extracted design tokens from Firecrawl output: %s", firecrawl_out,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to extract tokens from %s: %s", firecrawl_out, exc,
                )
                tokens = None

    # Tier 2: infer from PRD.
    if tokens is None:
        tokens = infer_design_tokens(prd_text, entities or [], title)
        logger.info(
            "Inferred design tokens: industry=%s personality=%s",
            tokens.industry, tokens.personality,
        )

    # If Tier 1 succeeded, still enrich empty fields from the inferred profile
    # so Wave D/D.5 always get a full record.
    if tokens.source == "user_reference":
        enriched = infer_design_tokens(prd_text, entities or [], title)
        tokens.industry = tokens.industry or enriched.industry
        tokens.personality = tokens.personality or enriched.personality
        if not tokens.design_notes:
            tokens.design_notes = list(enriched.design_notes)
        for slot, value in enriched.colors.items():
            if not tokens.colors.get(slot):
                tokens.colors[slot] = value
        for key, value in enriched.typography.items():
            if not tokens.typography.get(key):
                tokens.typography[key] = value
        for key, value in enriched.components.items():
            if not tokens.components.get(key):
                tokens.components[key] = value
        for key, value in enriched.layout.items():
            if not tokens.layout.get(key):
                tokens.layout[key] = value

    if cwd:
        try:
            out_path = Path(cwd) / ".agent-team" / "UI_DESIGN_TOKENS.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(dataclasses.asdict(tokens), indent=2),
                encoding="utf-8",
            )
            logger.info("Wrote design tokens to %s", out_path)
        except OSError as exc:
            logger.warning("Failed to persist UI_DESIGN_TOKENS.json: %s", exc)

    return tokens


def load_design_tokens(cwd: str) -> UIDesignTokens | None:
    """Load previously persisted ``UI_DESIGN_TOKENS.json`` if it exists."""
    if not cwd:
        return None
    path = Path(cwd) / ".agent-team" / "UI_DESIGN_TOKENS.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load UI_DESIGN_TOKENS.json: %s", exc)
        return None
    return UIDesignTokens(
        source=str(data.get("source", "inferred")),
        colors=dict(data.get("colors", {})),
        typography=dict(data.get("typography", {})),
        spacing=dict(data.get("spacing", {})),
        components=dict(data.get("components", {})),
        layout=dict(data.get("layout", {})),
        personality=str(data.get("personality", "")),
        industry=str(data.get("industry", "")),
        design_notes=list(data.get("design_notes", [])),
    )


def format_design_tokens_block(tokens: UIDesignTokens) -> str:
    """Format a tokens record as a prompt-friendly ``[DESIGN SYSTEM]`` block."""
    lines: list[str] = [
        "============================================================",
        "DESIGN SYSTEM (from UI_DESIGN_TOKENS.json)",
        "============================================================",
        f"Source: {tokens.source}",
        f"Industry profile: {tokens.industry or 'unknown'}",
        f"Personality: {tokens.personality or 'unknown'}",
        "",
        "Colors:",
    ]
    for key, value in tokens.colors.items():
        if value:
            lines.append(f"  - {key}: {value}")

    lines.append("")
    lines.append("Typography:")
    for key, value in tokens.typography.items():
        if value:
            lines.append(f"  - {key}: {value}")

    lines.append("")
    lines.append("Spacing / density:")
    for key, value in tokens.spacing.items():
        if value:
            lines.append(f"  - {key}: {value}")

    lines.append("")
    lines.append("Components:")
    for key, value in tokens.components.items():
        if value:
            lines.append(f"  - {key}: {value}")

    lines.append("")
    lines.append("Layout:")
    for key, value in tokens.layout.items():
        if value:
            lines.append(f"  - {key}: {value}")

    if tokens.design_notes:
        lines.append("")
        lines.append("Design notes:")
        for note in tokens.design_notes:
            lines.append(f"  - {note}")

    if tokens.source == "user_reference":
        lines.append("")
        lines.append(
            "Match the user-provided reference closely — these tokens were "
            "extracted from the user's design reference.",
        )
    else:
        lines.append("")
        lines.append(
            "These tokens are inferred from the PRD's domain. Use them as a "
            "starting point; deviate when a specific component needs it, but "
            "stay within the stated personality.",
        )
    lines.append(
        "============================================================",
    )
    return "\n".join(lines)


__all__ = [
    "UIDesignTokens",
    "APP_NATURE_PROFILES",
    "PROFILE_KEYWORDS",
    "classify_app_nature",
    "infer_design_tokens",
    "extract_tokens_from_html",
    "resolve_design_tokens",
    "load_design_tokens",
    "format_design_tokens_block",
]
