"""m9.6 eval harness — golden_fixture + eval_run (ENG-156)

Revision ID: 015474d0a18c
Revises: cb39832d29bb
Create Date: 2026-06-21 23:55:00.000000+00:00

M9.6 (the eval harness — how an accuracy claim is *defended* to an enterprise buyer and how a
model/resolver swap's regressions are caught, substrate §6): it *fills* the M0.6 eval scaffold
(``clue_research.evals``) with the real verification battery. This migration adds only the M9.6
*persistence* schema — the durable golden set and the eval-run audit — and, per the M9 isolation
contract, alters **no shared mutable surface** (no ``claim`` ALTER, no trigger change):

* ``golden_fixture`` — the hand-verified ground truth as versioned rows (the row form of
  ``GoldClaim``; the curated in-code ``GoldPack`` is the file form — both are valid per M09 §M9.6).
  One row per ``(entity_ref, field_key, fixture_kind)`` (the UNIQUE makes seeding idempotent). The
  ``fixture_kind`` is positive (a correct fact the rubric battery scores) or one of the four planted
  ``negative_*`` traps a *specific* mechanism must catch (its documented expected catch); ``mode``
  is the research mode (M1–M4) it exercises. The human spot-check sampler *ingests* a reviewed
  production claim as a new positive row here (the feedback loop, M09 §M9.6 acceptance).
* ``eval_run`` — append-only run audit: the ``suite``, the ``config_snapshot_json`` (the judge model
  / prompt version / thresholds / resolver set the run scored), and the ``report_json`` (the
  per-rubric + per-mechanism + regression report). Recorded so a regression traces to the **exact**
  swap that caused it (M09 §M9.6) and so trend/regression history is queryable.

``fixture_kind`` mirrors :class:`clue_research.evals.models.FixtureKind` (the eval-local taxonomy —
it lives in ``evals``, not ``core``, since it crosses no milestone seam; the DB↔enum parity test is
in the M9.6 suite). ``mode`` reuses the existing ``research_mode`` enum (0002). ``downgrade()``
cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015474d0a18c"
down_revision: str | None = "cb39832d29bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_research.evals.models.FixtureKind (parity-tested in the M9.6 suite).
_FIXTURE_KIND = (
    "positive",
    "negative_fabrication",
    "negative_samename",
    "negative_stale",
    "negative_unsupported",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE fixture_kind AS ENUM ({_enum_values_sql(_FIXTURE_KIND)})")

    # --- golden_fixture: the hand-verified ground truth as versioned rows ---
    # entity_ref is the resolved entity_id the fixture is about (everything keys on entity_id, never
    # a free-text name). expected_tier is the lowest-trust source tier still acceptable for the
    # field. fixture_kind = positive | the four negative traps (each a specific mechanism's expected
    # catch). One row per (entity_ref, field_key, fixture_kind) so seeding/ingest is idempotent.
    op.execute(
        """
        CREATE TABLE golden_fixture (
            id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_ref             uuid NOT NULL,
            field_key              text NOT NULL,
            expected_value_json    jsonb,
            expected_source_url    text,
            expected_tier          int,
            requires_evidence_span boolean NOT NULL DEFAULT true,
            fixture_kind           fixture_kind NOT NULL DEFAULT 'positive',
            mode                   research_mode,
            created_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT golden_fixture_tier_range
                CHECK (expected_tier IS NULL OR expected_tier BETWEEN 1 AND 4),
            CONSTRAINT golden_fixture_key UNIQUE (entity_ref, field_key, fixture_kind)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE golden_fixture IS 'M9.6 hand-verified eval ground truth as versioned "
        "rows (substrate §6). One row per (entity_ref, field_key, fixture_kind) — the UNIQUE makes "
        "seeding + human-spot-check ingest idempotent. fixture_kind = positive | negative_* "
        "(a planted trap a specific mechanism must catch); mode = the research mode (M1-M4) it "
        "exercises. Mirrors evals.FixtureKind / GoldClaim.'"
    )
    # Read path: the harness loads the whole suite; the entity index serves a per-entity read.
    op.execute("CREATE INDEX golden_fixture_entity_ref ON golden_fixture (entity_ref)")
    op.execute("CREATE INDEX golden_fixture_kind ON golden_fixture (fixture_kind)")

    # --- eval_run: append-only run audit (config snapshot + report) ---
    # config_snapshot_json pins the exact judge model / prompt version / thresholds / resolver set
    # the run scored, so a regression traces to the swap that caused it. report_json is the full
    # per-rubric + per-mechanism + regression EvalReport. Append-only by use (no UPDATE/DELETE).
    op.execute(
        """
        CREATE TABLE eval_run (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            suite                text NOT NULL,
            config_snapshot_json jsonb NOT NULL DEFAULT '{}',
            report_json          jsonb NOT NULL DEFAULT '{}',
            started_at           timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE eval_run IS 'M9.6 append-only eval-run audit (substrate §6 / Doc C §6). "
        "config_snapshot_json pins the judge model / prompt version / thresholds / resolver set "
        "the run scored (so a regression traces to the exact swap); report_json is the full "
        "per-rubric + per-mechanism + regression report. Feeds the M13.4 verification-health "
        "surface; never mutated.'"
    )
    # Trend/regression history is read newest-first, per suite.
    op.execute("CREATE INDEX eval_run_suite_started_at ON eval_run (suite, started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS eval_run_suite_started_at")
    op.execute("DROP TABLE IF EXISTS eval_run")
    op.execute("DROP INDEX IF EXISTS golden_fixture_kind")
    op.execute("DROP INDEX IF EXISTS golden_fixture_entity_ref")
    op.execute("DROP TABLE IF EXISTS golden_fixture")
    op.execute("DROP TYPE IF EXISTS fixture_kind")
