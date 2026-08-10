"""Lane E E3 acceptance — the value narrative, composed end to end over the real substrate.

The E1 suite's discipline, one species on: a real account-research fleet, a real job driven
terminal through ``finalize_entity_research_job``, the real toolbelt registry + :class:`ToolInvoker`
carrying the governed ``synthesize_value_narrative@1`` call, the real
:class:`~clue_research.narrative.Positioner` + :class:`FaithfulnessJudgeImpl` writing and judging
the claims, the real :class:`ContactEligibilityResolver` resolving the committee out of the durable
``account_run.references_index``, and the real ``read_client_kb_claims``-backed retriever reading a
Client Knowledge Base that was actually reverse-profiled. The only doubles are the LLM gateway (a
paid network call) and the per-job research *driver* (which would run a whole agent).

The acceptance criteria (charter §5-E3 / brief §3), in both toggle states:

1. a completed job with a resolvable committee produces one VERIFIED, product-stamped
   ``account.value_narrative`` claim per persona, visible in the C7 account view's pinned
   VALUE_NARRATIVE section;
2. with the flag off the step never offers the job — no journal row, no spend, prose unaffected;
3. a committee-starved account (the production-realistic M8D shape) refuses
   ``committee_unavailable`` and renders the honest empty state, with the job terminal and the
   fleet unsuspended;
4. an unresolvable client context refuses without a failure metric;
5. re-delivery replays, and a genuinely re-run synthesis supersedes per persona;
6. both client-resolution paths — the project run's own legs, and the C4-confirmed ICP lineage
   behind a run whose legs are null;
7. an empty Client KB is per-persona coverage gaps, never silence;
8. the shared outcome gate keeps cancelled/exhausted jobs inert.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.execution_wiring import build_tool_invoker
from clue_api.narrative_wiring import build_client_knowledge_retriever
from clue_api.prose_synthesis_step import ProseSynthesisStep, prose_operation_id
from clue_api.prose_synthesis_tools import ProseSynthesisServices
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.value_narrative_tools import (
    METRIC_COMMITTEE_UNAVAILABLE,
    SynthesizeValueNarrativeTool,
    ValueNarrativeServices,
)
from clue_config import DEFAULT_STAGE0_POLICY, Settings
from clue_core import (
    AccountStatus,
    Claim,
    ClaimId,
    Completion,
    EntityId,
    EntityType,
    ExtractionMethod,
    ICPCreatedFrom,
    IdentityBinding,
    Message,
    Persona,
    ProjectRunId,
    ReadinessGate,
    ResearchAvailability,
    ResearchMode,
    ResearchSectionKind,
    ResearchStatement,
    ResearchViewReadRequest,
    RunId,
    UseClass,
    VerificationStatus,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_core.entity_research import ResearchFinalizationOutcome
from clue_fleet import WorkContext, WorkId, WorkResult
from clue_obs.otel import InMemorySink, MetricSink, get_metric_sink, set_metric_sink
from clue_research.claimstore import (
    WorkspaceScope,
    current_values,
    insert_claim,
    record_run_lineage,
)
from clue_research.durable import (
    AccountRunStatus,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.icp import create_icp_spec
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    stamp_reuse,
)
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    METRIC_NARRATIVE_COVERAGE_GAP,
    METRIC_PROSE_FAILED,
    VALUE_NARRATIVE,
    ProseSynthesizer,
    load_narrative_pack,
    load_prose_pack,
    read_claim_support,
)

#: Not re-exported from the package (it postdates the surface); imported from its own module
#: rather than editing WP-A's export list from a test.
from clue_research.narrative.positioner import METRIC_NARRATIVE_JUDGE_SKIPPED
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from clue_research.stage0 import (
    ClientInput,
    VolunteeredMaterial,
    compile_product_context,
    evaluate_readiness,
    reverse_profile,
)
from clue_research.verification import FaithfulnessJudgeImpl
from clue_spine import create_brand, create_product, create_project
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_workspace
from tests.profiling.conftest import conn_session_factory, rollback_conn, seed_packs
from tests.toolbelt.conftest import InMemoryStore

from .conftest import run_async
from .test_lane_e_e1_acceptance import (
    ExplodingGateway,
    _envelope,
    _factory,
    _finalize,
    _FinalizingDriver,
    _MemoryStorage,
    _write_fact,
)

pytestmark = pytest.mark.usefixtures("require_integration_db")

_ICP_KEY = "primary"
_ARGUMENT = "Acme's picking backlog is exactly what the platform removes, and the EU expansion "
_JUDGE_MODEL_MARKER = "claude-3.5-sonnet"

#: The three account fields ``DEFAULT_FIELD_RELEVANCE`` maps the four personas onto, plus the core
#: identity facts. Every persona therefore clears ``min_account_evidence`` on its own evidence.
_FACTS: tuple[tuple[str, JsonValue], ...] = (
    ("core.account_name", "Acme Robotics"),
    ("core.industry", "warehouse automation"),
    ("core.company_about", "Robotic picking and sortation for high-volume warehouses."),
    ("account.operational_pain", "manual picking cannot keep up with peak-season volume"),
    ("account.strategic_moves", "expanding to the EU"),
    ("account.resonance.culture", "engineering-led, ships small and often"),
)

#: The two personas seeded onto the committee. Two, not one, because "one narrative per persona"
#: and "each persona cites its own evidence" are both invisible with a committee of one.
_PERSONAS = (Persona.ECONOMIC_BUYER, Persona.TECHNICAL_EVALUATOR)


class LaneEGateway:
    """One gateway serving the prose synthesis, the positioning synthesis, and the judge.

    The judge is separated by model id (its own configured model), but prose and positioning share
    the *synthesis* model by design — so the single non-judge payload carries both contracts'
    keys, and each parser takes only what it asked for. That keeps the real
    :class:`FaithfulnessJudgeImpl` and both real parsers in the loop unmodified.
    """

    def __init__(self, *, verdict: str = "supported", argument: str = _ARGUMENT) -> None:
        self._verdict = verdict
        self._argument = argument
        self.models: list[str] = []

    @property
    def synthesis_calls(self) -> int:
        return len([model for model in self.models if _JUDGE_MODEL_MARKER not in model])

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.models.append(model)
        if _JUDGE_MODEL_MARKER in model:
            score = 0.95 if self._verdict == "supported" else 0.05
            text_out = (
                f'{{"verdict": "{self._verdict}", "score": {score}, "rationale": "scripted"}}'
            )
        else:
            text_out = (
                '{"paragraphs": ["Acme Robotics builds warehouse automation systems.", '
                '"It employs around 400 people."], '
                f'"argument": "{self._argument}"}}'
            )
        return Completion(
            model=model, text=text_out, cost_cents=Decimal("0.4"), finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("positioning never embeds")


@contextmanager
def _sink() -> Iterator[InMemorySink]:
    """Install a fresh process sink. The tool and the positioner resolve theirs per emit, so this
    is what makes their metrics assertable without threading a sink through ``build_toolbelt``."""
    previous: MetricSink = get_metric_sink()
    sink = InMemorySink()
    set_metric_sink(sink)
    try:
        yield sink
    finally:
        set_metric_sink(previous)


@dataclass(frozen=True)
class LaneE3:
    workspace_id: str
    project_id: str
    product_id: str
    brand_id: str
    account_id: EntityId
    client_entity_id: EntityId | None
    envelope: Any
    job_id: UUID
    research_run_id: UUID
    projection: Any
    project_run_id: ProjectRunId
    committee_contacts: tuple[EntityId, ...]
    icp_key: str
    icp_version: int


async def _committee_claim(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    field_key: str,
    value: JsonValue,
    workspace_id: str,
    product_id: str,
    run_id: RunId,
) -> Claim:
    """A STRONG, product-stamped committee claim — the membership evidence the eligibility
    resolver requires (a weak or product-mismatched one is invisible to it, by design)."""
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=workspace_id,
    ).model_copy(
        update={"product_id": product_id, "verification_status": VerificationStatus.VERIFIED}
    )
    await insert_claim(conn, claim)
    return claim


async def _seed_committee(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    account_run_id: RunId,
    workspace_id: str,
    product_id: str,
    run_id: RunId,
    personas: tuple[Persona, ...] = _PERSONAS,
) -> tuple[EntityId, ...]:
    """One contact per persona, their membership claims, and the durable ``references_index`` that
    makes them *this run's* committee. Written through the real public writers only."""
    contacts: list[EntityId] = []
    refs: list[Claim] = []
    for persona in personas:
        contact = await insert_contact_entity(
            conn,
            account_entity_id=account_id,
            full_name=f"{persona.value.title()} Person",
            linkedin_url=f"https://linkedin.com/in/{persona.value}-{uuid4().hex[:6]}",
            status=AccountStatus.ACTIVE,
        )
        contacts.append(contact)
        refs.append(
            await _committee_claim(
                conn,
                contact=contact,
                field_key=ROLE_ON_COMMITTEE,
                value={"role": persona.value, "confidence": 1.0, "plausible": True},
                workspace_id=workspace_id,
                product_id=product_id,
                run_id=run_id,
            )
        )
        refs.append(
            await _committee_claim(
                conn,
                contact=contact,
                field_key=PERSONA,
                value=persona.value,
                workspace_id=workspace_id,
                product_id=product_id,
                run_id=run_id,
            )
        )
    await save_references(
        conn,
        account_run_id,
        references_index={"committee": [str(ref.id) for ref in refs]},
        cost_cents=Decimal(0),
        status=AccountRunStatus.DONE,
    )
    return tuple(contacts)


async def _seed(
    conn: AsyncConnection,
    *,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
    committee: bool = True,
    stage0_confirmed: bool = True,
    client_kb: bool = True,
    client_on_icp: bool = True,
    finalize: bool = True,
    reuse: LaneE3 | None = None,
) -> LaneE3:
    """A workspace with a real brand/product/project, a reverse-profiled client KB, an account with
    the narrative-relevant facts, a project run pinned to a confirmed ICP, an account run carrying
    the committee references, and one finalized account research job.

    ``stage0_confirmed`` / ``client_on_icp`` are the two client-resolution paths the tool must
    cover: a Stage-0-confirmed run answers from its own legs; every other run answers from the C4
    lineage on its *pinned* ICP version. Turning both off is the honest-refusal case.

    ``stage0_confirmed`` is all-or-none by construction, not by choice: the
    ``project_run_stage0_pins_complete`` CHECK binds ``client_entity_id``/``client_kb_version``/
    ``product_id``/``product_context_version_id``/``readiness_decision_id`` together, so a run
    either carries the whole confirmed chain (and can therefore be read under a product-pinned C7
    request) or none of it.
    """
    await seed_packs(conn)
    from clue_api.composition import load_research_packs

    await load_research_packs(conn)
    await load_prose_pack(conn)
    await load_narrative_pack(conn)
    await load_committee_pack(conn)

    if reuse is not None:
        workspace_id, project_id = reuse.workspace_id, reuse.project_id
        product_id, brand_id = reuse.product_id, reuse.brand_id
        account_id, client_entity_id = reuse.account_id, reuse.client_entity_id
        fact_run_id = new_run_id()
    else:
        workspace_id = await seed_workspace(conn, f"ws_{uuid4().hex[:8]}")
        brand = await create_brand(conn, workspace_id=workspace_id, name="Lane E brand")
        brand_id = brand.brand_id
        product = await create_product(
            conn, workspace_id=workspace_id, brand_id=brand_id, name="Lane E product"
        )
        product_id = product.product_id
        project = await create_project(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            name="Lane E project",
        )
        project_id = project.project_id

        client_entity_id = None
        if client_kb:
            profiled = await reverse_profile(
                conn,
                ClientInput(
                    name="Clue HQ",
                    website="https://cluehq.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="deck",
                            label="pitch deck",
                            content="client-volunteered facts",
                            asserted_fields={
                                "client.value_prop": (
                                    "We remove manual picking backlogs with autonomous sortation."
                                ),
                                "client.product": "Warehouse automation platform",
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
                product_id=product_id,
            )
            client_entity_id = profiled.ref.client_entity_id
        else:
            # A client entity with no Knowledge Base at all: the retriever finds nothing and every
            # persona must report an honest coverage gap rather than an ungrounded argument.
            client_entity_id = await insert_account_entity(
                conn,
                canonical_name="Clue HQ (unprofiled)",
                primary_domain=f"{uuid4().hex[:8]}.example",
                status=AccountStatus.ACTIVE,
                workspace_id=workspace_id,
            )

        account_id = await insert_account_entity(
            conn,
            canonical_name="Acme Robotics",
            primary_domain=f"{uuid4().hex[:8]}.example",
            status=AccountStatus.ACTIVE,
            workspace_id=workspace_id,
        )
        fact_run_id = new_run_id()
        await record_run_lineage(
            conn,
            run_id=UUID(str(fact_run_id)),
            workspace_id=workspace_id,
            kind="enrichment",
            project_id=project_id,
        )
        for field_key, value in _FACTS:
            await _write_fact(
                conn,
                account_id,
                field_key,
                value,
                workspace_id=workspace_id,
                run_id=fact_run_id,
            )

    if reuse is not None:
        # A genuine re-run of the SAME segment: supersession keys on
        # (persona, icp_key, icp_version, product, project), so a fresh ICP key here would prove
        # coexistence rather than supersession.
        icp_key, icp_version = reuse.icp_key, reuse.icp_version
    else:
        icp = await create_icp_spec(
            conn,
            workspace_id=workspace_id,
            icp_key=f"{_ICP_KEY}-{uuid4().hex[:6]}",
            created_from=ICPCreatedFrom.SYNTHESIS,
            activate=True,
            client_entity_id=client_entity_id if client_on_icp else None,
            client_kb_version=1 if client_on_icp else None,
            product_id=product_id if client_on_icp else None,
        )
        icp_key, icp_version = icp.icp_key, icp.version
    pins: dict[str, Any] = {}
    if stage0_confirmed:
        assert client_entity_id is not None
        context = await compile_product_context(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            client_entity_id=client_entity_id,
            client_kb_version=1,
            claim_refs=(),
        )
        readiness = await evaluate_readiness(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            project_id=project_id,
            client_entity_id=client_entity_id,
            client_kb_version=1,
            icp_key=icp_key,
            icp_version=icp_version,
            product_context_version_id=context.version_id,
            gate=ReadinessGate.DISCOVERY_SPEND,
            spec=DEFAULT_STAGE0_POLICY.readiness,
            metrics={"coverage_ratio": 1.0, "verified_claims": 1, "open_policy_blocks": 0},
            created_by_actor="agent",
        )
        pins = {
            "client_entity_id": client_entity_id,
            "client_kb_version": 1,
            "product_id": product_id,
            "product_context_version_id": context.version_id,
            "readiness_decision_id": readiness.readiness_decision_id,
        }
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project_id,
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_version=icp_version,
        **pins,
    )
    account_run_id = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=account_run_id,
        project_run_id=project_run_id,
        entity_id=account_id,
        tier="top",
        status=AccountRunStatus.DONE,
    )
    contacts: tuple[EntityId, ...] = ()
    if committee:
        contacts = await _seed_committee(
            conn,
            account_id=account_id,
            account_run_id=account_run_id,
            workspace_id=workspace_id,
            product_id=product_id,
            run_id=fact_run_id,
        )

    envelope = _envelope(
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        project_run_id=UUID(str(project_run_id)),
        account_id=account_id,
    )
    await record_run_lineage(
        conn,
        run_id=envelope.lifecycle.run_id,
        workspace_id=workspace_id,
        kind="entity_research",
        project_id=project_id,
        project_run_id=UUID(str(project_run_id)),
    )
    from clue_api.account_research_fleet import (
        AccountResearchFleetPolicy,
        AccountResearchFleetService,
    )

    service = AccountResearchFleetService(conn_factory=_factory(conn))
    await service.launch(
        envelope,
        policy=AccountResearchFleetPolicy(canary_size=1),
        actor="user:lane-e3",
        source_operation_id=envelope.lifecycle.run_id,
        source_action_ref=f"agent-action:launch-account-research:{envelope.lifecycle.run_id}",
    )
    if finalize:
        await _finalize(conn, envelope, outcome=outcome)
    projection = await service.reconcile(envelope.lifecycle.run_id)
    return LaneE3(
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        brand_id=brand_id,
        account_id=account_id,
        client_entity_id=client_entity_id,
        envelope=envelope,
        job_id=envelope.jobs[0].authorization.job_id,
        research_run_id=envelope.lifecycle.run_id,
        projection=projection,
        project_run_id=project_run_id,
        committee_contacts=contacts,
        icp_key=icp_key,
        icp_version=icp_version,
    )


# --- composition: the real toolbelt + invoker + bound step -------------------------------------


def _compose(
    conn: AsyncConnection,
    *,
    gateway: Any,
    verification_enabled: bool,
    narrative_enabled: bool = True,
    sink: InMemorySink | None = None,
) -> tuple[ProseSynthesisStep, Any]:
    """``fleet_main``'s composition, verbatim in miniature: one judge under the toggle, shared by
    the prose synthesizer and the positioning services, and the narrative offer gated on the same
    flag that decides whether the services exist at all."""
    cf = conn_session_factory(conn)
    judge = (
        FaithfulnessJudgeImpl(gateway=cast(Any, gateway), conn_factory=cf)
        if verification_enabled
        else None
    )
    synthesizer = ProseSynthesizer(gateway=cast(Any, gateway), judge=judge, conn_factory=cf)
    value_narrative = (
        ValueNarrativeServices(
            gateway=cast(Any, gateway),
            judge=judge,
            retriever=build_client_knowledge_retriever(conn_factory=cf),
            conn_factory=cf,
        )
        if narrative_enabled
        else None
    )
    registry = build_toolbelt(
        storage=None,
        gateway=cast(Any, gateway),
        conn_factory=cf,
        prose_synthesis=ProseSynthesisServices(account=synthesizer, contact=synthesizer),
        value_narrative=value_narrative,
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=InMemoryStore(),
        storage=cast(Any, _MemoryStorage()),
        settings=Settings(_env_file=None),
        conn_factory=cf,
    )
    step = ProseSynthesisStep(sink=sink, conn_factory=cf, narrative_enabled=narrative_enabled)
    step.bind(invoker)
    return step, invoker


def _terminal_result(fixture: LaneE3) -> WorkResult:
    summary = next(item for item in fixture.projection.jobs if item.job_id == fixture.job_id)
    assert summary.finalization_receipt_ref is not None
    return WorkResult(
        outcome="completed",
        references={
            "job_id": str(fixture.job_id),
            "finalization_receipt_ref": summary.finalization_receipt_ref,
        },
        task_finalized=True,
    )


async def _fire(fixture: LaneE3, step: ProseSynthesisStep) -> None:
    await step.after_account_job(
        job_id=fixture.job_id,
        result=_terminal_result(fixture),
        projection=fixture.projection,
    )


def _narrative_ctx(conn: AsyncConnection, fixture: LaneE3) -> Any:
    from clue_toolbelt import ToolContext

    return ToolContext(
        workspace_id=fixture.workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=cast(Any, prose_operation_id(fixture.job_id, VALUE_NARRATIVE)),
    )


async def _live_narratives(conn: AsyncConnection, fixture: LaneE3) -> list[Any]:
    rows = (
        await conn.execute(
            text(
                "SELECT id, verification_status, value_json, product_id FROM claim "
                "WHERE entity_id=:entity AND field_key=:field AND superseded_by IS NULL "
                "ORDER BY collected_at, id"
            ),
            {"entity": UUID(str(fixture.account_id)), "field": VALUE_NARRATIVE},
        )
    ).mappings()
    return list(rows)


async def _narrative_section(conn: AsyncConnection, fixture: LaneE3) -> Any:
    """The VALUE_NARRATIVE section of the live C7 account view, under the *pinned* read (the
    request carries the project run and the product — the E0 L1 regression's production proof)."""
    view = await ProductionResearchViewComposer(conn_factory=conn_session_factory(conn)).compose(
        ResearchViewReadRequest(
            workspace_id=fixture.workspace_id,
            project_id=fixture.project_id,
            project_run_id=fixture.project_run_id,
            subject_entity_id=fixture.account_id,
            subject_entity_type=EntityType.ACCOUNT,
            product_id=fixture.product_id,
        )
    )
    return next(
        section for section in view.sections if section.kind is ResearchSectionKind.VALUE_NARRATIVE
    )


async def _served_narrative(conn: AsyncConnection, fixture: LaneE3) -> Any:
    merged = await current_values(
        conn,
        [fixture.account_id],
        (VALUE_NARRATIVE,),
        scope=WorkspaceScope.for_workspace(fixture.workspace_id),
    )
    return merged.get((fixture.account_id, VALUE_NARRATIVE))


# --- AC1: the full happy path, flag on ---------------------------------------------------------


def test_a_completed_job_produces_one_verified_narrative_per_committee_persona() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            gateway = LaneEGateway()
            step, invoker = _compose(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)

            rows = await _live_narratives(conn, fixture)
            assert len(rows) == len(_PERSONAS)
            personas = sorted(row["value_json"]["persona"] for row in rows)
            assert personas == sorted(item.value for item in _PERSONAS)
            for row in rows:
                assert row["verification_status"] == VerificationStatus.VERIFIED.value
                # The product leg is what makes the claim visible at all on the exact_required
                # route, and the project leg is the FI-2 §6.4 supersede dimension.
                assert row["product_id"] == fixture.product_id
                assert row["value_json"]["project_id"] == fixture.project_id
                assert row["value_json"]["argument"]
                support = await read_claim_support(conn, ClaimId(row["id"]))
                assert support is not None
                # Both sides grounded — the whole point of the narrative species.
                assert support.account_evidence_ids
                assert support.client_knowledge_ids

            # ...and the reader that actually matters: the pinned C7 account view.
            section = await _narrative_section(conn, fixture)
            assert section.availability is ResearchAvailability.AVAILABLE
            statements = [item for item in section.items if isinstance(item, ResearchStatement)]
            assert statements
            assert {item.field_key for item in statements} == {VALUE_NARRATIVE}

            # The typed output lists the refs by reference (replayed from the journal, so this is
            # exactly what the step's invocation stored).
            replayed = await invoker.invoke(
                SynthesizeValueNarrativeTool.name,
                {"job_id": str(fixture.job_id)},
                _narrative_ctx(conn, fixture),
            )
            assert replayed.replayed is True
            assert replayed.references["outcome"] == "written"
            assert replayed.references["committee_size"] == len(_PERSONAS)
            assert len(replayed.references["narratives"]) == len(_PERSONAS)
            assert sorted(item["persona"] for item in replayed.references["narratives"]) == sorted(
                item.value for item in _PERSONAS
            )

            await assert_written_claims_are_attributable(
                conn,
                fixture.research_run_id,
                kind="entity_research",
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
            )

    run_async(scenario())


# --- AC6b: the second client-resolution path ---------------------------------------------------


def test_a_run_with_null_client_legs_resolves_through_the_confirmed_icp_lineage() -> None:
    """Every non-Stage-0-confirmed run today carries null client legs; the C4 lineage on the run's
    *pinned* ICP version is what makes those runs positionable at all."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, stage0_confirmed=False, client_on_icp=True)
            step, _ = _compose(conn, gateway=LaneEGateway(), verification_enabled=True)
            await _fire(fixture, step)
            assert len(await _live_narratives(conn, fixture)) == len(_PERSONAS)

    run_async(scenario())


# --- AC4: an unresolvable client context refuses, and a refusal is not a failure ---------------


def test_an_unresolvable_client_context_refuses_without_a_failure_metric() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, stage0_confirmed=False, client_on_icp=False)
            gateway = LaneEGateway()
            sink = InMemorySink()
            step, _ = _compose(conn, gateway=gateway, verification_enabled=True, sink=sink)
            await _fire(fixture, step)

            assert await _live_narratives(conn, fixture) == []
            # A precondition refusal is a decision the tool is supposed to make, not an incident.
            assert sink.counter(METRIC_PROSE_FAILED, field_key=VALUE_NARRATIVE) == 0
            # The prose offer is unaffected — the two offers are independently gated.
            assert (await _served_summary(conn, fixture)) is not None

    run_async(scenario())


async def _served_summary(conn: AsyncConnection, fixture: LaneE3) -> Any:
    merged = await current_values(
        conn,
        [fixture.account_id],
        (ACCOUNT_SUMMARY,),
        scope=WorkspaceScope.for_workspace(fixture.workspace_id),
    )
    return merged.get((fixture.account_id, ACCOUNT_SUMMARY))


# --- AC2: flag off -----------------------------------------------------------------------------


def test_with_the_flag_off_the_step_never_offers_the_job() -> None:
    """A disabled deployment must write ZERO narrative journal rows — an invoker precondition
    refusal is journaled, and per-job refusal noise is not an acceptable steady state."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            gateway = LaneEGateway()
            step, invoker = _compose(
                conn, gateway=gateway, verification_enabled=True, narrative_enabled=False
            )
            await _fire(fixture, step)

            assert await _live_narratives(conn, fixture) == []
            # One prose completion + one judge call, and nothing else was ever paid for.
            assert gateway.synthesis_calls == 1
            # The prose offer is unaffected.
            assert (await _served_summary(conn, fixture)) is not None
            # Nothing was journaled under the narrative operation id: a direct invoke now runs for
            # the first time (it would report `replayed` if the step had already recorded one) and
            # the flag-off composition refuses it.
            from clue_toolbelt import PreconditionFailed

            with pytest.raises(PreconditionFailed) as refusal:
                await invoker.invoke(
                    SynthesizeValueNarrativeTool.name,
                    {"job_id": str(fixture.job_id)},
                    _narrative_ctx(conn, fixture),
                )
            assert refusal.value.reason_codes == ("value_narrative_not_composed",)

    run_async(scenario())


# --- AC3: the committee-starved production shape -----------------------------------------------


def test_a_committee_starved_account_refuses_honestly_and_never_positions() -> None:
    """The M8D-realistic case: no writer fills ``references_index``, so the committee is empty.
    ``position()`` over an empty committee is a silent no-op — this proves the tool refuses instead.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, committee=False, finalize=False)
            gateway = LaneEGateway()
            with _sink() as sink:
                step, invoker = _compose(conn, gateway=gateway, verification_enabled=True)
                handler = _handler(conn, fixture, step)
                result = await handler.handle(_work_context(fixture))

                assert result.outcome == "completed"
                assert result.outcome != "supervisor_suspended"
                assert sink.counter(METRIC_COMMITTEE_UNAVAILABLE) == 1

            assert await _live_narratives(conn, fixture) == []
            # The honest empty state, not a fabricated or suppressed section.
            section = await _narrative_section(conn, fixture)
            assert section.items == ()
            assert section.availability is not ResearchAvailability.AVAILABLE

            state = (
                await conn.execute(
                    text("SELECT state FROM entity_research_job WHERE job_id=:id"),
                    {"id": fixture.job_id},
                )
            ).scalar_one()
            assert state == "terminal"

            replayed = await invoker.invoke(
                SynthesizeValueNarrativeTool.name,
                {"job_id": str(fixture.job_id)},
                _narrative_ctx(conn, fixture),
            )
            assert replayed.references["outcome"] == "committee_unavailable"
            assert replayed.references["committee_size"] == 0
            assert replayed.references["narratives"] == []

    run_async(scenario())


def _handler(conn: AsyncConnection, fixture: LaneE3, step: ProseSynthesisStep) -> Any:
    from clue_api.account_research_fleet import (
        AccountResearchFleetService,
        AccountResearchFleetWorkHandler,
    )

    return AccountResearchFleetWorkHandler(
        inner=cast(Any, _FinalizingDriver(conn=conn, envelope=fixture.envelope)),
        fleets=AccountResearchFleetService(conn_factory=_factory(conn)),
        prose_step=step,
    )


def _work_context(fixture: LaneE3) -> WorkContext:
    import asyncio

    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(fixture.job_id),
        worker_id="worker:lane-e3",
        lease_generation=cast(Any, 1),
        payload={"job_id": str(fixture.job_id)},
        stop_requested=cast(Any, asyncio.Event()),
        lease_lost=cast(Any, asyncio.Event()),
    )


def test_a_positioning_failure_leaves_the_job_terminal_and_the_fleet_unsuspended() -> None:
    """The narrative offer inherits the step's never-raises guarantee, exactly as prose does."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, finalize=False)
            sink = InMemorySink()
            step, _ = _compose(
                conn,
                gateway=cast(Any, ExplodingGateway()),
                verification_enabled=True,
                sink=sink,
            )
            result = await _handler(conn, fixture, step).handle(_work_context(fixture))

            assert result.outcome == "completed"
            assert result.outcome != "supervisor_suspended"
            # BOTH offers failed and BOTH were counted: the narrative offer is not skipped because
            # the prose offer blew up, and vice versa.
            assert sink.counter(METRIC_PROSE_FAILED, field_key=ACCOUNT_SUMMARY) == 1
            assert sink.counter(METRIC_PROSE_FAILED, field_key=VALUE_NARRATIVE) == 1
            assert await _live_narratives(conn, fixture) == []

    run_async(scenario())


# --- AC5: replay and supersede -----------------------------------------------------------------


def test_a_second_delivery_replays_instead_of_re_positioning() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            gateway = LaneEGateway()
            step, _ = _compose(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)
            calls = gateway.synthesis_calls
            assert calls == 1 + len(_PERSONAS)  # one prose + one per persona

            await _fire(fixture, step)
            assert gateway.synthesis_calls == calls  # no second N-call spend
            assert len(await _live_narratives(conn, fixture)) == len(_PERSONAS)

    run_async(scenario())


def test_a_second_research_pass_supersedes_one_narrative_per_persona() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            first = await _seed(conn)
            step, _ = _compose(conn, gateway=LaneEGateway(), verification_enabled=True)
            await _fire(first, step)
            original = {
                row["value_json"]["persona"]: row["id"]
                for row in await _live_narratives(conn, first)
            }

            second = await _seed(conn, reuse=first)
            # The re-run must be the SAME (icp, product, project) key for supersession to apply.
            await _fire(second, step)

            rows = await _live_narratives(conn, second)
            assert len(rows) == len(_PERSONAS)
            for row in rows:
                persona = row["value_json"]["persona"]
                assert row["id"] != original[persona]
                superseded_by = (
                    await conn.execute(
                        text("SELECT superseded_by FROM claim WHERE id=:id"),
                        {"id": original[persona]},
                    )
                ).scalar_one()
                assert superseded_by == row["id"]

    run_async(scenario())


# --- AC7: an empty Client KB is a gap, not silence ---------------------------------------------


def test_an_empty_client_knowledge_base_produces_coverage_gaps_not_claims() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, client_kb=False)
            gateway = LaneEGateway()
            with _sink() as sink:
                step, invoker = _compose(conn, gateway=gateway, verification_enabled=True)
                await _fire(fixture, step)
                assert (
                    sink.counter(
                        METRIC_NARRATIVE_COVERAGE_GAP,
                        persona=Persona.ECONOMIC_BUYER.value,
                        reason="no_client_knowledge",
                    )
                    == 1
                )

            assert await _live_narratives(conn, fixture) == []
            replayed = await invoker.invoke(
                SynthesizeValueNarrativeTool.name,
                {"job_id": str(fixture.job_id)},
                _narrative_ctx(conn, fixture),
            )
            assert replayed.references["outcome"] == "no_narratives"
            assert replayed.references["narratives"] == []
            assert sorted(
                item["persona"] for item in replayed.references["coverage_gaps"]
            ) == sorted(item.value for item in _PERSONAS)
            assert {item["reason"] for item in replayed.references["coverage_gaps"]} == {
                "no_client_knowledge"
            }

    run_async(scenario())


# --- AC8: the shared outcome gate --------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [ResearchFinalizationOutcome.CANCELLED, ResearchFinalizationOutcome.EXHAUSTED],
)
def test_a_non_synthesizable_outcome_positions_nothing(
    outcome: ResearchFinalizationOutcome,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, outcome=outcome)
            gateway = LaneEGateway()
            step, _ = _compose(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)
            assert await _live_narratives(conn, fixture) == []
            assert gateway.models == []  # not even a refused spend reached the model

    run_async(scenario())


# --- AC6: both toggle states -------------------------------------------------------------------


def test_with_verification_disabled_narratives_are_unverified_yet_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            gateway = LaneEGateway()
            with _sink() as sink:
                step, _ = _compose(conn, gateway=gateway, verification_enabled=False)
                await _fire(fixture, step)
                assert (
                    sink.counter(
                        METRIC_NARRATIVE_JUDGE_SKIPPED, persona=Persona.ECONOMIC_BUYER.value
                    )
                    == 1
                )

            rows = await _live_narratives(conn, fixture)
            assert len(rows) == len(_PERSONAS)
            assert {row["verification_status"] for row in rows} == {
                VerificationStatus.UNVERIFIED.value
            }
            # No judge ran: one prose completion + one per persona, and nothing else.
            assert gateway.synthesis_calls == len(gateway.models) == 1 + len(_PERSONAS)
            # Disabled mode drops the tier-4 verified gate, so the narrative IS served...
            assert await _served_narrative(conn, fixture) is not None
            section = await _narrative_section(conn, fixture)
            assert section.availability is ResearchAvailability.AVAILABLE

            # ...and the enabled-mode read withholds the very same unverified tier-4 claims.
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            assert await _served_narrative(conn, fixture) is None

    run_async(scenario())


def test_a_judge_rejected_narrative_is_not_served() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            step, _ = _compose(
                conn,
                gateway=LaneEGateway(verdict="unsupported"),
                verification_enabled=True,
            )
            await _fire(fixture, step)

            rows = await _live_narratives(conn, fixture)
            assert len(rows) == len(_PERSONAS)
            assert {row["verification_status"] for row in rows} == {
                VerificationStatus.REJECTED.value
            }
            assert await _served_narrative(conn, fixture) is None
            section = await _narrative_section(conn, fixture)
            assert section.items == ()

    run_async(scenario())


# --- the positioning-policy cascade -------------------------------------------------------------


def test_a_workspace_positioning_policy_row_overrides_the_built_in_default() -> None:
    """First production call site of ``load_positioning_policy``: the per-invocation cascade is
    workspace override → global row → built-in default, and this proves the override is live."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            from clue_research.narrative.prompts import PROMPT_VERSION

            await conn.execute(
                text(
                    """
                    INSERT INTO positioning_policy
                        (policy_id, workspace_id, narrative_model, prompt_version,
                         min_account_evidence, min_client_chunks, retrieval_limit,
                         max_evidence_chars, field_relevance, version)
                    VALUES (:pid, :ws, :model, :pv, 1, 1, 8, 4000, '{}'::jsonb, 1)
                    """
                ),
                {
                    "pid": f"pol-{uuid4().hex[:8]}",
                    "ws": fixture.workspace_id,
                    "model": "openrouter/lane-e3-override",
                    "pv": PROMPT_VERSION,
                },
            )
            gateway = LaneEGateway()
            step, _ = _compose(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)
            assert "openrouter/lane-e3-override" in gateway.models
            assert len(await _live_narratives(conn, fixture)) == len(_PERSONAS)

    run_async(scenario())
