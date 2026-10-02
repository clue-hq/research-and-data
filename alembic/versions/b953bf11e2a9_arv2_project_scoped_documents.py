"""arv2 project scoped documents

Revision ID: b953bf11e2a9
Revises: 6c54be5199c8
Create Date: 2026-09-12 12:27:55.063860+00:00

ICP authoring (docs/superpowers/plans/2026-09-12-icp-authoring.md, Task 1): a knowledge document
may now be scoped to one project, and an onboarding run may be a personas-only walk.

Until now every ``brand_knowledge_document`` was brand-level — ``(workspace, brand, path, version)``
was unique — so a project could not own an ICP variant, its personas, or its project plan without
colliding with the brand's copy. Two nullable columns change that: ``project_id`` (composite-FK
anchored to ``project (project_id, workspace_id)``, so a document can never scope itself to another
tenant's project) and ``derived_from_document_id``, the lineage back to the brand document a
project-local variant was cut from. Uniqueness moves with the scope: the brand-scoped UNIQUE
constraint is replaced by a unique index over ``COALESCE(project_id, '')``, so the brand copy and a
project's variant of the same path/version coexist while a second row in the *same* scope is still
refused. The ``project`` folder and the ``project-plan`` kind are admitted alongside.

``onboarding_run`` gains a ``kind``: the existing whole-brand walk is ``'full'`` (the default, so
every row already at rest keeps its meaning) and ``'personas'`` is a narrow run generating personas
for one ICP document. ``onboarding_run_persona_shape`` welds the two halves — a personas run must
name the ICP document it generates for, and a full run must not.

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
revision: str = "b953bf11e2a9"
down_revision: str | None = "6c54be5199c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN project_id text")
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN derived_from_document_id uuid")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_project_fk "
        "FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_derived_fk "
        "FOREIGN KEY (derived_from_document_id) REFERENCES brand_knowledge_document (document_id)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_path_version"
    )
    op.execute(
        "CREATE UNIQUE INDEX brand_knowledge_document_scope_path_version "
        "ON brand_knowledge_document "
        "(workspace_id, brand_id, COALESCE(project_id, ''), path, version)"
    )
    op.execute(
        "CREATE INDEX brand_knowledge_document_project ON brand_knowledge_document "
        "(workspace_id, project_id, path, version DESC) WHERE project_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_folder"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_folder CHECK "
        "(folder IN ('company', 'product', 'audience', 'proof', 'design', 'project'))"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_kind")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_kind CHECK "
        "(kind IN ('company-overview', 'product-catalog', 'product-research', 'customer-reviews', "
        "'icp-definition', 'audience-persona', 'design-brief', 'project-plan'))"
    )
    op.execute(
        "COMMENT ON COLUMN brand_knowledge_document.project_id IS 'NULL = a brand-level document; "
        "set = a document scoped to one project (a project-local ICP variant, its personas, the "
        "project plan). Uniqueness of (path, version) is per scope.'"
    )
    op.execute("ALTER TABLE onboarding_run ADD COLUMN kind text NOT NULL DEFAULT 'full'")
    op.execute("ALTER TABLE onboarding_run ADD COLUMN project_id text")
    op.execute("ALTER TABLE onboarding_run ADD COLUMN persona_icp_document_id uuid")
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_kind CHECK "
        "(kind IN ('full', 'personas'))"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_project_fk "
        "FOREIGN KEY (project_id, workspace_id) REFERENCES project (project_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_persona_icp_fk "
        "FOREIGN KEY (persona_icp_document_id) REFERENCES brand_knowledge_document (document_id)"
    )
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_persona_shape CHECK "
        "((kind = 'personas') = (persona_icp_document_id IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX onboarding_run_persona_open ON onboarding_run "
        "(persona_icp_document_id) WHERE kind = 'personas' AND status IN ('queued', 'running')"
    )


def downgrade() -> None:
    # Reverse order. The old UNIQUE constraint is restored verbatim; project-scoped rows (if any)
    # would violate it, so the downgrade refuses loudly when they exist.
    op.execute("DROP INDEX onboarding_run_persona_open")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_persona_shape")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_persona_icp_fk")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_project_fk")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_kind")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN persona_icp_document_id")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN project_id")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN kind")
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_kind")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_kind CHECK "
        "(kind IN ('company-overview', 'product-catalog', 'product-research', 'customer-reviews', "
        "'icp-definition', 'audience-persona', 'design-brief'))"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_folder"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_folder CHECK "
        "(folder IN ('company', 'product', 'audience', 'proof', 'design'))"
    )
    op.execute("DROP INDEX brand_knowledge_document_project")
    op.execute("DROP INDEX brand_knowledge_document_scope_path_version")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_path_version "
        "UNIQUE (workspace_id, brand_id, path, version)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_derived_fk"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_project_fk"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN derived_from_document_id")
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN project_id")
