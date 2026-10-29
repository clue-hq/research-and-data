"""Slice 4 — brand-kit review UI + asset library API surface (Agent A).

Covers the four apps/api additions the frontend review/library/ingest pages
consume:

* ``POST /brand-kits/{id}/approval`` (approve / revert; column + mirrored
  ``brand_kit_json.approval_status``; 422 invalid; 404 unknown),
* ``brand_kit_detail_dto`` carrying the full ``brand_summary`` (incl. the
  ingestion report),
* ``GET /assets/descriptions`` batch + ``PUT /assets/{id}/description`` partial
  merge (human origin; 404 only when the asset record is missing; and the
  literal ``descriptions`` segment must not resolve as an unknown asset id),
* ``GET /brand-kits/ingest`` most-recent-50 job list.

Kits are seeded directly through ``HybridRepository`` against the shared Postgres store
(the ingestion pipeline is exercised elsewhere); assets are uploaded through the
real ``POST /assets`` route so a genuine record exists for the description path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, wait_for_ingestion_job

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # These tests upload a logo only to have an asset record. An image upload also offers a
    # background description job, and if the test client's worker picked it up the job waited
    # forever at teardown on analysis tasks nobody ran, hanging the run (2026-10-29). Uploads
    # here register the record and offer nothing; enrichment is tested where it is the subject.
    def register_without_enrichment(workspace_id: str, record: dict, enrichment: dict) -> dict:
        return HybridRepository(workspace_id=workspace_id).create_asset_record(record)

    monkeypatch.setattr("lumen_api.asset_enrichment.register_upload", register_without_enrichment)
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def _seed_kit(
    client: TestClient,
    *,
    brand_kit_id: str = "kit_seed",
    version: int = 1,
    approval_status: str = "draft",
    source: str = "website",
    brand_summary: dict | None = None,
) -> dict:
    """Insert a kit row directly into the app's DB and return the stored row."""
    brand_kit = {
        "id": brand_kit_id,
        "version": version,
        "name": "Insight Health",
        "approval_status": approval_status,
        "description": "Calm, clinical, trustworthy.",
    }
    summary = brand_summary if brand_summary is not None else {"product_ready": False}
    return HybridRepository().create_brand_kit(
        brand_kit, summary, [], source
    )


def _read_kit_row(client: TestClient, brand_kit_id: str, version: int | None = None) -> dict:
    return HybridRepository().require_brand_kit(brand_kit_id, version)


def _upload_logo(client: TestClient) -> str:
    resp = client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG_PATH.read_bytes(), "image/png")},
        data={"label": "Acme logo", "kind": "logo", "uploaded_by": "designer"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["asset"]["id"]


# --- approval -------------------------------------------------------------------


def test_approval_approves_and_mirrors_into_kit_json(client: TestClient) -> None:
    _seed_kit(client, approval_status="draft")

    resp = client.post(
        "/brand-kits/kit_seed/approval", json={"approval_status": "approved"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # DTO reflects the new state on both the summary and the raw kit json.
    assert body["brand_kit"]["approval_status"] == "approved"
    assert body["brand_kit_json"]["approval_status"] == "approved"

    # Persisted row: column AND mirrored brand_kit_json.approval_status.
    row = _read_kit_row(client, "kit_seed")
    assert row["approval_status"] == "approved"
    assert row["brand_kit"]["approval_status"] == "approved"


def test_approval_reverts_to_draft(client: TestClient) -> None:
    _seed_kit(client, approval_status="approved")

    resp = client.post(
        "/brand-kits/kit_seed/approval", json={"approval_status": "draft"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["brand_kit"]["approval_status"] == "draft"

    row = _read_kit_row(client, "kit_seed")
    assert row["approval_status"] == "draft"
    assert row["brand_kit"]["approval_status"] == "draft"


def test_approval_updates_only_latest_version(client: TestClient) -> None:
    _seed_kit(client, brand_kit_id="kit_multi", version=1, approval_status="draft")
    _seed_kit(client, brand_kit_id="kit_multi", version=2, approval_status="draft")

    resp = client.post(
        "/brand-kits/kit_multi/approval", json={"approval_status": "approved"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["brand_kit"]["version"] == 2

    latest = _read_kit_row(client, "kit_multi", 2)
    older = _read_kit_row(client, "kit_multi", 1)
    assert latest["approval_status"] == "approved"
    assert latest["brand_kit"]["approval_status"] == "approved"
    # Older version untouched.
    assert older["approval_status"] == "draft"
    assert older["brand_kit"]["approval_status"] == "draft"


def test_approval_invalid_status_is_422(client: TestClient) -> None:
    _seed_kit(client)
    resp = client.post(
        "/brand-kits/kit_seed/approval", json={"approval_status": "maybe"}
    )
    assert resp.status_code == 422, resp.text


def test_approval_unknown_kit_is_404(client: TestClient) -> None:
    resp = client.post(
        "/brand-kits/kit_nope/approval", json={"approval_status": "approved"}
    )
    assert resp.status_code == 404, resp.text


# --- detail dto brand_summary ---------------------------------------------------


def test_detail_dto_carries_full_brand_summary(client: TestClient) -> None:
    summary = {
        "product_ready": True,
        "modes": ["theme.dark"],
        "ingestion": {
            "schema_version": 1,
            "source": {"kind": "website"},
            "dark_colorway": "synthesized",
        },
    }
    _seed_kit(client, brand_kit_id="kit_summary", brand_summary=summary)

    resp = client.get("/brand-kits/kit_summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "brand_summary" in body
    # Full summary, including the ingestion report, is surfaced.
    assert body["brand_summary"]["ingestion"]["dark_colorway"] == "synthesized"
    assert body["brand_summary"]["ingestion"]["source"]["kind"] == "website"


def test_detail_dto_brand_summary_defaults_to_object(client: TestClient) -> None:
    # A kit with an empty summary still gets an object (not null) under the key.
    _seed_kit(client, brand_kit_id="kit_empty", brand_summary={})
    resp = client.get("/brand-kits/kit_empty")
    assert resp.status_code == 200, resp.text
    assert resp.json()["brand_summary"] == {}


# --- descriptions ---------------------------------------------------------------


def test_descriptions_get_batch_missing_ids_absent(client: TestClient) -> None:
    asset_id = _upload_logo(client)
    # Author one row so it comes back; the unknown id is simply absent.
    put = client.put(
        f"/assets/{asset_id}/description",
        json={"title": "Acme mark", "tags": ["logo", "red"]},
    )
    assert put.status_code == 200, put.text

    resp = client.get(
        "/assets/descriptions",
        params={"asset_ids": f"{asset_id},asset_missing"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 1
    assert set(body["descriptions"].keys()) == {asset_id}
    row = body["descriptions"][asset_id]
    assert row["title"] == "Acme mark"
    assert row["tags"] == ["logo", "red"]
    assert row["origin"] == "human"


def test_descriptions_literal_segment_not_treated_as_asset_id(
    client: TestClient,
) -> None:
    # GET /assets/descriptions must NOT fall through to GET /assets/{asset_id}
    # and 404 as an unknown asset (route ordering guarantee).
    resp = client.get("/assets/descriptions", params={"asset_ids": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json()["descriptions"] == {}


def test_description_put_partial_merge_preserves_untouched_fields(
    client: TestClient,
) -> None:
    asset_id = _upload_logo(client)

    first = client.put(
        f"/assets/{asset_id}/description",
        json={
            "title": "Acme mark",
            "description": "Red square logo.",
            "usage": "Use on light backgrounds.",
            "tags": ["logo"],
        },
    )
    assert first.status_code == 200, first.text

    # Second PUT touches only the title; other fields merge from the existing row.
    second = client.put(
        f"/assets/{asset_id}/description", json={"title": "Acme wordmark"}
    )
    assert second.status_code == 200, second.text
    row = second.json()
    assert row["title"] == "Acme wordmark"
    assert row["description"] == "Red square logo."
    assert row["usage"] == "Use on light backgrounds."
    assert row["tags"] == ["logo"]
    assert row["origin"] == "human"


def test_description_put_sets_human_origin_over_absent_row(
    client: TestClient,
) -> None:
    asset_id = _upload_logo(client)
    resp = client.put(
        f"/assets/{asset_id}/description", json={"description": "A caption."}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["origin"] == "human"


def test_description_put_unknown_asset_is_404(client: TestClient) -> None:
    resp = client.put(
        "/assets/asset_missing/description", json={"title": "Nope"}
    )
    assert resp.status_code == 404, resp.text


# --- job list -------------------------------------------------------------------


def _seed_job(client: TestClient, kind: str) -> dict:
    from lumen_ingestion.jobs import IngestionJobStore

    return IngestionJobStore().create(kind, {"url": "https://x.example"})


def test_job_list_shape_and_recency_ordering(client: TestClient) -> None:
    first = _seed_job(client, "website")
    second = _seed_job(client, "pdf")
    third = _seed_job(client, "asset_upload")

    resp = client.get("/brand-kits/ingest")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 1
    jobs = body["jobs"]
    assert len(jobs) == 3
    # Most-recent first; public dto carries no request/evidence bodies.
    ids = [job["job_id"] for job in jobs]
    assert ids[0] == third["job_id"]
    assert set(ids) == {first["job_id"], second["job_id"], third["job_id"]}
    for job in jobs:
        assert "request" not in job
        assert "evidence" not in job
        assert {"job_id", "kind", "status", "stage", "progress"} <= set(job.keys())


def test_job_dto_carries_the_website_url_for_website_jobs_only(client: TestClient) -> None:
    """brand-kit slice 4: the Brand-context page's Re-extract button needs the URL a
    kit-less workspace's failed auto-ingestion was submitted with — the workspace's own
    input, served workspace-scoped. Non-website kinds have no URL and say so."""
    from lumen_ingestion.jobs import IngestionJobStore

    store = IngestionJobStore()
    website = store.create("website", {"url": "https://insighthealth.example"})
    pdf = store.create("pdf", {"filename": "brand.pdf"})
    uploads = store.create("asset_upload", {"filenames": ["logo.png"]})

    by_id = {job["job_id"]: job for job in client.get("/brand-kits/ingest").json()["jobs"]}
    assert by_id[website["job_id"]]["website_url"] == "https://insighthealth.example"
    assert by_id[pdf["job_id"]]["website_url"] is None
    assert by_id[uploads["job_id"]]["website_url"] is None
    # Still the public view: the URL is one named field, not the request body.
    assert "request" not in by_id[website["job_id"]]

    single = client.get(f"/brand-kits/ingest/{website['job_id']}").json()["job"]
    assert single["website_url"] == "https://insighthealth.example"


def test_job_list_empty(client: TestClient) -> None:
    resp = client.get("/brand-kits/ingest")
    assert resp.status_code == 200, resp.text
    assert resp.json()["jobs"] == []


def test_pipeline_ingested_assets_get_db_records(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (found in the slice-4 taste review): assets ingested by the
    capture layer must land as DB asset records so /assets/{id}/bytes and the
    library can serve them — the pipeline's _RecordingCore persists them."""
    import base64
    import json as _json

    from lumen_api import main as main_module
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.pipeline import run_website_ingestion

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "ingestion"
        / "evidence_website_insight.json"
    )
    png_bytes = LOGO_PNG_PATH.read_bytes()
    ingested_ids: list[str] = []

    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False
    ):
        assert discover_pages is True
        class Outcome:
            tier = "static"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        response = core.ingest_asset(
            store_root=store_root,
            bytes_base64=base64.b64encode(png_bytes).decode("ascii"),
            asset_id="asset_ing_reviewfix01",
            label="review-fix logo",
            declared_mime_type="image/png",
            filename="review-fix.png",
            kind="raster_image",
            tags=["brand-ingestion", "image"],
            raise_on_error=False,
        )
        assert response.get("ok"), response
        ingested_ids.append("asset_ing_reviewfix01")
        return BrandEvidence.model_validate(_json.loads(fixture.read_text()))

    async def passthrough(url: str) -> str:
        return url

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: passthrough)
    monkeypatch.setattr(
        main_module,
        "run_website_ingestion",
        lambda cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None: (
            run_website_ingestion(
                cache_dir,
                job_id,
                capture=fake_capture,
                build_evidence=fake_build_evidence,
                workspace_id=workspace_id,
                storage=storage,
                expected_generation=expected_generation,
            )
        ),
    )

    post = client.post(
        "/brand-kits/ingest/website", json={"url": "https://record-fix.example"}
    )
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert job["status"] == "succeeded", job

    assert ingested_ids == ["asset_ing_reviewfix01"]
    record = client.get("/assets/asset_ing_reviewfix01")
    assert record.status_code == 200, record.text
    body = client.get("/assets/asset_ing_reviewfix01/bytes")
    assert body.status_code == 200
    assert body.content == png_bytes
