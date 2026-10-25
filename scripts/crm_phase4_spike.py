"""CRM Phase 4 spike: can Clue create its own fields and duplicate labels through Composio? (by hand)

Phase 4 (Clue's own fields, option B; duplicate links, R-12.4) needs schema writes in the customer's
CRM. This checks, on the two TEST CRMs only, whether the connected apps may make them.

    set -a; source .env; set +a
    uv run python scripts/crm_phase4_spike.py [hubspot|salesforce]   # default: both

Uses the dev stack's active connections: Conduit AI (HubSpot) and Garner Health (Salesforce).
Everything it creates is named "spike" so it never collides with the real Clue fields; each step
looks before it creates, so a re-run is safe. Nothing is deleted.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import asyncpg

from clue_api.crm.composio_gateway import ComposioError, HttpComposioGateway, composio_user_id

HUBSPOT_WS = "ws_3c96440b557a413fa02bda3fbf90cc5e"  # Conduit AI
SALESFORCE_WS = "ws_c080123a7c434454898aa5ae1a8f698b"  # Garner Health

HS_GROUP = "clue_spike"
HS_PROPERTY = "clue_spike_stage"
HS_LABEL = "clue_spike_possible_duplicate"
HS_COMPANY = "355964361431"  # Atrium Hospitality (created by the Phase 3 live check)
HS_CONTACTS = ("576384067300", "574828255986")  # Rob Mangiarelli, Clue Testcontact

SF_ACCOUNT_FIELD = "Clue_Spike_Stage__c"
SF_EXTERNAL_ID = "Clue_Spike_Ext_Id__c"
SF_ACCOUNT = "001jV00000HsWdpQAF"  # Carmel Clay Schools
SF_CONTACT = "003jV00000F5nVhQAJ"  # Holly Herrera


def show(label: str, value: Any, limit: int = 1500) -> None:
    text = json.dumps(value, indent=1, default=str)
    print(f"\n--- {label}\n{text[:limit]}{' …' if len(text) > limit else ''}")


class Crm:
    def __init__(self, gateway: HttpComposioGateway, workspace_id: str, account: str, version: str):
        self.gateway, self.workspace_id, self.account, self.version = (
            gateway,
            workspace_id,
            account,
            version,
        )

    async def run(self, slug: str, **arguments: Any) -> Any:
        try:
            result = await self.gateway.execute(
                slug=slug,
                arguments=arguments,
                connected_account_id=self.account,
                user_id=composio_user_id(self.workspace_id),
                version=self.version,
            )
        except ComposioError as error:
            show(f"{slug} RAISED {error.kind} {error.status}", str(error), limit=2500)
            return None
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


async def hubspot(hs: Crm) -> None:
    """A property group and a property on companies, a value on one company, and a contact↔contact
    association label used on two contacts."""
    await hs.run(
        "HUBSPOT_CREATE_AND_RETURN_A_NEW_PROPERTY_GROUP",
        objectType="companies",
        name=HS_GROUP,
        label="Clue (spike)",
    )
    await hs.run(
        "HUBSPOT_CREATE_PROPERTY_FOR_SPECIFIED_OBJECT_TYPE",
        objectType="companies",
        name=HS_PROPERTY,
        label="Clue spike stage",
        type="enumeration",
        fieldType="select",
        groupName=HS_GROUP,
        options=[
            {"label": "Targeted", "value": "targeted", "displayOrder": 0, "hidden": False},
            {"label": "Engaged", "value": "engaged", "displayOrder": 1, "hidden": False},
        ],
    )
    await hs.run(
        "HUBSPOT_UPDATE_COMPANY",
        company_id=HS_COMPANY,
        properties={HS_PROPERTY: "engaged"},
    )
    await hs.run(
        "HUBSPOT_READ_CRM_OBJECT_BY_ID",
        objectType="companies",
        objectId=HS_COMPANY,
        properties=[HS_PROPERTY, "name"],
    )
    label = await hs.run(
        "HUBSPOT_CREATE_ASSOCIATION_LABEL",
        from_object_type="contacts",
        to_object_type="contacts",
        name=HS_LABEL,
        label="Possible duplicate (Clue spike)",
    )
    show("label answer (find associationTypeId)", label.data if label else None, limit=3000)


async def salesforce(sf: Crm) -> None:
    """A custom picklist on Account, a value on one account, and an external-id field on Contact
    used for an update-only upsert."""
    await sf.run(
        "SALESFORCE_CREATE_CUSTOM_FIELD",
        object_api_name="Account",
        field_api_name=SF_ACCOUNT_FIELD,
        field_type="Picklist",
        label="Clue spike stage",
        check_existing=True,
        picklist_values=[
            {"full_name": "Targeted", "label": "Targeted", "default": False},
            {"full_name": "Engaged", "label": "Engaged", "default": False},
        ],
    )
    await sf.run(
        "SALESFORCE_UPDATE_ACCOUNT",
        account_id=SF_ACCOUNT,
        custom_fields={SF_ACCOUNT_FIELD: "Engaged"},
    )
    await sf.run(
        "SALESFORCE_RUN_SOQL_QUERY",
        query=f"SELECT Id, Name, {SF_ACCOUNT_FIELD} FROM Account WHERE Id = '{SF_ACCOUNT}'",
    )
    await sf.run(
        "SALESFORCE_CREATE_CUSTOM_FIELD",
        object_api_name="Contact",
        field_api_name=SF_EXTERNAL_ID,
        field_type="Text",
        length=64,
        label="Clue spike external id",
        external_id=True,
        unique=True,
        check_existing=True,
    )
    await sf.run(
        "SALESFORCE_UPDATE_CONTACT",
        contact_id=SF_CONTACT,
        custom_fields={SF_EXTERNAL_ID: "clue-spike-herrera"},
    )
    await sf.run(
        "SALESFORCE_UPSERT_SOBJECT_BY_EXTERNAL_ID",
        sobject="Contact",
        field_name=SF_EXTERNAL_ID,
        field_value="clue-spike-herrera",
        fields={"Title": "Assistant Superintendent"},
        update_only=True,
    )
    await sf.run(
        "SALESFORCE_RUN_SOQL_QUERY",
        query=f"SELECT Id, Name, Title, {SF_EXTERNAL_ID} FROM Contact WHERE Id = '{SF_CONTACT}'",
    )


async def main() -> None:
    gateway = HttpComposioGateway(
        api_key=os.environ["CLUE_COMPOSIO_API_KEY"], base_url=os.environ["CLUE_COMPOSIO_BASE_URL"]
    )
    which = sys.argv[1:] or ["hubspot", "salesforce"]
    if "hubspot" in which:
        await hubspot(
            Crm(
                gateway,
                HUBSPOT_WS,
                await connected_account(HUBSPOT_WS),
                os.environ["CLUE_COMPOSIO_HUBSPOT_TOOLKIT_VERSION"],
            )
        )
    if "salesforce" in which:
        await salesforce(
            Crm(
                gateway,
                SALESFORCE_WS,
                await connected_account(SALESFORCE_WS),
                os.environ["CLUE_COMPOSIO_SALESFORCE_TOOLKIT_VERSION"],
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
