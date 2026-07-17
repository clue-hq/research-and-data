"""workspace_id rename — both ``tenant_id`` and ``client_id`` become ``workspace_id`` (Phase A3.1)

Revision ID: b61cd4887129
Revises: 15b6b816abe4
Create Date: 2026-07-17

The founder-ruled rename (spec ``docs/specs/PA-phase-a-restructure-and-spine.md`` §A3.1):
``tenant_id`` (M2 claim tenancy) and ``client_id`` (M3+ scoping) always named the same concept —
the tenancy root — to the point that the M13.2 ``labeled_dataset`` view literally joins
``c.tenant_id = d.client_id``. This migration collapses both to **``workspace_id``** in one
reversible pass:

* ``ALTER TABLE … RENAME COLUMN`` on all 19 tables (4 × ``tenant_id``, 15 × ``client_id``);
* renames every index/constraint whose *name* carries the old vocabulary (column lists inside
  kept-name indexes — ``claim_scoped_read``, the ``*_scope_version`` NULLS-NOT-DISTINCT slots,
  partial-index WHERE clauses — follow the column rename automatically);
* drops + recreates the ``claim_reuse_scope_tenant`` CHECK as ``claim_reuse_scope_workspace``
  (same expression over ``workspace_id``; the enum *value* ``tenant_private`` is retained — it
  names claim-pooling semantics, not the id);
* recreates the three plpgsql guards whose bodies reference the old column names
  (``claim_reject_immutable_update`` — ``workspace_id`` stays in the immutable list;
  ``icp_spec_reject_immutable_update``; ``disposition_reject_value_update``);
* renames the ``client_policy`` table to ``workspace_policy`` (+ its named constraints/index);
* recreates the ``labeled_dataset`` view: Postgres rewrites the view's internal column
  *references* on RENAME COLUMN, but its **output** columns keep their old aliases
  (``… AS client_id``), so the view must be rebuilt to expose ``workspace_id``.

Historical migrations stay byte-identical (history is never rewritten). ``downgrade()`` mirrors
everything exactly (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b61cd4887129"
down_revision: str | None = "15b6b816abe4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- the 19 column renames -----------------------------------------------------------------------
# All become workspace_id. claim (0008) / identity_review_task (0007) / dsar_tombstone /
# outreach_objected (b56207f907f2) carried tenant_id; the rest carried client_id.
_TENANT_ID_TABLES = ("claim", "identity_review_task", "dsar_tombstone", "outreach_objected")
_CLIENT_ID_TABLES = (
    "icp_spec",
    "source_profile_override",
    "pre_spend_policy",
    "judge_policy",
    "binding_policy",
    "cadence_policy",
    "positioning_policy",
    "client_policy",  # renamed to workspace_policy below (column first, then table)
    "campaign_run",
    "source_yield",
    "account_handoff",
    "handoff_event",
    "disposition",
    "config_revision",
    "review_session",
)

# --- index renames (only names carrying the old vocabulary; kept-name indexes auto-follow) -------
_INDEX_RENAMES = (
    ("icp_spec_client", "icp_spec_workspace"),
    ("campaign_run_client", "campaign_run_workspace"),
    ("handoff_event_client", "handoff_event_workspace"),
    ("account_handoff_client_run", "account_handoff_workspace_run"),
    ("identity_review_task_tenant", "identity_review_task_workspace"),
    ("outreach_objected_tenant", "outreach_objected_workspace"),
)

# --- constraint renames --------------------------------------------------------------------------
# (table, old, new). outreach_objected's is a UNIQUE constraint (renaming it renames its index).
_CONSTRAINT_RENAMES = (
    (
        "outreach_objected",
        "outreach_objected_contact_tenant_unique",
        "outreach_objected_contact_workspace_unique",
    ),
)

# workspace_policy (né client_policy): named constraints + the NULLS NOT DISTINCT slot index.
_POLICY_CONSTRAINT_RENAMES = (
    ("client_policy_pkey", "workspace_policy_pkey"),
    ("client_policy_allow_map_is_object", "workspace_policy_allow_map_is_object"),
    ("client_policy_gather_scope_is_array", "workspace_policy_gather_scope_is_array"),
    ("client_policy_regime_overrides_is_object", "workspace_policy_regime_overrides_is_object"),
    ("client_policy_sensitive_overrides_is_array", "workspace_policy_sensitive_overrides_is_array"),
    ("client_policy_version_positive", "workspace_policy_version_positive"),
)

# --- the claim append-only guard (0002 → 0004 → 0008 → 651b1d7229e2 discipline) ------------------
# Full immutable list at head; this revision renames tenant_id → workspace_id in the M2.5 slot.
_M1_1_IMMUTABLE = (
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
_M1_4_IMMUTABLE = ("identity_binding", "use_class", "discovery_provenance", "claim_flavor")
_M4_1_IMMUTABLE = ("source_key",)
_M2_5_IMMUTABLE_OLD = ("tenant_id", "reuse_scope")
_M2_5_IMMUTABLE_NEW = ("workspace_id", "reuse_scope")
_MUTABLE_COLUMNS = ("superseded_by", "verification_status", "corroborations")


def _claim_guard_sql(m2_5_columns: tuple[str, ...]) -> str:
    columns = _M1_1_IMMUTABLE + _M1_4_IMMUTABLE + m2_5_columns + _M4_1_IMMUTABLE
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in columns)
    allow = ", ".join(_MUTABLE_COLUMNS)
    return f"""
        CREATE OR REPLACE FUNCTION claim_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'claim is append-only: only ({allow}) may be updated; an immutable '
                    'provenance column was modified. Supersede by inserting a new claim.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


# --- the icp_spec append-only guard (0010 discipline; only the id column name changes) -----------
def _icp_spec_guard_sql(id_column: str) -> str:
    columns = (
        id_column,
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
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in columns)
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


# --- the disposition append-only-except-tombstone guard (3b470c5fdcb4 discipline) ----------------
def _disposition_guard_sql(id_column: str) -> str:
    columns = (
        "id",
        "disposition_type",
        "entity_id",
        "entity_type",
        "account_entity_id",
        "claim_id",
        "campaign_run_id",
        id_column,
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
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in columns)
    return f"""
        CREATE OR REPLACE FUNCTION disposition_reject_value_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'disposition is append-only: only tombstoned_at may change (M10.5 erasure)';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


# --- the labeled_dataset view (3b470c5fdcb4) — parameterised on the id column names --------------
def _labeled_dataset_sql(*, id_column: str, claim_id_column: str) -> str:
    return f"""
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
            d.{id_column}       AS {id_column},
            d.icp_key           AS icp_key,
            d.icp_spec_version  AS icp_spec_version,
            d.occurred_at       AS occurred_at,
            d.recorded_at       AS recorded_at,
            COALESCE(dp.contributing_source_keys, '{{}}') AS contributing_source_keys,
            COALESCE(dp.contributing_field_keys, '{{}}')  AS contributing_field_keys,
            COALESCE(dp.contributing_claim_ids, '{{}}')   AS contributing_claim_ids,
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
              AND c.{claim_id_column} = d.{id_column}
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
              AND c.{claim_id_column} = d.{id_column}
              AND d.icp_spec_version IS NOT NULL
              AND c.value_json ->> 'icp_version' = d.icp_spec_version::text
              AND c.value_json ->> 'icp_key' = d.icp_key
            ORDER BY c.collected_at DESC
            LIMIT 1
        ) intent ON true
        LEFT JOIN icp_spec spec
            ON spec.{id_column} = d.{id_column}
           AND spec.icp_key = d.icp_key
           AND spec.version = d.icp_spec_version
        WHERE d.tombstoned_at IS NULL
    """


_VIEW_COMMENT_NEW = (
    "COMMENT ON VIEW labeled_dataset IS 'M13.2 training-data export (spec §M13.2): one row per "
    "disposition joining its outcome label to the account Pass-A fit/intent snapshots (M6), "
    "the frozen contributing-source provenance, and the ICP spec (M3). Scoped by (workspace_id, "
    "icp_key, icp_spec_version); excludes tombstoned rows (M10.5). The contract M13.3 reads.'"
)
_VIEW_COMMENT_OLD = (
    "COMMENT ON VIEW labeled_dataset IS 'M13.2 training-data export (spec §M13.2): one row per "
    "disposition joining its outcome label to the account Pass-A fit/intent snapshots (M6), "
    "the frozen contributing-source provenance, and the ICP spec (M3). Scoped by (client_id, "
    "icp_key, icp_spec_version); excludes tombstoned rows (M10.5). The contract M13.3 reads.'"
)


def upgrade() -> None:
    # The view reads claim.tenant_id / disposition.client_id / icp_spec.client_id and would keep
    # its OLD output aliases through a bare RENAME COLUMN — drop first, rebuild last.
    op.execute("DROP VIEW labeled_dataset")

    # 1. the 19 column renames.
    for table in _TENANT_ID_TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN tenant_id TO workspace_id")
    for table in _CLIENT_ID_TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN client_id TO workspace_id")

    # 2. the claim reuse-scope CHECK: recreate under its new name over workspace_id. The enum
    # VALUE 'tenant_private' is retained (it names pooling semantics, not the id).
    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_reuse_scope_tenant")
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_reuse_scope_workspace CHECK (
            (reuse_scope = 'public_footprint' AND workspace_id IS NULL)
            OR (reuse_scope = 'tenant_private' AND workspace_id IS NOT NULL)
        )
        """
    )

    # 3. index/constraint renames (kept-name indexes follow the column rename automatically,
    # including every NULLS NOT DISTINCT slot and partial-index WHERE clause).
    for old, new in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
    for table, old, new in _CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")

    # 4. client_policy → workspace_policy (the old identifier goes away entirely).
    op.execute("ALTER TABLE client_policy RENAME TO workspace_policy")
    for old, new in _POLICY_CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE workspace_policy RENAME CONSTRAINT {old} TO {new}")
    op.execute("ALTER INDEX client_policy_scope_version RENAME TO workspace_policy_scope_version")

    # 5. the three plpgsql guards reference the old column names in their bodies (plpgsql resolves
    # NEW.<col> at run time) — recreate each over workspace_id. The claim guard keeps workspace_id
    # in its immutable list (the 0008/651b1d7229e2 append-only discipline).
    op.execute(_claim_guard_sql(_M2_5_IMMUTABLE_NEW))
    op.execute(_icp_spec_guard_sql("workspace_id"))
    op.execute(_disposition_guard_sql("workspace_id"))

    # 6. rebuild the view over the renamed columns (the c.tenant_id = d.client_id join collapses
    # to workspace_id = workspace_id) with workspace_id as its output column.
    op.execute(_labeled_dataset_sql(id_column="workspace_id", claim_id_column="workspace_id"))
    op.execute(_VIEW_COMMENT_NEW)


def downgrade() -> None:
    op.execute("DROP VIEW labeled_dataset")

    op.execute("ALTER INDEX workspace_policy_scope_version RENAME TO client_policy_scope_version")
    for old, new in _POLICY_CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE workspace_policy RENAME CONSTRAINT {new} TO {old}")
    op.execute("ALTER TABLE workspace_policy RENAME TO client_policy")

    for table, old, new in _CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for old, new in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")

    op.execute("ALTER TABLE claim DROP CONSTRAINT claim_reuse_scope_workspace")

    for table in _CLIENT_ID_TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN workspace_id TO client_id")
    for table in _TENANT_ID_TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN workspace_id TO tenant_id")

    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_reuse_scope_tenant CHECK (
            (reuse_scope = 'public_footprint' AND tenant_id IS NULL)
            OR (reuse_scope = 'tenant_private' AND tenant_id IS NOT NULL)
        )
        """
    )

    op.execute(_claim_guard_sql(_M2_5_IMMUTABLE_OLD))
    op.execute(_icp_spec_guard_sql("client_id"))
    op.execute(_disposition_guard_sql("client_id"))

    op.execute(_labeled_dataset_sql(id_column="client_id", claim_id_column="tenant_id"))
    op.execute(_VIEW_COMMENT_OLD)
