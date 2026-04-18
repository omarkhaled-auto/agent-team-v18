"""Tests for D-17 truth-score calibration — _score_error_handling and _score_test_presence."""
from pathlib import Path

from agent_team_v15.quality_checks import TruthScorer


# ---------------------------------------------------------------------------
# _score_error_handling
# ---------------------------------------------------------------------------

def test_error_handling_detects_global_exception_filter(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    # Put AllExceptionsFilter in a service-named file so it doesn't
    # create a separate "general" file that dilutes the blended score.
    (src / "users.service.ts").write_text(
        "import { ExceptionFilter } from '@nestjs/common';\n"
        "export class AllExceptionsFilter implements ExceptionFilter {\n"
        "  catch(exception: any) { /* handle */ }\n"
        "}\n"
        "export class UsersService {\n"
        "  async findAll() { return []; }\n"
        "  async findOne(id: string) { return null; }\n"
        "}\n"
    )
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    # With global filter detected, service_score is floored to 0.7.
    # No general files => pure service score path => >= 0.7
    assert result.dimensions["error_handling"] >= 0.7


def test_error_handling_detects_use_filters(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    # The @UseFilters pattern triggers the global filter detection
    (src / "orders.controller.ts").write_text(
        "import { Controller } from '@nestjs/common';\n"
        "@UseFilters(new HttpExceptionFilter())\n"
        "@Controller('orders')\n"
        "export class OrdersController {\n"
        "  async create(dto: any) { return dto; }\n"
        "  async findById(id: string) { return null; }\n"
        "}\n"
    )
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    # With global filter detected and only service/controller files,
    # service_score is floored to 0.7
    assert result.dimensions["error_handling"] >= 0.7


def test_error_handling_no_filter_uses_per_method(tmp_path):
    """Without a global filter, the scorer falls back to per-method try/catch counting."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "items.service.ts").write_text(
        "export class ItemsService {\n"
        "  async findAll() {\n"
        "    try {\n"
        "      return await this.repo.find();\n"
        "    } catch (err) {\n"
        "      throw err;\n"
        "    }\n"
        "  }\n"
        "  async findOne(id: string) {\n"
        "    return await this.repo.findOne(id);\n"
        "  }\n"
        "}\n"
    )
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    # One of two methods has try/catch => score ~0.5, which is < 0.7
    assert result.dimensions["error_handling"] < 0.7


def test_error_handling_empty_project(tmp_path):
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    assert result.dimensions["error_handling"] == 0.0


# ---------------------------------------------------------------------------
# _score_test_presence
# ---------------------------------------------------------------------------

def test_test_presence_placeholder_scaffold_floor(tmp_path):
    """Small source files with no tests get floored at 0.5."""
    src = tmp_path / "src"
    src.mkdir()
    # Create small scaffold-like source files (< 2000 chars each)
    for name in ("users.service.ts", "orders.service.ts", "app.module.ts"):
        (src / name).write_text(
            f"export class {name.split('.')[0].title()}Service {{\n"
            "  // scaffold placeholder\n"
            "}\n"
        )
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    assert result.dimensions["test_presence"] == 0.5


def test_test_presence_real_tests_scored_normally(tmp_path):
    """Source files with matching test files get scored above the floor."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "users.service.ts").write_text(
        "export class UsersService {\n"
        "  async findAll() { return []; }\n"
        "}\n"
    )
    (src / "users.service.spec.ts").write_text(
        "describe('UsersService', () => {\n"
        "  it('should find all', () => { expect(true).toBe(true); });\n"
        "});\n"
    )
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    assert result.dimensions["test_presence"] > 0.5


def test_test_presence_large_files_no_floor(tmp_path):
    """Large source files without tests should score below the floor (no special treatment)."""
    src = tmp_path / "src"
    src.mkdir()
    # Create large source files (> 2000 chars) with no tests
    large_content = "export class BigService {\n" + ("  async method() { return 'x'; }\n" * 100) + "}\n"
    (src / "big.service.ts").write_text(large_content)
    (src / "another.service.ts").write_text(large_content)
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    assert result.dimensions["test_presence"] < 0.5


def test_test_presence_no_source_files(tmp_path):
    """Empty project with no source files returns 1.0."""
    scorer = TruthScorer(tmp_path)
    result = scorer.score()
    assert result.dimensions["test_presence"] == 1.0
