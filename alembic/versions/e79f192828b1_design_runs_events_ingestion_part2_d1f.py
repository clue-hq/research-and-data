"""design runs events ingestion (part2 D1f)

Revision ID: e79f192828b1
Revises: 86a9ce389e6e
Create Date: 2026-08-07

Part II slice D1, migration (f) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 16–18): the execution-adjacent tables — ``design_agent_run``, ``design_run_event``,
``design_ingestion_job`` — porting SQLite ``006_agent_runs.sql`` + ``007_ingestion_jobs.sql``.

**Two of these are deliberately TEMPORARY shapes** (documented in their COMMENTs so nobody
mistakes them for end-state):

* ``design_agent_run`` is the D1/D2 port of today's daemon-thread run row; **D5 reshapes it**
  onto the fleet-job pattern (``lease_generation``, ``checkpoint_thread_id``, subject columns —
  the ``entity_research_job`` precedent), whatever host the D5 discussion lands on (the fleet
  question is re-opened per the O5 founder FYI; restart-survivable runs + concurrent
  multi-session design runs are binding either way).
* ``design_run_event`` **dies at D7**: leg activity moves to ``design.*`` topics on the durable
  platform ``run_event`` stream (subject widening per the C5.1 precedent). Until then it backs
  the ported SSE surface; its per-run ``seq`` is the SSE event id, allocated under
  ``FOR UPDATE`` on the parent run row (D2 DAL).
* ``design_ingestion_job`` is a keeper; its *execution* (FastAPI BackgroundTasks today — which
  a restart strands as ``running`` forever, the known hole) moves to durable execution at D5.
  Its result pointer gains the real composite FK to ``design_brand_kit`` SQLite omitted; the
  staged-upload ``tmp_path``s inside ``request_json`` move to platform storage keys at D4.

Enum types ``design_run_status`` / ``design_ingestion_kind`` / ``design_ingestion_status``
mirror ``clue_design.enums``; parity-tested in ``tests/design/``. ``design_run_event.
event_type`` stays free text — it is the agent runtime's open vocabulary (~60 event names),
not a closed lifecycle.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e79f192828b1"
down_revision: str | None = "86a9ce389e6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_RUN_STATUS = ("running", "succeeded", "failed")
_INGESTION_KIND = ("website", "pdf", "asset_upload")
_INGESTION_STATUS = ("queued", "running", "succeeded", "failed")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE design_run_status AS ENUM ({_enum_values_sql(_RUN_STATUS)})")
    op.execute(f"CREATE TYPE design_ingestion_kind AS ENUM ({_enum_values_sql(_INGESTION_KIND)})")
    op.execute(
        f"CREATE TYPE design_ingestion_status AS ENUM ({_enum_values_sql(_INGESTION_STATUS)})"
    )

    # --- design_agent_run: one design-agent turn (TEMPORARY shape; D5 reshapes) --------------
    op.execute(
        """
        CREATE TABLE design_agent_run (
            run_id       text NOT NULL,
            workspace_id text NOT NULL,
            status       design_run_status NOT NULL,
            document_id  text,
            result_json  jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_agent_run_pkey PRIMARY KEY (run_id),
            CONSTRAINT design_agent_run_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_agent_run_workspace_anchor UNIQUE (run_id, workspace_id),
            -- Real FK now (SQLite deliberately omitted it); a deleted document detaches,
            -- never deletes, the run history.
            CONSTRAINT design_agent_run_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id)
                ON DELETE SET NULL (document_id),
            CONSTRAINT design_agent_run_result_object
                CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_agent_run IS 'Design-agent turn runs (PD D1f) — TEMPORARY "
        "shape: the D1/D2 port of the daemon-thread run row. D5 reshapes it onto the durable "
        "job pattern (lease_generation, checkpoint_thread_id, subject columns); restart-"
        "survivable + concurrent multi-session runs are the binding requirements.'"
    )
    op.execute(
        "CREATE INDEX design_agent_run_workspace "
        "ON design_agent_run (workspace_id, updated_at DESC)"
    )

    # --- design_run_event: ported SSE event log (TEMPORARY — dies at D7) ---------------------
    op.execute(
        """
        CREATE TABLE design_run_event (
            id           bigint GENERATED ALWAYS AS IDENTITY,
            workspace_id text NOT NULL,
            run_id       text NOT NULL,
            seq          integer NOT NULL,
            event_type   text NOT NULL,
            data_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_run_event_pkey PRIMARY KEY (id),
            CONSTRAINT design_run_event_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_run_event_run_fk
                FOREIGN KEY (run_id, workspace_id)
                REFERENCES design_agent_run (run_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_run_event_seq_unique UNIQUE (run_id, seq),
            CONSTRAINT design_run_event_data_object CHECK (jsonb_typeof(data_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_run_event IS 'Ported design SSE event log (PD D1f) — "
        "TEMPORARY: dies at D7 when leg activity moves to design.* topics on the platform "
        "run_event stream (C5.1 subject-widening precedent). seq is the SSE event id, "
        "allocated under FOR UPDATE on the parent run row (D2 DAL).'"
    )
    op.execute("CREATE INDEX design_run_event_run ON design_run_event (run_id, seq)")

    # --- design_ingestion_job: brand-kit ingestion jobs --------------------------------------
    op.execute(
        """
        CREATE TABLE design_ingestion_job (
            job_id       text NOT NULL,
            workspace_id text NOT NULL,
            kind         design_ingestion_kind NOT NULL,
            status       design_ingestion_status NOT NULL,
            stage        text,
            progress     real NOT NULL DEFAULT 0,
            request_json  jsonb NOT NULL,
            evidence_json jsonb,
            brand_kit_id      text,
            brand_kit_version integer,
            error_json    jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_ingestion_job_pkey PRIMARY KEY (job_id),
            CONSTRAINT design_ingestion_job_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_ingestion_job_progress_range
                CHECK (progress >= 0 AND progress <= 1),
            -- Real composite FK now (SQLite back-linked by convention); a deleted kit
            -- detaches the result pointer, never the job history.
            CONSTRAINT design_ingestion_job_result_fk
                FOREIGN KEY (brand_kit_id, brand_kit_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id)
                ON DELETE SET NULL (brand_kit_id, brand_kit_version),
            CONSTRAINT design_ingestion_job_request_object
                CHECK (jsonb_typeof(request_json) = 'object'),
            CONSTRAINT design_ingestion_job_evidence_object
                CHECK (evidence_json IS NULL OR jsonb_typeof(evidence_json) = 'object'),
            CONSTRAINT design_ingestion_job_error_object
                CHECK (error_json IS NULL OR jsonb_typeof(error_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_ingestion_job IS 'Brand-kit ingestion jobs (PD D1f): "
        "website/pdf/asset_upload -> a design_brand_kit version. Execution moves to durable "
        "execution at D5 (BackgroundTasks strand running jobs on restart today); staged "
        "tmp_paths in request_json move to platform storage keys at D4.'"
    )
    op.execute(
        "CREATE INDEX design_ingestion_job_status "
        "ON design_ingestion_job (workspace_id, status, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_ingestion_job")
    op.execute("DROP TABLE design_run_event")
    op.execute("DROP TABLE design_agent_run")
    op.execute("DROP TYPE design_ingestion_status")
    op.execute("DROP TYPE design_ingestion_kind")
    op.execute("DROP TYPE design_run_status")
