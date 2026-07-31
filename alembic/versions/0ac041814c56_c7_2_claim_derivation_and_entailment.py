"""C7.2 immutable claim derivations and bounded entailment verdicts.

Revision ID: 0ac041814c56
Revises: 4dad5551c2f7
Create Date: 2026-07-27 17:10:08.298914+00:00

Adds the ``derived`` claim flavor, ordered append-only support edges, and append-only entailment
verdicts. Derived claims remain in the one claim substrate, but their evidence is the normalized
support set rather than an invented URL/span. A deferred claim constraint proves that a committed
derived claim has supports and that a terminal verification state has a verdict.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0ac041814c56"
down_revision: str | None = "4dad5551c2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLAIM_FLAVORS_BEFORE = ("discovery", "field_claim")
_CLAIM_FLAVORS_AFTER = (*_CLAIM_FLAVORS_BEFORE, "derived")
_SUPPORT_ROLES = (
    "direct_evidence",
    "corroboration",
    "account_signal",
    "employer_context",
    "client_capability",
)
_ENTAILMENT_VERDICTS = ("supported", "unsupported", "error")
_ENTAILMENT_REASONS = (
    "entailed",
    "missing_support",
    "subject_mismatch",
    "product_mismatch",
    "not_entailed",
    "contradicted",
    "malformed_response",
    "model_error",
)


def _enum_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_claim_flavor(values: tuple[str, ...], *, old_name: str) -> None:
    """Rebuild the enum so its new value is usable inside this migration transaction."""
    # PostgreSQL rewrites the column during the type swap. Temporarily remove the append-only
    # UPDATE trigger so its OLD composite (old enum) is not compared with NEW (new enum); recreate
    # it immediately against the unchanged guard function after the swap.
    op.execute("DROP TRIGGER IF EXISTS claim_no_immutable_update ON claim")
    op.execute("ALTER TABLE claim ALTER COLUMN claim_flavor DROP DEFAULT")
    op.execute(f"ALTER TYPE claim_flavor RENAME TO {old_name}")
    op.execute(f"CREATE TYPE claim_flavor AS ENUM ({_enum_sql(values)})")
    op.execute(
        "ALTER TABLE claim ALTER COLUMN claim_flavor TYPE claim_flavor "
        "USING claim_flavor::text::claim_flavor"
    )
    op.execute("ALTER TABLE claim ALTER COLUMN claim_flavor SET DEFAULT 'field_claim'")
    op.execute(f"DROP TYPE {old_name}")
    op.execute(
        "CREATE TRIGGER claim_no_immutable_update BEFORE UPDATE ON claim "
        "FOR EACH ROW EXECUTE FUNCTION claim_reject_immutable_update()"
    )


def _append_only_function(function: str, table: str) -> str:
    return f"""
        CREATE FUNCTION {function}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{table} is append-only';
        END;
        $$ LANGUAGE plpgsql
    """


def _claim_checks(*, derived: bool) -> None:
    no_envelope = "claim_flavor = 'discovery' OR discovery_provenance IS NULL"
    personal_flavors = "claim_flavor <> 'discovery'" if derived else "claim_flavor = 'field_claim'"
    span_exception = "AND claim_flavor <> 'derived'" if derived else ""
    op.execute(
        """
        ALTER TABLE claim ADD CONSTRAINT claim_discovery_requires_provenance CHECK (
            claim_flavor <> 'discovery'
            OR (
                discovery_provenance IS NOT NULL
                AND research_mode IN ('account_discovery', 'committee_discovery')
            )
        )
        """
    )
    op.execute(
        f"ALTER TABLE claim ADD CONSTRAINT claim_field_claim_no_discovery CHECK ({no_envelope})"
    )
    op.execute(
        f"""
        ALTER TABLE claim ADD CONSTRAINT claim_contact_field_requires_governance CHECK (
            NOT (
                {personal_flavors}
                AND entity_type = 'contact'
                AND (field_key = 'contact.facet' OR field_key LIKE 'contact.facet.%')
                AND (identity_binding IS NULL OR use_class IS NULL)
            )
        )
        """
    )
    op.execute(
        f"""
        ALTER TABLE claim ADD CONSTRAINT claim_tier4_verified_requires_span CHECK (
            NOT (
                verification_status = 'verified'
                AND source_tier = 4
                AND evidence_span IS NULL
                {span_exception}
            )
        )
        """
    )
    if derived:
        op.execute(
            """
            ALTER TABLE claim ADD CONSTRAINT claim_derived_provenance CHECK (
                claim_flavor <> 'derived'
                OR (
                    source_tier = 4
                    AND extraction_method = 'llm_synthesis'
                    AND source_url IS NULL
                    AND evidence_span IS NULL
                )
            )
            """
        )


def upgrade() -> None:
    # Rebuild rather than ALTER TYPE ADD VALUE: PostgreSQL forbids using a newly-added enum label
    # in constraints in the same transaction.
    for constraint in (
        "claim_discovery_requires_provenance",
        "claim_field_claim_no_discovery",
        "claim_contact_field_requires_governance",
        "claim_tier4_verified_requires_span",
        "claim_derived_provenance",
    ):
        op.execute(f"ALTER TABLE claim DROP CONSTRAINT IF EXISTS {constraint}")
    _replace_claim_flavor(_CLAIM_FLAVORS_AFTER, old_name="claim_flavor_before_c7_2")
    _claim_checks(derived=True)

    op.execute(f"CREATE TYPE research_support_role AS ENUM ({_enum_sql(_SUPPORT_ROLES)})")
    op.execute(f"CREATE TYPE entailment_verdict_kind AS ENUM ({_enum_sql(_ENTAILMENT_VERDICTS)})")
    op.execute(f"CREATE TYPE entailment_reason_code AS ENUM ({_enum_sql(_ENTAILMENT_REASONS)})")

    op.execute(
        """
        CREATE TABLE claim_derivation (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id        text NOT NULL REFERENCES workspace(workspace_id),
            derived_claim_id    uuid NOT NULL REFERENCES claim(id),
            supporting_claim_id uuid NOT NULL REFERENCES claim(id),
            support_role        research_support_role NOT NULL,
            ordinal             int NOT NULL,
            support_required    boolean NOT NULL DEFAULT true,
            operation_id        uuid NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT claim_derivation_no_self_edge
                CHECK (derived_claim_id <> supporting_claim_id),
            CONSTRAINT claim_derivation_ordinal_nonnegative CHECK (ordinal >= 0),
            CONSTRAINT claim_derivation_edge_unique
                UNIQUE (derived_claim_id, supporting_claim_id, support_role),
            CONSTRAINT claim_derivation_ordinal_unique UNIQUE (derived_claim_id, ordinal),
            CONSTRAINT claim_derivation_operation_ordinal_unique
                UNIQUE (workspace_id, operation_id, ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX claim_derivation_derived ON claim_derivation (derived_claim_id, ordinal)"
    )
    op.execute(
        "CREATE INDEX claim_derivation_supporting ON claim_derivation "
        "(supporting_claim_id, derived_claim_id)"
    )
    op.execute(
        "CREATE INDEX claim_derivation_operation ON claim_derivation (workspace_id, operation_id)"
    )

    op.execute(
        """
        CREATE TABLE entailment_verdict (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id       text NOT NULL REFERENCES workspace(workspace_id),
            derived_claim_id   uuid NOT NULL REFERENCES claim(id),
            support_set_sha256 text NOT NULL,
            verdict            entailment_verdict_kind NOT NULL,
            confidence         double precision NOT NULL,
            reason_codes       entailment_reason_code[] NOT NULL,
            requested_model    text NOT NULL,
            answering_model    text NOT NULL,
            prompt_version     text NOT NULL,
            policy_version     int NOT NULL,
            trace_ref          text NOT NULL,
            cost_cents         numeric NOT NULL DEFAULT 0,
            operation_id       uuid NOT NULL,
            judged_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entailment_verdict_support_hash_shape
                CHECK (support_set_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entailment_verdict_confidence_unit
                CHECK (confidence >= 0 AND confidence <= 1),
            CONSTRAINT entailment_verdict_reason_codes_bounded
                CHECK (cardinality(reason_codes) BETWEEN 1 AND 8),
            CONSTRAINT entailment_verdict_reason_coherent CHECK (
                (
                    verdict = 'supported'
                    AND reason_codes = ARRAY['entailed']::entailment_reason_code[]
                )
                OR (
                    verdict = 'unsupported'
                    AND NOT ('entailed'::entailment_reason_code = ANY(reason_codes))
                    AND NOT ('model_error'::entailment_reason_code = ANY(reason_codes))
                )
                OR (
                    verdict = 'error'
                    AND reason_codes = ARRAY['model_error']::entailment_reason_code[]
                )
            ),
            CONSTRAINT entailment_verdict_policy_positive CHECK (policy_version >= 1),
            CONSTRAINT entailment_verdict_trace_ref_bounded
                CHECK (length(btrim(trace_ref)) BETWEEN 1 AND 256),
            CONSTRAINT entailment_verdict_cost_nonnegative CHECK (cost_cents >= 0),
            CONSTRAINT entailment_verdict_cache_key UNIQUE (
                derived_claim_id,
                support_set_sha256,
                requested_model,
                prompt_version
            ),
            CONSTRAINT entailment_verdict_operation_unique UNIQUE (workspace_id, operation_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entailment_verdict_derived ON entailment_verdict "
        "(derived_claim_id, judged_at DESC)"
    )
    op.execute(
        "CREATE INDEX entailment_verdict_support_hash ON entailment_verdict (support_set_sha256)"
    )

    # Edge rows may never be updated/deleted. The INSERT validator enforces live claims, scope,
    # product/subject relations, strong contact binding, cycle prevention, and post-verdict freeze.
    op.execute(_append_only_function("claim_derivation_reject_mutation", "claim_derivation"))
    op.execute(
        """
        CREATE FUNCTION claim_derivation_validate_insert() RETURNS trigger AS $$
        DECLARE
            derived claim%ROWTYPE;
            support claim%ROWTYPE;
            parent_account uuid;
        BEGIN
            SELECT * INTO derived FROM claim WHERE id = NEW.derived_claim_id FOR UPDATE;
            IF NOT FOUND
               OR derived.claim_flavor <> 'derived'
               OR derived.superseded_by IS NOT NULL THEN
                RAISE EXCEPTION 'derived claim must exist, be live, and have flavor derived';
            END IF;

            SELECT * INTO support FROM claim WHERE id = NEW.supporting_claim_id FOR UPDATE;
            IF NOT FOUND OR support.superseded_by IS NOT NULL THEN
                RAISE EXCEPTION 'supporting claim must exist and be live';
            END IF;

            IF EXISTS (
                SELECT 1 FROM entailment_verdict
                WHERE derived_claim_id = NEW.derived_claim_id
            ) THEN
                RAISE EXCEPTION 'support set is frozen after entailment';
            END IF;

            IF derived.reuse_scope = 'tenant_private'
               AND derived.workspace_id IS DISTINCT FROM NEW.workspace_id THEN
                RAISE EXCEPTION 'derived claim workspace mismatch';
            END IF;
            IF support.reuse_scope = 'tenant_private'
               AND support.workspace_id IS DISTINCT FROM NEW.workspace_id THEN
                RAISE EXCEPTION 'supporting claim workspace mismatch';
            END IF;
            IF support.reuse_scope = 'tenant_private'
               AND derived.reuse_scope <> 'tenant_private' THEN
                RAISE EXCEPTION 'a public derivation cannot depend on tenant-private support';
            END IF;
            IF support.product_id IS NOT NULL
               AND support.product_id IS DISTINCT FROM derived.product_id THEN
                RAISE EXCEPTION 'supporting claim product mismatch';
            END IF;

            IF support.entity_type = 'contact'
               AND (
                   support.identity_binding = 'weak'
                   OR (
                       (support.field_key = 'contact.facet'
                        OR support.field_key LIKE 'contact.facet.%')
                       AND support.identity_binding IS DISTINCT FROM 'strong'
                   )
               ) THEN
                RAISE EXCEPTION 'contact support must be strongly identity-bound';
            END IF;

            IF NEW.support_role = 'client_capability' THEN
                IF derived.product_id IS NULL
                   OR support.product_id IS NULL
                   OR support.product_id IS DISTINCT FROM derived.product_id THEN
                    RAISE EXCEPTION
                        'client_capability requires support in the exact derived product scope';
                END IF;
            ELSIF derived.entity_id = support.entity_id THEN
                IF NEW.support_role = 'employer_context' THEN
                    RAISE EXCEPTION 'employer_context requires a parent-account support';
                END IF;
            ELSIF derived.entity_type = 'contact'
                  AND support.entity_type = 'account'
                  AND NEW.support_role IN ('employer_context', 'account_signal') THEN
                SELECT account_entity_id INTO parent_account
                FROM contact_entity
                WHERE id = derived.entity_id;
                IF parent_account IS DISTINCT FROM support.entity_id THEN
                    RAISE EXCEPTION 'account support is not the contact employer';
                END IF;
            ELSIF derived.entity_type = 'account'
                  AND support.entity_type = 'contact'
                  AND NEW.support_role = 'account_signal' THEN
                SELECT account_entity_id INTO parent_account
                FROM contact_entity
                WHERE id = support.entity_id;
                IF parent_account IS DISTINCT FROM derived.entity_id THEN
                    RAISE EXCEPTION 'contact signal is not bound to the derived account';
                END IF;
            ELSE
                RAISE EXCEPTION 'support role does not permit this cross-subject relation';
            END IF;

            IF EXISTS (
                WITH RECURSIVE dependencies(claim_id) AS (
                    SELECT NEW.supporting_claim_id
                    UNION
                    SELECT edge.supporting_claim_id
                    FROM claim_derivation edge
                    JOIN dependencies prior ON edge.derived_claim_id = prior.claim_id
                )
                SELECT 1 FROM dependencies WHERE claim_id = NEW.derived_claim_id
            ) THEN
                RAISE EXCEPTION 'claim derivation cycle detected';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER claim_derivation_validate "
        "BEFORE INSERT ON claim_derivation "
        "FOR EACH ROW EXECUTE FUNCTION claim_derivation_validate_insert()"
    )
    op.execute(
        "CREATE TRIGGER claim_derivation_no_update "
        "BEFORE UPDATE ON claim_derivation "
        "FOR EACH ROW EXECUTE FUNCTION claim_derivation_reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER claim_derivation_no_delete "
        "BEFORE DELETE ON claim_derivation "
        "FOR EACH ROW EXECUTE FUNCTION claim_derivation_reject_mutation()"
    )

    op.execute(_append_only_function("entailment_verdict_reject_mutation", "entailment_verdict"))
    op.execute(
        "CREATE TRIGGER entailment_verdict_no_update "
        "BEFORE UPDATE ON entailment_verdict "
        "FOR EACH ROW EXECUTE FUNCTION entailment_verdict_reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER entailment_verdict_no_delete "
        "BEFORE DELETE ON entailment_verdict "
        "FOR EACH ROW EXECUTE FUNCTION entailment_verdict_reject_mutation()"
    )

    # A transaction may insert claim -> edges -> verdict in that order. At COMMIT, the final shape
    # must be complete; direct SQL cannot leave a terminal derived claim without lineage/verdict.
    op.execute(
        """
        CREATE FUNCTION derived_claim_require_lineage() RETURNS trigger AS $$
        BEGIN
            IF NEW.claim_flavor = 'derived' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM claim_derivation WHERE derived_claim_id = NEW.id
                ) THEN
                    RAISE EXCEPTION 'a derived claim requires at least one support edge';
                END IF;
                IF NEW.verification_status IN ('verified', 'rejected')
                   AND NOT EXISTS (
                       SELECT 1 FROM entailment_verdict WHERE derived_claim_id = NEW.id
                   ) THEN
                    RAISE EXCEPTION 'a terminal derived claim requires an entailment verdict';
                END IF;
                IF NEW.verification_status = 'verified'
                   AND NOT EXISTS (
                       SELECT 1 FROM entailment_verdict
                       WHERE derived_claim_id = NEW.id AND verdict = 'supported'
                   ) THEN
                    RAISE EXCEPTION 'a verified derived claim requires a supported verdict';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER derived_claim_has_lineage "
        "AFTER INSERT OR UPDATE OF verification_status ON claim "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION derived_claim_require_lineage()"
    )


def downgrade() -> None:
    # Downgrading across real derived data would silently relabel research semantics. Refuse rather
    # than corrupt it; empty-schema up/down/up smoke remains fully reversible.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM claim WHERE claim_flavor = 'derived') THEN
                RAISE EXCEPTION
                    'cannot downgrade C7.2 while derived claims exist; preserve/export them first';
            END IF;
        END
        $$;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS derived_claim_has_lineage ON claim")
    op.execute("DROP FUNCTION IF EXISTS derived_claim_require_lineage()")

    op.execute("DROP TRIGGER IF EXISTS entailment_verdict_no_delete ON entailment_verdict")
    op.execute("DROP TRIGGER IF EXISTS entailment_verdict_no_update ON entailment_verdict")
    op.execute("DROP FUNCTION IF EXISTS entailment_verdict_reject_mutation()")
    op.execute("DROP TABLE IF EXISTS entailment_verdict")

    op.execute("DROP TRIGGER IF EXISTS claim_derivation_no_delete ON claim_derivation")
    op.execute("DROP TRIGGER IF EXISTS claim_derivation_no_update ON claim_derivation")
    op.execute("DROP TRIGGER IF EXISTS claim_derivation_validate ON claim_derivation")
    op.execute("DROP FUNCTION IF EXISTS claim_derivation_reject_mutation()")
    op.execute("DROP FUNCTION IF EXISTS claim_derivation_validate_insert()")
    op.execute("DROP TABLE IF EXISTS claim_derivation")

    op.execute("DROP TYPE IF EXISTS entailment_reason_code")
    op.execute("DROP TYPE IF EXISTS entailment_verdict_kind")
    op.execute("DROP TYPE IF EXISTS research_support_role")

    for constraint in (
        "claim_discovery_requires_provenance",
        "claim_field_claim_no_discovery",
        "claim_contact_field_requires_governance",
        "claim_tier4_verified_requires_span",
        "claim_derived_provenance",
    ):
        op.execute(f"ALTER TABLE claim DROP CONSTRAINT IF EXISTS {constraint}")
    _replace_claim_flavor(_CLAIM_FLAVORS_BEFORE, old_name="claim_flavor_with_c7_2")
    _claim_checks(derived=False)
