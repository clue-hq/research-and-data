"""An unreconciled Sumble dispatch settles terminally instead of poisoning the job.

Live regression (run ``accdce64-…``, two account jobs): a drive crashed between Sumble's dispatch
and its receipt, so the next drive quarantined the dispatching snapshot and marked the operation
``spend_outcome_unknown``. The governed action treated that provider outcome as a *result-contract*
violation and raised ``EntityResearchResultIntegrityError``, which suspends the job — and because
the operation is durably terminal, every resume replayed the same unknown outcome and re-suspended
with nothing the agent could do. Unknown spend is a terminal provider outcome: settle the attempt
(its real dispatch time plus an append-only zero-cost fold, so coverage can close honestly) and
refuse the call back to the agent as the repairable governed species.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchResultIntegrityError,
    ProviderOperationObservation,
    ProviderOperationReservation,
)
from clue_api.sumble_account_gaps import (
    SumbleAccountGapCoordinator,
    SumbleAccountGapStarter,
)
from clue_api.sumble_entity_research_tools import SumbleAccountSemanticEnrichmentAction
from clue_core import EntityId, ProjectRunId
from clue_core.entity_research import (
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchSubjectType,
)
from clue_research.resolvers.sumble import JOBS_SOURCE_KEY, SumbleClient, SumbleCreditBudget
from clue_storage import FsStorage
from tests.api.test_sumble_account_gaps_s1 import (
    _seed_selected_high_tier_account,
    _SumbleHttp,
)
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_HIRING = "account.hiring_velocity_eng"
_SHA = "0" * 64


class _UnreconciledSumbleHttp(_SumbleHttp):
    """Organizations answers; the paid ``/jobs`` dispatch never reconciles into a receipt."""

    def __call__(self, url: str, **kwargs: Any) -> object:
        if url.endswith("/jobs"):
            self.calls.append({"url": url, **kwargs})
            raise TimeoutError("the Sumble jobs response never arrived")
        return super().__call__(url, **kwargs)


def _request(account_id: EntityId, *, label: str) -> GovernedResearchToolRequest:
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


def _observation(reservation: ProviderOperationReservation) -> ProviderOperationObservation:
    return ProviderOperationObservation(
        observation_id=uuid4(),
        tool_request_id=uuid4(),
        operation_ref=reservation.operation_ref,
        workspace_id=reservation.workspace_id,
        disposition=reservation.observation_disposition.value,
        created_at=datetime.now(UTC),
    )


def test_an_unreconciled_sumble_dispatch_settles_and_refuses_instead_of_suspending(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = "ws-sumble-unreconciled"
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

            http = _UnreconciledSumbleHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            starter = SumbleAccountGapStarter(
                coordinator=SumbleAccountGapCoordinator(
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    client_factory=client_factory,
                ),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
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

            settled: list[ProviderOperationReservation] = []

            async def settle_terminal(
                reservation: ProviderOperationReservation,
            ) -> ProviderOperationObservation:
                settled.append(reservation)
                return _observation(reservation)

            async def before_dispatch(
                reservation: ProviderOperationReservation,
            ) -> ProviderOperationObservation:
                return _observation(reservation)

            with pytest.raises(EntityResearchGovernedRejection) as refusal:
                await action.execute(
                    _request(account_id, label="unreconciled-1"),
                    before_dispatch=before_dispatch,
                    settle_terminal=settle_terminal,
                )

            assert refusal.value.code == "provider_spend_unreconciled"
            assert '"recoverable":true' in refusal.value.render()
            assert not isinstance(refusal.value, EntityResearchResultIntegrityError)
            # The attempt is settled, and settled with the operation's *real* dispatch time — a
            # fold over an undispatched operation is not an attempt under execution closure, so a
            # settlement without it would leave the field outstanding forever anyway.
            assert len(settled) == 1
            assert settled[0].dispatched_at is not None
            assert settled[0].field_keys == (_HIRING,)

            state, spend = (
                (
                    await conn.execute(
                        text(
                            "SELECT state, spend_outcome FROM account_gap_operation "
                            "WHERE workspace_id=:workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )
                )
                .tuples()
                .one()
            )
            assert str(state) == "spend_outcome_unknown"
            assert str(spend) == "unknown"

            # The durable operation is terminal, so a re-drive replays exactly this outcome. That
            # replay is what suspended the live jobs on every resume; it must stay governed.
            with pytest.raises(EntityResearchGovernedRejection) as replayed:
                await action.execute(
                    _request(account_id, label="unreconciled-2"),
                    before_dispatch=before_dispatch,
                    settle_terminal=settle_terminal,
                )
            assert replayed.value.code == "provider_spend_unreconciled"
            assert len(settled) == 2

    run_async(scenario())
