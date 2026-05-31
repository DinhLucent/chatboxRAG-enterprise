"""Unit tests for the characterization (golden) test harness.

Covers volatile-field normalization (``strip_volatile``) and the
type-dispatched equivalence comparison (``assert_equivalent``) for CLI, HTTP,
and answer-path captures plus the generic payload path, including the
difference reporting embedded in raised ``AssertionError`` messages.

Spec: ``.kiro/specs/complex-code-decomposition`` — Task 2.2.
Requirements: 1.3 (HTTP/body volatile stripping), 1.4 (order-insensitive
citation set), 1.5 (persisted-record volatile stripping).
"""

from __future__ import annotations

import pytest

from tests.characterization import (
    VOLATILE,
    AnswerCapture,
    CliCapture,
    HttpCapture,
    assert_equivalent,
    strip_volatile,
)


# ---------------------------------------------------------------------------
# strip_volatile — volatile-field normalization (Requirements 1.3, 1.5)
# ---------------------------------------------------------------------------


def test_strip_volatile_removes_top_level_volatile_keys() -> None:
    payload = {"answer": "hello", "latency_ms": 42, "id": "abc-123"}

    result = strip_volatile(payload)

    assert result == {"answer": "hello"}


def test_strip_volatile_preserves_non_volatile_keys() -> None:
    payload = {"answer": "hello", "score": 0.9, "department": "ops"}

    result = strip_volatile(payload)

    assert result == {"answer": "hello", "score": 0.9, "department": "ops"}


def test_strip_volatile_removes_nested_volatile_keys_in_dicts_inside_lists() -> None:
    payload = {
        "records": [
            {"name": "a", "id": 1, "created_at": "t0"},
            {"name": "b", "log_id": 7, "updated_at": "t1"},
        ],
        "run_id": "run-xyz",
    }

    result = strip_volatile(payload)

    assert result == {"records": [{"name": "a"}, {"name": "b"}]}


def test_strip_volatile_removes_deeply_nested_volatile_keys() -> None:
    payload = {
        "outer": {
            "inner": {"keep": "v", "incident_id": "i-1", "timestamp": "t"},
        },
    }

    result = strip_volatile(payload)

    assert result == {"outer": {"inner": {"keep": "v"}}}


def test_strip_volatile_normalizes_tuples_to_lists() -> None:
    payload = {"vals": ("a", "b"), "nested": [("x", "y")]}

    result = strip_volatile(payload)

    assert result == {"vals": ["a", "b"], "nested": [["x", "y"]]}
    assert isinstance(result["vals"], list)
    assert isinstance(result["nested"][0], list)


def test_strip_volatile_returns_scalars_unchanged() -> None:
    assert strip_volatile(7) == 7
    assert strip_volatile("plain") == "plain"
    assert strip_volatile(None) is None


def test_strip_volatile_honors_custom_ignore_set() -> None:
    payload = {"keep": 1, "drop_me": 2, "id": 3}

    # A custom ignore set replaces VOLATILE: only "drop_me" is removed,
    # so the normally-volatile "id" survives.
    result = strip_volatile(payload, ignore={"drop_me"})

    assert result == {"keep": 1, "id": 3}


def test_volatile_set_contains_expected_field_families() -> None:
    # Sanity check the centralized volatile set covers the design's families.
    assert {"latency_ms", "generated_at", "id", "run_id"} <= set(VOLATILE)


# ---------------------------------------------------------------------------
# AnswerCapture — order-insensitive citation set (Requirement 1.4)
# ---------------------------------------------------------------------------


def _answer(citations: list[object], *, answer: str = "the answer",
            order_sensitive: bool = False) -> AnswerCapture:
    return AnswerCapture(
        answer=answer,
        citations=list(citations),
        order_sensitive=order_sensitive,
    )


def test_answer_order_insensitive_same_set_different_order_passes() -> None:
    cite_a = {"doc": "A", "page": 1}
    cite_b = {"doc": "B", "page": 2}
    before = _answer([cite_a, cite_b])
    after = _answer([cite_b, cite_a])

    # Reordered citation set must be treated as equivalent (no raise).
    assert_equivalent(before, after)


def test_answer_order_insensitive_missing_citation_fails() -> None:
    before = _answer([{"doc": "A"}, {"doc": "B"}])
    after = _answer([{"doc": "A"}])

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_answer_order_insensitive_extra_citation_fails() -> None:
    before = _answer([{"doc": "A"}])
    after = _answer([{"doc": "A"}, {"doc": "B"}])

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_answer_order_insensitive_ignores_volatile_citation_fields() -> None:
    before = _answer([{"doc": "A", "id": "x1"}, {"doc": "B", "id": "x2"}])
    after = _answer([{"doc": "B", "id": "y2"}, {"doc": "A", "id": "y1"}])

    # Same citation set after dropping volatile ids, just reordered.
    assert_equivalent(before, after)


# ---------------------------------------------------------------------------
# AnswerCapture — order-sensitive citation comparison (Requirement 7.2)
# ---------------------------------------------------------------------------


def test_answer_order_sensitive_identical_order_passes() -> None:
    cites = [{"doc": "A"}, {"doc": "B"}]
    before = _answer(cites, order_sensitive=True)
    after = _answer(cites, order_sensitive=True)

    assert_equivalent(before, after)


def test_answer_order_sensitive_reordered_citations_fail() -> None:
    before = _answer([{"doc": "A"}, {"doc": "B"}], order_sensitive=True)
    after = _answer([{"doc": "B"}, {"doc": "A"}], order_sensitive=True)

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_answer_order_sensitive_differing_answer_text_fails() -> None:
    cites = [{"doc": "A"}]
    before = _answer(cites, answer="original", order_sensitive=True)
    after = _answer(cites, answer="changed", order_sensitive=True)

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_answer_differing_text_with_same_citation_set_fails() -> None:
    # Answer text is always compared exactly, even order-insensitively.
    before = _answer([{"doc": "A"}], answer="original")
    after = _answer([{"doc": "A"}], answer="changed")

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


# ---------------------------------------------------------------------------
# HttpCapture — status/content-type exact, body minus volatile (Req 1.3)
# ---------------------------------------------------------------------------


def _http(body: object, *, status: int = 200,
          content_type: str | None = "application/json") -> HttpCapture:
    return HttpCapture(
        status_code=status,
        content_type=content_type,
        body=body,
        is_json=True,
    )


def test_http_bodies_differing_only_by_volatile_fields_pass() -> None:
    before = _http({"result": "ok", "generated_at": "2024-01-01T00:00:00Z",
                    "id": "rec-1", "latency_ms": 10})
    after = _http({"result": "ok", "generated_at": "2025-12-31T23:59:59Z",
                   "id": "rec-2", "latency_ms": 999})

    assert_equivalent(before, after)


def test_http_real_body_value_difference_fails() -> None:
    before = _http({"result": "ok"})
    after = _http({"result": "changed"})

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_http_status_code_mismatch_fails() -> None:
    before = _http({"result": "ok"}, status=200)
    after = _http({"result": "ok"}, status=500)

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_http_content_type_mismatch_fails() -> None:
    before = _http({"result": "ok"}, content_type="application/json")
    after = _http({"result": "ok"}, content_type="text/plain")

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


# ---------------------------------------------------------------------------
# CliCapture — byte-exact exit code + stdout + stderr (Req 6.2)
# ---------------------------------------------------------------------------


def _cli(exit_code: int = 0, stdout: bytes = b"out", stderr: bytes = b"") -> CliCapture:
    return CliCapture(exit_code=exit_code, stdout=stdout, stderr=stderr)


def test_cli_identical_captures_pass() -> None:
    before = _cli(0, b'{"ok": true}\n', b"")
    after = _cli(0, b'{"ok": true}\n', b"")

    assert_equivalent(before, after)


def test_cli_stdout_byte_difference_fails() -> None:
    before = _cli(stdout=b'{"ok": true}\n')
    after = _cli(stdout=b'{"ok": false}\n')

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_cli_stderr_byte_difference_fails() -> None:
    before = _cli(stderr=b"")
    after = _cli(stderr=b"warning: deprecated\n")

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_cli_exit_code_mismatch_fails() -> None:
    before = _cli(exit_code=0)
    after = _cli(exit_code=1)

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


def test_cli_volatile_like_bytes_are_not_stripped() -> None:
    # CLI comparison is byte-for-byte; volatile-looking content still matters.
    before = _cli(stdout=b'{"latency_ms": 10}\n')
    after = _cli(stdout=b'{"latency_ms": 11}\n')

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


# ---------------------------------------------------------------------------
# Generic payload path — dict/list/scalar minus volatile (Requirement 1.5)
# ---------------------------------------------------------------------------


def test_generic_payload_differing_only_by_volatile_fields_passes() -> None:
    before = {"family": "f1", "status": "active", "updated_at": "t0"}
    after = {"family": "f1", "status": "active", "updated_at": "t9"}

    assert_equivalent(before, after)


def test_generic_payload_real_difference_fails() -> None:
    before = {"family": "f1", "status": "active"}
    after = {"family": "f1", "status": "retired"}

    with pytest.raises(AssertionError):
        assert_equivalent(before, after)


# ---------------------------------------------------------------------------
# Difference reporting — useful path/diff descriptions (Requirements 1.3-1.5)
# ---------------------------------------------------------------------------


def test_http_difference_message_includes_body_path_and_values() -> None:
    before = _http({"result": "ok"})
    after = _http({"result": "changed"})

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "HTTP behavior regression detected" in message
    assert "$.body.result" in message
    assert "'ok'" in message and "'changed'" in message


def test_http_status_difference_message_reports_status_values() -> None:
    before = _http({"result": "ok"}, status=200)
    after = _http({"result": "ok"}, status=404)

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "status_code" in message
    assert "200" in message and "404" in message


def test_cli_difference_message_reports_exit_and_stream() -> None:
    before = _cli(exit_code=0, stdout=b"hello\n")
    after = _cli(exit_code=2, stdout=b"goodbye\n")

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "CLI behavior regression detected" in message
    assert "exit_code" in message
    assert "stdout bytes differ" in message


def test_answer_difference_message_includes_citations_path() -> None:
    before = _answer([{"doc": "A"}, {"doc": "B"}], order_sensitive=True)
    after = _answer([{"doc": "B"}, {"doc": "A"}], order_sensitive=True)

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "Answer-path behavior regression detected" in message
    assert "$.citations" in message


def test_answer_set_difference_message_describes_missing_citation() -> None:
    before = _answer([{"doc": "A"}, {"doc": "B"}])
    after = _answer([{"doc": "A"}])

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "$.citations (set)" in message
    assert "missing from after" in message


def test_generic_difference_message_includes_path() -> None:
    before = {"family": "f1", "status": "active"}
    after = {"family": "f1", "status": "retired"}

    with pytest.raises(AssertionError) as excinfo:
        assert_equivalent(before, after)

    message = str(excinfo.value)
    assert "Behavior regression detected" in message
    assert "$.status" in message
    assert "'active'" in message and "'retired'" in message
