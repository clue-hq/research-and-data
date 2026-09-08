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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from clue_api.arv2.ai_ark_client import AiArkCompany
from clue_api.arv2.ats_client import BoardPostings
from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.structuring_client import NegativeOrRisk, StructuredOutput
from clue_core import EntityId, EntityType, ExtractionMethod, ResearchMode, RunId

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
    "committee_candidate_claims",
    "fit_verdict_claims",
    "media_index_claim",
    "negative_claims",
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
        row: JsonValue = {
            "title": posting.title,
            "dept": posting.department,
            "published": published,
            "days_open": posting.days_open,
            "still_listed": posting.is_listed,
            "url": posting.url,
        }
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


#: The **only** AI Ark company fields that become claims, each with the exact path the value was
#: read from in the provider record (``ai_ark_client.company_from_record``). Everything else stays
#: in ``raw`` and is returned to the model as context, never written as a typed fact.
_AI_ARK_COMPANY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("linkedin", "core.company_linkedin_url", "link.linkedin"),
    ("industry", "core.industry", "summary.industry"),
    ("employee_count", "core.employee_count", "summary.staff.total"),
    ("revenue", "core.revenue_band", "financial.revenue.annual.amount"),
    ("location", "core.hq_location", "location.headquarter"),
)


def ai_ark_company_claims(company: AiArkCompany, scope: JobScope) -> list[ClaimDraft]:
    """The five mapped firmographic fields, cited by raw path rather than by a fake URL.

    ``https://api.ai-ark.com/v1/companies?domain=…`` is not a page a human can open, so writing it
    as ``source_url`` would manufacture provenance. The claim cites the record instead: the
    ``json_path`` of the value plus ``provider_record='ai_ark'``, which is what a replay actually
    needs. The lenient writer marks the missing URL, and the display layer renders the provider.
    """
    drafts: list[ClaimDraft] = []
    for attribute, field_key, json_path in _AI_ARK_COMPANY_FIELDS:
        raw_value = getattr(company, attribute)
        if raw_value is None:
            continue
        value: JsonValue = dict(raw_value) if isinstance(raw_value, Mapping) else raw_value
        drafts.append(
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
                source_key="ai_ark:company",
                markers={"json_path": json_path, "provider_record": "ai_ark"},
            )
        )
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
    row: JsonValue = {
        "person": person,
        "url": item_url,
        "kind": kind,
        "duration_s": duration_s,
        "transcript_model": transcript_model,
        "speaker_verified": speaker_verified,
    }
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
            value={
                "what": negative.what,
                "status": negative.status.lower() if negative.status else None,
                "source_note": None,
            },
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


def structured_claims(
    output: StructuredOutput, *, scope: JobScope, subject_url_hint: str | None
) -> list[ClaimDraft]:
    """The structuring pass's claims and proposed fields, annotations intact.

    The annotations travel as write markers because they are facts *about the extraction* — was the
    quote really in the material, did the value fit the field's schema, which mode asked for it —
    and the audit skill reads them off the claim rather than re-deriving them.

    ``subject_url_hint`` fills a claim whose ``source_url`` the model omitted (a page fetched by
    ``fetch_page`` is often the whole material). It is a *fallback*, never an override.
    """
    drafts = [
        _draft(
            scope,
            field_key=claim.field_key,
            value=claim.value,  # type: ignore[arg-type]  # a parsed JSON value is a JsonValue
            method=ExtractionMethod.LLM_SYNTHESIS,
            source_url=claim.source_url or subject_url_hint,
            evidence_span=claim.evidence_span or None,
            priority=claim.priority,
            outreach_safe=False if claim.field_key in ALWAYS_UNSAFE_FIELDS else claim.outreach_safe,
            confidence=_CONFIDENCE_WORDS.get((claim.confidence or "").strip().lower(), 0.5),
            source_key="structuring",
            markers={
                "evidence_verbatim": claim.evidence_verbatim,
                "schema_valid": claim.schema_valid,
                "source_kind": claim.source_kind,
                "media_timestamp": claim.media_timestamp,
                "structuring_mode": output.mode,
            },
        )
        for claim in output.claims
    ]
    drafts.extend(
        _draft(
            scope,
            field_key=proposed.suggested_key,
            value=proposed.value,  # type: ignore[arg-type]  # a parsed JSON value is a JsonValue
            method=ExtractionMethod.LLM_SYNTHESIS,
            source_url=proposed.source_url or subject_url_hint,
            evidence_span=proposed.evidence_span or None,
            priority=3,
            outreach_safe=True,
            confidence=0.5,
            source_key="structuring",
            markers={"proposed_origin": proposed.origin, "structuring_mode": output.mode},
            field_description=proposed.why or None,
        )
        for proposed in output.proposed
        if proposed.suggested_key
    )
    return drafts


# -- what the agent itself decided ----------------------------------------------------------------


def agent_claims(items: Sequence[ClaimInput], scope: JobScope) -> list[ClaimDraft]:
    """The claims the model wrote itself, tiered as synthesis whatever it says its source was."""
    return [
        _draft(
            scope,
            field_key=item.field_key,
            value=item.value,
            method=ExtractionMethod.LLM_SYNTHESIS,
            source_url=str(item.source_url) if item.source_url else None,
            evidence_span=item.evidence_span,
            priority=item.priority,
            outreach_safe=False if item.field_key in ALWAYS_UNSAFE_FIELDS else item.outreach_safe,
            confidence=item.confidence,
            source_key="agent",
            markers={"corrects_claim_id": item.corrects_claim_id}
            if item.corrects_claim_id
            else None,
        )
        for item in items
    ]


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
        value: JsonValue = {
            "gate": str(verdict.get("gate") or ""),
            "verdict": stated,
            "rationale": rationale,
            "claim_ids": list(claim_ids),
        }
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
        value: JsonValue = {
            "name": name,
            "title": candidate.get("title"),
            "persona": candidate.get("persona"),
            "linkedin_url": candidate.get("linkedin_url"),
            "confirmed_by": confirmed_by,
            "vacant_seat": bool(candidate.get("vacant_seat")) or not name,
        }
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


#: The two subject kinds ``structure_material`` knows about. R2 admits only the first.
SubjectKind = Literal["account", "person"]
