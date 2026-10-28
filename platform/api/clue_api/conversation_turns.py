"""One platform-deepagent **conversation turn** — the composition and the execution path.

FI Lane D slice **D2**. Two surfaces run the same Head-of-ABM conversation over the same durable
substrate: the dev-only stage-0 trial harness (`clue_api.stage0_trial`, ratified §6-D6) and the
production project conversation the fleet worker executes
(`clue_api.agent_turn_fleet_wiring`). Before this module they would have been two copies of the
same twelve steps; the charter names that duplication as the trial's defect (§1.2) and D2's job is
to leave exactly one implementation:

* :mod:`clue_api.conversation_capture` — the capture-before-spend half, which lives in its own
  module precisely so the HTTP process can import it without importing anything model-shaped.
* :class:`ConversationTurnEngine` — the execution half, and the thing that is **composed once**.
  The trial rebuilds it per request because it is a per-session CLI harness; the fleet worker
  builds it at startup and reuses it for every turn, which is the whole point of §3-P3.

What is deliberately *not* here: how a turn's identity, project card, budget envelope and
constitution are assembled. Those differ per surface (the trial has a Stage-0 project card and a
local session file; production reads durable project state), so each surface builds its own
:class:`~clue_agents.AgentTurnRequest` and hands it to the same engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid5

from clue_agents import (
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceLease,
    ArtifactRef,
    ContextAssemblyPolicy,
    DelegationRequest,
    DelegationResult,
    DeterministicAgentContextAssembler,
    HistoryMessageRef,
    MountRequest,
    ResolvedAgentProfile,
    WorkspaceSeedFile,
)
from clue_agents.contracts import ContinuationRef
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_execution_wiring import (
    C5AgentExecutionAdapter,
    DbAgentPlanJournal,
    FreshWakeChildRunner,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_context_assembler,
)
from clue_api.agent_runtime_wiring import (
    PROJECT_DOCUMENT_OBJECT_TYPE,
    CompletionGuard,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.attachment_binding import DbAttachmentDescriber
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_api.conversation_continuation import (
    continuation_config_for,
    find_resume_point,
    gap_history,
)
from clue_api.conversation_naming import (
    ConversationNamer,
    NamingOutcome,
    NamingRequest,
    TurnNamingLauncher,
)
from clue_api.conversation_naming import (
    log as naming_log,
)
from clue_api.design_leg_wiring import load_head_of_abm_history
from clue_api.head_of_abm_wiring import (
    HeadOfAbmStage0Runtime,
    build_head_of_abm_stage0_execution,
)
from clue_api.turn_binding import CapturedTurnBinder
from clue_core import ContextAssembly, ExecutionId, MemoryType
from clue_db import ConnFactory, transaction
from clue_execution import CompatibilityLoader, RecipeExecutor
from clue_obs import get_logger
from clue_toolbelt import ToolInvoker, ToolRegistry

__all__ = [
    "CONVERSATION_RECIPE_KEY",
    "CONVERSATION_RECIPE_VERSION",
    "ConversationTurnEngine",
    "ConversationTurnResult",
    "DelegationWithheld",
    "build_conversation_turn_engine",
]

#: The promoted Recipe-#0 revision every Head-of-ABM conversation runs, on both surfaces. It is one
#: constant because it is one fact: the C5 interaction slot's tool allowlist lives in that revision,
#: so a tool granted on a profile but absent from the pinned revision is rejected at plan validation
#: (``c5_tool_not_allowed``). Two surfaces pinning two revisions would mean two different sets of
#: callable tools for the same role, discovered only at the first refused plan.
#:
#: **v8** is the current hardening revision: v7 added trusted readiness/synthesis @2 and v8 adds
#: ``open_icp_confirmation_gate@1``. As with the earlier **v6** Option-B kickoff widening —
#: ``draft_account_research_directive@3``, ``open_directive_confirmation_gate@1``,
#: ``launch_account_research@1`` — because a surface grant alone is not enough: the C5 slot is a
#: second, independent ceiling, and until this revision the widened conversation surface would have
#: shown the model three tools that plan validation then refused. The trial surface still withholds
#: all three, so raising the shared ceiling grants the trial nothing.
#:
#: **v7** (PD-part3 P3.4) adds ``open_design_leg@1`` — the design delegation entry — under the
#: same rule. The trial surface withholds it too, so the shared ceiling again grants the trial
#: nothing.
CONVERSATION_RECIPE_KEY = "recipe0-stage0"
# Revision 22 (ARV2 onboarding O6) is revision 19 plus the new-lane onboarding surface — the
# set-valued product gate, the artifact-shaped ICP confirmation gate (``@2``) and the ARV2
# launch/read pair — and it re-pins the directive draft at ``draft_account_research_directive@5``
# (profile v43 pinned @5 while revision 19 admitted only @3, so plan validation refused the draft
# since the R0 merge). The ICP gate is *re-pinned*, not added twice: one requirement set resolves
# one version per (kind, key), so ``@1`` leaves revision 22. Revision 19 keeps ``@1`` and stays the
# exact replay input for turns already pinned to it.
# Revision 21 (Slice B browser-gate repair) is revision 20 with
# ``draft_account_research_directive@5`` — @4's contract behind a satisfiable schema
# (``directive.field_keys`` omittable) — in place of @4. Seeded replay-only: the active revision
# stays 19.
# Revision 20 (Slice B wave 2) is revision 16 with ``draft_account_research_directive@4`` — the
# comprehensive-profile directive contract — in place of @3. Seeded replay-only.
# Revision 19 (genad2) re-pins the delegation entry at ``open_design_leg@4`` — the same tool once
# more, promoted so a document-less ``doc_kind='scene'`` open births a ZERO-PAGE document the
# design agent then authors pages into (the format inputs are gone). Revision 18 stays the exact
# replay input for turns already pinned to it.
# Revision 18 (genad) re-pins the delegation entry at ``open_design_leg@3`` — the same tool again,
# promoted so a document-less ``doc_kind='scene'`` open can BIRTH its ad document at a named
# format. Revision 17 stays the exact replay input for turns already pinned to it.
# Revision 17 (genweb slice 2) re-pins the delegation entry at ``open_design_leg@2`` — the same
# tool, promoted so a document-less open can BIRTH its web document. The slot pins an exact
# address, so the promotion needs its own revision; revision 16 stays the exact replay input for
# turns already pinned to it.
# Revision 16 (part-iii merge) is revision 15 plus the ``open_design_leg@1`` delegation entry
# (PD-part3 P3.4's colliding v7, re-versioned onto the v15 lineage at the integration merge).
# Revision 14 keeps the current-message Account launch path usable after discovery by admitting
# the two read-only account-research tools already exposed by the promoted profile/skill. Revision
# 13 remains the exact replay input for turns that were already pinned to it.
# Revision 23 (ARV2 Track R, R4) is revision 22 plus one exact address:
# ``launch_arv2_discovery@1``, the verified account discovery `head-of-abm@v45` grants and
# stage0-interview v22 §7b teaches. The slot pins exact addresses, so a granted tool the
# promoted revision does not admit is refused by plan validation; v22 stays the exact replay
# input for turns already pinned to it.
# Revision 24 (ARV2 context and authoring) is revision 23 plus two exact addresses:
# ``author_icp_document@1`` and ``request_persona_synthesis@1``, the ICP-authoring pair
# `head-of-abm@v46` grants and stage0-interview v23 §5b/§5c teach. v23 stays the exact replay
# input for turns already pinned to it.
# Revision 25 (the project plan) is revision 24 plus one exact address:
# ``write_project_document@1``, the plan tool `head-of-abm@v47` grants and stage0-interview v24
# §6b teaches. v24 stays the exact replay input for turns already pinned to it.
# Revision 26 (the ARV2 reads) is revision 25 plus three exact addresses:
# ``read_project_accounts@1``, ``read_account_research@1`` and ``read_discovery_run@1``, the
# effect-free reads `head-of-abm@v48` grants and stage0-interview v25 §7b/§7c teach. v25 stays the
# exact replay input for turns already pinned to it. The reads' fix waves minted
# `head-of-abm@v49` / stage0-interview v26 and then `head-of-abm@v50` / stage0-interview v27, but
# NOT a revision 27: a recipe pins tool ADDRESSES, and no address moved — only the three tools'
# schema digests, which the profile and the skill pin and this file does not. The thread-workspace
# wave (`head-of-abm@v51` / stage0-interview v28) mints no revision either, for the same reason:
# it moves the profile's workspace block and the skill's §1 text, not a tool address. Nor does the
# workspace-libraries wave (`head-of-abm@v52` / stage0-interview v29 / prompt head-of-abm v9): it
# grants the `brand/` and `project/` read-only mounts and renames the paths the skill and the
# prompt tell the model to read, and again no tool address moves. Nor does the brand-index-path
# fix (`head-of-abm@v53` / stage0-interview v30): it corrects one path the skill names.
# Nor does the operating manual (`head-of-abm@v54` / stage0-interview v31 / prompt head-of-abm
# v10): it pins fifteen `manual-*@v1` chapters, each granting no tool, and edits prompt and skill
# prose. No tool address is added, dropped or moved.
# Revision 27 (the versioned project root) is the first revision that REMOVES addresses:
# ``author_icp_document@1``, ``request_persona_synthesis@1`` and ``write_project_document@1``
# leave the interaction slot, because `head-of-abm@v55` no longer grants them — the three
# documents they wrote are written as files under the versioned ``project/`` mount, taught by
# `icp-authoring@v1`, `persona-authoring@v1` and `plan-authoring@v1` and pointed at from
# stage0-interview v32 §5b/§5c/§6b. v26 stays the exact replay input for turns already pinned to
# it, so a replayed turn still resolves all three.
# Revision 28 (paged and spilled reads) re-pins two and adds two: ``read_account_research`` and
# ``read_discovery_run`` move to their paged ``@2``, the contracts `head-of-abm@v56` grants, and
# ``read_claims@1`` and ``read_artifact@1`` join, granted for the first time at that version. The
# two ``@1``s leave the slot rather than stand beside their ``@2``s — one version per ``(kind,
# key)`` resolves, so both at once is a ``conflicting_requirement`` — and v27 stays the exact
# replay input for turns pinned to it.
# Revision 29 (the code sandbox) admits one address and removes none: ``run_python@1``, granted
# for the first time at `head-of-abm@v58`, so a turn can open a PDF, a deck or a spreadsheet the
# human attached instead of guessing from its filename. v28 stays the exact replay input for
# turns pinned to it.
# Revision 30 (multi-artifact legs) re-pins one address: ``open_design_leg`` moves to ``@5``, the
# contract `head-of-abm@v59` grants — the top-level ``title`` is gone and the input carries an
# ``artifacts`` list, so one open births one document per item. ``@4`` leaves the slot rather than
# stand beside ``@5``, for the reason revision 22 recorded: one version per ``(kind, key)``
# resolves, so both at once is a ``conflicting_requirement``. ``run_python@1`` stays where
# revision 29 put it. v29 stays the exact replay input for turns pinned to it.
# Revision 32 (web search, 2026-09-22) admits one address and removes none: ``web_search@1``.
# Revision 33 (agent-authored discovery, 2026-09-30) RE-PINS two addresses and adds none:
# ``launch_arv2_discovery`` moves to ``@2`` (the brief the Head of ABM writes) and
# ``read_discovery_run`` to ``@3`` (summary, end reason, exclusions), the contracts
# `head-of-abm@v70` grants. The old versions leave rather than stand beside them (one version
# per ``(kind, key)``); they stay registered, so v32 stays the exact replay input for turns
# pinned to it.
# Revision 34 (product management, 2026-10-15) admits one address and removes none:
# ``manage_products@1``, granted by `head-of-abm@v71`.
# Revision 35 (discovery excludes the seller's customers, 2026-10-16) RE-PINS one address and adds
# none: ``launch_arv2_discovery@3``, whose brief carries ``exclude``, granted by `head-of-abm@v72`.
# Revision 36 (CRM integration Phase 1, 2026-10-20) admits four addresses and removes none:
# ``connect_crm@1``, ``find_crm_actions@1``, ``run_crm_action@1`` and ``write_brand_document@1``,
# granted by `head-of-abm@v76`.
# Revision 37 (CRM integration Phase 2, 2026-10-22) admits three addresses and removes none:
# ``propose_crm_changes@1``, ``crm_write_log@1`` and ``manage_crm_grants@1``, granted by
# `head-of-abm@v77`.
# Revision 38 (CRM integration Phase 3, 2026-10-23) admits three addresses and removes none:
# ``read_crm_targets@1``, ``find_crm_list@1`` and ``link_crm_list@1``, granted by
# `head-of-abm@v78`.
# Revision 39 (CRM integration Phase 3 Task 10, 2026-10-24) admits and removes no address: it
# moves with `head-of-abm@v79` (`crm-writing` v3, `manual-*@v25`).
# Revision 40 (CRM integration Phase 3 Task 11, 2026-10-24) admits and removes no address: it
# moves with `head-of-abm@v80` (`stage0-interview` v53, `manual-*@v26`).
# Revision 41 (CRM integration Phase 3 Task 12, 2026-10-24) admits and removes no address: it
# moves with `head-of-abm@v81` (`crm-writing` v4, `stage0-interview` v54, `manual-*@v27`).
# Revision 42 (CRM integration Phase 4 Task 6, 2026-10-25) admits one address and removes none:
# ``propose_clue_fields_setup@1``, granted by `head-of-abm@v82`.
# Revision 43 (CRM integration Phase 4 follow-up, 2026-10-25) admits and removes no address: it
# moves with `head-of-abm@v83` (`crm-writing` v6, `stage0-interview` v56, `manual-*@v29`).
# Revision 44 (F3 merged onto CRM Phase 4, 2026-10-25) admits and removes no address: it moves
# with `head-of-abm@v84` (F3's workspace text, `stage0-interview` v57, `manual-*@v30`).
# Revision 45 (founder ruling R-14.6, 2026-10-25) admits and removes no address: it moves with
# `head-of-abm@v85` ("Clue fit level": `crm-writing` v7, `stage0-interview` v58, `manual-*@v31`).
# Revision 46 (2026-10-27, main merged into the CRM line) admits and removes no address: it moves
# with `head-of-abm@v86` (main's prompt v19, `stage0-interview` v59, `manual-*@v32`).
# Revision 47 (site agent alignment R1.2, 2026-10-28) admits and removes no address: it moves with
# `head-of-abm@v87` (the page brief opens with who the page is for, `stage0-interview` v60,
# `manual-*@v33`).
CONVERSATION_RECIPE_VERSION = 47

#: What the human calls a document written *before* the free-flowing writer landed. A plan-3
#: receipt carries no title on its refs — the field did not exist — and its three object types were
#: the platform's word for what the document was. Replaying such a turn must still draw the card
#: the human saw, so those three names survive here and nowhere else. A document written since
#: carries its own title (:class:`~clue_agents.contracts.DomainObjectRef`), and nothing is looked
#: up for it.
_LEGACY_DOCUMENT_TITLES: Mapping[str, str] = MappingProxyType(
    {
        PROJECT_DOCUMENT_OBJECT_TYPE: "Plan",
        "project_icp_document": "ICP",
        "project_persona_document": "Personas",
    }
)

#: Finalization ``domain_refs`` object types that render as a §3.4 ``plan`` part. Deliberately a
#: closed set: an unknown object type is *not* projected, because a card whose contents the surface
#: cannot describe is worse than no card. D4's directive/gate objects extend this.
_PLAN_OBJECT_TYPES: frozenset[str] = frozenset(
    {"research_directive", "agent_plan", "plan", *_LEGACY_DOCUMENT_TITLES}
)


class DelegationWithheld:
    """The unreachable backstop for a conversation surface that withholds every delegable role.

    Both conversation surfaces withhold ``RESEARCH`` / ``CONTENT_DRAFTER`` / ``REVIEWER``
    (``C6_SURFACE_POLICIES``), so ``delegation_roles`` is empty, ``delegate_specialist`` is not in
    the middleware's allowed set, and no delegation can be constructed to hand a child runner. This
    stays only because :class:`~clue_api.head_of_abm_wiring.HeadOfAbmStage0Runtime` requires a child
    runner and "there is no runner" is not expressible — it is a backstop, not the fence.
    Restriction by crash is what ruling §2.4 rejects; the withheld roles are the actual mechanism.
    """

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: Any,
    ) -> DelegationResult:
        del request, child_execution_id, resolved_profile
        raise RuntimeError("specialist_delegation_withheld_on_conversation_surface")


log = get_logger("clue_api.conversation_turns")


@dataclass(frozen=True, slots=True)
class ConversationTurnResult:
    """One executed (or replayed) turn."""

    outcome: AgentTurnOutcome
    assistant_message: str | None
    #: ``True`` when the turn already had a committed finalization and was **not** re-executed.
    replayed: bool


class ConversationTurnEngine:
    """The composed-once Head-of-ABM conversation runtime, and the one turn execution path.

    Everything expensive — the resolved profile and its resource manifest, the captured-turn
    binder, the seven-layer context assembler, the deepagent runtime — is built by
    :func:`build_conversation_turn_engine` and then reused. The fleet worker builds exactly one of
    these at startup; nothing about it is per-turn or per-workspace, because the per-turn scope
    travels in the :class:`~clue_agents.AgentTurnRequest`.
    """

    def __init__(
        self,
        *,
        surface: str,
        resolved: ResolvedAgentProfile,
        components: AgentPlatformComponents,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        compatibility: CompatibilityLoader,
        contexts: DeterministicAgentContextAssembler,
        runtime: HeadOfAbmStage0Runtime,
        captured_turns: CapturedTurnBinder,
        plans: DbAgentPlanJournal,
        namer: ConversationNamer | None = None,
        continuation_enabled: bool = False,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self.surface = surface
        # Spec 2026-09-29 §3.1: a turn continues the thread's last completed turn's saved
        # conversation instead of rebuilding it (the production conversation only).
        self._continuation_enabled = continuation_enabled
        self.resolved = resolved
        self.components = components
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._compatibility = compatibility
        self._contexts = contexts
        self._runtime = runtime
        self._captured_turns = captured_turns
        self._plans = plans
        # Conversation naming (2026-09-18 §4.1): a service step beside the turn, never inside it.
        # Without a namer the launcher is a no-op and every chat keeps its placeholder name.
        self._naming = TurnNamingLauncher(namer=namer)
        self._conn_factory = conn_factory

    @property
    def artifacts(self) -> DurableAgentArtifactStore:
        return self.components.artifacts

    async def replay_committed(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        actor_id: str,
        user_message_artifact_ref: ArtifactRef,
        stream: TurnStreamEmitter | None = None,
    ) -> ConversationTurnResult | None:
        """Return an already committed turn before current state is recomposed.

        The production fleet calls this immediately after reading the immutable submission. That
        ordering is load-bearing for context replay: a retry after background recon advanced the
        Client-KB must not compile vN+1 cards for a turn whose durable receipt names vN. It also
        avoids re-driving a recipe execution that the original completed turn already closed.

        History append remains here because a process may have committed finalization authority
        and crashed before projecting the canonical user/assistant messages. Both appends are
        derived-id idempotent, exactly like the later in-execution replay path.
        """

        receipt = await self.components.turns.load(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if receipt is None:
            return None
        if (
            receipt.project_id != project_id
            or receipt.thread_id != thread_id
            or receipt.actor_id != actor_id
        ):
            raise ValueError("committed turn replay scope differs from its immutable submission")
        committed = await self.components.turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if committed is None:
            return None
        await self.components.history.append(
            message_id=uuid5(turn_id, "user"),
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            role="user",
            body_ref=user_message_artifact_ref,
        )
        if stream is not None:
            await stream.turn_started()
        return await self._result_from_outcome(
            outcome=committed,
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            stream=stream,
            replayed=True,
        )

    async def execute(
        self,
        *,
        request: AgentTurnRequest,
        lease: AgentWorkspaceLease,
        budget_limit_millicents: int,
        completion_guard: CompletionGuard | None = None,
        submitted_by_user_id: str | None = None,
        submitted_via_membership_id: str | None = None,
        stream: TurnStreamEmitter | None = None,
        input_seeds: tuple[WorkspaceSeedFile, ...] = (),
        mounts: MountRequest | None = None,
    ) -> ConversationTurnResult:
        """Run one turn, honouring the committed-outcome replay short-circuit.

        The short-circuit is the crash-safety contract: a turn that already holds an authoritative
        :class:`agent_finalization_commit` is **never executed a second time**, whatever re-enters
        here — a retried fleet task, a restarted process, a duplicate submission. The load is a
        pure read of the immutable commit joined to its live envelope artifact (an unfinalized
        failed turn deliberately returns ``None``, so an honest retry can resume its durable model
        checkpoint instead of manufacturing success).

        History is appended around that short-circuit rather than inside it, so a replayed turn
        re-projects the same two thread messages by their derived ids (``uuid5(turn_id, role)``)
        instead of duplicating them.

        ``stream`` (FI Lane D D3, charter §3-P4) is the live projection of this turn onto the
        durable event outbox. It is optional and never authoritative: every emission is best-effort
        by construction, and a turn's committed outcome is identical whether anybody was watching.

        ``input_seeds`` (ARV2 onboarding O6) are the surface's read-only workspace inputs for this
        turn. The engine only forwards them: what they are, and how they were pinned, belongs to
        the surface that composed them.

        ``mounts`` (spec 2026-09-19 §3.4) is the exact :class:`~clue_agents.MountRequest` the
        caller acquired ``lease`` with. It is what lets this method derive the turn's host
        directories for the code sandbox — the tool is handed ids, never handles, so the paths
        have to be registered here, under the turn's execution id, while the lease is held. A
        caller that passes none registers nothing and ``run_python@1`` refuses by name, which is
        the honest answer: a mount table nobody named is a guess.
        """

        constitution = request.constitution
        workspace_id = constitution.workspace_id
        # P3.4 (PD-part3 §2.4): the conversation surface's history is role-scoped — head-of-abm
        # assembles its own turns and never ingests a design leg's transcript. While a leg is
        # open this engine does not run at all (the routing rule sends the message to Design);
        # this load is what keeps the exclusion true after the leg closes.
        prior_history = await load_head_of_abm_history(
            self._conn_factory,
            workspace_id=workspace_id,
            thread_id=request.thread_id,
        )
        await self.components.turns.create(
            request=request,
            profile=self.resolved.profile,
            submitted_by_user_id=submitted_by_user_id,
            submitted_via_membership_id=submitted_via_membership_id,
        )
        await self.components.history.append(
            message_id=uuid5(request.turn_id, "user"),
            turn_id=request.turn_id,
            workspace_id=workspace_id,
            thread_id=request.thread_id,
            role="user",
            body_ref=request.user_message_artifact_ref,
        )
        committed = await self.components.turns.load_committed_outcome(
            turn_id=request.turn_id,
            workspace_id=workspace_id,
        )
        if stream is not None:
            await stream.turn_started()
        if committed is None:
            # The code sandbox and the CRM read sinks are bound to this execution by the
            # workspace factory itself, for exactly the life of the lease (F3, WS-14; AW-8.2):
            # ``acquire_restored`` binds them and the release unbinds them, so this engine binds
            # nothing of its own.
            execution = build_head_of_abm_stage0_execution(
                request=request,
                profiles=self.components.profiles,
                tools=self._tools,
                tool_invoker=self._tool_invoker,
                executor=self._executor,
                compatibility=self._compatibility,
                artifacts=self.components.artifacts,
                plans=self._plans,
                checkpointer_factory=postgres_agent_checkpointer,
                budget_limit_millicents=budget_limit_millicents,
                captured_turns=self._captured_turns,
                surface=self.surface,
                # The thread's own workspace is where a governed result too large for its
                # receipt lands: `reads/<operation>.json`, readable by the model, written by
                # nobody else.
                spill_sink=lease.backend,
                conn_factory=self._conn_factory,
            )
            # Continue or open fresh — decided before assembly, because a turn has exactly one
            # opening-context receipt (spec 2026-09-29 §3.1).
            history, continuation, continuation_config = await self._continuation_for(
                request=request, lease=lease, execution=execution, fresh_history=prior_history
            )
            context = await self._contexts.assemble(
                request=request,
                profile=self.resolved.profile,
                history=history,
                continuation=continuation,
            )
            outcome = await self._runtime.run(
                request=request,
                context=context,
                lease=lease,
                execution=execution,
                completion_guard=completion_guard,
                stream=stream,
                input_seeds=input_seeds,
                continuation_config=continuation_config,
            )
        else:
            outcome = committed
        return await self._result_from_outcome(
            outcome=outcome,
            turn_id=request.turn_id,
            workspace_id=workspace_id,
            thread_id=request.thread_id,
            stream=stream,
            replayed=committed is not None,
            naming_scope=(request.constitution.project_id, request.user_message_artifact_ref),
        )

    async def _continuation_for(
        self,
        *,
        request: AgentTurnRequest,
        lease: AgentWorkspaceLease,
        execution: C5AgentExecutionAdapter,
        fresh_history: tuple[HistoryMessageRef, ...],
    ) -> tuple[tuple[HistoryMessageRef, ...], ContinuationRef | None, dict[str, Any] | None]:
        """The history this turn opens with, and what it continues (if anything).

        Continues the thread's latest completed Head-of-ABM turn under the same profile, prompt
        and tool surface when its saved conversation is settled; otherwise the turn opens fresh
        with the whole thread history, exactly as before.
        """
        if not self._continuation_enabled:
            return fresh_history, None, None
        constitution = request.constitution
        async with self._conn_factory() as conn:
            point = await find_resume_point(
                conn,
                workspace_id=constitution.workspace_id,
                thread_id=request.thread_id,
                current_turn_id=request.turn_id,
                profile_name=constitution.profile_ref.name,
                profile_version=constitution.profile_ref.version,
                profile_sha256=constitution.profile_ref.sha256,
                resource_manifest_sha256=constitution.resource_manifest_sha256,
            )
        if point is None:
            return fresh_history, None, None
        config = continuation_config_for(point)
        # Missing, unsettled or unreadable all open fresh (spec §3.1). An unreadable one must not
        # fail the turn: the resume point would not change, so every later turn would fail too.
        try:
            settled = await self._runtime.continuation_is_settled(
                request=request, lease=lease, execution=execution, continuation_config=config
            )
            reason = "saved_conversation_not_settled"
        except Exception:
            log.warning(
                "agent_turn.continuation_unreadable",
                turn_id=str(request.turn_id),
                resume_turn_id=str(point.turn_id),
                exc_info=True,
            )
            settled = False
            reason = "saved_conversation_unreadable"
        if not settled:
            log.warning(
                "agent_turn.continuation_fallback",
                turn_id=str(request.turn_id),
                resume_turn_id=str(point.turn_id),
                reason=reason,
            )
            return fresh_history, None, None
        async with self._conn_factory() as conn:
            gap = await gap_history(
                conn,
                workspace_id=constitution.workspace_id,
                thread_id=request.thread_id,
                after_sequence=point.last_message_sequence,
                current_turn_id=request.turn_id,
            )
        continuation = ContinuationRef(
            turn_id=point.turn_id,
            execution_id=ExecutionId(point.execution_id),
            gap_message_ids=tuple(item.message_id for item in gap),
        )
        return gap, continuation, config

    async def _result_from_outcome(
        self,
        *,
        outcome: AgentTurnOutcome,
        turn_id: UUID,
        workspace_id: str,
        thread_id: str,
        stream: TurnStreamEmitter | None,
        replayed: bool,
        naming_scope: tuple[str, ArtifactRef] | None = None,
    ) -> ConversationTurnResult:
        """Resolve one durable outcome into its canonical message and optional projection.

        ``naming_scope`` is what conversation naming needs and this method does not otherwise
        read: the turn's project and the artifact holding what the human wrote. Only ``execute``
        passes it — a replayed turn was already named by the process that first completed it.
        """

        assistant_message: str | None = None
        envelope: AgentFinalizeEnvelope | None = None
        if outcome.finalization_ref is not None:
            envelope = AgentFinalizeEnvelope.model_validate_json(
                await self.components.artifacts.read(outcome.finalization_ref)
            )
            if envelope.user_message_artifact_ref is not None:
                assistant_message = (
                    await self.components.artifacts.read(envelope.user_message_artifact_ref)
                ).decode()
                await self.components.history.append(
                    message_id=uuid5(turn_id, "assistant"),
                    turn_id=turn_id,
                    workspace_id=workspace_id,
                    thread_id=thread_id,
                    role="assistant",
                    body_ref=envelope.user_message_artifact_ref,
                )
        naming_task = None
        if (
            naming_scope is not None
            and not replayed
            and assistant_message
            and outcome.status
            in (AgentExecutionStatus.COMPLETED, AgentExecutionStatus.AWAITING_INPUT)
        ):
            # §4.10: nothing on the naming path may raise into the turn — and this read is on
            # the turn's own path, ahead of the launcher's own guard. A turn that already
            # produced its reply must not fail because the message it was answering could not be
            # re-read; it simply goes unnamed.
            try:
                project_id, user_message_ref = naming_scope
                user_message = (await self.components.artifacts.read(user_message_ref)).decode()
                naming_task = self._naming.start(
                    NamingRequest(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        user_message=user_message,
                        assistant_message=assistant_message,
                    )
                )
            except Exception:  # noqa: BLE001 — a naming failure is a skip, never a turn error
                naming_log.warning(
                    "conversation_naming.skipped",
                    reason="user_message_unreadable",
                    turn_id=str(turn_id),
                    thread_id=thread_id,
                    exc_info=True,
                )
                naming_task = None
        if stream is not None:
            await self._project_turn_close(
                stream=stream,
                outcome=outcome,
                envelope=envelope,
                assistant_message=assistant_message,
                replayed=replayed,
                naming_task=naming_task,
            )
        return ConversationTurnResult(
            outcome=outcome,
            assistant_message=assistant_message,
            replayed=replayed,
        )

    async def _project_turn_close(
        self,
        *,
        stream: TurnStreamEmitter,
        outcome: AgentTurnOutcome,
        envelope: AgentFinalizeEnvelope | None,
        assistant_message: str | None,
        replayed: bool,
        naming_task: asyncio.Task[NamingOutcome] | None = None,
    ) -> None:
        """Project the finalization's durable refs, reconcile the text, then close the turn.

        Order is the contract a consumer relies on: the cards a message carries arrive before the
        message is declared finished, and the text is either proved byte-identical (``text.end``) or
        loudly disowned (``stream.reset``) before the terminal event lands.

        A **replayed** turn streams nothing and says so: no delta of this attempt exists, so the
        honest instruction is "re-fetch the canonical message", not a fabricated replay of text the
        model produced in an earlier process.

        The **task** projection runs whatever the turn's status: a launch is committed by its own
        transaction, so a turn that launched research and then failed to finalize still launched it,
        and hiding the card would hide spend the human authorized.

        What is deliberately **not** projected here is a ``sources`` part. §3.4's floor demands real
        message-scoped source items, and this surface has none to give: the project conversation
        withholds every fetching tool by policy ("you do not … fetch external sources",
        ``C6_SURFACE_POLICIES``), so no durable source receipt is produced in a turn. The only
        remaining candidate — the finalization's ``domain_refs`` — is *model-declared*, carries no
        URL, title or evidence ref, and projecting it would manufacture provenance out of a
        model's assertion. An honest gap beats an invented citation; when a tool on this surface
        starts producing durable source receipts, that receipt is what feeds
        ``TurnStreamEmitter.emit_sources_part``.
        """

        if envelope is not None:
            await stream.emit_gate_parts(refs=envelope.open_gate_refs)
            for ref in envelope.domain_refs:
                if ref.object_type in _PLAN_OBJECT_TYPES:
                    # A project document is titled by the document: the human reads "Q4 expansion
                    # plan", the name it gave itself, and each version is a file revision they can
                    # see in the editor, so it reads as "v3" rather than a bare ordinal. A plan-3
                    # receipt has no title and falls back to the name that surface used; everything
                    # else in the set keeps the old generic rendering.
                    document_title = ref.title or _LEGACY_DOCUMENT_TITLES.get(ref.object_type)
                    await stream.emit_plan_part(
                        ref=ref,
                        title=(
                            document_title
                            if document_title is not None
                            else ref.object_type.replace("_", " ")
                        ),
                        revision_label=(
                            f"v{ref.version}"
                            if document_title is not None and ref.version is not None
                            else (None if ref.version is None else str(ref.version))
                        ),
                    )
        await stream.emit_launched_task_parts()
        if replayed:
            await stream.rehydrate(reason="turn_replayed")
        else:
            await stream.reconcile_text(assistant_message=assistant_message)
        # §4.1: a fast namer lands before the terminal event (one refetch shows the names); a
        # slow one keeps running detached. The terminal event never waits longer than the grace.
        # (``wait_grace(None)`` is already a no-op; the guard keeps this projection callable
        # unbound, as the D5 close-projection tests call it.)
        if naming_task is not None:
            await self._naming.wait_grace(naming_task)
        await stream.turn_finished(
            status=outcome.status.value,
            failure_code=outcome.failure_code,
            replayed=replayed,
        )


def build_conversation_turn_engine(
    *,
    surface: str,
    components: AgentPlatformComponents,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    memory: ContextAssembly,
    requested_memory_types: tuple[MemoryType, ...],
    context_policy: ContextAssemblyPolicy,
    child_runner: FreshWakeChildRunner | None = None,
    namer: ConversationNamer | None = None,
    continuation: bool = False,
    conn_factory: ConnFactory = transaction,
) -> ConversationTurnEngine:
    """Compose one conversation engine for one declared capability surface.

    ``surface`` is load-bearing three times over — the resolved profile, the context assembler's
    L1/L2 authority description, and the runtime's own assertion all read it — which is exactly why
    it is a parameter rather than a constant: the production project conversation and the dev trial
    are the *same* role on *different* surfaces, and a surface mismatch between the three is the
    failure this single builder makes unrepresentable.
    """

    resolved = components.profiles.resolve(AgentRole.HEAD_OF_ABM, surface=surface)
    # PC-C8 §6: one binder shared by L7 (which *names* the captured turn) and the execution seam
    # (which *injects* its bytes and ids). Both derive the same binding from durable state, so
    # sharing costs nothing and saves the second read of every turn.
    captured_turns = CapturedTurnBinder(
        artifacts=components.artifacts,
        conn_factory=conn_factory,
    )
    contexts = build_agent_context_assembler(
        resolved_profile=resolved,
        artifacts=components.artifacts,
        cards=DbCompiledContextCardReader(conn_factory=conn_factory),
        memory=memory,
        memory_recipe=f"{CONVERSATION_RECIPE_KEY}@{CONVERSATION_RECIPE_VERSION}",
        requested_memory_types=requested_memory_types,
        policy=context_policy,
        captured_turns=captured_turns,
        # L7 names this turn's attachments from the submission rows, so a file the human dropped
        # into the conversation is a named file with a readable path rather than a bare hash.
        attachment_describer=DbAttachmentDescriber(conn_factory=conn_factory),
        # An image the user sent earlier stays in the conversation so it can still be asked about
        # later; the operator's setting decides how many the thread carries (ruling 2).
        history_images_max=components.history_images_max,
        conn_factory=conn_factory,
    )
    runtime = HeadOfAbmStage0Runtime(
        profiles=components.profiles,
        models=components.models,
        turns=components.turns,
        artifacts=components.artifacts,
        tools=tools,
        child_runner=child_runner if child_runner is not None else DelegationWithheld(),
        # Operator settings, not the profile's own numbers (founder ruling 2026-09-27).
        max_runtime_s=components.head_of_abm_turn_timeout_s,
        max_rounds=components.head_of_abm_max_model_rounds,
        long_turn_alert_s=components.agent_long_turn_alert_s,
        surface=surface,
        conn_factory=conn_factory,
    )
    return ConversationTurnEngine(
        surface=surface,
        resolved=resolved,
        components=components,
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        compatibility=compatibility,
        contexts=contexts,
        runtime=runtime,
        captured_turns=captured_turns,
        plans=DbAgentPlanJournal(conn_factory=conn_factory),
        namer=namer,
        continuation_enabled=continuation,
        conn_factory=conn_factory,
    )
