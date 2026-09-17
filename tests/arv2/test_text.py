"""The verbatim-matching primitives, on the semantics ``z4e_quote_verify.py`` established."""

from __future__ import annotations

from clue_api.arv2.text import normalize_for_match, substring_verdict

TRANSCRIPT = (
    "So when we started Zafran, the thing I cared about most was that the team could "
    "actually explain a risk to a CISO in one sentence, and we refused to ship anything "
    "that needed a slide deck to justify it. That is still the bar."
)


def test_normalisation_folds_case_punctuation_and_whitespace() -> None:
    """Whitespace collapses first, then punctuation becomes a space — the PoC's exact order.

    So a comma leaves the space it stood next to behind ("hello  world", two spaces). That is a
    faithful port, not an oversight: both sides of a comparison are folded the same way, so a
    verbatim substring stays a substring, and a verdict computed here can be compared against a
    verdict the proof-of-concept recorded.
    """
    assert normalize_for_match("  Hello,   WORLD!  ") == "hello  world"
    assert normalize_for_match("plain words here") == "plain words here"
    assert normalize_for_match(None) == ""
    assert normalize_for_match("") == ""


def test_normalisation_straightens_curly_quotes() -> None:
    """A smart apostrophe must not make a genuine quote look invented."""
    assert normalize_for_match("we don’t ship") == normalize_for_match("we don't ship")
    assert normalize_for_match("“quoted”") == normalize_for_match('"quoted"')


def test_normalisation_applies_nfkc() -> None:
    """NFKC folds the full-width and ligature forms a transcript can carry."""
    assert normalize_for_match("ＺＡＦＲＡＮ") == "zafran"
    assert normalize_for_match("ﬁrst") == "first"


def test_an_exact_substring_is_exact_despite_punctuation_and_case() -> None:
    assert substring_verdict("THE TEAM COULD ACTUALLY EXPLAIN A RISK", TRANSCRIPT) == "EXACT"
    assert substring_verdict("we refused to ship anything", TRANSCRIPT) == "EXACT"


def test_an_exact_substring_is_exact_despite_curly_quotes() -> None:
    assert substring_verdict("That is still the bar.", TRANSCRIPT) == "EXACT"
    assert substring_verdict("That’s not in there at all, honestly", TRANSCRIPT) == "NOT_FOUND"


def test_a_quote_with_a_word_changed_inside_it_is_partial() -> None:
    """One altered word mid-quote leaves a 40-character window intact — PARTIAL, not EXACT."""
    altered = (
        "the thing I cared about most was that the squad could actually explain a risk to a "
        "CISO in one sentence"
    )
    assert substring_verdict(altered, TRANSCRIPT) == "PARTIAL"


def test_a_fabricated_quote_is_not_found() -> None:
    fabricated = (
        "our whole strategy has always been to undercut the incumbent vendors on price and "
        "then win the renewal on support quality"
    )
    assert substring_verdict(fabricated, TRANSCRIPT) == "NOT_FOUND"


def test_a_short_needle_shorter_than_the_window_never_reports_partial() -> None:
    """Below one window there is nothing to slide, so the answer is EXACT or NOT_FOUND."""
    assert substring_verdict("one sentence", TRANSCRIPT) == "EXACT"
    assert substring_verdict("one sandwich", TRANSCRIPT) == "NOT_FOUND"


def test_an_empty_needle_is_not_found() -> None:
    """An empty quote is not "trivially present": it is no evidence at all."""
    assert substring_verdict("", TRANSCRIPT) == "NOT_FOUND"
    assert substring_verdict("   ", TRANSCRIPT) == "NOT_FOUND"
