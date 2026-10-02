"""arv2 r2 account research jobs

Revision ID: a3602967bb73
Revises: 9f81e5692fea
Create Date: 2026-09-07 23:42:20.277205+00:00

Track R (ARV2 account research), R2 — the substrate the account research agent drives from:

1. ``fleet_task_kind`` gains ``arv2_account_research``. ONE job per account, not one per run: an
   account that fails takes only itself down, and each account has exactly one lease and one
   place to resume from.

2. ``arv2_research_run`` — one launched research request. It records what the launch was pinned
   to (the ICP artifact and its sha, the ICP key/version, the product selection version, the
   agent profile ref and its sha, the request sha) so a run can be replayed against exactly the
   inputs a human signed off on, and never against whatever recon has since advanced to.

3. ``arv2_research_job`` — one account inside a run. ``status`` carries the seam-1 job states
   verbatim (``not_started`` / ``in_progress`` / ``needs_review`` / ``completed`` /
   ``suspended``); the CHECKs make a terminal row without a ``finished_at``, or a
   ``needs_review`` row without a failure code, unrepresentable.

4. ``arv2_claim_annotation`` — the link-audit verdict for one claim, kept beside the claim rather
   than inside it: an annotation is a *check result*, never the claim's own value, and the
   append-only claim history must not be edited to record one.

5. ``provider_call_ledger.extras_json`` — per-call provider detail the D1 ledger has no column
   for. ``provider_call_ledger.entity_research_job_id`` carries the R2 ``job_id``: the column
   name is the D1 migration's, and its meaning here is "the job that spent" (documented at
   ``provider_ledger.py``).

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Reversibility follows the ``af3cf1541ebe`` precedent exactly: PostgreSQL cannot drop an enum
label, so ``downgrade()`` refuses while any ``arv2_account_research`` task exists and otherwise
rebuilds the type without the label (rename → CREATE → ALTER COLUMN … USING → DROP).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3602967bb73"
down_revision: str | None = "9f81e5692fea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``ARV2_ACCOUNT_RESEARCH``.
_KINDS_BEFORE = (
    "drive_run",
    "account_job",
    "execute_graph",
    "entity_research_job",
    "agent_turn",
    "stage0_recon",
    "official_site_crawl",
    "design_job",
    "onboarding_run",
)

#: The seam-1 job states, verbatim. Runs and jobs share them so a reader learns one vocabulary.
_STATUSES = "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended')"


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (PG16
    # forbids only the use, not the addition) — the af3cf1541ebe precedent.
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_account_research'")
    op.execute(
        f"""
        CREATE TABLE arv2_research_run (
            run_id                    uuid PRIMARY KEY,
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            brand_id                  text NOT NULL,
            project_run_id            uuid NOT NULL REFERENCES project_run (id),
            icp_artifact_key          text NOT NULL,
            icp_artifact_sha256       text NOT NULL,
            icp_key                   text NOT NULL,
            icp_version               integer NOT NULL,
            product_selection_version integer NOT NULL,
            effort                    text NOT NULL,
            committee_cap             integer NOT NULL,
            directive_text            text NOT NULL DEFAULT '',
            profile_ref               text NOT NULL,
            profile_sha256            text NOT NULL,
            requested_by_user_id      text NOT NULL,
            request_sha256            text NOT NULL,
            status                    text NOT NULL DEFAULT 'not_started',
            created_at                timestamptz NOT NULL DEFAULT now(),
            finished_at               timestamptz,
            CONSTRAINT arv2_research_run_icp_sha CHECK (icp_artifact_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_profile_sha CHECK (profile_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_request_sha CHECK (request_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT arv2_research_run_effort CHECK (effort IN ('full', 'reduced', 'cheap-pass')),
            CONSTRAINT arv2_research_run_cap CHECK (committee_cap >= 1),
            CONSTRAINT arv2_research_run_selection CHECK (product_selection_version >= 1),
            CONSTRAINT arv2_research_run_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_research_run_finished CHECK (
                (status IN ('completed', 'needs_review')) = (finished_at IS NOT NULL))
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE arv2_research_job (
            job_id             uuid PRIMARY KEY,
            run_id             uuid NOT NULL REFERENCES arv2_research_run (run_id),
            workspace_id       text NOT NULL,
            account_entity_id  uuid NOT NULL,
            status             text NOT NULL DEFAULT 'not_started',
            attempt            integer NOT NULL DEFAULT 0,
            started_at         timestamptz,
            finished_at        timestamptz,
            finalization_json  jsonb,
            failure_code       text,
            failure_message    text,
            model_rounds       integer NOT NULL DEFAULT 0,
            tool_calls         integer NOT NULL DEFAULT 0,
            cost_usd           numeric(12, 6) NOT NULL DEFAULT 0,
            credits            numeric(12, 3) NOT NULL DEFAULT 0,
            media_seconds      integer NOT NULL DEFAULT 0,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_research_job_account_fk FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT arv2_research_job_once UNIQUE (run_id, account_entity_id),
            CONSTRAINT arv2_research_job_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_research_job_finished CHECK (
                (status IN ('completed', 'needs_review')) = (finished_at IS NOT NULL)),
            CONSTRAINT arv2_research_job_failure CHECK (
                (status = 'needs_review') = (failure_code IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX arv2_research_job_run ON arv2_research_job (run_id)")
    op.execute(
        "CREATE INDEX arv2_research_job_account ON arv2_research_job "
        "(workspace_id, account_entity_id)"
    )
    op.execute(
        """
        CREATE TABLE arv2_claim_annotation (
            annotation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id      uuid NOT NULL REFERENCES claim (id),
            job_id        uuid NOT NULL REFERENCES arv2_research_job (job_id),
            kind          text NOT NULL,
            verdict       text NOT NULL,
            detail_json   jsonb,
            checked_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_claim_annotation_kind CHECK (kind IN ('link_audit')),
            CONSTRAINT arv2_claim_annotation_verdict CHECK (
                verdict IN ('EXACT', 'PARTIAL', 'NOT_FOUND', 'fetch_failed'))
        )
        """
    )
    op.execute("CREATE INDEX arv2_claim_annotation_claim ON arv2_claim_annotation (claim_id)")
    op.execute("ALTER TABLE provider_call_ledger ADD COLUMN extras_json jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE provider_call_ledger DROP COLUMN extras_json")
    op.execute("DROP TABLE arv2_claim_annotation")
    op.execute("DROP TABLE arv2_research_job")
    op.execute("DROP TABLE arv2_research_run")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_account_research') THEN
                RAISE EXCEPTION 'cannot downgrade R2 while arv2_account_research fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_r2")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_r2")
