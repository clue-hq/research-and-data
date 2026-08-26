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


def test_a_persistence_failure_is_a_loud_diagnostic_and_keeps_the_ingestion(
    workspace_id: str,
) -> None:
    from lumen_ingestion import pipeline

    class ExplodingStorage:
        async def exists(self, key: str) -> bool:
            raise RuntimeError("object store is on fire")

        async def put(self, key: str, data: bytes, *, media_type: str) -> None:
            raise RuntimeError("object store is on fire")

        async def get(self, key: str) -> bytes:
            raise RuntimeError("object store is on fire")

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

    def __init__(self, snapshots: list[SiteSnapshot]) -> None:
        self.snapshots = snapshots
        self.snapshot = snapshots[0]
        self.tier = snapshots[0].tier
        self.escalated = False
        self.escalation_reason: Any = None
        self.diagnostics: list[dict] = []
