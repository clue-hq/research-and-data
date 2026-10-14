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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from clue_api.arv2.account_research_catalog import has_capability
from clue_api.arv2.ai_ark_client import AiArkCompany, AiArkEmailExport, AiArkPerson, AiArkPhone
from clue_api.arv2.ats_client import BoardPostings
from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.structuring_client import (
    UNIQUE_INSIGHT_TARGET_KEYS,
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
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    is_valid_field_key,
)
from clue_obs import get_logger

log = get_logger("clue_api.arv2.account_research_claims")

__all__ = [
    "ALWAYS_UNSAFE_FIELDS",
    "COMMITTEE_FIELD",
    "CURRENT_TITLE_FIELD",
    "EXCLUDED_LOOKALIKE_FIELD",
    "FIT_VERDICT_FIELD",
    "HOOKS_FIELD",
    "MEDIA_INDEX_FIELD",
    "OPENERS_FIELD",
    "PERSONA_FIELD",
    "PUBLIC_APPEARANCES_FIELD",
    "REPORTS_TO_FIELD",
    "REPUTATION_RISK_FIELD",
    "ROLE_ON_COMMITTEE_FIELD",
    "ClaimInput",
    "JobScope",
    "PersonFinalization",
    "UniqueInsight",
    "agent_claims",
    "ai_ark_company_claims",
    "ai_ark_person_claims",
    "ats_posting_claims",
    "coerce_scalar",
    "committee_candidate_claims",
    "committee_member_claims",
    "email_export_claim",
    "fit_verdict_claims",
    "media_index_claim",
    "negative_claims",
    "normalise_proposed_key",
    "person_finalization_claims",
    "revenue_band_bucket",
    "structured_claims",
    "unconfirmed_candidates",
    "unique_insight_claims",
]

#: The two keys that are never outreach material, whoever writes them (master plan §4; the
#: constitution's §5 verdict rule). Forced here rather than trusted to a caller.
REPUTATION_RISK_FIELD = "account.reputation_risk"
FIT_VERDICT_FIELD = "account.icp_fit_verdict"
ALWAYS_UNSAFE_FIELDS: frozenset[str] = frozenset({REPUTATION_RISK_FIELD, FIT_VERDICT_FIELD})

COMMITTEE_FIELD = "account.committee_candidate"
MEDIA_INDEX_FIELD = "account.media_layer_index"

#: Where a media item lands on a **person** job. The account job indexes the item under the
#: account (one row naming which of its people appeared); a person job's subject *is* the person,
#: so the same appearance is a fact about them and belongs on the contact's own appearances facet,
#: which is what the contact display's Angles section reads.
PUBLIC_APPEARANCES_FIELD = "contact.facet.public_appearances"

#: The four fields a person finalization writes. Openers and hooks are the outreach product;
#: the lookalike log is what *proves* the identity lock held; ``contact.reports_to`` is the
#: reporting line, admitted only from an ATS reporting line or the person's own statement
#: (founder ruling 2026-09-09) and therefore only ever written with the quote and URL behind it.
OPENERS_FIELD = "contact.facet.openers"
HOOKS_FIELD = "contact.facet.hooks"
EXCLUDED_LOOKALIKE_FIELD = "contact.facet.excluded_lookalike"
REPORTS_TO_FIELD = "contact.reports_to"

#: What the model's confidence word is worth as a number. Anything unreadable is 0.5 — the
#: substrate's own default — rather than a flattering guess.
_CONFIDENCE_WORDS: Mapping[str, float] = {"high": 0.8, "medium": 0.6, "low": 0.5}

#: The suffix a downgraded verdict carries, so a human reading the claim sees *why* it says
#: ``unclear`` when the agent said ``fail``.
DOWNGRADE_SUFFIX = " (downgraded: no contrary evidence cited)"


@dataclass(frozen=True)
class JobScope:
    """Everything a tool needs to know about the one job it serves.

    It is engine authority: the model can read every part of it (through ``read_account_state``)
    and change none of it. Every claim written in the job is stamped from here, which is what makes
    "which run wrote this, for which workspace, about which account" a query rather than a guess.

    A job has one **subject** (the migration's own ruling): an account, or one named person at that
    account. The account fields are always populated — a person job is still *about* a person at
    that account, and its context is the account's — and the ``person_*`` fields are populated only
    on a person job, where they are what every claim is stamped to.
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
    #: The keys of the pinned ICP's ``hard_gates``, in the order the document names them. Every fit
    #: verdict is keyed to one of them, so two accounts' receipts are read against the same gates
    #: rather than against whatever labels each run's model invented. An ICP with no hard gates
    #: leaves this empty, and then any gate label is admitted — there is nothing to key to.
    icp_gate_keys: tuple[str, ...] = ()
    #: Which subject this job researches. ``account`` is every R2 job and stays the default, so a
    #: caller that predates the person lane keeps exactly the behaviour it had.
    subject_kind: Literal["account", "person"] = "account"
    #: The person a ``person`` job is about — the contact entity every one of its claims is
    #: stamped to. ``None`` on an account job, and required on a person one (``__post_init__``).
    contact_id: EntityId | None = None
    person_name: str = ""
    person_title: str = ""
    person_linkedin_url: str = ""
    #: The person's employment as the job already knows it, one rendered line per role. Context for
    #: the prompts (so the model does not spend the job re-deriving where they have worked); never
    #: evidence, and never the source of a claim.
    employment_history: tuple[str, ...] = ()
    catalog_version: str = "v1"
    input_refs: Mapping[str, Any] | None = None
    #: The job's restart counter; selects which conversation the job runs (spec 2026-10-14 §3.2).
    restart_count: int = 0

    def __post_init__(self) -> None:
        if self.subject_kind == "person" and self.contact_id is None:
            raise ValueError("a person job's scope must carry the contact_id it is about")

    @property
    def person_subject_id(self) -> EntityId | None:
        """The contact every claim in this job is about, or ``None`` on an account job.

        ``__post_init__`` already refused a person scope with no contact, so the ``None`` this
        returns always means "this job's subject is the account", never "the id went missing".
        """
        contact_id = self.contact_id
        return contact_id if self.subject_kind == "person" and contact_id is not None else None


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


def _use_class_for(hint: str | None) -> UseClass:
    """The use class a contact claim is born with: the field's own declared hint, else the plain
    professional-public class every non-facet contact fact belongs to.

    Read from the registry's ``use_class_hint`` (:attr:`FieldSpec.use_class_hint`) rather than
    decided here, because "is this personal or professional" is a property of the *field*, and a
    key→class table in this module would be exactly the kind of meaning-by-spelling the mappers do
    not do. An unreadable hint falls back rather than raising: a claim must not be lost to a typo
    in a registry row, and the fallback is the stricter-to-use of the two public classes.
    """
    if hint:
        try:
            return UseClass(hint)
        except ValueError:
            log.info("arv2.unreadable_use_class_hint", use_class_hint=hint)
    return UseClass.PROFESSIONAL_PUBLIC


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
    contact_id: EntityId | None = None,
    use_class_hint: str | None = None,
) -> ClaimDraft:
    """One claim, with everything the job (never the caller) decides already stamped.

    The subject is the **job's**: an account job stamps the account, and a person job stamps the
    person it was launched for — entity, entity type and research mode together, so a person claim
    can never land on the account by omission. ``contact_id`` names a person explicitly, for the
    one case where an *account* job writes about one: the committee members it resolved.

    A contact claim is additionally born governed. ``identity_binding`` is ``STRONG`` because the
    lock is not this claim's to establish — the person was confirmed on a non-provider URL before
    the job existed, and every claim in it is about that confirmed person. ``use_class`` is the
    field's own declared hint (:func:`_use_class_for`). Both are stamped for every contact claim,
    not only for the ``contact.facet.*`` ones the substrate requires them on: the writer would
    otherwise default a facet to ``WEAK`` (which never promotes), and a plain contact claim
    carrying one of the pair without the other is a claim the composed contact view refuses.
    """
    person_id = contact_id if contact_id is not None else scope.person_subject_id
    return ClaimDraft(
        entity_id=person_id if person_id is not None else scope.account_id,
        entity_type=EntityType.CONTACT if person_id is not None else EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        extraction_method=method,
        run_id=RunId(scope.run_id),
        research_mode=(
            ResearchMode.CONTACT_PROFILING
            if person_id is not None
            else ResearchMode.ACCOUNT_PROFILING
        ),
        workspace_id=scope.workspace_id,
        source_url=source_url,
        source_key=source_key,
        evidence_span=evidence_span,
        observed_at=None,
        confidence=confidence,
        identity_binding=IdentityBinding.STRONG if person_id is not None else None,
        use_class=_use_class_for(use_class_hint) if person_id is not None else None,
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
        if scope.catalog_version == "v4":
            from clue_api.arv2.quality_hiring import hiring_context

            assert isinstance(row, dict)
            row.update(
                hiring_context(
                    posting.provider_fields,
                    observed=scope.today,
                    confirmed_board=True,
                    listed=posting.is_listed,
                )
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
                outreach_safe=not isinstance(row, dict)
                or row.get("hiring_state", "open") == "open",
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
    ("core.founded_year", ("summary", "founded_year")),
    ("core.company_type", ("summary", "type")),
    ("core.industries_all", ("industries",)),
    ("core.company_languages", ("languages",)),
    ("core.company_crunchbase_url", ("link", "crunchbase")),
    ("core.company_twitter_url", ("link", "twitter")),
    ("core.company_email", ("contact", "email")),
)

#: The provider states funding amounts as plain integers with no currency field. **Ruling
#: 2026-09-08: they are USD** — the inventory's ``total_amount`` of 130500000 is the $130.5M every
#: press source reports for the same company, and the answer keys carry the same figures under
#: ``amount_usd``. The assumption is not silent: every funding claim records it as a marker, so a
#: non-US record that ever contradicts it is findable by query rather than by re-reading this code.
CURRENCY_ASSUMED_MARKER = "currency_assumed"
ASSUMED_CURRENCY = "USD"

#: What ``account.total_funding.estimate_kind`` is for an AI Ark total. The registered enum is
#: ``reported | provider_estimate | third_party_estimate``, i.e. the axis is *reported vs modelled*,
#: not *who said it*. A funding total is the sum of disclosed rounds — the provider compiles it, it
#: does not estimate it (unlike its revenue *band*, which is why that one stays unmapped) — so the
#: honest value is ``reported``, and ``provider_record='ai_ark'`` on the claim says who compiled it.
_FUNDING_ESTIMATE_KIND = "reported"


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


def _integer(raw: object) -> int | None:
    """A record value as a real integer. ``bool`` is not a number, as in JSON."""
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _string(raw: object) -> str | None:
    """A record value as a non-blank string. A blank field is an absent field, never an empty
    claim, and a value of some other shape has no home in a string-typed property."""
    return raw if isinstance(raw, str) and raw.strip() else None


def _hq_location(location: Mapping[str, Any] | None) -> JsonValue | None:
    """``location.headquarter`` as the registered ``core.hq_location`` shape.

    The provider answers ``continent/country/city/state/raw_address/position``; the registry
    requires ``raw`` and knows ``city``/``region``/``country``/``country_code``. ``state`` is
    ``region``. Writing the provider's own object straight through is what made every AI Ark HQ
    claim land ``schema_valid=false`` on both live accounts — the value was right and its shape was
    foreign. ``raw`` is the provider's ``raw_address``, which is the whole point of that key: the
    source's own unparsed string.

    No ``raw_address`` means no claim: ``raw`` is the required key, and a location the provider
    never spelled out is not a location this field can hold.
    """
    raw_address = _dig(location, "raw_address")
    if not isinstance(raw_address, str) or not raw_address.strip():
        return None
    return _without_nones(
        {
            "raw": raw_address,
            "city": _dig(location, "city"),
            # The provider's ``state`` is the registry's ``region``; the record carries no ISO code
            # for either, so ``country_code`` appears only when the provider spelled one out —
            # never from a name→code table (the mapper does not decide what a value means).
            "region": _dig(location, "state"),
            "country": _dig(location, "country"),
            "country_code": _dig(location, "country_code"),
        },
        keep=("raw",),
    )


def _total_funding(funding: Mapping[str, Any] | None) -> JsonValue | None:
    """``financial.funding.total_amount`` as the registered ``{amount_usd, estimate_kind}``."""
    total = _dig(funding, "total_amount")
    if not isinstance(total, int) or isinstance(total, bool):
        return None
    return {"amount_usd": total, "estimate_kind": _FUNDING_ESTIMATE_KIND}


def _recent_round(funding: Mapping[str, Any] | None) -> tuple[JsonValue, int] | None:
    """The most recent funding round as ``{amount_usd, round}``, with the index it sits at.

    "Most recent" is decided by ``announced_at`` rather than by position, because the record's own
    ordering is the provider's and nothing promises it. The index travels back so the claim cites
    the round it actually read, not a guessed ``rounds[0]``.

    Only that round is considered: if the newest round did not disclose an amount, the answer is
    "the most recent round's amount is not in this record", never an older round's figure wearing a
    newer date.
    """
    rounds = _dig(funding, "rounds")
    if not isinstance(rounds, list):
        return None
    dated = [(index, item) for index, item in enumerate(rounds) if isinstance(item, Mapping)]
    if not dated:
        return None
    index, newest = max(
        dated, key=lambda pair: (str(_dig(pair[1], "announced_at") or ""), -pair[0])
    )
    amount = _dig(newest, "raised_amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        return None
    kind = _dig(newest, "type")
    return _without_nones(
        {"amount_usd": amount, "round": kind if isinstance(kind, str) else None},
        keep=("amount_usd",),
    ), index


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
    scope: JobScope,
    *,
    field_key: str,
    value: JsonValue,
    json_path: str,
    extra_markers: Mapping[str, JsonValue] = {},
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
        markers={"json_path": json_path, "provider_record": "ai_ark", **extra_markers},
    )


def ai_ark_company_claims(
    company: AiArkCompany, scope: JobScope, *, catalog: FieldCatalog
) -> list[ClaimDraft]:
    """Basic typed company facts, cited by raw path, never by a fake URL.

    Provider descriptions belong only in the raw audit; company_about comes from research.

    ``https://api.ai-ark.com/v1/companies?domain=…`` is not a page a human can open, so writing it
    as ``source_url`` would manufacture provenance. The claim cites the record instead: the
    ``json_path`` of the value plus ``provider_record='ai_ark'``, which is what a replay actually
    needs. The lenient writer marks the missing URL, and the display layer renders the provider.

    Three groups, in one order:

    * the three mapped attributes and ``core.revenue_band`` — unchanged, and deliberately not
      schema-gated: they are the shipped mapping, and the band is already the one honest
      translation of a provider vocabulary into a registered one (:func:`revenue_band_bucket`);
    * everything **translated** into the shape its field declares — the widened table
      (:data:`_AI_ARK_WIDE_FIELDS`), the HQ, the staff band, the technologies, and the two funding
      amounts (USD by ruling, recorded as an assumption on every one of those claims);
    * nothing else. ``financial.revenue.annual`` in particular has **no** honest home in
      ``core.annual_revenue``, which requires one amount, a currency, an as-of date and an
      estimate kind, where the record answers a *range* and names no currency at all. Funding is
      different in exactly the way that matters: it is one disclosed amount, not a band.

    Every translated value is checked against the field's own registered ``value_schema`` before a
    draft exists. A value that does not fit is logged and not claimed, because a claim that lands
    ``schema_valid=false`` is a fact the display layer cannot show and the audit has to explain —
    which is precisely what the old straight-through HQ mapping produced on both live accounts.
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
    funding = _dig(raw, "financial", "funding")
    money: Mapping[str, JsonValue] = {CURRENCY_ASSUMED_MARKER: ASSUMED_CURRENCY}
    widened: list[tuple[str, JsonValue | None, str, Mapping[str, JsonValue]]] = [
        (field_key, _provider_value(_dig(raw, *path)), ".".join(path), {})
        for field_key, path in _AI_ARK_WIDE_FIELDS
    ]
    widened.append(("core.hq_location", _hq_location(company.location), "location.headquarter", {}))
    widened.append(("core.employee_range", _employee_range(raw), "summary.staff.range", {}))
    widened.append(
        ("core.primary_tech_stack", list(company.technologies) or None, "technologies[].name", {})
    )
    widened.append(
        ("core.tech_stack_categorised", _categorised_technologies(raw), "technologies", {})
    )
    widened.append(
        (
            "account.total_funding",
            _total_funding(funding if isinstance(funding, Mapping) else None),
            "financial.funding.total_amount",
            money,
        )
    )
    recent = _recent_round(funding if isinstance(funding, Mapping) else None)
    if recent is not None:
        value_json, index = recent
        widened.append(
            ("account.recent_funding", value_json, f"financial.funding.rounds[{index}]", money)
        )

    for field_key, widened_value, json_path, extra_markers in widened:
        if widened_value is None:
            continue
        spec = catalog.spec(field_key)
        if spec is None:
            continue  # not registered in this deployment: not a field, so not a claim
        if check_value_schema(widened_value, spec.value_schema) is False:
            log.info(
                "arv2.ai_ark_value_does_not_fit_its_field",
                field_key=field_key,
                json_path=json_path,
                account_domain=scope.account_domain,
            )
            continue
        drafts.append(
            _ai_ark_draft(
                scope,
                field_key=field_key,
                value=widened_value,
                json_path=json_path,
                extra_markers=extra_markers,
            )
        )
    return drafts


#: The person record's scalar fields, as (mapped attribute, field key, the record path it was read
#: from). The attributes are ``ai_ark_client.person_from_record``'s own mapping, so the path here is
#: a citation of where the value came from, never a second parse of the record.
#:
#: The record's ``link.linkedin`` is deliberately **not** here. The person's LinkedIn URL is the
#: contact entity's own ``linkedin_url`` column — the identity strong key the lock was made on —
#: and that is where every reader takes it from. A claim on it would register a field nobody reads
#: and offer a second, divergent answer to a question the entity row already answers.
_AI_ARK_PERSON_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("title", "contact.current_title", "profile.title"),
)

#: The two ways the provider's ``profile.title`` carries the employer on the end of the job title
#: ("Head of Growth | Cogent", "Head of Growth at Cogent"). Both are separators, never part of a
#: title, which is why they can be cut at all.
_TITLE_COMPANY_SEPARATORS: tuple[str, ...] = (" | ", " at ")


def _fold_company(name: str) -> str:
    """The form two company names are compared in: case-folded, whitespace-collapsed, no trailing
    punctuation. Nothing else — ``Cogent`` and ``Cogent Security`` are deliberately *not* the same
    string here, because cutting a title on a partial match would cut real titles."""
    return " ".join(name.split()).strip(" .,").casefold()


def _title_without_company(title: str | None, *, companies: tuple[str, ...]) -> tuple[str, str]:
    """``("Head of Growth", "Head of Growth | Cogent")`` — the job title, and what the record said.

    W4 (live walk 2026-09-09): AI Ark's ``profile.title`` is frequently the LinkedIn headline's
    "role at employer" form, so ``contact.current_title`` was served as "Head of Growth | Cogent" —
    a title carrying a fact the account row already states. The suffix is cut only when what
    follows the separator **is** one of the employers this job already knows (the record's own
    current company, or the account the job is about), so a genuine title that happens to contain
    ``" at "`` ("Head of Security at Scale" at some other company) is left exactly as the record
    wrote it. The raw string rides on the claim as ``title_raw`` whenever anything was cut, so the
    provider's answer stays auditable.
    """
    raw = title or ""
    known = {_fold_company(name) for name in companies if name and name.strip()}
    for separator in _TITLE_COMPANY_SEPARATORS:
        head, found, tail = raw.rpartition(separator)
        if found and head.strip() and _fold_company(tail) in known:
            return head.strip(), raw
    return raw, raw


def _person_location(location: Mapping[str, Any] | None) -> JsonValue | None:
    """``location`` as the registered ``contact.current_location`` shape.

    The registry declares ``{raw?, country?}`` and the provider answers
    ``default/short/country/state/city/position``. ``default`` is the person's own unabbreviated
    location line, which is what ``raw`` means — the source's own unparsed string — and ``country``
    is the provider's, never derived from the city. A record that answers neither is not a
    location, so it is not a claim.
    """
    row = _without_nones(
        {
            "raw": _string(_dig(location, "default")),
            "country": _string(_dig(location, "country")),
        }
    )
    return row or None


def _network_statistics(raw: Mapping[str, Any]) -> JsonValue | None:
    """``statistics.network`` as the registered ``{followers, connections}`` counts.

    Only the two counts the field declares, and only when the record states them as integers: the
    provider's own block also carries ``influencer``/``followable``, which are not counts and have
    no home here.
    """
    network = _dig(raw, "statistics", "network")
    row = _without_nones(
        {
            "followers": _integer(_dig(network, "followers_count")),
            "connections": _integer(_dig(network, "connections_count")),
        }
    )
    return row or None


def _member_badges(raw: Mapping[str, Any]) -> JsonValue | None:
    """``member_badges`` as the registered object: the provider's own flags, nulls dropped."""
    badges = raw.get("member_badges")
    if not isinstance(badges, Mapping):
        return None
    row = _without_nones({str(name): flag for name, flag in badges.items()})
    return row or None


def _career_history(raw: Mapping[str, Any]) -> JsonValue | None:
    """``position_groups[].profile_positions[]`` as the registered ``[{org, role, date:{…}}]``.

    The provider's employment list is ``position_groups`` — one group per employer, one
    ``profile_positions`` entry per role held there — so a promotion is its own row rather than a
    tenure silently flattened into its latest title. The org is the position's own company name,
    falling back to the group's; a row that names no org is dropped, because ``org`` is the
    field's required key and a role at nobody is not a career-history row.

    The dates are the position's own when it states them and the group's otherwise: a group whose
    single position omits its dates is still one dated stint, and copying a *neighbouring*
    position's dates would be this module inventing a tenure.

    They sit **under ``date``** (W3, live walk 2026-09-09), which is the shape the answer keys
    carry and the one the contact header's tenure reads
    (``frontend_read.v1_shared.current_position_start`` looks for an entry with no ``date.end``
    and takes its ``date.start``). The mapper wrote them flat, so every mapped person's tenure
    read empty. A stint the record dates neither end of carries no ``date`` at all rather than an
    empty object: absent is not null, and an entry with an empty ``date`` would read as a current
    position with an unknown start.
    """
    groups = raw.get("position_groups")
    if not isinstance(groups, list):
        return None
    rows: list[JsonValue] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        positions = group.get("profile_positions")
        for position in positions if isinstance(positions, list) else ():
            if not isinstance(position, Mapping):
                continue
            org = _string(position.get("company")) or _string(_dig(group, "company", "name"))
            if org is None:
                continue
            span = _without_nones(
                {
                    "start": _string(_dig(position, "date", "start"))
                    or _string(_dig(group, "date", "start")),
                    "end": _string(_dig(position, "date", "end"))
                    or _string(_dig(group, "date", "end")),
                }
            )
            rows.append(
                _without_nones(
                    {
                        "org": org,
                        "role": _string(position.get("title")),
                        "date": span or None,
                    },
                    keep=("org",),
                )
            )
    return rows or None


def ai_ark_person_claims(person: AiArkPerson, scope: JobScope) -> list[ClaimDraft]:
    """Basic typed contact facts, cited by raw path.

    Free-form headlines and biographies belong only in the raw audit, not research inputs.

    The same law as :func:`ai_ark_company_claims`, one entity down: ``https://api.ai-ark.com/…`` is
    not a page a human can open, so a person claim carries ``source_url=None`` plus the exact
    ``json_path`` the value sits at, and the lenient writer marks the missing URL. Every claim is
    stamped to the job's person (:func:`_draft`), which is why the mapper takes no entity of its
    own: a person fact belongs to the person the job is about, and to nobody else.

    A path the record does not answer yields nothing at all — an absent field is a correct output.

    ``contact.current_title`` is the one value not passed straight through: the record's title
    often ends in the employer, and :func:`_title_without_company` cuts that suffix (W4).
    """
    raw = person.raw if isinstance(person.raw, Mapping) else {}
    title, title_raw = _title_without_company(
        person.title, companies=(person.current_company or "", scope.account_name)
    )
    mapped: list[tuple[str, JsonValue | None, str, dict[str, JsonValue]]] = [
        (
            field_key,
            _string(title) if attribute == "title" else getattr(person, attribute),
            json_path,
            {"title_raw": title_raw} if attribute == "title" and title != title_raw else {},
        )
        for attribute, field_key, json_path in _AI_ARK_PERSON_FIELDS
    ]
    mapped.append(("contact.current_location", _person_location(person.location), "location", {}))
    mapped.append(
        ("contact.network_statistics", _network_statistics(raw), "statistics.network", {})
    )
    mapped.append(("contact.member_badges", _member_badges(raw), "member_badges", {}))
    mapped.append(("contact.facet.career_history", _career_history(raw), "position_groups", {}))
    return [
        _draft(
            scope,
            field_key=field_key,
            value=value,
            method=ExtractionMethod.API,
            source_url=None,
            evidence_span=None,
            priority=2,
            outreach_safe=True,
            confidence=0.9,
            source_key="ai_ark:person",
            markers={"json_path": json_path, "provider_record": "ai_ark", **extra},
        )
        for field_key, value, json_path, extra in mapped
        if value is not None
    ]


#: The one verdict that means the mailbox itself answered, so the address is provider-verified
#: rather than merely accepted by a catch-all domain (``ai_ark_client.email_verdict``).
_PROVIDER_VERIFIED_VERDICT = "verified_smtp"


def email_export_claim(export: AiArkEmailExport, scope: JobScope) -> ClaimDraft | None:
    """The person's work email as one tier-1 claim, or ``None`` when the export found none.

    The verdict rides on the claim rather than deciding whether it is written: "we have an address
    and the domain accepts everything" is a different, useful answer from "we have an address the
    mailbox itself confirmed", and both are different from having no address. Collapsing the first
    two would make an unproven mailbox indistinguishable from a proven one at read time, which is
    exactly the distinction ``email_verdict`` exists to preserve.

    So the **value** is the pair, not the address alone (W1, live walk 2026-09-09): the field's
    registered shape is ``{address, status, checked_at?}`` (D4-b decision 6, migration
    ``7332ac974920``; the closed ``status`` vocabulary is ``claimstore.packs.WORK_EMAIL_STATUSES``),
    and ``frontend_read.v1_shared.email_facts`` shows the address only for the two verdicts that
    mean it is usable. Written as a bare string — as this mapper did — the address reached the
    claim store with its verification stripped off, and the contact header's email chip read
    ``lookup`` for everybody. Only a found export is written, so the ``status`` here is always one
    of the two graded verdicts the registry admits (``verified_smtp`` / ``catch_all_valid``);
    ``checked_at`` is the provider's own check timestamp (``email.output[0].date``), kept verbatim
    and omitted when the record does not state one, which is what the chip's verification date
    reads first.
    """
    if not export.found or not export.address:
        return None
    return _draft(
        scope,
        field_key="core.work_email",
        value=_without_nones(
            {
                "address": export.address,
                "status": export.verdict,
                "checked_at": export.checked_at,
            },
            keep=("address", "status"),
        ),
        method=ExtractionMethod.API,
        source_url=None,
        evidence_span=None,
        priority=2,
        outreach_safe=True,
        confidence=0.9,
        source_key="ai_ark:email_export",
        markers={
            "json_path": "email.output[0].address",
            "provider_record": "ai_ark",
            "verdict": export.verdict,
            "provider_verified": export.verdict == _PROVIDER_VERIFIED_VERDICT,
        },
    )


def media_index_claim(
    *,
    person: str,
    item_url: str,
    kind: str,
    duration_s: int | None,
    transcript_model: str | None,
    speaker_verified: bool,
    scope: JobScope,
    title: str | None = None,
    catalog: FieldCatalog | None = None,
) -> ClaimDraft:
    """The index row for one media item, on whichever entity this job is about.

    Written whether or not the speaker was verified: "we found this episode and could not confirm
    it is them" is a finding, and dropping it would make the same item cost money again on the next
    run. ``speaker_verified`` is what decides whether anything may be quoted from it, and it is on
    the claim rather than in a comment.

    **An account job** writes ``account.media_layer_index`` exactly as it always has — a row naming
    which of the account's people appeared, in the registered ``list[object]`` shape.

    **A person job** writes the same appearance as ``contact.facet.public_appearances`` on the
    person themselves, because that is what the item *is* on a job whose subject is one person, and
    it is the key the contact display's Angles section reads. That field's registered item shape is
    ``{title (required), url?, date?, venue?}`` and carries none of the transcription metadata, so
    ``kind``, ``duration_s``, ``transcript_model`` and the person the call was made for ride as
    write markers rather than being dropped or stuffed into undeclared properties.
    """
    if scope.subject_kind == "person":
        appearance: JsonValue = _without_nones({"title": title, "url": item_url}, keep=("title",))
        return _draft(
            scope,
            field_key=PUBLIC_APPEARANCES_FIELD,
            value=[appearance],
            method=ExtractionMethod.API,
            source_url=item_url,
            evidence_span=None,
            priority=3,
            outreach_safe=True,
            confidence=0.9,
            source_key=f"media:{kind}",
            markers=_without_nones(
                {
                    "speaker_verified": speaker_verified,
                    "media_kind": kind,
                    "duration_s": duration_s,
                    "transcript_model": transcript_model,
                    "media_person": person,
                }
            ),
            use_class_hint=_hint(PUBLIC_APPEARANCES_FIELD, catalog) if catalog else None,
        )
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


def _proposed_key_subject(scope: JobScope) -> Literal["account", "contact"]:
    """Which namespace a suggested key with none of its own belongs to.

    The job's subject decides it: a person job's ``"favourite band"`` is a fact about the person,
    and giving it the ``account.`` namespace would file a personal observation under the company.
    """
    return "contact" if scope.person_subject_id is not None else "account"


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


def _required_keys(field_key: str, catalog: FieldCatalog) -> tuple[str, ...] | None:
    """The required keys of an object-typed field, or ``None`` when the field is not an object."""
    spec = catalog.spec(field_key)
    schema = spec.value_schema if spec else None
    if not schema or schema.get("type") != "object":
        return None
    required = schema.get("required")
    return tuple(str(key) for key in required) if isinstance(required, list) else ()


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


def _hint(field_key: str, catalog: FieldCatalog) -> str | None:
    """The use class the field itself declares, or ``None`` when the catalog does not carry it."""
    spec = catalog.spec(field_key)
    return spec.use_class_hint if spec else None


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
        use_class_hint=_hint(claim.field_key, catalog),
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
    subject = _proposed_key_subject(scope)
    for proposed in output.proposed:
        if not proposed.suggested_key:
            continue
        field_key = normalise_proposed_key(proposed.suggested_key, subject)
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
                use_class_hint=_hint(field_key, catalog),
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
    it. On an object-shaped field the optional keys it wrote as ``null`` are dropped, exactly as
    the deterministic mappers drop them (:func:`_without_nones`) — absent is not null, and a
    *required* key stays so the schema marker can still say the value does not fit.
    """
    drafts: list[ClaimDraft] = []
    for item in items:
        field_key = (
            item.field_key
            if is_valid_field_key(item.field_key)
            else normalise_proposed_key(item.field_key, _proposed_key_subject(scope))
        )
        value, coercion = _coerced(field_key, item.value, catalog)
        markers: dict[str, JsonValue] = dict(coercion)
        required = _required_keys(field_key, catalog)
        if required is not None and isinstance(value, Mapping):
            # The mapper path already drops the optional keys a record did not answer
            # (``_without_nones``); the agent path did not, and the re-run's two vacant seats
            # landed ``schema_valid=false`` on ``"name": null`` alone. Same rule, same helper:
            # absent is not null, and a required key stays so the marker can say it is missing.
            kept = _without_nones(value, keep=required)
            dropped: list[JsonValue] = [key for key in value if key not in kept]
            if dropped:
                markers["dropped_null_keys"] = dropped
            value = kept
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
                use_class_hint=_hint(field_key, catalog),
            )
        )
    return drafts


def fit_verdict_claims(
    verdicts: Sequence[Mapping[str, Any]],
    scope: JobScope,
    *,
    filled_by_tool: Collection[str] = (),
) -> list[ClaimDraft]:
    """One ``account.icp_fit_verdict`` claim per ICP gate, leniency enforced in code.

    Constitution §5: a ``fail`` is admissible only on positive contrary evidence, so a ``fail``
    that cites no claim ids is recorded as ``unclear`` with the reason appended to its rationale.
    The rule therefore holds even in the runs where the model forgets it — which is the whole point
    of writing it here rather than only in the prompt.

    ``filled_by_tool`` names the gates the agent never assessed, which ``finalize_research`` fills
    as ``unclear``. Their claims carry the ``filled_by_tool`` marker, so a reader can always tell
    an agent's honest "unclear" from a gate nobody looked at.
    """
    filled = set(filled_by_tool)
    drafts: list[ClaimDraft] = []
    for verdict in verdicts:
        claim_ids = [str(claim_id) for claim_id in verdict.get("claim_ids") or []]
        stated = str(verdict.get("verdict") or "unclear")
        rationale = str(verdict.get("rationale") or "")
        downgraded = stated == "fail" and not claim_ids
        if downgraded:
            stated, rationale = "unclear", f"{rationale}{DOWNGRADE_SUFFIX}"
        gate = str(verdict.get("gate") or "")
        markers: dict[str, JsonValue] = {}
        if downgraded:
            markers["downgraded_from_fail"] = True
        if gate in filled:
            markers["filled_by_tool"] = True
        value: JsonValue = _without_nones(
            {
                "gate": gate,
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
                markers=markers or None,
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
        if candidate.get("name")
        and not candidate.get("confirmed_by")
        and not candidate.get("candidate_ref")
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
        if name and not confirmed_by and not candidate.get("candidate_ref"):
            continue
        value: JsonValue = _without_nones(
            {
                "name": name,
                "title": candidate.get("title"),
                "persona": candidate.get("persona"),
                "linkedin_url": candidate.get("linkedin_url"),
                "confirmed_by": confirmed_by,
                "vacant_seat": (
                    bool(candidate.get("vacant_seat"))
                    if has_capability(scope.catalog_version, "committee_discovery")
                    else bool(candidate.get("vacant_seat")) or not name
                ),
                **(
                    {
                        key: candidate.get(key)
                        for key in (
                            "evidence_kind",
                            "candidate_ref",
                            "role_key",
                            "gap_reason",
                            "provider_subject_id",
                            "artifact_key",
                            "operation_id",
                            "parent_job_id",
                            "rationale",
                        )
                    }
                    if has_capability(scope.catalog_version, "committee_discovery")
                    else {}
                ),
                # The why behind the seat, when the agent gave one. It rides the account claim as
                # well as the member's own role claim, so the account's committee reads the same
                # reasoning the contact page shows.
                "rationale": candidate.get("rationale"),
                "influence": candidate.get("influence"),
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
    return [
        provider_evidence(draft, candidate) if candidate.get("candidate_ref") else draft
        for draft, candidate in zip(
            drafts,
            [
                c
                for c in candidates
                if not c.get("name") or c.get("confirmed_by") or c.get("candidate_ref")
            ],
            strict=True,
        )
    ]


#: The three contact fields a confirmed committee member is written on, in the order they are
#: written. ``contact.persona`` is the bare enum the ``(account, persona)`` addressing keys on;
#: ``contact.role_on_committee`` is the same role plus the agent's reasoning about it; and
#: ``contact.current_title`` is the professional fact behind both.
PERSONA_FIELD = "contact.persona"
ROLE_ON_COMMITTEE_FIELD = "contact.role_on_committee"
CURRENT_TITLE_FIELD = "contact.current_title"


def committee_member_claims(
    candidate: Mapping[str, Any],
    *,
    scope: JobScope,
    contact_id: EntityId,
    catalog: FieldCatalog,
    method: ExtractionMethod = ExtractionMethod.LLM_SYNTHESIS,
) -> list[ClaimDraft]:
    """One confirmed committee member's persona, role and title, written onto their own contact.

    The account job resolved the committee, so these are claims about a *person* written from a
    job whose own subject is the account — which is why the contact entity is passed in rather
    than inferred: the caller resolved the identity, and this module never guesses whose claim
    this is. Everything else about a contact claim is stamped as usual by :func:`_draft` (contact
    profiling, strong binding, the field's use class — read from the catalog, so nothing here
    decides a meaning the field does not declare).

    Only what the candidate actually states is written. No persona means no persona claim and no
    role claim — ``role`` is the role field's required key and its closed enum, and a role with no
    role in it is not a committee assessment. The confirming URL and the candidate's own quote
    travel onto every one of the three, so a reader of any of them reaches the page that named
    this person in this seat.

    ``method`` is how the seat was decided, and it defaults to the account job's own answer: the
    model read a page and assessed the committee. The on-demand person launch passes
    :attr:`~clue_core.ExtractionMethod.HUMAN`, because there the persona is the requesting human's
    own statement — recording that as synthesis would put a false provenance (and a tier-4 stamp)
    on a tier-1 fact.
    """
    persona = candidate.get("persona")
    title = candidate.get("title")
    source_url = candidate.get("confirmed_by")
    evidence_span = str(candidate.get("evidence_span") or "") or None
    role: JsonValue | None = (
        _without_nones(
            {
                "role": persona,
                "rationale": candidate.get("rationale"),
                "influence": candidate.get("influence"),
            },
            keep=("role",),
        )
        if persona
        else None
    )
    values: tuple[tuple[str, JsonValue | None], ...] = (
        (PERSONA_FIELD, _string(persona)),
        (ROLE_ON_COMMITTEE_FIELD, role),
        (CURRENT_TITLE_FIELD, _string(title)),
    )
    drafts = [
        _draft(
            scope,
            field_key=field_key,
            value=value,
            method=method,
            source_url=str(source_url) if source_url else None,
            evidence_span=evidence_span,
            priority=2,
            outreach_safe=True,
            confidence=0.6,
            source_key="agent",
            contact_id=contact_id,
            use_class_hint=_hint(field_key, catalog),
        )
        for field_key, value in values
        if value is not None
    ]
    if candidate.get("candidate_ref"):
        drafts = [
            provider_evidence(
                replace(
                    draft,
                    extraction_method=ExtractionMethod.API
                    if draft.field_key == CURRENT_TITLE_FIELD
                    else draft.extraction_method,
                    source_key="ai_ark:person"
                    if draft.field_key == CURRENT_TITLE_FIELD
                    else draft.source_key,
                    markers={**draft.markers, "json_path": "profile.title"}
                    if draft.field_key == CURRENT_TITLE_FIELD
                    else draft.markers,
                ),
                candidate,
            )
            for draft in drafts
        ]
    return drafts


# -- the person job's own two shapes --------------------------------------------------------------


@dataclass(frozen=True)
class UniqueInsight:
    """The one-question pass's answer, and the keys it was not allowed to answer on."""

    drafts: list[ClaimDraft]
    #: Field keys the target set refused, in the order the model wrote them. Reported on the tool
    #: result: a dropped row and a thin footprint are otherwise the same empty ``written``, and the
    #: agent would learn the wrong thing from each.
    off_target: tuple[str, ...]


def unique_insight_claims(
    output: StructuredOutput, *, scope: JobScope, catalog: FieldCatalog
) -> UniqueInsight:
    """The one-question pass's answer: at most one claim, on a fact facet, at priority 1, marked.

    The mode registers no field — the fact is written to the existing facet it actually *is* — so
    this is :func:`structured_claims` with three things forced in code rather than trusted to the
    prompt:

    * **The target keys.** Only :data:`UNIQUE_INSIGHT_TARGET_KEYS` may carry an insight. The live
      run answered on ``contact.facet.hooks``, which is the outreach argument the finalization
      builds *from* the facts, not a fact — so the insight landed as an unquoted line in the field
      the openers are drawn from. A row on any other key is dropped and named.
    * **The row cap** — the whole point of the mode is that it returns *the* one thing, not a
      second broad pass. It applies after the target filter, so an admissible second row is
      still the answer when the model's first row was off target.
    * **The priority** — this is the fact the outreach opens with, and a model that typed
      ``priority: 3`` must not be able to bury it.

    The ``unique_insight`` marker is what the finalization receipt reads to say whether the insight
    was found; it lives on the claim row.
    """
    drafts = structured_claims(output, scope=scope, subject_url_hint=None, catalog=catalog)
    on_target = [draft for draft in drafts if draft.field_key in UNIQUE_INSIGHT_TARGET_KEYS]
    off_target = tuple(
        draft.field_key for draft in drafts if draft.field_key not in UNIQUE_INSIGHT_TARGET_KEYS
    )
    return UniqueInsight(
        drafts=[
            replace(draft, signal_priority=1, markers={**draft.markers, "unique_insight": True})
            for draft in on_target[:1]
        ],
        off_target=off_target,
    )


@dataclass(frozen=True)
class PersonFinalization:
    """What a person finalization writes, and what it refused to write and why.

    The drops are returned rather than logged because each one is something the agent *proposed*
    and the code declined: an opener with no quote behind it, a reporting line nobody stated. The
    receipt says so in the same turn, which is the only way the agent learns the rule held.
    """

    drafts: list[ClaimDraft]
    openers_written: list[str]
    openers_dropped: list[str]
    hooks_written: int
    lookalikes_written: int
    reports_to_written: bool
    reports_to_skipped: str | None


def person_finalization_claims(
    *,
    openers: Sequence[Mapping[str, Any]],
    hooks: Sequence[str],
    same_name_log: Sequence[Mapping[str, Any]],
    reports_to: Mapping[str, Any] | None,
    scope: JobScope,
    catalog: FieldCatalog,
) -> PersonFinalization:
    """The four person-finalization fields, with the leniency rules enforced in code.

    * **One claim per opener**, each a one-element list in the field's registered
      ``list[string]`` shape — the same rule :func:`ats_posting_claims` follows, and for the same
      reason: an opener is the unit that gets audited and quoted, and one claim carrying three
      texts could only cite one of the three quotes, which would attach opener A's evidence to
      openers B and C. An opener whose ``quote`` is empty is **dropped** (dossier skill §3: an
      opener whose hook has no quote is dropped, never written) and named in the result.
    * **Hooks are one claim**, because the arguments carry no per-hook quote: the hooks are the
      agent's reading of claims it already wrote, so the claim cites nothing and the writer's
      ``source_missing`` marker says so honestly.
    * **One claim per same-name row.** The registered object is ``{title?, reason?,
      discarded_media?}``, so the name-or-URL the agent met goes in ``title`` and its exclusion
      reason in ``reason``; nothing is inferred from the spelling of either.
    * **``contact.reports_to`` only with its evidence.** The founder's ruling admits a reporting
      line only from an ATS reporting line or the person's own statement, so a row with no quote
      or no URL is not written — and ``contact_id`` is the field's *required* key, so a manager
      the store could not resolve is not written either. Both skips carry their reason.
    """
    drafts: list[ClaimDraft] = []
    written: list[str] = []
    dropped: list[str] = []
    for opener in openers:
        text = str(opener.get("text") or "")
        quote = str(opener.get("quote") or "").strip()
        url = opener.get("url")
        if not quote:
            dropped.append(text)
            continue
        written.append(text)
        drafts.append(
            _draft(
                scope,
                field_key=OPENERS_FIELD,
                value=[text],
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=str(url) if url else None,
                evidence_span=quote,
                priority=1,
                outreach_safe=True,
                confidence=0.6,
                source_key="agent",
                markers=_without_nones({"opener_hook": str(opener.get("hook") or "") or None}),
                use_class_hint=_hint(OPENERS_FIELD, catalog),
            )
        )

    kept_hooks = [str(hook) for hook in hooks if str(hook).strip()]
    if kept_hooks:
        drafts.append(
            _draft(
                scope,
                field_key=HOOKS_FIELD,
                value=cast(JsonValue, kept_hooks),
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=None,
                evidence_span=None,
                priority=2,
                outreach_safe=True,
                confidence=0.6,
                source_key="agent",
                use_class_hint=_hint(HOOKS_FIELD, catalog),
            )
        )

    lookalikes = 0
    for row in same_name_log:
        value: JsonValue = _without_nones(
            {
                "title": _string(row.get("name_or_url")),
                "reason": _string(row.get("why_excluded")),
            }
        )
        if not value:
            continue
        lookalikes += 1
        drafts.append(
            _draft(
                scope,
                field_key=EXCLUDED_LOOKALIKE_FIELD,
                value=value,
                method=ExtractionMethod.LLM_SYNTHESIS,
                source_url=None,
                evidence_span=None,
                priority=3,
                outreach_safe=False,
                confidence=0.6,
                source_key="agent",
                use_class_hint=_hint(EXCLUDED_LOOKALIKE_FIELD, catalog),
            )
        )

    reports_to_written = False
    skipped: str | None = None
    if reports_to is not None:
        name = _string(reports_to.get("name"))
        contact_id = _string(reports_to.get("contact_id"))
        quote = str(reports_to.get("quote") or "").strip()
        url = _string(reports_to.get("url"))
        if not quote or not url:
            skipped = (
                f"{REPORTS_TO_FIELD} is written only from an ATS reporting line or the person's "
                "own statement, so it needs both the verbatim quote and the URL it came from"
            )
        elif contact_id is None:
            skipped = (
                f"no contact under this account resolves to {name!r}, and contact_id is "
                f"{REPORTS_TO_FIELD}'s required key"
            )
        else:
            reports_to_written = True
            drafts.append(
                _draft(
                    scope,
                    field_key=REPORTS_TO_FIELD,
                    value=_without_nones(
                        {"name": name, "contact_id": contact_id}, keep=("contact_id",)
                    ),
                    method=ExtractionMethod.LLM_SYNTHESIS,
                    source_url=url,
                    evidence_span=quote,
                    priority=2,
                    outreach_safe=True,
                    confidence=0.6,
                    source_key="agent",
                    use_class_hint=_hint(REPORTS_TO_FIELD, catalog),
                )
            )

    return PersonFinalization(
        drafts=drafts,
        openers_written=written,
        openers_dropped=dropped,
        hooks_written=1 if kept_hooks else 0,
        lookalikes_written=lookalikes,
        reports_to_written=reports_to_written,
        reports_to_skipped=skipped,
    )


def provider_evidence(draft: ClaimDraft, reference: Mapping[str, Any]) -> ClaimDraft:
    """The single provenance adapter for discovery, profile and channel claims."""
    markers = {
        **draft.markers,
        "provider_record": "ai_ark",
        "provider_subject_id": str(reference["provider_subject_id"]),
        "operation_id": str(reference["operation_id"]),
    }
    return replace(draft, artifact_key=str(reference["artifact_key"]), markers=markers)


def phone_claim(phone: AiArkPhone, scope: JobScope) -> ClaimDraft | None:
    if not phone.numbers:
        return None
    return _draft(
        scope,
        field_key="core.direct_phone",
        value=phone.numbers[0],
        method=ExtractionMethod.API,
        source_url=None,
        evidence_span=None,
        priority=2,
        outreach_safe=True,
        confidence=0.6,
        source_key="ai_ark:phone",
        markers={
            "json_path": "data",
            "provider_record": "ai_ark",
            "provider_ordered": True,
            "verification_not_supplied": True,
        },
    )
