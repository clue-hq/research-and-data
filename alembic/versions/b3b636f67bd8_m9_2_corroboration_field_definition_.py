"""m9.2 corroboration — field_definition corroboration config + conflict_flag (ENG-134)

Revision ID: b3b636f67bd8
Revises: 8aefd82b6d59
Create Date: 2026-06-21 12:23:21.340573+00:00

M9.2 (the verification layer's *structural corroboration* pass): provenance proves a single source
*said* something; corroboration proves the fact is *true* — N independent tier≤3 sources agreeing
(substrate §6(2)), with conflicts between authoritative (tier≤2) sources surfaced as a flag, not
silently resolved (substrate §1). This migration adds only the M9.2 *config* + *audit* schema, and
— per the M9 isolation contract — alters **no shared mutable surface**:

* ``field_definition`` gains two corroboration-config columns (policy-as-data, conventions §2):
  ``single_source_sufficient`` (a tier-1 deterministic claim verifies alone — e.g. a registry ID)
  and ``equality_mode`` (how the corroborator decides two ``value_json`` payloads *agree*: exact /
  numeric-tolerance / semantic). The corroboration *threshold N* reuses the **existing**
  ``corroboration_min`` column (added at 0003 for exactly this consumer) — no third column.
* ``conflict_flag`` — one open row per ``(entity, field)`` whose authoritative sources disagree,
  consumed by the review queue (M13.1). A partial unique index keeps a single *open* flag per pair
  so re-evaluation is idempotent (no duplicate rows); resolving a flag (setting ``resolved_by``) is
  M13.1's job, never M9.2's.

The promotion verdict itself rides the **already-mutable** ``claim.verification_status`` /
``claim.corroborations`` columns (the 0002/0004/0008 trigger allow-list) — so M9.2 needs **no
trigger change and no ``claim`` ALTER**. The ``claim_tier4_verified_requires_span`` CHECK (0002)
stays the backstop against promoting a span-less tier-4 claim.

``equality_mode`` mirrors :class:`clue_core.EqualityMode` (relocated from the M9.2
corroborator to ``core`` by the [M9.2×M1.2] merge-equality fix, so the mode-aware merge conflict
check and the corroborator share one enum; the parity test
``test_corroboration.py::test_equality_mode_enum_matches_db`` imports it via the verification
re-export). ``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3b636f67bd8"
down_revision: str | None = "8aefd82b6d59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_core.EqualityMode (parity-tested in the M9.2 suite).
_EQUALITY_MODE = ("exact", "numeric_tol", "semantic")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --- field_definition: corroboration config as data (conventions §2) ---
    op.execute(f"CREATE TYPE equality_mode AS ENUM ({_enum_values_sql(_EQUALITY_MODE)})")
    op.execute(
        "ALTER TABLE field_definition "
        "ADD COLUMN single_source_sufficient boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE field_definition "
        "ADD COLUMN equality_mode equality_mode NOT NULL DEFAULT 'exact'"
    )
    op.execute(
        "COMMENT ON COLUMN field_definition.single_source_sufficient IS "
        "'M9.2: a tier-1 deterministic claim on this field is verified without corroboration "
        "(e.g. a registry ID). Default false — most fields require corroboration_min sources.'"
    )
    op.execute(
        "COMMENT ON COLUMN field_definition.equality_mode IS "
        "'M9.2: how the corroborator decides two value_json payloads agree — exact (enums/ids), "
        "numeric_tol (numerics within tolerance), or semantic (normalized text overlap).'"
    )

    # --- conflict_flag: authoritative (tier≤2) disagreement, surfaced for review (M13.1) ---
    # conflicting_claim_ids is the representative claim id per disagreeing value-group. resolved_by
    # / resolved_at are written by M13.1 (human review / re-research), never by M9.2 (only raises).
    op.execute(
        """
        CREATE TABLE conflict_flag (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id             uuid NOT NULL,
            field_key             text NOT NULL,
            conflicting_claim_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            raised_at             timestamptz NOT NULL DEFAULT now(),
            resolved_by           text,
            resolved_at           timestamptz,

            CONSTRAINT conflict_flag_ids_is_array
                CHECK (jsonb_typeof(conflicting_claim_ids) = 'array'),
            -- resolved_by and resolved_at travel together: an open flag has neither, a resolved
            -- flag has both (M13.1 stamps them atomically).
            CONSTRAINT conflict_flag_resolution_coherent
                CHECK ((resolved_by IS NULL) = (resolved_at IS NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE conflict_flag IS 'M9.2 authoritative-source conflict (substrate §1): two"
        " or more tier≤2 sources disagree on an (entity, field). Raised by the corroborator, never"
        " auto-resolved; consumed by the review queue (M13.1). One OPEN flag per pair (partial "
        "unique index) so re-evaluation is idempotent.'"
    )
    # At most one *open* (unresolved) flag per (entity, field): the corroborator upserts onto this
    # index, so re-running it never accumulates rows (idempotency). A resolved flag drops out of the
    # index, so a later, distinct conflict can open a fresh one.
    op.execute(
        "CREATE UNIQUE INDEX conflict_flag_open_entity_field "
        "ON conflict_flag (entity_id, field_key) WHERE resolved_by IS NULL"
    )
    # Review-queue read paths: by (entity, field) and by time.
    op.execute("CREATE INDEX conflict_flag_entity_field ON conflict_flag (entity_id, field_key)")
    op.execute("CREATE INDEX conflict_flag_raised_at ON conflict_flag (raised_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conflict_flag_raised_at")
    op.execute("DROP INDEX IF EXISTS conflict_flag_entity_field")
    op.execute("DROP INDEX IF EXISTS conflict_flag_open_entity_field")
    op.execute("DROP TABLE IF EXISTS conflict_flag")
    op.execute("ALTER TABLE field_definition DROP COLUMN IF EXISTS equality_mode")
    op.execute("ALTER TABLE field_definition DROP COLUMN IF EXISTS single_source_sufficient")
    op.execute("DROP TYPE IF EXISTS equality_mode")
