"""d7 run_event subject widening

Revision ID: a02cbcb6e641
Revises: 2711924d1e29
Create Date: 2026-08-10 06:14:04.021442+00:00

Part II D7 (design-integration master plan II.5): the durable SSE outbox stops assuming its subject
is a project run. ``run_event`` (and its ``stream_token`` auth row) gain ``subject_kind`` +
``subject_id``, so a design leg is a **first-class stream subject** rather than something forced to
borrow a project-run id — one transport, one auth model, one replay semantics.

Why ``text`` + CHECK and not a Postgres enum for ``subject_kind``
----------------------------------------------------------------
The subject taxonomy is expected to grow (Part III adds agent-shaped subjects, and the plan's own
wording is "where the stream's subject key assumes a project run, widen the subject"). Adding a
value to a CHECK is one ``DROP CONSTRAINT`` + one ``ADD CONSTRAINT`` in a single transaction and is
trivially reversible; adding one to a PG enum is a one-way ``ALTER TYPE ... ADD VALUE`` that cannot
be removed and that a ``downgrade()`` can only undo by rebuilding the type and every column using
it. The repo does use PG enums where the vocabulary is genuinely frozen (``project_phase``,
``idempotency_scope``); this one is not.

Integrity, not convention
-------------------------
``run_id`` becomes NULLABLE, guarded by ``run_event_subject_coherent``:

    (subject_kind = 'project_run' AND run_id IS NOT NULL AND subject_id = run_id::text)
 OR (subject_kind <> 'project_run' AND run_id IS NULL)

so a project-run event can never lie about its subject (the two keys are pinned equal at the DB,
not by a writer's discipline), and a non-project event can never fake a project run (its ``run_id``
is structurally absent, so no project-run reader, index, or join can ever see it).

This is NOT a zero-downtime widening, on purpose
------------------------------------------------
``subject_kind`` has a DEFAULT; ``subject_id`` does not, and is NOT NULL. There is nothing correct
to default ``subject_id`` to for a subject that is not a project run, and a DEFAULT that only
happens to be right for one kind is exactly the sort of quiet mis-classification this widening
exists to make impossible. The consequence, stated plainly: a writer still emitting the pre-D7
column list ``(workspace_id, run_id, topic, payload)`` **fails** on the NOT NULL rather than
writing an unroutable row, so code and schema must ship together. In this repo that is precisely
two writers, both updated in this slice — ``clue_research.durable.emit_run_event`` and the C7.7
``publish_research_view_event_to_run_outbox`` trigger below.

Follow-on edits in this migration
---------------------------------
* ``publish_research_view_event_to_run_outbox`` (C7.7) inserts into ``run_event`` with an explicit
  column list. ``subject_id`` is NOT NULL with no default, so the trigger function is replaced to
  stamp the project-run subject alongside the run id. Its body is restored verbatim on downgrade.
* ``run_event`` is not one of the C5.1 ``_APPEND_ONLY_TABLES``, so the backfill UPDATE is legal
  here (checked, not assumed).

Reversibility
-------------
``downgrade()`` refuses **loudly** if any non-project-run subject row survives (the R2/D5
precedent): restoring ``run_id NOT NULL`` would otherwise either fail with an opaque constraint
error or, worse, silently invite a "just delete them" fix that destroys a tenant's stream history.
An operator who genuinely wants to roll back must first decide what happens to those events.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a02cbcb6e641"
down_revision: str | None = "2711924d1e29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The D7 subject vocabulary, mirrored by clue_core.run_event.RUN_EVENT_SUBJECT_KINDS (a DB-parity
# test binds code to this CHECK). At D7 this comment named two mirrors — the D8 consolidation left
# exactly one; the constraint itself is unchanged.
_SUBJECT_KINDS = "'project_run', 'design_run'"

_RESEARCH_VIEW_TRIGGER_FN_D7 = """
CREATE OR REPLACE FUNCTION publish_research_view_event_to_run_outbox()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    event_payload jsonb;
    legacy_topic text;
BEGIN
    event_payload := jsonb_build_object(
        'source_event_id', NEW.event_id,
        'canonical_topic', NEW.topic,
        'project_id', NEW.project_id,
        'project_run_id', NEW.project_run_id,
        'subject_entity_id', NEW.subject_entity_id,
        'snapshot_id', NEW.snapshot_id,
        'report_id', NEW.report_id,
        'section_ids', to_jsonb(NEW.section_ids),
        'item_ids', to_jsonb(NEW.item_ids),
        'reason_codes', to_jsonb(NEW.reason_codes),
        'fetch_ref', NEW.fetch_ref
    );

    INSERT INTO run_event
        (workspace_id, subject_kind, subject_id, run_id, topic, payload, created_at)
    VALUES (
        NEW.workspace_id, 'project_run', NEW.project_run_id::text, NEW.project_run_id,
        NEW.topic, event_payload, NEW.created_at
    );

    legacy_topic := CASE NEW.topic
        WHEN 'research_view.updated' THEN 'dossier.updated'
        WHEN 'research_view.section_stale' THEN 'dossier.section.stale'
        ELSE NULL
    END;
    IF legacy_topic IS NOT NULL THEN
        INSERT INTO run_event
            (workspace_id, subject_kind, subject_id, run_id, topic, payload, created_at)
        VALUES (
            NEW.workspace_id,
            'project_run',
            NEW.project_run_id::text,
            NEW.project_run_id,
            legacy_topic,
            event_payload || jsonb_build_object('deprecated_alias', true),
            NEW.created_at
        );
    END IF;
    RETURN NEW;
END;
$$
"""

# The pre-D7 body, restored verbatim on downgrade (677607ec1cd1).
_RESEARCH_VIEW_TRIGGER_FN_PRE_D7 = """
CREATE OR REPLACE FUNCTION publish_research_view_event_to_run_outbox()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    event_payload jsonb;
    legacy_topic text;
BEGIN
    event_payload := jsonb_build_object(
        'source_event_id', NEW.event_id,
        'canonical_topic', NEW.topic,
        'project_id', NEW.project_id,
        'project_run_id', NEW.project_run_id,
        'subject_entity_id', NEW.subject_entity_id,
        'snapshot_id', NEW.snapshot_id,
        'report_id', NEW.report_id,
        'section_ids', to_jsonb(NEW.section_ids),
        'item_ids', to_jsonb(NEW.item_ids),
        'reason_codes', to_jsonb(NEW.reason_codes),
        'fetch_ref', NEW.fetch_ref
    );

    INSERT INTO run_event (workspace_id, run_id, topic, payload, created_at)
    VALUES (
        NEW.workspace_id, NEW.project_run_id, NEW.topic, event_payload, NEW.created_at
    );

    legacy_topic := CASE NEW.topic
        WHEN 'research_view.updated' THEN 'dossier.updated'
        WHEN 'research_view.section_stale' THEN 'dossier.section.stale'
        ELSE NULL
    END;
    IF legacy_topic IS NOT NULL THEN
        INSERT INTO run_event (workspace_id, run_id, topic, payload, created_at)
        VALUES (
            NEW.workspace_id,
            NEW.project_run_id,
            legacy_topic,
            event_payload || jsonb_build_object('deprecated_alias', true),
            NEW.created_at
        );
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # --- run_event: the stream subject ---------------------------------------------------------
    # subject_kind DEFAULTs; subject_id deliberately does NOT (see the module docstring). A writer
    # still emitting the pre-D7 column list therefore fails loudly on the NOT NULL rather than
    # writing an unroutable row.
    op.execute("ALTER TABLE run_event ADD COLUMN subject_kind text NOT NULL DEFAULT 'project_run'")
    op.execute("ALTER TABLE run_event ADD COLUMN subject_id text")
    # Backfill: every existing row IS a project-run event (run_id was NOT NULL until this
    # migration), so the subject id is exactly the run id rendered as text.
    op.execute("UPDATE run_event SET subject_id = run_id::text WHERE subject_id IS NULL")
    op.execute("ALTER TABLE run_event ALTER COLUMN subject_id SET NOT NULL")

    op.execute(
        "ALTER TABLE run_event ADD CONSTRAINT run_event_subject_kind_known "
        f"CHECK (subject_kind IN ({_SUBJECT_KINDS}))"
    )
    op.execute(
        "ALTER TABLE run_event ADD CONSTRAINT run_event_subject_id_nonempty "
        "CHECK (length(btrim(subject_id)) > 0)"
    )
    # The integrity rule: a project-run event cannot lie about its subject, and a non-project-run
    # event cannot fake a project run.
    op.execute(
        """
        ALTER TABLE run_event ADD CONSTRAINT run_event_subject_coherent CHECK (
            (subject_kind = 'project_run' AND run_id IS NOT NULL AND subject_id = run_id::text)
            OR (subject_kind <> 'project_run' AND run_id IS NULL)
        )
        """
    )
    # Only now may run_id relax: the CHECK above already forbids a NULL run_id on a project-run row,
    # so the NOT NULL it replaces is strictly weaker than what remains.
    op.execute("ALTER TABLE run_event ALTER COLUMN run_id DROP NOT NULL")

    op.execute(
        "COMMENT ON COLUMN run_event.subject_kind IS 'D7 stream-subject taxonomy "
        "(project_run | design_run). text + CHECK, not a PG enum: the taxonomy grows at Part III+ "
        "and a CHECK swap is reversible where ALTER TYPE ... ADD VALUE is not.'"
    )
    op.execute(
        "COMMENT ON COLUMN run_event.subject_id IS 'D7 stream-subject id, text because id SHAPES "
        "differ per kind (a project run id is a uuid; a design run id is run_<uuid4 hex>). "
        "For subject_kind = project_run it equals run_id::text by CHECK.'"
    )
    op.execute(
        "COMMENT ON COLUMN run_event.run_id IS 'The project run this event belongs to. NULL for "
        "every non-project subject (run_event_subject_coherent), so no project-run reader, index, "
        "or join can ever see another subject''s events.'"
    )
    # The D7 replay hot path: one subject's rows in seq order. The pre-D7 indexes stay — the
    # project-run stream and the workspace stream still read through them.
    op.execute(
        "CREATE INDEX run_event_workspace_subject_seq "
        "ON run_event (workspace_id, subject_kind, subject_id, seq)"
    )

    # The C7.7 aggregation trigger writes an explicit column list; teach it the subject columns.
    op.execute(_RESEARCH_VIEW_TRIGGER_FN_D7)

    # --- stream_token: the same subject, so a token is bound to the stream it opens -------------
    # stream_token.run_id was already NULLABLE (NULL = a workspace-wide token, by design), so the
    # subject columns are nullable together with it: three legal shapes, one CHECK.
    op.execute("ALTER TABLE stream_token ADD COLUMN subject_kind text")
    op.execute("ALTER TABLE stream_token ADD COLUMN subject_id text")
    op.execute(
        "UPDATE stream_token SET subject_kind = 'project_run', subject_id = run_id::text "
        "WHERE run_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE stream_token ADD CONSTRAINT stream_token_subject_kind_known "
        f"CHECK (subject_kind IS NULL OR subject_kind IN ({_SUBJECT_KINDS}))"
    )
    op.execute(
        """
        ALTER TABLE stream_token ADD CONSTRAINT stream_token_subject_coherent CHECK (
            (subject_kind IS NULL AND subject_id IS NULL AND run_id IS NULL)
            OR (subject_kind = 'project_run' AND run_id IS NOT NULL
                AND subject_id = run_id::text)
            OR (subject_kind <> 'project_run' AND run_id IS NULL
                AND length(btrim(subject_id)) > 0)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN stream_token.subject_kind IS 'D7 stream-subject taxonomy, mirroring "
        "run_event.subject_kind. NULL (with a NULL subject_id and run_id) is the workspace-wide "
        "token the pre-D7 schema already allowed.'"
    )
    op.execute(
        "COMMENT ON COLUMN stream_token.subject_id IS 'D7 stream-subject id this token may open a "
        "stream for. Equals run_id::text when subject_kind = project_run (CHECK), so a token can "
        "never authorise a stream other than the one it was minted for.'"
    )


def downgrade() -> None:
    # Refuse loudly rather than destroy: restoring run_id NOT NULL is only meaningful once an
    # operator has decided what happens to the non-project-run stream history (R2/D5 precedent).
    op.execute(
        """
        DO $$
        DECLARE
            stray bigint;
        BEGIN
            SELECT count(*) INTO stray FROM run_event WHERE subject_kind <> 'project_run';
            IF stray > 0 THEN
                RAISE EXCEPTION
                    'refusing to downgrade: run_event holds % non-project-run subject rows; '
                    'restoring run_id NOT NULL would require destroying that stream history — '
                    'decide their fate explicitly first', stray;
            END IF;
            SELECT count(*) INTO stray FROM stream_token
                WHERE subject_kind IS NOT NULL AND subject_kind <> 'project_run';
            IF stray > 0 THEN
                RAISE EXCEPTION
                    'refusing to downgrade: stream_token holds % non-project-run subject rows',
                    stray;
            END IF;
        END
        $$
        """
    )

    op.execute("ALTER TABLE stream_token DROP CONSTRAINT IF EXISTS stream_token_subject_coherent")
    op.execute("ALTER TABLE stream_token DROP CONSTRAINT IF EXISTS stream_token_subject_kind_known")
    op.execute("ALTER TABLE stream_token DROP COLUMN IF EXISTS subject_id")
    op.execute("ALTER TABLE stream_token DROP COLUMN IF EXISTS subject_kind")

    op.execute(_RESEARCH_VIEW_TRIGGER_FN_PRE_D7)

    op.execute("DROP INDEX IF EXISTS run_event_workspace_subject_seq")
    op.execute("ALTER TABLE run_event DROP CONSTRAINT IF EXISTS run_event_subject_coherent")
    op.execute("ALTER TABLE run_event DROP CONSTRAINT IF EXISTS run_event_subject_id_nonempty")
    op.execute("ALTER TABLE run_event DROP CONSTRAINT IF EXISTS run_event_subject_kind_known")
    op.execute("ALTER TABLE run_event ALTER COLUMN run_id SET NOT NULL")
    op.execute("COMMENT ON COLUMN run_event.run_id IS NULL")
    op.execute("ALTER TABLE run_event DROP COLUMN IF EXISTS subject_id")
    op.execute("ALTER TABLE run_event DROP COLUMN IF EXISTS subject_kind")
