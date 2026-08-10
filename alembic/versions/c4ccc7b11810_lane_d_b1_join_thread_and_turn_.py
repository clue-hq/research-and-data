"""lane D B1 join: thread and turn ownership FKs

Revision ID: c4ccc7b11810
Revises: a21c4d290eb7
Create Date: 2026-08-08 13:03:10.559464+00:00

FI Lane D — the B1 join slice (``docs/specs/FI-lane-D-B1-join-implementation-brief.md``). D0's
migration ``fb558870202b`` created the four ownership columns
(``agent_thread.created_by_user_id`` / ``created_via_membership_id``,
``agent_turn.submitted_by_user_id`` / ``submitted_via_membership_id``) with **no** foreign keys,
because Lane B's identity substrate did not exist on that branch. B1 (``9398ae4467e3``) has since
landed ``platform_user`` / ``workspace_membership``, so those four columns become real references
here — the "no external foreign keys, all relationships reference Clue-owned keys" law of
``docs/specs/FI-lane-B-authenticated-principal-contract.md`` §§1.3/3, enforced by the database
instead of by convention.

Two of the four are **composite**, pairing the ownership column with the row's own
``workspace_id`` against ``workspace_membership (membership_id, workspace_id)`` (B1's
``workspace_membership_workspace_anchor``). A membership proves access to *one* workspace, so a
thread or turn in workspace A can no longer cite a membership that lives in workspace B — the same
structural anchor pattern ``workspace_invitation_inviter_ws_fk`` and ``agent_turn_thread_fk``
already use. Composite FKs default to ``MATCH SIMPLE``: a NULL membership column satisfies the
constraint regardless of ``workspace_id``, which is exactly the behaviour the nullable ownership
columns need.

All four columns stay **nullable and unchanged**. A platform-originated thread or turn (the stage-0
trial, an entity-research fleet unit, a specialist delegation) has no human submitter, and Lane B
ruling 8 forbids inventing one; NULL passes a foreign key by definition, so machine rows stay legal
and only *claimed* identities are now checked. ``created_via_membership_id`` remains unwritten in
production until Lane B's B4 carries membership through the ``ToolContext`` seam.

The preflight follows the ``82a80fb80c9e`` precedent: it refuses to migrate a database holding
ownership values that name identities which do not exist, and names the reset path. Nothing is
silently NULLed out — a claimed-but-unresolvable actor is a data defect, and every database on this
branch holds synthetic development data only.

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
revision: str = "c4ccc7b11810"
down_revision: str | None = "a21c4d290eb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- preflight: an unresolvable owner is a data defect, not something to quietly erase -------
    # Deleting or NULLing an orphan would destroy the very audit identity these columns exist to
    # carry, so the migration refuses and names the operator action instead (precedent:
    # 82a80fb80c9e). Each branch is written separately so the message says which column is wrong.
    op.execute(
        """
        DO $$
        DECLARE
            offender text;
        BEGIN
            SELECT 'agent_thread.created_by_user_id' INTO offender
            WHERE EXISTS (
                SELECT 1 FROM agent_thread t
                WHERE t.created_by_user_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM platform_user u WHERE u.user_id = t.created_by_user_id
                  )
            );
            IF offender IS NULL THEN
                SELECT 'agent_thread.created_via_membership_id' INTO offender
                WHERE EXISTS (
                    SELECT 1 FROM agent_thread t
                    WHERE t.created_via_membership_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM workspace_membership m
                          WHERE m.membership_id = t.created_via_membership_id
                            AND m.workspace_id = t.workspace_id
                      )
                );
            END IF;
            IF offender IS NULL THEN
                SELECT 'agent_turn.submitted_by_user_id' INTO offender
                WHERE EXISTS (
                    SELECT 1 FROM agent_turn t
                    WHERE t.submitted_by_user_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM platform_user u WHERE u.user_id = t.submitted_by_user_id
                      )
                );
            END IF;
            IF offender IS NULL THEN
                SELECT 'agent_turn.submitted_via_membership_id' INTO offender
                WHERE EXISTS (
                    SELECT 1 FROM agent_turn t
                    WHERE t.submitted_via_membership_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM workspace_membership m
                          WHERE m.membership_id = t.submitted_via_membership_id
                            AND m.workspace_id = t.workspace_id
                      )
                );
            END IF;
            IF offender IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'migration c4ccc7b11810: ' || offender || ' names an identity with '
                              'no Lane B platform_user / workspace_membership row',
                    HINT = 'Development data only: run make db-fresh && make migrate. Ownership '
                           'values are audit identities and are never rewritten or nulled here.';
            END IF;
        END
        $$;
        """
    )

    # --- the four ownership foreign keys ---------------------------------------------------------
    # VALIDATED (not NOT VALID, unlike D0's grandfathered agent_turn_thread_fk): the preflight above
    # has just proved there is nothing to grandfather, so the constraint is trustworthy for reads
    # as well as writes.
    op.execute(
        """
        ALTER TABLE agent_thread
            ADD CONSTRAINT agent_thread_created_by_user_fk
                FOREIGN KEY (created_by_user_id) REFERENCES platform_user (user_id),
            ADD CONSTRAINT agent_thread_created_via_membership_fk
                FOREIGN KEY (created_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id)
        """
    )
    op.execute(
        """
        ALTER TABLE agent_turn
            ADD CONSTRAINT agent_turn_submitted_by_user_fk
                FOREIGN KEY (submitted_by_user_id) REFERENCES platform_user (user_id),
            ADD CONSTRAINT agent_turn_submitted_via_membership_fk
                FOREIGN KEY (submitted_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn
            DROP CONSTRAINT IF EXISTS agent_turn_submitted_via_membership_fk,
            DROP CONSTRAINT IF EXISTS agent_turn_submitted_by_user_fk
        """
    )
    op.execute(
        """
        ALTER TABLE agent_thread
            DROP CONSTRAINT IF EXISTS agent_thread_created_via_membership_fk,
            DROP CONSTRAINT IF EXISTS agent_thread_created_by_user_fk
        """
    )
