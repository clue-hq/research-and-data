"""The discovery brief the Head of ABM writes (spec 2026-09-30 §3), and how gate roles decide."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.arv2.discovery_brief import Gate, parse_window_months
from clue_api.arv2.discovery_verifier import GateVerdict, disposition

GateRole = Literal["must", "must_not", "prefer"]
DiscoverySource = Literal["websets", "search"]


class BriefGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    rule: str = Field(min_length=1, max_length=500)
    test: str = Field(min_length=1, max_length=800)
    role: GateRole


class DiscoveryBrief2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: DiscoverySource
    query: str = Field(min_length=1, max_length=600)
    criteria: list[str] = Field(min_length=1, max_length=5)
    gates: list[BriefGate] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> DiscoveryBrief2:
        if any(not c.strip() or len(c) > 300 for c in self.criteria):
            raise ValueError("every criterion is 1-300 characters")
        keys = [g.key for g in self.gates]
        if len(set(keys)) != len(keys):
            raise ValueError("gate keys must be unique")
        return self


def verifier_gates(brief: DiscoveryBrief2) -> tuple[Gate, ...]:
    return tuple(
        Gate(
            key=g.key,
            rule=g.rule,
            test=g.test,
            window_months=parse_window_months(g.rule, g.test),
            main_business=g.role == "must_not",
        )
        for g in brief.gates
    )


@dataclass(frozen=True)
class RoleOutcome:
    excluded_by: str | None
    fit: float | None
    shown_disposition: str | None


def apply_roles(brief: DiscoveryBrief2, verdicts: Sequence[GateVerdict]) -> RoleOutcome:
    """A failed ``must`` or a passed ``must_not`` excludes; an unclear never does. Fit and the
    shown disposition are over the ``must`` and ``prefer`` gates only."""
    role = {g.key: g.role for g in brief.gates}
    for v in verdicts:
        if (role[v.gate_key] == "must" and v.verdict == "fail") or (
            role[v.gate_key] == "must_not" and v.verdict == "pass"
        ):
            return RoleOutcome(excluded_by=v.gate_key, fit=None, shown_disposition=None)
    scored = [v for v in verdicts if role[v.gate_key] != "must_not"]
    if not scored:
        return RoleOutcome(excluded_by=None, fit=None, shown_disposition="unclear")
    earned = sum(
        1.0 if v.verdict == "pass" else 0.5 if v.verdict == "unclear" else 0.0 for v in scored
    )
    return RoleOutcome(
        excluded_by=None, fit=earned / len(scored), shown_disposition=disposition(scored)
    )
