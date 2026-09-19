"""The company-identity resolver seam + the PDL implementation (W5/R3-A).

**The fixtures are the real wire shape.** ``tests/fixtures/company_identity/pdl_apollo.json`` is
the live vendor's own answer for ``apollo.io``, captured 2026-08-27 in the single sanity-check
call this work was permitted (one credit): the same top-level keys, the same string-typed
``linkedin_id``, the same scheme-less ``linkedin_url``, and the same pair of ``name`` /
``display_name`` spellings. Only the bulk enrichment fields nobody here reads are trimmed.

**That one live call is the whole reason this fixture can be trusted.** It also settled the
question the defect turns on: the vendor answers ``linkedin_id: "18511550"`` for apollo.io —
Apollo's true LinkedIn page, the one carrying 135 ads — while the ad library's own domain
resolution answers ``107285417``, a real page with none.

Nothing here touches the network. The resolver's transport is exercised only through its two
pure halves (``endpoint`` / ``parse_identity``), and an autouse guard refuses ``httpx`` outright
so a missed stub fails loudly instead of quietly spending a credit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lumen_ingestion.ad_library import (
    CompanyIdentity,
    CompanyIdentityCredentialsMissing,
    CompanyIdentityError,
    CompanyIdentityResolver,
    check_advertiser_names,
    company_name_key,
    resolve_company_identity_resolver,
)
from lumen_ingestion.ad_library.company_identity import (
    RESOLVER_AD_LIBRARY_DOMAIN,
    RESOLVER_EXPLICIT,
    RESOLVER_PDL,
    AdvertiserResolution,
)
from lumen_ingestion.ad_library.pdl import PdlCompanyIdentityResolver

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "company_identity"

#: The two page ids the R3-A defect is about. Named once so every test below reads as the story
#: it is really telling rather than as two arbitrary numbers.
APOLLO_TRUE_PAGE_ID = "18511550"
APOLLO_WRONG_PAGE_ID = "107285417"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this module may spend an enrichment credit."""
    import httpx

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "a company-identity test reached the network; the resolver's transport is never "
            "exercised here, only its two pure halves"
        )

    # ``Client`` is on the list since lane 3 slice 5: the lane's paid calls go through
    # ``clue_spend.HttpxTransport``, which builds an ``httpx.Client`` rather than calling the
    # module-level ``post``. Without it the guard would pass while the lane really dialled out.
    for name in ("get", "post", "request", "stream", "Client", "AsyncClient"):
        monkeypatch.setattr(httpx, name, refuse, raising=False)


@pytest.fixture
def resolver() -> PdlCompanyIdentityResolver:
    return PdlCompanyIdentityResolver(
        api_key="test-key", base_url="https://api.example.com"
    )


# --- credentials -----------------------------------------------------------------------------


def test_a_resolver_with_no_credentials_refuses_before_building_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED CASE: the absence has to be TYPED, and it has to happen at construction.

    Typed, because the lane branches on it — a missing key degrades to the ad library's own
    resolution, while a broken call is a different and noisier thing. At construction, because
    an enrichment costs a credit and a call already known to be unauthenticated is a call worth
    not making.
    """
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "pdl_api_key", "", raising=False)

    with pytest.raises(CompanyIdentityCredentialsMissing) as raised:
        resolve_company_identity_resolver()

    assert raised.value.code == "company_identity.credentials_missing"
    assert raised.value.variables == ("PDL_API_KEY",)
    # The message names the variable and NEVER its value.
    assert "PDL_API_KEY" in raised.value.message
    # It is a CompanyIdentityError too, so a caller that only wants "identity did not work"
    # catches one type.
    assert isinstance(raised.value, CompanyIdentityError)


def test_a_blank_key_of_pure_whitespace_is_still_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stray space in a .env is not a credential."""
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "pdl_api_key", "   ", raising=False)
    with pytest.raises(CompanyIdentityCredentialsMissing):
        resolve_company_identity_resolver()


def test_an_unknown_resolver_name_is_refused_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CompanyIdentityError) as raised:
        resolve_company_identity_resolver("clearbit")
    assert raised.value.code == "company_identity.unknown_resolver"


def test_the_configured_resolver_satisfies_the_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protocol is the contract; the implementation is an implementation detail."""
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "pdl_api_key", "test-key", raising=False)
    assert isinstance(resolve_company_identity_resolver(), CompanyIdentityResolver)


# --- the endpoint ----------------------------------------------------------------------------


def test_the_base_url_may_be_the_host_or_the_whole_endpoint() -> None:
    """RED CASE: the founder's own .env carries the full endpoint, the design named the host.

    Appending the enrichment path to the endpoint form would produce a doubled path, and a
    doubled path 404s — which this resolver reads as "no company matched". The whole lane would
    then fall back forever, silently, for a reason no log would name. That is the same
    quiet-misresolution shape R3-A is about, so both forms fold to one URL.
    """
    expected = "https://api.peopledatalabs.com/v5/company/enrich"
    for configured in (
        "https://api.peopledatalabs.com",
        "https://api.peopledatalabs.com/",
        "https://api.peopledatalabs.com/v5/company/enrich",
        "https://api.peopledatalabs.com/v5/company/enrich/",
        "  https://api.peopledatalabs.com/v5/company/enrich  ",
    ):
        built = PdlCompanyIdentityResolver(api_key="k", base_url=configured).endpoint
        assert built == expected, f"{configured!r} built {built!r}"


def test_an_operator_typed_domain_is_folded_to_a_bare_host() -> None:
    """``company_domain`` is typed by a human and arrives in whatever shape they typed it."""
    from lumen_ingestion.ad_library.pdl import _domain_of

    for typed in (
        "apollo.io",
        "APOLLO.IO",
        "www.apollo.io",
        "https://apollo.io",
        "https://www.apollo.io/pricing?utm=x",
    ):
        assert _domain_of(typed) == "apollo.io", typed


def test_resolving_a_blank_domain_is_refused_rather_than_asked(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """RED CASE: a credit spent on an empty question is a credit spent for nothing."""
    with pytest.raises(CompanyIdentityError) as raised:
        resolver.resolve("   ")
    assert raised.value.code == "company_identity.bad_request"


# --- parsing the vendor's real answer ----------------------------------------------------------


def test_the_real_apollo_record_yields_apollos_true_page_id(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """THE HEADLINE. This is the number the whole defect is about.

    The ad library resolves apollo.io to 107285417 — a real page with zero ads. The identity
    resolver answers 18511550, the page carrying 135. Captured live from the vendor.
    """
    identity = resolver.parse_identity("apollo.io", load("pdl_apollo"))

    assert identity is not None
    assert identity.linkedin_id == APOLLO_TRUE_PAGE_ID
    assert identity.linkedin_id != APOLLO_WRONG_PAGE_ID
    assert identity.name == "apollo.io"
    assert identity.linkedin_url == "linkedin.com/company/apolloio"
    assert identity.provider == "pdl"
    assert identity.addresses_a_page is True


def test_a_documented_not_found_is_an_answer_and_not_a_fault(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """The vendor saying "I have no record" must not turn into a red job.

    It is a typed absence: the lane falls back to the ad library's own resolution and records
    that nothing verified it. Raising here would make every unknown domain a failure.
    """
    assert resolver.parse_identity("nobody.example", load("pdl_not_found")) is None


def test_display_name_is_consulted_only_when_name_is_absent(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """`name` is the designed field and stays the one that decides."""
    both = resolver.parse_identity(
        "apollo.io", {"name": "apollo.io", "display_name": "Something Else"}
    )
    assert both is not None and both.name == "apollo.io"

    only_display = resolver.parse_identity("apollo.io", {"display_name": "Apollo.io"})
    assert only_display is not None and only_display.name == "Apollo.io"


def test_a_numeric_linkedin_id_is_carried_as_a_string(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """The vendor documents a string; a JSON number would make every id comparison in the lane
    quietly type-dependent, including the one that addresses the harvest."""
    identity = resolver.parse_identity("apollo.io", {"name": "Apollo", "linkedin_id": 18511550})
    assert identity is not None
    assert identity.linkedin_id == APOLLO_TRUE_PAGE_ID
    assert isinstance(identity.linkedin_id, str)


def test_a_record_naming_neither_a_company_nor_a_page_is_an_absence(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    assert resolver.parse_identity("x.example", {"status": 200, "website": "x.example"}) is None


def test_a_company_with_a_name_but_no_linkedin_page_is_kept_for_its_name(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    """A real record that cannot address a harvest can still gate custody."""
    identity = resolver.parse_identity("x.example", {"name": "Example Co"})
    assert identity is not None
    assert identity.addresses_a_page is False
    assert identity.name == "Example Co"


def test_a_non_object_body_is_a_typed_malformed_response(
    resolver: PdlCompanyIdentityResolver,
) -> None:
    with pytest.raises(CompanyIdentityError) as raised:
        resolver.parse_identity("apollo.io", ["not", "an", "object"])  # type: ignore[arg-type]
    assert raised.value.code == "company_identity.malformed_response"


# --- the name fold ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # The live pair: the vendor's `name` and LinkedIn's advertiser name are the SAME company
        # spelled two ways, and the fold is what makes the cross-check see that.
        ("apollo.io", "apolloio"),
        ("Apollo.io", "apolloio"),
        ("APOLLO . IO", "apolloio"),
        # Whitespace and case come from the base fold this builds on.
        ("  Ramp  ", "ramp"),
        ("RAMP", "ramp"),
        # Punctuation and trailing legal form are what R3-A added.
        ("Acme, Inc.", "acme"),
        ("Acme Incorporated", "acme"),
        ("Acme Holdings Ltd", "acme"),
        ("Acme GmbH", "acme"),
        # Absent, empty, and folds-away-to-nothing all answer None — an empty key must never be
        # allowed to compare equal to another empty key and call that a match.
        (None, None),
        ("", None),
        ("   ", None),
        ("Inc", None),
        ("!!!", None),
    ],
)
def test_the_company_name_fold(name: str | None, expected: str | None) -> None:
    assert company_name_key(name) == expected


def test_the_fold_does_not_collapse_two_different_companies() -> None:
    """The guard on the guard: a fold that tried harder would eventually match strangers."""
    assert company_name_key("Apollo") != company_name_key("Apollo Global Management")
    assert company_name_key("Ramp") != company_name_key("Ramp Network")
    assert company_name_key("Meta") != company_name_key("Metabase")


def test_the_base_fold_is_reused_and_left_unchanged() -> None:
    """R3-A promoted `harvest.normalize_name` rather than writing a second normalizer.

    The stronger fold layers ON TOP of it, so the thought-leader filter — which compares a
    person's name against a company's, and MUST stay strict — keeps its exact old behaviour.
    """
    from lumen_ingestion.ad_library.harvest import _normalize_name, normalize_name

    assert normalize_name is _normalize_name
    assert normalize_name("  Thought   Leader 1 ") == "thought leader 1"
    # Still strict where it has to be: the filter must not fold a person into the company.
    assert normalize_name("Ramp") != normalize_name("Ramp Employee")


# --- the advertiser cross-check ------------------------------------------------------------------


def _resolution(**kwargs: Any) -> AdvertiserResolution:
    base = {
        "resolver_used": RESOLVER_PDL,
        "linkedin_page_id": APOLLO_TRUE_PAGE_ID,
        "resolved_name": "apollo.io",
        "verified": True,
        "observed_page_id": APOLLO_TRUE_PAGE_ID,
    }
    base.update(kwargs)
    return AdvertiserResolution(**base)  # type: ignore[arg-type]


def test_the_live_spellings_agree() -> None:
    """The vendor says 'apollo.io'; LinkedIn's advertiser field says 'Apollo.io'. One company."""
    check = check_advertiser_names(
        ["Apollo.io", "Apollo.io"], expected="apollo.io", resolution=_resolution()
    )
    assert check.status == "ok"
    assert check.blocks_custody is False
    assert check.conflict is None


def test_a_stranger_blocks_custody_and_the_conflict_names_both_names_and_both_ids() -> None:
    """RED CASE, and the one the guard exists for.

    The quartet in the conflict sentence — both names, the page asked for, the page answered —
    is exactly what the W5 acceptance run had to reconstruct by hand across two rounds.
    """
    resolution = _resolution(
        linkedin_page_id=APOLLO_TRUE_PAGE_ID, observed_page_id=APOLLO_WRONG_PAGE_ID
    )
    check = check_advertiser_names(
        ["Seamless.AI"], expected="apollo.io", resolution=resolution
    )

    assert check.status == "mismatch"
    assert check.blocks_custody is True
    assert check.conflict is not None
    assert "Seamless.AI" in check.conflict
    assert "apollo.io" in check.conflict
    assert APOLLO_TRUE_PAGE_ID in check.conflict
    assert APOLLO_WRONG_PAGE_ID in check.conflict


def test_one_stranger_among_many_still_blocks_everything() -> None:
    """Keep NOTHING, not "keep the ones that matched".

    A page serving two advertisers is a page whose majority answer cannot be trusted, and a
    half-right reference library is the kind of wrong that only surfaces later, in an ad.
    """
    check = check_advertiser_names(
        ["Apollo.io", "Apollo.io", "Apollo.io", "Some Other Company"],
        expected="apollo.io",
        resolution=_resolution(),
    )
    assert check.blocks_custody is True
    assert "Some Other Company" in (check.conflict or "")


def test_no_expected_name_is_not_applicable_rather_than_a_silent_pass() -> None:
    """RED CASE: with nothing to compare, saying "they agreed" would be a lie.

    It must also not block — an unverifiable harvest is still a harvest, and the honest record
    is that the check did not run.
    """
    check = check_advertiser_names(
        ["Apollo.io"], expected=None, resolution=_resolution(resolved_name=None)
    )
    assert check.status == "not_applicable"
    assert check.blocks_custody is False
    assert check.observed == ("Apollo.io",)


def test_an_empty_harvest_cannot_be_a_mismatch() -> None:
    """Nothing kept is `empty`, never `advertiser_mismatch` — they mean opposite things."""
    check = check_advertiser_names([], expected="apollo.io", resolution=_resolution())
    assert check.status == "ok"
    assert check.blocks_custody is False


def test_a_legal_suffix_difference_is_not_a_conflict() -> None:
    """'Ramp' and 'Ramp Inc.' are one company; refusing the harvest over a corporate form
    would be the guard doing damage rather than work."""
    check = check_advertiser_names(
        ["Ramp"], expected="Ramp, Inc.", resolution=_resolution(resolved_name="Ramp, Inc.")
    )
    assert check.status == "ok"


def test_the_check_runs_the_same_on_every_resolution_path() -> None:
    """It is the UNIVERSAL guard: an unverified path is exactly where it matters most."""
    for used in (RESOLVER_PDL, RESOLVER_AD_LIBRARY_DOMAIN, RESOLVER_EXPLICIT):
        check = check_advertiser_names(
            ["Somebody Else"],
            expected="Apollo",
            resolution=_resolution(resolver_used=used, verified=used == RESOLVER_PDL),
        )
        assert check.blocks_custody is True, used
        assert used in (check.conflict or ""), used


def test_the_resolution_serializes_every_field_an_operator_needs() -> None:
    payload = _resolution(linkedin_url="linkedin.com/company/apolloio").to_json()
    assert payload == {
        "resolver_used": "pdl",
        "linkedin_page_id": APOLLO_TRUE_PAGE_ID,
        "linkedin_url": "linkedin.com/company/apolloio",
        "resolved_name": "apollo.io",
        "verified": True,
        "note": None,
        "observed_page_id": APOLLO_TRUE_PAGE_ID,
        # W-B3. Empty on a one-attempt harvest, which is almost all of them; the two-attempt
        # shape is proven end to end in `test_ad_assets_advertiser_resolution`.
        "attempts": [],
    }


def test_a_company_identity_is_frozen() -> None:
    """Provenance that a later step could edit is not provenance."""
    identity = CompanyIdentity(
        domain="apollo.io",
        name="apollo.io",
        linkedin_id=APOLLO_TRUE_PAGE_ID,
        linkedin_url=None,
        provider="pdl",
    )
    with pytest.raises(Exception):
        identity.linkedin_id = APOLLO_WRONG_PAGE_ID  # type: ignore[misc]


# --- the vendor seam ------------------------------------------------------------------------------


def test_no_module_outside_the_resolver_names_the_identity_vendor() -> None:
    """The same D3 discipline the ad-library provider is held to, for the same reason.

    A textual guard rather than a reading: the value of the seam is that a second identity
    source (a CRM, a hand-curated table) is a new file and not a grep-and-replace.
    """
    api_root = Path(__file__).resolve().parents[1]
    allowed = {
        "lumen_ingestion/ad_library/pdl.py",
        "lumen_ingestion/ad_library/company_identity.py",
        # The package docstring records which resolver v1 ships and where the seam is; that is
        # documentation of the boundary, not a caller reaching across it.
        "lumen_ingestion/ad_library/__init__.py",
    }
    offenders = []
    for path in sorted(
        [*(api_root / "lumen_api").rglob("*.py"), *(api_root / "lumen_ingestion").rglob("*.py")]
    ):
        relative = str(path.relative_to(api_root))
        if relative in allowed:
            continue
        text = path.read_text().lower()
        if "peopledatalabs" in text or "people data labs" in text:
            offenders.append(relative)
    assert not offenders, f"these modules name the v1 identity vendor directly: {offenders}"


def test_the_fallback_label_does_not_name_the_fetch_vendor() -> None:
    """R3-A's design sketched `adyntel_domain`; that spelling would breach the D3 seam.

    The fact being recorded is "the ad library resolved this itself", which stays true of
    whichever library answered — so the label says that instead, and a future Meta or Google
    fetcher does not turn every stored job row into a lie.
    """
    assert RESOLVER_AD_LIBRARY_DOMAIN == "ad_library_domain"
    assert "adyntel" not in RESOLVER_AD_LIBRARY_DOMAIN
