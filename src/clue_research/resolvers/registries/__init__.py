"""Authoritative registry resolvers — NPI / DUNS / CIK / LEI (M4.4 / ENG-122).

Deterministic, tier-1 sources that return an entity's *registry id* as a typed claim — the highest-
trust account identifiers (substrate §2: ``account_entity.registry_ids``). They are **vertical-gated
by construction**: a registry resolver only runs when a field's ``tier_plan`` names it, and only
a pack that includes that registry's field-class puts it there (substrate §3 payoff 1 — "NPI becomes
a resolver that only activates for healthcare ICPs"). So binding NPI is always safe; it is simply
never *invoked* for a non-healthcare ICP, because no non-healthcare field's ``tier_plan`` lists it.

The four are a config-driven family (a :class:`RegistrySpec` each) over one normalization,
not four hand-written resolvers: each declares the field-key it serves, the key its record holds the
id under, its citing base, and its public/credentialed status. The resolver returns the id claim;
M2's canonicalization is what writes it into ``account_entity.registry_ids`` (out of scope here).
NPI/SEC(CIK)/GLEIF(LEI) are public (no ``auth_ref``); DUNS is credentialed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from clue_research.core import CostCents, FieldDef
from clue_research.resolvers.base import (
    DeterministicResolver,
    EnrichmentBackend,
    ResolvedField,
    resolved_field,
)
from clue_research.resolvers.live import AccountLookup, HttpEnrichmentBackend, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_research.core import AccountEntity


@dataclass(frozen=True)
class RegistrySpec:
    """The per-registry configuration — the only thing that differs between NPI/DUNS/CIK/LEI."""

    source_key: str
    served_field: str  # the single field-key this registry populates, e.g. "healthcare.npi"
    id_key: str  # the key holding the registry id in the registry's record
    source_base: str  # the citing base URL when the record carries no canonical record_url
    auth_ref: str | None = None  # None ⇒ a public registry queried without a credential
    confidence: float = 0.97  # an authoritative registry match is high-confidence by definition


NPI = RegistrySpec("npi", "healthcare.npi", "npi", "https://npiregistry.cms.hhs.gov", auth_ref=None)
DUNS = RegistrySpec(
    "duns",
    "account.duns_number",
    "duns_number",
    "https://www.dnb.com",
    auth_ref="CLUE_DUNS_API_KEY",
)
CIK = RegistrySpec("cik", "account.cik", "cik", "https://www.sec.gov", auth_ref=None)
LEI = RegistrySpec("lei", "account.lei", "lei", "https://search.gleif.org", auth_ref=None)

SPECS: dict[str, RegistrySpec] = {spec.source_key: spec for spec in (NPI, DUNS, CIK, LEI)}


def registry_normalize(
    payload: Mapping[str, Any], field: FieldDef, *, spec: RegistrySpec
) -> list[ResolvedField]:
    """Normalize a registry record into the registry-id claim for the requested field.

    Returns ``[]`` unless the requested ``field`` is exactly the field this registry serves (so an
    NPI resolver handed a non-NPI field is a clean no-op) and the record carries the id (else a hard
    miss — the field is left empty+flagged, never fabricated). The id is the value; the grounding
    span and citing URL come from the record.
    """
    if field.field_key != spec.served_field:
        return []
    registry_id = payload.get(spec.id_key)
    if registry_id is None or registry_id == "":
        return []
    source_url = str(payload.get("record_url") or spec.source_base)
    return [
        resolved_field(
            field.field_key, registry_id, source_url=source_url, confidence=spec.confidence
        )
    ]


def _build_request(
    spec: RegistrySpec, account: AccountEntity, field: FieldDef, token: SecretStr | None
) -> HttpRequest:  # pragma: no cover - live request shape (finalized against recorded fixtures)
    params = {"q": account.canonical_name}
    if token is not None:
        params["api_key"] = token.get_secret_value()
    return HttpRequest(url=f"{spec.source_base}/api", params=params)


def make_resolver(
    source_key: str,
    *,
    backend: EnrichmentBackend | None = None,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents,
) -> DeterministicResolver:
    """Construct a registry resolver by ``source_key`` (live backend; inject for tests)."""
    spec = SPECS[source_key]
    return DeterministicResolver(
        backend
        or HttpEnrichmentBackend(
            source_key=spec.source_key,
            auth_ref=spec.auth_ref,
            build_request=partial(_build_request, spec),
            normalize=partial(registry_normalize, spec=spec),
            accounts=accounts,
        ),
        cost_cents=cost_cents,
    )
