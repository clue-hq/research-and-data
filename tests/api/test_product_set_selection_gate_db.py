"""The product_set_selection answer trigger (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3).

Reuses the lane-D4 seed (a real workspace, project, thread, human turn and submission) so the
answer's foreign keys are real; presents a product-set gate and drives the trigger's rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from clue_api.agent_gate import (
    KIND_PRODUCT_SET_SELECTION,
    insert_gate,
    insert_gate_answer,
    product_set_selection_gate_id,
)
from clue_api.turn_action import derive_turn_action_ref
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

DIGEST = "c" * 64
CANDIDATES = [
    {
        "product_id": "prd_aura",
        "name": "Aura AI Scribe",
        "short_description": "…",
        "aliases": [],
        "status": "active",
    },
    {
        "product_id": "prd_triage",
        "name": "Phone Triage AI Agent",
        "short_description": "…",
        "aliases": [],
        "status": "active",
    },
]


@pytest.fixture
def require_gate_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_gate_db")


async def _present_set_gate(conn: Any, seeded: Any) -> Any:
    subject_ref = "client-product-catalog:11111111-1111-4111-8111-111111111111:v1"
    gate_id = product_set_selection_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        subject_ref=subject_ref,
        expected_subject_sha256=DIGEST,
    )
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        kind=KIND_PRODUCT_SET_SELECTION,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=DIGEST,
        subject_snapshot={"products": CANDIDATES, "omitted_count": 0},
        max_spend_cents=None,
        currency=None,
        addressee_user_id=USER_ID,
    )
    return row


async def _answer(conn: Any, seeded: Any, gate: Any, decision: str, payload: dict[str, Any] | None):
    return await insert_gate_answer(
        conn,
        gate_id=gate.gate_id,
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        action_ref=derive_turn_action_ref(seeded.turn_id),
        decision=decision,
        expected_subject_sha256=gate.expected_subject_sha256,
        decision_payload=payload,
        answered_by_user_id=USER_ID,
    )


def test_an_approval_names_a_non_empty_subset_of_the_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o1-set-ok", label="set-ok")
            gate = await _present_set_gate(conn, seeded)
            answer = await _answer(
                conn, seeded, gate, "approved", {"selected_option_refs": ["prd_triage", "prd_aura"]}
            )
            assert answer.decision == "approved"
            assert answer.decision_payload == {"selected_option_refs": ["prd_triage", "prd_aura"]}
            assert answer.selected_option_ref is None

    run_async(scenario())


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        ({}, "empty"),
        ({"selected_option_refs": []}, "no-entries"),
        ({"selected_option_refs": ["prd_aura", "prd_aura"]}, "repeat"),
        ({"selected_option_refs": ["prd_aura", "prd_stranger"]}, "non-member"),
        ({"selected_option_refs": ["prd_aura"], "revision_request": "x"}, "extra-key"),
    ],
)
def test_the_trigger_refuses_every_bad_approval(tmp_path: Path, payload: dict, label: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(
                conn, tmp_path, workspace_id=f"ws-o1-set-{label}", label=f"set-{label}"
            )
            gate = await _present_set_gate(conn, seeded)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _answer(conn, seeded, gate, "approved", payload)

    run_async(scenario())


def test_a_rejection_carries_no_payload(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o1-set-rej", label="set-rej")
            gate = await _present_set_gate(conn, seeded)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _answer(
                        conn, seeded, gate, "rejected", {"selected_option_refs": ["prd_aura"]}
                    )
            answer = await _answer(conn, seeded, gate, "rejected", None)
            assert answer.decision == "rejected"

    run_async(scenario())
