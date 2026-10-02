"""Immutable project targeting and seller evidence for the quality research profile.

Document row revisions are not ICP content versions. Personas must name their source document,
or have recoverable production lineage. Neither a matching integer nor a matching path grants
compatibility. Reads verify the manifest and each original, not a mutable latest document.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_obs import get_logger
from clue_research.claimstore.registry import list_research_fields
from clue_spine import get_project, list_products, list_project_product_sets
from clue_storage import (
    ArtifactIntegrityError,
    StorageBackend,
    artifact_key,
    content_address,
    read_verified_artifact,
    record_artifact,
    retain_artifact,
)

log = get_logger(__name__)


class ContextUnavailable(ValueError):
    """A requested project pin cannot be read under this authority."""


class DocumentPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    document_version: int
    artifact_key: str
    sha256: str
    kind: str
    path: str
    project_id: str | None
    derived_from_document_id: UUID | None = None
    source_icp_document_id: UUID | None = None
    source_icp_sha256: str | None = None


class CatalogFieldPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity: Literal["accounts", "contacts"]
    field_key: str
    version: int
    value_type: str
    validation: dict[str, JsonValue] | None
    value_schema: dict[str, JsonValue] | None = None
    description: str


class ResearchContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    workspace_id: str
    brand_id: str
    project_id: str
    seller_name: str
    product_selection_version: int
    products: dict[str, str]
    icp: DocumentPin
    personas: tuple[DocumentPin, ...] = ()
    persona_state: Literal["pinned", "missing", "lineage_unresolved", "ambiguous"]
    seller_documents: tuple[DocumentPin, ...] = ()
    gaps: tuple[str, ...] = ()
    field_catalog: tuple[CatalogFieldPin, ...] = ()

    def documents(self) -> tuple[DocumentPin, ...]:
        return (self.icp, *self.personas, *self.seller_documents)


_DOC_COLUMNS = (
    "document_id, version AS document_version, artifact_key, artifact_sha256 AS sha256, "
    "kind, path, project_id, derived_from_document_id, source_icp_document_id, source_icp_sha256"
)


async def _document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    document_id: UUID,
) -> DocumentPin:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DOC_COLUMNS} FROM brand_knowledge_document WHERE workspace_id=:ws "
                    "AND brand_id=:brand AND document_id=:doc AND artifact_key IS NOT NULL "
                    "AND (project_id IS NULL OR project_id=:project)"
                ),
                {"ws": workspace_id, "brand": brand_id, "doc": document_id, "project": project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ContextUnavailable("document unavailable in the project's context")
    return DocumentPin.model_validate(dict(row))


async def read_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    pin: DocumentPin,
) -> str:
    record, raw = await read_verified_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        storage_key=pin.artifact_key,
    )
    if record.content_sha256 != pin.sha256:
        raise ContextUnavailable("document differs from its context pin")
    return raw.decode("utf-8")


def _semantic_icp(raw: str) -> str:
    """Only confirmation metadata can differ along an otherwise identical ICP lineage."""
    front, body = parse_front_matter(raw)
    metadata = {
        "version",
        "status",
        "confirmed_at",
        "confirmed_by",
        "confirmed_by_user_id",
        "confirmed_for_project_id",
        "product_selection_version",
        "confirmation_source",
        "confirmed_from_document_id",
        "confirmation_gate_id",
    }
    return json.dumps(
        {"front": {k: v for k, v in front.items() if k not in metadata}, "body": body},
        sort_keys=True,
        default=str,
    )


async def equivalent_icp_sources(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    icp: DocumentPin,
) -> dict[UUID, str]:
    """Follow recorded supersession only while semantics remain identical, never ancestry alone."""
    expected = _semantic_icp(await read_document(conn, storage, workspace_id=workspace_id, pin=icp))
    result = {icp.document_id: icp.sha256}
    current = icp
    while True:
        parent = (
            await conn.execute(
                text(
                    "SELECT supersedes_document_id FROM brand_knowledge_document "
                    "WHERE document_id=:doc AND workspace_id=:ws"
                ),
                {"doc": current.document_id, "ws": workspace_id},
            )
        ).scalar_one_or_none()
        if parent is None or parent in result:
            return result
        prior = await _document(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            project_id=project_id,
            document_id=parent,
        )
        if prior.project_id != icp.project_id:
            return result
        if (
            _semantic_icp(await read_document(conn, storage, workspace_id=workspace_id, pin=prior))
            != expected
        ):
            return result
        result[prior.document_id] = prior.sha256
        current = prior


async def _persona_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    doc: DocumentPin,
    ws: str,
) -> UUID | None:
    if doc.source_icp_document_id is not None:
        return doc.source_icp_document_id
    # Legacy persona-only runs recorded the source document in their durable launch record.
    row = (
        await conn.execute(
            text("""
      SELECT r.persona_icp_document_id FROM brand_knowledge_document d
      JOIN onboarding_step s ON s.step_id=d.produced_by_step_id
      JOIN onboarding_run r ON r.run_id=s.run_id AND r.workspace_id=d.workspace_id
      WHERE d.document_id=:doc AND d.workspace_id=:ws AND r.persona_icp_document_id IS NOT NULL
    """),
            {"doc": doc.document_id, "ws": ws},
        )
    ).scalar_one_or_none()
    if row is not None:
        return UUID(str(row))
    # Governed persona synthesis pins a trusted project card with the exact source ICP ID.
    # Read its immutable artifact rather than interpreting persona prose or integer versions.
    card_key = (
        await conn.execute(
            text("""
      SELECT r.artifact_key FROM brand_knowledge_document d
      JOIN agent_artifact_ref r ON r.turn_id=d.produced_by_turn_id AND r.workspace_id=d.workspace_id
      WHERE d.document_id=:doc AND d.workspace_id=:ws AND r.owner_kind='turn'
        AND r.ref_role='project_card' AND r.ordinal=0
    """),
            {"doc": doc.document_id, "ws": ws},
        )
    ).scalar_one_or_none()
    if card_key is None:
        return None
    try:
        _, raw = await read_verified_artifact(conn, storage, workspace_id=ws, storage_key=card_key)
        card = json.loads(raw)
        if card.get("task") != "persona":
            return None
        return UUID(card["icp"]["document_id"])
    except (ArtifactIntegrityError, KeyError, TypeError, ValueError):
        return None


async def build_context(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
    product_selection_version: int,
    persona_document_ids: Sequence[UUID] | None = None,
) -> ResearchContext:
    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise ContextUnavailable("project unavailable")
    target = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if target is None:
        raise ContextUnavailable("project ICP is not pinned")
    icp = await _document(
        conn,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        project_id=project_id,
        document_id=target.document_id,
    )
    if icp.artifact_key != target.artifact_key or icp.sha256 != target.artifact_sha256:
        raise ContextUnavailable("project ICP artifact mismatch")
    product_set = next(
        (
            p
            for p in await list_project_product_sets(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            if p.selection_version == product_selection_version
        ),
        None,
    )
    if product_set is None:
        raise ContextUnavailable("selected product version unavailable")
    products = {
        p.product_id: p.name
        for p in await list_products(conn, project.brand_id)
        if p.workspace_id == workspace_id and p.product_id in product_set.product_ids
    }
    if set(products) != set(product_set.product_ids):
        raise ContextUnavailable("selected product is outside seller context")
    seller = (
        await conn.execute(
            text("SELECT name FROM brand WHERE workspace_id=:ws AND brand_id=:brand"),
            {"ws": workspace_id, "brand": project.brand_id},
        )
    ).scalar_one()
    sources = await equivalent_icp_sources(
        conn,
        storage,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        project_id=project_id,
        icp=icp,
    )
    rows = (
        (
            await conn.execute(
                text(f"""
      SELECT DISTINCT ON (project_id,path) {_DOC_COLUMNS} FROM brand_knowledge_document
      WHERE workspace_id=:ws AND brand_id=:brand AND (project_id IS NULL OR project_id=:project)
        AND status IN ('ready','proposed','confirmed') AND artifact_key IS NOT NULL
        AND kind IN ('audience-persona','company-overview','product-research','product-catalog')
      ORDER BY project_id,path,version DESC, document_id
    """),
                {"ws": workspace_id, "brand": project.brand_id, "project": project_id},
            )
        )
        .mappings()
        .all()
    )
    documents = [DocumentPin.model_validate(dict(row)) for row in rows]
    explicit = persona_document_ids is not None
    if explicit:
        documents = [d for d in documents if d.kind != "audience-persona"]
        for did in dict.fromkeys(persona_document_ids or ()):
            selected = await _document(
                conn,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                project_id=project_id,
                document_id=did,
            )
            if selected.kind != "audience-persona":
                raise ContextUnavailable("selected persona is not a persona document")
            documents.append(selected)
    personas: list[DocumentPin] = []
    seller_documents: list[DocumentPin] = []
    gaps: list[str] = []
    mismatch = False
    supported_products: set[str] = set()
    for doc in documents:
        try:
            raw = await read_document(conn, storage, workspace_id=workspace_id, pin=doc)
        except (ArtifactIntegrityError, ContextUnavailable, FileNotFoundError, UnicodeError):
            if doc.kind != "audience-persona":
                raise
            mismatch = True
            gaps.append(f"persona_unreadable:{doc.document_id}")
            continue
        front, _ = parse_front_matter(raw)
        if doc.kind == "audience-persona":
            source = await _persona_source(conn, storage, doc, workspace_id)
            if source in sources and (
                doc.source_icp_sha256 is None or doc.source_icp_sha256 == sources[source]
            ):
                personas.append(
                    doc.model_copy(
                        update={
                            "source_icp_document_id": source,
                            "source_icp_sha256": sources[source],
                        }
                    )
                )
            else:
                mismatch = True
        elif doc.kind == "company-overview" or (
            doc.kind == "product-research" and front.get("product_id") in products
        ):
            seller_documents.append(doc)
            if doc.kind == "product-research":
                supported_products.add(str(front["product_id"]))
    if not explicit and any(d.project_id == project_id for d in personas):
        personas = [d for d in personas if d.project_id == project_id]
    state: Literal["pinned", "missing", "lineage_unresolved", "ambiguous"] = "pinned"
    if not explicit and len(personas) > 1:
        personas, state = [], "ambiguous"
    elif explicit and len(personas) != len(set(persona_document_ids or ())):
        personas, state = [], "lineage_unresolved"
    elif not personas:
        state = "lineage_unresolved" if mismatch else "missing"
    if state != "pinned":
        gaps.append(f"persona:{state}")
    gaps.extend(
        f"selected_product_capability_evidence_missing:{pid}"
        for pid in sorted(set(products) - supported_products)
    )
    catalog = []
    for entity in ("accounts", "contacts"):
        for row in await list_research_fields(conn, workspace_id=workspace_id, entity=entity):
            catalog.append(
                CatalogFieldPin.model_validate(
                    {
                        "entity": entity,
                        "field_key": row.field_def.field_key,
                        "version": row.definition_version,
                        "value_type": row.field_def.value_type,
                        "validation": row.field_def.validation,
                        "value_schema": row.value_schema,
                        "description": row.description,
                    }
                )
            )
    return ResearchContext(
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        project_id=project_id,
        seller_name=seller,
        products=products,
        product_selection_version=product_selection_version,
        icp=icp,
        personas=tuple(personas),
        persona_state=state,
        seller_documents=tuple(seller_documents),
        gaps=tuple(gaps),
        field_catalog=tuple(catalog),
    )


def context_catalog(context: ResearchContext, *, person: bool = False) -> FieldCatalog:
    """Convert the frozen menu to the existing deterministic mapper's catalog shape."""
    sections: dict[str, list[FieldSpec]] = {"account": [], "contact": [], "facet": []}
    for row in context.field_catalog:
        if row.entity != ("contacts" if person else "accounts"):
            continue
        key = row.field_key
        section = (
            "facet"
            if key.startswith("contact.facet.")
            else "contact"
            if key.startswith("contact.")
            else "account"
        )
        hint = (row.validation or {}).get("use_class_hint")
        sections[section].append(
            FieldSpec(
                key, row.description, row.value_schema, str(hint) if hint is not None else None
            )
        )
    return FieldCatalog(
        account=tuple(sections["account"]),
        contact=tuple(sections["contact"]),
        facet=tuple(sections["facet"]),
    )


async def persist_context(
    conn: AsyncConnection,
    storage: StorageBackend,
    context: ResearchContext,
) -> UUID:
    raw = json.dumps(
        context.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    sha = content_address(raw)
    key = artifact_key(context.workspace_id, sha)
    cid = uuid5(NAMESPACE_URL, f"arv2-context:{context.workspace_id}:{context.project_id}:{sha}")
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=context.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type="application/json")
    for retained in sorted({key, *(doc.artifact_key for doc in context.documents())}):
        await retain_artifact(
            conn,
            workspace_id=context.workspace_id,
            storage_key=retained,
            reference_kind="research_context",
            reference_id=str(cid),
        )
    await conn.execute(
        text("""
      INSERT INTO arv2_research_context_pin
        (context_id,workspace_id,project_id,brand_id,manifest_key,manifest_sha256,
         icp_document_id,product_selection_version)
      VALUES (:id,:ws,:project,:brand,:key,:sha,:icp,:selection) ON CONFLICT DO NOTHING
    """),
        {
            "id": cid,
            "ws": context.workspace_id,
            "project": context.project_id,
            "brand": context.brand_id,
            "key": key,
            "sha": sha,
            "icp": context.icp.document_id,
            "selection": context.product_selection_version,
        },
    )
    for doc in context.documents():
        await conn.execute(
            text("""
          INSERT INTO arv2_context_document(context_id,workspace_id,document_id,artifact_key,role)
          VALUES (:id,:ws,:doc,:key,:role) ON CONFLICT DO NOTHING
        """),
            {
                "id": cid,
                "ws": context.workspace_id,
                "doc": doc.document_id,
                "key": doc.artifact_key,
                "role": "icp"
                if doc == context.icp
                else "persona"
                if doc in context.personas
                else "seller",
            },
        )
    log.info(
        "arv2.context_pinned",
        context_id=str(cid),
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        persona_state=context.persona_state,
    )
    return cid


async def read_context(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
    context_id: UUID,
) -> ResearchContext:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT manifest_key,manifest_sha256 FROM "
                    "arv2_research_context_pin WHERE context_id=:id "
                    "AND workspace_id=:ws AND project_id=:project"
                ),
                {"id": context_id, "ws": workspace_id, "project": project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ContextUnavailable("research context unavailable")
    record, raw = await read_verified_artifact(
        conn, storage, workspace_id=workspace_id, storage_key=row["manifest_key"]
    )
    if record.content_sha256 != row["manifest_sha256"]:
        raise ContextUnavailable("research context digest mismatch")
    result = ResearchContext.model_validate_json(raw)
    if (result.workspace_id, result.project_id) != (workspace_id, project_id):
        raise ContextUnavailable("research context scope mismatch")
    return result
