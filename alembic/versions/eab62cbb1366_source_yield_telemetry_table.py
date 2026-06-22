"""source_yield telemetry table

Revision ID: eab62cbb1366
Revises: 651b1d7229e2
Create Date: 2026-06-20 13:58:35.722936+00:00

M4.6 (ENG-129) — the per-source yield telemetry the learning loop (staged-flow §7e / Doc C §6)
reweights. Append-only measurement rows per (ICP, field-class, source): coverage (claims/fields the
source produced), precision substrate (claims that survived M9 verification), cost, freshness, plus
a free-form ``disposition`` hook. M4.6 *emits and stores*; **M13 reweights** the source profiles
(``source_profile`` / ``source_profile_override``, migration 0009) from it — the loop is a config
writer, not an engine change.

Reuses the ``field_class`` PG enum created in 0003 (no new enum → no enum-parity burden, and the
downgrade leaves the shared type alone — mirroring how 0009 reuses ``field_class`` and
``b9c6d72ac860`` reuses ``identity_binding``). ``downgrade()`` cleanly reverses ``upgrade()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eab62cbb1366"
down_revision: str | None = "651b1d7229e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Append-only telemetry. A row is one measurement of one source's yield for one
    # (ICP, field-class) slot; M13 aggregates rows to reweight the priors. ``field_class`` NULL =
    # the pack-wide slot (mirrors source_profile). ``run_id`` NULL = not tied to a single run.
    op.execute(
        """
        CREATE TABLE source_yield (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            client_id        text NOT NULL,
            icp_key          text NOT NULL,
            icp_version      int,
            field_class      field_class,
            source_key       text NOT NULL,
            run_id           uuid,
            claims_total     int NOT NULL DEFAULT 0,
            claims_verified  int NOT NULL DEFAULT 0,
            fields_filled    int NOT NULL DEFAULT 0,
            cost_cents       numeric NOT NULL DEFAULT 0,
            freshness_seconds bigint,
            disposition      jsonb,
            recorded_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT source_yield_icp_version_positive
                CHECK (icp_version IS NULL OR icp_version >= 1),
            CONSTRAINT source_yield_claims_total_nonneg CHECK (claims_total >= 0),
            CONSTRAINT source_yield_claims_verified_nonneg CHECK (claims_verified >= 0),
            -- precision = claims_verified / claims_total: a measurement can never verify more
            -- claims than it produced (guards a malformed write).
            CONSTRAINT source_yield_verified_le_total CHECK (claims_verified <= claims_total),
            CONSTRAINT source_yield_fields_filled_nonneg CHECK (fields_filled >= 0),
            CONSTRAINT source_yield_cost_nonneg CHECK (cost_cents >= 0),
            CONSTRAINT source_yield_freshness_nonneg
                CHECK (freshness_seconds IS NULL OR freshness_seconds >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE source_yield IS 'Per-source yield telemetry (staged-flow §7e / Doc C §6; "
        "M4.6). Append-only measurement rows per (ICP=client_id+icp_key[+version], field_class, "
        "source_key): coverage (claims_total / fields_filled), precision (claims_verified = "
        "survived M9), cost_cents, freshness_seconds, disposition. M4.6 emits; M13 aggregates + "
        "reweights source_profile via the same config seam (the loop is a config writer).'"
    )

    # read-path indexes for the M13/audit aggregation (per ICP slot, and per source across ICPs).
    op.execute("CREATE INDEX source_yield_lookup ON source_yield (client_id, icp_key, source_key)")
    op.execute("CREATE INDEX source_yield_source ON source_yield (source_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS source_yield_source")
    op.execute("DROP INDEX IF EXISTS source_yield_lookup")
    op.execute("DROP TABLE IF EXISTS source_yield")
    # field_class is the shared enum from 0003 — leave it (other tables use it).
