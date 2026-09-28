"""design logo family cache

Revision ID: 1d09aba87206
Revises: 6eff96862040
Create Date: 2026-09-01

The durable target-logo family cache (vendor-first logo family, Task 7; founder decision #4,
2026-08-31). One row per ``(workspace_id, registrable_domain)`` holding the whole 2x2 family:
the cells' content digests plus the provenance/evidence each prepared cell was born with, so a
cache hit rebuilds the outcome without re-running either the vendor or the ladder rung.

* **Keyed on the DOMAIN, not an account id** (founder ruling 2026-09-02): the fetch tool
  receives a site, and the agent may fetch for companies that are no account of ours.
* **Workspace-scoped by the row itself.** ``workspace_id text NOT NULL`` with a real FK to
  ``workspace`` — the ``design_account`` shape from ``86a9ce389e6e``. A foreign workspace's
  read is an ordinary miss, so tenancy is structural rather than caller discipline.
* **No TTL.** The eviction affordance is ``force_refresh`` on the fetch tool, which overwrites
  through the UPSERT and stamps ``refreshed_at``; ``fetched_at`` keeps the first capture.
* The cache is an OPTIMIZATION, never a gate — nothing downstream reads this table as truth,
  and a read that fails (or whose bytes are no longer in custody) is simply a miss.

Hand-written and reversible, named constraints: ``downgrade()`` mirrors ``upgrade()``
(CI runs up -> down -> up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1d09aba87206"
down_revision: str | None = "6eff96862040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_logo_family (
            workspace_id        text        NOT NULL,
            registrable_domain  text        NOT NULL,
            family              jsonb       NOT NULL,
            fetched_at          timestamptz NOT NULL DEFAULT now(),
            refreshed_at        timestamptz,
            CONSTRAINT design_logo_family_pk
                PRIMARY KEY (workspace_id, registrable_domain),
            CONSTRAINT design_logo_family_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_logo_family")
