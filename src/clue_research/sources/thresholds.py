"""Per-field-class confidence thresholds — the waterfall's stop knob (M4.1, locked decision #1).

The trust-tiered waterfall stops at the first claim whose ``confidence`` clears the field's
threshold (substrate §4). Locked decision #1: that threshold is **engine-side versioned config keyed
by field-class** (deterministic firmographic fields demand a high bar; fuzzy resonance/facet signals
a lower one) — it is **NOT** on ``FieldDef`` / the field table / the plan hash. The waterfall
reads it here; swapping a threshold is a config change, never a field-row migration or a code edit.

It is "policy as data" like every other tunable (conventions §2); a per-client/per-ICP override can
later be layered through the config seam without touching the engine.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clue_research.core import FieldClass, UnitInterval

# Starting priors (D7 — defaults to confirm against real campaigns, not hardcoded policy):
# deterministic/official facts demand a high bar; fuzzy synthesized signals (resonance, personal
# hooks) clear at a lower one (decision #1 example: "firmographic 0.8, fuzzy resonance 0.6").
_DEFAULTS: dict[FieldClass, float] = {
    FieldClass.CORE: 0.8,
    FieldClass.ACCOUNT: 0.75,
    FieldClass.ACCOUNT_RESONANCE: 0.6,
    FieldClass.CONTACT: 0.75,
    FieldClass.CONTACT_FACET: 0.6,
    FieldClass.PACK: 0.75,
}


class ConfidenceThresholds(BaseModel):
    """Versioned per-field-class confidence thresholds the waterfall reads (decision #1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    # Fallback for any field-class not explicitly listed.
    default: UnitInterval = 0.7
    by_field_class: dict[FieldClass, UnitInterval] = Field(default_factory=lambda: dict(_DEFAULTS))

    def for_field_class(self, field_class: FieldClass) -> float:
        """The confidence a claim must clear to stop the waterfall for this field-class."""
        return self.by_field_class.get(field_class, self.default)


DEFAULT_CONFIDENCE_THRESHOLDS = ConfidenceThresholds()
