"""B2 — the ``artifact`` table + ``claim.artifact_key`` (PB-B2.2 / harness REQ-07)

Revision ID: d091e3962833
Revises: 98422adaaa38
Create Date: 2026-07-21

Durable evidence snapshots: the raw bytes a scrape fetches are stored content-addressed
(``clue_storage``), and this migration gives them their DB identity — the **``artifact``** row
(key, content hash, media type, size, workspace scope, source-manifest link, timestamps — REQ-07's
column list) plus ``erased_at`` (the DSAR disposition: blob physically deleted, row retained as
audit; the row carries no personal content, PB-B2 ruling 2).

``claim.artifact_key`` is the provenance ref (PB-B2 ruling 1): nullable — existing claims and
non-snapshotting writers stay NULL — and an FK onto ``artifact.storage_key``, the *deterministic*
content-addressed key (``{workspace|public}/{sha256}``), so the sync adapter chain can stamp it
before any DB write and content-hash dedup can never orphan a stamp. Like every provenance column
it is **immutable**: the append-only guard grows to cover it (the 0004/0008/651b/b61cd lock-step
discipline).

Hand-written and reversible: ``downgrade()`` restores the prior guard, then drops the column and
table (CI runs up → down → up via ``make db-smoke``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d091e3962833"
down_revision: str | None = "98422adaaa38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The append-only guard's immutable-column list, in lock-step with 0002 (M1.1) + 0004 (M1.4) +
# 0008/b61cd (workspace_id, reuse_scope) + 651b (source_key). B2 adds artifact_key (immutable
# provenance); only superseded_by / verification_status / corroborations stay mutable.
_M1_1_IMMUTABLE = (
    "id",
    "entity_id",
    "entity_type",
    "field_key",
    "value_json",
    "source_url",
    "source_tier",
    "extraction_method",
    "evidence_span",
    "confidence",
    "observed_at",
    "collected_at",
    "cost_cents",
    "run_id",
    "research_mode",
)
_M1_4_IMMUTABLE = ("identity_binding", "use_class", "discovery_provenance", "claim_flavor")
_A3_1_IMMUTABLE = ("workspace_id", "reuse_scope")
_M4_1_IMMUTABLE = ("source_key",)
_B2_IMMUTABLE = ("artifact_key",)
_PRIOR_IMMUTABLE = _M1_1_IMMUTABLE + _M1_4_IMMUTABLE + _A3_1_IMMUTABLE + _M4_1_IMMUTABLE
_MUTABLE_COLUMNS = ("superseded_by", "verification_status", "corroborations")


def _guard_function_sql(columns: tuple[str, ...]) -> str:
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in columns)
    allow = ", ".join(_MUTABLE_COLUMNS)
    return f"""
        CREATE OR REPLACE FUNCTION claim_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'claim is append-only: only ({allow}) may be updated; an immutable '
                    'provenance column was modified. Supersede by inserting a new claim.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    # --- the artifact table (REQ-07) ----------------------------------------
    # storage_key is the content-addressed identity ({workspace|public}/{sha256}); its UNIQUE
    # constraint is what makes record_artifact's ON CONFLICT DO NOTHING the dedup (identical
    # bytes in one workspace = one row). workspace_id is plain text, NULL-able — NULL means the
    # snapshot backs public-footprint claims (matches claim.workspace_id's convention: no FK).
    op.execute(
        """
        CREATE TABLE artifact (
            artifact_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            storage_key    text NOT NULL,
            workspace_id   text,
            content_sha256 text NOT NULL,
            media_type     text NOT NULL,
            size_bytes     bigint NOT NULL,
            source_key     text,
            source_url     text,
            created_at     timestamptz NOT NULL DEFAULT now(),
            erased_at      timestamptz,

            CONSTRAINT artifact_storage_key_unique UNIQUE (storage_key),
            CONSTRAINT artifact_size_bytes_nonneg CHECK (size_bytes >= 0),
            CONSTRAINT artifact_sha256_shape CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE artifact IS 'Durable content-addressed evidence snapshot (PB-B2 / "
        "REQ-07): the bytes a fetch saw, stored via clue_storage under storage_key = "
        "{workspace|public}/{sha256}. erased_at = blob deleted (DSAR); row retained as audit "
        "(no personal content). Claims reference storage_key (claim.artifact_key).'"
    )

    # --- the claim provenance ref (PB-B2 ruling 1) --------------------------
    # Nullable, no backfill: NULL means "no snapshot recorded" (pre-B2 rows; tier-1 API writers).
    op.execute("ALTER TABLE claim ADD COLUMN artifact_key text")
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_artifact_key_fk "
        "FOREIGN KEY (artifact_key) REFERENCES artifact(storage_key)"
    )
    # The DSAR refcount read path (live claims still referencing a snapshot).
    op.execute(
        "CREATE INDEX claim_artifact_key_live ON claim (artifact_key) "
        "WHERE artifact_key IS NOT NULL AND superseded_by IS NULL"
    )
    # Grow the append-only guard so artifact_key is immutable provenance too.
    op.execute(_guard_function_sql(_PRIOR_IMMUTABLE + _B2_IMMUTABLE))


def downgrade() -> None:
    # Restore the guard to the pre-B2 list BEFORE dropping the column it references.
    op.execute(_guard_function_sql(_PRIOR_IMMUTABLE))
    op.execute("DROP INDEX IF EXISTS claim_artifact_key_live")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_artifact_key_fk")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS artifact_key")
    op.execute("DROP TABLE artifact")
