"""Dormancy, degradation and repair lineage on a fragment row (clone-fidelity F3.0).

Three founder rulings meet on one table here, and each one is a different KIND of fact about a
cloned section:

* **D-F8 — dormant.** A section the source site HIDES is preserved rather than dropped, and it is
  preserved as something no automatic path can release: the kit approval cascade steps over it,
  default agent discovery never lists it, the document-write gate refuses to pin it, and the one
  door out is a human moving it to ``approved`` — which is refused unless the fragment has a
  usable preview to be judged on.
* **D-F6 — degraded.** "This clone is broken" is a judgement about a section, not a lifecycle
  state, so it rides ORTHOGONAL columns (``degraded`` + ``degraded_reason``). A degraded original
  stays approved and pinnable until its repair exists; it is evidence, and evidence is not
  retired for being ugly.
* **D-F6 — lineage.** A repair is a NEW fragment (the original is immutable), and it says whose
  repair it is: ``derived_from`` + ``derived_reason``, validated at write against a fragment this
  workspace actually holds.

DB-backed, with the suite's per-test workspace + disposable ``FsStorage``, exactly like
``test_web_fragments.py`` — which owns the F1.2 half (creation, addressing, the resolution gate).
"""

from __future__ import annotations

from typing import Any

import pytest
from clue_storage import FsStorage

from clue_design.errors import DesignFragmentActivationError
from lumen_api.database import FragmentReferenceError
from lumen_api.design_store import HybridRepository
from lumen_api.fragments import (
    FRAGMENT_STATUSES,
    FragmentRefused,
    create_web_fragment,
    list_web_fragments,
    set_web_fragment_degraded,
    set_web_fragment_status,
)

SOURCE_URL = "https://insight.example/"
PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"


def _html(marker: str) -> str:
    return f'<section class="{marker}"><h2>{marker}</h2></section>'


def _create(
    workspace_id: str,
    storage: FsStorage,
    *,
    marker: str = "hero",
    preview: bytes | None = PNG,
    **kwargs: Any,
):
    return create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=_html(marker),
        css=f".{marker} {{ padding: 64px }}",
        rehosted={},
        source_url=SOURCE_URL,
        section_role="other",
        preview=preview,
        **kwargs,
    )


def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_f30") -> dict[str, Any]:
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": kit_id, "version": 1, "name": "Insight", "approval_status": "draft"},
        {},
        [],
        "website",
    )


# --------------------------------------------------------------------------- #
# 1. The vocabulary
# --------------------------------------------------------------------------- #


def test_dormant_joins_the_status_vocabulary_and_a_typo_still_does_not(
    workspace_id: str, design_storage: FsStorage
) -> None:
    assert FRAGMENT_STATUSES == ("draft", "approved", "deprecated", "dormant")

    _row, artifact = _create(workspace_id, design_storage)
    moved = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="dormant"
    )
    assert moved["status"] == "dormant"

    with pytest.raises(ValueError) as excinfo:
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="hibernating"
        )
    assert "hibernating" in str(excinfo.value)


def test_a_fragment_can_be_born_dormant(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row, _artifact = _create(workspace_id, design_storage, status="dormant")
    assert row["status"] == "dormant"


def test_a_fragment_cannot_be_born_into_a_status_nobody_defined(
    workspace_id: str, design_storage: FsStorage
) -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _create(workspace_id, design_storage, status="asleep")
    assert excinfo.value.code == "fragment.status_unknown"
    assert list_web_fragments(workspace_id=workspace_id) == []


# --------------------------------------------------------------------------- #
# 2. The kit cascade steps over a dormant section
# --------------------------------------------------------------------------- #


def test_approving_the_kit_releases_the_drafts_and_leaves_the_dormant_one_asleep(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """One scenario, both halves. D-F8: a hidden section is NEVER auto-approved by the cascade —
    which is the whole reason it is a status rather than a flag on a draft."""
    kit = _seed_kit(workspace_id)
    _row, drafted = _create(
        workspace_id,
        design_storage,
        marker="visible",
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )
    _row2, sleeping = _create(
        workspace_id,
        design_storage,
        marker="hidden",
        status="dormant",
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )

    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )

    rows = {row["fragment_id"]: row["status"] for row in list_web_fragments(workspace_id=workspace_id)}
    assert rows[drafted.fragment_id] == "approved"
    assert rows[sleeping.fragment_id] == "dormant"


def test_un_approving_the_kit_does_not_wake_a_dormant_section_either(
    workspace_id: str, design_storage: FsStorage
) -> None:
    kit = _seed_kit(workspace_id)
    _row, sleeping = _create(
        workspace_id,
        design_storage,
        marker="hidden",
        status="dormant",
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )
    repo = HybridRepository(workspace_id=workspace_id)
    repo.update_brand_kit_approval(kit["brand_kit_id"], "approved")
    repo.update_brand_kit_approval(kit["brand_kit_id"], "draft")
    rows = {row["fragment_id"]: row["status"] for row in list_web_fragments(workspace_id=workspace_id)}
    assert rows[sleeping.fragment_id] == "dormant"


# --------------------------------------------------------------------------- #
# 3. Default agent discovery
# --------------------------------------------------------------------------- #


def test_default_discovery_never_offers_a_dormant_section(
    tmp_path, workspace_id: str, design_storage: FsStorage
) -> None:
    """Approved-only discovery already excludes it by construction; D-F8 makes that a promise
    rather than an accident, so it is pinned here on its own."""
    from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
    from lumen_api.design_store import DesignBlobStore

    _row, offered = _create(workspace_id, design_storage, marker="visible")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=offered.fragment_id, status="approved"
    )
    _row2, sleeping = _create(workspace_id, design_storage, marker="hidden", status="dormant")

    registry = DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(design_storage, workspace_id), cache_dir=tmp_path / "cache"
    )
    listed = registry.list_sections()
    ids = {section["fragment_id"] for section in listed["sections"]}
    assert offered.fragment_id in ids
    assert sleeping.fragment_id not in ids
    assert listed["total"] == 1


# --------------------------------------------------------------------------- #
# 4. Activation is a human act, and it needs something to look at
# --------------------------------------------------------------------------- #


def test_activating_a_dormant_section_with_no_preview_is_refused_and_says_why(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, sleeping = _create(
        workspace_id, design_storage, marker="hidden", preview=None, status="dormant"
    )
    with pytest.raises(DesignFragmentActivationError) as excinfo:
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=sleeping.fragment_id, status="approved"
        )
    assert excinfo.value.fragment_id == sleeping.fragment_id
    assert excinfo.value.reason == "no_preview"
    assert "preview" in str(excinfo.value)

    still = list_web_fragments(workspace_id=workspace_id)[0]
    assert still["status"] == "dormant"


def test_activation_succeeds_once_the_section_has_a_usable_preview(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, sleeping = _create(
        workspace_id, design_storage, marker="hidden", preview=PNG, status="dormant"
    )
    woken = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=sleeping.fragment_id, status="approved"
    )
    assert woken["status"] == "approved"


def test_a_dormant_section_cannot_slip_out_through_draft_either(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """``draft`` is one kit approval away from ``approved``, so letting a previewless dormant row
    become a draft would route around the gate rather than pass it."""
    _row, sleeping = _create(
        workspace_id, design_storage, marker="hidden", preview=None, status="dormant"
    )
    with pytest.raises(DesignFragmentActivationError):
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=sleeping.fragment_id, status="draft"
        )


def test_retiring_a_previewless_dormant_section_is_always_allowed(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The preview gate protects USE. Retiring is the opposite of using."""
    _row, sleeping = _create(
        workspace_id, design_storage, marker="hidden", preview=None, status="dormant"
    )
    retired = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=sleeping.fragment_id, status="deprecated"
    )
    assert retired["status"] == "deprecated"


# --------------------------------------------------------------------------- #
# 5. The pin gate (red case: a dormant section is not pinnable)
# --------------------------------------------------------------------------- #


def _web_doc(document_id: str, fragment_id: str) -> dict[str, Any]:
    node = {"id": "n1", "kind": "fragment", "fragment_id": fragment_id}
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "T",
        "pages": [
            {
                "id": "page_1",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {"root": {"id": "root", "kind": "container", "children": ["n1"]}, "n1": node},
            }
        ],
        "assets": {},
        "custom_css": "",
    }


def test_a_document_may_not_pin_a_dormant_section(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, sleeping = _create(workspace_id, design_storage, marker="hidden", status="dormant")
    store = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError) as excinfo:
        store.create_document(_web_doc("doc_dormant", sleeping.fragment_id), doc_kind="web")
    assert excinfo.value.code == "fragment.not_approved"
    assert "dormant" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 6. The degraded marker (D-F6) — orthogonal to status, by design
# --------------------------------------------------------------------------- #


def test_a_degraded_original_stays_approved_and_stays_pinnable(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """D-F6 preserves the harvested original as EVIDENCE. Marking it broken must not retire it —
    the page still pins it until a repair exists to pin instead."""
    _row, original = _create(workspace_id, design_storage, marker="broken")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=original.fragment_id, status="approved"
    )
    marked = set_web_fragment_degraded(
        workspace_id=workspace_id,
        fragment_id=original.fragment_id,
        degraded=True,
        reason="dead_height",
    )
    assert marked["degraded"] is True
    assert marked["degraded_reason"] == "dead_height"
    assert marked["status"] == "approved"

    store = HybridRepository(workspace_id=workspace_id)
    document = store.create_document(
        _web_doc("doc_degraded", original.fragment_id), doc_kind="web"
    )
    assert document["id"] == "doc_degraded"


def test_a_fragment_can_be_born_degraded_and_the_reason_is_not_optional(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row, _artifact = _create(
        workspace_id, design_storage, degraded=True, degraded_reason="dead_height"
    )
    assert row["degraded"] is True
    assert row["degraded_reason"] == "dead_height"

    with pytest.raises(FragmentRefused) as excinfo:
        _create(workspace_id, design_storage, marker="other", degraded=True)
    assert excinfo.value.code == "fragment.degraded_reason_missing"


def test_clearing_the_marker_clears_its_reason_with_it(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, original = _create(
        workspace_id, design_storage, degraded=True, degraded_reason="dead_height"
    )
    cleared = set_web_fragment_degraded(
        workspace_id=workspace_id, fragment_id=original.fragment_id, degraded=False
    )
    assert cleared["degraded"] is False
    assert cleared["degraded_reason"] is None


def test_marking_a_fragment_degraded_without_a_reason_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, original = _create(workspace_id, design_storage)
    with pytest.raises(ValueError):
        set_web_fragment_degraded(
            workspace_id=workspace_id, fragment_id=original.fragment_id, degraded=True, reason=None
        )


# --------------------------------------------------------------------------- #
# 7. Repair lineage (D-F6): derived_from + derived_reason
# --------------------------------------------------------------------------- #


def test_a_repair_records_which_fragment_it_repairs_and_why(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, original = _create(workspace_id, design_storage, marker="original")
    row, repair = _create(
        workspace_id,
        design_storage,
        marker="repair",
        derived_from=original.fragment_id,
        derived_reason="dead_height repaired to a compact static fallback",
    )
    assert row["derived_from"] == original.fragment_id
    assert row["derived_reason"].startswith("dead_height repaired")
    assert repair.fragment_id != original.fragment_id


def test_half_a_lineage_reference_is_refused_in_either_direction(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, original = _create(workspace_id, design_storage, marker="original")

    with pytest.raises(FragmentRefused) as no_reason:
        _create(workspace_id, design_storage, marker="a", derived_from=original.fragment_id)
    assert no_reason.value.code == "fragment.derived_incomplete"

    with pytest.raises(FragmentRefused) as no_target:
        _create(workspace_id, design_storage, marker="b", derived_reason="because")
    assert no_target.value.code == "fragment.derived_incomplete"


def test_a_repair_of_a_fragment_nobody_holds_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    absent = "frag_" + "ab" * 8
    with pytest.raises(FragmentRefused) as excinfo:
        _create(
            workspace_id,
            design_storage,
            marker="orphan",
            derived_from=absent,
            derived_reason="repaired",
        )
    assert excinfo.value.code == "fragment.derived_from_unresolved"
    assert excinfo.value.reference == absent
    assert list_web_fragments(workspace_id=workspace_id) == []


def test_a_repair_may_not_name_another_workspaces_fragment(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The id is a global content address, so a neighbour's fragment id is a REAL id — and it
    still resolves to the same refusal an invented one gets."""
    other = f"{workspace_id}_owner"
    _row, theirs = _create(other, design_storage, marker="theirs")
    with pytest.raises(FragmentRefused) as excinfo:
        _create(
            workspace_id,
            design_storage,
            marker="mine",
            derived_from=theirs.fragment_id,
            derived_reason="repaired",
        )
    assert excinfo.value.code == "fragment.derived_from_unresolved"
    assert list_web_fragments(workspace_id=workspace_id) == []


def test_lineage_is_frozen_by_the_trigger_the_way_the_payload_is(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """``degraded`` is a judgement that can change; ``derived_from`` is how the row came to
    exist, which cannot."""
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    _row, original = _create(workspace_id, design_storage, marker="original")
    _row2, repair = _create(
        workspace_id,
        design_storage,
        marker="repair",
        derived_from=original.fragment_id,
        derived_reason="repaired",
    )
    with pytest.raises(Exception) as excinfo:
        DesignStoreBridge(workspace_id)._run(
            lambda conn: conn.execute(
                text(
                    "UPDATE design_web_fragment SET derived_reason = 'rewritten' "
                    "WHERE fragment_id = :f AND workspace_id = :w"
                ),
                {"f": repair.fragment_id, "w": workspace_id},
            )
        )
    assert "immutable" in str(excinfo.value)
