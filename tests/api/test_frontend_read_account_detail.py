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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
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
from clue_research.claimstore import insert_claim, record_run_lineage, register_field
from clue_research.durable import (
    AccountRunStatus,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.membership import ensure_project_account
from clue_research.narrative import VALUE_NARRATIVE, load_narrative_pack
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
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


# --- harness --------------------------------------------------------------------------------


def _app(conn: AsyncConnection):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _get(
    conn: AsyncConnection, account_id: uuid.UUID | str, *, workspace_id: str = _WS
) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(f"{_BASE}/{account_id}", headers={"X-Workspace-Id": workspace_id})


def _sections(payload: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    """The project sections keyed by ``projectId`` — ``None`` is the unattributed section."""
    return {section["projectId"]: section for section in payload["projectSections"]}


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
) -> None:
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
    ).model_copy(update={"source_key": source_key})
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
    await load_committee_pack(conn)
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

            # ...and no neutral field leaks into a project section.
            for section in payload["projectSections"]:
                keys = {entry["fieldKey"] for entry in section["insights"]}
                assert "core.employee_count" not in keys
                assert "core.revenue_band" not in keys

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

            assert _values(section_a["insights"]) == ["insight for A"]
            assert _values(section_b["insights"]) == ["insight for B"]

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
    """FI-1 §4.5 ruling: the committee is read through ``ContactEligibilityResolver``, never
    ``identity.contact_ids_for_account`` (which knows nothing about display governance)."""

    from pathlib import Path

    import clue_api.frontend_read.account_detail as module

    source = Path(module.__file__).read_text()
    body = source.split('"""', 2)[2]
    assert "contact_ids_for_account" not in body
    assert "ContactEligibilityResolver" in body


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

    run_async(scenario())


def test_the_project_run_context_rule_is_latest_run_wins() -> None:
    """THE per-project committee-context rule, recorded once: the project's most recent
    ``project_run`` supplies ``(project_run_id, product_id)``."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.frontend_read.account_detail import latest_project_run_context

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
