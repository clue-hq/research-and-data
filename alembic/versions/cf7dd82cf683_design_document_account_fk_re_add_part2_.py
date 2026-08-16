"""design document account fk re-add + workspace-local personalization ids (part2 D2.4)

Revision ID: cf7dd82cf683
Revises: cf4f80537c8e
Create Date: 2026-08-08

Two changes, both required by the D2.4 port of the personalization + web-account domains.

**(1) ``design_document_account_fk`` returns.** Migration ``7a9881f9717a`` DROPPED it because
the staged port left accounts in SQLite (``web_accounts``): a document's ``account_id`` stamp —
written by the web derive path, already on Postgres — could not have satisfied an FK into an
empty ``design_account`` table, so the column kept its SQLite-era advisory semantics for two
slices. D2.4 ports the account domain (``clue_design.accounts`` → ``design_account``), so the
constraint the D1e migration created is re-added verbatim, restoring the ratified semantics: a
derived document points at a REAL same-workspace account, and deleting the account SET-NULLs
the stamp (``ON DELETE SET NULL (account_id)``) rather than leaving a dangling string. The
composite ``(account_id, workspace_id)`` reference is what makes the tenancy structural.

**(2) The personalization ids join the workspace-local namespaces.** ``7a9881f9717a`` re-keyed
every id namespace a client can supply (server-minted-uuid namespaces stayed global); the D1d
personalization tables were created before that ruling and kept single-column PKs. But
``design_binding_set.binding_set_id`` is **client-supplied** (the binding payload carries its
own id), and ``design_instance.instance_id`` / ``design_repair_request.repair_id`` are
**deterministically derived from it** (``inst_<revision>_<binding>`` /
``rep_<revision>_<slot>_<binding>``) — so two tenants authoring the same binding id against the
same (already workspace-local) template revision id collided on the PK, which is precisely the
squatting hazard the ruling names. All three PKs become ``(…, workspace_id)``; the existing
``(id, workspace_id)`` unique anchors that child FKs point at are untouched, so no FK moves.
``design_instance_batch``/``design_web_batch`` ids are server-minted uuids and stay global,
per the same ruling.

Hand-written and reversible: ``downgrade()`` mirrors both halves (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf7dd82cf683"
down_revision: str | None = "cf4f80537c8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, pkey constraint name, workspace-local pkey columns, global pkey column)
_WORKSPACE_LOCAL_IDS = (
    ("design_binding_set", "design_binding_set_pkey", "binding_set_id"),
    ("design_instance", "design_instance_pkey", "instance_id"),
    ("design_repair_request", "design_repair_request_pkey", "repair_id"),
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_document
            ADD CONSTRAINT design_document_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES design_account (account_id, workspace_id)
                ON DELETE SET NULL (account_id)
        """
    )
    for table, pkey, id_column in _WORKSPACE_LOCAL_IDS:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {pkey}, "
            f"ADD CONSTRAINT {pkey} PRIMARY KEY ({id_column}, workspace_id)"
        )


def downgrade() -> None:
    for table, pkey, id_column in reversed(_WORKSPACE_LOCAL_IDS):
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {pkey}, "
            f"ADD CONSTRAINT {pkey} PRIMARY KEY ({id_column})"
        )
    op.execute("ALTER TABLE design_document DROP CONSTRAINT design_document_account_fk")
