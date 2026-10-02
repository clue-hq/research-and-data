"""project documents are free-flowing

Revision ID: 639d081ad799
Revises: 5e78522ddf48
Create Date: 2026-09-14 00:00:00.000000+00:00

Founder ruling 2026-09-14: the agent may write any document it judges useful under ``project/``,
and the platform records and tracks it rather than gatekeeping by shape. Two closed CHECKs stood in
the way, because both encoded a taxonomy the writer no longer has:

* ``brand_knowledge_document_kind`` admitted eight kinds. A document's kind is now its own word for
  itself, read off the front matter the model wrote (``document`` when it says nothing), so the
  list could only ever be a refusal of a word nobody downstream reads.
* ``brand_knowledge_document_folder`` admitted six folders. A folder is the first segment of the
  document's path, and the path is the one the agent typed — ``notes/competitive-brief.md`` is a
  document, not an error.

What stays is every structural guarantee: ``path LIKE folder || '/%'`` (the folder is still derived
from the path and still agrees with it), the served-bytes CHECK, the status vocabulary, the scoped
unique index. Only the two taxonomies go.

The downgrade re-adds both CHECKs exactly as they were. It will fail loudly on a database that has
since stored a document outside the old vocabulary — which is correct: those rows are real
documents somebody wrote, and silently deleting or renaming them to satisfy an old constraint would
be worse than refusing to go back.

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
revision: str = "639d081ad799"
down_revision: str | None = "5e78522ddf48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOLDERS = "('company', 'product', 'audience', 'proof', 'design', 'project')"
_KINDS = (
    "('company-overview', 'product-catalog', 'product-research', 'customer-reviews', "
    "'icp-definition', 'audience-persona', 'design-brief', 'project-plan')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_kind")
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT brand_knowledge_document_folder"
    )
    op.execute(
        "COMMENT ON COLUMN brand_knowledge_document.kind IS 'What the document calls itself, from "
        "its own front matter; ''document'' when it says nothing. Not a closed vocabulary since "
        "2026-09-14 — the platform records what was written, it does not gatekeep by shape.'"
    )
    op.execute(
        "COMMENT ON COLUMN brand_knowledge_document.folder IS 'The first segment of the "
        "document''s path, which the path_in_folder CHECK still enforces. Not a closed vocabulary "
        "since 2026-09-14.'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN brand_knowledge_document.kind IS NULL")
    op.execute("COMMENT ON COLUMN brand_knowledge_document.folder IS NULL")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_folder "
        f"CHECK (folder IN {_FOLDERS})"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT brand_knowledge_document_kind "
        f"CHECK (kind IN {_KINDS})"
    )
