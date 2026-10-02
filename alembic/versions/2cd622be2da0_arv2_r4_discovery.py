"""arv2 r4: verified account discovery — fleet kind, discovery runs and candidates

Revision ID: 2cd622be2da0
Revises: 71e80c777cf6
Create Date: 2026-09-10 00:00:00.000000+00:00

Track R (ARV2 verified account discovery), R4 — the substrate the discovery driver works from
(spec: docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md §5–§6):

1. ``fleet_task_kind`` gains ``arv2_discovery``. A discovery run takes minutes, spends money on
   two providers, and must survive a worker restart, so it is a fleet job of its own kind driven
   beside the account-research handler — ONE job per run (the long list, the verification and the
   candidates are steps of one run, not separate leases).

2. ``arv2_discovery_run`` — one launched discovery request, pinned to the ICP document it was run
   against (the artifact key and its sha, the ICP key/version) so a run is replayable against
   exactly the document a human asked for rather than whatever the project has since moved to.
   ``status`` carries the seam-1 vocabulary verbatim (``not_started`` / ``in_progress`` /
   ``needs_review`` / ``completed`` / ``suspended``), so a reader learns one vocabulary across the
   ARV2 lane. The pool-exhaustion counters (``asked`` / ``found_strict`` / ``found_relaxed`` /
   ``analyzed`` / ``recall_estimate``) are columns rather than receipt keys because §4's "a short
   list is information, never padded" is a thing the product reads and reports, not a log line.
   ``(workspace_id, request_sha256)`` is unique: a re-launch of the same signed-off request finds
   the run it already made instead of paying for a second one.

   ``webset_id`` / ``strict_search_id`` / ``relaxed_search_id`` are the "already bought" record.
   The webset id alone was not enough: a webset holds *searches*, and a resumed run that could not
   see which search was the strict one guessed by array position, and a resumed relaxed pass bought
   a second widening search whose exclusion did not name the first one — Exa re-finds, and
   re-charges for, everything it already returned. Recording both search ids makes "never buy this
   twice" a fact of the row rather than of one attempt's memory.

3. ``arv2_discovery_candidate`` — one company the long list returned, with the pass it came from
   (``strict`` / ``relaxed``), its verified ``domain`` (unique per run), the provider's raw
   snapshot, the per-gate verdicts, the derived ``fit`` and its ``disposition``.

   ``decision`` is the approval, and it is deliberately nullable-or-``'approved'`` only —
   ruling 1′ (rev 5), **unapproved is not rejected**: a candidate the human did not tick carries
   no "rejected" label anywhere, it is simply a row with no decision, and the store's
   ``not_chosen_before`` disposition is how a *later* run remembers not to re-surface it. There is
   no vocabulary in this schema for rejecting a company, because the product never rejects one.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Reversibility follows the ``a3602967bb73`` precedent exactly: PostgreSQL cannot drop an enum
label, so ``downgrade()`` refuses while any ``arv2_discovery`` task exists and otherwise rebuilds
the type without the label (rename → CREATE → ALTER COLUMN … USING → DROP).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2cd622be2da0"
down_revision: str | None = "71e80c777cf6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``ARV2_DISCOVERY``.
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
    "arv2_account_research",
)

#: The seam-1 states, verbatim — the same vocabulary R2's runs and jobs carry.
_STATUSES = "('not_started', 'in_progress', 'needs_review', 'completed', 'suspended')"

#: What a verified candidate *is*, never what it was refused for. ``not_chosen_before`` is how a
#: later run in the same project remembers a candidate the human did not tick (ruling 1′, rev 5).
_DISPOSITIONS = (
    "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'not_chosen_before')"
)


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (PG16
    # forbids only the use, not the addition) — the af3cf1541ebe / a3602967bb73 precedent.
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'arv2_discovery'")
    op.execute(
        f"""
        CREATE TABLE arv2_discovery_run (
            run_id               uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            project_id           text NOT NULL,
            brand_id             text NOT NULL,
            project_run_id       uuid NOT NULL REFERENCES project_run (id),
            icp_artifact_key     text NOT NULL,
            icp_artifact_sha256  text NOT NULL,
            icp_key              text NOT NULL,
            icp_version          integer NOT NULL,
            requested_by_user_id text NOT NULL,
            request_sha256       text NOT NULL,
            target_count         integer NOT NULL CHECK (target_count > 0),
            strict_count         integer NOT NULL CHECK (strict_count > 0),
            relaxed_enabled      boolean NOT NULL,
            relaxed_requested    boolean NOT NULL DEFAULT false,
            criteria_gate_keys   jsonb NOT NULL,
            status               text NOT NULL DEFAULT 'not_started',
            webset_id            text,
            strict_search_id     text,
            relaxed_search_id    text,
            asked                integer,
            found_strict         integer,
            found_relaxed        integer,
            analyzed             integer,
            recall_estimate      integer,
            receipt_json         jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),
            started_at           timestamptz,
            finished_at          timestamptz,
            CONSTRAINT arv2_discovery_run_status CHECK (status IN {_STATUSES}),
            CONSTRAINT arv2_discovery_run_request UNIQUE (workspace_id, request_sha256)
        )
        """
    )
    op.execute(
        "CREATE INDEX arv2_discovery_run_project ON arv2_discovery_run "
        "(workspace_id, project_id, created_at DESC)"
    )
    op.execute(
        f"""
        CREATE TABLE arv2_discovery_candidate (
            candidate_id           uuid PRIMARY KEY,
            run_id                 uuid NOT NULL REFERENCES arv2_discovery_run (run_id),
            workspace_id           text NOT NULL,
            project_id             text NOT NULL,
            pass                   text NOT NULL CHECK (pass IN ('strict', 'relaxed')),
            domain                 text NOT NULL,
            websets_url            text,
            name                   text NOT NULL,
            provider_snapshot_json jsonb NOT NULL,
            verdicts_json          jsonb NOT NULL DEFAULT '[]'::jsonb,
            fit                    numeric(4,3),
            disposition            text NOT NULL DEFAULT 'pending',
            decision               text,
            decided_by_user_id     text,
            decided_at             timestamptz,
            account_entity_id      uuid REFERENCES account_entity (id),
            created_at             timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT arv2_discovery_candidate_run_domain UNIQUE (run_id, domain),
            CONSTRAINT arv2_discovery_candidate_disposition CHECK (disposition IN {_DISPOSITIONS}),
            CONSTRAINT arv2_discovery_candidate_decision CHECK (
                decision IS NULL OR decision = 'approved')
        )
        """
    )
    op.execute(
        "CREATE INDEX arv2_discovery_candidate_project_domain ON arv2_discovery_candidate "
        "(workspace_id, project_id, domain)"
    )
    op.execute(
        "CREATE INDEX arv2_discovery_candidate_account ON arv2_discovery_candidate "
        "(account_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE arv2_discovery_candidate")
    op.execute("DROP TABLE arv2_discovery_run")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'arv2_discovery') THEN
                RAISE EXCEPTION 'cannot downgrade R4 while arv2_discovery fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_r4")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_r4")
