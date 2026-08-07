"""Capture structured events for pytest assertions.

`capture_events` configures obs for the duration of a ``with`` block and adds a
capture handler that mirrors the CONSOLE path exactly — same shared chain, same
redaction, same mode-aware truncation — then records each final event dict for
assertions. Because it is a real root stdlib handler, events from plain
``logging.getLogger`` records flow through the bridge and are captured too.

On exit the original root-logger state is fully restored (handlers, level) and
any obs file handler is closed, so tests stay isolated.

A ready-made pytest fixture is available via ``pytest_fixture()`` (imports
pytest lazily, so importing this module in production never pulls pytest in)::

    from py_lumen_obs.testing import pytest_fixture
    log_capture = pytest_fixture()

    def test_something(log_capture):
        ...
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any, Iterator

import structlog

from .config import _resolve_mode, configure
from .config_types import LogFormat, LogMode
from .processors import build_processor_formatter


class LogCapture:
    """Collected events, with a few assertion conveniences."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def events(self, name: str | None = None) -> list[dict]:
        if name is None:
            return list(self.entries)
        return [e for e in self.entries if e.get("event") == name]

    def event_names(self) -> list[str]:
        return [e.get("event") for e in self.entries]

    def has(self, name: str) -> bool:
        return any(e.get("event") == name for e in self.entries)

    def first(self, name: str) -> dict | None:
        for e in self.entries:
            if e.get("event") == name:
                return e
        return None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[dict]:
        return iter(self.entries)


class _CaptureHandler(logging.Handler):
    """Runs its ProcessorFormatter for its capture side-effect, discards output."""

    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.format(record)
        except Exception:  # pragma: no cover - defensive
            self.handleError(record)


def _make_capture_handler(capture: LogCapture, mode: LogMode) -> _CaptureHandler:
    def renderer(logger: Any, method_name: str, event_dict: dict) -> str:
        capture.entries.append(dict(event_dict))
        return str(event_dict.get("event", ""))

    formatter = build_processor_formatter(mode, truncate=True, renderer=renderer)
    handler = _CaptureHandler(formatter)
    handler.setLevel(logging.DEBUG if mode is LogMode.DEBUG else logging.INFO)
    return handler


@contextlib.contextmanager
def capture_events(
    mode: LogMode | str | None = None,
    fmt: LogFormat | str | None = LogFormat.CONSOLE,
    run_log_path: Path | str | None = None,
) -> Iterator[LogCapture]:
    """Configure obs and capture every event for the block. Restores prior
    root-logger state on exit."""
    resolved_mode = _resolve_mode(mode)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    configure(mode=resolved_mode, fmt=fmt, run_log_path=run_log_path)

    capture = LogCapture()
    handler = _make_capture_handler(capture, resolved_mode)
    root.addHandler(handler)
    try:
        yield capture
    finally:
        for h in list(root.handlers):
            if getattr(h, "_lumen_obs_handler", False) or h is handler:
                try:
                    h.close()
                except Exception:
                    pass
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.reset_defaults()


def pytest_fixture(mode: LogMode | str | None = None):
    """Return a pytest fixture yielding a :class:`LogCapture`. Call at module
    scope in a test file. Imports pytest lazily."""
    import pytest

    @pytest.fixture
    def log_capture() -> Iterator[LogCapture]:
        with capture_events(mode=mode) as cap:
            yield cap

    return log_capture
