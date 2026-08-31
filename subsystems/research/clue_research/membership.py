"""``project_account`` — the account↔project membership junction (FI-2 P1; spec §2).

Accounts are workspace-global: one normalized spine, never a per-project copy (FI-2 R1). What a
project owns is *membership* — "this project targets that account" — and FI-2 R4 makes that real,
queryable state instead of folklore recomputed from discovery lineage. This module is that
junction's whole write/read surface:

* :func:`ensure_project_account` — the idempotent upsert every admission/import/directive write
  site calls inside its own transaction. **The first add wins for a given account**:
  ``added_via``/``added_at`` record the first channel and time that *this* account joined the
  project, so a later add through another channel is a no-op on the row.
* :func:`memberships_for_accounts` — the account-first read behind the frontend account row's
  ``projects[]``; ordered ``added_at`` ascending, so element 0 is the recorded ``primaryProjectId``
  policy (earliest membership), not an ``ORDER BY created_at DESC`` guess. It returns the whole
  ``(project_id, added_via, added_at)`` triple, which is what the read layer renders.
* :func:`projects_for_accounts` — the same read projected to project ids only, for the callers that
  need nothing else. It *delegates* to :func:`memberships_for_accounts` rather than issuing its own
  query, so the element-0-is-primary ordering policy lives in exactly one place.
* :func:`accounts_for_project` — the project-first read behind a project's target-account list.
* :func:`repoint_project_accounts` — moves a merge loser's memberships onto the survivor. Wired
  into ``identity.mark_merged`` so it runs in the merge's own transaction and no caller has to
  remember it. Where *both* accounts already belonged to a project, the **survivor's existing row
  is kept** (spec §2's ``ON CONFLICT DO NOTHING``) — the loser's possibly-earlier ``added_at`` is
  deliberately not adopted, so "first add wins" does not carry across a merge. **A merge's
  membership move is not reversible:** ``identity.split_merge`` un-does a merge's entity rows but
  does not restore the moved memberships — restoration is deferred to the M2.4 review composition
  (see that function's docstring).

**Both workspace anchors are enforced by the database** (migration ``61b00ee9c70a``): composite FKs
to ``account_entity (id, workspace_id)`` and ``project (project_id, workspace_id)`` — the real
project column is ``project_id``, not the ``id`` the spec's illustrative DDL writes. A membership
naming an account or a project from another workspace is therefore *unrepresentable*, not merely
validated in Python.

Import direction: this module imports nothing from :mod:`clue_research.identity` — the dependency
runs the other way (``identity.entities`` imports :func:`repoint_project_accounts`, and
``identity.review`` imports :func:`ensure_project_account` so a human review resolution joins the
account to the project whose admission enqueued the task), so there is no cycle.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

# Mirrors the ``project_account_added_via_check`` CHECK in migration 61b00ee9c70a (text + CHECK,
# not a DB enum) — the test suite asserts every channel here is accepted by the constraint.
ADDED_VIA = ("discovered", "imported", "manual", "directive")


class ProjectMembership(BaseModel):
    """One ``project_account`` row as a reader sees it: which project, through which channel, when.

    ``added_via`` stays the raw registered channel string (one of :data:`ADDED_VIA`) rather than an
    enum, because the CHECK — not a DB enum — is the constraint, and a read must not crash on a
    channel a later migration adds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    added_via: str
    added_at: datetime


_ENSURE = text(
    """
    INSERT INTO project_account
        (workspace_id, project_id, account_entity_id, added_via, added_at)
    VALUES (:workspace_id, :project_id, :account_entity_id, :added_via, :added_at)
    ON CONFLICT (workspace_id, project_id, account_entity_id) DO NOTHING
    """
)

_ENSURE_MANY = text(
    """
    INSERT INTO project_account
        (workspace_id, project_id, account_entity_id, added_via, added_at)
    SELECT :workspace_id, :project_id, a.id, :added_via, :added_at
    FROM account_entity a
    WHERE a.workspace_id = :workspace_id
      AND a.merged_into IS NULL
      AND a.id IN :account_ids
    ON CONFLICT (workspace_id, project_id, account_entity_id) DO NOTHING
    RETURNING account_entity_id
    """
).bindparams(bindparam("account_ids", expanding=True, type_=PgUUID(as_uuid=True)))

_BY_ACCOUNTS = text(
    """
    SELECT account_entity_id, project_id, added_via, added_at
    FROM project_account
    WHERE workspace_id = :workspace_id AND account_entity_id IN :account_ids
    ORDER BY account_entity_id, added_at, project_id
    """
).bindparams(bindparam("account_ids", expanding=True, type_=PgUUID(as_uuid=True)))

_BY_PROJECT = text(
    """
    SELECT account_entity_id
    FROM project_account
    WHERE workspace_id = :workspace_id AND project_id = :project_id
    ORDER BY added_at, account_entity_id
    """
)

# Mirror the loser's rows onto the survivor, keeping the survivor's own row where both are members
# of the same project (its added_at is the survivor's history, and the merge must not rewrite it).
_REPOINT_INSERT = text(
    """
    INSERT INTO project_account
        (workspace_id, project_id, account_entity_id, added_via, added_at)
    SELECT workspace_id, project_id, :survivor_id, added_via, added_at
    FROM project_account
    WHERE workspace_id = :workspace_id AND account_entity_id = :loser_id
    ON CONFLICT (workspace_id, project_id, account_entity_id) DO NOTHING
    """
)

_REPOINT_DELETE = text(
    "DELETE FROM project_account "
    "WHERE workspace_id = :workspace_id AND account_entity_id = :loser_id"
)


async def ensure_project_account(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    account_entity_id: uuid.UUID,
    added_via: str,
    added_at: datetime | None = None,
) -> None:
    """Record that ``project_id`` targets ``account_entity_id``. Idempotent; the first add wins.

    Call inside the same transaction as the admission/import/directive write it records. Raises
    :class:`ValueError` on an unknown ``added_via`` **before** issuing any statement, so a bad
    caller never leaves a partial write or poisons a shared transaction (the
    ``project_account_added_via_check`` CHECK mirrors the guard for writers that bypass this
    module).
    """
    if added_via not in ADDED_VIA:
        raise ValueError(f"unknown added_via {added_via!r}; expected one of {ADDED_VIA}")
    await conn.execute(
        _ENSURE,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "account_entity_id": account_entity_id,
            "added_via": added_via,
            "added_at": added_at or datetime.now(UTC),
        },
    )


async def ensure_project_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    account_entity_ids: Sequence[uuid.UUID],
    added_via: str,
    added_at: datetime | None = None,
) -> frozenset[uuid.UUID]:
    """Record many live canonical Accounts in one project and return the newly-added ids.

    Existing memberships are intentionally absent from the returned set: callers can report them
    as ``unchanged`` without rewriting their first-add provenance. Unknown, foreign-workspace, and
    merged-away ids are skipped by the workspace/live Account selection and remain distinguishable
    to a caller that compares this result with its own eligibility read.
    """

    if added_via not in ADDED_VIA:
        raise ValueError(f"unknown added_via {added_via!r}; expected one of {ADDED_VIA}")
    if not account_entity_ids:
        return frozenset()
    rows = await conn.execute(
        _ENSURE_MANY,
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "account_ids": list(account_entity_ids),
            "added_via": added_via,
            "added_at": added_at or datetime.now(UTC),
        },
    )
    return frozenset(uuid.UUID(str(account_id)) for account_id in rows.scalars())


async def memberships_for_accounts(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[ProjectMembership, ...]]:
    """Map each account to its memberships — project, channel and time — oldest membership first.

    Element 0 of each tuple is the account's ``primaryProjectId`` (earliest ``added_at`` — the
    recorded FI-2 §2 policy). An account with no membership (a stage-0 seed, the client entity, a
    legacy import) is simply absent from the mapping: membership-less accounts are expected, and
    the global list renders them.
    """
    if not account_ids:
        return {}
    rows = (
        await conn.execute(
            _BY_ACCOUNTS, {"workspace_id": workspace_id, "account_ids": list(account_ids)}
        )
    ).all()
    grouped: dict[uuid.UUID, list[ProjectMembership]] = defaultdict(list)
    for account_entity_id, project_id, added_via, added_at in rows:
        grouped[account_entity_id].append(
            ProjectMembership(
                project_id=str(project_id), added_via=str(added_via), added_at=added_at
            )
        )
    return {account_id: tuple(memberships) for account_id, memberships in grouped.items()}


async def projects_for_accounts(
    conn: AsyncConnection, *, workspace_id: str, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, ...]]:
    """:func:`memberships_for_accounts` projected to project ids — same order, same policy."""
    grouped = await memberships_for_accounts(
        conn, workspace_id=workspace_id, account_ids=account_ids
    )
    return {
        account_id: tuple(membership.project_id for membership in memberships)
        for account_id, memberships in grouped.items()
    }


async def accounts_for_project(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> tuple[uuid.UUID, ...]:
    """Every account this project targets, oldest membership first."""
    rows = await conn.execute(_BY_PROJECT, {"workspace_id": workspace_id, "project_id": project_id})
    return tuple(rows.scalars())


async def repoint_project_accounts(
    conn: AsyncConnection, *, workspace_id: str, loser_id: uuid.UUID, survivor_id: uuid.UUID
) -> None:
    """Move a merge loser's memberships onto the survivor (union, no duplicates).

    Run in the merge's own transaction — ``identity.mark_merged`` calls this, so membership can
    never be orphaned on a merged-away account. Within-workspace only, like every merge (B3); a
    project both accounts already belonged to keeps the *survivor's* row, so the survivor's own
    ``added_at`` history is not rewritten by the merge.

    Raises :class:`ValueError` when ``loser_id == survivor_id`` — self-re-pointing is never a real
    merge, and the mirror-then-delete would conflict on identical primary keys and then **delete
    every membership of that account**. Refused before any statement is issued, so a bad caller
    leaves no partial write and does not poison a shared transaction (same guard idiom as
    :func:`ensure_project_account`; ``identity.mark_merged`` raises ``MergeCycleError`` on the same
    pair, but this function is callable on its own).

    The move is one-way: ``identity.split_merge`` does not restore it (deferred to M2.4).
    """
    if loser_id == survivor_id:
        raise ValueError(
            f"cannot re-point project membership from {loser_id} onto itself; "
            "loser_id and survivor_id must differ"
        )
    params = {"workspace_id": workspace_id, "loser_id": loser_id, "survivor_id": survivor_id}
    await conn.execute(_REPOINT_INSERT, params)
    await conn.execute(_REPOINT_DELETE, {k: params[k] for k in ("workspace_id", "loser_id")})
