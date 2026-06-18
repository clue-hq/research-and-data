"""Per-client jurisdiction / use-class / posture policy — *shapes + defaults only* (M0.4).

"Policy is data, not code" (conventions §2). Doc D §1 demands jurisdiction be a *first-class
per-client switch* and the three personal-data postures (Doc D §6) ship as per-client config on
one ``use_class × jurisdiction`` machinery — "design for the strict (GDPR) case and switch down."
That switch and that policy schema must exist from the foundation, **even though the gate that
enforces them is M10** — retrofitting lawful-basis/jurisdiction tracking later is exactly the
base-layer rework Doc D §1 warns against.

**This module defines the typed shapes and the conservative defaults. It contains NO enforcement
logic.** The use-gate (``(use_class × jurisdiction × client_policy)`` → allowed?), the lawful-basis
balancing test (LIA), and the ``lawful_basis`` claim-provenance field all land with M10. Here we
only carry the inputs that gate will read.

Reuses :class:`clue_research.core.UseClass` (``professional-public | personal-public-non-sensitive
| sensitive``) — it is **not** re-defined here.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from clue_research.core import UseClass


class Jurisdiction(StrEnum):
    """A jurisdiction *regime* key (not a specific country) — the first-class per-client switch
    (Doc D §1). Regimes, strictest first; the default is the GDPR-grade strict case and lighter
    regimes are a *relaxation* of the same machinery, never a separate code path.

    Open by the same spirit as field-keys: the **specific 2026 legal values are D8** and are not
    encoded here — only the machinery to carry a regime key the M10 gate parameterizes on. New
    regimes are added as members without changing the gate.
    """

    GDPR = "gdpr"  # EU/UK GDPR-grade — the strict default ("design for the strict case")
    UK_GDPR = "uk_gdpr"  # UK GDPR / DPA 2018
    US_STATE = "us_state"  # US state privacy laws (CCPA/CPRA-grade); lighter B2B regime
    GLOBAL_STRICT = "global_strict"  # mixed/global, default to strictest obligations (D4)


# The GDPR-grade strict case is the default (Doc D §1). Centralized so callers never spell it out.
DEFAULT_JURISDICTION = Jurisdiction.GDPR


class Posture(StrEnum):
    """The three personal-data postures (Doc D §6), shipped as per-client config — **not**
    permanent forks. Option 1 is the recommended default; a regulated client dials down to
    Option 3, an aggressive US client dials up to Option 2.

    The decision is deferred to the data/compliance owner (D3); the platform hardcodes none of
    them — it ships all three as the *same* ``use_class × jurisdiction`` machinery.
    """

    CONSERVATIVE_DEFAULT = "conservative_default"  # Option 1 (recommended default)
    GATHER_BROADLY_GATE_AT_USE = "gather_broadly_gate_at_use"  # Option 2
    PROFESSIONAL_PUBLIC_ONLY = "professional_public_only"  # Option 3 (scopes at the source level)


DEFAULT_POSTURE = Posture.CONSERVATIVE_DEFAULT


class UseDisposition(StrEnum):
    """What may be done with a claim of a given use-class in a given jurisdiction — the value
    type of the allow-map (Doc D §6). Read by the M10 use-gate; **not enforced here**.

    * ``USABLE`` — may drive outreach (clears the use side of the gate; the accuracy/identity
      gate is still separate).
    * ``STORED_UNUSABLE`` — stored for completeness/provenance but locked from outreach.
    * ``NOT_STORED`` — not retained at all (the strictest disposition; minimizes risk).
    """

    USABLE = "usable"
    STORED_UNUSABLE = "stored_unusable"
    NOT_STORED = "not_stored"


class SourceScope(StrEnum):
    """How wide research is scoped *at the source level* — the lever the posture drives (Doc D §6).

    * ``FULL_SWEEP`` — the full deep open-internet sweep is allowed (Options 1 & 2); what is
      *usable* is then governed by the allow-map at/after extraction.
    * ``PROFESSIONAL_PUBLIC_ONLY`` — research is scoped to professional-public surfaces
      (LinkedIn, company pages, talks, publications); the deep personal-life classes are **never
      collected** (Option 3). This is a *collection*-time scope, distinct from the use-gate.
    """

    FULL_SWEEP = "full_sweep"
    PROFESSIONAL_PUBLIC_ONLY = "professional_public_only"


# The conservative-default allow-map (Doc D §6 Option 1): professional-public and
# personal-public-non-sensitive are usable; sensitive (special-category) is locked. Stored as a
# plain mapping so a client override is a data write, not a code change.
_CONSERVATIVE_ALLOW_MAP: dict[UseClass, UseDisposition] = {
    UseClass.PROFESSIONAL_PUBLIC: UseDisposition.USABLE,
    UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: UseDisposition.USABLE,
    UseClass.SENSITIVE: UseDisposition.STORED_UNUSABLE,  # locked: special-category, Art. 9
}


class LawfulBasisDefaults(BaseModel):
    """Placeholder for lawful-basis defaults (Doc D §4) — *carried, not enforced* in M0.

    The working basis for ``professional-public`` B2B signals is typically *legitimate interest*
    (GDPR Art. 6(1)(f)), which requires a documented balancing test (an LIA). The actual
    ``lawful_basis`` claim-provenance field and the LIA logic land with **M10** — here we only
    record the per-client default string the gate will stamp onto claims.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    professional_public_basis: str = "legitimate_interest"  # GDPR Art. 6(1)(f)
    personal_public_basis: str = "legitimate_interest"
    # sensitive (Art. 9) needs more than legitimate interest — effectively explicit consent you
    # will not have in cold outreach; excluded from outreach by default regardless of posture.
    sensitive_basis: str | None = None


class RetentionTtls(BaseModel):
    """Placeholder for personal-claim retention TTLs (Doc D §4) — *carried, not enforced* in M0.

    Personal claims carry a *shorter* freshness/retention TTL than firmographic facts (people
    change, and minimizing retained personal data shrinks risk). The aging-out machinery is
    later; here we only define the defaults the future retention sweep will read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    personal_claim_ttl: timedelta = timedelta(days=180)  # contact.facet.* and personal fields
    sensitive_claim_ttl: timedelta = timedelta(days=30)  # shortest — minimize sensitive retention
    professional_claim_ttl: timedelta = timedelta(days=365)


class JurisdictionPolicy(BaseModel):
    """Per-client jurisdiction/use-class/posture policy — the skeleton (data + defaults, no gate).

    Exposed via :func:`clue_research.config.get_policy`. Consumed (later) by M10 (the use-gate),
    M4 (posture-driven source-scope). Switching a client from Option 1 to Option 3 is a config
    write — it flips ``posture`` (and, derived, ``source_scope``) — never a code path (Doc D §6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    jurisdiction: Jurisdiction = DEFAULT_JURISDICTION
    posture: Posture = DEFAULT_POSTURE
    # The use-class allow-map for this client (one disposition per use-class). Defaults to the
    # conservative map; a client override replaces individual entries. The full
    # (use_class × jurisdiction) matrix the M10 gate reads is this map *parameterized by* the
    # client's resolved jurisdiction; M0 carries the per-client map and the jurisdiction key.
    allow_map: dict[UseClass, UseDisposition] = {
        UseClass.PROFESSIONAL_PUBLIC: UseDisposition.USABLE,
        UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: UseDisposition.USABLE,
        UseClass.SENSITIVE: UseDisposition.STORED_UNUSABLE,
    }
    lawful_basis_defaults: LawfulBasisDefaults = LawfulBasisDefaults()
    retention_ttls: RetentionTtls = RetentionTtls()

    @model_validator(mode="after")
    def _check_allow_map_complete(self) -> JurisdictionPolicy:
        """Every use-class must have a disposition; sensitive may never be silently usable."""
        missing = [uc for uc in UseClass if uc not in self.allow_map]
        if missing:
            raise ValueError(f"allow_map missing dispositions for use-classes: {missing}")
        # Hard guardrail the M10 gate relies on: sensitive special-category data is excluded
        # from outreach *by default regardless of posture* (Doc D §4). A client cannot make it
        # USABLE through config in this skeleton; the gate owner (M10) may add a reviewed
        # exception path with an explicit Art. 9 basis, but the default machinery forbids it.
        if self.allow_map[UseClass.SENSITIVE] is UseDisposition.USABLE:
            raise ValueError(
                "sensitive (special-category) data may not be marked USABLE in the policy "
                "skeleton — it is excluded from outreach by default (Doc D §4); use "
                "STORED_UNUSABLE or NOT_STORED"
            )
        return self

    @property
    def source_scope(self) -> SourceScope:
        """The collection-time source scope the posture drives (Doc D §6).

        Option 3 (professional-public-only) scopes research at the **source level** so the deep
        personal-life classes are never collected. Options 1 & 2 allow the full sweep and govern
        usability through the allow-map. This is *derived* from the posture — flipping the
        posture flips the scope with no separate config write, so a client moving to Option 3 is
        a single-field change (Doc D §6 "the posture becomes a configuration decision").
        """
        if self.posture is Posture.PROFESSIONAL_PUBLIC_ONLY:
            return SourceScope.PROFESSIONAL_PUBLIC_ONLY
        return SourceScope.FULL_SWEEP

    def disposition_for(self, use_class: UseClass) -> UseDisposition:
        """The configured disposition for a use-class (read by the M10 gate; not enforced here)."""
        return self.allow_map[use_class]
