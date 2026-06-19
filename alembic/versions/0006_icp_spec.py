"""icp_spec — the versioned ICP spec contract (M3.1 / ENG-104)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-19

The versioned ICP spec (staged-flow §2; conventions §4) is the single contract everything downstream
of Stage 0 runs against, keyed (client_id, icp_key, version). It is durable, append-only config
(conventions §2 — policy is data): an ``active`` spec is IMMUTABLE; an edit appends a new version
(``parent_version`` links the lineage) and activating it archives the prior — never deletes — so a
campaign_run (M7) that pins (client_id, icp_key, version) re-reads identically (the same discipline
the claim store uses in M1).

Stores the four sub-contract slots as JSONB: ``field_keys`` (active field set; validated against the
M1.3 registry at write) + ``enabled_packs`` (validated against the M3.3 pack catalog),
``discovery_strategy`` (M6), ``source_profile_ref`` (M4), ``scoring_rubric`` (M3.4). M3.1 stores the
latter three opaquely; their owners define the internals.

Append-only is enforced by a BEFORE-UPDATE trigger: only ``status`` may change on an existing row
(draft -> active -> archived); every other column is immutable (edit by inserting a new version). A
partial unique index guarantees at most one ``active`` version per (client_id, icp_key).

Enums mirror core.enums (ICPStatus / ICPCreatedFrom); the enum-parity test guards drift.

NOTE (integration): the M2 identity worktree is developed in parallel and also adds migrations from
0005; merging the branches will require renumbering this chain. Kept sequential within this branch.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.core.enums (ICPStatus / ICPCreatedFrom). The enum-parity test
# tests/icp/test_icp_spec.py::test_icp_spec_enums_match_core guards against drift.
_ICP_STATUS = ("draft", "active", "archived")
_ICP_CREATED_FROM = ("synthesis", "client_edit", "import_rederive")

# Columns immutable once written (everything except status). The append-only guard rejects an UPDATE
# touching any of them — edit by inserting a new version.
_IMMUTABLE = (
    "client_id",
    "icp_key",
    "version",
    "created_from",
    "parent_version",
    "label",
    "description",
    "field_keys",
    "enabled_packs",
    "discovery_strategy",
    "source_profile_ref",
    "scoring_rubric",
    "created_by",
    "created_at",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _guard_function_sql() -> str:
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in _IMMUTABLE)
    return f"""
        CREATE OR REPLACE FUNCTION icp_spec_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'icp_spec is append-only: only status may change; '
                    'edit by inserting a new version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    op.execute(f"CREATE TYPE icp_status AS ENUM ({_enum_values_sql(_ICP_STATUS)})")
    op.execute(f"CREATE TYPE icp_created_from AS ENUM ({_enum_values_sql(_ICP_CREATED_FROM)})")

    op.execute(
        """
        CREATE TABLE icp_spec (
            client_id          text NOT NULL,
            icp_key            text NOT NULL,
            version            int NOT NULL,
            status             icp_status NOT NULL DEFAULT 'draft',
            created_from       icp_created_from NOT NULL,
            parent_version     int,
            label              text,
            description        text,
            field_keys         jsonb NOT NULL DEFAULT '[]'::jsonb,
            enabled_packs      jsonb NOT NULL DEFAULT '[]'::jsonb,
            discovery_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_profile_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
            scoring_rubric     jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_by         text,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT icp_spec_pkey PRIMARY KEY (client_id, icp_key, version),
            CONSTRAINT icp_spec_version_positive CHECK (version >= 1),
            CONSTRAINT icp_spec_parent_before_self
                CHECK (parent_version IS NULL OR parent_version < version),
            CONSTRAINT icp_spec_field_keys_is_array CHECK (jsonb_typeof(field_keys) = 'array'),
            CONSTRAINT icp_spec_enabled_packs_is_array CHECK (jsonb_typeof(enabled_packs) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE icp_spec IS 'Versioned ICP spec (staged-flow §2; M3.1), keyed "
        "(client_id, icp_key, version). Append-only: active is immutable, edits append a version, "
        "activation archives the prior. The single contract M3.2/M3.4 read.'"
    )

    # At most one active version per (client_id, icp_key) (D5: many icp_keys per client coexist).
    op.execute(
        "CREATE UNIQUE INDEX icp_spec_one_active ON icp_spec (client_id, icp_key) "
        "WHERE status = 'active'"
    )
    # multi-ICP listing / lineage reads.
    op.execute("CREATE INDEX icp_spec_client ON icp_spec (client_id)")

    # Append-only guard: only status may change on an existing row.
    op.execute(_guard_function_sql())
    op.execute(
        "CREATE TRIGGER icp_spec_immutable BEFORE UPDATE ON icp_spec "
        "FOR EACH ROW EXECUTE FUNCTION icp_spec_reject_immutable_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS icp_spec_immutable ON icp_spec")
    op.execute("DROP FUNCTION IF EXISTS icp_spec_reject_immutable_update()")
    op.execute("DROP INDEX IF EXISTS icp_spec_client")
    op.execute("DROP INDEX IF EXISTS icp_spec_one_active")
    op.execute("DROP TABLE IF EXISTS icp_spec")
    op.execute("DROP TYPE IF EXISTS icp_created_from")
    op.execute("DROP TYPE IF EXISTS icp_status")
