"""`log_span` — one span, three events, a duration.

Wrap any unit of work (a helper call, a tool body, an LLM call) and get a
matched pair of structured events:

* ``<name>_started``   — emitted on entry, with the caller's fields;
* ``<name>_completed`` — on success, with ``duration_ms``;
* ``<name>_failed``    — on exception, with ``duration_ms`` + ``exc_info`` (the
  exception then re-raises unchanged).

Because it is a ``contextmanager``, the SAME object works both as a ``with``
block and as a ``@decorator`` — structlog's contextvars flow through either way.
The unmatched ``<name>_started`` with no ``completed`` is exactly the forensic
signature of a stuck call (the silent-hang black box the plan calls out).
"""
from __future__ import annotations

import contextlib
import time
from typing import Any, Iterator

from .config import get_logger


@contextlib.contextmanager
def log_span(name: str, logger: Any = None, **fields: Any) -> Iterator[Any]:
    """Emit ``{name}_started`` / ``{name}_completed`` (or ``{name}_failed``)
    around a block, stamping ``duration_ms``. Usable as a context manager or a
    decorator.

    Args:
        name: span name; event names are ``f"{name}_started"`` etc.
        logger: a structlog logger to emit through; defaults to a span logger.
        **fields: extra structured fields attached to every span event.
    """
    log = logger if logger is not None else get_logger("lumen_obs.span")
    start = time.perf_counter()
    log.info(f"{name}_started", **fields)
    try:
        yield log
    except BaseException as exc:  # noqa: BLE001 — measure + annotate, then re-raise
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        log.error(
            f"{name}_failed",
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            exc_info=True,
            **fields,
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        log.info(f"{name}_completed", duration_ms=duration_ms, **fields)
