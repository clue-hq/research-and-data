"""source_manifest — the source registry (M4.2 / ENG-111)

Revision ID: b9c6d72ac860
Revises: 0011
Create Date: 2026-06-20

Sibling registry to ``field_definition`` (M1.3): fields say *what to know*; a ``source_manifest``
row says *where to learn it and how much to trust each place* (staged-flow §7a; conventions §4). A
source is a row — adding Clay, dropping ZoomInfo, or wiring a new directory is a registry edit, and
**nothing downstream learns a provider's name** (everything references a source by ``source_key``).

Columns realize :class:`clue_research.core.SourceManifest` (the M0.2 capability contract — the
scalar ``cost_cents``/``latency_ms``/``freshness_profile`` shape, NOT re-introducing §7a's looser
jsonb cost, which would contradict core) **plus** the registry-row operational metadata (locked
decision #2 — *wrap, don't redefine*): ``active``, ``provider`` (vendor/human name, for billing/ops
ONLY — never branched on by callers), ``auth_ref`` (a reference into the credential store, **never**
the secret itself), ``rate_limit``, ``requires_adapter`` (M4.3 modality-adapter key), ``version``,
``created_at``.

Enums: ``modality`` and ``entity_scope`` are NEW types created here (mirroring
``clue_research.core.enums.Modality`` / ``EntityScope``; the parity test guards drift).
``identity_binding`` is REUSED (created in 0004) — a shared type, so ``downgrade`` does not drop it.
``yields`` references ``field_definition`` field-keys/classes BY NAME (the registry validates
existence at ``register_source`` time; no FK — a field-class like ``contact`` is not a row).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c6d72ac860"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.core.enums.Modality / EntityScope. The enum-parity test in
# tests/sources/test_source_manifest.py guards these against drift (as 0002/0003/0004 do).
_MODALITY = ("text", "video", "audio", "pdf", "structured")
_ENTITY_SCOPE = ("account", "contact", "both")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE modality AS ENUM ({_enum_values_sql(_MODALITY)})")
    op.execute(f"CREATE TYPE entity_scope AS ENUM ({_enum_values_sql(_ENTITY_SCOPE)})")

    op.execute(
        """
        CREATE TABLE source_manifest (
            source_key                text PRIMARY KEY,
            modality                  modality NOT NULL,
            entity_scope              entity_scope NOT NULL,
            yields                    jsonb NOT NULL DEFAULT '[]'::jsonb,
            tier                      int NOT NULL,
            cost_cents                numeric NOT NULL DEFAULT 0,
            latency_ms                int,
            geo_coverage              jsonb NOT NULL DEFAULT '[]'::jsonb,
            freshness_profile         text,
            identity_binding_strength identity_binding,
            active                    boolean NOT NULL DEFAULT true,
            provider                  text,
            auth_ref                  text,
            rate_limit                jsonb,
            requires_adapter          text,
            version                   int NOT NULL DEFAULT 1,
            created_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT source_manifest_tier_range CHECK (tier BETWEEN 1 AND 4),
            CONSTRAINT source_manifest_cost_nonneg CHECK (cost_cents >= 0),
            CONSTRAINT source_manifest_latency_nonneg
                CHECK (latency_ms IS NULL OR latency_ms >= 0),
            CONSTRAINT source_manifest_version_positive CHECK (version >= 1),
            CONSTRAINT source_manifest_yields_is_array
                CHECK (jsonb_typeof(yields) = 'array'),
            CONSTRAINT source_manifest_geo_is_array
                CHECK (jsonb_typeof(geo_coverage) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE source_manifest IS 'The source registry (staged-flow §7a; M4.2): every "
        "source is a row, referenced only by source_key. Realizes core.SourceManifest + registry "
        "metadata (decision #2). provider is for billing/ops only (never branched on); auth_ref is "
        "a credential-store reference, never the secret. Open by registration, not enumeration.'"
    )

    # read-path indexes: sources_for filters by yields-membership (GIN), tier, and active.
    op.execute("CREATE INDEX source_manifest_yields_gin ON source_manifest USING gin (yields)")
    op.execute("CREATE INDEX source_manifest_tier ON source_manifest (tier)")
    op.execute("CREATE INDEX source_manifest_active ON source_manifest (source_key) WHERE active")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS source_manifest_active")
    op.execute("DROP INDEX IF EXISTS source_manifest_tier")
    op.execute("DROP INDEX IF EXISTS source_manifest_yields_gin")
    op.execute("DROP TABLE IF EXISTS source_manifest")
    # modality / entity_scope are owned here; identity_binding is shared (0004) — leave it.
    op.execute("DROP TYPE IF EXISTS entity_scope")
    op.execute("DROP TYPE IF EXISTS modality")
