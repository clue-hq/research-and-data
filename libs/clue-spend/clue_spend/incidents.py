"""Provider incidents: the durable record that a provider stopped serving us, and the two
Sentry events per incident (design 2026-09-16 §3.3; moved here from ``clue_api`` by the design of
2026-10-31 so the design subsystem records through the same code).

Writers: the shared ledger drain (every spend scope in every subsystem), the chat turn's
model-call handler, and the start-up key check (``clue_spend.key_check``). The partial unique
index ``provider_incident_one_open`` is the open-once rule; the process whose insert returns a
row fires the open event, the process whose close returns rows fires the close event. Nothing here
may raise into the call it observes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import sentry_sdk
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core.provider_failures import ProviderFailure
from clue_obs import get_logger
from clue_obs.sentry import sentry_is_installed

__all__ = [
    "FAILURE_THRESHOLD",
    "FAILURE_WINDOW",
    "OpenIncident",
    "incident_sentence",
    "open_incidents",
    "provider_display",
    "reason_words",
    "record_failure",
    "record_success",
    "send_unsent",
]

log = get_logger("clue_spend.incidents")

#: A failure (429, 5xx, timeout) opens an incident only when the provider has failed this many
#: times inside the window — the caller's own retries absorb a single fault. Refusals open on the
#: first sight; a refusal is a decision, not a fault. The count comes from the durable ledgers
#: below and from nowhere else (ruling PI-4): every writer records its own row before it calls
#: :func:`record_failure`, so the query already sees the failure being recorded.
FAILURE_THRESHOLD = 3
FAILURE_WINDOW = timedelta(minutes=5)

_DISPLAY = {
    "openrouter": "Model provider",
    "openrouter_design": "Design model provider",
    "exa": "Discovery provider",
    "exa_websets": "Discovery provider",
    "live_http": "Website fetch",
    "pdl": "People Data Labs",
    "deepgram": "Transcription provider",
    "gemini": "Media model provider",
    "adyntel": "Ad library",
    "brandfetch": "Logo provider",
    "composio": "CRM connector",
    "cloudflare": "Custom domains",
    "clerk": "Sign-in provider",
    "youtube_data": "YouTube",
    "podcast_index": "Podcast Index",
    "ai_ark": "Contact data provider",
}
_REASON_WORDS = {
    "credits_exhausted": "credits exhausted",
    "key_limit": "key limit exceeded",
    "auth_invalid": "API key rejected",
    "account_suspended": "account suspended",
    "quota_exhausted": "quota used up",
    "key_missing": "API key missing",
    "rate_limited": "rate limited",
    "server_error": "server errors",
    "timeout": "timeouts",
}
_SURFACE_WORDS = {
    "research_job": ("research job", "research jobs"),
    "display_section": ("overview section", "overview sections"),
    "chat_turn": ("chat turn", "chat turns"),
    "discovery": ("discovery call", "discovery calls"),
    "onboarding": ("onboarding call", "onboarding calls"),
}


def _provider_for_env(env_name: str) -> str | None:
    try:
        from clue_spend.key_check import provider_for_env  # lazy: key_check imports this module
    except ImportError:
        return None
    return provider_for_env(env_name)


def provider_display(provider: str) -> str:
    """A provider id's display name. A missing-key incident is named ``<role>:<ENV_NAME>``
    (``worker:PDL_API_KEY``) and reads as "People Data Labs key PDL_API_KEY (worker)"."""
    role, sep, env_name = provider.partition(":")
    if sep:
        owner = _provider_for_env(env_name)
        named = f"{_DISPLAY.get(owner, owner)} key {env_name}" if owner else env_name
        return f"{named} ({role})"
    return _DISPLAY.get(provider, provider)


def reason_words(reason: str) -> str:
    return _REASON_WORDS.get(reason, reason.replace("_", " "))


@dataclass(frozen=True)
class OpenIncident:
    incident_id: UUID
    provider: str
    kind: str
    reason: str
    opened_at: datetime
    failure_count: int
    sample_message: str
    surfaces: dict[str, int]
    notified: bool


_INSERT = text(
    """
    INSERT INTO provider_incident (incident_id, provider, kind, reason, opened_at, last_failure_at,
        failure_count, sample_message, surfaces_json, workspaces_json)
    VALUES (:id, :provider, :kind, :reason, :now, :now, :count, :message,
        CAST(:surfaces AS jsonb), CAST(:workspaces AS jsonb))
    ON CONFLICT (provider, reason) WHERE closed_at IS NULL DO NOTHING
    RETURNING incident_id
    """
)
_INCREMENT = text(
    """
    UPDATE provider_incident
       SET failure_count = failure_count + 1,
           last_failure_at = :now,
           surfaces_json = surfaces_json || jsonb_build_object(CAST(:surface AS text),
               COALESCE((surfaces_json ->> CAST(:surface AS text))::int, 0) + 1),
           workspaces_json = CASE
               WHEN CAST(:workspace AS text) IS NULL
                    OR workspaces_json ? CAST(:workspace AS text)
               THEN workspaces_json
               ELSE workspaces_json || to_jsonb(CAST(:workspace AS text)) END
     WHERE provider = :provider AND reason = :reason AND closed_at IS NULL
    RETURNING incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
              surfaces_json, sentry_open_event_id
    """
)
_SELECT_OPEN = text(
    """
    SELECT incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
           surfaces_json, sentry_open_event_id
      FROM provider_incident
     WHERE closed_at IS NULL
       AND (CAST(:all AS boolean) OR provider = ANY(CAST(:providers AS text[])))
     ORDER BY opened_at
    """
)
_SELECT_ONE = text(
    """
    SELECT incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
           surfaces_json, sentry_open_event_id
      FROM provider_incident
     WHERE incident_id = :id
    """
)
_CLOSE = text(
    """
    UPDATE provider_incident SET closed_at = :now
     WHERE provider = :provider AND closed_at IS NULL
    RETURNING incident_id, provider, kind, reason, opened_at, failure_count, sample_message,
              surfaces_json, sentry_open_event_id
    """
)
_STAMP_EVENT = text(
    "UPDATE provider_incident "
    "SET sentry_open_event_id = COALESCE(sentry_open_event_id, CAST(:open_id AS text)), "
    "    sentry_close_event_id = COALESCE(sentry_close_event_id, CAST(:close_id AS text)) "
    "WHERE incident_id = :id"
)
#: Recent classified failures for one provider, from the two ledgers that already exist: the
#: ARV2 provider ledger (Task 3 stamps ``extras_json.provider_failure``) and the chat turn's
#: model-call receipts (Task 5 stamps ``provider_failed:`` codes).
_RECENT_FAILURES = text(
    """
    SELECT (SELECT count(*) FROM provider_call_ledger
             WHERE phase = 'result' AND recorded_at > :since
               -- A row may name the incident it belongs to (design rows stay 'openrouter' for
               -- the cost views but belong to 'openrouter_design').
               AND COALESCE(extras_json -> 'provider_failure' ->> 'provider',
                            extras_json ->> 'incident_provider', provider) = :provider
               AND extras_json -> 'provider_failure' ->> 'kind' = 'failure')
         + (SELECT count(*) FROM agent_model_call
             WHERE status = 'failed' AND started_at > :since
               AND error_code LIKE 'provider_failed:' || CAST(:provider AS text) || ':%')
    """
)


def _incident(row: Any) -> OpenIncident:
    surfaces = (
        row.surfaces_json
        if isinstance(row.surfaces_json, dict)
        else json.loads(row.surfaces_json or "{}")
    )
    return OpenIncident(
        incident_id=row.incident_id,
        provider=row.provider,
        kind=row.kind,
        reason=row.reason,
        opened_at=row.opened_at,
        failure_count=row.failure_count,
        sample_message=row.sample_message,
        surfaces={str(k): int(v) for k, v in surfaces.items()},
        notified=row.sentry_open_event_id is not None,
    )


def _sentry_event(
    title: str, *, level: Literal["error", "info"], incident: OpenIncident
) -> str | None:
    if not sentry_is_installed():
        return None
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("provider", incident.provider)
        scope.set_tag("reason", incident.reason)
        scope.set_tag("kind", incident.kind)
        if level == "error":
            # The Sentry alert rule that emails the founders matches this tag (design 2026-10-31).
            scope.set_tag("alert", "provider")
        scope.fingerprint = [
            "provider-incident",
            incident.provider,
            incident.reason,
            incident.opened_at.isoformat(),
        ]
        scope.set_extra("failure_count", incident.failure_count)
        scope.set_extra("surfaces", incident.surfaces)
        scope.set_extra("sample_message", incident.sample_message)
        return sentry_sdk.capture_message(title, level=level)


def _surface_breakdown(surfaces: dict[str, int]) -> str:
    parts = []
    # Worst surface first; equal counts keep the order the incident's own jsonb carries.
    for surface, count in sorted(surfaces.items(), key=lambda item: -item[1]):
        one, many = _SURFACE_WORDS.get(surface, (surface, surface + "s"))
        parts.append(f"{count} {one if count == 1 else many}")
    return ", ".join(parts)


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def incident_sentence(
    *,
    provider: str,
    kind: str,
    reason: str,
    since: datetime,
    affected: int | None,
    unit: str,
    notified: bool,
) -> str:
    verb = "refused" if kind == "refusal" else "failing"
    sentence = f"{provider_display(provider)} {verb}: {reason_words(reason)}. Since {since:%H:%M}"
    if affected:
        sentence += f", {affected} {unit} affected"
    sentence += "."
    if notified:
        sentence += " Clue has been notified."
    return sentence


async def _send_open_event(conn: AsyncConnection, incident: OpenIncident) -> str | None:
    verb = "refused" if incident.kind == "refusal" else "failing"
    title = f"{provider_display(incident.provider)} {verb}: {reason_words(incident.reason)}"
    event_id = _sentry_event(title, level="error", incident=incident)
    if event_id is not None:
        await conn.execute(
            _STAMP_EVENT,
            {"open_id": event_id, "close_id": None, "id": incident.incident_id},
        )
    return event_id


async def record_failure(
    conn: AsyncConnection,
    failure: ProviderFailure,
    *,
    surface: str,
    workspace_id: str | None,
    now: datetime,
) -> OpenIncident | None:
    """One classified failure. Returns the open incident it landed on, or ``None`` when none is
    open (a failure below the threshold), or on any error of its own."""
    try:
        # A savepoint: a database error in here rolls back only the incident write, never
        # the caller's own transaction (a drain's ledger rows, a key check's other rows).
        async with conn.begin_nested():
            incremented = (
                await conn.execute(
                    _INCREMENT,
                    {
                        "now": now,
                        "surface": surface,
                        "workspace": workspace_id,
                        "provider": failure.provider,
                        "reason": failure.reason,
                    },
                )
            ).first()
            if incremented is not None:
                incident = _incident(incremented)
                if not incident.notified and sentry_is_installed():
                    # The process that opened it had no Sentry: tell the founders now, once.
                    await _send_open_event(conn, incident)
                    return _incident(
                        (await conn.execute(_SELECT_ONE, {"id": incident.incident_id})).one()
                    )
                return incident
            if failure.kind == "failure":
                recent = (
                    await conn.execute(
                        _RECENT_FAILURES,
                        {"provider": failure.provider, "since": now - FAILURE_WINDOW},
                    )
                ).scalar_one()
                if int(recent) < FAILURE_THRESHOLD:
                    return None
            count = FAILURE_THRESHOLD if failure.kind == "failure" else 1
            inserted = (
                await conn.execute(
                    _INSERT,
                    {
                        "id": uuid.uuid4(),
                        "provider": failure.provider,
                        "kind": failure.kind,
                        "reason": failure.reason,
                        "now": now,
                        "count": count,
                        "message": failure.message,
                        "surfaces": json.dumps({surface: 1}),
                        "workspaces": json.dumps([workspace_id] if workspace_id else []),
                    },
                )
            ).first()
            if inserted is None:
                # Lost the race to another process: count ours onto theirs.
                again = (
                    await conn.execute(
                        _INCREMENT,
                        {
                            "now": now,
                            "surface": surface,
                            "workspace": workspace_id,
                            "provider": failure.provider,
                            "reason": failure.reason,
                        },
                    )
                ).first()
                return _incident(again) if again is not None else None
            row = (await conn.execute(_SELECT_ONE, {"id": inserted.incident_id})).one()
            incident = _incident(row)
            event_id = await _send_open_event(conn, incident)
            log.warning(
                "provider_incident.opened",
                provider=incident.provider,
                reason=incident.reason,
                kind=incident.kind,
                surface=surface,
                sentry_event_id=event_id,
            )
            return _incident((await conn.execute(_SELECT_ONE, {"id": incident.incident_id})).one())
    except Exception:
        log.exception(
            "provider_incident.recorder_failed",
            provider=failure.provider,
            reason=failure.reason,
            surface=surface,
        )
        return None


async def record_success(
    conn: AsyncConnection, provider: str, *, now: datetime
) -> tuple[OpenIncident, ...]:
    """One successful call: closes every open incident of the provider, one Sentry event each."""
    try:
        # A savepoint: a database error in here rolls back only the incident write, never
        # the caller's own transaction (a drain's ledger rows, a key check's other rows).
        async with conn.begin_nested():
            rows = (await conn.execute(_CLOSE, {"now": now, "provider": provider})).all()
            closed: list[OpenIncident] = []
            for row in rows:
                incident = _incident(row)
                title = (
                    f"{provider_display(provider)} recovered after "
                    f"{_duration(now - incident.opened_at)} — "
                    f"{incident.failure_count} calls failed "
                    f"({_surface_breakdown(incident.surfaces)})"
                )
                event_id = _sentry_event(title, level="info", incident=incident)
                if event_id is not None:
                    await conn.execute(
                        _STAMP_EVENT,
                        {"open_id": None, "close_id": event_id, "id": incident.incident_id},
                    )
                log.info(
                    "provider_incident.closed",
                    provider=provider,
                    reason=incident.reason,
                    failure_count=incident.failure_count,
                    sentry_event_id=event_id,
                )
                closed.append(incident)
            return tuple(closed)
    except Exception:
        log.exception("provider_incident.recorder_failed", provider=provider, reason="close")
        return ()


async def send_unsent(conn: AsyncConnection) -> int:
    """Send the open event of every open incident no process could send (it was opened where
    Sentry was not installed). Returns how many were sent; never raises."""
    if not sentry_is_installed():
        return 0
    sent = 0
    for incident in await open_incidents(conn):
        if incident.notified:
            continue
        try:
            async with conn.begin_nested():
                if await _send_open_event(conn, incident) is not None:
                    sent += 1
        except Exception:
            log.exception("provider_incident.recorder_failed", reason="send_unsent")
    return sent


async def open_incidents(
    conn: AsyncConnection, *, providers: Iterable[str] | None = None
) -> tuple[OpenIncident, ...]:
    try:
        # A savepoint: a database error in here rolls back only the incident write, never
        # the caller's own transaction (a drain's ledger rows, a key check's other rows).
        async with conn.begin_nested():
            wanted = list(providers) if providers is not None else []
            rows = (
                await conn.execute(_SELECT_OPEN, {"all": providers is None, "providers": wanted})
            ).all()
            return tuple(_incident(row) for row in rows)
    except Exception:
        log.exception("provider_incident.recorder_failed", reason="read")
        return ()
