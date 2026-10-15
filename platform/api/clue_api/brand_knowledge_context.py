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
* :func:`read_pinned_documents` — the pinned bytes, verified against the pinned digest. A turn
  reads them at ``brand/knowledge/``, where :mod:`clue_api.brand_library` renders them once per
  knowledge version and every thread of the brand mounts them read-only.
  :func:`knowledge_seed_files` copied the same bytes into one thread instead; no production
  surface composes it since 2026-09-14.
* :func:`compile_brand_knowledge_index_card` — a bounded index of those files for the opening
  context. The card is an *index*, not the knowledge: it carries a path, a status and one summary
  line per document so the model knows what to read, never the documents' contents.

The project's **ICP pin** (``arv2.icp_confirmation.current_project_icp_pin``) rides through both:
the turn's pinned set always contains the document version this project agreed to, even after a
newer version is published on its path, and the card's ``confirmed_icp`` is that pinned document —
never a scan for whatever currently carries ``confirmed_for_project_id`` (founder rulings
2026-09-10).

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
from pydantic import BaseModel, ConfigDict, JsonValue, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import WorkspaceSeedFile
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.project_context_files import project_workspace_path
from clue_core import UtcDatetime
from clue_spine import ProjectProductSet
from clue_storage import StorageBackend, read_verified_artifact

__all__ = [
    "BRAND_KNOWLEDGE_INDEX_CARD_MEDIA_TYPE",
    "BRAND_LIBRARY_PREFIX",
    "INPUT_PREFIX",
    "KNOWLEDGE_DOCUMENT_MEDIA_TYPE",
    "SEED_PREFIX",
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
    "current_project_knowledge_refs",
    "document_ref",
    "get_knowledge_pin",
    "knowledge_seed_files",
    "load_or_create_knowledge_pin",
    "read_pinned_documents",
    "version_qualified_path",
    "workspace_paths",
]

#: Where a turn reads the brand's knowledge documents. Since 2026-09-14 that is the **mounted**
#: brand library — the same documents rendered once per knowledge version beside the threads
#: (``<ws>/library/brand/<brand>/<version>/knowledge/``) and mounted read-only at ``brand/`` — so
#: the two constants below are one path, kept as two names because they are two *surfaces*: the
#: per-turn seed surface (:func:`knowledge_seed_files`, which no production turn composes any
#: more) and the library mount. One constant per surface, so a path is never spelled by hand at a
#: call site.
INPUT_PREFIX = "brand/knowledge/"
BRAND_LIBRARY_PREFIX = "brand/knowledge/"
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
    "document_id, path, kind, version, status, artifact_key, artifact_sha256, updated_at, "
    "project_id"
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
    #: ``None`` for a brand-level document; set for a document scoped to one project (a
    #: project-local ICP variant, its personas, the project plan). It defaults because the pinned
    #: sets already at rest in ``agent_turn_knowledge_pin.documents`` were written without it, and
    #: every one of those rows is brand-level.
    project_id: str | None = None


def _ref_from_row(row: RowMapping) -> KnowledgeDocumentRef:
    """One ``brand_knowledge_document`` row as a ref — the single decode every reader shares."""

    project_id = row["project_id"]
    return KnowledgeDocumentRef(
        document_id=row["document_id"],
        path=str(row["path"]),
        kind=str(row["kind"]),
        version=int(row["version"]),
        status=str(row["status"]),
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        updated_at=row["updated_at"],
        project_id=None if project_id is None else str(project_id),
    )


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
        "project_id": ref.project_id,
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
    """The brand's current servable knowledge documents — the max version of each path.

    **Brand-level rows only.** A project-scoped document belongs to one project, and this reader
    answers "what does this *brand* know" — a question no project's private variant may change.
    Its own reader is :func:`current_project_knowledge_refs`.
    """

    rows = (
        await conn.execute(
            text(
                f"SELECT DISTINCT ON (path) {_DOCUMENT_COLUMNS} "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "  AND project_id IS NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "statuses": list(SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(_ref_from_row(row) for row in rows.all())


async def current_project_knowledge_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[KnowledgeDocumentRef, ...]:
    """One project's own servable knowledge documents — the max version of each path.

    The mirror of :func:`current_knowledge_documents` on the other side of the scope: the ICP
    variants, personas and plan a project authored for itself. Read inside one workspace, so
    another tenant's project rows are indistinguishable from absence.
    """

    rows = (
        await conn.execute(
            text(
                f"SELECT DISTINCT ON (path) {_DOCUMENT_COLUMNS} "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "statuses": list(SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(_ref_from_row(row) for row in rows.all())


async def document_ref(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: UUID,
) -> KnowledgeDocumentRef | None:
    """One named document version, whatever its status — read inside one workspace.

    Status is deliberately not filtered: this reads the version a *project pinned*, and a pin is
    not undone by a later publish on the same path. A row with no bytes is honestly absent, because
    there is nothing to seed or verify.

    Public because the project's own compiler (``project_status.current_project_documents``) needs
    exactly this read for exactly this reason: a pinned project-scoped document that a newer
    version has superseded is no longer "current", yet it is still the document the project agreed
    to and still has to reach the workspace.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM brand_knowledge_document "
                    "WHERE document_id = :document_id AND workspace_id = :workspace_id "
                    "  AND artifact_key IS NOT NULL"
                ),
                {"document_id": document_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _ref_from_row(row)


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
    project_id: str,
) -> tuple[KnowledgePinRow, bool]:
    """Return this turn's pinned documents, atomically creating them on the first attempt.

    Concurrent attempts may both observe the live documents, but only the winning ``INSERT`` owns
    the turn. The loser reads the winner's row; it never composes from its discarded observation.
    Database ``now()`` supplies the receipt time.

    **The project's pinned ICP is always in the set** (founder rulings 2026-09-10), even when a
    newer version has since been published on its path: the brand's *current* documents answer
    "what does this brand know now", and the pin answers "what did this project agree to". A turn
    needs both, so they are unioned (by document id, so the common case where the pin still is the
    current version adds nothing). Replaying an existing pin is unchanged — the row is immutable.
    """

    existing = await get_knowledge_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if existing is not None:
        return existing, False

    documents = await current_knowledge_documents(
        conn, workspace_id=workspace_id, brand_id=brand_id
    )
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if pin is not None and all(ref.document_id != pin.document_id for ref in documents):
        pinned_ref = await document_ref(
            conn, workspace_id=workspace_id, document_id=pin.document_id
        )
        if pinned_ref is not None:
            documents = tuple(
                sorted((*documents, pinned_ref), key=lambda ref: (ref.path, ref.version))
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


def version_qualified_path(path: str, version: int) -> str:
    """``audience/icp-gi.md`` at v3 → ``audience/icp-gi.v3.md``.

    The one spelling of the name a *non-pinned* version of a pinned path takes, shared with the
    project compiler (``project_status.current_project_documents``) so a project's two versions
    are named here exactly as the brand's two are.
    """

    stem, dot, suffix = path.rpartition(".")
    return f"{stem}.v{version}.{suffix}" if dot else f"{path}.v{version}"


def workspace_paths(
    documents: Sequence[PinnedDocument],
    *,
    pinned_document_id: UUID | None = None,
    prefix: str = INPUT_PREFIX,
) -> dict[UUID, str]:
    """Where each pinned document materializes under ``prefix`` (default ``brand/knowledge/``).

    ``prefix`` is the one thing that could differ between the two surfaces that serve these
    documents — the thread's own seeds and the mounted brand library — and since 2026-09-14 the
    two agree on one path. The naming rules below are identical for both, which is the point: a
    document is at the same relative path whichever surface a turn reads it from.

    Normally one document holds a path and the answer is just that path. A project's ICP pin can
    put **two** versions of one path in a turn's set at once — the version the project agreed to,
    and a newer proposal the brand has since published — and a workspace refuses to materialize two
    files at one path (``AgentResourceMaterializer``). So the pinned version keeps the natural
    name, because it is what this project's ICP *is*, and the other version is offered beside it
    under a version-qualified name. Both are real, readable files; neither is silently dropped and
    neither overwrites the other.

    A project-scoped document materializes under the project's prefix instead, by the one rule in
    ``project_context_files.project_workspace_path``. Scope is therefore part of the grouping key:
    a brand document and a project's variant of the same path occupy two different workspace paths
    and do not collide, so neither has to be version-qualified out of the other's way.
    """

    grouped: dict[tuple[str | None, str], list[PinnedDocument]] = {}
    for document in documents:
        grouped.setdefault((document.ref.project_id, document.ref.path), []).append(document)
    resolved: dict[UUID, str] = {}
    for (project_id, path), group in grouped.items():
        keeper = next(
            (item for item in group if item.ref.document_id == pinned_document_id),
            # No pin on this path: the newest version answers to the plain name.
            max(group, key=lambda item: item.ref.version),
        )
        for document in group:
            name = (
                path
                if document.ref.document_id == keeper.ref.document_id
                else version_qualified_path(path, document.ref.version)
            )
            resolved[document.ref.document_id] = (
                prefix + name if project_id is None else project_workspace_path(name)
            )
    return resolved


#: Where the *seed* surface puts these documents. Deliberately NOT :data:`INPUT_PREFIX`, which now
#: names the mount: a ``WorkspaceSeedFile`` may only materialize below ``context/`` or ``inputs/``
#: (``clue_agents.resources``), so a seed built at the mount's prefix is refused at construction.
SEED_PREFIX = "inputs/brand/knowledge/"


def knowledge_seed_files(
    documents: Sequence[PinnedDocument],
    *,
    pinned_document_id: UUID | None = None,
    prefix: str = SEED_PREFIX,
) -> tuple[WorkspaceSeedFile, ...]:
    """The read-only workspace files the model reads by path, one per pinned **brand** document.

    A project-scoped document is skipped here and seeded by the project files pin instead, which
    owns everything under the project's prefix. Two seeds for one path would be a materialization
    conflict; one owner per prefix is the rule that prevents it.

    **No production surface composes this since 2026-09-14**: a turn reads these files at the
    mounted brand library instead, so these bytes are never copied into a thread. It is kept
    because it is the one place that spells the seed surface's naming rule, and because the rule
    it encodes is the library's too (:func:`workspace_paths` is shared).
    """

    paths = workspace_paths(documents, pinned_document_id=pinned_document_id, prefix=prefix)
    return tuple(
        WorkspaceSeedFile(
            path=paths[document.ref.document_id],
            content=document.body,
            sha256=document.ref.artifact_sha256,
            media_type=KNOWLEDGE_DOCUMENT_MEDIA_TYPE,
        )
        for document in documents
        if document.ref.project_id is None
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
    pinned_document_id: UUID | None,
) -> ConfirmedIcpRef | None:
    """The document this project **pinned** as its ICP, or ``None`` when it has not pinned one.

    A brand's ICPs are shared; a *confirmation* is per project — and the selector for which one is
    the project's is its durable pin (``project_icp_pin``), not a scan of whatever the brand holds
    now (founder rulings 2026-09-10). The confirmed version's front matter still records
    ``confirmed_for_project_id``, but as data about that document, never as the choice: a scan
    would move the moment another project confirmed the same path, or a re-synthesis published a
    newer version.

    A newer proposal on the pinned path stays in ``documents`` and stays listed in the card — the
    agent may read it. The card simply does not call it confirmed.
    """

    if pinned_document_id is None:
        return None
    chosen = next(
        (document for document in documents if document.ref.document_id == pinned_document_id),
        None,
    )
    # A pin whose bytes are not in this turn's set cannot be cited, so it is honestly absent
    # rather than half-known.
    if chosen is None:
        return None
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
    #: Set only when this card is a **library** manifest: the digest of the knowledge pin the
    #: library tree renders (``LibraryTree`` requires its ``index.json`` to record it). A turn's
    #: opening context card is not a manifest of anything, so it leaves the field unset — and an
    #: unset field is serialized away entirely, below, so that card's bytes and content hash are
    #: exactly what they were before this field existed.
    library_sha256: str | None = None
    #: Product changes of the last 30 days, one plain line each ("15 Oct 2026: 8 products merged
    #: into Proxon"; spec 2026-10-15 §8), so a product name in the chat history that no longer
    #: exists is recognised as stale. Omitted from every dump when unset, like ``library_sha256``,
    #: so a card with no change keeps the bytes it had before this field existed.
    recent_product_changes: list[str] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop ``library_sha256`` when it is unset — in *every* dump, not just the canonical one.

        The two serializations of this card must agree: the fleet wiring persists
        ``model_dump(exclude_none=False)`` and then asserts the stored digest equals
        :meth:`content_sha256`. A field that one path emitted as ``null`` and the other omitted
        would fail that check, so the omission lives in the serializer both paths share.
        """

        payload = dict(handler(self))
        if self.library_sha256 is None:
            payload.pop("library_sha256", None)
        if self.recent_product_changes is None:
            payload.pop("recent_product_changes", None)
        return payload

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


def _index_entry(document: PinnedDocument, *, workspace_path: str) -> IndexEntry:
    front = document.front_matter
    product_ids = _front_product_ids(front)
    product_id = front.get("product_id")
    _, icp_key = document_identity(front)
    return IndexEntry(
        path=document.ref.path,
        workspace_path=workspace_path,
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
    max_bytes: int | None = 8192,
    prefix: str = INPUT_PREFIX,
    library_sha256: str | None = None,
    recent_product_changes: Sequence[str] = (),
) -> BrandKnowledgeIndexCard:
    """Compile the opening index over one turn's pinned documents, bounded by ``max_bytes``.

    Over budget, per-product research entries are dropped from the end and counted in
    ``omitted_count``: the files stay seeded on disk and remain readable by path, they simply stop
    riding the opening context. Nothing else is droppable — the company, catalog, proof, ICP and
    persona lines are what the Stage-0 procedure is written against — so a budget below that floor
    yields a card that is as small as it can honestly be rather than a card missing its spine.

    ``max_bytes=None`` means **no budget**, and is what a card compiled as a durable manifest
    rather than as opening context asks for: an index that sits on disk and is opened by path costs
    a turn nothing until it is read, so dropping a line from it would buy nothing and would leave
    the manifest under-listing the very files it describes.

    **The entries are the brand's documents only.** A project-scoped document rides the pinned set
    (that is how its bytes reach the turn, and how ``confirmed_icp`` names it) but it is listed by
    the *project's* index card, off the project's own rows. Listing it in both cards spends the
    brand card's budget on a line the project card already carries, and — when the pinned version
    and the project's current version of one path differ — puts two disagreeing descriptions of one
    file in one turn's opening context. ``confirmed_icp`` is unchanged: naming the pinned document
    is this card's job whatever that document's scope.

    ``prefix`` and ``library_sha256`` are what the **brand library** compiles this same card with:
    the paths it names are then the library's mounted paths, and the digest records which pinned
    knowledge version the tree renders. Neither is set for a turn's opening card.
    """

    ordered = sorted(
        (document for document in documents if document.ref.project_id is None),
        key=lambda document: (_card_rank(document.ref.path), document.ref.version),
    )
    # The same paths the seeds materialize under, so every line of the index names a file that is
    # really there — including both versions of a pinned path.
    paths = workspace_paths(
        documents,
        pinned_document_id=None if confirmed_icp is None else confirmed_icp.document_id,
        prefix=prefix,
    )
    entries = [
        _index_entry(document, workspace_path=paths[document.ref.document_id])
        for document in ordered
    ]
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
            library_sha256=library_sha256,
            recent_product_changes=list(recent_product_changes) or None,
        )

    omitted_count = 0
    card = build(omitted_count)
    while max_bytes is not None and len(card.canonical_bytes()) > max_bytes:
        droppable = [index for index, kind in enumerate(kinds) if kind == _PRODUCT_RESEARCH_KIND]
        if not droppable:
            break
        last = droppable[-1]
        entries.pop(last)
        kinds.pop(last)
        omitted_count += 1
        card = build(omitted_count)
    return card
