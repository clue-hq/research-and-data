"""FI-2 slice 1, Task 3 — the global-lens account detail (`GET /frontend/v1/accounts/{id}`).

Same harness as the accounts-list suite: the real projections app driven in-process through
``httpx.ASGITransport`` on the test's rolled-back connection, so the endpoint reads exactly the
rows the test seeded and nothing commits.

The fixture is the slice-0 canonical shape — **two projects over one workspace, one shared
account** — extended with the three shapes this endpoint's composition rules turn on:

* a **neutral** fact written on project A's run (it must serve once, at the top level, in every
  lens — species-conditional lineage);
* **relative** claims per project (a score, a value narrative, and a registry-declared
  ``project_relative`` pack field standing in for a campaign insight), so a section can be proven
  to contain only its own project's work;
* claims from runs that map to **no** project — one registered ``kind='manual'`` with a NULL
  project (the ingestion shape) and one with no ``run_lineage`` row at all (the documented
  exemption class) — which must surface in the honest ``unattributed`` section, not vanish.

Plus the governed committee (through ``ContactEligibilityResolver``, never
``identity.contact_ids_for_account``), the merged-loser redirect, and the enveloped 404s.

Every read is workspace-scoped: this suite shares a database with suites that commit.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import JobStatus
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.display.blocks import insert_block, supersede_blocks
from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.recipes import load_display_recipes, recipes_for
from clue_api.arv2.display.render import display_claim
from clue_api.arv2.display.runner import SectionDraft
from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.contract_v1 import AccountDetailResponseV1
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    ClaimId,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    PassKind,
    Persona,
    ProjectRunId,
    ResearchMode,
    ResearchScope,
    ReuseScope,
    RunId,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchRunKind,
    ResearchRunLifecycleContract,
)
from clue_fleet import (
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    launch_entity_research_run,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    insert_claim,
    record_run_lineage,
    register_field,
)
from clue_research.claimstore.packs import load_core_pack
from clue_research.durable import (
    AccountRunStatus,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.icp import load_starter_packs
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.membership import ensure_project_account
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    VALUE_NARRATIVE,
    load_narrative_pack,
    load_prose_pack,
)
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from clue_spine import Project
from clue_storage import artifact_key, content_address, record_artifact
from tests._workspace import seed_project, seed_workspace
from tests.api.contract_v1.oracle import zod_validate
from tests.arv2.account_research_job_helpers import seed_arv2_job
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import lifecycle_fixture
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-slice1-account-detail"
_OTHER_WS = "fi2-slice1-account-detail-other"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"

#: A pack field registered by the fixture purely to *declare* itself ``project_relative``. It is
#: the stand-in for a campaign insight: today's shipped insight families (``account.recent_funding``
#: / ``operational_pain`` / ``strategic_moves`` / ``account.resonance.*``) are all
#: ``project_neutral`` under the ratified §5.2 table, so a hardcoded "insight" list would be wrong.
#: This field proves the split is read from the **registry**, not from a list in the read layer.
_INSIGHT_FIELD = "fi2read.campaign_insight"

#: The account-axis field the planted M8D result requests. The governed-request trigger refuses a
#: field key whose namespace is not the subject's axis, so a coverage fixture cannot use an
#: arbitrary key; ``account.recent_funding`` is a real registered (``project_neutral``) field, so
#: the "unresolved until answered" test can answer it with a real claim.
_REQUESTED_FIELD = "account.recent_funding"
_EMPLOYEE_ARTIFACT_BODY = b"Acme Detail reports 1,200 employees."
_EMPLOYEE_ARTIFACT_KEY = artifact_key(_WS, content_address(_EMPLOYEE_ARTIFACT_BODY))


# --- harness --------------------------------------------------------------------------------


class _MemoryStorage:
    def __init__(self, blobs: dict[str, bytes] | None = None) -> None:
        self.blobs = dict(blobs or {})

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        raise AssertionError(f"must not presign {key!r} for {expires_in}s")

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", datetime.min.replace(tzinfo=UTC)


def _app(conn: AsyncConnection, *, evidence_storage: _MemoryStorage | None = None):
    """The real projections app with the flag on and the DB seam bound to the test's connection.

    ``arv2_display_generate_on_read=False`` is not decoration: the composition root reads a real
    ``Secrets()``, so on a developer machine with ``OPENROUTER_API_KEY`` set the D3 display seam
    would build a live runner and this suite would *spend money* writing pages. Off, the seam is a
    pure projection — it composes the blocks the fixture stored and calls nothing.
    """
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None, frontend_read_enabled=True, arv2_display_generate_on_read=False
        ),
        conn_factory=conn_session_factory(conn),
        ingestion_storage=evidence_storage,
        manage_db_lifespan=False,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _get(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    *,
    workspace_id: str = _WS,
    evidence_storage: _MemoryStorage | None = None,
    contract: str | None = None,
) -> httpx.Response:
    """One detail request. ``contract=None`` is the FI-2 payload; ``"v1"`` selects contract v1."""
    async with _client(_app(conn, evidence_storage=evidence_storage)) as client:
        return await client.get(
            f"{_BASE}/{account_id}",
            params={} if contract is None else {"contract": contract},
            headers={"X-Workspace-Id": workspace_id},
        )


def _sections(payload: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    """The project sections keyed by ``projectId`` — ``None`` is the unattributed section."""
    return {section["projectId"]: section for section in payload["projectSections"]}


async def _count_statements(
    conn: AsyncConnection, account_id: uuid.UUID, *, contract: str | None = None
) -> tuple[int, dict[str, Any]]:
    """``(statements issued, payload)`` for one detail request.

    The endpoint composes a fixed number of batched reads per account, so this count is a
    *constant* the tests can compare across fixtures of different shapes — which is how the N+1
    guard proves a per-section lookup has not crept into the composition. Each contract has its
    own constant: the v1 branch composes more sources than the FI-2 one, so the two counts are
    compared against themselves, never against each other.
    """
    statements = 0

    def count(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(conn.sync_connection, "before_cursor_execute", count)
    try:
        response = await _get(conn, account_id, contract=contract)
    finally:
        event.remove(conn.sync_connection, "before_cursor_execute", count)
    assert response.status_code == 200
    return statements, response.json()


def _facts(payload: dict[str, Any]) -> dict[str, Any]:
    return {fact["fieldKey"]: fact for fact in payload["neutralFacts"]}


def _values(entries: list[dict[str, Any]]) -> list[Any]:
    return [entry["value"] for entry in entries]


# --- seeding --------------------------------------------------------------------------------


async def _register_insight_field(conn: AsyncConnection) -> None:
    """Register the declared-``project_relative`` pack field (idempotent within the transaction)."""
    await register_field(
        conn,
        FieldDef(
            field_key=_INSIGHT_FIELD,
            value_type="str",
            pass_kind=PassKind.DEEP,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            research_scope=ResearchScope.PROJECT_RELATIVE,
        ),
        pack="fi2read",
        description="FI-2 read-layer test field: a genuinely project-relative campaign insight.",
    )


async def _account(
    conn: AsyncConnection,
    *,
    name: str,
    domain: str | None,
    workspace_id: str = _WS,
) -> EntityId:
    return await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )


async def _run(
    conn: AsyncConnection, *, kind: str, project_id: str | None, registered: bool = True
) -> RunId:
    """Mint a run id, registering its lineage unless the caller wants the exemption shape."""
    run_id = new_run_id()
    if registered:
        await record_run_lineage(
            conn, run_id=run_id, workspace_id=_WS, kind=kind, project_id=project_id
        )
    return run_id


async def _account_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    field_key: str,
    value: JsonValue,
    run_id: RunId,
    source_key: str = "seed_source",
    private: bool = False,
    observed_at: datetime | None = None,
    artifact_body: bytes | None = None,
) -> uuid.UUID:
    retained_key: str | None = None
    if artifact_body is not None:
        digest = content_address(artifact_body)
        retained_key = artifact_key(_WS, digest)
        await record_artifact(
            conn,
            storage_key=retained_key,
            workspace_id=_WS,
            content_sha256=digest,
            media_type="text/plain",
            size_bytes=len(artifact_body),
            source_key=source_key,
            source_url="https://example.test/facts",
        )
    claim = account_claim(
        entity_id=account_id,
        field_key=field_key,
        value_json=value,
        source_tier=2,
        extraction_method=ExtractionMethod.API,
        confidence=Confidence(0.9),
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://example.test/facts",
        evidence_span="seeded",
        observed_at=observed_at,
    ).model_copy(update={"source_key": source_key, "artifact_key": retained_key})
    # The reuse class is stamped explicitly rather than inferred: ``account.value_narrative`` and
    # the test pack field both declare ``tenant_private`` at the field, and the default
    # ``stamp_reuse`` prefix policy does not match either (M12.1 injects its own policy for the
    # narrative). Stamping directly keeps the fixture honest about what the writer would produce.
    claim = (
        claim.model_copy(update={"reuse_scope": ReuseScope.TENANT_PRIVATE, "workspace_id": _WS})
        if private
        else stamp_reuse(claim, workspace_id=None)
    )
    await insert_claim(conn, claim)
    return uuid.UUID(str(claim.id))


async def _account_summary_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    paragraphs: Sequence[str],
    status: VerificationStatus = VerificationStatus.VERIFIED,
    research_outcome: str = "completed",
) -> None:
    """One Lane-E-shaped summary claim with its real tenant-private/verification stamps."""

    claim = account_claim(
        entity_id=account_id,
        field_key=ACCOUNT_SUMMARY,
        value_json={
            "paragraphs": list(paragraphs),
            "prompt_version": "account_summary_v1",
            "synthesized_from_job_id": str(uuid.uuid4()),
            "research_outcome": research_outcome,
            "project_id": None,
        },
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=Confidence(0.7),
        run_id=await _run(conn, kind="entity_research", project_id=None),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="clue://narrative/prose",
        evidence_span="verified account facts",
    ).model_copy(
        update={
            "source_key": "llm_synthesis",
            "verification_status": status,
            "reuse_scope": ReuseScope.TENANT_PRIVATE,
            "workspace_id": _WS,
        }
    )
    await insert_claim(conn, claim)


async def _score(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    project_id: str,
    fit: float,
    intent: float | None,
    icp_key: str,
    icp_version: int,
) -> None:
    run_id = await _run(conn, kind="scoring", project_id=project_id)
    values: list[tuple[str, float]] = [("account.scoring.fit", fit)]
    if intent is not None:
        values.append(("account.scoring.intent", intent))
    for field_key, value in values:
        await _account_claim(
            conn,
            account_id=account_id,
            field_key=field_key,
            value={
                "value": value,
                "components": [],
                "icp_key": icp_key,
                "icp_version": icp_version,
            },
            run_id=run_id,
            source_key="scoring_engine",
            private=True,
        )


async def _committee_member(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    account_run: RunId,
    name: str,
    suffix: str,
    persona: Persona = Persona.ECONOMIC_BUYER,
    binding: IdentityBinding = IdentityBinding.STRONG,
) -> tuple[EntityId, tuple[uuid.UUID, ...]]:
    """One governed committee member plus the claim ids the account run references."""
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=name,
        linkedin_url=f"https://linkedin.com/in/{suffix}",
        status=AccountStatus.ACTIVE,
    )
    claim_ids: list[uuid.UUID] = []
    for field_key, value, use_class in (
        (
            ROLE_ON_COMMITTEE,
            {
                "role": persona.value,
                "confidence": 1.0,
                "plausible": True,
                "rationale": "seeded",
            },
            UseClass.PROFESSIONAL_PUBLIC,
        ),
        (PERSONA, persona.value, UseClass.PROFESSIONAL_PUBLIC),
    ):
        claim = stamp_reuse(
            contact_claim(
                entity_id=contact,
                field_key=field_key,
                value_json=value,  # type: ignore[arg-type]
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                confidence=Confidence(1.0),
                run_id=account_run,
                research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                identity_binding=binding,
                use_class=use_class,
                evidence_span=f"evidence for {field_key}",
            ),
            workspace_id=_WS,
        ).model_copy(
            update={
                "verification_status": (
                    VerificationStatus.VERIFIED
                    if binding is IdentityBinding.STRONG
                    else VerificationStatus.UNVERIFIED
                )
            }
        )
        await insert_claim(conn, claim)
        claim_ids.append(uuid.UUID(str(claim.id)))
    return contact, tuple(claim_ids)


async def _launch_research_job(
    conn: AsyncConnection, *, project_id: str, account_id: EntityId
) -> dict[str, Any]:
    """Launch one real M8D account-research run/job through the production R2 entry point.

    Only the run and job rows matter here — they are the FK anchors the R4 result chain hangs off.
    """
    lifecycle = lifecycle_fixture(ResearchRunKind.ACCOUNT_RESEARCH)
    payload = lifecycle.model_dump(mode="json")
    selection = payload["selection"]
    selection["workspace_id"] = _WS
    selection["project_id"] = project_id
    selection["subjects"] = [{**selection["subjects"][0], "subject_entity_id": str(account_id)}]
    lifecycle = ResearchRunLifecycleContract.model_validate(payload)
    subject = lifecycle.selection.subjects[0]
    authorization = EntityResearchJobAuthorization(
        job_id=uuid.uuid4(),
        research_run_id=lifecycle.run_id,
        subject_type=lifecycle.selection.subject_type,
        subject_entity_id=subject.subject_entity_id,
        parent_account_id=lifecycle.selection.account_entity_id,
        workspace_id=_WS,
        project_id=project_id,
        product_id=lifecycle.selection.product_id,
        project_run_id=lifecycle.selection.project_run_id,
        selection=lifecycle.selection,
        agent_profile_ref="agent-profile:account:v1",
        agent_profile_sha256="0" * 64,
        checkpoint_thread_id=f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}",
        attempt_id=uuid.uuid4(),
        lease_id=uuid.uuid4(),
    )
    await launch_entity_research_run(
        conn,
        EntityResearchRunEnvelope(
            lifecycle=lifecycle,
            jobs=(
                EntityResearchJobEnvelope(
                    authorization=authorization,
                    priority=0,
                    budget_envelope_ref=f"budget:job:{authorization.job_id}",
                    budget_cap_cents=Decimal("4.00"),
                ),
            ),
            budget_cap_cents=Decimal("10.00"),
            concurrency_limit=1,
        ),
    )
    return {
        "research_run_id": lifecycle.run_id,
        "job_id": authorization.job_id,
        "project_run_id": lifecycle.selection.project_run_id,
        "product_id": lifecycle.selection.product_id,
        "project_id": project_id,
    }


async def _plant_research_result_fields(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    project_id: str,
    fields: Sequence[tuple[str, str, EntityId]],
) -> None:
    """Persist one M8D ``entity_research_result`` for ``account_id`` carrying ``fields``.

    ``fields`` is ``(field_key, subject_type, target_entity_id)`` — the shape
    ``entity_research_tools._flatten_result_fields`` produces, where an **account** result also
    carries every contact subject the account research discovered. Reproducing that mixed shape is
    the whole point: the coverage read must report only the account's own unresolved fields.

    The FK chain is written directly rather than driven through the governed tool invoker: what is
    under test is a read predicate over these rows, and R4's own suite owns proving the writer.
    """
    launch = await _launch_research_job(conn, project_id=project_id, account_id=account_id)
    ids = {name: uuid.uuid4() for name in ("turn", "execution", "event", "request", "observation")}
    result_id = uuid.uuid4()
    operation_ref = f"provider-op:{result_id}"
    artifact_sha = f"{result_id.hex}{result_id.hex}".ljust(64, "0")[:64]
    # ``artifact_key_encodes_scope``: the storage key IS ``{workspace}/{content_sha256}``.
    artifact_key = f"{_WS}/{artifact_sha}"
    context = {
        "agent_execution_id": str(ids["execution"]),
        "agent_turn_id": str(ids["turn"]),
        "role": "account",
        "subject_type": "account",
        "subject_entity_id": str(account_id),
        "job_id": str(launch["job_id"]),
        "research_run_id": str(launch["research_run_id"]),
        "workspace_id": _WS,
        "project_id": launch["project_id"],
        "product_id": launch["product_id"],
        "project_run_id": str(launch["project_run_id"]),
        "checkpoint_thread_id": f"checkpoint:{launch['research_run_id']}:{account_id}",
        # The governed-request trigger checks every requested tool/field/source/question against
        # what the turn admitted, so the admitted set is part of the fixture, not decoration.
        "tool_names": ["research_entity"],
        "admitted_field_keys": [_REQUESTED_FIELD],
        "admitted_source_keys": ["seed_source"],
        "field_source_authority": [{"field_key": _REQUESTED_FIELD, "source_keys": ["seed_source"]}],
        "research_questions": ["what?"],
    }
    params = {
        **{f"{name}_id": value for name, value in ids.items()},
        "result_id": result_id,
        "operation_ref": operation_ref,
        "artifact_key": artifact_key,
        "artifact_sha": artifact_sha,
        "workspace_id": _WS,
        "account_id": account_id,
        "sha": "a" * 64,
        "context": json.dumps(context),
        "requested_field": _REQUESTED_FIELD,
        "authority": json.dumps(context["field_source_authority"]),
        **{key: value for key, value in launch.items() if key != "job_id"},
        "job_id": launch["job_id"],
    }
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:artifact_key, :workspace_id, :artifact_sha, "
            "'application/json', 1)"
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_turn
                (agent_turn_id, agent_execution_id, job_id, research_run_id, role, subject_type,
                 target_entity_id, workspace_id, project_id, product_id, project_run_id,
                 checkpoint_thread_id, context_json, context_sha256, resource_manifest_json,
                 resource_manifest_sha256, tool_manifest_json, tool_manifest_sha256,
                 system_prompt_sha256)
            VALUES
                (:turn_id, :execution_id, :job_id, :research_run_id, 'account', 'account',
                 :account_id, :workspace_id, :project_id, :product_id, :project_run_id,
                 :checkpoint_thread_id, CAST(:context AS jsonb), :sha, '{}'::jsonb, :sha,
                 '[]'::jsonb, :sha, :sha)
            """
        ),
        {**params, "checkpoint_thread_id": context["checkpoint_thread_id"]},
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_event
                (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id, tool_name,
                 tool_version, tool_input_sha256, payload_json)
            VALUES (:event_id, :turn_id, :execution_id, 'tool_started', 'call-1', 'research_entity',
                    1, :sha, '{}'::jsonb)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 workspace_id, project_id,
                 product_id, project_run_id, tool_name, tool_version, tool_input_sha256,
                 field_plan_ref, source_plan_ref, field_keys, source_keys, questions,
                 budget_reservation_key, idempotency_key, field_source_authority)
            VALUES
                (:request_id, :turn_id, :execution_id, :event_id, 'call-1', :research_run_id,
                 :job_id, 'account', :account_id, :workspace_id, :project_id, :product_id,
                 :project_run_id, 'research_entity', 1, :sha, 'field-plan:1', 'source-plan:1',
                 ARRAY[:requested_field], ARRAY['seed_source'], ARRAY['what?'],
                 'budget:1', 'idem:1', CAST(:authority AS jsonb))
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_operation
                (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                 subject_type, target_entity_id, source_key, request_artifact_ref, reserved_at)
            VALUES (:operation_ref, 'seed', :workspace_id, :project_id, :project_run_id, 'account',
                    :account_id, 'seed_source', :artifact_key, now())
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_observation
                (observation_id, tool_request_id, external_workspace_id, disposition,
                 provider_operation_ref)
            VALUES (:observation_id, :request_id, :workspace_id, 'caused', :operation_ref)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_result
                (result_id, tool_request_id, provider_observation_id, workspace_id, subject_type,
                 target_entity_id, result_artifact_key, result_sha256, delivery,
                 requested_field_keys, provider_operation_ref, provider_snapshot_ref)
            VALUES (:result_id, :request_id, :observation_id, :workspace_id, 'account',
                    :account_id, :artifact_key, :sha, 'inline_complete',
                    ARRAY[:requested_field], :operation_ref, 'snapshot:1')
            """
        ),
        params,
    )
    for ordinal, (field_key, subject_type, target_entity_id) in enumerate(fields):
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_result_field
                    (result_id, ordinal, field_key, outcome, claim_delta, workspace_id,
                     verification_status, subject_type, target_entity_id, parent_account_id)
                VALUES (:result_id, :ordinal, :field_key, 'unsupported', 'none', :workspace_id,
                        'unverified', :subject_type, :target_entity_id, :parent_account_id)
                """
            ),
            {
                **params,
                "ordinal": ordinal,
                "field_key": field_key,
                "subject_type": subject_type,
                "target_entity_id": target_entity_id,
                "parent_account_id": None if subject_type == "account" else account_id,
            },
        )


class _Fixture:
    def __init__(
        self,
        *,
        project_a: Project,
        project_b: Project,
        run_a: ProjectRunId,
        run_b: ProjectRunId,
        acme: EntityId,
        champion: EntityId,
        ghost: EntityId,
    ) -> None:
        self.project_a = project_a
        self.project_b = project_b
        self.run_a = run_a
        self.run_b = run_b
        self.acme = acme
        self.champion = champion
        self.ghost = ghost


async def _build(conn: AsyncConnection) -> _Fixture:
    await seed_workspace(conn, _WS)
    await load_narrative_pack(conn)
    await load_prose_pack(conn)
    await load_committee_pack(conn)
    await load_starter_packs(conn)
    await _register_insight_field(conn)

    project_a = await seed_project(conn, _WS, name="Detail project A")
    project_b = await seed_project(conn, _WS, name="Detail project B")
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    acme = await _account(conn, name="Acme Detail", domain="acme-detail.test")
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_a.project_id,
        account_entity_id=acme,
        added_via="discovered",
        added_at=base,
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_b.project_id,
        account_entity_id=acme,
        added_via="imported",
        added_at=base + timedelta(minutes=5),
    )

    # --- neutral: one written on A's run, one on a project-less run. Neither is lineage-filtered.
    await _account_claim(
        conn,
        account_id=acme,
        field_key="core.employee_count",
        value=1200,
        run_id=await _run(conn, kind="scoring", project_id=project_a.project_id),
        source_key="clearbit",
        observed_at=base,
        artifact_body=_EMPLOYEE_ARTIFACT_BODY,
    )
    await _account_claim(
        conn,
        account_id=acme,
        field_key="core.revenue_band",
        value="100m_500m",
        run_id=await _run(conn, kind="enrichment", project_id=None),
        source_key="crunchbase",
        observed_at=base,
    )

    # --- relative: each project's own score, narrative and insight.
    await _score(
        conn,
        account_id=acme,
        project_id=project_a.project_id,
        fit=0.81,
        intent=0.40,
        icp_key="alpha",
        icp_version=1,
    )
    await _score(
        conn,
        account_id=acme,
        project_id=project_b.project_id,
        fit=0.55,
        intent=None,
        icp_key="beta",
        icp_version=3,
    )
    for project, label in ((project_a, "A"), (project_b, "B")):
        narrative_run = await _run(conn, kind="narrative", project_id=project.project_id)
        await _account_claim(
            conn,
            account_id=acme,
            field_key=VALUE_NARRATIVE,
            value={
                "persona": Persona.ECONOMIC_BUYER.value,
                "argument": f"narrative for {label}",
                "angle_label": "roi",
                "icp_key": "alpha" if label == "A" else "beta",
                "icp_spec_version": 1,
            },
            run_id=narrative_run,
            source_key="narrative_synthesis",
            private=True,
        )
        insight_run = await _run(conn, kind="entity_research", project_id=project.project_id)
        await _account_claim(
            conn,
            account_id=acme,
            field_key=_INSIGHT_FIELD,
            value=f"insight for {label}",
            run_id=insight_run,
            source_key="deep_research",
            private=True,
        )

    # --- unattributed: an ingestion-style manual run (registered, NULL project) and a run with no
    # lineage row at all (the documented pre-FI-2 / exemption shape).
    await _account_claim(
        conn,
        account_id=acme,
        field_key=_INSIGHT_FIELD,
        value="insight from a manual ingestion",
        run_id=await _run(conn, kind="manual", project_id=None),
        source_key="client_upload",
        private=True,
    )
    await _account_claim(
        conn,
        account_id=acme,
        field_key=_INSIGHT_FIELD,
        value="insight from an unregistered run",
        run_id=await _run(conn, kind="manual", project_id=None, registered=False),
        source_key="legacy",
        private=True,
    )

    # --- the governed committee: project A researched it, project B did not.
    run_a = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_a,
        project_id=project_a.project_id,
        workspace_id=_WS,
        icp_key="alpha",
        icp_version=1,
    )
    run_b = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_b,
        project_id=project_b.project_id,
        workspace_id=_WS,
        icp_key="beta",
        icp_version=3,
    )
    account_run = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=account_run,
        project_run_id=run_a,
        entity_id=acme,
        tier="top",
    )
    champion, champion_refs = await _committee_member(
        conn,
        account_id=acme,
        account_run=account_run,
        name="Dana Buyer",
        suffix="dana-buyer",
    )
    # A same-name-risk member whose identity binding is WEAK: membership is identity-bearing, so
    # the governed reader must drop it entirely rather than serve an unbound person.
    ghost, ghost_refs = await _committee_member(
        conn,
        account_id=acme,
        account_run=account_run,
        name="Unbound Person",
        suffix="unbound-person",
        persona=Persona.CHAMPION,
        binding=IdentityBinding.WEAK,
    )
    await save_references(
        conn,
        account_run,
        references_index={"committee": [str(claim_id) for claim_id in champion_refs + ghost_refs]},
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )

    return _Fixture(
        project_a=project_a,
        project_b=project_b,
        run_a=run_a,
        run_b=run_b,
        acme=acme,
        champion=champion,
        ghost=ghost,
    )


# --- identity -------------------------------------------------------------------------------


def test_the_identity_block_comes_from_the_entity_row() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            response = await _get(conn, fixture.acme)
            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == str(fixture.acme)
            assert payload["name"] == "Acme Detail"
            assert payload["domain"] == "acme-detail.test"
            assert payload["aliases"] == ["acme detail"]  # the mint-time normalized alias
            assert payload["registryIds"] == {}
            assert payload["redirectedFrom"] is None

    run_async(scenario())


# --- neutral vs relative --------------------------------------------------------------------


def test_account_summary_is_a_typed_current_claim_not_a_generic_fact() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await _account_summary_claim(
                conn,
                account_id=fixture.acme,
                paragraphs=(
                    "Acme operates a multi-site care network.",
                    "Its current research record highlights expansion and staffing pressure.",
                ),
            )

            payload = (await _get(conn, fixture.acme)).json()
            assert payload["summary"] == {
                "state": "available",
                "paragraphs": [
                    "Acme operates a multi-site care network.",
                    "Its current research record highlights expansion and staffing pressure.",
                ],
                "researchOutcome": "completed",
            }
            assert ACCOUNT_SUMMARY not in _facts(payload)

    run_async(scenario())


def test_account_summary_distinguishes_not_composed_from_restricted() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert (await _get(conn, fixture.acme)).json()["summary"] == {
                "state": "not_composed",
                "paragraphs": [],
                "researchOutcome": None,
            }

            await _account_summary_claim(
                conn,
                account_id=fixture.acme,
                paragraphs=("This rejected prose must never be served.",),
                status=VerificationStatus.REJECTED,
            )
            summary = (await _get(conn, fixture.acme)).json()["summary"]
            assert summary == {
                "state": "restricted",
                "paragraphs": [],
                "researchOutcome": None,
            }
            assert "rejected prose" not in str(summary)

    run_async(scenario())


def test_neutral_facts_are_served_once_not_once_per_project() -> None:
    """A ``project_neutral`` field is workspace truth: it serves from the canonical merge, at the
    top level, regardless of which project's run happened to write it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()

            facts = _facts(payload)
            assert facts["core.employee_count"]["value"] == 1200
            assert facts["core.revenue_band"]["value"] == "100m_500m"
            # Once each — not repeated per project.
            assert [fact["fieldKey"] for fact in payload["neutralFacts"]].count(
                "core.employee_count"
            ) == 1
            assert facts["core.employee_count"]["freshness"] in {"fresh", "stale"}
            assert facts["core.employee_count"]["provider"] == "clearbit"
            assert facts["core.employee_count"]["observedAt"].startswith("2026-08-01")
            evidence = facts["core.employee_count"]["evidence"]
            assert evidence["fieldKey"] == "core.employee_count"
            assert evidence["sourceTitle"] == "clearbit"
            assert evidence["sourceUrl"] == "https://example.test/facts"
            assert evidence["evidenceSpan"] == "seeded"
            assert evidence["confidence"] == pytest.approx(0.9)
            assert evidence["freshness"] == facts["core.employee_count"]["freshness"]
            assert evidence["protectedArtifactAvailable"] is True
            assert evidence["claimId"]

            # ...and no neutral field leaks into a project section.
            for section in payload["projectSections"]:
                keys = {entry["fieldKey"] for entry in section["insights"]}
                assert "core.employee_count" not in keys
                assert "core.revenue_band" not in keys

    run_async(scenario())


def test_retained_account_evidence_is_streamed_after_current_authorization_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            storage = _MemoryStorage({_EMPLOYEE_ARTIFACT_KEY: _EMPLOYEE_ARTIFACT_BODY})
            payload = (await _get(conn, fixture.acme, evidence_storage=storage)).json()
            evidence = _facts(payload)["core.employee_count"]["evidence"]
            assert evidence["protectedArtifactAvailable"] is True
            assert _EMPLOYEE_ARTIFACT_KEY not in str(payload)

            path = f"{_BASE}/{fixture.acme}/evidence/{evidence['claimId']}"
            async with _client(_app(conn, evidence_storage=storage)) as client:
                response = await client.get(path, headers={"X-Workspace-Id": _WS})
                crossed = await client.get(path, headers={"X-Workspace-Id": _OTHER_WS})
                unknown = await client.get(
                    f"{_BASE}/{fixture.acme}/evidence/{uuid.uuid4()}",
                    headers={"X-Workspace-Id": _WS},
                )

            assert response.status_code == 200
            assert response.content == _EMPLOYEE_ARTIFACT_BODY
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["content-security-policy"].startswith("sandbox")
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "signed" not in str(response.headers).lower()
            assert crossed.status_code == 404
            assert crossed.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
            assert unknown.status_code == 404

            await conn.execute(
                text("UPDATE artifact SET erased_at=now() WHERE storage_key=:key"),
                {"key": _EMPLOYEE_ARTIFACT_KEY},
            )
            async with _client(_app(conn, evidence_storage=storage)) as client:
                erased = await client.get(path, headers={"X-Workspace-Id": _WS})
            assert erased.status_code == 404
            assert erased.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

    run_async(scenario())


def test_each_projects_relative_claims_stay_inside_its_own_section() -> None:
    """The whole point of the lineage join: project B's narrative/insight/score can never be
    rendered as project A's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()
            sections = _sections(payload)

            section_a = sections[fixture.project_a.project_id]
            section_b = sections[fixture.project_b.project_id]

            assert section_a["addedVia"] == "discovered"
            assert section_b["addedVia"] == "imported"
            # Each section names its own project (FI-1 §9 plan-owner addendum), from the same
            # batched read the list row uses — so the two surfaces cannot disagree on a name.
            assert section_a["name"] == "Detail project A"
            assert section_b["name"] == "Detail project B"

            assert _values(section_a["insights"]) == ["insight for A"]
            assert _values(section_b["insights"]) == ["insight for B"]
            for insight in (*section_a["insights"], *section_b["insights"]):
                assert insight["evidence"]["fieldKey"] == _INSIGHT_FIELD
                assert insight["evidence"]["sourceUrl"] == "https://example.test/facts"
                assert insight["evidence"]["evidenceSpan"] == "seeded"

            assert [entry["value"]["argument"] for entry in section_a["narratives"]] == [
                "narrative for A"
            ]
            assert [entry["value"]["argument"] for entry in section_b["narratives"]] == [
                "narrative for B"
            ]

            assert [score["icpKey"] for score in section_a["scores"]] == ["alpha"]
            assert section_a["scores"][0]["fit"] == pytest.approx(0.81)
            assert section_a["scores"][0]["intent"] == pytest.approx(0.40)
            assert [score["icpKey"] for score in section_b["scores"]] == ["beta"]
            assert section_b["scores"][0]["fit"] == pytest.approx(0.55)
            # An unscored half is null, never a fabricated zero.
            assert section_b["scores"][0]["intent"] is None

    run_async(scenario())


def test_claims_whose_run_maps_to_no_project_land_in_the_unattributed_section() -> None:
    """Both exemption shapes — a registered run with a NULL project (ingestion/manual) and a run
    with no ``run_lineage`` row at all — are reported, not silently dropped."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()
            sections = _sections(payload)

            assert None in sections, "the unattributed section must exist when claims need it"
            unattributed = sections[None]
            assert unattributed["addedVia"] is None
            assert unattributed["addedAt"] is None
            # There is no project to name, so the slot is null — not the empty string, and not the
            # id echoed back as a pseudo-name.
            assert unattributed["name"] is None
            assert sorted(_values(unattributed["insights"])) == [
                "insight from a manual ingestion",
                "insight from an unregistered run",
            ]
            # ...and those claims are in NO project's section.
            for project_id in (fixture.project_a.project_id, fixture.project_b.project_id):
                assert _values(sections[project_id]["insights"]) == [
                    f"insight for {'A' if project_id == fixture.project_a.project_id else 'B'}"
                ]

    run_async(scenario())


def test_a_lineage_derived_section_with_no_project_row_is_named_null_not_guessed() -> None:
    """``run_lineage.project_id`` carries **no** FK to ``project``, so a section id can name a
    project this workspace holds no row for — a stale id, or (the case this seeds) another
    workspace's project. The section is still served, with its id, and its ``name`` is ``null``:
    dropping it would hide the account's work, and resolving the name across the workspace boundary
    would leak another tenant's label onto this response."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            foreign = await seed_project(conn, _OTHER_WS, name="Another tenant's project")
            await _account_claim(
                conn,
                account_id=fixture.acme,
                field_key=_INSIGHT_FIELD,
                value="insight attributed to a project row this workspace does not hold",
                run_id=await _run(conn, kind="entity_research", project_id=foreign.project_id),
                source_key="deep_research",
                private=True,
            )

            sections = _sections((await _get(conn, fixture.acme)).json())
            section = sections[foreign.project_id]
            assert section["name"] is None
            assert section["addedVia"] is None, "no membership either — it is not our project"
            assert _values(section["insights"]) == [
                "insight attributed to a project row this workspace does not hold"
            ]
            assert "Another tenant's project" not in str(sections)

    run_async(scenario())


def test_section_names_are_one_batched_read_not_one_query_per_section() -> None:
    """The name join must not become a per-section lookup on the surface most likely to grow one.

    Measured, not asserted in a comment: the endpoint's statement count is captured over the base
    fixture and again after three more *lineage-derived* sections appear. Lineage ids are the
    unbounded axis here — a project needs no membership row to attribute work to this account — so
    a per-section name lookup would grow the count by three; a batched read costs the same either
    way. Growth is deliberately seeded through lineage rather than membership, because the
    committee composition already issues one documented ``latest_project_run_context`` query per
    *membership* and would mask the signal this guard is watching for.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            baseline, before = await _count_statements(conn, fixture.acme)

            for ordinal in range(3):
                ghost = await seed_project(conn, _WS, name=f"Lineage-only project {ordinal}")
                await _account_claim(
                    conn,
                    account_id=fixture.acme,
                    field_key=_INSIGHT_FIELD,
                    value=f"insight attributed only through lineage {ordinal}",
                    run_id=await _run(conn, kind="entity_research", project_id=ghost.project_id),
                    source_key="deep_research",
                    private=True,
                )
            widened, after = await _count_statements(conn, fixture.acme)

            assert len(_sections(after)) == len(_sections(before)) + 3, "sections really did grow"
            # Without the lower bound the guard is vacuous: a harness change that stops the
            # listener firing would compare 0 == 0 and pass an endpoint full of per-section reads.
            assert baseline > 0, "the listener really fired"
            assert widened == baseline

    run_async(scenario())


def test_the_relative_field_set_is_read_from_the_registry_not_a_hardcoded_list() -> None:
    """``fi2read.campaign_insight`` is an ordinary pack field; it reaches ``insights`` only
    because the registry says it is ``project_relative``. A read layer with a hardcoded family
    list could not do this."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_research.claimstore import get_field

            fixture = await _build(conn)
            field = await get_field(conn, _INSIGHT_FIELD)
            assert field is not None and field.research_scope is ResearchScope.PROJECT_RELATIVE

            payload = (await _get(conn, fixture.acme)).json()
            assert _INSIGHT_FIELD not in _facts(payload)
            assert _INSIGHT_FIELD in {
                entry["fieldKey"]
                for section in payload["projectSections"]
                for entry in section["insights"]
            }

    run_async(scenario())


# --- committee ------------------------------------------------------------------------------


def test_the_committee_is_served_through_the_governed_reader_and_carries_its_projects() -> None:
    """A strongly-bound member appears once with the projects that target them; a member whose
    role/persona binding is WEAK is **absent** — governance blanks it rather than fabricating an
    unbound person, and the endpoint does not crash on the gap."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()

            members = {member["contactId"]: member for member in payload["committee"]}
            assert str(fixture.champion) in members
            assert str(fixture.ghost) not in members

            champion = members[str(fixture.champion)]
            assert champion["name"] == "Dana Buyer"
            assert champion["persona"] == Persona.ECONOMIC_BUYER.value
            assert champion["roleOnCommittee"] == Persona.ECONOMIC_BUYER.value
            # Only project A ran the committee research, so only A targets this member.
            assert champion["projectIds"] == [fixture.project_a.project_id]

    run_async(scenario())


def test_a_workspace_that_will_not_display_professional_facts_has_an_empty_committee() -> None:
    """The detail view's ``committee[]`` and the contacts endpoints render the same people from the
    same resolver, so they must agree on the workspace display policy. Until the shared
    ``committee_member_displayable`` gate landed they did not: this block listed names, personas and
    roles for members whose very role/persona claims the policy refuses to display, while
    `/accounts/{id}/contacts` correctly served nothing. Same data, two answers — the leak was here.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert (await _get(conn, fixture.acme)).json()["committee"], (
                "populated before the policy"
            )

            await conn.execute(
                text(
                    "INSERT INTO workspace_policy (policy_id, workspace_id, posture, "
                    "display_professional_public, version) "
                    "VALUES (:pid, :ws, 'conservative_default', false, 9)"
                ),
                {"pid": f"p-{uuid.uuid4()}", "ws": _WS},
            )
            payload = (await _get(conn, fixture.acme)).json()
            assert payload["committee"] == []
            # ...and the rest of the account is untouched: this is a contact-display policy, not a
            # blackout.
            assert _facts(payload)["core.employee_count"]["value"] == 1200

    run_async(scenario())


# --- redirect & 404 -------------------------------------------------------------------------


def test_a_merged_loser_redirects_to_its_survivor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            loser = await _account(conn, name="Acme Dup", domain="acme-dup.test")
            await mark_merged(conn, EntityType.ACCOUNT, loser_id=loser, survivor_id=fixture.acme)

            response = await _get(conn, loser)
            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == str(fixture.acme)
            assert payload["name"] == "Acme Detail"
            assert payload["redirectedFrom"] == str(loser)

    run_async(scenario())


def test_an_unknown_id_is_an_enveloped_404() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            response = await _get(conn, uuid.uuid4())
            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "ACCOUNT_NOT_FOUND"
            assert error["requestId"]

    run_async(scenario())


def test_the_workspace_client_cannot_be_opened_as_a_target_account() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            client = await _account(
                conn,
                name="Insight Health",
                domain="insighthealth.ai",
            )
            await bind_workspace_client(
                conn,
                workspace_id=_WS,
                client_entity_id=client,
            )

            response = await _get(conn, client)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    run_async(scenario())


def test_an_account_in_another_workspace_is_a_404_not_a_leak() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            foreign = await _account(
                conn, name="Foreign", domain="foreign.test", workspace_id=_OTHER_WS
            )
            response = await _get(conn, foreign)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    run_async(scenario())


# --- coverage & wire discipline ---------------------------------------------------------------


def test_coverage_counts_the_fields_the_account_actually_holds() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()
            coverage = payload["coverage"]
            # employee_count, revenue_band, scoring.fit, scoring.intent, value_narrative, insight
            assert coverage["researchedFieldCount"] == 6
            assert coverage["unresolvedFieldKeys"] == []

    run_async(scenario())


def test_coverage_reports_only_the_accounts_own_unresolved_fields() -> None:
    """An **account** research result also carries the fields of every contact subject it
    discovered (``_flatten_result_fields`` folds ``discovered_subjects`` into the account's result
    row). A coverage read that filtered on the *result*'s subject alone would report a contact's
    unsupported field as the account's — and it could never clear, because answering it writes a
    contact claim that never enters this account's held-key set.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            subject = await _account(conn, name="Coverage", domain="coverage.test")
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_entity_id=subject,
                added_via="manual",
            )
            contact = await insert_contact_entity(
                conn,
                account_entity_id=subject,
                full_name="Discovered Person",
                linkedin_url="https://linkedin.com/in/discovered-person",
                status=AccountStatus.ACTIVE,
            )
            await _plant_research_result_fields(
                conn,
                account_id=subject,
                project_id=fixture.project_a.project_id,
                fields=(
                    (_REQUESTED_FIELD, "account", subject),
                    ("contact.current_title", "contact", contact),
                ),
            )

            coverage = (await _get(conn, subject)).json()["coverage"]
            assert coverage["unresolvedFieldKeys"] == [_REQUESTED_FIELD]
            assert "contact.current_title" not in coverage["unresolvedFieldKeys"]

    run_async(scenario())


def test_unresolved_pack_fields_carry_their_registry_description() -> None:
    """A new industry-pack key needs no frontend label map: its registry row explains the gap."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            subject = await _account(conn, name="Pack gap", domain="pack-gap.test")
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_entity_id=subject,
                added_via="manual",
            )
            await _plant_research_result_fields(
                conn,
                account_id=subject,
                project_id=fixture.project_a.project_id,
                fields=(("healthcare.npi", "account", subject),),
            )

            coverage = (await _get(conn, subject)).json()["coverage"]
            assert coverage["unresolvedFieldKeys"] == ["healthcare.npi"]
            assert coverage["unresolvedFields"] == [
                {
                    "fieldKey": "healthcare.npi",
                    "description": (
                        "National Provider Identifier (deterministic registry id; tier-1)."
                    ),
                }
            ]

    run_async(scenario())


def test_an_unresolved_field_clears_once_the_account_holds_a_claim_for_it() -> None:
    """``unresolvedFieldKeys`` is a live gap report, not a scar: a field research once failed on
    is not unresolved after it is answered."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            subject = await _account(conn, name="Healed", domain="healed.test")
            await _plant_research_result_fields(
                conn,
                account_id=subject,
                project_id=fixture.project_a.project_id,
                fields=((_REQUESTED_FIELD, "account", subject),),
            )
            assert (await _get(conn, subject)).json()["coverage"]["unresolvedFieldKeys"] == [
                _REQUESTED_FIELD
            ]

            await _account_claim(
                conn,
                account_id=subject,
                field_key=_REQUESTED_FIELD,
                value={"round": "series_b", "amount_usd": 42000000},
                run_id=await _run(conn, kind="enrichment", project_id=None),
            )
            assert (await _get(conn, subject)).json()["coverage"]["unresolvedFieldKeys"] == []

    run_async(scenario())


def test_a_deactivated_relative_field_keeps_its_species() -> None:
    """Species is a property of the *declaration*, not of activation: deactivating a
    ``project_relative`` pack field must not migrate its existing claims out of their project
    section and into ``neutralFacts`` — a bucket change with no data change."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await conn.execute(
                text("UPDATE field_definition SET active = false WHERE field_key = :key"),
                {"key": _INSIGHT_FIELD},
            )
            payload = (await _get(conn, fixture.acme)).json()

            assert _INSIGHT_FIELD not in _facts(payload)
            section_a = _sections(payload)[fixture.project_a.project_id]
            assert _values(section_a["insights"]) == ["insight for A"]

    run_async(scenario())


def test_no_display_strings_reach_the_wire() -> None:
    """Band-2: enums, numbers, ISO timestamps, opaque ids — no ``*Label`` / formatted text."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _get(conn, fixture.acme)).json()

            def walk(node: Any, path: str = "") -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        assert not key.endswith("Label"), f"display string at {path}.{key}"
                        assert key not in {"displayName", "formatted", "text"}
                        walk(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        walk(value, f"{path}[{index}]")

            walk(payload)

    run_async(scenario())


def test_the_detail_never_scopes_a_claim_read_by_claim_workspace_id() -> None:
    """The slice-0 trap: a DB CHECK forces ``claim.workspace_id`` NULL on public claims, so that
    predicate silently *empties* a read instead of narrowing it. A grep, because the failure mode
    is a plausible short answer no fixture can catch."""

    from pathlib import Path

    import clue_api.frontend_read.account_detail as module

    source = Path(module.__file__).read_text()
    assert "claim.workspace_id" not in source.split('"""', 2)[2]


def test_the_lineage_join_dispatches_on_project_id_never_on_kind() -> None:
    """``run_lineage.run_id`` is a mixed id space and ``kind`` is advisory first-writer-wins."""

    from clue_api.frontend_read import account_detail

    assert "l.project_id" in account_detail.RELATIVE_CLAIMS_TEMPLATE
    assert "kind" not in account_detail.RELATIVE_CLAIMS_TEMPLATE


def test_a_workspace_header_is_structurally_required() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            async with _client(_app(conn)) as client:
                response = await client.get(f"{_BASE}/{fixture.acme}")
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


def test_a_non_uuid_id_is_an_enveloped_validation_error() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            response = await _get(conn, "not-a-uuid")
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    run_async(scenario())


def test_the_committee_reader_is_not_the_ungoverned_identity_helper() -> None:
    """FI-1 §4.5 and Slice-3: Account detail delegates to the one governed committee seam."""

    from pathlib import Path

    import clue_api.frontend_read.account_detail as module
    import clue_api.frontend_read.committee as committee

    body = Path(module.__file__).read_text().split('"""', 2)[2]
    committee_body = Path(committee.__file__).read_text().split('"""', 2)[2]
    assert "contact_ids_for_account" not in body + committee_body
    assert "read_governed_committee" in body
    assert "ContactEligibilityResolver" in committee_body


def test_the_unattributed_section_is_absent_when_everything_is_attributed() -> None:
    """Honest, not decorative: no unattributable claim means no unattributed section."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            clean = await _account(conn, name="Tidy", domain="tidy.test")
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_entity_id=clean,
                added_via="manual",
            )
            await _account_claim(
                conn,
                account_id=clean,
                field_key=_INSIGHT_FIELD,
                value="attributed insight",
                run_id=await _run(
                    conn, kind="entity_research", project_id=fixture.project_a.project_id
                ),
                private=True,
            )
            payload = (await _get(conn, clean)).json()
            assert None not in _sections(payload)
            assert list(_sections(payload)) == [fixture.project_a.project_id]

    run_async(scenario())


def test_a_membership_less_account_still_renders_its_neutral_facts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            seedling = await _account(conn, name="Seedling", domain=None)
            await _account_claim(
                conn,
                account_id=seedling,
                field_key="core.employee_count",
                value=17,
                run_id=await _run(conn, kind="stage0", project_id=None),
                source_key="stage0",
            )
            payload = (await _get(conn, seedling)).json()
            assert payload["domain"] is None
            assert _facts(payload)["core.employee_count"]["value"] == 17
            assert payload["projectSections"] == []
            assert payload["committee"] == []

    run_async(scenario())


def test_an_empty_account_is_a_valid_all_empty_detail() -> None:
    """An empty, flagged field is a correct output — never a 500 and never a fabrication."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            bare = await _account(conn, name="Bare", domain=None)
            payload = (await _get(conn, bare)).json()
            assert payload["neutralFacts"] == []
            assert payload["projectSections"] == []
            assert payload["committee"] == []
            assert payload["coverage"]["researchedFieldCount"] == 0

    run_async(scenario())


def test_the_route_is_absent_when_the_flag_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            app = create_projections_app(
                surface=None,  # type: ignore[arg-type]
                tool_invoker=None,  # type: ignore[arg-type]
                settings=load_settings(_env_file=None, frontend_read_enabled=False),
                conn_factory=conn_session_factory(conn),
                manage_db_lifespan=False,
            )
            async with _client(app) as client:
                response = await client.get(
                    f"{_BASE}/{fixture.acme}", headers={"X-Workspace-Id": _WS}
                )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "NOT_FOUND"
            assert response.json()["error"]["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_the_project_run_context_rule_is_latest_run_wins() -> None:
    """THE per-project committee-context rule, recorded once: the project's most recent
    ``project_run`` supplies ``(project_run_id, product_id)``."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.frontend_read.committee import latest_project_run_context

            fixture = await _build(conn)
            newer = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=newer,
                project_id=fixture.project_a.project_id,
                workspace_id=_WS,
                icp_key="alpha",
                icp_version=2,
            )
            await conn.execute(
                text(
                    "UPDATE project_run SET created_at = now() + interval '1 hour' WHERE id = :id"
                ),
                {"id": newer},
            )
            context = await latest_project_run_context(
                conn, workspace_id=_WS, project_id=fixture.project_a.project_id
            )
            assert context is not None
            assert context.project_run_id == newer
            assert context.product_id is None

            assert (
                await latest_project_run_context(
                    conn, workspace_id=_WS, project_id="no-such-project"
                )
                is None
            )

    run_async(scenario())


# --- ARV2 D3 E2: the contract-v1 detail under ``?contract=v1`` ---------------------------------
#
# The D3 ruling: contract v1 is selected per request. Everything above this line is the FI-2
# contract and keeps passing byte-for-byte — one route serves both until the D4 re-lift retires
# the FI-2 branch, so no FI-2 field is renamed, wrapped or removed here.
#
# Two fixture choices are deliberate and recorded rather than left to be re-derived:
#
# * **the committee reaches the page through D2's fallback member source** — every contact under
#   the account that holds a live claim — not through an ``entity_research_account_coverage``
#   row. ``committee_members`` supports both, and the fallback is the shape a workspace is
#   actually in until a fleet run publishes coverage;
# * **every claim is written through the D1 lenient writer**, not through ``insert_claim``. The
#   registry declares ``account.total_funding`` an object, while the provider the ARV2 lane
#   actually reads returns the string ``"$130.5M"``. The
#   lenient writer is the lane's own write path and stores exactly that, so the rail labels here
#   are proven against the shapes production really holds.


#: The retained evidence behind Dana's title claim — the one the stored overview section cites.
_TITLE_ARTIFACT_BODY = b"Dana Katz, VP of Security at Zafran."
_TITLE_ARTIFACT_KEY = artifact_key(_WS, content_address(_TITLE_ARTIFACT_BODY))


async def _seed_user(
    conn: AsyncConnection,
    user_id: str,
    *,
    display_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> str:
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name, first_name, last_name) "
            "VALUES (:u, :d, :f, :l) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id, "d": display_name, "f": first_name, "l": last_name},
    )
    return user_id


async def _lenient_claim(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    entity_type: EntityType,
    field_key: str,
    value: Any,
    research_mode: ResearchMode = ResearchMode.ACCOUNT_PROFILING,
    **overrides: Any,
) -> str:
    """One claim through the D1 lenient writer — the ARV2 lane's own write path, deliberately.

    The whole v1 fixture writes this way because the *lane* writes this way, and the difference is
    load-bearing for the rail labels: ``insert_claim`` validates a value against the registry's
    declared schema, while the D1 writer stores what the provider actually returned and records
    the divergence as a marker. ``account.total_funding`` is declared an object and comes back
    ``"$130.5M"``; ``core.work_email`` is declared a string and comes back
    ``{address, status}``. Writing this fixture strictly would therefore let the endpoint be
    proven against shapes the ARV2 lane never stores.
    """
    receipt = await LenientClaimWriter(lenient=True).write(
        conn,
        ClaimDraft(
            entity_id=entity_id,
            entity_type=entity_type,
            field_key=field_key,
            value_json=value,
            extraction_method=ExtractionMethod.API,
            run_id=new_run_id(),
            research_mode=research_mode,
            workspace_id=_WS,
            **overrides,
        ),
    )
    return str(receipt.claim_id)


async def _v1_contact(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    name: str,
    suffix: str,
    persona: str,
    title: str,
    email: str,
    rationale: str,
    title_artifact_key: str | None = None,
) -> tuple[EntityId, str, str]:
    """One committee member with the four claims the account detail reads about them.

    Returns ``(contact id, title claim id, work-email claim id)`` — the two claim ids the
    assertions need to name.
    """
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=name,
        linkedin_url=f"https://www.linkedin.com/in/{suffix}",
        status=AccountStatus.ACTIVE,
    )
    title_claim_id = await _lenient_claim(
        conn,
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key="contact.current_title",
        value=title,
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://zafran.io/team",
        evidence_span=f"{name}, {title} at Zafran.",
        # Stamped at write time, never patched afterwards: ``claim`` is append-only and its
        # provenance columns are immutable by trigger.
        artifact_key=title_artifact_key,
    )
    for field_key, value in (
        ("contact.persona", persona),
        ("contact.role_on_committee", {"role": persona, "rationale": rationale}),
    ):
        await _lenient_claim(
            conn,
            entity_id=contact,
            entity_type=EntityType.CONTACT,
            field_key=field_key,
            value=value,
            research_mode=ResearchMode.CONTACT_PROFILING,
            source_url="https://zafran.io/team",
        )
    email_claim_id = await _lenient_claim(
        conn,
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key="core.work_email",
        value={"address": email, "status": "verified_smtp"},
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://zafran.io/team",
    )
    return contact, title_claim_id, email_claim_id


async def _finalize_job(conn: AsyncConnection, job_id: uuid.UUID, *, outcome: str) -> None:
    """Drive a launched job to its terminal row (its own lifecycle is R2's suite's subject)."""
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'terminal',
                finalization_outcome = :outcome,
                finalization_receipt_ref = :receipt,
                terminal_at = now()
            WHERE job_id = :job_id
            """
        ),
        {"outcome": outcome, "receipt": f"receipt:{job_id}", "job_id": job_id},
    )


async def _seed_overview_block(
    conn: AsyncConnection, *, account_id: EntityId, cited: Sequence[str], now: datetime
) -> None:
    """One live ``overview/what-they-do`` block, written by hand through D2's own ``insert_block``.

    No model is called: what this fixture needs is a *stored* section, and building the draft here
    is how the read surface can be proven to compose what is stored rather than to write anything.

    ``cited`` deliberately mixes an account claim with a **contact** claim — an overview section
    legitimately speaks about both — which is what makes the E7 union testable: a contact claim is
    evidence the v1 page cites and the FI-2 body never exposes.
    """
    recipe = next(item for item in recipes_for("overview") if item.section_key == "what-they-do")
    claims = await claims_by_ids(
        conn,
        [ClaimId(uuid.UUID(claim_id)) for claim_id in cited],
        scope=WorkspaceScope.for_workspace(_WS),
    )
    section = SectionInput(
        recipe=recipe,
        claims=tuple(display_claim(claim, subject=None) for claim in claims.values()),
        deduped={},
    )
    draft = SectionDraft(
        section_key=recipe.section_key,
        intro=[
            {
                "text": "Zafran runs a threat-exposure management platform.",
                "claimIds": [cited[0]],
            }
        ],
        items=[
            {
                "id": "what-they-do-1",
                "h2": "Exposure management, not another scanner",
                "body": [
                    {"text": "They mitigate what they cannot patch.", "claimIds": list(cited)}
                ],
                "sendLine": None,
                "contactRefs": [],
                "priority": 1,
                "newSinceLastVisit": False,
            }
        ],
        cited_claim_ids=list(cited),
        checks={"unknown_aliases": [], "off_recipe": []},
        aliases={f"c{index}": claim_id for index, claim_id in enumerate(cited, start=1)},
        cost=None,
        model="x-ai/grok-4.6",
        raw_refs=(),
    )
    await insert_block(
        conn,
        workspace_id=_WS,
        subject_kind="account",
        subject_id=str(account_id),
        page="overview",
        recipe=recipe,
        draft=draft,
        section=section,
        now=now,
    )


class _V1Fixture:
    def __init__(
        self,
        *,
        base: _Fixture,
        zafran: EntityId,
        dana: EntityId,
        ravi: EntityId,
        cited_claim_ids: tuple[str, ...],
        email_claim_ids: tuple[str, ...],
        created_at: datetime,
    ) -> None:
        self.base = base
        self.zafran = zafran
        self.dana = dana
        self.ravi = ravi
        #: What the stored overview section cites: ``(account claim, Dana's title claim)``.
        self.cited_claim_ids = cited_claim_ids
        self.email_claim_ids = email_claim_ids
        self.created_at = created_at


async def _build_v1(conn: AsyncConnection) -> _V1Fixture:
    """The FI-2 fixture plus one fully-populated account — the shape the v1 detail is built for.

    Zafran carries every source the v1 detail composes: the rail's neutral facts, an owner and a
    creator, memberships in both projects, a fit score under the *primary* project (and a lower
    one under the other, so attribution is provable), a finished research job, two committee
    members with their titles/personas/roles/emails, one stored overview section, and one activity
    event. The FI-2 accounts stay exactly as they were, so both halves of this file share a seed.
    """
    base = await _build(conn)
    await load_core_pack(conn)
    await load_arv2_pack(conn)
    await load_display_recipes(conn)
    await _seed_user(conn, "u_owner", display_name="Ada Lovelace")
    await _seed_user(conn, "u_creator", first_name="Grace", last_name="Hopper")

    created_at = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
    zafran = await _account(conn, name="Zafran", domain="zafran.io")
    await conn.execute(
        text(
            "UPDATE account_entity SET created_at = :at, owner_user_id = 'u_owner', "
            "created_by_user_id = 'u_creator' WHERE id = :id"
        ),
        {"at": created_at, "id": zafran},
    )
    membership_base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    for project, added_via, offset in (
        (base.project_a, "discovered", timedelta()),
        (base.project_b, "imported", timedelta(minutes=5)),
    ):
        await ensure_project_account(
            conn,
            workspace_id=_WS,
            project_id=project.project_id,
            account_entity_id=zafran,
            added_via=added_via,
            added_at=membership_base + offset,
        )

    cited_claim_id: str | None = None
    for field_key, value in (
        ("core.employee_count", 167),
        # The registry shapes, not convenient strings: ``employee_range`` is an object whose only
        # required key is ``label``, ``hq_location`` an object whose required key is ``raw``.
        ("core.employee_range", {"label": "51-200", "min": 51, "max": 200}),
        ("core.revenue_band", "50m_100m"),
        ("core.annual_revenue", "$45M ARR"),
        ("core.hq_location", {"raw": "Tel Aviv, Israel", "city": "Tel Aviv", "country": "Israel"}),
        ("core.industry", "Cybersecurity"),
        ("core.industries_all", ["Cybersecurity", "Security software"]),
        ("core.company_linkedin_url", "https://www.linkedin.com/company/zafran"),
        ("core.founded_year", 2022),
        ("account.recent_funding", {"round": "Series C", "amount_usd": 60000000}),
        ("account.total_funding", "$130.5M"),
    ):
        claim_id = await _lenient_claim(
            conn,
            entity_id=zafran,
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value=value,
            source_key="exa_contents",
            source_url="https://zafran.io/about",
            evidence_span="Zafran is a cybersecurity company.",
        )
        if field_key == "core.industry":
            cited_claim_id = claim_id
    assert cited_claim_id is not None

    await _score(
        conn,
        account_id=zafran,
        project_id=base.project_a.project_id,
        fit=0.82,
        intent=0.5,
        icp_key="alpha",
        icp_version=1,
    )
    # A *lower* score under the non-primary project: the detail must report the primary project's
    # fit, never whichever score happens to sort first.
    await _score(
        conn,
        account_id=zafran,
        project_id=base.project_b.project_id,
        fit=0.20,
        intent=None,
        icp_key="beta",
        icp_version=3,
    )
    # The v1 detail's research status comes from ARV2's own rows and nothing else (D4-b decision
    # 1), so the seed is an ``arv2_research_job`` driven through the R2 store — not an M8D job.
    await seed_arv2_job(conn, project=base.project_a, account_id=zafran, status="completed")

    # Dana's title claim carries a retained artifact from birth: the stored overview section
    # cites it, which is what makes the E7 union (FI-2 evidence ∪ v1 page citations) provable.
    await record_artifact(
        conn,
        storage_key=_TITLE_ARTIFACT_KEY,
        workspace_id=_WS,
        content_sha256=content_address(_TITLE_ARTIFACT_BODY),
        media_type="text/plain",
        size_bytes=len(_TITLE_ARTIFACT_BODY),
        source_key="exa_contents",
        source_url="https://zafran.io/team",
    )
    dana, dana_title, dana_email = await _v1_contact(
        conn,
        title_artifact_key=_TITLE_ARTIFACT_KEY,
        account_id=zafran,
        name="Dana Katz",
        suffix="dana-katz",
        persona="economic_buyer",
        title="VP of Security",
        email="dana@zafran.io",
        rationale="Owns the security budget.",
    )
    ravi, _ravi_title, ravi_email = await _v1_contact(
        conn,
        account_id=zafran,
        name="Ravi Mehta",
        suffix="ravi-mehta",
        persona="champion",
        title="Director of Detection Engineering",
        email="ravi@zafran.io",
        rationale="Runs the team that would use it.",
    )

    cited = (cited_claim_id, dana_title)
    await _seed_overview_block(conn, account_id=zafran, cited=cited, now=datetime.now(UTC))
    await conn.execute(
        text(
            "INSERT INTO account_activity_event (workspace_id, account_entity_id, kind, "
            "actor_kind, text, action, occurred_at) "
            "VALUES (:w, :a, 'summary', 'clue', :t, :ac, :o)"
        ),
        {
            "w": _WS,
            "a": zafran,
            "t": "Summary refreshed",
            "ac": "View summary",
            "o": datetime.now(UTC) - timedelta(hours=3),
        },
    )
    return _V1Fixture(
        base=base,
        zafran=zafran,
        dana=dana,
        ravi=ravi,
        cited_claim_ids=cited,
        email_claim_ids=(dana_email, ravi_email),
        created_at=created_at,
    )


def _overview(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {section["key"]: section for section in payload["overviewDisplay"]["sections"]}


def test_the_v1_contract_serves_the_account_detail_for_a_fully_populated_account() -> None:
    """Every v1 field of the detail, composed from the sources decisions 5/8/9/15/16 name — and
    the whole body validated twice: by the strict pydantic model and by the frontend's own Zod."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            response = await _get(conn, fixture.zafran, contract="v1")
            assert response.status_code == 200
            body = response.json()

            # The envelope, and the strict wire model: extra keys forbidden, required-nullable
            # fields present.
            assert set(body) == {"data"}
            AccountDetailResponseV1.model_validate(body)
            detail = body["data"]

            assert detail["id"] == str(fixture.zafran)
            assert detail["name"] == "Zafran"
            assert detail["previewTitle"] == "Zafran"
            assert detail["logoPath"] is None
            assert detail["websiteUrl"] == "https://zafran.io"
            assert detail["websiteLabel"] == "zafran.io"
            assert detail["researchStatus"] == "completed"
            assert detail["researchStatusLabel"] == "Researched"
            assert detail["owner"] == {"id": "u_owner", "name": "Ada Lovelace"}
            assert detail["createdBy"] == {"id": "u_creator", "name": "Grace Hopper"}
            assert detail["industryLabels"] == ["Cybersecurity", "Security software"]
            assert detail["headcountLabel"] == "167 (51-200)"
            assert detail["locationsLabel"] == "Tel Aviv, Israel"
            # ``revenue_label``'s shipped rule: the rendered claim wins over the band.
            assert detail["revenueLabel"] == "$45M ARR"
            assert detail["foundedLabel"] == "2022"
            # The round object's own ``amount_usd`` becomes ``$60M``; the total is stored here as
            # prose and is served as the sentence it is.
            assert detail["fundingLabel"] == "Series C · $60M · $130.5M"
            assert detail["overallFit"] == "High"
            assert detail["fitScore"] == 82
            assert "fitScoreLabel" not in detail
            assert detail["createdAt"] == "2026-08-01T15:00:00Z"
            assert detail["lastModifiedAt"].endswith("Z")
            assert detail["lastModifiedAt"] >= detail["createdAt"]
            assert detail["socials"] == [
                {
                    "id": "linkedin",
                    "label": "LinkedIn",
                    "url": "https://www.linkedin.com/company/zafran",
                }
            ]
            # The legacy slots the display layer replaced: empty lists, never absent keys.
            assert detail["summaryParagraphs"] == []
            assert detail["businessParagraphs"] == []
            assert detail["headerMetadata"] == []
            assert detail["fitCriteria"] == []
            assert detail["insights"] == []

            # --- the rail's contact chips
            assert [contact["name"] for contact in detail["contacts"]] == [
                "Dana Katz",
                "Ravi Mehta",
            ]
            assert all(contact["hasDetail"] is True for contact in detail["contacts"])
            assert detail["contacts"][0]["title"] == "VP of Security"
            assert detail["contacts"][0]["persona"] == "Economic buyer"
            assert detail["contacts"][0]["emailVerified"] is True

            # --- the buying committee, persona-ordered
            committee_rows = detail["buyingCommittee"]
            assert [row["name"] for row in committee_rows] == ["Dana Katz", "Ravi Mehta"]
            dana = committee_rows[0]
            assert dana["contactId"] == str(fixture.dana)
            assert dana["title"] == "VP of Security"
            assert dana["persona"] == "Economic buyer"
            assert dana["email"] == "dana@zafran.io"
            assert dana["emailClaimId"] == fixture.email_claim_ids[0]
            assert dana["whyTheyMatter"] == "Owns the security budget."
            assert dana["linkedinUrl"] == "https://www.linkedin.com/in/dana-katz"

            # --- the generated page: the whole recipe grammar, written section and all
            sections = _overview(detail)
            assert detail["overviewDisplay"]["page"] == "overview"
            assert list(sections) == [
                "what-they-do",
                "why-they-fit",
                "why-now",
                "buying-committee",
                "how-to-approach",
                "watch-outs",
            ]
            written = sections["what-they-do"]
            assert written["empty"] is False
            assert written["intro"][0]["text"].startswith("Zafran runs")
            assert written["items"][0]["id"] == "what-they-do-1"
            assert all(
                sections[key]["empty"] is True for key in sections if key != "what-they-do"
            ), "generation is off in this suite, so nothing else can have been written"

            # --- the evidence drawer covers every id the page and the committee cite
            evidence = {row["claimId"]: row for row in detail["researchEvidence"]}
            assert set(evidence) == {*fixture.cited_claim_ids, *fixture.email_claim_ids}
            assert all("fieldKey" not in row for row in detail["researchEvidence"])
            assert evidence[fixture.cited_claim_ids[0]]["provider"] == "Exa"

            # --- activity
            assert len(detail["activity"]) == 1
            entry = detail["activity"][0]
            assert entry["actor"] == {"type": "clue"}
            assert entry["text"] == "Summary refreshed"
            assert entry["timeLabel"] == "3 hours ago"
            assert entry["occurredAt"].endswith("Z")

            zod_validate(detail, "AccountDetailSchema")

    run_async(scenario())


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("not_started", "Not started"),
        ("in_progress", "In progress"),
        ("needs_review", "Needs review"),
        ("completed", "Researched"),
        ("suspended", "Paused"),
    ],
)
def test_the_v1_detail_serves_the_latest_arv2_job_status_verbatim(status: str, label: str) -> None:
    """All five R2 states, unmapped — and the same read the list row uses, so the table and the
    page can never disagree about one account."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            # ``_build_v1`` already researched Zafran. The two jobs would share the transaction's
            # ``now()``, so the finished one is aged first: the status under test is the *latest*
            # job's, and that must be a fact about the rows rather than about uuid ordering.
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET created_at = created_at - interval '1 hour' "
                    "WHERE account_entity_id = :id"
                ),
                {"id": fixture.zafran},
            )
            await seed_arv2_job(
                conn,
                project=fixture.base.project_a,
                account_id=fixture.zafran,
                status=cast(JobStatus, status),
            )

            detail = (await _get(conn, fixture.zafran, contract="v1")).json()["data"]
            assert detail["researchStatus"] == status
            assert detail["researchStatusLabel"] == label

    run_async(scenario())


def test_an_account_with_no_arv2_job_is_not_started_on_the_v1_detail() -> None:
    """An unresearched account is honestly unresearched; nothing is invented for the missing row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)

            detail = (await _get(conn, fixture.base.acme, contract="v1")).json()["data"]
            assert detail["researchStatus"] == "not_started"
            assert detail["researchStatusLabel"] == "Not started"

    run_async(scenario())


def test_a_job_launched_by_a_non_primary_project_still_shows_on_the_v1_detail() -> None:
    """Research is a fact about the *account*: the page reports its latest ARV2 job whichever
    project launched it, rather than reporting a researched account as never researched."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            await seed_arv2_job(
                conn,
                project=fixture.base.project_b,
                account_id=fixture.base.acme,
                status="needs_review",
            )

            detail = (await _get(conn, fixture.base.acme, contract="v1")).json()["data"]
            assert detail["researchStatus"] == "needs_review"

    run_async(scenario())


def test_the_same_id_without_the_parameter_still_serves_the_fi2_detail() -> None:
    """The ruling: no FI-2 field is renamed, wrapped or removed while both contracts are served."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            body = (await _get(conn, fixture.zafran)).json()

            assert "neutralFacts" in body
            assert "data" not in body
            assert "projectSections" in body
            assert "coverage" in body
            assert "buyingCommittee" not in body
            assert "overviewDisplay" not in body

    run_async(scenario())


def test_an_unknown_id_is_an_enveloped_404_in_v1_mode() -> None:
    """The v1 branch resolves the account by exactly the FI-2 rules, refusal included."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build_v1(conn)
            response = await _get(conn, uuid.uuid4(), contract="v1")

            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "ACCOUNT_NOT_FOUND"
            assert error["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_a_merged_loser_is_followed_silently_in_v1() -> None:
    """The FI-2 body names the id the caller asked for; the v1 shape has no ``redirectedFrom``
    slot, so the survivor is simply served."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            loser = await _account(conn, name="Zafran Dup", domain="zafran-dup.test")
            await mark_merged(conn, EntityType.ACCOUNT, loser_id=loser, survivor_id=fixture.zafran)

            detail = (await _get(conn, loser, contract="v1")).json()["data"]
            assert detail["id"] == str(fixture.zafran)
            assert detail["name"] == "Zafran"
            assert "redirectedFrom" not in detail

    run_async(scenario())


def test_the_v1_detail_is_a_constant_number_of_statements() -> None:
    """The v1 detail composes more sources than the FI-2 one; it must still cost a fixed number of
    batched reads, not one per committee member, owner or custom field.

    The growth axes are the two that could plausibly grow a per-row lookup: the committee (every
    contact under the account that holds a claim is a member) and the memberships."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1(conn)
            baseline, before = await _count_statements(conn, fixture.zafran, contract="v1")

            await _v1_contact(
                conn,
                account_id=fixture.zafran,
                name="Zoe Adler",
                suffix="zoe-adler",
                persona="technical_evaluator",
                title="Staff Engineer",
                email="zoe@zafran.io",
                rationale="Evaluates the integration.",
            )
            for ordinal in range(3):
                extra = await seed_project(conn, _WS, name=f"Extra project {ordinal}")
                await ensure_project_account(
                    conn,
                    workspace_id=_WS,
                    project_id=extra.project_id,
                    account_entity_id=fixture.zafran,
                    added_via="manual",
                    added_at=datetime(2026, 8, 2, 12, ordinal, tzinfo=UTC),
                )
            widened, after = await _count_statements(conn, fixture.zafran, contract="v1")

            assert len(before["data"]["buyingCommittee"]) == 2
            assert len(after["data"]["buyingCommittee"]) == 3, "the committee really did grow"
            assert baseline > 0, "the listener really fired"
            assert widened == baseline

    run_async(scenario())


def test_a_claim_cited_only_by_the_v1_page_is_authorised_for_the_evidence_stream() -> None:
    """E7 authorises against the union of both contracts' evidence.

    The FI-2 detail exposes account claims through ``neutralFacts``/``projectSections`` and no
    contact claim at all; the v1 page cites both. The stored overview section here cites Dana's
    **title** claim — evidence this account's screen shows and the FI-2 body never names — so it
    can only be authorised through the v1 half of the union."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage({_TITLE_ARTIFACT_KEY: _TITLE_ARTIFACT_BODY})
            fixture = await _build_v1(conn)
            contact_claim_id = fixture.cited_claim_ids[1]
            assert contact_claim_id not in str((await _get(conn, fixture.zafran)).json()), (
                "the FI-2 body must not expose it, or this test proves nothing"
            )

            path = f"{_BASE}/{fixture.zafran}/evidence/{contact_claim_id}"
            unknown = f"{_BASE}/{fixture.zafran}/evidence/{uuid.uuid4()}"
            async with _client(_app(conn, evidence_storage=storage)) as client:
                served = await client.get(path, headers={"X-Workspace-Id": _WS})
                crossed = await client.get(path, headers={"X-Workspace-Id": _OTHER_WS})
                uncited = await client.get(unknown, headers={"X-Workspace-Id": _WS})

            assert served.status_code == 200
            assert served.content == _TITLE_ARTIFACT_BODY
            assert crossed.status_code == 404
            # The union widens authorisation, it does not remove it.
            assert uncited.status_code == 404

    run_async(scenario())


def test_the_evidence_route_authorises_against_stored_display_blocks_only() -> None:
    """The evidence stream has no ``?contract`` parameter — it serves both contracts' readers — and
    its v1 half asks the display seam with ``generate=False``.

    So authorisation follows what is **stored**: retire the section that cites the claim and the
    same request is refused, rather than the route rebuilding the page to find a reason to say yes.
    An authorisation check that can write a page is a spend path, and a GET that schedules work is
    not safe to retry.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage({_TITLE_ARTIFACT_KEY: _TITLE_ARTIFACT_BODY})
            fixture = await _build_v1(conn)
            contact_claim_id = fixture.cited_claim_ids[1]
            path = f"{_BASE}/{fixture.zafran}/evidence/{contact_claim_id}"

            async with _client(_app(conn, evidence_storage=storage)) as client:
                cited = await client.get(path, headers={"X-Workspace-Id": _WS})
            assert cited.status_code == 200

            await supersede_blocks(
                conn,
                workspace_id=_WS,
                subject_kind="account",
                subject_id=str(fixture.zafran),
                page="overview",
                section_keys=["what-they-do"],
                now=datetime.now(UTC),
            )
            async with _client(_app(conn, evidence_storage=storage)) as client:
                uncited = await client.get(path, headers={"X-Workspace-Id": _WS})
                detail = await client.get(
                    f"{_BASE}/{fixture.zafran}",
                    params={"contract": "v1"},
                    headers={"X-Workspace-Id": _WS},
                )

            assert uncited.status_code == 404
            assert uncited.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
            # The page really is unwritten now — nothing regenerated it behind the request.
            sections = _overview(detail.json()["data"])
            assert sections["what-they-do"]["empty"] is True

    run_async(scenario())
