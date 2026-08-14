"""The governed delegation entry onto the design leg (Part III P3.4, PD-part3 §1-D1/§2.3).

One tool, ``open_design_leg@1``, granted to the Head of ABM. It is the materialization of the
master plan's "attach as subagent" wrapper under ruling D1: delegating to Design is not a
LangGraph edge but a durable act — validate the D5 pins, build the §2.3 delegation bundle as one
immutable canonical-JSON artifact, and open the ``design_leg`` row whose existence *is* the
routing rule ("an open leg on the thread receives the user's message").

The authority discipline is the ``open_directive_confirmation_gate`` precedent, applied verbatim:

* **The leg's anchor is not the agent's choice.** The leg is derived from the turn the agent is
  answering (``source_turn_ref``, served through the PC-C8 ``TRUSTED_TURN_FIELD`` seam and
  stripped from the model-visible schema): its thread, its project, its execution. One presenting
  turn derives one leg id, so a replayed delegation converges on the same leg instead of racing
  the partial-unique index.
* **The pins are verified, never trusted.** A document pin's CAS guard is read from the durable
  ``design_document`` row (an ``expected_document_version`` that is not current is refused —
  D5's "mismatch = honest refusal"); a brand pin must name an existing ``(brand_kit_id,
  version)`` row — the fail-closed rule that makes the design entrypoint's silent default
  fallback an *error* once a bundle pin exists.
* **The bundle is bounded at build.** §2.3's day-one size policy: refs-only content and a hard
  byte cap (:data:`DESIGN_DELEGATION_BUNDLE_MAX_BYTES`), enforced here so an oversized bundle
  fails the delegation loudly rather than failing some later design turn confusingly. The cap is
  half of the 48k L3 layer (utf8-bytes token counter), because the C8 project card legitimately
  occupies the other half.

Claim refs ride the :class:`~clue_core.ContactHandoffClaimRef` vocabulary (ids + governance
stamps, never values) — validated structurally at the input model. Their existence/governance
provenance is the research-view surface's job: the only way a head-of-abm holds claim ids at all
is by having read them through ``get_research_view``.

What this tool does **not** do: dispatch anything. Opening a leg spends nothing and runs no
design turn; the agent's next act is to tell the user the design session is open and end its
turn. The user's next message on the thread is what becomes the first design turn (the P3.4
routing rule in ``agent_turn_fleet_wiring``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, JsonValue, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.turn_action import (
    TurnActionUnresolvable,
    TurnIdentity,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import ContactHandoffClaimRef
from clue_db import ConnFactory, transaction
from clue_design import legs as design_legs
from clue_design.documents import get_document
from clue_design.errors import DesignNotFoundError
from clue_storage import StorageBackend
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
    "DESIGN_DELEGATION_BUNDLE_MAX_BYTES",
    "DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE",
    "DESIGN_LEG_REF_PREFIX",
    "FinishDesignLegInput",
    "FinishDesignLegOutput",
    "FinishDesignLegTool",
    "OpenDesignLegInput",
    "OpenDesignLegOutput",
    "OpenDesignLegTool",
    "build_design_leg_tools",
    "design_leg_ref",
]

#: The §2.3 bundle's own media type — one artifact kind, one name.
DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE = "application/vnd.clue.design-delegation-bundle+json"

#: §2.3's day-one hard size policy. The bundle lands in the 48k-token L3 layer
#: (``utf8-bytes-v1`` counter: tokens are bytes) that the C8 project card can half-fill,
#: so the bundle's budget is the other half. An oversized bundle is refused at build.
DESIGN_DELEGATION_BUNDLE_MAX_BYTES = 24_000

#: The opaque reference shape carried in tool results and finalization refs.
DESIGN_LEG_REF_PREFIX = "design-leg:"

_LEG_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg")


def design_leg_ref(leg_id: str | UUID) -> str:
    return f"{DESIGN_LEG_REF_PREFIX}{leg_id}"


def derive_design_leg_id(*, workspace_id: str, turn_id: UUID) -> str:
    """One presenting turn ⇒ one leg id — the replay identity of the delegation."""

    framed = f"{len(workspace_id)}:{workspace_id}{len(str(turn_id))}:{turn_id}"
    return str(uuid5(_LEG_NAMESPACE, framed))


class OpenDesignLegInput(ToolInput):
    """What the agent proposes; every authority value is derived by the engine, not accepted."""

    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    #: The design brief — what the user wants made. Free text (D5: no fabricated content plane).
    brief: str = Field(min_length=1, max_length=16_000)
    #: Target document (nullable — a leg may create its document, §2.1).
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    #: The document version the agent believes is current. When present it must match the durable
    #: ``current_version`` exactly (the D5 CAS guard); when absent the current version is pinned.
    expected_document_version: int | None = Field(default=None, ge=0)
    #: The D5 fail-closed brand pin — both fields or neither.
    brand_kit_id: str | None = Field(default=None, min_length=1, max_length=200)
    brand_kit_version: int | None = Field(default=None, ge=1)
    #: Governed claim edges (ids + stamps, never values) — the C8 §2.3 vocabulary.
    claim_refs: tuple[ContactHandoffClaimRef, ...] = Field(default=(), max_length=200)
    #: Design's real content vocabulary, both nullable (ruling D5a).
    binding_set_ref: str | None = Field(default=None, min_length=1, max_length=500)
    template_revision_ref: str | None = Field(default=None, min_length=1, max_length=500)
    #: The §2.2 mis-exit recovery: re-delegation NAMES the closed leg to reopen it. The same
    #: leg returns ``open_awaiting_user`` with its original bundle and history — context
    #: resumes, and the exit journal record survives. When present, the pin/bundle fields
    #: above are ignored: a reopen is a resumption, not a fresh delegation.
    reopen_leg_id: str | None = Field(default=None, min_length=1, max_length=64)


class OpenDesignLegOutput(ToolOutput):
    leg_id: str
    leg_ref: str
    thread_id: str
    bundle_artifact_key: str
    bundle_sha256: str
    document_id: str | None
    document_version_guard: int | None
    brand_kit_id: str | None
    brand_kit_version: int | None
    created: bool
    #: ``True`` when this call reopened a closed leg (the mis-exit recovery path).
    reopened: bool = False


class _LegRefused(ValueError):
    """One typed refusal, raised by the shared resolution and rendered by both entry points."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _ResolvedDelegation:
    turn: TurnIdentity
    parent_execution_id: UUID
    leg_id: str
    document_id: str | None
    document_version_guard: int | None
    brand_kit_id: str | None
    brand_kit_version: int | None
    existing_leg: dict[str, Any] | None
    bundle_bytes: bytes
    #: The validated CLOSED leg a re-delegation names (§2.2 mis-exit reopen); ``None`` on the
    #: fresh-delegation path.
    reopen_leg: dict[str, Any] | None = None


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


class OpenDesignLegTool(Tool):
    name = "open_design_leg"
    version = "1"
    model_description = (
        "Hand this conversation to the design deepagent: validates the target-document and "
        "brand-kit pins, freezes the delegation bundle (brief, pins, governed claim refs) as one "
        "immutable artifact, and opens the durable design leg. While the leg is open, every user "
        "message on this thread goes directly to Design — you will not see the thread again "
        "until the leg closes. Opening a leg spends nothing and runs no design turn: tell the "
        "user the design session is open and end your turn."
    )
    input_model: ClassVar[type[ToolInput]] = OpenDesignLegInput
    output_model: ClassVar[type[ToolOutput]] = OpenDesignLegOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="one design leg per delegating turn (leg id derived from the turn)",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "document_id",
            "expected_document_version",
            "brand_kit_id",
            "brand_kit_version",
        )
    )
    #: The leg is anchored to one project (through its thread); the C5 step pins that project so
    #: a replayed delegation is judged against the same project revision it was opened under. The
    #: design-side pins (document CAS guard, brand-kit version) are validated by the tool itself
    #: against durable design rows — they have no platform pin kind, and inventing one here would
    #: fork the design substrate's own versioning.
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenDesignLegInput)
        try:
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _LegRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """Opening a leg is free — the spend happens inside governed design turns, later."""

        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenDesignLegInput)
        reopened = False
        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            if resolved.reopen_leg is not None:
                await design_legs.reopen_leg(
                    conn,
                    workspace_id=ctx.workspace_id,
                    leg_id=resolved.leg_id,
                )
                leg = await design_legs.get_leg(
                    conn, workspace_id=ctx.workspace_id, leg_id=resolved.leg_id
                )
                created = False
                reopened = True
            elif resolved.existing_leg is not None:
                leg = resolved.existing_leg
                created = False
            else:
                bundle_ref = await self._artifacts().persist_body(
                    workspace_id=ctx.workspace_id,
                    data=resolved.bundle_bytes,
                    media_type=DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE,
                    project_bindings=((resolved.turn.project_id, "design_delegation_context"),),
                )
                leg = await design_legs.open_leg(
                    conn,
                    workspace_id=ctx.workspace_id,
                    thread_id=resolved.turn.thread_id,
                    parent_execution_id=resolved.parent_execution_id,
                    opened_by_turn_id=resolved.turn.turn_id,
                    bundle_artifact_ref=bundle_ref.artifact_key,
                    document_id=resolved.document_id,
                    document_version_guard=resolved.document_version_guard,
                    brand_kit_id=resolved.brand_kit_id,
                    brand_kit_version=resolved.brand_kit_version,
                    leg_id=resolved.leg_id,
                )
                created = True
        bundle_sha = (
            (await self._bundle_sha(leg["bundle_artifact_ref"], ctx.workspace_id))
            if leg.get("bundle_artifact_ref")
            else ""
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": leg["id"],
                "leg_ref": design_leg_ref(leg["id"]),
                "thread_id": leg["thread_id"],
                "bundle_artifact_key": leg.get("bundle_artifact_ref") or "",
                "bundle_sha256": bundle_sha,
                "document_id": leg.get("document_id"),
                "document_version_guard": leg.get("document_version_guard"),
                "brand_kit_id": leg.get("brand_kit_id"),
                "brand_kit_version": leg.get("brand_kit_version"),
                "created": created,
                "reopened": reopened,
            },
        )

    def _artifacts(self) -> DurableAgentArtifactStore:
        if self._storage is None:  # pragma: no cover - guarded by _resolve
            raise RuntimeError("design leg storage is not configured")
        return DurableAgentArtifactStore(
            storage=self._storage,
            conn_factory=self._conn_factory,
        )

    async def _bundle_sha(self, artifact_key: str, workspace_id: str) -> str:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT content_sha256 FROM artifact "
                        "WHERE storage_key = :key AND workspace_id = :ws"
                    ),
                    {"key": artifact_key, "ws": workspace_id},
                )
            ).first()
        return "" if row is None else str(row[0])

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: OpenDesignLegInput,
        ctx: ToolContext,
    ) -> _ResolvedDelegation:
        """Every check the delegation depends on, run identically by preconditions and invoke."""

        if self._storage is None:
            raise _LegRefused(
                "this deployment has no artifact storage, so no delegation bundle can be "
                "frozen; the design leg cannot open",
                reason_code="design_leg_storage_not_configured",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _LegRefused(str(exc), reason_code="design_leg_turn_ref_malformed") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            raise _LegRefused(
                "no such turn in this workspace",
                reason_code="design_leg_turn_not_found",
            )
        execution_row = (
            await conn.execute(
                text("SELECT execution_id FROM agent_turn WHERE id = :turn AND workspace_id = :ws"),
                {"turn": turn.turn_id, "ws": ctx.workspace_id},
            )
        ).first()
        if execution_row is None:
            raise _LegRefused(
                "the presenting turn has no execution row yet, so the leg has no platform "
                "parent to attach to",
                reason_code="design_leg_turn_execution_missing",
            )
        parent_execution_id = UUID(str(execution_row[0]))

        if inputs.reopen_leg_id is not None:
            return await self._resolve_reopen(
                conn,
                inputs,
                ctx,
                turn=turn,
                parent_execution_id=parent_execution_id,
            )

        leg_id = derive_design_leg_id(workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        try:
            existing = await design_legs.get_leg(conn, workspace_id=ctx.workspace_id, leg_id=leg_id)
        except DesignNotFoundError:
            existing = None
        if existing is not None:
            if existing["state"] == "closed":
                # Practically unreachable (head-of-abm does not run while its own leg is open,
                # and a closed leg means a *later* turn re-delegates) — refused rather than
                # silently reopened; the mis-exit reopen names the leg via ``reopen_leg_id``.
                raise _LegRefused(
                    "this turn's design leg was already closed; a re-delegation reopens it by "
                    "naming it in reopen_leg_id, not by opening it again",
                    reason_code="design_leg_replay_closed",
                )
            return _ResolvedDelegation(
                turn=turn,
                parent_execution_id=parent_execution_id,
                leg_id=leg_id,
                document_id=existing.get("document_id"),
                document_version_guard=existing.get("document_version_guard"),
                brand_kit_id=existing.get("brand_kit_id"),
                brand_kit_version=existing.get("brand_kit_version"),
                existing_leg=existing,
                bundle_bytes=b"",
            )

        open_leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if open_leg is not None:
            raise _LegRefused(
                "this thread already has an open design leg; finish it (or let the user keep "
                "talking to Design) before delegating again",
                reason_code="design_leg_already_open",
            )

        document_version_guard: int | None = None
        if inputs.document_id is not None:
            try:
                document = await get_document(
                    conn, workspace_id=ctx.workspace_id, document_id=inputs.document_id
                )
            except DesignNotFoundError as exc:
                raise _LegRefused(
                    "no such design document in this workspace",
                    reason_code="design_document_not_found",
                ) from exc
            current = int(document.get("current_version") or 0)
            if (
                inputs.expected_document_version is not None
                and inputs.expected_document_version != current
            ):
                raise _LegRefused(
                    f"the document is at version {current}, not "
                    f"{inputs.expected_document_version}; re-read it before delegating",
                    reason_code="design_document_pin_stale",
                )
            document_version_guard = current
        elif inputs.expected_document_version is not None:
            raise _LegRefused(
                "an expected document version without a document id pins nothing",
                reason_code="design_document_pin_incomplete",
            )

        if (inputs.brand_kit_id is None) != (inputs.brand_kit_version is None):
            raise _LegRefused(
                "a brand pin is (brand_kit_id, version) together or absent entirely",
                reason_code="brand_kit_pin_incomplete",
            )
        if inputs.brand_kit_id is not None:
            kit = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM design_brand_kit "
                        "WHERE brand_kit_id = :kit AND version = :version "
                        "AND workspace_id = :ws"
                    ),
                    {
                        "kit": inputs.brand_kit_id,
                        "version": inputs.brand_kit_version,
                        "ws": ctx.workspace_id,
                    },
                )
            ).first()
            if kit is None:
                raise _LegRefused(
                    "no such brand kit version in this workspace — the pin is fail-closed "
                    "(PD-part3 D5), so a missing kit is a refusal, never a default fallback",
                    reason_code="brand_kit_pin_not_found",
                )

        bundle_bytes = _canonical_json(
            _bundle_payload(
                inputs=inputs,
                ctx_workspace_id=ctx.workspace_id,
                turn=turn,
                leg_id=leg_id,
                document_version_guard=document_version_guard,
            )
        )
        if len(bundle_bytes) > DESIGN_DELEGATION_BUNDLE_MAX_BYTES:
            raise _LegRefused(
                f"the delegation bundle is {len(bundle_bytes)} bytes; the hard cap is "
                f"{DESIGN_DELEGATION_BUNDLE_MAX_BYTES} (PD-part3 §2.3 — refs only, trim the "
                "brief or the claim set)",
                reason_code="design_bundle_too_large",
            )
        return _ResolvedDelegation(
            turn=turn,
            parent_execution_id=parent_execution_id,
            leg_id=leg_id,
            document_id=inputs.document_id,
            document_version_guard=document_version_guard,
            brand_kit_id=inputs.brand_kit_id,
            brand_kit_version=inputs.brand_kit_version,
            existing_leg=None,
            bundle_bytes=bundle_bytes,
        )

    async def _resolve_reopen(
        self,
        conn: AsyncConnection,
        inputs: OpenDesignLegInput,
        ctx: ToolContext,
        *,
        turn: TurnIdentity,
        parent_execution_id: UUID,
    ) -> _ResolvedDelegation:
        """§2.2's mis-exit recovery: validate the CLOSED leg this re-delegation names.

        A reopen is a resumption, not a fresh delegation: the original bundle, pins, history
        and parent execution all survive, so the pin/bundle fields of the input are ignored
        and nothing new is frozen. The exit journal record survives by construction (the DAL
        never deletes journal rows).
        """

        assert inputs.reopen_leg_id is not None
        try:
            leg = await design_legs.get_leg(
                conn, workspace_id=ctx.workspace_id, leg_id=inputs.reopen_leg_id
            )
        except DesignNotFoundError as exc:
            raise _LegRefused(
                "no such design leg in this workspace",
                reason_code="design_leg_reopen_not_found",
            ) from exc
        if leg["thread_id"] != turn.thread_id:
            raise _LegRefused(
                "that design leg belongs to another thread; a re-delegation may only reopen "
                "a leg of its own conversation",
                reason_code="design_leg_reopen_wrong_thread",
            )
        if leg["state"] != "closed":
            raise _LegRefused(
                "that design leg is not closed — the user can simply keep talking to Design",
                reason_code="design_leg_reopen_not_closed",
            )
        open_leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if open_leg is not None:
            raise _LegRefused(
                "this thread already has an open design leg; finish it before reopening another",
                reason_code="design_leg_already_open",
            )
        return _ResolvedDelegation(
            turn=turn,
            parent_execution_id=parent_execution_id,
            leg_id=str(leg["id"]),
            document_id=leg.get("document_id"),
            document_version_guard=leg.get("document_version_guard"),
            brand_kit_id=leg.get("brand_kit_id"),
            brand_kit_version=leg.get("brand_kit_version"),
            existing_leg=None,
            bundle_bytes=b"",
            reopen_leg=leg,
        )


def _bundle_payload(
    *,
    inputs: OpenDesignLegInput,
    ctx_workspace_id: str,
    turn: TurnIdentity,
    leg_id: str,
    document_version_guard: int | None,
) -> dict[str, JsonValue]:
    """The §2.3 delegation-bundle schema v1 — refs and stamps, never claim values."""

    return {
        "schema_version": "1",
        "bundle_kind": "design_delegation",
        "workspace_id": ctx_workspace_id,
        "project_id": turn.project_id,
        "thread_id": turn.thread_id,
        "leg_id": leg_id,
        "opened_by_turn_id": str(turn.turn_id),
        "brief": inputs.brief,
        "brand_kit": (
            None
            if inputs.brand_kit_id is None
            else {"brand_kit_id": inputs.brand_kit_id, "version": inputs.brand_kit_version}
        ),
        "target_document": (
            None
            if inputs.document_id is None
            else {
                "document_id": inputs.document_id,
                "version_guard": document_version_guard,
            }
        ),
        "claim_refs": [ref.model_dump(mode="json") for ref in inputs.claim_refs],
        "binding_set_ref": inputs.binding_set_ref,
        "template_revision_ref": inputs.template_revision_ref,
        "turn_contract": {
            "proposal_flow": "propose_accept_reject",
            "clarification_rounds": 1,
        },
    }


class FinishDesignLegInput(ToolInput):
    """The design orchestrator's proposed exit; the engine derives and validates everything."""

    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    #: The §2.2 closed exit vocabulary — no other reason exists.
    reason: Literal["locked", "out_of_scope", "abandoned"]
    #: The leg summary head-of-abm resumes with — what was made (or why the leg ended),
    #: in the user's terms. This is the ONE design artifact the strategy conversation's
    #: history gains; transcripts stay inside the leg.
    summary: str = Field(min_length=1, max_length=4_000)


class FinishDesignLegOutput(ToolOutput):
    leg_id: str
    leg_ref: str
    thread_id: str
    reason: str
    state: str
    journal_id: str
    summary_artifact_key: str
    summary_message_id: str
    redelivered_turn_id: str | None
    created: bool


@dataclass(frozen=True, slots=True)
class _ResolvedExit:
    turn: TurnIdentity
    leg: dict[str, Any] | None
    submission: Any
    #: The already-journaled exit this turn decided (replay); ``None`` on the fresh path.
    replay: dict[str, Any] | None


class FinishDesignLegTool(Tool):
    """The leg-level exit (PD-part3 §2.2) — the ONLY path to ``closed``.

    Reconciliation with the design harness's authorities, verbatim from the spec:
    ``final.json`` / ``finalize_run`` / ``request_clarification`` remain the TURN-level
    outcome contract and are untouched by this tool; a turn can finalize (proposal ready)
    while the leg stays open — that is the normal iteration loop. This tool is what ends the
    *leg*: it validates that the deciding turn is the leg's own, persists the summary as the
    §2.4 hand-back head-of-abm's history gains, journals the decision append-only, flips the
    leg, and — for ``out_of_scope`` — re-submits the **user's own captured message** (never
    model-authored text) as a fresh head-of-abm submission on the same thread, so the user
    never repeats themselves.
    """

    name = "finish_design_leg"
    version = "1"
    model_description = (
        "End the design leg and hand the thread back to the strategy agent. reason=locked "
        "when the user accepted the design; out_of_scope when their last message is not a "
        "design ask (it is re-delivered to the strategy agent verbatim — never rewrite it); "
        "abandoned when the user walked away. The summary is what the strategy agent resumes "
        "with — state what was made or why the leg ended, in the user's terms. Turn-level "
        "finalization (final.json) is unchanged: finishing a turn does not finish the leg; "
        "only this tool does."
    )
    input_model: ClassVar[type[ToolInput]] = FinishDesignLegInput
    output_model: ClassVar[type[ToolOutput]] = FinishDesignLegOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "one journaled exit per deciding design turn (replay returns the recorded exit; "
            "a deliberately reopened leg is never re-closed by a stale retry)"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("reason",))

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, FinishDesignLegInput)
        try:
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _LegRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """Ending a leg spends nothing; it records a decision and re-delivers at most one
        already-captured message."""

        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, FinishDesignLegInput)
        from clue_api.agent_turn_submission import (
            dispatch_next_thread_turn,
            insert_submission,
            submission_context_refs,
            turn_id_for_submission,
        )
        from clue_api.agent_turn_wiring import DbAgentHistoryStore
        from clue_api.design_leg_wiring import design_leg_run_id

        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            if resolved.replay is not None:
                return self._replayed(resolved.replay)
            leg = resolved.leg
            assert leg is not None  # the fresh path always carries the open leg
            leg_id = str(leg["id"])
            turn = resolved.turn
            submission = resolved.submission

            summary_ref = await self._artifacts().persist_body(
                workspace_id=ctx.workspace_id,
                data=inputs.summary.encode(),
                media_type="text/plain",
                project_bindings=((turn.project_id, "design_leg_context"),),
            )
            summary_message_id = uuid5(turn.turn_id, "leg_summary")
            await DbAgentHistoryStore(conn_factory=self._conn_factory).append(
                message_id=summary_message_id,
                turn_id=turn.turn_id,
                workspace_id=ctx.workspace_id,
                thread_id=turn.thread_id,
                role="assistant",
                body_ref=summary_ref,
            )
            document_version: int | None = None
            if leg.get("document_id") is not None:
                try:
                    document = await get_document(
                        conn,
                        workspace_id=ctx.workspace_id,
                        document_id=str(leg["document_id"]),
                    )
                    document_version = int(document.get("current_version") or 0)
                except DesignNotFoundError:
                    document_version = None

            redelivered_turn_id: str | None = None
            pending_ref: str | None = None
            if inputs.reason == "out_of_scope":
                # The user's own captured bytes, re-submitted under a derived identity so a
                # retried close converges on ONE redelivered turn.
                redelivery_key = f"design-leg-redelivery:{leg_id}:{turn.turn_id}"
                redelivered = turn_id_for_submission(
                    workspace_id=ctx.workspace_id,
                    thread_id=turn.thread_id,
                    idempotency_key=redelivery_key,
                )
                context_refs = await submission_context_refs(
                    conn,
                    workspace_id=ctx.workspace_id,
                    turn_id=turn.turn_id,
                )
                await insert_submission(
                    conn,
                    turn_id=redelivered,
                    workspace_id=ctx.workspace_id,
                    project_id=submission.project_id,
                    thread_id=turn.thread_id,
                    submitted_by_user_id=submission.submitted_by_user_id,
                    submitted_via_membership_id=submission.submitted_via_membership_id,
                    onboarding_input_id=submission.onboarding_input_id,
                    message_artifact_key=submission.message_artifact_key,
                    message_sha256=submission.message_sha256,
                    idempotency_key=redelivery_key,
                    context_refs=context_refs,
                )
                redelivered_turn_id = str(redelivered)
                pending_ref = submission.message_artifact_key

            summary_refs: dict[str, JsonValue] = {
                "closing_turn_id": str(turn.turn_id),
                "summary_artifact_key": summary_ref.artifact_key,
                "summary_sha256": summary_ref.sha256,
                "summary_message_id": str(summary_message_id),
                "document_id": leg.get("document_id"),
                "document_version": document_version,
                "redelivered_turn_id": redelivered_turn_id,
            }
            journal_id = await design_legs.close_leg(
                conn,
                workspace_id=ctx.workspace_id,
                leg_id=leg_id,
                reason=inputs.reason,
                summary_refs=summary_refs,
                pending_user_message_ref=pending_ref,
                decided_by_run_id=design_leg_run_id(turn.turn_id),
            )
            if redelivered_turn_id is not None:
                # The leg is closed in this transaction, so the redelivered turn routes to
                # head-of-abm. Offering is a no-op while this thread's own task is in flight
                # (the worker dispatches again after it finishes) — safe from either caller.
                await dispatch_next_thread_turn(
                    conn,
                    workspace_id=ctx.workspace_id,
                    thread_id=turn.thread_id,
                )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": leg_id,
                "leg_ref": design_leg_ref(leg_id),
                "thread_id": turn.thread_id,
                "reason": inputs.reason,
                "state": "closed",
                "journal_id": journal_id,
                "summary_artifact_key": summary_ref.artifact_key,
                "summary_message_id": str(summary_message_id),
                "redelivered_turn_id": redelivered_turn_id,
                "created": True,
            },
        )

    def _replayed(self, journal: dict[str, Any]) -> ToolResult:
        refs = journal["summary_refs"]
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "leg_id": str(journal["leg_id"]),
                "leg_ref": design_leg_ref(str(journal["leg_id"])),
                "thread_id": str(journal["thread_id"]),
                "reason": str(journal["reason"]),
                "state": "closed",
                "journal_id": str(journal["id"]),
                "summary_artifact_key": str(refs.get("summary_artifact_key") or ""),
                "summary_message_id": str(refs.get("summary_message_id") or ""),
                "redelivered_turn_id": refs.get("redelivered_turn_id"),
                "created": False,
            },
        )

    def _artifacts(self) -> DurableAgentArtifactStore:
        if self._storage is None:  # pragma: no cover - guarded by _resolve
            raise RuntimeError("design leg storage is not configured")
        return DurableAgentArtifactStore(
            storage=self._storage,
            conn_factory=self._conn_factory,
        )

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: FinishDesignLegInput,
        ctx: ToolContext,
    ) -> _ResolvedExit:
        """Every check the exit depends on, run identically by preconditions and invoke."""

        from clue_api.agent_turn_submission import get_submission

        if self._storage is None:
            raise _LegRefused(
                "this deployment has no artifact storage, so no leg summary can be "
                "persisted; the design leg cannot close",
                reason_code="design_leg_storage_not_configured",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _LegRefused(str(exc), reason_code="design_leg_turn_ref_malformed") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            raise _LegRefused(
                "no such turn in this workspace",
                reason_code="design_leg_turn_not_found",
            )
        # Replay first, and deliberately BEFORE the open-leg read: a stale retry of a close
        # whose leg was since deliberately reopened must replay the original decision, never
        # close the reopened leg a second time.
        journal = (
            (
                await conn.execute(
                    text(
                        "SELECT j.id, j.leg_id, j.reason, j.summary_refs, l.thread_id "
                        "FROM design_leg_exit_journal j "
                        "JOIN design_leg l ON l.id = j.leg_id "
                        "AND l.workspace_id = j.workspace_id "
                        "WHERE j.workspace_id = :ws "
                        "AND j.summary_refs->>'closing_turn_id' = :turn"
                    ),
                    {"ws": ctx.workspace_id, "turn": str(turn.turn_id)},
                )
            )
            .mappings()
            .one_or_none()
        )
        if journal is not None:
            refs = journal["summary_refs"]
            if isinstance(refs, (str, bytes)):
                refs = json.loads(refs)
            return _ResolvedExit(
                turn=turn,
                leg=None,
                submission=None,
                replay={
                    "id": journal["id"],
                    "leg_id": journal["leg_id"],
                    "reason": journal["reason"],
                    "thread_id": journal["thread_id"],
                    "summary_refs": refs,
                },
            )

        leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id
        )
        if leg is None:
            raise _LegRefused(
                "this thread has no open design leg to finish",
                reason_code="design_leg_not_open",
            )
        turn_row = (
            (
                await conn.execute(
                    text(
                        "SELECT role, parent_execution_id FROM agent_turn "
                        "WHERE id = :turn AND workspace_id = :ws"
                    ),
                    {"turn": turn.turn_id, "ws": ctx.workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            turn_row is None
            or turn_row["role"] != "design"
            or str(turn_row["parent_execution_id"]) != str(leg["parent_execution_id"])
        ):
            raise _LegRefused(
                "only the leg's own design turn may finish it — this turn is not a design "
                "turn of this leg",
                reason_code="design_leg_exit_wrong_turn",
            )
        submission = await get_submission(conn, workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        if submission is None:
            raise _LegRefused(
                "the deciding design turn has no durable submission, so there is no user "
                "message to carry back",
                reason_code="design_leg_exit_no_user_message",
            )
        return _ResolvedExit(turn=turn, leg=leg, submission=submission, replay=None)


def build_design_leg_tools(
    *,
    conn_factory: ConnFactory = transaction,
    storage: StorageBackend | None = None,
) -> tuple[Tool, ...]:
    """The design-leg tool set, registered unconditionally (the C6 audit is exact set equality).

    Without a storage backend both tools refuse ``design_leg_storage_not_configured`` before
    any write — present-but-refusing, the same posture as the design write tools.
    """

    return (
        OpenDesignLegTool(conn_factory=conn_factory, storage=storage),
        FinishDesignLegTool(conn_factory=conn_factory, storage=storage),
    )
