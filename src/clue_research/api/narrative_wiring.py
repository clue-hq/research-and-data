"""M12 (value narrative & handoff) api-root wiring — the home M12 fills (phase-3 pre-flight PF-7).

Own module so M10 / M11 / M12 never co-edit ``api/composition.py``. M12.1 fills
:func:`register_narrative_wiring`:

* **register the ``account.value_narrative`` field-def** — by appending
  :func:`clue_research.narrative.load_narrative_pack` to ``RESEARCH_PACK_LOADERS`` (its OWN wiring
  module, never co-editing ``load_research_packs`` — PF-7). The field declares
  ``reuse_scope=TENANT_PRIVATE`` (it is ``FieldClass.ACCOUNT`` whose default is
  ``PUBLIC_FOOTPRINT`` — the leak hazard) and the positioner stamps every claim via
  ``NARRATIVE_REUSE_POLICY`` + ``identity.stamp_reuse``, so a client-tuned narrative never
  amortizes cross-tenant.

Deferred to integration (constructed here once the sibling impls exist, exactly like the M9.4
binding-classifier injection): the :class:`~clue_research.narrative.Positioner` with its injected
seams —

* the ``core.retrieval.ClientKnowledgeRetriever`` (a stub over ``stage0.read_client_kb_claims``
  until the pgvector retriever lands — ``api`` may import ``stage0``; ``narrative`` may not);
* the M9.3 ``FaithfulnessJudge`` (``verification.FaithfulnessJudgeImpl`` over the shared gateway);
* the ``narrative.CommitteeReader`` production impl — reads ``contact_entity`` under the account,
  each member's persona/role/facet claims, and the **M10 ``use_decision``** per facet (so it
  returns use-cleared hooks); it needs ``compliance`` (M10), so it lands when M10 integrates.

The positioner filters hooks with ``is_outreach_promotable(claim, use_decision)`` (never
``Claim.is_promotable`` — accuracy-only) and reads the post-tombstone merge (no ``EXPIRED`` case),
per the pre-flight overrides. The M12.2 handoff assembler + M12.3 publisher are wired here later.
"""

from __future__ import annotations

from clue_core import EntityId
from clue_core.retrieval import ClientKnowledgeChunk, ClientKnowledgeRetriever
from clue_research.api.composition import RESEARCH_PACK_LOADERS
from clue_research.db import ConnFactory, transaction
from clue_research.narrative import (
    HandoffAssembler,
    HandoffCommitteeReader,
    fact_to_text,
    load_narrative_pack,
    rank_by_query_overlap,
)
from clue_research.stage0 import read_client_kb_claims


def register_narrative_wiring() -> None:
    """Register the ``account.value_narrative`` field pack at the api root (idempotent).

    Appends :func:`clue_research.narrative.load_narrative_pack` to ``RESEARCH_PACK_LOADERS`` so a
    deep run registers the field (a no-op if already appended — safe to call more than once). The
    positioner construction (its injected retrieval / judge / committee-reader / use-gate seams)
    is integration work that lands as the sibling milestones (M5 retriever, M10 ``use_decision``)
    integrate.
    """
    if load_narrative_pack not in RESEARCH_PACK_LOADERS:
        RESEARCH_PACK_LOADERS.append(load_narrative_pack)


class ClientKnowledgeRetrieverStub:
    """The pre-flight ``read_client_kb_claims``-backed ``ClientKnowledgeRetriever`` (M12.1 / PF —
    the one genuine pre-flight retrieval gap). ``narrative`` may not import ``stage0`` (a sibling
    worker), so the concrete stub lives at the ``api`` root and is injected into the positioner.

    It reads the **version-scoped** Client Knowledge Base via :func:`stage0.read_client_kb_claims`
    (M5 ships only full-KB reads today — no similarity search), turns each client fact into one
    chunk (``client_knowledge_id`` = the client claim's id, so the narrative cites a real KB entry),
    and applies an in-memory token-overlap relevance filter
    (:func:`clue_research.narrative.rank_by_query_overlap`). The pgvector retriever lands later
    behind this same :class:`~clue_core.retrieval.ClientKnowledgeRetriever` signature — a
    config/impl swap, no positioner change. Manages its own short read txn (no conn in the seam)."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def retrieve(
        self,
        *,
        client_entity_id: EntityId,
        client_id: str,
        query: str,
        kb_version: int | None = None,
        limit: int = 10,
    ) -> tuple[ClientKnowledgeChunk, ...]:
        async with self._conn_factory() as conn:
            kb = await read_client_kb_claims(
                conn, client_entity_id, client_id=client_id, version=kb_version
            )
        chunks = [
            ClientKnowledgeChunk(
                client_knowledge_id=str(claim.id),
                chunk=fact_to_text(field_key, claim.value_json),
            )
            for field_key, claim in kb.items()
        ]
        return rank_by_query_overlap(chunks, query, limit=limit)


def build_client_knowledge_retriever(
    *, conn_factory: ConnFactory = transaction
) -> ClientKnowledgeRetriever:
    """Construct the api-root Client-Knowledge retriever to inject into the M12.1 positioner (the
    ``read_client_kb_claims``-backed pre-flight stub until pgvector lands behind the same seam)."""
    return ClientKnowledgeRetrieverStub(conn_factory=conn_factory)


def build_handoff_assembler(*, committee_reader: HandoffCommitteeReader) -> HandoffAssembler:
    """Construct the M12.2 ``account_handoff`` assembler at the ``api`` composition root.

    The assembler is a pure store read; its one injected dependency is the
    :class:`~clue_research.narrative.HandoffCommitteeReader` (the M12 ↔ M8/M10 seam). The
    **production** reader — which reads ``profiling``'s committee/contact results (via the M8A.5
    ``build_handoff_skeleton``) and ``compliance``'s ``use_decision`` per facet — needs the M8/M10
    packages, so it is constructed at this root **when M8/M10 integrate** (the deferred-injection
    pattern, exactly like the M12.1 positioner's committee reader). Until then a caller injects the
    in-memory fake (``InMemoryHandoffCommitteeReader``) or an M8A.5-skeleton-backed adapter; M12.2's
    own code is unchanged by the swap (the seam is the contract).

    Materialising the assembled handoff (``narrative.write_handoff``) and serving / emitting it
    (M12.3) are wired here later; M12.2 stops at the assembler + the ``account_handoff`` table."""
    return HandoffAssembler(committee_reader=committee_reader)
