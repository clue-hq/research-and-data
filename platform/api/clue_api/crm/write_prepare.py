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
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import (
    ComposioGateway,
    CrmProvider,
    ExecuteResult,
    composio_user_id,
)
from clue_api.crm.connections import CrmConnection
from clue_api.crm.lists import live_list_named, stored_list
from clue_api.crm.write_actions import (
    CLUE_CAMPAIGN_SETTINGS,
    HUBSPOT_OBJECT_TYPE_IDS,
    NEW_LIST_PREFIX,
    ParsedChange,
    WriteActionSpec,
    WriteNotParsable,
    field_update_spec,
    is_forbidden_field,
    new_list_name,
    scope_key,
    single_field_arguments,
    write_spec,
)
from clue_api.crm.writes import (
    Grant,
    clue_added_members,
    clue_wrote_current_value,
    covering_grant,
    live_grants,
    same_value,
)

__all__ = [
    "PreparedBatch",
    "PreparedChange",
    "ProposedChange",
    "RefusedChange",
    "WriteRefused",
    "card_snapshot",
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
    #: one HubSpot no longer has.
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


def website_host(value: object) -> str:
    """A website as the lower-case host it names: ``https://www.Acme.com/about`` is
    ``acme.com``. No scheme, ``www.``, port, path, query or trailing slash."""
    host = str(value or "").strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = re.split(r"[/?#]", host, maxsplit=1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    host = host.strip(".")
    return host.removeprefix("www.")


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
    value = item.parsed.fields.get(key)
    if value is None or str(value).strip() == "":
        return None
    fields = sorted(item.parsed.fields)
    if provider == "hubspot":
        body = await reader.read(
            slug,
            {
                "filterGroups": [
                    {"filters": [{"propertyName": key, "operator": "EQ", "value": str(value)}]}
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
        if item.spec.find_existing is None:
            continue
        key = item.spec.find_existing[1]
        value = create_key(key, item.parsed.fields.get(key))
        if not value:
            continue
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
    made yet, is refused on its own (``crm_write_not_parsable``)."""
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
            elif create.parsed.object != item.parsed.object:
                parsed = dataclasses.replace(item.parsed, object=create.parsed.object)
                item = dataclasses.replace(item, parsed=parsed)
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
            elif kept.crm_object != item.parsed.object:
                parsed = dataclasses.replace(item.parsed, object=kept.crm_object)
                item = dataclasses.replace(item, parsed=parsed)
        resolved.append(item)
    return resolved, refused


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
            option_labels=self._option_labels(parsed.object, [field]),
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
            option_labels=self._option_labels(item.parsed.object, list(item.parsed.fields)),
        )

    def _option_labels(
        self, object_name: str, fields: Sequence[str]
    ) -> dict[str, Mapping[str, str]]:
        metas = self._metas.get(object_name, {})
        return {
            field: metas[field].option_labels
            for field in fields
            if field in metas and metas[field].option_labels
        }

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
    min_interval_s: float = 0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> PreparedBatch:
    """Check, read and scope a proposed batch; refuse it whole when any change may not be written,
    except a change whose record the CRM does not have, which alone is refused (R-11.7).

    ``project_id`` is the project the batch is proposed for (a removal may take off only a member
    that project's proposals added). ``version`` is the pinned Composio toolkit version of the
    connection's CRM; ``min_interval_s`` is the pause between its CRM reads
    (``CLUE_CRM_WRITE_MIN_INTERVAL_S``, the same pause the executor keeps between its calls).
    Writes nothing but the Salesforce budget's call count; the caller logs the result with
    :func:`clue_api.crm.writes.insert_writes` under ``proposal_id``.
    """
    del proposal_id  # the caller logs the prepared changes under it
    provider = connection.provider
    items, list_refused = await _with_list_objects(
        conn, connection, [_parse(provider, change) for change in changes]
    )
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
        [item for index, item in enumerate(items) if index not in list_refused],
    )

    # A field the object does not have refuses only its own change (final review M-2), as a
    # missing record does (R-11.7), and so does a change to a list Clue cannot use: the agent
    # learns it before any card, the rest go on.
    refused: list[RefusedChange] = list(list_refused.values())
    kept: dict[int, _Item] = {}
    for index, item in enumerate(items):
        if index in list_refused:
            continue
        unknown = next((f for f in item.parsed.fields if f not in metas[item.parsed.object]), None)
        if unknown is None:
            kept[index] = item
        else:
            refused.append(_field_unknown(provider, index, item, unknown))

    grants = await live_grants(conn, connection_id=connection.connection_id)
    builder = _Builder(conn, connection, grants, metas)

    # Before-values: field updates in batches per object where the CRM has a batch read
    # (HubSpot companies, every Salesforce object), else per record (HubSpot contacts).
    updates = [i for i in kept.values() if i.parsed.change_kind(i.spec) == "field_update"]
    current: dict[tuple[str, str], Mapping[str, object]] = {}
    if provider == "hubspot":
        by_record: dict[str, dict[str, list[str]]] = {}
        for item in updates:
            display = _DISPLAY_FIELDS[provider].get(item.parsed.object, ())
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
    ]
    members = (
        await _memberships(reader, provider, memberships_proposed)
        if memberships_proposed
        else set()
    )

    for index, item in kept.items():
        kind = item.parsed.change_kind(item.spec)
        if kind == "field_update":
            record_ref = str(item.parsed.record_ref)
            if (item.parsed.object, record_ref) not in current:
                refused.append(_record_not_found(provider, index, item, record_ref))
                continue
            values = current[(item.parsed.object, record_ref)]
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
            after: dict[str, object] = {"name": item.parsed.label}
            if provider == "salesforce":
                made.update(CLUE_CAMPAIGN_SETTINGS)
                after.update(CLUE_CAMPAIGN_SETTINGS)
            item = dataclasses.replace(
                item, proposed=dataclasses.replace(item.proposed, arguments=made)
            )
            builder.whole(item, before=None, after=after)
        elif kind in ("create_contact", "create_company"):
            found = await _find_existing(reader, provider, item)
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
    # A list is created before anything is added to it: creates come first, on the card and in
    # the order the executor sends (R-12.7).
    ordered = sorted(builder.prepared, key=lambda c: c.parsed.change_kind(c.spec) != "list_create")
    return PreparedBatch(ordered, sorted(refused, key=lambda r: r.index))


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
    """A picklist value as its option label; a value with no option shows as it is."""
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
    """The list a membership change names on the card: a list not made yet by its name."""
    return new_list_name(change.parsed.list_ref) or change.parsed.list_ref


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
