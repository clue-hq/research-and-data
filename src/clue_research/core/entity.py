"""Entities (M0.2).

``Entity`` is the minimal *resolved reference* — an ``entity_id`` plus its type — that
the ``Resolver`` protocol consumes and that everything keys on. ``AccountEntity`` is the
full account record from substrate §2 (its PK ``id`` is the ``entity_id`` claims reference).

Identity *resolution* (turning a messy name into one of these) is M2; here we only define
the shapes, and the encoding that an entity is keyed by a resolved id, never a free-text
name (a non-UUID ``entity_id``/``id`` is rejected at validation).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core.enums import AccountStatus, EntityType
from clue_research.core.primitives import EntityId


class Entity(BaseModel):
    """A resolved entity reference: the unit every component passes around (substrate §2).

    This is deliberately tiny — a key, not a record — so resolvers/adapters/judges/scorers
    share one shape regardless of how rich the underlying account/contact record is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType


class AccountEntity(BaseModel):
    """``account_entity`` (substrate §2). Contacts resolve *under* accounts (M2), keyed on
    LinkedIn URL / verified email; that contact record is added by M2, not here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EntityId
    canonical_name: str
    primary_domain: str | None = None  # the strong identity key
    aliases: tuple[str, ...] = ()
    hq_geo: dict[str, JsonValue] | None = None
    registry_ids: dict[str, str] = {}  # NPI | DUNS | CIK | LEI ... vertical-dependent
    status: AccountStatus = AccountStatus.CANDIDATE
    merged_into: EntityId | None = None  # set when status == MERGED

    def as_entity(self) -> Entity:
        """The resolved reference for this account (its ``id`` is the claim ``entity_id``)."""
        return Entity(entity_id=self.id, entity_type=EntityType.ACCOUNT)
