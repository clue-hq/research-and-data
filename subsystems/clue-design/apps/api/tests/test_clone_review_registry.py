"""The gate's two DB-backed seams: the durable verdict, and the reference review (F3.3, D-F6/7).

The behavioural walk itself is browserless and lives in ``test_clone_review_gate.py``. What is
pinned HERE is everything that touches the database:

* ``mark_degraded`` — the gate's ONE durable write. Narrow by construction: only the gate's own
  reason codes, only ON, and never at a model's word.
* ``reference_review`` — the comparison against F0's persisted capture, found through the pinned
  fragments' own mint provenance, plus the blind side-by-side composed from the two pictures.
* the advice-only carve-out at the seam that matters: a clone the gate marked broken is still
  pinnable and still publishes. The gate reports; it does not refuse.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F2.3 neighbour.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore
from lumen_api.fragments import (
    SlotSpec,
    create_web_fragment,
    read_web_fragment,
    set_web_fragment_status,
)
from lumen_api.fragments.degraded import (
    DEGRADED_REASON_BLANK_RENDER,
    DEGRADED_REASON_DEAD_HEIGHT,
    DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
)
from lumen_ingestion.jobs import IngestionJobStore
from lumen_ingestion.site_snapshot import persist_site_snapshots

SOURCE_URL = "https://insight.example/"
HERO_HTML = (
    '<section class="hero"><h1 class="head">Care, on your terms</h1>'
    '<a class="cta" href="https://insight.example/demo">Book a demo</a></section>'
)
HERO_CSS = ".hero { padding: 64px }"
PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"


def _grey_png(width: int, height: int, fill: int = 255) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("L", (width, height), fill).save(buffer, format="PNG")
    return buffer.getvalue()


class _Download:
    url = f"{SOURCE_URL}#screenshot"
    kind = "screenshot"
    content_type = "image/png"

    def __init__(self, data: bytes) -> None:
        self.bytes_b64 = base64.b64encode(data).decode("ascii")


class _Snapshot:
    """The shape ``persist_site_snapshots`` reads — a stand-in for one captured page."""

    def __init__(self, screenshot: bytes | None, *, viewport: int = 1440) -> None:
        self.requested_url = SOURCE_URL
        self.final_url = SOURCE_URL
        self.html = "<html><body>the client's real page</body></html>"
        self.stylesheets: list[Any] = []
        self.downloads = [_Download(screenshot)] if screenshot else []
        self.geometry = {"viewport": viewport, "sections": []}
        self.meta = {"title": "Insight"}
        self.tier = "rendered"
        self.fetched_at = "2026-08-28T00:00:00+00:00"


def _mint(
    workspace_id: str,
    storage: FsStorage,
    *,
    html: str = HERO_HTML,
    provenance: dict | None = None,
    approved: bool = True,
) -> dict:
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=HERO_CSS,
        rehosted={},
        source_url=SOURCE_URL,
        section_role="hero",
        label="Hero",
        slots=(SlotSpec(selector=".head", key="headline", kind="text"),),
        preview=PNG,
        provenance=provenance or {"page_url": SOURCE_URL},
    )
    if approved:
        row = set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
        )
    return row


def _registry(workspace_id: str, storage: FsStorage, cache_dir) -> DurableAgentClonedSectionRegistry:
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


# --- the durable verdict ---------------------------------------------------------------------


def test_the_gate_records_a_measured_verdict_with_its_own_reason_code(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    updated = registry.mark_degraded(
        row["fragment_id"], reason=DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    )

    assert updated["degraded"] is True
    assert updated["degraded_reason"] == DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    # ...and it is on the row, not merely in the return value.
    assert (
        read_web_fragment(design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"])
        is not None
    )
    listed = registry.list_sections()["sections"]
    assert listed[0]["degraded"] is True
    assert listed[0]["degraded_reason"] == DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    assert "the page we actually render" in listed[0]["degraded_note"]


def test_the_gate_cannot_write_the_mint_detectors_reason(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The other half of the reason-code split: the gate may not borrow ``dead_height``.

    If it could, the mint-time reconciler would re-measure that code from a fresh capture of the
    SOURCE site and clear a verdict about how OUR page renders — which it never looked at.
    """
    row = _mint(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(ValueError) as excinfo:
        registry.mark_degraded(row["fragment_id"], reason=DEGRADED_REASON_DEAD_HEIGHT)
    assert "belongs to another producer" in str(excinfo.value)
    assert (
        registry.list_sections()["sections"][0]["degraded"] is False
    )  # nothing was written


def test_a_clone_the_gate_marked_broken_still_pins_so_no_finding_blocks_a_publish(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The advice-only carve-out, at the seam a publish actually asks.

    D-F6 keeps the degraded original approved and pinnable while it is the only thing that
    exists; the gate's verdict is evidence for the repair ladder, never a refusal in front of the
    page.
    """
    row = _mint(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    registry.mark_degraded(row["fragment_id"], reason=DEGRADED_REASON_BLANK_RENDER)

    # The gate asked for permission the way a document write asks for it. It is GRANTED — the
    # refusal path raises, and nothing here raises.
    resolved = registry.resolve_insertable(row["fragment_id"])

    assert resolved["fragment_id"] == row["fragment_id"]
    assert resolved["render"]["html"]
    # ...and the pin carries the finding with it, which is what makes it advice rather than
    # silence: the author is told the band is broken at the moment it goes on the page.
    assert resolved["degraded"] is True
    assert resolved["degraded_reason"] == DEGRADED_REASON_BLANK_RENDER
    assert "shows nothing at all" in resolved["degraded_note"]


# --- the reference review --------------------------------------------------------------------


def _persist_reference(
    workspace_id: str, storage: FsStorage, *, screenshot: bytes | None
) -> str:
    # A real ingestion job: `design_site_snapshot` carries a composite FK to it, which is the
    # point — a reference capture belongs to the walk that made it.
    job_id = IngestionJobStore(workspace_id=workspace_id).create(
        "website", {"url": SOURCE_URL}
    )["job_id"]
    refs = persist_site_snapshots(
        [_Snapshot(screenshot)], workspace_id=workspace_id, job_id=job_id, storage=storage
    )
    return refs[0].snapshot_id


def test_the_review_finds_the_reference_through_the_fragments_own_provenance(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    reference = _grey_png(1440, 2000)
    snapshot_id = _persist_reference(workspace_id, design_storage, screenshot=reference)
    row = _mint(
        workspace_id,
        design_storage,
        provenance={
            "page_url": SOURCE_URL,
            "snapshot_id": snapshot_id,
            "viewport_width": 1440,
            "section_index": 0,
            "geometry": {"top_px": 0, "bottom_px": 800, "basis": "measured"},
        },
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    review = registry.reference_review(
        [row["fragment_id"]],
        capture_png=_grey_png(1440, 2000),
        rendered_bands=[
            {"fragment_id": row["fragment_id"], "top_px": 0.0, "height_px": 800.0}
        ],
    )

    assert review["status"] == "ok"
    assert review["snapshot_id"] == snapshot_id
    assert review["page_url"] == SOURCE_URL
    band = review["comparison"]["bands"][0]
    assert band["fragment_id"] == row["fragment_id"]
    assert band["height_ratio"] == 1.0
    assert band["drifted"] is False
    # The blind artifact rides along, key sealed to the image it answers for.
    assert review["blind_key"]["artifact_sha256"] == hashlib.sha256(
        review["blind_png"]
    ).hexdigest()
    assert set(review["blind_key"]["panels"]) == {"A", "B"}


def test_a_capture_that_never_took_a_screenshot_is_named_rather_than_papered_over(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    snapshot_id = _persist_reference(workspace_id, design_storage, screenshot=None)
    row = _mint(
        workspace_id,
        design_storage,
        provenance={
            "page_url": SOURCE_URL,
            "snapshot_id": snapshot_id,
            "viewport_width": 1440,
            "geometry": {"top_px": 0, "bottom_px": 800, "basis": "measured"},
        },
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    review = registry.reference_review(
        [row["fragment_id"]], capture_png=_grey_png(1440, 2000)
    )

    assert review["status"] == "unavailable"
    assert review["because"] == "no_reference_screenshot"
    assert "blind_png" not in review


def test_clones_that_predate_snapshot_custody_say_so(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, provenance={"page_url": SOURCE_URL})
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    review = registry.reference_review(
        [row["fragment_id"]], capture_png=_grey_png(1440, 2000)
    )

    assert review == {"status": "unavailable", "because": "no_snapshot_provenance"}


def test_a_snapshot_row_that_is_gone_refuses_rather_than_raising(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(
        workspace_id,
        design_storage,
        provenance={"page_url": SOURCE_URL, "snapshot_id": "snap_deadbeefdeadbeef"},
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    review = registry.reference_review(
        [row["fragment_id"]], capture_png=_grey_png(1440, 2000)
    )

    assert review == {"status": "unavailable", "because": "snapshot_missing"}
