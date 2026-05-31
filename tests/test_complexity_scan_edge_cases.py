"""Unit tests for Complexity_Scan edge cases (task 1.5).

These tests pin the exact decision-point counting rules implemented in
``scripts/complexity_scan.py`` for the trickier AST shapes -- comprehensions,
boolean operators, ternaries, ``match``/``case``, nested functions -- and the
unparseable/missing-input contract of ``scan_source`` / ``scan_file``.

CC counting rule under test (Requirements 2.1, 2.4):
``CC = 1 + decision points`` where decision points are ``if`` / ``elif``,
``for`` / ``while``, ``except``, each comprehension ``if`` clause, each ternary
``IfExp``, each ``match`` ``case``, and ``len(values) - 1`` per boolean operator.
Nested ``def`` / ``class`` scopes are measured as their own functions and are
excluded from the enclosing function's metrics.
"""

from __future__ import annotations

import textwrap

import pytest

from scripts.complexity_scan import FunctionMetric, scan_file, scan_source


def _scan_single(source: str) -> FunctionMetric:
    """Scan ``source`` (dedented) expecting exactly one function; return it."""
    metrics = scan_source(textwrap.dedent(source), file="sample.py")
    assert len(metrics) == 1, f"expected one function, got {len(metrics)}"
    return metrics[0]


def _by_qualname(source: str) -> dict[str, FunctionMetric]:
    """Scan ``source`` (dedented) and index the metrics by qualname."""
    metrics = scan_source(textwrap.dedent(source), file="sample.py")
    return {m.qualname: m for m in metrics}


# ---------------------------------------------------------------------------
# Comprehensions -- each comprehension ``if`` clause adds 1 to CC, and the
# comprehension's internal ``for`` does NOT add nesting (it is an expression).
# ---------------------------------------------------------------------------


def test_comprehensions_each_if_clause_adds_one() -> None:
    metric = _scan_single(
        """
        def comp(items):
            a = [x for x in items if x]
            b = {k: v for k, v in items if k}
            c = {y for y in items if y}
            return a, b, c
        """
    )
    # 3 comprehensions, one ``if`` each -> 3 decision points.
    assert metric.cc == 4
    # Comprehension ``for`` clauses are expressions, not control-flow blocks.
    assert metric.nesting == 0


def test_comprehension_multiple_if_clauses_each_count() -> None:
    metric = _scan_single(
        """
        def comp_two_ifs(items):
            return [x for x in items if x > 0 if x < 10]
        """
    )
    # Two ``if`` clauses on a single comprehension -> 2 decision points.
    assert metric.cc == 3
    assert metric.nesting == 0


# ---------------------------------------------------------------------------
# Boolean operators -- each BoolOp adds ``len(values) - 1``.
# ---------------------------------------------------------------------------


def test_boolean_operators_add_n_minus_one_per_boolop() -> None:
    metric = _scan_single(
        """
        def boolean_ops(a, b, c, d, e):
            x = a and b
            y = c or d or e
            return x and y
        """
    )
    # (and:2->+1) + (or:3->+2) + (and:2->+1) = 4 decision points.
    assert metric.cc == 5
    assert metric.nesting == 0


def test_mixed_and_or_counts_each_nested_boolop() -> None:
    metric = _scan_single(
        """
        def mixed(a, b, c):
            return a and b or c
        """
    )
    # ``a and b or c`` parses as Or(And(a, b), c): outer Or +1, inner And +1.
    assert metric.cc == 3
    assert metric.nesting == 0


# ---------------------------------------------------------------------------
# Ternary expressions (IfExp) -- each adds 1 to CC but NOT to nesting, in
# contrast to a statement-level ``if`` which adds to both.
# ---------------------------------------------------------------------------


def test_ternary_expression_adds_one_to_cc_not_nesting() -> None:
    metric = _scan_single(
        """
        def ternary(a, b, cond):
            return a if cond else b
        """
    )
    assert metric.cc == 2
    assert metric.nesting == 0


def test_multiple_ternaries_each_add_one() -> None:
    metric = _scan_single(
        """
        def ternaries(a, b, p, q, c1, c2, c3):
            x = a if c1 else b
            y = p if c2 else q
            return x if c3 else y
        """
    )
    assert metric.cc == 4
    assert metric.nesting == 0


def test_statement_if_contrasts_with_ternary_for_nesting() -> None:
    # A statement-level ``if`` adds the same +1 to CC as a ternary, but unlike
    # the ternary it also deepens nesting.
    metric = _scan_single(
        """
        def with_if(cond, a, b):
            if cond:
                return a
            return b
        """
    )
    assert metric.cc == 2
    assert metric.nesting == 1


# ---------------------------------------------------------------------------
# match / case -- each ``case`` clause adds 1 to CC.
# ---------------------------------------------------------------------------


def test_match_each_case_adds_one() -> None:
    metric = _scan_single(
        """
        def matcher(command):
            match command:
                case "a":
                    return 1
                case "b":
                    return 2
                case _:
                    return 0
        """
    )
    # Three ``case`` clauses -> 3 decision points.
    assert metric.cc == 4
    # ``match`` is not one of the nesting control-flow blocks.
    assert metric.nesting == 0


# ---------------------------------------------------------------------------
# Nested functions -- the inner def is reported as its own function and the
# outer function's metrics exclude the inner body.
# ---------------------------------------------------------------------------


def test_nested_function_reported_separately_and_excluded_from_outer() -> None:
    metrics = _by_qualname(
        """
        def outer(y):
            def inner(a, b, c):
                if a:
                    pass
                if b:
                    pass
                if c:
                    pass
                return 1
            if y:
                return inner(1, 2, 3)
            return None
        """
    )

    assert set(metrics) == {"sample.outer", "sample.outer.inner"}

    outer = metrics["sample.outer"]
    inner = metrics["sample.outer.inner"]

    # Outer sees only its own ``if y`` -- the inner def's three ifs are excluded.
    assert outer.cc == 2
    assert outer.nesting == 1

    # Inner is measured on its own: three ifs -> CC 4.
    assert inner.cc == 4
    assert inner.nesting == 1


def test_nested_function_qualname_is_dotted_under_outer() -> None:
    metrics = _by_qualname(
        """
        def outer():
            def inner():
                return 1
            return inner
        """
    )
    assert "sample.outer.inner" in metrics
    assert metrics["sample.outer.inner"].cc == 1


# ---------------------------------------------------------------------------
# Unparseable / missing input.
# ---------------------------------------------------------------------------


def test_scan_source_raises_syntax_error_on_unparseable_input() -> None:
    with pytest.raises(SyntaxError):
        scan_source("def broken(:\n    pass\n", file="broken.py")


def test_scan_file_returns_empty_for_unparseable_file(tmp_path) -> None:
    bad = tmp_path / "broken.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")
    assert scan_file(bad) == []


def test_scan_file_returns_empty_for_missing_file(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.py"
    assert scan_file(missing) == []
