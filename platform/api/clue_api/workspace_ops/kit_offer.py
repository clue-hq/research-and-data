"""Offer a design ingestion job from the platform, in-process (spec 2026-10-25 §4, D7).

The job row and its ``design_job`` fleet task are written together, on the caller's connection,
so a workspace repair can offer its brand-kit work in the same transaction as its onboarding run
and its audit row, and needs no design API to be reachable. This is the pair
``lumen_ingestion.jobs.create_and_offer`` writes on the design side; it is repeated here because
the platform may not import design app code (``lumen_*``), and ``clue_design`` may not learn the
queue exists.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_design import ingestion as design_ingestion
from clue_design.enums import DesignIngestionKind
from clue_design.envelopes import DesignIngestionEnvelope
from clue_fleet import FleetTaskKind
from clue_fleet.queue import enqueue_task


async def offer_design_job(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    kind: str,
    request: dict[str, Any],
    priority: int = 0,
) -> str:
    """Queue one design ingestion job and its fleet task; returns the job id."""
    job_id = design_ingestion.new_id("ingest")
    work_id = uuid4()
    envelope = DesignIngestionEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="ingestion",
        job_id=job_id,
        ingestion_kind=DesignIngestionKind(kind),
    ).model_dump(mode="json")
    await design_ingestion.create_job(
        conn,
        workspace_id=workspace_id,
        kind=kind,
        request=request,
        job_id=job_id,
        work_id=work_id,
    )
    await enqueue_task(
        conn,
        kind=FleetTaskKind.DESIGN_JOB,
        project_run_id=ProjectRunId(work_id),
        dedup_key=str(work_id),
        payload=envelope,
        priority=priority,
        reopen_terminal=False,
    )
    return job_id
