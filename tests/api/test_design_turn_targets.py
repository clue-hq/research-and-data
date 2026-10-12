from __future__ import annotations

import asyncio

import pytest

from clue_agents import DomainObjectRef
from clue_api.chat.composer_context import ContextReferenceError, validated_context_refs
from clue_api.design_turn_targets import (
    DesignTurnTargetError,
    SiteTarget,
    resolve_scene_targets,
    resolve_site_targets,
    resolve_web_targets,
    validate_site_targets,
    validate_web_targets,
)


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


# --- web targets (annotated web-editor refs) ---------------------------------------------------


def _web_ref(
    object_id: str,
    note: str | None = None,
    object_type: str = "design_node",
    version: int | None = 9,
) -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id="ws_1",
        object_type=object_type,
        object_id=object_id,
        version=version,
        note=note,
    )


def _web_doc() -> dict[str, object]:
    return {
        "id": "doc_web",
        "pages": [
            {"id": "home", "route": "/", "nodes": {"frg_a": {}, "sec_b": {}}},
            {"id": "pricing", "route": "/pricing", "nodes": {"sec_c": {}}},
        ],
    }


def test_web_targets_split_inner_paths_and_keep_order_and_notes() -> None:
    resolved = resolve_web_targets(
        [
            _web_ref("doc_1", object_type="design_document"),
            _web_ref("frg_a#:nth-child(1) > :nth-child(2)", "1. Shorter"),
            _web_ref("sec_b", "2. Remove"),
            _web_ref("frg_a#:nth-child(3)", "3. Bolder"),
        ]
    )

    assert resolved is not None
    assert resolved.target_node_ids == ("frg_a", "sec_b")
    assert [(n.target, n.path, n.note) for n in resolved.target_notes] == [
        ("frg_a", ":nth-child(1) > :nth-child(2)", "1. Shorter"),
        ("sec_b", None, "2. Remove"),
        ("frg_a", ":nth-child(3)", "3. Bolder"),
    ]


def test_no_design_node_refs_means_no_targets() -> None:
    assert resolve_web_targets([_web_ref("doc_1", object_type="design_document")]) is None


def test_web_target_validation_accepts_ids_across_pages_and_inner_paths() -> None:
    validate_web_targets(_web_doc(), ("frg_a#:nth-child(1) > :nth-child(2)", "sec_c"))


@pytest.mark.parametrize(
    ("targets", "code"),
    [
        ((), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("frg_a", "frg_a"), "CONTEXT_REF_DUPLICATE"),
        (("nope",), "CONTEXT_REF_NOT_FOUND"),
        (("frg_a#.headline",), "CONTEXT_REF_NOT_FOUND"),
        (("frg_a#:nth-child(1) >> :nth-child(2)",), "CONTEXT_REF_NOT_FOUND"),
    ],
)
def test_web_target_validation_refuses_empty_duplicate_unknown_or_malformed_paths(
    targets: tuple[str, ...],
    code: str,
) -> None:
    with pytest.raises(DesignTurnTargetError) as refused:
        validate_web_targets(_web_doc(), targets)

    assert refused.value.code == code


def test_validated_context_refs_accepts_annotated_nodes_on_a_web_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "id": "doc_web",
        "doc_kind": "web",
        "current_version": 9,
        "scene": _web_doc(),
    }

    async def get_document(*_args: object, **_kwargs: object) -> dict[str, object]:
        return document

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        DomainObjectRef(
            workspace_id="ws_1", object_type="design_document", object_id="doc_web", version=9
        ),
        _web_ref("frg_a#:nth-child(1)", "1. Make this shorter"),
        _web_ref("sec_c", "2. Remove this"),
    )

    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws_1",
                refs=refs,
                design_leg_document_ids=("doc_web",),
            )
        )
        == refs
    )


def test_validated_context_refs_refuses_an_unknown_node_on_a_web_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_document(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "id": "doc_web",
            "doc_kind": "web",
            "current_version": 9,
            "scene": _web_doc(),
        }

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        DomainObjectRef(
            workspace_id="ws_1", object_type="design_document", object_id="doc_web", version=9
        ),
        _web_ref("ghost", "1. Make this shorter"),
    )

    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws_1",
                refs=refs,
                design_leg_document_ids=("doc_web",),
            )
        )

    assert refused.value.code == "CONTEXT_REF_NOT_FOUND"


# --- site targets (Puck site documents, Wave 2 Lane A) -----------------------------------------


def _site_doc() -> dict[str, object]:
    return {
        "id": "doc_site",
        "pages": {
            "/": {
                "root": {"props": {}},
                "content": [{"type": "StatsBand", "props": {"id": "proof", "heading": "H"}}],
            },
            "/analysis": {
                "root": {"props": {}},
                "content": [
                    {
                        "type": "FeatureSplit",
                        "props": {"id": "Hero-1a2b", "title": "T", "body": "B"},
                    },
                    {"type": "Quote", "props": {"id": "v2.quote", "quote": "Q"}},
                ],
            },
        },
        "shell": {"header": {"preparedFor": "SCSD", "ctaLabel": "Go"}, "footer": {"legal": "©"}},
    }


def test_site_targets_name_a_component_its_prop_and_the_shell() -> None:
    assert validate_site_targets(
        _site_doc(),
        (
            "site:/analysis#Hero-1a2b.title",
            "site:/#proof",
            "site:shell#header.ctaLabel",
            "site:shell#footer",
            "site:/analysis#v2.quote",
        ),
    ) == (
        SiteTarget(route="/analysis", component_id="Hero-1a2b", prop="title"),
        SiteTarget(route="/", component_id="proof", prop=None),
        SiteTarget(route="shell", component_id="header", prop="ctaLabel"),
        SiteTarget(route="shell", component_id="footer", prop=None),
        # An id with a dot in it is read whole first, so "v2.quote" is a component, not a prop.
        SiteTarget(route="/analysis", component_id="v2.quote", prop=None),
    )


@pytest.mark.parametrize(
    ("targets", "code"),
    [
        ((), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("site:/#proof", "site:/#proof"), "CONTEXT_REF_DUPLICATE"),
        (("frg_a",), "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        (("site:/pricing#proof",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/#ghost",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/#proof.colour",), "CONTEXT_REF_NOT_FOUND"),
        (("site:shell#sidebar",), "CONTEXT_REF_NOT_FOUND"),
        (("site:/Analysis#Hero-1a2b",), "CONTEXT_REF_NOT_FOUND"),
    ],
)
def test_site_targets_refuse_what_the_stored_site_cannot_support(
    targets: tuple[str, ...], code: str
) -> None:
    with pytest.raises(DesignTurnTargetError) as refused:
        validate_site_targets(_site_doc(), targets)
    assert refused.value.code == code


def test_resolve_site_targets_keeps_order_and_notes() -> None:
    resolved = resolve_site_targets(
        _site_doc(),
        [
            _web_ref("doc_site", object_type="design_document"),
            _web_ref("site:/#proof", "1. Bigger"),
            _web_ref("site:shell#header.ctaLabel", "2. Shorter"),
        ],
    )
    assert resolved is not None
    assert [
        (n.target.route, n.target.component_id, n.target.prop, n.note)
        for n in resolved.target_notes
    ] == [
        ("/", "proof", None, "1. Bigger"),
        ("shell", "header", "ctaLabel", "2. Shorter"),
    ]
    assert (
        resolve_site_targets(_site_doc(), [_web_ref("doc_site", object_type="design_document")])
        is None
    )


def test_validated_context_refs_accepts_targets_on_a_site_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_document(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"id": "doc_site", "doc_kind": "site", "current_version": 9, "scene": _site_doc()}

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        DomainObjectRef(
            workspace_id="ws_1", object_type="design_document", object_id="doc_site", version=9
        ),
        _web_ref("site:/analysis#Hero-1a2b.title", "1. Shorter"),
    )
    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws_1",
                refs=refs,
                design_leg_document_ids=("doc_site",),
            )
        )
        == refs
    )
    bad = (refs[0], _web_ref("site:/analysis#nope", "1."))
    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws_1",
                refs=bad,
                design_leg_document_ids=("doc_site",),
            )
        )
    assert refused.value.code == "CONTEXT_REF_NOT_FOUND"
