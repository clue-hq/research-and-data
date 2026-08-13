"""P3.1 — design leg substrate + agent-role vocabulary (PD-part3 §3, deltas 1–5).

One coordinated migration, per the C8 §8 precedent for role-vocabulary changes:

- Widens the three agent-role CHECKs (``agent_turn_role``, ``agent_plan_role``,
  ``agent_delegation_roles``) to admit ``'design'`` — the platform-facing role of the
  composite design deepagent (PD-part3 D2: one role, the trio stays internal).
- Creates ``design_leg`` — the durable HITL carrier (PD-part3 D1: the leg row IS the
  "interrupted graph"; routing = "open leg on thread gets the message") — with the
  at-most-one-open-leg-per-thread partial unique index (D4's invariant), and the
  append-only ``design_leg_exit_journal`` (exit decisions survive reopens).
- Links ``design_agent_run`` to its leg and platform execution (nullable — legacy runs
  and standalone-editor runs legitimately have neither; same stamping pattern as B3).
- Widens ``agent_turn_submission_context_ref``'s ``object_type`` CHECK to admit
  ``'design_document'`` so canvas selections can ride ``focus_refs`` (master plan §2.4).
- Adds ``agent_turn_submission.previous_turn_outcome`` — the platform home for the
  design turn contract's one-clarification-round echo (design-side vocabulary:
  ``'clarification_requested'`` is the only value with routing meaning).

Downgrade restores every prior shape and FAILS LOUDLY (constraint re-add) if
``'design'`` rows or design legs already exist — deliberate, per house convention.
"""

from alembic import op

revision = "549de68ae3b9"
down_revision = "0bb98da7b5bb"
branch_labels = None
depends_on = None

_ROLE_CHECKS = (
    # (table, constraint, column expression rebuilt on upgrade/downgrade)
    ("agent_turn", "agent_turn_role", "role"),
    ("agent_plan", "agent_plan_role", "role"),
)

_OLD_ROLES = "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research')"
_NEW_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design')"
)


def upgrade() -> None:
    # -- 1. role vocabulary -----------------------------------------------------------
    for table, constraint, column in _ROLE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({column} IN {_NEW_ROLES})"
        )
    op.execute("ALTER TABLE agent_delegation DROP CONSTRAINT agent_delegation_roles")
    op.execute(
        "ALTER TABLE agent_delegation ADD CONSTRAINT agent_delegation_roles CHECK ("
        f"    parent_role IN {_NEW_ROLES}"
        f"    AND child_role IN {_NEW_ROLES}"
        "    AND parent_role <> child_role"
        ")"
    )

    # -- 2. design_leg + exit journal -------------------------------------------------
    op.execute(
        """
        CREATE TABLE design_leg (
            id                     uuid NOT NULL,
            workspace_id           text NOT NULL,
            thread_id              text NOT NULL,
            parent_execution_id    uuid NOT NULL,
            opened_by_turn_id      uuid,
            state                  text NOT NULL DEFAULT 'open_awaiting_user',
            bundle_artifact_ref    text,
            document_id            text,
            document_version_guard integer,
            brand_kit_id           text,
            brand_kit_version      integer,
            close_reason           text,
            closed_by_run_id       text,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_leg_pkey PRIMARY KEY (id),
            CONSTRAINT design_leg_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT design_leg_state CHECK (
                state IN ('open_awaiting_user', 'running', 'closed')
            ),
            CONSTRAINT design_leg_close_reason CHECK (
                close_reason IS NULL
                OR close_reason IN ('locked', 'out_of_scope', 'abandoned')
            ),
            CONSTRAINT design_leg_closed_shape CHECK (
                (state = 'closed') = (close_reason IS NOT NULL)
            ),
            CONSTRAINT design_leg_brand_pin_shape CHECK (
                (brand_kit_id IS NULL) = (brand_kit_version IS NULL)
            ),
            CONSTRAINT design_leg_version_guard_shape CHECK (
                document_version_guard IS NULL OR document_id IS NOT NULL
            ),
            CONSTRAINT design_leg_parent_execution_fk
                FOREIGN KEY (parent_execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT design_leg_thread_fk
                FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id)
        )
        """
    )
    # D1/D4: the routing rule's lookup key — at most one non-closed leg per thread.
    op.execute(
        """
        CREATE UNIQUE INDEX design_leg_one_open_per_thread
            ON design_leg (workspace_id, thread_id)
            WHERE state <> 'closed'
        """
    )
    op.execute("CREATE INDEX design_leg_thread_idx ON design_leg (workspace_id, thread_id)")

    op.execute(
        """
        CREATE TABLE design_leg_exit_journal (
            id                       uuid NOT NULL,
            leg_id                   uuid NOT NULL,
            workspace_id             text NOT NULL,
            reason                   text NOT NULL,
            summary_refs             jsonb NOT NULL,
            pending_user_message_ref text,
            decided_by_run_id        text,
            created_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_leg_exit_journal_pkey PRIMARY KEY (id),
            CONSTRAINT design_leg_exit_journal_leg_fk
                FOREIGN KEY (leg_id, workspace_id)
                REFERENCES design_leg (id, workspace_id),
            CONSTRAINT design_leg_exit_journal_reason CHECK (
                reason IN ('locked', 'out_of_scope', 'abandoned')
            ),
            CONSTRAINT design_leg_exit_journal_oos_message CHECK (
                reason <> 'out_of_scope' OR pending_user_message_ref IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX design_leg_exit_journal_leg_idx "
        "ON design_leg_exit_journal (leg_id, workspace_id)"
    )
    # Reuse the C5.1 append-only guard function (generic over TG_TABLE_NAME).
    op.execute(
        "CREATE TRIGGER design_leg_exit_journal_append_only "
        "BEFORE UPDATE OR DELETE ON design_leg_exit_journal "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    # -- 3. design_agent_run linkage --------------------------------------------------
    op.execute("ALTER TABLE design_agent_run ADD COLUMN leg_id uuid")
    op.execute("ALTER TABLE design_agent_run ADD COLUMN execution_id uuid")
    op.execute(
        "ALTER TABLE design_agent_run ADD CONSTRAINT design_agent_run_leg_fk "
        "FOREIGN KEY (leg_id, workspace_id) REFERENCES design_leg (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE design_agent_run ADD CONSTRAINT design_agent_run_execution_fk "
        "FOREIGN KEY (execution_id, workspace_id) REFERENCES execution (id, workspace_id)"
    )

    # -- 4. focus_refs vocabulary -----------------------------------------------------
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        "CHECK (object_type IN ('account', 'contact', 'design_document'))"
    )

    # -- 5. previous_turn_outcome -----------------------------------------------------
    op.execute(
        "ALTER TABLE agent_turn_submission ADD COLUMN previous_turn_outcome text"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission "
        "ADD CONSTRAINT agent_turn_submission_previous_turn_outcome "
        "CHECK (previous_turn_outcome IS NULL "
        "       OR previous_turn_outcome IN ('clarification_requested'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_turn_submission "
        "DROP CONSTRAINT agent_turn_submission_previous_turn_outcome"
    )
    op.execute("ALTER TABLE agent_turn_submission DROP COLUMN previous_turn_outcome")

    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "DROP CONSTRAINT agent_turn_submission_context_ref_type"
    )
    op.execute(
        "ALTER TABLE agent_turn_submission_context_ref "
        "ADD CONSTRAINT agent_turn_submission_context_ref_type "
        "CHECK (object_type IN ('account', 'contact'))"
    )

    op.execute("ALTER TABLE design_agent_run DROP CONSTRAINT design_agent_run_execution_fk")
    op.execute("ALTER TABLE design_agent_run DROP CONSTRAINT design_agent_run_leg_fk")
    op.execute("ALTER TABLE design_agent_run DROP COLUMN execution_id")
    op.execute("ALTER TABLE design_agent_run DROP COLUMN leg_id")

    op.execute("DROP TRIGGER design_leg_exit_journal_append_only ON design_leg_exit_journal")
    op.execute("DROP TABLE design_leg_exit_journal")
    op.execute("DROP TABLE design_leg")

    op.execute("ALTER TABLE agent_delegation DROP CONSTRAINT agent_delegation_roles")
    op.execute(
        "ALTER TABLE agent_delegation ADD CONSTRAINT agent_delegation_roles CHECK ("
        f"    parent_role IN {_OLD_ROLES}"
        f"    AND child_role IN {_OLD_ROLES}"
        "    AND parent_role <> child_role"
        ")"
    )
    for table, constraint, column in reversed(_ROLE_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({column} IN {_OLD_ROLES})"
        )
