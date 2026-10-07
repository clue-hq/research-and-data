"""Production side of the separate page writer (recipe 25+).

Everything the writer reads is loaded here from durable rows — the imported JSON dossiers, the
committee, the pinned seller context — so a first write and a later rewrite see the same facts.
The model call goes through the ARV2 provider caller: a Langfuse generation per call and a
``provider_call_ledger`` row stamped with the research job, so the writer's spend counts in the
job's cost like every other call. Pages publish through :func:`publish_page`, the one write path
into display blocks, under the writer's own ``execution`` row (its reply retained as the
parameter artifact).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.page_writer import (
    GUIDE_VERSION,
    ModelCall,
    WrittenPages,
    account_system,
    contact_system,
    seller_brief_request,
    seller_brief_system,
    write_account_pages,
    write_contact_page,
)
from clue_api.arv2.page_writer_view import Person
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.quality_context import read_context, read_document
from clue_api.arv2.quality_generation import reconcile_generation
from clue_api.arv2.quality_json_dossier import read_json_dossier
from clue_api.arv2.quality_page_inputs import page_inputs
from clue_api.arv2.quality_pages import PageDraft, publish_page
from clue_api.arv2.quality_person_release import read_parent_dossier
from clue_api.arv2.quality_policy import SEPARATE_WRITER_RECIPE, writes_pages_separately
from clue_api.arv2.quality_recipe import RECIPE_26, at_least
from clue_api.arv2.quality_relationships import read_committee
from clue_api.arv2.transport import HttpxTransport
from clue_api.execution_wiring import ExecutionRunEventWriter
from clue_config import GatewayConfig, Secrets, Settings
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

__all__ = [
    "SEPARATE_WRITER_RECIPE",
    "PageWriterModels",
    "page_writer_models",
    "provider_model_call",
    "publish_written",
    "rewrite_account_pages",
    "write_job_pages",
    "write_pages",
    "writer_model_id",
    "writes_pages_separately",
]

log = get_logger(__name__)

_BRIEF_KIND = "research_seller_brief"
_WRITER_KIND = "research_page_writer"


def writer_model_id(settings: Settings) -> str:
    """The research-narrative role's model; an env change, never a code change."""
    return (
        os.environ.get("RESEARCH_NARRATIVE_AGENT_MODEL", "").strip() or settings.arv2_display_model
    )


def writer_effort() -> str | None:
    return os.environ.get("RESEARCH_NARRATIVE_AGENT_MODEL_EFFORT", "").strip() or None


def provider_model_call(
    *,
    settings: Settings,
    secrets: Secrets,
    scope: JobScope,
    artifacts: ArtifactSink | None,
    conn_factory: ConnFactory,
    purpose: str,
) -> ModelCall:
    """A :data:`ModelCall` that bills the research job and traces each call in Langfuse."""
    api_key = secrets.openrouter_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise RuntimeError("the page writer needs CLUE_OPENROUTER_API_KEY")
    model = writer_model_id(settings)
    effort = writer_effort()

    async def call(messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
        )
        request = openrouter_chat_request(
            base_url=GatewayConfig().base_url,
            api_key=api_key,
            model=model,
            messages=[dict(m) for m in messages],
            response_format={"type": "json_object"} if json_mode else None,
            reasoning={"effort": effort} if effort else None,
            timeout_s=settings.arv2_page_writer_timeout_s,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=f"page-writer-{purpose}-{GUIDE_VERSION}",
            request=request,
            estimate=SpendEstimate(usd=Decimal("0.20")),
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={
                "job_id": str(scope.job_id),
                "workspace_id": scope.workspace_id,
                "purpose": f"page_writer:{purpose}",
            },
        )
        hop = asyncio.create_task(asyncio.to_thread(caller.call, spec))
        try:
            try:
                result = await asyncio.shield(hop)
            except asyncio.CancelledError:
                # A dispatched request is billed; keep its ledger row and start nothing new.
                await hop
                raise
        finally:
            async with conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=artifacts,
                    stamp=LedgerStamp(
                        workspace_id=scope.workspace_id,
                        project_id=scope.project_id,
                        job_id=scope.job_id,
                    ),
                )
        return openrouter_message_text(result.json())

    return call


def _guides_sha() -> str:
    body = "\n".join([seller_brief_system(), account_system(), contact_system(), GUIDE_VERSION])
    return hashlib.sha256(body.encode()).hexdigest()


async def _retain_json(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    kind: str,
    reference_id: str,
    value: Any,
    subjects: Sequence[UUID] = (),
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
        reference_kind=kind,
        reference_id=reference_id,
    )
    await conn.execute(
        text("""INSERT INTO agent_artifact_project
        (workspace_id,project_id,artifact_key,binding_kind)
        VALUES(:ws,:project,:key,:kind) ON CONFLICT DO NOTHING"""),
        {"ws": scope.workspace_id, "project": scope.project_id, "key": key, "kind": kind},
    )
    # Bound to every subject it describes, so erasing a person reaches the writer's reply too.
    for subject in subjects:
        await conn.execute(
            text("""INSERT INTO agent_artifact_subject
            (workspace_id,artifact_key,subject_entity_id,binding_kind)
            VALUES(:ws,:key,:subject,'derived') ON CONFLICT DO NOTHING"""),
            {"ws": scope.workspace_id, "key": key, "subject": subject},
        )
    return key


async def seller_brief(
    conn_factory: ConnFactory,
    storage: StorageBackend,
    model: ModelCall,
    *,
    scope: JobScope,
    context_id: UUID,
) -> str:
    """The project's seller brief: written once per context pin and guide version, then reused."""
    reference_id = f"{context_id}:{_guides_sha()[:16]}"
    async with conn_factory() as conn:
        key = (
            await conn.execute(
                text("""SELECT storage_key FROM artifact_reference WHERE workspace_id=:ws
                AND reference_kind=:kind AND reference_id=:ref ORDER BY storage_key LIMIT 1"""),
                {"ws": scope.workspace_id, "kind": _BRIEF_KIND, "ref": reference_id},
            )
        ).scalar_one_or_none()
        if key is not None:
            _, raw = await read_verified_artifact(
                conn, storage, workspace_id=scope.workspace_id, storage_key=key
            )
            return str(json.loads(raw)["brief"])
        context = await read_context(
            conn,
            storage,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            context_id=context_id,
        )
        documents = [
            (
                pin.kind,
                pin.path,
                await read_document(conn, storage, workspace_id=scope.workspace_id, pin=pin),
            )
            for pin in context.documents()
        ]
    request = seller_brief_request(
        seller_name=context.seller_name,
        products=context.products,
        gaps=context.gaps,
        documents=documents,
    )
    brief = (
        await model(
            [
                {"role": "system", "content": seller_brief_system()},
                {"role": "user", "content": request},
            ],
            False,
        )
    ).strip()
    if not brief:
        raise RuntimeError("the seller brief came back empty")
    async with conn_factory() as conn:
        await _retain_json(
            conn,
            storage,
            scope,
            kind=_BRIEF_KIND,
            reference_id=reference_id,
            value={"brief": brief, "context_id": str(context_id), "guides": _guides_sha()},
        )
    return brief


async def _dossier_for_job(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, job_id: UUID
) -> dict[str, Any] | None:
    """A job's imported dossier, or ``None`` until its import is complete."""
    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference
            WHERE workspace_id=:ws AND reference_kind='research_json_dossier'
              AND reference_id LIKE :prefix ORDER BY reference_id DESC LIMIT 1"""),
            {"ws": workspace_id, "prefix": f"{job_id}:%"},
        )
    ).scalar_one_or_none()
    if key is None:
        return None
    _, raw = await read_verified_artifact(conn, storage, workspace_id=workspace_id, storage_key=key)
    saved = json.loads(raw)
    if saved.get("job_id") != str(job_id) or saved.get("state") != "complete":
        return None
    return dict(saved)


async def _title(conn: AsyncConnection, workspace_id: str, contact_id: UUID) -> str | None:
    value = (
        await conn.execute(
            text("""SELECT value_json FROM claim WHERE workspace_id=:ws AND entity_id=:id
            AND field_key='contact.current_title' AND superseded_by IS NULL
            ORDER BY collected_at DESC LIMIT 1"""),
            {"ws": workspace_id, "id": contact_id},
        )
    ).scalar_one_or_none()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    return value if isinstance(value, str) else None


async def committee_people(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, context_id: UUID
) -> list[Person]:
    """The account's people: its committee, then anyone else this run researched for it.

    Each carries their dossier once their own research has imported.
    """
    members = await read_committee(
        conn, workspace_id=scope.workspace_id, account_id=scope.account_id, context_id=context_id
    )
    jobs = {
        row.subject_entity_id: row.job_id
        for row in (
            await conn.execute(
                # This run's people, plus people launched on their own who joined this account
                # job's research (attach_to_account_research); the newest job per person wins.
                text("""SELECT j.subject_entity_id,j.job_id FROM arv2_research_job j
                WHERE j.workspace_id=:ws AND j.account_entity_id=:account
                  AND j.subject_type='person' AND (j.run_id=:run OR EXISTS (
                    SELECT 1 FROM arv2_generation_child c
                    JOIN arv2_account_research_generation g
                      ON g.generation_id=c.generation_id AND g.workspace_id=c.workspace_id
                    WHERE c.job_id=j.job_id AND c.workspace_id=j.workspace_id
                      AND g.initial_job_id=:account_job))
                ORDER BY j.created_at"""),
                {
                    "ws": scope.workspace_id,
                    "run": scope.run_id,
                    "account": scope.account_id,
                    "account_job": scope.job_id,
                },
            )
        ).all()
    }
    roles: dict[UUID, str | None] = {
        m.contact_id: m.proposed_role.replace("_", " ") or None
        for m in members
        if m.state != "excluded"
    }
    excluded = {m.contact_id for m in members if m.state == "excluded"}
    for contact_id in jobs:
        if contact_id not in roles and contact_id not in excluded:
            roles[contact_id] = None
    people = []
    for contact_id, role in roles.items():
        name = (
            await conn.execute(
                text("SELECT full_name FROM contact_entity WHERE id=:id AND workspace_id=:ws"),
                {"id": contact_id, "ws": scope.workspace_id},
            )
        ).scalar_one_or_none()
        job_id = jobs.get(contact_id)
        people.append(
            Person(
                contact_id=contact_id,
                name=name or "Unnamed contact",
                title=await _title(conn, scope.workspace_id, contact_id),
                suggested_role=role,
                dossier=(
                    await _dossier_for_job(
                        conn, storage, workspace_id=scope.workspace_id, job_id=job_id
                    )
                    if job_id is not None
                    else None
                ),
            )
        )
    return people


async def _account_dossier_for_person(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, context_id: UUID
) -> dict[str, Any]:
    """The account findings a contact page may use.

    A person released by an account job reads that parent's import. A person launched on its own
    (no parent) reads the newest completed account dossier for the same account, project and
    research context; with none, the page is written from the person's own findings alone.
    """
    if (scope.input_refs or {}).get("parent_job_id"):
        try:
            return await read_parent_dossier(conn, storage, scope, context_id)
        except ValueError:
            # Recipe 26: a contact page written at the account's final step whose account never
            # imported is written from the person's own findings.
            if not at_least(scope, RECIPE_26):
                raise
            return {}
    jobs = (
        await conn.execute(
            text("""SELECT j.job_id FROM arv2_research_job j
            JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
            WHERE j.workspace_id=:ws AND j.account_entity_id=:account AND j.subject_type='account'
              AND r.project_id=:project AND r.context_id=:context
            ORDER BY j.created_at DESC"""),
            {
                "ws": scope.workspace_id,
                "account": scope.account_id,
                "project": scope.project_id,
                "context": context_id,
            },
        )
    ).scalars()
    for job_id in jobs:
        saved = await _dossier_for_job(
            conn, storage, workspace_id=scope.workspace_id, job_id=job_id
        )
        if saved is not None and (saved.get("receipt") or {}).get("complete"):
            return saved
    return {}


async def account_story(conn: AsyncConnection, scope: JobScope, context_id: UUID) -> str:
    """The account's current short version: the opening of Overview › Why they fit."""
    body = (
        await conn.execute(
            text("""SELECT body_json FROM display_block WHERE workspace_id=:ws
            AND project_id=:project AND context_id=:context AND subject_kind='account'
            AND subject_id=:account AND page='overview' AND section_key='why-they-fit'
            AND superseded_at IS NULL ORDER BY generated_at DESC LIMIT 1"""),
            {
                "ws": scope.workspace_id,
                "project": scope.project_id,
                "context": context_id,
                "account": scope.account_id,
            },
        )
    ).scalar_one_or_none()
    intro = (body or {}).get("intro") or []
    return " ".join(str(s.get("text") or "") for s in intro if isinstance(s, Mapping)).strip()


async def write_pages(
    model: ModelCall,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    *,
    scope: JobScope,
    context_id: UUID,
) -> WrittenPages:
    """Write (not publish) this job's pages from its durable inputs."""
    brief = await seller_brief(conn_factory, storage, model, scope=scope, context_id=context_id)
    async with conn_factory() as conn:
        own = await read_json_dossier(conn, storage, scope, context_id)
        if scope.person_subject_id is not None:
            parent = await _account_dossier_for_person(conn, storage, scope, context_id)
            story = await account_story(conn, scope, context_id)
        else:
            people = await committee_people(conn, storage, scope, context_id)
    if scope.person_subject_id is not None:
        return await write_contact_page(
            model,
            seller_brief=brief,
            account_name=scope.account_name,
            account_story=story,
            person=Person(
                contact_id=scope.person_subject_id,
                name=scope.person_name or "Unnamed contact",
                title=scope.person_title or None,
                suggested_role=None,
                dossier=own,
            ),
            account_dossier=parent,
        )
    return await write_account_pages(
        model,
        seller_brief=brief,
        account_name=scope.account_name,
        account_dossier=own,
        people=people,
    )


async def _event(conn: AsyncConnection, execution_id: UUID, event: ExecutionEventType) -> None:
    eid = ExecutionId(execution_id)
    cursor = await get_cursor(conn, eid)
    await DbExecutionJournal(transport=ExecutionRunEventWriter()).append_event(
        conn,
        execution_id=eid,
        event_type=event,
        actor="system",
        expected_state_version=cursor.state_version,
        payload={"purpose": "research_page_writer"},
    )


async def publish_written(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    context_id: UUID,
    written: WrittenPages,
    model_id: str,
    input_sha256: str | None = None,
) -> tuple[UUID, ...]:
    """Publish written pages under the writer's own execution, in the caller's transaction.

    ``input_sha256`` (the writer request's hash) is kept with the reply, so a later write from
    identical input can be skipped.
    """
    reply = json.dumps(written.result, sort_keys=True, default=str)
    execution_id = uuid5(
        NAMESPACE_URL,
        f"page-writer:{scope.job_id}:{context_id}:{hashlib.sha256(reply.encode()).hexdigest()}",
    )
    subjects: set[UUID] = {scope.person_subject_id or scope.account_id}
    subjects |= {
        id
        for sections in written.drafts.values()
        for section in sections
        for item in section.items
        for id in item.contact_ids
    }
    key = await _retain_json(
        conn,
        storage,
        scope,
        kind=_WRITER_KIND,
        reference_id=f"{scope.job_id}:{execution_id}",
        value={
            "result": written.result,
            "attempts": written.attempts,
            "guides": _guides_sha(),
            **({"input_sha256": input_sha256} if input_sha256 else {}),
        },
        subjects=sorted(subjects),
    )
    inserted = (
        await conn.execute(
            text("""INSERT INTO execution
            (id,workspace_id,project_id,started_by,parameter_artifact_key,
             parameter_manifest_hash,pin_manifest_hash)
            VALUES(:id,:ws,:project,'system',:key,:sha,:pin)
            ON CONFLICT (id) DO NOTHING RETURNING id"""),
            {
                "id": execution_id,
                "ws": scope.workspace_id,
                "project": scope.project_id,
                "key": key,
                "sha": key.rsplit("/", 1)[-1],
                "pin": _guides_sha(),
            },
        )
    ).scalar_one_or_none()
    if inserted is not None:
        await conn.execute(
            text("INSERT INTO execution_cursor(execution_id,status) VALUES(:id,'queued')"),
            {"id": execution_id},
        )
        await _event(conn, execution_id, ExecutionEventType.EXECUTION_STARTED)
    ids: list[UUID] = []
    for page, sections in written.drafts.items():
        inputs = await page_inputs(conn, scope, context_id=context_id, page=page)
        ids.extend(
            await publish_page(
                conn,
                storage,
                scope,
                context_id=context_id,
                execution_id=execution_id,
                model=model_id,
                draft=PageDraft(
                    page=page, expected_dependency_sha256=inputs.sha256, sections=sections
                ),
            )
        )
    if inserted is not None:
        await _event(conn, execution_id, ExecutionEventType.EXECUTION_COMPLETED)
    return tuple(ids)


@dataclass(frozen=True)
class PageWriterModels:
    """The writer's model, composed once per worker: a per-job call factory and its model id."""

    call_for: Callable[[JobScope], ModelCall]
    model_id: str


def page_writer_models(
    *,
    settings: Settings,
    secrets: Secrets,
    artifacts: ArtifactSink | None,
    conn_factory: ConnFactory,
) -> PageWriterModels:
    def call_for(scope: JobScope) -> ModelCall:
        return provider_model_call(
            settings=settings,
            secrets=secrets,
            scope=scope,
            artifacts=artifacts,
            conn_factory=conn_factory,
            purpose="contact" if scope.person_subject_id is not None else "account",
        )

    return PageWriterModels(call_for=call_for, model_id=writer_model_id(settings))


class _Unchanged(Exception):
    """The writer request is identical to the one behind the job's newest pages."""


def _input_sha256(messages: Sequence[Mapping[str, str]]) -> str:
    system, user = messages[0]["content"], messages[1]["content"]
    return hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()


async def _last_input_sha256(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope
) -> str | None:
    """The request hash kept with this job's newest written pages, if any."""
    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference WHERE workspace_id=:ws
            AND reference_kind=:kind AND reference_id LIKE :job||':%'
            ORDER BY created_at DESC, storage_key DESC LIMIT 1"""),
            {"ws": scope.workspace_id, "kind": _WRITER_KIND, "job": str(scope.job_id)},
        )
    ).scalar_one_or_none()
    if key is None:
        return None
    _, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=key
    )
    value = json.loads(raw).get("input_sha256")
    return str(value) if value else None


async def write_job_pages(
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    models: PageWriterModels,
    after_publish: Callable[[AsyncConnection], Awaitable[None]] | None = None,
) -> tuple[UUID, ...]:
    """Write and publish this job's pages once its research has settled. Raises on failure.

    ``after_publish`` runs in the publishing transaction, so bookkeeping that depends on the
    pages (settling an account generation) commits with them or not at all.
    """
    ids, _ = await _write_job_pages(
        conn_factory=conn_factory,
        storage=storage,
        scope=scope,
        context_id=context_id,
        models=models,
        after_publish=after_publish,
    )
    return ids


async def _write_job_pages(
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    models: PageWriterModels,
    after_publish: Callable[[AsyncConnection], Awaitable[None]] | None = None,
    skip_if_unchanged: bool = False,
) -> tuple[tuple[UUID, ...], bool]:
    """``write_job_pages``, also reporting whether it skipped an unchanged write.

    With ``skip_if_unchanged`` (recipe 26), the first writer request is hashed before it is sent;
    when it equals the hash kept with the job's newest pages, no model call is made, the pages
    stay as they are and ``after_publish`` still runs.
    """
    subject = "contact" if scope.person_subject_id is not None else "account"
    previous: str | None = None
    if skip_if_unchanged:
        async with conn_factory() as conn:
            previous = await _last_input_sha256(conn, storage, scope)
    hashed: list[str] = []
    model = models.call_for(scope)

    async def watched(messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        # The first page request (the seller brief is prose; repairs carry the reply).
        if json_mode and len(messages) == 2 and not hashed:
            hashed.append(_input_sha256(messages))
            if previous is not None and hashed[0] == previous:
                raise _Unchanged
        return await model(messages, json_mode)

    with observation(
        "research.page_writer",
        as_type="span",
        metadata={
            "workspace_id": scope.workspace_id,
            "job_id": str(scope.job_id),
            "subject": subject,
        },
    ):
        try:
            written = await write_pages(
                watched, conn_factory, storage, scope=scope, context_id=context_id
            )
        except _Unchanged:
            if after_publish is not None:
                async with conn_factory() as conn:
                    await after_publish(conn)
            log.info("arv2.page_writer.unchanged", job_id=str(scope.job_id), subject=subject)
            return (), True
        async with conn_factory() as conn:
            ids = await publish_written(
                conn,
                storage,
                scope,
                context_id=context_id,
                written=written,
                model_id=models.model_id,
                input_sha256=hashed[0] if hashed else None,
            )
            if after_publish is not None:
                await after_publish(conn)
    log.info(
        "arv2.page_writer.published",
        job_id=str(scope.job_id),
        subject=subject,
        pages=sorted(written.drafts),
        blocks=len(ids),
        attempts=written.attempts,
    )
    return ids, False


async def rewrite_account_pages(
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    generation_id: UUID,
    revision: int,
    models: PageWriterModels,
    deferred: Sequence[JobScope] = (),
) -> dict[str, Any]:
    """Rewrite the account's pages once its people have settled, and settle that revision.

    Recipe 26: this is the generation's one final page step. It first writes the ``deferred``
    contact pages (people who finished before the account imported), together, then the
    account's pages; each write is skipped when its request is identical to the last one. A
    contact page that fails is logged and settles the revision ``needs_review``.

    A full rewrite, not an edit: the writer reads the account dossier, the committee and every
    finished person dossier from durable rows, so later findings reach the story and the
    sections the same way the first write's findings did.

    An account whose own research never imported (it failed before ``finish_dossier``) has
    nothing to write from: the revision settles ``needs_review`` and its pages stay as they are,
    rather than being replaced by a page of gaps.
    """
    async with conn_factory() as conn:
        own = await read_json_dossier(conn, storage, scope, context_id)
        if own.get("state") != "complete":
            applied = await reconcile_generation(
                conn,
                workspace_id=scope.workspace_id,
                generation_id=generation_id,
                expected_revision=revision,
                processed_snapshot=True,
                needs_review=True,
            )
            return {
                "generation_id": str(generation_id),
                "input_revision": revision,
                "applied": applied,
                "skipped": "account_dossier_not_imported",
            }
    final_step = at_least(scope, RECIPE_26)
    contacts = await asyncio.gather(
        *(
            _write_job_pages(
                conn_factory=conn_factory,
                storage=storage,
                scope=person,
                context_id=context_id,
                models=models,
                skip_if_unchanged=final_step,
            )
            for person in deferred
        ),
        return_exceptions=True,
    )
    failed = 0
    for person, outcome in zip(deferred, contacts, strict=True):
        if isinstance(outcome, asyncio.CancelledError):
            raise outcome
        if isinstance(outcome, BaseException):
            failed += 1
            log.error(
                "arv2.page_writer.deferred_contact_failed",
                job_id=str(person.job_id),
                error=type(outcome).__name__,
            )
    applied = False

    async def settle(conn: AsyncConnection) -> None:
        nonlocal applied
        applied = await reconcile_generation(
            conn,
            workspace_id=scope.workspace_id,
            generation_id=generation_id,
            expected_revision=revision,
            processed_snapshot=True,
            needs_review=bool(failed),
        )

    ids, unchanged = await _write_job_pages(
        conn_factory=conn_factory,
        storage=storage,
        scope=scope,
        context_id=context_id,
        models=models,
        after_publish=settle,
        skip_if_unchanged=final_step,
    )
    return {
        "generation_id": str(generation_id),
        "input_revision": revision,
        "applied": applied,
        "blocks": len(ids),
        "unchanged": unchanged,
        "contact_pages": len(deferred) - failed,
        "contact_page_failures": failed,
    }
