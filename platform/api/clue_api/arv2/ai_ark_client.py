"""The AI Ark provider client — company search, name-scoped people search, single email export.

AI Ark is ARV2's committee and enrichment provider (`docs/specs/ARV2-ai-ark-contract-notes.md`
§7: it took the slot on a 5/5 live canary). Four wire facts learned there — none of them in the
vendor's docs — are why this module exists rather than a generic JSON helper:

* **Cloudflare answers a default HTTP client with 403 error 1010.** Every request therefore
  carries a browser ``User-Agent``.
* **Rate limiting is stricter than the documented 5 rps** — 429s appeared at roughly six calls in
  quick succession. Every call is paced at least ``min_gap_s`` (10.5 s by default, the
  ``arv2_ai_ark_min_gap_s`` setting) after the previous one returned.
* **Billing is result-count arithmetic, not a metered field.** ``GET /v1/credit`` answers 401 even
  with a working key, so there is no balance to read: the cost readers below multiply the unit
  price by the number of records the response actually returned, which is the only honest
  reading available.
* **``profile.birth_date`` is real in AI Ark bodies** (present, usually null) and has no outreach
  use-class. Appendix A law 3 — drop sensitive keys *inside the client, before persistence* — is
  implemented by handing :func:`scrub_birth_dates` to the wrapper as its ``raw_scrubber``, so the
  key exists on no path at all: not on disk, not in the cost reader, not in a returned object.

Nothing here opens a socket. Every call is a :class:`~clue_api.arv2.calls.CallSpec` handed to the
:class:`~clue_api.arv2.calls.ProviderCaller` the constructor is given, which is what makes the
raw record, the estimate row and the retry arithmetic properties of the lane rather than of this
file.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import SecretStr

from clue_api.arv2.calls import (
    CallCost,
    CallResult,
    CallSpec,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.transport import BROWSER_USER_AGENT, HttpResponse, json_request

#: The provider name every AI Ark ledger row and raw record carries, and the key the wrapper
#: latches a halt against.
PROVIDER: Final = "ai_ark"

AI_ARK_BASE_URL: Final = "https://api.ai-ark.com/api/developer-portal"

#: Per-request timeout. A fixed constant rather than a setting: it is not an operator dial, and
#: an env knob nobody turns is a knob that only rots (CLAUDE.md parity rule).
AI_ARK_TIMEOUT_S: Final = 120.0

#: Every spelling of a birth date seen in an AI Ark body. Appendix A law 3's drop list.
BIRTH_DATE_KEYS: Final[frozenset[str]] = frozenset({"birth_date", "birthDate", "birthday"})

#: The one halt reason this provider raises. Money truth *blocks* (master plan §2 item 3): a
#: provider that will not sell must stop the lane, not be retried into a bill.
CREDIT_HALT_REASON: Final = "ai_ark_credit_exhausted_or_denied"

COMPANY_CREDITS_PER_RESULT: Final = Decimal("0.1")
PERSON_CREDITS_PER_RESULT: Final = Decimal("0.5")
EXPORT_PROFILE_CREDITS: Final = Decimal("0.5")
EXPORT_EMAIL_CREDITS: Final = Decimal("0.5")
PHONE_CREDITS: Final = Decimal("5")
MAX_ROLE_PAGE_SIZE: Final = 100
SENIORITY_VALUES: Final = frozenset(
    {
        "owner",
        "founder",
        "c_suite",
        "partner",
        "vp",
        "head",
        "director",
        "manager",
        "senior",
        "entry",
        "intern",
        "mid-level",
    }
)


@cache
def function_values() -> frozenset[str]:
    """Provider vocabulary, pinned from its public CSV (2026-09-22). No request-time fetch."""
    return frozenset(Path(__file__).with_name("ai_ark_functions.txt").read_text().splitlines())


class AiArkResponseError(ValueError):
    """An HTTP failure or malformed provider result, distinct from a documented empty result."""

    def __init__(self, status: int, code: str = "ai_ark_response_failed") -> None:
        self.status = status
        super().__init__(f"{code}: HTTP {status}")


#: The largest page :meth:`AiArkClient.people_by_name` will ask for. This is a *spend law*, not
#: the provider's limit (it allows 100 per page): the method exists to resolve one named person
#: against one domain, and a bigger page would be a company roster fetched by another route —
#: exactly the thing this client has no method for, by construction.
MAX_PEOPLE_PAGE_SIZE: Final = 3

#: What an email export is worth as evidence. ``verified_smtp`` is a mailbox the provider
#: confirmed; ``catch_all_valid`` is a domain that accepts everything, so the address is plausible
#: but unproven; ``not_found`` is the honest empty.
EmailVerdict = Literal["verified_smtp", "catch_all_valid", "not_found"]


# -- value types -------------------------------------------------------------------------------


@dataclass(frozen=True)
class AiArkCompany:
    """One company record, with the whole record kept as ``raw`` for later re-parsing.

    Every named field is an explicit mapping of an AI Ark path (``summary.name``, ``link.domain``,
    …) rather than a guess at a key called ``name``: the record nests everything one level down,
    and reading the wrong key would silently produce an empty profile rather than an error.

    ``cost`` is what the request that returned this record cost — credit-metered, so
    ``cost.cost_source`` is ``metered``. It is ``None`` only on a record built by
    :func:`company_from_record` directly, which is a pure mapper with no call behind it.
    """

    name: str | None
    domain: str | None
    linkedin: str | None
    industry: str | None
    employee_count: int | None
    revenue: str | None
    technologies: tuple[str, ...]
    location: Mapping[str, Any] | None
    raw: Mapping[str, Any]
    cost: CallCost | None = None
    ark_id: str | None = None


@dataclass(frozen=True)
class AiArkPerson:
    """One person record from a name-scoped search, with the whole record kept as ``raw``."""

    full_name: str | None
    title: str | None
    headline: str | None
    linkedin_url: str | None
    location: Mapping[str, Any] | None
    current_company: str | None
    current_company_domain: str | None
    department: Mapping[str, Any] | None
    ark_id: str | None
    raw: Mapping[str, Any]
    current_company_id: str | None = None


@dataclass(frozen=True)
class AiArkPeople:
    """One company-scoped people result page and what that search cost.

    A people search bills 0.5 credit **per record returned**, so the cost belongs to the page,
    not to any one person in it: attaching it to each :class:`AiArkPerson` would make a caller
    that sums its people over-count the run by the page size. This is the page.

    It iterates and measures like the list it replaces, so ``for person in people`` and
    ``len(people)`` keep meaning what they meant before the cost was carried.
    """

    people: tuple[AiArkPerson, ...]
    cost: CallCost
    page: int = 0
    size: int = MAX_PEOPLE_PAGE_SIZE
    total_elements: int | None = None
    total_pages: int | None = None
    has_more: bool | None = None
    track_id: str | None = None

    def __iter__(self) -> Iterator[AiArkPerson]:
        return iter(self.people)

    def __len__(self) -> int:
        return len(self.people)

    def __getitem__(self, index: int) -> AiArkPerson:
        return self.people[index]


@dataclass(frozen=True)
class AiArkEmailExport:
    """One ``/v1/people/export/single`` result: the email block plus the identity around it.

    ``raw_email_block`` is kept whole because the verification metadata is the product here — an
    address flattened away from its ``status``/``domainType`` pair is a claim nobody can grade
    (contract notes §7 item 6).

    ``cost`` is the export request's money view; it is ``None`` only on a record built by
    :func:`email_export_from_record` directly, which is a pure mapper with no call behind it.
    """

    address: str | None
    status: str | None
    domain_type: str | None
    sub_status: str | None
    mx_record: str | None
    mx_provider: str | None
    mx_found: bool | None
    mx_google: bool | None
    free: bool | None
    generic: bool | None
    found: bool
    checked_at: str | None
    verdict: EmailVerdict
    full_name: str | None
    title: str | None
    current_company: str | None
    certifications: tuple[Mapping[str, Any], ...]
    raw_email_block: Mapping[str, Any]
    cost: CallCost | None = None
    ark_id: str | None = None
    linkedin_url: str | None = None


@dataclass(frozen=True)
class AiArkPhone:
    numbers: tuple[str, ...]
    ark_id: str | None
    linkedin_url: str | None
    cost: CallCost | None = None


def phone_from_record(record: Mapping[str, Any]) -> AiArkPhone:
    """Preserve provider ordering; accept E.164 only, without inventing a country code."""
    numbers: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif (
            isinstance(value, str)
            and re.fullmatch(r"\+[1-9]\d{6,14}", value)
            and value not in numbers
        ):
            numbers.append(value)

    collect(record.get("data"))
    return AiArkPhone(tuple(numbers), _text(record.get("id")), _text(record.get("linkedin")))


def role_search_body(
    titles: Sequence[str],
    *,
    company_id: str | None = None,
    domain: str | None = None,
    seniority: Sequence[str] = (),
    functions: Sequence[str] = (),
    page: int = 0,
    size: int = 10,
) -> dict[str, Any]:
    """SMART is for the title; the employer is an exact, required scope."""
    if bool(company_id) == bool(domain):
        raise ValueError("provide exactly one company_id or domain")
    if type(page) is not int or type(size) is not int or page < 0 or not 1 <= size <= 100:
        raise ValueError("page must be >= 0 and size between 1 and 100")
    if page * size >= 10_000:
        raise ValueError("people search pagination cannot exceed 10000 records")
    terms = sorted({_require_text(title, "title").casefold() for title in titles})
    if not terms or len(terms) > 300:
        raise ValueError("titles must contain between 1 and 300 non-blank values")
    if set(seniority) - SENIORITY_VALUES:
        raise ValueError("unsupported seniority value")
    if set(functions) - function_values():
        raise ValueError("unsupported department/function value")
    contact: dict[str, Any] = {
        "experience": {
            "latest": {
                "title": {
                    "any": {
                        "include": {
                            "mode": "SMART",
                            "content": terms,
                        }
                    }
                }
            }
        },
    }
    body: dict[str, Any] = {"contact": contact, "page": page, "size": size}
    if company_id:
        contact["company"] = {
            "latest": {"any": {"include": [_require_text(company_id, "company_id")]}}
        }
    else:
        body["account"] = {"domain": {"any": {"include": [_require_text(domain or "", "domain")]}}}
    for name, values in (("seniority", seniority), ("departmentAndFunction", functions)):
        if values:
            contact[name] = {"any": {"include": sorted(set(values))}}
    return body


# -- pure rules --------------------------------------------------------------------------------


def scrub_birth_dates(value: object) -> object:
    """Appendix A law 3: recursively drop every birth-date key from a parsed body.

    Handed to the wrapper as ``CallSpec.raw_scrubber``, whose output *replaces* the response for
    the rest of the call — so this must drop the birth-date keys and nothing else, or the cost
    reader and the halt rule would be reading a body the provider never sent.
    """
    if isinstance(value, dict):
        return {
            key: scrub_birth_dates(item)
            for key, item in value.items()
            if key not in BIRTH_DATE_KEYS
        }
    if isinstance(value, list):
        return [scrub_birth_dates(item) for item in value]
    return value


def ai_ark_halt_rule(response: HttpResponse) -> str | None:
    """Money truth: recognise a provider that will not sell, so the wrapper latches it.

    A 402 or 403 is the explicit refusal. Any other 4xx/5xx whose body names "credit" is the
    implicit one — AI Ark reports exhaustion in prose rather than a status of its own. Retrying
    either would burn the run's whole attempt budget against a wall.
    """
    if response.status in (402, 403):
        return CREDIT_HALT_REASON
    if response.status >= 400 and "credit" in response.body.decode("utf-8", "replace").lower():
        return CREDIT_HALT_REASON
    return None


def email_verdict(output: Mapping[str, Any]) -> EmailVerdict:
    """Grade one ``email.output[]`` entry (contract notes §7 item 6).

    ``VALID`` + ``SMTP`` means the mailbox itself answered — the only ``verified`` this lane
    recognises. ``VALID`` on any other domain type (``CATCH_ALL``) means the domain accepts every
    address, so the mailbox is unproven. Anything else is ``not_found``.
    """
    status = str(output.get("status") or "").upper()
    domain_type = str(output.get("domainType") or "").upper()
    if status == "VALID":
        return "verified_smtp" if domain_type == "SMTP" else "catch_all_valid"
    return "not_found"


# -- body readers ------------------------------------------------------------------------------


def _dig(value: object, *path: str) -> object:
    """Walk a nested mapping, yielding ``None`` the moment the path stops existing."""
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _json_body(response: HttpResponse) -> Mapping[str, Any] | None:
    """The response body as a JSON object, or ``None`` when it is not one.

    A cost reader must never raise on a shape it did not expect: the wrapper would record the
    call as ``cost_unreadable`` and fall back to the estimate, which is a worse answer than the
    zero a body with no ``content`` list honestly implies.
    """
    try:
        parsed = json.loads(response.body)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _content(body: Mapping[str, Any] | None) -> list[Any]:
    """The page's ``content`` list — the record set both search endpoints bill by."""
    if body is None:
        return []
    content = body.get("content")
    return content if isinstance(content, list) else []


def _first_email_output(body: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """``email.output[0]``, or an empty mapping when the export returned no email block."""
    output = _dig(body, "email", "output")
    if isinstance(output, list) and output and isinstance(output[0], Mapping):
        return output[0]
    return {}


def company_cost_reader(response: HttpResponse) -> CostReading:
    """0.1 credit per company record actually returned (contract notes §2).

    Returned as an explicit ``Decimal(0)`` rather than ``None`` when nothing came back, so the
    wrapper records a real zero instead of substituting the pre-spend estimate.
    """
    return _result_count_cost(response, COMPANY_CREDITS_PER_RESULT)


def people_cost_reader(response: HttpResponse) -> CostReading:
    """0.5 credit per person record actually returned (contract notes §2)."""
    return _result_count_cost(response, PERSON_CREDITS_PER_RESULT)


def _result_count_cost(response: HttpResponse, price: Decimal) -> CostReading:
    reported = _reported_credit(response)
    if reported is not None:
        return reported
    body = _json_body(response)
    if response.status != 404 and (body is None or not isinstance(body.get("content"), list)):
        return CostReading(extras={"credit_basis": "unknown"})
    count = len(_content(body))
    return _channel_cost(response, price * count, bool(count))


def export_cost_reader(response: HttpResponse) -> CostReading:
    """Single export: one credit if found, zero if empty (current provider contract)."""
    reported = _reported_credit(response)
    if reported is not None:
        return reported
    if response.status != 404 and not isinstance(
        (_json_body(response) or {}).get("email"), Mapping
    ):
        return CostReading(extras={"credit_basis": "unknown"})
    return _channel_cost(
        response,
        EXPORT_PROFILE_CREDITS + EXPORT_EMAIL_CREDITS,
        bool(_first_email_output(_json_body(response)).get("found")),
    )


def phone_cost_reader(response: HttpResponse) -> CostReading:
    reported = _reported_credit(response)
    if reported is not None:
        return reported
    body = _json_body(response) or {}
    found = bool(phone_from_record(body).numbers)
    if response.status != 404 and (
        not isinstance(body.get("data"), list) or (_has_phone_data(body.get("data")) and not found)
    ):
        return CostReading(extras={"credit_basis": "unknown"})
    return _channel_cost(response, PHONE_CREDITS, found)


def _has_phone_data(value: Any) -> bool:
    return any(_has_phone_data(item) for item in value) if isinstance(value, list) else bool(value)


def _reported_credit(response: HttpResponse) -> CostReading | None:
    reported = next((v for k, v in response.headers.items() if k.lower() == "x-credit"), None)
    if reported is not None:
        try:
            charge = abs(Decimal(reported))
            if charge.is_finite():
                return CostReading(credits=charge, extras={"credit_basis": "provider_header"})
        except ArithmeticError:
            pass
    return None


def _channel_cost(response: HttpResponse, price: Decimal, found: bool) -> CostReading:
    if response.status == 404 or 200 <= response.status < 300:
        if response.status != 404 and _json_body(response) is None:
            return CostReading(extras={"credit_basis": "unknown"})
        return CostReading(
            credits=price if found else Decimal(0),
            extras={"credit_basis": "documented_result_arithmetic"},
            inferred=True,
        )
    return CostReading(extras={"credit_basis": "unknown"})


def response_record(result: CallResult, *, empty_404: bool = False) -> Mapping[str, Any]:
    """Only caller-selected endpoints may turn a 404 into an honest empty."""
    response = result.response
    if response.status == 404 and empty_404:
        return {}
    if not 200 <= response.status < 300:
        raise AiArkResponseError(response.status)
    body = _json_body(response)
    if body is None:
        raise AiArkResponseError(response.status, "ai_ark_malformed_body")
    return body


# -- record mapping ----------------------------------------------------------------------------


def _text(value: object) -> str | None:
    """A non-blank string, or ``None``. A blank field is an absent field, never an empty claim."""
    return value if isinstance(value, str) and value.strip() else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _current_position(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """``position_groups[0]`` — AI Ark returns the current role first."""
    groups = record.get("position_groups")
    if isinstance(groups, list) and groups and isinstance(groups[0], Mapping):
        return groups[0]
    return {}


def _fold_company_url(value: str | None) -> str | None:
    """A LinkedIn company URL in the form two spellings of the same page share.

    Lower-cased, without the scheme, without ``www.`` and without the trailing slash — the same
    fold the person lock uses on profile URLs, kept here because this module may not import the
    toolbelt.
    """
    if value is None:
        return None
    folded = value.strip().lower().rstrip("/")
    for scheme in ("https://", "http://"):
        folded = folded.removeprefix(scheme)
    folded = folded.removeprefix("www.")
    return folded or None


def _current_company_domain(record: Mapping[str, Any], current_company: str | None) -> str | None:
    """The current employer's domain, or ``None`` when it cannot be target-locked.

    Wire fact: ``position_groups[0].company`` carries no domain at all, while the person record's
    top-level ``company`` block does (``company.link.domain``). That block is not labelled
    "current", so something has to say the two blocks are the same employer before its domain is
    attached — a previous employer's domain on a person who has moved is a target-lock error, and
    an empty field is the correct output.

    The proof runs as a ladder, strongest rung first:

    1. **The LinkedIn company URL.** Both blocks carry it (``position_groups[0].company.url`` and
       ``company.link.linkedin``), and it is the stable key the *name* never was: the live record
       for Alexander Semien at Cogent names the position ``"Cogent"`` and the company block
       ``"Cogent Security"``, both pointing at ``/company/cogentsecurity``. Two equal URLs are the
       same company page, whatever either block spells the name as.
    2. **Containment of the folded names, by whole word**, for a record whose blocks carry no URL:
       ``"cogent"`` inside ``"cogent security"`` is the same employer written short. The
       containment is over *words*, never over characters: ``"box"`` sits inside ``"dropbox"`` and
       ``"meta"`` inside ``"metabase"``, and a mover whose old employer's name is spelled inside
       the new one would otherwise be handed the wrong domain — which the caller then compares to
       the account, so a stale committee row would pass the employer lock. Two names that share no
       whole word are two employers, and so is an employer the record only half-states.
    3. Otherwise ``None`` — the domain is genuinely unknown, which is a different answer from a
       *different* employer, and the caller is the one that decides what to do with it.
    """
    domain = _text(_dig(record, "company", "link", "domain"))
    if domain is None:
        return None
    position_url = _fold_company_url(_text(_dig(_current_position(record), "company", "url")))
    company_url = _fold_company_url(_text(_dig(record, "company", "link", "linkedin")))
    if position_url is not None and position_url == company_url:
        return domain
    embedded_name = _text(_dig(record, "company", "summary", "name"))
    if current_company is None or embedded_name is None:
        return None
    left, right = current_company.strip().lower(), embedded_name.strip().lower()
    if _one_name_contains_the_other(left, right):
        return domain
    return None


def _one_name_contains_the_other(left: str, right: str) -> bool:
    """Is one folded company name the other written short — by whole words, never by characters?

    A prefix ("cogent" / "cogent security") and a shared word set ("acme labs" / "labs acme") both
    count; a name that merely spells the other inside a word ("box" / "dropbox") does not.
    """
    if right.startswith(left + " ") or left.startswith(right + " "):
        return True
    left_words, right_words = set(left.split()), set(right.split())
    if not left_words or not right_words:
        return False
    return left_words <= right_words or right_words <= left_words


def company_from_record(record: Mapping[str, Any]) -> AiArkCompany:
    """Map one ``/v1/companies`` record onto :class:`AiArkCompany`."""
    technologies = record.get("technologies")
    names: tuple[str, ...] = ()
    if isinstance(technologies, list):
        names = tuple(
            name
            for name in (_text(_dig(item, "name")) for item in technologies)
            if name is not None
        )
    return AiArkCompany(
        name=_text(_dig(record, "summary", "name")),
        domain=_text(_dig(record, "link", "domain")),
        linkedin=_text(_dig(record, "link", "linkedin")),
        industry=_text(_dig(record, "summary", "industry")),
        employee_count=_integer(_dig(record, "summary", "staff", "total")),
        revenue=_text(_dig(record, "financial", "revenue", "annual", "amount")),
        technologies=names,
        location=_mapping(_dig(record, "location", "headquarter")),
        raw=record,
        ark_id=_text(record.get("id")),
    )


def person_from_record(record: Mapping[str, Any]) -> AiArkPerson:
    """Map one ``/v1/people`` record onto :class:`AiArkPerson`."""
    current_company = _text(_dig(_current_position(record), "company", "name"))
    return AiArkPerson(
        full_name=_text(_dig(record, "profile", "full_name")),
        title=_text(_dig(record, "profile", "title")),
        headline=_text(_dig(record, "profile", "headline")),
        linkedin_url=_text(_dig(record, "link", "linkedin")),
        location=_mapping(record.get("location")),
        current_company=current_company,
        current_company_id=_text(_dig(_current_position(record), "company", "id")),
        current_company_domain=_current_company_domain(record, current_company),
        department=_mapping(record.get("department")),
        ark_id=_text(record.get("id")),
        raw=record,
    )


def email_export_from_record(record: Mapping[str, Any]) -> AiArkEmailExport:
    """Map one ``/v1/people/export/single`` body onto :class:`AiArkEmailExport`.

    The export returns the same person object as a search plus one extra ``email`` block, so the
    identity fields are read from the same paths a search record uses.
    """
    email_block = _mapping(record.get("email")) or {}
    output = _first_email_output(record)
    certifications = record.get("certifications")
    certified: tuple[Mapping[str, Any], ...] = ()
    if isinstance(certifications, list):
        certified = tuple(item for item in certifications if isinstance(item, Mapping))
    return AiArkEmailExport(
        address=_text(output.get("address")),
        status=_text(output.get("status")),
        domain_type=_text(output.get("domainType")),
        sub_status=_text(output.get("subStatus")),
        mx_record=_text(_dig(output, "mx", "record")),
        mx_provider=_text(_dig(output, "mx", "provider")),
        mx_found=_flag(_dig(output, "mx", "found")),
        mx_google=_flag(_dig(output, "mx", "google")),
        free=_flag(output.get("free")),
        generic=_flag(output.get("generic")),
        found=output.get("found") is True,
        checked_at=_text(output.get("date")),
        verdict=email_verdict(output),
        full_name=_text(_dig(record, "profile", "full_name")),
        title=_text(_dig(record, "profile", "title")),
        current_company=_text(_dig(_current_position(record), "company", "name")),
        certifications=certified,
        raw_email_block=email_block,
        ark_id=_text(record.get("id")),
        linkedin_url=_text(_dig(record, "link", "linkedin")),
    )


def _require_text(value: str, name: str) -> str:
    """A required, non-blank request field. Blank would silently widen the query, not narrow it."""
    stripped = (value or "").strip()
    if not stripped:
        raise ValueError(f"{name} must be a non-blank string")
    return stripped


# -- the client --------------------------------------------------------------------------------


_TOKEN_MUTEXES: dict[str, threading.Lock] = {}
_TOKEN_LAST: dict[str, float] = {}
_TOKEN_MUTEX_GUARD = threading.Lock()


class AiArkClient:
    """Builds AI Ark requests and reads AI Ark bodies. It never sends anything itself.

    Pacing is the one piece of state: AI Ark rate-limits harder than it documents, so at least
    ``min_gap_s`` elapses between the end of one call and the start of the next. ``sleep`` and
    ``monotonic`` are injectable so that pacing is a testable property rather than a wall-clock
    assumption.
    """

    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr,
        *,
        min_gap_s: float,
        base_url: str = AI_ARK_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._min_gap_s = min_gap_s
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_sent_at: float | None = None
        self._last_call: CallResult | None = None
        self._token_scope = hashlib.sha256(api_key.get_secret_value().encode()).hexdigest()
        # Injected clocks own their test timeline; live clients share a token clock.
        self._shared_clock = monotonic is time.monotonic and sleep is time.sleep
        with _TOKEN_MUTEX_GUARD:
            self._token_mutex = _TOKEN_MUTEXES.setdefault(self._token_scope, threading.Lock())

    @property
    def last_call(self) -> CallResult | None:
        """The wrapper's result for the most recent call — the audit handle.

        The parsed return types deliberately carry no ``raw_ref`` or ledger row id: a caller that
        needs to cite the evidence, or a test that has to prove what a call cost, reads it here.
        """
        return self._last_call

    def company_by_domain(self, domain: str) -> AiArkCompany | None:
        """The company record for one exact domain, or ``None`` when AI Ark knows of none.

        Estimated at one result (0.1 credit); the ledger records 0.1 per record actually returned.
        """
        target = _require_text(domain, "domain")
        body = {
            "account": {"domain": {"any": {"include": [target]}}},
            "page": 0,
            "size": 1,
        }
        result = self._send(
            operation="v1/companies",
            label=f"company-{target}",
            path="/v1/companies",
            json_body=body,
            estimate=SpendEstimate(credits=COMPANY_CREDITS_PER_RESULT),
            cost_reader=company_cost_reader,
        )
        records = _content(_json_body(result.response))
        first = records[0] if records else None
        if not isinstance(first, Mapping):
            return None
        return replace(company_from_record(first), cost=result.call_cost)

    def companies_exact(self, domain: str) -> tuple[AiArkCompany, ...]:
        target = _require_text(domain, "domain")
        result = self._send(
            operation="v1/companies",
            label="committee-company-lock",
            path="/v1/companies",
            json_body={"account": {"domain": {"any": {"include": [target]}}}, "page": 0, "size": 2},
            estimate=SpendEstimate(credits=COMPANY_CREDITS_PER_RESULT * 2),
            cost_reader=company_cost_reader,
        )
        record = response_record(result)
        if not isinstance(record.get("content"), list):
            raise AiArkResponseError(result.response.status, "ai_ark_missing_content")
        return tuple(company_from_record(p) for p in record["content"] if isinstance(p, Mapping))

    def people_by_name(
        self,
        name_variants: Sequence[str],
        domain: str,
        *,
        size: int = MAX_PEOPLE_PAGE_SIZE,
        strict_response: bool = False,
    ) -> AiArkPeople:
        """People matching any of ``name_variants`` **at** ``domain`` — never a roster.

        This named-lookup method never asks for a company roster. A name-scoped,
        domain-locked query is what makes the result target-locked (the canary's same-name check:
        464 unscoped "Mark Hoffman"s collapse to exactly one when the domain is added), and it is
        what keeps the spend bounded — a roster is 0.5 credits per person returned, so an
        unscoped page is the most expensive mistake this provider offers.

        Refused before the wire: a page bigger than :data:`MAX_PEOPLE_PAGE_SIZE`, no usable name
        variant, or no domain — each of those would turn this call into the roster it must not be.
        """
        if size > MAX_PEOPLE_PAGE_SIZE:
            raise ValueError(
                f"size must be <= {MAX_PEOPLE_PAGE_SIZE} (asked for {size}): a larger page is a "
                "company roster, which this client does not offer"
            )
        variants = [variant.strip() for variant in name_variants if variant and variant.strip()]
        if not variants:
            raise ValueError(
                "name_variants must contain at least one non-blank name: an unnamed people "
                "search is a company roster, which this client does not offer"
            )
        target = _require_text(domain, "domain")
        body = {
            "contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": variants}}}},
            "account": {"domain": {"any": {"include": [target]}}},
            "page": 0,
            "size": size,
        }
        result = self._send(
            operation="v1/people",
            label="bound-person-lookup" if strict_response else f"people-{variants[0]}-{target}",
            empty_404=strict_response,
            path="/v1/people",
            json_body=body,
            estimate=SpendEstimate(credits=PERSON_CREDITS_PER_RESULT * size),
            cost_reader=people_cost_reader,
        )
        response_body = (
            response_record(result, empty_404=True)
            if strict_response
            else _json_body(result.response)
        )
        if (
            strict_response
            and result.response.status != 404
            and not isinstance((response_body or {}).get("content"), list)
        ):
            raise AiArkResponseError(result.response.status, "ai_ark_missing_content")
        return AiArkPeople(
            people=tuple(
                person_from_record(record)
                for record in _content(response_body)
                if isinstance(record, Mapping)
            ),
            cost=result.call_cost,
        )

    def people_by_roles(
        self,
        titles: Sequence[str],
        *,
        company_id: str | None = None,
        domain: str | None = None,
        seniority: Sequence[str] = (),
        functions: Sequence[str] = (),
        page: int = 0,
        size: int = 10,
    ) -> AiArkPeople:
        body = role_search_body(
            titles,
            company_id=company_id,
            domain=domain,
            seniority=seniority,
            functions=functions,
            page=page,
            size=size,
        )
        result = self._send(
            operation="v1/people",
            label="committee-role-search",
            path="/v1/people",
            json_body=body,
            estimate=SpendEstimate(credits=PERSON_CREDITS_PER_RESULT * size),
            empty_404=True,
            cost_reader=people_cost_reader,
        )
        record = response_record(result, empty_404=True)
        if result.response.status != 404 and not isinstance(record.get("content"), list):
            raise AiArkResponseError(result.response.status, "ai_ark_missing_content")
        last = record.get("last")
        total_pages = _integer(record.get("totalPages"))
        return AiArkPeople(
            people=tuple(person_from_record(p) for p in _content(record) if isinstance(p, Mapping)),
            cost=result.call_cost,
            page=page,
            size=size,
            total_elements=0
            if result.response.status == 404
            else _integer(record.get("totalElements")),
            total_pages=total_pages,
            has_more=(
                False
                if result.response.status == 404
                else not last
                if isinstance(last, bool)
                else page + 1 < total_pages
                if total_pages is not None
                else None
            ),
            track_id=_text(record.get("trackId")),
        )

    def find_phone(
        self,
        *,
        domain: str | None = None,
        name: str | None = None,
        linkedin_url: str | None = None,
    ) -> AiArkPhone:
        if linkedin_url is not None:
            if domain is not None or name is not None:
                raise ValueError("phone lookup accepts linkedin_url OR domain and name")
            body = {"linkedin": _require_text(linkedin_url, "linkedin_url")}
        else:
            body = {
                "domain": _require_text(domain or "", "domain"),
                "name": _require_text(name or "", "name"),
            }
        result = self._send(
            operation="v1/people/mobile-phone-finder",
            label="selected-person-phone",
            path="/v1/people/mobile-phone-finder",
            json_body=body,
            estimate=SpendEstimate(credits=PHONE_CREDITS),
            empty_404=True,
            cost_reader=phone_cost_reader,
        )
        record = response_record(result, empty_404=True)
        if result.response.status != 404 and not isinstance(record.get("data"), list):
            raise AiArkResponseError(result.response.status, "ai_ark_missing_phone_data")
        phone = phone_from_record(record)
        if _has_phone_data(record.get("data")) and not phone.numbers:
            raise AiArkResponseError(result.response.status, "ai_ark_unusable_phone_data")
        return replace(phone, cost=result.call_cost)

    def export_email(
        self,
        linkedin_url: str | None = None,
        *,
        person_id: str | None = None,
    ) -> AiArkEmailExport:
        """Export one selected person by provider ID or LinkedIn URL, with the email verdict.

        One credit when found, zero for the documented no-email result. A selected search ID
        avoids another paid named-person search; export itself remains a billable operation.
        """
        if person_id is not None and linkedin_url is not None:
            raise ValueError("provide exactly one person_id or linkedin_url")
        body = (
            {"id": _require_text(person_id, "person_id")}
            if person_id is not None
            else {"url": _require_text(linkedin_url or "", "linkedin_url")}
        )
        result = self._send(
            operation="v1/people/export/single",
            label="selected-person-email",
            path="/v1/people/export/single",
            json_body=body,
            estimate=SpendEstimate(credits=EXPORT_PROFILE_CREDITS + EXPORT_EMAIL_CREDITS),
            empty_404=True,
            cost_reader=export_cost_reader,
        )
        record = response_record(result, empty_404=True)
        if result.response.status != 404 and not isinstance(record.get("email"), Mapping):
            raise AiArkResponseError(result.response.status, "ai_ark_missing_email_data")
        return replace(email_export_from_record(record), cost=result.call_cost)

    def _send(
        self,
        *,
        operation: str,
        label: str,
        path: str,
        json_body: Mapping[str, Any],
        estimate: SpendEstimate,
        cost_reader: Callable[[HttpResponse], CostReading],
        empty_404: bool = False,
    ) -> CallResult:
        """Pace, then hand one fully-built :class:`CallSpec` to the wrapper."""
        spec = CallSpec(
            provider=PROVIDER,
            operation=operation,
            label=label,
            request=json_request(
                "POST",
                f"{self._base_url}{path}",
                headers=self._headers(),
                json_body=dict(json_body),
                timeout_s=AI_ARK_TIMEOUT_S,
            ),
            estimate=estimate,
            halt_rule=ai_ark_halt_rule,
            cost_reader=cost_reader,
            raw_scrubber=scrub_birth_dates,
            empty_statuses=frozenset({404}) if empty_404 else frozenset(),
        )
        with self._token_mutex:
            if self._shared_clock:
                self._last_sent_at = _TOKEN_LAST.get(self._token_scope)
            self._pace()
            try:
                result = self._caller.call(spec)
            finally:
                self._last_sent_at = self._monotonic()
                if self._shared_clock:
                    _TOKEN_LAST[self._token_scope] = self._last_sent_at
        self._last_call = result
        return result

    def _headers(self) -> dict[str, str]:
        """The four headers every AI Ark request needs. ``X-TOKEN`` is redacted before any record.

        The browser ``User-Agent`` is load-bearing, not cosmetic: Cloudflare answers a default
        client string with 403 error 1010, which the halt rule would (correctly, and uselessly)
        read as a refusal to sell.
        """
        return {
            "X-TOKEN": self._api_key.get_secret_value(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": BROWSER_USER_AGENT,
        }

    def _pace(self) -> None:
        """Sleep out whatever is left of ``min_gap_s`` since the previous call returned."""
        if self._last_sent_at is None:
            return
        remaining = self._min_gap_s - (self._monotonic() - self._last_sent_at)
        if remaining > 0:
            self._sleep(remaining)
