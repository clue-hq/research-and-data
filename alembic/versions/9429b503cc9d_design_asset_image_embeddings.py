"""design asset image embeddings

Revision ID: 9429b503cc9d
Revises: 4a94970221e9
Create Date: 2026-10-05 14:39:55.753899+00:00

One CLIP image vector per design asset and embedding model (founder ruling 2026-10-05: the scene
agent's ``search_assets`` fuses today's keyword ranking with a visual ranking). A sidecar, like
``account_entity_embedding``, so re-embedding never rewrites the asset or its description.

- ``model`` names the embedding SPACE (``openai/clip-vit-base-patch32``), not the precision a
  given host ran: image vectors and query vectors only need to share the space.
- ``preview_digest`` is the sha256 of the preview pixels that were embedded, so ingestion can skip
  an asset whose preview has not changed and re-embed one whose preview has.
- No ANN index: a workspace library is hundreds of rows and is read whole into the turn.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9429b503cc9d"
down_revision: str | None = "4a94970221e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: CLIP ViT-B/32's projection width. A different model space needs its own migration.
EMBEDDING_DIM = 512


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""
        CREATE TABLE design_asset_embedding (
            asset_id       text NOT NULL,
            workspace_id   text NOT NULL,
            model          text NOT NULL,
            preview_digest text NOT NULL,
            embedding      vector({EMBEDDING_DIM}) NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_asset_embedding_pkey PRIMARY KEY (asset_id, workspace_id, model),
            CONSTRAINT design_asset_embedding_asset_fk FOREIGN KEY (asset_id, workspace_id)
                REFERENCES design_asset (asset_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_asset_embedding_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_asset_embedding_digest_shape CHECK (preview_digest ~ '^[0-9a-f]{{64}}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX design_asset_embedding_workspace_model "
        "ON design_asset_embedding (workspace_id, model)"
    )
    op.execute(
        "COMMENT ON TABLE design_asset_embedding IS 'CLIP image vectors for the scene agent''s "
        "hybrid asset search. Sidecar to design_asset; model is the embedding space.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS design_asset_embedding")
