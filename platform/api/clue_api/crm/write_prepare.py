"""Turn the changes the agent proposes into the batch a person is asked to allow.

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 plan, Task 4) and the permission card
(``2026-10-22-crm-write-permission-card-design.md`` §3, §5, §6). Rulings: R-6.5 (an overwrite of a
person's value always asks and is never covered by a standing permission), R-6.7 (what a standing
permission covers), R-6.25 call 11 (when the CRM cannot tell who set a value, a person did), R-7.1
(every create is find-then-create), R-8.1/R-8.7 (consent and phone fields are never written; a
person carries only name, job title, company link, work email, buying role and LinkedIn URL).

:func:`prepare_changes` refuses the whole batch (:class:`WriteRefused`) when any change may not be
written, so nothing reaches a card or the write log. Otherwise it returns one
:class:`PreparedChange` per (record, field) — a change setting three fields is three — each with
the value the CRM holds today. A change that would not change anything is dropped. Reading
before-values is the only CRM traffic here, and on Salesforce every call is taken from the
org's API budget first (R-7.5).
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import ComposioGateway, CrmProvider, composio_user_id
from clue_api.crm.connections import CrmConnection
from clue_api.crm.write_actions import (
    ParsedChange,
    WriteActionSpec,
    WriteNotParsable,
    field_update_spec,
    is_forbidden_field,
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
    "PreparedChange",
    "ProposedChange",
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


class WriteRefused(Exception):
    """A proposed change Clue may not write; the batch stops before any card.

    ``reason_code``: ``crm_write_not_allowed`` (not on the allowlist), ``crm_write_not_parsable``,
    ``crm_field_forbidden`` (consent, phone, or a person field outside R-8.7),
    ``crm_value_not_allowed`` (not one of the field's picklist values),
    ``crm_removal_not_allowed`` (a list or campaign member Clue did not add, R-6.25 call 12),
    ``crm_read_failed`` (the CRM's answer to a read needed to show the change was an error or not
    the expected shape; an unreadable value is never taken as empty).
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
_HUBSPOT_CONTACT_OBJECT_TYPE_ID = "0-1"
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
    ) -> None:
        self._conn = conn
        self._gateway = gateway
        self._budget = budget
        self._connection = connection
        self._version = version

    async def read(self, slug: str, arguments: Mapping[str, Any]) -> Any:
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
            raise WriteRefused(
                "crm_read_failed",
                f"Could not read {_CRM_NAMES[self._connection.provider]} to prepare the "
                f"changes: {result.error or 'no answer'}",
            )
        return _unwrap(result.data)


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
            if prop.get("type") == "enumeration":
                options = tuple(
                    str(option.get("value"))
                    for option in prop.get("options") or []
                    if isinstance(option, Mapping) and not option.get("hidden")
                )
            metas[str(prop.get("name"))] = _FieldMeta(
                str(prop.get("label") or prop.get("name")),
                options,
                prop.get("fieldType") == "checkbox",
            )
        return metas
    body = await reader.read(
        "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT", {"object_name": _SALESFORCE_SOBJECTS[object_name]}
    )
    for field in _list(body, "fields", f"the {object_name} fields"):
        kind = field.get("type")
        options = None
        if kind in ("picklist", "multipicklist"):
            options = tuple(
                str(value.get("value"))
                for value in field.get("picklistValues") or []
                if isinstance(value, Mapping) and value.get("active", True)
            )
        metas[str(field.get("name"))] = _FieldMeta(
            str(field.get("label") or field.get("name")), options, kind == "multipicklist"
        )
    return metas


def _soql_text(value: object) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _salesforce_id(value: str) -> str:
    if not _SALESFORCE_ID.match(value):
        raise WriteRefused("crm_write_not_parsable", f"{value!r} is not a Salesforce record id.")
    return value


def _sf_key(record_id: object) -> str:
    """Salesforce answers 18-character ids for 15-character ones."""
    return str(record_id)[:15]


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
) -> Mapping[str, object]:
    body = await reader.read(
        "HUBSPOT_READ_CRM_OBJECT_BY_ID",
        {
            "objectType": _HUBSPOT_OBJECT_TYPES[object_name],
            "objectId": record_ref,
            "properties": list(fields),
        },
    )
    properties = body.get("properties") if isinstance(body, Mapping) else None
    if not isinstance(properties, Mapping):
        raise _unreadable(f"the {object_name} {record_ref}")
    return properties


async def _salesforce_field_values(
    reader: _Reader, object_name: str, records: Mapping[str, set[str]]
) -> dict[str, Mapping[str, object]]:
    """Batched SOQL: one query per 200 records of an object."""
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
    missing = [record_ref for record_ref in ids if _sf_key(record_ref) not in found]
    if missing:
        raise _unreadable(f"the {object_name} {', '.join(missing)}")
    return {record_ref: found[_sf_key(record_ref)] for record_ref in ids}


async def _memberships(
    reader: _Reader, provider: CrmProvider, items: Sequence[_Item]
) -> set[tuple[str, str]]:
    """(list, record) pairs that exist today, for the membership changes proposed."""
    members: set[tuple[str, str]] = set()
    if provider == "hubspot":
        for record_ref in sorted({str(item.parsed.record_ref) for item in items}):
            body = await reader.read(
                "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS",
                {"object_type_id": _HUBSPOT_CONTACT_OBJECT_TYPE_ID, "record_id": record_ref},
            )
            for membership in _list(body, "results", f"the lists of contact {record_ref}"):
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
    query = (
        f"SELECT Id, {', '.join(fields)} FROM {_SALESFORCE_SOBJECTS[item.parsed.object]} "
        f"WHERE {key} = {_soql_text(value)} LIMIT 2"
    )
    what = f"the {item.parsed.object} search"
    records = _list(await reader.read(slug, {"query": query}), "records", what)
    if records and records[0].get("Id") is None:
        raise _unreadable(what)
    return (str(records[0]["Id"]), records[0]) if records else None


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


async def _check_removals(
    conn: AsyncConnection, connection: CrmConnection, items: Sequence[_Item]
) -> None:
    """Clue removes only members it added itself (R-6.25 call 12)."""
    removals = [
        (str(item.parsed.list_ref), str(item.parsed.record_ref), item.parsed.label)
        for item in items
        if item.parsed.change_kind(item.spec) == "list_removal"
    ]
    added = await clue_added_members(
        conn,
        connection_id=connection.connection_id,
        pairs=[(list_ref, record) for list_ref, record, _ in removals],
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
        )

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
            )
        )


async def prepare_changes(
    conn: AsyncConnection,
    *,
    gateway: ComposioGateway,
    budget: _Budget | None,
    connection: CrmConnection,
    proposal_id: UUID,
    changes: Sequence[ProposedChange],
    version: str,
) -> list[PreparedChange]:
    """Check, read and scope a proposed batch; refuse it whole when any change may not be written.

    ``version`` is the pinned Composio toolkit version of the connection's CRM. Writes nothing
    but the Salesforce budget's call count; the caller logs the result with
    :func:`clue_api.crm.writes.insert_writes` under ``proposal_id``.
    """
    del proposal_id  # the caller logs the prepared changes under it
    provider = connection.provider
    items = [_parse(provider, change) for change in changes]
    _check_once_per_record_field(items)

    reader = _Reader(conn, gateway=gateway, budget=budget, connection=connection, version=version)
    metas: dict[str, dict[str, _FieldMeta]] = {}
    for object_name in dict.fromkeys(item.parsed.object for item in items if item.parsed.fields):
        metas[object_name] = await _field_metas(reader, provider, object_name)
    for item in items:
        _check_fields(provider, item, metas)
    await _check_removals(conn, connection, items)

    grants = await live_grants(conn, connection_id=connection.connection_id)
    builder = _Builder(conn, connection, grants, metas)

    # Before-values: field updates per record (HubSpot) or per object (Salesforce, batched).
    updates = [item for item in items if item.parsed.change_kind(item.spec) == "field_update"]
    current: dict[tuple[str, str], Mapping[str, object]] = {}
    if provider == "hubspot":
        wanted: dict[tuple[str, str], list[str]] = {}
        for item in updates:
            key = (item.parsed.object, str(item.parsed.record_ref))
            wanted.setdefault(key, []).extend(item.parsed.fields)
        for (object_name, record_ref), fields in wanted.items():
            display = _DISPLAY_FIELDS[provider].get(object_name, ())
            current[(object_name, record_ref)] = await _hubspot_field_values(
                reader, object_name, record_ref, list(dict.fromkeys([*fields, *display]))
            )
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

    memberships_proposed = [
        item
        for item in items
        if item.parsed.change_kind(item.spec) in ("list_membership", "list_removal")
    ]
    members = (
        await _memberships(reader, provider, memberships_proposed)
        if memberships_proposed
        else set()
    )

    for item in items:
        kind = item.parsed.change_kind(item.spec)
        if kind == "field_update":
            record_ref = str(item.parsed.record_ref)
            values = current[(item.parsed.object, record_ref)]
            # Named by what the record is called today; its id only when the read holds nothing.
            label = _display_name(provider, item.parsed.object, values) or item.parsed.label
            item = dataclasses.replace(item, parsed=dataclasses.replace(item.parsed, label=label))
            for field, after in item.parsed.fields.items():
                await builder.field(item, item.spec, record_ref, field, values.get(field), after)
        elif kind in ("list_membership", "list_removal"):
            before = (str(item.parsed.list_ref), str(item.parsed.record_ref)) in members
            after = kind == "list_membership"
            if before != after:
                builder.whole(item, before=before, after=after)
        elif kind in ("create_contact", "create_company"):
            found = await _find_existing(reader, provider, item)
            if found is None:
                builder.whole(item, before=None, after=dict(item.parsed.fields))
                continue
            record_ref, values = found
            update = field_update_spec(provider, item.parsed.object)
            for field, after in item.parsed.fields.items():
                await builder.field(item, update, record_ref, field, values.get(field), after)
        else:  # link_duplicate has no action until Phase 3
            raise WriteRefused("crm_write_not_allowed", f"{kind} cannot be proposed yet.")
    return builder.prepared


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


def _counts(values: Sequence[object]) -> str:
    counted = Counter(_display(value) for value in values)
    return ", ".join(f"{value} ({count})" for value, count in sorted(counted.items()))


def _title(provider: CrmProvider, change: PreparedChange, count: int) -> str:
    kind = change.parsed.change_kind(change.spec)
    target = "list" if provider == "hubspot" else "campaign"
    people = _noun("contact", count)
    if kind == "list_membership":
        return f'Add {count} {people} to the {target} "{change.parsed.list_ref}"'
    if kind == "list_removal":
        return f'Remove {count} {people} from the {target} "{change.parsed.list_ref}"'
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
    if kind == "list_membership":
        return f"adding contacts to Clue {target}"
    if kind == "list_removal":
        return f"removing contacts from Clue {target}"
    if kind == "field_update":
        return f'setting "{change.field_label}" on {_noun(change.spec.object, 2)}'
    if kind == "create_contact":
        return "creating contacts"
    if kind == "create_company":
        return f"creating {_noun(change.spec.object, 2)}"
    return "marking possible duplicates"


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
        key = (
            change.parsed.change_kind(change.spec),
            change.spec.object,
            change.field,
            change.parsed.list_ref,
        )
        grouped.setdefault(key, []).append(change)

    groups: list[dict[str, Any]] = []
    for changes in grouped.values():
        first = changes[0]
        count = len(changes)
        summary = None
        if first.field is not None:
            befores = [change.before for change in changes]
            before_text = (
                "Empty today" if all(same_value(b, None) for b in befores) else _counts(befores)
            )
            summary = f"{before_text} → {_counts([change.after for change in changes])}"
        groups.append(
            {
                "kind": first.parsed.change_kind(first.spec),
                "object": first.spec.object,
                "field": first.field,
                "field_label": first.field_label,
                "list_ref": first.parsed.list_ref,
                "title": _title(provider, first, count),
                "count": count,
                "value_summary": summary,
                "reason": _reason(changes),
                "records": [
                    {
                        "write_id": str(change.write_id),
                        "record_ref": change.parsed.record_ref,
                        "name": change.parsed.label,
                        "before": change.before,
                        "after": change.after,
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
                "before": change.before,
                "after": change.after,
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
