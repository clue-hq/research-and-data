"""FI-2 §6.3 — the Sumble account-gap tool stops being blind to freshness.

Two defects, one fix each:

(a) the eligibility ladder read only *confidence* and *conflict*, so a fact everyone agreed was
    expired ("confidently resolved" at 400 days against a 30-day TTL) was refused as if it were
    current truth. A stale, confident, conflict-free field is now an ordinary gap
    (``AccountGapReason.STALE``) and gets refreshed.
(b) an *already-answered* field raised out of the M8D provider action as an uncaught exception,
    where the R10 contract wants a *governed* refusal the agent can act on. That one refusal — the
    fresh-skip, now its own :class:`SumbleAccountGapNotEligible` — becomes
    :class:`EntityResearchGovernedRejection`. Every other preflight refusal keeps propagating: an
    authority, discovery-seal, canonical-survivor or mis-declaration failure is not something the
    agent can repair by choosing differently, so it still suspends the job. The legacy toolbelt
    path keeps its own ``PreconditionFailed`` conversion (over the whole family): a human-facing
    precondition, not an agent turn.

Species (FI-2 §6.3, "the fresh-skip applies to NEUTRAL fields"): the ladder reads the
workspace-merged current value, so "already answered" is only a correct thing to say about a
``project_neutral`` field. Every field Sumble is approved for is a structured world fact and
resolves neutral under the ratified §5.2 key rule — asserted below through the registry rather than
assumed — and the preflight enforces it, so a *declaration* change (a new Sumble field, or a
re-declared one, carrying ``project_relative``) fails loudly instead of quietly giving the skip a
meaning it was never ratified for. That refusal is exercised too.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_tools import EntityResearchGovernedRejection
from clue_api.sumble_account_gaps import (
    _SOURCE_BY_FIELD,
    SumbleAccountGapCoordinator,
    SumbleAccountGapEligibilityError,
    SumbleAccountGapNotEligible,
    SumbleAccountGapStarter,
    compile_sumble_account_gap_preflight,
)
from clue_api.sumble_entity_research_tools import SumbleAccountSemanticEnrichmentAction
from clue_api.toolbelt_wiring import (
    EnrichAccountGapsInput,
    EnrichAccountGapsTool,
    build_toolbelt,
)
from clue_core import (
    AccountGapReason,
    EntityId,
    ExtractionMethod,
    FreshnessState,
    ProjectRunId,
    ResearchMode,
    ResearchScope,
    RunId,
    account_claim,
    new_operation_id,
)
from clue_core.entity_research import (
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchSubjectType,
)
from clue_research.claimstore import (
    WorkspaceScope,
    current_value,
    field_species,
    insert_claim,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.sumble import JOBS_SOURCE_KEY
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext, invoke_tool
from tests.api.test_sumble_account_gaps_s1 import (
    _seed_selected_high_tier_account,
    _SumbleHttp,
)
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_HIRING = "account.hiring_velocity_eng"  # neutral, 30d TTL
_SHA = "0" * 64


async def _hiring_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: EntityId,
    project_run_id: ProjectRunId,
    age: timedelta,
    evidence_span: str | None = "Seven open engineering roles were listed.",
) -> None:
    """One confident, conflict-free hiring-velocity claim of a chosen age and evidence state."""

    observed = datetime.now(UTC) - age
    claim = stamp_reuse(
        account_claim(
            entity_id=account_id,
            field_key=_HIRING,
            value_json=7,
            source_tier=2,
            extraction_method=ExtractionMethod.API,
            confidence=0.95,
            run_id=RunId(project_run_id),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://insighthealth.ai/careers",
            evidence_span=evidence_span,
        ).model_copy(update={"source_key": JOBS_SOURCE_KEY}),
        workspace_id=workspace_id,
    ).model_copy(update={"observed_at": observed, "collected_at": observed})
    await insert_claim(conn, claim)


def _starter(
    conn: AsyncConnection, *, storage: FsStorage, domain: str
) -> tuple[SumbleAccountGapStarter, _SumbleHttp]:
    @asynccontextmanager
    async def same_connection() -> AsyncIterator[AsyncConnection]:
        yield conn

    http = _SumbleHttp(domain)
    coordinator = SumbleAccountGapCoordinator(
        api_key=SecretStr("fixture"),
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=same_connection,
    )
    return (
        SumbleAccountGapStarter(
            coordinator=coordinator,
            storage=storage,
            cents_per_credit=Decimal("0.5"),
            conn_factory=same_connection,
        ),
        http,
    )


def _request(account_id: EntityId, *, label: str = "fi2-63") -> GovernedResearchToolRequest:
    """One exact single-field structured request, the shape the M8D action authorizes."""

    return GovernedResearchToolRequest(
        research_run_id=uuid4(),
        job_id=uuid4(),
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=account_id,
        agent_turn_id=uuid4(),
        agent_execution_id=uuid4(),
        tool_call_id=uuid4(),
        tool_name="enrich_account",
        tool_version=1,
        tool_input_sha256=_SHA,
        field_plan_ref=f"account-field-plan:{label}",
        source_plan_ref=f"effective-source-plans:{label}",
        field_keys=(_HIRING,),
        source_keys=(JOBS_SOURCE_KEY,),
        field_source_authority=(
            FieldSourceAuthority(field_key=_HIRING, source_keys=(JOBS_SOURCE_KEY,)),
        ),
        questions=("How fast is the engineering org hiring?",),
        budget_reservation_key=f"{label}-budget",
        idempotency_key=f"{label}-idempotency",
    )


def test_fi2_63_every_sumble_approved_field_is_project_neutral() -> None:
    """The verified premise of the fresh-skip, asserted through the registry, not assumed."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            species = await field_species(
                conn, workspace_id="ws-fi2-63", field_keys=sorted(_SOURCE_BY_FIELD)
            )
            assert set(species.values()) == {ResearchScope.PROJECT_NEUTRAL}

    run_async(scenario())


def test_fi2_63_a_field_declared_project_relative_is_refused_loudly(tmp_path: Path) -> None:
    """The enforcement behind that premise: a declaration change fails, it does not drift.

    Simulated at the registry row, because that is the only reachable route — a workspace override
    cannot do it (``register_workspace_field`` takes ``client.*`` keys only and forces neutral), so
    the real-world version of this is someone editing the pack declaration or adding a new
    Sumble-approved field with the wrong species.
    """

    async def scenario() -> None:
        workspace_id = "ws-fi2-63e"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            await conn.execute(
                text(
                    "UPDATE field_definition SET research_scope='project_relative' "
                    "WHERE field_key=:field_key"
                ),
                {"field_key": _HIRING},
            )
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match=f"declared project-relative: {_HIRING}",
            ):
                await compile_sumble_account_gap_preflight(
                    workspace_id=workspace_id,
                    project_run_id=run_id,
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={_HIRING: Decimal(5)},
                    provider_credit_cap=5,
                    allow_unbounded_tech=False,
                    observation_window=f"project-run:{run_id}:fi2-63e",
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                )
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63a_a_stale_but_confident_field_is_an_eligible_gap(tmp_path: Path) -> None:
    """400 days against a 30-day TTL: confidence is not currency, and the refresh is the point."""

    async def scenario() -> None:
        workspace_id = "ws-fi2-63a"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            await _hiring_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=run_id,
                age=timedelta(days=400),
            )
            preflight = await compile_sumble_account_gap_preflight(
                workspace_id=workspace_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HIRING: Decimal(5)},
                provider_credit_cap=5,
                allow_unbounded_tech=False,
                observation_window=f"project-run:{run_id}:fi2-63a",
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )

            plan = {str(item.field_key): item for item in preflight.request.fields}
            assert plan[_HIRING].reason is AccountGapReason.STALE
            # The stale winner is the durable basis of its own refresh.
            assert len(plan[_HIRING].basis_claim_ids) == 1
            # Nothing was reserved by compiling a plan.
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63a_a_fresh_confident_field_is_still_refused(tmp_path: Path) -> None:
    """The other side of the same branch: what is current is not re-bought."""

    async def scenario() -> None:
        workspace_id = "ws-fi2-63b"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            await _hiring_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=run_id,
                age=timedelta(days=1),
            )
            with pytest.raises(SumbleAccountGapNotEligible, match="confidently resolved, fresh"):
                await compile_sumble_account_gap_preflight(
                    workspace_id=workspace_id,
                    project_run_id=run_id,
                    account_id=account_id,
                    field_expected_value_credits={_HIRING: Decimal(5)},
                    provider_credit_cap=5,
                    allow_unbounded_tech=False,
                    observation_window=f"project-run:{run_id}:fi2-63b",
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                )

    run_async(scenario())


def test_a_fresh_claim_without_an_evidence_span_is_a_gap_not_an_answer(tmp_path: Path) -> None:
    """Settlement F5: unbuyable *and* unsatisfiable is a deadlock, so the ladder must not refuse.

    Execution completeness satisfies a field only with an *evidence-backed* current value
    (``CurrentValue.evidence_backed`` — fresh, unconflicted, non-empty span), because a claim with
    no evidence span cannot be promoted. The ladder read confidence, conflict and freshness only,
    so a fresh confident winner with a NULL span was refused as "already answered" while nothing
    could ever count it as answered: a field whose whole authority is Sumble stayed outstanding
    forever and its account could never settle. Both sides now read one predicate, so the field is
    an ordinary gap — bought again, with the span-less winner as the durable basis.
    """

    async def scenario() -> None:
        workspace_id = "ws-fi2-63f"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            await _hiring_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=run_id,
                age=timedelta(days=1),
                evidence_span=None,
            )
            merged = await current_value(
                conn,
                account_id,
                _HIRING,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            # The exact deadlock precondition: fresh and confident, yet not an answer.
            assert merged is not None
            assert merged.freshness_state is FreshnessState.FRESH
            assert not merged.conflict
            assert not merged.evidence_backed

            preflight = await compile_sumble_account_gap_preflight(
                workspace_id=workspace_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HIRING: Decimal(5)},
                provider_credit_cap=5,
                allow_unbounded_tech=False,
                observation_window=f"project-run:{run_id}:fi2-63f",
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            plan = {str(item.field_key): item for item in preflight.request.fields}
            assert plan[_HIRING].reason is AccountGapReason.NO_EVIDENCE
            assert plan[_HIRING].basis_claim_ids == (merged.provenance.claim_id,)
            # Compiling a plan reserves nothing.
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63b_the_m8d_path_converts_ineligibility_into_a_governed_skip(
    tmp_path: Path,
) -> None:
    """The agent gets a repairable refusal, not an exception, and nothing was reserved."""

    async def scenario() -> None:
        workspace_id = "ws-fi2-63c"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)
            await _hiring_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=run_id,
                age=timedelta(days=1),
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            starter, http = _starter(conn, storage=storage, domain="insighthealth.ai")
            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HIRING: Decimal(5)},
                provider_credit_cap=5,
            )

            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("an ineligible request must never reserve an operation")

            with pytest.raises(EntityResearchGovernedRejection) as refusal:
                await action.execute(  # type: ignore[arg-type]
                    _request(account_id, label="fi2-63c"),
                    before_dispatch=never_dispatched,
                    settle_terminal=never_dispatched,
                )

            assert refusal.value.code == "account_gap_ineligible"
            assert "confidently resolved, fresh" in refusal.value.detail
            assert '"recoverable":true' in refusal.value.render()
            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63b_a_job_authority_loss_is_not_a_governed_skip(tmp_path: Path) -> None:
    """The §6.3(b) conversion is the fresh-skip's alone; losing job authority still suspends.

    ``compile_sumble_account_gap_preflight`` raises ``SumbleAccountGapEligibilityError`` at ~20
    sites, most of which say "this job may not spend here" (authority, discovery seal, canonical
    survivor) rather than "this field is already answered". Those were suspending before §6.3(b)
    and must stay suspending: an agent cannot repair a lost job authority by picking another
    field, and converting it would let a fenced-out job keep taking turns. Only the narrower
    ``SumbleAccountGapNotEligible`` crosses into the governed-refusal path.
    """

    async def scenario() -> None:
        workspace_id = "ws-fi2-63f"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            starter, http = _starter(conn, storage=storage, domain="insighthealth.ai")
            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HIRING: Decimal(5)},
                provider_credit_cap=5,
                # No such live R6 job: the preflight's spend-capacity proof fails.
                entity_research_job_id=uuid4(),
            )

            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("an unauthorized request must never reserve an operation")

            with pytest.raises(
                SumbleAccountGapEligibilityError, match="exact Account research job"
            ):
                await action.execute(  # type: ignore[arg-type]
                    _request(account_id),
                    before_dispatch=never_dispatched,
                    settle_terminal=never_dispatched,
                )

            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63b_a_project_relative_declaration_is_not_a_governed_skip(tmp_path: Path) -> None:
    """The species guard is a loud failure, not a turn the agent can spend its way out of.

    A Sumble field declared ``project_relative`` means the fresh-skip ladder below it is reading
    another project's answer — a mis-declaration, not a request defect. Handing the agent a
    recoverable refusal would let it keep going against a broken declaration; propagating suspends
    the job for a human.
    """

    async def scenario() -> None:
        workspace_id = "ws-fi2-63g"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            await conn.execute(
                text(
                    "UPDATE field_definition SET research_scope='project_relative' "
                    "WHERE field_key=:field_key"
                ),
                {"field_key": _HIRING},
            )
            starter, http = _starter(conn, storage=storage, domain="insighthealth.ai")
            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HIRING: Decimal(5)},
                provider_credit_cap=5,
            )

            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("a mis-declared field must never reserve an operation")

            with pytest.raises(
                SumbleAccountGapEligibilityError, match=f"declared project-relative: {_HIRING}"
            ):
                await action.execute(  # type: ignore[arg-type]
                    _request(account_id),
                    before_dispatch=never_dispatched,
                    settle_terminal=never_dispatched,
                )

            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_63b_the_legacy_toolbelt_path_keeps_its_precondition_failure(
    tmp_path: Path,
) -> None:
    """The human-facing tool contract is unchanged: a loud precondition, not a governed turn.

    ``enrich_account_gaps@1`` is in ``QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES``, so a *registry*
    invocation never reaches eligibility at all — asserted first, so the quarantine cannot quietly
    lapse. (``ReplayOnlyEntityResearchTool.invoke`` raises unconditionally and never delegates to
    the wrapped tool; an exact replay is served from the idempotency cache, above the tool, so the
    quarantine wrapper is not the replay path either.) The tool object underneath is nonetheless
    still the live implementation — what the address resolves to when the quarantine lifts, and
    what any non-registry caller holds — so ``invoke`` is exercised directly to pin its contract:
    §6.3(b) converts the fresh-skip to :class:`EntityResearchGovernedRejection` on the M8D action
    *only*, and leaves this one raising ``PreconditionFailed('sumble_account_gap_ineligible')``.
    """

    async def scenario() -> None:
        workspace_id = "ws-fi2-63d"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)
            await _hiring_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=run_id,
                age=timedelta(days=1),
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            starter, http = _starter(conn, storage=storage, domain="insighthealth.ai")
            body = {
                "project_run_id": str(run_id),
                "account_entity_id": str(account_id),
                "field_expected_value_credits": {_HIRING: "5"},
                "provider_credit_cap": 5,
                "allow_unbounded_tech": False,
            }
            ctx = ToolContext(
                workspace_id=workspace_id,
                actor="human:fi2-63d",
                conn_factory=same_connection,
                operation_id=new_operation_id(),
            )
            registry = build_toolbelt(
                storage=storage,
                gateway=None,
                conn_factory=same_connection,
                account_gap_enrichment_starter=starter,
            )
            with pytest.raises(PreconditionFailed) as quarantined:
                await invoke_tool(registry, "enrich_account_gaps", body, ctx, idempotency_ttl_s=60)
            assert quarantined.value.reason_codes == ("entity_research_agent_not_composed",)

            tool = EnrichAccountGapsTool(
                starter=starter,
                conn_factory=same_connection,
                cents_per_credit=Decimal("0.5"),
            )
            with pytest.raises(PreconditionFailed) as refused:
                await tool.invoke(EnrichAccountGapsInput.model_validate(body), ctx)
            assert refused.value.reason_codes == ("sumble_account_gap_ineligible",)
            assert "confidently resolved, fresh" in refused.value.failures[0].message
            assert http.calls == []

    run_async(scenario())
