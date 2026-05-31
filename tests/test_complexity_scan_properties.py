"""Property-based tests for the Complexity_Scan threshold classification.

Feature: complex-code-decomposition (task 1.3).

These tests exercise ``scripts.complexity_scan`` over generated Python function
sources and assert that the per-function Complexity_Threshold verdict
(``FunctionMetric.passes`` / ``FunctionMetric.exceeds``) is correct: a function
passes iff every measured metric is within its limit, and ``exceeds`` lists
exactly the limits actually violated.
"""

from __future__ import annotations

from hypothesis import example, given, settings
from hypothesis import strategies as st

from scripts.complexity_scan import (
    CC_LIMIT,
    LOC_LIMIT,
    NESTING_LIMIT,
    scan_source,
)


def _make_function_source(n_flat: int, nesting_depth: int, n_filler: int) -> str:
    """Build a single ``def f(a): ...`` whose metrics we can control.

    * ``n_filler`` plain ``a = a`` assignments add lines only (drive LOC).
    * ``n_flat`` sibling ``if a:`` blocks each add one decision point (drive CC)
      and sit at nesting depth 1.
    * ``nesting_depth`` chained ``if a:`` blocks add both decision points and
      nesting depth (drive Nesting_Depth).

    Resulting metrics (verified against the scan in the property below):
        cc      == 1 + n_flat + nesting_depth
        nesting == max(nesting_depth, 1 if n_flat else 0)
        loc     == number of source lines
    """
    lines = ["def f(a):", "    a = 0"]
    lines.extend("    a = a" for _ in range(n_filler))
    for _ in range(n_flat):
        lines.append("    if a:")
        lines.append("        a = 1")
    for depth in range(nesting_depth):
        lines.append("    " + "    " * depth + "if a:")
    if nesting_depth > 0:
        lines.append("    " + "    " * nesting_depth + "a = 1")
    return "\n".join(lines)


# Feature: complex-code-decomposition, Property 4: Complexity_Scan threshold classification is correct
@settings(max_examples=100, deadline=None)
@given(
    n_flat=st.integers(min_value=0, max_value=20),
    nesting_depth=st.integers(min_value=0, max_value=8),
    n_filler=st.integers(min_value=0, max_value=120),
)
# Boundary cases pinned on both sides of every limit (cc 15/16, loc 80/81, nesting 5/6):
@example(n_flat=9, nesting_depth=5, n_filler=54)  # cc=15, loc=80, nesting=5 -> passes
@example(n_flat=9, nesting_depth=6, n_filler=54)  # cc=16, loc=81, nesting=6 -> exceeds all
def test_threshold_classification_is_correct(
    n_flat: int, nesting_depth: int, n_filler: int
) -> None:
    """Validates: Requirements 2.1, 2.2, 2.3, 2.4

    For any parseable function, the scan reports ``passes is True`` iff
    ``cc <= 15 and loc <= 80 and nesting <= 5``, and ``exceeds`` lists exactly
    the violated limits (in the canonical cc/loc/nesting order).
    """
    source = _make_function_source(n_flat, nesting_depth, n_filler)
    metrics = scan_source(source, file="generated.py")

    # Exactly one (non-nested) function is defined in the generated source.
    assert len(metrics) == 1
    metric = metrics[0]

    # The scan measured the metrics the source was constructed to have; this
    # keeps the classification assertions below meaningful rather than vacuous
    # and confirms the inputs straddle each threshold boundary.
    assert metric.cc == 1 + n_flat + nesting_depth
    assert metric.nesting == max(nesting_depth, 1 if n_flat > 0 else 0)
    assert metric.loc == len(source.splitlines())

    # Property 4: passes iff every metric is within its limit.
    expected_pass = (
        metric.cc <= CC_LIMIT
        and metric.loc <= LOC_LIMIT
        and metric.nesting <= NESTING_LIMIT
    )
    assert metric.passes is expected_pass

    # Property 4: exceeds lists exactly the violated limits, in canonical order.
    expected_exceeds: list[str] = []
    if metric.cc > CC_LIMIT:
        expected_exceeds.append("cc")
    if metric.loc > LOC_LIMIT:
        expected_exceeds.append("loc")
    if metric.nesting > NESTING_LIMIT:
        expected_exceeds.append("nesting")
    assert metric.exceeds == expected_exceeds

    # passes and exceeds are mutually consistent: a function passes iff nothing
    # is exceeded.
    assert metric.passes is (metric.exceeds == [])
