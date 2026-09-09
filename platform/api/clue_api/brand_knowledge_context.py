"""The brand knowledge a production conversation turn opens with (ARV2 onboarding O6).

Onboarding writes a brand's knowledge as markdown documents (`brand_knowledge_document`): the
company overview, the product catalog and per-product research, customer proof, the proposed ICPs
and their personas. The Head of ABM does not research a brand from zero — it reads those files.

This module is the seam between the durable documents and one turn's context:

* :func:`current_knowledge_documents` — the brand's current servable set, one row per path.
* :func:`load_or_create_knowledge_pin` — that set frozen for one turn. Onboarding keeps publishing
  versions in the background, so a turn that re-resolved "current" on every attempt could seed one
  set, crash, and seed a different set on the retry: the file the model was told to re-read would
  have moved underneath it. The pin is insert-once, written before composition; every later attempt
  reads the winner's row.
* :func:`read_pinned_documents` / :func:`knowledge_seed_files` — the pinned bytes, verified against
  the pinned digest, materialized read-only under ``inputs/brand/knowledge/``.
* :func:`compile_brand_knowledge_index_card` — a bounded index of those files for the opening
  context. The card is an *index*, not the knowledge: it carries a path, a status and one summary
  line per document so the model knows what to read, never the documents' contents.

The module holds no Client-KB version, readiness decision or Stage-0 pin: the brand's knowledge is
files, and files are pinned by ref and digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import WorkspaceSeedFile
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_core import UtcDatetime
from clue_spine import ProjectProductSet
from clue_storage import StorageBackend, read_verified_artifact

__all__ = [
    "BRAND_KNOWLEDGE_INDEX_CARD_MEDIA_TYPE",
    "INPUT_PREFIX",
    "KNOWLEDGE_DOCUMENT_MEDIA_TYPE",
    "SERVABLE_STATUSES",
    "BrandKnowledgeIndexCard",
    "ConfirmedIcpRef",
    "IndexEntry",
    "KnowledgeDocumentRef",
    "KnowledgePinConflict",
    "KnowledgePinRow",
    "PinnedDocument",
    "compile_brand_knowledge_index_card",
    "confirmed_icp_for_project",
    "current_knowledge_documents",
    "get_knowledge_pin",
    "knowledge_seed_files",
    "load_or_create_knowledge_pin",
    "read_pinned_documents",
]

#: Every brand knowledge document is materialized read-only below this workspace prefix.
INPUT_PREFIX = "inputs/brand/knowledge/"
#: A document is servable input when its bytes exist and it has not been superseded.
SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")
#: Knowledge documents are markdown with YAML front matter, on disk and in the artifact store.
KNOWLEDGE_DOCUMENT_MEDIA_TYPE = "text/markdown"
BRAND_KNOWLEDGE_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.brand-knowledge-index-card+json"

_ICP_KIND = "icp-definition"
_PRODUCT_RESEARCH_KIND = "product-research"
#: One index line per document: long enough to tell two ICPs apart, short enough to stay an index.
_SUMMARY_MAX_CHARS = 160
_DOCUMENT_COLUMNS = (
    "document_id, path, kind, version, status, artifact_key, artifact_sha256, updated_at"
)
_PIN_COLUMNS = "turn_id, workspace_id, brand_id, documents, documents_sha256, pinned_at"


class KnowledgePinConflict(ValueError):
    """This turn's pinned knowledge cannot be read as the turn pinned it."""


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentRef:
    """One knowledge document, identified precisely enough to re-read exactly these bytes."""

    document_id: UUID
    path: str
    kind: str
    version: int
    status: str
    artifact_key: str
    artifact_sha256: str
    updated_at: datetime


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _ref_payload(ref: KnowledgeDocumentRef) -> dict[str, Any]:
    return {
        "document_id": str(ref.document_id),
        "path": ref.path,
        "kind": ref.kind,
        "version": ref.version,
        "status": ref.status,
        "artifact_key": ref.artifact_key,
        "artifact_sha256": ref.artifact_sha256,
        "updated_at": ref.updated_at.isoformat(),
    }


def _documents_digest(refs: Sequence[KnowledgeDocumentRef]) -> str:
    """A bare 64-hex digest over the pinned set, in path order.

    Two attempts of one turn compare this value to prove they composed the same knowledge, so it is
    order-independent by construction rather than by the caller's care.
    """

    payload = [_ref_payload(ref) for ref in sorted(refs, key=lambda ref: (ref.path, ref.version))]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


async def current_knowledge_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
) -> tuple[KnowledgeDocumentRef, ...]:
    """The brand's current servable knowledge documents — the max version of each path."""

    rows = (
        await conn.execute(
            text(
                f"SELECT DISTINCT ON (path) {_DOCUMENT_COLUMNS} "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "statuses": list(SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(
        KnowledgeDocumentRef(
            document_id=row["document_id"],
            path=str(row["path"]),
            kind=str(row["kind"]),
            version=int(row["version"]),
            status=str(row["status"]),
            artifact_key=str(row["artifact_key"]),
            artifact_sha256=str(row["artifact_sha256"]),
            updated_at=row["updated_at"],
        )
        for row in rows.all()
    )


class KnowledgePinRow(BaseModel):
    """One turn's immutable brand-knowledge receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    workspace_id: str
    brand_id: str
    documents: tuple[KnowledgeDocumentRef, ...]
    documents_sha256: str
    pinned_at: UtcDatetime


def _pin_row(row: dict[str, Any]) -> KnowledgePinRow:
    """Decode the one ``jsonb`` column, which asyncpg may hand back as text or bytes."""

    documents = row.get("documents")
    if isinstance(documents, bytes | bytearray | str):
        row["documents"] = json.loads(documents)
    return KnowledgePinRow.model_validate(row)


async def get_knowledge_pin(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> KnowledgePinRow | None:
    """Read a pin inside one workspace; a foreign pin is indistinguishable from absence."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_PIN_COLUMNS} FROM agent_turn_knowledge_pin "
                    "WHERE turn_id = :turn_id AND workspace_id = :workspace_id"
                ),
                {"turn_id": turn_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _pin_row(dict(row))


async def load_or_create_knowledge_pin(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    brand_id: str,
) -> tuple[KnowledgePinRow, bool]:
    """Return this turn's pinned documents, atomically creating them on the first attempt.

    Concurrent attempts may both observe the live documents, but only the winning ``INSERT`` owns
    the turn. The loser reads the winner's row; it never composes from its discarded observation.
    Database ``now()`` supplies the receipt time.
    """

    existing = await get_knowledge_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if existing is not None:
        return existing, False

    documents = await current_knowledge_documents(
        conn, workspace_id=workspace_id, brand_id=brand_id
    )
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_knowledge_pin "
                    "(turn_id, workspace_id, brand_id, documents, documents_sha256) "
                    "VALUES (:turn_id, :workspace_id, :brand_id, CAST(:documents AS jsonb), "
                    " :digest) "
                    "ON CONFLICT (turn_id) DO NOTHING "
                    f"RETURNING {_PIN_COLUMNS}"
                ),
                {
                    "turn_id": turn_id,
                    "workspace_id": workspace_id,
                    "brand_id": brand_id,
                    "documents": _canonical_json([_ref_payload(ref) for ref in documents]).decode(),
                    "digest": _documents_digest(documents),
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return _pin_row(dict(inserted)), True

    winner = await get_knowledge_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if winner is None:
        raise KnowledgePinConflict(
            "this turn's knowledge pin exists outside the requested workspace"
        )
    return winner, False


@dataclass(frozen=True, slots=True)
class PinnedDocument:
    """One pinned document's verified bytes, split into its front matter and its markdown."""

    ref: KnowledgeDocumentRef
    body: bytes
    front_matter: dict[str, Any]
    body_text: str


def _split_document(body: bytes) -> tuple[dict[str, Any], str]:
    """Front matter and markdown; an unreadable document is honestly empty, never a guess."""

    try:
        decoded = body.decode()
    except UnicodeDecodeError:
        return {}, ""
    try:
        front, rest = parse_front_matter(decoded)
    except (ValueError, yaml.YAMLError):
        return {}, decoded
    return front, rest


async def read_pinned_documents(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    pin: KnowledgePinRow,
) -> tuple[PinnedDocument, ...]:
    """Read every pinned document's bytes, refusing any whose digest has moved since the pin."""

    documents: list[PinnedDocument] = []
    for ref in pin.documents:
        record, body = await read_verified_artifact(
            conn,
            storage,
            storage_key=ref.artifact_key,
            workspace_id=pin.workspace_id,
        )
        if record.content_sha256 != ref.artifact_sha256:
            raise KnowledgePinConflict(
                f"the pinned document {ref.path!r} no longer matches its pinned digest"
            )
        front, body_text = _split_document(body)
        documents.append(
            PinnedDocument(ref=ref, body=body, front_matter=front, body_text=body_text)
        )
    return tuple(documents)


def knowledge_seed_files(documents: Sequence[PinnedDocument]) -> tuple[WorkspaceSeedFile, ...]:
    """The read-only workspace files the model reads by path, one per pinned document."""

    return tuple(
        WorkspaceSeedFile(
            path=INPUT_PREFIX + document.ref.path,
            content=document.body,
            sha256=document.ref.artifact_sha256,
            media_type=KNOWLEDGE_DOCUMENT_MEDIA_TYPE,
        )
        for document in documents
    )


@dataclass(frozen=True, slots=True)
class ConfirmedIcpRef:
    """The ICP document a human confirmed for one project."""

    document_id: UUID
    icp_key: str
    version: int
    artifact_key: str
    artifact_sha256: str
    product_ids: tuple[str, ...]
    product_selection_version: int | None


def _icp_key(document: PinnedDocument) -> str:
    """The ICP key from front matter, or the document's path as the fallback."""

    _, key = document_identity(document.front_matter)
    if key is not None:
        return key
    return document.ref.path.removeprefix("audience/icp-").removesuffix(".md")


def _front_product_ids(front: dict[str, Any]) -> tuple[str, ...]:
    raw = front.get("product_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)


def _front_selection_version(front: dict[str, Any]) -> int | None:
    raw = front.get("product_selection_version")
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def confirmed_icp_for_project(
    documents: Sequence[PinnedDocument],
    *,
    project_id: str,
) -> ConfirmedIcpRef | None:
    """The confirmed ICP document belonging to this project, or ``None``.

    A brand's ICPs are shared; a *confirmation* is per project, recorded in the confirmed version's
    own front matter. Another project's confirmation is therefore not this project's ICP, and a
    proposal is not a confirmation.
    """

    candidates = [
        document
        for document in documents
        if document.ref.kind == _ICP_KIND
        and document.ref.status == "confirmed"
        and document.front_matter.get("confirmed_for_project_id") == project_id
    ]
    if not candidates:
        return None
    chosen = max(candidates, key=lambda document: document.ref.version)
    return ConfirmedIcpRef(
        document_id=chosen.ref.document_id,
        icp_key=_icp_key(chosen),
        version=chosen.ref.version,
        artifact_key=chosen.ref.artifact_key,
        artifact_sha256=chosen.ref.artifact_sha256,
        product_ids=_front_product_ids(chosen.front_matter),
        product_selection_version=_front_selection_version(chosen.front_matter),
    )


class IndexEntry(BaseModel):
    """One line of the index: what the file is, where it is, and why it might be worth opening."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    workspace_path: str
    kind: str
    version: int
    status: str
    as_of: str
    summary: str
    document_id: str
    artifact_key: str
    artifact_sha256: str
    icp_key: str | None = None
    product_ids: list[str] | None = None
    product_id: str | None = None


class BrandKnowledgeIndexCard(BaseModel):
    """The bounded index of a turn's pinned knowledge — an index, never the knowledge itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["brand_knowledge_index"] = "brand_knowledge_index"
    brand_id: str
    documents: list[IndexEntry]
    confirmed_icp: ConfirmedIcpRef | None
    product_set: dict[str, JsonValue] | None
    omitted_count: int

    def canonical_bytes(self) -> bytes:
        # ``exclude_none=False``: a null ``confirmed_icp`` is the typed "no ICP confirmed for this
        # project yet" state the model must be able to see, not an absent field.
        return _canonical_json(self.model_dump(mode="json", exclude_none=False))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def _card_rank(path: str) -> tuple[int, str]:
    """The order the model should meet the files in: who the company is, what it sells, who buys."""

    if path.startswith("company/"):
        return (0, path)
    if path == "product/catalog.md":
        return (1, path)
    if path.startswith("proof/"):
        return (2, path)
    if path.startswith("audience/icp-"):
        return (3, path)
    if path.startswith("audience/persona-"):
        return (4, path)
    if path.startswith("product/"):
        return (5, path)
    return (6, path)


def _summary(body_text: str) -> str:
    """The document's first prose paragraph, bounded.

    A leading markdown heading is the document's title, not a summary of it, so heading-only blocks
    are skipped — otherwise every entry in the index would read ``# Company overview``.
    """

    for block in body_text.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or all(line.lstrip().startswith("#") for line in lines):
            continue
        return " ".join(" ".join(lines).split())[:_SUMMARY_MAX_CHARS]
    return ""


def _index_entry(document: PinnedDocument) -> IndexEntry:
    front = document.front_matter
    product_ids = _front_product_ids(front)
    product_id = front.get("product_id")
    _, icp_key = document_identity(front)
    return IndexEntry(
        path=document.ref.path,
        workspace_path=INPUT_PREFIX + document.ref.path,
        kind=document.ref.kind,
        version=document.ref.version,
        status=document.ref.status,
        as_of=document.ref.updated_at.isoformat(),
        summary=_summary(document.body_text),
        document_id=str(document.ref.document_id),
        artifact_key=document.ref.artifact_key,
        artifact_sha256=document.ref.artifact_sha256,
        icp_key=icp_key,
        product_ids=list(product_ids) or None,
        product_id=product_id if isinstance(product_id, str) and product_id else None,
    )


def compile_brand_knowledge_index_card(
    *,
    brand_id: str,
    documents: Sequence[PinnedDocument],
    confirmed_icp: ConfirmedIcpRef | None,
    product_set: ProjectProductSet | None,
    max_bytes: int = 8192,
) -> BrandKnowledgeIndexCard:
    """Compile the opening index over one turn's pinned documents, bounded by ``max_bytes``.

    Over budget, per-product research entries are dropped from the end and counted in
    ``omitted_count``: the files stay seeded on disk and remain readable by path, they simply stop
    riding the opening context. Nothing else is droppable — the company, catalog, proof, ICP and
    persona lines are what the Stage-0 procedure is written against — so a budget below that floor
    yields a card that is as small as it can honestly be rather than a card missing its spine.
    """

    ordered = sorted(documents, key=lambda document: _card_rank(document.ref.path))
    entries = [_index_entry(document) for document in ordered]
    kinds = [document.ref.kind for document in ordered]

    def build(omitted: int) -> BrandKnowledgeIndexCard:
        return BrandKnowledgeIndexCard(
            brand_id=brand_id,
            documents=list(entries),
            confirmed_icp=confirmed_icp,
            product_set=(
                None
                if product_set is None
                else {
                    "selection_version": product_set.selection_version,
                    "product_ids": list(product_set.product_ids),
                }
            ),
            omitted_count=omitted,
        )

    omitted_count = 0
    card = build(omitted_count)
    while len(card.canonical_bytes()) > max_bytes:
        droppable = [index for index, kind in enumerate(kinds) if kind == _PRODUCT_RESEARCH_KIND]
        if not droppable:
            break
        last = droppable[-1]
        entries.pop(last)
        kinds.pop(last)
        omitted_count += 1
        card = build(omitted_count)
    return card
