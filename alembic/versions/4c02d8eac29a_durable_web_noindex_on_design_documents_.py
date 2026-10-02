"""durable web noindex on design documents (clone-fidelity F4.3, ruling R-F1)

Revision ID: 4c02d8eac29a
Revises: b2329bc1ee27
Create Date: 2026-08-29 00:27:50.170913+00:00

FOUNDER RULING R-F1 (2026-08-29): ``noindex`` is stored PERMANENTLY on every ABM page and
applied on EVERY republish, whichever route publishes it; removing it requires an EXPLICIT
action. Task 25 shipped it as a publish-time ARGUMENT, so a plain
``POST /documents/{id}/web/publish`` — which carries no such field — silently re-indexed an
account page. A property of the page cannot live in one caller's request body; it lives here.

One column, ``design_document.web_noindex boolean NOT NULL DEFAULT false``:

* ``NOT NULL DEFAULT false`` so every existing row is born un-stamped and an ordinary document's
  publish is byte-identical to what it produced before this migration. The durable flag can only
  make a page *less* indexed, and only when something deliberately stamped it.
* Named ``web_noindex`` rather than ``noindex``: ``design_document`` holds both scene and web
  documents, and this is meaningless for a scene. The prefix says which half of the table it is
  about (the ``doc_kind`` discriminator's own vocabulary).
* NOT a CHECK-constrained pair with ``doc_kind``. A scene document simply never carries it, and
  a constraint would have to be dropped and re-added the day a scene gains a publish surface.

Hand-written and reversible: ``downgrade()`` drops the column (CI runs up -> down -> up). No
data migration is owed — the ABM batch is the stamp's first writer, and it stamps forward, on
the documents it derives from this revision on.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c02d8eac29a"
down_revision: str | None = "b2329bc1ee27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE design_document ADD COLUMN web_noindex boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE design_document DROP COLUMN web_noindex")
