"""Offline browser evidence must detect broken controls, not just save a still."""

import json
import re

import pytest
from playwright.sync_api import sync_playwright
from test_web_substrate import _tools


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        handle = playwright.chromium.launch(headless=True)
        # Fixtures and the real vendored runtime are entirely local.
        handle.on("page", lambda page: page.route("**/*", lambda route: route.abort()))
        try:
            yield handle
        finally:
            handle.close()


def native_tabs(tmp_path, *, count=4):
    tools = _tools(tmp_path)
    items = "".join(
        f'<div id="item_{i}"><p>Choice {i}</p><p>Panel {i}</p></div>'
        for i in range(count)
    )
    result = json.loads(
        tools.author_web_page(
            '<section id="s"><div id="switcher" data-component="tabs">'
            + items
            + "</div></section>"
        )
    )
    assert result["status"] == "ok", result
    html = tools.core.web_render(tools.web_doc, tools.page_id, mode="editor")["html"]
    return tools, html


def test_native_capture_activates_each_panel_on_desktop_and_phone(tmp_path, browser):
    tools, html = native_tabs(tmp_path)
    limits = tools._capture_states(browser, html, tmp_path)
    captures = [c for c in tools._state_captures if c["kind"] == "tab-selected"]
    assert len(captures) == 8  # four actual panels at two widths, not one desktop still
    assert {(c["width"], c["panel_id"]) for c in captures} == {
        (width, f"item_{i}_panel") for width in (1440, 375) for i in range(4)
    }
    assert all(c["selection_confirmed"] and c["panel_visible"] for c in captures)
    assert all(c["keyboard"]["status"] == "observed" for c in captures)
    assert all(c["capture_scope"] == "component" for c in captures)
    assert not tools._state_capture_failures
    assert not any(limits.values())
    assert browser.contexts == []  # pages close even when a probe fails


def test_missing_controller_does_not_produce_selected_tab_receipts(tmp_path, browser):
    tools, html = native_tabs(tmp_path)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    tools._capture_states(browser, html, tmp_path)
    assert not tools._state_captures
    failures = tools._state_capture_failures
    assert failures and {f["width"] for f in failures} == {1440, 375}
    assert any(f["reason"] == "selection_not_observed" for f in failures)
    assert browser.contexts == []


def test_missing_current_page_target_is_failure_not_screenshot(tmp_path, browser):
    tools, _ = native_tabs(tmp_path)
    tools._capture_states(browser, "<html><body>Wrong render</body></html>", tmp_path)
    assert tools._state_captures == []
    assert {f["reason"] for f in tools._state_capture_failures} == {"component_missing"}


def test_capture_plan_does_not_probe_a_different_page(tmp_path, browser):
    tools, _ = native_tabs(tmp_path)
    # A real checked new-page operation, retaining the original switcher on page one.
    result = json.loads(tools.add_page("empty", "Empty", "/empty"))
    assert result["status"] == "ok", result
    html = tools.core.web_render(tools.web_doc, tools.page_id, mode="editor")["html"]
    tools._capture_states(browser, html, tmp_path)
    assert not tools._state_captures
    assert not tools._state_capture_failures


def radio_html(*, broken=False):
    inputs = "".join(
        f'<input type="radio" id="r{i}" name="product" {"checked" if i == 0 else ""}>'
        for i in range(4)
    )
    labels = "".join(f'<label for="r{i}">Choice {i}</label>' for i in range(4))
    images = "".join(
        f'<img id="picture_{i}" alt="Product {i}" '
        'src="data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22'
        "%20width=%2264%22%20height=%2264%22%3E"
        f'%3Crect%20width=%2264%22%20height=%2264%22%20fill=%22rgb({i * 60},100,100)%22/%3E%3C/svg%3E">'
        for i in range(4)
    )
    # Same clipped native inputs + CSS opacity-switch pattern used by the saved page.
    rules = "".join(
        f"#r{i}:checked~.panels #picture_{i}{{opacity:1}}" for i in range(4)
    )
    if broken:
        rules = "#picture_0{opacity:1}"
    return (
        "<html><head><style>input{position:absolute;clip:rect(0,0,0,0);width:1px;height:1px}"
        "label{display:inline-block;padding:12px}.panels{height:80px;position:relative}"
        ".panels img{position:absolute;width:64px;height:64px;opacity:0}"
        + rules
        + '</style></head><body><div data-node-id="pin" data-fragment-id="frag_test">'
        + inputs
        + labels
        + '<div class="panels">'
        + images
        + "</div></div></body></html>"
    )


def test_css_radio_capture_records_visible_image_mapping_not_all_opacity_hidden_images(
    tmp_path, browser
):
    tools, _ = native_tabs(tmp_path)
    # No native tabs on the captured page; discover the source fragment's real controls.
    tools.web_doc = tools.core.web_new_doc("radio_doc", "Radio", None)["web_doc"]
    tools.page_id = tools.web_doc["pages"][0]["id"]
    tools._capture_states(browser, radio_html(), tmp_path)
    captures = [c for c in tools._state_captures if c["kind"] == "radio-selected"]
    assert len(captures) == 8
    assert {
        (c["width"], c["control_id"], tuple(c["visible_images"])) for c in captures
    } == {
        (width, f"r{i}", (f"picture_{i}",)) for width in (1440, 375) for i in range(4)
    }
    assert all(c["source_mapping"] == "unverified" for c in captures)
    assert not tools._state_capture_failures


def test_radio_checked_state_without_image_change_is_reported(tmp_path, browser):
    tools, _ = native_tabs(tmp_path)
    tools.web_doc = tools.core.web_new_doc("radio_doc", "Radio", None)["web_doc"]
    tools.page_id = tools.web_doc["pages"][0]["id"]
    tools._capture_states(browser, radio_html(broken=True), tmp_path)
    assert not tools._state_captures
    assert any(
        f["reason"] == "media_did_not_change" for f in tools._state_capture_failures
    )


def test_capture_caps_leave_explicit_unobserved_states(tmp_path, browser):
    tools, html = native_tabs(tmp_path, count=5)
    limits = tools._capture_states(browser, html, tmp_path)
    assert len(tools._state_captures) == 8
    assert {
        (s["width"], s["state_index"], s["reason"]) for s in limits["switchers"]
    } == {(width, 4, "state_cap") for width in (1440, 375)}


def test_render_missing_one_expected_control_is_not_complete(tmp_path, browser):
    tools, html = native_tabs(tmp_path)
    html = re.sub(
        r'<button\b[^>]*id="item_3_tab"[^>]*>.*?</button>', "", html, flags=re.S
    )
    assert 'id="item_3_tab"' not in html
    tools._capture_states(browser, html, tmp_path)
    assert not tools._state_captures
    assert {f["reason"] for f in tools._state_capture_failures} == {
        "control_count_mismatch"
    }


def test_radio_transition_must_settle_before_image_receipt(tmp_path, browser):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    html = radio_html().replace("opacity:0}", "opacity:0;transition:opacity 0.25s}")
    result = capture_switchers(browser, html, tmp_path, [], (375,))
    assert len(result["captures"]) == 4
    assert not result["failures"]
    assert all(
        c["visible_images"] == [f"picture_{c['state_index']}"]
        for c in result["captures"]
    )


def test_form_radio_group_is_skipped_explicitly(tmp_path, browser):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    html = (
        radio_html()
        .replace("<body>", "<body><form>")
        .replace("</body>", "</form></body>")
    )
    result = capture_switchers(browser, html, tmp_path, [], (375,))
    assert not result["captures"]
    assert [row["reason"] for row in result["omitted"]] == ["form_controls_not_probed"]


def test_keyboard_selection_without_media_transition_is_not_keyboard_success(
    tmp_path, browser
):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    html = radio_html(broken=True).replace(
        "</body>",
        """<script>
      document.querySelectorAll('label').forEach((label,i) => label.onclick = () => {
        document.querySelectorAll('.panels img').forEach((img,j) => img.style.opacity = i === j ? 1 : 0);
      });
    </script></body>""",
    )
    result = capture_switchers(browser, html, tmp_path, [], (375,))
    assert not result["captures"]
    assert any(
        f["reason"] == "keyboard_media_transition_not_observed"
        for f in result["failures"]
    )


def test_radio_nonzero_initial_state_still_checks_all_four_states(tmp_path, browser):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    html = (
        radio_html()
        .replace('name="product" checked', 'name="product"')
        .replace('id="r1" name="product"', 'id="r1" name="product" checked')
    )
    result = capture_switchers(browser, html, tmp_path, [], (375,))
    assert len(result["captures"]) == 4
    assert not result["failures"]


def test_radio_distinct_elements_with_same_image_are_not_a_media_transition(
    tmp_path, browser
):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    html = re.sub(r"rgb\(\d+,100,100\)", "rgb(0,100,100)", radio_html())
    result = capture_switchers(browser, html, tmp_path, [], (375,))
    assert not result["captures"]
    assert {f["reason"] for f in result["failures"]} == {"media_did_not_change"}


def test_skipped_forms_do_not_consume_switcher_budget(tmp_path, browser):
    from lumen_agent.tools.web_interaction_capture import capture_switchers

    forms = "".join(
        f'<form><div data-fragment-id="form_{i}" data-node-id="form_{i}">'
        f'<input type="radio" name="form_{i}"><input type="radio" name="form_{i}">'
        "<img><img></div></form>"
        for i in range(2)
    )
    result = capture_switchers(
        browser, radio_html().replace("<body>", "<body>" + forms), tmp_path, [], (375,)
    )
    assert len(result["captures"]) == 4
    assert [r["reason"] for r in result["omitted"]] == ["form_controls_not_probed"] * 2


def test_failure_and_observation_metadata_survive_review_cache_and_finalization(
    tmp_path,
):
    from test_web_substrate import (
        _bare_tools,
        _review_report,
        _seed_page_capture,
        _seed_state_capture,
    )
    from lumen_agent.tools import web_substrate as ws

    tools = _bare_tools(tmp_path)
    for width in ws._PREVIEW_WIDTHS:
        _seed_page_capture(tmp_path, tools, width, (width, 300))
    _seed_state_capture(tmp_path, tools)
    tools._state_captures[0].update(
        {"keyboard": {"status": "observed"}, "source_mapping": "unverified"}
    )
    failures = [{"node_id": "broken", "reason": "selection_not_observed", "width": 375}]
    tools._state_capture_failures = failures
    tools._state_capture_limits = {
        "page_id": tools.page_id,
        "version": tools._doc_version,
        "failures": failures,
    }
    tools._preview_media_ready = True
    report = _review_report(tools)
    assert report["states"]["0"]["keyboard"]["status"] == "observed"
    assert report["states"]["0"]["source_mapping"] == "unverified"
    assert "review.state_capture_incomplete" in {g["code"] for g in report["gaps"]}
    cached = json.loads(tools.render_web_preview())
    assert cached["unchanged"]
    assert cached["state_capture_failures"] == failures
    saved = json.loads(tools.finalize_web_run("completed_with_warnings", "Draft saved"))
    assert saved["review_evidence"]["state_capture_limits"]["failures"] == failures
    tools._doc_version += 1
    assert _review_report(tools)["state_capture_limits"] == {}
