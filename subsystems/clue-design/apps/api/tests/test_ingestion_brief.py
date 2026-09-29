"""The ingestion design-brief agent + `BrandBrief@1` (design-brief plan, slice 3).

The gate for the slice: a per-brand Creative Brief, grounded in what slice 2
measured, rides the draft kit as `brand_kit_json.brief` — and every way the
brief can go wrong leaves the kit publishing exactly as it does today.

Three laws are tested here rather than trusted:

* **the token law** — a recipe/palette/rhythm value is a kit TOKEN NAME. A raw
  hex or a pixel value is refused at the schema, a well-formed name the kit does
  not carry is refused against the kit's own token set.
* **fail-soft** — refusal, invalid output, or an agent that throws all land as a
  diagnostic and a briefless kit. None of them may fail an ingestion.
* **silence when unconfigured** — with no brief agent there is no diagnostic and
  no `brief` key: byte-identical to the pre-slice-3 pipeline.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, wait_for_ingestion_job

from lumen_ingestion.brief import (
    BRIEF_SCHEMA_VERSION,
    BrandBrief,
    BriefRefused,
    kit_token_names,
    validate_brief,
)
from lumen_ingestion.brief_agent import (
    BRIEF_PROMPT_PATH,
    NullBriefAgent,
    build_brief_request,
    generate_brief,
    load_brief_prompt,
)
from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.normalizer import normalize_evidence

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion"
EXPECTED = FIXTURES / "expected"
REPO_ROOT = Path(__file__).resolve().parents[3]
LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"


def _kit() -> dict:
    """The committed golden kit for the website fixture — a real emitted kit."""
    return json.loads((EXPECTED / "evidence_website_insight.json").read_text())["brand_kit"]


def _evidence() -> BrandEvidence:
    return BrandEvidence.model_validate(
        json.loads((FIXTURES / "evidence_website_insight.json").read_text())
    )


def _kit_with_bands() -> tuple[BrandEvidence, dict]:
    """The website fixture wearing the real Stripe harvest's background rhythm.

    Its two navy sections mint `surface.band.statement`, which is the whole
    point: a name for the color the page stands on.
    """
    harvest = json.loads(
        (FIXTURES / "geometry" / "stripe_home.json").read_text()
    )
    parsed = parse_geometry(harvest, page_url="https://stripe.com/")
    evidence = _evidence().model_copy(update={"geometry": parsed.evidence()})
    kit = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_bands",
        version=1,
        name="Bands",
        created_at="2026-07-05",
    ).brand_kit
    return evidence, kit


def _brief_payload(**overrides) -> dict:
    """A brief a well-behaved agent could have written about the Insight fixture."""
    payload = {
        "schema_version": 1,
        "characterization": {
            "words": ["calm", "clinical", "optimistic"],
            "support": "Trustworthy teal ink over generous white, one accent.",
            "confidence": "medium",
        },
        "chromatic_moment": {
            "element": "the pricing card that flips to a filled surface",
            "token": "surface.brand",
            "surrounding": "three quiet cards on surface.card",
            "quiet": False,
            "confidence": "low",
        },
        "signature_compositions": [
            {
                "name": "one-loud-card pricing row",
                "structure": "four cards, exactly one filled",
                "strength": "STRONG",
                "confidence": "low",
            }
        ],
        "palette_application": [
            {
                "token": "surface.brand",
                "scope": "statement-surface",
                "evidence": "the single filled pricing card",
                "confidence": "medium",
            },
            {
                "token": "text.primary",
                "scope": "ink",
                "evidence": "every heading and body run",
                "confidence": "high",
            },
        ],
        "background_rhythm": {
            "bands": [
                {"index": 0, "token": "surface.canvas", "note": "hero"},
                {"index": 1, "token": "surface.card", "note": "features"},
            ],
            "ratio_summary": "1 tinted band : 1 canvas band",
            "differentiation": "chromatic",
            "confidence": "low",
        },
        "typographic_posture": {
            "case_posture": "sentence case throughout",
            "scale_temperament": "restrained",
            "signature_moves": ["tracked uppercase eyebrow above each section"],
            "tokens": ["type.headline", "type.body"],
            "confidence": "medium",
        },
        "imagery_posture": {
            "diet": "product-ui-led",
            "slots": ["hero right half"],
            "absences": ["no photography anywhere in pricing"],
            "confidence": "low",
        },
        "constraints": [
            {
                "rule": "surface.brand is the sole saturated fill on a page",
                "scope": "every page",
                "confidence": "medium",
            }
        ],
        "component_recipes": [
            {
                "component": "button",
                "variant": "solid",
                "radius": "radius.button",
                "padding": "space.3",
                "border": None,
                "shadow": None,
                "background": "surface.brand",
                "text": "text.inverse",
                "unmapped": [],
                "confidence": "high",
            }
        ],
        "diagnostics": [
            {
                "observation": "a warm sand band under the footer",
                "reason": "no kit color token carries that value",
            }
        ],
    }
    payload.update(overrides)
    return payload


# --- the schema -------------------------------------------------------------------


def test_a_grounded_brief_validates_and_keeps_every_section() -> None:
    brief = validate_brief(_brief_payload(), token_names=kit_token_names(_kit()))
    assert isinstance(brief, BrandBrief)
    assert brief.schema_version == BRIEF_SCHEMA_VERSION == 1
    assert brief.characterization.words == ["calm", "clinical", "optimistic"]
    assert brief.component_recipes[0].radius == "radius.button"
    assert brief.diagnostics[0].reason.startswith("no kit color token")


def test_absence_is_a_correct_answer() -> None:
    """Evidence-or-silence: every list section may be empty, and the chromatic
    moment may say the brand simply runs quiet."""
    payload = _brief_payload(
        signature_compositions=[],
        palette_application=[],
        constraints=[],
        component_recipes=[],
        diagnostics=[],
        chromatic_moment={
            "element": None,
            "token": None,
            "surrounding": None,
            "quiet": True,
            "confidence": "low",
        },
        background_rhythm={
            "bands": [],
            "ratio_summary": None,
            "differentiation": None,
            "confidence": "low",
        },
        imagery_posture={
            "diet": "text-forward",
            "slots": [],
            "absences": ["no imagery at all"],
            "confidence": "low",
        },
    )
    brief = validate_brief(payload, token_names=kit_token_names(_kit()))
    assert brief.chromatic_moment.quiet is True
    assert brief.component_recipes == []


def test_a_recipe_carrying_a_raw_hex_is_refused() -> None:
    payload = _brief_payload()
    payload["component_recipes"][0]["background"] = "#00A37A"
    with pytest.raises(BriefRefused) as refusal:
        validate_brief(payload, token_names=kit_token_names(_kit()))
    assert "#00A37A" in str(refusal.value)


def test_a_recipe_carrying_a_pixel_value_is_refused() -> None:
    payload = _brief_payload()
    payload["component_recipes"][0]["radius"] = "8px"
    with pytest.raises(BriefRefused):
        validate_brief(payload, token_names=kit_token_names(_kit()))


def test_a_token_name_the_kit_does_not_carry_is_refused() -> None:
    payload = _brief_payload()
    payload["component_recipes"][0]["background"] = "surface.invented"
    with pytest.raises(BriefRefused) as refusal:
        validate_brief(payload, token_names=kit_token_names(_kit()))
    assert "surface.invented" in str(refusal.value)


def test_every_token_bearing_section_is_checked_against_the_kit() -> None:
    """The token law is not recipe-only: the chromatic moment, the palette
    application, the background bands and the type tokens carry names too."""
    for section, mutate in (
        ("chromatic_moment", lambda p: p["chromatic_moment"].update(token="surface.nope")),
        ("palette_application", lambda p: p["palette_application"][0].update(token="ink.nope")),
        (
            "background_rhythm",
            lambda p: p["background_rhythm"]["bands"][0].update(token="surface.nope"),
        ),
        (
            "typographic_posture",
            lambda p: p["typographic_posture"].update(tokens=["type.nope"]),
        ),
    ):
        payload = _brief_payload()
        mutate(payload)
        with pytest.raises(BriefRefused, match="nope"):
            validate_brief(payload, token_names=kit_token_names(_kit()))


def test_a_band_the_kit_minted_is_a_name_the_brief_may_speak() -> None:
    """The token law cuts both ways.

    A kit whose measured rhythm minted `surface.band.statement` must offer that
    name to the agent (in the prompt payload AND in the validation dictionary),
    or the agent is back to approximating the one color the page stands on.
    """
    evidence, kit = _kit_with_bands()
    assert "surface.band.statement" in kit["tokens"]["colors"]

    request = build_brief_request(evidence, kit)
    assert "surface.band.statement" in request.token_names
    assert any(token["name"] == "surface.band.statement" for token in request.tokens)

    payload = _brief_payload()
    payload["background_rhythm"]["bands"][0]["token"] = "surface.band.statement"
    brief = validate_brief(payload, token_names=kit_token_names(kit))
    assert brief.background_rhythm.bands[0].token == "surface.band.statement"


def test_a_palette_scope_outside_the_grammar_is_refused() -> None:
    payload = _brief_payload()
    payload["palette_application"][0]["scope"] = "decoration"
    with pytest.raises(BriefRefused):
        validate_brief(payload, token_names=kit_token_names(_kit()))


def test_a_composition_without_its_strength_tag_is_refused() -> None:
    payload = _brief_payload()
    del payload["signature_compositions"][0]["strength"]
    with pytest.raises(BriefRefused):
        validate_brief(payload, token_names=kit_token_names(_kit()))


def test_a_missing_section_is_refused() -> None:
    payload = _brief_payload()
    del payload["characterization"]
    with pytest.raises(BriefRefused):
        validate_brief(payload, token_names=kit_token_names(_kit()))


def test_a_non_object_output_is_refused_not_crashed() -> None:
    with pytest.raises(BriefRefused):
        validate_brief("I could not ground a brief.", token_names={"surface.brand"})


def test_kit_token_names_collects_every_group_including_aliases() -> None:
    names = kit_token_names(_kit())
    assert {"surface.brand", "type.body", "radius.button", "space.1", "shadow.sm"} <= names
    assert "accent.primary" in names  # an alias is a usable name


def test_the_brief_schema_carries_no_contact_or_person_field() -> None:
    """DSAR posture unchanged: the brief is brand copy about a website, never
    personal data. No field may invite a person into it."""
    forbidden = {
        "email",
        "phone",
        "person",
        "people",
        "contact",
        "author",
        "employee",
        "customer",
        "address",
        "linkedin",
        "twitter",
        "handle",
        "avatar",
        "headshot",
        "quote_attribution",
    }
    schema = json.dumps(BrandBrief.model_json_schema()).lower()
    for word in forbidden:
        assert word not in schema, f"BrandBrief@1 mentions {word!r}"


# --- the agent stage ---------------------------------------------------------------


def test_the_request_hands_the_agent_the_evidence_it_may_not_go_and_get() -> None:
    request = build_brief_request(
        _evidence(),
        _kit(),
        screenshots=[("aGVsbG8=", "image/png")],
    )
    assert request.brand_name
    # Tokens ride WITH provenance — the prompt tells the agent to read it.
    assert any(token["provenance"].startswith("website:") for token in request.tokens)
    assert any(token["provenance"].startswith("derived:") for token in request.tokens)
    assert request.screenshots == [("aGVsbG8=", "image/png")]
    assert request.token_names == kit_token_names(_kit())
    # Slice-2 evidence, handed over whole.
    assert isinstance(request.shapes, list)
    assert isinstance(request.background_sequence, list)


def test_the_system_prompt_is_the_committed_controller_authored_file() -> None:
    text = load_brief_prompt()
    assert BRIEF_PROMPT_PATH.name == "brief_agent_prompt.md"
    assert text == BRIEF_PROMPT_PATH.read_text()
    # The two promises the harness has to keep true.
    assert "evidence or silence" in text.lower()
    assert "BrandBrief@1" in text
    # …and the band vocabulary the kit now mints, so the agent names a recurring
    # background by its token instead of the nearest approximation.
    assert "surface.band." in text


def test_an_unconfigured_brief_stage_is_silent() -> None:
    diagnostics: list[dict] = []
    brief = generate_brief(
        build_brief_request(_evidence(), _kit()),
        agent=NullBriefAgent(),
        diagnostics=diagnostics,
    )
    assert brief is None
    assert diagnostics == []


def test_a_refusing_agent_leaves_the_kit_briefless_with_a_diagnostic() -> None:
    class Refuser:
        active = True

        def write_brief(self, request):
            raise BriefRefused("one page of evidence could not ground a brief")

    diagnostics: list[dict] = []
    brief = generate_brief(
        build_brief_request(_evidence(), _kit()),
        agent=Refuser(),
        diagnostics=diagnostics,
    )
    assert brief is None
    assert [d["code"] for d in diagnostics] == ["LUMI0901"]
    assert "could not ground" in diagnostics[0]["message"]


def test_an_invalid_brief_leaves_the_kit_briefless_with_a_diagnostic() -> None:
    class Fabricator:
        active = True

        def write_brief(self, request):
            payload = _brief_payload()
            payload["component_recipes"][0]["background"] = "#00A37A"
            return payload

    diagnostics: list[dict] = []
    brief = generate_brief(
        build_brief_request(_evidence(), _kit()),
        agent=Fabricator(),
        diagnostics=diagnostics,
    )
    assert brief is None
    assert [d["code"] for d in diagnostics] == ["LUMI0902"]


def test_an_agent_that_throws_never_fails_the_stage() -> None:
    class Exploder:
        active = True

        def write_brief(self, request):
            raise RuntimeError("the gateway hung up")

    diagnostics: list[dict] = []
    brief = generate_brief(
        build_brief_request(_evidence(), _kit()),
        agent=Exploder(),
        diagnostics=diagnostics,
    )
    assert brief is None
    assert [d["code"] for d in diagnostics] == ["LUMI0903"]


def test_a_grounded_agent_returns_a_serializable_brief() -> None:
    class Writer:
        active = True

        def write_brief(self, request):
            return _brief_payload()

    diagnostics: list[dict] = []
    brief = generate_brief(
        build_brief_request(_evidence(), _kit()),
        agent=Writer(),
        diagnostics=diagnostics,
    )
    assert diagnostics == []
    assert brief is not None
    # A plain JSON object — this is what rides `brand_kit_json.brief`.
    assert json.loads(json.dumps(brief)) == brief
    assert brief["schema_version"] == 1


def test_the_agent_browses_nothing() -> None:
    """Plan constraint: the brief agent's evidence is handed to it. Its tool set
    is empty by construction, so it cannot go and fetch a second page."""
    from lumen_ingestion.brief_agent import OpenRouterBriefAgent

    assert OpenRouterBriefAgent.TOOLS == ()


def test_the_brief_model_is_built_with_its_own_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brief's model and reasoning effort are its own settings, handed to the gateway
    build as-is (founder ruling 2026-09-29: grok-4.7 at medium)."""
    import lumen_agent.llm as llm
    from lumen_ingestion import brief_agent
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "lumen_ingestion_brief", True)
    monkeypatch.setattr(settings, "lumen_ingestion_brief_model", "x-ai/grok-4.7")
    monkeypatch.setattr(settings, "lumen_ingestion_brief_reasoning", "medium")
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test")
    built: dict = {}

    class _Stop(Exception):
        pass

    def fake_init_model(model: str, **kwargs: object) -> None:
        built.update(kwargs, model=model)
        raise _Stop

    monkeypatch.setattr(llm, "init_model", fake_init_model)
    with pytest.raises(_Stop):
        brief_agent.OpenRouterBriefAgent().write_brief(build_brief_request(_evidence(), _kit()))
    assert built["model"] == "x-ai/grok-4.7"
    assert built["reasoning"] == "medium"
    assert built["role"] == "ingestion-brief"


# --- the pipeline ride-along --------------------------------------------------------


def _run_website_ingestion_through_the_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    brief_agent,
    url: str,
) -> dict:
    """Drive the real website route with a stubbed capture and the given agent."""
    from lumen_api import main as main_module
    from lumen_ingestion.pipeline import run_website_ingestion

    png_bytes = LOGO_PNG_PATH.read_bytes()

    async def fake_capture(url, *, reporter, force_render=False, page_urls=None):
        class Outcome:
            tier = "static"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        core.ingest_asset(
            store_root=store_root,
            bytes_base64=base64.b64encode(png_bytes).decode("ascii"),
            asset_id="asset_ing_brief01",
            label="brief logo",
            declared_mime_type="image/png",
            filename="brief.png",
            kind="raster_image",
            tags=["brand-ingestion", "image"],
            raise_on_error=False,
        )
        return _evidence()

    async def passthrough(target: str) -> str:
        return target

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: passthrough)
    monkeypatch.setattr(
        main_module,
        "run_website_ingestion",
        lambda cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None: (
            run_website_ingestion(
                cache_dir,
                job_id,
                capture=fake_capture,
                build_evidence=fake_build_evidence,
                brief_agent=brief_agent,
                workspace_id=workspace_id,
                storage=storage,
                expected_generation=expected_generation,
            )
        ),
    )

    post = client.post("/brand-kits/ingest/website", json={"url": url})
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert job["status"] == "succeeded", job
    return job


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache"))


def test_the_published_approved_kit_carries_the_brief(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Writer:
        active = True

        def write_brief(self, request):
            return _brief_payload()

    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, brief_agent=Writer(), url="https://brief-rides.example"
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert detail["brand_kit"]["approval_status"] == "approved"
    brief = detail["brand_kit_json"]["brief"]
    assert brief["schema_version"] == 1
    assert brief["characterization"]["words"] == ["calm", "clinical", "optimistic"]


def test_an_unconfigured_stage_publishes_a_kit_with_no_brief_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Byte-stability: no agent → the kit is exactly the kit today's pipeline
    publishes, with no `brief` key and no diagnostic about one."""
    job = _run_website_ingestion_through_the_route(
        client,
        monkeypatch,
        brief_agent=NullBriefAgent(),
        url="https://no-brief.example",
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert "brief" not in detail["brand_kit_json"]
    codes = {d.get("code") for d in detail["diagnostics"]["audit"]}
    assert not {code for code in codes if str(code).startswith("LUMI09")}


def test_a_refused_brief_still_publishes_the_kit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Refuser:
        active = True

        def write_brief(self, request):
            raise BriefRefused("no evidence for a chromatic moment")

    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, brief_agent=Refuser(), url="https://refused.example"
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert "brief" not in detail["brand_kit_json"]
    codes = {d.get("code") for d in detail["diagnostics"]["audit"]}
    assert "LUMI0901" in codes


def test_approval_does_not_mutate_the_brief(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Writer:
        active = True

        def write_brief(self, request):
            return _brief_payload()

    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, brief_agent=Writer(), url="https://approved-brief.example"
    )
    kit_id = job["brand_kit_id"]
    before = client.get(f"/brand-kits/{kit_id}").json()["brand_kit_json"]["brief"]

    approved = client.post(
        f"/brand-kits/{kit_id}/approval", json={"approval_status": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["brand_kit_json"]["approval_status"] == "approved"
    # The brief rides the approval flip untouched — approval is a status change,
    # never a re-write of the reviewed content.
    assert approved.json()["brand_kit_json"]["brief"] == before

    row = client.get(f"/brand-kits/{kit_id}").json()
    assert row["brand_kit_json"]["brief"] == before
    assert row["brand_kit"]["approval_status"] == "approved"


def test_a_pre_brief_era_approved_kit_still_serves(client: TestClient) -> None:
    """Back-compat: a kit approved before the brief existed has no `brief` key
    and every read of it keeps working."""
    from lumen_api.design_store import HybridRepository

    HybridRepository().create_brand_kit(
        {
            "id": "kit_pre_brief",
            "version": 3,
            "name": "Stripe",
            "approval_status": "approved",
            "description": None,
        },
        {"product_ready": False},
        [],
        "website",
    )
    detail = client.get("/brand-kits/kit_pre_brief")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert "brief" not in body["brand_kit_json"]
    assert body["brand_kit"]["approval_status"] == "approved"
    assert any(row["id"] == "kit_pre_brief" for row in client.get("/brand-kits").json())
