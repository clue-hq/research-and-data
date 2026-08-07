"""Route + pipeline tests for the brand-guidelines PDF ingestion path
(slice 2 §4/§5 Agent B).

No pymupdf, no Pillow, no Agent A dependency. The extractor is stubbed via the
injectable ``extract`` parameter that ``run_pdf_ingestion`` resolves lazily; the
stub returns a real ``BrandEvidence`` (built directly from
``lumen_ingestion.evidence``) wrapped in a ``PdfExtraction``-shaped object. The
route is exercised through ``TestClient``, which runs FastAPI
``BackgroundTasks`` synchronously after the response is serialized — so the POST
returns a queued job but GET reflects the terminal state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api import main as main_module
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_ingestion.evidence import (
    BrandEvidence,
    ColorEvidence,
    EvidencePointer,
    FontEvidence,
    NarrativeEvidence,
    RuleEvidence,
)
from lumen_ingestion.pipeline import run_pdf_ingestion
from py_lumen_config import settings

REFERENCE_ASSET_ID = "asset_ing_stubpdf00000000"

PDF_HEADER = b"%PDF-1.7\n"


def _ptr(name: str) -> EvidencePointer:
    return EvidencePointer(source="pdf", locator=f"page 1 :: {name}")


def _stub_evidence() -> BrandEvidence:
    """A minimal-but-valid PDF-shaped BrandEvidence (source kind
    ``uploaded_pdf`` per §1) that normalizes and passes draft validation with a
    captured dark colorway."""
    return BrandEvidence(
        source={
            "kind": "uploaded_pdf",
            "asset_id": REFERENCE_ASSET_ID,
            "filename": "insight-brand-guidelines.pdf",
            "confidence": 0.75,
        },
        colors=[
            ColorEvidence(
                value="#12EAB1",
                weight=5.0,
                role_hints=["accent"],
                name="Mint Green",
                pointer=_ptr("Mint Green"),
            ),
            ColorEvidence(
                value="#F5F5F5",
                weight=4.0,
                role_hints=["page-bg"],
                name="Off White",
                pointer=_ptr("Off White"),
            ),
            ColorEvidence(
                value="#1D1C1D",
                weight=4.0,
                role_hints=["body-text"],
                name="Ash Black",
                pointer=_ptr("Ash Black"),
            ),
            ColorEvidence(
                value="#1D1C1D",
                weight=3.0,
                theme="dark",
                role_hints=["page-bg"],
                name="Ash Black",
                pointer=_ptr("dark panel"),
            ),
        ],
        fonts=[
            FontEvidence(family="Aeonik", role_hint="heading", pointer=_ptr("Aeonik"))
        ],
        rules=[
            RuleEvidence(
                kind="dont", text="Don't stretch the logo.", pointer=_ptr("donts")
            )
        ],
        narrative=NarrativeEvidence(
            brand_name="Insight Health",
            summary_facts=["Digital-first primary care."],
        ),
    )


@dataclass
class FakePdfExtraction:
    """PdfExtraction-shaped stand-in (§1). The pipeline reads ``evidence``,
    ``diagnostics``, and (opaquely) ``reference_asset_id``/``page_count``."""

    evidence: BrandEvidence
    diagnostics: list[dict] = field(
        default_factory=lambda: [
            {"code": "LUMI0603", "severity": "info", "message": "image cap applied"}
        ]
    )
    reference_asset_id: str = REFERENCE_ASSET_ID
    page_count: int = 19


def _install_stub_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    extract: Callable[..., Any],
) -> None:
    """Rebind main's ``run_pdf_ingestion`` so the background task runs the real
    pipeline but with the extractor injected. Resolving the stub through the
    injectable ``extract`` param mirrors how ``pipeline.py`` lazily resolves
    ``capture.pdf`` — so no Agent A file is imported."""

    def _runner(database_path, asset_store_root, job_id, *, workspace_id=None):
        run_pdf_ingestion(
            database_path,
            asset_store_root,
            job_id,
            extract=extract,
            workspace_id=workspace_id,
        )

    monkeypatch.setattr(main_module, "run_pdf_ingestion", _runner)


def _good_extract(pdf_bytes, filename, *, core, store_root, reporter):
    reporter("Reading your brand guidelines…", 0.05)
    reporter("Extracting your colors…", 0.25)
    return FakePdfExtraction(evidence=_stub_evidence())


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return TestClient(app)


def _post_pdf(client: TestClient, *, data: bytes = PDF_HEADER + b"body", **form):
    files = {"file": ("insight-brand-guidelines.pdf", data, "application/pdf")}
    return client.post("/brand-kits/ingest/pdf", files=files, data=form)


def test_ingest_pdf_happy_path_persists_kit_and_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_pipeline(monkeypatch, extract=_good_extract)

    post = _post_pdf(client, name="Insight Health")
    assert post.status_code == 200, post.text
    body = post.json()
    assert body["schema_version"] == 1
    job = body["job"]
    assert job["kind"] == "pdf"
    # POST returns the queued job; the background task runs after the response
    # is serialized (TestClient runs it synchronously before unblocking).
    assert job["status"] == "queued", job
    job_id = job["job_id"]

    got = client.get(f"/brand-kits/ingest/{job_id}")
    assert got.status_code == 200, got.text
    got_job = got.json()["job"]
    assert got_job["status"] == "succeeded", got_job
    assert got_job["kind"] == "pdf"
    brand_kit_id = got_job["brand_kit_id"]
    assert brand_kit_id is not None
    assert got_job["brand_kit_version"] == 1
    assert got_job["error"] is None
    # Public dto carries no request/evidence bodies.
    assert "request" not in got_job
    assert "evidence" not in got_job

    kit = client.get(f"/brand-kits/{brand_kit_id}")
    assert kit.status_code == 200, kit.text
    assert kit.json()["brand_kit"]["source"] == "pdf"

    record = _read_brand_kit_row(client, brand_kit_id)
    summary = record["brand_summary"]
    assert "ingestion" in summary, summary.keys()
    report = summary["ingestion"]
    assert report["schema_version"] == 1
    # The reference PDF asset id surfaces in the report source dict.
    assert report["source"]["kind"] == "uploaded_pdf"
    assert report["source"]["asset_id"] == REFERENCE_ASSET_ID
    assert report["dark_colorway"] == "captured"


def test_ingest_pdf_cleans_tmp_file_after_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_pipeline(monkeypatch, extract=_good_extract)

    post = _post_pdf(client)
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job

    tmp_path = Path(client.app.state.asset_store_root) / "ingest_tmp" / f"{job_id}.pdf"
    assert not tmp_path.exists(), "tmp PDF must be deleted after a successful run"


def test_ingest_pdf_failure_marks_job_failed_and_cleans_tmp(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom_extract(pdf_bytes, filename, *, core, store_root, reporter):
        raise RuntimeError("extraction exploded")

    _install_stub_pipeline(monkeypatch, extract=boom_extract)

    post = _post_pdf(client)
    assert post.status_code == 200, post.text
    job = post.json()["job"]
    assert job["status"] == "queued", job
    job_id = job["job_id"]

    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "failed", got
    assert got["brand_kit_id"] is None
    assert got["error"] is not None
    assert "extraction exploded" in got["error"]["message"]

    # The tmp file is deleted even on the failure path.
    tmp_path = Path(client.app.state.asset_store_root) / "ingest_tmp" / f"{job_id}.pdf"
    assert not tmp_path.exists(), "tmp PDF must be deleted after a failed run"

    # No pdf kit row was created.
    kits = client.get("/brand-kits").json()
    assert all(k.get("source") != "pdf" for k in kits)


def test_ingest_pdf_missing_tmp_file_fails_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # run_pdf_ingestion must never raise; a missing tmp file → job failed with a
    # clear error rather than a crash.
    _install_stub_pipeline(monkeypatch, extract=_good_extract)

    post = _post_pdf(client)
    job_id = post.json()["job"]["job_id"]
    # Deleting the tmp file before the (synchronous) background task ran is not
    # possible via the client; instead invoke the pipeline directly with a job
    # whose tmp file we remove first.
    tmp_path = Path(client.app.state.asset_store_root) / "ingest_tmp" / f"{job_id}.pdf"
    # After the happy background run the file is already gone; re-run the
    # pipeline against the same (now-clean) job to prove missing-tmp handling.
    run_pdf_ingestion(
        str(client.app.state.database_path),
        client.app.state.asset_store_root,
        job_id,
        extract=_good_extract,
    )
    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "failed", got
    assert "LUMI0605" in got["error"]["message"], got["error"]
    assert not tmp_path.exists()


def test_ingest_pdf_rejects_non_pdf_bytes(client: TestClient) -> None:
    files = {"file": ("not-a-pdf.pdf", b"just text, no header", "application/pdf")}
    resp = client.post("/brand-kits/ingest/pdf", files=files)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ingest.not_a_pdf"


def test_ingest_pdf_rejects_unsupported_file(client: TestClient) -> None:
    files = {"file": ("logo.png", PDF_HEADER, "image/png")}
    resp = client.post("/brand-kits/ingest/pdf", files=files)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ingest.unsupported_file"


def test_ingest_pdf_rejects_oversize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "lumen_asset_max_bytes", 1024)
    big = PDF_HEADER + b"x" * 2048
    files = {"file": ("big.pdf", big, "application/pdf")}
    resp = client.post("/brand-kits/ingest/pdf", files=files)
    assert resp.status_code == 413, resp.text
    assert "exceeds" in resp.text


def _read_brand_kit_row(client: TestClient, brand_kit_id: str) -> dict:
    from lumen_api.database import Repository, connect

    connection = connect(client.app.state.database_path)
    try:
        return HybridRepository(connection).require_brand_kit(brand_kit_id)
    finally:
        connection.close()
