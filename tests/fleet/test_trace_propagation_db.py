"""Lane 3 slice 2, Task 4 (DB): enqueue stamps the carrier into payload_json; a payload with
no current span is unchanged."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.fleet.conftest import rollback_conn, run_async

from clue_core import decode_jsonb, new_project_run_id
from clue_fleet import FleetTaskKind, enqueue_task
from clue_obs.otel import collect_spans, traced_step

pytestmark = pytest.mark.usefixtures("require_fleet_db")


def _payload_for(dedup: str) -> object:
    async def scenario() -> object:
        async with rollback_conn() as conn:
            await enqueue_task(
                conn,
                kind=FleetTaskKind.AGENT_TURN,
                project_run_id=new_project_run_id(),
                dedup_key=dedup,
                payload={"turn_id": "turn-1", "workspace_id": "ws-1"},
            )
            raw = (
                await conn.execute(
                    text("SELECT payload_json FROM fleet_task WHERE dedup_key = :d"), {"d": dedup}
                )
            ).scalar_one()
            return decode_jsonb(raw)

    return run_async(scenario())


def test_enqueue_under_a_span_stamps_the_carrier() -> None:
    with collect_spans(), traced_step("api.request") as span:
        payload = _payload_for(f"trace-{uuid4().hex[:8]}")
    assert isinstance(payload, dict)
    assert payload["turn_id"] == "turn-1"
    trace_hex = f"{span.get_span_context().trace_id:032x}"
    assert str(payload["traceparent"]).startswith(f"00-{trace_hex}-")


def test_enqueue_without_a_span_leaves_the_payload_alone() -> None:
    payload = _payload_for(f"plain-{uuid4().hex[:8]}")
    assert payload == {"turn_id": "turn-1", "workspace_id": "ws-1"}
