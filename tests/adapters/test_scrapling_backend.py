"""PB-B2.4: the scrapling HTML→markdown backend + the CLUE_SCRAPE_BACKEND selection (DB-free).

Mirrors ``test_firecrawl_backend.py``: the live fetcher is lazy-built; here the scrape *logic*
(fetch page → HTML → markdown → :class:`RawArtifact`) runs against a duck-typed fake. Selection
tests prove the backend swap is settings alone — the M4.5 seam's promise, now a config knob.
"""

from __future__ import annotations

import pytest

from clue_config import Settings
from clue_core import AdaptContext
from clue_research.adapters import (
    FetchError,
    FirecrawlScrapeBackend,
    ScrapeBackend,
    ScraplingScrapeBackend,
    default_scrape_backend,
)

_HTML = "<html><body><h1>Acme</h1><p>We ship reusable rockets.</p></body></html>"


class _Page:
    def __init__(self, status: int = 200, html: str | None = _HTML) -> None:
        self.status = status
        self.html_content = html


class _Fetcher:
    def __init__(self, page: _Page) -> None:
        self._page = page
        self.calls: list[str] = []

    def get(self, ref: str, *, stealthy_headers: bool = True) -> _Page:
        self.calls.append(ref)
        return self._page


class _RaisingFetcher:
    def get(self, ref: str, *, stealthy_headers: bool = True) -> _Page:
        raise ConnectionError("boom")


def _ctx() -> AdaptContext:
    return AdaptContext(source_key="firecrawl_site")


def test_scrape_maps_html_to_markdown_artifact() -> None:
    fetcher = _Fetcher(_Page())
    art = ScraplingScrapeBackend(fetcher=fetcher).scrape("https://acme.example", _ctx())
    assert fetcher.calls == ["https://acme.example"]
    assert art.media_type == "text/markdown"
    assert art.metadata == {"backend": "scrapling"}
    text = art.text()
    assert "Acme" in text and "reusable rockets" in text
    assert "<h1>" not in text  # normalized, not raw HTML


def test_http_error_status_fails_loud() -> None:
    backend = ScraplingScrapeBackend(fetcher=_Fetcher(_Page(status=404)))
    with pytest.raises(FetchError, match="HTTP 404"):
        backend.scrape("https://acme.example/missing", _ctx())


def test_empty_html_fails_loud() -> None:
    backend = ScraplingScrapeBackend(fetcher=_Fetcher(_Page(html="   ")))
    with pytest.raises(FetchError, match="no HTML"):
        backend.scrape("https://acme.example", _ctx())


def test_transport_failure_is_a_typed_fetch_error() -> None:
    with pytest.raises(FetchError, match="scrapling scrape"):
        ScraplingScrapeBackend(fetcher=_RaisingFetcher()).scrape("https://acme.example", _ctx())


# --- selection: the backend swap is settings alone (PB-B2.4) ------------------


def test_default_selection_is_firecrawl() -> None:
    backend = default_scrape_backend(Settings(_env_file=None))
    assert isinstance(backend, FirecrawlScrapeBackend)


def test_scrapling_selected_by_setting() -> None:
    backend = default_scrape_backend(Settings(_env_file=None, scrape_backend="scrapling"))
    assert isinstance(backend, ScraplingScrapeBackend)


def test_env_var_drives_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SCRAPE_BACKEND", "scrapling")
    assert isinstance(default_scrape_backend(), ScraplingScrapeBackend)


def test_both_backends_satisfy_the_seam() -> None:
    assert isinstance(ScraplingScrapeBackend(), ScrapeBackend)
    assert isinstance(FirecrawlScrapeBackend(), ScrapeBackend)
