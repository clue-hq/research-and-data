"""enforce discovery, scoring, and human-checkpoint sequence

Revision ID: 3f41f54d6238
Revises: 0567b5fdf1ad
Create Date: 2026-08-03 07:34:35.457632+00:00

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
revision: str = "3f41f54d6238"
down_revision: str | None = "0567b5fdf1ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION discovery_enforce_post_seal_phase_sequence() RETURNS trigger AS $$
        DECLARE
            phase_checkpoint record;
        BEGIN
            IF OLD.phase = 'discovery' AND NEW.phase <> 'scoring' THEN
                RAISE EXCEPTION
                    'project run % cannot skip scoring after discovery', NEW.id;
            END IF;
            IF OLD.phase = 'scoring' AND NEW.phase <> 'tier_checkpoint' THEN
                RAISE EXCEPTION
                    'project run % cannot skip the tier checkpoint after scoring', NEW.id;
            END IF;
            IF OLD.phase = 'tier_checkpoint' AND NEW.phase <> 'deep' THEN
                RAISE EXCEPTION
                    'project run % cannot skip deep after the tier checkpoint', NEW.id;
            END IF;

            IF OLD.phase = 'scoring' AND NEW.phase = 'tier_checkpoint' THEN
                SELECT checkpoint.* INTO phase_checkpoint
                FROM project_phase_checkpoint checkpoint
                WHERE checkpoint.project_run_id = NEW.id
                  AND checkpoint.phase = 'scoring'
                  AND checkpoint.status = 'committed';
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'project run % requires a committed scoring checkpoint', NEW.id;
                END IF;
            END IF;

            IF OLD.phase = 'tier_checkpoint' AND NEW.phase = 'deep' THEN
                SELECT checkpoint.* INTO phase_checkpoint
                FROM project_phase_checkpoint checkpoint
                WHERE checkpoint.project_run_id = NEW.id
                  AND checkpoint.phase = 'tier_checkpoint'
                  AND checkpoint.status = 'committed';
                IF NOT FOUND
                   OR phase_checkpoint.payload_json ->> 'checkpoint_status'
                        IS DISTINCT FROM 'resumed'
                   OR phase_checkpoint.payload_json ->> 'decision_action'
                        IS DISTINCT FROM 'approve' THEN
                    RAISE EXCEPTION
                        'project run % requires an approved committed tier checkpoint', NEW.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER project_run_post_seal_phase_sequence "
        "BEFORE UPDATE OF phase ON project_run FOR EACH ROW "
        "WHEN (OLD.phase IS DISTINCT FROM NEW.phase) "
        "EXECUTE FUNCTION discovery_enforce_post_seal_phase_sequence()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS project_run_post_seal_phase_sequence ON project_run")
    op.execute("DROP FUNCTION IF EXISTS discovery_enforce_post_seal_phase_sequence()")
