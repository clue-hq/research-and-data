"""Decouple durable page acquisition from outgoing-link expansion.

Revision ID: 2500c418396f
Revises: df332fd7904c
Create Date: 2026-08-15 14:11:19.282870+00:00

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
revision: str = "2500c418396f"
down_revision: str | None = "df332fd7904c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE official_site_link_expansion (
            id                   uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            crawl_run_id         uuid NOT NULL,
            page_id              uuid NOT NULL,
            snapshot_id          uuid NOT NULL,
            state                text NOT NULL DEFAULT 'queued',
            outgoing_links_json  jsonb NOT NULL DEFAULT '[]'::jsonb,
            lease_owner          text,
            lease_generation     bigint NOT NULL DEFAULT 0,
            lease_acquired_at    timestamptz,
            lease_expires_at     timestamptz,
            attempt_count        integer NOT NULL DEFAULT 0,
            next_attempt_at      timestamptz,
            failure_stage        text,
            failure_code         text,
            failure_class        text,
            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now(),
            completed_at         timestamptz,

            CONSTRAINT official_site_link_expansion_scope_anchor
                UNIQUE (id, workspace_id),
            CONSTRAINT official_site_link_expansion_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_link_expansion_page_fk
                FOREIGN KEY (page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_link_expansion_snapshot_fk
                FOREIGN KEY (snapshot_id, page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_page_snapshot (id, page_id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_link_expansion_snapshot_once UNIQUE (snapshot_id),
            CONSTRAINT official_site_link_expansion_state CHECK (
                state IN ('queued', 'leased', 'retry_wait', 'completed', 'failed')
            ),
            CONSTRAINT official_site_link_expansion_links_array
                CHECK (jsonb_typeof(outgoing_links_json) = 'array'),
            CONSTRAINT official_site_link_expansion_nonnegative CHECK (
                lease_generation >= 0 AND attempt_count >= 0
            ),
            CONSTRAINT official_site_link_expansion_lease_shape CHECK (
                (state = 'leased' AND lease_owner IS NOT NULL
                    AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL)
                OR (state <> 'leased' AND lease_owner IS NULL
                    AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)
            ),
            CONSTRAINT official_site_link_expansion_lease_times CHECK (
                lease_expires_at IS NULL OR lease_expires_at > lease_acquired_at
            ),
            CONSTRAINT official_site_link_expansion_state_shape CHECK (
                (state = 'retry_wait' AND next_attempt_at IS NOT NULL
                    AND failure_stage = 'link_expansion' AND failure_code IS NOT NULL
                    AND failure_class IS NOT NULL AND completed_at IS NULL)
                OR (state = 'failed' AND next_attempt_at IS NULL
                    AND failure_stage = 'link_expansion' AND failure_code IS NOT NULL
                    AND failure_class IS NOT NULL AND completed_at IS NOT NULL)
                OR (state = 'completed' AND next_attempt_at IS NULL
                    AND failure_stage IS NULL AND failure_code IS NULL
                    AND failure_class IS NULL AND completed_at IS NOT NULL)
                OR (state IN ('queued', 'leased') AND next_attempt_at IS NULL
                    AND failure_stage IS NULL AND failure_code IS NULL
                    AND failure_class IS NULL AND completed_at IS NULL)
            ),
            CONSTRAINT official_site_link_expansion_failure_bounds CHECK (
                (failure_code IS NULL OR length(failure_code) <= 120)
                AND (failure_class IS NULL OR length(failure_class) <= 200)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_link_expansion_claim "
        "ON official_site_link_expansion "
        "(crawl_run_id, state, next_attempt_at, created_at, id) "
        "WHERE state IN ('queued', 'retry_wait')"
    )
    op.execute(
        "CREATE INDEX official_site_link_expansion_reclaim "
        "ON official_site_link_expansion (state, lease_expires_at) WHERE state = 'leased'"
    )
    op.execute(
        "CREATE INDEX official_site_link_expansion_progress "
        "ON official_site_link_expansion (workspace_id, crawl_run_id, state)"
    )

    # Legacy fetched pages already completed expansion inside the old acquisition hook. Backfill
    # a terminal row so upgrades do not rediscover links or mutate an historical checkpoint.
    op.execute(
        """
        INSERT INTO official_site_link_expansion (
            id, workspace_id, crawl_run_id, page_id, snapshot_id, state,
            outgoing_links_json, attempt_count, created_at, updated_at, completed_at
        )
        SELECT snapshot.id, snapshot.workspace_id, snapshot.crawl_run_id, snapshot.page_id,
               snapshot.id, 'completed', '[]'::jsonb, 1,
               snapshot.created_at, COALESCE(page.fetched_at, snapshot.created_at),
               COALESCE(page.fetched_at, snapshot.created_at)
        FROM official_site_page_snapshot AS snapshot
        JOIN official_site_crawl_page AS page
          ON page.id = snapshot.page_id
         AND page.crawl_run_id = snapshot.crawl_run_id
         AND page.workspace_id = snapshot.workspace_id
        WHERE page.state = 'fetched' AND page.latest_snapshot_id = snapshot.id
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE official_site_link_expansion")
