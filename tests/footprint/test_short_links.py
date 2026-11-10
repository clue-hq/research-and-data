"""Short links in post text are opened to the address they lead to (pages in each site's real
shape, addresses made up)."""

from __future__ import annotations

from clue_api.footprint.short_links import expand, short_links
from clue_spend.transport import HttpResponse, TransportFailure
from tests.footprint._pages import lnkd_page, tco_page
from tests.footprint.test_social import wire


def test_finds_short_links_in_text():
    text = "Read it: https://t.co/AbC123xyz and https://lnkd.in/g-D9_RTgPj, or example.com"
    assert short_links(text) == ["https://t.co/AbC123xyz", "https://lnkd.in/g-D9_RTgPj"]
    assert short_links(None) == []


def test_opens_tco_and_lnkd_links():
    caller, transport = wire(
        lnkd_page("https://example.com/events/blitz/?a=1&amp;b=2"),
        tco_page("https://example.org/infinite"),
    )
    found = expand(
        caller, ["https://t.co/AbC", "https://lnkd.in/gXy", "https://t.co/AbC"], workers=1
    )
    assert found == {
        "https://lnkd.in/gXy": "https://example.com/events/blitz/?a=1&b=2",
        "https://t.co/AbC": "https://example.org/infinite",
    }
    assert len(transport.requests) == 2  # each link opened once
    assert "Mozilla" in transport.requests[0].headers["User-Agent"]


def test_a_link_that_does_not_open_is_left_out():
    caller, _ = wire(
        HttpResponse(404, {}, b"not found"),
        HttpResponse(200, {}, b"<html>no address here</html>"),
        *[TransportFailure("reset")] * 2,
    )
    found = expand(caller, ["https://t.co/a", "https://t.co/b", "https://t.co/c"], workers=1)
    assert found == {}


def test_nothing_to_open():
    caller, transport = wire()
    assert expand(caller, []) == {} and transport.requests == []
