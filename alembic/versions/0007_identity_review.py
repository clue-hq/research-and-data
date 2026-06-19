"""identity_review_task + identity_disposition — auto-merge / review surface (M2.3 / ENG-112)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-19

Turn M2.2's scores into safe dispositions (substrate §2): high-confidence (≈≥0.95) auto-merges; the
mid-band routes to a **human review queue** rather than guessing; never silently collapse two real
companies. This migration adds the two tables that own that surface:

* ``identity_review_task`` — the queue: the observation, the ranked candidates (with scores +
  features), the proposed action, the entity under review, tenant scope, and the resolution
  lifecycle (``open → resolved | dismissed``). A wrong merge is *fabrication of identity*; routing
  the ambiguous case to a human is the correct, conservative output (the universal rule, applied to
  identity — conventions §5).
* ``identity_disposition`` — the **audit**: every disposition (auto-merge, new-entity admission, or
  a human resolution) records who/what decided, the score, and the policy ``config_version`` — so
  an entity's identity history is queryable (mirroring the claim store's audit discipline), and
  human dispositions double as labelled match/not-match pairs for later scorer training (capture
  only here — substrate §9/§10).

It REUSES the existing ``entity_type`` enum (M1.1) and only *mutates* ``account_entity`` /
``contact_entity`` ``status`` + ``merged_into`` (owned by M2.1) through the application; it never
touches ``claim`` (append-only — reads resolve through ``surviving_id``). ``tenant_id`` is carried
from day one (``text``, aligned with ``config.client_id``) so M2.5 scopes the queue without a
re-migration. The three new enums are parity-tested against the Python enums in
``clue_research.identity.review`` (the M1 drift-guard pattern).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.identity.review.{ReviewStatus,ReviewResolution,DispositionKind}. The parity
# test in tests/identity/test_review.py asserts these stay in lock-step with the Python StrEnums.
_REVIEW_STATUS = ("open", "resolved", "dismissed")
_REVIEW_RESOLUTION = ("merge_into", "create_new_entity", "not_a_match", "split")
_DISPOSITION_KIND = ("auto_merge", "new_entity", "review_enqueued", "review_resolved")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE review_status AS ENUM ({_enum_values_sql(_REVIEW_STATUS)})")
    op.execute(f"CREATE TYPE review_resolution AS ENUM ({_enum_values_sql(_REVIEW_RESOLUTION)})")
    op.execute(f"CREATE TYPE disposition_kind AS ENUM ({_enum_values_sql(_DISPOSITION_KIND)})")

    op.execute(
        """
        CREATE TABLE identity_review_task (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type       entity_type NOT NULL,
            observation_json  jsonb NOT NULL,
            candidates_json   jsonb NOT NULL,
            proposed_action   text NOT NULL,
            subject_entity_id uuid,
            tenant_id         text,
            status            review_status NOT NULL DEFAULT 'open',
            resolution        review_resolution,
            resolved_by       text,
            resolved_at       timestamptz,
            config_version    int NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            -- An open task has no resolution yet; a closed one records who/when (and may carry a
            -- resolution). The "never mutate an entity until resolved" rule is enforced in code.
            CONSTRAINT review_open_has_no_resolution
                CHECK (status <> 'open' OR (resolution IS NULL AND resolved_at IS NULL)),
            CONSTRAINT review_candidates_is_array
                CHECK (jsonb_typeof(candidates_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE identity_review_task IS 'The human review queue for ambiguous identity "
        "matches (substrate §2). Mid-band scores land here rather than auto-merging; resolving a "
        "task applies the human decision. tenant_id (text) is forward-compat with M2.5.'"
    )
    op.execute(
        "CREATE INDEX identity_review_task_open ON identity_review_task (status) "
        "WHERE status = 'open'"
    )
    op.execute(
        "CREATE INDEX identity_review_task_tenant ON identity_review_task (tenant_id) "
        "WHERE tenant_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE identity_disposition (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type      entity_type NOT NULL,
            kind             disposition_kind NOT NULL,
            survivor_id      uuid,
            loser_id         uuid,
            review_task_id   uuid REFERENCES identity_review_task(id),
            top_score        numeric,
            decided_by       text NOT NULL,
            config_version   int NOT NULL,
            observation_json jsonb,
            candidates_json  jsonb,
            created_at       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE identity_disposition IS 'Append-only audit of every identity disposition "
        "(auto-merge / new-entity / human resolution): decider, score, config_version. Also the "
        "labelled match/not-match capture for later scorer training (substrate §9/§10).'"
    )
    op.execute(
        "CREATE INDEX identity_disposition_survivor ON identity_disposition (survivor_id) "
        "WHERE survivor_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX identity_disposition_loser ON identity_disposition (loser_id) "
        "WHERE loser_id IS NOT NULL"
    )


def downgrade() -> None:
    # identity_disposition FKs identity_review_task → drop it first.
    op.execute("DROP TABLE IF EXISTS identity_disposition")
    op.execute("DROP TABLE IF EXISTS identity_review_task")
    op.execute("DROP TYPE IF EXISTS disposition_kind")
    op.execute("DROP TYPE IF EXISTS review_resolution")
    op.execute("DROP TYPE IF EXISTS review_status")
