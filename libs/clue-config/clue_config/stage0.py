"""Versioned policy for governed Stage 0 and its three readiness gates."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_config.settings import Settings
from clue_core import CostCents, FieldKey, ReadinessGate


class ReadinessFloor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    required_field_keys: tuple[FieldKey, ...] = ()
    min_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    min_verified_claims: int = Field(default=0, ge=0)
    max_open_policy_blocks: int = Field(default=0, ge=0)
    require_product_id: bool = False
    require_confirmed_icp: bool = False


class ReadinessSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=1, ge=1)
    floors: dict[ReadinessGate, ReadinessFloor]

    @model_validator(mode="after")
    def _all_gates_present(self) -> ReadinessSpec:
        expected = set(ReadinessGate)
        actual = set(self.floors)
        if actual != expected:
            missing = sorted(gate.value for gate in expected - actual)
            extra = sorted(str(gate) for gate in actual - expected)
            raise ValueError(
                f"readiness floors must define all gates; missing={missing}, extra={extra}"
            )
        return self


def default_readiness_spec() -> ReadinessSpec:
    return ReadinessSpec(
        floors={
            ReadinessGate.ICP_SYNTHESIS: ReadinessFloor(
                # Founder ruling (2026-08-19): baseline-field coverage is advisory and must not
                # mechanically block ICP synthesis by default. A workspace may still opt into a
                # higher floor through its explicit, versioned readiness policy.
                min_coverage_ratio=0.0,
                require_product_id=True,
                max_open_policy_blocks=0,
            ),
            ReadinessGate.DISCOVERY_SPEND: ReadinessFloor(
                min_coverage_ratio=0.25,
                max_open_policy_blocks=0,
                require_product_id=True,
                require_confirmed_icp=True,
            ),
            ReadinessGate.DEEP_SPEND: ReadinessFloor(
                min_coverage_ratio=0.5,
                # R0 Part 3C fix 3: the floor counts VERIFIED claims. With
                # `CLUE_VERIFICATION_ENABLED=false` nothing is ever promoted to VERIFIED, so a
                # floor of 1 could never be met and DEEP_SPEND readiness would deadlock. The
                # human override (`override_stage0_readiness`) remains the governing gate on
                # deep spend; this floor was never the authority.
                min_verified_claims=0,
                max_open_policy_blocks=0,
                require_product_id=True,
                require_confirmed_icp=True,
            ),
        }
    )


class Stage0Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fast_budget_cents: CostCents = Decimal("5")
    background_budget_cents: CostCents = Decimal("100")
    recon_dedupe_ttl_seconds: int = Field(default=86_400, ge=0)
    readiness: ReadinessSpec = Field(default_factory=default_readiness_spec)


DEFAULT_STAGE0_POLICY = Stage0Policy()


def stage0_policy_from_settings(settings: Settings) -> Stage0Policy:
    """The **production** Stage-0 policy: the frozen defaults with the two lane envelopes taken
    from deployment settings.

    Founder ruling (FI-onboarding-contract-gap-review §9, 2026-08-13): onboarding forms the base
    of everything downstream, so an envelope must never truncate onboarding research — quality
    before cost. That ruling needs a *mechanism*: this is it, and the composition root
    (``clue_api.toolbelt_wiring.build_toolbelt``) builds the recon tools' policy through here so
    a deployment raises a cap with an env var instead of a code change.

    Only the two budgets move. The dedupe TTL and the readiness spec stay the versioned constants
    they are — they are correctness/governance, not cost. ``DEFAULT_STAGE0_POLICY`` is
    deliberately left at its 5¢/100¢ library defaults: it is the shape tests and non-composed
    callers pin, and the *production* default now comes from ``Settings`` (25¢ fast — the full
    eleven-field firecrawl walk with headroom).
    """

    return Stage0Policy(
        fast_budget_cents=settings.stage0_fast_budget_cents,
        background_budget_cents=settings.stage0_background_budget_cents,
    )


__all__ = [
    "ReadinessFloor",
    "ReadinessSpec",
    "Stage0Policy",
    "DEFAULT_STAGE0_POLICY",
    "default_readiness_spec",
    "stage0_policy_from_settings",
]
