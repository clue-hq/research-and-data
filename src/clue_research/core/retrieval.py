"""The Client-Knowledge retrieval seam — the M5↔M12 contract (phase-3 pre-flight).

M12.1's positioning step (Output 4) must retrieve the client capabilities relevant to an account's
pains from the Client Knowledge Base (M5, Doc B §2/§5). M5 ships only full-KB *version* reads
(``read_client_kb`` / ``read_client_kb_claims``) — **no similarity retrieval** — and ``narrative``
(M12) may not import ``stage0`` (M5) under the import-linter independence contract. So the *seam* is
frozen here in ``core`` (like every cross-package contract — ``Resolver``, the gates, …): M12 builds
against this protocol; the impl is a stub over ``read_client_kb_claims`` + an in-memory relevance
filter until the pgvector retriever lands behind the same signature, injected at the ``api`` root.

This is the one pre-flight retrieval gap (the M12←M5 edge); freezing the signature lets M12.1
proceed in parallel.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_research.core.primitives import EntityId


class ClientKnowledgeChunk(BaseModel):
    """One retrieved client-knowledge passage relevant to a query. ``client_knowledge_id`` is
    the durable id into the Client Knowledge Base (``claim_id`` of the client fact, or a chunk id)
    that the value narrative cites in ``NarrativeSupport.client_knowledge_ids``; ``chunk`` is text
    the positioning step reasons over. ``score`` is an optional relevance score (``None`` for the
    in-memory stub; populated once the pgvector retriever lands)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_knowledge_id: str
    chunk: str
    score: float | None = None


@runtime_checkable
class ClientKnowledgeRetriever(Protocol):
    """Retrieve the client-knowledge passages relevant to ``query`` for a client, **version-scoped**
    (the M5↔M12 seam). Returns the relevant chunks (highest ``score`` first); the impl is a stub
    over ``read_client_kb_claims`` until the pgvector retriever lands behind this signature.
    Tenant-scoped on ``client_id`` (a client-knowledge claim is always ``TENANT_PRIVATE``)."""

    async def retrieve(
        self,
        *,
        client_entity_id: EntityId,
        client_id: str,
        query: str,
        kb_version: int | None = None,
        limit: int = 10,
    ) -> tuple[ClientKnowledgeChunk, ...]: ...
