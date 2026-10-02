"""Option A (2026-09-02), end to end: a WOFF2 font that enters through the two production doors
— the website-ingestion pipeline (`_RecordingCore` → durable custody → registry) and
`POST /assets` — is stored, recorded, and served as TTF.

The pipeline leg drives the fleet WORKER ENTRY (`execute_ingestion_job`) in process rather than
offering the job over the route, because any live design API on the same DSN would otherwise
claim the offered `design_job` and run it without this module's stubs.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont

from clue_design.envelopes import DesignIngestionEnvelope
from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
EVIDENCE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"
)
SFNT_TTF_MAGIC = b"\x00\x01\x00\x00"


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    font = TTFont(BytesIO(inter_ttf), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_order(data: bytes) -> list[str]:
    return TTFont(BytesIO(data)).getGlyphOrder()


def assert_stored_as_ttf(client: TestClient, asset_id: str, inter_ttf: bytes) -> None:
    stored = HybridRepository().require_asset_record(asset_id)["asset"]
    media = stored["media"]
    assert media["mime_type"] == "font/ttf", media
    assert media["filename"].endswith(".ttf"), media
    assert any(
        "decoded at ingestion: woff2 -> ttf" in note
        for note in stored["provenance"]["notes"]
    ), stored["provenance"]
    served = client.get(f"/assets/{asset_id}/bytes")
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("font/ttf")
    assert served.content[:4] == SFNT_TTF_MAGIC
    assert glyph_order(served.content) == glyph_order(inter_ttf)
    assert media["digest"]["value"] == __import__("hashlib").sha256(served.content).hexdigest()


def test_website_ingestion_persists_a_harvested_woff2_face_as_ttf(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, inter_ttf: bytes, inter_woff2: bytes
) -> None:
    """The job row is created directly and executed through the worker entry, never OFFERED.

    ``execute_ingestion_job`` is what the embedded (and detached) fleet worker actually calls, and
    it resolves ``run_website_ingestion`` from ``lumen_api.main``'s namespace at call time — the
    documented seam this module's stubs hang on. Going through
    ``POST /brand-kits/ingest/website`` instead would enqueue a ``design_job`` on the shared
    queue, where a co-running design API on the same DSN claims it and runs the REAL capture.
    """
    from lumen_api import main as main_module
    from lumen_api.main import execute_ingestion_job
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.pipeline import run_website_ingestion

    asset_id = "asset_ing_fontdecode01"
    ingested: list[dict] = []

    async def fake_capture(url, *, reporter, force_render=False, page_urls=None):
        class Outcome:
            tier = "static"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        # The exact call `lumen_ingestion.capture.evidence_builder._call_ingest` makes for a
        # harvested webfont, with real WOFF2 bytes.
        response = core.ingest_asset(
            store_root=store_root,
            bytes_base64=base64.b64encode(inter_woff2).decode("ascii"),
            asset_id=asset_id,
            label="inter-var.woff2",
            declared_mime_type="font/woff2",
            filename="inter-var.woff2",
            kind="font",
            provenance={
                "created_by": "lumen_ingestion",
                "created_at": "2026-09-02T00:00:00+00:00",
                "source_label": "website",
                "confidence": 0.7,
                "notes": [],
            },
            source={
                "kind": "website",
                "url": "https://record-fix.example/fonts/inter-var.woff2",
                "captured_at": "2026-09-02T00:00:00+00:00",
            },
            tags=["brand-ingestion", "font"],
            max_bytes=15 * 1024 * 1024,
            raise_on_error=False,
        )
        assert response.get("ok"), response
        ingested.append(response["asset"]["record"])
        return BrandEvidence.model_validate(json.loads(EVIDENCE_FIXTURE.read_text()))

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

    workspace_id = HybridRepository().workspace_id
    job = IngestionJobStore(workspace_id=workspace_id).create(
        "website", {"url": "https://record-fix.example"}
    )
    state = client.app.state
    status = execute_ingestion_job(
        DesignIngestionEnvelope(
            kind="ingestion",
            work_id=uuid4(),
            workspace_id=workspace_id,
            job_id=job["job_id"],
            ingestion_kind="website",
        ),
        host=SimpleNamespace(
            storage=state.storage, engine_cache_root=state.engine_cache_root
        ),
    )
    assert status == "succeeded", status

    assert [record["id"] for record in ingested] == [asset_id]
    assert ingested[0]["media"]["mime_type"] == "font/ttf"
    assert_stored_as_ttf(client, asset_id, inter_ttf)


def test_upload_route_persists_a_woff2_font_as_ttf(
    client: TestClient, inter_ttf: bytes, inter_woff2: bytes
) -> None:
    response = client.post(
        "/assets",
        files={"file": ("inter.woff2", inter_woff2, "font/woff2")},
        data={"label": "Inter web upload", "kind": "font"},
    )
    assert response.status_code == 200, response.text
    asset = response.json()["asset"]
    assert asset["media"]["mime_type"] == "font/ttf", asset
    assert_stored_as_ttf(client, asset["id"], inter_ttf)


def test_upload_route_refuses_an_undecodable_woff2(client: TestClient) -> None:
    response = client.post(
        "/assets",
        files={"file": ("broken.woff2", b"wOF2" + b"\x00" * 96, "font/woff2")},
        data={"label": "broken", "kind": "font"},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ingest.font_decode_failed"
