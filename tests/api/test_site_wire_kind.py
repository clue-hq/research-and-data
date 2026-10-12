"""The one wire-kind mapper (Contract 8): a site travels as "site"; the Head of ABM still reads
"web" for it (founder question Q1, recommendation (b))."""

from __future__ import annotations

import pytest

from clue_api.design_leg_wiring import design_document_card_fields, head_of_abm_doc_kind, wire_kind


@pytest.mark.parametrize(("doc_kind", "wire"), [("site", "site"), ("web", "web"), ("scene", "ad")])
def test_wire_kind(doc_kind: str, wire: str) -> None:
    assert wire_kind(doc_kind) == wire


def test_the_card_fields_say_site_for_a_site() -> None:
    fields = design_document_card_fields(
        {"doc_kind": "site", "pages_json": None, "artifact_type": None}
    )
    assert fields == {"kind": "site", "artifact_type": None, "width_px": None, "height_px": None}


def test_the_head_of_abm_reads_a_site_as_web() -> None:
    assert head_of_abm_doc_kind("site") == "web"
    assert head_of_abm_doc_kind("web") == "web"
    assert head_of_abm_doc_kind("scene") == "scene"
