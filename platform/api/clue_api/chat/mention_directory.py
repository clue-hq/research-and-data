"""The composer's @-mention directory: every account and committee contact in the workspace.

2026-10-05: the @ tagger only offered the 50 newest accounts (each with its committee), filtered in
the browser, so an older account could not be tagged whatever was typed. ABM directories are small
(tens to a few thousand accounts, a handful of committee contacts each), so the browser now loads
the whole directory once — names, one secondary line and ids, no research content — keeps it for
the session, and re-checks it with ``If-None-Match`` against :attr:`MentionDirectory.etag`.

Above ``max_entries`` (``CLUE_MENTION_DIRECTORY_MAX_ENTRIES``) the directory is cut — project
accounts first, then newest — and marked incomplete, and the composer also asks
:func:`search_mention_directory` as the user types.

Every rule is the existing one: the accounts are the accounts screen's lens
(``ACCOUNT_LENS_FILTER``: workspace-scoped, no merge losers, never the workspace's own client), and
the contacts are each account's ARV2 committee (``committee_members_for_accounts``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.gather import committee_members_for_accounts
from clue_api.chat.composer_context import (
    ComposerContextEntity,
    _account_logo_urls,
    account_context_entity,
    contact_context_entity,
)
from clue_api.frontend_read.accounts_list import ACCOUNT_LENS_FILTER
from clue_config import Settings
from clue_core import EntityId
from clue_research.claimstore import WorkspaceScope

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "MentionDirectory",
    "build_mention_directory",
    "search_mention_directory",
]

DEFAULT_MAX_ENTRIES = 5000
SEARCH_LIMIT = 20

# Project accounts first (when a project is given), then newest — the order the picker browses in.
_ACCOUNTS = text(
    f"""
    SELECT a.id, a.canonical_name, a.primary_domain,
           EXISTS (
               SELECT 1 FROM project_account pm
               WHERE pm.workspace_id = a.workspace_id
                 AND pm.account_entity_id = a.id
                 AND pm.project_id = :member_project
           ) AS in_project
    FROM account_entity a
    WHERE {ACCOUNT_LENS_FILTER}
    ORDER BY in_project DESC, a.created_at DESC, a.id DESC
    """
)

_SEARCH_ACCOUNTS = text(
    f"""
    SELECT a.id, a.canonical_name, a.primary_domain
    FROM account_entity a
    WHERE {ACCOUNT_LENS_FILTER}
      AND (
          a.canonical_name ILIKE :pattern ESCAPE '\\'
          OR a.primary_domain ILIKE :pattern ESCAPE '\\'
      )
    ORDER BY a.canonical_name, a.id
    LIMIT :limit
    """
)

# The committee rule (a live contact under a lens account holding at least one live claim),
# matched by name.
_SEARCH_CONTACTS_TEMPLATE = f"""
    SELECT contact.id, contact.account_entity_id
    FROM contact_entity contact
    JOIN account_entity a ON a.id = contact.account_entity_id
    WHERE contact.workspace_id = :workspace_id
      AND contact.merged_into IS NULL
      AND contact.full_name ILIKE :pattern ESCAPE '\\'
      AND {ACCOUNT_LENS_FILTER}
      AND EXISTS (
          SELECT 1 FROM claim
          WHERE claim.entity_id = contact.id
            AND claim.superseded_by IS NULL
            AND {{scope_sql}}
      )
    ORDER BY contact.full_name, contact.id
    LIMIT :limit
"""


@dataclass(frozen=True, slots=True)
class MentionDirectory:
    entities: tuple[ComposerContextEntity, ...]
    #: ``False`` when the workspace exceeded ``max_entries`` and the list was cut.
    complete: bool
    #: A strong validator over the whole payload, quoted for the ``ETag`` header.
    etag: str


def _etag(entities: list[ComposerContextEntity], complete: bool) -> str:
    payload = json.dumps(
        [
            [
                entity.object_type,
                entity.object_id,
                entity.label,
                entity.secondary_label,
                entity.image_url,
                entity.account_id,
                entity.account_name,
            ]
            for entity in entities
        ]
        + [complete],
        separators=(",", ":"),
    )
    return '"' + hashlib.sha256(payload.encode()).hexdigest()[:32] + '"'


async def build_mention_directory(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str | None,
    settings: Settings | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> MentionDirectory:
    """Every lens account, each followed by its committee contacts, in a fixed number of reads."""

    rows = (
        await conn.execute(
            _ACCOUNTS,
            {"workspace_id": workspace_id, "project_id": None, "member_project": project_id},
        )
    ).all()
    complete = len(rows) <= max_entries
    rows = rows[:max_entries]
    account_ids = [str(row[0]) for row in rows]
    committees = await committee_members_for_accounts(
        conn, workspace_id=workspace_id, account_ids=None if complete else account_ids
    )
    logos = await _account_logo_urls(
        conn,
        workspace_id=workspace_id,
        account_ids=[EntityId(UUID(account_id)) for account_id in account_ids],
    )
    entities: list[ComposerContextEntity] = []
    for account_id, name, domain, _in_project in rows:
        if len(entities) >= max_entries:
            complete = False
            break
        entities.append(
            account_context_entity(
                account_id,
                str(name),
                domain,
                logos.get(EntityId(UUID(str(account_id)))),
                settings=settings,
            )
        )
        for member in committees.get(str(account_id), []):
            if not member.name:
                continue
            if len(entities) >= max_entries:
                complete = False
                break
            entities.append(
                contact_context_entity(member, account_id=str(account_id), account_name=str(name))
            )
    return MentionDirectory(
        entities=tuple(entities), complete=complete, etag=_etag(entities, complete)
    )


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def search_mention_directory(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    query: str,
    limit: int = SEARCH_LIMIT,
    settings: Settings | None = None,
) -> tuple[ComposerContextEntity, ...]:
    """Accounts by name or domain, then committee contacts by name, across the whole workspace.

    Only for workspaces whose directory is incomplete; the usual path never asks the server.
    """

    needle = query.strip()
    if not needle:
        return ()
    params = {
        "workspace_id": workspace_id,
        "project_id": None,
        "pattern": _like_pattern(needle),
        "limit": limit,
    }
    accounts = (await conn.execute(_SEARCH_ACCOUNTS, params)).all()
    scope_sql, scope_params = WorkspaceScope.for_workspace(workspace_id).predicate()
    matched_contacts = (
        await conn.execute(
            text(_SEARCH_CONTACTS_TEMPLATE.format(scope_sql=scope_sql)),
            {**params, **scope_params},
        )
    ).all()
    logos = await _account_logo_urls(
        conn,
        workspace_id=workspace_id,
        account_ids=[EntityId(UUID(str(row[0]))) for row in accounts],
    )
    results: list[ComposerContextEntity] = [
        account_context_entity(
            account_id,
            str(name),
            domain,
            logos.get(EntityId(UUID(str(account_id)))),
            settings=settings,
        )
        for account_id, name, domain in accounts
    ]
    wanted = {str(contact_id) for contact_id, _account in matched_contacts}
    committees = await committee_members_for_accounts(
        conn,
        workspace_id=workspace_id,
        account_ids=sorted({str(account) for _contact, account in matched_contacts}),
    )
    for members in committees.values():
        for member in members:
            if member.id in wanted and member.name:
                results.append(
                    contact_context_entity(
                        member, account_id=member.account_id, account_name=member.account_name
                    )
                )
    return tuple(results[:limit])
