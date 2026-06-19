"""account_entity_embedding + trigram blocking — fuzzy candidate generation (M2.2 / ENG-106)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-19

The probabilistic half of resolution (substrate §2 — *deterministic first, probabilistic second*):
when an exact strong-key lookup misses, the resolver embeds the normalized name and pgvector-ANN
retrieves a bounded candidate set, combined with cheap trigram blocking, before the pairwise scorer
runs. This migration adds the storage for that:

* ``account_entity_embedding`` — a **sidecar** table (``entity_id`` PK → ``account_entity`` with
  ``ON DELETE CASCADE``), holding the name embedding + the ``model_version`` that produced it.
  Keeping it a sidecar rather than a column on ``account_entity`` means re-embedding (a model swap)
  never rewrites the entity row, and the embedding dimension can change without touching the entity
  schema (conventions §2 — the embedder is swappable behind the resolution seam).
* an **HNSW cosine index** on the embedding so ANN retrieval is sub-linear (``<=>`` =
  ``vector_cosine_ops``). pgvector is already enabled by migration 0001.
* the **pg_trgm** extension + a GIN trigram index on ``account_entity.canonical_name`` for the cheap
  blocking key that keeps recall up when an embedding is missing or weak.

The embedding **dimension is fixed** (``vector(N)``) and locked to
``clue_research.identity.embedding.EMBEDDING_DIM`` — a parity test (mirroring the M1 enum-parity
tests) asserts the DB column's declared dimension equals the Python constant, so a model/dimension
change is a deliberate, caught migration rather than a silent mismatch.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from clue_research.identity.embedding import EMBEDDING_DIM

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        f"""
        CREATE TABLE account_entity_embedding (
            entity_id     uuid PRIMARY KEY REFERENCES account_entity(id) ON DELETE CASCADE,
            embedding     vector({EMBEDDING_DIM}) NOT NULL,
            model_version text NOT NULL,
            embedded_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE account_entity_embedding IS 'Name embeddings for fuzzy resolution "
        "candidate generation (M2.2). Sidecar so re-embedding never rewrites the entity row; "
        "vector dim is locked to identity.embedding.EMBEDDING_DIM (parity-tested).'"
    )

    # ANN index for the candidate-set retrieval (cosine distance, the <=> operator). HNSW gives
    # sub-linear recall; on small data Postgres simply scans, so correctness is unaffected.
    op.execute(
        "CREATE INDEX account_entity_embedding_hnsw ON account_entity_embedding "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX account_entity_embedding_model ON account_entity_embedding (model_version)"
    )

    # Trigram blocking key on the display name (cheap recall when the embedding is weak/missing).
    op.execute(
        "CREATE INDEX account_entity_canonical_name_trgm ON account_entity "
        "USING gin (canonical_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS account_entity_canonical_name_trgm")
    op.execute("DROP TABLE IF EXISTS account_entity_embedding")
    # pg_trgm is an extension this migration introduced; drop it on the way down (0001 owns vector).
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
