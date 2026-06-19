"""M2.2 — the deterministic offline embedder (pure, no DB)."""

from __future__ import annotations

import math

from clue_research.identity.embedding import (
    DEFAULT_MODEL_VERSION,
    EMBEDDING_DIM,
    HashingEmbedder,
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def test_embedding_is_deterministic_and_fixed_dimension() -> None:
    e = HashingEmbedder()
    v1 = e.embed("Acme Logistics")
    v2 = e.embed("Acme Logistics")
    assert v1 == v2  # process-stable (blake2b, not salted hash())
    assert len(v1) == EMBEDDING_DIM == e.dimension
    assert e.model_version == DEFAULT_MODEL_VERSION


def test_empty_name_embeds_to_zero_vector() -> None:
    e = HashingEmbedder()
    assert e.embed("") == [0.0] * EMBEDDING_DIM
    assert e.embed("   ") == [0.0] * EMBEDDING_DIM
    # cosine with the zero vector is a clean 0 (no signal), never a crash.
    assert _cosine(e.embed(""), e.embed("Acme")) == 0.0


def test_unit_norm_for_nonempty() -> None:
    e = HashingEmbedder()
    v = e.embed("International Business Machines")
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, abs_tol=1e-9)


def test_similar_names_embed_closer_than_unrelated() -> None:
    e = HashingEmbedder()
    base = e.embed("International Business Machines")
    similar = e.embed("International Business Machines Corp")
    unrelated = e.embed("Globex Pharmaceuticals")
    assert _cosine(base, similar) > _cosine(base, unrelated)
    assert _cosine(base, similar) > 0.6


def test_swapping_model_version_is_visible() -> None:
    e = HashingEmbedder(model_version="hash-trigram-v2")
    assert e.model_version == "hash-trigram-v2"
    assert len(e.embed("Acme")) == EMBEDDING_DIM
