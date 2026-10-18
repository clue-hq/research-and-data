"""T2: the agent's tools, tested on the phase-1 Garner page before any agent sees them.

Run from the repo root:
    .venv/bin/python -m pytest trials/puck-spike/agent/tests -q
render_page tests need the spike dev server on :3047 and are skipped without it.
"""

from __future__ import annotations

import base64
import http.server
import json
import shutil
import socket
import threading
from pathlib import Path

import pytest

from trials_puck_agent.tools import PageTools, _difference, _missing_words  # noqa: E402  (path set in conftest)

SPIKE = Path(__file__).resolve().parents[2]
SITE = json.loads((SPIKE / "data" / "sites" / "garner-syracuse.json").read_text())

EVIDENCE = """# Fixture evidence (the facts the phase-1 page uses)
2025-26 Proposed Budget Presentation: "Healthcare increase of $4.2 million based on plan changes
and claim projections from our actuaries." Plans: PPO, PPO 3 and HDHP 2.
Aon study, published by Garner on March 31, 2026 (2020 to 2024): Garner-eligible group had 7.4% lower medical spend, $345 lower medical
spend Per Member Per Year (PMPY). Provider Impact Analysis: personalized 30-minute review.
"""

BRIEF = """For the page
- A 1:1 page for Syracuse City School District.

Notes for Design, never shown on the page
- Vendor case study, not independent causal proof.
- Do not quote 8% and 12% as medical-only.
"""


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    (ws / "research").mkdir(parents=True)
    (ws / "seller").mkdir()
    (ws / "fetched").mkdir()
    (ws / "page.json").write_text(json.dumps(SITE["pages"]["/"], indent=2))
    (ws / "pages").mkdir()  # the phase-1 home page links to /analysis
    (ws / "pages" / "analysis.json").write_text(json.dumps(SITE["pages"]["/analysis"], indent=2))
    (ws / "shell.json").write_text(json.dumps(SITE["shell"], indent=2))
    (ws / "brief.md").write_text(BRIEF)
    (ws / "research" / "evidence.md").write_text(EVIDENCE)
    (ws / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": "agent-test", "route": "/"})
    )
    return ws


def tools_for(ws: Path) -> PageTools:
    return PageTools(workspace=ws, spike_root=SPIKE, base_url="http://localhost:3047")


def edit_page(ws: Path, change) -> None:
    page = json.loads((ws / "page.json").read_text())
    change(page)
    (ws / "page.json").write_text(json.dumps(page, indent=2))


def section(page: dict, section_id: str) -> dict:
    return next(item for item in page["content"] if item["props"]["id"] == section_id)


def test_the_phase1_page_validates_clean_and_saves_version_1(workspace: Path) -> None:
    result = tools_for(workspace).validate_page()
    assert result.startswith("VALID"), result
    assert "version 1" in result
    assert (workspace / "versions" / "1.json").exists()


def test_schema_errors_pass_through_with_the_allowed_choices(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"].update(surface="green"))
    result = tools_for(workspace).validate_page()
    assert result.startswith("INVALID")
    assert "surface" in result and "brandSubtle" in result


def test_an_unknown_slot_is_refused_listing_the_clone_slots(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "hero")["props"]["slots"].update(subheadline="x"))
    result = tools_for(workspace).validate_page()
    assert "subheadline" in result and "headline" in result and "cta_href" in result


def test_a_replacement_must_match_text_in_the_clone(workspace: Path) -> None:
    edit_page(
        workspace,
        lambda p: section(p, "hero")["props"]["replacements"].append(
            {"find": "Book now", "replace": "x"}
        ),
    )
    result = tools_for(workspace).validate_page()
    assert "Book now" in result and "catalog/clones/frag_95041c54da629d99.md" in result


def test_an_image_must_come_from_the_brand_assets(workspace: Path) -> None:
    def change(page: dict) -> None:
        page["content"].append(
            {
                "type": "FeatureSplit",
                "props": {
                    "id": "extra",
                    "surface": "page",
                    "heading": "H",
                    "body": "B",
                    "image": "https://example.com/stock.jpg",
                },
            }
        )

    edit_page(workspace, change)
    result = tools_for(workspace).validate_page()
    assert "stock.jpg" in result and "brand/brand.md" in result


def test_judgement_is_not_a_blocking_check(workspace: Path) -> None:
    """Founder ruling 2026-10-08: numbers, named people and wording from the brief's notes are the
    agent's judgement (prompt and skills), never validator errors."""

    def change(page: dict) -> None:
        proof = section(page, "proof")["props"]
        proof["stats"][0]["value"] = "9.9%"
        proof["intro"] = "This is not independent causal proof of anything."
        proof["eyebrow"] = "For Nalisa Clark"

    edit_page(workspace, change)
    assert tools_for(workspace).validate_page().startswith("VALID")


def test_only_one_primary_destination(workspace: Path) -> None:
    def change(page: dict) -> None:
        page["content"].append(
            {
                "type": "CtaBand",
                "props": {
                    "id": "cta2",
                    "surface": "brand",
                    "heading": "Other",
                    "buttonLabel": "Go",
                    "buttonHref": "https://example.com/other-offer",
                },
            }
        )

    edit_page(workspace, change)
    result = tools_for(workspace).validate_page()
    assert "one primary destination" in result


def test_the_same_error_three_times_triggers_the_loop_guard(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"].update(surface="green"))
    tools = tools_for(workspace)
    first, second, third = tools.validate_page(), tools.validate_page(), tools.validate_page()
    assert "third time" not in first and "third time" not in second
    assert "third time" in third


def test_restore_version_rolls_back_a_bad_change(workspace: Path) -> None:
    tools = tools_for(workspace)
    assert tools.validate_page().startswith("VALID")
    original = (workspace / "page.json").read_text()
    edit_page(workspace, lambda p: p["content"].pop())
    assert "restored version 1" in tools.restore_version(1)
    assert (workspace / "page.json").read_text() == original


def test_restore_version_brings_back_every_page(workspace: Path) -> None:
    tools = tools_for(workspace)
    assert tools.validate_page().startswith("VALID")
    (workspace / "pages" / "analysis.json").unlink()
    (workspace / "pages" / "extra.json").write_text(json.dumps(SITE["pages"]["/analysis"]))
    tools.restore_version(1)
    assert sorted(p.name for p in (workspace / "pages").glob("*.json")) == ["analysis.json"]


def test_render_page_refuses_an_unknown_page(workspace: Path) -> None:
    result = tools_for(workspace).render_page("/pricing")
    assert isinstance(result, str) and "no page /pricing" in result and "/analysis" in result


def test_render_page_refuses_an_invalid_page(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"].update(surface="green"))
    result = tools_for(workspace).render_page()
    assert isinstance(result, str) and result.startswith("NOT RENDERED")


def _server_up() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", 3047)) == 0


@pytest.mark.skipif(not _server_up(), reason="spike dev server not running on :3047")
def test_render_page_renders_a_named_page(workspace: Path) -> None:
    blocks = tools_for(workspace).render_page("/analysis")
    assert not isinstance(blocks, str), blocks
    assert sorted(p.name for p in (workspace / "renders").glob("*.png")) == [
        "1-analysis-1440.png",
        "1-analysis-375.png",
    ]


@pytest.mark.skipif(not _server_up(), reason="spike dev server not running on :3047")
def test_render_page_returns_desktop_and_mobile_screenshots(workspace: Path) -> None:
    blocks = tools_for(workspace).render_page()
    images = [b for b in blocks if b.get("type") == "image"]
    texts = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    assert len(images) >= 4  # tall pages arrive in parts that keep their width
    assert "1440" in texts and "375" in texts and "top to bottom" in texts
    widths = {base64.b64decode(b["data"])[16:20] for b in images}
    assert len(widths) == 2  # 720 (desktop at half size) and 375 (mobile at full size)
    assert "broken images: 0" in texts


def test_fetch_page_saves_the_text_as_evidence(workspace: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "story.html").write_text(
        "<html><body><h1>Case study</h1><p>Saved 12% in year one.</p></body></html>"
    )
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(site), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/story.html"
        result = tools_for(workspace).fetch_page(url)
        assert "Saved 12% in year one." in result
        saved = list((workspace / "fetched").glob("*.md"))
        assert saved and url in saved[0].read_text()
    finally:
        server.shutdown()


def test_web_search_retries_a_transient_failure(workspace: Path) -> None:
    class FlakyReads:
        calls = 0

        def web_search(self, **kwargs):
            FlakyReads.calls += 1
            if FlakyReads.calls == 1:
                raise RuntimeError("timeout")
            return {"results": [{"title": "Aon study", "url": "https://garnerhealth.com/blog/aon"}]}

    tools = PageTools(
        workspace=workspace,
        spike_root=SPIKE,
        base_url="http://localhost:3047",
        reads=FlakyReads(),
        retry_delay_s=0,
    )
    result = tools.web_search("Aon study", include_domains=["garnerhealth.com"])
    assert "Aon study" in result and FlakyReads.calls == 2


def test_write_section_joins_only_its_own_site(workspace: Path) -> None:
    """E5: a section that passes the brand-token check joins its own site; one that fails never
    reaches the app; another site cannot use it."""
    skill = (SPIKE / "agent" / "skills-e5" / "writing-a-section" / "SKILL.md").read_text()
    example = skill.split("```tsx")[1].split("```")[0]
    site = "agent-test-e5"
    (workspace / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": site, "route": "/"})
    )
    tools = tools_for(workspace)
    root = SPIKE / "puck" / "agent-sections"
    try:
        refused = tools.write_section(
            "BadQuote", example.replace("text-ink-secondary", "text-emerald-600")
        )
        assert refused.startswith("NOT WRITTEN") and "palette colour" in refused
        assert not (root / site / "BadQuote.tsx").exists()

        written = tools.write_section("QuoteBand", example)
        assert written.startswith("WRITTEN"), written
        assert '"QuoteBand"' in (root / "index.ts").read_text()
        components = (workspace / "catalog" / "seller-components.md").read_text()
        assert "## QuoteBand" in components and '"attribution"' in components

        edit_page(
            workspace,
            lambda p: p["content"].append(
                {
                    "type": "QuoteBand",
                    "props": {
                        "id": "q",
                        "surface": "muted",
                        "quote": "A line.",
                        "attribution": "Someone",
                    },
                }
            ),
        )
        assert tools.validate_page().startswith("VALID")
        (workspace / ".run.json").write_text(
            json.dumps({"brand": "garner", "site": "another-site", "route": "/"})
        )
        assert 'unknown component "QuoteBand"' in tools.validate_page()
    finally:
        shutil.rmtree(root / site, ignore_errors=True)
        tools._write_section_index()


def _png(colour: str, size: tuple[int, int]) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_difference_score_compares_at_one_width_and_pads_heights() -> None:
    same, _, heights = _difference(_png("white", (200, 100)), _png("white", (100, 50)))
    assert same == 0 and heights == (
        100,
        100,
    )  # the rebuilt picture is scaled to the original's width
    taller, pair, heights = _difference(_png("white", (200, 100)), _png("white", (200, 150)))
    assert heights == (100, 150) and taller == 0  # padding is white, like the page
    different, _, _ = _difference(_png("white", (200, 100)), _png("black", (200, 100)))
    assert different == 1.0
    assert pair[:8] == b"\x89PNG\r\n\x1a\n"


def test_missing_words_lists_the_originals_words_once_in_order() -> None:
    assert _missing_words("Find the right doctors. Find savings!", "the right doctors") == [
        "find",
        "savings",
    ]
    assert _missing_words("Short a an", "") == ["short"]  # words under four letters are ignored


def test_view_clone_refuses_an_unknown_clone(workspace: Path) -> None:
    assert tools_for(workspace).view_clone("nope").startswith("No clone nope")


def test_compare_section_needs_the_component_first(workspace: Path) -> None:
    assert "write it with write_section first" in tools_for(workspace).compare_section(
        "Missing", "x", {}
    )


PANELS = """import { z } from "zod";
import type { Kit } from "@/puck/agent-kit";

export const schema = z.object({
  id: z.string(),
  surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),
  heading: z.string(),
  photo: z.string(),
}).strict();

export function render(props: z.infer<typeof schema>, kit: Kit) {
  return (
    <div className="grid md:grid-cols-2">
      <div className="relative min-h-80 bg-surface-inverse text-on-surface-inverse">
        <kit.Image src={props.photo} fit="fill" />
      </div>
      <div className="bg-surface-brand p-16 text-on-surface-brand">
        <h2 className="brand-heading font-title text-title">{props.heading}</h2>
      </div>
    </div>
  );
}
"""


@pytest.mark.skipif(not _server_up(), reason="the spike's dev server is not running on :3047")
def test_view_clone_and_compare_section_show_the_original_and_the_rebuild(workspace: Path) -> None:
    skill = (SPIKE / "agent" / "skills-e5" / "writing-a-section" / "SKILL.md").read_text()
    example = skill.split("```tsx")[1].split("```")[0]
    site = "agent-test-cmp"
    (workspace / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": site, "route": "/"})
    )
    tools = tools_for(workspace)
    root = SPIKE / "puck" / "agent-sections"
    clone = json.loads((SPIKE / "data" / "brands" / "garner" / "clones.json").read_text())[0]["id"]
    try:
        seen = tools.view_clone(clone)
        assert isinstance(seen, list) and sum(b["type"] == "image" for b in seen) >= 2, seen
        assert tools.write_section("QuoteBand", example).startswith("WRITTEN")
        compared = tools.compare_section(
            "QuoteBand", clone, {"quote": "A line.", "attribution": "Someone"}
        )
        assert isinstance(compared, list), compared
        assert (
            "of the area differs" in compared[0]["text"]
            and "missing from yours" in compared[0]["text"]
        )
        assert sum(b["type"] == "image" for b in compared) >= 2

        # Edge-to-edge panels without Shell, with a background photo: written, and found by the compare.
        image = json.loads((SPIKE / "data" / "brands" / "garner" / "assets.json").read_text())
        photo = next(
            a["file"] for a in image.values() if a["file"].endswith((".avif", ".png", ".jpg"))
        )
        panels = PANELS.replace("PHOTO", photo)
        assert tools.write_section("PhotoPanels", panels).startswith("WRITTEN")
        compared = tools.compare_section(
            "PhotoPanels", clone, {"heading": "A line.", "photo": photo}
        )
        assert isinstance(compared, list), compared
    finally:
        shutil.rmtree(root / site, ignore_errors=True)
        tools._write_section_index()
        for scratch in (SPIKE / "data" / "sites").glob(f"{site}*.json"):
            scratch.unlink()


@pytest.mark.skipif(not _server_up(), reason="the spike's dev server is not running on :3047")
def test_a_class_used_only_in_a_written_section_reaches_the_page(workspace: Path) -> None:
    """Tailwind must scan the agent's sections: a class no other file uses still gets its CSS."""
    from playwright.sync_api import sync_playwright

    site = "agent-test-css"
    (workspace / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": site, "route": "/"})
    )
    tools = tools_for(workspace)
    root = SPIKE / "puck" / "agent-sections"
    value = ".".join(
        ["41", "5"]
    )  # assembled here so the class appears in no source file Tailwind scans
    code = PANELS.replace('"relative min-h-80 ', f'"relative h-[{value}rem] ').replace("PHOTO", "")
    try:
        assert tools.write_section("TallPanels", code).startswith("WRITTEN")
        url = tools._scratch_url(
            [
                {
                    "type": "TallPanels",
                    "props": {"id": "t", "surface": "page", "heading": "x", "photo": ""},
                }
            ]
        )
        height = None
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            for _ in range(8):  # the dev server recompiles the CSS after the file lands
                page.goto(url, wait_until="load")
                page.wait_for_timeout(1500)
                height = page.evaluate(
                    "getComputedStyle(document.querySelector('[data-agent-section] .relative')).height"
                )
                if height == "664px":
                    break
            browser.close()
        assert height == "664px", height
    finally:
        shutil.rmtree(root / site, ignore_errors=True)
        tools._write_section_index()
        for scratch in (SPIKE / "data" / "sites").glob(f"{site}*.json"):
            scratch.unlink()


# --- R3: generated images (founder-approved 2026-10-09) ------------------------------------------


def _tiny_png(width: int = 32, height: int = 18) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 90, 70)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeImages:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def __call__(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider down")
        return SimpleNamespace(
            image_bytes=_tiny_png(),
            mime_type="image/png",
            width=32,
            height=18,
            model="test-image-model",
        )


@pytest.fixture()
def image_site(workspace: Path):
    import uuid

    site = f"agent-test-{uuid.uuid4().hex[:8]}"
    (workspace / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": site, "route": "/"})
    )
    yield site
    shutil.rmtree(SPIKE / "public" / "generated" / site, ignore_errors=True)


def _brand_photo() -> str:
    assets = json.loads((SPIKE / "data" / "brands" / "garner" / "assets.json").read_text())
    return next(a["file"] for a in assets.values() if a["file"].endswith((".png", ".avif", ".jpg")))


def test_generate_image_saves_it_for_this_site_and_shows_it(
    workspace: Path, image_site: str
) -> None:
    fake = FakeImages()
    tools = PageTools(
        workspace=workspace, spike_root=SPIKE, base_url="http://localhost:3047", image_generate=fake
    )
    reference = _brand_photo()
    blocks = tools.generate_image("A calm school-district scene at dusk", "16:9", [reference])
    text = blocks[0]["text"]
    assert text.startswith(f"/generated/{image_site}/") and "32x18" in text
    path = SPIKE / "public" / text.split()[0].lstrip("/")
    assert path.is_file() and blocks[1]["type"] == "image"
    call = fake.calls[0]
    assert (
        call["prompt"] == "A calm school-district scene at dusk" and call["aspect_ratio"] == "16:9"
    )
    assert len(call["reference_images"]) == 1 and call["reference_images"][0][1] == "image/png"
    index = json.loads((SPIKE / "public" / "generated" / image_site / "index.json").read_text())
    assert index[text.split()[0]]["prompt"] == "A calm school-district scene at dusk"


def test_generate_image_refuses_bad_references_and_reports_a_failure(
    workspace: Path, image_site: str
) -> None:
    tools = PageTools(
        workspace=workspace,
        spike_root=SPIKE,
        base_url="http://localhost:3047",
        image_generate=FakeImages(),
    )
    photo = _brand_photo()
    assert "at most three" in tools.generate_image("x", "16:9", [photo] * 4)
    assert "not one of this brand's images" in tools.generate_image(
        "x", "16:9", ["/brands/conduit/a.png"]
    )
    svg = next(
        a["file"]
        for a in json.loads(
            (SPIKE / "data" / "brands" / "garner" / "assets.json").read_text()
        ).values()
        if a["file"].endswith(".svg")
    )
    assert "a photo or picture" in tools.generate_image("x", "16:9", [svg])
    failing = PageTools(
        workspace=workspace,
        spike_root=SPIKE,
        base_url="http://localhost:3047",
        image_generate=FakeImages(fail=True),
    )
    assert "could not make the image" in failing.generate_image("x", "16:9", [])


def test_view_asset_shows_this_site_s_generated_image_but_not_another_site_s(
    workspace: Path, image_site: str
) -> None:
    tools = PageTools(
        workspace=workspace,
        spike_root=SPIKE,
        base_url="http://localhost:3047",
        image_generate=FakeImages(),
    )
    made = tools.generate_image("Abstract green waves", "1:1", [])[0]["text"].split()[0]
    blocks = tools.view_asset([made, "/generated/other-site/x.png"])
    assert blocks[0]["text"].startswith(made) and "Abstract green waves" in blocks[0]["text"]
    assert blocks[1]["type"] == "image"
    assert "not one of this site's images" in blocks[2]["text"]
