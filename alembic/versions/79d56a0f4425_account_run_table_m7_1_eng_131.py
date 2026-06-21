"""account_run table (M7.1 / ENG-131)

Revision ID: 79d56a0f4425
Revises: eab62cbb1366
Create Date: 2026-06-21

The per-account research run (substrate §5b; M7.1) — one row per account researched by one
``AccountResearchGraph`` invocation inside a campaign run. Its ``id`` IS the ``claim.run_id``
provenance every worker stamps, so a claim ties back to the exact graph run that produced it.

This is **mutable workflow state**, not a claim: ``status``/``plan_json``/``references_index``/
``cost_cents`` change over the run's life as the orchestrator plans, fans out aspect workers, and
collects their *references* (claim ids — never blobs, substrate §5b). It is therefore deliberately
**not** append-only (no supersede trigger): the claim store keeps the immutable history; this row is
the resumable execution cursor over it.

``references_index`` is a JSONB object ``{aspect -> [claim_id, …]}`` so the orchestrator's context
stays independent of claim count (it holds ids, not values). ``plan_json`` is persisted **before any
worker spawns** so a crash-after-plan / crash-before-plan both leave consistent state (M7.1 AC).

Soft FKs (no REFERENCES): ``campaign_run`` lands on a later M7.3 migration in this same branch and
``account_entity`` lives in M2 — mirroring the ``claim`` table's soft-FK convention (0002), the
integrity is enforced in the write path, not by a constraint that would couple migration order.

Enum ``account_run_status`` is a **durable-internal** lifecycle enum (Beat-0: M7 owns it; it is NOT
in ``core.enums``). It is mirrored from :class:`clue_research.durable.enums.AccountRunStatus`; the
parity test ``tests/durable/test_account_run_db.py::test_account_run_status_enum_matches_db`` guards
against drift.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "79d56a0f4425"
down_revision: str | None = "eab62cbb1366"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.durable.enums.AccountRunStatus (durable-internal; not a core enum). The
# parity test in tests/durable/ guards against drift.
_ACCOUNT_RUN_STATUS = (
    "pending",
    "planning",
    "running",
    "paused",
    "done",
    "failed",
    "budget_exceeded",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE account_run_status AS ENUM ({_enum_values_sql(_ACCOUNT_RUN_STATUS)})")

    op.execute(
        """
        CREATE TABLE account_run (
            id               uuid NOT NULL,
            campaign_run_id  uuid NOT NULL,
            entity_id        uuid NOT NULL,
            tier             text NOT NULL,
            status           account_run_status NOT NULL DEFAULT 'pending',
            plan_json        jsonb NOT NULL DEFAULT '{}'::jsonb,
            references_index jsonb NOT NULL DEFAULT '{}'::jsonb,
            cost_cents       numeric NOT NULL DEFAULT 0,
            started_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_run_pkey PRIMARY KEY (id),
            CONSTRAINT account_run_cost_nonneg CHECK (cost_cents >= 0),
            CONSTRAINT account_run_plan_is_object CHECK (jsonb_typeof(plan_json) = 'object'),
            CONSTRAINT account_run_refs_is_object
                CHECK (jsonb_typeof(references_index) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE account_run IS 'Per-account research run (substrate §5b; M7.1). "
        "id = claim.run_id provenance. Mutable, resumable execution state; references_index holds "
        "claim-id references only, never blobs.'"
    )

    # Hot reads: all account runs of a campaign (concurrency/scheduling), and runs for an entity
    # (single-flight / re-research lookups).
    op.execute("CREATE INDEX account_run_campaign ON account_run (campaign_run_id)")
    op.execute("CREATE INDEX account_run_entity ON account_run (entity_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS account_run_entity")
    op.execute("DROP INDEX IF EXISTS account_run_campaign")
    op.execute("DROP TABLE IF EXISTS account_run")
    op.execute("DROP TYPE IF EXISTS account_run_status")
