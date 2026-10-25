"""What Settings → Integrations shows about the workspace's CRM (R-15.1–R-15.3).

One read model for ``GET /frontend/v1/crm/integration``: the connection, the state of Clue's
research setup in the CRM (Clue's own fields, R-13.x) with its four user-facing preparations, the
standing permissions any member may revoke, the overwrites setting, and the project a new
"Ask Clue" chat opens in. Research setup is never run from the page (R-15.2): the page links to
the pending setup card, or opens a chat with a suggested message.

Every name a person reads is a label — Clue's field labels, the CRM's own field label from the
card that granted a permission — never a CRM API name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.crm.clue_fields import (
    CLUE_FIELDS,
    ClueField,
    ClueFieldsState,
    clue_field_written,
    clue_fields_set_up,
    clue_fields_state,
)
from clue_api.crm.composio_gateway import CrmProvider
from clue_api.crm.connections import CrmConnection, connection_overwrites, latest_connection
from clue_api.crm.writes import FULLY_AUTOMATIC, Grant, grant_scope_key, live_grants, object_noun

__all__ = ["ResearchState", "integration_view", "research_view", "settings_grant_description"]

ResearchState = Literal[
    "approval_needed",
    "preparing",
    "ready",
    "needs_attention",
    "permission_needed",
    "couldnt_finish",
    "not_connected",
]
ItemStatus = Literal["created", "pending", "permission_needed", "missing"]

_SETUP_KIND = "clue_fields_setup"


@dataclass(frozen=True)
class _Item:
    key: str
    title: str
    #: ``{record}`` is the CRM's name for a company record; ``{fit_label}`` Clue's fit field.
    description: str
    object: Literal["company", "contact"]
    #: The Clue field's key (:attr:`ClueField.key`, the same on both CRMs).
    clue_key: str


#: The four preparations a person reads about, in the page's order, each one Clue field.
_ITEMS: tuple[_Item, ...] = (
    _Item(
        "company_research_links",
        "Company research links",
        "A link on each {record} to its research in Clue.",
        "company",
        "clue_research_link",
    ),
    _Item(
        "contact_profile_links",
        "Contact profile links",
        "A link on each contact record to the person’s Clue profile.",
        "contact",
        "clue_contact_link",
    ),
    _Item(
        "contact_buying_roles",
        "Contacts’ buying roles",
        "The person’s role in the buying decision, saved on their contact record.",
        "contact",
        "clue_committee_role",
    ),
    _Item(
        "company_fit",
        "Company fit",
        "High, Medium, or Low fit, saved in the “{fit_label}” field.",
        "company",
        "clue_fit_level",
    ),
)

_RECORD: Mapping[CrmProvider, str] = {"hubspot": "company record", "salesforce": "account record"}
#: How a reason names the records of Clue's object.
_RECORD_WORD: Mapping[CrmProvider, Mapping[str, str]] = {
    "hubspot": {"company": "company", "contact": "contact"},
    "salesforce": {"company": "account", "contact": "contact"},
}
_CRM_NAMES: Mapping[CrmProvider, str] = {"hubspot": "HubSpot", "salesforce": "Salesforce"}

#: A CRM refusal that names a missing permission: HubSpot ``MISSING_SCOPES`` or an HTTP 403,
#: Salesforce ``INSUFFICIENT_ACCESS`` (and ``…_OR_READONLY``). Matched in the CRM's own answer and
#: in the stored sentence; the word "permission" only in the CRM's answer, since Clue's own step
#: names ("the permission set …") say it too.
_PERMISSION_CODES = re.compile(r"missing_scopes|insufficient_access|\b403\b", re.IGNORECASE)
_PERMISSION_WORD = re.compile(r"permission", re.IGNORECASE)


def _clue_field(provider: CrmProvider, item: _Item) -> ClueField:
    return next(
        f for f in CLUE_FIELDS[provider] if f.object == item.object and f.key == item.clue_key
    )


def _field_steps(field: ClueField) -> tuple[str, ...]:
    """The setup steps (``clue_fields_setup``) that make or open up ``field``."""
    return (f'the field "{field.label}" on {field.crm_object}', f"access to {field.qualified_name}")


def _json(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _failed_step(write: Any) -> str | None:
    response = _json(write.crm_response)
    steps = response.get("steps") if isinstance(response, dict) else None
    failed = [
        s.get("step") for s in steps or () if isinstance(s, dict) and s.get("result") == "failed"
    ]
    return str(failed[-1]) if failed else None


def _names_permission(write: Any) -> bool:
    response = _json(write.crm_response)
    answer = response.get("crm_answer") if isinstance(response, dict) else None
    answer_text = answer if isinstance(answer, str) else json.dumps(answer, default=str)
    message = write.crm_message or ""
    return (
        write.failure_kind == "permission"
        or bool(_PERMISSION_CODES.search(message))
        or bool(_PERMISSION_CODES.search(answer_text))
        or bool(_PERMISSION_WORD.search(answer_text))
    )


async def _setup_writes(conn: AsyncConnection, connection_id: Any) -> list[Any]:
    """The connection's setup changes, newest card first."""
    rows = await conn.execute(
        text(
            "SELECT w.status, w.failure_kind, w.crm_message, w.crm_response, "
            "p.status AS proposal_status, p.project_id, p.thread_id "
            "FROM crm_write w JOIN crm_write_proposal p ON p.proposal_id = w.proposal_id "
            "WHERE w.connection_id = :c AND w.kind = :kind "
            "ORDER BY p.created_at DESC, p.proposal_id DESC"
        ),
        {"c": connection_id, "kind": _SETUP_KIND},
    )
    return list(rows.all())


def _items(
    provider: CrmProvider,
    state: ClueFieldsState | None,
    refused_step: str | None,
) -> list[dict[str, str]]:
    created = set(state.created_names) if state is not None else set()
    gone = set(state.gone_names) if state is not None else set()
    fit_label = _clue_field(provider, _ITEMS[3]).label
    items = []
    for item in _ITEMS:
        field = _clue_field(provider, item)
        status: ItemStatus
        if field.qualified_name in gone:
            status = "missing"
        elif field.qualified_name in created:
            status = "created"
        elif refused_step is not None and refused_step in _field_steps(field):
            status = "permission_needed"
        else:
            status = "pending"
        items.append(
            {
                "key": item.key,
                "title": item.title,
                "description": item.description.format(
                    record=_RECORD[provider], fit_label=fit_label
                ),
                "status": status,
            }
        )
    return items


def _label_of(provider: CrmProvider, qualified_name: str) -> str | None:
    return next(
        (f.label for f in CLUE_FIELDS[provider] if f.qualified_name == qualified_name), None
    )


async def research_view(conn: AsyncConnection, connection: CrmConnection | None) -> dict[str, Any]:
    """The research setup's state for Settings (R-15.2), from the registry and the setup cards."""
    provider: CrmProvider = "hubspot" if connection is None else connection.provider
    if connection is None or connection.status == "disconnected":
        return {
            "state": "not_connected",
            "failedField": None,
            "reason": None,
            "reviewChat": None,
            "items": _items(provider, None, None),
        }
    state = await clue_fields_state(conn, connection_id=connection.connection_id)
    writes = await _setup_writes(conn, connection.connection_id)
    pending = next((w for w in writes if w.proposal_status == "awaiting_permission"), None)
    review = (
        None
        if pending is None
        else {"projectId": pending.project_id, "threadId": pending.thread_id}
    )
    latest = writes[0] if writes else None

    research_state: ResearchState
    failed_field: str | None = None
    reason: str | None = None
    refused_step: str | None = None
    crm = _CRM_NAMES[provider]
    # A gone field Clue no longer sets up (the test CRMs' old "Clue tier") is not a missing field.
    gone_labels = (
        [label for name in state.gone_names if (label := _label_of(provider, name))]
        if state is not None
        else []
    )
    if clue_fields_set_up(state) or _set_up_but_for_old_fields(state, gone_labels):
        research_state = "ready"
    # The card is allowed (queued/sending) a moment before its change is: both read Preparing.
    elif any(
        w.status in ("queued", "sending") or w.proposal_status in ("queued", "sending")
        for w in writes
    ):
        research_state = "preparing"
    elif gone_labels:
        research_state = "needs_attention"
        # The first missing preparation in page order, so the page's title and its "Restore"
        # message name the same field; a gone field outside the four falls back to the first.
        gone = set(state.gone_names) if state is not None else set()
        failed_field = next(
            (
                field.label
                for item in _ITEMS
                if (field := _clue_field(provider, item)).qualified_name in gone
            ),
            gone_labels[0],
        )
        reason = f"Clue’s field “{failed_field}” was deleted in {crm}."
    elif latest is not None and latest.proposal_status == "awaiting_permission":
        research_state = "approval_needed"
    elif (latest is not None and latest.status == "failed") or (
        state is not None and state.status == "partial"
    ):
        failed = next((w for w in writes if w.status == "failed"), None)
        if failed is not None and _names_permission(failed):
            research_state = "permission_needed"
            refused_step = _failed_step(failed)
            records = _refused_records(provider, refused_step)
            reason = f"The connected {crm} user doesn’t have permission to create fields on " + (
                "these records." if records is None else f"{records} records."
            )
        else:
            research_state = "couldnt_finish"
            reason = f"{crm} stopped part of the setup. Clue can retry the remaining steps."
    else:
        research_state = "approval_needed"
    return {
        "state": research_state,
        "failedField": failed_field,
        "reason": reason,
        # Only an unanswered card is reviewed; any other state opens a new chat (R-15.2).
        "reviewChat": review if research_state == "approval_needed" else None,
        "items": _items(provider, state, refused_step),
    }


def _set_up_but_for_old_fields(state: ClueFieldsState | None, gone_labels: list[str]) -> bool:
    """A setup marked gone only for a field Clue no longer sets up, with every current field
    created: as good as ready."""
    return (
        state is not None
        and state.status == "gone"
        and not gone_labels
        and all(f.qualified_name in state.created_names for f in CLUE_FIELDS[state.provider])
    )


def _refused_records(provider: CrmProvider, step: str | None) -> str | None:
    """The records ("company", "account", "contact") whose fields the refused step was making;
    ``None`` when the step names none (e.g. Salesforce's permission set)."""
    if step is None:
        return None
    for field in CLUE_FIELDS[provider]:
        if step in _field_steps(field):
            return _RECORD_WORD[provider][field.object]
    for field in CLUE_FIELDS[provider]:
        if step.endswith(f" on {field.crm_object}"):
            return _RECORD_WORD[provider][field.object]
    return None


async def _field_labels(
    conn: AsyncConnection, connection: CrmConnection, grants: Sequence[Grant]
) -> dict[UUID, str]:
    """The label each field grant's field is shown by: Clue's own label for Clue's fields, else
    the CRM's label the newest card that offered the permission showed (one query for all);
    never the CRM's API name. A field with neither is left out."""
    labels: dict[UUID, str] = {}
    asked: dict[str, list[UUID]] = {}
    for grant in grants:
        if grant.scope_kind != "field":
            continue
        clue = clue_field_written(connection.provider, str(grant.object), str(grant.field))
        if clue is not None:
            labels[grant.grant_id] = clue.label
        else:
            asked.setdefault(grant_scope_key(grant), []).append(grant.grant_id)
    if not asked:
        return labels
    rows = await conn.execute(
        text(
            "SELECT DISTINCT ON (grp ->> 'scope_key') grp ->> 'scope_key' AS scope, "
            "grp ->> 'field_label' AS label FROM crm_write_proposal p "
            "JOIN agent_gate a ON a.gate_id = p.gate_id "
            "CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN "
            "jsonb_typeof(a.subject_snapshot -> 'groups') = 'array' "
            "THEN a.subject_snapshot -> 'groups' ELSE '[]'::jsonb END) grp "
            "WHERE p.connection_id = :c AND grp ->> 'scope_key' = ANY(:scopes) "
            "AND coalesce(grp ->> 'field_label', '') <> '' "
            "ORDER BY grp ->> 'scope_key', p.created_at DESC"
        ),
        {"c": connection.connection_id, "scopes": list(asked)},
    )
    for row in rows:
        for grant_id in asked[row.scope]:
            labels[grant_id] = str(row.label)
    return labels


def settings_grant_description(provider: CrmProvider, grant: Grant, label: str | None) -> str:
    """How Settings names a standing permission (the Figma design's imperative wording; the chat
    card and the agent tool keep theirs). Never a CRM API name."""
    if grant.scope_kind == FULLY_AUTOMATIC:
        return "Always allow every change Clue proposes"
    if grant.scope_kind == "field":
        return f"Always set {label or 'a field'} on {object_noun(str(grant.object), 2)}"
    kind = grant.kind
    if kind == "list_create":
        return (
            "Always create Clue lists" if provider == "hubspot" else "Always create Clue campaigns"
        )
    if kind == "list_membership":
        return "Always add records to Clue lists and campaigns"
    if kind == "list_removal":
        return "Always remove records from Clue lists and campaigns"
    if kind == "create_contact":
        return "Always create contacts"
    if kind == "create_company":
        return "Always create companies" if provider == "hubspot" else "Always create accounts"
    if kind == "link_duplicate":
        return "Always mark possible duplicates"
    return "Always allow these changes"


async def _permissions(conn: AsyncConnection, connection: CrmConnection) -> list[dict[str, Any]]:
    grants = await live_grants(conn, connection_id=connection.connection_id)
    if not grants:
        return []
    rows = await conn.execute(
        text(
            "SELECT g.grant_id, g.granted_at, u.display_name FROM crm_write_grant g "
            "LEFT JOIN platform_user u ON u.user_id = g.granted_by_user_id "
            "WHERE g.grant_id = ANY(:ids)"
        ),
        {"ids": [g.grant_id for g in grants]},
    )
    by_id = {row.grant_id: row for row in rows}
    labels = await _field_labels(conn, connection, grants)
    shown = []
    for grant in grants:
        row = by_id[grant.grant_id]
        shown.append(
            {
                "grantId": str(grant.grant_id),
                "description": settings_grant_description(
                    connection.provider, grant, labels.get(grant.grant_id)
                ),
                "grantedByName": row.display_name,
                "grantedAt": row.granted_at.isoformat(),
            }
        )
    return shown


def _account_label(connection: CrmConnection) -> str:
    if connection.provider == "hubspot":
        external = connection.external_account_id
        return "HubSpot portal" if not external else f"Portal {external}"
    return connection.external_account_name or "Salesforce organization"


async def _ask_clue_project(conn: AsyncConnection, workspace_id: str) -> str | None:
    """Where "Ask Clue" opens a new chat (R-15.2): the project of the workspace's latest chat
    connect request when it is still open for work, else the most recently active project."""
    connected_in = await conn.scalar(
        text(
            "SELECT p.project_id FROM crm_connect_request r "
            "JOIN project p ON p.project_id = r.project_id AND p.workspace_id = r.workspace_id "
            "WHERE r.workspace_id = :ws AND r.project_id IS NOT NULL "
            "AND p.archived_at IS NULL AND p.kind = 'marketing' "
            "AND r.created_at = (SELECT max(created_at) FROM crm_connect_request "
            "WHERE workspace_id = :ws AND project_id IS NOT NULL) LIMIT 1"
        ),
        {"ws": workspace_id},
    )
    if connected_in is not None:
        return str(connected_in)
    recent = await conn.scalar(
        text(
            "SELECT p.project_id FROM project p WHERE p.workspace_id = :ws "
            "AND p.archived_at IS NULL AND p.kind = 'marketing' "
            "ORDER BY GREATEST(p.updated_at, coalesce((SELECT max(t.updated_at) "
            "FROM agent_thread t WHERE t.project_id = p.project_id "
            "AND t.workspace_id = p.workspace_id), p.updated_at)) DESC, p.project_id DESC "
            "LIMIT 1"
        ),
        {"ws": workspace_id},
    )
    return None if recent is None else str(recent)


async def integration_view(
    conn: AsyncConnection, *, workspace_id: str, can_manage: bool
) -> dict[str, Any]:
    """``GET /crm/integration``: everything Settings → Integrations shows (R-15.1)."""
    connection = await latest_connection(conn, workspace_id=workspace_id)
    shown: dict[str, Any] | None = None
    permissions: Sequence[dict[str, Any]] = []
    overwrites = "ask"
    if connection is not None:
        name = await conn.scalar(
            text("SELECT display_name FROM platform_user WHERE user_id = :id"),
            {"id": connection.connected_by_user_id},
        )
        shown = {
            "provider": connection.provider,
            "status": connection.status,
            "accountLabel": _account_label(connection),
            "connectedByName": name,
            "connectedAt": connection.connected_at.isoformat(),
        }
        if connection.status != "disconnected":
            permissions = await _permissions(conn, connection)
            overwrites = await connection_overwrites(conn, connection_id=connection.connection_id)
    return {
        "connection": shown,
        "canManage": can_manage,
        "research": await research_view(conn, connection),
        "permissions": list(permissions),
        "overwrites": overwrites,
        "askClueProjectId": await _ask_clue_project(conn, workspace_id),
    }
