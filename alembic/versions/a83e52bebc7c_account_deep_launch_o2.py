"""account deep launch o2

Revision ID: a83e52bebc7c
Revises: fa28c91abc3c
Create Date: 2026-08-04 13:40:44.948667+00:00

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
revision: str = "a83e52bebc7c"
down_revision: str | None = "fa28c91abc3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE account_deep_launch (
            id                            uuid NOT NULL,
            workspace_id                  text NOT NULL,
            project_id                    text NOT NULL,
            project_run_id                uuid NOT NULL,
            directive_id                  uuid NOT NULL,
            directive_version             integer NOT NULL,
            directive_sha256              text NOT NULL,
            request_sha256                text NOT NULL,
            approved_budget_cap_cents     numeric NOT NULL,
            estimated_cost_cents          numeric NOT NULL,
            created_by                    text NOT NULL,
            source_operation_id           uuid NOT NULL,
            source_action_ref              text NOT NULL,
            created_at                    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_deep_launch_pkey PRIMARY KEY (id),
            CONSTRAINT account_deep_launch_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT account_deep_launch_directive_pin_fk
                FOREIGN KEY (directive_id, directive_version, directive_sha256)
                REFERENCES account_research_directive
                    (directive_id, version, canonical_json_sha256),
            CONSTRAINT account_deep_launch_directive_workspace_fk
                FOREIGN KEY (directive_id, workspace_id)
                REFERENCES account_research_directive (directive_id, workspace_id),
            CONSTRAINT account_deep_launch_one_per_run UNIQUE (project_run_id),
            CONSTRAINT account_deep_launch_operation_unique
                UNIQUE (workspace_id, source_operation_id),
            CONSTRAINT account_deep_launch_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT account_deep_launch_directive_anchor
                UNIQUE (id, workspace_id, directive_id),
            CONSTRAINT account_deep_launch_directive_positive CHECK (directive_version >= 1),
            CONSTRAINT account_deep_launch_request_sha256
                CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT account_deep_launch_directive_sha256
                CHECK (directive_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT account_deep_launch_budget_nonnegative
                CHECK (approved_budget_cap_cents >= 0),
            CONSTRAINT account_deep_launch_estimate_nonnegative
                CHECK (estimated_cost_cents >= 0),
            CONSTRAINT account_deep_launch_text_shape CHECK (
                length(btrim(created_by)) > 0 AND length(btrim(source_action_ref)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX account_deep_launch_directive_lookup ON account_deep_launch "
        "(workspace_id, directive_id, project_run_id)"
    )
    op.execute(
        """
        CREATE TABLE account_deep_launch_account (
            launch_id      uuid NOT NULL,
            workspace_id   text NOT NULL,
            directive_id   uuid NOT NULL,
            account_id     uuid NOT NULL,
            directive_ref  text NOT NULL,
            override_id    uuid,
            override_ref   text,
            override_sha256 text,
            created_at     timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_deep_launch_account_pkey PRIMARY KEY (launch_id, account_id),
            CONSTRAINT account_deep_launch_account_launch_fk
                FOREIGN KEY (launch_id, workspace_id, directive_id)
                REFERENCES account_deep_launch (id, workspace_id, directive_id),
            CONSTRAINT account_deep_launch_account_membership_fk
                FOREIGN KEY (directive_id, account_id)
                REFERENCES account_research_directive_account (directive_id, account_id),
            CONSTRAINT account_deep_launch_account_entity_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_deep_launch_account_override_pin_fk
                FOREIGN KEY (override_id, directive_id, account_id, override_sha256)
                REFERENCES account_research_directive_override
                    (override_id, directive_id, account_id, canonical_json_sha256),
            CONSTRAINT account_deep_launch_account_override_shape CHECK (
                (override_id IS NULL AND override_ref IS NULL AND override_sha256 IS NULL)
                OR
                (override_id IS NOT NULL AND override_ref IS NOT NULL
                    AND override_sha256 ~ '^[0-9a-f]{64}$')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX account_deep_launch_account_lookup ON account_deep_launch_account "
        "(workspace_id, directive_id, account_id)"
    )
    op.execute(
        """
        CREATE FUNCTION account_deep_launch_guard() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'account deep launch records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_deep_launch_immutable BEFORE UPDATE OR DELETE "
        "ON account_deep_launch FOR EACH ROW EXECUTE FUNCTION account_deep_launch_guard()"
    )
    op.execute(
        "CREATE TRIGGER account_deep_launch_account_immutable BEFORE UPDATE OR DELETE "
        "ON account_deep_launch_account FOR EACH ROW "
        "EXECUTE FUNCTION account_deep_launch_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER account_deep_launch_account_immutable ON account_deep_launch_account")
    op.execute("DROP TRIGGER account_deep_launch_immutable ON account_deep_launch")
    op.execute("DROP FUNCTION account_deep_launch_guard()")
    op.execute("DROP INDEX account_deep_launch_account_lookup")
    op.execute("DROP TABLE account_deep_launch_account")
    op.execute("DROP INDEX account_deep_launch_directive_lookup")
    op.execute("DROP TABLE account_deep_launch")
