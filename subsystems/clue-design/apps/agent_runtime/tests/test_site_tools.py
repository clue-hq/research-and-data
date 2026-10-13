"""The site agent's core tools (Lane B Task 6); validator tests ported from the Puck spike."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_agent.site import tools as site_tools
from lumen_agent.site.tools import SiteTools, site_tool_set
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeAssets, FakeVersions, garner_brand, garner_site, inputs_for, png

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
PHOTO = "f" * 64


def _tools(tmp_path: Path, **overrides) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(**overrides)
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def _edit(tools: SiteTools, change) -> None:
    page = json.loads((tools.workspace / "page.json").read_text())
    change(page)
    (tools.workspace / "page.json").write_text(json.dumps(page, indent=2))


def _section(page: dict, section_id: str) -> dict:
    return next(item for item in page["content"] if item["props"]["id"] == section_id)


@needs_node
def test_the_phase1_page_validates_clean(tmp_path: Path) -> None:
    assert _tools(tmp_path).validate_page() == "VALID."


@needs_node
def test_schema_errors_pass_through_with_the_allowed_choices(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "proof")["props"].update(surface="green"))
    result = tools.validate_page()
    assert result.startswith("INVALID") and "surface" in result and "brandSubtle" in result


@needs_node
def test_an_unknown_slot_is_refused_listing_the_clone_slots(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "hero")["props"]["slots"].update(subheadline="x"))
    result = tools.validate_page()
    assert "subheadline" in result and "headline" in result and "cta_href" in result


@needs_node
def test_an_image_must_come_from_the_turns_brand(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: p["content"].append({"type": "FeatureSplit", "props": {
        "id": "extra", "surface": "page", "heading": "H", "body": "B", "image": "https://example.com/stock.jpg"}}))
    result = tools.validate_page()
    assert "stock.jpg" in result and "brand/brand.md" in result


@needs_node
def test_the_same_error_three_times_triggers_the_loop_guard(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "proof")["props"].update(surface="green"))
    first, second, third = tools.validate_page(), tools.validate_page(), tools.validate_page()
    assert "third time" not in first and "third time" not in second and "third time" in third


def test_a_validator_that_cannot_run_reads_as_an_invalid_page(tmp_path: Path, monkeypatch) -> None:
    from lumen_api.site_kit_cli import SiteKitCliError

    def broken(*args, **kwargs):
        raise SiteKitCliError("site_kit.toolchain_missing", "node is not on PATH")

    monkeypatch.setattr(site_tools, "validate_site_files", broken)
    result = _tools(tmp_path).validate_page()
    assert result.startswith("INVALID (1 error):") and "validator crashed: node is not on PATH" in result


def test_restore_version_brings_back_a_saved_version_of_every_page(tmp_path: Path) -> None:
    earlier = garner_site()
    del earlier["pages"]["/analysis"]
    tools = _tools(tmp_path, site_versions=FakeVersions(sites={3: earlier}))
    (tools.workspace / "pages" / "extra.json").write_text("{}")
    assert tools.restore_version(3) == "restored version 3 into page.json, shell.json and pages/."
    assert not (tools.workspace / "pages").exists() or not list((tools.workspace / "pages").glob("*.json"))
    assert json.loads((tools.workspace / "page.json").read_text()) == earlier["pages"]["/"]
    assert tools.restore_version(9) == "No version 9. Saved versions: [3]."


def test_view_asset_shows_a_turn_image_and_refuses_others(tmp_path: Path) -> None:
    brand = garner_brand()
    brand["assets"]["asset_photo"] = {"kind": "raster_image", "label": "Hallway", "description": "A school hallway",
                                      "mime": "image/png", "file": f"/asset-store/{PHOTO}", "logo": None}
    tools = _tools(tmp_path, brand=brand, assets=FakeAssets(blobs={PHOTO: ("image/png", png())}))
    blocks = tools.view_asset([f"/asset-store/{PHOTO}", "/asset-store/" + "0" * 64])
    assert blocks[0] == {"type": "text", "text": f"/asset-store/{PHOTO}: A school hallway"}
    assert blocks[1]["type"] == "image"
    assert "not one of this site's images" in blocks[2]["text"]


def test_fetch_page_saves_the_text_as_evidence_through_the_guard(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent.tools import web_substrate

    monkeypatch.setattr(web_substrate, "_fetch_grounded_page",
                        lambda url: {"text": "Saved 12% in year one.", "http_status": 200})
    tools = _tools(tmp_path)
    result = tools.fetch_page("https://garnerhealth.com/story")
    assert result.startswith("Saved to fetched/") and "(status 200)" in result and "Saved 12%" in result
    saved = list((tools.workspace / "fetched").glob("*.md"))
    assert saved and "Source: https://garnerhealth.com/story" in saved[0].read_text()


def test_fetch_page_reports_a_refused_url_without_retrying(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent.tools import web_substrate
    from lumen_ingestion.capture.net import CaptureError

    calls = []

    def refused(url):
        calls.append(url)
        raise CaptureError("LUMI0501", "blocked address")

    monkeypatch.setattr(web_substrate, "_fetch_grounded_page", refused)
    assert _tools(tmp_path).fetch_page("http://127.0.0.1/x").startswith("FETCH FAILED:")
    assert len(calls) == 1


def test_web_search_retries_a_transient_failure(tmp_path: Path) -> None:
    class FlakyReads:
        calls = 0

        def web_search(self, **kwargs):
            FlakyReads.calls += 1
            if FlakyReads.calls == 1:
                raise RuntimeError("timeout")
            return {"results": [{"title": "Aon study", "url": "https://garnerhealth.com/blog/aon"}]}

        def seller_knowledge(self):
            raise RuntimeError("no pin")

    tools = _tools(tmp_path, platform_reads=FlakyReads())
    assert "Aon study" in tools.web_search("Aon study", include_domains=["garnerhealth.com"])
    assert FlakyReads.calls == 2


def test_the_tool_set_holds_only_the_methods_that_exist_and_events_carry_no_operations(tmp_path: Path) -> None:
    received: list[tuple[str, dict]] = []
    tools = _tools(tmp_path)
    tools.event_sink = lambda event_type, data: received.append((event_type, data))
    names = [tool.name for tool in site_tool_set(tools)]
    assert {"validate_page", "restore_version", "view_asset", "web_search", "fetch_page"} <= set(names)
    assert all(name in site_tools.TOOL_DESCRIPTIONS for name in names)
    tools._record("valid")
    assert received == [("site_valid", {})]
    assert all("operations" not in data for _, data in received)
