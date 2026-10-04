"""C6.4 real-framework tools, honest finalization, and durable turn-loop composition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from langchain.tools import ToolRuntime
from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from pydantic_core import to_jsonable_python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentPlanRejected,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    ArtifactRef,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    DelegatedFileGrant,
    DomainObjectRef,
    FinalizeStatus,
    GovernedOperationReceipt,
    ResolvedAgentProfile,
    SpecialistTaskEnvelope,
    VersionedWriteOutcome,
)
from clue_agents.contracts import (
    MODEL_FORBIDDEN_AUTHORITY_KEYS,
    PlanDelegationStep,
    PlanToolStep,
    ReasonCode,
    StableId,
    normalize_virtual_path,
)
from clue_agents.tool_recovery import MAX_TOOL_REPAIR_ROUNDS
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus, ModelCostSource
from clue_agents.workspace import AgentWorkspaceLease
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
)
from clue_api.agent_turn_wiring import (
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.chat.turn_stream import TurnStreamCallbackHandler, TurnStreamEmitter
from clue_api.client_context_authority import trusted_client_kb_version_fields
from clue_api.client_knowledge_privacy import stream_tool_receipt
from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_api.product_context_authority import (
    product_scope_from_constitution,
    trusted_product_scope_fields,
)
from clue_api.product_knowledge_privacy import stream_product_tool_receipt
from clue_api.provider_incidents import record_failure, record_success
from clue_api.turn_binding import trusted_turn_fields
from clue_core.provider_failures import classify_exception, failure_code
from clue_db import ConnFactory, transaction
from clue_gateway.metadata import ANSWERING_MODEL_KEY, cost_cents_from_metadata
from clue_obs import get_logger
from clue_obs.langfuse import LangfuseRunRegistry, guardrail, propagate_trace
from clue_toolbelt import ToolEffectClass, ToolRegistry

#: What a document the turn *wrote* is called in the finalization's ``domain_refs``. One type for
#: every document, because the mount no longer decides what a document *is*: the agent writes any
#: markdown path under ``project/``, the document says in its own front matter what it is, and the
#: card is titled from that (founder ruling 2026-09-14). The two older types
#: (``project_icp_document`` / ``project_persona_document``) survive only where plan-3 receipts are
#: read back — see ``conversation_turns._LEGACY_DOCUMENT_TITLES``.
PROJECT_DOCUMENT_OBJECT_TYPE = "project_document"

__all__ = [
    "PROJECT_DOCUMENT_OBJECT_TYPE",
    "AgentFinalizationAuthority",
    "DurableAgentModelCallHandler",
    "DurableDeepAgentTurnRunner",
    "DelegateSpecialistRequest",
    "GovernedAgentToolFactory",
    "GovernedToolFailure",
    "ModelFinalizeRequest",
]

log = get_logger("clue_api.agent_runtime_wiring")

_DIRECT_PLAN_NAMESPACE = UUID("2d1e7d31-46cd-52cc-968b-eb7cfcd48720")
_FINALIZATION_NAMESPACE = UUID("085e19d4-e1f5-56a0-9d64-7779a7d1cf6f")

_GOVERNED_TOOL_REPAIR_HELP = (
    "No successful receipt was returned. Preserve successful sibling results. Correct what "
    "the reasons name and retry only the failed work. For an executed failed attempt, supply "
    "its node_key in retry_of (include earlier failed attempts of that same work too). "
    "Plan rejections have no execution node: omit retry_of for them. Do not claim success "
    "without a receipt; a late infrastructure error may occur after tool effects."
)


def _stable_error_code(error: BaseException) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()
    return value or "model_call_failed"


def resolve_model_call_role(
    response_metadata: Mapping[str, Any], *, constitution_role: AgentRole
) -> AgentRole:
    """P3.2 per-call attribution: the governed model's ``clue_role`` label when the
    instance is role-labelled (the design trio runs three roles inside ONE turn, so the
    turn's role is not enough), else the turn's constitution role. An unknown label
    falls back to the constitution role — the recording path never fails on
    attribution."""
    label = response_metadata.get("clue_role")
    if isinstance(label, str):
        try:
            return AgentRole(label)
        except ValueError:
            return constitution_role
    return constitution_role


class DurableAgentModelCallHandler(AsyncCallbackHandler):
    """Persist model bodies as artifacts and append a body-free call receipt."""

    def __init__(
        self,
        *,
        request: AgentTurnRequest,
        requested_model: str,
        initial_sequence: int,
        artifacts: DurableAgentArtifactStore,
        turns: DbAgentTurnJournal,
        langfuse_ids: LangfuseRunRegistry | None = None,
        incidents_conn_factory: ConnFactory | None = None,
    ) -> None:
        self._request = request
        self._requested_model = requested_model
        self._next_sequence = initial_sequence
        self._artifacts = artifacts
        self._turns = turns
        self._langfuse_ids = langfuse_ids
        # None where no database is in reach (the unit-test handler): the receipt still names the
        # refusal, only the durable incident is skipped.
        self._incidents_conn_factory = incidents_conn_factory
        self._lock = asyncio.Lock()
        self._pending: dict[UUID, tuple[int, datetime, float, ArtifactRef]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized
        owner = (kwargs.get("metadata") or {}).get("agent_execution_id")
        if owner is not None and owner != str(self._request.constitution.execution_id):
            return
        workspace_id = self._request.constitution.workspace_id
        body = json.dumps(
            [[message.model_dump(mode="json") for message in batch] for batch in messages],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode()
        input_ref = await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=body,
            media_type="application/vnd.clue.agent-model-input+json",
        )
        async with self._lock:
            sequence = self._next_sequence
            self._next_sequence += 1
            self._pending[run_id] = (
                sequence,
                datetime.now(UTC),
                time.monotonic(),
                input_ref,
            )

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return  # An inherited parent handler does not own the child's model call.
        generation = response.generations[0][0]
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        input_details = usage.get("input_token_details") or {}
        cache_read_tokens = int(
            input_details.get("cache_read", input_details.get("cached_tokens", 0))
        )
        cache_creation_tokens = int(
            input_details.get("cache_creation", input_details.get("cache_write", 0))
        )
        response_metadata = getattr(message, "response_metadata", None) or {}
        llm_output = response.llm_output or {}
        # Lane 3 slice 3: the gateway's own stamp is the served model (fallback-aware, stamped
        # once per stream); the provider's field is the fallback for a call that reached us
        # without one.
        answering_model = str(
            response_metadata.get(ANSWERING_MODEL_KEY)
            or llm_output.get("model_name")
            or response_metadata.get("model_name")
            or response_metadata.get("model")
            or self._requested_model
        )
        role = resolve_model_call_role(
            response_metadata, constitution_role=self._request.constitution.role
        )
        # Lane 3 slice 1: what this call cost, as the gateway measured it. The shared reader is
        # the only parse of the stamp, so this ledger and the ARV2 research ledger can never
        # disagree about what ``metered``/``estimate``/``unpriced`` mean. Cents arrive as a
        # Decimal; USD is the unit every cost read reports in, at the column's six places.
        cents, cost_source = cost_cents_from_metadata(response_metadata)
        cost_usd = None if cents is None else (cents / Decimal(100)).quantize(Decimal("0.000001"))
        output_ref = await self._artifacts.persist_body(
            workspace_id=self._request.constitution.workspace_id,
            data=response.model_dump_json().encode(),
            media_type="application/vnd.clue.agent-model-output+json",
        )
        await self._record(
            run_id=run_id,
            pending=pending,
            status=AgentModelCallStatus.COMPLETED,
            answering_model=answering_model,
            input_tokens=int(usage.get("input_tokens", 0)),
            cache_read_input_tokens=cache_read_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
            output_tokens=int(usage.get("output_tokens", 0)),
            output_ref=output_ref,
            role=role,
            cost_usd=cost_usd,
            cost_source=cost_source,
        )
        # The provider served us: whatever it was refusing or failing at is over.
        await self._with_incidents(
            lambda conn: record_success(conn, "openrouter", now=datetime.now(UTC)),
            what="close",
        )

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return
        # What the provider did, when it is the provider that did something: a refusal or a
        # fault is named ``provider_refused|failed:<provider>:<reason>`` on the receipt, so the
        # row, the turn's failure code and the incident all read the same sentence. Anything the
        # provider did not cause keeps the class-name code it always had.
        failure = classify_exception("openrouter", error)
        await self._record(
            run_id=run_id,
            pending=pending,
            status=AgentModelCallStatus.FAILED,
            # No response reached us, so no per-call clue_role exists; the turn's
            # constitution role is the truthful attribution for a failed call.
            role=self._request.constitution.role,
            answering_model=None,
            error_code=failure_code(failure) if failure is not None else _stable_error_code(error),
        )
        # After the receipt, never before: the recorder counts this provider's recent failures
        # out of the ledgers, and this call's own row has to be one of them (ruling PI-4).
        if failure is not None:
            await self._with_incidents(
                lambda conn: record_failure(
                    conn,
                    failure,
                    surface="chat_turn",
                    workspace_id=self._request.constitution.workspace_id,
                    now=datetime.now(UTC),
                ),
                what="open",
            )

    async def _with_incidents(
        self, action: Callable[[AsyncConnection], Awaitable[object]], *, what: str
    ) -> None:
        """Run one incident write, or none, and never raise into the callback that observes it.

        The recorder swallows its own errors, but opening the connection is outside it: a
        database that refuses a connection must not fail a model call that otherwise worked.
        With no factory (the unit-test handler) there is nothing to write and nothing to say.
        """
        if self._incidents_conn_factory is None:
            return
        try:
            async with self._incidents_conn_factory() as conn:
                await action(conn)
        except Exception:
            log.exception(
                "provider_incident.recorder_failed",
                what=what,
                turn_id=str(self._request.turn_id),
            )

    async def _record(
        self,
        *,
        run_id: UUID,
        pending: tuple[int, datetime, float, ArtifactRef],
        status: AgentModelCallStatus,
        answering_model: str | None,
        role: AgentRole,
        input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        output_tokens: int = 0,
        error_code: str | None = None,
        output_ref: ArtifactRef | None = None,
        cost_usd: Decimal | None = None,
        cost_source: ModelCostSource | None = None,
    ) -> None:
        sequence, started_at, started_clock, input_ref = pending
        langfuse = self._langfuse_ids.pop(run_id) if self._langfuse_ids is not None else None
        receipt = AgentModelCallReceipt(
            model_call_id=run_id,
            turn_id=self._request.turn_id,
            execution_id=self._request.constitution.execution_id,
            workspace_id=self._request.constitution.workspace_id,
            sequence=sequence,
            requested_model=self._requested_model,
            answering_model=answering_model,
            status=status,
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            output_tokens=output_tokens,
            # cost_millicredits stays 0 by decision (P3.2, PD-part3 delta 6): converting cents
            # to credits is the uncomposed credits milestone's policy, and inventing a rate here
            # would create a second cost authority. The USD beside it is NOT a conversion — it is
            # the gateway's own measurement (clue_cost_cents), read by the shared reader, so the
            # conversation-turn ledger and the ARV2 research ledger record the same fact the same
            # way (lane 3 slice 1).
            cost_millicredits=0,
            cost_usd=cost_usd,
            cost_source=cost_source,
            latency_ms=(time.monotonic() - started_clock) * 1000,
            error_code=error_code,
            role=role,
            langfuse_trace_id=langfuse.trace_id if langfuse is not None else None,
            langfuse_observation_id=langfuse.observation_id if langfuse is not None else None,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        await self._turns.record_model_call(
            receipt=receipt,
            input_ref=input_ref,
            output_ref=output_ref,
        )


class _ModelInput(BaseModel):
    # Tool arguments arrive as JSON, so arrays must validate into immutable tuples. Authority
    # fields remain forbidden or injected; accepting JSON representation is not authority
    # coercion.
    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)


class GovernedToolFailure(BaseModel):
    """The refusal of one governed invocation, shaped for the model that must repair it.

    A governed tool returns its :class:`GovernedOperationReceipt` as JSON when the operation
    commits. A refusal is the same kind of answer — a bounded, typed, reference-only statement of
    what the platform did — so it is returned the same way rather than raised. Raising killed the
    LangGraph run and the model was never told why (the live Stage-0 defect: a paraphrased claim
    value failed the interview verifier and the turn ended ``runtime_error`` in silence).

    ``recorded`` means no successful governed receipt was returned, not a guarantee of rollback.
    Failed attempts remain auditable; late infrastructure errors may follow durable tool effects.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    governed_repair_budgeted: bool = True
    error: Literal["plan_rejected", "operation_failed"]
    address: str
    node_key: str
    recorded: Literal[False] = False
    reasons: tuple[str, ...]
    guidance: str = _GOVERNED_TOOL_REPAIR_HELP


class ModelFinalizeRequest(_ModelInput):
    """Model-controlled final content only; trusted identity/time/output snapshots are injected."""

    status: FinalizeStatus
    user_message: str | None = Field(default=None, max_length=65_536)
    domain_refs: tuple[DomainObjectRef, ...] = ()
    open_gate_refs: tuple[DomainObjectRef, ...] = ()
    assumptions: tuple[str, ...] = Field(default=(), max_length=64)
    next_actions: tuple[str, ...] = Field(default=(), max_length=64)
    # The envelope's own alias, not a copy of its pattern. A hand-copied constraint is the exact
    # drift hazard this contract-parity work exists to close: tightening ``ReasonCode`` would
    # silently leave the model boundary looser again, and the model would once more be told yes
    # about a code the durable envelope refuses.
    failure_code: ReasonCode | None = None

    @model_validator(mode="after")
    def terminal_shape_is_honest(self) -> ModelFinalizeRequest:
        """Mirror :meth:`AgentFinalizeEnvelope.terminal_shape_is_honest` at the model boundary.

        The model-facing shape must be *at least* as strict as the durable envelope. When it is
        looser the model gets a green light for a proposal the envelope will refuse, and the turn
        dies inside envelope construction — the live Stage-0 defect (``awaiting_input`` carrying a
        ``failure_code``). Every rule the envelope enforces on a field the model actually supplies
        is restated here so the refusal happens where the model can still see and repair it.

        Two envelope rules are checked against their model-side *source*: the envelope's
        ``user_message_artifact_ref`` is persisted from ``user_message``, and its
        ``next_action_refs`` are persisted from ``next_actions`` — or, when a non-terminal turn
        supplies neither an explicit next action nor an open gate, from the ``user_message`` that
        already states what the human must do (the deliberate repair in ``_finalize_tool``). Rules
        over trusted injected fields (``output_refs``, identity, time) stay envelope-only: the
        model does not supply them, so there is nothing honest to check here.
        """

        if self.status is FinalizeStatus.FAILED:
            if self.failure_code is None:
                raise ValueError("status 'failed' must carry a stable snake_case failure_code")
        elif self.failure_code is not None:
            raise ValueError(
                f"status {self.status.value!r} cannot carry a failure_code; only 'failed' may"
            )
        if self.status is FinalizeStatus.COMPLETED and self.user_message is None:
            raise ValueError("status 'completed' must carry a user_message")
        if self.status in {FinalizeStatus.AWAITING_INPUT, FinalizeStatus.BLOCKED} and not (
            self.open_gate_refs or self.next_actions or self.user_message
        ):
            raise ValueError(
                f"status {self.status.value!r} must identify what it is waiting for: supply "
                "next_actions, open_gate_refs, or a user_message that asks for it"
            )
        return self


# A surface-specific veto over a *non-failing* terminal proposal, invoked for ``completed`` and
# ``awaiting_input`` (the two statuses that tell the human the turn did its job). It receives the
# whole proposal, so a guard that only governs one of them checks ``status`` itself; ``failed`` and
# ``blocked`` are never gated, because an honest failure must not be forced through work it could
# not do. A guard refuses by raising ``ValueError``, which the runtime's bounded finalize repair
# turns into visible model feedback before the turn fails closed.
CompletionGuard = Callable[[ModelFinalizeRequest], Awaitable[None]]

_GUARDED_STATUSES = frozenset({FinalizeStatus.COMPLETED, FinalizeStatus.AWAITING_INPUT})


class ModelDomainRef(_ModelInput):
    """Model-selected identity only; trusted workspace scope is injected."""

    object_type: str = Field(min_length=1, max_length=128)
    object_id: str = Field(min_length=1, max_length=255)
    version: int | None = Field(default=None, ge=1)


class DelegateSpecialistRequest(_ModelInput):
    """Small typed proposal accepted by the governed specialist delegation tool."""

    role: Literal[
        "research", "content_drafter", "reviewer", "research_claims", "research_narrative"
    ]
    goal: str = Field(min_length=1, max_length=2_048)
    instructions: str = Field(min_length=1, max_length=8_192)
    verbatim_context: tuple[str, ...] = Field(default=(), max_length=16)
    canonical_paths: tuple[str, ...] = Field(
        default=(),
        max_length=32,
        description="Existing local workspace files to copy. Research specialists already have "
        "scoped /research and /evidence views; mention those paths in instructions, not here.",
    )
    domain_refs: tuple[ModelDomainRef, ...] = Field(default=(), max_length=64)

    @field_validator("canonical_paths")
    @classmethod
    def paths_are_relative_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_virtual_path(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("canonical delegation paths must be unique")
        return normalized

    @model_validator(mode="after")
    def bounded_verbatim_context(self) -> DelegateSpecialistRequest:
        if any(not item or len(item) > 16_384 for item in self.verbatim_context):
            raise ValueError("verbatim context items must contain 1..16384 characters")
        return self


def _with_written_documents(
    declared: Sequence[DomainObjectRef],
    *,
    written: Sequence[VersionedWriteOutcome],
    workspace_id: str,
) -> tuple[DomainObjectRef, ...]:
    """Add the documents this turn actually wrote to the refs the model declared.

    A write into the versioned ``project/`` mount is a durable, human-visible event that the model
    has no way to cite: it typed a file path, and what came back was a *version* of a document it
    never named. So the turn says it on the model's behalf, from the outcomes the backend recorded
    — the card the human sees is then built from the rows the turn wrote, not from a claim the
    model remembered to make.

    The model's own refs keep their places and come first: it may legitimately point at objects it
    only read, and this is an addition, never a replacement. Deduplication is on the whole identity
    ``(object_type, object_id, version)``, so a model that *did* cite its write gets one card, and
    a turn that wrote the same document twice contributes one ref per version it minted.

    Every written document becomes a ref. There is no kind this surface refuses to name: a document
    the agent judged worth writing is a document the human is shown, titled by the document itself.
    """

    merged: dict[tuple[str, str, int | None], DomainObjectRef] = {}
    for ref in declared:
        merged.setdefault((ref.object_type, ref.object_id, ref.version), ref)
    for outcome in written:
        key = (PROJECT_DOCUMENT_OBJECT_TYPE, str(outcome.document_id), outcome.version)
        merged.setdefault(
            key,
            DomainObjectRef(
                workspace_id=workspace_id,
                object_type=PROJECT_DOCUMENT_OBJECT_TYPE,
                object_id=str(outcome.document_id),
                version=outcome.version,
                # The document's own title, so the card the human sees says what the document says
                # it is rather than "project document".
                title=outcome.title,
            ),
        )
    return tuple(merged.values())


def _with_trusted_runtime(
    model: type[BaseModel],
    *,
    name: str,
    allow_repair: bool = False,
) -> type[BaseModel]:
    """Add LangGraph's injected runtime and hide trusted authority from the model-visible schema.

    A tool input model may legitimately declare an authority field (the Stage-0 tools declare
    ``project_id``), but the model never gets to choose one: ``PlanToolStep.arguments`` rejects
    every :data:`MODEL_FORBIDDEN_AUTHORITY_KEYS` name outright, and the executor serves the value
    from the trusted :class:`~clue_agents.contracts.AgentConstitution`. Leaving those fields on
    the model-visible schema is not merely redundant — it breaks the tool, because
    ``StructuredTool`` materializes *every* defaulted field into the kwargs it hands the
    coroutine, so an untouched ``project_id=None`` would reach the plan step and trip the
    forbidden-authority guard on a call the model made correctly.

    The same removal covers per-turn authority: a field marked
    :data:`~clue_api.turn_binding.TRUSTED_TURN_FIELD` is
    served from the captured-turn binding at the execution seam (``clue_api.turn_binding``), so
    ``record_interview_answer``'s ``onboarding_input_id``, ``artifact_key`` and captured ``answer``
    body leave the model surface entirely. The two sets differ only in where the trusted value
    comes from — the constitution for the whole execution, the captured turn for this one turn.

    Removing them keeps ``extra='forbid'`` doing the honest thing: a model that invents
    ``project_id`` anyway gets an ordinary validation error it can see and react to, rather than
    a crash deep in plan construction. Field removal (rather than rebuilding the model from its
    surviving fields) preserves the source model's own field and model validators.
    """

    config = dict(model.model_config)
    config["arbitrary_types_allowed"] = True
    subclass = cast(
        type[BaseModel],
        type(
            name,
            (model,),
            {
                "__module__": __name__,
                "__annotations__": {
                    "runtime": ToolRuntime,
                    **({"retry_of": tuple[StableId, ...]} if allow_repair else {}),
                },
                **(
                    {
                        "retry_of": Field(
                            default=(),
                            description=(
                                "Corrected retry only: node_key values of earlier failed attempts "
                                "for this work and tool. Success resolves those failures; "
                                "omit for new work and plan_rejected feedback."
                            ),
                        )
                    }
                    if allow_repair
                    else {}
                ),
                "model_config": cast(ConfigDict, config),
            },
        ),
    )
    trusted = (
        MODEL_FORBIDDEN_AUTHORITY_KEYS
        | set(trusted_turn_fields(model))
        | set(trusted_client_kb_version_fields(model))
        | set(trusted_product_scope_fields(model))
    )
    hidden = trusted & set(subclass.__pydantic_fields__)
    if hidden:
        for key in hidden:
            del subclass.__pydantic_fields__[key]
        subclass.model_rebuild(force=True)
    return subclass


def _json_arguments(kwargs: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Render LangChain-validated tool kwargs as the pure JSON a durable plan step admits.

    ``StructuredTool`` hands the coroutine *validated* values — a nested ``BaseModel`` stays a
    model instance, an enum stays an enum member, ``UUID``/``Decimal``/``datetime`` stay rich
    Python objects — while :class:`~clue_agents.contracts.PlanToolStep.arguments` is
    ``dict[str, JsonValue]``. Without this seam every governed tool carrying a nested model dies
    with ``input was not a valid JSON value`` on a semantically correct model call.

    The conversion is a pure re-representation, never a repair: ``to_jsonable_python`` raises on
    a value with no JSON representation, so a malformed argument still fails loudly here instead
    of being laundered into the plan. Round-tripping through the tool's own args model is
    deliberately *not* used — that model is the ``_with_trusted_runtime`` subclass carrying the
    injected, unserializable ``runtime`` object, and dumping it would either fail or leak trusted
    authority into model-proposed arguments. (``runtime`` binds to the coroutine's own parameter,
    so it never reaches ``kwargs``; only model-controlled fields are normalized.) The executor
    re-validates these arguments into the tool's ``input_model``, which accepts the JSON
    representation.
    """

    return cast(dict[str, JsonValue], to_jsonable_python(dict(kwargs)))


class AgentFinalizationAuthority:
    """The only transition from a model proposal to an authoritative terminal turn."""

    def __init__(
        self,
        *,
        lease: AgentWorkspaceLease,
        artifacts: DurableAgentArtifactStore,
        turns: DbAgentTurnJournal,
        crash_hook: AgentExecutionCrashHook,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._lease = lease
        self._artifacts = artifacts
        self._turns = turns
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory

    async def finalize(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        envelope: AgentFinalizeEnvelope,
    ) -> ArtifactRef:
        if envelope.execution_id != self._lease.identity.execution_id:
            raise ValueError("finalization crosses the workspace execution")
        if workspace_id != self._lease.identity.workspace_id:
            raise ValueError("finalization crosses the workspace identity")
        existing = await self._existing(
            envelope=envelope,
            workspace_id=workspace_id,
        )
        if existing is not None:
            await self._turns.record_workspace_usage(
                turn_id=turn_id,
                workspace_id=workspace_id,
                usage=self._lease.usage_snapshot(),
            )
            self._lease.authorize_cleanup(finalization_ref=existing)
            return existing
        # Snapshot-then-empty: the first call of the turn persists and clears ``outputs/``
        # for the thread's next turn, and any later call returns that same single-flight
        # answer, so the two sites agree without re-walking an emptied folder.
        expected_outputs = tuple(await self._lease.backend.snapshot_outputs(empty_after=True))
        if envelope.output_refs != expected_outputs:
            raise ValueError("finalization outputs differ from the frozen workspace snapshot")
        await self._turns.record_workspace_usage(
            turn_id=turn_id,
            workspace_id=workspace_id,
            usage=self._lease.usage_snapshot(),
        )
        refs = (
            *((envelope.user_message_artifact_ref,) if envelope.user_message_artifact_ref else ()),
            *envelope.output_refs,
            *envelope.assumption_refs,
            *envelope.next_action_refs,
        )
        for ref in refs:
            await self._artifacts.read(ref)
        await self._crash_hook(
            "artifact_store",
            execution_id=envelope.execution_id,
            node_key=None,
        )
        envelope_ref = await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=envelope.model_dump_json(exclude_none=False).encode(),
            media_type="application/vnd.clue.agent-finalization+json",
        )
        await self._turns.record_finalization(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
        )
        await self._crash_hook(
            "finalize_event",
            execution_id=envelope.execution_id,
            node_key=None,
        )
        await self._turns.commit_finalization_authority(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
            envelope_ref=envelope_ref,
        )
        await self._crash_hook(
            "cursor_update",
            execution_id=envelope.execution_id,
            node_key=None,
        )
        self._lease.authorize_cleanup(finalization_ref=envelope_ref)
        return envelope_ref

    async def _existing(
        self,
        *,
        envelope: AgentFinalizeEnvelope,
        workspace_id: str,
    ) -> ArtifactRef | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT c.finalization_id, c.envelope_artifact_key,
                                   c.envelope_sha256,
                                   a.media_type, a.size_bytes
                            FROM agent_finalization_commit c
                            JOIN artifact a ON a.storage_key=c.envelope_artifact_key
                            WHERE c.execution_id=:execution AND c.workspace_id=:workspace
                            """
                        ),
                        {
                            "execution": envelope.execution_id,
                            "workspace": workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        expected_sha256 = hashlib.sha256(
            envelope.model_dump_json(exclude_none=False).encode()
        ).hexdigest()
        if (
            row["finalization_id"] != envelope.finalization_id
            or row["envelope_sha256"] != expected_sha256
        ):
            raise ValueError("execution already has a different finalization authority")
        ref = ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=row["envelope_artifact_key"],
            sha256=row["envelope_sha256"],
            media_type=row["media_type"],
            byte_count=int(row["size_bytes"]),
        )
        await self._artifacts.read(ref)
        return ref


class TurnWorkGuard(AsyncCallbackHandler):
    """Admission check shared by model and tool boundaries for one chat turn."""

    raise_error = True

    def __init__(self, check: Callable[[], Awaitable[None]]) -> None:
        self.check = check

    async def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        await self._admit()

    async def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        await self._admit()

    async def _admit(self) -> None:
        try:
            await self.check()
        except BaseException as exc:
            # Lane 3 slice 3: a refused admission is a guardrail in the tree, then the same raise.
            guardrail("turn.work_guard", reason=f"{type(exc).__name__}: {exc}"[:200])
            raise


class GovernedAgentToolFactory:
    """Expose exact effective descriptors plus one trusted honest-finalize mechanism."""

    def __init__(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        registry: ToolRegistry,
        execution: C5AgentExecutionAdapter,
        lease: AgentWorkspaceLease,
        artifacts: DurableAgentArtifactStore,
        required_output_path: str | None = None,
        completion_guard: CompletionGuard | None = None,
        stream: TurnStreamEmitter | None = None,
        before_work: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._before_work = before_work
        self._request = request
        self._resolved_profile = resolved_profile
        self._registry = registry
        self._execution = execution
        self._lease = lease
        self._artifacts = artifacts
        self._required_output_path = required_output_path
        self._completion_guard = completion_guard
        # FI Lane D D3: the live projection of this turn's tool cards. Optional, and absent
        # everywhere but the production conversation — a tool part is a projection of the durable
        # plan operation and its receipt, so it can only ever be emitted from here, where both
        # identities exist.
        self._stream = stream
        # Per-turn state: the factory is constructed once per turn, next to the turn's execution
        # adapter, so this budget is shared across every governed tool the model may call.
        # Repair rounds are checkpointed by ToolRepairRoundsMiddleware, never per-call counters.

    async def _check_work(self) -> None:
        if self._before_work is not None:
            await self._before_work()

    def build(self) -> tuple[BaseTool, ...]:
        tools = tuple(
            self._governed_tool(pin.name, pin.version)
            for pin in self._resolved_profile.profile.tools
            if self._tool_admitted(pin.name, pin.version)
        )
        delegation = (
            (self._delegation_tool(),) if self._resolved_profile.profile.delegation_roles else ()
        )
        return (*tools, *delegation, self._finalize_tool())

    def _tool_admitted(self, name: str, version: str) -> bool:
        """Apply constitution-dependent availability before a tool reaches the model.

        Product-KB reads are profile capabilities but only a selected product with an exact
        ``product_knowledge`` artifact grants their per-turn pin.  Hiding them here makes the
        no-selection/profile-only states honest instead of advertising a tool that can only fail
        during argument restoration.
        """

        descriptor = self._registry.descriptor(name, version)
        if "product_kb" in descriptor.pin_requirements:
            return product_scope_from_constitution(self._request.constitution) is not None
        return True

    def _governed_tool(self, name: str, version: str) -> BaseTool:
        descriptor = self._registry.descriptor(name, version)
        pin = next(
            item
            for item in self._resolved_profile.profile.tools
            if item.name == name and item.version == version
        )

        async def invoke(runtime: ToolRuntime, **kwargs: Any) -> str:
            await self._check_work()
            retry_of = tuple(kwargs.pop("retry_of", ()))
            tool_call_id = str(runtime.tool_call_id)
            call_digest = hashlib.sha256(tool_call_id.encode()).hexdigest()[:24]
            node_key = f"agent_{name}_{call_digest}"
            plan_id = uuid5(
                _DIRECT_PLAN_NAMESPACE,
                f"{self._request.constitution.execution_id}:{node_key}",
            )
            plan = AgentPlan(
                plan_id=plan_id,
                execution_id=self._request.constitution.execution_id,
                role=self._request.constitution.role,
                goal_ref=self._request.user_message_artifact_ref,
                steps=(
                    PlanToolStep(
                        node_key=node_key,
                        tool=pin,
                        arguments=_json_arguments(kwargs),
                        purpose=f"Governed direct invocation of {pin.address}.",
                        retry_of=retry_of,
                    ),
                ),
                proposed_at=self._request.requested_at,
            )
            if self._stream is not None:
                await self._stream.tool_started(
                    node_key=node_key,
                    tool_name=pin.name,
                    tool_version=pin.version,
                    tool_call_id=tool_call_id,
                    arguments=_json_arguments(kwargs),
                )
            try:
                validated = await self._execution.validate_plan(
                    plan=plan,
                    constitution=self._request.constitution,
                )
            except AgentPlanRejected as rejected:
                await self._stream_tool_failed(
                    node_key=node_key,
                    pin=pin,
                    tool_call_id=tool_call_id,
                    error_code="plan_rejected",
                    reasons=tuple(
                        f"{issue.location}: {issue.code}: {issue.message}"
                        for issue in rejected.review.issues
                    ),
                )
                return self._tool_failure(
                    error="plan_rejected",
                    address=pin.address,
                    node_key=node_key,
                    error_type=type(rejected).__name__,
                    reasons=tuple(
                        f"{issue.location}: {issue.code}: {issue.message}"
                        for issue in rejected.review.issues
                    ),
                    runtime=runtime,
                )
            await self._check_work()
            final_progress = None
            async for progress in self._execution.execute(plan=validated):
                final_progress = progress
            if final_progress is None or final_progress.status != "completed":
                failures = final_progress.failures if final_progress is not None else ()
                await self._stream_tool_failed(
                    node_key=node_key,
                    pin=pin,
                    tool_call_id=tool_call_id,
                    error_code="operation_failed",
                    reasons=tuple(
                        f"{failure.error_type}: {failure.message}" for failure in failures
                    ),
                )
                # W10 (2026-09-13): an effect-free read that refuses by precondition — the
                # overview is not written, no claims under that prefix, no discovery run — has
                # answered the question it was asked. It is not a misread argument contract, so
                # it does not spend the repair budget; a parallel fan-out of five such reads
                # killed a live turn.
                honest_read = (
                    descriptor.effect_class is ToolEffectClass.READ
                    and bool(failures)
                    and all(failure.error_type == "PreconditionFailed" for failure in failures)
                )
                return self._tool_failure(
                    error="operation_failed",
                    address=pin.address,
                    node_key=node_key,
                    error_type=(failures[0].error_type if failures else "RuntimeError"),
                    reasons=tuple(
                        f"{failure.error_type}: {failure.message}" for failure in failures
                    )
                    or ("the governed operation did not complete",),
                    runtime=runtime,
                    budgeted=not honest_read,
                )
            recovered = await self._execution.recover(
                execution_id=self._request.constitution.execution_id
            )
            receipts_value = recovered.get("operation_receipts", ())
            if not isinstance(receipts_value, Sequence):
                raise RuntimeError("operation receipts are malformed")
            receipts = tuple(
                item for item in receipts_value if isinstance(item, GovernedOperationReceipt)
            )
            receipt = next(
                (
                    item
                    for item in receipts
                    if getattr(item, "operation_id", None) == validated.operations[0].operation_id
                ),
                None,
            )
            if receipt is None:
                raise RuntimeError("completed governed operation has no durable receipt")
            if self._stream is not None:
                # The card is the receipt — structured refs, never pre-rendered prose (§3.4).
                await self._stream.tool_finished(
                    node_key=node_key,
                    tool_name=pin.name,
                    tool_version=pin.version,
                    tool_call_id=tool_call_id,
                    operation_id=getattr(receipt, "operation_id", None),
                    output=(stream_product_tool_receipt(receipt) or stream_tool_receipt(receipt)),
                )
            return receipt.model_dump_json(exclude_none=True)

        invoke.__name__ = name
        invoke.__doc__ = (
            f"{descriptor.model_description} Trusted identity, operation identity, journaling, "
            "and authority are injected."
        )
        return StructuredTool.from_function(
            coroutine=invoke,
            name=name,
            description=invoke.__doc__,
            args_schema=_with_trusted_runtime(
                descriptor.input_model,
                name=f"{descriptor.input_model.__name__}AgentRuntime",
                allow_repair=True,
            ),
        )

    async def _stream_tool_failed(
        self,
        *,
        node_key: str,
        pin: Any,
        tool_call_id: str,
        error_code: str,
        reasons: tuple[str, ...],
    ) -> None:
        """Project a refused governed invocation onto its tool card, if a stream is attached.

        A refusal is a *durable* fact (the operation's failure record was written and nothing
        committed), so the card must say so rather than sit forever at ``input-available``.
        """

        if self._stream is None:
            return
        await self._stream.tool_failed(
            node_key=node_key,
            tool_name=pin.name,
            tool_version=pin.version,
            tool_call_id=tool_call_id,
            error_code=error_code,
            reasons=reasons,
        )

    def _tool_failure(
        self,
        *,
        error: Literal["plan_rejected", "operation_failed"],
        address: str,
        node_key: str,
        error_type: str,
        reasons: tuple[str, ...],
        runtime: ToolRuntime,
        budgeted: bool = True,
    ) -> str:
        """Return every failure; only the next model boundary may exhaust repair rounds."""
        attempt = runtime.state.get("tool_repair_rounds", 0) + int(budgeted)
        log.warning(
            "agent.tool_repair",
            address=address,
            node_key=node_key,
            error=error,
            error_type=error_type,
            reasons=list(reasons),
            attempt=attempt,
            exhausted=budgeted and attempt > MAX_TOOL_REPAIR_ROUNDS,
            budgeted=budgeted,
        )
        return GovernedToolFailure(
            error=error,
            address=address,
            node_key=node_key,
            reasons=reasons,
            governed_repair_budgeted=budgeted,
        ).model_dump_json()

    def _delegation_tool(self) -> BaseTool:
        output_paths = {
            AgentRole.RESEARCH: "outputs/research-strategy.md",
            AgentRole.CONTENT_DRAFTER: "outputs/content-exemplar.md",
            AgentRole.REVIEWER: "outputs/review-verdict.md",
            AgentRole.RESEARCH_CLAIMS: "outputs/claim-processing.json",
            AgentRole.RESEARCH_NARRATIVE: "outputs/research-narrative.json",
        }

        async def delegate_specialist(runtime: ToolRuntime, **kwargs: Any) -> str:
            await self._check_work()
            model_input = DelegateSpecialistRequest.model_validate(kwargs)
            role = AgentRole(model_input.role)
            if role not in self._resolved_profile.profile.delegation_roles:
                raise ValueError(f"role {role.value!r} is absent from delegated authority")
            workspace_id = self._request.constitution.workspace_id
            canonical_paths = list(model_input.canonical_paths)
            if role in {AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE} and any(
                path.split("/", 1)[0] in {"research", "evidence"} for path in canonical_paths
            ):
                # These are live, revocable views, not files in the parent's private directory.
                # The child's own authority already exposes them. Reject the copy request before
                # touching the physical workspace, and let the parent correct its arguments.
                reason = (
                    "Research specialists already have scoped /research and /evidence views. "
                    "Pass canonical_paths=[] and refer to those views in instructions. "
                    "Only existing local workspace files can be copied."
                )
                digest = hashlib.sha256(str(runtime.tool_call_id).encode()).hexdigest()[:24]
                return self._tool_failure(
                    error="plan_rejected",
                    address="delegate_specialist",
                    node_key=f"delegate_{role.value}_{digest}",
                    error_type="virtual_view_is_not_a_file",
                    reasons=(reason,),
                    runtime=runtime,
                )
            domain_ref_inputs = list(model_input.domain_refs)
            if role is AgentRole.RESEARCH:
                for artifact in self._request.constitution.project_context_artifacts:
                    if artifact.name not in {"account-deep-steering", "research-directive"}:
                        continue
                    context_path = f"context/project/{artifact.name}.json"
                    if context_path not in canonical_paths:
                        canonical_paths.append(context_path)
                    candidate_ref = ModelDomainRef(
                        object_type=artifact.domain_ref.object_type,
                        object_id=artifact.domain_ref.object_id,
                        version=artifact.domain_ref.version,
                    )
                    if candidate_ref not in domain_ref_inputs:
                        domain_ref_inputs.append(candidate_ref)
            file_grants: list[DelegatedFileGrant] = []
            for ordinal, source_path in enumerate(canonical_paths):
                entry = await self._lease.backend.stat_entry(source_path)
                if entry.kind != "file" or entry.sha256 is None:
                    raise ValueError(f"canonical delegation path {source_path!r} is not a file")
                body = (await self._lease.backend.read_text(source_path)).encode()
                suffix = PurePosixPath(source_path).suffix
                if suffix not in self._resolved_profile.profile.workspace.allowed_extensions:
                    raise ValueError(
                        f"canonical delegation path {source_path!r} has a forbidden extension"
                    )
                ref = await self._artifacts.persist_body(
                    workspace_id=workspace_id,
                    data=body,
                    media_type=(
                        "application/json"
                        if suffix == ".json"
                        else "application/yaml"
                        if suffix in {".yaml", ".yml"}
                        else "text/markdown"
                        if suffix == ".md"
                        else "text/plain"
                    ),
                )
                if ref.sha256 != entry.sha256:
                    raise RuntimeError("canonical file changed while delegation was being frozen")
                child_path = f"context/delegated/{ordinal:02d}-{PurePosixPath(source_path).name}"
                file_grants.append(
                    DelegatedFileGrant(
                        source_path=source_path,
                        materialized_path=child_path,
                        artifact_ref=ref,
                    )
                )
            domain_refs = tuple(
                DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type=item.object_type,
                    object_id=item.object_id,
                    version=item.version,
                )
                for item in domain_ref_inputs
            )
            specialist_role = cast(
                Literal[
                    AgentRole.RESEARCH,
                    AgentRole.CONTENT_DRAFTER,
                    AgentRole.REVIEWER,
                    AgentRole.RESEARCH_CLAIMS,
                    AgentRole.RESEARCH_NARRATIVE,
                ],
                role,
            )
            task = SpecialistTaskEnvelope(
                role=specialist_role,
                goal=model_input.goal,
                instructions=model_input.instructions,
                verbatim_context=model_input.verbatim_context,
                file_grants=tuple(file_grants),
                domain_refs=domain_refs,
                required_output_path=output_paths[specialist_role],
            )
            task_ref = await self._artifacts.persist_body(
                workspace_id=workspace_id,
                data=task.model_dump_json(exclude_none=False).encode(),
                media_type="application/vnd.clue.specialist-task+json",
            )
            tool_call_id = str(runtime.tool_call_id)
            call_digest = hashlib.sha256(tool_call_id.encode()).hexdigest()[:24]
            node_key = f"delegate_{role.value}_{call_digest}"
            plan_id = uuid5(
                _DIRECT_PLAN_NAMESPACE,
                f"{self._request.constitution.execution_id}:{node_key}",
            )
            plan = AgentPlan(
                plan_id=plan_id,
                execution_id=self._request.constitution.execution_id,
                role=self._request.constitution.role,
                goal_ref=self._request.user_message_artifact_ref,
                steps=(
                    PlanDelegationStep(
                        node_key=node_key,
                        role=role,
                        task_artifact_ref=task_ref,
                        granted_paths=tuple(item.materialized_path for item in file_grants),
                        domain_refs=domain_refs,
                        purpose=(f"Fresh-wake governed {role.value} specialist task."),
                    ),
                ),
                proposed_at=self._request.requested_at,
            )
            validated = await self._execution.validate_plan(
                plan=plan,
                constitution=self._request.constitution,
            )
            final_progress = None
            async for progress in self._execution.execute(plan=validated):
                final_progress = progress
            if final_progress is None or final_progress.status != "completed":
                raise RuntimeError(f"governed {role.value} delegation failed")
            recovered = await self._execution.recover(
                execution_id=self._request.constitution.execution_id
            )
            receipts_value = recovered.get("operation_receipts", ())
            if not isinstance(receipts_value, Sequence):
                raise RuntimeError("operation receipts are malformed")
            receipt = next(
                (
                    item
                    for item in receipts_value
                    if isinstance(item, GovernedOperationReceipt)
                    and item.operation_id == validated.operations[0].operation_id
                ),
                None,
            )
            if receipt is None:
                raise RuntimeError("completed delegation has no durable receipt")
            return receipt.model_dump_json(exclude_none=True)

        delegate_specialist.__name__ = "delegate_specialist"
        delegate_specialist.__doc__ = (
            "Wake one governed specialist from an exact task, verbatim small context, immutable "
            "canonical-file copies, and typed domain refs. The child has no parent chat history, "
            "must durably write its role-specific output, and returns references only."
        )
        return StructuredTool.from_function(
            coroutine=delegate_specialist,
            name="delegate_specialist",
            description=delegate_specialist.__doc__,
            args_schema=_with_trusted_runtime(
                DelegateSpecialistRequest,
                name="DelegateSpecialistRequestRuntime",
            ),
        )

    def _finalize_tool(self) -> BaseTool:
        async def finalize_turn(runtime: ToolRuntime, **kwargs: Any) -> str:
            del runtime
            await self._check_work()
            model_input = ModelFinalizeRequest.model_validate(kwargs)
            # Every refusal must come before the completion guard writes outputs/ and before the
            # snapshot freezes it; afterwards the repair a refusal asks for cannot be made.
            await self._execution.check_finalizable(status=model_input.status)
            if (
                model_input.status is FinalizeStatus.COMPLETED
                and self._required_output_path is not None
            ):
                entry = await self._lease.backend.stat_entry(self._required_output_path)
                if entry.kind != "file" or entry.byte_count == 0:
                    raise ValueError(
                        "completed specialist turn requires its non-empty role output file"
                    )
            if model_input.status in _GUARDED_STATUSES and self._completion_guard is not None:
                await self._completion_guard(model_input)
            workspace_id = self._request.constitution.workspace_id
            final_message_ref = (
                await self._artifacts.persist_body(
                    workspace_id=workspace_id,
                    data=model_input.user_message.encode(),
                    media_type="text/markdown",
                )
                if model_input.user_message is not None
                else None
            )
            assumption_refs = tuple(
                [
                    await self._artifacts.persist_body(
                        workspace_id=workspace_id,
                        data=value.encode(),
                        media_type="text/plain",
                    )
                    for value in model_input.assumptions
                ]
            )
            # A user-facing question already identifies the requested human action. Providers
            # occasionally omit the redundant ``next_actions`` array even when they correctly
            # choose ``awaiting_input``. Preserve that exact message as the action reference so
            # the honest-finalization envelope remains valid without inventing new content.
            next_actions = model_input.next_actions
            message_is_implicit_next_action = (
                model_input.status in {FinalizeStatus.AWAITING_INPUT, FinalizeStatus.BLOCKED}
                and not model_input.open_gate_refs
                and not next_actions
                and model_input.user_message is not None
            )
            next_action_refs = (
                (final_message_ref,)
                if message_is_implicit_next_action and final_message_ref is not None
                else tuple(
                    [
                        await self._artifacts.persist_body(
                            workspace_id=workspace_id,
                            data=value.encode(),
                            media_type="text/plain",
                        )
                        for value in next_actions
                    ]
                )
            )
            output_refs = tuple(await self._lease.backend.snapshot_outputs(empty_after=True))
            domain_refs = _with_written_documents(
                model_input.domain_refs,
                written=self._lease.backend.written_documents,
                workspace_id=workspace_id,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid5(
                    _FINALIZATION_NAMESPACE,
                    str(self._request.constitution.execution_id),
                ),
                execution_id=self._request.constitution.execution_id,
                status=model_input.status,
                user_message_artifact_ref=final_message_ref,
                output_refs=output_refs,
                domain_refs=domain_refs,
                open_gate_refs=model_input.open_gate_refs,
                assumption_refs=assumption_refs,
                next_action_refs=next_action_refs,
                failure_code=model_input.failure_code,
                finalized_at=self._request.requested_at,
            )
            ref = await self._execution.finalize(envelope=envelope)
            return ref.model_dump_json()

        finalize_turn.__name__ = "finalize_turn"
        # The status rules are stated here, not only enforced in the schema: a plain object
        # schema cannot express "failure_code iff status='failed'", so the model learns the
        # contract from the description and is refused (visibly, with one bounded repair) if it
        # proposes a shape the durable envelope would reject.
        finalize_turn.__doc__ = (
            "Required terminal action. Durably commit the user message, frozen outputs, "
            "typed references, and honest status. Normal model stop is not success. "
            "Status contract, enforced exactly: "
            "'completed' requires user_message and must omit failure_code; "
            "'awaiting_input' and 'blocked' must omit failure_code and must say what is "
            "needed via next_actions, open_gate_refs, or a user_message that asks for it; "
            "'failed' requires a stable failure_code matching ^[a-z0-9_.-]+$ (lowercase, at "
            "most 128 characters). "
            "No status other than 'failed' may carry a failure_code."
        )
        return StructuredTool.from_function(
            coroutine=finalize_turn,
            name="finalize_turn",
            description=finalize_turn.__doc__,
            args_schema=_with_trusted_runtime(
                ModelFinalizeRequest,
                name="ModelFinalizeRequestRuntime",
            ),
            return_direct=True,
        )


class DurableDeepAgentTurnRunner:
    """Journal the real deepagent loop and make every unfinalized outcome visibly failed."""

    def __init__(
        self,
        *,
        runtime: DeepAgentTurnRuntime,
        turns: DbAgentTurnJournal,
        artifacts: DurableAgentArtifactStore,
        before_work: Callable[[], Awaitable[None]] | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._before_work = before_work
        self._runtime = runtime
        self._turns = turns
        self._artifacts = artifacts
        self._conn_factory = conn_factory

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        context: AssembledAgentContext,
        lease: AgentWorkspaceLease,
        tools: Sequence[BaseTool],
        stream: TurnStreamEmitter | None = None,
        backend: object | None = None,
    ) -> AgentTurnOutcome:
        workspace_id = request.constitution.workspace_id
        await self._turns.mark_running(
            turn_id=request.turn_id,
            workspace_id=workspace_id,
        )
        # Lane 3 slice 3: the Langfuse handler reports the graph (agent, nodes, sub-agents,
        # tools, generations); its registry hands each generation's ids to the recorder below.
        # ``None`` when Langfuse is off, so the tuple is then exactly what it was.
        langfuse = build_langfuse_callbacks()
        model_calls = DurableAgentModelCallHandler(
            request=request,
            requested_model=resolved_profile.profile.model.model_id,
            initial_sequence=await self._turns.next_model_call_sequence(turn_id=request.turn_id),
            artifacts=self._artifacts,
            turns=self._turns,
            langfuse_ids=langfuse.registry if langfuse is not None else None,
            incidents_conn_factory=self._conn_factory,
        )
        # FI Lane D D3: attaching the stream handler is also what opts *this* turn into the model's
        # streaming path (the handler is structurally a LangChain streaming consumer). With no
        # stream attached the callback tuple, and therefore the model path, is exactly what it was.
        # The Langfuse handler is a plain BaseCallbackHandler and does not opt the turn in.
        callbacks: tuple[BaseCallbackHandler, ...] = (model_calls,)
        if self._before_work is not None:
            callbacks = (TurnWorkGuard(self._before_work), *callbacks)
        if langfuse is not None:
            callbacks = (*callbacks, langfuse.handler)
        if stream is not None:
            callbacks = (*callbacks, TurnStreamCallbackHandler(emitter=stream))
        constitution = request.constitution
        profile_ref = constitution.profile_ref
        try:
            with propagate_trace(
                trace_name=f"{constitution.role.value.replace('_', '-')}.turn",
                session_id=str(request.thread_id),
                user_id=workspace_id,
                metadata={
                    "project_id": constitution.project_id,
                    "turn_id": request.turn_id,
                    "execution_id": constitution.execution_id,
                    "profile": f"{profile_ref.name}@{profile_ref.version}",
                    "actor_id": constitution.actor_id,
                },
                tags=(constitution.role.value,),
            ):
                outcome = await self._runtime.run(
                    request=request,
                    resolved_profile=resolved_profile,
                    context=context,
                    backend=backend if backend is not None else lease.backend,
                    governed_tools=tools,
                    callbacks=callbacks,
                )
        except BaseException:
            await self._turns.mark_unfinalized(
                turn_id=request.turn_id,
                workspace_id=workspace_id,
                reason_code="agent_cancelled_or_crashed",
                abandoned=True,
            )
            raise
        if outcome.failure_code is not None:
            await self._turns.mark_unfinalized(
                turn_id=request.turn_id,
                workspace_id=workspace_id,
                reason_code=outcome.failure_code,
                abandoned=False,
            )
        return outcome
