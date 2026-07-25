"""Log mode + format enums, in their own module so leaf processors
(``truncate``) can import them without pulling in ``config`` (which imports the
processors — avoiding an import cycle)."""

from __future__ import annotations

from enum import StrEnum


class LogMode(StrEnum):
    """How much detail reaches the console.

    ``INFO``  — lifecycle events, durations, codes; payloads truncated
                (~400 chars).
    ``DEBUG`` — every detail plus callsite (file:line) on every event, no
                truncation. Debug never means "leak secrets" — redaction is
                mode-independent (``redact``).
    """

    INFO = "info"
    DEBUG = "debug"

    @classmethod
    def coerce(cls, value: object, default: LogMode | None = None) -> LogMode:
        """Lenient parse: a str/enum → LogMode; unknown/None → ``default``
        (INFO unless overridden)."""
        fallback = default or cls.INFO
        if value is None:
            return fallback
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return fallback


class LogFormat(StrEnum):
    """Console renderer selection. File/run handlers are always JSON."""

    CONSOLE = "console"
    JSON = "json"

    @classmethod
    def coerce(cls, value: object, default: LogFormat) -> LogFormat:
        if value is None:
            return default
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default
