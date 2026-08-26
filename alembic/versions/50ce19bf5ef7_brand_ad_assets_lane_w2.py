"""brand ad assets lane (W2)

Revision ID: 50ce19bf5ef7
Revises: db145059253b
Create Date: 2026-08-26

The durable substrate for the Brand Ad Assets lane
(``subsystems/clue-design/docs/brand-ad-assets-v1-spec.md`` §4, workstream W2). Three artifact
kinds, three tables, plus one new value on an existing enum:

* ``design_ad_creative`` — one harvested reference creative. The BYTES are not here: each row
  points at a ``design_asset`` registry row, exactly as every other design artifact does, so
  the harvest's images are servable, placeable and GC-able through the machinery that already
  owns design bytes. What IS here is the provenance the asset record alone cannot carry as a
  queryable fact: the ad id, the library detail link, the advertiser page, the provider and
  the fetch time (spec §4.1). ``creative_id`` is content-derived from the creative URL — the
  same key the de-duplication compared — so re-running a harvest converges on the same rows
  instead of accumulating a second copy of every creative. Content-derived ⇒ workspace-local
  (migration ``cf4f80537c8e``'s ruling), hence the composite primary key.

* ``design_ad_dna_card`` — the versioned ad-DNA card (spec §4.2). Keyed
  ``(card_id, version)`` and IMMUTABLE, in the same spirit as ``design_brand_kit`` but one
  step stronger: brand kits are immutable by DAL convention, and this table's UPDATE/DELETE
  are refused by trigger (the ``design_web_publish_revision`` pattern). A distilled card is a
  claim about what a brand's creative system looked like at a moment in time; editing one in
  place would silently rewrite the input every ad turn since has been conditioned on.
  ``card_json`` holds the named visual systems in plain language; the composite FK pins the
  brand-kit version the card was distilled for.

* ``design_ad_pregenerated_asset`` — the link from one card VERSION to the imagery generated
  from it (spec §4.3), carrying which named visual system asked for it and the prompt that
  produced it. Deleting a card version takes its links with it (``ON DELETE CASCADE``) and
  leaves the assets themselves alone: the imagery is ordinary library-asset custody, and the
  link is the only thing that was ever about the card.

* ``design_ingestion_kind`` gains ``ad_assets``. The lane's onboarding job rides
  ``design_ingestion_job``, so it inherits fleet dispatch, the lease/generation fence, stage
  reporting and the stranded-work reaper rather than growing a second copy of each. The value
  is APPENDED because ``tests/design/test_design_schema_db::test_design_enum_parity`` asserts
  label order against ``clue_design.enums`` lock-step.

The enum change is done by RENAME-AND-RECREATE rather than ``ALTER TYPE … ADD VALUE``, in both
directions. ``ADD VALUE`` has no inverse, so a downgrade would have had to do this dance
anyway; doing it both ways keeps ``upgrade`` and ``downgrade`` the same shape and sidesteps
the "a new enum value cannot be used in the transaction that added it" rule entirely.

Nothing in this migration is read or written while ``LUMEN_BRAND_AD_ASSETS`` is off: the flag
gates the only entrypoint that creates an ``ad_assets`` job, and no other code path touches
these tables. Applying it to a deployment with the flag off is a pure schema addition.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50ce19bf5ef7"
down_revision: str | None = "db145059253b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums.DesignIngestionKind (parity-tested in tests/design/).
_INGESTION_KIND_WITH_AD_ASSETS = ("website", "pdf", "asset_upload", "ad_assets")
_INGESTION_KIND_BEFORE = ("website", "pdf", "asset_upload")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _rebuild_ingestion_kind(values: tuple[str, ...]) -> None:
    """Swap ``design_ingestion_kind`` for a type with exactly ``values``, in place.

    The column is converted through ``text`` because a direct enum-to-enum cast has no
    implicit path. A row whose kind is not in the target vocabulary fails the cast loudly,
    which is the correct behaviour for the downgrade: it means live ad-assets jobs exist and
    dropping the value would erase what they are.
    """
    op.execute("ALTER TYPE design_ingestion_kind RENAME TO design_ingestion_kind_old")
    op.execute(f"CREATE TYPE design_ingestion_kind AS ENUM ({_enum_values_sql(values)})")
    op.execute(
        "ALTER TABLE design_ingestion_job ALTER COLUMN kind TYPE design_ingestion_kind "
        "USING kind::text::design_ingestion_kind"
    )
    op.execute("DROP TYPE design_ingestion_kind_old")


def upgrade() -> None:
    _rebuild_ingestion_kind(_INGESTION_KIND_WITH_AD_ASSETS)

    # --- design_ad_creative: harvested reference creatives + provenance ----------------------
    op.execute(
        """
        CREATE TABLE design_ad_creative (
            creative_id   text NOT NULL,
            workspace_id  text NOT NULL,
            harvest_job_id text NOT NULL,
            provider      text NOT NULL,
            ad_id         text NOT NULL,
            advertiser_name    text,
            advertiser_page_id text,
            creative_url  text NOT NULL,
            view_details_link text,
            headline      text,
            commentary    text,
            asset_id      text NOT NULL,
            fetched_at    timestamptz NOT NULL,
            provenance_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_ad_creative_pkey PRIMARY KEY (creative_id, workspace_id),
            CONSTRAINT design_ad_creative_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_ad_creative_job_fk FOREIGN KEY (harvest_job_id)
                REFERENCES design_ingestion_job (job_id) ON DELETE CASCADE,
            -- The bytes live in the asset registry, structurally in this creative's own
            -- workspace: one tenant's harvest can never cite another's asset row.
            CONSTRAINT design_ad_creative_asset_fk FOREIGN KEY (asset_id, workspace_id)
                REFERENCES design_asset (asset_id, workspace_id),
            CONSTRAINT design_ad_creative_provenance_object
                CHECK (jsonb_typeof(provenance_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_ad_creative IS 'Harvested reference ad creatives (Brand Ad "
        "Assets v1 §4.1). Bytes live in design_asset; this row carries the provenance that "
        "re-finds the published ad after its CDN link expires. creative_id is derived from "
        "the creative URL — the dedupe key — so a re-run converges instead of duplicating.'"
    )
    op.execute(
        "CREATE INDEX design_ad_creative_job "
        "ON design_ad_creative (workspace_id, harvest_job_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX design_ad_creative_advertiser "
        "ON design_ad_creative (workspace_id, advertiser_page_id, fetched_at DESC)"
    )

    # --- design_ad_dna_card: the versioned, immutable ad-DNA card ----------------------------
    op.execute(
        """
        CREATE TABLE design_ad_dna_card (
            card_id      text NOT NULL,
            version      integer NOT NULL,
            workspace_id text NOT NULL,
            brand_kit_id text NOT NULL,
            brand_kit_version integer NOT NULL,
            harvest_job_id text,
            model        text,
            card_json    jsonb NOT NULL,
            source_creative_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_ad_dna_card_pkey PRIMARY KEY (card_id, version),
            CONSTRAINT design_ad_dna_card_version_positive CHECK (version >= 1),
            CONSTRAINT design_ad_dna_card_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_ad_dna_card_brand_kit_fk
                FOREIGN KEY (brand_kit_id, brand_kit_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id),
            CONSTRAINT design_ad_dna_card_job_fk FOREIGN KEY (harvest_job_id)
                REFERENCES design_ingestion_job (job_id) ON DELETE SET NULL,
            -- Composite-FK anchor for the pre-generated-asset links below.
            CONSTRAINT design_ad_dna_card_workspace_anchor
                UNIQUE (card_id, version, workspace_id),
            CONSTRAINT design_ad_dna_card_json_object
                CHECK (jsonb_typeof(card_json) = 'object'),
            CONSTRAINT design_ad_dna_card_sources_array
                CHECK (jsonb_typeof(source_creative_ids) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_ad_dna_card IS 'The versioned ad-DNA card (Brand Ad Assets "
        "v1 §4.2): named visual systems in plain language, distilled once per harvest. Keyed "
        "(card_id, version); UPDATE and DELETE are refused by trigger, because every ad turn "
        "conditioned on a version must keep seeing the version it was conditioned on. Born "
        "active — there is no approval gate (ruling D5).'"
    )
    op.execute(
        """
        CREATE FUNCTION design_ad_dna_card_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_ad_dna_card is immutable: an ad-DNA card version is what ad turns '
                'were conditioned on. Distil a new version instead of editing one.';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION design_ad_dna_card_reject_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_ad_dna_card is append-only: card versions are the lane''s history.';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER design_ad_dna_card_no_update BEFORE UPDATE ON design_ad_dna_card "
        "FOR EACH ROW EXECUTE FUNCTION design_ad_dna_card_reject_update()"
    )
    op.execute(
        "CREATE TRIGGER design_ad_dna_card_no_delete BEFORE DELETE ON design_ad_dna_card "
        "FOR EACH ROW EXECUTE FUNCTION design_ad_dna_card_reject_delete()"
    )
    op.execute(
        "CREATE INDEX design_ad_dna_card_brand_kit "
        "ON design_ad_dna_card (workspace_id, brand_kit_id, version DESC)"
    )

    # --- design_ad_pregenerated_asset: card version -> generated imagery ---------------------
    op.execute(
        """
        CREATE TABLE design_ad_pregenerated_asset (
            card_id      text NOT NULL,
            card_version integer NOT NULL,
            asset_id     text NOT NULL,
            workspace_id text NOT NULL,
            visual_system text NOT NULL,
            prompt       text NOT NULL,
            generation_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_ad_pregenerated_asset_pkey
                PRIMARY KEY (card_id, card_version, asset_id),
            CONSTRAINT design_ad_pregenerated_asset_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_ad_pregenerated_asset_card_fk
                FOREIGN KEY (card_id, card_version, workspace_id)
                REFERENCES design_ad_dna_card (card_id, version, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_ad_pregenerated_asset_asset_fk
                FOREIGN KEY (asset_id, workspace_id)
                REFERENCES design_asset (asset_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_ad_pregenerated_asset_generation_object
                CHECK (jsonb_typeof(generation_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_ad_pregenerated_asset IS 'Links one ad-DNA card VERSION to "
        "the imagery pre-generated from it (Brand Ad Assets v1 §4.3), with the named visual "
        "system that asked for it and the prompt that produced it. The assets themselves are "
        "ordinary library assets — this table is only the link.'"
    )
    op.execute(
        "CREATE INDEX design_ad_pregenerated_asset_system "
        "ON design_ad_pregenerated_asset (workspace_id, card_id, card_version, visual_system)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_ad_pregenerated_asset")
    op.execute("DROP TRIGGER design_ad_dna_card_no_delete ON design_ad_dna_card")
    op.execute("DROP TRIGGER design_ad_dna_card_no_update ON design_ad_dna_card")
    op.execute("DROP TABLE design_ad_dna_card")
    op.execute("DROP FUNCTION design_ad_dna_card_reject_delete")
    op.execute("DROP FUNCTION design_ad_dna_card_reject_update")
    op.execute("DROP TABLE design_ad_creative")
    # Any surviving ad_assets job would fail this cast loudly rather than being silently
    # relabelled — which is the honest outcome: the value cannot be dropped while it is in use.
    _rebuild_ingestion_kind(_INGESTION_KIND_BEFORE)
