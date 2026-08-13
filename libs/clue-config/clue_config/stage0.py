"""Versioned policy for governed Stage 0 and its three readiness gates."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
                # Seven of the nine substantive Client-KB baseline fields is the minimum useful
                # synthesis floor.  The denominator is compiled from CLIENT_BASELINE_FIELDS by
                # the backend, so an empty workspace extension policy can no longer turn 0/0
                # model-authored metrics into a misleading success.
                min_coverage_ratio=0.75,
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
                min_verified_claims=1,
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


__all__ = [
    "ReadinessFloor",
    "ReadinessSpec",
    "Stage0Policy",
    "DEFAULT_STAGE0_POLICY",
    "default_readiness_spec",
]
