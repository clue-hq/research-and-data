"""The CRM write executor: the ``crm_write`` fleet task that sends approved changes to the CRM.

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 plan, Task 6); rulings R-7.2 (temporary
failures are retried with back-off, refusals never retried as they are, an expired connection
pauses the batch), R-7.3–R-7.5 (every Salesforce call is taken from the org's API budget first),
R-7.4 (batch calls). One task per connection (``crm-write:<connection_id>``, offered by
``propose_crm_changes`` and by the answer to a permission card) works through the connection's
proposals oldest first, until none is left to send.

For each chosen change of a proposal it:

1. re-reads what the CRM holds now. A record that changed since the card is ``skipped`` with
   ``failure_kind = 'conflict'``; a record already holding the new value is not sent again (it is
   ``succeeded`` when an earlier send of this change put it there, ``skipped`` otherwise);
2. marks the change ``sending`` (``attempts + 1``, ``sent_at``) and commits before the call, so a
   change whose status is ``succeeded``, ``failed`` or ``skipped`` is never sent again, and a
   change caught ``sending`` by a crash is resolved by step 1 on the next run;
3. sends it, in the action's batch call when it has one (changes of one group, up to the CRM's
   batch size), else one call per change, pausing ``CLUE_CRM_WRITE_MIN_INTERVAL_S`` between calls;
4. reads every change the CRM accepted back (Task 1 ruling: a CRM can report success without
   writing — Salesforce's composite call hides per-record failures, HubSpot silently ignores a
   read-only property) and marks it ``succeeded`` only when the value landed; otherwise ``failed``
   with ``failure_kind = 'not_applied'``.

A refusal fails the change with ``failure_kind`` read from the CRM's own error code
(:func:`failure_kind`) and the CRM's message kept verbatim; it is never retried. A rate limit or an
unreachable CRM puts the change back to ``queued`` and requeues the task after
``CLUE_CRM_WRITE_RETRY_BASE_S * 2**(attempt-1)`` seconds, until ``CLUE_CRM_WRITE_MAX_ATTEMPTS``
sends, then fails it ``retryable``; a rate limit met by a read counts as an attempt the same way.
An expired connection is marked expired and the proposal ``paused``; a connection Composio refuses
(401/403, or a connected account it no longer knows) pauses it without touching the connection, as
does Salesforce's API budget running out. A paused proposal resumes only on its own connection: it
is never sent on another one, because a reconnect may be to a different portal or org (founder
ruling, Task 6 review). When a new connection becomes active, the connect callback closes the
other connections' unsent proposals (:func:`close_replaced_connection_proposals`) and their chats
are asked to propose again. A finished proposal — and a paused one — wakes the chat that proposed
it (:mod:`clue_api.crm.wake`). A change whose action is no longer allowlisted fails on its own and
never blocks the queue.

Declined and replaced proposals are never picked up: only ``queued`` ones, plus ``sending`` (a run
that died) and ``paused`` (waiting on a reconnect or the budget).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    ExecuteResult,
    build_composio_gateway,
    composio_user_id,
)
from clue_api.crm.connections import CrmConnection, get_connection
from clue_api.crm.salesforce_budget import CrmBudgetExhausted, SalesforceBudget
from clue_api.crm.tools import composio_refusal
from clue_api.crm.wake import queue_crm_writes_finished_turn, queue_crm_writes_paused_turn
from clue_api.crm.write_actions import WriteActionSpec, WriteNotParsable, write_spec
from clue_api.crm.write_prepare import (
    _CRM_NAMES,
    _HUBSPOT_CONTACT_OBJECT_TYPE_ID,
    _HUBSPOT_OBJECT_TYPES,
    _SALESFORCE_SOBJECTS,
    _sf_key,
    _soql_text,
    _unwrap,
)
from clue_api.crm.writes import (
    WriteProposal,
    forget_membership_link,
    get_proposal,
    record_link,
    record_membership_link,
    same_value,
    set_proposal_status,
)
from clue_config import Secrets, Settings
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind, WorkContext, WorkResult
from clue_obs import get_logger

__all__ = [
    "CrmWriteHandler",
    "build_crm_write_handler",
    "close_replaced_connection_proposals",
    "failure_kind",
]

log = get_logger("clue_api.crm.write_executor")

_TERMINAL = ("succeeded", "failed", "skipped")
_CREATES = ("create_contact", "create_company")
_MEMBERSHIP = ("list_membership", "list_removal")
_HUBSPOT_READ = "HUBSPOT_READ_CRM_OBJECT_BY_ID"
_SOQL = "SALESFORCE_RUN_SOQL_QUERY"
#: Salesforce ids are matched in one query per this many records.
_SOQL_CHUNK = 200
_RESUMABLE = ("queued", "sending", "paused")

NOT_APPLIED_MESSAGE = "The CRM reported success but the value did not change."
NOT_CHOSEN_MESSAGE = "Not chosen on the permission card, so it was not sent."
NO_LONGER_ALLOWED_MESSAGE = "This action is no longer allowed, so it was not sent."
RECONNECTED_MESSAGE = "The CRM was reconnected or switched, so this was not sent; propose again."
UNCONFIRMED_MESSAGE = (
    "The CRM was reconnected or switched after this was sent, so Clue could not confirm it; "
    "check the CRM, and propose again if it is missing."
)

FailureKind = Literal[
    "validation_rule",
    "required_field",
    "duplicate_rule",
    "permission",
    "not_found",
    "rate_limited",
    "connection_expired",
    "conflict",
    "not_applied",
    "other",
]

# --- what the CRM's refusal means ------------------------------------------------------------

#: The CRM's own error codes (composio-api-notes.md § Writes), first match wins. A code not
#: listed here — including every refusal not yet observed — is ``other``, with the message kept.
_FAILURE_CODES: tuple[tuple[FailureKind, tuple[str, ...]], ...] = (
    ("validation_rule", ("FIELD_CUSTOM_VALIDATION_EXCEPTION",)),
    ("required_field", ("REQUIRED_FIELD_MISSING",)),
    ("duplicate_rule", ("DUPLICATES_DETECTED", "DUPLICATE_VALUE", "already has that value")),
    (
        "permission",
        (
            "INSUFFICIENT_ACCESS",  # _OR_READONLY, _ON_CROSS_REFERENCE_ENTITY
            "INVALID_FIELD_FOR_INSERT_UPDATE",
            "MISSING_SCOPES",
        ),
    ),
    ("not_found", ("OBJECT_NOT_FOUND", "ENTITY_IS_DELETED", "NOT_FOUND")),
)
#: The UI API reports a duplicate as a non-null ``duplicateRecordError``.
_DUPLICATE_RECORD = re.compile(r'"duplicateRecordError"\s*:\s*\{')


def failure_kind(message: str | None) -> FailureKind:
    """The ``crm_write.failure_kind`` of a CRM refusal, from the error code in its message."""
    if not message:
        return "other"
    if _DUPLICATE_RECORD.search(message):
        return "duplicate_rule"
    for kind, codes in _FAILURE_CODES:
        if any(code in message for code in codes):
            return kind
    return "other"


#: The longest CRM answer shown as it came, when no message can be read out of it.
_MESSAGE_MAX = 500


def _crm_text(body: Any) -> str | None:
    """The message text in a CRM's JSON error body: HubSpot's ``errors[].message`` (else its
    ``message``), Salesforce's ``message (errorCode)`` for each error. ``None`` when it has none."""
    if isinstance(body, Mapping):
        errors = body.get("errors")
        items = errors if isinstance(errors, list) else []
        texts = [
            str(item["message"])
            for item in items
            if isinstance(item, Mapping) and item.get("message")
        ]
        if not texts and body.get("message"):
            texts = [str(body["message"])]
    elif isinstance(body, list):
        texts = []
        for item in body:
            if isinstance(item, Mapping) and item.get("message"):
                code = item.get("errorCode") or item.get("statusCode")
                texts.append(f"{item['message']} ({code})" if code else str(item["message"]))
    else:
        return None
    return "; ".join(texts) or None


def crm_reply(body: str) -> tuple[str, Any]:
    """What a CRM answered, as ``(crm_message, crm_response)``: the message text to show, and
    the answer it came from — its JSON body, or the raw text when it is cut for showing. The
    response is ``None`` when the message is the whole answer (Clue's own sentences)."""
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    if isinstance(parsed, Mapping | list):
        message = _crm_text(parsed) or body
        return message[:_MESSAGE_MAX], parsed
    if len(body) > _MESSAGE_MAX:
        return body[:_MESSAGE_MAX], body
    return body, None


_TEMPORARY_CODES = ("REQUEST_LIMIT_EXCEEDED", '"category":"RATE_LIMITS"')


def _status_code(result: ExecuteResult) -> int | None:
    """The CRM's HTTP status Composio reports inside a refused call's ``data``."""
    body = result.data
    for _ in range(2):
        if isinstance(body, Mapping) and isinstance(body.get("status_code"), int):
            return int(body["status_code"])
        body = body.get("data") if isinstance(body, Mapping) else None
    return None


def _refusal_kind(result: ExecuteResult) -> FailureKind:
    """A refused call's ``failure_kind``: the CRM's 404 for a record is ``not_found``."""
    if _status_code(result) == 404:
        return "not_found"
    return failure_kind(result.error)


def _temporary(result: ExecuteResult) -> Literal["rate_limited", "unavailable"] | None:
    """A refused call that is a rate limit or an unreachable CRM rather than a refusal."""
    status = _status_code(result)
    if status == 429 or any(code in (result.error or "") for code in _TEMPORARY_CODES):
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "unavailable"
    return None


# --- the run's pieces ------------------------------------------------------------------------


class _Budget(Protocol):
    async def take_call(
        self, conn: AsyncConnection, *, connection: CrmConnection, today: date
    ) -> None: ...


class _Stop(Exception):
    """The run cannot go on: a temporary failure, an expired connection, a connection Composio
    refuses (``auth``: Clue's key, or the connected account, is not accepted) or the budget."""

    def __init__(
        self,
        kind: Literal["rate_limited", "unavailable", "connection_expired", "auth", "budget"],
        message: str,
        *,
        error: ComposioError | None = None,
        budget_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.error = error
        self.budget_code = budget_code
        #: Changes the CRM accepted in this call before it stopped (the one-at-a-time resend).
        self.accepted: list[_Write] = []


@dataclass(frozen=True)
class _Write:
    write_id: UUID
    ordinal: int
    spec: WriteActionSpec
    arguments: Mapping[str, Any]
    kind: str
    object: str
    record_ref: str | None
    list_ref: str | None
    field: str | None
    before: Any
    after: Any
    attempts: int
    #: The record a create made, stored as soon as the CRM names it (before the read-back).
    crm_id: str | None


@dataclass(frozen=True)
class _Seen:
    """What a read found for one change: its current value, or why it could not be read."""

    value: object = None
    error: str | None = None
    kind: FailureKind | None = None


@dataclass(frozen=True)
class _Outcome:
    status: Literal["succeeded", "failed", "skipped"]
    failure_kind: FailureKind | None = None
    crm_message: str | None = None
    retryable: bool | None = None
    crm_id: str | None = None
    #: The CRM's answer behind ``crm_message``, when the message is not the whole of it.
    crm_response: Any = None


def _failed(message: str, kind: FailureKind | None = None, *, retryable: bool = False) -> _Outcome:
    """A failed change. ``message`` may be a CRM's raw answer: its kind is read from the raw
    answer, the card shows its message text, and the raw answer is kept."""
    shown, response = crm_reply(message)
    return _Outcome(
        "failed",
        failure_kind=kind or failure_kind(message),
        crm_message=shown,
        retryable=retryable,
        crm_response=response,
    )


def _response_param(response: Any) -> str | None:
    return None if response is None else json.dumps(response, default=str)


def _stop_message(stop: _Stop) -> dict[str, str | None]:
    """The ``:message`` / ``:response`` of a change failed by a stop (its CRM answer, if any)."""
    message, response = crm_reply(stop.message)
    return {"message": message, "response": _response_param(response)}


def _display(value: object) -> str:
    return "nothing" if same_value(value, None) else repr(value)


class _Crm:
    """Every call to the CRM: the pause between calls, Salesforce's budget, and what a failed
    call means for the run (:class:`_Stop`) or for the change (a refused result)."""

    def __init__(
        self,
        *,
        gateway: ComposioGateway,
        budget: _Budget | None,
        connection: CrmConnection,
        version: str,
        conn_factory: ConnFactory,
        min_interval_s: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self.connection = connection
        self._gateway = gateway
        self._budget = budget
        self._version = version
        self._conn_factory = conn_factory
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._calls = 0

    @property
    def name(self) -> str:
        return _CRM_NAMES[self.connection.provider]

    async def reserve(self) -> None:
        """Wait between calls, and take the call from Salesforce's budget."""
        if self._calls and self._min_interval_s > 0:
            await self._sleep(self._min_interval_s)
        self._calls += 1
        if self.connection.provider != "salesforce":
            return
        assert self._budget is not None
        exhausted: CrmBudgetExhausted | None = None
        try:
            async with self._conn_factory() as conn:
                try:
                    await self._budget.take_call(
                        conn, connection=self.connection, today=datetime.now(UTC).date()
                    )
                except CrmBudgetExhausted as exc:
                    exhausted = exc  # keep the limits lookup counted: it reached Salesforce
        except ComposioError as exc:  # the budget's own limits lookup
            raise self._stop(exc) from exc
        if exhausted is not None:
            raise _Stop("budget", str(exhausted), budget_code=exhausted.reason_code)

    async def execute(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult:
        try:
            result = await self._gateway.execute(
                slug=slug,
                arguments=arguments,
                connected_account_id=self.connection.composio_connected_account_id,
                user_id=composio_user_id(self.connection.workspace_id),
                version=self._version,
            )
        except ComposioError as exc:
            if exc.kind == "bad_request":  # Composio's own argument check: this change only
                return ExecuteResult(False, None, exc.message)
            raise self._stop(exc) from exc
        if not result.successful:
            temporary = _temporary(result)
            if temporary is not None:
                raise _Stop(temporary, result.error or f"{self.name} is not answering.")
        return result

    async def call(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult:
        await self.reserve()
        return await self.execute(slug, arguments)

    @staticmethod
    def _stop(exc: ComposioError) -> _Stop:
        """A Composio error that is about the connection, not one change. Its 401/403 (``auth``)
        and 404 (``not_found``: the connected account or tool is gone) pause the proposal; a
        CRM's 404 for one record comes back inside a refused result instead."""
        if exc.kind in ("connection_expired", "rate_limited"):
            return _Stop(exc.kind, exc.message, error=exc)
        if exc.kind in ("auth", "not_found"):
            return _Stop("auth", exc.message, error=exc)
        return _Stop("unavailable", exc.message, error=exc)


# --- reading the CRM ------------------------------------------------------------------------


def _records(body: Any, key: str) -> list[Mapping[str, Any]] | None:
    items = body.get(key) if isinstance(body, Mapping) else None
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        return None
    return items


def _unreadable(crm: _Crm, what: str) -> _Seen:
    return _Seen(error=f"Could not read {what} from {crm.name}: its answer was not readable.")


async def _read_fields(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    """The current value of each field update's field."""
    seen: dict[UUID, _Seen] = {}
    if crm.connection.provider == "hubspot":
        by_record: dict[tuple[str, str], list[_Write]] = {}
        for write in writes:
            by_record.setdefault((write.object, str(write.record_ref)), []).append(write)
        for (object_name, record_ref), group in by_record.items():
            result = await crm.call(
                _HUBSPOT_READ,
                {
                    "objectType": _HUBSPOT_OBJECT_TYPES[object_name],
                    "objectId": record_ref,
                    "properties": sorted({str(write.field) for write in group}),
                },
            )
            body = _unwrap(result.data) if result.successful else None
            properties = body.get("properties") if isinstance(body, Mapping) else None
            for write in group:
                if not result.successful:
                    seen[write.write_id] = _Seen(
                        error=result.error or "No answer.", kind=_refusal_kind(result)
                    )
                elif not isinstance(properties, Mapping):
                    seen[write.write_id] = _unreadable(crm, f"the {object_name} {record_ref}")
                else:
                    seen[write.write_id] = _Seen(value=properties.get(str(write.field)))
        return seen
    by_object: dict[str, list[_Write]] = {}
    for write in writes:
        by_object.setdefault(write.object, []).append(write)
    for object_name, group in by_object.items():
        fields = sorted({str(write.field) for write in group})
        ids = sorted({str(write.record_ref) for write in group})
        found: dict[str, Mapping[str, Any]] = {}
        refused: dict[str, _Seen] = {}
        for start in range(0, len(ids), _SOQL_CHUNK):
            chunk = ids[start : start + _SOQL_CHUNK]
            query = (
                f"SELECT Id, {', '.join(fields)} FROM {_SALESFORCE_SOBJECTS[object_name]} "
                f"WHERE Id IN ({', '.join(_soql_text(i) for i in chunk)})"
            )
            result = await crm.call(_SOQL, {"query": query})
            records = _records(_unwrap(result.data), "records") if result.successful else None
            if records is None:
                failure = (
                    _Seen(error=result.error or "No answer.")
                    if not result.successful
                    else _unreadable(crm, f"the {object_name} records")
                )
                refused.update(dict.fromkeys(chunk, failure))
                continue
            found.update({_sf_key(record.get("Id")): record for record in records})
        for write in group:
            record_ref = str(write.record_ref)
            if record_ref in refused:
                seen[write.write_id] = refused[record_ref]
            elif _sf_key(record_ref) not in found:
                seen[write.write_id] = _Seen(
                    error=f"Salesforce has no {object_name} {record_ref} (deleted or merged?).",
                    kind="not_found",
                )
            else:
                seen[write.write_id] = _Seen(value=found[_sf_key(record_ref)].get(str(write.field)))
    return seen


async def _read_memberships(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    """Whether each membership change's record is in its list or campaign now."""
    seen: dict[UUID, _Seen] = {}
    if crm.connection.provider == "hubspot":
        by_record: dict[str, list[_Write]] = {}
        for write in writes:
            by_record.setdefault(str(write.record_ref), []).append(write)
        for record_ref, group in by_record.items():
            result = await crm.call(
                "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS",
                {"object_type_id": _HUBSPOT_CONTACT_OBJECT_TYPE_ID, "record_id": record_ref},
            )
            records = _records(_unwrap(result.data), "results") if result.successful else None
            lists = None if records is None else {str(r.get("listId")) for r in records}
            for write in group:
                if not result.successful:
                    seen[write.write_id] = _Seen(error=result.error or "No answer.")
                elif lists is None:
                    seen[write.write_id] = _unreadable(crm, f"the lists of contact {record_ref}")
                else:
                    seen[write.write_id] = _Seen(value=str(write.list_ref) in lists)
        return seen
    by_campaign: dict[str, list[_Write]] = {}
    for write in writes:
        by_campaign.setdefault(str(write.list_ref), []).append(write)
    for campaign, group in by_campaign.items():
        contacts = sorted({str(write.record_ref) for write in group})
        members: set[str] = set()
        refused: _Seen | None = None
        for start in range(0, len(contacts), _SOQL_CHUNK):
            chunk = contacts[start : start + _SOQL_CHUNK]
            query = (
                "SELECT ContactId FROM CampaignMember WHERE CampaignId = "
                f"{_soql_text(campaign)} AND ContactId IN "
                f"({', '.join(_soql_text(c) for c in chunk)})"
            )
            result = await crm.call(_SOQL, {"query": query})
            records = _records(_unwrap(result.data), "records") if result.successful else None
            if records is None:
                refused = (
                    _Seen(error=result.error or "No answer.")
                    if not result.successful
                    else _unreadable(crm, f"the members of campaign {campaign}")
                )
                break
            members.update(_sf_key(record.get("ContactId")) for record in records)
        for write in group:
            seen[write.write_id] = refused or _Seen(value=_sf_key(write.record_ref) in members)
    return seen


async def _read_created(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    """For a create: the record it made (by the id the CRM gave), else a record it would
    duplicate (R-7.1). ``value`` is that record's id, or ``None``."""
    seen: dict[UUID, _Seen] = {}
    for write in writes:
        if write.crm_id is not None:
            seen[write.write_id] = await _read_by_id(crm, write)
            continue
        assert write.spec.find_existing is not None
        slug, key = write.spec.find_existing
        fields = write.after if isinstance(write.after, Mapping) else {}
        value = fields.get(key)
        if value is None or str(value).strip() == "":
            seen[write.write_id] = _Seen(value=None)
            continue
        if crm.connection.provider == "hubspot":
            result = await crm.call(
                slug,
                {
                    "filterGroups": [
                        {"filters": [{"propertyName": key, "operator": "EQ", "value": str(value)}]}
                    ],
                    "properties": [key],
                    "limit": 2,
                },
            )
            records = _records(_unwrap(result.data), "results") if result.successful else None
            id_key = "id"
        else:
            query = (
                f"SELECT Id FROM {_SALESFORCE_SOBJECTS[write.object]} "
                f"WHERE {key} = {_soql_text(value)} LIMIT 2"
            )
            result = await crm.call(slug, {"query": query})
            records = _records(_unwrap(result.data), "records") if result.successful else None
            id_key = "Id"
        if not result.successful:
            seen[write.write_id] = _Seen(error=result.error or "No answer.")
        elif records is None:
            seen[write.write_id] = _unreadable(crm, f"the {write.object} search")
        else:
            seen[write.write_id] = _Seen(
                value=str(records[0].get(id_key)) if records and records[0].get(id_key) else None
            )
    return seen


async def _read_by_id(crm: _Crm, write: _Write) -> _Seen:
    """Whether the record a create made exists: ``value`` is its id, or ``None``."""
    crm_id = str(write.crm_id)
    if crm.connection.provider == "hubspot":
        result = await crm.call(
            _HUBSPOT_READ,
            {
                "objectType": _HUBSPOT_OBJECT_TYPES[write.object],
                "objectId": crm_id,
                "properties": [],
            },
        )
        if not result.successful:
            # HubSpot answers 404 for a record that is not there.
            if failure_kind(result.error) == "not_found":
                return _Seen(value=None)
            return _Seen(error=result.error or "No answer.")
        body = _unwrap(result.data)
        return _Seen(value=crm_id if isinstance(body, Mapping) and body.get("id") else None)
    query = f"SELECT Id FROM {_SALESFORCE_SOBJECTS[write.object]} WHERE Id = {_soql_text(crm_id)}"
    result = await crm.call(_SOQL, {"query": query})
    records = _records(_unwrap(result.data), "records") if result.successful else None
    if not result.successful:
        return _Seen(error=result.error or "No answer.")
    if records is None:
        return _unreadable(crm, f"the {write.object} {crm_id}")
    return _Seen(value=crm_id if records else None)


async def _read(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    seen: dict[UUID, _Seen] = {}
    fields = [w for w in writes if w.kind == "field_update"]
    memberships = [w for w in writes if w.kind in _MEMBERSHIP]
    creates = [w for w in writes if w.kind in _CREATES]
    if fields:
        seen.update(await _read_fields(crm, fields))
    if memberships:
        seen.update(await _read_memberships(crm, memberships))
    if creates:
        seen.update(await _read_created(crm, creates))
    return seen


def _landed(write: _Write, seen: _Seen) -> bool:
    if write.kind in _CREATES:
        return write.crm_id is not None and seen.value == write.crm_id
    if write.kind in _MEMBERSHIP:
        return seen.value == (write.kind == "list_membership")
    return same_value(seen.value, write.after)


def _before_send(crm: _Crm, write: _Write, seen: _Seen) -> _Outcome | None:
    """The conflict check: what to record instead of sending, or ``None`` to send."""
    if seen.error is not None:
        return _failed(seen.error, seen.kind)
    if _landed(write, seen):
        if write.attempts > 0:  # an earlier send of this change put it there
            return _Outcome("succeeded", crm_id=write.crm_id or write.record_ref)
        return _Outcome(
            "skipped", crm_message=f"{crm.name} already held this value, so nothing was sent."
        )
    if write.kind in _CREATES:
        if write.crm_id is not None:  # named by an earlier send, yet not there: never re-create
            return _failed(
                f"{crm.name} named the new record ({write.crm_id}) but it cannot be found; check "
                f"{crm.name} before proposing it again.",
                "not_applied",
            )
        if seen.value is not None:
            return _Outcome(
                "skipped",
                failure_kind="conflict",
                crm_message=(
                    f"{crm.name} already has a matching {write.object} ({seen.value}), so it "
                    "was not created again."
                    + (" It may be the one an earlier send created." if write.attempts else "")
                ),
            )
        return None
    if write.kind in _MEMBERSHIP or same_value(seen.value, write.before):
        return None
    return _Outcome(
        "skipped",
        failure_kind="conflict",
        crm_message=(
            f"The record changed in {crm.name} after the card: it now holds "
            f"{_display(seen.value)}, not {_display(write.before)}, so Clue left it."
        ),
    )


def _after_send(write: _Write, seen: _Seen) -> _Outcome:
    """The read-back: ``succeeded`` only when the value landed."""
    if seen.error is not None:
        return _failed(
            f"The CRM reported success, but reading the record back failed: {seen.error}", "other"
        )
    if _landed(write, seen):
        return _Outcome("succeeded", crm_id=write.crm_id or write.record_ref)
    return _failed(NOT_APPLIED_MESSAGE, "not_applied")


def _created_id(data: Any) -> str | None:
    body = _unwrap(data)
    for candidate in (body, body.get("response_data") if isinstance(body, Mapping) else None):
        if isinstance(candidate, Mapping):
            value = candidate.get("id") or candidate.get("Id")
            if value:
                return str(value)
    return None


def _refused_inside(data: Any) -> str | None:
    """A single-record answer that is ``successful`` yet says ``success: false``."""
    body = _unwrap(data)
    if isinstance(body, Mapping) and body.get("success") is False:
        errors = body.get("errors")
        return json.dumps(errors, default=str) if errors else "Refused."
    return None


# --- the handler ----------------------------------------------------------------------------


class CrmWriteHandler:
    """The ``crm_write`` fleet handler (one task per connection; ``work_id`` = connection id)."""

    kind = FleetTaskKind.CRM_WRITE

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ComposioGateway,
        artifacts: DurableAgentArtifactStore | None,
        conn_factory: ConnFactory = transaction,
        budget: _Budget | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._budget = budget or SalesforceBudget(
            gateway,
            share_pct=settings.crm_salesforce_api_share_pct,
            version=settings.composio_salesforce_toolkit_version,
        )
        self._sleep = sleep

    async def handle(self, context: WorkContext) -> WorkResult:
        connection_id = UUID(str(context.work_id))
        async with self._conn_factory() as conn:
            connection = await get_connection(conn, connection_id=connection_id)
        if connection is None or connection.status != "active":
            return WorkResult(outcome="connection_not_active", references={})
        crm = _Crm(
            gateway=self._gateway,
            budget=self._budget,
            connection=connection,
            version=(
                self._settings.composio_hubspot_toolkit_version
                if connection.provider == "hubspot"
                else self._settings.composio_salesforce_toolkit_version
            ),
            conn_factory=self._conn_factory,
            min_interval_s=self._settings.crm_write_min_interval_s,
            sleep=self._sleep,
        )
        handled: list[UUID] = []
        while True:
            if context.stop_requested.is_set() or context.lease_lost.is_set():
                return WorkResult(outcome="interrupted", references={}, requeue=True)
            async with self._conn_factory() as conn:
                proposal_id = await _next_proposal(conn, connection, exclude=handled)
            if proposal_id is None:
                break
            handled.append(proposal_id)
            stopped = await self._run_proposal(crm, proposal_id, context)
            if stopped is not None:
                return stopped
        # No lost wake-up (Task 5 ruling): a proposal queued after the last look, whose offer
        # met this task still claimed, is picked up by requeueing this task.
        async with self._conn_factory() as conn:
            if await _next_proposal(conn, connection, exclude=handled, statuses=("queued",)):
                return WorkResult(
                    outcome="more_queued", references={"proposals": len(handled)}, requeue=True
                )
        return WorkResult(outcome="done", references={"proposals": len(handled)})

    async def _run_proposal(
        self, crm: _Crm, proposal_id: UUID, context: WorkContext
    ) -> WorkResult | None:
        """Send one proposal's chosen changes; a :class:`WorkResult` stops the task."""
        async with self._conn_factory() as conn:
            writes = await _start_proposal(conn, crm.connection, proposal_id)
        try:
            for spec, chunk in _chunks(writes):
                if context.stop_requested.is_set() or context.lease_lost.is_set():
                    return WorkResult(outcome="interrupted", references={}, requeue=True)
                await self._send_chunk(crm, spec, chunk)
        except _Stop as stop:
            return await self._stopped(crm, proposal_id, stop)
        async with self._conn_factory() as conn:
            await set_proposal_status(conn, proposal_id=proposal_id, status="finished")
            proposal = await get_proposal(conn, proposal_id=proposal_id)
            assert proposal is not None
            await self._wake(conn, proposal)
        return None

    async def _send_chunk(self, crm: _Crm, spec: WriteActionSpec, chunk: Sequence[_Write]) -> None:
        try:
            seen = await _read(crm, chunk)
        except _Stop as stop:
            if await self._read_stopped(chunk, stop):
                raise
            return  # every change of the chunk has used up its attempts and failed
        to_send: list[_Write] = []
        decided: dict[UUID, _Outcome] = {}
        for write in chunk:
            outcome = _before_send(crm, write, seen[write.write_id])
            if outcome is None:
                to_send.append(write)
            else:
                decided[write.write_id] = outcome
        await self._record(crm, chunk, decided)
        if not to_send:
            return
        accepted = await self._send(crm, spec, to_send)
        if accepted:
            await self._read_back(crm, accepted)

    async def _read_back(self, crm: _Crm, accepted: Sequence[_Write]) -> None:
        """Confirm the changes the CRM accepted. A stop here leaves them ``sending`` — sent,
        awaiting confirmation — with their attempt neither counted again nor failed: the next
        run's check confirms them without sending them again."""
        back = await _read(crm, accepted)
        await self._record(
            crm,
            accepted,
            {write.write_id: _after_send(write, back[write.write_id]) for write in accepted},
        )

    async def _read_stopped(self, writes: Sequence[_Write], stop: _Stop) -> bool:
        """The check before sending met a rate limit or an unreachable CRM: that counts as an
        attempt of each change still waiting to be sent (so the back-off grows), and one past
        ``MAX_ATTEMPTS`` fails ``retryable``. A change already sent (``sending``, awaiting
        confirmation) is never counted or failed here. ``True`` when the run must stop."""
        if stop.kind not in ("rate_limited", "unavailable"):
            return True
        ids = [write.write_id for write in writes]
        async with self._conn_factory() as conn:
            rows = await conn.execute(
                text(
                    "UPDATE crm_write SET attempts = attempts + 1 WHERE write_id = ANY(:ids) "
                    "AND status = 'queued' RETURNING write_id, attempts"
                ),
                {"ids": ids},
            )
            counted = rows.all()
            spent = [
                row.write_id
                for row in counted
                if int(row.attempts) >= self._settings.crm_write_max_attempts
            ]
            if spent:
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = 'failed', failure_kind = :kind, "
                        "crm_message = :message, crm_response = CAST(:response AS jsonb), "
                        "retryable = true, finished_at = now() WHERE write_id = ANY(:ids)"
                    ),
                    {
                        "ids": spent,
                        "kind": "rate_limited" if stop.kind == "rate_limited" else "other",
                        **_stop_message(stop),
                    },
                )
            undecided = await conn.scalar(
                text(
                    "SELECT count(*) FROM crm_write WHERE write_id = ANY(:ids) "
                    "AND status NOT IN ('succeeded', 'failed', 'skipped')"
                ),
                {"ids": ids},
            )
        return bool(undecided)

    async def _send(
        self, crm: _Crm, spec: WriteActionSpec, writes: Sequence[_Write]
    ) -> list[_Write]:
        """Send the changes; record every refusal; return the ones the CRM accepted (each with
        the id the CRM gave a create) for the read-back."""
        accepted: list[_Write] = []
        calls: list[list[_Write]] = (
            [list(writes)] if spec.batch is not None else [[write] for write in writes]
        )
        for call in calls:
            await crm.reserve()
            call = await self._mark_sending(call)
            if not call:
                continue
            try:
                accepted.extend(await self._call(crm, spec, call))
            except _Stop as stop:
                # Changes the CRM already accepted keep their send: they are read back now
                # (when the CRM can still be read), else settled by the next run's check.
                accepted.extend(stop.accepted)
                landed = {write.write_id for write in stop.accepted}
                waiting = await self._put_back(
                    [write for write in call if write.write_id not in landed], stop
                )
                if waiting or stop.kind not in ("rate_limited", "unavailable"):
                    if accepted and stop.kind in ("rate_limited", "unavailable"):
                        with contextlib.suppress(_Stop):
                            await self._read_back(crm, accepted)
                    raise
                # Every change of this call has used up its sends and failed: go on.
        return accepted

    async def _call(self, crm: _Crm, spec: WriteActionSpec, call: list[_Write]) -> list[_Write]:
        """One call to the CRM (the rows are already ``sending``)."""
        if spec.batch is not None:
            arguments = [write.arguments for write in call]
            result = await crm.execute(spec.batch.slug, spec.batch.build(arguments))
            if not result.successful and len(call) > 1:
                # One bad item refuses a whole HubSpot batch and writes nothing: send each alone
                # so the others go through and the refusal names its own record.
                accepted: list[_Write] = []
                for write in call:
                    try:
                        await crm.reserve()
                        accepted.extend(await self._call(crm, spec, [write]))
                    except _Stop as stop:
                        stop.accepted.extend(accepted)
                        raise
                return accepted
            if not result.successful:
                await self._record(
                    crm,
                    call,
                    {call[0].write_id: _failed(result.error or "Refused.", _refusal_kind(result))},
                )
                return []
            items = spec.batch.split(result.data, arguments)
            refusals = {
                write.write_id: _failed(item.error or "Refused.")
                for write, item in zip(call, items, strict=True)
                if not item.ok
            }
            await self._record(crm, call, refusals)
            return [write for write in call if write.write_id not in refusals]
        (write,) = call
        result = await crm.execute(spec.slug, write.arguments)
        refused = _refused_inside(result.data) if result.successful else result.error or "Refused."
        if refused is not None:
            kind = None if result.successful else _refusal_kind(result)
            await self._record(crm, call, {write.write_id: _failed(refused, kind)})
            return []
        if write.kind not in _CREATES:
            return [write]
        created = replace(write, crm_id=_created_id(result.data))
        if created.crm_id is None:
            await self._record(
                crm,
                call,
                {
                    write.write_id: _failed(
                        f"{crm.name} reported success but did not name the new record; check "
                        f"{crm.name} before proposing it again.",
                        "other",
                    )
                },
            )
            return []
        # The record exists from now on: its id and the "Clue created it" link are kept at once,
        # whatever happens to the read-back.
        connection = crm.connection
        async with self._conn_factory() as conn:
            await conn.execute(
                text("UPDATE crm_write SET crm_id = :crm_id WHERE write_id = :id"),
                {"crm_id": created.crm_id, "id": write.write_id},
            )
            await record_link(
                conn,
                workspace_id=connection.workspace_id,
                connection_id=connection.connection_id,
                crm_object=write.object,
                crm_id=created.crm_id,
                created_by_clue=True,
                created_by_write_id=write.write_id,
            )
        return [created]

    async def _mark_sending(self, call: Sequence[_Write]) -> list[_Write]:
        """Log the send before it happens; a change already decided is never sent again."""
        async with self._conn_factory() as conn:
            rows = await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'sending', attempts = attempts + 1, "
                    "sent_at = now() WHERE write_id = ANY(:ids) "
                    "AND status NOT IN ('succeeded', 'failed', 'skipped') "
                    "RETURNING write_id, attempts"
                ),
                {"ids": [write.write_id for write in call]},
            )
            attempts = {row.write_id: int(row.attempts) for row in rows}
        return [replace(w, attempts=attempts[w.write_id]) for w in call if w.write_id in attempts]

    async def _put_back(self, call: Sequence[_Write], stop: _Stop) -> bool:
        """A call that met a temporary failure or an expired connection: its changes wait again,
        except those that have used up their sends (rate limit / unreachable), which fail.
        ``True`` when any change waits (the run stops)."""
        exhausted: list[UUID] = []
        waiting: list[UUID] = []
        for write in call:
            if (
                stop.kind in ("rate_limited", "unavailable")
                and write.attempts >= self._settings.crm_write_max_attempts
            ):
                exhausted.append(write.write_id)
            else:
                waiting.append(write.write_id)
        async with self._conn_factory() as conn:
            if waiting:
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = 'queued', attempts = attempts - "
                        "CASE WHEN :unsent THEN 1 ELSE 0 END "
                        "WHERE write_id = ANY(:ids) AND status = 'sending'"
                    ),
                    # Composio refused an expired connection before reaching the CRM: not a send.
                    {"ids": waiting, "unsent": stop.kind == "connection_expired"},
                )
            if exhausted:
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = 'failed', failure_kind = :kind, "
                        "crm_message = :message, crm_response = CAST(:response AS jsonb), "
                        "retryable = true, finished_at = now() "
                        "WHERE write_id = ANY(:ids) AND status = 'sending'"
                    ),
                    {
                        "ids": exhausted,
                        "kind": "rate_limited" if stop.kind == "rate_limited" else "other",
                        **_stop_message(stop),
                    },
                )
        return bool(waiting)

    async def _record(
        self, crm: _Crm, writes: Sequence[_Write], outcomes: Mapping[UUID, _Outcome]
    ) -> None:
        """Store each decided change, with its record links, in one transaction."""
        if not outcomes:
            return
        by_id = {write.write_id: write for write in writes}
        connection = crm.connection
        async with self._conn_factory() as conn:
            for write_id, outcome in outcomes.items():
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = :status, failure_kind = :kind, "
                        "crm_message = :message, crm_response = CAST(:response AS jsonb), "
                        "retryable = :retryable, crm_id = COALESCE(:crm_id, crm_id), "
                        "finished_at = now() "
                        "WHERE write_id = :id AND status NOT IN ('succeeded', 'failed', 'skipped')"
                    ),
                    {
                        "id": write_id,
                        "status": outcome.status,
                        "kind": outcome.failure_kind,
                        "message": outcome.crm_message,
                        "response": _response_param(outcome.crm_response),
                        "retryable": outcome.retryable,
                        "crm_id": outcome.crm_id,
                    },
                )
                write = by_id[write_id]
                if outcome.status != "succeeded":
                    continue
                if write.kind in _CREATES and outcome.crm_id is not None:
                    await record_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        crm_object=write.object,
                        crm_id=outcome.crm_id,
                        created_by_clue=True,
                        created_by_write_id=write_id,
                    )
                elif write.kind == "list_membership":
                    await record_membership_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        list_ref=str(write.list_ref),
                        record_ref=str(write.record_ref),
                        write_id=write_id,
                    )
                elif write.kind == "list_removal":
                    await forget_membership_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        list_ref=str(write.list_ref),
                        record_ref=str(write.record_ref),
                    )

    async def _stopped(self, crm: _Crm, proposal_id: UUID, stop: _Stop) -> WorkResult:
        # Changes sent but not yet confirmed stay ``sending``: the next run's check confirms them.
        references: dict[str, Any] = {"proposal_id": str(proposal_id), "reason": stop.kind}
        if stop.kind in ("rate_limited", "unavailable"):
            async with self._conn_factory() as conn:
                await set_proposal_status(conn, proposal_id=proposal_id, status="queued")
                attempt = await conn.scalar(
                    text(
                        "SELECT GREATEST(1, COALESCE(max(attempts), 1)) FROM crm_write "
                        "WHERE proposal_id = :id AND selected AND status IN ('queued', 'sending')"
                    ),
                    {"id": proposal_id},
                )
            delay = self._settings.crm_write_retry_base_s * 2 ** (int(attempt or 1) - 1)
            return WorkResult(
                outcome=f"crm_{stop.kind}",
                references=references,
                requeue=True,
                requeue_after=timedelta(seconds=delay),
            )
        if stop.kind == "connection_expired":
            assert stop.error is not None
            await composio_refusal(self._conn_factory, stop.error, crm.connection)
            reason = f"the {crm.name} connection has expired or was revoked"
            resumes = (
                "once this connection works again; if the person connects the CRM anew, these "
                "changes are not sent and must be proposed again"
            )
        elif stop.kind == "auth":
            # Clue's Composio key or the connected account is not accepted: a deployment fault
            # or a deleted account, never a reason to fail the person's changes for good.
            log.error(
                "crm_write.composio_refused_connection",
                connection_id=str(crm.connection.connection_id),
                detail=stop.message,
            )
            reason = f"Clue could not use the {crm.name} connection ({stop.message})"
            resumes = "once the connection works again (the next approved change retries it)"
        else:
            reason = stop.message
            resumes = f"when {crm.name}'s daily API allowance allows it again"
        async with self._conn_factory() as conn:
            await set_proposal_status(conn, proposal_id=proposal_id, status="paused")
            proposal = await get_proposal(conn, proposal_id=proposal_id)
            assert proposal is not None
            if self._artifacts is not None:
                await queue_crm_writes_paused_turn(
                    conn, self._artifacts, proposal=proposal, reason=reason, resumes=resumes
                )
        log.info("crm_write.paused", proposal_id=str(proposal_id), reason=stop.kind)
        if stop.kind == "budget" and stop.budget_code == "salesforce_api_share_exhausted":
            # Clue's share comes back with the next UTC day.
            now = datetime.now(UTC)
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
            return WorkResult(
                outcome="crm_budget",
                references=references,
                requeue=True,
                requeue_after=tomorrow - now + timedelta(minutes=1),
            )
        return WorkResult(outcome=f"crm_{stop.kind}", references=references)

    async def _wake(self, conn: AsyncConnection, proposal: WriteProposal) -> None:
        if self._artifacts is None:
            log.warning("crm_write.no_artifact_store", proposal_id=str(proposal.proposal_id))
            return
        await queue_crm_writes_finished_turn(conn, self._artifacts, proposal=proposal)


# --- the proposals of a connection ------------------------------------------------------------

_NEXT_PROPOSAL = """
    SELECT p.proposal_id FROM crm_write_proposal p
    JOIN workspace_integration_connection c ON c.connection_id = p.connection_id
    WHERE p.connection_id = :connection_id AND c.status = 'active'
      AND p.status = ANY(:statuses)
      AND p.proposal_id <> ALL(CAST(:exclude AS uuid[]))
    ORDER BY p.created_at, p.proposal_id
    LIMIT 1
"""


async def _next_proposal(
    conn: AsyncConnection,
    connection: CrmConnection,
    *,
    exclude: Sequence[UUID],
    statuses: Sequence[str] = _RESUMABLE,
) -> UUID | None:
    """The oldest proposal this connection sends next. Only its own, and only while it is
    active: a proposal is never sent on another connection (a reconnect may be to another
    portal or org — founder ruling, Task 6 review)."""
    value = await conn.scalar(
        text(_NEXT_PROPOSAL),
        {
            "statuses": list(statuses),
            "connection_id": connection.connection_id,
            "exclude": list(exclude),
        },
    )
    return None if value is None else UUID(str(value))


async def _start_proposal(
    conn: AsyncConnection, connection: CrmConnection, proposal_id: UUID
) -> list[_Write]:
    """Mark the proposal ``sending``, skip the changes the person did not choose, queue the
    chosen ones, and load those not yet decided in order. A change whose action is no longer
    allowlisted fails here and the rest go on."""
    await set_proposal_status(conn, proposal_id=proposal_id, status="sending")
    await conn.execute(
        text(
            "UPDATE crm_write SET status = 'skipped', crm_message = :message, finished_at = now() "
            "WHERE proposal_id = :id AND NOT selected "
            "AND status NOT IN ('succeeded', 'failed', 'skipped')"
        ),
        {"id": proposal_id, "message": NOT_CHOSEN_MESSAGE},
    )
    await conn.execute(
        text(
            "UPDATE crm_write SET status = 'queued' "
            "WHERE proposal_id = :id AND selected AND status = 'proposed'"
        ),
        {"id": proposal_id},
    )
    rows = await conn.execute(
        text(
            "SELECT write_id, ordinal, slug, arguments::text AS arguments, kind, object, "
            "record_ref, field, before_value::text AS before_value, "
            "after_value::text AS after_value, attempts, crm_id FROM crm_write "
            "WHERE proposal_id = :id AND selected "
            "AND status NOT IN ('succeeded', 'failed', 'skipped') ORDER BY ordinal"
        ),
        {"id": proposal_id},
    )
    writes = []
    for row in rows.all():
        spec = write_spec(connection.provider, row.slug)
        arguments = json.loads(row.arguments)
        try:
            if spec is None:
                raise WriteNotParsable(row.slug)
            parsed = spec.parse(arguments)
        except WriteNotParsable:
            # The allowlist changed since the card: never send it, and never block the queue.
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'failed', failure_kind = 'other', "
                    "crm_message = :message, retryable = false, finished_at = now() "
                    "WHERE write_id = :id"
                ),
                {"id": row.write_id, "message": NO_LONGER_ALLOWED_MESSAGE},
            )
            continue
        writes.append(
            _Write(
                write_id=row.write_id,
                ordinal=int(row.ordinal),
                spec=spec,
                arguments=arguments,
                kind=row.kind,
                object=row.object,
                record_ref=row.record_ref,
                list_ref=parsed.list_ref,
                field=row.field,
                before=None if row.before_value is None else json.loads(row.before_value),
                after=None if row.after_value is None else json.loads(row.after_value),
                attempts=int(row.attempts),
                crm_id=row.crm_id,
            )
        )
    return writes


def _chunks(writes: Sequence[_Write]) -> list[tuple[WriteActionSpec, list[_Write]]]:
    """Changes of one action (and, for a batch, one group) together, in the order they first
    appear, cut to the CRM's batch size; an action without a batch is still read together."""
    groups: dict[tuple[str, str], tuple[WriteActionSpec, list[_Write]]] = {}
    for write in writes:
        group = write.spec.batch.group(write.arguments) if write.spec.batch is not None else ""
        groups.setdefault((write.spec.slug, group), (write.spec, []))[1].append(write)
    chunks: list[tuple[WriteActionSpec, list[_Write]]] = []
    for spec, members in groups.values():
        size = spec.batch.max_size if spec.batch is not None else _SOQL_CHUNK
        chunks.extend((spec, members[i : i + size]) for i in range(0, len(members), size))
    return chunks


async def close_replaced_connection_proposals(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore | None,
    *,
    workspace_id: str,
    active_connection_id: UUID,
) -> list[UUID]:
    """A new connection became active: the proposals other connections of the workspace still
    had to send are closed, never sent on the new one (it may be another portal or org). A card
    still waiting for its answer is closed too: it could never be answered (the answer route
    refuses a card of another connection), so it would otherwise wait for ever.

    Every undecided change is ``skipped`` with ``failure_kind = 'connection_expired'`` — or
    ``failed`` when it had been sent and could not be confirmed — the proposal is ``finished``,
    and its chat is woken once to propose again. Writes only through ``conn``."""
    rows = await conn.execute(
        text(
            "SELECT proposal_id FROM crm_write_proposal WHERE workspace_id = :ws "
            "AND connection_id <> :active "
            "AND status IN ('awaiting_permission', 'queued', 'sending', 'paused') "
            "ORDER BY created_at, proposal_id FOR UPDATE"
        ),
        {"ws": workspace_id, "active": active_connection_id},
    )
    closed = [UUID(str(row.proposal_id)) for row in rows.all()]
    for proposal_id in closed:
        await conn.execute(
            text(
                "UPDATE crm_write SET finished_at = now(), "
                "status = CASE WHEN NOT selected THEN 'skipped' "
                "WHEN attempts > 0 THEN 'failed' ELSE 'skipped' END, "
                "failure_kind = CASE WHEN selected THEN 'connection_expired' END, "
                "crm_message = CASE WHEN NOT selected THEN :not_chosen "
                "WHEN attempts > 0 THEN :unconfirmed ELSE :reconnected END "
                "WHERE proposal_id = :id AND status NOT IN ('succeeded', 'failed', 'skipped')"
            ),
            {
                "id": proposal_id,
                "not_chosen": NOT_CHOSEN_MESSAGE,
                "unconfirmed": UNCONFIRMED_MESSAGE,
                "reconnected": RECONNECTED_MESSAGE,
            },
        )
        await set_proposal_status(conn, proposal_id=proposal_id, status="finished")
        proposal = await get_proposal(conn, proposal_id=proposal_id)
        assert proposal is not None
        if artifacts is not None:
            await queue_crm_writes_finished_turn(conn, artifacts, proposal=proposal)
    if closed:
        log.info("crm_write.closed_on_reconnect", proposals=len(closed))
    return closed


def build_crm_write_handler(
    *,
    settings: Settings,
    secrets: Secrets | None,
    conn_factory: ConnFactory = transaction,
    artifacts: DurableAgentArtifactStore | None,
) -> CrmWriteHandler | None:
    """The fleet worker's CRM write executor, or ``None`` (stated once at boot) when the CRM
    integration is off or no Composio key is configured."""
    gateway = build_composio_gateway(settings=settings, secrets=secrets)
    if gateway is None:
        log.info(
            "crm_write.handler_not_composed",
            reason="CLUE_CRM_INTEGRATION_ENABLED is off or CLUE_COMPOSIO_API_KEY is not set",
        )
        return None
    return CrmWriteHandler(
        settings=settings, gateway=gateway, artifacts=artifacts, conn_factory=conn_factory
    )
