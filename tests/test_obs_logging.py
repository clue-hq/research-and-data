"""M0.5: the redacting log filter masks secrets without breaking formatting."""

from __future__ import annotations

import logging

from clue_obs.otel import RedactingFilter, get_logger


def _record(msg: str, args: object) -> logging.LogRecord:
    return logging.LogRecord("clue_research.x", logging.INFO, "f.py", 1, msg, args, None)  # type: ignore[arg-type]


def test_redacting_filter_masks_secret_string_arg() -> None:
    record = _record("calling api with %s", ("sk-live-secret-abcdef0123",))
    assert RedactingFilter().filter(record) is True
    rendered = record.getMessage()
    assert "***REDACTED***" in rendered
    assert "sk-live" not in rendered


def test_redacting_filter_preserves_non_secret_and_numeric_args() -> None:
    record = _record("count=%d label=%s", (5, "hello"))
    RedactingFilter().filter(record)
    assert record.getMessage() == "count=5 label=hello"  # %d still works; benign str kept


def test_get_logger_is_namespaced() -> None:
    assert get_logger("discovery").name == "clue_research.discovery"
