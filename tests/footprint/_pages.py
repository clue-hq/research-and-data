"""Short-link pages in each site's real shape (addresses made up)."""

from __future__ import annotations

from clue_spend.transport import HttpResponse


def tco_page(address):
    return HttpResponse(
        200,
        {"content-type": "text/html"},
        (
            f'<head><noscript><META http-equiv="refresh" content="0;URL={address}"></noscript>'
            f"<title>{address}</title></head><script>location.replace(...)</script>"
        ).encode(),
    )


def lnkd_page(address):
    return HttpResponse(
        200,
        {"content-type": "text/html"},
        (
            "<html><body><h1>This link will take you to a page that's not on LinkedIn</h1>"
            '<a class="artdeco-button" data-tracking-control-name="external_url_click" '
            f'data-tracking-will-navigate href="{address}">{address}</a></body></html>'
        ).encode(),
    )
