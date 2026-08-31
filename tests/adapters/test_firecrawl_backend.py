"""M4.3/M4.5: single-page Firecrawl backend logic (DB-free, fake-client driven).

The live Firecrawl client is lazy-built (wired in M4.5); here we unit-test the scrape *logic* — call
the client, map its markdown result to a :class:`RawArtifact` — against a duck-typed fake, mirroring
how the M0.4 gateway tests the OpenRouter client with an injected fake. Both a dict-shaped and an
attribute-shaped result are exercised; a missing-markdown result fails loud.
"""

from __future__ import annotations

import pytest

from clue_core import AdaptContext
from clue_research.adapters import FetchError, FirecrawlScrapeBackend


class _DictClient:
    def __init__(self, markdown: str | None) -> None:
        self._markdown = markdown
        self.calls: list[str] = []

    def scrape(self, ref: str, *, formats: list[str]) -> dict[str, object]:
        self.calls.append(ref)
        assert formats == ["markdown"]
        return {"markdown": self._markdown} if self._markdown is not None else {}


class _AttrResult:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown


class _AttrClient:
    def scrape(self, ref: str, *, formats: list[str]) -> _AttrResult:
        return _AttrResult("# Heading\n\nbody")


def test_declared_firecrawl_sdk_exposes_the_retained_single_page_api() -> None:
    """Catch SDK-major drift without making a network request."""
    from firecrawl import Firecrawl

    client = Firecrawl(api_key="fc-c0-contract-check")

    assert callable(client.scrape)


def _ctx() -> AdaptContext:
    return AdaptContext(source_key="firecrawl_site", auth_ref="CLUE_FIRECRAWL_API_KEY")


def test_scrape_maps_dict_markdown_to_artifact() -> None:
    client = _DictClient("# Acme\n\nWe build data pipelines.")
    backend = FirecrawlScrapeBackend(client=client)
    art = backend.scrape("https://acme.example/about", _ctx())
    assert art.media_type == "text/markdown"
    assert art.text() == "# Acme\n\nWe build data pipelines."
    assert art.metadata["backend"] == "firecrawl"
    assert client.calls == ["https://acme.example/about"]


def test_scrape_maps_attribute_markdown_to_artifact() -> None:
    backend = FirecrawlScrapeBackend(client=_AttrClient())
    art = backend.scrape("https://x.example", _ctx())
    assert art.text() == "# Heading\n\nbody"


def test_scrape_without_markdown_fails_loud() -> None:
    backend = FirecrawlScrapeBackend(client=_DictClient(None))
    with pytest.raises(FetchError, match="no markdown"):
        backend.scrape("https://x.example", _ctx())
