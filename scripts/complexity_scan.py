"""Complexity_Scan tool for the complex-code-decomposition effort.

A dependency-light, AST-only analyzer that measures per-function
``Cyclomatic_Complexity`` (CC), ``Function_Length`` (LOC), and
``Nesting_Depth`` for Python source, and classifies each function against the
``Complexity_Threshold`` (CC <= 15, LOC <= 80, nesting <= 5).

This module implements the metric data models and the metric computation
(task 1.1) plus the scan traversal, before/after diffing, and the CLI/JSON
reporting layer (task 1.2).

Metric computation rules (kept explicit so results are reproducible and match
the scan that produced the hotspot inventory):

* **CC**: ``1 + count of decision points`` where decision points are ``if`` /
  ``elif``, ``for``, ``while``, each ``and`` / ``or`` operator, ``except``
  handlers, comprehension ``if`` clauses, ternary expressions, and ``case``
  clauses.
* **LOC**: ``end_lineno - lineno + 1`` of the function node (body length
  including the signature line).
* **Nesting_Depth**: the maximum depth of nested control-flow blocks
  (``if`` / ``for`` / ``while`` / ``with`` / ``try``) within the function. The
  AST is read literally, so an ``elif`` chain (represented as nested ``If``
  nodes in ``orelse``) deepens the count -- this reproduces the reference scan.

Nested ``def`` / ``async def`` / ``class`` definitions are treated as separate
scopes: their bodies do not contribute to the enclosing function's metrics
(the scan reports them as their own functions).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

__all__ = [
    "CC_LIMIT",
    "LOC_LIMIT",
    "NESTING_LIMIT",
    "FunctionMetric",
    "ThresholdException",
    "ScanDiff",
    "compute_cc",
    "compute_loc",
    "compute_nesting",
    "metric_for_function",
    "FunctionNode",
    "scan_source",
    "scan_file",
    "scan_path",
    "diff_reports",
    "report_payload",
    "build_parser",
    "main",
]

# Complexity_Threshold ceilings (Requirements 2.1, 2.2, 2.3).
CC_LIMIT = 15
LOC_LIMIT = 80
NESTING_LIMIT = 5

# Function-like AST nodes the scan treats as analyzable units.
FunctionNode = (ast.FunctionDef, ast.AsyncFunctionDef)

# Nodes that open a new lexical scope. When measuring a function's metrics we do
# not descend into these, so a nested function/class is measured on its own.
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Statement-level control-flow blocks that increase Nesting_Depth.
_NESTING_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
)


@dataclass(frozen=True)
class FunctionMetric:
    """Computed complexity metrics for a single function.

    ``passes`` / ``exceeds`` derive the Complexity_Threshold verdict so the
    classification logic lives in one place (Requirement 2.4).
    """

    qualname: str
    file: str
    lineno: int
    cc: int
    loc: int
    nesting: int

    @property
    def passes(self) -> bool:
        """True iff the function meets every Complexity_Threshold limit."""
        return (
            self.cc <= CC_LIMIT
            and self.loc <= LOC_LIMIT
            and self.nesting <= NESTING_LIMIT
        )

    @property
    def exceeds(self) -> list[str]:
        """The threshold limits the function violates (subset of cc/loc/nesting)."""
        violated: list[str] = []
        if self.cc > CC_LIMIT:
            violated.append("cc")
        if self.loc > LOC_LIMIT:
            violated.append("loc")
        if self.nesting > NESTING_LIMIT:
            violated.append("nesting")
        return violated


@dataclass(frozen=True)
class ThresholdException:
    """A function that remains over the Complexity_Threshold, with rationale.

    Records the identifier, the measured metrics, the specific limit(s)
    exceeded, and a documented reason the threshold was not met
    (Requirements 2.5, 13.5).
    """

    qualname: str
    cc: int
    loc: int
    nesting: int
    exceeded: list[str]
    reason: str = ""

    @classmethod
    def from_metric(cls, metric: FunctionMetric, reason: str = "") -> "ThresholdException":
        """Build an exception entry from a failing :class:`FunctionMetric`."""
        return cls(
            qualname=metric.qualname,
            cc=metric.cc,
            loc=metric.loc,
            nesting=metric.nesting,
            exceeded=metric.exceeds,
            reason=reason,
        )


@dataclass(frozen=True)
class ScanDiff:
    """Before/after comparison for one decomposed hotspot.

    ``before`` is the original hotspot's metric; ``after`` is the list of
    resulting functions. ``all_pass`` is True when every resulting function
    meets the threshold; ``exceptions`` records any that do not (Req 2.5, 13).
    """

    hotspot: str
    before: FunctionMetric
    after: list[FunctionMetric] = field(default_factory=list)
    all_pass: bool = False
    exceptions: list[ThresholdException] = field(default_factory=list)


def compute_loc(node: ast.AST) -> int:
    """Return the function length in lines: ``end_lineno - lineno + 1``.

    Falls back to 1 when end position info is unavailable (Requirement 2.2).
    """
    end_lineno = getattr(node, "end_lineno", None)
    lineno = getattr(node, "lineno", None)
    if end_lineno is None or lineno is None:
        return 1
    return end_lineno - lineno + 1


def compute_cc(node: ast.AST) -> int:
    """Return Cyclomatic_Complexity: ``1 + decision points`` (Requirement 2.1)."""
    body: Iterable[ast.stmt] = getattr(node, "body", []) or []
    return 1 + sum(
        _count_decision_points(stmt)
        for stmt in body
        if not isinstance(stmt, _SCOPE_NODES)
    )


def compute_nesting(node: ast.AST) -> int:
    """Return the maximum nesting depth of control-flow blocks (Requirement 2.3)."""
    body: Iterable[ast.stmt] = getattr(node, "body", []) or []
    best = 0
    for stmt in body:
        if isinstance(stmt, _SCOPE_NODES):
            continue
        best = max(best, _max_nesting(stmt, 0))
    return best


def metric_for_function(node: ast.AST, *, qualname: str, file: str) -> FunctionMetric:
    """Compute a :class:`FunctionMetric` for ``node`` (a def/async def node)."""
    return FunctionMetric(
        qualname=qualname,
        file=file,
        lineno=getattr(node, "lineno", 0),
        cc=compute_cc(node),
        loc=compute_loc(node),
        nesting=compute_nesting(node),
    )


def _count_decision_points(node: ast.AST) -> int:
    """Count decision points contributed by ``node`` and its descendants.

    Does not descend into nested function/class scopes, which are measured as
    their own units.
    """
    total = 0

    if isinstance(node, ast.If):  # also covers ``elif`` (nested If in orelse)
        total += 1
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        total += 1
    elif isinstance(node, ast.ExceptHandler):
        total += 1
    elif isinstance(node, ast.IfExp):  # ternary expression
        total += 1
    elif isinstance(node, ast.BoolOp):  # each ``and`` / ``or`` operator branches
        total += len(node.values) - 1
    elif isinstance(node, ast.comprehension):  # comprehension ``if`` clauses
        total += len(node.ifs)
    elif isinstance(node, ast.match_case):  # ``case`` clause
        total += 1

    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPE_NODES):
            continue
        total += _count_decision_points(child)
    return total


def _max_nesting(node: ast.AST, depth: int) -> int:
    """Return the deepest control-flow nesting reachable from ``node``.

    ``depth`` is the nesting level at which ``node`` itself sits. Entering a
    control-flow block places its children one level deeper. Nested scopes are
    not descended into.
    """
    if isinstance(node, _SCOPE_NODES):
        return depth

    inner = depth + 1 if isinstance(node, _NESTING_NODES) else depth
    best = depth
    for child in ast.iter_child_nodes(node):
        best = max(best, _max_nesting(child, inner))
    return best


# ---------------------------------------------------------------------------
# Scan traversal (task 1.2)
# ---------------------------------------------------------------------------


def _relativize(path: Path) -> str:
    """Return ``path`` relative to the current working directory as posix.

    Falls back to the resolved absolute posix path when ``path`` is outside the
    working directory, so a scan run from the repo root reports files like
    ``poc_workflow/qa_agent_workflow.py``.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _iter_functions(
    tree: ast.AST, *, module_name: str
) -> list[tuple[ast.AST, str]]:
    """Yield ``(node, qualname)`` for every function defined anywhere in ``tree``.

    The qualname is dotted and prefixed with ``module_name`` (e.g.
    ``module.ClassName.method`` or ``module.outer.inner``). Functions nested
    inside control-flow blocks are discovered too; class and function scopes
    extend the prefix so each unit gets a stable, unique identifier.
    """
    results: list[tuple[ast.AST, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FunctionNode):
                qual = f"{prefix}.{child.name}"
                results.append((child, qual))
                visit(child, qual)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}.{child.name}")
            else:
                visit(child, prefix)

    visit(tree, module_name)
    return results


def scan_source(
    source: str, *, file: str, only: set[str] | None = None
) -> list[FunctionMetric]:
    """Scan ``source`` text and return one :class:`FunctionMetric` per function.

    ``file`` is the (relative) path recorded on each metric and used to derive
    the module-name prefix of qualnames. ``only`` optionally restricts the
    result to functions whose qualname is in the given set. Raises
    :class:`SyntaxError` if ``source`` cannot be parsed.
    """
    tree = ast.parse(source)
    module_name = Path(file).stem
    metrics: list[FunctionMetric] = []
    for node, qualname in _iter_functions(tree, module_name=module_name):
        if only is not None and qualname not in only:
            continue
        metrics.append(metric_for_function(node, qualname=qualname, file=file))
    return metrics


def scan_file(
    path: Path | str, *, only: set[str] | None = None
) -> list[FunctionMetric]:
    """Scan a single ``.py`` file. Returns ``[]`` for unreadable/unparseable files."""
    file_path = Path(path)
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        return scan_source(source, file=_relativize(file_path), only=only)
    except SyntaxError:
        return []


def _python_files(target: Path) -> list[Path]:
    """Return the ``.py`` files under ``target`` (a file or directory), sorted."""
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    if not target.exists():
        return []
    return sorted(
        p
        for p in target.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def scan_path(
    path: Path | str, *, only: set[str] | None = None
) -> list[FunctionMetric]:
    """Walk ``path`` (file or directory) and return all function metrics.

    Files that cannot be read or parsed are skipped so a directory scan is
    robust to an isolated bad file. Results are sorted deterministically by
    ``(file, lineno, qualname)``. ``only`` restricts the result to the given
    set of dotted qualnames (Req 2.4, 13.1).
    """
    target = Path(path)
    metrics: list[FunctionMetric] = []
    for file_path in _python_files(target):
        metrics.extend(scan_file(file_path, only=only))
    metrics.sort(key=lambda m: (m.file, m.lineno, m.qualname))
    return metrics


# ---------------------------------------------------------------------------
# Before/after diff (task 1.2)
# ---------------------------------------------------------------------------


def diff_reports(
    before: list[FunctionMetric], after: list[FunctionMetric]
) -> ScanDiff:
    """Compare a pre-decomposition scan to a post-decomposition scan.

    The hotspot is taken to be the highest-complexity function in ``before``
    (the primary decomposition target), tie-broken deterministically by
    ``(cc, loc, nesting, qualname)``. The resulting functions are the residual
    hotspot (if its name survives) plus every function in ``after`` that did
    not exist in ``before`` -- i.e. the units extracted by the decomposition.

    ``all_pass`` is True when every resulting function meets the
    Complexity_Threshold; ``exceptions`` records any that do not (Reqs 2.5, 13).
    """
    if not before:
        raise ValueError("before report must contain at least one function")

    hotspot = max(before, key=lambda m: (m.cc, m.loc, m.nesting, m.qualname))
    before_names = {m.qualname for m in before}
    resulting = [
        m
        for m in after
        if m.qualname == hotspot.qualname or m.qualname not in before_names
    ]
    resulting.sort(key=lambda m: (m.file, m.lineno, m.qualname))

    all_pass = bool(resulting) and all(m.passes for m in resulting)
    exceptions = [
        ThresholdException.from_metric(m) for m in resulting if not m.passes
    ]
    return ScanDiff(
        hotspot=hotspot.qualname,
        before=hotspot,
        after=resulting,
        all_pass=all_pass,
        exceptions=exceptions,
    )


# ---------------------------------------------------------------------------
# JSON reporting (task 1.2)
# ---------------------------------------------------------------------------


def _function_dict(metric: FunctionMetric) -> dict:
    """Serialize a metric to the JSON function entry shape (key ``pass``)."""
    return {
        "qualname": metric.qualname,
        "file": metric.file,
        "lineno": metric.lineno,
        "cc": metric.cc,
        "loc": metric.loc,
        "nesting": metric.nesting,
        "pass": metric.passes,
        "exceeds": metric.exceeds,
    }


def report_payload(metrics: list[FunctionMetric], *, target: str) -> dict:
    """Build the JSON report payload (functions + summary) for ``metrics``.

    Matches the documented output shape: ``generated_at``, ``target``,
    ``threshold``, ``functions``, and ``summary`` (Req 2.4, 13.1).
    """
    passing = sum(1 for m in metrics if m.passes)
    failing = len(metrics) - passing
    pass_rate = round(passing / len(metrics), 3) if metrics else 0.0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "threshold": {"cc": CC_LIMIT, "loc": LOC_LIMIT, "nesting": NESTING_LIMIT},
        "functions": [_function_dict(m) for m in metrics],
        "summary": {
            "function_count": len(metrics),
            "passing": passing,
            "failing": failing,
            "pass_rate": pass_rate,
        },
    }


def _metrics_from_payload(payload: dict) -> list[FunctionMetric]:
    """Rebuild a metric list from a previously emitted JSON report payload."""
    metrics: list[FunctionMetric] = []
    for entry in payload.get("functions", []):
        metrics.append(
            FunctionMetric(
                qualname=entry["qualname"],
                file=entry["file"],
                lineno=entry["lineno"],
                cc=entry["cc"],
                loc=entry["loc"],
                nesting=entry["nesting"],
            )
        )
    return metrics


def _load_baseline(path: Path | str) -> list[FunctionMetric]:
    """Load a baseline report file and return its metrics."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _metrics_from_payload(payload)


# ---------------------------------------------------------------------------
# CLI (task 1.2)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the Complexity_Scan CLI."""
    parser = argparse.ArgumentParser(
        prog="complexity_scan",
        description=(
            "Measure cyclomatic complexity, length, and nesting of Python "
            "functions and classify each against the Complexity_Threshold "
            "(CC<=15, LOC<=80, nesting<=5)."
        ),
    )
    parser.add_argument(
        "path",
        help="File or directory to scan (e.g. poc_workflow).",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        metavar="OUT",
        help="Write the JSON report to this file path.",
    )
    parser.add_argument(
        "--baseline",
        metavar="FILE",
        help="A previously emitted JSON report to diff the current scan against.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        metavar="DOTTED_NAME",
        help="Restrict the scan to these dotted function qualnames.",
    )
    parser.add_argument(
        "--fail-over-threshold",
        action="store_true",
        help="Exit non-zero if any in-scope function exceeds the threshold.",
    )
    return parser


def _print_summary(payload: dict) -> None:
    """Print a concise human-readable summary of a report payload to stdout."""
    summary = payload["summary"]
    rate_pct = summary["pass_rate"] * 100
    print(
        f"Scanned {payload['target']}: {summary['function_count']} functions, "
        f"{summary['passing']} passing, {summary['failing']} failing "
        f"(pass rate {rate_pct:.1f}%)"
    )
    failing = [f for f in payload["functions"] if not f["pass"]]
    if failing:
        print("Functions over threshold:")
        for f in failing:
            exceeds = ", ".join(f["exceeds"])
            print(
                f"  {f['qualname']}  cc={f['cc']} loc={f['loc']} "
                f"nesting={f['nesting']}  exceeds: {exceeds}"
            )


def _print_diff(diff: ScanDiff) -> None:
    """Print a before/after diff for one decomposed hotspot to stdout."""
    before = diff.before
    print(f"Diff for hotspot {diff.hotspot}:")
    print(f"  before: cc={before.cc} loc={before.loc} nesting={before.nesting}")
    print(f"  after ({len(diff.after)} functions): all_pass={diff.all_pass}")
    for metric in diff.after:
        verdict = "PASS" if metric.passes else "FAIL"
        print(
            f"    {metric.qualname}  cc={metric.cc} loc={metric.loc} "
            f"nesting={metric.nesting}  {verdict}"
        )
    for exc in diff.exceptions:
        exceeded = ", ".join(exc.exceeded)
        print(f"  exception: {exc.qualname} exceeds {exceeded}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    only = set(args.only) if args.only else None
    metrics = scan_path(args.path, only=only)
    payload = report_payload(metrics, target=str(args.path))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    _print_summary(payload)

    if args.baseline:
        before = _load_baseline(args.baseline)
        _print_diff(diff_reports(before, metrics))

    if args.fail_over_threshold and any(not m.passes for m in metrics):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
