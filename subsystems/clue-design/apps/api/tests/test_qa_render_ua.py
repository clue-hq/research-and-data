"""The QA renderers' User-Agent override — the flag, the helper, and both call sites.

Brandfetch's logo CDN refuses a User-Agent containing `HeadlessChrome`, so a hotlinked
decorative logo renders empty in the page thumbnail and in the clone-review walk. The
founder decided (2026-09-02, plan D11) that those two renderers present a normal Chrome
User-Agent, behind a flag that defaults on. What is pinned here is that the documented env
line actually loads, that the helper is read at call time, and that both renderers really
pass the kwarg through to `new_context` — a helper nobody calls would prove nothing.

No chromium is launched: both renderers are driven against fakes that record what
`new_context` was asked for.
"""

from __future__ import annotations

import pytest
from lumen_api import document_thumbnails as thumbs
from lumen_api.clone_review import WalkPlan
from lumen_api.clone_review.browser import run_walk
from lumen_api.qa_render_ua import QA_RENDER_USER_AGENT, qa_render_context_kwargs
from test_clone_review_gate import _factory, _FakeBrowser

# --- the flag ------------------------------------------------------------------------------


def test_the_flag_defaults_on(monkeypatch):
    from py_lumen_config.config import Settings

    monkeypatch.delenv("LUMEN_QA_RENDER_UA_OVERRIDE", raising=False)
    assert Settings(_env_file=None).lumen_qa_render_ua_override is True


def test_the_documented_env_line_turns_the_flag_off(monkeypatch):
    # The parity rule: the line written in .env.example must be loadable as written.
    from py_lumen_config.config import Settings

    monkeypatch.setenv("LUMEN_QA_RENDER_UA_OVERRIDE", "0")
    assert Settings(_env_file=None).lumen_qa_render_ua_override is False


# --- the helper ----------------------------------------------------------------------------


def _set_flag(monkeypatch, value: bool) -> None:
    import py_lumen_config

    monkeypatch.setattr(py_lumen_config.settings, "lumen_qa_render_ua_override", value)


def test_the_helper_offers_the_override_ua_when_the_flag_is_on(monkeypatch):
    _set_flag(monkeypatch, True)
    assert qa_render_context_kwargs() == {"user_agent": QA_RENDER_USER_AGENT}


def test_the_helper_offers_nothing_when_the_flag_is_off(monkeypatch):
    _set_flag(monkeypatch, False)
    assert qa_render_context_kwargs() == {}


def test_the_override_ua_does_not_announce_a_headless_browser():
    # The whole point: `HeadlessChrome` is the substring the CDN refuses on.
    assert "HeadlessChrome" not in QA_RENDER_USER_AGENT


# --- call site 1: the page thumbnail --------------------------------------------------------


class _RecordingPage:
    def set_content(self, html: str, wait_until: str = "load") -> None:
        pass

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def screenshot(self, *, type: str = "png") -> bytes:
        return b"png"


class _RecordingContext:
    def new_page(self) -> _RecordingPage:
        return _RecordingPage()

    def close(self) -> None:
        pass


class _RecordingBrowser:
    def __init__(self) -> None:
        self.context_kwargs: list[dict] = []

    def new_context(self, **kwargs) -> _RecordingContext:
        self.context_kwargs.append(kwargs)
        return _RecordingContext()

    def close(self) -> None:
        pass


class _RecordingPlaywright:
    def __init__(self, browser: _RecordingBrowser) -> None:
        self.chromium = self
        self._browser = browser

    def launch(self, headless: bool = True) -> _RecordingBrowser:
        return self._browser

    def __enter__(self) -> _RecordingPlaywright:
        return self

    def __exit__(self, *_exc) -> None:
        return None


def _capture_thumbnail(monkeypatch) -> _RecordingBrowser:
    # Patched on `playwright.sync_api` itself, the way the thumbnail suite's failure test
    # does it: the generator imports the name at call time.
    import playwright.sync_api

    browser = _RecordingBrowser()
    monkeypatch.setattr(thumbs, "resolve_tailwind_runtime", lambda: b"x")
    monkeypatch.setattr(
        playwright.sync_api, "sync_playwright", lambda: _RecordingPlaywright(browser)
    )
    assert thumbs.web_thumbnail_png("<html><body></body></html>") == b"png"
    return browser


def test_the_thumbnail_presents_the_override_ua_when_the_flag_is_on(monkeypatch):
    _set_flag(monkeypatch, True)
    browser = _capture_thumbnail(monkeypatch)
    assert browser.context_kwargs[0]["user_agent"] == QA_RENDER_USER_AGENT


def test_the_thumbnail_presents_no_ua_when_the_flag_is_off(monkeypatch):
    _set_flag(monkeypatch, False)
    browser = _capture_thumbnail(monkeypatch)
    assert "user_agent" not in browser.context_kwargs[0]


# --- call site 2: the clone-review walk -----------------------------------------------------


def _capture_walk(tmp_path) -> _FakeBrowser:
    browser = _FakeBrowser()
    run_walk(
        "<html></html>",
        WalkPlan(sections=()),
        output_dir=tmp_path,
        browser_factory=_factory(browser),
    )
    return browser


def test_the_walk_presents_the_override_ua_when_the_flag_is_on(monkeypatch, tmp_path):
    _set_flag(monkeypatch, True)
    browser = _capture_walk(tmp_path)
    # Every pass opens its own context, so every pass must carry it.
    assert browser.context_kwargs, "the walk opened no context"
    for kwargs in browser.context_kwargs:
        assert kwargs["user_agent"] == QA_RENDER_USER_AGENT


def test_the_walk_presents_no_ua_when_the_flag_is_off(monkeypatch, tmp_path):
    _set_flag(monkeypatch, False)
    browser = _capture_walk(tmp_path)
    assert browser.context_kwargs, "the walk opened no context"
    for kwargs in browser.context_kwargs:
        assert "user_agent" not in kwargs


if __name__ == "__main__":  # pragma: no cover - convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
