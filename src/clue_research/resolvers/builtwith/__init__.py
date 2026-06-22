"""BuiltWith — technographics (M4.4 / ENG-122).

The tier-1 ``structured`` technographics resolver: it populates ``core.primary_tech_stack`` (and
other tech mentions) from BuiltWith's observed-technology record. A miss returns ``[]`` — the
field is left for the merge to fill from another source or end empty+flagged — never a fabricated
stack (a dedicated M4.4 acceptance criterion). Account-scoped (technographics are an account fact),
so it never produces a contact claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from clue_research.core import CostCents, FieldDef
from clue_research.resolvers.base import (
    DeterministicResolver,
    EnrichmentBackend,
    ResolvedField,
    normalize_record,
)
from clue_research.resolvers.live import AccountLookup, HttpEnrichmentBackend, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_research.core import AccountEntity

SOURCE_KEY = "builtwith"
AUTH_REF = "CLUE_BUILTWITH_API_KEY"
_API = "https://api.builtwith.com/v21/api.json"
_SOURCE_BASE = "https://builtwith.com"
_DEFAULT_CONFIDENCE = 0.92  # an observed technology footprint is high-confidence when present

_PROVIDER_FIELD: dict[str, str] = {
    "core.primary_tech_stack": "technologies",
}


def normalize(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    """Map BuiltWith's technology list to ``core.primary_tech_stack`` (hard miss → ``[]``)."""
    return normalize_record(
        payload,
        field,
        field_map=_PROVIDER_FIELD,
        url_key="lookup_url",
        url_base=_SOURCE_BASE,
        confidence_key="confidence",
        default_confidence=_DEFAULT_CONFIDENCE,
    )


def _build_request(
    account: AccountEntity, field: FieldDef, token: SecretStr | None
) -> HttpRequest:  # pragma: no cover - live request shape (finalized against recorded fixtures)
    api_key = token.get_secret_value() if token else ""
    return HttpRequest(
        url=_API,
        params={"KEY": api_key, "LOOKUP": account.primary_domain or account.canonical_name},
    )


def make_resolver(
    *,
    backend: EnrichmentBackend | None = None,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents,
) -> DeterministicResolver:
    """Construct the BuiltWith resolver (live backend by default; inject ``backend`` for tests)."""
    return DeterministicResolver(
        backend
        or HttpEnrichmentBackend(
            source_key=SOURCE_KEY,
            auth_ref=AUTH_REF,
            build_request=_build_request,
            normalize=normalize,
            accounts=accounts,
        ),
        cost_cents=cost_cents,
    )
