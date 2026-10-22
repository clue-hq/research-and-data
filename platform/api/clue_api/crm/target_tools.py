"""``read_crm_targets@1``: a project's accounts and buying committee, already reduced to what Clue
may write into the connected CRM (CRM integration Phase 3, Task 4). The reduction itself lives in
:mod:`clue_api.crm.targets`; this is the agent's read over it. It reads only Clue's database: the
CRM is never called.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import ClassVar

from pydantic import Field

from clue_agents.manual import tool_manual_link
from clue_api.crm.composio_gateway import CrmProvider
from clue_api.crm.connections import latest_connection
from clue_api.crm.targets import (
    MAX_TARGET_CONTACTS,
    TargetAccount,
    TargetContact,
    project_targets,
)
from clue_api.crm.tools import _refuse
from clue_config import Settings
from clue_db import ConnFactory, transaction
from clue_spine import get_project_for_workspace
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = ["ReadCrmTargetsInput", "ReadCrmTargetsOutput", "ReadCrmTargetsTool"]

MAX_TARGET_ACCOUNTS = 200


class ReadCrmTargetsInput(ToolInput):
    project_id: str
    #: Only these accounts of the project.
    account_ids: list[str] | None = Field(default=None, max_length=MAX_TARGET_ACCOUNTS)
    include_contacts: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_TARGET_ACCOUNTS)
    #: The most contacts returned for the page's accounts.
    contacts_limit: int = Field(default=MAX_TARGET_CONTACTS, ge=1, le=MAX_TARGET_CONTACTS)


class ReadCrmTargetsOutput(ToolOutput):
    accounts: list[TargetAccount]
    contacts: list[TargetContact]
    #: The project's accounts (narrowed by ``account_ids``); ``accounts`` is one page of them.
    total_accounts: int
    #: The committee contacts of this page's accounts; ``contacts`` is at most contacts_limit.
    total_contacts: int
    #: Says, in words, when contacts were cut to the limit.
    contacts_note: str | None
    #: The CRM the workspace has connected ("hubspot" or "salesforce"), or ``None``.
    connected_crm: CrmProvider | None


class ReadCrmTargetsTool(Tool):
    name = "read_crm_targets"
    version = "1"
    model_description = (
        "Read a project's accounts and their buying-committee contacts as Clue may write them "
        "into the connected CRM: each account's name, domain, fit band, HubSpot ICP tier and the "
        "CRM record it already is; each contact's first and last name, job title, buying role "
        "(HubSpot only), verified work email and LinkedIn URL, and the CRM record it already "
        "is. Every value carries the claim ids it came from: pass one as a change's source_ref "
        "when you propose it with propose_crm_changes. A field Clue holds but may not write is "
        "listed in the contact's 'withheld' with the reason; never write it some other way. "
        "Page with offset and limit when total_accounts is larger than the page; when "
        "contacts_note says contacts were cut, read fewer accounts at a time. Reads only "
        "Clue's records; the CRM is not called. " + tool_manual_link("read_crm_targets")
    )
    input_model: ClassVar[type[ToolInput]] = ReadCrmTargetsInput
    output_model: ClassVar[type[ToolOutput]] = ReadCrmTargetsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="none: reading the project's accounts and claims writes nothing",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    #: The result names people; only the request's shape is shown.
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "include_contacts",
            "offset",
            "limit",
            "contacts_limit",
        )
    )
    pin_requirements = ("project",)

    def __init__(self, *, settings: Settings, conn_factory: ConnFactory = transaction) -> None:
        self._settings = settings
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def _failures(
        self, inputs: ReadCrmTargetsInput, ctx: ToolContext
    ) -> list[PreconditionFailure]:
        failures: list[PreconditionFailure] = []
        async with self._conn_factory() as conn:
            project = await get_project_for_workspace(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id
            )
        if project is None:
            failures.append(
                PreconditionFailure("project_not_found", "That project is not in this workspace.")
            )
        for account_id in inputs.account_ids or ():
            if not _is_uuid(account_id):
                failures.append(
                    PreconditionFailure(
                        "invalid_account_id", f"{account_id!r} is not an account id."
                    )
                )
                break
        return failures

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ReadCrmTargetsInput)
        return tuple(await self._failures(inputs, ctx))

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadCrmTargetsInput)
        failures = await self._failures(inputs, ctx)
        if failures:
            raise _refuse(failures[0].reason_code, failures[0].message)
        async with self._conn_factory() as conn:
            connection = await latest_connection(conn, workspace_id=ctx.workspace_id)
            active = (
                connection if connection is not None and connection.status == "active" else None
            )
            targets = await project_targets(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                connection_id=active.connection_id if active is not None else None,
                provider=active.provider if active is not None else None,
                settings=self._settings,
                account_ids=inputs.account_ids,
                include_contacts=inputs.include_contacts,
                offset=inputs.offset,
                limit=inputs.limit,
                contacts_limit=inputs.contacts_limit,
            )
        output = ReadCrmTargetsOutput(
            accounts=targets.accounts,
            contacts=targets.contacts,
            total_accounts=targets.total_accounts,
            total_contacts=targets.total_contacts,
            contacts_note=targets.contacts_note,
            connected_crm=active.provider if active is not None else None,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
