"""Route + pipeline tests for the website ingestion path (slice 1 §10, Agent B).

No network, no playwright. The capture package and evidence-builder are stubbed
via an injected ``run_website_ingestion`` that hands the pipeline a fake async
``capture`` and a ``build_evidence`` returning a real ``BrandEvidence`` loaded
from the slice-0 fixture. SSRF tests exercise Agent A's real async
``guard_url``.

TestClient runs FastAPI ``BackgroundTasks`` synchronously after the response is
returned, so the POST returns a queued job but by the time the call unblocks the
background ingestion has already run — GET then reflects the terminal state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, wait_for_ingestion_job

from clue_design.envelopes import DesignIngestionEnvelope

from lumen_api import main as main_module
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.pipeline import run_website_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion"
REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


def _load_evidence() -> BrandEvidence:
    data = json.loads((FIXTURES / "evidence_website_insight.json").read_text())
    return BrandEvidence.model_validate(data)


@dataclass
class FakeCaptureOutcome:
    """CaptureOutcome-shaped stand-in (§1). The pipeline only reads
    ``diagnostics`` off it; the rest is passed opaquely to build_evidence."""

    tier: str = "static"
    escalated: bool = False
    escalation_reason: Optional[str] = None
    diagnostics: list[dict] = field(
        default_factory=lambda: [
            {"code": "LUMI0504", "severity": "info", "message": "image cap applied"}
        ]
    )


def _install_stub_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capture: Callable[..., Any],
    build_evidence: Optional[Callable[..., Any]] = None,
) -> list[list[tuple[str, float]]]:
    """Rebind main's ``run_website_ingestion`` so the background task runs the
    real pipeline but with injected capture/build_evidence stubs. Returns a list
    that will collect the reporter stage calls seen by build_evidence."""
    reporter_calls: list[list[tuple[str, float]]] = []

    def _build_evidence(outcome, *, core, store_root, reporter):
        seen: list[tuple[str, float]] = []
        reporter_calls.append(seen)
        reporter("Capturing your colors…", 0.65)
        seen.append(("Capturing your colors…", 0.65))
        return _load_evidence()

    def _runner(
        engine_cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None
    ):
        run_website_ingestion(
            engine_cache_dir,
            job_id,
            capture=capture,
            build_evidence=build_evidence or _build_evidence,
            # D2.3: the dispatcher hands the worker the job's workspace so the kit it
            # publishes satisfies the job's composite result FK. D5 Round C: it arrives from
            # the job's frozen envelope and is required, not defaulted.
            workspace_id=workspace_id,
            # D4: and its byte backend, so custody lands where the app can read it.
            storage=storage,
            # D5 Round C: the claiming worker's lease generation (fences a taken-over attempt).
            expected_generation=expected_generation,
        )

    monkeypatch.setattr(main_module, "run_website_ingestion", _runner)
    return reporter_calls


def _bypass_ssrf_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the resolved guard with a no-op async pass-through so the happy-
    path fixtures can use unresolvable ``.example`` hostnames. SSRF tests use
    the real guard instead (they do not call this)."""

    async def _passthrough(url: str) -> str:
        return url

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: _passthrough)


def _read_brand_kit_row(client: TestClient, brand_kit_id: str) -> dict:
    """Read the persisted brand_kits row (incl. raw brand_summary_json) directly
    from the app's sqlite DB — the kit-detail dto does not surface the full
    brand_summary."""

    return HybridRepository().require_brand_kit(brand_kit_id)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def test_ingest_website_happy_path_persists_kit_and_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        assert discover_pages is True
        reporter("Visiting your website…", 0.05)
        return FakeCaptureOutcome()

    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=fake_capture)

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example", "name": "Insight Health"},
    )
    assert post.status_code == 200, post.text
    body = post.json()
    assert body["schema_version"] == 1
    job = body["job"]
    assert job["kind"] == "website"
    # `queued` OR `running`: the POST re-reads the job after create-and-offer, and the
    # embedded fleet worker (0.1s poll) may already have claimed it — a pure scheduling race,
    # and both are snapshots of a successfully-created job (D5: `queued` is alive, not idle).
    assert job["status"] in {"queued", "running"}, job
    job_id = job["job_id"]

    wait_for_ingestion_job(client, job_id)
    got = client.get(f"/brand-kits/ingest/{job_id}")
    assert got.status_code == 200, got.text
    got_job = got.json()["job"]
    assert got_job["status"] == "succeeded", got_job
    brand_kit_id = got_job["brand_kit_id"]
    assert brand_kit_id is not None
    assert got_job["brand_kit_version"] == 1
    assert got_job["error"] is None
    # Public dto carries no request/evidence bodies.
    assert "request" not in got_job
    assert "evidence" not in got_job

    kit = client.get(f"/brand-kits/{brand_kit_id}")
    assert kit.status_code == 200, kit.text
    kit_body = kit.json()
    assert kit_body["brand_kit"]["id"] == brand_kit_id
    assert kit_body["brand_kit"]["source"] == "website"

    # brand_summary_json must carry the ingestion report under key "ingestion"
    # (§9.5). The kit-detail dto flattens the summary, so read the persisted
    # row directly to assert the raw shape.
    record = _read_brand_kit_row(client, brand_kit_id)
    summary = record["brand_summary"]
    assert "ingestion" in summary, summary.keys()
    report = summary["ingestion"]
    assert report["schema_version"] == 1
    assert report["source"]["kind"] == "website"
    assert report["dark_colorway"] == "synthesized"


def test_reingest_existing_website_kit_publishes_a_new_approved_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slice 4: a client-supplied existing kit id means NEXT version, not a doomed
    create-at-version-1 collision. Both extractions are approved without a browser mutation."""

    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        return FakeCaptureOutcome()

    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=fake_capture)

    first = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert first.status_code == 200, first.text
    first_job_id = first.json()["job"]["job_id"]
    first_job = wait_for_ingestion_job(client, first_job_id)
    assert first_job["status"] == "succeeded", first_job
    brand_kit_id = first_job["brand_kit_id"]
    assert first_job["brand_kit_version"] == 1

    first_record = _read_brand_kit_row(client, brand_kit_id)
    assert first_record["approval_status"] == "approved"
    assert first_record["brand_kit"]["approval_status"] == "approved"
    assert first_record["brand_summary"]["approval_status"] == "approved"

    second = client.post(
        "/brand-kits/ingest/website",
        json={
            "url": "https://www.insighthealth.example",
            "brand_kit_id": brand_kit_id,
        },
    )
    assert second.status_code == 200, second.text
    second_job = wait_for_ingestion_job(client, second.json()["job"]["job_id"])
    assert second_job["status"] == "succeeded", second_job
    assert second_job["brand_kit_id"] == brand_kit_id
    assert second_job["brand_kit_version"] == 2

    latest = client.get(f"/brand-kits/{brand_kit_id}")
    assert latest.status_code == 200, latest.text
    assert latest.json()["brand_kit"]["version"] == 2
    assert latest.json()["brand_kit"]["approval_status"] == "approved"
    versions = [
        row["version"]
        for row in HybridRepository().list_brand_kits(all_versions=True)
        if row["brand_kit_id"] == brand_kit_id
    ]
    assert versions == [2, 1]


def test_ingested_kit_attaches_to_document(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        return FakeCaptureOutcome()

    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=fake_capture)

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    got_job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got_job["status"] == "succeeded", got_job
    brand_kit_id = got_job["brand_kit_id"]
    assert brand_kit_id is not None

    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    doc = client.post("/documents", json={"title": "Ingest DoD", "scene": scene})
    assert doc.status_code == 200, doc.text
    document_id = doc.json()["document"]["id"]

    attached = client.post(
        f"/documents/{document_id}/brand-kit",
        json={"brand_kit_id": brand_kit_id, "version": 1},
    )
    assert attached.status_code == 200, attached.text
    loaded = client.get(f"/documents/{document_id}").json()
    assert loaded["scene"]["meta"]["brand_kit"] == {
        "id": brand_kit_id,
        "version": 1,
    }


def test_capture_failure_marks_job_failed_no_kit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        raise RuntimeError("capture exploded")

    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=boom_capture)

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert post.status_code == 200, post.text
    job = post.json()["job"]
    # `queued` OR `running`: the POST re-reads the job after create-and-offer, and the
    # embedded fleet worker (0.1s poll) may already have claimed it — a pure scheduling race,
    # and both are snapshots of a successfully-created job (D5: `queued` is alive, not idle).
    assert job["status"] in {"queued", "running"}, job
    job_id = job["job_id"]

    wait_for_ingestion_job(client, job_id)
    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "failed", got
    assert got["brand_kit_id"] is None
    assert got["error"] is not None
    assert "capture exploded" in got["error"]["message"]

    # No kit row was created.
    kits = client.get("/brand-kits").json()
    assert all(k.get("source") != "website" for k in kits)


def test_stage_progression_reaches_preparing_before_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        reporter("Visiting your website…", 0.05)
        return FakeCaptureOutcome()

    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=fake_capture)

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]

    wait_for_ingestion_job(client, job_id)
    got = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert got["status"] == "succeeded"
    # The pipeline's final reporter stage before persist is the "Preparing…"
    # stage at progress 0.85; complete() bumps progress to 1 but leaves stage.
    assert got["stage"] == "Preparing your brand kit…"
    assert got["progress"] == 1


# --- the rendered tier is not negotiable (founder ruling 2026-08-20) ------------------------- #
#
# Website ingestion ALWAYS captures at the rendered tier: measured geometry and the brief's
# screenshots exist only there, and the static→rendered quality gate escalates on evidence
# POVERTY, so a well-server-rendered site never escalated and published kits with no geometry
# and no brief. The ruling is "geometry needs a live page by definition", so the rule is
# enforced SERVER-SIDE at the pipeline — a client that sends no flag, or sends the flag set to
# false, must still get a rendered capture.


def _capture_recording_force_render(seen: dict) -> Callable[..., Any]:
    async def fake_capture(
        url, *, reporter, force_render=False, page_urls=None, discover_pages=False,
    ):
        seen["force_render"] = force_render
        reporter("Visiting your website…", 0.05)
        return FakeCaptureOutcome(tier="rendered")

    return fake_capture


def test_website_ingestion_renders_even_though_the_request_asked_for_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}
    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=_capture_recording_force_render(seen))

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert post.status_code == 200, post.text
    job = wait_for_ingestion_job(client, post.json()["job"]["job_id"])
    assert job["status"] == "succeeded", job
    assert seen["force_render"] is True


def test_website_ingestion_renders_even_when_the_request_says_force_render_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request field is redundant-but-harmless — it cannot turn rendering OFF."""
    seen: dict = {}
    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=_capture_recording_force_render(seen))

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example", "force_render": False},
    )
    assert post.status_code == 200, post.text
    job = wait_for_ingestion_job(client, post.json()["job"]["job_id"])
    assert job["status"] == "succeeded", job
    assert seen["force_render"] is True


def test_the_fleet_worker_entry_renders_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule holds at the WORKER entry, not just behind the HTTP route.

    ``execute_ingestion_job`` is what the embedded (and detached) fleet worker actually calls,
    so it is driven here directly from a frozen envelope — the route only offers the job. A
    rule enforced at the route would be invisible to a replayed or re-offered envelope.
    """
    from lumen_api.main import execute_ingestion_job

    seen: dict = {}
    _bypass_ssrf_guard(monkeypatch)
    _install_stub_pipeline(monkeypatch, capture=_capture_recording_force_render(seen))

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.example"},
    )
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    seen.clear()

    state = client.app.state
    envelope = DesignIngestionEnvelope(
        kind="ingestion",
        work_id=uuid4(),
        workspace_id=HybridRepository().workspace_id,
        job_id=job_id,
        ingestion_kind="website",
    )
    status = execute_ingestion_job(
        envelope,
        host=SimpleNamespace(
            storage=state.storage, engine_cache_root=state.engine_cache_root
        ),
    )
    assert status == "succeeded", status
    assert seen["force_render"] is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "file:///etc/passwd",
        "http://user:pass@example.com",
        "http://localhost",
    ],
)
def test_ssrf_guard_rejects_dangerous_urls(client: TestClient, url: str) -> None:
    resp = client.post("/brand-kits/ingest/website", json={"url": url})
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "LUMI0501"


def test_route_ordering_ingest_not_captured_as_kit_id(
    client: TestClient,
) -> None:
    # GET /brand-kits/ingest/{job_id} for an unknown id must hit the ingestion
    # not-found path (distinct code), NOT the kit-detail 404.
    resp = client.get("/brand-kits/ingest/ingest_does_not_exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "ingestion_job.not_found"


@pytest.mark.skipif(
    os.environ.get("LUMEN_INGESTION_LIVE_E2E") != "1",
    reason="live e2e disabled (set LUMEN_INGESTION_LIVE_E2E=1)",
)
def test_live_e2e_ingests_real_site(client: TestClient) -> None:
    import time

    post = client.post(
        "/brand-kits/ingest/website",
        json={"url": "https://www.insighthealth.ai"},
    )
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        wait_for_ingestion_job(client, job_id)
        job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
        status = job["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(2)
    assert status == "succeeded", job
    kit = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert kit["brand_kit"]["source"] == "website"
    assert kit["brand_kit"]["approval_status"] == "approved"
    colors = kit["brand_kit_json"]["tokens"]["colors"]
    assert "surface.brand" in colors and "text.primary" in colors


def test_explicit_supporting_pages_are_guarded_before_any_job_is_queued(client, monkeypatch):
    from lumen_ingestion.capture.net import CaptureError

    calls = []

    async def guard(url):
        calls.append(url)
        if url == "http://127.0.0.1/private":
            raise CaptureError("LUMI0501", "blocked private address")
        return url

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: guard)
    response = client.post(
        "/brand-kits/ingest/website",
        json={
            "url": "https://example.com/",
            "page_urls": ["http://127.0.0.1/private"],
        },
    )
    assert response.status_code == 422
    assert calls == ["https://example.com/", "http://127.0.0.1/private"]
