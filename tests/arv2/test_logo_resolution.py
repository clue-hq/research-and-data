"""The mark-type logo rule (founder rulings 2026-09-11): keep only LinkedIn company marks from
Websets; build Brandfetch's Logo API URL (embed-only, never fetched) from the domain.

Fixture URLs are the shapes the proof of concept measured over the first Insight Health run.
"""

from __future__ import annotations

import pytest

from clue_api.arv2.logo_resolution import brandfetch_logo_url, is_linkedin_mark, websets_mark_url

MARK = "https://media.licdn.com/dms/image/v2/C4E0BAQFVxTYC/company-logo_200_200/0?e=2147483647"


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        (MARK, True),
        ("https://www.inova.org/themes/custom/inova_public/img/inova-opengraph.jpg", False),
        ("https://www.southern-ortho.com/wp-content/uploads/2024/08/s-o-team.jpg", False),
        ("https://static.licdn.com/aero-v1/sc/h/cs8pjfgyw96g44ln9r7tct85f", False),
        ("http://media.licdn.com/dms/image/company-logo_200_200/0", False),
        (None, False),
        ("", False),
    ],
)
def test_only_a_linkedin_company_mark_is_kept_from_websets(url: str | None, kept: bool) -> None:
    assert is_linkedin_mark(url) is kept
    assert websets_mark_url(url) == (url if kept else None)


def test_the_brandfetch_url_is_the_logo_apis_icon_with_a_lettermark_fallback() -> None:
    url = brandfetch_logo_url("Inova.org", client_id="abc123")
    assert url == (
        "https://cdn.brandfetch.io/domain/inova.org/w/128/h/128/fallback/lettermark/type/icon"
        "?c=abc123"
    )
    # No client id, no URL — the screens show their own placeholder instead.
    assert brandfetch_logo_url("inova.org", client_id="") is None
    assert brandfetch_logo_url("", client_id="abc123") is None
