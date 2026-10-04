"""``log_span`` — one span, three events, a duration.

Wrap any unit of work (a tool body, a resolver call, an LLM call) and get a
matched pair of structured events:

* ``<name>_started``   — emitted on entry, with the caller's fields;
* ``<name>_completed`` — on success, with ``duration_ms``;
* ``<name>_failed``    — on exception, with ``duration_ms`` + ``exc_info``
  (the exception then re-raises unchanged). An exception the caller lists as
  ``expected`` (a refusal it handles, such as a tool precondition) is logged at
  warning with its message and no traceback, so Sentry's logging integration,
  which reports error and above, does not page on it.

The unmatched ``<name>_started`` with no ``completed`` is exactly the forensic
signature of a stuck call (Doc R §4: a ``*_started`` with no completion is hang
forensics — havana's silent-hour lesson).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import Any

from clue_obs.config import get_logger


@contextlib.contextmanager
def log_span(
    name: str,
    logger: Any = None,
    *,
    expected: tuple[type[BaseException], ...] = (),
    **fields: Any,
) -> Iterator[Any]:
    """Emit ``{name}_started`` / ``{name}_completed`` (or ``{name}_failed``)
    around a block, stamping ``duration_ms``. Usable as a context manager or a
    decorator. ``expected`` exceptions fail at warning, not error."""
    log = logger if logger is not None else get_logger("clue_obs.span")
    start = time.perf_counter()
    log.info(f"{name}_started", **fields)
    try:
        yield log
    except expected as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        log.warning(
            f"{name}_failed",
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
            **fields,
        )
        raise
    except BaseException as exc:
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
