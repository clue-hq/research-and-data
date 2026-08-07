"""field_definition.research_scope — declared field species (FI-2 slice 0, pillar P3)

Revision ID: 21552956dc51
Revises: 61b00ee9c70a
Create Date: 2026-08-07

FI-2 §4/§5: turn "is this field's value a world-fact or a project-relative answer?" into a
**declaration at the field**, mirroring the ``reuse_scope`` design exactly (``82831d3fa4c5``). This
**extends** (does not redefine) the M1.3 ``field_definition`` registry and its C8 tenant-local
overlay ``workspace_field_definition`` with one column each (conventions §4 — extend, not redefine).

* ``field_definition.research_scope`` (``project_neutral`` | ``project_relative``, **nullable**) —
  ``NULL`` means "fall back to the ratified default" (``core.default_research_scope``):
  ``account.scoring.*`` / ``account.value_narrative`` / ``contact.persona`` /
  ``contact.role_on_committee`` → relative, everything else → neutral. A ``<pack>.*`` field must
  declare one (``register_field`` is fail-loud; ``client.*`` is excepted — it is neutral by
  construction).
* ``workspace_field_definition.research_scope`` — ``NOT NULL DEFAULT 'project_neutral'``, the way
  that table forces every other authority-bearing property. Deliberately **not** CHECK-forced to
  the neutral value, so a future declared-relative ``client.*`` field stays possible (FI-2 §4).

``text`` + a named CHECK, not a DB enum: species is registry policy that may grow, and a text
column carries no enum-parity burden (FI-2 slice-0 global constraint). The backfill is the exact
set the shipped code declares — the ratified relative keys, plus the existing non-``client``
``<pack>.*`` rows which the pack authors now declare neutral — so idempotent re-registration
(``register_field`` treats a species change as a redefinition) keeps working against a DB migrated
before those declarations landed. Every other row stays ``NULL`` and resolves via the default.
``field_definition`` is a mutable registry, and ``workspace_field_definition``'s immutability
trigger guards UPDATEs of rows, not DDL, so no trigger/guard is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "21552956dc51"
down_revision: str | None = "61b00ee9c70a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPECIES = "('project_neutral', 'project_relative')"

# The ratified relative keys (FI-2 §5.2). The scoring family is matched by prefix so a future
# account.scoring.* score inherits the species without another migration.
_RELATIVE_PREDICATE = (
    "field_key LIKE 'account.scoring.%' "
    "OR field_key IN ('account.value_narrative', 'contact.persona', "
    "'contact.role_on_committee')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE field_definition ADD COLUMN research_scope text")
    op.execute(
        "ALTER TABLE field_definition ADD CONSTRAINT field_definition_research_scope "
        f"CHECK (research_scope IS NULL OR research_scope IN {_SPECIES})"
    )
    op.execute(
        "COMMENT ON COLUMN field_definition.research_scope IS 'Declared field species (FI-2 P3): "
        "project_neutral (a world-fact about the account/contact — readable in every project lens, "
        "spend TTL-governed) vs project_relative (defined relative to an ICP/product/campaign — "
        "lineage-filtered reads, researched per project, project-scoped supersedes). NULL = fall "
        "back to core.default_research_scope; a <pack>.* field (client.* excepted) must declare "
        "one. Orthogonal to reuse_scope, which stays the privacy classification.'"
    )
    op.execute(
        "UPDATE field_definition SET research_scope = 'project_relative' "
        f"WHERE research_scope IS NULL AND ({_RELATIVE_PREDICATE})"
    )
    op.execute(
        "UPDATE field_definition SET research_scope = 'project_neutral' "
        "WHERE research_scope IS NULL AND field_class = 'pack' AND field_key NOT LIKE 'client.%'"
    )

    op.execute(
        "ALTER TABLE workspace_field_definition ADD COLUMN research_scope text "
        "NOT NULL DEFAULT 'project_neutral'"
    )
    op.execute(
        "ALTER TABLE workspace_field_definition ADD CONSTRAINT "
        "workspace_field_definition_research_scope "
        f"CHECK (research_scope IN {_SPECIES})"
    )
    op.execute(
        "COMMENT ON COLUMN workspace_field_definition.research_scope IS 'Declared field species "
        "(FI-2 P3) for a tenant-local client.* field. Defaults project_neutral (workspace-scoped "
        "by construction; FI-2 §5.2) and is forced neutral by the registration service, but is "
        "deliberately not CHECK-forced so a declared-relative client field stays possible.'"
    )


def downgrade() -> None:
    # Dropping the columns drops their CHECKs with them; no enum type was created.
    op.execute("ALTER TABLE workspace_field_definition DROP COLUMN IF EXISTS research_scope")
    op.execute("ALTER TABLE field_definition DROP COLUMN IF EXISTS research_scope")
