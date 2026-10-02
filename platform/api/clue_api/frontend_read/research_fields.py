"""Research field management over the shared, workspace-scoped claim registry."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.settings_authority import lock_manager, principal_for, refused
from clue_db import ConnFactory
from clue_research.claimstore import (
    ResearchFieldInputError,
    ResearchFieldKeyTaken,
    ResolvedFieldDefinition,
    WorkspaceDynamicClientKbErasedError,
    WorkspaceFieldDefinitionError,
    WorkspaceFieldRetiredError,
    get_field,
    get_workspace_field,
    list_research_fields,
    register_workspace_research_field,
    retire_workspace_field,
    update_workspace_research_field,
)
from clue_research.claimstore.registry import FieldRegistryOrigin, research_field_key

Entity = Literal["accounts", "contacts"]
_LABELS = {
    "core.account_name": "Company name",
    "core.industry": "Industry",
    "core.employee_count": "Headcount",
    "core.employee_range": "Headcount",
    "core.annual_revenue": "Revenue",
    "core.revenue_band": "Revenue",
    "core.hq_location": "Locations",
    "core.primary_domain": "Website",
    "account.scoring.fit": "Fit score",
}


class ResearchFieldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity: Entity
    label: str = Field(max_length=200)
    description: str = Field(min_length=1, max_length=2000)


class ResearchFieldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="", min_length=1, max_length=200)
    description: str = Field(default="", min_length=1, max_length=2000)


async def field_rows(
    conn: AsyncConnection, definitions: tuple[ResolvedFieldDefinition, ...]
) -> list[dict[str, Any]]:
    ids = sorted({d.promoted_by.removeprefix("human:") for d in definitions if d.promoted_by})
    names = {}
    if ids:
        people = (
            (
                await conn.execute(
                    text(
                        "SELECT user_id, display_name, first_name, last_name FROM platform_user "
                        "WHERE user_id = ANY(:ids) AND status = 'active'"
                    ),
                    {"ids": ids},
                )
            )
            .mappings()
            .all()
        )
        names = {
            p["user_id"]: p["display_name"]
            or " ".join(part for part in (p["first_name"], p["last_name"]) if part)
            or None
            for p in people
        }
    rows = []
    for definition in definitions:
        key = definition.field_def.field_key
        local = definition.origin is FieldRegistryOrigin.WORKSPACE
        rows.append(
            {
                "key": key,
                "label": (definition.label or key.rsplit(".", 1)[-1].replace("_", " ").capitalize())
                if local
                else _LABELS.get(key, key.rsplit(".", 1)[-1].replace("_", " ").capitalize()),
                "description": definition.description or "",
                "origin": "workspace" if local else "platform",
                "created_by": names.get((definition.promoted_by or "").removeprefix("human:"))
                if local
                else None,
                "created_at": definition.created_at.isoformat()
                if local and definition.created_at
                else None,
            }
        )
    return rows


def field_error(error: ValueError) -> HTTPException:
    if isinstance(error, ResearchFieldKeyTaken):
        return refused(409, "KEY_TAKEN", str(error))
    if isinstance(error, WorkspaceDynamicClientKbErasedError):
        return refused(409, "WORKSPACE_FIELDS_ERASED", "Workspace research fields were erased.")
    if isinstance(error, WorkspaceFieldRetiredError):
        return refused(404, "FIELD_NOT_FOUND", "Research field is missing or retired.")
    return refused(400, "FIELD_INVALID", str(error))


async def require_local_field(conn: AsyncConnection, workspace_id: str, key: str) -> None:
    if await get_field(conn, key) is not None:
        raise refused(409, "PLATFORM_FIELD", "Clue fields cannot be changed.")
    row = await get_workspace_field(conn, workspace_id=workspace_id, field_key=key)
    if row is None or row.client_kb_role != "research":
        raise refused(404, "FIELD_NOT_FOUND", "Research field is missing or retired.")


def register_research_field_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get("/settings/research-fields")
    async def read_fields(
        request: Request, workspace_id: WorkspaceDep, entity: Entity
    ) -> dict[str, Any]:
        principal_for(request, workspace_id)
        async with conn_factory() as conn:
            definitions = await list_research_fields(conn, workspace_id=workspace_id, entity=entity)
            ordered = tuple(
                sorted(
                    definitions,
                    key=lambda d: (
                        d.origin is FieldRegistryOrigin.WORKSPACE,
                        d.created_at
                        if d.origin is FieldRegistryOrigin.WORKSPACE and d.created_at
                        else datetime.min.replace(tzinfo=UTC),
                        d.field_def.field_key,
                    ),
                )
            )
            return {"entity": entity, "rows": await field_rows(conn, ordered)}

    @router.post("/settings/research-fields", status_code=201)
    async def create_field(
        body: ResearchFieldCreate, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_settings")
        try:
            research_field_key(body.entity, body.label)
        except ResearchFieldInputError as error:
            raise refused(400, "LABEL_INVALID", str(error)) from error
        try:
            async with conn_factory() as conn:
                await lock_manager(conn, principal, "workspace.manage_settings")
                row = await register_workspace_research_field(
                    conn,
                    workspace_id=workspace_id,
                    entity=body.entity,
                    label=body.label,
                    description=body.description,
                    created_by=f"human:{principal.user_id}",
                )
                return (await field_rows(conn, (row,)))[0]
        except (WorkspaceFieldDefinitionError, WorkspaceDynamicClientKbErasedError) as error:
            raise field_error(error) from error

    @router.patch("/settings/research-fields/{key}")
    async def patch_field(
        key: str, body: ResearchFieldPatch, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_settings")
        try:
            async with conn_factory() as conn:
                await lock_manager(conn, principal, "workspace.manage_settings")
                await require_local_field(conn, workspace_id, key)
                row = await update_workspace_research_field(
                    conn,
                    workspace_id=workspace_id,
                    field_key=key,
                    label=body.label if "label" in body.model_fields_set else None,
                    description=body.description
                    if "description" in body.model_fields_set
                    else None,
                )
                return (await field_rows(conn, (row,)))[0]
        except (
            WorkspaceFieldDefinitionError,
            WorkspaceFieldRetiredError,
            WorkspaceDynamicClientKbErasedError,
        ) as error:
            raise field_error(error) from error

    @router.delete("/settings/research-fields/{key}")
    async def retire_field(
        key: str, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, bool]:
        principal = principal_for(request, workspace_id, permission="workspace.manage_settings")
        try:
            async with conn_factory() as conn:
                await lock_manager(conn, principal, "workspace.manage_settings")
                await require_local_field(conn, workspace_id, key)
                await retire_workspace_field(
                    conn,
                    workspace_id=workspace_id,
                    field_key=key,
                    retired_by=f"human:{principal.user_id}",
                    reason="settings",
                )
                return {"ok": True}
        except (WorkspaceFieldRetiredError, WorkspaceDynamicClientKbErasedError) as error:
            raise field_error(error) from error
