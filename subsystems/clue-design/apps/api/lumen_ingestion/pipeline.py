"""`run_website_ingestion` — the website ingestion job glue (slice 1 §9).

Wires the capture package (Agent A) to slice-0's normalizer and the persistence
API, running inside a FastAPI ``BackgroundTasks`` worker. The whole thing is
driven through ``run_ingestion_job`` from slice 0 so it *never raises*: every
failure lands on the job row instead.

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
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from lumen_api.database import Repository, connect

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
        connection: Any,
        describer: Any,
        resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
        reporter: Callable[[str, float], None],
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

    if os.environ.get("LUMEN_INGESTION_DESCRIBE") == "1":
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
    connection: Any,
    describer: Any,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    reporter: Callable[[str, float], None],
) -> Any:
    """Lazily resolve Agent A's ``apply_descriptions`` and call it.

    Raises ``ImportError`` when describe.py is absent — callers wrap this in
    ``_maybe_describe`` which swallows that into a debug-level pass-through.
    """
    from .describe import apply_descriptions

    return apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=resolve_bytes,
        reporter=reporter,
    )


def _maybe_describe(
    evidence: Any,
    *,
    connection: Any,
    repo: Repository,
    asset_store_root: str,
    reporter: Callable[[str, float], None],
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> Any:
    """Stamp AI descriptions onto ``evidence`` — a guaranteed no-op when
    describe.py is absent or errors.

    Wraps the lazy ``apply_descriptions`` import in ``try/except ImportError``
    with a debug-level pass-through so the website + PDF suites stay green even
    if Agent A's describe.py lands after this code. Any other unexpected error
    is likewise swallowed (evidence returned unchanged) so a description-engine
    hiccup never fails an otherwise-good ingest.
    """
    apply = apply_descriptions or _default_apply_descriptions
    describer = describer if describer is not None else resolve_describer()
    resolve_bytes = _make_resolve_bytes(repo, asset_store_root)
    try:
        return apply(
            evidence,
            connection=connection,
            describer=describer,
            resolve_bytes=resolve_bytes,
            reporter=reporter,
        )
    except ImportError:
        logger.debug("describe.py unavailable; skipping description pass")
        return evidence
    except Exception:  # never let the description engine fail the ingest
        logger.debug("apply_descriptions failed; skipping", exc_info=True)
        return evidence


def _make_resolve_bytes(
    repo: Repository, asset_store_root: str
) -> Callable[[str], "tuple[bytes, str] | None"]:
    """Build the ``resolve_bytes`` callable (§1): asset_id → (bytes, mime) via
    ``Repository.require_asset_record`` → ``media.location.opaque_ref`` (provider
    ``local-store``) → store path. Mirrors main.py ``get_asset_bytes``. Returns
    ``None`` for ANY miss — never raises."""
    root = Path(asset_store_root).resolve()

    def resolve_bytes(asset_id: str) -> "tuple[bytes, str] | None":
        try:
            stored = repo.require_asset_record(asset_id)
        except Exception:
            return None
        record = stored.get("asset") or {}
        media = record.get("media") or {}
        location = media.get("location") or {}
        opaque_ref = location.get("opaque_ref")
        if location.get("provider") != "local-store" or not opaque_ref:
            return None
        candidate = (root / opaque_ref).resolve()
        if root != candidate and root not in candidate.parents:
            return None
        if not candidate.is_file():
            return None
        try:
            data = candidate.read_bytes()
        except OSError:
            return None
        mime = media.get("mime_type") or "application/octet-stream"
        return (data, mime)

    return resolve_bytes


def run_website_ingestion(
    database_path: str | Path,
    asset_store_root: str,
    job_id: str,
    *,
    capture: _CaptureCallable = _default_capture,
    build_evidence: _BuildEvidenceCallable = _default_build_evidence,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> None:
    """Run a website ingestion job to a terminal state. Never raises.

    Safe for ``BackgroundTasks``: opens its own sqlite connection, builds an
    ``IngestionJobStore``, and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row).
    """
    connection = connect(Path(database_path))
    try:
        store = IngestionJobStore(connection)
        repo = Repository(connection)
        core = _core_client()

        def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
            return _ingest(
                store=store,
                repo=repo,
                core=core,
                connection=connection,
                asset_store_root=asset_store_root,
                job_id=job_id,
                reporter=reporter,
                capture=capture,
                build_evidence=build_evidence,
                describer=describer,
                apply_descriptions=apply_descriptions,
            )

        run_ingestion_job(store, job_id, work)
    finally:
        connection.close()


def _ingest(
    *,
    store: IngestionJobStore,
    repo: Repository,
    core: Any,
    connection: Any,
    asset_store_root: str,
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
        outcome, core=core, store_root=asset_store_root, reporter=reporter
    )

    evidence = _maybe_describe(
        evidence,
        connection=connection,
        repo=repo,
        asset_store_root=asset_store_root,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
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
    )

    record = repo.create_brand_kit(validated_kit, summary, diagnostics, "website")

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
    database_path: str | Path,
    asset_store_root: str,
    job_id: str,
    *,
    extract: _ExtractPdfCallable = _default_extract_pdf,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> None:
    """Run a PDF ingestion job to a terminal state. Never raises.

    Safe for ``BackgroundTasks``: opens its own sqlite connection, builds an
    ``IngestionJobStore``, and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row). The uploaded PDF bytes are read
    from ``request["tmp_path"]`` and that tmp file is always deleted before the
    job reaches a terminal state.
    """
    connection = connect(Path(database_path))
    try:
        store = IngestionJobStore(connection)
        repo = Repository(connection)
        core = _core_client()

        def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
            return _ingest_pdf(
                store=store,
                repo=repo,
                core=core,
                connection=connection,
                asset_store_root=asset_store_root,
                job_id=job_id,
                reporter=reporter,
                extract=extract,
                describer=describer,
                apply_descriptions=apply_descriptions,
            )

        run_ingestion_job(store, job_id, work)
    finally:
        connection.close()


def _ingest_pdf(
    *,
    store: IngestionJobStore,
    repo: Repository,
    core: Any,
    connection: Any,
    asset_store_root: str,
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
    tmp_path = request.get("tmp_path")

    try:
        if not tmp_path or not os.path.exists(tmp_path):
            raise RuntimeError(
                f"LUMI0605: uploaded PDF tmp file was not found (tmp_path={tmp_path!r})"
            )
        pdf_bytes = Path(tmp_path).read_bytes()

        extraction = extract(
            pdf_bytes,
            filename,
            core=core,
            store_root=asset_store_root,
            reporter=reporter,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    evidence = getattr(extraction, "evidence", extraction)

    evidence = _maybe_describe(
        evidence,
        connection=connection,
        repo=repo,
        asset_store_root=asset_store_root,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
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
    )

    record = repo.create_brand_kit(validated_kit, summary, diagnostics, "pdf")

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
    database_path: str | Path,
    asset_store_root: str,
    job_id: str,
    *,
    analyze: _AnalyzeUploadsCallable = _default_analyze_uploads,
    describer: Any | None = None,
    apply_descriptions: _ApplyDescriptionsCallable | None = None,
) -> None:
    """Run an asset-upload ingestion job to a terminal state. Never raises.

    Safe for ``BackgroundTasks``: opens its own sqlite connection, builds an
    ``IngestionJobStore``, and hands the work to ``run_ingestion_job`` (which
    captures any exception onto the job row). The uploaded files live in tmp
    files listed in ``request["files"][*]["tmp_path"]`` and are always deleted
    before the job reaches a terminal state.
    """
    connection = connect(Path(database_path))
    try:
        store = IngestionJobStore(connection)
        repo = Repository(connection)
        core = _core_client()

        def work(reporter: StageReporter) -> "tuple[str, int, Optional[str]]":
            return _ingest_assets(
                store=store,
                repo=repo,
                core=core,
                connection=connection,
                asset_store_root=asset_store_root,
                job_id=job_id,
                reporter=reporter,
                analyze=analyze,
                describer=describer,
                apply_descriptions=apply_descriptions,
            )

        run_ingestion_job(store, job_id, work)
    finally:
        connection.close()


def _ingest_assets(
    *,
    store: IngestionJobStore,
    repo: Repository,
    core: Any,
    connection: Any,
    asset_store_root: str,
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
    tmp_paths = [spec.get("tmp_path") for spec in file_specs]

    try:
        inputs: list[Any] = []
        for spec in file_specs:
            tmp_path = spec.get("tmp_path")
            if not tmp_path or not os.path.exists(tmp_path):
                raise RuntimeError(
                    "LUMI0605: uploaded asset tmp file was not found "
                    f"(tmp_path={tmp_path!r})"
                )
            inputs.append(
                _upload_file_input(
                    filename=spec.get("filename") or Path(tmp_path).name,
                    content_type=spec.get("content_type"),
                    data=Path(tmp_path).read_bytes(),
                )
            )

        analysis = analyze(
            inputs,
            core=core,
            store_root=asset_store_root,
            reporter=reporter,
        )
    finally:
        for tmp_path in tmp_paths:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # ``analyze_uploads`` returns (evidence, diagnostics); tolerate a bare
    # evidence return from simpler stubs too.
    if isinstance(analysis, tuple):
        evidence, analyze_diagnostics = analysis[0], list(analysis[1] or [])
    else:
        evidence, analyze_diagnostics = analysis, []

    evidence = _maybe_describe(
        evidence,
        connection=connection,
        repo=repo,
        asset_store_root=asset_store_root,
        reporter=reporter,
        describer=describer,
        apply_descriptions=apply_descriptions,
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
        result.diagnostics + analyze_diagnostics + _validation_diagnostics(validation)
    )

    record = repo.create_brand_kit(validated_kit, summary, diagnostics, "asset_upload")

    evidence_json = _evidence_dump(evidence)
    return (record["brand_kit_id"], int(record["version"]), evidence_json)


def _asset_kit_name(evidence: Any, file_count: int) -> str:
    narrative = getattr(evidence, "narrative", None)
    brand_name = getattr(narrative, "brand_name", None) if narrative else None
    if brand_name:
        return brand_name
    return f"Uploaded assets ({file_count} files)"
