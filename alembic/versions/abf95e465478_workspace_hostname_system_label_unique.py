"""workspace hostname system label unique

Revision ID: abf95e465478
Revises: 57f948ca3545
Create Date: 2026-10-14 20:23:14.931354+00:00

Review finding S4-1. A workspace's system address is ``<label>.<suffix>``, and until now a label
was unique only together with its domain (the primary key is the whole hostname): ``acme.<old>``
and ``acme.<new>`` could belong to two workspaces. The edge Worker's 301 during and after the
published-pages domain move maps an old address to the new one by label alone, so the second
workspace would receive the first one's published links. This revision makes a system label
unique whatever its domain: ``workspace_hostname_system_label_key``, a unique index on the
hostname's first label over system rows. Labels never contain a dot (``clue_spine.hostnames``:
``label_candidates`` slugifies to ``[a-z0-9-]`` and ``validate_label`` admits only that), so the
first label is the whole label. Custom rows are untouched: they are customer hostnames, matched
exactly.

The upgrade refuses, naming them, when two system rows already share a label: which workspace keeps
it is an operator's decision, never this migration's guess. Resolve them by hand (a label change on
one of them) and re-run.

Reversible: the downgrade drops the index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abf95e465478"
down_revision: str | None = "57f948ca3545"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT split_part(hostname, '.', 1) AS label, "
                "string_agg(hostname || ' (' || workspace_id || ')', ', ' ORDER BY hostname) "
                "AS held_by FROM workspace_hostname WHERE kind = 'system' "
                "GROUP BY 1 HAVING count(*) > 1 ORDER BY 1"
            )
        )
        .all()
    )
    if duplicates:
        listed = "; ".join(f"{row.label!r}: {row.held_by}" for row in duplicates)
        raise RuntimeError(
            "workspace_hostname: system labels must be unique whatever the domain (review "
            f"finding S4-1), but {len(duplicates)} label(s) are held by more than one workspace — "
            f"{listed}. Change the label of all but one workspace per label, then re-run."
        )
    op.execute(
        "CREATE UNIQUE INDEX workspace_hostname_system_label_key "
        "ON workspace_hostname ((split_part(hostname, '.', 1))) WHERE kind = 'system'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX workspace_hostname_system_label_key")
