"""gate_decision enumeration variant (Option C)

Revision ID: c74c23defd01
Revises: 089dc65b5814
Create Date: 2026-06-22 18:03:25.655085+00:00

M9.1 Option C — a first-class ENUMERATION pre-spend request variant (governing committee
people-discovery: "find the people AT this account" has no single field). The ``gate_decision``
audit must honestly record it instead of overloading ``field_key`` with a synthetic name:

* ``request_kind`` (``pre_spend_kind`` enum: ``field`` | ``enumeration``) — what shape of spend was
  gated. NOT NULL DEFAULT ``'field'`` (backfills every existing row in one statement; every existing
  decision is a field-fill).
* ``enumeration_scope`` (``enumeration_scope`` enum: ``committee``) — the scope an enumeration spend
  fans out over; NULL for a field row.
* ``field_key`` — relaxed to NULLable: an enumeration request has no single field.
* a coherence CHECK pinning ``request_kind`` ⇄ ``field_key`` ⇄ ``enumeration_scope`` (mirrors the
  ``PreSpendRequest._check_kind`` model validator).

``pre_spend_kind`` / ``enumeration_scope`` mirror :class:`clue_research.core.enums.PreSpendKind` /
:class:`~clue_research.core.enums.EnumerationScope`; the enum-parity tests in
``tests/verification/test_prespend_gate.py`` guard drift. The ``gate_decision_entity_field``
``(entity_id, field_key)`` index tolerates NULL ``field_key`` (B-tree indexes NULLs), so it is left
unchanged. ``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up on a clean DB).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c74c23defd01"
down_revision: str | None = "089dc65b5814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.core.enums.PreSpendKind / EnumerationScope (parity-tested). The labels here
# ARE the StrEnum ``.value``s — the parity test asserts the PG enum labels equal these.
_PRE_SPEND_KIND = ("field", "enumeration")
_ENUMERATION_SCOPE = ("committee",)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE pre_spend_kind AS ENUM ({_enum_values_sql(_PRE_SPEND_KIND)})")
    op.execute(f"CREATE TYPE enumeration_scope AS ENUM ({_enum_values_sql(_ENUMERATION_SCOPE)})")

    # request_kind: NOT NULL DEFAULT 'field' backfills every existing row (all are field decisions)
    # in one statement; the default also keeps any future append path safe-by-default.
    op.execute(
        "ALTER TABLE gate_decision ADD COLUMN request_kind pre_spend_kind NOT NULL DEFAULT 'field'"
    )
    # enumeration_scope: NULL for a field row, set only on an enumeration row.
    op.execute("ALTER TABLE gate_decision ADD COLUMN enumeration_scope enumeration_scope")
    # field_key: an enumeration request has no single field.
    op.execute("ALTER TABLE gate_decision ALTER COLUMN field_key DROP NOT NULL")
    # Coherence: kind ⇄ field_key ⇄ scope (named CHECK; mirrors PreSpendRequest._check_kind).
    op.execute(
        "ALTER TABLE gate_decision ADD CONSTRAINT gate_decision_kind_coherent CHECK ("
        " (request_kind = 'field' AND field_key IS NOT NULL AND enumeration_scope IS NULL)"
        " OR (request_kind = 'enumeration' AND field_key IS NULL "
        "AND enumeration_scope IS NOT NULL))"
    )
    op.execute(
        "COMMENT ON COLUMN gate_decision.request_kind IS "
        "'M9.1 Option C — field=single-(entity,field) spend; enumeration=scope-fanout discovery.'"
    )
    op.execute(
        "COMMENT ON COLUMN gate_decision.enumeration_scope IS "
        "'M9.1 Option C — the enumeration scope (committee); NULL for a field row.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE gate_decision DROP CONSTRAINT IF EXISTS gate_decision_kind_coherent")
    # Restoring NOT NULL is safe on a clean DB (CI db-smoke); on a non-empty production DB any
    # enumeration rows (NULL field_key) must be deleted before this reverse.
    op.execute("ALTER TABLE gate_decision ALTER COLUMN field_key SET NOT NULL")
    op.execute("ALTER TABLE gate_decision DROP COLUMN IF EXISTS enumeration_scope")
    op.execute("ALTER TABLE gate_decision DROP COLUMN IF EXISTS request_kind")
    op.execute("DROP TYPE IF EXISTS enumeration_scope")
    op.execute("DROP TYPE IF EXISTS pre_spend_kind")
