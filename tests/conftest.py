"""Shared fixtures for the core-contract tests (M0.2)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from clue_research.core import (
    Claim,
    EntityId,
    ExtractionMethod,
    ResearchMode,
    RunId,
    account_claim,
    contact_claim,
    new_entity_id,
    new_run_id,
)


@pytest.fixture
def entity_id() -> EntityId:
    return new_entity_id()


@pytest.fixture
def run_id() -> RunId:
    return new_run_id()


@pytest.fixture
def make_account(entity_id: EntityId, run_id: RunId) -> Callable[..., Claim]:
    """Build a valid account claim, overriding any field via kwargs."""

    def _make(**overrides: object) -> Claim:
        kwargs: dict[str, object] = {
            "entity_id": entity_id,
            "field_key": "account.recent_funding",
            "value_json": {"amount_usd": 1_000_000},
            "source_tier": 1,
            "extraction_method": ExtractionMethod.API,
            "confidence": 0.9,
            "run_id": run_id,
            "research_mode": ResearchMode.ACCOUNT_PROFILING,
            "source_url": "https://example.com/funding",
        }
        kwargs.update(overrides)
        return account_claim(**kwargs)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def make_contact(entity_id: EntityId, run_id: RunId) -> Callable[..., Claim]:
    """Build a valid contact claim (identity_binding + use_class default to strong/professional)."""

    def _make(**overrides: object) -> Claim:
        from clue_research.core import IdentityBinding, UseClass

        kwargs: dict[str, object] = {
            "entity_id": entity_id,
            "field_key": "contact.facet.recent_post",
            "value_json": "spoke at KubeCon",
            "source_tier": 2,
            "extraction_method": ExtractionMethod.SCRAPE,
            "confidence": 0.8,
            "run_id": run_id,
            "research_mode": ResearchMode.CONTACT_PROFILING,
            "source_url": "https://example.com/post",
            "identity_binding": IdentityBinding.STRONG,
            "use_class": UseClass.PROFESSIONAL_PUBLIC,
        }
        kwargs.update(overrides)
        return contact_claim(**kwargs)  # type: ignore[arg-type]

    return _make
