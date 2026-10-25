"""Clue's own CRM fields: the fixed set per provider (CRM Phase 4, Task 1; R-13.2, R-13.7).

The set is Clue's contract with the customer's CRM (R-13.4): the setup run builds exactly these,
and the writes read them. These checks pin the names, types and options the later tasks rely on.
"""

from __future__ import annotations

from clue_api.crm.clue_fields import (
    CLUE_FIELDS,
    HUBSPOT_DUPLICATE_LABEL,
    HUBSPOT_GROUP,
    SALESFORCE_PERMISSION_SET,
    clue_field,
)


def _names(provider: str) -> set[tuple[str, str]]:
    return {(f.object, f.crm_name) for f in CLUE_FIELDS[provider]}  # type: ignore[index]


def test_hubspot_fields() -> None:
    assert _names("hubspot") == {
        ("company", "clue_tier"),
        ("company", "clue_research_link"),
        ("company", "clue_id"),
        ("contact", "clue_committee_role"),
        ("contact", "clue_contact_link"),
        ("contact", "clue_id"),
    }
    assert HUBSPOT_GROUP.name == "clue"
    assert HUBSPOT_GROUP.label == "Clue"
    for field in CLUE_FIELDS["hubspot"]:
        assert field.group == "clue"
        assert field.crm_object == {"company": "companies", "contact": "contacts"}[field.object]

    tier = clue_field("hubspot", "company", "clue_tier")
    assert (tier.type, tier.field_type) == ("enumeration", "select")
    assert [(o.value, o.label) for o in tier.options] == [
        ("tier_1", "Tier 1"),
        ("tier_2", "Tier 2"),
        ("tier_3", "Tier 3"),
    ]
    role = clue_field("hubspot", "contact", "clue_committee_role")
    assert [(o.value, o.label) for o in role.options] == [
        ("CHAMPION", "Champion"),
        ("BUDGET_HOLDER", "Budget holder"),
        ("INFLUENCER", "Influencer"),
        ("BLOCKER", "Blocker"),
        ("END_USER", "End user"),
    ]
    link = clue_field("hubspot", "company", "clue_research_link")
    assert (link.type, link.field_type, link.options) == ("string", "text", ())
    for obj in ("company", "contact"):
        clue_id = clue_field("hubspot", obj, "clue_id")
        assert clue_id.unique  # R-13.7: hasUniqueValue
        assert (clue_id.type, clue_id.field_type) == ("string", "text")

    assert HUBSPOT_DUPLICATE_LABEL.name == "clue_possible_duplicate"
    assert HUBSPOT_DUPLICATE_LABEL.label == "Possible duplicate"
    assert (HUBSPOT_DUPLICATE_LABEL.from_object, HUBSPOT_DUPLICATE_LABEL.to_object) == (
        "contacts",
        "contacts",
    )


def test_salesforce_fields() -> None:
    assert _names("salesforce") == {
        ("company", "Clue_Tier__c"),
        ("company", "Clue_Research_Link__c"),
        ("company", "Clue_Id__c"),
        ("contact", "Clue_Committee_Role__c"),
        ("contact", "Clue_Contact_Link__c"),
        ("contact", "Clue_Id__c"),
        ("contact", "Clue_Possible_Duplicate__c"),
    }
    for field in CLUE_FIELDS["salesforce"]:
        assert field.crm_object == {"company": "Account", "contact": "Contact"}[field.object]
        assert field.group is None

    tier = clue_field("salesforce", "company", "Clue_Tier__c")
    assert tier.type == "Picklist"
    assert [(o.value, o.label) for o in tier.options] == [
        ("Tier 1", "Tier 1"),
        ("Tier 2", "Tier 2"),
        ("Tier 3", "Tier 3"),
    ]
    role = clue_field("salesforce", "contact", "Clue_Committee_Role__c")
    assert [o.value for o in role.options] == [
        "Champion",
        "Budget holder",
        "Influencer",
        "Blocker",
        "End user",
    ]
    assert clue_field("salesforce", "contact", "Clue_Contact_Link__c").type == "Url"
    for obj in ("company", "contact"):
        clue_id = clue_field("salesforce", obj, "Clue_Id__c")
        assert (clue_id.type, clue_id.length) == ("Text", 64)
        assert clue_id.external_id and clue_id.unique
    duplicate = clue_field("salesforce", "contact", "Clue_Possible_Duplicate__c")
    assert duplicate.type == "Lookup"
    assert duplicate.reference_to == "Contact"
    assert duplicate.relationship_name

    assert SALESFORCE_PERMISSION_SET.name == "Clue_Fields"
    assert SALESFORCE_PERMISSION_SET.label == "Clue fields"


def test_every_field_is_labelled_and_keyed_once() -> None:
    for provider, fields in CLUE_FIELDS.items():
        keys = [(f.object, f.key) for f in fields]
        assert len(keys) == len(set(keys)), provider
        for field in fields:
            assert field.label.startswith("Clue ")
            assert field.key.startswith("clue_")
    # The same Clue meaning has the same key on both providers.
    assert {(f.object, f.key) for f in CLUE_FIELDS["hubspot"]} < {
        (f.object, f.key) for f in CLUE_FIELDS["salesforce"]
    }


def test_qualified_names_tell_the_two_clue_ids_apart() -> None:
    assert clue_field("salesforce", "company", "Clue_Id__c").qualified_name == "Account.Clue_Id__c"
    assert clue_field("salesforce", "contact", "Clue_Id__c").qualified_name == "Contact.Clue_Id__c"
    assert clue_field("hubspot", "company", "clue_id").qualified_name == "companies.clue_id"
    assert clue_field("hubspot", "contact", "clue_id").qualified_name == "contacts.clue_id"
    for fields in CLUE_FIELDS.values():
        names = [f.qualified_name for f in fields]
        assert len(names) == len(set(names))
