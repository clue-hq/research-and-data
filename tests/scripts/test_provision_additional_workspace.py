"""The operator link opens the setting-up screen for exactly the new workspace."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from scripts.provision_additional_workspace import operator_setup_url


def test_link_names_the_workspace_and_the_website() -> None:
    url = operator_setup_url(
        "https://app.cluehq.ai/", "ws_0123abcd", "https://acme.example/?ref=x&y=1"
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://app.cluehq.ai/onboarding/setting-up"
    )
    assert parse_qs(parts.query) == {
        "workspace": ["ws_0123abcd"],
        "website": ["https://acme.example/?ref=x&y=1"],
    }
