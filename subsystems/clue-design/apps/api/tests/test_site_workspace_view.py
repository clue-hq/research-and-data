"""lumen_api.site_workspace_view: one site turn's inputs from the database (Lane B Task 8)."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from conftest import make_blob_store
from lumen_api import site_workspace_view as view
from lumen_api.fragments.degraded import DEGRADED_REASON_BLANK_RENDER, degraded_headline
from lumen_api.main import create_app


def _frag(name: str) -> str:
    """A real-shaped fragment id (``frag_<16 hex>``, what ``fragment_wrapper_class`` accepts) for ``name``."""
    return "frag_" + hashlib.sha256(name.encode()).hexdigest()[:16]


def test_the_research_account_is_this_documents_artifact() -> None:
    bundle = {"artifacts": [{"document_id": "doc_a", "account_id": "acc_a"},
                            {"document_id": "doc_b", "account_id": "acc_b"}]}
    assert view.research_account_id(bundle, "doc_b") == "acc_b"
    assert view.research_account_id(bundle, "doc_c") is None
    assert view.research_account_id({"artifacts": [{"document_id": "doc_x", "account_id": "acc_x"}]}, "doc_y") == "acc_x"
    assert view.research_account_id({}, "doc_a") is None


def test_the_brief_carries_this_artifact_like_the_spike() -> None:
    bundle = {"brief": "Build a 1:1 page.", "artifact": {"position": 0, "count": 2, "title": "SCSD page", "note": ""}}
    assert view.brief_text(bundle) == (
        'Build a 1:1 page.\n\nTHIS ARTIFACT: {"position": 0, "count": 2, "title": "SCSD page", "note": ""}')
    assert view.brief_text({"brief": "Only a brief."}) == "Only a brief."


def test_research_pages_follow_the_paged_contract_and_a_missing_page_is_an_error_not_a_crash() -> None:
    class Reads:
        def read_account_research(self, *, account_entity_id, section, offset):
            if section == "insights":
                raise RuntimeError("refused:insights_not_written")
            pages = {0: {"overview": [{"section_key": "a"}], "next_offset": 1}, 1: {"overview": [{"section_key": "b"}], "next_offset": None}}
            return pages[offset]

    overview, insights, errors = view.read_research_pages(Reads(), "acc_1")
    assert [s["section_key"] for s in overview] == ["a", "b"] and insights == []
    assert "insights_not_written" in errors["insights"]


def _section(*ids: str) -> dict:
    return {"section_key": "s", "body_text": json.dumps({"h1": "S", "intro": [{"text": "t", "claimIds": list(ids)}]})}


def test_cited_claims_are_read_in_chunks_and_real_holds_are_kept() -> None:
    ids = [f"{n:08d}-0000-5000-8000-000000000000" for n in range(250)]
    asked: list[int] = []

    class Reads:
        def read_cited_claims(self, *, entity_id, claim_ids):
            asked.append(len(claim_ids))
            return {"entity_id": entity_id,
                    "claims": [{"claim_id": claim_ids[0]}],
                    "dispositions": {cid: ("held:outreach_unsafe" if cid == ids[3] else "served") for cid in claim_ids}}

    claims, held = view.cited_claims(Reads(), "acc_1", [_section(*ids)])
    assert asked == [200, 50] and len(claims) == 2 and held == frozenset({ids[3]})


def test_a_failed_cited_read_holds_every_cited_claim() -> None:
    class Reads:
        def read_cited_claims(self, **kwargs):
            raise RuntimeError("read_failed")

    claims, held = view.cited_claims(Reads(), "acc_1", [_section("c1", "c2")])
    assert claims == [] and held == frozenset({"c1", "c2"})


def test_project_files_are_the_pinned_instructions_and_decisions() -> None:
    reads = SimpleNamespace(project_design_context=lambda: {
        "status": "available", "files": [{"path": "instructions.md", "body_text": "Lead with cost."},
                                         {"path": "decisions.md", "body_text": "No video."}]})
    assert view.project_files_from(reads) == [{"path": "instructions.md", "body_text": "Lead with cost."},
                                             {"path": "decisions.md", "body_text": "No video."}]
    assert view.project_files_from(SimpleNamespace(project_design_context=lambda: {"status": "not_pinned", "files": []})) == []


def test_account_logos_are_stored_as_blobs_and_listed_with_their_alternatives(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    light = SimpleNamespace(cell="light_lockup", body=b"<svg viewBox='0 0 1 1'/>", content_type="image/svg+xml", label="Acme")
    other = SimpleNamespace(cell="unclassified", body=b"\x89PNGother", content_type="image/png", label="Acme (site header)")
    asked: list[tuple] = []

    def fetcher(domain, *, company_name, cache):
        asked.append((domain, company_name))
        return SimpleNamespace(prepared=[light], alternatives=[other])

    logos = view.fetch_account_logos(blobs, {"name": "Acme", "domain": "acme.example"}, fetcher=fetcher)
    assert asked == [("acme.example", "Acme")]
    assert [(logo.cell, logo.alternative, logo.label) for logo in logos] == [
        ("light_lockup", False, None), ("unclassified", True, "Acme (site header)")]
    digest = hashlib.sha256(light.body).hexdigest()
    assert logos[0].file == f"/asset-store/{digest}" and blobs.read(digest) == light.body
    assert view.fetch_account_logos(blobs, {"name": "Acme"}, fetcher=fetcher) == []

    def broken(*args, **kwargs):
        raise RuntimeError("blocked")

    assert view.fetch_account_logos(blobs, {"name": "Acme", "domain": "acme.example"}, fetcher=broken) == []


def test_the_catalog_lists_every_released_clone_and_flags_degraded_ones(monkeypatch) -> None:
    """Open question 2 (a): nav, footer and campaign-shell clones are offered like any other; only a
    superseded row gives way to its repair."""
    rows = [
        {"fragment_id": _frag("hero"), "section_role": "hero", "label": "Hero", "superseded_by": None, "degraded_note": None},
        {"fragment_id": _frag("old"), "section_role": "hero", "label": "Old hero", "superseded_by": _frag("hero")},
        {"fragment_id": _frag("nav"), "section_role": "nav", "label": "Nav", "superseded_by": None},
        {"fragment_id": _frag("shell"), "section_role": "header", "label": "Shell", "superseded_by": None, "composed": "campaign_shell"},
        {"fragment_id": _frag("broken"), "section_role": "proof", "label": "Proof", "superseded_by": None,
         "degraded_note": "this clone is marked broken, with no reason recorded."},
    ]

    class Registry:
        def __init__(self, *, blobs, cache_dir):
            pass

        def list_sections(self):
            return {"sections": rows}

    monkeypatch.setattr(view, "DurableAgentClonedSectionRegistry", Registry)
    monkeypatch.setattr(view, "read_web_fragment", lambda storage, *, workspace_id, fragment_id: SimpleNamespace(
        html=f"<p>{fragment_id}</p>", css="", slot_manifest={}))
    clones = view.list_site_clones(SimpleNamespace(storage=None, workspace_id="ws"), "/tmp/cache")
    assert [clone["id"] for clone in clones] == [_frag("hero"), _frag("nav"), _frag("shell"), _frag("broken")]
    assert clones[3]["degraded_note"] == "this clone is marked broken, with no reason recorded."


def test_the_brand_keeps_every_section_the_page_uses_outside_the_catalog(monkeypatch) -> None:
    """Founder ruling Q5 (2026-10-12): a section the page already uses stays in the brand data whatever
    its status (superseded by a repair, retired, not yet approved), so the page still draws, saves and
    reaches publish; it is marked out of the catalog. A section that no longer exists at all is left
    out, so the save check and publish refuse it honestly."""

    loaded = {
        _frag("old"): SimpleNamespace(html="<p>old</p>", css="", slot_manifest={},
                                      row={"fragment_id": _frag("old"), "label": "Old hero", "section_role": "hero"}),
    }

    def read(storage, *, workspace_id, fragment_id):
        if fragment_id not in loaded:
            raise view.NotFoundError("web fragment", fragment_id)
        return loaded[fragment_id]

    monkeypatch.setattr(view, "read_web_fragment", read)
    site = {"pages": {"/": {"content": [
        {"type": "ClonedSection", "props": {"id": "a", "fragmentId": _frag("hero")}},
        {"type": "ClonedSection", "props": {"id": "b", "fragmentId": _frag("old")}},
        {"type": "ClonedSection", "props": {"id": "c", "fragmentId": _frag("gone")}},
        {"type": "CtaBand", "props": {"id": "d"}},
    ]}}}
    pinned = view.pinned_site_clones(site, SimpleNamespace(storage=None, workspace_id="ws"), listed={_frag("hero")})
    assert [(clone["id"], clone["label"], clone["in_catalog"]) for clone in pinned] == [(_frag("old"), "Old hero", False)]


def test_a_pinned_clone_reads_its_page_position_and_degraded_note_the_registrys_way(monkeypatch) -> None:
    """Controller ruling (2026-10-12): a web_fragment row names its page in ``provenance.page_url``
    (else ``source_url``), its position in ``provenance.section_index``, and its brokenness as
    ``degraded``/``degraded_reason``; the registry's one row shaper turns those into the clone's
    ``page_url``, ``section_index`` and ``degraded_note``."""

    row = {"fragment_id": _frag("old"), "section_role": "hero", "label": "Old hero",
           "source_url": "https://garnerhealth.com/",
           "provenance": {"page_url": "https://garnerhealth.com/plans", "section_index": 3},
           "degraded": True, "degraded_reason": DEGRADED_REASON_BLANK_RENDER}
    monkeypatch.setattr(view, "read_web_fragment", lambda storage, *, workspace_id, fragment_id: SimpleNamespace(
        html="<p>old</p>", css="", slot_manifest={}, row=row))
    site = {"pages": {"/": {"content": [{"type": "ClonedSection", "props": {"id": "b", "fragmentId": _frag("old")}}]}}}
    [clone] = view.pinned_site_clones(site, SimpleNamespace(storage=None, workspace_id="ws"), listed=set())
    assert clone["id"] == _frag("old") and clone["in_catalog"] is False
    assert clone["page_url"] == "https://garnerhealth.com/plans"
    assert clone["section_index"] == 3
    assert clone["degraded_note"] == degraded_headline(DEGRADED_REASON_BLANK_RENDER)


def test_sections_for_a_turn_keep_the_documents_pins_and_add_the_newest_of_each_name() -> None:
    rows = {
        "a" * 64: {"name": "StepsBand", "digest": "a" * 64, "module_sha256": "a" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 1}},
        "b" * 64: {"name": "StepsBand", "digest": "b" * 64, "module_sha256": "b" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 2}},
        "d" * 64: {"name": "QuoteBand", "digest": "d" * 64, "module_sha256": "d" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 3}},
    }
    store = SimpleNamespace(
        get_site_sections=lambda digests: [rows[d] for d in digests if d in rows],
        list_latest_site_sections=lambda: [rows["b" * 64], rows["d" * 64]],
    )
    blobs = SimpleNamespace(read=lambda digest: f"bytes {digest[:1]}".encode())
    sections = view.site_sections_for_turn(store, blobs, {"agent_sections": {"StepsBand": "a" * 64}})
    assert sections["StepsBand"].digest == "a" * 64  # the document's own pin wins
    assert sections["QuoteBand"].digest == "d" * 64 and sections["QuoteBand"].module_js == "bytes d"


def test_library_assets_join_only_when_the_site_already_uses_them() -> None:
    site = {"pages": {"/": {"content": [{"props": {"image": "/asset-store/" + "1" * 64}}]}}}
    library = {
        "asset_used": {"record": {"media": {"digest": {"value": "1" * 64}}}},
        "asset_unused": {"record": {"media": {"digest": {"value": "2" * 64}}}},
    }
    assert view.referenced_digests(site) == {"1" * 64}
    assert set(view.referenced_library_assets(library, view.referenced_digests(site))) == {"asset_used"}


def test_the_turn_inputs_put_it_together(monkeypatch) -> None:
    monkeypatch.setattr(view, "list_site_clones", lambda blobs, cache_dir: [])
    monkeypatch.setattr(view, "build_site_catalog", lambda brand, seller: {"brand/brand.md": f"# Brand: {seller}\n"})
    monkeypatch.setattr(view, "fetch_account_logos", lambda blobs, card, cache=None: [])
    monkeypatch.setattr(view, "seller_name", lambda store, ref, kit: "Garner Health")
    monkeypatch.setattr(view, "site_sections_for_turn", lambda store, blobs, site: {})

    class Reads:
        def read_account_research(self, *, account_entity_id, section, offset):
            return {"overview": [_section("c1")], "next_offset": None}

        def read_cited_claims(self, *, entity_id, claim_ids):
            return {"entity_id": entity_id, "claims": [{"claim_id": "c1"}], "dispositions": {"c1": "served"}}

        def project_design_context(self):
            return {"status": "not_pinned", "files": []}

    document = {"id": "doc_a", "scene": {"id": "doc_a", "title": "T", "theme": {"brand_kit": {"id": "kit_1", "version": 2}},
                                          "pages": {"/": {"content": []}}, "shell": None, "agent_sections": {}}}
    inputs = view.build_site_turn_inputs(
        document=document, store=SimpleNamespace(), blobs=SimpleNamespace(workspace_id="ws_1"), cache_dir="/tmp",
        platform_reads=Reads(), account_card={"name": "Syracuse City School District", "domain": "syracusecityschools.com"},
        delegation_bundle={"brief": "B", "artifacts": [{"document_id": "doc_a", "account_id": "acc_1"}]},
        brand_kit={"name": "kit"}, kit_assets={}, font_spec=None, asset_library={},
    )
    assert inputs.document_id == "doc_a" and inputs.workspace_id == "ws_1" and inputs.brief == "B"
    assert inputs.account_name == "Syracuse City School District" and inputs.seller == "Garner Health"
    assert inputs.catalog == {"brand/brand.md": "# Brand: Garner Health\n"}
    assert inputs.brand["slug"] == "kit_1" and "measured" not in inputs.brand
    assert len(inputs.overview) == 1 and len(inputs.insights) == 1  # both sections read through the same fake
    assert inputs.claims == [{"claim_id": "c1"}] and inputs.held_claim_ids == frozenset()


def test_the_brand_loader_lane_a_validates_with_is_the_same_builder(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from lumen_api import main as api_main

    monkeypatch.setattr(api_main, "resolve_web_turn_brand_kit",
                        lambda site, blobs: ({"name": "Garner"}, "document", {}, {"faces": []}))
    monkeypatch.setattr(view, "list_site_clones", lambda blobs, cache_dir: [])
    asked: list[str] = []
    load = view.site_brand_loader_for(lambda workspace_id: asked.append(workspace_id) or tmp_path)
    document = {"id": "doc_a", "scene": {"id": "doc_a", "theme": {"brand_kit": {"id": "kit_1", "version": 2}}, "pages": {}}}
    brand = load(None, SimpleNamespace(workspace_id="ws_b"), document)
    assert brand["slug"] == "kit_1" and brand["clones"] == {} and asked == ["ws_b"]
