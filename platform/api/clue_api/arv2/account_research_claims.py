"""Deterministic claim mappers: provider records and model output → typed claim drafts.

Master plan §8's two claim species meet here. A **deterministic** record (an ATS posting, an AI Ark
company row, a downloaded media item) becomes a claim in *code*, so the model never retypes a fact
a provider already stated — the value, the raw path it came from and the tier are all decided by
this module. A **prose** claim arrives already typed by the structuring pass, and this module only
carries the annotations across (the verbatim verdict, the schema verdict, the mode that produced
it) without re-deciding anything.

Three rules the shapes encode, each of which has failed the other way in a real run:

* **A provider record cites its raw path, never a fabricated URL.** ``https://api.ai-ark.com/…`` is
  not a page anybody can read, so an AI Ark claim carries ``source_url=None`` plus the exact
  ``json_path`` of the value inside the record. The lenient writer marks it ``source_missing``,
  which is the honest state: the evidence is a provider record, and the display layer says so.
* **A negative is born unsafe.** Anything in ``negatives_and_risks`` is by definition something
  that went wrong for this company; it is recorded (it is real research) and it is never outreach
  material. Same for a fit verdict, which is an opinion about the client's own ICP.
* **Leniency lives in code, not in a prompt.** A ``fail`` verdict citing no contrary evidence is
  downgraded to ``unclear`` here, so the rule holds even when the model forgets it (constitution
  §5), and a committee candidate with no confirming URL is dropped rather than written.

Every function is pure: no I/O, no provider, no database. The tools call them and hand the drafts
to :meth:`ToolRuntime.write`, which is the one write path.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from clue_api.arv2.ai_ark_client import AiArkCompany
from clue_api.arv2.ats_client import BoardPostings
from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.structuring_client import (
    FieldCatalog,
    NegativeOrRisk,
    StructuredClaim,
    StructuredOutput,
    check_value_schema,
)
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    RunId,
    is_valid_field_key,
)
from clue_obs import get_logger

log = get_logger("clue_api.arv2.account_research_claims")

__all__ = [
    "ALWAYS_UNSAFE_FIELDS",
    "COMMITTEE_FIELD",
    "FIT_VERDICT_FIELD",
    "MEDIA_INDEX_FIELD",
    "REPUTATION_RISK_FIELD",
    "ClaimInput",
    "JobScope",
    "agent_claims",
    "ai_ark_company_claims",
    "ats_posting_claims",
    "coerce_scalar",
    "committee_candidate_claims",
    "fit_verdict_claims",
    "media_index_claim",
    "negative_claims",
    "normalise_proposed_key",
    "revenue_band_bucket",
    "structured_claims",
    "unconfirmed_candidates",
]

#: The two keys that are never outreach material, whoever writes them (master plan §4; the
#: constitution's §5 verdict rule). Forced here rather than trusted to a caller.
REPUTATION_RISK_FIELD = "account.reputation_risk"
FIT_VERDICT_FIELD = "account.icp_fit_verdict"
ALWAYS_UNSAFE_FIELDS: frozenset[str] = frozenset({REPUTATION_RISK_FIELD, FIT_VERDICT_FIELD})

COMMITTEE_FIELD = "account.committee_candidate"
MEDIA_INDEX_FIELD = "account.media_layer_index"

#: What the model's confidence word is worth as a number. Anything unreadable is 0.5 — the
#: substrate's own default — rather than a flattering guess.
_CONFIDENCE_WORDS: Mapping[str, float] = {"high": 0.8, "medium": 0.6, "low": 0.5}

#: The suffix a downgraded verdict carries, so a human reading the claim sees *why* it says
#: ``unclear`` when the agent said ``fail``.
DOWNGRADE_SUFFIX = " (downgraded: no contrary evidence cited)"


@dataclass(frozen=True)
class JobScope:
    """Everything a tool needs to know about the one account job it serves.

    It is engine authority: the model can read every part of it (through ``read_account_state``)
    and change none of it. Every claim written in the job is stamped from here, which is what makes
    "which run wrote this, for which workspace, about which account" a query rather than a guess.
    """

    workspace_id: str
    project_id: str
    project_run_id: UUID
    run_id: UUID
    job_id: UUID
    account_id: EntityId
    account_name: str
    account_domain: str
    icp_markdown: str
    persona_markdown: str
    already_established: str
    effort: str
    committee_cap: int
    today: date


class ClaimInput(BaseModel):
    """One claim the model asks ``write_claims`` to store.

    ``evidence_span`` is required and non-empty by schema: master plan §2 makes a claim without a
    quote a claim nobody can audit, and the cheapest place to say so is the argument schema, where
    the refusal names the field and costs nothing.
    """

    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1)
    value: JsonValue
    evidence_span: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    priority: int = Field(ge=1, le=3)
    outreach_safe: bool = True
    confidence: float = Field(0.6, ge=0, le=1)
    corrects_claim_id: str | None = None


def _without_nones(row: Mapping[str, Any], *, keep: tuple[str, ...] = ()) -> dict[str, Any]:
    """Drop the optional keys the record did not answer, keeping the field's required ones.

    A registered property is typed (``{"type": "string"}``), and the schema check is
    ``isinstance``, so writing an explicit ``null`` for "we saw no department" makes a correct,
    deterministically-mapped claim land ``schema_valid=False`` — which is the marker the audit
    skill and the display layer read as *"the extraction did not fit the field"*. Omitting the key
    is also the more honest record: absent is not null.

    ``keep`` names the field's **required** keys. They stay even when they are ``None``, because a
    required key nothing answered really is a claim that does not fit its field, and the schema
    marker should say so rather than be dodged by deleting the evidence of it.
    """
    return {key: value for key, value in row.items() if value is not None or key in keep}


def _draft(
    scope: JobScope,
    *,
    field_key: str,
    value: JsonValue,
    method: ExtractionMethod,
    source_url: str | None,
    evidence_span: str | None,
    priority: int,
    outreach_safe: bool,
    confidence: float,
    source_key: str,
    markers: Mapping[str, JsonValue] | None = None,
    field_description: str | None = None,
) -> ClaimDraft:
    """One account claim, with everything the job (never the caller) decides already stamped."""
    return ClaimDraft(
        entity_id=scope.account_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        extraction_method=method,
        run_id=RunId(scope.run_id),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        workspace_id=scope.workspace_id,
        source_url=source_url,
        source_key=source_key,
        evidence_span=evidence_span,
        observed_at=None,
        confidence=confidence,
        signal_priority=priority,
        outreach_safe=outreach_safe,
        field_description=field_description,
        markers=dict(markers or {}),
    )


# -- deterministic provider records ---------------------------------------------------------------


def ats_posting_claims(postings: BoardPostings, scope: JobScope) -> list[ClaimDraft]:
    """One tier-1 claim per open requisition, each citing its own posting URL and record index.

    One claim *per posting* rather than one claim carrying the whole board: a requisition is the
    unit that opens, closes and gets quoted in outreach, and a single list-valued claim would make
    "this role is still listed" unanswerable without re-fetching. The value is still the registered
    ``list[object]`` shape — a list of one — so the field's schema is satisfied exactly.

    Priority 1: an open ABM or GTM role is the lane's strongest cheap buying signal.
    """
    drafts: list[ClaimDraft] = []
    for index, posting in enumerate(postings.postings):
        published = posting.published_at.isoformat() if posting.published_at else None
        row: JsonValue = _without_nones(
            {
                "title": posting.title,
                "dept": posting.department,
                "published": published,
                "days_open": posting.days_open,
                "still_listed": posting.is_listed,
                "url": posting.url,
            },
            keep=("title",),
        )
        span_parts = [
            part
            for part in (
                posting.title,
                posting.department,
                f"published {published}" if published else None,
            )
            if part
        ]
        drafts.append(
            _draft(
                scope,
                field_key="account.open_requisitions",
                value=[row],
                method=ExtractionMethod.API,
                source_url=posting.url,
                evidence_span=" — ".join(span_parts) or None,
                priority=1,
                outreach_safe=True,
                confidence=0.9,
                source_key=f"ats:{postings.board.kind}",
                markers={"json_path": f"jobs[{index}]", "board_url": postings.url},
            )
        )
    return drafts


#: The AI Ark company fields that are read off the mapped :class:`AiArkCompany` attributes, each
#: with the exact path the value was read from in the provider record
#: (``ai_ark_client.company_from_record``).
_AI_ARK_COMPANY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("linkedin", "core.company_linkedin_url", "link.linkedin"),
    ("industry", "core.industry", "summary.industry"),
    ("employee_count", "core.employee_count", "summary.staff.total"),
    ("location", "core.hq_location", "location.headquarter"),
)

#: Everything **else** the company record carries that a registered ``core.*`` field can hold, as
#: (field key, record path). Founder ruling 2026-09-08, after the recall baseline: the record was
#: being read for five fields and returned to the model as context for the rest, so a dozen
#: deterministic, tier-1 provider facts (the legal name, the founding year, the industries list,
#: the languages, the socials, the contact email, the technologies) reached the model as prose it
#: could only re-type — and the answer keys duly read ``missing``. A provider fact belongs in code.
#:
#: A path that is not in the record yields nothing, a value that does not fit the field's
#: registered schema is not claimed, and a field this deployment has not registered is not claimed:
#: an unmapped field is simply absent, never guessed at.
_AI_ARK_WIDE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("core.account_name", ("summary", "name")),
    ("core.primary_domain", ("link", "domain")),
    ("core.legal_name", ("summary", "legal_name")),
    ("core.company_about", ("summary", "description")),
    ("core.founded_year", ("summary", "founded_year")),
    ("core.company_type", ("summary", "type")),
    ("core.industries_all", ("industries",)),
    ("core.company_languages", ("languages",)),
    ("core.company_crunchbase_url", ("link", "crunchbase")),
    ("core.company_twitter_url", ("link", "twitter")),
    ("core.company_email", ("contact", "email")),
)


def _dig(value: object, *path: str) -> object:
    """Walk a nested mapping, yielding ``None`` the moment the path stops existing.

    Mirrors ``ai_ark_client._dig``: this module is pure and imports no client internals, and one
    four-line walk written twice is cheaper than a public path helper nobody else wants.
    """
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _provider_value(raw: object) -> JsonValue | None:
    """One record value as something a claim can hold: a non-blank string, a real integer, or a
    list of non-blank strings. Anything else (a nested object, a float id, a mixed list) has no
    registered home in the widened table and is left in ``raw``."""
    if isinstance(raw, str):
        return raw if raw.strip() else None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, list):
        items: list[JsonValue] = [item for item in raw if isinstance(item, str) and item.strip()]
        return items or None
    return None


def _employee_range(raw: Mapping[str, Any]) -> JsonValue | None:
    """``summary.staff.range`` as the registered ``{label, min, max}`` shape.

    The label is the range the provider actually stated (``"51-200"``), rendered rather than
    invented: the registered field requires a label, and a band with no label is a band nobody can
    read back. A range missing either end is not a band, so it is not claimed.
    """
    start, end = (
        _dig(raw, "summary", "staff", "range", "start"),
        _dig(raw, "summary", "staff", "range", "end"),
    )
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    return {"label": f"{start}-{end}", "min": start, "max": end}


def _categorised_technologies(raw: Mapping[str, Any]) -> JsonValue | None:
    """``technologies`` as the registered ``list[object]``: the provider's name/category pairs."""
    technologies = raw.get("technologies")
    if not isinstance(technologies, list):
        return None
    rows: list[JsonValue] = [
        _without_nones(
            {"name": _dig(item, "name"), "category": _dig(item, "category")}, keep=("name",)
        )
        for item in technologies
        if isinstance(_dig(item, "name"), str)
    ]
    return rows or None


#: ``core.revenue_band`` is an **enum** field (``packs.py``:
#: ``under_1m|1m_10m|10m_50m|50m_100m|100m_500m|500m_1b|1b_plus``), and AI Ark answers a numeric
#: band (``financial.revenue.annual`` = ``start``/``end`` ints plus an ``amount`` string like
#: ``"10000000-25000000"``). Writing the provider's string straight through would store a value
#: that passes as a string and means nothing to the field — every such claim would land
#: ``schema_valid=False``. The translation is therefore done here, in code, and it refuses to
#: guess: a band that does not sit inside exactly one bucket is not claimed at all.
#:
#: Upper bound of each bucket, exclusive, in ascending order. ``1b_plus`` is everything above.
_REVENUE_BUCKETS: tuple[tuple[int, str], ...] = (
    (1_000_000, "under_1m"),
    (10_000_000, "1m_10m"),
    (50_000_000, "10m_50m"),
    (100_000_000, "50m_100m"),
    (500_000_000, "100m_500m"),
    (1_000_000_000, "500m_1b"),
)
_TOP_REVENUE_BUCKET = "1b_plus"


def _bucket_of(amount: int) -> str:
    """The bucket one exact figure falls in. Each bound is exclusive: 10_000_000 is ``10m_50m``."""
    for ceiling, name in _REVENUE_BUCKETS:
        if amount < ceiling:
            return name
    return _TOP_REVENUE_BUCKET


def revenue_band_bucket(start: int | None, end: int | None) -> str | None:
    """The registered band a provider's revenue range means, or ``None`` when it means no one band.

    A provider band and a registered band are two different vocabularies, and only some provider
    bands have an answer in ours: ``10M–25M`` is unambiguously ``10m_50m``, while ``25M–75M``
    spans ``10m_50m`` and ``50m_100m`` and there is no honest way to pick one. ``None`` is that
    answer, and the caller writes no claim — an empty field is a correct output, a rounded one is
    a fabricated fact about how big a company is.
    """
    if start is None or end is None or start < 0 or end < start:
        return None
    low, high = _bucket_of(start), _bucket_of(end)
    return low if low == high else None


def _revenue_bounds(
    annual: Mapping[str, Any] | None, amount: str | None
) -> tuple[int | None, int | None]:
    """The band's two ends: the record's own ints when it carries them, else the ``amount`` string.

    The string is the fallback rather than the source because ``start``/``end`` are already typed
    and the string is a rendering of them; parsing is only for a record that omits the pair.
    """
    if annual is not None:
        start, end = annual.get("start"), annual.get("end")
        if isinstance(start, int) and isinstance(end, int) and not isinstance(start, bool):
            return start, end
    parts = [part.strip() for part in (amount or "").split("-")]
    if all(part.isdigit() for part in parts) and len(parts) in (1, 2):
        numbers = [int(part) for part in parts]
        return numbers[0], numbers[-1]
    return None, None


def _revenue_band_draft(company: AiArkCompany, scope: JobScope) -> ClaimDraft | None:
    """The ``core.revenue_band`` claim for one company record, when the record names one band."""
    raw = company.raw if isinstance(company.raw, Mapping) else {}
    financial = raw.get("financial")
    revenue = financial.get("revenue") if isinstance(financial, Mapping) else None
    annual = revenue.get("annual") if isinstance(revenue, Mapping) else None
    bucket = revenue_band_bucket(
        *_revenue_bounds(annual if isinstance(annual, Mapping) else None, company.revenue)
    )
    if bucket is None:
        return None
    return _draft(
        scope,
        field_key="core.revenue_band",
        value=bucket,
        method=ExtractionMethod.API,
        source_url=None,
        evidence_span=None,
        priority=2,
        outreach_safe=True,
        confidence=0.9,
        source_key="ai_ark:company",
        markers={
            "json_path": "financial.revenue.annual",
            "provider_record": "ai_ark",
            "provider_value": company.revenue,
        },
    )


def _ai_ark_draft(
    scope: JobScope, *, field_key: str, value: JsonValue, json_path: str
) -> ClaimDraft:
    """One AI Ark company claim: tier-1, provider-cited, never URL-cited."""
    return _draft(
        scope,
        field_key=field_key,
        value=value,
        method=ExtractionMethod.API,
        source_url=None,
        evidence_span=None,
        priority=2,
        outreach_safe=True,
        confidence=0.9,
        source_key="ai_ark:company",
        markers={"json_path": json_path, "provider_record": "ai_ark"},
    )


def ai_ark_company_claims(
    company: AiArkCompany, scope: JobScope, *, catalog: FieldCatalog
) -> list[ClaimDraft]:
    """Every registered field the company record carries, cited by raw path, never by a fake URL.

    ``https://api.ai-ark.com/v1/companies?domain=…`` is not a page a human can open, so writing it
    as ``source_url`` would manufacture provenance. The claim cites the record instead: the
    ``json_path`` of the value plus ``provider_record='ai_ark'``, which is what a replay actually
    needs. The lenient writer marks the missing URL, and the display layer renders the provider.

    Three groups, in one order:

    * the four mapped attributes and ``core.revenue_band`` — unchanged, and deliberately not
      schema-gated: they are the shipped mapping, and the band is already the one honest
      translation of a provider vocabulary into a registered one (:func:`revenue_band_bucket`);
    * the widened table (:data:`_AI_ARK_WIDE_FIELDS`) plus the two derived values —
      ``core.employee_range`` from the staff band and the two technology fields;
    * nothing else. ``financial.revenue.annual`` in particular has **no** honest home in
      ``core.annual_revenue``, which requires one amount, a currency, an as-of date and an
      estimate kind, where the record answers a range and names no currency at all.

    Every widened value is checked against the field's own registered ``value_schema`` before a
    draft exists. A value that does not fit is logged and not claimed, because a claim that lands
    ``schema_valid=false`` is a fact the display layer cannot show and the audit has to explain.
    """
    drafts: list[ClaimDraft] = []
    for attribute, field_key, json_path in _AI_ARK_COMPANY_FIELDS:
        raw_value = getattr(company, attribute)
        if raw_value is None:
            continue
        # A provider's own object (``location.headquarter``) carries explicit nulls for what it
        # did not know; those keys are typed in the registered schema, so they are dropped here
        # for the same reason as everywhere else in this module.
        value: JsonValue = (
            _without_nones(raw_value) if isinstance(raw_value, Mapping) else raw_value
        )
        drafts.append(_ai_ark_draft(scope, field_key=field_key, value=value, json_path=json_path))
    band = _revenue_band_draft(company, scope)
    if band is not None:
        drafts.append(band)

    raw = company.raw if isinstance(company.raw, Mapping) else {}
    widened: list[tuple[str, JsonValue | None, str]] = [
        (field_key, _provider_value(_dig(raw, *path)), ".".join(path))
        for field_key, path in _AI_ARK_WIDE_FIELDS
    ]
    widened.append(("core.employee_range", _employee_range(raw), "summary.staff.range"))
    widened.append(
        ("core.primary_tech_stack", list(company.technologies) or None, "technologies[].name")
    )
    widened.append(("core.tech_stack_categorised", _categorised_technologies(raw), "technologies"))
    for field_key, value, json_path in widened:
        if value is None:
            continue
        spec = catalog.spec(field_key)
        if spec is None:
            continue  # not registered in this deployment: not a field, so not a claim
        if check_value_schema(value, spec.value_schema) is False:
            log.info(
                "arv2.ai_ark_value_does_not_fit_its_field",
                field_key=field_key,
                json_path=json_path,
                account_domain=scope.account_domain,
            )
            continue
        drafts.append(_ai_ark_draft(scope, field_key=field_key, value=value, json_path=json_path))
    return drafts


def media_index_claim(
    *,
    person: str,
    item_url: str,
    kind: str,
    duration_s: int | None,
    transcript_model: str | None,
    speaker_verified: bool,
    scope: JobScope,
) -> ClaimDraft:
    """The index row for one media item found for one of the account's people.

    Written whether or not the speaker was verified: "we found this episode and could not confirm
    it is them" is a finding, and dropping it would make the same item cost money again on the next
    run. ``speaker_verified`` is what decides whether anything may be quoted from it, and it is on
    the claim rather than in a comment.
    """
    row: JsonValue = _without_nones(
        {
            "person": person,
            "url": item_url,
            "kind": kind,
            "duration_s": duration_s,
            "transcript_model": transcript_model,
            "speaker_verified": speaker_verified,
        }
    )
    return _draft(
        scope,
        field_key=MEDIA_INDEX_FIELD,
        value=[row],
        method=ExtractionMethod.API,
        source_url=item_url,
        evidence_span=None,
        priority=3,
        outreach_safe=True,
        confidence=0.9,
        source_key=f"media:{kind}",
        markers={"speaker_verified": speaker_verified},
    )


# -- what a model said, made writable -------------------------------------------------------------

#: Everything a field key may not contain. The registry's own rule is lowercase dotted segments of
#: ``[a-z][a-z0-9_]*``, so a space, a dash, a capital or a bracket is what has to go.
_KEY_STRIPPABLE = re.compile(r"[^a-z0-9_.]")
_KEY_SEPARATORS = re.compile(r"[\s\-/]+")


def normalise_proposed_key(key: str, subject: Literal["account", "contact"]) -> str:
    """The writable field key a model's suggested key means.

    A proposed field is a real observation with real evidence; the only thing wrong with
    ``"Recent Funding"`` is its spelling. The lenient gate registers an unknown key, but it calls
    ``classify_field_key`` first, which *raises* on a malformed one — so before this existed, one
    badly-spelled suggested key took the whole write down and the evidence with it.

    Spaces, dashes and slashes become underscores, everything outside ``[a-z0-9_.]`` is dropped, a
    key with no namespace gets the subject's, and a ``core_``-prefixed key is read as the ``core.``
    namespace it was reaching for. Whatever still fails the registry's rule becomes
    ``<subject>.proposed_<digest>`` — a valid, stable, obviously-machine-made key — rather than an
    exception: the claim keeps its value and its quote, and a human can see what happened.
    """
    slug = _KEY_SEPARATORS.sub("_", key.strip().lower())
    slug = _KEY_STRIPPABLE.sub("", slug)
    if slug.startswith("core_"):
        slug = "core." + slug.removeprefix("core_")
    if "." not in slug:
        slug = f"{subject}.{slug}"
    if not is_valid_field_key(slug):
        digest = hashlib.sha256(key.encode()).hexdigest()[:8]
        return f"{subject}.proposed_{digest}"
    return slug


#: The keys a model wraps a scalar in when it wants to say more than the field can hold
#: (``{"count": 36, "semantics": "linkedin_estimate"}`` for ``core.employee_count``). Exactly one
#: of them may be present: two carriers is an object with real structure, not a wrapped scalar.
_CARRIER_KEYS: frozenset[str] = frozenset(
    {"value", "count", "year", "amount", "n", "total", "text", "name"}
)
_NUMERIC_TYPES: frozenset[str] = frozenset({"integer", "number"})


def _declared_type(field_key: str, catalog: FieldCatalog) -> str | None:
    """The single scalar ``type`` a registered field declares, or ``None``."""
    spec = catalog.spec(field_key)
    schema = spec.value_schema if spec else None
    declared = schema.get("type") if schema else None
    if declared in {"integer", "number", "string", "boolean"}:
        return str(declared)
    return None


def coerce_scalar(field_key: str, value: JsonValue, catalog: FieldCatalog) -> JsonValue:
    """A model's value, read as the scalar its registered field actually declares.

    Two shapes, both measured on the R2 run: a scalar wrapped in an object with one carrier key
    plus commentary (``{"count": 36, "semantics": …}`` on an integer field), and a number written
    as a string (``"2024"`` on a year field). Both are the right fact in the wrong shape, and both
    otherwise land ``schema_valid=false`` — which reads, wrongly, as "the extraction did not fit
    the field" rather than "the model added a note".

    Nothing else is touched. A digit string on a *string* field stays a string, a list on a list
    field stays a list, an object with two carrier keys keeps its structure, and an unregistered
    key is left exactly as it arrived. Coercing beyond what the field declares would be this
    module deciding what a value means, which is the one thing it must not do.
    """
    declared = _declared_type(field_key, catalog)
    if declared is None:
        return value
    if isinstance(value, Mapping):
        carriers = [name for name in value if name in _CARRIER_KEYS]
        if len(carriers) == 1:
            unwrapped = value[carriers[0]]
            return coerce_scalar(field_key, unwrapped, catalog)
        return value
    if declared in _NUMERIC_TYPES and isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
        if declared == "number":
            try:
                return float(text)
            except ValueError:
                return value
    return value


def _coerced(
    field_key: str, value: JsonValue, catalog: FieldCatalog
) -> tuple[JsonValue, Mapping[str, JsonValue]]:
    """The value to write, plus the ``coerced_from`` marker when the shape actually changed."""
    coerced = coerce_scalar(field_key, value, catalog)
    return coerced, {} if coerced == value else {"coerced_from": value}


# -- what the structuring pass produced -----------------------------------------------------------


def negative_claims(negatives: Sequence[NegativeOrRisk], scope: JobScope) -> list[ClaimDraft]:
    """Every negative or risk as an ``account.reputation_risk`` claim, born ``outreach_safe=False``.

    The model's own ``outreach_safe`` is ignored here on purpose (founder ruling 2026-09-08): the
    partition it landed in already says what it is, and a layoff read as outreach-safe because one
    key came back garbled is the failure that reaches a prospect.
    """
    return [
        _draft(
            scope,
            field_key=REPUTATION_RISK_FIELD,
            value=_without_nones(
                {
                    "what": negative.what,
                    "status": negative.status.lower() if negative.status else None,
                    "source_note": None,
                },
                keep=("what",),
            ),
            method=ExtractionMethod.LLM_SYNTHESIS,
            source_url=negative.source_url,
            evidence_span=negative.evidence_span or None,
            priority=2,
            outreach_safe=False,
            confidence=0.5,
            source_key="structuring",
        )
        for negative in negatives
    ]


def _structured_claim_draft(
    claim: StructuredClaim,
    *,
    output: StructuredOutput,
    scope: JobScope,
    hint: str | None,
    catalog: FieldCatalog,
) -> ClaimDraft:
    """One kept structuring claim, with the extraction's own annotations as write markers."""
    value, coercion = _coerced(claim.field_key, cast(JsonValue, claim.value), catalog)
    markers: dict[str, JsonValue] = {
        "evidence_verbatim": claim.evidence_verbatim,
        "schema_valid": claim.schema_valid,
        "source_kind": claim.source_kind,
        "media_timestamp": claim.media_timestamp,
        "structuring_mode": output.mode,
        **coercion,
    }
    if claim.source_kind_block is not None:
        markers["source_kind_block"] = claim.source_kind_block
    if claim.source_url_corrected:
        markers["source_url_corrected"] = True
    if claim.quoted_context:
        markers["quoted_context"] = True
    return _draft(
        scope,
        field_key=claim.field_key,
        value=value,
        method=ExtractionMethod.LLM_SYNTHESIS,
        source_url=claim.source_url or hint,
        evidence_span=claim.evidence_span or None,
        priority=claim.priority,
        outreach_safe=False if claim.field_key in ALWAYS_UNSAFE_FIELDS else claim.outreach_safe,
        confidence=_CONFIDENCE_WORDS.get((claim.confidence or "").strip().lower(), 0.5),
        source_key="structuring",
        markers=markers,
    )


def structured_claims(
    output: StructuredOutput,
    *,
    scope: JobScope,
    subject_url_hint: str | None,
    catalog: FieldCatalog,
) -> list[ClaimDraft]:
    """The structuring pass's claims and proposed fields, annotations intact.

    The annotations travel as write markers because they are facts *about the extraction* — was the
    quote really in the material, did the value fit the field's schema, which block the quote came
    out of, whether the URL had to be corrected, which mode asked for it — and the audit skill
    reads them off the claim rather than re-deriving them.

    ``subject_url_hint`` fills a claim whose ``source_url`` the model omitted (a page fetched by
    ``fetch_page`` is often the whole material). It is a *fallback*, never an override.

    A proposed field's key is normalised (:func:`normalise_proposed_key`) before it is written, and
    the raw spelling is kept on the claim: an unwritable key must never cost the observation.
    """
    drafts = [
        _structured_claim_draft(
            claim, output=output, scope=scope, hint=subject_url_hint, catalog=catalog
        )
        for claim in output.claims
    ]
    for proposed in output.proposed:
        if not proposed.suggested_key:
            continue
        field_key = normalise_proposed_key(proposed.suggested_key, "account")
        markers: dict[str, JsonValue] = {
            "proposed_origin": proposed.origin,
            "structuring_mode": output.mode,
        }
        if field_key != proposed.suggested_key:
            markers["proposed_key_raw"] = proposed.suggested_key
        value, coercion = _coerced(field_key, cast(JsonValue, proposed.value), catalog)
        drafts.append(
            _draft(
                scope,
                field_key=field_key,
                value=value,
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=proposed.source_url or subject_url_hint,
                evidence_span=proposed.evidence_span or None,
                priority=3,
                outreach_safe=True,
                confidence=0.5,
                source_key="structuring",
                markers={**markers, **coercion},
                field_description=proposed.why or None,
            )
        )
    return drafts


# -- what the agent itself decided ----------------------------------------------------------------


def agent_claims(
    items: Sequence[ClaimInput], scope: JobScope, *, catalog: FieldCatalog
) -> list[ClaimDraft]:
    """The claims the model wrote itself, tiered as synthesis whatever it says its source was.

    The key it named is normalised and its value is read as the shape the field declares, exactly
    as for a structuring claim: the agent hand-writes claims through the same registry, so a
    wrapped scalar or a spelled-out key must not mean two different things depending on who typed
    it.
    """
    drafts: list[ClaimDraft] = []
    for item in items:
        field_key = (
            item.field_key
            if is_valid_field_key(item.field_key)
            else normalise_proposed_key(item.field_key, "account")
        )
        value, coercion = _coerced(field_key, item.value, catalog)
        markers: dict[str, JsonValue] = dict(coercion)
        if item.corrects_claim_id:
            markers["corrects_claim_id"] = item.corrects_claim_id
        if field_key != item.field_key:
            markers["proposed_key_raw"] = item.field_key
        drafts.append(
            _draft(
                scope,
                field_key=field_key,
                value=value,
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=str(item.source_url) if item.source_url else None,
                evidence_span=item.evidence_span,
                priority=item.priority,
                outreach_safe=(False if field_key in ALWAYS_UNSAFE_FIELDS else item.outreach_safe),
                confidence=item.confidence,
                source_key="agent",
                markers=markers or None,
            )
        )
    return drafts


def fit_verdict_claims(verdicts: Sequence[Mapping[str, Any]], scope: JobScope) -> list[ClaimDraft]:
    """One ``account.icp_fit_verdict`` claim per ICP gate, leniency enforced in code.

    Constitution §5: a ``fail`` is admissible only on positive contrary evidence, so a ``fail``
    that cites no claim ids is recorded as ``unclear`` with the reason appended to its rationale.
    The rule therefore holds even in the runs where the model forgets it — which is the whole point
    of writing it here rather than only in the prompt.
    """
    drafts: list[ClaimDraft] = []
    for verdict in verdicts:
        claim_ids = [str(claim_id) for claim_id in verdict.get("claim_ids") or []]
        stated = str(verdict.get("verdict") or "unclear")
        rationale = str(verdict.get("rationale") or "")
        downgraded = stated == "fail" and not claim_ids
        if downgraded:
            stated, rationale = "unclear", f"{rationale}{DOWNGRADE_SUFFIX}"
        value: JsonValue = _without_nones(
            {
                "gate": str(verdict.get("gate") or ""),
                "verdict": stated,
                "rationale": rationale,
                "claim_ids": list(claim_ids),
            },
            keep=("gate", "verdict"),
        )
        drafts.append(
            _draft(
                scope,
                field_key=FIT_VERDICT_FIELD,
                value=value,
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=None,
                evidence_span=None,
                priority=2,
                outreach_safe=False,
                confidence=0.6,
                source_key="agent",
                markers={"downgraded_from_fail": True} if downgraded else None,
            )
        )
    return drafts


def unconfirmed_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The named candidates that carry no confirming URL — reported to the model, never written."""
    return [
        candidate
        for candidate in candidates
        if candidate.get("name") and not candidate.get("confirmed_by")
    ]


def committee_candidate_claims(
    candidates: Sequence[Mapping[str, Any]], scope: JobScope
) -> list[ClaimDraft]:
    """One claim per committee candidate whose identity was confirmed on a non-provider URL.

    A *named* person with nothing behind the name is the failure this field exists to prevent, so a
    candidate with no ``confirmed_by`` is dropped (the caller reports it back to the model through
    :func:`unconfirmed_candidates`). A **vacant seat** carries no name and needs no URL: "nobody
    holds this role" is a finding about the account, not an assertion about a person.
    """
    drafts: list[ClaimDraft] = []
    for candidate in candidates:
        name = candidate.get("name")
        confirmed_by = candidate.get("confirmed_by")
        if name and not confirmed_by:
            continue
        value: JsonValue = _without_nones(
            {
                "name": name,
                "title": candidate.get("title"),
                "persona": candidate.get("persona"),
                "linkedin_url": candidate.get("linkedin_url"),
                "confirmed_by": confirmed_by,
                "vacant_seat": bool(candidate.get("vacant_seat")) or not name,
            },
            # ``persona`` alone identifies the row (``catalog_seed``): a vacant seat has no name,
            # and writing ``"name": null`` into a string-typed property would make the correctly
            # recorded vacancy land ``schema_valid=false``.
            keep=("persona",),
        )
        drafts.append(
            _draft(
                scope,
                field_key=COMMITTEE_FIELD,
                value=value,
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=str(confirmed_by) if confirmed_by else None,
                evidence_span=str(candidate.get("evidence_span") or "") or None,
                priority=2,
                outreach_safe=True,
                confidence=0.6,
                source_key="agent",
            )
        )
    return drafts
