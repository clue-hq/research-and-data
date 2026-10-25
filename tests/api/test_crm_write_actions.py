"""The CRM write allowlist (CRM integration Phase 2, Task 3).

Which Composio write actions Clue may propose, how each one's arguments are read into the change
the person is shown, and which fields are never written (consent and phone, ruling R-8.7). The
example arguments follow the shapes verified (or read from the schema) in
``docs/superpowers/specs/crm-integration/composio-api-notes.md`` § Writes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pytest

from clue_api.crm.write_actions import (
    WRITE_ACTIONS,
    ParsedChange,
    WriteNotParsable,
    field_update_spec,
    forbidden_fields,
    is_forbidden_field,
    scope_key,
    single_field_arguments,
    write_spec,
)

_EXAMPLES: dict[tuple[str, str], tuple[dict[str, Any], ParsedChange]] = {
    ("hubspot", "HUBSPOT_UPDATE_COMPANY"): (
        {"companyId": "101", "properties": {"industry": "HOSPITALITY", "name": "Aldercare"}},
        ParsedChange(
            "company", "101", {"industry": "HOSPITALITY", "name": "Aldercare"}, None, "Aldercare"
        ),
    ),
    ("hubspot", "HUBSPOT_UPDATE_CONTACTS"): (
        {"inputs": [{"id": "201", "properties": {"jobtitle": "COO"}}]},
        ParsedChange("contact", "201", {"jobtitle": "COO"}, None, "201"),
    ),
    ("hubspot", "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID"): (
        {"objectType": "contacts", "objectId": "201", "properties": {"clue_id": "c-1"}},
        ParsedChange("contact", "201", {"clue_id": "c-1"}, None, "201"),
    ),
    ("hubspot", "HUBSPOT_UPDATE_LIST_MEMBERSHIPS"): (
        {"list_id": "9", "operation": "add", "record_ids": ["201"]},
        ParsedChange("contact", "201", {}, "9", "201", kind="list_membership"),
    ),
    ("hubspot", "HUBSPOT_CREATE_CONTACT"): (
        {
            "email": "ana@aldercare.example.com",
            "firstname": "Ana",
            "lastname": "Ruiz",
            "associations": [
                {
                    "to": {"id": "101"},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 279}],
                }
            ],
        },
        ParsedChange(
            "contact",
            None,
            {
                "email": "ana@aldercare.example.com",
                "firstname": "Ana",
                "lastname": "Ruiz",
                "associatedcompanyid": "101",
            },
            None,
            "ana@aldercare.example.com",
        ),
    ),
    ("hubspot", "HUBSPOT_CREATE_COMPANY"): (
        {"name": "Aldercare", "domain": "aldercare.test", "custom_properties": {"tier": "1"}},
        ParsedChange(
            "company",
            None,
            {"name": "Aldercare", "domain": "aldercare.test", "tier": "1"},
            None,
            "Aldercare",
        ),
    ),
    ("hubspot", "HUBSPOT_CREATE_LIST"): (
        {"name": "Clue: Q4 hotel groups", "object_type_id": "0-2", "processing_type": "MANUAL"},
        ParsedChange("company", None, {}, None, "Clue: Q4 hotel groups"),
    ),
    ("hubspot", "HUBSPOT_CREATE_OBJECT_ASSOCIATION"): (
        {"objectId": "201", "toObjectId": "202"},
        ParsedChange("contact", "201", {}, None, "201", duplicate_ref="202"),
    ),
    ("salesforce", "SALESFORCE_CREATE_CAMPAIGN"): (
        {"name": "Clue: Q4 hotel groups"},
        ParsedChange("contact", None, {}, None, "Clue: Q4 hotel groups"),
    ),
    ("salesforce", "SALESFORCE_UPDATE_ACCOUNT"): (
        {"account_id": "001A", "industry": "Hospitality", "custom_fields": {"Tier__c": "1"}},
        ParsedChange("account", "001A", {"Industry": "Hospitality", "Tier__c": "1"}, None, "001A"),
    ),
    ("salesforce", "SALESFORCE_UPDATE_CONTACT"): (
        {"contact_id": "003A", "title": "COO", "first_name": "Ana"},
        ParsedChange("contact", "003A", {"Title": "COO", "FirstName": "Ana"}, None, "003A"),
    ),
    ("salesforce", "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN"): (
        {"campaign_id": "701A", "contact_id": "003A", "status": "Sent"},
        ParsedChange("contact", "003A", {}, "701A", "003A"),
    ),
    ("salesforce", "SALESFORCE_REMOVE_FROM_CAMPAIGN"): (
        {"campaign_id": "701A", "member_id": "003A"},
        ParsedChange("contact", "003A", {}, "701A", "003A"),
    ),
    ("salesforce", "SALESFORCE_CREATE_CONTACT"): (
        {
            "last_name": "Ruiz",
            "first_name": "Ana",
            "email": "ana@aldercare.example.com",
            "account_id": "001A",
        },
        ParsedChange(
            "contact",
            None,
            {
                "LastName": "Ruiz",
                "FirstName": "Ana",
                "Email": "ana@aldercare.example.com",
                "AccountId": "001A",
            },
            None,
            "ana@aldercare.example.com",
        ),
    ),
    ("salesforce", "SALESFORCE_CREATE_ACCOUNT"): (
        {"name": "Aldercare", "website": "aldercare.test"},
        ParsedChange(
            "account", None, {"Name": "Aldercare", "Website": "aldercare.test"}, None, "Aldercare"
        ),
    ),
}


def test_no_allowlisted_write_merges_deletes_or_runs_an_llm() -> None:
    risky = re.compile(r"MERGE|DELETE|_FROM_NL|GDPR|ERASE")
    offenders = [
        slug
        for (_provider, slug), spec in WRITE_ACTIONS.items()
        if risky.search(slug) and spec.kind != "list_removal"
    ]
    assert offenders == []
    assert all(spec.slug == slug for (_p, slug), spec in WRITE_ACTIONS.items())
    assert all(provider == spec.provider for (provider, _s), spec in WRITE_ACTIONS.items())
    # HUBSPOT_UPDATE_CONTACT reported success on a refused write (composio-api-notes § Writes).
    assert write_spec("hubspot", "HUBSPOT_UPDATE_CONTACT") is None
    # Deprecated in the pinned Salesforce toolkit.
    assert write_spec("salesforce", "SALESFORCE_UPDATE_ACCOUNT_OBJECT_BY_ID") is None
    assert write_spec("salesforce", "SALESFORCE_UPDATE_CONTACT_BY_ID") is None
    assert write_spec("hubspot", "HUBSPOT_SEARCH_DEALS") is None


def test_the_allowlist_covers_every_kind() -> None:
    for provider in ("hubspot", "salesforce"):
        kinds = {spec.kind for (p, _s), spec in WRITE_ACTIONS.items() if p == provider}
        assert kinds >= {
            "field_update",
            "list_membership",
            "create_contact",
            "create_company",
            "list_create",
        }
    assert {spec.kind for spec in WRITE_ACTIONS.values()} >= {"list_removal", "link_duplicate"}


def test_a_salesforce_duplicate_link_is_a_contact_update_of_clues_lookup_alone() -> None:
    """Phase 4 (R-6.13): setting Clue_Possible_Duplicate__c is a link_duplicate, scoped by its
    kind; clearing it is an ordinary field update (only Clue's own undo passes preparation)."""
    spec = write_spec("salesforce", "SALESFORCE_UPDATE_CONTACT")
    assert spec is not None
    link = spec.parse(
        {"contact_id": "003A", "custom_fields": {"Clue_Possible_Duplicate__c": "003B"}}
    )
    assert (link.change_kind(spec), link.duplicate_ref) == ("link_duplicate", "003B")
    assert scope_key(spec, link, None) == "kind:link_duplicate"
    cleared = spec.parse(
        {"contact_id": "003A", "custom_fields": {"Clue_Possible_Duplicate__c": None}}
    )
    assert cleared.change_kind(spec) == "field_update"
    assert cleared.duplicate_ref is None


def test_consent_and_phone_fields_are_forbidden() -> None:
    hubspot = forbidden_fields("hubspot", "contact")
    assert {"hs_email_optout", "phone", "mobilephone"} <= hubspot
    salesforce = forbidden_fields("salesforce", "contact")
    assert {"HasOptedOutOfEmail", "DoNotCall", "Phone", "MobilePhone", "HomePhone"} <= salesforce
    assert {"HasOptedOutOfFax", "OtherPhone", "AssistantPhone", "Fax"} <= salesforce
    # Subscription-specific HubSpot opt-outs are named per subscription.
    assert is_forbidden_field("hubspot", "contact", "hs_email_optout_12345")
    assert is_forbidden_field("salesforce", "contact", "MobilePhone")
    assert not is_forbidden_field("hubspot", "contact", "jobtitle")
    assert not is_forbidden_field("hubspot", "company", "industry")


@pytest.mark.parametrize(("key", "example"), sorted(_EXAMPLES.items()), ids=lambda v: str(v))
def test_each_spec_parses_its_own_example(
    key: tuple[str, str], example: tuple[dict[str, Any], ParsedChange]
) -> None:
    arguments, expected = example
    spec = write_spec(key[0], key[1])  # type: ignore[arg-type]
    assert spec is not None
    parsed = spec.parse(arguments)
    assert parsed == expected
    assert parsed.change_kind(spec) == (expected.kind or spec.kind)


def test_every_spec_has_an_example() -> None:
    assert set(WRITE_ACTIONS) == set(_EXAMPLES)


def test_a_hubspot_contact_field_update_is_sent_by_id() -> None:
    """Phase 4 live check: Composio's HUBSPOT_UPDATE_CONTACTS drops every non-standard property,
    so a contact's field update is logged and sent as the by-id update, one record per call."""
    proposed = write_spec("hubspot", "HUBSPOT_UPDATE_CONTACTS")
    sent = field_update_spec("hubspot", "contact")
    assert proposed is not None and proposed.batch is None
    assert sent.slug == "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID" and sent.batch is None
    assert (sent.kind, sent.object, sent.read_before) == (
        "field_update",
        "contact",
        proposed.read_before,
    )
    arguments = single_field_arguments(sent, "201", "hs_buying_role", "CHAMPION")
    assert arguments == {
        "objectType": "contacts",
        "objectId": "201",
        "properties": {"hs_buying_role": "CHAMPION"},
    }
    assert sent.parse(arguments) == ParsedChange(
        "contact", "201", {"hs_buying_role": "CHAMPION"}, None, "201"
    )
    # Scoped like the proposed action, so a grant covers both.
    parsed = proposed.parse({"inputs": [{"id": "201", "properties": {"jobtitle": "COO"}}]})
    assert scope_key(proposed, parsed, "jobtitle") == scope_key(sent, parsed, "jobtitle")
    # Companies stay on their batch tool (custom properties work there).
    assert field_update_spec("hubspot", "company").slug == "HUBSPOT_UPDATE_COMPANY"


def test_hubspot_list_removal_is_its_own_kind_and_scope() -> None:
    spec = write_spec("hubspot", "HUBSPOT_UPDATE_LIST_MEMBERSHIPS")
    assert spec is not None
    parsed = spec.parse({"list_id": "9", "operation": "remove", "record_ids": ["201"]})
    assert parsed.change_kind(spec) == "list_removal"
    assert scope_key(spec, parsed, None) == "kind:list_removal"


def test_a_list_removal_never_matches_a_list_add_grant() -> None:
    spec = write_spec("hubspot", "HUBSPOT_UPDATE_LIST_MEMBERSHIPS")
    assert spec is not None
    add = spec.parse({"list_id": "9", "operation": "add", "record_ids": ["201"]})
    remove = spec.parse({"list_id": "9", "operation": "remove", "record_ids": ["201"]})
    add_grant = scope_key(spec, add, None)
    assert add_grant == "kind:list_membership"
    assert scope_key(spec, remove, None) != add_grant
    # Salesforce's two actions agree with HubSpot's one.
    sf_add = write_spec("salesforce", "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN")
    sf_remove = write_spec("salesforce", "SALESFORCE_REMOVE_FROM_CAMPAIGN")
    assert sf_add is not None and sf_remove is not None
    assert (
        scope_key(sf_add, sf_add.parse({"campaign_id": "7", "contact_id": "3"}), None) == add_grant
    )
    assert scope_key(
        sf_remove, sf_remove.parse({"campaign_id": "7", "member_id": "3"}), None
    ) == scope_key(spec, remove, None)


@pytest.mark.parametrize(
    ("provider", "slug", "arguments", "object_name"),
    [
        (
            "hubspot",
            "HUBSPOT_CREATE_LIST",
            {"name": "Clue: Q4", "object_type_id": "0-2", "processing_type": "MANUAL"},
            "company",
        ),
        (
            "hubspot",
            "HUBSPOT_CREATE_LIST",
            {"name": "Clue: Q4", "object_type_id": "0-1", "processing_type": "MANUAL"},
            "contact",
        ),
        ("salesforce", "SALESFORCE_CREATE_CAMPAIGN", {"name": "Clue: Q4"}, "contact"),
    ],
)
def test_create_list_is_a_list_create_change(
    provider: str, slug: str, arguments: Mapping[str, Any], object_name: str
) -> None:
    spec = write_spec(provider, slug)  # type: ignore[arg-type]
    assert spec is not None
    parsed = spec.parse(arguments)
    assert parsed.change_kind(spec) == "list_create"
    assert (parsed.object, parsed.record_ref, parsed.label) == (object_name, None, "Clue: Q4")
    assert parsed.fields == {} and parsed.list_ref is None
    assert scope_key(spec, parsed, None) == "kind:list_create"
    # Nothing is read before a list is created, and it is never a batch.
    assert spec.read_before is None and spec.batch is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "Clue: Q4", "object_type_id": "0-2", "processing_type": "DYNAMIC"},
        {"name": "Clue: Q4", "object_type_id": "0-2", "processing_type": "SNAPSHOT"},
        {"name": "Clue: Q4", "object_type_id": "0-2"},
    ],
)
def test_hubspot_creates_manual_lists_only(arguments: Mapping[str, Any]) -> None:
    spec = write_spec("hubspot", "HUBSPOT_CREATE_LIST")
    assert spec is not None
    with pytest.raises(WriteNotParsable, match="Clue creates manual lists only"):
        spec.parse(arguments)


def test_scope_keys() -> None:
    update = write_spec("hubspot", "HUBSPOT_UPDATE_COMPANY")
    create = write_spec("salesforce", "SALESFORCE_CREATE_CONTACT")
    assert update is not None and create is not None
    change = update.parse({"companyId": "1", "properties": {"industry": "A"}})
    assert scope_key(update, change, "industry") == "field:company.industry"
    new = create.parse({"last_name": "Ruiz"})
    assert scope_key(create, new, None) == "kind:create_contact"
    with pytest.raises(ValueError):
        scope_key(update, change, None)  # a field update is scoped by a field it sets
    with pytest.raises(ValueError):
        scope_key(update, change, "name")
    with pytest.raises(ValueError):
        scope_key(create, new, "LastName")  # a create is scoped by its kind only


@pytest.mark.parametrize(
    ("provider", "slug", "arguments"),
    [
        # one record per change, so the card and the log can name it
        (
            "hubspot",
            "HUBSPOT_UPDATE_CONTACTS",
            {"inputs": [{"id": "1", "properties": {"a": 1}}] * 2},
        ),
        (
            "hubspot",
            "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
            {"list_id": "9", "operation": "add", "record_ids": ["1", "2"]},
        ),
        (
            "hubspot",
            "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
            {"list_id": "9", "operation": "wipe", "record_ids": ["1"]},
        ),
        # an argument the card could not show is never sent
        ("salesforce", "SALESFORCE_UPDATE_ACCOUNT", {"account_id": "001A", "surprise": "x"}),
        (
            "salesforce",
            "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN",
            {"campaign_id": "7", "contact_id": "3", "custom_fields": {"X__c": 1}},
        ),
        (
            "salesforce",
            "SALESFORCE_REMOVE_FROM_CAMPAIGN",
            {"campaign_id": "7", "campaign_member_id": "00v"},
        ),
        ("hubspot", "HUBSPOT_UPDATE_COMPANY", {"companyId": "1", "properties": {}}),
        # the by-id update is locked to one contact
        (
            "hubspot",
            "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID",
            {"objectType": "companies", "objectId": "1", "properties": {"a": 1}},
        ),
        (
            "hubspot",
            "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID",
            {"objectId": "1", "properties": {"a": 1}},
        ),
        (
            "hubspot",
            "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID",
            {"objectType": "contacts", "objectId": "1", "properties": {}},
        ),
        (
            "hubspot",
            "HUBSPOT_PARTIALLY_UPDATE_CRM_OBJECT_BY_ID",
            {"objectType": "contacts", "objectId": "1", "properties": {"a": 1}, "idProperty": "x"},
        ),
        ("hubspot", "HUBSPOT_UPDATE_COMPANY", {"properties": {"name": "x"}}),
        ("salesforce", "SALESFORCE_CREATE_CONTACT", {"first_name": "Ana"}),
        # a list is named, of companies or contacts, and holds nothing the card cannot show
        ("hubspot", "HUBSPOT_CREATE_LIST", {"object_type_id": "0-2", "processing_type": "MANUAL"}),
        (
            "hubspot",
            "HUBSPOT_CREATE_LIST",
            {"name": "Q4", "object_type_id": "0-3", "processing_type": "MANUAL"},
        ),
        (
            "hubspot",
            "HUBSPOT_CREATE_LIST",
            {"name": "Q4", "object_type_id": "0-2", "processing_type": "MANUAL", "filters": {}},
        ),
        ("salesforce", "SALESFORCE_CREATE_CAMPAIGN", {"name": " "}),
        ("salesforce", "SALESFORCE_CREATE_CAMPAIGN", {"name": "Q4", "budgeted_cost": 9}),
        # R-12.9: Clue's campaigns are active and "In Progress", nothing else
        ("salesforce", "SALESFORCE_CREATE_CAMPAIGN", {"name": "Q4", "is_active": False}),
        ("salesforce", "SALESFORCE_CREATE_CAMPAIGN", {"name": "Q4", "status": "Planned"}),
        (
            "hubspot",
            "HUBSPOT_CREATE_CONTACT",
            {
                "email": "a@b.example.com",
                "associations": [
                    {
                        "to": {"id": "5"},
                        "types": [{"associationCategory": "USER_DEFINED", "associationTypeId": 9}],
                    }
                ],
            },
        ),
    ],
)
def test_unparsable_arguments_are_refused(
    provider: str, slug: str, arguments: Mapping[str, Any]
) -> None:
    spec = write_spec(provider, slug)  # type: ignore[arg-type]
    assert spec is not None
    with pytest.raises(WriteNotParsable):
        spec.parse(arguments)


def test_hubspot_batches_join_records_and_split_by_id() -> None:
    spec = write_spec("hubspot", "HUBSPOT_UPDATE_COMPANY")
    assert spec is not None and spec.batch is not None
    batch = spec.batch
    items = [
        {"companyId": "1", "properties": {"industry": "A"}},
        {"companyId": "2", "properties": {"industry": "B"}},
    ]
    assert batch.slug == "HUBSPOT_UPDATE_COMPANIES" and batch.max_size == 100
    assert batch.build(items) == {
        "inputs": [
            {"id": "1", "properties": {"industry": "A"}},
            {"id": "2", "properties": {"industry": "B"}},
        ]
    }
    outcomes = batch.split(
        {"status": "COMPLETE", "results": [{"id": "2", "properties": {}}]}, items
    )
    assert [(o.ok, o.crm_id) for o in outcomes] == [(False, "1"), (True, "2")]


def test_salesforce_batch_names_each_record_once() -> None:
    """Live (Phase 4): Salesforce refuses a composite call naming one Id twice. Changes of one
    record -- its 15- and 18-character ids alike -- are one entry, and share its result."""
    spec = write_spec("salesforce", "SALESFORCE_UPDATE_ACCOUNT")
    assert spec is not None and spec.batch is not None
    batch = spec.batch
    items = [
        {"account_id": "001jV00000HsWdp", "custom_fields": {"Clue_Id__c": "c-1"}},
        {"account_id": "001B", "industry": "Banking"},
        {"account_id": "001jV00000HsWdpQAF", "custom_fields": {"Clue_Tier__c": "Tier 1"}},
    ]
    assert batch.record_key("001jV00000HsWdpQAF") == batch.record_key("001jV00000HsWdp")
    assert batch.build(items)["records"] == [
        {
            "attributes": {"type": "Account"},
            "Id": "001jV00000HsWdp",
            "Clue_Id__c": "c-1",
            "Clue_Tier__c": "Tier 1",
        },
        {"attributes": {"type": "Account"}, "Id": "001B", "Industry": "Banking"},
    ]
    refused = {"statusCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION", "message": "no"}
    data = {
        "results": [
            {"id": "001jV00000HsWdpQAF", "success": False, "errors": [refused]},
            {"id": "001B", "success": True, "errors": []},
        ]
    }
    assert [o.ok for o in batch.split(data, items)] == [False, True, False]
    # Two values of one field of one record never share a call (the executor splits them).
    with pytest.raises(ValueError):
        batch.build([items[1], {"account_id": "001B", "industry": "Retail"}])


def test_hubspot_batch_names_each_company_once() -> None:
    spec = write_spec("hubspot", "HUBSPOT_UPDATE_COMPANY")
    assert spec is not None and spec.batch is not None
    items = [
        {"companyId": "1", "properties": {"industry": "A"}},
        {"companyId": "1", "properties": {"name": "Acme"}},
    ]
    assert spec.batch.build(items) == {
        "inputs": [{"id": "1", "properties": {"industry": "A", "name": "Acme"}}]
    }
    answer = {"status": "COMPLETE", "results": [{"id": "1", "properties": {}}]}
    assert [o.ok for o in spec.batch.split(answer, items)] == [True, True]


def test_salesforce_batch_can_clear_and_keeps_per_record_failures() -> None:
    spec = write_spec("salesforce", "SALESFORCE_UPDATE_CONTACT")
    assert spec is not None and spec.batch is not None
    batch = spec.batch
    items = [{"contact_id": "003A", "title": None}, {"contact_id": "003B", "title": "CEO"}]
    assert batch.slug == "SALESFORCE_PATCH_COMPOSITE_SOBJECTS" and batch.max_size == 200
    built = batch.build(items)
    assert built["sobject_name"] == "Contact" and built["external_id_field_name"] == "Id"
    assert built["all_or_none"] is False
    assert built["records"] == [
        {"attributes": {"type": "Contact"}, "Id": "003A", "Title": None},
        {"attributes": {"type": "Contact"}, "Id": "003B", "Title": "CEO"},
    ]
    data = {
        "results": [
            {"id": "003A", "success": True, "created": False, "errors": []},
            {
                "id": "003B",
                "success": False,
                "errors": [{"statusCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION", "message": "no"}],
            },
        ]
    }
    outcomes = batch.split(data, items)
    assert [(o.ok, o.crm_id) for o in outcomes] == [(True, "003A"), (False, "003B")]
    assert (
        outcomes[1].error is not None and "FIELD_CUSTOM_VALIDATION_EXCEPTION" in outcomes[1].error
    )


def test_hubspot_list_batch_groups_by_list_and_operation() -> None:
    spec = write_spec("hubspot", "HUBSPOT_UPDATE_LIST_MEMBERSHIPS")
    assert spec is not None and spec.batch is not None
    batch = spec.batch
    a = {"list_id": "9", "operation": "add", "record_ids": ["1"]}
    b = {"list_id": "9", "operation": "add", "record_ids": ["2"]}
    c = {"list_id": "9", "operation": "remove", "record_ids": ["3"]}
    assert batch.group(a) == batch.group(b) != batch.group(c)
    assert batch.build([a, b]) == {"list_id": "9", "operation": "add", "record_ids": ["1", "2"]}
    outcomes = batch.split({"recordsIdsAdded": ["1"], "recordIdsMissing": ["2"]}, [a, b])
    assert [(o.ok, o.crm_id) for o in outcomes] == [(True, "1"), (False, "2")]


def test_a_campaign_create_may_name_the_active_status_clue_sets() -> None:
    spec = write_spec("salesforce", "SALESFORCE_CREATE_CAMPAIGN")
    assert spec is not None
    parsed = spec.parse({"name": "Clue: Q4", "is_active": True, "status": "In Progress"})
    assert parsed.label == "Clue: Q4" and parsed.change_kind(spec) == "list_create"
