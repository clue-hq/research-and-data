"""`run_website_ingestion` — the website ingestion job glue (slice 1 §9).

Wires the capture package (Agent A) to slice-0's normalizer and the persistence API. It ran
inside a FastAPI ``BackgroundTasks`` worker until **Part II slice D5 Round C**, which moved
ingestion onto the ``design_job`` fleet queue: the three entry points below are now driven from a
frozen ``DesignIngestionEnvelope`` by ``lumen_api.main.execute_ingestion_job``, inside
``asyncio.to_thread`` on a leased worker. Nothing in this module had to change shape for that —
it was always a self-contained "job id in, terminal row out" function — but its inputs are now
mandatory (``workspace_id``) and fenceable (``expected_generation``). The whole thing is still
driven through ``run_ingestion_job`` from slice 0 so it *never raises*: every failure lands on
the job row instead.

The capture package (``lumen_ingestion.capture``) and the core client
(``lumen_api.core``) are imported lazily so this module stays importable even
while Agent A's capture files do not yet exist, and so tests can inject stubs
without pulling in playwright / httpx. ``capture`` and ``build_evidence`` are
both injectable parameters whose defaults resolve the real callables at call
time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence

from clue_storage import StorageBackend, storage_from_settings
from lumen_api.database import NotFoundError
from lumen_api.design_store import DesignBlobStore, HybridRepository
from py_lumen_config import settings

from .brief import kit_token_names
from .grammar_audit import extract_grammar_audit
from .jobs import IngestionJobStore, StageReporter, run_ingestion_job
from .measured_components import MeasuredComponentsRefused, validate_measured_components
from .normalizer import normalize_evidence

JsonObject = dict[str, Any]

logger = logging.getLogger(__name__)


class _CaptureCallable(Protocol):
    def __call__(
        self,
        url: str,
        *,
        reporter: StageReporter,
        force_render: bool = ...,
        page_urls: "Sequence[str] | None" = ...,
        discover_pages: bool = ...,
    ) -> Awaitable[Any]: ...


class _BuildEvidenceCallable(Protocol):
    def __call__(
        self, outcome: Any, *, core: Any, store_root: str, reporter: StageReporter
    ) -> Any: ...


def _default_capture(
    url: str,
    *,
    reporter: StageReporter,
    force_render: bool = False,
    page_urls: "Sequence[str] | None" = None,
    discover_pages: bool = False,
) -> Awaitable[Any]:
    from .capture import capture_website

    return capture_website(
        url, reporter=reporter, force_render=force_render, page_urls=page_urls,
        discover_pages=discover_pages,
    )


def _default_build_evidence(
    outcome: Any, *, core: Any, store_root: str, reporter: StageReporter
) -> Any:
    from .capture.evidence_builder import build_evidence

    return build_evidence(outcome, core=core, store_root=store_root, reporter=reporter)


def _core_client() -> Any:
    from lumen_api.core import CoreClient

    return CoreClient()


# --- D6 Round C: the ingestion worker's governed write path ---------------------------------- #


def _worker_design_tools(storage: StorageBackend) -> Any:
    """The design toolbelt as the ingestion WORKER sees it.

    The pipeline's two durable design writes — promoting a capture's assets into the library and
    publishing the kit it produced — are the same writes the HTTP routes make, so D6 routes them
    through the same tools with ``actor="agent"`` (REQ-20 parity). The host needs only the row
    store and the byte store: nothing here calls the engine from inside a tool (R-D6-B4 — the
    validate/summarize round-trip happens in this module, before the invocation).
    """
    from lumen_api.toolbelt.wiring import DesignToolInvocations, design_tool_host

    def _unavailable(name: str) -> Any:
        raise RuntimeError(f"the ingestion worker's design tool host has no {name}")

    return DesignToolInvocations(
        host=design_tool_host(
            storage=storage,
            core=lambda: _unavailable("engine core"),
            web_export_node_bin=lambda: _unavailable("web export node binary"),
            compiler_node_bin=lambda: _unavailable("component compiler"),
            compiler_worker_path=lambda: _unavailable("component compiler worker"),
            compiler_timeout_seconds=lambda: _unavailable("component compiler timeout"),
            compile_fn=lambda: _unavailable("component compiler"),
        ),
        storage=storage,
    )


def _register_captured_assets(
    tools: Any, workspace_id: str, records: "list[JsonObject]"
) -> None:
    """Promote one capture's asset records into the library, through the governed tool."""
    if not records:
        return
    tools.invoke(
        "design_register_captured_assets",
        {"records": records},
        workspace_id=workspace_id,
        actor="agent",
    )


def _publish_ingested_kit(
    tools: Any,
    repo: HybridRepository,
    *,
    core: Any,
    brand_kit: JsonObject,
    brand_summary: JsonObject,
    diagnostics: "list[JsonObject]",
    source: str,
    job_derived_id: bool,
) -> JsonObject:
    """Publish the kit one ingestion produced.

    A job-derived id creates version 1 and adopts that exact slot on a re-offer. A
    client-supplied id has two meanings: create version 1 when the lineage does not exist yet,
    or publish the existing lineage's NEXT version when it does. The latter is the manual
    Re-extract contract — it must not run the capture and then collide with version 1.

    **The re-offer hole this closes.** The D5 Round C reaper re-offers a job whose worker died
    between publishing the kit and terminalizing the job row. The kit id is already per-job
    deterministic — ``brand_kit_ing_<job suffix>`` at version 1 — so the second attempt's INSERT
    collided on the composite primary key and the job failed with a database error instead of
    completing with the result it had already produced.

    ``on_conflict='adopt'`` makes the job-derived create a no-op that returns the existing row,
    which is safe *because* the id is derived from the job id: the only writer that can have
    filled that slot is an earlier attempt of this same job. When the CLIENT supplied the kit id,
    an absent lineage still uses ``on_conflict='refuse'`` because that slot is not the job's to
    adopt. An existing lineage uses ``design_publish_brand_kit_version``: its version is allocated
    inside the locked write, its expected base is CAS-checked, and the DAL inherits the lineage's
    explicit ``brand_id``.

    A rare reaper residual remains deliberately visible: an existing-lineage job that dies after
    this publish but before terminalizing has no durable producing-job marker in the kit row, so
    its re-offer can publish one extra version. Ingestion now auto-approves each version;
    the page shows the latest. A durable producing-job receipt remains a separate follow-up.
    """
    # Extraction is automatically accepted at publication (founder, 2026-09-21).
    # Normalize and structurally validate first, then summarize the approved kit so
    # product_ready and completeness diagnostics still describe the actual content.
    brand_kit = {**brand_kit, "approval_status": "approved"}
    summary_response = core.summarize_brand_kit(brand_kit, raise_on_error=False)
    brand_summary = {**brand_summary, **summary_response["brand_summary"]}

    if not job_derived_id:
        brand_kit_id = str(brand_kit["id"])
        try:
            current = repo.require_brand_kit(brand_kit_id)
        except NotFoundError:
            pass
        else:
            ref = tools.invoke(
                "design_publish_brand_kit_version",
                {
                    "brand_kit": brand_kit,
                    "brand_summary": brand_summary,
                    "diagnostics": diagnostics,
                    "source": source,
                    "expected_base_version": int(current["version"]),
                },
                workspace_id=repo.workspace_id,
                actor="agent",
            ).references
            return repo.require_brand_kit(ref["brand_kit_id"], ref["version"])

    ref = tools.invoke(
        "design_create_brand_kit",
        {
            "brand_kit": brand_kit,
            "brand_summary": brand_summary,
            "diagnostics": diagnostics,
            "source": source,
            "on_conflict": "adopt" if job_derived_id else "refuse",
        },
        workspace_id=repo.workspace_id,
        actor="agent",
    ).references
    if not ref["created"]:
        logger.info(
            "ingestion job adopted the brand kit its earlier attempt already published: %s v%s",
            ref["brand_kit_id"],
            ref["version"],
        )
    return repo.require_brand_kit(ref["brand_kit_id"], ref["version"])


class _RecordingCore:
    """Proxy over CoreClient that captures ingest_asset records — and, since D4, the ONE
    write-back chokepoint for the whole ingestion lane.

    The capture layer writes bytes into the engine's materialization cache via
    core.ingest_asset but the /assets/{id} routes serve from the DB asset RECORDS (the upload
    route persists both). Wrapping the client here lets each pipeline persist
    the records afterward without threading a sink through the capture layer.

    That same wrapper is why the three capture modules (uploads / pdf / evidence_builder) need
    no D4 changes at all: every one of their ``core.ingest_asset`` calls lands here, so ONE
    ``register_engine_write`` gives durable custody to every byte the capture layer produces and
    re-points each record's ``media.location`` (R-D4-4) before the record is ever persisted or
    embedded in a kit. Threading a blob store through the capture layer instead would have put
    the same call in four places and made "did every producer remember?" an audit question.

    ingest_asset may run in worker threads (list.append is GIL-atomic; the write-back is one
    self-contained bridged transaction per call); persistence happens on the pipeline thread via
    `persist_records`, which since D6 Round C goes through the governed design toolbelt.
    """

    def __init__(self, inner: Any, blobs: DesignBlobStore, cache_dir: str) -> None:
        self._inner = inner
        self._blobs = blobs
        self._cache_dir = cache_dir
        self.records: list[JsonObject] = []

    def ingest_asset(self, *args: Any, **kwargs: Any) -> Any:
        from lumen_api.asset_custody import register_engine_write
        from clue_design.storage import SOURCE_KEY_ASSET

        response = self._inner.ingest_asset(*args, **kwargs)
        record = ((response or {}).get("asset") or {}).get("record") or {}
        if record.get("id"):
            register_engine_write(
                self._blobs,
                self._cache_dir,
                record=record,
                source_key=SOURCE_KEY_ASSET,
            )
            self.records.append(record)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def persist_records(self, register: "Callable[[list[JsonObject]], None]") -> None:
        """Hand every captured record to the governed bulk registration (D6 Round C).

        It used to call ``repo.create_asset_record`` per record. The write is governed now, so
        it goes out as ONE ``design_register_captured_assets`` invocation: a capture is one
        gesture, the ids are content-derived (so a re-offered job converges), and a per-record
        invocation would cost a private engine and a journal execution per captured image.
        """
        register(list(self.records))


def _read_staged(blobs: DesignBlobStore, digest: Any) -> "bytes | None":
    """One staged upload's bytes (R-D4-5), or None — which the caller turns into LUMI0605."""
    from lumen_api.asset_custody import read_asset_bytes

    if not isinstance(digest, str) or not digest:
        return None
    return read_asset_bytes(blobs, digest)


def _discard_staged(
    repo: HybridRepository, blobs: DesignBlobStore, digests: "list[Any]"
) -> None:
    """Clean up the job's staged uploads — but ONLY the ones nothing kept (R-D4-5).

    Staging and promotion are content-addressed, so a file that made it into the library is
    living under the SAME key the staging register wrote: deleting the staged blob would delete
    the asset's bytes. So the rule is the asset GC's rule, asked per digest — if any asset
    record in this workspace still names it, the bytes were promoted and stay; otherwise the
    upload was rejected, deduped away, or the job failed, and the staged copy is garbage.

    Never raises: cleanup runs in a ``finally`` and must not mask the job's real outcome.
    """
    for digest in dict.fromkeys(d for d in digests if isinstance(d, str) and d):
        try:
            if repo.count_assets_with_digest(digest):
                continue
            blobs.delete(digest)
        except Exception:  # noqa: BLE001 - cleanup is best-effort by construction
            logger.warning("staged upload cleanup failed for %s", digest, exc_info=True)


def _capture_diagnostics(outcome: Any) -> list[JsonObject]:
    diagnostics = getattr(outcome, "diagnostics", None) or []
    return [dict(d) for d in diagnostics]


def _validation_diagnostics(validation: JsonObject) -> list[JsonObject]:
    return list(validation.get("diagnostics") or [])


# ---------------------------------------------------------------------------
# Snapshot custody (clone-fidelity F0.1) — additive, loud, never fatal.
# ---------------------------------------------------------------------------


def _requested_page_urls(request: JsonObject) -> "list[str] | None":
    """The extra pages this job asked for (F0.4), or ``None`` — the entry page alone.

    Read off the durable job request rather than added to the route DTO: F0.4 is a PROVISION.
    Nothing produces a page list yet (nav discovery is later work), and a request shape that
    exists before a producer does is a shape nobody has tested against real input. Read
    defensively for the same reason — the request is stored JSON, so a malformed value is a
    thing that can happen, and it must not take an ingestion down with it.
    """
    raw = request.get("page_urls")
    if not isinstance(raw, list):
        return None
    pages = [page for page in raw if isinstance(page, str) and page]
    return pages or None


def _outcome_snapshots(outcome: Any) -> list[Any]:
    """Every page this capture produced, entry page first.

    ``CaptureOutcome.snapshots`` is the F0.4 multi-page list; ``.snapshot`` is the entry page
    every pre-F0.4 caller (and every capture stub in the suites) still speaks. Reading both means
    a stubbed outcome that only sets ``.snapshot`` is persisted exactly like a real single-page
    capture, and one that sets neither simply has nothing to persist.
    """
    snapshots = getattr(outcome, "snapshots", None)
    if snapshots:
        return list(snapshots)
    snapshot = getattr(outcome, "snapshot", None)
    return [snapshot] if snapshot is not None else []


def _persist_site_snapshots(
    outcome: Any,
    *,
    workspace_id: str,
    job_id: str,
    storage: StorageBackend,
    diagnostics: "list[JsonObject]",
) -> list[Any]:
    """Give the capture durable custody. A failure is a DIAGNOSTIC, not the end of the job.

    Snapshot custody is additive to the ingestion's real product (the brand kit its evidence
    produced). Two failure modes are wrong here and this function exists to avoid both: a silent
    pass, which is how a clone tier later discovers it has no source to read and nobody knows
    when that started; and a raise, which would throw away a perfectly good kit because the blob
    store hiccuped after the evidence was already built. So the failure is recorded loudly —
    ``LUMI0512`` on the kit's diagnostics, with the exception in the worker log — and the
    ingestion carries on with an empty ref list.
    """
    from .site_snapshot import SNAPSHOT_PERSIST_FAILED_CODE, persist_site_snapshots

    snapshots = _outcome_snapshots(outcome)
    if not snapshots:
        return []
    try:
        return list(
            persist_site_snapshots(
                snapshots,
                workspace_id=workspace_id,
                job_id=job_id,
                storage=storage,
            )
        )
    except Exception as error:  # noqa: BLE001 — custody must not kill an ingestion
        logger.exception("site snapshot persistence failed for job %s", job_id)
        diagnostics.append(
            {
                "code": SNAPSHOT_PERSIST_FAILED_CODE,
                "severity": "error",
                "message": (
                    "captured site snapshots were not persisted; this ingestion's html, "
                    f"stylesheets and screenshot are not durable: {type(error).__name__}: {error}"
                ),
            }
        )
        return []


# ---------------------------------------------------------------------------
# Description engine hook (slice 3 §6) — shared by all three ingestion paths.
#
# ``describe.py`` (Agent A) may not exist while this module is edited, so the
# describer + ``apply_descriptions`` are both resolved lazily at call time and
# every entry point is injectable so tests can stub them. The website + PDF
# paths call ``_maybe_describe`` which is a GUARANTEED no-op pass-through when
# ``describe.py`` is absent or a NullDescriber is in play — the existing suites
# must stay green even if Agent A's files land after these edits.
# ---------------------------------------------------------------------------


class _DescriberProtocol(Protocol):
    def describe(self, items: list[Any]) -> list[Any]: ...


class _ApplyDescriptionsCallable(Protocol):
    def __call__(
        self,
        evidence: Any,
        *,
        describer: Any,
        resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
        reporter: Callable[[str, float], None],
        rasterize_svg: Callable[[str], "bytes | None"] | None = None,
        resolve_thumbnail: Callable[[str], "tuple[bytes, str] | None"] | None = None,
        diagnostics: list | None = None,
    ) -> Any: ...


def resolve_describer() -> Any:
    """Return the configured ``AssetDescriber`` (Agent A's describe.py).

    ``OpenRouterDescriber`` when ``LUMEN_INGESTION_DESCRIBE=1`` else the
    deterministic ``NullDescriber``. Resolved lazily so this module imports
    without describe.py present; if describe.py is missing entirely a tiny
    inline null describer is returned so callers still get a real object.
    """
    try:
        from .describe import NullDescriber, OpenRouterDescriber
    except ImportError:
        logger.debug("describe.py unavailable; using inline null describer")
        return _InlineNullDescriber()

    if settings.lumen_ingestion_describe:
        return OpenRouterDescriber()
    return NullDescriber()


class _InlineNullDescriber:
    """Fallback describer used only when describe.py is absent. Returns
    ``[None] * len(items)`` so ``apply_descriptions`` (also absent) is never
    reached — this exists purely to keep ``resolve_describer`` total."""

    def describe(self, items: list[Any]) -> list[Any]:
        return [None] * len(items)


def _default_apply_descriptions(
    evidence: Any,
    *,
    describer: Any,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    reporter: Callable[[str, float], None],
    rasterize_svg: Callable[[str], "bytes | None"] | None = None,
    resolve_thumbnail: Callable[[str], "tuple[bytes, str] | None"] | None = None,
    diagnostics: list | None = None,
    workspace_id: str | None = None,
    asset_records: list[dict] | None = None,
    job_id: str | None = None,
    brand_kit_id: str | None = None,
) -> Any:
    """Lazily resolve Agent A's ``apply_descriptions`` and call it.

    Raises ``ImportError`` when describe.py is absent — callers wrap this in
    ``_maybe_describe`` which swallows that into a debug-level pass-through.

    ``workspace_id`` (D2.3) rides only this default path, never the injected seam: the
    ``_ApplyDescriptionsCallable`` protocol is unchanged, so stubbed describers keep their
    existing signature.
    """
    from .describe import apply_descriptions

    return apply_descriptions(
        evidence,
        describer=describer,
        resolve_bytes=resolve_bytes,
        reporter=reporter,
        rasterize_svg=rasterize_svg,
        resolve_thumbnail=resolve_thumbnail,
        diagnostics=diagnostics,
        workspace_id=workspace_id,
        asset_records=asset_records, job_id=job_id, brand_kit_id=brand_kit_id,
    )



# ---------------------------------------------------------------------------
# The design-brief stage (design-brief plan, slice 3).
#
# Runs after normalize + engine validation and BEFORE the kit is published, so
# the brief rides the SAME draft version everything else in this job produced.
# Everything about it is fail-soft: an unconfigured stage is silent, and every
# other outcome is a diagnostic plus a briefless kit. `brief_agent` is injectable
# so the ingestion suite can drive every branch without a gateway.
# ---------------------------------------------------------------------------


def _brief_screenshots(evidence: Any, resolve_bytes) -> "list[tuple[str, str]]":
    """The capture's screenshots as `(base64, mime)`, for the agent's vision path.

    The capture already stored them, so this is a read of durable bytes, never a
    re-render. An unresolvable screenshot drops itself — the brief is then written
    from the measured evidence alone, which is thinner but still honest.
    """
    import base64

    from .brief_agent import MAX_SCREENSHOTS

    shots: list[tuple[str, str]] = []
    for asset_id in list(getattr(evidence, "screenshots", []) or [])[:MAX_SCREENSHOTS]:
        resolved = resolve_bytes(asset_id)
        if not resolved:
            continue
        data, mime = resolved
        shots.append((base64.b64encode(data).decode("ascii"), mime))
    return shots


def _maybe_write_brief(
    evidence: Any,
    brand_kit: JsonObject,
    *,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    brief_agent: Any | None,
    diagnostics: list,
) -> "JsonObject | None":
    """The brief for this kit, or None. Never raises — a brief is never a gate."""
    try:
        from .brief_agent import build_brief_request, generate_brief, resolve_brief_agent

        agent = brief_agent if brief_agent is not None else resolve_brief_agent()
        # `generate_brief` re-checks this; asking here too keeps an unconfigured
        # stage from reading (and base64-ing) every stored screenshot first.
        if not getattr(agent, "active", False):
            return None
        request = build_brief_request(
            evidence, brand_kit, screenshots=_brief_screenshots(evidence, resolve_bytes)
        )
        return generate_brief(request, agent=agent, diagnostics=diagnostics)
    except Exception as error:  # noqa: BLE001 - the stage may never fail an ingest
        logger.warning("the brief stage could not run; publishing briefless", exc_info=True)
        diagnostics.append(
            {
                "code": "LUMI0903",
                "severity": "warning",
                "message": f"the brief stage could not run ({type(error).__name__}): {error}",
            }
        )
        return None


def _maybe_extract_grammar_audit(
    evidence: Any, brand_kit: JsonObject, *, diagnostics: list
) -> "JsonObject | None":
    """The kit's `BrandGrammarAudit@1`, or None with a diagnostic.

    Deterministic arithmetic over evidence already in hand — no agent, no
    screenshots, nothing to configure — so unlike the brief there is no "silent
    when unconfigured" branch: a website kit always gets one. It is still never a
    gate: an extraction that throws publishes the kit auditless and says so, the
    same posture the brief stage takes.
    """
    try:
        return extract_grammar_audit(evidence, brand_kit).model_dump()
    except Exception as error:  # noqa: BLE001 - the stage may never fail an ingest
        logger.warning(
            "the grammar audit could not be extracted; publishing without one", exc_info=True
        )
        diagnostics.append(
            {
                "code": "LUMI0910",
                "severity": "warning",
                "message": (
                    "the brand grammar audit could not be extracted "
                    f"({type(error).__name__}): {error}"
                ),
            }
        )
        return None


def _attach_measured_components(
    validated_kit: JsonObject, measured: "JsonObject | None", diagnostics: list
) -> JsonObject:
    """The kit with its `MeasuredComponents@1`, or the kit as it was with a diagnostic.

    It rides the validated kit for the brief's reason (the engine's BrandKit has no field for it);
    the tokens it names were minted into `tokens` before the engine round trip, so they are there.
    """
    if measured is None:
        return validated_kit
    try:
        section = validate_measured_components(measured, token_names=kit_token_names(validated_kit))
    except MeasuredComponentsRefused as refusal:
        diagnostics.append({
            "code": "LUMI0608", "severity": "warning",
            "message": f"measured component styles were not kept on the kit: {refusal.reason}",
        })
        return validated_kit
    return {**validated_kit, "measured_components": section}


def _font_metrics_map(evidence: Any, resolve_bytes) -> dict:
    """K4 rung 2: measured metrics per font family, from the stored face
    bytes. Best-effort — a face that cannot be read or parsed contributes
    nothing, and a kit with no readable faces gets the identity ramp."""
    from .normalizer.font_metrics import extract_font_metrics

    metrics: dict = {}
    for font in getattr(evidence, "fonts", []) or []:
        family = getattr(font, "family", None)
        if not family or family in metrics:
            continue
        for face in getattr(font, "faces", []) or []:
            asset_id = getattr(face, "asset_id", None)
            if not asset_id:
                continue
            resolved = resolve_bytes(asset_id)
            if not resolved:
                continue
            measured = extract_font_metrics(resolved[0])
            if measured:
                metrics[family] = measured
                break
    return metrics


def _maybe_describe(
    evidence: Any,
    *,
    repo: HybridRepository,
    blobs: DesignBlobStore,
    cache_dir: str,
    reporter: Callable[[str, float], None],
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
    diagnostics: list | None = None,
    asset_records: list[dict] | None = None,
    job_id: str | None = None,
    brand_kit_id: str | None = None,
) -> Any:
    """Stamp AI descriptions onto ``evidence`` — a guaranteed no-op when
    describe.py is absent or errors.

    Wraps the lazy ``apply_descriptions`` import in ``try/except ImportError``
    with a debug-level pass-through so the website + PDF suites stay green even
    if Agent A's describe.py lands after this code. An unexpected error still
    never fails the ingest, but it is no longer invisible: it lands in
    ``diagnostics`` as a LUMI0803 warning (imagery slice 1 — the silent
    describe failure cost the kit its entire image metadata once already).
    """
    # D2.3: descriptions are workspace-scoped rows now (and FK'd to the registry), so the
    # default path carries the repository's workspace. Taken off ``repo`` rather than threaded
    # through the three ``_ingest*`` signatures, and passed ONLY to the default (an injected
    # test stub still sees the unchanged protocol).
    workspace_id = getattr(repo, "workspace_id", None)
    apply = apply_descriptions or partial(_default_apply_descriptions, workspace_id=workspace_id,
                                                     asset_records=asset_records, job_id=job_id,
                                                     brand_kit_id=brand_kit_id)
    describer = describer if describer is not None else resolve_describer()
    resolve_bytes = _make_resolve_bytes(repo, blobs)
    try:
        return apply(
            evidence,
            describer=describer,
            resolve_bytes=resolve_bytes,
            reporter=reporter,
            rasterize_svg=_make_rasterize_svg(repo, blobs, cache_dir),
            # W1.4: SVGs prefer their STORED raster thumbnail (W1.2 makes one at
            # ingest) over a fresh engine rasterization; `rasterize_svg` above
            # stays as the fallback for records that predate it.
            resolve_thumbnail=_make_resolve_thumbnail_bytes(repo, blobs),
            diagnostics=diagnostics,
        )
    except ImportError:
        logger.debug("describe.py unavailable; skipping description pass")
        return evidence
    except Exception as error:  # never let the description engine fail the ingest
        logger.warning("apply_descriptions failed; skipping", exc_info=True)
        if diagnostics is not None:
            diagnostics.append(
                {
                    "code": "LUMI0803",
                    "severity": "warning",
                    "message": f"asset description pass failed entirely: {error}",
                }
            )
        return evidence


def _make_rasterize_svg(
    repo: HybridRepository, blobs: "DesignBlobStore", cache_dir: str
) -> Callable[[str], "bytes | None"]:
    """Rasterize a stored SVG asset through the ENGINE renderer (imagery
    slice 1): wrap the asset in a minimal one-image scene and export a PNG —
    the same `skia_safe::svg::Dom` path production rendering uses, so the
    describe preview shows exactly what a design would. Returns None on any
    failure — the caller emits the LUMI0804 diagnostic."""

    def rasterize(asset_id: str) -> "bytes | None":
        try:
            from lumen_api.core import CoreClient

            core = CoreClient()
            from lumen_api.asset_custody import ensure_materialized, record_digests

            record = repo.require_asset_record(asset_id)
            asset = record.get("asset") or record
            # D4 read-through: the engine rasterizes from ITS cache, so the SVG's bytes have to
            # be materialized out of durable storage first.
            ensure_materialized(
                blobs, cache_dir, (digest for digest, _mime in record_digests(asset))
            )
            # `new_scene` yields an empty scene with ZERO pages, so an
            # export against it produced no artifact and every SVG declined
            # (LUMI0804). Give the raster its own square page and insert the
            # image into it — the same page+image shape production rendering
            # uses.
            page_id = "page_svg_raster"
            scene = core.new_scene("doc_svg_raster", "svg raster")
            scene["pages"] = {page_id: _raster_page(page_id)}
            scene.setdefault("assets", {})[asset_id] = asset
            core_result = core.apply_operations(
                scene,
                [
                    {
                        "kind": "insert_node",
                        "parent": {"kind": "page", "id": page_id},
                        "index": 0,
                        "node": _raster_image_node(asset_id),
                    }
                ],
            )
            scene = core_result.get("scene") or scene
            export = core.export_preview(
                scene,
                "png",
                page_ids=[page_id],
                raise_on_error=False,
                asset_store_root=cache_dir,
            )
            for artifact in (export.get("export") or {}).get("artifacts") or []:
                # The engine emits raw pixel bytes under `bytes` (a list of
                # ints), never `bytes_base64` — reading the wrong key silently
                # dropped every rasterized preview.
                raw = artifact.get("bytes")
                if raw:
                    return bytes(raw)
            return None
        except Exception:  # noqa: BLE001 - raster failure is the caller's diagnostic
            logger.debug("svg rasterization failed for %s", asset_id, exc_info=True)
            return None

    return rasterize


# Public seam names for callers outside the pipeline (the /describe-assets
# backfill route builds the same resolve/rasterize pair the ingest pass uses).
def make_resolve_bytes(repo: HybridRepository, blobs: "DesignBlobStore"):
    return _make_resolve_bytes(repo, blobs)


def make_rasterize_svg(repo: HybridRepository, blobs: "DesignBlobStore", cache_dir: str):
    return _make_rasterize_svg(repo, blobs, cache_dir)


def _raster_page(page_id: str) -> dict:
    """A minimal square page (canonical pt units) sized to the raster viewport,
    so the SVG fills a 512×512 preview."""
    side = 512.0
    return {
        "id": page_id,
        "name": "svg raster",
        "size": {
            "width": side,
            "height": side,
            "unit": "pt",
            "preset": None,
            "orientation": "portrait",
        },
        "children": [],
        "bleed": None,
        "safe_area": None,
        "background": [],
    }


def _raster_image_node(asset_id: str) -> dict:
    """A minimal absolute-positioned image node filling the raster viewport."""
    side = 512.0
    return {
        "id": "svg_raster_image",
        "name": "svg raster image",
        "kind": {"kind": "image", "asset_id": asset_id, "alt": None},
        "children": [],
        "fills": [],
        "strokes": [],
        "opacity": 1.0,
        "clip": False,
        "locked": False,
        "layout": None,
        "computed": None,
        "position_mode": "absolute",
        "absolute_box": {"x": 0.0, "y": 0.0, "width": side, "height": side},
        "size": {
            "width": {"kind": "fixed", "value": side},
            "height": {"kind": "fixed", "value": side},
        },
        "transform": {
            "x": 0.0,
            "y": 0.0,
            "rotation": 0.0,
            "skew_x": 0.0,
            "skew_y": 0.0,
            "flip_x": False,
            "flip_y": False,
        },
        "corner": {
            "top_left": 0.0,
            "top_right": 0.0,
            "bottom_left": 0.0,
            "bottom_right": 0.0,
        },
    }


def _make_resolve_bytes(
    repo: HybridRepository, blobs: "DesignBlobStore"
) -> Callable[[str], "tuple[bytes, str] | None"]:
    """Build the ``resolve_bytes`` callable (§1): asset_id → (bytes, mime) via
    ``HybridRepository.require_asset_record`` → the record's digest → durable platform storage.
    Mirrors main.py ``get_asset_bytes``, including D4's resolve-BY-DIGEST rule (so the three
    historical ``opaque_ref`` shapes all resolve and no stored ref is read as a path). Returns
    ``None`` for ANY miss — never raises."""
    from lumen_api.asset_custody import read_asset_bytes
    from clue_design.storage import location_digest

    def resolve_bytes(asset_id: str) -> "tuple[bytes, str] | None":
        try:
            stored = repo.require_asset_record(asset_id)
        except Exception:
            return None
        record = stored.get("asset") or {}
        media = record.get("media") or {}
        try:
            data = read_asset_bytes(blobs, location_digest(media.get("location")))
        except Exception:
            return None
        if data is None:
            return None
        mime = media.get("mime_type") or "application/octet-stream"
        return (data, mime)

    return resolve_bytes


def _make_resolve_thumbnail_bytes(
    repo: HybridRepository, blobs: "DesignBlobStore"
) -> Callable[[str], "tuple[bytes, str] | None"]:
    """Build a ``resolve_thumbnail`` callable: asset_id → the record's STORED
    thumbnail as ``(bytes, mime)``, or ``None``.

    Same read as ``_make_resolve_bytes`` one block down the record —
    ``media.thumbnail.location`` instead of ``media.location`` — because a
    thumbnail carries no digest block of its own (see
    ``asset_custody.record_digests``). Since W1.2 every ingested SVG has one, so
    the describe pass can caption a vector from durable bytes instead of paying
    for a fresh engine rasterization. Returns ``None`` for ANY miss — never
    raises."""
    from lumen_api.asset_custody import read_asset_bytes
    from clue_design.storage import location_digest

    def resolve_thumbnail(asset_id: str) -> "tuple[bytes, str] | None":
        try:
            stored = repo.require_asset_record(asset_id)
        except Exception:
            return None
        record = stored.get("asset") or {}
        media = record.get("media") or {}
        thumbnail = media.get("thumbnail")
        if not isinstance(thumbnail, dict):
            return None
        try:
            data = read_asset_bytes(blobs, location_digest(thumbnail.get("location")))
        except Exception:
            return None
        if data is None:
            return None
        mime = thumbnail.get("mime_type") or "application/octet-stream"
        return (data, mime)

    return resolve_thumbnail


def run_website_ingestion(
    engine_cache_dir: str,
    job_id: str,
    *,
    capture: _CaptureCallable = _default_capture,
    build_evidence: _BuildEvidenceCallable = _default_build_evidence,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
    brief_agent: Any | None = None,
    workspace_id: str,
    storage: StorageBackend | None = None,
    expected_generation: int | None = None,
) -> None:
    """Run a website ingestion job to a terminal state. Never raises.

    Self-contained by design (it was a ``BackgroundTasks`` target until D5 Round C moved it onto
    the ``design_job`` fleet queue, and the property that made it safe there is what makes it
    safe in a worker thread now): it builds its own ``IngestionJobStore`` (Postgres, D2.5B: no
    SQLite connection to open or close) and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row). ``engine_cache_dir`` (D4) is the DISPATCHING
    REQUEST's per-workspace engine materialization cache — a transient mirror, never a store;
    every byte the capture layer writes there is given durable custody through the blob store
    below (see ``_RecordingCore``).

    ``workspace_id`` (D2.3) is threaded from the dispatching request — since D5 Round C, out of
    the job's frozen ``DesignIngestionEnvelope`` — so the job row, the brand kit it publishes,
    and the assets it registers all land in the SAME workspace; the job's composite result FK is
    enforced, so a mismatch fails loudly instead of orphaning. It is now REQUIRED: D5 Round C
    removed the dev-workspace fallback, because a worker-path write that silently picks a tenant
    is invisible until it is a cross-tenant incident. ``storage`` (D4) is likewise the
    dispatching app's byte backend; ``None`` falls back to the configured one.
    ``expected_generation`` (D5 Round C) is the claiming worker's lease generation — set it and
    every job write is fenced against a takeover (see ``IngestionJobStore``).
    """
    store = IngestionJobStore(
        workspace_id=workspace_id, expected_generation=expected_generation
    )
    repo = HybridRepository(workspace_id=workspace_id)
    resolved_storage = storage or storage_from_settings()
    blobs = DesignBlobStore(resolved_storage, workspace_id)
    core = _RecordingCore(_core_client(), blobs, engine_cache_dir)
    tools = _worker_design_tools(resolved_storage)

    def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
        return _ingest(
            store=store,
            repo=repo,
            core=core,
            blobs=blobs,
            tools=tools,
            cache_dir=engine_cache_dir,
            job_id=job_id,
            reporter=reporter,
            capture=capture,
            build_evidence=build_evidence,
            describer=describer,
            apply_descriptions=apply_descriptions,
            brief_agent=brief_agent,
        )

    run_ingestion_job(store, job_id, work, on_complete=_card_offer(workspace_id, tools))


def _ingest(
    *,
    store: IngestionJobStore,
    repo: HybridRepository,
    core: Any,
    blobs: DesignBlobStore,
    tools: Any,
    cache_dir: str,
    job_id: str,
    reporter: StageReporter,
    capture: _CaptureCallable,
    build_evidence: _BuildEvidenceCallable,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
    brief_agent: Any | None = None,
) -> "tuple[str, int, Optional[str]]":
    job = store.require(job_id)
    request = job["request"]
    url = request["url"]
    requested_kit_id = request.get("brand_kit_id")
    requested_name = request.get("name")
    page_urls = _requested_page_urls(request)

    # FOUNDER RULING (2026-08-20): website ingestion ALWAYS captures at the RENDERED tier —
    # "geometry needs a live page by definition". The brand's measured geometry (radii, stroke
    # weights, shadows, spacing) and the design brief's screenshots exist ONLY on the rendered
    # tier, and the static→rendered quality gate escalates on evidence POVERTY — so a site that
    # server-renders well (stripe.com) never escalated, and every kit the UI's Re-extract
    # published for it carried zero measured geometry and no brief.
    #
    # Enforced HERE, at the pipeline, and deliberately not at the route or in a client flag:
    # every website ingestion — the HTTP route, the `design_ingest_website` tool, the platform
    # proxy, a re-offered envelope replayed by a worker — passes through this one function, so a
    # caller that sends no flag still gets geometry. `request["force_render"]` is consequently
    # redundant and is no longer read (see `IngestWebsiteRequest.force_render`); the durable
    # request row keeps recording whatever the caller sent, which is the honest thing for it to
    # record. PDF and upload ingestion are untouched — there is no page to render.
    #
    # HONEST COST: rendering turns a ~10s static ingest into MINUTES (browser launch,
    # networkidle wait, ten scroll steps, a full-page screenshot, the geometry probe — the live
    # stripe.com walk measured ~3 minutes). That is affordable only because the job is offered
    # and drained asynchronously by a fleet worker and the checklist row streams its stage and
    # progress the whole time. If ingestion ever becomes synchronous again, this is the line
    # that makes it unaffordable.
    # Old frozen job requests retain single-page semantics; new API requests
    # carry their discovery decision explicitly and are replayable as recorded.
    capture_options = {"discover_pages": True} if request.get("discover_pages") is True else {}
    outcome = asyncio.run(
        capture(url, reporter=reporter, force_render=True, page_urls=page_urls, **capture_options)
    )
    evidence = build_evidence(
        outcome, core=core, store_root=cache_dir, reporter=reporter
    )

    # Give the capture itself durable custody (clone-fidelity F0.1) — the post-JS html, every
    # stylesheet fetched, and the full-page screenshot, one row per captured page. Placed HERE,
    # right after the snapshot is in scope and the evidence is built: the evidence is the job's
    # product and must not be at risk from a byte-store hiccup, so this runs after it and cannot
    # fail the job (see ``_persist_site_snapshots``).
    snapshot_diagnostics: list = []
    snapshot_refs = _persist_site_snapshots(
        outcome,
        workspace_id=repo.workspace_id,
        job_id=job_id,
        storage=blobs.storage,
        diagnostics=snapshot_diagnostics,
    )

    # Persist DB asset records for everything the capture layer ingested so
    # /assets/{id}/bytes|thumbnail and the library can serve them.
    #
    # ORDER (fixed at D2.3): registry FIRST, descriptions second. The description pass reads
    # bytes through ``repo.require_asset_record`` and now writes rows that are FK'd 1:1 to the
    # registry row, so describing before persisting could resolve nothing (every asset a
    # LUMI0805) and could not persist a caption at all.
    getattr(core, "persist_records", lambda _register: None)(
        partial(_register_captured_assets, tools, repo.workspace_id)
    )

    describe_diagnostics: list = []
    evidence = _maybe_describe(
        evidence,
        repo=repo,
        blobs=blobs,
        cache_dir=cache_dir,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
        diagnostics=describe_diagnostics,
        asset_records=getattr(core, "records", []), job_id=job_id,
        brand_kit_id=job["request"].get("brand_kit_id") or f"brand_kit_ing_{job_id.split('_', 1)[-1]}",
    )

    reporter("Preparing your brand kit…", 0.85)

    suffix = job_id.split("_", 1)[-1]
    brand_kit_id = requested_kit_id or f"brand_kit_ing_{suffix}"
    name = requested_name or _kit_name(evidence, url)
    created_at = (job["created_at"] or "").split("T", 1)[0]

    result = normalize_evidence(
        evidence,
        brand_kit_id=brand_kit_id,
        name=name,
        created_at=created_at or job["created_at"],
        version=1,
        font_metrics=_font_metrics_map(
            evidence, _make_resolve_bytes(repo, blobs)
        ),
    )
    kit = result.brand_kit

    # Persist mirroring main.py's create_brand_kit flow, but for a draft
    # ingestion kit (product_ready=False — completeness is reported independently).
    validation = core.validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    if not validation.get("ok"):
        codes = sorted(
            {
                str(d.get("code"))
                for d in validation.get("diagnostics") or []
                if d.get("severity") == "error"
            }
        )
        raise RuntimeError(f"ingested brand kit failed structural validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary = {"ingestion": result.ingestion_report}

    # The brief rides the VALIDATED kit: the engine's BrandKit has no `brief`
    # field, so a payload carrying one through `validate_brand_kit` would come
    # back with the section silently dropped. Attaching it after the round-trip
    # keeps the engine's contract untouched and the section durable.
    brief_diagnostics: list = []
    brief = _maybe_write_brief(
        evidence,
        validated_kit,
        resolve_bytes=_make_resolve_bytes(repo, blobs),
        brief_agent=brief_agent,
        diagnostics=brief_diagnostics,
    )
    if brief is not None:
        validated_kit = {**validated_kit, "brief": brief}

    # The grammar audit rides the same slot for the same reason (the engine's
    # BrandKit has no field for it), and is attached after the brief so the two
    # kit sections land in a stable order.
    audit_diagnostics: list = []
    audit = _maybe_extract_grammar_audit(
        evidence, validated_kit, diagnostics=audit_diagnostics
    )
    if audit is not None:
        validated_kit = {**validated_kit, "grammar_audit": audit}

    measured_diagnostics: list = []
    validated_kit = _attach_measured_components(
        validated_kit, result.measured_components, measured_diagnostics
    )

    diagnostics = (
        result.diagnostics
        + _capture_diagnostics(outcome)
        + _validation_diagnostics(validation)
        + describe_diagnostics
        + brief_diagnostics
        + audit_diagnostics
        + measured_diagnostics
        + snapshot_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
        core=core,
        brand_kit=validated_kit,
        brand_summary=summary,
        diagnostics=diagnostics,
        source="website",
        job_derived_id=requested_kit_id is None,
    )

    # Clone the pages' sections into fragments (clone-fidelity F2.2). AFTER the publish, because
    # a fragment is bound to the kit VERSION it was cloned into and an existing lineage's version
    # is allocated inside that write — so this is the first moment the binding can be honest.
    mint_refs, mint_diagnostics = _mint_page_fragments(
        outcome,
        repo=repo,
        blobs=blobs,
        brand_kit_id=str(record["brand_kit_id"]),
        brand_kit_version=int(record["version"]),
        snapshot_refs=snapshot_refs,
    )

    evidence_json = _evidence_dump(
        evidence,
        site_snapshots=snapshot_refs,
        web_fragments=mint_refs,
        fragment_diagnostics=mint_diagnostics,
        page_coverage=getattr(outcome, "page_coverage", None),
        missing_page_roles=getattr(outcome, "missing_page_roles", None),
    )
    return (record["brand_kit_id"], int(record["version"]), evidence_json)


def _kit_name(evidence: Any, url: str) -> str:
    narrative = getattr(evidence, "narrative", None)
    brand_name = getattr(narrative, "brand_name", None) if narrative else None
    if brand_name:
        return brand_name
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    return host or url


def _allocate_fragment_budget(counts: list[int], budget: int, per_page_cap: int) -> list[int]:
    """Round-robin allocation; a dense homepage cannot consume the entire library."""
    allocated = [0] * len(counts)
    remaining = max(0, budget)
    while remaining:
        progressed = False
        for index, count in enumerate(counts):
            if allocated[index] < min(count, per_page_cap) and remaining:
                allocated[index] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return allocated


def _mint_page_fragments(
    outcome: Any,
    *,
    repo: HybridRepository,
    blobs: DesignBlobStore,
    brand_kit_id: str,
    brand_kit_version: int,
    snapshot_refs: list[Any],
) -> tuple[list[JsonObject], list[JsonObject]]:
    """Mint captured sections with separate visible/dormant pools and fair page shares.

    Legacy captures keep their original total budget. New library captures use
    the documented library budget, still bounded by the existing per-page cap.
    Acquisition, fragment readiness and visual fidelity are separate outcomes.
    """
    from lumen_ingestion.sections import mint as section_mint
    from lumen_ingestion.sections.segment import segment_snapshot

    from .capture.geometry import captured_font_context
    from .capture.page_plan import MAX_CAPTURE_PAGES

    refs: list[JsonObject] = []
    diagnostics: list[JsonObject] = []
    snapshots = list(_outcome_snapshots(outcome))
    if not snapshots:
        return refs, diagnostics
    by_index = {ref.page_index: ref for ref in snapshot_refs}
    total = section_mint.SECTION_MINT_CAP
    if getattr(outcome, "library_capture", False):
        total = min(
            section_mint.LIBRARY_MINT_CAP, MAX_CAPTURE_PAGES * section_mint.SECTION_MINT_CAP
        )
    segmentations = []
    for index, snapshot in enumerate(snapshots):
        try:
            segmentation = segment_snapshot(
                _SnapshotView(
                    snapshot,
                    snapshot_id=getattr(by_index.get(index), "snapshot_id", None),
                )
            )
            diagnostics.extend(dict(entry) for entry in segmentation.diagnostics)
            segmentations.append(segmentation)
        except Exception as error:  # noqa: BLE001 — report one failed page and continue
            diagnostics.append(
                {
                    "code": section_mint.MINT_FAILED_CODE,
                    "severity": "error",
                    "page_url": snapshot.requested_url,
                    "message": f"page segmentation failed: {type(error).__name__}: {error}",
                }
            )
            segmentations.append(None)
    visible = _allocate_fragment_budget(
        [
            section_mint.visible_mint_capacity(s, snapshot.html) if s else 0
            for s, snapshot in zip(segmentations, snapshots, strict=True)
        ],
        total,
        section_mint.SECTION_MINT_CAP,
    )
    dormant = _allocate_fragment_budget(
        [len(s.hidden_sections) if s else 0 for s in segmentations],
        total,
        section_mint.SECTION_MINT_CAP,
    )
    rehost = section_mint.make_asset_rehoster(blobs)
    mark_degraded = section_mint.make_degraded_marker(workspace_id=repo.workspace_id)
    coverage = {row["url"]: row for row in getattr(outcome, "page_coverage", [])}
    for index, (snapshot, segmentation) in enumerate(zip(snapshots, segmentations, strict=True)):
        page = coverage.get(snapshot.requested_url)
        if page is not None:
            page["fragments"] = {"status": "failed", "minted": 0}
        if segmentation is None:
            continue
        try:
            result = section_mint.mint_sections(
                segmentation,
                html=snapshot.html,
                stylesheets=list(getattr(snapshot, "stylesheets", None) or []),
                initial_font_px=captured_font_context(getattr(snapshot, "geometry", None)).get(
                    "initial_font_px"
                ),
                captured=section_mint.captured_assets(snapshot),
                screenshot=_screenshot_bytes(snapshot),
                source_kit_id=brand_kit_id,
                source_kit_version=brand_kit_version,
                register_bytes=rehost,
                create_fragment=section_mint.make_fragment_writer(
                    blobs.storage, workspace_id=repo.workspace_id
                ),
                mark_degraded=mark_degraded,
                limit=visible[index],
                dormant_limit=dormant[index],
            )
        except Exception as error:  # noqa: BLE001 — fragment failure does not discard capture
            logger.exception("fragment minting failed for page %s", index)
            diagnostics.append(
                {
                    "code": section_mint.MINT_FAILED_CODE,
                    "severity": "error",
                    "page_url": snapshot.requested_url,
                    "message": f"page mint failed: {type(error).__name__}: {error}",
                }
            )
            continue
        refs.extend(minted.as_job_ref() for minted in result.minted)
        diagnostics.extend(dict(entry) for entry in result.diagnostics)
        if page is not None:
            wanted = len(segmentation.sections) + len(segmentation.hidden_sections)
            page["fragments"] = {
                "status": (
                    "minted"
                    if len(result.minted) == wanted and wanted
                    and not any(
                        d.get("code") == section_mint.MINT_FAILED_CODE for d in result.diagnostics
                    )
                    else "partial"
                ),
                "segmented": wanted,
                "minted": len(result.minted),
                "visible_budget": visible[index],
                "dormant_budget": dormant[index],
            }
    return refs, diagnostics


class _SnapshotView:
    """The shape :func:`segment_snapshot` reads, over a LIVE capture rather than a stored row.

    The segmenter is duck-typed on ``LoadedSiteSnapshot`` (Task 11's D2), and a ``SiteSnapshot``
    is nearly that shape already — it just spells its geometry differently and does not know its
    own persisted id. Three lines of adapter beats either loading the row back (bytes we already
    hold, a round trip we already paid for) or teaching the segmenter a second input shape.
    """

    def __init__(self, snapshot: Any, *, snapshot_id: "str | None") -> None:
        geometry = getattr(snapshot, "geometry", None)
        self.html = getattr(snapshot, "html", "") or ""
        # Relative references belong to the document that actually loaded,
        # including redirects to www or a canonical product path.
        self.page_url = (
            getattr(snapshot, "final_url", "") or getattr(snapshot, "requested_url", "") or ""
        )
        self.snapshot_id = snapshot_id
        self.viewport_width = _viewport_from_geometry(geometry)
        from .sections.bands import (
            SNAPSHOT_META_BANDS_KEY,
            SNAPSHOT_META_SKIPPED_KEY,
            SNAPSHOT_META_TRUNCATED_KEY,
            bands_for_meta,
            skipped_for_meta,
        )

        # PROJECT THE SAME THREE KEYS the persisted snapshot row carries (`site_snapshot.py`),
        # not just the bands. The skip records are the browser's own answer to "is this hidden?"
        # — the strongest evidence the segmenter has, both for binding a band sequence and (F3.0)
        # for deciding a section is hidden on the source site rather than merely class-named. The
        # live path was reading the row's shape minus that key, so a real ingestion made those
        # judgements from markup alone while the persisted snapshot beside it held the answer.
        self.meta = {
            SNAPSHOT_META_BANDS_KEY: bands_for_meta(geometry),
            SNAPSHOT_META_SKIPPED_KEY: skipped_for_meta(geometry),
            SNAPSHOT_META_TRUNCATED_KEY: bool(
                isinstance(geometry, dict) and geometry.get("truncated")
            ),
        }


def _viewport_from_geometry(geometry: Any) -> "int | None":
    if not isinstance(geometry, dict):
        return None
    try:
        width = int(geometry.get("viewport"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def _screenshot_bytes(snapshot: Any) -> "bytes | None":
    import base64 as _base64

    for download in getattr(snapshot, "downloads", None) or []:
        if getattr(download, "kind", None) != "screenshot":
            continue
        try:
            return _base64.b64decode(getattr(download, "bytes_b64", "") or "")
        except Exception:  # noqa: BLE001 — a corrupt shot costs a preview, not the job
            return None
    return None


def _evidence_dump(
    evidence: Any,
    *,
    site_snapshots: "list[Any] | None" = None,
    web_fragments: "list[JsonObject] | None" = None,
    fragment_diagnostics: "list[JsonObject] | None" = None,
    page_coverage: list[JsonObject] | None = None,
    missing_page_roles: list[str] | None = None,
) -> Optional[str]:
    """Dump BrandEvidence to JSON for the job row (it carries no raw bytes).

    ``site_snapshots`` (clone-fidelity F0.1) rides along on the website lane: the bounded refs
    — snapshot id, page url, html digest, screenshot digest — for the pages this job captured,
    so "what did this ingestion actually keep?" is answerable from the job row itself rather
    than only by querying the snapshot table. ``evidence_json`` is the JOB's evidence payload,
    not a serialized ``BrandEvidence`` (the ad-assets lane writes a step report into the same
    column), which is why the key can live at the top level.
    """
    if evidence is None:
        return None
    payload = evidence.model_dump() if hasattr(evidence, "model_dump") else evidence
    if site_snapshots is not None:
        payload = {**payload, "site_snapshots": [ref.as_job_ref() for ref in site_snapshots]}
    if web_fragments is not None:
        payload = {**payload, "web_fragments": list(web_fragments)}
    if fragment_diagnostics:
        payload = {**payload, "web_fragment_diagnostics": list(fragment_diagnostics)}
    if page_coverage is not None:
        payload = {
            **payload,
            "page_coverage": page_coverage,
            "outcome": {
                "kind": "website_capture",
                "fidelity_verified": False,
                "pages": [
                    {
                        key: row[key]
                        for key in (
                            "url",
                            "final_url",
                            "role",
                            "status",
                            "asset_count",
                            "fragments",
                        )
                        if key in row
                    }
                    for row in page_coverage
                ],
                "missing_page_roles": missing_page_roles or [],
            },
        }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# PDF ingestion (slice 2 §1/§4) — additive; mirrors the website path above.
#
# ``extract`` is an injectable parameter whose default lazily resolves Agent A's
# ``extract_pdf_evidence`` at call time, so this module stays importable while
# ``capture/pdf.py`` does not yet exist and tests can inject a stub without
# pulling pymupdf / Pillow. The PDF bytes live in a tmp file named by ``job_id``
# (written by the route); the pipeline reads then deletes it in a ``finally``.
# ---------------------------------------------------------------------------


class _ExtractPdfCallable(Protocol):
    def __call__(
        self,
        pdf_bytes: bytes,
        filename: str,
        *,
        core: Any,
        store_root: str,
        reporter: Callable[[str, float], None],
    ) -> Any: ...


def resolve_pdf_vision() -> Any:
    """Return the configured PDF vision assist without changing library defaults.

    Deployments opt in with ``LUMEN_INGESTION_VISION=1``. A missing OpenRouter key resolves
    directly to :class:`NullPdfVision`, preserving deterministic extraction without paying the
    PDF page-rasterization cost of an assist that cannot call its gateway.
    """
    from .capture.pdf_vision import NullPdfVision, OpenRouterPdfVision

    if settings.lumen_ingestion_vision and settings.openrouter_api_key:
        return OpenRouterPdfVision()
    return NullPdfVision()


def _default_extract_pdf(
    pdf_bytes: bytes,
    filename: str,
    *,
    core: Any,
    store_root: str,
    reporter: Callable[[str, float], None],
) -> Any:
    from .capture.pdf import extract_pdf_evidence

    return extract_pdf_evidence(
        pdf_bytes,
        filename,
        core=core,
        store_root=store_root,
        reporter=reporter,
        vision=resolve_pdf_vision(),
    )


def run_pdf_ingestion(
    engine_cache_dir: str,
    job_id: str,
    *,
    extract: _ExtractPdfCallable = _default_extract_pdf,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
    workspace_id: str,
    storage: StorageBackend | None = None,
    expected_generation: int | None = None,
) -> None:
    """Run a PDF ingestion job to a terminal state. Never raises.

    Self-contained by design (it was a ``BackgroundTasks`` target until D5 Round C moved it onto
    the ``design_job`` fleet queue, and the property that made it safe there is what makes it
    safe in a worker thread now): it builds its own ``IngestionJobStore`` (Postgres, D2.5B: no
    SQLite connection to open or close) and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row). ``engine_cache_dir`` (D4) is the DISPATCHING
    REQUEST's per-workspace engine materialization cache — a transient mirror, never a store;
    every byte the capture layer writes there is given durable custody through the blob store
    below (see ``_RecordingCore``). The uploaded PDF bytes are read from platform
    storage by the digest the route staged at ``request["staged_digest"]`` (R-D4-5), and the
    staged blob is always cleaned up before the job reaches a terminal state — unless it was
    promoted into a live asset, which is byte-identical and therefore the SAME key.
    ``workspace_id`` (D2.3, REQUIRED since D5 Round C — no dev-workspace fallback) comes from
    the dispatching request or the job's frozen envelope. ``storage`` (D4) is likewise the
    dispatching app's byte backend — threaded rather than re-derived so a process holding an
    injected backend cannot stage an upload in one place and read it from another.
    ``expected_generation`` (D5 Round C) fences every job write against a takeover.
    """
    store = IngestionJobStore(
        workspace_id=workspace_id, expected_generation=expected_generation
    )
    repo = HybridRepository(workspace_id=workspace_id)
    resolved_storage = storage or storage_from_settings()
    blobs = DesignBlobStore(resolved_storage, workspace_id)
    core = _RecordingCore(_core_client(), blobs, engine_cache_dir)
    tools = _worker_design_tools(resolved_storage)

    def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
        return _ingest_pdf(
            store=store,
            repo=repo,
            core=core,
            blobs=blobs,
            tools=tools,
            cache_dir=engine_cache_dir,
            job_id=job_id,
            reporter=reporter,
            extract=extract,
            describer=describer,
            apply_descriptions=apply_descriptions,
        )

    run_ingestion_job(store, job_id, work, on_complete=_card_offer(workspace_id, tools))


def _ingest_pdf(
    *,
    store: IngestionJobStore,
    repo: HybridRepository,
    core: Any,
    blobs: DesignBlobStore,
    tools: Any,
    cache_dir: str,
    job_id: str,
    reporter: StageReporter,
    extract: _ExtractPdfCallable,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> "tuple[str, int, Optional[str]]":
    job = store.require(job_id)
    request = job["request"]
    filename = request.get("filename") or "brand-guidelines.pdf"
    requested_kit_id = request.get("brand_kit_id")
    requested_name = request.get("name")
    staged_digest = request.get("staged_digest")

    try:
        pdf_bytes = _read_staged(blobs, staged_digest)
        if pdf_bytes is None:
            raise RuntimeError(
                f"LUMI0605: staged PDF bytes were not found (digest={staged_digest!r})"
            )

        extraction = extract(
            pdf_bytes,
            filename,
            core=core,
            store_root=cache_dir,
            reporter=reporter,
        )
    finally:
        _discard_staged(repo, blobs, [staged_digest])

    evidence = getattr(extraction, "evidence", extraction)

    # Persist DB asset records for everything the capture layer ingested so
    # /assets/{id}/bytes|thumbnail and the library can serve them.
    #
    # ORDER (fixed at D2.3): registry FIRST, descriptions second. The description pass reads
    # bytes through ``repo.require_asset_record`` and now writes rows that are FK'd 1:1 to the
    # registry row, so describing before persisting could resolve nothing (every asset a
    # LUMI0805) and could not persist a caption at all.
    getattr(core, "persist_records", lambda _register: None)(
        partial(_register_captured_assets, tools, repo.workspace_id)
    )

    describe_diagnostics: list = []
    evidence = _maybe_describe(
        evidence,
        repo=repo,
        blobs=blobs,
        cache_dir=cache_dir,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
        diagnostics=describe_diagnostics,
        asset_records=getattr(core, "records", []), job_id=job_id,
        brand_kit_id=job["request"].get("brand_kit_id") or f"brand_kit_ing_{job_id.split('_', 1)[-1]}",
    )

    reporter("Preparing your brand kit…", 0.85)

    suffix = job_id.split("_", 1)[-1]
    brand_kit_id = requested_kit_id or f"brand_kit_ing_{suffix}"
    name = requested_name or _pdf_kit_name(evidence, filename)
    created_at = (job["created_at"] or "").split("T", 1)[0]

    result = normalize_evidence(
        evidence,
        brand_kit_id=brand_kit_id,
        name=name,
        created_at=created_at or job["created_at"],
        version=1,
        font_metrics=_font_metrics_map(
            evidence, _make_resolve_bytes(repo, blobs)
        ),
    )
    kit = result.brand_kit

    validation = core.validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    if not validation.get("ok"):
        codes = sorted(
            {
                str(d.get("code"))
                for d in validation.get("diagnostics") or []
                if d.get("severity") == "error"
            }
        )
        raise RuntimeError(f"ingested brand kit failed structural validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary = {"ingestion": result.ingestion_report}

    diagnostics = (
        result.diagnostics
        + _pdf_extraction_diagnostics(extraction)
        + _validation_diagnostics(validation)
        + describe_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
        core=core,
        brand_kit=validated_kit,
        brand_summary=summary,
        diagnostics=diagnostics,
        source="pdf",
        job_derived_id=requested_kit_id is None,
    )

    evidence_json = _evidence_dump(evidence)
    return (record["brand_kit_id"], int(record["version"]), evidence_json)


def _pdf_extraction_diagnostics(extraction: Any) -> list[JsonObject]:
    diagnostics = getattr(extraction, "diagnostics", None) or []
    return [dict(d) for d in diagnostics]


def _pdf_kit_name(evidence: Any, filename: str) -> str:
    narrative = getattr(evidence, "narrative", None)
    brand_name = getattr(narrative, "brand_name", None) if narrative else None
    if brand_name:
        return brand_name
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Brand Kit"


# ---------------------------------------------------------------------------
# Asset-upload ingestion (slice 3 §6) — additive; mirrors the PDF path.
#
# ``analyze`` is an injectable parameter whose default lazily resolves Agent A's
# ``analyze_uploads`` at call time, so this module stays importable while
# ``capture/uploads.py`` does not yet exist and tests can inject a stub without
# pulling Pillow. Uploaded files live in tmp files named by ``job_id`` (written
# by the route); the pipeline reads then deletes ALL of them in a ``finally``.
# ---------------------------------------------------------------------------


class _AnalyzeUploadsCallable(Protocol):
    def __call__(
        self,
        files: list[Any],
        *,
        core: Any,
        store_root: str,
        reporter: Callable[[str, float], None],
    ) -> Any: ...


def _default_analyze_uploads(
    files: list[Any],
    *,
    core: Any,
    store_root: str,
    reporter: Callable[[str, float], None],
) -> Any:
    from .capture.uploads import analyze_uploads

    return analyze_uploads(
        files,
        core=core,
        store_root=store_root,
        reporter=reporter,
    )


def _upload_file_input(filename: str, content_type: Optional[str], data: bytes) -> Any:
    """Build an ``UploadFileInput`` (§1). Lazily resolves Agent A's dataclass so
    this module imports without ``capture/uploads.py`` present; falls back to a
    duck-typed shim carrying the same attribute names when it is absent (only
    reachable in tests that also stub ``analyze``)."""
    try:
        from .capture.uploads import UploadFileInput
    except ImportError:
        return _UploadFileInputShim(
            filename=filename, content_type=content_type, data=data
        )
    return UploadFileInput(filename=filename, content_type=content_type, data=data)


class _UploadFileInputShim:
    __slots__ = ("filename", "content_type", "data")

    def __init__(self, *, filename: str, content_type: Optional[str], data: bytes):
        self.filename = filename
        self.content_type = content_type
        self.data = data


def run_asset_ingestion(
    engine_cache_dir: str,
    job_id: str,
    *,
    analyze: _AnalyzeUploadsCallable = _default_analyze_uploads,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
    workspace_id: str,
    storage: StorageBackend | None = None,
    expected_generation: int | None = None,
) -> None:
    """Run an asset-upload ingestion job to a terminal state. Never raises.

    Self-contained by design (it was a ``BackgroundTasks`` target until D5 Round C moved it onto
    the ``design_job`` fleet queue, and the property that made it safe there is what makes it
    safe in a worker thread now): it builds its own ``IngestionJobStore`` (Postgres, D2.5B: no
    SQLite connection to open or close) and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row). ``engine_cache_dir`` (D4) is the DISPATCHING
    REQUEST's per-workspace engine materialization cache — a transient mirror, never a store;
    every byte the capture layer writes there is given durable custody through the blob store
    below (see ``_RecordingCore``). The uploaded files are read from platform
    storage by the digests the route staged at ``request["files"][*]["staged_digest"]``
    (R-D4-5), and each staged blob is cleaned up before the job reaches a terminal state —
    unless it was promoted into a live asset, which is byte-identical and therefore the SAME
    key. ``workspace_id`` (D2.3, REQUIRED since D5 Round C — no dev-workspace fallback) comes
    from the dispatching request or the job's frozen envelope; ``expected_generation``
    (D5 Round C) fences every job write against a takeover.
    """
    store = IngestionJobStore(
        workspace_id=workspace_id, expected_generation=expected_generation
    )
    repo = HybridRepository(workspace_id=workspace_id)
    resolved_storage = storage or storage_from_settings()
    blobs = DesignBlobStore(resolved_storage, workspace_id)
    core = _RecordingCore(_core_client(), blobs, engine_cache_dir)
    tools = _worker_design_tools(resolved_storage)

    def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
        return _ingest_assets(
            store=store,
            repo=repo,
            core=core,
            blobs=blobs,
            tools=tools,
            cache_dir=engine_cache_dir,
            job_id=job_id,
            reporter=reporter,
            analyze=analyze,
            describer=describer,
            apply_descriptions=apply_descriptions,
        )

    run_ingestion_job(store, job_id, work, on_complete=_card_offer(workspace_id, tools))


def _card_offer(workspace_id: str, tools: Any) -> Callable[[], Any]:
    """A kit ingestion that finishes second offers the ad-DNA card (``ad_library.auto_card``)."""
    from .ad_library.auto_card import card_offer_hook

    return card_offer_hook(workspace_id, tools=tools)


def _ingest_assets(
    *,
    store: IngestionJobStore,
    repo: HybridRepository,
    core: Any,
    blobs: DesignBlobStore,
    tools: Any,
    cache_dir: str,
    job_id: str,
    reporter: StageReporter,
    analyze: _AnalyzeUploadsCallable,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> "tuple[str, int, Optional[str]]":
    job = store.require(job_id)
    request = job["request"]
    requested_kit_id = request.get("brand_kit_id")
    requested_name = request.get("name")
    file_specs = list(request.get("files") or [])
    staged_digests = [spec.get("staged_digest") for spec in file_specs]

    try:
        inputs: list[Any] = []
        for spec in file_specs:
            staged_digest = spec.get("staged_digest")
            data = _read_staged(blobs, staged_digest)
            if data is None:
                raise RuntimeError(
                    "LUMI0605: staged asset bytes were not found "
                    f"(digest={staged_digest!r})"
                )
            inputs.append(
                _upload_file_input(
                    filename=spec.get("filename") or str(staged_digest),
                    content_type=spec.get("content_type"),
                    data=data,
                )
            )

        analysis = analyze(
            inputs,
            core=core,
            store_root=cache_dir,
            reporter=reporter,
        )
    finally:
        _discard_staged(repo, blobs, staged_digests)

    # ``analyze_uploads`` returns (evidence, diagnostics); tolerate a bare
    # evidence return from simpler stubs too.
    if isinstance(analysis, tuple):
        evidence, analyze_diagnostics = analysis[0], list(analysis[1] or [])
    else:
        evidence, analyze_diagnostics = analysis, []

    # Persist DB asset records for everything the capture layer ingested so
    # /assets/{id}/bytes|thumbnail and the library can serve them.
    #
    # ORDER (fixed at D2.3): registry FIRST, descriptions second. The description pass reads
    # bytes through ``repo.require_asset_record`` and now writes rows that are FK'd 1:1 to the
    # registry row, so describing before persisting could resolve nothing (every asset a
    # LUMI0805) and could not persist a caption at all.
    getattr(core, "persist_records", lambda _register: None)(
        partial(_register_captured_assets, tools, repo.workspace_id)
    )

    describe_diagnostics: list = []
    evidence = _maybe_describe(
        evidence,
        repo=repo,
        blobs=blobs,
        cache_dir=cache_dir,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
        diagnostics=describe_diagnostics,
        asset_records=getattr(core, "records", []), job_id=job_id,
        brand_kit_id=job["request"].get("brand_kit_id") or f"brand_kit_ing_{job_id.split('_', 1)[-1]}",
    )

    reporter("Preparing your brand kit…", 0.85)

    suffix = job_id.split("_", 1)[-1]
    brand_kit_id = requested_kit_id or f"brand_kit_ing_{suffix}"
    name = requested_name or _asset_kit_name(evidence, len(file_specs))
    created_at = (job["created_at"] or "").split("T", 1)[0]

    result = normalize_evidence(
        evidence,
        brand_kit_id=brand_kit_id,
        name=name,
        created_at=created_at or job["created_at"],
        version=1,
        font_metrics=_font_metrics_map(
            evidence, _make_resolve_bytes(repo, blobs)
        ),
    )
    kit = result.brand_kit

    validation = core.validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    if not validation.get("ok"):
        codes = sorted(
            {
                str(d.get("code"))
                for d in validation.get("diagnostics") or []
                if d.get("severity") == "error"
            }
        )
        raise RuntimeError(f"ingested brand kit failed structural validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary = {"ingestion": result.ingestion_report}

    diagnostics = (
        result.diagnostics
        + analyze_diagnostics
        + _validation_diagnostics(validation)
        + describe_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
        core=core,
        brand_kit=validated_kit,
        brand_summary=summary,
        diagnostics=diagnostics,
        source="asset_upload",
        job_derived_id=requested_kit_id is None,
    )

    evidence_json = _evidence_dump(evidence)
    return (record["brand_kit_id"], int(record["version"]), evidence_json)


def _asset_kit_name(evidence: Any, file_count: int) -> str:
    narrative = getattr(evidence, "narrative", None)
    brand_name = getattr(narrative, "brand_name", None) if narrative else None
    if brand_name:
        return brand_name
    return f"Uploaded assets ({file_count} files)"
