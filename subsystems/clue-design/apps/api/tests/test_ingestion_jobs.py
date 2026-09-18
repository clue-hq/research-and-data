from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lumen_api.design_store import HybridRepository
from lumen_ingestion.jobs import (
    IngestionJobStore,
    new_id,
    run_ingestion_job,
)

def _store(tmp_path: Path) -> IngestionJobStore:
    return IngestionJobStore()


def _seed_kit(tmp_path: Path, brand_kit_id: str, version: int = 1) -> None:
    """D2.3: the job's result pointer is a REAL composite FK to design_brand_kit now (SQLite
    only back-linked it by convention), so a completing job needs its kit to exist."""
    repo = HybridRepository()
    repo.create_brand_kit(
        {
            "id": brand_kit_id,
            "version": version,
            "name": brand_kit_id,
            "approval_status": "draft",
        },
        {"product_ready": False},
        [],
        "website",
    )


def test_create_running_stage_complete_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_kit(tmp_path, "kit_1", 3)
    job = store.create("website", {"url": "https://insighthealth.example"})
    assert job["status"] == "queued"
    assert job["stage"] is None
    assert job["progress"] == 0
    assert job["request"] == {"url": "https://insighthealth.example"}
    assert job["created_at"] == job["updated_at"]
    job_id = job["job_id"]

    running = store.set_running(job_id)
    assert running["status"] == "running"

    staged = store.set_stage(job_id, "Visiting your website…", 0.4)
    assert staged["stage"] == "Visiting your website…"
    # D2.3: design_ingestion_job.progress is a PG `real` (float4), so a non-dyadic fraction
    # round-trips at single precision (0.4 -> 0.40000000596…). SQLite's REAL was a double.
    # Harmless for a 0..1 progress bar; asserted approximately rather than papered over.
    assert staged["progress"] == pytest.approx(0.4)

    done = store.complete(job_id, "kit_1", 3, '{"schema_version": 1}')
    assert done["status"] == "succeeded"
    assert done["progress"] == 1
    assert done["brand_kit_id"] == "kit_1"
    assert done["brand_kit_version"] == 3
    assert done["evidence"] == {"schema_version": 1}
    assert done["error"] is None


def test_run_ingestion_job_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_kit(tmp_path, "kit_pdf")
    job_id = store.create("pdf", {"filename": "brand.pdf"})["job_id"]
    seen: list[tuple[str, float]] = []

    def work(report):
        report("Reading your PDF…", 0.5)
        seen.append(("done", 1.0))
        return ("kit_pdf", 1, None)

    run_ingestion_job(store, job_id, work)

    job = store.require(job_id)
    assert job["status"] == "succeeded"
    assert job["brand_kit_id"] == "kit_pdf"
    assert job["brand_kit_version"] == 1
    assert job["evidence"] is None
    assert seen == [("done", 1.0)]
    # the reporter persisted the intermediate stage
    assert job["progress"] == 1


def test_run_ingestion_job_failure_stores_error_and_never_raises(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    job_id = store.create("website", {"url": "https://x.example"})["job_id"]

    def work(report):
        report("Visiting your website…", 0.2)
        raise RuntimeError("capture exploded")

    # Must not raise.
    run_ingestion_job(store, job_id, work)

    job = store.require(job_id)
    assert job["status"] == "failed"
    assert job["error"] is not None
    assert "capture exploded" in job["error"]["message"]
    assert job["error"]["code"] == "LUMI0401"
    assert job["brand_kit_id"] is None


def test_a_provider_that_refuses_to_sell_gets_its_own_failure_code(tmp_path: Path) -> None:
    """Lane 3 slice 5: an out-of-credit OpenRouter key is not "this stage did not work".

    The ingestion model clients swallow every other failure and fall back; a ``ProviderHalted``
    is the one they re-raise, and the job's terminal code names the provider and the reason so an
    operator reads "top up the key" rather than a generic stage failure.
    """
    from clue_spend import ProviderHalted

    store = _store(tmp_path)
    job_id = store.create("website", {"url": "https://x.example"})["job_id"]

    def work(report):
        raise ProviderHalted("openrouter", "payment_required", http_status=402)

    run_ingestion_job(store, job_id, work)

    job = store.require(job_id)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "provider_refused:openrouter:payment_required"
    assert job["brand_kit_id"] is None


def test_get_missing_job_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get("ingest_nope") is None
    with pytest.raises(KeyError):
        store.require("ingest_nope")


def test_new_id_prefix() -> None:
    ident = new_id("ingest")
    assert ident.startswith("ingest_")
    assert len(ident) > len("ingest_")


def _minimal_kit_row(source: str) -> tuple[dict, dict, list, str]:
    brand_kit = {
        "id": f"kit_{source}",
        "version": 1,
        "name": f"{source} kit",
        "approval_status": "draft",
    }
    brand_summary = {"product_ready": False}
    diagnostics: list = []
    return brand_kit, brand_summary, diagnostics, source


def test_brand_kits_source_check_accepts_website(tmp_path: Path) -> None:
    repo = HybridRepository()
    for source in ("website", "pdf", "asset_upload"):
        brand_kit, brand_summary, diagnostics, src = _minimal_kit_row(source)
        row = repo.create_brand_kit(brand_kit, brand_summary, diagnostics, src)
        assert row["source"] == source
    # legacy sources still accepted
    brand_kit, brand_summary, diagnostics, src = _minimal_kit_row("manual")
    assert (
        repo.create_brand_kit(brand_kit, brand_summary, diagnostics, src)["source"]
        == "manual"
    )
    # unknown source still rejected by the rebuilt CHECK
    brand_kit, brand_summary, diagnostics, _ = _minimal_kit_row("bogus")
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_brand_kit(brand_kit, brand_summary, diagnostics, "bogus")

# D2.5B DELETED the SQLite migration tests that lived here (migration idempotence on reopen,
# the pre-007 upgrade/FK-preservation walk, and the 007 rebuild-on-boot check): their subject —
# `run_migrations`, `apps/api/migrations/*.sql`, and the SQLite tables themselves — no longer
# exists. Schema evolution is Alembic's, covered by `make db-smoke` and the platform suite.
