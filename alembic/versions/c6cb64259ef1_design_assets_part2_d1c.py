"""design assets (part2 D1c)

Revision ID: c6cb64259ef1
Revises: 51db518c2a68
Create Date: 2026-08-07

Part II slice D1, migration (c) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 9–11): the design asset registry — ``design_asset`` + ``design_asset_description``,
porting SQLite ``004_assets.sql`` + ``008_asset_descriptions.sql``.

* **Registry only, never bytes** (unchanged invariant): ``record_json`` is the canonical Rust
  ``AssetRecord``; the scalar columns are query projections of it. Bytes stay in the API-local
  content-addressed store until **D4** moves them to platform storage (``clue_storage``,
  ``{ws}/{sha}`` keys) and re-points ``record_json.media.location``.
* **O3 (RATIFIED, clarified):** the legacy ``asset_metadata`` table is DROPPED (not ported —
  its endpoint 410s at D2). ``design_asset_description`` is expressly preserved with its full
  behavior — AI generation, human-wins conditional upsert (enforced by the D2 DAL:
  ``WHERE origin != 'human'``), model attribution, caching, and description stamping into
  versioned brand kits. It gains its real FK (1:1 on the registry row) that SQLite omitted.
* Digest columns keep sha256 shape CHECKs; dedup queries are workspace-scoped (indexes) — no
  cross-tenant identity, matching the B3 account-localization ruling's spirit.
* Enum type ``design_description_origin`` mirrors ``clue_design.enums``.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6cb64259ef1"
down_revision: str | None = "51db518c2a68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_DESCRIPTION_ORIGIN = ("ai", "human")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE design_description_origin AS ENUM ({_enum_values_sql(_DESCRIPTION_ORIGIN)})"
    )

    # --- design_asset: the content-addressed asset registry (bytes live elsewhere) -----------
    op.execute(
        """
        CREATE TABLE design_asset (
            asset_id     text NOT NULL,
            workspace_id text NOT NULL,
            label        text NOT NULL,
            kind         text NOT NULL,
            status       text NOT NULL,
            mime_type    text,
            digest_algorithm text,
            digest_value     text,
            byte_length      bigint,
            filename         text,
            tags_json    jsonb NOT NULL DEFAULT '[]'::jsonb,
            record_json  jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_asset_pkey PRIMARY KEY (asset_id),
            CONSTRAINT design_asset_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_asset_workspace_anchor UNIQUE (asset_id, workspace_id),
            CONSTRAINT design_asset_digest_shape
                CHECK (digest_value IS NULL OR digest_value ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_asset_byte_length_nonneg
                CHECK (byte_length IS NULL OR byte_length >= 0),
            CONSTRAINT design_asset_tags_array CHECK (jsonb_typeof(tags_json) = 'array'),
            CONSTRAINT design_asset_record_object CHECK (jsonb_typeof(record_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_asset IS 'Design asset registry (PD D1c) — record_json is "
        "the canonical AssetRecord; scalar columns are projections. Bytes are NEVER here: "
        "API-local content-addressed store until D4, then platform clue_storage.'"
    )
    op.execute(
        "CREATE INDEX design_asset_digest ON design_asset (workspace_id, digest_value) "
        "WHERE digest_value IS NOT NULL"
    )
    op.execute("CREATE INDEX design_asset_kind_status ON design_asset (workspace_id, kind, status)")

    # --- design_asset_description: curated/AI descriptions (1:1, human wins) -----------------
    op.execute(
        """
        CREATE TABLE design_asset_description (
            asset_id     text NOT NULL,
            workspace_id text NOT NULL,
            title        text,
            description  text,
            usage        text,
            tags_json    jsonb NOT NULL DEFAULT '[]'::jsonb,
            origin       design_description_origin NOT NULL,
            model        text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_asset_description_pkey PRIMARY KEY (asset_id),
            CONSTRAINT design_asset_description_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- Real 1:1 FK now (SQLite deliberately omitted it).
            CONSTRAINT design_asset_description_asset_fk
                FOREIGN KEY (asset_id, workspace_id)
                REFERENCES design_asset (asset_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_asset_description_tags_array
                CHECK (jsonb_typeof(tags_json) = 'array'),
            -- AI rows attribute their model; human rows need none.
            CONSTRAINT design_asset_description_ai_has_model
                CHECK (origin != 'ai' OR model IS NOT NULL)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_asset_description IS 'Asset descriptions (PD D1c; O3 "
        "clarified — preserved with full behavior). Human curation wins: the D2 DAL''s AI "
        "upsert is conditional (WHERE origin != ''human''); descriptions stamp into versioned "
        "brand kits.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_asset_description")
    op.execute("DROP TABLE design_asset")
    op.execute("DROP TYPE design_description_origin")
