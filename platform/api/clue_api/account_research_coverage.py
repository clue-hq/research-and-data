"""Reference-only reads over M8D account-research output (R11 §6c / R11.5).

Two questions live here, and they are deliberately *not* in :mod:`clue_api.account_research_fleet`
even though that module owns the tables:

1. which account-research run currently describes a project run, and
2. what that run recorded for one account.

The R6 controller is a heavyweight module — it holds the supervisor, the queue offers, the work
handler, and (for typing) an edge to the prose-synthesis step.  A read-side consumer that only wants
references should not pull any of that in, and one of those consumers is the governed committee
read, which sits inside the turn-serving import graph that must be provably unable to reach a model
(``tests/api/test_lane_d2_http_gateway_isolation.py`` walks it statically, TYPE_CHECKING edges
included).  Keeping these two reads in their own dependency-light module is what lets the committee
bridge reuse them instead of re-deriving the ordering rule.

Nothing here returns a value: coverage carries references, and a reader joins them back to the claim
store under its own governance.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "AccountResearchCoverageLookup",
    "AccountResearchCoverageRefs",
    "latest_account_research_run_id",
    "read_account_coverage_in_run",
]


async def latest_account_research_run_id(
    conn: AsyncConnection,
    project_run_id: UUID,
    *,
    workspace_id: str,
) -> UUID | None:
    """The **current** account-research run bound to ``project_run_id``, or ``None``.

    R11 §6c (ratified): the current run is the latest launch — every fleet row is human-confirmed by
    construction, because the R6 service's ``launch`` requires a durable ``source_action_ref``.
    Earlier runs stay visible history and never drive the DEEP phase, the verification selection, or
    the committee read.

    This is the single definition of that ordering rule; every consumer resolves the run through it
    rather than restating the ``ORDER BY``.  Read-only and workspace-scoped: a run belonging to
    another workspace reads as absent.
    """

    research_run_id = (
        await conn.execute(
            text(
                "SELECT research_run_id FROM entity_research_account_fleet "
                "WHERE project_run_id=:project_run_id AND workspace_id=:workspace_id "
                "ORDER BY created_at DESC, research_run_id DESC LIMIT 1"
            ),
            {"project_run_id": project_run_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    return None if research_run_id is None else UUID(str(research_run_id))


class AccountResearchCoverageRefs(BaseModel):
    """One account's M8D research output, as references only.

    The R5 finalization compiler writes one of these rows per finalized account job
    (:mod:`clue_api.account_entity_research`).  ``claim_refs`` (``claim:<uuid>`` strings) is the
    M8D-native equivalent of the legacy ``account_run.references_index``, and
    ``committee_member_ids`` is the committee that job actually resolved.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_id: UUID
    job_id: UUID
    account_entity_id: UUID
    claim_refs: tuple[str, ...]
    committee_member_ids: tuple[UUID, ...]
    committee_status: Literal["complete", "partial", "needs_review"]


class AccountResearchCoverageLookup(BaseModel):
    """What one research run has to say about one account, in a single read.

    ``run_has_coverage`` and ``coverage`` answer two different questions a reader must not conflate:
    *has this run published any research output at all* versus *what did it record for this
    particular account*.  A run with no output anywhere has not yet spoken about a single account; a
    run with output but no row for this account did not research it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_has_coverage: bool
    coverage: AccountResearchCoverageRefs | None


async def read_account_coverage_in_run(
    conn: AsyncConnection,
    research_run_id: UUID,
    *,
    account_entity_id: UUID,
    workspace_id: str,
) -> AccountResearchCoverageLookup:
    """One account's current coverage under a research run, plus whether that run has any at all.

    Both facts come from one statement deliberately: this read sits on the per-account committee
    path (R11.5), where a second round trip is a per-account cost on a surface whose composition is
    query-budgeted.

    ``entity_research_account_coverage`` carries no uniqueness beyond its ``coverage_id`` primary
    key, so a run may legitimately hold several rows for one account (one per job, and a job that
    re-finalizes appends rather than updates).  The row returned is therefore latest-wins on
    ``(created_at, coverage_id)`` — the same ordering the R6 projection already uses for its per-job
    lateral, so the projection and this reader can never disagree about which row is current.

    Workspace-scoped: another tenant's coverage reads as absent.
    """

    row = (
        (
            await conn.execute(
                text(
                    """
                    WITH mine AS (
                        SELECT coverage_id, job_id, account_entity_id, claim_refs,
                               committee_member_ids, committee_status
                        FROM entity_research_account_coverage
                        WHERE research_run_id=:run_id AND workspace_id=:workspace_id
                          AND account_entity_id=:account_id
                        ORDER BY created_at DESC, coverage_id DESC LIMIT 1
                    )
                    SELECT
                        EXISTS (
                            SELECT 1 FROM entity_research_account_coverage
                            WHERE research_run_id=:run_id AND workspace_id=:workspace_id
                        ) AS run_has_coverage,
                        mine.coverage_id, mine.job_id, mine.account_entity_id, mine.claim_refs,
                        mine.committee_member_ids, mine.committee_status
                    FROM (SELECT 1) AS present LEFT JOIN mine ON TRUE
                    """
                ),
                {
                    "run_id": research_run_id,
                    "account_id": account_entity_id,
                    "workspace_id": workspace_id,
                },
            )
        )
        .mappings()
        .one()
    )
    coverage = (
        None
        if row["coverage_id"] is None
        else AccountResearchCoverageRefs(
            coverage_id=row["coverage_id"],
            job_id=row["job_id"],
            account_entity_id=row["account_entity_id"],
            claim_refs=tuple(str(value) for value in row["claim_refs"]),
            committee_member_ids=tuple(row["committee_member_ids"]),
            committee_status=row["committee_status"],
        )
    )
    return AccountResearchCoverageLookup(
        run_has_coverage=bool(row["run_has_coverage"]), coverage=coverage
    )
