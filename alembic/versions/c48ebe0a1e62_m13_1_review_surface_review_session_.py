"""m13.1 review surface (review_session + review_action + REVIEW phase)

Revision ID: c48ebe0a1e62
Revises: 05f66cc526ae
Create Date: 2026-06-25 21:21:54.124681+00:00

M13.1 puts a Tier-1 human review surface immediately before the M12 handoff, modelled as a new
``CampaignPhase.REVIEW`` between ``verification`` and ``handoff`` that suspends via the existing
``AWAITING_INPUT`` checkpoint (M7.3). This migration adds:

* the ``review`` value on the **``campaign_phase``** enum (mirrors ``core.enums.CampaignPhase``),
  ordered ``BEFORE 'handoff'`` so the DB enum sort order matches the Python enum definition order
  (the parity test in ``tests/durable/test_campaign_run_db.py`` compares them). ``ALTER TYPE ... ADD
  VALUE`` is **irreversible** in Postgres (there is no ``DROP VALUE``), so ``downgrade`` leaves the
  label in place — a documented no-op; the full ``downgrade`` to base drops the whole type anyway.
* ``review_session`` — one row per ``account_handoff`` candidate under review (one high-tier
  ``account_entity_id`` within a ``campaign_run`` at a ``review_round``). A *mutable* cursor
  (``status`` open→finalized), deliberately **not** append-only (like ``campaign_run``/``account_run``
  — the claim store keeps immutable history). ``UNIQUE(account_entity_id, campaign_run_id,
  review_round)`` is the frozen idempotency shape (resume never double-advances; ``open_session`` is
  idempotent on it). Finalization gates that account's handoff (M13.1 AC).
* ``review_action`` — the **append-only** audit log: one row per approve/correct/reject. A
  ``correct`` carries the corrected value (written as a new ``human`` claim that supersedes the
  original); a ``reject`` carries a reason code (written as a ``REJECTED`` superseding claim).
  Guarded append-only by a BEFORE UPDATE/DELETE reject trigger, mirroring ``claim`` (0002) and
  ``adjustment_journal`` (ce08…).

Enums: ``review_session_status`` / ``review_action_kind`` / ``review_reject_reason`` mirror the
``core.enums`` taxonomies (``ReviewSessionStatus`` / ``ReviewAction`` / ``ReviewRejectReason``);
parity-tested in ``tests/review/`` (the same ``StrEnum`` discipline as the durable enums).

Soft FKs (no ``REFERENCES``, mirroring ``claim``/``campaign_run``): ``review_session.campaign_run_id``
/ ``account_entity_id`` and ``review_action.claim_id`` / ``review_session_id`` are not DB-level FKs;
integrity is enforced in the write path so milestone migrations stay order-independent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c48ebe0a1e62"
down_revision: str | None = "05f66cc526ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Extend the cross-milestone campaign_phase enum (mirror core.enums.CampaignPhase). Ordered
    #    BEFORE 'handoff' so the DB enum sort order equals the Python enum order (parity test). ADD
    #    VALUE is irreversible (no DROP VALUE); IF NOT EXISTS makes a partial-down/re-up idempotent.
    #    PG16 permits ADD VALUE inside a transaction as long as the value is not *used* in the same
    #    transaction — it is not (the review tables use their own enums, not campaign_phase).
    op.execute("ALTER TYPE campaign_phase ADD VALUE IF NOT EXISTS 'review' BEFORE 'handoff'")

    # 2. review-surface enums (mirror core.enums.ReviewSessionStatus / ReviewAction / ReviewRejectReason).
    op.execute("CREATE TYPE review_session_status AS ENUM ('open', 'finalized', 'abandoned')")
    op.execute("CREATE TYPE review_action_kind AS ENUM ('approve', 'correct', 'reject')")
    op.execute(
        "CREATE TYPE review_reject_reason AS ENUM "
        "('inaccurate', 'outdated', 'misattributed', 'inappropriate', 'unsupported', 'other')"
    )

    # 3. review_session: the mutable per-candidate review cursor -------------------------------
    op.execute(
        """
        CREATE TABLE review_session (
            id                 uuid NOT NULL,
            account_entity_id  uuid NOT NULL,
            campaign_run_id    uuid NOT NULL,
            client_id          text NOT NULL,
            review_round       integer NOT NULL DEFAULT 1,
            status             review_session_status NOT NULL DEFAULT 'open',
            opened_by          text,
            opened_at          timestamptz NOT NULL DEFAULT now(),
            finalized_at       timestamptz,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT review_session_pkey PRIMARY KEY (id),
            CONSTRAINT review_session_round_positive CHECK (review_round >= 1),
            -- The frozen (account, campaign_run, review_round) idempotency shape: at most one session
            -- per round of a candidate, so open_session deduplicates onto the same row (M13.1 AC).
            CONSTRAINT review_session_scope
                UNIQUE (account_entity_id, campaign_run_id, review_round),
            -- A finalized session stamps when it finalized (and only a finalized one may).
            CONSTRAINT review_session_finalized_at_iff_finalized
                CHECK ((status = 'finalized') = (finalized_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE review_session IS 'Tier-1 review session over one account_handoff "
        "candidate (M13.1). Mutable cursor (open->finalized); finalization gates that account''s "
        "handoff. UNIQUE(account_entity_id, campaign_run_id, review_round) = the idempotency shape.'"
    )
    # Hot read: the reviewer's queue — open sessions for a run (the app orders by tier then fit).
    op.execute("CREATE INDEX review_session_run_status ON review_session (campaign_run_id, status)")

    # 4. review_action: append-only audit of every review action ------------------------------
    op.execute(
        """
        CREATE TABLE review_action (
            id                   uuid NOT NULL,
            seq                  bigint GENERATED ALWAYS AS IDENTITY,
            review_session_id    uuid NOT NULL,
            claim_id             uuid NOT NULL,
            action               review_action_kind NOT NULL,
            reason_code          review_reject_reason,
            corrected_value_json jsonb,
            note                 text,
            superseding_claim_id uuid,
            actor                text NOT NULL,
            acted_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT review_action_pkey PRIMARY KEY (id),
            -- A correction carries the corrected value; approve/reject must not.
            CONSTRAINT review_action_corrected_value_iff_correct
                CHECK ((action = 'correct') = (corrected_value_json IS NOT NULL)),
            -- A reject carries a reason code; approve/correct must not.
            CONSTRAINT review_action_reason_iff_reject
                CHECK ((action = 'reject') = (reason_code IS NOT NULL)),
            -- correct/reject record their superseding claim; approve does not.
            CONSTRAINT review_action_supersede_iff_mutating
                CHECK ((superseding_claim_id IS NOT NULL) = (action IN ('correct', 'reject')))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE review_action IS 'Append-only audit of Tier-1 review actions (M13.1): one "
        "row per approve/correct/reject. correct writes a human superseding claim; reject writes a "
        "REJECTED superseding claim. Immutable (reject trigger); ordered by the monotonic seq.'"
    )
    # Ordered audit per session by the monotonic seq (created_at ties within a transaction).
    op.execute("CREATE INDEX review_action_session ON review_action (review_session_id, seq)")
    # Lookup: every action taken on a given claim (the per-claim disposition history M13.2 reads).
    op.execute("CREATE INDEX review_action_claim ON review_action (claim_id)")

    # Append-only guard (mirrors claim 0002 / adjustment_journal): the audit is immutable, so any
    # UPDATE or DELETE is a programming error and is rejected at the database.
    op.execute(
        """
        CREATE FUNCTION review_action_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'review_action is append-only (no % allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER review_action_no_update BEFORE UPDATE ON review_action "
        "FOR EACH ROW EXECUTE FUNCTION review_action_reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER review_action_no_delete BEFORE DELETE ON review_action "
        "FOR EACH ROW EXECUTE FUNCTION review_action_reject_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_action_no_delete ON review_action")
    op.execute("DROP TRIGGER IF EXISTS review_action_no_update ON review_action")
    op.execute("DROP FUNCTION IF EXISTS review_action_reject_mutation()")
    op.execute("DROP INDEX IF EXISTS review_action_claim")
    op.execute("DROP INDEX IF EXISTS review_action_session")
    op.execute("DROP TABLE IF EXISTS review_action")

    op.execute("DROP INDEX IF EXISTS review_session_run_status")
    op.execute("DROP TABLE IF EXISTS review_session")

    op.execute("DROP TYPE IF EXISTS review_reject_reason")
    op.execute("DROP TYPE IF EXISTS review_action_kind")
    op.execute("DROP TYPE IF EXISTS review_session_status")

    # NOTE: the 'review' value added to the campaign_phase enum is intentionally NOT removed —
    # Postgres has no ``ALTER TYPE ... DROP VALUE``. A downgrade-to-base drops the whole
    # campaign_phase type (in the ce08… migration), so the round-trip db-smoke (up→base→up) stays
    # clean; a partial ``downgrade -1`` leaves the dangling 'review' label, which a re-``upgrade``
    # tolerates (ADD VALUE IF NOT EXISTS).
