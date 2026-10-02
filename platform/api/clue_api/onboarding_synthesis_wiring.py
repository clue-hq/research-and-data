"""The onboarding synthesis turns (ARV2-ONBOARDING-PLAN.md §5; O4).

This module lives outside ``clue_api.arv2`` because it composes the agent/execution substrate:
governed deepagent turns executed inside the promoted ``onboarding-synthesis-unit@1`` recipe,
under a per-brand system project row.

The shape is the account-research unit runner (``account_research_wiring`` +
``account_research_turn_wiring``) with the account scope replaced by the **brand** scope: the
brand's current knowledge documents are materialized read-only under ``inputs/brand/knowledge/``,
and the turn's ``outputs/`` become new ``brand_knowledge_document`` rows stamped with
``produced_by_turn_id``.

**One turn is one task.** :meth:`OnboardingSynthesisLauncher.launch_icps` runs the ICP turn — it
writes the client's profiles from the brand's own knowledge documents and returns the
:class:`RegisteredIcp` rows it registered. :meth:`OnboardingSynthesisLauncher.launch_persona` then
runs one turn per registered ICP.

The split is not cosmetic. Two things were measured on the live runs of the single turn that wrote
every ICP *and* every persona. First, the ICPs were finished early and then sat unregistered for
8–10 minutes while the rest of the turn ran, because a turn's outputs only become documents once
the whole turn ends — so nothing downstream could see a profile the agent had already written.
Second, the three personas queued behind each other inside that one turn, when they share no state
and could have been written at the same time. Splitting the work registers each ICP as soon as its
own turn ends and lets the persona turns run concurrently.

The split also lets the two tasks carry different authority: the ICP turn resolves the
``onboarding_icp`` surface, where the evidence tool is **not installed**, while a persona turn
keeps the role's full surface because its per-role evidence pass is what that tool is for.

The documents a turn needs most also ride the **opening context** (L5 focus), not only the disk:
each selected document is a ``brand_knowledge_document`` focus ref, compiled to its own verified
markdown by :class:`DbCompiledContextCardReader`. The same bytes stay seeded under
``inputs/brand/knowledge/`` so the model can cite a stable path, which is what the prompt asks for.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentPlanPolicy,
    AgentResourceMaterializer,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceLease,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DeepAgentTurnRuntime,
    DeterministicAgentContextAssembler,
    DomainObjectRef,
    LayerBudget,
    ResolvedAgentProfile,
    WorkspaceSeedFile,
)
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_compaction import compaction_for
from clue_api.agent_execution_wiring import (
    C5AgentExecutionAdapter,
    CheckpointerFactory,
    DbAgentPlanJournal,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_context_assembler,
)
from clue_api.agent_registry_wiring import ONBOARDING_ICP_SURFACE
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_authoring import comma_split_rows
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.brand_knowledge_context import (
    SERVABLE_STATUSES,
    current_knowledge_documents,
    current_project_knowledge_refs,
)
from clue_api.stage0_recipe import RecipeStep, StepPinProvider
from clue_config import Secrets, Settings
from clue_core import (
    AssemblyRequest,
    ExecutionId,
    MemoryBundle,
    MemorySelectionPin,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    operation_id_from_key,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityLoader,
    DbExecutionStarter,
    DbRecipeReader,
    ExecutionConflict,
    ExecutionParameterStore,
    ExecutionStatus,
    PinRequest,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_obs import get_logger
from clue_spine import get_brand
from clue_storage import StorageBackend, read_verified_artifact
from clue_toolbelt import ToolContext, ToolInvoker, ToolRegistry

__all__ = [
    "BUDGET_LIMIT_MILLICENTS",
    "EXECUTION_NAMESPACE_KEY",
    "INPUT_PREFIX",
    "SYNTHESIS_CARD_MEDIA_TYPE",
    "TURN_NAMESPACE",
    "IcpSynthesisResult",
    "OnboardingSynthesisLauncher",
    "OnboardingSynthesisResult",
    "OnboardingSynthesisStepPinProvider",
    "RegisteredIcp",
    "build_onboarding_synthesis_context",
    "build_onboarding_synthesis_launcher",
    "ensure_onboarding_project",
    "onboarding_project_id",
    "onboarding_synthesis_context_policy",
]

log = get_logger("clue_api.onboarding_synthesis_wiring")

#: The deterministic execution namespace: one execution per onboarding run, per recipe identity.
EXECUTION_NAMESPACE_KEY = "onboarding-synthesis-unit@1"
#: The uuid5 namespace for this surface's turn ids — one turn per onboarding run.
TURN_NAMESPACE = UUID("6c2f9d0e-4b3a-5f1e-9a77-0e2b4c8d1f55")
#: The $5 record-only ceiling the C5 plan policy enforces for one synthesis turn.
BUDGET_LIMIT_MILLICENTS = 500_000
SYNTHESIS_CARD_MEDIA_TYPE = "application/vnd.clue.onboarding-synthesis-card+json"
#: Where THIS surface puts the knowledge documents its turns read. It seeds its own read-only
#: copies per turn and mounts no library, and its profile (``onboarding-synthesis@v4``), prompt
#: and skill all name this path — so it is deliberately not on the library/mount path the
#: conversation turn moved to, and it owns the constant rather than sharing
#: ``brand_knowledge_context.INPUT_PREFIX``, which now names the mount.
INPUT_PREFIX = "inputs/brand/knowledge/"

_RECIPE_KEY = "onboarding-synthesis-unit"
_RECIPE_VERSION = 1
_GATE_NODE_KEY = "onboarding_synthesis_interactions"
_PREPARER_WORKER_ID = "agent-onboarding-synthesis-preparer"
_EVIDENCE_TOOL_NAME = "exa_search_evidence"
_EVIDENCE_TOOL_VERSION = "1"

#: Synthesis needs both halves of the brand's story: who the company is, and what it sells.
_REQUIRED_INPUT_KINDS = frozenset({"company-overview", "product-catalog"})

#: The documents every synthesis turn opens with, in the order the model should meet them: who the
#: company is, what it sells, then what its customers say. They are small, they are the client's
#: own story, and no task is honest without them — so they ride the opening context, not the disk
#: alone. (``customer-reviews`` is optional; a brand without one simply has no row.)
_CORE_INPUT_KINDS = ("company-overview", "product-catalog", "customer-reviews")
_ICP_KIND = "icp-definition"
#: The statuses a newly published version may retire. `confirmed` is deliberately absent: it is a
#: human's yes, and some project's pinned ICP. Reads still use the wider `SERVABLE_STATUSES`.
RETIRABLE_STATUSES: tuple[str, ...] = ("ready", "proposed")
#: Per-product research: deep, numerous, and only some of it belongs to a given ICP. It is seeded
#: under ``inputs/`` for the model to read by path, never pushed into the opening context.
_PRODUCT_RESEARCH_KIND = "product-research"

#: The two document kinds this turn may produce, and the durable status each is born with. An ICP
#: is a *proposal* a human confirms; a persona is a derived reading of a confirmed-or-proposed ICP
#: and is simply ready.
_OUTPUT_KINDS: dict[str, tuple[str, str]] = {
    "icp-definition": ("icp", "proposed"),
    "audience-persona": ("persona", "ready"),
}

#: The persona role vocabulary the card names for the model. Kept here, not in ``clue_core.enums``:
#: these are the strings the skills write into persona front matter, and nothing in O4 validates a
#: claim-side ``Persona`` against them.
_PERSONA_VOCABULARY = (
    "economic_buyer",
    "champion",
    "user",
    "technical_evaluator",
    "blocker",
)

_ICP_OBJECTIVE = "Task: icp. Write the ICP documents, then finalize_turn."


async def _no_crash(
    point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del point, execution_id, node_key


def onboarding_project_id(*, workspace_id: str, brand_id: str) -> str:
    """The deterministic per-brand system project id this surface's turns belong to."""

    digest = uuid5(NAMESPACE_URL, f"onboarding-project:{workspace_id}:{brand_id}").hex[:24]
    return f"prj_onb_{digest}"


async def ensure_onboarding_project(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    brand_name: str,
) -> str:
    """Create (idempotently) the per-brand system project an onboarding turn is scoped to.

    ``agent_turn.project_id`` and ``execution.project_id`` are real foreign keys, so a governed
    turn always belongs to a project. Onboarding is not a marketing motion, so the row is born
    ``kind = 'system'`` and ``archived`` (with its ``archived_at``) and carries no product: it is
    a scope anchor, never something a marketer opens — and ``kind`` is what keeps it out of the
    projects directory without anyone having to read its id prefix.
    """

    project_id = onboarding_project_id(workspace_id=workspace_id, brand_id=brand_id)
    await conn.execute(
        text(
            "INSERT INTO project (project_id, workspace_id, brand_id, name, status, kind, "
            "archived_at) "
            "VALUES (:project_id, :workspace_id, :brand_id, :name, 'archived', 'system', now()) "
            "ON CONFLICT (project_id) DO NOTHING"
        ),
        {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "name": f"Onboarding · {brand_name}",
        },
    )
    return project_id


@dataclass(frozen=True, slots=True)
class OnboardingSynthesisResult:
    """One persona turn's outcome — structurally O3's ``SynthesisOutcome``, plus its documents."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    documents: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RegisteredIcp:
    """One ICP document the ICP turn actually registered — the persona turns' work list.

    ``path`` is the document's own path (``audience/icp-<key>.md``), not the workspace path: the
    caller prefixes :data:`INPUT_PREFIX` when it wants the file the model reads.
    """

    document_id: UUID
    icp_key: str
    version: int
    path: str
    #: The ICP's scope: ``None`` for the brand's own ICP, a project id for a project-local variant.
    #: A persona written for that ICP is written in the same scope (Task 4 threads it through).
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class IcpSynthesisResult:
    """The ICP turn's outcome. ``icps`` is empty unless the status is ``completed``."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    icps: tuple[RegisteredIcp, ...]


class _InputSelectionError(Exception):
    """An input the task cannot run without is not there — a typed step failure, never a crash."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _failure_code(error: BaseException) -> str:
    return error.code if isinstance(error, _InputSelectionError) else type(error).__name__


@dataclass(frozen=True, slots=True)
class _TurnInputs:
    """What one turn gets: ``focus`` rides the opening context, ``seeds`` land under ``inputs/``.

    ``seeds`` is always a superset of ``focus`` — a document in context is also on disk, so the
    model can cite it by the path the prompt names instead of by a context hash.
    """

    focus: tuple[dict[str, Any], ...]
    seeds: tuple[dict[str, Any], ...]


def _row_front_matter(row: Mapping[str, Any]) -> dict[str, Any] | None:
    body = row.get("body")
    if body is None:
        return None
    try:
        front, _ = parse_front_matter(body.decode() if isinstance(body, bytes) else str(body))
    except (UnicodeDecodeError, ValueError):
        return None
    return front


def _document_product_ids(row: Mapping[str, Any]) -> frozenset[str] | None:
    """The product ids a knowledge document declares, or ``None`` when it declares none readably.

    ``None`` is the honest answer for an unparseable document *and* for one whose front matter
    simply has no product id: in both cases the selection below cannot tell whether the document
    belongs to an ICP, and the rule is to keep it rather than to silently starve the turn.
    """

    front = _row_front_matter(row)
    if front is None:
        return None
    ids = {
        value
        for value in (
            front.get("product_id"),
            *(front.get("product_ids") or () if isinstance(front.get("product_ids"), list) else ()),
        )
        if isinstance(value, str) and value
    }
    return frozenset(ids) or None


def _row_icp_key(row: Mapping[str, Any]) -> str:
    """The ICP key of an ``icp-definition`` row: its front matter, or its path as the fallback."""

    front = _row_front_matter(row)
    if front is not None:
        _, key = document_identity(front)
        if key is not None:
            return key
    return str(row["path"]).removeprefix("audience/icp-").removesuffix(".md")


def _select_inputs(
    rows: Sequence[dict[str, Any]],
    *,
    task: Literal["icp", "persona"],
    icp: RegisteredIcp | None = None,
    product_ids_of: Callable[[dict[str, Any]], frozenset[str] | None] = _document_product_ids,
) -> _TurnInputs:
    """Choose one turn's context documents and one turn's disk documents.

    Both tasks open on the core three (company overview, product catalog, customer reviews). The
    ICP task then sees **every** ICP on file — that is what makes a re-run refine a profile instead
    of renaming it — and gets every product-research file on disk, because it decides for itself
    which products a profile sells. A persona task sees exactly **one** ICP, and only the
    product-research files that ICP's ``product_ids`` name; a file whose own product id cannot be
    read is kept, because dropping it would silently hide research from the one turn that writes
    about the buyer.

    ``audience-persona`` rows are never selected either way: a persona document is this surface's
    *output*, and feeding the previous one back would let a re-run copy itself.
    """

    core = sorted(
        (row for row in rows if str(row["kind"]) in _CORE_INPUT_KINDS),
        key=lambda row: (_CORE_INPUT_KINDS.index(str(row["kind"])), str(row["path"])),
    )
    icp_rows = sorted(
        (row for row in rows if str(row["kind"]) == _ICP_KIND),
        key=lambda row: str(row["path"]),
    )
    products = sorted(
        (row for row in rows if str(row["kind"]) == _PRODUCT_RESEARCH_KIND),
        key=lambda row: str(row["path"]),
    )

    if task == "icp":
        focus = (*core, *icp_rows)
        return _TurnInputs(focus=focus, seeds=(*focus, *products))

    if icp is None:
        raise ValueError("a persona turn selects its inputs against one registered ICP")
    chosen = next((row for row in icp_rows if row["document_id"] == icp.document_id), None)
    if chosen is None:
        raise _InputSelectionError(
            "icp_document_missing",
            f"the ICP document for {icp.icp_key!r} is not a current brand knowledge document",
        )
    wanted = product_ids_of(chosen)
    focus = (*core, chosen)

    def belongs(row: dict[str, Any]) -> bool:
        own = product_ids_of(row)
        return wanted is None or own is None or bool(own & wanted)

    return _TurnInputs(focus=focus, seeds=(*focus, *(row for row in products if belongs(row))))


class OnboardingSynthesisStepPinProvider(StepPinProvider):
    """Guard the one tool address this surface's dynamic children may carry.

    ``exa_search_evidence@1`` declares ``pin_requirements=("skill",)``: it may be spent only inside
    a slot that pinned the ``audience-persona`` skill telling the model what evidence is *for*.
    **The recipe slot pins that skill statically** (``compatibility.nodes`` of the promoted
    ``onboarding-synthesis-unit@1``), which is what satisfies the executor's requirement check —
    ``missing = descriptor.pin_requirements - static_kinds - supplied_kinds`` — and what the
    execution's compatibility report resolves to the observed digest. So this provider must **not**
    re-observe and re-request that same skill: the executor resolves ``(*static_requests,
    *pin_requests)`` together, and a bare ``skill audience-persona v1`` next to a digest-pinned
    ``skill audience-persona <sha>`` is a ``conflicting_requirement`` that fails every evidence
    call with ``IncompatibleRecipe``. Nothing durable is lost by dropping it, and the provider's
    remaining job is the address guard.
    """

    async def pins_for(
        self,
        step: RecipeStep,
        *,
        ctx: ToolContext,
    ) -> tuple[PinRequest, ...]:
        del ctx  # the pins are the recipe's; this provider only guards the address
        if step.tool_name != _EVIDENCE_TOOL_NAME or step.tool_version != _EVIDENCE_TOOL_VERSION:
            raise ExecutionConflict(
                "the onboarding-synthesis recipe admits only exa_search_evidence@1"
            )
        return step.pin_requests


class _NoMemoryContext:
    """The memory seam with memory switched off: no bodies, no pins, no journal."""

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        del request
        return None

    async def select(
        self, request: AssemblyRequest
    ) -> MemorySelectionPin | MemorySelectionUnavailable:
        del request
        return MemorySelectionUnavailable(reason="memory_disabled")

    async def resolve(
        self, request: AssemblyRequest, pin: MemorySelectionPin
    ) -> MemoryBundle | MemorySelectionStale | MemorySelectionUnavailable:
        del request, pin
        return MemorySelectionUnavailable(reason="memory_disabled")


def onboarding_synthesis_context_policy() -> ContextAssemblyPolicy:
    """The opening-context budget for onboarding-synthesis@v2.

    L3 (project) is generous because the brand card, the budget envelope and the synthesis card
    all land there; L4 (memory) and L6 (conversation) are zero because this surface has neither.

    L5 (focus) is large — 256 KiB under the utf8-byte counter — because the turn's core knowledge
    documents ride it as their own markdown. v1 budgeted 8 KiB there and expected the model to
    ``read_file`` its way to the same bytes; a company overview alone exceeds that, so the layer's
    real job was impossible and every input arrived only as a path — an over-budget candidate was
    then *excluded*, silently, and the honest fix was a budget that fits the documents rather than
    a smaller set of documents.

    Budgets are reported, never enforced (founder ruling 2026-09-14), which is why this is v3: an
    over-budget layer is logged and carried whole, so these seven numbers now say what this surface
    *expects* each layer to cost. The v2 numbers are kept unchanged — a surface whose documents
    routinely blow its own expectation is worth seeing in the log, not worth re-guessing here.
    """

    return ContextAssemblyPolicy(
        version="onboarding-synthesis-context-v3",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (24_000, 8_000, 64_000, 0, 262_144, 0, 12_000),
                strict=True,
            )
        ),
    )


def build_onboarding_synthesis_context(
    *,
    resolved_profile: ResolvedAgentProfile,
    artifacts: DurableAgentArtifactStore,
    cards: DbCompiledContextCardReader,
    conn_factory: ConnFactory = transaction,
) -> DeterministicAgentContextAssembler:
    """Build the L1-L7 assembler for one synthesis turn; no memory, no conversation history."""

    return build_agent_context_assembler(
        resolved_profile=resolved_profile,
        artifacts=artifacts,
        cards=cards,
        memory=_NoMemoryContext(),
        memory_recipe=EXECUTION_NAMESPACE_KEY,
        requested_memory_types=(),
        policy=onboarding_synthesis_context_policy(),
        conn_factory=conn_factory,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


async def _current_input_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """The current servable knowledge documents a turn may read, as mutable input rows.

    One reader of ``brand_knowledge_document`` (``current_knowledge_documents``), two shapes: the
    O6 conversation turn pins the typed refs, while this surface still carries each row through a
    dict it later stamps with the document's own ``body``.

    ``project_id`` is the scope of the ICP the turn is *about*, and it is set only for a persona
    turn whose ICP is a project-local variant. The brand-level reader cannot see such a document
    by construction, so without this union the turn would fail ``icp_document_missing`` on the
    very file it was asked to write about. The project's rows win on a shared path: a project that
    authored its own version of a document reads its own version.
    """

    documents = {
        document.path: document
        for document in await current_knowledge_documents(
            conn, workspace_id=workspace_id, brand_id=brand_id
        )
    }
    if project_id is not None:
        documents.update(
            {
                document.path: document
                for document in await current_project_knowledge_refs(
                    conn, workspace_id=workspace_id, project_id=project_id
                )
            }
        )
    return tuple(
        {
            "document_id": document.document_id,
            "path": document.path,
            "kind": document.kind,
            "version": document.version,
            "artifact_key": document.artifact_key,
            "artifact_sha256": document.artifact_sha256,
        }
        for document in documents.values()
    )


def _objective(
    *,
    task: Literal["icp", "persona"],
    icp: RegisteredIcp | None,
    focus: Sequence[dict[str, Any]],
) -> str:
    """The turn's one instruction, in the exact phrasing onboarding-synthesis@v2 was written for.

    The ICP turn is told which ICPs are already on file and where to read them, because the skill's
    rule is that a re-run *refines* a profile under its existing key rather than renaming it — and
    the model can only honour that if the keys are named in the instruction, not merely present
    somewhere in its context.
    """

    if task == "icp" or icp is None:
        known = [row for row in focus if str(row["kind"]) == _ICP_KIND]
        if not known:
            return _ICP_OBJECTIVE
        listed = "; ".join(
            f"{_row_icp_key(row)} ({INPUT_PREFIX}{row['path']}, version {int(row['version'])})"
            for row in known
        )
        return f"{_ICP_OBJECTIVE} ICPs already on file: {listed}."
    return (
        f"Task: persona:{icp.icp_key}. The ICP is {INPUT_PREFIX}{icp.path}, "
        f"version {icp.version}. Write outputs/audience/persona-{icp.icp_key}.md, "
        "then finalize_turn."
    )


@dataclass(frozen=True, slots=True)
class _TaskOutcome:
    """One governed turn's result, before its outputs are read as documents."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    turn_id: UUID | None
    finalization_ref: ArtifactRef | None


@dataclass(frozen=True, slots=True)
class _RegisteredDocument:
    document_id: UUID
    kind: str
    icp_key: str
    path: str
    version: int


class OnboardingSynthesisLauncher:
    """Prepare every trusted input, then run the governed synthesis turns and register outputs."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageBackend,
        components: AgentPlatformComponents,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        compatibility: CompatibilityLoader,
        plans: DbAgentPlanJournal,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        materializer: AgentResourceMaterializer | None = None,
        checkpointer_factory: CheckpointerFactory = postgres_agent_checkpointer,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._components = components
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._compatibility = compatibility
        self._plans = plans
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._materializer = materializer or AgentResourceMaterializer()
        self._checkpointer_factory = checkpointer_factory
        self._conn_factory = conn_factory

    async def launch_icps(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
    ) -> IcpSynthesisResult:
        """Run the ICP turn and register the profiles it wrote.

        The driver's failure law: every failure is a step outcome, never a raise.
        """

        try:
            return await self._launch_icps(
                workspace_id=workspace_id,
                brand_id=brand_id,
                run_id=run_id,
                step_id=step_id,
            )
        except Exception as error:  # noqa: BLE001 -- a contained step outcome, never a raise
            log.exception(
                "onboarding_synthesis.contained_failure",
                task="icp",
                run_id=str(run_id),
                step_id=str(step_id),
                workspace_id=workspace_id,
            )
            return IcpSynthesisResult(
                "failed",
                _failure_code(error),
                str(error)[:500],
                Decimal(0),
                (),
            )

    async def launch_persona(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
        icp: RegisteredIcp,
    ) -> OnboardingSynthesisResult:
        """Run one persona turn for one registered ICP, and register the document it wrote."""

        try:
            return await self._launch_persona(
                workspace_id=workspace_id,
                brand_id=brand_id,
                run_id=run_id,
                step_id=step_id,
                icp=icp,
            )
        except Exception as error:  # noqa: BLE001 -- a contained step outcome, never a raise
            log.exception(
                "onboarding_synthesis.contained_failure",
                task="persona",
                icp_key=icp.icp_key,
                run_id=str(run_id),
                step_id=str(step_id),
                workspace_id=workspace_id,
            )
            return OnboardingSynthesisResult(
                "failed",
                _failure_code(error),
                str(error)[:500],
                Decimal(0),
                (),
            )

    async def _launch_icps(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
    ) -> IcpSynthesisResult:
        outcome = await self._run_task(
            workspace_id=workspace_id,
            brand_id=brand_id,
            run_id=run_id,
            step_id=step_id,
            task="icp",
            icp=None,
        )
        if outcome.status == "empty":
            return IcpSynthesisResult("empty", None, outcome.failure_message, outcome.cost_usd, ())
        if outcome.turn_id is None or outcome.finalization_ref is None:
            return IcpSynthesisResult(
                "failed",
                outcome.failure_code or "turn_not_completed",
                outcome.failure_message,
                outcome.cost_usd,
                (),
            )
        registered = await self._register_documents(
            workspace_id=workspace_id,
            brand_id=brand_id,
            turn_id=outcome.turn_id,
            finalization_ref=outcome.finalization_ref,
            task="icp",
            icp=None,
        )
        icps = tuple(
            RegisteredIcp(
                document_id=document.document_id,
                icp_key=document.icp_key,
                version=document.version,
                path=document.path,
            )
            for document in registered
            if document.kind == _ICP_KIND
        )
        if not icps:
            return IcpSynthesisResult(
                "empty",
                None,
                "the agent wrote no ICP documents",
                outcome.cost_usd,
                (),
            )
        return IcpSynthesisResult("completed", None, None, outcome.cost_usd, icps)

    async def _launch_persona(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
        icp: RegisteredIcp,
    ) -> OnboardingSynthesisResult:
        outcome = await self._run_task(
            workspace_id=workspace_id,
            brand_id=brand_id,
            run_id=run_id,
            step_id=step_id,
            task="persona",
            icp=icp,
        )
        if outcome.status == "empty":
            return OnboardingSynthesisResult(
                "empty", None, outcome.failure_message, outcome.cost_usd, ()
            )
        if outcome.turn_id is None or outcome.finalization_ref is None:
            return OnboardingSynthesisResult(
                "failed",
                outcome.failure_code or "turn_not_completed",
                outcome.failure_message,
                outcome.cost_usd,
                (),
            )
        registered = await self._register_documents(
            workspace_id=workspace_id,
            brand_id=brand_id,
            turn_id=outcome.turn_id,
            finalization_ref=outcome.finalization_ref,
            task="persona",
            icp=icp,
        )
        if not registered:
            return OnboardingSynthesisResult(
                "empty",
                None,
                "the agent wrote no documents",
                outcome.cost_usd,
                (),
            )
        return OnboardingSynthesisResult(
            "completed",
            None,
            None,
            outcome.cost_usd,
            tuple(document.document_id for document in registered),
        )

    async def _run_task(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
        task: Literal["icp", "persona"],
        icp: RegisteredIcp | None,
    ) -> _TaskOutcome:
        """Run one governed turn for one task. Both public entry points share this whole body."""

        # The ICP turn resolves the `onboarding_icp` surface, which withholds `exa_search_evidence`
        # — that turn writes from the brand's own documents, and the rule is governed by a tool
        # that is not installed rather than by a sentence in a skill. A persona turn resolves the
        # role unnarrowed: its per-role evidence pass is the whole point of the tool.
        if task == "icp":
            resolved = self._components.profiles.resolve(
                AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_ICP_SURFACE
            )
            identity_key = f"{run_id}:icp"
            thread_id = f"onboarding-synthesis-{run_id}-icp"
        elif icp is None:
            raise ValueError("a persona turn needs the ICP it writes about")
        else:
            resolved = self._components.profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS)
            identity_key = f"{run_id}:persona:{icp.icp_key}"
            thread_id = f"onboarding-synthesis-{run_id}-persona-{icp.icp_key}"

        # 1. inputs -----------------------------------------------------------------------------
        async with self._conn_factory() as conn:
            brand = await get_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
            if brand is None:
                raise ValueError("the onboarding brand does not belong to this workspace")
            rows = await _current_input_documents(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                # A persona turn for a project-local ICP also reads that project's own documents:
                # its ICP lives there, not in the brand's set.
                project_id=None if icp is None else icp.project_id,
            )
            # The onboarding run is O3's row. This surface only *reads* it, and only for two
            # honest values: the domain the card names, and the run's own request time (so a
            # replayed launch stamps the same instant its first attempt did). A launch driven
            # before the row exists — the isolated turn-runner test — simply has neither.
            run_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT company_domain, requested_at FROM onboarding_run "
                            "WHERE run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                )
                .mappings()
                .first()
            )
            company_domain = None if run_row is None else run_row["company_domain"]
            requested_at = datetime.now(UTC) if run_row is None else run_row["requested_at"]
            if not {str(row["kind"]) for row in rows} >= _REQUIRED_INPUT_KINDS:
                log.warning(
                    "onboarding_synthesis.no_inputs",
                    task=task,
                    run_id=str(run_id),
                    step_id=str(step_id),
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                )
                return _TaskOutcome("empty", None, "no inputs", Decimal(0), None, None)
            # Every row's bytes are read once, here: the seeds need them, and the selection below
            # reads the product ids out of a document's own front matter.
            for row in rows:
                _, row["body"] = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=str(row["artifact_key"]),
                    workspace_id=workspace_id,
                )
            selected = _select_inputs(rows, task=task, icp=icp)
            input_seeds = tuple(
                WorkspaceSeedFile(
                    path=INPUT_PREFIX + str(row["path"]),
                    content=row["body"],
                    sha256=str(row["artifact_sha256"]),
                    media_type="text/markdown",
                )
                for row in selected.seeds
            )
            # 2. the per-brand system project the turn and its execution belong to.
            project_id = await ensure_onboarding_project(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                brand_name=brand.name,
            )

        # 3. the durable C5 execution -----------------------------------------------------------
        execution_id = ExecutionId(operation_id_from_key(identity_key, EXECUTION_NAMESPACE_KEY))
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key=_RECIPE_KEY,
            version=_RECIPE_VERSION,
        )
        if revision is None:
            raise RuntimeError("promoted onboarding-synthesis-unit@1 is not installed")
        parameter_key, parameter_sha = await self._parameters.snapshot(
            workspace_id=workspace_id,
            parameters={},
        )
        await self._starter.start(
            workspace_id=workspace_id,
            recipe_revision_id=revision.recipe_revision_id,
            parameters={},
            parameter_artifact_key=parameter_key,
            parameter_manifest_hash=parameter_sha,
            actor="agent",
            execution_id=execution_id,
            project_id=project_id,
        )
        await self._drive_execution(execution_id)

        # 4. the isolated one-execution workspace ------------------------------------------------
        lease = self._components.workspaces.acquire(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        try:
            # 5. the four trusted artifacts --------------------------------------------------------
            card_ref = await self._artifact(
                workspace_id,
                SYNTHESIS_CARD_MEDIA_TYPE,
                {
                    "schema_version": "2",
                    "brand_id": brand_id,
                    "company_domain": company_domain,
                    "task": task,
                    "icp": (
                        None
                        if icp is None
                        else {
                            "key": icp.icp_key,
                            "document_id": str(icp.document_id),
                            "version": icp.version,
                        }
                    ),
                    "inputs": [
                        {
                            "path": str(row["path"]),
                            "kind": str(row["kind"]),
                            "version": int(row["version"]),
                        }
                        for row in selected.seeds
                    ],
                    # Two honest lists rather than one: what the model is already holding,
                    # and what it can open. Both are `inputs/` paths, because that is the
                    # path it must cite.
                    "context_paths": [INPUT_PREFIX + str(row["path"]) for row in selected.focus],
                    "seeded_paths": [INPUT_PREFIX + str(row["path"]) for row in selected.seeds],
                    "persona_vocabulary": list(_PERSONA_VOCABULARY),
                },
                project_id,
            )
            budget_ref = await self._artifact(
                workspace_id,
                "application/vnd.clue.agent-budget-envelope+json",
                {"schema_version": "1", "limit_millicents": BUDGET_LIMIT_MILLICENTS},
                project_id,
            )
            manifest_ref = await self._artifact(
                workspace_id,
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
                project_id,
            )
            user_message_ref = await self._artifact(
                workspace_id,
                "application/vnd.clue.agent-turn-input+json",
                {
                    "schema_version": "1",
                    "objective": _objective(task=task, icp=icp, focus=selected.focus),
                    "onboarding_run_id": str(run_id),
                    "onboarding_step_id": str(step_id),
                    "input_paths": [INPUT_PREFIX + str(row["path"]) for row in selected.seeds],
                },
                project_id,
            )

            # 6. the turn request ------------------------------------------------------------------
            turn_id = uuid5(TURN_NAMESPACE, identity_key)
            request = AgentTurnRequest(
                turn_id=turn_id,
                thread_id=thread_id,
                constitution=AgentConstitution(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    execution_id=execution_id,
                    actor_id="system",
                    role=AgentRole.ONBOARDING_SYNTHESIS,
                    brand_id=brand_id,
                    workspace_root_id=lease.identity.workspace_root_id,
                    project_card_ref=card_ref,
                    budget_envelope_ref=budget_ref,
                    profile_ref=resolved.profile_ref,
                    resource_manifest_ref=manifest_ref,
                    resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                ),
                user_message_artifact_ref=user_message_ref,
                # L5: the documents the task cannot be done without, as their own markdown.
                # The exact version is pinned, so a document that moved under us fails loudly
                # instead of serving the model a different text than the one this card names.
                focus_refs=tuple(
                    DomainObjectRef(
                        workspace_id=workspace_id,
                        object_type="brand_knowledge_document",
                        object_id=str(row["document_id"]),
                        version=int(row["version"]),
                    )
                    for row in selected.focus
                ),
                requested_at=requested_at,
            )
            await self._components.turns.create(request=request, profile=resolved.profile)

            # 7. replay short-circuit --------------------------------------------------------------
            outcome = await self._components.turns.load_committed_outcome(
                turn_id=turn_id,
                workspace_id=workspace_id,
            )
            if outcome is None:
                outcome = await self._run_turn(
                    request=request,
                    resolved=resolved,
                    lease=lease,
                    input_seeds=input_seeds,
                )

            # 8. close the durable recipe ----------------------------------------------------------
            await self._complete_recipe_if_needed(outcome)

            cost_usd = await self._cost_usd(execution_id=execution_id, workspace_id=workspace_id)
            if (
                outcome.status is not AgentExecutionStatus.COMPLETED
                or outcome.finalization_ref is None
            ):
                return _TaskOutcome(
                    "failed",
                    outcome.failure_code or "turn_not_completed",
                    f"the synthesis turn ended {outcome.status.value}",
                    cost_usd,
                    None,
                    None,
                )
            return _TaskOutcome(
                "completed", None, None, cost_usd, turn_id, outcome.finalization_ref
            )
        finally:
            lease.release()

    # --- the turn ------------------------------------------------------------------------------

    async def _run_turn(
        self,
        *,
        request: AgentTurnRequest,
        resolved: ResolvedAgentProfile,
        lease: AgentWorkspaceLease,
        input_seeds: tuple[WorkspaceSeedFile, ...],
    ) -> AgentTurnOutcome:
        contexts = build_onboarding_synthesis_context(
            resolved_profile=resolved,
            artifacts=self._components.artifacts,
            # The focus layer compiles each `brand_knowledge_document` from its verified artifact,
            # so this reader needs storage; without it that object type serves nothing at all.
            cards=DbCompiledContextCardReader(
                conn_factory=self._conn_factory,
                storage=self._storage,
            ),
            conn_factory=self._conn_factory,
        )
        context = await contexts.assemble(
            request=request,
            profile=resolved.profile,
            history=(),
        )
        context_seeds = tuple(
            WorkspaceSeedFile(
                path=item.path,
                content=item.data,
                sha256=item.sha256,
                media_type=item.media_type,
            )
            for item in context.materializations
        )
        seed_paths = {*(item.path for item in context_seeds), *(item.path for item in input_seeds)}
        if len(seed_paths) != len(context_seeds) + len(input_seeds):
            raise ValueError("a knowledge-document input collided with a canonical context path")
        seed_files = (*context_seeds, *input_seeds)
        if lease.resources_frozen:
            self._materializer.verify_materialized(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )
        else:
            self._materializer.materialize(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )

        execution = C5AgentExecutionAdapter(
            turn_id=request.turn_id,
            constitution=request.constitution,
            resolved_profile=resolved,
            policy=AgentPlanPolicy.from_profile(
                resolved.profile,
                budget_limit_millicents=BUDGET_LIMIT_MILLICENTS,
                max_fanout=1,
                max_parallelism=1,
                max_rounds=resolved.profile.max_model_rounds,
            ),
            slot_key=_GATE_NODE_KEY,
            tools=self._tools,
            tool_invoker=self._tool_invoker,
            executor=self._executor,
            artifacts=self._components.artifacts,
            journal=self._plans,
            checkpointer_factory=self._checkpointer_factory,
            pin_provider=OnboardingSynthesisStepPinProvider(),
            conn_factory=self._conn_factory,
        )
        execution.bind_finalization_authority(
            AgentFinalizationAuthority(
                lease=lease,
                artifacts=self._components.artifacts,
                turns=self._components.turns,
                crash_hook=_no_crash,
                conn_factory=self._conn_factory,
            )
        )
        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._components.artifacts,
        ).build()
        return await DurableDeepAgentTurnRunner(
            runtime=DeepAgentTurnRuntime(
                compaction_for=compaction_for,
                models=self._components.models,
                execution=execution,
                max_runtime_s=resolved.profile.turn_timeout_s,
                max_rounds=resolved.profile.max_model_rounds,
            ),
            turns=self._components.turns,
            artifacts=self._components.artifacts,
        ).run(
            request=request,
            resolved_profile=resolved,
            context=context,
            lease=lease,
            tools=governed_tools,
        )

    # --- durable recipe ------------------------------------------------------------------------

    async def _complete_recipe_if_needed(self, outcome: AgentTurnOutcome) -> None:
        if outcome.status is not AgentExecutionStatus.COMPLETED:
            return
        try:
            await self._executor.decide_gate(
                execution_id=outcome.execution_id,
                node_key=_GATE_NODE_KEY,
                actor="agent",
                decision="complete",
            )
        except ExecutionConflict:
            # A replayed launch finds the gate already decided. The status assertion below is
            # still the real invariant, so swallowing the second decision hides nothing.
            log.info(
                "onboarding_synthesis.gate_already_decided",
                execution_id=str(outcome.execution_id),
            )
        status = await self._drive_execution(outcome.execution_id)
        if status is not ExecutionStatus.COMPLETED:
            raise RuntimeError("completed synthesis turn did not complete its durable C5 recipe")

    async def _drive_execution(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self._conn_factory() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_PREPARER_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("onboarding-synthesis execution is owned by another live worker")
        try:
            result = await self._executor.execute(
                execution_id,
                worker_id=_PREPARER_WORKER_ID,
                lease_generation=lease.generation,
            )
            return result.status
        finally:
            async with self._conn_factory() as conn:
                await release_work_lease(
                    conn,
                    work_id=WorkId(execution_id),
                    worker_id=_PREPARER_WORKER_ID,
                    generation=LeaseGeneration(lease.generation),
                )

    # --- outputs -------------------------------------------------------------------------------

    async def _register_documents(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        turn_id: UUID,
        finalization_ref: ArtifactRef,
        task: Literal["icp", "persona"],
        icp: RegisteredIcp | None,
    ) -> tuple[_RegisteredDocument, ...]:
        """Turn each finalized output into a versioned ``brand_knowledge_document``.

        An output whose front matter is unreadable, whose ``kind`` is not one this surface may
        produce, or which carries no ``icp_key`` is skipped and logged. It is never a failure: the
        turn's other documents are real, and an unidentifiable file is honestly not a document. An
        ICP whose gate or qualifier rows lost text to an unquoted comma
        (:func:`~clue_api.arv2.icp_authoring.comma_split_rows`) is skipped the same way: stored,
        it would serve half a rule as the whole one to every agent that reads it.

        A persona turn is scoped to exactly one ICP, so two more outputs are skipped there: an
        ``icp-definition`` (the ICP turn is the only authority that registers one — a persona turn
        that writes a profile would silently version over the profile it was asked to write *about*)
        and a persona for some other ICP key. Both are logged and dropped, never registered.

        A re-synthesis at the same path is a new version that **names** the document it replaces
        (``supersedes_document_id``) and then retires it, so the chain is walkable in both
        directions rather than only inferrable from the version ordering.
        """

        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self._components.artifacts.read(finalization_ref)
        )
        registered: list[_RegisteredDocument] = []
        for ref in envelope.output_refs:
            body = await self._components.artifacts.read(ref)
            try:
                front, _ = parse_front_matter(body.decode())
            except (UnicodeDecodeError, ValueError) as error:
                log.warning(
                    "onboarding_synthesis.unreadable_output",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    reason=str(error)[:200],
                )
                continue
            kind, icp_key = document_identity(front)
            naming = _OUTPUT_KINDS.get(kind)
            if naming is None or icp_key is None:
                log.warning(
                    "onboarding_synthesis.unidentifiable_output",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    kind=kind,
                    icp_key=icp_key,
                )
                continue
            damaged = comma_split_rows(front) if kind == _ICP_KIND else ()
            if damaged:
                log.warning(
                    "onboarding_synthesis.comma_split_output",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    icp_key=icp_key,
                    rows=list(damaged),
                )
                continue
            if task == "persona" and kind == _ICP_KIND:
                log.warning(
                    "onboarding_synthesis.persona_wrote_icp",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    icp_key=icp_key,
                )
                continue
            if task == "persona" and icp is not None and icp_key != icp.icp_key:
                log.warning(
                    "onboarding_synthesis.persona_wrote_other_icp",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    icp_key=icp_key,
                    expected_icp_key=icp.icp_key,
                )
                continue
            prefix, status = naming
            path = f"audience/{prefix}-{icp_key}.md"
            # An ICP turn writes the brand's ICPs; a persona turn writes in the scope of the ICP it
            # was asked about, so a project-local ICP's personas are that project's too. The whole
            # version chain below — the next version, the row it supersedes, the rows it retires —
            # is read and written inside that one scope.
            project_id = None if icp is None else icp.project_id
            document_id = uuid5(
                NAMESPACE_URL,
                f"onboarding-synthesis-doc:{turn_id}:{path}",
            )
            async with self._conn_factory() as conn:
                # One read answers both halves of the version chain: the next version number (over
                # every row at this path, whatever its status) and the document this one replaces
                # — the highest-version *servable* row, which the UPDATE below then supersedes.
                # They must agree, or a reader following ``supersedes_document_id`` backwards
                # would walk off a row that was never actually retired.
                lineage = (
                    (
                        await conn.execute(
                            text(
                                "SELECT"
                                "  (SELECT COALESCE(MAX(version), 0) + 1"
                                "     FROM brand_knowledge_document"
                                "    WHERE workspace_id = :workspace_id"
                                "      AND brand_id = :brand_id AND path = :path"
                                "      AND project_id IS NOT DISTINCT FROM :project_id"
                                "  ) AS next_version,"
                                "  (SELECT document_id"
                                "     FROM brand_knowledge_document"
                                "    WHERE workspace_id = :workspace_id"
                                "      AND brand_id = :brand_id AND path = :path"
                                "      AND project_id IS NOT DISTINCT FROM :project_id"
                                "      AND status = ANY(:statuses)"
                                "    ORDER BY version DESC LIMIT 1"
                                "  ) AS supersedes_document_id"
                            ),
                            {
                                "workspace_id": workspace_id,
                                "brand_id": brand_id,
                                "path": path,
                                "project_id": project_id,
                                "statuses": list(SERVABLE_STATUSES),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                version = int(lineage["next_version"])
                supersedes = lineage["supersedes_document_id"]
                source_icp_sha256 = None
                if kind == "audience-persona" and icp is not None:
                    source_icp_sha256 = (
                        await conn.execute(
                            text(
                                "SELECT artifact_sha256 FROM brand_knowledge_document "
                                "WHERE document_id=:doc AND workspace_id=:ws AND brand_id=:brand "
                                "AND kind='icp-definition' "
                                "AND project_id IS NOT DISTINCT FROM :project"
                            ),
                            {
                                "doc": icp.document_id,
                                "ws": workspace_id,
                                "brand": brand_id,
                                "project": project_id,
                            },
                        )
                    ).scalar_one()
                    if source_icp_sha256 is None:
                        raise ValueError("persona source ICP has no artifact digest")
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document ("
                        "  document_id, workspace_id, brand_id, project_id, folder, path, kind, "
                        "  version, status, artifact_key, artifact_sha256, produced_by_turn_id, "
                        "  supersedes_document_id, source_icp_document_id, source_icp_sha256"
                        ") VALUES ("
                        "  :document_id, :workspace_id, :brand_id, :project_id, 'audience', "
                        "  :path, :kind, "
                        "  :version, :status, :artifact_key, :artifact_sha256, :turn_id, "
                        "  :supersedes, :source_icp_document_id, :source_icp_sha256"
                        ") ON CONFLICT (document_id) DO NOTHING"
                    ),
                    {
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                        "brand_id": brand_id,
                        "project_id": project_id,
                        "path": path,
                        "kind": kind,
                        "version": version,
                        "status": status,
                        "artifact_key": ref.artifact_key,
                        "artifact_sha256": ref.sha256,
                        "turn_id": turn_id,
                        "source_icp_document_id": icp.document_id
                        if source_icp_sha256 is not None and icp is not None
                        else None,
                        "source_icp_sha256": source_icp_sha256,
                        # A replayed launch re-reads a chain it already wrote, so the row it would
                        # name is its own; the ON CONFLICT above makes that a no-op either way.
                        "supersedes": None if supersedes == document_id else supersedes,
                    },
                )
                # Re-synthesis retires the drafts it replaces — and only those. A `confirmed`
                # row is a human's yes and some project's pinned ICP (founder rulings
                # 2026-09-10); superseding it here would retire an ICP nobody asked to change and
                # break the launches pinned to it. It stays confirmed beside the new proposal, and
                # the project moves only when a human approves the new one at the gate.
                await conn.execute(
                    text(
                        "UPDATE brand_knowledge_document SET status = 'superseded', "
                        "  updated_at = now() "
                        "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                        "  AND path = :path AND document_id <> :document_id "
                        "  AND status = ANY(:statuses) "
                        "  AND project_id IS NOT DISTINCT FROM :project_id"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "brand_id": brand_id,
                        "path": path,
                        "project_id": project_id,
                        "document_id": document_id,
                        "statuses": list(RETIRABLE_STATUSES),
                    },
                )
                # Read the version back rather than trusting the one we just computed: on a
                # replayed launch the INSERT was a no-op, and the row's own version is the truth a
                # persona turn will cite.
                stored_version = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT version FROM brand_knowledge_document "
                                "WHERE document_id = :document_id"
                            ),
                            {"document_id": document_id},
                        )
                    ).scalar_one()
                )
            registered.append(
                _RegisteredDocument(
                    document_id=document_id,
                    kind=kind,
                    icp_key=icp_key,
                    path=path,
                    version=stored_version,
                )
            )
        return tuple(registered)

    # --- cost ----------------------------------------------------------------------------------

    async def _cost_usd(self, *, execution_id: ExecutionId, workspace_id: str) -> Decimal:
        """Sum the evidence tool's own reported spend across this execution's durable receipts."""

        total = Decimal(0)
        receipts = await self._plans.load_receipts(
            execution_id=execution_id,
            workspace_id=workspace_id,
        )
        for receipt in receipts:
            if receipt.kind != "tool" or not receipt.address.startswith(f"{_EVIDENCE_TOOL_NAME}@"):
                continue
            for ref in receipt.artifact_refs:
                try:
                    payload = json.loads(await self._components.artifacts.read(ref))
                    references = payload.get("references") or {}
                    total += Decimal(str(references.get("cost_usd", "0")))
                except (InvalidOperation, ValueError, AttributeError, TypeError):
                    log.warning(
                        "onboarding_synthesis.unreadable_tool_cost",
                        execution_id=str(execution_id),
                        artifact_key=ref.artifact_key,
                    )
        return total

    # --- helpers -------------------------------------------------------------------------------

    async def _artifact(
        self,
        workspace_id: str,
        media_type: str,
        payload: object,
        project_id: str,
    ) -> ArtifactRef:
        return await self._components.artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            project_bindings=((project_id, "onboarding_synthesis_context"),),
        )

    @classmethod
    async def for_tests(
        cls,
        *,
        conn: AsyncConnection,
        storage: StorageBackend,
        models: Any,
        workspace_root: Path,
    ) -> OnboardingSynthesisLauncher:
        """Compose the real launcher over one test connection, with a scripted model provider.

        Everything here is production wiring: the real toolbelt, profile registry, recipe seeder
        and lifecycle, execution starter, recipe executor, tool invoker, artifact store and
        workspace factory. Exactly three things are substituted, and each for a stated reason —
        the model provider (scripted, so no turn spends real money), the checkpointer (in-memory,
        because the test's rolled-back connection cannot host LangGraph's own tables), and the
        workspace root (a temporary directory rather than ``CLUE_AGENT_WORKSPACE_ROOT``).

        ``build_toolbelt`` is called **without** ``secrets``, so ``exa_search_evidence@1`` is
        composed fail-closed and refuses ``exa_not_configured`` if anything ever calls it.
        """

        from clue_agents import AgentWorkspaceFactory, WorkspaceRootPolicy
        from clue_api.agent_platform_wiring import DbAgentOwnershipRouter
        from clue_api.agent_registry_wiring import build_agent_profile_registry
        from clue_api.agent_turn_wiring import (
            AgentPrivacyService,
            DbAgentHistoryStore,
            DbAgentReplayReader,
            DbAgentTurnJournal,
        )
        from clue_api.execution_wiring import (
            ExecutionRunEventWriter,
            StorageExecutionParameterStore,
            StorageParameterArtifactStore,
            build_tool_invoker,
        )
        from clue_api.recipe_wiring import (
            build_recipe_lifecycle,
            build_recipe_pin_registry,
            load_system_recipe_definitions,
            seed_system_recipes,
        )
        from clue_api.toolbelt_wiring import build_toolbelt
        from clue_config import load_settings
        from clue_execution import DbExecutionJournal, DbRecipeRepository
        from clue_toolbelt import DbIdempotencyStore

        @asynccontextmanager
        async def conn_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        def checkpointer_factory(
            execution_id: ExecutionId,
        ) -> Any:
            del execution_id

            @asynccontextmanager
            async def opened() -> AsyncIterator[BaseCheckpointSaver[str]]:
                yield InMemorySaver()

            return opened()

        settings = load_settings(_env_file=None)
        tools = build_toolbelt(storage=None, gateway=None)
        artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)

        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        source_root = root / "source"
        home_root = root / "home"
        source_root.mkdir(mode=0o700, exist_ok=True)
        home_root.mkdir(mode=0o700, exist_ok=True)
        workspaces = AgentWorkspaceFactory(
            prepared_root=WorkspaceRootPolicy(
                configured_root=root / "runtime",
                source_root=source_root,
                home_root=home_root,
            ).prepare(),
            artifact_sink=artifacts,
        )

        pin_registry = build_recipe_pin_registry(tool_registry=tools, conn_factory=conn_factory)
        compatibility = CompatibilityLoader(pin_registry)
        await seed_system_recipes(
            repository=DbRecipeRepository(conn_factory=conn_factory),
            lifecycle=build_recipe_lifecycle(
                tool_registry=tools,
                conn_factory=conn_factory,
                pin_registry=pin_registry,
            ),
            definitions=[
                definition
                for definition in load_system_recipe_definitions()
                if definition.recipe_key == _RECIPE_KEY
            ],
        )
        journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
        parameters = StorageExecutionParameterStore(
            StorageParameterArtifactStore(storage=storage, conn_factory=conn_factory)
        )
        tool_invoker = build_tool_invoker(
            registry=tools,
            idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
            storage=storage,
            settings=settings,
            conn_factory=conn_factory,
        )
        recipes = DbRecipeReader(conn_factory=conn_factory)
        components = AgentPlatformComponents(
            profiles=build_agent_profile_registry(tools),
            models=models,
            workspaces=workspaces,
            artifacts=artifacts,
            turns=DbAgentTurnJournal(conn_factory=conn_factory),
            history=DbAgentHistoryStore(conn_factory=conn_factory),
            replay=DbAgentReplayReader(storage=storage, conn_factory=conn_factory),
            privacy=AgentPrivacyService(
                storage=storage,
                workspaces=workspaces,
                conn_factory=conn_factory,
            ),
            ownership=DbAgentOwnershipRouter(settings=settings, conn_factory=conn_factory),
        )
        return cls(
            settings=settings,
            storage=storage,
            components=components,
            tools=tools,
            tool_invoker=tool_invoker,
            executor=RecipeExecutor(
                conn_factory=conn_factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
                parameters=parameters,
                tool_invoker=tool_invoker,
                max_concurrency=1,
            ),
            compatibility=compatibility,
            plans=DbAgentPlanJournal(conn_factory=conn_factory),
            recipes=recipes,
            starter=DbExecutionStarter(
                conn_factory=conn_factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
            ),
            parameters=parameters,
            checkpointer_factory=checkpointer_factory,
            conn_factory=conn_factory,
        )


def build_onboarding_synthesis_launcher(
    *,
    settings: Settings,
    secrets: Secrets,
    storage: StorageBackend,
    components: AgentPlatformComponents,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    plans: DbAgentPlanJournal,
    recipes: DbRecipeReader,
    starter: DbExecutionStarter,
    parameters: ExecutionParameterStore,
    conn_factory: ConnFactory = transaction,
) -> OnboardingSynthesisLauncher:
    """The production seam the onboarding driver (O3) composes at the API/fleet root."""

    del secrets  # the turn spends only through governed tools, which own their own credentials
    return OnboardingSynthesisLauncher(
        settings=settings,
        storage=storage,
        components=components,
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        compatibility=compatibility,
        plans=plans,
        recipes=recipes,
        starter=starter,
        parameters=parameters,
        conn_factory=conn_factory,
    )
