"""Route + pipeline tests for the asset-upload ingestion path
(slice 3 §6/§7 Agent B).

No Pillow, no Agent A analyzer or describer. The analyzer is stubbed via the
injectable ``analyze`` parameter that ``run_asset_ingestion`` resolves lazily,
returning a real ``BrandEvidence`` (built directly from
``lumen_ingestion.evidence``) plus a diagnostics list. The describer hook is
exercised by injecting a stub ``apply_descriptions`` that stamps
title/description onto the evidence — proving descriptions reach the persisted
kit assets without importing Agent A's ``describe.py``.

The route is driven through ``TestClient``, which runs FastAPI
``BackgroundTasks`` synchronously after the response is serialized — so the POST
returns a queued job but GET reflects the terminal state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api import main as main_module
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_ingestion.evidence import (
    BrandEvidence,
    ColorEvidence,
    EvidencePointer,
    ImageEvidence,
    LogoEvidence,
    NarrativeEvidence,
)
from lumen_ingestion.pipeline import run_asset_ingestion
from py_lumen_config import settings

# 1x1 minimal images so the route's magic sniff passes (§2).
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32 + b"\xff\xd9"
NOT_AN_IMAGE = b"just some plain text, not an image at all"

LOGO_ASSET_ID = "asset_ing_stublogo000000"
IMAGE_ASSET_ID = "asset_ing_stubimage00000"


def _ptr(name: str) -> EvidencePointer:
    return EvidencePointer(source="upload", locator=f"upload :: {name}")


def _stub_evidence(*, with_descriptions: bool = False) -> BrandEvidence:
    """A minimal asset-upload BrandEvidence (source kind ``logo_file`` per §2)
    that normalizes and passes draft validation, carrying one logo + one image
    plus a captured dark colorway so validation is happy."""
    logo_kwargs: dict[str, Any] = {}
    image_kwargs: dict[str, Any] = {}
    if with_descriptions:
        logo_kwargs = {
            "title": "Primary Mark",
            "description": "A teal wordmark on a transparent field.",
        }
        image_kwargs = {
            "title": "Feature Illustration",
            "description": "A soft indigo abstract illustration.",
        }
    return BrandEvidence(
        source={
            "kind": "logo_file",
            "asset_id": LOGO_ASSET_ID,
            "filename": "logo.png",
            "confidence": 0.8,
        },
        colors=[
            ColorEvidence(
                value="#12EAB1",
                weight=5.0,
                role_hints=["accent"],
                theme="light",
                name="Mint Green",
                pointer=_ptr("logo.png"),
            ),
            ColorEvidence(
                value="#F5F5F5",
                weight=4.0,
                role_hints=["page-bg"],
                theme="light",
                name="Off White",
                pointer=_ptr("logo.png"),
            ),
            ColorEvidence(
                value="#1D1C1D",
                weight=4.0,
                role_hints=["body-text"],
                theme="light",
                name="Ash Black",
                pointer=_ptr("logo.png"),
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
        logos=[
            LogoEvidence(
                asset_id=LOGO_ASSET_ID,
                color_mode_hint="full_color",
                usage_hint="primary",
                width=200.0,
                height=200.0,
                pointer=_ptr("logo.png"),
                **logo_kwargs,
            )
        ],
        images=[
            ImageEvidence(
                asset_id=IMAGE_ASSET_ID,
                width=800,
                height=800,
                transparency=True,
                dominant_colors=["#8080F9"],
                kind_hint="illustration",
                pointer=_ptr("illustration.png"),
                **image_kwargs,
            )
        ],
        narrative=NarrativeEvidence(brand_name=None),
    )


def _good_analyze(files, *, core, store_root, reporter):
    reporter("Reading your files…", 0.10)
    reporter("Analyzing your assets…", 0.40)
    return (
        _stub_evidence(),
        [{"code": "LUMI0701", "severity": "warning", "message": "one file skipped"}],
    )


def _install_stub_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    analyze: Callable[..., Any],
    apply_descriptions: Optional[Callable[..., Any]] = None,
) -> None:
    """Rebind main's ``run_asset_ingestion`` so the background task runs the real
    pipeline with the analyzer (and optionally the description hook) injected —
    mirroring how ``pipeline.py`` lazily resolves ``capture.uploads`` /
    ``describe`` so no Agent A file is imported."""

    def _runner(database_path, asset_store_root, job_id, *, workspace_id=None):
        run_asset_ingestion(
            database_path,
            asset_store_root,
            job_id,
            analyze=analyze,
            apply_descriptions=apply_descriptions,
            workspace_id=workspace_id,
        )

    monkeypatch.setattr(main_module, "run_asset_ingestion", _runner)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return make_client(app)


def _post_assets(client: TestClient, *, uploads=None, **form):
    if uploads is None:
        uploads = [
            ("logo.png", PNG_BYTES, "image/png"),
            ("photo.jpg", JPEG_BYTES, "image/jpeg"),
            ("illustration.png", PNG_BYTES, "image/png"),
        ]
    files = [("files", (name, data, mime)) for name, data, mime in uploads]
    return client.post("/brand-kits/ingest/assets", files=files, data=form)


def _read_brand_kit_row(client: TestClient, brand_kit_id: str) -> dict:
    from lumen_api.database import Repository, connect

    connection = connect(client.app.state.database_path)
    try:
        return HybridRepository(connection).require_brand_kit(brand_kit_id)
    finally:
        connection.close()


def _asset_entries(container: Any) -> list[dict]:
    """kit assets.logos / assets.images is a dict keyed by token (e.g.
    ``logo.primary`` / ``img.1``); return the entry values as a list."""
    if isinstance(container, dict):
        return list(container.values())
    return list(container or [])


def _kit_assets(kit: dict) -> tuple[list[dict], list[dict]]:
    assets = kit.get("assets") or {}
    return _asset_entries(assets.get("logos")), _asset_entries(assets.get("images"))


def test_ingest_assets_happy_path_persists_kit_and_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)

    post = _post_assets(client, name="Insight Assets")
    assert post.status_code == 200, post.text
    body = post.json()
    assert body["schema_version"] == 1
    job = body["job"]
    assert job["kind"] == "asset_upload"
    assert job["status"] == "queued", job
    job_id = job["job_id"]

    got = client.get(f"/brand-kits/ingest/{job_id}")
    assert got.status_code == 200, got.text
    got_job = got.json()["job"]
    assert got_job["status"] == "succeeded", got_job
    assert got_job["kind"] == "asset_upload"
    brand_kit_id = got_job["brand_kit_id"]
    assert brand_kit_id is not None
    assert got_job["brand_kit_version"] == 1
    assert got_job["error"] is None
    assert "request" not in got_job
    assert "evidence" not in got_job

    kit_resp = client.get(f"/brand-kits/{brand_kit_id}")
    assert kit_resp.status_code == 200, kit_resp.text
    assert kit_resp.json()["brand_kit"]["source"] == "asset_upload"

    record = _read_brand_kit_row(client, brand_kit_id)
    kit = record["brand_kit"]
    logos, images = _kit_assets(kit)
    assert len(logos) >= 1, kit["assets"]
    assert len(images) >= 1, kit["assets"]

    summary = record["brand_summary"]
    assert "ingestion" in summary, summary.keys()
    assert summary["ingestion"]["schema_version"] == 1


def test_ingest_assets_name_default_when_absent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)

    post = _post_assets(client)  # no name form field
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job

    kit = client.get(f"/brand-kits/{got_job['brand_kit_id']}").json()["brand_kit"]
    assert kit["name"] == "Uploaded assets (3 files)", kit["name"]


def test_ingest_assets_too_many_files_422(client: TestClient) -> None:
    uploads = [(f"logo{i}.png", PNG_BYTES, "image/png") for i in range(21)]
    resp = _post_assets(client, uploads=uploads)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ingest.too_many_files"


def test_ingest_assets_oversize_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "lumen_asset_max_bytes", 256)
    big = PNG_BYTES + b"x" * 512
    resp = _post_assets(client, uploads=[("big.png", big, "image/png")])
    assert resp.status_code == 413, resp.text
    assert "exceeds" in resp.text


def test_ingest_assets_none_supported_422(client: TestClient) -> None:
    resp = _post_assets(
        client,
        uploads=[
            ("notes.txt", NOT_AN_IMAGE, "text/plain"),
            ("data.bin", b"\x00\x01\x02\x03nope", "application/octet-stream"),
        ],
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ingest.unsupported_file"


def test_ingest_assets_mixed_supported_passes_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch with SOME unsupported files still queues (uploads.py skips the
    bad ones with diagnostics) as long as at least one file sniffs OK."""
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)
    resp = _post_assets(
        client,
        uploads=[
            ("logo.png", PNG_BYTES, "image/png"),
            ("notes.txt", NOT_AN_IMAGE, "text/plain"),
        ],
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job


def test_ingest_assets_cleans_tmp_files_after_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)

    post = _post_assets(client)
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job

    tmp_dir = Path(client.app.state.asset_store_root) / "ingest_tmp"
    leftovers = list(tmp_dir.glob(f"{job_id}_*"))
    assert leftovers == [], f"tmp files must be deleted after success: {leftovers}"


def test_ingest_assets_failure_marks_job_failed_and_cleans_tmp(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom_analyze(files, *, core, store_root, reporter):
        raise RuntimeError("analysis exploded")

    _install_stub_pipeline(monkeypatch, analyze=boom_analyze)

    post = _post_assets(client)
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]

    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "failed", got
    assert got["brand_kit_id"] is None
    assert "analysis exploded" in got["error"]["message"]

    # Tmp files are deleted even on the failure path.
    tmp_dir = Path(client.app.state.asset_store_root) / "ingest_tmp"
    leftovers = list(tmp_dir.glob(f"{job_id}_*"))
    assert leftovers == [], f"tmp files must be deleted after failure: {leftovers}"

    # No asset_upload kit row was created.
    kits = client.get("/brand-kits").json()
    assert all(k.get("source") != "asset_upload" for k in kits)


def test_ingest_assets_missing_tmp_file_fails_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # run_asset_ingestion must never raise; a missing tmp file → job failed with
    # a clear LUMI0605 message rather than a crash. Re-running the pipeline
    # against a job whose tmp files were already consumed proves the handling.
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)

    post = _post_assets(client)
    job_id = post.json()["job"]["job_id"]
    # After the (synchronous) happy background run the tmp files are already
    # gone; re-run the pipeline against the same job to prove missing-tmp
    # handling.
    run_asset_ingestion(
        str(client.app.state.database_path),
        client.app.state.asset_store_root,
        job_id,
        analyze=_good_analyze,
    )
    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "failed", got
    assert "LUMI0605" in got["error"]["message"], got["error"]


def test_ingest_assets_describer_hook_stamps_descriptions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stub ``apply_descriptions`` (standing in for describe.py) that stamps
    title/description onto the evidence → those descriptions surface on the
    persisted kit's logo + image assets."""
    seen: dict[str, Any] = {}

    def stub_apply_descriptions(
        evidence, *, connection, describer, resolve_bytes, reporter, **_kwargs
    ):
        # **_kwargs absorbs the imagery-slice-1 seam extensions
        # (rasterize_svg, diagnostics) — this stub only asserts the hook fires.
        seen["called"] = True
        seen["describer"] = describer
        reporter("Describing your assets…", 0.80)
        # Return a fresh evidence carrying stamped title/description so the
        # normalizer/emit stamps them onto the kit assets.
        return _stub_evidence(with_descriptions=True)

    _install_stub_pipeline(
        monkeypatch,
        analyze=_good_analyze,
        apply_descriptions=stub_apply_descriptions,
    )

    post = _post_assets(client, name="Described Assets")
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job
    assert seen.get("called") is True

    kit = client.get(f"/brand-kits/{got_job['brand_kit_id']}").json()["brand_kit_json"]
    logos, images = _kit_assets(kit)
    logo_titles = [entry.get("title") for entry in logos]
    image_titles = [entry.get("title") for entry in images]
    assert "Primary Mark" in logo_titles, logos
    assert "Feature Illustration" in image_titles, images


def test_ingest_assets_null_describer_is_noop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default hook (no apply_descriptions injected, describe.py absent) is a
    guaranteed no-op pass-through — the kit persists with no descriptions and no
    error. Proves the website + PDF paths are safe too."""
    monkeypatch.setattr(settings, "lumen_ingestion_describe", False)
    _install_stub_pipeline(monkeypatch, analyze=_good_analyze)

    post = _post_assets(client)
    job_id = post.json()["job"]["job_id"]
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job

    kit = client.get(f"/brand-kits/{got_job['brand_kit_id']}").json()["brand_kit_json"]
    logos, _images = _kit_assets(kit)
    # No description engine ran → logos carry no stamped title.
    assert all("title" not in entry for entry in logos), logos
