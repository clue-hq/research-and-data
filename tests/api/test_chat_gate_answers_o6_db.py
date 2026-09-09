"""The set-valued gate answer route (ARV2 onboarding O6, T3).

A project targets a SET of products (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3, ruling P1), so its
gate is answered with ``selected_product_ids`` and the approval confirms the whole set in the same
transaction as the immutable answer — by calling ``clue_spine.confirm_project_product_set``
directly, not by invoking a tool. What this suite pins:

* an approval writes one answer row carrying ``selected_option_refs`` and exactly one new
  ``project_product`` version stamped with the answering gate;
* every refusal happens before a byte is written — a stale (archived) candidate, a repeated
  candidate, and a rejection that still names products;
* a second confirmed set is a new version, never an edit of the first.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from clue_api.agent_gate import (
    KIND_PRODUCT_SET_SELECTION,
    gate_answer_for_turn,
    insert_gate,
    product_set_selection_gate_id,
)
from clue_spine import create_product, get_project, list_project_product_sets
from tests.api.test_lane_d4_gate_response_route_db import (
    USER_ID,
    _app,
    _client,
    _seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SET_DIGEST = "e" * 64


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


async def _seed_products(conn: Any, seeded: Any) -> list[str]:
    project = await get_project(conn, seeded.project_id)
    assert project is not None
    ids = []
    for name in ("Aura AI Scribe", "Phone Triage AI Agent", "Retired Bundle"):
        product = await create_product(
            conn,
            brand_id=project.brand_id,
            workspace_id=seeded.workspace_id,
            name=name,
        )
        ids.append(product.product_id)
    seeded.brand_id = project.brand_id
    return ids


async def _present_set(
    conn: Any,
    seeded: Any,
    *,
    product_ids: list[str],
    archived_id: str | None = None,
    digest: str = SET_DIGEST,
) -> Any:
    subject_ref = f"brand-product-catalog:{seeded.brand_id}:{uuid4()}"
    gate_id = product_set_selection_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.presenting_turn_id,
        subject_ref=subject_ref,
        expected_subject_sha256=digest,
    )
    products: list[dict[str, Any]] = [
        {
            "product_id": product_id,
            "name": product_id,
            "short_description": "",
            "aliases": [],
            "status": "archived" if product_id == archived_id else "active",
        }
        for product_id in product_ids
    ]
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.presenting_turn_id,
        kind=KIND_PRODUCT_SET_SELECTION,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=digest,
        subject_snapshot={
            "brand_id": seeded.brand_id,
            "catalog_document_id": None,
            "catalog_version": 1,
            "products": products,
            "omitted_count": 0,
            "current_selection": None,
            "suggested_product_ids": [],
        },
        max_spend_cents=None,
        currency=None,
        addressee_user_id=USER_ID,
    )
    return row


async def _answer_set(
    client: httpx.AsyncClient,
    seeded: Any,
    *,
    gate: Any,
    key: str,
    decision: str = "approved",
    selected_product_ids: list[str] | None = None,
    amount: Decimal | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "gate_id": str(gate.gate_id),
        "decision": decision,
        "expected_subject_sha256": gate.expected_subject_sha256,
    }
    if selected_product_ids is not None:
        payload["selected_product_ids"] = selected_product_ids
    if amount is not None:
        payload["expected_estimated_cost_cents"] = str(amount)
    return await client.post(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        json={"gate_response": payload},
        headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": key},
    )


def test_an_approval_confirms_the_whole_set_in_one_transaction(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-ok", label="o6setok")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_set(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-set-ok",
                    selected_product_ids=[products[1], products[0]],
                )
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])

            answer = await gate_answer_for_turn(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert answer is not None
            assert answer.decision == "approved"
            assert answer.selected_option_ref is None
            assert answer.decision_payload == {"selected_option_refs": [products[1], products[0]]}

            sets = await list_project_product_sets(
                conn, workspace_id=seeded.workspace_id, project_id=seeded.project_id
            )
            assert len(sets) == 1
            assert sets[0].selection_version == 1
            assert set(sets[0].product_ids) == {products[0], products[1]}
            assert sets[0].gate_id == gate.gate_id
            assert sets[0].confirmed_by_user_id == USER_ID

    run_async(scenario())


def test_an_archived_candidate_cannot_be_chosen(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-arch", label="o6setarch")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products, archived_id=products[2])
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_set(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-set-arch",
                    selected_product_ids=[products[0], products[2]],
                )
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "GATE_PRODUCT_STALE"
            assert (
                await conn.execute(text("SELECT count(*) FROM agent_gate_answer"))
            ).scalar_one() == 0

    run_async(scenario())


def test_a_repeated_candidate_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-dup", label="o6setdup")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_set(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-set-dup",
                    selected_product_ids=[products[0], products[0]],
                )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "GATE_PRODUCT_DUPLICATE"

    run_async(scenario())


def test_an_approval_must_name_at_least_one_product(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-req", label="o6setreq")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_set(client, seeded, gate=gate, key="k-o6-set-req")
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "GATE_PRODUCT_REQUIRED"

    run_async(scenario())


def test_a_rejection_may_not_name_products(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-rej", label="o6setrej")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                refused = await _answer_set(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-set-rej",
                    decision="rejected",
                    selected_product_ids=[products[0]],
                )
                assert refused.status_code == 422, refused.text
                assert refused.json()["error"]["code"] == "GATE_PRODUCT_UNEXPECTED"

                accepted = await _answer_set(
                    client, seeded, gate=gate, key="k-o6-set-rej-2", decision="rejected"
                )
            assert accepted.status_code == 202, accepted.text
            turn_id = UUID(accepted.json()["data"]["turn_id"])
            answer = await gate_answer_for_turn(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert answer is not None and answer.decision_payload == {}
            sets = await list_project_product_sets(
                conn, workspace_id=seeded.workspace_id, project_id=seeded.project_id
            )
            assert sets == []

    run_async(scenario())


def test_a_second_confirmed_set_is_a_new_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-v2", label="o6setv2")
            products = await _seed_products(conn, seeded)
            first = await _present_set(conn, seeded, product_ids=products)
            second = await _present_set(conn, seeded, product_ids=products, digest="f" * 64)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                one = await _answer_set(
                    client,
                    seeded,
                    gate=first,
                    key="k-o6-set-v2-a",
                    selected_product_ids=[products[0]],
                )
                assert one.status_code == 202, one.text
                two = await _answer_set(
                    client,
                    seeded,
                    gate=second,
                    key="k-o6-set-v2-b",
                    selected_product_ids=[products[1], products[2]],
                )
            assert two.status_code == 202, two.text
            sets = await list_project_product_sets(
                conn, workspace_id=seeded.workspace_id, project_id=seeded.project_id
            )
            assert [entry.selection_version for entry in sets] == [1, 2]
            assert set(sets[1].product_ids) == {products[1], products[2]}
            assert sets[1].gate_id == second.gate_id

    run_async(scenario())


def test_the_set_gate_carries_no_spend_amount(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-set-amt", label="o6setamt")
            products = await _seed_products(conn, seeded)
            gate = await _present_set(conn, seeded, product_ids=products)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_set(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-set-amt",
                    selected_product_ids=[products[0]],
                    amount=Decimal("600"),
                )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "GATE_AMOUNT_UNEXPECTED"

    run_async(scenario())
