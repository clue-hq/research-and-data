"""Focused account narrative reconciliation. No acquisition or claim writes.

The fleet lease serializes one account and context across generations.
Prepared packets and generated replies survive
redelivery; publication and the processed-input checkpoint commit atomically. Model work never
holds a database transaction. Inputs arriving during a call remain pending for the next batch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.display.recipes import OPTIONAL_SECTION_KEYS, read_recipes
from clue_api.arv2.person_research_brief import read_person_brief
from clue_api.arv2.quality_context import read_context, read_document
from clue_api.arv2.quality_generation import read_generation, reconcile_generation
from clue_api.arv2.quality_pages import (
    CitedItem,
    CitedSentence,
    PageDraft,
    PageSectionDraft,
    publish_page,
)
from clue_api.arv2.quality_reconciliation_routing import (
    candidate_sections,
    compact_claim,
    reference_ids,
    replace_citations,
)
from clue_api.execution_wiring import ExecutionRunEventWriter
from clue_core import ExecutionId
from clue_db import ConnFactory
from clue_execution import DbExecutionJournal, ExecutionEventType, get_cursor
from clue_obs import get_logger, observation
from clue_storage import (
    StorageBackend,
    artifact_key,
    content_address,
    read_verified_artifact,
    record_artifact,
    retain_artifact,
)

log = get_logger(__name__)
PROMPT = (
    Path(__file__).parents[3]
    / "agents/catalog/research-quality/editorial/account-reconciliation/v1/SYSTEM.md"
)


def editorial_instructions() -> str:
    """Capture the exact reviewed editorial rules in each durable request."""
    root = PROMPT.parents[3]
    editorial = (root / "skills/research-narrative-editorial/v1/SKILL.md").read_text()
    account = (root / "skills/account-research-narrative/v2/SKILL.md").read_text()
    account = account.split("## Overview:", 1)[1].split("## Review, references and save", 1)[0]
    return (
        "Editorial guidance:\n"
        + editorial
        + "\n\nSection purposes and examples:\n"
        + account
        + "\n\nReconciliation assignment and output contract:\n"
        + PROMPT.read_text()
    )


class ReconciliationSentence(CitedSentence):
    # Reuse the production narrative schema; only citations use request-local aliases.
    claim_ids: tuple[str, ...] = Field(  # type: ignore[assignment]
        default=(), max_length=30, alias="claimIds"
    )


class ReconciliationItem(CitedItem):
    body: tuple[ReconciliationSentence, ...] = Field(min_length=1, max_length=20)
    send_line: ReconciliationSentence | None = Field(default=None, alias="sendLine")


class ReconciliationSection(PageSectionDraft):
    intro: tuple[ReconciliationSentence, ...] = Field(default=(), max_length=30)
    items: tuple[ReconciliationItem, ...] = Field(default=(), max_length=30)


class ReconciliationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Literal["overview", "insights"]
    section: ReconciliationSection


class ReconciliationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    updates: list[ReconciliationUpdate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def execution_id_for(generation_id: UUID, revision: int) -> ExecutionId:
    return ExecutionId(uuid5(NAMESPACE_URL, f"reconciliation:{generation_id}:{revision}"))


async def execution_event(
    conn: AsyncConnection, generation_id: UUID, revision: int, event: ExecutionEventType
) -> None:
    eid = execution_id_for(generation_id, revision)
    cursor = await get_cursor(conn, eid)
    await DbExecutionJournal(transport=ExecutionRunEventWriter()).append_event(
        conn,
        execution_id=eid,
        event_type=event,
        actor="system",
        expected_state_version=cursor.state_version,
        payload={"generation_id": str(generation_id), "input_revision": revision},
    )


async def persist(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    generation_id: UUID,
    revision: int,
    kind: str,
    value: Any,
    parents: Any = (),
) -> str:
    raw = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True).encode()
    sha = content_address(raw)
    key = artifact_key(scope.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type="application/json")
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=key,
        reference_kind="research_reconciliation",
        reference_id=f"{generation_id}:{revision}:{kind}",
    )
    for parent in sorted(set(parents)):
        await conn.execute(
            text("""INSERT INTO artifact_derivation(workspace_id,parent_key,child_key)
            VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"""),
            {"ws": scope.workspace_id, "parent": parent, "child": key},
        )
    await conn.execute(
        text("""INSERT INTO agent_artifact_subject
        (workspace_id,artifact_key,subject_entity_id,binding_kind)
        VALUES(:ws,:key,:subject,'derived') ON CONFLICT DO NOTHING"""),
        {"ws": scope.workspace_id, "key": key, "subject": scope.account_id},
    )
    await conn.execute(
        text("""INSERT INTO agent_artifact_project
        (workspace_id,project_id,artifact_key,binding_kind)
        VALUES(:ws,:project,:key,'research_reconciliation') ON CONFLICT DO NOTHING"""),
        {"ws": scope.workspace_id, "project": scope.project_id, "key": key},
    )
    return key


async def account_research_model(conn: AsyncConnection, scope: JobScope) -> str:
    """Recover the originating research model, scoped to its account job and workspace."""
    execution_id = uuid5(NAMESPACE_URL, f"research-quality:{scope.job_id}")
    model = (
        await conn.execute(
            text(
                "SELECT requested_model FROM agent_model_call WHERE execution_id=:id "
                "AND workspace_id=:ws ORDER BY sequence LIMIT 1"
            ),
            {"id": execution_id, "ws": scope.workspace_id},
        )
    ).scalar_one_or_none()
    if not model:
        raise ValueError("Account researcher model history unavailable; cannot continue session")
    return str(model)


async def read_payload(
    conn: AsyncConnection, storage: StorageBackend, ws: str, key: str
) -> dict[str, Any]:
    _, body = await read_verified_artifact(conn, storage, workspace_id=ws, storage_key=key)
    return cast(dict[str, Any], json.loads(body))


async def prepare(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    generation_id: UUID,
    revision: int,
) -> dict[str, Any]:
    generation = await read_generation(
        conn, workspace_id=scope.workspace_id, generation_id=generation_id
    )
    if (
        generation.project_id != scope.project_id
        or generation.context_id != context_id
        or generation.account_id != scope.account_id
        or generation.initial_job_id != scope.job_id
        or generation.run_id != scope.run_id
        or scope.person_subject_id is not None
    ):
        raise ValueError("Reconciliation scope does not match its account generation")
    if generation.state in ("suspended", "privacy_stopped"):
        raise ValueError("Reconciliation generation is stopped")
    if revision > generation.input_revision:
        raise ValueError("Reconciliation revision is ahead of committed inputs")
    existing = (
        (
            await conn.execute(
                text("""SELECT * FROM arv2_narrative_reconciliation
        WHERE generation_id=:generation AND input_revision=:revision AND workspace_id=:ws"""),
                {"generation": generation_id, "revision": revision, "ws": scope.workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        return dict(existing)
    prior = (
        await conn.execute(
            text("""SELECT claim_versions FROM arv2_narrative_reconciliation
        WHERE generation_id=:generation AND workspace_id=:ws AND state='completed'
        ORDER BY input_revision DESC LIMIT 1"""),
            {"generation": generation_id, "ws": scope.workspace_id},
        )
    ).scalar_one_or_none()
    children = (
        (
            await conn.execute(
                text("""SELECT j.job_id,j.subject_entity_id,j.status,j.input_refs,
        (SELECT max(dossier_version) FROM arv2_research_import_ready r WHERE r.job_id=j.job_id
          AND r.workspace_id=j.workspace_id) AS imported_version
        FROM arv2_generation_child c JOIN arv2_research_job j ON j.job_id=c.job_id
        WHERE c.generation_id=:generation AND c.workspace_id=:ws ORDER BY j.job_id"""),
                {"generation": generation_id, "ws": scope.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    if any(
        not c["imported_version"] and c["status"] not in ("completed", "needs_review", "failed")
        for c in children
    ):
        raise ValueError("Person import batch is not ready")
    subjects = [scope.account_id, *(c["subject_entity_id"] for c in children)]
    rows = (
        (
            await conn.execute(
                text("""SELECT c.id,c.entity_id,c.field_key,c.value_json,
        c.source_url,c.evidence_span,c.superseded_by,c.artifact_key,q.revision,q.conclusion
        FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
        LEFT JOIN artifact a ON a.storage_key=c.artifact_key AND a.workspace_id=c.workspace_id
        WHERE c.workspace_id=:ws AND c.entity_id=ANY(:subjects)
          AND (q.context_id IS NULL OR q.context_id=:context)
          AND c.field_key NOT IN ('account.value_narrative','contact.value_narrative')
          AND (c.artifact_key IS NULL OR (a.storage_key IS NOT NULL AND a.erased_at IS NULL
            AND NOT a.privacy_erased AND (a.expires_at IS NULL OR a.expires_at>now())))
        ORDER BY c.id"""),
                {"ws": scope.workspace_id, "subjects": subjects, "context": context_id},
            )
        )
        .mappings()
        .all()
    )
    claims = {str(r["id"]): compact_claim(dict(r)) for r in rows}
    versions = {
        str(r["id"]): [
            r["revision"],
            r["conclusion"],
            str(r["superseded_by"]) if r["superseded_by"] else None,
        ]
        for r in rows
    }
    blocks = (
        (
            await conn.execute(
                text("""SELECT page,section_key,display_block_id,body_json,
        dependency_manifest,output_artifact_key FROM display_block
        WHERE workspace_id=:ws AND project_id=:project AND context_id=:context
          AND generation_id=:generation AND subject_id=:subject AND subject_kind='account'
          AND superseded_at IS NULL AND EXISTS (
            SELECT 1 FROM artifact a WHERE a.storage_key=display_block.output_artifact_key
              AND a.workspace_id=display_block.workspace_id AND a.erased_at IS NULL
              AND NOT a.privacy_erased AND (a.expires_at IS NULL OR a.expires_at>now()))
          ORDER BY page,section_key"""),
                {
                    "ws": scope.workspace_id,
                    "project": scope.project_id,
                    "context": context_id,
                    "generation": generation_id,
                    "subject": scope.account_id,
                },
            )
        )
        .mappings()
        .all()
    )
    baseline = prior
    if baseline is None:
        # Initial account already wrote its own claims. Compare its actual dependencies for
        # corrections; every ready person finding receives one consideration, even if cited.
        baseline = {
            id: v for id, v in versions.items() if claims[id]["entity_id"] == str(scope.account_id)
        }
        for b in blocks:
            for id, *v in b["dependency_manifest"].get("claim_versions", []):
                if id not in claims or claims[id]["entity_id"] == str(scope.account_id):
                    baseline[id] = v
    changed = {id for id in set(baseline) | set(versions) if baseline.get(id) != versions.get(id)}
    recipes = [
        r
        for page in ("overview", "insights")
        for r in await read_recipes(conn, page, workspace_id=scope.workspace_id)
        if r.shared_from is None
    ]
    all_sections = {f"{r.page}/{r.section_key}": r for r in recipes}
    live = {f"{b['page']}/{b['section_key']}": dict(b) for b in blocks}
    candidates = set()
    routes = {}
    for id in sorted(changed):
        routes[id] = sorted(candidate_sections(claims[id], recipes)) if id in claims else []
        candidates.update(routes[id])
    for key, existing_block in live.items():
        if reference_ids(existing_block["body_json"].get("_quality_draft", {})) & changed:
            candidates.add(key)
    candidates &= all_sections.keys()
    selected = set(changed) & claims.keys()
    sections = []
    for key in sorted(candidates):
        block = live.get(key)
        r = all_sections[key]
        draft = (
            block["body_json"].get("_quality_draft")
            if block
            else {"key": r.section_key, "intro": [], "items": [], "gaps": []}
        )
        selected.update(reference_ids(draft) & claims.keys())
        selected.update(
            id
            for id, c in claims.items()
            if c["entity_id"] == str(scope.account_id)
            and key in candidate_sections(c, [r])
            and (c["field_key"] in r.allowed_field_keys or key in candidate_sections(c, recipes))
        )
        sections.append({"page": r.page, "title": r.h1, "section": draft})
    # Follow explicit qualification/conflict/supersession links to closure.
    while True:
        expanded = selected | (
            set().union(*(reference_ids(claims[id]) for id in selected)) & claims.keys()
        )
        if expanded == selected:
            break
        selected = expanded
    aliases = {id: f"C{i + 1}" for i, id in enumerate(sorted(selected))}
    # A removed/erased reference remains identifiable for correction, without resurrecting text.
    missing_refs = set().union(*(reference_ids(s) for s in sections)) - aliases.keys()
    for id in sorted(missing_refs):
        aliases[id] = f"C{len(aliases) + 1}"
    packet = {
        "_editorial_system": editorial_instructions(),
        "_execution_id": str(execution_id_for(generation_id, revision)),
        "changed": [aliases[id] for id in sorted(changed) if id in aliases],
        "claims": [
            {**claims[id], "id": aliases[id], "suggested_sections": routes.get(id, [])}
            for id in sorted(selected)
        ],
        "unavailable_claims": [aliases[id] for id in sorted(missing_refs)],
        "sections": replace_citations(sections, aliases),
        "people": [
            {
                "contact_id": str(c["subject_entity_id"]),
                "job_status": c["status"],
                "imported_version": c["imported_version"],
            }
            for c in children
        ],
        "direction": scope.directive_text
        if hasattr(scope, "directive_text")
        else (scope.input_refs or {}).get("directive_text", ""),
    }
    parents = [r["artifact_key"] for r in rows if str(r["id"]) in selected and r["artifact_key"]]
    parents.extend(b["output_artifact_key"] for b in blocks if b["output_artifact_key"])
    if candidates:
        ctx = await read_context(
            conn,
            storage,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            context_id=context_id,
        )
        packet["seller"] = {
            "name": ctx.seller_name,
            "products": ctx.products,
            "persona_state": ctx.persona_state,
            "gaps": ctx.gaps,
        }
        packet["documents"] = [
            {
                "kind": d.kind,
                "text": await read_document(conn, storage, workspace_id=scope.workspace_id, pin=d),
            }
            for d in ctx.documents()
        ]
        parents.extend(d.artifact_key for d in ctx.documents())
        packet["direction"] = (
            await conn.execute(
                text(
                    "SELECT directive_text FROM arv2_research_run "
                    "WHERE run_id=:run AND workspace_id=:ws"
                ),
                {"run": scope.run_id, "ws": scope.workspace_id},
            )
        ).scalar_one()
        for child, person in zip(children, packet["people"], strict=True):
            brief = await read_person_brief(
                conn,
                storage,
                replace(
                    scope,
                    job_id=child["job_id"],
                    subject_kind="person",
                    contact_id=child["subject_entity_id"],
                    input_refs=child["input_refs"],
                ),
                context_id=context_id,
            )
            person["delegation"] = brief["brief"] if brief else None
            if ref := (child["input_refs"] or {}).get("person_research_brief"):
                parents.append(ref["artifact_key"])
    stored = {
        "input": packet,
        "aliases": {v: k for k, v in aliases.items()},
        "allowed_sections": sorted(candidates),
        "required_sections": sorted(
            key for key, r in all_sections.items() if r.section_key not in OPTIONAL_SECTION_KEYS
        ),
    }
    key = await persist(conn, storage, scope, generation_id, revision, "packet", stored, parents)
    # Publication has its own system execution. The continued researcher has a separate
    # governed turn; this record owns the atomic section replacement and input checkpoint.
    eid = execution_id_for(generation_id, revision)
    await conn.execute(
        text("""INSERT INTO execution
        (id,workspace_id,project_id,started_by,parameter_artifact_key,
         parameter_manifest_hash,pin_manifest_hash)
        VALUES(:id,:ws,:project,'system',:key,:sha,:pin)"""),
        {
            "id": eid,
            "ws": scope.workspace_id,
            "project": scope.project_id,
            "key": key,
            "sha": key.rsplit("/", 1)[-1],
            "pin": hashlib.sha256(packet["_editorial_system"].encode()).hexdigest(),
        },
    )
    await conn.execute(
        text("INSERT INTO execution_cursor(execution_id,status) VALUES(:id,'queued')"), {"id": eid}
    )
    await execution_event(conn, generation_id, revision, ExecutionEventType.EXECUTION_STARTED)
    # Preserve subject erasure bindings even for claims with no artifact parent.
    for subject in subjects:
        await conn.execute(
            text("""INSERT INTO agent_artifact_subject
            (workspace_id,artifact_key,subject_entity_id,binding_kind)
            VALUES(:ws,:key,:subject,'derived') ON CONFLICT DO NOTHING"""),
            {"ws": scope.workspace_id, "key": key, "subject": subject},
        )
    block_versions = {k: str(v["display_block_id"]) for k, v in live.items() if k in candidates}
    await conn.execute(
        text("""INSERT INTO arv2_narrative_reconciliation
        (generation_id,input_revision,workspace_id,packet_key,claim_versions,block_versions)
        VALUES(:generation,:revision,:ws,:key,CAST(:claims AS jsonb),CAST(:blocks AS jsonb))"""),
        {
            "generation": generation_id,
            "revision": revision,
            "ws": scope.workspace_id,
            "key": key,
            "claims": json.dumps(versions),
            "blocks": json.dumps(block_versions),
        },
    )
    return {
        "state": "prepared",
        "packet_key": key,
        "response_key": None,
        "claim_versions": versions,
        "block_versions": block_versions,
    }


def parse_updates(
    raw: Any, packet: dict[str, Any]
) -> list[tuple[Literal["overview", "insights"], PageSectionDraft]]:
    reply = ReconciliationReply.model_validate(raw)
    updates: list[tuple[Literal["overview", "insights"], PageSectionDraft]] = []
    seen = set()
    for update in reply.updates:
        page = update.page
        section = PageSectionDraft.model_validate(
            replace_citations(
                update.section.model_dump(mode="json", by_alias=True), packet["aliases"]
            )
        )
        key = f"{page}/{section.key}"
        if key not in packet["allowed_sections"] or key in seen:
            raise ValueError("Update must name a unique supplied section")
        seen.add(key)
        unavailable = set(packet["input"]["unavailable_claims"])
        unavailable_ids = {packet["aliases"][id] for id in unavailable}
        if any(str(id) in unavailable_ids for s in section.sentences() for id in s.claim_ids):
            raise ValueError("Cannot cite unavailable evidence")
        if any(s.kind != "gap" and not s.claim_ids for s in section.sentences()):
            raise ValueError("Non-gap sentences require supplied evidence")
        people = {p["contact_id"] for p in packet["input"]["people"]}
        if any(str(id) not in people for i in section.items for id in i.contact_ids):
            raise ValueError("Unknown contact reference")
        updates.append((page, section))
    return updates


async def run_reconciliation(
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    generation_id: UUID,
    revision: int,
    generate: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    model: str,
    stopped: Callable[[], bool],
    assert_lease: Callable[..., Awaitable[None]] | None = None,
) -> dict[str, Any]:
    start = time.monotonic()
    with observation(
        "research.account_reconciliation",
        as_type="span",
        metadata={
            "workspace_id": scope.workspace_id,
            "job_id": str(scope.job_id),
            "generation_id": str(generation_id),
            "input_revision": revision,
            "execution_id": str(execution_id_for(generation_id, revision)),
        },
    ):
        async with conn_factory() as conn:
            if assert_lease:
                await assert_lease(conn)
            row = await prepare(conn, storage, scope, context_id, generation_id, revision)
            if row["state"] in ("completed", "failed"):
                return {"replayed": True, "state": row["state"]}
            packet = await read_payload(conn, storage, scope.workspace_id, row["packet_key"])
            reply = (
                await read_payload(conn, storage, scope.workspace_id, row["response_key"])
                if row["response_key"]
                else None
            )
        prepared_at = time.monotonic()
        if stopped():
            raise asyncio.CancelledError()
        if reply is None:
            reply = (
                await generate({**packet["input"], "_validation_packet": packet})
                if packet["allowed_sections"]
                else {"updates": [], "notes": []}
            )
            parse_updates(reply, packet)
            async with conn_factory() as conn:
                key = await persist(
                    conn,
                    storage,
                    scope,
                    generation_id,
                    revision,
                    "reply",
                    reply,
                    [row["packet_key"]],
                )
                await conn.execute(
                    text("""UPDATE arv2_narrative_reconciliation
                    SET response_key=:key,state='generated'
                    WHERE generation_id=:generation AND input_revision=:revision"""),
                    {"key": key, "generation": generation_id, "revision": revision},
                )
                row["response_key"] = key
        generated_at = time.monotonic()
        updates = parse_updates(reply, packet)
        if stopped():
            raise asyncio.CancelledError()
        async with conn_factory() as conn:
            if assert_lease:
                await assert_lease(conn)
            g = await read_generation(
                conn, workspace_id=scope.workspace_id, generation_id=generation_id, lock=True
            )
            # Erasure/expiry during the model call must not publish the retained response.
            await read_payload(conn, storage, scope.workspace_id, row["packet_key"])
            if g.state in ("suspended", "privacy_stopped"):
                raise ValueError("Generation stopped before publication")
            # Serialize publication with claim corrections, using the same ordering as the
            # normal page writer. New unrelated claims can arrive without invalidating work.
            from clue_api.arv2.quality_page_inputs import page_inputs

            inputs = await page_inputs(
                conn, scope, context_id=context_id, page="overview", lock=True
            )
            now_versions = {id: v for id, *v in cast(list[Any], inputs.manifest["claim_versions"])}
            cited = {
                str(id)
                for _, s in updates
                for sentence in s.sentences()
                for id in sentence.claim_ids
            }
            if any(now_versions.get(id) != row["claim_versions"].get(id) for id in cited):
                raise ValueError("Cited evidence changed during reconciliation; refresh required")
            # Publication may merge new claims arriving in parallel, but cannot overwrite an
            # independently edited narrative section. Keep the generated reply for inspection.
            for page, section in updates:
                current = (
                    await conn.execute(
                        text("""SELECT display_block_id FROM display_block
                    WHERE workspace_id=:ws AND context_id=:context AND generation_id=:generation
                      AND subject_id=:subject AND page=:page AND section_key=:section
                      AND superseded_at IS NULL"""),
                        {
                            "ws": scope.workspace_id,
                            "context": context_id,
                            "generation": generation_id,
                            "subject": scope.account_id,
                            "page": page,
                            "section": section.key,
                        },
                    )
                ).scalar_one_or_none()
                if (str(current) if current else None) != row["block_versions"].get(
                    f"{page}/{section.key}"
                ):
                    raise ValueError(
                        "Narrative section changed during reconciliation; explicit refresh required"
                    )
            for page in ("overview", "insights"):
                sections = tuple(s for p, s in updates if p == page)
                if sections:
                    await publish_page(
                        conn,
                        storage,
                        scope,
                        context_id=context_id,
                        execution_id=execution_id_for(generation_id, revision),
                        model=model,
                        draft=PageDraft(
                            page=page,
                            expected_dependency_sha256="0" * 64,
                            sections=sections,
                        ),
                        complete=False,
                    )
            await conn.execute(
                text("""UPDATE arv2_narrative_reconciliation
                SET state='completed',completed_at=now()
                WHERE generation_id=:generation AND input_revision=:revision"""),
                {"generation": generation_id, "revision": revision},
            )
            # Missing account pages stay a visible gap; a no-op editor must not falsely
            # certify an account whose original narrative failed. Contact pages can finish later.
            published = (
                (
                    await conn.execute(
                        text("""SELECT page,section_key,dependency_manifest,
                cited_claim_ids FROM display_block WHERE workspace_id=:ws AND context_id=:context
                AND generation_id=:generation AND subject_id=:subject AND superseded_at IS NULL"""),
                        {
                            "ws": scope.workspace_id,
                            "context": context_id,
                            "generation": generation_id,
                            "subject": scope.account_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            missing_sections = set(packet["required_sections"]) - {
                f"{b['page']}/{b['section_key']}" for b in published
            }
            stale_evidence = any(
                {id: v for id, *v in b["dependency_manifest"]["claim_versions"]}.get(str(cid))
                != now_versions.get(str(cid))
                for b in published
                for cid in b["cited_claim_ids"]
            )
            await reconcile_generation(
                conn,
                needs_review=bool(missing_sections or stale_evidence),
                workspace_id=scope.workspace_id,
                generation_id=generation_id,
                expected_revision=revision,
                processed_snapshot=True,
            )
            await execution_event(
                conn, generation_id, revision, ExecutionEventType.EXECUTION_COMPLETED
            )
        elapsed = time.monotonic() - start
        timing = {
            "prepare": round(prepared_at - start, 3),
            "generation_and_save": round(generated_at - prepared_at, 3),
            "publication": round(time.monotonic() - generated_at, 3),
        }
        log.info(
            "arv2.reconciliation.completed",
            generation_id=str(generation_id),
            revision=revision,
            updated_sections=len(updates),
            elapsed_seconds=elapsed,
            target_missed=elapsed > 60,
            timing_seconds=timing,
            supplied_claims=len(packet["input"]["claims"]),
            changed_claims=len(packet["input"]["changed"]),
        )
        return {
            "updated_sections": len(updates),
            "input_revision": revision,
            "elapsed_seconds": round(elapsed, 3),
            "timing_seconds": timing,
            "execution_id": str(execution_id_for(generation_id, revision)),
            "packet_key": row["packet_key"],
            "response_key": row["response_key"],
        }
