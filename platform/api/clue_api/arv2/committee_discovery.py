"""ARV2 v2 committee discovery and selected-person enrichment.

Tools reason over provider data; authority remains the job, verified source references, shared
identity service and claim writer. Profiles never become a second durable fact store.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import research_operations as operations
from clue_api.arv2.account_research_catalog import has_capability
from clue_api.arv2.account_research_claims import (
    COMMITTEE_FIELD,
    JobScope,
    _draft,
    ai_ark_company_claims,
    ai_ark_person_claims,
    committee_candidate_claims,
    email_export_claim,
    fit_verdict_claims,
    provider_evidence,
)
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.ai_ark_client import (
    AiArkPerson,
    company_from_record,
    email_export_from_record,
    person_from_record,
    role_search_body,
)
from clue_api.arv2.ai_ark_research import enrichment_only
from clue_api.arv2.claim_writer import WriteReceipt
from clue_api.arv2.exa_client import read_deep_report
from clue_core import ExtractionMethod
from clue_research.identity.provider import (
    register_provider_subjects,
    resolve_provider_contact,
)
from clue_storage import read_verified_artifact, verify_artifact_bytes

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

    from clue_api.arv2.account_research_tools import ToolRuntime


class DiscoverPeopleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    titles: list[str] = Field(min_length=1, max_length=300)
    seniority: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    page: int = Field(default=0, ge=0)
    size: int = Field(default=10, ge=1, le=100)


class ReadPeopleResultArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_ref: UUID
    candidate_refs: list[str] = Field(default_factory=list)


class EnrichContactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[Literal["email"]] = Field(default=["email"])


def fold(value: str | None) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .rstrip("/")
    )


def candidate_ref(operation_id: UUID, person_id: str) -> str:
    return f"{operation_id}:{person_id}"


def split_candidate(reference: str) -> tuple[UUID, str]:
    try:
        op, subject = reference.split(":", 1)
        if not subject:
            raise ValueError("missing subject")
        return UUID(op), subject
    except ValueError as exc:
        raise RefusalError("invalid_arguments", "invalid candidate reference") from exc


def employment_check(person: AiArkPerson, scope: JobScope) -> None:
    if person.current_company_domain and fold(person.current_company_domain) != fold(
        scope.account_domain
    ):
        raise RefusalError(
            "invalid_arguments", "candidate has a conflicting current employer; record the gap"
        )


def provider_reference_data(
    op: operations.Operation, subject: str, provider_job_id: UUID
) -> dict[str, Any]:
    """Provider provenance is independent of the job that delegated this investigation."""
    return {
        "version": 1,
        "candidate_ref": candidate_ref(op.operation_id, subject),
        "operation_id": str(op.operation_id),
        "provider_subject_id": subject,
        "artifact_key": op.artifact_key,
        "provider_job_id": str(provider_job_id),
    }


def reference_data(op: operations.Operation, subject: str, parent_job_id: UUID) -> dict[str, Any]:
    return {
        **provider_reference_data(op, subject, parent_job_id),
        "parent_job_id": str(parent_job_id),
    }


def _ai_ark_people(record: Mapping[str, Any]) -> bool:
    # Companies have IDs too, but are not personal-data subjects.
    return record.get("provider") == "ai_ark" and "people" in str(record.get("operation", ""))


async def index_provider_artifacts(
    runtime: ToolRuntime,
    conn: AsyncConnection,
    keys: Iterable[str],
    bodies: Mapping[str, bytes] | None = None,
) -> None:
    """Register the people in AI Ark responses as provider subjects.

    ``bodies`` are responses the caller has just stored (key -> bytes, W2-16): a response that is
    not an AI Ark people result is skipped without a download, and an AI Ark one is checked
    against its row without one.
    """
    assert runtime.storage is not None
    for key in keys:
        held = (bodies or {}).get(key)
        if held is not None:
            record = json.loads(held).get("record", {})
            if not _ai_ark_people(record):
                continue
            await verify_artifact_bytes(
                conn, storage_key=key, workspace_id=runtime.scope.workspace_id, data=held
            )
            data = held
        else:
            _, data = await read_verified_artifact(
                conn, runtime.storage, storage_key=key, workspace_id=runtime.scope.workspace_id
            )
        envelope = json.loads(data)
        record = envelope.get("record", {})
        if not _ai_ark_people(record):
            continue
        try:
            response = json.loads(envelope.get("body_utf8", "null"))
        except ValueError:
            response = {}
        if not isinstance(response, dict):
            response = {}
        rows = response.get("content")
        profiles = rows if isinstance(rows, list) else [response]
        subjects: list[tuple[str, str | None]] = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            person = person_from_record(profile)
            linkedin = person.linkedin_url or profile.get("linkedin")
            subject = person.ark_id or (f"linkedin:{fold(linkedin)}" if linkedin else None)
            if subject:
                subjects.append((subject, linkedin))
        # A no-email/no-phone response can omit identity. The bound request still identifies it.
        if runtime.scope.subject_kind == "person" and runtime.scope.person_linkedin_url:
            subjects.append(
                (
                    f"linkedin:{fold(runtime.scope.person_linkedin_url)}",
                    runtime.scope.person_linkedin_url,
                )
            )
        if runtime.person_seed:
            subjects.append(
                (
                    runtime.person_seed["provider_subject_id"],
                    runtime.scope.person_linkedin_url or None,
                )
            )
        await register_provider_subjects(
            conn,
            workspace_id=runtime.scope.workspace_id,
            provider="ai_ark",
            artifact_key=key,
            subjects=subjects,
        )


async def company_lock(runtime: ToolRuntime) -> dict[str, Any]:
    domain = fold(runtime.scope.account_domain)
    if not domain:
        raise RefusalError("invalid_arguments", "account has no exact domain; use web evidence")
    try:
        op, raw = await runtime.operate(
            "ai_ark",
            "company_lock",
            {"domain": domain},
            lambda caller: runtime.clients.ai_ark(caller).companies_exact(domain),
        )
    except Exception as exc:
        if has_capability(runtime.scope.catalog_version, "research_quality"):
            raise  # Governed receipt must expose the refusal instead of reporting a green lookup.
        # A provider halt is not bypassed: the next people call sees the same runtime latch.
        return {"domain": domain, "company_id": None, "reason": type(exc).__name__}
    rows = [company_from_record(row) for row in raw.get("content", []) if isinstance(row, dict)]
    exact = [row for row in rows if fold(row.domain) == domain]
    ids = {row.ark_id for row in exact if row.ark_id}
    selected = exact[0] if len(ids) == 1 and len(exact) == 1 else None
    if selected:
        await runtime.write(
            [
                replace(
                    d,
                    artifact_key=op.artifact_key,
                    markers={**d.markers, "operation_id": str(op.operation_id)},
                )
                for d in ai_ark_company_claims(selected, runtime.scope, catalog=runtime.catalog)
            ]
        )
    return {
        "domain": domain,
        "company_id": selected.ark_id if selected else None,
        "operation_id": str(op.operation_id),
        "reason": "resolved" if selected and selected.ark_id else "no_unambiguous_company_id",
    }


async def discover_people(runtime: ToolRuntime, args: DiscoverPeopleArgs) -> dict[str, Any]:
    # Validate before even the company-lookup spend; optional invalid filters never broaden.
    try:
        role_search_body(
            args.titles,
            domain=fold(runtime.scope.account_domain),
            seniority=args.seniority,
            functions=args.functions,
            page=args.page,
            size=args.size,
        )
    except ValueError as error:
        raise RefusalError("invalid_arguments", str(error)) from error
    async with runtime._conn_factory() as conn:
        attempted = await operations.deep_attempted(conn, runtime.operation_scope)
    if not attempted:
        raise RefusalError(
            "invalid_arguments",
            (
                "Call research_deep for this account first. After its exhausted "
                "failure, record the research gap and continue discovery."
            ),
        )
    lock = await company_lock(runtime)
    filters = {
        "company_id": lock["company_id"],
        "domain": None if lock["company_id"] else lock["domain"],
        "seniority": args.seniority,
        "functions": args.functions,
        "page": args.page,
        "size": args.size,
    }
    request = role_search_body(args.titles, **filters)
    op, raw = await runtime.operate(
        "ai_ark",
        "people_roles",
        request,
        lambda caller: runtime.clients.ai_ark(caller).people_by_roles(args.titles, **filters),
    )
    assessment = _draft(
        runtime.scope,
        field_key="account.committee_search_assessment",
        value={
            "role_key": args.role_key,
            "rationale": args.rationale,
            "evidence_refs": [str(ref) for ref in args.evidence_refs],
            "result_ref": str(op.operation_id),
            "titles": request["contact"]["experience"]["latest"]["title"]["any"]["include"][
                "content"
            ],
            "company_lock": lock,
        },
        method=ExtractionMethod.LLM_SYNTHESIS,
        source_url=None,
        evidence_span=args.rationale,
        priority=2,
        outreach_safe=False,
        confidence=0.6,
        source_key="agent",
    )
    if not has_capability(runtime.scope.catalog_version, "research_quality"):
        await runtime.write([replace(assessment, artifact_key=op.artifact_key)])
    result = page_result(op, raw, runtime.scope, full=False)
    result.update(company_lock=lock, page=args.page, size=args.size)
    if result["has_more"] is None and isinstance(result["total_pages"], int):
        result["has_more"] = args.page + 1 < result["total_pages"]
    return result


def page_result(
    op: operations.Operation, raw: Mapping[str, Any], scope: JobScope, *, full: bool
) -> dict[str, Any]:
    people = []
    request = op.request_data or {}
    expected_ids = (
        request.get("contact", {})
        .get("company", {})
        .get("latest", {})
        .get("any", {})
        .get("include", [])
    )
    for row in raw.get("content", []):
        if not isinstance(row, dict):
            continue
        person = person_from_record(row)
        conflict = bool(
            (
                person.current_company_domain
                and fold(person.current_company_domain) != fold(scope.account_domain)
            )
            or (
                person.current_company_id
                and expected_ids
                and person.current_company_id not in expected_ids
            )
        )
        people.append(
            {
                "candidate_ref": candidate_ref(op.operation_id, person.ark_id)
                if person.ark_id
                else None,
                "provider_subject_id": person.ark_id,
                "name": person.full_name,
                "title": person.title,
                "linkedin_url": person.linkedin_url,
                "current_company": person.current_company,
                "current_company_domain": person.current_company_domain,
                "employment": "conflict"
                if conflict
                else "stated"
                if person.current_company_domain
                else "unknown",
                **({"profile": enrichment_only(row)} if full else {}),
            }
        )
    last = raw.get("last")
    return {
        "result_ref": str(op.operation_id),
        "people": people,
        "returned": len(people),
        "total_elements": raw.get("totalElements"),
        "total_pages": raw.get("totalPages"),
        "page": request.get("page"),
        "size": request.get("size"),
        "has_more": not last if isinstance(last, bool) else False if op.state == "empty" else None,
        "track_id": raw.get("trackId"),
        "source_kind": "external_provider_data",
    }


async def read_people_result(runtime: ToolRuntime, args: ReadPeopleResultArgs) -> dict[str, Any]:
    assert runtime.storage is not None
    async with runtime._conn_factory() as conn:
        op, raw = await operations.body(
            conn, runtime.storage, runtime.operation_scope, args.result_ref
        )
    if op.kind != "people_roles":
        raise RefusalError("invalid_arguments", "reference is not a role search")
    result = page_result(op, raw, runtime.scope, full=True)
    if args.candidate_refs:
        available = {p["candidate_ref"] for p in result["people"]}
        if not set(args.candidate_refs) <= available:
            raise RefusalError("invalid_arguments", "candidate does not belong to this result")
        result["people"] = [
            p for p in result["people"] if p["candidate_ref"] in args.candidate_refs
        ]
    return result


async def read_candidate(
    conn: AsyncConnection, storage: Any, scope: operations.OperationScope, reference: str
) -> tuple[operations.Operation, AiArkPerson]:
    oid, subject = split_candidate(reference)
    op, raw = await operations.body(conn, storage, scope, oid)
    if op.kind not in {"people_roles", "person_named"}:
        raise RefusalError("invalid_arguments", "reference is not a people result")
    rows = [
        p for p in raw.get("content", []) if isinstance(p, dict) and str(p.get("id")) == subject
    ]
    if len(rows) != 1:
        raise RefusalError("invalid_arguments", "candidate reference is absent or ambiguous")
    person = person_from_record(rows[0])
    expected_ids = (
        (op.request_data or {})
        .get("contact", {})
        .get("company", {})
        .get("latest", {})
        .get("any", {})
        .get("include", [])
    )
    if person.current_company_id and expected_ids and person.current_company_id not in expected_ids:
        raise RefusalError("invalid_arguments", "candidate has a conflicting provider employer ID")
    return op, person


async def finalize_committee(
    runtime: ToolRuntime, args: Any, verdicts: Any, keyed: Any, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    assert runtime.storage is not None
    resolved = []
    seen: set[str] = set()
    # Selection and its ordered checkpoint commit together; a lost return reuses live claims.
    async with runtime._conn_factory() as conn:
        saved = (
            await conn.execute(
                text(
                    "SELECT selection_claim_ids FROM arv2_research_job WHERE job_id=:job "
                    "AND workspace_id=:ws FOR UPDATE"
                ),
                {"job": runtime.scope.job_id, "ws": runtime.scope.workspace_id},
            )
        ).scalar_one()
        if saved is not None:
            resolved = await operations.selected_candidates(conn, runtime.operation_scope)
            receipts: list[WriteReceipt] = []
        else:
            for supplied in candidates:
                candidate = dict(supplied)
                kind = candidate["evidence_kind"]
                if kind == "provider_candidate":
                    op, person = await read_candidate(
                        conn,
                        runtime.storage,
                        runtime.operation_scope,
                        candidate.get("candidate_ref") or "",
                    )
                    employment_check(person, runtime.scope)
                    if not person.full_name or not person.ark_id:
                        raise RefusalError(
                            "invalid_arguments", "provider profile lacks a name or ID"
                        )
                    candidate.update(
                        reference_data(op, person.ark_id, runtime.scope.job_id),
                        name=person.full_name,
                        title=person.title,
                        linkedin_url=person.linkedin_url,
                        confirmed_by=None,
                        vacant_seat=False,
                        evidence_span=None,
                    )
                    identity = f"provider:{person.ark_id}"
                elif kind == "unfilled_role":
                    if not candidate.get("role_key") or not candidate.get("gap_reason"):
                        raise RefusalError(
                            "invalid_arguments", "unfilled_role needs role_key and gap_reason"
                        )
                    if candidate.get("vacant_seat") and not (
                        candidate.get("confirmed_by") and candidate.get("evidence_span")
                    ):
                        raise RefusalError(
                            "invalid_arguments",
                            (
                                "vacancy requires evidence; a missing search result "
                                "is only an unfilled role"
                            ),
                        )
                    candidate.update(name=None, title=None, linkedin_url=None, candidate_ref=None)
                    identity = f"role:{candidate['role_key']}"
                else:
                    url = str(candidate.get("confirmed_by") or "")
                    if (
                        not candidate.get("name")
                        or not url.startswith(("https://", "http://"))
                        or not candidate.get("evidence_span")
                    ):
                        raise RefusalError(
                            "invalid_arguments",
                            "web_candidate needs name, confirming URL and evidence",
                        )
                    candidate["candidate_ref"] = None
                    identity = (
                        f"url:{fold(candidate.get('linkedin_url'))}"
                        if candidate.get("linkedin_url")
                        else f"name:{candidate['name'].strip().casefold()}"
                    )
                aliases = {identity}
                if candidate.get("linkedin_url"):
                    aliases.add(f"url:{fold(candidate['linkedin_url'])}")
                if seen & aliases:
                    continue
                seen.update(aliases)
                resolved.append(candidate)
            drafts = [
                *fit_verdict_claims(verdicts, runtime.scope, filled_by_tool=keyed.filled),
                *committee_candidate_claims(resolved, runtime.scope),
            ]
            receipts = []
            selection_ids = []
            for draft in drafts:
                receipt = await runtime._writer.write(conn, draft)
                receipts.append(receipt)
                if draft.field_key == COMMITTEE_FIELD:
                    selection_ids.append(UUID(str(receipt.claim_id)))
                    value = draft.value_json
                    if isinstance(value, dict) and value.get("provider_subject_id"):
                        await conn.execute(
                            text(
                                "INSERT INTO "
                                "provider_selection_claim(workspace_id,provider,"
                                "subject_id,claim_id) "
                                "VALUES (:ws,'ai_ark',:subject,:claim) ON CONFLICT DO NOTHING"
                            ),
                            {
                                "ws": runtime.scope.workspace_id,
                                "subject": value["provider_subject_id"],
                                "claim": receipt.claim_id,
                            },
                        )
            await operations.checkpoint_selection(conn, runtime.operation_scope, selection_ids)
    runtime.finalization = {
        "summary": args.summary,
        "fit_verdicts": verdicts,
        "gaps": args.gaps,
        "committee_candidates": resolved,
        "proposed_at": runtime.now().isoformat(),
    }
    return {
        "accepted": True,
        "claim_ids": [str(r.claim_id) for r in receipts],
        "dropped_candidates": [],
        "duplicate_gates": list(keyed.duplicates),
    }


def deep_result(
    op: operations.Operation, raw: Mapping[str, Any], *, text_output: bool = False
) -> dict[str, Any]:
    report = read_deep_report(raw, text_output=text_output) or ""
    if not report.strip():
        raise RefusalError(
            "deep_thin_response",
            (
                "account deep research exhausted its retry; record this gap and "
                "continue committee discovery"
            ),
        )
    return {
        "report": report,
        "result_ref": str(op.operation_id),
        "n_results": len(raw.get("results", [])),
        "source_artifact_key": op.artifact_key,
        "source_from_saved_response": True,
    }


async def load_person_seed(runtime: ToolRuntime) -> dict[str, Any] | None:
    refs = runtime.scope.input_refs or {}
    if not refs.get("candidate_ref"):
        return None
    assert runtime.storage is not None
    if refs.get("version") != 1:
        raise RefusalError("subject_lock_failed", "unsupported person seed version")
    provider_job_id = UUID(refs.get("provider_job_id") or refs["parent_job_id"])
    provider_scope = replace(runtime.operation_scope, job_id=provider_job_id)
    async with runtime._conn_factory() as conn:
        # Stored job references, not model arguments, grant access to the parent selection.
        job = (
            await conn.execute(
                text(
                    "SELECT input_refs FROM arv2_research_job WHERE job_id=:job AND "
                    "workspace_id=:ws AND subject_entity_id=:contact"
                ),
                {
                    "job": runtime.scope.job_id,
                    "ws": runtime.scope.workspace_id,
                    "contact": runtime.scope.contact_id,
                },
            )
        ).scalar_one()
        if job.get("candidate_ref") != refs["candidate_ref"] or (
            job.get("provider_job_id") or job.get("parent_job_id")
        ) != str(provider_job_id):
            raise RefusalError("subject_lock_failed", "person seed does not match the job")
        op, person = await read_candidate(
            conn, runtime.storage, provider_scope, refs["candidate_ref"]
        )
        employment_check(person, runtime.scope)
        bound, _ = await resolve_provider_contact(
            conn,
            workspace_id=runtime.scope.workspace_id,
            account_id=runtime.scope.account_id,
            provider="ai_ark",
            subject_id=person.ark_id or "",
            name=person.full_name or "",
            linkedin_url=person.linkedin_url,
            artifact_key=op.artifact_key or "",
            require_account_match=runtime.scope.catalog_version != "v4",
        )
        if bound != runtime.scope.contact_id:
            raise RefusalError(
                "subject_lock_failed", "source profile belongs to a different contact"
            )
    seed = {
        **job,
        **provider_reference_data(op, person.ark_id or "", provider_job_id),
        "profile": enrichment_only(person.raw),
    }
    runtime.person_seed = seed
    await runtime.write(
        [provider_evidence(d, seed) for d in ai_ark_person_claims(person, runtime.scope)]
    )
    return seed


def channel_identity(
    raw: Mapping[str, Any],
    seed: Mapping[str, Any],
    *,
    phone: bool,
    account_domain: str | None = None,
) -> bool:
    person = person_from_record(seed["profile"])
    returned = person_from_record(raw)
    target_domain = account_domain or person.current_company_domain
    if (
        returned.current_company_domain
        and target_domain
        and fold(returned.current_company_domain) != fold(target_domain)
    ):
        return False
    returned_id = raw.get("id")
    link = raw.get("linkedin") or (raw.get("link") or {}).get("linkedin")
    if returned_id and str(returned_id) != person.ark_id:
        return False
    if link and person.linkedin_url and fold(str(link)) != fold(person.linkedin_url):
        return False
    # Email was requested by stable ID. Phone was requested by a possibly shared name and must
    # explicitly establish the returned person via a matching ID or the selected LinkedIn.
    return not phone or bool(
        (returned_id and str(returned_id) == person.ark_id)
        or (link and person.linkedin_url and fold(str(link)) == fold(person.linkedin_url))
    )


async def enrich_channel(runtime: ToolRuntime, channel: str) -> dict[str, Any]:
    # Also protect direct/internal callers carrying an old phone request. Refuse before
    # loading profiles, recording a provider operation or spending any credits.
    if channel != "email":
        raise RefusalError("invalid_arguments", "Only work-email enrichment is available.")
    seed = runtime.person_seed
    if seed is None:
        return {"state": "unresolved", "reason": "no bound provider profile"}
    subject = seed["provider_subject_id"]
    kind = f"contact_{channel}"
    try:
        op, raw = await runtime.operate(
            "ai_ark",
            kind,
            {"id": subject},
            lambda caller: runtime.clients.ai_ark(caller).export_email(person_id=subject),
        )
        if op.state == "empty":
            state = "empty"
        elif not channel_identity(
            raw, seed, phone=False, account_domain=runtime.scope.account_domain
        ):
            state = "unresolved_identity"
        elif email_export_from_record(raw).free is True:
            state = "unresolved_private_email"
        else:
            draft = email_export_claim(email_export_from_record(raw), runtime.scope)
            if draft:
                reference = reference_data(op, subject, runtime.scope.job_id)
                await runtime.write([provider_evidence(draft, reference)])
            state = "succeeded" if draft else "empty"
        runtime.channel_states[kind] = state
        return {"state": state, "operation_id": str(op.operation_id)}
    except Exception as exc:
        # Failed claims can be retried by the tool against the saved response without re-purchase.
        async with runtime._conn_factory() as conn:
            saved = await operations.operation_states(conn, runtime.operation_scope)
        state = saved.get(kind, "failed")
        if state in {"succeeded", "empty"}:
            state = "claim_write_failed"
        runtime.channel_states[kind] = state
        return {"state": state, "reason": type(exc).__name__}


async def enrich_contact(runtime: ToolRuntime, args: EnrichContactArgs) -> dict[str, Any]:
    if runtime.person_seed is None:
        await load_person_seed(runtime)
    channels = list(dict.fromkeys(args.channels))
    results = await asyncio.gather(*(enrich_channel(runtime, c) for c in channels))
    return dict(zip(channels, results, strict=True))


async def lookup_bound_person(runtime: ToolRuntime, args: Any) -> dict[str, Any]:
    # Seeded jobs never pay for a name search, even if the model asks explicitly.
    if runtime.person_seed is None:
        await load_person_seed(runtime)
    if runtime.person_seed is not None:
        return {
            "profile": enrichment_only(runtime.person_seed["profile"]),
            "channels": await enrich_contact(runtime, EnrichContactArgs()),
        }
    locked = fold(runtime.scope.person_linkedin_url)
    if not locked or fold(args.linkedin_url) != locked:
        raise RefusalError(
            "subject_lock_failed", "unseeded lookup requires this job's confirmed LinkedIn URL"
        )
    op, raw = await runtime.operate(
        "ai_ark",
        "person_named",
        {
            "name": runtime.scope.person_name,
            "domain": fold(runtime.scope.account_domain),
            "linkedin": locked,
        },
        lambda caller: runtime.clients.ai_ark(caller).people_by_name(
            [runtime.scope.person_name], runtime.scope.account_domain, size=3, strict_response=True
        ),
    )
    people = [person_from_record(p) for p in raw.get("content", []) if isinstance(p, dict)]
    matches = [p for p in people if fold(p.linkedin_url) == locked]
    if len(matches) != 1 or not matches[0].ark_id:
        raise RefusalError(
            "subject_lock_failed", "named lookup did not uniquely establish the bound person"
        )
    person = matches[0]
    assert person.ark_id is not None
    employment_check(person, runtime.scope)
    assert runtime.storage is not None
    async with runtime._conn_factory() as conn:
        bound, _ = await resolve_provider_contact(
            conn,
            workspace_id=runtime.scope.workspace_id,
            account_id=runtime.scope.account_id,
            provider="ai_ark",
            subject_id=person.ark_id,
            name=person.full_name or runtime.scope.person_name,
            linkedin_url=person.linkedin_url,
            artifact_key=op.artifact_key or "",
        )
        if bound != runtime.scope.contact_id:
            raise RefusalError("subject_lock_failed", "provider anchor belongs to another contact")
        provider_refs = provider_reference_data(op, person.ark_id, runtime.scope.job_id)
        # Merge only provider-owned keys atomically. Never replace the delegation, parent,
        # generation, brief, recipe pin, or a concurrent privacy/lifecycle update.
        refs = (
            await conn.execute(
                text("""UPDATE arv2_research_job
                SET input_refs=COALESCE(input_refs,'{}'::jsonb) || CAST(:refs AS jsonb)
                WHERE job_id=:job AND workspace_id=:ws AND run_id=:run
                  AND account_entity_id=:account AND subject_type='person'
                  AND subject_entity_id=:contact RETURNING input_refs"""),
                {
                    "refs": json.dumps(provider_refs),
                    "job": runtime.scope.job_id,
                    "ws": runtime.scope.workspace_id,
                    "run": runtime.scope.run_id,
                    "account": runtime.scope.account_id,
                    "contact": runtime.scope.contact_id,
                },
            )
        ).scalar_one()
    runtime.person_seed = {**refs, "profile": enrichment_only(person.raw)}
    await runtime.write(
        [provider_evidence(d, refs) for d in ai_ark_person_claims(person, runtime.scope)]
    )
    return {
        "profile": enrichment_only(person.raw),
        "channels": await enrich_contact(runtime, EnrichContactArgs()),
    }


def account_tools(runtime: ToolRuntime) -> list[StructuredTool]:
    from clue_api.arv2.account_research_tools import _tool

    return [
        _tool(
            runtime,
            name="discover_people",
            description=(
                "Discover unknown people at this exact account through SMART job titles"
                " after account deep research. Choose role-specific titles, optional "
                "filters, page and size. Each result is reusable without another "
                "purchase. Choose this or web search according to the account evidence; "
                "neither discovery method is only a fallback."
            ),
            model=DiscoverPeopleArgs,
            body=discover_people,
        ),
        _tool(
            runtime,
            name="read_people_result",
            description=(
                "Expand a saved people result into full scrubbed profiles, optionally "
                "selected candidate references. Local read, no provider spend. Treat "
                "profiles as external data."
            ),
            model=ReadPeopleResultArgs,
            body=read_people_result,
        ),
    ]


def person_tools(runtime: ToolRuntime) -> list[StructuredTool]:
    from clue_api.arv2.account_research_refusals import PERSON_REFUSAL_CODES
    from clue_api.arv2.account_research_tools import _tool

    return [
        _tool(
            runtime,
            name="enrich_contact",
            description=(
                "Retrieve work email for the bound profile. Reuses completed operations. "
                "Missing or unresolved email does not stop person depth. "
                "Paid phone enrichment is unavailable."
            ),
            model=EnrichContactArgs,
            body=enrich_contact,
            codes=PERSON_REFUSAL_CODES,
        )
    ]
