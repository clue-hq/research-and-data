"""campaign_run to project_run rename (§1a stage 2)

Revision ID: 814a272f79a5
Revises: 399633c6e1cb
Create Date: 2026-07-22 04:37:08.350926+00:00

The harness §1a ruling made *project* the end-to-end ABM motion (everything historically called
"campaign_run") and *campaign* a channel program within a project. Stage 1 renamed the fleet-owned
surfaces on the B1 lane (``run_lease`` / ``fleet_task`` are already ``project_run_id``); this is
the stage-2 repo rename per ``docs/specs/PB-rename-campaign-run-to-project-run.md`` — the
live-schema half. Token-precise over the run machinery only; bare "campaign" concepts stay.

What renames (measured against the live schema, 2026-07-22):

* tables ``campaign_run`` → ``project_run`` and ``campaign_phase_checkpoint`` →
  ``project_phase_checkpoint`` (§3f judgment call: the checkpoint table is run machinery);
* enum *type names* ``campaign_phase`` → ``project_phase``, ``campaign_run_status`` →
  ``project_run_status`` (their VALUES carry no token — verified against the live catalog);
* every carrying ``campaign_run_id`` column → ``project_run_id`` (9 tables);
* every token-named constraint/index (names do not follow ``RENAME``); indexes whose *names*
  carry no token keep their names — their definitions follow the column rename automatically;
* the one plpgsql function whose *body* names the column at runtime
  (``disposition_reject_value_update`` — A3.1 gotcha 1: function bodies are not rewritten by
  ``RENAME COLUMN``) is dropped + recreated over ``project_run_id``, with its trigger;
* the one view (``labeled_dataset`` — A3.1 gotcha 2: output aliases do not follow the rename) is
  dropped + recreated with ``d.project_run_id AS project_run_id``.

**Deliberately untouched — frozen durable data (playbook §4.5):** the ``idempotency_scope`` enum
VALUES (``'account_step'``, ``'campaign_phase'``) are baked into every M7.4 ledger key at rest
(as prefix and hash payload) and stored verbatim in ``idempotency_ledger.scope``. Renaming a
value would change the derived key for every in-flight run (re-execution / double-spend). Only
Python member *names* flip in code; the value strings are frozen forever.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Forward + reverse: ``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
- Historical migration files stay byte-identical; this migration renames the *live* schema only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "814a272f79a5"
down_revision: str | None = "399633c6e1cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- carrier tables whose campaign_run_id column renames (stage-1 fleet tables excluded) ---------
_CARRIERS: tuple[str, ...] = (
    "account_run",
    "budget_event",
    "account_handoff",
    "handoff_event",
    "review_session",
    "disposition",
    "cost_estimate",
    "adjustment_journal",
    "campaign_phase_checkpoint",  # column pass runs BEFORE the table renames — old name here
)

# --- token-named constraints: (table name AFTER the table renames, old, new) ---------------------
# ALTER TABLE … RENAME CONSTRAINT also renames the backing index for pkeys/uniques.
_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    ("project_run", "campaign_run_pkey", "project_run_pkey"),
    ("project_run", "campaign_run_cap_nonneg", "project_run_cap_nonneg"),
    ("project_run", "campaign_run_spent_nonneg", "project_run_spent_nonneg"),
    ("project_run", "campaign_run_estimated_nonneg", "project_run_estimated_nonneg"),
    ("project_run", "campaign_run_icp_version_positive", "project_run_icp_version_positive"),
    ("project_run", "campaign_run_cutoffs_is_object", "project_run_cutoffs_is_object"),
    ("project_run", "campaign_run_project_fk", "project_run_project_fk"),
    (
        "project_phase_checkpoint",
        "campaign_phase_checkpoint_pkey",
        "project_phase_checkpoint_pkey",
    ),
    (
        "project_phase_checkpoint",
        "campaign_phase_checkpoint_run_phase",
        "project_phase_checkpoint_run_phase",
    ),
    (
        "project_phase_checkpoint",
        "campaign_phase_checkpoint_committed_at_iff_committed",
        "project_phase_checkpoint_committed_at_iff_committed",
    ),
    (
        "project_phase_checkpoint",
        "campaign_phase_checkpoint_payload_is_object",
        "project_phase_checkpoint_payload_is_object",
    ),
)

# Plain (non-constraint) index renames — only names that carry the token.
_INDEXES: tuple[tuple[str, str], ...] = (
    ("campaign_run_project", "project_run_project"),
    ("campaign_run_workspace", "project_run_workspace"),
    ("campaign_phase_checkpoint_run", "project_phase_checkpoint_run"),
    ("account_run_campaign", "account_run_project"),
    ("account_handoff_campaign_run", "account_handoff_project_run"),
)

# --- disposition immutability guard (3b470c5fdcb4, last recreated by b61cd4887129) ---------------
# The body names columns at runtime, so the column rename requires a drop + recreate (gotcha 1).
_IMMUTABLE_NEW: tuple[str, ...] = (
    "id",
    "disposition_type",
    "entity_id",
    "entity_type",
    "account_entity_id",
    "claim_id",
    "project_run_id",
    "workspace_id",
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
_IMMUTABLE_OLD: tuple[str, ...] = tuple(
    "campaign_run_id" if col == "project_run_id" else col for col in _IMMUTABLE_NEW
)


def _immutable_guard_sql(columns: tuple[str, ...]) -> str:
    guard = " OR ".join(f"NEW.{col} IS DISTINCT FROM OLD.{col}" for col in columns)
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


# --- the labeled_dataset view (3b470c5fdcb4 → b61cd4887129) — parameterised on the run column ----
# Output aliases do not follow RENAME COLUMN (gotcha 2): drop + recreate with the new alias.
def _labeled_dataset_sql(*, run_column: str) -> str:
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
            d.{run_column}      AS {run_column},
            d.workspace_id      AS workspace_id,
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
              AND c.workspace_id = d.workspace_id
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
              AND c.workspace_id = d.workspace_id
              AND d.icp_spec_version IS NOT NULL
              AND c.value_json ->> 'icp_version' = d.icp_spec_version::text
              AND c.value_json ->> 'icp_key' = d.icp_key
            ORDER BY c.collected_at DESC
            LIMIT 1
        ) intent ON true
        LEFT JOIN icp_spec spec
            ON spec.workspace_id = d.workspace_id
           AND spec.icp_key = d.icp_key
           AND spec.version = d.icp_spec_version
        WHERE d.tombstoned_at IS NULL
    """


_VIEW_COMMENT = (
    "COMMENT ON VIEW labeled_dataset IS 'M13.2 training-data export (spec §M13.2): one row per "
    "disposition joining its outcome label to the account Pass-A fit/intent snapshots (M6), "
    "the frozen contributing-source provenance, and the ICP spec (M3). Scoped by (workspace_id, "
    "icp_key, icp_spec_version); excludes tombstoned rows (M10.5). The contract M13.3 reads.'"
)


def upgrade() -> None:
    # 0. Drop the objects whose bodies/aliases name the old column (recreated in step 4).
    op.execute("DROP VIEW labeled_dataset")
    op.execute("DROP TRIGGER disposition_immutable ON disposition")
    op.execute("DROP FUNCTION disposition_reject_value_update()")

    # 1. Column renames on every carrier (runs before the table renames — old table names).
    for table in _CARRIERS:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN campaign_run_id TO project_run_id")

    # 2. Table + enum-type renames (composite row types follow the table rename automatically).
    op.execute("ALTER TABLE campaign_run RENAME TO project_run")
    op.execute("ALTER TABLE campaign_phase_checkpoint RENAME TO project_phase_checkpoint")
    op.execute("ALTER TYPE campaign_phase RENAME TO project_phase")
    op.execute("ALTER TYPE campaign_run_status RENAME TO project_run_status")

    # 3. Token-named constraints + indexes (names do not follow the renames above).
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")

    # 4. Recreate the guard function + trigger and the view over the new names.
    op.execute(_immutable_guard_sql(_IMMUTABLE_NEW))
    op.execute(
        "CREATE TRIGGER disposition_immutable BEFORE UPDATE ON disposition "
        "FOR EACH ROW EXECUTE FUNCTION disposition_reject_value_update()"
    )
    op.execute(_labeled_dataset_sql(run_column="project_run_id"))
    op.execute(_VIEW_COMMENT)


def downgrade() -> None:
    # Mirror image: drop the recreated objects, rename everything back, recreate over old names.
    op.execute("DROP VIEW labeled_dataset")
    op.execute("DROP TRIGGER disposition_immutable ON disposition")
    op.execute("DROP FUNCTION disposition_reject_value_update()")

    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")

    op.execute("ALTER TYPE project_run_status RENAME TO campaign_run_status")
    op.execute("ALTER TYPE project_phase RENAME TO campaign_phase")
    op.execute("ALTER TABLE project_phase_checkpoint RENAME TO campaign_phase_checkpoint")
    op.execute("ALTER TABLE project_run RENAME TO campaign_run")

    for table in _CARRIERS:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN project_run_id TO campaign_run_id")

    op.execute(_immutable_guard_sql(_IMMUTABLE_OLD))
    op.execute(
        "CREATE TRIGGER disposition_immutable BEFORE UPDATE ON disposition "
        "FOR EACH ROW EXECUTE FUNCTION disposition_reject_value_update()"
    )
    op.execute(_labeled_dataset_sql(run_column="campaign_run_id"))
    op.execute(_VIEW_COMMENT)
