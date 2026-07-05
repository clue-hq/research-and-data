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
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from lumen_api.database import Repository, connect

from .jobs import IngestionJobStore, StageReporter, run_ingestion_job
from .normalizer import normalize_evidence

JsonObject = dict[str, Any]


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


def run_website_ingestion(
    database_path: str | Path,
    asset_store_root: str,
    job_id: str,
    *,
    capture: _CaptureCallable = _default_capture,
    build_evidence: _BuildEvidenceCallable = _default_build_evidence,
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
                asset_store_root=asset_store_root,
                job_id=job_id,
                reporter=reporter,
                capture=capture,
                build_evidence=build_evidence,
            )

        run_ingestion_job(store, job_id, work)
    finally:
        connection.close()


def _ingest(
    *,
    store: IngestionJobStore,
    repo: Repository,
    core: Any,
    asset_store_root: str,
    job_id: str,
    reporter: StageReporter,
    capture: _CaptureCallable,
    build_evidence: _BuildEvidenceCallable,
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
                asset_store_root=asset_store_root,
                job_id=job_id,
                reporter=reporter,
                extract=extract,
            )

        run_ingestion_job(store, job_id, work)
    finally:
        connection.close()


def _ingest_pdf(
    *,
    store: IngestionJobStore,
    repo: Repository,
    core: Any,
    asset_store_root: str,
    job_id: str,
    reporter: StageReporter,
    extract: _ExtractPdfCallable,
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
