"""The ``kit_repair`` ingestion job (spec 2026-10-25 §3.4 B).

One job a workspace repair offers: describe the planned assets as one batch, republish the kit
with the descriptions stamped, and re-offer a missing ad-DNA card. Real uploads, real description
rows, the real publish tool; the vision model and the engine are stubbed.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from asset_analysis_fixture import analysis
from lumen_api.asset_enrichment import run_asset_enrichment
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_ingestion import pipeline
from lumen_ingestion.ad_library import auto_card
from lumen_ingestion.describe import DescribeResult
from lumen_ingestion.jobs import IngestionJobStore

KIT_ID = "brand_kit_repair_test"


class _Good:
    active = True

    def describe(self, items: list[Any]) -> list[DescribeResult]:
        return [
            DescribeResult(item.asset_id, f"Title {item.asset_id}", f"Caption {item.asset_id}.",
                           "Use anywhere.", [], analysis=analysis("Ok", item.source_occurrences))
            for item in items
        ]


class _Down:
    active = True

    def describe(self, items: list[Any]) -> list[DescribeResult]:
        raise RuntimeError("provider_refused:openrouter:auth_invalid")


class _FailsFor(_Good):
    def __init__(self, asset_id: str) -> None:
        self.asset_id = asset_id

    def describe(self, items: list[Any]) -> list[DescribeResult]:
        if items[0].asset_id == self.asset_id:
            raise RuntimeError("still down for this one")
        return super().describe(items)


class _StubCore:
    def validate_brand_kit(self, kit: dict, product_ready: bool = False) -> dict:
        return {"brand_kit": kit, "diagnostics": []}

    def summarize_brand_kit(self, kit: dict, raise_on_error: bool = False) -> dict:
        return {"brand_summary": {}, "diagnostics": []}


def _png(colour: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _workspace_with_failed_descriptions(tmp_path, workspace_id, design_storage, monkeypatch):
    """Three uploaded images whose analyses all failed in an outage, and a kit that lists them
    with no descriptions — the Illumio shape."""
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _Down())
    client = TestClient(create_app(tmp_path / "cache", storage=design_storage),
                        headers={"X-Workspace-Id": workspace_id})
    asset_ids = []
    for colour in ("#003366", "#663300", "#336600"):
        response = client.post(
            "/assets", files={"file": (f"{colour[1:]}.png", _png(colour), "image/png")},
            data={"creative_type": "logo"}, headers={"Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_asset_enrichment(str(tmp_path / "cache"), body["enrichment"]["job_id"],
                             workspace_id=workspace_id, storage=design_storage)
        asset_ids.append(body["asset"]["id"])
    repo = HybridRepository(workspace_id)
    repo.create_brand_kit(
        {"id": KIT_ID, "version": 1, "name": "Repair", "approval_status": "approved",
         "assets": {"images": {f"img.{n}": {"asset_id": aid, "role": "photo"}
                               for n, aid in enumerate(asset_ids)}}},
        {"product_ready": False}, [], "website",
    )
    return client, asset_ids


def _offer_repair(workspace_id: str, asset_ids: list[str], *, offer_card: bool = True) -> str:
    job = IngestionJobStore(workspace_id=workspace_id).create(
        "kit_repair",
        {"targets": {aid: {} for aid in asset_ids}, "republish_brand_kit_id": KIT_ID,
         "offer_card": offer_card, "actor": "operator:ops@cluehq.ai", "reason": "outage",
         "operation_id": str(uuid4())},
    )
    return str(job["job_id"])


def _run(tmp_path, job_id, workspace_id, design_storage) -> dict:
    from lumen_ingestion.kit_repair import run_kit_repair

    run_kit_repair(str(tmp_path / "cache"), job_id, workspace_id=workspace_id,
                   storage=design_storage)
    return IngestionJobStore(workspace_id=workspace_id).require(job_id)


def _statuses(client: TestClient, asset_ids: list[str]) -> list[str]:
    rows = client.get("/assets/descriptions", params={"asset_ids": ",".join(asset_ids)}).json()
    return [rows["descriptions"][aid]["status"] for aid in asset_ids]


def test_kit_repair_describes_republishes_and_offers_card(
    tmp_path, workspace_id, design_storage, monkeypatch
) -> None:
    client, asset_ids = _workspace_with_failed_descriptions(
        tmp_path, workspace_id, design_storage, monkeypatch)
    assert _statuses(client, asset_ids) == ["failed"] * 3
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _Good())
    monkeypatch.setattr(pipeline, "_core_client", lambda: _StubCore())
    offers: list[dict] = []
    monkeypatch.setattr(auto_card, "offer_card_if_ready",
                        lambda ws, **kw: offers.append({"ws": ws, "retry": kw.get("retry")})
                        or "ingest_adcard_x")

    job = _run(tmp_path, _offer_repair(workspace_id, asset_ids), workspace_id, design_storage)

    assert job["status"] == "succeeded", job
    assert _statuses(client, asset_ids) == ["ready"] * 3
    kit = HybridRepository(workspace_id).require_brand_kit(KIT_ID)
    assert kit["version"] == 2
    images = kit["brand_kit"]["assets"]["images"]
    # The structured analysis is the description of record (asset_analysis_fixture).
    assert {entry.get("description") for entry in images.values()} == {
        "A product interface with a navigation sidebar."
    }
    assert (job["brand_kit_id"], job["brand_kit_version"]) == (KIT_ID, 2)
    assert offers == [{"ws": workspace_id, "retry": True}]
    assert job["evidence"]["card_job_id"] == "ingest_adcard_x"
    assert job["evidence"]["gaps"] == []


def test_kit_repair_with_a_still_failing_asset_ends_with_gaps(
    tmp_path, workspace_id, design_storage, monkeypatch
) -> None:
    client, asset_ids = _workspace_with_failed_descriptions(
        tmp_path, workspace_id, design_storage, monkeypatch)
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _FailsFor(asset_ids[0]))
    monkeypatch.setattr(pipeline, "_core_client", lambda: _StubCore())

    job = _run(tmp_path, _offer_repair(workspace_id, asset_ids, offer_card=False),
               workspace_id, design_storage)

    assert job["status"] == "succeeded_with_gaps", job
    assert job["evidence"]["gaps"] == [
        {"area": "descriptions", "failed": 1, "reason": "analysis failed"}
    ]
    assert HybridRepository(workspace_id).require_brand_kit(KIT_ID)["version"] == 2


def test_kit_repair_run_twice_publishes_once(
    tmp_path, workspace_id, design_storage, monkeypatch
) -> None:
    """A re-driven job (its worker died after publishing) must not publish a second version."""
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    client, asset_ids = _workspace_with_failed_descriptions(
        tmp_path, workspace_id, design_storage, monkeypatch)
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _Good())
    monkeypatch.setattr(pipeline, "_core_client", lambda: _StubCore())
    job_id = _offer_repair(workspace_id, asset_ids, offer_card=False)
    _run(tmp_path, job_id, workspace_id, design_storage)

    async def reopen(conn: Any) -> None:
        await conn.execute(
            text("UPDATE design_ingestion_job SET status = 'running' WHERE job_id = :j"),
            {"j": job_id},
        )

    DesignStoreBridge(workspace_id)._run(reopen)
    again = _run(tmp_path, job_id, workspace_id, design_storage)

    assert again["status"] == "succeeded"
    assert HybridRepository(workspace_id).require_brand_kit(KIT_ID)["version"] == 2
