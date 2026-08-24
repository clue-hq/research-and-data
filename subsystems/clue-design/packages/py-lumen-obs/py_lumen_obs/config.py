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
from pathlib import Path
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
# attached them (they carry only ``_OWNED``), so the harness's per-run
# ``run.jsonl`` survives a foreign reconfigure — no event is lost, it just
# stops being written twice.
_ROOT_CONSOLE_OWNED = "_obs_root_console_handler"

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
    for handler in list(root.handlers):
        if getattr(handler, _OWNED, False) or getattr(handler, _ROOT_CONSOLE_OWNED, False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


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
    root.addHandler(console)

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
        root.addHandler(file_handler)


def get_logger(name: str | None = None, **initial_values: Any) -> Any:
    """Acquire a structlog logger. The single entry point every app uses instead
    of ``logging.getLogger`` / building its own logger."""
    return structlog.get_logger(name, **initial_values)


__all__ = ["configure", "get_logger", "LogMode", "LogFormat"]
