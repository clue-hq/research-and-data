"""Standing Recipe #0/#1 tool inventory and replay-safety audit."""

from __future__ import annotations

from dataclasses import dataclass

from clue_toolbelt import (
    ExternalReplayBoundary,
    ReplayPolicy,
    ToolEffectClass,
    ToolRegistry,
)

RECIPE_0_TOOL_ADDRESSES: tuple[str, ...] = (
    "submit_onboarding_input@1",
    "start_recon@1",
    "record_interview_answer@1",
    "confirm_project_product@1",
    "evaluate_stage0_readiness@2",
    "synthesize_icps@3",
    "open_icp_confirmation_gate@1",
    "confirm_icp@1",
    "override_stage0_readiness@1",
    "open_discovery_configuration_gate@1",
    "start_confirmed_project_run@3",
    "propose_field@2",
    "propose_source@1",
    "submit_ingestion@1",
    # PC-C8 §7 (retained in recipe0-stage0@5): the two bounded read-only history tools. A tool the
    # card's
    # omission cursors resolve through has to be runnable in the Stage-0 interaction slot, and
    # anything in that slot is certified here first.
    "inspect_statement_history@1",
    "inspect_readiness_history@1",
    # FI production context S4-D (recipe0-stage0@8): strict artifact-bound reads behind the
    # bounded Client-KB index. Both are effect-free and pin only the exact Client-KB checkpoint;
    # project/workspace/client authority is injected from the production constitution.
    "list_client_knowledge@2",
    "inspect_client_claim@2",
    # S5-D (recipe0-stage0@9): selected-product knowledge stays a separate exact Product-KB
    # surface. Scope is injected from the paired turn pin; both reads are effect-free.
    "list_product_knowledge@1",
    "inspect_product_claim@1",
    # S5-F: this model-callable action presents the exact pinned catalog to the human but cannot
    # confirm a product. Its deterministic gate identity makes retries domain-idempotent.
    "open_product_selection_gate@1",
    # FI Lane D D4 (added in recipe0-stage0@6): the Option-B kickoff chain. Anything runnable in
    # the Stage-0 interaction slot is replay-certified here first, and these three are the whole
    # point of the widened conversation surface — draft the direction, present its confirmation
    # gate, and launch what the human's confirming turn approved.
    "draft_account_research_directive@5",
    "open_directive_confirmation_gate@1",
    "get_research_view@1",
    "launch_account_research@1",
    # FI-2 exact current-message Account launch, retained in integration recipe0-stage0@11.
    "launch_selected_account_research@1",
    "read_account_research_run@1",
    # PD-part3 P3.4 (added in recipe0-stage0@16 on this lineage): the design delegation entry,
    # promoted to @2 in @17 (genweb slice 2 — a document-less open births the web document), to @3
    # in @18 (genad — a document-less ``doc_kind='scene'`` open births the ad document at a named
    # format) and to @4 in @19 (genad2 — the scene births ZERO pages and the design agent authors
    # them, so the format inputs are gone), and to @5 in @30 (multi-artifact legs — the input
    # carries an ``artifacts`` list, so one open births one document per item). Opening a leg is
    # still a durable write with no spend and no dispatch; each birth is one governed create keyed
    # on the same replay identity as the leg, so a retried delegation converges on one leg and its
    # documents rather than minting twins.
    "open_design_leg@5",
    # ARV2 onboarding O6 (added in recipe0-stage0@22): the new-lane onboarding surface Head-of-ABM
    # drives in the conversation slot — the set-valued product gate, the artifact-shaped ICP
    # confirmation gate, and the ARV2 launch/read pair. Nothing is removed: every address the
    # earlier revisions pinned stays here so an already-pinned execution still resolves it.
    "open_product_set_selection_gate@1",
    "open_icp_confirmation_gate@2",
    "launch_arv2_account_research@1",
    # Founder ruling 3 (2026-09-10): the same launch for named people, granted to the Head of ABM
    # at `head-of-abm@v44`. It declares the same ``project`` pin as its siblings, which is what
    # this audit requires of every standing address.
    "launch_arv2_person_research@1",
    # ARV2 Track R, R4 (added in recipe0-stage0@23): verified account discovery for the project,
    # granted at `head-of-abm@v45`. It declares the same ``project`` pin as its launch siblings —
    # the spine row the execution is bound to — which is what this audit requires of every
    # standing address. Agent-authored discovery (recipe0-stage0@33) RE-PINS it at ``@2``, whose
    # input is the brief the Head of ABM writes; ``@1`` leaves (one version per ``(kind, key)``)
    # and stays registered only to refuse ``discovery_tool_retired`` on replay. recipe0-stage0@35
    # RE-PINS it at ``@3``, whose brief adds ``exclude`` (spec 2026-10-16).
    "launch_arv2_discovery@3",
    "read_arv2_account_research_run@1",
    # ``author_icp_document@1`` (added in @24), ``request_persona_synthesis@1`` (@24) and
    # ``write_project_document@1`` (@25) were retired at recipe0-stage0@27: the documents they
    # wrote are written as files under the versioned ``project/`` mount now, and `head-of-abm@v55`
    # grants none of them. The addresses stay REGISTERED for replay of executions pinned to ≤v26,
    # which read their own immutable revision — they are simply no longer standing, so this audit
    # no longer requires them to keep declaring a ``project`` pin.
    # The ARV2 reads (added in recipe0-stage0@26): the project's accounts, one account's
    # research, and the discovery run — effect-free reads over rows that already exist.
    # Granted at `head-of-abm@v48` and declaring the same ``project`` pin as their siblings —
    # the spine row the execution is bound to — which is what this audit requires of every
    # standing address.
    "read_project_accounts@1",
    # Paged and spilled reads (recipe0-stage0@28): ``read_account_research`` and
    # ``read_discovery_run`` are RE-PINNED to their paged ``@2`` — ``offset``/``limit`` in,
    # ``next_offset`` back — which is what `head-of-abm@v56` grants. A requirement set resolves one
    # version per ``(kind, key)``, so ``@1`` and ``@2`` in one slot is a ``conflicting_requirement``
    # that refuses promotion; the ``@1``s therefore LEAVE, exactly as ``open_icp_confirmation_gate``
    # @1 left at @22. They stay registered, and v27 stays the exact replay input for turns pinned
    # to it. Two reads join in the same revision, granted for the first time at v56: the general
    # claims query and the gallery read. All four are effect-free over rows that already exist and
    # declare the same ``project`` pin as their siblings, which is what this audit requires of
    # every standing address.
    "read_account_research@2",
    "read_claims@1",
    "read_artifact@1",
    # recipe0-stage0@33 re-pins the discovery read at ``@3`` (summary, end reason, exclusions),
    # the contract `head-of-abm@v70` grants; ``@2`` leaves the standing set and stays registered.
    "read_discovery_run@3",
    # The code sandbox (recipe0-stage0@29): one short Python script per call, in a container with
    # no network, over the turn's own workspace. Granted for the first time at `head-of-abm@v58`
    # and admitted to the interaction slot in the same revision. It is a WRITE, so unlike its
    # neighbours above it is operation-bound and OPERATION_IDEMPOTENT — a retry of the same call
    # converges on the journaled receipt of one run rather than running the script twice — and it
    # declares the same ``project`` pin as its siblings, the spine row the execution is bound to
    # and the project whose ``attachments/`` the container can see.
    "run_python@1",
    "configure_project_targeting@1",
    # web_search@1 (recipe0-stage0@32): one deep-lite open-web search, used last, answering text
    # that is never a claim. Granted at `head-of-abm@v62`; a SPEND, AT_LEAST_ONCE on replay, with
    # the same ``project`` pin as its siblings.
    "web_search@1",
    # manage_products@1 (recipe0-stage0@34): the Head of ABM adds, renames, merges or removes the
    # brand's products when the person asks. Granted at `head-of-abm@v71`; a WRITE with the same
    # ``project`` pin as its siblings, resolved from the presenting turn.
    "manage_products@1",
    # CRM integration Phase 1 (recipe0-stage0@36), granted at `head-of-abm@v76`. `connect_crm@1`
    # and `write_brand_document@1` are WRITEs resolved from the presenting turn; `run_crm_action@1`
    # is a SPEND and `find_crm_actions@1` an effect-free read, both with the execution's
    # ``project`` pin.
    "connect_crm@1",
    "find_crm_actions@1",
    "run_crm_action@1",
    "write_brand_document@1",
    # CRM integration Phase 2 (recipe0-stage0@37), granted at `head-of-abm@v77`.
    # `propose_crm_changes@1` and `manage_crm_grants@1` are WRITEs resolved from the presenting
    # turn; `crm_write_log@1` is an effect-free read with the execution's ``project`` pin.
    "propose_crm_changes@1",
    "crm_write_log@1",
    "manage_crm_grants@1",
    # CRM integration Phase 3 (recipe0-stage0@38), granted at `head-of-abm@v78`.
    # `read_crm_targets@1` and `find_crm_list@1` are effect-free reads; `link_crm_list@1` is a
    # WRITE that keeps a CRM list for the project (nothing changes in the CRM). All three take the
    # execution's ``project`` pin.
    "read_crm_targets@1",
    "find_crm_list@1",
    "link_crm_list@1",
    # CRM integration Phase 4 (recipe0-stage0@42), granted at `head-of-abm@v82`.
    # `propose_clue_fields_setup@1` is a WRITE (a permission card only an owner or admin can
    # allow) resolved from the presenting turn, like `propose_crm_changes@1`.
    "propose_clue_fields_setup@1",
)

RECIPE_1_TOOL_ADDRESSES: tuple[str, ...] = (
    "reverse_profile@1",
    "synthesize_icps@1",
    "confirm_icp@1",
    "import_accounts@1",
    "discover_accounts@1",
    "score_accounts@1",
    "submit_tier_checkpoint@1",
    "submit_project_checkpoint@1",
    "advance_project_phase@1",
    "run_deep_account@1",
    "resolve_committee@1",
    "profile_contact@1",
    "run_verification@1",
    "compose_handoff@1",
    "estimate_project@1",
    "start_project_run@1",
    "pause_run@1",
    "resume_run@1",
    "adjust_budget@1",
)

ACCOUNT_RESEARCH_TOOL_ADDRESSES: tuple[str, ...] = ("research_account_gaps@2",)

# ARV2 onboarding O4 (plan §4.5): the synthesis unit's whole spendable surface is one governed
# deep-reasoning search over O2's fixed persona-evidence template.
ONBOARDING_SYNTHESIS_TOOL_ADDRESSES: tuple[str, ...] = ("exa_search_evidence@1",)


def _split_address(address: str) -> tuple[str, str]:
    name, separator, version = address.rpartition("@")
    if not separator or not name or not version:
        raise ValueError(f"invalid exact tool address {address!r}")
    return name, version


@dataclass(frozen=True, slots=True)
class ReplayAuditEntry:
    address: str
    recipes: tuple[str, ...]
    replay_policy: ReplayPolicy
    durable_identity: str
    operation_id_required: bool
    external_boundary: ExternalReplayBoundary
    effect_class: ToolEffectClass
    input_schema_sha256: str
    output_schema_sha256: str
    pin_requirements: tuple[str, ...]


def standing_recipe_addresses() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(RECIPE_0_TOOL_ADDRESSES)
            | set(RECIPE_1_TOOL_ADDRESSES)
            | set(ACCOUNT_RESEARCH_TOOL_ADDRESSES)
            | set(ONBOARDING_SYNTHESIS_TOOL_ADDRESSES)
        )
    )


def build_replay_safety_audit(registry: ToolRegistry) -> tuple[ReplayAuditEntry, ...]:
    """Resolve every standing tool exactly and return the machine-readable replay audit."""
    entries: list[ReplayAuditEntry] = []
    failures: list[str] = []
    for address in standing_recipe_addresses():
        name, version = _split_address(address)
        descriptor = registry.descriptor(name, version)
        if not descriptor.has_typed_output:
            failures.append(f"{address}: output is untyped")
        if descriptor.replay.policy is ReplayPolicy.UNCERTIFIED:
            failures.append(f"{address}: replay policy is uncertified")
        if not descriptor.pin_requirements:
            failures.append(f"{address}: pin requirements are empty")
        if (
            descriptor.effect_class is ToolEffectClass.STEERING
            and not descriptor.has_steering_snapshot
        ):
            failures.append(f"{address}: steering snapshot is absent")
        recipes = tuple(
            recipe
            for recipe, addresses in (
                ("recipe0@1", RECIPE_0_TOOL_ADDRESSES),
                ("recipe1@1", RECIPE_1_TOOL_ADDRESSES),
                ("account-research-unit@1", ACCOUNT_RESEARCH_TOOL_ADDRESSES),
                ("onboarding-synthesis-unit@1", ONBOARDING_SYNTHESIS_TOOL_ADDRESSES),
            )
            if address in addresses
        )
        entries.append(
            ReplayAuditEntry(
                address=address,
                recipes=recipes,
                replay_policy=descriptor.replay.policy,
                durable_identity=descriptor.replay.durable_identity,
                operation_id_required=descriptor.replay.operation_id_required,
                external_boundary=descriptor.replay.external_boundary,
                effect_class=descriptor.effect_class,
                input_schema_sha256=descriptor.input_schema_sha256,
                output_schema_sha256=descriptor.output_schema_sha256,
                pin_requirements=descriptor.pin_requirements,
            )
        )
    if failures:
        raise ValueError("standing recipe contract audit failed:\n" + "\n".join(failures))
    return tuple(entries)


__all__ = [
    "RECIPE_0_TOOL_ADDRESSES",
    "RECIPE_1_TOOL_ADDRESSES",
    "ACCOUNT_RESEARCH_TOOL_ADDRESSES",
    "ONBOARDING_SYNTHESIS_TOOL_ADDRESSES",
    "ReplayAuditEntry",
    "build_replay_safety_audit",
    "standing_recipe_addresses",
]
