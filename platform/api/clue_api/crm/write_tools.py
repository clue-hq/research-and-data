"""``propose_crm_changes@1``: the agent's only way to change the connected CRM (CRM integration
Phase 2, spec docs/superpowers/specs/crm-integration/ §6.1). Beside it, ``crm_write_log@1`` reads
what Clue changed (with the before values an undo proposes again) and ``manage_crm_grants@1`` lists
and revokes the standing permissions; granting happens only on the permission card.

The agent proposes a batch; :func:`~clue_api.crm.write_prepare.prepare_changes` checks it against
the allowlist and reads what the CRM holds today, and the batch is logged as one
``crm_write_proposal`` with its ordered ``crm_write`` rows before anything is sent. When a standing
permission covers every change the proposal is ``queued`` and the connection's write executor is
offered at once. Otherwise one permission card (a ``crm_write_permission`` gate) asks the person,
the covered changes waiting with the rest, and the agent ends its turn on it. A chat shows one live
card: an earlier card of the same chat still waiting for its answer is ``replaced``.

The proposal id is derived from the presenting turn and the exact batch, so a replayed call finds
its own proposal and returns it without reading the CRM again.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.agent_gate import (
    KIND_CRM_WRITE_PERMISSION,
    crm_write_permission_gate_id,
    insert_gate,
)
from clue_api.agent_gate_tools import gate_ref
from clue_api.crm.composio_gateway import ComposioError, ComposioGateway
from clue_api.crm.connections import CrmConnection
from clue_api.crm.salesforce_budget import CrmBudgetExhausted, SalesforceBudget
from clue_api.crm.tools import (
    _active_connection,
    _refuse,
    _Refused,
    _require_gateway,
    composio_refusal,
)
from clue_api.crm.write_prepare import (
    PreparedChange,
    ProposedChange,
    WriteRefused,
    _noun,
    card_snapshot,
    prepare_changes,
)
from clue_api.crm.writes import (
    insert_proposal,
    insert_writes,
    live_grants,
    revoke_grant,
    set_proposal_status,
)
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_config import Settings
from clue_db import ConnFactory, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind, WorkId, WorkQueue
from clue_spine import get_project
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

__all__ = [
    "CrmChangeInput",
    "CrmChangeGroup",
    "CrmGrantView",
    "CrmLoggedWrite",
    "CrmWriteLogInput",
    "CrmWriteLogOutput",
    "CrmWriteLogTool",
    "ManageCrmGrantsInput",
    "ManageCrmGrantsOutput",
    "ManageCrmGrantsTool",
    "ProposeCrmChangesInput",
    "ProposeCrmChangesOutput",
    "ProposeCrmChangesTool",
    "crm_write_dedup_key",
    "proposal_id_for",
]

_PROPOSAL_NAMESPACE = uuid5(NAMESPACE_URL, "clue:crm:write-proposal")
_MAX_CHANGES = 500


class CrmChangeInput(BaseModel):
    #: A write action find_crm_actions listed with access "write".
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    arguments: dict[str, Any]
    #: One line the person reads on the card: why Clue wants this change.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    #: Where the value came from (a claim, a document path), when there is one.
    source_ref: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
        | None
    ) = None
    #: The logged write this change undoes, when it is an undo.
    reverses_write_id: UUID | None = None


class ProposeCrmChangesInput(ToolInput):
    changes: list[CrmChangeInput] = Field(min_length=1, max_length=_MAX_CHANGES)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class CrmChangeGroup(BaseModel):
    kind: str
    object: str
    field: str | None
    count: int
    #: A standing permission covers these: they are sent without asking.
    covered: bool
    #: These overwrite a value a person set; each is shown on the card on its own, unticked.
    overwrites_person: bool


class ProposeCrmChangesOutput(ToolOutput):
    proposal_id: str
    state: Literal["queued", "awaiting_permission"]
    gate_id: str | None
    gate_ref: str | None
    gate_kind: str | None
    covered: int
    needs_permission: int
    groups: list[CrmChangeGroup]
    overwrites: int


def proposal_id_for(source_turn_ref: str, changes: Sequence[CrmChangeInput]) -> UUID:
    """One proposal per presenting turn and exact batch."""
    digest = hashlib.sha256(
        json.dumps(
            [change.model_dump(mode="json") for change in changes],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return uuid5(_PROPOSAL_NAMESPACE, f"{len(source_turn_ref)}:{source_turn_ref}{digest}")


def crm_write_dedup_key(connection_id: UUID) -> str:
    """The write executor's one task per connection."""
    return f"crm-write:{connection_id}"


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class ProposeCrmChangesTool(Tool):
    name = "propose_crm_changes"
    version = "1"
    model_description = (
        "Propose changes to the connected CRM: one batch of write actions found with "
        "find_crm_actions (access 'write'), each with its arguments and a one-line reason the "
        "person reads. Clue checks every change, reads the values the CRM holds today, and sends "
        "at once the changes a standing permission covers. When state is 'awaiting_permission' a "
        "permission card asks the person: tell them to use the card and end your turn; the chat "
        "continues by itself when the changes are done. Put everything you want to change in one "
        "call. " + tool_manual_link("propose_crm_changes")
    )
    input_model: ClassVar[type[ToolInput]] = ProposeCrmChangesInput
    output_model: ClassVar[type[ToolOutput]] = ProposeCrmChangesOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one crm_write_proposal per presenting turn and exact batch "
            "(proposal_id = uuid5 of the turn ref and the input digest)"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "Preparing reads the CRM (and, on Salesforce, counts those reads against the org's "
            "daily API share); a replay finds the stored proposal and reads nothing."
        ),
    )
    #: The arguments and reasons can name people and companies, so nothing is displayed.
    parameter_policy = JournalParameterPolicy(safe_display_fields=())
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ComposioGateway | None,
        conn_factory: ConnFactory = transaction,
        work_queue: WorkQueue | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._conn_factory = conn_factory
        self._work_queue = work_queue
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeCrmChangesInput)
        try:
            _require_gateway(self._gateway)
            await self._turn(inputs, ctx)
            await _active_connection(self._conn_factory, ctx.workspace_id)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeCrmChangesInput)
        try:
            gateway = _require_gateway(self._gateway)
            turn = await self._turn(inputs, ctx)
            connection = await _active_connection(self._conn_factory, ctx.workspace_id)
        except _Refused as exc:
            raise _refuse(exc.reason_code, str(exc)) from exc
        proposal_id = proposal_id_for(inputs.source_turn_ref, inputs.changes)

        refusal: Exception | None = None
        async with self._conn_factory() as conn:
            stored = await _stored_output(conn, ctx.workspace_id, proposal_id)
            if stored is None:
                try:
                    prepared = await prepare_changes(
                        conn,
                        gateway=gateway,
                        budget=self._budget if connection.provider == "salesforce" else None,
                        connection=connection,
                        proposal_id=proposal_id,
                        changes=[
                            ProposedChange(
                                slug=change.slug,
                                arguments=change.arguments,
                                reason=change.reason,
                                source_ref=change.source_ref,
                                reverses_write_id=change.reverses_write_id,
                            )
                            for change in inputs.changes
                        ],
                        version=self._version(connection),
                    )
                except (WriteRefused, ComposioError, CrmBudgetExhausted) as exc:
                    # Leave the block normally: the Salesforce reads already made stay counted.
                    refusal = exc
                else:
                    if not prepared:
                        refusal = WriteRefused(
                            "crm_nothing_to_change",
                            "The CRM already holds every proposed value, so nothing was proposed.",
                        )
                    else:
                        await self._record(conn, ctx, turn, connection, proposal_id, prepared)
                        stored = await _stored_output(conn, ctx.workspace_id, proposal_id)
        if isinstance(refusal, ComposioError):
            raise await composio_refusal(self._conn_factory, refusal, connection) from refusal
        if isinstance(refusal, WriteRefused | CrmBudgetExhausted):
            raise _refuse(refusal.reason_code, str(refusal)) from refusal
        assert stored is not None
        if stored.state == "queued":
            await self._offer(connection)
        return ToolResult(
            tool=self.name, version=self.version, references=stored.model_dump(mode="json")
        )

    async def _record(
        self,
        conn: AsyncConnection,
        ctx: ToolContext,
        turn: Any,
        connection: CrmConnection,
        proposal_id: UUID,
        prepared: Sequence[PreparedChange],
    ) -> None:
        needs_permission = any(change.covered_by is None for change in prepared)
        await insert_proposal(
            conn,
            proposal_id=proposal_id,
            workspace_id=ctx.workspace_id,
            connection_id=connection.connection_id,
            project_id=turn.project_id,
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
        )
        await insert_writes(
            conn,
            proposal_id=proposal_id,
            workspace_id=ctx.workspace_id,
            connection_id=connection.connection_id,
            prepared=prepared,
        )
        if not needs_permission:
            await set_proposal_status(conn, proposal_id=proposal_id, status="queued")
            return

        # One live card per chat: an earlier card still waiting for its answer is replaced. One
        # guarded UPDATE, never read-then-write: when an answer is being recorded on that card at
        # the same moment, this waits for its row lock and then re-checks the status, so a
        # proposal the answer just queued (or declined) is never overwritten.
        await conn.execute(
            text(
                "UPDATE crm_write_proposal SET status = 'replaced', finished_at = now() "
                "WHERE workspace_id = :ws AND thread_id = :thread "
                "AND status = 'awaiting_permission' AND proposal_id <> :proposal_id"
            ),
            {"ws": ctx.workspace_id, "thread": turn.thread_id, "proposal_id": proposal_id},
        )

        project = await get_project(conn, turn.project_id)
        snapshot = card_snapshot(
            prepared,
            provider=connection.provider,
            project_name=project.name if project is not None else "",
        )
        gate_id = crm_write_permission_gate_id(
            workspace_id=ctx.workspace_id, proposal_id=proposal_id
        )
        await insert_gate(
            conn,
            gate_id=gate_id,
            workspace_id=ctx.workspace_id,
            project_id=turn.project_id,
            thread_id=turn.thread_id,
            turn_id=turn.turn_id,
            kind=KIND_CRM_WRITE_PERMISSION,
            subject_ref=f"crm_write_proposal:{proposal_id}",
            subject_revision=None,
            expected_subject_sha256=_snapshot_digest(snapshot),
            subject_snapshot=snapshot,
            # Asking to write spends nothing, so the card carries no amount.
            max_spend_cents=None,
            currency=None,
            addressee_user_id=turn.submitted_by_user_id,
            permitted_decisions=("approved", "rejected"),
        )
        await set_proposal_status(
            conn, proposal_id=proposal_id, status="awaiting_permission", gate_id=gate_id
        )

    async def _offer(self, connection: CrmConnection) -> None:
        """Offer the connection's write executor; a finished one is offered again."""
        queue = self._work_queue if self._work_queue is not None else DbWorkQueue()
        await queue.enqueue(
            kind=FleetTaskKind.CRM_WRITE,
            work_id=WorkId(connection.connection_id),
            dedup_key=crm_write_dedup_key(connection.connection_id),
            reopen_terminal=True,
        )

    def _version(self, connection: CrmConnection) -> str:
        if connection.provider == "hubspot":
            return self._settings.composio_hubspot_toolkit_version
        return self._settings.composio_salesforce_toolkit_version

    async def _turn(self, inputs: ProposeCrmChangesInput, ctx: ToolContext) -> Any:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _Refused("crm_turn_not_found", "The current turn is unavailable.") from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None or not turn.submitted_by_user_id:
            raise _Refused("crm_turn_not_found", "The current turn has no person to ask.")
        return turn


async def _stored_output(
    conn: AsyncConnection, workspace_id: str, proposal_id: UUID
) -> ProposeCrmChangesOutput | None:
    """The tool's answer for a logged proposal, read from its rows (the same on a replay)."""
    row = (
        await conn.execute(
            text(
                "SELECT gate_id FROM crm_write_proposal "
                "WHERE proposal_id = :id AND workspace_id = :ws"
            ),
            {"id": proposal_id, "ws": workspace_id},
        )
    ).one_or_none()
    if row is None:
        return None
    gate_id = row.gate_id
    groups = [
        CrmChangeGroup(
            kind=group.kind,
            object=group.object,
            field=group.field,
            count=group.changes,
            covered=group.covered,
            overwrites_person=group.overwrites_person,
        )
        for group in (
            await conn.execute(
                text(
                    "SELECT kind, object, field, covered_by IS NOT NULL AS covered, "
                    "overwrites_person, count(*) AS changes FROM crm_write "
                    "WHERE proposal_id = :id "
                    "GROUP BY kind, object, field, covered_by IS NOT NULL, overwrites_person "
                    "ORDER BY min(ordinal)"
                ),
                {"id": proposal_id},
            )
        ).all()
    ]
    return ProposeCrmChangesOutput(
        proposal_id=str(proposal_id),
        state="queued" if gate_id is None else "awaiting_permission",
        gate_id=None if gate_id is None else str(gate_id),
        gate_ref=None if gate_id is None else gate_ref(gate_id),
        gate_kind=None if gate_id is None else KIND_CRM_WRITE_PERMISSION,
        covered=sum(group.count for group in groups if group.covered),
        needs_permission=sum(group.count for group in groups if not group.covered),
        groups=groups,
        overwrites=sum(group.count for group in groups if group.overwrites_person),
    )


# --- the write log ---------------------------------------------------------------------------

_LOG_DEFAULT_DAYS = 7
_LOG_MAX_ROWS = 200


class CrmWriteLogInput(ToolInput):
    #: One proposal's changes, however long ago (the week's window does not apply).
    proposal_id: UUID | None = None
    #: A record's CRM id, or part of its name.
    record: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    status: Literal["proposed", "queued", "sending", "succeeded", "failed", "skipped"] | None = None
    since_days: int = Field(default=_LOG_DEFAULT_DAYS, ge=1, le=3_650)
    limit: int = Field(default=50, ge=1, le=_LOG_MAX_ROWS)


class CrmLoggedWrite(BaseModel):
    write_id: str
    #: The write action and what it acts on, so an undo is one propose_crm_changes call.
    slug: str
    object: str
    kind: str
    when: datetime
    record_label: str
    record_ref: str | None
    field: str | None
    before: Any
    after: Any
    status: str
    failure_kind: str | None
    crm_message: str | None
    reason: str
    proposal_id: str


class CrmWriteLogOutput(ToolOutput):
    writes: list[CrmLoggedWrite]


class CrmWriteLogTool(Tool):
    name = "crm_write_log"
    version = "1"
    model_description = (
        "Read what Clue changed (or tried to change) in the CRM, newest first: each change's "
        "record, field, the value before and after, its status and the CRM's message when it "
        "failed. By default the last 7 days; narrow by proposal_id (any age), record (its CRM id "
        "or part of its name), status or since_days. To undo a change, call propose_crm_changes "
        "with reverses_write_id set to its write_id: for a field update (kind 'field_update'), "
        "propose the same action with the before value; for adding someone to a list or "
        "campaign (kind 'list_membership'), propose the matching removal; for a removal, propose "
        "adding them back. Clue does not undo a created record (kinds 'create_contact', "
        "'create_company'): tell the person to delete it in the CRM if they want it gone. "
        + tool_manual_link("crm_write_log")
    )
    input_model: ClassVar[type[ToolInput]] = CrmWriteLogInput
    output_model: ClassVar[type[ToolOutput]] = CrmWriteLogOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="none: reading the write log writes nothing",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    #: The log names CRM records (people and companies), so only the filters' shape is shown.
    parameter_policy = JournalParameterPolicy(safe_display_fields=("status", "since_days", "limit"))
    pin_requirements = ("project",)

    def __init__(
        self, *, gateway: ComposioGateway | None, conn_factory: ConnFactory = transaction
    ) -> None:
        self._gateway = gateway
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        try:
            _require_gateway(self._gateway)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, CrmWriteLogInput)
        try:
            _require_gateway(self._gateway)
        except _Refused as exc:
            raise _refuse(exc.reason_code, str(exc)) from exc
        # Every connection of the workspace: the history outlives a reconnect.
        where = ["w.workspace_id = :ws"]
        params: dict[str, Any] = {"ws": ctx.workspace_id, "limit": inputs.limit}
        if inputs.proposal_id is not None:
            where.append("w.proposal_id = :proposal_id")
            params["proposal_id"] = inputs.proposal_id
        else:
            where.append(f"{_WHEN} >= now() - make_interval(days => :days)")
            params["days"] = inputs.since_days
        if inputs.record is not None:
            where.append(
                "(w.record_ref = :record OR w.record_label ILIKE '%' || :record_like || '%')"
            )
            params["record"] = inputs.record
            params["record_like"] = _escape_like(inputs.record)
        if inputs.status is not None:
            where.append("w.status = :status")
            params["status"] = inputs.status
        async with self._conn_factory() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT w.write_id, w.slug, w.object, w.kind, "  # noqa: S608
                        f"{_WHEN} AS logged_at, w.record_label, w.record_ref, w.field, "
                        "w.before_value::text AS before_value, "
                        "w.after_value::text AS after_value, w.status, w.failure_kind, "
                        "w.crm_message, w.reason, w.proposal_id "
                        "FROM crm_write w JOIN crm_write_proposal p "
                        "ON p.proposal_id = w.proposal_id "
                        f"WHERE {' AND '.join(where)} "
                        f"ORDER BY {_WHEN} DESC, p.created_at DESC, w.ordinal LIMIT :limit"
                    ),
                    params,
                )
            ).all()
        output = CrmWriteLogOutput(
            writes=[
                CrmLoggedWrite(
                    write_id=str(row.write_id),
                    slug=row.slug,
                    object=row.object,
                    kind=row.kind,
                    when=row.logged_at,
                    record_label=row.record_label,
                    record_ref=row.record_ref,
                    field=row.field,
                    before=_json_value(row.before_value),
                    after=_json_value(row.after_value),
                    status=row.status,
                    failure_kind=row.failure_kind,
                    crm_message=row.crm_message,
                    reason=row.reason,
                    proposal_id=str(row.proposal_id),
                )
                for row in rows
            ]
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )


#: When a change happened: when it finished, else when it was sent, else when it was proposed.
_WHEN = "COALESCE(w.finished_at, w.sent_at, p.created_at)"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json_value(raw: str | None) -> Any:
    return None if raw is None else json.loads(raw)


# --- standing permissions ----------------------------------------------------------------------


class ManageCrmGrantsInput(ToolInput):
    action: Literal["list", "revoke"]
    #: The grant to revoke (from a list).
    grant_id: UUID | None = None
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class CrmGrantView(BaseModel):
    grant_id: str
    #: What the person reads, e.g.
    #: "Always allow setting “ICP tier” on companies — by Aryan, 22 Oct".
    phrase: str
    scope_kind: str
    kind: str | None
    object: str | None
    field: str | None
    granted_by_user_id: str
    granted_at: datetime


class ManageCrmGrantsOutput(ToolOutput):
    #: The live standing permissions of the connected CRM (after a revoke, the ones left).
    grants: list[CrmGrantView]
    revoked: CrmGrantView | None
    #: The grant named in a revoke had been revoked before this call; nothing changed.
    already_revoked: bool = False


class ManageCrmGrantsTool(Tool):
    name = "manage_crm_grants"
    version = "1"
    model_description = (
        "List or revoke the standing permissions ('Always allow') the person gave on CRM "
        "permission cards: action 'list' returns each one in plain words; action 'revoke' with "
        "its grant_id withdraws it, so those changes ask again. Permissions are given only on "
        "the card, never with this tool. " + tool_manual_link("manage_crm_grants")
    )
    input_model: ClassVar[type[ToolInput]] = ManageCrmGrantsInput
    output_model: ClassVar[type[ToolOutput]] = ManageCrmGrantsOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "crm_write_grant.revoked_at: a grant is revoked once; revoking it again (a replay) "
            "answers already_revoked and stamps nothing; a list writes nothing"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("action", "grant_id"))
    pin_requirements = ("project",)

    def __init__(
        self, *, gateway: ComposioGateway | None, conn_factory: ConnFactory = transaction
    ) -> None:
        self._gateway = gateway
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ManageCrmGrantsInput)
        try:
            self._check(inputs)
            await _person(self._conn_factory, inputs.source_turn_ref, ctx)
            await _active_connection(self._conn_factory, ctx.workspace_id)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ManageCrmGrantsInput)
        try:
            self._check(inputs)
            person = await _person(self._conn_factory, inputs.source_turn_ref, ctx)
            connection = await _active_connection(self._conn_factory, ctx.workspace_id)
            revoked, already_revoked = None, False
            async with self._conn_factory() as conn:
                if inputs.action == "revoke":
                    assert inputs.grant_id is not None
                    revoked, already_revoked = await _revoke(
                        conn, ctx.workspace_id, connection, inputs.grant_id, person
                    )
                grants = await _grant_views(conn, connection)
        except _Refused as exc:
            raise _refuse(exc.reason_code, str(exc)) from exc
        output = ManageCrmGrantsOutput(
            grants=grants, revoked=revoked, already_revoked=already_revoked
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    def _check(self, inputs: ManageCrmGrantsInput) -> None:
        _require_gateway(self._gateway)
        if inputs.action == "revoke" and inputs.grant_id is None:
            raise _Refused(
                "crm_grant_not_named",
                "Name the permission to revoke by its grant_id (list them first).",
            )


async def _person(conn_factory: ConnFactory, source_turn_ref: str, ctx: ToolContext) -> str:
    """The person whose turn this is (a revoke is stamped with them)."""
    try:
        turn_id = parse_turn_action_ref(source_turn_ref)
    except TurnActionUnresolvable as exc:
        raise _Refused("crm_turn_not_found", "The current turn is unavailable.") from exc
    async with conn_factory() as conn:
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
    if turn is None or not turn.submitted_by_user_id:
        raise _Refused("crm_turn_not_found", "The current turn has no person.")
    return str(turn.submitted_by_user_id)


_GRANT_COLUMNS = (
    "g.grant_id, g.scope_kind, g.kind, g.object, g.field, g.granted_by_user_id, g.granted_at, "
    "g.revoked_at, g.workspace_id, u.display_name AS granted_by_name"
)


async def _revoke(
    conn: AsyncConnection,
    workspace_id: str,
    connection: CrmConnection,
    grant_id: UUID,
    person: str,
) -> tuple[CrmGrantView, bool]:
    """Revoke a grant of the active connection; ``True`` when it was already revoked.

    A grant of an older connection never applies again, so it reads as unknown, like a missing
    id or another workspace's grant.
    """
    row = (
        await conn.execute(
            text(
                f"SELECT {_GRANT_COLUMNS} FROM crm_write_grant g "  # noqa: S608
                "LEFT JOIN platform_user u ON u.user_id = g.granted_by_user_id "
                "WHERE g.grant_id = :id AND g.workspace_id = :ws "
                "AND g.connection_id = :connection_id FOR UPDATE OF g"
            ),
            {"id": grant_id, "ws": workspace_id, "connection_id": connection.connection_id},
        )
    ).first()
    if row is None:
        raise _Refused(
            "crm_grant_not_found",
            "There is no such permission for the connected CRM; list the permissions to find it.",
        )
    view = _grant_view(row, connection.provider)
    # The row is locked, so a grant live here is revoked by this call.
    if row.revoked_at is not None:
        return view, True
    return view, not await revoke_grant(conn, grant_id=grant_id, revoked_by_user_id=person)


async def _grant_views(conn: AsyncConnection, connection: CrmConnection) -> list[CrmGrantView]:
    """The active connection's live grants: a new connection starts with none."""
    live = {
        grant.grant_id for grant in await live_grants(conn, connection_id=connection.connection_id)
    }
    if not live:
        return []
    rows = (
        await conn.execute(
            text(
                f"SELECT {_GRANT_COLUMNS} FROM crm_write_grant g "  # noqa: S608
                "LEFT JOIN platform_user u ON u.user_id = g.granted_by_user_id "
                "WHERE g.grant_id = ANY(:ids) ORDER BY g.granted_at, g.grant_id"
            ),
            {"ids": list(live)},
        )
    ).all()
    return [_grant_view(row, connection.provider) for row in rows]


def _grant_view(row: Any, provider: str) -> CrmGrantView:
    granted_at: datetime = row.granted_at
    by = row.granted_by_name or row.granted_by_user_id
    phrase = (
        f"Always allow {_grant_phrase(provider, row.scope_kind, row.kind, row.object, row.field)}"
        f" — by {by}, {granted_at.day} {granted_at:%b}"
    )
    return CrmGrantView(
        grant_id=str(row.grant_id),
        phrase=phrase,
        scope_kind=row.scope_kind,
        kind=row.kind,
        object=row.object,
        field=row.field,
        granted_by_user_id=row.granted_by_user_id,
        granted_at=granted_at,
    )


def _grant_phrase(
    provider: str, scope_kind: str, kind: str | None, object_name: str | None, field: str | None
) -> str:
    """The card's "Always allow" wording (card spec §5). A grant records no field label, so a
    field is named by its CRM field name."""
    if scope_kind == "fully_automatic":
        return "every change Clue proposes"
    if scope_kind == "field":
        return f"setting “{field}” on {_noun(str(object_name), 2)}"
    target = "lists" if provider == "hubspot" else "campaigns"
    if kind == "list_membership":
        return f"adding contacts to Clue {target}"
    if kind == "list_removal":
        return f"removing contacts from Clue {target}"
    if kind == "create_contact":
        return "creating contacts"
    if kind == "create_company":
        return "creating companies" if provider == "hubspot" else "creating accounts"
    if kind == "link_duplicate":
        return "marking possible duplicates"
    return f"{kind} changes"
