"""arv2 onboarding knowledge pin

Revision ID: a3fc75e248e0
Revises: 63294c3ce019
Create Date: 2026-09-09 00:14:11.213812+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

ARV2 onboarding **O6**. A production conversation turn opens on the brand's knowledge documents:
they are compiled into a bounded index card and seeded read-only under
``inputs/brand/knowledge/``. Onboarding keeps publishing new document versions in the background,
so a turn that resolved "the current documents" independently on every attempt could seed one set,
crash, and seed a different set on the retry — the file the model was told to re-read would have
moved underneath it.

This table applies the same discipline ``agent_turn_scope_pin`` applies to project/client scope,
to files: one insert-once row per turn, written before composition, carrying the exact document
refs (id, path, kind, version, status, artifact key + digest) and one digest over the whole set.
Every later attempt of that turn reads this row instead of the live documents.

``documents_sha256`` is a bare 64-hex sha256 — the same shape ``brand_knowledge_document``'s own
``artifact_sha256`` uses, never a ``sha256:``-prefixed card digest — so the two can be compared
without a normalization step.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3fc75e248e0"
down_revision: str | None = "63294c3ce019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_turn_knowledge_pin (
            turn_id           uuid PRIMARY KEY,
            workspace_id      text NOT NULL,
            brand_id          text NOT NULL,
            documents         jsonb NOT NULL,
            documents_sha256  text NOT NULL,
            pinned_at         timestamptz NOT NULL DEFAULT now(),

            -- The same turn anchor agent_turn_scope_pin uses: a pin can only name a turn that was
            -- really submitted, in the pin's own workspace.
            CONSTRAINT agent_turn_knowledge_pin_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_knowledge_pin_brand_fk
                FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT agent_turn_knowledge_pin_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(brand_id)) > 0
            ),
            CONSTRAINT agent_turn_knowledge_pin_documents_array CHECK (
                jsonb_typeof(documents) = 'array'
            ),
            CONSTRAINT agent_turn_knowledge_pin_documents_sha256 CHECK (
                documents_sha256 ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_knowledge_pin IS 'ARV2 O6: the immutable set of brand "
        "knowledge documents one AGENT_TURN opens with, written before composition. Every retry "
        "of the turn seeds and indexes exactly these refs; a document version published meanwhile "
        "can only affect a later turn.'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_knowledge_pin.documents_sha256 IS 'Bare 64-hex sha256 over "
        "the pinned refs in path order — the value two attempts of one turn compare to prove they "
        "composed the same knowledge.'"
    )
    op.execute(
        "CREATE INDEX agent_turn_knowledge_pin_brand "
        "ON agent_turn_knowledge_pin (workspace_id, brand_id, pinned_at DESC)"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_knowledge_pin_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_knowledge_pin "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_knowledge_pin_append_only ON agent_turn_knowledge_pin"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_knowledge_pin_brand")
    op.execute("DROP TABLE IF EXISTS agent_turn_knowledge_pin")
