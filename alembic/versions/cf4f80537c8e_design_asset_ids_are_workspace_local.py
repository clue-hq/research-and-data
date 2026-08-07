"""design asset and snapshot ids are workspace local (part2 D2.3a)

Revision ID: cf4f80537c8e
Revises: 7a9881f9717a
Create Date: 2026-08-08

Part II D2.3 follow-up to the D1c schema, surfaced by the asset-domain port: **design asset ids
are content-derived**, so a GLOBAL ``design_asset`` primary key is the same tenancy wart
``7a9881f9717a`` removed everywhere else. The ingestion path mints
``asset_ing_<sha256(bytes)[:16]}`` (``lumen_ingestion/capture/uploads.py``, ``capture/pdf.py``,
``capture/evidence_builder.py``) and the font library mints
``asset_font_lib_<slug>_w<weight>_<digest[:12]>`` — two workspaces ingesting the same logo or
font face derive the SAME asset id, so under a global PK one tenant's first upload would block
(or, through an upsert, silently overwrite) every other tenant's. Scene-carried and
fixture-supplied ids are client-suppliable on the same grounds.

Same medicine, same safety argument as ``7a9881f9717a``: the PK gains ``workspace_id``; nothing
references the standalone key — ``design_asset_description``'s FK already targets the surviving
composite anchor ``design_asset_workspace_anchor (asset_id, workspace_id)``. The 1:1 child's own
PK is re-keyed with it (a global child PK would re-introduce the collision one table down).

**``design_snapshot`` joins them (D2.3b evidence).** Snapshot ids are *client-suppliable*, not
server-minted: ``POST /documents/{id}/snapshots`` takes the id straight from the request body
(the design API's own tests post literal ids such as ``snapshot_id="snap_before_edit"``, and the
template-finalize flow pins a caller-chosen source snapshot). A global ``design_snapshot``
primary key therefore carries the exact squatting flaw ``7a9881f9717a`` removed for documents
and template revisions: one tenant posting ``snap_before_edit`` would deny that id to every
other tenant (a cross-workspace existence leak by 409). Same medicine again — the PK gains
``workspace_id``; nothing references the standalone key, because
``design_template_revision_snapshot_fk`` already targets the surviving composite anchor
``design_snapshot_workspace_anchor (snapshot_id, workspace_id)``.

Hand-written and reversible: ``downgrade()`` restores the global keys (a downgrade with
cross-workspace duplicate ids fails naturally on the PK rebuild — the honest outcome).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf4f80537c8e"
down_revision: str | None = "7a9881f9717a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_asset_description
            DROP CONSTRAINT design_asset_description_pkey,
            ADD CONSTRAINT design_asset_description_pkey PRIMARY KEY (asset_id, workspace_id)
        """
    )
    op.execute(
        """
        ALTER TABLE design_asset
            DROP CONSTRAINT design_asset_pkey,
            ADD CONSTRAINT design_asset_pkey PRIMARY KEY (asset_id, workspace_id)
        """
    )
    op.execute(
        """
        ALTER TABLE design_snapshot
            DROP CONSTRAINT design_snapshot_pkey,
            ADD CONSTRAINT design_snapshot_pkey PRIMARY KEY (snapshot_id, workspace_id)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_snapshot
            DROP CONSTRAINT design_snapshot_pkey,
            ADD CONSTRAINT design_snapshot_pkey PRIMARY KEY (snapshot_id)
        """
    )
    op.execute(
        """
        ALTER TABLE design_asset
            DROP CONSTRAINT design_asset_pkey,
            ADD CONSTRAINT design_asset_pkey PRIMARY KEY (asset_id)
        """
    )
    op.execute(
        """
        ALTER TABLE design_asset_description
            DROP CONSTRAINT design_asset_description_pkey,
            ADD CONSTRAINT design_asset_description_pkey PRIMARY KEY (asset_id)
        """
    )
