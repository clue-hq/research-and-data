"""Provider-transport doubles for the comprehensive account-research proof harness.

Every double here sits at the **provider HTTP/transport seam and nowhere else**: the production
composition (``ProductionAccountResearchProviderActions``, in
:mod:`clue_api.entity_research_provider_wiring`) builds the real Exa/Sumble coordinators, the real
preflight/eligibility/durability code runs unchanged, and the real response parsers and validators
run over these payloads. What is replaced is only the socket.

Three seams, all of which the shipped clients already expose as an injectable ``http`` fetcher (or,
for Exa, an injectable transport object):

* ``ExaDeepHttpAcquisitionTransport`` — replaced with :class:`HarnessExaTransport`, which answers
  each compiled bundle from that bundle's own output schema (the
  ``tests/api/test_comprehensive_account_execution_db`` pattern, imported rather than restated).
* ``SumbleClient`` inside :mod:`clue_api.sumble_account_gaps` — its ``http`` fetcher is replaced.
* ``SumbleV9CommitteeClient`` — its ``http`` fetcher is replaced.

Routing is by *content*, never by call order: the Exa request carries its account's canonical name
and registrable domain in ``request.query``, and every Sumble body carries either the requested
domain or the organization id this harness minted for that account. A harness cycle can therefore
serve five accounts different adversity without any implicit sequencing assumption.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from clue_research.resolvers.exa.deep_contract import EXA_FIELD_ALIAS_CHARACTERS
from clue_research.resolvers.http import ProviderResponseError
from tests.api.test_comprehensive_account_execution_db import (
    _schema_example,
    _ScriptedExaTransport,
)

_SUMBLE_V9 = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "sumble" / "v9"

#: The first organization id this harness mints. Sumble organization ids are provider-side
#: integers; the harness needs a stable, collision-free one per account so every later
#: ``/jobs`` / ``/techs`` / ``/teams`` / ``/people`` body routes back to its account by content.
_ORGANIZATION_ID_BASE = 7_100_000

#: The host every retained document in the recorded Exa envelope sits on. Rewritten per account.
_RECORDED_DOMAIN = "cascade-gastro.example"

#: What one Exa Deep bundle costs in this harness, in dollars. The recorded live envelope reports
#: ``0.42``; the shipped scripted transport rewrites it to ``0.07``. Both are far above the
#: ``exa_deep`` source manifest's ``cost_cents=10`` per-call budget unit, which is what the
#: production reservation is sized from.
_RECORDED_BUNDLE_COST_DOLLARS = 0.07


def organization_id_for(index: int) -> int:
    return _ORGANIZATION_ID_BASE + index


class HarnessExaTransport(_ScriptedExaTransport):
    """One Exa Deep transport serving five accounts, routed by the request's own target lock.

    ``empty_field_keys`` (inherited) leaves a field out of the structured answer entirely — the
    production shape of "asked, found nothing", which the real projection builder turns into a
    ``null`` outcome with ``explicit_null`` verification.

    ``truncating_domains`` reproduces the live defect the settlement repair was written for: Exa
    answers a dispatched bundle with truncated structured-output alias keys, so
    ``validate_exa_deep_exchange`` refuses the exchange and the operation must settle
    ``spend_outcome_unknown`` terminally instead of stranding the account. Only the *first* bundle
    of the nominated account is corrupted, so that account's batch is the live mixed shape: some
    bundles ready, one dispatched bundle that can never yield a snapshot.

    The corruption is modelled as an *alias copy budget*: the provider only reproduces the first
    ``alias_char_budget`` characters of a property name. That is the live shape — the resonance
    bundle asked for 52, 66 and 74-character hex aliases and got 48, 62 and 62 characters back.
    The default budget is deliberately below the current fixed alias length so this transport still
    corrupts. What the real provider managed is ``LIVE_ALIAS_CHAR_BUDGET`` in
    :mod:`tests.api.test_comprehensive_account_execution_db`, six times the current alias length.
    """

    def __init__(
        self,
        *,
        domains: Mapping[str, str],
        empty_field_keys: Sequence[str] = (),
        truncating_domains: Sequence[str] = (),
        alias_char_budget: int = EXA_FIELD_ALIAS_CHARACTERS - 2,
        cost_dollars: float = _RECORDED_BUNDLE_COST_DOLLARS,
    ) -> None:
        super().__init__(empty_field_keys=empty_field_keys)
        self._cost_dollars = cost_dollars
        self._domain_by_slug = dict(domains)
        self._slug_by_domain = {domain: slug for slug, domain in domains.items()}
        self._truncating = frozenset(truncating_domains)
        self._alias_char_budget = alias_char_budget
        self._corrupted: dict[str, frozenset[str]] = {}
        self.requested_field_keys_by_slug: dict[str, set[str]] = {}

    @property
    def corrupted_field_keys(self) -> Mapping[str, frozenset[str]]:
        """The exact fields whose bundle was answered with unusable keys, per account slug."""

        return dict(self._corrupted)

    def _slug(self, request: Any) -> str:
        for domain, slug in self._slug_by_domain.items():
            if domain in request.query:
                return slug
        raise AssertionError(f"Exa request is not target-locked to a harness account: {request!r}")

    def search(self, request: Any) -> Mapping[str, Any]:
        slug = self._slug(request)
        domain = self._domain_by_slug[slug]
        # Re-host the recorded envelope on the account being researched. This is not cosmetic:
        # ``GroundedSynthesisResolver._on_entity`` keeps a synthesized value only when the
        # citation's registrable host is the account's own domain or the account's name is a
        # whole-word match in the retrieved passage. A real Exa answer about this account cites
        # documents about this account; an envelope still pointing at the recorded fixture's
        # company would be correctly refused as off-entity, and the field would then normalize
        # without a claim.
        payload: dict[str, Any] = json.loads(
            json.dumps(super().search(request)).replace(_RECORDED_DOMAIN, domain)
        )
        cast(dict[str, Any], payload["costDollars"])["total"] = self._cost_dollars
        field_key_by_alias = cast(Mapping[str, str], request.field_key_by_alias)
        self.requested_field_keys_by_slug.setdefault(slug, set()).update(
            str(field_key) for field_key in field_key_by_alias.values()
        )
        if domain not in self._truncating or slug in self._corrupted:
            return payload
        output = dict(cast(Mapping[str, Any], payload["output"]))
        content = cast(Mapping[str, Any], output["content"])
        clipped = {alias[: self._alias_char_budget]: value for alias, value in content.items()}
        if clipped == content:
            # Every requested alias fitted the provider's copy budget, so nothing is corrupted and
            # the exchange settles normally. This is the whole point of the short alias scheme.
            return payload
        output["content"] = clipped
        payload["output"] = output
        self._corrupted[slug] = frozenset(str(field_key_by_alias[alias]) for alias in content)
        return payload


def _fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_SUMBLE_V9 / name).read_text()))


class HarnessSumbleHttp:
    """One Sumble v9 HTTP fetcher for the account-gap *and* committee lanes.

    The shipped ``SumbleClient`` / ``SumbleV9CommitteeClient`` both accept ``http`` as their only
    I/O seam, so this callable is the whole fake. Every payload below is shaped to satisfy the real
    response models, the real credit reconciliation (``credits_used <= maximum``) and the real
    normalizers, so genuine evidence-backed claims and genuine committee candidates come out.

    Adversity is keyed by account:

    * ``rejecting_jobs_domains`` — ``POST /v9/jobs`` answers HTTP 422 for that account. A 4xx is a
      *deterministic* provider rejection, so the account-gap operation settles ``FAILED_TERMINAL``,
      the requested field's ``(field, source)`` pair reaches a terminal dispatched attempt, and the
      tool converts it into a governed rejection rather than a job-integrity crash.
    * ``empty_committee_slugs`` — ``/teams`` and ``/people`` answer with a genuine zero-result
      succeeded payload, which is the ``confirmed_empty_discovery`` shape.
    """

    def __init__(
        self,
        *,
        domains: Mapping[str, str],
        organization_ids: Mapping[str, int],
        names: Mapping[str, str],
        localities: Mapping[str, tuple[str, str]],
        run_token: str,
        rejecting_jobs_slugs: Sequence[str] = (),
        empty_committee_slugs: Sequence[str] = (),
    ) -> None:
        # Provider request/operation ids are globally unique in the durable substrate — the
        # committee snapshot table carries UNIQUE NULLS NOT DISTINCT (source_key,
        # provider_operation_id), and account-gap replay re-checks the stored provider request id.
        # A cycle token keeps a repeated account slug from minting a colliding id.
        self._token = run_token
        self._domains = dict(domains)
        self._slug_by_domain = {domain: slug for slug, domain in domains.items()}
        self._organization_ids = dict(organization_ids)
        self._slug_by_organization = {value: slug for slug, value in organization_ids.items()}
        self._names = dict(names)
        self._localities = dict(localities)
        self._rejecting_jobs = frozenset(rejecting_jobs_slugs)
        self._empty_committee = frozenset(empty_committee_slugs)
        self.calls: list[tuple[str, str]] = []

    # -- routing ---------------------------------------------------------------------------

    def __call__(self, url: str, **kwargs: Any) -> Any:
        body = cast(Mapping[str, Any] | None, kwargs.get("json_body"))
        if url.endswith("/organizations"):
            return self._organizations(body)
        if url.endswith("/jobs"):
            return self._jobs(body)
        if url.endswith("/techs"):
            return self._techs(url)
        if url.endswith("/teams"):
            return self._teams(body)
        if url.endswith("/people"):
            return self._people(body)
        raise AssertionError(f"unexpected Sumble URL: {url}")

    def _slug_for_organization(self, organization_id: int) -> str:
        slug = self._slug_by_organization.get(int(organization_id))
        if slug is None:
            raise AssertionError(f"unknown harness organization id {organization_id}")
        return slug

    # -- account-gap lane ------------------------------------------------------------------

    def _organizations(self, body: Mapping[str, Any] | None) -> dict[str, Any]:
        assert body is not None
        requested = str(cast(Mapping[str, Any], body["organizations"][0])["url"])
        slug = self._slug_by_domain.get(requested)
        if slug is None:
            raise AssertionError(f"unknown harness domain {requested}")
        self.calls.append((slug, "organizations"))
        selected = frozenset(
            str(value)
            for value in cast(Mapping[str, Any], body.get("select", {})).get("attributes", ())
        )
        attributes: dict[str, Any] = {
            "id": self._organization_ids[slug],
            "name": self._names[slug],
            "url": self._domains[slug],
            "sumble_url": f"https://sumble.com/l/org/{slug}",
        }
        # Model the live contract: a paid attribute is returned only when it was selected.
        available = {
            "employee_count": 120,
            "industry": "Healthcare",
            "headquarters_country": "US",
        }
        attributes.update({name: value for name, value in available.items() if name in selected})
        return {
            "id": f"harness-org-{self._token}-{slug}",
            "credits_used": 1,
            "credits_remaining": 9_999,
            "organizations": [
                {
                    "input": {"url": self._domains[slug]},
                    "attributes": attributes,
                    "entities": [],
                }
            ],
            "matched_count": 1,
            "total": 1,
        }

    def _jobs(self, body: Mapping[str, Any] | None) -> dict[str, Any]:
        assert body is not None
        organization_id = self._committee_organization_id(body)
        slug = self._slug_for_organization(organization_id)
        self.calls.append((slug, "jobs"))
        if slug in self._rejecting_jobs:
            raise ProviderResponseError(
                "sumble_jobs: provider rejected the request",
                status_code=422,
                body_excerpt='{"detail":"unsupported job_function filter for this organization"}',
            )
        return {
            "id": f"harness-jobs-{self._token}-{slug}",
            "credits_used": 1,
            "credits_remaining": 9_998,
            "jobs": [
                {
                    "job_id": organization_id,
                    "sumble_url": f"https://sumble.com/l/job/{slug}",
                    "attributes": {},
                }
            ],
            "total": 4,
            "source_data_url": f"https://sumble.com/l/org/{slug}/jobs",
        }

    def _techs(self, url: str) -> dict[str, Any]:
        organization_id = int(url.rsplit("/", 2)[-2])
        slug = self._slug_for_organization(organization_id)
        self.calls.append((slug, "techs"))
        return {
            "id": f"harness-techs-{self._token}-{slug}",
            "credits_used": 3,
            "credits_remaining": 9_995,
            "organization_id": organization_id,
            "organization_slug": slug,
            "business_functions": [
                {
                    "business_function": "Operations",
                    "categories": [
                        {
                            "category_slug": "clinical-systems",
                            "category_name": "Clinical",
                            "category_name_full": "Clinical Systems",
                            "technologies": [
                                {
                                    "name": "Epic",
                                    "slug": "epic",
                                    "job_post_used_count": 8,
                                    "domain": "epic.com",
                                },
                                {
                                    "name": "RingCentral",
                                    "slug": "ringcentral",
                                    "job_post_used_count": 3,
                                    "domain": "ringcentral.com",
                                },
                            ],
                            "evidence": [
                                {"name": "Epic", "job_post_used_count": 8},
                                {"name": "RingCentral", "job_post_used_count": 3},
                            ],
                        }
                    ],
                }
            ],
        }

    # -- committee lane --------------------------------------------------------------------

    def _teams(self, body: Mapping[str, Any] | None) -> dict[str, Any]:
        assert body is not None
        organization_id = self._committee_organization_id(body)
        slug = self._slug_for_organization(organization_id)
        self.calls.append((slug, "teams"))
        if slug in self._empty_committee:
            payload = _fixture("teams_empty_succeeded.json")
        else:
            payload = _personalize(_fixture("teams_succeeded.json"), token=self._token, slug=slug)
            _retarget_teams(payload, organization_id=organization_id, name=self._names[slug])
        payload["id"] = f"harness-teams-{self._token}-{slug}"
        payload["credits_used"] = 1
        payload["credits_remaining"] = 9_990
        return payload

    def _people(self, body: Mapping[str, Any] | None) -> dict[str, Any]:
        assert body is not None
        request_id = body.get("request_id")
        if isinstance(request_id, str):
            slug = request_id.removeprefix(f"harness-people-{self._token}-")
            self.calls.append((slug, "people_poll"))
        else:
            organization_id = self._committee_organization_id(body)
            slug = self._slug_for_organization(organization_id)
            self.calls.append((slug, "people_submit"))
        organization_id = self._organization_ids[slug]
        if slug in self._empty_committee:
            payload = _fixture("people_empty_succeeded.json")
        else:
            payload = _personalize(_fixture("people_succeeded.json"), token=self._token, slug=slug)
            city, region = self._localities[slug]
            _retarget_people(
                payload,
                organization_id=organization_id,
                name=self._names[slug],
                city=city,
                region=region,
            )
        payload["id"] = f"harness-people-response-{self._token}-{slug}"
        payload["request_id"] = f"harness-people-{self._token}-{slug}"
        payload["status"] = "succeeded"
        payload["credits_used"] = 1
        payload["credits_remaining"] = 9_985
        return payload

    @staticmethod
    def _committee_organization_id(body: Mapping[str, Any]) -> int:
        """Every filtered v9 body (jobs, teams, people) names its organization the same way."""

        query = cast(Mapping[str, Any], body.get("filter", {}))
        ids = query.get("organization_ids")
        if isinstance(ids, list) and ids:
            return int(cast(Any, ids[0]))
        raise AssertionError(f"Sumble v9 body carries no organization id: {body!r}")


#: The person identities the recorded v9 fixtures carry. Reusing them across accounts would make
#: one contact entity (the LinkedIn URL is the workspace-scoped strong key) hold contradictory
#: immutable professional facts, which the committee worker correctly refuses as a replay conflict.
#: Different companies employ different people, so the harness gives each account its own.
_RECORDED_PEOPLE = (
    (1001, "alex-ops", "alex-morgan-ops", "Alex Morgan"),
    (1002, "sam-former", "sam-former", "Sam Former"),
)


def _personalize(payload: dict[str, Any], *, token: str, slug: str) -> dict[str, Any]:
    """Give this account's committee its own people, deterministically derived from the account."""

    body = json.dumps(payload)
    for ordinal, (person_id, person_slug, profile_slug, full_name) in enumerate(_RECORDED_PEOPLE):
        digest = hashlib.sha256(f"{token}:{slug}".encode()).digest()
        unique = 1_000_000 + int.from_bytes(digest[:3], "big") % 900_000 * 10 + ordinal
        body = body.replace(f'"person_id": {person_id}', f'"person_id": {unique}')
        body = body.replace(f"person/{person_slug}", f"person/{person_slug}-{token}-{slug}")
        body = body.replace(f"in/{profile_slug}", f"in/{profile_slug}-{token}-{slug}")
        body = body.replace(f'"{full_name}"', f'"{full_name} {slug.title()}"')
    return cast(dict[str, Any], json.loads(body))


def _retarget_teams(payload: dict[str, Any], *, organization_id: int, name: str) -> None:
    for team in cast(list[dict[str, Any]], payload.get("teams", [])):
        attributes = cast(dict[str, Any], team.get("attributes", {}))
        organization = cast(dict[str, Any], attributes.get("organization", {}))
        organization["organization_id"] = organization_id
        organization["name"] = name
        for person in cast(list[dict[str, Any]], team.get("related_people", [])):
            person_attributes = cast(dict[str, Any], person.get("attributes", {}))
            employer = cast(dict[str, Any], person_attributes.get("current_employer", {}))
            if employer:
                employer["organization_id"] = organization_id
                employer["name"] = name


def _retarget_people(
    payload: dict[str, Any],
    *,
    organization_id: int,
    name: str,
    city: str,
    region: str,
) -> None:
    people = cast(list[dict[str, Any]], payload.get("people", []))
    for index, person in enumerate(people):
        attributes = cast(dict[str, Any], person.get("attributes", {}))
        employer = cast(dict[str, Any], attributes.get("current_employer", {}))
        if not employer:
            continue
        # The recorded fixture deliberately carries one *former* employee whose employer id does
        # not match; retarget only the first person so the harness keeps that negative case.
        employer["organization_id"] = organization_id if index == 0 else 9_999_999
        if index == 0:
            employer["name"] = name
            attributes["location"] = f"{city}, {region}, United States"


__all__ = [
    "HarnessExaTransport",
    "HarnessSumbleHttp",
    "organization_id_for",
    "_schema_example",
]
