"""pre_spend_policy global-NULL slot NULLS NOT DISTINCT (B4 slice 1)

Revision ID: 86b9c791ae12
Revises: 814a272f79a5
Create Date: 2026-07-22 05:55:13.970187+00:00

Closes CLAUDE.md ``[M9.1×M0.4]``: the M9.1 ``pre_spend_policy_scope_version`` unique index
(``8aefd82b6d59``) is a plain ``UNIQUE (workspace_id, icp_version, version)`` — and Postgres treats
NULLs as distinct without ``NULLS NOT DISTINCT``, so the **global default** slot (``workspace_id IS
NULL`` / ``icp_version IS NULL``) admits *duplicate* same-version rows, which the loader
(``load_pre_spend_policy``, ``ORDER BY version DESC``) could then resolve non-deterministically.
M9.3 already fixed its own copy (``judge_policy_scope_version`` uses ``NULLS NOT DISTINCT``; loader
tie-breaks on ``created_at``/``policy_id``); this migration harmonises M9.1.

Drop + recreate the index with ``NULLS NOT DISTINCT`` (mirrors migration 0009's ``source_profile``
slots), so a duplicate global-default row is now a write-time IntegrityError. The loader gains the
matching ``created_at DESC, policy_id DESC`` tie-break (a code change) so any pre-existing/racing
duplicate still resolves deterministically.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
- Historical migration files stay byte-identical; this migration alters the *live* index only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86b9c791ae12"
down_revision: str | None = "814a272f79a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Make the migration total: dedup any pre-existing duplicate rows in a scope slot BEFORE the
    # NULLS NOT DISTINCT unique index is created (otherwise CREATE UNIQUE INDEX would fail on a DB
    # that already carries duplicate global-default rows). Keep exactly the row the loader would
    # resolve to — its ORDER BY tie-break is version DESC, then created_at DESC, then policy_id DESC
    # — per (workspace_id-or-null, icp_version-or-null, version) slot; delete the rest. NULLs are
    # grouped with COALESCE so the global-default slot (both keys NULL) collapses to one group.
    op.execute(
        """
        DELETE FROM pre_spend_policy p
        USING (
            SELECT policy_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(workspace_id, ''), COALESCE(icp_version, -1), version
                       ORDER BY created_at DESC, policy_id DESC
                   ) AS rn
            FROM pre_spend_policy
        ) ranked
        WHERE p.policy_id = ranked.policy_id AND ranked.rn > 1
        """
    )
    # Recreate the scope-uniqueness index with NULLS NOT DISTINCT so the global default slot
    # (workspace_id IS NULL, icp_version IS NULL) is a single row, not an unbounded set of
    # same-scope duplicates (mirror of migration 0009's source_profile slots).
    op.execute("DROP INDEX IF EXISTS pre_spend_policy_scope_version")
    op.execute(
        "CREATE UNIQUE INDEX pre_spend_policy_scope_version ON pre_spend_policy "
        "(workspace_id, icp_version, version) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    # Back to the plain unique index (NULLs distinct) — the M9.1 shape.
    op.execute("DROP INDEX IF EXISTS pre_spend_policy_scope_version")
    op.execute(
        "CREATE UNIQUE INDEX pre_spend_policy_scope_version ON pre_spend_policy "
        "(workspace_id, icp_version, version)"
    )
