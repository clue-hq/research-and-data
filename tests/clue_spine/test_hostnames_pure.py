"""Custom-domain publishing S1 Task 3: label allocation and hostname helpers (no DB)."""

from __future__ import annotations

from itertools import islice

import pytest

from clue_spine.hostnames import (
    LABEL_MAX,
    LABEL_MIN,
    RESERVED_LABELS,
    allocate_label,
    is_valid_hostname,
    label_candidates,
    normalize_hostname,
    public_origin,
    slugify_label,
)

WS = "ws_0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Acme", "acme"),
        ("Acme Corp.", "acme-corp"),
        ("Crème Brûlée & Co", "creme-brulee-co"),
        ("  --Weird__Name--  ", "weird-name"),
        ("日本語", ""),
    ],
)
def test_slugify_label(name: str, label: str) -> None:
    assert slugify_label(name) == label


def test_short_or_empty_names_fall_back_to_the_workspace_id() -> None:
    assert next(label_candidates("", WS)) == "ws-01234567"
    assert next(label_candidates("ab", WS)) == "ws-01234567"
    assert next(label_candidates("日本語", WS)) == "ws-01234567"


def test_long_names_are_cut_at_forty_on_a_hyphen_boundary() -> None:
    name = "the-quick-brown-fox-jumps-over-the-lazy-dog-again-and-again"
    first = next(label_candidates(name, WS))
    assert len(first) <= 40
    assert first == "the-quick-brown-fox-jumps-over-the-lazy"
    solid = "a" * 50
    assert next(label_candidates(solid, WS)) == "a" * 40


def test_reserved_labels_are_never_offered() -> None:
    for reserved in ("app", "api", "www", "pages", "page-origin", "admin", "mcp"):
        assert reserved in RESERVED_LABELS
        assert next(label_candidates(reserved, WS)) == f"{reserved}-2"
    assert "acme" not in RESERVED_LABELS


def test_candidates_suffix_from_two_and_keep_the_length_cap() -> None:
    assert list(islice(label_candidates("acme", WS), 3)) == ["acme", "acme-2", "acme-3"]
    long = "b" * 40
    second = list(islice(label_candidates(long, WS), 2))[1]
    assert second == "b" * 38 + "-2"
    assert len(second) <= 40


def test_allocate_label_skips_taken_and_reserved() -> None:
    assert allocate_label("Acme", set(), workspace_id=WS) == "acme"
    assert allocate_label("Acme", {"acme"}, workspace_id=WS) == "acme-2"
    assert allocate_label("Acme", {"acme", "acme-2"}, workspace_id=WS) == "acme-3"
    assert allocate_label("www", set(), workspace_id=WS) == "www-2"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Go.Acme.COM", "go.acme.com"),
        ("go.acme.com.", "go.acme.com"),
        ("  go.acme.com ", "go.acme.com"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_normalize_hostname(raw: str, normalized: str) -> None:
    assert normalize_hostname(raw) == normalized
    assert is_valid_hostname(normalized)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "-go.acme.com",
        "go-.acme.com",
        "go..acme.com",
        "a" * 64 + ".example",
        "go.acme.com:443",
        "go acme.com",
    ],
)
def test_invalid_hostnames_are_refused(bad: str) -> None:
    assert not is_valid_hostname(bad)
    with pytest.raises(ValueError):
        normalize_hostname(bad)


def test_public_origin() -> None:
    assert public_origin("acme.pages.cluehq.ai", scheme="https", port=None) == (
        "https://acme.pages.cluehq.ai"
    )
    assert public_origin("acme.pages.localhost", scheme="http", port=8040) == (
        "http://acme.pages.localhost:8040"
    )


def test_a_hyphen_cut_never_drops_below_the_minimum_length() -> None:
    first = next(label_candidates("a-" + "b" * 50, WS))
    assert LABEL_MIN <= len(first) <= LABEL_MAX
    assert first == ("a-" + "b" * 50)[:LABEL_MAX]
