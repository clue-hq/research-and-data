"""The one place the gateway's cost stamp is parsed (lane 3 slice 1, Task 2)."""

from __future__ import annotations

from decimal import Decimal

from clue_gateway.metadata import COST_CENTS_KEY, COST_SOURCE_KEY, cost_cents_from_metadata


def test_metered_answer_yields_its_cents_as_a_decimal() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "1.2345", COST_SOURCE_KEY: "metered"}) == (
        Decimal("1.2345"),
        "metered",
    )


def test_estimate_answer_is_priced_but_labelled_estimate() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "0.5", COST_SOURCE_KEY: "estimate"}) == (
        Decimal("0.5"),
        "estimate",
    )


def test_unpriced_answer_is_a_blank_not_a_zero() -> None:
    assert cost_cents_from_metadata({COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"}) == (
        None,
        "unpriced",
    )


def test_missing_or_malformed_stamp_is_blank() -> None:
    assert cost_cents_from_metadata({}) == (None, None)
    assert cost_cents_from_metadata({COST_SOURCE_KEY: "metered"}) == (None, "metered")
    assert cost_cents_from_metadata(
        {COST_CENTS_KEY: "not-a-number", COST_SOURCE_KEY: "metered"}
    ) == (
        None,
        "metered",
    )
    assert cost_cents_from_metadata({COST_CENTS_KEY: "1", COST_SOURCE_KEY: "free"}) == (None, None)
