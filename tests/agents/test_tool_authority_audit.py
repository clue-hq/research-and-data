"""Current C6 replay/authority audit over the complete tool registry."""

from __future__ import annotations

from pathlib import Path

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY, c6_roles_for_tool
from clue_api.coverage_tools import coverage_evaluator_owner
from clue_api.toolbelt_wiring import build_toolbelt
from clue_toolbelt import ReplayPolicy, ToolEffectClass

_HUMAN_ONLY_STEERING = {
    "adjust_budget",
    "confirm_project_product",
    "override_stage0_readiness",
    "pause_run",
    "resume_run",
    "submit_project_checkpoint",
    "submit_tier_checkpoint",
}

_REPLAY_BLOCKED = {
    "decide_field_proposal@1",
    "decide_source_proposal@1",
    "research_account_gaps@1",
    "retry_ingestion@1",
}
_C65_CERTIFIED = {
    "propose_field": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "propose_source": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "submit_ingestion": ReplayPolicy.AT_LEAST_ONCE,
}


def test_every_current_tool_has_an_explicit_c6_authority_decision() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(C6_AGENT_TOOL_AUTHORITY) == set(registry.names())
    # Every addition must have a reviewed role decision here. O2 added the account-deep launch
    # boundary; M8D R10 retires it from every active role (exact historical replay only) and
    # promotes the separately confirmed account/contact entity-research launch and read tools.
    # Part II D6 Round A: the design subsystem's eight governed write tools join the audit with
    # NO role — registered so the platform's write-authority surface is complete, granted to
    # nobody until Part III wires the design deepagent (48 -> 56). Round B adds the documents /
    # history / diagnostics plane, the website-mode documents and the two turn enqueues on the
    # same terms (56 -> 76). Round C adds the last twenty-one — brand kits x4, ingestion
    # enqueues x3, the asset registry x7 and personalization + both batch families x7
    # (76 -> 97), which empties UNCONVERTED_MUTATIONS on the design side.
    # FI Lane D D0 added the four REQ-21 thread tools, all ungranted: they are invocable by the
    # authenticated chat surface but sit on no model surface, and they are not human-only either.
    # FI Lane D D4 added `open_directive_confirmation_gate`, and Stage-0 hardening added the exact-
    # subject ICP confirmation counterpart. Both are granted to the Head of ABM: asking the human
    # for authority is that role's own act, and neither tool can address a gate to anybody but the
    # human whose turn it is answering.
    # P3.3 (PD-part3, 2026-08-14): the moment Part II staged — all 49 design tools flip from
    # `()` to `(AgentRole.DESIGN,)`. One role, the composite design deepagent (ruling D2),
    # gains the design write surface it always described; every other role still sees the
    # design plane as role-unavailable. The count is unchanged: this is a grant, not a tool.
    # P3.4 (PD-part3 §1-D1/§2.3): `open_design_leg` joins, granted to the Head of ABM — the
    # delegation entry that validates the D5 pins, freezes the §2.3 bundle, and opens the
    # durable design leg whose existence IS the routing rule. It spends nothing and dispatches
    # nothing; the trial surface withholds it.
    # P3.5 (PD-part3 §2.2): `finish_design_leg` joins, granted to the DESIGN role — the
    # engine-validated leg-level exit and the only path to a closed leg. Turn-level
    # finalization (the design harness's final.json) is a different authority and remains
    # design-runtime-internal.
    # The part-iii integration merge unions that design lineage (49 design grants + the two leg
    # tools) with this branch's own additions since the common base: 63 + 49 + 2 = 114.
    # Brand Ad Assets v1 W2 adds the ad-assets lane's four write envelopes, all UNGRANTED
    # (114 -> 118) — see the carve-out below.
    # Clone-fidelity F4.3 / FOUNDER RULING R-F1 (2026-08-29) adds `design_set_web_noindex`,
    # UNGRANTED (118 -> 119). The ruling makes clearing a published ABM page's robots meta an
    # explicit HUMAN act; the design API's route invokes the tool as actor="human" and the ABM
    # batch stamps it ON through the same door. A model surface that held it could take the
    # noindex off an account page, which is the one thing the ruling exists to prevent.
    # ARV2 onboarding O4 adds `exa_search_evidence` (119 -> 120), granted to the synthesis agent
    # alone: it is the one SPEND tool of the onboarding synthesis turn (plan §4.5 — at most one
    # call per persona role, behind `CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED`), and no other role
    # has a reason to buy a deep-reasoning web search from inside a conversation.
    # ARV2 Track R, R2 adds the account-research lane's two toolbelt surfaces (120 -> 122), and
    # ARV2 Track R, R3 adds `launch_arv2_person_research` (122 -> 123), UNGRANTED on the same
    # terms as the account launch was (a human act through
    # `scripts/launch_arv2_person_research.py`), and ARV2 onboarding O6 adds the set-valued
    # product gate (123 -> 124).
    # R2 registered the launch pair UNGRANTED and said the grant was not a dict edit —
    # `build_agent_profile_registry` refuses to compose when a role's authority and its profile's
    # tool list disagree, so it needed a new head-of-abm profile version carrying both pins AND the
    # conversation surface's promoted-profile pin moving with it. O6 is that bump:
    # `head-of-abm@v44` pins `launch_arv2_account_research@1`,
    # `read_arv2_account_research_run@1` and `open_product_set_selection_gate@1`, so all three are
    # granted to the Head of ABM here, and stage0-interview v21 §6 is the procedure that says what
    # must be confirmed before the launch may be called. FOUNDER RULING 3 (2026-09-10) adds R3's
    # person launch to that same bump: researching named people is the same act on the same lane,
    # so it is granted here and pinned in v44 beside its account sibling.
    #
    # The same slice moved SEVENTEEN old-lane tools the other way, to `()` — the twelve
    # recon/readiness/Client-KB/Product-KB tools, plus (FOUNDER RULING 2, 2026-09-10) the five
    # old-research-lane tools `launch_account_research`, `launch_selected_account_research`,
    # `launch_contact_research`, `read_account_research_run` and `read_contact_research_run`. They
    # stay registered and audited — the complete-write-surface property is what this file is for —
    # but no model surface names them: the new Stage-0 lane reads the brand's knowledge documents
    # instead of recon-ing the company, has no readiness check, confirms a product SET rather than
    # one product, and launches research on the ARV2 lane rather than the entity-research fleet.
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1` (124 -> 125) and grants it here: the
    # grant lands with `head-of-abm@v45`, which pins it, and stage0-interview v22 §7b is the
    # procedure that says what must be confirmed first — a project whose ICP and product set are
    # confirmed — and what a successful result does and does not mean (the run is queued; no
    # account is found or approved by the call).
    # Project rename is installed for the human UI, ungranted to all agents (125 -> 126).
    # ICP authoring registered `author_icp_document@1` (126 -> 127) and
    # `request_persona_synthesis@1` (127 -> 128) ungranted, and this is the version that grants
    # both: they are pinned by `head-of-abm@v46`, and stage0-interview v23 §5b/§5c are the
    # procedures that say what may be written down (only what the brand's knowledge files and the
    # human support) and what a call does NOT do — authoring mints a *proposed* document the human
    # still confirms at the ICP gate, and the persona request queues a background turn rather than
    # returning a document.
    # The project plan registered `write_project_document@1` (128 -> 129) ungranted, and this is
    # the version that grants it: it is pinned by `head-of-abm@v47`, and stage0-interview v24 §6b
    # is the procedure that says when a plan may be written (after the section-2 answers, a
    # confirmed and pinned ICP and a confirmed product set) and what a call does NOT do — it
    # decides nothing new, and the human's own edits in the Plan tab win over a stale write.
    # The three ARV2 reads registered (129 -> 132) ungranted, and this is the version that grants
    # them: they are pinned by `head-of-abm@v48`, and stage0-interview v25 §7c is the procedure
    # that says to read before speaking about accounts (§7b before proposing another discovery).
    # A call does NOT spend, approve or launch — each one only returns what the project's own rows
    # already say, which is what makes it safe to require before an answer.
    # The versioned project root registers nothing (the count stays 132) and UNGRANTS three:
    # `author_icp_document`, `request_persona_synthesis` and `write_project_document` are dropped
    # from the role at `head-of-abm@v55`, because the documents they wrote are written as files
    # under the `project/` mount now. They stay registered and audited — this file's
    # complete-write-surface property is what keeps a retired tool visible — and an execution
    # pinned to recipe0-stage0@26 or earlier still replays them against its own revision.
    # The paged reads add no NAME and so no entry here (the count stays 132): the `limit` on
    # `read_account_research` and the `offset`/`limit` on `read_discovery_run` are new *addresses*
    # of names this map already carries, because a changed input schema at the same address would
    # break the digest `head-of-abm@v55` pins. Authority is therefore decided by address for both
    # names below — the `@1`s keep the grant the promoted profile pins, and the `@2`s register
    # ungranted until a reviewed profile version moves it, exactly as `open_icp_confirmation_gate`
    # does with the grant on the other version.
    # The general claims query DOES add a name (132 -> 133): `read_claims@1` is one account's or
    # one contact's live claims asked by field family, source tier, verification status or date,
    # behind the same display gate as `read_account_research`'s claims. It registers with the
    # name-only alias — it is the only version of itself — and is held by NOBODY: the grant needs
    # a profile version that pins its contract, which is a reviewed bump and not a dict edit.
    assert len(C6_AGENT_TOOL_AUTHORITY) == 133
    assert C6_AGENT_TOOL_AUTHORITY["read_project_accounts"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("read_project_accounts@1") == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["read_account_research"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("read_account_research@1") == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["read_discovery_run"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("read_discovery_run@1") == (AgentRole.HEAD_OF_ABM,)
    # Registered, audited, and held by nobody — the paged pair waits for its profile version.
    assert c6_roles_for_tool("read_account_research@2") == ()
    assert c6_roles_for_tool("read_discovery_run@2") == ()
    assert C6_AGENT_TOOL_AUTHORITY["read_claims"] == ()
    assert c6_roles_for_tool("read_claims@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["write_project_document"] == ()
    assert c6_roles_for_tool("write_project_document@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["author_icp_document"] == ()
    assert c6_roles_for_tool("author_icp_document@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["request_persona_synthesis"] == ()
    assert c6_roles_for_tool("request_persona_synthesis@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["launch_arv2_discovery"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("launch_arv2_discovery@1") == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["launch_arv2_person_research"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("launch_arv2_person_research@1") == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["launch_arv2_account_research"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["read_arv2_account_research_run"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("launch_arv2_account_research@1") == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("read_arv2_account_research_run@1") == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["open_product_set_selection_gate"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("open_product_set_selection_gate@1") == (AgentRole.HEAD_OF_ABM,)
    for dropped in (
        "evaluate_stage0_readiness",
        "inspect_readiness_history",
        "list_client_knowledge",
        "inspect_client_claim",
        "list_product_knowledge",
        "inspect_product_claim",
        "start_confirmed_project_run",
        "open_product_selection_gate",
        "synthesize_icps",
        "start_recon",
        "submit_onboarding_input",
        "open_discovery_configuration_gate",
        # FOUNDER RULING 2 (2026-09-10): the five old-research-lane tools. The new lane's
        # launch/read pair replaces them, and `account-deep-steering@v8` — the skill that required
        # all five — leaves v44 with them. A steering skill written against the ARV2 tools is a
        # follow-up, not a re-grant of these.
        "launch_account_research",
        "launch_selected_account_research",
        "launch_contact_research",
        "read_account_research_run",
        "read_contact_research_run",
    ):
        assert C6_AGENT_TOOL_AUTHORITY[dropped] == (), dropped
    # `open_icp_confirmation_gate` did not leave the role — its subject changed. `@2` presents the
    # brand's ICP knowledge document; `@1`, whose subject was a draft `icp_spec` row this lane
    # never writes, stays registered and frozen for replay with no role behind it.
    assert c6_roles_for_tool("open_icp_confirmation_gate@2") == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("open_icp_confirmation_gate@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["open_design_leg"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["finish_design_leg"] == (AgentRole.DESIGN,)
    design_grants = {
        name: roles for name, roles in C6_AGENT_TOOL_AUTHORITY.items() if name.startswith("design_")
    }
    assert len(design_grants) == 54
    # The Brand Ad Assets lane is MACHINE-INVOKED, on exactly the terms `synthesize_entity_prose`
    # and `synthesize_value_narrative` already established below: its onboarding job's worker
    # calls these through the design toolbelt (actor="agent"), and no model surface plans a
    # harvest, distils a card, or decides to spend N image generations. So they are registered
    # and audited — the complete-write-surface property holds — but granted to nobody. Granting
    # them would be a reviewed design-profile version bump, which is a decision this lane does
    # not get to make on its own.
    AD_ASSETS_LANE = {
        "design_ingest_ad_assets",
        "design_record_ad_creatives",
        "design_publish_ad_dna_card",
        "design_link_ad_pregenerated_assets",
    }
    assert set(design_grants) >= AD_ASSETS_LANE
    assert all(design_grants[name] == () for name in AD_ASSETS_LANE)
    # Clone-fidelity F4.3 / ruling R-F1: the second ungranted design write, and for a different
    # reason from the ad-assets lane's. That lane is machine-invoked and merely unplanned by any
    # model; this one is HUMAN-ONLY by ruling — clearing a published ABM page's robots meta is an
    # explicit act of the person, so no role may hold the tool that can do it.
    HUMAN_ONLY_DESIGN = {"design_set_web_noindex"}
    assert set(design_grants) >= HUMAN_ONLY_DESIGN
    assert all(design_grants[name] == () for name in HUMAN_ONLY_DESIGN)
    assert all(
        roles == (AgentRole.DESIGN,)
        for name, roles in design_grants.items()
        if name not in AD_ASSETS_LANE | HUMAN_ONLY_DESIGN
    )
    assert C6_AGENT_TOOL_AUTHORITY["create_thread"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["rename_thread"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["rename_project"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["set_thread_pinned"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["archive_thread"] == ()
    # Lane E E1 adds `synthesize_entity_prose`, machine-invoked only: the fleet step offers a
    # finalized job to it, and no model surface may reach for it.
    assert C6_AGENT_TOOL_AUTHORITY["synthesize_entity_prose"] == ()
    # Lane E E3, same reasoning one slice on: an agent that could position on demand could spend N
    # completions on an account the research engine never finished.
    assert C6_AGENT_TOOL_AUTHORITY["synthesize_value_narrative"] == ()
    # ARV2 onboarding O4 §4.5: the onboarding synthesis agent is the only spender of the governed
    # evidence call — one deep-reasoning search per persona role, and only when the flag is on.
    assert C6_AGENT_TOOL_AUTHORITY["exa_search_evidence"] == (AgentRole.ONBOARDING_SYNTHESIS,)
    assert c6_roles_for_tool("exa_search_evidence@1") == (AgentRole.ONBOARDING_SYNTHESIS,)
    # The combined inventory retains both exact-subject human gates, FI-2's selected-Account
    # launch, and S4/S5's company/product readers. Machine-only confirmation remains withheld.
    # (The total is asserted once above — 114 after the part-iii merge.)
    assert C6_AGENT_TOOL_AUTHORITY["open_icp_confirmation_gate"] == (AgentRole.HEAD_OF_ABM,)
    # ARV2 onboarding O6: the S4-E/S5-F Client-KB and Product-KB readers, and the single-product
    # gate, are ungranted at EVERY version now. The exact-address rules that used to admit one safe
    # version of each were deleted with the grants, so `@1` and `@2` are both `()` — which is what
    # these assertions check, because a resurrected exact-address rule would otherwise re-grant a
    # tool the profile does not pin and only the registry's composition check would notice.
    for dropped in (
        "list_client_knowledge",
        "inspect_client_claim",
        "list_product_knowledge",
        "inspect_product_claim",
        "open_product_selection_gate",
    ):
        assert C6_AGENT_TOOL_AUTHORITY[dropped] == (), dropped
    assert c6_roles_for_tool("list_client_knowledge@1") == ()
    assert c6_roles_for_tool("list_client_knowledge@2") == ()
    assert c6_roles_for_tool("inspect_client_claim@1") == ()
    assert c6_roles_for_tool("inspect_client_claim@2") == ()
    assert c6_roles_for_tool("list_product_knowledge@1") == ()
    assert c6_roles_for_tool("inspect_product_claim@1") == ()
    assert c6_roles_for_tool("open_product_selection_gate@1") == ()
    assert C6_AGENT_TOOL_AUTHORITY["confirm_project_product"] == ()
    # `inspect_statement_history` survives O6 and `inspect_readiness_history` does not: the first
    # reads what the human said in this conversation, which the new lane still records; the second
    # reads a readiness decision the new lane never makes.
    assert C6_AGENT_TOOL_AUTHORITY["inspect_statement_history"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["inspect_readiness_history"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["draft_account_research_directive"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["confirm_account_research_directive"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["approve_contact_research_selection"] == ()
    assert C6_AGENT_TOOL_AUTHORITY["launch_account_deep"] == ()
    # Every version of each dropped old-lane tool, not just the one v43 pinned: an exact-address
    # rule that granted one version would put the tool back on a model surface.
    for address in (
        "launch_account_research@1",
        "launch_selected_account_research@1",
        "launch_contact_research@1",
        "read_account_research_run@1",
        "read_contact_research_run@1",
    ):
        assert c6_roles_for_tool(address) == (), address
    assert C6_AGENT_TOOL_AUTHORITY["compose_contact_content_handoff"] == (
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    )

    for descriptor in registry.all_descriptors():
        roles = c6_roles_for_tool(descriptor.address)
        if roles:
            assert descriptor.recipe_safe, f"{descriptor.address} cannot enter an agent plan"
            assert descriptor.replay.policy is not ReplayPolicy.UNCERTIFIED
            assert descriptor.effect_class is not ToolEffectClass.STEERING


def test_human_steering_and_replay_blocked_tools_are_structurally_absent() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.address: item for item in registry.all_descriptors()}

    assert all(not C6_AGENT_TOOL_AUTHORITY[name] for name in _HUMAN_ONLY_STEERING)
    assert all(
        descriptors[f"{name}@1"].effect_class is ToolEffectClass.STEERING
        for name in _HUMAN_ONLY_STEERING
    )

    assert all(not c6_roles_for_tool(address) for address in _REPLAY_BLOCKED)
    assert all(
        descriptors[address].replay.policy is ReplayPolicy.UNCERTIFIED
        for address in _REPLAY_BLOCKED
    )
    assert not c6_roles_for_tool("research_account_gaps@2")
    assert descriptors["research_account_gaps@2"].recipe_safe


def test_c65_proposal_and_ingestion_certifications_are_live_and_admitted() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.name: item for item in registry.descriptors()}

    for name, replay_policy in _C65_CERTIFIED.items():
        assert C6_AGENT_TOOL_AUTHORITY[name]
        assert descriptors[name].replay.policy is replay_policy
        assert descriptors[name].recipe_safe

    assert c6_roles_for_tool("propose_field@1") == ()
    assert c6_roles_for_tool("propose_field@2") == (AgentRole.HEAD_OF_ABM,)


def test_c1_goal_judge_has_one_explicit_production_construction_owner() -> None:
    assert coverage_evaluator_owner() == "c1.engine.goal_judge"

    root = Path(__file__).resolve().parents[2]
    constructions = [
        path.relative_to(root)
        for source_root in ("platform", "subsystems")
        for path in (root / source_root).rglob("*.py")
        if "GoalJudge(" in path.read_text(encoding="utf-8")
    ]

    assert constructions == [Path("platform/api/clue_api/coverage_tools.py")]
