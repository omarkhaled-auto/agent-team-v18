"""Keyword-based complexity scoring for 3-Tier Model Routing (Feature #5).

Analyzes task descriptions and optional code context to produce a
complexity score between 0.0 (trivial transform) and 1.0 (requires
deep reasoning).  All analysis is pure Python regex -- no external
dependencies.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Tier-1 transform functions (pure Python, no LLM needed)
# ---------------------------------------------------------------------------

def transform_var_to_const(code: str) -> str:
    """Replace ``var`` declarations with ``const`` (JS/TS)."""
    return re.sub(r'\bvar\b', 'const', code)


def transform_add_types(code: str) -> str:
    """Add basic TypeScript-style type annotations to untyped function params.

    Converts ``function foo(x, y)`` to ``function foo(x: any, y: any)``.
    """
    def _annotate(match: re.Match) -> str:
        name = match.group(1)
        params = match.group(2)
        if not params.strip():
            return match.group(0)
        parts = [p.strip() for p in params.split(',')]
        typed = []
        for p in parts:
            if ':' not in p and p:
                typed.append(f'{p}: any')
            else:
                typed.append(p)
        return f'function {name}({", ".join(typed)})'
    return re.sub(r'function\s+(\w+)\(([^)]*)\)', _annotate, code)


def transform_add_error_handling(code: str) -> str:
    """Wrap bare function bodies in try/catch (JS/TS).

    Only targets ``function name(...) {`` blocks that lack existing
    try/catch.  Scans the full brace-balanced body.
    """
    result = []
    i = 0
    while i < len(code):
        m = re.match(r'(function\s+\w+\([^)]*\))\s*\{', code[i:])
        if not m:
            result.append(code[i])
            i += 1
            continue
        sig = m.group(1)
        brace_start = i + m.end() - 1  # position of '{'
        # Find matching closing brace
        depth = 1
        j = brace_start + 1
        while j < len(code) and depth > 0:
            if code[j] == '{':
                depth += 1
            elif code[j] == '}':
                depth -= 1
            j += 1
        body = code[brace_start + 1:j - 1]
        if 'try' in body and 'catch' in body:
            # Already has try/catch — emit unchanged
            result.append(code[i:j])
        else:
            indent = '  '
            wrapped_body = '\n'.join(f'{indent}{indent}{line}' for line in body.strip().splitlines())
            result.append(
                f'{sig} {{\n'
                f'{indent}try {{\n'
                f'{wrapped_body}\n'
                f'{indent}}} catch (error) {{\n'
                f'{indent}{indent}console.error(error);\n'
                f'{indent}{indent}throw error;\n'
                f'{indent}}}\n'
                f'}}'
            )
        i = j
    return ''.join(result)


def transform_add_logging(code: str) -> str:
    """Add ``console.log`` entry/exit markers to functions."""
    def _add_log(match: re.Match) -> str:
        sig = match.group(1)
        name_match = re.search(r'function\s+(\w+)', sig)
        fname = name_match.group(1) if name_match else 'anonymous'
        body = match.group(2)
        return (
            f'{sig} {{\n'
            f'  console.log("[ENTER] {fname}");\n'
            f'{body}\n'
            f'  console.log("[EXIT] {fname}");\n'
            f'}}'
        )
    return re.sub(
        r'(function\s+\w+\([^)]*\))\s*\{([^}]+)\}',
        _add_log,
        code,
    )


def transform_remove_console(code: str) -> str:
    """Remove ``console.log(...)`` statements."""
    return re.sub(r'\s*console\.log\([^)]*\);?\s*\n?', '\n', code)


def transform_async_await(code: str) -> str:
    """Convert ``.then(cb)`` chains to ``async/await`` style.

    Rewrites ``someCall().then(x => { ... })`` to
    ``const result = await someCall();``.
    """
    # Simple .then() chain → await
    code = re.sub(
        r'(\w[\w.]*\([^)]*\))\.then\(\s*(\w+)\s*=>\s*\{([^}]*)\}\s*\)',
        r'const \2 = await \1;\3',
        code,
    )
    # Mark containing function as async if not already
    code = re.sub(
        r'(?<!async\s)function\s+(\w+)\(([^)]*)\)\s*\{([^}]*await\s)',
        r'async function \1(\2) {\3',
        code,
    )
    return code


# ---------------------------------------------------------------------------
# Complexity keyword tables
# ---------------------------------------------------------------------------

_HIGH_COMPLEXITY_KEYWORDS: list[str] = [
    'architect', 'redesign', 'refactor entire', 'migration',
    'distributed', 'microservice', 'scalability', 'concurrency',
    'security audit', 'performance optimization', 'database schema',
    'authentication flow', 'authentication', 'authorization', 'oauth',
    'real-time', 'websocket',
    'machine learning', 'algorithm design', 'state management',
    'caching strategy', 'api design', 'system design',
    'event-driven', 'cqrs', 'domain-driven',
]

_MEDIUM_COMPLEXITY_KEYWORDS: list[str] = [
    'refactor', 'integrate', 'implement feature', 'add endpoint',
    'create component', 'write tests', 'add validation', 'error handling',
    'pagination', 'filtering', 'sorting', 'form validation',
    'api call', 'database query', 'middleware', 'hook',
    'context', 'provider', 'reducer', 'state',
]

_LOW_COMPLEXITY_KEYWORDS: list[str] = [
    'rename', 'fix typo', 'update comment', 'change color',
    'add logging', 'remove console', 'var to const', 'add types',
    'format', 'lint', 'style', 'indent',
    'simple', 'trivial', 'minor', 'small change',
]


class ComplexityAnalyzer:
    """Keyword-based complexity scoring engine.

    Produces a score in [0.0, 1.0] from task descriptions and optional
    code context.  Higher scores indicate tasks that likely require a
    more capable (and more expensive) model.
    """

    def __init__(
        self,
        high_keywords: list[str] | None = None,
        medium_keywords: list[str] | None = None,
        low_keywords: list[str] | None = None,
    ) -> None:
        self.high_keywords = high_keywords or _HIGH_COMPLEXITY_KEYWORDS
        self.medium_keywords = medium_keywords or _MEDIUM_COMPLEXITY_KEYWORDS
        self.low_keywords = low_keywords or _LOW_COMPLEXITY_KEYWORDS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, task: str, code: str | None = None) -> float:
        """Return a complexity score between 0.0 and 1.0.

        The score is determined by keyword matching against the task
        description and optional code context.  Code length also
        influences the score (longer code -> higher complexity).
        """
        text = task.lower()
        if code:
            text += ' ' + code.lower()

        score = 0.0

        # Keyword matching
        high_hits = sum(1 for kw in self.high_keywords if kw in text)
        medium_hits = sum(1 for kw in self.medium_keywords if kw in text)
        low_hits = sum(1 for kw in self.low_keywords if kw in text)

        score += high_hits * 0.20
        score += medium_hits * 0.06
        score += low_hits * 0.02

        # Code length factor (if code provided)
        if code:
            lines = len(code.splitlines())
            if lines > 500:
                score += 0.2
            elif lines > 200:
                score += 0.1
            elif lines > 50:
                score += 0.05

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, score))
