"""The Head of ABM's reads for writing a project into the connected CRM (CRM integration Phase 3).

``read_crm_targets@1`` (Task 4): a project's accounts and buying committee, already reduced to what
Clue may write. The reduction itself lives in :mod:`clue_api.crm.targets`; this is the agent's
read over it. It reads only Clue's database: the CRM is never called.

``find_crm_list@1`` and ``link_crm_list@1`` (Task 7, R-11.11): the lists (HubSpot) and campaigns
(Salesforce) a project adds to. ``find_crm_list`` gives the ones Clue keeps for the project (and
says when the CRM no longer has one), and with a name looks the list up in the CRM by that exact
name. ``link_crm_list`` keeps a list the person names, after checking in the CRM that it exists and
can take members; it writes only Clue's own records (:mod:`clue_api.crm.lists`), never the CRM, so
it needs no permission card. Answers are read in the shapes verified live (composio-api-notes.md
§ Phase 3 shapes).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, StringConstraints

from clue_agents.manual import tool_manual_link
from clue_api.crm.clue_fields import clue_fields_set_up, clue_fields_state
from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    CrmProvider,
    ExecuteResult,
    composio_user_id,
)
from clue_api.crm.connections import CrmConnection, latest_connection
from clue_api.crm.lists import CrmList, lists_for_project, store_list
from clue_api.crm.salesforce_budget import (
    API_DISABLED_MESSAGE,
    CrmBudgetExhausted,
    SalesforceBudget,
    is_api_disabled,
)
from clue_api.crm.targets import (
    MAX_TARGET_CONTACTS,
    TargetAccount,
    TargetContact,
    project_targets,
)
from clue_api.crm.tools import (
    _active_connection,
    _refuse,
    _Refused,
    _require_gateway,
    composio_refusal,
)
from clue_api.crm.write_actions import HUBSPOT_OBJECT_TYPE_IDS
from clue_api.crm.write_prepare import _sf_key, _soql_text, _status_code, _unwrap
from clue_config import Settings
from clue_db import ConnFactory, transaction
from clue_spine import get_project_for_workspace
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
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

__all__ = [
    "CrmListView",
    "FindCrmListInput",
    "FindCrmListOutput",
    "FindCrmListTool",
    "LinkCrmListInput",
    "LinkCrmListOutput",
    "LinkCrmListTool",
    "ReadCrmTargetsInput",
    "ReadCrmTargetsOutput",
    "ReadCrmTargetsTool",
]

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
    #: Set when a CRM is connected but Clue's own fields are not set up (or one is gone): the
    #: clue_* values are still offered, but cannot be written until the setup is proposed.
    clue_fields_note: str | None = None


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
            state = (
                await clue_fields_state(conn, connection_id=active.connection_id)
                if active is not None
                else None
            )
        output = ReadCrmTargetsOutput(
            accounts=targets.accounts,
            contacts=targets.contacts,
            total_accounts=targets.total_accounts,
            total_contacts=targets.total_contacts,
            contacts_note=targets.contacts_note,
            connected_crm=active.provider if active is not None else None,
            clue_fields_note=(
                f"Clue's fields are not set up in {_CRM_NAMES[active.provider]}; "
                "propose_clue_fields_setup first."
                if active is not None and not clue_fields_set_up(state)
                else None
            ),
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


# --- find_crm_list@1 / link_crm_list@1 (Task 7) ------------------------------------------------

CrmListObject = Literal["company", "contact"]
#: The most campaigns of one name a find returns (Salesforce names may repeat).
_MAX_FOUND = 10
_HUBSPOT_LIST_ID = re.compile(r"^[0-9]{1,20}$")
_SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")
_CRM_NAMES: Mapping[str, str] = {"hubspot": "HubSpot", "salesforce": "Salesforce"}


class CrmListView(BaseModel):
    crm_list_id: str
    name: str
    #: What the list holds: HubSpot lists hold companies or contacts; a Salesforce campaign
    #: holds contacts.
    object: CrmListObject
    #: Clue may add to it: a HubSpot list whose members are set by hand (not by a rule), or any
    #: Salesforce campaign.
    manual: bool
    #: Clue keeps it for this project, so changes to it may be proposed.
    stored: bool
    #: Clue kept it, but the CRM no longer has it.
    gone: bool
    #: Clue created it (only a kept list can say so).
    created_by_clue: bool
    #: Whether a Salesforce campaign is active; ``None`` on HubSpot.
    active: bool | None


class FindCrmListInput(ToolInput):
    project_id: str
    #: The exact name of a list (HubSpot, case ignored) or campaign (Salesforce) to look up in the
    #: CRM. Leave it out to see only the lists Clue keeps for the project.
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    #: HubSpot only: what the list holds. Clue's HubSpot lists hold companies (R-12.3).
    object: CrmListObject = "company"


class FindCrmListOutput(ToolOutput):
    #: The CRM the workspace has connected.
    connected_crm: CrmProvider
    #: The lists Clue keeps for this project: the live ones first, then any the CRM no longer
    #: has (``gone``).
    lists: list[CrmListView]
    #: The lists the CRM has under ``name`` (empty without a name). On Salesforce, several
    #: campaigns may share a name: the active ones come first, newest first.
    found: list[CrmListView]
    #: Says, in words, what was not found, what is gone, or that a name is shared.
    note: str | None


class LinkCrmListInput(ToolInput):
    project_id: str
    #: The list's (HubSpot) or campaign's (Salesforce) id, as find_crm_list gave it.
    crm_list_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    #: HubSpot only: what the list holds, as find_crm_list gave it.
    object: CrmListObject = "company"


class LinkCrmListOutput(ToolOutput):
    connected_crm: CrmProvider
    #: The list as Clue now keeps it for the project.
    list: CrmListView


class _ListTool(Tool):
    """What both list tools share: the CRM connection, the project check, and one CRM read."""

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ComposioGateway | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._conn_factory = conn_factory
        self._budget = (
            None
            if gateway is None
            else SalesforceBudget(
                gateway,
                share_pct=settings.crm_salesforce_api_share_pct,
                version=settings.composio_salesforce_toolkit_version,
            )
        )

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def _checked(self, project_id: str, ctx: ToolContext) -> CrmConnection:
        """The active connection, once the gateway exists and the project is the workspace's."""
        _require_gateway(self._gateway)
        async with self._conn_factory() as conn:
            project = await get_project_for_workspace(
                conn, workspace_id=ctx.workspace_id, project_id=project_id
            )
        if project is None:
            raise _Refused("project_not_found", "That project is not in this workspace.")
        return await _active_connection(self._conn_factory, ctx.workspace_id)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, FindCrmListInput | LinkCrmListInput)
        try:
            await self._checked(inputs.project_id, ctx)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def _connection(self, project_id: str, ctx: ToolContext) -> CrmConnection:
        try:
            return await self._checked(project_id, ctx)
        except _Refused as exc:
            raise _refuse(exc.reason_code, str(exc)) from exc

    async def _read(
        self, connection: CrmConnection, slug: str, arguments: Mapping[str, Any]
    ) -> ExecuteResult:
        """One read of the CRM; a Salesforce read is taken from the org's daily share first."""
        gateway = _require_gateway(self._gateway)
        try:
            if connection.provider == "salesforce":
                await self._take_salesforce_call(connection)
            result = await gateway.execute(
                slug=slug,
                arguments=dict(arguments),
                connected_account_id=connection.composio_connected_account_id,
                user_id=composio_user_id(connection.workspace_id),
                version=(
                    self._settings.composio_hubspot_toolkit_version
                    if connection.provider == "hubspot"
                    else self._settings.composio_salesforce_toolkit_version
                ),
            )
        except ComposioError as exc:
            raise await composio_refusal(self._conn_factory, exc, connection) from exc
        if (
            not result.successful
            and connection.provider == "salesforce"
            and is_api_disabled(result.error)
        ):
            raise _refuse("salesforce_api_disabled", API_DISABLED_MESSAGE)
        return result

    async def _take_salesforce_call(self, connection: CrmConnection) -> None:
        assert self._budget is not None
        refusal: CrmBudgetExhausted | None = None
        async with self._conn_factory() as conn:
            try:
                await self._budget.take_call(
                    conn, connection=connection, today=datetime.now(UTC).date()
                )
            except CrmBudgetExhausted as exc:
                refusal = exc  # keep the limits lookup counted: it did reach Salesforce
        if refusal is not None:
            raise _refuse(refusal.reason_code, str(refusal))

    def _failed(self, connection: CrmConnection, result: ExecuteResult) -> PreconditionFailed:
        return _refuse(
            "crm_action_failed",
            f"{_CRM_NAMES[connection.provider]} refused the list read: "
            f"{result.error or 'no reason given'}",
        )

    def _unreadable(self, connection: CrmConnection) -> PreconditionFailed:
        return _refuse(
            "crm_action_failed",
            f"{_CRM_NAMES[connection.provider]} answered the list read in a shape Clue does not "
            "know.",
        )


class FindCrmListTool(_ListTool):
    name = "find_crm_list"
    version = "1"
    model_description = (
        "Find the list (HubSpot) or campaign (Salesforce) a project adds to. 'lists' are the ones "
        "Clue keeps for the project; propose changes only to one with stored true. A list with "
        "gone true is one the CRM no longer has: look for it by name, and if it is not there, "
        "propose creating it again. With name, the CRM is searched for a list of exactly that "
        "name and 'found' lists it: when the person named it, link it with link_crm_list before "
        "proposing changes to it (a HubSpot list with manual false is set by a rule and cannot "
        "take members). Salesforce campaigns may share a name: when 'found' has more than one, "
        "ask the person which one they mean. " + tool_manual_link("find_crm_list")
    )
    input_model: ClassVar[type[ToolInput]] = FindCrmListInput
    output_model: ClassVar[type[ToolOutput]] = FindCrmListOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="none: reading Clue's kept lists and one CRM list lookup writes nothing",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="On Salesforce a lookup by name counts against the org's daily API share.",
    )
    #: A list name can name a company or a person, so it is not displayed.
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "object"))
    pin_requirements = ("project",)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, FindCrmListInput)
        connection = await self._connection(inputs.project_id, ctx)
        async with self._conn_factory() as conn:
            kept = await lists_for_project(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                connection_id=connection.connection_id,
                include_gone=True,
            )
        lists = [_kept_view(item) for item in kept]
        notes = [
            f"{_CRM_NAMES[connection.provider]} no longer has the {_noun(connection)} "
            f'"{item.name}" ({item.crm_list_id}): find it by name, or propose creating it again.'
            for item in kept
            if item.gone_at is not None
        ]
        found: list[CrmListView] = []
        if inputs.name is not None:
            found = await self._find(connection, inputs.name, inputs.object)
            # A list found by name that Clue already keeps for the project is said to be kept.
            live = {item.crm_list_id: item for item in lists if item.stored}
            found = [
                live[item.crm_list_id].model_copy(update={"active": item.active})
                if item.crm_list_id in live
                else item
                for item in found
            ]
            noun = _noun(connection)
            if not found:
                notes.append(
                    f'{_CRM_NAMES[connection.provider]} has no {noun} named "{inputs.name}".'
                )
            elif len(found) > 1:
                notes.append(
                    f"{_CRM_NAMES[connection.provider]} has {len(found)} {noun}s named "
                    f'"{inputs.name}"; ask the person which one they mean.'
                )
        output = FindCrmListOutput(
            connected_crm=connection.provider,
            lists=lists,
            found=found,
            note=" ".join(notes) or None,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    async def _find(
        self, connection: CrmConnection, name: str, crm_object: CrmListObject
    ) -> list[CrmListView]:
        if connection.provider == "hubspot":
            result = await self._read(
                connection,
                "HUBSPOT_GET_CRM_LIST_BY_NAME",
                {"object_type_id": HUBSPOT_OBJECT_TYPE_IDS[crm_object], "list_name": name},
            )
            if not result.successful:
                # HubSpot answers 404 LIST_NAME_DOES_NOT_EXIST for a name it does not have.
                if _status_code(result) == 404 or "LIST_NAME_DOES_NOT_EXIST" in (
                    result.error or ""
                ):
                    return []
                raise self._failed(connection, result)
            body = _unwrap(result.data)
            found = body.get("list") if isinstance(body, Mapping) else None
            view = _hubspot_view(found)
            if view is None:
                raise self._unreadable(connection)
            return [view]
        result = await self._read(
            connection,
            "SALESFORCE_RUN_SOQL_QUERY",
            {
                "query": "SELECT Id, Name, IsActive, Status FROM Campaign WHERE Name = "
                f"{_soql_text(name)} ORDER BY IsActive DESC, CreatedDate DESC "
                f"LIMIT {_MAX_FOUND}"
            },
        )
        if not result.successful:
            raise self._failed(connection, result)
        records = _soql_records(result)
        if records is None:
            raise self._unreadable(connection)
        views = [view for view in (_campaign_view(record) for record in records) if view]
        # Active campaigns first; within each, the order Salesforce gave (newest first).
        return sorted(views, key=lambda view: view.active is not True)


class LinkCrmListTool(_ListTool):
    name = "link_crm_list"
    version = "1"
    model_description = (
        "Keep a list (HubSpot) or campaign (Salesforce) the person named for this project, so "
        "Clue can propose adding to it. Give the id find_crm_list found (and, on HubSpot, its "
        "object). Clue checks in the CRM that it exists and, on HubSpot, that its members are "
        "set by hand, not by a rule. Clue never removes members it did not add. This changes "
        "only Clue's own records, not the CRM, so no permission card is shown; linking it again "
        "changes nothing. " + tool_manual_link("link_crm_list")
    )
    input_model: ClassVar[type[ToolInput]] = LinkCrmListInput
    output_model: ClassVar[type[ToolOutput]] = LinkCrmListOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one crm_list row per (connection_id, crm_list_id) and one crm_list_project row per "
            "(list_id, project_id); storing and linking again changes nothing"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "Writes only Clue's database. The check reads the CRM again on a replay (on "
            "Salesforce, counted against the org's daily API share)."
        ),
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "crm_list_id", "object")
    )
    pin_requirements = ("project",)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LinkCrmListInput)
        connection = await self._connection(inputs.project_id, ctx)
        view = await self._look_up(connection, inputs.crm_list_id, inputs.object)
        if not view.manual:
            raise _refuse(
                "crm_list_not_manual",
                f'The HubSpot list "{view.name}" ({view.crm_list_id}) is set by a rule, so Clue '
                "cannot add to it. Ask the person for a list whose members are set by hand, or "
                "propose creating Clue's own list.",
            )
        async with self._conn_factory() as conn:
            stored = await store_list(
                conn,
                workspace_id=ctx.workspace_id,
                connection_id=connection.connection_id,
                provider=connection.provider,
                crm_object=view.object,
                crm_list_id=view.crm_list_id,
                name=view.name,
                kind="hubspot_list" if connection.provider == "hubspot" else "salesforce_campaign",
                created_by_clue=False,
                created_by_write_id=None,
                project_id=inputs.project_id,
            )
        output = LinkCrmListOutput(
            connected_crm=connection.provider,
            list=view.model_copy(
                update={"stored": True, "gone": False, "created_by_clue": stored.created_by_clue}
            ),
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    async def _look_up(
        self, connection: CrmConnection, crm_list_id: str, crm_object: CrmListObject
    ) -> CrmListView:
        not_found = _refuse(
            "crm_list_not_found",
            f"{_CRM_NAMES[connection.provider]} has no {_noun(connection)} with the id "
            f"{crm_list_id!r}. Find it by its exact name with find_crm_list and link the id it "
            "gives.",
        )
        if connection.provider == "hubspot":
            if not _HUBSPOT_LIST_ID.match(crm_list_id):
                raise not_found
            result = await self._read(
                connection,
                "HUBSPOT_SEARCH_CRM_LISTS",
                {
                    "objectTypeId": HUBSPOT_OBJECT_TYPE_IDS[crm_object],
                    "listIds": [crm_list_id],
                    "count": 1,
                },
            )
            if not result.successful:
                raise self._failed(connection, result)
            body = _unwrap(result.data)
            lists = body.get("lists") if isinstance(body, Mapping) else None
            if not isinstance(lists, list):
                raise self._unreadable(connection)
            for item in lists:
                if isinstance(item, Mapping) and str(item.get("listId")) == crm_list_id:
                    view = _hubspot_view(item)
                    if view is None:
                        raise self._unreadable(connection)
                    return view
            raise not_found
        if not _SALESFORCE_ID.match(crm_list_id):
            raise not_found
        result = await self._read(
            connection,
            "SALESFORCE_RUN_SOQL_QUERY",
            {
                "query": "SELECT Id, Name, IsActive, Status FROM Campaign WHERE Id = "
                f"{_soql_text(crm_list_id)} LIMIT 1"
            },
        )
        if not result.successful:
            raise self._failed(connection, result)
        records = _soql_records(result)
        if records is None:
            raise self._unreadable(connection)
        for record in records:
            view = _campaign_view(record)
            if view is not None and _sf_key(view.crm_list_id) == _sf_key(crm_list_id):
                # Kept under the id Salesforce answers (its 18-character form).
                return view
        raise not_found


def _noun(connection: CrmConnection) -> str:
    return "list" if connection.provider == "hubspot" else "campaign"


def _kept_view(item: CrmList) -> CrmListView:
    gone = item.gone_at is not None
    return CrmListView(
        crm_list_id=item.crm_list_id,
        name=item.name,
        object="company" if item.crm_object == "company" else "contact",
        # Clue keeps only lists that can take members (its own manual lists, or ones it checked).
        manual=True,
        stored=not gone,
        gone=gone,
        created_by_clue=item.created_by_clue,
        active=None,
    )


def _hubspot_view(found: object) -> CrmListView | None:
    if not isinstance(found, Mapping) or found.get("listId") in (None, ""):
        return None
    name = found.get("name")
    object_type = found.get("objectTypeId")
    crm_object = next(
        (key for key, value in HUBSPOT_OBJECT_TYPE_IDS.items() if value == object_type), None
    )
    if not isinstance(name, str) or crm_object not in ("company", "contact"):
        return None
    return CrmListView(
        crm_list_id=str(found["listId"]),
        name=name,
        object="company" if crm_object == "company" else "contact",
        # Only a list whose members are set by hand takes members from Clue (Task 1 spike).
        manual=found.get("processingType") == "MANUAL",
        stored=False,
        gone=False,
        created_by_clue=False,
        active=None,
    )


def _campaign_view(record: Mapping[str, Any]) -> CrmListView | None:
    campaign_id, name = record.get("Id"), record.get("Name")
    if not isinstance(campaign_id, str) or not campaign_id or not isinstance(name, str):
        return None
    active = record.get("IsActive")
    return CrmListView(
        crm_list_id=campaign_id,
        name=name,
        # A Salesforce campaign holds the committee contacts Clue wrote (R-12.3).
        object="contact",
        manual=True,
        stored=False,
        gone=False,
        created_by_clue=False,
        active=active if isinstance(active, bool) else None,
    )


def _soql_records(result: ExecuteResult) -> list[Mapping[str, Any]] | None:
    body = _unwrap(result.data)
    records = body.get("records") if isinstance(body, Mapping) else None
    if not isinstance(records, list):
        return None
    return [record for record in records if isinstance(record, Mapping)]
