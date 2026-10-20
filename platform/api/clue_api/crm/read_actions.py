"""Which CRM actions the agent may run in Phase 1, and the summary it gets back instead of records.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§5. Reads only: an action runs only when it is on this reviewed allowlist, and Composio's
natural-language actions (``*_FROM_NL``) are never exposed, because they hand the CRM query to
another model. The full result always goes to a file in ``reads/``; the model sees only
:class:`ResultSummary` (how many records, which fields, how to fetch the next page).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from clue_api.crm.composio_gateway import CrmProvider

__all__ = ["READ_ACTIONS", "ResultSummary", "is_readable", "summarize"]

READ_ACTIONS: Mapping[CrmProvider, frozenset[str]] = {
    "hubspot": frozenset(
        {
            "HUBSPOT_SEARCH_DEALS",
            "HUBSPOT_LIST_DEALS",
            "HUBSPOT_GET_DEALS",
            "HUBSPOT_READ_CRM_OBJECT_BY_ID",
            "HUBSPOT_LIST_COMPANIES",
            "HUBSPOT_SEARCH_COMPANIES",
            "HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES",
            "HUBSPOT_LIST_CONTACTS",
            "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA",
            "HUBSPOT_READ_CONTACTS",
            "HUBSPOT_READ_ASSOCIATIONS_BATCH",
            "HUBSPOT_LIST_ASSOCIATION_TYPES",
            "HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE",
            "HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE",
            "HUBSPOT_RETRIEVE_PIPELINE_STAGES",
            "HUBSPOT_RETRIEVE_OWNERS",
            "HUBSPOT_LIST_GRANTED_SCOPES",
            "HUBSPOT_WHO_AM_I",
            "HUBSPOT_RETRIEVE_LINE_ITEMS",
            "HUBSPOT_LIST_PRODUCTS",
            "HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE",
            "HUBSPOT_SEARCH_CRM_OBJECTS_BY_CRITERIA",
        }
    ),
    "salesforce": frozenset(
        {
            "SALESFORCE_RUN_SOQL_QUERY",
            "SALESFORCE_QUERY_MORE",
            "SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT",
            "SALESFORCE_GET_PICKLIST_VALUES_BY_RECORD_TYPE",
            "SALESFORCE_GET_S_OBJECT_RECORD",
            "SALESFORCE_LIST_ACCOUNTS",
            "SALESFORCE_LIST_CONTACTS",
            "SALESFORCE_LIST_OPPORTUNITIES",
            "SALESFORCE_GET_REPORT",
            "SALESFORCE_GET_ORG_LIMITS",
        }
    ),
}

#: How many records are looked at to list the fields a result carries.
_FIELD_SAMPLE = 50
#: The most field names a summary lists; a property dump can name hundreds.
_MAX_FIELDS = 200


@dataclass(frozen=True)
class ResultSummary:
    #: Records in this page, or ``None`` when the result is not a list of records.
    record_count: int | None
    #: The total the CRM reports across all pages, when it reports one.
    total: int | None
    fields: list[str]
    #: Pass this back to fetch the next page (HubSpot ``after``; Salesforce ``nextRecordsUrl``).
    next_cursor: str | None
    done: bool


def is_readable(provider: CrmProvider, slug: str) -> bool:
    """On the read allowlist for this CRM, and never a natural-language action."""
    return slug in READ_ACTIONS[provider] and not slug.endswith("_FROM_NL")


def summarize(provider: CrmProvider, slug: str, data: Any) -> ResultSummary:
    """Describe a result without quoting any record from it."""
    del slug  # the shapes are the CRM's, not the action's
    body = _unwrap(data)
    if isinstance(body, list):
        return ResultSummary(len(body), None, _fields(body), None, True)
    if not isinstance(body, dict):
        return ResultSummary(None, None, [], None, True)
    if provider == "salesforce" and isinstance(body.get("records"), list):
        records = body["records"]
        cursor = body.get("nextRecordsUrl")
        done = bool(body.get("done", cursor is None))
        return ResultSummary(
            len(records), _int(body.get("totalSize")), _fields(records), _str(cursor), done
        )
    if isinstance(body.get("results"), list):
        records = body["results"]
        paging = body.get("paging")
        after = paging.get("next", {}).get("after") if isinstance(paging, dict) else None
        cursor = _str(after)
        return ResultSummary(
            len(records), _int(body.get("total")), _fields(records), cursor, cursor is None
        )
    return ResultSummary(None, None, sorted(body)[:_MAX_FIELDS], None, True)


def _unwrap(data: Any) -> Any:
    """Composio sometimes nests the CRM's body one level down, under ``data``."""
    for _ in range(2):
        if (
            isinstance(data, dict)
            and "data" in data
            and not ({"results", "records"} & data.keys())
            and isinstance(data["data"], dict | list)
        ):
            data = data["data"]
    return data


def _fields(records: list[Any]) -> list[str]:
    names: set[str] = set()
    for record in records[:_FIELD_SAMPLE]:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if key == "attributes":  # Salesforce's per-record type/url metadata
                continue
            if key == "properties" and isinstance(value, dict):  # HubSpot's record values
                names.update(f"properties.{name}" for name in value)
            else:
                names.add(key)
    return sorted(names)[:_MAX_FIELDS]


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
