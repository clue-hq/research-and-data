"""The CRM read allowlist and the result summary the model gets instead of records (Task 8)."""

from __future__ import annotations

import pytest

from clue_api.crm.read_actions import READ_ACTIONS, is_readable, summarize


@pytest.mark.parametrize(
    ("provider", "slug"),
    [
        ("hubspot", "HUBSPOT_CREATE_CONTACT"),
        ("hubspot", "HUBSPOT_SEARCH_DEALS_FROM_NL"),
        ("salesforce", "SALESFORCE_CREATE_LEAD"),
        ("salesforce", "HUBSPOT_SEARCH_DEALS"),  # another CRM's read
    ],
)
def test_from_nl_and_unlisted_slugs_are_refused(provider: str, slug: str) -> None:
    assert not is_readable(provider, slug)  # type: ignore[arg-type]


def test_the_list_reads_are_allowed_and_list_writes_are_not() -> None:
    # Phase 3: Clue finds a project's list by name (composio-api-notes.md § Phase 3 shapes).
    assert is_readable("hubspot", "HUBSPOT_GET_CRM_LIST_BY_NAME")
    assert is_readable("hubspot", "HUBSPOT_SEARCH_CRM_LISTS")
    assert not is_readable("hubspot", "HUBSPOT_CREATE_LIST")
    assert not is_readable("salesforce", "SALESFORCE_CREATE_CAMPAIGN")


def test_every_listed_action_is_readable_and_none_is_natural_language() -> None:
    for provider, slugs in READ_ACTIONS.items():
        for slug in slugs:
            assert is_readable(provider, slug)
            assert slug.startswith(provider.upper() + "_")


def test_summarize_hubspot_search_page() -> None:
    data = {
        "results": [
            {"id": "1", "properties": {"dealname": "Acme", "amount": "100"}},
            {"id": "2", "properties": {"dealname": "Beta", "closedate": "2026-09-01"}},
        ],
        "total": 36,
        "paging": {"next": {"after": "2"}},
    }
    summary = summarize("hubspot", "HUBSPOT_SEARCH_DEALS", data)
    assert summary.record_count == 2
    assert summary.total == 36
    assert summary.fields == [
        "id",
        "properties.amount",
        "properties.closedate",
        "properties.dealname",
    ]
    assert summary.next_cursor == "2"
    assert summary.done is False


def test_summarize_hubspot_last_page_is_done() -> None:
    summary = summarize("hubspot", "HUBSPOT_LIST_DEALS", {"results": [{"id": "1"}]})
    assert summary.next_cursor is None and summary.done is True


def test_summarize_salesforce_soql() -> None:
    data = {
        "totalSize": 118,
        "done": False,
        "nextRecordsUrl": "/services/data/v67.0/query/01g-2000",
        "records": [
            {"attributes": {"type": "Opportunity"}, "Id": "006", "StageName": "Closed Won"},
        ],
    }
    summary = summarize("salesforce", "SALESFORCE_RUN_SOQL_QUERY", data)
    assert summary.record_count == 1
    assert summary.total == 118
    assert summary.fields == ["Id", "StageName"]  # Salesforce's per-record metadata is skipped
    assert summary.next_cursor == "/services/data/v67.0/query/01g-2000"
    assert summary.done is False


def test_summarize_unwraps_composio_nesting_and_describes_non_lists() -> None:
    summary = summarize(
        "hubspot", "HUBSPOT_WHO_AM_I", {"data": {"portalId": 1, "account_type": "DEVELOPER_TEST"}}
    )
    assert summary.record_count is None
    assert summary.fields == ["account_type", "portalId"]
    assert summary.done is True
