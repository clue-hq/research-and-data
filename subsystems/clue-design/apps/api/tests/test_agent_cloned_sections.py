"""The cloned-section capability one web turn gets (clone-fidelity F2.3).

The agent runtime never opens the design database. Everything it may know about the workspace's
cloned sections therefore arrives through one injected capability, exactly as the account-local
custom-component registry arrives — and this file pins what that capability will and will not say.

Two properties matter more than the rest:

* **Approved only.** Discovery lists what a human released. A ``draft`` section (minted, waiting
  on its brand kit's approval) and a ``deprecated`` one (retired) are never offered.
* **The refusal is the GATE's.** ``resolve_insertable`` does not re-decide what "approved" means;
  it asks :meth:`HybridRepository.validate_fragment_reference_changes` — the same check the
  document write makes — so a status rule can never mean one thing to the agent and another to
  the write it is heading for.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F1.2 neighbour.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.database import FragmentReferenceError
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import SlotSpec, create_web_fragment, set_web_fragment_status

HERO_HTML = (
    '<section class="hero"><h1 class="head">Care, on your terms</h1>'
    '<a class="cta" href="https://insight.example/demo">Book a demo</a></section>'
)
HERO_CSS = ".hero { padding: 64px } .head { color: #123456 }"
NAV_HTML = '<nav class="nav"><a class="brand" href="/">Insight</a></nav>'
NAV_CSS = ".nav { display: flex }"
PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"
SOURCE_URL = "https://insight.example/"

HERO_SLOTS = (
    SlotSpec(selector=".head", key="headline", kind="text"),
    SlotSpec(selector=".cta", key="cta_href", kind="href"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mint(
    workspace_id: str,
    storage: FsStorage,
    *,
    html: str = HERO_HTML,
    css: str = HERO_CSS,
    section_role: str = "hero",
    label: str | None = "Hero — Care, on your terms",
    slots: Any = HERO_SLOTS,
    preview: bytes | None = PNG,
    approved: bool = True,
    **kwargs: Any,
) -> dict:
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=css,
        rehosted={},
        source_url=SOURCE_URL,
        section_role=section_role,
        label=label,
        slots=slots,
        preview=preview,
        provenance={"page_url": SOURCE_URL, "slots": [spec.key for spec in slots]},
        **kwargs,
    )
    if approved:
        row = set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
        )
    return row


def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_clone_1") -> dict:
    """A real kit row — the fragment table's kit binding is a foreign key, not a label."""
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": kit_id, "version": 3, "name": "Insight", "approval_status": "approved"},
        {},
        [],
        "website",
    )


def _registry(
    workspace_id: str, storage: FsStorage, cache_dir
) -> DurableAgentClonedSectionRegistry:
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


# --------------------------------------------------------------------------- #
# Discovery: approved only
# --------------------------------------------------------------------------- #


def test_list_sections_returns_the_approved_rows_with_what_a_picker_needs(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    row = _mint(
        workspace_id,
        design_storage,
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["schema_version"] == 1
    assert [section["fragment_id"] for section in listed["sections"]] == [
        row["fragment_id"]
    ]
    section = listed["sections"][0]
    assert section["section_role"] == "hero"
    assert section["label"] == "Hero — Care, on your terms"
    assert section["source_url"] == SOURCE_URL
    assert section["source_kit_id"] == kit["brand_kit_id"]
    assert section["source_kit_version"] == int(kit["version"])
    assert section["preview_digest"] == _sha(PNG)
    # The row's own record of what can be re-filled — no payload blob is read to list.
    assert section["slot_keys"] == ["headline", "cta_href"]


def test_a_draft_section_is_never_listed(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    _mint(workspace_id, design_storage, approved=False)

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["sections"] == []


def test_a_deprecated_section_is_never_listed(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        status="deprecated",
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["sections"] == []


def test_listing_is_bounded(
    workspace_id: str, design_storage: FsStorage, tmp_path, monkeypatch
) -> None:
    for index in range(4):
        _mint(
            workspace_id,
            design_storage,
            html=f'<section class="hero"><h1 class="head">Headline {index}</h1></section>',
            slots=(SlotSpec(selector=".head", key="headline", kind="text"),),
        )
    monkeypatch.setattr(
        "lumen_api.agent_cloned_sections.CLONED_SECTION_LIST_MAX", 2, raising=True
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert len(listed["sections"]) == 2


# --------------------------------------------------------------------------- #
# Describe: the slot kinds and the pixels
# --------------------------------------------------------------------------- #


def test_describe_reads_the_slot_kinds_and_materializes_the_preview(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    cache = tmp_path / "cache"
    row = _mint(workspace_id, design_storage)

    described = _registry(workspace_id, design_storage, cache).describe(
        [row["fragment_id"]]
    )

    entry = described[row["fragment_id"]]
    assert entry["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]
    preview_path = entry["preview_path"]
    assert preview_path is not None
    with open(preview_path, "rb") as handle:
        assert handle.read() == PNG


def test_describe_says_so_when_a_section_has_no_preview(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, preview=None)

    described = _registry(workspace_id, design_storage, tmp_path / "cache").describe(
        [row["fragment_id"]]
    )

    assert described[row["fragment_id"]]["preview_path"] is None


def test_describe_skips_an_id_it_cannot_resolve(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    described = _registry(workspace_id, design_storage, tmp_path / "cache").describe(
        ["frag_deadbeefdeadbeef"]
    )

    assert described == {}


# --------------------------------------------------------------------------- #
# The insert gate: the refusal is the document write's own
# --------------------------------------------------------------------------- #


def test_resolve_insertable_hands_back_the_render_entry_for_an_approved_section(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)

    resolved = _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
        row["fragment_id"]
    )

    assert resolved["fragment_id"] == row["fragment_id"]
    assert resolved["section_role"] == "hero"
    assert "Care, on your terms" in resolved["render"]["html"]
    assert resolved["render"]["css"]
    assert resolved["render"]["slot_kinds"] == {"headline": "text", "cta_href": "href"}
    assert resolved["render"]["asset_digests"] == []
    assert resolved["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]


def test_resolve_insertable_refuses_a_draft_with_the_gates_own_code(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, approved=False)

    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            row["fragment_id"]
        )

    assert caught.value.code == "fragment.not_approved"
    assert caught.value.fragment_id == row["fragment_id"]
    assert "approve the brand kit" in caught.value.message


def test_resolve_insertable_refuses_a_deprecated_section(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        status="deprecated",
    )

    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            row["fragment_id"]
        )

    assert caught.value.code == "fragment.not_approved"


def test_resolve_insertable_refuses_an_id_this_workspace_does_not_hold(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            "frag_deadbeefdeadbeef"
        )

    assert caught.value.code == "fragment.unresolved"


def test_another_tenants_approved_section_is_neither_listed_nor_insertable(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    other = f"{workspace_id}_neighbour"
    row = _mint(other, design_storage)

    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    assert registry.list_sections()["sections"] == []
    with pytest.raises(FragmentReferenceError) as caught:
        registry.resolve_insertable(row["fragment_id"])
    assert caught.value.code == "fragment.unresolved"
