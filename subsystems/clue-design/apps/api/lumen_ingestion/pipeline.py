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
from typing import Any, Awaitable, Callable, Optional, Protocol

from clue_storage import StorageBackend, storage_from_settings
from lumen_api.design_store import DesignBlobStore, HybridRepository
from py_lumen_config import settings

from .jobs import IngestionJobStore, StageReporter, run_ingestion_job
from .normalizer import normalize_evidence

JsonObject = dict[str, Any]

logger = logging.getLogger(__name__)


class _CaptureCallable(Protocol):
    def __call__(
        self, url: str, *, reporter: StageReporter, force_render: bool = ...
    ) -> Awaitable[Any]: ...


class _BuildEvidenceCallable(Protocol):
    def __call__(
        self, outcome: Any, *, core: Any, store_root: str, reporter: StageReporter
    ) -> Any: ...


def _default_capture(
    url: str, *, reporter: StageReporter, force_render: bool = False
) -> Awaitable[Any]:
    from .capture import capture_website

    return capture_website(url, reporter=reporter, force_render=force_render)


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
    brand_kit: JsonObject,
    brand_summary: JsonObject,
    diagnostics: "list[JsonObject]",
    source: str,
    job_derived_id: bool,
) -> JsonObject:
    """Publish the kit one ingestion produced, adopting its own earlier attempt's row.

    **The re-offer hole this closes.** The D5 Round C reaper re-offers a job whose worker died
    between publishing the kit and terminalizing the job row. The kit id is already per-job
    deterministic — ``brand_kit_ing_<job suffix>`` at version 1 — so the second attempt's INSERT
    collided on the composite primary key and the job failed with a database error instead of
    completing with the result it had already produced.

    ``on_conflict='adopt'`` makes that create a no-op that returns the existing row, which is
    safe *because* the id is derived from the job id: the only writer that can have filled that
    slot is an earlier attempt of this same job. When the CLIENT supplied the kit id
    (``job_derived_id=False``) the slot is not the job's to adopt, so the collision stays the
    loud refusal it has always been.
    """
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
    diagnostics: list | None = None,
    workspace_id: str | None = None,
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
        diagnostics=diagnostics,
        workspace_id=workspace_id,
    )



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
    apply = apply_descriptions or partial(_default_apply_descriptions, workspace_id=workspace_id)
    describer = describer if describer is not None else resolve_describer()
    resolve_bytes = _make_resolve_bytes(repo, blobs)
    try:
        return apply(
            evidence,
            describer=describer,
            resolve_bytes=resolve_bytes,
            reporter=reporter,
            rasterize_svg=_make_rasterize_svg(repo, blobs, cache_dir),
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


def run_website_ingestion(
    engine_cache_dir: str,
    job_id: str,
    *,
    capture: _CaptureCallable = _default_capture,
    build_evidence: _BuildEvidenceCallable = _default_build_evidence,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
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
        )

    run_ingestion_job(store, job_id, work)


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
) -> "tuple[str, int, Optional[str]]":
    job = store.require(job_id)
    request = job["request"]
    url = request["url"]
    force_render = bool(request.get("force_render", False))
    requested_kit_id = request.get("brand_kit_id")
    requested_name = request.get("name")

    outcome = asyncio.run(capture(url, reporter=reporter, force_render=force_render))
    evidence = build_evidence(
        outcome, core=core, store_root=cache_dir, reporter=reporter
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
    # ingestion kit (product_ready=False — the human reviews before publish).
    validation = core.validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    if not validation.get("ok"):
        codes = sorted(
            {
                str(d.get("code"))
                for d in validation.get("diagnostics") or []
                if d.get("severity") == "error"
            }
        )
        raise RuntimeError(f"ingested brand kit failed draft validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary_response = core.summarize_brand_kit(validated_kit, raise_on_error=False)
    summary = summary_response.get("brand_summary") or {}
    summary["ingestion"] = result.ingestion_report

    diagnostics = (
        result.diagnostics
        + _capture_diagnostics(outcome)
        + _validation_diagnostics(validation)
        + describe_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
        brand_kit=validated_kit,
        brand_summary=summary,
        diagnostics=diagnostics,
        source="website",
        job_derived_id=requested_kit_id is None,
    )

    evidence_json = _evidence_dump(evidence)
    return (record["brand_kit_id"], int(record["version"]), evidence_json)


def _kit_name(evidence: Any, url: str) -> str:
    narrative = getattr(evidence, "narrative", None)
    brand_name = getattr(narrative, "brand_name", None) if narrative else None
    if brand_name:
        return brand_name
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    return host or url


def _evidence_dump(evidence: Any) -> Optional[str]:
    """Dump BrandEvidence to JSON for the job row (it carries no raw bytes)."""
    if evidence is None:
        return None
    if hasattr(evidence, "model_dump"):
        return json.dumps(evidence.model_dump(), sort_keys=True, separators=(",", ":"))
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"))


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

    run_ingestion_job(store, job_id, work)


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
        raise RuntimeError(f"ingested brand kit failed draft validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary_response = core.summarize_brand_kit(validated_kit, raise_on_error=False)
    summary = summary_response.get("brand_summary") or {}
    summary["ingestion"] = result.ingestion_report

    diagnostics = (
        result.diagnostics
        + _pdf_extraction_diagnostics(extraction)
        + _validation_diagnostics(validation)
        + describe_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
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

    run_ingestion_job(store, job_id, work)


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
        raise RuntimeError(f"ingested brand kit failed draft validation: {codes}")
    validated_kit = validation.get("brand_kit") or kit
    summary_response = core.summarize_brand_kit(validated_kit, raise_on_error=False)
    summary = summary_response.get("brand_summary") or {}
    summary["ingestion"] = result.ingestion_report

    diagnostics = (
        result.diagnostics
        + analyze_diagnostics
        + _validation_diagnostics(validation)
        + describe_diagnostics
    )

    record = _publish_ingested_kit(
        tools,
        repo,
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
