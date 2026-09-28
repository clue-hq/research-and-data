"""The account detail page: ``GET /frontend/v1/accounts/{id}`` (contract v1, ARV2 E2).

The ARV2 account page and its preview: the rail's labels, the account's own chrome, the committee
card, the generated overview page, and the evidence behind every citation on it. Everything is
composed from untouched mechanism surfaces — the account spine, the canonical merge over the
neutral fields, the lineage-attributed score, the D2 committee, the D3 display seam — and nothing
here owns research logic of its own.

Two disciplines are load-bearing here and are enforced, not merely intended:

* **Never scope a claim read by ``claim.workspace_id``** — a DB CHECK forces it NULL on every
  ``public_footprint`` claim, so that predicate silently *empties* a read instead of narrowing it.
  Every claim read here scopes through the **entity** (an id already proven to belong to this
  workspace) plus ``WorkspaceScope.predicate()``, and the lineage join adds
  ``run_lineage.workspace_id`` — a real tenancy column on a real tenancy table.
* **A fixed number of batched statements per response** — a per-member or per-field lookup here is
  what the suite's statement-count guard exists to prevent.

The second route in this module, ``GET /accounts/{id}/evidence/{claim_id}``, streams one retained
evidence artifact. It authorises stored overview citations and the account's scoped custom-field
claims, including retired fields. Authorization never writes or schedules a page.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.recipes import Page
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.frontend_read.accounts_list import (
    V1_NEUTRAL_FIELD_KEYS,
    _read_scores,
    account_fit,
    as_int,
    as_str,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contract_v1 import (
    AccountDetailResponseV1,
    AccountDetailV1,
    ResearchDisplayBlock,
)
from clue_api.frontend_read.display_pages import (
    DisplayPages,
    buying_committee,
    committee,
    rail_contacts,
)
from clue_api.frontend_read.evidence_stream import (
    evidence_artifact_response,
    read_live_artifact,
)
from clue_api.frontend_read.v1_shared import (
    EMPTY_BAND,
    RESEARCH_STATUS_LABELS,
    account_logo_path,
    activity_for,
    arv2_research_status_for,
    custom_field_evidence_for,
    custom_fields_for,
    employee_range_label,
    fit_band,
    fit_score_100,
    funding_label,
    headcount_label,
    industry_labels,
    iso_utc,
    last_modified_for,
    location_label,
    owners_for,
    research_evidence_for,
    revenue_label,
    socials,
    website_label,
    website_url,
)
from clue_config import Settings
from clue_core import ClaimId, EntityId, EntityType
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, current_values
from clue_research.compliance import load_workspace_policy
from clue_research.identity import get_account, surviving_id
from clue_storage import StorageBackend


class AccountNotFound(LookupError):
    """No live account with that id is visible in this workspace."""


#: The neutral fields the **contract-v1 detail** renders, read in ONE batched merge. A superset of
#: the v1 *list* row's set (:data:`~clue_api.frontend_read.accounts_list.V1_NEUTRAL_FIELD_KEYS`,
#: imported rather than restated so the two screens can never disagree about the account's chrome)
#: plus the four the detail's rail adds: revenue, founding year, and the two funding facts.
V1_DETAIL_FIELD_KEYS: tuple[str, ...] = (
    *V1_NEUTRAL_FIELD_KEYS,
    "core.annual_revenue",
    "core.founded_year",
    "account.recent_funding",
    "account.total_funding",
)

#: The page the account detail serves. Named so the reader and the evidence route cannot drift.
OVERVIEW_PAGE: Page = "overview"


def founded_label(value: Any) -> str | None:
    """``core.founded_year`` as the year a screen shows, or ``None`` when it is not a year.

    A year is an integer. The claim may arrive as one, as a float that *is* one, or — through the
    D1 lenient writer, which stores what the provider returned rather than what the registry
    declares — as the string ``"2022"``. Anything else (``"founded in the nineties"``, an object)
    yields ``None`` and the label is omitted: an unparseable year is not a year, and printing the
    raw value would put prose in a rail slot that the frontend renders as a date.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return str(int(value.strip()))
        except ValueError:
            return None
    return None


# The one account's own spine row. Not the list's ``_ACCOUNT_PEOPLE`` read: this branch needs the
# two timestamps as well (``createdAt`` is required in contract v1 and the entity model does not
# carry them), and widening a shared statement for one caller is how a batched read for a page
# quietly becomes a wider read for every row of it.
_ACCOUNT_SPINE = text(
    """
    SELECT owner_user_id, created_by_user_id, created_at, updated_at
    FROM account_entity
    WHERE workspace_id = :workspace_id AND id = :entity_id
    """
)


async def read_account_detail(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    display: DisplayPages,
    settings: Settings,
    now: datetime,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
) -> AccountDetailResponseV1:
    """The account detail in **contract v1** — the ARV2 account page and its preview.

    Same account, same resolution rules as :func:`read_account_detail` (``surviving_id``, the
    workspace check, the client-entity exclusion, the same :class:`AccountNotFound`); what differs
    is everything served. The v1 detail is the *screen's* detail: the rail's labels, the account's
    own chrome, the committee card, the generated overview page, and the evidence behind every
    citation on it.

    A merged loser is followed **silently** — the contract has no ``redirectedFrom`` slot, so the
    survivor is simply served rather than a field being invented to announce the redirect.

    Two properties are structural rather than incidental:

    * **the fit and the research status are the primary project's**, exactly as the v1 list row's
      are, because the page has one of each. An account with no membership has no project to
      report a status for and is honestly ``not_started``, never attributed to whichever project
      happened to research it;
    * **the evidence drawer is the union of what the page cites and what the committee card
      shows.** A committee email chip finds its evidence by claim id (ruling R5), so an
      ``emailClaimId`` with no row in ``researchEvidence`` would be a chip that opens onto
      nothing.

    Every source is read in a fixed number of batched statements: a per-member or per-field lookup
    here is what the suite's v1 statement-count guard exists to prevent.
    """
    requested = EntityId(account_id)
    canonical = await surviving_id(conn, requested, EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    if account is None or account.workspace_id != workspace_id or canonical == client_entity_id:
        raise AccountNotFound(str(account_id))

    account_uuid = uuid.UUID(str(canonical))
    scope = WorkspaceScope.for_workspace(workspace_id)
    neutral = await current_values(conn, [canonical], V1_DETAIL_FIELD_KEYS, scope=scope)

    def value_of(field_key: str) -> Any:
        current = neutral.get((canonical, field_key))
        return None if current is None else current.value_json

    scores = await _read_scores(conn, workspace_id=workspace_id, entity_ids=[account_uuid])
    # The v1 *list* row's research read, shared rather than re-written so the table and the page
    # can never report a different status for one account. Its refresh flag is dropped here: the
    # detail contract has no ``researchIsRefreshing`` slot (the Zod schema is the arbiter of that
    # split), and a second query for the status alone is how the two surfaces would start to drift.
    research = await arv2_research_status_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )
    status, _refreshing = research.get(canonical, ("not_started", False))

    spine = (
        await conn.execute(_ACCOUNT_SPINE, {"workspace_id": workspace_id, "entity_id": canonical})
    ).one()
    owner_user_id, created_by_user_id, created_at, updated_at = spine
    owners = await owners_for(
        conn, user_ids=[user_id for user_id in (owner_user_id, created_by_user_id) if user_id]
    )
    custom_fields = await custom_fields_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )
    last_modified = await last_modified_for(
        conn, workspace_id=workspace_id, account_ids=[canonical]
    )

    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    members = await committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical),
        project_id=project_id,
        context_id=context_id,
    )
    contacts = await rail_contacts(conn, workspace_id=workspace_id, members=members, policy=policy)
    committee_rows = await buying_committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical),
        members=members,
        policy=policy,
    )
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="account",
        subject_id=str(canonical),
        page=OVERVIEW_PAGE,
        project_id=project_id,
        context_id=context_id,
    )
    activity = await activity_for(conn, workspace_id=workspace_id, account_id=canonical, now=now)
    # The drawer's ids: what the page cites, then what the committee's email chips point at,
    # deduped in that order (``dict.fromkeys`` is order-preserving) so an id cited by both appears
    # once and the page's own order leads.
    evidence = await research_evidence_for(
        conn,
        workspace_id=workspace_id,
        claim_ids=dict.fromkeys(
            (
                *page.cited_claim_ids,
                *(row.email_claim_id for row in committee_rows if row.email_claim_id),
            )
        ),
    )

    field_evidence = await custom_field_evidence_for(
        conn, workspace_id=workspace_id, subject_id=canonical
    )
    evidence = list({record.claim_id: record for record in [*evidence, *field_evidence]}.values())

    # ``canonical_name`` is NOT NULL on the spine, but a blank one would fail the contract's
    # ``min(1)``; the domain, then the id, keep the page honest and reachable.
    name = str(account.canonical_name or account.primary_domain or account_uuid)
    location = location_label(value_of("core.hq_location"))
    # The account's newest fit whichever project scored it (founder ruling 2026-09-11: a fit is
    # global to the account); the per-project sections below keep the attribution.
    contextual = page.research_quality and page.research_quality.get("qualityState") != "legacy"
    chosen_project = (page.research_quality or {}).get("projectId") or project_id
    candidates = scores.get(account_uuid, ())
    if contextual:
        candidates = tuple(
            s for s in candidates if chosen_project and s.project_id == chosen_project
        )
    fit = account_fit(candidates)
    return AccountDetailResponseV1(
        data=AccountDetailV1(
            id=str(account_uuid),
            name=name,
            # The preview and the page are the same subject; the dummy renders the two slots from
            # different fields, and serving anything but the account's name in one of them would
            # be a second name for one account.
            preview_title=name,
            # The platform's logo route when the account carries a mark-type logo (founder ruling
            # 2026-09-11); null otherwise — never a guessed URL.
            logo_path=account_logo_path(
                account_uuid,
                value_of("core.logo_url"),
                domain=account.primary_domain,
                settings=settings,
            ),
            website_url=website_url(account.primary_domain),
            website_label=website_label(account.primary_domain) or EMPTY_BAND,
            research_status=status,
            research_status_label=RESEARCH_STATUS_LABELS[status],
            owner=owners.get(owner_user_id) if owner_user_id else None,
            created_by=owners.get(created_by_user_id) if created_by_user_id else None,
            industry_labels=tuple(
                industry_labels(value_of("core.industry"), value_of("core.industries_all"))
            ),
            headcount_label=headcount_label(
                as_int(value_of("core.employee_count")),
                employee_range_label(value_of("core.employee_range")),
            ),
            # Required non-empty here (the list row may omit it), so an account with no location
            # says "Unknown" rather than dropping the rail row entirely.
            locations_label=location or EMPTY_BAND,
            revenue_label=revenue_label(
                value_of("core.annual_revenue"), as_str(value_of("core.revenue_band"))
            ),
            founded_label=founded_label(value_of("core.founded_year")),
            funding_label=funding_label(
                value_of("account.recent_funding"), value_of("account.total_funding")
            ),
            fit_score=fit_score_100(fit),
            # Omitted: the band IS the label the header shows, and a second rendering of one score
            # is a second place for the two to disagree.
            fit_score_label=None,
            overall_fit=fit_band(fit, settings=settings),
            created_at=iso_utc(created_at),
            last_modified_at=iso_utc(last_modified.get(canonical, updated_at)),
            socials=tuple(
                socials(value_of("core.company_linkedin_url"), value_of("core.company_twitter_url"))
            ),
            custom_fields=tuple(custom_fields.get(canonical, ())),
            # The four slots the display layer replaced. Served as empty lists, not omitted: the
            # contract requires them, and "this page has none" is the honest answer while the
            # dummy's legacy prose/criteria/insight surfaces have no backend owner (D0 rulings
            # S5/S9). ``overviewDisplay`` is where this account's prose actually lives.
            summary_paragraphs=(),
            business_paragraphs=(),
            header_metadata=(),
            fit_criteria=(),
            insights=(),
            contacts=tuple(contacts),
            activity=tuple(activity),
            research_evidence=tuple(evidence),
            # Always present, even when every section is empty: an all-empty block is still a
            # block, and the frontend renders the page grammar from it.
            overview_display=ResearchDisplayBlock.model_validate(page.display_block),
            buying_committee=tuple(committee_rows),
        )
    )


# --- the route --------------------------------------------------------------------------------


def register_account_detail_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    display: DisplayPages,
    evidence_storage: StorageBackend | None = None,
) -> None:
    """Register ``GET /accounts/{account_id}`` and its evidence route on the `/frontend/v1` router.

    ``display`` is the D3 display seam the composition root shares across every endpoint that
    serves a generated page — one instance, so two screens looking at the same account schedule one
    rewrite between them — and ``settings`` reaches the reader because the fit bands are configured
    thresholds, not code (ruling S3). A ``?contract=`` query parameter is accepted and ignored: it
    selected between the FI-2 and v1 payloads until the FI-2 half was deleted (2026-09-09).
    """

    @router.get("/accounts/{account_id}")
    async def get_account_detail(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> AccountDetailResponseV1:
        async with conn_factory() as conn:
            try:
                return await read_account_detail(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    display=display,
                    settings=settings,
                    now=datetime.now(UTC),
                    project_id=project_id,
                    context_id=context_id,
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "ACCOUNT_NOT_FOUND",
                        "message": "no such account in this workspace",
                    },
                ) from exc

    @router.get("/accounts/{account_id}/evidence/{claim_id}")
    async def get_account_evidence_artifact(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        claim_id: uuid.UUID,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> Response:
        """Stream evidence for stored page citations or scoped custom-field values.

        The authorising set includes the **stored** overview and custom values. ``generate=False``
        is load-bearing: an authorisation check must never be a spend path, so this asks only what
        is already written and neither writes a section nor schedules a rewrite. The account id is
        resolved to its survivor first, so a merged-loser url authorises against the page the
        caller would actually be looking at.
        """

        if evidence_storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EVIDENCE_SERVICE_UNAVAILABLE",
                    "message": "retained evidence is temporarily unavailable",
                },
            )
        async with conn_factory() as conn:
            canonical = await surviving_id(conn, EntityId(account_id), EntityType.ACCOUNT)
            account = await get_account(conn, canonical)
            client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
            if (
                account is None
                or account.workspace_id != workspace_id
                or canonical == client_entity_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            page = await display.page(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_id=str(canonical),
                page=OVERVIEW_PAGE,
                project_id=project_id,
                context_id=context_id,
                generate=False,
            )
            custom_evidence = await custom_field_evidence_for(
                conn, workspace_id=workspace_id, subject_id=canonical
            )
            insights = await display.page(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_id=str(canonical),
                page="insights",
                project_id=project_id,
                context_id=context_id,
                generate=False,
            )
            served_ids = {
                *page.cited_claim_ids,
                *insights.cited_claim_ids,
                *(row.claim_id for row in custom_evidence),
            }
            if str(claim_id) not in served_ids:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            typed_claim_id = ClaimId(claim_id)
            from clue_research.claimstore.quality import inspectable_claims_by_ids

            claims = await inspectable_claims_by_ids(
                conn,
                workspace_id=workspace_id,
                claim_ids=[typed_claim_id],
            )
            claim = claims.get(typed_claim_id)
            if claim is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            artifact = await read_live_artifact(
                conn,
                claim=claim,
                workspace_id=workspace_id,
                storage=evidence_storage,
            )
            if artifact is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EVIDENCE_NOT_FOUND",
                        "message": "no such evidence in this workspace",
                    },
                )
            return evidence_artifact_response(artifact)
