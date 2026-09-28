"""The one rule that names a workspace from its website when nobody typed a company name."""

from __future__ import annotations

import pytest

from clue_core.normalize import canonical_workspace_name


@pytest.mark.parametrize(
    ("website", "expected"),
    [
        ("https://www.acme-health.com/pricing", "Acme Health"),
        ("acme-health.com", "Acme Health"),
        ("http://WWW.Bright_Side.co.uk", "Bright Side"),
        ("shop.example.com.au", "Example"),
        ("https://insighthealth.ai", "Insighthealth"),
        ("https://192.168.1.1/", None),
        ("localhost", None),
        ("", None),
        (None, None),
        ("https://user:pw@www.acme.com", "Acme"),
    ],
)
def test_canonical_workspace_name(website: str | None, expected: str | None) -> None:
    assert canonical_workspace_name(website) == expected
