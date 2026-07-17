"""M12.1 api-root wiring (ENG-158): the value-narrative pack registration + the pre-flight
Client-Knowledge retriever stub. Pure (no DB) — the stub's DB read is exercised at integration."""

from __future__ import annotations

from clue_core.retrieval import ClientKnowledgeRetriever
from clue_research.api import composition
from clue_research.api.narrative_wiring import (
    ClientKnowledgeRetrieverStub,
    build_client_knowledge_retriever,
    register_narrative_wiring,
)
from clue_research.narrative import load_narrative_pack


def test_register_narrative_wiring_appends_pack_idempotently() -> None:
    saved = list(composition.RESEARCH_PACK_LOADERS)
    try:
        composition.RESEARCH_PACK_LOADERS[:] = [
            loader for loader in saved if loader is not load_narrative_pack
        ]
        register_narrative_wiring()
        register_narrative_wiring()  # idempotent — a second call must not duplicate
        assert composition.RESEARCH_PACK_LOADERS.count(load_narrative_pack) == 1
    finally:
        composition.RESEARCH_PACK_LOADERS[:] = saved  # never leak global state to sibling tests


def test_client_knowledge_retriever_stub_conforms_to_seam() -> None:
    retriever = build_client_knowledge_retriever()
    assert isinstance(retriever, ClientKnowledgeRetrieverStub)
    # structural conformance to the frozen core.retrieval seam (runtime_checkable).
    assert isinstance(retriever, ClientKnowledgeRetriever)
