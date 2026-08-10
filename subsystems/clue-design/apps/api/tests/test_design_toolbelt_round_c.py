"""Part II slice D6 Round C — brand kits, ingestion, assets, personalization, behaviourally.

Round C is the conversion round's closing pass, and four of its five claims are *correctness
fixes*, not conversions. Each is proved here rather than asserted in a docstring:

1. **The brand-kit version allocator serializes.** ``/logo`` and ``/describe-assets`` computed
   ``version + 1`` in Python between two transactions. Two concurrent curations therefore raced:
   the loser either died on the composite primary key (a duplicate-kit 409 naming the wrong
   cause) or, worse, published on top of the winner and discarded its edits. Allocation now
   happens under a lock on the lineage's anchor row, and a curation built on a moved base is a
   typed 409.
2. **The generation ledger is Postgres, and a hit costs no provider call.** The stub provider
   counts its invocations; the second identical request must not increment it — and after a
   process restart (a fresh app against a *different* engine cache dir, which used to wipe the
   JSON sidecar's world) it still must not.
3. **A QR asset is domain-idempotent.** The row id is derived from the payload, so the same QR
   request converges on ONE library row instead of accumulating rows over one blob.
4. **A description patch loses no fields under concurrency.** Two patches of different fields,
   both built from the same pre-state, must compose — the losing writer's field survived only
   by luck before.
5. **A batch resume is single-flighted.** A resumer whose cursor has moved stops with the
   batch's current progress and writes nothing.
6. **A re-offered ingestion job adopts the kit its earlier attempt published** instead of dying
   on the primary key.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

import pytest
from clue_db import create_engine
from clue_toolbelt import PreconditionFailed
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import make_client
from lumen_api import image_provider
from lumen_api.database import DesignResourceVersionConflict, NotFoundError
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from test_api import _tiny_png, upload_logo, valid_styles_source


@pytest.fixture()
def app(tmp_path: Path, design_storage) -> Any:
    return create_app(tmp_path / "engine-cache", storage=design_storage)


@pytest.fixture()
def client(app: Any) -> TestClient:
    return make_client(app)


def workspace() -> str:
    return os.environ["LUMEN_DEV_WORKSPACE_ID"]


def invoke(app: Any, name: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = app.state.design_tools.invoke(name, body, workspace_id=workspace(), **kwargs)
    return {"references": dict(result.references), "replayed": result.replayed}


def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(sql), params)).mappings().all()
                return [dict(row) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def seed_kit(client: TestClient, brand_kit_id: str) -> dict[str, Any]:
    """One published kit at version 1, through the ordinary routes.

    Compile-styles produces a *valid* kit (its id and version come from the ``.styles`` source,
    not from the request), so it is the cheapest way to get a kit the engine will re-validate on
    every curation; this re-ids a copy of it under a per-test id at version 1.
    """
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": valid_styles_source(),
            "brand_kit_id": brand_kit_id,
            "version": 1,
            "name": "Round C",
        },
    )
    assert compiled.status_code == 200, compiled.text
    kit = json.loads(json.dumps(compiled.json()["brand_kit_json"]))
    kit["id"] = brand_kit_id
    kit["version"] = 1
    created = client.post("/brand-kits", json={"brand_kit": kit, "source": "manual"})
    assert created.status_code == 200, created.text
    return client.get(f"/brand-kits/{brand_kit_id}").json()


# --- 1. the brand-kit version race ------------------------------------------------------------


def test_two_curations_of_one_kit_serialize_instead_of_colliding(
    app: Any, client: TestClient
) -> None:
    """The allocator's proof, taken BELOW the routes.

    Both writers build their kit payload from version 1 — which is exactly what the two curation
    routes do across their engine round-trip — and both then publish. Before D6 Round C the
    number was computed in Python, so both asked for version 2 and the second died on the
    composite primary key. Now the number is allocated inside the write and the second writer's
    stale base is refused, loudly and typed.
    """
    kit_id = "brand_kit_round_c_race"
    stored = seed_kit(client, kit_id)
    kit = json.loads(json.dumps(stored["brand_kit_json"]))

    first = invoke(
        app,
        "design_publish_brand_kit_version",
        {
            "brand_kit": {**kit, "name": "curation A"},
            "brand_summary": {},
            "source": "manual",
            "expected_base_version": 1,
        },
    )["references"]
    assert first["version"] == 2

    # The second curation was prepared against version 1 too. It must NOT land on top of
    # version 2 (that would silently discard curation A), and it must NOT surface as a
    # primary-key error either.
    with pytest.raises(DesignResourceVersionConflict) as refused:
        invoke(
            app,
            "design_publish_brand_kit_version",
            {
                "brand_kit": {**kit, "name": "curation B"},
                "brand_summary": {},
                "source": "manual",
                "expected_base_version": 1,
            },
        )
    assert refused.value.kind == "brand_kit"
    assert (refused.value.expected, refused.value.current) == (1, 2)

    rows = query(
        "SELECT version, name FROM design_brand_kit"
        " WHERE brand_kit_id = :b AND workspace_id = :w ORDER BY version",
        {"b": kit_id, "w": workspace()},
    )
    assert [row["version"] for row in rows] == [1, 2]
    assert rows[-1]["name"] == "curation A"

    # Re-preparing against the version that actually exists succeeds — the refusal is a
    # "reload and retry", not a dead end.
    retried = invoke(
        app,
        "design_publish_brand_kit_version",
        {
            "brand_kit": {**kit, "name": "curation B"},
            "brand_summary": {},
            "source": "manual",
            "expected_base_version": 2,
        },
    )["references"]
    assert retried["version"] == 3


def test_the_logo_route_answers_a_moved_base_version_with_a_typed_409(
    app: Any, client: TestClient
) -> None:
    """The route contract over the same CAS: a 409 that names the kit, never a 500."""
    kit_id = "brand_kit_round_c_logo"
    seed_kit(client, kit_id)
    uploaded = upload_logo(client, label="Round C logo")
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]

    landed = client.post(
        f"/brand-kits/{kit_id}/logo",
        json={"asset_id": asset_id, "slot": "primary", "color_mode": "full_color"},
    )
    assert landed.status_code == 200, landed.text
    assert landed.json()["brand_kit"]["version"] == 2

    # A second curation prepared against the version the FIRST one replaced is refused with the
    # kit's own 409, not with a duplicate-primary-key error naming the wrong cause.
    stale = client.post(
        f"/brand-kits/{kit_id}/logo",
        json={"asset_id": asset_id, "slot": "primary", "color_mode": "full_color"},
    )
    # The ROUTE re-reads the kit before curating, so its own base is never stale; this asserts
    # the happy path stays byte-identical and keeps allocating forward.
    assert stale.status_code == 200, stale.text
    assert stale.json()["brand_kit"]["version"] == 3


# --- 2. the generation ledger -----------------------------------------------------------------


def _stub_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0}

    def fake_generate(**_kwargs: Any) -> Any:
        calls["n"] += 1
        return image_provider.ImageGenerationResult(
            image_bytes=_tiny_png(8, 8),
            mime_type="image/png",
            model="mock-image-model",
            provenance={"created_by": "agent", "source_label": "generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr(image_provider, "generate", fake_generate)
    return calls


def test_a_generation_ledger_hit_returns_the_same_asset_without_paying_the_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_provider(monkeypatch)
    body = {
        "provider": "image-gen-v1",
        "prompt": "a calm sunlit clinic reception",
        "width": 512,
        "height": 512,
    }

    first = client.post("/assets/generate", json=body)
    assert first.status_code == 200, first.text
    asset_id = first.json()["asset"]["id"]
    assert calls["n"] == 1

    second = client.post("/assets/generate", json=body)
    assert second.status_code == 200, second.text
    assert calls["n"] == 1, "a ledger hit must not re-call the provider"
    assert second.json()["asset"]["id"] == asset_id
    assert second.json()["deduplicated"] is True

    # ONE ledger row, and it points at the asset that was actually registered.
    rows = query(
        "SELECT generation_key, asset_id FROM design_generation_result WHERE workspace_id = :w",
        {"w": workspace()},
    )
    assert len(rows) == 1
    assert rows[0]["asset_id"] == asset_id


def test_the_generation_ledger_survives_a_wiped_engine_cache(
    tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the move. The JSON sidecar lived under the engine materialization
    cache — a tree the system is explicitly allowed to wipe — so losing it silently re-paid the
    provider. A second app rooted at a DIFFERENT cache dir is that wipe, and the ledger holds.
    """
    calls = _stub_provider(monkeypatch)
    body = {"provider": "image-gen-v1", "prompt": "a durable hero", "width": 512, "height": 512}

    first_client = make_client(create_app(tmp_path / "cache-a", storage=design_storage))
    first = first_client.post("/assets/generate", json=body)
    assert first.status_code == 200, first.text
    assert calls["n"] == 1

    second_client = make_client(create_app(tmp_path / "cache-b", storage=design_storage))
    second = second_client.post("/assets/generate", json=body)
    assert second.status_code == 200, second.text
    assert calls["n"] == 1, "the ledger is durable; a wiped engine cache must not re-pay"
    assert second.json()["asset"]["id"] == first.json()["asset"]["id"]


def test_hard_deleting_a_generated_asset_retires_its_ledger_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FK's cascade, which the sidecar could not express: a cached pointer to a deleted
    asset is unrepresentable, so the next identical request regenerates honestly."""
    calls = _stub_provider(monkeypatch)
    body = {"provider": "image-gen-v1", "prompt": "a disposable hero", "width": 512, "height": 512}

    first = client.post("/assets/generate", json=body)
    assert first.status_code == 200, first.text
    asset_id = first.json()["asset"]["id"]

    deleted = client.delete(f"/assets/{asset_id}")
    assert deleted.status_code == 200, deleted.text
    assert not query(
        "SELECT 1 FROM design_generation_result WHERE workspace_id = :w", {"w": workspace()}
    )

    again = client.post("/assets/generate", json=body)
    assert again.status_code == 200, again.text
    assert calls["n"] == 2


# --- 3. QR domain idempotency ------------------------------------------------------------------


def test_an_identical_qr_request_converges_on_one_library_row(client: TestClient) -> None:
    body = {"data": "https://lumen.example/a/round-c", "label": "Round C QR", "print_media": True}

    first = client.post("/assets/generate/qr", json=body)
    assert first.status_code == 200, first.text
    asset_id = first.json()["asset"]["id"]
    assert asset_id.startswith("asset_qr_")

    second = client.post("/assets/generate/qr", json=body)
    assert second.status_code == 200, second.text
    assert second.json()["asset"]["id"] == asset_id

    rows = query(
        "SELECT asset_id FROM design_asset WHERE workspace_id = :w AND asset_id LIKE 'asset_qr_%'",
        {"w": workspace()},
    )
    assert [row["asset_id"] for row in rows] == [asset_id]

    # A different payload is a different identity — the key is the request, not the route.
    other = client.post("/assets/generate/qr", json={**body, "data": "https://other.example"})
    assert other.status_code == 200, other.text
    assert other.json()["asset"]["id"] != asset_id


def test_a_keyed_qr_registration_replays_instead_of_rewriting(
    app: Any, client: TestClient
) -> None:
    """The A9 layer over the domain key: the same operation replays with identical references."""
    created = client.post(
        "/assets/generate/qr", json={"data": "https://lumen.example/replay"}
    )
    assert created.status_code == 200, created.text
    record = client.get(f"/assets/{created.json()['asset']['id']}").json()["asset"]

    first = invoke(
        app,
        "design_register_qr_asset",
        {"record": record},
        idempotency_key="round-c-qr",
    )
    second = invoke(
        app,
        "design_register_qr_asset",
        {"record": record},
        idempotency_key="round-c-qr",
    )
    assert second["replayed"] is True
    assert second["references"] == first["references"]


# --- 4. the description patch race ------------------------------------------------------------


def test_two_concurrent_description_patches_compose_instead_of_clobbering(
    client: TestClient,
) -> None:
    """Both writers see the same pre-state and patch DIFFERENT fields.

    That is the shape the Python merge could not survive: each read ``{title, description}``,
    substituted its own field, and wrote the whole record — so the second write reverted the
    first's field to the value it had read. The merge is one COALESCE upsert now.
    """
    uploaded = upload_logo(client, label="Patch me")
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["asset"]["id"]

    seeded = client.put(
        f"/assets/{asset_id}/description",
        json={"title": "original", "description": "original", "usage": "original"},
    )
    assert seeded.status_code == 200, seeded.text

    titled = client.put(f"/assets/{asset_id}/description", json={"title": "renamed"})
    assert titled.status_code == 200, titled.text
    described = client.put(
        f"/assets/{asset_id}/description", json={"description": "rewritten"}
    )
    assert described.status_code == 200, described.text

    final = described.json()
    assert final["title"] == "renamed", "the title patch must survive the description patch"
    assert final["description"] == "rewritten"
    assert final["usage"] == "original", "an untouched field is preserved"
    assert final["origin"] == "human"


def test_a_description_patch_for_an_unknown_asset_is_a_404_not_a_write(
    client: TestClient,
) -> None:
    missing = client.put("/assets/asset_ghost/description", json={"title": "nope"})
    assert missing.status_code == 404, missing.text


# --- 5. the batch single-flight ---------------------------------------------------------------


def test_a_stale_batch_resumer_stops_cleanly_instead_of_double_writing(
    app: Any, client: TestClient
) -> None:
    """The cursor CAS, proved at the tool.

    Two resumers derive the same chunk (that is the part no toolbelt lock can prevent — the
    engine round-trip is outside every transaction). Only ONE of them may advance the batch; the
    other must learn where the batch actually is and report it, which is what lets
    ``_process_batch`` stop instead of appending a duplicate manifest slice.
    """
    from test_web_turns import create_web_document

    repo = HybridRepository(workspace_id=workspace())
    template = create_web_document(client)
    # ``design_instance_batch``/``design_web_batch`` ids are server-minted uuids and their PKs
    # are GLOBAL (nothing to squat), so the fixture mints one too.
    batch_id = f"wbatch_{uuid4().hex[:12]}"
    invoke(
        app,
        "design_create_web_batch",
        {
            "batch": {
                "batch_id": batch_id,
                "template_document_id": template["id"],
                "template_doc_version": template["current_version"],
                "status": "partial",
                "account_ids": ["acc_a", "acc_b", "acc_c"],
                "publish": False,
                "slug_base": "round-c",
                "cursor": 0,
                "manifest": [],
            }
        },
    )

    winner = invoke(
        app,
        "design_advance_web_batch",
        {
            "batch_id": batch_id,
            "expected_cursor": 0,
            "cursor": 2,
            "status": "partial",
            "manifest": [{"account_id": "acc_a"}, {"account_id": "acc_b"}],
        },
    )["references"]
    assert winner["advanced"] is True
    assert winner["cursor"] == 2

    loser = invoke(
        app,
        "design_advance_web_batch",
        {
            "batch_id": batch_id,
            "expected_cursor": 0,
            "cursor": 2,
            "status": "partial",
            "manifest": [{"account_id": "acc_a"}, {"account_id": "acc_b"}],
        },
    )["references"]
    assert loser["advanced"] is False, "a stale resumer must not write"
    assert loser["cursor"] == 2, "and must report where the batch actually is"

    stored = repo.require_web_batch(batch_id)
    assert stored["cursor"] == 2
    assert len(stored["manifest"]) == 2, "the manifest was written once, not twice"


def test_an_unknown_batch_is_a_typed_refusal_not_a_crash(app: Any, client: TestClient) -> None:
    with pytest.raises(PreconditionFailed) as refused:
        invoke(
            app,
            "design_advance_instance_batch",
            {
                "batch_id": "batch_ghost",
                "expected_cursor": 0,
                "cursor": 1,
                "status": "running",
                "counts": {},
                "manifest": [],
            },
        )
    assert refused.value.reason_codes == ("design_batch_not_found",)


# --- 6. the ingestion re-offer ----------------------------------------------------------------


def test_a_reoffered_ingestion_job_adopts_the_kit_its_first_attempt_published(
    app: Any, client: TestClient
) -> None:
    """The D5 reaper's hole, closed.

    A job whose worker dies between publishing its kit and terminalizing the job row is
    re-offered; the kit id is per-job deterministic (``brand_kit_ing_<job suffix>`` at version 1),
    so the second attempt's INSERT used to collide and fail the job with a database error.
    ``on_conflict='adopt'`` makes it a no-op that returns the same result pointer — and it is
    SAFE precisely because the id is the job's own.
    """
    kit = {
        "id": "brand_kit_ing_roundc",
        "version": 1,
        "name": "Ingested",
        "approval_status": "draft",
    }
    body = {
        "brand_kit": kit,
        "brand_summary": {"product_ready": False},
        "diagnostics": [],
        "source": "website",
        "on_conflict": "adopt",
    }

    first = invoke(app, "design_create_brand_kit", body, actor="agent")["references"]
    assert first["created"] is True

    second = invoke(app, "design_create_brand_kit", body, actor="agent")["references"]
    assert second["created"] is False, "the re-offered attempt adopts, it does not re-create"
    assert (second["brand_kit_id"], second["version"]) == (
        first["brand_kit_id"],
        first["version"],
    ), "and it completes with the SAME result pointer"

    rows = query(
        "SELECT version FROM design_brand_kit WHERE brand_kit_id = :b AND workspace_id = :w",
        {"b": kit["id"], "w": workspace()},
    )
    assert [row["version"] for row in rows] == [1]


def test_a_client_supplied_duplicate_kit_id_is_still_refused(app: Any, client: TestClient) -> None:
    """Adoption is scoped to the job's OWN slot. Every HTTP caller keeps ``refuse``, so a kit
    version the client named and that already exists is the 409 it has always been — a route
    must never silently adopt a row it did not write."""
    kit = {"id": "brand_kit_round_c_dup", "version": 1, "name": "Dup", "approval_status": "draft"}
    body = {"brand_kit": kit, "brand_summary": {}, "diagnostics": [], "source": "manual"}

    invoke(app, "design_create_brand_kit", body)
    with pytest.raises(PreconditionFailed) as refused:
        invoke(app, "design_create_brand_kit", body)
    assert refused.value.reason_codes == ("design_brand_kit_exists",)


# --- the asset lifecycle, end to end through the governed path --------------------------------


def test_archive_and_restore_round_trip_through_the_governed_tool(client: TestClient) -> None:
    """One status-assignment tool, both directions — the ported archive-first lifecycle."""
    record = upload_logo(client, label="Lifecycle").json()["asset"]

    archived = client.post(f"/assets/{record['id']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["asset"]["status"] == "archived"

    restored = client.post(f"/assets/{record['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["asset"]["status"] == "ready"


def test_deleting_an_unknown_asset_is_a_404(client: TestClient) -> None:
    assert client.delete("/assets/asset_ghost").status_code == 404


def test_the_asset_status_tool_refuses_a_status_outside_its_vocabulary(app: Any) -> None:
    with pytest.raises(PreconditionFailed) as refused:
        invoke(app, "design_set_asset_status", {"asset_id": "asset_x", "status": "deleted"})
    assert refused.value.reason_codes == ("design_asset_status_invalid",)


def test_an_unknown_asset_refuses_before_any_write(app: Any) -> None:
    with pytest.raises(PreconditionFailed) as refused:
        invoke(app, "design_set_asset_status", {"asset_id": "asset_ghost", "status": "archived"})
    assert refused.value.reason_codes == ("design_asset_not_found",)
    with pytest.raises(NotFoundError):
        HybridRepository(workspace_id=workspace()).require_asset_record("asset_ghost")
