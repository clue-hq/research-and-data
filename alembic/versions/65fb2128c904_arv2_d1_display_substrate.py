"""ARV2 D1 — the display substrate: priority/outreach-safety/write-markers on claim, owner columns
on account_entity, display_block, display_section_recipe, provider_call_ledger,
account_activity_event, workspace_field_definition.presentation, and the persona vocabulary
data-fix (Persona gains ``user``).

Revision ID: 65fb2128c904
Revises: 44039cb83844
Create Date: 2026-09-07

Master plan v1.6 §4 and ARV2-DATA-SOURCE-MAP v1.1 §2.2. Conventions: append-only claim history,
UTC timestamptz, jsonb payloads with indexed hot keys, everything keyed on entity ids, forward +
reverse.

The persona vocabulary is not a Postgres enum: it is the ``enum`` list inside three registered
value schemas (``contact.persona``, ``contact.role_on_committee``, ``account.value_narrative``),
built at pack-load time from ``clue_core.Persona``. Adding ``user`` to the Python enum changes
those schemas, and ``register_field`` refuses a redefinition, so this revision rewrites the stored
rows to match. On a fresh database the UPDATEs touch zero rows; that is fine.

The three new claim columns are deliberately NOT added to the append-only immutable-column guard:
``signal_priority`` and ``outreach_safe`` are governance annotations whose change is a display
invalidation event (master plan §7), and ``write_markers`` records write-time checks. Supersession
remains the way a value changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65fb2128c904"
down_revision: str | None = "44039cb83844"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


_COMMENTS: tuple[tuple[str, str], ...] = (
    (
        "claim.signal_priority",
        "ARV2 signal priority: 1 active buying intent, 2 qualifying fact, 3 context. Stamped at "
        "write time; orders display items, never gates.",
    ),
    (
        "claim.outreach_safe",
        "ARV2 appropriateness flag, distinct from accuracy: false confines the claim to restricted "
        "display sections and bars it from outreach copy.",
    ),
    (
        "claim.write_markers",
        "ARV2 lenient-write annotations recorded at insert (schema_valid, source_missing, "
        "proposed_field, identity_binding_defaulted, use_class_defaulted, pipe_joined_key, "
        "evidence_verbatim, unevidenced, entailment). NULL = nothing to note.",
    ),
    (
        "account_entity.owner_user_id",
        "Assigned account owner (a workspace user). NULL = unassigned; the frontend then shows "
        "createdBy, else 'Unassigned' — never the viewer (ruling R6).",
    ),
    (
        "account_entity.created_by_user_id",
        "The user who created the account; NULL when an agent or loader created it.",
    ),
    (
        "display_block",
        "One persisted display section for one subject and page: the Luna-written body with the "
        "claim ids every sentence cites. Generated once on first request, superseded on "
        "recipe-scoped invalidation (master plan §7).",
    ),
    (
        "display_section_recipe",
        "One page section's allow-list of field keys plus its served heading and layout flags. "
        "An empty-string workspace_id = the system row; a workspace row overrides it.",
    ),
    (
        "provider_call_ledger",
        "One row per provider-call phase (estimate before the wire, result after) written by the "
        "ARV2 ProviderCaller; raw bodies are artifact rows the row references (Appendix A laws "
        "1-2).",
    ),
    (
        "account_activity_event",
        "The account activity feed: actor-based events written by the backend (account created, "
        "researched, committee confirmed, page written, artifact bound).",
    ),
    (
        "workspace_field_definition.presentation",
        "How a custom variable renders on the accounts screens: text, badge or score (contract v1 "
        "customFields.presentation).",
    ),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE claim ADD COLUMN signal_priority smallint NOT NULL DEFAULT 3, "
        "ADD COLUMN outreach_safe boolean NOT NULL DEFAULT true, "
        "ADD COLUMN write_markers jsonb"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_signal_priority_range "
        "CHECK (signal_priority BETWEEN 1 AND 3)"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_write_markers_object "
        "CHECK (write_markers IS NULL OR jsonb_typeof(write_markers) = 'object')"
    )
    op.execute(
        "CREATE INDEX claim_live_unsafe ON claim (entity_id) "
        "WHERE superseded_by IS NULL AND outreach_safe = false"
    )

    op.execute(
        "ALTER TABLE account_entity ADD COLUMN owner_user_id text, "
        "ADD COLUMN created_by_user_id text"
    )
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_owner_user_fk "
        "FOREIGN KEY (owner_user_id) REFERENCES platform_user (user_id)"
    )
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_created_by_user_fk "
        "FOREIGN KEY (created_by_user_id) REFERENCES platform_user (user_id)"
    )

    op.execute(
        "ALTER TABLE workspace_field_definition ADD COLUMN presentation text "
        "NOT NULL DEFAULT 'text'"
    )
    op.execute(
        "ALTER TABLE workspace_field_definition ADD CONSTRAINT "
        "workspace_field_definition_presentation "
        "CHECK (presentation IN ('text', 'badge', 'score'))"
    )

    op.execute(
        """
        CREATE TABLE display_section_recipe (
            page                 text    NOT NULL,
            section_key          text    NOT NULL,
            workspace_id         text    NOT NULL DEFAULT '',
            h1                   text    NOT NULL,
            position             integer NOT NULL,
            allowed_field_keys   text[]  NOT NULL,
            restricted           boolean NOT NULL DEFAULT false,
            default_open         boolean NOT NULL DEFAULT false,
            instruction_version  text    NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT display_section_recipe_pkey
                PRIMARY KEY (page, section_key, workspace_id),
            CONSTRAINT display_section_recipe_page
                CHECK (page IN ('overview', 'insights', 'contact')),
            CONSTRAINT display_section_recipe_h1_nonempty CHECK (length(h1) > 0),
            CONSTRAINT display_section_recipe_position_nonneg CHECK (position >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN display_section_recipe.workspace_id IS "
        "'Empty string = the system recipe (a NULL cannot sit in a primary key); a workspace id "
        "= that workspace''s override row.'"
    )

    op.execute(
        """
        CREATE TABLE display_block (
            display_block_id  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      text        NOT NULL REFERENCES workspace (workspace_id),
            subject_kind      text        NOT NULL,
            subject_id        uuid        NOT NULL,
            page              text        NOT NULL,
            section_key       text        NOT NULL,
            body_json         jsonb       NOT NULL,
            cited_claim_ids   uuid[]      NOT NULL,
            model             text        NOT NULL,
            prompt_version    text        NOT NULL,
            recipe_version    integer     NOT NULL,
            generated_at      timestamptz NOT NULL DEFAULT now(),
            superseded_at     timestamptz,
            CONSTRAINT display_block_subject_kind
                CHECK (subject_kind IN ('account', 'contact')),
            CONSTRAINT display_block_page
                CHECK (page IN ('overview', 'insights', 'contact')),
            CONSTRAINT display_block_body_object CHECK (jsonb_typeof(body_json) = 'object')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX display_block_live ON display_block "
        "(workspace_id, subject_kind, subject_id, page, section_key) "
        "WHERE superseded_at IS NULL"
    )
    op.execute(
        "CREATE INDEX display_block_subject ON display_block "
        "(workspace_id, subject_kind, subject_id, page)"
    )

    op.execute(
        """
        CREATE TABLE provider_call_ledger (
            ledger_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            call_id                 uuid NOT NULL,
            workspace_id            text,
            project_id              text,
            project_run_id          text,
            entity_research_job_id  uuid,
            provider                text NOT NULL,
            operation               text NOT NULL,
            label                   text NOT NULL,
            phase                   text NOT NULL,
            http_status             integer,
            latency_ms              integer,
            attempts                integer NOT NULL DEFAULT 0,
            estimate_usd            numeric(12, 6) NOT NULL DEFAULT 0,
            estimate_credits        numeric(12, 3) NOT NULL DEFAULT 0,
            estimate_media_seconds  integer NOT NULL DEFAULT 0,
            cost_usd                numeric(12, 6),
            credits                 numeric(12, 3),
            media_seconds           integer,
            over_ceiling            boolean NOT NULL DEFAULT false,
            outcome                 text NOT NULL,
            error_code              text,
            provider_request_id     text,
            request_artifact_key    text,
            response_artifact_key   text,
            recorded_at             timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT provider_call_ledger_phase CHECK (phase IN ('estimate', 'result')),
            CONSTRAINT provider_call_ledger_outcome CHECK (outcome IN (
                'estimate', 'ok', 'client_error', 'retry_exhausted', 'halted',
                'transport_error'))
        )
        """
    )
    op.execute(
        "CREATE INDEX provider_call_ledger_workspace_time ON provider_call_ledger "
        "(workspace_id, recorded_at)"
    )
    op.execute("CREATE INDEX provider_call_ledger_call ON provider_call_ledger (call_id)")

    op.execute(
        """
        CREATE TABLE account_activity_event (
            event_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id       text        NOT NULL REFERENCES workspace (workspace_id),
            account_entity_id  uuid        NOT NULL,
            kind               text        NOT NULL,
            actor_kind         text        NOT NULL,
            actor_user_id      text        REFERENCES platform_user (user_id),
            text               text        NOT NULL,
            action             text,
            occurred_at        timestamptz NOT NULL,
            project_id         text,
            ref_json           jsonb,
            CONSTRAINT account_activity_event_account_fk
                FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_activity_event_kind
                CHECK (kind IN ('created', 'contacts', 'summary', 'artifact', 'updated')),
            CONSTRAINT account_activity_event_actor_kind
                CHECK (actor_kind IN ('clue', 'person')),
            CONSTRAINT account_activity_event_actor_shape CHECK (
                (actor_kind = 'clue' AND actor_user_id IS NULL) OR
                (actor_kind = 'person' AND actor_user_id IS NOT NULL)),
            CONSTRAINT account_activity_event_text_nonempty CHECK (length(text) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX account_activity_event_feed ON account_activity_event "
        "(workspace_id, account_entity_id, occurred_at DESC, event_id DESC)"
    )

    # D8 data-fix: append 'user' to the three stored persona vocabularies where present.
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{enum}', (value_schema->'enum') || '"user"')
        WHERE field_key = 'contact.persona'
          AND value_schema ? 'enum'
          AND NOT (value_schema->'enum') ? 'user'
        """
    )
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{properties,role,enum}',
                                     (value_schema#>'{properties,role,enum}') || '"user"')
        WHERE field_key = 'contact.role_on_committee'
          AND value_schema#>'{properties,role,enum}' IS NOT NULL
          AND NOT (value_schema#>'{properties,role,enum}') ? 'user'
        """
    )
    op.execute(
        """
        UPDATE field_definition
        SET value_schema = jsonb_set(value_schema, '{properties,persona,enum}',
                                     (value_schema#>'{properties,persona,enum}') || '"user"')
        WHERE field_key = 'account.value_narrative'
          AND value_schema#>'{properties,persona,enum}' IS NOT NULL
          AND NOT (value_schema#>'{properties,persona,enum}') ? 'user'
        """
    )

    for target, comment in _COMMENTS:
        keyword = "COLUMN" if "." in target else "TABLE"
        op.execute(f"COMMENT ON {keyword} {target} IS {_literal(comment)}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_activity_event")
    op.execute("DROP TABLE IF EXISTS provider_call_ledger")
    op.execute("DROP TABLE IF EXISTS display_block")
    op.execute("DROP TABLE IF EXISTS display_section_recipe")
    op.execute(
        "ALTER TABLE workspace_field_definition DROP CONSTRAINT IF EXISTS "
        "workspace_field_definition_presentation"
    )
    op.execute("ALTER TABLE workspace_field_definition DROP COLUMN IF EXISTS presentation")
    op.execute("ALTER TABLE account_entity DROP CONSTRAINT IF EXISTS account_entity_owner_user_fk")
    op.execute(
        "ALTER TABLE account_entity DROP CONSTRAINT IF EXISTS account_entity_created_by_user_fk"
    )
    op.execute(
        "ALTER TABLE account_entity DROP COLUMN IF EXISTS owner_user_id, "
        "DROP COLUMN IF EXISTS created_by_user_id"
    )
    op.execute("DROP INDEX IF EXISTS claim_live_unsafe")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_write_markers_object")
    op.execute("ALTER TABLE claim DROP CONSTRAINT IF EXISTS claim_signal_priority_range")
    op.execute(
        "ALTER TABLE claim DROP COLUMN IF EXISTS write_markers, "
        "DROP COLUMN IF EXISTS outreach_safe, DROP COLUMN IF EXISTS signal_priority"
    )
    # The persona 'user' label stays in the three value schemas: the Python enum keeps it, and a
    # pack reload against the downgraded row would refuse a redefinition otherwise.
