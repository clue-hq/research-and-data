"""Add a workspace to an existing login (spec 2026-10-25 §3.1).

``clue_auth.provision_additional_workspace`` does the work — the workspace, its one brand and an
owner membership, refusing a bad website, an email with no (or several) users, an inactive user
and a duplicate name. A dry run makes the same writes inside a savepoint and rolls it back, so it
reports exactly what an apply would create. Applying also writes the audit row.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.workspace_ops.audit import record_operation
from clue_api.workspace_ops.operators import Operator, OpsRefused
from clue_auth import provision_additional_workspace
from clue_auth.errors import IdentityConflictError, ProvisioningValidationError


def operator_setup_url(app_origin: str, workspace_id: str, website: str) -> str:
    """The link that, opened by the signed-in owner, selects the workspace and starts setup."""
    query = urlencode({"workspace": workspace_id, "website": website})
    return f"{app_origin.rstrip('/')}/onboarding/setting-up?{query}"


async def add_workspace(
    conn: AsyncConnection,
    *,
    email: str,
    website: str,
    company_name: str | None,
    operator: Operator,
    app_origin: str,
    pages_system_suffix: str,
    apply: bool,
) -> dict[str, Any]:
    savepoint = await conn.begin_nested()
    try:
        result = await provision_additional_workspace(
            conn,
            email=email,
            company_website=website,
            company_name=company_name,
            pages_system_suffix=pages_system_suffix,
        )
    except IdentityConflictError as error:
        await savepoint.rollback()
        code = (
            "workspace_exists" if "already owns a workspace" in str(error) else "identity_conflict"
        )
        raise OpsRefused(409 if code == "workspace_exists" else 422, code, str(error)) from error
    except ProvisioningValidationError as error:
        await savepoint.rollback()
        raise OpsRefused(422, error.code, str(error)) from error
    workspace_id = result.workspace.workspace_id
    created = {
        "user_id": result.user.user_id,
        "email": email.strip().casefold(),
        "workspace_id": workspace_id,
        "workspace_name": result.workspace.name,
        "brand_id": result.brand.brand_id,
        "membership_id": result.membership.membership_id,
        "onboarding_link": operator_setup_url(app_origin, workspace_id, result.company_website),
        "applied": apply,
    }
    if not apply:
        await savepoint.rollback()
        return created
    await savepoint.commit()
    await record_operation(
        conn,
        operation="add_workspace",
        workspace_id=workspace_id,
        actor=operator.actor,
        reason=None,
        plan=created,
        estimated_cost_usd=Decimal(0),
        onboarding_run_id=None,
        design_job_ids=(),
    )
    return created
