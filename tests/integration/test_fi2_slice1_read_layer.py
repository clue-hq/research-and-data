"""FI-2 slice 1, Task 5 — the read layer **composed**: all four endpoints over one workspace.

Tasks 2–4 each proved their own endpoint against its own fixture. What no per-endpoint suite can
prove is that the three surfaces tell the *same story* about the same rows: the `/accounts` table,
the account the operator clicks into, and the contacts tab underneath it are one screen flow, and a
disagreement between them (a score the list attributes to project A and the detail attributes to
project B; a committee member the detail lists and the contacts table withholds) is a product bug
that neither suite would ever fail on.

So this module seeds **one** workspace in the slice-0 canonical shape — two projects, one shared
account, one project-local account, one membership-less seed — with everything the read layer's
composition rules turn on:

* neutral facts, one of them written on a **project-attributed** run (it must still serve in every
  lens — species-conditional lineage);
* per-project attributed scores, including **two ICP versions inside one project** (the
  multiplicity FI-2 §7 refuses to collapse to a representative run);
* narratives per persona and a registry-declared ``project_relative`` insight per project, plus one
  insight from a project-less manual run (the honest ``unattributed`` bucket);
* a governed committee with a member reached through **both** projects, an unnamed partially
  researched member, a member holding a display-denied (special-category) title, a merged stale
  identity link, and a member whose role/persona binding is WEAK;
* mixed research statuses across the two projects and the two researched accounts.

Then it drives every slice-1 endpoint through the real ASGI app (flag on, in-process over the
test's rolled-back connection) and asserts the composed picture coheres: list row ↔ detail
agreement, detail ``committee[]`` ↔ contacts-list agreement, the redaction semantics agreeing
across row and profile, pagination composing with the ``projectId`` filter, the 404/redirect matrix
being the same answer on every path — and the two disciplines (no display strings on any of the
four payloads; no module in the package scoping a claim read by ``claim.workspace_id``).

Every read is workspace-scoped: this suite shares a database with suites that commit, so an
unscoped assertion would fail for reasons that have nothing to do with FI-2.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read import FRONTEND_READ_PREFIX, AccountResearchStatusValue

# The signal whitelist is the endpoint's own — imported, never re-declared here, so a rename in the
# read layer moves this fixture with it instead of silently seeding a field nothing counts.
from clue_api.frontend_read.contacts import CONTACT_SIGNAL_FIELD_KEYS, FACET_RECENT_POST
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
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
from tests.fleet.entity_research_r2_helpers import lifecycle_fixture
from tests.profiling.conftest import conn_session_factory, rollback_conn

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_integration_db")

_WS = "fi2-slice1-read-layer"
_OTHER_WS = "fi2-slice1-read-layer-other"
_ACCOUNTS = f"{FRONTEND_READ_PREFIX}/accounts"

#: A pack field registered by the fixture purely to *declare* itself ``project_relative`` — the
#: stand-in for a campaign insight (every shipped insight family is ``project_neutral`` under the
#: ratified §5.2 table, so a hardcoded list would be wrong). It proves the neutral/relative split is
#: read from the registry, on the composed surface as well as in the Task-3 suite.
_INSIGHT_FIELD = "fi2read.campaign_insight"


# --- harness ----------------------------------------------------------------------------------


def _app(conn: AsyncConnection) -> Any:
    """The real projections app, flag on, with the DB seam bound to the test's connection."""
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _call(
    conn: AsyncConnection,
    path: str,
    *,
    workspace_id: str | None = _WS,
    **params: Any,
) -> httpx.Response:
    headers = {} if workspace_id is None else {"X-Workspace-Id": workspace_id}
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn)), base_url="http://t"
    ) as client:
        return await client.get(
            path,
            params={key: value for key, value in params.items() if value is not None},
            headers=headers,
        )


async def _list(conn: AsyncConnection, **kwargs: Any) -> httpx.Response:
    return await _call(conn, _ACCOUNTS, **kwargs)


async def _detail(conn: AsyncConnection, account_id: Any, **kwargs: Any) -> httpx.Response:
    return await _call(conn, f"{_ACCOUNTS}/{account_id}", **kwargs)


async def _contacts(conn: AsyncConnection, account_id: Any, **kwargs: Any) -> httpx.Response:
    return await _call(conn, f"{_ACCOUNTS}/{account_id}/contacts", **kwargs)


async def _profile(
    conn: AsyncConnection, account_id: Any, contact_id: Any, **kwargs: Any
) -> httpx.Response:
    return await _call(conn, f"{_ACCOUNTS}/{account_id}/contacts/{contact_id}", **kwargs)


def _by_name(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in payload["data"]}


def _sections(detail: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    return {section["projectId"]: section for section in detail["projectSections"]}


def _neutral(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {fact["fieldKey"]: fact for fact in detail["neutralFacts"]}


def _facts(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {fact["fieldKey"]: fact for fact in profile["professionalFacts"]}


def _statuses(row: dict[str, Any]) -> dict[str, str]:
    return {entry["projectId"]: entry["status"] for entry in row["researchStatus"]}


# --- seeding ----------------------------------------------------------------------------------


async def _account(
    conn: AsyncConnection,
    *,
    name: str,
    domain: str | None,
    workspace_id: str = _WS,
    created_at: datetime | None = None,
) -> EntityId:
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    if created_at is not None:
        # Keyset pagination orders on ``created_at``; the seeds land microseconds apart, so the
        # walk is pinned to explicit, well-separated times instead of racing the clock.
        await conn.execute(
            text("UPDATE account_entity SET created_at = :at WHERE id = :id"),
            {"at": created_at, "id": account_id},
        )
    return account_id


async def _run(conn: AsyncConnection, *, kind: str, project_id: str | None) -> RunId:
    run_id = new_run_id()
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
    # ``account.scoring.*``, ``account.value_narrative`` and the test pack field all declare
    # ``tenant_private`` at the field, and the default ``stamp_reuse`` prefix policy matches none of
    # them — stamping directly keeps the fixture honest about what the real writer produces.
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
    """One project's Pass-A score under one ICP, written the way M6.3 writes it: tenant-private
    claims on a run registered to that project (the lineage row is what attributes them)."""
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


async def _contact_claim(
    conn: AsyncConnection,
    *,
    contact_id: EntityId,
    field_key: str,
    value: JsonValue,
    run_id: RunId,
    use_class: UseClass,
    binding: IdentityBinding = IdentityBinding.STRONG,
    source_key: str = "seed_source",
    observed_at: datetime | None = None,
) -> uuid.UUID:
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact_id,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=Confidence(1.0),
            run_id=run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            identity_binding=binding,
            use_class=use_class,
            evidence_span=f"evidence for {field_key}",
            observed_at=observed_at,
        ),
        workspace_id=_WS,
    ).model_copy(
        update={
            "source_key": source_key,
            "verification_status": (
                VerificationStatus.VERIFIED
                if binding is IdentityBinding.STRONG
                else VerificationStatus.UNVERIFIED
            ),
        }
    )
    await insert_claim(conn, claim)
    return uuid.UUID(str(claim.id))


async def _member(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    account_run: RunId,
    name: str | None,
    suffix: str | None,
    persona: Persona,
    binding: IdentityBinding = IdentityBinding.STRONG,
    role_confidence: float = 0.87,
    extra: Sequence[tuple[str, JsonValue, UseClass]] = (),
) -> tuple[EntityId, tuple[uuid.UUID, ...]]:
    """One committee member plus every claim id the account run references."""
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=name,
        linkedin_url=None if suffix is None else f"https://linkedin.com/in/{suffix}",
        status=AccountStatus.ACTIVE,
    )
    base = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    claim_ids = [
        await _contact_claim(
            conn,
            contact_id=contact,
            field_key=ROLE_ON_COMMITTEE,
            value={
                "role": persona.value,
                "confidence": role_confidence,
                "plausible": True,
                "rationale": "seeded",
            },
            run_id=account_run,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            binding=binding,
            source_key="committee_inference",
            observed_at=base,
        ),
        await _contact_claim(
            conn,
            contact_id=contact,
            field_key=PERSONA,
            value=persona.value,
            run_id=account_run,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            binding=binding,
            source_key="committee_inference",
            observed_at=base,
        ),
    ]
    for ordinal, (field_key, value, use_class) in enumerate(extra):
        claim_ids.append(
            await _contact_claim(
                conn,
                contact_id=contact,
                field_key=field_key,
                value=value,
                run_id=account_run,
                use_class=use_class,
                binding=binding,
                source_key="linkedin_snapshot" if field_key.startswith("contact.f") else "sumble",
                observed_at=base + timedelta(minutes=ordinal),
            )
        )
    return contact, tuple(claim_ids)


async def _launch_job(conn: AsyncConnection, *, project_id: str, account_id: EntityId) -> uuid.UUID:
    """Launch one real M8D account-research run/job for ``(account, project)`` through the
    production R2 entry point, returning its job id. Only the *scope* ids and the subject are
    overridden on the frozen R0 fixture lifecycle."""
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
    return authorization.job_id


async def _finalize(conn: AsyncConnection, job_id: uuid.UUID, *, outcome: str) -> None:
    """Drive a launched job to its terminal row (the row the read layer actually reads; driving the
    full lease → begin → finalize dance is R2's own acceptance suite's job)."""
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


@dataclass(frozen=True)
class _Fixture:
    """The seeded workspace's ids — what every assertion below is written against."""

    project_a: Project
    project_b: Project
    acme: EntityId
    zephyr: EntityId
    seedling: EntityId
    shared: EntityId
    masked: EntityId
    unnamed: EntityId
    merged_loser: EntityId
    unbound: EntityId


async def _build(conn: AsyncConnection) -> _Fixture:
    """One workspace, two projects, three accounts, one governed committee, mixed research."""
    await seed_workspace(conn, _WS)
    await load_narrative_pack(conn)
    await load_committee_pack(conn)
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

    project_a = await seed_project(conn, _WS, name="Read-layer project A")
    project_b = await seed_project(conn, _WS, name="Read-layer project B")
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    acme = await _account(conn, name="Acme", domain="acme.test", created_at=base)
    zephyr = await _account(
        conn, name="Zephyr", domain="zephyr.test", created_at=base + timedelta(hours=1)
    )
    seedling = await _account(
        conn, name="Seedling", domain=None, created_at=base + timedelta(hours=2)
    )
    for project, account, via, added_at in (
        (project_a, acme, "discovered", base),
        (project_b, acme, "imported", base + timedelta(minutes=5)),
        (project_b, zephyr, "manual", base + timedelta(hours=1)),
    ):
        await ensure_project_account(
            conn,
            workspace_id=_WS,
            project_id=project.project_id,
            account_entity_id=account,
            added_via=via,
            added_at=added_at,
        )

    # --- neutral: one written on project A's run, one on a project-less run. Neither is
    # lineage-filtered — a ``project_neutral`` field is workspace truth in every lens.
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
    # Zephyr belongs only to B, and its headcount was discovered on a run attributed to A.
    await _account_claim(
        conn,
        account_id=zephyr,
        field_key="core.employee_count",
        value=340,
        run_id=await _run(conn, kind="scoring", project_id=project_a.project_id),
        source_key="clearbit",
        observed_at=base,
    )

    # --- relative: A scored the account under two ICP versions, B under its own ICP.
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
        project_id=project_a.project_id,
        fit=0.86,
        intent=0.44,
        icp_key="alpha",
        icp_version=2,
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

    # --- relative: narratives (per persona) and insights, per project.
    for project, label, personas in (
        (project_a, "A", (Persona.ECONOMIC_BUYER, Persona.CHAMPION)),
        (project_b, "B", (Persona.ECONOMIC_BUYER,)),
    ):
        narrative_run = await _run(conn, kind="narrative", project_id=project.project_id)
        for persona in personas:
            await _account_claim(
                conn,
                account_id=acme,
                field_key=VALUE_NARRATIVE,
                value={
                    "persona": persona.value,
                    "argument": f"narrative for {label}/{persona.value}",
                    "angle_label": "roi",
                    "icp_key": "alpha" if label == "A" else "beta",
                    "icp_spec_version": 1,
                },
                run_id=narrative_run,
                source_key="narrative_synthesis",
                private=True,
            )
        await _account_claim(
            conn,
            account_id=acme,
            field_key=_INSIGHT_FIELD,
            value=f"insight for {label}",
            run_id=await _run(conn, kind="entity_research", project_id=project.project_id),
            source_key="deep_research",
            private=True,
        )
    # ...and one relative claim from a manual run that belongs to no project: the honest
    # ``unattributed`` bucket, which must never be smeared onto a real project's section.
    await _account_claim(
        conn,
        account_id=acme,
        field_key=_INSIGHT_FIELD,
        value="insight from a manual ingestion",
        run_id=await _run(conn, kind="manual", project_id=None),
        source_key="client_upload",
        private=True,
    )

    # --- the governed committee. A researched it; B's run references only the shared member, which
    # is what makes the union a union rather than two disjoint lists.
    project_run_a = new_project_run_id()
    project_run_b = new_project_run_id()
    for project_run, project, icp_key, icp_version in (
        (project_run_a, project_a, "alpha", 1),
        (project_run_b, project_b, "beta", 3),
    ):
        await ensure_project_run(
            conn,
            project_run_id=project_run,
            project_id=project.project_id,
            workspace_id=_WS,
            icp_key=icp_key,
            icp_version=icp_version,
        )
    account_run_a, account_run_b = new_run_id(), new_run_id()
    for account_run, project_run in (
        (account_run_a, project_run_a),
        (account_run_b, project_run_b),
    ):
        await insert_account_run(
            conn,
            account_run_id=account_run,
            project_run_id=project_run,
            entity_id=acme,
            tier="top",
        )

    shared, shared_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Dana Buyer",
        suffix="dana-buyer",
        persona=Persona.ECONOMIC_BUYER,
        extra=(
            (CURRENT_TITLE, "VP Finance", UseClass.PROFESSIONAL_PUBLIC),
            (
                FACET_RECENT_POST,
                "posted about procurement",
                UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
            ),
        ),
    )
    # A held-but-display-denied (special-category) title: the value must never appear, and both
    # surfaces must say so the same way.
    masked, masked_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Chris Blocker",
        suffix="chris-blocker",
        persona=Persona.BLOCKER,
        role_confidence=0.62,
        extra=((CURRENT_TITLE, "Head Chaplain", UseClass.SENSITIVE),),
    )
    # A valid committee identity can be intentionally unnamed and only partially researched. Its
    # role/persona are sufficient for governed membership and Contact-detail addressability; name,
    # title, LinkedIn and signal fields remain honestly absent.
    unnamed, unnamed_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name=None,
        suffix=None,
        persona=Persona.TECHNICAL_EVALUATOR,
        role_confidence=0.71,
    )
    # A stale link to a merged contact remains addressable and visibly resolves to the survivor.
    merged_loser = await insert_contact_entity(
        conn,
        account_entity_id=acme,
        full_name="Dana Buyer (duplicate)",
        linkedin_url="https://linkedin.com/in/dana-buyer-duplicate",
        status=AccountStatus.ACTIVE,
    )
    await mark_merged(conn, EntityType.CONTACT, loser_id=merged_loser, survivor_id=shared)
    # Membership is identity-bearing: a WEAK role/persona binding is dropped by the governed
    # reader — on *both* surfaces, which is the agreement this fixture exists to prove.
    unbound, unbound_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Unbound Person",
        suffix="unbound-person",
        persona=Persona.CHAMPION,
        binding=IdentityBinding.WEAK,
    )
    await save_references(
        conn,
        account_run_a,
        references_index={
            "committee": [
                str(item) for item in shared_refs + masked_refs + unnamed_refs + unbound_refs
            ]
        },
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )
    await save_references(
        conn,
        account_run_b,
        references_index={"committee": [str(item) for item in shared_refs]},
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )

    # --- mixed research status: A finished Acme needing review, B is still running it, and B's
    # Zephyr run stopped without a result (the backend has no `failed` terminal to report).
    await _finalize(
        conn,
        await _launch_job(conn, project_id=project_a.project_id, account_id=acme),
        outcome="needs_review",
    )
    await _launch_job(conn, project_id=project_b.project_id, account_id=acme)
    await _finalize(
        conn,
        await _launch_job(conn, project_id=project_b.project_id, account_id=zephyr),
        outcome="cancelled",
    )

    return _Fixture(
        project_a=project_a,
        project_b=project_b,
        acme=acme,
        zephyr=zephyr,
        seedling=seedling,
        shared=shared,
        masked=masked,
        unnamed=unnamed,
        merged_loser=merged_loser,
        unbound=unbound,
    )


# --- (a) the list row and the detail tell the same story ---------------------------------------


def test_every_list_row_agrees_with_the_detail_of_the_same_account() -> None:
    """The screen flow's first seam: clicking a row must not change the facts. Identity, the neutral
    values, the memberships and every attributed score are re-derived by two different compositions
    (a batched page read vs a single-entity union read) and must land on the same answer."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            page = (await _list(conn)).json()
            assert page["meta"]["total"] == 3

            for row in page["data"]:
                detail = (await _detail(conn, row["id"])).json()

                assert (detail["id"], detail["name"], detail["domain"]) == (
                    row["id"],
                    row["name"],
                    row["domain"],
                )
                assert detail["redirectedFrom"] is None

                # The two neutral list columns are the same canonical-merge winners the detail
                # serves as ``neutralFacts`` — one merge, two projections of it.
                neutral = _neutral(detail)
                for column, field_key in (
                    ("employeeCount", "core.employee_count"),
                    ("revenueBand", "core.revenue_band"),
                ):
                    fact = neutral.get(field_key)
                    assert row[column] == (None if fact is None else fact["value"])

                # Membership-bearing sections, in order, are exactly the row's ``projects[]``.
                membership_sections = [
                    section
                    for section in detail["projectSections"]
                    if section["projectId"] is not None and section["addedVia"] is not None
                ]
                # ``name`` is in the tuple deliberately: both surfaces resolve it through the same
                # batched read, so the one thing the frontend searches and sorts on cannot say
                # "Project A" on the table and something else on the detail.
                assert [
                    (
                        section["projectId"],
                        section["name"],
                        section["addedVia"],
                        section["addedAt"],
                    )
                    for section in membership_sections
                ] == [
                    (
                        project["projectId"],
                        project["name"],
                        project["addedVia"],
                        project["addedAt"],
                    )
                    for project in row["projects"]
                ]
                assert row["primaryProjectId"] == (
                    row["projects"][0]["projectId"] if row["projects"] else None
                )

                # Scores: the list flattens ``(project, icp, version)`` onto the row, the detail
                # nests them under their section. Same tuples, or one of the two is guessing.
                # Scoped to attributed sections on purpose: the list is attributed-only (its score
                # read inner-joins lineage), so an unattributed (``projectId: null``) score is a
                # real product asymmetry, not a test failure — comparing it here would make a
                # future fixture that seeds one fail the test instead of surfacing the product gap.
                assert {
                    (score["projectId"], score["icpKey"], score["icpVersion"]): (
                        score["fit"],
                        score["intent"],
                        score["scoredAt"],
                    )
                    for score in row["scores"]
                } == {
                    (section["projectId"], score["icpKey"], score["icpVersion"]): (
                        score["fit"],
                        score["intent"],
                        score["scoredAt"],
                    )
                    for section in detail["projectSections"]
                    if section["projectId"] is not None
                    for score in section["scores"]
                }

                # The list is the only surface carrying research status; it must at least agree
                # with the detail about which projects the account belongs to.
                assert set(_statuses(row)) == {project["projectId"] for project in row["projects"]}

            rows = _by_name(page)
            # And the fixture's own shape, so the loop above is asserting over real content:
            # A scored Acme under two ICP versions and B under its own — three attributed scores.
            assert len(rows["Acme"]["scores"]) == 3
            assert {(score["icpKey"], score["icpVersion"]) for score in rows["Acme"]["scores"]} == {
                ("alpha", 1),
                ("alpha", 2),
                ("beta", 3),
            }
            assert rows["Seedling"]["projects"] == []
            assert rows["Seedling"]["scores"] == []
            assert rows["Zephyr"]["employeeCount"] == 340

    run_async(scenario())


def test_research_status_is_per_project_and_uses_the_backend_vocabulary() -> None:
    """Status is a ``(account, project)`` fact, never an account-wide one: the same account is
    ``needs_review`` in the project that finished it and ``in_progress`` in the one still running.
    A stopped-without-a-result run reads ``suspended`` — there is no ``failed`` on this wire."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            rows = _by_name((await _list(conn)).json())

            assert _statuses(rows["Acme"]) == {
                fixture.project_a.project_id: AccountResearchStatusValue.NEEDS_REVIEW.value,
                fixture.project_b.project_id: AccountResearchStatusValue.IN_PROGRESS.value,
            }
            assert _statuses(rows["Zephyr"]) == {
                fixture.project_b.project_id: AccountResearchStatusValue.SUSPENDED.value
            }
            # A membership-less account has no project to be researched *for*.
            assert rows["Seedling"]["researchStatus"] == []
            assert "failed" not in {
                entry["status"] for row in rows.values() for entry in row["researchStatus"]
            }

    run_async(scenario())


def test_relative_work_stays_in_its_own_section_and_the_residue_is_reported() -> None:
    """The detail's partition, composed: each project's narrative/insight/score sits in its own
    section, and the claim whose run maps to no project surfaces in the ``unattributed`` bucket
    instead of being dropped or guessed onto whichever project happens to be first."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            detail = (await _detail(conn, fixture.acme)).json()
            sections = _sections(detail)

            assert set(sections) == {
                fixture.project_a.project_id,
                fixture.project_b.project_id,
                None,
            }
            section_a = sections[fixture.project_a.project_id]
            section_b = sections[fixture.project_b.project_id]

            assert [entry["value"] for entry in section_a["insights"]] == ["insight for A"]
            assert [entry["value"] for entry in section_b["insights"]] == ["insight for B"]
            # Narratives are plural *per persona* — collapsing them would have to pick a winner.
            assert {entry["value"]["persona"] for entry in section_a["narratives"]} == {
                Persona.ECONOMIC_BUYER.value,
                Persona.CHAMPION.value,
            }
            assert len(section_b["narratives"]) == 1

            unattributed = sections[None]
            assert unattributed["addedVia"] is None and unattributed["addedAt"] is None
            assert [entry["value"] for entry in unattributed["insights"]] == [
                "insight from a manual ingestion"
            ]
            assert unattributed["scores"] == []

            # Neutral facts are served once, at the top level, in every lens — never per project.
            assert set(_neutral(detail)) == {"core.employee_count", "core.revenue_band"}
            for section in detail["projectSections"]:
                assert not {entry["fieldKey"] for entry in section["insights"]} & {
                    "core.employee_count",
                    "core.revenue_band",
                }

    run_async(scenario())


# --- (b) the detail's committee and the contacts table are the same people ----------------------


def test_the_detail_committee_and_the_contacts_list_are_the_same_governed_people() -> None:
    """The second seam of the flow. Both surfaces resolve the committee through the same governed
    reader under the same workspace policy, so their member sets, personas, roles and per-member
    project attributions must be identical — including who is *excluded* (the WEAK-bound person is
    on neither list, and a policy that hides role/persona empties both)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            detail = (await _detail(conn, fixture.acme)).json()
            contacts = (await _contacts(conn, fixture.acme)).json()

            in_detail = {member["contactId"]: member for member in detail["committee"]}
            in_list = {row["id"]: row for row in contacts["data"]}
            assert (
                set(in_detail)
                == set(in_list)
                == {
                    str(fixture.shared),
                    str(fixture.masked),
                    str(fixture.unnamed),
                }
            )
            assert str(fixture.unbound) not in in_detail
            assert contacts["meta"]["total"] == len(contacts["data"]) == 3

            for contact_id, member in in_detail.items():
                row = in_list[contact_id]
                assert member["name"] == row["name"]
                assert member["persona"] == row["persona"]
                # The one shape difference between the surfaces: the detail serves the role as a
                # bare enum value, the contacts row wraps it with the inference confidence.
                assert member["roleOnCommittee"] == row["roleOnCommittee"]["value"]
                assert member["projectIds"] == row["projectIds"]

                # This is the authored-link invariant: every id emitted by either Account detail
                # or Contacts list resolves through the account-scoped Contact profile endpoint.
                profile_response = await _profile(conn, fixture.acme, contact_id)
                assert profile_response.status_code == 200
                profile = profile_response.json()
                assert profile["id"] == contact_id
                assert profile["accountId"] == str(fixture.acme)

            # The member both projects' runs reference appears ONCE, carrying both projects.
            assert in_list[str(fixture.shared)]["projectIds"] == [
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            ]
            assert in_list[str(fixture.masked)]["projectIds"] == [fixture.project_a.project_id]
            unnamed = in_list[str(fixture.unnamed)]
            assert unnamed["name"] is None
            assert unnamed["title"] is None
            assert unnamed["titleRestricted"] is False
            assert unnamed["linkedinUrl"] is None
            assert unnamed["signals"] == {"typeCount": 0}

            merged = await _profile(conn, fixture.acme, fixture.merged_loser)
            assert merged.status_code == 200
            assert merged.json()["id"] == str(fixture.shared)
            assert merged.json()["redirectedFrom"] == str(fixture.merged_loser)

            # ...and they agree on *nobody*, too: role and persona are what make someone a committee
            # member, so a workspace that will not display those claims empties both surfaces at
            # once. Until the shared display gate landed this was a live leak — the detail listed
            # names and roles the contacts table correctly withheld.
            await conn.execute(
                text(
                    "INSERT INTO workspace_policy (policy_id, workspace_id, posture, "
                    "display_professional_public, version) "
                    "VALUES (:pid, :ws, 'conservative_default', false, 9)"
                ),
                {"pid": f"p-{uuid.uuid4()}", "ws": _WS},
            )
            assert (await _detail(conn, fixture.acme)).json()["committee"] == []
            assert (await _contacts(conn, fixture.acme)).json() == {
                "data": [],
                "meta": {"total": 0},
            }

    run_async(scenario())


def test_a_display_denied_field_is_withheld_identically_on_the_row_and_the_profile() -> None:
    """Redaction is a property of the claim, not of the endpoint: the withheld title is absent with
    a marker on the row, absent with a marker in the profile's fact slot, and its value appears in
    no payload of the flow. A weakly-bound member's data never appears at all."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            detail = (await _detail(conn, fixture.acme)).json()
            contacts = (await _contacts(conn, fixture.acme)).json()
            rows = {row["id"]: row for row in contacts["data"]}

            masked_row = rows[str(fixture.masked)]
            assert masked_row["title"] is None
            assert masked_row["titleRestricted"] is True
            masked_profile = (await _profile(conn, fixture.acme, fixture.masked)).json()
            withheld = _facts(masked_profile)[CURRENT_TITLE]
            assert withheld["restricted"] is True
            assert withheld["value"] is None
            # Nothing about the withheld claim leaks through the slot — not even its provenance.
            assert withheld["provider"] is None and withheld["observedAt"] is None

            shared_row = rows[str(fixture.shared)]
            assert shared_row["title"] == "VP Finance"
            assert shared_row["titleRestricted"] is False
            # One facet seeded, from the endpoint's own signal whitelist.
            assert FACET_RECENT_POST in CONTACT_SIGNAL_FIELD_KEYS
            assert shared_row["signals"] == {"typeCount": 1}
            shared_profile = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert _facts(shared_profile)[CURRENT_TITLE]["value"] == "VP Finance"
            # The profile is the row plus account identity — the shared half cannot drift.
            for key in ("id", "name", "title", "persona", "projectIds", "signals"):
                assert shared_profile[key] == shared_row[key]
            assert shared_profile["accountId"] == detail["id"]
            assert shared_profile["accountName"] == detail["name"]
            assert shared_profile["redirectedFrom"] is None
            assert {chip["provider"] for chip in shared_profile["evidence"]} == {
                "committee_inference",
                "linkedin_snapshot",
                "sumble",
            }

            blob = str([detail, contacts, masked_profile, shared_profile])
            assert "Chaplain" not in blob
            assert "Unbound Person" not in blob

    run_async(scenario())


# --- (c) pagination composed with the membership filter ----------------------------------------


def test_pagination_and_the_project_filter_compose_over_the_whole_workspace() -> None:
    """The cursor predicate and the membership predicate are ANDed, so a filtered walk can neither
    leak a non-member nor skip a member — and an unknown project is an empty *filter*, not a 404
    (this endpoint has no authority to say a project does not exist)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)

            async def walk(limit: int, project_id: str | None) -> list[str]:
                seen: list[str] = []
                cursor: str | None = None
                for _ in range(10):  # a bounded loop: a cursor bug must fail, not hang
                    page = (
                        await _list(conn, limit=limit, cursor=cursor, projectId=project_id)
                    ).json()
                    seen += [row["name"] for row in page["data"]]
                    cursor = page["meta"]["nextCursor"]
                    if cursor is None:
                        return seen
                raise AssertionError("the cursor never closed the walk")

            walked = await walk(2, None)
            assert sorted(walked) == ["Acme", "Seedling", "Zephyr"]
            assert len(walked) == len(set(walked))

            in_b = await walk(1, fixture.project_b.project_id)
            assert sorted(in_b) == ["Acme", "Zephyr"]
            assert "Seedling" not in in_b

            only_a = (await _list(conn, projectId=fixture.project_a.project_id)).json()
            assert set(_by_name(only_a)) == {"Acme"}
            assert only_a["meta"]["total"] == 1
            # A filter narrows the set of rows, never the row: Acme still carries both projects.
            assert len(_by_name(only_a)["Acme"]["projects"]) == 2

            unknown = (await _list(conn, projectId="no-such-project")).json()
            assert unknown == {"data": [], "meta": {"total": 0, "nextCursor": None}}

            assert (await _list(conn, cursor="not-a-cursor")).status_code == 400
            assert (await _list(conn, limit=201)).status_code == 422

    run_async(scenario())


# --- (d) the 404 / redirect matrix --------------------------------------------------------------


def test_the_404_and_redirect_matrix_is_the_same_answer_on_every_path() -> None:
    """One id, three endpoints, one answer. An unknown id and a foreign workspace's id are
    deliberately indistinguishable (so the surface cannot probe another tenant's id space); a merged
    loser is a **redirect** on the two entity paths and simply absent from the list — a list of
    accounts must not contain a row that no longer exists."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            foreign = await _account(
                conn, name="Foreign", domain="foreign.test", workspace_id=_OTHER_WS
            )
            unknown = uuid.uuid4()

            for account_id in (unknown, foreign):
                for response in (
                    await _detail(conn, account_id),
                    await _contacts(conn, account_id),
                    await _profile(conn, account_id, fixture.shared),
                ):
                    assert response.status_code == 404
                    error = response.json()["error"]
                    assert error["code"] == "ACCOUNT_NOT_FOUND"
                    assert error["requestId"]
            # ...and the reverse: this workspace's account read under the foreign tenant header.
            assert (await _detail(conn, fixture.acme, workspace_id=_OTHER_WS)).status_code == 404
            assert "Acme" not in _by_name((await _list(conn, workspace_id=_OTHER_WS)).json())

            # A contact that exists but is on no committee here (the WEAK-bound person) is a 404,
            # exactly like an unknown contact id.
            for contact_id in (uuid.uuid4(), fixture.unbound):
                response = await _profile(conn, fixture.acme, contact_id)
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "CONTACT_NOT_FOUND"

            # The merged loser.
            loser = await _account(conn, name="Acme Dup", domain="acme-dup.test")
            await mark_merged(conn, EntityType.ACCOUNT, loser_id=loser, survivor_id=fixture.acme)

            detail = (await _detail(conn, loser)).json()
            assert detail["id"] == str(fixture.acme)
            assert detail["redirectedFrom"] == str(loser)
            contacts = (await _contacts(conn, loser)).json()
            assert {row["id"] for row in contacts["data"]} == {
                row["id"] for row in (await _contacts(conn, fixture.acme)).json()["data"]
            }
            # The list envelope carries no redirect vocabulary at all — there is no row to redirect.
            assert set(contacts) == {"data", "meta"}
            profile = (await _profile(conn, loser, fixture.shared)).json()
            assert profile["accountId"] == str(fixture.acme)
            assert profile["redirectedFrom"] is None

            page = (await _list(conn)).json()
            assert str(loser) not in {row["id"] for row in page["data"]}
            assert page["meta"]["total"] == 3

            # Malformed input and a missing tenant header answer in the same envelope.
            assert (await _detail(conn, "not-a-uuid")).status_code == 422
            assert (await _profile(conn, fixture.acme, "not-a-uuid")).json()["error"][
                "code"
            ] == "VALIDATION_ERROR"
            for response in (
                await _list(conn, workspace_id=None),
                await _detail(conn, fixture.acme, workspace_id=None),
                await _contacts(conn, fixture.acme, workspace_id=None),
                await _profile(conn, fixture.acme, fixture.shared, workspace_id=None),
            ):
                assert response.status_code == 401
                assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


# --- (e) the two disciplines --------------------------------------------------------------------


_BANNED_KEYS = {
    "email",
    "workEmail",
    "emailStatus",
    "avatar",
    "avatarUrl",
    "socials",
    "twitterUrl",
    "xUrl",
    "phone",
    "directPhone",
    "displayName",
    "formatted",
}

#: The carve-out is anchored on the **shapes** that carry a claim's own JSON, not on a key name:
#: a fact row is exactly a dict carrying ``fieldKey`` (the four fact slots — ``neutralFacts``,
#: ``insights``, ``narratives``, ``professionalFacts``), and its ``value`` is served verbatim (the
#: M12.1 narrative object carries ``persona`` / ``argument`` / ``angle_label`` — the synthesizer's
#: own field names, snake_case, unchanged). The account-detail root additionally carries two opaque
#: maps keyed by registry and geo component. Anchoring this way means a *new* ``value`` key
#: somewhere else on the wire is still swept. The Band-2 rule constrains the envelope this layer
#: authors; it cannot rename the inside of a stored claim without fabricating a shape no writer
#: produces — so the frontend treats these slots as opaque backend JSON (recorded in the contract).
_FACT_ROW_MARKER = "fieldKey"
_DETAIL_ROOT_MARKER = "projectSections"
_DETAIL_OPAQUE_MAPS = ("registryIds", "hqGeo")


def test_no_display_string_reaches_any_of_the_four_payloads() -> None:
    """Band-2 across the whole flow: semantic values only — enums, numbers, ISO-8601 timestamps,
    opaque ids and nulls. A label the frontend should own (or a personal field FI-1 G1–G3 keeps off
    this slice's wire) must not appear on *any* of the four surfaces, not merely on the one whose
    own suite happens to check for it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payloads = [
                (await _list(conn)).json(),
                (await _detail(conn, fixture.acme)).json(),
                (await _contacts(conn, fixture.acme)).json(),
                (await _profile(conn, fixture.acme, fixture.shared)).json(),
            ]

            personas = {persona.value for persona in Persona}
            statuses = {status.value for status in AccountResearchStatusValue}

            def opaque(node: dict[str, Any], key: str) -> bool:
                """True only for the claim-owned payloads: a fact row's ``value``, and the account
                detail root's two opaque maps."""
                if key == "value":
                    return _FACT_ROW_MARKER in node
                return key in _DETAIL_OPAQUE_MAPS and _DETAIL_ROOT_MARKER in node

            def walk(node: Any, path: str) -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        assert key not in _BANNED_KEYS, f"{path}.{key}"
                        assert not key.lower().endswith("label"), f"display string at {path}.{key}"
                        if key.endswith("At") and isinstance(value, str):
                            assert datetime.fromisoformat(value).tzinfo is not None, path
                        if key == "persona":
                            assert value in personas, f"{path}.{key} = {value}"
                        if key == "status":
                            assert value in statuses, f"{path}.{key} = {value}"
                        if not opaque(node, key):
                            walk(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        walk(value, f"{path}[{index}]")

            for ordinal, payload in enumerate(payloads):
                walk(payload, f"payload[{ordinal}]")
                # G3: no email address anywhere in the contact surfaces.
                assert "@" not in str(payload)

    run_async(scenario())


def test_no_module_in_the_read_package_scopes_a_claim_read_by_claim_workspace_id() -> None:
    """The slice-0 trap, swept over the **whole** package rather than module by module.

    ``claim.workspace_id`` is the M2.5 reuse-class tenant binding, and a DB CHECK forces it NULL on
    every ``public_footprint`` claim — so ``WHERE claim.workspace_id = :ws`` does not narrow a claim
    read, it silently *empties* it. The failure mode is a plausible-looking short answer that no
    fixture can catch, and a new module added to this package tomorrow would not inherit any of the
    per-module greps. Module docstrings are stripped first: they name the trap on purpose.
    """
    import clue_api.frontend_read as package

    offenders: list[str] = []
    for path in sorted(Path(package.__file__).parent.glob("*.py")):
        source = path.read_text()
        first = ast.parse(source).body[0] if source.strip() else None
        docstring_end = (
            first.end_lineno or 0
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            else 0
        )
        body = "\n".join(source.splitlines()[docstring_end:])
        if "claim.workspace_id" in body:
            offenders.append(path.name)
    assert offenders == [], f"claim reads scoped by the reuse-class column: {offenders}"
