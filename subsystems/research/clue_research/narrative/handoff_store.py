"""The ``account_handoff`` materialization — write-on-assembly, recompute-on-supersede (M12.2).

``assemble`` (``narrative.handoff``) is a *pure read* of the claim store; this module caches its
result so M12.3 serves a stable object with a precomputed provenance index, Postgres stays the only
source of truth, and a re-assembly after a claim is superseded simply replaces the row (overview §3
recommended persistence; AC8). The whole :class:`~clue_research.narrative.handoff.AssembledHandoff`
(the frozen ``AccountHandoff`` contract object + the M12.2 extras) is stored as a JSONB ``payload``;
the scope key columns
``(workspace_id, account_entity_id, icp_spec_version, icp_key, product_id)`` make a client's view
fetchable, product-exact, and tenant-isolated (substrate §2 — the same public account researched
by two clients keeps two handoffs).

This is a *read-projection* of the claim store, never a write-back path (conventions §6 / substrate
§5c): the only writer is the assembler caching its own read.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, ProjectRunId, decode_jsonb
from clue_research.narrative.handoff import AssembledHandoff


class LegacyHandoffErasedSubjectError(ValueError):
    """A legacy copied-body write attempted to reintroduce an erased contact."""


def _decode_payload(raw: object) -> AssembledHandoff:
    """Decode an ``account_handoff.payload`` column (asyncpg returns jsonb already decoded; a raw
    ``str`` / ``bytes`` is parsed defensively through ``core.decode_jsonb``) into an
    :class:`AssembledHandoff`."""
    return AssembledHandoff.model_validate(decode_jsonb(raw))


async def write_handoff(
    conn: AsyncConnection,
    assembled: AssembledHandoff,
    *,
    workspace_id: str,
    icp_key: str = "",
    tier: str | None = None,
    product_id: str | None = None,
) -> None:
    """Materialise ``assembled`` for ``(workspace_id, icp_key)`` (UPSERT on the ``(workspace_id,
    account_entity_id, icp_spec_version, icp_key)`` scope key — a re-assembly after supersession
    replaces the payload + ``assembled_at``, never duplicating). ``icp_key`` is the ICP segment
    (D5: ``icp_spec_version`` restarts at 1 per ``icp_key``, so two segments must not clobber each
    other's materialised handoff); it defaults to ``""`` for a single-segment account. ``tier`` is
    the account's research tier (M6 two-pass), stamped by the emit path so the list endpoint can
    filter "by tier" (spec §M12.3); ``None`` when materialised outside the emit path. The full
    ``AssembledHandoff`` is stored as JSONB so the serve path reconstructs it without re-reading the
    claim store."""
    h = assembled.handoff
    committee_contact_ids = tuple(member.contact_entity_id for member in h.committee)
    claim_ids = tuple(h.provenance_index)
    reached_rows: Sequence[Row[Any]] = ()
    if claim_ids:
        reached_rows = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT c.entity_id, c.entity_type,
                           ce.account_entity_id AS parent_account_id
                    FROM claim c
                    LEFT JOIN contact_entity ce
                      ON c.entity_type = 'contact' AND ce.id = c.entity_id
                    LEFT JOIN account_entity ae
                      ON c.entity_type = 'account' AND ae.id = c.entity_id
                    WHERE c.id = ANY(CAST(:claim_ids AS uuid[]))
                      AND (
                          c.reuse_scope = 'public_footprint'
                          OR c.workspace_id = :workspace_id
                      )
                      AND (
                          (c.entity_type = 'contact' AND ce.workspace_id = :workspace_id)
                          OR
                          (c.entity_type = 'account' AND ae.workspace_id = :workspace_id)
                      )
                    ORDER BY c.entity_type, c.entity_id
                    """
                ),
                {"claim_ids": list(claim_ids), "workspace_id": workspace_id},
            )
        ).all()
    contact_ids = tuple(
        {
            *committee_contact_ids,
            *(row[0] for row in reached_rows if str(row[1]) == "contact"),
        }
    )
    if contact_ids:
        erased = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT contact_entity_id
                    FROM dsar_tombstone
                    WHERE workspace_id = :workspace_id
                      AND contact_entity_id = ANY(CAST(:contact_ids AS uuid[]))
                    LIMIT 1
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "contact_ids": [str(value) for value in contact_ids],
                },
            )
        ).first()
        if erased is not None:
            raise LegacyHandoffErasedSubjectError(
                "legacy account_handoff body would reintroduce an erased reachable contact; "
                "compose a reference-only C7 research-view receipt instead"
            )
    payload = assembled.model_dump(mode="json")
    row = (
        await conn.execute(
            text(
                """
            INSERT INTO account_handoff
                (workspace_id, account_entity_id, icp_spec_version, icp_key, product_id,
                 project_run_id,
                 assembled_at, tier, payload)
            VALUES
                (:workspace_id, :account_entity_id, :icp_spec_version, :icp_key, :product_id,
                 :project_run_id,
                 :assembled_at, :tier, CAST(:payload AS jsonb))
            ON CONFLICT (
                workspace_id, account_entity_id, icp_spec_version, icp_key, product_id
            ) DO UPDATE SET
                project_run_id = EXCLUDED.project_run_id,
                assembled_at    = EXCLUDED.assembled_at,
                tier            = EXCLUDED.tier,
                payload         = EXCLUDED.payload,
                legacy_payload_purged_at = NULL
            RETURNING id
            """
            ),
            {
                "workspace_id": workspace_id,
                "account_entity_id": str(h.account_entity_id),
                "icp_spec_version": h.icp_spec_version,
                "icp_key": icp_key,
                "product_id": product_id or "",
                "project_run_id": str(h.project_run_id) if h.project_run_id is not None else None,
                "assembled_at": h.assembled_at,
                "tier": tier,
                "payload": json.dumps(payload),
            },
        )
    ).first()
    if row is None:  # pragma: no cover - INSERT/UPSERT always returns the materialized row
        raise RuntimeError("account_handoff write did not return its row identity")
    handoff_id = row[0]
    await conn.execute(
        text("DELETE FROM account_handoff_subject WHERE account_handoff_id = :handoff_id"),
        {"handoff_id": handoff_id},
    )
    await conn.execute(
        text(
            """
            INSERT INTO account_handoff_subject (
                account_handoff_id, subject_entity_id, subject_entity_type,
                parent_account_entity_id, relation
            ) VALUES (
                :handoff_id, :subject_entity_id, 'account', NULL, 'view_subject'
            )
            """
        ),
        {"handoff_id": handoff_id, "subject_entity_id": str(h.account_entity_id)},
    )
    for contact_id in sorted(set(committee_contact_ids), key=str):
        await conn.execute(
            text(
                """
                INSERT INTO account_handoff_subject (
                    account_handoff_id, subject_entity_id, subject_entity_type,
                    parent_account_entity_id, relation
                ) VALUES (
                    :handoff_id, :subject_entity_id, 'contact', :parent_account_entity_id,
                    'committee_member'
                )
                """
            ),
            {
                "handoff_id": handoff_id,
                "subject_entity_id": str(contact_id),
                "parent_account_entity_id": str(h.account_entity_id),
            },
        )
    for entity_id, entity_type, parent_account_id in reached_rows:
        await conn.execute(
            text(
                """
                INSERT INTO account_handoff_subject (
                    account_handoff_id, subject_entity_id, subject_entity_type,
                    parent_account_entity_id, relation
                ) VALUES (
                    :handoff_id, :subject_entity_id, CAST(:subject_entity_type AS entity_type),
                    :parent_account_entity_id, 'claim_reachable'
                )
                ON CONFLICT (account_handoff_id, subject_entity_id, relation) DO NOTHING
                """
            ),
            {
                "handoff_id": handoff_id,
                "subject_entity_id": str(entity_id),
                "subject_entity_type": str(entity_type),
                "parent_account_entity_id": (
                    str(parent_account_id) if parent_account_id is not None else None
                ),
            },
        )


async def read_handoff(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: EntityId,
    icp_spec_version: int,
    icp_key: str = "",
    product_id: str | None = None,
) -> AssembledHandoff | None:
    """Read the materialised :class:`AssembledHandoff` for ``(workspace_id, account_entity_id,
    icp_spec_version, icp_key)``, or ``None`` if it has not been assembled. Tenant-scoped on
    ``workspace_id`` so a client never reads another client's assembled handoff (substrate §2);
    ``icp_key`` (default ``""``) selects the ICP segment (D5)."""
    row = (
        await conn.execute(
            text(
                "SELECT payload FROM account_handoff WHERE workspace_id = :workspace_id "
                "AND account_entity_id = :account_entity_id "
                "AND icp_spec_version = :icp_spec_version AND icp_key = :icp_key "
                "AND product_id = :product_id "
                "AND payload IS NOT NULL"
            ),
            {
                "workspace_id": workspace_id,
                "account_entity_id": str(account_entity_id),
                "icp_spec_version": icp_spec_version,
                "icp_key": icp_key,
                "product_id": product_id or "",
            },
        )
    ).first()
    if row is None:
        return None
    return _decode_payload(row[0])


async def list_handoffs_for_run(
    conn: AsyncConnection, *, workspace_id: str, project_run_id: ProjectRunId
) -> list[tuple[str, str | None, str | None, AssembledHandoff]]:
    """All materialised handoffs for ``(workspace_id, project_run_id)`` as
    ``(icp_key, tier, product_id, assembled)`` tuples — the M12.3 list-serve surface
    (``GET /project_runs/{id}/handoffs``). A
    materialised row exists only *after* assembly (which reads verified claims), so the list returns
    exactly the run's **ready** handoffs (M12.3 AC: an account still in deep/verification has no row
    and is absent). ``icp_key`` / ``tier`` are table columns (the frozen ``AccountHandoff`` payload
    carries ``icp_spec_version`` but not the segment key — D5 — nor the tier), so a multi-segment
    account's fetch ref is correct and the list can filter by tier. Workspace-scoped on
    ``workspace_id``
    (substrate §2); ordered by ``(account_entity_id, icp_spec_version, icp_key)``."""
    rows = (
        await conn.execute(
            text(
                "SELECT icp_key, tier, NULLIF(product_id, ''), payload FROM account_handoff "
                "WHERE workspace_id = :workspace_id AND project_run_id = :project_run_id "
                "AND payload IS NOT NULL "
                "ORDER BY account_entity_id, icp_spec_version, icp_key"
            ),
            {"workspace_id": workspace_id, "project_run_id": project_run_id},
        )
    ).all()
    return [(str(row[0]), row[1], row[2], _decode_payload(row[3])) for row in rows]
