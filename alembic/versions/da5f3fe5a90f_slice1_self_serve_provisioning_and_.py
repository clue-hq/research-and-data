"""FI-4 slice 1: platform_user profile columns + self-serve provisioning record.

Revision ID: da5f3fe5a90f
Revises: 5d7ab295742b
Create Date: 2026-08-11 21:16:52.042799+00:00

Implements FI-4 D-2/D-3 (ratified 2026-08-12):

- ``platform_user`` gains three nullable profile columns — ``first_name``, ``last_name``,
  ``job_role`` — collected by the onboarding profile screen. ``job_role`` is a free-form
  self-described job title ("Founder", "Marketing", …) and is deliberately NOT
  ``workspace_membership.role_key`` (the authorization role); no CHECK constrains its values.
  All three are personal data: ``clue_auth.store.erase_platform_user`` clears them in the same
  change (DSAR completeness), and empty strings are refused at the DB so absence is always NULL.

- ``self_serve_provisioning`` is the durable idempotency record for the D-2 one-shot
  provisioning operation: at most one self-serve-provisioned workspace per auth identity
  (PK on ``auth_identity_id``), and a workspace can be the product of at most one self-serve
  provisioning (UNIQUE on ``workspace_id``). A replayed provision call finds this row and
  returns the exact workspace AND first brand it created (``brand_id`` is recorded, composite
  FK through the brand's workspace anchor) instead of creating another. ``company_website``
  (company data, not personal data) is retained for the slice-2 setup composition to read.

Hand-written and reversible. Downgrade drops the record table and the three columns
(schema-reversible; column data is lost on downgrade, matching repo convention).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da5f3fe5a90f"
down_revision: str | None = "5d7ab295742b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_user
            ADD COLUMN first_name text,
            ADD COLUMN last_name  text,
            ADD COLUMN job_role   text,
            ADD CONSTRAINT platform_user_first_name_nonempty
                CHECK (first_name IS NULL OR btrim(first_name) <> ''),
            ADD CONSTRAINT platform_user_last_name_nonempty
                CHECK (last_name IS NULL OR btrim(last_name) <> ''),
            ADD CONSTRAINT platform_user_job_role_nonempty
                CHECK (job_role IS NULL OR btrim(job_role) <> '')
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform_user.job_role IS 'Self-described job title from onboarding "
        "(free text). This is profile data, never an authorization role; role_key on "
        "workspace_membership is the only authorization role.'"
    )

    op.execute(
        """
        CREATE TABLE self_serve_provisioning (
            auth_identity_id text        NOT NULL,
            workspace_id     text        NOT NULL,
            brand_id         text        NOT NULL,
            company_website  text,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT self_serve_provisioning_pkey PRIMARY KEY (auth_identity_id),
            CONSTRAINT self_serve_provisioning_identity_fk FOREIGN KEY (auth_identity_id)
                REFERENCES auth_identity (auth_identity_id),
            CONSTRAINT self_serve_provisioning_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT self_serve_provisioning_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT self_serve_provisioning_workspace_once UNIQUE (workspace_id),
            CONSTRAINT self_serve_provisioning_website_nonempty
                CHECK (company_website IS NULL OR btrim(company_website) <> '')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE self_serve_provisioning IS 'FI-4 D-2 idempotency record: one "
        "self-serve-provisioned workspace per auth identity. A replayed provision call returns "
        "the workspace recorded here; it never creates a second one.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE self_serve_provisioning")
    op.execute(
        """
        ALTER TABLE platform_user
            DROP CONSTRAINT platform_user_job_role_nonempty,
            DROP CONSTRAINT platform_user_last_name_nonempty,
            DROP CONSTRAINT platform_user_first_name_nonempty,
            DROP COLUMN job_role,
            DROP COLUMN last_name,
            DROP COLUMN first_name
        """
    )
