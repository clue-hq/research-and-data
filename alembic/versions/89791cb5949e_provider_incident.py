"""provider incident

Revision ID: 89791cb5949e
Revises: b7193eb28363
Create Date: 2026-09-16 11:36:07.540210+00:00

Provider incidents (design 2026-09-16 §3.3). One row per stretch during which an external
provider refused to serve us or failed repeatedly. The partial unique index is the open-once
rule: two processes seeing the same refusal race on the insert and exactly one wins, so exactly
one Sentry event leaves the box. Rows are never deleted; ``closed_at`` ends a stretch.

Reversible: the downgrade drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "89791cb5949e"
down_revision: str | None = "b7193eb28363"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_incident (
            incident_id           uuid PRIMARY KEY,
            provider              text NOT NULL,
            kind                  text NOT NULL CHECK (kind IN ('refusal', 'failure')),
            reason                text NOT NULL,
            opened_at             timestamptz NOT NULL,
            last_failure_at       timestamptz NOT NULL,
            failure_count         integer NOT NULL CHECK (failure_count >= 1),
            sample_message        text NOT NULL,
            surfaces_json         jsonb NOT NULL DEFAULT '{}'::jsonb,
            workspaces_json       jsonb NOT NULL DEFAULT '[]'::jsonb,
            closed_at             timestamptz,
            sentry_open_event_id  text,
            sentry_close_event_id text,
            CONSTRAINT provider_incident_closed_after_open
                CHECK (closed_at IS NULL OR closed_at >= opened_at)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX provider_incident_one_open "
        "ON provider_incident (provider, reason) WHERE closed_at IS NULL"
    )
    op.execute(
        "CREATE INDEX provider_incident_provider_opened "
        "ON provider_incident (provider, opened_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE provider_incident")
