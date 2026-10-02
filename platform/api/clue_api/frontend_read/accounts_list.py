"""The workspace accounts table: ``GET /frontend/v1/accounts`` (contract v1, ARV2 E1).

The workspace-scoped read the frontend `/accounts` table binds to. It composes untouched mechanism
surfaces and owns no research logic of its own:

1. **the account spine** — a workspace ``account_entity`` scan (the workspace's own client binding
   and merge losers are excluded: neither is a target-account row);
2. **neutral facts** — ONE :func:`~clue_research.claimstore.current_values` batch over the row's
   neutral field set, under ``WorkspaceScope.for_workspace``. These fields are ``project_neutral``,
   so they serve from the canonical merge in *every* lens and are deliberately **not**
   lineage-filtered;
3. **membership** — :func:`~clue_research.membership.memberships_for_accounts`, whose element 0 is
   the recorded ``primaryProjectId`` policy, with each project's display name resolved by ONE
   batched :func:`project_names` read over the whole page (a per-membership lookup would be an N+1
   over a 200-row page);
4. **the account's fit** — the live ``account.scoring.fit`` claims joined to their projects
   through ``run_lineage``, the newest of which the row shows whichever project produced it
   (founder ruling 2026-09-11: a fit is global to the account; see :func:`account_fit`). The join
   still matters: a score arrives attributed to the project that produced it, and no
   representative run is guessed — the detail's project sections keep that attribution;
5. **research status** — the account's own latest ARV2 job
   (:func:`~clue_api.frontend_read.v1_shared.arv2_research_status_for`).

Two disciplines are load-bearing here and are enforced, not merely intended:

* **Never scope a claim read by ``claim.workspace_id``.** That column is the M2.5 reuse-class
  tenant binding and a DB CHECK forces it ``NULL`` on every ``public_footprint`` claim, so
  ``WHERE claim.workspace_id = :ws`` does not narrow a read — it silently *empties* it. Both claim
  reads here scope through the **entity** (ids drawn from the workspace's own ``account_entity``
  page) plus ``WorkspaceScope.predicate()``, which encodes the reuse-class rule correctly, and the
  lineage join adds ``run_lineage.workspace_id`` — a real tenancy column on a real tenancy table.
* **A fixed number of batched statements per response.** Every source above is read once over the
  whole page; a per-row lookup is what the suite's statement-count guard exists to prevent.

The scan is **paginated by construction** over ``(created_at, id)`` descending, newest account
first, so a workspace list can never become an unbounded query. Internal consumers retain opaque
keyset cursors; the browser uses a mutually-exclusive numbered-page mode over the same total order
so it can navigate backwards and jump to a page without pretending it selected unseen rows.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contract_v1 import (
    AccountOwner,
    AccountProject,
    AccountsMeta,
    AccountsResponseV1,
    AccountV1,
)
from clue_api.frontend_read.v1_shared import (
    RESEARCH_STATUS_LABELS,
    account_logo_path,
    arv2_research_status_for,
    custom_fields_for,
    employee_band,
    fit_band,
    fit_score_100,
    industry_labels,
    iso_utc,
    last_modified_for,
    location_label,
    owners_for,
    revenue_band_label,
    socials,
    website_url,
)
from clue_config import Settings
from clue_core import EntityId, decode_jsonb_scalar
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, current_values
from clue_research.membership import memberships_for_accounts

# --- policy constants -------------------------------------------------------------------------

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: The neutral (``project_neutral``) account fields the row renders (ARV2 D3 decision 3), read in
#: ONE batched merge: the account's own chrome — bands, location, industries, socials. Every one of
#: them is optional on the wire, because an empty field is a correct output.
V1_NEUTRAL_FIELD_KEYS: tuple[str, ...] = (
    "core.employee_count",
    "core.employee_range",
    "core.revenue_band",
    "core.hq_location",
    "core.industry",
    "core.industries_all",
    "core.company_linkedin_url",
    "core.company_twitter_url",
    "core.logo_url",
)

#: The ``project_relative`` scoring fields the row attributes per project. ``account.scoring.*`` is
#: relative by prefix, so these two are lineage-joined (unlike the neutral set above).
FIT_FIELD_KEY = "account.scoring.fit"
INTENT_FIELD_KEY = "account.scoring.intent"
SCORE_FIELD_KEYS: tuple[str, ...] = (FIT_FIELD_KEY, INTENT_FIELD_KEY)

_CURSOR_SEPARATOR = "|"


class InvalidCursorError(ValueError):
    """A ``?cursor=`` value this endpoint did not mint (or that has been tampered with)."""


# --- the wire vocabulary ----------------------------------------------------------------------


class WireModel(BaseModel):
    """Frozen, camelCase-on-the-wire, snake_case in Python — the frontend's JSON convention."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class ProjectScore(WireModel):
    """A Pass-A score under one ICP — the score itself, with no project attached.

    ``fit`` and ``intent`` are independently nullable: a project may have scored fit and not intent
    (or vice versa), and reporting the missing half as ``0`` would be a fabrication.

    The nested shape: the account-detail endpoint already knows which project's section it is
    filling, so repeating the id inside every score there would be noise.
    """

    fit: float | None = None
    intent: float | None = None
    icp_key: str | None = None
    icp_version: int | None = None
    scored_at: datetime


class AccountProjectScore(ProjectScore):
    """A :class:`ProjectScore` carrying the project it belongs to — the flat list row's shape."""

    project_id: str


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

# Workspace-scoped, with the customer identity and merge losers excluded. ``merged_into IS NULL``
# and ``status <> 'merged'`` are equivalent by the ``account_entity_merged_iff_target`` CHECK; the
# null test is the indexable one. ``workspace_client_binding`` is the authority for which account
# represents the customer itself, so it must not leak into any target-account lens.
_ACCOUNT_FILTER = """
    a.workspace_id = :workspace_id
    AND a.merged_into IS NULL
    AND NOT EXISTS (
        SELECT 1
        FROM workspace_client_binding wcb
        WHERE wcb.workspace_id = a.workspace_id
          AND wcb.client_entity_id = a.id
    )
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

_NUMBERED_PAGE_ACCOUNTS = text(
    f"""
    SELECT a.id, a.canonical_name, a.primary_domain, a.created_at, a.updated_at
    FROM account_entity a
    WHERE {_ACCOUNT_FILTER}
    ORDER BY a.created_at DESC, a.id DESC
    LIMIT :row_limit OFFSET :row_offset
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

# The project display names for a page's project ids — one batched read, never one query per row.
# Workspace-scoped on purpose: membership's composite FK already pins a project to this workspace,
# but the account detail derives section ids from ``run_lineage.project_id``, which has **no** FK to
# ``project`` at all, so an id there can be unknown or (in principle) another tenant's. A foreign or
# missing id resolves to no row and the name is served ``null``, never another workspace's label.
_PROJECT_NAMES = text(
    """
    SELECT project_id, name
    FROM project
    WHERE workspace_id = :workspace_id AND project_id IN :project_ids
    """
).bindparams(bindparam("project_ids", expanding=True))

# The page's owner and creator ids, read from the spine in one batched statement rather than
# widened onto ``_PAGE_ACCOUNTS``: the page scan is shared with the composer's mention catalog and
# stays the five columns a row is identified by. Workspace-scoped like every other read here.
_ACCOUNT_PEOPLE = text(
    """
    SELECT id, owner_user_id, created_by_user_id
    FROM account_entity
    WHERE workspace_id = :workspace_id AND id IN :entity_ids
    """
).bindparams(bindparam("entity_ids", expanding=True, type_=PgUUID(as_uuid=True)))

# --- composition helpers ----------------------------------------------------------------------


def as_int(value: Any) -> int | None:
    """A JSON number that is genuinely an integer — ``bool`` is not one, whatever Python says."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


#: One ``account.scoring.*`` claim as :func:`group_score_claims` consumes it:
#: ``(entity_id, project_id | None, field_key, decoded value_json, scored_at)``. ``project_id`` is
#: ``None`` only for the account-detail endpoint's unattributed partition — this endpoint's own
#: query inner-joins lineage, so it never produces one.
ScoreClaimRow = tuple[uuid.UUID, str | None, str, Any, datetime]


def group_score_claims(
    rows: Iterable[ScoreClaimRow],
) -> dict[tuple[uuid.UUID, str | None], tuple[ProjectScore, ...]]:
    """The one scoring-attribution rule, shared by the list row and the detail's project sections.

    Grouped by ``(entity, project, icp_key, icp_version)``, not merely by project: an account may be
    scored under several ICPs within one project (D5), and collapsing those to one score would have
    to pick a winner — another representative-run guess.

    **Last-collected-wins, not the canonical merge.** ``current_values`` cannot serve this read: it
    collapses to one winner per ``(entity, field)`` with no project attribution, which is exactly
    the representative-run fiction FI-2 §7 removes. So the tie-break inside a group is recency
    alone, not the merge's tier → corroborations → confidence ordering. That is sound *here* because
    a score is a derived, single-writer value (M6.3 writes it at tier 1 with a deterministic
    per-ICP run id and supersedes its own earlier rubric version), so a group normally holds exactly
    one live claim per field and the ordering never has to break a real tie. If a second writer ever
    produces ``account.scoring.*``, this needs the merge's ranking — see the FI-2 §6.4
    project-scoped-supersede work, which is the change that would create that possibility.

    ``rows`` must arrive oldest-first within a group; a later row of the same field overwrites an
    earlier one, so last-written is newest.
    """
    grouped: dict[tuple[uuid.UUID, str | None, str | None, int | None], dict[str, Any]] = {}
    for entity_id, project_id, field_key, value, scored_at in rows:
        payload = value if isinstance(value, dict) else {}
        key = (
            entity_id,
            project_id,
            as_str(payload.get("icp_key")),
            as_int(payload.get("icp_version")),
        )
        accumulator = grouped.setdefault(key, {"fit": None, "intent": None, "scored_at": scored_at})
        accumulator["fit" if field_key == FIT_FIELD_KEY else "intent"] = as_float(
            payload.get("value")
        )
        if scored_at > accumulator["scored_at"]:
            accumulator["scored_at"] = scored_at

    by_group: dict[tuple[uuid.UUID, str | None], list[ProjectScore]] = defaultdict(list)
    for (entity_id, project_id, icp_key, icp_version), accumulator in grouped.items():
        by_group[(entity_id, project_id)].append(
            ProjectScore(
                fit=accumulator["fit"],
                intent=accumulator["intent"],
                icp_key=icp_key,
                icp_version=icp_version,
                scored_at=accumulator["scored_at"],
            )
        )
    return {
        group: tuple(sorted(scores, key=lambda s: (s.icp_key or "", s.icp_version or 0)))
        for group, scores in by_group.items()
    }


async def _read_scores(
    conn: AsyncConnection, *, workspace_id: str, entity_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[AccountProjectScore, ...]]:
    """Per-account, per-project, per-ICP scores — the lineage-attributed relative read.

    The SQL is this endpoint's (batched over a page of accounts, lineage **inner**-joined so an
    unattributable score is never guessed onto a project); the grouping is
    :func:`group_score_claims`, shared with the account-detail sections so the two surfaces cannot
    report a different score for the same claims.
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

    grouped = group_score_claims(
        (
            uuid.UUID(str(entity_id)),
            str(project_id),
            str(field_key),
            decode_jsonb_scalar(raw_value),
            # The claim's own age, on the same rule the merge uses: the observation time when the
            # source stated one, else when we collected it.
            observed_at or collected_at,
        )
        for entity_id, field_key, raw_value, observed_at, collected_at, project_id in rows
    )
    by_account: dict[uuid.UUID, list[AccountProjectScore]] = defaultdict(list)
    for (entity_id, project_id), scores in grouped.items():
        by_account[entity_id].extend(
            AccountProjectScore(project_id=str(project_id), **score.model_dump())
            for score in scores
        )
    return {
        entity_id: tuple(
            sorted(scores, key=lambda s: (s.project_id, s.icp_key or "", s.icp_version or 0))
        )
        for entity_id, scores in by_account.items()
    }


async def project_names(
    conn: AsyncConnection, *, workspace_id: str, project_ids: Iterable[str | None]
) -> dict[str, str]:
    """``{project_id: name}`` for the ids this workspace actually has a ``project`` row for.

    THE project-name read, shared by the list row's ``projects[]`` and the detail's
    ``projectSections[]`` so the two surfaces cannot name the same project differently. One batched
    statement per response — a per-membership lookup would be an N+1 over a 200-row page — and ids
    with no row are simply absent from the mapping, so every caller renders ``null`` by
    ``.get(project_id)`` rather than inventing a placeholder.

    ``None`` entries (the detail's unattributed section) are dropped before the query: there is no
    project to name.
    """
    wanted = sorted({project_id for project_id in project_ids if project_id is not None})
    if not wanted:
        return {}
    rows = await conn.execute(_PROJECT_NAMES, {"workspace_id": workspace_id, "project_ids": wanted})
    return {str(project_id): str(name) for project_id, name in rows}


# --- the read model ---------------------------------------------------------------------------

#: One page of the account spine: ``(total, rows, has_more)``. ``total`` counts the whole filtered
#: set, not the page; ``rows`` are ``(id, canonical_name, primary_domain, created_at, updated_at)``
#: in the served order.
SpinePage = tuple[int, Sequence[Any], bool]


async def read_spine_page(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str | None,
    limit: int,
    cursor: str | None,
    page_number: int | None,
) -> SpinePage:
    """The paginated account scan — ONE definition of "which accounts this workspace has".

    Public because the composer's mention catalog needs the same bounded, client-binding-excluding,
    merge-loser-excluding page the table shows; a second scan somewhere else is how two surfaces
    start disagreeing about which accounts exist. Raises :class:`InvalidCursorError` for a cursor
    this endpoint did not mint.
    """
    if page_number is not None and cursor is not None:
        raise ValueError("page and cursor are mutually exclusive")
    cursor_created_at, cursor_id = (None, None) if cursor is None else decode_cursor(cursor)
    filter_params: dict[str, Any] = {"workspace_id": workspace_id, "project_id": project_id}

    total = int((await conn.execute(_COUNT_ACCOUNTS, filter_params)).scalar_one())
    if page_number is None:
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
        return total, rows[:limit], len(rows) > limit
    page_rows = (
        await conn.execute(
            _NUMBERED_PAGE_ACCOUNTS,
            {**filter_params, "row_limit": limit, "row_offset": (page_number - 1) * limit},
        )
    ).all()
    return total, page_rows, False


def _next_cursor(
    page_rows: Sequence[Any], *, page_number: int | None, has_more: bool
) -> str | None:
    """The keyset cursor for the next page — ``None`` in numbered-page mode and on the last page."""
    if page_number is not None or not has_more or not page_rows:
        return None
    last_id, _name, _domain, last_created_at, _updated = page_rows[-1]
    return encode_cursor(last_created_at, uuid.UUID(str(last_id)))


def account_fit(scores: tuple[AccountProjectScore, ...]) -> float | None:
    """The fit the row shows: the account's most recently scored fit, whichever project scored it.

    **Founder ruling 2026-09-11 — a fit is global to the account.** A seller's ICPs vary little
    from project to project, so a score decided once (by discovery, or by a later scorer) is the
    account's fit everywhere: the row shows it whether the account belongs to the project that
    scored it, to another, or to none at all. This supersedes the FI-2 §7 read rule under which
    the row served only the *primary project's* score and a membership-less account was always
    unscored — which left every freshly discovered account (a member of nothing until approved)
    with an empty fit column on the very screen meant to show it.

    Among the account's scores the most recently scored wins, because an older ICP's verdict is not
    this account's current fit; the per-project attribution is kept on the account detail's project
    sections, so nothing is lost. The scores still arrive attributed through ``run_lineage`` —
    nothing here guesses a run — and an account with no live score has no fit: ``None`` is served,
    never a band.
    """
    candidates = [score for score in scores if score.fit is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda score: score.scored_at).fit


async def list_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    page_number: int | None = None,
    settings: Settings,
    now: datetime,
) -> AccountsResponseV1:
    """One page of the workspace's accounts — the ARV2 accounts-table row.

    The page, the filter and the cursor semantics are :func:`read_spine_page`'s; this function owns
    the row. It is the *screen's* row: bands and labels the backend computes so the browser cannot
    disagree with it, the account's own chrome (industries, socials, location, custom fields,
    owner), and exactly one research status and one fit, because the table has one column for each.
    The status and the fit are scoped differently and on purpose:
    the fit is the **primary project's** (a score is ``project_relative``, so serving another
    project's would be a category error), while the research status is the account's own latest
    ARV2 job, whichever project launched it.

    Every source is read in a fixed number of batched statements over the whole page: a per-row
    lookup here would be an N+1 over a 200-row page, which is what the suite's statement-count
    guard exists to prevent.

    ``now`` is accepted for the v1 reader signature the other four endpoints share (they serve
    relative time labels); this row carries none, so nothing here reads the clock.
    """
    del now  # no relative label on this row — see the docstring.
    total, page_rows, has_more = await read_spine_page(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        page_number=page_number,
    )
    meta = AccountsMeta(
        total=total, next_cursor=_next_cursor(page_rows, page_number=page_number, has_more=has_more)
    )
    if not page_rows:
        return AccountsResponseV1(data=(), meta=meta)

    account_ids = [uuid.UUID(str(row[0])) for row in page_rows]
    entity_ids = [EntityId(account_id) for account_id in account_ids]
    neutral = await current_values(
        conn,
        entity_ids,
        V1_NEUTRAL_FIELD_KEYS,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    memberships = await memberships_for_accounts(
        conn, workspace_id=workspace_id, account_ids=account_ids
    )
    scores = await _read_scores(conn, workspace_id=workspace_id, entity_ids=account_ids)
    research = await arv2_research_status_for(
        conn, workspace_id=workspace_id, account_ids=entity_ids
    )
    names = await project_names(
        conn,
        workspace_id=workspace_id,
        project_ids=(
            membership.project_id
            for account_memberships in memberships.values()
            for membership in account_memberships
        ),
    )
    people = {
        uuid.UUID(str(entity_id)): (owner_user_id, created_by_user_id)
        for entity_id, owner_user_id, created_by_user_id in (
            await conn.execute(
                _ACCOUNT_PEOPLE, {"workspace_id": workspace_id, "entity_ids": account_ids}
            )
        ).all()
    }
    owners = await owners_for(
        conn,
        user_ids=(user_id for pair in people.values() for user_id in pair if user_id),
    )
    custom_fields = await custom_fields_for(conn, workspace_id=workspace_id, account_ids=entity_ids)
    last_modified = await last_modified_for(conn, workspace_id=workspace_id, account_ids=entity_ids)

    def owner_of(user_id: str | None) -> AccountOwner | None:
        return owners.get(user_id) if user_id else None

    def neutral_value(entity_id: EntityId, field_key: str) -> Any:
        current = neutral.get((entity_id, field_key))
        return None if current is None else current.value_json

    data: list[AccountV1] = []
    for account_id, (_id, canonical_name, primary_domain, created_at, updated_at) in zip(
        account_ids, page_rows, strict=True
    ):
        entity_id = EntityId(account_id)
        account_memberships = memberships.get(account_id, ())
        # The recorded FI-2 §2 policy: element 0 of the membership read is the primary project. A
        # membership-less account (a seed, a legacy import) simply has none, and its row is served
        # unscored rather than attributed to a project it does not belong to.
        primary_project_id = account_memberships[0].project_id if account_memberships else None
        # The account's own latest ARV2 job, whichever project launched it. The row still leads
        # with the primary project's *name*, but research is a fact about the account: an ARV2 run
        # pins its project, and hiding a finished research job because the account's primary
        # membership happens to be another project would report it as never researched.
        status, refreshing = research.get(entity_id, ("not_started", False))
        # The account's newest fit, whichever project scored it (founder ruling 2026-09-11: a fit
        # is global to the account) — see :func:`account_fit`.
        fit = account_fit(scores.get(account_id, ()))
        location = location_label(neutral_value(entity_id, "core.hq_location"))
        owner_user_id, created_by_user_id = people.get(account_id, (None, None))
        revenue_band = as_str(neutral_value(entity_id, "core.revenue_band"))
        data.append(
            AccountV1(
                id=str(account_id),
                # ``canonical_name`` is NOT NULL on the spine, but a blank one would fail the
                # contract's ``min(1)``; the domain, then the id, keep the row honest and visible.
                name=str(canonical_name or primary_domain or account_id),
                # The platform's logo route when the account carries a mark-type logo (founder
                # ruling 2026-09-11); null otherwise — never a guessed URL.
                logo_path=account_logo_path(
                    account_id,
                    neutral_value(entity_id, "core.logo_url"),
                    domain=primary_domain,
                    settings=settings,
                ),
                website_url=website_url(primary_domain),
                # ``arv2_research_job.status`` is the seam-1 vocabulary, which is character-for-
                # character the ``ResearchStatus`` literal (D0 ruling S11): the row's status *is*
                # the job's status, and the label map is keyed by it.
                research_status=status,
                research_status_label=RESEARCH_STATUS_LABELS[status],
                research_is_refreshing=refreshing,
                overall_fit=fit_band(fit, settings=settings),
                fit_score=fit_score_100(fit),
                # The label, not the token: ``core.revenue_band`` stores ``"10m_50m"`` and the
                # revenue column was printing it verbatim at a marketer (D4-b controller ruling 2).
                revenue_band=revenue_band_label(revenue_band),
                employee_band=employee_band(
                    as_int(neutral_value(entity_id, "core.employee_count")),
                    neutral_value(entity_id, "core.employee_range"),
                ),
                # One location claim per account today, so the count is 0 or 1 — reported as a
                # count because the screen shows "+N", and inventing a larger one would be a lie.
                location_count=1 if location else 0,
                locations_label=location,
                owner=owner_of(owner_user_id),
                created_by=owner_of(created_by_user_id),
                industry_labels=tuple(
                    industry_labels(
                        neutral_value(entity_id, "core.industry"),
                        neutral_value(entity_id, "core.industries_all"),
                    )
                ),
                socials=tuple(
                    socials(
                        neutral_value(entity_id, "core.company_linkedin_url"),
                        neutral_value(entity_id, "core.company_twitter_url"),
                    )
                ),
                created_at=iso_utc(created_at),
                last_modified_at=iso_utc(last_modified.get(entity_id, updated_at)),
                primary_project_id=primary_project_id,
                projects=tuple(
                    AccountProject(
                        id=membership.project_id,
                        # The contract requires a non-empty name; an unnamed project is named by
                        # its id rather than served as an empty chip.
                        name=names.get(membership.project_id) or membership.project_id,
                    )
                    for membership in account_memberships
                ),
                custom_fields=tuple(custom_fields.get(entity_id, ())),
            )
        )
    return AccountsResponseV1(data=tuple(data), meta=meta)


# --- the route --------------------------------------------------------------------------------


def register_accounts_list_routes(
    router: APIRouter, *, conn_factory: ConnFactory, settings: Settings
) -> None:
    """Register ``GET /accounts`` on the workspace-scoped `/frontend/v1` router.

    ``settings`` reaches the reader because the fit bands are configured thresholds, not code
    (ruling S3). A ``?contract=`` query parameter is accepted and ignored: it selected between the
    FI-2 and v1 payloads until the FI-2 half was deleted (2026-09-09), and refusing the value the
    frontend may still be sending would 422 a request this route can answer perfectly well.
    """

    @router.get("/accounts")
    async def get_accounts(
        workspace_id: WorkspaceDep,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        cursor: Annotated[str | None, Query()] = None,
        page: Annotated[int | None, Query(ge=1)] = None,
    ) -> AccountsResponseV1:
        async with conn_factory() as conn:
            try:
                return await list_accounts(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    limit=limit,
                    cursor=cursor,
                    page_number=page,
                    settings=settings,
                    now=datetime.now(UTC),
                )
            except (InvalidCursorError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": (
                            "INVALID_CURSOR"
                            if isinstance(exc, InvalidCursorError)
                            else "INVALID_PAGINATION"
                        ),
                        "message": str(exc),
                    },
                ) from exc
