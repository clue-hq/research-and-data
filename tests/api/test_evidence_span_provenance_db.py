"""Live defect #29 — a projected evidence span the retained artifact never contained.

Job ``eea48931-2798-54d7-b631-5320fd65b869`` (Millennium Physician Group) suspended with
``EntityResearchResultIntegrityError: projected evidence span is absent from retained artifact``
raised out of an ``enrich_account`` (``sumble_organizations``) projection. The guard is the
anti-fabrication rule — a cited span must literally occur in the immutable bytes it names — and it
is deterministic engine code, so the divergence had to be on the writing side. It was, twice over:

1. Every ``exa_websets`` claim was born with a *described* span rather than a quoted one —
   ``Exa company properties company.headquarters|company.location: {"city":"Fort Myers",…}`` — a
   sentence about normalized platform values that appears nowhere in the retained item. All 187
   ``exa_websets`` claims in the live database fail the guard; no other source has a single
   failure, because the Sumble resolver already quotes canonical members
   (``resolvers.sumble._json_member_span``). ``_RetainedItem`` now cuts every Exa span out of the
   exact retained bytes, so the two sides cannot diverge by construction.
2. The Sumble account projection published *contenders'* evidence on a conflicting field, so a
   ``sumble_organizations`` result carried ``exa_websets`` artifacts and spans. That is what
   walked the foreign claim into the guard — and had the span been quotable, the very next engine
   check (``projected evidence violates exact field/source authority``) would have refused it
   anyway. Conflicting claims are now cited by reference; evidence stays the operation's own.

Neither guard is relaxed here: a genuine mismatch still refuses, which the last test asserts.

**The second act — the wedge (03:17 and 03:46).** The defect-29 fixes changed what the projection
*composes*, and the operation above had already stored a first projection under the defective code.
The replay guard recomputed, saw the difference, and refused (``Sumble projection replay changed``);
``c7d6da82`` then made that branch serve the STORED projection, which handed the job back the very
draft whose foreign span the guard had refused at 02:14 — the identical error, on every resume. The
last three tests hold the amendment that opened the loop: first-write-wins guards *admitted*
history, and a stored projection whose operation has no ``entity_research_result`` anywhere was
never admitted to any turn. For that draft the immutable truth is the retained snapshot, so the
replay serves the fresh recomputation; the append-only first draft stays at rest as audit.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultIntegrityError,
    EntityResearchResultStore,
    ExternalResearchProjectionDraft,
    ProviderObservationDisposition,
    ProviderOperationObservation,
    ProviderOperationReservation,
    _json_contains_text,
)
from clue_api.exa_websets_materialization import ExaWebsetsD4Materializer
from clue_api.sumble_account_gaps import SumbleAccountGapCoordinator, SumbleAccountGapStarter
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_api.sumble_entity_research_tools import (
    _EVIDENCE_NAMESPACE,
    SumbleAccountSemanticEnrichmentAction,
    SumbleCommitteeSemanticResearchAction,
    SumbleEntityResearchLineageReader,
)
from clue_core import (
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
)
from clue_core.entity_research import (
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchEvidenceProjection,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchSubjectType,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import capture_discovery_artifact
from clue_research.identity import get_account, stamp_reuse
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_storage import FsStorage
from tests.api.test_account_entity_research_r5_db import _committee_tool_request
from tests.api.test_exa_websets_materialization_d4 import _company_item, _seed_terminal_batch
from tests.api.test_sumble_account_gaps_s1 import _seed_selected_high_tier_account
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport
from tests.api.test_sumble_committee_acquisition_s2b import _setup as _committee_setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.profiling.conftest import FakeGateway, conn_session_factory, seed_packs

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_HQ = "core.hq_location"
_SHA = "0" * 64

#: The evidence span the live ``exa_websets`` ``core.hq_location`` claim
#: (``4a03dca8-306d-4cac-8411-0d3ae3e52c27``) actually carries at rest, copied verbatim from the
#: live database. Nothing like it occurs in the Exa item it cites: the retained bytes hold
#: ``"headquarters":{…,"city":"Fort Myers",…}`` and ``"location":"Fort Myers, United States"``.
_LIVE_DESCRIBED_SPAN = (
    "Exa company properties company.headquarters|company.location: "
    '{"city":"Fort Myers","country":"United States","country_code":"US",'
    '"raw":"Fort Myers, United States","region":"Florida"}'
)


def _live_shaped_item(item_id: str) -> dict[str, object]:
    """The D4 fixture item, re-shaped to the live Millennium payload the defect came from."""

    payload = _company_item(item_id, city="Fort Myers", criterion_state="yes")
    properties = payload["properties"]
    assert isinstance(properties, dict)
    company = properties["company"]
    assert isinstance(company, dict)
    company["name"] = "Millennium Physician Group"
    company["employees"] = 955
    company["location"] = "Fort Myers, United States"
    company["about"] = (
        "Millennium Physician Group is a Hospitals and Health Care company. Millennium "
        "Physician Group has 800-900 employees (+10% YoY) and has annual revenue in the "
        "$80M-$90M range, founded in 2008."
    )
    headquarters = company["headquarters"]
    assert isinstance(headquarters, dict)
    headquarters["address"] = "6321 Daniels Pkwy Suite 200"
    headquarters["postalCode"] = "33919"
    headquarters["state"] = "Florida"
    headquarters["country"] = "United States"
    return payload


class _OrganizationsHttp:
    """The live ``/organizations`` answer: an employee count and an HQ country, nothing else."""

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        if url.endswith("/organizations"):
            return {
                "id": "defect-29-org-request",
                "credits_used": 1,
                "credits_remaining": 63,
                "organizations": [
                    {
                        "input": {"url": self.domain},
                        "attributes": {
                            "id": 6489,
                            "name": "Millennium Physician Group",
                            "url": self.domain,
                            "sumble_url": "https://sumble.com/l/org/toO4GKmA4tLo",
                            "employee_count": 955,
                            "headquarters_country": "US",
                        },
                        "entities": [],
                    }
                ],
                "matched_count": 1,
                "total": 1,
            }
        raise AssertionError(f"unexpected Sumble URL: {url}")


def _request(account_id: EntityId) -> GovernedResearchToolRequest:
    """The exact governed shape of the live call: one field, one authorized source."""

    return GovernedResearchToolRequest(
        research_run_id=uuid4(),
        job_id=uuid4(),
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=account_id,
        agent_turn_id=uuid4(),
        agent_execution_id=uuid4(),
        tool_call_id=uuid4(),
        tool_name="enrich_account",
        tool_version=1,
        tool_input_sha256=_SHA,
        field_plan_ref="account-field-plan:defect-29",
        source_plan_ref="effective-source-plans:defect-29",
        field_keys=(_HQ,),
        source_keys=(ORGANIZATIONS_SOURCE_KEY,),
        field_source_authority=(
            FieldSourceAuthority(field_key=_HQ, source_keys=(ORGANIZATIONS_SOURCE_KEY,)),
        ),
        questions=(),
        budget_reservation_key="defect-29-budget",
        idempotency_key="defect-29-idempotency",
    )


def test_every_exa_websets_claim_span_is_verbatim_in_the_retained_item(tmp_path: Path) -> None:
    """Defect #29 root cause 1, through the real D4 materializer on the live payload shape.

    The engine's own predicate is the oracle — the same function that raised live — so this cannot
    pass by agreeing with a re-implementation of the rule.
    """

    async def scenario() -> None:
        workspace_id = "ws-defect-29-exa"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            batch_id, _, item_keys = await _seed_terminal_batch(
                conn,
                storage,
                workspace_id,
                item_payloads=[_live_shaped_item("item_defect_29")],
            )
            await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            retained = {key: await storage.get(key) for key in item_keys}
            rows = (
                await conn.execute(
                    text(
                        "SELECT field_key, artifact_key, evidence_span FROM claim "
                        "WHERE source_key = 'exa_websets' "
                        "AND artifact_key = ANY(CAST(:keys AS text[]))"
                    ),
                    {"keys": list(item_keys)},
                )
            ).all()

            # The live payload yields the base fields plus the LinkedIn enrichment and the
            # discovery-provenance claim; every one of them is a span the guard re-checks.
            assert len(rows) >= 8
            described = [
                str(field_key)
                for field_key, _, span in rows
                if str(span).startswith("Exa company properties")
            ]
            assert described == []
            absent = [
                (str(field_key), str(span))
                for field_key, artifact_key, span in rows
                if not _json_contains_text(retained[str(artifact_key)], str(span))
            ]
            assert absent == []
            # And the spans are cut, not merely findable: the two-member HQ citation is one
            # contiguous run of the retained object, not a join of two lookups.
            hq_span = next(str(span) for field_key, _, span in rows if str(field_key) == _HQ)
            assert hq_span.startswith('"headquarters":{"address":"6321 Daniels Pkwy Suite 200"')
            assert hq_span.endswith('"location":"Fort Myers, United States"')

    run_async(scenario())


def test_a_sumble_conflict_projects_only_its_own_retained_evidence(tmp_path: Path) -> None:
    """Defect #29 end to end: the live crash, replayed through the engine that raised it.

    The conflicting ``exa_websets`` claim is planted carrying the *legacy* described span, because
    that is what 187 claims in the live database still carry — root cause 1 stops new ones being
    born, but the projection must be safe over the old ones too.
    """

    async def scenario() -> None:
        workspace_id = "ws-defect-29-sumble"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn,
                storage,
                workspace_id=workspace_id,
                account_tier="tier4",
                tier_claim_source_tier=4,
            )
            account_id = EntityId(ready.account_id)
            run_id = ProjectRunId(started.project_run_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            # A real retained Exa artifact, and a claim that describes rather than quotes it.
            exa_bytes = json.dumps(
                _live_shaped_item("item_defect_29_conflict"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            exa_artifact = await capture_discovery_artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                content=exa_bytes,
                media_type="application/json",
                source_key="exa_websets",
                source_url="https://insighthealth.ai",
            )
            assert not _json_contains_text(exa_bytes, _LIVE_DESCRIBED_SPAN)
            exa_claim_id = await insert_claim(
                conn,
                stamp_reuse(
                    account_claim(
                        entity_id=account_id,
                        field_key=_HQ,
                        value_json={
                            "raw": "Fort Myers, United States",
                            "city": "Fort Myers",
                            "region": "Florida",
                            "country": "United States",
                            "country_code": "US",
                        },
                        source_tier=2,
                        extraction_method=ExtractionMethod.API,
                        confidence=0.5,
                        run_id=RunId(started.project_run_id),
                        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                        source_url="https://insighthealth.ai",
                        evidence_span=_LIVE_DESCRIBED_SPAN,
                    ).model_copy(
                        update={"source_key": "exa_websets", "artifact_key": exa_artifact}
                    ),
                    workspace_id=workspace_id,
                ),
            )

            http = _OrganizationsHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            starter = SumbleAccountGapStarter(
                coordinator=SumbleAccountGapCoordinator(
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    client_factory=client_factory,
                ),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits={_HQ: Decimal(25)},
                provider_credit_cap=25,
            )
            request = _request(account_id)
            causation = EntityResearchProviderCausationStore(conn_factory=same_connection)

            async def observe(
                reservation: ProviderOperationReservation,
            ) -> ProviderOperationObservation:
                # The provider-neutral operation row the projection's lineage joins to. The full
                # journal-backed observation needs an agent turn this focused test does not run.
                await causation._project_operation(conn, request=request, operation=reservation)
                return ProviderOperationObservation(
                    observation_id=uuid4(),
                    tool_request_id=request.tool_call_id,
                    operation_ref=reservation.operation_ref,
                    workspace_id=reservation.workspace_id,
                    disposition=reservation.observation_disposition.value,
                    created_at=datetime.now(UTC),
                )

            drafts = await action.execute(
                request,
                before_dispatch=observe,
                settle_terminal=observe,
            )
            (draft,) = drafts
            (field,) = draft.fields
            assert field.field_key == _HQ
            assert field.outcome is ResearchFieldOutcome.CONFLICT
            # The contender is still fully reported — by reference, which is what a conflict is.
            assert f"claim:{exa_claim_id}" in field.claim_refs
            assert field.decision_refs == (f"conflict:{account_id}:{_HQ}",)
            # …but this tool vouches only for the artifact it bought.
            assert {item.source_key for item in field.evidence} == {ORGANIZATIONS_SOURCE_KEY}
            for item in field.evidence:
                cited = await storage.get(item.artifact_ref.removeprefix("artifact:"))
                assert _json_contains_text(cited, item.evidence_span)

            reader = SumbleEntityResearchLineageReader(
                provider_kind=action.provider_kind,
                conn_factory=same_connection,
            )
            store = EntityResearchResultStore(
                storage=storage,
                conn_factory=same_connection,
                lineage_readers={action.provider_kind: reader},
            )
            lineage = await reader.load(
                request=request,
                operation=draft.operation,
                snapshot_ref=draft.snapshot_ref,
            )
            # The exact engine calls that raised live, in order.
            await store._validate_artifacts(conn, request=request, lineage=lineage)
            await store._validate_fields(conn, request=request, draft=draft, lineage=lineage)

            # The guard keeps its teeth: re-projecting the contender's evidence still refuses.
            laundered = draft.model_copy(
                update={
                    "fields": (
                        field.model_copy(
                            update={
                                "evidence": field.evidence
                                + (
                                    ResearchEvidenceProjection(
                                        evidence_ref=f"research-evidence:{uuid4()}",
                                        source_key="exa_websets",
                                        provider_source_id="defect-29-org-request",
                                        source_url="https://insighthealth.ai",
                                        artifact_ref=f"artifact:{exa_artifact}",
                                        evidence_span=_LIVE_DESCRIBED_SPAN,
                                    ),
                                )
                            }
                        ),
                    )
                }
            )
            with pytest.raises(
                EntityResearchResultIntegrityError,
                match="projected evidence span is absent from retained artifact",
            ):
                await store._validate_fields(
                    conn, request=request, draft=laundered, lineage=lineage
                )

    run_async(scenario())


# --- The second act: replaying a projection that was written but never admitted ------------------

_LEGACY_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:test:defect-29:superseded-projection")
"""Stands in for any evidence-ref minting rule the shipped code no longer reproduces."""


class _PreFixAccountProjection(SumbleAccountSemanticEnrichmentAction):
    """The pre-``aa88e0b0`` account projection: a conflict published its *contenders'* evidence.

    Only the composition is rolled back — the operation, the provider call, the retained snapshot
    and the durable gap ledger are all the real production ones — so the projection this stores is
    exactly the shape the live job wedged on: a ``sumble_organizations`` result carrying an
    ``exa_websets`` artifact and its described (unquotable) span.
    """

    def _field(
        self,
        result: object,
        *,
        claims_by_id: Mapping[UUID, Mapping[str, object]],
        provider_request_id: str,
        operation_id: UUID,
    ) -> ResearchFieldResultProjection:
        projection = super()._field(
            result,
            claims_by_id=claims_by_id,
            provider_request_id=provider_request_id,
            operation_id=operation_id,
        )
        if projection.outcome is not ResearchFieldOutcome.CONFLICT:
            return projection
        return projection.model_copy(
            update={
                "evidence": projection.evidence
                + tuple(
                    ResearchEvidenceProjection(
                        evidence_ref=(
                            f"research-evidence:{uuid5(_LEGACY_EVIDENCE_NAMESPACE, str(row['id']))}"
                        ),
                        source_key=str(row["source_key"]),
                        provider_source_id=provider_request_id,
                        source_url=str(row["source_url"]) if row["source_url"] else None,
                        artifact_ref=f"artifact:{row['artifact_key']}",
                        evidence_span=str(row["evidence_span"]),
                    )
                    for row in claims_by_id.values()
                    if str(row["source_key"]) != ORGANIZATIONS_SOURCE_KEY
                )
            }
        )


class _LegacyEvidenceRefAccountProjection(SumbleAccountSemanticEnrichmentAction):
    """A superseded composition that is *admissible*: only its evidence-ref minting differs.

    The old-code-admission world c7d6da82 was written for. Its spans are the operation's own
    retained provenance, so the anti-fabrication guard admits it — but current code no longer mints
    those evidence refs, so a replay recomputes something different and lands in the same mismatch
    branch as the defect-29 draft.
    """

    def _field(
        self,
        result: object,
        *,
        claims_by_id: Mapping[UUID, Mapping[str, object]],
        provider_request_id: str,
        operation_id: UUID,
    ) -> ResearchFieldResultProjection:
        projection = super()._field(
            result,
            claims_by_id=claims_by_id,
            provider_request_id=provider_request_id,
            operation_id=operation_id,
        )
        return projection.model_copy(
            update={
                "evidence": tuple(
                    item.model_copy(
                        update={
                            "evidence_ref": (
                                "research-evidence:"
                                f"{uuid5(_LEGACY_EVIDENCE_NAMESPACE, item.evidence_ref)}"
                            )
                        }
                    )
                    for item in projection.evidence
                )
            }
        )


Observer = Callable[[ProviderOperationReservation], Awaitable[ProviderOperationObservation]]


@dataclass(frozen=True)
class _Wedge:
    """The live wedge's first half: a superseded projection stored under code since replaced."""

    request: GovernedResearchToolRequest
    account_id: EntityId
    observe: Observer
    action: SumbleAccountSemanticEnrichmentAction
    store: EntityResearchResultStore
    reader: SumbleEntityResearchLineageReader
    first_write: ExternalResearchProjectionDraft
    stored_normalized_key: str
    operation_ref: str


async def _wedge_a_stored_projection(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    first_write: type[SumbleAccountSemanticEnrichmentAction] = _PreFixAccountProjection,
) -> _Wedge:
    """Run one real Sumble enrichment under superseded projection code and store its first draft.

    ``first_write`` is the code that composed it: the defect-29 draft by default (evidence the span
    guard can never admit), or any other superseded composition current code no longer reproduces.
    """

    started, ready = await _seed_selected_high_tier_account(
        conn,
        storage,
        workspace_id=workspace_id,
        account_tier="tier4",
        tier_claim_source_tier=4,
    )
    account_id = EntityId(ready.account_id)
    run_id = ProjectRunId(started.project_run_id)

    @asynccontextmanager
    async def same_connection() -> AsyncIterator[AsyncConnection]:
        yield conn

    exa_bytes = json.dumps(
        _live_shaped_item("item_defect_29_wedge"), sort_keys=True, separators=(",", ":")
    ).encode()
    exa_artifact = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=exa_bytes,
        media_type="application/json",
        source_key="exa_websets",
        source_url="https://insighthealth.ai",
    )
    assert not _json_contains_text(exa_bytes, _LIVE_DESCRIBED_SPAN)
    await insert_claim(
        conn,
        stamp_reuse(
            account_claim(
                entity_id=account_id,
                field_key=_HQ,
                value_json={
                    "raw": "Fort Myers, United States",
                    "city": "Fort Myers",
                    "region": "Florida",
                    "country": "United States",
                    "country_code": "US",
                },
                source_tier=2,
                extraction_method=ExtractionMethod.API,
                confidence=0.5,
                run_id=RunId(started.project_run_id),
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                source_url="https://insighthealth.ai",
                evidence_span=_LIVE_DESCRIBED_SPAN,
            ).model_copy(update={"source_key": "exa_websets", "artifact_key": exa_artifact}),
            workspace_id=workspace_id,
        ),
    )

    http = _OrganizationsHttp("insighthealth.ai")

    def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
        return SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=maximum),
            http=http,
            cents_per_credit=cents,
        )

    starter = SumbleAccountGapStarter(
        coordinator=SumbleAccountGapCoordinator(
            api_key=SecretStr("fixture"),
            storage=storage,
            cents_per_credit=Decimal("0.5"),
            conn_factory=same_connection,
            client_factory=client_factory,
        ),
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=same_connection,
    )

    def build(
        action_type: type[SumbleAccountSemanticEnrichmentAction],
    ) -> SumbleAccountSemanticEnrichmentAction:
        return action_type(
            starter=starter,
            storage=storage,
            conn_factory=same_connection,
            workspace_id=workspace_id,
            project_id=started.project_id,
            project_run_id=run_id,
            account_id=account_id,
            field_expected_value_credits={_HQ: Decimal(25)},
            provider_credit_cap=25,
        )

    request = _request(account_id)
    causation = EntityResearchProviderCausationStore(conn_factory=same_connection)

    async def observe(reservation: ProviderOperationReservation) -> ProviderOperationObservation:
        await causation._project_operation(conn, request=request, operation=reservation)
        return ProviderOperationObservation(
            observation_id=uuid4(),
            tool_request_id=request.tool_call_id,
            operation_ref=reservation.operation_ref,
            workspace_id=reservation.workspace_id,
            disposition=reservation.observation_disposition.value,
            created_at=datetime.now(UTC),
        )

    (stored_draft,) = await build(first_write).execute(
        request, before_dispatch=observe, settle_terminal=observe
    )
    operation_ref = stored_draft.operation.operation_ref
    stored_normalized_key = str(
        (
            await conn.execute(
                text(
                    "SELECT normalized_result_artifact_key FROM entity_research_sumble_projection "
                    "WHERE provider_operation_ref=:operation_ref"
                ),
                {"operation_ref": operation_ref},
            )
        ).scalar_one()
    )
    reader = SumbleEntityResearchLineageReader(
        provider_kind=stored_draft.operation.provider_kind,
        conn_factory=same_connection,
    )
    return _Wedge(
        request=request,
        account_id=account_id,
        observe=observe,
        action=build(SumbleAccountSemanticEnrichmentAction),
        store=EntityResearchResultStore(
            storage=storage,
            conn_factory=same_connection,
            lineage_readers={stored_draft.operation.provider_kind: reader},
        ),
        reader=reader,
        first_write=stored_draft,
        stored_normalized_key=stored_normalized_key,
        operation_ref=operation_ref,
    )


async def _plant_governed_causation(
    conn: AsyncConnection, request: GovernedResearchToolRequest, *, operation_ref: str
) -> ProviderOperationObservation:
    """Plant the run→job→turn→event→tool_request→observation chain ``request`` claims to have.

    The chain is written directly rather than driven through the governed tool invoker (which needs
    a live agent runtime, journal and budget reservation), but everything downstream of it is the
    real thing: the returned observation is what ``EntityResearchResultStore.persist`` admits a
    result against, so the admitted result rows/artifact this suite reads back are written by
    production code, not by the test. Every scope value is the request's own or is read off the
    real provider-operation row, because the tool-request and observation authority triggers check
    exactly that identity.
    """

    scope = (
        (
            await conn.execute(
                text(
                    "SELECT workspace_id, project_id, project_run_id, target_entity_id, "
                    "source_key, field_keys FROM entity_research_provider_operation "
                    "WHERE operation_ref=:operation_ref"
                ),
                {"operation_ref": operation_ref},
            )
        )
        .mappings()
        .one()
    )
    ids = {
        "run": request.research_run_id,
        "job": request.job_id,
        "turn": request.agent_turn_id,
        "execution": request.agent_execution_id,
        "request": request.tool_call_id,
        "event": uuid4(),
        "observation": uuid4(),
    }
    field_keys = [str(value) for value in scope["field_keys"]]
    authority = [
        {"field_key": key, "source_keys": [str(scope["source_key"])]} for key in field_keys
    ]
    selection_id = uuid4()
    workspace_id = str(scope["workspace_id"])
    project_id = str(scope["project_id"])
    product_id = "product:defect-29"
    checkpoint = f"checkpoint:{ids['run']}:{scope['target_entity_id']}"
    context = {
        "agent_execution_id": str(ids["execution"]),
        "agent_turn_id": str(ids["turn"]),
        "role": "account",
        "subject_type": "account",
        "subject_entity_id": str(scope["target_entity_id"]),
        "job_id": str(ids["job"]),
        "research_run_id": str(ids["run"]),
        "workspace_id": workspace_id,
        "project_id": project_id,
        "product_id": product_id,
        "project_run_id": str(scope["project_run_id"]),
        "checkpoint_thread_id": checkpoint,
        # The governed-request trigger checks the request against what the turn admitted.
        "tool_names": [request.tool_name],
        "admitted_field_keys": field_keys,
        "admitted_source_keys": [str(scope["source_key"])],
        "field_source_authority": authority,
        "research_questions": ["what?"],
    }
    selection = {
        "selection_id": str(selection_id),
        "subject_type": "account",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "product_id": product_id,
        "project_run_id": str(scope["project_run_id"]),
        "budget_envelope_ref": "budget:defect-29",
    }
    params: dict[str, Any] = {
        **{f"{name}_id": value for name, value in ids.items()},
        "workspace_id": workspace_id,
        "project_id": project_id,
        "project_run_id": scope["project_run_id"],
        "target_entity_id": scope["target_entity_id"],
        "source_key": str(scope["source_key"]),
        "field_keys": field_keys,
        "product_id": product_id,
        "operation_ref": operation_ref,
        "sha": "0" * 64,
        "tool_input_sha256": request.tool_input_sha256,
        "checkpoint": checkpoint,
        "context": json.dumps(context),
        "authority": json.dumps(authority),
        "selection_id": selection_id,
        "lifecycle": json.dumps(
            {
                "run_id": str(ids["run"]),
                "run_kind": "account_research",
                "selection": selection,
            }
        ),
        "authorization": json.dumps(
            {
                "job_id": str(ids["job"]),
                "research_run_id": str(ids["run"]),
                "subject_type": "account",
                "subject_entity_id": str(scope["target_entity_id"]),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": str(scope["project_run_id"]),
                "checkpoint_thread_id": checkpoint,
                "selection": selection,
            }
        ),
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_run
                (research_run_id, run_kind, subject_type, workspace_id, project_id, product_id,
                 project_run_id, selection_id, lifecycle_json, lifecycle_sha256,
                 budget_envelope_ref, budget_cap_cents, concurrency_limit)
            VALUES (:run_id, 'account_research', 'account', :workspace_id, :project_id,
                    :product_id, :project_run_id, :selection_id, CAST(:lifecycle AS jsonb), :sha,
                    'budget:defect-29', 1000, 1)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job
                (job_id, research_run_id, subject_type, subject_entity_id, workspace_id,
                 project_id, product_id, project_run_id, authorization_json, authorization_sha256,
                 priority, budget_envelope_ref, budget_cap_cents, checkpoint_thread_id,
                 initial_state_sha256, current_state_sha256)
            VALUES (:job_id, :run_id, 'account', :target_entity_id, :workspace_id, :project_id,
                    :product_id, :project_run_id, CAST(:authorization AS jsonb), :sha, 0,
                    'budget:defect-29', 1000, :checkpoint, :sha, :sha)
            """
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
            VALUES (:turn_id, :execution_id, :job_id, :run_id, 'account', 'account',
                    :target_entity_id, :workspace_id, :project_id, :product_id, :project_run_id,
                    :checkpoint, CAST(:context AS jsonb), :sha, '{}'::jsonb, :sha, '[]'::jsonb,
                    :sha, :sha)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_event
                (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id, tool_name,
                 tool_version, tool_input_sha256, payload_json)
            VALUES (:event_id, :turn_id, :execution_id, 'tool_started', :raw_call, :tool_name,
                    :tool_version, :tool_input_sha256, '{}'::jsonb)
            """
        ),
        {
            **params,
            "raw_call": f"defect-29-call:{request.tool_call_id}",
            "tool_name": request.tool_name,
            "tool_version": request.tool_version,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 workspace_id, project_id, product_id, project_run_id, tool_name, tool_version,
                 tool_input_sha256, field_plan_ref, source_plan_ref, field_keys, source_keys,
                 questions, budget_reservation_key, idempotency_key, field_source_authority)
            VALUES (:request_id, :turn_id, :execution_id, :event_id, :raw_call, :run_id,
                    :job_id, 'account', :target_entity_id, :workspace_id, :project_id,
                    :product_id, :project_run_id, :tool_name, :tool_version, :tool_input_sha256,
                    :field_plan_ref, :source_plan_ref,
                    CAST(:field_keys AS text[]), ARRAY[:source_key], '{}'::text[],
                    :budget_key, :idempotency_key, CAST(:authority AS jsonb))
            """
        ),
        {
            **params,
            "raw_call": f"defect-29-call:{request.tool_call_id}",
            "tool_name": request.tool_name,
            "tool_version": request.tool_version,
            "field_plan_ref": request.field_plan_ref,
            "source_plan_ref": request.source_plan_ref,
            "budget_key": request.budget_reservation_key,
            "idempotency_key": request.idempotency_key,
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_observation
                (observation_id, tool_request_id, external_workspace_id, disposition,
                 provider_operation_ref)
            VALUES (:observation_id, :request_id, :workspace_id, 'replay_observation',
                    :operation_ref)
            """
        ),
        params,
    )
    return ProviderOperationObservation(
        observation_id=ids["observation"],
        tool_request_id=request.tool_call_id,
        operation_ref=operation_ref,
        workspace_id=workspace_id,
        disposition=ProviderObservationDisposition.REPLAY.value,
        created_at=datetime.now(UTC),
    )


def test_a_never_admitted_stored_projection_is_recomputed_on_replay(tmp_path: Path) -> None:
    """The closed loop, end to end: 02:14's refusal, 03:17's replay, and 03:46's re-refusal.

    The stored draft cites a foreign contender's span, so the anti-fabrication guard can never
    admit it — serving it back on resume wedges the job forever. Nothing was ever admitted for the
    operation, so the draft is not history: the replay recomputes from the retained snapshot.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            wedge = await _wedge_a_stored_projection(
                conn, storage, workspace_id="ws-defect-29-wedge"
            )

            # 02:14 — the first write is a draft that no guard can ever admit.
            (defective_field,) = wedge.first_write.fields
            assert _LIVE_DESCRIBED_SPAN in {item.evidence_span for item in defective_field.evidence}
            defective_lineage = await wedge.reader.load(
                request=wedge.request,
                operation=wedge.first_write.operation,
                snapshot_ref=wedge.first_write.snapshot_ref,
            )
            with pytest.raises(
                EntityResearchResultIntegrityError,
                match="projected evidence span is absent from retained artifact",
            ):
                await wedge.store._validate_fields(
                    conn,
                    request=wedge.request,
                    draft=wedge.first_write,
                    lineage=defective_lineage,
                )
            # …so no result was ever admitted for this operation. That is the whole distinction.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_result "
                        "WHERE provider_operation_ref=:operation_ref"
                    ),
                    {"operation_ref": wedge.operation_ref},
                )
            ).scalar_one() == 0

            # 03:17 — the resume replays the terminal operation under current code.
            (replayed,) = await wedge.action.execute(
                wedge.request, before_dispatch=wedge.observe, settle_terminal=wedge.observe
            )
            (fresh,) = replayed.fields
            assert fresh.field_key == _HQ
            assert fresh.outcome is ResearchFieldOutcome.CONFLICT
            assert {item.source_key for item in fresh.evidence} == {ORGANIZATIONS_SOURCE_KEY}
            for item in fresh.evidence:
                cited = await storage.get(item.artifact_ref.removeprefix("artifact:"))
                assert _json_contains_text(cited, item.evidence_span)

            # …and the engine that refused at 02:14 and 03:46 now admits it.
            replay_lineage = await wedge.reader.load(
                request=wedge.request,
                operation=replayed.operation,
                snapshot_ref=replayed.snapshot_ref,
            )
            await wedge.store._validate_artifacts(
                conn, request=wedge.request, lineage=replay_lineage
            )
            await wedge.store._validate_fields(
                conn, request=wedge.request, draft=replayed, lineage=replay_lineage
            )

            # Supersession is by non-adoption: the append-only first draft is untouched at rest.
            assert (
                str(
                    (
                        await conn.execute(
                            text(
                                "SELECT normalized_result_artifact_key "
                                "FROM entity_research_sumble_projection "
                                "WHERE provider_operation_ref=:operation_ref"
                            ),
                            {"operation_ref": wedge.operation_ref},
                        )
                    ).scalar_one()
                )
                == wedge.stored_normalized_key
            )
            audit = await storage.get(wedge.stored_normalized_key)
            assert _json_contains_text(audit, _LIVE_DESCRIBED_SPAN)

    run_async(scenario())


def test_an_admitted_result_replays_exactly_what_that_result_recorded(tmp_path: Path) -> None:
    """The ``c7d6da82`` guarantee, kept — but pinned to the admitted RESULT, not the stored row.

    The pin moved because the old one was falsified live at 06:37:33 (job 3cc0a4f2): "a result was
    admitted for this operation" is not "the stored projection row is what was admitted", and once
    a never-admitted operation's first replay serves fresh they diverge permanently. Here they do
    NOT diverge — this is the world c7d6da82 was written for, an admission made from the stored
    first write — so the observable outcome is unchanged: the replay serves that first write, and
    the recomputation current code would have produced is not served.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            wedge = await _wedge_a_stored_projection(
                conn,
                storage,
                workspace_id="ws-defect-29-admitted",
                first_write=_LegacyEvidenceRefAccountProjection,
            )
            # The real admission of that first write, through the production result store.
            observation = await _plant_governed_causation(
                conn, wedge.request, operation_ref=wedge.operation_ref
            )
            admitted = await wedge.store.persist(
                request=wedge.request, observation=observation, draft=wedge.first_write
            )
            assert admitted.fields == wedge.first_write.fields

            second_job = _request(wedge.account_id)
            (replayed,) = await wedge.action.execute(
                second_job, before_dispatch=wedge.observe, settle_terminal=wedge.observe
            )
            (served,) = replayed.fields
            assert served.field_key == _HQ
            # Byte-for-byte what the admitted result recorded — which here IS the stored draft.
            assert served == wedge.first_write.fields[0]
            assert replayed.snapshot_ref == wedge.first_write.snapshot_ref
            # …and not what today's composition would mint for the same durable snapshot.
            operation_id = wedge.operation_ref.rsplit(":", 1)[-1]
            recomputed_refs = {
                f"research-evidence:{uuid5(_EVIDENCE_NAMESPACE, f'{operation_id}:{claim}')}"
                for claim in (ref.removeprefix("claim:") for ref in served.claim_refs)
            }
            served_refs = {item.evidence_ref for item in served.evidence}
            assert served_refs and served_refs.isdisjoint(recomputed_refs)

    run_async(scenario())


def test_the_next_job_replays_the_fresh_projection_its_admitted_result_recorded(
    tmp_path: Path,
) -> None:
    """The 06:37:33 wedge (job 3cc0a4f2), which the first amendment armed rather than closed.

    eea48931's resume replayed operation 7e29c0bf while nothing was admitted, was served the fresh
    recomputation, and admitted result c8be9969 FROM it. The stored projection row is append-only,
    so it still holds the pre-aa88e0b0 draft — and the next job to replay the same operation was
    handed that draft back, straight into the span guard it had already failed twice. What replays
    is what the first admitted result recorded, so the span guard admits it by construction: those
    spans passed at admission.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            wedge = await _wedge_a_stored_projection(
                conn, storage, workspace_id="ws-defect-29-armed"
            )

            # eea48931's resume: nothing admitted yet, so the draft is superseded by the fresh one.
            (resumed,) = await wedge.action.execute(
                wedge.request, before_dispatch=wedge.observe, settle_terminal=wedge.observe
            )
            assert {item.source_key for item in resumed.fields[0].evidence} == {
                ORGANIZATIONS_SOURCE_KEY
            }
            observation = await _plant_governed_causation(
                conn, wedge.request, operation_ref=wedge.operation_ref
            )
            admitted = await wedge.store.persist(
                request=wedge.request, observation=observation, draft=resumed
            )
            assert admitted.fields == resumed.fields
            # The append-only row still holds the draft the guard refused — that is the trap.
            assert (
                str(
                    (
                        await conn.execute(
                            text(
                                "SELECT normalized_result_artifact_key "
                                "FROM entity_research_sumble_projection "
                                "WHERE provider_operation_ref=:operation_ref"
                            ),
                            {"operation_ref": wedge.operation_ref},
                        )
                    ).scalar_one()
                )
                == wedge.stored_normalized_key
            )
            assert _json_contains_text(
                await storage.get(wedge.stored_normalized_key), _LIVE_DESCRIBED_SPAN
            )

            # 06:37:33 — a second job replays the same terminal operation.
            second_job = _request(wedge.account_id)
            (served,) = await wedge.action.execute(
                second_job, before_dispatch=wedge.observe, settle_terminal=wedge.observe
            )
            # The engine that killed job 3cc0a4f2 at 06:37:33 is the oracle: served the stored
            # draft, this raises "projected evidence span is absent from retained artifact".
            lineage = await wedge.reader.load(
                request=second_job,
                operation=served.operation,
                snapshot_ref=served.snapshot_ref,
            )
            await wedge.store._validate_artifacts(conn, request=second_job, lineage=lineage)
            await wedge.store._validate_fields(
                conn, request=second_job, draft=served, lineage=lineage
            )

            (field,) = served.fields
            assert field == admitted.fields[0]
            assert _LIVE_DESCRIBED_SPAN not in {item.evidence_span for item in field.evidence}
            for item in field.evidence:
                cited = await storage.get(item.artifact_ref.removeprefix("artifact:"))
                assert _json_contains_text(cited, item.evidence_span)

    run_async(scenario())


class _PreFixCommitteeProjection(SumbleCommitteeSemanticResearchAction):
    """A committee first draft whose evidence refs current code no longer reproduces."""

    @staticmethod
    def _committee_evidence_ref(operation_id: object, claim_id: object) -> str:
        return (
            f"research-evidence:{uuid5(_LEGACY_EVIDENCE_NAMESPACE, f'{operation_id}:{claim_id}')}"
        )


def test_a_never_admitted_committee_projection_is_recomputed_on_replay(tmp_path: Path) -> None:
    """The same amendment on the committee branch, whose first-write-wins rule is the same rule."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            durable = await _committee_setup(conn, storage, workspace_id="ws-defect-29-committee")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=_CommitteeTransport(),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(durable, cents_per_credit=Decimal("0.5"))
            ready = await coordinator.start(preflight)
            for _ in range(2):  # the People submission settles on the polling path
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"
                    ),
                    {
                        "id": ready.operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                ready = await coordinator.start(preflight)
            assert ready.operation.state.value == "ready"

            account = await get_account(conn, durable.account_id)
            assert account is not None
            selected = tuple(
                await SumbleCommitteeSource(
                    operation_ids={durable.account_id: ready.operation.operation_id},
                    storage=storage,
                    conn_factory=same_connection,
                ).find_candidates(account, limit=durable.people_limit)
            )
            assert selected

            await seed_packs(conn)

            def build(
                action_type: type[SumbleCommitteeSemanticResearchAction],
            ) -> SumbleCommitteeSemanticResearchAction:
                return action_type(
                    preflight=preflight,
                    coordinator=coordinator,
                    storage=storage,
                    conn_factory=same_connection,
                    gateway=FakeGateway(),
                    role_model="defect-29-role-model",
                )

            action = build(SumbleCommitteeSemanticResearchAction)
            committee = await action._discover_committee_members(
                conn,
                account_entity_id=durable.account_id,
                run_id=RunId(UUID(str(durable.project_run_id))),
                workspace_id=durable.workspace_id,
                selected=selected,
                budget_cap_cents=durable.money_budget_cap_cents,
            )
            request = _committee_tool_request(durable)
            provider_operation = action._committee_descriptor(
                ready.operation,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=True,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_operation
                        (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                         subject_type, target_entity_id, parent_account_id, source_key,
                         field_keys, request_artifact_ref, reserved_at, dispatched_at)
                    VALUES
                        (:operation_ref, :provider_kind, :workspace_id, :project_id,
                         :project_run_id, :subject_type, :target_entity_id, :parent_account_id,
                         :source_key, :field_keys, :request_artifact_ref, :reserved_at,
                         :dispatched_at)
                    """
                ),
                {
                    "operation_ref": provider_operation.operation_ref,
                    "provider_kind": provider_operation.provider_kind,
                    "workspace_id": provider_operation.workspace_id,
                    "project_id": provider_operation.project_id,
                    "project_run_id": provider_operation.project_run_id,
                    "subject_type": provider_operation.subject_type.value,
                    "target_entity_id": provider_operation.target_entity_id,
                    "parent_account_id": provider_operation.parent_account_id,
                    "source_key": provider_operation.source_key,
                    "field_keys": list(provider_operation.field_keys),
                    "request_artifact_ref": provider_operation.request_artifact_ref,
                    "reserved_at": provider_operation.reserved_at,
                    "dispatched_at": provider_operation.dispatched_at,
                },
            )

            _, superseded = await build(_PreFixCommitteeProjection)._persist_committee_projection(
                request=request,
                operation=ready.operation,
                provider_operation=provider_operation,
                committee=committee,
                excluded=0,
                ambiguous=0,
            )
            stored_refs = {
                item.evidence_ref
                for subject in superseded
                for field in subject.fields
                for item in field.evidence
            }
            assert stored_refs
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_result "
                        "WHERE provider_operation_ref=:operation_ref"
                    ),
                    {"operation_ref": provider_operation.operation_ref},
                )
            ).scalar_one() == 0

            _, replayed = await action._persist_committee_projection(
                request=request,
                operation=ready.operation,
                provider_operation=provider_operation,
                committee=committee,
                excluded=0,
                ambiguous=0,
            )
            fresh_refs = {
                item.evidence_ref
                for subject in replayed
                for field in subject.fields
                for item in field.evidence
            }
            assert fresh_refs == {
                action._committee_evidence_ref(
                    ready.operation.operation_id, claim.removeprefix("claim:")
                )
                for subject in replayed
                for field in subject.fields
                for claim in field.claim_refs
            }
            assert fresh_refs.isdisjoint(stored_refs)

    run_async(scenario())
