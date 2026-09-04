"""require selected product knowledge on new turn pins

Revision ID: ab295072ba84
Revises: f5f8c50f70f3
Create Date: 2026-08-19 08:03:41.048371+00:00

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
revision: str = "ab295072ba84"
down_revision: str | None = "f5f8c50f70f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_turn_scope_pin DROP CONSTRAINT agent_turn_scope_pin_policy_shape")
    op.execute(
        "ALTER TABLE agent_turn_scope_pin "
        "ADD CONSTRAINT agent_turn_scope_pin_policy_shape CHECK ("
        "(knowledge_scope_policy_version = 'company-account-wide-v1' "
        "AND product_kb_version IS NULL) OR "
        "(knowledge_scope_policy_version = 'company-and-selected-product-v2') OR "
        "(knowledge_scope_policy_version = 'company-and-selected-product-required-v3' AND ("
        "(product_id IS NULL AND product_kb_version IS NULL) OR "
        "(product_id IS NOT NULL AND client_entity_id IS NOT NULL "
        "AND client_kb_version IS NOT NULL AND product_kb_version IS NOT NULL))))"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_scope_pin.product_kb_version IS 'Exact independently "
        "versioned selected-product knowledge pin. Historical V1/V2 receipts may be NULL; under "
        "company-and-selected-product-required-v3 every selected-product turn carries a version, "
        "including an honest empty baseline.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_turn_scope_pin DROP CONSTRAINT agent_turn_scope_pin_policy_shape")
    op.execute(
        "ALTER TABLE agent_turn_scope_pin "
        "ADD CONSTRAINT agent_turn_scope_pin_policy_shape CHECK ("
        "(knowledge_scope_policy_version = 'company-account-wide-v1' "
        "AND product_kb_version IS NULL) OR "
        "(knowledge_scope_policy_version = 'company-and-selected-product-v2'))"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_scope_pin.product_kb_version IS 'S5: exact independently "
        "versioned selected-product knowledge pin. NULL means no confirmed product or no "
        "published Product-KB at this turn snapshot.'"
    )
