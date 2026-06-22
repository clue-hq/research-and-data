"""m9.4 identity-binding gate — binding_policy + identity_binding_eval (ENG-144)

Revision ID: 971febbe2906
Revises: 911a1beeb9c1
Create Date: 2026-06-21 20:09:37.491500+00:00

M9.4 (the verification layer's *identity* gate over contact claims — the contact-axis analogue of
the tier-4 evidence-span rule): for a personal claim, getting the person *wrong* in 1:1 outreach is
worse than omitting it (staged-flow §6). Every contact claim carries an ``identity_binding``
strength — ``strong`` (evidence on the contact's *verified* profile/handle, or ≥K co-occurring
identifiers bound to *this* person) or ``weak`` (the same-name trap). **A weak-bound claim never
promotes and never drives outreach.** This migration adds only the M9.4 *config* + *audit* schema
and — per the M9 isolation contract — alters **no shared mutable surface**:

* ``binding_policy`` — versioned, per-client-overridable identity-binding config (policy-as-data,
  conventions §2): ``min_identifiers_k``, the ``strong_identifier_set`` counted toward criterion 2,
  and the two same-name-guard flags the gate reads at construction. Changing K or the identifier set
  is a config row, **not a code change** (the swap is regression-checked by the M9.6 eval battery).
  Stored as typed columns (M09 §M9.4 data model), like ``judge_policy`` (not a ``rules_json`` blob).
* ``identity_binding_eval`` — append-only audit, **one row per ``(claim_id, policy_fingerprint)``**
  (the unique constraint *is* the idempotency/cache key: re-classifying the same claim under the
  same policy *content* returns the cached binding and writes no new row; ANY content change — a new
  K, a changed identifier set, a bumped version — yields a different fingerprint → a fresh verdict).
  Keying on a content hash, not the bare integer ``policy_version``, closes the stale-cache hole
  where two policies sharing ``version`` (the in-code default and a config row both default to 1)
  would collide. It records the classified ``strength``, the 0..1 ``strength_score``, the
  ``evidence_signals_json`` (which signals fired), and the ``policy_version`` (a human-readable
  audit column) so M12's provenance index and the Doc C §6 "share at strong binding" surface can
  read the binding decision per claim.

The gate **does not** rewrite ``claim.identity_binding`` — that column is *immutable provenance*
(the 0004 trigger allow-list is only ``superseded_by/verification_status/corroborations``) and is
*born* with the claim (the M4 waterfall stamps the source prior; the DB CHECK
``claim_contact_field_requires_governance`` requires it for ``contact.facet.*``). The authoritative
classification flows two ways: M8.4/M8.5 stamp ``classify_binding(...)``'s result at insert (so the
immutable column — which ``merge._is_eligible`` and ``core.can_be_promoted`` both read to exclude
weak-bound contacts — is born correct), and the gate's defensive backstop drives the **already-
mutable** ``claim.verification_status`` to ``rejected`` only for a drift case (a claim the gate
classifies ``weak`` whose born column wrongly says it is promotable) via
:func:`clue_research.claimstore.record_verification`. So M9.4 needs **no trigger change, no
``claim`` ALTER, and no new enum** — the eval's ``strength`` reuses the ``identity_binding`` enum
(0004), parity-tested in ``tests/claimstore/test_provenance_flavors.py``.

``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "971febbe2906"
down_revision: str | None = "911a1beeb9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- binding_policy: versioned identity-binding config as data (per-client overridable) ---
    # Typed columns (M09 §M9.4): min_identifiers_k (criterion-2 threshold K), strong_identifier_set
    # (which identifier kinds count toward K — a JSON array of identifier names), and the two
    # same-name-guard flags (verified_handle_sufficient: a verified-handle match alone is strong;
    # weak_source_requires_handle: a WEAK-prior source can't be strong on identifiers alone).
    # client_id NULL = the global default policy; the loader reads the most-specific (per-client >
    # global) row, latest version, with a deterministic created_at/policy_id tie-break.
    op.execute(
        """
        CREATE TABLE binding_policy (
            policy_id                   text PRIMARY KEY,
            client_id                   text,
            min_identifiers_k           int  NOT NULL DEFAULT 2,
            strong_identifier_set       jsonb NOT NULL DEFAULT '["full_name", "employer", "geo"]',
            verified_handle_sufficient  boolean NOT NULL DEFAULT true,
            weak_source_requires_handle boolean NOT NULL DEFAULT true,
            version                     int NOT NULL DEFAULT 1,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT binding_policy_version_positive CHECK (version >= 1),
            CONSTRAINT binding_policy_k_positive CHECK (min_identifiers_k >= 1),
            CONSTRAINT binding_policy_identifier_set_is_array
                CHECK (jsonb_typeof(strong_identifier_set) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE binding_policy IS 'M9.4 identity-binding config as versioned data "
        "(policy-as-data, conventions §2). The gate reads the most-specific row (per-client > "
        "global); client_id NULL = the global default policy. Changing min_identifiers_k or the "
        "strong_identifier_set is a config row, regression-checked by the M9.6 eval battery.'"
    )
    # Resolution lookup: the loader selects by client_id (the NULL-scoped global row is found by the
    # same index). ``NULLS NOT DISTINCT`` (pg15+) so the global default (client_id IS NULL) is ONE
    # slot per version, not many — otherwise a plain UNIQUE treats NULLs as distinct and would admit
    # duplicate (NULL, version) global rows the loader could then resolve non-deterministically
    # (the gap M9.3 closed for judge_policy / migration 0009's source_profile; applied here from the
    # start so M9.4 never carries it).
    op.execute(
        "CREATE UNIQUE INDEX binding_policy_scope_version "
        "ON binding_policy (client_id, version) NULLS NOT DISTINCT"
    )

    # --- identity_binding_eval: append-only audit; the unique key is the idempotency/cache key ---
    # One row per (claim_id, policy_fingerprint): the gate SELECTs it first and returns the cached
    # binding on a hit (no re-read, no re-classification); any policy-content change misses → fresh.
    # policy_fingerprint is a content hash of the resolved BindingPolicy (K, identifier set, the two
    # guard flags, version) — NOT the bare integer policy_version, so an in-place policy edit at the
    # same version still re-classifies (mirrors M9.3 keying its judge cache on the model id).
    # policy_version rides along as a human-readable audit column. Append-only by use — no
    # UPDATE/DELETE path. strength reuses the existing identity_binding enum (0004); strength_score
    # is the 0..1 binding confidence; evidence_signals_json records which signals fired (the
    # verified-handle match, which identifiers co-occurred, the source prior). No FK to claim
    # (mirrors faithfulness_verdict): the audit row may be written for an in-flight claim and
    # survives the claim's supersession.
    op.execute(
        """
        CREATE TABLE identity_binding_eval (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id              uuid NOT NULL,
            contact_entity_id     uuid NOT NULL,
            strength              identity_binding NOT NULL,
            strength_score        double precision NOT NULL,
            evidence_signals_json jsonb NOT NULL DEFAULT '{}',
            policy_version        int NOT NULL DEFAULT 1,
            policy_fingerprint    text NOT NULL,
            evaluated_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT identity_binding_eval_score_unit_interval
                CHECK (strength_score >= 0 AND strength_score <= 1),
            CONSTRAINT identity_binding_eval_cache_key
                UNIQUE (claim_id, policy_fingerprint)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE identity_binding_eval IS 'M9.4 append-only identity-binding audit "
        "(staged-flow §6/§9 / Doc C §6). One row per (claim_id, policy_fingerprint) — the UNIQUE "
        "is the cache key (re-classifying the same claim under the same policy content returns the "
        "cached binding; any content change forces a fresh verdict). policy_fingerprint is a "
        "BindingPolicy content hash; policy_version is a human-readable audit column. strength "
        "reuses the identity_binding enum; cited by M12 provenance; never mutated.'"
    )
    # Read path: every classification for a claim (provenance index / re-classify cache probe).
    op.execute("CREATE INDEX identity_binding_eval_claim_id ON identity_binding_eval (claim_id)")
    op.execute(
        "CREATE INDEX identity_binding_eval_evaluated_at ON identity_binding_eval (evaluated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS identity_binding_eval_evaluated_at")
    op.execute("DROP INDEX IF EXISTS identity_binding_eval_claim_id")
    op.execute("DROP TABLE IF EXISTS identity_binding_eval")
    op.execute("DROP INDEX IF EXISTS binding_policy_scope_version")
    op.execute("DROP TABLE IF EXISTS binding_policy")
