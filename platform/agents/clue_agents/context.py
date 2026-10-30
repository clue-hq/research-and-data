"""Deterministic seven-layer opening context for one governed agent turn.

Bodies in this module are ephemeral. The durable receipt contains only exact source pointers,
hashes, counts and materialized relative paths. Context is assembled before the first model call;
the model never decides what opening authority or data it receives.

Layer budgets are **reported, never enforced** (founder ruling 2026-09-14): assembly emits every
candidate every source offers, records what each one cost, and logs the layers that exceed their
policy number. Nothing here drops context or fails a turn to stay under a budget.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid5

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_agents.attachment_images import is_shown_as_picture, viewable_image
from clue_agents.contracts import (
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    ContinuationRef,
    DomainObjectRef,
)
from clue_agents.ports import (
    INTERRUPTED_ASSISTANT_NOTICE,
    AgentArtifactReader,
    AssembledAgentContext,
    ContextMaterialization,
    HistoryMessageRef,
)
from clue_agents.registry import ResolvedAgentProfile
from clue_core import AssemblyRequest, ContextAssembly, MemoryType, ScopeStack
from clue_obs import get_logger

__all__ = [
    "IMAGE_TOKEN_ALLOWANCE",
    "AttachmentDescriber",
    "AttachmentDescription",
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

log = get_logger("clue_agents.context")

_ORDER = tuple(ContextLayer)
#: A continued turn appends to a saved conversation that already opens with the system prompt, so
#: its additions are the gap messages first, then this turn's cards, then the user's message.
_CONTINUATION_ORDER = (
    ContextLayer.L1_IDENTITY,
    ContextLayer.L6_CONVERSATION,
    ContextLayer.L2_WORKSPACE_PRODUCT,
    ContextLayer.L3_PROJECT,
    ContextLayer.L4_MEMORY,
    ContextLayer.L5_FOCUS,
    ContextLayer.L7_TURN,
)

#: What one image on a turn is *reported* to cost against its layer budget (spec 2026-09-18).
#:
#: An image rides the user message as a data-url part, so the utf-8 byte counter that measures
#: every other candidate would either miss it entirely (the bytes are not in ``budget_text``) or,
#: if it were handed the base64, wildly overstate it — providers bill an image by its tiles, not
#: by its transport encoding. A flat per-image allowance keeps the reported number honest enough
#: to reason about without pretending to know the provider's tiling. Budgets are reporting-only
#: (founder ruling 2026-09-14), so this number can never cost a turn its context or fail it.
IMAGE_TOKEN_ALLOWANCE = 1_000

#: Layers whose budget retains the **newest** candidates rather than the first ones in canonical
#: (``stable_key``) order — FI Lane D D0, charter §1.1.
#:
#: Every other layer is a set of independent compiled cards where "which one was dropped" is a
#: matter of ordering convention. L6 is not: it is one ordered conversation, its ``stable_key`` is
#: the message sequence, and a long thread that keeps its *oldest* messages hands the model a
#: transcript that stops before the thing the user just said. Retention is therefore newest-first
#: for L6; **emission stays chronological** for every layer, so the model still reads the retained
#: window in order and each candidate's ``stable_key``/receipt ordinal is unchanged.
#:
#: Since the 2026-09-14 ruling nothing is dropped at all, so this direction currently selects
#: nothing. It is kept because it is the already-settled answer for the only trim that could ever
#: be justified — one sized to the provider's context window, a fact of the model rather than a
#: policy of ours — and that trim, if it is ever wanted, belongs exactly here.
_RETAIN_NEWEST_LAYERS: frozenset[ContextLayer] = frozenset({ContextLayer.L6_CONVERSATION})


class ContextValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class LayerBudget(ContextValue):
    layer: ContextLayer
    max_tokens: int = Field(ge=0)


class ContextAssemblyPolicy(ContextValue):
    """Versioned per-layer budgets; all seven layers must be explicitly governed.

    ``max_tokens`` is a *reporting* line, not a ceiling — the assembler measures each layer against
    it and logs the overruns, and never withholds context or fails a turn on it. The shape is kept
    unchanged so every receipt, old and new, still carries the seven numbers it was assembled
    against.
    """

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
    """One atomic context item; it is counted, and emitted, whole."""

    stable_key: str = Field(min_length=1)
    ref: ArtifactRef | DomainObjectRef
    body: str = Field(min_length=1)
    role: Literal["system", "user", "assistant", "tool"] = "system"
    origin: Literal["trusted_context", "history", "current_user_instruction"] = "trusted_context"
    materialized_path: str | None = None
    required: bool = False
    interrupted: bool = False
    #: Images the model sees beside this candidate's text (spec 2026-09-18, ruling 1 and 2).
    #: Pointers only, like every other ref here — the assembler reads the bytes once, at the one
    #: moment the message is built, and they are never part of the candidate's durable receipt.
    image_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def interruption_is_history(self) -> ContextCandidate:
        if self.interrupted and (self.role != "assistant" or self.origin != "history"):
            raise ValueError("interruption provenance belongs to assistant history")
        return self

    @property
    def budget_text(self) -> str:
        # Keep the provenance and exact saved body together under the layer budget.
        if self.interrupted:
            return INTERRUPTED_ASSISTANT_NOTICE + "\n\n" + self.body
        return self.body

    @property
    def image_token_allowance(self) -> int:
        """The reported cost of this candidate's images; see :data:`IMAGE_TOKEN_ALLOWANCE`."""

        return IMAGE_TOKEN_ALLOWANCE * len(self.image_refs)


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
        unique: list[DomainObjectRef] = []
        seen: set[tuple[str, str, int | None]] = set()
        for ref in refs:
            identity = (ref.object_type, ref.object_id, ref.version)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(ref)
        result: list[ContextCandidate] = []
        for ordinal, ref in enumerate(unique):
            card = await self._cards.read(
                workspace_id=request.constitution.workspace_id,
                object_type=ref.object_type,
                object_id=ref.object_id,
            )
            if card is None:
                continue
            if (
                card.ref.workspace_id != ref.workspace_id
                or card.ref.object_type != ref.object_type
                or card.ref.object_id != ref.object_id
                or (ref.version is not None and card.ref.version != ref.version)
            ):
                raise ValueError("focus card version differs from the requested exact reference")
            result.append(
                ContextCandidate(
                    # The assembler sorts by stable key before budgeting and emission. Prefixing
                    # the durable submission order keeps the user's account/contact sequence
                    # intact all the way into L5 instead of silently alphabetizing it.
                    stable_key=(f"{ordinal:06d}:{ref.object_type}:{ref.object_id}:{ref.version}"),
                    ref=ref,
                    body=card.body,
                    materialized_path=_card_path("focus", ref),
                )
            )
        return result


class HistoryLayerSource:
    layer = ContextLayer.L6_CONVERSATION

    def __init__(self, artifacts: AgentArtifactReader, *, images_max: int = 20) -> None:
        self._artifacts = artifacts
        self._images_max = images_max

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile
        ordered = sorted(history, key=lambda value: value.sequence)
        # Ruling 2 (2026-09-18): a picture the user already sent stays visible for the rest of the
        # conversation, so the model can still be asked about it three turns later. Bytes are not
        # free, so a thread carries at most ``images_max`` of them and the newest win the cap
        # (``0`` = no cap). Walking newest-first is what makes "newest win" true.
        budget = None if self._images_max == 0 else self._images_max
        kept: dict[int, tuple[ArtifactRef, ...]] = {}
        for item in reversed(ordered):
            images = tuple(
                ref for ref in item.attachment_refs if is_shown_as_picture(ref.media_type)
            )
            if item.role != "user" or not images:
                continue
            if budget is None:
                kept[item.sequence] = images
            elif budget > 0:
                take = images[-budget:]
                kept[item.sequence] = take
                budget -= len(take)
        result: list[ContextCandidate] = []
        for item in ordered:
            if item.body_ref.workspace_id != request.constitution.workspace_id:
                raise ValueError("history ref crosses the turn workspace boundary")
            body = (await self._artifacts.read(item.body_ref)).decode("utf-8")
            result.append(
                ContextCandidate(
                    stable_key=f"{item.sequence:020d}:{item.message_id}",
                    ref=item.body_ref,
                    body=body,
                    role=item.role,
                    origin="history",
                    interrupted=item.interrupted and item.role == "assistant",
                    image_refs=kept.get(item.sequence, ()),
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


class AttachmentDescription(Protocol):
    """What one attachment is called, where its file sits, and which family it belongs to.

    ``family`` is ``"text"``, ``"image"`` or ``"document"`` — it decides only which tool the
    sentence tells the agent to open the file with, never whether the file is there.
    """

    @property
    def filename(self) -> str: ...

    @property
    def workspace_path(self) -> str | None: ...

    @property
    def family(self) -> str: ...


class AttachmentDescriber(Protocol):
    """Name each attachment by its filename, its workspace path, and its family.

    Structural for the same reason :class:`CapturedTurnDescription` is: the durable rows an
    attachment is named from live at the api composition root, and L7 only ever reads the three
    values above. Keyed by ``artifact_key`` — the one identity a turn's attachment refs carry.
    """

    async def describe(self, request: AgentTurnRequest) -> Mapping[str, AttachmentDescription]: ...


class TurnLayerSource:
    layer = ContextLayer.L7_TURN

    def __init__(
        self,
        artifacts: AgentArtifactReader,
        *,
        captured_turn: CapturedTurnDescription | None = None,
        attachments: AttachmentDescriber | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._captured_turn = captured_turn
        self._attachments = attachments

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del profile, history
        body = (await self._artifacts.read(request.user_message_artifact_ref)).decode("utf-8")
        result: list[ContextCandidate] = []
        # Raw attachment bytes are never opening context. The agent gets only exact pointers and
        # may later use an authorized tool to inspect an allowed attachment. A describer turns
        # those pointers into the words a human would use — the file's name, the one path the
        # worker syncs it to, and the tool that opens that family — so the model can open what it
        # needs instead of guessing from a hash. With no describer (or an attachment the describer
        # does not know) the pointer line is unchanged: naming nothing is better than naming it
        # wrong.
        described: Mapping[str, AttachmentDescription] = (
            await self._attachments.describe(request) if self._attachments is not None else {}
        )
        for index, ref in enumerate(request.attachment_refs):
            info = described.get(ref.artifact_key)
            size = f"{ref.byte_count:,} bytes"
            # A local of its own, never ``body``: that name already holds the words the human
            # typed, and reusing it here would hand the model an attachment line as its own
            # most-recent instruction.
            description: str
            if info is None:
                description = (
                    "Attachment reference only: "
                    f"artifact_key={ref.artifact_key} sha256={ref.sha256} "
                    f"media_type={ref.media_type} byte_count={ref.byte_count}"
                )
            elif info.workspace_path is None:
                # Fallback for a describer that names no path (the production one always does):
                # claim only what is true without a synced file — the image is in the message.
                description = (
                    f'Attachment "{info.filename}" ({ref.media_type}, {size}) is attached to this '
                    "message as an image."
                )
            else:
                # One sentence per file: what it is, where its one copy sits, and how to open it.
                # An image is named too — the model sees it here, but code reads it from the path.
                # An SVG is a drawing written as text: it is read, never shown (spec 2026-10-30).
                if info.family == "text" or (
                    info.family == "image" and not is_shown_as_picture(ref.media_type)
                ):
                    opener = "open it with read_file."
                elif info.family == "image":
                    opener = "it is also shown to you as an image in this message."
                else:
                    # Every other family is bytes read_file would refuse; run_python reads any of
                    # them, so it is also the honest answer for a family L7 does not recognise.
                    opener = "open it with run_python."
                description = (
                    f'Attachment "{info.filename}" ({ref.media_type}, {size}) was attached to '
                    f"this message. It is at {info.workspace_path}; {opener}"
                )
            result.append(
                ContextCandidate(
                    stable_key=f"200-{index:06d}-attachment:{ref.artifact_key}",
                    ref=ref,
                    body=description,
                    role="system",
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
                    stable_key="100-captured-turn",
                    ref=request.user_message_artifact_ref,
                    body=(
                        "Captured turn reference only: this message is already a captured "
                        "onboarding input. The platform supplies these values to any tool that "
                        "needs them; never author or retype them. "
                        f"onboarding_input_id={captured.onboarding_input_id} "
                        f"artifact_key={captured.artifact_key} sha256={captured.sha256} "
                        f"byte_count={captured.byte_count}"
                    ),
                    role="system",
                )
            )
        # ``request.focus_refs`` are the exact Account/Contact references durably captured on
        # this human submission. L5 hydrates those objects, but hydration alone does not tell the
        # model whether an Account came from the *current message* or from ambient project focus.
        # Keep that authority distinction explicit in L7 so phrases such as "the selected
        # account" resolve to the submitted ordered set and never widen to the project catalog.
        # One candidate per ref preserves both its domain receipt and its submission order.
        for index, current_ref in enumerate(request.focus_refs):
            result.append(
                ContextCandidate(
                    stable_key=f"150-current-context-ref:{index:06d}",
                    ref=current_ref,
                    body=(
                        "Current human-message context reference: the platform durably captured "
                        "this exact ordered subject on the user's current message. Treat words "
                        "such as selected, this, these, or them as naming exactly these current "
                        "message references; never widen, replace, or ask the user to retype "
                        "them. The platform supplies authoritative values to governed tools. "
                        f"ordinal={index} object_type={current_ref.object_type} "
                        f"object_id={current_ref.object_id} version={current_ref.version}"
                    ),
                    role="system",
                    materialized_path=(
                        "inputs/current-context/"
                        f"{index:06d}-{current_ref.object_type}-{current_ref.object_id}.txt"
                    ),
                )
            )
        # The only user-authored message in L7 is deliberately last. Attachment and capture
        # descriptions are platform-authored trusted context, not words the user typed, and may
        # never become the model's most-recent human instruction.
        result.append(
            ContextCandidate(
                stable_key="999-user-message",
                ref=request.user_message_artifact_ref,
                body=body,
                role="user",
                origin="current_user_instruction",
                materialized_path="inputs/user-message.txt",
                required=True,
                # An image cannot be read with ``read_file``; the only way a model sees one is
                # beside the words it was sent with, so the turn's images ride this message.
                # Everything else on the turn stays a pointer the agent opens deliberately.
                image_refs=tuple(
                    ref for ref in request.attachment_refs if is_shown_as_picture(ref.media_type)
                ),
            )
        )
        return result


def _message(candidate: ContextCandidate, images: Mapping[str, bytes] | None = None) -> BaseMessage:
    """Turn one candidate into the message the model reads.

    ``images`` maps ``artifact_key`` to the bytes the assembler already read for this turn; a
    candidate carrying :attr:`ContextCandidate.image_refs` becomes a multipart human message whose
    first part is its text and whose remaining parts are the images as data urls (the shape the
    Task-1 probe proved the Head-of-ABM model accepts). ``None`` means no images were read, which
    is the only thing a text-only candidate ever needs.
    """

    if candidate.role == "user" and candidate.image_refs:
        read = images or {}
        parts: list[str | dict[Any, Any]] = [{"type": "text", "text": candidate.body}]
        for ref in candidate.image_refs:
            # A format the model does not take is shown as a PNG copy; bytes that do not decode
            # are not shown at all (the file is still in the agent's folder).
            shown = viewable_image(read[ref.artifact_key], ref.media_type)
            if shown is None:
                continue
            data, media_type = shown
            encoded = base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
        return HumanMessage(content=parts)
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
        artifacts: AgentArtifactReader | None = None,
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
        # Only an image-carrying candidate needs bytes, so a composition with no image path may
        # leave this ``None`` and stay valid; assembly fails loudly the moment one shows up.
        self._artifacts = artifacts

    def _retain(
        self,
        *,
        layer: ContextLayer,
        candidates: Sequence[ContextCandidate],
        budget: int,
    ) -> dict[str, int]:
        """Count every candidate; return ``{stable_key: token_count}`` for all of them.

        This method used to *decide*: a candidate that did not fit ``budget`` was skipped, and a
        ``required`` one that did not fit raised, so a profile 273 bytes too large took down every
        turn on it. Founder ruling 2026-09-14: no layer budget may fail a turn or cost it context.
        Nothing is skipped and nothing raises here — the budget survives as a number to report
        against (the caller logs the layers that exceed theirs), never as a gate.

        ``budget`` is therefore unread, and the newest-first order for
        :data:`_RETAIN_NEWEST_LAYERS` no longer selects anything. Both are kept deliberately: the
        direction is the answer already worked out for the day a *window*-sized trim lands — a fact
        of the provider's context window rather than a policy of ours — and the day it does, this
        is where it goes.
        """

        del budget
        order = tuple(reversed(candidates)) if layer in _RETAIN_NEWEST_LAYERS else tuple(candidates)
        return {
            candidate.stable_key: self._counter.count(candidate.budget_text)
            + candidate.image_token_allowance
            for candidate in order
        }

    async def assemble(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
        continuation: ContinuationRef | None = None,
    ) -> AssembledAgentContext:
        """The turn's opening messages and their receipt.

        With ``continuation``, ``history`` is the gap since the resumed turn, the system prompt is
        not re-sent (the resumed state opens with it; its manifest still records it), and the
        messages are ordered gap, cards, message — appended to the saved conversation.
        """
        manifests: list[ContextLayerManifest] = []
        receipt_refs: list[ContextReceiptRef] = []
        messages: list[BaseMessage] = []
        materializations: list[ContextMaterialization] = []
        seen_paths: set[str] = set()
        current_instructions: list[ContextCandidate] = []
        # Image bytes, keyed by ``artifact_key`` and read exactly once for the whole turn.
        images: dict[str, bytes] = {}

        for layer in _ORDER if continuation is None else _CONTINUATION_ORDER:
            emit = continuation is None or layer is not ContextLayer.L1_IDENTITY
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
                if (
                    candidate.origin == "current_user_instruction"
                    and layer is not ContextLayer.L7_TURN
                ):
                    raise ValueError("only l7_turn may emit the current user instruction")
                for image_ref in candidate.image_refs:
                    if image_ref.workspace_id != request.constitution.workspace_id:
                        raise ValueError(f"{layer.value} emitted a cross-workspace context ref")
            # Every image is read before a single message is built, and each one exactly once: the
            # same attachment can be named by more than one candidate, and a turn must never pay
            # twice for the same bytes. A candidate carrying images with no reader composed is a
            # composition error, not a turn the model gets to see half of.
            for candidate in candidates:
                for image_ref in candidate.image_refs:
                    if image_ref.artifact_key in images:
                        continue
                    if self._artifacts is None:
                        raise ValueError("image candidates need an artifact reader")
                    images[image_ref.artifact_key] = await self._artifacts.read(image_ref)
            budget = self._policy.budget_for(layer)
            retained = self._retain(layer=layer, candidates=candidates, budget=budget)
            used = 0
            included: list[ContextCandidate] = []
            hashes: list[str] = []
            paths: list[str] = []
            # Emission is canonical ``stable_key`` order for every layer, and every candidate is
            # emitted: budgets no longer decide membership, so there is nothing left to skip.
            for candidate in candidates:
                count = retained[candidate.stable_key]
                digest = hashlib.sha256(candidate.budget_text.encode("utf-8")).hexdigest()
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
                if candidate.origin == "current_user_instruction":
                    current_instructions.append(candidate)
                hashes.append(digest)
                if emit:
                    if candidate.interrupted:
                        messages.append(SystemMessage(content=INTERRUPTED_ASSISTANT_NOTICE))
                    messages.append(_message(candidate, images))
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
            if used > budget:
                # The one thing an over-budget layer now does: say so. The turn carries all of it.
                log.warning(
                    "agent_turn.context_layer_over_budget",
                    execution_id=str(request.constitution.execution_id),
                    layer=layer.value,
                    token_count=used,
                    token_budget=budget,
                    policy_version=self._policy.version,
                )
            manifests.append(
                ContextLayerManifest(
                    layer=layer,
                    source_refs=tuple(item.ref for item in included),
                    materialized_paths=tuple(paths),
                    content_sha256s=tuple(hashes),
                    token_count=used,
                    excluded_refs=(),
                    exclusion_reason_codes=(),
                )
            )

        # Receipts keep the canonical L1-L7 order whatever order the messages were built in.
        manifests.sort(key=lambda item: _ORDER.index(item.layer))
        receipt_refs.sort(key=lambda item: _ORDER.index(item.layer))
        if len(current_instructions) != 1:
            raise ValueError("opening context requires exactly one current user instruction")
        current_instruction = current_instructions[0]
        if current_instruction.ref != request.user_message_artifact_ref:
            raise ValueError("current user instruction differs from the turn message artifact")
        if not messages:
            raise ValueError("current user instruction must be the final opening-context message")
        final = messages[-1]
        # The instruction's words are the message's text, whether it is a plain string or the
        # multipart shape an image-carrying turn takes; the check is over the words either way.
        final_text = (
            final.content
            if isinstance(final.content, str)
            else next(
                (
                    part["text"]
                    for part in final.content
                    if isinstance(part, dict) and part.get("type") == "text"
                ),
                None,
            )
        )
        if not isinstance(final, HumanMessage) or final_text != current_instruction.body:
            raise ValueError("current user instruction must be the final opening-context message")

        aggregate_payload: dict[str, Any] = {
            "schema_version": "1",
            "execution_id": str(request.constitution.execution_id),
            "policy_version": self._policy.version,
            "token_counter_version": self._policy.token_counter_version,
            "layers": [item.model_dump(mode="json") for item in manifests],
        }
        if continuation is not None:
            aggregate_payload["continuation"] = continuation.model_dump(mode="json")
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
            continuation=continuation,
        )
