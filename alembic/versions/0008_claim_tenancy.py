"""claim cross-tenant reuse class + tenant isolation (M2.5 / ENG-124)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-19

Realize the architecture's stated moat while keeping it safe (substrate §2): *public-footprint
claims about a company (employee count, tech stack, funding) are partially reusable across clients
and amortize cost; client-specific scoring and any client-private data stay tenant-isolated.*
This migration makes the reuse boundary a property of the data model — two additive columns on the
M1 ``claim`` table:

* ``reuse_scope`` (``public_footprint`` | ``tenant_private``) — derived from policy at write, stored
  for fast filtering;
* ``tenant_id`` (``text``, aligned with ``config.client_id``) — present iff the claim is private.

A CHECK couples them (``public_footprint ⟺ tenant_id IS NULL``), and a scoped partial index
``(entity_id, field_key, reuse_scope, tenant_id) WHERE superseded_by IS NULL`` serves the
tenant-scoped ``current_value`` read.

**Backfill (decision):** existing rows are set to ``public_footprint`` (``tenant_id`` NULL). This is
correct at M2's position in the build order: the tenant-private *writers* (the CRM resolver M4,
scoring M6, the personal/facet/resonance synthesizers M8) do not exist yet, so every pre-existing
claim is genuinely a public-eligible firmographic fact (or test data). Going forward the writer
classifies via ``identity.classify_reuse_scope`` and stamps the column explicitly; the DB DEFAULT is
kept as the fail-safe shared base (a value, never a tenant, so it can leak no private data).

**Append-only guard (the critical step):** ``tenant_id`` / ``reuse_scope`` are immutable provenance,
so the ``claim_reject_immutable_update`` guard MUST grow to cover them — otherwise they would be
silently mutable in place (the exact M1.4 gotcha). We ``CREATE OR REPLACE`` the guard with the full
column list and restore the prior list on downgrade (mirroring 0004's discipline).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.core.enums.ReuseScope. Parity-tested in the M2.5 isolation test suite.
_REUSE_SCOPE = ("public_footprint", "tenant_private")

# The append-only guard's immutable-column list, kept in lock-step with 0002 (M1.1) + 0004 (M1.4).
# M2.5 adds tenant_id + reuse_scope (immutable provenance); only superseded_by / verification_status
# / corroborations stay mutable.
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
_MUTABLE_COLUMNS = ("superseded_by", "verification_status", "corroborations")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


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
    op.execute(f"CREATE TYPE reuse_scope AS ENUM ({_enum_values_sql(_REUSE_SCOPE)})")

    # tenant_id is text (aligned with config.client_id). reuse_scope is added WITH a default so
    # existing rows backfill to public_footprint (correct at M2 — no tenant-private writers exist
    # yet); the default is kept as the fail-safe shared base for low-level inserts.
    op.execute("ALTER TABLE claim ADD COLUMN tenant_id text")
    op.execute(
        "ALTER TABLE claim ADD COLUMN reuse_scope reuse_scope NOT NULL DEFAULT 'public_footprint'"
    )

    # public_footprint ⟺ no tenant; tenant_private ⟺ a tenant. A private claim can never be silently
    # shared (no tenant), and a public claim can never be silently attributed to one tenant.
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_reuse_scope_tenant CHECK (
            (reuse_scope = 'public_footprint' AND tenant_id IS NULL)
            OR (reuse_scope = 'tenant_private' AND tenant_id IS NOT NULL)
        )
        """
    )

    # The scoped live-claims read: current_value filters on (reuse_scope, tenant_id) here.
    op.execute(
        "CREATE INDEX claim_scoped_read ON claim (entity_id, field_key, reuse_scope, tenant_id) "
        "WHERE superseded_by IS NULL"
    )

    # Grow the append-only guard to the two new immutable columns (else they would be mutable
    # in place — the M1.4 gotcha). Full list = M1.1 + M1.4 + M2.5.
    op.execute(_guard_function_sql(_M1_1_IMMUTABLE + _M1_4_IMMUTABLE + _M2_5_IMMUTABLE))


def downgrade() -> None:
    # Restore the guard to the 0007-era list (M1.1 + M1.4) BEFORE dropping the columns it uses.
    op.execute(_guard_function_sql(_M1_1_IMMUTABLE + _M1_4_IMMUTABLE))
    op.execute("DROP INDEX IF EXISTS claim_scoped_read")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_reuse_scope_tenant")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS reuse_scope")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP TYPE IF EXISTS reuse_scope")
