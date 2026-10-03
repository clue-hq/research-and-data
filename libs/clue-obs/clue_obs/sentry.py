"""Sentry at the process roots (lane 3 slice 2, R6).

Errors leave the box with our ids and a stack trace, never customer text: PII capture off, local
variables off, the secret-key redaction over the event's extras and request, and the bound run
context copied onto the tags so an error opens to its workspace, run and turn. Sentry gets no
tracing (R7: OpenTelemetry owns that), but every event is labelled with the OpenTelemetry trace it
happened in and a Langfuse link (2026-10-03 agent-scoped tracing spec, R5). Nothing here runs
unless :func:`install_sentry` was given a DSN; :func:`capture` is then a one-liner the worker loops
call beside their ``log.exception``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import sentry_sdk
from sentry_sdk.types import Event, Hint

from clue_obs.otel.install import bound_run_context
from clue_obs.otel.trace_ids import current_trace_ids, remembered_trace
from clue_obs.redact import redact_value

__all__ = ["capture", "install_sentry", "sentry_is_installed", "warn"]

_installed = False
_langfuse_host: str | None = None


def _event_trace(hint: Hint) -> tuple[str, str] | None:
    """The OpenTelemetry trace the event belongs to: the current span's, else the one the
    exception remembered as it left its span (the fleet worker reports after ``fleet.task``)."""
    ids = current_trace_ids()
    if ids is not None:
        return ids
    exc_info = hint.get("exc_info") if isinstance(hint, dict) else None
    if not isinstance(exc_info, tuple) or len(exc_info) != 3:
        return None
    error = exc_info[1]
    return remembered_trace(error) if isinstance(error, BaseException) else None


def _before_send(event: Event, hint: Hint) -> Event:
    # ``Event`` is a TypedDict to the type checker; this hook reads and writes sections by name,
    # so it works over the same mapping untyped.
    fields = cast(dict[str, Any], event)
    tags = dict(fields.get("tags") or {})
    for key, value in bound_run_context().items():
        if value is not None:
            tags[key] = str(value)
    for section in ("extra", "contexts", "request"):
        value = fields.get(section)
        if isinstance(value, dict):
            fields[section] = redact_value(value)
    # One trace id across tools (2026-10-03 spec, R5): the event's trace is the OpenTelemetry
    # trace the logs and Langfuse carry, not the id Sentry invents with its tracing off. Set after
    # the redaction, which would mask a 32-hex id as an opaque token.
    ids = _event_trace(hint)
    if ids is not None:
        trace_id, span_id = ids
        tags["trace_id"] = trace_id
        contexts = dict(fields.get("contexts") or {})
        contexts["trace"] = {"trace_id": trace_id, "span_id": span_id}
        if _langfuse_host is not None:
            contexts["langfuse"] = {"trace_url": f"{_langfuse_host}/trace/{trace_id}"}
        fields["contexts"] = contexts
    if tags:
        fields["tags"] = tags
    return event


def install_sentry(
    *,
    dsn: str | None,
    environment: str,
    release: str | None,
    process_name: str,
    transport: Any = None,
    langfuse_host: str | None = None,
) -> bool:
    """Initialise the SDK with the ruled posture. Returns ``False`` (and does nothing) without a
    DSN. ``transport`` is the test seam (a stub that records envelopes). With ``langfuse_host``
    every event that has a trace links to it there (``/trace/<id>`` redirects to its project)."""
    global _installed, _langfuse_host
    if dsn is None or not dsn.strip():
        return False
    host = (langfuse_host or "").strip().rstrip("/")
    _langfuse_host = host or None
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
