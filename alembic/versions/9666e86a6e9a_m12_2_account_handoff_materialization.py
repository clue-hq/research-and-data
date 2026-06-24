"""m12_2 account_handoff materialization

Revision ID: 9666e86a6e9a
Revises: 11299b862da3
Create Date: 2026-06-24 17:12:37.627259+00:00

M12.2 materialises the assembled ``account_handoff`` on assembly (recompute on supersede — the
recommended persistence in overview §3 / the M12.2 spec): a row per ``(client_id,
account_entity_id, icp_spec_version)`` holding the serialized
``clue_research.narrative.handoff.AssembledHandoff`` (the frozen ``AccountHandoff`` object + the
M12.2 extras — the D6 non-fit flag, the narrative citations, the coverage gaps) as a JSONB
``payload``, so M12.3 serves a stable object with a precomputed provenance index and Postgres stays
the only source of truth (conventions §6 / substrate §12).

The handoff is **tenant-private** (a client's *assembled* view — substrate §2): the same public
account researched by two clients yields two handoffs, so the key is per-``client_id``. The
``assemble`` step is a pure read; this table caches it, idempotent on the scope key (re-assembling
after a claim is superseded UPSERTs a fresh ``payload`` + ``assembled_at`` — AC8). No domain claim
is written here (a read-projection of the claim store, never a write-back path).

``downgrade()`` drops the table (CI runs up → down → up). No enum, no trigger, no ``claim`` ALTER.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9666e86a6e9a"
down_revision: str | None = "11299b862da3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE account_handoff (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            client_id         text NOT NULL,
            account_entity_id uuid NOT NULL,
            icp_spec_version  int NOT NULL,
            campaign_run_id   uuid,
            assembled_at      timestamptz NOT NULL,
            payload           jsonb NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_handoff_icp_version_positive CHECK (icp_spec_version >= 1)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE account_handoff IS 'M12.2 materialised account_handoff (overview §3): a "
        "row per (client_id, account_entity_id, icp_spec_version) holding the serialized "
        "AssembledHandoff (frozen AccountHandoff + the M12.2 extras) as JSONB. Tenant-private "
        "(substrate §2): a client''s assembled view, recomputed on supersede (UPSERT). A "
        "read-projection of the claim store — never a write-back path (conventions §6).'"
    )
    # The scope key (client_id, account_entity_id, icp_spec_version) — re-assembly UPSERTs the slot.
    # The same public account under two clients/ICPs keeps distinct handoffs (D5; substrate §2).
    op.execute(
        "CREATE UNIQUE INDEX account_handoff_scope "
        "ON account_handoff (client_id, account_entity_id, icp_spec_version)"
    )
    # Serve path: all handoffs for an account; the campaign-run list (M12.3).
    op.execute("CREATE INDEX account_handoff_account ON account_handoff (account_entity_id)")
    op.execute(
        "CREATE INDEX account_handoff_campaign_run "
        "ON account_handoff (campaign_run_id) WHERE campaign_run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS account_handoff_campaign_run")
    op.execute("DROP INDEX IF EXISTS account_handoff_account")
    op.execute("DROP INDEX IF EXISTS account_handoff_scope")
    op.execute("DROP TABLE IF EXISTS account_handoff")
