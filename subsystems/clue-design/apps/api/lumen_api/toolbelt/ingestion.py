"""Governed brand-kit ingestion ENQUEUE tools (Part II slice D6 Round C — domain 2).

The three ingest routes (``POST /brand-kits/ingest/{website,pdf,assets}``) do not ingest: since
D5 Round C they OFFER the work — the ``design_ingestion_job`` row and its ``design_job`` fleet
task are written in ONE transaction (``IngestionJobStore.create_and_offer``) and a leased worker
executes it. That atomic enqueue is the durable mutation, and it is what these tools govern.
Exactly the shape of :mod:`lumen_api.toolbelt.turns`.

**Staged blob registration stays in the route, and is exempt by construction.** The PDF and
asset routes write their uploaded bytes into platform storage *before* the job row exists (D4
R-D4-5 / D5 Round C ordering), so the row can be created with its complete request. That write is
content-addressed and immutable — registering the same bytes twice is the same key — so it is not
a mutation the D6 gate has anything to protect: there is no state to lose, no ordering to get
wrong, and an abandoned staged blob is exactly what the orphan sweep already collects. The tool
governs the row + task, which is the write that *can* be wrong.

**Validation stays in the route too** (the same reasoning as ``turns``): the SSRF guard's
rejection, the PDF magic-header check, the file-count ceiling and the size limits are wire
contracts with their own 4xx bodies that a tool precondition cannot reproduce, and they gate the
*upload*, not the row.

Replay honesty: ``OPERATION_IDEMPOTENT``, ``operation_id_required``. The job id is minted fresh
per request, so the row is a new identity every time — but the OFFER side is domain-idempotent
underneath, because ``enqueue_task`` dedups on ``dedup_key = str(work_id)``. A job row and its
fleet task therefore cannot diverge.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "IngestAdAssetsTool",
    "IngestAssetsTool",
    "IngestPdfTool",
    "IngestWebsiteTool",
    "IngestionJobRef",
    "OfferIngestionJobInput",
]

JsonObject = dict[str, Any]


class IngestionJobRef(ToolOutput):
    """The offered job, by reference. Never the request body (it holds staged digests)."""

    job_id: str
    work_id: str
    kind: str
    status: str


class OfferIngestionJobInput(ToolInput):
    #: Minted by the route (``ingest_<uuid4hex>``) because the frozen envelope names the job it
    #: dispatches — an id discovered only after the INSERT could not have ridden the payload.
    job_id: str
    #: The fleet work id; also the queue's ``dedup_key``.
    work_id: str
    #: The job's durable request: the ingestion parameters plus, for the upload kinds, the
    #: platform-storage digests of the already-staged bytes.
    request: JsonObject
    #: The frozen ``DesignIngestionEnvelope`` payload the fleet task carries.
    envelope: JsonObject
    priority: int = 0


class IngestWebsiteTool(DesignTool):
    """Offer one website brand-kit ingestion to the fleet."""

    name = "design_ingest_website"
    version = "1"
    model_description = (
        "Offer a website brand-kit ingestion to the worker fleet: writes the job row and its "
        "fleet task in one transaction and returns the job reference. The capture, "
        "normalization and kit publish happen asynchronously."
    )
    input_model: ClassVar[type[ToolInput]] = OfferIngestionJobInput
    output_model: ClassVar[type[ToolOutput]] = IngestionJobRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + job_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the job id is minted per request, so each execution is a new job row; the OFFER "
            "side is domain-idempotent underneath (the fleet queue dedups on "
            "dedup_key = work_id), so a job and its task can never diverge. The kit the WORKER "
            "publishes is separately governed and per-job deterministic, so a re-offered job "
            "adopts its own kit rather than publishing a second one"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("job_id", "work_id")
    )
    _kind: ClassVar[str] = "website"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, OfferIngestionJobInput)
        from lumen_ingestion.jobs import IngestionJobStore

        job = IngestionJobStore(workspace_id=ctx.workspace_id).create_and_offer(
            self._kind,
            inputs.request,
            job_id=inputs.job_id,
            work_id=UUID(inputs.work_id),
            envelope=inputs.envelope,
            priority=inputs.priority,
        )
        return IngestionJobRef(
            job_id=job["job_id"],
            work_id=inputs.work_id,
            kind=self._kind,
            status=job["status"],
        )


class IngestPdfTool(IngestWebsiteTool):
    """Offer one brand-guidelines PDF ingestion to the fleet."""

    name = "design_ingest_pdf"
    version = "1"
    model_description = (
        "Offer a brand-guidelines PDF ingestion to the worker fleet. The uploaded bytes are "
        "already staged in platform storage; the job request carries their digest."
    )
    _kind: ClassVar[str] = "pdf"


class IngestAssetsTool(IngestWebsiteTool):
    """Offer one brand-asset upload ingestion to the fleet."""

    name = "design_ingest_assets"
    version = "1"
    model_description = (
        "Offer a brand-asset upload ingestion to the worker fleet. The uploaded files are "
        "already staged in platform storage; the job request carries their digests."
    )
    _kind: ClassVar[str] = "asset_upload"


class IngestAdAssetsTool(IngestWebsiteTool):
    """Offer one Brand Ad Assets onboarding job to the fleet (spec §5 W2).

    The fourth ingestion kind, and a sibling rather than a special case: the lane needs fleet
    dispatch, the lease/generation fence, stage reporting and the stranded-work reaper, which
    is precisely what ``design_ingestion_job`` already is. Its job REQUEST holds no staged
    bytes — the harvest fetches its own, from the ad library — so the "staged blob registration
    stays in the route" note above simply does not apply here.

    The route that offers this is flag-gated (``LUMEN_BRAND_AD_ASSETS``) and 404s when the flag
    is off, so with the flag off this tool is registered, auditable, and unreachable.
    """

    name = "design_ingest_ad_assets"
    version = "1"
    model_description = (
        "Offer a brand ad-assets onboarding job to the worker fleet: harvest the brand's own "
        "published ads, filter and de-duplicate them, custody their bytes, distil the ad-DNA "
        "card, and pre-generate imagery from it. Runs asynchronously."
    )
    _kind: ClassVar[str] = "ad_assets"


class EnrichAssetsTool(IngestWebsiteTool):
    """Offer explicitly requested asset analysis through the existing governed job seam."""

    name = "design_enrich_assets"
    _kind = "asset_enrichment"
    model_description = "Queue analysis of existing workspace assets; originals and human edits remain intact."

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, OfferIngestionJobInput)
        from ..asset_enrichment import offer_retry
        job = offer_retry(ctx.workspace_id, inputs.request, job_id=inputs.job_id,
                          work_id=UUID(inputs.work_id), envelope=inputs.envelope,
                          priority=inputs.priority)
        return IngestionJobRef(job_id=job["job_id"], work_id=inputs.work_id,
                               kind=self._kind, status=job["status"])
