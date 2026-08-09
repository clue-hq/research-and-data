"""d5 design run job fleet reshape

Revision ID: 50b84c524fa2
Revises: be855c8f6993
Create Date: 2026-08-09

Part II slice D5 (durable execution), migration 2 of 2 — ``design_agent_run`` stops being the
D1/D2 port of a daemon-thread run row and becomes a leasable durable job; ``design_ingestion_job``
gains the same fleet handle.

``design_agent_run`` gains, and why each column exists:

* ``work_id uuid NOT NULL UNIQUE`` — the fleet's work id for this run. It is *derivable* from the
  run id (``run_<uuid4 hex>`` → that same uuid) but stored explicitly: the fleet keys on a uuid,
  the design API's shipped surface keys on the ``run_…`` string, and a derivation living only in
  code would be an unindexable, unverifiable join. The UNIQUE constraint is what makes
  ``claim_run_for_execution`` a single-row CAS.
* ``checkpoint_thread_id text NOT NULL`` — the LangGraph ``AsyncPostgresSaver`` thread id. The D5
  ruling unifies the two ids that exist today (the API's ``run_…`` and the agent runtime's
  separate ``tools.run_id``): the checkpoint thread IS the design run, so a resumed run resumes
  the same graph. New rows carry ``checkpoint_thread_id = run_id``; the runtime's own id degrades
  to trace-directory naming (Round B).
* ``kind design_run_kind NOT NULL`` (``agent_turn`` | ``web_turn``) — the run's shape, mirrored by
  ``clue_design.enums.DesignRunKind`` and parity-tested. The two turn families have different
  runtimes (``lumen_agent.harness`` vs ``harness_web``) and the worker must know which to enter
  without unpacking the payload.
* ``payload jsonb NOT NULL DEFAULT '{}'`` (object CHECK) — the frozen by-value turn envelope the
  worker executes from. Same discipline as ``entity_research_job.authorization_json``: everything
  the run needs (brand kit, fonts spec, resolved reference assets, account card, asset library,
  target node ids …) is captured at enqueue, so a takeover worker replays the *same* turn rather
  than re-reading mutable state that has since moved.
* ``leased_by text`` / ``lease_generation bigint`` / ``leased_at timestamptz`` — nullable
  observability columns stamped by the claiming worker. The authoritative fence stays the
  platform ``work_lease`` row (Rule F1: design code never learns the queue exists); these make
  "who is driving this run, under which generation" answerable from the design row alone.

``status`` widens with ``queued``: a run is now *born queued* by the API and stamped ``running``
by the worker that claims it. The type is rebuilt rather than ``ALTER TYPE … ADD VALUE``-ed so
that (a) the label lands in lifecycle order (``queued`` first) rather than appended last, and
(b) the migration is genuinely reversible — PostgreSQL cannot drop an enum label.

Suspension / HITL states are deliberately NOT in this vocabulary; D5's status set stays minimal.

``design_ingestion_job`` gains ``work_id uuid`` **nullable** with a partial UNIQUE index: jobs
created before fleet dispatch (and any created by a path that has not yet been switched over in
Round B) legitimately have none, so NULL must stay legal while every stamped value stays unique.

Backfill: existing rows get ``work_id`` from their run id, ``checkpoint_thread_id = run_id``, and
``kind = 'agent_turn'`` (every run today is an editor/web agent turn opened by the daemon-thread
path). The derivation below is **byte-identical to** ``clue_design.runs.work_id_for_run`` — same
``^run_[0-9a-f]{32}$`` test, same MD5 fold for anything else — so a row backfilled here and a row
created by the DAL carry the same work id for the same run id. Keep the two in step if either
changes.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up), and
refuses rather than silently destroying state when a ``queued`` run exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50b84c524fa2"
down_revision: str | None = "be855c8f6993"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_RUN_KIND = ("agent_turn", "web_turn")
_RUN_STATUS_AFTER = ("queued", "running", "succeeded", "failed")
_RUN_STATUS_BEFORE = ("running", "succeeded", "failed")

_TABLE_COMMENT_AFTER = (
    "Design agent runs (PD D5) — one leasable durable job per design turn. work_id is the "
    "fleet handle (derived from run_id, stored explicitly); checkpoint_thread_id is the "
    "LangGraph thread (= run_id) so a resumed run resumes the same graph; payload is the "
    "frozen by-value turn envelope the worker executes from; kind selects the runtime. "
    "Born 'queued'; the claiming worker stamps 'running' + the lease columns."
)
_TABLE_COMMENT_BEFORE = (
    "Design-agent turn runs (PD D1f) — TEMPORARY shape: the D1/D2 port of the daemon-thread "
    "run row. D5 reshapes it onto the durable job pattern (lease_generation, "
    "checkpoint_thread_id, subject columns); restart-survivable + concurrent multi-session "
    "runs are the binding requirements."
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _literal(text: str) -> str:
    """A SQL string literal (single quotes doubled) — the COMMENT bodies quote enum labels."""
    doubled = text.replace("'", "''")
    return f"'{doubled}'"


def _rebuild_run_status(values: tuple[str, ...]) -> None:
    """Recreate ``design_run_status`` with ``values`` (its only user is design_agent_run.status)."""
    op.execute("ALTER TYPE design_run_status RENAME TO design_run_status_pd_d5")
    op.execute(f"CREATE TYPE design_run_status AS ENUM ({_enum_values_sql(values)})")
    op.execute(
        """
        ALTER TABLE design_agent_run
        ALTER COLUMN status TYPE design_run_status
        USING status::text::design_run_status
        """
    )
    op.execute("DROP TYPE design_run_status_pd_d5")


def upgrade() -> None:
    op.execute(f"CREATE TYPE design_run_kind AS ENUM ({_enum_values_sql(_RUN_KIND)})")
    _rebuild_run_status(_RUN_STATUS_AFTER)

    op.execute(
        """
        ALTER TABLE design_agent_run
        ADD COLUMN work_id              uuid,
        ADD COLUMN checkpoint_thread_id text,
        ADD COLUMN kind                 design_run_kind,
        ADD COLUMN payload              jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN leased_by            text,
        ADD COLUMN lease_generation     bigint,
        ADD COLUMN leased_at            timestamptz
        """
    )
    # Backfill (see the module docstring): the same derivation clue_design.runs.work_id_for_run
    # applies — the uuid inside a shipped `run_<uuid4 hex>` id, else an MD5 fold of the whole id.
    op.execute(
        """
        UPDATE design_agent_run
        SET work_id = CASE
                WHEN run_id ~ '^run_[0-9a-f]{32}$' THEN CAST(substring(run_id FROM 5) AS uuid)
                ELSE CAST(md5(run_id) AS uuid)
            END,
            checkpoint_thread_id = run_id,
            kind = CAST('agent_turn' AS design_run_kind)
        WHERE work_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE design_agent_run
        ALTER COLUMN work_id SET NOT NULL,
        ALTER COLUMN checkpoint_thread_id SET NOT NULL,
        ALTER COLUMN kind SET NOT NULL,
        ADD CONSTRAINT design_agent_run_work_id_unique UNIQUE (work_id),
        ADD CONSTRAINT design_agent_run_checkpoint_thread_nonempty
            CHECK (length(checkpoint_thread_id) > 0),
        ADD CONSTRAINT design_agent_run_payload_object
            CHECK (jsonb_typeof(payload) = 'object'),
        ADD CONSTRAINT design_agent_run_lease_generation_positive
            CHECK (lease_generation IS NULL OR lease_generation >= 1),
        ADD CONSTRAINT design_agent_run_lease_shape CHECK (
            (leased_by IS NULL AND lease_generation IS NULL AND leased_at IS NULL) OR
            (leased_by IS NOT NULL AND lease_generation IS NOT NULL AND leased_at IS NOT NULL)
        )
        """
    )
    op.execute(f"COMMENT ON TABLE design_agent_run IS {_literal(_TABLE_COMMENT_AFTER)}")
    for column, comment in (
        (
            "work_id",
            "Fleet work id for this run (derived from run_id, stored explicitly so the fleet "
            "can key on a uuid and the CAS claim is a single indexed row).",
        ),
        (
            "checkpoint_thread_id",
            "LangGraph AsyncPostgresSaver thread id — equals run_id for runs created at or "
            "after D5, so a resumed run resumes the same graph.",
        ),
        (
            "kind",
            "Which design runtime executes this run (agent_turn = scene harness, "
            "web_turn = web harness). The fleet sees one mechanical kind (design_job); this "
            "column plus the payload envelope carry the real discriminant.",
        ),
        (
            "payload",
            "Frozen by-value turn envelope the worker executes from (brand kit, fonts spec, "
            "resolved reference assets, account card, asset library, target node ids, ...). "
            "Captured at enqueue so a takeover replays the same turn.",
        ),
        (
            "leased_by",
            "Observability: worker id that last claimed this run. The authoritative fence is "
            "the platform work_lease row; design code never reads the queue.",
        ),
        ("lease_generation", "Observability: lease generation under which the run was claimed."),
        ("leased_at", "Observability: when the current lease holder claimed the run."),
    ):
        op.execute(f"COMMENT ON COLUMN design_agent_run.{column} IS {_literal(comment)}")

    op.execute("ALTER TABLE design_ingestion_job ADD COLUMN work_id uuid")
    op.execute(
        "CREATE UNIQUE INDEX design_ingestion_job_work_id "
        "ON design_ingestion_job (work_id) WHERE work_id IS NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN design_ingestion_job.work_id IS "
        + _literal(
            "Fleet work id once this job is dispatched to the fleet. NULLABLE by design: jobs "
            "that predate fleet dispatch have none, and the partial UNIQUE index keeps every "
            "stamped value unique without outlawing NULL."
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX design_ingestion_job_work_id")
    op.execute("ALTER TABLE design_ingestion_job DROP COLUMN work_id")

    op.execute(
        """
        ALTER TABLE design_agent_run
        DROP CONSTRAINT design_agent_run_lease_shape,
        DROP CONSTRAINT design_agent_run_lease_generation_positive,
        DROP CONSTRAINT design_agent_run_payload_object,
        DROP CONSTRAINT design_agent_run_checkpoint_thread_nonempty,
        DROP CONSTRAINT design_agent_run_work_id_unique,
        DROP COLUMN leased_at,
        DROP COLUMN lease_generation,
        DROP COLUMN leased_by,
        DROP COLUMN payload,
        DROP COLUMN kind,
        DROP COLUMN checkpoint_thread_id,
        DROP COLUMN work_id
        """
    )
    op.execute(f"COMMENT ON TABLE design_agent_run IS {_literal(_TABLE_COMMENT_BEFORE)}")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM design_agent_run WHERE status::text = 'queued') THEN
                RAISE EXCEPTION
                    'cannot downgrade PD D5 while queued design runs exist';
            END IF;
        END $$
        """
    )
    _rebuild_run_status(_RUN_STATUS_BEFORE)
    op.execute("DROP TYPE design_run_kind")
