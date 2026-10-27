"""Real substrate tests with explicit offline provider fixtures; no paid calls."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.arv2 import account_research_store as store
from clue_api.arv2 import research_operations as ops
from clue_api.arv2.account_research_catalog import arv2_person_profile_sha256
from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.account_research_tools import (
    FinalizeResearchArgs,
    ToolRuntime,
    _finalize_research,
)
from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.committee_discovery import (
    DiscoverPeopleArgs,
    EnrichContactArgs,
    ReadPeopleResultArgs,
    company_lock,
    discover_people,
    enrich_contact,
    load_person_seed,
    read_people_result,
)
from clue_api.arv2.committee_step import run_committee_step
from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.gemini_media_client import MediaBudget
from clue_api.arv2.quality_provider_tools import AcquireResearchTool
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_config import Settings
from clue_core import EntityId
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.identity import insert_contact_entity
from clue_research.identity.provider import (
    erase_provider_evidence,
)
from clue_storage import (
    ArtifactIntegrityError,
    artifact_key,
    content_address,
    purge_erased_artifacts,
    record_artifact,
)
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.arv2.test_committee_discovery_v2 import person
from tests.arv2.test_committee_step_db import COMMITTEE_CATALOG, _scope, _seed
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


class Artifacts:
    def __init__(self, conn, storage):
        self.conn, self.storage = conn, storage

    async def persist_body(self, *, workspace_id, data, media_type):
        sha = content_address(data)
        key = artifact_key(workspace_id, sha)
        await record_artifact(
            self.conn,
            storage_key=key,
            workspace_id=workspace_id,
            content_sha256=sha,
            media_type=media_type,
            size_bytes=len(data),
        )
        await self.storage.put(key, data, media_type=media_type)
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=key,
            sha256=sha,
            media_type=media_type,
            byte_count=len(data),
        )


class Clients:
    def ai_ark(self, caller):
        return AiArkClient(caller, SecretStr("fixture"), min_gap_s=0)

    def exa(self, caller):
        return ExaClient(caller, SecretStr("fixture"))


def factory(conn):
    lock = asyncio.Lock()

    @asynccontextmanager
    async def connection():
        async with lock:
            yield conn

    return connection


def runtime(conn, scope, storage, wire):
    return ToolRuntime(
        scope=scope,
        settings=Settings(arv2_ai_ark_min_gap_s=0),
        clients=Clients(),
        conn_factory=factory(conn),
        artifacts=Artifacts(conn, storage),
        storage=storage,
        writer=LenientClaimWriter(lenient=True),
        catalog=COMMITTEE_CATALOG,
        media_budget=MediaBudget(100),
        transport_factory=lambda: wire,
    )


def response(body, status=200):
    return HttpResponse(status=status, body=json.dumps(body).encode())


async def ready_account(conn, *, no_linkedin=False, catalog_version="v2"):
    run, account, job_id = await _seed(conn)
    scope = replace(_scope(run, account), job_id=job_id, catalog_version=catalog_version)
    storage = _MemoryStorage()
    candidate = person(linkedin=not no_linkedin)
    candidate["profile"]["headline"] = "PROVIDER_PROMO"
    candidate["company"]["summary"]["description"] = "PROVIDER_PROMO"
    wire = ScriptedTransport(
        [
            response(
                {
                    "content": [
                        {
                            "id": "company-1",
                            "link": {"domain": "probook.ai"},
                            "summary": {"name": "Probook"},
                        }
                    ]
                }
            ),
            response(
                {
                    "content": [candidate, person("p2", "Other Test")],
                    "last": False,
                    "totalPages": 2,
                    "totalElements": 3,
                }
            ),
        ]
    )
    rt = runtime(conn, scope, storage, wire)
    deep, _ = await ops.begin(
        conn, rt.operation_scope, "account_deep", {"fixture": "failed after retry"}
    )
    await conn.execute(
        text(
            "UPDATE arv2_research_operation SET "
            "state='failed',error_code='retry_exhausted' WHERE operation_id=:id"
        ),
        {"id": deep.operation_id},
    )
    result = await discover_people(
        rt,
        DiscoverPeopleArgs(
            role_key="growth", rationale="Owns demand generation", titles=["VP Marketing"]
        ),
    )
    return run, account, rt, storage, wire, result


@pytest.mark.parametrize("catalog_version", ["v2", "v3"])
def test_full_handoff_profile_reuse_channels_and_replay(catalog_version):
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, wire, result = await ready_account(
                conn, no_linkedin=True, catalog_version=catalog_version
            )
            assert len(wire.requests) == 2
            again = await discover_people(
                rt,
                DiscoverPeopleArgs(
                    role_key="sponsor", rationale="May own the budget", titles=["vp marketing"]
                ),
            )
            assert result["result_ref"] == again["result_ref"] and len(wire.requests) == 2
            details = await read_people_result(
                rt, ReadPeopleResultArgs(result_ref=result["result_ref"])
            )
            assert "birth_date" not in details["people"][0]["profile"]["profile"]
            assert "PROVIDER_PROMO" not in json.dumps(details)
            candidate = {
                "evidence_kind": "provider_candidate",
                "candidate_ref": result["people"][0]["candidate_ref"],
                "persona": "champion",
                "rationale": "Owns marketing operations",
            }
            await _finalize_research(
                rt,
                FinalizeResearchArgs(
                    summary="The researched company needs marketing support.",
                    committee_candidates=[candidate, candidate],
                    gaps=["Account Exa exhausted its retry"],
                ),
            )
            candidates = await ops.selected_candidates(conn, rt.operation_scope)
            assert len(candidates) == 1 and candidates[0]["name"] == "Dana Test"
            job = await store.read_job(conn, job_id=rt.scope.job_id)
            assert len(job.selection_claim_ids) == 1
            step = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=rt.scope,
                candidates=candidates,
                writer=rt._writer,
                catalog=COMMITTEE_CATALOG,
                person_profile_sha256=arv2_person_profile_sha256(version=catalog_version),
                person_profile_ref=f"agent-profile:arv2-person:{catalog_version}",
            )
            assert not step.skipped and len(step.jobs) == 1
            child = await store.read_job(conn, job_id=step.jobs[0].job_id)
            assert child.profile_ref == f"agent-profile:arv2-person:{catalog_version}"
            assert set(child.input_refs) == {"version", "candidate_ref", "parent_job_id"}
            person_scope = replace(
                rt.scope,
                job_id=child.job_id,
                subject_kind="person",
                contact_id=EntityId(child.subject_entity_id),
                person_name="Dana Test",
                person_title="VP Marketing",
                input_refs=child.input_refs,
            )
            person_wire = ScriptedTransport(
                [
                    response(
                        {
                            "id": "p1",
                            "email": {
                                "output": [
                                    {
                                        "address": "dana@example.test",
                                        "found": True,
                                        "status": "VALID",
                                        "domainType": "SMTP",
                                    }
                                ]
                            },
                        }
                    ),
                ]
            )
            prt = runtime(conn, person_scope, storage, person_wire)
            await load_person_seed(prt)
            assert "PROVIDER_PROMO" not in json.dumps(prt.person_seed)
            assert not person_wire.requests
            channels = await enrich_contact(prt, EnrichContactArgs())
            assert set(channels) == {"email"}
            assert channels["email"]["state"] == "succeeded"
            assert len(person_wire.requests) == 1
            await enrich_contact(prt, EnrichContactArgs())
            assert len(person_wire.requests) == 1
            claims = await claims_for(
                conn, person_scope.contact_id, scope=WorkspaceScope.for_workspace(run.workspace_id)
            )
            keys = {c.field_key for c in claims}
            assert {"core.work_email", "contact.current_title"} <= keys
            assert "core.direct_phone" not in keys
            assert all(
                c.artifact_key
                for c in claims
                if c.field_key in {"core.work_email", "core.direct_phone"}
            )
            # Repeat settlement reuses contact/job. No second person row or channel purchases.
            repeat = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=rt.scope,
                candidates=candidates,
                writer=rt._writer,
                catalog=COMMITTEE_CATALOG,
                person_profile_sha256=child.profile_sha256,
                person_profile_ref=child.profile_ref,
            )
            assert repeat.jobs == step.jobs and repeat.contacts_created == ()

    run_async(scenario())


def test_ordering_scope_empty_unknown_and_erased_pages():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, wire, result = await ready_account(conn)
            # Unselected candidate is still discoverable to erasure through its LinkedIn.
            other = await insert_contact_entity(
                conn,
                account_entity_id=EntityId(account),
                full_name="Other Test",
                linkedin_url="https://linkedin.com/in/p2",
            )
            keys = await erase_provider_evidence(
                conn, workspace_id=run.workspace_id, contact_id=other
            )
            assert keys
            with pytest.raises(ArtifactIntegrityError, match="erased"):
                await read_people_result(rt, ReadPeopleResultArgs(result_ref=result["result_ref"]))
            # Purge whole shared pages despite surviving candidates; never resurrect deleted data.
            purged = await purge_erased_artifacts(conn, storage, keys=tuple(keys))
            assert purged.purged_keys
            fresh = replace(rt.operation_scope, workspace_id="another-workspace")
            with pytest.raises(RefusalError, match="belong"):
                await ops.get(conn, fresh, result["result_ref"])
            op, won = await ops.begin(
                conn, rt.operation_scope, "contact_email", {"id": "uncertain"}
            )
            assert won
            await conn.execute(
                text(
                    "UPDATE arv2_research_operation SET lease_until=now()-interval '1 "
                    "second' WHERE operation_id=:id"
                ),
                {"id": op.operation_id},
            )
            replay, won = await ops.begin(
                conn, rt.operation_scope, "contact_email", {"id": "uncertain"}
            )
            assert not won and replay.state == "unknown"
            with pytest.raises(RefusalError, match="unknown"):
                await ops.body(conn, storage, rt.operation_scope, replay.operation_id)
            assert len(wire.requests) == 2

    run_async(scenario())


def test_search_before_account_deep_spends_nothing():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v2")
            wire = ScriptedTransport([])
            rt = runtime(conn, scope, _MemoryStorage(), wire)
            with pytest.raises(RefusalError, match="research_deep"):
                await discover_people(
                    rt,
                    DiscoverPeopleArgs(
                        role_key="growth", rationale="Relevant role", titles=["CMO"]
                    ),
                )
            assert not wire.requests

    run_async(scenario())


def test_recipe_27_searches_people_in_the_opening_rounds_before_account_deep():
    """Recipe 27 aligns the tool with the prompt: people search no longer waits for deep research
    (run 4, 2026-10-10: the prompt said "opening rounds", the tool refused, the agent nominated from
    web results instead)."""

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(
                _scope(run, account),
                job_id=job_id,
                catalog_version="v2",
                input_refs={"quality_recipe_version": 27},
            )
            wire = ScriptedTransport(
                [
                    response(
                        {
                            "content": [
                                {
                                    "id": "company-1",
                                    "link": {"domain": "probook.ai"},
                                    "summary": {"name": "Probook"},
                                }
                            ]
                        }
                    ),
                    response(
                        {"content": [person()], "last": True, "totalPages": 1, "totalElements": 1}
                    ),
                ]
            )
            rt = runtime(conn, scope, _MemoryStorage(), wire)
            result = await discover_people(
                rt,
                DiscoverPeopleArgs(role_key="growth", rationale="Relevant role", titles=["CMO"]),
            )
            assert result["returned"] == 1
            assert len(wire.requests) == 2

    run_async(scenario())


def test_deep_retry_replays_the_chosen_response_not_the_last_attempt():
    from clue_api.arv2.account_research_tools import ResearchDeepArgs, _research_deep

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v2")
            richer = "A useful but thin report. " * 40
            wire = ScriptedTransport(
                [
                    response({"output": {"content": {"report": richer}}, "results": []}),
                    response({"output": {"content": {"report": "thin"}}, "results": []}),
                ]
            )
            rt = runtime(conn, scope, _MemoryStorage(), wire)
            args = ResearchDeepArgs(charter="Research the target company against its ICP. " * 6)
            result = await _research_deep(rt, args)
            assert result["report"] == richer and len(wire.requests) == 2
            replay = await _research_deep(rt, args)
            assert replay["report"] == richer and len(wire.requests) == 2
            assert await ops.deep_attempted(conn, rt.operation_scope)

    run_async(scenario())


def test_forged_candidate_tampered_artifact_and_unfilled_role():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, wire, result = await ready_account(conn)
            with pytest.raises(RefusalError, match="absent"):
                await _finalize_research(
                    rt,
                    FinalizeResearchArgs(
                        summary="Company research has completed successfully.",
                        committee_candidates=[
                            {
                                "evidence_kind": "provider_candidate",
                                "candidate_ref": result["result_ref"] + ":forged",
                                "persona": "champion",
                            }
                        ],
                    ),
                )
            assert (await store.read_job(conn, job_id=rt.scope.job_id)).selection_claim_ids is None
            op = await ops.get(conn, rt.operation_scope, result["result_ref"])
            original = storage.blobs[op.artifact_key]
            storage.blobs[op.artifact_key] = b"tampered"
            with pytest.raises(ArtifactIntegrityError):
                await read_people_result(rt, ReadPeopleResultArgs(result_ref=result["result_ref"]))
            storage.blobs[op.artifact_key] = original
            await _finalize_research(
                rt,
                FinalizeResearchArgs(
                    summary="We did not establish a technical evaluator.",
                    committee_candidates=[
                        {
                            "evidence_kind": "unfilled_role",
                            "role_key": "technical",
                            "gap_reason": "No relevant results",
                            "persona": "technical_evaluator",
                        }
                    ],
                ),
            )
            selected = await ops.selected_candidates(conn, rt.operation_scope)
            assert selected[0]["vacant_seat"] is False and not selected[0].get("name")

    run_async(scenario())


def test_distinct_provider_people_with_same_name_are_not_merged():
    from clue_research.identity.provider import resolve_provider_contact

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, wire, result = await ready_account(conn, no_linkedin=True)
            op = await ops.get(conn, rt.operation_scope, result["result_ref"])
            first, _ = await resolve_provider_contact(
                conn,
                workspace_id=run.workspace_id,
                account_id=EntityId(account),
                provider="ai_ark",
                subject_id="p1",
                name="Same Name",
                linkedin_url=None,
                artifact_key=op.artifact_key,
            )
            second, _ = await resolve_provider_contact(
                conn,
                workspace_id=run.workspace_id,
                account_id=EntityId(account),
                provider="ai_ark",
                subject_id="p2",
                name="Same Name",
                linkedin_url=None,
                artifact_key=op.artifact_key,
            )
            assert first != second
            assert (
                await resolve_provider_contact(
                    conn,
                    workspace_id=run.workspace_id,
                    account_id=EntityId(account),
                    provider="ai_ark",
                    subject_id="p1",
                    name="Same Name",
                    linkedin_url=None,
                    artifact_key=op.artifact_key,
                )
            )[0] == first

    run_async(scenario())


def test_persona_pin_survives_latest_document_change_and_names_unknown_lineage():
    from clue_api.arv2.research_context import pin_persona, read_persona_pin
    from tests.arv2.test_account_research_driver_db import _register_document

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, _, _ = await _seed(conn)
            storage = _MemoryStorage()
            key, _ = await _register_document(
                conn,
                storage,
                workspace_id=run.workspace_id,
                brand_id=run.brand_id,
                path="audience/persona-test.md",
                kind="audience-persona",
                status="ready",
                body=(
                    "---\nkind: audience-persona\nicp_key: clue-abm-buyers\n---\n"
                    "Founder owns the budget."
                ),
            )
            pin = await pin_persona(
                conn,
                storage,
                workspace_id=run.workspace_id,
                brand_id=run.brand_id,
                project_id=run.project_id,
                icp_key=run.icp_key,
                icp_version=1,
            )
            assert pin["state"] == "pinned" and pin["lineage"] == "unverified"
            await conn.execute(
                text(
                    "UPDATE brand_knowledge_document SET status='superseded' WHERE "
                    "artifact_key=:key"
                ),
                {"key": key},
            )
            body = await read_persona_pin(conn, storage, workspace_id=run.workspace_id, pin=pin)
            assert "Founder owns the budget" in body and "LINEAGE GAP" in body
            missing = await pin_persona(
                conn,
                storage,
                workspace_id=run.workspace_id,
                brand_id=run.brand_id,
                project_id=run.project_id,
                icp_key=run.icp_key,
                icp_version=1,
            )
            assert missing["state"] == "missing"

    run_async(scenario())


def test_expired_profile_is_unreadable_and_purged():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, wire, result = await ready_account(conn)
            op = await ops.get(conn, rt.operation_scope, result["result_ref"])
            await conn.execute(
                text(
                    "UPDATE artifact SET expires_at=now()-interval '1 second' WHERE "
                    "storage_key=:key"
                ),
                {"key": op.artifact_key},
            )
            with pytest.raises(ArtifactIntegrityError, match="expired"):
                await read_people_result(rt, ReadPeopleResultArgs(result_ref=result["result_ref"]))
            await purge_erased_artifacts(conn, storage)
            assert op.artifact_key not in storage.blobs

    run_async(scenario())


@pytest.mark.parametrize("catalog_version", ["v2", "v3"])
def test_scripted_agent_account_then_person_depth_channels_receipt_and_erasure(catalog_version):
    from uuid import uuid4

    from langchain_core.messages import AIMessage, ToolMessage

    from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
    from clue_api.arv2.account_research_driver import (
        Arv2AccountResearchWorkHandler,
        _Claim,
        _Scope,
    )
    from clue_api.arv2.research_context import pin_persona
    from clue_api.storage_wiring import DurableContactResearchPrivacyStopper
    from clue_research.compliance import DataSubjectRightsImpl
    from tests.arv2.test_account_research_driver_db import (
        _Models,
        _register_document,
        _ScriptedModel,
    )

    class WiredClients(Clients):
        # Exercise the production token-wide pacing path as well as the paid operation.
        ai_ark_token_scope = "scripted-driver-pacing-regression"

        def __init__(self, wire):
            self.wire = wire

        def ai_ark(self, caller):
            caller._transport = self.wire
            return super().ai_ark(caller)

        def exa(self, caller):
            caller._transport = self.wire
            return super().exa(caller)

    class Queue:
        def __init__(self):
            self.offers = []

        async def enqueue(self, **spec):
            self.offers.append(spec)
            return uuid4()

    def tool_call(name, args):
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": str(uuid4()), "type": "tool_call"}],
        )

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            storage = _MemoryStorage()
            key, sha = await _register_document(
                conn,
                storage,
                workspace_id=run.workspace_id,
                brand_id=run.brand_id,
                path="audience/icp-v2.md",
                kind="icp-definition",
                status="confirmed",
                body=(
                    "---\nkind: icp-definition\nicp_key: clue-abm-buyers\n---\n"
                    "Growth-stage software companies."
                ),
            )
            pin = await pin_persona(
                conn,
                storage,
                workspace_id=run.workspace_id,
                brand_id=run.brand_id,
                project_id=run.project_id,
                icp_key=run.icp_key,
                icp_version=1,
            )
            await conn.execute(
                text(
                    "UPDATE arv2_research_run SET profile_ref=:ref,profile_sha256=:digest,i"
                    "cp_artifact_key=:key,icp_artifact_sha256=:sha,persona_pin=CAST(:pin AS"
                    " jsonb) WHERE run_id=:id"
                ),
                {
                    "ref": f"agent-profile:arv2-account:{catalog_version}",
                    "digest": arv2_account_profile_sha256(version=catalog_version),
                    "key": key,
                    "sha": sha,
                    "pin": json.dumps(pin),
                    "id": run.run_id,
                },
            )
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET profile_ref=:ref,profile_sha256=:digest "
                    "WHERE job_id=:id"
                ),
                {
                    "ref": f"agent-profile:arv2-account:{catalog_version}",
                    "digest": arv2_account_profile_sha256(version=catalog_version),
                    "id": job_id,
                },
            )
            wire = ScriptedTransport(
                [
                    response({"output": {"content": {"report": ""}}, "results": []}),
                    response({"output": {"content": {"report": ""}}, "results": []}),
                    response(
                        {
                            "content": [
                                {
                                    "id": "company-1",
                                    "link": {"domain": "probook.ai"},
                                    "summary": {"name": "Probook"},
                                }
                            ]
                        }
                    ),
                    response({"content": [person()], "last": True}),
                ]
            )

            def account_respond(messages):
                results = [m for m in messages if isinstance(m, ToolMessage)]
                if len(results) == 0:
                    return tool_call(
                        "research_deep",
                        {"charter": "Research company operations, strategy and buying roles. " * 5},
                    )
                if len(results) == 1:
                    return tool_call(
                        "discover_people",
                        {
                            "role_key": "growth",
                            "rationale": "Marketing owns demand generation",
                            "titles": ["VP Marketing"],
                        },
                    )
                found = json.loads(results[-1].content)
                return tool_call(
                    "finalize_research",
                    {
                        "summary": "Company research continued after a deep-research gap.",
                        "committee_candidates": [
                            {
                                "evidence_kind": "provider_candidate",
                                "candidate_ref": found["people"][0]["candidate_ref"],
                                "persona": "champion",
                                "rationale": "Owns demand generation",
                            }
                        ],
                    },
                )

            # The driver owns data-connection serialization. Its underlying factory must
            # remain independently callable by the pacing transaction while a hop runs.
            @asynccontextmanager
            async def raw_connection():
                yield conn

            queue = Queue()
            handler = Arv2AccountResearchWorkHandler(
                settings=Settings(_env_file=None, arv2_ai_ark_min_gap_s=0),
                conn_factory=raw_connection,
                artifacts=Artifacts(conn, storage),
                storage=storage,
                clients=WiredClients(wire),
                model_provider=_Models(_ScriptedModel(account_respond)),
                model_id="offline-model",
                writer=LenientClaimWriter(lenient=True),
                queue=queue,
            )
            scope = _Scope(job_id=job_id, run_id=run.run_id, workspace_id=run.workspace_id)
            ran = await asyncio.wait_for(handler._run(scope, _Claim(), task_attempt=1), 10)
            assert ran == "completed"
            account_job = await store.read_job(conn, job_id=job_id)
            assert account_job.finalization["gaps"]
            jobs = await store.list_jobs(conn, run_id=run.run_id)
            child = next(j for j in jobs if j.subject_type == "person")
            assert len(wire.requests) == 4
            before = len(queue.offers)
            await handler._run(scope, _Claim(), task_attempt=2)
            assert len(queue.offers) > before and len(wire.requests) == 4
            # Re-enter after a simulated interrupted settlement. The committed selection wins
            # without another model turn, duplicate child or provider purchase.
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status='suspended',finished_at=NULL "
                    "WHERE job_id=:id"
                ),
                {"id": job_id},
            )
            await handler._run(scope, _Claim(), task_attempt=3)
            recovered = await store.read_job(conn, job_id=job_id)
            assert (
                recovered.finalization["summary"] == "Recovered the committed committee selection."
            )
            assert len(wire.requests) == 4
            assert len(await store.list_jobs(conn, run_id=run.run_id)) == 2

            # The person model can do depth while contact enrichment is independently in flight.
            class PersonWire:
                def __init__(self):
                    self.requests = []

                def send(self, request):
                    self.requests.append(request)
                    if request.url.endswith("/search"):
                        return response(
                            {
                                "output": {
                                    "content": {"report": "Public professional writing. " * 50}
                                },
                                "results": [],
                            }
                        )
                    if request.url.endswith("/export/single"):
                        return response(
                            {
                                "id": "p1",
                                "email": {
                                    "output": [
                                        {
                                            "address": "dana@example.test",
                                            "found": True,
                                            "status": "VALID",
                                            "domainType": "SMTP",
                                        }
                                    ]
                                },
                            }
                        )
                    raise AssertionError("seeded person performed an unexpected provider call")

            person_wire = PersonWire()

            def person_respond(messages):
                results = [m for m in messages if isinstance(m, ToolMessage)]
                if not results:
                    return tool_call(
                        "research_deep",
                        {
                            "charter": (
                                "Research the bound person's responsibilities and "
                                "public professional writing. "
                            )
                            * 5
                        },
                    )
                return tool_call(
                    "finalize_research",
                    {
                        "summary": "The person has a professional public footprint.",
                        "not_found": ["No public long-form interview established"],
                    },
                )

            person_handler = Arv2AccountResearchWorkHandler(
                settings=Settings(_env_file=None, arv2_ai_ark_min_gap_s=0),
                conn_factory=raw_connection,
                artifacts=Artifacts(conn, storage),
                storage=storage,
                clients=WiredClients(person_wire),
                model_provider=_Models(_ScriptedModel(person_respond)),
                model_id="offline-model",
                writer=LenientClaimWriter(lenient=True),
                queue=queue,
            )
            assert (
                await asyncio.wait_for(
                    person_handler._run(
                        _Scope(
                            job_id=child.job_id, run_id=run.run_id, workspace_id=run.workspace_id
                        ),
                        _Claim(),
                        task_attempt=1,
                    ),
                    10,
                )
                == "completed"
            )
            child = await store.read_job(conn, job_id=child.job_id)
            assert child.finalization["channels"]["contact_email"] == "succeeded"
            assert "contact_phone" not in child.finalization["channels"]
            assert {req.url.rsplit("/", 1)[-1] for req in person_wire.requests} == {
                "search",
                "single",
            }
            assert not any(req.url.endswith("/v1/people") for req in person_wire.requests)
            # DSAR removes the account-side copy and stops old person authority as well.
            rights = DataSubjectRightsImpl(
                run.workspace_id,
                conn_factory=factory(conn),
                storage=storage,
                contact_research_stopper=DurableContactResearchPrivacyStopper(),
            )
            erased = await rights.erase(EntityId(child.subject_entity_id))
            assert erased
            assert (
                await ops.selected_candidates(
                    conn, ops.OperationScope(run.workspace_id, run.run_id, job_id, account)
                )
                == []
            )
            assert not await ops.job_available(
                conn, ops.OperationScope(run.workspace_id, run.run_id, child.job_id, account)
            )

    run_async(scenario())


async def seeded_person_runtime(conn, wire, *, catalog_version="v2"):
    run, account, rt, storage, _, result = await ready_account(
        conn, catalog_version=catalog_version
    )
    await _finalize_research(
        rt,
        FinalizeResearchArgs(
            summary="Marketing owns this account's demand-generation program.",
            committee_candidates=[
                {
                    "evidence_kind": "provider_candidate",
                    "candidate_ref": result["people"][0]["candidate_ref"],
                    "persona": "champion",
                    "rationale": "Owns marketing",
                }
            ],
        ),
    )
    step = await run_committee_step(
        conn,
        job=await store.read_job(conn, job_id=rt.scope.job_id),
        run=run,
        scope=rt.scope,
        candidates=await ops.selected_candidates(conn, rt.operation_scope),
        writer=rt._writer,
        catalog=COMMITTEE_CATALOG,
        person_profile_sha256=arv2_person_profile_sha256(version=catalog_version),
        person_profile_ref=f"agent-profile:arv2-person:{catalog_version}",
    )
    child = await store.read_job(conn, job_id=step.jobs[0].job_id)
    scope = replace(
        rt.scope,
        job_id=child.job_id,
        subject_kind="person",
        contact_id=EntityId(child.subject_entity_id),
        person_name="Dana Test",
        person_linkedin_url="https://linkedin.com/in/p1",
        input_refs=child.input_refs,
    )
    prt = runtime(conn, scope, storage, wire)
    await load_person_seed(prt)
    return prt


@pytest.mark.parametrize(
    "email_mode,state",
    [
        ("empty", "empty"),
        ("error", "failed"),
        ("found", "succeeded"),
        ("wrong-person", "unresolved_identity"),
    ],
)
@pytest.mark.parametrize("catalog_version", ["v2", "v3", "v4"])
def test_email_outcomes_preserve_profile_without_phone_purchase(email_mode, state, catalog_version):
    class Wire:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            if request.url.endswith("/export/single"):
                if email_mode == "error":
                    return response({"error": "bad request"}, 400)
                if email_mode == "empty":
                    return response({"message": "No email"}, 404)
                return response(
                    {
                        "id": "wrong-person" if email_mode == "wrong-person" else "p1",
                        "email": {
                            "output": [
                                {
                                    "address": "dana@example.test",
                                    "found": True,
                                    "status": "VALID",
                                }
                            ]
                        },
                    }
                )
            raise AssertionError("email enrichment attempted another provider endpoint")

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            wire = Wire()
            rt = await seeded_person_runtime(conn, wire)
            rt.scope = replace(rt.scope, catalog_version=catalog_version)
            capability = next(
                c
                for c in AcquireResearchTool(rt).capabilities()
                if c["operation"] == "enrich_contact"
            )
            channel_schema = capability["arguments_schema"]["properties"]["channels"]
            assert channel_schema["default"] == ["email"]
            assert channel_schema["items"]["const"] == "email"
            result = await enrich_contact(rt, EnrichContactArgs())
            assert set(result) == {"email"}
            assert result["email"]["state"] == state
            claims = await rt.job_claims()
            keys = {c.field_key for c in claims}
            assert "contact.current_title" in keys
            assert ("core.work_email" in keys) == (state == "succeeded")
            assert "core.direct_phone" not in keys
            await enrich_contact(rt, EnrichContactArgs())
            assert len(wire.requests) == 1

    run_async(scenario())


def test_completed_channel_survives_claim_failure_and_new_runtime_replay():
    class FailEmailOnce(LenientClaimWriter):
        failed = False

        async def write(self, conn, draft):
            if draft.field_key == "core.work_email" and not self.failed:
                self.failed = True
                raise RuntimeError("injected claim persistence failure")
            return await super().write(conn, draft)

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            wire = ScriptedTransport(
                [
                    response(
                        {
                            "id": "p1",
                            "email": {
                                "output": [
                                    {
                                        "address": "dana@example.test",
                                        "found": True,
                                        "status": "VALID",
                                    }
                                ]
                            },
                        }
                    )
                ]
            )
            rt = await seeded_person_runtime(conn, wire)
            rt._writer = FailEmailOnce(lenient=True)
            args = EnrichContactArgs(channels=["email"])
            assert (await enrich_contact(rt, args))["email"]["state"] == "claim_write_failed"
            fresh = runtime(conn, rt.scope, rt.storage, wire)
            assert (await enrich_contact(fresh, args))["email"]["state"] == "succeeded"
            assert len(wire.requests) == 1
            await ops.stop_contact_jobs(
                conn,
                workspace_id=rt.scope.workspace_id,
                contact_id=rt.scope.contact_id,
                stop_external=True,
                channel_fields=None,
            )
            result = await enrich_contact(fresh, EnrichContactArgs())
            assert result["email"]["state"] != "succeeded" and len(wire.requests) == 1
            from clue_api.arv2.account_research_claims import ai_ark_person_claims
            from clue_api.arv2.ai_ark_client import person_from_record

            with pytest.raises(ValueError, match="authority"):
                await fresh.write(ai_ark_person_claims(person_from_record(person()), fresh.scope))

    run_async(scenario())


def test_equivalent_concurrent_operation_has_one_owner_and_reuses_receipt():
    import threading

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, storage, _, _ = await ready_account(conn)
            started, release = threading.Event(), threading.Event()

            class Wire:
                requests = []

                def send(self, request):
                    self.requests.append(request)
                    started.set()
                    assert release.wait(5)
                    return response({"content": [person()], "last": True})

            wire = Wire()
            rt._transport_factory = lambda: wire
            request = {"fixture": "same paid operation"}

            def provider(caller):
                return rt.clients.ai_ark(caller).people_by_roles(["CEO"], domain="probook.ai")

            owner = asyncio.create_task(rt.operate("ai_ark", "people_roles", request, provider))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                # Since 2026-10-13 the equivalent call waits for the owner instead of being refused
                # (run 7 lost its only people search to that refusal), and reads the same result.
                second = asyncio.create_task(
                    rt.operate("ai_ark", "people_roles", request, provider)
                )
                await asyncio.sleep(0.2)
                assert not second.done()
            finally:
                release.set()
            receipt, body = await owner
            waited, waited_body = await second
            replay, _ = await rt.operate("ai_ark", "people_roles", request, provider)
            assert receipt.operation_id == waited.operation_id == replay.operation_id
            assert waited_body == body and len(wire.requests) == 1

    run_async(scenario())


def test_provider_anchors_refuse_other_employer_and_conflicting_linkedin():
    from clue_research.identity import get_contact, insert_account_entity
    from clue_research.identity.provider import ProviderIdentityConflict, resolve_provider_contact

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, rt, _, _, result = await ready_account(conn)
            op = await ops.get(conn, rt.operation_scope, result["result_ref"])
            elsewhere = await insert_account_entity(
                conn,
                canonical_name="Elsewhere",
                primary_domain="elsewhere.test",
                workspace_id=run.workspace_id,
            )
            other = await insert_contact_entity(
                conn,
                account_entity_id=elsewhere,
                full_name="Dana Test",
                linkedin_url="https://www.linkedin.com/in/p1/",
            )
            args = {
                "workspace_id": run.workspace_id,
                "account_id": EntityId(account),
                "provider": "ai_ark",
                "subject_id": "p1",
                "name": "Dana Test",
                "linkedin_url": "https://linkedin.com/in/p1",
                "artifact_key": op.artifact_key,
            }
            with pytest.raises(ProviderIdentityConflict, match="employment_conflict"):
                await resolve_provider_contact(conn, **args)
            assert (await get_contact(conn, other)).account_entity_id == elsewhere
            args.update(subject_id="p2", linkedin_url="https://linkedin.com/in/p2")
            bound, _ = await resolve_provider_contact(conn, **args)
            args["linkedin_url"] = "https://linkedin.com/in/p1"
            with pytest.raises(ProviderIdentityConflict, match="provider_linkedin_conflict"):
                await resolve_provider_contact(conn, **args)
            assert bound != other

    run_async(scenario())


def test_unseeded_person_uses_bound_lookup_then_same_channels_without_second_lookup():
    from clue_api.arv2.account_research_tools import LookupPersonArgs
    from clue_api.arv2.committee_discovery import lookup_bound_person

    class Wire:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            if request.url.endswith("/v1/people"):
                return response({"content": [person()], "last": True})
            return response({"message": "Not found"}, 404)

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            wire = Wire()
            seeded = await seeded_person_runtime(conn, wire)
            parent = seeded.scope.input_refs["parent_job_id"]
            delegation = {
                "parent_job_id": parent,
                "generation_id": "durable-generation",
                "quality_recipe_version": 24,
                "person_research_brief": {"artifact_key": "retained-brief", "sha256": "a" * 64},
                "privacy_stopped": False,
            }
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=CAST(:refs AS jsonb) WHERE job_id=:id"
                ),
                {"id": seeded.scope.job_id, "refs": json.dumps(delegation)},
            )
            unseeded = runtime(conn, replace(seeded.scope, input_refs={}), seeded.storage, wire)
            args = LookupPersonArgs(linkedin_url="https://linkedin.com/in/p1")
            result = await lookup_bound_person(unseeded, args)
            assert result["profile"]["id"] == "p1"
            assert result["channels"]["email"]["state"] == "empty"
            assert set(result["channels"]) == {"email"}
            await lookup_bound_person(unseeded, args)
            assert len(wire.requests) == 2
            assert sum(r.url.endswith("/v1/people") for r in wire.requests) == 1
            refs = (await store.read_job(conn, job_id=seeded.scope.job_id)).input_refs
            assert "profile" not in refs and refs["candidate_ref"]
            assert all(refs[k] == v for k, v in delegation.items())
            assert refs["provider_job_id"] == str(seeded.scope.job_id)
            assert refs["parent_job_id"] != refs["provider_job_id"]
            # A fresh runtime must reopen its own lookup, not search the account's operations.
            restarted = runtime(conn, replace(seeded.scope, input_refs=refs), seeded.storage, wire)
            await lookup_bound_person(restarted, args)
            assert len(wire.requests) == 2
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=input_refs || "
                    '\'{"provider_job_id":"00000000-0000-0000-0000-000000000000"}\'::jsonb '
                    "WHERE job_id=:id"
                ),
                {"id": seeded.scope.job_id},
            )
            stale = runtime(conn, replace(seeded.scope, input_refs=refs), seeded.storage, wire)
            with pytest.raises(RefusalError, match="person seed does not match"):
                await load_person_seed(stale)

    run_async(scenario())


@pytest.mark.parametrize("catalog_version", ["v2", "v3"])
def test_v2_launch_pins_version_and_rollback_keeps_old_jobs(tmp_path, catalog_version):
    from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
    from clue_api.arv2.account_research_launch import launch_arv2_account_research
    from clue_storage.fs import FsStorage
    from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
    from tests.arv2.test_account_research_launch_db import _request

    async def scenario():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            request = _request(fixture)
            v2 = settings_for(
                arv2_account_research_enabled=True, arv2_research_catalog_version=catalog_version
            )
            receipt = await launch_arv2_account_research(
                conn,
                request,
                settings=v2,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version=catalog_version),
            )
            run = await store.read_run(conn, run_id=receipt.run_id)
            assert (
                run.profile_ref.endswith(":" + catalog_version)
                and run.persona_pin["state"] == "missing"
            )
            assert all(
                j.profile_ref.endswith(":" + catalog_version)
                for j in await store.list_jobs(conn, run_id=run.run_id)
            )
            replay = await launch_arv2_account_research(
                conn,
                request,
                settings=v2,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version=catalog_version),
            )
            assert replay.replayed and replay.run_id == run.run_id
            v1 = settings_for(
                arv2_account_research_enabled=True, arv2_research_catalog_version="v1"
            )
            rollback = await launch_arv2_account_research(
                conn,
                request,
                settings=v1,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(),
            )
            assert rollback.run_id != receipt.run_id
            assert (await store.read_run(conn, run_id=run.run_id)).profile_ref.endswith(
                ":" + catalog_version
            )
            assert (await store.read_run(conn, run_id=rollback.run_id)).profile_ref.endswith(":v1")

    run_async(scenario())


def test_page_and_title_refinement_are_distinct_queries_under_same_company():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            _, _, rt, _, initial_wire, first = await ready_account(conn)
            wire = ScriptedTransport(
                [
                    response({"content": [person("p3")], "last": True, "totalPages": 2}),
                    response({"content": [], "last": True, "totalPages": 0}),
                ]
            )
            rt._transport_factory = lambda: wire
            second = await discover_people(
                rt,
                DiscoverPeopleArgs(
                    role_key="growth",
                    rationale="Inspect the remaining candidates",
                    titles=["VP Marketing"],
                    page=1,
                ),
            )
            refined = await discover_people(
                rt,
                DiscoverPeopleArgs(
                    role_key="economic-buyer",
                    rationale="Investigate a different responsibility",
                    titles=["Chief Executive Officer"],
                ),
            )
            assert len({first["result_ref"], second["result_ref"], refined["result_ref"]}) == 3
            assert len(initial_wire.requests) == 2 and len(wire.requests) == 2
            assert second["has_more"] is False and refined["people"] == []
            for request in wire.requests:
                assert json.loads(request.body)["contact"]["company"]["latest"]["any"] == {
                    "include": ["company-1"],
                }
            assert json.loads(wire.requests[0].body)["page"] == 1
            details = await read_people_result(
                rt,
                ReadPeopleResultArgs(
                    result_ref=second["result_ref"],
                ),
            )
            assert details["page"] == 1 and details["people"][0]["profile"]["id"] == "p3"

    run_async(scenario())


def test_late_channel_response_after_erasure_is_retained_only_as_unreadable_receipt():
    import threading

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            started, release = threading.Event(), threading.Event()

            class Wire:
                requests = []

                def send(self, request):
                    self.requests.append(request)
                    started.set()
                    assert release.wait(5)
                    return response(
                        {
                            "id": "p1",
                            "email": {
                                "output": [
                                    {
                                        "address": "dana@example.test",
                                        "found": True,
                                        "status": "VALID",
                                    }
                                ]
                            },
                        }
                    )

            wire = Wire()
            rt = await seeded_person_runtime(conn, wire)
            pending = asyncio.create_task(enrich_contact(rt, EnrichContactArgs()))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                await ops.stop_contact_jobs(
                    conn,
                    workspace_id=rt.scope.workspace_id,
                    contact_id=rt.scope.contact_id,
                    stop_external=True,
                    channel_fields=None,
                )
                await erase_provider_evidence(
                    conn,
                    workspace_id=rt.scope.workspace_id,
                    contact_id=rt.scope.contact_id,
                )
            finally:
                release.set()
            assert (await pending)["email"]["state"] != "succeeded"
            assert not any(c.field_key == "core.work_email" for c in await rt.job_claims())
            row = (
                await conn.execute(
                    text(
                        "SELECT o.artifact_key,a.privacy_erased,o.ledger_id "
                        "FROM arv2_research_operation o JOIN artifact a "
                        "ON a.storage_key=o.artifact_key "
                        "WHERE o.job_id=:job AND o.kind='contact_email'"
                    ),
                    {"job": rt.scope.job_id},
                )
            ).one()
            assert row.privacy_erased and row.ledger_id
            assert len(wire.requests) == 1

    run_async(scenario())


def test_web_selected_person_keeps_parent_for_queue_redelivery_without_provider_seed():
    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v2")
            rt = runtime(conn, scope, _MemoryStorage(), ScriptedTransport([]))
            await _finalize_research(
                rt,
                FinalizeResearchArgs(
                    summary="The company team page identifies its marketing owner.",
                    committee_candidates=[
                        {
                            "evidence_kind": "web_candidate",
                            "name": "Dana Test",
                            "persona": "champion",
                            "rationale": "Owns marketing",
                            "confirmed_by": "https://probook.ai/team",
                            "evidence_span": "Dana Test, VP Marketing",
                        }
                    ],
                ),
            )
            step = await run_committee_step(
                conn,
                job=await store.read_job(conn, job_id=job_id),
                run=run,
                scope=scope,
                candidates=await ops.selected_candidates(conn, rt.operation_scope),
                writer=rt._writer,
                catalog=COMMITTEE_CATALOG,
                person_profile_sha256=arv2_person_profile_sha256(version="v2"),
                person_profile_ref="agent-profile:arv2-person:v2",
            )
            child = await store.read_job(conn, job_id=step.jobs[0].job_id)
            assert child.input_refs == {"version": 1, "parent_job_id": str(job_id)}
            prt = runtime(
                conn,
                replace(
                    scope,
                    job_id=child.job_id,
                    subject_kind="person",
                    contact_id=EntityId(child.subject_entity_id),
                    input_refs=child.input_refs,
                ),
                rt.storage,
                ScriptedTransport([]),
            )
            assert await load_person_seed(prt) is None

    run_async(scenario())


class _HeldTransport(ScriptedTransport):
    """Scripted responses, with the first request held open until the test releases it."""

    def __init__(self, script):
        super().__init__(script)
        self.release = threading.Event()

    def send(self, request):
        if not self.requests:
            self.requests.append(request)
            assert self.release.wait(10), "the held request was never released"
            self.requests.pop()
        return super().send(request)


def test_a_people_search_waits_for_the_company_lookup_another_tool_started():
    """Run 7 (2026-10-12): the agent called lookup_company and discover_people in one round. Both
    make the same AI Ark company request, so they share one saved operation, and discover_people
    read it 45 ms after lookup_company started it. It was refused ("saved operation is running: in
    flight; do not repeat uncertain spending; record the gap"), the refusal was saved under the
    search's own arguments, and the agent never searched AI Ark for people again. The second
    caller now waits for the first and reads its saved result; the company is bought once."""

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v4")
            company = {
                "content": [
                    {"id": "company-1", "link": {"domain": "probook.ai"}, "summary": {"name": "P"}}
                ]
            }
            people = {"content": [person()], "last": True, "totalPages": 1, "totalElements": 1}
            wire = _HeldTransport([response(company), response(people)])
            rt = runtime(
                conn,
                replace(scope, input_refs={"quality_recipe_version": 27}),
                _MemoryStorage(),
                wire,
            )
            lookup = asyncio.create_task(company_lock(rt))
            while not wire.requests:  # lookup_company's company request is on the wire
                await asyncio.sleep(0.01)
            search = asyncio.create_task(
                discover_people(
                    rt,
                    DiscoverPeopleArgs(
                        role_key="growth", rationale="Owns demand", titles=["VP Marketing"]
                    ),
                )
            )
            await asyncio.sleep(0.2)
            assert not search.done(), "the search must wait for the running company lookup"
            wire.release.set()
            lock, found = await asyncio.gather(lookup, search)
            assert lock["company_id"] == "company-1"
            assert found["company_lock"]["company_id"] == "company-1"
            assert [p["name"] for p in found["people"]] == ["Dana Test"]
            assert [r.url.rsplit("/", 1)[-1] for r in wire.requests] == ["companies", "people"]

    run_async(scenario())


def test_a_request_left_running_by_a_crashed_attempt_is_still_refused_not_bought_again():
    """Waiting only covers a call this runtime is making itself. An operation still marked running
    by another process (a worker that died mid-call) has an unknown outcome: it stays refused, and
    the provider is not called a second time."""

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v4")
            wire = ScriptedTransport([])
            rt = runtime(
                conn,
                replace(scope, input_refs={"quality_recipe_version": 27}),
                _MemoryStorage(),
                wire,
            )
            await ops.begin(conn, rt.operation_scope, "company_lock", {"domain": "probook.ai"})
            with pytest.raises(RefusalError, match="saved operation is running"):
                await asyncio.wait_for(company_lock(rt), timeout=5)
            assert wire.requests == []

    run_async(scenario())


def test_the_company_lookup_skips_company_facts_discovery_already_saved():
    """Founder ruling 2026-10-27: discovery enriches the table's company facts from AI Ark, and
    deep research's company lookup — still made, because the committee search needs the company —
    does not save those facts again. Facts discovery did not save are still written."""
    from clue_api.arv2.ai_ark_client import company_from_record
    from clue_api.arv2.discovery_firmographics import Resolution, firmographic_drafts

    async def scenario():
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            scope = replace(_scope(run, account), job_id=job_id, catalog_version="v4")
            record = {
                "id": "company-1",
                "link": {"domain": "probook.ai", "linkedin": "https://www.linkedin.com/company/pb"},
                "summary": {
                    "name": "Probook",
                    "industry": "software development",
                    "staff": {"total": 80},
                },
            }
            # What discovery saved earlier: the industry only.
            discovered = [
                d
                for d in firmographic_drafts(
                    Resolution(company_from_record(record), "single_record"),
                    workspace_id=scope.workspace_id,
                    discovery_run_id=scope.run_id,
                    account_id=scope.account_id,
                    domain="probook.ai",
                    catalog=COMMITTEE_CATALOG,
                )
                if d.field_key == "core.industry"
            ]
            assert [d.field_key for d in discovered] == ["core.industry"]
            for draft in discovered:
                await LenientClaimWriter(lenient=True).write(conn, draft)

            wire = ScriptedTransport([response({"content": [record]})])
            rt = runtime(
                conn,
                replace(scope, input_refs={"quality_recipe_version": 27}),
                _MemoryStorage(),
                wire,
            )
            lock = await company_lock(rt)

            assert lock["company_id"] == "company-1", "the lookup itself still happens"
            rows = (
                await conn.execute(
                    text(
                        "SELECT field_key, research_mode FROM claim WHERE entity_id = :e "
                        "AND source_key = 'ai_ark:company' AND superseded_by IS NULL"
                    ),
                    {"e": scope.account_id},
                )
            ).all()
            by_field = {}
            for field_key, mode in rows:
                by_field.setdefault(field_key, []).append(mode)
            assert by_field["core.industry"] == ["account_discovery"], "not saved a second time"
            assert by_field["core.employee_count"] == ["account_profiling"]
            assert by_field["core.company_linkedin_url"] == ["account_profiling"]

    run_async(scenario())
