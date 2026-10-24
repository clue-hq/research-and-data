"""The setup run: create Clue's own fields in the connected CRM, idempotently (Phase 4, Task 3).

Spec: docs/superpowers/specs/crm-integration/ (Phase 4 plan, Task 3); rulings R-13.1 (Clue grants
access to its Salesforce fields itself, through the "Clue fields" permission set), R-13.2 (the
field set), R-13.4 (built from code) and R-13.7 (HubSpot's Clue id is unique). The call shapes are
the spike's (composio-api-notes.md § Phase 4 shapes).

HubSpot: the property group ``clue`` on every object Clue has fields on (409 = already there),
each property (409 = already there), then the contacts↔contacts "Possible duplicate" association
label, looked up by name first so it is never made twice; its ``typeId`` is kept.

Salesforce: each custom field (Composio answers a field that exists ``successful`` with an inner
``success: false`` "There is already a field named …": already there), then the permission set
``Clue_Fields``, one ``FieldPermissions`` row (read and edit) per field, and the assignment of the
set to the connected user (``SALESFORCE_WHO_AM_I``) — each looked up first. A field made through
the Tooling API is invisible until that access is granted, so the run ends by reading every field
back with SOQL as the connected user: only an answer that sees them all makes the setup ready.

The run stops at the first step the CRM refuses; every step before it is kept in the outcome, so
a later run starts again from the top, finds what is there and makes only what is missing. Every
call goes through the executor's CRM (its pause between calls, Salesforce's API budget, and its
stops for a rate limit or an expired connection, which this module lets through). Clue never
deletes what it made.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from clue_api.crm.clue_fields import (
    HUBSPOT_DUPLICATE_LABEL,
    HUBSPOT_GROUP,
    SALESFORCE_PERMISSION_SET,
    ClueField,
)
from clue_api.crm.composio_gateway import ExecuteResult
from clue_api.crm.connections import CrmConnection
from clue_api.crm.write_prepare import _soql_text, _status_code, _unwrap

__all__ = [
    "SetupCrm",
    "SetupOutcome",
    "SetupStep",
    "run_clue_fields_setup",
]

StepResult = Literal["created", "already there", "checked", "failed"]

_GROUP = "HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP"
_PROPERTY = "HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE"
_LABELS = "HUBSPOT_LIST_ASSOCIATION_TYPES"
_LABEL = "HUBSPOT_CREATE_ASSOCIATION_LABEL"
_SF_FIELD = "SALESFORCE_CREATE_CUSTOM_FIELD"
_SF_CREATE = "SALESFORCE_CREATE_S_OBJECT_RECORD"
_SF_WHO = "SALESFORCE_WHO_AM_I"
_SOQL = "SALESFORCE_RUN_SOQL_QUERY"

#: HubSpot's answers for a group or property that exists (409; the spike saw ``GROUP_EXISTS``).
_HUBSPOT_EXISTS = ("GROUP_EXISTS", "already exists")
#: Salesforce's answer for a custom field that exists (the spike's trap).
_SALESFORCE_FIELD_EXISTS = "There is already a field named"
_NEEDS_ADMIN = "The connected user needs to be a Salesforce admin."
_UNREADABLE = "its answer was not readable"


class SetupCrm(Protocol):
    """The executor's CRM: every call through it is paced, budgeted and may stop the run."""

    connection: CrmConnection

    @property
    def name(self) -> str: ...

    async def call(self, slug: str, arguments: Mapping[str, Any]) -> ExecuteResult: ...


@dataclass(frozen=True)
class SetupStep:
    """One step and what came of it."""

    step: str
    result: StepResult

    def as_json(self) -> dict[str, str]:
        return {"step": self.step, "result": self.result}


@dataclass
class SetupOutcome:
    """What a setup run found or made, step by step. Filled as the run goes, so a run stopped
    half-way (a rate limit, an expired connection) still says what exists."""

    steps: list[SetupStep] = field(default_factory=list)
    #: The Clue fields the CRM has (found or made), in setup order.
    fields: list[ClueField] = field(default_factory=list)
    permission_set_id: str | None = None
    label_type_id: str | None = None
    #: The refused step's sentence, with ``{message}`` where the CRM's message goes.
    failure: str | None = None
    #: The CRM's whole answer to the refused step.
    failure_answer: str | None = None

    @property
    def ready(self) -> bool:
        return self.failure is None

    def counted(self, result: StepResult) -> int:
        return sum(1 for step in self.steps if step.result == result)


class _Refused(Exception):
    """A step the CRM refused: the run stops here."""


async def run_clue_fields_setup(
    crm: SetupCrm, fields: Sequence[ClueField], *, outcome: SetupOutcome | None = None
) -> SetupOutcome:
    """Set up ``fields`` (Clue's fields of the connection's provider, as the card listed them)
    in the CRM. ``outcome`` may be given to keep what the run did when a stop raised from the CRM
    ends it early. The outcome is ready only when every step is done."""
    outcome = outcome if outcome is not None else SetupOutcome()
    try:
        if crm.connection.provider == "hubspot":
            await _hubspot(crm, fields, outcome)
        else:
            await _salesforce(crm, fields, outcome)
    except _Refused:
        pass
    return outcome


def _refuse(outcome: SetupOutcome, step: str, sentence: str, answer: str) -> _Refused:
    outcome.steps.append(SetupStep(step, "failed"))
    outcome.failure = sentence
    outcome.failure_answer = answer
    return _Refused(step)


def _answer(result: ExecuteResult) -> str:
    """The CRM's answer to a refused or unreadable call, as text."""
    if result.error:
        return result.error
    return json.dumps(result.data, default=str) if result.data is not None else _UNREADABLE


def _records(result: ExecuteResult) -> list[Mapping[str, Any]] | None:
    body = _unwrap(result.data) if result.successful else None
    items = body.get("records") if isinstance(body, Mapping) else None
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        return None
    return items


# --- HubSpot -----------------------------------------------------------------------------------


def _hubspot_exists(result: ExecuteResult) -> bool:
    return not result.successful and (
        _status_code(result) == 409 or any(code in (result.error or "") for code in _HUBSPOT_EXISTS)
    )


def _named(result: ExecuteResult, name: str) -> bool:
    body = _unwrap(result.data)
    return result.successful and isinstance(body, Mapping) and body.get("name") == name


async def _hubspot(crm: SetupCrm, fields: Sequence[ClueField], outcome: SetupOutcome) -> None:
    for object_type in dict.fromkeys(f.crm_object for f in fields):
        step = f'the property group "{HUBSPOT_GROUP.label}" on {object_type}'
        result = await crm.call(
            _GROUP,
            {"objectType": object_type, "name": HUBSPOT_GROUP.name, "label": HUBSPOT_GROUP.label},
        )
        if _hubspot_exists(result):
            outcome.steps.append(SetupStep(step, "already there"))
        elif _named(result, HUBSPOT_GROUP.name):
            outcome.steps.append(SetupStep(step, "created"))
        else:
            raise _refuse(outcome, step, f"HubSpot refused {step}: {{message}}.", _answer(result))
    for clue_field in fields:
        step = f'the field "{clue_field.label}" on {clue_field.crm_object}'
        result = await crm.call(_PROPERTY, _hubspot_property(clue_field))
        if _hubspot_exists(result):
            outcome.steps.append(SetupStep(step, "already there"))
        elif _named(result, clue_field.crm_name):
            outcome.steps.append(SetupStep(step, "created"))
        else:
            raise _refuse(outcome, step, f"HubSpot refused {step}: {{message}}.", _answer(result))
        outcome.fields.append(clue_field)
    await _hubspot_label(crm, outcome)


def _hubspot_property(clue_field: ClueField) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "objectType": clue_field.crm_object,
        "name": clue_field.crm_name,
        "label": clue_field.label,
        "type": clue_field.type,
        "fieldType": clue_field.field_type,
        "groupName": clue_field.group,
    }
    if clue_field.options:
        arguments["options"] = [
            {"label": option.label, "value": option.value, "displayOrder": order, "hidden": False}
            for order, option in enumerate(clue_field.options)
        ]
    if clue_field.unique:
        arguments["hasUniqueValue"] = True  # R-13.7
    return arguments


async def _hubspot_label(crm: SetupCrm, outcome: SetupOutcome) -> None:
    """The "Possible duplicate" contact label: found by name, else made (its ``typeId`` kept)."""
    label = HUBSPOT_DUPLICATE_LABEL
    step = f'the "{label.label}" label for {label.from_object}'
    found = await _hubspot_label_type(crm, outcome, step)
    if found is not None:
        outcome.label_type_id = found
        outcome.steps.append(SetupStep(step, "already there"))
        return
    result = await crm.call(
        _LABEL,
        {
            "from_object_type": label.from_object,
            "to_object_type": label.to_object,
            "name": label.name,
            "label": label.label,
        },
    )
    made = _created_label_type(result)
    if made is None and _hubspot_exists(result):  # made since the look-up
        made = await _hubspot_label_type(crm, outcome, step)
    if made is None:
        raise _refuse(outcome, step, f"HubSpot refused {step}: {{message}}.", _answer(result))
    outcome.label_type_id = made
    outcome.steps.append(SetupStep(step, "created"))


async def _hubspot_label_type(crm: SetupCrm, outcome: SetupOutcome, step: str) -> str | None:
    """The type id of Clue's label among HubSpot's contact-to-contact association types."""
    label = HUBSPOT_DUPLICATE_LABEL
    result = await crm.call(
        _LABELS, {"fromObjectType": label.from_object, "toObjectType": label.to_object}
    )
    body = _unwrap(result.data) if result.successful else None
    types = body.get("results") if isinstance(body, Mapping) else None
    if not isinstance(types, list):
        raise _refuse(
            outcome,
            step,
            f"HubSpot did not list its {label.from_object} labels: {{message}}.",
            _answer(result),
        )
    for item in types:
        if isinstance(item, Mapping) and item.get("name") == label.name and item.get("id"):
            return str(item["id"])
    return None


def _created_label_type(result: ExecuteResult) -> str | None:
    body = _unwrap(result.data) if result.successful else None
    made = body.get("results") if isinstance(body, Mapping) else None
    if not isinstance(made, list):
        return None
    directions = [item for item in made if isinstance(item, Mapping) and item.get("typeId")]
    ours = [item for item in directions if item.get("label") == HUBSPOT_DUPLICATE_LABEL.label]
    chosen = (ours or directions)[:1]
    return str(chosen[0]["typeId"]) if chosen else None


# --- Salesforce --------------------------------------------------------------------------------


async def _salesforce(crm: SetupCrm, fields: Sequence[ClueField], outcome: SetupOutcome) -> None:
    for clue_field in fields:
        await _salesforce_field(crm, clue_field, outcome)
        outcome.fields.append(clue_field)
    permission_set = await _permission_set(crm, outcome)
    outcome.permission_set_id = permission_set
    await _field_permissions(crm, fields, permission_set, outcome)
    await _assignment(crm, permission_set, outcome)
    await _read_back(crm, fields, outcome)


def _salesforce_arguments(clue_field: ClueField) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "object_api_name": clue_field.crm_object,
        "field_api_name": clue_field.crm_name,
        "field_type": clue_field.type,
        "label": clue_field.label,
        "check_existing": True,
    }
    if clue_field.options:
        arguments["picklist_values"] = [
            {"full_name": option.value, "label": option.label, "default": False}
            for option in clue_field.options
        ]
    if clue_field.length is not None:
        arguments["length"] = clue_field.length
    if clue_field.external_id:
        arguments["external_id"] = True
    if clue_field.unique:
        arguments["unique"] = True
    if clue_field.reference_to is not None:
        arguments["reference_to"] = clue_field.reference_to
    if clue_field.relationship_name is not None:
        arguments["relationship_name"] = clue_field.relationship_name
    return arguments


async def _salesforce_field(crm: SetupCrm, clue_field: ClueField, outcome: SetupOutcome) -> None:
    step = f'the field "{clue_field.label}" on {clue_field.crm_object}'
    result = await crm.call(_SF_FIELD, _salesforce_arguments(clue_field))
    body = _unwrap(result.data) if result.successful else None
    inner = body if isinstance(body, Mapping) else {}
    errors = inner.get("errors") if result.successful else None
    answer = json.dumps(errors, default=str) if errors else _answer(result)
    if _SALESFORCE_FIELD_EXISTS in answer or inner.get("already_exists") is True:
        outcome.steps.append(SetupStep(step, "already there"))
    elif inner.get("success") is True:
        outcome.steps.append(SetupStep(step, "created"))
    else:  # the outer ``successful`` is never trusted alone (the spike's trap)
        raise _refuse(outcome, step, f"Salesforce refused {step}: {{message}}.", answer)


def _created_record(result: ExecuteResult) -> tuple[str | None, str]:
    """The id a ``SALESFORCE_CREATE_S_OBJECT_RECORD`` answer gives, and the answer as text."""
    body = _unwrap(result.data) if result.successful else None
    if isinstance(body, Mapping) and body.get("success") is not False and body.get("id"):
        return str(body["id"]), ""
    errors = body.get("errors") if isinstance(body, Mapping) else None
    return None, json.dumps(errors, default=str) if errors else _answer(result)


async def _find_one(
    crm: SetupCrm, outcome: SetupOutcome, step: str, query: str
) -> Mapping[str, Any] | None:
    result = await crm.call(_SOQL, {"query": query})
    records = _records(result)
    if records is None:
        raise _refuse(
            outcome, step, f"Salesforce could not look up {step}: {{message}}.", _answer(result)
        )
    return records[0] if records else None


async def _permission_set(crm: SetupCrm, outcome: SetupOutcome) -> str:
    """The "Clue fields" permission set: found by its name, else made (R-13.1)."""
    name = SALESFORCE_PERMISSION_SET.name
    step = f'the permission set "{SALESFORCE_PERMISSION_SET.label}"'
    found = await _find_one(
        crm, outcome, step, f"SELECT Id FROM PermissionSet WHERE Name = {_soql_text(name)}"
    )
    if found is not None and found.get("Id"):
        outcome.steps.append(SetupStep(step, "already there"))
        return str(found["Id"])
    result = await crm.call(
        _SF_CREATE,
        {
            "sobject_type": "PermissionSet",
            "fields": {"Name": name, "Label": SALESFORCE_PERMISSION_SET.label},
        },
    )
    made, answer = _created_record(result)
    if made is None:
        raise _refuse(
            outcome,
            step,
            f"Salesforce refused the permission set: {{message}}. {_NEEDS_ADMIN}",
            answer,
        )
    outcome.steps.append(SetupStep(step, "created"))
    return made


async def _field_permissions(
    crm: SetupCrm, fields: Sequence[ClueField], permission_set: str, outcome: SetupOutcome
) -> None:
    """Read and edit on every field in the permission set; a field it already grants is left."""
    step = "the access the permission set grants"
    result = await crm.call(
        _SOQL,
        {
            "query": "SELECT Id, Field FROM FieldPermissions WHERE ParentId = "
            f"{_soql_text(permission_set)}"
        },
    )
    records = _records(result)
    if records is None:
        raise _refuse(
            outcome, step, f"Salesforce could not look up {step}: {{message}}.", _answer(result)
        )
    granted = {str(record.get("Field")) for record in records}
    for clue_field in fields:
        step = f"access to {clue_field.qualified_name}"
        if clue_field.qualified_name in granted:
            outcome.steps.append(SetupStep(step, "already there"))
            continue
        made, answer = _created_record(
            await crm.call(
                _SF_CREATE,
                {
                    "sobject_type": "FieldPermissions",
                    "fields": {
                        "ParentId": permission_set,
                        "SobjectType": clue_field.crm_object,
                        "Field": clue_field.qualified_name,
                        "PermissionsRead": True,
                        "PermissionsEdit": True,
                    },
                },
            )
        )
        if made is None:
            raise _refuse(
                outcome,
                step,
                f"Salesforce refused access to the field {clue_field.qualified_name} in the "
                f"permission set: {{message}}. {_NEEDS_ADMIN}",
                answer,
            )
        outcome.steps.append(SetupStep(step, "created"))


async def _assignment(crm: SetupCrm, permission_set: str, outcome: SetupOutcome) -> None:
    """The permission set assigned to the connected user (found first, else made)."""
    step = "the permission set for the connected user"
    who = await crm.call(_SF_WHO, {})
    body = _unwrap(who.data) if who.successful else None
    identity = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(identity, Mapping):
        identity = body if isinstance(body, Mapping) else {}
    user = identity.get("user_id")
    if not user:
        raise _refuse(
            outcome,
            step,
            "Salesforce did not say who the connected user is: {message}.",
            _answer(who),
        )
    found = await _find_one(
        crm,
        outcome,
        step,
        "SELECT Id FROM PermissionSetAssignment WHERE PermissionSetId = "
        f"{_soql_text(permission_set)} AND AssigneeId = {_soql_text(user)}",
    )
    if found is not None:
        outcome.steps.append(SetupStep(step, "already there"))
        return
    made, answer = _created_record(
        await crm.call(
            _SF_CREATE,
            {
                "sobject_type": "PermissionSetAssignment",
                "fields": {"PermissionSetId": permission_set, "AssigneeId": str(user)},
            },
        )
    )
    if made is None:
        raise _refuse(
            outcome,
            step,
            f"Salesforce refused giving the connected user the permission set: {{message}}. "
            f"{_NEEDS_ADMIN}",
            answer,
        )
    outcome.steps.append(SetupStep(step, "created"))


async def _read_back(crm: SetupCrm, fields: Sequence[ClueField], outcome: SetupOutcome) -> None:
    """Every field read with SOQL as the connected user: Salesforce answers "No such column" for
    a field the user cannot see, so an answer proves access (one query per object)."""
    step = "reading Clue's fields back as the connected user"
    by_object: dict[str, list[str]] = {}
    for clue_field in fields:
        by_object.setdefault(clue_field.crm_object, []).append(clue_field.crm_name)
    for sobject, names in by_object.items():
        result = await crm.call(
            _SOQL, {"query": f"SELECT Id, {', '.join(names)} FROM {sobject} LIMIT 1"}
        )
        if _records(result) is None:
            raise _refuse(
                outcome,
                step,
                "Salesforce still hides Clue's fields from the connected user after the "
                "permission set: {message}.",
                _answer(result),
            )
    outcome.steps.append(SetupStep(step, "checked"))
