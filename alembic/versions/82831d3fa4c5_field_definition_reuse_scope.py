"""field_definition.reuse_scope — declared cross-tenant reuse class (M6 prereq / ENG-165 W1)

Revision ID: 82831d3fa4c5
Revises: eab62cbb1366
Create Date: 2026-06-21

ENG-165 (the M6 prereq): turn cross-tenant reuse from an inferred prefix heuristic into a
**declaration at the field**. This **extends** (does not redefine) the M1.3 ``field_definition``
registry with one nullable column the classifier consults *before* the prefix heuristic and the
write boundary enforces fail-closed (conventions §4 — extend, not redefine; mirrors how 0011 added
``signal_class``).

* ``reuse_scope`` (``public_footprint`` | ``tenant_private``, nullable) — the field's declared
  reuse class. ``NULL`` means "fall back to the class default" (``core.default_reuse_scope``):
  ``core.*`` / ``account.*`` → public, ``contact.*`` / ``contact.facet.*`` / ``account.resonance.*``
  → private, and a ``<pack>.*`` field has **no safe default** so it must declare one (the authoring
  guard enforces it; the write boundary refuses an unresolvable scope).

Reuses the ``reuse_scope`` PG enum created in 0008 (claim tenancy) — no new enum, so no enum-parity
burden, and ``downgrade()`` leaves the shared type alone (other columns use it). The column is added
WITHOUT a backfill: existing rows resolve via the class default at read/write time, so legacy rows
stay correct and idempotent re-registration (``register_field``: NULL == an undeclared FieldDef)
keeps working; only the newly-reserved ``account.scoring.*`` keys are inserted ``tenant_private``.
``field_definition`` is a mutable registry (not append-only), so no trigger/guard touches it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82831d3fa4c5"
down_revision: str | None = "eab62cbb1366"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: NULL = "use the class default" (core.default_reuse_scope); a PACK field must
    # declare a non-NULL value (enforced by the authoring guard + the claim-write boundary, not a DB
    # CHECK, so legacy NULL rows in canonical namespaces remain valid and resolvable).
    op.execute("ALTER TABLE field_definition ADD COLUMN reuse_scope reuse_scope")
    op.execute(
        "COMMENT ON COLUMN field_definition.reuse_scope IS 'Declared cross-tenant reuse class "
        "(M2.5/ENG-165 W1): public_footprint (amortizes across clients) vs tenant_private "
        "(isolated). NULL = fall back to core.default_reuse_scope by field_class; a <pack>.* field "
        "has no safe default and must declare one. The classifier consults this before the prefix "
        "heuristic; the claim-write boundary is fail-closed on it.'"
    )


def downgrade() -> None:
    # reuse_scope is the shared enum from 0008 — leave the type (the claim table uses it); drop only
    # the column this migration added.
    op.execute("ALTER TABLE field_definition DROP COLUMN IF EXISTS reuse_scope")
