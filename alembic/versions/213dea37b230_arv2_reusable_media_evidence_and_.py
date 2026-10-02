"""arv2 reusable media evidence and acquisition ownership

Revision ID: 213dea37b230
Revises: 0ab01fe27c1e
Create Date: 2026-09-22 12:33:34.407492+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md
        §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in
        place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys
        (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down →
        up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "213dea37b230"
down_revision: str | None = "0ab01fe27c1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifact ADD COLUMN erasure_reason text")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_media_job_scope "
        "UNIQUE(workspace_id,job_id)"
    )
    op.execute("""
    CREATE TABLE arv2_media_item (
      workspace_id text NOT NULL, item_id uuid NOT NULL,
      canonical_key text NOT NULL, source_url text, title text NOT NULL DEFAULT '',
      metadata jsonb NOT NULL DEFAULT '{}', current_version uuid,
      created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL DEFAULT now()+interval '30 days',
      erased_at timestamptz, privacy_erased boolean NOT NULL DEFAULT false,
      acquisition_generation integer NOT NULL DEFAULT 0,
      CONSTRAINT arv2_media_item_pk PRIMARY KEY(workspace_id,item_id),
      CONSTRAINT arv2_media_identity UNIQUE(workspace_id,canonical_key)
    )
    """)
    op.execute("""
    CREATE TABLE arv2_media_alias (
      workspace_id text NOT NULL, alias_hash text NOT NULL, item_id uuid NOT NULL,
      evidence_key text,
      CONSTRAINT arv2_media_alias_pk PRIMARY KEY(workspace_id,alias_hash),
      CONSTRAINT arv2_media_alias_evidence FOREIGN KEY(evidence_key,workspace_id)
        REFERENCES artifact(storage_key,workspace_id),
      CONSTRAINT arv2_media_alias_item FOREIGN KEY(workspace_id,item_id)
        REFERENCES arv2_media_item(workspace_id,item_id)
    )
    """)
    op.execute("""
    CREATE TABLE arv2_media_transcript (
      workspace_id text NOT NULL, version_id uuid NOT NULL, item_id uuid NOT NULL,
      text_key text NOT NULL, segments_key text NOT NULL,
      text_sha256 text NOT NULL, char_count integer NOT NULL,
      quality jsonb NOT NULL, recipe text NOT NULL, source_method text NOT NULL,
      supersedes uuid, created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL DEFAULT now()+interval '30 days',
      CONSTRAINT arv2_media_transcript_pk PRIMARY KEY(workspace_id,version_id),
      CONSTRAINT arv2_media_transcript_identity UNIQUE(workspace_id,item_id,version_id),
      CONSTRAINT arv2_media_transcript_text FOREIGN KEY(text_key,workspace_id)
        REFERENCES artifact(storage_key,workspace_id),
      CONSTRAINT arv2_media_transcript_segments FOREIGN KEY(segments_key,workspace_id)
        REFERENCES artifact(storage_key,workspace_id),
      CONSTRAINT arv2_media_transcript_item FOREIGN KEY(workspace_id,item_id)
        REFERENCES arv2_media_item(workspace_id,item_id),
      CONSTRAINT arv2_media_transcript_previous FOREIGN KEY(workspace_id,item_id,supersedes)
        REFERENCES arv2_media_transcript(workspace_id,item_id,version_id),
      CONSTRAINT arv2_media_transcript_length CHECK(char_count>0),
      CONSTRAINT arv2_media_repair_once UNIQUE(workspace_id,supersedes)
    )
    """)
    op.execute(
        "ALTER TABLE arv2_media_item ADD CONSTRAINT arv2_media_current FOREIGN "
        "KEY(workspace_id,item_id,current_version) REFERENCES "
        "arv2_media_transcript(workspace_id,item_id,version_id)"
    )
    op.execute("""
    CREATE TABLE arv2_media_index (
      workspace_id text NOT NULL, index_id uuid NOT NULL, version_id uuid NOT NULL,
      contract jsonb NOT NULL, contract_sha256 text NOT NULL,
      state text NOT NULL DEFAULT 'lexical', created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT arv2_media_index_pk PRIMARY KEY(workspace_id,index_id),
      CONSTRAINT arv2_media_index_version FOREIGN KEY(workspace_id,version_id)
        REFERENCES arv2_media_transcript(workspace_id,version_id),
      CONSTRAINT arv2_media_index_once UNIQUE(workspace_id,version_id,contract_sha256),
      CONSTRAINT arv2_media_index_state CHECK(state IN
        ('lexical','partial','ready','unavailable'))
    )
    """)
    op.execute("""
    CREATE TABLE arv2_media_passage (
      workspace_id text NOT NULL, index_id uuid NOT NULL, ordinal integer NOT NULL,
      start_offset integer NOT NULL, end_offset integer NOT NULL, body text NOT NULL,
      embedding vector, search tsvector GENERATED ALWAYS AS (to_tsvector('english',body))
        STORED,
      CONSTRAINT arv2_media_passage_pk PRIMARY KEY(workspace_id,index_id,ordinal),
      CONSTRAINT arv2_media_passage_index FOREIGN KEY(workspace_id,index_id)
        REFERENCES arv2_media_index(workspace_id,index_id) ON DELETE CASCADE,
      CONSTRAINT arv2_media_passage_bounds CHECK(ordinal>=0 AND start_offset>=0 AND
        end_offset>start_offset AND char_length(body)=end_offset-start_offset)
    )
    """)
    op.execute("CREATE INDEX arv2_media_passage_search ON arv2_media_passage USING gin(search)")
    op.execute("""
    CREATE TABLE arv2_media_operation (
      workspace_id text NOT NULL, operation_id uuid NOT NULL, item_id uuid NOT NULL,
      owner_job uuid NOT NULL, fingerprint text NOT NULL, stage text NOT NULL,
      state text NOT NULL DEFAULT 'reserved', owner_token uuid NOT NULL,
      lease_until timestamptz NOT NULL DEFAULT now()+interval '2 hours',
      seconds integer NOT NULL DEFAULT 0, artifact_keys text[] NOT NULL DEFAULT '{}',
      ledger_ids uuid[] NOT NULL DEFAULT '{}', result jsonb NOT NULL DEFAULT '{}',
      error_code text, created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT arv2_media_operation_pk PRIMARY KEY(workspace_id,operation_id),
      CONSTRAINT arv2_media_operation_item FOREIGN KEY(workspace_id,item_id)
        REFERENCES arv2_media_item(workspace_id,item_id),
      CONSTRAINT arv2_media_operation_job FOREIGN KEY(workspace_id,owner_job)
        REFERENCES arv2_research_job(workspace_id,job_id),
      CONSTRAINT arv2_media_operation_once UNIQUE(workspace_id,item_id,stage,fingerprint),
      CONSTRAINT arv2_media_operation_seconds CHECK(seconds>=0),
      CONSTRAINT arv2_media_operation_state CHECK(state IN
        ('reserved','dispatched','succeeded','failed','unknown','unavailable'))
    )
    """)
    op.execute("""
    CREATE TABLE arv2_media_attempt (
      workspace_id text NOT NULL, attempt_id uuid NOT NULL, job_id uuid NOT NULL,
      item_id uuid, version_id uuid, kind text NOT NULL, outcome text NOT NULL,
      purpose text NOT NULL DEFAULT '', data jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT arv2_media_attempt_pk PRIMARY KEY(workspace_id,attempt_id),
      CONSTRAINT arv2_media_attempt_job FOREIGN KEY(workspace_id,job_id)
        REFERENCES arv2_research_job(workspace_id,job_id),
      CONSTRAINT arv2_media_attempt_item FOREIGN KEY(workspace_id,item_id)
        REFERENCES arv2_media_item(workspace_id,item_id),
      CONSTRAINT arv2_media_attempt_version FOREIGN KEY(workspace_id,version_id)
        REFERENCES arv2_media_transcript(workspace_id,version_id)
    )
    """)
    op.execute(
        "CREATE INDEX arv2_media_attempt_scope ON arv2_media_attempt(workspace_id,job_id,item_id)"
    )
    op.execute(
        "CREATE INDEX arv2_media_claim_version ON claim "
        "((write_markers->'media'->>'version_ref')) WHERE write_markers ? "
        "'media'"
    )
    # The artifact substrate owns expiry/DSAR. Invalidate derived copies in the same transaction.
    op.execute("""
    CREATE FUNCTION arv2_media_artifact_unavailable() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target uuid;
    BEGIN
      IF NEW.erased_at IS NULL OR (OLD.erased_at IS NOT NULL AND
          OLD.privacy_erased=NEW.privacy_erased AND
          OLD.erasure_reason IS NOT DISTINCT FROM NEW.erasure_reason) THEN RETURN NEW; END IF;
      UPDATE arv2_media_attempt SET data='{}',purpose='',outcome='unavailable'
        WHERE workspace_id=NEW.workspace_id AND created_at<=now()-interval '30 days';
      FOR target IN
        SELECT item_id FROM arv2_media_transcript WHERE workspace_id=NEW.workspace_id
          AND (text_key=NEW.storage_key OR segments_key=NEW.storage_key)
        UNION SELECT item_id FROM arv2_media_operation WHERE workspace_id=NEW.workspace_id
          AND NEW.storage_key=ANY(artifact_keys)
      LOOP
        UPDATE arv2_media_item SET erased_at=COALESCE(erased_at,now()),
          privacy_erased=privacy_erased OR (NEW.erasure_reason IS DISTINCT FROM 'retention'),
          source_url=NULL,title='',metadata='{}',
          current_version=NULL WHERE workspace_id=NEW.workspace_id AND item_id=target;
        DELETE FROM arv2_media_passage WHERE workspace_id=NEW.workspace_id AND index_id IN
          (SELECT i.index_id FROM arv2_media_index i JOIN arv2_media_transcript t
            USING(workspace_id,version_id) WHERE t.workspace_id=NEW.workspace_id AND
        t.item_id=target);
        UPDATE arv2_media_index SET state='unavailable' WHERE workspace_id=NEW.workspace_id
          AND version_id IN (SELECT version_id FROM arv2_media_transcript
            WHERE workspace_id=NEW.workspace_id AND item_id=target);
        UPDATE arv2_media_attempt SET purpose='',data='{}',outcome='unavailable'
          WHERE workspace_id=NEW.workspace_id AND item_id=target;
        UPDATE arv2_media_transcript SET expires_at=LEAST(expires_at,now())
          WHERE workspace_id=NEW.workspace_id AND item_id=target;
        UPDATE arv2_media_operation SET state='unavailable',result='{}'
          WHERE workspace_id=NEW.workspace_id AND item_id=target;
        UPDATE artifact SET erased_at=COALESCE(erased_at,now()),
          privacy_erased=true,erasure_reason=NEW.erasure_reason,source_url=NULL
          WHERE workspace_id=NEW.workspace_id AND (erased_at IS NULL OR
            (NEW.privacy_erased AND NOT privacy_erased) OR
            (NEW.erasure_reason IS DISTINCT FROM 'retention' AND erasure_reason='retention'))
          AND storage_key IN (
            SELECT text_key FROM arv2_media_transcript WHERE workspace_id=NEW.workspace_id
        AND item_id=target
            UNION SELECT segments_key FROM arv2_media_transcript WHERE
        workspace_id=NEW.workspace_id AND item_id=target
            UNION SELECT unnest(artifact_keys) FROM arv2_media_operation WHERE
        workspace_id=NEW.workspace_id AND item_id=target);
      END LOOP;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER arv2_media_artifact_erasure AFTER UPDATE OF "
        "erased_at,privacy_erased,erasure_reason ON artifact FOR EACH ROW EXECUTE FUNCTION "
        "arv2_media_artifact_unavailable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER arv2_media_artifact_erasure ON artifact")
    op.execute("DROP FUNCTION arv2_media_artifact_unavailable()")
    op.drop_column("artifact", "erasure_reason")
    op.execute("DROP INDEX arv2_media_claim_version")
    op.execute("ALTER TABLE arv2_media_item DROP CONSTRAINT arv2_media_current")
    for name in ("attempt", "operation", "passage", "index", "transcript", "alias", "item"):
        op.drop_table("arv2_media_" + name)
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_media_job_scope")
