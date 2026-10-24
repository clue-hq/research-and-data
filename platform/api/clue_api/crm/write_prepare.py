"""Turn the changes the agent proposes into the batch a person is asked to allow.

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 plan, Task 4) and the permission card
(``2026-10-22-crm-write-permission-card-design.md`` §3, §5, §6). Rulings: R-6.5 (an overwrite of a
person's value always asks and is never covered by a standing permission), R-6.7 (what a standing
permission covers), R-6.25 call 11 (when the CRM cannot tell who set a value, a person did), R-7.1
(every create is find-then-create), R-8.1/R-8.7 (consent and phone fields are never written; a
person carries only name, job title, company link, work email, buying role and LinkedIn URL).

:func:`prepare_changes` refuses the whole batch (:class:`WriteRefused`) when any change may not be
written, so nothing reaches a card or the write log. The exceptions are a record the CRM does not
have (R-11.7) and a field the object does not have (final review M-2): that change alone is left
out as a :class:`RefusedChange` (``crm_record_not_found`` / ``crm_field_unknown``) and the rest
go on. Otherwise it returns one :class:`PreparedChange`
per (record, field) — a change setting three fields is three — each with the value the CRM holds
today. A change that would not change anything is dropped. Reading before-values is the only CRM
traffic here: batched by object where the CRM has a batch read (R-7.4), paused between calls
(R-7.3), and on Salesforce every call is taken from the org's API budget first (R-7.5).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import (
    ComposioGateway,
    CrmProvider,
    ExecuteResult,
    composio_user_id,
)
from clue_api.crm.connections import CrmConnection
from clue_api.crm.lists import live_list_named, stored_list
from clue_api.crm.targets import TargetAccount, TargetContact, TargetValue, project_targets
from clue_api.crm.write_actions import (
    _SALESFORCE_CONTACT_ARGS,
    CLUE_CAMPAIGN_SETTINGS,
    HUBSPOT_OBJECT_TYPE_IDS,
    NEW_COMPANY_PREFIX,
    NEW_CONTACT_PREFIX,
    NEW_LIST_PREFIX,
    ParsedChange,
    WriteActionSpec,
    WriteNotParsable,
    created_reference,
    field_update_spec,
    find_value,
    is_forbidden_field,
    new_list_name,
    record_reference,
    record_references,
    reference_in,
    scope_key,
    single_field_arguments,
    website_host,
    with_reference_filled,
    write_spec,
)
from clue_api.crm.writes import (
    Grant,
    clue_added_members,
    clue_wrote_current_value,
    covering_grant,
    forget_record_link,
    live_grants,
    same_value,
)
from clue_config import Settings

__all__ = [
    "PERSONAL_DATA_NOT_ALLOWED",
    "PreparedBatch",
    "PreparedChange",
    "ProposedChange",
    "RefusedChange",
    "WriteRefused",
    "card_snapshot",
    "check_against_targets",
    "prepare_changes",
]


@dataclass(frozen=True)
class ProposedChange:
    """One item of what the agent proposes: an allowlisted action and its arguments."""

    slug: str
    arguments: Mapping[str, object]
    reason: str
    source_ref: str | None = None
    reverses_write_id: UUID | None = None
    #: The Clue contact or account this change is about (a person change must name one).
    clue_entity_id: str | None = None


@dataclass(frozen=True)
class PreparedChange:
    write_id: UUID
    #: The action that will be sent: a create that found its record is that object's update.
    spec: WriteActionSpec
    #: The change of this one write: one record and, for a field update, one field.
    parsed: ParsedChange
    field: str | None
    before: object | None
    after: object | None
    overwrites_person: bool
    scope_key: str
    #: ``grant:<id>`` when a standing permission covers it; never for an overwrite.
    covered_by: str | None
    reason: str
    source_ref: str | None
    #: ``spec``'s arguments for exactly this change (what the executor sends).
    arguments: Mapping[str, object]
    #: The CRM's own label of ``field`` (the card never shows a field id).
    field_label: str | None = None
    reverses_write_id: UUID | None = None
    #: Each picklist field's option labels by internal value, for the card only (R-11.5); what
    #: is stored, compared and sent stays the internal value.
    option_labels: Mapping[str, Mapping[str, str]] = dataclasses.field(default_factory=dict)
    #: The Clue contact or account the change is about, when the agent named one.
    clue_entity_id: str | None = None
    #: The claims the written value came from (R-8.7: an erasure can list what reached the CRM).
    source_claim_ids: tuple[UUID, ...] = ()
    #: The name of the list or campaign a membership change names, for the card only (R-12.13):
    #: the one Clue keeps under that id, or the one the same card creates.
    list_name: str | None = None


@dataclass(frozen=True)
class RefusedChange:
    """One proposed change left out of the batch while the rest go on (R-11.7)."""

    #: Its position in the proposed batch, counting from 0.
    index: int
    slug: str
    record_ref: str | None
    #: ``crm_record_not_found``: the read before the card found no such record;
    #: ``crm_field_unknown``: the object has no such field (final review M-2);
    #: ``crm_list_not_kept`` / ``crm_list_gone``: a HubSpot list Clue does not keep, or a kept
    #: one HubSpot no longer has; ``crm_personal_data_not_allowed``: a person value (or a
    #: company's ICP tier) that is not what Clue researched and cleared (R-8.7).
    reason_code: str
    message: str


@dataclass(frozen=True)
class PreparedBatch:
    #: What goes on the card (or is sent under a standing permission).
    changes: list[PreparedChange]
    #: The changes left out, each with why.
    refused: list[RefusedChange]


class WriteRefused(Exception):
    """A proposed change Clue may not write; the batch stops before any card.

    ``reason_code``: ``crm_write_not_allowed`` (not on the allowlist), ``crm_write_not_parsable``,
    ``crm_field_forbidden`` (consent, phone, or a person field outside R-8.7),
    ``crm_value_not_allowed`` (not one of the field's picklist values),
    ``crm_removal_not_allowed`` (a list or campaign member Clue did not add, R-6.25 call 12),
    ``crm_list_exists`` (a list or campaign of that name Clue already keeps on this connection),
    ``crm_read_failed`` (the CRM's answer to a read needed to show the change was an error or not
    the expected shape; an unreadable value is never taken as empty), ``crm_rate_limited`` /
    ``crm_unavailable`` (a read met the CRM's rate limit or no answer: temporary, worth one more
    try later). A record the CRM does not have is not a failed read: it refuses only its own
    change (:class:`RefusedChange`).
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class _Budget(Protocol):
    async def take_call(
        self, conn: AsyncConnection, *, connection: CrmConnection, today: date
    ) -> None: ...


# --- what may be written (R-8.1, R-8.7) ------------------------------------------------------

_PERSON_OBJECTS = frozenset({"contact", "lead"})

#: Person fields Clue may write, by each CRM's own names (R-8.7).
_PERSON_FIELDS: Mapping[CrmProvider, frozenset[str]] = {
    "hubspot": frozenset(
        {
            "firstname",
            "lastname",
            "jobtitle",
            "email",
            "work_email",
            "associatedcompanyid",
            "hs_buying_role",
            "hs_linkedin_url",
        }
    ),
    "salesforce": frozenset({"FirstName", "LastName", "Title", "Email", "AccountId"}),
}
#: A custom person field is allowed when its name or label says it is one of these.
_PERSON_FIELD_WORDS = ("buyingrole", "buyingcommittee", "committeerole", "linkedinurl")
#: Never written on any object, whatever the field is called.
_CONSENT_WORDS = ("optout", "consent", "donotcall")
#: Never written on a person (a company's phone number is not personal data).
_PHONE_WORDS = ("phone", "mobile")

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{1,18}$")
_SOQL_CHUNK = 200
_MAX_LISTED_VALUES = 50

_HUBSPOT_OBJECT_TYPES = {"company": "companies", "contact": "contacts"}
#: HubSpot objects whose current values are read many records per call (R-7.4), and how many
#: per call (composio-api-notes.md § Writes, (f)). Contacts have no batch read with a recorded
#: argument shape, so each is read on its own.
_HUBSPOT_BATCH_READS = {"company": "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES"}
_HUBSPOT_BATCH_READ_SIZE = 100
_SALESFORCE_SOBJECTS = {"account": "Account", "contact": "Contact"}
_CRM_NAMES: Mapping[CrmProvider, str] = {"hubspot": "HubSpot", "salesforce": "Salesforce"}
#: Read alongside a field update's before-values only to name the record on the card and in the
#: write log; never compared, never written. In order of preference.
_DISPLAY_FIELDS: Mapping[CrmProvider, Mapping[str, tuple[str, ...]]] = {
    "hubspot": {"company": ("name", "domain"), "contact": ("firstname", "lastname", "email")},
    "salesforce": {"account": ("Name",), "contact": ("Name", "Email")},
}


@dataclass(frozen=True)
class _FieldMeta:
    label: str
    #: The values a picklist accepts; ``None`` for any other field.
    options: tuple[str, ...] | None
    #: A multi-select picklist: the value is ``;``-separated.
    multi: bool
    #: Each option's label by its value, shown on the card instead of the value (R-11.5).
    option_labels: Mapping[str, str] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True)
class _Item:
    proposed: ProposedChange
    spec: WriteActionSpec
    parsed: ParsedChange
    #: Each written field's claim ids, once the targets check cleared the change.
    claims: Mapping[str, tuple[UUID, ...]] = dataclasses.field(default_factory=dict)
    #: The buying role Clue offers this contact, when the change writes one (composed with the
    #: roles the CRM contact already has once its value is read).
    buying_role: tuple[str, str] | None = None  # (field, Clue's role)
    #: Whose CRM record this change must be (Fix round 1, Critical #1): ``person`` or
    #: ``company``, the record Clue knows the entity by on this connection, and the email (person)
    #: or domain (company) the record must hold when Clue knows no record.
    owner: tuple[str, str | None, str | None] | None = None
    #: Clue's own undo restoring its before-value (ruling #2/#3): no research check applies.
    exempt: bool = False
    #: A new person linked to a company the batch creates (R-12.11) when Clue already knows the
    #: person's company as a CRM record: (the link field, that record). The link passes only when
    #: the create finds exactly that record (:func:`_company_links_not_known`).
    known_company: tuple[str, str] | None = None
    #: The name of the list or campaign a membership change names, when Clue knows it (R-12.13).
    list_name: str | None = None
    #: For the card only: each field's company/account ids by the company's name (R-12.13), as
    #: picklist option labels are shown.
    value_labels: Mapping[str, Mapping[str, str]] = dataclasses.field(default_factory=dict)


def _words(*names: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]", "", name.lower()) for name in names)


def _check_fields(
    provider: CrmProvider, item: _Item, metas: Mapping[str, Mapping[str, _FieldMeta]]
) -> None:
    object_name = item.parsed.object
    person = object_name in _PERSON_OBJECTS
    fields_meta = metas.get(object_name, {})
    for field, value in item.parsed.fields.items():
        meta = fields_meta.get(field)
        label = meta.label if meta else field
        words = _words(field, label)
        forbidden_words = _CONSENT_WORDS + (_PHONE_WORDS if person else ())
        if is_forbidden_field(provider, object_name, field) or any(
            word in words for word in forbidden_words
        ):
            raise WriteRefused(
                "crm_field_forbidden",
                f'Clue never writes "{label}" ({field}): consent and phone fields stay the '
                "customer's own.",
            )
        if (
            person
            and field not in _PERSON_FIELDS[provider]
            and not any(word in words for word in _PERSON_FIELD_WORDS)
        ):
            raise WriteRefused(
                "crm_field_forbidden",
                f'Clue does not write "{label}" ({field}) on a person. Only name, job title, '
                "company link, verified work email, buying role and LinkedIn URL are written.",
            )
        if meta is not None and meta.options is not None:
            _check_value(provider, field, meta, value)


def _check_value(provider: CrmProvider, field: str, meta: _FieldMeta, value: object) -> None:
    if value is None or str(value).strip() == "":
        return  # clearing a picklist is allowed
    values = str(value).split(";") if meta.multi else [str(value)]
    for one in values:
        if one not in (meta.options or ()):
            listed = ", ".join((meta.options or ())[:_MAX_LISTED_VALUES])
            more = " …" if len(meta.options or ()) > _MAX_LISTED_VALUES else ""
            raise WriteRefused(
                "crm_value_not_allowed",
                f'"{one}" is not one of the values of "{meta.label}" ({field}) in '
                f"{_CRM_NAMES[provider]}. Allowed values: {listed}{more}.",
            )


# --- reading the CRM -----------------------------------------------------------------------


class _Reader:
    def __init__(
        self,
        conn: AsyncConnection,
        *,
        gateway: ComposioGateway,
        budget: _Budget | None,
        connection: CrmConnection,
        version: str,
        min_interval_s: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._conn = conn
        self._gateway = gateway
        self._budget = budget
        self._connection = connection
        self._version = version
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._calls = 0

    async def read(self, slug: str, arguments: Mapping[str, Any]) -> Any:
        result = await self.call(slug, arguments)
        if not result.successful:
            raise self._failed(result)
        return _unwrap(result.data)

    async def read_record(self, slug: str, arguments: Mapping[str, Any]) -> Any | None:
        """A read of one record by its id: ``None`` when the CRM says there is no such record
        (HubSpot's 404). Any other failure refuses the batch, like :meth:`read`."""
        result = await self.call(slug, arguments)
        if not result.successful:
            if _record_missing(result):
                return None
            raise self._failed(result)
        return _unwrap(result.data)

    async def call(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult:
        """One read, after the pause between calls (R-7.3) and, on Salesforce, taken from the
        org's API budget (R-7.5). A rate limit or an unreachable CRM refuses the batch as
        temporary; any other refused answer is returned for the caller to judge."""
        if self._calls and self._min_interval_s > 0:
            await self._sleep(self._min_interval_s)
        self._calls += 1
        if self._connection.provider == "salesforce":
            if self._budget is None:
                raise ValueError("Salesforce reads need the API budget.")
            await self._budget.take_call(
                self._conn, connection=self._connection, today=datetime.now(UTC).date()
            )
        result = await self._gateway.execute(
            slug=slug,
            arguments=arguments,
            connected_account_id=self._connection.composio_connected_account_id,
            user_id=composio_user_id(self._connection.workspace_id),
            version=self._version,
        )
        if not result.successful:
            temporary = temporary_failure(result)
            name = _CRM_NAMES[self._connection.provider]
            if temporary == "rate_limited":
                raise WriteRefused(
                    "crm_rate_limited",
                    f"{name} is rate-limiting Clue's reads, so the changes cannot be shown yet: "
                    f"{result.error or 'too many requests'}",
                )
            if temporary == "unavailable":
                raise WriteRefused(
                    "crm_unavailable",
                    f"{name} is not answering, so the changes cannot be shown yet: "
                    f"{result.error or 'no answer'}",
                )
        return result

    def _failed(self, result: ExecuteResult) -> WriteRefused:
        return WriteRefused(
            "crm_read_failed",
            f"Could not read {_CRM_NAMES[self._connection.provider]} to prepare the "
            f"changes: {result.error or 'no answer'}",
        )


def _status_code(result: ExecuteResult) -> int | None:
    """The CRM's HTTP status Composio reports inside a refused call's ``data``."""
    body = result.data
    for _ in range(2):
        if isinstance(body, Mapping) and isinstance(body.get("status_code"), int):
            return int(body["status_code"])
        body = body.get("data") if isinstance(body, Mapping) else None
    return None


_TEMPORARY_CODES = ("REQUEST_LIMIT_EXCEEDED", '"category":"RATE_LIMITS"')


def temporary_failure(result: ExecuteResult) -> Literal["rate_limited", "unavailable"] | None:
    """A refused call that is a rate limit or an unreachable CRM rather than a refusal."""
    status = _status_code(result)
    if status == 429 or any(code in (result.error or "") for code in _TEMPORARY_CODES):
        return "rate_limited"
    if isinstance(status, int) and status >= 500:
        return "unavailable"
    return None


def _record_missing(result: ExecuteResult) -> bool:
    """A refused read that says the record is not there: HubSpot's 404 (``OBJECT_NOT_FOUND``)."""
    return _status_code(result) == 404 or "OBJECT_NOT_FOUND" in (result.error or "")


def _unwrap(data: Any) -> Any:
    """Composio sometimes nests the CRM's body one or two levels down, under ``data``."""
    for _ in range(2):
        if (
            isinstance(data, dict)
            and set(data) <= {"data", "successful", "error"}
            and "data" in data
        ):
            data = data["data"]
    return data


def _unreadable(what: str) -> WriteRefused:
    return WriteRefused(
        "crm_read_failed",
        f"Could not read {what} from the CRM, so the change cannot be shown safely. Nothing "
        "was proposed; try again, or ask the person to check the record.",
    )


def _list(body: Any, key: str, what: str) -> list[Mapping[str, Any]]:
    """The answer's list of records; an answer of any other shape refuses the batch (an
    unreadable answer is never taken as "empty")."""
    items = body.get(key) if isinstance(body, Mapping) else None
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise _unreadable(what)
    return items


async def _field_metas(
    reader: _Reader, provider: CrmProvider, object_name: str
) -> dict[str, _FieldMeta]:
    """Every field of the object with its label and picklist values: one read per object."""
    metas: dict[str, _FieldMeta] = {}
    if provider == "hubspot":
        body = await reader.read(
            "HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE",
            {"objectType": _HUBSPOT_OBJECT_TYPES[object_name]},
        )
        for prop in _list(body, "results", f"the {object_name} fields"):
            options = None
            labels: dict[str, str] = {}
            if prop.get("type") == "enumeration":
                shown = [
                    option
                    for option in prop.get("options") or []
                    if isinstance(option, Mapping) and not option.get("hidden")
                ]
                options = tuple(str(option.get("value")) for option in shown)
                labels = _option_labels(prop.get("options"))
            metas[str(prop.get("name"))] = _FieldMeta(
                str(prop.get("label") or prop.get("name")),
                options,
                prop.get("fieldType") == "checkbox",
                labels,
            )
        return metas
    body = await reader.read(
        "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT", {"object_name": _SALESFORCE_SOBJECTS[object_name]}
    )
    for field in _list(body, "fields", f"the {object_name} fields"):
        kind = field.get("type")
        options = None
        labels = {}
        if kind in ("picklist", "multipicklist"):
            options = tuple(
                str(value.get("value"))
                for value in field.get("picklistValues") or []
                if isinstance(value, Mapping) and value.get("active", True)
            )
            labels = _option_labels(field.get("picklistValues"))
        metas[str(field.get("name"))] = _FieldMeta(
            str(field.get("label") or field.get("name")), options, kind == "multipicklist", labels
        )
    return metas


def _option_labels(options: object) -> dict[str, str]:
    """Each option's label by its value. Inactive or hidden options keep theirs: a value read
    from the CRM may still hold one."""
    if not isinstance(options, list):
        return {}
    return {
        str(option.get("value")): str(option.get("label"))
        for option in options
        if isinstance(option, Mapping) and option.get("label") not in (None, "")
    }


def _soql_text(value: object) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _salesforce_id(value: str) -> str:
    if not _SALESFORCE_ID.match(value):
        raise WriteRefused("crm_write_not_parsable", f"{value!r} is not a Salesforce record id.")
    return value


def _sf_key(record_id: object) -> str:
    """Salesforce answers 18-character ids for 15-character ones."""
    return str(record_id)[:15]


#: Create keys that hold a website: matched as the host they name, never as the string
#: (R-7.1 "companies/accounts by domain"; final review I-5).
_HOST_KEYS = frozenset({"Website", "domain"})


def create_key(key: str, value: object) -> str:
    """What a create is matched on (R-7.1): a website's host, else the value as written, trimmed
    and lower-cased (an email). Empty when there is nothing to match on."""
    if value is None:
        return ""
    return website_host(value) if key in _HOST_KEYS else str(value).strip().lower()


def salesforce_find_query(sobject: str, key: str, value: object, fields: Sequence[str]) -> str:
    """The SOQL that looks for the record a create would duplicate. A website is looked for
    broadly (any spelling that contains its host); :func:`salesforce_match` then keeps only the
    records whose website is that host."""
    select = ", ".join(dict.fromkeys(["Id", *fields, key]))
    if key not in _HOST_KEYS:
        return f"SELECT {select} FROM {sobject} WHERE {key} = {_soql_text(value)} LIMIT 2"
    host = website_host(value)
    for special in ("\\", "%", "_"):
        host = host.replace(special, "\\" + special)
    pattern = "'%" + host.replace("'", "\\'") + "%'"
    return f"SELECT {select} FROM {sobject} WHERE {key} LIKE {pattern} LIMIT {_SOQL_CHUNK}"


def salesforce_match(
    key: str, value: object, records: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    """The record of :func:`salesforce_find_query`'s answer that the create would duplicate."""
    wanted = create_key(key, value)
    return next((r for r in records if create_key(key, r.get(key)) == wanted), None)


def _display_name(
    provider: CrmProvider, object_name: str, values: Mapping[str, object]
) -> str | None:
    """What the record is called today, from the display fields read with its before-values."""

    def text(name: str) -> str | None:
        value = values.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    if provider == "hubspot" and object_name == "contact":
        full = " ".join(part for part in (text("firstname"), text("lastname")) if part)
        return full or text("email")
    return next(
        (found for name in _DISPLAY_FIELDS[provider].get(object_name, ()) if (found := text(name))),
        None,
    )


async def _hubspot_field_values(
    reader: _Reader, object_name: str, record_ref: str, fields: Sequence[str]
) -> Mapping[str, object] | None:
    """The record's values, or ``None`` when HubSpot has no such record."""
    body = await reader.read_record(
        "HUBSPOT_READ_CRM_OBJECT_BY_ID",
        {
            "objectType": _HUBSPOT_OBJECT_TYPES[object_name],
            "objectId": record_ref,
            "properties": list(fields),
        },
    )
    if body is None:
        return None
    properties = body.get("properties") if isinstance(body, Mapping) else None
    if not isinstance(properties, Mapping):
        raise _unreadable(f"the {object_name} {record_ref}")
    return properties


async def hubspot_batch_values(
    call: Callable[[str, Mapping[str, Any]], Awaitable[ExecuteResult]],
    object_name: str,
    wanted: Mapping[str, Sequence[str]],
) -> dict[str, Mapping[str, object]]:
    """The values of ``wanted`` records (id → fields) of an object HubSpot reads many per call
    (R-7.4: up to 100 ids a call). A record the answer leaves out — HubSpot's batch read skips
    one it does not have — is not in the result, nor is any record of a call refused or answered
    in an unexpected shape: the caller reads those one by one, which tells a missing record from
    a failed read. ``call`` makes one read (and raises on a temporary failure)."""
    slug = _HUBSPOT_BATCH_READS.get(object_name)
    found: dict[str, Mapping[str, object]] = {}
    if slug is None:
        return found
    ids = list(wanted)
    for start in range(0, len(ids), _HUBSPOT_BATCH_READ_SIZE):
        chunk = ids[start : start + _HUBSPOT_BATCH_READ_SIZE]
        properties = list(dict.fromkeys(field for rid in chunk for field in wanted[rid]))
        result = await call(
            slug, {"inputs": [{"id": rid} for rid in chunk], "properties": properties}
        )
        records = _batch_records(result.data) if result.successful else None
        if records is not None:
            found.update({rid: records[rid] for rid in chunk if rid in records})
    return found


def _batch_records(data: Any) -> dict[str, Mapping[str, object]] | None:
    """Each record's properties by id in a HubSpot batch read's answer; ``None`` when the answer
    is not of that shape."""
    body = _unwrap(data)
    results = body.get("results") if isinstance(body, Mapping) else None
    if not isinstance(results, list):
        return None
    records: dict[str, Mapping[str, object]] = {}
    for record in results:
        properties = record.get("properties") if isinstance(record, Mapping) else None
        if not isinstance(record, Mapping) or record.get("id") is None:
            return None
        if not isinstance(properties, Mapping):
            return None
        records[str(record["id"])] = properties
    return records


async def _salesforce_field_values(
    reader: _Reader, object_name: str, records: Mapping[str, set[str]]
) -> dict[str, Mapping[str, object]]:
    """Batched SOQL: one query per 200 records of an object. A record the query does not return
    does not exist (or the connected user cannot see it) and is left out."""
    fields = sorted({field for wanted in records.values() for field in wanted})
    ids = sorted(records)
    found: dict[str, Mapping[str, object]] = {}
    for start in range(0, len(ids), _SOQL_CHUNK):
        chunk = ids[start : start + _SOQL_CHUNK]
        query = (
            f"SELECT Id, {', '.join(fields)} FROM {_SALESFORCE_SOBJECTS[object_name]} "
            f"WHERE Id IN ({', '.join(_soql_text(_salesforce_id(i)) for i in chunk)})"
        )
        body = await reader.read("SALESFORCE_RUN_SOQL_QUERY", {"query": query})
        for record in _list(body, "records", f"the {object_name} records"):
            found[_sf_key(record.get("Id"))] = record
    return {
        record_ref: found[_sf_key(record_ref)] for record_ref in ids if _sf_key(record_ref) in found
    }


async def _memberships(
    reader: _Reader, provider: CrmProvider, items: Sequence[_Item]
) -> set[tuple[str, str]]:
    """(list, record) pairs that exist today, for the membership changes proposed."""
    members: set[tuple[str, str]] = set()
    if provider == "hubspot":
        pairs = sorted({(item.parsed.object, str(item.parsed.record_ref)) for item in items})
        for object_name, record_ref in pairs:
            body = await reader.read(
                "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS",
                {"object_type_id": HUBSPOT_OBJECT_TYPE_IDS[object_name], "record_id": record_ref},
            )
            what = f"the lists of {object_name} {record_ref}"
            for membership in _list(body, "results", what):
                members.add((str(membership.get("listId")), record_ref))
        return members
    by_campaign: dict[str, set[str]] = {}
    for item in items:
        by_campaign.setdefault(str(item.parsed.list_ref), set()).add(str(item.parsed.record_ref))
    for campaign, contacts in sorted(by_campaign.items()):
        ordered = sorted(contacts)
        for start in range(0, len(ordered), _SOQL_CHUNK):
            chunk = ordered[start : start + _SOQL_CHUNK]
            query = (
                "SELECT ContactId FROM CampaignMember WHERE CampaignId = "
                f"{_soql_text(_salesforce_id(campaign))} AND ContactId IN "
                f"({', '.join(_soql_text(_salesforce_id(c)) for c in chunk)})"
            )
            body = await reader.read("SALESFORCE_RUN_SOQL_QUERY", {"query": query})
            records = _list(body, "records", f"the members of campaign {campaign}")
            in_campaign = {_sf_key(r.get("ContactId")) for r in records}
            members.update((campaign, c) for c in chunk if _sf_key(c) in in_campaign)
    return members


async def _find_existing(
    reader: _Reader, provider: CrmProvider, item: _Item
) -> tuple[str, Mapping[str, object]] | None:
    """The record a create would duplicate (R-7.1): its id and its current values."""
    assert item.spec.find_existing is not None
    slug, key = item.spec.find_existing
    value = _find_value(item)
    if value is None or str(value).strip() == "":
        return None
    fields = sorted(item.parsed.fields)
    if provider == "hubspot":
        # HubSpot keeps a company's ``domain`` as its bare host: look for that host, so
        # "https://www.acme.com/" finds the company kept as "acme.com" (Review Focus 2).
        wanted = website_host(value) if key in _HOST_KEYS else str(value)
        body = await reader.read(
            slug,
            {
                "filterGroups": [
                    {"filters": [{"propertyName": key, "operator": "EQ", "value": wanted}]}
                ],
                "properties": fields,
                "limit": 2,
            },
        )
        results = _list(body, "results", f"the {item.parsed.object} search")
        if not results:
            return None
        properties = results[0].get("properties")
        if not isinstance(properties, Mapping) or results[0].get("id") is None:
            raise _unreadable(f"the {item.parsed.object} search")
        return str(results[0]["id"]), properties
    if not create_key(key, value):
        return None
    query = salesforce_find_query(_SALESFORCE_SOBJECTS[item.parsed.object], key, value, fields)
    what = f"the {item.parsed.object} search"
    records = _list(await reader.read(slug, {"query": query}), "records", what)
    if any(record.get("Id") is None for record in records):
        raise _unreadable(what)
    match = salesforce_match(key, value, records)
    return (str(match["Id"]), match) if match is not None else None


# --- what Clue researched and cleared (R-8.7 in code, Phase 3 Task 5) -----------------------

PERSONAL_DATA_NOT_ALLOWED = "crm_personal_data_not_allowed"
_NAME_THE_CONTACT = "Name the Clue contact this is about."
_NOT_RESEARCHED = "not what Clue researched"
_NEVER_REMOVES = "Clue only adds its buying role; it never removes one"
_TARGET_CHUNK = 200

#: Each person field Clue may write, the :class:`TargetContact` value it must equal, and the
#: word ``withheld`` names it by.
_PERSON_TARGETS: Mapping[CrmProvider, Mapping[str, tuple[str, str]]] = {
    "hubspot": {
        "firstname": ("first_name", "first name"),
        "lastname": ("last_name", "last name"),
        "jobtitle": ("job_title", "title"),
        "email": ("work_email", "email"),
        "work_email": ("work_email", "email"),
        "hs_linkedin_url": ("linkedin_url", "LinkedIn"),
        "hs_buying_role": ("buying_role", "buying role"),
    },
    "salesforce": {
        "FirstName": ("first_name", "first name"),
        "LastName": ("last_name", "last name"),
        "Title": ("job_title", "title"),
        "Email": ("work_email", "email"),
    },
}
#: The field that links a person to their company: it must be the company Clue knows them by.
_COMPANY_LINK_FIELDS = frozenset({"associatedcompanyid", "AccountId"})
#: A custom person field R-8.7 allows, by the words in its name or label.
_CUSTOM_PERSON_TARGETS = (
    ("linkedinurl", ("linkedin_url", "LinkedIn")),
    ("buyingrole", ("buying_role", "buying role")),
    ("buyingcommittee", ("buying_role", "buying role")),
    ("committeerole", ("buying_role", "buying role")),
)
_ICP_TIER_FIELD = "hs_ideal_customer_profile"
_TARGET_ACCOUNT_FIELD = "hs_is_target_account"
#: Written only from Clue's fit for a named account (ruling #4, R-12.1).
_CLUE_ACCOUNT_FIELDS = frozenset({_ICP_TIER_FIELD, _TARGET_ACCOUNT_FIELD})
_NOT_THE_PERSON = "This CRM record is not the person Clue researched."
_NOT_THE_COMPANY = "This CRM record is not the company Clue researched."
_NOT_AN_UNDO = "This undo does not match a change Clue made."
#: The field a record is recognised by when Clue knows no record id for it.
_OWNER_FIELDS: Mapping[str, Mapping[CrmProvider, str]] = {
    "person": {"hubspot": "email", "salesforce": "Email"},
    "company": {"hubspot": "domain", "salesforce": "Website"},
}


def _person_change(item: _Item) -> bool:
    return item.parsed.object in _PERSON_OBJECTS and item.parsed.change_kind(item.spec) in (
        "create_contact",
        "field_update",
    )


def _company_change(item: _Item) -> bool:
    return item.parsed.object in ("company", "account") and item.parsed.change_kind(item.spec) in (
        "create_company",
        "field_update",
    )


def _normalised(value: object) -> str:
    return " ".join(str(value).split())


def _roles(value: object) -> list[str]:
    """A multi-select value's options, in order, without repeats."""
    if value is None:
        return []
    return list(dict.fromkeys(part.strip() for part in str(value).split(";") if part.strip()))


def _uuid(value: str | None) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _withheld_reason(withheld: Sequence[str], word: str) -> str:
    prefix = f"{word}: "
    return next((w[len(prefix) :] for w in withheld if w.startswith(prefix)), _NOT_RESEARCHED)


async def _owned_entities(
    conn: AsyncConnection, workspace_id: str, ids: set[UUID]
) -> tuple[dict[str, str], set[str]]:
    """``({contact id: its account id}, {account ids})`` of these ids that are live entities of
    this workspace; an id of another workspace (or a merged-away one) is in neither."""
    if not ids:
        return {}, set()
    params = {"ws": workspace_id, "ids": sorted(ids)}
    contacts = {
        str(row.id): str(row.account_entity_id)
        for row in await conn.execute(
            text(
                "SELECT id, account_entity_id FROM contact_entity WHERE workspace_id = :ws "
                "AND merged_into IS NULL AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            params,
        )
    }
    accounts = {
        str(row.id)
        for row in await conn.execute(
            text(
                "SELECT id FROM account_entity WHERE workspace_id = :ws "
                "AND merged_into IS NULL AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            params,
        )
    }
    return contacts, accounts


async def _targets(
    conn: AsyncConnection,
    *,
    connection: CrmConnection,
    project_id: str,
    settings: Settings,
    account_ids: set[str],
    contact_ids: set[str],
) -> tuple[dict[str, TargetAccount], dict[str, TargetContact]]:
    """What :func:`~clue_api.crm.targets.project_targets` offers for exactly these accounts and
    contacts of the project: the same gate the agent read, never a second copy of it."""
    accounts: dict[str, TargetAccount] = {}
    contacts: dict[str, TargetContact] = {}
    ordered = sorted(account_ids)
    for start in range(0, len(ordered), _TARGET_CHUNK):
        page = await project_targets(
            conn,
            workspace_id=connection.workspace_id,
            project_id=project_id,
            connection_id=connection.connection_id,
            provider=connection.provider,
            settings=settings,
            account_ids=ordered[start : start + _TARGET_CHUNK],
            include_contacts=bool(contact_ids),
            limit=_TARGET_CHUNK,
            contacts_limit=max(1, len(contact_ids)),
            contact_ids=contact_ids,
        )
        accounts.update({a.account_entity_id: a for a in page.accounts})
        contacts.update({c.contact_entity_id: c for c in page.contacts})
    return accounts, contacts


def _refused(
    index: int, item: _Item, message: str, code: str = PERSONAL_DATA_NOT_ALLOWED
) -> RefusedChange:
    return RefusedChange(
        index=index,
        slug=item.proposed.slug,
        record_ref=item.parsed.record_ref,
        reason_code=code,
        message=message,
    )


def _owner_field(provider: CrmProvider, item: _Item) -> tuple[str, ...]:
    """The field a change's record is recognised by, read with its before-values."""
    return () if item.owner is None else (_OWNER_FIELDS[item.owner[0]][provider],)


def _owner_values(provider: CrmProvider, item: _Item) -> Mapping[str, object]:
    """A create was found by the email or website it writes, which was checked against the
    research, so the record holds it (a search answer may leave the field out)."""
    if item.spec.find_existing is None:
        return {}
    return {_OWNER_FIELDS[item.owner[0]][provider]: _find_value(item)} if item.owner else {}


def _find_value(item: _Item) -> object | None:
    """What a create is looked for by (:func:`~clue_api.crm.write_actions.find_value`)."""
    assert item.spec.find_existing is not None
    return find_value(item.spec.find_existing[1], item.parsed.fields)


def owner_mismatch(
    provider: CrmProvider, item: _Item, record_ref: str, values: Mapping[str, object]
) -> RefusedChange | None:
    """Whether the CRM record a change writes is the named entity's (Fix round 1, Critical #1):
    the record Clue knows it by on this connection; else, when Clue knows none, a record whose
    own email (person) or domain (company), read before the write, is the researched one.
    ``None`` when it is; the change's refusal otherwise (its index is set by the caller)."""
    if item.owner is None:
        return None
    kind, known, expected = item.owner
    if known is not None:
        same = (
            _sf_key(known) == _sf_key(record_ref)
            if provider == "salesforce"
            else str(known) == str(record_ref)
        )
    else:
        held = values.get(_OWNER_FIELDS[kind][provider])
        if not expected or held in (None, ""):
            same = False
        elif kind == "person":
            same = str(held).strip().lower() == expected.strip().lower()
        else:
            same = website_host(held) == website_host(expected)
    if same:
        return None
    return _refused(-1, item, _NOT_THE_PERSON if kind == "person" else _NOT_THE_COMPANY)


async def _reversed_writes(
    conn: AsyncConnection, connection: CrmConnection, items: Mapping[int, _Item]
) -> dict[str, Mapping[str, Any]]:
    """The field updates Clue made and the CRM accepted on this connection that the batch's
    undos name, by write id (``reverses_write_id`` is never taken on the agent's word)."""
    ids = sorted(
        {
            item.proposed.reverses_write_id
            for item in items.values()
            if item.proposed.reverses_write_id is not None
        }
    )
    if not ids:
        return {}
    rows = await conn.execute(
        text(
            "SELECT write_id, object, record_ref, field, before_value::text AS before_value, "
            "clue_entity_id, reverses_write_id "
            "FROM crm_write WHERE write_id = ANY(:ids) AND workspace_id = :ws "
            "AND connection_id = :connection AND status = 'succeeded' AND kind = 'field_update'"
        ),
        {"ids": ids, "ws": connection.workspace_id, "connection": connection.connection_id},
    )
    return {
        str(row.write_id): {
            **row._mapping,
            "before_value": None if row.before_value is None else json.loads(row.before_value),
        }
        for row in rows
    }


def _undo(item: _Item, reversed_write: Mapping[str, Any] | None) -> _Item | str:
    """Ruling #2/#3: an undo of Clue's own update restores exactly its before-value. The cleared
    undo (no claim ids, the reversed write's Clue entity, ``owner`` unset), the refusal of an
    undo that names no such write of this record and field, or — when the value is not the
    before-value, or the reversed write is itself an undo (fix round 2: re-sending the value Clue
    first wrote is a new write of it, so today's research decides, and a claim rejected, superseded
    or erased since is not sent again) — the change to check like any other, about the Clue entity
    the reversed write named when the change names none."""
    if reversed_write is None:
        return _NOT_AN_UNDO
    if (
        reversed_write["object"] != item.parsed.object
        or str(reversed_write["record_ref"]) != str(item.parsed.record_ref)
        or set(item.parsed.fields) != {reversed_write["field"]}
    ):
        return _NOT_AN_UNDO
    value = item.parsed.fields[str(reversed_write["field"])]
    if reversed_write["reverses_write_id"] is not None or not same_value(
        value, reversed_write["before_value"]
    ):
        if item.proposed.clue_entity_id is not None or reversed_write["clue_entity_id"] is None:
            return item
        named = dataclasses.replace(
            item.proposed, clue_entity_id=str(reversed_write["clue_entity_id"])
        )
        return dataclasses.replace(item, proposed=named)
    proposed = dataclasses.replace(item.proposed, clue_entity_id=reversed_write["clue_entity_id"])
    return dataclasses.replace(item, proposed=proposed, claims={}, owner=None, exempt=True)


def _person_target(provider: CrmProvider, field: str, label: str) -> tuple[str, str] | None:
    known = _PERSON_TARGETS[provider].get(field)
    if known is not None:
        return known
    words = _words(field, label)
    return next((target for word, target in _CUSTOM_PERSON_TARGETS if word in words), None)


def _check_person(
    provider: CrmProvider,
    item: _Item,
    contact: TargetContact,
    account: TargetAccount | None,
    metas: Mapping[str, _FieldMeta],
) -> _Item | str:
    """The change with each field's claim ids, or why it may not be written."""
    claims: dict[str, tuple[UUID, ...]] = {}
    buying_role: tuple[str, str] | None = None
    as_researched: dict[str, str] = {}
    known_company: tuple[str, str] | None = None
    value_labels: dict[str, Mapping[str, str]] = {}
    for field, value in item.parsed.fields.items():
        meta = metas.get(field)
        label = meta.label if meta else field
        named = f"{label} ({field})"
        if field in _COMPANY_LINK_FIELDS:
            reference = record_reference(value)
            known = account.crm_record_id if account is not None else None
            if reference is not None:  # a company the batch creates (R-12.11): by its website
                domain = account.domain if account is not None else None
                if domain and reference != NEW_COMPANY_PREFIX + website_host(domain):
                    return f"{named}: not the company Clue knows this person by."
                if known is not None:  # it must turn out to be that record: checked once found
                    known_company = (field, known)
                continue
            if known is not None and _sf_key(known) != _sf_key(str(value).strip()):
                return f"{named}: not the company Clue knows this person by."
            if known is not None and account is not None:  # shown by its name (R-12.13)
                value_labels[field] = {str(value).strip(): account.name}
            continue
        target = _person_target(provider, field, label)
        if target is None:
            return f"{named}: {_NOT_RESEARCHED}."
        attribute, word = target
        offered: TargetValue | None = getattr(contact, attribute)
        if offered is None:
            return f"{named}: {_withheld_reason(contact.withheld, word)}."
        if attribute == "buying_role":
            if offered.value not in _roles(value):
                return f"{named}: {_NOT_RESEARCHED}."
            buying_role = (field, offered.value)
        elif attribute == "work_email":
            if str(value).strip().lower() != offered.value.strip().lower():
                return f"{named}: {_NOT_RESEARCHED}."
        elif _normalised(value) != _normalised(offered.value):
            return f"{named}: {_NOT_RESEARCHED}."
        if attribute != "buying_role":
            as_researched[field] = offered.value
        claims[field] = offered.claim_ids
    if item.parsed.change_kind(item.spec) == "create_contact" and not any(
        _person_target(provider, f, f) == ("work_email", "email") for f in item.parsed.fields
    ):
        return "A contact is created only with its verified work email."
    # Ruling #5: what reaches the CRM is Clue's own spelling, not the agent's.
    item = _with_values(item, as_researched)
    email = contact.work_email.value if contact.work_email is not None else None
    return dataclasses.replace(
        item,
        claims=claims,
        buying_role=buying_role,
        owner=("person", contact.crm_record_id, email),
        known_company=known_company,
        value_labels={**item.value_labels, **value_labels},
    )


def _with_values(item: _Item, values: Mapping[str, object]) -> _Item:
    """``item`` with these fields set to these values, in its parsed fields and in the arguments
    sent (an update's properties, a create's own or custom properties; on Salesforce under the
    action's argument name)."""
    if not values:
        return item
    arguments: dict[str, Any] = {
        key: (dict(value) if isinstance(value, Mapping) else value)
        for key, value in item.proposed.arguments.items()
    }
    inputs = arguments.get("inputs")
    if isinstance(inputs, list) and inputs and isinstance(inputs[0], Mapping):
        first = dict(inputs[0])
        first["properties"] = dict(first.get("properties") or {})
        arguments["inputs"] = [first, *inputs[1:]]
    for field, value in values.items():
        names = [field, *(arg for arg, sf in _SALESFORCE_CONTACT_ARGS.items() if sf == field)]
        holders = [arguments]
        if isinstance(arguments.get("inputs"), list):
            holders.append(arguments["inputs"][0]["properties"])
        for nested in ("custom_properties", "custom_fields", "properties"):
            if isinstance(arguments.get(nested), dict):
                holders.append(arguments[nested])
        for holder in holders:
            name = next((n for n in names if n in holder), None)
            if name is not None:
                holder[name] = value
                break
    fields = {**item.parsed.fields, **values}
    return dataclasses.replace(
        item,
        proposed=dataclasses.replace(item.proposed, arguments=arguments),
        parsed=dataclasses.replace(item.parsed, fields=fields),
    )


def _check_company(
    item: _Item, account: TargetAccount, metas: Mapping[str, _FieldMeta]
) -> _Item | str:
    claims: dict[str, tuple[UUID, ...]] = {}
    for field, value in item.parsed.fields.items():
        meta = metas.get(field)
        named = f"{meta.label if meta else field} ({field})"
        if field == _ICP_TIER_FIELD:
            tier = account.hubspot_icp_tier
            if tier is None:
                reason = next(
                    (w.split(": ", 1)[1] for w in account.withheld),
                    "Clue has no fit for this account in this project",
                )
                return f"{named}: {reason}."
            if str(value).strip() != tier.value:
                return f"{named}: not the tier of Clue's fit for this account."
            claims[field] = tier.claim_ids
        elif field == _TARGET_ACCOUNT_FIELD and not (
            value is True or str(value).strip().lower() == "true"
        ):
            return f"{named}: Clue only sets it to true."
    if item.spec.find_existing is not None:  # a create: it must be this company's website
        key = item.spec.find_existing[1]
        if not account.domain or website_host(item.parsed.fields.get(key)) != website_host(
            account.domain
        ):
            return _NOT_THE_COMPANY
    return dataclasses.replace(
        item, claims=claims, owner=("company", account.crm_record_id, account.domain)
    )


async def check_against_targets(
    conn: AsyncConnection,
    *,
    connection: CrmConnection,
    project_id: str,
    settings: Settings,
    items: Mapping[int, _Item],
    metas: Mapping[str, Mapping[str, _FieldMeta]],
    reader: _Reader | None = None,
) -> tuple[dict[int, _Item], list[RefusedChange]]:
    """R-8.7 in code. A change that creates or updates a person must name the Clue contact it is
    about, and each person value it writes must be the one ``read_crm_targets`` offers for that
    contact in this project (an email compared without case, everything else with its spaces
    normalised). A company change that names its Clue account may set the ICP tier only to the
    tier of the project's fit, and the target-account flag only to true. Each change that is not
    is refused on its own, naming the field and why, never the value. The rest go on, carrying
    the claim ids their values came from.

    A create of an account Clue already knows in the CRM is refused (update it instead), unless
    ``reader`` reads that record and the CRM no longer has it: the stale link is forgotten and
    the create goes ahead as one of an account Clue knows no record for."""
    provider = connection.provider
    cleared: dict[int, _Item] = {}
    refused: list[RefusedChange] = []
    # Undos first (ruling #2/#3, fix round 2): Clue's own undo is cleared as it is; any other
    # change naming a reversed write is checked below, about the entity that write named.
    reversed_writes = await _reversed_writes(conn, connection, items)
    pending: dict[int, _Item] = {}
    for index, item in items.items():
        if (
            item.proposed.reverses_write_id is not None
            and item.parsed.change_kind(item.spec) == "field_update"
        ):
            undo = _undo(item, reversed_writes.get(str(item.proposed.reverses_write_id)))
            if isinstance(undo, str):
                refused.append(_refused(index, item, undo, "crm_write_not_parsable"))
                continue
            if undo.exempt:
                cleared[index] = undo
                continue
            item = undo
        pending[index] = item
    items = pending

    named = {
        uid
        for item in items.values()
        if (_person_change(item) or _company_change(item))
        and (uid := _uuid(item.proposed.clue_entity_id)) is not None
    }
    owned_contacts, owned_accounts = await _owned_entities(conn, connection.workspace_id, named)
    person_ids = {
        str(_uuid(item.proposed.clue_entity_id))
        for item in items.values()
        if _person_change(item) and str(_uuid(item.proposed.clue_entity_id)) in owned_contacts
    }
    company_ids = {
        str(_uuid(item.proposed.clue_entity_id))
        for item in items.values()
        if _company_change(item) and str(_uuid(item.proposed.clue_entity_id)) in owned_accounts
    }
    accounts, contacts = await _targets(
        conn,
        connection=connection,
        project_id=project_id,
        settings=settings,
        account_ids={owned_contacts[c] for c in person_ids} | company_ids,
        contact_ids=person_ids,
    )
    if reader is not None:
        await _forget_deleted_accounts(conn, reader, connection, items, accounts)

    for index, item in items.items():
        entity = _uuid(item.proposed.clue_entity_id)
        entity_id = str(entity) if entity is not None else None
        object_metas = metas.get(item.parsed.object, {})
        checked: _Item | str = item
        if _person_change(item):
            if item.proposed.clue_entity_id is None:
                checked = _NAME_THE_CONTACT
            elif entity_id not in owned_contacts:
                checked = "The Clue contact named is not a contact of this workspace."
            elif entity_id not in contacts:
                checked = "That Clue contact is not one of this project's researched contacts."
            else:
                contact = contacts[entity_id]
                checked = _check_person(
                    provider, item, contact, accounts.get(contact.account_entity_id), object_metas
                )
        elif _company_change(item) and item.proposed.clue_entity_id is None:
            unnamed = sorted(_CLUE_ACCOUNT_FIELDS & set(item.parsed.fields))
            if unnamed:
                meta = object_metas.get(unnamed[0])
                checked = (
                    f"{meta.label if meta else unnamed[0]} ({unnamed[0]}): it comes only from "
                    "Clue's fit; name the Clue account it is for (clue_entity_id)."
                )
        elif _company_change(item) and item.proposed.clue_entity_id is not None:
            if entity_id not in owned_accounts:
                checked = "The Clue account named is not an account of this workspace."
            elif entity_id not in accounts:
                checked = "That Clue account is not one of this project's accounts."
            elif (
                item.spec.find_existing is not None
                and (known := accounts[entity_id].crm_record_id) is not None
            ):
                # Clue knows this account's CRM record: it is updated, never created again.
                refused.append(
                    _refused(
                        index,
                        item,
                        f"This account is already in {_CRM_NAMES[provider]} as {known}. Update "
                        "that record instead of creating it.",
                        "crm_write_not_parsable",
                    )
                )
                continue
            else:
                checked = _check_company(item, accounts[entity_id], object_metas)
        if isinstance(checked, str):
            refused.append(_refused(index, item, checked))
        else:
            cleared[index] = checked
    return dict(sorted(cleared.items())), refused


async def _forget_deleted_accounts(
    conn: AsyncConnection,
    reader: _Reader,
    connection: CrmConnection,
    items: Mapping[int, _Item],
    accounts: dict[str, TargetAccount],
) -> None:
    """For each account a change creates although Clue knows its CRM record: read that record by
    its id; when the CRM says it is not there, forget the link and treat the account as having
    no record. A read that fails any other way (rate limit, no answer) keeps the link, so the
    create is refused as before."""
    for item in items.values():
        entity = _uuid(item.proposed.clue_entity_id)
        account = accounts.get(str(entity)) if entity is not None else None
        if (
            account is None
            or account.crm_record_id is None
            or not _company_change(item)
            or item.spec.find_existing is None
        ):
            continue
        known = account.crm_record_id
        try:
            if connection.provider == "hubspot":
                gone = (
                    await _hubspot_field_values(reader, item.parsed.object, known, ["name"]) is None
                )
            else:
                gone = not await _salesforce_field_values(
                    reader, item.parsed.object, {known: {"Name"}}
                )
        except WriteRefused:
            continue
        if gone:
            await forget_record_link(
                conn,
                connection_id=connection.connection_id,
                crm_object=item.parsed.object,
                crm_id=known,
            )
            accounts[account.account_entity_id] = dataclasses.replace(account, crm_record_id=None)


def _with_buying_role(
    index: int, item: _Item, current: Mapping[str, object]
) -> _Item | RefusedChange:
    """The change with its buying role composed: the roles the CRM contact already has, then
    Clue's own (Task 1 ruling: the field is multi-select, and Clue only adds). The agent may give
    Clue's role alone, or the whole value; a value that names a role neither Clue nor the CRM has,
    or leaves out one the contact has, is refused."""
    if item.buying_role is None:
        return item
    field, role = item.buying_role
    proposed = _roles(item.parsed.fields.get(field))
    held = _roles(current.get(field))
    named = f"Buying role ({field})"
    if role not in proposed or any(r != role and r not in held for r in proposed):
        return _refused(index, item, f"{named}: {_NOT_RESEARCHED}.")
    if proposed != [role] and any(r not in proposed for r in held):
        return _refused(index, item, f"{named}: {_NEVER_REMOVES}.")
    composed = ";".join([*held, *([] if role in held else [role])])
    fields = {**item.parsed.fields, field: composed}
    return dataclasses.replace(item, parsed=dataclasses.replace(item.parsed, fields=fields))


# --- preparing -----------------------------------------------------------------------------


def _parse(provider: CrmProvider, change: ProposedChange) -> _Item:
    spec = write_spec(provider, change.slug)
    if spec is None:
        raise WriteRefused(
            "crm_write_not_allowed",
            f"{change.slug} is not a change Clue may propose to {_CRM_NAMES[provider]}.",
        )
    try:
        parsed = spec.parse(change.arguments)
    except WriteNotParsable as exc:
        raise WriteRefused("crm_write_not_parsable", f"{change.slug}: {exc}") from exc
    if provider == "salesforce":
        for field in parsed.fields:
            if not _IDENTIFIER.match(field):
                raise WriteRefused(
                    "crm_write_not_parsable", f"{field!r} is not a Salesforce field name."
                )
    return _Item(change, spec, parsed)


def _check_once_per_record_field(items: Sequence[_Item]) -> None:
    seen: set[tuple[object, ...]] = set()
    for item in items:
        parsed = item.parsed
        keys: list[tuple[object, ...]]
        if parsed.record_ref is None:
            continue
        if parsed.fields:
            keys = [(parsed.object, parsed.record_ref, field) for field in parsed.fields]
        else:
            keys = [(parsed.object, parsed.record_ref, "list", parsed.list_ref)]
        for key in keys:
            if key in seen:
                raise WriteRefused(
                    "crm_write_not_parsable",
                    f"{parsed.label} is changed twice in one batch; propose each field once.",
                )
            seen.add(key)


def _check_once_per_created_record(items: Sequence[_Item]) -> None:
    """Two creates of one record (same email, same website host) in a batch would both pass the
    search before either exists (final review I-5)."""
    seen: set[tuple[str, str]] = set()
    for item in items:
        # The value other changes refer to the record by (R-12.11): one record, one create.
        made = created_reference(item.parsed.change_kind(item.spec), item.parsed.fields)
        if made is None:
            continue
        company = made.startswith(NEW_COMPANY_PREFIX)
        key = "domain" if company else "email"
        value = made.removeprefix(NEW_COMPANY_PREFIX if company else NEW_CONTACT_PREFIX)
        if (item.parsed.object, value) in seen:
            raise WriteRefused(
                "crm_write_not_parsable",
                f'The {_noun(item.parsed.object, 1)} with {key} "{value}" is proposed twice in '
                "this batch; propose each record once.",
            )
        seen.add((item.parsed.object, value))


async def _check_removals(
    conn: AsyncConnection, connection: CrmConnection, project_id: str, items: Sequence[_Item]
) -> None:
    """Clue removes only members it added itself (R-6.25 call 12), for this batch's project: a
    list several projects use keeps each project's members its own (R-11.11)."""
    removals = [
        (str(item.parsed.list_ref), str(item.parsed.record_ref), item.parsed.label)
        for item in items
        if item.parsed.change_kind(item.spec) == "list_removal"
    ]
    added = await clue_added_members(
        conn,
        connection_id=connection.connection_id,
        pairs=[(list_ref, record) for list_ref, record, _ in removals],
        project_id=project_id,
    )
    for list_ref, record, label in removals:
        if (list_ref, record) not in added:
            target = "list" if connection.provider == "hubspot" else "campaign"
            raise WriteRefused(
                "crm_removal_not_allowed",
                f"Clue only removes members it added itself, and it did not add {label} to the "
                f"{target} {list_ref}. Ask the person to remove it in "
                f"{_CRM_NAMES[connection.provider]} if they want it gone.",
            )


#: Said for a change to a HubSpot list Clue does not keep (fix round 1 ruling).
LIST_NOT_KEPT_MESSAGE = "Clue does not keep this list yet. Link it first with link_crm_list."
#: Said for a change to a kept list HubSpot no longer has (R-11.11 (4)).
LIST_GONE_MESSAGE = "The list no longer exists in HubSpot; find it by name or create it again."


async def _with_list_objects(
    conn: AsyncConnection, connection: CrmConnection, items: Sequence[_Item]
) -> tuple[list[_Item], dict[int, RefusedChange]]:
    """A HubSpot list holds one object type, which its membership action does not name: read it
    from the list Clue keeps (a company list holds companies). A change to a list Clue does not
    keep (``crm_list_not_kept``: the person names one with ``link_crm_list`` first) or to a kept
    list HubSpot no longer has (``crm_list_gone``) is refused on its own.

    An add to ``new:<name>`` (R-12.7) is to the list the same batch creates under exactly that
    name: it holds that create's object. One that names no create, or a removal from a list not
    made yet, is refused on its own (``crm_write_not_parsable``).

    Each membership change carries the name of its list or campaign for the card (R-12.13): the
    create's, or the name Clue keeps it under (a Salesforce campaign Clue does not keep is shown
    by its id)."""
    resolved: list[_Item] = []
    refused: dict[int, RefusedChange] = {}
    created = {
        item.parsed.label: item
        for item in items
        if item.parsed.change_kind(item.spec) == "list_create"
    }
    for index, item in enumerate(items):
        kind = item.parsed.change_kind(item.spec)
        name = new_list_name(item.parsed.list_ref)
        if kind in ("list_membership", "list_removal") and name is not None:
            create = created.get(name)
            if kind == "list_removal" or create is None:
                refused[index] = RefusedChange(
                    index=index,
                    slug=item.proposed.slug,
                    record_ref=item.parsed.record_ref,
                    reason_code="crm_write_not_parsable",
                    message=(
                        f'"{item.parsed.list_ref}" names no list this batch creates: '
                        f"{NEW_LIST_PREFIX}<name> must be the exact name of a list or campaign "
                        "created in the same call, and is used only to add to it."
                    ),
                )
            else:
                parsed = dataclasses.replace(item.parsed, object=create.parsed.object)
                item = dataclasses.replace(item, parsed=parsed, list_name=create.parsed.label)
        elif connection.provider == "hubspot" and kind in ("list_membership", "list_removal"):
            kept = await stored_list(
                conn, connection_id=connection.connection_id, crm_list_id=str(item.parsed.list_ref)
            )
            if kept is None or kept.gone_at is not None:
                code, message = (
                    ("crm_list_not_kept", LIST_NOT_KEPT_MESSAGE)
                    if kept is None
                    else ("crm_list_gone", LIST_GONE_MESSAGE)
                )
                refused[index] = RefusedChange(
                    index=index,
                    slug=item.proposed.slug,
                    record_ref=item.parsed.record_ref,
                    reason_code=code,
                    message=message,
                )
            else:
                parsed = dataclasses.replace(item.parsed, object=kept.crm_object)
                item = dataclasses.replace(item, parsed=parsed, list_name=kept.name)
        elif kind in ("list_membership", "list_removal"):  # a Salesforce campaign
            kept = await stored_list(
                conn, connection_id=connection.connection_id, crm_list_id=str(item.parsed.list_ref)
            )
            if kept is not None:
                item = dataclasses.replace(item, list_name=kept.name)
        resolved.append(item)
    return resolved, refused


#: Where a record the batch creates may be used (R-12.11).
_REFERENCE_PLACES = (
    f"{NEW_COMPANY_PREFIX}<domain> is used only to add a new company to a HubSpot list or to "
    f"link a new person to their new company, and {NEW_CONTACT_PREFIX}<email> only to add a new "
    "person to a Salesforce campaign"
)


def _with_record_references(items: Sequence[_Item]) -> tuple[list[_Item], dict[int, RefusedChange]]:
    """A change may use a company or person the same batch creates by ``new:company:<domain>`` /
    ``new:contact:<email>`` (R-12.11), in the one place its action allows. Each such reference
    is kept spelled as Clue matches it, so the executor finds it exactly, and an add names the
    record by its create's name. A reference that names no create of the batch, or stands in
    any other place, refuses its own change (``crm_write_not_parsable``)."""
    creates: dict[str, _Item] = {}
    for item in items:
        made = created_reference(item.parsed.change_kind(item.spec), item.parsed.fields)
        if made is not None:
            creates.setdefault(made, item)
    resolved: list[_Item] = []
    refused: dict[int, RefusedChange] = {}
    for index, item in enumerate(items):
        found = record_references(item.proposed.arguments)
        if not found:
            resolved.append(item)
            continue
        reference = reference_in(item.proposed.slug, item.proposed.arguments)
        others = list(found)
        if reference is not None:
            others.remove(reference)
        create = creates.get(reference) if reference is not None else None
        kind = item.parsed.change_kind(item.spec)
        message: str | None = None
        if others:
            message = f'"{others[0]}" cannot be used here: {_REFERENCE_PLACES}.'
        elif create is None:
            message = (
                f'"{reference}" names no record this batch creates: it must be spelled exactly '
                "like the domain or email of a create in the same call."
            )
        elif kind == "list_membership" and create.parsed.object != item.parsed.object:
            message = (
                f"The list holds {_noun(item.parsed.object, 2)}, so "
                f"{_noun(create.parsed.object, 1)} {reference} cannot be added to it."
            )
        if message is not None:
            refused[index] = RefusedChange(
                index=index,
                slug=item.proposed.slug,
                record_ref=item.parsed.record_ref,
                reason_code="crm_write_not_parsable",
                message=message,
            )
            resolved.append(item)
            continue
        assert create is not None and reference is not None
        label = create.parsed.label if kind == "list_membership" else item.parsed.label
        resolved.append(_with_reference(item, reference, label=label))
    return resolved, refused


def _with_reference(item: _Item, value: str, *, label: str | None = None) -> _Item:
    """``item`` with its record reference replaced by ``value`` (the reference as Clue spells
    it, or the id of the record it names), in what is sent and in what the card shows."""
    arguments = with_reference_filled(item.proposed.slug, item.proposed.arguments, value)
    parsed = dataclasses.replace(
        item.spec.parse(arguments),
        object=item.parsed.object,
        label=item.parsed.label if label is None else label,
    )
    proposed = dataclasses.replace(item.proposed, arguments=arguments)
    return dataclasses.replace(item, proposed=proposed, parsed=parsed)


async def _check_list_creates(
    conn: AsyncConnection, connection: CrmConnection, items: Sequence[_Item]
) -> None:
    """One list of a name per connection: a name Clue already keeps, or proposed twice in one
    batch, is refused (a list the CRM no longer has may be created again)."""
    target = "list" if connection.provider == "hubspot" else "campaign"
    seen: set[str] = set()
    for item in items:
        if item.parsed.change_kind(item.spec) != "list_create":
            continue
        name = item.parsed.label
        if name.lower() in seen:
            raise WriteRefused(
                "crm_write_not_parsable",
                f'The {target} "{name}" is created twice in this batch; propose it once.',
            )
        seen.add(name.lower())
        kept = await live_list_named(conn, connection_id=connection.connection_id, name=name)
        if kept is not None:
            raise WriteRefused(
                "crm_list_exists",
                f'Clue already keeps the {target} "{kept.name}" ({kept.crm_list_id}) in '
                f"{_CRM_NAMES[connection.provider]}. Use it instead of creating another.",
            )


class _Builder:
    def __init__(
        self,
        conn: AsyncConnection,
        connection: CrmConnection,
        grants: Sequence[Grant],
        metas: Mapping[str, Mapping[str, _FieldMeta]],
    ) -> None:
        self._conn = conn
        self._connection = connection
        self._grants = grants
        self._metas = metas
        self.prepared: list[PreparedChange] = []

    async def field(
        self,
        item: _Item,
        spec: WriteActionSpec,
        record_ref: str,
        field: str,
        before: object,
        after: object,
    ) -> None:
        if same_value(before, after):
            return  # nothing would change
        empty = same_value(before, None)
        overwrites = not empty and not await clue_wrote_current_value(
            self._conn,
            connection_id=self._connection.connection_id,
            record_ref=record_ref,
            field=field,
            value=before,
        )
        parsed = dataclasses.replace(
            item.parsed, record_ref=record_ref, fields={field: after}, kind=None
        )
        meta = self._metas.get(parsed.object, {}).get(field)
        self._add(
            item,
            spec,
            parsed,
            field=field,
            before=None if empty else before,
            after=after,
            overwrites=overwrites,
            arguments=single_field_arguments(spec, record_ref, field, after),
            field_label=meta.label if meta else field,
            option_labels=self._option_labels(item, parsed.object, [field]),
        )

    def whole(self, item: _Item, *, before: object, after: object) -> None:
        self._add(
            item,
            item.spec,
            item.parsed,
            field=None,
            before=before,
            after=after,
            overwrites=False,
            arguments=dict(item.proposed.arguments),
            field_label=None,
            option_labels=self._option_labels(item, item.parsed.object, list(item.parsed.fields)),
        )

    def _option_labels(
        self, item: _Item, object_name: str, fields: Sequence[str]
    ) -> dict[str, Mapping[str, str]]:
        """Each field's labels for the card: its picklist options, and a company id by the
        company's name (R-12.13)."""
        metas = self._metas.get(object_name, {})
        labels: dict[str, Mapping[str, str]] = {}
        for field in fields:
            merged = {
                **(metas[field].option_labels if field in metas else {}),
                **item.value_labels.get(field, {}),
            }
            if merged:
                labels[field] = merged
        return labels

    def _add(
        self,
        item: _Item,
        spec: WriteActionSpec,
        parsed: ParsedChange,
        *,
        field: str | None,
        before: object,
        after: object,
        overwrites: bool,
        arguments: Mapping[str, object],
        field_label: str | None,
        option_labels: Mapping[str, Mapping[str, str]],
    ) -> None:
        scope = scope_key(spec, parsed, field)
        grant = (
            None if overwrites else covering_grant(self._grants, scope, parsed.change_kind(spec))
        )
        self.prepared.append(
            PreparedChange(
                write_id=uuid4(),
                spec=spec,
                parsed=parsed,
                field=field,
                before=before,
                after=after,
                overwrites_person=overwrites,
                scope_key=scope,
                covered_by=None if grant is None else f"grant:{grant}",
                reason=item.proposed.reason,
                source_ref=item.proposed.source_ref,
                arguments=arguments,
                field_label=field_label,
                reverses_write_id=item.proposed.reverses_write_id,
                option_labels=option_labels,
                clue_entity_id=item.proposed.clue_entity_id,
                list_name=item.list_name,
                source_claim_ids=(
                    item.claims.get(field, ())
                    if field is not None
                    else tuple(dict.fromkeys(cid for ids in item.claims.values() for cid in ids))
                ),
            )
        )


async def prepare_changes(
    conn: AsyncConnection,
    *,
    gateway: ComposioGateway,
    budget: _Budget | None,
    connection: CrmConnection,
    proposal_id: UUID,
    project_id: str,
    changes: Sequence[ProposedChange],
    version: str,
    settings: Settings,
    min_interval_s: float = 0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> PreparedBatch:
    """Check, read and scope a proposed batch; refuse it whole when any change may not be written,
    except a change whose record the CRM does not have, which alone is refused (R-11.7).

    ``project_id`` is the project the batch is proposed for (a removal may take off only a member
    that project's proposals added). ``version`` is the pinned Composio toolkit version of the
    connection's CRM; ``min_interval_s`` is the pause between its CRM reads
    (``CLUE_CRM_WRITE_MIN_INTERVAL_S``, the same pause the executor keeps between its calls).
    ``settings`` holds the fit bands and verification posture the targets read uses: a person
    value, and a company's ICP tier, is written only as :mod:`clue_api.crm.targets` offers it.
    Writes nothing but the Salesforce budget's call count and the forgetting of a record link
    whose CRM record is gone (:func:`check_against_targets`); the caller logs the result with
    :func:`clue_api.crm.writes.insert_writes` under ``proposal_id``.
    """
    del proposal_id  # the caller logs the prepared changes under it
    provider = connection.provider
    items, list_refused = await _with_list_objects(
        conn, connection, [_parse(provider, change) for change in changes]
    )
    items, record_refused = _with_record_references(items)
    # Each of these changes alone is left out; a misplaced record reference says so first.
    alone = {**list_refused, **record_refused}
    _check_once_per_record_field(items)
    _check_once_per_created_record(items)
    await _check_list_creates(conn, connection, items)

    reader = _Reader(
        conn,
        gateway=gateway,
        budget=budget,
        connection=connection,
        version=version,
        min_interval_s=min_interval_s,
        sleep=sleep,
    )
    metas: dict[str, dict[str, _FieldMeta]] = {}
    for object_name in dict.fromkeys(item.parsed.object for item in items if item.parsed.fields):
        metas[object_name] = await _field_metas(reader, provider, object_name)
    for item in items:
        _check_fields(provider, item, metas)
    await _check_removals(
        conn,
        connection,
        project_id,
        [item for index, item in enumerate(items) if index not in alone],
    )

    # A field the object does not have refuses only its own change (final review M-2), as a
    # missing record does (R-11.7), and so does a change to a list Clue cannot use: the agent
    # learns it before any card, the rest go on.
    refused: list[RefusedChange] = list(alone.values())
    kept: dict[int, _Item] = {}
    for index, item in enumerate(items):
        if index in alone:
            continue
        unknown = next((f for f in item.parsed.fields if f not in metas[item.parsed.object]), None)
        if unknown is None:
            kept[index] = item
        else:
            refused.append(_field_unknown(provider, index, item, unknown))
    # R-8.7 in code: a person value (and a company's ICP tier) only as Clue researched and
    # cleared it. Each change that is not is refused on its own; the rest go on.
    cleared, person_refused = await check_against_targets(
        conn,
        connection=connection,
        project_id=project_id,
        settings=settings,
        items=kept,
        metas=metas,
        reader=reader,
    )
    kept = cleared
    refused.extend(person_refused)

    # R-12.11: a create that finds its record already there gives that record's id to the
    # changes that use it, before anything is read for them.
    used = {ref for item in kept.values() if (ref := _reference(item)) is not None}
    looked_up: dict[int, tuple[str, Mapping[str, object]] | None] = {}
    found_ids: dict[str, str] = {}
    for index, item in kept.items():
        own = created_reference(item.parsed.change_kind(item.spec), item.parsed.fields)
        if own is None or own not in used:
            continue
        hit = looked_up[index] = await _find_existing(reader, provider, item)
        if hit is not None and (
            owner_mismatch(provider, item, hit[0], {**hit[1], **_owner_values(provider, item)})
            is None
        ):
            found_ids[own] = hit[0]
    for index, item in kept.items():
        reference = _reference(item)
        if reference is not None and reference in found_ids:
            kept[index] = _with_reference(item, found_ids[reference])
    kept = _with_created_company_names(kept, found_ids)
    for index in _company_links_not_known(provider, kept):
        refused.append(
            _refused(
                index,
                kept.pop(index),
                "The company link: not the company Clue knows this person by. Link the person to "
                "the CRM company read_crm_targets gives for their account.",
            )
        )

    grants = await live_grants(conn, connection_id=connection.connection_id)
    builder = _Builder(conn, connection, grants, metas)

    # Before-values: field updates in batches per object where the CRM has a batch read
    # (HubSpot companies, every Salesforce object), else per record (HubSpot contacts).
    updates = [i for i in kept.values() if i.parsed.change_kind(i.spec) == "field_update"]
    current: dict[tuple[str, str], Mapping[str, object]] = {}
    if provider == "hubspot":
        by_record: dict[str, dict[str, list[str]]] = {}
        for item in updates:
            display = (
                *_DISPLAY_FIELDS[provider].get(item.parsed.object, ()),
                *_owner_field(provider, item),
            )
            fields = by_record.setdefault(item.parsed.object, {}).setdefault(
                str(item.parsed.record_ref), []
            )
            fields.extend(f for f in (*item.parsed.fields, *display) if f not in fields)
        for object_name, record_fields in by_record.items():
            batch = await hubspot_batch_values(reader.call, object_name, record_fields)
            for record_ref, fields in record_fields.items():
                values = batch.get(record_ref)
                if values is None:
                    values = await _hubspot_field_values(reader, object_name, record_ref, fields)
                if values is not None:
                    current[(object_name, record_ref)] = values
    else:
        by_object: dict[str, dict[str, set[str]]] = {}
        for item in updates:
            records = by_object.setdefault(item.parsed.object, {})
            wanted_fields = records.setdefault(str(item.parsed.record_ref), set())
            wanted_fields.update(item.parsed.fields)
            wanted_fields.update(_DISPLAY_FIELDS[provider].get(item.parsed.object, ()))
            wanted_fields.update(_owner_field(provider, item))
        for object_name, records in by_object.items():
            for record_ref, values in (
                await _salesforce_field_values(reader, object_name, records)
            ).items():
                current[(object_name, record_ref)] = values

    # A list this batch creates has no members yet: nothing to read for its adds.
    memberships_proposed = [
        item
        for item in kept.values()
        if item.parsed.change_kind(item.spec) in ("list_membership", "list_removal")
        and new_list_name(item.parsed.list_ref) is None
        and _reference(item) is None  # nor has a record not made yet
    ]
    members = (
        await _memberships(reader, provider, memberships_proposed)
        if memberships_proposed
        else set()
    )

    starts: dict[int, int] = {}
    for index, item in kept.items():
        starts[index] = len(builder.prepared)
        kind = item.parsed.change_kind(item.spec)
        if kind == "field_update":
            record_ref = str(item.parsed.record_ref)
            if (item.parsed.object, record_ref) not in current:
                refused.append(_record_not_found(provider, index, item, record_ref))
                continue
            values = current[(item.parsed.object, record_ref)]
            mismatch = owner_mismatch(provider, item, record_ref, values)
            if mismatch is not None:
                refused.append(dataclasses.replace(mismatch, index=index))
                continue
            composed = _with_buying_role(index, item, values)
            if isinstance(composed, RefusedChange):
                refused.append(composed)
                continue
            item = composed
            # Named by what the record is called today; its id only when the read holds nothing.
            label = _display_name(provider, item.parsed.object, values) or item.parsed.label
            item = dataclasses.replace(item, parsed=dataclasses.replace(item.parsed, label=label))
            for field, after in item.parsed.fields.items():
                await builder.field(item, item.spec, record_ref, field, values.get(field), after)
        elif kind == "list_membership" and new_list_name(item.parsed.list_ref) is not None:
            # Kept as parsed (``new:<name>``, no stray spaces), so the executor finds it by the
            # create's name exactly (Task 3b review I-1).
            builder.whole(
                _with_arguments(item, _LIST_ARGUMENTS, str(item.parsed.list_ref)),
                before=False,
                after=True,
            )
        elif kind == "list_membership" and _reference(item) is not None:
            builder.whole(item, before=False, after=True)  # a record not made yet is in no list
        elif kind in ("list_membership", "list_removal"):
            before = (str(item.parsed.list_ref), str(item.parsed.record_ref)) in members
            after = kind == "list_membership"
            if before != after:
                builder.whole(item, before=before, after=after)
        elif kind == "list_create":
            # Nothing to read: the list is new (a kept one of that name was refused above).
            # The list is made under the name the card shows; a Salesforce campaign is made
            # active, "In Progress" (R-12.9). What is stored is what is sent, on every try.
            made: dict[str, object] = {**item.proposed.arguments, "name": item.parsed.label}
            new_list: dict[str, object] = {"name": item.parsed.label}
            if provider == "salesforce":
                made.update(CLUE_CAMPAIGN_SETTINGS)
                new_list.update(CLUE_CAMPAIGN_SETTINGS)
            item = dataclasses.replace(
                item, proposed=dataclasses.replace(item.proposed, arguments=made)
            )
            builder.whole(item, before=None, after=new_list)
        elif kind in ("create_contact", "create_company"):
            found = (
                looked_up[index]
                if index in looked_up
                else await _find_existing(reader, provider, item)
            )
            if found is not None:
                mismatch = owner_mismatch(
                    provider, item, found[0], {**found[1], **_owner_values(provider, item)}
                )
                if mismatch is not None:
                    refused.append(dataclasses.replace(mismatch, index=index))
                    continue
            composed = _with_buying_role(index, item, found[1] if found is not None else {})
            if isinstance(composed, RefusedChange):
                refused.append(composed)
                continue
            item = composed
            if found is None:
                builder.whole(item, before=None, after=dict(item.parsed.fields))
                continue
            record_ref, values = found
            update = field_update_spec(provider, item.parsed.object)
            assert item.spec.find_existing is not None
            match_key = item.spec.find_existing[1]
            for field, after in item.parsed.fields.items():
                held = values.get(field)
                if field == match_key and create_key(field, held) == create_key(field, after):
                    continue  # the website it was found by, spelled another way: not a change
                await builder.field(item, update, record_ref, field, held, after)
        else:  # link_duplicate has no action until Phase 3
            raise WriteRefused("crm_write_not_allowed", f"{kind} cannot be proposed yet.")
    prepared = _without_changes_of_records_not_made(kept, builder.prepared, starts, refused)
    # A list is created before anything is added to it: creates come first, on the card and in
    # the order the executor sends (R-12.7).
    ordered = sorted(prepared, key=lambda c: c.parsed.change_kind(c.spec) != "list_create")
    return PreparedBatch(ordered, sorted(refused, key=lambda r: r.index))


def _with_created_company_names(
    kept: Mapping[int, _Item], found_ids: Mapping[str, str]
) -> dict[int, _Item]:
    """R-12.13: a person's company link that names a company the card creates (by its reference,
    or by the id that create found) is shown on the card by that create's name."""
    names: dict[str, str] = {}
    for item in kept.values():
        made = created_reference(item.parsed.change_kind(item.spec), item.parsed.fields)
        if made is not None and item.parsed.change_kind(item.spec) == "create_company":
            names[made] = item.parsed.label
            if made in found_ids:
                names[found_ids[made]] = item.parsed.label
    labelled: dict[int, _Item] = {}
    for index, item in kept.items():
        extra = {
            field: {str(value): names[str(value)]}
            for field, value in item.parsed.fields.items()
            if field in _COMPANY_LINK_FIELDS and str(value) in names
        }
        if extra and _person_change(item):
            item = dataclasses.replace(item, value_labels={**item.value_labels, **extra})
        labelled[index] = item
    return labelled


def _company_links_not_known(provider: CrmProvider, kept: Mapping[int, _Item]) -> list[int]:
    """The new people linked to a company the batch creates although Clue already knows their
    company as another CRM record (R-8.7 with R-12.11): the link still names the create (it
    found nothing, so it would make a duplicate) or names the record it found, which is not the
    known one."""
    wrong = []
    for index, item in kept.items():
        if item.known_company is None:
            continue
        field, known = item.known_company
        linked = item.parsed.fields.get(field)
        if record_reference(linked) is not None or not same_record(provider, known, linked):
            wrong.append(index)
    return wrong


def same_record(provider: CrmProvider, known: str, value: object) -> bool:
    """Two CRM ids name one record (Salesforce answers 18 characters for 15)."""
    text_value = str(value or "").strip()
    if provider == "salesforce":
        return _sf_key(known) == _sf_key(text_value)
    return str(known) == text_value


def _reference(item: _Item) -> str | None:
    """The record of the batch a change uses before it exists (R-12.11), else ``None``."""
    return reference_in(item.proposed.slug, item.proposed.arguments)


def _without_changes_of_records_not_made(
    kept: Mapping[int, _Item],
    prepared: Sequence[PreparedChange],
    starts: Mapping[int, int],
    refused: list[RefusedChange],
) -> list[PreparedChange]:
    """The prepared changes without those that use a record whose create is not on the card
    (refused, or left out): each of those is refused on its own, and so is what uses it in turn
    (a campaign add of a person linked to a company that is not created). ``starts`` is where
    each kept change's prepared changes begin."""
    order = list(starts)
    added = {
        index: list(prepared[starts[index] : starts[order[i + 1]] if i + 1 < len(order) else None])
        for i, index in enumerate(order)
    }
    made = {
        ref
        for index, changes in added.items()
        if changes
        and changes[0].parsed.change_kind(changes[0].spec) in ("create_contact", "create_company")
        and (
            ref := created_reference(
                changes[0].parsed.change_kind(changes[0].spec), kept[index].parsed.fields
            )
        )
        is not None
    }
    dropped: set[int] = set()
    changed = True
    while changed:
        changed = False
        for index, changes in added.items():
            reference = _reference(kept[index])
            if index in dropped or not changes or reference is None or reference in made:
                continue
            dropped.add(index)
            changed = True
            what = "company" if reference.startswith(NEW_COMPANY_PREFIX) else "person"
            refused.append(
                _refused(
                    index,
                    kept[index],
                    f"The {what} it needs ({reference}) is not created by this batch, so it is "
                    "not proposed.",
                    "crm_write_not_parsable",
                )
            )
            own = created_reference(
                changes[0].parsed.change_kind(changes[0].spec), kept[index].parsed.fields
            )
            made.discard(own or "")
    return [
        change for index, changes in added.items() if index not in dropped for change in changes
    ]


#: The argument that names a membership change's list (HubSpot) or campaign (Salesforce).
_LIST_ARGUMENTS = ("list_id", "campaign_id")


def _with_arguments(item: _Item, names: Sequence[str], value: str) -> _Item:
    """``item`` with the one of ``names`` it carries set to ``value``."""
    arguments = dict(item.proposed.arguments)
    for name in names:
        if name in arguments:
            arguments[name] = value
    return dataclasses.replace(
        item, proposed=dataclasses.replace(item.proposed, arguments=arguments)
    )


def _field_unknown(provider: CrmProvider, index: int, item: _Item, field: str) -> RefusedChange:
    what = "property" if provider == "hubspot" else "field"
    return RefusedChange(
        index=index,
        slug=item.proposed.slug,
        record_ref=item.parsed.record_ref,
        reason_code="crm_field_unknown",
        message=(f"{_CRM_NAMES[provider]} {_noun(item.parsed.object, 2)} have no {what} {field}."),
    )


def _record_not_found(
    provider: CrmProvider, index: int, item: _Item, record_ref: str
) -> RefusedChange:
    return RefusedChange(
        index=index,
        slug=item.proposed.slug,
        record_ref=record_ref,
        reason_code="crm_record_not_found",
        message=f"{_CRM_NAMES[provider]} has no {_noun(item.parsed.object, 1)} {record_ref}.",
    )


# --- the card (card spec §3, §5, §6) -------------------------------------------------------

_NOUNS: Mapping[str, tuple[str, str]] = {
    "company": ("company", "companies"),
    "account": ("account", "accounts"),
    "contact": ("contact", "contacts"),
    "lead": ("lead", "leads"),
}


def _noun(object_name: str, count: int) -> str:
    one, many = _NOUNS.get(object_name, (object_name, f"{object_name}s"))
    return one if count == 1 else many


def _display(value: object) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "Empty"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _labelled(labels: Mapping[str, str] | None, value: object) -> object:
    """A picklist value as its option label (a company id as its company's name); a value with
    no option shows as it is."""
    if labels and isinstance(value, int) and not isinstance(value, bool):
        return labels.get(str(value), value)
    if not labels or not isinstance(value, str):
        return value
    if value in labels:
        return labels[value]
    if ";" in value:  # a multi-select value
        return "; ".join(labels.get(one, one) for one in value.split(";"))
    return value


def _shown(change: PreparedChange, value: object) -> object:
    """``value`` of ``change`` as the card shows it: option labels instead of internal values."""
    if not change.option_labels:
        return value
    if isinstance(value, Mapping):  # a create's fields
        return {key: _labelled(change.option_labels.get(key), one) for key, one in value.items()}
    if change.field is None:
        return value
    return _labelled(change.option_labels.get(change.field), value)


def _counts(values: Sequence[object]) -> str:
    counted = Counter(_display(value) for value in values)
    return ", ".join(f"{value} ({count})" for value, count in sorted(counted.items()))


def _title(provider: CrmProvider, change: PreparedChange, count: int) -> str:
    kind = change.parsed.change_kind(change.spec)
    target = "list" if provider == "hubspot" else "campaign"
    people = _noun("contact", count)
    members = _noun(change.parsed.object, count)
    if kind == "list_create":
        return f'Create the {target} "{change.parsed.label}"'
    if kind == "list_membership":
        return f'Add {count} {members} to the {target} "{_list_shown(change)}"'
    if kind == "list_removal":
        return f'Remove {count} {members} from the {target} "{_list_shown(change)}"'
    if kind == "field_update":
        return f'Set "{change.field_label}" on {count} {_noun(change.spec.object, count)}'
    if kind == "create_contact":
        return f"Create {count} {people}"
    if kind == "create_company":
        return f"Create {count} {_noun(change.spec.object, count)}"
    return f"Mark {count} possible duplicate{'' if count == 1 else 's'}"


def _phrase(provider: CrmProvider, change: PreparedChange) -> str:
    kind = change.parsed.change_kind(change.spec)
    target = "lists" if provider == "hubspot" else "campaigns"
    if kind == "list_create":
        return f"creating Clue {target}"
    # One scope covers every list and campaign, of companies or contacts (R-12.8).
    if kind == "list_membership":
        return "adding records to Clue lists and campaigns"
    if kind == "list_removal":
        return "removing records from Clue lists and campaigns"
    if kind == "field_update":
        return f'setting "{change.field_label}" on {_noun(change.spec.object, 2)}'
    if kind == "create_contact":
        return "creating contacts"
    if kind == "create_company":
        return f"creating {_noun(change.spec.object, 2)}"
    return "marking possible duplicates"


def _list_shown(change: PreparedChange) -> str | None:
    """The list a membership change names on the card: by its name (R-12.13) when Clue keeps it
    or the card creates it, else by its id."""
    return change.list_name or new_list_name(change.parsed.list_ref) or change.parsed.list_ref


def _group_object(provider: CrmProvider, change: PreparedChange) -> str:
    if change.parsed.change_kind(change.spec) == "list_create":
        return "list" if provider == "hubspot" else "campaign"
    return change.parsed.object


def _reason(changes: Sequence[PreparedChange]) -> str:
    return " ".join(dict.fromkeys(change.reason.strip() for change in changes if change.reason))


def card_snapshot(
    prepared: Sequence[PreparedChange], *, provider: CrmProvider, project_name: str
) -> dict[str, Any]:
    """What the permission card shows while it asks (card spec §6).

    Changes a standing permission covers never appear. The rest are grouped by action and field
    (and list); every overwrite of a person's value is listed on its own, unticked (R-6.5), and
    never offered an "Always allow".
    """
    shown = [change for change in prepared if change.covered_by is None]
    grouped: dict[tuple[object, ...], list[PreparedChange]] = {}
    overwrites: list[PreparedChange] = []
    for change in shown:
        if change.overwrites_person:
            overwrites.append(change)
            continue
        kind = change.parsed.change_kind(change.spec)
        key = (
            kind,
            change.parsed.object,
            change.field,
            # Each list created is its own group, named.
            change.parsed.label if kind == "list_create" else change.parsed.list_ref,
        )
        grouped.setdefault(key, []).append(change)

    groups: list[dict[str, Any]] = []
    for changes in grouped.values():
        first = changes[0]
        count = len(changes)
        kind = first.parsed.change_kind(first.spec)
        summary = None
        if kind == "list_create" and provider == "salesforce":
            summary = f'Active, status "{CLUE_CAMPAIGN_SETTINGS["status"]}"'
        if first.field is not None:
            befores = [change.before for change in changes]
            before_text = (
                "Empty today"
                if all(same_value(b, None) for b in befores)
                else _counts([_shown(c, c.before) for c in changes])
            )
            summary = f"{before_text} → {_counts([_shown(c, c.after) for c in changes])}"
        groups.append(
            {
                "kind": kind,
                # What the group's records are: a list created is a list (or campaign).
                "object": _group_object(provider, first),
                "field": first.field,
                "field_label": first.field_label,
                "list_ref": _list_shown(first),
                "title": _title(provider, first, count),
                "count": count,
                "value_summary": summary,
                "reason": _reason(changes),
                "records": [
                    {
                        "write_id": str(change.write_id),
                        "record_ref": change.parsed.record_ref,
                        "name": change.parsed.label,
                        "before": _shown(change, change.before),
                        "after": _shown(change, change.after),
                    }
                    for change in changes
                ],
                "scope_key": first.scope_key,
                "always_allow": _phrase(provider, first),
                "selected": True,
            }
        )

    standing: dict[str, str] = {}
    for group in groups:
        standing.setdefault(group["scope_key"], group["always_allow"])

    count = len(overwrites)
    return {
        "crm": provider,
        "project_name": project_name,
        "state": "asking",
        "title": f"Clue wants to update {_CRM_NAMES[provider]}",
        "description": f'For "{project_name}". Nothing is sent until you allow it.',
        "groups": groups,
        "overwrites_heading": (
            f"{count} change{'s' if count != 1 else ''} overwrite"
            f"{'s' if count == 1 else ''} a value a person set"
            if count
            else None
        ),
        "overwrites": [
            {
                "write_id": str(change.write_id),
                "record_ref": change.parsed.record_ref,
                "name": change.parsed.label,
                "field": change.field,
                "field_label": change.field_label,
                "before": _shown(change, change.before),
                "after": _shown(change, change.after),
                "set_by": None,
                "set_at": None,
                "set_by_text": "Who set it isn't known",
                "reason": change.reason,
                "selected": False,
            }
            for change in overwrites
        ],
        "standing_permissions": [
            {"scope_key": scope, "phrase": phrase, "selected": False}
            for scope, phrase in standing.items()
        ],
        "allow_count": sum(group["count"] for group in groups),
        "caption": "Any member of this workspace can answer.",
    }
