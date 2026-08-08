"""FI-2 slice 1, Task 2 — the global-lens accounts list: ``GET /frontend/v1/accounts``.

The workspace-scoped, Band-2 read the frontend `/accounts` table binds to. It composes five
untouched mechanism surfaces and owns no research logic of its own:

1. **the account spine** — a workspace ``account_entity`` scan (merge losers excluded: a merged
   account is not a row, it is a redirect — Task 3 serves that);
2. **neutral facts** — ONE :func:`~clue_research.claimstore.current_values` batch over the
   list-row neutral field set, under ``WorkspaceScope.for_workspace``. These fields are
   ``project_neutral``, so they serve from the canonical merge in *every* lens and are
   deliberately **not** lineage-filtered (FI-2 slice-0 handoff: lineage filtering is
   species-conditional);
3. **membership** — :func:`~clue_research.membership.memberships_for_accounts`, whose element 0 is
   the recorded ``primaryProjectId`` policy;
4. **per-project attributed scores** — the live ``account.scoring.fit`` / ``.intent`` claims joined
   to their project through ``run_lineage``. These fields *are* ``project_relative``, so the join
   is the whole point: every project's score is served **attributed to that project**, and no
   representative run is guessed (FI-2 §7 dissolves FI-1 D-2 — ambiguity is shown, not hidden);
5. **research status** — the M8D ``entity_research_job`` aggregation (see
   :class:`AccountResearchStatusValue` for the mapping and why ``failed`` is absent).

Two disciplines are load-bearing here and are enforced, not merely intended:

* **Never scope a claim read by ``claim.workspace_id``.** That column is the M2.5 reuse-class
  tenant binding and a DB CHECK forces it ``NULL`` on every ``public_footprint`` claim, so
  ``WHERE claim.workspace_id = :ws`` does not narrow a read — it silently *empties* it. Both claim
  reads here scope through the **entity** (ids drawn from the workspace's own ``account_entity``
  page) plus ``WorkspaceScope.predicate()``, which encodes the reuse-class rule correctly, and the
  lineage join adds ``run_lineage.workspace_id`` — a real tenancy column on a real tenancy table.
* **Band-2 wire discipline.** Semantic values only: enums, numbers, ISO-8601 timestamps, opaque
  ids, and ``null`` wherever the backend genuinely knows nothing. No display strings, no labels, no
  formatting — the frontend owns presentation (FI-1 Band-1/Band-2 split).

The scan is **paginated by construction** (keyset over ``(created_at, id)`` descending, newest
account first) so a workspace list can never become an unbounded query. The cursor is opaque by
contract; its encoding is an implementation detail callers must not parse.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import WorkspaceDep
from clue_core import EntityId, decode_jsonb_scalar
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, current_values
from clue_research.membership import ProjectMembership, memberships_for_accounts

# --- policy constants -------------------------------------------------------------------------

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: The neutral (``project_neutral``) account fields the list row renders. Read in ONE batched
#: merge; every one of them is optional on the wire, because an empty field is a correct output.
LIST_NEUTRAL_FIELD_KEYS: tuple[str, ...] = ("core.employee_count", "core.revenue_band")

#: The ``project_relative`` scoring fields the row attributes per project. ``account.scoring.*`` is
#: relative by prefix, so these two are lineage-joined (unlike the neutral set above).
FIT_FIELD_KEY = "account.scoring.fit"
INTENT_FIELD_KEY = "account.scoring.intent"
SCORE_FIELD_KEYS: tuple[str, ...] = (FIT_FIELD_KEY, INTENT_FIELD_KEY)

_CURSOR_SEPARATOR = "|"


class InvalidCursorError(ValueError):
    """A ``?cursor=`` value this endpoint did not mint (or that has been tampered with)."""


# --- the wire vocabulary ----------------------------------------------------------------------


class AccountResearchStatusValue(StrEnum):
    """The honest per-``(account, project)`` research status (FI-1 §5.2).

    The mapping, from the M8D lifecycle in ``entity_research_job`` (+ the R6 account-fleet control
    rows), applied to the **latest** job for that pair — multiple concurrent runs per account are
    legal, so a per-account status needs a latest-run-wins rule and this is it:

    ==================================================  ==================
    backend condition                                   status
    ==================================================  ==================
    no ``entity_research_job`` for the (account, run)   ``not_started``
    fleet ``suspended`` **or** admission ``paused``     ``suspended``
    job state non-terminal                              ``in_progress``
    terminal + outcome ``needs_review``                 ``needs_review``
    terminal + outcome ``completed``                    ``completed``
    terminal + any other outcome                        ``suspended``
    ==================================================  ==================

    **Why there is no ``failed``.** The backend has no failure terminal to report. A worker crash
    does not fail the job — it *re-queues* it, pauses admission and drives the fleet to
    ``suspended`` (there is no attempt counter, no retry ceiling, and no persisted error text). So
    the honest rendering of "research stopped and it is not finished" is always "halted, awaiting a
    human", which is exactly ``suspended``; inventing a ``failed`` slot would put a state on the
    wire that no backend row can ever justify. The same reasoning routes the other non-success
    terminal outcomes (``cancelled`` / ``exhausted`` / ``budget_stopped`` / the unreachable
    ``failed``) to ``suspended``: each one means stopped-without-a-result, and a human decides what
    happens next. ``completed`` is reported for the ``completed`` outcome alone — the frontend's
    stronger "fully enriched" (empty ``unresolved_field_keys`` + a complete committee) is a claim
    this endpoint cannot yet substantiate, so it does not make it.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    SUSPENDED = "suspended"


class _WireModel(BaseModel):
    """Frozen, camelCase-on-the-wire, snake_case in Python — the frontend's JSON convention."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class AccountProjectMembership(_WireModel):
    """One project that targets this account, and how/when it joined."""

    project_id: str
    added_via: str
    added_at: datetime


class AccountProjectScore(_WireModel):
    """One project's Pass-A score for this account, under the ICP that produced it.

    ``fit`` and ``intent`` are independently nullable: a project may have scored fit and not intent
    (or vice versa), and reporting the missing half as ``0`` would be a fabrication.
    """

    project_id: str
    fit: float | None = None
    intent: float | None = None
    icp_key: str | None = None
    icp_version: int | None = None
    scored_at: datetime


class AccountResearchStatus(_WireModel):
    """The research status of this account *within* one project."""

    project_id: str
    status: AccountResearchStatusValue


class AccountListRow(_WireModel):
    """One row of the global accounts list."""

    id: uuid.UUID
    name: str
    domain: str | None = None
    employee_count: int | None = None
    revenue_band: str | None = None
    # No logo pipeline exists yet. Explicitly ``null`` rather than absent, so the frontend binds the
    # field now and the backend can start populating it without a schema change.
    logo_url: str | None = None
    projects: tuple[AccountProjectMembership, ...] = ()
    primary_project_id: str | None = None
    scores: tuple[AccountProjectScore, ...] = ()
    research_status: tuple[AccountResearchStatus, ...] = ()
    updated_at: datetime


class AccountListMeta(_WireModel):
    """Pagination metadata. ``total`` counts the whole filtered set, not the page."""

    total: int
    next_cursor: str | None = None


class AccountListResponse(_WireModel):
    """``{data, meta}`` — the envelope `apps/frontend/docs/api-contracts/accounts.md` documents."""

    data: tuple[AccountListRow, ...]
    meta: AccountListMeta


# --- the opaque cursor ------------------------------------------------------------------------


def encode_cursor(created_at: datetime, account_id: uuid.UUID) -> str:
    """Encode the keyset position. Opaque by contract — callers must not parse it."""
    raw = f"{created_at.isoformat()}{_CURSOR_SEPARATOR}{account_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a cursor this endpoint minted, or raise :class:`InvalidCursorError`.

    Fails loudly rather than falling back to "start from the beginning": a silently-ignored cursor
    would make a paging client re-serve page 1 forever and look like data loss.
    """
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        position, account_id = raw.split(_CURSOR_SEPARATOR, 1)
        created_at = datetime.fromisoformat(position)
        parsed_id = uuid.UUID(account_id)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidCursorError("cursor is not a value this endpoint issued") from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at, parsed_id


# --- SQL --------------------------------------------------------------------------------------

# Workspace-scoped, merge-losers excluded. ``merged_into IS NULL`` and ``status <> 'merged'`` are
# equivalent by the ``account_entity_merged_iff_target`` CHECK; the null test is the indexable one.
_ACCOUNT_FILTER = """
    a.workspace_id = :workspace_id
    AND a.merged_into IS NULL
    AND (
        CAST(:project_id AS text) IS NULL
        OR EXISTS (
            SELECT 1 FROM project_account pa
            WHERE pa.workspace_id = a.workspace_id
              AND pa.account_entity_id = a.id
              AND pa.project_id = :project_id
        )
    )
"""

_COUNT_ACCOUNTS = text(f"SELECT count(*) FROM account_entity a WHERE {_ACCOUNT_FILTER}")

# Keyset, newest first. The row-value comparison is the whole cursor predicate: it is total over
# ``(created_at, id)``, so two accounts created in the same transaction (identical ``created_at``)
# still page deterministically and neither is skipped nor repeated.
_PAGE_ACCOUNTS = text(
    f"""
    SELECT a.id, a.canonical_name, a.primary_domain, a.created_at, a.updated_at
    FROM account_entity a
    WHERE {_ACCOUNT_FILTER}
      AND (
          CAST(:cursor_created_at AS timestamptz) IS NULL
          OR (a.created_at, a.id) < (:cursor_created_at, CAST(:cursor_id AS uuid))
      )
    ORDER BY a.created_at DESC, a.id DESC
    LIMIT :row_limit
    """
)

# Per-project attributed scores. The claim predicate lives in a subquery so that
# ``WorkspaceScope.predicate()``'s unqualified ``reuse_scope``/``workspace_id`` columns can never
# be confused with ``run_lineage``'s own ``workspace_id`` — and so the scope filter provably
# applies to the claim, not to the join. Eligibility mirrors the merge's: live, field-flavoured,
# not rejected. Claims whose run has no lineage row, or a lineage row with no project, are dropped
# by the inner join — they are unattributable, and guessing a project for them is exactly the
# representative-run fiction FI-2 §7 removes.
_SCORE_CLAIMS_TEMPLATE = """
    SELECT c.entity_id, c.field_key, c.value_json, c.observed_at, c.collected_at, l.project_id
    FROM (
        SELECT id, entity_id, field_key, value_json, observed_at, collected_at, run_id
        FROM claim
        WHERE entity_id IN :entity_ids
          AND field_key IN :field_keys
          AND superseded_by IS NULL
          AND claim_flavor = 'field_claim'
          AND verification_status <> 'rejected'
          AND {scope_sql}
    ) c
    JOIN run_lineage l ON l.run_id = c.run_id
    WHERE l.workspace_id = :lineage_workspace_id AND l.project_id IS NOT NULL
    ORDER BY c.entity_id, l.project_id, c.collected_at, c.id
"""

# The latest job per (account, project) plus the two control rows that can hold it: the R6 account
# fleet (whose ``suspended`` state is the backend's real failure mode) and its per-job admission
# control (whose ``paused`` state is FI-1 §5.2's explicit carve-out from ``in_progress``). Only
# account-subject jobs are considered — a contact job is a different subject's research.
_RESEARCH_JOBS = text(
    """
    SELECT DISTINCT ON (j.subject_entity_id, j.project_id)
        j.subject_entity_id,
        j.project_id,
        j.state,
        j.finalization_outcome,
        jc.admission_state,
        f.state AS fleet_state
    FROM entity_research_job j
    LEFT JOIN entity_research_account_fleet_job_control jc ON jc.job_id = j.job_id
    LEFT JOIN entity_research_account_fleet f ON f.research_run_id = j.research_run_id
    WHERE j.workspace_id = :workspace_id
      AND j.subject_type = 'account'
      AND j.subject_entity_id IN :entity_ids
    ORDER BY j.subject_entity_id, j.project_id, j.created_at DESC, j.job_id DESC
    """
).bindparams(bindparam("entity_ids", expanding=True, type_=PgUUID(as_uuid=True)))


# --- composition helpers ----------------------------------------------------------------------


def research_status_for(
    *,
    job_state: str,
    finalization_outcome: str | None,
    admission_state: str | None,
    fleet_state: str | None,
) -> AccountResearchStatusValue:
    """The FI-1 §5.2 mapping, as a pure function (see :class:`AccountResearchStatusValue`)."""
    if fleet_state == "suspended" or admission_state == "paused":
        return AccountResearchStatusValue.SUSPENDED
    if job_state != "terminal":
        return AccountResearchStatusValue.IN_PROGRESS
    if finalization_outcome == "needs_review":
        return AccountResearchStatusValue.NEEDS_REVIEW
    if finalization_outcome == "completed":
        return AccountResearchStatusValue.COMPLETED
    return AccountResearchStatusValue.SUSPENDED


def _as_int(value: Any) -> int | None:
    """A JSON number that is genuinely an integer — ``bool`` is not one, whatever Python says."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


async def _read_scores(
    conn: AsyncConnection, *, workspace_id: str, entity_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[AccountProjectScore, ...]]:
    """Per-account, per-project, per-ICP scores — the lineage-attributed relative read.

    Grouped by ``(project, icp_key, icp_version)``, not merely by project: an account may be scored
    under several ICPs within one project (D5), and collapsing those to one row would have to pick
    a winner — another representative-run guess. Within a group the latest claim of each field
    wins, and ``scored_at`` is the newer of the two.
    """
    if not entity_ids:
        return {}
    scope = WorkspaceScope.for_workspace(workspace_id)
    scope_sql, scope_params = scope.predicate()
    stmt = text(_SCORE_CLAIMS_TEMPLATE.format(scope_sql=scope_sql)).bindparams(
        bindparam("entity_ids", expanding=True, type_=PgUUID(as_uuid=True)),
        bindparam("field_keys", expanding=True),
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_ids": list(entity_ids),
                "field_keys": list(SCORE_FIELD_KEYS),
                "lineage_workspace_id": workspace_id,
                **scope_params,
            },
        )
    ).all()

    # (entity, project, icp_key, icp_version) -> mutable accumulator
    grouped: dict[tuple[uuid.UUID, str, str | None, int | None], dict[str, Any]] = {}
    for entity_id, field_key, raw_value, observed_at, collected_at, project_id in rows:
        value = decode_jsonb_scalar(raw_value)
        payload = value if isinstance(value, dict) else {}
        key = (
            uuid.UUID(str(entity_id)),
            str(project_id),
            _as_str(payload.get("icp_key")),
            _as_int(payload.get("icp_version")),
        )
        # The claim's own age, on the same rule the merge uses: the observation time when the
        # source stated one, else when we collected it.
        scored_at = observed_at or collected_at
        accumulator = grouped.setdefault(key, {"fit": None, "intent": None, "scored_at": scored_at})
        # Rows arrive oldest-first per (entity, project), so a later claim overwrites an earlier
        # one of the same field — last write wins is newest wins.
        accumulator["fit" if field_key == FIT_FIELD_KEY else "intent"] = _as_float(
            payload.get("value")
        )
        if scored_at > accumulator["scored_at"]:
            accumulator["scored_at"] = scored_at

    by_account: dict[uuid.UUID, list[AccountProjectScore]] = defaultdict(list)
    for (entity_id, project_id, icp_key, icp_version), accumulator in grouped.items():
        by_account[entity_id].append(
            AccountProjectScore(
                project_id=project_id,
                fit=accumulator["fit"],
                intent=accumulator["intent"],
                icp_key=icp_key,
                icp_version=icp_version,
                scored_at=accumulator["scored_at"],
            )
        )
    return {
        entity_id: tuple(
            sorted(scores, key=lambda s: (s.project_id, s.icp_key or "", s.icp_version or 0))
        )
        for entity_id, scores in by_account.items()
    }


async def _read_research_status(
    conn: AsyncConnection, *, workspace_id: str, entity_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, AccountResearchStatusValue]]:
    """``{account: {project: status}}`` for every (account, project) that has *any* research job."""
    if not entity_ids:
        return {}
    rows = (
        await conn.execute(
            _RESEARCH_JOBS, {"workspace_id": workspace_id, "entity_ids": list(entity_ids)}
        )
    ).all()
    statuses: dict[uuid.UUID, dict[str, AccountResearchStatusValue]] = defaultdict(dict)
    for entity_id, project_id, state, outcome, admission_state, fleet_state in rows:
        statuses[uuid.UUID(str(entity_id))][str(project_id)] = research_status_for(
            job_state=str(state),
            finalization_outcome=None if outcome is None else str(outcome),
            admission_state=None if admission_state is None else str(admission_state),
            fleet_state=None if fleet_state is None else str(fleet_state),
        )
    return statuses


def _research_status_rows(
    memberships: tuple[ProjectMembership, ...],
    statuses: dict[str, AccountResearchStatusValue],
) -> tuple[AccountResearchStatus, ...]:
    """One entry per membership project (``not_started`` when it has no job), **plus** any project
    that researched this account without a membership row.

    That second class should not exist — research is launched for a project that targets the
    account — so when it does, it is reported rather than hidden: a silently dropped status is
    indistinguishable from no research at all.
    """
    ordered = [membership.project_id for membership in memberships]
    members = set(ordered)
    ordered += sorted(project_id for project_id in statuses if project_id not in members)
    return tuple(
        AccountResearchStatus(
            project_id=project_id,
            status=statuses.get(project_id, AccountResearchStatusValue.NOT_STARTED),
        )
        for project_id in ordered
    )


# --- the read model ---------------------------------------------------------------------------


async def list_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> AccountListResponse:
    """One page of the workspace's accounts, fully composed.

    ``project_id`` is a **filter over membership**, not a lens: an unknown or foreign project
    simply matches nothing and returns an empty page, because "no accounts in that project" is a
    true answer and a 404 would claim the project does not exist — which this endpoint has no
    authority to say.

    Raises :class:`InvalidCursorError` for a cursor this endpoint did not mint.
    """
    cursor_created_at, cursor_id = (None, None) if cursor is None else decode_cursor(cursor)
    filter_params: dict[str, Any] = {"workspace_id": workspace_id, "project_id": project_id}

    total = int((await conn.execute(_COUNT_ACCOUNTS, filter_params)).scalar_one())
    # One extra row is the has-more probe; it is never served.
    rows = (
        await conn.execute(
            _PAGE_ACCOUNTS,
            {
                **filter_params,
                "cursor_created_at": cursor_created_at,
                "cursor_id": None if cursor_id is None else str(cursor_id),
                "row_limit": limit + 1,
            },
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    if not page:
        return AccountListResponse(data=(), meta=AccountListMeta(total=total, next_cursor=None))

    account_ids = [uuid.UUID(str(row[0])) for row in page]
    neutral = await current_values(
        conn,
        [EntityId(account_id) for account_id in account_ids],
        LIST_NEUTRAL_FIELD_KEYS,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    memberships = await memberships_for_accounts(
        conn, workspace_id=workspace_id, account_ids=account_ids
    )
    scores = await _read_scores(conn, workspace_id=workspace_id, entity_ids=account_ids)
    statuses = await _read_research_status(conn, workspace_id=workspace_id, entity_ids=account_ids)

    data: list[AccountListRow] = []
    for account_id, (_id, canonical_name, primary_domain, _created_at, updated_at) in zip(
        account_ids, page, strict=True
    ):
        entity_id = EntityId(account_id)
        employee_count = neutral.get((entity_id, "core.employee_count"))
        revenue_band = neutral.get((entity_id, "core.revenue_band"))
        account_memberships = memberships.get(account_id, ())
        data.append(
            AccountListRow(
                id=account_id,
                name=str(canonical_name),
                domain=primary_domain,
                employee_count=(
                    None if employee_count is None else _as_int(employee_count.value_json)
                ),
                revenue_band=None if revenue_band is None else _as_str(revenue_band.value_json),
                projects=tuple(
                    AccountProjectMembership(
                        project_id=membership.project_id,
                        added_via=membership.added_via,
                        added_at=membership.added_at,
                    )
                    for membership in account_memberships
                ),
                # The recorded FI-2 §2 policy: earliest membership. A membership-less account has
                # no primary project, and that is a legitimate row — seeds, the client entity and
                # legacy imports all render this way.
                primary_project_id=(
                    account_memberships[0].project_id if account_memberships else None
                ),
                scores=scores.get(account_id, ()),
                research_status=_research_status_rows(
                    account_memberships, statuses.get(account_id, {})
                ),
                updated_at=updated_at,
            )
        )

    last_id, _name, _domain, last_created_at, _updated = page[-1]
    next_cursor = encode_cursor(last_created_at, uuid.UUID(str(last_id))) if has_more else None
    return AccountListResponse(
        data=tuple(data), meta=AccountListMeta(total=total, next_cursor=next_cursor)
    )


# --- the route --------------------------------------------------------------------------------


def register_accounts_list_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    """Register ``GET /accounts`` on the workspace-scoped `/frontend/v1` router."""

    @router.get("/accounts")
    async def get_accounts(
        workspace_id: WorkspaceDep,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: Annotated[str | None, Query()] = None,
    ) -> AccountListResponse:
        async with conn_factory() as conn:
            try:
                return await list_accounts(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    limit=limit,
                    cursor=cursor,
                )
            except InvalidCursorError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_CURSOR", "message": str(exc)},
                ) from exc
