"""Tests for anti-pattern spot checker (Agent 19)."""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.quality_checks import (
    Violation,
    run_frontend_hallucination_scan,
    run_spot_checks,
    _check_ts_any,
    _check_sql_concat,
    _check_console_log,
    _check_n_plus_1,
    _check_generic_fonts,
    _check_default_tailwind_colors,
    _check_transaction_safety,
    _check_param_validation,
    _check_validation_data_flow,
    _check_gitignore,
    _check_duplicate_functions,
    _check_i18n_hardcoded_strings,
    run_placeholder_scan,
    run_state_machine_completeness_scan,
    run_business_rule_verification,
)


class TestCheckTsAny:
    def test_detects_any_type(self):
        content = "const x: any = 5;"
        violations = _check_ts_any(content, "test.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "FRONT-007"

    def test_ignores_non_ts(self):
        content = "const x: any = 5;"
        violations = _check_ts_any(content, "test.py", ".py")
        assert len(violations) == 0

    def test_no_false_positive_on_many(self):
        content = "const many = 5;"
        violations = _check_ts_any(content, "test.ts", ".ts")
        assert len(violations) == 0


class TestCheckSqlConcat:
    def test_detects_concat_suffix(self):
        content = 'const q = "SELECT * FROM users WHERE id=" + userId;'
        violations = _check_sql_concat(content, "test.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "BACK-001"

    def test_clean_parameterized_query(self):
        content = 'db.query("SELECT * FROM users WHERE id=$1", [userId]);'
        violations = _check_sql_concat(content, "test.ts", ".ts")
        assert len(violations) == 0


class TestCheckConsoleLog:
    def test_detects_console_log(self):
        content = 'console.log("debug");'
        violations = _check_console_log(content, "src/app.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "FRONT-010"

    def test_allows_in_test_files(self):
        content = 'console.log("debug");'
        violations = _check_console_log(content, "src/app.test.ts", ".ts")
        assert len(violations) == 0


class TestCheckNPlus1:
    def test_detects_for_await(self):
        content = "for (const user of users) await db.find(user.id);"
        violations = _check_n_plus_1(content, "test.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "BACK-002"

    def test_no_false_positive_on_single_await(self):
        content = "const result = await db.findAll();"
        violations = _check_n_plus_1(content, "test.ts", ".ts")
        assert len(violations) == 0


class TestCheckGenericFonts:
    def test_detects_inter_font(self):
        content = "font-family: Inter, sans-serif;"
        violations = _check_generic_fonts(content, "style.css", ".css")
        assert len(violations) >= 1
        assert violations[0].check == "SLOP-003"

    def test_allows_custom_fonts(self):
        content = "font-family: 'Space Grotesk', sans-serif;"
        violations = _check_generic_fonts(content, "style.css", ".css")
        assert len(violations) == 0


class TestCheckDefaultTailwindColors:
    def test_detects_indigo_500(self):
        content = '<div className="bg-indigo-500">'
        violations = _check_default_tailwind_colors(content, "page.tsx", ".tsx")
        assert len(violations) >= 1
        assert violations[0].check == "SLOP-001"

    def test_allows_custom_colors(self):
        content = '<div className="bg-emerald-500">'
        violations = _check_default_tailwind_colors(content, "page.tsx", ".tsx")
        assert len(violations) == 0


class TestRunSpotChecks:
    def test_empty_project(self, tmp_path):
        # Provide .gitignore so the project-level check doesn't fire
        (tmp_path / ".gitignore").write_text("node_modules\ndist\n.env\n", encoding="utf-8")
        violations = run_spot_checks(tmp_path)
        assert violations == []

    def test_finds_violations(self, tmp_path):
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("const x: any = 5;\nconsole.log(x);\n", encoding="utf-8")
        violations = run_spot_checks(tmp_path)
        checks = {v.check for v in violations}
        assert "FRONT-007" in checks

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        ts_file = nm / "index.ts"
        ts_file.write_text("const x: any = 5;", encoding="utf-8")
        violations = run_spot_checks(tmp_path)
        assert all(v.file_path != "node_modules/pkg/index.ts" for v in violations)

    def test_cap_at_max_violations(self, tmp_path):
        # Create many files with violations (cap raised to 500 in A9)
        for i in range(600):
            f = tmp_path / f"file_{i}.ts"
            f.write_text("const x: any = 5;\nconst y: any = 6;\n", encoding="utf-8")
        violations = run_spot_checks(tmp_path)
        assert len(violations) <= 500

    def test_sorted_by_severity(self, tmp_path):
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            'const q = "SELECT * FROM users WHERE id=" + userId;\n'
            'const x: any = 5;\n'
            'console.log("hi");\n',
            encoding="utf-8",
        )
        violations = run_spot_checks(tmp_path)
        if len(violations) >= 2:
            severities = [v.severity for v in violations]
            severity_order = {"error": 0, "warning": 1, "info": 2}
            assert all(
                severity_order.get(severities[i], 99) <= severity_order.get(severities[i + 1], 99)
                for i in range(len(severities) - 1)
            )

    def test_includes_i18n_hardcoded_string_scan(self, tmp_path):
        page = tmp_path / "page.tsx"
        page.write_text(
            "export default function Page() {\n"
            "  return <button title=\"Dashboard\">Submit</button>;\n"
            "}\n",
            encoding="utf-8",
        )
        violations = run_spot_checks(tmp_path)
        checks = {v.check for v in violations}
        assert "I18N-HARDCODED-001" in checks


class TestRunFrontendHallucinationScan:
    def test_detects_invalid_locale_union(self, tmp_path: Path) -> None:
        page = tmp_path / "apps" / "web" / "src" / "app" / "page.tsx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "const locale = value as 'en' | 'ar' | 'id';\n",
            encoding="utf-8",
        )

        violations = run_frontend_hallucination_scan(
            tmp_path,
            allowed_locales=["en", "ar"],
        )

        assert [v.check for v in violations] == ["LOCALE-HALLUCINATE-001"]
        assert "declared project locales are ar, en" in violations[0].message

    def test_detects_invalid_google_font_subset(self, tmp_path: Path) -> None:
        page = tmp_path / "apps" / "web" / "src" / "app" / "page.tsx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "import { Inter } from 'next/font/google';\n"
            "const inter = Inter({ subsets: ['latin', 'arabic'] });\n",
            encoding="utf-8",
        )

        violations = run_frontend_hallucination_scan(tmp_path, allowed_locales=["en"])

        assert [v.check for v in violations] == ["FONT-SUBSET-001"]
        assert "Inter does not support Google Font subset 'arabic'" in violations[0].message


class TestCheckI18nHardcodedStrings:
    def test_detects_jsx_text_and_props(self):
        content = "export function Page() { return <button label=\"Submit\">Dashboard</button>; }\n"
        violations = _check_i18n_hardcoded_strings(content, "src/page.tsx", ".tsx")
        assert len(violations) >= 2
        assert all(v.check == "I18N-HARDCODED-001" for v in violations)

    def test_ignores_translated_and_non_user_facing_props(self):
        content = (
            "import logo from './logo.svg';\n"
            "export function Page() {\n"
            "  return <Button className=\"btn-primary\" label={t('orders.submit')}>{t('orders.title')}</Button>;\n"
            "}\n"
        )
        violations = _check_i18n_hardcoded_strings(content, "src/page.tsx", ".tsx")
        assert violations == []


# ===================================================================
# New Spot Checks (Quality Optimization)
# ===================================================================

class TestCheckDuplicateFunctions:
    def test_duplicate_functions_detected(self, tmp_path):
        f1 = tmp_path / "routes.ts"
        f1.write_text("function formatDate(d: Date) { return d.toISOString(); }\n", encoding="utf-8")
        f2 = tmp_path / "utils.ts"
        f2.write_text("function formatDate(d: Date) { return d.toLocaleDateString(); }\n", encoding="utf-8")
        source_files = [f1, f2]
        violations = _check_duplicate_functions(tmp_path, source_files)
        assert len(violations) >= 1
        assert any("FRONT-016" in v.check for v in violations)

    def test_no_duplicate_false_positive(self, tmp_path):
        f1 = tmp_path / "routes.ts"
        f1.write_text("function formatDate(d: Date) { return d.toISOString(); }\n", encoding="utf-8")
        f2 = tmp_path / "utils.ts"
        f2.write_text("function parseInput(s: string) { return s.trim(); }\n", encoding="utf-8")
        source_files = [f1, f2]
        violations = _check_duplicate_functions(tmp_path, source_files)
        assert len(violations) == 0

    def test_const_non_function_not_flagged(self, tmp_path):
        """const config = {...} should NOT be detected as a function."""
        f1 = tmp_path / "a.ts"
        f1.write_text("const config = { port: 3000 };\n", encoding="utf-8")
        f2 = tmp_path / "b.ts"
        f2.write_text("const config = { port: 8080 };\n", encoding="utf-8")
        source_files = [f1, f2]
        violations = _check_duplicate_functions(tmp_path, source_files)
        assert len(violations) == 0

    def test_const_arrow_function_detected(self, tmp_path):
        """const formatDate = () => ... SHOULD be detected as a function."""
        f1 = tmp_path / "a.ts"
        f1.write_text("const formatDate = (d: Date) => d.toISOString();\n", encoding="utf-8")
        f2 = tmp_path / "b.ts"
        f2.write_text("const formatDate = (d: Date) => d.toLocaleDateString();\n", encoding="utf-8")
        source_files = [f1, f2]
        violations = _check_duplicate_functions(tmp_path, source_files)
        assert len(violations) >= 1


class TestCheckTransactionSafety:
    def test_transaction_safety_flagged(self):
        content = (
            "async function replaceItems(userId: string) {\n"
            "  await prisma.item.deleteMany({ where: { userId } });\n"
            "  await prisma.item.createMany({ data: newItems });\n"
            "}\n"
        )
        violations = _check_transaction_safety(content, "items.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "BACK-016"

    def test_transaction_safety_passes(self):
        content = (
            "async function replaceItems(userId: string) {\n"
            "  await prisma.$transaction(async (tx) => {\n"
            "    await tx.item.deleteMany({ where: { userId } });\n"
            "    await tx.item.createMany({ data: newItems });\n"
            "  });\n"
            "}\n"
        )
        violations = _check_transaction_safety(content, "items.ts", ".ts")
        assert len(violations) == 0


class TestCheckParamValidation:
    def test_param_validation_flagged(self):
        content = (
            "app.get('/users/:id', (req, res) => {\n"
            "  const id = Number(req.params.id);\n"
            "  const user = db.getUser(id);\n"
            "  res.json(user);\n"
            "});\n"
        )
        violations = _check_param_validation(content, "routes.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "BACK-018"

    def test_param_validation_passes(self):
        content = (
            "app.get('/users/:id', (req, res) => {\n"
            "  const id = Number(req.params.id);\n"
            "  if (isNaN(id)) return res.status(400).json({ error: 'Invalid ID' });\n"
            "  const user = db.getUser(id);\n"
            "  res.json(user);\n"
            "});\n"
        )
        violations = _check_param_validation(content, "routes.ts", ".ts")
        assert len(violations) == 0


class TestCheckValidationDataFlow:
    def test_validation_flow_flagged(self):
        content = (
            "app.post('/users', (req, res) => {\n"
            "  schema.parse(req.body);\n"
            "  const user = createUser(req.body);\n"
            "  res.json(user);\n"
            "});\n"
        )
        violations = _check_validation_data_flow(content, "routes.ts", ".ts")
        assert len(violations) >= 1
        assert violations[0].check == "BACK-017"

    def test_validation_flow_passes(self):
        content = (
            "app.post('/users', (req, res) => {\n"
            "  const data = schema.parse(req.body);\n"
            "  const user = createUser(data);\n"
            "  res.json(user);\n"
            "});\n"
        )
        violations = _check_validation_data_flow(content, "routes.ts", ".ts")
        assert len(violations) == 0

    def test_validation_flow_return_not_flagged(self):
        """return schema.parse(req.body) should NOT be flagged — result is used."""
        content = (
            "function validate(req: Request) {\n"
            "  return schema.parse(req.body);\n"
            "}\n"
        )
        violations = _check_validation_data_flow(content, "middleware.ts", ".ts")
        assert len(violations) == 0


class TestCheckGitignore:
    def test_gitignore_missing(self, tmp_path):
        violations = _check_gitignore(tmp_path)
        assert len(violations) >= 1

    def test_gitignore_present(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("node_modules\ndist\n.env\n", encoding="utf-8")
        violations = _check_gitignore(tmp_path)
        assert len(violations) == 0


# ===================================================================
# V16 Phase 1.2: Handler completeness scan (STUB-001)
# ===================================================================

from agent_team_v15.quality_checks import (
    run_handler_completeness_scan,
    run_entity_coverage_scan,
    run_cross_service_scan,
    run_api_completeness_scan,
    is_fixable_violation,
    classify_violation,
    get_violation_signature,
    filter_fixable_violations,
    reset_fix_signatures,
    track_fix_attempt,
    get_persistent_violations,
    filter_non_persistent,
    FIXABLE_CODE,
    FIXABLE_LOGIC,
    UNFIXABLE_INFRA,
    UNFIXABLE_ARCH,
    _is_stub_handler,
    _extract_function_body_lines,
)


class TestIsStubHandler:
    """Unit tests for the _is_stub_handler heuristic."""

    def test_empty_body_is_stub(self):
        assert _is_stub_handler([]) is True

    def test_log_only_python_is_stub(self):
        body = [
            '    logger.info("Received event: %s", payload)',
        ]
        assert _is_stub_handler(body) is True

    def test_log_plus_pass_is_stub(self):
        body = [
            '    logger.info("Event received")',
            '    pass',
        ]
        assert _is_stub_handler(body) is True

    def test_log_plus_comment_is_stub(self):
        body = [
            '    # TODO: implement this handler',
            '    logger.info("Event received: %s", data)',
        ]
        assert _is_stub_handler(body) is True

    def test_payload_extraction_plus_log_is_stub(self):
        body = [
            '    payload = message.get("payload", {})',
            '    invoice_id = payload.get("invoice_id")',
            '    logger.info("Processing invoice: %s", invoice_id)',
        ]
        assert _is_stub_handler(body) is True

    def test_db_write_is_not_stub(self):
        body = [
            '    payload = message.get("payload", {})',
            '    logger.info("Processing event")',
            '    await db.execute(insert(AuditLog).values(entity_id=payload["id"]))',
        ]
        assert _is_stub_handler(body) is False

    def test_http_call_is_not_stub(self):
        body = [
            '    logger.info("Creating GL entry")',
            '    await self.gl_service.create_journal_entry(payload)',
        ]
        assert _is_stub_handler(body) is False

    def test_status_change_is_not_stub(self):
        body = [
            '    order.status = "approved"',
            '    await session.commit()',
        ]
        assert _is_stub_handler(body) is False

    def test_nestjs_log_only_is_stub(self):
        body = [
            '    this.logger.log(`Event received: ${payload.id}`);',
        ]
        assert _is_stub_handler(body) is True

    def test_nestjs_with_save_is_not_stub(self):
        body = [
            '    this.logger.log(`Processing event`);',
            '    const entity = await this.repository.save(newRecord);',
        ]
        assert _is_stub_handler(body) is False

    def test_publish_event_is_not_stub(self):
        body = [
            '    logger.info("Forwarding event")',
            '    await publish_event("order.approved", payload)',
        ]
        assert _is_stub_handler(body) is False

    def test_raise_exception_is_not_stub(self):
        body = [
            '    if not payload.get("id"):',
            '        raise ValueError("Missing entity ID")',
            '    await process(payload)',
        ]
        assert _is_stub_handler(body) is False


class TestExtractFunctionBodyLines:
    """Unit tests for Python/TS function body extraction."""

    def test_python_simple_function(self):
        content = (
            "async def handle_event(data):\n"
            "    logger.info('got it')\n"
            "    pass\n"
            "\n"
            "def other_func():\n"
            "    return 1\n"
        )
        body = _extract_function_body_lines(content, 0, is_python=True)
        assert len(body) >= 2
        assert any("logger" in line for line in body)

    def test_python_stops_at_dedent(self):
        content = (
            "async def handle_event(data):\n"
            "    logger.info('got it')\n"
            "\n"
            "class Foo:\n"
            "    pass\n"
        )
        body = _extract_function_body_lines(content, 0, is_python=True)
        assert not any("class Foo" in line for line in body)

    def test_typescript_brace_counting(self):
        content = (
            "async handleEvent(payload: any) {\n"
            "    this.logger.log('received');\n"
            "    console.log(payload);\n"
            "}\n"
            "\n"
            "otherMethod() {\n"
        )
        body = _extract_function_body_lines(content, 0, is_python=False)
        # Body should contain the log lines but NOT the signature line or otherMethod
        assert any("logger" in line or "console" in line for line in body)
        assert not any("otherMethod" in line for line in body)
        # Signature line (containing opening {) should be skipped
        assert not any("handleEvent" in line for line in body)


class TestRunHandlerCompletenessScan:
    """Integration tests for the full scan function."""

    def test_detects_python_stub_handler(self, tmp_path):
        handler_file = tmp_path / "event_handlers.py"
        handler_file.write_text(
            'import logging\n'
            'logger = logging.getLogger(__name__)\n'
            '\n'
            'async def handle_invoice_created(message: dict) -> None:\n'
            '    payload = message.get("payload", {})\n'
            '    logger.info("Invoice created: %s", payload.get("invoice_id"))\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) == 1
        assert violations[0].check == "STUB-001"
        assert "handle_invoice_created" in violations[0].message

    def test_detects_typescript_stub_handler_subscribe(self, tmp_path):
        handler_file = tmp_path / "event-handlers.service.ts"
        handler_file.write_text(
            'export class EventHandlerService {\n'
            '  onModuleInit() {\n'
            '    this.subscriber.subscribe(\'gl.period.closed\', async (envelope) => {\n'
            '      this.logger.log(`Period closed: ${envelope.payload.period_id}`);\n'
            '    });\n'
            '  }\n'
            '}\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) >= 1
        assert violations[0].check == "STUB-001"

    def test_detects_typescript_stub_handler_method(self, tmp_path):
        handler_file = tmp_path / "event-handlers.service.ts"
        handler_file.write_text(
            'export class EventHandlerService {\n'
            '  async handleInvoiceCreated(payload: any): Promise<void> {\n'
            '    this.logger.log(`Invoice created: ${payload.id}`);\n'
            '  }\n'
            '}\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) >= 1
        assert violations[0].check == "STUB-001"

    def test_ignores_real_handler(self, tmp_path):
        handler_file = tmp_path / "event_handlers.py"
        handler_file.write_text(
            'async def handle_invoice_created(message: dict) -> None:\n'
            '    payload = message.get("payload", {})\n'
            '    logger.info("Processing invoice")\n'
            '    await db.execute(insert(JournalEntry).values(\n'
            '        tenant_id=payload["tenant_id"],\n'
            '        amount=payload["total"],\n'
            '    ))\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) == 0

    def test_ignores_non_handler_files(self, tmp_path):
        service_file = tmp_path / "invoice_service.py"
        service_file.write_text(
            'async def handle_request(data):\n'
            '    logger.info("Processing request")\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) == 0  # Not a handler file (no "handler"/"event" in name)

    def test_empty_project_no_violations(self, tmp_path):
        violations = run_handler_completeness_scan(tmp_path)
        assert len(violations) == 0

    def test_respects_scope(self, tmp_path):
        from agent_team_v15.quality_checks import ScanScope
        handler = tmp_path / "event_handlers.py"
        handler.write_text(
            'async def handle_event(msg):\n'
            '    logger.info("stub")\n',
            encoding="utf-8",
        )
        # Scope with empty changed_files — should scan nothing
        scope = ScanScope(mode="changed_only", changed_files=[])
        violations = run_handler_completeness_scan(tmp_path, scope=scope)
        assert len(violations) == 0


# ===================================================================
# V16 Phase 1.5: Entity coverage scan (ENTITY-001..003)
# ===================================================================

class TestRunEntityCoverageScan:
    """Integration tests for entity coverage verification."""

    def test_no_entities_returns_empty(self, tmp_path):
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=None)
        assert len(violations) == 0

    def test_empty_entities_list_returns_empty(self, tmp_path):
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=[])
        assert len(violations) == 0

    def test_missing_model_detected(self, tmp_path):
        """Entity in PRD but no ORM model in codebase."""
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_001 = [v for v in violations if v.check == "ENTITY-001"]
        assert len(entity_001) == 1
        assert "Invoice" in entity_001[0].message

    def test_model_exists_no_entity_001(self, tmp_path):
        """Entity model exists — should not flag ENTITY-001."""
        model_file = tmp_path / "models.py"
        model_file.write_text(
            "from sqlalchemy.orm import DeclarativeBase\n"
            "class Base(DeclarativeBase): pass\n"
            "class Invoice(Base):\n"
            "    __tablename__ = 'invoices'\n",
            encoding="utf-8",
        )
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_001 = [v for v in violations if v.check == "ENTITY-001"]
        assert len(entity_001) == 0

    def test_missing_routes_detected(self, tmp_path):
        """Entity model exists but no CRUD routes."""
        model_file = tmp_path / "models.py"
        model_file.write_text(
            "class Invoice(Base):\n    pass\n",
            encoding="utf-8",
        )
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_002 = [v for v in violations if v.check == "ENTITY-002"]
        assert len(entity_002) == 1

    def test_routes_exist_no_entity_002(self, tmp_path):
        """Entity routes exist — should not flag ENTITY-002."""
        route_file = tmp_path / "routes.py"
        route_file.write_text(
            '@router.get("/api/invoices")\n'
            "async def list_invoices(): pass\n"
            '@router.post("/api/invoices")\n'
            "async def create_invoice(): pass\n",
            encoding="utf-8",
        )
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_002 = [v for v in violations if v.check == "ENTITY-002"]
        assert len(entity_002) == 0

    def test_missing_tests_detected(self, tmp_path):
        """Entity has no test files."""
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_003 = [v for v in violations if v.check == "ENTITY-003"]
        assert len(entity_003) == 1

    def test_tests_exist_no_entity_003(self, tmp_path):
        """Test file exists for entity."""
        test_file = tmp_path / "test_invoice.py"
        test_file.write_text("def test_invoice(): assert True\n", encoding="utf-8")
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_003 = [v for v in violations if v.check == "ENTITY-003"]
        assert len(entity_003) == 0

    def test_multiple_entities(self, tmp_path):
        """Multiple entities checked — some missing, some present."""
        model_file = tmp_path / "models.py"
        model_file.write_text(
            "class Invoice(Base): pass\n"
            "class Customer(Base): pass\n",
            encoding="utf-8",
        )
        entities = [
            {"name": "Invoice"},
            {"name": "Customer"},
            {"name": "Payment"},  # missing
        ]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_001 = [v for v in violations if v.check == "ENTITY-001"]
        # Only Payment should be missing
        assert len(entity_001) == 1
        assert "Payment" in entity_001[0].message

    def test_typescript_entity_detected(self, tmp_path):
        """TypeORM @Entity() class detected."""
        entity_file = tmp_path / "invoice.entity.ts"
        entity_file.write_text(
            "@Entity()\nexport class Invoice {\n  @PrimaryColumn()\n  id: string;\n}\n",
            encoding="utf-8",
        )
        entities = [{"name": "Invoice"}]
        violations = run_entity_coverage_scan(tmp_path, parsed_entities=entities)
        entity_001 = [v for v in violations if v.check == "ENTITY-001"]
        assert len(entity_001) == 0


# ===================================================================
# V16 Phase 1.6: Fix loop intelligence
# ===================================================================

class TestIsFixableViolation:
    """Unit tests for unfixable violation classification."""

    def test_normal_violation_is_fixable(self):
        v = Violation(check="FRONT-007", message="any type found", file_path="x.ts", line=1, severity="warning")
        assert is_fixable_violation(v) is True

    def test_deploy_prefix_is_unfixable(self):
        v = Violation(check="DEPLOY-001", message="port mismatch", file_path="docker-compose.yml", line=5, severity="error")
        assert is_fixable_violation(v) is False

    def test_asset_prefix_is_unfixable(self):
        v = Violation(check="ASSET-002", message="broken ref", file_path="index.html", line=10, severity="warning")
        assert is_fixable_violation(v) is False

    def test_docker_message_is_unfixable(self):
        v = Violation(check="BACK-001", message="Dockerfile not found in service", file_path="x.py", line=1, severity="error")
        assert is_fixable_violation(v) is False

    def test_npm_build_message_is_unfixable(self):
        v = Violation(check="BACK-002", message="npm run build failed with exit code 1", file_path="x.ts", line=1, severity="error")
        assert is_fixable_violation(v) is False

    def test_stub_violation_is_fixable(self):
        v = Violation(check="STUB-001", message="handler is log-only stub", file_path="handler.py", line=5, severity="warning")
        assert is_fixable_violation(v) is True

    def test_mock_violation_is_fixable(self):
        v = Violation(check="MOCK-001", message="hardcoded data", file_path="service.ts", line=10, severity="warning")
        assert is_fixable_violation(v) is True


class TestGetViolationSignature:
    """Unit tests for violation signature generation."""

    def test_empty_list(self):
        sig = get_violation_signature([])
        assert sig == frozenset()

    def test_same_violations_same_signature(self):
        v1 = Violation(check="X", message="msg1", file_path="a.py", line=1, severity="warning")
        v2 = Violation(check="X", message="msg1", file_path="a.py", line=1, severity="warning")
        assert get_violation_signature([v1]) == get_violation_signature([v2])

    def test_different_violations_different_signature(self):
        v1 = Violation(check="X", message="msg1", file_path="a.py", line=1, severity="warning")
        v2 = Violation(check="Y", message="msg2", file_path="b.py", line=2, severity="error")
        assert get_violation_signature([v1]) != get_violation_signature([v2])

    def test_order_independent(self):
        v1 = Violation(check="X", message="a", file_path="a.py", line=1, severity="w")
        v2 = Violation(check="Y", message="b", file_path="b.py", line=2, severity="w")
        assert get_violation_signature([v1, v2]) == get_violation_signature([v2, v1])


class TestFilterFixableViolations:
    """Integration tests for the combined filter + repeat detection."""

    def setup_method(self):
        reset_fix_signatures()

    def test_all_fixable_returned(self):
        violations = [
            Violation(check="STUB-001", message="stub", file_path="h.py", line=1, severity="warning"),
            Violation(check="MOCK-001", message="mock", file_path="s.ts", line=2, severity="warning"),
        ]
        fixable, skip = filter_fixable_violations(violations, "test_scan")
        assert len(fixable) == 2
        assert skip is False

    def test_unfixable_filtered_out(self):
        violations = [
            Violation(check="STUB-001", message="stub", file_path="h.py", line=1, severity="warning"),
            Violation(check="DEPLOY-001", message="docker port", file_path="dc.yml", line=5, severity="error"),
        ]
        fixable, skip = filter_fixable_violations(violations, "test_scan2")
        assert len(fixable) == 1
        assert fixable[0].check == "STUB-001"
        assert skip is False

    def test_all_unfixable_signals_skip(self):
        violations = [
            Violation(check="DEPLOY-001", message="docker port", file_path="dc.yml", line=5, severity="error"),
            Violation(check="ASSET-001", message="broken ref", file_path="x.html", line=1, severity="warning"),
        ]
        fixable, skip = filter_fixable_violations(violations, "test_scan3")
        assert len(fixable) == 0
        assert skip is True

    def test_repeat_detection_second_pass(self):
        violations = [
            Violation(check="STUB-001", message="stub handler", file_path="h.py", line=1, severity="warning"),
        ]
        _, skip1 = filter_fixable_violations(violations, "test_scan_repeat")
        assert skip1 is False
        _, skip2 = filter_fixable_violations(violations, "test_scan_repeat")
        assert skip2 is True

    def test_different_scan_names_independent(self):
        violations = [
            Violation(check="STUB-001", message="stub", file_path="h.py", line=1, severity="warning"),
        ]
        _, skip1 = filter_fixable_violations(violations, "scan_a")
        assert skip1 is False
        _, skip2 = filter_fixable_violations(violations, "scan_b")
        assert skip2 is False

    def test_changed_violations_not_repeat(self):
        v1 = [Violation(check="STUB-001", message="stub A", file_path="a.py", line=1, severity="warning")]
        v2 = [Violation(check="STUB-001", message="stub B", file_path="b.py", line=2, severity="warning")]
        _, skip1 = filter_fixable_violations(v1, "test_scan_change")
        assert skip1 is False
        _, skip2 = filter_fixable_violations(v2, "test_scan_change")
        assert skip2 is False

    def test_reset_clears_signatures(self):
        violations = [
            Violation(check="STUB-001", message="stub", file_path="h.py", line=1, severity="warning"),
        ]
        filter_fixable_violations(violations, "test_reset")
        reset_fix_signatures()
        _, skip = filter_fixable_violations(violations, "test_reset")
        assert skip is False


# ===================================================================
# V16 Phase 3.1: Stub completion agent — service grouping logic
# ===================================================================

class TestStubCompletionServiceGrouping:
    """Test the service extraction logic used by _run_stub_completion."""

    def test_service_from_services_dir_path(self):
        """Extract service name from services/gl/app/event_handlers.py."""
        v = Violation(
            check="STUB-001",
            message="stub handler",
            file_path="services/gl/app/event_handlers.py",
            line=1,
            severity="warning",
        )
        parts = v.file_path.replace("\\", "/").split("/")
        svc = "unknown"
        for i, part in enumerate(parts):
            if part == "services" and i + 1 < len(parts):
                svc = parts[i + 1]
                break
        assert svc == "gl"

    def test_service_from_nested_handler_path(self):
        """Extract service from services/ar/src/event-handlers/event-handlers.service.ts."""
        v = Violation(
            check="STUB-001",
            message="stub",
            file_path="services/ar/src/event-handlers/event-handlers.service.ts",
            line=5,
            severity="warning",
        )
        parts = v.file_path.replace("\\", "/").split("/")
        svc = "unknown"
        for i, part in enumerate(parts):
            if part == "services" and i + 1 < len(parts):
                svc = parts[i + 1]
                break
        assert svc == "ar"

    def test_grouping_multiple_stubs(self):
        """Group stubs by service directory."""
        violations = [
            Violation(check="STUB-001", message="stub1", file_path="services/gl/app/event_handlers.py", line=1, severity="warning"),
            Violation(check="STUB-001", message="stub2", file_path="services/gl/app/event_handlers.py", line=10, severity="warning"),
            Violation(check="STUB-001", message="stub3", file_path="services/ar/src/event-handlers/handler.ts", line=5, severity="warning"),
        ]
        stubs_by_service: dict[str, list] = {}
        for v in violations:
            parts = v.file_path.replace("\\", "/").split("/")
            svc = "unknown"
            for i, part in enumerate(parts):
                if part == "services" and i + 1 < len(parts):
                    svc = parts[i + 1]
                    break
            stubs_by_service.setdefault(svc, []).append(v)
        assert len(stubs_by_service) == 2
        assert len(stubs_by_service["gl"]) == 2
        assert len(stubs_by_service["ar"]) == 1


# ===================================================================
# V16 Phase 3.2: Violation classification system
# ===================================================================

class TestClassifyViolation:
    """Unit tests for 4-category violation classification."""

    def test_code_fix(self):
        v = Violation(check="FRONT-007", message="any type found", file_path="x.ts", line=1, severity="warning")
        assert classify_violation(v) == FIXABLE_CODE

    def test_logic_fix_stub(self):
        v = Violation(check="STUB-001", message="log-only handler", file_path="h.py", line=1, severity="warning")
        assert classify_violation(v) == FIXABLE_LOGIC

    def test_logic_fix_mock(self):
        v = Violation(check="MOCK-001", message="hardcoded data", file_path="s.ts", line=1, severity="warning")
        assert classify_violation(v) == FIXABLE_LOGIC

    def test_infra_deploy(self):
        v = Violation(check="DEPLOY-001", message="port mismatch", file_path="dc.yml", line=5, severity="error")
        assert classify_violation(v) == UNFIXABLE_INFRA

    def test_infra_docker_message(self):
        v = Violation(check="BACK-001", message="Dockerfile not found", file_path="x.py", line=1, severity="error")
        assert classify_violation(v) == UNFIXABLE_INFRA

    def test_arch_missing_entity(self):
        v = Violation(check="ENTITY-001", message="missing ORM model", file_path="(project-wide)", line=0, severity="warning")
        assert classify_violation(v) == UNFIXABLE_ARCH

    def test_back_violation_is_code_fix(self):
        v = Violation(check="BACK-005", message="missing auth", file_path="routes.py", line=10, severity="warning")
        assert classify_violation(v) == FIXABLE_CODE

    def test_ui_violation_is_code_fix(self):
        v = Violation(check="UI-FAIL-003", message="color issue", file_path="app.css", line=5, severity="warning")
        assert classify_violation(v) == FIXABLE_CODE


# ===================================================================
# V16 Phase 3.3: Fix attempt tracking with stop conditions
# ===================================================================

class TestFixAttemptTracking:
    """Test per-violation fix attempt tracking and persistence detection."""

    def setup_method(self):
        reset_fix_signatures()

    def test_no_attempts_not_persistent(self):
        v = Violation(check="STUB-001", message="stub handler", file_path="h.py", line=1, severity="warning")
        assert get_persistent_violations([v]) == []

    def test_one_attempt_not_persistent(self):
        v = Violation(check="STUB-001", message="stub handler", file_path="h.py", line=1, severity="warning")
        track_fix_attempt([v])
        assert get_persistent_violations([v]) == []

    def test_two_attempts_becomes_persistent(self):
        v = Violation(check="STUB-001", message="stub handler", file_path="h.py", line=1, severity="warning")
        track_fix_attempt([v])
        track_fix_attempt([v])
        persistent = get_persistent_violations([v])
        assert len(persistent) == 1
        assert persistent[0].check == "STUB-001"

    def test_filter_non_persistent_excludes_persistent(self):
        v1 = Violation(check="STUB-001", message="stub A", file_path="a.py", line=1, severity="warning")
        v2 = Violation(check="MOCK-001", message="mock B", file_path="b.ts", line=5, severity="warning")
        track_fix_attempt([v1, v2])
        track_fix_attempt([v1])  # v1 has 2 attempts, v2 has 1
        non_persistent = filter_non_persistent([v1, v2])
        assert len(non_persistent) == 1
        assert non_persistent[0].check == "MOCK-001"

    def test_reset_clears_attempt_counts(self):
        v = Violation(check="STUB-001", message="stub", file_path="h.py", line=1, severity="warning")
        track_fix_attempt([v])
        track_fix_attempt([v])
        assert len(get_persistent_violations([v])) == 1
        reset_fix_signatures()  # Also clears attempt counts
        assert len(get_persistent_violations([v])) == 0

    def test_different_violations_tracked_independently(self):
        v1 = Violation(check="STUB-001", message="stub A", file_path="a.py", line=1, severity="warning")
        v2 = Violation(check="STUB-001", message="stub B", file_path="b.py", line=2, severity="warning")
        track_fix_attempt([v1])
        track_fix_attempt([v1])
        # v1 has 2 attempts, v2 has 0
        assert len(get_persistent_violations([v1])) == 1
        assert len(get_persistent_violations([v2])) == 0


# ===================================================================
# V16 Phase 3.4: Cross-service integration verification
# ===================================================================

class TestCrossServiceScan:
    """Integration tests for event pub/sub cross-reference."""

    def test_matched_pub_sub_no_violations(self, tmp_path):
        pub = tmp_path / "publisher.py"
        pub.write_text(
            'async def post_invoice(invoice):\n'
            '    await publish_event("ar.invoice.created", payload)\n',
            encoding="utf-8",
        )
        sub = tmp_path / "subscriber.py"
        sub.write_text(
            'async def start():\n'
            '    await subscribe("ar.invoice.created", handler)\n',
            encoding="utf-8",
        )
        violations = run_cross_service_scan(tmp_path)
        assert len(violations) == 0

    def test_publish_without_subscriber(self, tmp_path):
        pub = tmp_path / "publisher.py"
        pub.write_text(
            'await publish_event("ar.invoice.created", payload)\n',
            encoding="utf-8",
        )
        violations = run_cross_service_scan(tmp_path)
        xsvc001 = [v for v in violations if v.check == "XSVC-001"]
        assert len(xsvc001) == 1
        assert "ar.invoice.created" in xsvc001[0].message

    def test_subscribe_without_publisher(self, tmp_path):
        sub = tmp_path / "event_handlers.py"
        sub.write_text(
            'await subscribe("gl.period.closed", handler)\n',
            encoding="utf-8",
        )
        violations = run_cross_service_scan(tmp_path)
        xsvc002 = [v for v in violations if v.check == "XSVC-002"]
        assert len(xsvc002) == 1
        assert "gl.period.closed" in xsvc002[0].message

    def test_typescript_pub_sub(self, tmp_path):
        pub = tmp_path / "event-publisher.service.ts"
        pub.write_text(
            'this.eventBus.publish("order.completed", data);\n',
            encoding="utf-8",
        )
        sub = tmp_path / "event-handler.service.ts"
        sub.write_text(
            'this.subscriber.subscribe("order.completed", async (msg) => {});\n',
            encoding="utf-8",
        )
        violations = run_cross_service_scan(tmp_path)
        assert len(violations) == 0

    def test_empty_project(self, tmp_path):
        violations = run_cross_service_scan(tmp_path)
        assert len(violations) == 0


# ===================================================================
# V16 Phase 3.6: API completeness scan
# ===================================================================

class TestRunApiCompletenessScan:
    def test_model_with_no_routes(self, tmp_path):
        model = tmp_path / "models.py"
        model.write_text(
            "class Invoice(Base):\n    __tablename__ = 'invoices'\n",
            encoding="utf-8",
        )
        violations = run_api_completeness_scan(tmp_path)
        api001 = [v for v in violations if v.check == "API-001"]
        assert len(api001) == 1
        assert "invoice" in api001[0].message.lower()

    def test_model_with_crud_routes(self, tmp_path):
        model = tmp_path / "models.py"
        model.write_text("class Invoice(Base): pass\n", encoding="utf-8")
        routes = tmp_path / "routes.py"
        routes.write_text(
            '@router.get("/invoices")\n'
            "async def list_invoices(page: int = 1, limit: int = 20): pass\n"
            '@router.post("/invoices")\n'
            "async def create_invoice(): pass\n"
            '@router.get("/invoices/{id}")\n'
            "async def get_invoice(): pass\n",
            encoding="utf-8",
        )
        violations = run_api_completeness_scan(tmp_path)
        api001 = [v for v in violations if v.check == "API-001"]
        assert len(api001) == 0

    def test_empty_project(self, tmp_path):
        violations = run_api_completeness_scan(tmp_path)
        assert len(violations) == 0

    def test_typescript_entity_with_routes(self, tmp_path):
        entity = tmp_path / "invoice.entity.ts"
        entity.write_text(
            "@Entity()\nexport class Invoice { }\n",
            encoding="utf-8",
        )
        ctrl = tmp_path / "invoice.controller.ts"
        ctrl.write_text(
            "@Get('invoices')\nfindAll() {}\n"
            "@Post('invoices')\ncreate() {}\n"
            "@Get('invoices/:id')\nfindOne() {}\n",
            encoding="utf-8",
        )
        violations = run_api_completeness_scan(tmp_path)
        api001 = [v for v in violations if v.check == "API-001"]
        assert len(api001) == 0


# ===================================================================
# V16 Quality Fix Phase 1: Placeholder comment scanner (PLACEHOLDER-001)
# ===================================================================


class TestRunPlaceholderScan:
    """Tests for detecting placeholder comments that indicate stub implementations."""

    def test_detects_in_production_comment_ts(self, tmp_path):
        svc = tmp_path / "purchase-invoice.service.ts"
        svc.write_text(
            "async match(dto: any) {\n"
            "  const tolerancePercent = dto.tolerancePercent ?? 1;\n"
            "  // In production, amounts would be compared\n"
            "  invoice.matchStatus = 'full_match';\n"
            "}\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        assert len(ph) >= 1
        assert "production" in ph[0].message.lower()

    def test_detects_would_be_compared_pattern(self, tmp_path):
        svc = tmp_path / "matching.service.ts"
        svc.write_text(
            "function validate(invoice: Invoice) {\n"
            "  // amounts would be compared against PO data\n"
            "  return true;\n"
            "}\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        assert len(ph) >= 1

    def test_detects_todo_implement_python(self, tmp_path):
        svc = tmp_path / "service.py"
        svc.write_text(
            "def calculate_depreciation(asset):\n"
            "    # TODO: implement actual calculation\n"
            "    return 0\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        assert len(ph) >= 1

    def test_detects_stub_implementation(self, tmp_path):
        svc = tmp_path / "handler.ts"
        svc.write_text(
            "async handleEvent(payload: any) {\n"
            "  // stub implementation\n"
            "  console.log(payload);\n"
            "}\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        assert len(ph) >= 1

    def test_detects_not_yet_implemented(self, tmp_path):
        svc = tmp_path / "revaluation.py"
        svc.write_text(
            "def revalue_fx(positions):\n"
            "    # not yet implemented\n"
            "    pass\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        assert len(ph) >= 1

    def test_ignores_readme_files(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text(
            "# Service\n"
            "In production, this service runs behind a load balancer.\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        assert len(violations) == 0

    def test_ignores_test_files(self, tmp_path):
        test_file = tmp_path / "test_service.py"
        test_file.write_text(
            "def test_placeholder():\n"
            "    # TODO: implement real test\n"
            "    pass\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        assert len(violations) == 0

    def test_ignores_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "some-lib"
        nm.mkdir(parents=True)
        lib = nm / "index.ts"
        lib.write_text("// In production, this would use native module\n", encoding="utf-8")
        violations = run_placeholder_scan(tmp_path)
        assert len(violations) == 0

    def test_no_false_positive_on_production_config(self, tmp_path):
        svc = tmp_path / "config.ts"
        svc.write_text(
            "export const config = {\n"
            "  // production uses Redis, dev uses in-memory\n"
            "  cacheDriver: process.env.NODE_ENV === 'production' ? 'redis' : 'memory',\n"
            "};\n",
            encoding="utf-8",
        )
        violations = run_placeholder_scan(tmp_path)
        ph = [v for v in violations if v.check == "PLACEHOLDER-001"]
        # "production uses Redis" doesn't match "In production, X would be Y"
        assert len(ph) == 0

    def test_empty_project(self, tmp_path):
        violations = run_placeholder_scan(tmp_path)
        assert len(violations) == 0

    def test_severity_is_error(self, tmp_path):
        svc = tmp_path / "service.ts"
        svc.write_text("// In production, amounts would be compared\n", encoding="utf-8")
        violations = run_placeholder_scan(tmp_path)
        assert len(violations) >= 1
        assert violations[0].severity == "error"


# ===================================================================
# V16 Quality Fix Phase 1: Handler filename filter fix
# ===================================================================


class TestHandlerFilenameFilterFix:
    """Tests that handler scan now checks main.py and app.py files too."""

    def test_detects_stub_in_main_py(self, tmp_path):
        main = tmp_path / "main.py"
        main.write_text(
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '\n'
            'async def handle_period_closed(data: dict) -> None:\n'
            '    logger.info("gl_period_closed_received", data=data)\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        stubs = [v for v in violations if v.check == "STUB-001"]
        assert len(stubs) >= 1
        assert "handle_period_closed" in stubs[0].message

    def test_detects_stub_in_app_py(self, tmp_path):
        app = tmp_path / "app.py"
        app.write_text(
            'async def handle_exchange_rate_updated(data: dict) -> None:\n'
            '    logger.info("rate updated", data=data)\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        stubs = [v for v in violations if v.check == "STUB-001"]
        assert len(stubs) >= 1

    def test_real_handler_in_main_py_passes(self, tmp_path):
        main = tmp_path / "main.py"
        main.write_text(
            'async def handle_period_closed(data: dict) -> None:\n'
            '    logger.info("Processing period close")\n'
            '    await db.execute(update(ReconciliationSession).where(\n'
            '        ReconciliationSession.period_id == data["period_id"]\n'
            '    ).values(status="frozen"))\n',
            encoding="utf-8",
        )
        violations = run_handler_completeness_scan(tmp_path)
        stubs = [v for v in violations if v.check == "STUB-001"]
        assert len(stubs) == 0


class TestRunStateMachineCompletenessScan:
    """Tests for run_state_machine_completeness_scan."""

    def test_no_state_machines_returns_empty(self, tmp_path):
        """parsed_state_machines=None returns []."""
        result = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=None)
        assert result == []

    def test_empty_list_returns_empty(self, tmp_path):
        """parsed_state_machines=[] returns []."""
        result = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=[])
        assert result == []

    def test_detects_missing_transition_python(self, tmp_path):
        """Python file has VALID_TRANSITIONS dict missing a transition from the PRD."""
        svc = tmp_path / "tax_return_service.py"
        svc.write_text(
            'VALID_TRANSITIONS = {\n'
            '    "preparing": ["draft"],\n'
            '    "draft": ["submitted"],\n'
            '    "submitted": ["accepted"],\n'
            '    "accepted": ["amended"],\n'
            '}\n',
            encoding="utf-8",
        )
        parsed = [
            {
                "entity": "TaxReturn",
                "transitions": [
                    {"from_state": "preparing", "to_state": "draft"},
                    {"from_state": "draft", "to_state": "submitted"},
                    {"from_state": "submitted", "to_state": "accepted"},
                    {"from_state": "accepted", "to_state": "amended"},
                    {"from_state": "submitted", "to_state": "rejected"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        sm_violations = [v for v in violations if v.check == "SM-001"]
        missing = [v for v in sm_violations if "missing" in v.message]
        assert len(missing) >= 1
        assert any("rejected" in v.message for v in missing)

    def test_detects_missing_transition_typescript(self, tmp_path):
        """TS file with transitions missing one from PRD."""
        svc = tmp_path / "payment-run.service.ts"
        svc.write_text(
            "const VALID_TRANSITIONS: Record<string, string[]> = {\n"
            "  created: ['approved'],\n"
            "  approved: ['processing'],\n"
            "  processing: ['completed', 'failed'],\n"
            "};\n",
            encoding="utf-8",
        )
        parsed = [
            {
                "entity": "PaymentRun",
                "transitions": [
                    {"from_state": "created", "to_state": "approved"},
                    {"from_state": "approved", "to_state": "processing"},
                    {"from_state": "processing", "to_state": "completed"},
                    {"from_state": "processing", "to_state": "failed"},
                    {"from_state": "failed", "to_state": "retrying"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        sm_violations = [v for v in violations if v.check == "SM-001"]
        missing = [v for v in sm_violations if "missing" in v.message]
        assert len(missing) >= 1
        assert any("retrying" in v.message for v in missing)

    def test_all_transitions_present_no_violations(self, tmp_path):
        """Code has all PRD transitions — no missing-transition violations."""
        svc = tmp_path / "invoice_service.py"
        svc.write_text(
            'VALID_TRANSITIONS = {\n'
            '    "draft": ["submitted", "void"],\n'
            '    "submitted": ["approved", "rejected"],\n'
            '    "approved": ["paid"],\n'
            '}\n',
            encoding="utf-8",
        )
        parsed = [
            {
                "entity": "Invoice",
                "transitions": [
                    {"from_state": "draft", "to_state": "submitted"},
                    {"from_state": "draft", "to_state": "void"},
                    {"from_state": "submitted", "to_state": "approved"},
                    {"from_state": "submitted", "to_state": "rejected"},
                    {"from_state": "approved", "to_state": "paid"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        missing = [v for v in violations if "missing" in v.message]
        assert len(missing) == 0

    def test_extra_transitions_are_info_only(self, tmp_path):
        """Code has transitions not in PRD — those are info level only."""
        svc = tmp_path / "order_service.py"
        svc.write_text(
            'VALID_TRANSITIONS = {\n'
            '    "draft": ["submitted"],\n'
            '    "submitted": ["approved", "cancelled"],\n'
            '}\n',
            encoding="utf-8",
        )
        parsed = [
            {
                "entity": "Order",
                "transitions": [
                    {"from_state": "draft", "to_state": "submitted"},
                    {"from_state": "submitted", "to_state": "approved"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        extra = [v for v in violations if "not defined in PRD" in v.message]
        # Extra transitions (cancelled) should be info only
        for v in extra:
            assert v.severity == "info"

    def test_missing_reverse_transition_is_warning(self, tmp_path):
        """Missing a transition where to_state is a backward state like draft/created."""
        svc = tmp_path / "purchase_order_service.py"
        svc.write_text(
            'VALID_TRANSITIONS = {\n'
            '    "submitted": ["approved"],\n'
            '    "approved": ["fulfilled"],\n'
            '}\n',
            encoding="utf-8",
        )
        parsed = [
            {
                "entity": "PurchaseOrder",
                "transitions": [
                    {"from_state": "submitted", "to_state": "approved"},
                    {"from_state": "approved", "to_state": "fulfilled"},
                    {"from_state": "approved", "to_state": "draft"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        missing = [v for v in violations if "missing" in v.message]
        assert len(missing) >= 1
        draft_missing = [v for v in missing if "draft" in v.message]
        assert len(draft_missing) >= 1
        assert draft_missing[0].severity == "warning"

    def test_empty_project(self, tmp_path):
        """No source files but parsed_state_machines provided — violations for missing everything."""
        parsed = [
            {
                "entity": "Shipment",
                "transitions": [
                    {"from_state": "created", "to_state": "dispatched"},
                    {"from_state": "dispatched", "to_state": "delivered"},
                ],
            }
        ]
        violations = run_state_machine_completeness_scan(tmp_path, parsed_state_machines=parsed)
        sm_violations = [v for v in violations if v.check == "SM-001"]
        # Should report all transitions as missing (no code found)
        assert len(sm_violations) >= 2
        assert all("no transition map found" in v.message for v in sm_violations)


class TestRunBusinessRuleVerification:
    """Tests for run_business_rule_verification."""

    def test_none_rules_returns_empty(self, tmp_path):
        """Passing None for business_rules returns an empty list."""
        result = run_business_rule_verification(tmp_path, business_rules=None)
        assert result == []

    def test_empty_rules_returns_empty(self, tmp_path):
        """Passing an empty list returns an empty list."""
        result = run_business_rule_verification(tmp_path, business_rules=[])
        assert result == []

    def test_detects_missing_implementation(self, tmp_path):
        """No file matches entity 'PurchaseInvoice' -> CRITICAL violation."""
        # Create an unrelated file so the project is not empty
        unrelated = tmp_path / "user.service.ts"
        unrelated.write_text(
            "export class UserService {\n"
            "  getUser() { return {}; }\n"
            "}\n",
            encoding="utf-8",
        )
        rules = [
            {
                "id": "BR-AP-001",
                "entity": "PurchaseInvoice",
                "description": "3-way matching with tolerance comparison",
                "rule_type": "validation",
                "required_operations": ["multiplication", "comparison"],
                "anti_patterns": [],
            }
        ]
        violations = run_business_rule_verification(tmp_path, business_rules=rules)
        assert len(violations) >= 1
        assert violations[0].check == "RULE-001"
        assert violations[0].severity == "critical"
        assert "No implementation found" in violations[0].message
        assert "BR-AP-001" in violations[0].message

    def test_detects_missing_required_operations(self, tmp_path):
        """Function exists but lacks multiplication/comparison -> WARNING."""
        svc = tmp_path / "purchase-invoice.service.ts"
        svc.write_text(
            "export class PurchaseInvoiceService {\n"
            "  async match(invoiceId: string, dto: any) {\n"
            "    const invoice = await this.repo.findOne(invoiceId);\n"
            "    if (!invoice.poNumber) {\n"
            "      invoice.matchStatus = 'no_po';\n"
            "    } else {\n"
            "      invoice.matchStatus = 'full_match';\n"
            "    }\n"
            "    return invoice;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        rules = [
            {
                "id": "BR-AP-001",
                "entity": "PurchaseInvoice",
                "description": "3-way matching with tolerance comparison",
                "rule_type": "validation",
                "required_operations": ["multiplication", "comparison"],
                "anti_patterns": [],
            }
        ]
        violations = run_business_rule_verification(tmp_path, business_rules=rules)
        warnings = [v for v in violations if v.severity == "warning"]
        assert len(warnings) >= 1
        assert warnings[0].check == "RULE-001"
        assert "missing required operations" in warnings[0].message
        assert "multiplication" in warnings[0].message

    def test_passes_when_operations_present(self, tmp_path):
        """Function has multiplication and comparison -> no violations."""
        svc = tmp_path / "purchase-invoice.service.ts"
        svc.write_text(
            "export class PurchaseInvoiceService {\n"
            "  async match(invoiceId: string, dto: any) {\n"
            "    const invoice = await this.repo.findOne(invoiceId);\n"
            "    const expected = po.qty * po.unitPrice;\n"
            "    const variance = Math.abs(expected - invoice.amount) / expected;\n"
            "    if (variance > dto.tolerance) {\n"
            "      throw new Error('Match failed');\n"
            "    }\n"
            "    invoice.matchStatus = 'full_match';\n"
            "    return invoice;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        rules = [
            {
                "id": "BR-AP-001",
                "entity": "PurchaseInvoice",
                "description": "3-way matching with tolerance comparison",
                "rule_type": "validation",
                "required_operations": ["multiplication", "comparison"],
                "anti_patterns": [],
            }
        ]
        violations = run_business_rule_verification(tmp_path, business_rules=rules)
        assert violations == []

    def test_detects_anti_pattern(self, tmp_path):
        """Function with simple field-existence check -> ERROR violation."""
        svc = tmp_path / "purchase-invoice.service.ts"
        svc.write_text(
            "export class PurchaseInvoiceService {\n"
            "  async match(invoiceId: string, dto: any) {\n"
            "    const invoice = await this.repo.findOne(invoiceId);\n"
            "    if (!invoice.poNumber)\n"
            "      throw new Error('missing PO');\n"
            "    return invoice;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        rules = [
            {
                "id": "BR-AP-001",
                "entity": "PurchaseInvoice",
                "description": "3-way matching with tolerance comparison",
                "rule_type": "validation",
                "required_operations": [],
                "anti_patterns": ["Check only for string field existence"],
            }
        ]
        violations = run_business_rule_verification(tmp_path, business_rules=rules)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) >= 1
        assert errors[0].check == "RULE-001"
        assert "anti-pattern" in errors[0].message

    def test_integration_rule_checks_http_call(self, tmp_path):
        """Integration rule with http_call checks for fetch/axios."""
        svc = tmp_path / "purchase-invoice.service.ts"
        svc.write_text(
            "export class PurchaseInvoiceService {\n"
            "  async syncWithErp(invoiceId: string) {\n"
            "    const invoice = await this.repo.findOne(invoiceId);\n"
            "    const result = await fetch('/api/erp/sync', {\n"
            "      method: 'POST',\n"
            "      body: JSON.stringify(invoice),\n"
            "    });\n"
            "    return result.json();\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        rules = [
            {
                "id": "BR-AP-010",
                "entity": "PurchaseInvoice",
                "description": "Sync invoice data with ERP system",
                "rule_type": "integration",
                "required_operations": ["http_call"],
                "anti_patterns": [],
            }
        ]
        violations = run_business_rule_verification(tmp_path, business_rules=rules)
        # fetch( is present, so http_call is satisfied — no violations
        assert violations == []
