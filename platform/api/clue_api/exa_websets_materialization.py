"""D4 composition: durable Exa items -> canonical accounts, claims, and field decisions.

This module performs no provider I/O. It reads the immutable artifacts D3 already reconciled and
composes the existing discovery-channel, M2 identity, claim-store, artifact-index, and durable D1
seams in one transaction. D5 alone seals the batch and advances the project.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryCandidateAdmissionState,
    DiscoveryFieldRequirement,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    DiscoveryItemSnapshot,
    DiscoveryItemSnapshotId,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPageResource,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    RunId,
    account_claim,
    canonical_json,
    revalidate_with,
    validate_discovery_plan_policy,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import apply_attributes, traced_step
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_SOURCE_KEY,
    ExaDiscoveryCompanyItem,
    ExaDiscoveryEnrichmentObservation,
    ExaResponseEnrichment,
    ExaWebsetItem,
    ExaWebsetReference,
    normalize_exa_discovery_company_item,
)
from clue_research.claimstore import (
    ALL_WORKSPACES,
    WorkspaceScope,
    claims_for,
    insert_claim,
    load_core_pack,
)
from clue_research.discovery_scoring.discovery import (
    DISCOVERY_ENVELOPE_POLICY_V1,
    REVENUE_BAND_OPTIONS,
    CandidateHypothesis,
    CandidateRecord,
    DiscoveryQuery,
)
from clue_research.discovery_scoring.gate import (
    DISCOVERY_PROVENANCE_FIELD,
    AdmissionStatus,
    admit,
    ensure_discovery_provenance,
    membership_channel,
)
from clue_research.durable import (
    DiscoveryNotFound,
    DiscoveryReplayConflict,
    bind_discovery_artifact_subject,
    get_discovery_candidate_link,
    get_discovery_plan,
    index_account_discovery_artifacts,
    list_discovery_items,
    list_discovery_operations,
    list_discovery_pages,
    lock_discovery_batch_for_materialization,
    normalize_discovery_item,
    put_discovery_candidate_link,
    put_discovery_field_resolution,
    update_discovery_batch_state,
)
from clue_research.identity import (
    ReviewResolution,
    ReviewStatus,
    canonical_member_ids,
    current_value_resolved,
    get_account,
    get_review_decision,
    registrable_domain,
    surviving_id,
)
from clue_research.membership import ensure_project_account
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import StorageBackend, content_address

_ENRICHMENT_COLLECTION = TypeAdapter(tuple[ExaResponseEnrichment, ...])
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ().-]{6,}[0-9]$")
_REVENUE_BANDS = frozenset(REVENUE_BAND_OPTIONS)


class ExaD4Outcome(StrEnum):
    MATERIALIZED = "materialized"
    REPLAYED = "replayed"
    REVIEW_REQUIRED = "review_required"


class ExaD4Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: DiscoveryBatchId
    outcome: ExaD4Outcome
    batch_state: DiscoveryBatchState
    item_count: int
    account_ids: tuple[EntityId, ...]
    excluded_item_count: int
    review_item_count: int
    claim_ids: tuple[ClaimId, ...]
    claims_created: int
    claims_reused: int
    field_resolution_count: int


class ExaWebsetsDurableSnapshotChannel:
    """Existing ``DiscoveryChannel`` over records already paid for and persisted by D3."""

    source_key = EXA_WEBSETS_SOURCE_KEY

    def __init__(self, records: Sequence[CandidateRecord]) -> None:
        self._records = tuple(records)

    async def discover(self, query: DiscoveryQuery) -> list[CandidateRecord]:
        if query.channel != self.source_key:
            raise ValueError("durable Exa snapshot channel received another channel's query")
        return list(self._records[: query.limit])


class _PreparedItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    snapshot: DiscoveryItemSnapshot
    company: ExaDiscoveryCompanyItem
    record: CandidateRecord
    #: The exact retained item bytes every claim of this item cites and is cut from.
    retained: bytes


class _ItemMaterialization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: DiscoveryItemSnapshotId
    survivor_id: EntityId
    claim_ids_by_field: dict[str, tuple[ClaimId, ...]]
    attempted_fields: frozenset[str]
    missing_fields: frozenset[str]
    enrichment_missing_fields: frozenset[str]
    observed_at: datetime


def _json_number(value: object) -> int | float:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Exa financial value {value!r} is not numeric") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("Exa financial values must be finite and non-negative")
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _reference_payload(reference: ExaWebsetReference) -> dict[str, JsonValue]:
    return {
        "url": reference.url,
        "title": reference.title,
        "snippet": reference.snippet,
    }


def _candidate_evidence(company: ExaDiscoveryCompanyItem) -> dict[str, JsonValue]:
    return {
        "provider_item_id": company.provider_item_id,
        "provider_webset_id": company.provider_webset_id,
        "provider_source_id": company.provider_source_id,
        "evaluations": [
            {
                "criterion": evaluation.criterion,
                "satisfied": evaluation.satisfied,
                "reasoning": evaluation.reasoning,
                "references": [
                    _reference_payload(reference) for reference in evaluation.references
                ],
            }
            for evaluation in company.evaluations
        ],
    }


class ExaRetainedSpanError(RuntimeError):
    """An Exa evidence span could not be cut from the exact retained item artifact.

    Fail-closed by construction: every ``exa_websets`` claim's ``evidence_span`` must be a literal
    substring of the immutable bytes it cites, because that is precisely what the engine's
    anti-fabrication guard re-checks before a projection may reach an agent
    (``entity_research_tools._json_contains_text``). A span this module cannot cut verbatim is one
    it must not write.
    """


class _RetainedItem:
    """The retained item artifact, plus the ability to cut verbatim spans out of it.

    Every retained webset item is stored as canonical JSON (``sort_keys=True``, ``(",", ":")``
    separators) — the D3 page ingest and the targeted-enrichment reconciler both serialize it that
    way — so re-rendering any object it contains reproduces the exact retained bytes, and any
    contiguous slice of that rendering is a literal substring of the artifact. Spans are therefore
    *cut from the evidence*, never composed about it: a description like
    ``Exa company properties company.employees: 819`` reads well and is unfindable in the bytes,
    which is exactly the shape the guard exists to refuse.
    """

    def __init__(self, retained: bytes) -> None:
        self._text = retained.decode("utf-8")
        payload = json.loads(self._text)
        if not isinstance(payload, dict):
            raise ExaRetainedSpanError("retained Exa item artifact is not a JSON object")
        self._payload: Mapping[str, JsonValue] = payload

    def provider_member_span(self, provider_field: str) -> str:
        """The slice covering the retained member(s) named by ``provider_field``.

        ``provider_field`` is the base-field provenance label (``company.employees``,
        ``properties.url``, ``company.financials.revenueAnnual``) and may name alternatives with
        ``|`` when one platform value is derived from more than one retained member
        (``company.headquarters|company.location``). Alternatives must share one container, so the
        cut stays a single contiguous run of retained bytes rather than a fabricated join.
        """

        paths = tuple(_item_path(alternative) for alternative in provider_field.split("|"))
        parents = {path[:-1] for path in paths}
        if len(parents) != 1:
            raise ExaRetainedSpanError(
                f"Exa provider field {provider_field!r} spans more than one retained container"
            )
        container = self._container(next(iter(parents)), provider_field)
        keys = tuple(path[-1] for path in paths if path[-1] in container)
        if not keys:
            raise ExaRetainedSpanError(
                f"retained Exa item has no member for provider field {provider_field!r}"
            )
        return self._cut(container, keys, provider_field)[:8000]

    def enrichment_span(self, enrichment_id: str) -> str:
        """The retained enrichment result — reasoning, references and value, exactly as stored."""

        entries = self._payload.get("enrichments")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("enrichmentId") == enrichment_id:
                    span = canonical_json(cast(JsonValue, entry))
                    if span not in self._text:
                        raise ExaRetainedSpanError(
                            f"retained Exa enrichment {enrichment_id!r} is not stored canonically"
                        )
                    return span[:8000]
        raise ExaRetainedSpanError(f"retained Exa item has no enrichment {enrichment_id!r}")

    def evaluations_span(self) -> str:
        """The retained match evaluations — the grounding behind admitting this candidate."""

        return self._cut(self._payload, ("evaluations",), "evaluations")[:8000]

    def _container(self, path: Sequence[str], provider_field: str) -> Mapping[str, JsonValue]:
        node: JsonValue = cast(JsonValue, self._payload)
        for part in path:
            if not isinstance(node, dict) or part not in node:
                raise ExaRetainedSpanError(
                    f"retained Exa item has no container for provider field {provider_field!r}"
                )
            node = node[part]
        if not isinstance(node, dict):
            raise ExaRetainedSpanError(
                f"retained Exa container for {provider_field!r} is not a JSON object"
            )
        return node

    def _cut(
        self,
        container: Mapping[str, JsonValue],
        keys: Sequence[str],
        provider_field: str,
    ) -> str:
        ordered = sorted(container)
        members = [f"{canonical_json(key)}:{canonical_json(container[key])}" for key in ordered]
        rendered = "{" + ",".join(members) + "}"
        if rendered not in self._text:
            raise ExaRetainedSpanError(
                f"retained Exa container for {provider_field!r} is not stored canonically"
            )
        bounds: dict[str, tuple[int, int]] = {}
        cursor = 1
        for key, member in zip(ordered, members, strict=True):
            bounds[key] = (cursor, cursor + len(member))
            cursor += len(member) + 1
        return rendered[min(bounds[key][0] for key in keys) : max(bounds[key][1] for key in keys)]


def _item_path(provider_field: str) -> tuple[str, ...]:
    """Translate a base-field provenance label into its path inside the retained item."""

    parts = tuple(part for part in provider_field.split(".") if part)
    if parts[:1] == ("company",):
        return ("properties", "company", *parts[1:])
    if parts[:1] == ("properties",) and len(parts) > 1:
        return parts
    raise ExaRetainedSpanError(f"Exa provider field {provider_field!r} names no retained member")


def _matched_signal(company: ExaDiscoveryCompanyItem) -> str:
    states = ", ".join(
        f"{evaluation.criterion}={evaluation.satisfied}" for evaluation in company.evaluations
    )
    return states[:2000] or f"Exa Websets company search {company.provider_source_id}"


def _candidate_record(
    snapshot: DiscoveryItemSnapshot,
    company: ExaDiscoveryCompanyItem,
    retained: _RetainedItem,
) -> CandidateRecord:
    domain = registrable_domain(company.company_url)
    return CandidateRecord(
        # A provider item id can recur across searches in the same batch. The snapshot id is the
        # batch-local lossless handle; provider ids remain preserved in discovery_evidence.
        source_record_ref=str(snapshot.item_snapshot_id),
        source_url=company.company_url,
        raw_name=company.company_name,
        candidate_domain=domain,
        candidate_geo=_headquarters_value(company),
        matched_signal=_matched_signal(company),
        confidence=0.9,
        cost_cents=Decimal(0),
        artifact_key=snapshot.raw_artifact_key,
        evidence_span=retained.evaluations_span(),
        discovery_evidence=_candidate_evidence(company),
        observed_at=company.observed_at,
    )


def _headquarters_value(company: ExaDiscoveryCompanyItem) -> dict[str, JsonValue] | None:
    raw_hq = company.base_fields.get("headquarters")
    location = company.base_fields.get("location")
    hq = raw_hq if isinstance(raw_hq, dict) else {}
    raw = str(location).strip() if isinstance(location, str) and location.strip() else ""
    if not raw:
        raw = ", ".join(
            str(hq[key]).strip()
            for key in ("address", "city", "state", "postalCode", "country")
            if hq.get(key) is not None and str(hq[key]).strip()
        )
    if not raw:
        return None
    result: dict[str, JsonValue] = {"raw": raw}
    for provider_key, field_key in (
        ("city", "city"),
        ("state", "region"),
        ("country", "country"),
        ("countryCode", "country_code"),
    ):
        value = hq.get(provider_key)
        if value is not None and str(value).strip():
            result[field_key] = str(value).strip()
    return result


def _base_field_values(company: ExaDiscoveryCompanyItem) -> dict[str, JsonValue]:
    fields = company.base_fields
    domain = registrable_domain(company.company_url)
    values: dict[str, JsonValue] = {
        "core.account_name": company.company_name,
    }
    if domain:
        values["core.primary_domain"] = domain
    industry = fields.get("industry")
    if isinstance(industry, str) and industry.strip():
        values["core.industry"] = industry.strip()
    employees = fields.get("employees")
    if isinstance(employees, int) and not isinstance(employees, bool):
        values["core.employee_count"] = employees
    headquarters = _headquarters_value(company)
    if headquarters is not None:
        values["core.hq_location"] = headquarters
    about = fields.get("about")
    if isinstance(about, str) and about.strip():
        values["core.company_about"] = about.strip()

    revenue = fields.get("revenueAnnual")
    if revenue is not None:
        values["core.annual_revenue"] = {
            "amount": _json_number(revenue),
            "currency": "USD",
            "as_of": company.observed_at.date().isoformat(),
            "estimate_kind": "provider_estimate",
            "provider_field": "company.financials.revenueAnnual",
        }
    total_funding = fields.get("fundingTotal")
    if total_funding is not None:
        values["account.total_funding"] = {
            "amount_usd": _json_number(total_funding),
            "estimate_kind": "provider_estimate",
        }
    latest = fields.get("fundingLatestRound")
    if isinstance(latest, dict) and latest.get("amount") is not None:
        recent: dict[str, JsonValue] = {"amount_usd": _json_number(latest["amount"])}
        if latest.get("name") is not None and str(latest["name"]).strip():
            recent["round"] = str(latest["name"]).strip()
        if latest.get("date") is not None and str(latest["date"]).strip():
            recent["date"] = str(latest["date"]).strip()
        recent["estimate_kind"] = "provider_estimate"
        values["account.recent_funding"] = recent
    return values


_BASE_ATTEMPTS: dict[str, tuple[str, ...]] = {
    "core.industry": ("industry",),
    "core.employee_count": ("employees",),
    "core.hq_location": ("headquarters", "location"),
    "core.annual_revenue": ("revenueAnnual",),
}


def _base_attempts(company: ExaDiscoveryCompanyItem) -> tuple[set[str], set[str]]:
    attempted = set(_BASE_ATTEMPTS)
    missing = {field_key for field_key in attempted if field_key not in _base_field_values(company)}
    return attempted, missing


def _canonical_enrichment_field(field_key: str) -> str:
    aliases = {"core.annual_revenue_usd": "core.annual_revenue"}
    return aliases.get(field_key, field_key)


def _one_result(observation: ExaDiscoveryEnrichmentObservation) -> str:
    if observation.result is None:
        raise ValueError("missing enrichment has no value")
    if len(observation.result) != 1:
        raise ValueError(
            f"D4 enrichment {observation.enrichment_id!r} must contain exactly one value"
        )
    return observation.result[0].strip()


def exa_enrichment_value(
    company: ExaDiscoveryCompanyItem,
    observation: ExaDiscoveryEnrichmentObservation,
) -> tuple[str, JsonValue] | None:
    field_key = _canonical_enrichment_field(observation.field_key)
    if observation.result is None:
        return None
    raw = _one_result(observation)
    if field_key == "core.company_linkedin_url":
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme not in {"http", "https"} or host != "linkedin.com":
            raise ValueError("LinkedIn enrichment is not an absolute linkedin.com URL")
        return field_key, raw
    if field_key == "core.annual_revenue":
        return field_key, {
            "amount": _json_number(raw),
            "currency": "USD",
            "as_of": company.observed_at.date().isoformat(),
            "estimate_kind": "provider_estimate",
            "provider_field": observation.field_key,
        }
    if field_key == "core.revenue_band":
        if raw not in _REVENUE_BANDS:
            raise ValueError("revenue-band enrichment is outside the closed vocabulary")
        return field_key, raw
    if field_key == "core.company_email":
        if _EMAIL.fullmatch(raw) is None:
            raise ValueError("company email enrichment is invalid")
        return field_key, raw
    if field_key == "core.company_phone":
        if _PHONE.fullmatch(raw) is None:
            raise ValueError("company phone enrichment is invalid")
        return field_key, raw
    raise ValueError(f"D4 has no approved mapping for enrichment field {observation.field_key!r}")


def _best_reference_url(
    company: ExaDiscoveryCompanyItem,
    references: Sequence[ExaWebsetReference],
) -> str:
    return references[0].url if references else company.company_url


def _claim_tier(
    company: ExaDiscoveryCompanyItem,
    field_key: str,
    references: Sequence[ExaWebsetReference],
) -> int:
    if not references:
        return (
            2
            if field_key
            in {
                "core.account_name",
                "core.primary_domain",
                "core.company_about",
                "core.hq_location",
            }
            else 3
        )
    account_domain = registrable_domain(company.company_url)
    for reference in references:
        host = (urlsplit(reference.url).hostname or "").lower().removeprefix("www.")
        if (account_domain and registrable_domain(reference.url) == account_domain) or (
            field_key == "core.company_linkedin_url" and host == "linkedin.com"
        ):
            return 2
    return 3


async def _equivalent_claim(
    conn: AsyncConnection,
    *,
    entity_ids: Sequence[EntityId],
    field_key: str,
    artifact_key: str,
    value: JsonValue,
) -> ClaimId | None:
    target = canonical_json(value)
    matches: list[ClaimId] = []
    for entity_id in entity_ids:
        for claim in await claims_for(conn, entity_id, field_key, scope=ALL_WORKSPACES):
            if (
                claim.source_key == EXA_WEBSETS_SOURCE_KEY
                and claim.artifact_key == artifact_key
                and canonical_json(claim.value_json) == target
            ):
                matches.append(claim.id)
    if len(matches) > 1:
        raise DiscoveryReplayConflict(
            f"D4 item artifact {artifact_key!r} has duplicate equivalent {field_key!r} claims"
        )
    if matches:
        return matches[0]
    return None


async def _item_provenance_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: EntityId,
    artifact_key: str,
) -> ClaimId:
    members = await canonical_member_ids(
        conn, entity_id, EntityType.ACCOUNT, workspace_id=workspace_id
    )
    matches: list[ClaimId] = []
    for member_id in members:
        matches.extend(
            claim.id
            for claim in await claims_for(
                conn, member_id, DISCOVERY_PROVENANCE_FIELD, scope=ALL_WORKSPACES
            )
            if claim.source_key == EXA_WEBSETS_SOURCE_KEY and claim.artifact_key == artifact_key
        )
    if len(matches) != 1:
        raise DiscoveryReplayConflict(
            f"D4 item artifact {artifact_key!r} has {len(matches)} discovery-provenance claims"
        )
    return matches[0]


async def ensure_exa_company_field_claim(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    run_id: RunId,
    artifact_key: str,
    retained_item: bytes,
    company: ExaDiscoveryCompanyItem,
    member_ids: Sequence[EntityId],
    field_key: str,
    value: JsonValue,
    provider_field: str,
    enrichment_id: str | None = None,
    references: Sequence[ExaWebsetReference] = (),
    reasoning: str | None = None,
    research_mode: ResearchMode = ResearchMode.ACCOUNT_DISCOVERY,
) -> tuple[ClaimId, bool]:
    if not artifact_key.endswith(content_address(retained_item)):
        raise ExaRetainedSpanError("retained Exa item bytes are not the cited artifact")
    existing = await _equivalent_claim(
        conn,
        entity_ids=member_ids,
        field_key=field_key,
        artifact_key=artifact_key,
        value=value,
    )
    if existing is not None:
        return existing, False
    claim = account_claim(
        entity_id=entity_id,
        field_key=field_key,
        value_json=value,
        source_tier=_claim_tier(company, field_key, references),
        extraction_method=ExtractionMethod.API,
        confidence=0.85 if references else 0.75,
        run_id=run_id,
        research_mode=research_mode,
        source_url=_best_reference_url(company, references),
        # The span is cut out of the retained bytes, never composed about them: the engine
        # re-reads this artifact and refuses any projection whose span it cannot find there.
        evidence_span=(
            _RetainedItem(retained_item).enrichment_span(enrichment_id)
            if enrichment_id is not None
            else _RetainedItem(retained_item).provider_member_span(provider_field)
        ),
        observed_at=company.observed_at,
        cost_cents=Decimal(0),
    )
    claim = revalidate_with(
        claim,
        source_key=EXA_WEBSETS_SOURCE_KEY,
        artifact_key=artifact_key,
    )
    return await insert_claim(conn, claim), True


async def _materialize_item_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    survivor_id: EntityId,
    run_id: RunId,
    prepared: _PreparedItem,
) -> tuple[dict[str, tuple[ClaimId, ...]], set[str], set[str], set[str], int, int]:
    created = 0
    reused = 0
    by_field: dict[str, list[ClaimId]] = defaultdict(list)
    attempted, missing = _base_attempts(prepared.company)
    enrichment_missing: set[str] = set()
    provider_fields = {
        "core.account_name": "company.name",
        "core.primary_domain": "properties.url",
        "core.industry": "company.industry",
        "core.employee_count": "company.employees",
        "core.hq_location": "company.headquarters|company.location",
        "core.company_about": "company.about",
        "core.annual_revenue": "company.financials.revenueAnnual",
        "account.total_funding": "company.financials.fundingTotal",
        "account.recent_funding": "company.financials.fundingLatestRound",
    }
    member_ids = await canonical_member_ids(
        conn, survivor_id, EntityType.ACCOUNT, workspace_id=workspace_id
    )
    for field_key, value in _base_field_values(prepared.company).items():
        claim_id, was_created = await ensure_exa_company_field_claim(
            conn,
            entity_id=survivor_id,
            run_id=run_id,
            artifact_key=prepared.snapshot.raw_artifact_key,
            retained_item=prepared.retained,
            company=prepared.company,
            member_ids=member_ids,
            field_key=field_key,
            value=value,
            provider_field=provider_fields[field_key],
        )
        by_field[field_key].append(claim_id)
        created += int(was_created)
        reused += int(not was_created)

    for observation in prepared.company.enrichments:
        field_key = _canonical_enrichment_field(observation.field_key)
        attempted.add(field_key)
        mapped = exa_enrichment_value(prepared.company, observation)
        if mapped is None:
            missing.add(field_key)
            enrichment_missing.add(field_key)
            continue
        mapped_field, value = mapped
        missing.discard(mapped_field)
        claim_id, was_created = await ensure_exa_company_field_claim(
            conn,
            entity_id=survivor_id,
            run_id=run_id,
            artifact_key=prepared.snapshot.raw_artifact_key,
            retained_item=prepared.retained,
            company=prepared.company,
            member_ids=member_ids,
            field_key=mapped_field,
            value=value,
            provider_field=observation.field_key,
            enrichment_id=observation.enrichment_id,
            references=observation.references,
            reasoning=observation.reasoning,
        )
        by_field[mapped_field].append(claim_id)
        created += int(was_created)
        reused += int(not was_created)
    return (
        {key: tuple(value) for key, value in by_field.items()},
        attempted,
        missing,
        enrichment_missing,
        created,
        reused,
    )


def _logical_attempts(logical_key: str, configured: tuple[str, ...]) -> tuple[str, ...]:
    if logical_key == "identity.account_name":
        return ("core.account_name",)
    return configured


async def _resolve_survivor_fields(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
    survivor_id: EntityId,
    items: Sequence[_ItemMaterialization],
) -> int:
    account = await get_account(conn, survivor_id)
    if account is None or account.workspace_id != workspace_id:
        raise DiscoveryNotFound(f"D4 survivor account {survivor_id} in workspace {workspace_id}")
    item_ids = tuple(sorted((item.snapshot_id for item in items), key=str))
    observed_at = max(item.observed_at for item in items)
    local_claims: dict[str, set[ClaimId]] = defaultdict(set)
    attempted: set[str] = set()
    missing: set[str] = set()
    enrichment_missing: set[str] = set()
    for item in items:
        attempted.update(item.attempted_fields)
        missing.update(item.missing_fields)
        enrichment_missing.update(item.enrichment_missing_fields)
        for field_key, item_claim_ids in item.claim_ids_by_field.items():
            local_claims[field_key].update(item_claim_ids)

    count = 0
    scope = WorkspaceScope.for_workspace(workspace_id)
    for envelope in DISCOVERY_ENVELOPE_POLICY_V1.fields:
        logical_key = str(envelope.logical_field_key)
        attempts = _logical_attempts(
            logical_key, tuple(str(value) for value in envelope.field_attempt_order)
        )
        resolution_claim_ids: set[ClaimId] = set()
        winner: ClaimId | None = None
        conflict = False
        for field_key in attempts:
            resolution_claim_ids.update(local_claims.get(field_key, set()))
            current = await current_value_resolved(
                conn,
                survivor_id,
                field_key,
                scope=scope,
                entity_type=EntityType.ACCOUNT,
            )
            if current is None:
                continue
            resolution_claim_ids.add(current.provenance.claim_id)
            resolution_claim_ids.update(current.conflicting_claim_ids)
            if current.conflict:
                conflict = True
                continue
            if winner is None:
                winner = current.provenance.claim_id

        if logical_key == "identity.account_name" and not account.canonical_name.strip():
            raise ValueError("canonical account has no name")
        if logical_key == "identity.primary_domain" and not account.primary_domain:
            raise ValueError("canonical account has no primary domain")

        ordered_claims = tuple(sorted(resolution_claim_ids, key=str))
        if conflict:
            state = DiscoveryFieldResolutionState.CONFLICT
            reason = "authoritative_claims_disagree"
            winner = None
        elif winner is not None:
            state = DiscoveryFieldResolutionState.RESOLVED
            reason = None
        elif envelope.requirement is DiscoveryFieldRequirement.HARD_IDENTITY:
            raise ValueError(f"hard identity {logical_key!r} has no evidence claim")
        elif any(field_key in enrichment_missing for field_key in attempts):
            if envelope.requirement is DiscoveryFieldRequirement.REQUIRED_ATTEMPT:
                state = DiscoveryFieldResolutionState.PENDING
                reason = None
            else:
                state = DiscoveryFieldResolutionState.CONFIRMED_MISSING
                reason = "exa_terminal_attempt_returned_null"
        elif any(field_key in missing or field_key in attempted for field_key in attempts):
            if envelope.requirement is DiscoveryFieldRequirement.REQUIRED_ATTEMPT:
                state = DiscoveryFieldResolutionState.PENDING
                reason = None
            else:
                state = DiscoveryFieldResolutionState.CONFIRMED_MISSING
                reason = "exa_terminal_base_property_absent"
        elif envelope.requirement is DiscoveryFieldRequirement.OPTIONAL_ATTEMPT:
            continue
        else:
            state = DiscoveryFieldResolutionState.FAILED_TERMINAL
            reason = "required_attempt_not_planned"
        await put_discovery_field_resolution(
            conn,
            workspace_id=workspace_id,
            resolution=DiscoveryFieldResolution(
                batch_id=batch_id,
                account_entity_id=survivor_id,
                logical_field_key=envelope.logical_field_key,
                state=state,
                claim_ids=ordered_claims,
                winning_claim_id=winner,
                source_item_ids=item_ids,
                reason_code=reason,
                updated_at=observed_at,
            ),
        )
        count += 1
    return count


class ExaWebsetsD4Materializer:
    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def _prepare_operation(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        operation_id: DiscoveryOperationId,
    ) -> tuple[_PreparedItem, ...]:
        pages = await list_discovery_pages(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
        definition_pages = [
            page
            for page in pages
            if page.receipt.resource_kind is DiscoveryPageResource.ENRICHMENTS
        ]
        if len(definition_pages) != 1:
            raise DiscoveryReplayConflict(
                f"D4 operation {operation_id} requires one terminal enrichment page"
            )
        definitions_raw = await self._storage.get(definition_pages[0].receipt.payload_artifact_key)
        if content_address(definitions_raw) != definition_pages[0].receipt.payload_sha256:
            raise DiscoveryReplayConflict("D4 enrichment-definition artifact hash mismatch")
        definitions = _ENRICHMENT_COLLECTION.validate_json(definitions_raw)
        items = await list_discovery_items(
            conn, workspace_id=workspace_id, operation_id=operation_id
        )
        prepared: list[_PreparedItem] = []
        for snapshot in items:
            raw = await self._storage.get(snapshot.raw_artifact_key)
            if content_address(raw) != snapshot.item_sha256:
                raise DiscoveryReplayConflict("D4 raw item artifact hash mismatch")
            provider_item = ExaWebsetItem.model_validate_json(raw)
            if provider_item.id != snapshot.provider_item_id:
                raise DiscoveryReplayConflict("D4 raw item id differs from its durable snapshot")
            company = normalize_exa_discovery_company_item(provider_item, definitions)
            retained = _RetainedItem(raw)
            prepared.append(
                _PreparedItem(
                    snapshot=snapshot,
                    company=company,
                    record=_candidate_record(snapshot, company, retained),
                    retained=raw,
                )
            )
        return tuple(prepared)

    async def materialize(
        self,
        *,
        workspace_id: str,
        batch_id: DiscoveryBatchId,
    ) -> ExaD4Result:
        with traced_step(
            "discovery.exa_websets.materialize",
            workspace_id=workspace_id,
            source_key=EXA_WEBSETS_SOURCE_KEY,
            batch_id=str(batch_id),
        ) as span:
            async with self._conn_factory() as conn:
                batch = await lock_discovery_batch_for_materialization(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                replay = batch.state is DiscoveryBatchState.SEAL_PENDING
                plan_row = await get_discovery_plan(
                    conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
                )
                if plan_row is None:
                    raise DiscoveryNotFound(f"D4 discovery plan {batch.discovery_plan_id}")
                validate_discovery_plan_policy(plan_row.plan, DISCOVERY_ENVELOPE_POLICY_V1)
                await load_core_pack(conn)
                # Boot order: a source manifest's ``yields`` validate against the field
                # registry, and the tier-3 ``exa_search`` seed yields ``client.*`` keys — so
                # the client-knowledge pack must be loaded before the manifests are seeded.
                await load_client_knowledge_pack(conn)
                await seed_source_manifests(conn)
                operations = await list_discovery_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                if len(operations) != len(plan_row.plan.searches):
                    raise DiscoveryReplayConflict("D4 requires every planned operation")
                prepared: list[_PreparedItem] = []
                for operation in operations:
                    if operation.state not in {
                        DiscoveryOperationState.SUCCEEDED,
                        DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
                    }:
                        raise DiscoveryReplayConflict(
                            f"D4 operation {operation.operation_id} is not terminal"
                        )
                    if (
                        operation.final_reconciled_at is None
                        or operation.pagination_exhausted_at is None
                    ):
                        raise DiscoveryReplayConflict(
                            f"D4 operation {operation.operation_id} lacks final D3 reconciliation"
                        )
                    if operation.state is DiscoveryOperationState.SUCCEEDED:
                        if operation.source_key != EXA_WEBSETS_SOURCE_KEY:
                            raise DiscoveryReplayConflict(
                                "Exa D4 materializer received a non-Exa operation"
                            )
                        prepared.extend(
                            await self._prepare_operation(
                                conn,
                                workspace_id=workspace_id,
                                operation_id=operation.operation_id,
                            )
                        )

                channel = ExaWebsetsDurableSnapshotChannel([item.record for item in prepared])
                discovered = await channel.discover(
                    DiscoveryQuery(
                        channel=EXA_WEBSETS_SOURCE_KEY,
                        limit=max(1, len(prepared)),
                    )
                )
                by_record = {item.record.source_record_ref: item for item in prepared}
                run_id = RunId(batch.project_run_id)
                item_results: list[_ItemMaterialization] = []
                excluded = 0
                reviews = 0
                created = 0
                reused = 0
                all_claim_ids: set[ClaimId] = set()

                for record in discovered:
                    item = by_record[record.source_record_ref]
                    domain = registrable_domain(record.candidate_domain or record.source_url or "")
                    if not record.raw_name or not record.raw_name.strip() or not domain:
                        await put_discovery_candidate_link(
                            conn,
                            workspace_id=workspace_id,
                            batch_id=batch_id,
                            item_snapshot_id=item.snapshot.item_snapshot_id,
                            admission_status=DiscoveryCandidateAdmissionState.EXCLUDED,
                            raw_name=record.raw_name,
                            candidate_domain=domain,
                            source_url=record.source_url,
                            disposition_reason="missing_required_name_or_registrable_domain",
                        )
                        await normalize_discovery_item(
                            conn,
                            workspace_id=workspace_id,
                            item_snapshot_id=item.snapshot.item_snapshot_id,
                            normalized_at=item.company.observed_at,
                        )
                        excluded += 1
                        continue

                    existing_link = await get_discovery_candidate_link(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=batch_id,
                        item_snapshot_id=item.snapshot.item_snapshot_id,
                    )
                    if existing_link is not None and existing_link.admission_status in {
                        DiscoveryCandidateAdmissionState.ADMITTED,
                        DiscoveryCandidateAdmissionState.MERGED,
                    }:
                        survivor = existing_link.survivor_entity_id
                        assert survivor is not None
                    elif existing_link is not None and existing_link.admission_status is (
                        DiscoveryCandidateAdmissionState.EXCLUDED
                    ):
                        excluded += 1
                        continue
                    elif existing_link is not None and existing_link.admission_status is (
                        DiscoveryCandidateAdmissionState.REVIEW_REQUIRED
                    ):
                        if existing_link.review_task_id is None:
                            raise RuntimeError("review-required candidate has no task id")
                        decision = await get_review_decision(conn, existing_link.review_task_id)
                        if decision.workspace_id != workspace_id:
                            raise DiscoveryReplayConflict(
                                "identity review task belongs to another workspace"
                            )
                        if decision.status is ReviewStatus.OPEN:
                            reviews += 1
                            continue
                        if decision.status is ReviewStatus.DISMISSED or (
                            decision.status is ReviewStatus.RESOLVED
                            and decision.resolution is ReviewResolution.NOT_A_MATCH
                        ):
                            await put_discovery_candidate_link(
                                conn,
                                workspace_id=workspace_id,
                                batch_id=batch_id,
                                item_snapshot_id=item.snapshot.item_snapshot_id,
                                admission_status=DiscoveryCandidateAdmissionState.EXCLUDED,
                                raw_name=record.raw_name,
                                candidate_domain=domain,
                                source_url=record.source_url,
                                disposition_reason=(
                                    "identity_review_dismissed"
                                    if decision.status is ReviewStatus.DISMISSED
                                    else "identity_review_not_a_match"
                                ),
                                review_task_id=existing_link.review_task_id,
                            )
                            excluded += 1
                            continue
                        if (
                            decision.status is not ReviewStatus.RESOLVED
                            or decision.resolution
                            not in {
                                ReviewResolution.MERGE_INTO,
                                ReviewResolution.CREATE_NEW_ENTITY,
                            }
                            or decision.survivor_id is None
                        ):
                            raise DiscoveryReplayConflict(
                                "identity review has no supported terminal admission decision"
                            )
                        survivor = decision.survivor_id
                        existing_link = await put_discovery_candidate_link(
                            conn,
                            workspace_id=workspace_id,
                            batch_id=batch_id,
                            item_snapshot_id=item.snapshot.item_snapshot_id,
                            admission_status=DiscoveryCandidateAdmissionState.ADMITTED,
                            raw_name=record.raw_name,
                            candidate_domain=domain,
                            source_url=record.source_url,
                            account_entity_id=survivor,
                            survivor_entity_id=survivor,
                            review_task_id=existing_link.review_task_id,
                        )
                        await ensure_discovery_provenance(
                            conn,
                            CandidateHypothesis.from_record(
                                record, matched_channel=EXA_WEBSETS_SOURCE_KEY
                            ),
                            survivor,
                            run_id,
                        )
                    else:
                        admission = await admit(
                            conn,
                            CandidateHypothesis.from_record(
                                record, matched_channel=EXA_WEBSETS_SOURCE_KEY
                            ),
                            run_id,
                            workspace_id=workspace_id,
                            project_id=batch.project_id,
                        )
                        if admission.status is AdmissionStatus.REJECTED:
                            await put_discovery_candidate_link(
                                conn,
                                workspace_id=workspace_id,
                                batch_id=batch_id,
                                item_snapshot_id=item.snapshot.item_snapshot_id,
                                admission_status=DiscoveryCandidateAdmissionState.EXCLUDED,
                                raw_name=record.raw_name,
                                candidate_domain=domain,
                                source_url=record.source_url,
                                disposition_reason=(
                                    admission.reason or "identity_admission_rejected"
                                ),
                            )
                            await normalize_discovery_item(
                                conn,
                                workspace_id=workspace_id,
                                item_snapshot_id=item.snapshot.item_snapshot_id,
                                normalized_at=item.company.observed_at,
                            )
                            excluded += 1
                            continue
                        if admission.status is AdmissionStatus.NEEDS_REVIEW:
                            if admission.review_task_id is None:
                                raise RuntimeError("identity review admission has no task id")
                            await put_discovery_candidate_link(
                                conn,
                                workspace_id=workspace_id,
                                batch_id=batch_id,
                                item_snapshot_id=item.snapshot.item_snapshot_id,
                                admission_status=DiscoveryCandidateAdmissionState.REVIEW_REQUIRED,
                                raw_name=record.raw_name,
                                candidate_domain=domain,
                                source_url=record.source_url,
                                review_task_id=admission.review_task_id,
                            )
                            await normalize_discovery_item(
                                conn,
                                workspace_id=workspace_id,
                                item_snapshot_id=item.snapshot.item_snapshot_id,
                                normalized_at=item.company.observed_at,
                            )
                            reviews += 1
                            continue
                        survivor = admission.account_entity_id
                        if survivor is None:
                            raise RuntimeError("admitted identity has no account id")
                        existing_link = await put_discovery_candidate_link(
                            conn,
                            workspace_id=workspace_id,
                            batch_id=batch_id,
                            item_snapshot_id=item.snapshot.item_snapshot_id,
                            admission_status=DiscoveryCandidateAdmissionState.ADMITTED,
                            raw_name=record.raw_name,
                            candidate_domain=domain,
                            source_url=record.source_url,
                            account_entity_id=survivor,
                            survivor_entity_id=survivor,
                        )

                    current_survivor = await surviving_id(conn, survivor, EntityType.ACCOUNT)
                    if current_survivor != survivor:
                        original_id = (
                            existing_link.account_entity_id
                            if existing_link is not None
                            and existing_link.account_entity_id is not None
                            else survivor
                        )
                        existing_link = await put_discovery_candidate_link(
                            conn,
                            workspace_id=workspace_id,
                            batch_id=batch_id,
                            item_snapshot_id=item.snapshot.item_snapshot_id,
                            admission_status=DiscoveryCandidateAdmissionState.MERGED,
                            raw_name=record.raw_name,
                            candidate_domain=domain,
                            source_url=record.source_url,
                            account_entity_id=original_id,
                            survivor_entity_id=current_survivor,
                            disposition_reason="identity_survivor_redirect",
                            review_task_id=(
                                existing_link.review_task_id if existing_link is not None else None
                            ),
                        )
                    survivor = current_survivor
                    survivor_account = await get_account(conn, survivor)
                    if survivor_account is None or survivor_account.workspace_id != workspace_id:
                        raise DiscoveryReplayConflict(
                            "D4 candidate survivor belongs to another workspace"
                        )

                    # FI-2 P1 (spec §2): membership follows the *current* survivor, on every branch
                    # that reaches here — the fresh admit (which already recorded it against the id
                    # it resolved), a replay over an existing ADMITTED/MERGED link, an identity
                    # review resolved to an entity, and a link rewritten to MERGED by a later merge.
                    # Idempotent and first-add-wins, so re-materialising a sealed batch never
                    # rewrites the original add, and a survivor that inherited the loser's
                    # membership (``repoint_project_accounts``) keeps its own ``added_at``.
                    await ensure_project_account(
                        conn,
                        workspace_id=workspace_id,
                        project_id=batch.project_id,
                        account_entity_id=survivor,
                        added_via=membership_channel(EXA_WEBSETS_SOURCE_KEY),
                    )

                    (
                        claims_by_field,
                        attempted,
                        missing,
                        enrichment_missing,
                        item_created,
                        item_reused,
                    ) = await _materialize_item_claims(
                        conn,
                        workspace_id=workspace_id,
                        survivor_id=survivor,
                        run_id=run_id,
                        prepared=item,
                    )
                    all_claim_ids.add(
                        await _item_provenance_claim(
                            conn,
                            workspace_id=workspace_id,
                            entity_id=survivor,
                            artifact_key=item.snapshot.raw_artifact_key,
                        )
                    )
                    for claim_ids in claims_by_field.values():
                        all_claim_ids.update(claim_ids)
                    created += item_created
                    reused += item_reused
                    await bind_discovery_artifact_subject(
                        conn,
                        workspace_id=workspace_id,
                        artifact_key_value=item.snapshot.raw_artifact_key,
                        subject_kind="account",
                        subject_entity_id=survivor,
                        reference_kind="item",
                        reference_id=str(item.snapshot.item_snapshot_id),
                    )
                    await index_account_discovery_artifacts(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=batch_id,
                        account_entity_id=survivor,
                    )
                    await normalize_discovery_item(
                        conn,
                        workspace_id=workspace_id,
                        item_snapshot_id=item.snapshot.item_snapshot_id,
                        normalized_at=item.company.observed_at,
                    )
                    item_results.append(
                        _ItemMaterialization(
                            snapshot_id=item.snapshot.item_snapshot_id,
                            survivor_id=survivor,
                            claim_ids_by_field=claims_by_field,
                            attempted_fields=frozenset(attempted),
                            missing_fields=frozenset(missing),
                            enrichment_missing_fields=frozenset(enrichment_missing),
                            observed_at=item.company.observed_at,
                        )
                    )

                grouped: dict[EntityId, list[_ItemMaterialization]] = defaultdict(list)
                for materialized_item in item_results:
                    grouped[materialized_item.survivor_id].append(materialized_item)
                resolution_count = 0
                for survivor, survivor_items in grouped.items():
                    resolution_count += await _resolve_survivor_fields(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=batch_id,
                        survivor_id=survivor,
                        items=survivor_items,
                    )

                target_state = (
                    DiscoveryBatchState.SEAL_PENDING
                    if reviews == 0
                    else DiscoveryBatchState.FIELD_MATERIALIZATION
                )
                if batch.state is not target_state:
                    batch = await update_discovery_batch_state(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=batch_id,
                        state=target_state,
                    )
                outcome = (
                    ExaD4Outcome.REVIEW_REQUIRED
                    if reviews
                    else ExaD4Outcome.REPLAYED
                    if replay and created == 0
                    else ExaD4Outcome.MATERIALIZED
                )
                result = ExaD4Result(
                    batch_id=batch_id,
                    outcome=outcome,
                    batch_state=batch.state,
                    item_count=len(prepared),
                    account_ids=tuple(sorted(grouped, key=str)),
                    excluded_item_count=excluded,
                    review_item_count=reviews,
                    claim_ids=tuple(sorted(all_claim_ids, key=str)),
                    claims_created=created,
                    claims_reused=reused,
                    field_resolution_count=resolution_count,
                )
                apply_attributes(
                    span,
                    {
                        "outcome": result.outcome.value,
                        "item_count": result.item_count,
                        "account_count": len(result.account_ids),
                        "claims_created": result.claims_created,
                        "claims_reused": result.claims_reused,
                        "review_item_count": result.review_item_count,
                    },
                )
                return result


__all__ = [
    "ExaD4Outcome",
    "ExaD4Result",
    "ExaWebsetsD4Materializer",
    "ExaWebsetsDurableSnapshotChannel",
    "ensure_exa_company_field_claim",
    "exa_enrichment_value",
]
