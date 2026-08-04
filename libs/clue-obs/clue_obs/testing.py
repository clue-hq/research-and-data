"""Capture structured events for pytest assertions.

``capture_events`` configures obs for the duration of a ``with`` block and adds
a capture handler that mirrors the CONSOLE path exactly — same shared chain,
same redaction, same mode-aware truncation — then records each final event dict
for assertions. Because it is a real root stdlib handler, events from plain
``logging.getLogger`` records flow through the bridge and are captured too.

On exit the original root-logger state is fully restored (handlers, level) and
any obs file handler is closed, so tests stay isolated.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import structlog

from clue_obs.config import _resolve_mode, setup
from clue_obs.config_types import LogFormat, LogMode
from clue_obs.processors import build_processor_formatter


class LogCapture:
    """Collected events, with a few assertion conveniences."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def events(self, name: str | None = None) -> list[dict[str, Any]]:
        if name is None:
            return list(self.entries)
        return [e for e in self.entries if e.get("event") == name]

    def event_names(self) -> list[Any]:
        return [e.get("event") for e in self.entries]

    def has(self, name: str) -> bool:
        return any(e.get("event") == name for e in self.entries)

    def first(self, name: str) -> dict[str, Any] | None:
        for e in self.entries:
            if e.get("event") == name:
                return e
        return None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.entries)


class _CaptureHandler(logging.Handler):
    """Runs its ProcessorFormatter for its capture side-effect, discards output."""

    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.format(record)
        except Exception:  # pragma: no cover — defensive
            self.handleError(record)


def _make_capture_handler(capture: LogCapture, mode: LogMode) -> _CaptureHandler:
    def renderer(logger: Any, method_name: str, event_dict: Any) -> str:
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
    saved_disabled = {
        name: logger.disabled
        for name, logger in logging.root.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }

    # Alembic's stdlib ``fileConfig`` disables loggers that its config does not name. A capture
    # block is an isolated test logging environment, so revive existing loggers for the duration
    # and restore every flag afterwards. Without this, results depend on whether a migration test
    # happened to run earlier in the same pytest process.
    for logger_entry in logging.root.manager.loggerDict.values():
        if isinstance(logger_entry, logging.Logger):
            logger_entry.disabled = False

    setup(mode=resolved_mode, fmt=fmt, run_log_path=run_log_path)

    capture = LogCapture()
    handler = _make_capture_handler(capture, resolved_mode)
    root.addHandler(handler)
    try:
        yield capture
    finally:
        for h in list(root.handlers):
            if getattr(h, "_clue_obs_handler", False) or h is handler:
                with contextlib.suppress(Exception):
                    h.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for name, disabled in saved_disabled.items():
            restored_logger = logging.root.manager.loggerDict.get(name)
            if isinstance(restored_logger, logging.Logger):
                restored_logger.disabled = disabled
        structlog.reset_defaults()
