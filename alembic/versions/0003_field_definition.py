"""field_definition registry — the field set as a contract, not hardcoded columns (M1.3 / ENG-117)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19

The field registry is *the* generalization move (substrate §1/§3): every ``field_key`` is a row
declaring its type, validation, ordered tier plan, freshness TTL, scoring/deep pass, and gate — so
adding a per-vertical field (``healthcare.npi``) or a whole vertical is a *registration*, never a
pipeline fork (conventions §2 — open by registration, not enumeration). It also registers the two
governed field-classes (``account.resonance.*`` culture/sentiment, ``contact.facet.*`` personal
hooks; Doc C §2) — registered, not enumerated.

Columns are the ``_conventions.md`` §4 ``field_definition`` contract plus the M1.3 extensions:

* ``value_schema`` — the JSONB shape a ``claim.value_json`` must validate against for this field
  (enforced by ``validate_value`` / ``insert_claim``);
* ``corroboration_min`` — # independent tier≤3 sources required before ``verified`` (substrate
  §6(2); the M9 corroboration engine consumes it; M1.3 only stores it);
* ``field_class`` — the namespace class, derived from the ``field_key`` prefix; carries the
  governed/deep/tier-4 nature of resonance/facet fields that M10/Doc D read;
* ``pack`` / ``active`` / ``version`` / ``created_at`` — registry bookkeeping.

This table is a sibling of M4's ``source_manifest`` registry; ``tier_plan`` references source keys
*by name* only — M1.3 does not validate that a resolver exists (that join is M4, behind the seam).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_core.enums.PassKind / FieldClass. The enum-parity test in
# tests/claimstore/test_field_registry.py::test_registry_enums_match_core guards against drift.
_PASS = ("scoring", "deep")
_FIELD_CLASS = ("core", "account", "account.resonance", "contact", "contact.facet", "pack")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE field_pass AS ENUM ({_enum_values_sql(_PASS)})")
    op.execute(f"CREATE TYPE field_class AS ENUM ({_enum_values_sql(_FIELD_CLASS)})")

    op.execute(
        """
        CREATE TABLE field_definition (
            field_key         text PRIMARY KEY,
            value_type        text NOT NULL,
            validation        jsonb,
            tier_plan         jsonb NOT NULL DEFAULT '[]'::jsonb,
            freshness_ttl     interval,
            pass_kind         field_pass NOT NULL,
            gate              text,
            field_class       field_class NOT NULL,
            value_schema      jsonb,
            corroboration_min int NOT NULL DEFAULT 1,
            description       text,
            active            boolean NOT NULL DEFAULT true,
            pack              text,
            version           int NOT NULL DEFAULT 1,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT field_definition_corroboration_min_nonneg
                CHECK (corroboration_min >= 0),
            CONSTRAINT field_definition_tier_plan_is_array
                CHECK (jsonb_typeof(tier_plan) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE field_definition IS 'The field registry (substrate §1/§3): every "
        "field_key is a row. Open by registration, not enumeration. tier_plan references source "
        "keys by name (the join to source_manifest is M4).'"
    )
    # list_fields() filters on these; promote them to indexes.
    op.execute("CREATE INDEX field_definition_pass_kind ON field_definition (pass_kind)")
    op.execute("CREATE INDEX field_definition_field_class ON field_definition (field_class)")
    op.execute(
        "CREATE INDEX field_definition_pack ON field_definition (pack) WHERE pack IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field_definition")
    op.execute("DROP TYPE IF EXISTS field_class")
    op.execute("DROP TYPE IF EXISTS field_pass")
