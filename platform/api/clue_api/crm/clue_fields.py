"""Clue's own fields in a connected CRM: the fixed field set, and what a connection has set up
(the ``crm_clue_fields`` row, migration ``crm_clue_fields``).

Spec: docs/superpowers/specs/crm-integration/ (Phase 4 plan, Task 1); rulings R-13.1 (Clue grants
access to its Salesforce fields itself, through the "Clue fields" permission set), R-13.2 (the
starting set: what Clue can fill today), R-13.4 (the set is Clue's contract, built from code, never
chosen by the agent) and R-13.7 (HubSpot's Clue id is unique).

The field set is data: the setup run (Task 3) creates exactly these, and the writes (Tasks 4–5)
read them. The registry functions write through the ``conn`` they are given and never commit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.composio_gateway import CrmProvider

__all__ = [
    "CLUE_FIELDS",
    "HUBSPOT_DUPLICATE_LABEL",
    "HUBSPOT_GROUP",
    "SALESFORCE_PERMISSION_SET",
    "ClueField",
    "ClueFieldOption",
    "ClueFieldsState",
    "ClueFieldsStatus",
    "clue_field",
    "clue_field_ready",
    "clue_field_written",
    "clue_fields_state",
    "mark_clue_field_gone",
    "record_clue_fields",
    "record_partial_clue_fields",
]

ClueObject = Literal["company", "contact"]
ClueFieldsStatus = Literal["ready", "partial", "gone"]


@dataclass(frozen=True)
class ClueFieldOption:
    """One picklist option: the value stored in the CRM and the label a person reads."""

    value: str
    label: str


@dataclass(frozen=True)
class ClueField:
    """One of Clue's own CRM fields.

    ``key`` is Clue's name for the meaning (the same on both providers); ``object`` is Clue's
    object and ``crm_object`` the CRM's (HubSpot ``companies``/``contacts``, Salesforce
    ``Account``/``Contact``). ``type`` is HubSpot's property ``type`` or Salesforce's field type;
    ``field_type`` is HubSpot's ``fieldType`` (``None`` on Salesforce). ``length`` is a Salesforce
    Text length; ``external_id`` a Salesforce external id; ``unique`` HubSpot's ``hasUniqueValue``
    or Salesforce's unique flag; ``reference_to`` and ``relationship_name`` describe a Salesforce
    lookup; ``group`` is the HubSpot property group.
    """

    key: str
    object: ClueObject
    crm_object: str
    crm_name: str
    label: str
    type: str
    options: tuple[ClueFieldOption, ...] = ()
    field_type: str | None = None
    group: str | None = None
    length: int | None = None
    external_id: bool = False
    unique: bool = False
    reference_to: str | None = None
    relationship_name: str | None = None

    @property
    def qualified_name(self) -> str:
        """The field's name with its CRM object (``Account.Clue_Id__c``, ``contacts.clue_id``):
        the form the registry stores, since the same CRM name exists on both objects."""
        return f"{self.crm_object}.{self.crm_name}"


@dataclass(frozen=True)
class HubSpotPropertyGroup:
    name: str
    label: str


@dataclass(frozen=True)
class HubSpotAssociationLabel:
    """A HubSpot association label Clue creates (the "Possible duplicate" contact link)."""

    name: str
    label: str
    from_object: str
    to_object: str


@dataclass(frozen=True)
class SalesforcePermissionSet:
    """The permission set that grants read/edit on Clue's Salesforce fields (R-13.1)."""

    name: str
    label: str


HUBSPOT_GROUP = HubSpotPropertyGroup(name="clue", label="Clue")
HUBSPOT_DUPLICATE_LABEL = HubSpotAssociationLabel(
    name="clue_possible_duplicate",
    label="Possible duplicate",
    from_object="contacts",
    to_object="contacts",
)
SALESFORCE_PERMISSION_SET = SalesforcePermissionSet(name="Clue_Fields", label="Clue fields")

#: Tier labels, best first; HubSpot stores ``tier_1``… (as its own ICP tier does, R-12.1).
_TIERS = ("Tier 1", "Tier 2", "Tier 3")
#: Committee roles in R-12.6's order, with HubSpot's buying-role values.
_ROLES = (
    ("CHAMPION", "Champion"),
    ("BUDGET_HOLDER", "Budget holder"),
    ("INFLUENCER", "Influencer"),
    ("BLOCKER", "Blocker"),
    ("END_USER", "End user"),
)

_HUBSPOT_OBJECT: Mapping[ClueObject, str] = {"company": "companies", "contact": "contacts"}
_SALESFORCE_OBJECT: Mapping[ClueObject, str] = {"company": "Account", "contact": "Contact"}


def _hubspot(
    key: str, obj: ClueObject, label: str, *, options: tuple[ClueFieldOption, ...] = ()
) -> ClueField:
    return ClueField(
        key=key,
        object=obj,
        crm_object=_HUBSPOT_OBJECT[obj],
        crm_name=key,
        label=label,
        type="enumeration" if options else "string",
        field_type="select" if options else "text",
        options=options,
        group=HUBSPOT_GROUP.name,
        unique=key == "clue_id",
    )


def _salesforce(
    key: str,
    obj: ClueObject,
    label: str,
    sf_type: str,
    *,
    options: tuple[ClueFieldOption, ...] = (),
    length: int | None = None,
    external_id: bool = False,
    reference_to: str | None = None,
    relationship_name: str | None = None,
) -> ClueField:
    """A Salesforce field; its API name is the key in Title_Case with ``__c``
    (``clue_tier`` → ``Clue_Tier__c``)."""
    return ClueField(
        key=key,
        object=obj,
        crm_object=_SALESFORCE_OBJECT[obj],
        crm_name="_".join(part.capitalize() for part in key.split("_")) + "__c",
        label=label,
        type=sf_type,
        options=options,
        length=length,
        external_id=external_id,
        unique=external_id,
        reference_to=reference_to,
        relationship_name=relationship_name,
    )


_HUBSPOT_TIERS = tuple(
    ClueFieldOption(f"tier_{n}", label) for n, label in enumerate(_TIERS, start=1)
)
_HUBSPOT_ROLES = tuple(ClueFieldOption(value, label) for value, label in _ROLES)
_SALESFORCE_TIERS = tuple(ClueFieldOption(label, label) for label in _TIERS)
_SALESFORCE_ROLES = tuple(ClueFieldOption(label, label) for _, label in _ROLES)

#: Clue's own fields per provider (R-13.2). Company: tier, research link, Clue id; contact:
#: committee role, contact link, Clue id; Salesforce also the possible-duplicate lookup (R-13.5).
CLUE_FIELDS: Mapping[CrmProvider, tuple[ClueField, ...]] = {
    "hubspot": (
        _hubspot("clue_tier", "company", "Clue tier", options=_HUBSPOT_TIERS),
        _hubspot("clue_research_link", "company", "Clue research link"),
        _hubspot("clue_id", "company", "Clue id"),
        _hubspot("clue_committee_role", "contact", "Clue committee role", options=_HUBSPOT_ROLES),
        _hubspot("clue_contact_link", "contact", "Clue contact link"),
        _hubspot("clue_id", "contact", "Clue id"),
    ),
    "salesforce": (
        _salesforce("clue_tier", "company", "Clue tier", "Picklist", options=_SALESFORCE_TIERS),
        _salesforce("clue_research_link", "company", "Clue research link", "Url"),
        _salesforce("clue_id", "company", "Clue id", "Text", length=64, external_id=True),
        _salesforce(
            "clue_committee_role",
            "contact",
            "Clue committee role",
            "Picklist",
            options=_SALESFORCE_ROLES,
        ),
        _salesforce("clue_contact_link", "contact", "Clue contact link", "Url"),
        _salesforce("clue_id", "contact", "Clue id", "Text", length=64, external_id=True),
        _salesforce(
            "clue_possible_duplicate",
            "contact",
            "Clue possible duplicate",
            "Lookup",
            reference_to="Contact",
            relationship_name="Clue_Possible_Duplicates",
        ),
    ),
}


def clue_field(provider: CrmProvider, obj: ClueObject, crm_name: str) -> ClueField:
    """The Clue field of ``provider`` on ``obj`` named ``crm_name``; ``KeyError`` when it is not
    one of Clue's."""
    for field in CLUE_FIELDS[provider]:
        if field.object == obj and field.crm_name == crm_name:
            return field
    raise KeyError(f"{provider} {obj} {crm_name}")


#: Clue's object for each CRM object a write action names (HubSpot ``company``, Salesforce
#: ``account``; ``contact`` on both).
_WRITE_OBJECTS: Mapping[str, ClueObject] = {
    "company": "company",
    "account": "company",
    "contact": "contact",
}


def clue_field_written(provider: CrmProvider, object_name: str, crm_name: str) -> ClueField | None:
    """The Clue field a change writes when it sets ``crm_name`` on the write action's object
    ``object_name``; ``None`` when that is not one of Clue's fields (an exact name only)."""
    obj = _WRITE_OBJECTS.get(object_name)
    if obj is None:
        return None
    try:
        return clue_field(provider, obj, crm_name)
    except KeyError:
        return None


def clue_field_ready(state: ClueFieldsState | None, field: ClueField) -> bool:
    """Whether ``field`` may be written: the setup is ``ready`` and it created the field, which
    has not been found missing since."""
    return (
        state is not None
        and state.status == "ready"
        and field.qualified_name in state.created_names
        and field.qualified_name not in state.gone_names
    )


@dataclass(frozen=True)
class ClueFieldsState:
    """What Clue set up in one connection's CRM. ``created_names`` are the CRM names Clue created
    (kept even when gone); ``gone_names`` those since found missing; ``gone_at`` when the first was
    found missing."""

    connection_id: UUID
    workspace_id: str
    provider: CrmProvider
    status: ClueFieldsStatus
    created_names: tuple[str, ...]
    gone_names: tuple[str, ...]
    permission_set_id: str | None
    label_type_id: str | None
    gone_at: datetime | None
    created_at: datetime
    updated_at: datetime


_COLUMNS = (
    "connection_id, workspace_id, provider, status, created_names, gone_names, "
    "permission_set_id, label_type_id, gone_at, created_at, updated_at"
)


async def clue_fields_state(
    conn: AsyncConnection, *, connection_id: UUID
) -> ClueFieldsState | None:
    """What Clue set up in this connection's CRM; ``None`` before any setup was recorded."""
    row = (
        await conn.execute(
            text(f"SELECT {_COLUMNS} FROM crm_clue_fields WHERE connection_id = :c"),
            {"c": connection_id},
        )
    ).one_or_none()
    if row is None:
        return None
    values = dict(row._mapping)
    values["created_names"] = tuple(values["created_names"])
    values["gone_names"] = tuple(values["gone_names"])
    return ClueFieldsState(**values)


async def record_clue_fields(
    conn: AsyncConnection,
    *,
    connection_id: UUID,
    workspace_id: str,
    provider: CrmProvider,
    created: Iterable[ClueField],
    permission_set_id: str | None,
    label_type_id: str | None,
    status: Literal["ready", "partial"],
) -> None:
    """Record what a setup run left in the CRM: ``created`` are the Clue fields it found or made,
    stored by :attr:`ClueField.qualified_name`. A later run replaces the record, so nothing it
    lists is gone any more. A field that is not one of ``provider``'s is a ``ValueError``."""
    names: list[str] = []
    for field in created:
        if field not in CLUE_FIELDS[provider]:
            raise ValueError(f"{field.qualified_name} is not a {provider} Clue field")
        names.append(field.qualified_name)
    await conn.execute(
        text(
            "INSERT INTO crm_clue_fields (connection_id, workspace_id, provider, status, "
            "created_names, permission_set_id, label_type_id) "
            "VALUES (:c, :ws, :provider, :status, :created, :ps, :label) "
            "ON CONFLICT (connection_id) DO UPDATE SET status = EXCLUDED.status, "
            "created_names = EXCLUDED.created_names, gone_names = '{}', gone_at = NULL, "
            "permission_set_id = EXCLUDED.permission_set_id, "
            "label_type_id = EXCLUDED.label_type_id, updated_at = now()"
        ),
        {
            "c": connection_id,
            "ws": workspace_id,
            "provider": provider,
            "status": status,
            "created": names,
            "ps": permission_set_id,
            "label": label_type_id,
        },
    )


async def record_partial_clue_fields(
    conn: AsyncConnection,
    *,
    connection_id: UUID,
    workspace_id: str,
    provider: CrmProvider,
    found: Iterable[ClueField],
    permission_set_id: str | None,
    label_type_id: str | None,
) -> None:
    """Record what a setup run that did not finish found or made, without forgetting what an
    earlier run recorded: the created names are the union (in :data:`CLUE_FIELDS` order), a
    permission set or label id this run did not reach is kept, and a ``gone`` record stays gone
    with its gone names (only a run that reaches ``ready`` clears them,
    :func:`record_clue_fields`). Otherwise the record is ``partial``."""
    seen = {field.qualified_name for field in found}
    state = await clue_fields_state(conn, connection_id=connection_id)
    known = set(state.created_names) if state is not None else set()
    names = [
        field.qualified_name
        for field in CLUE_FIELDS[provider]
        if field.qualified_name in seen | known
    ]
    if state is None:
        await conn.execute(
            text(
                "INSERT INTO crm_clue_fields (connection_id, workspace_id, provider, status, "
                "created_names, permission_set_id, label_type_id) "
                "VALUES (:c, :ws, :provider, 'partial', :created, :ps, :label)"
            ),
            {
                "c": connection_id,
                "ws": workspace_id,
                "provider": provider,
                "created": names,
                "ps": permission_set_id,
                "label": label_type_id,
            },
        )
        return
    await conn.execute(
        text(
            "UPDATE crm_clue_fields SET created_names = :created, "
            "permission_set_id = COALESCE(:ps, permission_set_id), "
            "label_type_id = COALESCE(:label, label_type_id), "
            "status = CASE WHEN status = 'gone' THEN 'gone' ELSE 'partial' END, "
            "updated_at = now() WHERE connection_id = :c"
        ),
        {"c": connection_id, "created": names, "ps": permission_set_id, "label": label_type_id},
    )


async def mark_clue_field_gone(
    conn: AsyncConnection, *, connection_id: UUID, obj: ClueObject, crm_name: str
) -> None:
    """Remember that the CRM no longer has the Clue field ``crm_name`` on ``obj``: the setup is
    ``gone`` until set up again. Nothing is recorded for a connection that was never set up; a
    name that is not one of the connection's provider's Clue fields on ``obj`` is a ``KeyError``.
    """
    provider = (
        await conn.execute(
            text("SELECT provider FROM crm_clue_fields WHERE connection_id = :c"),
            {"c": connection_id},
        )
    ).scalar_one_or_none()
    if provider is None:
        return
    field = clue_field(provider, obj, crm_name)
    await conn.execute(
        text(
            "UPDATE crm_clue_fields SET status = 'gone', gone_at = COALESCE(gone_at, now()), "
            "gone_names = CASE WHEN :name = ANY(gone_names) THEN gone_names "
            "ELSE array_append(gone_names, CAST(:name AS text)) END, updated_at = now() "
            "WHERE connection_id = :c"
        ),
        {"c": connection_id, "name": field.qualified_name},
    )
