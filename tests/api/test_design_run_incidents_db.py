"""Final review #2 (design 2026-10-31 §5.1): a design agent's model refusal opens the design
provider's incident. The scene/site/web agents' calls land as turn receipts, not ledger rows, so
the run's own collected calls are what record it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from clue_api.design_leg_wiring import record_design_run_incidents
from clue_spend.incidents import open_incidents
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _call(status: str, at: datetime, failure: dict | None = None) -> dict:
    return {
        "run_id": str(uuid4()),
        "status": status,
        "completed_at": at.isoformat(),
        "provider_failure": failure,
    }


REFUSED = {
    "kind": "refusal",
    "reason": "credits_exhausted",
    "message": "Insufficient credits",
    "provider": "openrouter_design",
}


def _record(model_calls: list[dict]):
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            await record_design_run_incidents(
                {"model_calls": model_calls}, workspace_id="ws_design", conn_factory=same
            )
            return await open_incidents(conn, providers=["openrouter_design"])

    return run_async(scenario())


def test_a_refused_design_model_call_opens_the_design_incident() -> None:
    (incident,) = _record([_call("failed", NOW, REFUSED)])
    assert (incident.reason, incident.kind) == ("credits_exhausted", "refusal")


def test_a_later_answered_call_closes_it_and_an_earlier_one_does_not() -> None:
    assert _record([_call("completed", NOW), _call("failed", NOW + timedelta(seconds=5), REFUSED)])
    assert (
        _record([_call("failed", NOW, REFUSED), _call("completed", NOW + timedelta(seconds=5))])
        == ()
    )


def test_a_run_with_no_model_calls_records_nothing() -> None:
    assert _record([]) == ()


def test_a_design_receipt_carries_the_failure_code_the_threshold_counts() -> None:
    from clue_api.design_leg_wiring import receipts_from_design_run

    call = {
        "run_id": str(uuid4()),
        "sequence": 1,
        "requested_model": "m",
        "status": "failed",
        "error_code": "rate_limit_error",
        "started_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
        "provider_failure": {
            "kind": "failure",
            "reason": "rate_limited",
            "message": "slow down",
            "provider": "openrouter_design",
        },
    }
    (receipt,) = receipts_from_design_run(
        {"model_calls": [call]}, turn_id=uuid4(), workspace_id="ws_design"
    )
    assert receipt.error_code == "provider_failed:openrouter_design:rate_limited"
