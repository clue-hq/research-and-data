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
from typing import Annotated, Any, ClassVar
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
        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            if resolved.existing_leg is not None:
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

        leg_id = derive_design_leg_id(workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        try:
            existing = await design_legs.get_leg(conn, workspace_id=ctx.workspace_id, leg_id=leg_id)
        except DesignNotFoundError:
            existing = None
        if existing is not None:
            if existing["state"] == "closed":
                # Practically unreachable (head-of-abm does not run while its own leg is open,
                # and a closed leg means a *later* turn re-delegates) — refused rather than
                # silently reopened; the mis-exit reopen path is P3.5's re-delegation contract.
                raise _LegRefused(
                    "this turn's design leg was already closed; re-delegation reopens it "
                    "through the finish/reopen contract, not by opening it again",
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


def build_design_leg_tools(
    *,
    conn_factory: ConnFactory = transaction,
    storage: StorageBackend | None = None,
) -> tuple[Tool, ...]:
    """The design-leg tool set, registered unconditionally (the C6 audit is exact set equality).

    Without a storage backend the tool refuses ``design_leg_storage_not_configured`` before any
    write — present-but-refusing, the same posture as the design write tools.
    """

    return (OpenDesignLegTool(conn_factory=conn_factory, storage=storage),)
