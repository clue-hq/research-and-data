"""Offline native author -> repair -> artifact -> repeated pin regression.

Only registry custody is in memory. The author, helper, sanitizer, CSS compiler,
artifact builder, package admission and browser runtime are production paths.
"""
import json

from playwright.sync_api import sync_playwright

from test_web_recreate_and_repair import FakeRegistry, PROOF_ID, _tools
from lumen_api.agent_cloned_sections import detect_slots
from lumen_api.fragments import build_fragment_artifact
from lumen_api.fragments.cssscope import PRELUDE_REFERENCE_STRIP
from lumen_api.fragments.sanitize import sanitize_fragment_html


class ArtifactRegistry(FakeRegistry):
    def mint_repair(self, *, native_dependencies=None, **kwargs):
        result = super().mint_repair(**kwargs)
        sanitized = sanitize_fragment_html(kwargs["html"], rehosted={})
        specs = list(detect_slots(sanitized.html).specs)
        # Keep the pre-fix red at the missing behavior, not an unknown keyword.
        dependencies = (
            {"native_dependencies": native_dependencies} if native_dependencies else {}
        )
        artifact = build_fragment_artifact(
            html=sanitized.html, css=kwargs["css"], rehosted={}, slots=specs,
            prelude_reference=PRELUDE_REFERENCE_STRIP,
            source_fragment_id=kwargs["replaces"], **dependencies,
        )
        self.artifact = artifact
        self.add(
            artifact.fragment_id, role="features", label="Native repair fixture", index=0,
            status="draft", derived_from=kwargs["replaces"],
            slots=[{"key": s.key, "kind": s.kind} for s in specs],
        )
        self.rows[artifact.fragment_id].update(
            html=artifact.payload["html"], css=artifact.payload["css"], **dependencies,
        )
        return result | {"fragment_id": artifact.fragment_id,
                         "slot_keys": [s.key for s in specs]}

    def resolve_insertable(self, fragment_id):
        result = super().resolve_insertable(fragment_id)
        if dependencies := self.rows[fragment_id].get("native_dependencies"):
            result["render"]["native_dependencies"] = dependencies
        return result


def _fixture(tmp_path, html=None):
    registry = ArtifactRegistry(tmp_path)
    registry.add(PROOF_ID, role="features", label="Missing controller", index=0,
                 degraded=True, degraded_reason="dead_height")
    authored = _tools(tmp_path / "author", registry)
    assert json.loads(authored.insert_cloned_section(PROOF_ID))["status"] == "ok"
    items = "".join(f'<div id="item_{i}"><p>Choice {i}</p><p>Panel {i}</p></div>'
                    for i in range(4))
    result = json.loads(authored.repair_cloned_section(
        PROOF_ID, html or ('<section id="repaired"><div id="switcher" '
                          'data-component="tabs">' + items + '</div></section>'),
        2, "Offline regression fixture",
    ))
    return registry, authored, result


def _render(tools):
    return tools.core.web_render(
        tools.web_doc, tools.page_id, mode="delivery",
        fragments=tools._fragment_render_map(), fragment_css=tools._fragment_css(),
    )["html"]


def test_repaired_tabs_keep_styles_and_independent_keyboard_behavior(tmp_path):
    registry, authored, result = _fixture(tmp_path)
    assert result["status"] == "ok", result
    fid = result["repair_fragment_id"]
    release = json.loads(authored.release_repair(fid))
    assert release["status"] == "ok", release
    pinned = _tools(tmp_path / "pin", registry)
    # A typed sibling uses the original IDs. The two saved instances must not
    # bind its panels, or each other's, even when all three share a controller.
    assert json.loads(pinned.author_web_page(
        '<section id="sibling"><div id="switcher" data-component="tabs">'
        '<div id="item_0"><p>Choice 0</p><p>Sibling 0</p></div>'
        '<div id="item_1"><p>Choice 1</p><p>Sibling 1</p></div></div></section>',
        custom_css='.lumen-tab {padding:0; border-radius:0}',
    ))["status"] == "ok"
    for _ in range(2):
        assert json.loads(pinned.insert_cloned_section(fid))["status"] == "ok"
    original_payload = registry.artifact.payload_bytes
    html = _render(pinned)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 600})
            page.emulate_media(reduced_motion="reduce")
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="domcontentloaded")
            groups = page.locator(".lumen-tabs")
            assert groups.count() == 3
            assert groups.nth(0).locator('[role="tablist"]').evaluate(
                "e => getComputedStyle(e).display"
            ) == "flex"
            second = groups.nth(2)
            for i in range(4):
                second.get_by_role("tab").nth(i).click()
                assert second.get_by_role("tabpanel").inner_text() == f"Panel {i}"
                assert groups.nth(1).get_by_role("tabpanel").inner_text() == "Panel 0"
                assert groups.nth(0).get_by_role("tabpanel").inner_text() == "Sibling 0"
            second.get_by_role("tab").nth(1).click()
            assert second.get_by_role("tabpanel").inner_text() == "Panel 1"
            assert groups.nth(1).get_by_role("tabpanel").inner_text() == "Panel 0"
            assert groups.nth(0).get_by_role("tabpanel").inner_text() == "Sibling 0"
            second.get_by_role("tab").nth(1).press("ArrowRight")
            assert second.get_by_role("tabpanel").inner_text() == "Panel 2"
            assert groups.nth(1).get_by_role("tabpanel").inner_text() == "Panel 0"
            assert groups.nth(0).get_by_role("tabpanel").inner_text() == "Sibling 0"
            assert page.get_by_role("tab").evaluate_all(
                "els => els.every(e => getComputedStyle(e).paddingTop === '0px' && getComputedStyle(e).borderRadius === '0px')"
            )
            ids = page.locator('[role="tab"], [role="tabpanel"]').evaluate_all(
                "els => els.map(e => e.id)"
            )
            assert len(ids) == len(set(ids))
        finally:
            browser.close()
    assert registry.artifact.payload_bytes == original_payload


def test_pinned_native_tabs_are_in_the_interaction_capture(tmp_path):
    registry, authored, result = _fixture(tmp_path)
    assert result["status"] == "ok", result
    fid = result["repair_fragment_id"]
    assert json.loads(authored.release_repair(fid))["status"] == "ok"
    pinned = _tools(tmp_path / "capture", registry)
    assert json.loads(pinned.insert_cloned_section(fid))["status"] == "ok"
    html = pinned.core.web_render(
        pinned.web_doc, pinned.page_id, mode="editor",
        fragments=pinned._fragment_render_map(), fragment_css=pinned._fragment_css(),
    )["html"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser.on("page", lambda page: page.route("**/*", lambda route: route.abort()))
        try:
            pinned._capture_states(browser, html, tmp_path)
            assert not pinned._state_capture_failures, pinned._state_capture_failures
            captures = [c for c in pinned._state_captures if c["kind"] == "tab-selected"]
            assert len(captures) == 8  # four panels on desktop and phone
            assert all(c.get("root_id") and c["keyboard"]["status"] == "observed" for c in captures)
        finally:
            browser.close()


def test_unsupported_native_repair_is_not_minted_as_preserved(tmp_path):
    registry, authored, result = _fixture(
        tmp_path,
        '<section id="repaired"><div id="rotator" data-component="carousel">'
        '<p>One</p><p>Two</p></div></section>',
    )
    assert result["status"] == "error", result
    assert result["error_code"] == "fragment.native_dependency_unsupported"
    assert not registry.mint_calls
    assert "lumen-carousel" in _render(authored)  # accepted typed section survives


def test_nested_native_tabs_keep_selection_owned_by_each_root(tmp_path):
    registry, authored, result = _fixture(tmp_path,
        '<section id="repaired"><div id="outer" data-component="tabs">'
        '<div id="one"><p>One</p><div id="inner" data-component="tabs">'
        '<div id="inner_a"><p>A</p><p>Panel A</p></div>'
        '<div id="inner_b"><p>B</p><p>Panel B</p></div></div></div>'
        '<div id="two"><p>Two</p><p>Second outer panel</p></div></div></section>')
    assert result["status"] == "ok", result
    fid = result["repair_fragment_id"]
    assert json.loads(authored.release_repair(fid))["status"] == "ok"
    reused = _tools(tmp_path / "nested", registry)
    assert json.loads(reused.insert_cloned_section(fid))["status"] == "ok"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(_render(reused), wait_until="domcontentloaded")
            page.get_by_role("tab", name="B", exact=True).click()
            assert page.get_by_text("Panel B", exact=True).is_visible()
            assert page.get_by_role("tab", name="One", exact=True).get_attribute("aria-selected") == "true"
            page.get_by_role("tab", name="Two", exact=True).click()
            assert page.get_by_text("Second outer panel", exact=True).is_visible()
            page.get_by_role("tab", name="One", exact=True).click()
            assert page.get_by_text("Panel B", exact=True).is_visible()
        finally:
            browser.close()


def test_unowned_controls_stay_inert_beside_a_native_repair(tmp_path):
    registry, authored, result = _fixture(tmp_path)
    assert result["status"] == "ok", result
    fid = result["repair_fragment_id"]
    assert json.loads(authored.release_repair(fid))["status"] == "ok"
    reused = _tools(tmp_path / "inert", registry)
    assert json.loads(reused.insert_cloned_section(fid))["status"] == "ok"
    foreign = build_fragment_artifact(html=(
        '<div class="lumen-tabs" id="foreign"><div class="lumen-tabs-list" role="tablist">'
        '<button class="lumen-tab" id="f0" role="tab" aria-controls="fp0" aria-selected="true">F0</button>'
        '<button class="lumen-tab" id="f1" role="tab" aria-controls="fp1" aria-selected="false">F1</button>'
        '</div><div role="tabpanel" id="fp0">Foreign zero</div><div role="tabpanel" id="fp1" hidden>Foreign one</div></div>'
        '<div class="lumen-marquee"><div class="lumen-marquee-track">Static</div></div>'
        '<button commandfor="foreign-dialog" command="show-modal">Foreign dialog</button>'
        '<dialog id="foreign-dialog">Foreign content</dialog>'
    ), css="", rehosted={})
    registry.add(foreign.fragment_id, role="features", label="Captured controls", index=1)
    registry.rows[foreign.fragment_id].update(html=foreign.payload["html"], css=foreign.payload["css"])
    assert json.loads(reused.insert_cloned_section(foreign.fragment_id))["status"] == "ok"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            # Exercise the approved fallback path, also on Chromium versions
            # with native invokers. Prevent native default after our listener.
            page.evaluate("delete HTMLButtonElement.prototype.command")
            page.set_content(_render(reused), wait_until="domcontentloaded")
            page.evaluate("document.addEventListener('click', e => e.preventDefault())")
            page.get_by_role("tab", name="F1", exact=True).click()
            assert page.locator('#f1').get_attribute("aria-selected") == "false"
            assert page.locator('#fp1').evaluate("e => e.hidden")
            assert page.locator('#foreign [role=tablist]').evaluate("e => getComputedStyle(e).display") == "block"
            assert page.locator('.lumen-marquee-track').evaluate("e => getComputedStyle(e).animationName") == "none"
            page.get_by_role("button", name="Foreign dialog", exact=True).click()
            assert not page.locator('#foreign-dialog').evaluate("e => e.open")
        finally:
            browser.close()
