"""M0.2 acceptance: entities key on a resolved id, never a free-text name (substrate §2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import AccountEntity, AccountStatus, Entity, EntityType, new_entity_id


def test_entity_requires_a_resolved_uuid_not_a_name() -> None:
    eid = new_entity_id()
    entity = Entity(entity_id=eid, entity_type=EntityType.ACCOUNT)
    assert entity.entity_id == eid
    # a free-text company name is not a resolved entity_id
    with pytest.raises(ValidationError):
        Entity(entity_id="Acme Corporation", entity_type=EntityType.ACCOUNT)  # type: ignore[arg-type]


def test_account_entity_defaults_and_as_entity() -> None:
    acct = AccountEntity(id=new_entity_id(), canonical_name="Acme", primary_domain="acme.com")
    assert acct.status is AccountStatus.CANDIDATE
    assert acct.aliases == ()
    ref = acct.as_entity()
    assert ref.entity_type is EntityType.ACCOUNT
    assert ref.entity_id == acct.id


def test_account_entity_carries_registry_ids_and_merge_target() -> None:
    target = new_entity_id()
    acct = AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme",
        registry_ids={"DUNS": "123456789"},
        status=AccountStatus.MERGED,
        merged_into=target,
    )
    assert acct.registry_ids["DUNS"] == "123456789"
    assert acct.merged_into == target
