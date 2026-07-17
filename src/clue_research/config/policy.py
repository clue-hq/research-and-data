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

Reuses :class:`clue_core.UseClass` (``professional-public | personal-public-non-sensitive
| sensitive``) — it is **not** re-defined here.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clue_core import UseClass


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


# --- use-class special-category lexicon (M10.2) ----------------------------
# The Art. 9 special-category markers (Doc D §2) the use-class tagger escalates on, plus the
# benign-cause markers that let a SENSITIVE-hinted "causes" field de-escalate. Authored as config
# (policy-as-data, conventions §2) so the Art. 9 set is editable WITHOUT code (M10.2 AC; D8) — the
# M8 tagger reads this lexicon instead of a hardcoded list. The set covers every Doc D §2 category:
# religion, politics, health/disability, sexual-orientation/ethnicity, trade-union,
# biometric/genetic, plus the reasonable-person-private extension (family/children, financial).
#
# A missed marker leaves the field at its declared hint — fail-*safe* only for a restrictive
# hint (``causes`` hints SENSITIVE), but fail-*open* for an escalatable field whose hint is usable
# (``stated_interests`` hints PERSONAL_PUBLIC_NON_SENSITIVE → an uncaught special-category interest
# stays usable). So the marker set must cover the Doc D §2 categories; substring recall is still
# best-effort, and adversarial/recall hardening belongs in the M9.6 eval battery. Matching is
# substring over lowercased text, so markers are kept lowercase + selective (no substrings of common
# benign words) to protect precision against the M8 behaviour tests.
_DEFAULT_SENSITIVE_MARKERS: tuple[str, ...] = (
    # religion
    "church",
    "mosque",
    "synagogue",
    "temple",
    "faith",
    "religious",
    "religion",
    "christian",
    "catholic",
    "muslim",
    "islam",
    "islamic",
    "jewish",
    "judaism",
    "hindu",
    "buddhist",
    "bible",
    "evangelical",
    "ministry",
    "parish",
    # politics
    "political",
    "politics",
    "republican",
    "democrat",
    "conservative party",
    "labour party",
    "campaign",
    "candidate",
    "election",
    "activist",
    "lobby",
    # health / disability
    "health condition",
    "medical",
    "disability",
    "disabled",
    "illness",
    "cancer",
    "disease",
    "mental health",
    "addiction",
    "recovery",
    "diagnosis",
    "patient advocacy",
    # sexual orientation / ethnicity
    "lgbt",
    "lgbtq",
    "gay rights",
    "queer",
    "ethnic",
    "racial",
    # trade-union membership (Art. 9) — selective phrases, not bare "union" (≈ reunion/communion)
    "trade union",
    "trade-union",
    "trade unionist",
    "union member",
    "labor union",
    "labour union",
    # biometric / genetic (Art. 9)
    "biometric",
    "genetic",
    "genome",
    "dna test",
    # family / children (reasonable-person-private) — selective, not bare "family"/"children"
    "pregnan",
    "my children",
    "my kids",
    "my son",
    "my daughter",
    "custody battle",
    "fertility",
    "ivf",
    # financial status (reasonable-person-private) — selective, not bare "debt"/"financial"/"loan"
    "bankruptcy",
    "insolvency",
    "foreclosure",
    "net worth",
    "in debt",
    "financial hardship",
)
# Markers that a "cause" is evidently benign (lets a SENSITIVE-hint field de-escalate per-claim).
_DEFAULT_BENIGN_CAUSE_MARKERS: tuple[str, ...] = (
    "environment",
    "climate",
    "wildlife",
    "conservation",
    "education",
    "literacy",
    "animal",
    "sports",
    "arts",
    "music",
    "open source",
    "open-source",
    "stem",
    "scholarship",
    "mentorship",
    "youth",
    "hunger",
    "homelessness",
)


class UseClassLexicon(BaseModel):
    """The versioned special-category lexicon the use-class tagger reads (Doc D §2; M10.2; D8).

    ``sensitive_markers`` are the Art. 9 special-category (+ reasonable-person-private) substrings
    whose presence in a claim's evidence/value escalates an *escalatable* personal field to
    ``SENSITIVE``; ``benign_cause_markers`` let a SENSITIVE-hinted ``causes`` field de-escalate when
    the cause is evidently benign. **Policy is data:** adding an Art. 9 category is a config edit,
    not code — the tagger consults this lexicon, never a hardcoded list (M10.2 AC). Matching is
    conservative and fails *safe* toward ``SENSITIVE`` (Doc D §2 "empty is correct").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sensitive_markers: tuple[str, ...] = _DEFAULT_SENSITIVE_MARKERS
    benign_cause_markers: tuple[str, ...] = _DEFAULT_BENIGN_CAUSE_MARKERS
    version: int = 1

    @field_validator("sensitive_markers", "benign_cause_markers", mode="before")
    @classmethod
    def _normalize_markers(cls, value: object) -> object:
        """Lower-case + strip every marker (matching is over lowercased text, so an upper-case
        custom marker would silently never fire) and **reject a blank marker** — an empty/whitespace
        marker substring-matches *everything*, which on the benign side would silently de-escalate
        every claim (the unsafe direction). Only runs for *provided* values; the defaults are clean.
        """
        if not isinstance(value, (list, tuple)):
            return value
        out: list[str] = []
        for raw in value:
            marker = str(raw).strip().lower()
            if not marker:
                raise ValueError(
                    "a use-class marker must be non-empty/non-whitespace — a blank marker matches "
                    "every claim (Doc D §2; the benign side would silently de-escalate everything)"
                )
            out.append(marker)
        return tuple(out)

    @model_validator(mode="after")
    def _check_sensitive_non_empty(self) -> UseClassLexicon:
        # An empty special-category set silently disables Art. 9 escalation — sensitive data must
        # fail *safe* toward SENSITIVE, so reject it (mirrors JurisdictionPolicy's sensitive floor).
        if not self.sensitive_markers:
            raise ValueError(
                "sensitive_markers must be non-empty: an empty special-category lexicon silently "
                "disables Art. 9 escalation; sensitive data must fail safe to SENSITIVE (Doc D §2)"
            )
        return self


DEFAULT_USE_CLASS_LEXICON = UseClassLexicon()


# --- region -> regime mapping (M10.1) --------------------------------------
# The strictest common regime — used whenever a contact's jurisdiction cannot be resolved (no
# location evidence, or a region the mapping does not cover). "Design for the strict (GDPR-grade)
# case and switch down" (Doc D §1): absence/ambiguity of evidence never *relaxes* governance, so the
# resolver fails closed to this regime rather than to a permissive default.
STRICT_DEFAULT_REGIME = Jurisdiction.GDPR

# Default ISO-3166 alpha-2 region -> regime. EU-27 + EEA (IS/LI/NO) -> GDPR; GB -> UK GDPR; US ->
# US state-privacy regime. This is a *starting* default authored as config (policy-as-data,
# conventions §2): the precise 2026 boundaries (US state granularity, adequacy decisions, the long
# tail of jurisdictions) are D8 and are changed by editing this map, never the resolver. Any region
# not listed resolves to STRICT_DEFAULT_REGIME (fail-closed), so an unlisted country is governed
# strictly rather than leniently.
_EU_EEA_REGIONS = (
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",  # EU-27
    "IS",
    "LI",
    "NO",  # EEA (GDPR applies)
)
_DEFAULT_REGION_REGIME: dict[str, Jurisdiction] = {
    **dict.fromkeys(_EU_EEA_REGIONS, Jurisdiction.GDPR),
    "GB": Jurisdiction.UK_GDPR,
    "UK": Jurisdiction.UK_GDPR,  # common non-ISO alias for GB
    "US": Jurisdiction.US_STATE,
}

# Common full-country-NAME → ISO alpha-2 aliases. Scraped/synthesized ``geo`` dicts (M8) frequently
# carry a country name ("Germany") rather than the ISO code ("DE"), so without this layer the
# resolver would fail closed to the strict default for most real contacts — safe but useless. This
# is a *curated, finite* set for the regions in the default mapping; an unlisted name still fails
# closed (never relaxes governance). Like the mapping itself it is policy-as-data (D8-extensible).
_DEFAULT_NAME_ALIASES: dict[str, str] = {
    "GERMANY": "DE",
    "FRANCE": "FR",
    "ITALY": "IT",
    "SPAIN": "ES",
    "NETHERLANDS": "NL",
    "THE NETHERLANDS": "NL",
    "IRELAND": "IE",
    "BELGIUM": "BE",
    "POLAND": "PL",
    "SWEDEN": "SE",
    "DENMARK": "DK",
    "FINLAND": "FI",
    "AUSTRIA": "AT",
    "PORTUGAL": "PT",
    "GREECE": "GR",
    "CZECHIA": "CZ",
    "CZECH REPUBLIC": "CZ",
    "ROMANIA": "RO",
    "HUNGARY": "HU",
    "CROATIA": "HR",
    "BULGARIA": "BG",
    "SLOVAKIA": "SK",
    "SLOVENIA": "SI",
    "LITHUANIA": "LT",
    "LATVIA": "LV",
    "ESTONIA": "EE",
    "LUXEMBOURG": "LU",
    "CYPRUS": "CY",
    "MALTA": "MT",
    "NORWAY": "NO",
    "ICELAND": "IS",
    "LIECHTENSTEIN": "LI",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "ENGLAND": "GB",
    "SCOTLAND": "GB",
    "WALES": "GB",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "USA": "US",
    "AMERICA": "US",
}


class RegimeMapping(BaseModel):
    """region -> data-protection :class:`Jurisdiction` regime — the M10.1 lookup table (Doc D §1;
    D8). **Policy is data:** adding/adjusting a regime is a config edit, not code.

    ``mapping`` is keyed by ISO-3166 alpha-2 codes; ``name_aliases`` maps common full country NAMES
    to those codes (scraped ``geo`` dicts often carry "Germany" rather than "DE"). ``region_keys``
    is the ordered set of keys the resolver probes in a contact/account ``geo`` dict (or a location
    claim's value) to find the region — geo dicts are loosely conventional (``country`` /
    ``country_code`` / ``region``) and carry no enforced schema. Lookups upper-case the region, try
    ``name_aliases`` then ``mapping``; a region matching neither returns ``None`` (the resolver then
    fails closed to ``STRICT_DEFAULT_REGIME`` — absence/ambiguity never relaxes governance).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping: dict[str, Jurisdiction] = dict(_DEFAULT_REGION_REGIME)
    name_aliases: dict[str, str] = dict(_DEFAULT_NAME_ALIASES)
    region_keys: tuple[str, ...] = ("country", "country_code", "region", "jurisdiction")

    def regime_for(self, region: str | None) -> Jurisdiction | None:
        """The regime for a region code or full country name, or ``None`` when empty/unmapped."""
        if region is None:
            return None
        normalized = region.strip().upper()
        if not normalized:
            return None
        code = self.name_aliases.get(normalized, normalized)
        return self.mapping.get(code)


DEFAULT_REGIME_MAPPING = RegimeMapping()


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
    # Pointer to the client's documented legitimate-interest balancing test (the LIA) — recorded as
    # provenance alongside a legitimate-interest claim by M10.5 so "why were we allowed to hold
    # this" cites the actual assessment. Per-client config (the LIA is the client's document); None
    # until the client supplies one (M10.5 records the basis with a null lia_ref, for the owner).
    lia_ref: str | None = None


class RetentionTtls(BaseModel):
    """Placeholder for personal-claim retention TTLs (Doc D §4) — *carried, not enforced* in M0.

    Personal claims carry a *shorter* freshness/retention TTL than firmographic facts (people
    change, and minimizing retained personal data shrinks risk). The aging-out machinery is
    later; here we only define the defaults the future retention sweep will read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    personal_claim_ttl: timedelta = timedelta(days=180)  # contact.facet.* and personal fields
    sensitive_claim_ttl: timedelta = timedelta(days=30)  # shortest — minimize sensitive retention
    # The longest-held personal class (professional B2B, legitimate interest), but still **strictly
    # shorter than the firmographic freshness TTL** (FreshnessTtls core = 365d) — Doc D §4 / M10.5:
    # "personal claims carry a *shorter* retention than firmographic facts". All three personal
    # horizons (sensitive 30d < personal 180d < professional 300d) are < 365d firmographic. (D8
    # config.)
    professional_claim_ttl: timedelta = timedelta(days=300)


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
    # --- use-class tagging input (M10.2) ---
    # The Art. 9 special-category lexicon the M8 tagger escalates on (Doc D §2). Carried on the
    # policy (like ``regime_mapping``) so it is per-client overlayable as policy-as-data; the api
    # composition root constructs ``UseClassTagger(lexicon=get_policy(cid).use_class_lexicon)`` when
    # wiring the M8 call site. Defaults to the conservative platform lexicon.
    use_class_lexicon: UseClassLexicon = DEFAULT_USE_CLASS_LEXICON
    # --- jurisdiction resolution inputs (M10.1) ---
    # The region->regime lookup the M10.1 JurisdictionResolver applies (Doc D §1; D8). A per-client
    # overlay can swap it without code (policy-as-data); note the ConfigOverlay whole-subtree
    # replace semantics — an overlay overriding ``policy`` must re-supply the whole policy.
    regime_mapping: RegimeMapping = DEFAULT_REGIME_MAPPING
    # The field-keys the resolver reads via ``current_value`` to find a contact's / the parent
    # account's location *claim* (provenance-backed, supersession-correct). Empty/absent fields are
    # read gracefully as "no claim" — the resolver then falls back to the resolved entity columns
    # (``ContactEntity.geo`` / ``AccountEntity.hq_geo``). M8/M1 own the location field-keys; M10
    # only *lists* which to consult, so adding one when M8 registers a field is a config change.
    contact_location_fields: tuple[str, ...] = ("contact.location",)
    account_location_fields: tuple[str, ...] = ("account.hq_location",)

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
