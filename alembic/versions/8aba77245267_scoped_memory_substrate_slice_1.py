"""scoped memory substrate — slice 1 (Doc M / PB-B3)

Revision ID: 8aba77245267
Revises: 98422adaaa38
Create Date: 2026-07-21

The second substrate (Doc M): ``memory`` + ``memory_claim_ref`` + the two journals
(``memory_event``, ``memory_bundle_journal``) + the workspace kill-switch pair
(``memory_switch``, ``memory_switch_audit``). Spine style throughout — text enum columns with
named CHECKs (parity-tested against ``clue_core.memory``), text PKs (``mem_`` prefixed uuid4
hex), and invalid states impossible **by schema**:

* **Scope binding is structural.** Per-scope-type FK columns composite-pinned to the memory's own
  ``workspace_id`` via the spine anchors, so a cross-workspace scope reference is unrepresentable;
  ``memory_scope_shape`` requires exactly the column matching ``scope_type`` (workspace scope →
  all NULL: the workspace itself is the instance). ``project_workspace_anchor`` is added to the
  spine's ``project`` table here (append-only; mirrors ``brand_workspace_anchor`` /
  ``product_workspace_anchor`` from 98422adaaa38, which simply had no composite-FK consumer yet).
* **``account`` scope is deferred** (PB-B3 §0 ruling 5): the CHECK has no account arm, so an
  account-scoped row is unrepresentable until the follow-up appends the enum value + FK column
  + CHECK arm.
* **The species split is structural too:** ``memory_claim_ref`` FKs ``claim(id)`` — refs carry
  the facts; the ``memory`` table has no claim-content column. DB-level FKs into research-owned
  tables (``claim``, ``contact_entity``) are schema coupling only — Rule S1 (no code import)
  holds.
* **Ids-never-bodies is structural in the bundle journal:** no body/trigger/quote column exists
  there; rendering dereferences live rows.
* ``person_adjacent ⇔ subject_entity_id`` is a two-way CHECK (fail-closed subject binding,
  Doc M §16.1).

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8aba77245267"
down_revision: str | None = "98422adaaa38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- spine anchor for project's composite FK (append-only; mirrors brand/product) ---------
    op.execute(
        "ALTER TABLE project ADD CONSTRAINT project_workspace_anchor "
        "UNIQUE (project_id, workspace_id)"
    )

    # --- memory: the record (Doc M §5) --------------------------------------------------------
    op.execute(
        """
        CREATE TABLE memory (
            memory_id        text NOT NULL,
            workspace_id     text NOT NULL,
            scope_type       text NOT NULL,
            scope_brand_id   text,
            scope_product_id text,
            scope_project_id text,
            scope_id         text GENERATED ALWAYS AS (
                CASE scope_type
                    WHEN 'workspace' THEN workspace_id
                    WHEN 'brand'     THEN scope_brand_id
                    WHEN 'product'   THEN scope_product_id
                    WHEN 'project'   THEN scope_project_id
                END
            ) STORED,
            type             text NOT NULL,
            trigger          text NOT NULL,
            body             text NOT NULL,
            provenance_class text NOT NULL,
            trust_grade      smallint NOT NULL,
            creating_quote   text,
            status           text NOT NULL,
            superseded_by    text,
            confirmation_count     integer NOT NULL DEFAULT 0,
            last_confirmed_at      timestamptz,
            cycles_since_confirmed integer NOT NULL DEFAULT 0,
            subject_entity_id uuid,
            retention_class  text NOT NULL DEFAULT 'standard',
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT memory_pkey PRIMARY KEY (memory_id),
            CONSTRAINT memory_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- Scope FKs are composite-pinned to the memory's own workspace (cross-workspace
            -- references unrepresentable — the spine-anchor pattern).
            CONSTRAINT memory_scope_brand_fk FOREIGN KEY (scope_brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT memory_scope_product_fk FOREIGN KEY (scope_product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT memory_scope_project_fk FOREIGN KEY (scope_project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            -- Exactly the scope column matching scope_type is set ('account' arm deferred).
            CONSTRAINT memory_scope_shape CHECK (
                CASE scope_type
                    WHEN 'workspace' THEN scope_brand_id IS NULL
                        AND scope_product_id IS NULL AND scope_project_id IS NULL
                    WHEN 'brand' THEN scope_brand_id IS NOT NULL
                        AND scope_product_id IS NULL AND scope_project_id IS NULL
                    WHEN 'product' THEN scope_product_id IS NOT NULL
                        AND scope_brand_id IS NULL AND scope_project_id IS NULL
                    WHEN 'project' THEN scope_project_id IS NOT NULL
                        AND scope_brand_id IS NULL AND scope_product_id IS NULL
                    ELSE false
                END
            ),
            CONSTRAINT memory_scope_type CHECK (
                scope_type IN ('workspace', 'brand', 'product', 'project')
            ),
            CONSTRAINT memory_type CHECK (type IN ('preference', 'behavioral_learning')),
            CONSTRAINT memory_provenance_class CHECK (
                provenance_class IN ('user_stated', 'edit_distilled', 'agent_observed')
            ),
            CONSTRAINT memory_trust_grade CHECK (trust_grade BETWEEN 0 AND 4),
            CONSTRAINT memory_status CHECK (
                status IN ('proposed', 'active', 'dormant', 'superseded', 'invalidated',
                           'locked', 'tombstoned')
            ),
            CONSTRAINT memory_superseded_fk FOREIGN KEY (superseded_by)
                REFERENCES memory (memory_id),
            -- superseded_by is set exactly on superseded rows (invalidated = no successor).
            CONSTRAINT memory_superseded_shape CHECK (
                (status = 'superseded') = (superseded_by IS NOT NULL)
            ),
            CONSTRAINT memory_counters_nonnegative CHECK (
                confirmation_count >= 0 AND cycles_since_confirmed >= 0
            ),
            CONSTRAINT memory_subject_fk FOREIGN KEY (subject_entity_id)
                REFERENCES contact_entity (id),
            -- Fail-closed subject binding (Doc M §16.1): person-adjacent ⇔ subject bound.
            CONSTRAINT memory_retention_class CHECK (
                retention_class IN ('standard', 'person_adjacent')
            ),
            CONSTRAINT memory_person_adjacency CHECK (
                (retention_class = 'person_adjacent') = (subject_entity_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE memory IS 'Scoped-memory substrate (Doc M): advisory preferences / "
        "behavioral learnings over the object spine. Facts stay claims — refs carry them "
        "(memory_claim_ref); rows transition status, never silently mutate content (sanctioned "
        "exception: tombstoning redacts).'"
    )
    # The gate/reconcile query: one scope instance's records of one type, by status.
    op.execute(
        "CREATE INDEX memory_scope_read ON memory "
        "(workspace_id, scope_type, scope_id, type, status)"
    )
    # DSAR entry point: everything bound to a subject (partial — most rows are not).
    op.execute(
        "CREATE INDEX memory_subject ON memory (subject_entity_id) "
        "WHERE subject_entity_id IS NOT NULL"
    )

    # --- memory_claim_ref: refs carry the facts (Doc M §5/§16.2) ------------------------------
    op.execute(
        """
        CREATE TABLE memory_claim_ref (
            memory_id text NOT NULL,
            claim_id  uuid NOT NULL,

            CONSTRAINT memory_claim_ref_pkey PRIMARY KEY (memory_id, claim_id),
            CONSTRAINT memory_claim_ref_memory_fk FOREIGN KEY (memory_id)
                REFERENCES memory (memory_id),
            CONSTRAINT memory_claim_ref_claim_fk FOREIGN KEY (claim_id)
                REFERENCES claim (id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE memory_claim_ref IS 'Indexed both directions (one relation, two "
        "consumers): the PK serves assembly/labels forward; the claim_id index serves the DSAR "
        "cascade + reference-health staleness reverse (both deferred consumers, PB-B3 §0).'"
    )
    op.execute("CREATE INDEX memory_claim_ref_reverse ON memory_claim_ref (claim_id)")

    # --- memory_event: every transition journaled with actor + cause (Doc M §5) ---------------
    op.execute(
        """
        CREATE TABLE memory_event (
            event_id     uuid NOT NULL DEFAULT gen_random_uuid(),
            memory_id    text NOT NULL,
            workspace_id text NOT NULL,
            event_type   text NOT NULL,
            from_status  text,
            to_status    text,
            actor        text NOT NULL,
            cause        text,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT memory_event_pkey PRIMARY KEY (event_id),
            CONSTRAINT memory_event_memory_fk FOREIGN KEY (memory_id)
                REFERENCES memory (memory_id),
            CONSTRAINT memory_event_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT memory_event_type CHECK (
                event_type IN ('created', 'activated', 'confirmed', 'contradicted',
                               'superseded', 'invalidated', 'reactivated', 'evicted',
                               'backfilled', 'locked', 'tombstoned', 'kickoff_cycle')
            )
        )
        """
    )
    op.execute("CREATE INDEX memory_event_by_memory ON memory_event (memory_id, created_at)")

    # --- memory_bundle_journal: the REQ-12 reproducibility record (Doc M §11) -----------------
    # Ids-never-bodies is STRUCTURAL: no body/trigger/quote column exists; label metadata is
    # enum/numeric only. Rendering dereferences live; erased memories render as tombstones.
    op.execute(
        """
        CREATE TABLE memory_bundle_journal (
            journal_id      uuid NOT NULL DEFAULT gen_random_uuid(),
            workspace_id    text NOT NULL,
            recipe          text NOT NULL,
            requested_types jsonb NOT NULL,
            scope_stack     jsonb NOT NULL,
            included        jsonb NOT NULL DEFAULT '[]'::jsonb,
            excluded        jsonb NOT NULL DEFAULT '[]'::jsonb,
            cross_branch_pairs jsonb NOT NULL DEFAULT '[]'::jsonb,
            bundle_hash     text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT memory_bundle_journal_pkey PRIMARY KEY (journal_id),
            CONSTRAINT memory_bundle_journal_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT memory_bundle_journal_arrays CHECK (
                jsonb_typeof(requested_types) = 'array'
                AND jsonb_typeof(included) = 'array'
                AND jsonb_typeof(excluded) = 'array'
                AND jsonb_typeof(cross_branch_pairs) = 'array'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX memory_bundle_journal_by_workspace ON memory_bundle_journal "
        "(workspace_id, created_at)"
    )

    # --- the workspace kill-switch + its audit (Doc M §17a; PB-B3 Q2 ruling: the DB toggle is
    # the mechanism, CLUE_MEMORY_ENABLED the deploy master default layered above) --------------
    op.execute(
        """
        CREATE TABLE memory_switch (
            workspace_id text NOT NULL,
            enabled      boolean NOT NULL,
            updated_at   timestamptz NOT NULL DEFAULT now(),
            updated_by   text NOT NULL,

            CONSTRAINT memory_switch_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT memory_switch_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE memory_switch_audit (
            audit_id     uuid NOT NULL DEFAULT gen_random_uuid(),
            workspace_id text NOT NULL,
            enabled      boolean NOT NULL,
            actor        text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT memory_switch_audit_pkey PRIMARY KEY (audit_id),
            CONSTRAINT memory_switch_audit_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE memory_switch_audit IS 'Who flipped memory on/off, when — the audit "
        "entry that makes journal claims of \"memory was off\" verifiable (Doc M §17a). Off is "
        "not erasure: the store freezes intact.'"
    )
    op.execute(
        "CREATE INDEX memory_switch_audit_by_workspace ON memory_switch_audit "
        "(workspace_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE memory_switch_audit")
    op.execute("DROP TABLE memory_switch")
    op.execute("DROP TABLE memory_bundle_journal")
    op.execute("DROP TABLE memory_event")
    op.execute("DROP TABLE memory_claim_ref")
    op.execute("DROP TABLE memory")
    op.execute("ALTER TABLE project DROP CONSTRAINT project_workspace_anchor")
