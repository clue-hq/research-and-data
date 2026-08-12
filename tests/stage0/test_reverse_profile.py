"""DB-backed tests for M5.1 — client reverse-profiling → versioned Client Knowledge Base.

Exercises the reverse-profiling orchestration end-to-end against the real Postgres substrate,
driving the waterfall through a fake resolver bound to a real seeded ``source_key`` (the production
dispatch path). Covers every M5.1 acceptance criterion: minimum-input → versioned base, materials
shortcut, tenant isolation, tier ordering, versioning/supersession, idempotent re-entry, budget
halt, coverage.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Secrets
from clue_core import (
    ClaimDraft,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    account_claim,
    new_run_id,
)
from clue_research.adapters import CallableClaimExtractor, span_for
from clue_research.claimstore import (
    ALL_WORKSPACES,
    ReuseScopeError,
    WorkspaceScope,
    claims_for,
    current_value,
    insert_claim,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.exa_search import register_exa_search_resolver
from clue_research.resolvers.http import ProviderResponseError
from clue_research.sources import bind_resolver
from clue_research.stage0 import (
    CLIENT_BASELINE_FIELDS,
    CLIENT_KB_VERSION,
    CLIENT_KNOWLEDGE_FIELDS,
    CLIENT_KNOWLEDGE_REUSE_POLICY,
    ClientInput,
    FieldProgressStatus,
    SurfaceClass,
    VolunteeredMaterial,
    current_kb_version,
    read_client_kb,
    reverse_profile,
)
from clue_research.stage0 import client_kb as client_kb_module
from clue_research.stage0.client_kb import _judge_tier4_claims
from clue_research.stage0.fields import (
    CLIENT_COMPETITOR,
    CLIENT_CUSTOMER,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRICING_POSTURE,
    CLIENT_PRODUCT,
    CLIENT_PROOF_POINT,
    CLIENT_VALUE_PROP,
)
from tests._run_lineage import assert_written_claims_are_attributable
from tests.stage0._fakes import FakeResolver, RecordingJudge, make_tier4_claim
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db", "resolver_bindings")

_CLIENT = "tenant-acme"


def _owned_values(suffix: str = "") -> dict[str, object]:
    """Canned scrape values for the owned/positioning client fields."""
    return {
        CLIENT_VALUE_PROP: f"We help teams ship faster{suffix}",
        CLIENT_PRODUCT: f"A CI platform{suffix}",
        CLIENT_DIFFERENTIATOR: f"Fastest builds{suffix}",
        CLIENT_PRICING_POSTURE: "usage-based",
        CLIENT_PROOF_POINT: "Acme cut build time 70%",
        CLIENT_CUSTOMER: [{"name": "BigCo", "domain": "bigco.example"}, {"name": "MidCo"}],
        CLIENT_ICP_EVIDENCE: {"industries": ["devtools"], "sizes": ["mid-market"]},
    }


def _bind_firecrawl(values: dict[str, object]) -> None:
    bind_resolver("firecrawl_site", FakeResolver(tier=2, values=values))


def _input(materials: tuple[VolunteeredMaterial, ...] = ()) -> ClientInput:
    return ClientInput(name="Acme Corp", website="https://acme.example", materials=materials)


def test_minimum_input_produces_versioned_kb() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)

            # versioned base, single resolved entity
            assert result.ref.client_kb_version == 1
            assert result.coverage.filled_count >= 5  # owned + positioning surfaces filled
            assert (
                await current_kb_version(conn, result.ref.client_entity_id, workspace_id=_CLIENT)
                == 1
            )

            # every populated field is queryable with provenance, tenant-scoped
            scope = WorkspaceScope.for_workspace(_CLIENT)
            cv = await current_value(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=scope
            )
            assert cv is not None
            assert cv.value_json == "We help teams ship faster"
            assert cv.provenance.source_tier == 2

            # client-knowledge claims are tenant-private (never the shared public base)
            (claim,) = await claims_for(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=ALL_WORKSPACES
            )
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == _CLIENT
            # a public-only read sees nothing (isolation holds)
            assert (
                await current_value(
                    conn,
                    result.ref.client_entity_id,
                    CLIENT_VALUE_PROP,
                    scope=WorkspaceScope.public_only(),
                )
                is None
            )

    run_async(_run())


def test_materials_shortcut_derivation() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            # the scraper would say one thing; the client's deck asserts another (tier-1 human wins)
            _bind_firecrawl(_owned_values())
            deck = VolunteeredMaterial(
                kind="deck",
                label="pitch.pdf",
                content="Our value prop: we eliminate flaky CI.",
                asserted_fields={CLIENT_VALUE_PROP: "We eliminate flaky CI"},
            )
            result = await reverse_profile(conn, _input((deck,)), workspace_id=_CLIENT)

            scope = WorkspaceScope.for_workspace(_CLIENT)
            cv = await current_value(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=scope
            )
            assert cv is not None
            # the volunteered tier-1 fact beats the tier-2 scrape
            assert cv.value_json == "We eliminate flaky CI"
            assert cv.provenance.source_tier == 1

            # and the waterfall did NOT also write a value_prop claim (derivation was shortcut)
            value_prop_claims = await claims_for(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=ALL_WORKSPACES
            )
            assert len(value_prop_claims) == 1
            assert value_prop_claims[0].extraction_method is ExtractionMethod.HUMAN

    run_async(_run())


def test_no_materials_path_completes() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            assert result.ref.client_kb_version == 1
            assert result.coverage.filled_count > 0

    run_async(_run())


def test_tier4_spanless_claim_never_surfaces() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl({CLIENT_VALUE_PROP: "tier-2 truth"})
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            entity_id = result.ref.client_entity_id

            # inject a span-less tier-4 synthesized claim for the same field
            tier4 = make_tier4_claim(entity_id, CLIENT_VALUE_PROP, with_span=False)
            tier4 = stamp_reuse(tier4, workspace_id=_CLIENT, policy=CLIENT_KNOWLEDGE_REUSE_POLICY)
            await insert_claim(conn, tier4, validate_field=False)

            # current_value still returns the tier-2 fact (unverified tier-4 is excluded)
            cv = await current_value(
                conn, entity_id, CLIENT_VALUE_PROP, scope=WorkspaceScope.for_workspace(_CLIENT)
            )
            assert cv is not None
            assert cv.value_json == "tier-2 truth"
            assert cv.provenance.source_tier == 2

    run_async(_run())


def test_rerun_bumps_version_and_supersedes() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values(" v1"))
            r1 = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            assert r1.ref.client_kb_version == 1
            entity_id = r1.ref.client_entity_id

            # a fresh run (new run id) with new values
            _bind_firecrawl(_owned_values(" v2"))
            r2 = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            assert r2.ref.client_kb_version == 2
            # re-run resolved to the SAME entity (deterministic on domain)
            assert r2.ref.client_entity_id == entity_id
            assert await current_kb_version(conn, entity_id, workspace_id=_CLIENT) == 2

            scope = WorkspaceScope.for_workspace(_CLIENT)
            cv = await current_value(conn, entity_id, CLIENT_VALUE_PROP, scope=scope)
            assert cv is not None and cv.value_json == "We help teams ship faster v2"

            # both versions' markers remain queryable; the prior one is superseded
            markers = await claims_for(
                conn, entity_id, CLIENT_KB_VERSION, include_superseded=True, scope=ALL_WORKSPACES
            )
            assert len(markers) == 2
            superseded = [m for m in markers if m.superseded_by is not None]
            assert len(superseded) == 1

            # pinning to v1 returns the prior values (append-only audit)
            v1 = await read_client_kb(conn, entity_id, workspace_id=_CLIENT, version=1)
            assert v1[CLIENT_VALUE_PROP] == "We help teams ship faster v1"
            current = await read_client_kb(conn, entity_id, workspace_id=_CLIENT)
            assert current[CLIENT_VALUE_PROP] == "We help teams ship faster v2"

    run_async(_run())


def test_idempotent_reentry_same_run_id() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            deck = VolunteeredMaterial(asserted_fields={CLIENT_PROOF_POINT: "deck proof"})
            r1 = await reverse_profile(conn, _input((deck,)), workspace_id=_CLIENT, run_id=None)
            run_id = r1.run_id
            entity_id = r1.ref.client_entity_id
            before = len(await claims_for(conn, entity_id, scope=ALL_WORKSPACES))

            # re-enter with the SAME run id — no double-write, no version bump
            r2 = await reverse_profile(conn, _input((deck,)), workspace_id=_CLIENT, run_id=run_id)
            after = len(await claims_for(conn, entity_id, scope=ALL_WORKSPACES))
            assert r2.ref.client_kb_version == 1
            assert after == before
            assert await current_kb_version(conn, entity_id, workspace_id=_CLIENT) == 1

    run_async(_run())


def test_budget_cap_halts_gracefully() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            # each scrape step costs 1.0c; a 1.5c cap admits ~one field then stops
            bind_resolver(
                "firecrawl_site",
                FakeResolver(tier=2, values=_owned_values(), cost_cents=Decimal("1.0")),
            )
            result = await reverse_profile(
                conn, _input(), workspace_id=_CLIENT, budget_cap_cents=Decimal("1.5")
            )
            assert result.budget_exhausted is True
            # still a valid, versioned (partial) base
            assert result.ref.client_kb_version == 1
            assert result.coverage.filled_count < len(CLIENT_KNOWLEDGE_FIELDS)
            assert result.coverage.empty_fields  # gaps are visible
            assert result.cost_cents <= Decimal("1.5") + Decimal("1.0")

    run_async(_run())


def test_coverage_reports_unattempted_surfaces_empty() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            # only firecrawl bound → third-party (g2/capterra) + reviews (g2/trustradius) stay empty
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)

            by_surface = {s.surface_class: s for s in result.coverage.surfaces}
            assert by_surface[SurfaceClass.OWNED].filled_fields  # owned filled
            assert by_surface[SurfaceClass.THIRD_PARTY].empty_fields  # no resolver wired
            assert by_surface[SurfaceClass.REVIEWS].empty_fields
            # all four surface classes were attempted
            assert all(s.attempted for s in result.coverage.surfaces)
            assert len(result.coverage.surfaces) == 4

    run_async(_run())


def test_judge_called_on_tier4_client_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            entity_id = result.ref.client_entity_id

            # write a tier-4 client claim under a known run, then run the judge hook over it
            tier4 = make_tier4_claim(entity_id, CLIENT_ICP_EVIDENCE, with_span=True)
            tier4 = stamp_reuse(tier4, workspace_id=_CLIENT, policy=CLIENT_KNOWLEDGE_REUSE_POLICY)
            await insert_claim(conn, tier4, validate_field=False)

            judge = RecordingJudge()
            verdicts = await _judge_tier4_claims(
                conn,
                entity_id,
                run_id=tier4.run_id,
                scope=WorkspaceScope.for_workspace(_CLIENT),
                judge=judge,
            )
            assert len(verdicts) == 1
            assert judge.judged[0].id == tier4.id

    run_async(_run())


def test_rerun_dropping_a_field_clears_it_from_current_kb() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            # v1 fills the full owned set (incl. product)
            _bind_firecrawl(_owned_values(" v1"))
            r1 = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            entity_id = r1.ref.client_entity_id

            # v2 re-derives only value_prop; the scraper no longer returns product (a dropped fact)
            _bind_firecrawl({CLIENT_VALUE_PROP: "value v2"})
            r2 = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            assert r2.ref.client_kb_version == 2

            # the version-scoped canonical read reflects ONLY v2 — product is correctly absent
            current = await read_client_kb(conn, entity_id, workspace_id=_CLIENT)
            assert current[CLIENT_VALUE_PROP] == "value v2"
            assert CLIENT_PRODUCT not in current  # not carried forward as current truth
            # but the prior version remains queryable (append-only audit trail)
            v1 = await read_client_kb(conn, entity_id, workspace_id=_CLIENT, version=1)
            assert v1[CLIENT_PRODUCT] == "A CI platform v1"

    run_async(_run())


def test_no_registrable_domain_client_reuses_entity_on_rerun() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl({CLIENT_VALUE_PROP: "x"})
            # a website with no registrable domain → resolve goes fuzzy; the name-key fallback must
            # still re-find the client's own entity, never spawning a duplicate on re-run.
            ci = ClientInput(name="NoDomain Co", website="nodomain-internal")
            r1 = await reverse_profile(conn, ci, workspace_id=_CLIENT)
            r2 = await reverse_profile(conn, ci, workspace_id=_CLIENT)
            assert r2.ref.client_entity_id == r1.ref.client_entity_id  # single entity, no duplicate
            assert r2.ref.client_kb_version == 2  # same entity, bumped version

    run_async(_run())


def test_outer_budget_precheck_halts_before_next_field() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            # cost 1.0/field, cap 1.0: field 1 runs (inner check 1 > 1 is false), spends 1.0, then
            # the OUTER `spent >= cap` check halts before field 2 is even reached.
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(
                conn, _input(), workspace_id=_CLIENT, budget_cap_cents=Decimal("1.0")
            )
            assert result.budget_exhausted is True
            assert result.coverage.filled_count == 1  # only the first field
            assert result.cost_cents == Decimal("1.0")  # cap not exceeded

    run_async(_run())


def test_trust_order_higher_tier_never_overwritten_by_lower() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            r = await reverse_profile(
                conn, _input(), workspace_id=_CLIENT
            )  # no resolver → entity only
            entity_id = r.ref.client_entity_id

            def _claim(value: str, tier: int, method: ExtractionMethod):  # type: ignore[no-untyped-def]
                c = account_claim(
                    entity_id=entity_id,
                    field_key=CLIENT_VALUE_PROP,
                    value_json=value,
                    source_tier=tier,
                    extraction_method=method,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url=f"https://t{tier}.example",
                )
                return stamp_reuse(c, workspace_id=_CLIENT, policy=CLIENT_KNOWLEDGE_REUSE_POLICY)

            await insert_claim(conn, _claim("tier-3 value", 3, ExtractionMethod.SCRAPE))
            await insert_claim(conn, _claim("tier-1 value", 1, ExtractionMethod.API))
            cv = await current_value(
                conn, entity_id, CLIENT_VALUE_PROP, scope=WorkspaceScope.for_workspace(_CLIENT)
            )
            assert cv is not None
            assert cv.value_json == "tier-1 value"  # trust order: tier-1 wins, never the tier-3
            assert cv.provenance.source_tier == 1

    run_async(_run())


def test_client_claim_stamped_public_is_refused() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            r = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            # a client claim left at the default public_footprint scope is fail-closed at the write
            # boundary (ENG-165) — the field is declared tenant_private.
            leaky = account_claim(
                entity_id=r.ref.client_entity_id,
                field_key=CLIENT_VALUE_PROP,
                value_json="should not leak",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://leak.example",
            )
            assert leaky.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT
            with pytest.raises(ReuseScopeError):
                await insert_claim(conn, leaky)

    run_async(_run())


def test_wrong_typed_volunteered_field_is_skipped_not_fatal() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            # value_prop is a string field; the deck asserts an int (wrong type) plus a valid fact
            deck = VolunteeredMaterial(
                asserted_fields={CLIENT_VALUE_PROP: 123, CLIENT_PROOF_POINT: "valid proof"}
            )
            result = await reverse_profile(conn, _input((deck,)), workspace_id=_CLIENT)
            assert result.ref.client_kb_version == 1  # the run completed, not aborted

            scope = WorkspaceScope.for_workspace(_CLIENT)
            # the bad value_prop was skipped → no tier-1 material claim; the waterfall filled it
            vp = await current_value(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=scope
            )
            assert vp is not None and vp.provenance.source_tier == 2
            # the valid volunteered fact landed as a tier-1 human claim
            pp = await current_value(
                conn, result.ref.client_entity_id, CLIENT_PROOF_POINT, scope=scope
            )
            assert pp is not None and pp.value_json == "valid proof"

    run_async(_run())


def test_client_customer_is_multi_valued_list() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            result = await reverse_profile(conn, _input(), workspace_id=_CLIENT)
            cv = await current_value(
                conn,
                result.ref.client_entity_id,
                CLIENT_CUSTOMER,
                scope=WorkspaceScope.for_workspace(_CLIENT),
            )
            assert cv is not None
            assert isinstance(cv.value_json, list) and len(cv.value_json) == 2  # 1-to-N preserved

    run_async(_run())


def test_per_field_progress_events_are_emitted_in_flight() -> None:
    """D-5 Path B: every field the loop *attempts* announces itself before the lane finishes."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            seen: list[tuple[str, FieldProgressStatus]] = []

            async def record(
                progress_conn: AsyncConnection, field_key: str, status: FieldProgressStatus
            ) -> None:
                # The callback receives the LANE connection — a factory-less emitter writes
                # same-transaction on it (and every test conn-factory shape stays deadlock-free).
                assert progress_conn is conn
                seen.append((field_key, status))

            await reverse_profile(conn, _input(), workspace_id=_CLIENT, on_field_progress=record)

            starts = [k for k, s in seen if s is FieldProgressStatus.STARTED]
            assert starts  # the loop attempted fields, and each announced its start
            assert starts == [k for k in CLIENT_BASELINE_FIELDS if k in starts]  # loop order
            assert len(starts) == len(set(starts))  # exactly one start per attempted field
            for key in starts:
                terminals = [
                    s for k, s in seen if k == key and s is not FieldProgressStatus.STARTED
                ]
                assert len(terminals) == 1
                assert terminals[0] in (FieldProgressStatus.RESOLVED, FieldProgressStatus.EMPTY)

            # honest statuses: a field the fake scraper answered is RESOLVED, an unwired one EMPTY
            resolved = {k for k, s in seen if s is FieldProgressStatus.RESOLVED}
            empty = {k for k, s in seen if s is FieldProgressStatus.EMPTY}
            assert CLIENT_VALUE_PROP in resolved
            assert empty  # third-party/review surfaces have no resolver bound

    run_async(_run())


def test_a_raising_resolver_emits_failed_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blown resolution is announced as FAILED, then still fails the lane (no swallowing)."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            seen: list[tuple[str, FieldProgressStatus]] = []

            async def record(_c: AsyncConnection, field_key: str, s: FieldProgressStatus) -> None:
                seen.append((field_key, s))

            async def boom(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("resolver exploded")

            monkeypatch.setattr(client_kb_module, "resolve_field", boom)
            with pytest.raises(RuntimeError, match="resolver exploded"):
                await reverse_profile(
                    conn, _input(), workspace_id=_CLIENT, on_field_progress=record
                )

            assert len(seen) == 2  # the first field: started, then failed — nothing after
            assert seen[0][1] is FieldProgressStatus.STARTED
            assert seen[1][1] is FieldProgressStatus.FAILED
            assert seen[0][0] == seen[1][0] == CLIENT_BASELINE_FIELDS[0]

    run_async(_run())


def test_unattempted_fields_emit_nothing() -> None:
    """Honest absence: a material-shortcut field and budget-cut fields announce nothing."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            bind_resolver(
                "firecrawl_site",
                FakeResolver(tier=2, values=_owned_values(), cost_cents=Decimal("1.0")),
            )
            deck = VolunteeredMaterial(asserted_fields={CLIENT_VALUE_PROP: "from the deck"})
            seen: list[tuple[str, FieldProgressStatus]] = []

            async def record(_c: AsyncConnection, field_key: str, s: FieldProgressStatus) -> None:
                seen.append((field_key, s))

            result = await reverse_profile(
                conn,
                _input((deck,)),
                workspace_id=_CLIENT,
                budget_cap_cents=Decimal("1.5"),
                on_field_progress=record,
            )

            assert result.budget_exhausted is True
            announced = {k for k, _ in seen}
            # shortcut by the volunteered tier-1 fact — never attempted, so never announced
            assert CLIENT_VALUE_PROP not in announced
            # the budget halt left later fields un-attempted; they announce nothing either
            assert announced < set(CLIENT_BASELINE_FIELDS)

    run_async(_run())


def test_reverse_profile_registers_its_run_in_run_lineage() -> None:
    """FI-2 P2: the Client-KB claims back-join to a workspace-level stage-0 run (no project)."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            run_id = new_run_id()
            await reverse_profile(conn, _input(), workspace_id=_CLIENT, run_id=run_id)

            await assert_written_claims_are_attributable(
                conn, run_id, kind="stage0", workspace_id=_CLIENT, project_id=None
            )
            # Resuming the same run re-registers harmlessly.
            await reverse_profile(conn, _input(), workspace_id=_CLIENT, run_id=run_id)

    run_async(_run())


# --- slice 3: the tier-3 exa_search source is background-lane-only ---------------------------


_COMPETITOR_URL = "https://reviews.example/acme-vs-rival"
_COMPETITOR_TEXT = "Acme Corp and Rival Inc are the two leading CI platforms."


class _ExaBinder:
    """The Stage-0 account-lookup bridge, as the composition roots wire it.

    ``reverse_profile`` only knows the client's account *after* identity resolution, and the
    resolver seam is sync, so the root passes this as ``on_client_resolved``: it accumulates the
    resolved record and (re)binds the tier-3 resolver over a lookup on itself.
    """

    def __init__(self, http: object) -> None:
        self._accounts: dict[object, object] = {}
        self._http = http

    def key_for(self, entity_id: object) -> object | None:
        return self._accounts.get(entity_id)

    def __call__(self, account: object) -> None:
        self._accounts[account.id] = account  # type: ignore[attr-defined]
        register_exa_search_resolver(
            extractor=CallableClaimExtractor(_competitor_drafts),
            accounts=self,  # type: ignore[arg-type]
            secrets=Secrets(_env_file=None, exa_api_key="lane-test"),
            http=self._http,  # type: ignore[arg-type]
        )


class _SearchHttp:
    """A ``get_json`` double returning one on-entity search record, counting every call."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, **kwargs: object) -> object:
        self.calls += 1
        return {
            "results": [{"title": "CI platforms", "url": _COMPETITOR_URL, "text": _COMPETITOR_TEXT}]
        }


def _competitor_drafts(normalized: object, entity: object, field: object) -> list[ClaimDraft]:
    """A canned extractor: one grounded competitor draft, cited to the record it came from."""
    key = field.field_key  # type: ignore[attr-defined]
    text = normalized.text  # type: ignore[attr-defined]
    if key != CLIENT_COMPETITOR or _COMPETITOR_TEXT not in text:
        return []
    return [
        ClaimDraft(
            field_key=key,
            value={"name": "Rival Inc"},
            evidence_span=span_for(text, _COMPETITOR_TEXT),
            confidence=0.8,
            source_url=_COMPETITOR_URL,
        )
    ]


def test_exa_search_is_skipped_by_the_fast_lane_and_paid_only_by_the_background_lane() -> None:
    """The tier gate is what keeps interactive onboarding free.

    The fast lane caps at ``max_source_tier=2``: the tier-3 source is refused BEFORE a request is
    issued, so ``client.competitor`` stays honestly empty at zero spend. The background lane
    (``max_source_tier=3``) is the only one that pays — and then the field fills with a grounded,
    cited tier-3 claim.
    """

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            http = _SearchHttp()
            binder = _ExaBinder(http)

            fast = await reverse_profile(
                conn,
                _input(),
                workspace_id=_CLIENT,
                max_source_tier=2,
                on_client_resolved=binder,
            )
            assert http.calls == 0  # gate-skipped before the provider call
            assert fast.cost_cents == Decimal(0)
            scope = WorkspaceScope.for_workspace(_CLIENT)
            assert (
                await current_value(conn, fast.ref.client_entity_id, CLIENT_COMPETITOR, scope=scope)
                is None
            )

            background = await reverse_profile(
                conn,
                _input(),
                workspace_id=_CLIENT,
                max_source_tier=3,
                on_client_resolved=binder,
            )
            # both tier-3 client fields were researched; only the competitor one yielded a value
            assert http.calls == 2
            assert background.cost_cents > Decimal(0)
            cv = await current_value(
                conn, background.ref.client_entity_id, CLIENT_COMPETITOR, scope=scope
            )
            assert cv is not None
            assert cv.value_json == {"name": "Rival Inc"}
            assert cv.provenance.source_tier == 3
            (claim,) = await claims_for(
                conn, background.ref.client_entity_id, CLIENT_COMPETITOR, scope=ALL_WORKSPACES
            )
            assert claim.source_key == "exa_search"  # engine-stamped
            assert claim.extraction_method is ExtractionMethod.API
            assert claim.source_url == _COMPETITOR_URL
            assert claim.evidence_span == _COMPETITOR_TEXT
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE

    run_async(_run())


class _RefusingHttp:
    """A ``get_json`` double that answers every search with a hard 402 (credits exhausted)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, **kwargs: object) -> object:
        self.calls += 1
        raise ProviderResponseError(
            "exa_search: HTTP 402", status_code=402, body_excerpt="out of credits"
        )


def test_a_refusing_exa_search_empties_its_own_fields_and_leaves_the_run_intact() -> None:
    """The rest of the review-fix invariant, at lane level.

    The composition root refuses to bind this source without a credential — but a key can be
    revoked or run out of credits *after* boot, and that arrives as a hard 4xx mid-run. A resolver
    exception is re-raised by the waterfall and again here, so an escaping 402 would destroy an
    entire onboarding run over one optional open-web enrichment. Instead the two tier-3 fields end
    empty, every other field is untouched, and the run completes with its version marker.
    """

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            _bind_firecrawl(_owned_values())
            http = _RefusingHttp()
            result = await reverse_profile(
                conn,
                _input(),
                workspace_id=_CLIENT,
                max_source_tier=3,
                on_client_resolved=_ExaBinder(http),
            )

            assert http.calls == 2  # both tier-3 fields tried, both refused
            assert result.ref.client_kb_version == 1  # the run COMPLETED
            scope = WorkspaceScope.for_workspace(_CLIENT)
            # the refused fields are honestly empty …
            assert (
                await current_value(
                    conn, result.ref.client_entity_id, CLIENT_COMPETITOR, scope=scope
                )
                is None
            )
            # … and every tier-2 field the same run resolved is unaffected
            cv = await current_value(
                conn, result.ref.client_entity_id, CLIENT_VALUE_PROP, scope=scope
            )
            assert cv is not None
            assert cv.value_json == "We help teams ship faster"

    run_async(_run())
