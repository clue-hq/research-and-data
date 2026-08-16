"""C6.2 composition of reviewed folder profiles against the live tool registry."""

from __future__ import annotations

from pathlib import Path

from clue_agents import AgentRole, ToolPin
from clue_agents.catalog import (
    AgentCatalogError,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
)
from clue_agents.registry import (
    AgentProfileRegistry,
    AgentSurfacePolicy,
    AgentToolCatalog,
    AgentToolContract,
)
from clue_api.entity_research_quarantine import (
    ENTITY_RESEARCH_AGENT_NOT_COMPOSED,
    QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES,
)
from clue_toolbelt import ToolEffectClass, ToolRegistry, UnknownTool

__all__ = [
    "C6_ACTIVE_PROFILE_VERSIONS",
    "C6_AGENT_TOOL_AUTHORITY",
    "C6_SURFACE_POLICIES",
    "ACCOUNT_RESEARCH_UNIT_SURFACE",
    "PROJECT_CONVERSATION_SURFACE",
    "STAGE0_CONVERSATION_TRIAL_SURFACE",
    "c6_roles_for_tool",
    "ToolRegistryAgentCatalog",
    "build_agent_profile_registry",
]

C6_ACTIVE_PROFILE_VERSIONS: dict[AgentRole, str] = {
    # v36 (part-iii merge): v35 plus ``open_design_leg@1`` — the delegation entry that opens the
    # design leg (§1-D1's "attach as subagent" wrapper, materialized as a durable act; introduced
    # as PD-part3 P3.4's v24, re-versioned onto the v35 chain at the integration merge). v35
    # preserves the frozen v34 surface and gives Account-focused turns the exact pinned
    # field/source vocabulary needed to launch profiling without model-invented field keys.
    AgentRole.HEAD_OF_ABM: "v36",
    AgentRole.RESEARCH: "v7",
    AgentRole.CONTENT_DRAFTER: "v5",
    AgentRole.REVIEWER: "v5",
    # P3.3 (PD-part3): the composite design deepagent's platform-facing profile.
    AgentRole.DESIGN: "v1",
}


# C6.7 live authority. Empty means structurally absent from every current model surface.
C6_AGENT_TOOL_AUTHORITY: dict[str, tuple[AgentRole, ...]] = {
    "approve_contact_research_selection": (),
    "adjust_budget": (),
    # FI Lane D D0 / REQ-21 thread shell. Empty for now — the tools exist and are invocable by the
    # authenticated chat surface, but no *model* surface has been given thread management yet.
    # They are deliberately NOT in ``_HUMAN_ONLY_TOOLS``: REQ-21 anticipates an agent filing or
    # splitting its own threads, so this is an ungranted capability, not a human-authority gate.
    "archive_thread": (),
    "create_thread": (),
    "rename_thread": (),
    "set_thread_pinned": (),
    "compose_handoff": (
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "compose_contact_content_handoff": (
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "compose_dossier": (),
    "confirm_icp": (),
    "confirm_project_product": (),
    "decide_field_proposal": (),
    "decide_source_proposal": (),
    # Part II D6 (Rounds A + B) registered these ungranted; P3.3 (PD-part3) grants them to
    # the DESIGN role — the composite design deepagent's platform-facing authority. The audit
    # question "which durable writes can the platform name?" stays complete and static; what
    # changed is that exactly one role may now name the design write path.
    "design_apply_edits": (AgentRole.DESIGN,),
    "design_apply_operations": (AgentRole.DESIGN,),
    "design_apply_web_operations": (AgentRole.DESIGN,),
    "design_attach_brand_kit": (AgentRole.DESIGN,),
    "design_compile_component": (AgentRole.DESIGN,),
    "design_create_document": (AgentRole.DESIGN,),
    "design_create_snapshot": (AgentRole.DESIGN,),
    "design_create_web_account": (AgentRole.DESIGN,),
    "design_create_web_template": (AgentRole.DESIGN,),
    "design_delete_web_account": (AgentRole.DESIGN,),
    "design_derive_web_document": (AgentRole.DESIGN,),
    "design_finalize_document": (AgentRole.DESIGN,),
    "design_persist_preflight": (AgentRole.DESIGN,),
    "design_publish_web": (AgentRole.DESIGN,),
    "design_record_diagnostics": (AgentRole.DESIGN,),
    "design_redo_document": (AgentRole.DESIGN,),
    "design_redo_web_document": (AgentRole.DESIGN,),
    "design_replace_scene": (AgentRole.DESIGN,),
    "design_rollback_web_publish": (AgentRole.DESIGN,),
    "design_set_agent_instructions": (AgentRole.DESIGN,),
    "design_set_layout_managed_editing": (AgentRole.DESIGN,),
    "design_start_agent_turn": (AgentRole.DESIGN,),
    "design_start_web_turn": (AgentRole.DESIGN,),
    "design_undo_document": (AgentRole.DESIGN,),
    "design_undo_web_document": (AgentRole.DESIGN,),
    "design_unpublish_web": (AgentRole.DESIGN,),
    "design_update_web_account": (AgentRole.DESIGN,),
    "design_write_component_source": (AgentRole.DESIGN,),
    "design_advance_instance_batch": (AgentRole.DESIGN,),
    "design_advance_web_batch": (AgentRole.DESIGN,),
    "design_create_brand_compatibility_report": (AgentRole.DESIGN,),
    "design_create_brand_kit": (AgentRole.DESIGN,),
    "design_create_instance_batch": (AgentRole.DESIGN,),
    "design_create_web_batch": (AgentRole.DESIGN,),
    "design_delete_asset": (AgentRole.DESIGN,),
    "design_delete_binding_set": (AgentRole.DESIGN,),
    "design_derive_instance": (AgentRole.DESIGN,),
    "design_ingest_assets": (AgentRole.DESIGN,),
    "design_ingest_pdf": (AgentRole.DESIGN,),
    "design_ingest_website": (AgentRole.DESIGN,),
    "design_publish_brand_kit_version": (AgentRole.DESIGN,),
    "design_register_asset_record": (AgentRole.DESIGN,),
    "design_register_captured_assets": (AgentRole.DESIGN,),
    "design_register_generated_asset": (AgentRole.DESIGN,),
    "design_register_qr_asset": (AgentRole.DESIGN,),
    "design_set_asset_description": (AgentRole.DESIGN,),
    "design_set_asset_status": (AgentRole.DESIGN,),
    "design_set_brand_kit_approval": (AgentRole.DESIGN,),
    "design_upsert_binding_set": (AgentRole.DESIGN,),
    "draft_account_research_directive": (AgentRole.HEAD_OF_ABM,),
    # P3.5 (PD-part3 §2.2): the leg-level exit, granted to the composite design deepagent — the
    # only path to a closed leg. Turn-level finalization (the design harness's final.json) is a
    # different authority and stays design-runtime-internal; this is the engine-validated
    # doorway back to head-of-abm (lock-in summary, out_of_scope re-delivery, journaled).
    "finish_design_leg": (AgentRole.DESIGN,),
    "confirm_account_research_directive": (),
    "discover_accounts": (),
    "estimate_project": (),
    "enrich_account_gaps": (),
    "enrich_selected_accounts": (),
    "evaluate_stage0_readiness": (AgentRole.HEAD_OF_ABM,),
    "get_research_view": (
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "import_accounts": (),
    # PC-C8 §7 (task 1.5's deferred grant, landed against profile v10). These are the tools the
    # card's `omissions` cursors are resolvable *through*: read-only, effect-free, page-bounded,
    # and fail-closed on workspace/project scope. They are granted on the base role *and* stay
    # installed on the trial surface — §7 sanctions them there explicitly, and a card that emits an
    # omission kind no installed tool can resolve is the contract
    # `test_c8_omission_resolution_contract.py` now refuses to let ship.
    "inspect_readiness_history": (AgentRole.HEAD_OF_ABM,),
    "inspect_client_claim": (AgentRole.HEAD_OF_ABM,),
    "inspect_product_claim": (AgentRole.HEAD_OF_ABM,),
    "inspect_statement_history": (AgentRole.HEAD_OF_ABM,),
    "list_client_knowledge": (AgentRole.HEAD_OF_ABM,),
    "list_product_knowledge": (AgentRole.HEAD_OF_ABM,),
    "launch_account_deep": (),
    "launch_account_research": (AgentRole.HEAD_OF_ABM,),
    "launch_selected_account_research": (AgentRole.HEAD_OF_ABM,),
    "launch_contact_research": (AgentRole.HEAD_OF_ABM,),
    # P3.4 (PD-part3 §1-D1/§2.3): delegating to Design is the Head of ABM's own act — the tool
    # validates the D5 pins, freezes the delegation bundle, and opens the durable leg whose
    # existence IS the routing rule. It spends nothing and dispatches nothing; the user's next
    # message on the thread is what becomes the first design turn.
    "open_design_leg": (AgentRole.HEAD_OF_ABM,),
    # FI Lane D D4 / §3-P5(a): asking the human for authority is the Head of ABM's own act, so the
    # gate-opening tool is granted to that role. It writes an immutable gate row and nothing else —
    # it confirms nothing, spends nothing, and cannot address a gate to anybody but the human whose
    # turn it is answering (the addressee is derived from the durable submission, not proposed).
    "open_directive_confirmation_gate": (AgentRole.HEAD_OF_ABM,),
    "open_discovery_configuration_gate": (AgentRole.HEAD_OF_ABM,),
    "open_icp_confirmation_gate": (AgentRole.HEAD_OF_ABM,),
    "open_product_selection_gate": (AgentRole.HEAD_OF_ABM,),
    "override_stage0_readiness": (),
    "pause_run": (),
    "profile_contact": (),
    "propose_field": (AgentRole.HEAD_OF_ABM,),
    "propose_source": (AgentRole.HEAD_OF_ABM,),
    "read_account_research_run": (AgentRole.HEAD_OF_ABM,),
    "read_contact_research_run": (AgentRole.HEAD_OF_ABM,),
    "record_interview_answer": (AgentRole.HEAD_OF_ABM,),
    "recheck_research_view": (),
    "research_account_gaps": (),
    "resolve_committee": (),
    "resume_run": (),
    "retry_ingestion": (),
    "reverse_profile": (),
    "run_deep_account": (),
    "run_verification": (AgentRole.RESEARCH,),
    "score_accounts": (),
    "start_confirmed_project_run": (AgentRole.HEAD_OF_ABM,),
    "start_project_run": (),
    "start_recon": (AgentRole.HEAD_OF_ABM,),
    "submit_ingestion": (AgentRole.HEAD_OF_ABM,),
    "submit_onboarding_input": (AgentRole.HEAD_OF_ABM,),
    "submit_project_checkpoint": (),
    "submit_tier_checkpoint": (),
    # Lane E E1. Machine-invoked only: the post-finalize fleet step offers a just-terminal research
    # job to it. It is deliberately absent from every model surface — an agent that could summarize
    # on demand could spend on prose for a job the research engine never finished.
    "synthesize_entity_prose": (),
    # Lane E E3. Machine-invoked only, for the same reason one slice stronger: positioning spends
    # one completion (and one judge call) *per committee persona*, so an on-demand agent reach for
    # it is an unbounded spend on research the engine may never have finished.
    "synthesize_value_narrative": (),
    "synthesize_icps": (AgentRole.HEAD_OF_ABM,),
}

#: The Stage-0 conversation trial (`clue_api.stage0_trial`). One human types, the platform captures
#: every turn, and the agent's whole job is to converse and route what was said.
STAGE0_CONVERSATION_TRIAL_SURFACE = "stage0_conversation_trial"

#: The **production** project conversation (FI Lane D D2): the same Head-of-ABM role, on a real
#: project thread, executed by the fleet worker instead of a local CLI. It is a separate surface
#: from the trial rather than a reuse of it because the two are genuinely different deployments of
#: one role — the trial is a dev harness with no launch authority *and* no production traffic, and
#: collapsing them would make widening the production surface (D4's P5(e)) silently widen the trial
#: too. D2 declares it with exactly the trial's tool subtraction: the launch tools stay
#: structurally withheld until the D4 kickoff flow earns them.
PROJECT_CONVERSATION_SURFACE = "project_conversation"

#: The fleet-owned per-account unit executes the one-tool ``account-research-unit@1`` recipe.
#: ``get_research_view`` belongs to the broader account-research role for conversational/read
#: surfaces, but this bounded coverage unit has neither that tool nor its verification-policy pin
#: in its C5 slot.  Resolve a named surface so the manifest, middleware, and installed tools all
#: describe that narrower authority before the model wakes.
ACCOUNT_RESEARCH_UNIT_SURFACE = "account_research_unit"

#: PC-C8 §8: surface restrictions are enforced by tools that are *not installed*, never by prose in
#: a shared skill or a context card. Each entry narrows one role's effective tool set on one named
#: surface; the registry refuses a policy that withholds a tool the role's profile does not pin, so
#: a rename cannot quietly restore a withheld capability.
#:
#: The trial withholds four tools, all for one reason — this surface is a manual conversation and
#: does no external research, and neither the model nor the platform captures anything on the
#: agent's behalf:
#:
#: * ``start_recon`` and ``synthesize_icps`` are the two prohibitions the deleted stage-snapshot
#:   prose used to state (task 1.3 deleted it with its artifact). ``start_recon`` spends against
#:   external surfaces; ``synthesize_icps`` is driven from the human ``/synthesize-icp`` command,
#:   which calls the research function directly and never needs the agent tool.
#: * ``submit_onboarding_input`` is withheld as a **policy call** (PC-C8 §8, task 1.4). The trial's
#:   rule is that the agent never captures: ``Stage0Trial.run_turn`` writes the ``user_turn``
#:   capture itself, as ``actor='human'``, before the model is ever woken. Task 1.2's binder made
#:   an agent-written row harmless to the turn binding (the capture lookup is scoped by project and
#:   ``actor='human'``), so this is no longer a *safety* fix — it is that the tool has no honest use
#:   left here. Its only consumers of a fresh capture were ``start_recon`` (withheld) and the human
#:   upload boundary (absent on this surface), so every reachable call would write an
#:   ``actor='agent'`` capture record for a turn the platform already captured: durable noise with
#:   misleading provenance. Defence in depth is unchanged — 1.2's lookup scoping stays.
#: * ``enrich_selected_accounts`` and ``enrich_account_gaps`` are post-checkpoint provider-spend
#:   boundaries. They have no honest Stage-0 use even though the broader Head-of-ABM role owns
#:   those decisions.
#:
#: ``submit_ingestion`` is deliberately **kept**: it ingests an already-captured workspace artifact
#: and performs no external research, so it does not cross this surface's boundary. So are the two
#: §7 inspection tools: read-only, effect-free, and the only way a card omission cursor resolves.
#:
#: **Delegation is withheld too, and for the same sentence.** A tool ceiling alone left the trial's
#: own map promising "no external research" while still advertising ``delegate_specialist`` and the
#: three specialist roles under it — one of which is *the research role*. The only thing preventing
#: a delegation was ``stage0_trial._DelegationDisabled.run`` raising at call time, i.e. restriction
#: by crash, which is exactly what ruling §2.4 rejects and what the withheld tools fixed for tools.
#: Withholding the roles empties ``delegation_roles``, so ``delegate_specialist`` leaves the
#: middleware's allowed set, the Delegation block stops naming anyone, and the child runner's
#: refusal becomes an unreachable backstop rather than the mechanism.
C6_SURFACE_POLICIES: tuple[AgentSurfacePolicy, ...] = (
    AgentSurfacePolicy(
        surface=STAGE0_CONVERSATION_TRIAL_SURFACE,
        role=AgentRole.HEAD_OF_ABM,
        withheld_tools=frozenset(
            {
                "launch_account_research",
                "launch_selected_account_research",
                "launch_contact_research",
                # D4 added the gate tool to the role. The trial keeps it withheld with the launch
                # tools it belongs to: a dev harness that could present a real, durable, addressed
                # confirmation gate — but never act on the answer — would be inviting a human to
                # approve spend that no surface here can perform.
                "open_directive_confirmation_gate",
                "open_discovery_configuration_gate",
                "open_product_selection_gate",
                # P3.4 added the design delegation entry to the role. The trial withholds it for
                # the same sentence as delegation itself: this surface is a manual conversation,
                # and a leg opened from a dev CLI would durably reroute a thread no design
                # runtime here can serve.
                "open_design_leg",
                "start_recon",
                "submit_onboarding_input",
                "synthesize_icps",
            }
        ),
        withheld_delegation_roles=frozenset(
            {
                AgentRole.RESEARCH,
                AgentRole.CONTENT_DRAFTER,
                AgentRole.REVIEWER,
            }
        ),
        withheld_reason_code="trial_manual_conversation_only",
        framing=(
            "This surface is a manual-conversation-only Stage-0 trial: it does no external "
            "research, and the platform captures every turn before you see it, so you never "
            "capture, fetch, delegate, or synthesize outside this conversation."
        ),
    ),
    # D4 widened this surface: `launch_account_research` / `launch_contact_research` are no longer
    # withheld here, because the authority they were waiting for now exists — a durable gate object
    # (`open_directive_confirmation_gate@1`), a structured human answer to it, and the confirming
    # turn's own `action_ref` threaded into the tool context. The remaining two subtractions are
    # the trial's, for the trial's reasons: this surface still does no external research and still
    # never captures on the client's behalf. Slice 1 removes ``synthesize_icps`` from this list:
    # @2 is the governed Stage-0 capability and persists draft specs. Delegation stays withheld
    # (D4 grants launch authority, not a specialist fleet).
    AgentSurfacePolicy(
        surface=PROJECT_CONVERSATION_SURFACE,
        role=AgentRole.HEAD_OF_ABM,
        withheld_tools=frozenset(
            {
                "start_recon",
                "submit_onboarding_input",
            }
        ),
        withheld_delegation_roles=frozenset(
            {
                AgentRole.RESEARCH,
                AgentRole.CONTENT_DRAFTER,
                AgentRole.REVIEWER,
            }
        ),
        withheld_reason_code="project_conversation_no_autonomous_research",
        framing=(
            "This surface is the project conversation: you converse with the client, record what "
            "they tell you, and can draft research direction, present its confirmation gate, or "
            "launch an exact Account set explicitly commanded and attached by the current human "
            "turn when the pilot budget gate is disabled. You do not capture on their behalf, "
            "fetch external sources, delegate to a specialist, or widen the human's selected set."
        ),
    ),
)

_HUMAN_ONLY_TOOLS = frozenset(
    {
        "adjust_budget",
        "confirm_icp",
        "confirm_project_product",
        "confirm_account_research_directive",
        "decide_field_proposal",
        "decide_source_proposal",
        "override_stage0_readiness",
        "pause_run",
        "resume_run",
        "submit_project_checkpoint",
        "submit_tier_checkpoint",
    }
)
_RESERVED_REASON: dict[str, str] = {
    # (P3.3 retired the Part II D6 `design_agent_not_wired_until_part_iii` block: the design
    # tools are granted to AgentRole.DESIGN now, so they are no longer reserved.)
    "discover_accounts": "post_stage0_not_admitted",
    "estimate_project": "post_stage0_not_admitted",
    "import_accounts": "post_stage0_not_admitted",
    "retry_ingestion": "replay_not_certified",
    "reverse_profile": "superseded_by_governed_stage0_recon",
    "score_accounts": "post_stage0_not_admitted",
    "start_project_run": "legacy_unconfirmed_entry_forbidden",
}


def _roles_for(address: str, name: str) -> tuple[AgentRole, ...]:
    """Resolve authority by exact address where versions have different safety proofs."""

    if name == "list_client_knowledge":
        return (AgentRole.HEAD_OF_ABM,) if address == "list_client_knowledge@2" else ()
    if name == "inspect_client_claim":
        return (AgentRole.HEAD_OF_ABM,) if address == "inspect_client_claim@2" else ()
    if name == "list_product_knowledge":
        return (AgentRole.HEAD_OF_ABM,) if address == "list_product_knowledge@1" else ()
    if name == "inspect_product_claim":
        return (AgentRole.HEAD_OF_ABM,) if address == "inspect_product_claim@1" else ()
    if name == "propose_field":
        return (AgentRole.HEAD_OF_ABM,) if address == "propose_field@2" else ()
    if name == "draft_account_research_directive":
        return (AgentRole.HEAD_OF_ABM,) if address == "draft_account_research_directive@3" else ()
    if name == "evaluate_stage0_readiness":
        return (AgentRole.HEAD_OF_ABM,) if address.endswith("@2") else ()
    if name == "synthesize_icps":
        return (AgentRole.HEAD_OF_ABM,) if address.endswith("@3") else ()
    if name == "start_confirmed_project_run":
        return (AgentRole.HEAD_OF_ABM,) if address.endswith("@3") else ()
    if name == "research_account_gaps":
        return ()
    if name == "profile_contact":
        return ()
    return C6_AGENT_TOOL_AUTHORITY.get(name, ())


def c6_roles_for_tool(address: str) -> tuple[AgentRole, ...]:
    name, separator, _version = address.partition("@")
    if not separator:
        raise ValueError("C6 tool authority requires an exact name@version address")
    return _roles_for(address, name)


def _unavailable_reason(address: str, name: str) -> str | None:
    if address in QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES:
        return ENTITY_RESEARCH_AGENT_NOT_COMPOSED
    if address == "research_account_gaps@1":
        return "replaced_by_replay_safe_v2"
    if address == "profile_contact@1":
        return "replaced_by_governed_v2"
    if address in {
        "evaluate_stage0_readiness@1",
        "start_confirmed_project_run@1",
        "synthesize_icps@1",
    }:
        return "replaced_by_trusted_stage0_v2"
    if address == "start_confirmed_project_run@2":
        return "replaced_by_provider_neutral_discovery_v3"
    if address == "synthesize_icps@2":
        return "replaced_by_bounded_icp_presentation_v3"
    return _RESERVED_REASON.get(name)


class ToolRegistryAgentCatalog(AgentToolCatalog):
    """Translate the live toolbelt descriptor into C6's provider-neutral exact contract."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def resolve(self, pin: ToolPin) -> AgentToolContract:
        try:
            descriptor = self._registry.descriptor(pin.name, pin.version)
        except UnknownTool as exc:
            raise AgentCatalogError(f"tool {pin.address!r} is unavailable") from exc
        actual = ToolPin(
            name=descriptor.name,
            version=descriptor.version,
            input_schema_sha256=descriptor.input_schema_sha256,
            output_schema_sha256=descriptor.output_schema_sha256,
        )
        return AgentToolContract(
            pin=actual,
            recipe_safe=descriptor.recipe_safe,
            steering=descriptor.effect_class is ToolEffectClass.STEERING,
            effect_class=descriptor.effect_class.value,
            admitted_roles=_roles_for(descriptor.address, descriptor.name),
            unavailable_reason_code=(
                "human_authority"
                if descriptor.name in _HUMAN_ONLY_TOOLS
                else _unavailable_reason(descriptor.address, descriptor.name)
            ),
        )


def build_agent_profile_registry(
    tool_registry: ToolRegistry,
    *,
    catalog_root: Path | None = None,
) -> AgentProfileRegistry:
    """Fail-fast composition of all active role resources and exact tool authority."""

    if set(tool_registry.names()) != set(C6_AGENT_TOOL_AUTHORITY):
        missing = sorted(set(C6_AGENT_TOOL_AUTHORITY) - set(tool_registry.names()))
        extra = sorted(set(tool_registry.names()) - set(C6_AGENT_TOOL_AUTHORITY))
        raise AgentCatalogError(
            f"live tool registry differs from the C6 authority audit; missing={missing}, "
            f"extra={extra}"
        )
    admitted_addresses: set[str] = set()
    for descriptor in tool_registry.all_descriptors():
        roles = _roles_for(descriptor.address, descriptor.name)
        if roles:
            if not descriptor.recipe_safe:
                raise AgentCatalogError(
                    f"admitted tool {descriptor.address!r} is no longer replay-safe"
                )
            if descriptor.effect_class is ToolEffectClass.STEERING:
                raise AgentCatalogError(
                    f"admitted tool {descriptor.address!r} became human steering"
                )
            admitted_addresses.add(descriptor.address)

    root = catalog_root or Path(__file__).resolve().parents[2] / "agents" / "catalog"
    resolved = AgentProfileRegistry(
        prompts=FolderPromptCatalog((root / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((root / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((root / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(tool_registry),
        engine_tool_ceiling=frozenset(admitted_addresses),
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
        tool_inventory=tuple(
            ToolRegistryAgentCatalog(tool_registry).resolve(
                ToolPin(
                    name=descriptor.name,
                    version=descriptor.version,
                    input_schema_sha256=descriptor.input_schema_sha256,
                    output_schema_sha256=descriptor.output_schema_sha256,
                )
            )
            for descriptor in tool_registry.all_descriptors()
        ),
        surface_policies=C6_SURFACE_POLICIES,
    )
    for role in C6_ACTIVE_PROFILE_VERSIONS:
        expected = {
            descriptor.address
            for descriptor in tool_registry.all_descriptors()
            if role in _roles_for(descriptor.address, descriptor.name)
        }
        actual = {pin.address for pin in resolved.resolve(role).profile.tools}
        if actual != expected:
            raise AgentCatalogError(
                f"profile {role.value!r} differs from reviewed authority; "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )
    return resolved
