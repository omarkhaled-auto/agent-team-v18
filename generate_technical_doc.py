"""Generate a professional technical document PDF for the FORGE Coordinated Builder.

v2 — Fixed: TOC overflow, blank pages, callout clipping, orphaned headings.
Uses a two-pass approach: pass 1 builds content and collects TOC entries,
pass 2 rebuilds with correct page numbers in the TOC.
"""

from __future__ import annotations

import os
from fpdf import FPDF

# ─── Brand Identity ───────────────────────────────────────────────────
BRAND_NAME = "FORGE"
BRAND_TAGLINE = "Autonomous Application Engineering"
BRAND_VERSION = "v17.0"
DOC_TITLE = "Technical Reference"
DOC_SUBTITLE = "Coordinated Builder System"
DOC_DATE = "March 2026"

# Colors (RGB)
NAVY = (10, 22, 40)
BLUE = (37, 99, 235)
LIGHT_BLUE = (219, 234, 254)
GOLD = (245, 158, 11)
DARK_GRAY = (31, 41, 55)
MED_GRAY = (107, 114, 128)
LIGHT_GRAY = (243, 244, 246)
WHITE = (255, 255, 255)

PAGE_W = 210
PAGE_H = 297
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 25
MARGIN_B = 25
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
USABLE_H = PAGE_H - MARGIN_T - MARGIN_B - 10  # 10mm for header


def _ascii(text: str) -> str:
    """Replace Unicode characters with ASCII equivalents for core fonts."""
    return (
        text
        .replace("\u2014", " -- ")
        .replace("\u2013", " - ")
        .replace("\u2022", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2026", "...")
        .replace("\u2192", "->")
        .replace("\u2190", "<-")
        .replace("\u2265", ">=")
        .replace("\u2264", "<=")
        .replace("\u00d7", "x")
        .replace("\u2502", "|")
        .replace("\u251c", "+--")
        .replace("\u2514", "+--")
        .replace("\u25b6", ">")
        .replace("\u25cf", "*")
    )


class ForgePDF(FPDF):
    """Custom PDF with FORGE branding."""

    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=MARGIN_B)
        self.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
        self._in_cover = False
        self._in_back_cover = False
        self._chapter_num = 0
        self._section_counts: dict[int, int] = {}
        self._toc_entries: list[tuple[int, str, int]] = []

    def normalize_text(self, text):
        return super().normalize_text(_ascii(text))

    # ── Header / Footer ──────────────────────────────────────────
    def header(self):
        if self._in_cover or self._in_back_cover or self.page_no() <= 1:
            return
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MED_GRAY)
        self.cell(0, 6, f"{BRAND_NAME}  |  {DOC_SUBTITLE}", align="L")
        self.cell(0, 6, BRAND_VERSION, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*BLUE)
        self.set_line_width(0.3)
        self.line(MARGIN_L, self.get_y(), PAGE_W - MARGIN_R, self.get_y())
        self.ln(4)

    def footer(self):
        if self._in_cover or self._in_back_cover or self.page_no() <= 1:
            return
        self.set_y(-18)
        self.set_draw_color(*LIGHT_GRAY)
        self.set_line_width(0.2)
        self.line(MARGIN_L, self.get_y(), PAGE_W - MARGIN_R, self.get_y())
        self.ln(3)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MED_GRAY)
        self.cell(CONTENT_W / 2, 5, f"{BRAND_NAME} {DOC_TITLE}", align="L")
        self.cell(CONTENT_W / 2, 5, f"Page {self.page_no()}", align="R")

    # ── Cover Page ────────────────────────────────────────────────
    def cover_page(self):
        self._in_cover = True
        self.add_page()
        # Disable auto break for cover (we control layout manually)
        self.set_auto_page_break(auto=False)

        # Navy background
        self.set_fill_color(*NAVY)
        self.rect(0, 0, PAGE_W, 185, "F")
        self.set_fill_color(*BLUE)
        self.rect(0, 185, PAGE_W, 3, "F")

        # Gold accent
        self.set_fill_color(*GOLD)
        self.rect(MARGIN_L, 50, 40, 3, "F")

        # Brand name
        self.set_y(60)
        self.set_font("Helvetica", "B", 52)
        self.set_text_color(*WHITE)
        self.cell(0, 20, BRAND_NAME, align="L", new_x="LMARGIN", new_y="NEXT")

        # Tagline
        self.set_font("Helvetica", "", 14)
        self.set_text_color(*LIGHT_BLUE)
        self.cell(0, 8, BRAND_TAGLINE, align="L", new_x="LMARGIN", new_y="NEXT")

        # Separator
        self.ln(20)
        self.set_fill_color(*BLUE)
        self.rect(MARGIN_L, self.get_y(), 60, 0.8, "F")
        self.ln(15)

        # Doc title
        self.set_font("Helvetica", "B", 28)
        self.set_text_color(*WHITE)
        self.cell(0, 14, DOC_TITLE, align="L", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 18)
        self.set_text_color(*LIGHT_BLUE)
        self.cell(0, 10, DOC_SUBTITLE, align="L", new_x="LMARGIN", new_y="NEXT")

        # Metadata
        self.set_y(200)
        meta = [
            ("Version", BRAND_VERSION),
            ("Date", DOC_DATE),
            ("Classification", "Technical Reference"),
            ("Author", "Omar Khaled"),
            ("System", "Agent Team v15 -- Coordinated Builder"),
        ]
        for label, value in meta:
            self.set_font("Helvetica", "B", 10)
            self.set_text_color(*MED_GRAY)
            self.cell(35, 7, label, align="L")
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*DARK_GRAY)
            self.cell(0, 7, value, align="L", new_x="LMARGIN", new_y="NEXT")

        # Confidential footer (placed carefully to avoid page break)
        self.set_y(265)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MED_GRAY)
        self.cell(0, 5, "Confidential -- For authorized recipients only", align="C")

        self.set_auto_page_break(auto=True, margin=MARGIN_B)
        self._in_cover = False

    # ── Table of Contents (written inline with correct page numbers) ──
    def write_toc(self, entries: list[tuple[int, str, int]]):
        """Write table of contents from pre-collected entries."""
        self.add_page()
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*NAVY)
        self.cell(0, 12, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_draw_color(*BLUE)
        self.set_line_width(0.6)
        self.line(MARGIN_L, self.get_y(), MARGIN_L + 50, self.get_y())
        self.ln(8)

        for level, title, pg in entries:
            # Check if we need a new page for TOC continuation
            if self.get_y() > PAGE_H - MARGIN_B - 12:
                self.add_page()
                self.ln(2)

            if level == 1:
                self.set_font("Helvetica", "B", 11)
                self.set_text_color(*NAVY)
                indent = 0
                self.ln(1)
            else:
                self.set_font("Helvetica", "", 10)
                self.set_text_color(*DARK_GRAY)
                indent = 8

            self.set_x(MARGIN_L + indent)
            title_w = CONTENT_W - indent - 15
            self.cell(title_w, 7, title, align="L")
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*MED_GRAY)
            self.cell(15, 7, str(pg), align="R", new_x="LMARGIN", new_y="NEXT")

    # ── Section Helpers ───────────────────────────────────────────
    def chapter_title(self, title: str):
        self._chapter_num += 1
        self._section_counts[self._chapter_num] = 0
        num = f"{self._chapter_num:02d}"
        self.add_page()
        self._toc_entries.append((1, f"{num}  {title}", self.page_no()))

        self.set_font("Helvetica", "B", 42)
        self.set_text_color(*BLUE)
        self.cell(0, 18, num, align="L", new_x="LMARGIN", new_y="NEXT")
        self.set_fill_color(*GOLD)
        self.rect(MARGIN_L, self.get_y() + 1, 35, 2.5, "F")
        self.ln(8)
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*NAVY)
        self.multi_cell(CONTENT_W, 9, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def section_title(self, title: str):
        self._section_counts[self._chapter_num] = self._section_counts.get(self._chapter_num, 0) + 1
        sec = self._section_counts[self._chapter_num]
        num = f"{self._chapter_num}.{sec}"
        self._toc_entries.append((2, f"{num}  {title}", self.page_no()))

        # Keep heading with at least some content — need 30mm
        self._check_space(30)
        self.ln(3)
        self.set_fill_color(*LIGHT_BLUE)
        self.rect(MARGIN_L, self.get_y(), CONTENT_W, 9, "F")
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*NAVY)
        self.set_x(MARGIN_L + 3)
        self.cell(CONTENT_W - 6, 9, f"{num}   {title}", align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def sub_heading(self, title: str):
        # Keep subheading with at least 25mm of content after it
        self._check_space(25)
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*BLUE)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body(self, text: str):
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*DARK_GRAY)
        self.multi_cell(CONTENT_W, 5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def bullet(self, text: str, indent: int = 0):
        self._check_space(8)
        x = MARGIN_L + 4 + indent
        self.set_x(x)
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*DARK_GRAY)
        bw = CONTENT_W - 4 - indent
        self.cell(4, 5, "-")
        self.multi_cell(bw - 4, 5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def code_block(self, code: str, title: str = ""):
        lines = code.strip().split("\n")
        block_h = len(lines) * 4.5 + 6
        total_h = block_h + (5 if title else 0)
        self._check_space(min(total_h, 50))  # At least try to fit, but allow page breaks for big blocks

        if title:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*MED_GRAY)
            self.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")

        self.set_fill_color(30, 30, 46)
        y_start = self.get_y()

        # If block is too tall, just render what fits and continue
        if y_start + block_h > PAGE_H - MARGIN_B - 5:
            # Render partial, let page break handle it
            pass

        self.rect(MARGIN_L, y_start, CONTENT_W, block_h, "F")
        self.ln(3)
        self.set_font("Courier", "", 8)
        self.set_text_color(200, 220, 255)
        for line in lines:
            self.set_x(MARGIN_L + 4)
            self.cell(CONTENT_W - 8, 4.5, line[:110], new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def table(self, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None):
        if col_widths is None:
            col_widths = [CONTENT_W / len(headers)] * len(headers)

        row_h = 8
        total_h = row_h + len(rows) * 7
        self._check_space(min(total_h, 50))  # Try to fit header + some rows

        # Header
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 8.5)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], row_h, f"  {h}", fill=True, border=0, align="L")
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 8.5)
        for idx, row in enumerate(rows):
            # Check for page break before each row
            if self.get_y() > PAGE_H - MARGIN_B - 10:
                self.add_page()
                # Reprint header on new page
                self.set_fill_color(*NAVY)
                self.set_text_color(*WHITE)
                self.set_font("Helvetica", "B", 8.5)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], row_h, f"  {h}", fill=True, border=0, align="L")
                self.ln()
                self.set_font("Helvetica", "", 8.5)

            if idx % 2 == 0:
                self.set_fill_color(*LIGHT_GRAY)
            else:
                self.set_fill_color(*WHITE)
            self.set_text_color(*DARK_GRAY)

            rh = 7
            y_before = self.get_y()
            for i, cell_text in enumerate(row):
                x = self.get_x()
                self.rect(x, y_before, col_widths[i], rh, "F")
                self.set_xy(x + 2, y_before + 1)
                self.multi_cell(col_widths[i] - 4, 4.5, cell_text, border=0)
                actual_h = self.get_y() - y_before
                if actual_h > rh:
                    rh = actual_h
                self.set_xy(x + col_widths[i], y_before)

            # Re-draw backgrounds with correct height if multiline
            if rh > 7:
                if idx % 2 == 0:
                    self.set_fill_color(*LIGHT_GRAY)
                else:
                    self.set_fill_color(*WHITE)
                x_start = MARGIN_L
                for i, cell_text in enumerate(row):
                    self.rect(x_start, y_before, col_widths[i], rh, "F")
                    self.set_xy(x_start + 2, y_before + 1)
                    self.set_text_color(*DARK_GRAY)
                    self.multi_cell(col_widths[i] - 4, 4.5, cell_text, border=0)
                    x_start += col_widths[i]

            self.set_y(y_before + rh)

        self.ln(3)

    def callout(self, text: str):
        """Blue info callout box with dynamic height."""
        self._check_space(20)
        # Calculate actual height needed
        self.set_font("Helvetica", "B", 9)
        text_w = CONTENT_W - 14
        # Estimate lines needed
        words = text.split()
        line = ""
        line_count = 1
        for word in words:
            test = line + " " + word if line else word
            if self.get_string_width(test) > text_w:
                line_count += 1
                line = word
            else:
                line = test
        box_h = max(14, line_count * 5.5 + 6)

        y = self.get_y()
        self.set_fill_color(*LIGHT_BLUE)
        self.rect(MARGIN_L, y, CONTENT_W, box_h, "F")
        self.set_fill_color(*BLUE)
        self.rect(MARGIN_L, y, 3, box_h, "F")
        self.set_xy(MARGIN_L + 6, y + 3)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*BLUE)
        self.multi_cell(text_w, 5, text)
        self.set_y(y + box_h + 2)
        self.ln(2)

    def gold_callout(self, text: str):
        """Gold accent callout box with dynamic height."""
        self._check_space(20)
        self.set_font("Helvetica", "BI", 9)
        text_w = CONTENT_W - 14
        words = text.split()
        line = ""
        line_count = 1
        for word in words:
            test = line + " " + word if line else word
            if self.get_string_width(test) > text_w:
                line_count += 1
                line = word
            else:
                line = test
        box_h = max(14, line_count * 5.5 + 6)

        y = self.get_y()
        self.set_fill_color(254, 243, 199)
        self.rect(MARGIN_L, y, CONTENT_W, box_h, "F")
        self.set_fill_color(*GOLD)
        self.rect(MARGIN_L, y, 3, box_h, "F")
        self.set_xy(MARGIN_L + 6, y + 3)
        self.set_font("Helvetica", "BI", 9)
        self.set_text_color(146, 64, 14)
        self.multi_cell(text_w, 5, text)
        self.set_y(y + box_h + 2)
        self.ln(2)

    def _check_space(self, needed: float):
        """Check if enough space remains on page; if not, add new page."""
        if self.get_y() + needed > PAGE_H - MARGIN_B - 5:
            self.add_page()

    def spacer(self, h: float = 3):
        self.ln(h)


# ═════════════════════════════════════════════════════════════════════
# CONTENT BUILDER — called twice (pass 1 collects TOC, pass 2 is final)
# ═════════════════════════════════════════════════════════════════════

def _build_content(pdf: ForgePDF):
    """Build all chapter content. Returns the TOC entries collected."""

    # ── Chapter 1: Executive Summary ──
    pdf.chapter_title("Executive Summary")
    pdf.body(
        "FORGE is a convergence-driven, multi-agent orchestration system that autonomously transforms "
        "Product Requirements Documents (PRDs) into fully implemented, production-grade applications. "
        "Built on the Claude Agent SDK, FORGE deploys specialized AI agents in a coordinated pipeline "
        "that iteratively builds, audits, and refines code until measurable quality targets are met."
    )
    pdf.body(
        "Unlike conventional AI code generators that produce a single output, FORGE operates in a "
        "closed-loop architecture: an initial build is followed by systematic audit against every "
        "acceptance criterion in the PRD, intelligent triage of findings, targeted fix generation, "
        "and rebuild -- repeating until convergence or a stop condition is reached. This approach "
        "achieves compliance rates of 93%+ with zero regressions, validated on real-world projects."
    )
    pdf.gold_callout(
        "Evidence: EVS Customer Portal -- 103 acceptance criteria, $72 total cost, "
        "84.6% initial build -> 93.5% after one fix cycle, zero regressions."
    )

    pdf.section_title("Key Capabilities")
    for c in [
        "End-to-end application generation from PRD to deployable code",
        "Three-agent audit-fix loop: Audit Agent, Configuration Agent, Fix PRD Agent",
        "Five-layer regression prevention with git snapshots and circuit breakers",
        "20+ technology stack detection with Context7 research integration",
        "40+ anti-pattern quality checks across frontend, backend, and testing",
        "Browser-based validation via Playwright MCP with visual evidence capture",
        "Budget-aware convergence with configurable stop conditions",
        "Full state persistence with resume capability across runs",
    ]:
        pdf.bullet(c)

    pdf.section_title("System at a Glance")
    pdf.table(
        ["Attribute", "Value"],
        [
            ["Architecture", "Multi-agent orchestration with subprocess isolation"],
            ["Core Language", "Python 3.10+"],
            ["AI Foundation", "Claude Agent SDK + Claude Sonnet/Opus models"],
            ["Primary Loop", "Build -> Audit -> Decide -> Fix PRD -> Rebuild"],
            ["Max Iterations", "4 runs (1 initial + 3 fix cycles)"],
            ["Quality Metric", "PRD Acceptance Criteria compliance score"],
            ["Regression Safety", "5-layer defense (prevention + detection + recovery)"],
            ["Browser Testing", "Playwright MCP with Claude operator sessions"],
            ["State Format", "JSON (coordinated_state.json) + archived per run"],
            ["License", "MIT"],
        ],
        [60, CONTENT_W - 60],
    )

    # ── Chapter 2: System Architecture ──
    pdf.chapter_title("System Architecture")
    pdf.body(
        "FORGE operates as a convergence-driven orchestrator that coordinates three specialized agents "
        "in a feedback loop. The system is designed around the principle that iterative, evidence-based "
        "refinement produces higher quality output than single-pass generation."
    )

    pdf.section_title("Architecture Overview")
    pdf.body(
        "The system follows a five-phase pipeline. Phase 1 performs tech research and PRD analysis. "
        "Phase 2 executes the initial build through the standard builder pipeline (PRD parsing, "
        "contract generation, milestone execution, quality scans). Phase 3 enters the audit-fix loop, "
        "where three agents collaborate: the Audit Agent inspects the codebase, the Configuration Agent "
        "decides whether to continue, and the Fix PRD Agent generates targeted corrections. Phase 4 "
        "runs optional browser-based validation. Phase 5 produces the final report."
    )
    pdf.code_block(
        "ORIGINAL PRD (Source of Truth - Never Modified)\n"
        "         |\n"
        "    [Phase 1] Tech Research & Stack Detection\n"
        "         |\n"
        "    [Phase 2] INITIAL BUILD (Standard Pipeline)\n"
        "         |       Parser -> Contracts -> Milestones -> Scans\n"
        "         |\n"
        "    [Phase 3] AUDIT-FIX LOOP (Up to 3 cycles)\n"
        "         |    +---> Audit Agent (inspect vs PRD)\n"
        "         |    |         |\n"
        "         |    |    Config Agent (stop conditions)\n"
        "         |    |         |\n"
        "         |    |    STOP? --YES--> Final Report\n"
        "         |    |         |\n"
        "         |    |    Fix PRD Agent (targeted PRD)\n"
        "         |    |         |\n"
        "         |    +----Builder (rebuild with fix PRD)\n"
        "         |\n"
        "    [Phase 4] BROWSER TEST PHASE (Optional)\n"
        "         |\n"
        "    [Phase 5] FINAL REPORT",
        "System Pipeline Flow"
    )

    pdf.section_title("Core Design Principles")
    for title, desc in [
        ("PRD as Source of Truth", "The original PRD is never modified. Every audit checks against the original requirements. Fix PRDs reference it but create separate, targeted documents."),
        ("Builder Statelessness", "Each builder run starts fresh. Previous run state is archived. The orchestrator maintains cross-run state separately from the builder's own STATE.json."),
        ("Evidence-Based Iteration", "Only measurable findings (acceptance criteria pass/fail) drive iteration. The system does not fix issues it cannot verify."),
        ("Budget-Aware Convergence", "The system stops when the return on investment drops below configurable thresholds, preventing endless iteration."),
        ("Zero Human in Loop", "Between the initial PRD input and the final report, no human intervention is required. The system is fully autonomous."),
    ]:
        pdf.sub_heading(title)
        pdf.body(desc)

    pdf.section_title("Subprocess Isolation Model")
    pdf.body(
        "The orchestrator invokes the builder as a subprocess for clean isolation. Each builder run "
        "creates its own STATE.json, which the orchestrator archives after completion."
    )
    pdf.code_block(
        'cmd = [sys.executable, "-m", "agent_team_v15",\n'
        '       "--prd", str(prd_path),\n'
        '       "--cwd", str(cwd),\n'
        '       "--depth", depth, "--no-interview"]\n\n'
        'result = subprocess.run(cmd, capture_output=True,\n'
        '                        text=True, timeout=7200)',
        "Builder Subprocess Invocation"
    )

    # ── Chapter 3: Tech Research Phase ──
    pdf.chapter_title("Tech Research Phase")
    pdf.body(
        "Before any code is generated, FORGE performs comprehensive technology research to ensure "
        "the builder has up-to-date knowledge of every framework, library, and tool specified in "
        "the PRD. This phase detects the technology stack, generates targeted research queries, "
        "and produces a TECH_RESEARCH.md reference document."
    )

    pdf.section_title("Technology Detection")
    pdf.body(
        "FORGE analyzes the PRD text, package.json, requirements.txt, docker-compose files, and "
        "configuration files to detect the project's technology stack. It recognizes 20+ technologies."
    )
    pdf.table(
        ["Category", "Technologies Detected"],
        [
            ["Frontend", "Next.js, React, Vue, Angular, Svelte"],
            ["Backend", "Express, NestJS, FastAPI, Django, Flask, Spring Boot, Laravel, Rails"],
            ["Databases", "PostgreSQL, MySQL, MongoDB, Redis, SQLite, Supabase, Firebase"],
            ["ORMs", "Prisma, Drizzle, TypeORM, Sequelize, SQLAlchemy, Mongoose"],
            ["UI Libraries", "Tailwind CSS, shadcn/ui, Chakra, Material UI, Ant Design, Radix"],
            ["Testing", "Jest, Vitest, Pytest, Playwright, Cypress, Pact"],
            ["Integrations", "Stripe, SendGrid, Twilio, Plaid, Auth0, Clerk, Resend"],
            ["Utilities", "date-fns, zod, react-hook-form, TanStack Query, Axios, Socket.IO"],
        ],
        [35, CONTENT_W - 35],
    )

    pdf.section_title("Context7 Research Integration")
    pdf.body(
        "For each detected technology, FORGE generates 4 base queries and 4 expanded queries "
        "targeting the Context7 documentation service. This retrieves the latest API references, "
        "best practices, and code examples -- ensuring the builder uses current syntax rather "
        "than potentially outdated training data. The output is compiled into TECH_RESEARCH.md."
    )

    # ── Chapter 4: Initial Build Pipeline ──
    pdf.chapter_title("Initial Build Pipeline")
    pdf.body(
        "The initial build transforms the PRD into a complete application through a multi-stage "
        "pipeline. Each stage is executed by specialized AI agents coordinated by the orchestrator."
    )

    pdf.section_title("Pipeline Stages")
    for i, (title, desc) in enumerate([
        ("PRD Parsing", "The PRD is parsed into a structured ParsedPRD object. Entity definitions, state machines, events, bounded contexts, technology hints, and acceptance criteria are extracted."),
        ("Contract Generation", "Service contracts are generated from parsed entities and bounded contexts. CONTRACTS.md defines interface agreements between services -- endpoints, DTOs, and relationships."),
        ("Milestone Decomposition", "The orchestrator decomposes the parsed PRD into ordered milestones. Each milestone targets a bounded context or service with clear deliverables and dependencies."),
        ("Agent Fleet Deployment", "For each milestone, specialized agents are deployed: architect-agent designs the approach, code-engineer implements, test-engineer writes tests, and integration-agent wires services."),
        ("Quality Scanning", "After each milestone, 40+ anti-pattern checks scan the generated code for violations including SQL injection risks, N+1 queries, hardcoded mock data, and missing error handling."),
        ("Contract Verification", "The contract verifier compares actual code signatures against CONTRACTS.md, flagging missing endpoints, signature mismatches, and undocumented routes."),
        ("E2E Test Execution", "End-to-end tests are generated and executed to verify the integrated application works as a whole, not just individual components."),
        ("Convergence Check", "The orchestrator evaluates whether all milestones meet quality gates. Failing milestones trigger review cycles with targeted fixes."),
    ], 1):
        pdf.sub_heading(f"Stage {i}: {title}")
        pdf.body(desc)

    pdf.section_title("Specialized Agent Types")
    pdf.table(
        ["Agent", "Role", "Capabilities"],
        [
            ["Orchestrator", "Coordination", "Decomposes PRD, assigns milestones, manages convergence"],
            ["Architect", "Design", "Designs file structure, API contracts, data models"],
            ["Code Engineer", "Implementation", "Writes production code following architect's plan"],
            ["Test Engineer", "Testing", "Writes unit/integration tests, validates coverage"],
            ["Integration Agent", "Wiring", "Connects services, routes, middleware, shared state"],
            ["Research Agent", "Knowledge", "Queries Context7, gathers library documentation"],
            ["Scanner Agent", "Quality", "Runs anti-pattern checks, reports violations"],
            ["Review Agent", "Verification", "Reviews code changes against requirements"],
        ],
        [35, 28, CONTENT_W - 63],
    )

    pdf.section_title("Build Depth Levels")
    pdf.table(
        ["Depth", "Description", "Quality Gates"],
        [
            ["quick", "Fast prototype, minimal checks", "Basic syntax only"],
            ["standard", "Production code, standard checks", "Anti-patterns + contracts"],
            ["exhaustive", "Maximum quality, full audit", "All checks + convergence + browser tests"],
        ],
        [28, 55, CONTENT_W - 83],
    )

    # ── Chapter 5: Audit Agent ──
    pdf.chapter_title("Audit Agent")
    pdf.body(
        "The Audit Agent is the quality backbone of FORGE. After each build, it systematically "
        "compares the generated codebase against every acceptance criterion, business rule, entity "
        "specification, and non-functional requirement in the original PRD."
    )

    pdf.section_title("Three-Tier Inspection Methodology")
    pdf.sub_heading("Tier 1: Static Checks ($0 -- No API Calls)")
    pdf.body(
        "Approximately 30% of acceptance criteria can be verified through file existence checks, "
        "string/pattern grep, constant value validation, and import verification."
    )
    pdf.table(
        ["Check Type", "Example", "Method"],
        [
            ["File Existence", '"Has a Dockerfile"', "Path(codebase / 'Dockerfile').exists()"],
            ["String Presence", '"uses httpOnly cookies"', "grep for 'httpOnly' in auth code"],
            ["Constant Values", '"expires after 15 minutes"', "grep for 15*60, 900, '15m'"],
            ["Import Checks", '"uses bcrypt for hashing"', "grep for 'import.*bcrypt'"],
            ["Entity Fields", '"User has email field"', "check schema/model files"],
        ],
        [32, 42, CONTENT_W - 74],
    )

    pdf.sub_heading("Tier 2: Claude-Assisted Behavioral Checks (~$0.15)")
    pdf.body(
        "About 50% of acceptance criteria require semantic understanding. The audit agent sends "
        "relevant code sections and the AC text to Claude Sonnet for evaluation. Each check returns "
        "PASS, FAIL, or PARTIAL with evidence citing specific file paths and line numbers."
    )
    pdf.table(
        ["Check Type", "What It Verifies"],
        [
            ["Logic Flow", "Code implements the specified business logic sequence"],
            ["State Transitions", "State machine transitions match PRD specifications"],
            ["Business Rules", "Calculations, validations, and constraints are correct"],
            ["Error Handling", "Error cases are handled as specified in the PRD"],
        ],
        [40, CONTENT_W - 40],
    )

    pdf.sub_heading("Tier 3: Classification Only ($0)")
    pdf.body(
        "Approximately 20% of acceptance criteria cannot be verified without runtime execution "
        "or external system access. These are classified as REQUIRES_HUMAN and excluded from "
        "the score calculation."
    )

    pdf.section_title("Acceptance Criterion Extraction")
    pdf.body(
        "The audit agent extracts acceptance criteria from the PRD using multi-pattern regex "
        "matching. It supports four common PRD formats and associates each AC with its parent "
        "feature via heading tracking."
    )
    pdf.code_block(
        '# Supported AC formats:\n'
        '- [x] AC-001: Requirement text       # checkbox\n'
        '**AC-002:** Requirement text           # bold\n'
        'AC-003: Requirement text               # plain\n'
        'Acceptance Criterion 4: Text           # long-form\n\n'
        '# Feature association via headings:\n'
        '## Feature F-001: User Authentication\n'
        '### F-002: Dashboard',
        "PRD Acceptance Criterion Formats"
    )

    pdf.section_title("Severity Classification")
    pdf.table(
        ["Severity", "Criteria", "Examples"],
        [
            ["CRITICAL", "Security, data loss, missing feature", "No auth on endpoint, missing migration"],
            ["HIGH", "Partial functionality, wrong behavior", "Wrong validation logic"],
            ["MEDIUM", "Minor logic errors, edge cases", "Off-by-one, wrong default value"],
            ["LOW", "Cosmetic, suboptimal patterns", "Naming conventions, styling"],
            ["ACCEPTABLE_DEV", "Builder made a better choice", "Used modern pattern instead"],
            ["REQUIRES_HUMAN", "External systems, visual eval", "API testing, benchmarks"],
        ],
        [32, 48, CONTENT_W - 80],
    )

    pdf.section_title("Finding Data Structure")
    pdf.table(
        ["Field", "Type", "Description"],
        [
            ["id", "string", "Unique ID (e.g., F001-AC10)"],
            ["feature", "string", "Parent feature reference"],
            ["acceptance_criterion", "string", "Full AC text from PRD"],
            ["severity", "enum", "CRITICAL | HIGH | MEDIUM | LOW | ACCEPTABLE | HUMAN"],
            ["category", "enum", "code_fix | missing_feature | security | regression"],
            ["file_path", "string", "Source file containing the issue"],
            ["line_number", "int", "Line number of the problematic code"],
            ["code_snippet", "string", "Current code at the location"],
            ["fix_suggestion", "string", "Recommended change"],
            ["estimated_effort", "enum", "trivial | small | medium | large"],
        ],
        [38, 20, CONTENT_W - 58],
    )

    pdf.section_title("Scoring Formula")
    pdf.callout(
        "Score = (passed + 0.5 x partial) / (total - skipped) x 100%  "
        "Where 'skipped' = REQUIRES_HUMAN ACs (excluded from denominator)."
    )

    # ── Chapter 6: Configuration Agent ──
    pdf.chapter_title("Configuration Agent")
    pdf.body(
        "The Configuration Agent is the decision-making core of the audit-fix loop. After each audit, "
        "it evaluates whether to STOP or CONTINUE, applies circuit breaker safety checks, triages "
        "findings by priority and budget, and estimates costs for the next fix run."
    )

    pdf.section_title("Stop Condition Evaluation")
    pdf.body("Five stop conditions are evaluated in order. The first triggered wins.")

    pdf.sub_heading("Condition 1: Circuit Breaker (Safety)")
    pdf.table(
        ["Level", "Trigger", "Action"],
        [
            ["L1 (Warning)", "Score dropped from previous run", "Log warning, continue"],
            ["L2 (Stop)", "Score dropped 2 consecutive runs", "STOP: 'OSCILLATING'"],
            ["L3 (Stop)", "Regressions > new fixes", "STOP: 'REGRESSION_SPIRAL'"],
        ],
        [28, 52, CONTENT_W - 80],
    )

    pdf.sub_heading("Condition 2: Convergence")
    pdf.code_block(
        "IF improvement < 3% AND critical == 0 AND high == 0:\n"
        '    STOP("CONVERGED")',
        "Convergence Check"
    )

    pdf.sub_heading("Condition 3: Zero Actionable")
    pdf.code_block(
        "IF count(CRITICAL + HIGH + MEDIUM) == 0:\n"
        '    STOP("COMPLETE")',
        "Completion Check"
    )

    pdf.sub_heading("Condition 4: Budget Exhausted")
    pdf.code_block(
        "IF total_cost >= initial_build_cost x 3:\n"
        '    STOP("BUDGET")',
        "Budget Check"
    )

    pdf.sub_heading("Condition 5: Maximum Iterations")
    pdf.code_block(
        'IF current_run >= 4:  STOP("MAX_ITERATIONS")',
        "Iteration Limit"
    )

    pdf.section_title("Finding Triage")
    pdf.body(
        "When the decision is CONTINUE, findings are triaged by priority for the next fix run. "
        "Maximum 15 findings per fix PRD to prevent context window overflow."
    )
    pdf.table(
        ["Priority", "Finding Types", "Inclusion Rule"],
        [
            ["1 (Highest)", "All CRITICAL findings", "Always included"],
            ["2", "All HIGH findings", "Included if budget allows"],
            ["3", "MEDIUM code_fix + missing_feature", "Budget permitting"],
            ["4", "MEDIUM test_gap + performance", "Deferred unless surplus"],
            ["5 (Lowest)", "LOW, ACCEPTABLE, REQUIRES_HUMAN", "Always deferred"],
        ],
        [28, 50, CONTENT_W - 78],
    )

    pdf.section_title("Cost Estimation Model")
    pdf.body(
        "The configuration agent estimates the cost of fixing each finding based on category "
        "and effort level."
    )
    pdf.table(
        ["Category", "Base Cost ($)", "Effort Multipliers"],
        [
            ["code_fix", "3.00", "trivial: 0.5x  |  small: 1.0x"],
            ["missing_feature", "8.00", "medium: 1.5x  |  large: 2.5x"],
            ["security", "5.00", "Applied to base cost"],
            ["test_gap", "3.00", "Applied to base cost"],
            ["regression", "5.00", "Applied to base cost"],
            ["performance", "5.00", "Applied to base cost"],
        ],
        [38, 28, CONTENT_W - 66],
    )

    # ── Chapter 7: Fix PRD Agent ──
    pdf.chapter_title("Fix PRD Agent")
    pdf.body(
        "The Fix PRD Agent generates a parser-valid PRD document from structured audit findings. "
        "Fix PRDs are not special-mode instructions -- they are complete, standard PRDs that the "
        "builder processes through its normal pipeline. The PRD itself is what makes it targeted."
    )

    pdf.section_title("Fix PRD Structure")
    pdf.table(
        ["Section", "Content", "Purpose"],
        [
            ["Product Overview", "Fix run declaration, paths, count", "Context and scope"],
            ["Technology Stack", "Verbatim copy from original PRD", "Parser compatibility"],
            ["Existing Context", "Unchanged entities in brief table", "Awareness without regeneration"],
            ["Entities", "Only modified/new entities", "Targeted code generation"],
            ["Bounded Contexts", "FIX/FEAT items with code snippets", "Specific changes with evidence"],
            ["Regression Prevention", "DO NOT MODIFY + passing ACs", "Prevents breaking existing code"],
            ["Success Criteria", "Testable criterion per fix", "Verification targets"],
        ],
        [35, 50, CONTENT_W - 85],
    )

    pdf.section_title("Code Context Enrichment")
    pdf.body(
        "For each finding, the fix PRD agent reads the codebase to extract current code snippets "
        "at the finding's file path and line number. These snippets are embedded directly in the "
        "fix PRD, showing the builder exactly what needs to change."
    )

    pdf.section_title("Entity Handling Strategy")
    pdf.body("All entities are included but in different sections:")
    pdf.bullet("Existing Context: All unchanged entities in brief table format. Parser extracts them for relationship awareness, builder instructed not to regenerate.", 0)
    pdf.bullet("Entities: Only modified or new entities in full detail for code generation.", 0)
    pdf.bullet("Prose explicitly states 'DO NOT REGENERATE' for existing entities.", 0)

    pdf.section_title("Parser Compatibility Validation")
    pdf.body(
        "After generation, the fix PRD is validated against the builder's parser. If validation "
        "fails, the agent regenerates with adjusted formatting (up to 2 retries). Checks: H1 title "
        "present, technology section exists, minimum 200 characters of content."
    )

    # ── Chapter 8: Regression Prevention ──
    pdf.chapter_title("Regression Prevention")
    pdf.body(
        "FORGE employs a five-layer defense strategy to prevent regressions during fix cycles. "
        "No single layer is 100% preventive, but combined they provide 90%+ prevention, "
        "100% detection, and full recovery capability."
    )

    pdf.section_title("Defense Layers")
    for title, effectiveness, desc in [
        ("Layer 1: Fix PRD Language", "80%",
         "Explicit 'DO NOT MODIFY' instructions and file scoping in the fix PRD. Prompt-based, not structurally enforced."),
        ("Layer 2: Git Snapshots", "100% detectable, 100% recoverable",
         "Before each fix run, the orchestrator creates a git commit snapshot. After the run, git diff shows what changed. Git revert enables full rollback."),
        ("Layer 3: Previously Passing AC List", "~70%",
         "The fix PRD lists all previously passing ACs with 'MUST STILL PASS' instructions. The builder's test-engineer milestone verifies them."),
        ("Layer 4: Surgical Code Context", "~85%",
         "Fix PRDs include current code snippets with specific change descriptions, preventing unnecessary file rewrites."),
        ("Layer 5: Post-Fix Audit", "100% detection",
         "The next audit explicitly checks every previously passing AC. Regressions are flagged. Circuit breaker stops if regressions exceed fixes."),
    ]:
        pdf.sub_heading(f"{title} -- Effectiveness: {effectiveness}")
        pdf.body(desc)

    pdf.section_title("Combined Effectiveness")
    pdf.table(
        ["Defense Type", "Layers", "Coverage"],
        [
            ["Prevention", "L1 + L3 + L4", "~90% of regressions prevented"],
            ["Detection", "L2 + L5", "100% of regressions detected"],
            ["Recovery", "L2 (Git Snapshot)", "Full rollback available"],
        ],
        [28, 52, CONTENT_W - 80],
    )
    pdf.gold_callout(
        "EVS Customer Portal achieved zero regressions with Layer 1 alone. "
        "Layers 2-5 provide defense in depth for more complex projects."
    )

    # ── Chapter 9: Browser Test Phase ──
    pdf.chapter_title("Browser Test Phase")
    pdf.body(
        "The Browser Test Phase extends quality assurance beyond static code analysis to runtime "
        "validation. After the audit-fix loop converges at ~93% compliance, the browser test phase "
        "opens a real browser to verify the application actually works as users would experience it."
    )
    pdf.callout(
        "Why browser tests matter: Pages can render but buttons have non-functional handlers. "
        "Forms validate client-side but APIs return 500. Navigation links point to nonexistent routes. "
        "These bugs only surface in a real browser."
    )

    pdf.section_title("Phase Workflow")
    pdf.body("The browser test phase executes in eight steps:")
    for i, s in enumerate([
        "Extract workflows from PRD user journeys and feature specs (Claude, one-time)",
        "Start application (Docker Compose + dev server + database migrations)",
        "Setup test authentication (seed credentials or programmatic session creation)",
        "Execute workflows via Claude operator sessions with Playwright MCP tools",
        "Collect screenshots and pass/fail status per step with console error capture",
        "If failures: generate fix PRD from browser findings",
        "Run builder with fix PRD, then re-test (up to 2 additional iterations)",
        "Stop application, archive screenshots, generate evidence report",
    ], 1):
        pdf.bullet(f"Step {i}: {s}")

    pdf.section_title("Workflow Extraction")
    pdf.body(
        "Claude reads the PRD text once and converts natural language workflows into structured "
        "WorkflowStep objects. Two PRD formats are supported:"
    )
    pdf.code_block(
        "# Format 1: User Journeys (arrow-delimited)\n"
        "Open app -> Tap repair -> View status -> Close app\n\n"
        "# Format 2: Feature Workflows (numbered steps)\n"
        '1. Customer sees "Action Required" badge\n'
        "2. Quotation detail loads\n"
        '3. Customer taps "Approve"\n'
        "4. Backend calls external API (marked SKIP)",
        "PRD Workflow Formats"
    )

    pdf.section_title("Action Types")
    pdf.table(
        ["Action", "Description", "Example"],
        [
            ["navigate", "Go to a URL path", "/dashboard"],
            ["click", "Click button or link", "Approve button"],
            ["type", "Type text into input", "test@example.com"],
            ["wait", "Wait for element", "Spinner disappears"],
            ["verify_text", "Verify content exists", "'Welcome back' message"],
            ["verify_element", "Verify UI element visible", "Navigation menu"],
            ["verify_url", "Verify current URL", "/dashboard/overview"],
            ["select", "Select from dropdown", "Status: Active"],
            ["scroll", "Scroll to element", "Footer section"],
        ],
        [28, 42, CONTENT_W - 70],
    )

    pdf.section_title("Browser Test Engine")
    pdf.body(
        "The BrowserTestEngine executes workflows through Claude operator sessions with Playwright "
        "MCP tools. It is stack-aware (Next.js, Vite, Express) and handles Docker setup, migrations, "
        "seeding, test user creation, screenshot capture, and console error collection. Failures are "
        "automatically converted to Finding objects for seamless browser-fix iteration."
    )

    # ── Chapter 10: Quality Assurance Framework ──
    pdf.chapter_title("Quality Assurance Framework")
    pdf.body(
        "FORGE includes a comprehensive quality assurance framework that runs 40+ anti-pattern "
        "checks on generated code during the initial build."
    )

    pdf.section_title("Violation Categories")
    pdf.table(
        ["Category", "Code Range", "Examples"],
        [
            ["Frontend", "FRONT-001 to FRONT-010", "Using 'any' type, console.log in production"],
            ["Backend", "BACK-001 to BACK-016", "SQL injection, N+1 queries, no transactions"],
            ["Mock Detection", "MOCK-001 to MOCK-007", "Hardcoded data in services, fake API calls"],
            ["UI Compliance", "UI-001 to UI-004", "Wrong colors, fonts, spacing vs design system"],
            ["E2E Quality", "E2E-001 to E2E-007", "Hardcoded ports, missing timeouts, empty tests"],
        ],
        [30, 38, CONTENT_W - 68],
    )

    pdf.section_title("Violation Classification")
    pdf.table(
        ["Classification", "Meaning", "Builder Action"],
        [
            ["FIXABLE_CODE", "Can be fixed with code changes", "Automatic fix in review cycle"],
            ["FIXABLE_LOGIC", "Logic error requiring design change", "Fix with architect guidance"],
            ["UNFIXABLE_INFRA", "Infrastructure limitation", "Document and defer"],
            ["UNFIXABLE_ARCH", "Architectural constraint", "Document and defer"],
        ],
        [35, 48, CONTENT_W - 83],
    )

    pdf.section_title("Contract Verification")
    pdf.body(
        "The contract verifier compares actual code signatures against CONTRACTS.md, ensuring "
        "service interfaces remain consistent throughout the build. It detects:"
    )
    pdf.bullet("Missing endpoints declared in contracts but not implemented")
    pdf.bullet("Extra endpoints in code but not documented in contracts")
    pdf.bullet("Signature mismatches between declared and actual DTOs")
    pdf.bullet("Undocumented routes that bypass the contract system")

    # ── Chapter 11: State Management ──
    pdf.chapter_title("State Management & Persistence")
    pdf.body(
        "FORGE maintains comprehensive state across all runs, enabling resume capability, "
        "audit trails, and post-mortem analysis."
    )

    pdf.section_title("State Architecture")
    pdf.table(
        ["State File", "Owner", "Lifecycle"],
        [
            ["coordinated_state.json", "Orchestrator", "Persists across all runs"],
            ["STATE.json", "Builder", "Created fresh each run, archived"],
            ["STATE.json.runN", "Orchestrator", "Archived copy for run N"],
            ["audit_runN.json", "Audit Agent", "Structured findings for run N"],
            ["fix_prd_runN.md", "Fix PRD Agent", "Generated fix PRD for run N"],
            ["FINAL_REPORT.md", "Orchestrator", "Summary at loop termination"],
        ],
        [42, 26, CONTENT_W - 68],
    )

    pdf.section_title("File Organization")
    pdf.code_block(
        "output/\n"
        "+-- .agent-team/\n"
        "|   +-- coordinated_state.json   # Cross-run loop state\n"
        "|   +-- audit_run1.json          # Audit after initial build\n"
        "|   +-- fix_prd_run2.md          # Fix PRD for first fix\n"
        "|   +-- STATE.json               # Current builder state\n"
        "|   +-- STATE.json.run1          # Archived initial state\n"
        "|   +-- FINAL_REPORT.md          # Loop summary report\n"
        "|   +-- screenshots/             # Browser test evidence\n"
        "+-- src/                          # Generated source code\n"
        "+-- tests/                        # Generated tests\n"
        "+-- CONTRACTS.md                  # Service contracts",
        "Output Directory Structure"
    )

    pdf.section_title("Loop State Schema")
    pdf.table(
        ["Field", "Type", "Description"],
        [
            ["schema_version", "int", "Schema version for compatibility"],
            ["original_prd_path", "string", "Path to original PRD"],
            ["config", "object", "Budget, iterations, threshold, depth, model"],
            ["runs[]", "array", "Run records with audit data"],
            ["total_cost", "float", "Cumulative cost across all runs"],
            ["current_run", "int", "Current run number"],
            ["status", "enum", "running | converged | stopped | failed"],
            ["stop_reason", "string", "Human-readable stop reason"],
        ],
        [38, 20, CONTENT_W - 58],
    )

    pdf.section_title("Run Record Schema")
    pdf.table(
        ["Field", "Type", "Description"],
        [
            ["run_number", "int", "Sequential run number"],
            ["type", "enum", "initial | fix"],
            ["cost", "float", "Builder cost for this run"],
            ["score", "float", "Audit score after this run"],
            ["total_acs / passed_acs", "int", "Total and passing ACs"],
            ["critical / high count", "int", "Severity counts"],
            ["regression_count", "int", "Regressions from previous run"],
            ["timestamp", "ISO 8601", "When this run completed"],
        ],
        [38, 20, CONTENT_W - 58],
    )

    # ── Chapter 12: Configuration & CLI Reference ──
    pdf.chapter_title("Configuration & CLI Reference")

    pdf.section_title("Coordinated Build Configuration")
    pdf.table(
        ["Parameter", "Default", "Description"],
        [
            ["max_budget", "3x initial cost", "Maximum total spend across all runs"],
            ["max_iterations", "4", "Maximum runs (1 initial + 3 fix)"],
            ["min_improvement", "3.0%", "Min score improvement for convergence"],
            ["depth", "exhaustive", "Build depth (quick/standard/exhaustive)"],
            ["audit_model", "claude-sonnet-4", "Model for audit Claude calls"],
            ["skip_initial_build", "false", "Skip initial build (testing/resume)"],
            ["builder_timeout", "7200s (2hr)", "Max time per builder run"],
        ],
        [38, 35, CONTENT_W - 73],
    )

    pdf.section_title("Browser Test Configuration")
    pdf.table(
        ["Parameter", "Default", "Description"],
        [
            ["enabled", "true", "Enable/disable browser test phase"],
            ["max_iterations", "2", "Max browser-fix cycles"],
            ["port", "3080", "Application port for browser tests"],
            ["operator_model", "claude-sonnet-4", "Model for browser operator"],
        ],
        [38, 35, CONTENT_W - 73],
    )

    pdf.section_title("CLI Commands")
    pdf.code_block(
        '# Full coordinated build\n'
        'python -m agent_team_v15 coordinated-build \\\n'
        '    --prd "path/to/prd.md" --cwd "./output" \\\n'
        '    --max-budget 300 --depth exhaustive\n\n'
        '# Standalone audit\n'
        'python -m agent_team_v15 audit \\\n'
        '    --prd "original.md" --cwd "./build" \\\n'
        '    --output "audit_report.json"\n\n'
        '# Generate fix PRD from audit\n'
        'python -m agent_team_v15 generate-fix-prd \\\n'
        '    --prd "original.md" --cwd "./build" \\\n'
        '    --audit-report "audit.json" --output "fix.md"',
        "CLI Commands"
    )

    pdf.section_title("Programmatic API")
    pdf.code_block(
        'from pathlib import Path\n'
        'from agent_team_v15.coordinated_builder import (\n'
        '    run_coordinated_build,\n'
        ')\n\n'
        'result = run_coordinated_build(\n'
        '    prd_path=Path("my_app.md"),\n'
        '    cwd=Path("./output"),\n'
        '    config={"max_budget": 300, "depth": "exhaustive"},\n'
        ')\n'
        'print(f"Score: {result.final_score:.1f}%")\n'
        'print(f"Cost: ${result.total_cost:.2f}")\n'
        'print(f"Runs: {result.total_runs}")',
        "Python API Usage"
    )

    # ── Chapter 13: Performance & Cost Profile ──
    pdf.chapter_title("Performance & Cost Profile")

    pdf.section_title("Evidence-Based Metrics")
    pdf.body(
        "Metrics from the EVS Customer Portal -- a real-world application with 103 acceptance criteria."
    )
    pdf.table(
        ["Metric", "Run 1 (Initial)", "Run 2 (Fix)", "Final"],
        [
            ["Score", "84.6%", "93.5%", "93.5%"],
            ["ACs Passed", "78/103", "93/103", "93/103"],
            ["CRITICAL", "2", "0", "0"],
            ["HIGH", "8", "0", "0"],
            ["Regressions", "N/A", "0", "0"],
            ["Cost", "$62", "$10", "$72 total"],
        ],
        [35, 35, 35, CONTENT_W - 105],
    )

    pdf.section_title("Cost Breakdown by Component")
    pdf.table(
        ["Component", "Cost Range", "Notes"],
        [
            ["Initial Build", "$50 - $150", "Depends on PRD complexity"],
            ["Audit Agent", "$0.20 - $0.35/run", "Claude Sonnet behavioral checks"],
            ["Fix PRD Generation", "$0.10 - $0.20", "Template + Claude enrichment"],
            ["Fix Build", "$10 - $40/run", "Reduced scope vs initial"],
            ["Browser Tests", "$0.50 - $2.00/run", "Claude operator sessions"],
        ],
        [38, 33, CONTENT_W - 71],
    )

    pdf.section_title("Time Profile")
    pdf.table(
        ["Phase", "Duration", "Notes"],
        [
            ["Initial Build", "30-60 min", "Full pipeline with all milestones"],
            ["Audit", "2-5 min", "Static + Claude behavioral checks"],
            ["Fix PRD Generation", "1-2 min", "Template assembly + enrichment"],
            ["Fix Build", "15-30 min", "Targeted rebuild, reduced scope"],
            ["Browser Tests", "5-15 min", "Depends on workflow count"],
            ["Total (4 runs)", "2-4 hours", "Wall-clock including all iterations"],
        ],
        [38, 28, CONTENT_W - 66],
    )

    # ── Chapter 14: Error Handling ──
    pdf.chapter_title("Error Handling & Recovery")

    pdf.section_title("Error Taxonomy")
    pdf.table(
        ["Error Class", "Trigger", "System Response"],
        [
            ["BuilderRunError", "Builder crashes or times out", "STOP: BUILDER_FAILURE"],
            ["AuditError", "Audit agent fails (API/parsing)", "Retry once, then STOP"],
            ["PRDGenerationError", "Fix PRD generation fails", "STOP: PRD_GENERATION_FAILURE"],
            ["Budget Exceeded", "Total cost exceeds cap", "Complete run, then STOP"],
            ["Git Failure", "Git operations fail", "Continue without safety net"],
        ],
        [35, 42, CONTENT_W - 77],
    )

    pdf.section_title("Recovery Strategies")
    pdf.bullet("Resume from state: orchestrator saves state after every action; interrupted runs resume from last checkpoint")
    pdf.bullet("Audit retry: failures trigger one automatic retry before stopping (transient API errors)")
    pdf.bullet("Git rollback: catastrophic regressions can be reverted via git revert")
    pdf.bullet("State archival: every builder STATE.json is archived for forensic analysis")

    # ── Chapter 15: Dependencies ──
    pdf.chapter_title("Dependencies & Requirements")

    pdf.section_title("System Requirements")
    pdf.table(
        ["Requirement", "Minimum", "Recommended"],
        [
            ["Python", "3.10+", "3.12+"],
            ["Claude Agent SDK", "0.1.26+", "Latest"],
            ["Anthropic API Key", "Required", "Required"],
            ["Git", "2.x (optional)", "2.40+"],
            ["Docker", "Optional", "24.x+ (for browser tests)"],
        ],
        [35, 32, CONTENT_W - 67],
    )

    pdf.section_title("Python Dependencies")
    pdf.table(
        ["Package", "Version", "Purpose"],
        [
            ["claude-agent-sdk", ">=0.1.26", "Core AI agent orchestration"],
            ["pyyaml", ">=6.0", "Configuration file parsing"],
            ["rich", ">=13.0", "Terminal output formatting"],
            ["python-dotenv", ">=1.0 (opt)", "Environment variable management"],
            ["pytest", ">=7.0 (dev)", "Test framework"],
        ],
        [35, 26, CONTENT_W - 61],
    )

    pdf.section_title("Source Code Structure")
    pdf.table(
        ["File", "Lines", "Responsibility"],
        [
            ["coordinated_builder.py", "~750", "Orchestrator loop, state management"],
            ["audit_agent.py", "~1,200", "AC extraction, inspection, findings"],
            ["config_agent.py", "~450", "Stop conditions, circuit breaker, triage"],
            ["fix_prd_agent.py", "~550", "Fix PRD generation, validation"],
            ["quality_checks.py", "~1,800", "40+ anti-pattern checks"],
            ["tech_research.py", "~1,300", "Tech detection, Context7 queries"],
            ["browser_test_agent.py", "~1,100", "Workflow extraction, Playwright"],
            ["app_lifecycle.py", "~615", "Docker, migrations, health checks"],
            ["agents.py", "~2,000", "Agent definitions, orchestrator prompt"],
            ["cli.py", "~1,200", "CLI interface, argument parsing"],
        ],
        [42, 16, CONTENT_W - 58],
    )

    return pdf._toc_entries


def _build_back_cover(pdf: ForgePDF):
    """Add the back cover page."""
    pdf._in_back_cover = True
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, PAGE_W, PAGE_H, "F")

    pdf.set_y(100)
    pdf.set_fill_color(*GOLD)
    pdf.rect(PAGE_W / 2 - 20, pdf.get_y(), 40, 3, "F")
    pdf.ln(15)

    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 16, BRAND_NAME, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(*LIGHT_BLUE)
    pdf.cell(0, 8, BRAND_TAGLINE, align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(30)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MED_GRAY)
    pdf.cell(0, 6, "Agent Team v15  |  Coordinated Builder System", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Version {BRAND_VERSION}  |  {DOC_DATE}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.cell(0, 6, "Designed and built by Omar Khaled", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(265)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(80, 80, 100)
    pdf.cell(0, 5, "Confidential -- For authorized recipients only", align="C")

    pdf.set_auto_page_break(auto=True, margin=MARGIN_B)
    # Keep _in_back_cover = True so footer() skips this page during output()


def _draw_flowchart(pdf: ForgePDF):
    """Draw a full-page visual flowchart of the FORGE pipeline."""
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)  # Manual layout — no auto breaks

    # ── Page title ──
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, "FORGE Pipeline -- End-to-End Workflow", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.5)
    cx = PAGE_W / 2
    pdf.line(cx - 40, pdf.get_y(), cx + 40, pdf.get_y())
    pdf.ln(6)

    # ── Drawing helpers ──
    def box(x, y, w, h, label, fill_color, text_color=WHITE, font_size=9, bold=True):
        pdf.set_fill_color(*fill_color)
        pdf.set_draw_color(*fill_color)
        # Rounded-ish box via rect
        pdf.rect(x, y, w, h, "F")
        pdf.set_font("Helvetica", "B" if bold else "", font_size)
        pdf.set_text_color(*text_color)
        # Center text
        lines = label.split("\n")
        line_h = font_size * 0.4
        total_h = len(lines) * line_h
        start_y = y + (h - total_h) / 2
        for i, line in enumerate(lines):
            tw = pdf.get_string_width(line)
            pdf.set_xy(x + (w - tw) / 2, start_y + i * line_h)
            pdf.cell(tw, line_h, line)

    def arrow_down(x, y1, y2):
        pdf.set_draw_color(*DARK_GRAY)
        pdf.set_line_width(0.6)
        pdf.line(x, y1, x, y2 - 2)
        # Arrowhead
        pdf.set_fill_color(*DARK_GRAY)
        pdf.polygon([(x - 2, y2 - 4), (x + 2, y2 - 4), (x, y2)], style="F")

    def arrow_right(x1, y, x2):
        pdf.set_draw_color(*DARK_GRAY)
        pdf.set_line_width(0.6)
        pdf.line(x1, y, x2 - 2, y)
        pdf.set_fill_color(*DARK_GRAY)
        pdf.polygon([(x2 - 4, y - 2), (x2 - 4, y + 2), (x2, y)], style="F")

    def loop_arrow(x_right, y_top, y_bottom, x_left):
        """Draw a loop-back arrow on the left side."""
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.8)
        # Down on the left
        pdf.line(x_left, y_top, x_left, y_bottom)
        # Right to center
        pdf.line(x_left, y_bottom, x_right, y_bottom)
        # Up arrow at top
        pdf.line(x_left, y_top, x_right, y_top)
        # Arrowhead pointing right at top
        pdf.set_fill_color(*GOLD)
        pdf.polygon([(x_right - 4, y_top - 2), (x_right - 4, y_top + 2), (x_right, y_top)], style="F")

    # ── Layout constants ──
    bw = 100  # box width
    bh = 12   # box height
    bx = cx - bw / 2  # box x (centered)
    gap = 8   # gap between boxes
    y = pdf.get_y() + 2

    # ── 1. PRD Input ──
    box(bx, y, bw, bh, "PRD Input", NAVY)
    y += bh
    arrow_down(cx, y, y + gap)
    y += gap

    # ── 2. Tech Research ──
    box(bx, y, bw, bh, "Tech Research Phase", (30, 64, 175))
    # Side note
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(50, 4, "Context7 queries")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(50, 4, "20+ tech detection")
    y += bh
    arrow_down(cx, y, y + gap)
    y += gap

    # ── 3. Initial Build ──
    box(bx, y, bw, 15, "Initial Build\n(Standard Pipeline)", BLUE)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(55, 4, "PRD Parser")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(55, 4, "Contracts + Milestones")
    pdf.set_xy(bx + bw + 5, y + 9)
    pdf.cell(55, 4, "Quality Scans")
    y += 15
    arrow_down(cx, y, y + gap)
    y += gap

    # ── AUDIT-FIX LOOP boundary ──
    loop_y_start = y
    loop_box_x = bx - 18
    loop_box_w = bw + 36

    # Dashed border for the loop region
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.4)
    loop_h = 105
    # Draw dashed border manually
    pdf.rect(loop_box_x, loop_y_start - 4, loop_box_w, loop_h, "D")

    # Loop label
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*GOLD)
    pdf.set_xy(loop_box_x + 2, loop_y_start - 3)
    pdf.cell(40, 4, "AUDIT-FIX LOOP")
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(loop_box_x + 43, loop_y_start - 3)
    pdf.cell(30, 4, "(up to 3 cycles)")

    y += 3

    # ── 4. Audit Agent ──
    box(bx, y, bw, bh, "Audit Agent", (55, 48, 163))
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(55, 4, "3-tier inspection")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(55, 4, "AC extraction + scoring")
    y += bh
    arrow_down(cx, y, y + gap)
    y += gap

    # ── 5. Config Agent (Diamond-ish decision) ──
    box(bx, y, bw, bh, "Configuration Agent", (55, 48, 163))
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(55, 4, "5 stop conditions")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(55, 4, "Circuit breaker")
    y += bh
    arrow_down(cx, y, y + gap - 1)
    y += gap

    # ── Decision: STOP? ──
    dw, dh = 50, 14
    dx = cx - dw / 2
    # Diamond shape via polygon
    diamond_cx = cx
    diamond_cy = y + dh / 2
    pdf.set_fill_color(220, 38, 38)  # red
    pdf.polygon([
        (diamond_cx, y),
        (diamond_cx + dw / 2, diamond_cy),
        (diamond_cx, y + dh),
        (diamond_cx - dw / 2, diamond_cy),
    ], style="F")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*WHITE)
    tw = pdf.get_string_width("STOP?")
    pdf.set_xy(diamond_cx - tw / 2, diamond_cy - 2)
    pdf.cell(tw, 5, "STOP?")

    # YES arrow to the right -> Final Report (side box)
    yes_y = diamond_cy
    yes_x_start = diamond_cx + dw / 2
    report_x = bx + bw + 8
    report_w = 40
    arrow_right(yes_x_start, yes_y, report_x)
    box(report_x, yes_y - 6, report_w, bh, "Final Report", (22, 163, 74), WHITE, 8)  # green
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(22, 163, 74)
    pdf.set_xy(yes_x_start + 2, yes_y - 6)
    pdf.cell(10, 4, "YES")

    # NO arrow down
    y += dh
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(220, 38, 38)
    pdf.set_xy(cx + 2, y - 2)
    pdf.cell(10, 4, "NO")
    arrow_down(cx, y, y + gap - 1)
    y += gap

    # ── 6. Fix PRD Agent ──
    box(bx, y, bw, bh, "Fix PRD Agent", (55, 48, 163))
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(55, 4, "Parser-valid fix PRD")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(55, 4, "Regression prevention")
    y += bh

    # Loop-back arrow (left side) from Fix PRD back up to Audit Agent
    loop_arrow(bx, loop_y_start + 6, y + 3, loop_box_x + 5)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*GOLD)
    pdf.set_xy(loop_box_x + 6, loop_y_start + (y + 3 - loop_y_start) / 2 - 2)
    pdf.cell(12, 4, "LOOP")

    y = loop_y_start + loop_h + 2
    arrow_down(cx, y - 6, y + gap - 2)
    y += gap

    # ── 7. Browser Test Phase ──
    box(bx, y, bw, 15, "Browser Test Phase\n(Playwright MCP)", (15, 118, 110))
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MED_GRAY)
    pdf.set_xy(bx + bw + 5, y + 1)
    pdf.cell(55, 4, "Workflow extraction")
    pdf.set_xy(bx + bw + 5, y + 5)
    pdf.cell(55, 4, "Claude operator sessions")
    pdf.set_xy(bx + bw + 5, y + 9)
    pdf.cell(55, 4, "Screenshot evidence")
    y += 15
    arrow_down(cx, y, y + gap)
    y += gap

    # ── 8. Output Artifacts ──
    box(bx, y, bw, bh, "Output Artifacts", NAVY)
    y += bh + 3

    # Artifact boxes (small, in a row)
    art_w = 42
    art_h = 10
    art_gap = 4
    art_x = cx - (art_w * 3 + art_gap * 2) / 2
    artifacts = [
        ("Source Code\n+ Tests", (37, 99, 235)),
        ("CONTRACTS.md\n+ State", (55, 48, 163)),
        ("FINAL_REPORT\n+ Screenshots", (22, 163, 74)),
    ]
    for i, (label, color) in enumerate(artifacts):
        ax = art_x + i * (art_w + art_gap)
        box(ax, y, art_w, art_h, label, color, WHITE, 7)

    # ── Legend at bottom ──
    y += art_h + 10
    pdf.set_y(y)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 5, "Legend", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    legend_items = [
        (NAVY, "Input / Output"),
        ((30, 64, 175), "Research Phase"),
        (BLUE, "Build Phase"),
        ((55, 48, 163), "Audit-Fix Agents"),
        ((15, 118, 110), "Browser Testing"),
        ((22, 163, 74), "Completion"),
        ((220, 38, 38), "Decision Point"),
        (GOLD, "Iteration Loop"),
    ]
    lx = MARGIN_L
    ly = pdf.get_y()
    col_w = CONTENT_W / 4
    for i, (color, label) in enumerate(legend_items):
        col = i % 4
        row = i // 4
        x = lx + col * col_w
        yy = ly + row * 8
        pdf.set_fill_color(*color)
        pdf.rect(x, yy + 1, 6, 4, "F")
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*DARK_GRAY)
        pdf.set_xy(x + 8, yy)
        pdf.cell(col_w - 10, 6, label)

    pdf.set_auto_page_break(auto=True, margin=MARGIN_B)  # Restore


def build_document():
    """Build the FORGE technical reference PDF using a two-pass approach."""

    # ── Pass 1: Build content to collect TOC entries and page numbers ──
    pdf1 = ForgePDF()
    pdf1.cover_page()
    # Skip TOC in pass 1 — just build content
    toc_entries = _build_content(pdf1)
    total_content_pages = pdf1.page_no()

    # Calculate how many pages the TOC will need
    toc_line_h = 8  # height per entry
    toc_header_h = 30  # title + underline + spacing
    usable_toc_h = PAGE_H - MARGIN_T - MARGIN_B - 15  # Account for header/footer
    first_page_entries = int((usable_toc_h - toc_header_h) / toc_line_h)
    remaining_entries = len(toc_entries) - first_page_entries
    toc_pages = 1 + max(0, (remaining_entries + int(usable_toc_h / toc_line_h) - 1) // int(usable_toc_h / toc_line_h))

    # Adjust page numbers: all content pages shift by toc_pages
    adjusted_entries = [
        (level, title, pg + toc_pages)  # page 1 = cover, then toc_pages, then content
        for level, title, pg in toc_entries
    ]

    # ── Pass 2: Build final PDF with TOC ──
    pdf = ForgePDF()
    pdf.cover_page()
    pdf.write_toc(adjusted_entries)
    _build_content(pdf)
    _draw_flowchart(pdf)
    _build_back_cover(pdf)

    output_path = os.path.join(os.path.dirname(__file__), "FORGE_Technical_Reference.pdf")
    pdf.output(output_path)
    print(f"PDF generated: {output_path} ({pdf.page_no()} pages)")
    return output_path


if __name__ == "__main__":
    build_document()
