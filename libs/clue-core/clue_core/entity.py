"""Entities (M0.2).

``Entity`` is the minimal *resolved reference* — an ``entity_id`` plus its type — that
the ``Resolver`` protocol consumes and that everything keys on. ``AccountEntity`` is the
full account record from substrate §2 (its PK ``id`` is the ``entity_id`` claims reference).

Identity *resolution* (turning a messy name into one of these) is M2; here we only define
the shapes, and the encoding that an entity is keyed by a resolved id, never a free-text
name (a non-UUID ``entity_id``/``id`` is rejected at validation).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core.enums import AccountStatus, EntityType
from clue_core.primitives import EntityId


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
    LinkedIn URL / verified email — modelled by :class:`ContactEntity` (added by M2.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EntityId
    canonical_name: str
    primary_domain: str | None = None  # the strong identity key
    aliases: tuple[str, ...] = ()
    hq_geo: dict[str, JsonValue] | None = None
    registry_ids: dict[str, str] = {}  # NPI | DUNS | CIK | LEI ... vertical-dependent
    status: AccountStatus = AccountStatus.CANDIDATE
    merged_into: EntityId | None = None  # set when status == MERGED
    # Durable identity revision used by C7 research-view/snapshot identity. It changes only when
    # canonical identity state changes; bookkeeping timestamps do not create a new revision.
    canonical_version: int = Field(default=1, ge=1)
    # Workspace tenancy (contract-delta 2026-07-24, [B3×research]): accounts are workspace-local.
    # Required in both the domain shape and DB from migration 82a80fb80c9e; the dev-only legacy
    # NULL state was retired rather than backfilled.
    workspace_id: str

    def as_entity(self) -> Entity:
        """The resolved reference for this account (its ``id`` is the claim ``entity_id``)."""
        return Entity(entity_id=self.id, entity_type=EntityType.ACCOUNT)


class ContactEntity(BaseModel):
    """``contact_entity`` (substrate §2/§7) — a contact resolved *under* an account (M2.1).

    Keyed on its own strong identifiers (``linkedin_url`` / ``verified_email``) with an
    ``account_entity_id`` parent, this is the structural basis for the ``(account, persona)``
    committee graph everything downstream reads. ``jurisdiction`` (Doc D §1, D4 mixed/global) is
    carried from day one so the strict-case machinery has its hook; it stays ``None`` until a
    location claim resolves it (M10). ``AccountStatus`` is the shared candidate→active→merged
    entity lifecycle (it is the *entity* lifecycle, not account-only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EntityId
    account_entity_id: EntityId  # contacts resolve under accounts — the parent is required
    full_name: str | None = None
    linkedin_url: str | None = None  # strong key (unique-when-present)
    verified_email: str | None = None  # strong key (unique-when-present)
    aliases: tuple[str, ...] = ()
    geo: dict[str, JsonValue] | None = None
    jurisdiction: str | None = None  # resolved per Doc D §1; nullable until a location claim lands
    status: AccountStatus = AccountStatus.CANDIDATE
    merged_into: EntityId | None = None  # set when status == MERGED
    canonical_version: int = Field(default=1, ge=1)
    # Workspace tenancy (contract-delta 2026-07-24, [B3×research]): required and denormalized from
    # the parent account; the composite FK makes a mismatch unrepresentable.
    workspace_id: str

    def as_entity(self) -> Entity:
        """The resolved reference for this contact (its ``id`` is the claim ``entity_id``)."""
        return Entity(entity_id=self.id, entity_type=EntityType.CONTACT)
