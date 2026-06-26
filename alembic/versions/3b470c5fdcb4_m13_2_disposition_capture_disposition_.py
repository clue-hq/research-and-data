"""m13.2 disposition capture (disposition + disposition_provenance + labeled_dataset view)

Revision ID: 3b470c5fdcb4
Revises: c48ebe0a1e62
Create Date: 2026-06-26 01:03:42.049998+00:00

M13.2 normalizes every feedback signal — internal Tier-1 review actions (M13.1) and downstream
client sales outcomes (CRM-read / webhook / manual) — into one append-only, idempotent
``disposition`` row (the labeled-training-data substrate the M13.3 learning loop reads). This adds:

* three enums — ``disposition_type`` / ``disposition_actor`` / ``disposition_origin`` — mirroring
  the ``clue_research.review.disposition`` ``StrEnum``s (parity-tested in
  ``tests/review/test_disposition_db.py``, the same discipline as the M13.1 review enums). The
  ``entity_type`` enum is **reused** from 0002 (no new enum, no extra parity burden, and the
  downgrade leaves the shared type alone — mirroring how ``source_yield`` reuses ``field_class``).

* ``disposition`` — one row per captured signal, keyed on a **resolved** ``entity_id`` (account or
  contact) with an ``account_entity_id`` rollup, the ``(client_id, icp_key, icp_spec_version)``
  scope (D5: version restarts per ``icp_key``), and ``natural_key`` UNIQUE (the idempotency anchor —
  ``record`` is ``ON CONFLICT (natural_key) DO NOTHING``). **Append-only except the erasure
  marker**: a BEFORE-UPDATE guard rejects any update touching a column other than ``tombstoned_at``
  (mirrors the ``icp_spec`` immutable guard), so M10.5 erasure can *stamp* ``tombstoned_at``
  (audited, never a hard delete) while the row's value stays immutable. Soft FKs (no ``REFERENCES``)
  like ``claim`` / ``review_action`` — integrity is enforced in the write path so milestone
  migrations stay order-independent.

* ``disposition_provenance`` — the 1:1 frozen snapshot of which sources/fields/claims fed the
  account at handoff time (the M12.2 provenance index re-resolved to ``source_key``/``field_key``
  arrays), captured at ``record`` time so a later config change can't rewrite history (§M13.2 AC3).

* ``labeled_dataset`` — the **read view** M13.3 consumes (the repo's first SQL VIEW): one row per
  disposition joining its outcome label to the account's decomposed Pass-A fit/intent score
  snapshots (M6, tenant-scoped + version-matched), the frozen contributing-source provenance, and
  the ICP spec (M3). Scoped by ``(client_id + icp_key + icp_spec_version)`` and ``WHERE
  tombstoned_at IS NULL`` so erased rows leave the training set; reproducible + append-only (the
  disposition row set only grows).

``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b470c5fdcb4"
down_revision: str | None = "c48ebe0a1e62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.review.disposition (DispositionType / DispositionActor / DispositionOrigin).
# tests/review/test_disposition_db.py guards parity with the Python StrEnums.
_DISPOSITION_TYPE = (
    "claim_approved",
    "claim_corrected",
    "claim_rejected",
    "account_accepted",
    "account_rejected",
    "account_contacted",
    "reply_received",
    "meeting_booked",
    "closed_won",
    "closed_lost",
)
_DISPOSITION_ACTOR = ("internal_reviewer", "client_sales", "system")
_DISPOSITION_ORIGIN = ("review_surface", "crm_ingest", "webhook", "manual")

# Every column immutable once written, except the erasure marker ``tombstoned_at`` (M10.5 may stamp
# it). The guard rejects an UPDATE touching any of these — edit/erase only via tombstoning.
_IMMUTABLE = (
    "id",
    "disposition_type",
    "entity_id",
    "entity_type",
    "account_entity_id",
    "claim_id",
    "campaign_run_id",
    "client_id",
    "icp_key",
    "icp_spec_version",
    "actor",
    "origin",
    "review_action_id",
    "reason_code",
    "detail",
    "occurred_at",
    "recorded_at",
    "natural_key",
    "created_at",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _immutable_guard_sql() -> str:
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in _IMMUTABLE)
    return f"""
        CREATE FUNCTION disposition_reject_value_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'disposition is append-only: only tombstoned_at may change (M10.5 erasure)';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    # 1. enums (mirror core review.disposition StrEnums; entity_type reused from 0002) -----------
    op.execute(f"CREATE TYPE disposition_type AS ENUM ({_enum_values_sql(_DISPOSITION_TYPE)})")
    op.execute(f"CREATE TYPE disposition_actor AS ENUM ({_enum_values_sql(_DISPOSITION_ACTOR)})")
    op.execute(f"CREATE TYPE disposition_origin AS ENUM ({_enum_values_sql(_DISPOSITION_ORIGIN)})")

    # 2. disposition: the normalized feedback record --------------------------------------------
    op.execute(
        """
        CREATE TABLE disposition (
            id                uuid NOT NULL,
            disposition_type  disposition_type NOT NULL,
            entity_id         uuid NOT NULL,
            entity_type       entity_type NOT NULL,
            account_entity_id uuid NOT NULL,
            claim_id          uuid,
            campaign_run_id   uuid,
            client_id         text NOT NULL,
            icp_key           text NOT NULL DEFAULT '',
            icp_spec_version  int,
            actor             disposition_actor NOT NULL,
            origin            disposition_origin NOT NULL,
            review_action_id  uuid,
            reason_code       text,
            detail            jsonb,
            occurred_at       timestamptz NOT NULL,
            recorded_at       timestamptz NOT NULL DEFAULT now(),
            tombstoned_at     timestamptz,
            natural_key       text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT disposition_pkey PRIMARY KEY (id),
            -- The idempotency anchor: at most one disposition per natural_key (review-origin =
            -- review_action_id; downstream = origin:client:external_id:type).
            -- record() does ON CONFLICT DO NOTHING.
            CONSTRAINT disposition_natural_key_uniq UNIQUE (natural_key),
            CONSTRAINT disposition_icp_version_positive
                CHECK (icp_spec_version IS NULL OR icp_spec_version >= 1),
            -- A claim_* disposition carries the reviewed claim; an account-level one does not.
            CONSTRAINT disposition_claim_iff_claim_type CHECK (
                (disposition_type IN ('claim_approved', 'claim_corrected', 'claim_rejected'))
                = (claim_id IS NOT NULL)
            ),
            -- Review-origin mirrors a review_action audit row; the other origins never do.
            CONSTRAINT disposition_review_action_iff_review CHECK (
                (origin = 'review_surface') = (review_action_id IS NOT NULL)
            ),
            -- An account-typed disposition's entity IS its account (the rollup is itself).
            CONSTRAINT disposition_account_entity_self CHECK (
                entity_type <> 'account' OR entity_id = account_entity_id
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE disposition IS 'M13.2 normalized feedback record (substrate §9/§10): one "
        "row per Tier-1 review action (M13.1) or downstream sales outcome, keyed on a resolved "
        "entity_id (+ account_entity_id rollup) and (client_id, icp_key, icp_spec_version) scope. "
        "Append-only except tombstoned_at (M10.5 erasure marker); idempotent on natural_key. The "
        "labeled training-data substrate M13.3 reads via the labeled_dataset view.'"
    )

    # Read paths: the dataset/source rollup (by account), the tombstone cascade (by contact), the
    # dataset scoping (by ICP segment+version), per-run reads, and the review-action mirror lookup.
    op.execute("CREATE INDEX disposition_account ON disposition (account_entity_id)")
    op.execute("CREATE INDEX disposition_entity ON disposition (entity_id, entity_type)")
    op.execute(
        "CREATE INDEX disposition_scope ON disposition (client_id, icp_key, icp_spec_version)"
    )
    op.execute("CREATE INDEX disposition_run ON disposition (campaign_run_id)")
    op.execute(
        "CREATE INDEX disposition_review_action ON disposition (review_action_id) "
        "WHERE review_action_id IS NOT NULL"
    )

    # Append-only-except-erasure guard (mirrors icp_spec's immutable guard): only tombstoned_at may
    # change on an existing row, so M10.5 can tombstone but the captured signal never mutates.
    op.execute(_immutable_guard_sql())
    op.execute(
        "CREATE TRIGGER disposition_immutable BEFORE UPDATE ON disposition "
        "FOR EACH ROW EXECUTE FUNCTION disposition_reject_value_update()"
    )

    # 3. disposition_provenance: the 1:1 frozen contributing-source snapshot --------------------
    op.execute(
        """
        CREATE TABLE disposition_provenance (
            disposition_id           uuid NOT NULL,
            contributing_source_keys text[] NOT NULL DEFAULT '{}',
            contributing_field_keys  text[] NOT NULL DEFAULT '{}',
            contributing_claim_ids   text[] NOT NULL DEFAULT '{}',
            snapshot_at              timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT disposition_provenance_pkey PRIMARY KEY (disposition_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE disposition_provenance IS 'M13.2 1:1 frozen snapshot of which sources / "
        "fields / claims contributed to a disposition''s account at handoff time (the M12.2 "
        "provenance index re-resolved to source_key/field_key via claims_by_ids — ProvenanceRef "
        "carries neither). Captured at record() time so config changes cannot rewrite history "
        "(spec §M13.2 AC3). Soft FK on disposition_id (write-path integrity).'"
    )

    # 4. labeled_dataset: the read view M13.3 consumes (the repo's first SQL VIEW) ---------------
    # One row per disposition × its frozen provenance × the account's Pass-A fit/intent score
    # snapshots (M6, tenant-private + matched on the value_json's (icp_version, icp_key) — D5) × the
    # ICP spec (M3). LEFT JOINs so a disposition with no handoff/score still appears (label only).
    # tombstoned rows are excluded (M10.5). Reproducible + append-only: keyed on disposition_id, the
    # row set only grows; features reflect the current winning score claim for the pinned version.
    op.execute(
        """
        CREATE VIEW labeled_dataset AS
        SELECT
            d.id                AS disposition_id,
            d.disposition_type  AS disposition_type,
            d.actor             AS actor,
            d.origin            AS origin,
            d.entity_id         AS entity_id,
            d.entity_type       AS entity_type,
            d.account_entity_id AS account_entity_id,
            d.claim_id          AS claim_id,
            d.campaign_run_id   AS campaign_run_id,
            d.client_id         AS client_id,
            d.icp_key           AS icp_key,
            d.icp_spec_version  AS icp_spec_version,
            d.occurred_at       AS occurred_at,
            d.recorded_at       AS recorded_at,
            COALESCE(dp.contributing_source_keys, '{}') AS contributing_source_keys,
            COALESCE(dp.contributing_field_keys, '{}')  AS contributing_field_keys,
            COALESCE(dp.contributing_claim_ids, '{}')   AS contributing_claim_ids,
            fit.value_json      AS fit_score_json,
            intent.value_json   AS intent_score_json,
            spec.scoring_rubric AS scoring_rubric,
            spec.label          AS icp_label
        FROM disposition d
        LEFT JOIN disposition_provenance dp ON dp.disposition_id = d.id
        LEFT JOIN LATERAL (
            SELECT c.value_json
            FROM claim c
            WHERE c.entity_id = d.account_entity_id
              AND c.field_key = 'account.scoring.fit'
              AND c.superseded_by IS NULL
              AND c.reuse_scope = 'tenant_private'
              AND c.tenant_id = d.client_id
              AND d.icp_spec_version IS NOT NULL
              AND c.value_json ->> 'icp_version' = d.icp_spec_version::text
              AND c.value_json ->> 'icp_key' = d.icp_key
            ORDER BY c.collected_at DESC
            LIMIT 1
        ) fit ON true
        LEFT JOIN LATERAL (
            SELECT c.value_json
            FROM claim c
            WHERE c.entity_id = d.account_entity_id
              AND c.field_key = 'account.scoring.intent'
              AND c.superseded_by IS NULL
              AND c.reuse_scope = 'tenant_private'
              AND c.tenant_id = d.client_id
              AND d.icp_spec_version IS NOT NULL
              AND c.value_json ->> 'icp_version' = d.icp_spec_version::text
              AND c.value_json ->> 'icp_key' = d.icp_key
            ORDER BY c.collected_at DESC
            LIMIT 1
        ) intent ON true
        LEFT JOIN icp_spec spec
            ON spec.client_id = d.client_id
           AND spec.icp_key = d.icp_key
           AND spec.version = d.icp_spec_version
        WHERE d.tombstoned_at IS NULL
        """
    )
    op.execute(
        "COMMENT ON VIEW labeled_dataset IS 'M13.2 training-data export (spec §M13.2): one row per "
        "disposition joining its outcome label to the account Pass-A fit/intent snapshots (M6), "
        "the frozen contributing-source provenance, and the ICP spec (M3). Scoped by (client_id, "
        "icp_key, icp_spec_version); excludes tombstoned rows (M10.5). The contract M13.3 reads.'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS labeled_dataset")

    op.execute("DROP TABLE IF EXISTS disposition_provenance")

    op.execute("DROP TRIGGER IF EXISTS disposition_immutable ON disposition")
    op.execute("DROP FUNCTION IF EXISTS disposition_reject_value_update()")
    op.execute("DROP INDEX IF EXISTS disposition_review_action")
    op.execute("DROP INDEX IF EXISTS disposition_run")
    op.execute("DROP INDEX IF EXISTS disposition_scope")
    op.execute("DROP INDEX IF EXISTS disposition_entity")
    op.execute("DROP INDEX IF EXISTS disposition_account")
    op.execute("DROP TABLE IF EXISTS disposition")

    op.execute("DROP TYPE IF EXISTS disposition_origin")
    op.execute("DROP TYPE IF EXISTS disposition_actor")
    op.execute("DROP TYPE IF EXISTS disposition_type")
    # entity_type is the shared enum from 0002 — leave it (claim / account_entity / … use it).
