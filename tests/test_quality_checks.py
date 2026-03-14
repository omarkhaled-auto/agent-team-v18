"""Tests for anti-pattern spot checker (Agent 19)."""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.quality_checks import (
    Violation,
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

    def test_cap_at_100(self, tmp_path):
        # Create many files with violations
        for i in range(120):
            f = tmp_path / f"file_{i}.ts"
            f.write_text("const x: any = 5;\nconst y: any = 6;\n", encoding="utf-8")
        violations = run_spot_checks(tmp_path)
        assert len(violations) <= 100

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
