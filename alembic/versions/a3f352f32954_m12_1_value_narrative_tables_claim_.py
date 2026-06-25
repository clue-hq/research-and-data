"""m12.1 value narrative — claim_support + positioning_policy (ENG-158)

Revision ID: a3f352f32954
Revises: 3df3b2f629fd
Create Date: 2026-06-24 07:40:16.370149+00:00

M12.1 (the positioning step) writes the per-``(account, persona)`` value narrative as an
``account.value_narrative`` claim (registered by ``narrative.load_narrative_pack`` — a data row,
no DDL). This migration adds only the M12.1 *provenance* + *config* side schema and — like the M9
gate tables — alters **no shared mutable surface** (no ``claim`` ALTER, no immutable-guard REPLACE):

* ``claim_support`` — a narrative claim's two-sided provenance: the verified account ``claim`` ids
  it argues from (``account_evidence_ids``) and the Client-Knowledge-Base ids it draws on
  (``client_knowledge_ids``), so overview §3 ``supporting{account_evidence_ids[],
  client_knowledge_ids[]}`` is a queryable row, not a promise. Per phase-3 pre-flight PF-2 this is a
  **side table keyed on the narrative ``claim_id``** (one row per claim, the PK), **not** columns on
  ``claim`` — so no branch ALTERs the append-only ``claim`` or its ``claim_reject_immutable_update``
  guard. Like the M9 audit tables it carries **no FK to ``claim(id)``** (the link survives
  supersession; a re-synthesis mints a new claim id and its own row). The id collections are JSONB
  arrays (the codebase convention for id lists — e.g. ``gate_decision.reasons``), guarded by a
  ``jsonb_typeof = 'array'`` CHECK.
* ``positioning_policy`` — versioned, per-client-overridable positioning config (policy-as-data,
  conventions §2): the gateway ``narrative_model`` id, the ``prompt_version``, the coverage/cap
  knobs, and the ``field_relevance`` map (which verified account fields feed which persona). The
  loader reads the most-specific row (per-client > global; ``client_id IS NULL`` = the global
  default), latest ``version`` — so a model/prompt/relevance swap is a config row, not a code change
  (M12.1 AC8). Mirrors ``judge_policy``: ``NULLS NOT DISTINCT`` keeps the global default ONE slot
  per version.

``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f352f32954"
down_revision: str | None = "3df3b2f629fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- claim_support: a narrative claim's two-sided provenance (PF-2 side table) ---
    op.execute(
        """
        CREATE TABLE claim_support (
            claim_id             uuid PRIMARY KEY,
            account_evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            client_knowledge_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT claim_support_account_ids_is_array
                CHECK (jsonb_typeof(account_evidence_ids) = 'array'),
            CONSTRAINT claim_support_client_ids_is_array
                CHECK (jsonb_typeof(client_knowledge_ids) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE claim_support IS 'M12.1 two-sided provenance for an "
        "account.value_narrative claim (overview §3 supporting{account_evidence_ids[], "
        "client_knowledge_ids[]}; PF-2 side table keyed on claim_id — never a claim ALTER, no FK "
        "to claim(id) so the link survives supersession). Written by the positioner; read by the "
        "M12.2 assembler / provenance index.'"
    )
    op.execute("CREATE INDEX claim_support_created_at ON claim_support (created_at)")

    # --- positioning_policy: versioned positioning config as data (per-client overridable) ---
    op.execute(
        """
        CREATE TABLE positioning_policy (
            policy_id            text PRIMARY KEY,
            client_id            text,
            narrative_model      text NOT NULL,
            prompt_version       text NOT NULL,
            min_account_evidence int NOT NULL DEFAULT 1,
            min_client_chunks    int NOT NULL DEFAULT 1,
            retrieval_limit      int NOT NULL DEFAULT 8,
            max_evidence_chars   int NOT NULL DEFAULT 4000,
            field_relevance      jsonb NOT NULL DEFAULT '{}'::jsonb,
            version              int NOT NULL DEFAULT 1,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT positioning_policy_version_positive CHECK (version >= 1),
            CONSTRAINT positioning_policy_min_evidence_positive CHECK (min_account_evidence >= 1),
            CONSTRAINT positioning_policy_min_chunks_positive CHECK (min_client_chunks >= 1),
            CONSTRAINT positioning_policy_retrieval_limit_positive CHECK (retrieval_limit >= 1),
            CONSTRAINT positioning_policy_max_chars_positive CHECK (max_evidence_chars >= 1),
            CONSTRAINT positioning_policy_field_relevance_is_object
                CHECK (jsonb_typeof(field_relevance) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE positioning_policy IS 'M12.1 value-narrative positioning config as "
        "versioned data (policy-as-data, conventions §2). The positioner reads the most-specific "
        "row (per-client > global); client_id NULL = the global default. narrative_model is a "
        "gateway model id and field_relevance maps persona -> account field keys — swapping either "
        "is a config row, not code (M12.1 AC8).'"
    )
    # Resolution lookup mirrors judge_policy: the loader selects by client_id (the NULL-scoped
    # global row is found by the same index). NULLS NOT DISTINCT (pg15+) so the global default
    # (client_id IS NULL) is ONE slot per version — a plain UNIQUE treats NULLs as distinct and
    # would admit duplicate (NULL, version) rows the loader could then resolve non-deterministic.
    op.execute(
        "CREATE UNIQUE INDEX positioning_policy_scope_version "
        "ON positioning_policy (client_id, version) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS positioning_policy_scope_version")
    op.execute("DROP TABLE IF EXISTS positioning_policy")
    op.execute("DROP INDEX IF EXISTS claim_support_created_at")
    op.execute("DROP TABLE IF EXISTS claim_support")
