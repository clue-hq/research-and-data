"""The company-identity resolver seam (W5/R3-A) — who is this domain, verifiably.

**The defect this exists for.** The lane used to hand the advertiser's identity to the ad
library and accept whatever came back. For ``apollo.io`` the vendor's own domain resolution
answered LinkedIn page ``107285417`` — a real page, with genuinely zero ads — while Apollo's
true page is ``18511550`` (135 ads, confirmed against LinkedIn's own ad library). The harvest
was empty, the job was green, the resolved id never reached the caller, and two full rounds of
acceptance testing were spent chasing a number the pipeline never showed anyone.

So identity is now resolved FIRST, by a party that is not the ad library, and the harvest is
then addressed by the id that resolution produced. Two independent sources have to agree about
who the advertiser is before a single creative is kept.

**The shape of the seam mirrors the ad-library provider pair exactly**, for the same reasons:
this module declares the protocol and the typed failures and names no vendor; ``pdl`` is the
one v1 implementation, reached only through :func:`resolve_company_identity_resolver`. A second
identity source (Clearbit, a CRM, a hand-curated table) is a new implementation plus a line in
the factory — never a change to onboarding.

**Absence is typed, and it is not a failure.** Three different things can happen and the lane
must tell them apart: the resolver is not configured (no key), the resolver answered "I do not
know this domain", and the resolver broke. The first two are ordinary states of the world that
fall back to the vendor's own resolution; only the third is worth a raised error, and even that
one the lane catches and degrades from. What must NEVER happen is the fallback pretending to be
verified — which is what :attr:`AdvertiserResolution.verified` and its ``note`` are for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

from .harvest import normalize_name

__all__ = [
    "AdvertiserNameCheck",
    "AdvertiserResolution",
    "CompanyIdentity",
    "CompanyIdentityCredentialsMissing",
    "CompanyIdentityError",
    "CompanyIdentityResolver",
    "RESOLVER_AD_LIBRARY_DOMAIN",
    "RESOLVER_EXPLICIT",
    "RESOLVER_PDL",
    "RESOLVER_PDL_THEN_AD_LIBRARY_DOMAIN",
    "check_advertiser_names",
    "company_name_key",
    "resolve_company_identity_resolver",
]

JsonObject = dict[str, Any]

#: The three ways this lane can come to believe it knows who the advertiser is. Stamped into
#: the job's evidence and lifted into its DTO, so an operator never has to infer which one
#: happened — the R3-A complaint was precisely that they could not.
#:
#: The fallback label is ``ad_library_domain`` and NOT the v1 fetch vendor's name, which the
#: R3-A design sketched. Naming the vendor here would breach the D3 seam that
#: ``test_no_module_outside_the_provider_package_names_the_vendor`` enforces — and it would
#: also become a lie the moment a Meta or Google fetcher ships, because the fact being recorded
#: is "the ad library resolved this itself", which is true of whichever library answered.
RESOLVER_PDL = "pdl"
RESOLVER_AD_LIBRARY_DOMAIN = "ad_library_domain"
RESOLVER_EXPLICIT = "explicit"

#: W-B3 adds a FOURTH label, for a harvest that took two attempts to find an advertiser.
#:
#: The identity resolver can name a page that genuinely exists and genuinely belongs to the
#: company, and STILL be the wrong page to harvest: for ``cursor.com`` it answered the legal
#: entity's page (105610681, zero ads) while the advertiser's page carried 4489. That is a
#: different failure from R3-A's — nothing was misresolved, the company simply advertises from
#: a page other than the one its enrichment record names — and it is invisible to every check
#: the lane already has, because an empty page is an honest answer.
#:
#: So when a ``pdl``-resolved page holds NO ADS AT ALL, the harvest is retried once against the
#: ad library's own domain resolution. This label records that it took both, and it is
#: deliberately NOT ``pdl``: the creatives came from a page nothing independent verified, which
#: is exactly what ``ad_library_domain`` has always meant, so it cannot borrow the verified
#: path's word. Compound rather than plain so the first attempt does not vanish from the record.
RESOLVER_PDL_THEN_AD_LIBRARY_DOMAIN = "pdl_then_ad_library_domain"


class CompanyIdentityError(RuntimeError):
    """A typed identity-resolution failure. ``code`` is the stable, loggable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CompanyIdentityCredentialsMissing(CompanyIdentityError):
    """The configured identity resolver has no credentials in the environment.

    Raised at construction, before any request is built — the same discipline as
    :class:`~.provider.AdLibraryCredentialsMissing`, for the same reason: an enrichment call
    costs a credit, and a call already known to be unauthenticated is a call worth not making.
    The message names the environment variables and never their values.

    Unlike the ad-library case this is NOT fatal to the job. The lane catches it and falls back
    to the vendor's own domain resolution, recording honestly that nothing verified the answer.
    A deployment with no identity key behaves exactly as the lane did before R3-A — no worse,
    and no longer pretending to be better.
    """

    def __init__(self, provider: str, variables: tuple[str, ...]) -> None:
        super().__init__(
            "company_identity.credentials_missing",
            f"the {provider} company-identity resolver needs {' and '.join(variables)} set in "
            "the environment; credentials are never read from code or from the repository",
        )
        self.provider = provider
        self.variables = variables


@dataclass(frozen=True)
class CompanyIdentity:
    """What an identity resolver knows about one domain.

    Every field is optional because a real enrichment record routinely is: a company can be
    known by name and carry no LinkedIn presence at all. A resolution with no ``linkedin_id``
    is therefore a legitimate answer and NOT an error — it simply cannot address a harvest, so
    the lane falls back while keeping the ``name`` it did learn, which is still worth having
    because the advertiser cross-check can use it.
    """

    domain: str
    name: str | None
    linkedin_id: str | None
    linkedin_url: str | None
    provider: str

    @property
    def addresses_a_page(self) -> bool:
        """True when this identity can actually re-address the harvest."""
        return bool(self.linkedin_id)


@runtime_checkable
class CompanyIdentityResolver(Protocol):
    """Resolve one company domain to its canonical name and LinkedIn page.

    One domain, one call, one credit — batching is deliberately not in the seam. The lane
    resolves exactly one advertiser per job, and a batch API would invite a caller to spend
    credits on domains no harvest asked about.

    ``resolve`` returns ``None`` for "this resolver does not know this domain" (a typed
    absence, not an exception) and raises :class:`CompanyIdentityError` when the call itself
    failed. The distinction matters to the caller: the first is an answer, the second is a
    missing answer, and only one of them is worth mentioning as a fault.
    """

    #: The stable resolver label stamped into the job's resolution provenance.
    name: str

    def resolve(self, domain: str) -> CompanyIdentity | None: ...


def resolve_company_identity_resolver(name: str = RESOLVER_PDL) -> CompanyIdentityResolver:
    """The one place an identity vendor is named. Raises for an unknown resolver, loudly.

    Raises :class:`CompanyIdentityCredentialsMissing` when the resolver exists but is not
    configured — the caller distinguishes "not built" (a bug) from "not configured" (a
    deployment fact it degrades from) by catching the subclass.

    Imported lazily so this module — the seam every other module imports — never pulls a
    concrete vendor (or its transport) into a process that only wanted the types.
    """
    if name == RESOLVER_PDL:
        from .pdl import PdlCompanyIdentityResolver

        return PdlCompanyIdentityResolver()
    raise CompanyIdentityError(
        "company_identity.unknown_resolver",
        f"no company-identity resolver named {name!r} is registered (v1 ships 'pdl')",
    )


@dataclass(frozen=True)
class AdvertiserResolution:
    """How this harvest came to address the advertiser it addressed — the R3-A provenance.

    This is the block the W5 report asked for in as many words: "surface the resolved
    ``page_id`` + ``advertiser_name`` in the job DTO". It rides the job's evidence AND is
    lifted into the polled DTO next to the R2-C outcome, because an operator who cannot see
    which page was harvested cannot tell a right answer from a wrong one.

    ``verified`` is the load-bearing field and it is deliberately narrow: it is true only when
    an identity source INDEPENDENT of the ad library named the page. The vendor agreeing with
    itself is not verification, and neither is an operator's hand-typed id — the latter is an
    assertion, which is a different and weaker thing, so it gets its own resolver label rather
    than being folded in with the verified case.
    """

    resolver_used: str
    linkedin_page_id: str | None = None
    linkedin_url: str | None = None
    resolved_name: str | None = None
    verified: bool = False
    note: str | None = None
    #: The page the ad library actually answered with, which is NOT necessarily the page that
    #: was asked for — on the fallback path it is the vendor's own resolution, and comparing
    #: the two is exactly how R3-A was eventually found.
    observed_page_id: str | None = None
    #: W-B3: every page the harvest actually asked for, in order, with what came back. Usually
    #: one entry; two when a resolved page held no ads and the domain retry ran. It exists
    #: because the compound outcome above collapses two facts into one word, and an operator
    #: diagnosing "why did this brand harvest from an unverified page" needs BOTH — the page
    #: the identity resolver named and found empty, and the page the retry read instead.
    #: Bounded by construction: at most two entries, each four scalars.
    attempts: tuple[JsonObject, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "resolver_used": self.resolver_used,
            "linkedin_page_id": self.linkedin_page_id,
            "linkedin_url": self.linkedin_url,
            "resolved_name": self.resolved_name,
            "verified": self.verified,
            "note": self.note,
            "observed_page_id": self.observed_page_id,
            "attempts": [dict(attempt) for attempt in self.attempts],
        }


@dataclass(frozen=True)
class AdvertiserNameCheck:
    """The universal custody gate: do the harvested ads belong to the company we resolved?

    Runs on EVERY path — verified, fallback and operator-asserted alike — because the failure
    it catches (harvesting a stranger's ads into a brand's reference library) is worse than an
    empty lane on all three. ``not_applicable`` is an honest third state rather than a silent
    pass: with no expected name there is nothing to compare, and saying so is not the same as
    saying the names agreed.
    """

    status: str
    expected: str | None = None
    observed: tuple[str, ...] = ()
    conflict: str | None = None

    @property
    def blocks_custody(self) -> bool:
        return self.status == "mismatch"

    def to_json(self) -> JsonObject:
        return {
            "status": self.status,
            "expected": self.expected,
            "observed": list(self.observed),
            "conflict": self.conflict,
        }


#: Corporate form suffixes stripped before two company names are compared. The list is
#: deliberately short and boring: every entry is a legal-form token that carries no identifying
#: information, so removing it can only ever make a TRUE match findable — it cannot invent one
#: between two genuinely different companies (no two distinct brands differ only by "ltd").
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "lp",
        "llp",
        "ltd",
        "limited",
        "plc",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "bv",
        "nv",
        "ab",
        "oy",
        "as",
        "pty",
        "srl",
        "spa",
        "kk",
        "holdings",
        "holding",
        "group",
    }
)

_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_UNDERSCORES = re.compile(r"_+")


def company_name_key(name: str | None) -> str | None:
    """The comparison key for one company name: casefolded, unpunctuated, de-suffixed.

    Built ON TOP of :func:`~.harvest.normalize_name` rather than beside it. That helper is the
    subsystem's existing name normalizer and it is what the harvest's thought-leader filter
    compares with, so reusing it keeps the two from drifting — and, just as importantly, leaves
    the filter's own behaviour byte-identical, because this function adds its extra folding
    here instead of inside the shared base.

    The extra folding is the two things the R3-A design named: punctuation goes (so "Apollo.io"
    and "Apollo io" are one name) and trailing legal-form tokens go (so "Ramp" matches "Ramp
    Business Corporation" as far as its corporate form is concerned). Nothing else — a fold
    that guessed harder would eventually decide two different companies were one, which is the
    exact failure this whole check exists to prevent.

    Returns ``None`` for absent-or-empty input, and for a name that folds away to nothing (a
    string of punctuation, or the bare word "Inc"), because an empty key must never be allowed
    to compare equal to another empty key and call it a match.
    """
    base = normalize_name(name)
    if base is None:
        return None
    stripped = _UNDERSCORES.sub(" ", _PUNCTUATION.sub(" ", base))
    tokens = stripped.split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return "".join(tokens) or None


def check_advertiser_names(
    observed: Iterable[str | None],
    *,
    expected: str | None,
    resolution: AdvertiserResolution,
) -> AdvertiserNameCheck:
    """Compare the harvested ads' advertiser names against the name we resolved.

    Every distinct observed name must match. A page that served two advertisers is not a page
    whose majority answer can be trusted — the minority ads are somebody else's creatives, and
    "mostly the right brand" is not a standard a reference library can be built on.

    The ``conflict`` sentence names BOTH names and BOTH page ids, because that quartet is
    exactly what a human needs to diagnose the failure and is exactly what the W5 acceptance
    run had to reconstruct by hand over two rounds.
    """
    expected_key = company_name_key(expected)
    seen: list[str] = []
    for name in observed:
        text = (name or "").strip()
        if text and text not in seen:
            seen.append(text)

    if expected_key is None:
        return AdvertiserNameCheck(
            status="not_applicable",
            expected=expected,
            observed=tuple(seen),
            conflict=None,
        )

    disagreeing = [name for name in seen if company_name_key(name) != expected_key]
    if not disagreeing:
        return AdvertiserNameCheck(status="ok", expected=expected, observed=tuple(seen))

    asked = resolution.linkedin_page_id or "(none — the vendor resolved the domain itself)"
    answered = resolution.observed_page_id or "(none reported)"
    conflict = (
        f"the harvested ads are advertised by {', '.join(repr(n) for n in disagreeing)}, but "
        f"the advertiser resolved to {expected!r} via {resolution.resolver_used}; "
        f"page asked for: {asked}; page the ad library answered with: {answered}. "
        "Nothing was kept — a reference library must not be built from another company's ads."
    )
    return AdvertiserNameCheck(
        status="mismatch",
        expected=expected,
        observed=tuple(seen),
        conflict=conflict,
    )
