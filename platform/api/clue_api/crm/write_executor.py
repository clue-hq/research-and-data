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
sends, then fails it ``retryable``; a rate limit met by a read counts as an attempt the same way,
and a change sent whose confirming read keeps failing is failed ``retryable`` at the same cap.
An expired connection is marked expired and the proposal ``paused`` (a proposal still waiting when
its task finds the connection already expired is paused the same way); a connection Composio refuses
(401/403, or a connected account it no longer knows) pauses it without touching the connection, as
does Salesforce's API budget running out. A paused proposal resumes only on its own connection: it
is never sent on another one, because a reconnect may be to a different portal or org (founder
ruling, Task 6 review; R-11.10: a reconnect does not resume it). When a new connection becomes
active, the connect callback closes the other connections' unsent proposals
(:func:`close_replaced_connection_proposals`) and their chats are asked to propose again. A finished
proposal — and a paused one — wakes the chat that proposed it (:mod:`clue_api.crm.wake`). A change
whose action is no longer allowlisted fails on its own and never blocks the queue.

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
from clue_api.crm.lists import link_project, mark_gone, store_list, stored_list
from clue_api.crm.salesforce_budget import CrmBudgetExhausted, SalesforceBudget
from clue_api.crm.tools import composio_refusal
from clue_api.crm.wake import queue_crm_writes_finished_turn, queue_crm_writes_paused_turn
from clue_api.crm.write_actions import (
    HUBSPOT_OBJECT_TYPE_IDS,
    NEW_COMPANY_PREFIX,
    NEW_LIST_PREFIX,
    WriteActionSpec,
    WriteNotParsable,
    created_reference,
    find_value,
    new_list_name,
    reference_in,
    with_reference_filled,
    write_spec,
)
from clue_api.crm.write_prepare import (
    _CRM_NAMES,
    _HUBSPOT_OBJECT_TYPES,
    _SALESFORCE_SOBJECTS,
    _sf_key,
    _soql_text,
    _status_code,
    _unwrap,
    create_key,
    hubspot_batch_values,
    salesforce_find_query,
    salesforce_match,
    temporary_failure,
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
_LIST_CREATE = "list_create"
#: Every kind that makes something new in the CRM and stores the id the CRM gives it.
_MAKES = (*_CREATES, _LIST_CREATE)
_HUBSPOT_READ = "HUBSPOT_READ_CRM_OBJECT_BY_ID"
_SOQL = "SALESFORCE_RUN_SOQL_QUERY"
#: Salesforce ids are matched in one query per this many records.
_SOQL_CHUNK = 200
_RESUMABLE = ("queued", "sending", "paused")
#: A HubSpot value the read-back did not find is read once more after this pause (live check
#: L-3): HubSpot applies some values a moment after it answers the update — a contact's
#: ``associatedcompanyid`` follows the association the update makes — so a by-id read two
#: seconds later can still show the old value.
_READ_AGAIN_AFTER_S = 5.0

NOT_APPLIED_MESSAGE = "The CRM reported success but the value did not change."
NOT_CHOSEN_MESSAGE = "Not chosen on the permission card, so it was not sent."
NO_LONGER_ALLOWED_MESSAGE = "This action is no longer allowed, so it was not sent."
#: Phase 4 Task 2 proposes Clue's fields setup; Task 3 runs it. Until then an allowed setup fails
#: closed: nothing is sent to the CRM.
SETUP_NOT_BUILT_MESSAGE = "Setting up Clue's fields is not built yet, so nothing was sent."
RECONNECTED_MESSAGE = "The CRM was reconnected or switched, so this was not sent; propose again."
#: A change sent whose confirming read kept failing until its attempts ran out (final review I-2).
UNCONFIRMED_SEND_MESSAGE = "Sent; Clue could not confirm it — check the CRM"
#: An add to a list the same proposal was to create, when the create did not happen (R-12.7).
NOT_CREATED_MESSAGE = "The list was not created, so nothing was added to it."
#: A change that uses a company or person the same proposal was to create, when the create did
#: not happen (R-12.11).
COMPANY_NOT_CREATED_MESSAGE = "The company it needs was not created, so it was not sent."
PERSON_NOT_CREATED_MESSAGE = "The person it needs was not created, so it was not sent."
#: Salesforce refuses "In Progress" when the org's Campaign.Status picklist lacks it (R-12.9).
NO_IN_PROGRESS_MESSAGE = (
    'Salesforce has no campaign status "In Progress"; ask your Salesforce admin to add it.'
)
#: A membership change of a list HubSpot no longer has (R-11.11 (4); Review Focus 3).
LIST_GONE_MESSAGE = "The list no longer exists in HubSpot; find it by name or create it again."
#: A membership change of a campaign Salesforce no longer has (R-12.15; final review).
CAMPAIGN_GONE_MESSAGE = (
    "The campaign no longer exists in Salesforce; find it by name or create it again."
)
#: Salesforce lets only Marketing Users create campaigns (Phase 3 Task 1 ruling).
MARKETING_USER_MESSAGE = (
    "Your Salesforce user needs the Marketing User permission to create campaigns."
)
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


#: Salesforce's refusal of a campaign create by a user who is not a Marketing User (verbatim).
_CAMPAIGN_NOT_ALLOWED = (
    "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY",
    "entity type cannot be inserted: Campaign",
)


def _campaign_not_allowed(message: str) -> bool:
    return all(part in message for part in _CAMPAIGN_NOT_ALLOWED)


def _no_in_progress_status(parsed: Any) -> bool:
    """Salesforce's refusal of the campaign status Clue sends: a bad restricted-picklist value
    on ``Status`` naming "In Progress"."""
    return isinstance(parsed, list) and any(
        isinstance(item, Mapping)
        and item.get("errorCode") == "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST"
        and "Status" in (item.get("fields") or [])
        and "In Progress" in str(item.get("message") or "")
        for item in parsed
    )


def failure_kind(message: str | None) -> FailureKind:
    """The ``crm_write.failure_kind`` of a CRM refusal, from the error code in its message."""
    if not message:
        return "other"
    if _campaign_not_allowed(message):
        return "permission"
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
        # A refusal a person can act on is said in plain words; the answer is kept.
        message = MARKETING_USER_MESSAGE if _campaign_not_allowed(body) else None
        if message is None and _no_in_progress_status(parsed):
            message = NO_IN_PROGRESS_MESSAGE
        message = message or _crm_text(parsed) or body
        return message[:_MESSAGE_MAX], parsed
    if len(body) > _MESSAGE_MAX:
        return body[:_MESSAGE_MAX], body
    return body, None


def _refusal_kind(result: ExecuteResult) -> FailureKind:
    """A refused call's ``failure_kind``: the CRM's 404 for a record is ``not_found``."""
    if _status_code(result) == 404:
        return "not_found"
    return failure_kind(result.error)


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
    #: What the card called the record; a list's name for a ``list_create``.
    label: str | None = None
    #: The project of the change's proposal (a list Clue creates is kept for it).
    project_id: str | None = None
    #: The Clue contact or account the change is about (Task 5): its CRM record is linked to it
    #: once the change succeeds (Task 6).
    clue_entity_id: str | None = None


@dataclass(frozen=True)
class _Seen:
    """What a read found for one change: its current value, or why it could not be read."""

    value: object = None
    error: str | None = None
    kind: FailureKind | None = None
    #: The name the CRM holds for a list or campaign it found (``list_create`` only).
    name: str | None = None
    #: More than one Salesforce campaign has the name looked for (``list_create`` only).
    ambiguous: bool = False


@dataclass(frozen=True)
class _Outcome:
    status: Literal["succeeded", "failed", "skipped"]
    failure_kind: FailureKind | None = None
    crm_message: str | None = None
    retryable: bool | None = None
    crm_id: str | None = None
    #: The CRM's answer behind ``crm_message``, when the message is not the whole of it.
    crm_response: Any = None
    #: The record a create found already there at send time (R-7.1: the same email or domain),
    #: linked to the change's Clue entity instead of creating another (Task 6 ruling #2).
    found_id: str | None = None


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
            temporary = temporary_failure(result)
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
    """The current value of each field update's field, read in batches where the CRM has a
    batch read (HubSpot companies, Salesforce SOQL)."""
    seen: dict[UUID, _Seen] = {}
    if crm.connection.provider == "hubspot":
        hubspot_objects: dict[str, dict[str, list[_Write]]] = {}
        for write in writes:
            hubspot_objects.setdefault(write.object, {}).setdefault(
                str(write.record_ref), []
            ).append(write)
        # Batched where HubSpot has a batch read (companies, R-7.4); a record the batch did not
        # return, and every contact, is read on its own (that read tells "not found" apart).
        by_record: dict[tuple[str, str], list[_Write]] = {}
        for object_name, object_records in hubspot_objects.items():
            batch = await hubspot_batch_values(
                crm.call,
                object_name,
                {
                    ref: sorted({str(w.field) for w in group})
                    for ref, group in object_records.items()
                },
            )
            for record_ref, group in object_records.items():
                if record_ref not in batch:
                    by_record[(object_name, record_ref)] = group
                    continue
                for write in group:
                    seen[write.write_id] = _Seen(value=batch[record_ref].get(str(write.field)))
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
        by_record: dict[tuple[str, str], list[_Write]] = {}
        for write in writes:
            by_record.setdefault((write.object, str(write.record_ref)), []).append(write)
        for (object_name, record_ref), group in by_record.items():
            result = await crm.call(
                "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS",
                {"object_type_id": HUBSPOT_OBJECT_TYPE_IDS[object_name], "record_id": record_ref},
            )
            records = _records(_unwrap(result.data), "results") if result.successful else None
            lists = None if records is None else {str(r.get("listId")) for r in records}
            for write in group:
                if not result.successful:
                    seen[write.write_id] = _Seen(error=result.error or "No answer.")
                elif lists is None:
                    seen[write.write_id] = _unreadable(
                        crm, f"the lists of {object_name} {record_ref}"
                    )
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
        value = find_value(key, fields)
        if not create_key(key, value):
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
            query = salesforce_find_query(_SALESFORCE_SOBJECTS[write.object], key, value, [])
            result = await crm.call(slug, {"query": query})
            records = _records(_unwrap(result.data), "records") if result.successful else None
            if records is not None:  # a website matches by its host, not its spelling
                match = salesforce_match(key, value, records)
                records = [] if match is None else [match]
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


async def _read_lists(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    """For a list or campaign create: the one the CRM has. By the id the CRM gave it once it gave
    one (a list renamed since is still Clue's); before that by name. ``value`` is its id, or
    ``None``; ``name`` is what the CRM calls it (composio-api-notes.md § Phase 3 shapes)."""
    seen: dict[UUID, _Seen] = {}
    for write in writes:
        name = str(write.label or "")
        if crm.connection.provider == "hubspot":
            seen[write.write_id] = await _read_hubspot_list(crm, write, name)
            continue
        # Salesforce allows two campaigns of one name: by name, the newest first, and two
        # found are said to be two (never one picked).
        where = (
            f"Id = {_soql_text(write.crm_id)}"
            if write.crm_id is not None
            else f"Name = {_soql_text(name)} ORDER BY CreatedDate DESC"
        )
        result = await crm.call(
            _SOQL, {"query": f"SELECT Id, Name FROM Campaign WHERE {where} LIMIT 2"}
        )
        records = _records(_unwrap(result.data), "records") if result.successful else None
        if not result.successful:
            seen[write.write_id] = _Seen(error=result.error or "No answer.")
        elif records is None:
            seen[write.write_id] = _unreadable(crm, f'the campaign "{name}"')
        elif not records or not records[0].get("Id"):
            seen[write.write_id] = _Seen(value=None)
        else:
            found_id = str(records[0]["Id"])
            # Salesforce may answer the 18-character form of the id it gave.
            same = write.crm_id is not None and _sf_key(found_id) == _sf_key(write.crm_id)
            seen[write.write_id] = _Seen(
                value=write.crm_id if same else found_id,
                name=_text(records[0].get("Name")),
                ambiguous=write.crm_id is None and len(records) > 1,
            )
    return seen


async def _read_hubspot_list(crm: _Crm, write: _Write, name: str) -> _Seen:
    type_id = HUBSPOT_OBJECT_TYPE_IDS[write.object]
    if write.crm_id is not None:
        result = await crm.call(
            "HUBSPOT_SEARCH_CRM_LISTS",
            {"objectTypeId": type_id, "listIds": [write.crm_id], "count": 1},
        )
        if not result.successful:
            return _Seen(error=result.error or "No answer.")
        found = _records(_unwrap(result.data), "lists")
        if found is None:
            return _unreadable(crm, f"the list {write.crm_id}")
        match = next((one for one in found if str(one.get("listId")) == write.crm_id), None)
        if match is None:
            return _Seen(value=None)
        return _Seen(value=write.crm_id, name=_text(match.get("name")))
    result = await crm.call(
        "HUBSPOT_GET_CRM_LIST_BY_NAME", {"object_type_id": type_id, "list_name": name}
    )
    if not result.successful:
        # HubSpot answers 404 LIST_NAME_DOES_NOT_EXIST for a name it does not have.
        missing = _status_code(result) == 404 or "LIST_NAME_DOES_NOT_EXIST" in (result.error or "")
        return _Seen(value=None) if missing else _Seen(error=result.error or "No answer.")
    body = _unwrap(result.data)
    found_list = body.get("list") if isinstance(body, Mapping) else None
    if not isinstance(found_list, Mapping) or found_list.get("listId") in (None, ""):
        return _unreadable(crm, f'the list "{name}"')
    return _Seen(value=str(found_list["listId"]), name=_text(found_list.get("name")))


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def _read(crm: _Crm, writes: Sequence[_Write]) -> dict[UUID, _Seen]:
    seen: dict[UUID, _Seen] = {}
    fields = [w for w in writes if w.kind == "field_update"]
    memberships = [w for w in writes if w.kind in _MEMBERSHIP]
    creates = [w for w in writes if w.kind in _CREATES]
    lists = [w for w in writes if w.kind == _LIST_CREATE]
    if fields:
        seen.update(await _read_fields(crm, fields))
    if memberships:
        seen.update(await _read_memberships(crm, memberships))
    if creates:
        seen.update(await _read_created(crm, creates))
    if lists:
        seen.update(await _read_lists(crm, lists))
    return seen


def _landed(write: _Write, seen: _Seen) -> bool:
    if write.kind in _MAKES:
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
    if write.kind in _MAKES:
        if write.crm_id is not None:  # named by an earlier send, yet not there: never re-create
            return _failed(
                f"{crm.name} named the new record ({write.crm_id}) but it cannot be found; check "
                f"{crm.name} before proposing it again.",
                "not_applied",
            )
        if (
            seen.value is not None
            and write.kind == _LIST_CREATE
            and write.attempts > 0
            and seen.name == write.label
            and seen.ambiguous
        ):
            return _failed(
                f'{crm.name} has more than one campaign named "{write.label}", so Clue cannot '
                f"tell which one it created; check {crm.name} before proposing it again.",
                "conflict",
            )
        if (
            seen.value is not None
            and write.kind == _LIST_CREATE
            and write.attempts > 0
            and seen.name == write.label
        ):
            # An earlier send made it but died before Clue kept its id (review #3): the list of
            # exactly the name Clue sent is Clue's own, kept now and never made again.
            return _Outcome("succeeded", crm_id=str(seen.value))
        if seen.value is not None and write.kind == _LIST_CREATE:
            target = "list" if crm.connection.provider == "hubspot" else "campaign"
            return _Outcome(
                "skipped",
                failure_kind="conflict",
                crm_message=(
                    f'{crm.name} already has a {target} named "{write.label}" ({seen.value}), '
                    "so it was not created again."
                    + (" It may be the one an earlier send created." if write.attempts else "")
                ),
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
                found_id=str(seen.value),
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
    """The id a create's answer gives: a record's ``id``, or a HubSpot list's ``list.listId``."""
    body = _unwrap(data)
    nested = (
        (body.get("response_data"), body.get("list")) if isinstance(body, Mapping) else (None, None)
    )
    for candidate in (body, *nested):
        if isinstance(candidate, Mapping):
            value = candidate.get("id") or candidate.get("Id") or candidate.get("listId")
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
            if connection is not None and connection.status == "expired":
                await self._pause_waiting(connection)
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

    async def _pause_waiting(self, connection: CrmConnection) -> None:
        """The connection expired before its waiting proposals were sent: pause each and wake
        its chat, as when it expires mid-batch (final review M-12). A proposal already paused
        has woken its chat; the wake's key keeps a second run from waking it again."""
        reason, next_step = _expired_reason(connection)
        async with self._conn_factory() as conn:
            rows = await conn.execute(
                text(
                    "SELECT proposal_id FROM crm_write_proposal WHERE connection_id = :c "
                    "AND status IN ('queued', 'sending') ORDER BY created_at, proposal_id "
                    "FOR UPDATE"
                ),
                {"c": connection.connection_id},
            )
            for row in rows.all():
                proposal_id = UUID(str(row.proposal_id))
                await set_proposal_status(conn, proposal_id=proposal_id, status="paused")
                proposal = await get_proposal(conn, proposal_id=proposal_id)
                assert proposal is not None
                if self._artifacts is not None:
                    await queue_crm_writes_paused_turn(
                        conn, self._artifacts, proposal=proposal, reason=reason, next_step=next_step
                    )
                log.info("crm_write.paused", proposal_id=str(proposal_id), reason="expired")

    async def _run_proposal(
        self, crm: _Crm, proposal_id: UUID, context: WorkContext
    ) -> WorkResult | None:
        """Send one proposal's chosen changes; a :class:`WorkResult` stops the task."""
        async with self._conn_factory() as conn:
            writes = await _start_proposal(conn, crm.connection, proposal_id)
        try:
            # Creates first: lists and companies (R-12.7, R-12.11), then people, then the rest. A
            # change that uses one of them names it ``new:<name>`` / ``new:company:<domain>`` /
            # ``new:contact:<email>`` until the create has an id. The id is then kept on that
            # change's row, so a later run never sends the placeholder; when the create did not
            # happen the change is skipped.
            handled: set[UUID] = set()
            for stage in _STAGES:
                picked = [
                    write
                    for write in writes
                    if (stage is None or write.kind in stage)
                    and write.write_id not in handled
                    and not _waits(write)
                ]
                handled.update(write.write_id for write in picked)
                for spec, chunk in _chunks(picked):
                    if context.stop_requested.is_set() or context.lease_lost.is_set():
                        return WorkResult(outcome="interrupted", references={}, requeue=True)
                    await self._send_chunk(crm, spec, chunk)
                if stage is not None and any(_waits(write) for write in writes):
                    async with self._conn_factory() as conn:
                        await _fill_new_lists(conn, crm.connection, proposal_id)
                        await _fill_new_records(conn, proposal_id)
                        writes = await _load_writes(conn, crm.connection, proposal_id)
        except _Stop as stop:
            return await self._stopped(crm, proposal_id, stop)
        async with self._conn_factory() as conn:
            # "Finished" means every change was decided: an add still naming a list not made,
            # or a change still waiting for a record, is skipped, never left waiting (Task 3b
            # review I-1).
            await _skip_adds_to_lists_not_made(conn, crm.connection, proposal_id)
            await _skip_waiting_for_records(conn, proposal_id)
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
        run's check confirms them without sending them again (a stopped check counts as an
        attempt, :meth:`_read_stopped`)."""
        back = await _read(crm, accepted)
        outcomes = {write.write_id: _after_send(write, back[write.write_id]) for write in accepted}
        late = [
            write
            for write in accepted
            if crm.connection.provider == "hubspot"
            and write.kind == "field_update"
            and outcomes[write.write_id].failure_kind == "not_applied"
        ]
        if late:  # HubSpot may apply it a moment later (L-3): read those once more
            await self._sleep(_READ_AGAIN_AFTER_S)
            again = await _read(crm, late)
            outcomes.update({w.write_id: _after_send(w, again[w.write_id]) for w in late})
        await self._record(crm, accepted, outcomes)

    async def _read_stopped(self, writes: Sequence[_Write], stop: _Stop) -> bool:
        """The check before sending met a rate limit or an unreachable CRM: that counts as an
        attempt of each change it read (so the back-off grows), and one at ``MAX_ATTEMPTS`` fails
        ``retryable``. For a change still waiting to be sent it is a send that did not happen; for
        one already sent (``sending``, awaiting confirmation) it is a confirming read that did not
        happen, and at the cap that change is settled as sent but unconfirmed, never sent again
        (final review I-2: an outage must not leave the card "Sending" for ever). ``True`` when
        the run must stop."""
        if stop.kind not in ("rate_limited", "unavailable"):
            return True
        ids = [write.write_id for write in writes]
        async with self._conn_factory() as conn:
            rows = await conn.execute(
                text(
                    "UPDATE crm_write SET attempts = attempts + 1 WHERE write_id = ANY(:ids) "
                    "AND status IN ('queued', 'sending') RETURNING write_id, status, attempts"
                ),
                {"ids": ids},
            )
            spent = [
                row
                for row in rows.all()
                if int(row.attempts) >= self._settings.crm_write_max_attempts
            ]
            unsent = [row.write_id for row in spent if row.status == "queued"]
            unconfirmed = [row.write_id for row in spent if row.status == "sending"]
            if unsent:
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = 'failed', failure_kind = :kind, "
                        "crm_message = :message, crm_response = CAST(:response AS jsonb), "
                        "retryable = true, finished_at = now() WHERE write_id = ANY(:ids)"
                    ),
                    {
                        "ids": unsent,
                        "kind": "rate_limited" if stop.kind == "rate_limited" else "other",
                        **_stop_message(stop),
                    },
                )
            if unconfirmed:
                await conn.execute(
                    text(
                        "UPDATE crm_write SET status = 'failed', failure_kind = 'other', "
                        "crm_message = :message, crm_response = CAST(:response AS jsonb), "
                        "retryable = true, finished_at = now() WHERE write_id = ANY(:ids)"
                    ),
                    {
                        "ids": unconfirmed,
                        "message": UNCONFIRMED_SEND_MESSAGE,
                        "response": _stop_message(stop)["response"],
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
            if not result.successful and _list_gone(call, result):
                await self._fail_gone_list(crm, call, result)
                return []
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
        if not result.successful and await _campaign_gone(crm, write, result):
            await self._fail_gone_list(crm, call, result)
            return []
        refused = _refused_inside(result.data) if result.successful else result.error or "Refused."
        if refused is not None:
            kind = None if result.successful else _refusal_kind(result)
            await self._record(crm, call, {write.write_id: _failed(refused, kind)})
            return []
        if write.kind not in _MAKES:
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
        # whatever happens to the read-back. Its Clue entity is linked only once the create is
        # confirmed (:meth:`_record`), so an unconfirmed record is never the entity's. A list is
        # not a record: it is kept once it is confirmed (:meth:`_record`).
        connection = crm.connection
        async with self._conn_factory() as conn:
            await conn.execute(
                text("UPDATE crm_write SET crm_id = :crm_id WHERE write_id = :id"),
                {"crm_id": created.crm_id, "id": write.write_id},
            )
            if write.kind == _LIST_CREATE:
                return [created]
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

    async def _fail_gone_list(
        self, crm: _Crm, call: Sequence[_Write], result: ExecuteResult
    ) -> None:
        """The CRM no longer has the list or campaign: Clue stops offering it, and every change of
        the call fails in plain words, keeping the CRM's answer (R-11.11 (4), R-12.15)."""
        _, response = crm_reply(result.error or "")
        async with self._conn_factory() as conn:
            await mark_gone(
                conn, connection_id=crm.connection.connection_id, crm_list_id=str(call[0].list_ref)
            )
        await self._record(
            crm,
            call,
            {
                write.write_id: _Outcome(
                    "failed",
                    failure_kind="other",
                    crm_message=(
                        LIST_GONE_MESSAGE
                        if crm.connection.provider == "hubspot"
                        else CAMPAIGN_GONE_MESSAGE
                    ),
                    retryable=False,
                    crm_response=response if response is not None else result.error,
                )
                for write in call
            },
        )

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
        """A call that met a temporary failure or a stop that pauses (an expired or refused
        connection, the budget): its changes wait again, except those that have used up their
        sends (rate limit / unreachable), which fail.
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
                    # A stop that pauses (an expired or refused connection, the budget) came
                    # before any CRM answer: not a send (final review M-9). A temporary stop keeps
                    # its attempt even when Composio raised it, so the back-off grows and the
                    # attempt cap is reached (else it would retry for ever).
                    {"ids": waiting, "unsent": stop.kind not in ("rate_limited", "unavailable")},
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
                        "record_ref = COALESCE(:created, record_ref), finished_at = now() "
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
                        # A create that succeeded names its new record (L9): the write log and
                        # the wake message read it like any other change's record. One that found
                        # the record already there names that record, whose id the changes that
                        # use it then take (R-12.11).
                        "created": (
                            outcome.crm_id
                            if outcome.status == "succeeded" and by_id[write_id].kind in _MAKES
                            else outcome.found_id
                        ),
                    },
                )
                write = by_id[write_id]
                if outcome.found_id is not None and _entity(write) is not None:
                    # Not created by Clue: the record a find matched is the same person or
                    # company, and becomes the Clue entity's record.
                    await record_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        crm_object=write.object,
                        crm_id=outcome.found_id,
                        created_by_clue=False,
                        created_by_write_id=write_id,
                        clue_entity_id=_entity(write),
                    )
                if outcome.status != "succeeded":
                    continue
                if write.kind == _LIST_CREATE and outcome.crm_id is not None:
                    assert write.project_id is not None and write.label is not None
                    await store_list(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        provider=connection.provider,
                        crm_object="company" if write.object == "company" else "contact",
                        crm_list_id=outcome.crm_id,
                        name=write.label,
                        kind=(
                            "hubspot_list"
                            if connection.provider == "hubspot"
                            else "salesforce_campaign"
                        ),
                        created_by_clue=True,
                        created_by_write_id=write_id,
                        project_id=write.project_id,
                    )
                elif write.kind in _CREATES and outcome.crm_id is not None:
                    await record_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        crm_object=write.object,
                        crm_id=outcome.crm_id,
                        created_by_clue=True,
                        created_by_write_id=write_id,
                        clue_entity_id=_entity(write),
                    )
                elif (
                    write.kind == "field_update"
                    and write.record_ref is not None
                    and _entity(write) is not None
                ):
                    # An update links an existing CRM record to the Clue entity it was checked
                    # against (Task 6); Clue did not create it. The write that made the link is
                    # kept, so the finished message can say how many records were linked.
                    await record_link(
                        conn,
                        workspace_id=connection.workspace_id,
                        connection_id=connection.connection_id,
                        crm_object=write.object,
                        crm_id=write.record_ref,
                        created_by_clue=False,
                        created_by_write_id=write_id,
                        clue_entity_id=_entity(write),
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
                    kept = await stored_list(
                        conn,
                        connection_id=connection.connection_id,
                        crm_list_id=str(write.list_ref),
                    )
                    if kept is not None and write.project_id is not None:
                        # A list Clue keeps for another project is now this project's too, so
                        # find_crm_list lists it here (final review).
                        await link_project(
                            conn,
                            list_id=kept.list_id,
                            project_id=write.project_id,
                            workspace_id=connection.workspace_id,
                            linked_by="person_named",
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
            reason, next_step = _expired_reason(crm.connection)
        elif stop.kind == "auth":
            # Clue's Composio key or the connected account is not accepted: a deployment fault
            # or a deleted account, never a reason to fail the person's changes for good.
            log.error(
                "crm_write.composio_refused_connection",
                connection_id=str(crm.connection.connection_id),
                detail=stop.message,
            )
            reason = f"Clue could not use the {crm.name} connection ({stop.message})"
            next_step = (
                "They continue by themselves once the connection works again "
                "(the next approved change retries them)."
            )
        else:
            reason = stop.message
            next_step = (
                f"They continue by themselves when {crm.name}'s daily API allowance "
                "allows it again."
            )
        async with self._conn_factory() as conn:
            await set_proposal_status(conn, proposal_id=proposal_id, status="paused")
            proposal = await get_proposal(conn, proposal_id=proposal_id)
            assert proposal is not None
            if self._artifacts is not None:
                await queue_crm_writes_paused_turn(
                    conn, self._artifacts, proposal=proposal, reason=reason, next_step=next_step
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


#: HubSpot's answer to a membership change of a list deleted in HubSpot (live check L-12):
#: "Attempted to modify membership for deleted lists: [PortalListId{portalId=…, listId=18}];
#: Aborting operations." The list ids it names are read out of it.
_DELETED_LISTS = "Attempted to modify membership for deleted lists"
_DELETED_LIST_ID = re.compile(r"listId=(\d+)")


def _list_gone(call: Sequence[_Write], result: ExecuteResult) -> bool:
    """A membership call HubSpot refused because the list does not exist
    (composio-api-notes.md § Phase 3 shapes: ``ListError.LIST_ID_DOES_NOT_EXIST``) or was
    deleted (R-12.15: the "deleted lists" answer, only when it names this call's list)."""
    if call[0].kind not in _MEMBERSHIP:
        return False
    error = result.error or ""
    if "LIST_ID_DOES_NOT_EXIST" in error:
        return True
    if _DELETED_LISTS not in error:
        return False
    deleted = error.split(_DELETED_LISTS, 1)[1]
    return str(call[0].list_ref) in _DELETED_LIST_ID.findall(deleted)


#: Salesforce's answers to a campaign add or removal naming a record it does not have: a
#: deleted one (``ENTITY_IS_DELETED``) or an id that names nothing
#: (``INVALID_CROSS_REFERENCE_KEY``). Either may be about the contact as well as the campaign;
#: the campaign is read to tell.
_SALESFORCE_MISSING_RECORD = ("ENTITY_IS_DELETED", "INVALID_CROSS_REFERENCE_KEY")


async def _campaign_gone(crm: _Crm, write: _Write, result: ExecuteResult) -> bool:
    """A Salesforce campaign membership change refused because the campaign of this call no
    longer exists (final review: the Salesforce twin of L-12). Salesforce's answer does not say
    which record is missing, so the campaign is read by its id: only an empty answer means gone.
    A failed read, or a campaign still there (the contact was the missing one), is not."""
    if crm.connection.provider != "salesforce" or write.kind not in _MEMBERSHIP:
        return False
    error = result.error or ""
    if not any(code in error for code in _SALESFORCE_MISSING_RECORD):
        return False
    query = f"SELECT Id FROM Campaign WHERE Id = {_soql_text(str(write.list_ref))}"
    try:
        found = await crm.call(_SOQL, {"query": query})
    except _Stop:
        return False
    records = _records(_unwrap(found.data), "records") if found.successful else None
    return records == []


def _expired_reason(connection: CrmConnection) -> tuple[str, str]:
    """The paused wake's reason and what happens next, for an expired connection (R-11.10)."""
    return (
        f"the {_CRM_NAMES[connection.provider]} connection has expired or was revoked",
        "They are not sent: connecting the CRM again creates a new connection, so once the "
        "person reconnects, propose them again.",
    )


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
    return await _load_writes(conn, connection, proposal_id)


#: The argument that names a membership change's list (HubSpot) or campaign (Salesforce).
_LIST_ARGUMENT = {"hubspot": "list_id", "salesforce": "campaign_id"}


async def _fill_new_lists(
    conn: AsyncConnection, connection: CrmConnection, proposal_id: UUID
) -> None:
    """Every list the proposal created gives its id to the adds that name it ``new:<name>``;
    an add to a list whose create failed, was skipped or was not chosen is skipped, never sent
    (R-12.7). A create still undecided leaves its adds waiting."""
    argument = _LIST_ARGUMENT[connection.provider]
    creates = await conn.execute(
        text(
            "SELECT status, crm_id, record_label FROM crm_write "
            "WHERE proposal_id = :id AND kind = 'list_create'"
        ),
        {"id": proposal_id},
    )
    for create in creates.all():
        waiting = {
            "id": proposal_id,
            "argument": argument,
            "placeholder": f"{NEW_LIST_PREFIX}{create.record_label}",
        }
        if create.status == "succeeded" and create.crm_id:
            await conn.execute(
                text(
                    "UPDATE crm_write SET arguments = jsonb_set(arguments, "
                    "ARRAY[CAST(:argument AS text)], to_jsonb(CAST(:crm_id AS text))) "
                    "WHERE proposal_id = :id AND kind = 'list_membership' "
                    "AND status NOT IN ('succeeded', 'failed', 'skipped') "
                    "AND arguments ->> :argument = :placeholder"
                ),
                {**waiting, "crm_id": create.crm_id},
            )
        elif create.status in _TERMINAL:
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'skipped', crm_message = :message, "
                    "finished_at = now() WHERE proposal_id = :id AND kind = 'list_membership' "
                    "AND status NOT IN ('succeeded', 'failed', 'skipped') "
                    "AND arguments ->> :argument = :placeholder"
                ),
                {**waiting, "message": NOT_CREATED_MESSAGE},
            )


async def _skip_adds_to_lists_not_made(
    conn: AsyncConnection, connection: CrmConnection, proposal_id: UUID
) -> None:
    """Skip every undecided add that still names a list by ``new:<name>``."""
    await conn.execute(
        text(
            "UPDATE crm_write SET status = 'skipped', crm_message = :message, finished_at = now() "
            "WHERE proposal_id = :id AND kind = 'list_membership' "
            "AND status NOT IN ('succeeded', 'failed', 'skipped') "
            "AND starts_with(arguments ->> :argument, :prefix)"
        ),
        {
            "id": proposal_id,
            "argument": _LIST_ARGUMENT[connection.provider],
            "prefix": NEW_LIST_PREFIX,
            "message": NOT_CREATED_MESSAGE,
        },
    )


#: The order a proposal's changes are sent in: what others may use is created first (lists and
#: companies, then people, who may be linked to a new company), then everything else.
_STAGES: tuple[tuple[str, ...] | None, ...] = (
    (_LIST_CREATE, "create_company"),
    ("create_contact",),
    None,
)


def _waits(write: _Write) -> bool:
    """The change still names a list or record the proposal has not created yet."""
    return (
        new_list_name(write.list_ref) is not None
        or reference_in(write.spec.slug, write.arguments) is not None
    )


def _not_created_message(reference: str) -> str:
    return (
        COMPANY_NOT_CREATED_MESSAGE
        if reference.startswith(NEW_COMPANY_PREFIX)
        else PERSON_NOT_CREATED_MESSAGE
    )


async def _fill_new_records(conn: AsyncConnection, proposal_id: UUID) -> None:
    """Every company or person the proposal created — or found already there when it came to
    create it — gives its id to the undecided changes that name it ``new:company:<domain>`` /
    ``new:contact:<email>``; a change whose create failed, was skipped without finding the
    record, or was not chosen is skipped, never sent (R-12.11). A create still undecided leaves
    its changes waiting."""
    creates = await conn.execute(
        text(
            "SELECT kind, status, crm_id, record_ref, after_value::text AS after_value "
            "FROM crm_write WHERE proposal_id = :id "
            "AND kind IN ('create_company', 'create_contact')"
        ),
        {"id": proposal_id},
    )
    #: Each reference to a create and the id of its record; ``None`` when it will never have one.
    made: dict[str, str | None] = {}
    for create in creates.all():
        after = json.loads(create.after_value) if create.after_value else None
        reference = created_reference(create.kind, after if isinstance(after, Mapping) else {})
        if reference is None:
            continue
        if create.status == "succeeded" and create.crm_id:
            made[reference] = str(create.crm_id)
        elif create.status == "skipped" and create.record_ref:  # it found the record
            made[reference] = str(create.record_ref)
        elif create.status in _TERMINAL:
            made[reference] = None
    if not made:
        return
    waiting = await conn.execute(
        text(
            "SELECT write_id, slug, arguments::text AS arguments, record_ref, "
            "after_value::text AS after_value FROM crm_write WHERE proposal_id = :id "
            "AND status NOT IN ('succeeded', 'failed', 'skipped')"
        ),
        {"id": proposal_id},
    )
    for row in waiting.all():
        arguments = json.loads(row.arguments)
        reference = reference_in(row.slug, arguments)
        if reference is None or reference not in made:
            continue
        crm_id = made[reference]
        if crm_id is None:
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'skipped', crm_message = :message, "
                    "finished_at = now() WHERE write_id = :id"
                ),
                {"id": row.write_id, "message": _not_created_message(reference)},
            )
            continue
        after = json.loads(row.after_value) if row.after_value else None
        if isinstance(after, Mapping):  # a new person's company link
            after = {key: crm_id if value == reference else value for key, value in after.items()}
        await conn.execute(
            text(
                "UPDATE crm_write SET arguments = CAST(:arguments AS jsonb), "
                "record_ref = :record_ref, after_value = CAST(:after AS jsonb) WHERE write_id = :id"
            ),
            {
                "id": row.write_id,
                "arguments": json.dumps(with_reference_filled(row.slug, arguments, crm_id)),
                "record_ref": crm_id if row.record_ref == reference else row.record_ref,
                "after": None if after is None else json.dumps(after, default=str),
            },
        )


async def _skip_waiting_for_records(conn: AsyncConnection, proposal_id: UUID) -> None:
    """Skip every undecided change that still names a record by ``new:company:`` /
    ``new:contact:``."""
    rows = await conn.execute(
        text(
            "SELECT write_id, slug, arguments::text AS arguments FROM crm_write "
            "WHERE proposal_id = :id AND status NOT IN ('succeeded', 'failed', 'skipped')"
        ),
        {"id": proposal_id},
    )
    for row in rows.all():
        reference = reference_in(row.slug, json.loads(row.arguments))
        if reference is not None:
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'skipped', crm_message = :message, "
                    "finished_at = now() WHERE write_id = :id"
                ),
                {"id": row.write_id, "message": _not_created_message(reference)},
            )


def _entity(write: _Write) -> UUID | None:
    """The change's Clue entity as a link stores it; ``None`` when it names none."""
    if write.clue_entity_id is None:
        return None
    try:
        return UUID(write.clue_entity_id)
    except ValueError:
        return None


async def _load_writes(
    conn: AsyncConnection, connection: CrmConnection, proposal_id: UUID
) -> list[_Write]:
    """The proposal's chosen changes not yet decided, in order."""
    project_id = await conn.scalar(
        text("SELECT project_id FROM crm_write_proposal WHERE proposal_id = :id"),
        {"id": proposal_id},
    )
    rows = await conn.execute(
        text(
            "SELECT write_id, ordinal, slug, arguments::text AS arguments, kind, object, "
            "record_ref, record_label, field, before_value::text AS before_value, "
            "after_value::text AS after_value, attempts, crm_id, clue_entity_id FROM crm_write "
            "WHERE proposal_id = :id AND selected "
            "AND status NOT IN ('succeeded', 'failed', 'skipped') ORDER BY ordinal"
        ),
        {"id": proposal_id},
    )
    writes = []
    for row in rows.all():
        if row.kind == "clue_fields_setup":
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'failed', failure_kind = 'other', "
                    "crm_message = :message, retryable = false, finished_at = now() "
                    "WHERE write_id = :id"
                ),
                {"id": row.write_id, "message": SETUP_NOT_BUILT_MESSAGE},
            )
            continue
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
                label=row.record_label,
                project_id=None if project_id is None else str(project_id),
                clue_entity_id=row.clue_entity_id,
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
