"""Characterization (golden) test harness for the complex-code-decomposition effort.

Captures and compares the ``Observable_Behavior`` of a hotspot before and after
decomposition so that any ``Behavior_Regression`` is detected automatically.

See ``harness.py`` for implementation and the design doc at
``.kiro/specs/complex-code-decomposition/design.md`` (Component 2).
"""

from __future__ import annotations

from .harness import (
    VOLATILE,
    AnswerCapture,
    CliCapture,
    HttpCapture,
    assert_equivalent,
    golden_answer,
    golden_cli,
    golden_http,
    strip_volatile,
)

__all__ = [
    "VOLATILE",
    "AnswerCapture",
    "CliCapture",
    "HttpCapture",
    "assert_equivalent",
    "golden_answer",
    "golden_cli",
    "golden_http",
    "strip_volatile",
]
