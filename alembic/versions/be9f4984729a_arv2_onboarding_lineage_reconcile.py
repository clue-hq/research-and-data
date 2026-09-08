"""arv2 onboarding lineage reconcile

Revision ID: be9f4984729a
Revises: a3602967bb73
Create Date: 2026-09-08 18:31:56.959993+00:00

Track O (ARV2 onboarding), O3 — the substrate the catalog identity ladder writes to.

``af3cf1541ebe`` gave ``onboarding_product_lineage`` the S5 resolution vocabulary verbatim
(``created`` / ``alias_reused`` / ``lineage_reused`` / ``unresolved_ambiguous``). The ladder adds a
fourth, batched stage — a model reconciliation over the entries no deterministic rung resolved —
so two states join the taxonomy and both, like every resolved state, carry a product:

- ``model_reused``  — the reconciler matched the entry onto an existing product row.
- ``model_unsure``  — the reconciler minted, but said so with less than full confidence.

``unresolved_ambiguous`` stays the ONLY product-less state, so "did this entry get a product?"
remains a single structural question rather than a per-state lookup table.

Two nullable columns record the reconciler's own account of itself: ``reconcile_confidence``
(``high`` / ``medium`` / ``low``, CHECKed, NULL for every deterministically-resolved row) and the
free-text ``reconcile_reason``. They are nullable because the deterministic rungs neither produce
nor need them — a NULL says "no model decided this", which is the honest reading.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

The table's append-only trigger is ``BEFORE UPDATE`` on rows; ``ALTER TABLE`` is unaffected by it.
``downgrade()`` narrows the state CHECK back, so it refuses while any model-decided row exists
rather than leaving rows the restored constraint would reject (the ``af3cf1541ebe`` precedent).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be9f4984729a"
down_revision: str | None = "a3602967bb73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Resolution states carrying a product AFTER this migration. The two model states join the four
#: S5 words verbatim; ``unresolved_ambiguous`` stays the only product-less state.
_RESOLVED_AFTER = "'created', 'alias_reused', 'lineage_reused', 'model_reused', 'model_unsure'"

#: What ``downgrade()`` restores — the ``af3cf1541ebe`` set.
_RESOLVED_BEFORE = "'created', 'alias_reused', 'lineage_reused'"

_STATE_CONSTRAINT = "onboarding_product_lineage_state"
_CONFIDENCE_CONSTRAINT = "onboarding_product_lineage_reconcile_confidence"


def _state_check(resolved: str) -> str:
    return (
        f"ALTER TABLE onboarding_product_lineage ADD CONSTRAINT {_STATE_CONSTRAINT} CHECK ("
        f"(resolution_state IN ({resolved}) AND product_id IS NOT NULL) "
        "OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL))"
    )


def upgrade() -> None:
    op.execute(f"ALTER TABLE onboarding_product_lineage DROP CONSTRAINT {_STATE_CONSTRAINT}")
    op.execute(_state_check(_RESOLVED_AFTER))
    op.execute("ALTER TABLE onboarding_product_lineage ADD COLUMN reconcile_confidence text")
    op.execute("ALTER TABLE onboarding_product_lineage ADD COLUMN reconcile_reason text")
    op.execute(
        f"ALTER TABLE onboarding_product_lineage ADD CONSTRAINT {_CONFIDENCE_CONSTRAINT} CHECK "
        "(reconcile_confidence IS NULL OR reconcile_confidence IN ('high', 'medium', 'low'))"
    )


def downgrade() -> None:
    # The restored CHECK would reject the model states, so refuse rather than leave rows behind
    # a constraint they violate (the ``af3cf1541ebe`` precedent for an unremovable enum label).
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM onboarding_product_lineage
                WHERE resolution_state IN ('model_reused', 'model_unsure')
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade the identity ladder while model-decided lineage rows exist';
            END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE onboarding_product_lineage DROP CONSTRAINT {_CONFIDENCE_CONSTRAINT}")
    op.execute("ALTER TABLE onboarding_product_lineage DROP COLUMN reconcile_reason")
    op.execute("ALTER TABLE onboarding_product_lineage DROP COLUMN reconcile_confidence")
    op.execute(f"ALTER TABLE onboarding_product_lineage DROP CONSTRAINT {_STATE_CONSTRAINT}")
    op.execute(_state_check(_RESOLVED_BEFORE))
