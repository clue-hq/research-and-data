"""Real composer capabilities for Home and project conversations (repair slice R8).

This module is the narrow join between Lane C's workspace-scoped account/contact reads and
Lane D's durable turn-submission seam. It owns no account or contact state: catalogs come from
the published frontend-read functions, and validation resolves the typed object ids through the
identity store plus the governed contact-profile reader.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import DomainObjectRef
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.frontend_read.account_detail import AccountNotFound
from clue_api.frontend_read.accounts_list import list_accounts
from clue_api.frontend_read.contacts import (
    ContactNotFound,
    read_account_contacts,
    read_contact_profile,
)
from clue_core import EntityId
from clue_research.identity import get_account, get_contact

__all__ = [
    "PROJECT_CONVERSATION_AGENT_PROFILE_ID",
    "PROJECT_CONVERSATION_MODEL_ID",
    "ComposerContextEntity",
    "ContextReferenceError",
    "list_composer_context_entities",
    "prepare_composer_context_entities",
    "validated_context_refs",
]

# One real choice, per the product ruling for R8. The id names the promoted immutable profile;
# the model id is presentation metadata, not an instruction the browser may send independently.
PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v33"
PROJECT_CONVERSATION_MODEL_ID = "openai/gpt-5.6-terra"

_MAX_CONTEXT_ACCOUNTS = 50


class ContextReferenceError(ValueError):
    """A submitted context ref is not usable in the authenticated workspace."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ComposerContextEntity:
    object_type: Literal["account", "contact"]
    object_id: str
    label: str
    secondary_label: str
    image_url: str | None = None
    version: int | None = None


async def list_composer_context_entities(
    conn: AsyncConnection,
    *,
    workspace_id: str,
) -> tuple[ComposerContextEntity, ...]:
    """Return a bounded real account/contact catalog using Lane C's governed reads."""

    accounts = await list_accounts(
        conn,
        workspace_id=workspace_id,
        limit=_MAX_CONTEXT_ACCOUNTS,
    )
    result: list[ComposerContextEntity] = []
    for account in accounts.data:
        result.append(
            ComposerContextEntity(
                object_type="account",
                object_id=str(account.id),
                label=account.name,
                secondary_label=account.domain or "Account",
            )
        )
        try:
            contacts = await read_account_contacts(
                conn,
                workspace_id=workspace_id,
                account_id=account.id,
            )
        except AccountNotFound:  # pragma: no cover - the account page and read share one txn
            continue
        for contact in contacts.data:
            if contact.name is None:
                continue
            result.append(
                ComposerContextEntity(
                    object_type="contact",
                    object_id=str(contact.id),
                    label=contact.name,
                    secondary_label=contact.title or account.name,
                )
            )
    return tuple(result)


async def validated_context_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[DomainObjectRef],
) -> tuple[DomainObjectRef, ...]:
    """Validate tenancy, exact revisions, and any selected contact/account relationship."""

    if any(ref.workspace_id != workspace_id for ref in refs):
        raise ContextReferenceError(
            "CONTEXT_REF_NOT_FOUND",
            "a context reference is not available in this workspace",
        )
    identities = [(ref.object_type, ref.object_id, ref.version) for ref in refs]
    if len(set(identities)) != len(identities):
        raise ContextReferenceError(
            "CONTEXT_REF_DUPLICATE",
            "the same context reference may appear only once in a submission",
        )

    selected_accounts: set[EntityId] = set()
    contact_parents: list[EntityId] = []
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    for ref in refs:
        try:
            entity_id = EntityId(UUID(ref.object_id))
        except ValueError as exc:
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a context reference is not available in this workspace",
            ) from exc
        if ref.object_type == "account":
            account = await get_account(conn, entity_id)
            if (
                account is None
                or account.workspace_id != workspace_id
                or account.merged_into is not None
                or account.id == client_entity_id
            ):
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "an account context reference is not available in this workspace",
                )
            if ref.version is not None and ref.version != account.canonical_version:
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "an account context reference no longer names the current revision",
                )
            selected_accounts.add(account.id)
            continue

        contact = await get_contact(conn, entity_id)
        if (
            contact is None
            or contact.workspace_id != workspace_id
            or contact.merged_into is not None
            or contact.account_entity_id == client_entity_id
        ):
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a contact context reference is not available in this workspace",
            )
        if ref.version is not None and ref.version != contact.canonical_version:
            raise ContextReferenceError(
                "CONTEXT_REF_STALE",
                "a contact context reference no longer names the current revision",
            )
        try:
            await read_contact_profile(
                conn,
                workspace_id=workspace_id,
                account_id=UUID(str(contact.account_entity_id)),
                contact_id=UUID(str(contact.id)),
            )
        except (AccountNotFound, ContactNotFound) as exc:
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a contact context reference is not available in this workspace",
            ) from exc
        contact_parents.append(contact.account_entity_id)

    if selected_accounts and any(parent not in selected_accounts for parent in contact_parents):
        raise ContextReferenceError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "each selected contact must belong to a selected account",
        )
    return tuple(refs)


async def prepare_composer_context_entities(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[DomainObjectRef],
) -> tuple[ComposerContextEntity, ...]:
    """Validate and hydrate an exact draft set without relying on the bounded mention catalog.

    The returned labels are the same display-approved Account/Contact values used by the live
    FI-2 reads. Canonical versions are resolved here and revalidated again when the message is
    submitted; this preparation is draft hydration, never durable authorization.
    """

    validated = await validated_context_refs(
        conn,
        workspace_id=workspace_id,
        refs=refs,
    )
    prepared: list[ComposerContextEntity] = []
    for ref in validated:
        entity_id = EntityId(UUID(ref.object_id))
        if ref.object_type == "account":
            account = await get_account(conn, entity_id)
            if account is None:  # pragma: no cover - validation above owns this invariant
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "an account context reference is not available in this workspace",
                )
            prepared.append(
                ComposerContextEntity(
                    object_type="account",
                    object_id=str(account.id),
                    label=account.canonical_name,
                    secondary_label=account.primary_domain or "Account",
                    version=account.canonical_version,
                )
            )
            continue

        contact = await get_contact(conn, entity_id)
        if contact is None:  # pragma: no cover - validation above owns this invariant
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a contact context reference is not available in this workspace",
            )
        profile = await read_contact_profile(
            conn,
            workspace_id=workspace_id,
            account_id=UUID(str(contact.account_entity_id)),
            contact_id=UUID(str(contact.id)),
        )
        prepared.append(
            ComposerContextEntity(
                object_type="contact",
                object_id=str(contact.id),
                label=profile.name or "Unnamed contact",
                secondary_label=profile.title or profile.account_name,
                version=contact.canonical_version,
            )
        )
    return tuple(prepared)
