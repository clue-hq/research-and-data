"""The ONE place that calls ``structlog.configure`` and wires the stdlib bridge.

`configure()` is idempotent — calling it again tears down the handlers it
previously installed and rebuilds cleanly, so a second call with a different
mode/format simply replaces the first. Nothing else in the codebase configures
structlog or builds a formatter; every app acquires loggers via `get_logger`.

Env defaults (``LUMEN_LOG_MODE`` / ``LUMEN_LOG_FORMAT``) are read only when the
matching argument is ``None``; an explicit argument always wins (so an L2
``cli.py`` can force ``debug`` regardless of the environment).
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Any

import structlog

from .config_types import LogFormat, LogMode
from .processors import build_processor_formatter, build_renderer, build_shared_processors

# Attribute stamped on the stdlib handlers this module owns, so idempotent
# reconfiguration only ever removes ITS OWN handlers (never a foreign one).
_OWNED = "_lumen_obs_handler"

# Attribute stamped on the ROOT CONSOLE handler by every cooperating obs
# configurator in the process, whichever package it lives in.
#
# Intra-package idempotency (``_OWNED``) is not enough, because two obs modules
# ship in one process: this one and the platform's ``clue_obs``
# (``libs/clue-obs``). Each used to strip only its own marker, so both consoles
# ended up on the root logger and EVERY line in the design fleet worker's log
# was written twice (measured: 6021 lines, 3391 unique). This module's console
# arrives silently in that process — the worker imports ``lumen_api.main`` to
# run a design job, and its module-scope ``app = create_app()`` calls
# ``configure()``.
#
# So the root console is a single shared slot: last configurator wins, and
# there is exactly one. The string is duplicated verbatim in the platform
# package rather than imported, because the design subsystem and the platform
# libs deliberately share no imports; keep the two literals in step.
#
# Scoped to the CONSOLE on purpose. Run-file handlers stay private to whoever
# attached them (legacy files carry ``_OWNED``; scoped files have their own
# marker), so a foreign console reconfigure does not detach those files.
_ROOT_CONSOLE_OWNED = "_obs_root_console_handler"
# Cooperating configurators carry these filters into replacement consoles.
# The callbacks are process-local capabilities, never subsystem imports.
_ROOT_CONSOLE_FILTERS = "_obs_root_console_filters"

# Scoped run sinks outlive a configure() call, but never the run that owns them.
# They deliberately do not carry _OWNED, whose legacy replacement semantics stay
# unchanged. The lock covers setup/teardown only, never work performed by a run.
_RUN_OWNED = "_lumen_obs_run_handler"
_CONFIG_LOCK = RLock()
_run_level_restore: tuple[int, tuple[logging.Handler, ...]] | None = None
_private_payload_context: ContextVar[bool] = ContextVar("lumen_private_payloads", default=False)
_private_run_counts: dict[str, int] = {}

_ENV_MODE = "LUMEN_LOG_MODE"
_ENV_FORMAT = "LUMEN_LOG_FORMAT"


def _resolve_mode(mode: LogMode | str | None) -> LogMode:
    if mode is not None:
        return LogMode.coerce(mode)
    return LogMode.coerce(os.environ.get(_ENV_MODE))


def _resolve_format(fmt: LogFormat | str | None) -> LogFormat:
    if fmt is not None:
        return LogFormat.coerce(fmt, LogFormat.CONSOLE)
    env = os.environ.get(_ENV_FORMAT)
    if env:
        return LogFormat.coerce(env, LogFormat.CONSOLE)
    # No explicit choice: colour console for a TTY, machine JSON otherwise.
    is_tty = False
    try:
        is_tty = bool(sys.stdout.isatty())
    except Exception:
        is_tty = False
    return LogFormat.CONSOLE if is_tty else LogFormat.JSON


def _remove_owned_handlers(root: logging.Logger) -> None:
    """Detach this module's handlers, plus ANY cooperating package's root console.

    The second clause is what keeps the process to one console handler; see
    ``_ROOT_CONSOLE_OWNED``.
    """
    owned = tuple(
        handler for handler in root.handlers
        if getattr(handler, _OWNED, False) or getattr(handler, _ROOT_CONSOLE_OWNED, False)
    )
    _update_handlers(root, remove=owned)
    for handler in owned:
        try:
            handler.close()
        except Exception:
            pass


def _update_handlers(
    root: logging.Logger,
    *,
    add: tuple[logging.Handler, ...] = (),
    remove: tuple[logging.Handler, ...] = (),
) -> None:
    # Logger.callHandlers traverses its list without a lock. Replacing the list
    # leaves an in-flight traversal stable; removeHandler() would shift another
    # run's sink behind that iterator. Use stdlib's configuration lock so this
    # read/replace also cooperates with foreign addHandler/removeHandler calls.
    logging._acquireLock()
    try:
        handlers = [handler for handler in root.handlers if handler not in remove]
        handlers.extend(handler for handler in add if handler not in handlers)
        root.handlers = handlers
    finally:
        logging._releaseLock()


class _RunFileHandler(logging.FileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        # A record can be paused in a filter when the run exits. FileHandler's
        # append mode otherwise reopens a closed stream when that record resumes.
        # Share close()'s I/O lock so no write can start after close completes.
        self.acquire()
        try:
            if not self._closed:
                super().emit(record)
        finally:
            self.release()


def configure(
    mode: LogMode | str | None = None,
    fmt: LogFormat | str | None = None,
    run_log_path: Path | str | None = None,
) -> None:
    """Configure structlog + the stdlib root bridge. Idempotent.

    Args:
        mode: ``info`` (truncated lifecycle events) or ``debug`` (every detail +
            callsite). ``None`` → ``LUMEN_LOG_MODE`` → ``info``.
        fmt: ``console`` (ANSI) or ``json`` for the console handler. ``None`` →
            ``LUMEN_LOG_FORMAT`` → console when stdout is a TTY else json. The
            run-file handler is ALWAYS JSON regardless.
        run_log_path: optional path to a per-run JSONL file. It receives
            full-detail events (never truncated, mode-independent) — the trace
            substrate the CLI viewer renders.
    """
    with _CONFIG_LOCK:
        _configure(mode, fmt, run_log_path)


def _configure(
    mode: LogMode | str | None,
    fmt: LogFormat | str | None,
    run_log_path: Path | str | None,
) -> None:
    resolved_mode = _resolve_mode(mode)
    resolved_fmt = _resolve_format(fmt)

    # Native structlog side: shared pre-chain, then hand off to stdlib.
    structlog.reset_defaults()
    structlog.configure(
        processors=build_shared_processors(resolved_mode)
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # False so a later reconfigure actually takes effect on existing loggers.
        cache_logger_on_first_use=False,
    )

    root = logging.getLogger()
    _remove_owned_handlers(root)

    # Console handler honours the mode (truncates at info). The run file always
    # gets full detail, so the ROOT must let DEBUG records through whenever a run
    # file is attached (or mode is debug); otherwise stay at INFO for zero cost.
    attach_file = run_log_path is not None
    capture_debug = resolved_mode is LogMode.DEBUG or attach_file
    root.setLevel(logging.DEBUG if capture_debug else logging.INFO)

    # "Full detail" means OUR events, not the HTTP wire. At DEBUG the openai
    # client logs every request payload verbatim — with vision turns that is
    # the base64 of every attached screenshot, measured live at 14MB per line
    # and 0.1–1.7GB of run.jsonl per turn (2026-07-29). Pin the wire-level
    # third-party loggers to INFO; their spans/usage are already captured as
    # first-class events by our own instrumentation.
    for noisy in ("openai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if resolved_mode is LogMode.DEBUG else logging.INFO)
    console.setFormatter(
        build_processor_formatter(
            resolved_mode,
            truncate=True,
            renderer=build_renderer(resolved_fmt),
        )
    )
    setattr(console, _OWNED, True)
    setattr(console, _ROOT_CONSOLE_OWNED, True)  # shared console slot
    for event_filter in getattr(root, _ROOT_CONSOLE_FILTERS, ()):
        console.addFilter(event_filter)
    _update_handlers(root, add=(console,))

    if attach_file:
        path = Path(run_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # full detail, mode-independent
        file_handler.setFormatter(
            build_processor_formatter(
                resolved_mode,
                truncate=False,  # run.jsonl is never truncated
                renderer=build_renderer(LogFormat.JSON),
            )
        )
        setattr(file_handler, _OWNED, True)
        _update_handlers(root, add=(file_handler,))

    if any(getattr(h, _RUN_OWNED, False) for h in root.handlers):
        _capture_run_level(root)


def _other_handlers(root: logging.Logger) -> tuple[logging.Handler, ...]:
    return tuple(h for h in root.handlers if not getattr(h, _RUN_OWNED, False))


def _capture_run_level(root: logging.Logger) -> None:
    global _run_level_restore
    _run_level_restore = (root.level, _other_handlers(root))
    root.setLevel(logging.DEBUG)


def _event_run_id(record: logging.LogRecord) -> Any:
    # Structlog has already merged ambient context into its event dictionary;
    # an explicit value (including None) must never fall back to another run.
    if isinstance(record.msg, dict) and "run_id" in record.msg:
        return record.msg["run_id"]
    if "run_id" in record.__dict__:
        return record.__dict__["run_id"]
    return structlog.contextvars.get_contextvars().get("run_id")


def _record_run_id(_logger, _method, event: dict) -> dict:
    # The file's payload must use the same attribution as its routing filter,
    # including stdlib dict messages and explicit extra fields.
    event["run_id"] = _event_run_id(event["_record"])
    return event


def _allow_shared_console(record: logging.LogRecord) -> bool:
    # Drop the whole event: arbitrary text, tool arguments and exception messages
    # can all echo private advice. The scoped run handler still receives it intact.
    if _private_payload_context.get():
        return False
    with _CONFIG_LOCK:
        run_id = _event_run_id(record)
        return not isinstance(run_id, str) or run_id not in _private_run_counts


@contextmanager
def _private_console_scope(run_id: str, enabled: bool) -> Iterator[None]:
    # A nested scope cannot downgrade data already private in its parent context.
    enabled = enabled or _private_payload_context.get()
    token = _private_payload_context.set(enabled)
    try:
        if enabled:
            with _CONFIG_LOCK:
                root = logging.getLogger()
                filters = getattr(root, _ROOT_CONSOLE_FILTERS, ())
                if _allow_shared_console not in filters:
                    setattr(root, _ROOT_CONSOLE_FILTERS, (*filters, _allow_shared_console))
                for handler in root.handlers:
                    if getattr(handler, _ROOT_CONSOLE_OWNED, False):
                        handler.addFilter(_allow_shared_console)
                _private_run_counts[run_id] = _private_run_counts.get(run_id, 0) + 1
        yield
    finally:
        if enabled:
            with _CONFIG_LOCK:
                remaining = _private_run_counts[run_id] - 1
                if remaining:
                    _private_run_counts[run_id] = remaining
                else:
                    del _private_run_counts[run_id]
        _private_payload_context.reset(token)
        # Keep the body-free filter registered for the process lifetime: inherited
        # callback contexts can outlive a run, and configurators may replace sinks.


@contextmanager
def run_log(
    run_id: str, path: Path | str, *, private_payloads: bool = False,
) -> Iterator[None]:
    """Capture only this run's attributed events, then detach and close the file.

    Console configuration still follows configure()'s env/default behavior. An
    unrelated configurator may raise the global threshold while a run is active;
    its choice is preserved on exit, not overwritten with our older threshold.
    Unattributed events remain on the console and never enter a run file.
    With private_payloads, the cooperating shared console is suppressed for this
    run; its removable trace retains full detail, including model echoes/errors.
    """
    global _run_level_restore
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_log requires a nonempty run_id")
    with _private_console_scope(run_id, private_payloads):
        with _CONFIG_LOCK:
            configure(mode=None)
            root = logging.getLogger()
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = _RunFileHandler(path, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            formatter = build_processor_formatter(
                _resolve_mode(None), truncate=False, renderer=build_renderer(LogFormat.JSON),
            )
            formatter.foreign_pre_chain = [
                _record_run_id, *formatter.foreign_pre_chain,
            ]
            handler.setFormatter(formatter)
            handler.addFilter(lambda record: _event_run_id(record) == run_id)
            setattr(handler, _RUN_OWNED, True)
            if not any(getattr(h, _RUN_OWNED, False) for h in root.handlers):
                _capture_run_level(root)
            _update_handlers(root, add=(handler,))
        try:
            yield
        finally:
            with _CONFIG_LOCK:
                _update_handlers(root, remove=(handler,))
                handler.close()
                if not any(getattr(h, _RUN_OWNED, False) for h in root.handlers):
                    if _run_level_restore is not None:
                        level, others = _run_level_restore
                        # Do not undo a foreign threshold/handler reconfiguration.
                        if root.level == logging.DEBUG and _other_handlers(root) == others:
                            root.setLevel(level)
                    _run_level_restore = None


def get_logger(name: str | None = None, **initial_values: Any) -> Any:
    """Acquire a structlog logger. The single entry point every app uses instead
    of ``logging.getLogger`` / building its own logger."""
    return structlog.get_logger(name, **initial_values)


__all__ = ["configure", "run_log", "get_logger", "LogMode", "LogFormat"]
