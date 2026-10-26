"""CRM Phase 3 spike: verify list, campaign and field shapes on the two TEST CRMs (run by hand).

Plan: docs/superpowers/plans/2026-10-23-crm-integration-phase-3-first-writes.md, Task 1.
Findings: docs/superpowers/specs/crm-integration/composio-api-notes.md, "Phase 3 shapes".

    set -a; source .env; set +a
    uv run python scripts/crm_phase3_spike.py [hubspot|salesforce]   # default: both

Uses the dev stack's active connections (read-only SQL on ``workspace_integration_connection``):
Conduit AI (HubSpot) and Garner Health (Salesforce). Safe to re-run: the "Clue: spike" list and
campaign are looked up before they are created, and the one company / one contact used is removed
again at the end. Nothing is deleted except that membership (Clue never deletes CRM records).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import asyncpg

from clue_api.crm.composio_gateway import HttpComposioGateway, composio_user_id

HUBSPOT_WS = "ws_3c96440b557a413fa02bda3fbf90cc5e"  # Conduit AI
SALESFORCE_WS = "ws_c080123a7c434454898aa5ae1a8f698b"  # Garner Health
SPIKE_NAME = "Clue: spike"
COMPANY_TYPE = "0-2"
PROPERTIES = ("hs_ideal_customer_profile", "hs_is_target_account", "hs_buying_role")


def show(label: str, value: Any, limit: int = 1500) -> None:
    text = json.dumps(value, indent=1, default=str)
    print(f"\n--- {label}\n{text[:limit]}{' …' if len(text) > limit else ''}")


class Crm:
    """One connection: the gateway plus the connected account, user id and pinned version."""

    def __init__(self, gateway: HttpComposioGateway, workspace_id: str, account: str, version: str):
        self.gateway, self.workspace_id, self.account, self.version = (
            gateway,
            workspace_id,
            account,
            version,
        )

    async def run(self, slug: str, **arguments: Any) -> Any:
        result = await self.gateway.execute(
            slug=slug,
            arguments=arguments,
            connected_account_id=self.account,
            user_id=composio_user_id(self.workspace_id),
            version=self.version,
        )
        show(f"{slug} {json.dumps(arguments)[:200]} successful={result.successful}", result.data)
        if result.error:
            show(f"{slug} error", result.error, limit=2500)
        return result


async def connected_account(workspace_id: str) -> str:
    dsn = os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval(
            "SELECT composio_connected_account_id FROM workspace_integration_connection "
            "WHERE workspace_id = $1 AND status = 'active'",
            workspace_id,
        )
    finally:
        await conn.close()


async def hubspot_properties(hs: Crm) -> None:
    """Step 1: the option lists of the three ABM properties (companies and contacts)."""
    for object_type in ("companies", "contacts"):
        result = await hs.gateway.execute(
            slug="HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE",
            arguments={"objectType": object_type},
            connected_account_id=hs.account,
            user_id=composio_user_id(hs.workspace_id),
            version=hs.version,
        )
        data = result.data or {}
        rows = data.get("results") or (data.get("data") or {}).get("results") or []
        print(f"\n=== {object_type}: {len(rows)} properties, top-level keys {list(data)[:6]}")
        for prop in rows:
            if prop.get("name") in PROPERTIES:
                show(
                    f"{object_type}.{prop['name']}",
                    {
                        key: prop.get(key)
                        for key in (
                            "label",
                            "type",
                            "fieldType",
                            "groupName",
                            "hidden",
                            "modificationMetadata",
                        )
                    }
                    | {
                        "options": [
                            (o.get("value"), o.get("label"), o.get("hidden"))
                            for o in prop.get("options") or []
                        ]
                    },
                    limit=4000,
                )


async def hubspot_lists(hs: Crm) -> None:
    """Step 2: a manual company list, add / read back / remove one company, a missing list id."""
    await hs.run("HUBSPOT_SEARCH_CRM_LISTS", objectTypeId=COMPANY_TYPE, count=20, offset=0)
    found = await hs.run(
        "HUBSPOT_GET_CRM_LIST_BY_NAME", object_type_id=COMPANY_TYPE, list_name=SPIKE_NAME
    )
    if not found.successful:
        await hs.run(
            "HUBSPOT_CREATE_LIST",
            name=SPIKE_NAME,
            object_type_id=COMPANY_TYPE,
            processing_type="MANUAL",
        )
        found = await hs.run(
            "HUBSPOT_GET_CRM_LIST_BY_NAME", object_type_id=COMPANY_TYPE, list_name=SPIKE_NAME
        )
    data = found.data or {}
    spike_list = data.get("list") or (data.get("data") or {}).get("list") or data
    list_id = str(spike_list["listId"])
    print(f"\n=== list id {list_id}, processingType {spike_list.get('processingType')}")

    companies = await hs.run("HUBSPOT_SEARCH_COMPANIES", query="Aldercare", limit=1)
    results = (companies.data or {}).get("results") or (
        (companies.data or {}).get("data") or {}
    ).get("results")
    company_id = str(results[0]["id"])

    await hs.run(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS", list_id=list_id, operation="add", record_ids=[company_id]
    )
    await hs.run(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS", list_id=list_id, operation="add", record_ids=[company_id]
    )  # adding again: what does an existing member answer?
    await hs.run(
        "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS", object_type_id=COMPANY_TYPE, record_id=company_id
    )
    await hs.run(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        list_id=list_id,
        operation="remove",
        record_ids=[company_id],
    )
    await hs.run(
        "HUBSPOT_GET_RECORD_LIST_MEMBERSHIPS", object_type_id=COMPANY_TYPE, record_id=company_id
    )
    await hs.run(
        "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        list_id="999999999",
        operation="add",
        record_ids=[company_id],
    )


def soql_records(result: Any) -> list[dict[str, Any]]:
    data = result.data or {}
    return data.get("records") or (data.get("data") or {}).get("records") or []


async def salesforce_campaign(sf: Crm) -> None:
    """Step 3: a campaign, its member statuses, add / read back / remove one contact."""
    lookup = f"SELECT Id, Name, IsActive, Status FROM Campaign WHERE Name = '{SPIKE_NAME}'"
    campaigns = soql_records(await sf.run("SALESFORCE_RUN_SOQL_QUERY", query=lookup))
    if not campaigns:
        await sf.run("SALESFORCE_CREATE_CAMPAIGN", name=SPIKE_NAME)
        campaigns = soql_records(await sf.run("SALESFORCE_RUN_SOQL_QUERY", query=lookup))
    if not campaigns:
        # Seen 2026-10-23: CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY because the connected user is not
        # a Marketing User (User.UserPermissionsMarketingUser = false). Shown here, then stop.
        await sf.run(
            "SALESFORCE_RUN_SOQL_QUERY",
            query="SELECT Id, UserPermissionsMarketingUser, Profile.Name FROM User "
            f"WHERE Id = '{(await sf.run('SALESFORCE_WHO_AM_I')).data['data']['user_id']}'",
        )
        print("\n=== no campaign: stopping the Salesforce step")
        return
    campaign_id = campaigns[0]["Id"]

    await sf.run(
        "SALESFORCE_RUN_SOQL_QUERY",
        query="SELECT Label, IsDefault, HasResponded, SortOrder FROM CampaignMemberStatus "
        f"WHERE CampaignId = '{campaign_id}' ORDER BY SortOrder",
    )
    contact = soql_records(
        await sf.run(
            "SALESFORCE_RUN_SOQL_QUERY",
            query="SELECT Id, Name FROM Contact WHERE Account.Name LIKE 'Aldercare%' LIMIT 1",
        )
    )[0]
    members = f"SELECT Id, ContactId, Status FROM CampaignMember WHERE CampaignId = '{campaign_id}'"

    await sf.run(
        "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN", campaign_id=campaign_id, contact_id=contact["Id"]
    )
    await sf.run("SALESFORCE_RUN_SOQL_QUERY", query=members)
    await sf.run(
        "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN", campaign_id=campaign_id, contact_id=contact["Id"]
    )  # adding again: the "already a member" answer
    await sf.run(
        "SALESFORCE_REMOVE_FROM_CAMPAIGN", campaign_id=campaign_id, member_id=contact["Id"]
    )
    await sf.run("SALESFORCE_RUN_SOQL_QUERY", query=members)


async def main() -> None:
    gateway = HttpComposioGateway(
        api_key=os.environ["CLUE_COMPOSIO_API_KEY"], base_url=os.environ["CLUE_COMPOSIO_BASE_URL"]
    )
    hs = Crm(
        gateway,
        HUBSPOT_WS,
        await connected_account(HUBSPOT_WS),
        os.environ["CLUE_COMPOSIO_HUBSPOT_TOOLKIT_VERSION"],
    )
    sf = Crm(
        gateway,
        SALESFORCE_WS,
        await connected_account(SALESFORCE_WS),
        os.environ["CLUE_COMPOSIO_SALESFORCE_TOOLKIT_VERSION"],
    )
    which = sys.argv[1:] or ["hubspot", "salesforce"]
    if "hubspot" in which:
        await hubspot_properties(hs)
        await hubspot_lists(hs)
    if "salesforce" in which:
        await salesforce_campaign(sf)


if __name__ == "__main__":
    asyncio.run(main())
