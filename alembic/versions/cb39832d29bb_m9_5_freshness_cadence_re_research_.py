"""m9.5 freshness cadence + re-research candidate (ENG-149)

Revision ID: cb39832d29bb
Revises: 971febbe2906
Create Date: 2026-06-21 22:45:45.199728+00:00

M9.5 (the verification layer's *freshness* half — "the master database is a myth"): the workforce
and tech stack churn constantly, so freshness is a first-class signal, not an afterthought
(substrate §6 / Doc C §1). Every claim has ``observed_at`` + a field-level TTL; the merge view
treats a stale claim as refresh-eligible, scoring discounts it, and re-research runs on a cadence
(~90-day default; signal fields faster; personal fields shorter — Doc D §4). This migration adds
only the M9.5 *config* + *emission* schema and — per the M9 isolation contract — alters **no shared
mutable surface**:

* ``cadence_policy`` — versioned, per-client-overridable freshness/refresh config as data
  (policy-as-data, conventions §2), **one row per field-class**: the ``ttl`` (the staleness
  threshold a claim of this class crosses fresh→stale) and the ``refresh_cadence`` (the re-research
  spacing the candidate emitter uses for ``due_at``). The defaults mirror ``config.FreshnessTtls``
  (field-class TTLs) so the merge and the freshness engine read one shared shape; changing a class's
  cadence is a config row, **not a code change** (regression-checked by the M9.6 eval battery). The
  personal-claim **retention horizon** (which makes a claim ``expired``) is *not* a column here — it
  is owned by M10.5 and referenced from ``config.RetentionTtls`` (M09 §M9.5: "referenced here, not
  redefined").
* ``re_research_candidate`` — the append-only emission queue M7's durable executor drains. One row
  per ``(entity_id, field_key, due_at)`` (the UNIQUE *is* the idempotency key: re-emitting the same
  due window writes no new row). It carries the ``stale_claim_ids`` due for refresh, the ``due_at``
  (earliest reference_time + refresh_cadence among them), and a tier-driven ``priority`` (lower =
  sooner). M9.5 *detects and emits* these; **M7 schedules and runs** the refresh (M9.5 never
  executes — the executor swap Postgres→Temporal stays behind this row seam).

The freshness disposition itself is **not** a claim column. ``claim.freshness_state`` was the M09
spec's original intent, but the substrate models freshness as a *derived* property: the M1.2 merge
view already computes ``FRESH``/``STALE`` onto ``CurrentValue.freshness_state`` from
``observed_at|collected_at`` vs the field TTL (never onto the immutable, append-only claim row — the
0004 trigger allow-list is only ``superseded_by/verification_status/corroborations``). M9.5 follows
that established pattern: the per-claim verdict is the *computed* ``Staleness.state`` returned by
``Freshness.evaluate`` (FRESH/STALE/EXPIRED), and ``expired`` personal claims are surfaced to M10.5
for age-out (``Freshness.due_for_age_out``) rather than written to a column. So M9.5 needs **no new
enum** (it reuses the existing ``field_class`` enum from 0003 for ``cadence_policy``), and **no
``claim`` ALTER, no trigger change**.

``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cb39832d29bb"
down_revision: str | None = "971febbe2906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- cadence_policy: versioned freshness/refresh config as data (per field-class) ---
    # Typed columns (M09 §M9.5): ttl (the fresh->stale threshold) and refresh_cadence (the
    # re-research due_at spacing) per field_class. client_id NULL = the global default; the loader
    # reads the most-specific scope (per-client > global), latest version per field_class. The
    # retention horizon (what makes a claim *expired*) is deliberately NOT here — owned by M10.5,
    # referenced from config.RetentionTtls (so the lawful-retention horizon has one home, not two).
    op.execute(
        """
        CREATE TABLE cadence_policy (
            policy_id       text PRIMARY KEY,
            client_id       text,
            field_class     field_class NOT NULL,
            ttl             interval NOT NULL,
            refresh_cadence interval NOT NULL,
            version         int NOT NULL DEFAULT 1,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT cadence_policy_version_positive CHECK (version >= 1),
            CONSTRAINT cadence_policy_ttl_positive CHECK (ttl > interval '0'),
            CONSTRAINT cadence_policy_cadence_positive CHECK (refresh_cadence > interval '0')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE cadence_policy IS 'M9.5 freshness/refresh config as versioned data "
        "(policy-as-data, conventions §2), one row per field-class. ttl = the fresh->stale "
        "threshold; refresh_cadence = the re-research due_at spacing. The engine reads the "
        "most-specific scope (per-client > global); client_id NULL = the global default. Defaults "
        "mirror config.FreshnessTtls; the retention horizon (expired) is referenced from "
        "config.RetentionTtls (M10.5-owned), not stored here. Regression-checked by the M9.6 "
        "eval battery.'"
    )
    # Resolution lookup: one slot per (client_id, field_class, version). ``NULLS NOT DISTINCT``
    # (pg15+) so the global default (client_id IS NULL) is ONE slot per (field_class, version), not
    # many — otherwise a plain UNIQUE treats NULLs as distinct and would admit duplicate global rows
    # the loader could resolve non-deterministically (the M9.1 NULL-slot gap / 0009's source_profile
    # slots; applied here from the start so M9.5 never carries it).
    op.execute(
        "CREATE UNIQUE INDEX cadence_policy_scope_class_version "
        "ON cadence_policy (client_id, field_class, version) NULLS NOT DISTINCT"
    )

    # --- re_research_candidate: append-only emission queue; the UNIQUE is the idempotency key ---
    # One row per (entity_id, field_key, due_at): the freshness engine detects stale-and-due claims
    # and emits them here; M7's durable executor drains by due_at/priority and runs the refresh.
    # Append-only by use — re-emitting the same (entity, field, due_at) window is a no-op
    # (ON CONFLICT DO NOTHING). stale_claim_ids is the set of live claims due for refresh; priority
    # is tier-driven (lower = sooner). No FK to claim (mirrors the M9.3/M9.4 audit tables): a
    # candidate may name a claim that is later superseded, and the row survives for the audit trail.
    op.execute(
        """
        CREATE TABLE re_research_candidate (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id       uuid NOT NULL,
            field_key       text NOT NULL,
            stale_claim_ids uuid[] NOT NULL DEFAULT '{}',
            due_at          timestamptz NOT NULL,
            priority        int NOT NULL DEFAULT 5,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT re_research_candidate_priority_nonneg CHECK (priority >= 0),
            CONSTRAINT re_research_candidate_key UNIQUE (entity_id, field_key, due_at)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE re_research_candidate IS 'M9.5 append-only re-research emission queue "
        "(substrate §6 / Doc C §1). One row per (entity_id, field_key, due_at) — the UNIQUE is the "
        "idempotency key (re-emitting the same due window is a no-op). M9.5 detects + emits; M7 "
        "schedules + runs the refresh (M9.5 never executes). priority is tier-driven (lower = "
        "sooner).'"
    )
    # Drain path: M7 reads the oldest-due candidates first; the entity index serves a per-account
    # refresh scope.
    op.execute("CREATE INDEX re_research_candidate_due_at ON re_research_candidate (due_at)")
    op.execute("CREATE INDEX re_research_candidate_entity ON re_research_candidate (entity_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS re_research_candidate_entity")
    op.execute("DROP INDEX IF EXISTS re_research_candidate_due_at")
    op.execute("DROP TABLE IF EXISTS re_research_candidate")
    op.execute("DROP INDEX IF EXISTS cadence_policy_scope_class_version")
    op.execute("DROP TABLE IF EXISTS cadence_policy")
