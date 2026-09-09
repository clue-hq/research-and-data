"""arv2 project icp pin

Revision ID: 71e80c777cf6
Revises: fcb4a7b0b465
Create Date: 2026-09-09 22:36:06.543668+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

ARV2 onboarding **O6**, founder rulings 2026-09-10. A project pins exactly one confirmed ICP
document version, by document id, and the pin is written when a human approves the ICP
confirmation gate. It never moves on its own.

Before this table, "the project's ICP" was recomputed from whatever the brand happened to hold
now — the newest ``confirmed`` row for the brand (the person launch), or a scan of the servable
documents for one carrying ``confirmed_for_project_id`` in its front matter (the index card). Both
answers move under a project that never asked them to: a re-synthesis proposal, or *another*
project confirming the same path, would change what an existing project reads and launches with.
A pin is a row, so it cannot.

The table is append-only and sequenced rather than one-row-per-project: switching a project's ICP
is a durable human act with its own receipt (who pinned it, when, against which product
selection), and the history of what a project researched against must survive the switch. **The
current pin is the row with the greatest ``pin_seq``.** Nothing in this slice appends a second row
except a human approving a different document at the gate.

``product_selection_version`` is nullable on purpose: a project may confirm its ICP before it
confirms a product set (the "other order" case), and recording a version nobody chose would be a
fabrication.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71e80c777cf6"
down_revision: str | None = "fcb4a7b0b465"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_icp_pin (
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            pin_seq                   integer NOT NULL,
            brand_id                  text NOT NULL,
            document_id               uuid NOT NULL,
            icp_key                   text NOT NULL,
            artifact_key              text NOT NULL,
            artifact_sha256           text NOT NULL,
            product_selection_version integer,
            pinned_by_user_id         text NOT NULL,
            pinned_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_icp_pin_pkey PRIMARY KEY (project_id, pin_seq),
            -- A pin can never name a project in another workspace — structurally.
            CONSTRAINT project_icp_pin_project_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT project_icp_pin_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            -- The pin is by document id: the exact version a human approved, not a path.
            CONSTRAINT project_icp_pin_document_fk FOREIGN KEY (document_id)
                REFERENCES brand_knowledge_document (document_id),
            CONSTRAINT project_icp_pin_seq_positive CHECK (pin_seq >= 1),
            CONSTRAINT project_icp_pin_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(brand_id)) > 0
                AND length(btrim(icp_key)) > 0
                AND length(btrim(artifact_key)) > 0
                AND length(btrim(pinned_by_user_id)) > 0
            ),
            -- A bare 64-hex sha256, the shape brand_knowledge_document.artifact_sha256 uses, so
            -- a launch can compare the two without a normalization step.
            CONSTRAINT project_icp_pin_artifact_sha256 CHECK (
                artifact_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT project_icp_pin_selection_version_positive CHECK (
                product_selection_version IS NULL OR product_selection_version >= 1
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE project_icp_pin IS 'ARV2 O6: the confirmed ICP document version one "
        "project reads and launches against. Append-only; the current pin is the row with the "
        "greatest pin_seq. A newer version on the same path — a re-synthesis proposal, or another "
        "project confirming it — cannot change what this project pinned.'"
    )
    op.execute(
        "COMMENT ON COLUMN project_icp_pin.product_selection_version IS 'The project product set "
        "confirmed when the ICP was pinned, or NULL when none was confirmed yet (the ICP-first "
        "order). Never a version nobody chose.'"
    )
    op.execute(
        "CREATE INDEX project_icp_pin_workspace_project "
        "ON project_icp_pin (workspace_id, project_id)"
    )
    op.execute(
        "CREATE TRIGGER project_icp_pin_append_only "
        "BEFORE UPDATE OR DELETE ON project_icp_pin "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS project_icp_pin_append_only ON project_icp_pin")
    op.execute("DROP INDEX IF EXISTS project_icp_pin_workspace_project")
    op.execute("DROP TABLE IF EXISTS project_icp_pin")
