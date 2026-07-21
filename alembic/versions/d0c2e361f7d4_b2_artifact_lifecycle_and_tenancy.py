"""B2 — artifact lifecycle bookkeeping + structural snapshot tenancy (review findings 1–4)

Revision ID: d0c2e361f7d4
Revises: b2df6d050fc5
Create Date: 2026-07-21

Hardens the B2 evidence-snapshot substrate against the audit's integration blockers:

* **``artifact.purged_at``** — the physical-deletion bookmark for the two-phase DSAR erasure.
  ``erased_at`` becomes the *durable intent* stamped inside the erasing transaction (under the
  artifact row lock, so the refcount check is race-free); the blob delete moves **after commit**
  (``clue_storage.artifacts.purge_erased_artifacts``), which stamps ``purged_at`` once the blob
  is physically gone. A crash between the two phases leaves an ``erased_at IS NOT NULL AND
  purged_at IS NULL`` row the next purge/sweep converges on — external storage is never mutated
  inside a database transaction on the erase path.

* **Structural tenancy** (the "tenancy is structural" invariant, substrate §2). The storage key
  already *encodes* its scope — ``{workspace|public}/{sha256}`` — so two CHECKs make a
  cross-tenant evidence reference unrepresentable rather than caller-discipline:

  - ``artifact``: ``storage_key`` must equal ``COALESCE(workspace_id,'public') || '/' ||
    content_sha256`` — a row can never lie about which workspace its blob belongs to.
  - ``claim``: a claim may cite a ``public/…`` snapshot, or a snapshot in **its own** workspace;
    a tenant-private claim citing another tenant's snapshot is an integrity error. (A
    public-footprint claim — ``workspace_id IS NULL`` — may cite the capture-context workspace's
    snapshot: the sink is workspace-scoped at fetch time while reuse-scope is stamped later, so
    one fetch legitimately backs both public and private claims. Cross-tenant *serving* of such
    a ref is the presign policy gate's job, PB-B2 follow-up 4.)

Hand-written and reversible (up → down → up via ``make db-smoke``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0c2e361f7d4"
down_revision: str | None = "b2df6d050fc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- two-phase erasure bookkeeping --------------------------------------
    op.execute("ALTER TABLE artifact ADD COLUMN purged_at timestamptz")
    op.execute(
        "COMMENT ON COLUMN artifact.purged_at IS 'When the blob was physically deleted from "
        "storage (phase 2 of DSAR erasure). erased_at IS NOT NULL AND purged_at IS NULL = "
        "durable intent awaiting purge (crash-recoverable via purge_erased_artifacts).'"
    )
    # The purge scan: erased-but-not-yet-purged rows only (stays cheap as erased rows accumulate).
    op.execute(
        "CREATE INDEX artifact_erased_unpurged ON artifact (storage_key) "
        "WHERE erased_at IS NOT NULL AND purged_at IS NULL"
    )

    # --- structural tenancy --------------------------------------------------
    # The key encodes its scope; the row may never contradict it.
    op.execute(
        "ALTER TABLE artifact ADD CONSTRAINT artifact_key_encodes_scope CHECK "
        "(storage_key = COALESCE(workspace_id, 'public') || '/' || content_sha256)"
    )
    # A claim's evidence ref stays inside its own tenancy: public snapshots are citable by
    # anyone; a workspace-scoped snapshot only by claims of that workspace (or by a
    # public-footprint claim born of the same capture — see the module docstring).
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_artifact_scope_compatible CHECK "
        "(artifact_key IS NULL OR workspace_id IS NULL "
        "OR split_part(artifact_key, '/', 1) IN ('public', workspace_id))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_artifact_scope_compatible")
    op.execute("ALTER TABLE artifact DROP CONSTRAINT IF EXISTS artifact_key_encodes_scope")
    op.execute("DROP INDEX IF EXISTS artifact_erased_unpurged")
    op.execute("ALTER TABLE artifact DROP COLUMN IF EXISTS purged_at")
