from __future__ import annotations

import pytest

from clue_api.design_turn_targets import DesignTurnTargetError, resolve_scene_targets


def _scene() -> dict[str, object]:
    return {
        "pages": {
            "page_one": {"id": "page_one", "children": ["frame_one"]},
            "page_two": {"id": "page_two", "children": ["frame_two"]},
        },
        "nodes": {
            "frame_one": {"children": ["headline", "body"]},
            "headline": {"children": []},
            "body": {"children": []},
            "frame_two": {"children": ["footer"]},
            "footer": {"children": []},
            "detached": {"children": []},
        },
    }


def test_scene_targets_preserve_order_and_derive_the_page_server_side() -> None:
    resolved = resolve_scene_targets(_scene(), ("body", "headline"))

    assert resolved.target_node_ids == ("body", "headline")
    assert resolved.active_page_id == "page_one"


@pytest.mark.parametrize(
    ("targets", "code"),
    [
        (("missing",), "CONTEXT_REF_NOT_FOUND"),
        (("detached",), "CONTEXT_REF_NOT_FOUND"),
        (("headline", "footer"), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("headline", "headline"), "CONTEXT_REF_DUPLICATE"),
    ],
)
def test_scene_targets_refuse_missing_detached_cross_page_or_duplicate_nodes(
    targets: tuple[str, ...],
    code: str,
) -> None:
    with pytest.raises(DesignTurnTargetError) as refused:
        resolve_scene_targets(_scene(), targets)

    assert refused.value.code == code
