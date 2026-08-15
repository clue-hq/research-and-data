"""bind and redact agent gate snapshots

Revision ID: df332fd7904c
Revises: adaadcfaa9e8
Create Date: 2026-08-15 04:23:34.745773+00:00

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
revision: str = "df332fd7904c"
down_revision: str | None = "adaadcfaa9e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A gate snapshot is a durable exact-value copy, not merely a body-free receipt. Bind each
    # snapshot to every subject it contains without inspecting JSON during DSAR.
    op.execute(
        """
        CREATE TABLE agent_gate_subject (
            workspace_id      text NOT NULL,
            gate_id           uuid NOT NULL,
            subject_entity_id uuid NOT NULL,
            binding_kind      text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_gate_subject_pk PRIMARY KEY (
                workspace_id, gate_id, subject_entity_id
            ),
            CONSTRAINT agent_gate_subject_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT agent_gate_subject_gate_fk
                FOREIGN KEY (gate_id, workspace_id)
                REFERENCES agent_gate (gate_id, workspace_id),
            CONSTRAINT agent_gate_subject_kind_nonempty CHECK (
                length(btrim(binding_kind)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_gate_subject_lookup "
        "ON agent_gate_subject (workspace_id, subject_entity_id, gate_id)"
    )
    op.execute(
        "CREATE TRIGGER agent_gate_subject_append_only "
        "BEFORE UPDATE OR DELETE ON agent_gate_subject "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    op.execute("ALTER TABLE agent_gate ADD COLUMN snapshot_erased_at timestamptz")
    op.execute("ALTER TABLE agent_gate ADD COLUMN snapshot_erasure_reason text")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_snapshot_erasure_pair CHECK ("
        "(snapshot_erased_at IS NULL AND snapshot_erasure_reason IS NULL) OR "
        "(snapshot_erased_at IS NOT NULL AND length(btrim(snapshot_erasure_reason)) > 0 "
        "AND subject_snapshot='{}'::jsonb))"
    )

    # Receipts remain immutable except for the one privacy transition: an exact snapshot may be
    # replaced once by the empty object while its identity/hash/version and an erasure marker stay.
    # Comparing the remaining JSON form prevents privacy from becoming a general update escape.
    op.execute("DROP TRIGGER agent_gate_append_only ON agent_gate")
    op.execute(
        """
        CREATE FUNCTION agent_gate_reject_except_privacy_redaction() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='UPDATE'
               AND OLD.snapshot_erased_at IS NULL
               AND NEW.snapshot_erased_at IS NOT NULL
               AND NEW.subject_snapshot='{}'::jsonb
               AND NEW.snapshot_erasure_reason IS NOT NULL
               AND length(btrim(NEW.snapshot_erasure_reason)) > 0
               AND (
                    to_jsonb(NEW) - ARRAY[
                        'subject_snapshot', 'snapshot_erased_at', 'snapshot_erasure_reason'
                    ]::text[]
                   ) = (
                    to_jsonb(OLD) - ARRAY[
                        'subject_snapshot', 'snapshot_erased_at', 'snapshot_erasure_reason'
                    ]::text[]
                   )
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION USING
                ERRCODE='55000',
                MESSAGE=TG_TABLE_NAME || ' is append-only except for privacy redaction';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER agent_gate_append_only BEFORE UPDATE OR DELETE ON agent_gate "
        "FOR EACH ROW EXECUTE FUNCTION agent_gate_reject_except_privacy_redaction()"
    )

    # Defense in depth: a redacted question cannot be answered through direct SQL either.
    op.execute(
        """
        CREATE FUNCTION agent_gate_answer_reject_erased_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM agent_gate g
                WHERE g.gate_id=NEW.gate_id AND g.workspace_id=NEW.workspace_id
                  AND g.snapshot_erased_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE='55000',
                    MESSAGE='an erased gate snapshot cannot be answered';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER agent_gate_answer_snapshot_available "
        "BEFORE INSERT ON agent_gate_answer FOR EACH ROW "
        "EXECUTE FUNCTION agent_gate_answer_reject_erased_snapshot()"
    )

    op.execute("ALTER TABLE agent_privacy_event DROP CONSTRAINT agent_privacy_event_action")
    op.execute(
        "ALTER TABLE agent_privacy_event ADD CONSTRAINT agent_privacy_event_action CHECK ("
        "action IN ('artifact_tombstoned', 'workspace_purged', 'gate_snapshot_redacted'))"
    )


def downgrade() -> None:
    # Privacy erasure is intentionally irreversible. A clean smoke database has no redactions and
    # downgrades normally; a populated database must not pretend it can reconstruct erased bytes.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM agent_gate WHERE snapshot_erased_at IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot downgrade after an agent gate snapshot was privacy-erased';
            END IF;
        END;
        $$
        """
    )
    op.execute("ALTER TABLE agent_privacy_event DROP CONSTRAINT agent_privacy_event_action")
    op.execute(
        "ALTER TABLE agent_privacy_event ADD CONSTRAINT agent_privacy_event_action CHECK ("
        "action IN ('artifact_tombstoned', 'workspace_purged'))"
    )
    op.execute("DROP TRIGGER IF EXISTS agent_gate_answer_snapshot_available ON agent_gate_answer")
    op.execute("DROP FUNCTION IF EXISTS agent_gate_answer_reject_erased_snapshot()")
    op.execute("DROP TRIGGER IF EXISTS agent_gate_append_only ON agent_gate")
    op.execute("DROP FUNCTION IF EXISTS agent_gate_reject_except_privacy_redaction()")
    op.execute(
        "CREATE TRIGGER agent_gate_append_only BEFORE UPDATE OR DELETE ON agent_gate "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_snapshot_erasure_pair")
    op.execute("ALTER TABLE agent_gate DROP COLUMN snapshot_erasure_reason")
    op.execute("ALTER TABLE agent_gate DROP COLUMN snapshot_erased_at")
    op.execute("DROP TRIGGER IF EXISTS agent_gate_subject_append_only ON agent_gate_subject")
    op.execute("DROP INDEX IF EXISTS agent_gate_subject_lookup")
    op.execute("DROP TABLE IF EXISTS agent_gate_subject")
