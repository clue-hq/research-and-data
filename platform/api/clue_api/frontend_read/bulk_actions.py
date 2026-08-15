"""Authenticated, durable bulk actions for the FI-2 Account and Contact tables.

The browser sends an explicit finite set of ids from its current page. This module never accepts a
query-shaped "all matching" request, so a header checkbox cannot accidentally target unseen rows.
Every request is idempotent, every item gets a durable outcome, and the actual mutations remain at
their existing seams: ``project_account`` membership and ``ContactEmailLookupService``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import Field, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.account_detail import AccountNotFound
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contact_email_lookup import (
    ContactEmailLookupService,
    ContactEmailLookupView,
    EmailLookupTarget,
    read_contact_email_lookup,
)
from clue_api.frontend_read.contacts import read_account_contacts
from clue_core import EntityId, EntityType, operation_id_from_key
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_research.identity import get_account, get_contacts, surviving_id
from clue_research.membership import ensure_project_accounts

ACCOUNT_BATCH_LIMIT = 100
CONTACT_EMAIL_BATCH_LIMIT = 20
log = get_logger("clue_api.frontend_read.bulk_actions")

BulkOutcome = Literal[
    "accepted",
    "completed",
    "unchanged",
    "not_found",
    "withheld",
    "ineligible",
    "failed_retryable",
    "failed_terminal",
]


class BulkActionCapability(WireModel):
    allowed: bool
    max_items: int


class BulkProjectOption(WireModel):
    id: str
    name: str
    status: Literal["draft", "active"]


class AccountBulkCapabilities(WireModel):
    add_to_project: BulkActionCapability
    add_to_chat: BulkActionCapability
    projects: tuple[BulkProjectOption, ...] = ()


class ContactBulkCapabilities(WireModel):
    lookup_work_emails: BulkActionCapability
    add_to_chat: BulkActionCapability


class AddAccountsToProjectRequest(WireModel):
    account_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=ACCOUNT_BATCH_LIMIT)
    project_id: str = Field(min_length=1, max_length=200)

    @field_validator("account_ids")
    @classmethod
    def _unique_accounts(cls, value: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("accountIds must not contain duplicates")
        return value


class LookupContactEmailsRequest(WireModel):
    contact_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=CONTACT_EMAIL_BATCH_LIMIT)

    @field_validator("contact_ids")
    @classmethod
    def _unique_contacts(cls, value: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("contactIds must not contain duplicates")
        return value


class BulkActionCounts(WireModel):
    requested: int
    completed: int
    unchanged: int
    ineligible: int
    failed: int


class BulkActionItem(WireModel):
    subject_id: uuid.UUID
    outcome: BulkOutcome
    reason_code: str | None = None
    email_lookup: ContactEmailLookupView | None = None


class BulkActionResponse(WireModel):
    operation_id: uuid.UUID
    state: Literal["pending", "completed", "partial", "failed"]
    counts: BulkActionCounts
    items: tuple[BulkActionItem, ...]


_PROJECTS = text(
    """
    SELECT project_id, name, status
    FROM project
    WHERE workspace_id=:workspace_id AND status <> 'archived'
    ORDER BY lower(name), created_at, project_id
    """
)

_PROJECT_EXISTS = text(
    """
    SELECT 1 FROM project
    WHERE workspace_id=:workspace_id AND project_id=:project_id AND status <> 'archived'
    """
)

_ACCOUNT_ELIGIBILITY = text(
    """
    SELECT a.id, (pa.account_entity_id IS NOT NULL) AS already_member
    FROM account_entity a
    LEFT JOIN project_account pa
      ON pa.workspace_id=a.workspace_id
     AND pa.account_entity_id=a.id
     AND pa.project_id=:project_id
    WHERE a.workspace_id=:workspace_id
      AND a.merged_into IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM workspace_client_binding wcb
          WHERE wcb.workspace_id = a.workspace_id
            AND wcb.client_entity_id = a.id
      )
      AND a.id IN :account_ids
    """
).bindparams(bindparam("account_ids", expanding=True, type_=PgUUID(as_uuid=True)))

_INSERT_OPERATION = text(
    """
    INSERT INTO frontend_bulk_action_operation (
        id, workspace_id, action_key, subject_type, idempotency_key, request_sha256,
        request_json, requested_by_user_id, requested_via_membership_id, requested_count
    ) VALUES (
        :id, :workspace_id, :action_key, :subject_type, :idempotency_key, :request_sha256,
        CAST(:request_json AS jsonb), :requested_by_user_id, :requested_via_membership_id,
        :requested_count
    ) ON CONFLICT (workspace_id, idempotency_key) DO NOTHING
    """
)

_READ_OPERATION = text(
    """
    SELECT id, action_key, subject_type, request_sha256, state, requested_count,
           completed_count, unchanged_count, ineligible_count, failed_count
    FROM frontend_bulk_action_operation
    WHERE workspace_id=:workspace_id AND id=:operation_id
    """
)

_INSERT_ITEM = text(
    """
    INSERT INTO frontend_bulk_action_item (
        operation_id, workspace_id, ordinal, subject_id, outcome, reason_code, downstream_id
    ) VALUES (
        :operation_id, :workspace_id, :ordinal, :subject_id, :outcome, :reason_code, :downstream_id
    ) ON CONFLICT (operation_id, subject_id) DO NOTHING
    """
)

_READ_ITEMS = text(
    """
    SELECT ordinal, subject_id, outcome, reason_code, downstream_id
    FROM frontend_bulk_action_item
    WHERE operation_id=:operation_id AND workspace_id=:workspace_id
    ORDER BY ordinal
    """
)

_FINALIZE_OPERATION = text(
    """
    UPDATE frontend_bulk_action_operation
    SET state=:state,
        completed_count=:completed_count,
        unchanged_count=:unchanged_count,
        ineligible_count=:ineligible_count,
        failed_count=:failed_count,
        finalized_at=now()
    WHERE id=:operation_id AND workspace_id=:workspace_id AND state='pending'
    """
)

_CURRENT_EMAIL_LOOKUPS = text(
    """
    SELECT contact_id
    FROM contact_email_lookup
    WHERE workspace_id=:workspace_id
      AND contact_id IN :contact_ids
      AND observation_window=to_char(now(), 'YYYY-MM')
    """
).bindparams(bindparam("contact_ids", expanding=True, type_=PgUUID(as_uuid=True)))


def _canonical_request(payload: Mapping[str, object]) -> tuple[str, str]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return encoded.decode(), hashlib.sha256(encoded).hexdigest()


def _has_permission(request: Request, permission: str, *, allow_local: bool) -> bool:
    principal = principal_from_request(request)
    if principal is not None:
        return permission in principal.permissions
    return allow_local


def _requester(
    request: Request, permission: Literal["project.write", "research.launch"], *, allow_local: bool
) -> tuple[str, str | None, str | None]:
    principal = principal_from_request(request)
    if principal is not None:
        principal.require(permission)
        return principal.user_id, principal.user_id, principal.membership_id
    if allow_local:
        return "local-development-user", None, None
    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "an authenticated session is required"},
    )


async def _start_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    action_key: Literal["add_to_project", "lookup_work_email"],
    subject_type: Literal["account", "contact"],
    idempotency_key: str,
    request_json: str,
    request_sha256: str,
    requested_count: int,
    actor_user_id: str | None,
    membership_id: str | None,
) -> RowMapping:
    operation_id = uuid.UUID(
        str(operation_id_from_key(workspace_id, f"frontend-bulk:{idempotency_key}"))
    )
    # Serialize the first creation/replay decision for this key. The lock is transaction-scoped and
    # carries no user data; it prevents two identical browser retries from both dispatching work.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{workspace_id}:{idempotency_key}"},
    )
    await conn.execute(
        _INSERT_OPERATION,
        {
            "id": operation_id,
            "workspace_id": workspace_id,
            "action_key": action_key,
            "subject_type": subject_type,
            "idempotency_key": idempotency_key,
            "request_sha256": request_sha256,
            "request_json": request_json,
            "requested_by_user_id": actor_user_id,
            "requested_via_membership_id": membership_id,
            "requested_count": requested_count,
        },
    )
    row = (
        (
            await conn.execute(
                _READ_OPERATION, {"workspace_id": workspace_id, "operation_id": operation_id}
            )
        )
        .mappings()
        .one()
    )
    if (
        row["request_sha256"] != request_sha256
        or row["action_key"] != action_key
        or row["subject_type"] != subject_type
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "this idempotency key already names a different bulk action",
            },
        )
    return row


async def _record_item(
    conn: AsyncConnection,
    *,
    operation_id: uuid.UUID,
    workspace_id: str,
    ordinal: int,
    subject_id: uuid.UUID,
    outcome: BulkOutcome,
    reason_code: str | None = None,
    downstream_id: uuid.UUID | None = None,
) -> None:
    await conn.execute(
        _INSERT_ITEM,
        {
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "ordinal": ordinal,
            "subject_id": subject_id,
            "outcome": outcome,
            "reason_code": reason_code,
            "downstream_id": downstream_id,
        },
    )


async def _finalize(conn: AsyncConnection, *, workspace_id: str, operation_id: uuid.UUID) -> None:
    outcomes = [
        str(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT outcome FROM frontend_bulk_action_item "
                    "WHERE operation_id=:operation_id AND workspace_id=:workspace_id"
                ),
                {"operation_id": operation_id, "workspace_id": workspace_id},
            )
        ).scalars()
    ]
    completed = sum(
        value in {"accepted", "completed", "not_found", "withheld"} for value in outcomes
    )
    unchanged = outcomes.count("unchanged")
    ineligible = outcomes.count("ineligible")
    failed = sum(value in {"failed_retryable", "failed_terminal"} for value in outcomes)
    successful = completed + unchanged
    state = "completed" if ineligible + failed == 0 else "partial" if successful else "failed"
    await conn.execute(
        _FINALIZE_OPERATION,
        {
            "operation_id": operation_id,
            "workspace_id": workspace_id,
            "state": state,
            "completed_count": completed,
            "unchanged_count": unchanged,
            "ineligible_count": ineligible,
            "failed_count": failed,
        },
    )


async def _response(
    conn: AsyncConnection, *, workspace_id: str, operation_id: uuid.UUID
) -> BulkActionResponse:
    operation = (
        (
            await conn.execute(
                _READ_OPERATION, {"workspace_id": workspace_id, "operation_id": operation_id}
            )
        )
        .mappings()
        .one()
    )
    rows = (
        (
            await conn.execute(
                _READ_ITEMS, {"workspace_id": workspace_id, "operation_id": operation_id}
            )
        )
        .mappings()
        .all()
    )
    items: list[BulkActionItem] = []
    for row in rows:
        lookup = None
        if row["downstream_id"] is not None:
            lookup = await read_contact_email_lookup(
                conn,
                workspace_id=workspace_id,
                lookup_id=uuid.UUID(str(row["downstream_id"])),
            )
        items.append(
            BulkActionItem(
                subject_id=uuid.UUID(str(row["subject_id"])),
                outcome=str(row["outcome"]),  # type: ignore[arg-type]
                reason_code=row["reason_code"],
                email_lookup=lookup,
            )
        )
    return BulkActionResponse(
        operation_id=uuid.UUID(str(operation["id"])),
        state=str(operation["state"]),  # type: ignore[arg-type]
        counts=BulkActionCounts(
            requested=int(operation["requested_count"]),
            completed=int(operation["completed_count"]),
            unchanged=int(operation["unchanged_count"]),
            ineligible=int(operation["ineligible_count"]),
            failed=int(operation["failed_count"]),
        ),
        items=tuple(items),
    )


def _email_outcome(view: ContactEmailLookupView, *, reused: bool) -> tuple[BulkOutcome, str | None]:
    if reused:
        return "unchanged", None
    if view.state.value == "pending":
        return "accepted", None
    if view.state.value == "available":
        return "completed", None
    if view.state.value == "not_found":
        return "not_found", None
    if view.state.value == "withheld":
        return "withheld", "policy_withheld"
    if view.retryable:
        return "failed_retryable", "provider_retryable"
    return "failed_terminal", "provider_unavailable"


def register_bulk_action_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    contact_email_lookup: ContactEmailLookupService | None,
    allow_local_mutations: bool,
    chat_available: bool,
) -> None:
    """Register capability reads plus the two authenticated table actions."""

    @router.get("/accounts/bulk-capabilities")
    async def account_bulk_capabilities(
        request: Request, workspace_id: WorkspaceDep
    ) -> AccountBulkCapabilities:
        async with conn_factory() as conn:
            projects = tuple(
                BulkProjectOption(id=str(row[0]), name=str(row[1]), status=str(row[2]))  # type: ignore[arg-type]
                for row in (await conn.execute(_PROJECTS, {"workspace_id": workspace_id})).all()
            )
        allowed = _has_permission(request, "project.write", allow_local=allow_local_mutations)
        return AccountBulkCapabilities(
            add_to_project=BulkActionCapability(
                allowed=allowed and bool(projects), max_items=ACCOUNT_BATCH_LIMIT
            ),
            add_to_chat=BulkActionCapability(
                allowed=chat_available
                and _has_permission(request, "thread.write", allow_local=allow_local_mutations),
                max_items=ACCOUNT_BATCH_LIMIT,
            ),
            projects=projects,
        )

    @router.get("/accounts/{account_id}/contacts/bulk-capabilities")
    async def contact_bulk_capabilities(
        request: Request, workspace_id: WorkspaceDep, account_id: uuid.UUID
    ) -> ContactBulkCapabilities:
        # Preserve account-scoped non-disclosure: a foreign/missing account is a 404, not a
        # capability response that reveals anything about the caller's workspace selection.
        async with conn_factory() as conn:
            try:
                await read_account_contacts(conn, workspace_id=workspace_id, account_id=account_id)
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "ACCOUNT_NOT_FOUND", "message": "no such account"},
                ) from exc
        allowed = _has_permission(request, "research.launch", allow_local=allow_local_mutations)
        return ContactBulkCapabilities(
            lookup_work_emails=BulkActionCapability(
                allowed=allowed and contact_email_lookup is not None,
                max_items=CONTACT_EMAIL_BATCH_LIMIT,
            ),
            add_to_chat=BulkActionCapability(
                allowed=chat_available
                and _has_permission(request, "thread.write", allow_local=allow_local_mutations),
                max_items=ACCOUNT_BATCH_LIMIT,
            ),
        )

    @router.post("/accounts/bulk-actions/add-to-project")
    async def add_accounts_to_project(
        request: Request,
        body: AddAccountsToProjectRequest,
        workspace_id: WorkspaceDep,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
    ) -> BulkActionResponse:
        _requested_by, actor_user_id, membership_id = _requester(
            request, "project.write", allow_local=allow_local_mutations
        )
        account_ids = tuple(sorted(body.account_ids, key=str))
        request_json, request_sha256 = _canonical_request(
            {
                "accountIds": [str(value) for value in account_ids],
                "action": "add_to_project",
                "projectId": body.project_id,
            }
        )
        async with conn_factory() as conn:
            operation = await _start_operation(
                conn,
                workspace_id=workspace_id,
                action_key="add_to_project",
                subject_type="account",
                idempotency_key=idempotency_key,
                request_json=request_json,
                request_sha256=request_sha256,
                requested_count=len(account_ids),
                actor_user_id=actor_user_id,
                membership_id=membership_id,
            )
            operation_id = uuid.UUID(str(operation["id"]))
            if operation["state"] != "pending":
                return await _response(conn, workspace_id=workspace_id, operation_id=operation_id)
            project_exists = (
                await conn.execute(
                    _PROJECT_EXISTS,
                    {"workspace_id": workspace_id, "project_id": body.project_id},
                )
            ).scalar_one_or_none()
            if project_exists is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "PROJECT_NOT_FOUND", "message": "no such active project"},
                )
            eligibility_rows = (
                await conn.execute(
                    _ACCOUNT_ELIGIBILITY,
                    {
                        "workspace_id": workspace_id,
                        "project_id": body.project_id,
                        "account_ids": list(account_ids),
                    },
                )
            ).all()
            eligible = {uuid.UUID(str(row[0])) for row in eligibility_rows}
            existing = {uuid.UUID(str(row[0])) for row in eligibility_rows if bool(row[1])}
            inserted = await ensure_project_accounts(
                conn,
                workspace_id=workspace_id,
                project_id=body.project_id,
                account_entity_ids=tuple(eligible),
                added_via="manual",
            )
            for ordinal, account_id in enumerate(account_ids):
                if account_id not in eligible:
                    await _record_item(
                        conn,
                        operation_id=operation_id,
                        workspace_id=workspace_id,
                        ordinal=ordinal,
                        subject_id=account_id,
                        outcome="ineligible",
                        reason_code="account_not_found",
                    )
                elif account_id in existing or account_id not in inserted:
                    await _record_item(
                        conn,
                        operation_id=operation_id,
                        workspace_id=workspace_id,
                        ordinal=ordinal,
                        subject_id=account_id,
                        outcome="unchanged",
                    )
                else:
                    await _record_item(
                        conn,
                        operation_id=operation_id,
                        workspace_id=workspace_id,
                        ordinal=ordinal,
                        subject_id=account_id,
                        outcome="completed",
                    )
            await _finalize(conn, workspace_id=workspace_id, operation_id=operation_id)
            return await _response(conn, workspace_id=workspace_id, operation_id=operation_id)

    @router.post("/accounts/{account_id}/contacts/bulk-actions/email-lookup")
    async def lookup_contact_emails(
        request: Request,
        body: LookupContactEmailsRequest,
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
    ) -> BulkActionResponse:
        if contact_email_lookup is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EMAIL_LOOKUP_UNAVAILABLE",
                    "message": "email enrichment is not configured for this environment",
                },
            )
        requested_by, actor_user_id, membership_id = _requester(
            request, "research.launch", allow_local=allow_local_mutations
        )
        contact_ids = tuple(sorted(body.contact_ids, key=str))
        request_json, request_sha256 = _canonical_request(
            {
                "accountId": str(account_id),
                "action": "lookup_work_email",
                "contactIds": [str(value) for value in contact_ids],
            }
        )
        async with conn_factory() as conn:
            operation = await _start_operation(
                conn,
                workspace_id=workspace_id,
                action_key="lookup_work_email",
                subject_type="contact",
                idempotency_key=idempotency_key,
                request_json=request_json,
                request_sha256=request_sha256,
                requested_count=len(contact_ids),
                actor_user_id=actor_user_id,
                membership_id=membership_id,
            )
            operation_id = uuid.UUID(str(operation["id"]))
            if operation["state"] != "pending":
                return await _response(conn, workspace_id=workspace_id, operation_id=operation_id)
            try:
                committee = await read_account_contacts(
                    conn, workspace_id=workspace_id, account_id=account_id
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "ACCOUNT_NOT_FOUND", "message": "no such account"},
                ) from exc
            canonical_account_id = await surviving_id(
                conn, EntityId(account_id), EntityType.ACCOUNT
            )
            account = await get_account(conn, canonical_account_id)
            committee_ids = {uuid.UUID(str(row.id)) for row in committee.data}
            entities = await get_contacts(
                conn, tuple(EntityId(value) for value in contact_ids if value in committee_ids)
            )
            prior = {
                uuid.UUID(str(value))
                for value in (
                    await conn.execute(
                        _CURRENT_EMAIL_LOOKUPS,
                        {"workspace_id": workspace_id, "contact_ids": list(contact_ids)},
                    )
                ).scalars()
            }
            existing_items = {
                uuid.UUID(str(value))
                for value in (
                    await conn.execute(
                        text(
                            "SELECT subject_id FROM frontend_bulk_action_item "
                            "WHERE operation_id=:operation_id AND workspace_id=:workspace_id"
                        ),
                        {"operation_id": operation_id, "workspace_id": workspace_id},
                    )
                ).scalars()
            }

        for ordinal, contact_id in enumerate(contact_ids):
            if contact_id in existing_items:
                continue
            entity = entities.get(EntityId(contact_id))
            if contact_id not in committee_ids:
                async with conn_factory() as conn:
                    await _record_item(
                        conn,
                        operation_id=operation_id,
                        workspace_id=workspace_id,
                        ordinal=ordinal,
                        subject_id=contact_id,
                        outcome="ineligible",
                        reason_code="contact_not_on_committee",
                    )
                continue
            if account is None or entity is None or not entity.full_name or not entity.linkedin_url:
                async with conn_factory() as conn:
                    await _record_item(
                        conn,
                        operation_id=operation_id,
                        workspace_id=workspace_id,
                        ordinal=ordinal,
                        subject_id=contact_id,
                        outcome="ineligible",
                        reason_code="identity_incomplete",
                    )
                continue
            target = EmailLookupTarget(
                workspace_id=workspace_id,
                account_id=uuid.UUID(str(account.id)),
                contact_id=uuid.UUID(str(entity.id)),
                full_name=entity.full_name,
                linkedin_url=entity.linkedin_url,
                account_name=account.canonical_name,
                primary_domain=account.primary_domain,
            )
            try:
                view = await contact_email_lookup.start(target=target, requested_by=requested_by)
                outcome, reason = _email_outcome(view, reused=contact_id in prior)
                downstream_id = view.lookup_id
            except PermissionError:
                outcome, reason, downstream_id = "withheld", "policy_withheld", None
            except Exception:  # provider/internal detail is never copied to the browser or ledger
                log.exception(
                    "frontend_bulk.email_lookup_failed",
                    workspace_id=workspace_id,
                    operation_id=str(operation_id),
                    contact_id=str(contact_id),
                )
                outcome, reason, downstream_id = (
                    "failed_retryable",
                    "email_service_error",
                    None,
                )
            async with conn_factory() as conn:
                await _record_item(
                    conn,
                    operation_id=operation_id,
                    workspace_id=workspace_id,
                    ordinal=ordinal,
                    subject_id=contact_id,
                    outcome=outcome,
                    reason_code=reason,
                    downstream_id=downstream_id,
                )

        async with conn_factory() as conn:
            await _finalize(conn, workspace_id=workspace_id, operation_id=operation_id)
            return await _response(conn, workspace_id=workspace_id, operation_id=operation_id)


__all__ = [
    "ACCOUNT_BATCH_LIMIT",
    "CONTACT_EMAIL_BATCH_LIMIT",
    "AccountBulkCapabilities",
    "BulkActionResponse",
    "ContactBulkCapabilities",
    "register_bulk_action_routes",
]
