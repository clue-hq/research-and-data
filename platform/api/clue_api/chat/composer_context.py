"""Real composer capabilities for Home and project conversations (repair slice R8).

This module is the narrow join between the workspace-scoped account/contact reads and Lane D's
durable turn-submission seam. It owns no account or contact state: the account catalog is the
accounts table's own page scan, the contact catalog and the contact addressability rule are D2's
committee (the contacts under an account that hold at least one live claim, which is exactly the
set the contacts table lists), and versions come from the identity store.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import DomainObjectRef
from clue_api.arv2.display.gather import (
    SubjectRef,
    committee_members,
    committee_members_for_accounts,
)
from clue_api.arv2.project_documents import (
    document_title,
    get_project_document,
    latest_project_document_version,
    read_project_document,
)
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.design_leg_wiring import project_design_documents, wire_kind
from clue_api.design_turn_targets import (
    DesignTurnTargetError,
    resolve_scene_targets,
    validate_site_targets,
    validate_web_targets,
)
from clue_api.frontend_read.accounts_list import read_spine_page
from clue_api.frontend_read.v1_shared import account_logo_path
from clue_api.knowledge_bytes import read_knowledge_bytes
from clue_config import Settings
from clue_core import EntityId
from clue_research.claimstore import WorkspaceScope, current_values
from clue_research.identity import get_account, get_contact
from clue_storage import StorageBackend

__all__ = [
    "PROJECT_CONVERSATION_AGENT_PROFILE_ID",
    "PROJECT_CONVERSATION_MODEL_ID",
    "MAX_DESIGN_REFERENCE_ASSETS",
    "ComposerContextEntity",
    "ContextReferenceError",
    "PRESENTED_REF_TYPES",
    "context_ref_presentations",
    "list_composer_context_entities",
    "prepare_composer_context_entities",
    "validated_context_refs",
]

# One real choice, per the product ruling for R8. The id names the promoted immutable profile;
# the model id is presentation metadata, not an instruction the browser may send independently.
# v58 grants `run_python@1` — one short script per call in a locked-down container over the
# turn's own workspace — and mounts the project's `attachments/` read-only, so a human who
# attaches a PDF, a deck or a spreadsheet gets an answer about what is in it. v59 moves
# `open_design_leg` to @5, so one ask can open one leg that births many artifacts, and v60 is the
# prompt that stops telling the user to speak before generation begins: the leg's first design
# turn is queued from the message that opened it.
PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v74"
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
    #: A contact's account — the id the picker nests it under and the name search shows beside
    #: it. Always both or neither; an account entity carries neither.
    account_id: str | None = None
    account_name: str | None = None


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


async def _account_logo_urls(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, Any]:
    """Each account's stored ``core.logo_url`` under the workspace scope, in one read."""

    if not account_ids:
        return {}
    values = await current_values(
        conn,
        list(account_ids),
        ("core.logo_url",),
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    return {entity_id: current.value_json for (entity_id, _field), current in values.items()}


def account_context_entity(
    account_id: Any,
    name: str,
    primary_domain: str | None,
    logo: Any,
    *,
    settings: Settings | None,
) -> ComposerContextEntity:
    """One account as the picker shows it (shared by the bounded list and the directory)."""

    return ComposerContextEntity(
        object_type="account",
        object_id=str(account_id),
        label=name,
        secondary_label=primary_domain or "Account",
        image_url=account_logo_path(account_id, logo, domain=primary_domain, settings=settings),
    )


def contact_context_entity(
    member: SubjectRef, *, account_id: str, account_name: str
) -> ComposerContextEntity:
    """One committee contact as the picker shows it, nested under its account."""

    return ComposerContextEntity(
        object_type="contact",
        object_id=member.id,
        label=member.name,
        secondary_label=member.title or account_name,
        account_id=account_id,
        account_name=account_name,
    )


async def list_composer_context_entities(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    settings: Settings | None = None,
) -> tuple[ComposerContextEntity, ...]:
    """Return a bounded real account/contact catalog: the workspace's newest accounts, each with
    the contacts its research has actually written about.

    An account's ``image_url`` is the same logo the accounts screens show (``account_logo_path``:
    the platform's logo route for a stored mark, else Brandfetch's Logo API for the domain when
    ``settings`` carries a client id). Contacts carry no image; the composer draws their initials.
    """

    _total, rows, _has_more = await read_spine_page(
        conn,
        workspace_id=workspace_id,
        project_id=None,
        limit=_MAX_CONTEXT_ACCOUNTS,
        cursor=None,
        page_number=None,
    )
    logo_urls = await _account_logo_urls(
        conn,
        workspace_id=workspace_id,
        account_ids=[EntityId(UUID(str(row[0]))) for row in rows],
    )
    # One batched committee read for the whole page (it was one query per account).
    committees = await committee_members_for_accounts(
        conn, workspace_id=workspace_id, account_ids=[str(row[0]) for row in rows]
    )
    result: list[ComposerContextEntity] = []
    for account_id, canonical_name, primary_domain, _created_at, _updated_at in rows:
        result.append(
            account_context_entity(
                account_id,
                str(canonical_name),
                primary_domain,
                logo_urls.get(EntityId(UUID(str(account_id)))),
                settings=settings,
            )
        )
        result.extend(
            contact_context_entity(
                member, account_id=str(account_id), account_name=str(canonical_name)
            )
            for member in committees.get(str(account_id), [])
            if member.name
        )
    return tuple(result)


async def validated_context_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[DomainObjectRef],
    design_leg_document_ids: tuple[str, ...] = (),
    storage: StorageBackend | None = None,
    project_id: str | None = None,
) -> tuple[DomainObjectRef, ...]:
    """Validate tenancy, exact revisions, project containment, and contact/account relationship.

    ``project_id`` is the project the composer belongs to. ``project_document`` refs require it
    (a Gallery file is only addressable inside its project); ``design_document`` refs are
    additionally contained to the project's own design documents when it is given. The Home
    bootstrap has no project yet and passes ``None``.

    ``design_leg_document_ids`` is the open design leg's whole document SET (spec §3.7): a leg
    holds many documents, so a node target only has to name one of them, and reference images
    ride a leg whose documents are all scene-kind. Empty means no leg is open.
    """

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
        if len(document_refs) != 1 or not design_leg_document_ids:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design node targets require one document reference on the open design leg",
            )
        target_document_ref = document_refs[0]
        if target_document_ref.object_id not in design_leg_document_ids:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "the targeted design document is not one of the open design leg's documents",
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
        target_doc_kind = target_document.get("doc_kind")
        if target_doc_kind not in {"scene", "web", "site"}:
            raise ContextReferenceError(
                "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                "design node targets require a scene or web document",
            )
        if target_document_ref.version != target_document.get("current_version"):
            raise ContextReferenceError(
                "CONTEXT_REF_STALE",
                "the targeted design document no longer names the current version",
            )
        try:
            # A scene target must resolve to ONE page (the scene runtime edits a page at a
            # time); a web target only has to exist somewhere in the document, and may carry
            # an inner ``#`` path naming the annotated element inside its node.
            if target_doc_kind == "scene":
                resolve_scene_targets(
                    target_document.get("scene") or {},
                    tuple(ref.object_id for ref in design_nodes),
                )
            elif target_doc_kind == "site":
                validate_site_targets(
                    target_document.get("scene") or {},
                    tuple(ref.object_id for ref in design_nodes),
                )
            else:
                validate_web_targets(
                    target_document.get("scene") or {},
                    tuple(ref.object_id for ref in design_nodes),
                )
        except DesignTurnTargetError as exc:
            raise ContextReferenceError(exc.code, exc.message) from exc

    if design_assets:
        if not design_leg_document_ids:
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

        # Untargeted reference images ride EVERY addressed run of the leg (spec §3.7), so the
        # scene-kind rule is asked of the whole document set, not of one pinned document.
        if target_document is None:
            leg_documents: list[dict[str, Any]] = []
            for leg_document_id in design_leg_document_ids:
                try:
                    leg_documents.append(
                        await get_design_document(
                            conn,
                            workspace_id=workspace_id,
                            document_id=leg_document_id,
                        )
                    )
                except DesignNotFoundError as exc:
                    raise ContextReferenceError(
                        "CONTEXT_REF_NOT_FOUND",
                        "an open design leg document is not available in this workspace",
                    ) from exc
            kinds = {document.get("doc_kind") for document in leg_documents}
        else:
            kinds = {target_document.get("doc_kind")}
        if kinds != {"scene"}:
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
    project_design_ids: frozenset[str] | None = None
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
            if project_id is not None:
                if project_design_ids is None:
                    project_design_ids = frozenset(
                        str(item["id"])
                        for item in await project_design_documents(
                            conn, workspace_id=workspace_id, project_id=project_id
                        )
                    )
                if ref.object_id not in project_design_ids:
                    raise ContextReferenceError(
                        "CONTEXT_REF_NOT_FOUND",
                        "a design document context reference is not in this project",
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
        if ref.object_type == "project_document":
            # A Gallery file. Always version-pinned to the latest servable row of its path: the
            # picker only offers the latest, and a tag that has since been superseded is refused
            # rather than silently repointed.
            if project_id is None:
                raise ContextReferenceError(
                    "CONTEXT_REF_RELATIONSHIP_MISMATCH",
                    "a project document can be referenced only inside its project",
                )
            try:
                document_id = UUID(ref.object_id)
            except ValueError as exc:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a project document context reference is not available in this project",
                ) from exc
            row = await get_project_document(
                conn, workspace_id=workspace_id, project_id=project_id, document_id=document_id
            )
            if row is None:
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "a project document context reference is not available in this project",
                )
            if ref.version is None or ref.version != row.version:
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "a project document context reference must pin the document's version",
                )
            latest = await latest_project_document_version(
                conn, workspace_id=workspace_id, project_id=project_id, path=row.path
            )
            if latest != row.version:
                raise ContextReferenceError(
                    "CONTEXT_REF_STALE",
                    "a project document context reference no longer names the latest version",
                )
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
    project_id: str | None = None,
    settings: Settings | None = None,
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
        project_id=project_id,
    )
    prepared: list[ComposerContextEntity] = []
    for ref in validated:
        if ref.object_type not in {"account", "contact"}:
            # This endpoint hydrates mention-picker entities only. Design and project-document
            # refs can be present on durable messages, but they are presented from their owning
            # read models.
            continue
        entity_id = EntityId(UUID(ref.object_id))
        if ref.object_type == "account":
            account = await get_account(conn, entity_id)
            if account is None:  # pragma: no cover - validation above owns this invariant
                raise ContextReferenceError(
                    "CONTEXT_REF_NOT_FOUND",
                    "an account context reference is not available in this workspace",
                )
            logo_urls = await _account_logo_urls(
                conn, workspace_id=workspace_id, account_ids=(entity_id,)
            )
            prepared.append(
                ComposerContextEntity(
                    object_type="account",
                    object_id=str(account.id),
                    label=account.canonical_name,
                    secondary_label=account.primary_domain or "Account",
                    image_url=account_logo_path(
                        account.id,
                        logo_urls.get(entity_id),
                        domain=account.primary_domain,
                        settings=settings,
                    ),
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
                account_id=str(contact.account_entity_id),
                account_name=subject.account_name,
            )
        )
    return tuple(prepared)


PRESENTED_REF_TYPES = frozenset({"artifact", "design_asset", "design_document", "project_document"})
"""The ref types whose read-time presentation the transcript joins."""


async def _project_document_rows(
    conn: AsyncConnection, *, workspace_id: str, document_ids: Sequence[UUID]
) -> dict[str, Any]:
    """This workspace's project-scoped file rows by id — the join behind a file's label."""

    rows = (
        await conn.execute(
            text(
                "SELECT document_id, project_id, path, kind, artifact_key, artifact_sha256 "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id "
                "  AND document_id = ANY(CAST(:ids AS uuid[])) AND project_id IS NOT NULL"
            ),
            {"workspace_id": workspace_id, "ids": [str(value) for value in document_ids]},
        )
    ).all()
    return {str(row.document_id): row for row in rows}


async def _design_document_rows(
    conn: AsyncConnection, *, workspace_id: str, document_ids: Sequence[str]
) -> dict[str, Any]:
    """This workspace's design documents by id — the join behind a design document's label."""

    rows = (
        await conn.execute(
            text(
                "SELECT id, title, doc_kind FROM design_document "
                "WHERE workspace_id = :workspace_id AND id = ANY(:ids)"
            ),
            {"workspace_id": workspace_id, "ids": list(document_ids)},
        )
    ).mappings()
    return {str(row["id"]): row for row in rows}


async def context_ref_presentations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[Any],
    storage: StorageBackend | None = None,
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve durable refs to read-time labels: asset filenames, file titles, design titles.

    The append-only submission row remains the source of *which* object was submitted. Mutable
    presentation metadata (a filename, a document's own title) is joined only while reading the
    transcript, so nothing user-facing is denormalized into the durable turn receipt — and no
    path or id is ever the label.
    """

    result: dict[tuple[str, str], dict[str, str]] = {}

    asset_ids = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "design_asset")
    )
    if asset_ids:
        from clue_design.assets import get_asset_records

        records = await get_asset_records(
            conn,
            workspace_id=workspace_id,
            asset_ids=asset_ids,
        )
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

    document_ids: list[UUID] = []
    for ref in refs:
        if ref.object_type != "project_document":
            continue
        try:
            document_ids.append(UUID(str(ref.object_id)))
        except ValueError:
            continue
    if document_ids:
        rows = await _project_document_rows(
            conn, workspace_id=workspace_id, document_ids=tuple(dict.fromkeys(document_ids))
        )
        if storage is not None:
            # Every tagged document is opened for its title; fetch them together so the reads
            # below are served from the content cache (2026-10-15: one after another they were
            # 1.4 s of a chat's load). A row without a file has nothing to fetch.
            await read_knowledge_bytes(
                conn,
                storage,
                workspace_id=workspace_id,
                refs=[
                    (str(row.artifact_key), str(row.artifact_sha256))
                    for row in rows.values()
                    if getattr(row, "artifact_key", None) and getattr(row, "artifact_sha256", None)
                ],
            )
        for document_id, row in rows.items():
            front: Mapping[str, Any] = {}
            body = ""
            if storage is not None:
                # ``servable_only=False``: a transcript read of an older turn whose tagged
                # version has since been superseded still names the document the user tagged.
                read = await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=str(row.project_id),
                    document_id=UUID(document_id),
                    servable_only=False,
                )
                if read is not None:
                    _, front, body = read
            result[("project_document", document_id)] = {
                "label": document_title(front, body, path=str(row.path)),
                "kind": str(row.kind),
            }

    # An attachment ref projects as ``object_type='artifact'`` with the content-addressed storage
    # key as its id. The key says nothing a person can read, so the filename and media type the
    # human's upload carried are joined here — the same read-time-only discipline as above, and
    # workspace-scoped, so a key from another tenant simply resolves to nothing.
    artifact_keys = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "artifact")
    )
    if artifact_keys:
        attachment_rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (artifact_key) artifact_key, upload_id, filename, "
                    "media_type FROM agent_turn_submission_attachment "
                    "WHERE workspace_id = :ws AND artifact_key = ANY(:keys) "
                    "ORDER BY artifact_key, created_at DESC"
                ),
                {"ws": workspace_id, "keys": list(artifact_keys)},
            )
        ).mappings()
        for attachment in attachment_rows:
            result[("artifact", str(attachment["artifact_key"]))] = {
                "label": str(attachment["filename"]),
                "media_type": str(attachment["media_type"]),
                "upload_id": str(attachment["upload_id"]),
            }

    design_ids = tuple(
        dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "design_document")
    )
    if design_ids:
        rows = await _design_document_rows(conn, workspace_id=workspace_id, document_ids=design_ids)
        for design_id, row in rows.items():
            result[("design_document", design_id)] = {
                "label": str(row["title"] or "Design"),
                "kind": wire_kind(str(row["doc_kind"])),
            }
    return result
