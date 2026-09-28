"""Employment and buying remit are evidenced assessments, never contact-parent inference.

The reader rechecks live support on every request. A contradictory person finding removes the
established seat immediately, even while account reconciliation and page refresh are queued.
Canonical identity, affiliation, buying remit and permitted use remain separate decisions.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, ResearchScope, ReuseScope
from clue_research.claimstore.packs import SeedField, load_pack
from clue_research.claimstore.quality import eligible_sql

EMPLOYMENT = "contact.employment_assessment"
COMMITTEE = "account.committee_assessment"
SELECTION = "account.committee_selection"


class OrganizationScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    relationship: Literal["exact_company", "parent", "subsidiary", "affiliate", "unresolved"]
    geography: Literal["local", "regional", "global", "remote", "unresolved"]
    location_relevance: Literal["required", "supporting", "not_required", "unresolved"]
    rationale: str = Field(min_length=1, max_length=3000)


class EmploymentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: UUID
    contact_id: UUID
    affiliation: Literal["supported", "unresolved", "refuted"]
    time_scope: Literal["current", "historical", "unknown"]
    assessed_on: date
    organization_scope: OrganizationScope
    rationale: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def positive_affiliation_requires_resolved_organization(self) -> EmploymentAssessment:
        if self.affiliation == "supported" and (
            self.organization_scope.relationship == "unresolved"
            or self.organization_scope.location_relevance == "unresolved"
        ):
            raise ValueError(
                "supported affiliation requires an explicit organization/location decision"
            )
        return self


class CommitteeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: UUID
    contact_id: UUID
    context_id: UUID
    persona_key: str = Field(min_length=1, max_length=200)
    role: Literal["champion", "economic_buyer", "technical_evaluator", "blocker", "other"]
    state: Literal["candidate", "supported", "needs_verification", "excluded"]
    remit: Literal["supported", "hypothesis", "unresolved", "refuted"]
    organization_scope: OrganizationScope
    employment_claim_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    rationale: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def supported_seat_requires_affiliation_and_remit(self) -> CommitteeAssessment:
        if self.state == "supported" and (
            not self.employment_claim_ids or self.remit != "supported"
        ):
            raise ValueError(
                "an established seat requires employment evidence and supported buying remit"
            )
        return self


class CommitteeMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contact_id: UUID
    assessment_claim_id: UUID
    persona_key: str
    proposed_role: str
    state: Literal["candidate", "supported", "needs_verification", "excluded"]
    employment_claim_ids: tuple[UUID, ...]
    gaps: tuple[str, ...] = ()
    outreach_eligible: bool = False


def _registry_schema(model: type[BaseModel]) -> dict[str, Any]:
    # The registry's deliberately small validator accepts object properties, while Pydantic
    # enforces UUID/date/enums/nested meaning at the one proposal contract below.
    return {
        "type": "object",
        "required": list(model.model_fields),
        "properties": {key: {} for key in model.model_fields},
    }


async def load_relationship_fields(conn: AsyncConnection) -> None:
    await load_pack(
        conn,
        tuple(
            SeedField(
                field_def=FieldDef(
                    field_key=key,
                    value_type="object",
                    tier_plan=(),
                    gate=None,
                    freshness_ttl=timedelta(days=30),
                    pass_kind=PassKind.DEEP,
                    research_scope=scope,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    validation={"use_class_hint": "professional_public"},
                ),
                value_schema=_registry_schema(model),
                description=description,
            )
            for key, model, scope, description in (
                (
                    EMPLOYMENT,
                    EmploymentAssessment,
                    ResearchScope.PROJECT_NEUTRAL,
                    "An evidence-backed assessment of one person's affiliation with the exact "
                    "account, "
                    "including current or historical scope and the relevance of location. "
                    "Identity alone "
                    "does not establish affiliation.",
                ),
                (
                    COMMITTEE,
                    CommitteeAssessment,
                    ResearchScope.PROJECT_RELATIVE,
                    "An assessment of one person's buying remit for an exact project context "
                    "and account. "
                    "Candidates and unresolved affiliation are not established committee members.",
                ),
            )
        ),
    )


async def validate_relationship(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: UUID,
    contact_id: UUID | None,
    context_id: UUID,
    field_key: str,
    value: object,
    support_claim_ids: set[UUID],
) -> EmploymentAssessment | CommitteeAssessment | None:
    if field_key not in (EMPLOYMENT, COMMITTEE):
        return None
    model = EmploymentAssessment if field_key == EMPLOYMENT else CommitteeAssessment
    assessment = model.model_validate(value)
    if assessment.account_id != account_id or (
        contact_id is not None and assessment.contact_id != contact_id
    ):
        raise ValueError("relationship assessment names another subject")
    if (field_key == EMPLOYMENT) != (contact_id is not None):
        raise ValueError(
            "employment belongs to person research; committee belongs to account research"
        )
    present = (
        await conn.execute(
            text("""SELECT id FROM contact_entity
        WHERE id=:contact AND workspace_id=:ws AND merged_into IS NULL AND full_name IS
        NOT NULL AND NOT EXISTS (SELECT 1 FROM provider_identity p WHERE
        p.workspace_id=:ws AND p.contact_id=contact_entity.id AND p.erased_at IS NOT
        NULL)"""),
            {"contact": assessment.contact_id, "ws": workspace_id},
        )
    ).scalar_one_or_none()
    if present is None:
        raise ValueError("relationship identity unavailable")
    if isinstance(assessment, CommitteeAssessment):
        if assessment.context_id != context_id:
            raise ValueError("committee belongs to another project context")
        if not set(assessment.employment_claim_ids).issubset(support_claim_ids):
            raise ValueError("employment references must also be registered derivation supports")
        for cid in assessment.employment_claim_ids:
            row = (
                await conn.execute(
                    text(
                        """SELECT value_json FROM claim WHERE id=:id
                AND workspace_id=:ws AND entity_id=:contact AND field_key=:field
                AND superseded_by IS NULL AND """
                        + eligible_sql()
                    ),
                    {
                        "id": cid,
                        "ws": workspace_id,
                        "contact": assessment.contact_id,
                        "field": EMPLOYMENT,
                    },
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError("employment reference is not applicable")
            employment = EmploymentAssessment.model_validate(row)
            if employment.account_id != account_id:
                raise ValueError("employment reference names another account")
            if assessment.state == "supported" and (
                employment.affiliation != "supported" or employment.time_scope != "current"
            ):
                raise ValueError("established committee requires current supported affiliation")
    return assessment


async def read_committee(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: UUID,
    context_id: UUID,
) -> tuple[CommitteeMember, ...]:
    # Fetch newest assessment per person/persona, including unresolved/invalid corrections.
    # Filtering those away first could resurrect a previously incorrect supported membership.
    rows = (
        (
            await conn.execute(
                text(
                    """SELECT c.id,c.value_json,c.outreach_safe,c.write_markers,
        q.conclusion, ("""
                    + eligible_sql("c")
                    + """) AS applicable
        FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.entity_id=:account AND c.field_key=ANY(:fields)
          AND c.superseded_by IS NULL AND q.context_id=:context
        ORDER BY c.collected_at DESC,c.id DESC"""
                ),
                {
                    "ws": workspace_id,
                    "account": account_id,
                    "fields": [COMMITTEE, SELECTION],
                    "context": context_id,
                },
            )
        )
        .mappings()
        .all()
    )
    result: list[CommitteeMember] = []
    seen: set[tuple[UUID, str]] = set()
    for row in rows:
        assessment = None
        source_member = None
        try:
            if (row["write_markers"] or {}).get("quality_advisory"):
                value = row["value_json"]
                source_member = CommitteeMember(
                    contact_id=UUID(value["contact_id"]),
                    assessment_claim_id=row["id"],
                    persona_key=value.get("persona_key", "general"),
                    proposed_role=value.get("role", "other"),
                    state="supported",
                    employment_claim_ids=(),
                    outreach_eligible=True,
                    gaps=tuple((row["write_markers"] or {}).get("qualifications", [])),
                )
                contact_id, persona_key = source_member.contact_id, source_member.persona_key
            else:
                assessment = CommitteeAssessment.model_validate(row["value_json"])
                contact_id, persona_key = assessment.contact_id, assessment.persona_key
        except (ValueError, KeyError, TypeError):
            continue
        identity = (contact_id, persona_key)
        if identity in seen:
            continue
        seen.add(identity)
        exists = (
            await conn.execute(
                text(
                    "SELECT id FROM contact_entity WHERE id=:id AND workspace_id=:ws AND "
                    "merged_into IS NULL AND full_name IS NOT NULL AND NOT EXISTS (SELECT 1 "
                    "FROM provider_identity p WHERE p.workspace_id=:ws AND "
                    "p.contact_id=contact_entity.id AND p.erased_at IS NOT NULL)"
                ),
                {"id": contact_id, "ws": workspace_id},
            )
        ).scalar_one_or_none()
        if exists is None:
            continue
        if source_member is not None:
            result.append(source_member)
            continue
        assert assessment is not None
        state = assessment.state
        gaps: list[str] = []
        if not row["applicable"] or row["conclusion"] != "supported":
            state = "excluded" if row["conclusion"] == "invalid" else "needs_verification"
            gaps.append("committee_assessment_not_applicable")
        # The latest person assessment may contradict the earlier source even when a specialist
        # has not yet superseded that source. A conflict blocks a confirmed seat immediately.
        latest = (
            (
                await conn.execute(
                    text(
                        """SELECT c.value_json,q.conclusion,
            ("""
                        + eligible_sql("c")
                        + """) AS applicable FROM claim c
            JOIN claim_quality_current q ON q.claim_id=c.id
            WHERE c.workspace_id=:ws AND c.entity_id=:contact AND c.field_key=:field
              AND c.collected_at > now()-interval '30 days' AND
        c.value_json->>'account_id'=:account AND c.superseded_by IS NULL
            ORDER BY c.collected_at DESC,c.id DESC LIMIT 1"""
                    ),
                    {
                        "ws": workspace_id,
                        "contact": assessment.contact_id,
                        "field": EMPLOYMENT,
                        "account": str(account_id),
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        valid_employment = False
        if latest:
            employment = EmploymentAssessment.model_validate(latest["value_json"])
            valid_employment = bool(
                latest["applicable"]
                and latest["conclusion"] == "supported"
                and employment.affiliation == "supported"
                and employment.time_scope == "current"
            )
            if employment.affiliation == "refuted":
                state = "excluded"
                gaps.append("affiliation_refuted")
        if not valid_employment:
            if state == "supported":
                state = "needs_verification"
            gaps.append("current_affiliation_not_established")
        result.append(
            CommitteeMember(
                contact_id=assessment.contact_id,
                assessment_claim_id=row["id"],
                persona_key=assessment.persona_key,
                proposed_role=assessment.role,
                state=state,
                employment_claim_ids=assessment.employment_claim_ids,
                gaps=tuple(gaps),
                outreach_eligible=bool(
                    state == "supported" and valid_employment and row["outreach_safe"]
                ),
            )
        )
    return tuple(result)
