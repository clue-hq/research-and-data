"""ZoomInfo — people/firmographic enrichment (M4.4 / ENG-122).

A second direct structured-DB people source under the uniform resolver seam: it normalizes its own
response shape (``email`` / ``jobTitle`` …) into the same provider-agnostic claims Clay and Apollo
produce, so a field's ``tier_plan`` can mix or swap any of them with no caller change. Tier-1,
``structured`` modality; contacts it enriches carry a ``WEAK`` identity binding (the manifest's
authoritative strength) until a stronger source corroborates them.
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

SOURCE_KEY = "zoominfo"
AUTH_REF = "CLUE_ZOOMINFO_API_KEY"
_API = "https://api.zoominfo.com"
_SOURCE_BASE = "https://www.zoominfo.com"
_DEFAULT_CONFIDENCE = 0.87

# Only fields registered in the field registry — a claim for an unregistered field_key is rejected
# by insert_claim (the registry is the single source of valid keys). ZoomInfo's contact title would
# need a registered ``contact.*`` field first (a pack/M3 concern); until then it serves work email.
_PROVIDER_FIELD: dict[str, str] = {
    "core.work_email": "email",
}


def normalize(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    """Map a ZoomInfo contact/company record to the requested field (hard miss → ``[]``)."""
    return normalize_record(
        payload,
        field,
        field_map=_PROVIDER_FIELD,
        url_key="profile_url",
        url_base=_SOURCE_BASE,
        confidence_key="match_score",
        default_confidence=_DEFAULT_CONFIDENCE,
    )


def _build_request(
    account: AccountEntity, field: FieldDef, token: SecretStr | None
) -> HttpRequest:  # pragma: no cover - live request shape (finalized against recorded fixtures)
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
    return HttpRequest(
        url=f"{_API}/enrich/company",
        headers=headers,
        params={"domain": account.primary_domain or account.canonical_name},
    )


def make_resolver(
    *,
    backend: EnrichmentBackend | None = None,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents,
) -> DeterministicResolver:
    """Construct the ZoomInfo resolver (live backend by default; inject ``backend`` for tests)."""
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
