"""Status derivation for a custom hostname (spec §7.4) and the closed error-code set (§7.5).
Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from clue_api.dns_observe import DnsObservation

TXT_GRACE = timedelta(minutes=30)


@dataclass(frozen=True)
class ProviderState:
    status: str
    ssl_status: str | None
    verification_errors: tuple[str, ...]
    ssl_validation_errors: tuple[str, ...]
    deleted: bool = False


@dataclass(frozen=True)
class StatusDecision:
    status: str
    error_code: str | None
    error_detail: str | None


def _error(code: str, detail: str) -> StatusDecision:
    return StatusDecision(status="error", error_code=code, error_detail=detail)


def derive_status(
    *,
    observation: DnsObservation,
    provider: ProviderState | None,
    cname_target: str,
    expected_txt_value: str,
    connected_at: datetime,
    now: datetime,
) -> StatusDecision:
    if provider is None or provider.deleted or provider.status in ("moved", "deleted"):
        return _error(
            "verification_expired",
            "Cloudflare no longer holds this hostname; remove it and connect again.",
        )
    if observation.error:
        return _error("provider_error", f"DNS lookup failed: {observation.error}")
    caa = [m for m in provider.ssl_validation_errors if "caa" in m.lower()]
    if caa:
        return _error("caa_blocked", caa[0])
    other = (*provider.verification_errors, *provider.ssl_validation_errors)
    if other:
        return _error("provider_error", "; ".join(other))
    observed = observation.cname.rstrip(".").lower() if observation.cname else None
    if observed is None:
        return StatusDecision(status="pending_dns", error_code=None, error_detail=None)
    if observed != cname_target.rstrip(".").lower():
        return _error("cname_incorrect", f"CNAME points at {observed}, expected {cname_target}.")
    if expected_txt_value not in observation.txt_values:
        if now - connected_at > TXT_GRACE:
            return _error(
                "txt_missing", "The ownership TXT record has not appeared; add it to your DNS."
            )
        return StatusDecision(status="verifying_ownership", error_code=None, error_detail=None)
    if provider.status != "active" or provider.ssl_status != "active":
        return StatusDecision(status="issuing_certificate", error_code=None, error_detail=None)
    return StatusDecision(status="active", error_code=None, error_detail=None)
