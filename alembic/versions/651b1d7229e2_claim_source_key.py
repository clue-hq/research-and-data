"""claim.source_key — the producing source on the claim (M4.1 / ENG-105)

Revision ID: 651b1d7229e2
Revises: b9c6d72ac860
Create Date: 2026-06-20

The M1 ``claim`` carries ``source_url`` + ``source_tier`` but not *which registered source* produced
it. M4 needs that: the waterfall (M4.1) attributes per-source yield and keys its idempotency on the
step's source, and ``tier_plan`` routinely lists >1 source at one tier (``[apollo, clay]``) so tier
alone is ambiguous. The M4 backlog invariant says exactly this — "make claims carry ``source_key``
and re-key telemetry once M4 adds it." This adds a nullable ``source_key`` column (the waterfall
stamps it; pre-M4 rows and non-resolver writers leave it NULL) and grows the append-only guard to
cover it — ``source_key`` is immutable provenance, like every other provenance column (M1.4/M2.5
discipline).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "651b1d7229e2"
down_revision: str | None = "b9c6d72ac860"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The append-only guard's immutable-column list, in lock-step with 0002 (M1.1) + 0004 (M1.4) +
# 0008 (M2.5). M4.1 adds source_key (immutable provenance); only superseded_by /
# verification_status / corroborations stay mutable.
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
_M2_5_IMMUTABLE = ("tenant_id", "reuse_scope")
_M4_1_IMMUTABLE = ("source_key",)
_PRIOR_IMMUTABLE = _M1_1_IMMUTABLE + _M1_4_IMMUTABLE + _M2_5_IMMUTABLE
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
    # Nullable: the waterfall stamps it; pre-M4 rows and non-resolver writers keep NULL until they
    # set it. No backfill — NULL means "producing source not recorded".
    op.execute("ALTER TABLE claim ADD COLUMN source_key text")
    # Grow the append-only guard so source_key is immutable provenance too (the M1.4/M2.5 gotcha).
    op.execute(_guard_function_sql(_PRIOR_IMMUTABLE + _M4_1_IMMUTABLE))


def downgrade() -> None:
    # Restore the guard to the pre-M4.1 list BEFORE dropping the column it references.
    op.execute(_guard_function_sql(_PRIOR_IMMUTABLE))
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS source_key")
