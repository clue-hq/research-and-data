"""The catalog synchronizer's name-comparison key, offline.

The pairs are the ones four live onboarding runs on ONE workspace actually produced: the lineup
renamed the same offerings between runs (trademark marks, spacing, a stray "Agent" suffix) and the
product rows grew from 19 to 28. Everything here is about the comparison key only — a hit still has
to survive the resolution ladder, and nothing normalizes a product into being renamed or merged.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.arv2.onboarding_lineage import (
    CatalogProduct,
    ProductLink,
    _fingerprint,
    _should_reconcile,
    normalize_identity,
)

SAME = [
    ("Aura AI Scribe", "Aura™ AI Scribe"),
    ("Aura Anywhere", "Aura™ Anywhere"),
    ("MagicFlow", "magic flow"),
]

DIFFERENT = [
    ("AI Front Desk", "AI Front Desk for Clinics"),
    ("Referrals AI Agent", "Referral Management AI Agent"),
    ("Direct Access Colonoscopy AI Agent", "Direct Access Colonoscopy AI Intake"),
    ("athenahealth", "Insight Health for athenahealth"),
]


@pytest.mark.parametrize(("left", "right"), SAME)
def test_drifted_spellings_of_one_product_share_a_key(left: str, right: str) -> None:
    assert normalize_identity(left) == normalize_identity(right)


@pytest.mark.parametrize(("left", "right"), DIFFERENT)
def test_distinct_offerings_keep_distinct_keys(left: str, right: str) -> None:
    """These pairs differ by a real word, not by decoration. They stay separate rows on purpose —
    whether two of them are one product is the product-set gate's call, not the key's."""
    assert normalize_identity(left) != normalize_identity(right)


def test_the_fingerprint_is_over_the_raw_entry_not_the_normalized_one() -> None:
    """The lineage fingerprint keys every row already at rest; if normalization touched it, every
    existing row would stop matching its own entry and lineage reuse would break for all of them."""
    plain = CatalogProduct(name="Aura AI Scribe", short_description="Ambient.", aliases=())
    marked = CatalogProduct(name="Aura™ AI Scribe", short_description="Ambient.", aliases=())
    assert _fingerprint(plain) != _fingerprint(marked)
    assert (
        _fingerprint(plain)
        == "sha256:69cbfa622a1a3ca49f87b5f59ca19d95f489b36aeaaf9e5f7b6d80853e337683"
    )


def test_a_product_link_carries_no_reconcile_verdict_unless_a_model_gave_one() -> None:
    """Every deterministic rung leaves both columns NULL — a NULL says "no model decided this"."""
    link = ProductLink("prd_x", "MagicFlow", "alias_reused", 1, uuid4())
    assert (link.reconcile_confidence, link.reconcile_reason) == (None, None)


def test_the_model_stage_is_skipped_when_its_answer_is_already_known() -> None:
    """A first run with one unplaced entry and nothing on file has exactly one possible answer, so
    the synchronizer does not spend a call to hear it. Everything else with leftovers is asked."""
    assert _should_reconcile(existing=0, leftovers=0) is False
    assert _should_reconcile(existing=3, leftovers=0) is False
    assert _should_reconcile(existing=0, leftovers=1) is False
    assert _should_reconcile(existing=1, leftovers=1) is True
    assert _should_reconcile(existing=0, leftovers=2) is True
