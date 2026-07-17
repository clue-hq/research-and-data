"""The injected read-seams the positioner consumes — committee + client-knowledge (M12.1).

The positioning step is a *worker* (import-linter independence contract), so it may not import the
sibling packages that own its inputs: the buying committee + use-gated facets live behind
``profiling`` (M8) and ``compliance`` (M10); the Client Knowledge Base retrieval is a ``stage0``
(M5) concern. So both reach the positioner the way every cross-package dependency does here — as
an **injected seam** (exactly like the M9 gates and the M9.4 binding-classifier injection): the
positioner binds to a narrow protocol; the production implementation is constructed at the ``api``
composition root (it may import all of them) and injected.

* :class:`ClientKnowledgeRetriever` is the *frozen* ``core.retrieval`` seam (the production impl
  is a stub over ``stage0.read_client_kb_claims`` until the pgvector retriever lands — wired at
  ``api``).
* :class:`CommitteeReader` is M12-owned (it returns the *use-cleared* committee, so it depends on
  M10, which cannot live in ``core``). The production impl reads ``contact_entity`` under the
  account, each contact's persona/role/facet claims, and the M10 ``use_decision`` per facet — at
  the ``api`` root.

This module also ships in-memory fakes so M12.1 builds and tests against fixtures with zero
sibling imports (the kickoff plan: "M12 builds against fixtures; at integration the same
field-keys are populated by the real readers — zero M12 code change").
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_core import (
    Claim,
    ClientKnowledgeChunk,
    EntityId,
    Persona,
    UseDecision,
)


def rank_by_query_overlap(
    chunks: Sequence[ClientKnowledgeChunk], query: str, *, limit: int
) -> tuple[ClientKnowledgeChunk, ...]:
    """Rank client-knowledge chunks by case-insensitive token overlap with ``query`` (highest
    first; ties keep insertion order), truncated to ``limit``.

    The in-memory relevance heuristic the pre-flight ``ClientKnowledgeRetriever`` stub uses until
    the pgvector retriever lands — shared by the in-memory test fake
    (:class:`InMemoryClientKnowledgeRetriever`) and the api-root ``read_client_kb_claims``-backed
    stub so the two can't drift."""
    query_tokens = {t for t in query.lower().split() if t}

    def overlap(chunk: ClientKnowledgeChunk) -> int:
        return len(query_tokens & {t for t in chunk.chunk.lower().split() if t})

    ranked = sorted(chunks, key=overlap, reverse=True)  # stable: ties keep insertion order
    return tuple(ranked[: max(0, limit)])


class FacetHook(BaseModel):
    """A personal hook (``contact.facet.*`` claim) for a committee member, paired with the M10
    appropriateness/use verdict on it.

    The positioner keeps a hook only if it clears BOTH gates — ``is_outreach_promotable(claim,
    decision)`` (strong identity-binding AND ``usable_for_outreach``); a weak-binding or
    use-disallowed hook (``decision is None`` or not usable) is dropped before it can flavor any
    argument (M12.1 AC5). The use verdict is supplied (not read off the claim) because it lives in
    M10's ``use_decision`` side table (PF-2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    decision: UseDecision | None = None


class CommitteeContact(BaseModel):
    """A buying-committee member as the positioner consumes it: identity + persona + the candidate
    personal hooks (pre-gating).

    Maps onto the committee that M8.3 produces and M8.4 enriches; the positioner reads it via the
    injected :class:`CommitteeReader`, never by importing ``profiling``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    persona: Persona
    role_on_committee: str
    facets: tuple[FacetHook, ...] = ()


@runtime_checkable
class CommitteeReader(Protocol):
    """Read the use-cleared buying committee for an account (the M12 ↔ M8/M10 seam).

    Returns one :class:`CommitteeContact` per resolved committee member with its persona/role and
    candidate facet hooks (each carrying its M10 use verdict). Tenant-scoped on ``tenant_id`` (a
    committee assessment and its personal hooks are ``TENANT_PRIVATE``). The production impl
    (``contact_entity`` under the account × persona/facet claims × ``use_decision``) is injected
    at the ``api`` root.
    """

    async def committee_for(
        self, *, account_entity_id: EntityId, tenant_id: str
    ) -> tuple[CommitteeContact, ...]: ...


# --- in-memory fakes (fixtures; no sibling imports) -------------------------------------------


class InMemoryCommitteeReader:
    """A fixture :class:`CommitteeReader` backed by a plain ``{account_entity_id: (members, ...)}``
    map — for M12.1 tests and local runs before the real reader is wired at ``api``.
    """

    def __init__(
        self, committees: dict[EntityId, tuple[CommitteeContact, ...]] | None = None
    ) -> None:
        self._committees = committees or {}

    async def committee_for(
        self, *, account_entity_id: EntityId, tenant_id: str
    ) -> tuple[CommitteeContact, ...]:
        return self._committees.get(account_entity_id, ())


class InMemoryClientKnowledgeRetriever:
    """A fixture ``ClientKnowledgeRetriever`` backed by an in-memory ``{client_entity_id: (chunk,
    ...)}`` map.

    Naive relevance: case-insensitive token overlap with the query, highest overlap first, falling
    back to insertion order; truncated to ``limit``. Stands in for the pgvector /
    ``read_client_kb_claims`` retriever (wired at ``api``) so M12.1 is testable with no ``stage0``
    import.
    """

    def __init__(
        self, chunks: dict[EntityId, tuple[ClientKnowledgeChunk, ...]] | None = None
    ) -> None:
        self._chunks = chunks or {}

    async def retrieve(
        self,
        *,
        client_entity_id: EntityId,
        client_id: str,
        query: str,
        kb_version: int | None = None,
        limit: int = 10,
    ) -> tuple[ClientKnowledgeChunk, ...]:
        return rank_by_query_overlap(self._chunks.get(client_entity_id, ()), query, limit=limit)
