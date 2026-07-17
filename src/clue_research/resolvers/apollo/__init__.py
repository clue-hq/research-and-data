"""Apollo — people/firmographic enrichment + the direct alternative to Clay (M4.4 / ENG-122).

Apollo is implemented as the **direct alternative to Clay for an overlapping field-class** (work
email, employee count) so per-field insourcing is provable: the same field can list ``[clay]``,
``[apollo]``, or ``[apollo, clay]`` in its ``tier_plan`` and the waterfall (M4.1) picks per config —
zero caller change (the Clay note's build-vs-buy as pure config). Apollo's response shape is
its own (``estimated_num_employees``, ``email`` …); :func:`normalize` maps it to the same
provider-agnostic :class:`ResolvedField`\\s Clay produces, so nothing downstream can tell which
provider answered. It also enriches contacts (``email`` on a resolved contact entity) and serves
``account.recent_funding`` as a firmographic signal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import JsonValue

from clue_core import CostCents, FieldDef
from clue_research.resolvers.base import (
    DeterministicResolver,
    EnrichmentBackend,
    ResolvedField,
    coerce_confidence,
    normalize_record,
    resolved_field,
)
from clue_research.resolvers.live import AccountLookup, HttpEnrichmentBackend, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_core import AccountEntity

SOURCE_KEY = "apollo"
AUTH_REF = "CLUE_APOLLO_API_KEY"
_API = "https://api.apollo.io/v1"
_SOURCE_BASE = "https://app.apollo.io"
_DEFAULT_CONFIDENCE = 0.9  # a direct source for the field — slightly higher than the aggregator
_FUNDING_FIELD = "account.recent_funding"

# Apollo's own flat response keys → our field_key. Distinct from Clay's keys on purpose: proving the
# normalization (not the wire shape) is what each resolver owns. ``account.recent_funding`` is NOT
# here — its registry value_schema is an object (required ``amount_usd``), so it is built by
# :func:`_normalize_funding`, not the flat path (a string would be rejected by the value validator).
_PROVIDER_FIELD: dict[str, str] = {
    "core.work_email": "email",
    "core.employee_count": "estimated_num_employees",
}


def normalize(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    """Map an Apollo match record to typed :class:`ResolvedField`\\s for the requested field.

    Returns ``[]`` on a hard miss (field unserved or value absent). Confidence is Apollo's
    ``confidence`` (or a direct-source default); the citing URL is the match's Apollo record. The
    funding field is normalized to its registered object shape (the flat keys to their scalar).
    """
    if field.field_key == _FUNDING_FIELD:
        return _normalize_funding(payload, field)
    return normalize_record(
        payload,
        field,
        field_map=_PROVIDER_FIELD,
        url_key="apollo_url",
        url_base=_SOURCE_BASE,
        confidence_key="confidence",
        default_confidence=_DEFAULT_CONFIDENCE,
    )


def _normalize_funding(payload: Mapping[str, Any], field: FieldDef) -> list[ResolvedField]:
    """Build ``account.recent_funding`` as the registry's required object ``{amount_usd, round}``.

    The field's value_schema requires ``amount_usd`` (a number), so a stage string alone cannot
    satisfy it: without an amount this is a *hard miss* (it falls through to a deeper source),
    never a malformed claim. ``round`` (the stage) is attached when Apollo reports it.
    """
    amount = payload.get("funding_total_usd")
    if amount in (None, ""):
        return []
    value: dict[str, JsonValue] = {"amount_usd": amount}
    stage = payload.get("latest_funding_stage")
    if stage:
        value["round"] = stage
    source_url = str(payload.get("apollo_url") or _SOURCE_BASE)
    confidence = coerce_confidence(
        payload.get("confidence", _DEFAULT_CONFIDENCE), _DEFAULT_CONFIDENCE
    )
    return [resolved_field(field.field_key, value, source_url=source_url, confidence=confidence)]


def _build_request(
    account: AccountEntity, field: FieldDef, token: SecretStr | None
) -> HttpRequest:  # pragma: no cover - live request shape (finalized against recorded fixtures)
    api_key = token.get_secret_value() if token else ""
    return HttpRequest(
        url=f"{_API}/organizations/enrich",
        params={"domain": account.primary_domain or account.canonical_name, "api_key": api_key},
    )


def make_resolver(
    *,
    backend: EnrichmentBackend | None = None,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents,
) -> DeterministicResolver:
    """Construct the Apollo resolver (live backend by default; inject ``backend`` for tests)."""
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
