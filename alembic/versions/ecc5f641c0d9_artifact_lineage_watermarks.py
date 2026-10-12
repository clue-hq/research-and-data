"""artifact lineage watermarks

Revision ID: ecc5f641c0d9
Revises: 349779801104
Create Date: 2026-10-12 17:13:20.659253+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

A saved research step (model request and reply, tool result, plan, dossier: every artifact
``ResearchArtifacts.persist_body`` writes) used to get one ``artifact_derivation`` row per evidence
source of its run and account, plus its context items: steps x sources rows, ~460,000 per account
run. Those parents were always "every source published up to now" (by subject) plus the context, so
one row per step now says the same thing:

* ``artifact_evidence_watermark``: the step saw the evidence of (run, account) up to
  ``evidence_revision``; ``subject_key`` is the person for a person job, the account otherwise.
* ``artifact_context_lineage``: the step saw context ``context_id`` (documents, pin, supports).

Erasing an evidence source at revision r (subject s) erases every step with the same run and
account, a watermark >= r, and ``s`` = the account or ``subject_key`` in (account, s); erasing a
context item erases every step of that context. Both take an exclusive advisory lock that saving
takes shared, which closes the window between a save's erasure check and its row (the per-source
``FOR SHARE`` locks did that before).

Existing steps keep their old links, which this trigger still follows, so erasure is complete from
the moment this runs. ``scripts/backfill_artifact_lineage.py`` converts them in batches on a live
database (deleting only links the new rows cover); it is not part of the migration because one
statement over millions of links held the table for minutes. Specification:
docs/superpowers/specs/2026-10-12-research-storage-linear-growth-design.md §4.1.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ecc5f641c0d9"
down_revision: str | None = "349779801104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET_ERASED = (
    "privacy_erased=true, erased_at=COALESCE(a.erased_at,now()), "
    "erasure_reason=NEW.erasure_reason, source_url=NULL"
)

# Every artifact that is a context item of a context: documents, the pin, claim supports.
_CONTEXT_ITEMS = """
    SELECT workspace_id, context_id, artifact_key FROM arv2_context_document
    UNION SELECT workspace_id, context_id, manifest_key FROM arv2_research_context_pin
    UNION SELECT s.workspace_id, q.context_id, s.artifact_key FROM claim_quality_support s
      JOIN claim_quality_current q ON q.assessment_id=s.assessment_id
      WHERE q.context_id IS NOT NULL
"""


def _contexts_of(workspace: str, key: str) -> str:
    """The contexts an artifact is a context item of (document, pin or claim support), looked up
    by that one artifact through indexes, never by joining every context item."""
    return f"""
      SELECT context_id FROM arv2_context_document
        WHERE workspace_id={workspace} AND artifact_key={key}
      UNION SELECT context_id FROM arv2_research_context_pin
        WHERE workspace_id={workspace} AND manifest_key={key}
      UNION SELECT q.context_id FROM claim_quality_support sup
        JOIN claim_quality_current q ON q.assessment_id=sup.assessment_id
        WHERE sup.workspace_id={workspace} AND sup.artifact_key={key}
          AND q.context_id IS NOT NULL"""


# Downgrade: expand the rows back into one link per covered parent.
EXPAND_EVIDENCE_LINKS = """
      INSERT INTO artifact_derivation (workspace_id, parent_key, child_key)
      SELECT w.workspace_id, s.artifact_key, w.child_key
      FROM artifact_evidence_watermark w
      JOIN arv2_evidence_source s ON s.workspace_id=w.workspace_id AND s.run_id=w.run_id
        AND s.account_id=w.account_id AND s.revision<=w.evidence_revision
        AND (s.subject_id=s.account_id OR w.subject_key IN (w.account_id, s.subject_id))
      WHERE s.artifact_key<>w.child_key
      ON CONFLICT DO NOTHING
    """

EXPAND_CONTEXT_LINKS = f"""
      INSERT INTO artifact_derivation (workspace_id, parent_key, child_key)
      SELECT l.workspace_id, i.artifact_key, l.child_key
      FROM artifact_context_lineage l
      JOIN ({_CONTEXT_ITEMS}) i ON i.workspace_id=l.workspace_id AND i.context_id=l.context_id
      WHERE i.artifact_key<>l.child_key
      ON CONFLICT DO NOTHING
    """


def upgrade() -> None:
    op.execute("""
      CREATE TABLE artifact_evidence_watermark (
        workspace_id text NOT NULL,
        child_key text NOT NULL,
        run_id uuid NOT NULL,
        account_id uuid NOT NULL,
        subject_key uuid NOT NULL,
        evidence_revision bigint NOT NULL,
        CONSTRAINT artifact_evidence_watermark_pk
          PRIMARY KEY(workspace_id,child_key,run_id,account_id,subject_key),
        CONSTRAINT artifact_evidence_watermark_child FOREIGN KEY(child_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT artifact_evidence_watermark_manifest FOREIGN KEY(workspace_id,run_id,account_id)
          REFERENCES arv2_evidence_manifest(workspace_id,run_id,account_id),
        CONSTRAINT artifact_evidence_watermark_revision CHECK(evidence_revision>=0)
      )
    """)
    op.execute(
        "CREATE INDEX artifact_evidence_watermark_scope ON artifact_evidence_watermark"
        "(workspace_id,run_id,account_id,evidence_revision)"
    )
    op.execute("""
      CREATE TABLE artifact_context_lineage (
        workspace_id text NOT NULL,
        child_key text NOT NULL,
        context_id uuid NOT NULL,
        CONSTRAINT artifact_context_lineage_pk PRIMARY KEY(workspace_id,child_key,context_id),
        CONSTRAINT artifact_context_lineage_child FOREIGN KEY(child_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT artifact_context_lineage_context FOREIGN KEY(context_id,workspace_id)
          REFERENCES arv2_research_context_pin(context_id,workspace_id)
      )
    """)
    op.execute(
        "CREATE INDEX artifact_context_lineage_context ON artifact_context_lineage"
        "(workspace_id,context_id)"
    )
    # The erasure trigger looks sources and pins up by artifact.
    op.execute(
        "CREATE INDEX arv2_evidence_source_artifact ON arv2_evidence_source"
        "(workspace_id,artifact_key)"
    )
    op.execute(
        "CREATE INDEX arv2_research_context_pin_manifest ON arv2_research_context_pin"
        "(workspace_id,manifest_key)"
    )

    op.execute(f"""
      CREATE OR REPLACE FUNCTION erase_derived_artifacts() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE
        ev record;
        c uuid;
      BEGIN
        IF NEW.privacy_erased AND NOT OLD.privacy_erased THEN
          -- Precise links (claims, pages, reconciliation, evidence originals, dossier reports).
          -- workspace_id first so the primary key serves the lookup.
          UPDATE artifact a SET {_SET_ERASED}
          FROM artifact_derivation d
          WHERE d.workspace_id=NEW.workspace_id AND d.parent_key=NEW.storage_key
            AND a.storage_key=d.child_key AND NOT a.privacy_erased;
          -- Steps that saw this evidence: same run and account, watermark at or past it.
          FOR ev IN SELECT run_id, account_id, subject_id, revision FROM arv2_evidence_source
                   WHERE workspace_id=NEW.workspace_id AND artifact_key=NEW.storage_key LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended(
              'artifact-lineage:'||NEW.workspace_id||':'||ev.run_id||':'||ev.account_id, 0));
            UPDATE artifact a SET {_SET_ERASED}
            FROM artifact_evidence_watermark w
            WHERE w.workspace_id=NEW.workspace_id AND w.run_id=ev.run_id
              AND w.account_id=ev.account_id AND w.evidence_revision>=ev.revision
              AND (ev.subject_id=ev.account_id OR w.subject_key IN (w.account_id, ev.subject_id))
              AND a.storage_key=w.child_key AND NOT a.privacy_erased;
          END LOOP;
          -- Steps that saw this context item.
          FOR c IN {_contexts_of("NEW.workspace_id", "NEW.storage_key")} LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended(
              'artifact-lineage-context:'||NEW.workspace_id||':'||c, 0));
            UPDATE artifact a SET {_SET_ERASED}
            FROM artifact_context_lineage l
            WHERE l.workspace_id=NEW.workspace_id AND l.context_id=c
              AND a.storage_key=l.child_key AND NOT a.privacy_erased;
          END LOOP;
        END IF;
        RETURN NEW;
      END $$
    """)


def downgrade() -> None:
    op.execute(EXPAND_EVIDENCE_LINKS)
    op.execute(EXPAND_CONTEXT_LINKS)
    op.execute("""
      CREATE OR REPLACE FUNCTION erase_derived_artifacts() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.privacy_erased AND NOT OLD.privacy_erased THEN
          UPDATE artifact a SET privacy_erased=true,erased_at=COALESCE(a.erased_at,now()),
            erasure_reason=NEW.erasure_reason,source_url=NULL
          FROM artifact_derivation d WHERE d.parent_key=NEW.storage_key
            AND a.storage_key=d.child_key AND NOT a.privacy_erased;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute("DROP INDEX arv2_research_context_pin_manifest")
    op.execute("DROP INDEX arv2_evidence_source_artifact")
    op.execute("DROP TABLE artifact_context_lineage")
    op.execute("DROP TABLE artifact_evidence_watermark")
