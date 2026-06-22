"""m9.3 faithfulness judge — judge_policy + faithfulness_verdict (ENG-139)

Revision ID: 911a1beeb9c1
Revises: b3b636f67bd8
Create Date: 2026-06-21 18:10:00.000000+00:00

M9.3 (the verification layer's *accuracy* gate over synthesized claims): provenance proves a source
*said* something and corroboration proves tier≤3 sources *agree*; neither proves a **tier-4
LLM-synthesized** value is *entailed by its own cited evidence span*. The faithfulness judge
(LLM-as-judge, claim-level entailment) is that missing eval layer (substrate §6(3) / §0). This
migration adds only the M9.3 *config* + *audit* schema and — per the M9 isolation contract — alters
**no shared mutable surface**:

* ``judge_policy`` — versioned, per-client-overridable judge config (policy-as-data, conventions
  §2): the gateway ``judge_model`` id, the ``prompt_version``, and the ``supported_threshold`` the
  judge reads at construction, so a **judge-model swap is a config row, not a code change** (the
  swap is regression-checked by the M9.6 eval battery). Unlike M9.1's ``pre_spend_policy``
  (``rules_json`` blob), the judge policy is a small fixed set of typed columns (M09 §M9.3 data
  model), so it is stored as columns and read directly.
* ``faithfulness_verdict`` — append-only audit, **one row per ``(claim_id, judge_model,
  prompt_version)``** (the unique constraint *is* the idempotency/cache key: re-judging the same
  claim with the same model+prompt returns the cached verdict and makes no second LLM call; bumping
  ``prompt_version`` forces a fresh judgment). It records the verdict, score, rationale, cost, and
  latency so M12's provenance index can cite "judged faithful by ``<model>@<prompt_version>``" and
  the Doc C §6 verification-health surface can read the tier-4 faithfulness pass-rate.

The verdict itself rides the **already-mutable** ``claim.verification_status`` column (the
0002/0004/0008 trigger allow-list) — the judge sets ``verified`` (supported), ``rejected``
(unsupported/contradicted), or ``flagged`` (partial) via
:func:`clue_research.claimstore.record_verification` — so M9.3 needs **no trigger change and no
``claim`` ALTER**. The ``claim_tier4_verified_requires_span`` CHECK (0002) stays the DB backstop, so
a span-less tier-4 claim can never be flipped to ``verified`` even through the judge (it is
auto-rejected by the structural pre-check before any LLM call anyway).

``judge_verdict`` mirrors :class:`clue_research.core.enums.JudgeVerdict` (a *core* enum — the
verdict crosses the M5.1/M8/M11 caller boundary, so it lives in ``core``; the DB↔enum parity test
is ``test_faithfulness.py::test_judge_verdict_enum_matches_core``). ``downgrade()`` cleanly reverses
``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "911a1beeb9c1"
down_revision: str | None = "b3b636f67bd8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_research.core.enums.JudgeVerdict (parity-tested in the M9.3 suite).
_JUDGE_VERDICT = ("supported", "partial", "unsupported", "contradicted")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE judge_verdict AS ENUM ({_enum_values_sql(_JUDGE_VERDICT)})")

    # --- judge_policy: versioned judge config as data (per-client overridable) ---
    # Typed columns (M09 §M9.3): judge_model (a gateway model id), prompt_version (the versioned
    # entailment prompt), supported_threshold (the 0..1 score floor for a `supported` verdict to
    # promote). client_id NULL = the global default policy; the loader reads the most-specific
    # (per-client > global) row, latest version. A model/prompt/threshold change is a row, not code.
    op.execute(
        """
        CREATE TABLE judge_policy (
            policy_id           text PRIMARY KEY,
            client_id           text,
            judge_model         text NOT NULL,
            prompt_version      text NOT NULL,
            supported_threshold double precision NOT NULL,
            version             int NOT NULL DEFAULT 1,
            created_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT judge_policy_version_positive CHECK (version >= 1),
            CONSTRAINT judge_policy_threshold_unit_interval
                CHECK (supported_threshold >= 0 AND supported_threshold <= 1)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE judge_policy IS 'M9.3 faithfulness-judge config as versioned data "
        "(policy-as-data, conventions §2). The judge reads the most-specific row (per-client > "
        "global); client_id NULL = the global default policy. judge_model is a gateway model id — "
        "swapping it is a config row, regression-checked by the M9.6 eval battery.'"
    )
    # Resolution lookup: the loader selects by client_id (the NULL-scoped global row is found by the
    # same index). ``NULLS NOT DISTINCT`` (pg15+) so the global default (client_id IS NULL) is ONE
    # slot per version, not many — otherwise a plain UNIQUE treats NULLs as distinct and would admit
    # duplicate (NULL, version) global rows the loader could then resolve non-deterministically
    # (same pattern as 0009's source_profile slots).
    op.execute(
        "CREATE UNIQUE INDEX judge_policy_scope_version "
        "ON judge_policy (client_id, version) NULLS NOT DISTINCT"
    )

    # --- faithfulness_verdict: append-only audit; the unique key is the idempotency/cache key ---
    # One row per (claim_id, judge_model, prompt_version): the judge SELECTs it first and returns
    # the cached verdict on a hit (no second LLM call); a prompt_version bump misses → a fresh
    # judgment. Append-only by use — no UPDATE/DELETE path. score is the 0..1 entailment
    # confidence; cost_cents / latency_ms make per-judge spend queryable (Doc C §6).
    op.execute(
        """
        CREATE TABLE faithfulness_verdict (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id       uuid NOT NULL,
            verdict        judge_verdict NOT NULL,
            score          double precision NOT NULL,
            rationale      text NOT NULL DEFAULT '',
            judge_model    text NOT NULL,
            prompt_version text NOT NULL,
            cost_cents     numeric NOT NULL DEFAULT 0,
            latency_ms     double precision,
            judged_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT faithfulness_verdict_score_unit_interval
                CHECK (score >= 0 AND score <= 1),
            CONSTRAINT faithfulness_verdict_cost_nonneg CHECK (cost_cents >= 0),
            CONSTRAINT faithfulness_verdict_cache_key
                UNIQUE (claim_id, judge_model, prompt_version)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE faithfulness_verdict IS 'M9.3 append-only faithfulness-judge audit "
        "(substrate §6(3) / Doc C §6). One row per (claim_id, judge_model, prompt_version) — the "
        "UNIQUE is the cache key (re-judging the same model+prompt returns the cached verdict, "
        "no second LLM call; a prompt_version bump forces a fresh judgment). Cited by M12 "
        "provenance; never mutated.'"
    )
    # Read path: every verdict for a claim (provenance index / re-judge cache probe).
    op.execute("CREATE INDEX faithfulness_verdict_claim_id ON faithfulness_verdict (claim_id)")
    op.execute("CREATE INDEX faithfulness_verdict_judged_at ON faithfulness_verdict (judged_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS faithfulness_verdict_judged_at")
    op.execute("DROP INDEX IF EXISTS faithfulness_verdict_claim_id")
    op.execute("DROP TABLE IF EXISTS faithfulness_verdict")
    op.execute("DROP INDEX IF EXISTS judge_policy_scope_version")
    op.execute("DROP TABLE IF EXISTS judge_policy")
    op.execute("DROP TYPE IF EXISTS judge_verdict")
