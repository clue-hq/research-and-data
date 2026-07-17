"""m10.3 appropriateness/use gate — client_policy + use_decision (+ use_reason enum)

Revision ID: 8074999828fe
Revises: 3df3b2f629fd
Create Date: 2026-06-25 00:00:00.000000+00:00

M10.3 is the *second* gate Doc D was written to add (Doc D §3/§5): the accuracy/identity-binding
gate (M9.3/M9.4) answers "is it true, and is it *this* person?"; this gate answers the orthogonal
"*may we lawfully and tastefully use* this true claim on this person, in this jurisdiction, for this
client?" — a pure decision over ``use_class × jurisdiction × client_policy``. It is the first M10
migration (M10.1 jurisdiction + M10.2 use-class tagging were registry-row / config-only) and — per
the phase-3 pre-flight isolation contract (PF-2) — adds **only side tables keyed on ``claim_id``**
and a new enum; it alters **no shared mutable surface** (no ``claim`` ALTER, no immutable-guard
``REPLACE``, no ``merge`` change):

* ``client_policy`` — the versioned, per-client-overridable use-gate policy as data (policy-as-data,
  conventions §2; Doc D §6 "postures are not forks, they are settings on one machinery"). Stores the
  ``posture`` label, the ``use_class → disposition`` ``allow_map`` (the materialized posture — the
  authoritative parameters the gate reads), the per-regime ``regime_overrides`` (the "design strict,
  switch down" relaxation, keyed by regime — M10.4 fills these), and a ``version`` the gate records
  on every decision. A posture switch / allow-map edit is a config row, **not a code path** (Doc D
  §6). ``client_id NULL`` = the global default policy; the loader reads the most-specific
  (per-client > global) row, latest version, with a deterministic ``created_at``/``policy_id``
  tie-break. M10.4 extends this table (``store_sensitive`` sub-flag, ``gather_scope`` allow-list,
  legally-reviewed ``sensitive`` override register) — it is the M10 posture store, introduced here
  because M10.3's gate needs the versioned ``policy_version``.
* ``use_decision`` — the use-gate verdict, **one current row per ``(claim_id, policy_version)``**
  (the unique constraint *is* the idempotency key: re-evaluating the same claim under the same
  policy version with the same inputs is a no-op; a policy bump → a fresh decision under the new
  version,
  the old version's row preserved). Holds ``usable_for_outreach`` (the single bit M12 reads), the
  typed ``reason`` (``use_reason``), the deciding ``regime`` (audit — *which* jurisdiction the
  verdict was reached under, so the M10.3×M10.1 interaction is queryable; not in the core seam), and
  ``policy_version``. This is the side-table home of
  :class:`clue_core.compliance.UseDecision` — explicitly a verdict **settable *after* the
  claim is inserted** (PF-2: "a use verdict is settable post-insert (a side-table row), which an
  immutable born-column would forbid anyway"), never a born ``claim`` column, so M10 never touches
  the append-only immutable guard. Unlike the strictly content-addressed (append-only)
  ``faithfulness_verdict`` / ``identity_binding_eval``, the use decision is a *pure, re-derivable*
  function of the claim's (immutable) ``use_class``, the contact's *current* resolved regime (M10.1,
  itself a superseding claim), and the policy — so only the **current** verdict is meaningful and
  the row is refreshed in place when a jurisdiction re-resolution flips the decision under the same
  policy version (settable post-insert). Distinct from ``faithfulness_verdict`` (accuracy) and the
  claim's ``identity_binding`` (identity) so the two gates stay separately queryable (Doc D §5 — "we
  used something we shouldn't have" is a different, separately-measurable failure from "we
  fabricated").

``use_reason`` mirrors :class:`clue_core.enums.UseReason` (a *core* enum — the verdict
crosses the M12/M13 caller boundary, so it lives in ``core``; the DB↔enum parity test is
``tests/compliance/test_use_gate.py::test_use_reason_enum_matches_core`` + the no-DB tuple guard).
There is deliberately **no ``objected`` member** — a data-subject objection (Art. 21) and retention
age-out (``FreshnessState.EXPIRED``) are *merge/substrate* exclusions (decisions D-OBJ / D-EXP),
handled by M10.5 tombstone-before-read, never a per-claim use reason. ``downgrade()`` cleanly
reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8074999828fe"
down_revision: str | None = "3df3b2f629fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_core.enums.UseReason (parity-tested in the M10.3 suite, with order).
_USE_REASON = ("allowed", "sensitive_locked", "use_class_disallowed_for_regime")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE use_reason AS ENUM ({_enum_values_sql(_USE_REASON)})")

    # --- client_policy: versioned use-gate policy as data (per-client overridable) ---
    # posture is the descriptive Doc D §6 label; allow_map is the AUTHORITATIVE materialized posture
    # (use_class -> disposition); regime_overrides is the per-regime relaxation the gate reads down
    # from the strict default ({} until M10.4 fills it). client_id NULL = the global default policy;
    # the loader reads the most-specific (per-client > global) row, latest version. A posture switch
    # or allow-map edit is a config row, not code (Doc D §6). M10.4 extends this table.
    op.execute(
        """
        CREATE TABLE client_policy (
            policy_id        text PRIMARY KEY,
            client_id        text,
            posture          text NOT NULL DEFAULT 'conservative_default',
            allow_map        jsonb NOT NULL DEFAULT
                '{"professional-public": "usable",
                  "personal-public-non-sensitive": "usable",
                  "sensitive": "stored_unusable"}',
            regime_overrides jsonb NOT NULL DEFAULT '{}',
            version          int NOT NULL DEFAULT 1,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT client_policy_version_positive CHECK (version >= 1),
            CONSTRAINT client_policy_allow_map_is_object
                CHECK (jsonb_typeof(allow_map) = 'object'),
            CONSTRAINT client_policy_regime_overrides_is_object
                CHECK (jsonb_typeof(regime_overrides) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE client_policy IS 'M10.3/M10.4 use-gate policy as versioned data "
        "(policy-as-data, conventions §2; Doc D §6 — postures are settings on one machinery, not "
        "forks). The gate reads the most-specific row (per-client > global); client_id NULL = the "
        "global default policy. allow_map is the authoritative materialized posture; "
        "regime_overrides is the per-regime relaxation. version is recorded on every use_decision. "
        "A posture switch / allow-map edit is a config row, not code.'"
    )
    # Resolution lookup: the loader selects by client_id (the NULL-scoped global row is found by the
    # same index). ``NULLS NOT DISTINCT`` (pg15+) so the global default (client_id IS NULL) is ONE
    # slot per version, not many — otherwise a plain UNIQUE treats NULLs as distinct and would admit
    # duplicate (NULL, version) global rows the loader could then resolve non-deterministically (the
    # gap M9.3 closed for judge_policy / M9.4 for binding_policy; applied here from the start).
    op.execute(
        "CREATE UNIQUE INDEX client_policy_scope_version "
        "ON client_policy (client_id, version) NULLS NOT DISTINCT"
    )

    # --- use_decision: the current use-gate verdict; the unique key is the idempotency key ---
    # One CURRENT row per (claim_id, policy_version): the gate UPSERTs it (settable post-insert,
    # PF-2). The decision is a pure, re-derivable function of the claim's immutable use_class, the
    # contact's CURRENT resolved regime (M10.1), and the policy — so an identical re-evaluation is a
    # no-op (cache hit), but a jurisdiction re-resolution that flips the verdict under the same
    # policy version refreshes the row in place (ON CONFLICT DO UPDATE), so M12 always reads the
    # current verdict. usable_for_outreach is the single bit M12 reads via is_outreach_promotable;
    # reason is the typed justification (use_reason); regime records which jurisdiction decided it
    # (audit; not in the core seam); policy_version pins the client_policy row. No FK to claim
    # (mirrors faithfulness_verdict / identity_binding_eval): the verdict may be written for an
    # in-flight claim and survives the claim's supersession.
    op.execute(
        """
        CREATE TABLE use_decision (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id            uuid NOT NULL,
            usable_for_outreach boolean NOT NULL,
            reason              use_reason NOT NULL,
            regime              text NOT NULL,
            policy_version      int NOT NULL,
            evaluated_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT use_decision_policy_version_positive CHECK (policy_version >= 1),
            CONSTRAINT use_decision_cache_key UNIQUE (claim_id, policy_version)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE use_decision IS 'M10.3 appropriateness/use-gate verdict (Doc D §3/§5). "
        "One CURRENT row per (claim_id, policy_version) — the UNIQUE is the idempotency key; the "
        "gate UPSERTs (settable post-insert, PF-2). The verdict is a pure function of "
        "the claim use_class, the contact current resolved regime (M10.1), and the policy, so an "
        "identical re-eval is a no-op and a jurisdiction re-resolution that flips it refreshes the "
        "row in place (so M12 reads the current verdict). Side-table home of "
        "core.compliance.UseDecision; regime is an audit column (not in the seam). Distinct from "
        "faithfulness_verdict (accuracy) and claim.identity_binding (identity) so the two gates "
        "stay separately queryable; cited by M12 provenance.'"
    )
    # Read path: every decision for a claim (provenance index / re-evaluate cache probe).
    op.execute("CREATE INDEX use_decision_claim_id ON use_decision (claim_id)")
    op.execute("CREATE INDEX use_decision_evaluated_at ON use_decision (evaluated_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS use_decision_evaluated_at")
    op.execute("DROP INDEX IF EXISTS use_decision_claim_id")
    op.execute("DROP TABLE IF EXISTS use_decision")
    op.execute("DROP INDEX IF EXISTS client_policy_scope_version")
    op.execute("DROP TABLE IF EXISTS client_policy")
    op.execute("DROP TYPE IF EXISTS use_reason")
