"""Lane E E2 acceptance — ``contact.overview`` synthesis over the real contact-research lane.

Same posture as the E1 suite: nothing here is a shortcut around production. A real contact
selection is materialized and approved, a real contact-research fleet is launched through
``ContactResearchFleetLauncher``, a real job is driven terminal through the R2 lifecycle, the real
``ContactResearchFleetWorkHandler`` reconciles it and offers it to the real
``ProseSynthesisStep`` → toolbelt registry → :class:`ToolInvoker` → :class:`ProseSynthesizer` →
:class:`FaithfulnessJudgeImpl`. The only doubles are the LLM gateway (a paid network call) and the
per-job research *driver* (which would otherwise run a whole agent).

Two things make this lane different from E1's, and both get their own AC:

* **the contact handler has NO suspend-on-error try.** On the account lane the step sits *after* a
  protective block it must not join; here there is no block at all, so the step's never-raises
  guarantee is the only thing between a synthesis failure and a fleet incident (AC4).
* **two governance rules ride the evidence read** — G6 (a ``sensitive`` contact claim is totally
  absent from the prompt, the span and the support row, AC2) and the identity-binding stamp (a
  non-STRONG cited input makes the overview born WEAK, and a WEAK contact claim is stored but
  never served, AC3 — in *both* toggle states, because identity protection is not verification).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_research_fleet import (
    ContactResearchFleetProjection,
    ContactResearchFleetService,
    ContactResearchFleetWorkHandler,
)
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchFleetLaunchRequest,
)
from clue_api.prose_synthesis_step import ProseSynthesisStep, prose_operation_id
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_core import (
    ClaimId,
    Completion,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Message,
    ProjectRunId,
    ResearchAvailability,
    ResearchMode,
    ResearchSectionKind,
    ResearchStatement,
    ResearchViewReadRequest,
    RunId,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
)
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchSubjectType,
)
from clue_fleet import (
    EntityResearchExecutionFence,
    FleetTaskKind,
    LeaseGeneration,
    WorkContext,
    WorkId,
    WorkResult,
    acquire_work_lease,
    begin_entity_research_job,
    claim_next_task,
    finalize_entity_research_job,
    release_work_lease,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore import (
    WorkspaceScope,
    current_values,
    insert_claim,
)
from clue_research.durable import AccountRunStatus, save_references
from clue_research.identity import stamp_reuse
from clue_research.narrative import (
    CONTACT_OVERVIEW,
    METRIC_PROSE_FAILED,
    load_prose_pack,
    read_claim_support,
)
from clue_research.profiling.fields import FACET_CAREER_HISTORY, FACET_CAUSES
from tests._run_lineage import assert_written_claims_are_attributable
from tests.api.test_contact_research_fleet_launch_r7_db import _approved_mixed_selection
from tests.profiling.conftest import conn_session_factory, rollback_conn

from .conftest import run_async
from .test_lane_e_e1_acceptance import (
    ExplodingGateway,
    ScriptedGateway,
    _compose_step,
    _event,
    _factory,
    _receipt,
)

pytestmark = pytest.mark.usefixtures("require_integration_db")

_TTL = timedelta(seconds=60)
_CONTACT_TITLE = "contact.current_title"
_CONTACT_JOB_FUNCTION = "contact.job_function"
#: A value distinctive enough that "it never reached the model" is a substring assertion which
#: cannot pass by coincidence.
_UNGOVERNED_VALUE = "Zorblatt revenue choreography"

_CONTACT_PARAGRAPHS = (
    '{"paragraphs": ["Alex Rivera is a revenue operations leader at Insight Health.", '
    '"They previously led operations at Globex."]}'
)

#: Two STRONG, professional-public contact facts — the synthesizer\'s contact ``min_facts`` floor
#: is 2, and it counts CONTACT facts only (account context is optional garnish).
_CONTACT_FACTS: tuple[tuple[str, JsonValue], ...] = (
    (_CONTACT_TITLE, "VP of Revenue Operations"),
    (FACET_CAREER_HISTORY, [{"org": "Globex", "role": "Director of Operations"}]),
)

#: The G6 canary. A *sensitive* claim on an allowlisted field: the key stays eligible, the claim
#: does not. Its value is a string no grounded paragraph could coincidentally contain, so "absent
#: from the prompt" is a substring assertion that cannot pass by luck.
_SENSITIVE_CAUSE = "the Zorblatt Reform Synod"


class RecordingGateway(ScriptedGateway):
    """The E1 scripted gateway plus the prompt payload, so G6 can be asserted where it matters.

    "The sensitive value never reached the model" is only provable against the bytes actually sent.
    Subclassed rather than added to the E1 gateway so the E1 suite stays untouched.
    """

    def __init__(self, *, prose: str = _CONTACT_PARAGRAPHS, verdict: str = "supported") -> None:
        super().__init__(prose=prose, verdict=verdict)
        self.messages: list[list[Message]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.messages.append(list(messages))
        return super().complete(model=model, messages=messages, **opts)

    @property
    def prompt_text(self) -> str:
        """Every byte of every message this gateway was ever handed."""
        return "\n".join(str(message.content) for batch in self.messages for message in batch)


# --- fixture: an approved, launched contact run with one researchable contact -------------------


@dataclass(frozen=True)
class LaneE2:
    workspace_id: str
    project_id: str
    project_run_id: Any
    account_id: EntityId
    contact_id: EntityId
    account_run_id: RunId
    job_id: UUID
    research_run_id: UUID
    fleets: ContactResearchFleetService


async def _write_contact_fact(
    conn: AsyncConnection,
    contact: EntityId,
    field_key: str,
    value: JsonValue,
    *,
    run_id: RunId,
    use_class: UseClass | None = UseClass.PROFESSIONAL_PUBLIC,
    binding: IdentityBinding | None = IdentityBinding.STRONG,
) -> ClaimId:
    """A tier-1 contact claim through the real factory + ``stamp_reuse`` path.

    ``binding``/``use_class`` may be ``None``: the 0004 governance CHECK requires them only for
    ``contact.facet.*``, so a plain ``contact.*`` claim with neither is representable, insertable
    and *servable* — which is exactly the hole the binding stamp and G6's fail-closed arm exist to
    close. The factory requires both, so the ``None`` is applied afterwards.
    """
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=Confidence(1.0),
            run_id=run_id,
            research_mode=ResearchMode.CONTACT_PROFILING,
            identity_binding=binding or IdentityBinding.STRONG,
            use_class=use_class or UseClass.PROFESSIONAL_PUBLIC,
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=WORKSPACE_ID,
    ).model_copy(update={"identity_binding": binding, "use_class": use_class})
    return await insert_claim(conn, claim)


async def _write_account_fact(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    value: JsonValue,
    *,
    run_id: RunId,
) -> ClaimId:
    return await insert_claim(
        conn,
        stamp_reuse(
            account_claim(
                entity_id=account,
                field_key=field_key,
                value_json=value,
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://insight-health.example/about",
                evidence_span=f"evidence for {field_key}",
            ),
            workspace_id=WORKSPACE_ID,
        ),
    )


async def _seed_contact_run(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    suffix: str,
    facts: tuple[tuple[str, JsonValue], ...] = _CONTACT_FACTS,
    sensitive_cause: bool = False,
    no_use_class: bool = False,
    unbound: bool = False,
) -> LaneE2:
    """Approve + launch a real contact-research run, and give its contact something to say."""
    await load_prose_pack(conn)
    (
        seed,
        _initial,
        selection,
        _approval,
        _op,
        approved_at,
        _other,
    ) = await _approved_mixed_selection(conn, tmp_path, suffix=suffix)
    account_run_id = seed.account_run_id
    for field_key, value in facts:
        await _write_contact_fact(conn, seed.contact_id, field_key, value, run_id=account_run_id)
    if sensitive_cause:
        # A merge-winning SENSITIVE claim on an allowlisted field. G6 is claim-level, so the field
        # stays eligible while this particular claim must vanish completely.
        await _write_contact_fact(
            conn,
            seed.contact_id,
            FACET_CAUSES,
            [{"cause": _SENSITIVE_CAUSE, "context": "named in a public member directory"}],
            run_id=account_run_id,
            use_class=UseClass.SENSITIVE,
        )
    # Both governance holes live on a *plain* ``contact.*`` field: the 0004 CHECK
    # (``claim_contact_field_requires_governance``) demands a binding and a use-class only for
    # ``contact.facet.*``, so a bare professional fact can legally be born with neither — and the
    # merge serves it either way. That is precisely what the two rules have to catch.
    if no_use_class:
        await _write_contact_fact(
            conn,
            seed.contact_id,
            _CONTACT_JOB_FUNCTION,
            _UNGOVERNED_VALUE,
            run_id=account_run_id,
            use_class=None,
        )
    if unbound:
        await _write_contact_fact(
            conn,
            seed.contact_id,
            _CONTACT_JOB_FUNCTION,
            _UNGOVERNED_VALUE,
            run_id=account_run_id,
            binding=None,
        )
    # Employer context: optional garnish that must reach the support row when it exists.
    await _write_account_fact(
        conn, seed.account_id, "core.account_name", "Insight Health", run_id=account_run_id
    )
    await _write_account_fact(
        conn,
        seed.account_id,
        "core.company_about",
        "Insight Health runs neurosurgical care pathways.",
        run_id=account_run_id,
    )
    # The C7 contact view admits a contact only through its account run's reference index.
    await save_references(
        conn,
        account_run_id,
        references_index={"contacts": [str(seed.contact_id)]},
        cost_cents=Decimal(0),
        status=AccountRunStatus.DONE,
    )

    launched = await ContactResearchFleetLauncher(conn_factory=conn_session_factory(conn)).launch(
        ContactResearchFleetLaunchRequest(
            workspace_id=WORKSPACE_ID,
            selection_id=UUID(str(selection.selection_id)),
            selection_sha256=selection.selection_sha256,
            approved_budget_cap_cents=Decimal("12.00"),
            expected_estimated_cost_cents=Decimal("12.00"),
            concurrency_limit=2,
        ),
        actor="human:lane-e2",
        source_action_ref=f"turn:lane-e2-launch:{suffix}",
        source_operation_id=uuid4(),
        confirmed_at=approved_at + timedelta(seconds=1),
    )
    job = next(
        item for item in launched.jobs if item.contact_entity_id == UUID(str(seed.contact_id))
    )
    return LaneE2(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        project_run_id=seed.project_run_id,
        account_id=seed.account_id,
        contact_id=seed.contact_id,
        account_run_id=account_run_id,
        job_id=job.job_id,
        research_run_id=launched.research_run_id,
        fleets=ContactResearchFleetService(conn_factory=_factory(conn)),
    )


async def _drive_terminal(
    conn: AsyncConnection,
    fixture: LaneE2,
    *,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
) -> str:
    """Drive this contact job terminal through the REAL R2 lifecycle; return the receipt ref."""
    job_id = fixture.job_id
    worker_id = f"worker:{job_id}"
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(conn, work_id=WorkId(job_id), worker_id=worker_id, ttl=_TTL)
    assert lease is not None
    fence = EntityResearchExecutionFence(
        task_id=task.task_id,
        worker_id=worker_id,
        lease_generation=lease.generation,
        task_attempt=1,
    )
    begin = await begin_entity_research_job(conn, job_id, fence=fence)
    assert begin.admitted
    terminal = await finalize_entity_research_job(
        conn,
        job_id,
        fence=fence,
        receipt=_receipt(
            job_id=job_id,
            subject_type=ResearchSubjectType.CONTACT,
            target_entity_id=UUID(str(fixture.contact_id)),
            current_state_sha256=begin.job.current_state_sha256,
            outcome=outcome,
        ),
    )
    assert terminal.state is ResearchJobState.TERMINAL
    await release_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        generation=LeaseGeneration(lease.generation),
    )
    assert terminal.finalization_receipt_ref is not None
    return terminal.finalization_receipt_ref


@dataclass
class _FinalizingContactDriver:
    """Stands in for the per-job contact research agent, but drives the REAL R2 finalization — so
    the handler sees exactly the finalized-this-cycle ``WorkResult`` production produces."""

    conn: AsyncConnection
    fixture: LaneE2
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED

    async def handle(self, context: WorkContext) -> WorkResult:
        receipt_ref = await _drive_terminal(self.conn, self.fixture, outcome=self.outcome)
        return WorkResult(
            outcome=self.outcome.value,
            references={
                "job_id": str(self.fixture.job_id),
                "finalization_receipt_ref": receipt_ref,
            },
            task_finalized=True,
        )


def _work_context(job_id: UUID) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(job_id),
        worker_id="worker:lane-e2",
        lease_generation=cast(Any, 1),
        payload={"job_id": str(job_id)},
        stop_requested=cast(Any, _event()),
        lease_lost=cast(Any, _event()),
    )


async def _run_through_the_handler(
    conn: AsyncConnection,
    fixture: LaneE2,
    step: ProseSynthesisStep | None,
    *,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
) -> WorkResult:
    handler = ContactResearchFleetWorkHandler(
        inner=cast(Any, _FinalizingContactDriver(conn=conn, fixture=fixture, outcome=outcome)),
        fleets=fixture.fleets,
        prose_step=step,
    )
    return await handler.handle(_work_context(fixture.job_id))


# --- readers -----------------------------------------------------------------------------------


async def _live_overviews(conn: AsyncConnection, fixture: LaneE2) -> list[Any]:
    rows = (
        await conn.execute(
            text(
                "SELECT id, verification_status, value_json, identity_binding, use_class, "
                "evidence_span FROM claim WHERE entity_id=:entity AND field_key=:field "
                "AND superseded_by IS NULL ORDER BY collected_at"
            ),
            {"entity": UUID(str(fixture.contact_id)), "field": CONTACT_OVERVIEW},
        )
    ).mappings()
    return list(rows)


async def _served_overview(conn: AsyncConnection, fixture: LaneE2) -> Any:
    merged = await current_values(
        conn,
        [fixture.contact_id],
        (CONTACT_OVERVIEW,),
        scope=WorkspaceScope.for_workspace(fixture.workspace_id),
    )
    return merged.get((fixture.contact_id, CONTACT_OVERVIEW))


async def _summary_section(conn: AsyncConnection, fixture: LaneE2) -> Any:
    """The SUMMARY section of the live C7 *contact* research view — the surface a human reads."""
    view = await ProductionResearchViewComposer(conn_factory=conn_session_factory(conn)).compose(
        ResearchViewReadRequest(
            workspace_id=fixture.workspace_id,
            project_id=fixture.project_id,
            project_run_id=fixture.project_run_id,
            subject_entity_id=fixture.contact_id,
            subject_entity_type=EntityType.CONTACT,
            product_id=PRODUCT_ID,
        )
    )
    return next(section for section in view.sections if section.kind is ResearchSectionKind.SUMMARY)


def _machine_ctx(conn: AsyncConnection, fixture: LaneE2) -> Any:
    from clue_toolbelt import ToolContext

    return ToolContext(
        workspace_id=fixture.workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=cast(Any, prose_operation_id(fixture.job_id, CONTACT_OVERVIEW)),
    )


# --- AC1: a completed contact job produces one verified, served overview -----------------------


def test_a_completed_contact_job_produces_one_verified_served_overview(tmp_path: Path) -> None:
    """The whole E2 path in one test: real handler → real step → governed tool → synthesizer →
    judge, ending at the two readers that matter (the canonical merge, and the C7 contact view)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac1")
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=True)
            result = await _run_through_the_handler(conn, fixture, step)
            assert result.outcome == "completed"

            rows = await _live_overviews(conn, fixture)
            assert len(rows) == 1
            row = rows[0]
            assert row["verification_status"] == VerificationStatus.VERIFIED.value
            # Every cited contact claim was STRONG, so the overview is born STRONG.
            assert row["identity_binding"] == IdentityBinding.STRONG.value
            assert row["use_class"] == UseClass.PROFESSIONAL_PUBLIC.value
            value = row["value_json"]
            assert value["research_outcome"] == "completed"
            assert value["synthesized_from_job_id"] == str(fixture.job_id)
            assert value["project_id"] is None
            assert len(value["paragraphs"]) == 2

            # The support row carries the contact facts AND the two account-context claims.
            support = await read_claim_support(conn, ClaimId(row["id"]))
            assert support is not None
            assert len(support.account_evidence_ids) >= 4
            assert support.client_knowledge_ids == ()

            served = await _served_overview(conn, fixture)
            assert served is not None
            assert served.provenance.source_tier == 4

            summary = await _summary_section(conn, fixture)
            assert summary.availability is ResearchAvailability.AVAILABLE
            statements = [item for item in summary.items if isinstance(item, ResearchStatement)]
            assert [item.field_key for item in statements] == [CONTACT_OVERVIEW]
            assert statements[0].claim_id == ClaimId(row["id"])

            # The prose claim is stamped with the contact research run, which the production
            # launcher registered in `run_lineage` as a `contact_research` run at launch.
            await assert_written_claims_are_attributable(
                conn,
                fixture.research_run_id,
                kind="contact_research",
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
            )

    run_async(scenario())


# --- AC2: G6 total absence at the acceptance tier ----------------------------------------------


def test_a_sensitive_contact_claim_never_reaches_the_prompt_span_or_support(
    tmp_path: Path,
) -> None:
    """G6 is claim-level, not key-level: ``contact.facet.causes`` stays on the evidence allowlist
    while *this* sensitive claim is totally absent — from the bytes sent to the model, from the
    stored evidence span, and from the support row. The synthesis still succeeds on what remains."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac2", sensitive_cause=True)
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=True)
            await _run_through_the_handler(conn, fixture, step)

            rows = await _live_overviews(conn, fixture)
            assert len(rows) == 1, "the remaining professional facts still synthesize"
            assert gateway.messages, "the synthesis really did call the model"
            assert _SENSITIVE_CAUSE not in gateway.prompt_text
            assert FACET_CAUSES not in gateway.prompt_text
            assert _SENSITIVE_CAUSE not in (rows[0]["evidence_span"] or "")

            support = await read_claim_support(conn, ClaimId(rows[0]["id"]))
            assert support is not None
            cited = {UUID(str(value)) for value in support.account_evidence_ids}
            sensitive_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM claim WHERE entity_id=:entity AND field_key=:field "
                        "AND superseded_by IS NULL"
                    ),
                    {"entity": UUID(str(fixture.contact_id)), "field": FACET_CAUSES},
                )
            ).scalar_one()
            assert sensitive_id not in cited

    run_async(scenario())


def test_a_contact_claim_with_no_use_class_is_excluded_fail_closed(tmp_path: Path) -> None:
    """A plain ``contact.*`` claim may be born with no use-class at all. Unclassified is not
    "safe by default" — it is excluded exactly like a sensitive one."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(
                conn, tmp_path, suffix="e2-noclass", no_use_class=True
            )
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=True)
            await _run_through_the_handler(conn, fixture, step)

            assert len(await _live_overviews(conn, fixture)) == 1
            assert _UNGOVERNED_VALUE not in gateway.prompt_text

    run_async(scenario())


# --- AC3: the identity-binding stamp -----------------------------------------------------------


def test_a_non_strong_cited_input_makes_the_overview_born_weak_and_unserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hole the stamp closes: a ``None``-bound contact claim is happily *served* by the merge,
    so it can reach the prompt. An overview citing one is born WEAK — written as an audit record,
    withheld by the merge in BOTH toggle modes (identity protection is not verification), and the
    SUMMARY section keeps its honest empty state."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac3", unbound=True)
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=True)
            await _run_through_the_handler(conn, fixture, step)

            rows = await _live_overviews(conn, fixture)
            assert len(rows) == 1, "the claim IS written — it is the serving that is withheld"
            assert rows[0]["identity_binding"] == IdentityBinding.WEAK.value
            # A WEAK contact claim can never be promoted, so a supported judge verdict cannot
            # carry it to VERIFIED either.
            assert rows[0]["verification_status"] != VerificationStatus.VERIFIED.value
            assert await _served_overview(conn, fixture) is None

            # ...and it stays withheld with verification OFF. Disabled mode drops the tier-4
            # verified gate; it does not drop the binding exclusion, because identity protection
            # is not verification.
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            assert await _served_overview(conn, fixture) is None

            # NOT asserted here: the C7 SUMMARY empty state. The only representable
            # non-STRONG-yet-*served* input is a plain `contact.*` claim born with a NULL binding
            # (the 0004 CHECK demands governance columns only for `contact.facet.*`, and a WEAK
            # claim never reaches the prompt at all) — and every prose-allowlisted plain contact
            # field is routed into the contact view by `_professional_field`. Composing the view
            # over such a claim currently raises inside `ResearchStatement` ("identity_binding and
            # use_class must be supplied together") rather than dropping the undisplayable
            # statement, so the assertion would pin a pre-existing composer defect that has
            # nothing to do with prose. `current_values` above is the read the SUMMARY section is
            # built from, and AC1/AC2 do assert the live SUMMARY.

    run_async(scenario())


# --- AC4: fail-soft on a lane with no suspend-on-error try -------------------------------------


def test_a_synthesis_failure_leaves_the_contact_job_terminal_and_the_handler_normal(
    tmp_path: Path,
) -> None:
    """There is no fleet suspension path on this lane at all, so the assertion is that the handler
    returns *its own* composed result — built from the inner one, with the projection folded in —
    exactly as it would with no step composed."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac4")
            sink = InMemorySink()
            step, _ = _compose_step(
                conn,
                gateway=cast(Any, ExplodingGateway()),
                verification_enabled=True,
                sink=sink,
            )
            result = await _run_through_the_handler(conn, fixture, step)

            assert result.outcome == "completed"
            assert result.references["research_run_id"] == str(fixture.research_run_id)
            assert "contact_fleet_state" in result.references
            assert sink.counter(METRIC_PROSE_FAILED, field_key=CONTACT_OVERVIEW) == 1

            state = (
                await conn.execute(
                    text("SELECT state FROM entity_research_job WHERE job_id=:id"),
                    {"id": fixture.job_id},
                )
            ).scalar_one()
            assert state == ResearchJobState.TERMINAL.value
            assert await _live_overviews(conn, fixture) == []

    run_async(scenario())


# --- AC5: redelivery replays instead of re-synthesizing -----------------------------------------


def test_a_second_delivery_of_the_same_contact_job_replays(tmp_path: Path) -> None:
    """One job = one synthesis, on this lane too: the operation id is content-addressed over
    ``(job_id, contact.overview)``, so the invocation journal replays the stored result."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac5")
            gateway = RecordingGateway()
            step, invoker = _compose_step(
                conn, gateway=cast(Any, gateway), verification_enabled=True
            )
            await _run_through_the_handler(conn, fixture, step)
            paid_calls = len(gateway.models)

            replayed = await invoker.invoke(
                "synthesize_entity_prose",
                {"job_id": str(fixture.job_id), "field_key": CONTACT_OVERVIEW},
                _machine_ctx(conn, fixture),
            )
            assert replayed.replayed is True
            assert len(gateway.models) == paid_calls
            assert len(await _live_overviews(conn, fixture)) == 1

    run_async(scenario())


# --- AC6: non-synthesizable contact outcomes are inert ------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [ResearchFinalizationOutcome.CANCELLED, ResearchFinalizationOutcome.EXHAUSTED],
)
def test_a_non_synthesizable_contact_outcome_produces_no_prose(
    tmp_path: Path, outcome: ResearchFinalizationOutcome
) -> None:
    """Prose over a broken pass would be a confident summary of nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix=f"e2-ac6-{outcome.value}")
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=True)
            await _run_through_the_handler(conn, fixture, step, outcome=outcome)
            assert await _live_overviews(conn, fixture) == []
            assert gateway.models == []  # not even a refused spend reached the model

    run_async(scenario())


# --- AC7: both toggle states --------------------------------------------------------------------


def test_with_verification_disabled_the_overview_is_unverified_yet_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No judge exists, so the claim keeps its born status — and the disabled-mode effective merge
    policy (never an explicit one) is what serves it. The STRONG binding still has to hold."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac7")
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            gateway = RecordingGateway()
            step, _ = _compose_step(conn, gateway=cast(Any, gateway), verification_enabled=False)
            await _run_through_the_handler(conn, fixture, step)

            rows = await _live_overviews(conn, fixture)
            assert len(rows) == 1
            assert rows[0]["verification_status"] == VerificationStatus.UNVERIFIED.value
            assert rows[0]["identity_binding"] == IdentityBinding.STRONG.value
            assert len(gateway.models) == 1  # one completion only: the judge never ran

            served = await _served_overview(conn, fixture)
            assert served is not None
            assert served.value_json["research_outcome"] == "completed"

            # ...and the enabled-mode read withholds the very same unverified tier-4 claim.
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            assert await _served_overview(conn, fixture) is None

    run_async(scenario())


# --- AC8: the handler-without-step pin ----------------------------------------------------------


def test_the_contact_handler_without_a_prose_step_is_unchanged(tmp_path: Path) -> None:
    """Every pre-Lane-E contact composition must keep behaving exactly as it did."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_contact_run(conn, tmp_path, suffix="e2-ac8")
            result = await _run_through_the_handler(conn, fixture, None)

            assert result.outcome == "completed"
            assert result.references["research_run_id"] == str(fixture.research_run_id)
            assert "contact_fleet_state" in result.references
            assert await _live_overviews(conn, fixture) == []
            projection = await fixture.fleets.project(fixture.research_run_id)
            assert isinstance(projection, ContactResearchFleetProjection)
            summary = next(item for item in projection.jobs if item.job_id == fixture.job_id)
            assert summary.finalization_outcome is ResearchFinalizationOutcome.COMPLETED

    run_async(scenario())
