"""Sentry at the process roots (lane 3 slice 2, R6).

Errors leave the box with our ids and a stack trace, never customer text: PII capture off, local
variables off, the secret-key redaction over the event's extras and request, and the bound run
context copied onto the tags so an error opens to its workspace, run and turn. Sentry gets no
tracing (R7: OpenTelemetry owns that). Nothing here runs unless :func:`install_sentry` was given
a DSN; :func:`capture` is then a one-liner the worker loops call beside their ``log.exception``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import sentry_sdk
from sentry_sdk.types import Event, Hint

from clue_obs.otel.install import bound_run_context
from clue_obs.redact import redact_value

__all__ = ["capture", "install_sentry", "sentry_is_installed", "warn"]

_installed = False


def _before_send(event: Event, hint: Hint) -> Event:
    del hint
    # ``Event`` is a TypedDict to the type checker; this hook reads and writes sections by name,
    # so it works over the same mapping untyped.
    fields = cast(dict[str, Any], event)
    tags = dict(fields.get("tags") or {})
    for key, value in bound_run_context().items():
        if value is not None:
            tags[key] = str(value)
    if tags:
        fields["tags"] = tags
    for section in ("extra", "contexts", "request"):
        value = fields.get(section)
        if isinstance(value, dict):
            fields[section] = redact_value(value)
    return event


def install_sentry(
    *,
    dsn: str | None,
    environment: str,
    release: str | None,
    process_name: str,
    transport: Any = None,
) -> bool:
    """Initialise the SDK with the ruled posture. Returns ``False`` (and does nothing) without a
    DSN. ``transport`` is the test seam (a stub that records envelopes)."""
    global _installed
    if dsn is None or not dsn.strip():
        return False
    sentry_sdk.init(
        dsn=dsn.strip(),
        environment=environment,
        release=release or None,
        server_name=process_name,
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0.0,
        before_send=_before_send,
        transport=transport,
    )
    _installed = True
    return True


def sentry_is_installed() -> bool:
    return _installed


def capture(exc: BaseException) -> None:
    """Report one caught exception; a no-op when Sentry is not installed."""
    if _installed:
        sentry_sdk.capture_exception(exc)


def warn(
    message: str,
    *,
    fingerprint: Sequence[str],
    tags: Mapping[str, str],
    extra: Mapping[str, object] | None = None,
) -> str | None:
    """Send one warning-level message (not an exception); a no-op when Sentry is not installed.

    ``fingerprint`` decides which Sentry issue the event groups under, so a caller that wants an
    alert per occurrence gives each occurrence its own fingerprint.
    """
    if not _installed:
        return None
    with sentry_sdk.new_scope() as scope:
        for key, tag in tags.items():
            scope.set_tag(key, tag)
        for key, detail in (extra or {}).items():
            scope.set_extra(key, detail)
        scope.fingerprint = list(fingerprint)
        return sentry_sdk.capture_message(message, level="warning")
