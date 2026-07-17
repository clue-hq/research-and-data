"""Clay — the swappable tier-1 enrichment aggregator (M4.4 / ENG-122).

Clay collapses dozens of provider integrations into one waterfall across 150+ databases; it is the
pragmatic V1 move but **one resolver among many** and **permanent-until-proven-otherwise** (the Clay
note). Here it is exactly that: a :class:`DeterministicResolver` over a
``clay``-keyed backend that normalizes Clay's commodity ``core.*`` answers (firmographics, work
email, generic tech stack) into typed claims like every other resolver. No Clay-specific response
shape escapes :func:`normalize`; ``provider='clay'`` is billing/ops-only and is never
branched on downstream — so insourcing a field later (Clay → a direct API, e.g. Apollo) is binding a
different backend to a different ``source_key`` and editing a ``tier_plan``, not a caller change.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from clue_core import CostCents, FieldDef
from clue_research.resolvers.base import (
    DeterministicResolver,
    EnrichmentBackend,
    ResolvedField,
    normalize_record,
)
from clue_research.resolvers.live import AccountLookup, HttpEnrichmentBackend, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_core import AccountEntity

SOURCE_KEY = "clay"
AUTH_REF = "CLUE_CLAY_API_KEY"
_API = "https://api.clay.com/v1"
_SOURCE_BASE = "https://app.clay.com"
_DEFAULT_CONFIDENCE = 0.88  # Clay's match rate is breadth-driven; clears the 0.8 core threshold

# Our field_key → the key Clay returns it under in a record (the assumed response contract,
# finalized against recorded fixtures when live keys land). Mapping *here* — not downstream — is the
# normalization that keeps Clay's shape from leaking past this resolver.
_PROVIDER_FIELD: dict[str, str] = {
    "core.employee_count": "employee_count",
    "core.work_email": "work_email",
    "core.primary_domain": "domain",
    "core.primary_tech_stack": "technologies",
}


def normalize(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    """Map a Clay enrichment record to typed :class:`ResolvedField`\\s for the requested field.

    Returns ``[]`` when Clay does not serve the field or the value is absent (a *hard miss* — the
    field may end empty+flagged, never fabricated). The span and citing ``source_url`` come
    from the record; confidence is Clay's ``match_confidence`` (or a breadth-driven default).
    """
    return normalize_record(
        payload,
        field,
        field_map=_PROVIDER_FIELD,
        url_key="record_url",
        url_base=_SOURCE_BASE,
        confidence_key="match_confidence",
        default_confidence=_DEFAULT_CONFIDENCE,
    )


def _build_request(
    account: AccountEntity, field: FieldDef, token: SecretStr | None
) -> HttpRequest:  # pragma: no cover - live request shape (finalized against recorded fixtures)
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
    return HttpRequest(
        url=f"{_API}/enrich",
        headers=headers,
        params={"domain": account.primary_domain or account.canonical_name},
    )


def make_resolver(
    *,
    backend: EnrichmentBackend | None = None,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents,
) -> DeterministicResolver:
    """Construct the Clay resolver (live backend by default; inject ``backend`` for tests)."""
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
