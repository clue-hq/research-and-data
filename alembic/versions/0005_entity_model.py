"""account_entity + contact_entity — the canonical entity tables (M2.1 / ENG-100)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19

Establish the canonical entity tables the entire subsystem keys on. Conventions §2 fixes the
invariant: *everything keys on a resolved ``entity_id``, never a free-text name*, and identity
resolution (M2) is the only thing allowed to turn a name into an id. Before any resolution logic
exists there must be a stable, well-keyed home for the resolved entity, its strong keys (domain,
registry ids), aliases, lifecycle status, and the ``merged_into`` pointer that makes append-only
history coherent (substrate §2).

What this migration establishes (M2.1 scope):

* ``account_entity`` — the ``_conventions.md`` §4 / substrate §2 contract verbatim (id,
  canonical_name, primary_domain, aliases[], hq_geo, registry_ids{NPI|DUNS|CIK|LEI…},
  status{candidate|active|merged}, merged_into), plus only types/indexes/constraints.
* ``contact_entity`` — the substrate §2 "contacts resolve *under* accounts" structure, keyed on its
  own strong identifiers (LinkedIn URL / verified email) with an ``account_entity_id`` FK and the
  Doc D §1 ``jurisdiction`` column (nullable until a location claim resolves it — D4 mixed/global).
* **strong-key uniqueness** — partial-unique on ``account_entity.primary_domain`` (where non-null,
  normalized to registrable form by the write path), per-namespace partial-unique on the canonical
  identifying registries (DUNS/NPI/CIK/LEI), and partial-unique on ``contact_entity.linkedin_url`` /
  ``verified_email`` (where non-null). NULL strong keys are permitted (candidate entities).
* **lifecycle / merge integrity** — ``status = 'merged' ⟺ merged_into IS NOT NULL`` and a
  no-self-merge CHECK (the 1-hop cycle guard). Longer ``merged_into`` cycles are detected and
  errored by the read-side ``surviving_id`` helper (never looped), per the §M2.1 criteria.

**Soft FK note (resolves the M1.1 deferral — DECISION).** ``claim.entity_id`` logically references
*either* ``account_entity(id)`` (when ``entity_type='account'``) *or* ``contact_entity(id)`` (when
``'contact'``). Because the reference is **polymorphic** across two tables, a single hard FK is not
expressible *and* would reject every contact-typed claim; so ``entity_id`` stays a **soft**
reference, its integrity guaranteed by the resolution service (M2 — the only ``entity_id`` writer)
together with the ``entity_type`` discriminator. This supersedes the M1.1 "FK deferred to M2" note:
the honest resolution is no hard FK, documented here.

``entity_status`` is **one shared enum** used by both tables (the candidate→active→merged lifecycle
is the entity lifecycle, mapped to ``core.AccountStatus``); the enum-parity test guards it against
drift exactly as the M1 migrations do. The per-namespace registry uniqueness is enforced for the
canonical *identifying* registries only (conventions §3); the ``registry_ids`` JSONB map stays
open-by-registration (D8) — storing a new namespace needs no schema change, and making a *new*
registry uniquely-identifying is one added partial-unique index here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors clue_research.core.enums.AccountStatus (the shared entity lifecycle, used by both the
# account and contact tables). The enum-parity test in tests/identity/test_entity_model.py guards
# against drift, exactly as the M1 migrations' parity tests do.
_ENTITY_STATUS = ("candidate", "active", "merged")

# The canonical *identifying* registries (conventions §3) for which a value pins exactly one
# account. Storing any other namespace in registry_ids needs no change; promoting a new namespace
# to uniquely-identifying is one added partial-unique index here.
_IDENTIFYING_REGISTRIES = ("DUNS", "NPI", "CIK", "LEI")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE entity_status AS ENUM ({_enum_values_sql(_ENTITY_STATUS)})")

    # --- account_entity -----------------------------------------------------
    op.execute(
        """
        CREATE TABLE account_entity (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_name text NOT NULL,
            primary_domain text,
            aliases        text[] NOT NULL DEFAULT '{}',
            hq_geo         jsonb,
            registry_ids   jsonb NOT NULL DEFAULT '{}'::jsonb,
            status         entity_status NOT NULL DEFAULT 'candidate',
            merged_into    uuid REFERENCES account_entity(id),
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),

            -- A merged entity always points at its survivor; a live one never does (substrate §2).
            CONSTRAINT account_entity_merged_iff_target
                CHECK ((status = 'merged') = (merged_into IS NOT NULL)),
            -- Kills 1-cycles at write time; longer cycles are caught by surviving_id (read side).
            CONSTRAINT account_entity_no_self_merge
                CHECK (merged_into IS NULL OR merged_into <> id),
            CONSTRAINT account_entity_registry_ids_is_object
                CHECK (jsonb_typeof(registry_ids) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE account_entity IS 'Canonical account entity (substrate §2). The "
        "entity_id every component keys on; claim.entity_id soft-references id (polymorphic with "
        "contact_entity, so no hard FK). registry_ids JSONB is open-by-registration (D8).'"
    )

    # Strong-key uniqueness (partial — NULLs allowed for pre-resolution candidates).
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_key ON account_entity (primary_domain) "
        "WHERE primary_domain IS NOT NULL"
    )
    for namespace in _IDENTIFYING_REGISTRIES:
        # One identifying-registry value pins one account. The expression index keys on the JSONB
        # value; the partial WHERE limits it to rows that carry that registry.
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{namespace.lower()}_key "
            f"ON account_entity ((registry_ids->>'{namespace}')) "
            f"WHERE registry_ids ? '{namespace}'"
        )
    op.execute("CREATE INDEX account_entity_canonical_name ON account_entity (canonical_name)")
    op.execute("CREATE INDEX account_entity_aliases_gin ON account_entity USING gin (aliases)")
    op.execute("CREATE INDEX account_entity_status ON account_entity (status)")
    op.execute(
        "CREATE INDEX account_entity_merged_into ON account_entity (merged_into) "
        "WHERE merged_into IS NOT NULL"
    )

    # --- contact_entity (contacts resolve under accounts) -------------------
    op.execute(
        """
        CREATE TABLE contact_entity (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            account_entity_id uuid NOT NULL REFERENCES account_entity(id),
            full_name         text,
            linkedin_url      text,
            verified_email    text,
            aliases           text[] NOT NULL DEFAULT '{}',
            geo               jsonb,
            jurisdiction      text,
            status            entity_status NOT NULL DEFAULT 'candidate',
            merged_into       uuid REFERENCES contact_entity(id),
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT contact_entity_merged_iff_target
                CHECK ((status = 'merged') = (merged_into IS NOT NULL)),
            CONSTRAINT contact_entity_no_self_merge
                CHECK (merged_into IS NULL OR merged_into <> id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE contact_entity IS 'Contact entity under an account (substrate §2/§7). "
        "Strong keys: linkedin_url / verified_email. jurisdiction (Doc D §1) is resolved from a "
        "location claim later (M10); nullable until then. The (account, persona) committee graph "
        "keys on these rows.'"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_key ON contact_entity (linkedin_url) "
        "WHERE linkedin_url IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_key ON contact_entity (verified_email) "
        "WHERE verified_email IS NOT NULL"
    )
    op.execute("CREATE INDEX contact_entity_account ON contact_entity (account_entity_id)")
    op.execute("CREATE INDEX contact_entity_full_name ON contact_entity (full_name)")
    op.execute("CREATE INDEX contact_entity_aliases_gin ON contact_entity USING gin (aliases)")
    op.execute("CREATE INDEX contact_entity_status ON contact_entity (status)")
    op.execute(
        "CREATE INDEX contact_entity_merged_into ON contact_entity (merged_into) "
        "WHERE merged_into IS NOT NULL"
    )


def downgrade() -> None:
    # contact_entity has an FK into account_entity, so drop it first.
    op.execute("DROP TABLE IF EXISTS contact_entity")
    op.execute("DROP TABLE IF EXISTS account_entity")
    op.execute("DROP TYPE IF EXISTS entity_status")
