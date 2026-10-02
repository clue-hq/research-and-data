"""Plan 1 item A backfill: a stored kit whose evidence carried px/16 type units is re-derived
from that evidence (corrected in memory), published as a NEW immutable version, and the
documents pinned to the old version follow it when asked. Throwaway DSN only."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from clue_design.envelopes import DesignIngestionEnvelope
from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "rederive_kit_type_units.py"
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
EVIDENCE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"
)


def load_script():
    spec = importlib.util.spec_from_file_location("rederive_kit_type_units", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec_module (the documented importlib recipe): the script pairs
    # `from __future__ import annotations` with @dataclass, and CPython resolves the string
    # annotation through `sys.modules.get(cls.__module__)`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


@pytest.fixture()
def conn():
    dsn = (
        os.environ["CLUE_DATABASE_URL"]
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    with psycopg.connect(dsn) as connection:
        yield connection


def _evidence_with_px16_headline() -> dict:
    evidence = json.loads(EVIDENCE_FIXTURE.read_text())
    evidence["type_samples"] = [
        {
            "label": "h1",
            "family": "Aeonik",
            "weight": 600,
            "size_px": 72.0,
            "line_height": 4.5,
            "letter_spacing": -0.045,
            "pointer": {"source": "website", "locator": "rendered :: h1"},
        },
        {
            "label": "body",
            "family": "Aeonik",
            "weight": 400,
            "size_px": 18.0,
            "line_height": 1.6875,
            "letter_spacing": 0.0105,
            "pointer": {"source": "website", "locator": "rendered :: body"},
        },
    ]
    return evidence


def _publish_kit_from_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, evidence: dict
) -> tuple[str, int]:
    """Drive the real website pipeline in-process (fake capture + fake evidence), exactly as
    tests/test_ingestion_font_decode.py does, so the kit row, its job row, and the job's
    evidence_json are all real. Returns (brand_kit_id, version).

    The job row is created directly and executed through the WORKER ENTRY, never OFFERED: an
    offered job goes on the shared `design_job` queue where a co-running design API on the same
    DSN would claim it and run the REAL capture.
    """
    from lumen_api import main as main_module
    from lumen_api.main import execute_ingestion_job
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.jobs import IngestionJobStore
    from lumen_ingestion.pipeline import run_website_ingestion

    async def fake_capture(url, *, reporter, force_render=False, page_urls=None):
        class Outcome:
            tier = "static"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        return BrandEvidence.model_validate(evidence)

    monkeypatch.setattr(
        main_module,
        "run_website_ingestion",
        lambda cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None: (
            run_website_ingestion(
                cache_dir,
                job_id,
                capture=fake_capture,
                build_evidence=fake_build_evidence,
                workspace_id=workspace_id,
                storage=storage,
                expected_generation=expected_generation,
            )
        ),
    )

    workspace_id = HybridRepository().workspace_id
    store = IngestionJobStore(workspace_id=workspace_id)
    job = store.create("website", {"url": "https://rederive.example"})
    state = client.app.state
    status = execute_ingestion_job(
        DesignIngestionEnvelope(
            kind="ingestion",
            work_id=uuid4(),
            workspace_id=workspace_id,
            job_id=job["job_id"],
            ingestion_kind="website",
        ),
        host=SimpleNamespace(storage=state.storage, engine_cache_root=state.engine_cache_root),
    )
    assert status == "succeeded", status
    finished = store.require(job["job_id"])
    return finished["brand_kit_id"], int(finished["brand_kit_version"])


def _create_document(client: TestClient, title: str) -> dict:
    """One scene document with an id of its own (the fixture scene names itself)."""
    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    scene["meta"]["id"] = f"doc_{uuid4().hex[:12]}"
    response = client.post("/documents", json={"title": title, "scene": scene})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def _pin_document(conn, workspace_id: str, document_id: str, kit_id: str, version: int) -> None:
    conn.execute(
        "UPDATE design_document SET effective_brand_kit_id=%s, effective_brand_kit_version=%s,"
        " effective_brand_kit_source='brand_kit_library' WHERE id=%s AND workspace_id=%s",
        (kit_id, version, document_id, workspace_id),
    )
    conn.commit()


def test_dry_run_reports_and_writes_nothing(
    client: TestClient, conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_id, version = _publish_kit_from_evidence(
        client, monkeypatch, _evidence_with_px16_headline()
    )
    script = load_script()
    summary = script.rederive_kit_type_units(
        conn,
        workspace_id=HybridRepository().workspace_id,
        brand_kit_id=kit_id,
        apply=False,
        repin_documents=False,
    )
    assert summary.examined == 1 and summary.changed == 1 and summary.published == 0
    latest = HybridRepository().require_brand_kit(kit_id)
    assert latest["version"] == version


def test_apply_publishes_the_next_version_with_corrected_units_and_repins(
    client: TestClient, conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = HybridRepository().workspace_id
    kit_id, version = _publish_kit_from_evidence(
        client, monkeypatch, _evidence_with_px16_headline()
    )
    before = HybridRepository().require_brand_kit(kit_id)["brand_kit"]
    # Task 2's guard already kept 4.5 out of the kit; the derived default (1.1) is what v1 holds.
    assert before["tokens"]["typography"]["type.headline"]["value"]["default"]["line_height"] == 1.1

    doc = _create_document(client, "pinned")
    _pin_document(conn, workspace_id, doc["id"], kit_id, version)

    script = load_script()
    summary = script.rederive_kit_type_units(
        conn,
        workspace_id=workspace_id,
        brand_kit_id=kit_id,
        apply=True,
        repin_documents=True,
    )
    assert summary.published == 1 and summary.repinned_documents == 1

    after = HybridRepository().require_brand_kit(kit_id)
    assert after["version"] == version + 1
    headline = after["brand_kit"]["tokens"]["typography"]["type.headline"]["value"]["default"]
    assert headline["line_height"] == 1.0  # 4.5 × 16 = 72px over 72px
    assert headline["letter_spacing"] == -0.01  # -0.045 × 16 = -0.72px over 72px
    body = after["brand_kit"]["tokens"]["typography"]["type.body"]["value"]["default"]
    # Rendered samples are ALWAYS px-derived, so body becomes 1.6875 × 16 / 18 = 1.5.
    assert body["line_height"] == 1.5
    assert any(d["code"] == "LUMI0233" for d in after["diagnostics"])
    # Everything else in the kit is byte-identical.
    for path, style in after["brand_kit"]["tokens"]["typography"].items():
        for key, value in style["value"]["default"].items():
            if key not in ("line_height", "letter_spacing"):
                assert before["tokens"]["typography"][path]["value"]["default"][key] == value

    row = conn.execute(
        "SELECT effective_brand_kit_version FROM design_document WHERE id=%s", (doc["id"],)
    ).fetchone()
    assert row[0] == version + 1


def test_a_kit_with_no_stored_evidence_is_skipped_loudly(
    client: TestClient, conn, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_id, _ = _publish_kit_from_evidence(client, monkeypatch, _evidence_with_px16_headline())
    conn.execute(
        "UPDATE design_ingestion_job SET evidence_json=NULL WHERE brand_kit_id=%s", (kit_id,)
    )
    conn.commit()
    summary = load_script().rederive_kit_type_units(
        conn,
        workspace_id=HybridRepository().workspace_id,
        brand_kit_id=kit_id,
        apply=True,
        repin_documents=False,
    )
    assert summary.skipped_no_evidence == 1 and summary.published == 0
    assert "no stored evidence" in capsys.readouterr().out


#: A kit id that sorts FIRST inside the workspace (`_latest_kits` orders by brand_kit_id), so the
#: stub row is swept BEFORE the healthy kit and a regression to the old abort-the-run behaviour
#: costs the healthy kit its publish.
STUB_KIT_ID = "brand_kit_ing_" + "0" * 32


def _clone_kit_with_stub_evidence(
    conn, workspace_id: str, source_kit_id: str, source_version: int, new_kit_id: str
) -> None:
    """A second kit whose ingestion job never got past its stub `{"schema_version": 1}`.

    Cloned in SQL rather than driven through the pipeline a second time: the kit row is a REAL
    kit row (byte-copied from the healthy one) and the job row is the exact shape the colombo
    database carries, without a second ~40s ingestion-brief model call.
    """
    conn.execute(
        "INSERT INTO design_brand_kit (brand_kit_id, version, workspace_id, brand_id, name,"
        " approval_status, product_ready, source, brand_kit_json, brand_summary_json,"
        " diagnostics_json)"
        " SELECT %s, version, workspace_id, brand_id, name, approval_status, product_ready,"
        " source, brand_kit_json, brand_summary_json, diagnostics_json FROM design_brand_kit"
        " WHERE brand_kit_id=%s AND version=%s AND workspace_id=%s",
        (new_kit_id, source_kit_id, source_version, workspace_id),
    )
    conn.execute(
        "INSERT INTO design_ingestion_job (job_id, workspace_id, kind, status, request_json,"
        " evidence_json, brand_kit_id, brand_kit_version)"
        " VALUES (%s, %s, 'website', 'succeeded', %s::jsonb, %s::jsonb, %s, %s)",
        (
            f"job_stub_{uuid4().hex[:12]}",
            workspace_id,
            json.dumps({"url": "https://stub.example"}),
            json.dumps({"schema_version": 1}),
            new_kit_id,
            source_version,
        ),
    )
    conn.commit()


def test_a_kit_whose_stored_evidence_is_a_stub_is_skipped_and_the_sweep_continues(
    client: TestClient, conn, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The colombo abort: `{"schema_version": 1}` fails `BrandEvidence` validation, and before
    the fix that ValidationError escaped the per-kit guard and killed the run for every kit
    after it. The stub kit sorts first here, so a regression costs the healthy kit its publish.
    """
    workspace_id = HybridRepository().workspace_id
    healthy_kit_id, version = _publish_kit_from_evidence(
        client, monkeypatch, _evidence_with_px16_headline()
    )
    _clone_kit_with_stub_evidence(conn, workspace_id, healthy_kit_id, version, STUB_KIT_ID)
    assert STUB_KIT_ID < healthy_kit_id, "the stub kit must be swept first"

    summary = load_script().rederive_kit_type_units(
        conn,
        workspace_id=workspace_id,
        brand_kit_id=None,
        apply=True,
        repin_documents=False,
    )

    assert summary.examined == 2
    assert summary.skipped_no_evidence == 1
    assert summary.failed == 0
    # The sweep did NOT stop: the healthy kit behind the stub was still re-derived and published.
    assert summary.changed == 1 and summary.published == 1

    out = capsys.readouterr().out
    assert f"SKIP {workspace_id}/{STUB_KIT_ID} v{version}" in out
    assert "stored evidence is not a usable BrandEvidence" in out
    assert "source: Field required" in out

    # Nothing was published for the stub kit; the healthy kit moved on by one.
    assert HybridRepository().require_brand_kit(STUB_KIT_ID)["version"] == version
    assert HybridRepository().require_brand_kit(healthy_kit_id)["version"] == version + 1
