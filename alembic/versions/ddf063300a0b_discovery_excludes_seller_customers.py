"""Discovery excludes the seller's customers — the ``customers`` onboarding step and run kind, and
the ``excluded_by_brief`` discovery disposition.

Spec ``docs/superpowers/specs/2026-10-16-discovery-excludes-seller-customers-design.md``:

- onboarding researches the seller's existing customers in a ``customers`` step, and a brand
  onboarded before that gets a ``customers``-only run;
- a discovery candidate the brief's ``exclude`` list (or the seller's own domain) matched is
  recorded as ``excluded_by_brief``, naming the entry in ``excluded_by_entry``, exactly as a gate
  exclusion names its gate in ``excluded_by_gate``.

Downgrade FAILS LOUDLY while any row uses a new value (house convention, as ``ae4a5dfb3943``).

Revision ID: ddf063300a0b
Revises: 1ecc7437e5bc
Create Date: 2026-10-16 12:37:10.259450+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ddf063300a0b"
down_revision: str | None = "1ecc7437e5bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STEP_KINDS = (
    "('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research', 'persona')"
)
_NEW_STEP_KINDS = (
    "('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research', 'persona', "
    "'customers')"
)
_OLD_RUN_KINDS = "('full', 'personas')"
_NEW_RUN_KINDS = "('full', 'personas', 'customers')"
_OLD_DISPOSITIONS = (
    "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before', 'excluded')"
)
_NEW_DISPOSITIONS = (
    "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before', "
    "'excluded', 'excluded_by_brief')"
)


def _install(step_kinds: str, run_kinds: str, dispositions: str) -> None:
    op.execute("ALTER TABLE onboarding_step DROP CONSTRAINT onboarding_step_kind")
    op.execute(
        "ALTER TABLE onboarding_step ADD CONSTRAINT onboarding_step_kind "
        f"CHECK (kind IN {step_kinds})"
    )
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_kind")
    op.execute(
        f"ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_kind CHECK (kind IN {run_kinds})"
    )
    op.execute(
        "ALTER TABLE arv2_discovery_candidate DROP CONSTRAINT arv2_discovery_candidate_disposition"
    )
    op.execute(
        "ALTER TABLE arv2_discovery_candidate ADD CONSTRAINT arv2_discovery_candidate_disposition "
        f"CHECK (disposition IN {dispositions})"
    )


def upgrade() -> None:
    _install(_NEW_STEP_KINDS, _NEW_RUN_KINDS, _NEW_DISPOSITIONS)
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            ADD COLUMN excluded_by_entry text NULL,
            ADD CONSTRAINT arv2_discovery_candidate_excluded_entry
                CHECK ((disposition = 'excluded_by_brief') = (excluded_by_entry IS NOT NULL))
        """
    )
    op.execute(
        "COMMENT ON COLUMN arv2_discovery_candidate.excluded_by_entry IS 'The brief exclude entry "
        "(its name, or ''seller'' for the seller''s own domain) that matched this candidate.'"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM onboarding_step WHERE kind = 'customers')
               OR EXISTS (SELECT 1 FROM onboarding_run WHERE kind = 'customers')
               OR EXISTS (SELECT 1 FROM arv2_discovery_candidate
                          WHERE disposition = 'excluded_by_brief') THEN
                RAISE EXCEPTION 'cannot downgrade ddf063300a0b while customers steps or runs, or '
                    'excluded_by_brief candidates, exist';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        ALTER TABLE arv2_discovery_candidate
            DROP CONSTRAINT arv2_discovery_candidate_excluded_entry,
            DROP COLUMN excluded_by_entry
        """
    )
    _install(_OLD_STEP_KINDS, _OLD_RUN_KINDS, _OLD_DISPOSITIONS)
