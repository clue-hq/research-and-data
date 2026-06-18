"""pack catalog + source_profile — industry packs as data (M3.3 / ENG-115)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19

Promote staged-flow §9's two-part "pack" to first-class, versioned catalog rows (conventions §2 —
policy is data, not code; open by registration, not enumeration). A pack carries *two prior sets*:
a field set ("what to know") and a source profile ("where to look").

* ``pack`` — the catalog of industry packs. A pack has a ``pack_key`` (e.g. ``healthcare_practice``)
  and a field-key ``namespace`` (e.g. ``healthcare``); the two differ on purpose (conventions §3).
  The *field-set half* is authored into ``field_definition`` (M1.3) under that namespace
  (``field_definition.pack`` = the namespace, NOT the pack_key — so no FK between them). This table
  records the pack itself, so a vertical is open-by-registration and a typo namespace is
  distinguishable from a known pack.
* ``source_profile`` — the *source-profile half* (staged-flow §7c/§9): per pack, optionally per
  field-class, an ordered/weighted set of ``source_key``s. ``source_key``s reference M4's
  ``source_manifest`` namespace **by name only** (M3.3 stores references; M4 owns the manifests —
  exactly as ``field_definition.tier_plan`` references resolvers by name; the join is M4's).
* ``source_profile_override`` — per-client / per-ICP overrides of a pack's source profile
  (override > pack default; staged-flow §7c "overridable per client"), versioned + append-only so a
  campaign pinned to a prior version re-reads identically; M13's learning loop writes it.

Reuses the M1.3 ``field_class`` enum — no new enum type, nothing to keep in lock-step with core.
``weighted_sources`` is JSONB (``[{"source_key", "weight", "rank"}, …]``) so the weight vocabulary
and the M13 reweighting knobs evolve without a schema change. A nullable ``field_class`` means a
*pack-wide default* slot; the unique indexes use ``NULLS NOT DISTINCT`` (pg15+) so a NULL
``field_class`` / ``icp_key`` is one slot, not many (a plain UNIQUE treats NULLs as distinct).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- pack catalog -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE pack (
            pack_key    text PRIMARY KEY,
            namespace   text NOT NULL,
            title       text NOT NULL,
            description text,
            active      boolean NOT NULL DEFAULT true,
            version     int NOT NULL DEFAULT 1,
            created_at  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT pack_version_positive CHECK (version >= 1),
            CONSTRAINT pack_namespace_format CHECK (namespace ~ '^[a-z][a-z0-9_]*$')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE pack IS 'Industry-pack catalog (staged-flow §9; M3.3). pack_key vs "
        "field-key namespace differ (conventions §3). field_definition.pack stores the namespace; "
        "open by registration, not enumeration.'"
    )

    # --- source_profile (pack default; the source-profile half) -------------
    # weighted_sources references source_manifest.source_key by name (M4 owns the manifest). A NULL
    # field_class is the pack-wide default slot.
    op.execute(
        """
        CREATE TABLE source_profile (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pack_key         text NOT NULL REFERENCES pack (pack_key),
            field_class      field_class,
            weighted_sources jsonb NOT NULL,
            version          int NOT NULL DEFAULT 1,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT source_profile_version_positive CHECK (version >= 1),
            CONSTRAINT source_profile_weighted_is_array
                CHECK (jsonb_typeof(weighted_sources) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE source_profile IS 'Source-profile half of a pack (staged-flow §7c/§9): "
        "weighted source_key priors per (pack, field_class). source_key references M4 by name; "
        "versioned + append-only (policy-as-data, D7).'"
    )

    # --- source_profile_override (per-client / per-ICP; override > default) --
    op.execute(
        """
        CREATE TABLE source_profile_override (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            pack_key         text NOT NULL REFERENCES pack (pack_key),
            field_class      field_class,
            client_id        text NOT NULL,
            icp_key          text,
            weighted_sources jsonb NOT NULL,
            version          int NOT NULL DEFAULT 1,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT source_profile_override_version_positive CHECK (version >= 1),
            CONSTRAINT source_profile_override_weighted_is_array
                CHECK (jsonb_typeof(weighted_sources) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE source_profile_override IS 'Per-client/per-ICP override of a pack "
        "source profile (override > pack default; staged-flow §7c). icp_key NULL = client-wide. "
        "Versioned + append-only; M13 writes it (the base pack profile stays unchanged).'"
    )

    # --- unique slots: NULLS NOT DISTINCT (pg15+) so a NULL field_class / icp_key is ONE slot,
    # not many (a plain UNIQUE treats NULLs as distinct). Avoids a non-IMMUTABLE enum->text cast in
    # an index expression.
    op.execute(
        "CREATE UNIQUE INDEX source_profile_slot ON source_profile "
        "(pack_key, field_class, version) NULLS NOT DISTINCT"
    )
    op.execute(
        "CREATE UNIQUE INDEX source_profile_override_slot ON source_profile_override "
        "(pack_key, field_class, client_id, icp_key, version) NULLS NOT DISTINCT"
    )

    # --- read-path indexes --------------------------------------------------
    op.execute("CREATE INDEX pack_active ON pack (pack_key) WHERE active")
    op.execute("CREATE INDEX source_profile_pack ON source_profile (pack_key)")
    op.execute(
        "CREATE INDEX source_profile_override_lookup "
        "ON source_profile_override (pack_key, client_id)"
    )
    op.execute(
        "CREATE INDEX source_profile_weighted_gin ON source_profile USING gin (weighted_sources)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS source_profile_weighted_gin")
    op.execute("DROP INDEX IF EXISTS source_profile_override_lookup")
    op.execute("DROP INDEX IF EXISTS source_profile_pack")
    op.execute("DROP INDEX IF EXISTS pack_active")
    op.execute("DROP INDEX IF EXISTS source_profile_override_slot")
    op.execute("DROP INDEX IF EXISTS source_profile_slot")
    # children (FK to pack) before the parent.
    op.execute("DROP TABLE IF EXISTS source_profile_override")
    op.execute("DROP TABLE IF EXISTS source_profile")
    op.execute("DROP TABLE IF EXISTS pack")
