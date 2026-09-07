"""The onboarding lane's client-entity seam.

Implemented **outside** ``clue_api.arv2`` because it reuses the Stage-0 client resolution
(``clue_research.stage0``), which the ARV2 import guard forbids inside the lane. The driver holds
it as the injected ``ClientEntityBinder`` protocol and never learns whose resolution it is.

**Standing rule (catalog contract §10).** This reuses Stage-0's *client-entity resolution only*.
It reads and writes no Client-KB version, no readiness decision and no Stage-0 run pin, so no
old-lane gate can block the onboarding lane: an onboarding run needs an identity to hang its
knowledge off, not a Client-KB.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import bind_workspace_client, workspace_client_entity_id
from clue_core import RunId
from clue_research.stage0 import ClientInput, prepare_client_kb_run

__all__ = ["Stage0ClientEntityBinder"]


class Stage0ClientEntityBinder:
    """Resolve (or reuse) the workspace's client entity for the company being onboarded.

    Once per workspace: an existing ``workspace_client_binding`` wins outright — re-resolving would
    risk minting a rival entity for the same customer, and repointing an existing binding is a
    refusal by design (``WorkspaceClientBindingConflict``). The run's own stamp is write-once for
    the same reason: a retry records the identity it found, never overwrites one already there.

    ``brand_id`` is part of the seam's shape but unused here: the client entity is *workspace*-
    scoped (one customer per workspace, many brands), so binding it per brand would be wrong.
    """

    async def ensure(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        run_id: UUID,
    ) -> UUID | None:
        entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
        if entity_id is None:
            entity_id = await prepare_client_kb_run(
                conn,
                ClientInput(name=company_domain, website=f"https://{company_domain}"),
                workspace_id=workspace_id,
                run_id=RunId(run_id),
            )
            await bind_workspace_client(conn, workspace_id=workspace_id, client_entity_id=entity_id)
        resolved = UUID(str(entity_id))
        await conn.execute(
            text(
                "UPDATE onboarding_run SET client_entity_id = :entity "
                "WHERE run_id = :run_id AND client_entity_id IS NULL"
            ),
            {"entity": resolved, "run_id": run_id},
        )
        return resolved
