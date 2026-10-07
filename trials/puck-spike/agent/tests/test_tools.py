"""T2: the agent's tools, tested on the phase-1 Garner page before any agent sees them.

Run from the repo root:
    .venv/bin/python -m pytest trials/puck-spike/agent/tests -q
render_page tests need the spike dev server on :3047 and are skipped without it.
"""

from __future__ import annotations

import http.server
import json
import shutil
import socket
import threading
from pathlib import Path

import pytest

from trials_puck_agent.tools import PageTools  # noqa: E402  (path set in conftest)

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
    (ws / "shell.json").write_text(json.dumps(SITE["shell"], indent=2))
    (ws / "brief.md").write_text(BRIEF)
    (ws / "research" / "evidence.md").write_text(EVIDENCE)
    (ws / "research" / "people.json").write_text(json.dumps(["Nalisa Clark", "Michael Puntschenko"]))
    (ws / ".run.json").write_text(json.dumps({"brand": "garner", "site": "agent-test", "route": "/"}))
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
        lambda p: section(p, "hero")["props"]["replacements"].append({"find": "Book now", "replace": "x"}),
    )
    result = tools_for(workspace).validate_page()
    assert "Book now" in result and "catalog/clones/frag_95041c54da629d99.md" in result


def test_an_image_must_come_from_the_brand_assets(workspace: Path) -> None:
    def change(page: dict) -> None:
        page["content"].append({
            "type": "FeatureSplit",
            "props": {"id": "extra", "surface": "page", "heading": "H", "body": "B",
                      "image": "https://example.com/stock.jpg"},
        })
    edit_page(workspace, change)
    result = tools_for(workspace).validate_page()
    assert "stock.jpg" in result and "brand/brand.md" in result


def test_a_number_must_appear_in_the_evidence(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"]["stats"][0].update(value="9.9%"))
    result = tools_for(workspace).validate_page()
    assert "9.9%" in result and "fetch_page" in result


def test_wording_from_the_briefs_notes_is_refused(workspace: Path) -> None:
    edit_page(
        workspace,
        lambda p: section(p, "proof")["props"].update(intro="This is not independent causal proof of anything."),
    )
    result = tools_for(workspace).validate_page()
    assert "Notes for Design" in result


def test_people_from_the_research_are_not_named(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"].update(eyebrow="For Nalisa Clark"))
    result = tools_for(workspace).validate_page()
    assert "Nalisa Clark" in result


def test_only_one_primary_destination(workspace: Path) -> None:
    def change(page: dict) -> None:
        page["content"].append({
            "type": "CtaBand",
            "props": {"id": "cta2", "surface": "brand", "heading": "Other", "buttonLabel": "Go",
                      "buttonHref": "https://example.com/other-offer"},
        })
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


def test_render_page_refuses_an_invalid_page(workspace: Path) -> None:
    edit_page(workspace, lambda p: section(p, "proof")["props"].update(surface="green"))
    result = tools_for(workspace).render_page()
    assert isinstance(result, str) and result.startswith("NOT RENDERED")


def _server_up() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", 3047)) == 0


@pytest.mark.skipif(not _server_up(), reason="spike dev server not running on :3047")
def test_render_page_returns_desktop_and_mobile_screenshots(workspace: Path) -> None:
    blocks = tools_for(workspace).render_page()
    images = [b for b in blocks if b.get("type") == "image"]
    texts = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    assert len(images) == 2
    assert "1440" in texts and "375" in texts
    assert "broken images: 0" in texts


def test_fetch_page_saves_the_text_as_evidence(workspace: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "story.html").write_text("<html><body><h1>Case study</h1><p>Saved 12% in year one.</p></body></html>")
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

    tools = PageTools(workspace=workspace, spike_root=SPIKE, base_url="http://localhost:3047",
                      reads=FlakyReads(), retry_delay_s=0)
    result = tools.web_search("Aon study", include_domains=["garnerhealth.com"])
    assert "Aon study" in result and FlakyReads.calls == 2
