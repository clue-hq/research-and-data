"""Real composer capabilities for Home and project conversations (repair slice R8).

This module is the narrow join between the workspace-scoped account/contact reads and Lane D's
durable turn-submission seam. It owns no account or contact state: the account catalog is the
accounts table's own page scan, the contact catalog and the contact addressability rule are D2's
committee (the contacts under an account that hold at least one live claim, which is exactly the
set the contacts table lists), and versions come from the identity store.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import DomainObjectRef
from clue_api.arv2.display.gather import SubjectRef, committee_members
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.design_turn_targets import DesignTurnTargetError, resolve_scene_targets
from clue_api.frontend_read.accounts_list import read_spine_page
from clue_core import EntityId
from clue_research.identity import get_account, get_contact
from clue_storage import StorageBackend

__all__ = [
    "PROJECT_CONVERSATION_AGENT_PROFILE_ID",
    "PROJECT_CONVERSATION_MODEL_ID",
    "MAX_DESIGN_REFERENCE_ASSETS",
    "ComposerContextEntity",
    "ContextReferenceError",
    "design_asset_ref_presentations",
    "list_composer_context_entities",
    "prepare_composer_context_entities",
    "validated_context_refs",
]

# One real choice, per the product ruling for R8. The id names the promoted immutable profile;
# the model id is presentation metadata, not an instruction the browser may send independently.
PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v52"
PROJECT_CONVERSATION_MODEL_ID = "x-ai/grok-4.6"

_MAX_CONTEXT_ACCOUNTS = 50
MAX_DESIGN_REFERENCE_ASSETS = 4
_DESIGN_REFERENCE_IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}
)
_SHA256_SHAPE = re.compile(r"^[0-9a-f]{64}$")


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


async def _contact_subject(
    conn: AsyncConnection, *, workspace_id: str, contact: Any
) -> SubjectRef | None:
    """The contact as the screens show them, or ``None`` when nothing addresses them.

    The rule is D2's committee — the contacts under this account that hold at least one live
    claim — which is exactly the set the contacts table lists and this picker offers. A contact row
    the research has written nothing about is not referenceable: the card it would compile has a
    name in it and nothing else.
    """

    members = await committee_members(
        conn, workspace_id=workspace_id, account_id=str(contact.account_entity_id)
    )
    return next((member for member in members if member.id == str(contact.id)), None)


async def list_composer_context_entities(
    conn: AsyncConnection,
    *,
    workspace_id: str,
) -> tuple[ComposerContextEntity, ...]:
    """Return a bounded real account/contact catalog: the workspace's newest accounts, each with
    the contacts its research has actually written about."""

    _total, rows, _has_more = await read_spine_page(
        conn,
        workspace_id=workspace_id,
        project_id=None,
        limit=_MAX_CONTEXT_ACCOUNTS,
        cursor=None,
        page_number=None,
    )
    result: list[ComposerContextEntity] = []
    for account_id, canonical_name, primary_domain, _created_at, _updated_at in rows:
        name = str(canonical_name)
        result.append(
            ComposerContextEntity(
                object_type="account",
                object_id=str(account_id),
                label=name,
                secondary_label=primary_domain or "Account",
            )
        )
        for member in await committee_members(
            conn, workspace_id=workspace_id, account_id=str(account_id)
        ):
            if not member.name:
                continue
            result.append(
                ComposerContextEntity(
                    object_type="contact",
                    object_id=member.id,
                    label=member.name,
                    secondary_label=member.title or name,
                )
            )
    return tuple(result)


async def validated_context_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[DomainObjectRef],
    design_leg_document_id: str | None = None,
    storage: StorageBackend | None = None,
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

    design_nodes = tuple(ref for ref in refs if ref.object_type == "design_node")
    design_assets = tuple(ref for ref in refs if ref.object_type == "design_asset")
    if len(design_assets) > MAX_DESIGN_REFERENCE_ASSETS:
        raise ContextReferenceError(
            "CONTEXT_REF_LIMIT_EXCEEDED",
            f"a design turn accepts at most {MAX_DESIGN_REFERENCE_ASSETS} reference images",
        )
    target_document: dict[str, Any] | None = None
    target_document_ref: DomainObjectRef | None = None
    if design_nodes:
        document_refs = tuple(ref for ref in refs if ref.object_type == "design_document")
        if len(document_refs) != 1 or design_leg_document_id is None:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design node targets require the open design leg's one document reference",
            )
        target_document_ref = document_refs[0]
        if target_document_ref.object_id != design_leg_document_id:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "the targeted design document is not the open design leg's document",
            )
        if target_document_ref.version is None or any(
            ref.version != target_document_ref.version for ref in design_nodes
        ):
            raise ContextReferenceError(
                "CONTEXT_REF_STALE",
                "design document and node targets must carry the same exact document version",
            )
        from clue_design.documents import get_document as get_design_document
        from clue_design.errors import DesignNotFoundError

        try:
            target_document = await get_design_document(
                conn,
                workspace_id=workspace_id,
                document_id=target_document_ref.object_id,
            )
        except DesignNotFoundError as exc:
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "the targeted design document is not available in this workspace",
            ) from exc
        if target_document.get("doc_kind") != "scene":
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design node targets require a scene document",
            )
        if target_document_ref.version != target_document.get("current_version"):
            raise ContextReferenceError(
                "CONTEXT_REF_STALE",
                "the targeted design document no longer names the current version",
            )
        try:
            resolve_scene_targets(
                target_document.get("scene") or {},
                tuple(ref.object_id for ref in design_nodes),
            )
        except DesignTurnTargetError as exc:
            raise ContextReferenceError(exc.code, exc.message) from exc

    if design_assets:
        if design_leg_document_id is None:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design reference images require an open design leg",
            )
        if any(ref.version is not None for ref in design_assets):
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design asset references do not carry a document version",
            )
        if storage is None:
            raise ContextReferenceError(
                "CAPABILITY_UNAVAILABLE",
                "this deployment cannot verify design reference image bytes",
            )
        from clue_design.assets import get_asset_records
        from clue_design.documents import get_document as get_design_document
        from clue_design.errors import DesignNotFoundError
        from clue_design.storage import read_design_blob

        if target_document is None:
            try:
                target_document = await get_design_document(
                    conn,
                    workspace_id=workspace_id,
                    document_id=design_leg_document_id,
                )
            except DesignNotFoundError as exc:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "the open design leg document is not available in this workspace",
                ) from exc
        if target_document.get("doc_kind") != "scene":
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "reference images are available only for scene-design turns",
            )

        asset_ids = tuple(ref.object_id for ref in design_assets)
        records = await get_asset_records(
            conn,
            workspace_id=workspace_id,
            asset_ids=asset_ids,
        )
        for asset_id in asset_ids:
            wrapped = records.get(asset_id)
            if wrapped is None:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a design reference image is not available in this workspace",
                )
            asset = wrapped.get("asset") or {}
            media = asset.get("media") or {}
            digest = media.get("digest") or {}
            mime_type = str(media.get("mime_type") or "").lower()
            sha256 = str(digest.get("value") or "")
            if asset.get("status") != "ready":
                raise ContextReferenceError(
                    "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                    "a design reference image is not ready",
                )
            if mime_type not in _DESIGN_REFERENCE_IMAGE_TYPES:
                raise ContextReferenceError(
                    "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                    "design references must be PNG, JPEG, WebP, or SVG images",
                )
            if digest.get("algorithm") != "sha256" or not _SHA256_SHAPE.fullmatch(sha256):
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a design reference image has no readable durable bytes",
                )
            try:
                stored_media_type, data = await read_design_blob(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    sha256=sha256,
                )
            except DesignNotFoundError as exc:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a design reference image has no readable durable bytes",
                ) from exc
            if stored_media_type.lower() not in _DESIGN_REFERENCE_IMAGE_TYPES:
                raise ContextReferenceError(
                    "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                    "design references must have image bytes in durable storage",
                )
            if not data:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a design reference image has no readable durable bytes",
                )

    selected_accounts: set[EntityId] = set()
    contact_parents: list[EntityId] = []
    has_entity_refs = any(ref.object_type in {"account", "contact"} for ref in refs)
    client_entity_id = (
        await workspace_client_entity_id(conn, workspace_id=workspace_id)
        if has_entity_refs
        else None
    )
    for ref in refs:
        if ref.object_type == "design_document":
            # P3.1 (master plan §2.4): design ids are strings, not entity UUIDs, and the
            # version check is the document's CAS counter (PD-part3 D5).
            from clue_design.documents import get_document as get_design_document
            from clue_design.errors import DesignNotFoundError

            if target_document_ref is not None and ref == target_document_ref:
                document = target_document
            else:
                try:
                    document = await get_design_document(
                        conn, workspace_id=workspace_id, document_id=ref.object_id
                    )
                except DesignNotFoundError as exc:
                    raise ContextReferenceError(
                        "CONTEXT_REF_NOT_FOUND",
                        "a design document context reference is not available in this workspace",
                    ) from exc
            assert document is not None
            if ref.version is not None and ref.version != document.get("current_version"):
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "a design document context reference no longer names the current version",
                )
            continue
        if ref.object_type == "design_node":
            # Validated as one document-scoped set above. A node id is not a
            # platform entity UUID and must never fall into the contact branch.
            continue
        if ref.object_type == "design_asset":
            # Validated as one bounded, scene-leg-scoped set above. Asset ids are opaque design
            # ids, never platform entity UUIDs.
            continue
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
        if await _contact_subject(conn, workspace_id=workspace_id, contact=contact) is None:
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a contact context reference is not available in this workspace",
            )
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

    The returned labels are the same values the live Account/Contact reads serve. Canonical
    versions are resolved here and revalidated again when the message is submitted; this
    preparation is draft hydration, never durable authorization.
    """

    validated = await validated_context_refs(
        conn,
        workspace_id=workspace_id,
        refs=refs,
    )
    prepared: list[ComposerContextEntity] = []
    for ref in validated:
        if ref.object_type not in {"account", "contact"}:
            # This endpoint hydrates mention-picker entities only. Design refs can be present on
            # durable messages, but they are presented from their owning design read models.
            continue
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
        subject = await _contact_subject(conn, workspace_id=workspace_id, contact=contact)
        if subject is None:  # pragma: no cover - validation above owns this invariant
            raise ContextReferenceError(
                "CONTEXT_REF_NOT_FOUND",
                "a contact context reference is not available in this workspace",
            )
        prepared.append(
            ComposerContextEntity(
                object_type="contact",
                object_id=str(contact.id),
                label=subject.name or "Unnamed contact",
                secondary_label=subject.title or subject.account_name,
                version=contact.canonical_version,
            )
        )
    return tuple(prepared)


async def design_asset_ref_presentations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[Any],
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve durable design-asset refs to read-time labels and thumbnail digests.

    The append-only submission row remains the source of *which* asset was submitted. Mutable
    presentation metadata stays in the design asset library and is joined only while reading the
    transcript, so filenames and thumbnails are not denormalized into the durable turn receipt.
    """

    asset_ids = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "design_asset")
    )
    if not asset_ids:
        return {}
    from clue_design.assets import get_asset_records

    records = await get_asset_records(
        conn,
        workspace_id=workspace_id,
        asset_ids=asset_ids,
    )
    result: dict[tuple[str, str], dict[str, str]] = {}
    for asset_id, wrapped in records.items():
        asset = wrapped.get("asset") or {}
        media = asset.get("media") or {}
        thumbnail = media.get("thumbnail") or {}
        thumbnail_digest = thumbnail.get("digest") or media.get("digest") or {}
        presentation = {
            "label": str(media.get("filename") or asset.get("label") or "Reference image"),
            "media_type": str(media.get("mime_type") or ""),
        }
        digest_value = thumbnail_digest.get("value")
        if thumbnail_digest.get("algorithm") == "sha256" and digest_value:
            presentation["thumbnail_digest"] = str(digest_value)
        result[("design_asset", asset_id)] = presentation
    return result
