"""The Brand Ad Assets onboarding job, end to end (W2) — flag surface, durability, versioning.

Everything external is stubbed: the ad-library provider answers from the frozen real-shape Ramp
fixtures, creative bytes come from an injected fetcher, the distiller is a canned card and the
image provider is a canned generator. The DATABASE is real, because the properties under test —
step durability, card version immutability, the FK from a creative to its asset row — are
database properties and a mock would only prove the mock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, wait_for_ingestion_job
from lumen_api import main as main_module
from lumen_api.main import create_app
from lumen_ingestion.ad_library.adyntel import AdyntelProvider
from lumen_ingestion.ad_library.distill import AdDnaCard, StyleGroup
from lumen_ingestion.ad_library.provider import AdLibraryPage
from py_lumen_config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
VALID_STYLES_PATH = REPO_ROOT / "crates/lumen-core/fixtures/styles/valid_insight_health.styles"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ad_library"

BRAND_KIT_VERSION = 1

# An 8x8 RGB PNG. Small, but a REAL raster: the engine ingests it and, just as importantly,
# Pillow can open and downscale it — the distillation step turns each harvested creative into a
# downscaled preview, so bytes Pillow refuses would make every card fail with "no preview"
# rather than exercising anything.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000080000000808020000004b6d29dc"
    "0000001449444154789c6314703060c00698b08a0e5a090069e8009026c1daab00"
    "00000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _stub_asset_describer(monkeypatch):
    from asset_analysis_fixture import analysis
    from lumen_ingestion import pipeline
    from lumen_ingestion.describe import DescribeResult
    class Describer:
        active = True
        def describe(self, items):
            return [DescribeResult(item.asset_id, "Ad", "Ad", "Reference", [],
                                   analysis=analysis("Ad", item.source_occurrences)) for item in items]
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: Describer())


def _pages() -> list[AdLibraryPage]:
    provider = AdyntelProvider(api_key="k", email="e@example.com")
    return [
        provider.parse_page(json.loads((FIXTURES / f"ramp_page{n}.json").read_text()))
        for n in (1, 2)
    ]


class _StubProvider:
    name = "stub-library"

    def __init__(self) -> None:
        self._pages = _pages()
        self.calls: list[dict[str, Any]] = []

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        self.calls.append(kwargs)
        return self._pages[min(len(self.calls) - 1, len(self._pages) - 1)]


class _StubDistiller:
    active = True
    model = "stub/vision"
    last_failure_reason = None

    def __init__(self, card: AdDnaCard | None = None) -> None:
        self._card = card if card is not None else _card()
        self.seen: list[Any] = []

    def distil(self, previews: list[Any]) -> AdDnaCard | None:
        self.seen.append(previews)
        return self._card


class _FailingDistiller:
    active = True
    model = "stub/vision"
    last_failure_reason = "HTTP 503 (attempt 2): upstream is on fire"

    def distil(self, previews: list[Any]) -> AdDnaCard | None:
        del previews
        return None


class _UnconfiguredDistiller:
    """The R2-B shape: a distiller with no model key at all.

    ``active = False`` is what the lane reads as "not attempted", and it is exactly what the
    W5 acceptance run got from a stock `.env`. Kept as its own stub rather than reusing
    ``NullAdDnaDistiller`` so the test names the condition it is reproducing.
    """

    active = False
    model = "null"
    last_failure_reason = None

    def distil(self, previews: list[Any]) -> AdDnaCard | None:
        raise AssertionError("an inactive distiller must never be called")


class _EmptyProvider:
    """A vendor that resolves the advertiser and honestly has no ads for it.

    This is the Apollo shape from the W5 run — `page_id` resolves, `ads` is empty — and it is
    the one harvest outcome the suite never covered.
    """

    name = "stub-library-empty"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        self.calls.append(kwargs)
        return AdLibraryPage(
            page_id="107285417",
            total_ads=0,
            ads=(),
            continuation_token=None,
            is_last_page=True,
            provider=self.name,
        )


def _card() -> AdDnaCard:
    return AdDnaCard(
        prose=(
            "These ads are one flat deep-green field with a heavy headline on the left and "
            "a product card on the right. A lime accent shows up once, on the call to "
            "action. The logo sits bottom left, reversed out of the green."
        ),
        style_groups=(StyleGroup(name="Deep Field", creative_ids=("adcre_stub",)),),
        model="stub/vision",
    )


class _StubGenerated:
    image_bytes = TINY_PNG
    mime_type = "image/png"
    model = "stub/image"
    provenance: dict = {"kind": "generated"}
    license = None
    width = 1920
    height = 1080
    aspect_ratio_honored = True


def _stub_generate(**kwargs: Any) -> _StubGenerated:
    """A canned image model that returns DIFFERENT bytes per aspect ratio.

    Asset ids are content-derived from the generated bytes, so a stub that returned one image
    for every call would collapse a system's whole set into a single asset — and the test would
    then be asserting the stub's laziness rather than the lane's behaviour. A real model never
    returns identical bytes twice.
    """
    generated = _StubGenerated()
    generated.image_bytes = _distinct_png(str(kwargs.get("aspect_ratio") or ""))
    return generated


def _distinct_png(salt: str) -> bytes:
    """A valid PNG whose bytes depend on ``salt`` — still openable by Pillow."""
    from io import BytesIO

    from PIL import Image

    shade = (sum(salt.encode()) % 200) + 20
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (shade, 64, 48)).save(buffer, format="PNG")
    return buffer.getvalue()


def _fetch_creative(url: str) -> tuple[bytes, str]:
    del url
    return TINY_PNG, "image/png"


@pytest.fixture
def lane_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    # Pipeline tests drive the offered job with injected providers in _run_job;
    # an embedded worker would race that drive with the production providers.
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in this module may reach the network — asserted, not assumed.

    The lane touches FIVE external systems (the company-identity resolver, the ad library, the
    creative CDN, the vision model and the image model) and every one of them is stubbed by
    injection. This makes a missed stub fail loudly instead of quietly making a real request: an
    earlier draft of these tests monkeypatched a module attribute that was already bound as a
    default argument, so the "stub" did nothing and the suite was fetching real LinkedIn CDN
    bytes.

    The identity resolver is stopped one step EARLIER than the others, by blanking its
    credential rather than by refusing its transport. It has to be: R3-A's resolution step is
    deliberately forgiving — an identity call that fails must degrade to the ad library's own
    domain resolution rather than lose a harvest that would otherwise work — so a refused
    request would be caught and turned into a fallback, and the loud guard above would go
    unheard. With no key the resolver is never constructed at all, which is both louder and
    closer to what these tests mean: they are about the harvest, not about identity.
    """
    import httpx

    from py_lumen_config import settings as _settings

    monkeypatch.setattr(_settings, "pdl_api_key", "", raising=False)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "a Brand Ad Assets test reached the network; every external call in this lane is "
            "an injected seam and one of them was missed"
        )

    # ``Client`` is on the list since lane 3 slice 5: the lane's paid calls go through
    # ``clue_spend.HttpxTransport``, which builds an ``httpx.Client`` rather than calling the
    # module-level ``post``. Without it the guard would pass while the lane really dialled out.
    for name in ("get", "post", "request", "stream", "Client", "AsyncClient"):
        monkeypatch.setattr(httpx, name, refuse, raising=False)


def _client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def _seed_brand_kit(client: TestClient) -> str:
    """Publish a kit under an id unique to this test, and return that id.

    Two reasons it is not simply "compile the .styles fixture and use its id". The fixture
    DECLARES its own identity, so compiling it always yields ``brand_kit_insight_health`` v4
    whatever the request asks for — and ``design_brand_kit``'s primary key is
    ``(brand_kit_id, version)``, which is GLOBAL, not per-workspace. Every test that compiled
    the fixture was therefore racing every other test in the shared development database for
    one row. Compiling for the kit JSON and republishing it under a per-test id makes each
    test's kit genuinely its own.
    """
    compiled = client.post(
        "/brand-kits/compile-styles",
        json={
            "source": VALID_STYLES_PATH.read_text(),
            "brand_kit_id": "brand_kit_ad_assets_seed",
            "version": 1,
            "name": "Ad Assets Test",
            "persist": False,
        },
    )
    assert compiled.status_code == 200, compiled.text

    kit = json.loads(json.dumps(compiled.json()["brand_kit_json"]))
    brand_kit_id = f"brand_kit_ad_{uuid4().hex[:12]}"
    kit["id"] = brand_kit_id
    kit["version"] = BRAND_KIT_VERSION
    created = client.post("/brand-kits", json={"brand_kit": kit, "source": "manual"})
    assert created.status_code == 200, created.text
    return brand_kit_id


def _install_stub_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: Any,
    distiller: Any,
    generate: Any = _stub_generate,
) -> None:
    """Rebind main's ``run_ad_assets_onboarding`` so the REAL job runs with stub externals.

    The same seam the ingestion route suites use: ``execute_ingestion_job`` resolves the runner
    from ``main``'s namespace at call time, so patching it here keeps the whole fleet path —
    offer, claim, lease, fence, terminal row — genuinely exercised.
    """
    from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding as real

    def runner(engine_cache_dir: str, job_id: str, **kwargs: Any) -> None:
        real(
            engine_cache_dir,
            job_id,
            provider=provider,
            distiller=distiller,
            generate=generate,
            # All FOUR external systems are stubbed, creative bytes included — see the runner's
            # own docstring for why three would not be enough.
            fetch_creative=_fetch_creative,
            now=lambda: datetime(2026, 8, 26, tzinfo=UTC),
            **kwargs,
        )

    monkeypatch.setattr(main_module, "run_ad_assets_onboarding", runner)


# --- the flag surface ------------------------------------------------------------------------


def test_with_the_flag_off_the_lane_has_no_surface_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE, and the load-bearing one: flag off must be zero behaviour change.

    The routes are not registered at all, so the paths 404 exactly like any unknown path and
    the OpenAPI schema does not mention them. Nothing else in the app reads the lane's tables,
    so nothing at runtime touches the new schema either.
    """
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    client = _client(tmp_path)

    assert client.post("/brand-ad-assets/onboard", json={}).status_code == 404
    assert client.get("/brand-ad-assets/brand_kit_anything").status_code == 404

    paths = client.get("/openapi.json").json()["paths"]
    assert not [path for path in paths if path.startswith("/brand-ad-assets")]
    # The brand-kit ingestion surface it shares a job table with is untouched.
    assert client.get("/brand-kits/ingest").status_code == 200


def test_with_the_flag_on_the_lane_surface_appears(tmp_path: Path, lane_on: None) -> None:
    client = _client(tmp_path)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/brand-ad-assets/onboard" in paths
    # An un-harvested brand is an ordinary state of the world, not a 404.
    lane = client.get("/brand-ad-assets/brand_kit_never_harvested")
    assert lane.status_code == 200
    assert lane.json()["card"] is None
    assert lane.json()["pregenerated_assets"] == []


def test_the_advertiser_selector_must_be_unambiguous(tmp_path: Path, lane_on: None) -> None:
    """RED CASE: guessing which selector a caller meant would spend a vendor credit."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    body = {"brand_kit_id": brand_kit_id, "brand_kit_version": BRAND_KIT_VERSION}

    neither = client.post("/brand-ad-assets/onboard", json=body)
    assert neither.status_code == 422
    assert neither.json()["detail"]["code"] == "ad_assets.advertiser_ambiguous"

    both = client.post(
        "/brand-ad-assets/onboard",
        json={**body, "company_domain": "ramp.com", "page_id": "1406226"},
    )
    assert both.status_code == 422


def test_an_unknown_brand_kit_is_refused_before_any_credit_is_spent(
    tmp_path: Path, lane_on: None
) -> None:
    client = _client(tmp_path)
    refused = client.post(
        "/brand-ad-assets/onboard",
        json={
            "brand_kit_id": "brand_kit_does_not_exist",
            "brand_kit_version": 1,
            "company_domain": "ramp.com",
        },
    )
    assert refused.status_code == 404


# --- the whole job ---------------------------------------------------------------------------


def _evidence(client: TestClient, job_id: str) -> dict:
    """The job's per-step outcome record, read from the durable row.

    NOT from the HTTP dto: ``ingestion_job_dto`` deliberately omits request and evidence bodies
    (they hold staged digests and, here, the whole harvest report). That contract predates this
    lane and is not this lane's to change, so the test reads the row the way an operator would.
    """
    from lumen_ingestion.jobs import IngestionJobStore

    job = IngestionJobStore(workspace_id=client.headers["X-Workspace-Id"]).require(job_id)
    return job["evidence"] or {}


def _offer(
    client: TestClient,
    *,
    brand_kit_id: str,
    max_creatives: int = 4,
    max_pages: int = 2,
    harvest_only: bool = False,
) -> str:
    offered = client.post(
        "/brand-ad-assets/onboard",
        json={
            "brand_kit_id": brand_kit_id,
            "brand_kit_version": BRAND_KIT_VERSION,
            "company_domain": "ramp.com",
            "advertiser_name": "Ramp",
            "max_pages": max_pages,
            "max_creatives": max_creatives,
            "harvest_only": harvest_only,
        },
    )
    assert offered.status_code == 200, offered.text
    job_id: str = offered.json()["job"]["job_id"]
    return job_id


def _run_job(
    client: TestClient,
    tmp_path: Path,
    *,
    brand_kit_id: str,
    distiller: Any,
    generate: Any = _stub_generate,
    provider: Any = None,
    max_creatives: int = 4,
    max_pages: int = 2,
    harvest_only: bool = False,
) -> dict:
    """Offer one job through the route, then DRIVE it here, and return the terminal row.

    The pipeline tests below drive the runner directly rather than waiting for the embedded
    fleet worker, and that is a deliberate decoupling rather than a shortcut. ``fleet_task`` is
    a table shared by every workspace and every earlier run; a test's embedded worker lives
    only as long as that test and handles one task at a time, so ANY stray ``design_job`` task —
    another suite's, or a previous run's — takes the worker and leaves this test's job sitting
    in the queue until it times out. That flakiness has nothing to do with what these tests
    assert, which is what the PIPELINE does.

    ``test_the_fleet_worker_executes_an_ad_assets_job`` covers the part that genuinely needs the
    queue, and it is the one test that waits on a worker.
    """
    from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding

    job_id = _offer(
        client, brand_kit_id=brand_kit_id, max_creatives=max_creatives, max_pages=max_pages,
        harvest_only=harvest_only,
    )
    run_ad_assets_onboarding(
        str(tmp_path / "engine-cache" / client.headers["X-Workspace-Id"]),
        job_id,
        workspace_id=client.headers["X-Workspace-Id"],
        provider=provider if provider is not None else _StubProvider(),
        distiller=distiller,
        generate=generate,
        fetch_creative=_fetch_creative,
        now=lambda: datetime(2026, 8, 26, tzinfo=UTC),
    )
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    job["evidence"] = _evidence(client, job_id)
    return job


def test_manual_harvest_keeps_originals_without_calling_creative_models(
    tmp_path: Path, lane_on: None,
) -> None:
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    class NoModelCalls:
        active = True

        def distil(self, previews):
            raise AssertionError("harvest-only must not analyze or generate imagery")

    def no_generation(*args, **kwargs):
        raise AssertionError("harvest-only must not generate imagery")

    job = _run_job(
        client, tmp_path, brand_kit_id=brand_kit_id,
        distiller=NoModelCalls(), generate=no_generation, harvest_only=True,
    )
    assert job["status"] == "succeeded", job
    steps = job["evidence"]["steps"]
    assert steps["record"]["count"] > 0
    assert steps["distill"]["status"] == "skipped"
    assert steps["pregenerate"]["status"] == "skipped"
    assert "harvest-only" in steps["distill"]["reason"]
    assert job["outcome"]["status"] == "partial"
    assert job["outcome"]["card_written"] is False
    assert job["outcome"]["assets_generated"] == 0


def test_a_full_run_harvests_distils_and_pregenerates(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())
    assert job["status"] == "succeeded", job
    assert job["kind"] == "ad_assets"
    assert job["brand_kit_id"] == brand_kit_id

    steps = job["evidence"]["steps"]
    assert steps["harvest"]["status"] == "ok"
    assert steps["harvest"]["kept"] == 4
    assert steps["harvest"]["dropped"]["thought_leader"] >= 1
    assert steps["custody"]["custodied"] == 4
    assert steps["record"]["count"] == 4
    assert steps["distill"]["status"] == "ok"
    assert steps["distill"]["style_groups"] == 1
    assert steps["pregenerate"]["status"] == "ok"
    assert steps["pregenerate"]["generated"] == 2

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 1
    assert lane["card"]["card"]["prose"].startswith("These ads are one flat deep-green field")
    assert lane["card"]["card"]["style_groups"][0]["name"] == "Deep Field"
    assert len(lane["pregenerated_assets"]) == 2
    assert {asset["visual_system"] for asset in lane["pregenerated_assets"]} == {"Deep Field"}
    assert len(lane["creatives"]) == 4

    creative = lane["creatives"][0]
    for key in ("ad_id", "view_details_link", "advertiser_page_id", "fetched_at", "provider"):
        assert creative["provenance"][key] is not None or key == "advertiser_page_id"
    assert creative["asset_id"].startswith("asset_ad_")
    # The bytes really are servable through the asset registry, not just named.
    assert client.get(f"/assets/{creative['asset_id']}").status_code == 200


# --- W5/R2-C: the top-line outcome names what actually happened -------------------------------
#
# All three jobs below end `succeeded`, and that stays correct: this lane has no gates (D5), and
# a brand with no static ads has honestly nothing to harvest. What is being pinned is that the
# CALLER can now tell them apart without opening the evidence body — which is what the W5 run
# could not do, twice.


def test_an_empty_harvest_says_so_at_the_top_level(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE 1: the vendor resolved the advertiser and returned no ads.

    Before this, the whole truth was `steps.harvest.status == "empty"` one level down, while
    the job row said `succeeded` / progress 1.0 / error null and the polled DTO carried no hint
    at all. The distil and pre-generate steps were not merely skipped, they were never reached —
    absent keys, which read as silence.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(
        client,
        tmp_path,
        brand_kit_id=brand_kit_id,
        distiller=_StubDistiller(),
        provider=_EmptyProvider(),
    )

    assert job["status"] == "succeeded", "an empty harvest is not an error"
    assert job["evidence"]["steps"]["harvest"]["status"] == "empty"

    outcome = job["outcome"]
    assert outcome is not None, "the polled DTO must carry the outcome, not bury it"
    assert outcome["status"] == "empty"
    assert outcome["creatives_kept"] == 0
    assert outcome["creatives_custodied"] == 0
    assert outcome["card_written"] is False
    assert outcome["assets_generated"] == 0
    # The steps that never ran are NAMED, rather than being absent keys nobody notices.
    assert outcome["steps_not_reached"] == ["custody", "record", "enrich", "distill", "pregenerate"]
    assert "0 ad(s) kept" in outcome["summary"]
    assert "No ad-DNA card was written." in outcome["summary"]

    # The durable row and the DTO tell the same story.
    assert job["evidence"]["outcome"] == outcome
    # And the human-facing stage no longer reads as whichever step narrated last.
    assert job["stage"] == outcome["summary"]

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"] is None
    assert lane["creatives"] == []


def test_a_distillation_skipped_for_a_missing_key_says_so_at_the_top_level(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE 2: the R2-B failure, reported honestly even when the key is still absent.

    R2-B stops the design subsystem being keyless by accident. This is the other half: when a
    deployment genuinely has no model key, the job must still not look like a working lane.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(
        client, tmp_path, brand_kit_id=brand_kit_id, distiller=_UnconfiguredDistiller()
    )

    assert job["status"] == "succeeded", "a missing key is not a job failure"

    outcome = job["outcome"]
    assert outcome["status"] == "partial", "creatives landed, the card and imagery did not"
    assert outcome["creatives_custodied"] == 4
    assert outcome["card_written"] is False
    assert outcome["assets_generated"] == 0
    assert outcome["steps_skipped"] == ["distill"]
    assert outcome["steps_not_reached"] == ["pregenerate"]
    # The REASON rides the top level too — an operator should not have to guess "no model key".
    assert "no model key" in outcome["reasons"]["distill"]
    assert "no model key" in outcome["summary"]

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"] is None
    assert len(lane["creatives"]) == 4, "the harvest survived the skipped distillation"


def test_a_fully_populated_lane_is_the_only_one_that_reads_ok(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control: `ok` means all three artifact kinds actually exist."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())

    outcome = job["outcome"]
    assert outcome["status"] == "ok"
    assert outcome["creatives_kept"] == 4
    assert outcome["card_written"] is True
    assert outcome["assets_generated"] == 2
    assert outcome["steps_skipped"] == []
    assert outcome["steps_failed"] == []
    assert outcome["steps_not_reached"] == []
    assert outcome["reasons"] == {}


def test_a_failed_distillation_reads_as_partial_and_names_the_failure(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model that answered badly is `partial` too — and it is not confused with `skipped`."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_FailingDistiller())

    outcome = job["outcome"]
    assert outcome["status"] == "partial"
    assert outcome["steps_failed"] == ["distill"]
    assert outcome["steps_skipped"] == []
    assert "upstream is on fire" in outcome["reasons"]["distill"]


def test_the_older_ingestion_kinds_gain_a_field_and_lose_nothing(tmp_path: Path) -> None:
    """The outcome member is lifted from evidence, never the evidence body itself.

    `ingestion_job_dto` is shared by all four kinds. The three older ones compose no outcome,
    so theirs stays `None` — and no kind's DTO ever exposes the request or evidence bodies.
    """
    from lumen_api.dto import ingestion_job_dto

    row = {
        "job_id": "ingest_x",
        "kind": "website",
        "status": "succeeded",
        "stage": None,
        "progress": 1.0,
        "request": {"secret_staged_digest": "do-not-leak"},
        "evidence": {"schema_version": 1, "colors": ["#fff"]},
        "error": None,
        "created_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
    }

    dto = ingestion_job_dto(row)
    assert dto["outcome"] is None
    assert "evidence" not in dto and "request" not in dto


def test_a_failed_distillation_does_not_lose_the_harvested_creatives(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE, and the spec's explicit requirement: each step's output is durable first."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_FailingDistiller())
    # Finished, but without its card: a gap, not a failure (spec 2026-10-25 §5.1).
    assert job["status"] == "succeeded_with_gaps", job

    steps = job["evidence"]["steps"]
    assert steps["record"]["count"] == 4
    assert steps["distill"]["status"] == "failed"
    assert "upstream is on fire" in steps["distill"]["reason"]
    assert "pregenerate" not in steps

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"] is None
    assert len(lane["creatives"]) == 4, "the harvest survived the distillation failure"


def test_a_failed_pregeneration_does_not_lose_the_card(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    def exploding_generate(**kwargs: Any) -> Any:
        raise RuntimeError("the image provider is down")

    job = _run_job(
        client,
        tmp_path,
        brand_kit_id=brand_kit_id,
        distiller=_StubDistiller(),
        generate=exploding_generate,
    )
    assert job["status"] == "succeeded", job

    steps = job["evidence"]["steps"]
    assert steps["distill"]["status"] == "ok"
    assert steps["pregenerate"]["status"] == "empty"
    assert steps["pregenerate"]["failures"]

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 1, "the card survived the pre-generation failure"
    assert lane["pregenerated_assets"] == []
    assert len(lane["creatives"]) == 4


def test_a_second_harvest_appends_a_version_and_leaves_the_first_untouched(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Card versions are immutable: distilling again appends, it never edits."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    first = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())
    assert first["evidence"]["steps"]["distill"]["version"] == 1

    revised = AdDnaCard(
        prose="A later harvest saw something else: these ads are photographs, edge to edge.",
        style_groups=(StyleGroup(name="Second Look", creative_ids=("adcre_stub",)),),
        model="stub/vision",
    )
    second = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller(revised))
    assert second["evidence"]["steps"]["distill"]["version"] == 2

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 2
    assert lane["card"]["card"]["style_groups"][0]["name"] == "Second Look"

    from lumen_ingestion.ad_library.store import AdAssetsStore

    store = AdAssetsStore(workspace_id=client.headers["X-Workspace-Id"])
    original = store.get_card(lane["card"]["card_id"], 1)
    assert original["card"]["style_groups"][0]["name"] == "Deep Field"
    assert original["card"]["prose"].startswith("These ads are one flat deep-green field")


def test_a_card_version_cannot_be_edited_or_deleted(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED CASE: the immutability is the DATABASE's, not a convention the DAL keeps."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    card_id = lane["card"]["card_id"]
    workspace_id = client.headers["X-Workspace-Id"]

    from lumen_api.design_store import DesignStoreBridge
    from sqlalchemy import text

    bridge = DesignStoreBridge(workspace_id)

    with pytest.raises(Exception) as updated:
        bridge._run(
            lambda conn: conn.execute(
                text(
                    "UPDATE design_ad_dna_card SET model = 'tampered'"
                    " WHERE card_id = :c AND workspace_id = :w"
                ),
                {"c": card_id, "w": workspace_id},
            )
        )
    assert "immutable" in str(updated.value)

    with pytest.raises(Exception) as deleted:
        bridge._run(
            lambda conn: conn.execute(
                text(
                    "DELETE FROM design_ad_dna_card WHERE card_id = :c AND workspace_id = :w"
                ),
                {"c": card_id, "w": workspace_id},
            )
        )
    assert "append-only" in str(deleted.value)


def test_the_page_cap_bounds_the_vendor_spend(tmp_path: Path, lane_on: None) -> None:
    """One page is one credit. The cap the caller asked for is the cap the job honours."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    provider = _StubProvider()
    job = _run_job(
        client,
        tmp_path,
        brand_kit_id=brand_kit_id,
        distiller=_StubDistiller(),
        provider=provider,
        max_pages=1,
        max_creatives=3,
    )

    assert job["status"] == "succeeded", job
    assert len(provider.calls) == 1
    assert job["evidence"]["steps"]["harvest"]["pages_fetched"] == 1
    assert job["evidence"]["steps"]["harvest"]["kept"] == 3
    assert all("all_ads" not in call for call in provider.calls)


def test_the_fleet_worker_executes_an_ad_assets_job(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatch half: an offered ad_assets job is claimed and driven by the fleet.

    The only test here that waits on the embedded worker, because it is the only one whose
    subject IS the queue — that the new ingestion KIND routes to the new runner, under the same
    lease and fence as every other design job. Everything the pipeline does is asserted by the
    tests above, which drive the runner directly (see ``_run_job``).
    """
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", True, raising=False)
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _install_stub_runner(
        monkeypatch, provider=_StubProvider(), distiller=_StubDistiller()
    )

    job_id = _offer(client, brand_kit_id=brand_kit_id, max_creatives=2, max_pages=1)
    job = wait_for_ingestion_job(client, job_id)

    assert job["status"] == "succeeded", job
    assert job["kind"] == "ad_assets"
    assert _evidence(client, job_id)["steps"]["harvest"]["kept"] == 2


def test_a_re_driven_job_converges_instead_of_orphaning_the_paid_imagery(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W-B1 red case (Wave-C fix #2). Ramp's incident: the same onboarding job executed
    twice (reaper re-offer / second embedded worker over the shared queue), the second
    distill minted card v2, pre-generation's assets stayed linked to v1, and the lane —
    which serves the LATEST version — showed zero of the ten paid grounds. Under the guard
    a re-driven execution converges: one card version, no second vision spend, no second
    image spend, and the paid imagery still visible on the latest version."""
    from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding

    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    distiller = _StubDistiller()
    generate_calls: list[str] = []

    def counting_generate(**kwargs: Any) -> Any:
        generate_calls.append(str(kwargs.get("aspect_ratio") or ""))
        return _stub_generate(**kwargs)

    job = _run_job(
        client, tmp_path, brand_kit_id=brand_kit_id, distiller=distiller,
        generate=counting_generate,
    )
    assert job["status"] == "succeeded", job
    first_distills = len(distiller.seen)
    first_generates = len(generate_calls)
    assert first_distills == 1 and first_generates > 0

    # The infrastructure re-drive: SAME job id, executed again from the top.
    run_ad_assets_onboarding(
        str(tmp_path / "engine-cache" / client.headers["X-Workspace-Id"]),
        job["job_id"],
        workspace_id=client.headers["X-Workspace-Id"],
        provider=_StubProvider(),
        distiller=distiller,
        generate=counting_generate,
        fetch_creative=_fetch_creative,
        now=lambda: datetime(2026, 8, 26, tzinfo=UTC),
    )
    redriven = client.get(f"/brand-kits/ingest/{job['job_id']}").json()["job"]
    assert redriven["status"] == "succeeded", redriven
    evidence = _evidence(client, job["job_id"])
    assert evidence["steps"]["distill"]["status"] == "converged"
    assert evidence["steps"]["distill"]["version"] == 1
    assert evidence["steps"]["pregenerate"]["status"] == "converged"

    assert len(distiller.seen) == first_distills  # no second vision-model spend
    assert len(generate_calls) == first_generates  # no second image-model spend

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 1  # ONE version — no twin
    assert len(lane["pregenerated_assets"]) == 2  # the paid imagery is still visible


def test_a_deliberate_second_onboarding_still_mints_a_fresh_version(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard's other half: a NEW job (the human re-onboarding on purpose) is new work —
    a fresh card version is minted and the lane serves it, with its own linked grounds."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    first = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())
    assert first["status"] == "succeeded", first

    second = _run_job(client, tmp_path, brand_kit_id=brand_kit_id, distiller=_StubDistiller())
    assert second["status"] == "succeeded", second
    assert second["job_id"] != first["job_id"]
    assert second["evidence"]["steps"]["distill"]["status"] == "ok"
    assert second["evidence"]["steps"]["distill"]["version"] == 2

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 2  # deliberate re-run = genuinely new version
    assert len(lane["pregenerated_assets"]) == 2  # linked to the NEW version, still visible


# --- auto ad ingestion at onboarding (2026-09-28): harvest now, card when a kit exists ---------
#
# Onboarding offers a HARVEST phase with no kit, in parallel with the website ingestion. The
# harvest custodies and describes the ads; the CARD phase (distil + pre-generate) is offered as its
# own job the moment both a finished harvest and a kit exist, by whichever of the two finishes
# second, exactly once per harvest.


class _NoLibraryCalls:
    """The card phase reuses the stored ads: any ad-library call is a double spend."""

    name = "no-library-calls"

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        raise AssertionError("the card phase must never call the ad library")


def _no_creative_fetch(url: str) -> tuple[bytes, str]:
    raise AssertionError("the card phase must never re-download a creative")


def _offer_harvest(client: TestClient, *, max_creatives: int = 4, max_pages: int = 2) -> str:
    offered = client.post(
        "/brand-ad-assets/onboard",
        json={
            "phase": "harvest",
            "company_domain": "ramp.com",
            "advertiser_name": "Ramp",
            "max_pages": max_pages,
            "max_creatives": max_creatives,
        },
    )
    assert offered.status_code == 200, offered.text
    job_id: str = offered.json()["job"]["job_id"]
    return job_id


def _drive(client: TestClient, tmp_path: Path, job_id: str, **seams: Any) -> dict:
    from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding

    run_ad_assets_onboarding(
        str(tmp_path / "engine-cache" / client.headers["X-Workspace-Id"]),
        job_id,
        workspace_id=client.headers["X-Workspace-Id"],
        now=lambda: datetime(2026, 8, 26, tzinfo=UTC),
        **seams,
    )
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    job["evidence"] = _evidence(client, job_id)
    return job


def _run_harvest(client: TestClient, tmp_path: Path, **kwargs: Any) -> dict:
    def no_card_models(**_kwargs: Any) -> Any:
        raise AssertionError("the harvest phase must not generate imagery")

    class NoDistiller:
        active = True

        def distil(self, previews: list[Any]) -> Any:
            raise AssertionError("the harvest phase must not distil a card")

    return _drive(
        client,
        tmp_path,
        _offer_harvest(client, **kwargs),
        provider=_StubProvider(),
        distiller=NoDistiller(),
        generate=no_card_models,
        fetch_creative=_fetch_creative,
    )


def _finish_a_kit_ingestion(client: TestClient, brand_kit_id: str) -> str:
    """A website ingestion that ended with a kit — the row the card offer looks for."""
    from lumen_ingestion.jobs import IngestionJobStore

    store = IngestionJobStore(workspace_id=client.headers["X-Workspace-Id"])
    job = store.create("website", {"url": "https://ramp.com"})
    store.complete(job["job_id"], brand_kit_id, BRAND_KIT_VERSION, "{}")
    return str(job["job_id"])


def _ad_jobs(client: TestClient) -> list[dict]:
    from lumen_ingestion.jobs import IngestionJobStore

    store = IngestionJobStore(workspace_id=client.headers["X-Workspace-Id"])
    return store.list_recent(50, kinds=("ad_assets",))


def test_a_harvest_is_offered_with_no_brand_kit(tmp_path: Path, lane_on: None) -> None:
    client = _client(tmp_path)
    job_id = _offer_harvest(client)
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert job["kind"] == "ad_assets"
    assert job["brand_kit_id"] is None


def test_the_card_phase_is_not_a_public_request_and_full_still_needs_a_kit(
    tmp_path: Path, lane_on: None
) -> None:
    client = _client(tmp_path)
    card = client.post(
        "/brand-ad-assets/onboard", json={"phase": "card", "company_domain": "ramp.com"}
    )
    assert card.status_code == 422
    assert card.json()["detail"]["code"] == "ad_assets.card_phase_is_internal"
    full = client.post("/brand-ad-assets/onboard", json={"company_domain": "ramp.com"})
    assert full.status_code == 422
    assert full.json()["detail"]["code"] == "ad_assets.brand_kit_required"


def test_the_harvest_phase_keeps_and_describes_the_ads_and_defers_the_card(
    tmp_path: Path, lane_on: None
) -> None:
    client = _client(tmp_path)
    job = _run_harvest(client, tmp_path)

    assert job["status"] == "succeeded", job
    assert job["brand_kit_id"] is None
    steps = job["evidence"]["steps"]
    assert steps["harvest"]["kept"] == 4
    assert steps["custody"]["custodied"] == 4
    assert steps["enrich"]["status"] == "ok"
    assert steps["distill"]["status"] == "deferred"
    assert steps["pregenerate"]["status"] == "deferred"
    # The vendor's own order (most recent first) is kept for the card phase to follow.
    assert len(steps["record"]["creative_ids"]) == 4
    assert job["evidence"]["phase"] == "harvest"
    assert job["outcome"]["creatives_custodied"] == 4
    # No kit yet, so no card job was offered.
    assert [j["job_id"] for j in _ad_jobs(client)] == [job["job_id"]]


def test_a_kit_that_finishes_second_offers_exactly_one_card_job(
    tmp_path: Path, lane_on: None
) -> None:
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready

    client = _client(tmp_path)
    workspace_id = client.headers["X-Workspace-Id"]
    harvest = _run_harvest(client, tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _finish_a_kit_ingestion(client, brand_kit_id)

    card_job_id = offer_card_if_ready(workspace_id)
    assert card_job_id is not None
    again = offer_card_if_ready(workspace_id)
    assert again is None

    from lumen_ingestion.jobs import IngestionJobStore

    card_job = IngestionJobStore(workspace_id=workspace_id).require(card_job_id)
    assert card_job["request"] == {
        "phase": "card",
        "harvest_job_id": harvest["job_id"],
        "brand_kit_id": brand_kit_id,
        "brand_kit_version": BRAND_KIT_VERSION,
    }
    assert len(_ad_jobs(client)) == 2


def test_a_harvest_that_finishes_second_offers_the_card_itself(
    tmp_path: Path, lane_on: None
) -> None:
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _finish_a_kit_ingestion(client, brand_kit_id)

    harvest = _run_harvest(client, tmp_path)
    jobs = _ad_jobs(client)
    assert len(jobs) == 2
    card = next(j for j in jobs if j["job_id"] != harvest["job_id"])
    assert card["request"]["phase"] == "card"
    assert card["request"]["harvest_job_id"] == harvest["job_id"]


def test_an_empty_harvest_never_offers_a_card(tmp_path: Path, lane_on: None) -> None:
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready

    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _finish_a_kit_ingestion(client, brand_kit_id)
    empty = _drive(
        client,
        tmp_path,
        _offer_harvest(client),
        provider=_EmptyProvider(),
        distiller=_StubDistiller(),
        generate=_stub_generate,
        fetch_creative=_fetch_creative,
    )
    assert empty["status"] == "succeeded", empty
    assert offer_card_if_ready(client.headers["X-Workspace-Id"]) is None
    assert len(_ad_jobs(client)) == 1


def test_with_the_lane_off_no_card_is_offered(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready

    client = _client(tmp_path)
    _run_harvest(client, tmp_path)
    _finish_a_kit_ingestion(client, _seed_brand_kit(client))
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    assert offer_card_if_ready(client.headers["X-Workspace-Id"]) is None


def test_the_card_phase_reuses_the_stored_ads_and_pins_the_kit(
    tmp_path: Path, lane_on: None
) -> None:
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready

    client = _client(tmp_path)
    harvest = _run_harvest(client, tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _finish_a_kit_ingestion(client, brand_kit_id)
    card_job_id = offer_card_if_ready(client.headers["X-Workspace-Id"])
    assert card_job_id is not None

    distiller = _StubDistiller()
    job = _drive(
        client,
        tmp_path,
        card_job_id,
        provider=_NoLibraryCalls(),
        distiller=distiller,
        generate=_stub_generate,
        fetch_creative=_no_creative_fetch,
    )

    assert job["status"] == "succeeded", job
    assert job["brand_kit_id"] == brand_kit_id
    assert job["evidence"]["phase"] == "card"
    assert job["evidence"]["harvest_job_id"] == harvest["job_id"]
    # The previews follow the harvest's own order, from the stored bytes.
    previewed = [p.creative_id for p in distiller.seen[0]]
    assert previewed == harvest["evidence"]["steps"]["record"]["creative_ids"]
    steps = job["evidence"]["steps"]
    assert steps["distill"]["status"] == "ok"
    assert steps["pregenerate"]["generated"] == 2
    # The outcome describes the whole lane, harvest included.
    assert job["outcome"]["status"] == "ok"
    assert job["outcome"]["creatives_custodied"] == 4

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["card"]["version"] == 1
    assert len(lane["pregenerated_assets"]) == 2


def test_the_website_pipeline_hands_its_completion_to_the_card_offer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whichever finishes second: a kit ingestion finishing must also look for a harvest."""
    from lumen_ingestion import pipeline

    seen: dict[str, Any] = {}

    def capture(store: Any, job_id: str, work: Any, *, on_complete: Any = None) -> None:
        seen["on_complete"] = on_complete

    monkeypatch.setattr(pipeline, "run_ingestion_job", capture)
    pipeline.run_website_ingestion(str(tmp_path), "ingest_x", workspace_id="ws_x")
    assert callable(seen["on_complete"])


# --- honest status (spec 2026-10-25 §5.1) ------------------------------------------------------


class _FailingAssetDescriber:
    """Every ad analysis fails, as it did when the OpenRouter key was disabled (Illumio)."""

    active = True
    last_failure_reason = "provider_refused:openrouter:auth_invalid"

    def describe(self, items: list[Any]) -> list[Any]:
        raise RuntimeError(self.last_failure_reason)


def test_harvest_with_failed_ad_analyses_records_an_ad_analyses_gap(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_ingestion import pipeline

    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _FailingAssetDescriber())
    client = _client(tmp_path)
    job = _run_harvest(client, tmp_path)

    assert job["status"] == "succeeded_with_gaps", job
    gaps = job["evidence"]["gaps"]
    assert [gap["area"] for gap in gaps] == ["ad_analyses"]
    enrich = job["evidence"]["steps"]["enrich"]
    assert enrich["status"] == "failed" and enrich["ready"] == 0
    assert gaps[0]["failed"] == enrich["total"]


def test_harvest_with_no_ads_or_a_deferred_card_has_no_gaps(
    tmp_path: Path, lane_on: None
) -> None:
    client = _client(tmp_path)
    job = _run_harvest(client, tmp_path)

    assert job["status"] == "succeeded", job
    assert job["evidence"]["steps"]["distill"]["status"] == "deferred"
    assert job["evidence"]["gaps"] == []


def test_card_phase_distil_failure_records_an_ad_card_gap(tmp_path: Path, lane_on: None) -> None:
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready

    client = _client(tmp_path)
    _run_harvest(client, tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    _finish_a_kit_ingestion(client, brand_kit_id)
    card_job_id = offer_card_if_ready(client.headers["X-Workspace-Id"])
    assert card_job_id is not None

    job = _drive(
        client,
        tmp_path,
        card_job_id,
        provider=_NoLibraryCalls(),
        distiller=_FailingDistiller(),
        generate=_stub_generate,
        fetch_creative=_no_creative_fetch,
    )

    assert job["status"] == "succeeded_with_gaps", job
    assert [gap["area"] for gap in job["evidence"]["gaps"]] == ["ad_card"]


def test_card_offer_accepts_a_gapped_kit_and_harvest(
    tmp_path: Path, lane_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_ingestion import pipeline
    from lumen_ingestion.ad_library.auto_card import offer_card_if_ready
    from lumen_ingestion.jobs import IngestionJobStore

    client = _client(tmp_path)
    workspace_id = client.headers["X-Workspace-Id"]
    # The harvest kept its ads but some analyses failed: gapped, still usable.
    monkeypatch.setattr(pipeline, "resolve_describer", lambda: _FailingAssetDescriber())
    harvest = _run_harvest(client, tmp_path)
    assert harvest["status"] == "succeeded_with_gaps"
    brand_kit_id = _seed_brand_kit(client)
    store = IngestionJobStore(workspace_id=workspace_id)
    kit_job = store.create("website", {"url": "https://ramp.com"})
    store.complete(
        kit_job["job_id"],
        brand_kit_id,
        BRAND_KIT_VERSION,
        json.dumps({"gaps": [{"area": "descriptions", "failed": 1, "reason": "x"}]}),
    )
    assert store.require(kit_job["job_id"])["status"] == "succeeded_with_gaps"

    assert offer_card_if_ready(workspace_id) is not None
