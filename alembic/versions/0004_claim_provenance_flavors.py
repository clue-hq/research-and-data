"""claim provenance flavors — discovery vs field-claim, identity-binding, use-class (M1.4 / ENG-123)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19

One substrate carries the two structurally different kinds of provenance the 2×2 of research modes
produces (staged-flow §9), with richer typing rather than a second table:

* **field-claim provenance** (modes M2/M4) — value + span + tier; for *contact* personal claims,
  also ``identity_binding`` (the contact-axis analogue of the tier-4 evidence-span rule — a weak
  binding never promotes / drives outreach) and ``use_class`` (Doc D §2; the use-gate, M10, reads
  it);
* **discovery-provenance** (modes M1/M3) — a ``discovery_provenance`` JSONB envelope recording
  *where an entity was found and why it matched* (the existence-gate evidence), kept JSONB so
  discovery channels stay open-by-registration.

``research_mode`` was already created on ``claim`` by M1.1 (0002) — it is part of the §4 base
contract and ``core.Claim`` requires it. This migration adds only the *flavor* columns around it:
``identity_binding``, ``use_class``, ``discovery_provenance``, and the ``claim_flavor``
discriminator. Existing rows are valid: the new columns are nullable except ``claim_flavor``, which
defaults to ``field_claim`` (every M1.1 row is a field claim).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_core.enums (IdentityBinding / UseClass / ClaimFlavor). The enum-parity test
# tests/claimstore/test_provenance_flavors.py::test_flavor_enums_match_core guards against drift.
_IDENTITY_BINDING = ("strong", "weak")
_USE_CLASS = ("professional-public", "personal-public-non-sensitive", "sensitive")
_CLAIM_FLAVOR = ("discovery", "field_claim")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# The append-only trigger's immutable-column guard (created in 0002) must grow to cover the new
# provenance columns — they are immutable provenance too (only superseded_by / verification_status /
# corroborations are mutable). We CREATE OR REPLACE the guard function here (and restore the M1.1
# list on downgrade). Kept in lock-step with 0002's column list.
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
    op.execute(f"CREATE TYPE identity_binding AS ENUM ({_enum_values_sql(_IDENTITY_BINDING)})")
    op.execute(f"CREATE TYPE use_class AS ENUM ({_enum_values_sql(_USE_CLASS)})")
    op.execute(f"CREATE TYPE claim_flavor AS ENUM ({_enum_values_sql(_CLAIM_FLAVOR)})")

    op.execute("ALTER TABLE claim ADD COLUMN identity_binding identity_binding")
    op.execute("ALTER TABLE claim ADD COLUMN use_class use_class")
    op.execute("ALTER TABLE claim ADD COLUMN discovery_provenance jsonb")
    op.execute(
        "ALTER TABLE claim ADD COLUMN claim_flavor claim_flavor NOT NULL DEFAULT 'field_claim'"
    )

    # A discovery claim must carry a discovery_provenance and a discovery research_mode.
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_discovery_requires_provenance CHECK (
            claim_flavor <> 'discovery'
            OR (discovery_provenance IS NOT NULL
                AND research_mode IN ('account_discovery', 'committee_discovery'))
        )
        """
    )
    # A field claim must NOT carry a discovery_provenance (that envelope is discovery-only).
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_field_claim_no_discovery CHECK (
            claim_flavor <> 'field_claim' OR discovery_provenance IS NULL
        )
        """
    )
    # A contact *personal* field claim (the contact.facet.* field-class — rich personal hooks,
    # conventions §3) must carry identity_binding + use_class. Plain contact.* facts
    # (role_on_committee, persona…) are not personal hooks, and a contact *discovery* claim
    # (mode M3 admission evidence) is not a field value, so neither requires it (staged-flow §6/§9).
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_contact_field_requires_governance CHECK (
            NOT (claim_flavor = 'field_claim'
                 AND entity_type = 'contact'
                 AND (field_key = 'contact.facet' OR field_key LIKE 'contact.facet.%')
                 AND (identity_binding IS NULL OR use_class IS NULL))
        )
        """
    )

    # Indexes: research_mode filtering, the weak-binding partial index (the never-promote set the
    # merge view and the M10 use-gate read), and a GIN index over the discovery envelope.
    op.execute("CREATE INDEX claim_research_mode ON claim (research_mode)")
    op.execute(
        "CREATE INDEX claim_weak_binding ON claim (entity_id, field_key) "
        "WHERE identity_binding = 'weak' AND entity_type = 'contact'"
    )
    op.execute(
        "CREATE INDEX claim_discovery_provenance_gin ON claim USING gin (discovery_provenance)"
    )

    # Extend the append-only guard to the new immutable provenance columns (the 0002 function only
    # knew the M1.1 columns, so identity_binding/use_class/discovery_provenance/claim_flavor would
    # otherwise be silently mutable in place — breaking append-only for the flavor provenance).
    op.execute(_guard_function_sql(_M1_1_IMMUTABLE + _M1_4_IMMUTABLE))


def downgrade() -> None:
    # Restore the guard to the M1.1 column list *before* dropping the columns it would reference.
    op.execute(_guard_function_sql(_M1_1_IMMUTABLE))
    op.execute("DROP INDEX IF EXISTS claim_discovery_provenance_gin")
    op.execute("DROP INDEX IF EXISTS claim_weak_binding")
    op.execute("DROP INDEX IF EXISTS claim_research_mode")
    op.execute(
        "ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_contact_field_requires_governance"
    )
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_field_claim_no_discovery")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_discovery_requires_provenance")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS claim_flavor")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS discovery_provenance")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS use_class")
    op.execute("ALTER TABLE claim DROP COLUMN IF EXISTS identity_binding")
    op.execute("DROP TYPE IF EXISTS claim_flavor")
    op.execute("DROP TYPE IF EXISTS use_class")
    op.execute("DROP TYPE IF EXISTS identity_binding")
