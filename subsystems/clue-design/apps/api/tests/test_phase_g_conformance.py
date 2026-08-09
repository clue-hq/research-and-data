"""Phase G conformance gate (slice G10).

Acceptance criteria (wave plan, Track D):
- deterministic 100-instance batch from seeded binding sets;
- zero silent overflows: every fit issue surfaces in InstanceFitReports;
- QR scan-verified on a sampled instance artifact (PNG and the
  raster-flattened PDF per the B3 verdict);
- re-derivation idempotence;
- complete bulk-export manifest.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
MAILER_REVISION_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/conformance/phase_g_mailer_revision.json"
)

FIRST_NAMES = [
    "Priya", "Adaeze", "Liang", "Mateo", "Ingrid", "Tomasz", "Yuki", "Amara",
    "Declan", "Sofia", "Ravi", "Helena", "Oluwaseun", "Marta", "Kenji", "Aisha",
]
LAST_NAMES = [
    "Sharma", "Okafor", "Chen", "Alvarez", "Lindqvist", "Kowalski", "Tanaka",
    "Mensah", "O'Sullivan", "Rossi", "Iyer", "Novak", "Adeyemi", "Silva",
]
CTAS = [
    "Book your demo",
    "See the platform live",
    "Reserve your onboarding session",
    "Start your pilot this quarter",
]
INSIGHTS = [
    "Reduced patient wait times by 38%",
    "Cut intake admin workload in half",
    "Integrated with Epic in two weeks",
    "Unified nineteen scheduling systems without downtime",
    "Recovered four thousand staff hours annually",
    "Raised patient satisfaction by twenty-two points",
]
QUOTES = [
    "Their team shipped twice as fast as any vendor we have worked with.",
    "The rollout was the smoothest our clinics have ever seen.",
    "Adoption hit ninety percent in the first month.",
]
# Deliberate overflows: cannot fit the 120mm headline box even at the
# ShrinkFont minimum of 6 — these MUST surface as overflow verdicts.
OVERFLOW_NAMES = [
    "Dr. Maximiliana Alexandra Whitmore-Kensington of Bartholomew House",
    "Professor Konstantina Alexandropoulou-Papadimitriou the Magnificent",
]
# Long-but-recoverable names: ShrinkFont resolves them between 6 and 10.
SHRINK_NAMES = [
    "Dr. Alexandra Montgomery-Hayes",
    "Dr. Bartholomew Quincy Adeyemi",
]

BATCH_SIZE = 100
OVERFLOW_EVERY = 20  # instances 0, 20, 40, 60, 80 overflow deliberately
SHRINK_EVERY = 7


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def seeded_binding_sets(count: int, logo_asset_id: str) -> list[dict]:
    rng = random.Random(42)
    bindings = []
    for index in range(count):
        if index % OVERFLOW_EVERY == 0:
            name = OVERFLOW_NAMES[index // OVERFLOW_EVERY % len(OVERFLOW_NAMES)]
        elif index % SHRINK_EVERY == 0:
            name = SHRINK_NAMES[index // SHRINK_EVERY % len(SHRINK_NAMES)]
        else:
            name = (
                f"Dr. {rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            )
        insights = rng.sample(INSIGHTS, rng.randint(1, 4))
        values = {
            "contact.full_name": {"kind": "text", "value": name},
            "account.logo": {"kind": "asset", "asset_id": logo_asset_id},
            "campaign.cta": {"kind": "text", "value": rng.choice(CTAS)},
            "research.key_insights": {
                "kind": "list",
                "items": [{"kind": "text", "value": text} for text in insights],
            },
        }
        if rng.random() < 0.7:
            values["research.quote"] = {
                "kind": "text",
                "value": rng.choice(QUOTES),
            }
        bindings.append(
            {
                "schema_version": 1,
                "binding_set_id": f"bind_conf_{index:03d}",
                "template_revision_id": "tmpl_mailer_v1",
                "audience": {
                    "account_id": f"acct_{index:03d}",
                    "contact_id": f"ct_{index:03d}",
                },
                "values": values,
                "links": {
                    "landing_page": {
                        "url": f"https://go.example.com/conf/{index:03d}"
                    }
                },
                "generated": {
                    "qr_landing": {
                        "provider": "qr",
                        "input": {
                            "url_from": "links.landing_page.url",
                            "ec_level": "h",
                        },
                        "bind_to_slot": "campaign.qr",
                    }
                },
            }
        )
    return bindings


def setup_revision_and_logo(client: TestClient) -> str:
    from PIL import Image

    scene = json.loads(MAILER_REVISION_PATH.read_text())
    scene["meta"]["id"] = "doc_conformance"
    scene["meta"]["status"] = {"kind": "draft"}
    assert (
        client.post(
            "/documents", json={"document_id": "doc_conformance", "scene": scene}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/documents/doc_conformance/finalize",
            json={"template_revision_id": "tmpl_mailer_v1"},
        ).status_code
        == 200
    )

    buffer = BytesIO()
    Image.new("RGBA", (600, 200), (20, 60, 130, 255)).save(
        buffer, format="PNG", dpi=(305, 305)
    )
    buffer.seek(0)
    upload = client.post(
        "/assets",
        files={"file": ("conformance-logo.png", buffer, "image/png")},
        data={"label": "Conformance logo", "kind": "logo"},
    )
    assert upload.status_code == 200, upload.text
    return upload.json()["asset"]["id"]


def store_path(client: TestClient, relative: str) -> Path:
    """A derive artifact's path inside this workspace's ENGINE MATERIALIZATION CACHE (D4).

    Artifacts are written there by the engine and given durable custody in the same request;
    this reads the cache copy because the engine's `relative_path` is a cache-relative path."""
    return (
        Path(client.app.state.engine_cache_root)
        / os.environ["LUMEN_DEV_WORKSPACE_ID"]
        / relative
    )


def test_g10_conformance_100_instance_batch(client: TestClient) -> None:
    zxingcpp = pytest.importorskip("zxingcpp")
    from PIL import Image

    logo_asset_id = setup_revision_and_logo(client)
    bindings = seeded_binding_sets(BATCH_SIZE, logo_asset_id)
    for binding in bindings:
        stored = client.post("/binding-sets", json={"binding_set": binding})
        assert stored.status_code == 200, stored.text

    response = client.post(
        "/template-revisions/tmpl_mailer_v1/batches",
        json={
            "binding_set_ids": [b["binding_set_id"] for b in bindings],
            "export_formats": ["svg", "png"],
            "chunk_size": 20,
        },
    )
    assert response.status_code == 200, response.text
    batch = response.json()

    # --- batch completion + complete manifest -------------------------
    assert batch["status"] == "completed"
    assert batch["cursor"] == BATCH_SIZE
    assert batch["counts"]["total"] == BATCH_SIZE
    assert len(batch["manifest"]) == BATCH_SIZE
    manifest_ids = {entry["binding_set_id"] for entry in batch["manifest"]}
    assert manifest_ids == {b["binding_set_id"] for b in bindings}

    expected_overflows = len(range(0, BATCH_SIZE, OVERFLOW_EVERY))
    assert batch["counts"]["failed"] == expected_overflows
    assert batch["counts"]["derived"] == BATCH_SIZE - expected_overflows
    assert batch["counts"]["fit"]["overflow"] == expected_overflows
    assert batch["counts"]["fit"]["fits_with_policy"] > 0, (
        "the seeded population must exercise ShrinkFont resolution"
    )

    # Every derived entry exported both formats with stored bytes.
    for entry in batch["manifest"]:
        if entry["status"] == "derived":
            formats = sorted(a["format"] for a in entry["artifacts"])
            assert formats == ["png", "svg"], entry
            for artifact in entry["artifacts"]:
                assert artifact["digest_value"]
                assert store_path(client, artifact["relative_path"]).exists()
        else:
            assert entry["artifacts"] == [], "failed instances never export"

    # --- zero silent overflows ----------------------------------------
    instances = client.get(
        "/template-revisions/tmpl_mailer_v1/instances"
    ).json()["instances"]
    assert len(instances) == BATCH_SIZE
    overflow_codes = {"LUMG0320", "LUMG0321", "LUMG0322", "LUMG0323", "LUMG0325"}
    text_fit_codes = {"LUMV0902", "LUMV0903", "LUMV0904"}
    for instance in instances:
        report = instance["fit_report"]
        verdicts = {entry["verdict"]["kind"] for entry in report["slots"]}
        fit_issue_diagnosed = any(
            d["code"] in overflow_codes | text_fit_codes
            for d in instance["diagnostics"]
        )
        if fit_issue_diagnosed:
            assert report["status"] != "fits", (
                f"instance {instance['instance_id']} has fit diagnostics but a "
                f"clean report: {instance['diagnostics']}"
            )
        if instance["status"] == "failed":
            assert "overflow" in verdicts, (
                f"failed instance {instance['instance_id']} must carry an "
                f"overflow verdict: {report}"
            )
            assert any(
                d["code"] == "LUMG0321" for d in instance["diagnostics"]
            ), "the deliberate overflow is the exhausted-shrink case"
        if instance["fit_status"] == "fits":
            assert not fit_issue_diagnosed

    # ShrinkFont resolutions record the executed policy and size.
    policy_instances = [
        i for i in instances if i["fit_status"] == "fits_with_policy"
    ]
    assert policy_instances
    for instance in policy_instances:
        adjusted = [
            entry
            for entry in instance["fit_report"]["slots"]
            if entry["verdict"]["kind"] == "fits_with_policy"
        ]
        assert adjusted
        for entry in adjusted:
            assert entry["verdict"]["policy"] == "shrink_font"
            assert 6.0 <= entry["verdict"]["adjusted_font_size"] < 10.0

    # --- every derived scene passes full validation -------------------
    core = client.app.state.core
    for instance in instances:
        if instance["status"] != "derived":
            continue
        full = client.get(f"/instances/{instance['instance_id']}").json()
        validation = core.validate_scene(full["derived_scene"])
        errors = [
            d
            for d in validation.get("diagnostics", [])
            if d["severity"] == "error"
        ]
        assert errors == [], (
            f"derived scene {instance['instance_id']} failed validation: {errors}"
        )

    # --- QR scan-verified on a sampled artifact -----------------------
    sample = next(
        entry for entry in batch["manifest"] if entry["binding_set_id"] == "bind_conf_001"
    )
    png_artifact = next(a for a in sample["artifacts"] if a["format"] == "png")
    image = Image.open(store_path(client, png_artifact["relative_path"]))
    decoded = zxingcpp.read_barcodes(image)
    assert [r.text for r in decoded] == ["https://go.example.com/conf/001"], (
        "the sampled instance's QR must scan to its own landing URL"
    )

    # --- re-derivation idempotence ------------------------------------
    for binding_set_id in ["bind_conf_001", "bind_conf_042", "bind_conf_099"]:
        before = client.get(
            f"/instances/inst_tmpl_mailer_v1_{binding_set_id}"
        ).json()
        rederived = client.post(
            "/template-revisions/tmpl_mailer_v1/instances",
            json={
                "binding_set_id": binding_set_id,
                "export_formats": ["svg", "png"],
            },
        ).json()
        assert rederived["derived_scene"] == before["derived_scene"], (
            f"re-derivation of {binding_set_id} must be byte-identical"
        )
        assert [
            (a["format"], a["digest_value"]) for a in rederived["artifacts"]
        ] == [(a["format"], a["digest_value"]) for a in before["artifacts"]]


def test_g10_pdf_batch_follows_the_b3_verdict(client: TestClient) -> None:
    zxingcpp = pytest.importorskip("zxingcpp")
    if shutil.which("pdftoppm") is None or shutil.which("pdfimages") is None:
        pytest.skip("poppler (pdftoppm/pdfimages) is required for the PDF gate")
    from PIL import Image

    logo_asset_id = setup_revision_and_logo(client)
    bindings = seeded_binding_sets(3, logo_asset_id)
    # Drop the deliberate overflow (index 0) content so all three derive.
    bindings[0]["values"]["contact.full_name"] = {
        "kind": "text",
        "value": "Dr. Priya Sharma",
    }
    for binding in bindings:
        assert (
            client.post("/binding-sets", json={"binding_set": binding}).status_code
            == 200
        )

    batch = client.post(
        "/template-revisions/tmpl_mailer_v1/batches",
        json={
            "binding_set_ids": [b["binding_set_id"] for b in bindings],
            "export_formats": ["pdf"],
            "chunk_size": 2,
        },
    ).json()
    assert batch["status"] == "completed"
    assert batch["counts"]["derived"] == 3

    entry = batch["manifest"][1]
    pdf_artifact = next(a for a in entry["artifacts"] if a["format"] == "pdf")
    # Bulk PDF = the vector press-ready deliverable through the shared
    # adapter pipeline (supersedes the W0-era flattened-raster B3 default):
    # live text with embedded subset fonts, print boxes, and the print-ready
    # report riding the artifact. Clean instances report no error codes.
    assert pdf_artifact["profile_name"] == "instance_pdf"
    assert pdf_artifact["print_ready"]["status"] != "fail"
    assert entry["error_codes"] == []

    pdf_path = store_path(client, pdf_artifact["relative_path"])
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"FontFile2" in pdf_bytes, "embedded subset fonts expected"
    assert b"/TrimBox" in pdf_bytes, "print finalize expected"

    # The QR scans from a 300dpi render of the flattened PDF to the
    # exact per-recipient landing URL.
    render_dir = pdf_path.parent
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            "300",
            "-png",
            str(pdf_path),
            str(render_dir / "g10-render"),
        ],
        check=True,
    )
    rendered = next(render_dir.glob("g10-render*.png"))
    decoded = zxingcpp.read_barcodes(Image.open(rendered))
    assert [r.text for r in decoded] == [
        f"https://go.example.com/conf/{entry['binding_set_id'].split('_')[-1]}"
    ]
