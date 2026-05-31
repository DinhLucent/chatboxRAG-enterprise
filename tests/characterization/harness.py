"""Characterization (golden) test harness.

This module implements the capture/compare helpers and volatile-field
normalization used by the complex-code-decomposition effort to pin the
current ``Observable_Behavior`` of a hotspot *before* any structural edit and
to assert zero ``Behavior_Regression`` afterwards.

Design reference: ``.kiro/specs/complex-code-decomposition/design.md`` —
"Component 2: Characterization test harness".

Public API
----------
- ``VOLATILE`` — the centralized set of inherently non-deterministic fields
  (timestamps, auto-generated ids, ``latency_ms``, ``generated_at``, run ids)
  that are excluded from equivalence comparisons (Requirements 1.3, 1.5).
- ``golden_cli`` — capture exit code + raw stdout/stderr for byte-exact compare.
- ``golden_http`` — capture status + body + content-type via a TestClient.
- ``golden_answer`` — capture answer text + citation collection for an answer
  path, recording whether citations compare order-sensitively (Req 7.2) or
  order-insensitively (Req 1.4).
- ``assert_equivalent`` — zero-regression check that dispatches on capture type
  and ignores volatile fields when comparing structured payloads.
- ``strip_volatile`` — recursively drop volatile keys from a payload.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Volatile field set (Requirements 1.3, 1.5)
# ---------------------------------------------------------------------------

#: Inherently non-deterministic fields excluded from equivalence comparisons.
#: Covers timestamps, auto-generated identifiers, ``latency_ms``,
#: ``generated_at``, and run ids called out by the design.
VOLATILE: frozenset[str] = frozenset(
    {
        # latency / timing
        "latency_ms",
        # generation / timestamps
        "generated_at",
        "created_at",
        "updated_at",
        "completed_at",
        "started_at",
        "finished_at",
        "timestamp",
        "logged_at",
        # auto-generated identifiers
        "id",
        "log_id",
        "query_log_id",
        "knowledge_gap_id",
        "incident_id",
        "gap_id",
        # run ids
        "run_id",
        "answer_run_id",
        "ingestion_run_id",
    }
)


# ---------------------------------------------------------------------------
# Capture data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CliCapture:
    """Captured CLI behavior: exit code plus raw stdout/stderr bytes.

    stdout/stderr are kept as ``bytes`` so the comparison is byte-for-byte
    exact (Requirement 1.2 / 6.2), with no decoding normalization applied.
    """

    exit_code: int
    stdout: bytes
    stderr: bytes

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class HttpCapture:
    """Captured HTTP behavior: status, content-type, and parsed body."""

    status_code: int
    content_type: str | None
    body: Any
    is_json: bool


@dataclass(frozen=True)
class AnswerCapture:
    """Captured answer-path behavior: answer text plus citation collection.

    ``order_sensitive`` records how citations should be compared:
    order-sensitive (character-for-character order, Req 7.2 for
    ``chatbot.ask``) or order-insensitive (citation *set*, Req 1.4 for the QA
    agent workflow).
    """

    answer: str
    citations: list[Any]
    order_sensitive: bool
    raw: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------


def golden_cli(
    args: Sequence[str],
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = 300.0,
) -> CliCapture:
    """Run the workflow CLI in a subprocess and capture its observable output.

    The CLI is invoked as ``python -m poc_workflow.cli --root <root> <args...>``
    so stdout/stderr are captured as raw bytes for byte-exact comparison
    (Requirement 1.2 / 6.2). ``--root`` is injected as a top-level argument
    ahead of the subcommand.

    Parameters
    ----------
    args:
        Subcommand and its arguments, e.g. ``["manifest"]`` or
        ``["ask", "query text", "--provider", "local"]``. ``--root`` must not
        be included; pass it via ``root``.
    root:
        Workspace root passed as the top-level ``--root`` argument.
    env:
        Optional environment overrides, merged on top of the current
        environment. Use this to pin non-deterministic env-backed behavior.
    cwd:
        Optional working directory for the subprocess.
    timeout:
        Subprocess timeout in seconds (``None`` disables it).
    """
    command = [sys.executable, "-m", "poc_workflow.cli", "--root", str(root), *args]
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    completed = subprocess.run(
        command,
        capture_output=True,
        cwd=str(cwd) if cwd is not None else None,
        env=run_env,
        timeout=timeout,
        check=False,
    )
    return CliCapture(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def golden_http(
    client: "TestClient",
    method: str,
    path: str,
    **kwargs: Any,
) -> HttpCapture:
    """Issue an HTTP request via a FastAPI ``TestClient`` and capture the result.

    Captures status code, content-type, and body. JSON bodies are parsed so
    that volatile fields can be stripped during comparison (Requirement 1.3);
    non-JSON bodies are captured as text and compared verbatim.
    """
    response = client.request(method.upper(), path, **kwargs)
    content_type = response.headers.get("content-type")
    is_json = bool(content_type) and "application/json" in content_type.lower()
    if is_json:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
            is_json = False
    else:
        body = response.text
    return HttpCapture(
        status_code=response.status_code,
        content_type=content_type,
        body=body,
        is_json=is_json,
    )


def golden_answer(
    fn: Callable[[], Mapping[str, Any]],
    *,
    order_sensitive: bool,
    answer_key: str = "answer",
    citations_key: str = "citations",
) -> AnswerCapture:
    """Invoke an answer-path callable and capture its answer text + citations.

    Parameters
    ----------
    fn:
        Zero-argument callable returning an answer payload mapping, e.g.
        ``lambda: ask(root, query, provider="local")``.
    order_sensitive:
        ``True`` to compare citations in order (``chatbot.ask``, Req 7.2),
        ``False`` to compare them as an order-insensitive set (QA agent
        workflow, Req 1.4).
    answer_key / citations_key:
        Keys to read the answer text and citation collection from.
    """
    result = fn()
    answer = str(result.get(answer_key, ""))
    raw_citations = result.get(citations_key) or []
    citations = list(raw_citations)
    return AnswerCapture(
        answer=answer,
        citations=citations,
        order_sensitive=order_sensitive,
        raw=dict(result),
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def strip_volatile(value: Any, ignore: frozenset[str] | set[str] = VOLATILE) -> Any:
    """Return a copy of ``value`` with all volatile keys removed recursively.

    Dictionary keys present in ``ignore`` are dropped at every depth; lists and
    tuples are walked element-wise. Scalars are returned unchanged. Tuples are
    normalized to lists so comparisons treat ordered sequences uniformly.
    """
    if isinstance(value, Mapping):
        return {
            key: strip_volatile(val, ignore)
            for key, val in value.items()
            if key not in ignore
        }
    if isinstance(value, (list, tuple)):
        return [strip_volatile(item, ignore) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    """Serialize ``value`` to a stable, comparable string (sorted keys)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Difference reporting
# ---------------------------------------------------------------------------


def _find_difference(before: Any, after: Any, path: str = "$") -> str | None:
    """Return a human-readable description of the first difference, or ``None``.

    Walks dicts (by key) and sequences (by index) to report the most specific
    location where ``before`` and ``after`` diverge.
    """
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        before_keys = set(before)
        after_keys = set(after)
        only_before = before_keys - after_keys
        if only_before:
            key = sorted(only_before)[0]
            return f"{path}: key {key!r} present in before but missing in after"
        only_after = after_keys - before_keys
        if only_after:
            key = sorted(only_after)[0]
            return f"{path}: key {key!r} present in after but missing in before"
        for key in before:
            diff = _find_difference(before[key], after[key], f"{path}.{key}")
            if diff is not None:
                return diff
        return None
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        if len(before) != len(after):
            return f"{path}: sequence length {len(before)} != {len(after)}"
        for index, (item_before, item_after) in enumerate(zip(before, after)):
            diff = _find_difference(item_before, item_after, f"{path}[{index}]")
            if diff is not None:
                return diff
        return None
    if before != after:
        return f"{path}: {before!r} != {after!r}"
    return None


def _citation_difference(
    before: list[Any],
    after: list[Any],
    *,
    order_sensitive: bool,
    ignore: frozenset[str] | set[str],
) -> str | None:
    """Describe the first citation difference under the requested ordering."""
    norm_before = [strip_volatile(item, ignore) for item in before]
    norm_after = [strip_volatile(item, ignore) for item in after]
    if order_sensitive:
        return _find_difference(norm_before, norm_after, "$.citations")
    canon_before = sorted(_canonical_json(item) for item in norm_before)
    canon_after = sorted(_canonical_json(item) for item in norm_after)
    if canon_before == canon_after:
        return None
    missing = [item for item in canon_before if item not in canon_after]
    added = [item for item in canon_after if item not in canon_before]
    parts: list[str] = []
    if len(norm_before) != len(norm_after):
        parts.append(f"count {len(norm_before)} != {len(norm_after)}")
    if missing:
        parts.append(f"missing from after: {missing}")
    if added:
        parts.append(f"unexpected in after: {added}")
    return "$.citations (set): " + "; ".join(parts)


# ---------------------------------------------------------------------------
# Equivalence assertions (zero-regression check)
# ---------------------------------------------------------------------------


def _assert_cli_equivalent(before: CliCapture, after: CliCapture) -> None:
    mismatches: list[str] = []
    if before.exit_code != after.exit_code:
        mismatches.append(f"exit_code: {before.exit_code} != {after.exit_code}")
    if before.stdout != after.stdout:
        mismatches.append(
            "stdout bytes differ:\n"
            f"  before={before.stdout_text!r}\n  after={after.stdout_text!r}"
        )
    if before.stderr != after.stderr:
        mismatches.append(
            "stderr bytes differ:\n"
            f"  before={before.stderr_text!r}\n  after={after.stderr_text!r}"
        )
    if mismatches:
        raise AssertionError(
            "CLI behavior regression detected:\n" + "\n".join(mismatches)
        )


def _assert_http_equivalent(
    before: HttpCapture,
    after: HttpCapture,
    *,
    ignore: frozenset[str] | set[str],
) -> None:
    mismatches: list[str] = []
    if before.status_code != after.status_code:
        mismatches.append(
            f"status_code: {before.status_code} != {after.status_code}"
        )
    if before.content_type != after.content_type:
        mismatches.append(
            f"content_type: {before.content_type!r} != {after.content_type!r}"
        )
    body_diff = _find_difference(
        strip_volatile(before.body, ignore),
        strip_volatile(after.body, ignore),
        "$.body",
    )
    if body_diff is not None:
        mismatches.append(body_diff)
    if mismatches:
        raise AssertionError(
            "HTTP behavior regression detected:\n" + "\n".join(mismatches)
        )


def _assert_answer_equivalent(
    before: AnswerCapture,
    after: AnswerCapture,
    *,
    ignore: frozenset[str] | set[str],
) -> None:
    if before.order_sensitive != after.order_sensitive:
        raise ValueError(
            "Cannot compare AnswerCaptures with mismatched order_sensitive flags: "
            f"{before.order_sensitive} vs {after.order_sensitive}"
        )
    mismatches: list[str] = []
    if before.answer != after.answer:
        mismatches.append(
            "answer text differs:\n"
            f"  before={before.answer!r}\n  after={after.answer!r}"
        )
    citation_diff = _citation_difference(
        before.citations,
        after.citations,
        order_sensitive=before.order_sensitive,
        ignore=ignore,
    )
    if citation_diff is not None:
        mismatches.append(citation_diff)
    if mismatches:
        raise AssertionError(
            "Answer-path behavior regression detected:\n" + "\n".join(mismatches)
        )


def assert_equivalent(
    before: Any,
    after: Any,
    *,
    ignore: frozenset[str] | set[str] = VOLATILE,
) -> None:
    """Assert ``after`` preserves the observable behavior captured in ``before``.

    Dispatches on the capture type:

    - ``CliCapture`` — byte-exact exit code + stdout + stderr (``ignore`` is not
      applied; CLI comparison is byte-for-byte per Req 1.2 / 6.2).
    - ``HttpCapture`` — exact status + content-type, body compared minus
      volatile fields (Req 1.3).
    - ``AnswerCapture`` — exact answer text, citations compared order-sensitively
      or as a set per the capture's ``order_sensitive`` flag (Reqs 1.4, 7.2).
    - any other payload (dict / list / scalar) — compared minus volatile fields
      (Req 1.5, e.g. persisted records).

    Raises ``AssertionError`` with a difference description on any regression.
    """
    if isinstance(before, CliCapture) and isinstance(after, CliCapture):
        _assert_cli_equivalent(before, after)
        return
    if isinstance(before, HttpCapture) and isinstance(after, HttpCapture):
        _assert_http_equivalent(before, after, ignore=ignore)
        return
    if isinstance(before, AnswerCapture) and isinstance(after, AnswerCapture):
        _assert_answer_equivalent(before, after, ignore=ignore)
        return
    if type(before) is not type(after) and not (
        isinstance(before, Mapping) and isinstance(after, Mapping)
    ):
        raise AssertionError(
            "Cannot compare mismatched capture/payload types: "
            f"{type(before).__name__} vs {type(after).__name__}"
        )
    diff = _find_difference(
        strip_volatile(before, ignore),
        strip_volatile(after, ignore),
    )
    if diff is not None:
        raise AssertionError("Behavior regression detected:\n" + diff)
