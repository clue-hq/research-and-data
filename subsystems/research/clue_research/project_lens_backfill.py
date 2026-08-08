"""The one-shot repair for the FI-2 project lens (spec §2/§3 backfill paragraphs).

FI-2 slice 0 taught every *live* account-entry and run-minting site to record its
``project_account`` membership (§2) and its ``run_lineage`` attribution (§3). Rows already at rest
predate those writers, so on an existing database a project's account list is empty and its claim
lens resolves no runs — the frontend's ``/accounts`` table would render a workspace's accounts with
no project chips, and a project-scoped claim read would return nothing. This module reconstructs
both spines from the durable execution records that *do* exist.

Five sources, all reconstructions of what the live writer would have written:

===========================  ===========================================================
``discovery_membership``     ``discovery_candidate_link`` (admitted/merged) → the batch's
                             project ⇒ ``added_via='discovered'``
``directive_membership``     ``account_research_directive_account`` → the directive's
                             project ⇒ ``added_via='directive'``
``discovery_lineage``        each ``project_run``'s pinned ``(icp_key, icp_version)`` ⇒ the
                             DISCOVERY phase's own deterministic run id, ``kind='discovery'``
``entity_research_lineage``  ``entity_research_run`` ⇒ ``kind='entity_research'`` (account
                             subjects) / ``'contact_research'`` (contact subjects)
``account_run_lineage``      ``account_run`` (``id`` *is* the claim's ``run_id``) ⇒
                             ``kind='entity_research'``
===========================  ===========================================================

Properties this repair holds to, because a script anyone may re-run is only safe if it does:

* **Idempotent.** Both writers are ``ON CONFLICT DO NOTHING``, and the plan skips rows already
  present, so a second pass writes nothing and reports zero. Rows a live writer already wrote are
  never rewritten — *first add wins* survives the backfill.
* **One plan, two outcomes.** ``dry_run`` builds the *same* plan and simply does not write it, so
  the preview cannot under-report (the discipline
  ``identity.backfill_account_embeddings`` established).
* **Merge-aware.** A candidate link may still name an account that has since been merged away;
  membership follows the survivor (``identity.surviving_ids``, the real chain walker — never a
  re-implementation), exactly as the live admission path does.
* **Chronological.** Membership candidates from all sources are applied oldest-event-first, so the
  channel and ``added_at`` that land are the ones history would have produced — which is what makes
  ``projects_for_accounts``' element-0 ``primaryProjectId`` policy meaningful.
* **Never fatal on bad data.** ``entity_research_run`` and ``account_run`` carry no foreign key to
  ``project_run``, so either may name a run that no longer exists. Such a row is skipped and
  counted (``skipped_orphan``), never raised — ``run_lineage.project_run_id`` *does* have that FK,
  so writing it would abort the whole transaction.

Dev-data-only by intent (the B3 synthetic-data ruling): this is a one-shot developer convenience
for databases that predate slice 0, not production machinery, and it adds no migration. The CLI is
``scripts/backfill_fi2_slice0.py``.

Import direction: this module sits above the substrates it repairs — it imports
``membership``/``claimstore``/``identity`` and ``discovery_scoring``'s run-id formula, and nothing
imports it back (the CLI is a script, and no package re-exports it), so it introduces no cycle and
no new coupling between the milestone packages.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, EntityType, ProjectRunId
from clue_research.claimstore import record_run_lineage
from clue_research.discovery_scoring import project_discovery_run_id
from clue_research.identity import surviving_ids
from clue_research.membership import ensure_project_account

# Report keys, in the order the pass applies them. Membership sources come first because a
# membership write is the thing whose *channel* depends on ordering; lineage is keyed on the run id
# alone and so is order-independent.
BACKFILL_SOURCES = (
    "discovery_membership",
    "directive_membership",
    "discovery_lineage",
    "entity_research_lineage",
    "account_run_lineage",
)

# Mirrors the two M8D fleet launch sites: ``account_research_fleet_launch`` registers its
# ``research_run_id`` as ``entity_research``, ``contact_research_fleet_launch`` as
# ``contact_research``. The ``entity_research_run_kind_subject`` CHECK ties ``run_kind`` to
# ``subject_type`` one-to-one, so keying off the subject is the same statement either way.
_RESEARCH_KIND_BY_SUBJECT = {"account": "entity_research", "contact": "contact_research"}


class SourceCounts(BaseModel):
    """What one backfill source contributed.

    ``scanned`` is the distinct candidate rows it produced (after survivor redirection and
    within-source de-duplication), ``written`` the subset that was not already present — so a
    converged store reports ``written=0`` with ``scanned`` unchanged, and that difference is the
    signal that the repair has already run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scanned: int = 0
    written: int = 0
    skipped_orphan: int = 0


class ProjectLensBackfillReport(BaseModel):
    """What one :func:`backfill_project_lens` pass did, per source and per workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_source: Mapping[str, SourceCounts]
    by_workspace: Mapping[str, int]
    scanned: int
    written: int
    skipped_orphan: int

    @classmethod
    def from_sources(
        cls,
        by_source: Mapping[str, SourceCounts],
        by_workspace: Mapping[str, int] | None = None,
    ) -> ProjectLensBackfillReport:
        """Build the report, filling every unreported source with an explicit zero.

        Every source always appears, so an operator reading the JSON can tell "this source found
        nothing" from "this source did not run" — the two look identical if absent keys are allowed.
        """
        counts = {name: by_source.get(name, SourceCounts()) for name in BACKFILL_SOURCES}
        return cls(
            by_source=counts,
            by_workspace=dict(by_workspace or {}),
            scanned=sum(count.scanned for count in counts.values()),
            written=sum(count.written for count in counts.values()),
            skipped_orphan=sum(count.skipped_orphan for count in counts.values()),
        )


@dataclass(frozen=True, slots=True)
class _Membership:
    workspace_id: str
    project_id: str
    account_entity_id: uuid.UUID
    added_via: str
    added_at: datetime
    source: str

    @property
    def key(self) -> tuple[str, str, uuid.UUID]:
        return (self.workspace_id, self.project_id, self.account_entity_id)


@dataclass(frozen=True, slots=True)
class _Lineage:
    run_id: uuid.UUID
    workspace_id: str
    project_id: str
    project_run_id: uuid.UUID
    kind: str
    created_at: datetime
    source: str


# A candidate link's own ``updated_at`` is the only per-link timestamp the table has (there is no
# ``created_at``) and it *mutates* — a later merge rewrites the link — so the batch's immutable
# ``started_at`` is the stable lower bound for "when this project discovered this account".
#
# The batch carries ``project_id`` directly, and its ``discovery_batch_run_fk`` is the composite
# ``(project_run_id, workspace_id, project_id) → project_run``, so that column *is* the project
# run's project: the extra hop through ``project_run`` is a join that cannot change the answer.
_DISCOVERY_MEMBERSHIP = text(
    """
    SELECT b.workspace_id,
           b.project_id,
           COALESCE(link.survivor_entity_id, link.account_entity_id) AS account_entity_id,
           b.started_at AS added_at
    FROM discovery_candidate_link link
    JOIN discovery_batch b ON b.id = link.batch_id AND b.workspace_id = link.workspace_id
    WHERE link.admission_status IN ('admitted', 'merged')
      AND COALESCE(link.survivor_entity_id, link.account_entity_id) IS NOT NULL
      AND (CAST(:ws AS text) IS NULL OR b.workspace_id = :ws)
    """
)

_DIRECTIVE_MEMBERSHIP = text(
    """
    SELECT scope.workspace_id,
           directive.project_id,
           scope.account_id AS account_entity_id,
           scope.created_at AS added_at
    FROM account_research_directive_account scope
    JOIN account_research_directive directive
      ON directive.directive_id = scope.directive_id
     AND directive.workspace_id = scope.workspace_id
    WHERE (CAST(:ws AS text) IS NULL OR scope.workspace_id = :ws)
    """
)

# One discovery run per project run: the phase pins exactly one ``(icp_key, icp_version)`` on the
# ``project_run`` row, and ``project_discovery_run_id`` is a pure function of that triple.
_DISCOVERY_LINEAGE = text(
    """
    SELECT id AS project_run_id, workspace_id, project_id, icp_key, icp_version, created_at
    FROM project_run
    WHERE (CAST(:ws AS text) IS NULL OR workspace_id = :ws)
    """
)

# ``entity_research_run`` has no FK to ``project_run``; the LEFT JOIN is what turns a dangling
# reference into a counted skip instead of an IntegrityError on the lineage insert. The project is
# read from ``project_run`` — the FK-backed truth — not from the run's own denormalized copy.
_ENTITY_RESEARCH_LINEAGE = text(
    """
    SELECT run.research_run_id AS run_id,
           run.workspace_id,
           project_run.project_id,
           run.project_run_id,
           run.subject_type,
           run.created_at
    FROM entity_research_run run
    LEFT JOIN project_run
      ON project_run.id = run.project_run_id AND project_run.workspace_id = run.workspace_id
    WHERE (CAST(:ws AS text) IS NULL OR run.workspace_id = :ws)
    """
)

# ``account_run`` carries no ``workspace_id`` at all (M7.1 predates workspace localization), so its
# workspace is *derived* through the project run — which is also why a workspace-scoped pass cannot
# see an orphaned account run: an orphan belongs to no workspace, so no tenant's repair owns it.
_ACCOUNT_RUN_LINEAGE = text(
    """
    SELECT account_run.id AS run_id,
           project_run.workspace_id,
           project_run.project_id,
           account_run.project_run_id,
           account_run.started_at AS created_at
    FROM account_run
    LEFT JOIN project_run ON project_run.id = account_run.project_run_id
    WHERE (CAST(:ws AS text) IS NULL OR project_run.workspace_id = :ws)
    """
)

_EXISTING_MEMBERSHIP = text(
    """
    SELECT workspace_id, project_id, account_entity_id FROM project_account
    WHERE (CAST(:ws AS text) IS NULL OR workspace_id = :ws)
    """
)

_EXISTING_LINEAGE = text(
    "SELECT run_id FROM run_lineage WHERE (CAST(:ws AS text) IS NULL OR workspace_id = :ws)"
)


async def backfill_project_lens(
    conn: AsyncConnection,
    *,
    workspace_id: str | None = None,
    dry_run: bool = False,
) -> ProjectLensBackfillReport:
    """Reconstruct ``project_account`` + ``run_lineage`` from the durable execution records.

    Runs inside the caller's transaction — the CLI supplies one, so the whole repair commits or
    rolls back as a unit. Scope it to a single ``workspace_id`` or leave it ``None`` to repair every
    workspace; the report is broken down per workspace either way.

    ``dry_run`` builds the identical plan and writes nothing, so the preview reports exactly what a
    real pass would write.
    """
    counts: dict[str, SourceCounts] = {}
    by_workspace: dict[str, int] = defaultdict(int)

    memberships = await _plan_memberships(conn, workspace_id=workspace_id, counts=counts)
    lineages = await _plan_lineage(conn, workspace_id=workspace_id, counts=counts)

    for membership in memberships:
        by_workspace[membership.workspace_id] += 1
        if not dry_run:
            await ensure_project_account(
                conn,
                workspace_id=membership.workspace_id,
                project_id=membership.project_id,
                account_entity_id=membership.account_entity_id,
                added_via=membership.added_via,
                added_at=membership.added_at,
            )
    for lineage in lineages:
        by_workspace[lineage.workspace_id] += 1
        if not dry_run:
            await record_run_lineage(
                conn,
                run_id=lineage.run_id,
                workspace_id=lineage.workspace_id,
                kind=lineage.kind,
                project_id=lineage.project_id,
                project_run_id=lineage.project_run_id,
            )
    return ProjectLensBackfillReport.from_sources(counts, dict(by_workspace))


async def _plan_memberships(
    conn: AsyncConnection, *, workspace_id: str | None, counts: dict[str, SourceCounts]
) -> list[_Membership]:
    """The membership rows to write: oldest event first, one per (workspace, project, account)."""
    candidates: list[_Membership] = []
    for source, stmt, added_via in (
        ("discovery_membership", _DISCOVERY_MEMBERSHIP, "discovered"),
        ("directive_membership", _DIRECTIVE_MEMBERSHIP, "directive"),
    ):
        rows = (await conn.execute(stmt, {"ws": workspace_id})).mappings().all()
        candidates.extend(
            _Membership(
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                account_entity_id=row["account_entity_id"],
                added_via=added_via,
                added_at=row["added_at"],
                source=source,
            )
            for row in rows
        )

    candidates = await _redirect_to_survivors(conn, candidates)
    existing = {
        (row[0], row[1], row[2])
        for row in (await conn.execute(_EXISTING_MEMBERSHIP, {"ws": workspace_id})).all()
    }

    scanned: dict[str, set[tuple[str, str, uuid.UUID]]] = defaultdict(set)
    written: dict[str, int] = defaultdict(int)
    planned: list[_Membership] = []
    claimed = set(existing)
    # Oldest event first, so the channel and ``added_at`` that land are the ones history would have
    # produced. ``source`` and the account id break ties deterministically (two events on the same
    # timestamp must not depend on the database's row order).
    for candidate in sorted(candidates, key=lambda m: (m.added_at, m.source, m.key)):
        scanned[candidate.source].add(candidate.key)
        if candidate.key in claimed:
            continue
        claimed.add(candidate.key)
        written[candidate.source] += 1
        planned.append(candidate)

    for source in ("discovery_membership", "directive_membership"):
        counts[source] = SourceCounts(scanned=len(scanned[source]), written=written[source])
    return planned


async def _redirect_to_survivors(
    conn: AsyncConnection, candidates: Sequence[_Membership]
) -> list[_Membership]:
    """Point every candidate at its live merge survivor (workspace-scoped, batched per workspace).

    A source row may name an account merged away after it was written; membership belongs on the
    survivor — the same redirect ``identity.mark_merged``/``repoint_project_accounts`` apply to rows
    that were already written. Uses the real chain walker, never a local re-implementation.
    """
    by_workspace: dict[str, set[EntityId]] = defaultdict(set)
    for candidate in candidates:
        by_workspace[candidate.workspace_id].add(EntityId(candidate.account_entity_id))
    survivors: dict[str, dict[EntityId, EntityId]] = {}
    for workspace, ids in by_workspace.items():
        survivors[workspace] = await surviving_ids(
            conn, sorted(ids), EntityType.ACCOUNT, workspace_id=workspace
        )
    return [
        _Membership(
            workspace_id=candidate.workspace_id,
            project_id=candidate.project_id,
            account_entity_id=survivors[candidate.workspace_id].get(
                EntityId(candidate.account_entity_id), EntityId(candidate.account_entity_id)
            ),
            added_via=candidate.added_via,
            added_at=candidate.added_at,
            source=candidate.source,
        )
        for candidate in candidates
    ]


async def _plan_lineage(
    conn: AsyncConnection, *, workspace_id: str | None, counts: dict[str, SourceCounts]
) -> list[_Lineage]:
    """The lineage rows to write, one per run id, oldest run first."""
    candidates: list[_Lineage] = []
    orphans: dict[str, int] = defaultdict(int)

    for row in (await conn.execute(_DISCOVERY_LINEAGE, {"ws": workspace_id})).mappings().all():
        run_id = project_discovery_run_id(
            project_run_id=ProjectRunId(row["project_run_id"]),
            icp_key=row["icp_key"],
            icp_version=row["icp_version"],
        )
        candidates.append(
            _Lineage(
                run_id=uuid.UUID(str(run_id)),
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                project_run_id=row["project_run_id"],
                kind="discovery",
                created_at=row["created_at"],
                source="discovery_lineage",
            )
        )

    for row in (
        (await conn.execute(_ENTITY_RESEARCH_LINEAGE, {"ws": workspace_id})).mappings().all()
    ):
        if row["project_id"] is None:
            orphans["entity_research_lineage"] += 1
            continue
        candidates.append(
            _Lineage(
                run_id=row["run_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                project_run_id=row["project_run_id"],
                kind=_RESEARCH_KIND_BY_SUBJECT[row["subject_type"]],
                created_at=row["created_at"],
                source="entity_research_lineage",
            )
        )

    for row in (await conn.execute(_ACCOUNT_RUN_LINEAGE, {"ws": workspace_id})).mappings().all():
        if row["project_id"] is None:
            orphans["account_run_lineage"] += 1
            continue
        candidates.append(
            _Lineage(
                run_id=row["run_id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                project_run_id=row["project_run_id"],
                kind="entity_research",
                created_at=row["created_at"],
                source="account_run_lineage",
            )
        )

    existing = {
        row[0] for row in (await conn.execute(_EXISTING_LINEAGE, {"ws": workspace_id})).all()
    }
    scanned: dict[str, set[uuid.UUID]] = defaultdict(set)
    written: dict[str, int] = defaultdict(int)
    planned: list[_Lineage] = []
    claimed = set(existing)
    # ``run_lineage`` is keyed on the run id alone, so two sources naming the same run (the Sumble
    # committee path deliberately reuses the project run id) must resolve deterministically: oldest
    # first, then source, then run id.
    for candidate in sorted(candidates, key=lambda r: (r.created_at, r.source, r.run_id)):
        scanned[candidate.source].add(candidate.run_id)
        if candidate.run_id in claimed:
            continue
        claimed.add(candidate.run_id)
        written[candidate.source] += 1
        planned.append(candidate)

    for source in ("discovery_lineage", "entity_research_lineage", "account_run_lineage"):
        counts[source] = SourceCounts(
            scanned=len(scanned[source]),
            written=written[source],
            skipped_orphan=orphans[source],
        )
    return planned
