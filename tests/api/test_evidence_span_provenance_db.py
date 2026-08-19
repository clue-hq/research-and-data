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
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultIntegrityError,
    EntityResearchResultStore,
    ProviderOperationObservation,
    ProviderOperationReservation,
    _json_contains_text,
)
from clue_api.exa_websets_materialization import ExaWebsetsD4Materializer
from clue_api.sumble_account_gaps import SumbleAccountGapCoordinator, SumbleAccountGapStarter
from clue_api.sumble_entity_research_tools import (
    SumbleAccountSemanticEnrichmentAction,
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
    ResearchSubjectType,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import capture_discovery_artifact
from clue_research.identity import stamp_reuse
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_storage import FsStorage
from tests.api.test_exa_websets_materialization_d4 import _company_item, _seed_terminal_batch
from tests.api.test_sumble_account_gaps_s1 import _seed_selected_high_tier_account
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.profiling.conftest import conn_session_factory

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
                await conn.exec_driver_sql(
                    "SELECT field_key, artifact_key, evidence_span FROM claim "
                    "WHERE source_key = 'exa_websets' AND artifact_key = ANY(%s)",
                    (list(item_keys),),
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
