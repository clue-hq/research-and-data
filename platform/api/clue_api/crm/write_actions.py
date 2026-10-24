"""Which CRM write actions Clue may propose, and how each one's arguments become a change.

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 plan, Task 3). The slugs and argument
names are the ones checked in ``composio-api-notes.md`` § Writes. The agent never runs a write
itself (``run_crm_action`` refuses one); it proposes it with ``propose_crm_changes`` and the person
approves it on a card. Every spec's ``parse`` turns the agent's arguments into one
:class:`ParsedChange` — one record — so the card and the write log can name exactly what changes,
and refuses (:class:`WriteNotParsable`) any argument the card could not show.

Field names in a :class:`ParsedChange` are the CRM's own: HubSpot internal property names and
Salesforce API names (``Industry``, ``Tier__c``). Salesforce's named tools take snake_case
arguments (``industry``), so they are mapped here.

Never allowlisted: merges, deletes, GDPR/erase actions and Composio's natural-language
(``*_FROM_NL``) actions; ``HUBSPOT_UPDATE_CONTACT`` (it reported success on a refused write — use
the batch ``HUBSPOT_UPDATE_CONTACTS``); the Salesforce ``*_BY_ID`` update tools (deprecated in the
pinned toolkit). ``link_duplicate`` is a declared kind with no action until Phase 4.

``clue_fields_setup`` (Phase 4, Task 2; R-13.3, R-13.4) sets up Clue's own fields in the CRM. It is
not on the allowlist: no Composio action of its own, never proposed through ``propose_crm_changes``.
``propose_clue_fields_setup`` builds the one change from ``CLUE_FIELDS``
(:mod:`clue_api.crm.clue_fields`) with :func:`clue_fields_setup_spec`, so the agent never chooses a
field; the executor runs it (Task 3). Only a workspace owner or admin may allow it, and no
standing permission covers it.

``list_create`` (Phase 3, Task 3) creates a Clue list: a **manual** HubSpot list of companies or
contacts, or a Salesforce campaign (which holds contacts). Its ``label`` is the list's name; it
sets no field and names no record until the CRM gives it an id. A HubSpot list membership change
names no object type, so its ``object`` here is ``contact``; preparation reads the real one from
the list Clue keeps (``crm_list.crm_object``).

What a result means is the executor's business (Task 6), but two traps are recorded here: a
Salesforce composite call is ``successful`` even when records fail (each carries ``success`` and
``errors``), and HubSpot silently ignores a write to a read-only property — so the executor reads
the record back after writing.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from clue_api.crm.clue_fields import CLUE_FIELDS
from clue_api.crm.composio_gateway import CrmProvider

__all__ = [
    "HUBSPOT_OBJECT_TYPE_IDS",
    "NEW_COMPANY_PREFIX",
    "NEW_CONTACT_PREFIX",
    "NEW_LIST_PREFIX",
    "WRITE_ACTIONS",
    "CLUE_CAMPAIGN_SETTINGS",
    "CLUE_FIELDS_SETUP",
    "CLUE_FIELDS_SETUP_SLUG",
    "BatchSpec",
    "ItemOutcome",
    "ParsedChange",
    "WriteActionSpec",
    "WriteKind",
    "WriteNotParsable",
    "clue_fields_setup_arguments",
    "clue_fields_setup_spec",
    "field_update_spec",
    "forbidden_fields",
    "is_forbidden_field",
    "is_write",
    "created_reference",
    "find_value",
    "new_list_name",
    "record_reference",
    "record_references",
    "reference_in",
    "scope_key",
    "single_field_arguments",
    "website_host",
    "with_reference_filled",
    "write_spec",
]

WriteKind = Literal[
    "field_update",
    "list_membership",
    "list_removal",
    "create_contact",
    "create_company",
    "list_create",
    "link_duplicate",
    "clue_fields_setup",
]

#: The kind no standing permission ("Always allow", "Fully automatic") ever covers (R-13.3).
CLUE_FIELDS_SETUP: WriteKind = "clue_fields_setup"
#: What a ``clue_fields_setup`` change is logged as in ``crm_write.slug``: Clue's own name, not a
#: Composio action (the setup is many calls, run by the executor).
CLUE_FIELDS_SETUP_SLUG = "CLUE_FIELDS_SETUP"

Arguments = Mapping[str, Any]


class WriteNotParsable(ValueError):
    """The arguments do not describe one change the person could be shown."""


@dataclass(frozen=True)
class ParsedChange:
    object: str
    #: The CRM id of the record; ``None`` for a record that does not exist yet.
    record_ref: str | None
    #: Field -> the value the change sets (empty for membership). ``None`` or ``""`` clears it.
    fields: Mapping[str, object]
    #: The list (HubSpot) or campaign (Salesforce) for membership kinds.
    list_ref: str | None
    #: What the card calls the record: its name or email, else its id.
    label: str
    #: Set only when one action carries two kinds (HubSpot's list membership adds and removes);
    #: read it through :meth:`change_kind`.
    kind: WriteKind | None = None

    def change_kind(self, spec: WriteActionSpec) -> WriteKind:
        return self.kind or spec.kind


@dataclass(frozen=True)
class ItemOutcome:
    """What a batch result says about one of the changes it carried."""

    ok: bool
    crm_id: str | None
    #: The CRM's own words for a refused record, kept verbatim for the log.
    error: str | None = None


def _one_group(arguments: Arguments) -> str:
    del arguments
    return ""


@dataclass(frozen=True)
class BatchSpec:
    #: The action that carries many changes in one call.
    slug: str
    max_size: int
    #: The batch call's arguments from the single-change arguments of one group.
    build: Callable[[Sequence[Arguments]], dict[str, Any]]
    #: One outcome per item, in the order of the items the call was built from.
    split: Callable[[Any, Sequence[Arguments]], list[ItemOutcome]]
    #: Changes join one call only when their group is equal (e.g. the same list and operation).
    group: Callable[[Arguments], str] = dataclasses.field(default=_one_group)


@dataclass(frozen=True)
class WriteActionSpec:
    provider: CrmProvider
    slug: str
    kind: WriteKind
    object: str
    parse: Callable[[Arguments], ParsedChange]
    #: A read action that returns the record's current values (before-values, conflict check).
    read_before: str | None
    #: (read action, key field) to look for the record before creating it.
    find_existing: tuple[str, str] | None
    batch: BatchSpec | None


# --- helpers ----------------------------------------------------------------------------------


def _id(arguments: Arguments, name: str) -> str:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, str | int) or str(value).strip() == "":
        raise WriteNotParsable(f"'{name}' must be the record's CRM id.")
    return str(value).strip()


def _only(arguments: Arguments, allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise WriteNotParsable(
            f"These arguments cannot be shown to the person, so they are not sent: {unknown}."
        )


def _mapping(arguments: Arguments, name: str) -> Mapping[str, object]:
    value = arguments.get(name, {})
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise WriteNotParsable(f"'{name}' must be an object of field names to values.")
    return value


def _require_fields(fields: Mapping[str, object]) -> Mapping[str, object]:
    if not fields:
        raise WriteNotParsable("The change sets no field.")
    return fields


def _label(fields: Mapping[str, object], *names: str, fallback: str) -> str:
    for name in names:
        value = fields.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _error_text(value: Any) -> str | None:
    if value in (None, [], {}, ""):
        return None
    return value if isinstance(value, str) else json.dumps(value, default=str)


def _unwrap(data: Any) -> Any:
    """Composio sometimes nests the CRM's body one level down, under ``data``."""
    if isinstance(data, Mapping) and "data" in data and isinstance(data["data"], Mapping):
        return data["data"]
    return data


#: A membership change may add to a list the same batch creates, before it has an id: its
#: list argument is ``new:`` and the exact name the create gives the list (R-12.7). Preparation
#: checks the batch holds that create; the executor sends the create first and puts the new id in.
NEW_LIST_PREFIX = "new:"


def new_list_name(list_ref: str | None) -> str | None:
    """The name of the list a ``new:<name>`` reference points at; ``None`` for a CRM id."""
    if list_ref is None or not list_ref.startswith(NEW_LIST_PREFIX):
        return None
    return list_ref[len(NEW_LIST_PREFIX) :]


def website_host(value: object) -> str:
    """A website as the lower-case host it names: ``https://www.Acme.com/about`` is
    ``acme.com``. No scheme, ``www.``, port, path, query or trailing slash."""
    host = str(value or "").strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = re.split(r"[/?#]", host, maxsplit=1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    host = host.strip(".")
    return host.removeprefix("www.")


#: A change may also use a record the same batch creates, before it has an id (R-12.11): a
#: company or account by ``new:company:<domain>``, a person by ``new:contact:<email>``, spelled
#: like the create's domain (HubSpot ``domain``, Salesforce ``website``, matched as the host it
#: names) or email (without case or surrounding spaces). Only in the places
#: :func:`reference_in` reads; preparation checks the batch holds that create, and the executor
#: sends the create first and puts the new record's id in.
NEW_COMPANY_PREFIX = "new:company:"
NEW_CONTACT_PREFIX = "new:contact:"


def record_reference(value: object) -> str | None:
    """The reference ``value`` makes to a record the batch creates, spelled as Clue matches it
    (``new:company:<host>`` or ``new:contact:<email in lower case>``); ``None`` for any other
    value."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    lowered = text.lower()
    if lowered.startswith(NEW_COMPANY_PREFIX):
        return NEW_COMPANY_PREFIX + website_host(text[len(NEW_COMPANY_PREFIX) :])
    if lowered.startswith(NEW_CONTACT_PREFIX):
        return NEW_CONTACT_PREFIX + text[len(NEW_CONTACT_PREFIX) :].strip().lower()
    return None


def record_references(value: object) -> list[str]:
    """Every record reference anywhere in ``value`` (arguments, at any depth), in order."""
    if isinstance(value, Mapping):
        return [ref for item in value.values() for ref in record_references(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in record_references(item)]
    reference = record_reference(value)
    return [] if reference is None else [reference]


def created_reference(kind: str, fields: Mapping[str, object]) -> str | None:
    """The reference other changes use for the record a create makes: a company by the host of
    its domain or website, a person by their email. ``None`` for any other change, or a create
    with nothing to match on."""
    if kind == "create_company":
        host = website_host(fields.get("domain") or fields.get("Website") or "")
        return NEW_COMPANY_PREFIX + host if host else None
    if kind == "create_contact":
        email = next(
            (
                str(fields[name]).strip().lower()
                for name in ("email", "work_email", "Email")
                if isinstance(fields.get(name), str) and str(fields[name]).strip()
            ),
            None,
        )
        return NEW_CONTACT_PREFIX + email if email else None
    return None


def find_value(key: str, fields: Mapping[str, object]) -> object | None:
    """What a create is looked for by before it is made (R-7.1): its ``find_existing`` field.
    A person created with only ``work_email`` is looked for by that email under ``key``, spelled
    as :func:`created_reference` spells it, so preparation and the send find the same record."""
    value = fields.get(key)
    if key == "email" and (value is None or str(value).strip() == ""):
        made = created_reference("create_contact", fields)
        return made[len(NEW_CONTACT_PREFIX) :] if made is not None else None
    return value


def _reference_path(slug: str, arguments: Arguments) -> tuple[list[str | int], str] | None:
    """Where a change of ``slug`` may hold a record reference, and of which kind (R-12.11):
    a company added to a HubSpot list, a new person's company, a person added to a Salesforce
    campaign."""
    if slug == "HUBSPOT_UPDATE_LIST_MEMBERSHIPS" and arguments.get("operation") == "add":
        return ["record_ids", 0], NEW_COMPANY_PREFIX
    if slug == "HUBSPOT_CREATE_CONTACT":
        return ["associations", 0, "to", "id"], NEW_COMPANY_PREFIX
    if slug == "SALESFORCE_CREATE_CONTACT":
        return ["account_id"], NEW_COMPANY_PREFIX
    if slug == "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN":
        return ["contact_id"], NEW_CONTACT_PREFIX
    return None


def _at(arguments: Any, path: Sequence[str | int]) -> Any:
    value = arguments
    for step in path:
        if isinstance(step, int):
            if not isinstance(value, list) or len(value) <= step:
                return None
        elif not isinstance(value, Mapping):
            return None
        value = value[step] if isinstance(step, int) else value.get(step)
    return value


def reference_in(slug: str, arguments: Arguments) -> str | None:
    """The record reference a change holds in the one place its action may hold one; ``None``
    when that place holds a CRM id (or a reference of the other kind)."""
    place = _reference_path(slug, arguments)
    if place is None:
        return None
    path, prefix = place
    reference = record_reference(_at(arguments, path))
    return reference if reference is not None and reference.startswith(prefix) else None


def with_reference_filled(slug: str, arguments: Arguments, value: str) -> dict[str, Any]:
    """``arguments`` with the record reference :func:`reference_in` reads replaced by ``value``
    (the record's CRM id, or the reference as Clue spells it)."""
    place = _reference_path(slug, arguments)
    filled: dict[str, Any] = copy.deepcopy(dict(arguments))
    if place is None or _at(filled, place[0]) is None:
        return filled
    path = place[0]
    holder: Any = filled
    for step in path[:-1]:
        holder = holder[step]
    holder[path[-1]] = value
    return filled


# --- HubSpot ----------------------------------------------------------------------------------

#: HubSpot's object type ids of the objects a Clue list holds (composio-api-notes.md § Phase 3).
HUBSPOT_OBJECT_TYPE_IDS: Mapping[str, str] = {"company": "0-2", "contact": "0-1"}

#: Contact-to-company association types HubSpot defines (primary, unlabeled).
_HUBSPOT_CONTACT_COMPANY_TYPES = frozenset({1, 279})


def _hubspot_update_company(arguments: Arguments) -> ParsedChange:
    _only(arguments, {"companyId", "properties"})
    record = _id(arguments, "companyId")
    fields = _require_fields(_mapping(arguments, "properties"))
    return ParsedChange(
        "company", record, dict(fields), None, _label(fields, "name", fallback=record)
    )


def _hubspot_update_contacts(arguments: Arguments) -> ParsedChange:
    _only(arguments, {"inputs"})
    inputs = arguments.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], Mapping):
        raise WriteNotParsable("Propose one contact per change: 'inputs' must hold exactly one.")
    item = inputs[0]
    _only(item, {"id", "properties"})
    record = _id(item, "id")
    fields = _require_fields(_mapping(item, "properties"))
    return ParsedChange(
        "contact", record, dict(fields), None, _label(fields, "email", fallback=record)
    )


def _hubspot_list_membership(arguments: Arguments) -> ParsedChange:
    _only(arguments, {"list_id", "operation", "record_ids"})
    list_ref = _id(arguments, "list_id")
    operation = arguments.get("operation")
    if operation not in ("add", "remove"):
        raise WriteNotParsable("'operation' must be 'add' or 'remove'.")
    records = arguments.get("record_ids")
    if not isinstance(records, list) or len(records) != 1:
        raise WriteNotParsable("Propose one record per change: 'record_ids' must hold exactly one.")
    record = _id({"record_id": records[0]}, "record_id")
    kind: WriteKind = "list_membership" if operation == "add" else "list_removal"
    return ParsedChange("contact", record, {}, list_ref, record, kind=kind)


def _list_name(arguments: Arguments) -> str:
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WriteNotParsable("'name' must be the list's name.")
    return name.strip()


def _hubspot_create_list(arguments: Arguments) -> ParsedChange:
    _only(arguments, {"name", "object_type_id", "processing_type"})
    name = _list_name(arguments)
    if arguments.get("processing_type") != "MANUAL":
        raise WriteNotParsable(
            "Clue creates manual lists only: set 'processing_type' to \"MANUAL\"."
        )
    type_id = str(arguments.get("object_type_id"))
    object_name = next((o for o, t in HUBSPOT_OBJECT_TYPE_IDS.items() if t == type_id), None)
    if object_name is None:
        raise WriteNotParsable(
            '\'object_type_id\' must be "0-2" (a list of companies) or "0-1" (of contacts).'
        )
    return ParsedChange(object_name, None, {}, None, name)


def _hubspot_associated_company(associations: object) -> str | None:
    if associations in (None, []):
        return None
    if not isinstance(associations, list) or len(associations) != 1:
        raise WriteNotParsable("A new contact can be linked to one company only.")
    link = associations[0]
    target = link.get("to") if isinstance(link, Mapping) else None
    types = link.get("types") if isinstance(link, Mapping) else None
    if (
        not isinstance(target, Mapping)
        or not isinstance(types, list)
        or not types
        or not all(
            isinstance(t, Mapping)
            and t.get("associationCategory") == "HUBSPOT_DEFINED"
            and t.get("associationTypeId") in _HUBSPOT_CONTACT_COMPANY_TYPES
            for t in types
        )
    ):
        raise WriteNotParsable(
            "A new contact's only link may be to its company (HUBSPOT_DEFINED, type 1 or 279)."
        )
    return _id(target, "id")


def _hubspot_create(object_name: str, *label_fields: str) -> Callable[[Arguments], ParsedChange]:
    def parse(arguments: Arguments) -> ParsedChange:
        fields: dict[str, object] = {
            name: value
            for name, value in arguments.items()
            if name not in ("custom_properties", "associations")
        }
        fields.update(_mapping(arguments, "custom_properties"))
        if object_name == "contact":
            company = _hubspot_associated_company(arguments.get("associations"))
            if company is not None:
                fields["associatedcompanyid"] = company
        elif arguments.get("associations") not in (None, []):
            raise WriteNotParsable("A new company is created without links.")
        _require_fields(fields)
        return ParsedChange(
            object_name, None, fields, None, _label(fields, *label_fields, fallback="new record")
        )

    return parse


def _hubspot_inputs_build(id_arg: str) -> Callable[[Sequence[Arguments]], dict[str, Any]]:
    def build(items: Sequence[Arguments]) -> dict[str, Any]:
        if id_arg == "inputs":  # already the batch shape, one input each
            return {"inputs": [dict(item["inputs"][0]) for item in items]}
        return {
            "inputs": [
                {"id": str(item[id_arg]), "properties": dict(item["properties"])} for item in items
            ]
        }

    return build


def _hubspot_record_id(item: Arguments) -> str:
    if "inputs" in item:
        return str(item["inputs"][0]["id"])
    if "record_ids" in item:
        return str(item["record_ids"][0])
    return str(item["companyId"])


def _hubspot_split_results(data: Any, items: Sequence[Arguments]) -> list[ItemOutcome]:
    """HubSpot batch update: every record written is in ``results``; one that is not, failed."""
    body = _unwrap(data)
    results = body.get("results") if isinstance(body, Mapping) else None
    written = {
        str(result["id"])
        for result in results or []
        if isinstance(result, Mapping) and result.get("id") is not None
    }
    errors = _error_text(body.get("errors")) if isinstance(body, Mapping) else None
    outcomes = []
    for item in items:
        record = _hubspot_record_id(item)
        ok = record in written
        outcomes.append(ItemOutcome(ok, record, None if ok else errors or "Not in the result."))
    return outcomes


def _hubspot_list_group(item: Arguments) -> str:
    return f"{item['list_id']}:{item['operation']}"


def _hubspot_list_build(items: Sequence[Arguments]) -> dict[str, Any]:
    first = items[0]
    return {
        "list_id": first["list_id"],
        "operation": first["operation"],
        "record_ids": [str(item["record_ids"][0]) for item in items],
    }


def _hubspot_list_split(data: Any, items: Sequence[Arguments]) -> list[ItemOutcome]:
    """A record HubSpot could not find is in ``recordIdsMissing``; every other one is done
    (a record already in, or already out of, the list is not listed as added or removed)."""
    body = _unwrap(data)
    missing = (
        {str(i) for i in (body.get("recordIdsMissing") or [])}
        if isinstance(body, Mapping)
        else set()
    )
    outcomes = []
    for item in items:
        record = _hubspot_record_id(item)
        ok = record not in missing
        outcomes.append(
            ItemOutcome(ok, record, None if ok else "HubSpot could not find the record.")
        )
    return outcomes


# --- Salesforce -------------------------------------------------------------------------------

_SALESFORCE_ACCOUNT_ARGS: Mapping[str, str] = {
    "name": "Name",
    "type": "Type",
    "phone": "Phone",
    "fax": "Fax",
    "website": "Website",
    "industry": "Industry",
    "sic_desc": "SicDesc",
    "parent_id": "ParentId",
    "description": "Description",
    "account_source": "AccountSource",
    "annual_revenue": "AnnualRevenue",
    "number_of_employees": "NumberOfEmployees",
    "billing_street": "BillingStreet",
    "billing_city": "BillingCity",
    "billing_state": "BillingState",
    "billing_postal_code": "BillingPostalCode",
    "billing_country": "BillingCountry",
    "shipping_street": "ShippingStreet",
    "shipping_city": "ShippingCity",
    "shipping_state": "ShippingState",
    "shipping_postal_code": "ShippingPostalCode",
    "shipping_country": "ShippingCountry",
}

_SALESFORCE_CONTACT_ARGS: Mapping[str, str] = {
    "first_name": "FirstName",
    "last_name": "LastName",
    "email": "Email",
    "title": "Title",
    "department": "Department",
    "account_id": "AccountId",
    "phone": "Phone",
    "mobile_phone": "MobilePhone",
    "birthdate": "Birthdate",
    "lead_source": "LeadSource",
    "mailing_street": "MailingStreet",
    "mailing_city": "MailingCity",
    "mailing_state": "MailingState",
    "mailing_postal_code": "MailingPostalCode",
    "mailing_country": "MailingCountry",
}

_SALESFORCE_SOBJECT = {"account": "Account", "contact": "Contact"}


def _salesforce_fields(
    arguments: Arguments, names: Mapping[str, str], id_arg: str | None
) -> dict[str, object]:
    allowed = set(names) | {"custom_fields"} | ({id_arg} if id_arg else set())
    _only(arguments, allowed)
    fields: dict[str, object] = {
        names[name]: value for name, value in arguments.items() if name in names
    }
    fields.update(_mapping(arguments, "custom_fields"))
    return _require_fields(fields)  # type: ignore[return-value]


def _salesforce_update(
    object_name: str, id_arg: str, names: Mapping[str, str], *labels: str
) -> Callable[[Arguments], ParsedChange]:
    def parse(arguments: Arguments) -> ParsedChange:
        record = _id(arguments, id_arg)
        fields = _salesforce_fields(arguments, names, id_arg)
        return ParsedChange(
            object_name, record, fields, None, _label(fields, *labels, fallback=record)
        )

    return parse


def _salesforce_create(
    object_name: str, names: Mapping[str, str], required: str, *labels: str
) -> Callable[[Arguments], ParsedChange]:
    def parse(arguments: Arguments) -> ParsedChange:
        fields = _salesforce_fields(arguments, names, None)
        if not isinstance(fields.get(required), str) or not str(fields[required]).strip():
            raise WriteNotParsable(f"Salesforce needs {required} to create the record.")
        return ParsedChange(
            object_name, None, fields, None, _label(fields, *labels, fallback="new record")
        )

    return parse


def _salesforce_add_to_campaign(arguments: Arguments) -> ParsedChange:
    _only(arguments, {"campaign_id", "contact_id", "status"})
    record = _id(arguments, "contact_id")
    return ParsedChange("contact", record, {}, _id(arguments, "campaign_id"), record)


def _salesforce_remove_from_campaign(arguments: Arguments) -> ParsedChange:
    # Only by the contact's id, so the card and the undo name the person, not a member row.
    _only(arguments, {"campaign_id", "member_id"})
    record = _id(arguments, "member_id")
    return ParsedChange("contact", record, {}, _id(arguments, "campaign_id"), record)


#: How Clue creates every Salesforce campaign (R-12.9): active and "In Progress", because a target
#: list is in use from the start (an inactive "Planned" one is hidden from most reports and
#: pickers). Preparation adds these to the name the agent gives; the card says so.
CLUE_CAMPAIGN_SETTINGS: Mapping[str, object] = {"is_active": True, "status": "In Progress"}


def _salesforce_create_campaign(arguments: Arguments) -> ParsedChange:
    # The name, and only the settings Clue itself sends, so the card shows everything sent.
    _only(arguments, {"name", *CLUE_CAMPAIGN_SETTINGS})
    for setting, value in CLUE_CAMPAIGN_SETTINGS.items():
        if setting in arguments and arguments[setting] != value:
            raise WriteNotParsable(
                f"Clue creates campaigns with {setting} {value!r} (R-12.9); leave '{setting}' out."
            )
    return ParsedChange("contact", None, {}, None, _list_name(arguments))


def _salesforce_composite_build(
    object_name: str, parse: Callable[[Arguments], ParsedChange]
) -> Callable[[Sequence[Arguments]], dict[str, Any]]:
    sobject = _SALESFORCE_SOBJECT[object_name]

    def build(items: Sequence[Arguments]) -> dict[str, Any]:
        records = []
        for item in items:
            change = parse(item)
            # ``None`` clears the field here, which the named update tools cannot do (undo).
            records.append(
                {"attributes": {"type": sobject}, "Id": change.record_ref, **change.fields}
            )
        return {
            "sobject_name": sobject,
            "external_id_field_name": "Id",
            "all_or_none": False,
            "records": records,
        }

    return build


def _salesforce_composite_split(
    id_arg: str,
) -> Callable[[Any, Sequence[Arguments]], list[ItemOutcome]]:
    """Salesforce answers ``successful`` even when records fail: each result, in request order,
    carries its own ``success`` and ``errors``."""

    def split(data: Any, items: Sequence[Arguments]) -> list[ItemOutcome]:
        body = _unwrap(data)
        results = body.get("results") if isinstance(body, Mapping) else body
        results = results if isinstance(results, list) else []
        outcomes = []
        for index, item in enumerate(items):
            record = str(item[id_arg])
            result = results[index] if index < len(results) else None
            if not isinstance(result, Mapping):
                outcomes.append(ItemOutcome(False, record, "Not in the result."))
                continue
            # By position: Salesforce answers in request order (its ids may be 18 characters
            # where the request used 15).
            ok = result.get("success") is True
            outcomes.append(
                ItemOutcome(
                    ok, record, None if ok else _error_text(result.get("errors")) or "Refused."
                )
            )
        return outcomes

    return split


# --- the allowlist ----------------------------------------------------------------------------

_HUBSPOT_READ = "HUBSPOT_READ_CRM_OBJECT_BY_ID"
_SOQL = "SALESFORCE_RUN_SOQL_QUERY"

_hubspot_list_batch = BatchSpec(
    slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
    max_size=100,  # no stated maximum; kept to HubSpot's usual batch size
    build=_hubspot_list_build,
    split=_hubspot_list_split,
    group=_hubspot_list_group,
)

_sf_update_account = _salesforce_update("account", "account_id", _SALESFORCE_ACCOUNT_ARGS, "Name")
_sf_update_contact = _salesforce_update("contact", "contact_id", _SALESFORCE_CONTACT_ARGS, "Email")

_SPECS: tuple[WriteActionSpec, ...] = (
    # HubSpot
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_UPDATE_COMPANY",
        kind="field_update",
        object="company",
        parse=_hubspot_update_company,
        read_before=_HUBSPOT_READ,
        find_existing=None,
        batch=BatchSpec(
            slug="HUBSPOT_UPDATE_COMPANIES",
            max_size=100,
            build=_hubspot_inputs_build("companyId"),
            split=_hubspot_split_results,
        ),
    ),
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_UPDATE_CONTACTS",
        kind="field_update",
        object="contact",
        parse=_hubspot_update_contacts,
        read_before=_HUBSPOT_READ,
        find_existing=None,
        batch=BatchSpec(
            slug="HUBSPOT_UPDATE_CONTACTS",
            max_size=100,
            build=_hubspot_inputs_build("inputs"),
            split=_hubspot_split_results,
        ),
    ),
    # Verified live (Phase 3 Task 1, company lists): add answers {recordsIdsAdded}, remove
    # {recordIdsRemoved}; adding an existing member is successful with empty data.
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        kind="list_membership",  # operation "remove" is a list_removal (ParsedChange.kind)
        object="contact",
        parse=_hubspot_list_membership,
        read_before="HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS",
        find_existing=None,
        batch=_hubspot_list_batch,
    ),
    # Schema only — verified at the Phase 2 live check.
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_CREATE_CONTACT",
        kind="create_contact",
        object="contact",
        parse=_hubspot_create("contact", "email", "work_email"),
        read_before=None,
        find_existing=("HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA", "email"),
        batch=None,
    ),
    # Schema only — verified at the Phase 2 live check.
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_CREATE_COMPANY",
        kind="create_company",
        object="company",
        parse=_hubspot_create("company", "name", "domain"),
        read_before=None,
        find_existing=("HUBSPOT_SEARCH_COMPANIES", "domain"),
        batch=None,
    ),
    # Verified live (Phase 3 Task 1): a manual company list.
    WriteActionSpec(
        provider="hubspot",
        slug="HUBSPOT_CREATE_LIST",
        kind="list_create",
        object="company",  # or contact: the parsed change carries the list's object
        parse=_hubspot_create_list,
        read_before=None,
        find_existing=None,
        batch=None,
    ),
    # Salesforce
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_UPDATE_ACCOUNT",
        kind="field_update",
        object="account",
        parse=_sf_update_account,
        read_before=_SOQL,
        find_existing=None,
        batch=BatchSpec(
            slug="SALESFORCE_PATCH_COMPOSITE_SOBJECTS",
            max_size=200,
            build=_salesforce_composite_build("account", _sf_update_account),
            split=_salesforce_composite_split("account_id"),
        ),
    ),
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_UPDATE_CONTACT",
        kind="field_update",
        object="contact",
        parse=_sf_update_contact,
        read_before=_SOQL,
        find_existing=None,
        batch=BatchSpec(
            slug="SALESFORCE_PATCH_COMPOSITE_SOBJECTS",
            max_size=200,
            build=_salesforce_composite_build("contact", _sf_update_contact),
            split=_salesforce_composite_split("contact_id"),
        ),
    ),
    # Verified live (Phase 3 Task 1): answers {id, success, errors}; the member's Status is the
    # campaign's default ("Sent"). Adding an existing member is refused ("Already a campaign
    # member.", DUPLICATE_VALUE), so read_before checks membership by SOQL.
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
        kind="list_membership",
        object="contact",
        parse=_salesforce_add_to_campaign,
        read_before=_SOQL,
        find_existing=None,
        batch=None,
    ),
    # Verified live (Phase 3 Task 1): ``member_id`` takes the contact's id; answers {}.
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_REMOVE_FROM_CAMPAIGN",
        kind="list_removal",
        object="contact",
        parse=_salesforce_remove_from_campaign,
        read_before=_SOQL,
        find_existing=None,
        batch=None,
    ),
    # Schema only — verified at the Phase 2 live check.
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_CREATE_CONTACT",
        kind="create_contact",
        object="contact",
        parse=_salesforce_create("contact", _SALESFORCE_CONTACT_ARGS, "LastName", "Email"),
        read_before=None,
        find_existing=(_SOQL, "Email"),
        batch=None,
    ),
    # Schema only — verified at the Phase 2 live check (which response shape carries the id).
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_CREATE_ACCOUNT",
        kind="create_company",
        object="account",
        parse=_salesforce_create("account", _SALESFORCE_ACCOUNT_ARGS, "Name", "Name"),
        read_before=None,
        find_existing=(_SOQL, "Website"),
        batch=None,
    ),
    # Verified live (Phase 3 Task 1 re-run): answers {id, success, errors}; a new campaign is
    # "Planned". Only a Marketing User may create one. A campaign holds contacts.
    WriteActionSpec(
        provider="salesforce",
        slug="SALESFORCE_CREATE_CAMPAIGN",
        kind="list_create",
        object="contact",
        parse=_salesforce_create_campaign,
        read_before=None,
        find_existing=None,
        batch=None,
    ),
)

WRITE_ACTIONS: Mapping[tuple[CrmProvider, str], WriteActionSpec] = {
    (spec.provider, spec.slug): spec for spec in _SPECS
}


def write_spec(provider: CrmProvider, slug: str) -> WriteActionSpec | None:
    return WRITE_ACTIONS.get((provider, slug))


def is_write(provider: CrmProvider, slug: str) -> bool:
    return (provider, slug) in WRITE_ACTIONS


# --- setting up Clue's own fields (Phase 4, R-13.4) -----------------------------------------------


def clue_fields_setup_arguments(provider: CrmProvider) -> dict[str, Any]:
    """The setup change's arguments: every Clue field of ``provider``, by qualified name, in
    :data:`CLUE_FIELDS` order. Built from code; the agent gives none of it."""
    return {"fields": [field.qualified_name for field in CLUE_FIELDS[provider]]}


def _clue_fields_setup_parse(provider: CrmProvider) -> Callable[[Arguments], ParsedChange]:
    def parse(arguments: Arguments) -> ParsedChange:
        if dict(arguments) != clue_fields_setup_arguments(provider):
            raise WriteNotParsable("Clue's fields are set up exactly as Clue defines them.")
        return ParsedChange("clue_fields", None, {}, None, "Clue's fields")

    return parse


def clue_fields_setup_spec(provider: CrmProvider) -> WriteActionSpec:
    """The ``clue_fields_setup`` change of ``provider``. Not in :data:`WRITE_ACTIONS`: nothing
    proposes it but ``propose_clue_fields_setup``."""
    return WriteActionSpec(
        provider=provider,
        slug=CLUE_FIELDS_SETUP_SLUG,
        kind=CLUE_FIELDS_SETUP,
        object="clue_fields",
        parse=_clue_fields_setup_parse(provider),
        read_before=None,
        find_existing=None,
        batch=None,
    )


# --- fields never written (ruling R-8.7) -------------------------------------------------------

#: Consent and phone fields of a person. Company phone numbers are not personal data.
_FORBIDDEN: Mapping[tuple[CrmProvider, str], frozenset[str]] = {
    ("hubspot", "contact"): frozenset(
        {
            "phone",
            "mobilephone",
            "fax",
            "hs_whatsapp_phone_number",
            "hs_calculated_phone_number",
            "hs_calculated_mobile_number",
            "hs_searchable_calculated_phone_number",
            "hs_searchable_calculated_mobile_number",
            "hs_email_optout",
            "hs_legal_basis",
            "hs_marketable_status",
            "hs_marketable_reason_id",
            "hs_marketable_reason_type",
        }
    ),
    ("salesforce", "contact"): frozenset(
        {
            "Phone",
            "MobilePhone",
            "HomePhone",
            "OtherPhone",
            "AssistantPhone",
            "Fax",
            "HasOptedOutOfEmail",
            "HasOptedOutOfFax",
            "DoNotCall",
            "IndividualId",
        }
    ),
}

#: Families named per subscription or channel (``hs_email_optout_<subscription id>``).
_FORBIDDEN_PREFIXES: Mapping[tuple[CrmProvider, str], tuple[str, ...]] = {
    ("hubspot", "contact"): ("hs_email_optout_", "hs_sms_", "hs_whatsapp_", "hs_calculated_phone"),
}


def forbidden_fields(provider: CrmProvider, object: str) -> frozenset[str]:  # noqa: A002
    """Consent and phone fields of this CRM object, which Clue never writes."""
    return _FORBIDDEN.get((provider, object), frozenset())


def is_forbidden_field(provider: CrmProvider, object: str, field_name: str) -> bool:  # noqa: A002
    """:func:`forbidden_fields`, plus the families HubSpot names per subscription."""
    if field_name in forbidden_fields(provider, object):
        return True
    return field_name.startswith(_FORBIDDEN_PREFIXES.get((provider, object), ()))


def scope_key(spec: WriteActionSpec, parsed: ParsedChange, field: str | None) -> str:
    """What a standing permission covers: one field of one object, or one kind of change.

    The kind is the parsed change's own (:meth:`ParsedChange.change_kind`), never the action's:
    HubSpot's list membership action both adds and removes, and a grant to add must never cover
    removing. A field update is scoped by its field; every other kind by the kind alone.
    """
    kind = parsed.change_kind(spec)
    if kind == "field_update":
        if not field or field not in parsed.fields:
            raise ValueError("A field update is scoped by one of the fields it sets.")
        return f"field:{spec.object}.{field}"
    if field is not None:
        raise ValueError(f"A {kind} change sets no field to scope by.")
    return f"kind:{kind}"


def single_field_arguments(
    spec: WriteActionSpec, record_ref: str, field: str, value: object
) -> dict[str, Any]:
    """The arguments of ``spec`` (a field update) that set one field on one record.

    A proposal that sets three fields is logged as three writes, each carrying only its own field,
    so every logged write can be sent, retried and undone on its own.
    """
    if spec.kind != "field_update":
        raise ValueError(f"{spec.slug} is not a field update.")
    if spec.slug == "HUBSPOT_UPDATE_COMPANY":
        return {"companyId": record_ref, "properties": {field: value}}
    if spec.slug == "HUBSPOT_UPDATE_CONTACTS":
        return {"inputs": [{"id": record_ref, "properties": {field: value}}]}
    names, id_arg = {
        "SALESFORCE_UPDATE_ACCOUNT": (_SALESFORCE_ACCOUNT_ARGS, "account_id"),
        "SALESFORCE_UPDATE_CONTACT": (_SALESFORCE_CONTACT_ARGS, "contact_id"),
    }[spec.slug]
    argument = next((arg for arg, api_name in names.items() if api_name == field), None)
    if argument is None:
        return {id_arg: record_ref, "custom_fields": {field: value}}
    return {id_arg: record_ref, argument: value}


def field_update_spec(provider: CrmProvider, object: str) -> WriteActionSpec:  # noqa: A002
    """The allowlisted field update of this CRM object (a create that finds its record uses it)."""
    for spec in _SPECS:
        if spec.provider == provider and spec.object == object and spec.kind == "field_update":
            return spec
    raise LookupError(f"No field update for {provider} {object}.")
