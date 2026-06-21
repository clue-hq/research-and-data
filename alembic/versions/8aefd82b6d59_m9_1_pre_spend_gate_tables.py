"""m9.1 pre-spend gate — pre_spend_policy + gate_decision (ENG-130)

Revision ID: 8aefd82b6d59
Revises: 82831d3fa4c5
Create Date: 2026-06-21 10:43:41.125756+00:00

M9.1 (the verification layer's entry gate): the cheapest verification is the one that prevents
spend on a doomed claim (substrate §6(1)). This migration adds the two M9.1 persistence objects —
*config* and *audit* — leaving the ``claim`` table untouched (M9 alters no shared table):

* ``pre_spend_policy`` — versioned, per-client/ICP-overridable gate rules as data (policy-as-data,
  conventions §2): which gates run and how strict, read by the ``PreSpendGate`` at construction so
  flipping a rule is a config row, not a code change. The structured ``rules_json`` parses into the
  ``verification.PreSpendPolicy`` model.
* ``gate_decision`` — an append-only audit row per ``PreSpendGate.check`` decision, so
  "claims blocked pre-spend" is a measurable verification-health signal (Doc C §6). Append-only by
  use (like ``source_yield``): no in-place mutation path is created.

The per-field ``gate_spec`` (M9.1) is carried in the **existing** ``field_definition.gate`` text
column (same column, declared JSON contents) — no schema change there.

``pre_spend_verdict`` mirrors :class:`clue_research.core.enums.PreSpendVerdict`; the enum-parity
test ``test_prespend_gate.py::test_pre_spend_verdict_enum_matches_core`` guards drift (the DB and
the domain model cannot import each other's spelling). ``entity_type`` is reused from 0002 (no new
enum, no downgrade burden for it). ``downgrade()`` cleanly reverses ``upgrade()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8aefd82b6d59"
down_revision: str | None = "82831d3fa4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_research.core.enums.PreSpendVerdict (parity-tested in the M9.1 test suite).
_PRE_SPEND_VERDICT = ("pass", "reject")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE pre_spend_verdict AS ENUM ({_enum_values_sql(_PRE_SPEND_VERDICT)})")

    # --- pre_spend_policy: versioned gate rules as data (per-client/ICP overridable) ---
    op.execute(
        """
        CREATE TABLE pre_spend_policy (
            policy_id    text PRIMARY KEY,
            client_id    text,
            icp_version  int,
            rules_json   jsonb NOT NULL,
            version      int NOT NULL DEFAULT 1,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT pre_spend_policy_version_positive CHECK (version >= 1),
            CONSTRAINT pre_spend_policy_icp_version_positive
                CHECK (icp_version IS NULL OR icp_version >= 1),
            CONSTRAINT pre_spend_policy_rules_is_object
                CHECK (jsonb_typeof(rules_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE pre_spend_policy IS 'M9.1 pre-spend gate rules as versioned data "
        "(policy-as-data, conventions §2). rules_json parses into verification.PreSpendPolicy; the "
        "gate reads the most-specific row (per-ICP > per-client > global). client_id NULL = the "
        "global default policy; icp_version NULL = the client-wide policy.'"
    )
    # Resolution lookup: the gate selects by (client_id, icp_version); the NULL-scoped global row is
    # found by the same index. A client+icp slot is unique per version.
    op.execute(
        "CREATE UNIQUE INDEX pre_spend_policy_scope_version "
        "ON pre_spend_policy (client_id, icp_version, version)"
    )

    # --- gate_decision: append-only audit of every PreSpendGate.check decision ---
    # entity_type reuses the 0002 enum; pre_spend_verdict is this migration's enum. reasons is the
    # typed-reason array carried on a REJECT (field unknown, tier not in plan, value invalid, entity
    # unresolved/merged/weakly-keyed, lock held by another run). Append-only by use (like
    # source_yield) — there is no UPDATE/DELETE path; "claims blocked pre-spend" is COUNT(*) on it.
    op.execute(
        """
        CREATE TABLE gate_decision (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id        uuid NOT NULL,
            entity_id     uuid NOT NULL,
            entity_type   entity_type NOT NULL,
            field_key     text NOT NULL,
            source_tier   int NOT NULL,
            decision      pre_spend_verdict NOT NULL,
            reasons       jsonb NOT NULL DEFAULT '[]'::jsonb,
            decided_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT gate_decision_source_tier_range CHECK (source_tier BETWEEN 1 AND 4),
            CONSTRAINT gate_decision_reasons_is_array CHECK (jsonb_typeof(reasons) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE gate_decision IS 'M9.1 append-only audit of pre-spend gate decisions "
        "(substrate §6(1) / Doc C §6). One row per PreSpendGate.check; reasons carries the typed "
        "REJECT reasons. Append-only by use — no mutation path.'"
    )
    # Read paths: per-run (a run's blocked set), per (entity, field) (was this pair gated?), and by
    # time (the verification-health rollup).
    op.execute("CREATE INDEX gate_decision_run_id ON gate_decision (run_id)")
    op.execute("CREATE INDEX gate_decision_entity_field ON gate_decision (entity_id, field_key)")
    op.execute("CREATE INDEX gate_decision_decided_at ON gate_decision (decided_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gate_decision_decided_at")
    op.execute("DROP INDEX IF EXISTS gate_decision_entity_field")
    op.execute("DROP INDEX IF EXISTS gate_decision_run_id")
    op.execute("DROP TABLE IF EXISTS gate_decision")
    op.execute("DROP INDEX IF EXISTS pre_spend_policy_scope_version")
    op.execute("DROP TABLE IF EXISTS pre_spend_policy")
    op.execute("DROP TYPE IF EXISTS pre_spend_verdict")
