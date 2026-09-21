"""Captured supporting media enter the shared library without changing homepage identity.

Synthetic snapshots exercise the real evidence builder. The sink substitutes only the
subprocess asset ingester; the integration test below uses the real engine and registry.
These fixtures are regression inputs, not seeded brand packs or fresh-URL capture proof.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from lumen_ingestion import normalize_evidence
from lumen_ingestion.capture import CaptureOutcome, build_evidence
from lumen_ingestion.capture.snapshot import Download, SiteSnapshot, Stylesheet

HOME = "https://brand.example/"
PRODUCT = "https://brand.example/products/console?edition=team"
HOME_TIME = "2026-09-19T10:00:00Z"
PRODUCT_TIME = "2026-09-20T11:00:00Z"


def _download(url, body, kind="image", content_type="image/svg+xml"):
    return Download(
        url=url,
        kind=kind,
        content_type=content_type,
        bytes_b64=base64.b64encode(body).decode(),
        sha256=hashlib.sha256(body).hexdigest(),
    )


def _svg(color):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
        f'<rect width="640" height="360" fill="{color}"/></svg>'
    ).encode()


def _snapshot(url, downloads=(), *, html="", css="", fetched_at=HOME_TIME):
    return SiteSnapshot(
        requested_url=url,
        final_url=url,
        fetched_at=fetched_at,
        tier="static",
        html=(
            "<html><head><title>Brand</title></head><body><main><section>"
            "<h1>Source brand</h1><p>Tools for practical teams.</p>"
            + html
            + "</section></main></body></html>"
        ),
        stylesheets=[Stylesheet(url=url + "style.css", text=css)],
        downloads=list(downloads),
    )


def _outcome(home, *pages):
    return CaptureOutcome(
        snapshot=home,
        snapshots=[home, *pages],
        tier="static",
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
        library_capture=True,
    )


class _CoreSink:
    def __init__(self, refused=()):
        self.calls = []
        self.refused = set(refused)

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["source"].get("url") in self.refused:
            return {"ok": False, "error": {"code": "asset.refused", "message": "bad bytes"}}
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _build(outcome, tmp_path, core=None):
    sink = core or _CoreSink()
    evidence = build_evidence(
        outcome, core=sink, store_root=str(tmp_path), reporter=lambda *_: None
    )
    return evidence, sink


def test_supporting_images_and_fonts_keep_exact_asset_source_and_capture_time(tmp_path):
    image_url = "https://cdn.brand.example/console.svg?width=1280&v=2"
    font_url = "https://cdn.brand.example/product.woff2"
    home = _snapshot(HOME)
    product = _snapshot(
        PRODUCT,
        [
            _download(image_url, _svg("blue")),
            _download(font_url, b"wOF2-test-supporting-font", "font", "font/woff2"),
        ],
        html=f'<img src="{image_url}" width="640" height="360">',
        fetched_at=PRODUCT_TIME,
    )
    _, sink = _build(_outcome(home, product), tmp_path)
    by_url = {call["source"]["url"]: call for call in sink.calls}
    assert set(by_url) == {image_url, font_url}
    for url, call in by_url.items():
        assert call["source"] == {"kind": "website", "url": url, "captured_at": PRODUCT_TIME}
        assert call["provenance"]["created_at"] == PRODUCT_TIME
        assert any(PRODUCT in note for note in call["provenance"]["notes"])
    assert by_url[font_url]["kind"] == "font"


def test_shared_bytes_ingest_once_with_homepage_source_precedence(tmp_path):
    body = _svg("green")
    supporting_body = _svg("purple")
    home_url = "https://brand.example/identity.svg"
    alias_url = "https://cdn.brand.example/shared.svg?cached=1"
    support_url = "https://brand.example/product-only.svg"
    home = _snapshot(HOME, [_download(home_url, body)])
    product = _snapshot(
        PRODUCT,
        [_download(alias_url, body), _download(support_url, supporting_body)],
        fetched_at=PRODUCT_TIME,
    )
    third = _snapshot(
        "https://brand.example/customers",
        [
            _download(alias_url, body),
            _download("https://cdn.brand.example/product-alias.svg", supporting_body),
        ],
    )
    _, sink = _build(_outcome(home, product, third), tmp_path)
    assert len(sink.calls) == 2
    by_url = {call["source"]["url"]: call for call in sink.calls}
    assert set(by_url) == {home_url, support_url}
    assert by_url[home_url]["source"]["captured_at"] == HOME_TIME
    assert by_url[support_url]["source"]["captured_at"] == PRODUCT_TIME


def test_supporting_pages_do_not_change_homepage_evidence_or_normalized_kit(tmp_path):
    home = _snapshot(HOME, css=":root { --brand-primary: #123456; }")
    product = _snapshot(
        PRODUCT,
        [_download("https://brand.example/other.svg", _svg("red"))],
        html='<header><img alt="Different logo" src="/other.svg"></header>',
        css=":root { --brand-primary: #ff0000; } h1 { font-family: Different; }",
    )
    before, _ = _build(_outcome(home), tmp_path)
    after, _ = _build(_outcome(home, product), tmp_path)
    assert after.model_dump() == before.model_dump()
    options = {
        "brand_kit_id": "brand_test",
        "version": 1,
        "name": "Brand",
        "created_at": "2026-09-20",
    }
    assert (
        normalize_evidence(after, **options).brand_kit
        == normalize_evidence(before, **options).brand_kit
    )


def test_supporting_video_is_not_ingested_as_an_image(tmp_path):
    video = _download("https://brand.example/demo.mp4", b"video-bytes", "video", "video/mp4")
    product = _snapshot(PRODUCT, [video], html='<video src="/demo.mp4"></video>')
    _, sink = _build(_outcome(_snapshot(HOME), product), tmp_path)
    assert sink.calls == []


def test_supporting_missing_and_refused_assets_keep_named_diagnostics(tmp_path):
    missing_url = "https://brand.example/missing.svg"
    refused_url = "https://brand.example/refused.svg"
    product = _snapshot(
        PRODUCT,
        [_download(refused_url, _svg("red"))],
        html=f'<img src="{missing_url}" width="640" height="360">',
    )
    product.diagnostics = [{"url": missing_url, "reason": "HTTP 404", "code": "LUMI0500"}]
    outcome = _outcome(_snapshot(HOME), product)
    _build(outcome, tmp_path, _CoreSink(refused=[refused_url]))
    by_url = {row.get("url"): row for row in outcome.diagnostics if row["code"] == "LUMI0515"}
    assert by_url[missing_url]["reason"] == "HTTP 404"
    assert by_url[refused_url]["reason"] == "bad bytes"


@pytest.mark.parametrize("invalid", ["empty", "base64", "digest"])
def test_supporting_invalid_bytes_are_reported_without_aborting_other_assets(tmp_path, invalid):
    empty_url = "https://brand.example/empty.svg"
    good_url = "https://brand.example/good.svg"
    broken = _download(empty_url, b"")
    if invalid == "base64":
        broken.bytes_b64 = "%%not-base64%%"
    elif invalid == "digest":
        broken.bytes_b64 = base64.b64encode(_svg("red")).decode()
    product = _snapshot(PRODUCT, [broken, _download(good_url, _svg("blue"))])
    outcome = _outcome(_snapshot(HOME), product)
    _, sink = _build(outcome, tmp_path)
    assert [call["source"]["url"] for call in sink.calls] == [good_url]
    assert any(
        row.get("url") == empty_url and row["code"] == "LUMI0515" for row in outcome.diagnostics
    )


def test_pipeline_registers_supporting_media_for_agent_search(
    tmp_path,
    workspace_id,
    design_storage,
    monkeypatch,
):
    """Real ingestion/engine/storage/search seams; only network capture is a fixture."""
    import json
    from dataclasses import replace
    from pathlib import Path

    from lumen_agent.config import AgentRuntimeConfig
    from lumen_agent.tools.web_substrate import LumenWebTools
    from lumen_api.design_store import DesignBlobStore, HybridRepository
    from lumen_api.main import workspace_asset_library_manifest
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.pipeline import run_website_ingestion
    from py_lumen_config import settings

    for field in (
        "lumen_ingestion_describe",
        "lumen_ingestion_brief",
        "lumen_ingestion_assist",
        "lumen_ingestion_vision",
    ):
        monkeypatch.setattr(settings, field, False)
    image_url = "https://brand.example/support-console.svg?version=2"
    body = _svg("#123456")
    product = _snapshot(
        PRODUCT,
        [_download(image_url, body)],
        html=f'<img src="{image_url}" width="640" height="360">',
        fetched_at=PRODUCT_TIME,
    )

    async def capture(url, *, reporter, force_render, page_urls=None, discover_pages=False):
        assert url == HOME and force_render and discover_pages
        return _outcome(_snapshot(HOME), product)

    store = IngestionJobStore(workspace_id=workspace_id)
    job_id = store.create("website", {"url": HOME, "discover_pages": True})["job_id"]
    run_website_ingestion(
        str(tmp_path / "engine"),
        job_id,
        capture=capture,
        workspace_id=workspace_id,
        storage=design_storage,
    )
    job = store.require(job_id)
    assert job["status"] == "succeeded", job
    repo = HybridRepository(workspace_id=workspace_id)
    manifest = workspace_asset_library_manifest(repo)
    assert len(manifest) == 1
    asset_id, entry = next(iter(manifest.items()))
    record = entry["record"]
    assert record["source"] == {"kind": "website", "url": image_url, "captured_at": PRODUCT_TIME}
    assert record["kind"] == "vector"
    assert (
        DesignBlobStore(design_storage, workspace_id).read(record["media"]["digest"]["value"])
        == body
    )
    config = replace(
        AgentRuntimeConfig.from_env(Path(__file__).resolve().parents[3]),
        trace_dir=tmp_path / "agent",
        asset_store_root=tmp_path / "engine",
        asset_library=manifest,
    )
    tools = LumenWebTools(
        config,
        "Find captured product media",
        initial_web_doc={
            "schema_version": 1,
            "id": "web_support_search",
            "title": "Asset search",
            "theme": {},
            "custom_css": "",
            "assets": {},
            "pages": [
                {
                    "id": "home",
                    "name": "Home",
                    "route": "/",
                    "root": "root",
                    "nodes": {
                        "root": {"id": "root", "kind": "container", "classes": "", "new_tab": False}
                    },
                }
            ],
        },
    )
    results = json.loads(tools.search_assets("support-console", kind="image"))
    assert [row["asset_id"] for row in results["results"]] == [asset_id]
