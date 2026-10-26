"""agent authored discovery: brief, source, thread lock, stop, wake, exclusion (spec 2026-09-30).

Spec: docs/superpowers/specs/archive/2026-09-30-agent-authored-account-discovery-design.md §3–§5, §8.
A run stores the brief the Head of ABM wrote (``brief_json``) and the source it chose; a partial
unique index holds one unreleased discovery per project (the project lock); a run carries its
launching thread, stop request, wake turn and release. A candidate a ``must``/``must_not`` gate
excluded is recorded with the gate that excluded it. Existing runs are released on upgrade: the
lock is for runs launched from now on.

Revision ID: 0a3a88c7e5ed
Revises: 6eb27d45f570
Create Date: 2026-09-30 14:12:35.860751+00:00

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
revision: str = "0a3a88c7e5ed"
down_revision: str | None = "6eb27d45f570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE arv2_discovery_run
            ADD COLUMN source text NOT NULL DEFAULT 'websets',
            ADD COLUMN brief_json jsonb NULL,
            ADD COLUMN launched_thread_id text NULL,
            ADD COLUMN launching_turn_id uuid NULL,
            ADD COLUMN end_reason text NULL,
            ADD COLUMN summary_json jsonb NULL,
            ADD COLUMN stop_requested_at timestamptz NULL,
            ADD COLUMN wake_turn_id uuid NULL,
            ADD COLUMN released_at timestamptz NULL,
            ADD CONSTRAINT arv2_discovery_run_source CHECK (source IN ('websets', 'search')),
            ADD CONSTRAINT arv2_discovery_run_end_reason CHECK (end_reason IS NULL OR end_reason IN
                ('filled', 'dry', 'round_cap', 'wall_clock', 'stopped', 'failed'))
        """
    )
    op.execute("ALTER TABLE arv2_discovery_run DROP CONSTRAINT arv2_discovery_run_status")
    op.execute(
        "ALTER TABLE arv2_discovery_run ADD CONSTRAINT arv2_discovery_run_status CHECK (status IN "
        "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended', 'stopped'))"
    )
    # Every run that already exists is released: the lock is for runs launched from now on.
    op.execute("UPDATE arv2_discovery_run SET released_at = COALESCE(finished_at, now())")
    op.execute(
        "CREATE UNIQUE INDEX arv2_discovery_run_project_active ON arv2_discovery_run "
        "(workspace_id, project_id) WHERE released_at IS NULL"
    )
    op.execute(
        "CREATE INDEX arv2_discovery_run_thread_active ON arv2_discovery_run "
        "(workspace_id, launched_thread_id) WHERE released_at IS NULL"
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            ADD COLUMN excluded_by_gate text NULL,
            DROP CONSTRAINT arv2_discovery_candidate_disposition,
            ADD CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN
                ('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before',
                 'excluded')),
            ADD CONSTRAINT arv2_discovery_candidate_excluded_gate
                CHECK ((disposition = 'excluded') = (excluded_by_gate IS NOT NULL))
        """
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_search
            ADD COLUMN source text NOT NULL DEFAULT 'websets',
            DROP CONSTRAINT arv2_discovery_search_kind,
            ADD CONSTRAINT arv2_discovery_search_kind
                CHECK (kind IN ('strict', 'strict_topup', 'relaxed', 'round')),
            DROP CONSTRAINT arv2_discovery_search_ordinal,
            ADD CONSTRAINT arv2_discovery_search_ordinal CHECK (ordinal BETWEEN 1 AND 16),
            ADD CONSTRAINT arv2_discovery_search_source CHECK (source IN ('websets', 'search'))
        """
    )
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN
                    ('design_leg_redelivery', 'design_leg_first_turn', 'discovery_finished'))
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM agent_turn_submission WHERE derivation = 'discovery_finished'")
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN
                    ('design_leg_redelivery', 'design_leg_first_turn'))
        """
    )
    op.execute("DELETE FROM arv2_discovery_search WHERE kind = 'round' OR ordinal > 3")
    op.execute(
        """
        ALTER TABLE arv2_discovery_search
            DROP CONSTRAINT arv2_discovery_search_source,
            DROP CONSTRAINT arv2_discovery_search_ordinal,
            ADD CONSTRAINT arv2_discovery_search_ordinal CHECK (ordinal BETWEEN 1 AND 3),
            DROP CONSTRAINT arv2_discovery_search_kind,
            ADD CONSTRAINT arv2_discovery_search_kind
                CHECK (kind IN ('strict', 'strict_topup', 'relaxed')),
            DROP COLUMN source
        """
    )
    op.execute("DELETE FROM arv2_discovery_candidate WHERE disposition = 'excluded'")
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            DROP CONSTRAINT arv2_discovery_candidate_excluded_gate,
            DROP CONSTRAINT arv2_discovery_candidate_disposition,
            ADD CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN
                ('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before')),
            DROP COLUMN excluded_by_gate
        """
    )
    op.execute("DROP INDEX arv2_discovery_run_thread_active")
    op.execute("DROP INDEX arv2_discovery_run_project_active")
    op.execute("UPDATE arv2_discovery_run SET status = 'completed' WHERE status = 'stopped'")
    op.execute("ALTER TABLE arv2_discovery_run DROP CONSTRAINT arv2_discovery_run_status")
    op.execute(
        "ALTER TABLE arv2_discovery_run ADD CONSTRAINT arv2_discovery_run_status CHECK (status IN "
        "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended'))"
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_run
            DROP CONSTRAINT arv2_discovery_run_end_reason,
            DROP CONSTRAINT arv2_discovery_run_source,
            DROP COLUMN released_at, DROP COLUMN wake_turn_id, DROP COLUMN stop_requested_at,
            DROP COLUMN summary_json, DROP COLUMN end_reason, DROP COLUMN launching_turn_id,
            DROP COLUMN launched_thread_id, DROP COLUMN brief_json, DROP COLUMN source
        """
    )
