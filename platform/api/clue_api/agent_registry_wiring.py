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
    "ONBOARDING_ICP_SURFACE",
    "PROJECT_CONVERSATION_SURFACE",
    "STAGE0_CONVERSATION_TRIAL_SURFACE",
    "c6_roles_for_tool",
    "ToolRegistryAgentCatalog",
    "build_agent_profile_registry",
]

C6_ACTIVE_PROFILE_VERSIONS: dict[AgentRole, str] = {
    # v42 (Slice B browser-gate repair): v41 with ``draft_account_research_directive@5`` and
    # steering skill v8 — @4's schema marked ``directive.field_keys`` required while the skill
    # (correctly) said to omit it, so a schema-honouring model could never place the comprehensive
    # request; @5 makes the key omittable and nothing else changes.
    # v41 (comprehensive account/contact research, Slice B): v36 plus the comprehensive-profile
    # directive contract — ``draft_account_research_directive@4`` and steering skill v7. A normal
    # full-profile request now compiles deterministically to the fixed 21-field account profile
    # (contract §3.2/§3.3 row 1) instead of the three-field qualitative subset the v6 skill named.
    # v39 (genad2, 2026-08-23): v38 with the delegation entry at ``open_design_leg@4`` and prompt
    # v7 — the founder's ruling that the platform owns no page geometry. A ``doc_kind='scene'``
    # open births a ZERO-PAGE document and the design agent authors the page, so the prompt no
    # longer infers or states a format: it routes, delegates the user's own words in ``brief``,
    # and says the design session is open.
    # v38 (genad): v37 with the delegation entry at ``open_design_leg@3`` and prompt v6 — chat ad
    # creation. The prompt teaches the same handover at a different shape: infer the ad's format
    # from the ask, STATE the choice so the user can correct it, and do not block on a
    # confirmation before opening the leg.
    # v37 (genweb slice 2): v36 with the delegation entry at ``open_design_leg@2`` and prompt v5
    # — the design-delegation teaching. The tool's own description remains the contract; the
    # prompt only says WHEN to hand the thread over and what the handover costs (the user's next
    # message starts a generation that takes minutes).
    # v36 (part-iii merge): v35 plus ``open_design_leg@1`` — the delegation entry that opens the
    # design leg (§1-D1's "attach as subagent" wrapper, materialized as a durable act; introduced
    # as PD-part3 P3.4's v24, re-versioned onto the v35 chain at the integration merge). v35
    # preserves the frozen v34 surface and gives Account-focused turns the exact pinned
    # field/source vocabulary needed to launch profiling without model-invented field keys.
    # v40 (2026-08-27, demo-night model correction): v39 with ``model_id: x-ai/grok-4.6`` —
    # the founder's 2026-08-23 grok-everywhere directive finally applied to the conversation
    # profile (gpt-5.6-terra returned plain-text stops under tool_choice=required and killed
    # turns as ``missing_finalize``).
    # v43 (ARV2-R0 merge, 2026-09-01): v40 plus comprehensive's directive contract —
    # ``draft_account_research_directive@5`` and account-deep-steering v8. Minted at the merge
    # because v40 and v42 are DIVERGENT SIBLINGS, not a chain: v42 carries the directive contract
    # but pins prompt v4, ``open_design_leg@1``, and ``openai/gpt-5.6-terra``, so it cannot even
    # resolve here (this line retired @1/@2/@3) and would revert the grok-4.6 correction. v42
    # stays on disk, replay-only, exactly as minted.
    # v44 (ARV2 onboarding O6, 2026-09-09): v43 with the new-lane Stage-0 surface — prompt v8 and
    # stage0-interview v21. The twelve old-lane tools (recon, readiness, Client-KB/Product-KB
    # listing and inspection, the `icp_spec` synthesis and single-product gate, the discovery
    # configuration gate, the onboarding-input capture and the confirmed-run start) are gone,
    # because the knowledge they served is now brand knowledge documents the agent reads off its
    # workspace. What replaces them is the product-set gate, `open_icp_confirmation_gate@2` over
    # the ICP knowledge document, and the ARV2 launch/read pair. Model, workspace, delegation and
    # limits are v43's, unchanged.
    # v45 (ARV2 Track R, R4, 2026-09-10): v44 plus ONE tool — `launch_arv2_discovery@1`, verified
    # account discovery for a project — and stage0-interview v22, whose §7b is the procedure for
    # it. Nothing is dropped and nothing is re-pinned; everything else is v44's.
    # v46 (ARV2 context and authoring, 2026-09-12): v45 plus `author_icp_document@1` and
    # `request_persona_synthesis@1` — the agent may write a proposed ICP document (brand-level or
    # a project-local variant) and ask the platform for its personas — and stage0-interview v23,
    # whose §5b and §5c are the procedures and whose §1 names the project's own files. Neither
    # tool confirms anything: the ICP gate is still the human's. Everything else is v45's.
    # v47 (project plan, 2026-09-12): v46 plus ONE tool — `write_project_document@1`, the
    # project's one plan written with a revision check — and stage0-interview v24, whose §6b says
    # when the plan is written (after the section-2 answers, a confirmed ICP and a confirmed
    # product set) and what it contains. The human edits the same file in the Plan tab, so a
    # stale write is refused by name rather than overwriting their words. Everything else is v46's.
    # v48 (read tools, 2026-09-13): v47 plus THREE effect-free reads over the project's own ARV2
    # rows — `read_project_accounts@1` (the accounts in the project and each one's research
    # status), `read_account_research@1` (one account's written overview, or its live claims) and
    # `read_discovery_run@1` (the latest or a named discovery run with its candidates) — and
    # stage0-interview v25, whose §7c says to read before speaking about accounts and whose §7b
    # says to read the last discovery run before proposing another. None of them spends, approves
    # or launches: they replace "what my own thread happened to start" with what the rows say.
    # Everything else is v47's.
    # v49 (read-tool contract repairs, 2026-09-13): v48's three reads with their contracts fixed,
    # and stage0-interview v26. The rows they serve are typed in the output schema now, so a later
    # change to a row shape moves the digest and this pin notices; `read_account_research`'s claims
    # are gated exactly as the account page gates them (sensitive, unverified tier-4 and
    # outreach-unsafe held back and counted) so chat cannot state a fact the app refuses to print;
    # `read_project_accounts` gained `query`/`offset` so a named account past the first page is
    # reachable; and `read_discovery_run`'s `verified` counts the candidates the verifier judged.
    # No tool is added or dropped. Everything else is v48's.
    # v50 (read-tool hotfix, 2026-09-13): v49's three reads with the hotfix contracts, and
    # stage0-interview v27. `read_account_research` pages its claims (`offset`/`next_offset`) under
    # a byte budget so a wide account fits the governed receipt, and names the account's own claim
    # families in `prefixes` so a narrowing prefix is never invented; `read_discovery_run` accepts
    # the schema's own `pass` on input so its result passes the runner's validation. §7c now says
    # an overview renders on first page view (so `overview_not_written` is not a failure) and that
    # claims are read to the end before a count is stated. No tool is added or dropped. Everything
    # else is v49's.
    # v51 (thread workspace, 2026-09-13): v50's surface with the workspace block moved to the
    # thread layout — the turn now runs in one persistent directory per chat thread, so `scratch/`
    # is the agent's notebook (readable and writable, and it survives the turn), `reads/` is
    # readable, `work/` stays readable and writable — the Head of ABM's own skill never names it,
    # but the registry intersects a child's workspace with its parent's, so dropping it would take
    # every delegated specialist's scratch pad away — and the quota rises to 400 files / 20 MiB.
    # stage0-interview v28 §1 names the notebook: what to keep in `scratch/` and what belongs in
    # the project's own files instead. No tool is added or dropped. Everything else is v50's.
    # v52 (the mounted libraries, 2026-09-13): v51's surface with the two read-only library
    # mounts granted — `brand/` (the brand's knowledge, materialized once per pinned version) and
    # `project/` (the project's settled state: `status.md`, `decisions.md`, its own documents and
    # the artifact index, compiled once per project). Both are readable, neither is writable: a
    # library is the platform's word about what is settled, and the agent changes it through a
    # governed tool, never by writing a file. prompt head-of-abm v9 and stage0-interview v29 name
    # those mounted paths instead of the per-turn seed paths under `inputs/`. No tool is added or
    # dropped. Everything else is v51's.
    # v53 (brand index path, 2026-09-14): v52's surface with the skill pin moved v29→v30 —
    # §1 names the brand library's manifest at its real mounted path, `brand/index.json`.
    # v54 (the operating manual, 2026-09-14): v53's surface with the manual disclosed. Fifteen
    # `manual-*@v1` chapters join the skill pins, so the capability map names each one with a
    # summary and an openable path and the agent can read the chapter instead of guessing. Every
    # chapter grants no tool, so the governed surface is byte-for-byte v53's. Prompt pin v9→v10
    # (the specialist-delegation paragraph is dropped, because this surface withholds delegation,
    # and Stage 0 now points at the manual); skill pin v30→v31 (§1/§6/§7c/§10 name the chapter
    # that answers the step's question, and §6 no longer claims an unrouted finalization is
    # refused here).
    # v55 (the versioned project root, 2026-09-14): v54's surface with the project's documents
    # written as FILES. `project/` joins `writable_prefixes`, so a `write_file` at
    # `audience/icp-<key>.md`, `audience/persona-<key>.md` or `plan.md` lands a new version of the
    # document that path names; `author_icp_document@1`, `request_persona_synthesis@1` and
    # `write_project_document@1` are ungranted for exactly that reason — two ways to write one
    # document is one too many. Skill pin v31→v32 keeps §5b/§5c/§6b as pointers and three new
    # skills (`icp-authoring@v1`, `persona-authoring@v1`, `plan-authoring@v1`) carry the
    # procedures; none of them grants a tool. The manual re-mints at `manual-*@v2` because the
    # grant it describes moved and a catalog version is immutable. Prompt stays v10. Three
    # addresses leave the interaction slot, so the conversation recipe moves 26 → 27.
    # v56 (paged and spilled reads, 2026-09-14): v55's surface with the read side finished. Two
    # reads move to their PAGED contract — `read_account_research@2` and `read_discovery_run@2`
    # take `offset`/`limit` and answer `next_offset`, so a wide account or a long discovery is
    # walked to the end instead of guessed at from one page — and two reads are granted for the
    # first time: `read_claims@1` (the general claims query over one account or contact, narrowed
    # by family, tier, verification status or date, behind the account page's own display gate)
    # and `read_artifact@1` (one artifact of this project's gallery by id, its summary or the
    # words on its page). None of them spends, approves or launches. The `@1`s of the two paged
    # reads stay registered, and recipe0-stage0@27 stays their replay input, so the name-only
    # default alias moves to `@2` with the pin. Skill pin v32→v33 (§7c is the read map: which
    # read answers which question, pages read to the end, `field_prefix` taken from `prefixes`, a
    # `spilled_to` receipt read from its file in chunks and noted in `scratch/notes.md`); the
    # three document skills move to v2. The manual re-mints at `manual-*@v3` because the grant it
    # describes moved. Prompt stays v10. The conversation recipe moves 27 → 28: the interaction
    # slot re-pins the two reads to `@2` and admits the two new addresses.
    AgentRole.HEAD_OF_ABM: "v56",
    AgentRole.RESEARCH: "v7",
    AgentRole.CONTENT_DRAFTER: "v5",
    AgentRole.REVIEWER: "v5",
    # P3.3 (PD-part3): the composite design deepagent's platform-facing profile.
    AgentRole.DESIGN: "v1",
    # ARV2 Track O, O4: the onboarding synthesis agent (ARV2-ONBOARDING-PLAN.md §5). v2 splits the
    # one turn into one ICP turn plus one persona turn per ICP: each fleet-run turn takes exactly
    # one task, the ICP skill reuses the keys of the ICPs already on file, and the persona skill
    # writes one document for the one ICP it is given. Its whole spendable surface is
    # ``exa_search_evidence@1`` — withheld on ``onboarding_icp``, where the profiles are written
    # from the files alone; it delegates to nobody. Model per ruling O-D1: ``x-ai/grok-4.6`` at
    # the model's default reasoning effort.
    AgentRole.ONBOARDING_SYNTHESIS: "v3",
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
    # The three document tools, retired from the role at `head-of-abm@v55`. Each one wrote a
    # project document through a governed call — a proposed ICP, its personas, the plan. The
    # versioned `project/` mount does the same work from an ordinary `write_file`, so the grant
    # would only offer two ways to write one document and two vocabularies for its refusals. They
    # stay REGISTERED and audited — an execution pinned to recipe0-stage0@26 or earlier replays
    # against its own immutable revision — and the procedures moved to the `icp-authoring`,
    # `persona-authoring` and `plan-authoring` skills that stage0-interview v32 §5b/§5c/§6b point
    # at. Empty here means structurally absent from every current model surface, as everywhere
    # else in this map.
    "author_icp_document": (),
    "request_persona_synthesis": (),
    "write_project_document": (),
    # The ARV2 reads: what this project's own rows already say — its accounts and their research
    # status, one account's overview or claims, one discovery run and its candidates. Granted with
    # `head-of-abm@v48` (contracts repaired at v49); stage0-interview v26 §7c is the procedure and
    # its §7b says to read the last discovery run before proposing another. They spend nothing,
    # approve nothing and launch nothing, so the only thing a call can do is make an answer true:
    # a fact about an account now comes from a claim the read returned rather than from an earlier
    # thread's memory.
    "read_project_accounts": (AgentRole.HEAD_OF_ABM,),
    "read_account_research": (AgentRole.HEAD_OF_ABM,),
    "read_discovery_run": (AgentRole.HEAD_OF_ABM,),
    # Their newest sibling: the general claims query (one account or contact, by field family,
    # source tier, verification status or date, paged, behind the same display gate). Granted with
    # `head-of-abm@v56` — the bump that pins its contract and mints the manual chapter that
    # teaches it, because `build_agent_profile_registry` refuses to compose when a role's
    # authority and its profile's tool list disagree, so a grant is that bump and never a dict
    # edit. stage0-interview v33 §7c says which question it is the read for.
    "read_claims": (AgentRole.HEAD_OF_ABM,),
    # The same posture for the gallery read: one design artifact of this project — what it is,
    # what it is called, and (asked for) the words on the page. It reads the rail's own rows and
    # changes nothing, and it is granted with the same `head-of-abm@v56` bump, so describing an
    # artifact stops being a memory of the turn that made it.
    "read_artifact": (AgentRole.HEAD_OF_ABM,),
    "create_thread": (),
    "rename_thread": (),
    "rename_project": (),
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
    # Clone-fidelity F4.3, FOUNDER RULING R-F1 (2026-08-29): the durable `noindex` stamp on a
    # published web document. UNGRANTED, and deliberately so, unlike its two neighbours above.
    # The ruling's whole point is that TAKING the robots meta off an ABM account page is an
    # explicit human act; a model that held this tool could clear it. The design API's own
    # route invokes it as `actor="human"`, and the ABM batch stamps it ON through the same
    # tool — neither is a model surface. Registered regardless, so the audit question "which
    # durable writes can the platform name?" stays a complete statement (the ad-assets
    # precedent below). Granting it later is a reviewed profile version bump.
    "design_set_web_noindex": (),
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
    # Brand Ad Assets v1 W2 — the ad-assets lane. UNGRANTED, and deliberately so: the lane is
    # populated by an onboarding JOB, whose worker invokes these through the design toolbelt
    # directly (actor="agent"), exactly as the brand-kit ingestion worker does. No model
    # surface plans a harvest, so handing these to one would be authority nobody asked for.
    # Registered here regardless, so the audit question "which durable writes can the platform
    # name?" stays a complete, static statement. Granting them later is a reviewed profile
    # version bump, which is the review this deliberately does not pre-empt.
    "design_ingest_ad_assets": (),
    "design_record_ad_creatives": (),
    "design_publish_ad_dna_card": (),
    "design_link_ad_pregenerated_assets": (),
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
    # ARV2 onboarding O6: dropped from the Head-of-ABM surface at v44. There is no readiness
    # check on the new lane — the brand's knowledge documents either exist or they do not, and the
    # agent says which. Registered here so the audit stays a complete statement.
    "evaluate_stage0_readiness": (),
    # ARV2 onboarding O4 (plan §4.5): the synthesis agent's one SPEND tool — a single fixed
    # deep-reasoning search for first-person evidence, at most once per persona role. No other
    # role may buy it: this is the onboarding synthesis turn's own governed provider call.
    "exa_search_evidence": (AgentRole.ONBOARDING_SYNTHESIS,),
    "get_research_view": (
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "import_accounts": (),
    # PC-C8 §7 (task 1.5's deferred grant, landed against profile v10) granted six read-only
    # cursor-resolution tools here. ARV2 onboarding O6 drops five of them at `head-of-abm@v44`:
    # they all read the Client-KB / Product-KB claim surfaces, and the new lane's Stage-0 knowledge
    # is brand knowledge documents the agent reads off its own workspace instead. Only
    # `inspect_statement_history` survives — it reads what the human said in this conversation,
    # which the new lane still records through `record_interview_answer`.
    "inspect_readiness_history": (),
    "inspect_client_claim": (),
    "inspect_product_claim": (),
    "inspect_statement_history": (AgentRole.HEAD_OF_ABM,),
    "list_client_knowledge": (),
    "list_product_knowledge": (),
    "launch_account_deep": (),
    # ARV2 onboarding O6 / FOUNDER RULING 2 (2026-09-10): the five old-research-lane tools are
    # dropped from the Head-of-ABM surface at v44. `head-of-abm@v44` runs one research lane, and it
    # is the ARV2 pair below: these three launches start entity-research fleet jobs the new lane
    # does not use, and the two run reads answer about `account_research_run` rows it never writes.
    # They stay registered and invocable by whatever non-model surface still calls them; what
    # changes is that no model surface names them. The skill that required all five —
    # `account-deep-steering@v8` — leaves v44 with them; a steering skill written against the ARV2
    # tools is a follow-up, and it is not a re-grant of these.
    "launch_account_research": (),
    # ARV2 Track R, R2 (seam 1). Registered UNGRANTED, on the terms the ad-assets lane and the
    # pre-P3.3 design writes already established: the platform's write surface stays complete and
    # auditable, and the role decision lands with the profile version that teaches it. Granting is
    # not a dict edit here — `build_agent_profile_registry` refuses to compose when a role's
    # authority and its profile's tool list disagree, so the Head-of-ABM grant requires a new
    # head-of-abm profile version carrying both pins AND the conversation surface's promoted
    # profile pin moving with it (`PROJECT_CONVERSATION_AGENT_PROFILE_ID`, checked at
    # `agent_turn_fleet_wiring.py:561`). That is O6's bump — it is the slice that gives the Head of
    # ABM the launch, along with the prompt/skill content telling it what to confirm first. Until
    # then the lane is launched by a human: `scripts/launch_arv2_account_research.py`.
    # ARV2 onboarding O6 (T6): granted. `head-of-abm@v44` pins both and stage0-interview v21 §6
    # states the preconditions the tool itself enforces — a confirmed ICP document version, a
    # confirmed product set, and the exact accounts attached to the current human turn.
    "launch_arv2_account_research": (AgentRole.HEAD_OF_ABM,),
    # ARV2 Track R, R3: the same launch for named *people*, on exactly the same terms and for the
    # same reason. It researches contacts a human picked (or a committee step resolved). Registered
    # ungranted by R3 (a human act through `scripts/launch_arv2_person_research.py`); the O6 grant
    # to the Head of ABM lands with the v44 pin that teaches it.
    # ARV2 onboarding O6 / FOUNDER RULING 3 (2026-09-10): granted. Researching people a human
    # named is the same act on the same lane as researching accounts they named, so it is granted
    # on the same terms — `head-of-abm@v44` pins it, and the skill text that teaches it is
    # stage0-interview v21's.
    "launch_arv2_person_research": (AgentRole.HEAD_OF_ABM,),
    "read_arv2_account_research_run": (AgentRole.HEAD_OF_ABM,),
    # ARV2 Track R, R4: granted with head-of-abm@v45; stage0-interview v22 §7b teaches it.
    # Finding candidate accounts from the ICP the project pinned is the same act on the same lane
    # as researching accounts a human named, granted on the same terms — the human's own turn asks
    # for it, the ICP and the gates come from the pinned document rather than the call, and a
    # successful result means a run was queued, never that companies were found or approved.
    "launch_arv2_discovery": (AgentRole.HEAD_OF_ABM,),
    "launch_selected_account_research": (),
    "launch_contact_research": (),
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
    # ARV2 onboarding O6: dropped at v44. Discovery scope is not configured from the Stage-0
    # conversation on the new lane — the human attaches the accounts to the turn.
    "open_discovery_configuration_gate": (),
    "open_icp_confirmation_gate": (AgentRole.HEAD_OF_ABM,),
    # ARV2 onboarding O6: dropped at v44, superseded by the set-valued gate below. A project
    # targets a SET of products, and the candidates come from the brand's own product rows.
    "open_product_selection_gate": (),
    # ARV2 onboarding O6 (T3/T6): granted, and `head-of-abm@v44` pins it. The agent may present
    # the exact derived candidate set; only the human confirms it, and the gate receipt is the only
    # authority a confirmed product set ever has.
    "open_product_set_selection_gate": (AgentRole.HEAD_OF_ABM,),
    "override_stage0_readiness": (),
    "pause_run": (),
    "profile_contact": (),
    "propose_field": (AgentRole.HEAD_OF_ABM,),
    "propose_source": (AgentRole.HEAD_OF_ABM,),
    "read_account_research_run": (),
    "read_contact_research_run": (),
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
    # ARV2 onboarding O6: dropped at v44. The new lane launches research per account through
    # `launch_arv2_account_research`, not by starting a phase-machine project run.
    "start_confirmed_project_run": (),
    "start_project_run": (),
    # ARV2 onboarding O6: dropped at v44. There is no recon on this surface — onboarding produced
    # the brand's knowledge documents before the conversation ever opened.
    "start_recon": (),
    "submit_ingestion": (AgentRole.HEAD_OF_ABM,),
    # ARV2 onboarding O6: dropped at v44. Its only consumer was `start_recon`.
    "submit_onboarding_input": (),
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
    # ARV2 onboarding O6: dropped at v44. The ICPs are written by the onboarding synthesis agent
    # into the brand's knowledge documents; the Head of ABM proposes from those files and can never
    # author one.
    "synthesize_icps": (),
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

#: ARV2 onboarding O4: the fleet-owned synthesis turn executes the one-gate
#: ``onboarding-synthesis-unit@1`` recipe. The synthesis agent's whole spendable surface there is
#: ``exa_search_evidence@1``; resolving a named surface makes the manifest, the middleware, and the
#: installed tools describe that one authority before the model wakes.
ONBOARDING_SYNTHESIS_UNIT_SURFACE = "onboarding_synthesis_unit"

#: ARV2 onboarding O4 (synthesis split): the ICP turn of the split synthesis run. It writes the
#: client's profiles from the brand's own knowledge documents, so it has no honest use for the
#: evidence tool — and the rule that it must not search is governed by a tool that is not
#: installed, never by a sentence in the skill. The persona turns keep the full role surface,
#: where the per-role evidence pass is the point.
ONBOARDING_ICP_SURFACE = "onboarding_icp"

#: PC-C8 §8: surface restrictions are enforced by tools that are *not installed*, never by prose in
#: a shared skill or a context card. Each entry narrows one role's effective tool set on one named
#: surface; the registry refuses a policy that withholds a tool the role's profile does not pin, so
#: a rename cannot quietly restore a withheld capability.
#:
#: The trial withholds the launch and delegation surfaces, all for one reason — this surface is a
#: manual conversation and does no external research, and neither the model nor the platform
#: captures anything on the agent's behalf.
#:
#: ARV2 onboarding O6 shortened this list without relaxing it. The registry refuses a policy that
#: withholds a tool the role's profile does not pin, and ``head-of-abm@v44`` no longer pins
#: ``start_recon``, ``submit_onboarding_input``, ``synthesize_icps``,
#: ``open_product_selection_gate``, ``open_discovery_configuration_gate`` or — per founder ruling
#: 2, 2026-09-10 — ``launch_account_research``, ``launch_selected_account_research``,
#: ``launch_contact_research``, ``read_account_research_run`` and ``read_contact_research_run`` at
#: all. They are ungranted on *every* surface now, which is a stronger statement than withholding
#: them on one. The trial's own reasons for withholding them are preserved in the authority map
#: above.
#:
#: ``submit_ingestion`` is deliberately **kept**: it ingests an already-captured workspace artifact
#: and performs no external research, so it does not cross this surface's boundary.
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
                # D4 added the gate tool to the role. The trial keeps it withheld alongside the
                # launches below, which is where it belongs: a dev harness that could present a
                # real, durable, addressed confirmation gate — but never act on the answer — would
                # be inviting a human to approve spend that no surface here can perform.
                "open_directive_confirmation_gate",
                # P3.4 added the design delegation entry to the role. The trial withholds it for
                # the same sentence as delegation itself: this surface is a manual conversation,
                # and a leg opened from a dev CLI would durably reroute a thread no design
                # runtime here can serve.
                "open_design_leg",
                # ARV2 onboarding O6: the new lane's launch and its two gates join the same
                # sentence their predecessors are here for. `launch_arv2_account_research` queues
                # real per-account research jobs against external providers, which is precisely
                # what this surface promises it does not do; `open_product_set_selection_gate` and
                # `open_icp_confirmation_gate` each write a real, durable, human-addressed gate
                # whose answer no surface here can act on — inviting a person to confirm a product
                # set or an ICP that goes nowhere. `read_arv2_account_research_run` stays
                # installed: it is read-only, spends nothing, and addresses nobody.
                # `launch_arv2_person_research` joins for the same sentence as its account sibling
                # (founder ruling 3, 2026-09-10) — it queues real per-person research jobs — and
                # so does `launch_arv2_discovery` (ARV2 Track R, R4): it queues a real discovery
                # run against providers, buying a long list and verifying it company by company.
                "launch_arv2_account_research",
                "launch_arv2_discovery",
                "launch_arv2_person_research",
                "open_product_set_selection_gate",
                "open_icp_confirmation_gate",
                # `author_icp_document`, `request_persona_synthesis` and `write_project_document`
                # used to stand here. `head-of-abm@v55` does not grant any of them on any surface,
                # and a policy may only narrow tools the profile pins, so there is nothing left to
                # withhold — ungranted everywhere is the stronger statement, exactly as it was for
                # the old-lane tools at v44. (The writes they performed are now file writes under
                # `project/`, which this surface's workspace policy governs, not its tool ceiling.)
                # The three ARV2 reads spend nothing and address nobody, so they are withheld for
                # the OTHER reason PC-C8 §2.4 gives: the trial's own `build_toolbelt` passes no
                # `arv2_reads`, so installed they would be advertised in the capability map and
                # refuse `arv2_reads_not_composed` at call time — restriction by refusal, which
                # that section rejects. Withheld, the trial's framing sentence is true: this
                # surface has no read surface over the project's rows.
                # `read_claims` joins them at `head-of-abm@v56` for the identical sentence — it
                # reads through the same uncomposed `arv2_reads` service — and `read_artifact`
                # joins for the nearest thing to it: it needs no service, but a dev-harness turn
                # carries no project, so installed it could only refuse `project_not_found`.
                "read_project_accounts",
                "read_account_research",
                "read_claims",
                "read_artifact",
                "read_discovery_run",
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
    # turn's own `action_ref` threaded into the tool context. Its remaining two subtractions were
    # ``start_recon`` and ``submit_onboarding_input``, the trial's, for the trial's reasons.
    # ARV2 onboarding O6 empties the tool ceiling because ``head-of-abm@v44`` does not pin either
    # tool on any surface: the role-wide drop is stronger than this surface's withholding was, and
    # the registry refuses a policy that withholds a tool the profile never grants. The policy
    # stays for its delegation ceiling and its framing — this surface still delegates to nobody.
    AgentSurfacePolicy(
        surface=PROJECT_CONVERSATION_SURFACE,
        role=AgentRole.HEAD_OF_ABM,
        withheld_tools=frozenset(),
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
            "they tell you, write the project's ICP, its personas and its plan as files under "
            "`project/`, open the product-set and ICP confirmation gates, and launch ARV2 "
            "discovery, account research and person research on this project when the human asks "
            "for them. You read the project's accounts, their research and claims, its discovery "
            "runs and its gallery artifacts from the rows before speaking about them. You do not "
            "fetch external sources yourself, delegate to a "
            "specialist, or widen a set the human selected."
        ),
    ),
    # ARV2 O4 (synthesis split): the ICP turn writes the client's profiles from the brand's
    # knowledge documents alone, so `exa_search_evidence` is withheld rather than merely
    # discouraged. The role's whole spendable surface is that one tool, so this ceiling makes the
    # ICP turn structurally unable to spend; the persona turns resolve the unnarrowed role and
    # keep it, because their per-role evidence pass is what the tool is for.
    AgentSurfacePolicy(
        surface=ONBOARDING_ICP_SURFACE,
        role=AgentRole.ONBOARDING_SYNTHESIS,
        withheld_tools=frozenset({"exa_search_evidence"}),
        withheld_reason_code="icp_turn_writes_from_files_only",
        framing=(
            "This surface is the ICP turn of onboarding synthesis: you write the client's ideal "
            "customer profiles from the brand knowledge documents in your context and on disk. "
            "You do not search external sources; the persona turns do that."
        ),
    ),
)

_HUMAN_ONLY_TOOLS = frozenset(
    {
        "adjust_budget",
        # R-F1 (clone-fidelity T27): clearing a published account page's robots meta is a
        # human act by founder ruling — the tool is registered ungranted, and this membership
        # makes the human-only claim structural rather than a fact about today's grant table.
        "design_set_web_noindex",
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
    # ARV2 onboarding O6: the seventeen tools `head-of-abm@v44` dropped. They stay registered and
    # invocable by whatever non-model surface still calls them; what this records is WHY no model
    # surface names them any more — the new Stage-0 lane reads the brand's knowledge documents
    # instead of the Client-KB/Product-KB claim surfaces, its gates are the product-set gate and
    # the artifact-ref ICP gate, and its research is launched on the ARV2 lane.
    "evaluate_stage0_readiness": "superseded_by_onboarding_v2",
    "inspect_readiness_history": "superseded_by_onboarding_v2",
    "list_client_knowledge": "superseded_by_onboarding_v2",
    "inspect_client_claim": "superseded_by_onboarding_v2",
    "list_product_knowledge": "superseded_by_onboarding_v2",
    "inspect_product_claim": "superseded_by_onboarding_v2",
    "start_confirmed_project_run": "superseded_by_onboarding_v2",
    "open_product_selection_gate": "superseded_by_onboarding_v2",
    "synthesize_icps": "superseded_by_onboarding_v2",
    "start_recon": "superseded_by_onboarding_v2",
    "submit_onboarding_input": "superseded_by_onboarding_v2",
    "open_discovery_configuration_gate": "superseded_by_onboarding_v2",
    # FOUNDER RULING 2 (2026-09-10): the five old-research-lane tools, on the same terms as the
    # twelve above. The new lane's `launch_arv2_*` pair supersedes the three launches, and
    # `read_arv2_account_research_run` supersedes the two run reads.
    "launch_account_research": "superseded_by_onboarding_v2",
    "launch_selected_account_research": "superseded_by_onboarding_v2",
    "launch_contact_research": "superseded_by_onboarding_v2",
    "read_account_research_run": "superseded_by_onboarding_v2",
    "read_contact_research_run": "superseded_by_onboarding_v2",
}


def _roles_for(address: str, name: str) -> tuple[AgentRole, ...]:
    """Resolve authority by exact address where versions have different safety proofs."""

    # (ARV2 onboarding O6 deleted the exact-address rules for `list_client_knowledge`,
    # `inspect_client_claim`, `list_product_knowledge`, `inspect_product_claim`,
    # `evaluate_stage0_readiness`, `synthesize_icps` and `start_confirmed_project_run`. Those rules
    # existed to grant ONE safe version of a tool the Head of ABM held; v44 holds none of them, so
    # they now fall through to the authority map above, which says `()` for every version.)
    if name == "propose_field":
        return (AgentRole.HEAD_OF_ABM,) if address == "propose_field@2" else ()
    if name == "draft_account_research_directive":
        return (AgentRole.HEAD_OF_ABM,) if address == "draft_account_research_directive@5" else ()
    # ARV2 onboarding O6 (T4/T6): ``@2`` presents the ICP knowledge document instead of a draft
    # ``icp_spec`` row, and its approval mints a confirmed version of that document. ``@1``'s
    # subject — a draft ``icp_spec`` row — is not written on this lane at all, so the grant moves
    # to ``@2`` with the ``head-of-abm@v44`` pin. ``@1`` stays registered and frozen for replay.
    if name == "open_icp_confirmation_gate":
        return (AgentRole.HEAD_OF_ABM,) if address.endswith("@2") else ()
    # The paged reads. `read_account_research@2` and `read_discovery_run@2` take `offset`/`limit`
    # and answer with `next_offset`, and `head-of-abm@v56` pins those exact contracts, so the
    # grant is theirs. The `@1`s stay REGISTERED, and recipe0-stage0@27 stays the exact replay
    # input for a turn pinned to it — @28 RE-PINS the key rather than admitting both, because one
    # requirement set resolves one version per (kind, key) — but a role holding a version no
    # current profile pins is authority nobody asked for, so they are ungranted here.
    # The same shape `open_icp_confirmation_gate` has, with the grant on the newer version.
    if name in {"read_account_research", "read_discovery_run"}:
        return (AgentRole.HEAD_OF_ABM,) if address.endswith("@2") else ()
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
