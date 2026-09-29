from __future__ import annotations

import pytest

from clue_spine.hostnames import (
    HostnameRefused,
    registrable_domain,
    validate_custom_hostname,
    validate_label,
)

SUFFIX = "pages.cluehq.ai"


@pytest.mark.parametrize(
    ("hostname", "registrable"),
    [
        ("go.acme.com", "acme.com"),
        ("acme.co.uk", "acme.co.uk"),
        ("go.acme.co.uk", "acme.co.uk"),
        ("a.b.c.example", "c.example"),  # unknown suffix: last two labels
        ("acme.pages.cluehq.ai", "cluehq.ai"),
    ],
)
def test_registrable_domain(hostname: str, registrable: str) -> None:
    assert registrable_domain(hostname) == registrable


@pytest.mark.parametrize(
    "ok",
    [
        "go.acme.com",
        "Go.Acme.COM.",
        "go.acme.co.uk",
        "pages.bücher.example",
        "a" * 63 + ".acme.com",
    ],
)
def test_accepted_hostnames_are_normalised(ok: str) -> None:
    result = validate_custom_hostname(ok, system_suffix=SUFFIX)
    assert result == result.lower() and not result.endswith(".")


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("", "hostname_invalid"),
        ("go acme.com", "hostname_invalid"),
        ("-go.acme.com", "hostname_invalid"),
        ("a" * 64 + ".acme.com", "hostname_invalid"),
        ("acme.com", "hostname_is_apex"),
        ("acme.co.uk", "hostname_is_apex"),
        ("x.cluehq.ai", "hostname_reserved"),
        ("cluehq.ai", "hostname_reserved"),
        ("go.pages.cluehq.ai", "hostname_reserved"),
    ],
)
def test_refusals_in_spec_order(bad: str, code: str) -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname(bad, system_suffix=SUFFIX)
    assert caught.value.code == code
    assert caught.value.message


def test_apex_message_names_a_subdomain_example() -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname("acme.com", system_suffix=SUFFIX)
    assert "go.acme.com" in caught.value.message


@pytest.mark.parametrize("label", ["acme", "acme-hq", "a1b"])
def test_valid_labels(label: str) -> None:
    assert validate_label(label) == label


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("ab", "label_invalid"),
        ("-acme", "label_invalid"),
        ("Acme", "label_invalid"),
        ("a" * 41, "label_invalid"),
        ("www", "label_reserved"),
    ],
)
def test_invalid_labels(label: str, code: str) -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_label(label)
    assert caught.value.code == code
