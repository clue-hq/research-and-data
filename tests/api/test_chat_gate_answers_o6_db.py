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
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SET_SELECTION,
    gate_answer_for_turn,
    icp_artifact_gate_id,
    insert_gate,
    product_set_selection_gate_id,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_spine import (
    confirm_project_product_set,
    create_product,
    get_project,
    list_project_product_sets,
)
from tests.api.test_icp_artifact_gate_db import icp_body, seed_document
from tests.api.test_lane_d4_gate_response_route_db import (
    USER_ID,
    _app,
    _client,
    _seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
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


# --- the ICP confirmation gate over a knowledge document (T4) ----------------------------------
#
# The `@2` gate's subject is a `brand_knowledge_document`, not a draft `icp_spec` row, so the
# route revalidates the document against the immutable snapshot and — on approval — mints the
# `confirmed` version of that same path in the same transaction as the answer. The old `icp_spec`
# path (a snapshot with no `subject_kind`) is untouched and stays covered by its own suite.


async def _seed_icp_document(
    conn: Any,
    seeded: Any,
    *,
    status: str = "proposed",
    confirmed_for_project_id: str | None = None,
    product_ids: list[str] | None = None,
) -> Any:
    project = await get_project(conn, seeded.project_id)
    assert project is not None
    seeded.brand_id = project.brand_id
    artifacts = DurableAgentArtifactStore(
        storage=seeded.storage,
        conn_factory=conn_session_factory(conn),
    )
    document_id, artifact_key, artifact_sha256 = await seed_document(
        conn,
        artifacts=artifacts,
        workspace_id=seeded.workspace_id,
        brand_id=project.brand_id,
        path="audience/icp-clinics.md",
        kind="icp-definition",
        version=1,
        status=status,
        body=icp_body(
            key="clinics",
            status=status,
            product_ids=product_ids or [],
            project_id=confirmed_for_project_id,
        ),
    )
    return _Icp(
        document_id=document_id,
        artifact_key=artifact_key,
        artifact_sha256=artifact_sha256,
        brand_id=project.brand_id,
    )


class _Icp:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _present_icp(conn: Any, seeded: Any, icp: Any, *, digest: str | None = None) -> Any:
    subject_ref = f"brand-knowledge-document:{icp.document_id}:v1"
    expected = digest or icp.artifact_sha256
    gate_id = icp_artifact_gate_id(
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        subject_ref=subject_ref,
        expected_subject_sha256=expected,
    )
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.presenting_turn_id,
        kind=KIND_ICP_CONFIRMATION,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=expected,
        subject_snapshot={
            "subject_kind": "brand_knowledge_document",
            "document_id": str(icp.document_id),
            "brand_id": icp.brand_id,
            "path": "audience/icp-clinics.md",
            "icp_key": "clinics",
            "version": 1,
            "status": "proposed",
            "artifact_key": icp.artifact_key,
            "artifact_sha256": expected,
            "product_ids": [],
            "title": "Independent multi-site clinic groups",
        },
        max_spend_cents=None,
        currency=None,
        addressee_user_id=USER_ID,
    )
    return row


async def _answer_icp(
    client: httpx.AsyncClient,
    seeded: Any,
    *,
    gate: Any,
    key: str,
    decision: str = "approved",
    revision_request: str | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "gate_id": str(gate.gate_id),
        "decision": decision,
        "expected_subject_sha256": gate.expected_subject_sha256,
    }
    if revision_request is not None:
        payload["revision_request"] = revision_request
    return await client.post(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        json={"gate_response": payload},
        headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": key},
    )


async def _documents(conn: Any, seeded: Any) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT document_id, version, status, artifact_key, artifact_sha256, "
                " supersedes_document_id, produced_by_turn_id, project_id, "
                " derived_from_document_id "
                "FROM brand_knowledge_document WHERE workspace_id = :ws "
                " AND path = 'audience/icp-clinics.md' ORDER BY version"
            ),
            {"ws": seeded.workspace_id},
        )
    ).mappings()
    return [dict(row) for row in rows.all()]


async def _pins(conn: Any, seeded: Any) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT pin_seq, document_id, icp_key, artifact_key, artifact_sha256, "
                " product_selection_version, pinned_by_user_id, brand_id "
                "FROM project_icp_pin WHERE workspace_id = :ws AND project_id = :project "
                "ORDER BY pin_seq"
            ),
            {"ws": seeded.workspace_id, "project": seeded.project_id},
        )
    ).mappings()
    return [dict(row) for row in rows.all()]


async def _artifacts(conn: Any, seeded: Any) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM artifact WHERE workspace_id = :ws"),
                {"ws": seeded.workspace_id},
            )
        ).scalar_one()
    )


def test_approving_an_icp_document_mints_its_confirmed_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-ok", label="o6icpok")
            products = await _seed_products(conn, seeded)
            icp = await _seed_icp_document(conn, seeded)
            confirmed_set = await confirm_project_product_set(
                conn,
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_id,
                product_ids=[products[0]],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert confirmed_set is not None
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-ok")
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])

            answer = await gate_answer_for_turn(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert answer is not None and answer.decision == "approved"

            rows = await _documents(conn, seeded)
            assert [(row["version"], row["status"]) for row in rows] == [
                (1, "superseded"),
                (2, "confirmed"),
            ]
            minted = rows[1]
            assert minted["supersedes_document_id"] == icp.document_id
            # The answering turn's `agent_turn` row does not exist yet (the engine creates it when
            # the turn runs), so the confirming human rides the front matter, not this column.
            assert minted["produced_by_turn_id"] is None

            body = await seeded.storage.get(str(minted["artifact_key"]))
            front, _rest = parse_front_matter(body.decode())
            assert front["status"] == "confirmed"
            assert front["confirmed_by"] == USER_ID
            assert front["confirmed_for_project_id"] == seeded.project_id
            assert front["product_selection_version"] == 1
            assert isinstance(front["confirmed_at"], str)

            # Founder rulings 2026-09-10: the same approval pins the minted version for this
            # project, in the same transaction. The pin — not the front matter — is what every
            # later read and every launch resolves the project's ICP from.
            pins = await _pins(conn, seeded)
            assert [row["pin_seq"] for row in pins] == [1]
            assert pins[0]["document_id"] == minted["document_id"]
            assert pins[0]["icp_key"] == "clinics"
            assert pins[0]["brand_id"] == seeded.brand_id
            assert pins[0]["artifact_key"] == minted["artifact_key"]
            assert pins[0]["artifact_sha256"] == minted["artifact_sha256"]
            assert pins[0]["product_selection_version"] == 1
            assert pins[0]["pinned_by_user_id"] == USER_ID

    run_async(scenario())


def test_approving_a_project_local_icp_keeps_its_scope_and_its_lineage(tmp_path: Path) -> None:
    """A project's own ICP variant is confirmed in its own scope, beside the brand's document.

    Three things are load-bearing and all three are read back from rows: the minted version carries
    the variant's ``project_id`` and the ``derived_from_document_id`` back to the brand document it
    was cut from; its version is the next one *in that scope* (2, not 4 — the brand's v3 at the same
    path is a different document's history); and the brand row is neither retired nor versioned over
    by a confirmation that was never about it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-loc", label="o6icploc")
            project = await get_project(conn, seeded.project_id)
            assert project is not None
            seeded.brand_id = project.brand_id
            artifacts = DurableAgentArtifactStore(
                storage=seeded.storage,
                conn_factory=conn_session_factory(conn),
            )
            brand_document_id, _brand_key, _brand_sha = await seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-clinics.md",
                kind="icp-definition",
                version=3,
                status="proposed",
                body=icp_body(key="clinics", status="proposed", product_ids=[]),
            )
            document_id, artifact_key, artifact_sha256 = await seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-clinics.md",
                kind="icp-definition",
                version=1,
                status="proposed",
                body=icp_body(
                    key="clinics",
                    status="proposed",
                    product_ids=[],
                    title="Independent multi-site clinic groups",
                ),
                project_id=seeded.project_id,
                derived_from_document_id=brand_document_id,
            )
            icp = _Icp(
                document_id=document_id,
                artifact_key=artifact_key,
                artifact_sha256=artifact_sha256,
                brand_id=project.brand_id,
            )
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-loc")
            assert response.status_code == 202, response.text

            rows = await _documents(conn, seeded)
            assert [(row["version"], row["status"], row["project_id"]) for row in rows] == [
                (1, "superseded", seeded.project_id),
                (2, "confirmed", seeded.project_id),
                (3, "proposed", None),
            ]
            minted = rows[1]
            assert minted["supersedes_document_id"] == document_id
            assert minted["derived_from_document_id"] == brand_document_id

            pins = await _pins(conn, seeded)
            assert [row["document_id"] for row in pins] == [minted["document_id"]]

    run_async(scenario())


def test_a_confirmation_with_no_product_set_omits_the_selection_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-nosel", label="o6icpnosel")
            icp = await _seed_icp_document(conn, seeded)
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-nosel")
            assert response.status_code == 202, response.text
            rows = await _documents(conn, seeded)
            body = await seeded.storage.get(str(rows[1]["artifact_key"]))
            front, _rest = parse_front_matter(body.decode())
            assert "product_selection_version" not in front
            assert front["confirmed_for_project_id"] == seeded.project_id
            pins = await _pins(conn, seeded)
            assert [row["pin_seq"] for row in pins] == [1]
            assert pins[0]["product_selection_version"] is None

    run_async(scenario())


def test_a_retried_approval_replays_and_mints_nothing_further(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-replay", label="o6icprep")
            icp = await _seed_icp_document(conn, seeded)
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                first = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-rep")
                after_first = await _artifacts(conn, seeded)
                second = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-rep")
            assert first.status_code == 202, first.text
            assert second.status_code == 202, second.text
            assert second.json()["data"]["replayed"] is True
            assert first.json()["data"]["turn_id"] == second.json()["data"]["turn_id"]
            rows = await _documents(conn, seeded)
            assert [row["version"] for row in rows] == [1, 2]
            # No orphan: the replay renders and stores nothing, so it records no artifact either.
            assert await _artifacts(conn, seeded) == after_first
            # And it pins nothing further: the pin's receipt stays the first approval's.
            assert [row["pin_seq"] for row in await _pins(conn, seeded)] == [1]

    run_async(scenario())


def test_a_document_that_moved_since_the_gate_refuses_the_approval(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-stale", label="o6icpstale")
            icp = await _seed_icp_document(conn, seeded)
            gate = await _present_icp(conn, seeded, icp)
            # Onboarding published a newer proposal at the same path after the gate was opened.
            artifacts = DurableAgentArtifactStore(
                storage=seeded.storage,
                conn_factory=conn_session_factory(conn),
            )
            await conn.execute(
                text(
                    "UPDATE brand_knowledge_document SET status = 'superseded' "
                    "WHERE document_id = :id"
                ),
                {"id": icp.document_id},
            )
            await seed_document(
                conn,
                artifacts=artifacts,
                workspace_id=seeded.workspace_id,
                brand_id=seeded.brand_id,
                path="audience/icp-clinics.md",
                kind="icp-definition",
                version=2,
                status="proposed",
                body=icp_body(
                    key="clinics",
                    status="proposed",
                    product_ids=[],
                    title="A rewritten profile",
                ),
            )
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_icp(client, seeded, gate=gate, key="k-o6-icp-stale")
            assert response.status_code == 409, response.text
            error = response.json()["error"]
            assert error["code"] == "GATE_SUBJECT_STALE"
            # The document check, not the legacy `icp_spec` scope check, is what refused.
            assert error["message"] == "the current ICP document differs from the reviewed one"
            assert (
                await conn.execute(text("SELECT count(*) FROM agent_gate_answer"))
            ).scalar_one() == 0
            rows = await _documents(conn, seeded)
            assert [row["version"] for row in rows] == [1, 2]

    run_async(scenario())


def test_revising_an_icp_document_requires_the_requested_changes(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-rev", label="o6icprev")
            icp = await _seed_icp_document(conn, seeded)
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                refused = await _answer_icp(
                    client, seeded, gate=gate, key="k-o6-icp-rev", decision="revised"
                )
                assert refused.status_code == 422, refused.text
                assert refused.json()["error"]["code"] == "GATE_REVISION_REQUEST_REQUIRED"

                accepted = await _answer_icp(
                    client,
                    seeded,
                    gate=gate,
                    key="k-o6-icp-rev-2",
                    decision="revised",
                    revision_request="Split the clinics profile by group size.",
                )
            assert accepted.status_code == 202, accepted.text
            rows = await _documents(conn, seeded)
            assert [(row["version"], row["status"]) for row in rows] == [(1, "proposed")]

    run_async(scenario())


def test_a_rejected_icp_document_writes_no_confirmation(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-o6-icp-rej", label="o6icprej")
            icp = await _seed_icp_document(conn, seeded)
            gate = await _present_icp(conn, seeded, icp)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer_icp(
                    client, seeded, gate=gate, key="k-o6-icp-rej", decision="rejected"
                )
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])
            answer = await gate_answer_for_turn(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert answer is not None and answer.decision == "rejected"
            rows = await _documents(conn, seeded)
            assert [(row["version"], row["status"]) for row in rows] == [(1, "proposed")]
            assert await _pins(conn, seeded) == []

    run_async(scenario())
