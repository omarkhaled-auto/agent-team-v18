"""Tests for agent_team_v15.complexity_analyzer (Feature #5)."""

from __future__ import annotations

import pytest

from agent_team_v15.complexity_analyzer import (
    ComplexityAnalyzer,
    transform_add_error_handling,
    transform_add_logging,
    transform_add_types,
    transform_async_await,
    transform_remove_console,
    transform_var_to_const,
)


# ---------------------------------------------------------------------------
# Transform function tests
# ---------------------------------------------------------------------------

class TestTransformVarToConst:
    def test_basic(self):
        assert transform_var_to_const("var x = 1;") == "const x = 1;"

    def test_multiple(self):
        code = "var a = 1;\nvar b = 2;"
        result = transform_var_to_const(code)
        assert "var" not in result
        assert result.count("const") == 2

    def test_no_vars(self):
        code = "const x = 1; let y = 2;"
        assert transform_var_to_const(code) == code


class TestTransformAddTypes:
    def test_basic(self):
        result = transform_add_types("function foo(x, y) {}")
        assert "x: any" in result
        assert "y: any" in result

    def test_already_typed(self):
        result = transform_add_types("function foo(x: string, y: number) {}")
        assert "x: string" in result
        assert "y: number" in result

    def test_no_params(self):
        code = "function foo() {}"
        assert transform_add_types(code) == code


class TestTransformAddErrorHandling:
    def test_wraps_in_try_catch(self):
        code = "function foo() { return 1; }"
        result = transform_add_error_handling(code)
        assert "try" in result
        assert "catch" in result

    def test_skips_existing_try(self):
        code = "function foo() { try { x(); } catch(e) { } }"
        result = transform_add_error_handling(code)
        # Should not double-wrap
        assert result.count("try") == 1


class TestTransformAddLogging:
    def test_adds_entry_exit(self):
        code = "function bar() { return 42; }"
        result = transform_add_logging(code)
        assert "[ENTER] bar" in result
        assert "[EXIT] bar" in result


class TestTransformRemoveConsole:
    def test_removes_console_log(self):
        code = "console.log('hello');\nconst x = 1;"
        result = transform_remove_console(code)
        assert "console.log" not in result
        assert "const x = 1" in result

    def test_preserves_non_console(self):
        code = "const x = 1;\nreturn x;"
        assert transform_remove_console(code) == code


class TestTransformAsyncAwait:
    def test_converts_then(self):
        code = "function load() { fetchData().then(data => { process(data); }) }"
        result = transform_async_await(code)
        assert "await" in result

    def test_no_then(self):
        code = "function foo() { return 1; }"
        result = transform_async_await(code)
        assert "await" not in result


# ---------------------------------------------------------------------------
# ComplexityAnalyzer tests
# ---------------------------------------------------------------------------

class TestComplexityAnalyzer:
    def setup_method(self):
        self.analyzer = ComplexityAnalyzer()

    def test_score_range(self):
        """Score must always be in [0.0, 1.0]."""
        score = self.analyzer.analyze("rename a variable")
        assert 0.0 <= score <= 1.0

    def test_high_complexity(self):
        score = self.analyzer.analyze("architect a microservice with distributed caching strategy")
        assert score >= 0.3  # Multiple high-complexity keywords

    def test_low_complexity(self):
        score = self.analyzer.analyze("fix typo in comment")
        assert score <= 0.3

    def test_medium_complexity(self):
        score = self.analyzer.analyze("implement feature: add validation and error handling to the form")
        assert 0.05 <= score <= 0.8

    def test_code_length_factor(self):
        """Longer code should increase complexity score."""
        short_code = "const x = 1;"
        long_code = "\n".join(f"const x{i} = {i};" for i in range(600))

        score_short = self.analyzer.analyze("refactor this", code=short_code)
        score_long = self.analyzer.analyze("refactor this", code=long_code)
        assert score_long > score_short

    def test_no_task_returns_zero(self):
        score = self.analyzer.analyze("")
        assert score == 0.0

    def test_custom_keywords(self):
        analyzer = ComplexityAnalyzer(
            high_keywords=["mega"],
            medium_keywords=[],
            low_keywords=[],
        )
        score = analyzer.analyze("mega task")
        assert score >= 0.1

    def test_score_clamped_at_one(self):
        """Even with many keywords, score should not exceed 1.0."""
        task = " ".join([
            "architect redesign refactor entire migration distributed",
            "microservice scalability concurrency security audit",
            "performance optimization database schema authentication flow",
        ])
        score = self.analyzer.analyze(task)
        assert score <= 1.0
