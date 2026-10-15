"""Product-change notices in a project's chat (spec 2026-10-15 product management §7).

A merge or removal moves every project whose product set used an affected product, and records
what it did in ``product_change_project``. Those rows are the project's notices: one line each,
shown above the chat until the person dismisses it (per person), for 30 days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.product_management import describe_change
from clue_core import decode_jsonb
from clue_db import ConnFactory

__all__ = ["register_product_notice_routes"]

LOCAL_USER_ID = "local-development-user"
NOTICE_WINDOW = timedelta(days=30)

_OUTCOME_TAIL = {
    "updated": "",
    "restored": "",
    "needs_choice": " This project had no other product, so it keeps its old one for now. "
    "Choose its products in chat.",
    "left_as_is": " This project's products were changed since, so they were left as they are.",
}


class ProductNoticeWire(WireModel):
    change_id: str
    text: str
    outcome: str
    created_at: str


class ProductNoticesWire(WireModel):
    notices: list[ProductNoticeWire]


def notice_text(kind: str, details: dict[str, object], outcome: str, when: datetime) -> str:
    return (
        f"Products changed on {when:%d %b}: {describe_change(kind, details)}."
        f"{_OUTCOME_TAIL.get(outcome, '')}"
    )


def register_product_notice_routes(
    router: APIRouter, *, conn_factory: ConnFactory, allow_local_mutations: bool = False
) -> None:
    def reader(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            return principal.user_id
        if allow_local_mutations:
            return LOCAL_USER_ID
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
        )

    @router.get("/projects/{project_id}/product-notices", response_model=ProductNoticesWire)
    async def get_product_notices(
        request: Request, workspace_id: WorkspaceDep, project_id: str
    ) -> ProductNoticesWire:
        user_id = reader(request)
        async with conn_factory() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.change_id, c.kind, c.details, p.outcome, p.created_at "
                    "FROM product_change_project p "
                    "JOIN product_change c ON c.change_id = p.change_id "
                    "WHERE p.workspace_id = :ws AND p.project_id = :project "
                    "AND p.created_at >= :since "
                    "AND NOT EXISTS (SELECT 1 FROM product_change_notice_dismissal d "
                    "  WHERE d.change_id = p.change_id AND d.project_id = p.project_id "
                    "  AND d.user_id = :user) "
                    "ORDER BY p.created_at DESC LIMIT 10"
                ),
                {
                    "ws": workspace_id,
                    "project": project_id,
                    "since": datetime.now(UTC) - NOTICE_WINDOW,
                    "user": user_id,
                },
            )
            notices = [
                ProductNoticeWire(
                    change_id=str(row["change_id"]),
                    text=notice_text(
                        str(row["kind"]),
                        dict(decode_jsonb(row["details"]) or {}),
                        str(row["outcome"]),
                        row["created_at"],
                    ),
                    outcome=str(row["outcome"]),
                    created_at=row["created_at"].astimezone(UTC).isoformat().replace("+00:00", "Z"),
                )
                for row in rows.mappings().all()
            ]
        return ProductNoticesWire(notices=notices)

    @router.post("/projects/{project_id}/product-notices/{change_id}/dismiss", status_code=204)
    async def dismiss_product_notice(
        request: Request, workspace_id: WorkspaceDep, project_id: str, change_id: UUID
    ) -> None:
        user_id = reader(request)
        async with conn_factory() as conn:
            found = await conn.scalar(
                text(
                    "SELECT 1 FROM product_change_project WHERE workspace_id = :ws "
                    "AND project_id = :project AND change_id = :change"
                ),
                {"ws": workspace_id, "project": project_id, "change": change_id},
            )
            if not found:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOTICE_NOT_FOUND", "message": "No such notice."},
                )
            if user_id == LOCAL_USER_ID:
                await conn.execute(
                    text(
                        "INSERT INTO platform_user (user_id, display_name) VALUES (:id, 'Local') "
                        "ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"id": user_id},
                )
            await conn.execute(
                text(
                    "INSERT INTO product_change_notice_dismissal (change_id, project_id, user_id) "
                    "VALUES (:change, :project, :user) ON CONFLICT DO NOTHING"
                ),
                {"change": change_id, "project": project_id, "user": user_id},
            )
