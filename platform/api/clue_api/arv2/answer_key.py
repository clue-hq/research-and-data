"""Answer-key mapping: the two proof-of-concept claim files → claim drafts (pure, no I/O).

Every rule here is a recorded plan decision (``docs/superpowers/plans/2026-09-07-arv2-d1-…md``,
"Decisions taken by this plan" 4-8, 10). Nothing is invented: a value the run did not find is a
skip, a source the run could not name is a ``source_missing`` marker left for the writer, and a
persona the run could not express in the closed vocabulary is a skip with its reason recorded.

The module is deliberately pure — it reads dictionaries and returns dataclasses. The loader (the
one caller) resolves subjects to entity ids, so nothing here touches a database, a clock or a file.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import JsonValue

from clue_core import (
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchMode,
    RunId,
    UseClass,
)
from clue_research.claimstore.packs import WORK_EMAIL_STATUSES

ANSWER_KEY_NAMESPACE = uuid.UUID("6f1c2a3e-7b4d-4e8f-9a0b-1c2d3e4f5a6b")
ZAFRAN_RUN_ID = RunId(uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:zafran:2026-09-02"))
ZAFRAN_PROJECT_RUN_ID = ProjectRunId(
    uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:project-run:v1")
)
PEOPLE_RUN_ID = RunId(uuid.uuid5(ANSWER_KEY_NAMESPACE, "arv2-answer-key:person-depth:2026-09-03"))

#: The Zafran run cited some synthesised rows against a lettered source bundle rather than a URL.
#: ``SOURCE A`` was the provider database read, which has no public URL — that row keeps ``None``.
BUNDLE_SOURCES: dict[str, str | None] = {
    "SOURCE A": None,
    "SOURCE B": "https://www.zafran.io/",
    "SOURCE C": (
        "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
        "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai"
    ),
    "SOURCE D": "https://www.youtube.com/watch?v=8_YWBtq4eic",
    "SOURCE E": "https://www.youtube.com/watch?v=avcD5WVLCYs",
    "SOURCE F": "https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf",
}

#: The two committee roles the run wrote that are not ``Persona`` members. Everything else must
#: already be one; an unmappable value is a skip, never a guess.
PERSONA_MAP: dict[str, str] = {"executive_sponsor": "economic_buyer", "adjacent_buyer": "user"}

#: Both files' use-class spellings (the Zafran run underscored them, the person-depth run
#: hyphenated them). ``business_public`` is an account fact, which carries no use class at all.
USE_CLASS_MAP: dict[str, UseClass | None] = {
    "business_public": None,
    "professional_public": UseClass.PROFESSIONAL_PUBLIC,
    "personal_public_self_stated": UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    "professional-public": UseClass.PROFESSIONAL_PUBLIC,
    "personal-public-non-sensitive": UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
}

#: Signal priority for the Zafran fields (the person-depth rows carry their own ``priority``).
#: 1 = a buying signal, 2 = a qualifying or resonance fact, 3 = everything else.
ZAFRAN_PRIORITY: dict[str, int] = {
    "account.open_requisitions": 1,
    "account.hiring_velocity": 1,
    "account.hiring_velocity_eng": 1,
    "account.abm_program_maturity": 1,
    "account.operational_pain": 1,
    "account.strategic_moves": 1,
    "account.recent_funding": 2,
    "account.total_funding": 2,
    "account.gtm_tooling_stack": 2,
    "account.named_customers": 2,
    "account.reputation_risk": 2,
    "account.claimed_customer_logos": 2,
    "account.claimed_outcomes_metrics": 2,
    "core.annual_revenue": 2,
    "core.revenue_band": 2,
    "core.employee_count": 2,
    "core.employee_range": 2,
    "account.resonance.attrition_signal": 2,
    "account.resonance.buying_culture": 2,
    "account.resonance.public_frustrations": 2,
    "account.resonance.culture": 2,
    "account.resonance.eng_blog_tone": 2,
    "contact.facet.hobby": 2,
    "contact.facet.voice_quote": 2,
    "contact.facet.recent_post": 2,
    "contact.facet.publications": 2,
    "contact.facet.public_appearances": 2,
    "contact.facet.certifications": 2,
    "contact.facet.recent_award": 2,
    "contact.facet.communication_style": 2,
    "contact.facet.stated_interests": 2,
    "contact.facet.career_history": 2,
}

#: The closed persona vocabulary, as plain strings (``Persona`` is a ``StrEnum``).
_PERSONA_VALUES = frozenset(persona.value for persona in Persona)

#: A Zafran contact claim binds strongly only when the source named the person itself.
_STRONG_SOURCE_KINDS = frozenset({"provider_database", "transcript_self", "company_primary"})
_CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}
_DEFAULT_CONFIDENCE = 0.7
_METHOD_FOR_KIND = {
    "deterministic": ExtractionMethod.API,
    "deterministic_media": ExtractionMethod.SCRAPE,
    "exclusion": ExtractionMethod.SCRAPE,
    "synthesised": ExtractionMethod.LLM_SYNTHESIS,
    "proposed_field": ExtractionMethod.LLM_SYNTHESIS,
}
_PROPOSED_PREFIX = "PROPOSED::"
_PROPOSED_ORIGIN = "structuring_pass"
_NOT_FOUND = "NOT FOUND"
#: The marker every loaded Zafran answer-key claim carries, so a reader can find exactly the
#: rows this mapping wrote (the recall measurement reads them back through it). Public
#: because it is a join key, not an internal detail.
ZAFRAN_ANSWER_KEY = "zafran-2026-09-02"
#: The same join key for the ten-person depth answer key (the R3 per-person recall reads it back).
PEOPLE_ANSWER_KEY = "person-depth-2026-09-03"
_ZAFRAN_OBSERVED_DEFAULT = "2026-09-02"
#: The person-depth run date (``.context/arv2-person-depth/PERSON-DEPTH-REPORT.md``).
_PEOPLE_OBSERVED_DEFAULT = "2026-09-03"
_PEOPLE_SOURCE_KEY = "arv2_person_depth"
_PEOPLE_PRIORITY = {"P1": 1, "P2": 2, "P3": 3}


# -- the manifest -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonSpec:
    """One contact the answer key names, and enough to create their entity."""

    key: str
    name: str
    title: str
    company_domain: str
    linkedin_url: str


@dataclass(frozen=True)
class AccountSpec:
    """One account the answer key names."""

    key: str
    name: str
    domain: str


@dataclass(frozen=True)
class MediaSpec:
    """One transcribed media item the Zafran run quoted from."""

    media_url: str
    transcript_file: str
    title: str


@dataclass(frozen=True)
class DocumentSpec:
    """One brand-knowledge document the answer-key workspace carries as a confirmed stand-in.

    Track O's synthesis agent (O4) will author these and a human will confirm them through the ICP
    gate (O6); until then the research lane needs a confirmed ``icp-definition`` to pin a launch on,
    so the loader registers these hand-written files the way O6 would — one document row, one
    content-addressed artifact, status ``confirmed`` — and stamps the spine ids (brand, products,
    project, selection version) that only exist at load time.
    """

    path: str  # ``<folder>/<name>.md`` — the same path the brand-context page shows
    kind: str  # ``icp-definition`` | ``audience-persona``
    file: str  # the source file under ``.context/arv2-answer-key-knowledge/``


@dataclass(frozen=True)
class AnswerKeyManifest:
    """The workspace, project and subjects the two answer-key files describe."""

    workspace_id: str
    workspace_name: str
    brand_name: str
    product_name: str
    project_id: str
    project_name: str
    run_id: RunId
    project_run_id: ProjectRunId
    accounts: tuple[AccountSpec, ...]
    people: tuple[PersonSpec, ...]
    media: tuple[MediaSpec, ...]
    documents: tuple[DocumentSpec, ...]
    #: The ICP the project run and the confirmed ICP document both name (master plan §5.2).
    icp_key: str


ZAFRAN_MANIFEST = AnswerKeyManifest(
    workspace_id="ws_arv2_answer_key",
    workspace_name="ARV2 answer key",
    brand_name="Clue",
    product_name="Clue",
    project_id="prj_arv2_answer_key",
    project_name="ARV2 answer key — Zafran",
    run_id=ZAFRAN_RUN_ID,
    project_run_id=ZAFRAN_PROJECT_RUN_ID,
    accounts=(
        AccountSpec(key="zafran", name="Zafran Security", domain="zafran.io"),
        AccountSpec(key="cogent", name="Cogent Security", domain="cogent.com"),
        AccountSpec(key="harmonic", name="Harmonic Security", domain="harmonic.security"),
        AccountSpec(key="uptiq", name="UPTIQ, Inc.", domain="uptiq.ai"),
        # The second fixed answer key (master plan §10 item 6): researched by the v3 sample run
        # (``.context/arv2-clue-sample-v3``). Only the entity is seeded — R2 researches it live and
        # the run's ``claims.json`` is what the result is compared against, so loading those rows
        # here would pre-empt the very gate they exist to check.
        AccountSpec(key="probook", name="Probook", domain="probook.ai"),
    ),
    people=(
        PersonSpec(
            key="vari_kaur",
            name="Vari Kaur",
            title="Head of Growth Marketing",
            company_domain="zafran.io",
            linkedin_url="https://www.linkedin.com/in/varinderkaur",
        ),
        PersonSpec(
            key="nick_fisher",
            name="Nick Fisher",
            title="VP Marketing",
            company_domain="zafran.io",
            linkedin_url="https://www.linkedin.com/in/nicholastfisher",
        ),
        PersonSpec(
            key="sanaz_yashar",
            name="Sanaz Yashar",
            title="Co-Founder & CEO",
            company_domain="zafran.io",
            linkedin_url="https://www.linkedin.com/in/sanaz-yashar",
        ),
        PersonSpec(
            key="alexander_semien",
            name="Alexander Semien",
            title="Head of Growth",
            company_domain="cogent.com",
            linkedin_url="https://www.linkedin.com/in/alexander-semien",
        ),
        PersonSpec(
            key="cameron_coles",
            name="Cameron Coles",
            title="VP of Marketing",
            company_domain="cogent.com",
            linkedin_url="https://www.linkedin.com/in/cameroncoles",
        ),
        PersonSpec(
            key="vineet_edupuganti",
            name="Vineet Edupuganti",
            title="Co-Founder & CEO",
            company_domain="cogent.com",
            linkedin_url="https://www.linkedin.com/in/vineetedupuganti",
        ),
        PersonSpec(
            key="ana_corio",
            name="Ana Corio",
            title="Director of Demand Generation",
            company_domain="harmonic.security",
            linkedin_url="https://www.linkedin.com/in/anastasiacorio",
        ),
        PersonSpec(
            key="tyler_chonoles",
            name="Tyler Chonoles",
            title="Growth and Demand Gen Marketing Manager",
            company_domain="harmonic.security",
            linkedin_url="https://www.linkedin.com/in/tyler-chonoles-106405a0",
        ),
        PersonSpec(
            key="alastair_paterson",
            name="Alastair Paterson",
            title="CEO & Co-Founder",
            company_domain="harmonic.security",
            linkedin_url="https://www.linkedin.com/in/alastair-paterson-2586445",
        ),
        PersonSpec(
            key="mandar_marathe",
            name="Mandar Marathe",
            title="VP Marketing",
            company_domain="uptiq.ai",
            linkedin_url="https://www.linkedin.com/in/mandarmarathe",
        ),
        # The Zafran committee rows name two people the person-depth roster does not: both need an
        # entity, or their claims have no subject to hang on.
        PersonSpec(
            key="tom_anthony",
            name="Tom Anthony",
            title="SVP, Global Sales",
            company_domain="zafran.io",
            linkedin_url="https://www.linkedin.com/in/tomanthonyjr",
        ),
        PersonSpec(
            key="ben_seri",
            name="Ben Seri",
            title="Co-Founder & CTO",
            company_domain="zafran.io",
            linkedin_url="https://www.linkedin.com/in/ben-seri",
        ),
    ),
    media=(
        MediaSpec(
            media_url=(
                "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
                "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai"
            ),
            transcript_file="sanaz_boardroom.md",
            title="AI Summit: Sanaz Yashar (Boardroom Club)",
        ),
        MediaSpec(
            media_url="https://www.youtube.com/watch?v=8_YWBtq4eic",
            transcript_file="nick_supporting_cc.md",
            title="Supporting Cocktail Chemistry",
        ),
        MediaSpec(
            media_url="https://www.youtube.com/watch?v=avcD5WVLCYs",
            transcript_file="nick_moscow_mule.md",
            title="Perfect Moscow Mule",
        ),
    ),
    documents=(
        DocumentSpec(
            path="audience/icp-clue-abm-buyers.md",
            kind="icp-definition",
            file="icp-clue-abm-buyers.md",
        ),
        DocumentSpec(
            path="audience/persona-clue-abm-buyers.md",
            kind="audience-persona",
            file="persona-clue-abm-buyers.md",
        ),
    ),
    icp_key="clue-abm-buyers",
)


# -- the drafts ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RowDraft:
    """One answer-key row, mapped — a draft before entity ids are known."""

    subject: str  # "account:<domain>" or "contact:<linkedin_url>"
    entity_type: EntityType
    field_key: str
    value_json: JsonValue
    extraction_method: ExtractionMethod
    research_mode: ResearchMode
    source_url: str | None
    source_key: str | None
    evidence_span: str | None
    observed_at: datetime | None
    confidence: float
    identity_binding: IdentityBinding | None
    use_class: UseClass | None
    signal_priority: int
    outreach_safe: bool
    media_url: str | None
    field_description: str | None
    markers: dict[str, JsonValue]
    source_row_id: str


@dataclass(frozen=True)
class Skip:
    """A row that produced no draft, and why. Reasons: not_found, duplicate_persona,
    unknown_persona."""

    source_row_id: str
    reason: str


@dataclass(frozen=True)
class MappedRows:
    """Everything one answer-key file yields: the drafts, and the rows deliberately dropped."""

    drafts: tuple[RowDraft, ...]
    skips: tuple[Skip, ...]


# -- shared rules -------------------------------------------------------------------------------


def _contact_subject(linkedin_url: str) -> str:
    return "contact:" + linkedin_url.strip().lower().rstrip("/")


def resolve_source_url(raw: str | None) -> str | None:
    """The first citable URL in a Zafran ``source_url`` cell, or ``None``.

    A cell is one or more ``" / "``-joined tokens: an http URL, or a ``BUNDLE: SOURCE X`` label
    list resolved through :data:`BUNDLE_SOURCES`. ``SOURCE A`` (the provider database) has no URL,
    so a row citing only it keeps ``None`` and the writer marks it ``source_missing``.
    """
    if not raw:
        return None
    for token in (part.strip() for part in raw.split(" / ")):
        if token.startswith("http"):
            return token
        # ``BUNDLE: SOURCE A / SOURCE B`` splits into a labelled first token and bare ones after,
        # so the prefix is optional on every token.
        for label in (name.strip() for name in token.removeprefix("BUNDLE:").split("/")):
            url = BUNDLE_SOURCES.get(label)
            if url:
                return url
    return None


def priority_for(field_key: str, entity_type: EntityType) -> int:
    """The Zafran signal priority for a field; anything unlisted is background (3)."""
    del entity_type  # the key already names its entity; the argument keeps the call site explicit
    return ZAFRAN_PRIORITY.get(field_key, 3)


def _observed(date_text: str | None, default: str) -> datetime:
    """``YYYY-MM-DD`` → aware UTC midnight, falling back to ``default``.

    A person-depth ``source_timestamp`` is sometimes a media offset ("37:46") rather than a date,
    so anything that is not a date is the run date — never a crash and never a fabricated day.
    """
    if date_text:
        try:
            return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.strptime(default, "%Y-%m-%d").replace(tzinfo=UTC)


#: The one field whose value is the provider's graded verdict rather than the raw observation.
WORK_EMAIL_KEY = "core.work_email"
#: A provider verdict this lane does not recognise (AI Ark's ``not_found``, a future label, a typo)
#: is graded ``unknown`` rather than stored as-is: the registry declares a closed vocabulary, and
#: "the provider checked and did not confirm" is exactly what an unrecognised verdict means.
_UNRECOGNISED_VERDICT = "unknown"
#: No ``verification`` block at all means nobody probed the mailbox — not that it failed.
_UNPROBED = "unverified"


def work_email_value(address: JsonValue, verification: Mapping[str, Any] | None) -> JsonValue:
    """A ``core.work_email`` value: the address with the verdict that grades it (decision 6).

    The answer key kept AI Ark's whole verification block beside the address; the claim keeps the
    two facts a reader needs from it — the verdict and when the mailbox was checked. ``checked_at``
    is omitted rather than written null when the provider gave none: the registry's value-schema
    validator has no union type, and every reader asks with ``.get("checked_at")`` anyway.
    """
    if not isinstance(address, str):
        return address  # a value that is not an address is left exactly as the run recorded it
    verdict = verification.get("verdict") if verification else None
    status = str(verdict) if isinstance(verdict, str) else None
    value: dict[str, JsonValue] = {
        "address": address,
        "status": (
            _UNPROBED
            if verification is None
            else status
            if status in WORK_EMAIL_STATUSES
            else _UNRECOGNISED_VERDICT
        ),
    }
    checked_at = verification.get("checked_at") if verification else None
    if isinstance(checked_at, str) and checked_at:
        value["checked_at"] = checked_at
    return value


def _is_not_found(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_NOT_FOUND)


def _split_field_keys(field_key: str) -> tuple[list[str], str | None]:
    """``"a|b"`` → the two keys and the original joined spelling (kept as a marker)."""
    if "|" not in field_key:
        return [field_key], None
    return [part.strip() for part in field_key.split("|") if part.strip()], field_key


def _zafran_source_key(provider: str | None) -> str | None:
    """The tool that produced the row: the first provider named, normalised.

    The run recorded chains (``exa_deep_reasoning|exa_contents|gemini``), combinations
    (``exa_contents+gemini``) and structuring annotations (``… (structured by gpt-5-mini)``).
    The head of the chain is the source of record; the rest is how it was post-processed.
    """
    if not provider:
        return None
    head = provider.split("|", 1)[0].split("+", 1)[0].split("(", 1)[0]
    return head.strip().lower().replace(" ", "_") or None


# -- the Zafran file ----------------------------------------------------------------------------


def _zafran_personas(
    rows: Sequence[Mapping[str, Any]], name_to_url: Mapping[str, str]
) -> dict[str, str]:
    """Each contact's committee persona, in file order — the first valid value wins.

    ``contact.role_on_committee`` is free text and has to be filed under a persona, so the personas
    are read before any row is mapped.
    """
    personas: dict[str, str] = {}
    for row in rows:
        if row.get("field_key") != "contact.persona" or _is_not_found(row.get("value")):
            continue
        value = row.get("value")
        if not isinstance(value, str):
            continue
        persona = PERSONA_MAP.get(value, value)
        if persona not in _PERSONA_VALUES:
            continue
        subject = _zafran_subject(row, name_to_url)[0]
        personas.setdefault(subject, persona)
    return personas


def _zafran_name_to_url(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """``{person name: LinkedIn URL}`` from the rows that key on a URL.

    Half the Zafran contact rows key on a bare name; the run named the same five people either way,
    so the URL-keyed rows are the lookup that resolves them.
    """
    return {
        str(row["person"]): str(row["entity_key"])
        for row in rows
        if row.get("entity") == "contact" and str(row.get("entity_key", "")).startswith("http")
    }


def _zafran_subject(
    row: Mapping[str, Any], name_to_url: Mapping[str, str]
) -> tuple[str, EntityType]:
    entity_key = str(row["entity_key"])
    if row["entity"] == "account":
        return f"account:{entity_key}", EntityType.ACCOUNT
    url = entity_key if entity_key.startswith("http") else name_to_url[entity_key]
    return _contact_subject(url), EntityType.CONTACT


def map_zafran_rows(payload: Mapping[str, Any]) -> MappedRows:
    """The one-account Zafran answer key → drafts, in file order."""
    rows: Sequence[Mapping[str, Any]] = payload["claims"]
    name_to_url = _zafran_name_to_url(rows)
    personas = _zafran_personas(rows, name_to_url)

    drafts: list[RowDraft] = []
    skips: list[Skip] = []
    persona_written: set[str] = set()

    for row in rows:
        row_id = str(row["claim_id"])
        value: JsonValue = row["value"]
        if _is_not_found(value):
            skips.append(Skip(source_row_id=row_id, reason="not_found"))
            continue

        subject, entity_type = _zafran_subject(row, name_to_url)
        raw_key = str(row["field_key"])
        markers: dict[str, JsonValue] = {"source_row_id": row_id, "answer_key": ZAFRAN_ANSWER_KEY}

        description: str | None = None
        if raw_key.startswith(_PROPOSED_PREFIX):
            raw_key = raw_key.removeprefix(_PROPOSED_PREFIX)
            markers["proposed_field_origin"] = _PROPOSED_ORIGIN
            description = row.get("why") or row.get("note")

        if raw_key == "contact.persona":
            persona = PERSONA_MAP.get(value, value) if isinstance(value, str) else None
            if persona not in _PERSONA_VALUES:
                reason = "duplicate_persona" if subject in persona_written else "unknown_persona"
                skips.append(Skip(source_row_id=row_id, reason=reason))
                continue
            value = persona
            persona_written.add(subject)
        elif raw_key == "contact.role_on_committee" and isinstance(value, str):
            value = {"role": personas.get(subject), "rationale": value}
        elif raw_key == WORK_EMAIL_KEY:
            block = row.get("verification")
            value = work_email_value(value, block if isinstance(block, Mapping) else None)

        media_url = row.get("media_url")
        if media_url:
            value = {
                "text": value,
                "media_url": media_url,
                "media_timestamp": row.get("media_timestamp"),
            }

        keys, joined = _split_field_keys(raw_key)
        if joined:
            markers["pipe_joined_key"] = joined

        use_class = (
            None if entity_type is EntityType.ACCOUNT else USE_CLASS_MAP[str(row["use_class"])]
        )
        binding = (
            None
            if entity_type is EntityType.ACCOUNT
            else (
                IdentityBinding.STRONG
                if row.get("source_kind") in _STRONG_SOURCE_KINDS
                else IdentityBinding.WEAK
            )
        )
        research_mode = (
            ResearchMode.ACCOUNT_PROFILING
            if entity_type is EntityType.ACCOUNT
            else ResearchMode.CONTACT_PROFILING
        )
        drafts.extend(
            RowDraft(
                subject=subject,
                entity_type=entity_type,
                field_key=field_key,
                value_json=value,
                extraction_method=_METHOD_FOR_KIND[str(row["claim_kind"])],
                research_mode=research_mode,
                source_url=resolve_source_url(row.get("source_url")),
                source_key=_zafran_source_key(row.get("source_provider")),
                evidence_span=row.get("evidence_span") or row.get("evidence_span_2"),
                observed_at=_observed(row.get("observed_at"), _ZAFRAN_OBSERVED_DEFAULT),
                confidence=_CONFIDENCE.get(str(row.get("confidence")), _DEFAULT_CONFIDENCE),
                identity_binding=binding,
                use_class=use_class,
                signal_priority=priority_for(field_key, entity_type),
                outreach_safe=bool(row["outreach_safe"]),
                media_url=media_url,
                field_description=description,
                markers=dict(markers),
                source_row_id=row_id,
            )
            for field_key in keys
        )

    return MappedRows(drafts=tuple(drafts), skips=tuple(skips))


# -- the person-depth file ----------------------------------------------------------------------


def map_people_rows(payload: Mapping[str, Any], roster: Sequence[Mapping[str, Any]]) -> MappedRows:
    """The ten-person depth answer key → drafts. Every row is evidenced, so nothing is skipped."""
    domains = {str(person["key"]): str(person["domain"]) for person in roster}

    drafts: list[RowDraft] = []
    for person_key, person in payload["people"].items():
        subject = _contact_subject(str(person["linkedin"]))
        for position, row in enumerate(person["claims"], start=1):
            row_id = f"{person_key}-{position:03d}"
            markers: dict[str, JsonValue] = {
                "source_row_id": row_id,
                "answer_key": PEOPLE_ANSWER_KEY,
            }
            company_domain = domains.get(str(person_key))
            if company_domain:
                markers["company_domain"] = company_domain

            keys, joined = _split_field_keys(str(row["field_key"]))
            if joined:
                markers["pipe_joined_key"] = joined

            # The person-depth run recorded no email at all, but the rule is the field's, not the
            # file's: an address written here would carry its verdict too — an unprobed one.
            value: JsonValue = row["value"]
            if WORK_EMAIL_KEY in keys:
                value = work_email_value(value, None)

            drafts.extend(
                RowDraft(
                    subject=subject,
                    entity_type=EntityType.CONTACT,
                    field_key=field_key,
                    value_json=value,
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    source_url=row.get("source_url"),
                    source_key=_PEOPLE_SOURCE_KEY,
                    evidence_span=row.get("evidence_quote"),
                    observed_at=_observed(row.get("source_timestamp"), _PEOPLE_OBSERVED_DEFAULT),
                    confidence=_CONFIDENCE.get(str(row.get("confidence")), _DEFAULT_CONFIDENCE),
                    identity_binding=IdentityBinding(str(row["identity_binding"]).lower()),
                    use_class=USE_CLASS_MAP[str(row["use_class"])],
                    signal_priority=_PEOPLE_PRIORITY[str(row["priority"])],
                    outreach_safe=bool(row["outreach_safe"]),
                    media_url=None,  # the person-depth rows cite pages, never media
                    field_description=None,
                    markers=dict(markers),
                    source_row_id=row_id,
                )
                for field_key in keys
            )

    return MappedRows(drafts=tuple(drafts), skips=())
