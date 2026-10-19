"""Site-snapshot persistence (clone-fidelity F0.1) + the multi-page provision (F0.4).

Every website ingestion now gives its capture DURABLE custody: the post-JS HTML, every fetched
stylesheet and the full-page screenshot land in the design blob namespace, and one
``design_site_snapshot`` row per captured page records the digests. Before this, the snapshot
died in memory the moment ``build_evidence`` had read what it wanted.

These tests are DB-backed (the row store is Postgres) and use the suite's per-test workspace +
disposable ``FsStorage``, exactly like the neighbouring ingestion suites.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from clue_design.storage import DESIGN_KEY_SEGMENT
from clue_storage import FsStorage

from lumen_api.design_store import DesignBlobStore
from lumen_ingestion.capture.snapshot import Download, SiteSnapshot, Stylesheet
from lumen_ingestion.jobs import IngestionJobStore
from lumen_ingestion.site_snapshot import (
    SITE_SNAPSHOT_SOURCE_KEY,
    SNAPSHOT_PERSIST_FAILED_CODE,
    SiteSnapshotRef,
    list_site_snapshot_refs,
    persist_site_snapshots,
    read_site_snapshot,
    site_snapshot_id,
)

HTML = "<html><head><title>Insight</title></head><body><h1>Hello</h1></body></html>"
CSS_A = "body{color:#123456}"
CSS_B = "h1{font-size:32px}"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(
    url: str = "https://insighthealth.example/",
    *,
    tier: str = "rendered",
    with_screenshot: bool = True,
    html: str = HTML,
) -> SiteSnapshot:
    downloads = []
    if with_screenshot:
        downloads.append(
            Download(
                url=f"{url}#screenshot",
                kind="screenshot",
                content_type="image/png",
                bytes_b64=base64.b64encode(PNG).decode("ascii"),
                sha256=_sha(PNG),
            )
        )
    return SiteSnapshot(
        requested_url=url,
        final_url=url,
        fetched_at="2026-08-27T10:00:00+00:00",
        tier=tier,  # type: ignore[arg-type]
        html=html,
        stylesheets=[
            Stylesheet(url=f"{url}a.css", text=CSS_A),
            Stylesheet(url=f"{url}b.css", text=CSS_B),
        ],
        geometry={"viewport": 1440} if tier == "rendered" else None,
        downloads=downloads,
        meta={"title": "Insight", "og:title": "Insight Health"},
    )


def _job(workspace_id: str, url: str = "https://insighthealth.example/") -> str:
    return IngestionJobStore(workspace_id=workspace_id).create("website", {"url": url})["job_id"]


# --------------------------------------------------------------------------- #
# F0.1 — persistence + round trip
# --------------------------------------------------------------------------- #


def test_persisting_a_snapshot_writes_one_row_four_blobs_and_round_trips(
    workspace_id: str, design_storage: FsStorage
) -> None:
    job_id = _job(workspace_id)
    snapshot = _snapshot()
    snapshot.geometry.update(initial_font_px=18, root_font_px=9)

    refs = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )

    assert len(refs) == 1
    ref = refs[0]
    assert isinstance(ref, SiteSnapshotRef)
    assert ref.snapshot_id == site_snapshot_id(job_id, snapshot.requested_url)
    assert ref.page_url == snapshot.requested_url
    assert ref.page_index == 0
    # Digests are the content addresses of the exact bytes captured.
    assert ref.html_digest == _sha(HTML.encode("utf-8"))
    assert list(ref.stylesheet_digests) == [
        _sha(CSS_A.encode("utf-8")),
        _sha(CSS_B.encode("utf-8")),
    ]
    assert ref.screenshot_digest == _sha(PNG)

    # ONE row for this job.
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=job_id) == refs

    # FOUR blobs: html + 2 stylesheets + screenshot, each live in this workspace.
    blobs = DesignBlobStore(design_storage, workspace_id)
    digests = [ref.html_digest, *ref.stylesheet_digests, ref.screenshot_digest]
    assert len(set(digests)) == 4
    for digest in digests:
        assert blobs.exists(digest), digest

    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=ref.snapshot_id
    )
    assert loaded.html == HTML
    assert [sheet.url for sheet in loaded.stylesheets] == [
        f"{snapshot.requested_url}a.css",
        f"{snapshot.requested_url}b.css",
    ]
    assert [sheet.text for sheet in loaded.stylesheets] == [CSS_A, CSS_B]
    assert loaded.screenshot == PNG
    assert loaded.viewport_width == 1440
    assert loaded.page_url == snapshot.requested_url
    assert loaded.meta["meta"]["title"] == "Insight"
    assert loaded.meta["final_url"] == snapshot.final_url
    assert loaded.meta["tier"] == "rendered"
    assert loaded.meta["font_context"] == {"initial_font_px": 18, "root_font_px": 9}


def test_static_tier_snapshot_has_no_screenshot_and_no_phantom_blob(
    workspace_id: str, design_storage: FsStorage
) -> None:
    job_id = _job(workspace_id)
    snapshot = _snapshot(tier="static", with_screenshot=False)

    (ref,) = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )

    assert ref.screenshot_digest is None
    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=ref.snapshot_id
    )
    assert loaded.screenshot is None
    assert loaded.viewport_width is None
    # Exactly three artifact rows were written for this snapshot — html + two stylesheets.
    blobs = DesignBlobStore(design_storage, workspace_id)
    assert [blobs.exists(d) for d in (ref.html_digest, *ref.stylesheet_digests)] == [True] * 3


def test_two_pages_of_one_job_get_their_own_rows_and_page_indexes(
    workspace_id: str, design_storage: FsStorage
) -> None:
    job_id = _job(workspace_id)
    home = _snapshot("https://insighthealth.example/")
    about = _snapshot("https://insighthealth.example/about", html=HTML.replace("Hello", "About"))

    refs = persist_site_snapshots(
        [home, about], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )

    assert [r.page_index for r in refs] == [0, 1]
    assert [r.page_url for r in refs] == [home.requested_url, about.requested_url]
    assert refs[0].snapshot_id != refs[1].snapshot_id
    assert refs[0].html_digest != refs[1].html_digest
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=job_id) == refs


def test_one_page_per_job_is_structural_not_conventional(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """UNIQUE (job_id, page_url): a second row for the same page is refused by the database.

    Persisting the SAME job+page again converges (the id is content-derived from both), so the
    only way to reach the constraint is a hand-built second id — which is exactly what a future
    caller that mints ids its own way would do, and it must fail loudly rather than double-count.
    """
    from clue_design import site_snapshots as dal
    from lumen_api.design_store import DesignStoreBridge

    job_id = _job(workspace_id)
    snapshot = _snapshot()
    persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )
    # Same job + page, converges on the same row rather than raising.
    again = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )
    assert len(list_site_snapshot_refs(workspace_id=workspace_id, job_id=job_id)) == 1
    assert again[0].snapshot_id == site_snapshot_id(job_id, snapshot.requested_url)

    bridge = DesignStoreBridge(workspace_id)
    with pytest.raises(Exception) as excinfo:
        bridge._run(
            lambda conn: dal.upsert_site_snapshot(
                conn,
                workspace_id=workspace_id,
                snapshot_id="snap_deadbeefdeadbeef",
                job_id=job_id,
                page_url=snapshot.requested_url,
                page_index=1,
                html_digest="0" * 64,
                stylesheets=[],
                screenshot_digest=None,
                viewport_width=None,
                captured_at=snapshot.fetched_at,
                meta={},
            )
        )
    assert "design_site_snapshot_job_page_unique" in str(excinfo.value)


def test_deleting_a_job_that_captured_pages_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The job FK is ON DELETE RESTRICT: clone source outlives the job that fetched it.

    A snapshot row is what phase F2 harvests sections out of — durable brand source, not the
    ingestion job's bookkeeping. Cascading would let any future job pruner destroy it as a side
    effect nobody saw. RESTRICT keeps the reference honest AND makes that pruner fail loudly,
    which is the whole point: a pruner that really wants these rows gone deletes them itself,
    on purpose.
    """
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    job_id = _job(workspace_id)
    persist_site_snapshots(
        [_snapshot()], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )

    with pytest.raises(Exception) as excinfo:
        DesignStoreBridge(workspace_id)._run(
            lambda conn: conn.execute(
                text("DELETE FROM design_ingestion_job WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        )
    assert "design_site_snapshot_job_fk" in str(excinfo.value)
    # The job is still there, and so is what it captured.
    assert len(list_site_snapshot_refs(workspace_id=workspace_id, job_id=job_id)) == 1


def test_re_ingesting_identical_content_dedups_bytes_and_writes_a_new_row(
    workspace_id: str, design_storage: FsStorage
) -> None:
    snapshot = _snapshot()
    first_job = _job(workspace_id)
    second_job = _job(workspace_id)

    (first,) = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=first_job, storage=design_storage
    )
    (second,) = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=second_job, storage=design_storage
    )

    # Content addressing: identical bytes, identical digests — one blob, two citers.
    assert first.html_digest == second.html_digest
    assert first.stylesheet_digests == second.stylesheet_digests
    assert first.screenshot_digest == second.screenshot_digest
    # A new job is a new row, keyed to its own job.
    assert first.snapshot_id != second.snapshot_id
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=first_job) == [first]
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=second_job) == [second]


def test_reading_another_workspaces_snapshot_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    job_id = _job(workspace_id)
    (ref,) = persist_site_snapshots(
        [_snapshot()], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )
    from lumen_api.database import NotFoundError

    with pytest.raises(NotFoundError):
        read_site_snapshot(
            design_storage,
            workspace_id=f"{workspace_id}_other",
            snapshot_id=ref.snapshot_id,
        )


# --------------------------------------------------------------------------- #
# F0.1 — the pipeline wrapper: loud, never fatal
# --------------------------------------------------------------------------- #


class ExplodingStorage:
    """A byte backend that is having a bad day, for every call."""

    async def exists(self, key: str) -> bool:
        raise RuntimeError("object store is on fire")

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        raise RuntimeError("object store is on fire")

    async def get(self, key: str) -> bytes:
        raise RuntimeError("object store is on fire")

    async def delete(self, key: str) -> None:
        raise RuntimeError("object store is on fire")


class DeadDesignBlobStorage:
    """:class:`ExplodingStorage`, but only for the DESIGN blob namespace.

    A globally dead store cannot express ruling 5's promise, and finding that out is worth
    recording rather than working around: the governed publish tool snapshots its own parameters
    to storage (``clue_execution.parameters`` → the toolbelt host's ``persist``) under the
    claim-evidence key shape ``{ws}/{sha}``, so a backend that fails EVERY put fails the kit
    publish too. That is a real failure, and a genuinely fatal one — but it is a different
    failure from the one this test is about.

    Failing only ``{ws}/design/{sha}`` isolates exactly the byte path snapshot custody uses. In
    this test nothing else writes design bytes at all (``build_evidence`` is stubbed, so the
    capture layer ingests no assets), so this is precisely "snapshot custody could not write".
    """

    def __init__(self, inner: FsStorage) -> None:
        self._inner = inner

    @staticmethod
    def _dead(key: str) -> bool:
        return f"/{DESIGN_KEY_SEGMENT}/" in key

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        if self._dead(key):
            raise RuntimeError("object store is on fire")
        await self._inner.put(key, data, media_type=media_type)

    async def get(self, key: str) -> bytes:
        if self._dead(key):
            raise RuntimeError("object store is on fire")
        return await self._inner.get(key)

    async def delete(self, key: str) -> None:
        if self._dead(key):
            raise RuntimeError("object store is on fire")
        await self._inner.delete(key)

    async def exists(self, key: str) -> bool:
        if self._dead(key):
            raise RuntimeError("object store is on fire")
        return await self._inner.exists(key)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return await self._inner.presign(key, expires_in=expires_in)

    def list_blobs(self):
        return self._inner.list_blobs()


def test_a_persistence_failure_is_a_loud_diagnostic_and_keeps_the_ingestion(
    workspace_id: str,
) -> None:
    from lumen_ingestion import pipeline

    job_id = _job(workspace_id)
    outcome = _FakeOutcome([_snapshot()])
    diagnostics: list[dict] = []

    refs = pipeline._persist_site_snapshots(
        outcome,
        workspace_id=workspace_id,
        job_id=job_id,
        storage=ExplodingStorage(),
        diagnostics=diagnostics,
    )

    assert refs == []
    assert [d["code"] for d in diagnostics] == [SNAPSHOT_PERSIST_FAILED_CODE]
    assert diagnostics[0]["severity"] == "error"
    assert "on fire" in diagnostics[0]["message"]
    # Row before blob, in ONE transaction: a failed put leaves no row claiming those bytes.
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=job_id) == []


def test_the_snapshot_source_key_is_its_own(workspace_id: str, design_storage: FsStorage) -> None:
    """Blobs written by this seam are labelled ``design_site_snapshot`` on the artifact row."""
    from clue_design.storage import design_storage_key
    from clue_storage.artifacts import get_artifact
    from lumen_api.design_store import DesignStoreBridge

    job_id = _job(workspace_id)
    (ref,) = persist_site_snapshots(
        [_snapshot()], workspace_id=workspace_id, job_id=job_id, storage=design_storage
    )
    record = DesignStoreBridge(workspace_id)._run(
        lambda conn: get_artifact(conn, design_storage_key(workspace_id, ref.html_digest))
    )
    assert record is not None
    assert record.source_key == SITE_SNAPSHOT_SOURCE_KEY
    assert SITE_SNAPSHOT_SOURCE_KEY == "design_site_snapshot"


class _FakeOutcome:
    """CaptureOutcome-shaped stand-in carrying the snapshots the pipeline persists."""

    def __init__(self, snapshots: list[SiteSnapshot], diagnostics: list[dict] | None = None) -> None:
        self.snapshots = snapshots
        self.snapshot = snapshots[0]
        self.tier = snapshots[0].tier
        self.escalated = False
        self.escalation_reason: Any = None
        self.diagnostics: list[dict] = diagnostics or []


# --------------------------------------------------------------------------- #
# The whole website lane, end to end — capture stubbed, everything else real
# --------------------------------------------------------------------------- #


def _load_evidence() -> Any:
    import json
    from pathlib import Path

    from lumen_ingestion.evidence import BrandEvidence

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"
    )
    return BrandEvidence.model_validate(json.loads(fixture.read_text()))


def _run_website_ingestion(
    workspace_id: str,
    design_storage: FsStorage,
    tmp_path: Any,
    outcome: _FakeOutcome,
) -> dict:
    """One real ``run_website_ingestion`` with only capture + evidence stubbed."""
    from lumen_ingestion.pipeline import run_website_ingestion

    store = IngestionJobStore(workspace_id=workspace_id)
    job_id = store.create("website", {"url": "https://insighthealth.example/"})["job_id"]

    async def _capture(url, *, reporter, force_render=False, page_urls=None):
        reporter("Visiting your website…", 0.05)
        return outcome

    def _build_evidence(outcome_, *, core, store_root, reporter):
        return _load_evidence()

    run_website_ingestion(
        str(tmp_path / "engine-cache"),
        job_id,
        capture=_capture,
        build_evidence=_build_evidence,
        workspace_id=workspace_id,
        storage=design_storage,
    )
    return store.require(job_id)


def test_a_website_ingestion_leaves_its_capture_durable_and_named_on_the_job(
    workspace_id: str, design_storage: FsStorage, tmp_path: Any
) -> None:
    snapshot = _snapshot()
    job = _run_website_ingestion(
        workspace_id, design_storage, tmp_path, _FakeOutcome([snapshot])
    )

    assert job["status"] == "succeeded", job
    refs = list_site_snapshot_refs(workspace_id=workspace_id, job_id=job["job_id"])
    assert len(refs) == 1
    assert refs[0].html_digest == _sha(HTML.encode("utf-8"))

    # Readable from the job itself, not only from the snapshot table.
    on_job = job["evidence"]["site_snapshots"]
    assert on_job == [
        {
            "snapshot_id": refs[0].snapshot_id,
            "page_url": snapshot.requested_url,
            "html_digest": refs[0].html_digest,
            "screenshot_digest": refs[0].screenshot_digest,
        }
    ]
    # The bytes really are there: the round trip goes through durable custody, not memory.
    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=refs[0].snapshot_id
    )
    assert loaded.html == HTML


def test_a_non_entry_page_that_failed_to_capture_costs_a_page_not_the_job(
    workspace_id: str, design_storage: FsStorage, tmp_path: Any
) -> None:
    """The F0.4 partial-capture contract, as the pipeline sees it.

    ``capture_website`` already dropped the page that could not be fetched and left a LUMI0513
    behind (see ``test_ingestion_capture``); what this asserts is the rest of the promise — the
    entry page is still persisted, the diagnostic reaches the published kit, and the job is
    green.
    """
    from lumen_api.design_store import HybridRepository

    failure = {
        "code": "LUMI0513",
        "severity": "warning",
        "message": "page capture failed for https://insighthealth.example/about",
    }
    job = _run_website_ingestion(
        workspace_id,
        design_storage,
        tmp_path,
        _FakeOutcome([_snapshot()], diagnostics=[failure]),
    )

    assert job["status"] == "succeeded", job
    refs = list_site_snapshot_refs(workspace_id=workspace_id, job_id=job["job_id"])
    assert [r.page_url for r in refs] == ["https://insighthealth.example/"]

    kit = HybridRepository(workspace_id=workspace_id).require_brand_kit(
        job["brand_kit_id"], job["brand_kit_version"]
    )
    assert any(d["code"] == "LUMI0513" for d in kit["diagnostics"]), kit["diagnostics"]


def test_a_dead_byte_store_costs_the_snapshots_and_nothing_else(
    workspace_id: str, design_storage: FsStorage, tmp_path: Any
) -> None:
    """The whole of ruling 5, at the level it is actually promised: the JOB.

    ``_persist_site_snapshots`` returning a diagnostic is only half of "loud, never fatal" —
    the other half is that the diagnostic reaches somewhere a human reads, and that the job
    keeps the result it had already produced. Both are asserted here against a real
    ``run_website_ingestion`` whose byte backend fails every call:

    * the job SUCCEEDS and still carries its evidence — the kit is the ingestion's product and
      a byte-store outage after the evidence was built must not throw it away;
    * ``LUMI0512`` is on the PUBLISHED KIT's diagnostics, which is the surface the checklist and
      the review UI read. Nothing else in the suite covers that wiring: deleting
      ``+ snapshot_diagnostics`` from the pipeline's diagnostics fold leaves every other test
      in this file green (verified by reverting the line and watching only this test fail).
    """
    from lumen_api.design_store import HybridRepository

    job = _run_website_ingestion(
        workspace_id,
        DeadDesignBlobStorage(design_storage),  # type: ignore[arg-type]
        tmp_path,
        _FakeOutcome([_snapshot()]),
    )

    assert job["status"] == "succeeded", job
    assert job["evidence"] is not None
    assert job["evidence"]["site_snapshots"] == []
    assert list_site_snapshot_refs(workspace_id=workspace_id, job_id=job["job_id"]) == []

    kit = HybridRepository(workspace_id=workspace_id).require_brand_kit(
        job["brand_kit_id"], job["brand_kit_version"]
    )
    loud = [d for d in kit["diagnostics"] if d["code"] == SNAPSHOT_PERSIST_FAILED_CODE]
    assert len(loud) == 1, kit["diagnostics"]
    assert loud[0]["severity"] == "error"
    assert "not durable" in loud[0]["message"]


def test_snapshot_keeps_unminted_media_dependencies_in_durable_custody(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """A refused section must not discard its source video or prevent a later repair."""
    from lumen_api.fragments.refs import asset_url

    snapshot = _snapshot()
    video = b"\x1a\x45\xdf\xa3original-video"
    snapshot.downloads.append(
        Download(
            url="https://cdn.example/hero.webm",
            kind="video",
            content_type="video/webm",
            bytes_b64=base64.b64encode(video).decode(),
            sha256=_sha(video),
            origin="video",
        )
    )
    snapshot.downloads.append(
        Download(
            url="https://cdn.example/customer.png?width=640",
            kind="image",
            content_type="image/png",
            bytes_b64=base64.b64encode(PNG).decode(),
            sha256=_sha(PNG),
            origin="img",
        )
    )
    (ref,) = persist_site_snapshots(
        [snapshot], workspace_id=workspace_id, job_id=_job(workspace_id), storage=design_storage
    )
    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=ref.snapshot_id
    )
    assets = {item["url"]: item for item in loaded.meta["assets"]}
    assert assets["https://cdn.example/hero.webm"]["digest"] == _sha(video)
    assert assets["https://cdn.example/hero.webm"]["kind"] == "video"
    assert assets["https://cdn.example/customer.png?width=640"]["digest"] == _sha(PNG)
    blobs = DesignBlobStore(design_storage, workspace_id)
    assert blobs.read(_sha(video)) == video
    assert asset_url(_sha(video)) == f"/asset-store/{_sha(video)}"


def test_motion_inventory_is_durable_without_claiming_canvas_runtime(
    workspace_id: str,
    design_storage: FsStorage,
) -> None:
    snapshot = _snapshot(
        html='<html><body><canvas></canvas><video src="/hero.webm"></video></body></html>'
    )
    snapshot.stylesheets.append(
        Stylesheet(
            url="https://insighthealth.example/motion.css", text="@keyframes fade {to {opacity: 1}}"
        )
    )
    (ref,) = persist_site_snapshots(
        [snapshot],
        workspace_id=workspace_id,
        job_id=_job(workspace_id),
        storage=design_storage,
    )
    loaded = read_site_snapshot(
        design_storage, workspace_id=workspace_id, snapshot_id=ref.snapshot_id
    )
    assert loaded.meta["motion"]["css_keyframes"] == ["fade"]
    assert loaded.meta["motion"]["canvas_runtime_recovered"] is False
    assert loaded.meta["motion"]["missing_video_assets"] == [
        "https://insighthealth.example/hero.webm"
    ]
