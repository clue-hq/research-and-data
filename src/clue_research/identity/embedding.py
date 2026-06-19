"""Name embeddings for fuzzy candidate generation (M2.2).

The probabilistic stage embeds a normalized name and pgvector-ANN retrieves similar entities. The
**embedder is swappable behind the resolution seam** (conventions §2): callers depend on the
:class:`Embedder` protocol, never a concrete model, so a learned sentence-embedder can replace the
default without changing ``resolve``'s signature — the stored ``model_version`` records which model
produced each row, so a swap re-embeds explicitly.

The default :class:`HashingEmbedder` is **deterministic and offline**: it feature-hashes character
trigrams + token unigrams of the normalized name into a fixed-dimension unit vector using a stable
hash (``blake2b``, *not* Python's salted ``hash()``). This is what lets the M2.2 tests assert "zero
embedding calls on a deterministic hit" and run a recall fixture with no network — and it still
gives the scorer a usable name-similarity signal (shared n-grams → high cosine).

``EMBEDDING_DIM`` is the fixed vector dimension the ``account_entity_embedding`` column is declared
with (migration 0006); a parity test asserts the DB column matches this constant.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import EntityId
from clue_research.identity.normalize import normalize_name

# The fixed embedding dimension. Locked to the ``vector(N)`` column in migration 0006 (parity test).
EMBEDDING_DIM = 128

# The default model version stamp (stored per row so a re-embed under a new model is auditable).
DEFAULT_MODEL_VERSION = "hash-trigram-v1"


@runtime_checkable
class Embedder(Protocol):
    """The swappable embedding model. Callers depend on this, not a concrete embedder."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_version(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


def _stable_bucket(token: str) -> tuple[int, float]:
    """Map a token to a ``(bucket, sign)`` deterministically via blake2b (process-stable)."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    bucket = value % EMBEDDING_DIM
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return bucket, sign


def _features(normalized: str) -> list[str]:
    """The n-gram + token features of a normalized name (char trigrams over each padded token,
    plus the token unigrams) — shared n-grams are what make similar names embed close."""
    feats: list[str] = []
    for token in normalized.split():
        feats.append(f"_{token}_")  # the whole token (unigram)
        padded = f"  {token}  "
        for i in range(len(padded) - 2):
            feats.append(padded[i : i + 3])  # char trigram
    return feats


class HashingEmbedder:
    """A deterministic, offline feature-hashing embedder (the default :class:`Embedder`)."""

    def __init__(
        self, *, dimension: int = EMBEDDING_DIM, model_version: str = DEFAULT_MODEL_VERSION
    ) -> None:
        self._dimension = dimension
        self._model_version = model_version

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_version(self) -> str:
        return self._model_version

    def embed(self, text: str) -> list[float]:
        """Embed a name to a unit vector (empty / non-foldable names → the zero vector)."""
        vec = [0.0] * self._dimension
        for feature in _features(normalize_name(text)):
            bucket, sign = _stable_bucket(feature)
            vec[bucket % self._dimension] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec  # zero vector: cosine similarity with anything is 0 (a clean "no signal")
        return [x / norm for x in vec]


# The process default embedder (injected explicitly in tests / by the resolver).
DEFAULT_EMBEDDER: Embedder = HashingEmbedder()


def vector_literal(vector: list[float]) -> str:
    """Render a vector in pgvector's text format (``[1,2,3]``) for a ``CAST(:v AS vector)``."""
    return "[" + ",".join(repr(x) for x in vector) + "]"


_UPSERT_EMBEDDING = text(
    """
    INSERT INTO account_entity_embedding (entity_id, embedding, model_version, embedded_at)
    VALUES (:entity_id, CAST(:embedding AS vector), :model_version, now())
    ON CONFLICT (entity_id) DO UPDATE
        SET embedding = EXCLUDED.embedding,
            model_version = EXCLUDED.model_version,
            embedded_at = now()
    """
)


async def embed_account(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    embedder: Embedder = DEFAULT_EMBEDDER,
    text_override: str | None = None,
) -> bool:
    """Embed an account's name and upsert it into ``account_entity_embedding``.

    By default embeds the entity's ``canonical_name``; ``text_override`` forces a specific string
    (e.g. a richer name+aliases blob). Returns ``False`` if the entity does not exist. Idempotent
    (upsert): re-embedding under a new ``embedder.model_version`` replaces the row in place — the
    embedding is derived data, not an append-only claim.
    """
    name = text_override
    if name is None:
        row = (
            await conn.execute(
                text("SELECT canonical_name FROM account_entity WHERE id = :id"),
                {"id": entity_id},
            )
        ).first()
        if row is None:
            return False
        name = row[0]
    await conn.execute(
        _UPSERT_EMBEDDING,
        {
            "entity_id": entity_id,
            "embedding": vector_literal(embedder.embed(name)),
            "model_version": embedder.model_version,
        },
    )
    return True
