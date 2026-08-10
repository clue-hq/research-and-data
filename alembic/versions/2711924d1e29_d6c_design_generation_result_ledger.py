"""d6c design generation result ledger

Revision ID: 2711924d1e29
Revises: ad332dc38f36
Create Date: 2026-08-10

Part II slice D6 Round C — the generation cache gets its Postgres home.

``lumen_api.image_cache`` maps a normalized image-generation request (prompt + model +
constraints + reference/source digests) to the asset record it produced, so an identical repeat
re-places the same image instead of re-paying the provider. Since D4 it has persisted that map as
a **mutable JSON sidecar** at ``{engine_cache_root}/{workspace_id}/.generation-cache.json``, with
a LOUD WARNING in its own docstring naming this round as the fix. Three defects, not one:

* the engine cache is a wipeable mirror by construction, so the index that decides whether we pay
  a provider lived in the one tree the system is allowed to delete;
* a whole-file rewrite is last-writer-wins across processes — two API workers pointed at the same
  directory silently double-spend;
* nothing tied an entry to the asset row it named, so a hard-deleted asset stayed cached forever.

``design_generation_result`` fixes all three: workspace-scoped and durable, a real primary key
that arbitrates concurrent claims, and a composite FK to ``design_asset`` whose ``ON DELETE
CASCADE`` makes "cached pointer to a deleted asset" unrepresentable.

``record_json`` is the record **as produced**, kept for provenance; the read path joins the LIVE
``design_asset.record_json`` so a later description edit or re-registration is visible to a cache
hit. The ledger key itself (``generation_key``) is unchanged — only its storage moves.

Scope note: the AGENT-RUNTIME half of the cache (``lumen_agent.tools.substrate``) deliberately
stays on the file sidecar. The design agent runtime holds no database handle by design (it is
trace/cache-local), and giving it one is Part-III work, not a migration.

Hand-written and reversible: ``downgrade()`` drops the table. That destroys only a cost-saving
index — every asset it points at has durable custody of its own — so it needs no refusal guard.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2711924d1e29"
down_revision: str | None = "ad332dc38f36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _literal(text: str) -> str:
    """A SQL string literal (single quotes doubled)."""
    doubled = text.replace("'", "''")
    return f"'{doubled}'"


_COMMENTS = (
    (
        "design_generation_result",
        "Generation-result ledger (PD D6 Round C): request key -> the asset it produced, so an "
        "identical repeat re-places the same image instead of re-paying the provider. Replaces "
        "the .generation-cache.json sidecar under the wipeable engine materialization cache.",
    ),
    (
        "design_generation_result.generation_key",
        "sha256 of the normalized generation request (prompt, model, dimensions, brand notes, "
        "aspect/size, transparency, reference asset ids + pixel digests, and for edits the "
        "source digest). Computed by lumen_api.image_cache.generation_key; unchanged by the move.",
    ),
    (
        "design_generation_result.asset_id",
        "The asset this request produced. Composite FK to design_asset ON DELETE CASCADE: hard "
        "deleting the asset retires its cache entry, so the ledger can never serve a dead id.",
    ),
    (
        "design_generation_result.record_json",
        "The engine AssetRecord as produced, kept for provenance. Readers join the LIVE "
        "design_asset.record_json instead, so later curation is visible to a cache hit.",
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_generation_result (
          workspace_id   text        NOT NULL REFERENCES workspace (workspace_id)
                                       ON DELETE CASCADE,
          generation_key text        NOT NULL,
          asset_id       text        NOT NULL,
          record_json    jsonb       NOT NULL,
          created_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT design_generation_result_pk
            PRIMARY KEY (workspace_id, generation_key),
          CONSTRAINT design_generation_result_asset_fk
            FOREIGN KEY (asset_id, workspace_id)
            REFERENCES design_asset (asset_id, workspace_id) ON DELETE CASCADE,
          CONSTRAINT design_generation_result_key_nonempty
            CHECK (length(generation_key) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX design_generation_result_asset_idx"
        " ON design_generation_result (workspace_id, asset_id)"
    )
    for target, comment in _COMMENTS:
        keyword = "COLUMN" if "." in target else "TABLE"
        op.execute(f"COMMENT ON {keyword} {target} IS {_literal(comment)}")


def downgrade() -> None:
    op.execute("DROP INDEX design_generation_result_asset_idx")
    op.execute("DROP TABLE design_generation_result")
