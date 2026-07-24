"""M6.2 (ENG-133) — the existence/identity gate, against a live Postgres.

One test per acceptance criterion: admit a real candidate (entity + one provenance claim); dedup to
an existing entity via the strong key; reject a fabricated candidate (no entity, no claim); route a
mid-band match to the review queue; idempotent re-admission; same-domain → single entity; and the
import-symmetry contract.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    ClaimFlavor,
    EntityId,
    ExtractionMethod,
    ResearchMode,
    new_run_id,
)
from clue_research.claimstore import ALL_WORKSPACES, claims_for
from clue_research.discovery_scoring import AdmissionStatus, ExistenceVerdict, admit
from clue_research.discovery_scoring.gate.admission import DISCOVERY_PROVENANCE_FIELD
from clue_research.identity import (
    DispositionPolicy,
    embed_account,
    get_account,
    insert_account_entity,
    list_open_tasks,
)
from tests._workspace import DEFAULT_TEST_WORKSPACE as WS
from tests._workspace import seed_workspace

from .conftest import candidate, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_discovery_db")


async def _seed(conn: AsyncConnection, **kwargs: object) -> EntityId:
    """Insert + embed an account so the probabilistic resolver can find it (mirrors M2.3 tests)."""
    eid = await insert_account_entity(conn, workspace_id=WS, **kwargs)  # type: ignore[arg-type]
    await embed_account(conn, eid)
    return eid


async def _count_accounts(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_entity"))).scalar_one())


async def _provenance_claims(conn: AsyncConnection, entity_id: EntityId) -> list[object]:
    return list(await claims_for(conn, entity_id, DISCOVERY_PROVENANCE_FIELD, scope=ALL_WORKSPACES))


def test_admit_real_candidate_creates_entity_and_one_provenance_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await admit(
                conn,
                candidate(
                    matched_channel="exa", domain="totallynew.example", name="Totally New Co"
                ),
                new_run_id(),
                workspace_id=WS,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            assert result.discovery_provenance_claim_id is not None

            account = await get_account(conn, result.account_entity_id)
            assert account is not None and account.status is AccountStatus.CANDIDATE

            claims = await _provenance_claims(conn, result.account_entity_id)
            assert len(claims) == 1
            claim = claims[0]
            assert claim.claim_flavor is ClaimFlavor.DISCOVERY  # type: ignore[attr-defined]
            provenance = claim.discovery_provenance  # type: ignore[attr-defined]
            assert provenance is not None
            assert provenance.found_via == "exa"
            assert provenance.matched_signal == "series-b saas"
            assert provenance.research_mode is ResearchMode.ACCOUNT_DISCOVERY

    run_async(_run())


def test_admit_dedups_to_existing_entity_via_strong_key() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acme = await _seed(conn, canonical_name="Acme", primary_domain="acme.com")
            before = await _count_accounts(conn)
            result = await admit(
                conn, candidate(domain="acme.com", name="Acme Inc"), new_run_id(), workspace_id=WS
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id == acme  # auto-merged onto the existing entity
            assert await _count_accounts(conn) == before  # no new account created
            assert len(await _provenance_claims(conn, acme)) == 1

    run_async(_run())


def test_admit_rejects_fabricated_candidate_with_no_entity_and_no_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            before = await _count_accounts(conn)
            # grounded by a record ref (passes M6.1) but nothing to resolve to (no domain, no name)
            result = await admit(
                conn,
                candidate(matched_channel="exa", record_ref="ghost:1", domain=None, name=None),
                new_run_id(),
                workspace_id=WS,
            )
            assert result.status is AdmissionStatus.REJECTED
            assert result.account_entity_id is None
            assert result.discovery_provenance_claim_id is None
            assert (
                await _count_accounts(conn) == before
            )  # the fabricated candidate died at the gate

    run_async(_run())


def test_admit_mid_band_routes_to_review_and_admits_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _seed(conn, canonical_name="Acme Corporation")  # name-only, embedded
            before = await _count_accounts(conn)
            # a fuzzy name match (no strong key) lands in the review band under this policy
            policy = DispositionPolicy(
                version=9, review_low_threshold=0.3, auto_merge_threshold=0.99
            )
            result = await admit(
                conn,
                candidate(matched_channel="exa", name="Acme Corporation"),
                new_run_id(),
                workspace_id=WS,
                disposition_policy=policy,
            )
            assert result.status is AdmissionStatus.NEEDS_REVIEW
            assert result.review_task_id is not None
            assert result.account_entity_id is None
            tasks = await list_open_tasks(conn)
            assert any(task.id == result.review_task_id for task in tasks)
            assert await _count_accounts(conn) == before  # nothing admitted (never guessed)

    run_async(_run())


def test_admit_is_idempotent_on_reattempt() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run_id = new_run_id()
            hypothesis = candidate(matched_channel="exa", domain="acme.com", name="Acme")
            first = await admit(conn, hypothesis, run_id, workspace_id=WS)
            second = await admit(conn, hypothesis, run_id, workspace_id=WS)  # M7 replay
            assert first.status is second.status is AdmissionStatus.ADMITTED
            assert first.account_entity_id == second.account_entity_id
            # the same provenance claim is reused — no duplicate written
            assert first.discovery_provenance_claim_id == second.discovery_provenance_claim_id
            assert first.account_entity_id is not None
            assert len(await _provenance_claims(conn, first.account_entity_id)) == 1

    run_async(_run())


def test_two_admissions_of_the_same_domain_produce_one_entity() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            before = await _count_accounts(conn)
            first = await admit(
                conn,
                candidate(matched_channel="exa", domain="acme.com", name="Acme"),
                new_run_id(),
                workspace_id=WS,
            )
            second = await admit(
                conn,
                candidate(matched_channel="apollo", domain="acme.com", name="Acme Inc"),
                new_run_id(),
                workspace_id=WS,
            )
            assert (
                first.account_entity_id == second.account_entity_id
            )  # single entity, no double-admit
            assert await _count_accounts(conn) == before + 1  # exactly one account created

    run_async(_run())


def test_admit_import_is_symmetric_with_discovery() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await admit(
                conn,
                candidate(matched_channel="import", domain="imported.example", name="Imported Co"),
                new_run_id(),
                workspace_id=WS,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            (claim,) = await _provenance_claims(conn, result.account_entity_id)
            provenance = claim.discovery_provenance  # type: ignore[attr-defined]
            # indistinguishable from a discovered account except by the channel + tier-1 crm method
            assert provenance is not None and provenance.found_via == "import"
            assert claim.extraction_method is ExtractionMethod.CRM_IMPORT  # type: ignore[attr-defined]
            assert claim.source_tier == 1  # type: ignore[attr-defined]

    run_async(_run())


def test_admit_under_redis_lock_dedups_to_single_entity() -> None:
    """The in-flight Redis lock path admits and serializes same-company admits onto one entity
    (needs Redis — skips otherwise; true parallelism is backstopped by the DB strong-key unique
    constraint + the M2.4 lock tests)."""

    async def _run() -> None:
        from clue_locks import create_redis

        client = create_redis()
        try:
            await client.ping()
        except Exception:
            await client.aclose()
            pytest.skip("CLUE_REDIS_URL unset or Redis unreachable; run `make redis-up`")
        try:
            async with rollback_conn() as conn:
                before = await _count_accounts(conn)
                first = await admit(
                    conn,
                    candidate(domain="locked.example", name="Locked Co"),
                    new_run_id(),
                    workspace_id=WS,
                    redis=client,
                )
                second = await admit(
                    conn,
                    candidate(matched_channel="apollo", domain="locked.example", name="Locked Inc"),
                    new_run_id(),
                    workspace_id=WS,
                    redis=client,
                )
                assert first.status is AdmissionStatus.ADMITTED
                assert first.account_entity_id == second.account_entity_id  # one entity under lock
                assert await _count_accounts(conn) == before + 1
        finally:
            await client.aclose()

    run_async(_run())


def test_admit_stamps_candidate_workspace() -> None:
    """A freshly-admitted account is stamped with the caller's workspace (accounts are
    workspace-local — [B3×research]): the new entity's ``workspace_id`` equals the admitting ws."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn)
            result = await admit(
                conn,
                candidate(matched_channel="exa", domain="stamped.example", name="Stamped Co"),
                new_run_id(),
                workspace_id=ws,
            )
            assert result.status is AdmissionStatus.ADMITTED
            assert result.account_entity_id is not None
            account = await get_account(conn, result.account_entity_id)
            assert account is not None
            assert account.workspace_id == ws

    run_async(_run())


def test_domain_lock_id_is_workspace_partitioned() -> None:
    """The admit-lock id folds in the workspace, so two workspaces admitting the *same* domain get
    different lock ids (no needless cross-tenant serialization — accounts are workspace-local,
    [B3×research]), while the same ``(workspace, domain)`` is deterministic/stable."""
    from clue_research.discovery_scoring.gate.admission import _domain_lock_id

    a = _domain_lock_id("ws-a", "acme.com")
    assert _domain_lock_id("ws-b", "acme.com") != a  # different ws, same domain → distinct lock
    assert _domain_lock_id("ws-a", "acme.com") == a  # same (ws, domain) → stable
    assert _domain_lock_id("ws-a", "beta.com") != a  # same ws, different domain → distinct lock


def test_existence_check_is_a_pluggable_gate() -> None:
    """A custom existence check can reject even a well-formed candidate (the live-domain seam)."""

    class _RejectAll:
        async def check(self, _candidate: object) -> ExistenceVerdict:
            return ExistenceVerdict(exists=False, reason="domain not live")

    async def _run() -> None:
        async with rollback_conn() as conn:
            before = await _count_accounts(conn)
            result = await admit(
                conn,
                candidate(domain="acme.com", name="Acme"),
                new_run_id(),
                workspace_id=WS,
                existence=_RejectAll(),
            )
            assert result.status is AdmissionStatus.REJECTED
            assert result.reason == "domain not live"
            assert await _count_accounts(conn) == before

    run_async(_run())
