from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from clue_agents import DomainObjectRef
from clue_api.arv2.display.gather import SubjectRef
from clue_api.chat import composer_context
from clue_api.chat.composer_context import (
    ContextReferenceError,
    prepare_composer_context_entities,
    validated_context_refs,
)
from clue_core import EntityId

ACCOUNT_A = EntityId(UUID("00000000-0000-0000-0000-0000000008a1"))
ACCOUNT_B = EntityId(UUID("00000000-0000-0000-0000-0000000008b1"))
CONTACT_A = EntityId(UUID("00000000-0000-0000-0000-0000000008c1"))


def _member(
    contact_id: EntityId,
    *,
    account_id: EntityId,
    name: str = "A Person",
    account_name: str = "An Account",
) -> SubjectRef:
    """One row of D2's committee — the addressability rule the composer now applies."""
    return SubjectRef(
        kind="contact",
        id=str(contact_id),
        name=name,
        account_id=str(account_id),
        account_name=account_name,
        account_domain=None,
    )


def _ref(object_type: str, object_id: EntityId, *, version: int | None = None):
    return DomainObjectRef(
        workspace_id="ws-r8-context",
        object_type=object_type,
        object_id=str(object_id),
        version=version,
    )


def _design_ref(object_type: str, object_id: str, *, version: int | None = None):
    return DomainObjectRef(
        workspace_id="ws-r8-context",
        object_type=object_type,
        object_id=object_id,
        version=version,
    )


def test_context_validation_preserves_order_and_checks_contact_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = {
        ACCOUNT_A: SimpleNamespace(
            id=ACCOUNT_A,
            workspace_id="ws-r8-context",
            canonical_version=3,
            merged_into=None,
        ),
        ACCOUNT_B: SimpleNamespace(
            id=ACCOUNT_B,
            workspace_id="ws-r8-context",
            canonical_version=1,
            merged_into=None,
        ),
    }
    contact = SimpleNamespace(
        id=CONTACT_A,
        workspace_id="ws-r8-context",
        account_entity_id=ACCOUNT_A,
        canonical_version=4,
        merged_into=None,
    )

    async def get_account(_conn: object, entity_id: EntityId):
        return accounts.get(entity_id)

    async def get_contact(_conn: object, entity_id: EntityId):
        return contact if entity_id == CONTACT_A else None

    async def committee_members(_conn: object, *, workspace_id: str, account_id: str):
        del workspace_id
        return [_member(CONTACT_A, account_id=ACCOUNT_A)] if account_id == str(ACCOUNT_A) else []

    async def workspace_client_entity_id(*_args: object, **_kwargs: object):
        return None

    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(composer_context, "get_contact", get_contact)
    monkeypatch.setattr(composer_context, "committee_members", committee_members)
    monkeypatch.setattr(
        composer_context,
        "workspace_client_entity_id",
        workspace_client_entity_id,
    )

    ordered = (_ref("contact", CONTACT_A, version=4), _ref("account", ACCOUNT_A, version=3))
    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=ordered,
            )
        )
        == ordered
    )

    with pytest.raises(ContextReferenceError) as mismatch:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("account", ACCOUNT_B), _ref("contact", CONTACT_A)),
            )
        )
    assert mismatch.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH"


def test_context_validation_refuses_stale_or_duplicate_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(
        id=ACCOUNT_A,
        workspace_id="ws-r8-context",
        canonical_version=3,
        merged_into=None,
    )

    async def get_account(_conn: object, _entity_id: EntityId):
        return account

    async def workspace_client_entity_id(*_args: object, **_kwargs: object):
        return None

    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(
        composer_context,
        "workspace_client_entity_id",
        workspace_client_entity_id,
    )

    with pytest.raises(ContextReferenceError) as stale:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("account", ACCOUNT_A, version=2),),
            )
        )
    assert stale.value.code == "CONTEXT_REF_STALE"

    duplicate = _ref("account", ACCOUNT_A)
    with pytest.raises(ContextReferenceError) as repeated:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(duplicate, duplicate),
            )
        )
    assert repeated.value.code == "CONTEXT_REF_DUPLICATE"


def test_context_validation_refuses_the_workspace_client_and_its_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(
        id=ACCOUNT_A,
        workspace_id="ws-r8-context",
        canonical_version=3,
        merged_into=None,
    )
    contact = SimpleNamespace(
        id=CONTACT_A,
        workspace_id="ws-r8-context",
        account_entity_id=ACCOUNT_A,
        canonical_version=4,
        merged_into=None,
    )

    async def get_account(_conn: object, _entity_id: EntityId):
        return account

    async def get_contact(_conn: object, _entity_id: EntityId):
        return contact

    async def workspace_client_entity_id(*_args: object, **_kwargs: object):
        return ACCOUNT_A

    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(composer_context, "get_contact", get_contact)
    monkeypatch.setattr(
        composer_context,
        "workspace_client_entity_id",
        workspace_client_entity_id,
    )

    for refs in ((_ref("account", ACCOUNT_A),), (_ref("contact", CONTACT_A),)):
        with pytest.raises(ContextReferenceError) as unavailable:
            asyncio.run(
                validated_context_refs(
                    object(),  # type: ignore[arg-type]
                    workspace_id="ws-r8-context",
                    refs=refs,
                )
            )
        assert unavailable.value.code == "CONTEXT_REF_NOT_FOUND"


def test_context_validation_accepts_exact_nodes_only_on_the_open_leg_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "id": "doc_target",
        "doc_kind": "scene",
        "current_version": 7,
        "scene": {
            "pages": {"page_ad": {"id": "page_ad", "children": ["frame"]}},
            "nodes": {
                "frame": {"children": ["headline"]},
                "headline": {"children": []},
            },
        },
    }

    async def get_document(*_args: object, **_kwargs: object):
        return document

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        _design_ref("design_document", "doc_target", version=7),
        _design_ref("design_node", "headline", version=7),
    )

    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=refs,
                design_leg_document_ids=("doc_target",),
            )
        )
        == refs
    )

    with pytest.raises(ContextReferenceError) as wrong_leg:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=refs,
                design_leg_document_ids=("doc_other",),
            )
        )
    assert wrong_leg.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH"


def test_context_validation_accepts_nodes_on_any_document_of_a_multi_document_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §3.7: a leg holds MANY documents, and the targeted one only has to be in the set."""

    def _scene(document_id: str) -> dict[str, object]:
        return {
            "id": document_id,
            "doc_kind": "scene",
            "current_version": 7,
            "scene": {
                "pages": {"page_ad": {"id": "page_ad", "children": ["frame"]}},
                "nodes": {
                    "frame": {"children": ["headline"]},
                    "headline": {"children": []},
                },
            },
        }

    documents_by_id = {"doc_first": _scene("doc_first"), "doc_second": _scene("doc_second")}

    async def get_document(*_args: object, document_id: str, **_kwargs: object):
        from clue_design.errors import DesignNotFoundError

        try:
            return documents_by_id[document_id]
        except KeyError:
            raise DesignNotFoundError("design_document", document_id) from None

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        _design_ref("design_document", "doc_second", version=7),
        _design_ref("design_node", "headline", version=7),
    )

    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=refs,
                design_leg_document_ids=("doc_first", "doc_second"),
            )
        )
        == refs
    )

    with pytest.raises(ContextReferenceError) as off_the_leg:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=refs,
                design_leg_document_ids=("doc_first",),
            )
        )
    assert off_the_leg.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH"


@pytest.mark.parametrize(
    ("node_id", "node_version", "code"),
    [
        ("headline", 6, "CONTEXT_REF_STALE"),
        ("missing", 7, "CONTEXT_REF_NOT_FOUND"),
    ],
)
def test_context_validation_refuses_stale_or_missing_design_nodes(
    monkeypatch: pytest.MonkeyPatch,
    node_id: str,
    node_version: int,
    code: str,
) -> None:
    async def get_document(*_args: object, **_kwargs: object):
        return {
            "id": "doc_target",
            "doc_kind": "scene",
            "current_version": 7,
            "scene": {
                "pages": {"page_ad": {"id": "page_ad", "children": ["headline"]}},
                "nodes": {"headline": {"children": []}},
            },
        }

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    refs = (
        _design_ref("design_document", "doc_target", version=7),
        _design_ref("design_node", node_id, version=node_version),
    )

    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=refs,
                design_leg_document_ids=("doc_target",),
            )
        )
    assert refused.value.code == code


def test_context_preparation_hydrates_exact_records_beyond_the_bounded_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(
        id=ACCOUNT_A,
        canonical_name="Exact Account",
        primary_domain="exact.example",
        canonical_version=8,
    )
    contact = SimpleNamespace(
        id=CONTACT_A,
        account_entity_id=ACCOUNT_A,
        canonical_version=11,
    )

    async def validate(_conn: object, *, refs: object, **_kwargs: object):
        return refs

    async def get_account(_conn: object, _entity_id: EntityId):
        return account

    async def get_contact(_conn: object, _entity_id: EntityId):
        return contact

    async def committee_members(_conn: object, **_kwargs: object):
        return [_member(CONTACT_A, account_id=ACCOUNT_A, name="", account_name="Exact Account")]

    async def account_logo_urls(_conn: object, **_kwargs: object):
        return {}

    monkeypatch.setattr(composer_context, "validated_context_refs", validate)
    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(composer_context, "get_contact", get_contact)
    monkeypatch.setattr(composer_context, "committee_members", committee_members)
    monkeypatch.setattr(composer_context, "_account_logo_urls", account_logo_urls)

    refs = (_ref("contact", CONTACT_A), _ref("account", ACCOUNT_A))
    prepared = asyncio.run(
        prepare_composer_context_entities(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs,
            settings=SimpleNamespace(brandfetch_client_id="cid"),  # type: ignore[arg-type]
        )
    )
    assert [(item.object_type, item.object_id) for item in prepared] == [
        ("contact", str(CONTACT_A)),
        ("account", str(ACCOUNT_A)),
    ]
    assert prepared[0].label == "Unnamed contact"
    assert prepared[0].secondary_label == "Exact Account"
    assert prepared[0].version == 11
    assert prepared[1].label == "Exact Account"
    assert prepared[1].version == 8
    # The account carries the same logo the accounts screens show — Brandfetch's Logo API for
    # its domain when no mark is stored; a contact carries none (the composer draws initials).
    assert prepared[1].image_url is not None
    assert prepared[1].image_url.startswith("https://cdn.brandfetch.io/domain/exact.example/")
    assert prepared[0].image_url is None
    # A contact names its account so the picker can nest it; an account names none.
    assert prepared[0].account_id == str(ACCOUNT_A)
    assert prepared[0].account_name == "Exact Account"
    assert prepared[1].account_id is None


PLAN_DOCUMENT = UUID("00000000-0000-0000-0000-00000000d0c1")


def _plan_row(version: int = 2, status: str = "ready"):
    return SimpleNamespace(
        document_id=PLAN_DOCUMENT,
        path="project/plan.md",
        kind="project-plan",
        version=version,
        status=status,
        updated_at=None,
        artifact_key="ws/abc",
        artifact_sha256="a" * 64,
        icp_key=None,
    )


def test_project_document_refs_require_a_project_and_pin_the_latest_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_project_document(*_args: object, **kwargs: object):
        return _plan_row() if kwargs["document_id"] == PLAN_DOCUMENT else None

    async def latest_project_document_version(*_args: object, **_kwargs: object):
        return 2

    monkeypatch.setattr(composer_context, "get_project_document", get_project_document)
    monkeypatch.setattr(
        composer_context, "latest_project_document_version", latest_project_document_version
    )

    pinned = (_ref("project_document", PLAN_DOCUMENT, version=2),)
    assert (
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=pinned,
                project_id="prj_1",
            )
        )
        == pinned
    )

    with pytest.raises(ContextReferenceError) as no_project:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=pinned,
            )
        )
    assert no_project.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH"

    with pytest.raises(ContextReferenceError) as unpinned:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", PLAN_DOCUMENT),),
                project_id="prj_1",
            )
        )
    assert unpinned.value.code == "CONTEXT_REF_STALE"

    with pytest.raises(ContextReferenceError) as missing:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", ACCOUNT_A, version=2),),
                project_id="prj_1",
            )
        )
    assert missing.value.code == "CONTEXT_REF_NOT_FOUND"


def test_project_document_refs_refuse_a_superseded_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_project_document(*_args: object, **_kwargs: object):
        return _plan_row(version=2)

    async def latest_project_document_version(*_args: object, **_kwargs: object):
        return 3

    monkeypatch.setattr(composer_context, "get_project_document", get_project_document)
    monkeypatch.setattr(
        composer_context, "latest_project_document_version", latest_project_document_version
    )
    with pytest.raises(ContextReferenceError) as stale:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", PLAN_DOCUMENT, version=2),),
                project_id="prj_1",
            )
        )
    assert stale.value.code == "CONTEXT_REF_STALE"

    # The common real shape: rewriting the document retired the version the user tagged. The
    # retired row is still this project's row, so it is refused as stale, never as missing.
    async def superseded_row(*_args: object, **_kwargs: object):
        return _plan_row(version=2, status="superseded")

    monkeypatch.setattr(composer_context, "get_project_document", superseded_row)
    with pytest.raises(ContextReferenceError) as retired:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_ref("project_document", PLAN_DOCUMENT, version=2),),
                project_id="prj_1",
            )
        )
    assert retired.value.code == "CONTEXT_REF_STALE"


def test_design_document_mentions_must_belong_to_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_document(*_args: object, **_kwargs: object):
        return {"id": "doc_site", "doc_kind": "web", "current_version": 4}

    async def project_design_documents(*_args: object, **_kwargs: object):
        return ({"id": "doc_other"},)

    from clue_design import documents

    monkeypatch.setattr(documents, "get_document", get_document)
    monkeypatch.setattr(composer_context, "project_design_documents", project_design_documents)
    with pytest.raises(ContextReferenceError) as foreign:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id="ws-r8-context",
                refs=(_design_ref("design_document", "doc_site", version=4),),
                project_id="prj_1",
            )
        )
    assert foreign.value.code == "CONTEXT_REF_NOT_FOUND"

    async def containing(*_args: object, **_kwargs: object):
        return ({"id": "doc_site"},)

    monkeypatch.setattr(composer_context, "project_design_documents", containing)
    accepted = asyncio.run(
        validated_context_refs(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=(_design_ref("design_document", "doc_site", version=4),),
            project_id="prj_1",
        )
    )
    assert accepted[0].object_id == "doc_site"


def test_context_ref_presentations_label_files_and_design_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clue_api.chat.composer_context import context_ref_presentations

    async def project_document_rows(*_args: object, **_kwargs: object):
        return {
            str(PLAN_DOCUMENT): SimpleNamespace(
                document_id=PLAN_DOCUMENT,
                project_id="prj_1",
                path="project/plan.md",
                kind="project-plan",
            )
        }

    async def design_document_rows(*_args: object, **_kwargs: object):
        return {"doc_site": {"id": "doc_site", "title": "Spring launch page", "doc_kind": "web"}}

    async def read_project_document(*_args: object, **_kwargs: object):
        return (None, {"title": "Q4 expansion plan"}, "# ignored\n")

    monkeypatch.setattr(composer_context, "_project_document_rows", project_document_rows)
    monkeypatch.setattr(composer_context, "_design_document_rows", design_document_rows)
    monkeypatch.setattr(composer_context, "read_project_document", read_project_document)

    refs = (
        _ref("project_document", PLAN_DOCUMENT, version=2),
        _design_ref("design_document", "doc_site", version=4),
        _ref("account", ACCOUNT_A),
    )
    presentations = asyncio.run(
        context_ref_presentations(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs,
            storage=object(),  # type: ignore[arg-type]
        )
    )
    assert presentations[("project_document", str(PLAN_DOCUMENT))] == {
        "label": "Q4 expansion plan",
        "kind": "project-plan",
    }
    assert presentations[("design_document", "doc_site")] == {
        "label": "Spring launch page",
        "kind": "web",
    }
    assert ("account", str(ACCOUNT_A)) not in presentations

    no_storage = asyncio.run(
        context_ref_presentations(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs[:1],
        )
    )
    assert no_storage[("project_document", str(PLAN_DOCUMENT))]["label"] == "plan"
