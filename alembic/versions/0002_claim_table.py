"""claim table — append-only, supersede, provenance fields (M1.1 / ENG-102)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19

Stand up ``claim``: the append-only event log that is the atomic unit of the whole subsystem
(substrate §0/§1). Every fact about an account or contact is a *row* with its full provenance
envelope, never a field on a free-text dossier. This migration realizes the ``_conventions.md`` §4
``claim`` contract and the migration-conventions checklist in ``src/clue_research/db/README.md``.

What this migration establishes (M1.1 scope):

* the §4 column set + the ``verification_status`` lifecycle column (the structural home of the
  evidence-span verdict; M9/M10 transition it, the M1.2 merge view reads it);
* **append-only enforcement** — a BEFORE-UPDATE trigger that rejects any mutation of an immutable
  provenance column (the only permitted updates are ``superseded_by``, ``verification_status``,
  ``corroborations``), and a BEFORE-DELETE trigger that rejects deletes outright (erasure /
  tombstoning is M10.5, not here). Supersession is modelled by INSERTing a new row and setting the
  prior row's ``superseded_by`` — never an in-place UPDATE of a value column;
* **CHECK constraints** encoding the substrate invariants — ``source_tier ∈ 1..4``,
  ``confidence ∈ 0..1``, the tier-4 ⇔ ``llm_synthesis`` coupling (substrate §4), and *the
  evidence-span rule*: a row may not be ``verified`` while ``source_tier = 4 AND evidence_span IS
  NULL`` (the schema-level kill switch for fabricated facts; substrate §1/§6);
* indexes for the hot read paths the merge view (M1.2) and scoring (M6) need, including the
  ``(entity_id, field_key) WHERE superseded_by IS NULL`` partial "live claims" index.

``research_mode`` is created here (it is part of the §4 base ``claim`` contract and the
``core.Claim`` model requires it); M1.4 (migration 0004) adds the two *provenance-flavor* columns
(``identity_binding``, ``use_class``, ``discovery_provenance``, ``claim_flavor``) and the
flavor-specific constraints/indexes around it — one substrate, richer typing (staged-flow §9).

Soft FK note: ``entity_id`` logically references ``account_entity(id)`` (M2), but that table does
not exist yet. The FK is therefore *deferred* — a later M2 migration adds it once the table is
populated — so M1 can land first (spec §M1.1 "documented as deferrable").
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum value sets mirror clue_research.core.enums (StrEnum members) exactly. The enum-parity test
# tests/claimstore/test_claim_table.py::test_db_enums_match_core introspects the live pg_enum and
# asserts these stay in lock-step with the Python enums (the DB and the domain model can't import
# each other's spelling, so the test is the guard against drift).
_ENTITY_TYPE = ("account", "contact")
_EXTRACTION_METHOD = ("api", "scrape", "llm_synthesis", "human", "crm_import")
_RESEARCH_MODE = (
    "account_discovery",
    "account_profiling",
    "committee_discovery",
    "contact_profiling",
)
_VERIFICATION_STATUS = ("unverified", "verified", "rejected", "flagged")

# The only columns a supersession / verification verdict may mutate (spec §M1.1 allow-list).
# Everything else is immutable provenance and the trigger rejects any change to it.
_MUTABLE_COLUMNS = ("superseded_by", "verification_status", "corroborations")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --- enum types ---------------------------------------------------------
    op.execute(f"CREATE TYPE entity_type AS ENUM ({_enum_values_sql(_ENTITY_TYPE)})")
    op.execute(f"CREATE TYPE extraction_method AS ENUM ({_enum_values_sql(_EXTRACTION_METHOD)})")
    op.execute(f"CREATE TYPE research_mode AS ENUM ({_enum_values_sql(_RESEARCH_MODE)})")
    op.execute(
        f"CREATE TYPE verification_status AS ENUM ({_enum_values_sql(_VERIFICATION_STATUS)})"
    )

    # --- claim table --------------------------------------------------------
    # gen_random_uuid() is built into Postgres 13+ (no extension needed). value_json is JSONB so
    # per-vertical payload shape varies without a schema change (substrate §12). Time columns are
    # timestamptz (UTC). The evidence-span CHECK is the structural anti-fabrication invariant.
    op.execute(
        """
        CREATE TABLE claim (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id           uuid NOT NULL,
            entity_type         entity_type NOT NULL,
            field_key           text NOT NULL,
            value_json          jsonb NOT NULL,
            source_url          text,
            source_tier         int NOT NULL,
            extraction_method   extraction_method NOT NULL,
            evidence_span       text,
            confidence          numeric NOT NULL,
            corroborations      int NOT NULL DEFAULT 0,
            observed_at         timestamptz,
            collected_at        timestamptz NOT NULL DEFAULT now(),
            cost_cents          numeric NOT NULL DEFAULT 0,
            run_id              uuid NOT NULL,
            research_mode       research_mode NOT NULL,
            superseded_by       uuid REFERENCES claim(id),
            verification_status verification_status NOT NULL DEFAULT 'unverified',

            CONSTRAINT claim_source_tier_range
                CHECK (source_tier BETWEEN 1 AND 4),
            CONSTRAINT claim_confidence_range
                CHECK (confidence >= 0 AND confidence <= 1),
            CONSTRAINT claim_corroborations_nonneg
                CHECK (corroborations >= 0),
            CONSTRAINT claim_cost_cents_nonneg
                CHECK (cost_cents >= 0),
            -- substrate §4: tier 4 is exactly LLM synthesis, and nothing else is tier 4.
            CONSTRAINT claim_tier4_iff_synthesis
                CHECK ((source_tier = 4) = (extraction_method = 'llm_synthesis')),
            -- the evidence-span rule (substrate §1/§6): a tier-4 claim with no span can never be
            -- promoted to 'verified'. A fabricated fact has no span to point at.
            CONSTRAINT claim_tier4_verified_requires_span
                CHECK (NOT (verification_status = 'verified'
                            AND source_tier = 4
                            AND evidence_span IS NULL))
        )
        """
    )

    op.execute(
        "COMMENT ON TABLE claim IS 'Append-only typed-claim-with-provenance event log "
        "(substrate §1). Supersede via superseded_by; never UPDATE-in-place. entity_id "
        "soft-references account_entity(id) (M2) — FK deferred until that table exists.'"
    )

    # --- append-only enforcement (trigger) ----------------------------------
    # BEFORE UPDATE: reject any change to an immutable provenance column. Only superseded_by,
    # verification_status, corroborations may change. IS DISTINCT FROM is null-safe.
    immutable_guard = " OR ".join(
        f"NEW.{col} IS DISTINCT FROM OLD.{col}"
        for col in (
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
    )
    allow = ", ".join(_MUTABLE_COLUMNS)
    op.execute(
        f"""
        CREATE FUNCTION claim_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {immutable_guard} THEN
                RAISE EXCEPTION
                    'claim is append-only: only ({allow}) may be updated; an immutable '
                    'provenance column was modified. Supersede by inserting a new claim.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION claim_reject_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'claim is append-only: rows cannot be deleted (erasure/tombstoning is M10.5)';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER claim_no_immutable_update BEFORE UPDATE ON claim "
        "FOR EACH ROW EXECUTE FUNCTION claim_reject_immutable_update()"
    )
    op.execute(
        "CREATE TRIGGER claim_no_delete BEFORE DELETE ON claim "
        "FOR EACH ROW EXECUTE FUNCTION claim_reject_delete()"
    )

    # --- indexes for the hot read paths -------------------------------------
    # The "live claims" partial index the merge view (M1.2) reads on every current_value() call.
    op.execute(
        "CREATE INDEX claim_live_entity_field ON claim (entity_id, field_key) "
        "WHERE superseded_by IS NULL"
    )
    op.execute("CREATE INDEX claim_field_key ON claim (field_key)")
    op.execute("CREATE INDEX claim_run_id ON claim (run_id)")
    op.execute("CREATE INDEX claim_collected_at ON claim (collected_at)")
    op.execute("CREATE INDEX claim_value_json_gin ON claim USING gin (value_json)")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS claim_no_delete ON claim")
    op.execute("DROP TRIGGER IF EXISTS claim_no_immutable_update ON claim")
    op.execute("DROP TABLE IF EXISTS claim")
    op.execute("DROP FUNCTION IF EXISTS claim_reject_delete()")
    op.execute("DROP FUNCTION IF EXISTS claim_reject_immutable_update()")
    op.execute("DROP TYPE IF EXISTS verification_status")
    op.execute("DROP TYPE IF EXISTS research_mode")
    op.execute("DROP TYPE IF EXISTS extraction_method")
    op.execute("DROP TYPE IF EXISTS entity_type")
