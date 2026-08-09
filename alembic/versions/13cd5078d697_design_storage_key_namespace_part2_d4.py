"""design storage key namespace (part2 D4)

Revision ID: 13cd5078d697
Revises: cf7dd82cf683
Create Date: 2026-08-09

Design bytes move onto ``clue_storage`` in Part-II slice D4, under their own key namespace:
``{workspace_id}/design/{sha256}`` (ruling R-D4-2, implemented by
``clue_design.storage.design_storage_key``). The ``design`` segment is what keeps design blobs
**structurally disjoint** from claim-evidence blobs, whose DSAR erasure decides destruction by
counting the live *claims* citing a key — a design blob has no claim citing it, so sharing the
bare ``{workspace}/{sha}`` namespace would expose it to a zero-refcount purge.

``artifact_key_encodes_scope`` (B2, ``d0c2e361f7d4``) pinned the key to exactly the bare shape,
so it must admit the design shape too. The invariant it exists to enforce is unchanged: the key
still *encodes* its scope — the workspace segment is still the row's workspace and the trailing
segment is still the row's content hash — a row simply may now name which namespace it is in.
Both shapes remain unforgeable; nothing else about the constraint relaxes.

It also adds ``artifact_content_sha256``, a btree index on the digest column: the public design
read is digest-first (R-D4-7 — ``GET /asset-store/{digest}`` resolves by ``content_sha256``, not
by key), and without it every published-page image and ``@font-face`` fetch sequentially scans
``artifact``.

Hand-written and reversible. The downgrade restores the bare-only CHECK, so it fails loud if
design rows are already present (correct: their keys are not representable in the old shape).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "13cd5078d697"
down_revision: str | None = "cf7dd82cf683"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "COALESCE(workspace_id, 'public')"


def upgrade() -> None:
    op.execute("ALTER TABLE artifact DROP CONSTRAINT artifact_key_encodes_scope")
    op.execute(
        "ALTER TABLE artifact ADD CONSTRAINT artifact_key_encodes_scope CHECK ("
        f"storage_key = {_SCOPE} || '/' || content_sha256"
        f" OR storage_key = {_SCOPE} || '/design/' || content_sha256)"
    )
    # The design public read is digest-first (R-D4-7): GET /asset-store/{digest} looks a blob up by
    # content_sha256, never by storage_key, so the unique-key indexes do not serve it. Without this
    # every published-page image and @font-face fetch sequential-scans artifact. Serves any future
    # digest-keyed lookup (dedup-on-write, cross-namespace identity) too.
    op.execute("CREATE INDEX artifact_content_sha256 ON artifact (content_sha256)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS artifact_content_sha256")
    op.execute("ALTER TABLE artifact DROP CONSTRAINT artifact_key_encodes_scope")
    op.execute(
        "ALTER TABLE artifact ADD CONSTRAINT artifact_key_encodes_scope CHECK "
        f"(storage_key = {_SCOPE} || '/' || content_sha256)"
    )
