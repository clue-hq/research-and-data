"""O2 composition acceptance for the complete Sumble S2D -> S2B -> S2C lane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.committee_eligibility import CommitteeEligibilityService
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_launch import GatedSumbleCommitteeLauncher
from clue_api.sumble_committee_preparation import (
    SumbleCommitteePreparationError,
    SumbleCommitteePreparationInputs,
    SumbleCommitteePreparer,
)
from clue_core import (
    ExternalResearchPreparationOutcome,
    ResearchDirectiveId,
    RunId,
)
from clue_research.durable import find_committee_acquisition_operation
from clue_research.identity import get_account
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _setup
from tests.api.test_sumble_committee_eligibility_s2d import _authorization, _sources
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Inputs:
    def __init__(self, value: SumbleCommitteePreparationInputs) -> None:
        self._value = value

    async def resolve(self, **_kwargs) -> SumbleCommitteePreparationInputs:
        return self._value


def test_sumble_preparer_waits_then_returns_exact_snapshot_source_without_resubmit(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(
                conn,
                storage,
                workspace_id="ws-o2-sumble-preparer",
                strict_s2d=True,
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            eligibility = CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=PreSpendGateImpl(conn_factory=same_connection),
                sources=_sources(),
                conn_factory=same_connection,
            )
            preflight = compile_sumble_committee_preflight(
                request,
                cents_per_credit=Decimal("0.5"),
            )
            original_inputs = SumbleCommitteePreparationInputs(
                preflight=preflight,
                authorization=_authorization(request),
            )
            input_resolver = _Inputs(original_inputs)
            preparer = SumbleCommitteePreparer(
                inputs=input_resolver,
                launcher=GatedSumbleCommitteeLauncher(
                    eligibility=eligibility,
                    starter=coordinator,
                ),
                storage=storage,
                conn_factory=same_connection,
            )
            kwargs = {
                "account_entity_id": request.account_id,
                "account_run_id": RunId(request.project_run_id),
                "project_run_id": request.project_run_id,
                "workspace_id": request.workspace_id,
                "tier": "high",
            }

            mismatched_id = ResearchDirectiveId(uuid4())
            mismatched_pin = request.research_directive.model_copy(
                update={
                    "directive_id": mismatched_id,
                    "directive_ref": f"research-directive:{mismatched_id}:v1",
                    "canonical_json_sha256": "f" * 64,
                }
            )
            mismatched_request = request.model_copy(
                update={
                    "research_direction_ref": mismatched_pin.directive_ref,
                    "research_directive": mismatched_pin,
                }
            )
            input_resolver._value = SumbleCommitteePreparationInputs(
                preflight=preflight.model_copy(update={"request": mismatched_request}),
                authorization=original_inputs.authorization.model_copy(
                    update={
                        "research_direction_ref": mismatched_pin.directive_ref,
                        "research_directive": mismatched_pin,
                    }
                ),
            )
            with pytest.raises(
                SumbleCommitteePreparationError,
                match="exact directive pin",
            ):
                await preparer.prepare(**kwargs)
            assert transport.calls == []
            input_resolver._value = original_inputs

            waiting = await preparer.prepare(**kwargs)
            assert (
                waiting.preparation.outcome is ExternalResearchPreparationOutcome.WAITING_EXTERNAL
            )
            assert waiting.sources is None
            assert transport.calls == ["teams", "people_submit"]
            operation = await find_committee_acquisition_operation(
                conn,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )
            assert operation is not None
            operation_ref = f"committee-operation:{operation.operation_id}"
            assert waiting.preparation.operation_ref == operation_ref

            not_due = await preparer.prepare(**kwargs)
            assert (
                not_due.preparation.outcome is ExternalResearchPreparationOutcome.WAITING_EXTERNAL
            )
            assert not_due.preparation.operation_ref == operation_ref
            assert transport.calls == ["teams", "people_submit"]

            for _ in range(2):
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past "
                        "WHERE id=:operation_id"
                    ),
                    {
                        "operation_id": operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                prepared = await preparer.prepare(**kwargs)

            assert prepared.preparation.outcome is ExternalResearchPreparationOutcome.READY
            assert prepared.preparation.operation_ref == operation_ref
            assert len(prepared.preparation.snapshot_refs) == 2
            assert prepared.preparation.cost_receipt_ref is not None
            assert prepared.sources is not None and len(prepared.sources) == 1
            calls_at_ready = tuple(transport.calls)

            account = await get_account(conn, request.account_id)
            assert account is not None
            candidates = await prepared.sources[0].find_candidates(account, limit=10)
            assert len(candidates) == 1
            assert candidates[0].source_person_id == "1001"
            assert tuple(transport.calls) == calls_at_ready

            replay = await preparer.prepare(**kwargs)
            assert replay.preparation.outcome is ExternalResearchPreparationOutcome.READY
            assert replay.preparation.operation_ref == operation_ref
            assert tuple(transport.calls) == calls_at_ready
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM committee_acquisition_operation "
                        "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_id,
                    },
                )
            ).scalar_one() == 1

    run_async(scenario())
