"""ARV2 D3, E3 — the account **workspace** payload: ``GET /frontend/v1/accounts/{id}/workspace``.

The insights-and-artifacts half of one account's screen, and the only endpoint that serves the
generated **insights** page. It is deliberately a *new* route rather than a second contract on an
existing one: nothing FI-2-era ever served this shape, so there was no old payload to keep
byte-for-byte beside it.

Four properties are structural rather than incidental:

* **the account is resolved by exactly the detail's three rules** — ``surviving_id`` (a merged
  loser is followed *silently*: this contract has no ``redirectedFrom`` slot), the workspace check,
  and the client-entity exclusion. An unknown id and another tenant's id are indistinguishable to
  the caller, so the route cannot be used to probe another workspace's id space;
* **``insightSummary`` is computed by the backend, from the block it just served.** D2's
  :func:`~clue_api.arv2.display.blocks.insight_summary` counts items in *non-restricted* sections
  only — a "context only" watch-out is context the marketer must not use, so counting it would
  overstate what the page offers — and the people count is the committee this page speaks about.
  Deriving either in the browser would be a second place for the two to disagree;
* **``researchEvidence`` covers exactly what the page cites**, so every citation chip on the
  insights page opens onto a row rather than onto nothing;
* **``insights`` is served as an empty list, never omitted.** It is the dummy's legacy per-source
  rows, which have no backend owner; ``insightsDisplay`` is where this account's insight prose
  actually lives. The contract requires the key.
* **``artifacts`` are the design documents made for this account** (D0 ruling S9's later slice):
  the artifacts library's own rows narrowed to the account through ``design_account``, from every
  project and labelled with the project's name (founder, 2026-09-30), archived ones left out, with
  the gallery's thumbnail route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.blocks import insight_summary
from clue_api.arv2.display.recipes import Page
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.design_leg_wiring import design_document_card_fields, workspace_design_documents
from clue_api.frontend_read.account_detail import AccountNotFound
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contacts import _account_404
from clue_api.frontend_read.contract_v1 import (
    AccountArtifact,
    AccountWorkspaceResponseV1,
    AccountWorkspaceV1,
    ResearchDisplayBlock,
)
from clue_api.frontend_read.display_pages import DisplayPages, committee
from clue_api.frontend_read.v1_shared import activity_for, iso_utc, research_evidence_for
from clue_core import EntityId, EntityType
from clue_db import ConnFactory
from clue_research.identity import get_account, surviving_id

#: The page this endpoint serves. Named so the reader and any later evidence route cannot drift.
INSIGHTS_PAGE: Page = "insights"


async def read_account_workspace(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    display: DisplayPages,
    now: datetime,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
) -> AccountWorkspaceResponseV1:
    """One account's workspace payload in contract v1, or :class:`AccountNotFound`.

    ``display.page`` is called with its default ``generate=True``: this *is* the page read, so
    writing a section the account does not have yet is the intended behaviour wherever the seam has
    a runner. Where it has none (no key, or generation switched off) the seam is a pure projection
    and the page is served exactly as it is stored — an all-empty block is still a block, and the
    frontend renders the page grammar from it.
    """
    canonical = await surviving_id(conn, EntityId(account_id), EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    if account is None or account.workspace_id != workspace_id or canonical == client_entity_id:
        raise AccountNotFound(str(account_id))

    members = await committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical),
        project_id=project_id,
        context_id=context_id,
    )
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="account",
        subject_id=str(canonical),
        page=INSIGHTS_PAGE,
        project_id=project_id,
        context_id=context_id,
    )
    evidence = await research_evidence_for(
        conn, workspace_id=workspace_id, claim_ids=page.cited_claim_ids
    )
    activity = await activity_for(conn, workspace_id=workspace_id, account_id=canonical, now=now)

    return AccountWorkspaceResponseV1(
        data=AccountWorkspaceV1(
            account_id=str(canonical),
            # The dummy's legacy per-source insight rows: no backend owner, and the generated
            # page below is where this account's insights actually live.
            insights=(),
            insight_summary=tuple(insight_summary(page.display_block, len(members))),
            research_evidence=tuple(evidence),
            insights_display=ResearchDisplayBlock.model_validate(page.display_block),
            artifacts=await account_artifacts(
                conn, workspace_id=workspace_id, account_entity_id=canonical
            ),
            activity=tuple(activity),
        )
    )


#: Enough for any real account; the tab has no paging of its own.
_ACCOUNT_ARTIFACT_LIMIT = 200


async def account_artifacts(
    conn: AsyncConnection, *, workspace_id: str, account_entity_id: EntityId
) -> tuple[AccountArtifact, ...]:
    """The account's design documents, newest first, from every project; archived ones left out."""
    rows = await workspace_design_documents(
        conn,
        workspace_id=workspace_id,
        user_id=None,
        limit=_ACCOUNT_ARTIFACT_LIMIT,
        account_entity_id=str(account_entity_id),
    )
    items: list[AccountArtifact] = []
    for row in rows:
        if row["archived_at"] is not None:
            continue
        updated: datetime = row["updated_at"]
        document_id = str(row["id"])
        items.append(
            AccountArtifact(
                id=document_id,
                title=str(row["title"]),
                type=design_document_card_fields(row)["kind"],
                account_id=str(account_entity_id),
                project_name=str(row["project_title"]),
                updated_at=iso_utc(updated),
                # The gallery's own thumbnail route (``artifact-library.ts``), versioned so a new
                # design version is a new image.
                thumbnail_path=(
                    f"/api/clue/design/documents/{quote(document_id, safe='')}/thumbnail"
                    f"?v={int(row['current_version'])}"
                ),
                last_edited_label=f"Last edited {updated:%b} {updated.day}, {updated.year}",
            )
        )
    return tuple(items)


# --- the route --------------------------------------------------------------------------------


def register_account_workspace_routes(
    router: APIRouter, *, conn_factory: ConnFactory, display: DisplayPages
) -> None:
    """Register ``GET /accounts/{account_id}/workspace`` on the `/frontend/v1` router.

    ``display`` is the one seam the composition root shares across every endpoint that serves a
    generated page, so this screen and the detail screen looking at the same account schedule one
    rewrite between them rather than two.
    """

    @router.get("/accounts/{account_id}/workspace")
    async def get_account_workspace(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> AccountWorkspaceResponseV1:
        async with conn_factory() as conn:
            try:
                return await read_account_workspace(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    display=display,
                    now=datetime.now(tz=UTC),
                    project_id=project_id,
                    context_id=context_id,
                )
            except AccountNotFound as exc:
                # The 404 the other Account routes already answer with, imported rather than
                # re-typed: the code and the message are what the frontend switches on, and a
                # second literal of them is a second answer to "no such account".
                raise _account_404() from exc
