"""Deterministic seven-layer opening context for one governed agent turn.

Bodies in this module are ephemeral. The durable receipt contains only exact source pointers,
hashes, counts, materialized relative paths and stable exclusion reasons. Context is assembled
before the first model call; the model never decides what opening authority or data it receives.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid5

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_agents.contracts import (
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    DomainObjectRef,
)
from clue_agents.ports import (
    AgentArtifactReader,
    AssembledAgentContext,
    ContextMaterialization,
    HistoryMessageRef,
)
from clue_agents.registry import ResolvedAgentProfile
from clue_core import AssemblyRequest, ContextAssembly, MemoryType, ScopeStack

__all__ = [
    "CompiledContextCard",
    "ContextAssemblyPolicy",
    "ContextAssemblyReceipt",
    "ContextCandidate",
    "ContextLayerSource",
    "ContextReceiptRef",
    "ContextReceiptStore",
    "DeterministicAgentContextAssembler",
    "FocusLayerSource",
    "HistoryLayerSource",
    "IdentityLayerSource",
    "LayerBudget",
    "MemoryLayerSource",
    "ProjectLayerSource",
    "TurnLayerSource",
    "Utf8ByteTokenCounter",
    "WorkspaceProductLayerSource",
]

_ORDER = tuple(ContextLayer)

#: Layers whose budget retains the **newest** candidates rather than the first ones in canonical
#: (``stable_key``) order — FI Lane D D0, charter §1.1.
#:
#: Every other layer is a set of independent compiled cards where "which one was dropped" is a
#: matter of ordering convention. L6 is not: it is one ordered conversation, its ``stable_key`` is
#: the message sequence, and a long thread that keeps its *oldest* messages hands the model a
#: transcript that stops before the thing the user just said. Retention is therefore newest-first
#: for L6; **emission stays chronological** for every layer, so the model still reads the retained
#: window in order and each candidate's ``stable_key``/receipt ordinal is unchanged.
_RETAIN_NEWEST_LAYERS: frozenset[ContextLayer] = frozenset({ContextLayer.L6_CONVERSATION})


class ContextValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class LayerBudget(ContextValue):
    layer: ContextLayer
    max_tokens: int = Field(ge=0)


class ContextAssemblyPolicy(ContextValue):
    """Versioned hard budgets; all seven layers must be explicitly governed."""

    version: str = Field(min_length=1)
    token_counter_version: str = Field(min_length=1)
    budgets: tuple[LayerBudget, ...]

    @model_validator(mode="after")
    def exactly_seven_budgets(self) -> ContextAssemblyPolicy:
        if tuple(item.layer for item in self.budgets) != _ORDER:
            raise ValueError("context policy must budget L1-L7 in canonical order")
        return self

    def budget_for(self, layer: ContextLayer) -> int:
        return next(item.max_tokens for item in self.budgets if item.layer is layer)


class ContextCandidate(ContextValue):
    """One atomic context item. Budgeting includes or excludes the whole item."""

    stable_key: str = Field(min_length=1)
    ref: ArtifactRef | DomainObjectRef
    body: str = Field(min_length=1)
    role: Literal["system", "user", "assistant", "tool"] = "system"
    materialized_path: str | None = None
    required: bool = False


class ContextReceiptRef(ContextValue):
    layer: ContextLayer
    disposition: Literal["included", "excluded"]
    ordinal: int = Field(ge=0)
    ref: ArtifactRef | DomainObjectRef
    content_sha256: str | None = None
    materialized_path: str | None = None
    token_count: int | None = Field(default=None, ge=0)
    exclusion_reason_code: str | None = None

    @model_validator(mode="after")
    def receipt_shape(self) -> ContextReceiptRef:
        if self.disposition == "included":
            if self.content_sha256 is None or self.token_count is None:
                raise ValueError("included context ref requires hash and token count")
            if self.exclusion_reason_code is not None:
                raise ValueError("included context ref cannot carry an exclusion reason")
        elif (
            self.content_sha256 is not None
            or self.materialized_path is not None
            or self.token_count is not None
            or self.exclusion_reason_code is None
        ):
            raise ValueError("excluded context ref may carry only a stable exclusion reason")
        return self


class ContextAssemblyReceipt(ContextValue):
    manifest: ContextBundleManifest
    policy_version: str
    token_counter_version: str
    budgets: tuple[LayerBudget, ...]
    refs: tuple[ContextReceiptRef, ...]

    @model_validator(mode="after")
    def exactly_seven_budgets(self) -> ContextAssemblyReceipt:
        if tuple(item.layer for item in self.budgets) != _ORDER:
            raise ValueError("context receipt must retain all seven effective layer budgets")
        return self


class CompiledContextCard(ContextValue):
    """A versioned, provenance-addressable card compiled by the owning subsystem."""

    ref: DomainObjectRef
    body: str


@runtime_checkable
class CompiledContextCardReader(Protocol):
    async def read(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
    ) -> CompiledContextCard | None: ...


@runtime_checkable
class ContextLayerSource(Protocol):
    layer: ContextLayer

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]: ...


@runtime_checkable
class ContextReceiptStore(Protocol):
    async def record(
        self,
        *,
        request: AgentTurnRequest,
        receipt: ContextAssemblyReceipt,
    ) -> None: ...


class Utf8ByteTokenCounter:
    """Conservative deterministic counter used until a pinned model tokenizer replaces it.

    One token per UTF-8 byte intentionally over-counts ordinary model tokenization. It is a hard
    safety ceiling, is dependency-free, and is explicitly versioned in every receipt.
    """

    version = "utf8-bytes-v1"

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class IdentityLayerSource:
    layer = ContextLayer.L1_IDENTITY

    def __init__(self, resolved: ResolvedAgentProfile) -> None:
        self._resolved = resolved

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del history
        if profile != self._resolved.profile:
            raise ValueError("identity source profile differs from the resolved resource snapshot")
        return (
            ContextCandidate(
                stable_key="identity",
                ref=request.constitution.resource_manifest_ref,
                body=self._resolved.system_prompt,
                role="system",
                required=True,
            ),
        )


def _card_path(prefix: str, ref: DomainObjectRef) -> str:
    suffix = hashlib.sha256(
        f"{ref.object_type}\0{ref.object_id}\0{ref.version}".encode()
    ).hexdigest()[:20]
    return f"context/{prefix}/{ref.object_type}-{suffix}.md"


class WorkspaceProductLayerSource:
    layer = ContextLayer.L2_WORKSPACE_PRODUCT

    def __init__(self, cards: CompiledContextCardReader) -> None:
        self._cards = cards

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        identities = (
            ("brand", request.constitution.brand_id),
            ("product", request.constitution.product_id),
        )
        result: list[ContextCandidate] = []
        for object_type, object_id in identities:
            if object_id is None:
                continue
            card = await self._cards.read(
                workspace_id=request.constitution.workspace_id,
                object_type=object_type,
                object_id=object_id,
            )
            if card is None:
                continue
            result.append(
                ContextCandidate(
                    stable_key=f"{object_type}:{object_id}:{card.ref.version}",
                    ref=card.ref,
                    body=card.body,
                    materialized_path=_card_path("workspace-product", card.ref),
                )
            )
        return result


class ProjectLayerSource:
    """L3 holds the two base project artifacts plus explicitly constituted project inputs.

    One owner per concern (PC-C8 §2). The card is the whole bounded projection of durable project
    state, so the compiled ``project`` context card this source used to read as well is subsumed by
    it — reading both would put two descriptions of the same project in front of the model and
    reintroduce the duplication the card exists to remove. The budget envelope stays separate
    because it is spend authority rather than project state.
    """

    layer = ContextLayer.L3_PROJECT

    def __init__(self, *, artifacts: AgentArtifactReader) -> None:
        self._artifacts = artifacts

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        candidates = (
            ("project_card", request.constitution.project_card_ref),
            ("budget", request.constitution.budget_envelope_ref),
            *(
                (item.name, item.artifact_ref)
                for item in request.constitution.project_context_artifacts
            ),
        )
        result: list[ContextCandidate] = []
        for name, ref in candidates:
            body = (await self._artifacts.read(ref)).decode("utf-8")
            result.append(
                ContextCandidate(
                    stable_key=f"{name}:{ref.artifact_key}",
                    ref=ref,
                    body=body,
                    materialized_path=f"context/project/{name}.json",
                    required=True,
                )
            )
        return result


class MemoryLayerSource:
    layer = ContextLayer.L4_MEMORY

    def __init__(
        self,
        *,
        assembly: ContextAssembly,
        recipe: str,
        requested_types: tuple[MemoryType, ...],
    ) -> None:
        self._assembly = assembly
        self._recipe = recipe
        self._requested_types = requested_types

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        if not self._requested_types or request.constitution.brand_id is None:
            return ()
        account_refs = tuple(
            ref for ref in request.constitution.focus_refs if ref.object_type == "account"
        )
        account_entity_id: UUID | None = None
        if len(account_refs) == 1:
            # A DomainObjectRef is generic and older/non-research account ids need not be UUIDs.
            # The project preference still belongs in context; only the optional account scope is
            # omitted when it cannot name the memory substrate's canonical account key.
            with suppress(ValueError):
                account_entity_id = UUID(account_refs[0].object_id)
        bundle = await self._assembly.assemble(
            AssemblyRequest(
                scope_stack=ScopeStack(
                    workspace_id=request.constitution.workspace_id,
                    brand_id=request.constitution.brand_id,
                    product_id=request.constitution.product_id,
                    project_id=request.constitution.project_id,
                    account_entity_id=account_entity_id,
                ),
                recipe=self._recipe,
                requested_types=self._requested_types,
            )
        )
        if bundle is None:
            return ()
        result: list[ContextCandidate] = []
        for entry in bundle.entries:
            ref = DomainObjectRef(
                workspace_id=bundle.workspace_id,
                object_type="scoped_memory",
                object_id=entry.memory_id,
                version=None,
            )
            label = entry.label.model_dump_json()
            result.append(
                ContextCandidate(
                    stable_key=f"memory:{entry.memory_id}",
                    ref=ref,
                    body=f"Memory label: {label}\n\nAdvisory body:\n{entry.body}",
                    materialized_path=_card_path("memory", ref),
                )
            )
        return result


class FocusLayerSource:
    layer = ContextLayer.L5_FOCUS

    def __init__(self, cards: CompiledContextCardReader) -> None:
        self._cards = cards

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        refs = (*request.constitution.focus_refs, *request.focus_refs)
        unique = {(ref.object_type, ref.object_id, ref.version): ref for ref in refs}
        result: list[ContextCandidate] = []
        for ref in sorted(
            unique.values(),
            key=lambda item: (
                item.object_type,
                item.object_id,
                item.version,
            ),
        ):
            card = await self._cards.read(
                workspace_id=request.constitution.workspace_id,
                object_type=ref.object_type,
                object_id=ref.object_id,
            )
            if card is None:
                continue
            if card.ref != ref:
                raise ValueError("focus card version differs from the requested exact reference")
            result.append(
                ContextCandidate(
                    stable_key=f"{ref.object_type}:{ref.object_id}:{ref.version}",
                    ref=ref,
                    body=card.body,
                    materialized_path=_card_path("focus", ref),
                )
            )
        return result


class HistoryLayerSource:
    layer = ContextLayer.L6_CONVERSATION

    def __init__(self, artifacts: AgentArtifactReader) -> None:
        self._artifacts = artifacts

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile
        result: list[ContextCandidate] = []
        for item in sorted(history, key=lambda value: value.sequence):
            if item.body_ref.workspace_id != request.constitution.workspace_id:
                raise ValueError("history ref crosses the turn workspace boundary")
            body = (await self._artifacts.read(item.body_ref)).decode("utf-8")
            result.append(
                ContextCandidate(
                    stable_key=f"{item.sequence:020d}:{item.message_id}",
                    ref=item.body_ref,
                    body=body,
                    role=item.role,
                )
            )
        return result


class CapturedTurnIdentity(Protocol):
    """The engine-owned identity of a captured user turn (PC-C8 §6b).

    Structural on purpose: the concrete binding lives at the api composition root (it needs the
    artifact store and the capture record), and L7 only ever reads these four values. They are
    read-only members, which is also what lets an immutable (frozen) implementation satisfy this.
    """

    @property
    def onboarding_input_id(self) -> str: ...

    @property
    def artifact_key(self) -> str: ...

    @property
    def sha256(self) -> str: ...

    @property
    def byte_count(self) -> int: ...


class CapturedTurnDescription(Protocol):
    """Describe this turn's capture, or ``None`` when the surface captured none."""

    async def describe(self, request: AgentTurnRequest) -> CapturedTurnIdentity | None: ...


class TurnLayerSource:
    layer = ContextLayer.L7_TURN

    def __init__(
        self,
        artifacts: AgentArtifactReader,
        *,
        captured_turn: CapturedTurnDescription | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._captured_turn = captured_turn

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        body = (await self._artifacts.read(request.user_message_artifact_ref)).decode("utf-8")
        result = [
            ContextCandidate(
                stable_key="000-user-message",
                ref=request.user_message_artifact_ref,
                body=body,
                role="user",
                materialized_path="inputs/user-message.txt",
                required=True,
            )
        ]
        # Raw attachment bytes are never opening context. The agent gets only exact pointers and
        # may later use an authorized tool to inspect an allowed attachment.
        for index, ref in enumerate(request.attachment_refs):
            result.append(
                ContextCandidate(
                    stable_key=f"{index + 1:03d}-attachment:{ref.artifact_key}",
                    ref=ref,
                    body=(
                        "Attachment reference only: "
                        f"artifact_key={ref.artifact_key} sha256={ref.sha256} "
                        f"media_type={ref.media_type} byte_count={ref.byte_count}"
                    ),
                    role="user",
                )
            )
        # The turn's own identity, so the model can *reference* this capture without authoring it.
        # Deliberately reference-only and last: the trusted values are injected at the tool seam
        # (PC-C8 §6a), and a model that retypes them from here changes nothing. A surface that
        # captured no onboarding input simply has no envelope — that is not a failure, and L7 must
        # still assemble.
        captured = (
            await self._captured_turn.describe(request) if self._captured_turn is not None else None
        )
        if captured is not None:
            result.append(
                ContextCandidate(
                    stable_key="900-captured-turn",
                    ref=request.user_message_artifact_ref,
                    body=(
                        "Captured turn reference only: this message is already a captured "
                        "onboarding input. The platform supplies these values to any tool that "
                        "needs them; never author or retype them. "
                        f"onboarding_input_id={captured.onboarding_input_id} "
                        f"artifact_key={captured.artifact_key} sha256={captured.sha256} "
                        f"byte_count={captured.byte_count}"
                    ),
                    role="user",
                )
            )
        return result


def _message(candidate: ContextCandidate) -> BaseMessage:
    if candidate.role == "system":
        return SystemMessage(content=candidate.body)
    if candidate.role == "user":
        return HumanMessage(content=candidate.body)
    if candidate.role == "assistant":
        return AIMessage(content=candidate.body)
    if candidate.role == "tool":
        return ToolMessage(content=candidate.body, tool_call_id=f"context-{candidate.stable_key}")
    raise ValueError(f"unsupported context message role {candidate.role!r}")


def _media_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith((".md", ".markdown")):
        return "text/markdown"
    return "text/plain"


class DeterministicAgentContextAssembler:
    """Assemble, budget and receipt exactly one source for each of L1-L7."""

    def __init__(
        self,
        *,
        sources: Sequence[ContextLayerSource],
        policy: ContextAssemblyPolicy,
        receipts: ContextReceiptStore,
        token_counter: Utf8ByteTokenCounter | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        source_map = {source.layer: source for source in sources}
        if len(source_map) != len(sources) or tuple(sorted(source_map, key=_ORDER.index)) != _ORDER:
            raise ValueError("context assembler requires exactly one source for every L1-L7 layer")
        self._sources: Mapping[ContextLayer, ContextLayerSource] = source_map
        self._policy = policy
        self._receipts = receipts
        self._counter = token_counter or Utf8ByteTokenCounter()
        if self._counter.version != policy.token_counter_version:
            raise ValueError("token counter version differs from context policy")
        self._clock = clock

    def _retain(
        self,
        *,
        layer: ContextLayer,
        candidates: Sequence[ContextCandidate],
        budget: int,
    ) -> dict[str, int]:
        """Decide which candidates fit ``budget``; return ``{stable_key: token_count}``.

        The greedy rule is unchanged — a candidate that does not fit is *skipped*, not a stop, so a
        small later item still fits behind a large refused one — and so is the hard failure when a
        ``required`` candidate cannot fit. The only thing this method adds is the **direction** in
        which the budget is spent: canonical order for every layer, reverse (newest-first) for the
        conversation layer, where dropping the newest messages would silently truncate the turn the
        user just took (:data:`_RETAIN_NEWEST_LAYERS`).
        """

        order = tuple(reversed(candidates)) if layer in _RETAIN_NEWEST_LAYERS else tuple(candidates)
        retained: dict[str, int] = {}
        used = 0
        for candidate in order:
            count = self._counter.count(candidate.body)
            if used + count > budget:
                if candidate.required:
                    raise ValueError(
                        f"required {layer.value} context exceeds its hard layer budget"
                    )
                continue
            retained[candidate.stable_key] = count
            used += count
        return retained

    async def assemble(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> AssembledAgentContext:
        manifests: list[ContextLayerManifest] = []
        receipt_refs: list[ContextReceiptRef] = []
        messages: list[BaseMessage] = []
        materializations: list[ContextMaterialization] = []
        seen_paths: set[str] = set()

        for layer in _ORDER:
            candidates = sorted(
                await self._sources[layer].load(
                    request=request,
                    profile=profile,
                    history=history,
                ),
                key=lambda item: item.stable_key,
            )
            if len({item.stable_key for item in candidates}) != len(candidates):
                raise ValueError(f"{layer.value} emitted duplicate stable context keys")
            for candidate in candidates:
                if candidate.ref.workspace_id != request.constitution.workspace_id:
                    raise ValueError(f"{layer.value} emitted a cross-workspace context ref")
            budget = self._policy.budget_for(layer)
            retained = self._retain(layer=layer, candidates=candidates, budget=budget)
            used = 0
            included: list[ContextCandidate] = []
            excluded: list[ContextCandidate] = []
            hashes: list[str] = []
            paths: list[str] = []
            # Emission stays in canonical ``stable_key`` order for every layer — only *which*
            # candidates survive the budget depends on the layer's retention direction.
            for candidate in candidates:
                count = retained.get(candidate.stable_key)
                if count is None:
                    excluded.append(candidate)
                    receipt_refs.append(
                        ContextReceiptRef(
                            layer=layer,
                            disposition="excluded",
                            ordinal=len(excluded) - 1,
                            ref=candidate.ref,
                            exclusion_reason_code="layer_budget_exceeded",
                        )
                    )
                    continue
                digest = hashlib.sha256(candidate.body.encode("utf-8")).hexdigest()
                if candidate.materialized_path is not None:
                    if candidate.materialized_path in seen_paths:
                        raise ValueError("context materialization paths must be bundle-unique")
                    seen_paths.add(candidate.materialized_path)
                    paths.append(candidate.materialized_path)
                    materializations.append(
                        ContextMaterialization(
                            path=candidate.materialized_path,
                            data=candidate.body.encode("utf-8"),
                            sha256=digest,
                            media_type=_media_type(candidate.materialized_path),
                        )
                    )
                included.append(candidate)
                hashes.append(digest)
                messages.append(_message(candidate))
                receipt_refs.append(
                    ContextReceiptRef(
                        layer=layer,
                        disposition="included",
                        ordinal=len(included) - 1,
                        ref=candidate.ref,
                        content_sha256=digest,
                        materialized_path=candidate.materialized_path,
                        token_count=count,
                    )
                )
                used += count
            manifests.append(
                ContextLayerManifest(
                    layer=layer,
                    source_refs=tuple(item.ref for item in included),
                    materialized_paths=tuple(paths),
                    content_sha256s=tuple(hashes),
                    token_count=used,
                    excluded_refs=tuple(item.ref for item in excluded),
                    exclusion_reason_codes=tuple("layer_budget_exceeded" for _ in excluded),
                )
            )

        aggregate_payload = {
            "schema_version": "1",
            "execution_id": str(request.constitution.execution_id),
            "policy_version": self._policy.version,
            "token_counter_version": self._policy.token_counter_version,
            "layers": [item.model_dump(mode="json") for item in manifests],
        }
        aggregate = hashlib.sha256(
            json.dumps(
                aggregate_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        bundle_id = uuid5(request.turn_id, aggregate)
        manifest = ContextBundleManifest(
            context_bundle_id=bundle_id,
            execution_id=request.constitution.execution_id,
            schema_version="1",
            layers=tuple(manifests),
            aggregate_sha256=aggregate,
            assembled_at=self._clock(),
        )
        receipt = ContextAssemblyReceipt(
            manifest=manifest,
            policy_version=self._policy.version,
            token_counter_version=self._policy.token_counter_version,
            budgets=self._policy.budgets,
            refs=tuple(receipt_refs),
        )
        await self._receipts.record(request=request, receipt=receipt)
        return AssembledAgentContext(
            manifest=manifest,
            messages=tuple(messages),
            materializations=tuple(materializations),
        )
