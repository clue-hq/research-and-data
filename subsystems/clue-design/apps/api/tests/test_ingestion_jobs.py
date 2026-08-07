from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lumen_api.database import Repository, connect, run_migrations
from lumen_api.design_store import HybridRepository
from lumen_ingestion.jobs import (
    IngestionJobStore,
    new_id,
    run_ingestion_job,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _frozen_clock():
    ticks = iter(f"2026-01-01T00:00:{s:02d}+00:00" for s in range(60))

    def now_iso() -> str:
        return next(ticks)

    return now_iso


def _store(tmp_path: Path) -> IngestionJobStore:
    database_path = tmp_path / "api.sqlite3"
    run_migrations(database_path)
    connection = connect(database_path)
    return IngestionJobStore(connection, now_iso=_frozen_clock())


def test_create_running_stage_complete_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
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
    assert staged["progress"] == 0.4

    done = store.complete(job_id, "kit_1", 3, '{"schema_version": 1}')
    assert done["status"] == "succeeded"
    assert done["progress"] == 1
    assert done["brand_kit_id"] == "kit_1"
    assert done["brand_kit_version"] == 3
    assert done["evidence"] == {"schema_version": 1}
    assert done["error"] is None


def test_run_ingestion_job_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
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
    database_path = tmp_path / "api.sqlite3"
    run_migrations(database_path)
    repo = HybridRepository(connect(database_path))
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


def test_migration_idempotent_fresh_and_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "api.sqlite3"
    # Fresh apply.
    run_migrations(database_path)
    repo = HybridRepository(connect(database_path))
    repo.create_brand_kit(*_minimal_kit_row("website"))
    repo.connection.close()

    # Re-open: run_migrations runs again (re-runs 007's rebuild). Data must
    # survive and the ingestion_jobs table stays usable.
    run_migrations(database_path)
    repo2 = HybridRepository(connect(database_path))
    kept = repo2.require_brand_kit("kit_website", 1)
    assert kept["source"] == "website"
    store = IngestionJobStore(connect(database_path))
    job = store.create("website", {"url": "https://x.example"})
    assert job["status"] == "queued"


def _apply_pre_007(database_path: Path) -> None:
    """Apply migrations 001-006 only, to build a pre-007 database."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration.name >= "007":
            continue
        connection.executescript(migration.read_text())
    connection.commit()
    connection.close()


def test_upgrade_from_pre_007_preserves_brand_kit_and_fk_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "api.sqlite3"
    _apply_pre_007(database_path)

    # Insert a kit + a compatibility report referencing it via FK, before 007.
    connection = sqlite3.connect(str(database_path))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO brand_kits (
          brand_kit_id, version, name, approval_status, product_ready,
          source, brand_kit_json, brand_summary_json, diagnostics_json,
          created_at, updated_at
        )
        VALUES ('kit_old', 1, 'Old Kit', 'draft', 0, 'manual', '{}', '{}',
                '[]', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
        """
    )
    connection.execute(
        """
        INSERT INTO brand_compatibility_reports (
          report_id, from_brand_kit_id, from_version, to_brand_kit_id,
          to_version, report_json, diagnostics_json, created_at
        )
        VALUES ('rep_old', 'kit_old', 1, 'kit_old', 1, '{}', '[]',
                '2026-01-01T00:00:00+00:00')
        """
    )
    connection.commit()
    connection.close()

    # Now apply 007 (via run_migrations, exactly as create_app would).
    run_migrations(database_path)

    verify = connect(database_path)
    kit = verify.execute(
        "SELECT source FROM brand_kits WHERE brand_kit_id = 'kit_old'"
    ).fetchone()
    assert kit is not None and kit["source"] == "manual"
    # FK row not orphaned / cascaded away by the rebuild.
    report = verify.execute(
        "SELECT report_id FROM brand_compatibility_reports WHERE report_id = 'rep_old'"
    ).fetchone()
    assert report is not None
    assert verify.execute("PRAGMA foreign_key_check").fetchall() == []
    # New CHECK now admits ingestion sources.
    verify.execute(
        """
        INSERT INTO brand_kits (
          brand_kit_id, version, name, approval_status, product_ready,
          source, brand_kit_json, brand_summary_json, diagnostics_json,
          created_at, updated_at
        )
        VALUES ('kit_new', 1, 'New', 'draft', 0, 'website', '{}', '{}', '[]',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
        """
    )
    verify.commit()
    verify.close()
