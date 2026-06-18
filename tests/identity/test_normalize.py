"""M2.1 — the deterministic normalizers (pure, no DB).

These functions are the bedrock of deterministic-first resolution: both sides of every strong-key
comparison fold through them, so they must be stable and total. Each is unit-tested directly.
"""

from __future__ import annotations

import pytest

from clue_research.identity.normalize import (
    canonical_registry_id,
    name_key,
    normalize_name,
    registrable_domain,
    strip_legal_suffix,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Açme, Inc.", "acme inc"),
        ("  International   Business  Machines ", "international business machines"),
        ("I.B.M.", "i b m"),
        ("Café & Co", "cafe co"),
        ("", ""),
        ("   ", ""),
        ("北京", ""),  # non-latin folds away to empty (no fabricated key)
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme Inc", "acme"),
        ("Acme Co Ltd", "acme"),
        ("International Business Machines Corp", "international business machines"),
        ("Group", "group"),  # never strip the last remaining token
        ("Holdings Group", "holdings"),
    ],
)
def test_name_key_strips_legal_suffix(raw: str, expected: str) -> None:
    assert name_key(raw) == expected


def test_strip_legal_suffix_is_idempotent_on_normalized() -> None:
    assert strip_legal_suffix("acme") == "acme"
    assert strip_legal_suffix("acme inc llc") == "acme"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Acme.com/about?x=1", "acme.com"),
        ("ACME.COM", "acme.com"),
        ("http://user:pw@sub.acme.com:8080/path", "sub.acme.com"),
        ("www.example.co.uk", "example.co.uk"),
        ("acme", None),  # bare word, no dot → not a domain
        ("", None),
        ("a sentence with spaces.com is not a host", None),
    ],
)
def test_registrable_domain(raw: str, expected: str | None) -> None:
    assert registrable_domain(raw) == expected


@pytest.mark.parametrize(
    ("ns", "value", "expected"),
    [
        ("duns", "12-345 6789", ("DUNS", "123456789")),
        ("DUNS", "123456789", ("DUNS", "123456789")),
        ("lei", "5493 0012 ZZ", ("LEI", "54930012ZZ")),
        ("npi", "", ("NPI", "")),
    ],
)
def test_canonical_registry_id(ns: str, value: str, expected: tuple[str, str]) -> None:
    assert canonical_registry_id(ns, value) == expected


def test_ibm_variants_fold_to_one_name_key_except_dotted_acronym() -> None:
    """The non-dotted IBM variants share a name-key; the dotted acronym does not (that is M2.2's
    fuzzy job, not deterministic exact matching — documented boundary)."""
    assert name_key("IBM") == name_key("ibm") == "ibm"
    assert name_key("International Business Machines Corp.") == "international business machines"
    # "I.B.M." folds to "i b m" — deliberately NOT equal to "ibm" at the deterministic layer.
    assert name_key("I.B.M.") == "i b m"
