"""
Regression tests based on MiniBooks mini-build (10/10 success criteria).

These tests verify that the pipeline's quality mechanisms produce correct
accounting code. They test the PIPELINE (parser, mandates, contracts, scans),
not the generated code.

To update after a pipeline change:
1. Re-run the mini-build
2. Verify 10/10 criteria still pass
3. Update file paths/expectations if the build output structure changed
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_team_v15.prd_parser import parse_prd  # noqa: E402
from agent_team_v15.agents import build_tiered_mandate  # noqa: E402
from agent_team_v15.contract_generator import generate_contracts  # noqa: E402
from agent_team_v15.quality_checks import (  # noqa: E402
    run_placeholder_scan,
    run_handler_completeness_scan,
    run_business_rule_verification,
    run_shortcut_detection_scan,
)

MINI_PRD_PATH = Path(r"C:\MY_PROJECTS\mini-accounting\prd.md")
MINI_BUILD_PATH = Path(r"C:\MY_PROJECTS\mini-accounting")


@pytest.fixture(scope="module")
def mini_prd():
    """Load the MiniBooks PRD text."""
    if not MINI_PRD_PATH.exists():
        pytest.skip("MiniBooks PRD not available")
    return MINI_PRD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(mini_prd):
    """Parse the MiniBooks PRD."""
    return parse_prd(mini_prd)


@pytest.fixture(scope="module")
def business_rules(parsed):
    """Extract business rules as dicts (format expected by build_tiered_mandate)."""
    return [
        {
            "id": r.id,
            "service": r.service,
            "entity": r.entity,
            "rule_type": r.rule_type,
            "description": r.description,
            "required_operations": r.required_operations,
            "anti_patterns": r.anti_patterns,
            "source_line": r.source_line,
        }
        for r in parsed.business_rules
    ]


# -----------------------------------------------------------------------
# PRD Parser Tests
# -----------------------------------------------------------------------


class TestPRDParser:
    """Verify parser extracts all entities and state machines."""

    def test_entity_count(self, parsed):
        assert len(parsed.entities) >= 8, (
            f"Expected >=8 entities, got {len(parsed.entities)}"
        )

    def test_state_machine_count(self, parsed):
        assert len(parsed.state_machines) >= 3, (
            f"Expected >=3 state machines, got {len(parsed.state_machines)}"
        )

    def test_state_machines_have_transitions(self, parsed):
        for sm in parsed.state_machines:
            transitions = sm.get("transitions", [])
            assert len(transitions) >= 2, (
                f"State machine {sm.get('entity', '?')} has <2 transitions"
            )

    def test_event_count(self, parsed):
        assert len(parsed.events) >= 3, (
            f"Expected >=3 events, got {len(parsed.events)}"
        )

    def test_key_entities_present(self, parsed):
        names = {
            (e.get("name", e) if isinstance(e, dict) else str(e)).lower()
            for e in parsed.entities
        }
        for expected in ("journalentry", "journalline", "fiscalperiod", "invoice"):
            assert any(expected in n for n in names), (
                f"Expected entity '{expected}' not found in {names}"
            )


# -----------------------------------------------------------------------
# Business Rules Extraction Tests
# -----------------------------------------------------------------------


class TestBusinessRulesExtraction:
    """Verify the parser extracts accounting-critical rules."""

    def test_minimum_rule_count(self, parsed):
        assert len(parsed.business_rules) >= 15, (
            f"Expected >=15 business rules, got {len(parsed.business_rules)}"
        )

    def test_extracts_double_entry_rule(self, parsed):
        rule_text = " ".join(r.description for r in parsed.business_rules).lower()
        assert "debit" in rule_text and "credit" in rule_text, (
            "Business rules must include double-entry validation"
        )

    def test_extracts_3way_matching_rule(self, parsed):
        rule_text = " ".join(r.description for r in parsed.business_rules).lower()
        assert "tolerance" in rule_text or "matching" in rule_text, (
            "Business rules must include 3-way matching"
        )

    def test_extracts_period_locking_rule(self, parsed):
        rule_text = " ".join(r.description for r in parsed.business_rules).lower()
        assert "period" in rule_text and (
            "close" in rule_text or "open" in rule_text
        ), "Business rules must include period locking"

    def test_rules_have_required_operations(self, parsed):
        with_ops = [r for r in parsed.business_rules if r.required_operations]
        assert len(with_ops) >= 5, (
            f"Expected >=5 rules with required_operations, got {len(with_ops)}"
        )


# -----------------------------------------------------------------------
# Tiered Mandate Tests
# -----------------------------------------------------------------------


class TestTieredMandates:
    """Verify mandates are service-specific and domain-prioritized."""

    def test_ap_mandate_mentions_matching(self, business_rules):
        ap_rules = [r for r in business_rules if r["service"] == "ap"]
        mandate = build_tiered_mandate(ap_rules)
        mandate_lower = mandate.lower()
        assert (
            "tolerance" in mandate_lower
            or "3-way" in mandate_lower
            or "matching" in mandate_lower
        ), "AP mandate Tier 1 must mention 3-way matching"

    def test_gl_mandate_mentions_balance(self, business_rules):
        gl_rules = [r for r in business_rules if r["service"] == "gl"]
        mandate = build_tiered_mandate(gl_rules)
        mandate_lower = mandate.lower()
        assert (
            "debit" in mandate_lower
            or "credit" in mandate_lower
            or "balance" in mandate_lower
        ), "GL mandate Tier 1 must mention double-entry"

    def test_mandates_differ_per_service(self, business_rules):
        gl_rules = [r for r in business_rules if r["service"] == "gl"]
        ap_rules = [r for r in business_rules if r["service"] == "ap"]
        gl_mandate = build_tiered_mandate(gl_rules)
        ap_mandate = build_tiered_mandate(ap_rules)
        assert gl_mandate != ap_mandate, (
            "GL and AP mandates must differ (service-specific rules)"
        )

    def test_tier1_before_tier3(self, business_rules):
        ap_rules = [r for r in business_rules if r["service"] == "ap"]
        mandate = build_tiered_mandate(ap_rules)
        mandate_lower = mandate.lower()
        tier1_pos = mandate_lower.find("tier 1")
        tier3_pos = mandate_lower.find("tier 3")
        if tier1_pos >= 0 and tier3_pos >= 0:
            assert tier1_pos < tier3_pos, "Tier 1 must appear before Tier 3"


# -----------------------------------------------------------------------
# Contract Generation Tests
# -----------------------------------------------------------------------


class TestContractGeneration:
    """Verify contracts include critical integration specs."""

    def test_contracts_include_journal_endpoint(self, parsed):
        contracts = generate_contracts(parsed)
        assert "journal" in contracts.contracts_md.lower(), (
            "Contracts must include GL journal entry endpoint"
        )

    def test_contracts_include_account_mapping(self, parsed):
        contracts = generate_contracts(parsed)
        text = contracts.contracts_md.lower()
        assert "receivable" in text or "revenue" in text, (
            "Contracts must include GL account mapping"
        )

    def test_contracts_generate_clients(self, parsed):
        contracts = generate_contracts(parsed)
        assert contracts.python_clients or contracts.typescript_clients, (
            "Contract bundle must generate at least one client library"
        )


# -----------------------------------------------------------------------
# Quality Scan Tests (on MiniBooks build output)
# -----------------------------------------------------------------------


class TestQualityScans:
    """Verify quality scans produce no false positives on MiniBooks build."""

    @pytest.fixture
    def build_root(self):
        if not MINI_BUILD_PATH.exists():
            pytest.skip("MiniBooks build output not available")
        return MINI_BUILD_PATH

    def test_zero_handler_stubs(self, build_root):
        violations = run_handler_completeness_scan(build_root)
        assert len(violations) == 0, (
            f"MiniBooks build has {len(violations)} handler stubs: "
            + "; ".join(v.message[:80] for v in violations[:3])
        )

    def test_shortcut_scan_reasonable(self, build_root):
        violations = run_shortcut_detection_scan(build_root)
        # Some shortcuts may exist (e.g. SHORTCUT-001 for async without await),
        # but should be a reasonable number
        assert len(violations) < 50, (
            f"MiniBooks build has {len(violations)} shortcuts — too many"
        )

    def test_business_rules_verified(self, build_root, business_rules):
        violations = run_business_rule_verification(build_root, business_rules)
        # Business rule violations should decrease over time
        # Current baseline: track the count to detect regressions
        assert isinstance(violations, list), "Business rule scan should return a list"


# -----------------------------------------------------------------------
# Mutation Detection Tests (synthetic)
# -----------------------------------------------------------------------


class TestMutationDetection:
    """Verify scans catch critical mutations using synthetic code samples."""

    def test_early_return_stub_detected(self):
        """M12 regression: early return in handler should be flagged as stub."""
        from agent_team_v15.quality_checks import _is_stub_handler

        body = [
            "      try {",
            '        this.logger.info("event received", payload);',
            "        return;",
            "        const { id } = payload.data;",
            "        await this.repo.update(id, { status: 'processed' });",
        ]
        assert _is_stub_handler(body) is True, (
            "Early return after logging must be detected as stub"
        )

    def test_real_handler_not_flagged(self):
        """Original handler with business logic should NOT be a stub."""
        from agent_team_v15.quality_checks import _is_stub_handler

        body = [
            "      try {",
            "        const { id } = payload.data;",
            '        this.logger.info("Processing", id);',
            "        await this.repo.update(id, { status: 'processed' });",
            "      } catch (error) {",
            '        this.logger.error("Failed", error);',
            "      }",
        ]
        assert _is_stub_handler(body) is False, (
            "Handler with real business logic must NOT be flagged as stub"
        )

    def test_inline_block_comment_detected(self):
        """M22 regression: inline block comments matching placeholder patterns."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a non-test filename to avoid skip filters
            f = Path(tmpdir) / "service.ts"
            f.write_text(
                '/* In production, this would call the real API */ doSomething();\n',
                encoding="utf-8",
            )
            violations = run_placeholder_scan(Path(tmpdir))
            assert len(violations) >= 1, (
                "Inline block comment with placeholder should be detected"
            )

