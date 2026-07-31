"""C6.4 real-framework tools, honest finalization, and durable turn-loop composition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from langchain.tools import ToolRuntime
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from pydantic_core import to_jsonable_python
from sqlalchemy import text

from clue_agents import (
    AgentFinalizeEnvelope,
    AgentPlan,
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
)
from clue_agents.contracts import (
    MODEL_FORBIDDEN_AUTHORITY_KEYS,
    PlanDelegationStep,
    PlanToolStep,
    ReasonCode,
    normalize_virtual_path,
)
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus
from clue_agents.workspace import AgentWorkspaceLease
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
)
from clue_api.agent_turn_wiring import (
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_db import ConnFactory, transaction
from clue_toolbelt import ToolRegistry

__all__ = [
    "AgentFinalizationAuthority",
    "DurableAgentModelCallHandler",
    "DurableDeepAgentTurnRunner",
    "DelegateSpecialistRequest",
    "GovernedAgentToolFactory",
    "ModelFinalizeRequest",
]

_DIRECT_PLAN_NAMESPACE = UUID("2d1e7d31-46cd-52cc-968b-eb7cfcd48720")
_FINALIZATION_NAMESPACE = UUID("085e19d4-e1f5-56a0-9d64-7779a7d1cf6f")


def _stable_error_code(error: BaseException) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()
    return value or "model_call_failed"


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
    ) -> None:
        self._request = request
        self._requested_model = requested_model
        self._next_sequence = initial_sequence
        self._artifacts = artifacts
        self._turns = turns
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
        del serialized, kwargs
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
        pending = self._pending.pop(run_id)
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
        answering_model = str(
            llm_output.get("model_name")
            or response_metadata.get("model_name")
            or response_metadata.get("model")
            or self._requested_model
        )
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
        )

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        pending = self._pending.pop(run_id)
        await self._record(
            run_id=run_id,
            pending=pending,
            status=AgentModelCallStatus.FAILED,
            answering_model=None,
            error_code=_stable_error_code(error),
        )

    async def _record(
        self,
        *,
        run_id: UUID,
        pending: tuple[int, datetime, float, ArtifactRef],
        status: AgentModelCallStatus,
        answering_model: str | None,
        input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        output_tokens: int = 0,
        error_code: str | None = None,
        output_ref: ArtifactRef | None = None,
    ) -> None:
        sequence, started_at, started_clock, input_ref = pending
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
            cost_millicredits=0,
            latency_ms=(time.monotonic() - started_clock) * 1000,
            error_code=error_code,
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

    role: Literal["research", "content_drafter", "reviewer"]
    goal: str = Field(min_length=1, max_length=2_048)
    instructions: str = Field(min_length=1, max_length=8_192)
    verbatim_context: tuple[str, ...] = Field(default=(), max_length=16)
    canonical_paths: tuple[str, ...] = Field(default=(), max_length=32)
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


def _with_trusted_runtime(
    model: type[BaseModel],
    *,
    name: str,
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
                "__annotations__": {"runtime": ToolRuntime},
                "model_config": cast(ConfigDict, config),
            },
        ),
    )
    hidden = MODEL_FORBIDDEN_AUTHORITY_KEYS & set(subclass.__pydantic_fields__)
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
        expected_outputs = tuple(await self._lease.backend.snapshot_outputs())
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
    ) -> None:
        self._request = request
        self._resolved_profile = resolved_profile
        self._registry = registry
        self._execution = execution
        self._lease = lease
        self._artifacts = artifacts
        self._required_output_path = required_output_path
        self._completion_guard = completion_guard

    def build(self) -> tuple[BaseTool, ...]:
        tools = tuple(
            self._governed_tool(pin.name, pin.version)
            for pin in self._resolved_profile.profile.tools
        )
        delegation = (
            (self._delegation_tool(),) if self._resolved_profile.profile.delegation_roles else ()
        )
        return (*tools, *delegation, self._finalize_tool())

    def _governed_tool(self, name: str, version: str) -> BaseTool:
        descriptor = self._registry.descriptor(name, version)
        pin = next(
            item
            for item in self._resolved_profile.profile.tools
            if item.name == name and item.version == version
        )

        async def invoke(runtime: ToolRuntime, **kwargs: Any) -> str:
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
                raise RuntimeError(f"governed operation {pin.address} failed")
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
            return receipt.model_dump_json(exclude_none=True)

        invoke.__name__ = name
        invoke.__doc__ = (
            f"Invoke exact governed platform tool {descriptor.address}. "
            "Trusted identity, operation identity, journaling, and authority are injected."
        )
        return StructuredTool.from_function(
            coroutine=invoke,
            name=name,
            description=invoke.__doc__,
            args_schema=_with_trusted_runtime(
                descriptor.input_model,
                name=f"{descriptor.input_model.__name__}AgentRuntime",
            ),
        )

    def _delegation_tool(self) -> BaseTool:
        output_paths = {
            AgentRole.RESEARCH: "outputs/research-strategy.md",
            AgentRole.CONTENT_DRAFTER: "outputs/content-exemplar.md",
            AgentRole.REVIEWER: "outputs/review-verdict.md",
        }

        async def delegate_specialist(runtime: ToolRuntime, **kwargs: Any) -> str:
            model_input = DelegateSpecialistRequest.model_validate(kwargs)
            role = AgentRole(model_input.role)
            if role not in self._resolved_profile.profile.delegation_roles:
                raise ValueError(f"role {role.value!r} is absent from delegated authority")
            workspace_id = self._request.constitution.workspace_id
            file_grants: list[DelegatedFileGrant] = []
            for ordinal, source_path in enumerate(model_input.canonical_paths):
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
                for item in model_input.domain_refs
            )
            specialist_role = cast(
                Literal[
                    AgentRole.RESEARCH,
                    AgentRole.CONTENT_DRAFTER,
                    AgentRole.REVIEWER,
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
            model_input = ModelFinalizeRequest.model_validate(kwargs)
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
            output_refs = tuple(await self._lease.backend.snapshot_outputs())
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid5(
                    _FINALIZATION_NAMESPACE,
                    str(self._request.constitution.execution_id),
                ),
                execution_id=self._request.constitution.execution_id,
                status=model_input.status,
                user_message_artifact_ref=final_message_ref,
                output_refs=output_refs,
                domain_refs=model_input.domain_refs,
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
    ) -> None:
        self._runtime = runtime
        self._turns = turns
        self._artifacts = artifacts

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        context: AssembledAgentContext,
        lease: AgentWorkspaceLease,
        tools: Sequence[BaseTool],
    ) -> AgentTurnOutcome:
        workspace_id = request.constitution.workspace_id
        await self._turns.mark_running(
            turn_id=request.turn_id,
            workspace_id=workspace_id,
        )
        model_calls = DurableAgentModelCallHandler(
            request=request,
            requested_model=resolved_profile.profile.model.model_id,
            initial_sequence=await self._turns.next_model_call_sequence(turn_id=request.turn_id),
            artifacts=self._artifacts,
            turns=self._turns,
        )
        try:
            outcome = await self._runtime.run(
                request=request,
                resolved_profile=resolved_profile,
                context=context,
                backend=lease.backend,
                governed_tools=tools,
                callbacks=(model_calls,),
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
