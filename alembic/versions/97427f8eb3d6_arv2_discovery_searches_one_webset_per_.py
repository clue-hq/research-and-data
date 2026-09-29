"""arv2 discovery searches: one webset per search

Revision ID: 97427f8eb3d6
Revises: 4c916b02ed9b
Create Date: 2026-09-28

Founder rulings 2026-09-28 (plan: docs/superpowers/plans/2026-09-28-arv2-discovery-exact-count-and-
find-more.md). A discovery run now asks Exa for exactly the number the human wants, and tops up a
shortfall with further searches — each one a **new webset** that excludes the websets before it,
because ``exclude`` accepts only whole websets or imports (a live 400 proved the old
``{source: "search"}`` form was never accepted) and a second search on the same webset replaces its
items by default. So a run owns up to three websets instead of one:

1. ``arv2_discovery_search`` — one row per search, ``ordinal`` 1–3 in the order they ran,
   ``kind`` ``strict`` / ``strict_topup`` / ``relaxed``. ``external_id`` is the ``externalId`` sent
   to Exa and is written **before** the webset is created, so a worker that dies between Exa's
   answer and the write finds its webset again by that id instead of buying a second one.
   ``webset_id`` stays null until Exa has answered; ``finished_at`` is set once the webset is idle
   and every company it found has been verified. ``exclude_webset_ids`` is exactly what the search
   told Exa to skip.

2. ``arv2_discovery_run`` loses what one-webset runs needed: ``webset_id`` /
   ``strict_search_id`` / ``relaxed_search_id`` (the searches table holds them), ``strict_count``
   (the fixed provider ask of 35 is gone — the first search asks for ``target_count``), and
   ``relaxed_requested`` (the path that reopened a finished run for a relaxed pass is gone: the
   relaxed search runs inside the run, and asking for more is a new run). Existing runs' websets
   are copied into the searches table first.

3. The candidate disposition ``not_chosen_before`` becomes ``found_before``: a later run of a
   project skips every company an earlier discovery of that project found, whatever the human did
   with it.

Reversible: ``downgrade()`` restores the columns from the searches table (``strict_count`` from the
first search's ask) and the old disposition word. Search ids inside a webset are not restored — no
code reads them any more.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "97427f8eb3d6"
down_revision: str | None = "4c916b02ed9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISPOSITIONS_BEFORE = (
    "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'not_chosen_before')"
)
_DISPOSITIONS_AFTER = (
    "('pending', 'pass', 'partial', 'unclear', 'duplicate_of_existing', 'found_before')"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE arv2_discovery_search (
            run_id             uuid NOT NULL REFERENCES arv2_discovery_run (run_id),
            ordinal            smallint NOT NULL,
            kind               text NOT NULL,
            external_id        text NOT NULL,
            webset_id          text,
            asked              integer NOT NULL,
            criteria           jsonb NOT NULL,
            exclude_webset_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            found              integer,
            analyzed           integer,
            recall_estimate    integer,
            created_at         timestamptz NOT NULL DEFAULT now(),
            finished_at        timestamptz,
            CONSTRAINT arv2_discovery_search_pkey PRIMARY KEY (run_id, ordinal),
            CONSTRAINT arv2_discovery_search_ordinal CHECK (ordinal BETWEEN 1 AND 3),
            CONSTRAINT arv2_discovery_search_kind CHECK (
                kind IN ('strict', 'strict_topup', 'relaxed')),
            CONSTRAINT arv2_discovery_search_asked CHECK (asked > 0),
            CONSTRAINT arv2_discovery_search_external_id UNIQUE (external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX arv2_discovery_search_webset ON arv2_discovery_search (webset_id) "
        "WHERE webset_id IS NOT NULL"
    )
    # Every run that bought a webset keeps it, as its first search. ``arv2-discovery:<run>`` is the
    # externalId those runs sent. A relaxed search the old code added to the SAME webset is folded
    # into that row — it bought no webset of its own, and none of the recorded runs has one.
    op.execute(
        """
        INSERT INTO arv2_discovery_search (
            run_id, ordinal, kind, external_id, webset_id, asked, criteria, found, analyzed,
            recall_estimate, created_at, finished_at)
        SELECT run_id, 1, 'strict', 'arv2-discovery:' || run_id::text, webset_id,
               COALESCE(asked, strict_count),
               COALESCE(receipt_json -> 'criteria', '[]'::jsonb),
               found_strict, analyzed, recall_estimate, COALESCE(started_at, created_at),
               finished_at
        FROM arv2_discovery_run
        WHERE webset_id IS NOT NULL
        """
    )
    op.execute("ALTER TABLE arv2_discovery_run DROP COLUMN webset_id")
    op.execute("ALTER TABLE arv2_discovery_run DROP COLUMN strict_search_id")
    op.execute("ALTER TABLE arv2_discovery_run DROP COLUMN relaxed_search_id")
    op.execute("ALTER TABLE arv2_discovery_run DROP COLUMN strict_count")
    op.execute("ALTER TABLE arv2_discovery_run DROP COLUMN relaxed_requested")

    op.execute(
        "ALTER TABLE arv2_discovery_candidate DROP CONSTRAINT arv2_discovery_candidate_disposition"
    )
    op.execute(
        "UPDATE arv2_discovery_candidate SET disposition = 'found_before' "
        "WHERE disposition = 'not_chosen_before'"
    )
    op.execute(
        "ALTER TABLE arv2_discovery_candidate ADD CONSTRAINT arv2_discovery_candidate_disposition "
        f"CHECK (disposition IN {_DISPOSITIONS_AFTER})"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE arv2_discovery_candidate DROP CONSTRAINT arv2_discovery_candidate_disposition"
    )
    op.execute(
        "UPDATE arv2_discovery_candidate SET disposition = 'not_chosen_before' "
        "WHERE disposition = 'found_before'"
    )
    op.execute(
        "ALTER TABLE arv2_discovery_candidate ADD CONSTRAINT arv2_discovery_candidate_disposition "
        f"CHECK (disposition IN {_DISPOSITIONS_BEFORE})"
    )

    op.execute(
        "ALTER TABLE arv2_discovery_run ADD COLUMN relaxed_requested boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE arv2_discovery_run ADD COLUMN strict_count integer")
    op.execute(
        """
        UPDATE arv2_discovery_run r SET strict_count = COALESCE(
            (SELECT s.asked FROM arv2_discovery_search s
              WHERE s.run_id = r.run_id AND s.ordinal = 1),
            r.target_count)
        """
    )
    op.execute("ALTER TABLE arv2_discovery_run ALTER COLUMN strict_count SET NOT NULL")
    op.execute(
        "ALTER TABLE arv2_discovery_run "
        "ADD CONSTRAINT arv2_discovery_run_strict_count_check CHECK (strict_count > 0)"
    )
    op.execute("ALTER TABLE arv2_discovery_run ADD COLUMN relaxed_search_id text")
    op.execute("ALTER TABLE arv2_discovery_run ADD COLUMN strict_search_id text")
    op.execute("ALTER TABLE arv2_discovery_run ADD COLUMN webset_id text")
    op.execute(
        """
        UPDATE arv2_discovery_run r SET webset_id = s.webset_id
        FROM arv2_discovery_search s WHERE s.run_id = r.run_id AND s.ordinal = 1
        """
    )
    op.execute("DROP TABLE arv2_discovery_search")
