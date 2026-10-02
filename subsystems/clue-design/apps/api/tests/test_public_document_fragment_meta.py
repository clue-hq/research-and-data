from __future__ import annotations

from lumen_api.main import fragment_meta_for_document

FRAG = "frag_" + "ab" * 8
OTHER = "frag_" + "cd" * 8


def _doc() -> dict:
    return {
        "doc_kind": "web",
        "scene": {
            "pages": [
                {
                    "id": "home",
                    "root": "r",
                    "nodes": {
                        "r": {"id": "r", "kind": "container", "children": ["s"]},
                        "s": {"id": "s", "kind": "section", "children": ["f"]},
                        "f": {"id": "f", "kind": "fragment", "fragment_id": FRAG},
                    },
                },
                {
                    "id": "issuing",
                    "root": "r2",
                    "nodes": {
                        "r2": {"id": "r2", "kind": "container", "children": ["f2"]},
                        "f2": {"id": "f2", "kind": "fragment", "fragment_id": OTHER},
                    },
                },
            ]
        },
    }


def test_meta_covers_every_pinned_fragment_on_every_page() -> None:
    rows = [
        {"fragment_id": FRAG, "label": "Stripe homepage hero", "section_role": "hero"},
        {"fragment_id": "frag_" + "ef" * 8, "label": "unpinned", "section_role": "cta"},
    ]
    meta = fragment_meta_for_document(_doc(), rows)
    assert meta == {
        FRAG: {"label": "Stripe homepage hero", "section_role": "hero"},
        OTHER: {"label": None, "section_role": None},  # pinned but unknown → honest nulls
    }


def test_scene_documents_get_no_meta() -> None:
    assert fragment_meta_for_document({"doc_kind": "scene", "scene": {}}, []) is None
