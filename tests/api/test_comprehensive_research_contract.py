"""Slice-A freeze of the comprehensive account/contact research contracts.

Authority: ``docs/FI-comprehensive-account-contact-research-contract.md`` §3.1 (the fixed
21-field account profile and its static provider ownership) and §7.1 (the 15-field contact
profile split 6 Sumble-structured / 9 Exa-Deep).
"""

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
    CONTACT_DEEP_FIELDS,
    CONTACT_STRUCTURED_FIELDS,
)
from clue_api.research_directive_tools import (
    DraftAccountResearchDirectiveInputV4,
    DraftAccountResearchDirectiveInputV5,
)
from clue_core import (
    Entity,
    EntityId,
    EntityScope,
    EntityType,
    ICPCreatedFrom,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchEffortPolicy,
    ResearchMode,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    new_entity_id,
)
from clue_research.claimstore import get_field
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
)
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS, PROSE_CONTACT_FIELDS
from clue_research.resolvers.sumble import SUMBLE_SOURCE_KEYS, sumble_action_supports_field
from clue_research.sources import plan_sources, seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_PERMITTED_ACCOUNT_SOURCES = {
    "exa_deep",
    "sumble_organizations",
    "sumble_jobs",
    "sumble_tech_stack",
}

#: The §3.1 rows that own at least one acquisition source — everything the launcher must be able to
#: plan. Derived from the contract map, never retyped.
_ACQUISITION_FIELDS = tuple(
    field for field in COMPREHENSIVE_ACCOUNT_FIELDS if COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field]
)


def test_the_21_field_account_contract_is_frozen_verbatim() -> None:
    assert COMPREHENSIVE_ACCOUNT_FIELDS == PROSE_ACCOUNT_FIELDS
    assert len(COMPREHENSIVE_ACCOUNT_FIELDS) == 21
    assert COMPREHENSIVE_ACCOUNT_FIELDS[0] == "core.account_name"
    assert COMPREHENSIVE_ACCOUNT_FIELDS[20] == "account.resonance.buying_culture"


def test_every_account_field_has_static_ownership_within_the_permitted_set() -> None:
    assert set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == set(COMPREHENSIVE_ACCOUNT_FIELDS)
    for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items():
        assert set(sources) <= _PERMITTED_ACCOUNT_SOURCES, field
    # §3.1 spot checks:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.primary_tech_stack"] == ("sumble_tech_stack",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.hiring_velocity_eng"] == ("sumble_jobs",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.operational_pain"] == ("exa_deep",)
    # Derive-only fields own no acquisition source:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.employee_range"] == ()
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.revenue_band"] == ()


def test_the_static_ownership_table_is_pinned_row_for_row() -> None:
    """Carry-forward 3a — the whole §3.1 table, not five spot checks.

    Every row is a founder-adjudicated ownership decision; a silent edit to any of them changes
    which provider is bought for a field, so the literal below is the contract's durable pin.
    """

    assert dict(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == {
        "core.account_name": (),
        "core.industry": ("sumble_organizations", "exa_deep"),
        "core.company_about": ("exa_deep", "sumble_organizations"),
        "core.employee_count": ("sumble_organizations",),
        "core.employee_range": (),
        "core.hq_location": ("sumble_organizations",),
        "core.annual_revenue": ("exa_deep",),
        "core.revenue_band": (),
        "core.primary_tech_stack": ("sumble_tech_stack",),
        "core.company_linkedin_url": ("sumble_organizations",),
        "account.total_funding": ("sumble_organizations", "exa_deep"),
        "account.recent_funding": ("sumble_organizations", "exa_deep"),
        "account.hiring_velocity_eng": ("sumble_jobs",),
        "account.operational_pain": ("exa_deep",),
        "account.strategic_moves": ("exa_deep",),
        "account.resonance.culture": ("exa_deep",),
        "account.resonance.employee_sentiment": ("exa_deep",),
        "account.resonance.attrition_signal": ("exa_deep",),
        "account.resonance.eng_blog_tone": ("exa_deep",),
        "account.resonance.public_frustrations": ("exa_deep",),
        "account.resonance.buying_culture": ("exa_deep",),
    }
    # The map is frozen at runtime too, not merely by convention (carry-forward 3b).
    with pytest.raises(TypeError):
        COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.industry"] = ()  # type: ignore[index]


@pytest.mark.usefixtures("require_profiling_db")
def test_every_acquisition_field_plans_a_permitted_source() -> None:
    """§3.1 ownership must reach the planner the launcher actually calls.

    ``AccountResearchFleetLauncher`` plans each confirmed field with ``plan_sources`` and then
    intersects the result with the four permitted field-sources; a field no permitted source
    *yields* leaves that intersection empty and raises ``no composed R5 source is authorized``.
    So for every §3.1 row that owns an acquisition source, the planned set must be non-empty and
    must stay inside that row's ownership — an extra permitted source would buy a provider §3.1
    never granted the field.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="permitted_four",
                    namespace="permitted_four",
                    title="The four permitted account field-sources (§2.2)",
                    source_profile=(
                        PackSourceSlot(
                            sources=tuple(
                                WeightedSource(source_key=key, weight=SourceWeight.HIGH, rank=rank)
                                for rank, key in enumerate(
                                    (
                                        "sumble_organizations",
                                        "sumble_jobs",
                                        "sumble_tech_stack",
                                        "exa_deep",
                                    ),
                                    start=1,
                                )
                            )
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id="acme",
                icp_key="comprehensive",
                created_from=ICPCreatedFrom.SYNTHESIS,
                enabled_packs=("permitted_four",),
            )
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)

            unplanned: list[str] = []
            overreaching: dict[str, set[str]] = {}
            for field in _ACQUISITION_FIELDS:
                plan = await plan_sources(
                    conn,
                    spec=spec,
                    entity=entity,
                    field=field,
                    mode=ResearchMode.ACCOUNT_PROFILING,
                    entity_scope=EntityScope.ACCOUNT,
                )
                planned = {source.source_key for source in plan.ordered_sources}
                if not planned:
                    unplanned.append(field)
                extra = planned - set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field])
                if extra:
                    overreaching[field] = extra
            assert not unplanned and not overreaching, (
                f"no permitted source yields: {unplanned}; "
                f"planned outside §3.1 ownership: {overreaching}"
            )

    run_async(_run())


@pytest.mark.usefixtures("require_profiling_db")
def test_every_dispatchable_31_owner_is_declared_in_its_fields_tier_plan() -> None:
    """Ownership must also survive the *action's* own tier-plan check.

    The composed Exa account action refuses a field whose registered ``tier_plan`` does not name
    ``exa_deep`` — a suspending integrity error, not a governed refusal — and the Sumble gap
    materializer refuses the same way for its own source key. So for every §3.1 row, each owner
    that can actually be dispatched for that field must appear in the field's tier plan. An owner
    whose pinned action cannot even request the field (Sumble Organizations for the funding,
    about-text and LinkedIn rows) is deliberately *not* declared: a tier plan states what a source
    can answer, and B6 settles those rows as honest ``source_cannot_request_field`` gaps instead.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            missing: dict[str, set[str]] = {}
            for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items():
                dispatchable = {
                    source
                    for source in sources
                    if source not in SUMBLE_SOURCE_KEYS
                    or sumble_action_supports_field(field, source)
                }
                if not dispatchable:
                    continue
                definition = await get_field(conn, field)
                assert definition is not None, field
                absent = dispatchable - set(definition.tier_plan)
                if absent:
                    missing[field] = absent
            assert not missing, f"§3.1 owners absent from the field tier plan: {missing}"

    run_async(_run())


def test_the_15_field_contact_partition_is_exact_and_disjoint() -> None:
    assert CONTACT_STRUCTURED_FIELDS + CONTACT_DEEP_FIELDS == PROSE_CONTACT_FIELDS
    assert len(CONTACT_STRUCTURED_FIELDS) == 6
    assert len(CONTACT_DEEP_FIELDS) == 9
    assert all(k.startswith("contact.facet.") for k in CONTACT_DEEP_FIELDS)
    assert not any(k.startswith("contact.facet.") for k in CONTACT_STRUCTURED_FIELDS)


def test_the_account_launcher_supports_exactly_the_four_permitted_field_sources() -> None:
    """Regression tripwire (contract §2.2): freezes current truth, so it passes on arrival.

    It fails only if someone later widens the launcher's field-source set beyond the four
    permitted providers.
    """

    from clue_api.account_research_fleet_launch import _SUPPORTED_FIELD_SOURCES

    assert frozenset(_PERMITTED_ACCOUNT_SOURCES) == _SUPPORTED_FIELD_SOURCES


def test_committee_discovery_has_exactly_one_provider_and_no_fallback() -> None:
    """Regression tripwire (contract §5.1 / annotation 9): Sumble Teams/People only.

    Freezes current truth — no red phase — and fails if a committee-discovery fallback provider
    is introduced under this key.
    """

    from clue_api.account_research_fleet_launch import PEOPLE_SOURCE_KEY

    assert PEOPLE_SOURCE_KEY == "sumble_people"


def test_no_excluded_provider_family_is_importable_from_the_entity_research_wiring() -> None:
    """Regression tripwire (contract §2.2): the deferred provider families stay out of composition.

    Freezes current truth, so it passes on arrival — no red phase. It fails if a deferred family
    (Firecrawl, Scrapling, registries, CRM, Apollo, ZoomInfo, BuiltWith, Clay) is wired into the
    entity-research provider composition.
    """

    import inspect

    import clue_api.entity_research_provider_wiring as wiring

    source = inspect.getsource(wiring)
    for banned in ("firecrawl", "apollo", "zoominfo", "builtwith", "scrapling", "clay"):
        assert banned not in source.lower(), banned


# --- B4: the deterministic comprehensive-profile compiler at directive drafting ----------------


def _directive_body(field_keys: tuple[str, ...]) -> ResearchDirectiveBody:
    """A minimal valid directive body; only ``field_keys`` varies across these cases."""

    return ResearchDirectiveBody(
        account_scope=ResearchAccountScope(
            explicit_account_ids=(EntityId(UUID("30000000-0000-0000-0000-000000000001")),)
        ),
        field_keys=field_keys,
        questions=(
            ResearchQuestion(
                question_id="operational-friction",
                text="Is there grounded account-level evidence of operational friction?",
                target_field_key="account.operational_pain",
            ),
        ),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations",),
            levels=("Director",),
            teams=("Administration",),
            personas=("champion",),
            candidate_cap=6,
        ),
        source_policy=ResearchSourcePolicy(
            # sumble_people keeps the intentional committee plan above executable — the 9dc3e693
            # draft guard refuses a committee-intent body with no committee-capable source.
            allowed_source_keys=(
                "sumble_organizations",
                "sumble_jobs",
                "exa_deep",
                "sumble_people",
            ),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=False,
            contact_reveals_allowed=False,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=8,
            budget_cap_cents=Decimal("300"),
            budget_envelope_ref="budget:comprehensive-v1",
            recursion_policy_ref="recursion:comprehensive-v1",
            freshness_policy_ref="freshness:comprehensive-v1",
        ),
    )


def _draft_input(
    *, profile: str, field_keys: tuple[str, ...]
) -> DraftAccountResearchDirectiveInputV4:
    return DraftAccountResearchDirectiveInputV4(
        project_id="project-comprehensive",
        product_id="product-comprehensive",
        icp_key="deep",
        icp_version=1,
        profile=profile,  # type: ignore[arg-type]
        directive=_directive_body(field_keys),
        user_instruction="Research these accounts comprehensively.",
        source_turn_ref="turn:comprehensive-1",
    )


def test_a_comprehensive_request_compiles_to_all_21_fields() -> None:
    """§3.3 row 1 — a full-profile command means the whole fixed profile, deterministically.

    The expansion is the tool's, not the model's: §3.2 wants mechanical contract expansion, so a
    directive drafted with no explicit field selection carries all 21 §3.1 rows in contract order.
    """

    drafted = _draft_input(profile="comprehensive", field_keys=())
    assert tuple(str(key) for key in drafted.directive.field_keys) == COMPREHENSIVE_ACCOUNT_FIELDS


def test_a_custom_request_passes_the_explicit_field_selection_through_unchanged() -> None:
    """The narrower subset stays available — but only when the human explicitly asked for it."""

    narrow = ("account.operational_pain", "account.strategic_moves")
    drafted = _draft_input(profile="custom", field_keys=narrow)
    assert tuple(str(key) for key in drafted.directive.field_keys) == narrow


def test_a_comprehensive_request_with_explicit_fields_is_refused_as_ambiguous() -> None:
    """Two conflicting statements of breadth are a request the tool must not silently resolve."""

    with pytest.raises(ValidationError, match="comprehensive"):
        _draft_input(profile="comprehensive", field_keys=("account.operational_pain",))


def test_the_v5_schema_lets_the_model_omit_field_keys_entirely() -> None:
    """The Slice B browser gate found @4 structurally unsatisfiable: its advertised schema marked
    ``directive.field_keys`` *required* while the steering skill (correctly) instructed "no field
    list" — so a schema-honouring model always supplied a list and was always refused as ambiguous
    breadth. @5's contract is the same, but the schema finally agrees with the skill: the key is
    optional, and a raw payload whose directive carries no ``field_keys`` at all — the exact shape
    the model should send — validates and expands to the full fixed profile.
    """

    schema = DraftAccountResearchDirectiveInputV5.model_json_schema()
    body_schema = schema["$defs"]["ResearchDirectiveBodyDraftInput"]
    assert "field_keys" not in body_schema["required"]
    # @4's advertised body really did demand the key — the deadlock this test exists to pin.
    v4_body = DraftAccountResearchDirectiveInputV4.model_json_schema()["$defs"][
        "ResearchDirectiveBody"
    ]
    assert "field_keys" in v4_body["required"]

    body = _directive_body(()).model_dump(mode="json")
    del body["field_keys"]
    drafted = DraftAccountResearchDirectiveInputV5.model_validate(
        {
            "project_id": "project-comprehensive",
            "product_id": "product-comprehensive",
            "icp_key": "deep",
            "icp_version": 1,
            "directive": body,
            "user_instruction": "Research these accounts comprehensively.",
            "source_turn_ref": "turn:comprehensive-1",
        }
    )
    assert tuple(str(key) for key in drafted.directive.field_keys) == COMPREHENSIVE_ACCOUNT_FIELDS


def test_the_v5_accepts_a_verbatim_full_profile_retyping() -> None:
    """A model whose steering card lists the 21 rows reliably retypes them (observed live at the
    Slice B browser gate) — and an explicit list that IS the full fixed profile is the same
    statement of breadth, not an ambiguity. It normalizes to the contract order; @4 keeps its
    frozen refusal.
    """

    shuffled = tuple(reversed(COMPREHENSIVE_ACCOUNT_FIELDS))
    drafted = DraftAccountResearchDirectiveInputV5(
        project_id="project-comprehensive",
        product_id="product-comprehensive",
        icp_key="deep",
        icp_version=1,
        directive=_directive_body(shuffled),
        user_instruction="Research these accounts comprehensively.",
        source_turn_ref="turn:comprehensive-1",
    )
    assert tuple(str(key) for key in drafted.directive.field_keys) == COMPREHENSIVE_ACCOUNT_FIELDS
    with pytest.raises(ValidationError, match="comprehensive"):
        _draft_input(profile="comprehensive", field_keys=shuffled)


def test_the_v5_ambiguity_refusal_is_unchanged() -> None:
    """@5 relaxes only the schema; comprehensive plus a narrower explicit list is still refused."""

    with pytest.raises(ValidationError, match="comprehensive"):
        DraftAccountResearchDirectiveInputV5(
            project_id="project-comprehensive",
            product_id="product-comprehensive",
            icp_key="deep",
            icp_version=1,
            profile="comprehensive",
            directive=_directive_body(("account.operational_pain",)),  # type: ignore[arg-type]
            user_instruction="Research these accounts comprehensively.",
            source_turn_ref="turn:comprehensive-1",
        )


def test_the_comprehensive_directive_tool_is_the_granted_head_of_abm_version() -> None:
    """The expansion only reaches production if the *granted* address is the new version."""

    from clue_agents import AgentRole
    from clue_api.agent_registry_wiring import C6_ACTIVE_PROFILE_VERSIONS, c6_roles_for_tool
    from clue_api.chat.composer_context import PROJECT_CONVERSATION_AGENT_PROFILE_ID

    # head-of-abm v68 dropped the directive lane (founder ruling 2026-09-29): no version is granted.
    assert c6_roles_for_tool("draft_account_research_directive@5") == ()
    assert c6_roles_for_tool("draft_account_research_directive@3") == ()
    assert c6_roles_for_tool("draft_account_research_directive@4") == ()
    # v42 was re-minted from comprehensive; its contract carried into active v43 at the R0 merge
    # and into v44 (ARV2 onboarding O6) unchanged — O6 replaced the Stage-0 surface, not the
    # account-deep directive contract, so `draft_account_research_directive@5` is still the granted
    # address and the two pins must still agree. v45 (ARV2 Track R, R4) carries it forward again:
    # that bump adds `launch_arv2_discovery@1` and nothing else, and v46 (ARV2 context and
    # authoring) adds only `author_icp_document@1` and `request_persona_synthesis@1`. v47 (the
    # project plan) adds only `write_project_document@1`, and v48 (the ARV2 reads) only
    # `read_project_accounts@1`, `read_account_research@1` and `read_discovery_run@1`. v49 adds no
    # tool at all — it re-pins the same three reads after their contracts were repaired. v55 is
    # the first version that takes tools AWAY (the three document tools, now file writes under
    # `project/`), and the directive draft is not among them, so the granted address is unmoved
    # and the two pins must still agree.
    assert C6_ACTIVE_PROFILE_VERSIONS[AgentRole.HEAD_OF_ABM] == "v82"
    assert PROJECT_CONVERSATION_AGENT_PROFILE_ID == "head-of-abm@v82"
