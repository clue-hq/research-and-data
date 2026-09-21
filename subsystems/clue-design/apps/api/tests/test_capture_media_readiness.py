"""Local browser regressions for pictures taken before offscreen media has loaded."""

import time
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from lumen_api.clone_review.browser import run_walk
from lumen_api.clone_review.walk import walk_plan
from PIL import Image
from playwright.sync_api import sync_playwright


def _html(*, failed=False):
    failure = '<img src="https://capture.test/fail.png" width="60" height="60">' if failed else ""
    return f"""<!doctype html><html><head>
      <script data-lumen-tailwind-runtime></script>
      <style>body{{margin:0}}.spacer{{height:6500px}}</style></head><body>
      <div class="spacer"></div>
      <img loading="lazy" src="https://capture.test/delayed.png" width="100" height="100">
      {failure}<div style="height:1000px"></div></body></html>"""


@pytest.fixture
def local_browser():
    """Intercept every request; these tests never contact a website or provider."""
    data = BytesIO()
    Image.new("RGB", (100, 100), (234, 12, 32)).save(data, format="PNG")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        def route(request):
            if request.request.url.endswith("/delayed.png"):
                time.sleep(0.12)
                request.fulfill(content_type="image/png", body=data.getvalue())
            else:
                request.fulfill(status=404, body="missing")

        class RoutedBrowser:
            def new_context(self, **kwargs):
                context = browser.new_context(**kwargs)
                context.route("**/*", route)
                return context

            def new_page(self, **kwargs):
                return self.new_context(**kwargs).new_page()

        try:
            yield RoutedBrowser()
        finally:
            browser.close()


def test_walk_loads_lower_lazy_images_before_full_page_captures(tmp_path, local_browser):
    @contextmanager
    def factory():
        yield local_browser

    walk = run_walk(_html(), walk_plan(), output_dir=tmp_path, browser_factory=factory)
    for name in ("full_page", "mobile", "reduced_motion"):
        shot = walk.by_class(name).shots[0]
        with Image.open(shot.path) as image:
            assert image.convert("RGB").getpixel((40, 6540)) == (234, 12, 32), name


def test_failed_image_is_reported_instead_of_certified_ready(tmp_path, local_browser):
    @contextmanager
    def factory():
        yield local_browser

    walk = run_walk(_html(failed=True), walk_plan(), output_dir=tmp_path, browser_factory=factory)
    report = walk.by_class("mobile").notes.get("media_readiness", {})
    assert walk.by_class("reduced_motion").notes["heights_settled"] is False
    assert report.get("settled") is False
    assert any(item["reason"] == "load_failed" for item in report["unresolved"])


def test_media_warmup_restores_scroll_without_changing_loading_or_motion(local_browser):
    from lumen_api.capture_readiness import prepare_capture_media

    page = local_browser.new_page(viewport={"width": 375, "height": 812}, reduced_motion="reduce")
    page.set_content(_html())
    page.evaluate("scrollTo(0, 300)")
    result = prepare_capture_media(page)
    assert result["settled"] is True
    assert result["scroll_restored"] is True
    assert page.evaluate("scrollY") == 300
    assert page.locator("img").get_attribute("loading") == "lazy"
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
    page.context.close()


def test_incomplete_scroll_coverage_is_reported_under_a_fixed_budget(local_browser):
    from lumen_api.capture_readiness import prepare_capture_media

    page = local_browser.new_page(viewport={"width": 375, "height": 812})
    page.set_content(_html())
    start = time.monotonic()
    result = prepare_capture_media(page, timeout_ms=100, max_steps=1)
    assert time.monotonic() - start < 1
    assert result["settled"] is False
    assert result["coverage_complete"] is False
    assert result["scroll_restored"] is True
    assert any(item["reason"] == "loading" for item in result["unresolved"])
    page.context.close()


@pytest.mark.parametrize("failed", [False, True])
def test_agent_preview_uses_media_readiness_at_each_width(tmp_path, local_browser, failed):
    from lumen_agent.tools.web_substrate import LumenWebTools

    # The browser remains real. Only the unrelated core/agent construction and
    # interactive-state pass are outside this base-preview regression.
    tools = SimpleNamespace(
        _browser_handle=lambda: local_browser,
        _preview_by_width={},
        _capture_states=lambda *args: {},
    )
    diagnostics = []
    paths, error, _ = LumenWebTools._capture_pass(
        tools, _html(failed=failed), tmp_path, diagnostics
    )
    assert error is None
    assert len(paths) == 3
    for path in paths:
        with Image.open(path) as image:
            assert image.convert("RGB").getpixel((40, 6540)) == (234, 12, 32)
    assert tools._preview_media_ready is (not failed)
    assert bool(diagnostics) is failed


@pytest.mark.parametrize("offset", ["left:10000px", "top:10000px"])
def test_clipped_inactive_images_do_not_block_a_visible_capture(local_browser, offset):
    from lumen_api.capture_readiness import prepare_capture_media

    page = local_browser.new_page(viewport={"width": 375, "height": 812})
    page.set_content(f"""<div style="position:relative;overflow:hidden;width:200px;height:200px">
        <img loading="lazy" src="https://capture.test/delayed.png" width="100" height="100"
             style="position:absolute;{offset}"></div>""")
    result = prepare_capture_media(page, timeout_ms=100)
    assert result["settled"] is True
    assert result["images_checked"] == 0
    page.context.close()
