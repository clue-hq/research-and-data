"""Short links in post text are opened to the address they lead to (review I8).

Pages in each site's real shape (checked live 2026-11-11, addresses made up): t.co answers a
browser with a page whose refresh tag holds the address; lnkd.in answers with a "leaving LinkedIn"
page for an outside address, and with a 301 whose location is the address for a LinkedIn one. The
opener reads the address and never fetches it; a link that cannot be opened for any reason is left
as written and counted; nothing is recorded as spend or evidence.
"""

from __future__ import annotations

from clue_api.footprint import short_links
from clue_api.footprint.short_links import expand
from clue_spend.transport import HttpResponse, ScriptedTransport, TransportFailure
from tests.footprint._pages import lnkd_page, tco_page


def opened(*responses):
    transport = ScriptedTransport(list(responses))
    return transport, (lambda links: expand(links, transport=transport, workers=1))


def test_finds_short_links_in_text():
    text = "Read it: https://t.co/AbC123xyz and https://lnkd.in/g-D9_RTgPj, or example.com"
    assert short_links.short_links(text) == [
        "https://t.co/AbC123xyz",
        "https://lnkd.in/g-D9_RTgPj",
    ]
    assert short_links.short_links(None) == []


def test_opens_tco_and_lnkd_pages():
    transport, run = opened(
        lnkd_page("https://example.com/events/blitz/?a=1&amp;b=2"),
        tco_page("https://example.org/infinite"),
    )
    found = run(["https://t.co/AbC", "https://lnkd.in/gXy", "https://t.co/AbC"])
    assert found.addresses == {
        "https://lnkd.in/gXy": "https://example.com/events/blitz/?a=1&b=2",
        "https://t.co/AbC": "https://example.org/infinite",
    }
    assert found.failed == 0 and len(transport.requests) == 2  # each link opened once
    assert "Mozilla" in transport.requests[0].headers["User-Agent"]


def test_a_redirect_is_read_not_followed():
    linkedin = "https://www.linkedin.com/feed/update/urn:li:share:1"
    transport, run = opened(HttpResponse(301, {"location": linkedin}, b""))
    found = run(["https://lnkd.in/gIn"])
    assert found.addresses == {"https://lnkd.in/gIn": linkedin}
    assert len(transport.requests) == 1  # the address itself is never fetched


def test_a_link_that_does_not_open_is_left_as_written_and_counted():
    transport, run = opened(
        HttpResponse(404, {}, b"not found"),
        HttpResponse(200, {}, b"<html>no address here</html>"),
        TransportFailure("reset"),
        HttpResponse(301, {"location": "javascript:alert(1)"}, b""),
    )
    found = run(["https://t.co/a", "https://t.co/b", "https://t.co/c", "https://t.co/d"])
    assert found.addresses == {} and found.failed == 4


def test_any_error_opening_a_link_never_escapes():
    class Exploding:
        def send(self, request):
            raise ValueError("redirect ceiling exceeded")  # or a refused private address

    found = expand(["https://t.co/x"], transport=Exploding(), workers=1)
    assert found.addresses == {} and found.failed == 1


def test_nothing_to_open():
    transport, run = opened()
    found = run([])
    assert found.addresses == {} and found.failed == 0 and transport.requests == []


def test_the_default_transport_refuses_private_addresses_and_redirects():
    from clue_api.footprint.media_resolution import PublicMediaTransport

    transport = short_links.default_transport()
    assert isinstance(transport, PublicMediaTransport) and transport.follow_redirects is False


def test_a_reader_counts_unopened_links_and_records_no_spend(monkeypatch):
    from tests.footprint.test_social import TOKEN, timeline, tweet, wire

    links = ScriptedTransport([tco_page("https://a.example/1"), HttpResponse(404, {}, b"")])
    monkeypatch.setattr(short_links, "TRANSPORT", lambda: links)
    monkeypatch.setattr(short_links, "WORKERS", 1)
    caller, _ = wire(timeline(tweet("5", "See https://t.co/One and https://t.co/Two")))
    from clue_api.footprint.social import x_posts

    history = x_posts(caller, TOKEN, "ada")
    assert history.posts[0].links == {"https://t.co/One": "https://a.example/1"}
    assert history.gaps == ["1 of 2 short link(s) could not be opened; they are left as written"]
    assert not [row for row in caller._ledger.rows if row.provider == "short_link"]
