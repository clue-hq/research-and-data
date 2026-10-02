"""The ONE place that calls ``structlog.configure`` and wires the stdlib bridge.

``setup()`` is idempotent — calling it again tears down the handlers it
previously installed and rebuilds cleanly, so a second call with a different
mode/format simply replaces the first. Nothing else in the codebase configures
structlog or builds a formatter; every entrypoint acquires loggers via
``get_logger``.

Env defaults (``CLUE_LOG_MODE`` / ``CLUE_LOG_FORMAT``) are read only when the
matching argument is ``None``; an explicit argument always wins (so a CLI can
force ``debug`` regardless of the environment).
"""

from __future__ import annotations

import contextlib
import logging
import sys
from os import environ
from pathlib import Path
from typing import Any

import structlog

from clue_obs.config_types import LogFormat, LogMode
from clue_obs.processors import build_processor_formatter, build_renderer, build_shared_processors

# Attribute stamped on the stdlib handlers this module owns, so idempotent
# reconfiguration only ever removes ITS OWN handlers (never a foreign one).
_OWNED = "_clue_obs_handler"

# Attribute stamped on the ROOT CONSOLE handler by every cooperating obs
# configurator in the process, whichever package it lives in.
#
# Intra-package idempotency (``_OWNED``) is not enough, because two obs modules
# ship in one process: this one and ``py_lumen_obs`` (the design subsystem's,
# at ``subsystems/clue-design/packages/py-lumen-obs``). Each used to strip only
# its own marker, so both consoles ended up on the root logger and EVERY line
# in the design fleet worker's log was written twice (measured: 6021 lines,
# 3391 unique). The second one arrives silently — importing ``lumen_api.main``
# for a design job runs its module-scope ``app = create_app()``, which calls
# ``py_lumen_obs.configure()``.
#
# So the root console is a single shared slot: last configurator wins, and
# there is exactly one. The string is duplicated verbatim in the sibling
# package rather than imported, because the design subsystem and the platform
# libs deliberately share no imports; keep the two literals in step.
#
# Scoped to the CONSOLE on purpose. Run-file handlers stay private to whoever
# attached them (they carry only ``_OWNED``), so reconfiguring the console
# never detaches another package's run trace — no event is lost, it just stops
# being written twice.
_ROOT_CONSOLE_OWNED = "_obs_root_console_handler"
# Process-local filters registered by cooperating console owners survive setup.
_ROOT_CONSOLE_FILTERS = "_obs_root_console_filters"

_ENV_MODE = "CLUE_LOG_MODE"
_ENV_FORMAT = "CLUE_LOG_FORMAT"


def _resolve_mode(mode: LogMode | str | None) -> LogMode:
    if mode is not None:
        return LogMode.coerce(mode)
    return LogMode.coerce(environ.get(_ENV_MODE))


def _resolve_format(fmt: LogFormat | str | None) -> LogFormat:
    if fmt is not None:
        return LogFormat.coerce(fmt, LogFormat.CONSOLE)
    env = environ.get(_ENV_FORMAT)
    if env:
        return LogFormat.coerce(env, LogFormat.CONSOLE)
    # No explicit choice: colour console for a TTY, machine JSON otherwise.
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
            with contextlib.suppress(Exception):
                handler.close()


def setup(
    mode: LogMode | str | None = None,
    fmt: LogFormat | str | None = None,
    run_log_path: Path | str | None = None,
) -> None:
    """Configure structlog + the stdlib root bridge. Idempotent; call once per
    entrypoint (api, fleet worker, CLI/script).

    Args:
        mode: ``info`` (truncated lifecycle events) or ``debug`` (every detail +
            callsite). ``None`` → ``CLUE_LOG_MODE`` → ``info``.
        fmt: ``console`` (ANSI) or ``json`` for the console handler. ``None`` →
            ``CLUE_LOG_FORMAT`` → console when stdout is a TTY else json. The
            run-file handler is ALWAYS JSON regardless.
        run_log_path: optional path to a per-run JSONL file. It receives
            full-detail events (never truncated, mode-independent) — the
            console truncates; the run file never does (Doc R §4 sinks rule).
    """
    resolved_mode = _resolve_mode(mode)
    resolved_fmt = _resolve_format(fmt)

    # Native structlog side: shared pre-chain, then hand off to stdlib.
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            *build_shared_processors(resolved_mode),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # False so a later reconfigure actually takes effect on existing loggers.
        cache_logger_on_first_use=False,
    )

    root = logging.getLogger()
    _remove_owned_handlers(root)

    # Console handler honours the mode (truncates at info). The run file always
    # gets full detail, so the ROOT must let DEBUG records through whenever a
    # run file is attached (or mode is debug); otherwise stay at INFO.
    attach_file = run_log_path is not None
    capture_debug = resolved_mode is LogMode.DEBUG or attach_file
    root.setLevel(logging.DEBUG if capture_debug else logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if resolved_mode is LogMode.DEBUG else logging.INFO)
    console.setFormatter(
        build_processor_formatter(
            resolved_mode,
            truncate=True,
            renderer=build_renderer(resolved_fmt),
        )
    )
    setattr(console, _OWNED, True)  # noqa: B010 — dynamic ownership marker
    setattr(console, _ROOT_CONSOLE_OWNED, True)  # noqa: B010 — shared console slot
    for event_filter in getattr(root, _ROOT_CONSOLE_FILTERS, ()):
        console.addFilter(event_filter)
    root.addHandler(console)

    if run_log_path is not None:
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
        setattr(file_handler, _OWNED, True)  # noqa: B010
        root.addHandler(file_handler)


def get_logger(name: str | None = None, **initial_values: Any) -> Any:
    """Acquire a structlog logger. The single entry point every component uses
    instead of ``logging.getLogger`` / building its own logger."""
    return structlog.get_logger(name, **initial_values)


__all__ = ["LogFormat", "LogMode", "get_logger", "setup"]
