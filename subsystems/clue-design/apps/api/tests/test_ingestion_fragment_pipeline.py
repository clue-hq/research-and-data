"""Fragment minting where it becomes durable (clone-fidelity F2.2).

Three things, all of which need a database:

* the mint stage inside the website ingestion job — the fragments a real capture leaves behind,
  bound to the brand kit that same job published;
* the human gate — minting happens against the DRAFT kit, and the EXISTING brand-context
  approval flow is what flips that kit version's fragments to ``approved``, in one transaction;
* the document-write reference gate's new half — a NEW pin needs an approved fragment, while a
  pin that is already there stays loadable and renderable no matter what its status became.

``test_ingestion_section_mint.py`` holds the pure halves (rule matching, slot detection, the
reference harvest, preview crops) with the durable seams injected.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.database import FragmentReferenceError
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import list_web_fragments, read_web_fragment, set_web_fragment_status
from lumen_ingestion.sections.mint import (
    CapturedAsset,
    make_asset_rehoster,
    make_fragment_writer,
    mint_sections,
)
from lumen_ingestion.sections.segment import segment_page

PAGE_URL = "https://insight.example/"
HERO_JPG = "https://insight.example/img/hero.jpg"

PAGE_HTML = (
    "<html><body>"
    '<header class="nav_component"><a href="/">Home</a><a href="/pricing">Pricing</a></header>'
    '<main><section class="section_home-hero">'
    '<h1 class="heading-xl">Care, on your terms</h1>'
    '<p class="body-copy">We help teams ship.</p>'
    '<img src="/img/hero.jpg" alt="hero">'
    '<a class="button" href="/demo"><span class="button_label">Book a demo</span></a>'
    "</section>"
    '<section class="section_proof"><p>Trusted by 400 clinics</p></section></main>'
    '<footer class="footer_component"><p>&copy; 2026 Insight</p></footer>'
    "</body></html>"
)

STYLESHEET_TEXT = (
    ":root { --brand: #123456 }\n"
    ".heading-xl { font-size: 4rem; color: var(--brand) }\n"
    ".section_home-hero { padding: 6rem 0; background-image: url(/img/hero.jpg) }\n"
    ".nav_component { display: flex }\n"
    ".footer_component { padding: 2rem }\n"
    ".pricing_table { display: grid }\n"
    "@font-face { font-family: Inter; src: url(/fonts/inter.woff2) }\n"
)

BANDS = [
    {"index": 0, "tag": "section", "id": "", "classes": "section_home-hero", "top": 80.0,
     "height": 600.0, "bgImage": True},
    {"index": 1, "tag": "section", "id": "", "classes": "section_proof", "top": 680.0,
     "height": 300.0, "bgImage": False},
]


class _Sheet:
    def __init__(self, url: str, text: str) -> None:
        self.url = url
        self.text = text


def _png(width: int, height: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _segmentation():
    from lumen_ingestion.sections.bands import measured_bands

    return segment_page(
        PAGE_HTML,
        page_url=PAGE_URL,
        bands=measured_bands({"bands": BANDS}),
        viewport_width=1200,
        snapshot_id="snap_abc123",
    )


def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_ing_1") -> dict[str, Any]:
    repo = HybridRepository(workspace_id=workspace_id)
    return repo.create_brand_kit(
        {"id": kit_id, "version": 1, "name": "Insight", "approval_status": "draft"},
        {},
        [],
        "website",
    )


def _mint(
    workspace_id: str,
    storage: FsStorage,
    *,
    kit: dict[str, Any] | None = None,
    screenshot: bytes | None = None,
    stylesheets=None,
    captured=None,
    limit: int = 12,
):
    blobs = DesignBlobStore(storage, workspace_id)
    return mint_sections(
        _segmentation(),
        html=PAGE_HTML,
        stylesheets=stylesheets if stylesheets is not None else [_Sheet("/s.css", STYLESHEET_TEXT)],
        captured=captured
        if captured is not None
        else {
            HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"hero-jpeg-bytes", content_type="image/jpeg"),
            "https://insight.example/fonts/inter.woff2": CapturedAsset(
                url="https://insight.example/fonts/inter.woff2",
                data=b"woff2-bytes",
                content_type="font/woff2",
            ),
        },
        screenshot=screenshot,
        source_kit_id=None if kit is None else kit["brand_kit_id"],
        source_kit_version=None if kit is None else int(kit["version"]),
        register_bytes=make_asset_rehoster(blobs),
        create_fragment=make_fragment_writer(storage, workspace_id=workspace_id),
        limit=limit,
    )


# --------------------------------------------------------------------------- #
# Minting, for real
# --------------------------------------------------------------------------- #


def test_a_captured_page_leaves_real_fragment_rows_bound_to_its_kit(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    outcome = _mint(workspace_id, design_storage, kit=kit, screenshot=_png(1200, 1400))

    rows = list_web_fragments(workspace_id=workspace_id)
    assert {row["section_role"] for row in rows} == {"nav", "hero", "proof", "footer"}
    assert all(row["source_kit_id"] == kit["brand_kit_id"] for row in rows)
    assert all(row["source_kit_version"] == 1 for row in rows)
    assert all(row["status"] == "draft" for row in rows)
    assert {minted.fragment_id for minted in outcome.minted} == {row["fragment_id"] for row in rows}



def test_sections_arriving_after_kit_approval_are_released_and_replay_keeps_retirements(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    first = _mint(workspace_id, design_storage, kit=kit)
    assert all(row["status"] == "approved" for row in list_web_fragments(workspace_id=workspace_id))
    retired = first.minted[0].fragment_id
    set_web_fragment_status(workspace_id=workspace_id, fragment_id=retired, status="deprecated")
    _mint(workspace_id, design_storage, kit=kit)
    rows = {row["fragment_id"]: row["status"] for row in list_web_fragments(workspace_id=workspace_id)}
    assert rows[retired] == "deprecated"
    assert all(status == "approved" for fid, status in rows.items() if fid != retired)


def test_newer_kit_approval_does_not_release_sections_bound_to_an_older_draft(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {**kit["brand_kit"], "version": 2, "approval_status": "approved"}, {}, [], "website"
    )
    _mint(workspace_id, design_storage, kit=kit)
    rows = list_web_fragments(workspace_id=workspace_id)
    assert rows
    assert all(row["status"] == "draft" and row["source_kit_version"] == 1 for row in rows)

def test_a_minted_fragment_reads_back_as_a_self_contained_clone(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    outcome = _mint(workspace_id, design_storage, kit=kit, screenshot=_png(1200, 1400))
    hero = next(minted for minted in outcome.minted if minted.role == "hero")

    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=hero.fragment_id
    )
    # Every byte it displays is ours, named by digest — nothing points at the source site.
    assert "insight.example" not in loaded.html
    assert "/asset-store/" in loaded.html
    assert loaded.asset_digests
    # Its rules came with it, scoped, and the page's unrelated rules did not.
    assert ".lumen-frag-" in loaded.css
    assert "pricing_table" not in loaded.css
    assert "--brand" in loaded.css  # :root re-anchored onto the wrapper
    assert "@font-face" in loaded.css
    # And it is editable.
    assert {"headline", "body", "cta_href", "cta_label", "image", "visible"} <= set(
        loaded.slot_manifest
    )


def test_the_bytes_a_minted_fragment_names_are_actually_in_custody(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """A digest with no blob behind it is a fragment that renders a hole — the exact failure
    the reference gate exists to prevent, arriving one layer later."""
    kit = _seed_kit(workspace_id)
    outcome = _mint(workspace_id, design_storage, kit=kit, screenshot=_png(1200, 1400))
    hero = next(minted for minted in outcome.minted if minted.role == "hero")
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=hero.fragment_id
    )
    blobs = DesignBlobStore(design_storage, workspace_id)
    for digest in loaded.asset_digests:
        assert blobs.read(digest)
    assert blobs.read(hero.preview_digest)


def test_re_minting_the_same_page_converges_on_the_same_rows(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    first = _mint(workspace_id, design_storage, kit=kit, screenshot=_png(1200, 1400))
    second = _mint(workspace_id, design_storage, kit=kit, screenshot=_png(1200, 1400))
    assert [m.fragment_id for m in first.minted] == [m.fragment_id for m in second.minted]
    assert len(list_web_fragments(workspace_id=workspace_id)) == len(first.minted)


def test_a_fragment_may_be_minted_from_a_page_that_never_became_a_kit(
    workspace_id: str, design_storage: FsStorage
) -> None:
    outcome = _mint(workspace_id, design_storage, kit=None)
    assert outcome.minted
    assert all(row["source_kit_id"] is None for row in list_web_fragments(workspace_id=workspace_id))


# --------------------------------------------------------------------------- #
# The human gate: fragments ride the kit approval surface
# --------------------------------------------------------------------------- #


def test_approving_the_kit_approves_the_fragments_minted_against_it(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    _mint(workspace_id, design_storage, kit=kit)
    assert all(row["status"] == "draft" for row in list_web_fragments(workspace_id=workspace_id))

    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    assert all(row["status"] == "approved" for row in list_web_fragments(workspace_id=workspace_id))


def test_reverting_the_kit_to_draft_takes_its_fragments_back_with_it(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    _mint(workspace_id, design_storage, kit=kit)
    repo = HybridRepository(workspace_id=workspace_id)
    repo.update_brand_kit_approval(kit["brand_kit_id"], "approved")
    repo.update_brand_kit_approval(kit["brand_kit_id"], "draft")
    assert all(row["status"] == "draft" for row in list_web_fragments(workspace_id=workspace_id))


def test_a_deprecated_fragment_is_not_dragged_back_by_a_kit_approval(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Deprecation is a decision about ONE section. Approving the kit is a decision about the
    kit, and it must not quietly undo the narrower one."""
    kit = _seed_kit(workspace_id)
    outcome = _mint(workspace_id, design_storage, kit=kit)
    retired = outcome.minted[0].fragment_id
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=retired, status="deprecated"
    )
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    rows = {row["fragment_id"]: row["status"] for row in list_web_fragments(workspace_id=workspace_id)}
    assert rows[retired] == "deprecated"
    assert all(status == "approved" for fid, status in rows.items() if fid != retired)


def test_approving_one_kit_does_not_approve_another_kits_fragments(
    workspace_id: str, design_storage: FsStorage
) -> None:
    mine = _seed_kit(workspace_id, "brand_kit_mine")
    theirs = _seed_kit(workspace_id, "brand_kit_theirs")
    _mint(workspace_id, design_storage, kit=mine)
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        theirs["brand_kit_id"], "approved"
    )
    assert all(row["status"] == "draft" for row in list_web_fragments(workspace_id=workspace_id))


def test_a_fragment_bound_to_no_kit_is_never_swept_up_by_an_approval(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    _mint(workspace_id, design_storage, kit=None)
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    assert all(row["status"] == "draft" for row in list_web_fragments(workspace_id=workspace_id))


def test_the_kit_approval_route_flips_the_fragments_too(
    tmp_path, workspace_id: str, design_storage: FsStorage
) -> None:
    """Ride the SURFACE, not a private helper: this is the flow a human actually uses, and it
    goes through the governed ``design_set_brand_kit_approval`` tool rather than the DAL."""
    from conftest import make_client
    from lumen_api.main import create_app

    kit = _seed_kit(workspace_id)
    _mint(workspace_id, design_storage, kit=kit)
    client = make_client(create_app(tmp_path / "engine-cache"))
    response = client.post(
        f"/brand-kits/{kit['brand_kit_id']}/approval", json={"approval_status": "approved"}
    )
    assert response.status_code == 200, response.text
    assert all(row["status"] == "approved" for row in list_web_fragments(workspace_id=workspace_id))


# --------------------------------------------------------------------------- #
# The reference gate's new half: a NEW pin needs an approved fragment
# --------------------------------------------------------------------------- #


def _web_doc(*pins: tuple[str, str]) -> dict[str, Any]:
    """A web document pinning ``(node_id, fragment_id)`` — the shape ``fragment_nodes`` reads."""
    nodes: dict[str, Any] = {
        "root": {"id": "root", "kind": "container", "children": [node_id for node_id, _ in pins]}
    }
    for node_id, fragment_id in pins:
        nodes[node_id] = {"id": node_id, "kind": "fragment", "fragment_id": fragment_id}
    return {
        "schema_version": 1,
        "id": "doc_gate",
        "title": "T",
        "pages": [
            {"id": "page_1", "name": "Home", "route": "/", "root": "root", "nodes": nodes}
        ],
        "assets": {},
        "custom_css": "",
    }


def test_a_new_pin_to_a_draft_fragment_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    repo = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.validate_fragment_reference_changes(
            before_web_doc={}, after_web_doc=_web_doc(("n1", minted.fragment_id))
        )
    assert excinfo.value.code == "fragment.not_approved"
    assert minted.fragment_id in str(excinfo.value)


def test_the_same_pin_is_allowed_once_a_human_approves_the_kit(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    repo = HybridRepository(workspace_id=workspace_id)
    repo.update_brand_kit_approval(kit["brand_kit_id"], "approved")
    repo.validate_fragment_reference_changes(
        before_web_doc={}, after_web_doc=_web_doc(("n1", minted.fragment_id))
    )


def test_a_deprecated_fragment_cannot_be_newly_pinned(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    repo = HybridRepository(workspace_id=workspace_id)
    repo.update_brand_kit_approval(kit["brand_kit_id"], "approved")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=minted.fragment_id, status="deprecated"
    )
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.validate_fragment_reference_changes(
            before_web_doc={}, after_web_doc=_web_doc(("n1", minted.fragment_id))
        )
    assert excinfo.value.code == "fragment.not_approved"


def test_a_pin_that_is_already_there_survives_its_fragment_being_un_approved(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Fail-soft render, unchanged: a document that already pins a fragment stays loadable and
    editable when the fragment is deprecated or reverted to draft. Losing the ability to edit a
    page's TITLE because somebody retired one section of it would be absurd."""
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    repo = HybridRepository(workspace_id=workspace_id)
    repo.update_brand_kit_approval(kit["brand_kit_id"], "approved")
    pinned = _web_doc(("n1", minted.fragment_id))

    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=minted.fragment_id, status="deprecated"
    )
    repo.validate_fragment_reference_changes(before_web_doc=pinned, after_web_doc=pinned)

    # ...but a SECOND node on the same dead pin is a new reference, and it is refused.
    with pytest.raises(FragmentReferenceError):
        repo.validate_fragment_reference_changes(
            before_web_doc=pinned,
            after_web_doc=_web_doc(("n1", minted.fragment_id), ("n2", minted.fragment_id)),
        )


def test_an_unknown_fragment_still_refuses_as_unresolved_not_as_unapproved(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The two refusals need different repairs — mint it, versus approve it — so they keep
    different codes."""
    repo = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.validate_fragment_reference_changes(
            before_web_doc={}, after_web_doc=_web_doc(("n1", "frag_0123456789abcdef"))
        )
    assert excinfo.value.code == "fragment.unresolved"


# --------------------------------------------------------------------------- #
# The pipeline stage
# --------------------------------------------------------------------------- #


def test_the_website_ingestion_job_mints_the_sections_it_captured(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The whole stage, driven from the pipeline's own entry point with only capture and
    evidence stubbed, so the wiring — which page, which kit, which diagnostics — is pinned
    rather than assumed."""
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.pipeline import run_website_ingestion

    store = IngestionJobStore(workspace_id=workspace_id)
    job_id = store.create("website", {"url": PAGE_URL})["job_id"]

    async def _capture(url, *, reporter, force_render=False, page_urls=None):
        reporter("Visiting your website…", 0.05)
        return _FakeOutcome([_snapshot()])

    run_website_ingestion(
        str(tmp_path / "engine-cache"),
        job_id,
        capture=_capture,
        build_evidence=lambda outcome_, *, core, store_root, reporter: _load_evidence(),
        workspace_id=workspace_id,
        storage=design_storage,
    )

    job = store.require(job_id)
    assert job["status"] == "succeeded", job
    rows = list_web_fragments(workspace_id=workspace_id)
    assert {row["section_role"] for row in rows} >= {"nav", "hero", "footer"}
    assert all(row["status"] == "approved" for row in rows)
    assert all(row["source_kit_id"] == job["brand_kit_id"] for row in rows)
    assert all(row["source_kit_version"] == job["brand_kit_version"] for row in rows)
    # And the job itself says what it cloned, so "what did this ingestion keep?" is answerable
    # from the job row rather than only by querying the registry.
    on_job = job["evidence"]["web_fragments"]
    assert {ref["role"] for ref in on_job} == {row["section_role"] for row in rows}
    assert all(ref["status"] == "approved" for ref in on_job)


def test_a_page_whose_sections_cannot_be_minted_still_finishes_its_ingestion(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Minting is additive to the ingestion's real product. A capture that references bytes
    nobody fetched must cost diagnostics, never the brand kit."""
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.pipeline import run_website_ingestion

    store = IngestionJobStore(workspace_id=workspace_id)
    job_id = store.create("website", {"url": PAGE_URL})["job_id"]

    async def _capture(url, *, reporter, force_render=False, page_urls=None):
        return _FakeOutcome([_snapshot(downloads=[])])

    run_website_ingestion(
        str(tmp_path / "engine-cache"),
        job_id,
        capture=_capture,
        build_evidence=lambda outcome_, *, core, store_root, reporter: _load_evidence(),
        workspace_id=workspace_id,
        storage=design_storage,
    )
    job = store.require(job_id)
    assert job["status"] == "succeeded", job
    assert job["brand_kit_id"]


# --------------------------------------------------------------------------- #
# capture stand-ins
# --------------------------------------------------------------------------- #


def _load_evidence() -> Any:
    import json
    from pathlib import Path

    from lumen_ingestion.evidence import BrandEvidence

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"
    )
    return BrandEvidence.model_validate(json.loads(fixture.read_text()))


def _snapshot(downloads: list | None = None, url: str = PAGE_URL):
    import hashlib

    from lumen_ingestion.capture.snapshot import Download, SiteSnapshot, Stylesheet

    shot = _png(1200, 1400)
    if downloads is None:
        downloads = [
            Download(
                url=HERO_JPG,
                kind="image",
                content_type="image/jpeg",
                bytes_b64=base64.b64encode(b"hero-jpeg-bytes").decode("ascii"),
                sha256=hashlib.sha256(b"hero-jpeg-bytes").hexdigest(),
            ),
            Download(
                url="https://insight.example/fonts/inter.woff2",
                kind="font",
                content_type="font/woff2",
                bytes_b64=base64.b64encode(b"woff2-bytes").decode("ascii"),
                sha256=hashlib.sha256(b"woff2-bytes").hexdigest(),
            ),
        ]
    downloads = list(downloads) + [
        Download(
            url=f"{url}#screenshot",
            kind="screenshot",
            content_type="image/png",
            bytes_b64=base64.b64encode(shot).decode("ascii"),
            sha256=hashlib.sha256(shot).hexdigest(),
        )
    ]
    return SiteSnapshot(
        requested_url=url,
        final_url=url,
        fetched_at="2026-08-27T10:00:00+00:00",
        tier="rendered",
        html=PAGE_HTML,
        stylesheets=[Stylesheet(url=f"{PAGE_URL}s.css", text=STYLESHEET_TEXT)],
        geometry={"viewport": 1200, "sections": BANDS},
        downloads=downloads,
    )


class _FakeOutcome:
    def __init__(self, snapshots: list, diagnostics: list | None = None) -> None:
        self.snapshots = snapshots
        self.snapshot = snapshots[0]
        self.tier = snapshots[0].tier
        self.escalated = False
        self.escalation_reason: Any = None
        self.diagnostics: list[dict[str, Any]] = diagnostics or []


# --------------------------------------------------------------------------- #
# Fix round 1
# --------------------------------------------------------------------------- #


def test_a_re_mint_under_a_newer_kit_version_moves_the_binding_forward(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """M6. The row is content-addressed, so a re-ingest converges onto the row it already wrote
    — and used to keep that row pointed at the OLD kit version. Approving the NEW kit then
    flipped nothing, and the fragment sat draft forever with no surface that could release it.

    The kit binding is bookkeeping about which capture minted this content, not the content,
    so it moves forward. The payload digest — what the row IS — does not."""
    repo = HybridRepository(workspace_id=workspace_id)
    first_kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=first_kit).minted[0]

    second = repo.create_brand_kit(
        {"id": first_kit["brand_kit_id"], "version": 2, "name": "Insight", "approval_status": "draft"},
        {},
        [],
        "website",
        )
    before = next(
        row for row in list_web_fragments(workspace_id=workspace_id)
        if row["fragment_id"] == minted.fragment_id
    )
    again = _mint(workspace_id, design_storage, kit=second).minted
    assert minted.fragment_id in {m.fragment_id for m in again}

    row = next(
        r for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == minted.fragment_id
    )
    assert row["source_kit_version"] == 2
    assert row["payload_digest"] == before["payload_digest"]

    # And the new kit's approval now reaches it, which is the whole point.
    repo.update_brand_kit_approval(first_kit["brand_kit_id"], "approved")
    row = next(
        r for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == minted.fragment_id
    )
    assert row["status"] == "approved"


def test_a_re_mint_never_drags_a_fragment_back_to_an_older_kit_version(
    workspace_id: str, design_storage: FsStorage
) -> None:
    repo = HybridRepository(workspace_id=workspace_id)
    kit = _seed_kit(workspace_id)
    second = repo.create_brand_kit(
        {"id": kit["brand_kit_id"], "version": 2, "name": "Insight", "approval_status": "draft"},
        {},
        [],
        "website",
    )
    minted = _mint(workspace_id, design_storage, kit=second).minted[0]
    _mint(workspace_id, design_storage, kit=kit)
    row = next(
        r for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == minted.fragment_id
    )
    assert row["source_kit_version"] == 2


def test_a_re_mint_does_not_move_a_fragment_between_kit_lineages(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """A different lineage is a different decision, not a newer version of the same one, and
    silently repointing would hand one brand's approval authority over another's material."""
    mine = _seed_kit(workspace_id, "brand_kit_mine")
    theirs = _seed_kit(workspace_id, "brand_kit_theirs")
    minted = _mint(workspace_id, design_storage, kit=mine).minted[0]
    _mint(workspace_id, design_storage, kit=theirs)
    row = next(
        r for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == minted.fragment_id
    )
    assert row["source_kit_id"] == "brand_kit_mine"


def test_pages_dropped_by_an_exhausted_budget_are_named(
    workspace_id: str, design_storage: FsStorage, monkeypatch
) -> None:
    """I3. The outer loop broke on an exhausted budget and said nothing, so a multi-page walk
    could clone page one and drop pages two and three in silence — the exact silent truncation
    the per-page cap diagnostic exists to prevent, one level up."""
    from lumen_ingestion import pipeline
    from lumen_ingestion.sections import mint as section_mint

    monkeypatch.setattr(section_mint, "SECTION_MINT_CAP", 2)
    kit = _seed_kit(workspace_id)
    blobs = DesignBlobStore(design_storage, workspace_id)
    outcome = _FakeOutcome([_snapshot(), _snapshot(url=PAGE_URL + "pricing")])

    refs, diagnostics = pipeline._mint_page_fragments(
        outcome,
        repo=HybridRepository(workspace_id=workspace_id),
        blobs=blobs,
        brand_kit_id=kit["brand_kit_id"],
        brand_kit_version=int(kit["version"]),
        snapshot_refs=[],
    )
    assert len(refs) == 2
    dropped = [d for d in diagnostics if d["code"] == section_mint.MINT_CAPPED_CODE]
    assert dropped, diagnostics
    assert any(PAGE_URL + "pricing" in str(d) for d in dropped)


# --------------------------------------------------------------------------- #
# I4 — a derivation inherits its source's pins
# --------------------------------------------------------------------------- #


def _approved_fragment(workspace_id: str, design_storage: FsStorage) -> str:
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    return minted.fragment_id


def test_a_derivation_inherits_its_templates_pins_even_when_one_is_retired(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """I4 (RULED). Every per-account derivation calls ``create_document``, which validates with
    an EMPTY before-context — so every pin looks new, and retiring one cloned section would
    fail every derivation of every template that pins it. A derivation does not CHOOSE a
    fragment; it inherits one. Deprecation must block a genuinely new pin, not a copy."""
    repo = HybridRepository(workspace_id=workspace_id)
    fragment_id = _approved_fragment(workspace_id, design_storage)

    source = repo.create_document(
        _doc("doc_src", ("n1", fragment_id)), doc_kind="web"
    )
    template = repo.create_web_template(
        _doc("tpl_1", ("n1", fragment_id)), source_document_id=source["id"]
    )

    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=fragment_id, status="deprecated"
    )

    derived = repo.create_document(
        _doc("doc_acct_1", ("n1", fragment_id)),
        doc_kind="web",
        template_document_id=template["id"],
        template_doc_version=int(template["current_version"]),
    )
    assert derived["id"] == "doc_acct_1"


def test_a_genuinely_new_pin_of_that_same_retired_fragment_is_still_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The other half of the ruling: inheritance is not amnesty."""
    repo = HybridRepository(workspace_id=workspace_id)
    fragment_id = _approved_fragment(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=fragment_id, status="deprecated"
    )
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.create_document(_doc("doc_fresh", ("n1", fragment_id)), doc_kind="web")
    assert excinfo.value.code == "fragment.not_approved"


def test_a_derivation_may_not_smuggle_in_a_pin_its_template_never_had(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Inheritance is bounded by what the source actually pins."""
    repo = HybridRepository(workspace_id=workspace_id)
    inherited = _approved_fragment(workspace_id, design_storage)
    template = repo.create_web_template(_doc("tpl_2", ("n1", inherited)))
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.create_document(
            _doc("doc_smuggle", ("n1", inherited), ("n2", "frag_" + "ab" * 8)),
            doc_kind="web",
            template_document_id=template["id"],
            template_doc_version=int(template["current_version"]),
        )
    assert excinfo.value.code == "fragment.unresolved"


def test_an_inherited_pin_must_still_exist_in_this_workspace(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Inheriting a pin excuses its STATUS, never its existence — a derived document that pins
    a fragment nobody holds renders a hole exactly as a fresh one would."""
    repo = HybridRepository(workspace_id=workspace_id)
    fragment_id = _approved_fragment(workspace_id, design_storage)
    template = repo.create_web_template(_doc("tpl_3", ("n1", fragment_id)))
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    DesignStoreBridge(workspace_id)._run(
        lambda conn: conn.execute(
            text("DELETE FROM design_web_fragment WHERE fragment_id = :f AND workspace_id = :w"),
            {"f": fragment_id, "w": workspace_id},
        )
    )
    with pytest.raises(FragmentReferenceError) as excinfo:
        repo.create_document(
            _doc("doc_gone", ("n1", fragment_id)),
            doc_kind="web",
            template_document_id=template["id"],
            template_doc_version=int(template["current_version"]),
        )
    assert excinfo.value.code == "fragment.unresolved"


def test_saving_a_document_as_a_template_inherits_that_documents_pins(
    workspace_id: str, design_storage: FsStorage
) -> None:
    repo = HybridRepository(workspace_id=workspace_id)
    fragment_id = _approved_fragment(workspace_id, design_storage)
    source = repo.create_document(_doc("doc_live", ("n1", fragment_id)), doc_kind="web")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=fragment_id, status="deprecated"
    )
    template = repo.create_web_template(
        _doc("tpl_from_live", ("n1", fragment_id)), source_document_id=source["id"]
    )
    assert template["id"] == "tpl_from_live"


def _doc(document_id: str, *pins: tuple[str, str]) -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "root": {"id": "root", "kind": "container", "children": [node for node, _ in pins]}
    }
    for node_id, fragment_id in pins:
        nodes[node_id] = {"id": node_id, "kind": "fragment", "fragment_id": fragment_id}
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "T",
        "pages": [{"id": "page_1", "name": "Home", "route": "/", "root": "root", "nodes": nodes}],
        "assets": {},
        "custom_css": "",
    }


@pytest.mark.parametrize("column,value", [("label", "'Renamed'"), ("source_url", "'https://x/'")])
def test_relaxing_the_trigger_for_the_kit_binding_froze_nothing_else(
    workspace_id: str, design_storage: FsStorage, column: str, value: str
) -> None:
    """M6's migration widened the immutability trigger by exactly two columns. Everything that
    defines the artifact is still refused by the DATABASE, not by this module's good manners."""
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    with pytest.raises(Exception) as excinfo:
        DesignStoreBridge(workspace_id)._run(
            lambda conn: conn.execute(
                text(
                    f"UPDATE design_web_fragment SET {column} = {value} "
                    "WHERE fragment_id = :f AND workspace_id = :w"
                ),
                {"f": minted.fragment_id, "w": workspace_id},
            )
        )
    assert "immutable" in str(excinfo.value)


def test_the_row_records_what_was_actually_stored_not_only_what_was_matched(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """W8. A fragment's CSS is scoped under an id derived from its own content, so the stored
    bytes do not exist until the artifact is built — one call after the mint stage assembled its
    provenance. The creation seam knows the answer and stamps it, rather than the producer
    minting twice to measure once."""
    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    row = next(
        r for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == minted.fragment_id
    )
    payload_sizes = row["provenance"]["payload"]
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted.fragment_id
    )
    assert payload_sizes["css_bytes"] == len(loaded.css.encode("utf-8"))
    assert payload_sizes["html_bytes"] == len(loaded.html.encode("utf-8"))
    assert payload_sizes["bytes"] > payload_sizes["css_bytes"]
    # The matched (pre-scope) figure the mint stage recorded is still there, and is a DIFFERENT
    # number — scoping prefixes every selector, so what is stored is larger than what matched.
    assert row["provenance"]["css"]["byte_length"] <= payload_sizes["css_bytes"]


def test_an_unresolvable_pin_tells_the_operator_which_kind_of_broken_it_is(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """W8. "This section cannot be shown" is one sentence to a page and two different repairs to
    whoever maintains the pipeline: a purged blob is a custody problem, an unparseable payload is
    a schema or write problem. The refusal's own code is what separates them."""
    import logging

    from lumen_api.fragments.render import build_fragment_render_package

    # A handler of our own rather than `caplog`: that fixture belongs to pytest's logging
    # plugin, so a gate invoked with `-p no:logging` — a reasonable thing to do when a suite is
    # noisy — turned this test into an ERROR rather than a skip. A test that only runs under one
    # harness flag is a test that quietly stops running.
    captured: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    sink = _Sink(level=logging.WARNING)
    render_logger = logging.getLogger("lumen_api.fragments.render")
    render_logger.addHandler(sink)
    previous_level = render_logger.level
    render_logger.setLevel(logging.WARNING)

    kit = _seed_kit(workspace_id)
    minted = _mint(workspace_id, design_storage, kit=kit).minted[0]
    web_doc = _doc("doc_log", ("n1", minted.fragment_id))

    page = {**web_doc, "pages": [{**web_doc["pages"][0], "id": "home"}]}
    try:
        package = build_fragment_render_package(
            design_storage, workspace_id=workspace_id, web_doc=page, page_id="home"
        )
        assert package["missing"] == []
        assert not captured

        # Now break the custody and look again: the log names the reason, not just the id.
        DesignBlobStore(design_storage, workspace_id).delete(
            next(
                r for r in list_web_fragments(workspace_id=workspace_id)
                if r["fragment_id"] == minted.fragment_id
            )["payload_digest"]
        )
        package = build_fragment_render_package(
            design_storage, workspace_id=workspace_id, web_doc=page, page_id="home"
        )
    finally:
        render_logger.removeHandler(sink)
        render_logger.setLevel(previous_level)

    assert package["missing"] == [minted.fragment_id]
    assert any("reason=fragment." in message for message in captured), captured


# --------------------------------------------------------------------------- #
# A hidden section, all the way to a durable dormant row (clone-fidelity F3.0)
# --------------------------------------------------------------------------- #


HIDDEN_PAGE_HTML = (
    "<html><body><main>"
    '<section class="section_home-hero"><h1 class="heading-xl">Care, on your terms</h1></section>'
    '<section class="section_pricing w-condition-invisible"><h2>Pricing</h2>'
    "<p>From $99 a month.</p></section>"
    '<section class="section_proof"><p>Trusted by 400 clinics</p></section>'
    "</main></body></html>"
)

HIDDEN_PAGE_BANDS = [
    {"index": 0, "tag": "section", "classes": "section_home-hero", "top": 0.0, "height": 600.0},
    {"index": 1, "tag": "section", "classes": "section_proof", "top": 600.0, "height": 300.0},
]


def _mint_hidden_page(workspace_id: str, storage: FsStorage, *, kit: dict[str, Any]):
    from lumen_ingestion.sections.bands import measured_bands

    blobs = DesignBlobStore(storage, workspace_id)
    segmentation = segment_page(
        HIDDEN_PAGE_HTML,
        page_url=PAGE_URL,
        bands=measured_bands({"bands": HIDDEN_PAGE_BANDS}),
        viewport_width=1200,
        snapshot_id="snap_hidden",
    )
    assert len(segmentation.hidden_sections) == 1
    return mint_sections(
        segmentation,
        html=HIDDEN_PAGE_HTML,
        stylesheets=[_Sheet("/s.css", ".section_pricing { display: grid }")],
        captured={},
        screenshot=None,
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
        register_bytes=make_asset_rehoster(blobs),
        create_fragment=make_fragment_writer(storage, workspace_id=workspace_id),
    )


def test_a_hidden_section_becomes_a_real_dormant_row_the_kit_approval_cannot_wake(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The whole D-F8 path through the REAL creation seam, not a stub: a section the site hides is
    minted dormant, its provenance carries the evidence, the human gate steps over it, and the
    document-write gate refuses to pin it. The stubbed mint tests prove the driver's decisions;
    this proves the row those decisions actually produce."""
    kit = _seed_kit(workspace_id)
    outcome = _mint_hidden_page(workspace_id, design_storage, kit=kit)

    dormant = [minted for minted in outcome.minted if minted.hidden_on_source]
    assert [minted.status for minted in dormant] == ["dormant"]

    rows = {row["fragment_id"]: row for row in list_web_fragments(workspace_id=workspace_id)}
    row = rows[dormant[0].fragment_id]
    assert row["status"] == "dormant"
    assert row["degraded"] is False
    assert row["preview_digest"] is None  # never rendered, so never previewed — honestly
    assert row["provenance"]["hidden_on_source"]["hidden"] is True
    assert row["provenance"]["hidden_on_source"]["evidence"]
    # The artifact is a real clone, not a stub: the payload holds the section's own markup.
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=row["fragment_id"]
    )
    assert "From $99 a month." in loaded.html

    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )
    after = {r["fragment_id"]: r["status"] for r in list_web_fragments(workspace_id=workspace_id)}
    assert after[row["fragment_id"]] == "dormant"
    assert all(
        status == "approved"
        for fid, status in after.items()
        if fid != row["fragment_id"]
    )

    store = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError) as excinfo:
        store.create_document(_doc("doc_dormant_e2e", ("n1", row["fragment_id"])), doc_kind="web")
    assert excinfo.value.code == "fragment.not_approved"
