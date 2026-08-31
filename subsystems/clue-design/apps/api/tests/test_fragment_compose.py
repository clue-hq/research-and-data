"""The raw-CSS authoring lane (founder ruling 2026-08-30): agent-composed sections.

`compose_section` lets the agent mint a NEW library fragment from raw HTML + raw CSS. The whole
point of this file is one sentence: **same door, no exceptions** — an agent composition passes
the exact sanitize-once pipeline a harvested clone passes (script stripping, fail-closed byte
references, slot detection, CSS scoping with layer flattening), and differs only in its birth
policy: minted `draft` per R-I5, then immediately released through the same explicit status
transition every other release uses, because the founder ruled agent compositions carry no
human release door.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its repair
neighbour.
"""

from __future__ import annotations

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore
from lumen_api.fragments import (
    FragmentRefused,
    create_web_fragment,
    read_web_fragment,
    set_web_fragment_status,
)

COMPOSED_HTML = (
    '<section id="sec_consult" class="consult-band">'
    '<h2 class="consult-head">What we cover in the consult</h2>'
    '<p class="consult-body">Pricing models, metering, and quote to cash.</p>'
    '<a class="consult-cta" href="#book">Request a billing consult</a>'
    "</section>"
)
COMPOSED_CSS = (
    ".consult-band { padding: 96px 0; background: #ffffff }"
    ".consult-head { font-size: 2.25rem; letter-spacing: -0.02em }"
    ".consult-cta { border-radius: 16.5px; background: #635bff; color: #fff }"
)


def _registry(workspace_id: str, storage: FsStorage, cache_dir):
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


def test_a_composed_section_is_minted_and_released_in_one_act(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.compose_section(
        COMPOSED_HTML, COMPOSED_CSS, section_role="other",
        label="Consult coverage band", note="campaign consult coverage band",
    )

    # Released with no human door — the founder's autonomy ruling, via the ordinary
    # status transition (mint births draft; release is explicit, and recorded).
    assert minted["status"] == "approved"
    assert minted["insertable"] is True
    listing = registry.list_sections()
    row = next(
        section for section in listing["sections"]
        if section["fragment_id"] == minted["fragment_id"]
    )
    # Marked composed like the campaign shells: listed and pinnable, and excluded
    # from whole-page recreates by the same flag those use.
    assert row.get("composed") == "agent"


def test_compose_rides_the_same_sanitizer_a_harvested_clone_does(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.compose_section(
        '<section id="sec_x"><h2 onclick="pwn()">Hi</h2>'
        "<script>steal(document.cookie)</script><p>Body</p></section>",
        ".x { color: #123 }",
        note="sanitizer parity check",
    )

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert "script" not in stored.html
    assert "steal" not in stored.html
    assert "onclick" not in stored.html


def test_compose_css_is_scoped_and_its_cascade_layers_are_flattened(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.compose_section(
        COMPOSED_HTML,
        "@layer reset, base;"
        "@layer base { .consult-head { margin-inline: auto } }"
        "@layer reset { * { margin: 0 } }",
        note="layer flattening parity check",
    )

    stored = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=minted["fragment_id"]
    )
    assert "@layer" not in stored.css
    assert "lumen-frag-" in stored.css  # scoped under the wrapper, never bare


def test_an_unregistered_byte_reference_refuses_fail_closed(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused):
        registry.compose_section(
            '<section id="sec_x"><img src="https://cdn.example/hot.png" alt=""></section>',
            ".x { color: #123 }",
            note="hotlink must refuse",
        )


def test_a_blank_note_refuses_before_anything_is_written(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    with pytest.raises(FragmentRefused) as refusal:
        registry.compose_section(COMPOSED_HTML, COMPOSED_CSS, note="   ")
    assert refusal.value.code == "fragment.compose_note_missing"


def test_identical_bytes_converge_onto_one_fragment(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    first = registry.compose_section(COMPOSED_HTML, COMPOSED_CSS, note="first mint")
    second = registry.compose_section(COMPOSED_HTML, COMPOSED_CSS, note="second mint")

    assert second["fragment_id"] == first["fragment_id"]
    assert second["insertable"] is True


def test_a_raw_repair_is_minted_released_in_one_act_with_lineage(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Founder ruling A (2026-08-30): the raw lane's repair is released at mint.

    R-I5 is honored, not bypassed — the mint births draft and the release is the ordinary
    explicit transition — and the lineage pair still names the clone it replaces, so the
    library-wide substitution story is intact, just no longer gated per repair.
    """
    row, _artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html='<section class="band"><h2>Original</h2></section>',
        css=".band { height: 2400px }",
        rehosted={},
        source_url="https://seller.example/",
        section_role="proof",
        label="Proof — original",
        provenance={"page_url": "https://seller.example/"},
    )
    original = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.mint_repair(
        replaces=original["fragment_id"],
        html='<section id="sec_fix" class="band"><h2>Original</h2><p>At natural height.</p></section>',
        css=".band { padding: 96px 0 }",
        rung=2,
        note="dead height removed, same story",
        release=True,
    )

    assert minted["status"] == "approved"
    assert minted["insertable"] is True
    assert minted["derived_from"] == original["fragment_id"]
    # And the vocabulary lane's contract is untouched: without release, draft as ever.
    unreleased = registry.mint_repair(
        replaces=original["fragment_id"],
        html='<section id="sec_fix2" class="band"><h2>Original</h2></section>',
        css=".band { padding: 48px 0 }",
        rung=3,
        note="a second, different repair without release",
    )
    assert unreleased["status"] == "draft"
    assert unreleased["insertable"] is False


def test_slots_are_detected_so_the_band_stays_rebindable(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    minted = registry.compose_section(
        COMPOSED_HTML, COMPOSED_CSS, note="slot detection check"
    )

    # The same detector minting runs on harvested clones: the composed band's texts
    # and links come back as a rebindable editing surface, not a sealed blob.
    assert len(minted["slot_keys"]) >= 1
