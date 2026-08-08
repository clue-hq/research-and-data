"""FI-2 §6.3 — the Sumble account-gap tool stops being blind to freshness.

Two defects, one fix each:

(a) the eligibility ladder read only *confidence* and *conflict*, so a fact everyone agreed was
    expired ("confidently resolved" at 400 days against a 30-day TTL) was refused as if it were
    current truth. A stale, confident, conflict-free field is now an ordinary gap
    (``AccountGapReason.STALE``) and gets refreshed.
(b) an ineligible field raised :class:`SumbleAccountGapEligibilityError` straight out of the M8D
    provider action — an uncaught exception where the R10 contract wants a *governed* refusal the
    agent can act on. It is now :class:`EntityResearchGovernedRejection`. The legacy toolbelt path
    keeps its own ``PreconditionFailed`` conversion: a human-facing precondition, not an agent turn.

Species (FI-2 §6.3, "the fresh-skip applies to NEUTRAL fields"): every field Sumble is approved for
is a structured world fact and resolves ``project_neutral`` under the ratified §5.2 key rule — the
test below verifies that rather than assuming it, and the preflight now *enforces* it, so a
workspace registry override cannot silently give the fresh-skip a meaning it was never ratified for.
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
from clue_api.frontend_read.account_detail import field_species
from clue_api.sumble_account_gaps import (
    _SOURCE_BY_FIELD,
    SumbleAccountGapCoordinator,
    SumbleAccountGapEligibilityError,
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
from clue_research.claimstore import insert_claim
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
) -> None:
    """One confident, conflict-free, evidence-backed hiring-velocity claim of a chosen age."""

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
            evidence_span="Seven open engineering roles were listed.",
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


def test_fi2_63_every_sumble_approved_field_is_project_neutral(tmp_path: Path) -> None:
    """The verified premise of the fresh-skip, asserted through the registry, not assumed."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        del storage
        async with rollback_conn(seed_pack=True) as conn:
            species = await field_species(
                conn, workspace_id="ws-fi2-63", field_keys=sorted(_SOURCE_BY_FIELD)
            )
            assert set(species.values()) == {ResearchScope.PROJECT_NEUTRAL}

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
            with pytest.raises(
                SumbleAccountGapEligibilityError, match="confidently resolved, fresh"
            ):
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
            request = GovernedResearchToolRequest(
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
                field_plan_ref="account-field-plan:fi2-63c",
                source_plan_ref="effective-source-plans:fi2-63c",
                field_keys=(_HIRING,),
                source_keys=(JOBS_SOURCE_KEY,),
                field_source_authority=(
                    FieldSourceAuthority(field_key=_HIRING, source_keys=(JOBS_SOURCE_KEY,)),
                ),
                questions=("How fast is the engineering org hiring?",),
                budget_reservation_key="fi2-63c-budget",
                idempotency_key="fi2-63c-idempotency",
            )

            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("an ineligible request must never reserve an operation")

            with pytest.raises(EntityResearchGovernedRejection) as refusal:
                await action.execute(request, before_dispatch=never_dispatched)  # type: ignore[arg-type]

            assert refusal.value.code == "account_gap_ineligible"
            assert "confidently resolved, fresh" in refusal.value.detail
            assert '"recoverable":true' in refusal.value.render()
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
    lapse. The tool object itself is still the live implementation the human path would run (and
    the one an exact replay resolves), so ``invoke`` is exercised directly: §6.3(b) must convert
    ineligibility to :class:`EntityResearchGovernedRejection` on the M8D action *only*, and leave
    this one raising ``PreconditionFailed('sumble_account_gap_ineligible')``.
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
