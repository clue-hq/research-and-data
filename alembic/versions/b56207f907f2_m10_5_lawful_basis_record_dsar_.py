"""m10_5 lawful_basis_record + dsar_tombstone + outreach_objected

Revision ID: b56207f907f2
Revises: 196d37e4a179
Create Date: 2026-06-25 12:42:26.939432+00:00

M10.5 makes "why are we allowed to hold this" and "stop holding this" first-class, queryable
operations rather than assumptions (Doc D §4). It is the third M10 migration (M10.1 jurisdiction +
M10.2 use-class tagging were registry/config only; M10.3 added ``client_policy``/``use_decision``;
M10.4 extended ``client_policy``) and — per the phase-3 pre-flight isolation contract (PF-2) — adds
**only side tables keyed on ``claim_id`` / ``contact_entity_id``** plus the per-contact objection
marker; it alters **no shared mutable surface** (no ``claim`` ALTER, no immutable-guard ``REPLACE``,
no ``merge`` change). Erasure itself is implemented purely as append-only
**supersession-by-tombstone** over the existing claim store (PF-5: the tombstone is a ``claim`` row
with ``extraction_method = human``), so no new deletion path and no execution-engine-specific code
(the same machinery works under the Postgres state machine or Temporal).

Tables:

* ``lawful_basis_record`` — the lawful basis recorded as provenance alongside each personal claim
  (Doc D §4). One **current** row per ``claim_id`` (the UNIQUE is the idempotency key; settable
  post-insert / UPSERT-refreshable, PF-2 — like ``use_decision``): the basis is a pure function of
  the claim's immutable ``use_class``, the contact's resolved regime (M10.1), and the client policy
  (M10.4), so only the current basis is meaningful. ``lawful_basis`` is the derived basis
  (``professional-public`` B2B under GDPR → ``legitimate_interest`` + an ``lia_ref`` pointer to the
  client's documented balancing test; ``sensitive`` → ``none`` for outreach, reinforcing the M10.3
  Art. 9 floor); ``third_party_collected`` is the Art. 14 transparency flag (personal data collected
  from sources other than the data subject — almost always true in cold B2B research); ``regime`` is
  the audit copy of the deciding jurisdiction; ``retention_until`` is the use-class-keyed retention
  horizon (``collected_at`` + the personal-claim TTL — shorter than firmographic, Doc D §4).
* ``dsar_tombstone`` — the erasure/objection/age-out audit marker (Doc D §4). One row per erased
  claim (``erased_claim_id`` UNIQUE → idempotent: a claim is tombstoned once), recording the
  superseding ``tombstone_claim_id``, the ``contact_entity_id`` + ``tenant_id`` the request was for
  (a DSAR is always scoped to one controller), the ``reason``, and an optional ``scope`` note.
  A value-redacted, append-only record of the erasure (substrate §1 — never a destructive UPDATE):
  the tombstone ``claim`` row is written ``REJECTED`` so the merge can never serve it, which is what
  makes ``current_value`` / the handoff return none of the erased values.
* ``outreach_objected`` — the GDPR Art. 21 (near-absolute right to object to direct-marketing
  processing) marker. One row per ``(contact_entity_id, tenant_id)``; an objected contact's outreach
  hooks are tombstoned before the merge read (D-OBJ: a **substrate** exclusion, not a use-gate
  reason — there is deliberately no ``UseReason.objected``), and the marker lets a re-sweep
  re-suppress any newly-arrived hooks.

``lawful_basis`` and ``reason`` are stored as **TEXT with a CHECK** (not a DB enum) — they are
compliance-local closed vocabularies (``clue_research.compliance`` ``LawfulBasis`` /
``TombstoneReason``), not ``core.enums`` members that cross the M12/M13 caller boundary, so they
follow the ``use_decision.regime`` text-not-enum precedent rather than minting an orphan DB enum.
The CHECK value sets are kept in lock-step with the Python ``StrEnum``s by a **no-DB** drift guard
(``tests/compliance/test_dsar.py`` / ``test_lawful_basis.py``) that runs in ``make check``.
``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b56207f907f2"
down_revision: str | None = "196d37e4a179"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_research.compliance.lawful_basis.LawfulBasis (parity-tested, no-DB drift guard).
_LAWFUL_BASIS = ("legitimate_interest", "consent", "none")
# Mirrors clue_research.compliance.dsar.TombstoneReason (parity-tested, no-DB drift guard).
_TOMBSTONE_REASON = ("erasure", "objection", "retention_expiry")


def _check_in(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    # --- lawful_basis_record: the lawful basis recorded as provenance (Doc D §4) ---
    # One CURRENT row per claim_id (the UNIQUE is the idempotency key); settable post-insert /
    # UPSERT (PF-2). No FK to claim (mirrors use_decision / faithfulness_verdict): the basis may be
    # recorded for an in-flight claim and survives the claim's supersession. lawful_basis / regime
    # are text (compliance-local vocab; the use_decision.regime precedent); the basis set is
    # CHECK-guarded and drift-tested against the Python enum.
    op.execute(
        f"""
        CREATE TABLE lawful_basis_record (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id              uuid NOT NULL,
            lawful_basis          text NOT NULL,
            lia_ref               text,
            third_party_collected boolean NOT NULL DEFAULT true,
            regime                text NOT NULL,
            retention_until       timestamptz,
            recorded_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT lawful_basis_record_basis_valid
                CHECK ({_check_in("lawful_basis", _LAWFUL_BASIS)}),
            CONSTRAINT lawful_basis_record_claim_unique UNIQUE (claim_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE lawful_basis_record IS 'M10.5 lawful basis recorded as provenance per "
        "personal claim (Doc D §4). One current row per claim_id (UNIQUE = idempotency key; "
        "settable post-insert/UPSERT, PF-2). lawful_basis is derived from (use_class, regime, "
        "policy): professional-public GDPR -> legitimate_interest + lia_ref; sensitive -> none "
        "(reinforces the M10.3 Art. 9 floor). third_party_collected is the Art. 14 flag; "
        "retention_until is the use-class-keyed retention horizon (shorter than firmographic). "
        "No FK to claim (survives supersession).'"
    )
    # The Art. 14 "notice may be owed" aggregate joins third-party-collected rows to claim. A plain
    # b-tree over the low-cardinality, mostly-true boolean cannot accelerate selecting the majority
    # value (the planner seq-scans); a PARTIAL index on claim_id WHERE third_party_collected matches
    # the report's predicate and supports the join over just the third-party subset.
    op.execute(
        "CREATE INDEX lawful_basis_record_third_party "
        "ON lawful_basis_record (claim_id) WHERE third_party_collected"
    )

    # --- dsar_tombstone: the erasure/objection/age-out audit marker (Doc D §4) ---
    # One row per erased claim (erased_claim_id UNIQUE → a claim is tombstoned once; the erase path
    # is idempotent). Records the superseding tombstone_claim_id, the contact_entity_id + tenant_id
    # the request was for (a DSAR is scoped to one controller), the reason, and an optional scope
    # note. A value-redacted, append-only record (the tombstone claim row carries the redaction +
    # REJECTED status that makes current_value/handoff return none of the erased values).
    op.execute(
        f"""
        CREATE TABLE dsar_tombstone (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            erased_claim_id     uuid NOT NULL,
            tombstone_claim_id  uuid NOT NULL,
            contact_entity_id   uuid NOT NULL,
            tenant_id           text NOT NULL,
            reason              text NOT NULL,
            scope               text,
            erased_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT dsar_tombstone_reason_valid
                CHECK ({_check_in("reason", _TOMBSTONE_REASON)}),
            CONSTRAINT dsar_tombstone_erased_claim_unique UNIQUE (erased_claim_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE dsar_tombstone IS 'M10.5 erasure/objection/age-out audit marker "
        "(Doc D §4). One row per erased claim (erased_claim_id UNIQUE → idempotent). Erasure is "
        "append-only supersession-by-tombstone: the tombstone is a claim row "
        "(extraction_method=human, PF-5) written REJECTED + value-redacted, so the merge never "
        "serves it and current_value/handoff return none of the erased values; no destructive "
        "delete (substrate §1). reason in {erasure, objection, retention_expiry}; tenant_id scopes "
        "the DSAR to one controller.'"
    )
    op.execute(
        "CREATE INDEX dsar_tombstone_contact ON dsar_tombstone (contact_entity_id, tenant_id)"
    )

    # --- outreach_objected: the Art. 21 objection marker (D-OBJ — a substrate exclusion) ---
    # One row per (contact_entity_id, tenant_id). An objected contact's outreach hooks are
    # tombstoned before the merge read (NOT a use-gate reason — there is no UseReason.objected); the
    # marker is durable so a re-sweep re-suppresses newly-arrived hooks and the objection stays
    # queryable.
    op.execute(
        """
        CREATE TABLE outreach_objected (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            contact_entity_id  uuid NOT NULL,
            tenant_id          text NOT NULL,
            note               text NOT NULL DEFAULT '',
            objected_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT outreach_objected_contact_tenant_unique UNIQUE (contact_entity_id, tenant_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE outreach_objected IS 'M10.5 GDPR Art. 21 objection marker (near-absolute "
        "right to object to direct-marketing processing). One row per (contact_entity_id, "
        "tenant_id). D-OBJ: objection is a substrate exclusion (the contact''s outreach hooks are "
        "tombstoned before the merge read), NOT a use-gate reason (no UseReason.objected). The "
        "marker is durable so a re-sweep re-suppresses newly-arrived hooks.'"
    )
    op.execute("CREATE INDEX outreach_objected_tenant ON outreach_objected (tenant_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS outreach_objected_tenant")
    op.execute("DROP TABLE IF EXISTS outreach_objected")
    op.execute("DROP INDEX IF EXISTS dsar_tombstone_contact")
    op.execute("DROP TABLE IF EXISTS dsar_tombstone")
    op.execute("DROP INDEX IF EXISTS lawful_basis_record_third_party")
    op.execute("DROP TABLE IF EXISTS lawful_basis_record")
