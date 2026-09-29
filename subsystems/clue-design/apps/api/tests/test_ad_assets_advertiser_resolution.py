"""Verified LinkedIn resolution through the whole onboarding job (W5/R3-A).

**The defect, in one line:** the lane asked the ad library to resolve ``apollo.io`` and believed
the answer. The vendor returned page ``107285417`` — real, and carrying zero ads — while
Apollo's true page is ``18511550`` with 135. The harvest came back empty, the job reported
success, and the resolved id never reached the caller, so two full rounds of W5 acceptance
testing were spent chasing a number the pipeline never showed anyone.

Every test here drives the REAL job function. The ad library is a stub that reproduces the
vendor's actual behaviour — it resolves the domain to the wrong page and serves nothing from
it, while serving Apollo's ads from the right one — so "the harvest went to the right page" is
a claim about the pipeline's selector and not about a fixture's generosity.

The helpers are imported from :mod:`test_ad_assets_onboarding` rather than copied, so the two
suites can never drift on what a seeded brand kit or a stubbed image model is.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from json import dumps as json_dumps
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumen_ingestion.ad_library.company_identity import (
    CompanyIdentity,
    CompanyIdentityError,
)
from lumen_ingestion.ad_library.provider import AdLibraryAd, AdLibraryPage
from py_lumen_config import settings
from test_ad_assets_onboarding import (
    BRAND_KIT_VERSION,
    _client,
    _evidence,
    _fetch_creative,
    _seed_brand_kit,
    _stub_generate,
    _StubDistiller,
)

#: The two page ids the defect is about, verified against LinkedIn's own ad library (R3) and
#: against the identity vendor (one live call, 2026-08-27).
APOLLO_TRUE_PAGE_ID = "18511550"
APOLLO_WRONG_PAGE_ID = "107285417"


def _ad(ad_id: str, advertiser: str, url: str) -> AdLibraryAd:
    return AdLibraryAd(
        ad_id=ad_id,
        kind="image",
        creative_type="SPONSORED_STATUS_UPDATE",
        advertiser_name=advertiser,
        advertiser_promoted=True,
        image_url=url,
        image_alt_text=None,
        headline_title="Run outbound from your AI chats",
        headline_description=None,
        commentary_text=None,
        view_details_link=f"https://www.linkedin.com/ad-library/detail/{ad_id}",
        has_carousel=False,
    )


def _page(page_id: str, ads: tuple[AdLibraryAd, ...]) -> AdLibraryPage:
    return AdLibraryPage(
        page_id=page_id,
        # R3-C: `total_ads` is unreliable (the Ramp control answered 0 while carrying 24), so
        # the stub carries a deliberately wrong value. Nothing may branch on it.
        total_ads=0,
        ads=ads,
        continuation_token=None,
        is_last_page=True,
        provider="stub-library",
    )


class _ApolloLibrary:
    """The ad library, behaving exactly as the real one did on 2026-08-26.

    Asked for a DOMAIN it answers its own resolution — page 107285417, with nothing on it.
    Asked for page 18511550 it serves Apollo's real ads. That asymmetry is the defect, modelled;
    it is what makes "the pipeline reached the right page" a testable claim.
    """

    name = "stub-library"

    #: Which page a page_id request is served from. Anything unknown answers empty.
    def __init__(self, *, ads_by_page: dict[str, tuple[AdLibraryAd, ...]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._ads_by_page = ads_by_page or {
            APOLLO_TRUE_PAGE_ID: tuple(
                _ad(f"155438273{n}", "Apollo.io", f"https://cdn.example/apollo-{n}.jpg")
                for n in range(4)
            )
        }

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        self.calls.append(kwargs)
        page_id = kwargs.get("page_id")
        if page_id:
            return _page(page_id, self._ads_by_page.get(page_id, ()))
        # The vendor's own domain resolution — a real page id, and nothing behind it.
        return _page(APOLLO_WRONG_PAGE_ID, self._ads_by_page.get(APOLLO_WRONG_PAGE_ID, ()))


class _StubIdentityResolver:
    """An identity source that knows Apollo's real page — the live vendor's actual answer."""

    name = "stub-identity"

    def __init__(self, identity: CompanyIdentity | None = None) -> None:
        self.calls: list[str] = []
        self._identity = (
            identity
            if identity is not None
            else CompanyIdentity(
                domain="apollo.io",
                name="apollo.io",
                linkedin_id=APOLLO_TRUE_PAGE_ID,
                linkedin_url="linkedin.com/company/apolloio",
                provider="stub-identity",
            )
        )

    def resolve(self, domain: str) -> CompanyIdentity | None:
        self.calls.append(domain)
        return self._identity


class _UnknownDomainResolver:
    """A configured resolver that simply has no record of this domain."""

    name = "stub-identity"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, domain: str) -> CompanyIdentity | None:
        self.calls.append(domain)
        return None


class _BrokenIdentityResolver:
    """The vendor is down. A harvest that would otherwise work must not be lost to this."""

    name = "stub-identity"

    def resolve(self, domain: str) -> CompanyIdentity | None:
        raise CompanyIdentityError(
            "company_identity.transport_error", "ConnectError: the resolver is unreachable"
        )


@pytest.fixture
def lane_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)


@pytest.fixture(autouse=True)
def _no_embedded_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offer the job, then drive it here — with nothing else able to claim it first.

    Every test in this module offers through the real route (which writes the job row AND its
    fleet task) and then drives the real runner directly with injected stubs. The app's embedded
    fleet worker would otherwise race that drive for the same task and sometimes win — and when
    it wins it runs the job with the PRODUCTION ad-library provider, which has no credentials in
    a test process, so the job dies on `AdLibraryCredentialsMissing` and the assertion that
    fails is about advertiser resolution. That is a wrong answer to the right question, and it
    is intermittent, which is worse.

    The subject of this module is the pipeline, not the queue. The dispatch half — that an
    `ad_assets` job routes to the right runner under the same lease and fence as every other
    design job — is covered by `test_the_fleet_worker_executes_an_ad_assets_job`, which is the
    one test that genuinely wants a worker.
    """
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five external systems, five injected stubs — asserted, not assumed.

    The identity resolver's credential is blanked as well as its transport refused. R3-A's
    resolution step degrades rather than raising, so a refused request would be swallowed into
    a fallback and the loud guard would go unheard; with no key the production resolver is never
    constructed, and every test that wants one injects it explicitly.
    """
    import httpx

    monkeypatch.setattr(settings, "pdl_api_key", "", raising=False)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "an advertiser-resolution test reached the network; every external call in this "
            "lane is an injected seam and one of them was missed"
        )

    # ``Client`` is on the list since lane 3 slice 5: the lane's paid calls go through
    # ``clue_spend.HttpxTransport``, which builds an ``httpx.Client`` rather than calling the
    # module-level ``post``. Without it the guard would pass while the lane really dialled out.
    for name in ("get", "post", "request", "stream", "Client", "AsyncClient"):
        monkeypatch.setattr(httpx, name, refuse, raising=False)


def _offer(client: TestClient, body: dict) -> str:
    offered = client.post("/brand-ad-assets/onboard", json=body)
    assert offered.status_code == 200, offered.text
    job_id: str = offered.json()["job"]["job_id"]
    return job_id


def _run(
    client: TestClient,
    tmp_path: Path,
    *,
    request_body: dict,
    provider: Any,
    identity_resolver: Any = None,
) -> dict:
    """Offer one job through the real route, drive the real runner, return the terminal row."""
    from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding

    job_id = _offer(client, request_body)
    run_ad_assets_onboarding(
        str(tmp_path / "engine-cache" / client.headers["X-Workspace-Id"]),
        job_id,
        workspace_id=client.headers["X-Workspace-Id"],
        provider=provider,
        identity_resolver=identity_resolver,
        distiller=_StubDistiller(),
        generate=_stub_generate,
        fetch_creative=_fetch_creative,
        now=lambda: datetime(2026, 8, 27, tzinfo=UTC),
    )
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    job["evidence"] = _evidence(client, job_id)
    return job


def _body(brand_kit_id: str, **overrides: Any) -> dict:
    body = {
        "brand_kit_id": brand_kit_id,
        "brand_kit_version": BRAND_KIT_VERSION,
        "company_domain": "apollo.io",
        "max_pages": 1,
        "max_creatives": 4,
    }
    body.update(overrides)
    return body


# --- the headline red case ---------------------------------------------------------------------


def test_the_pre_fix_selector_reaches_the_wrong_page_and_finds_nothing(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE, proving the stub is not rigged: the OLD path really did fail this way.

    Before R3-A the lane passed ``company_domain`` straight through to the ad library. Driven
    that way, the same stub the next test uses answers page 107285417 with zero ads — which is
    precisely what the real vendor did, and precisely why the W5 harvest was empty.
    """
    from lumen_ingestion.ad_library.harvest import fetch_pages, select_creatives

    library = _ApolloLibrary()
    pages = fetch_pages(library, company_domain="apollo.io", page_id=None, max_pages=1)

    assert library.calls == [
        {
            "company_domain": "apollo.io",
            "page_id": None,
            "continuation_token": None,
            "date_filter": None,
        }
    ]
    assert pages[0].page_id == APOLLO_WRONG_PAGE_ID
    assert pages[0].ads == ()
    assert select_creatives(pages).kept == (), "the wrong page has nothing on it — the W5 empty"


def test_the_harvest_is_addressed_by_the_verified_page_and_not_the_vendors_guess(
    tmp_path: Path, lane_on: None
) -> None:
    """THE FIX. Identity is resolved first, and the harvest goes where resolution pointed.

    Same request, same ad library, same domain. The only difference from the red case above is
    that something other than the ad library was asked who apollo.io is.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary()
    identity = _StubIdentityResolver()

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=library,
        identity_resolver=identity,
    )

    assert identity.calls == ["apollo.io"], "identity is resolved BEFORE the library is asked"
    # The selector is the whole point: the resolved id went on the wire, the domain did not.
    assert library.calls[0]["page_id"] == APOLLO_TRUE_PAGE_ID
    assert library.calls[0]["company_domain"] is None
    assert all(call["page_id"] != APOLLO_WRONG_PAGE_ID for call in library.calls)

    assert job["status"] == "succeeded", job
    assert job["evidence"]["steps"]["harvest"]["kept"] == 4
    assert job["evidence"]["steps"]["custody"]["custodied"] == 4

    outcome = job["outcome"]
    assert outcome["status"] == "ok"
    assert outcome["resolver_used"] == "pdl"
    assert outcome["linkedin_page_id"] == APOLLO_TRUE_PAGE_ID
    assert outcome["advertiser_verified"] is True
    assert outcome["advertiser_conflict"] is None

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert len(lane["creatives"]) == 4
    assert lane["creatives"][0]["provenance"]["advertiser_page_id"] == APOLLO_TRUE_PAGE_ID


# --- provenance reaches the caller ---------------------------------------------------------------


def test_the_polled_dto_carries_the_resolution_alongside_the_outcome(
    tmp_path: Path, lane_on: None
) -> None:
    """R3-A's minimum ask: surface the resolved page id where an operator can actually see it.

    The whole cost of this defect was that the number lived nowhere a caller could reach. It now
    rides the documented endpoint, next to the R2-C outcome member and still without exposing
    the evidence body.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=_ApolloLibrary(),
        identity_resolver=_StubIdentityResolver(),
    )

    resolution = job["resolution"]
    assert resolution is not None, "the polled DTO must carry it, not bury it"
    assert resolution["resolver_used"] == "pdl"
    assert resolution["linkedin_page_id"] == APOLLO_TRUE_PAGE_ID
    assert resolution["observed_page_id"] == APOLLO_TRUE_PAGE_ID
    assert resolution["linkedin_url"] == "linkedin.com/company/apolloio"
    assert resolution["resolved_name"] == "apollo.io"
    assert resolution["verified"] is True

    # The durable row and the DTO tell the same story, and neither leaks the bodies.
    assert job["evidence"]["resolution"] == resolution
    assert "evidence" not in {k for k in job if k == "request"}
    # The human-readable stage names the page too.
    assert APOLLO_TRUE_PAGE_ID in job["stage"]
    assert "verified" in job["stage"]


def test_the_older_ingestion_kinds_gain_a_resolution_field_and_lose_nothing() -> None:
    """`ingestion_job_dto` is shared by all four kinds; only this lane composes a resolution."""
    from lumen_api.dto import ingestion_job_dto

    dto = ingestion_job_dto(
        {
            "job_id": "ingest_x",
            "kind": "website",
            "status": "succeeded",
            "stage": None,
            "progress": 1.0,
            "request": {"secret_staged_digest": "do-not-leak"},
            "evidence": {"schema_version": 1, "colors": ["#fff"]},
            "error": None,
            "created_at": "2026-08-27T00:00:00Z",
            "updated_at": "2026-08-27T00:00:00Z",
        }
    )
    assert dto["resolution"] is None
    assert dto["outcome"] is None
    assert "evidence" not in dto and "request" not in dto


# --- the universal custody guard -----------------------------------------------------------------


def test_an_advertiser_mismatch_keeps_nothing_and_names_the_conflict(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE: resolution pointed at a page, and the page served somebody else's ads.

    Nothing is custodied — not even the ads, not even partially — and the top-line outcome names
    both companies and both page ids so the failure is diagnosable from one poll instead of two
    rounds of forensics.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_TRUE_PAGE_ID: tuple(
                _ad(f"999000{n}", "Seamless.AI", f"https://cdn.example/seamless-{n}.jpg")
                for n in range(3)
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=library,
        identity_resolver=_StubIdentityResolver(),
    )

    assert job["status"] == "succeeded", "a refusal is not a crash"
    steps = job["evidence"]["steps"]
    assert steps["harvest"]["status"] == "advertiser_mismatch"
    assert steps["harvest"]["kept"] == 0
    assert steps["harvest"]["advertiser_check"]["status"] == "mismatch"
    assert "custody" not in steps, "KEEP NOTHING — custody was never reached"
    assert "record" not in steps

    outcome = job["outcome"]
    # NOT `empty`. An empty lane means the brand has no ads; this means ads were found and
    # REFUSED, and conflating the two is the exact mistake R3 spent two rounds making.
    assert outcome["status"] == "advertiser_mismatch"
    assert outcome["creatives_kept"] == 0
    assert outcome["creatives_custodied"] == 0
    conflict = outcome["advertiser_conflict"]
    assert conflict is not None
    assert "Seamless.AI" in conflict and "apollo.io" in conflict
    assert APOLLO_TRUE_PAGE_ID in conflict
    assert "Seamless.AI" in outcome["summary"]

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert lane["creatives"] == [], "not one stranger's creative entered the library"
    assert lane["card"] is None


CONDUIT_PAGE_ID = "96574094"


def _conduit_library() -> _ApolloLibrary:
    """Conduit's real page shape (2026-09-29): one executive's promoted posts outnumber the
    company's own ads. Both are paid for by Conduit's page; only the company's go to the library."""
    executive = tuple(
        _ad(f"5100{n}", "Cole Rubin", f"https://cdn.example/cole-{n}.jpg") for n in range(5)
    )
    company = tuple(
        _ad(f"5200{n}", "Conduit", f"https://cdn.example/conduit-{n}.jpg") for n in range(2)
    )
    return _ApolloLibrary(ads_by_page={CONDUIT_PAGE_ID: executive + company})


def _conduit_identity() -> _StubIdentityResolver:
    return _StubIdentityResolver(
        CompanyIdentity(
            domain="conduit.ai",
            name="conduit",
            linkedin_id=CONDUIT_PAGE_ID,
            linkedin_url="linkedin.com/company/useconduitai",
            provider="stub-identity",
        )
    )


def test_left_to_guess_the_filter_takes_the_executive_for_the_company() -> None:
    """RED CASE, proving the stub reproduces the live failure: with no name, the most frequent
    advertiser wins, so the executive is kept and the company's own ads are dropped."""
    from lumen_ingestion.ad_library.harvest import select_creatives

    pages = [_page(CONDUIT_PAGE_ID, _conduit_library()._ads_by_page[CONDUIT_PAGE_ID])]
    selection = select_creatives(pages)

    assert selection.advertiser_name == "Cole Rubin"
    assert {ad.advertiser_name for ad in selection.kept} == {"Cole Rubin"}


def test_the_resolved_name_keeps_the_companys_ads_over_a_louder_executive(
    tmp_path: Path, lane_on: None
) -> None:
    """THE FIX. The filter is told the resolved name, so the company's ads are kept, the
    executive's promoted posts are dropped as thought-leader ads, and the check passes."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id, company_domain="conduit.ai"),
        provider=_conduit_library(),
        identity_resolver=_conduit_identity(),
    )

    harvest = job["evidence"]["steps"]["harvest"]
    assert harvest["advertiser_name"] == "conduit"
    assert harvest["kept"] == 2
    assert harvest["dropped"] == {"thought_leader": 5}
    assert harvest["advertiser_check"]["status"] == "ok"
    assert job["outcome"]["status"] != "advertiser_mismatch"
    creatives = client.get(f"/brand-ad-assets/{brand_kit_id}").json()["creatives"]
    assert {c["advertiser_name"] for c in creatives} == {"Conduit"}


def test_on_the_fallback_path_a_named_brand_keeps_nothing_from_a_strangers_page(
    tmp_path: Path, lane_on: None
) -> None:
    """A stranger's page yields nothing, and says WHY: the dropped names reach the cross-check.

    The filter drops every ad not advertised by the brand's name, so nothing is kept. Until
    2026-09-30 the cross-check compared only the KEPT ads, was handed an empty list, and the lane
    landed on the weaker word `empty`. It now checks the names the filter dropped for not being
    the brand's when nothing was kept, so a stranger's page reads as `advertiser_mismatch` and the
    stranger is named. Custody is unchanged: not one stranger's creative is kept.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: (
                _ad("42", "Some Other Company", "https://cdn.example/other.jpg"),
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id, advertiser_name="Apollo.io"),
        provider=library,
        identity_resolver=_UnknownDomainResolver(),
    )

    harvest = job["evidence"]["steps"]["harvest"]
    assert harvest["status"] == "advertiser_mismatch"
    assert harvest["kept"] == 0
    assert harvest["dropped"] == {"thought_leader": 1}, "the filter did the dropping"
    assert harvest["advertiser_check"]["status"] == "mismatch"
    assert harvest["advertiser_check"]["observed"] == ["Some Other Company"]

    assert job["outcome"]["advertiser_verified"] is False
    assert "UNVERIFIED" in job["outcome"]["summary"]
    # THE R3-A FIX, in the case that matters most: the page is named.
    assert APOLLO_WRONG_PAGE_ID in job["outcome"]["summary"]
    assert client.get(f"/brand-ad-assets/{brand_kit_id}").json()["creatives"] == []


def test_with_no_expected_name_at_all_the_check_records_that_it_could_not_run(
    tmp_path: Path, lane_on: None
) -> None:
    """The honest third state, and the guard's real limit.

    On the fallback path with no identity resolver AND no operator-supplied name, there is no
    independently-sourced name to compare against — the only name available is the one inferred
    from the very page whose identity is in question, and comparing a page to itself verifies
    nothing. The check records `not_applicable` rather than a silent pass, and the harvest
    proceeds UNVERIFIED, which is exactly what it is.

    This is why the identity resolver matters: it is the only path that supplies a name the
    harvest did not choose for itself.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: (
                _ad("43", "Some Other Company", "https://cdn.example/other.jpg"),
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),  # no advertiser_name
        provider=library,
        identity_resolver=_UnknownDomainResolver(),
    )

    harvest = job["evidence"]["steps"]["harvest"]
    assert harvest["advertiser_check"]["status"] == "not_applicable"
    assert harvest["advertiser_check"]["observed"] == ["Some Other Company"]
    # It does NOT block: an unverifiable harvest is still a harvest, and the record says so.
    assert harvest["kept"] == 1
    assert job["resolution"]["verified"] is False
    assert job["resolution"]["resolved_name"] is None
    assert "UNVERIFIED" in job["outcome"]["summary"]


# --- the fallback chain ---------------------------------------------------------------------------


def test_a_broken_resolver_falls_back_and_says_the_result_was_unverified(
    tmp_path: Path, lane_on: None
) -> None:
    """An identity outage must not cost a harvest that would otherwise work.

    It must also not be allowed to look like the verified path. The lane degrades to exactly
    the pre-R3-A behaviour and says so, in the summary, in words.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: tuple(
                _ad(f"7000{n}", "Apollo.io", f"https://cdn.example/fallback-{n}.jpg")
                for n in range(2)
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id, advertiser_name="Apollo.io"),
        provider=library,
        identity_resolver=_BrokenIdentityResolver(),
    )

    assert job["status"] == "succeeded"
    # The domain went on the wire, because nothing resolved it.
    assert library.calls[0]["company_domain"] == "apollo.io"
    assert library.calls[0]["page_id"] is None
    assert job["evidence"]["steps"]["harvest"]["kept"] == 2

    resolution = job["resolution"]
    assert resolution["resolver_used"] == "ad_library_domain"
    assert resolution["verified"] is False
    assert "transport_error" in resolution["note"]
    assert resolution["observed_page_id"] == APOLLO_WRONG_PAGE_ID

    outcome = job["outcome"]
    assert outcome["advertiser_verified"] is False
    assert "UNVERIFIED" in outcome["summary"]
    assert outcome["creatives_custodied"] == 2, "the harvest survived the identity outage"


def test_a_blank_identity_credential_falls_back_rather_than_failing(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE: blank is the DEFAULT, so this is what most deployments do.

    A keyless deployment must behave exactly as the lane did before R3-A — no worse — and must
    stop claiming to be better. The autouse fixture already blanks the key; passing no resolver
    is therefore the production path for an unconfigured install.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: (
                _ad("8001", "Apollo.io", "https://cdn.example/keyless.jpg"),
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id, advertiser_name="Apollo.io"),
        provider=library,
        identity_resolver=None,  # production default -> resolved from settings -> no key
    )

    assert job["status"] == "succeeded"
    assert library.calls[0]["company_domain"] == "apollo.io"
    resolution = job["resolution"]
    assert resolution["resolver_used"] == "ad_library_domain"
    assert resolution["verified"] is False
    assert "credentials_missing" in resolution["note"]
    assert job["outcome"]["creatives_custodied"] == 1


def test_a_resolver_that_knows_the_company_but_not_a_page_keeps_the_name(
    tmp_path: Path, lane_on: None
) -> None:
    """A named company with no LinkedIn page cannot address the harvest — but it can gate it."""
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: (
                _ad("8100", "Somebody Else", "https://cdn.example/nameless.jpg"),
            )
        }
    )
    nameless = _StubIdentityResolver(
        CompanyIdentity(
            domain="apollo.io",
            name="Apollo.io",
            linkedin_id=None,
            linkedin_url=None,
            provider="stub-identity",
        )
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=library,
        identity_resolver=nameless,
    )

    resolution = job["resolution"]
    assert resolution["resolver_used"] == "ad_library_domain"
    assert resolution["resolved_name"] == "Apollo.io", "the name survived to gate custody"
    assert resolution["verified"] is False
    # And it did its job: the fallback page served a stranger and was refused.
    assert job["outcome"]["status"] == "advertiser_mismatch"


# --- the operator override --------------------------------------------------------------------------


def test_an_explicit_page_id_skips_the_resolver_and_still_cross_checks(
    tmp_path: Path, lane_on: None
) -> None:
    """The operator's hand-verified id IS the verification, so no credit is spent to re-ask it.

    It is an assertion rather than a verification, though — so `verified` stays false, and the
    advertiser-name check still gates custody exactly as on every other path. This is the shape
    R3 had to run by hand to get a working Apollo harvest at all.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary()
    identity = _StubIdentityResolver()

    job = _run(
        client,
        tmp_path,
        request_body=_body(
            brand_kit_id,
            company_domain=None,
            page_id=APOLLO_TRUE_PAGE_ID,
            advertiser_name="Apollo.io",
        ),
        provider=library,
        identity_resolver=identity,
    )

    assert identity.calls == [], "an explicit id must not spend an enrichment credit"
    assert library.calls[0]["page_id"] == APOLLO_TRUE_PAGE_ID

    resolution = job["resolution"]
    assert resolution["resolver_used"] == "explicit"
    assert resolution["linkedin_page_id"] == APOLLO_TRUE_PAGE_ID
    assert resolution["verified"] is False, "an assertion is not a verification"
    assert job["outcome"]["creatives_custodied"] == 4
    assert job["outcome"]["advertiser_conflict"] is None


def test_an_explicit_but_wrong_page_id_still_yields_nothing(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE: the operator can be wrong too, and nothing defers to them.

    This is R3's own manual workaround pointed at the wrong number — the operator hand-types a
    page id that turns out to serve somebody else. As in the fallback test above, the supplied
    `advertiser_name` means the thought-leader filter refuses the ads before the cross-check is
    reached, so the status is `empty`; what matters is the guarantee, which holds: the library
    stays clean, and the summary names the page that was actually read.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _ApolloLibrary(
        ads_by_page={
            APOLLO_WRONG_PAGE_ID: (
                _ad("9100", "Seamless.AI", "https://cdn.example/wrong.jpg"),
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_body(
            brand_kit_id,
            company_domain=None,
            page_id=APOLLO_WRONG_PAGE_ID,
            advertiser_name="Apollo.io",
        ),
        provider=library,
        identity_resolver=None,
    )

    assert job["outcome"]["creatives_custodied"] == 0
    assert job["evidence"]["steps"]["harvest"]["dropped"] == {"thought_leader": 1}
    assert job["resolution"]["resolver_used"] == "explicit"
    assert job["resolution"]["verified"] is False
    assert APOLLO_WRONG_PAGE_ID in job["outcome"]["summary"]
    assert client.get(f"/brand-ad-assets/{brand_kit_id}").json()["creatives"] == []


def test_the_route_accepts_the_override_under_either_spelling(
    tmp_path: Path, lane_on: None
) -> None:
    """`linkedin_page_id` is the R3-A spelling and the vendor's own; `page_id` is the legacy one.

    They are ONE field, not two — a second independent page selector would recreate exactly the
    "which one did the caller mean" ambiguity the route refuses `company_domain` + `page_id`
    together to avoid. So the alias must also still trip that refusal.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    for spelling in ("page_id", "linkedin_page_id"):
        body = {
            "brand_kit_id": brand_kit_id,
            "brand_kit_version": BRAND_KIT_VERSION,
            spelling: APOLLO_TRUE_PAGE_ID,
        }
        offered = client.post("/brand-ad-assets/onboard", json=body)
        assert offered.status_code == 200, f"{spelling}: {offered.text}"

    ambiguous = client.post(
        "/brand-ad-assets/onboard",
        json={
            "brand_kit_id": brand_kit_id,
            "brand_kit_version": BRAND_KIT_VERSION,
            "company_domain": "apollo.io",
            "linkedin_page_id": APOLLO_TRUE_PAGE_ID,
        },
    )
    assert ambiguous.status_code == 422
    assert ambiguous.json()["detail"]["code"] == "ad_assets.advertiser_ambiguous"


def test_a_harvest_that_dies_in_the_ad_library_loses_its_resolution_block(
    tmp_path: Path, lane_on: None
) -> None:
    """A KNOWN GAP, pinned so it is a decision on record rather than a surprise later.

    `run_ingestion_job` persists evidence only on the success path — `store.fail` writes an
    `error_json` and nothing else — so a job that dies fetching keeps no resolution block, and
    the page it was about to read is not recoverable from the job row. That is the R3-A question
    ("which advertiser was this even about?") at its least answerable.

    It is NOT fixed here on purpose. The fix is to teach `store.fail` to carry partial evidence,
    which is machinery shared by all four ingestion kinds, and widening a shared failure contract
    is not this change's call to make. This test exists so that when someone does make it, the
    behaviour flips loudly instead of silently.
    """
    from lumen_ingestion.ad_library.provider import AdLibraryError

    class _BrokenLibrary:
        name = "stub-library"

        def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
            raise AdLibraryError("ad_library.http_error", "HTTP 503: the vendor is on fire")

    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=_BrokenLibrary(),
        identity_resolver=_StubIdentityResolver(),
    )

    assert job["status"] == "failed", "a vendor outage IS a job failure"
    assert "the vendor is on fire" in json_dumps(job["error"])
    # The gap. Flip this to an assertion that the block SURVIVES once `store.fail` carries
    # partial evidence.
    assert job["resolution"] is None


# --- the honest empty is still honest -------------------------------------------------------------


def test_a_verified_page_that_genuinely_has_no_ads_still_reads_empty(
    tmp_path: Path, lane_on: None
) -> None:
    """`empty` must survive R3-A intact: a brand with no static ads is not a mismatch.

    The two statuses mean opposite things and the summary now says which page was checked, so
    "we looked in the right place and there was nothing" is finally a statement a caller can
    read rather than infer.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)

    job = _run(
        client,
        tmp_path,
        request_body=_body(brand_kit_id),
        provider=_ApolloLibrary(ads_by_page={APOLLO_TRUE_PAGE_ID: ()}),
        identity_resolver=_StubIdentityResolver(),
    )

    outcome = job["outcome"]
    assert outcome["status"] == "empty"
    assert outcome["advertiser_conflict"] is None
    assert outcome["advertiser_verified"] is True
    assert outcome["linkedin_page_id"] == APOLLO_TRUE_PAGE_ID
    assert "0 ad(s) kept" in outcome["summary"]
    # The critical difference from the W5 run: the page that was checked is IN the summary.
    assert APOLLO_TRUE_PAGE_ID in outcome["summary"]


# ======================================================================================
# W-B3 — the resolved page that is real, correct, and still the wrong place to harvest
# ======================================================================================
#
# R3-A assumed that resolving the advertiser independently was enough. It is not. For
# `cursor.com` the identity resolver answered page 105610681 — a real page, genuinely the
# company's — carrying zero ads, while the page Cursor actually advertises from holds 4489.
# Enrichment records name the LEGAL ENTITY, and a company may advertise from a different page.
#
# Nothing in the lane could see this: an empty page is an honest answer, so the job read
# `empty`, which is a sentence reserved for "this brand has no static ads" and was flatly
# false. The fix is one retry against the ad library's own domain resolution, fired only when
# the resolved page held NO ADS AT ALL.


#: The identity resolver's answer for cursor.com, as recorded in the W-B3 run: a real page,
#: correctly the company's, carrying zero ads.
CURSOR_LEGAL_ENTITY_PAGE_ID = "105610681"

#: The page the ad library's own domain resolution answers with instead. The W-B3 run found
#: 4489 ads behind it; its NUMBER is not reproduced here as a fact, because these tests assert
#: which page the harvest reached, not what that page is called.
CURSOR_ADVERTISER_PAGE_ID = "cursor-advertiser-page"


class _CursorLibrary:
    """The ad library on the W-B3 shape: the resolver's page is empty, the vendor's is not.

    Asked for a PAGE ID it serves that page (empty unless seeded). Asked for a DOMAIN it
    answers its own resolution — a different page, and the one with the ads on it. That
    asymmetry is the whole defect, and it is the reverse of R3-A's, where the vendor's own
    resolution was the wrong one.
    """

    name = "stub-library"

    def __init__(self, *, ads_by_page: dict[str, tuple[AdLibraryAd, ...]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._ads_by_page = (
            ads_by_page
            if ads_by_page is not None
            else {
                CURSOR_ADVERTISER_PAGE_ID: tuple(
                    _ad(f"44890{n}", "Cursor", f"https://cdn.example/cursor-{n}.jpg")
                    for n in range(4)
                )
            }
        )

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        self.calls.append(kwargs)
        page_id = kwargs.get("page_id") or CURSOR_ADVERTISER_PAGE_ID
        return _page(page_id, self._ads_by_page.get(page_id, ()))


def _cursor_identity(page_id: str | None = CURSOR_LEGAL_ENTITY_PAGE_ID) -> _StubIdentityResolver:
    return _StubIdentityResolver(
        CompanyIdentity(
            domain="cursor.com",
            name="Cursor",
            linkedin_id=page_id,
            linkedin_url="linkedin.com/company/cursor",
            provider="stub-identity",
        )
    )


def _cursor_body(brand_kit_id: str, **overrides: Any) -> dict:
    return _body(brand_kit_id, company_domain="cursor.com", **overrides)


def test_the_resolved_page_is_real_correct_and_empty_while_the_ads_live_elsewhere(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE, proving the stub is not rigged: R3-A's own fix produces the W-B3 empty.

    Driven the post-R3-A way — resolve first, harvest the resolved id, no retry — the identity
    resolver's page answers with nothing at all. Not "nothing kept": nothing CONSIDERED. That
    is the number the retry keys on, and this is what it looks like before the retry exists.
    """
    from lumen_ingestion.ad_library.harvest import ads_considered, fetch_pages, select_creatives

    library = _CursorLibrary()
    pages = fetch_pages(
        library, company_domain=None, page_id=CURSOR_LEGAL_ENTITY_PAGE_ID, max_pages=1
    )

    assert library.calls[0]["page_id"] == CURSOR_LEGAL_ENTITY_PAGE_ID
    assert pages[0].page_id == CURSOR_LEGAL_ENTITY_PAGE_ID
    assert ads_considered(pages) == 0, "the legal entity's page holds nothing at all"
    assert select_creatives(pages).kept == ()
    # And the ads were there the whole time, one domain resolution away.
    assert ads_considered(fetch_pages(library, company_domain="cursor.com", max_pages=1)) == 4


def test_an_empty_resolved_page_retries_once_against_the_ad_librarys_own_domain(
    tmp_path: Path, lane_on: None
) -> None:
    """THE FIX. Same request, same library, same resolver — and the harvest now finds the ads.

    Exactly two vendor page fetches: the resolved page, then the domain. No loop, no candidate
    set. The provenance carries BOTH attempts, and the summary says in plain language which
    page came up empty and which one the creatives actually came from.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary()

    job = _run(
        client,
        tmp_path,
        request_body=_cursor_body(brand_kit_id),
        provider=library,
        identity_resolver=_cursor_identity(),
    )

    # The retry, and its cost: one extra page fetch, on a harvest that had found nothing.
    assert len(library.calls) == 2, library.calls
    assert library.calls[0] == {
        "company_domain": None,
        "page_id": CURSOR_LEGAL_ENTITY_PAGE_ID,
        "continuation_token": None,
        "date_filter": None,
    }
    assert library.calls[1] == {
        "company_domain": "cursor.com",
        "page_id": None,
        "continuation_token": None,
        "date_filter": None,
    }

    assert job["status"] == "succeeded"
    assert job["evidence"]["steps"]["harvest"]["ads_considered"] == 4
    assert job["evidence"]["steps"]["harvest"]["kept"] == 4
    assert job["outcome"]["creatives_custodied"] == 4

    # --- honest provenance: both attempts, named ---
    resolution = job["resolution"]
    assert resolution["resolver_used"] == "pdl_then_ad_library_domain"
    assert resolution["linkedin_page_id"] == CURSOR_LEGAL_ENTITY_PAGE_ID, "the empty page stays"
    assert resolution["observed_page_id"] == CURSOR_ADVERTISER_PAGE_ID, "the page that harvested"
    assert resolution["verified"] is False, "nothing independent verified the page that served"
    assert resolution["resolved_name"] == "Cursor", "the resolver's name still gates custody"
    assert resolution["attempts"] == [
        {
            "resolver_used": "pdl",
            "page_id_asked": CURSOR_LEGAL_ENTITY_PAGE_ID,
            "page_id_answered": CURSOR_LEGAL_ENTITY_PAGE_ID,
            "ads_considered": 0,
        },
        {
            "resolver_used": "ad_library_domain",
            "page_id_asked": None,
            "page_id_answered": CURSOR_ADVERTISER_PAGE_ID,
            "ads_considered": 4,
        },
    ]

    outcome = job["outcome"]
    assert outcome["status"] == "ok"
    assert outcome["resolver_used"] == "pdl_then_ad_library_domain"
    assert outcome["linkedin_page_id"] == CURSOR_ADVERTISER_PAGE_ID
    assert outcome["advertiser_verified"] is False
    # The sentence a human reads. Both pages, in order, with what each held.
    summary = outcome["summary"]
    assert f"page {CURSOR_LEGAL_ENTITY_PAGE_ID} had no ads" in summary
    assert "fell back to the ad library's own domain resolution" in summary
    assert CURSOR_ADVERTISER_PAGE_ID in summary
    assert "UNVERIFIED" in summary

    lane = client.get(f"/brand-ad-assets/{brand_kit_id}").json()
    assert len(lane["creatives"]) == 4
    assert lane["creatives"][0]["provenance"]["advertiser_page_id"] == CURSOR_ADVERTISER_PAGE_ID


def test_a_resolved_page_that_holds_ads_the_filter_dropped_does_not_retry(
    tmp_path: Path, lane_on: None
) -> None:
    """THE LIMIT THAT MATTERS MOST. `kept == 0` is not the trigger; `considered == 0` is.

    This page holds three video ads. The filter drops all three, so nothing is kept — and the
    page is nevertheless the RIGHT page: it is where this advertiser publishes, it simply
    publishes video. Retrying it would spend a vendor fetch to be told the same thing by a
    source with weaker provenance, and would downgrade a verified resolution for nothing.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary(
        ads_by_page={
            CURSOR_LEGAL_ENTITY_PAGE_ID: tuple(
                replace(_ad(f"5100{n}", "Cursor", f"https://cdn.example/v-{n}.mp4"), kind="video")
                for n in range(3)
            ),
            CURSOR_ADVERTISER_PAGE_ID: (
                _ad("6100", "Cursor", "https://cdn.example/never-reached.jpg"),
            ),
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_cursor_body(brand_kit_id),
        provider=library,
        identity_resolver=_cursor_identity(),
    )

    assert len(library.calls) == 1, "no retry — the page had ads, they were simply not static"
    harvest = job["evidence"]["steps"]["harvest"]
    assert harvest["ads_considered"] == 3
    assert harvest["kept"] == 0
    assert harvest["dropped"] == {"not_static:video": 3}

    resolution = job["resolution"]
    assert resolution["resolver_used"] == "pdl", "the verified path is not downgraded"
    assert resolution["verified"] is True
    assert len(resolution["attempts"]) == 1
    assert job["outcome"]["status"] == "empty"
    assert job["outcome"]["linkedin_page_id"] == CURSOR_LEGAL_ENTITY_PAGE_ID
    # One attempt gets no retry sentence: there is nothing to explain.
    assert "fell back" not in job["outcome"]["summary"]


def test_an_explicit_page_id_with_no_ads_never_falls_back(
    tmp_path: Path, lane_on: None
) -> None:
    """The operator asserted this page. Second-guessing an assertion is an override, not a
    fallback — so an explicitly-requested page that comes back empty stays empty.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary()  # the domain WOULD answer with four ads, if anyone asked

    job = _run(
        client,
        tmp_path,
        request_body=_body(
            brand_kit_id,
            company_domain=None,
            page_id=CURSOR_LEGAL_ENTITY_PAGE_ID,
            advertiser_name="Cursor",
        ),
        provider=library,
        identity_resolver=None,
    )

    assert len(library.calls) == 1, "the operator's page was read once and believed"
    assert job["resolution"]["resolver_used"] == "explicit"
    assert len(job["resolution"]["attempts"]) == 1
    assert job["outcome"]["status"] == "empty"
    assert job["outcome"]["creatives_kept"] == 0


def test_a_keyless_harvest_that_comes_back_empty_does_not_re_ask_the_same_question(
    tmp_path: Path, lane_on: None
) -> None:
    """The `ad_library_domain` path is the thing being fallen back TO — it cannot fall back.

    A deployment with no identity key already sends the domain on the first call. If that came
    back empty, retrying it would ask the identical question of the identical source and spend
    a second vendor fetch to be told the same thing. This is the other half of "only on the
    `pdl` path", and without it the retry would double the cost of every empty keyless harvest.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary(ads_by_page={})

    job = _run(
        client,
        tmp_path,
        request_body=_cursor_body(brand_kit_id),
        provider=library,
        identity_resolver=None,  # no key -> the ad library resolves the domain itself
    )

    assert len(library.calls) == 1, "asking the same source the same question twice is not a fix"
    assert job["resolution"]["resolver_used"] == "ad_library_domain"
    assert len(job["resolution"]["attempts"]) == 1
    assert job["outcome"]["status"] == "empty"


def test_when_the_fallback_is_also_empty_the_zero_is_honest_and_both_attempts_are_recorded(
    tmp_path: Path, lane_on: None
) -> None:
    """Two empty pages are still an empty harvest — and the verified answer stands.

    The retry ran and found nothing either. The resolution is NOT downgraded to unverified on
    the strength of a second empty page: the identity resolver's page really is the best
    answer anyone has, and calling it unverified would trade a true statement for a false one.
    Both attempts are on the record, and the summary says both came up empty rather than
    quietly reporting one number.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary(ads_by_page={})  # nothing anywhere

    job = _run(
        client,
        tmp_path,
        request_body=_cursor_body(brand_kit_id),
        provider=library,
        identity_resolver=_cursor_identity(),
    )

    assert len(library.calls) == 2, "the retry ran"
    assert job["status"] == "succeeded"

    resolution = job["resolution"]
    assert resolution["resolver_used"] == "pdl"
    assert resolution["verified"] is True
    assert resolution["observed_page_id"] == CURSOR_LEGAL_ENTITY_PAGE_ID
    assert [a["ads_considered"] for a in resolution["attempts"]] == [0, 0]
    assert [a["resolver_used"] for a in resolution["attempts"]] == ["pdl", "ad_library_domain"]

    outcome = job["outcome"]
    assert outcome["status"] == "empty"
    assert outcome["creatives_kept"] == 0
    summary = outcome["summary"]
    assert f"page {CURSOR_LEGAL_ENTITY_PAGE_ID} had no ads" in summary
    assert "had none either" in summary
    assert "fell back" not in summary, "nothing was fallen back TO — both were empty"


def test_the_cross_check_still_gates_custody_on_the_fallback_page(
    tmp_path: Path, lane_on: None
) -> None:
    """RED CASE: the retry can land on a stranger's page, and the guard must still hold.

    This is the risk the retry introduces — the ad library's own domain resolution is exactly
    the source R3-A proved can be wrong, and the retry hands it authority again. What keeps it
    safe is that the identity resolver's NAME survives the fallback, so the cross-check is
    still comparing the harvested ads against an independently-sourced name rather than
    against the page's own account of itself. Nothing is kept.
    """
    client = _client(tmp_path)
    brand_kit_id = _seed_brand_kit(client)
    library = _CursorLibrary(
        ads_by_page={
            CURSOR_ADVERTISER_PAGE_ID: tuple(
                _ad(f"7200{n}", "Windsurf", f"https://cdn.example/stranger-{n}.jpg")
                for n in range(2)
            )
        }
    )

    job = _run(
        client,
        tmp_path,
        request_body=_cursor_body(brand_kit_id),  # no advertiser_name: the resolver supplies it
        provider=library,
        identity_resolver=_cursor_identity(),
    )

    assert len(library.calls) == 2
    steps = job["evidence"]["steps"]
    assert steps["harvest"]["status"] == "advertiser_mismatch"
    assert steps["harvest"]["kept"] == 0
    assert "custody" not in steps, "KEEP NOTHING — custody was never reached"

    outcome = job["outcome"]
    assert outcome["status"] == "advertiser_mismatch"
    conflict = outcome["advertiser_conflict"]
    assert "Windsurf" in conflict and "Cursor" in conflict
    # Both pages are in the conflict sentence, which is what makes it diagnosable.
    assert CURSOR_LEGAL_ENTITY_PAGE_ID in conflict
    assert CURSOR_ADVERTISER_PAGE_ID in conflict
    assert client.get(f"/brand-ad-assets/{brand_kit_id}").json()["creatives"] == []
