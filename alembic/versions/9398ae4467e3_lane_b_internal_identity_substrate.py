"""Lane B B1: Clue-owned users, auth identities, and workspace memberships.

Revision ID: 9398ae4467e3
Revises: 870fe4f2af87
Create Date: 2026-08-08 11:31:42.704559+00:00

Implements ``docs/specs/FI-lane-B-authenticated-principal-contract.md`` §3 and B1. External
authentication providers prove a session only. ``platform_user`` and ``workspace_membership`` are
the durable actor/authorization spine; the opaque external subject is confined to
``auth_identity`` as a unique lookup attribute. No provider value is a primary key, foreign key,
tenancy key, or authorization key.

``workspace_invitation`` owns provisioning independently of provider organizations. Its raw token
is never stored: only a caller-produced digest reaches this table. The inviter FK is composite with
``workspace_id`` so an invitation cannot be issued under a membership from another workspace.

Hand-written and reversible. Parallel FI migrations are expected to create a second head when the
lane is integrated; the integration branch must join them with ``alembic merge``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9398ae4467e3"
down_revision: str | None = "870fe4f2af87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_user (
            user_id       text        NOT NULL,
            display_name  text,
            status        text        NOT NULL DEFAULT 'active',
            created_at    timestamptz NOT NULL DEFAULT now(),
            suspended_at  timestamptz,
            disabled_at   timestamptz,

            CONSTRAINT platform_user_pkey PRIMARY KEY (user_id),
            CONSTRAINT platform_user_status_check
                CHECK (status IN ('active','suspended','disabled')),
            CONSTRAINT platform_user_lifecycle_check CHECK (
                (status = 'active' AND suspended_at IS NULL AND disabled_at IS NULL)
                OR (status = 'suspended' AND suspended_at IS NOT NULL AND disabled_at IS NULL)
                OR (status = 'disabled' AND disabled_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform_user IS 'Lane B canonical human identity. Every durable human "
        "actor reference uses user_id; provider subjects and email addresses are never actor ids.'"
    )

    op.execute(
        """
        CREATE TABLE auth_identity (
            auth_identity_id text        NOT NULL,
            user_id          text        NOT NULL,
            provider_key     text        NOT NULL,
            provider_subject text        NOT NULL,
            status           text        NOT NULL DEFAULT 'active',
            linked_at        timestamptz NOT NULL DEFAULT now(),
            revoked_at       timestamptz,

            CONSTRAINT auth_identity_pkey PRIMARY KEY (auth_identity_id),
            CONSTRAINT auth_identity_user_fk FOREIGN KEY (user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT auth_identity_provider_subject_unique
                UNIQUE (provider_key, provider_subject),
            CONSTRAINT auth_identity_provider_key_nonempty
                CHECK (btrim(provider_key) <> ''),
            CONSTRAINT auth_identity_provider_subject_nonempty
                CHECK (btrim(provider_subject) <> ''),
            CONSTRAINT auth_identity_status_check
                CHECK (status IN ('active','unlinked','revoked')),
            CONSTRAINT auth_identity_lifecycle_check CHECK (
                (status IN ('active','unlinked') AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            )
        )
        """
    )
    op.execute("CREATE INDEX auth_identity_by_user ON auth_identity (user_id)")
    op.execute(
        "COMMENT ON TABLE auth_identity IS 'Replaceable provider mapping. provider_subject is an "
        "opaque lookup attribute confined to this table; no domain table may reference it.'"
    )

    op.execute(
        """
        CREATE TABLE workspace_membership (
            membership_id text        NOT NULL,
            workspace_id  text        NOT NULL,
            user_id       text        NOT NULL,
            role_key      text        NOT NULL,
            status        text        NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            activated_at  timestamptz,
            revoked_at    timestamptz,

            CONSTRAINT workspace_membership_pkey PRIMARY KEY (membership_id),
            CONSTRAINT workspace_membership_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_membership_user_fk FOREIGN KEY (user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT workspace_membership_user_once UNIQUE (workspace_id, user_id),
            CONSTRAINT workspace_membership_workspace_anchor
                UNIQUE (membership_id, workspace_id),
            CONSTRAINT workspace_membership_role_check
                CHECK (role_key IN ('owner','admin','operator','viewer')),
            CONSTRAINT workspace_membership_status_check
                CHECK (status IN ('invited','active','suspended','revoked')),
            CONSTRAINT workspace_membership_lifecycle_check CHECK (
                (status = 'invited' AND activated_at IS NULL AND revoked_at IS NULL)
                OR (status IN ('active','suspended') AND activated_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX workspace_membership_by_user ON workspace_membership (user_id, status)"
    )
    op.execute(
        "CREATE INDEX workspace_membership_by_workspace ON workspace_membership "
        "(workspace_id, status)"
    )
    op.execute(
        "COMMENT ON TABLE workspace_membership IS 'Clue-owned human access membership. This is "
        "not FI-2 project_account target-account membership and never reads provider roles.'"
    )

    op.execute(
        """
        CREATE TABLE workspace_invitation (
            invitation_id            text        NOT NULL,
            workspace_id             text        NOT NULL,
            invited_address          text        NOT NULL,
            role_key                 text        NOT NULL,
            status                   text        NOT NULL DEFAULT 'pending',
            token_digest             text        NOT NULL,
            expires_at               timestamptz NOT NULL,
            invited_by_membership_id text        NOT NULL,
            accepted_by_user_id      text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            accepted_at              timestamptz,
            revoked_at               timestamptz,

            CONSTRAINT workspace_invitation_pkey PRIMARY KEY (invitation_id),
            CONSTRAINT workspace_invitation_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_invitation_inviter_ws_fk
                FOREIGN KEY (invited_by_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id),
            CONSTRAINT workspace_invitation_acceptor_fk FOREIGN KEY (accepted_by_user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT workspace_invitation_token_digest_unique UNIQUE (token_digest),
            CONSTRAINT workspace_invitation_address_nonempty
                CHECK (btrim(invited_address) <> ''),
            CONSTRAINT workspace_invitation_token_digest_nonempty
                CHECK (btrim(token_digest) <> ''),
            CONSTRAINT workspace_invitation_role_check
                CHECK (role_key IN ('owner','admin','operator','viewer')),
            CONSTRAINT workspace_invitation_status_check
                CHECK (status IN ('pending','accepted','revoked','expired')),
            CONSTRAINT workspace_invitation_lifecycle_check CHECK (
                (status = 'pending' AND accepted_by_user_id IS NULL
                    AND accepted_at IS NULL AND revoked_at IS NULL)
                OR (status = 'accepted' AND accepted_by_user_id IS NOT NULL
                    AND accepted_at IS NOT NULL AND revoked_at IS NULL)
                OR (status = 'revoked' AND accepted_by_user_id IS NULL
                    AND accepted_at IS NULL AND revoked_at IS NOT NULL)
                OR (status = 'expired' AND accepted_by_user_id IS NULL
                    AND accepted_at IS NULL AND revoked_at IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX workspace_invitation_pending_by_workspace ON workspace_invitation "
        "(workspace_id, expires_at) WHERE status = 'pending'"
    )
    op.execute(
        "COMMENT ON TABLE workspace_invitation IS 'Clue-owned provisioning record. Stores only a "
        "digest of the bearer invitation token; provider organizations grant no workspace access.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_invitation")
    op.execute("DROP TABLE workspace_membership")
    op.execute("DROP TABLE auth_identity")
    op.execute("DROP TABLE platform_user")
