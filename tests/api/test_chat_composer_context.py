from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from clue_agents import DomainObjectRef
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


def _ref(object_type: str, object_id: EntityId, *, version: int | None = None):
    return DomainObjectRef(
        workspace_id="ws-r8-context",
        object_type=object_type,
        object_id=str(object_id),
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

    async def read_contact_profile(*_args: object, **_kwargs: object):
        return SimpleNamespace()

    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(composer_context, "get_contact", get_contact)
    monkeypatch.setattr(composer_context, "read_contact_profile", read_contact_profile)

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

    monkeypatch.setattr(composer_context, "get_account", get_account)

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

    async def read_contact_profile(*_args: object, **_kwargs: object):
        return SimpleNamespace(name=None, title=None, account_name="Exact Account")

    monkeypatch.setattr(composer_context, "validated_context_refs", validate)
    monkeypatch.setattr(composer_context, "get_account", get_account)
    monkeypatch.setattr(composer_context, "get_contact", get_contact)
    monkeypatch.setattr(composer_context, "read_contact_profile", read_contact_profile)

    refs = (_ref("contact", CONTACT_A), _ref("account", ACCOUNT_A))
    prepared = asyncio.run(
        prepare_composer_context_entities(
            object(),  # type: ignore[arg-type]
            workspace_id="ws-r8-context",
            refs=refs,
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
