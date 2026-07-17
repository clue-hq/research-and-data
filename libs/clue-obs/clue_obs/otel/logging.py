"""Structured logging integrated with the M0.4 redaction helper (M0.5).

A :class:`RedactingFilter` scrubs every log record's message and string arguments through the
``config`` redaction helper, so a secret-shaped value (a key, a DSN with credentials, an opaque
token) never reaches a log line — the log half of "no secret/raw-source-excerpt ever escapes"
(the span half lives in :mod:`clue_obs.otel.attributes`). Non-string args are passed through
untouched so ``%d``/``%f`` formatting still works.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from clue_config import redact

_ROOT_LOGGER = "clue_research"


class RedactingFilter(logging.Filter):
    """Masks secret-shaped values in a log record's message and string args (in place)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in args)
        elif isinstance(args, Mapping):
            record.args = {k: (redact(v) if isinstance(v, str) else v) for k, v in args.items()}
        return True


def configure_logging(
    level: int = logging.INFO, *, logger_name: str = _ROOT_LOGGER
) -> logging.Logger:
    """Configure the ``clue_research`` logger with a redacting, structured handler (idempotent)."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    logger.handlers.clear()  # idempotent reconfigure
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """A child logger under the ``clue_research`` namespace (inherits the redacting handler)."""
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}")
