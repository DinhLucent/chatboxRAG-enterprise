"""Property test for Complexity_Scan metric monotonicity under wrapping.

Task 1.4 / Property 5: the Complexity_Scan must respond correctly to the very
transformations the decomposition playbook performs. Wrapping a function body
in an extra control-flow block must never decrease nesting and must strictly
increase cyclomatic complexity (the wrapper adds a decision point); extracting
an inner block out of the body must not increase either metric.

These are metamorphic properties over the pure AST metric functions
``compute_cc`` / ``compute_nesting`` (Requirements 2.1, 2.3, 2.4).
"""

from __future__ import annotations

import ast

from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.complexity_scan import compute_cc, compute_nesting


# ---------------------------------------------------------------------------
# Source generators
# ---------------------------------------------------------------------------

# Simple (non-block) statements. A mix of plain statements and ones that carry
# decision points (boolean operators, ternaries, comprehension ``if``) so the
# generated bodies exercise the full CC counting surface. Names are undefined
# on purpose -- the source is only parsed, never executed.
_SIMPLE_STATEMENTS = [
    "pass",
    "x = 1",
    "x += 1",
    "return x",
    "y = a and b",            # BoolOp -> +1 CC
    "z = a or b or c",        # BoolOp (3 values) -> +2 CC
    "w = a if b else c",      # ternary IfExp -> +1 CC
    "total = sum(v for v in items if v)",  # comprehension if -> +1 CC
]

# Control-flow block headers. ``if``/``for``/``while`` each add a decision
# point and a nesting level; ``with`` adds a nesting level only.
_BLOCK_HEADERS = ["if a:", "for _ in items:", "while a:", "with ctx:"]


def _assemble_block(header: str, child_stmts: list[list[str]]) -> list[str]:
    """Render a control-flow block as source lines at column 0.

    ``child_stmts`` is a list of statements, each itself a list of source lines
    already indented relative to its own column 0.
    """
    body_lines: list[str] = []
    for stmt in child_stmts:
        body_lines.extend(stmt)
    if not body_lines:
        body_lines = ["pass"]
    return [header] + ["    " + line for line in body_lines]


# A statement is a list of source lines (column-0 relative). Recursively either
# a simple statement (leaf) or a control-flow block wrapping nested statements.
_simple = st.sampled_from(_SIMPLE_STATEMENTS).map(lambda s: [s])
_statement = st.recursive(
    _simple,
    lambda children: st.builds(
        _assemble_block,
        st.sampled_from(_BLOCK_HEADERS),
        st.lists(children, min_size=1, max_size=3),
    ),
    max_leaves=12,
)

# A statement guaranteed to be a control-flow block (for the extraction test).
_block_statement = st.builds(
    _assemble_block,
    st.sampled_from(_BLOCK_HEADERS),
    st.lists(_statement, min_size=1, max_size=3),
)

# A function body: a non-empty sequence of statements.
_body = st.lists(_statement, min_size=1, max_size=4)


def _stmts_to_lines(stmts: list[list[str]]) -> list[str]:
    """Flatten a list of statements into body source lines at column 0."""
    lines: list[str] = []
    for stmt in stmts:
        lines.extend(stmt)
    if not lines:
        lines = ["pass"]
    return lines


def _function_source(body_lines: list[str]) -> str:
    """Wrap column-0 body lines in ``def f():`` at the function-body indent."""
    return "def f():\n" + "\n".join("    " + line for line in body_lines) + "\n"


def _wrap_in_block(body_lines: list[str]) -> list[str]:
    """Wrap body lines in an extra ``if True:`` decision-bearing block.

    ``if True:`` adds exactly one decision point (CC +1) and one nesting level,
    so it is a clean wrapper for the monotonicity relation.
    """
    return ["if True:"] + ["    " + line for line in body_lines]


def _metrics(source: str) -> tuple[int, int]:
    """Parse ``source`` and return ``(cc, nesting)`` of its single function."""
    tree = ast.parse(source)
    func = tree.body[0]
    return compute_cc(func), compute_nesting(func)


# ---------------------------------------------------------------------------
# Property 5 tests
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(body=_body)
def test_wrapping_in_block_increases_cc_and_does_not_decrease_nesting(body):
    # Feature: complex-code-decomposition, Property 5: Complexity_Scan nesting and CC are monotonic under wrapping
    body_lines = _stmts_to_lines(body)

    base_cc, base_nesting = _metrics(_function_source(body_lines))
    wrapped_cc, wrapped_nesting = _metrics(
        _function_source(_wrap_in_block(body_lines))
    )

    # Wrapping in an extra control-flow block never decreases nesting...
    assert wrapped_nesting >= base_nesting
    # ...and strictly increases CC (the wrapper adds a decision point).
    assert wrapped_cc > base_cc


@settings(max_examples=100, deadline=None)
@given(
    prefix=st.lists(_statement, max_size=2),
    inner=_block_statement,
    suffix=st.lists(_statement, max_size=2),
)
def test_extracting_inner_block_does_not_increase_either_metric(prefix, inner, suffix):
    # Feature: complex-code-decomposition, Property 5: Complexity_Scan nesting and CC are monotonic under wrapping
    original_stmts = prefix + [inner] + suffix
    # Extracting the inner block into a separate function leaves a plain call in
    # its place (no decision point, no nesting) for the remaining body.
    extracted_stmts = prefix + [["result = helper()"]] + suffix

    original_cc, original_nesting = _metrics(
        _function_source(_stmts_to_lines(original_stmts))
    )
    extracted_cc, extracted_nesting = _metrics(
        _function_source(_stmts_to_lines(extracted_stmts))
    )

    # Extracting an inner block must not increase either metric for the
    # remaining body.
    assert extracted_nesting <= original_nesting
    assert extracted_cc <= original_cc


def test_wrapping_example_is_exactly_plus_one_cc_and_nesting():
    """Concrete anchor: wrapping a known body adds exactly +1 CC and +1 nesting."""
    body_lines = ["x = a and b", "return x"]  # cc=2 (BoolOp), nesting=0

    base_cc, base_nesting = _metrics(_function_source(body_lines))
    wrapped_cc, wrapped_nesting = _metrics(
        _function_source(_wrap_in_block(body_lines))
    )

    assert (base_cc, base_nesting) == (2, 0)
    assert (wrapped_cc, wrapped_nesting) == (3, 1)
